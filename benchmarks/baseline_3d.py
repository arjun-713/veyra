"""Measured sparse 3D baseline: voxel-hash occupancy at 5 cm.

Smallest honest MEASURED counterpart to the ANALYTICAL-only
``reference_baselines.uniform_5cm_3d`` dense-grid estimate in
``benchmarks/run_benchmark.py``. That reference is deliberately never
allocated or timed (dense 5 cm voxels over a ~200 m span); closure needs a
sparse high-resolution 3D reference that actually runs on the same input
and reports RSS / allocated bytes / latency / element count.

Method
------
* Same input path as the closure benchmark: ``load_selection`` (adapter +
  checked-in perception pipeline, 100 m envelope) over SemanticPOSS seq 00,
  frames 0-29. XYZ is world-frame; perception preserves XYZ exactly, so the
  voxelized coordinates are the staged-stream coordinates. The binary stream
  digest is recomputed over the retained frames and compared against the
  closure digest ``4cd60ac5``.
* Representation: pure occupancy set of packed 5 cm voxel keys
  (``floor(x/0.05)`` per axis, biased into one 63-bit int). First-seen
  wins; no per-voxel statistics, no eviction. This is a reference, not a
  mapper: it answers "how much does it cost to touch every occupied 5 cm
  voxel once" and nothing else.
* Measurement scope (mirrors the ``map_update`` stage): per-frame latency
  covers voxelize + hash-insert only. Dataset load and perception are
  timed separately and excluded.
* Memory accounting (NOT malloc-hooked): ``allocated = N * 32`` bytes
  (8 B packed key + 8 B occupancy/count payload + 16 B open-addressing
  slot overhead for a typical dense hash table). The Python ``set`` object
  overhead is excluded from the accounted figure; process-level cost is
  reported separately as peak RSS, which includes the interpreter.
* Peak RSS: ``max(ru_maxrss, /proc/self/status VmHWM)`` sampled after the
  voxel loop (ru_maxrss is monotonic process peak; includes interpreter +
  retained frames, stated explicitly).

Reuse, not a fork: analytical bounds, percentile convention, tail
reliability, frame loading, and the RSS convention are imported from
``benchmarks/run_benchmark.py`` / ``benchmarks/regression.py``.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.protocol import binary_stream_file  # noqa: E402
from benchmarks.regression import max_rss_bytes  # noqa: E402
from benchmarks.run_benchmark import (  # noqa: E402
    analytical_3d_reference_bounds,
    load_selection,
    nearest_rank_summary,
    tail_reliability,
)

VOXEL_SIZE_M = 0.05
# 8 B packed key + 8 B payload + 16 B hash-slot overhead. Documented
# accounting unit, not a malloc hook (see module docstring).
BYTES_PER_ENTRY = 32
_BIAS = 1 << 20  # covers +/- ~52 km at 5 cm; real spans are ~+/-100 m
EXPECTED_DIGEST_PREFIX = "4cd60ac5"


def pack_voxel_keys(indices: np.ndarray) -> np.ndarray:
    """Pack (N,3) int64 voxel indices into one uint64 key per voxel."""
    biased = indices.astype(np.int64, copy=False) + _BIAS
    if np.any(biased < 0) or np.any(biased >= (1 << 21)):
        raise ValueError("voxel index outside 21-bit packing range")
    packed = (
        (biased[:, 0].astype(np.uint64) << 42)
        | (biased[:, 1].astype(np.uint64) << 21)
        | biased[:, 2].astype(np.uint64)
    )
    return packed


def unpack_voxel_keys(packed: np.ndarray) -> np.ndarray:
    """Inverse of :func:`pack_voxel_keys` (used by unit tests)."""
    packed = np.asarray(packed, dtype=np.uint64)
    indices = np.empty((packed.shape[0], 3), dtype=np.int64)
    indices[:, 0] = ((packed >> 42) & np.uint64((1 << 21) - 1)).astype(np.int64) - _BIAS
    indices[:, 1] = ((packed >> 21) & np.uint64((1 << 21) - 1)).astype(np.int64) - _BIAS
    indices[:, 2] = (packed & np.uint64((1 << 21) - 1)).astype(np.int64) - _BIAS
    return indices


def frame_voxel_keys(points_xyz: np.ndarray) -> np.ndarray:
    """Unique packed 5 cm voxel keys occupied by one frame's XYZ points."""
    xyz = np.asarray(points_xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] < 3 or xyz.shape[0] == 0:
        raise ValueError("frame voxelization requires non-empty XYZ points")
    if not np.isfinite(xyz[:, :3]).all():
        raise ValueError("frame points must be finite")
    indices = np.floor(xyz[:, :3] / VOXEL_SIZE_M).astype(np.int64)
    return np.unique(pack_voxel_keys(indices))


def vmhwm_bytes() -> int | None:
    """Peak RSS from /proc/self/status (VmHWM), or None if unavailable."""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def peak_rss_bytes() -> dict[str, int | None]:
    """Process peak RSS via ru_maxrss and VmHWM; peak is the max of both."""
    ru_max = max_rss_bytes()
    hwm = vmhwm_bytes()
    candidates = [value for value in (ru_max, hwm) if value is not None]
    return {
        "ru_maxrss_bytes": ru_max,
        "vmhwm_bytes": hwm,
        "peak_rss_bytes": max(candidates) if candidates else None,
    }


class SparseVoxelBaseline:
    """Accumulating 5 cm occupancy set with per-frame insert latency."""

    def __init__(self) -> None:
        self.voxels: set[int] = set()
        self.insert_latency_ns: list[int] = []
        self.per_frame_new_voxels: list[int] = []
        self.per_frame_points: list[int] = []

    def insert_frame(self, points_xyz: np.ndarray) -> int:
        """Insert one frame; returns new voxels. Times voxelize+insert."""
        started = time.perf_counter_ns()
        keys = frame_voxel_keys(points_xyz)
        before = len(self.voxels)
        self.voxels.update(int(key) for key in keys.tolist())
        elapsed = time.perf_counter_ns() - started
        self.insert_latency_ns.append(elapsed)
        self.per_frame_new_voxels.append(len(self.voxels) - before)
        self.per_frame_points.append(int(np.asarray(points_xyz).shape[0]))
        return self.per_frame_new_voxels[-1]

    @property
    def accounted_bytes(self) -> int:
        return len(self.voxels) * BYTES_PER_ENTRY


def mem_total_bytes() -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def git_sha(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_baseline(args: argparse.Namespace, repo: Path) -> dict:
    base_rss = peak_rss_bytes()
    load_started_ns = time.perf_counter_ns()
    frames, _distance_config, entry, perception_ns, window_radius_m = load_selection(
        repo,
        args.dataset,
        args.sequence,
        args.start,
        args.count,
        run_perception=not args.skip_perception,
        perception_config=Path(args.perception_config)
        if Path(args.perception_config).is_absolute()
        else repo / args.perception_config,
        dataset_root=Path(args.dataset_root) if args.dataset_root else None,
    )
    load_elapsed_ns = time.perf_counter_ns() - load_started_ns

    point_count = sum(len(frame.points) for frame in frames)
    min_xyz = np.min(
        [np.asarray(f.points[:, :3], dtype=np.float64).min(axis=0) for f in frames],
        axis=0,
    )
    max_xyz = np.max(
        [np.asarray(f.points[:, :3], dtype=np.float64).max(axis=0) for f in frames],
        axis=0,
    )

    with tempfile.TemporaryDirectory(prefix="veyra-baseline-3d-stream-") as directory:
        digest = binary_stream_file(
            iter(frames), Path(directory) / "observations.stream"
        )

    baseline = SparseVoxelBaseline()
    for frame in frames:
        baseline.insert_frame(np.asarray(frame.points[:, :3], dtype=np.float64))
    rss = peak_rss_bytes()

    analytical = analytical_3d_reference_bounds(min_xyz, max_xyz)
    latency = nearest_rank_summary([float(v) for v in baseline.insert_latency_ns])
    latency_ms = {
        key: (value / 1e6 if key != "count" else value)
        for key, value in latency.items()
    }
    accounted = baseline.accounted_bytes
    dense_bytes = analytical["estimated_dense_bytes"]
    return {
        "schema": "veyra-baseline-3d/1",
        "status": "measured",
        "representation": "sparse_voxel_hash_occupancy_5cm",
        "voxel_size_m": VOXEL_SIZE_M,
        "input": {
            "dataset": args.dataset,
            "sequence": args.sequence,
            "start": args.start,
            "count": args.count,
            "frames_voxelized": len(frames),
            "point_count": point_count,
            "window_radius_m": window_radius_m,
            "perception_executed": not args.skip_perception,
            "perception_latency_ns": (
                nearest_rank_summary([float(v) for v in perception_ns])
                if perception_ns
                else None
            ),
            "load_latency_ns": load_elapsed_ns,
            "dataset_root": (
                str(Path(args.dataset_root).resolve()) if args.dataset_root else entry.get("root")
            ),
            "stream_digest": digest,
            "stream_digest_matches_closure_4cd60ac5": digest.startswith(
                EXPECTED_DIGEST_PREFIX
            ),
            "expected_digest_prefix": EXPECTED_DIGEST_PREFIX,
            "bounds_min_m": min_xyz.tolist(),
            "bounds_max_m": max_xyz.tolist(),
        },
        "measurement_scope": (
            "per-frame update latency covers voxelize (floor+pack+unique) + "
            "hash-insert only; dataset load and perception are timed "
            "separately and excluded, mirroring the map_update stage scope"
        ),
        "update_latency_ns": latency,
        "update_latency_ms": latency_ms,
        "tail_reliability": tail_reliability(len(frames)),
        "elements": {
            "occupied_voxels": len(baseline.voxels),
            "per_frame_new_voxels": baseline.per_frame_new_voxels,
            "per_frame_points": baseline.per_frame_points,
        },
        "memory_accounting": {
            "method": (
                "accounted, not malloc-hooked: occupied_voxels * 32 B "
                "(8 B packed key + 8 B occupancy/count payload + 16 B "
                "open-addressing hash-slot overhead). Python set object "
                "overhead is excluded from this figure; process-level cost "
                "is reported separately as peak RSS."
            ),
            "bytes_per_entry": BYTES_PER_ENTRY,
            "accounted_bytes": accounted,
        },
        "rss": {
            **rss,
            "base_ru_maxrss_bytes_before_voxel_loop": base_rss["peak_rss_bytes"],
            "note": (
                "process peak incl. interpreter + retained frames + voxel "
                "set; accounted voxel bytes are the comparator against the "
                "analytical dense estimate, not RSS"
            ),
        },
        "analytical_3d_reference": analytical,
        "comparison": {
            "dense_voxels_analytical": analytical["dense_voxel_count"],
            "occupied_voxels_measured": len(baseline.voxels),
            "sparsity_occupied_over_dense": (
                len(baseline.voxels) / analytical["dense_voxel_count"]
                if analytical["dense_voxel_count"]
                else None
            ),
            "estimated_dense_bytes_analytical": dense_bytes,
            "accounted_sparse_bytes_measured": accounted,
            "bytes_ratio_measured_over_analytical": (
                accounted / dense_bytes if dense_bytes else None
            ),
            "peak_rss_bytes_measured": rss["peak_rss_bytes"],
            "table_markdown": "",
        },
        "provenance": {
            "git_sha": git_sha(repo),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "host": platform.node(),
            "platform": platform.platform(),
            "cpu_count": __import__("os").cpu_count(),
            "mem_total_bytes": mem_total_bytes(),
            "python": platform.python_version(),
            "voxel_size_m": VOXEL_SIZE_M,
        },
    }


def render_table(result: dict) -> str:
    comparison = result["comparison"]
    latency = result["update_latency_ms"]
    rss = result["rss"]
    lines = [
        "| quantity | ANALYTICAL (dense, never allocated/timed) | MEASURED (sparse voxel-hash) |",
        "| --- | --- | --- |",
        f"| representation | dense_uniform_3d_voxels | sparse_voxel_hash_occupancy_5cm |",
        f"| voxel size | 0.05 m | {result['voxel_size_m']} m |",
        f"| elements | {comparison['dense_voxels_analytical']} dense voxels | "
        f"{comparison['occupied_voxels_measured']} occupied voxels |",
        f"| memory | {comparison['estimated_dense_bytes_analytical']} B estimated | "
        f"{comparison['accounted_sparse_bytes_measured']} B accounted "
        f"(ratio {comparison['bytes_ratio_measured_over_analytical']:.6f}) |",
        f"| peak RSS | n/a (never ran) | {rss['peak_rss_bytes']} B "
        f"(process peak, incl. interpreter) |",
        f"| update latency p50/p95/p99 | n/a (never ran) | "
        f"{latency['p50']:.3f}/{latency['p95']:.3f}/{latency['p99']:.3f} ms "
        f"(n={latency['count']}) |",
        f"| sparsity occupied/dense | — | "
        f"{comparison['sparsity_occupied_over_dense']:.6f} |",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dataset", default="semanticposs")
    parser.add_argument("--sequence", default="00")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--skip-perception", action="store_true")
    parser.add_argument("--perception-config", default="configs/perception.yaml")
    parser.add_argument(
        "--output",
        default="reports/closure/baseline-3d/MEASURED.json",
        help="Relative paths resolve against --repo",
    )
    args = parser.parse_args()
    repo = Path(args.repo)
    try:
        result = run_baseline(args, repo)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"veyra baseline-3d: {error}", file=sys.stderr)
        return 2
    result["comparison"]["table_markdown"] = render_table(result)
    output = Path(args.output)
    if not output.is_absolute():
        output = repo / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["comparison"]["table_markdown"])
    print(f"wrote {output}")
    print(
        f"stream_digest={result['input']['stream_digest']} "
        f"match_closure_4cd60ac5={result['input']['stream_digest_matches_closure_4cd60ac5']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
