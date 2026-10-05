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
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.protocol import binary_stream_file
from benchmarks.regression import max_rss_bytes
from benchmarks.run_benchmark import (
    _host_memory_bytes,
    analytical_3d_reference_bounds,
    host_cpu_model,
    load_selection,
    nearest_rank_summary,
    tail_reliability,
)

# Voxel key packing and the 32 B/entry accounting unit are shared with the
# in-benchmark storage comparison (benchmarks/storage_3d.py).
from benchmarks.storage_3d import (
    BYTES_PER_ENTRY,
    VOXEL_SIZE_M,
    frame_voxel_keys,
    pack_voxel_keys as pack_voxel_keys,  # re-exported for callers and tests
    unpack_voxel_keys as unpack_voxel_keys,  # re-exported
)

EXPECTED_DIGEST_PREFIX = "4cd60ac5"


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
        pass
    # No /proc (macOS): physical pages x page size, as the OS reports them.
    return _host_memory_bytes()


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


def git_dirty(repo: Path) -> bool | None:
    """True when the worktree has uncommitted changes; None if git is unusable."""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256_file(path: Path) -> str | None:
    """Hex sha256 of a file, or None when the file is absent/unreadable."""
    import hashlib

    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def cpu_model() -> str | None:
    return host_cpu_model()


def gpu_info() -> dict[str, str | None]:
    """Best-effort GPU identity; null name when no NVIDIA GPU is visible.

    The baseline itself runs CPU-only (numpy); this block exists so a
    reproducer can confirm the hardware matches, not because the GPU is used.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return {"name": "; ".join(names) if names else None, "note": "nvidia-smi"}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {
            "name": None,
            "note": "no discrete GPU visible (nvidia-smi absent/failed); "
            "baseline runs CPU-only",
        }


def collect_provenance(
    repo: Path,
    args: argparse.Namespace,
    *,
    frames_voxelized: int,
    point_count: int,
) -> dict:
    """Complete provenance block: every key a reproducer needs to match hardware,
    source data, config, and code identity. No dataset access required."""
    perception_config = (
        Path(args.perception_config)
        if Path(args.perception_config).is_absolute()
        else repo / args.perception_config
    )
    try:
        perception_config_rel = str(perception_config.relative_to(repo))
    except ValueError:
        perception_config_rel = str(perception_config)
    return {
        "git_sha": git_sha(repo),
        "git_dirty": git_dirty(repo),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": platform.node(),
        "platform": platform.platform(),
        "os": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or cpu_model(),
        },
        "cpu_count": __import__("os").cpu_count(),
        "cpu_model": cpu_model(),
        "gpu": gpu_info(),
        "mem_total_bytes": mem_total_bytes(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "dataset": args.dataset,
        "sequence": args.sequence,
        "start_frame": args.start,
        "frame_count": args.count,
        "frames_voxelized": frames_voxelized,
        "point_count": point_count,
        "dataset_root": str(Path(args.dataset_root).resolve())
        if args.dataset_root
        else None,
        "build": {
            "type": "pure_python_no_cpp",
            "cpp_mapper_binary_used": False,
            "note": "baseline_3d.py uses numpy only; no cmake/cargo "
            "artifact is built or executed",
        },
        "config": {
            "perception_config": perception_config_rel,
            "perception_sha256": sha256_file(perception_config),
            "perception_executed": not args.skip_perception,
        },
        "policy": {
            "leg": "measured_3d",
            "representation": "sparse_voxel_hash_occupancy_5cm",
            "voxel_size_m": VOXEL_SIZE_M,
            "suite": "reference",
        },
        "voxel_size_m": VOXEL_SIZE_M,
    }


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

    cumulative = 0
    frame_rows: list[dict[str, int]] = []
    for index, (points, new_voxels, latency_ns) in enumerate(
        zip(
            baseline.per_frame_points,
            baseline.per_frame_new_voxels,
            baseline.insert_latency_ns,
        )
    ):
        cumulative += new_voxels
        frame_rows.append(
            {
                "frame_index": args.start + index,
                "points": points,
                "new_voxels": new_voxels,
                "cumulative_voxels": cumulative,
                "insert_latency_ns": latency_ns,
            }
        )

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
                str(Path(args.dataset_root).resolve())
                if args.dataset_root
                else entry.get("root")
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
            "per_frame_insert_latency_ns": list(baseline.insert_latency_ns),
            "frames": frame_rows,
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
        "provenance": collect_provenance(
            repo,
            args,
            frames_voxelized=len(frames),
            point_count=point_count,
        ),
    }


def render_table(result: dict) -> str:
    comparison = result["comparison"]
    latency = result["update_latency_ms"]
    rss = result["rss"]
    lines = [
        "| quantity | ANALYTICAL (dense, never allocated/timed) | MEASURED (sparse voxel-hash) |",
        "| --- | --- | --- |",
        "| representation | dense_uniform_3d_voxels | sparse_voxel_hash_occupancy_5cm |",
        f"| voxel size | 0.05 m | {result['voxel_size_m']} m |",
        (
            f"| elements | {comparison['dense_voxels_analytical']} dense voxels | "
            f"{comparison['occupied_voxels_measured']} occupied voxels |"
        ),
        (
            f"| memory | {comparison['estimated_dense_bytes_analytical']} B estimated | "
            f"{comparison['accounted_sparse_bytes_measured']} B accounted "
            f"(ratio {comparison['bytes_ratio_measured_over_analytical']:.6f}) |"
        ),
        (
            f"| peak RSS | n/a (never ran) | {rss['peak_rss_bytes']} B "
            "(process peak, incl. interpreter) |"
        ),
        (
            f"| update latency p50/p95/p99 | n/a (never ran) | "
            f"{latency['p50']:.3f}/{latency['p95']:.3f}/{latency['p99']:.3f} ms "
            f"(n={latency['count']}) |"
        ),
        (
            f"| sparsity occupied/dense | — | "
            f"{comparison['sparsity_occupied_over_dense']:.6f} |"
        ),
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
