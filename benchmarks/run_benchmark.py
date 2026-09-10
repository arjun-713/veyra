"""Run reproducible, multi-frame Veyra policy benchmarks on local data only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from benchmarks.protocol import PROTOCOL_VERSION, stream_bytes
from datasets.rellis import Rellis3DDataset
from datasets.semanticposs import SemanticPOSSDataset
from perception.pipeline import PerceptionPipeline

SCHEMA_VERSION = 2


@dataclass(frozen=True)
class PolicyAdapter:
    name: str
    cpp_policy: str | None
    available: bool
    integration_note: str


POLICY_ADAPTERS = {
    "uniform5": PolicyAdapter("uniform5", "uniform5", True, "public adapter available"),
    "uniform40": PolicyAdapter(
        "uniform40", "uniform40", True, "public adapter available"
    ),
    "distance_lod": PolicyAdapter(
        "distance_lod", "distance_lod", True, "public adapter available"
    ),
    "utility_lod": PolicyAdapter(
        "utility_lod",
        "utility_lod",
        True,
        "stateful public map/policy adapter available",
    ),
}


def nearest_rank_summary(samples: list[int | float]) -> dict[str, int | float]:
    """Same nearest-rank p50/p95/p99 convention as the C++ collector."""
    if not samples:
        raise ValueError("cannot summarize an empty sample set")
    ordered = sorted(samples)

    def rank(percentile: float) -> int | float:
        return ordered[
            max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
        ]

    return {
        "count": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "p50": rank(0.50),
        "p95": rank(0.95),
        "p99": rank(0.99),
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _host_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def hardware_metadata(profile: str) -> dict[str, Any]:
    """Capture runtime provenance; config profiles never invent hardware values."""
    cpu_model = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "profile": profile,
        "capture": "runtime",
        "os": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": cpu_model or platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": _host_memory_bytes(),
    }


def validate_hardware_profile(config: object, profile: str) -> None:
    if not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("configs/hardware_profiles.yaml must use schema_version 2")
    profiles = config.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("configs/hardware_profiles.yaml must define profiles")  # noqa: TRY004
    matched = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("name") == profile
    ]
    if len(matched) != 1 or matched[0].get("capture") != "runtime":
        raise ValueError(
            f"hardware profile must be one runtime-capture profile: {profile}"
        )


def compute_window_radius_m(frames: list[Any], configured_radius_m: float) -> float:
    """Return the smallest common world-frame window that contains all input."""
    required = float(configured_radius_m)
    for frame in frames:
        distance = np.hypot(
            frame.points[:, 0] - frame.pose.matrix[0, 3],
            frame.points[:, 1] - frame.pose.matrix[1, 3],
        )
        if distance.size:
            required = max(required, float(np.max(distance)))
    # The selected points are float32 while C++ parses decimal float64. Keep a
    # recorded 1 mm containment margin so a point exactly on the source crop
    # boundary is not rejected by representation-level roundoff.
    return required + 0.001


def _normalized_distance_config(distance_config: object) -> dict[str, Any]:
    """Normalize legacy detailed and current compact DistanceLOD configuration."""
    if not isinstance(distance_config, dict):
        raise ValueError("configs/distance_lod.yaml must contain a mapping")  # noqa: TRY004
    if "ranges_m" not in distance_config:
        boundaries = distance_config.get("distance_boundaries_m")
        maximum = distance_config.get("max_range_m")
        if distance_config.get("mode") != "distance_lod":
            raise ValueError("compact distance_lod mode must be distance_lod")
        if not isinstance(boundaries, list) or tuple(map(float, boundaries)) != (
            10.0,
            30.0,
            60.0,
        ):
            raise ValueError("compact distance_lod boundaries must be 10,30,60 m")
        if float(maximum) != 100.0:
            raise ValueError("compact distance_lod max range must be 100 m")
        return {
            "levels": [0.05, 0.10, 0.20, 0.40],
            "ranges_m": [[0.0, 10.0], [10.0, 30.0], [30.0, 60.0], [60.0, 100.0]],
            "frame": "odom",
            "source_schema": "compact",
        }
    return dict(distance_config)


def validate_configs(dataset_config: object, distance_config: object) -> None:
    if not isinstance(dataset_config, dict):
        raise ValueError("configs/datasets.yaml must contain a mapping")  # noqa: TRY004
    normalized = _normalized_distance_config(distance_config)
    if normalized.get("frame") != "odom":
        raise ValueError("distance_lod frame must be odom")
    levels, ranges = normalized.get("levels"), normalized.get("ranges_m")
    if not isinstance(levels, list) or tuple(map(float, levels)) != (
        0.05,
        0.10,
        0.20,
        0.40,
    ):
        raise ValueError(
            "distance_lod levels do not match supported dyadic resolutions"
        )
    if not isinstance(ranges, list) or len(ranges) != 4:
        raise ValueError("distance_lod.yaml must define four ranges")
    parsed_ranges: list[tuple[float, float]] = []
    for item in ranges:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(value, (int, float)) for value in item)
        ):
            raise ValueError("distance_lod ranges must be numeric [min,max] pairs")
        lower, upper = map(float, item)
        if lower >= upper:
            raise ValueError("distance_lod ranges must be increasing")
        parsed_ranges.append((lower, upper))
    if parsed_ranges[0][0] != 0.0:
        raise ValueError("distance_lod ranges must start at zero")
    if any(previous[1] != current[0] for previous, current in pairwise(parsed_ranges)):
        raise ValueError("distance_lod ranges must be contiguous")
    for name in ("semanticposs", "rellis3d"):
        entry = dataset_config.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"configs/datasets.yaml must define {name}")  # noqa: TRY004
        for key in ("root", "sequences", "scan_dir", "label_dir", "max_range_m"):
            if key not in entry:
                raise ValueError(f"dataset config for {name} missing {key}")
        if not isinstance(entry["root"], str) or Path(entry["root"]).is_absolute():
            raise ValueError(f"dataset root for {name} must be repository-relative")
        if not isinstance(entry["sequences"], list) or not entry["sequences"]:
            raise ValueError(f"dataset sequences for {name} must be non-empty")
        if (
            float(entry.get("min_range_m", 0.0)) < 0.0
            or float(entry["max_range_m"]) != parsed_ranges[-1][1]
        ):
            raise ValueError(f"dataset range for {name} must match distance_lod.yaml")


def load_selection(repo: Path, dataset: str, sequence: str, start: int, count: int):
    dataset_config = yaml.safe_load((repo / "configs/datasets.yaml").read_text())
    raw_distance_config = yaml.safe_load(
        (repo / "configs/distance_lod.yaml").read_text()
    )
    benchmark_config = yaml.safe_load((repo / "configs/benchmark.yaml").read_text())
    if (
        not isinstance(benchmark_config, dict)
        or benchmark_config.get("map_frame") != "odom"
    ):
        raise ValueError("configs/benchmark.yaml must declare map_frame: odom")
    validate_configs(dataset_config, raw_distance_config)
    distance_config = _normalized_distance_config(raw_distance_config)
    entry = dataset_config.get(dataset)
    if entry is None:
        raise ValueError(f"unknown dataset: {dataset}")
    root = repo / entry["root"]
    if not root.is_dir():
        raise FileNotFoundError(f"configured dataset root does not exist: {root}")
    adapter_type = SemanticPOSSDataset if dataset == "semanticposs" else Rellis3DDataset
    adapter = adapter_type(
        root,
        sequences=entry["sequences"],
        scan_dir=entry["scan_dir"],
        label_dir=entry["label_dir"],
    )
    if sequence not in adapter.list_sequences():
        raise ValueError(f"sequence {sequence} is not configured for {dataset}")
    source_frames = list(
        adapter.replay(
            sequence,
            start=start,
            end=start + count,
            min_range_m=float(entry.get("min_range_m", 0.0)),
            max_range_m=float(entry["max_range_m"]),
        )
    )
    if not source_frames:
        raise ValueError("frame selection is empty")
    pipeline, processed, durations_ns = PerceptionPipeline(), [], []
    for source_frame in source_frames:
        started = time.perf_counter_ns()
        processed.append(pipeline.process(source_frame).frame)
        durations_ns.append(time.perf_counter_ns() - started)
    return (
        processed,
        distance_config,
        entry,
        durations_ns,
        compute_window_radius_m(processed, float(entry["max_range_m"])),
    )


def _command(
    binary: str,
    adapter: PolicyAdapter,
    distance_config: dict[str, Any],
    window_radius_m: float,
    warmup_frames: int,
    repo: Path,
) -> list[str]:
    ranges = distance_config["ranges_m"]
    return [
        binary,
        "--policy",
        str(adapter.cpp_policy),
        "--levels",
        ",".join(str(float(item)) for item in distance_config["levels"]),
        "--window-radius",
        str(window_radius_m),
        "--distance-boundaries",
        ",".join(str(float(item[1])) for item in ranges[:3]),
        "--warmup-frames",
        str(warmup_frames),
        "--utility-config",
        str(repo / "configs" / "utility_lod.yaml"),
        "--governor-config",
        str(repo / "configs" / "resource_governor.yaml"),
    ]


def _aggregate_policy_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    stages: dict[str, list[int]] = {}
    churn, peak_rss = [], []
    late_frames = dropped_frames = 0
    drops_available = True
    fps = []
    for run in runs:
        memory, stream, metrics = (
            run["metrics"]["memory"],
            run["metrics"]["stream"],
            run["metrics"],
        )
        if memory["peak_rss_bytes"] is not None:
            peak_rss.append(memory["peak_rss_bytes"])
        if metrics["fps"] is not None:
            fps.append(metrics["fps"])
        late_frames += stream["late_frames"]
        if stream["dropped_frames"] is None:
            drops_available = False
        else:
            dropped_frames += stream["dropped_frames"]
        for frame in run["frame_metrics"]:
            churn.append(frame["topology_churn"])
            for name, value in frame["stages_ns"].items():
                stages.setdefault(name, []).append(value)
    return {
        "stage_latency_ns": {
            name: nearest_rank_summary(values)
            for name, values in sorted(stages.items())
        },
        "topology_churn_per_frame": nearest_rank_summary(churn),
        "late_frames": late_frames,
        "dropped_frames": dropped_frames if drops_available else None,
        "peak_rss_bytes": max(peak_rss) if peak_rss else None,
        "measured_frame_count": sum(run["metrics"]["frame_count"] for run in runs),
        "fps": nearest_rank_summary(fps),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    if (
        args.start < 0
        or args.count <= 0
        or args.warmup_frames < 0
        or args.repetitions <= 0
    ):
        raise ValueError(
            "start/warmup must be non-negative and count/repetitions positive"
        )
    if args.warmup_frames >= args.count:
        raise ValueError("warmup_frames must be smaller than count")
    requested = [item.strip() for item in args.policies.split(",") if item.strip()]
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("policies must be a non-empty, unique comma-separated list")
    unknown = set(requested) - POLICY_ADAPTERS.keys()
    if unknown:
        raise ValueError(f"unknown policies: {', '.join(sorted(unknown))}")
    unavailable = [name for name in requested if not POLICY_ADAPTERS[name].available]
    if unavailable:
        raise ValueError(f"policy adapter unavailable: {', '.join(unavailable)}")
    hardware_config = yaml.safe_load(
        (repo / "configs/hardware_profiles.yaml").read_text()
    )
    validate_hardware_profile(hardware_config, args.hardware_profile)
    frames, distance_config, _dataset_entry, perception_ns, window_radius_m = (
        load_selection(repo, args.dataset, args.sequence, args.start, args.count)
    )
    stream, digest = stream_bytes(frames)
    runs_by_policy: dict[str, list[dict[str, Any]]] = {
        policy: [] for policy in requested
    }
    execution_order: list[list[str]] = []
    for repetition in range(args.repetitions):
        order = (
            requested[repetition % len(requested) :]
            + requested[: repetition % len(requested)]
        )
        execution_order.append(order)
        for policy in order:
            adapter = POLICY_ADAPTERS[policy]
            completed = subprocess.run(
                _command(
                    args.binary,
                    adapter,
                    distance_config,
                    window_radius_m,
                    args.warmup_frames,
                    repo,
                ),
                input=stream,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"{policy} repetition {repetition} failed: {completed.stderr.decode(errors='replace').strip()}"
                )
            result = json.loads(completed.stdout)
            if (
                result.get("schema_version") != SCHEMA_VERSION
                or result.get("stream_digest") != digest
                or result.get("policy") != policy
            ):
                raise RuntimeError(
                    f"{policy} repetition {repetition} violated benchmark contract"
                )
            runs_by_policy[policy].append(result)
    results: dict[str, Any] = {}
    for policy in requested:
        adapter, runs = POLICY_ADAPTERS[policy], runs_by_policy[policy]
        results[policy] = {
            "adapter": {
                "cpp_policy": adapter.cpp_policy,
                "available": adapter.available,
                "integration_note": adapter.integration_note,
            },
            "runs": runs,
            "aggregate": _aggregate_policy_runs(runs),
        }
    config_paths = [
        repo / "configs/datasets.yaml",
        repo / "configs/distance_lod.yaml",
        repo / "configs/utility_lod.yaml",
        repo / "configs/resource_governor.yaml",
        repo / "configs/benchmark.yaml",
        repo / "configs/hardware_profiles.yaml",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": {
            "protocol_version": PROTOCOL_VERSION,
            "selection_digest": digest,
            "config_sha256": {path.name: _sha256_file(path) for path in config_paths},
            "hardware": hardware_metadata(args.hardware_profile),
            "repetitions": args.repetitions,
            "warmup_frames": args.warmup_frames,
            "policy_execution_order": execution_order,
            "map_window_radius_m": window_radius_m,
            "measurement_scope": {
                "perception": "Python PerceptionPipeline processing, shared once before all policy runs",
                "map_window_follow": "C++ public map window-center update from the transmitted world-frame pose; excludes serialization",
                "map_update": "C++ map update calls only; excludes protocol parsing, snapshotting, and JSON/CSV serialization",
                "protocol_parse_and_validate": "C++ token parsing and Observation construction; excludes stdin I/O",
                "snapshot_and_topology": "C++ map snapshot plus topology extraction; excludes JSON/CSV serialization",
            },
        },
        "dataset": args.dataset,
        "sequence": args.sequence,
        "start": args.start,
        "input_frames": len(frames),
        "measured_frames_per_run": len(frames) - args.warmup_frames,
        "shared_stage_latency_ns": {"perception": nearest_rank_summary(perception_ns)},
        "policies": results,
    }


def _write_csv(path: Path, result: dict[str, Any]) -> None:
    fields = (
        "schema_version",
        "dataset",
        "sequence",
        "policy",
        "selection_digest",
        "repetitions",
        "measured_frame_count",
        "map_update_mean_ns",
        "map_update_p50_ns",
        "map_update_p95_ns",
        "map_update_p99_ns",
        "map_update_max_ns",
        "topology_churn_p95",
        "late_frames",
        "dropped_frames",
        "peak_rss_bytes",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for policy, report in result["policies"].items():
            aggregate, map_update = (
                report["aggregate"],
                report["aggregate"]["stage_latency_ns"]["map_update"],
            )
            writer.writerow(
                {
                    "schema_version": result["schema_version"],
                    "dataset": result["dataset"],
                    "sequence": result["sequence"],
                    "policy": policy,
                    "selection_digest": result["provenance"]["selection_digest"],
                    "repetitions": result["provenance"]["repetitions"],
                    "measured_frame_count": aggregate["measured_frame_count"],
                    "map_update_mean_ns": map_update["mean"],
                    "map_update_p50_ns": map_update["p50"],
                    "map_update_p95_ns": map_update["p95"],
                    "map_update_p99_ns": map_update["p99"],
                    "map_update_max_ns": map_update["max"],
                    "topology_churn_p95": aggregate["topology_churn_per_frame"]["p95"],
                    "late_frames": aggregate["late_frames"],
                    "dropped_frames": aggregate["dropped_frames"],
                    "peak_rss_bytes": aggregate["peak_rss_bytes"],
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--binary", required=True)
    parser.add_argument(
        "--dataset", choices=("semanticposs", "rellis3d"), required=True
    )
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--warmup-frames", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--policies", default="uniform5,uniform40,distance_lod,utility_lod"
    )
    parser.add_argument("--hardware-profile", default="auto")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    args = parser.parse_args()
    try:
        result = run(args)
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        yaml.YAMLError,
        json.JSONDecodeError,
    ) as error:
        print(f"veyra benchmark: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    if args.csv_output:
        _write_csv(args.csv_output, result)
    if not args.output:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
