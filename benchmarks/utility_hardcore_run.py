"""Reproducible UtilityLOD challenge and resource budget runner."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from benchmarks.run_benchmark import (
    POLICY_ADAPTERS,
    PolicyAdapter,
    _fine_reference_from_snapshot,
    run as benchmark_run,
)
from benchmarks.utility_hardcore import manifest_digest, regional_comparison
from benchmarks.utility_hardcore_report import write_diagnostics, write_plots
from datasets.rellis import Rellis3DDataset
from datasets.semantickitti import SemanticKITTIDataset
from datasets.semanticposs import SemanticPOSSDataset


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("challenges"), list
    ):
        raise ValueError("unsupported challenge manifest schema")
    if manifest.get("sha256") != manifest_digest(manifest):
        raise ValueError("challenge manifest checksum mismatch")
    return manifest


def memory_budget_config(source: dict[str, Any], target_bytes: int) -> dict[str, Any]:
    if target_bytes <= 0:
        raise ValueError("logical budget must be positive")
    result = dict(source)
    pressure = float(result["pressure_ratio"])
    if not 0 < pressure <= 1:
        raise ValueError("pressure ratio must be in (0,1]")
    result["max_logical_bytes"] = math.ceil(target_bytes / pressure)
    # Isolate the existing governor's logical-byte response in this sweep.
    # The normal deadline and cell caps are tested in a separate run.
    result["max_active_cells"] = max(int(result["max_active_cells"]), 1_000_000_000)
    result["target_frame_time_ms"] = max(
        float(result["target_frame_time_ms"]), 1_000_000.0
    )
    result["max_rss_bytes"] = 0
    result["overload_consecutive_frames"] = 1
    return result


def _verified_sources(repo: Path, challenges: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for challenge in challenges:
        for kind in ("scan", "label"):
            relative = str(challenge[f"source_{kind}_path"])
            if relative in seen:
                continue
            seen.add(relative)
            path = (repo / relative).resolve()
            if not path.is_relative_to(repo.resolve()) or not path.is_file():
                raise ValueError(f"missing or escaped frozen {kind}: {relative}")
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if sha != challenge[f"source_{kind}_sha256"]:
                raise ValueError(f"frozen {kind} checksum mismatch: {relative}")


def _groups(challenges: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in challenges:
        key = (
            item["dataset"],
            item["sequence"],
            item["frame_start"],
            item["frame_end_exclusive"],
        )
        groups[key].append(item)
    return [groups[key] for key in sorted(groups)]


def _world_xy(
    points: np.ndarray, pose: np.ndarray, *, coordinate_frame: str = "sensor"
) -> np.ndarray:
    xyz = np.asarray(points[:, :3], dtype=np.float64)
    if coordinate_frame == "world":
        return xyz[:, :2]
    if coordinate_frame not in {"sensor", "lidar"}:
        raise ValueError(f"unsupported challenge coordinate frame: {coordinate_frame}")
    matrix = np.asarray(pose, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError("invalid source-frame pose in challenge")
    return (xyz @ matrix[:3, :3].T + matrix[:3, 3])[:, :2]


def _args(
    repo: Path,
    binary: Path,
    challenge: dict[str, Any],
    policies: list[str],
    repetitions: int,
    warmup: int,
    perception_config: Path,
    telemetry: bool = True,
) -> argparse.Namespace:
    return argparse.Namespace(
        repo=repo,
        binary=str(binary),
        dataset=challenge["dataset"],
        sequence=challenge["sequence"],
        start=challenge["frame_start"],
        count=challenge["frame_end_exclusive"] - challenge["frame_start"],
        warmup_frames=warmup,
        repetitions=repetitions,
        policies=",".join(policies),
        hardware_profile="auto",
        retain_frames=True,
        skip_perception=False,
        perception_config=str(perception_config),
        dataset_root=None,
        governor_config="configs/resource_governor.yaml",
        planner_evaluation=False,
        keep_leaf_details=True,
        promotion_telemetry=telemetry,
        build_type="Release",
        dataset_sha256=None,
    )


def _critical_bins(
    repo: Path, challenge: dict[str, Any]
) -> set[tuple[int, int]] | None:
    if challenge["challenge_type"] not in {"semantic_object", "motion_candidate"}:
        return None
    config = yaml.safe_load((repo / "configs/datasets.yaml").read_text())[
        challenge["dataset"]
    ]
    adapter_type = {
        "semanticposs": SemanticPOSSDataset,
        "rellis3d": Rellis3DDataset,
        "semantickitti": SemanticKITTIDataset,
    }[challenge["dataset"]]
    frame = adapter_type(repo / config["root"]).load_frame(
        challenge["sequence"], challenge["source_frame_id"], max_range_m=100.0
    )
    x0, y0, x1, y1 = challenge["bbox_xy_m"]
    world_xy = _world_xy(
        np.asarray(frame.points),
        np.asarray(frame.pose.matrix),
        coordinate_frame=frame.provenance.coordinate_frame,
    )
    mask = (
        (world_xy[:, 0] >= x0)
        & (world_xy[:, 0] < x1)
        & (world_xy[:, 1] >= y0)
        & (world_xy[:, 1] < y1)
    )
    if challenge["challenge_type"] == "semantic_object":
        mask &= np.asarray(frame.semantic_class) == int(
            challenge["support"]["class_id"]
        )
    else:
        mask &= np.isin(
            np.asarray(frame.raw_semantic_class), challenge["support"]["raw_moving_ids"]
        )
    instance = challenge["support"].get("instance_id")
    if instance is not None:
        mask &= np.asarray(frame.instance_id) == int(instance)
    return {
        (math.floor(float(x) * 20), math.floor(float(y) * 20))
        for x, y in world_xy[mask]
    }


def _semantic_retention(
    snapshot: dict[str, Any],
    keys: set[tuple[int, int]] | None,
    classes: set[int] | None,
) -> float | None:
    if not keys or not classes:
        return None
    by_id = {
        (int(leaf["level"]), int(leaf["ix"]), int(leaf["iy"])): leaf
        for leaf in snapshot.get("leaves", [])
    }
    retained = 0
    for ix, iy in keys:
        owner = next(
            (
                by_id[(level, ix >> level, iy >> level)]
                for level in range(4)
                if (level, ix >> level, iy >> level) in by_id
            ),
            None,
        )
        retained += int(
            owner is not None and int(owner.get("semantic_class", 0)) in classes
        )
    return retained / len(keys)


def _row(
    challenge: dict[str, Any],
    name: str,
    policy: dict[str, Any],
    regional: dict[str, Any],
    retention: float | None,
    *,
    budget_fraction: float | None = None,
    budget_target_bytes: int | None = None,
) -> dict[str, Any]:
    run = policy["runs"][-1]
    aggregate = policy["aggregate"]
    latency = aggregate["stage_latency_ns"]["map_update"]
    critical = regional["critical"]["utility_lod"]
    background = regional["background"]["utility_lod"]
    memory = run["metrics"]["memory"]
    logical = int(memory["logical_map_bytes"])
    telemetry = run.get("promotion_telemetry") or {}
    transitions = telemetry.get("promotion_transitions", [])
    transition_count = sum(int(item["count"]) for item in transitions)
    frames = int(run["metrics"]["frame_count"])
    return {
        "challenge_id": challenge["id"],
        "dataset": challenge["dataset"],
        "challenge_type": challenge["challenge_type"],
        "relevant_class": challenge["relevant_class"],
        "policy": name,
        "budget_fraction": budget_fraction,
        "budget_target_bytes": budget_target_bytes,
        "budget_met_2pct": logical <= budget_target_bytes * 1.02
        if budget_target_bytes
        else None,
        "selection_digest": run["stream_digest"],
        "logical_map_bytes": logical,
        "allocated_map_bytes": memory["allocated_map_bytes"],
        "peak_rss_bytes": aggregate["peak_rss_bytes"],
        "active_cells": sum(
            int(n) for n in aggregate["final_leaves_per_level"].values()
        ),
        "map_p50_ms": latency["p50"] / 1e6,
        "map_p95_ms": latency["p95"] / 1e6,
        "map_samples": latency["count"],
        "tail_latency_credible": latency["count"] >= 20,
        "topology_churn_p95": aggregate["topology_churn_per_frame"]["p95"],
        "governor_actions": aggregate["governor"]["actions_applied"],
        "promotion_transitions": transition_count if telemetry else None,
        "promotion_transitions_per_frame": transition_count / frames
        if telemetry and frames
        else None,
        "promotion_budget_vetoes": telemetry.get("budget_suppressed"),
        "critical_reference_bins": regional["critical_reference_bins"],
        "critical_accuracy_10cm": critical["height_accuracy_10cm"],
        "critical_completion": critical["completion_fraction"],
        "critical_chamfer_m": critical["symmetric_chamfer_m"],
        "critical_elevation_rmse_m": critical["elevation_rmse_m"],
        "background_accuracy_10cm": background["height_accuracy_10cm"],
        "background_completion": background["completion_fraction"],
        "background_chamfer_m": background["symmetric_chamfer_m"],
        "semantic_retention_critical": retention,
        "promotion_recall_denominator": regional["promotion_recall_denominator"]
        if name.startswith(("utility", "a"))
        else None,
        "missed_critical_bins": regional["missed_critical_bins"]
        if name.startswith(("utility", "a"))
        else None,
        "promotion_precision": regional["promotion_precision"]
        if name.startswith(("utility", "a"))
        else None,
        "promotion_recall": regional["promotion_recall"]
        if name.startswith(("utility", "a"))
        else None,
        "promoted_bins": regional["promoted_bins"]
        if name.startswith(("utility", "a"))
        else None,
        "promoted_observed_area_m2": regional["promoted_bins"] * 0.05 * 0.05
        if name.startswith(("utility", "a"))
        else None,
        "wasted_promotion_ratio": regional["wasted_promotion_ratio"]
        if name.startswith(("utility", "a"))
        else None,
        "promotion_telemetry": run.get("promotion_telemetry"),
    }


def _score_group(
    repo: Path,
    challenges: list[dict[str, Any]],
    result: dict[str, Any],
    baseline: dict[str, Any],
    reference: dict[str, Any],
    *,
    budget_fraction: float | None = None,
    budget_target_bytes: int | None = None,
) -> list[dict[str, Any]]:
    digest = baseline["provenance"]["selection_digest"]
    if result["provenance"]["selection_digest"] != digest:
        raise ValueError(
            "policy comparison did not consume the frozen identical input stream"
        )
    distance_snapshot = baseline["policies"]["distance_lod"]["runs"][-1]["snapshot"]
    scored = []
    for challenge in challenges:
        mask = _critical_bins(repo, challenge)
        if (
            challenge["challenge_type"] in {"semantic_object", "motion_candidate"}
            and not mask
        ):
            raise ValueError(
                f"frozen challenge has no aligned labelled support: {challenge['id']}"
            )
        task_classes = (
            {int(challenge["support"]["class_id"])}
            if challenge["challenge_type"] == "semantic_object"
            else None
        )
        for name, policy in result["policies"].items():
            snapshot = policy["runs"][-1]["snapshot"]
            region = regional_comparison(
                reference,
                distance_snapshot,
                snapshot,
                bbox_xy_m=challenge["bbox_xy_m"],
                critical_bins=mask,
            )
            if mask and region["critical_reference_bins"] == 0:
                raise ValueError(
                    f"frozen challenge has no retained fine reference support: {challenge['id']}"
                )
            scored.append(
                _row(
                    challenge,
                    name,
                    policy,
                    region,
                    _semantic_retention(snapshot, mask, task_classes),
                    budget_fraction=budget_fraction,
                    budget_target_bytes=budget_target_bytes,
                )
            )
    return scored


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    flat = [
        {key: value for key, value in row.items() if key != "promotion_telemetry"}
        for row in rows
    ]
    if not flat:
        return
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)


def _json(path: Path, content: Any) -> None:
    path.write_text(
        json.dumps(content, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def _annotate_efficiency(rows: list[dict[str, Any]]) -> None:
    baseline = {
        row["challenge_id"]: row for row in rows if row["policy"] == "distance_lod"
    }
    for row in rows:
        control = baseline[row["challenge_id"]]
        extra_mb = (row["logical_map_bytes"] - control["logical_map_bytes"]) / 1e6
        row["extra_logical_mb_vs_distance"] = extra_mb
        for field, output, direction in (
            ("critical_accuracy_10cm", "critical_accuracy_gain_per_MB", 1),
            ("semantic_retention_critical", "critical_retention_gain_per_MB", 1),
            ("critical_chamfer_m", "critical_chamfer_improvement_per_MB", -1),
        ):
            measured, reference = row.get(field), control.get(field)
            row[output] = (
                direction * (measured - reference) / extra_mb
                if measured is not None and reference is not None and extra_mb > 0
                else None
            )


def _variants(directory: Path, repo: Path) -> list[str]:
    # The C++ policy reader accepts the repository's inline-list YAML subset,
    # not PyYAML's block-list re-serialization of distance_boundaries_m.
    original = (repo / "configs/utility_lod.yaml").read_text()
    full = yaml.safe_load(original)
    variants = {
        "a1_geometry": ("geometry_weight",),
        "a2_semantics": ("semantic_weight",),
        "a3_geometry_semantics": ("geometry_weight", "semantic_weight"),
        "a4_geometry_semantics_motion": (
            "geometry_weight",
            "semantic_weight",
            "motion_weight",
        ),
    }
    weights = {
        "geometry_weight",
        "semantic_weight",
        "motion_weight",
        "traversability_risk_weight",
        "uncertainty_weight",
    }
    for name, enabled in variants.items():
        content = original
        for field in weights - set(enabled):
            if field not in full["utility"]:
                raise ValueError(f"missing production utility weight: {field}")
            pattern = rf"(?m)^(  {re.escape(field)}:)\s*[^#\n]+$"
            content, count = re.subn(pattern, r"\g<1> 0.0", content)
            if count != 1:
                raise ValueError(f"cannot override production utility weight: {field}")
        path = directory / f"{name}.yaml"
        path.write_text(content)
        POLICY_ADAPTERS[name] = PolicyAdapter(
            name,
            "utility_lod",
            True,
            "benchmark ablation retaining production weights/thresholds and safety override",
            utility_config=str(path),
            suite="hardcore_ablation",
            signals=tuple(field.removesuffix("_weight") for field in enabled),
        )
    return list(variants)


def _budget_variants(
    directory: Path, repo: Path, distance_bytes: int
) -> list[tuple[str, float, int]]:
    source = yaml.safe_load((repo / "configs/resource_governor.yaml").read_text())
    variants = []
    for percent in (0, 5, 10, 20, 30):
        fraction = percent / 100.0
        target = round(distance_bytes * (1 + fraction))
        config = memory_budget_config(source, target)
        path = directory / f"logical_budget_plus_{percent}.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=True))
        name = f"utility_budget_plus_{percent}"
        POLICY_ADAPTERS[name] = PolicyAdapter(
            name,
            "utility_lod",
            True,
            "existing governor with isolated logical-byte budget",
            utility_config="utility_lod.yaml",
            suite="hardcore_budget",
            signals=POLICY_ADAPTERS["utility_lod"].signals,
            governor_config=str(path),
        )
        variants.append((name, fraction, target))
    return variants


def run_suite(
    repo: Path,
    binary: Path,
    manifest: dict[str, Any],
    *,
    repetitions: int,
    matrix_repetitions: int,
    warmup: int,
    max_groups: int | None = None,
    ablations: bool = True,
    budgets: bool = True,
    progress_path: Path | None = None,
    telemetry: bool = True,
) -> dict[str, Any]:
    groups = _groups(manifest["challenges"])
    selected = groups if max_groups is None else groups[:max_groups]
    _verified_sources(repo, [item for group in selected for item in group])
    rows: list[dict[str, Any]] = []
    run_provenance = []
    with tempfile.TemporaryDirectory(prefix="veyra-utility-config-") as temporary:
        directory = Path(temporary)
        ablation_names = _variants(directory, repo)
        for group_index, group in enumerate(selected, start=1):
            challenge = group[0]
            print(
                f"challenge stream {group_index}/{len(selected)}: {challenge['dataset']} "
                f"{challenge['sequence']} frames {challenge['frame_start']}:{challenge['frame_end_exclusive']}",
                flush=True,
            )
            perception_config = repo / "configs/perception.yaml"
            if any(item["challenge_type"] == "motion_candidate" for item in group):
                setting = yaml.safe_load(perception_config.read_text())
                setting["temporal"]["enabled"] = True
                perception_config = directory / "perception-temporal.yaml"
                perception_config.write_text(yaml.safe_dump(setting, sort_keys=True))
            base_started = time.perf_counter()
            base = benchmark_run(
                _args(
                    repo,
                    binary,
                    challenge,
                    ["uniform5", "uniform40", "distance_lod", "utility_lod"],
                    repetitions,
                    warmup,
                    perception_config,
                    telemetry,
                )
            )
            stages = base["perception"]["status"]
            if (
                stages.get("semantic") != "ground_truth"
                or not str(stages.get("ground", "")).startswith("pypatchworkpp")
                or stages.get("terrain") != "available"
            ):
                raise RuntimeError(
                    f"challenge perception stage unavailable or fell back: {stages}"
                )
            if any(
                item["challenge_type"] == "motion_candidate" for item in group
            ) and stages.get("temporal") in {
                None,
                "disabled",
                "unavailable",
                "invalid",
            }:
                raise RuntimeError(f"motion challenge lacked temporal stage: {stages}")
            reference = _fine_reference_from_snapshot(
                base["policies"]["uniform5"]["runs"][-1]["snapshot"]
            )
            rows.extend(_score_group(repo, group, base, base, reference))
            run_provenance.append(
                {
                    "group": [item["id"] for item in group],
                    "stage": "baseline",
                    "benchmark_wall_s": time.perf_counter() - base_started,
                    "provenance": base["provenance"],
                    "perception": base["perception"],
                }
            )
            variants: list[tuple[str, float, int]] = []
            if budgets:
                baseline_bytes = base["policies"]["distance_lod"]["runs"][-1][
                    "metrics"
                ]["memory"]["logical_map_bytes"]
                variants = _budget_variants(directory, repo, int(baseline_bytes))
            optional_names = (ablation_names if ablations else []) + [
                item[0] for item in variants
            ]
            if optional_names:
                # Ablations and logical-budget sweep share one perception pass.
                print(
                    f"  ablation/budget matrix: {len(optional_names)} policies",
                    flush=True,
                )
                matrix_started = time.perf_counter()
                matrix = benchmark_run(
                    _args(
                        repo,
                        binary,
                        challenge,
                        optional_names,
                        matrix_repetitions,
                        warmup,
                        perception_config,
                        telemetry,
                    )
                )
                if ablations:
                    ablated = {
                        **matrix,
                        "policies": {
                            name: matrix["policies"][name] for name in ablation_names
                        },
                    }
                    rows.extend(_score_group(repo, group, ablated, base, reference))
                for name, fraction, target in variants:
                    single = {
                        **matrix,
                        "policies": {name: matrix["policies"][name]},
                    }
                    rows.extend(
                        _score_group(
                            repo,
                            group,
                            single,
                            base,
                            reference,
                            budget_fraction=fraction,
                            budget_target_bytes=target,
                        )
                    )
                run_provenance.append(
                    {
                        "group": [item["id"] for item in group],
                        "stage": "ablation_and_budget_matrix",
                        "benchmark_wall_s": time.perf_counter() - matrix_started,
                        "provenance": matrix["provenance"],
                        "generated_configs": {
                            name: (directory / f"{name}.yaml").read_text()
                            for name in (ablation_names if ablations else [])
                        }
                        | {
                            name: Path(
                                POLICY_ADAPTERS[name].governor_config
                            ).read_text()
                            for name, _, _ in variants
                        },
                    }
                )
                del matrix
            del base
            if progress_path is not None:
                _json(
                    progress_path,
                    {
                        "status": "partial",
                        "completed_groups": group_index,
                        "rows": rows,
                        "runs": run_provenance,
                    },
                )
    _annotate_efficiency(rows)
    return {
        "schema_version": 1,
        "challenge_manifest_sha256": manifest["sha256"],
        "challenge_count": len(manifest["challenges"]),
        "evaluated_challenges": sum(len(group) for group in selected),
        "group_count": len(selected),
        "selection_frozen_before_policy_execution": True,
        "reference_is_ground_truth": False,
        "promotion_telemetry_enabled": telemetry,
        "metric_definitions": {
            "critical": "frozen GT object 5cm bins where available; otherwise selected fixed XY geometry/control region",
            "semantic_input": "dataset ground-truth labels intentionally supplied to production UtilityLOD in this policy-potential experiment; not neural model accuracy",
            "promotion_precision": "fraction of final Utility-finer observed bins within frozen critical region",
            "promotion_recall": "fraction of frozen critical bins with DistanceLOD owner coarser than L0 that are finer in Utility final map",
            "wasted_promotion_ratio": "fraction of final promoted observed bins outside critical region with no absolute elevation-error reduction",
            "budget": "existing governor logical-byte pressure; cap is assessed after each frame, not enforced exactly",
            "p95": "nearest-rank p95; credible tail requires >=20 samples",
        },
        "rows": rows,
        "runs": run_provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/utility_challenge_manifest.json"),
    )
    parser.add_argument(
        "--binary", type=Path, default=Path("build/apps/benchmark/veyra_benchmark")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("reports/utility-hardcore")
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--matrix-repetitions",
        type=int,
        default=1,
        help="ablation/budget repetitions (p95 requires at least 20 samples)",
    )
    parser.add_argument("--warmup-frames", type=int, default=2)
    parser.add_argument("--max-groups", type=int)
    parser.add_argument("--skip-ablations", action="store_true")
    parser.add_argument("--skip-budgets", action="store_true")
    parser.add_argument(
        "--disable-promotion-telemetry",
        action="store_true",
        help="repeat uninstrumented policy latency/quality for overhead assessment",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    manifest_path = (
        args.manifest if args.manifest.is_absolute() else repo / args.manifest
    )
    binary = args.binary if args.binary.is_absolute() else repo / args.binary
    destination = (
        args.output_dir if args.output_dir.is_absolute() else repo / args.output_dir
    )
    if not binary.is_file():
        parser.error(f"benchmark binary missing: {binary}")
    if (
        args.repetitions < 1
        or args.matrix_repetitions < 1
        or args.warmup_frames < 0
        or (args.max_groups is not None and args.max_groups < 1)
    ):
        parser.error("repetitions and max-groups must be positive; warmup non-negative")
    manifest = load_manifest(manifest_path)
    destination.mkdir(parents=True, exist_ok=True)
    result = run_suite(
        repo,
        binary,
        manifest,
        repetitions=args.repetitions,
        matrix_repetitions=args.matrix_repetitions,
        warmup=args.warmup_frames,
        max_groups=args.max_groups,
        ablations=not args.skip_ablations,
        budgets=not args.skip_budgets,
        progress_path=destination / "partial_results.json",
        telemetry=not args.disable_promotion_telemetry,
    )
    _json(destination / "utility_full_results.json", result)
    _write_csv(destination / "utility_full_results.csv", result["rows"])
    for challenge_type, filename in (
        ("semantic_object", "semantic_challenges.csv"),
        ("geometry_hazard", "geometry_challenges.csv"),
        ("motion_candidate", "motion_challenges.csv"),
    ):
        _write_csv(
            destination / filename,
            [row for row in result["rows"] if row["challenge_type"] == challenge_type],
        )
    _write_csv(
        destination / "control_challenges.csv",
        [row for row in result["rows"] if row["challenge_type"].endswith("control")],
    )
    _write_csv(
        destination / "budget_sweep.csv",
        [row for row in result["rows"] if row["budget_fraction"] is not None],
    )
    _write_csv(
        destination / "ablation_results.csv",
        [row for row in result["rows"] if row["policy"].startswith("a")],
    )
    _json(
        destination / "reproducibility.json",
        {"manifest_sha256": manifest["sha256"], "runs": result["runs"]},
    )
    distributions = write_diagnostics(destination, result["rows"])
    write_plots(destination, result["rows"], distributions)
    print(
        f"evaluated {result['evaluated_challenges']} challenges in {result['group_count']} shared streams; {len(result['rows'])} policy-region rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
