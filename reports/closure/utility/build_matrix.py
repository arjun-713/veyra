"""Build the UtilityLOD closure ablation matrix from a benchmark report.

Reads reports/closure/utility/benchmark_semanticposs00.json (one identical
SemanticPOSS stream for every policy) and writes ablation_matrix.json with
task-quality evidence (pole/pedestrian/vehicle/hazard retention, elevation
RMSE) against measured cost (latency, RSS, bytes, cells, churn), plus
deltas of every leg versus the ablation_distance control.

Usage: python3 reports/closure/utility/build_matrix.py [benchmark.json [matrix.json]]
Defaults preserve the original closure artifacts (benchmark_semanticposs00.json
-> ablation_matrix.json); the utility rerun passes its own pair.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "benchmark_semanticposs00.json"
OUTPUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "ablation_matrix.json"

ABLATION_ORDER = [
    "ablation_distance",
    "ablation_geometry",
    "ablation_semantics",
    "ablation_motion",
    "ablation_traversability",
    "utility_lod",
]
CONTEXT_POLICIES = ["uniform5", "uniform40", "distance_lod"]


def _ms(ns: float | int | None) -> float | None:
    return None if ns is None else float(ns) / 1_000_000.0


def _mb(value: float | int | None) -> float | None:
    return None if value is None else float(value) / 1048576.0


def _retention(entry: dict) -> dict:
    return {
        "status": entry.get("status"),
        "reference_bins": entry.get("reference_bins"),
        "retained_bins": entry.get("retained_bins"),
        "retention_fraction": entry.get("retention_fraction"),
    }


def _policy_row(name: str, report: dict) -> dict:
    aggregate = report["aggregate"]
    final_run = report["runs"][-1]
    quality = final_run["quality"]
    retention = quality.get("field_retention", {})
    task_classes = retention.get("task_classes", {})
    members = task_classes.get("members", {}) if isinstance(task_classes, dict) else {}
    map_update = aggregate["stage_latency_ns"]["map_update"]
    memory = final_run["metrics"]["memory"]
    return {
        "signals": report["adapter"]["signals"],
        "cpp_policy": report["adapter"]["cpp_policy"],
        "utility_config": report["adapter"]["utility_config"],
        "quality": {
            "elevation_rmse_m": quality["elevation_vs_fine_reference"]["rmse_m"],
            "elevation_coverage": quality["elevation_vs_fine_reference"]["coverage"],
            "weighted_mean_level": final_run["detail_metric"]["weighted_mean_level"],
            "semantic_retention": _retention(retention.get("semantic", {})),
            "terrain_hazard_retention": _retention(retention.get("terrain_hazard", {})),
            "task_classes": {
                group: _retention(entry) for group, entry in members.items()
            },
        },
        "cost": {
            "map_update_p50_ms": _ms(map_update["p50"]),
            "map_update_p95_ms": _ms(map_update["p95"]),
            "map_update_p99_ms": _ms(map_update["p99"]),
            "peak_rss_mb": _mb(aggregate["peak_rss_bytes"]),
            "logical_map_bytes": memory["logical_map_bytes"],
            "allocated_map_bytes": memory["allocated_map_bytes"],
            "active_leaves": sum(aggregate["final_leaves_per_level"].values()),
            "final_leaves_per_level": aggregate["final_leaves_per_level"],
        },
        "dynamics": {
            "topology_churn_p50": aggregate["topology_churn_per_frame"]["p50"],
            "topology_churn_p95": aggregate["topology_churn_per_frame"]["p95"],
            "splits_p95": aggregate["splits_per_frame"]["p95"],
            "merges_p95": aggregate["merges_per_frame"]["p95"],
            "governor_interventions": aggregate["governor"]["interventions"],
            "governor_actions_applied": aggregate["governor"]["actions_applied"],
        },
    }


def _delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return float(current) - float(baseline)


def main() -> None:
    benchmark = json.loads(REPORT.read_text())
    policies = benchmark["policies"]
    missing = [name for name in (*CONTEXT_POLICIES, *ABLATION_ORDER) if name not in policies]
    if missing:
        raise SystemExit(f"benchmark report is missing policies: {missing}")
    digest = benchmark["provenance"]["selection_digest"]
    digests = {
        name: policies[name]["runs"][0].get("stream_digest") for name in policies
    }
    if len(set(digests.values())) != 1:
        raise SystemExit(f"policies did not share one stream: {digests}")
    rows = {name: _policy_row(name, policies[name]) for name in policies}
    baseline = rows["ablation_distance"]
    matrix: dict[str, dict] = {}
    for name in ABLATION_ORDER:
        row = rows[name]
        bq, q = baseline["quality"], row["quality"]
        bc, c = baseline["cost"], row["cost"]
        bd, d = baseline["dynamics"], row["dynamics"]
        matrix[name] = {
            **row,
            "delta_vs_distance": {
                "elevation_rmse_m": _delta(
                    q["elevation_rmse_m"], bq["elevation_rmse_m"]
                ),
                "weighted_mean_level": _delta(
                    q["weighted_mean_level"], bq["weighted_mean_level"]
                ),
                "semantic_retention": _delta(
                    q["semantic_retention"]["retention_fraction"],
                    bq["semantic_retention"]["retention_fraction"],
                ),
                "terrain_hazard_retention": _delta(
                    q["terrain_hazard_retention"]["retention_fraction"],
                    bq["terrain_hazard_retention"]["retention_fraction"],
                ),
                "task_class_retention": {
                    group: _delta(
                        q["task_classes"].get(group, {}).get("retention_fraction"),
                        bq["task_classes"].get(group, {}).get("retention_fraction"),
                    )
                    for group in ("pole", "pedestrian", "vehicle")
                },
                "map_update_p95_ms": _delta(
                    c["map_update_p95_ms"], bc["map_update_p95_ms"]
                ),
                "peak_rss_mb": _delta(c["peak_rss_mb"], bc["peak_rss_mb"]),
                "active_leaves": _delta(c["active_leaves"], bc["active_leaves"]),
                "topology_churn_p95": _delta(
                    d["topology_churn_p95"], bd["topology_churn_p95"]
                ),
            },
        }
    OUTPUT.write_text(
        json.dumps(
            {
                "selection_digest": digest,
                "dataset": benchmark["dataset"],
                "sequence": benchmark["sequence"],
                "input_frames": benchmark["input_frames"],
                "measured_frames_per_run": benchmark["measured_frames_per_run"],
                "repetitions": benchmark["provenance"]["repetitions"],
                "warmup_frames": benchmark["provenance"]["warmup_frames"],
                "git_sha": benchmark["provenance"]["git_sha"],
                "hardware": benchmark["provenance"]["hardware"],
                "perception": benchmark["perception"],
                "context_policies": {
                    name: rows[name] for name in CONTEXT_POLICIES
                },
                "ablation_matrix": matrix,
                "utility_ablation_framework": benchmark["utility_ablation"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"wrote {OUTPUT} ({len(matrix)} ablation members, digest {digest[:16]})")


if __name__ == "__main__":
    main()
