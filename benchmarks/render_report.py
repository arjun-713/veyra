"""Render compact benchmark JSON as an Actions summary and review comment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text())


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value) / 1e6:.2f} ms"


def _mb(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value) / 1048576:.1f} MB"


def _metres(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f} m"


def _retention(quality: dict[str, Any], field: str) -> str:
    value = quality.get("field_retention", {}).get(field, {})
    fraction = value.get("retention_fraction")
    if value.get("status") != "measured":
        return "n/a"
    return "n/a" if fraction is None else f"{float(fraction):.1%}"


def _map_table(report: dict[str, Any] | None) -> str:
    headers = ["Metric", "Uniform5", "Uniform40", "DistanceLOD", "UtilityLOD"]
    metrics = [
        ("FPS", lambda a, r: a["fps"]["p50"]),
        (
            "p50 map latency",
            lambda a, r: _ms(a["stage_latency_ns"]["map_update"]["p50"]),
        ),
        ("p95", lambda a, r: _ms(a["stage_latency_ns"]["map_update"]["p95"])),
        ("p99", lambda a, r: _ms(a["stage_latency_ns"]["map_update"]["p99"])),
        ("Peak RSS", lambda a, r: _mb(a["peak_rss_bytes"])),
        (
            "Logical bytes",
            lambda a, r: str(r["runs"][-1]["metrics"]["memory"]["logical_map_bytes"]),
        ),
        (
            "Allocated bytes",
            lambda a, r: str(r["runs"][-1]["metrics"]["memory"]["allocated_map_bytes"]),
        ),
        (
            "Active leaves",
            lambda a, r: f"{sum(a['final_leaves_per_level'].values()):,}",
        ),
        ("Topology churn", lambda a, r: f"{a['topology_churn_per_frame']['p95']:.1f}"),
        (
            "Splits/frame",
            lambda a, r: f"{a.get('splits_per_frame', {}).get('p95', 'n/a')}",
        ),
        (
            "Merges/frame",
            lambda a, r: f"{a.get('merges_per_frame', {}).get('p95', 'n/a')}",
        ),
        (
            "Elevation error",
            lambda a, r: _metres(
                a["quality"][-1]["elevation_vs_fine_reference"]["rmse_m"]
            ),
        ),
        (
            "Elevation coverage",
            lambda a, r: (
                "n/a"
                if a["quality"][-1]["elevation_vs_fine_reference"].get("coverage")
                is None
                else f"{a['quality'][-1]['elevation_vs_fine_reference']['coverage']:.1%}"
            ),
        ),
        (
            "Seam/boundary ownership",
            lambda a, r: (
                "PASS"
                if a["quality"][-1].get("mixed_resolution_topology", {}).get("status")
                == "valid"
                else "FAIL"
            ),
        ),
        (
            "Point conservation",
            lambda a, r: (
                "PASS"
                if all(q["point_conservation"]["holds"] for q in a["quality"])
                else "FAIL"
            ),
        ),
        (
            "Governor interventions",
            lambda a, r: str(a.get("governor", {}).get("interventions", "n/a")),
        ),
        (
            "Duplicate ownership",
            lambda a, r: (
                "PASS"
                if all(q["duplicate_ownership"]["holds"] for q in a["quality"])
                else "FAIL"
            ),
        ),
        (
            "Semantic retention",
            lambda a, r: _retention(a["quality"][-1], "semantic"),
        ),
        (
            "Terrain hazard retention",
            lambda a, r: _retention(a["quality"][-1], "terrain_hazard"),
        ),
    ]
    lines = ["| " + " | ".join(headers) + " |", "| --- | ---: | ---: | ---: | ---: |"]
    for label, getter in metrics:
        values = []
        for policy in headers[1:]:
            # Policy names use snake_case in JSON while the table uses review names.
            aliases = {
                "Uniform5": "uniform5",
                "Uniform40": "uniform40",
                "DistanceLOD": "distance_lod",
                "UtilityLOD": "utility_lod",
            }
            policy_report = (
                report.get("policies", {}).get(aliases[policy]) if report else None
            )
            values.append(
                "n/a"
                if not policy_report
                else str(getter(policy_report["aggregate"], policy_report))
            )
        lines.append("| " + " | ".join([label, *values]) + " |")
    return "\n".join(lines)


def _perception_table(report: dict[str, Any] | None) -> str:
    lines = ["| Stage | p50 | p95 | p99 |", "| --- | ---: | ---: | ---: |"]
    if not report:
        return "\n".join(lines + ["| unavailable | n/a | n/a | n/a |"])
    aliases = {
        "dataset_load": "Dataset load",
        "load": "Dataset load",
        "semantic": "SalsaNext",
        "ground": "Patchwork++",
        "terrain": "Terrain",
        "temporal": "Temporal",
        "bridge": "Bridge",
        "total": "Total perception",
        "end_to_end": "End-to-end",
    }
    for key, values in report.get("timings", {}).items():
        lines.append(
            f"| {aliases.get(key, key)} | {values['p50_ms']:.2f} ms | {values['p95_ms']:.2f} ms | {values['p99_ms']:.2f} ms |"
        )
    return "\n".join(lines)


def _perception_status_summary(report: dict[str, Any] | None) -> str:
    statuses = (report or {}).get("status", {})
    if not statuses:
        return "Backend status: unavailable."
    return (
        "Backend status: "
        + ", ".join(f"{name}=`{statuses[name]}`" for name in sorted(statuses))
        + "."
    )


def _ablation_table(report: dict[str, Any] | None) -> str:
    ablation = (report or {}).get("utility_ablation")
    if not isinstance(ablation, dict):
        return "Ablation matrix was not included in this artifact."
    members = ablation.get("members", {})
    lines = [
        "| Variant | Signals | RMSE | Δ RMSE | Sem. retain | Hazard retain | p95 map | Δ RSS |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ablation.get("required_policies", []):
        member = members.get(name)
        if not member:
            lines.append(f"| {name} | not run | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        measured = member["measurements"]
        delta = member["delta_vs_distance"]
        rss_delta = delta["peak_rss_fraction"]

        def percentage(value: float | None) -> str:
            return "n/a" if value is None else f"{float(value):.1%}"

        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    ", ".join(member["signals"]) or "distance only",
                    _metres(measured["elevation_rmse_m"]),
                    _metres(delta["elevation_rmse_m"]),
                    percentage(measured.get("semantic_retention_fraction")),
                    percentage(measured.get("terrain_hazard_retention_fraction")),
                    _ms(measured["map_latency_p95_ns"]),
                    "n/a" if rss_delta is None else f"{rss_delta:+.1%}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            (
                f"Status: **{ablation.get('status', 'unknown')}**. Full vs distance: "
                f"`{ablation.get('full_vs_distance_assessment', 'unavailable')}`."
            ),
        ]
    )
    return "\n".join(lines)


def _semantic_quality_summary(report: dict[str, Any] | None) -> str:
    quality = (report or {}).get("semantic_quality")
    if not quality or quality.get("status") != "measured":
        return "Range-binned semantic quality: unavailable (no paired labels)."
    overall = quality.get("overall", {})
    bins = quality.get("range_bins", [])
    lines = [
        "| Range | Points | Accuracy | mIoU |",
        "| --- | ---: | ---: | ---: |",
        f"| Overall | {overall.get('points', 0):,} | {overall.get('accuracy', 0):.1%} | {overall.get('miou', 0):.1%} |",
    ]
    for item in bins:
        accuracy = item.get("accuracy")
        miou = item.get("miou")
        lines.append(
            f"| {item['min_m']:.0f}–{item['max_m']:.0f} m | {item.get('points', 0):,} | "
            f"{'n/a' if accuracy is None else f'{accuracy:.1%}'} | "
            f"{'n/a' if miou is None else f'{miou:.1%}'} |"
        )
    return "\n".join(lines)


def _field_retention_summary(report: dict[str, Any] | None) -> str:
    quality = (report or {}).get("policies", {})
    unavailable: set[str] = set()
    seen = False
    for policy in quality.values():
        for item in policy.get("aggregate", {}).get("quality", []):
            for name, value in item.get("field_retention", {}).items():
                if name == "status":
                    continue
                seen = True
                if isinstance(value, dict):
                    if value.get("status") != "measured":
                        unavailable.add(f"{name}: {value.get('reason', 'unavailable')}")
                else:
                    unavailable.add(f"{name}: {value}")
    return (
        "Field retention: unavailable (" + "; ".join(sorted(unavailable)) + ")."
        if unavailable or not seen
        else "Field retention: measured for semantic and terrain hazard evidence."
    )


def _hard_failure(
    mapping: dict[str, Any] | None, perception: dict[str, Any] | None
) -> bool:
    if mapping is None or perception is None:
        return True
    if not mapping.get("policies") or not perception.get("timings"):
        return True
    if any(
        not quality["point_conservation"]["holds"]
        or not quality["duplicate_ownership"]["holds"]
        or quality.get("mixed_resolution_topology", {}).get("status") == "invalid"
        for policy in mapping.get("policies", {}).values()
        for quality in policy.get("aggregate", {}).get("quality", [])
    ):
        return True
    semantic = mapping.get("semantic_quality", {})
    if semantic.get("status") == "measured":
        scores = [
            semantic.get("overall", {}).get("accuracy"),
            semantic.get("overall", {}).get("miou"),
        ]
        scores.extend(item.get("accuracy") for item in semantic.get("range_bins", []))
        scores.extend(item.get("miou") for item in semantic.get("range_bins", []))
        if any(
            value is not None
            and (not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0)
            for value in scores
        ):
            return True
    return False


def _performance_warnings(
    mapping: dict[str, Any] | None, baseline: dict[str, Any] | None
) -> list[str]:
    if not mapping or not baseline:
        return []
    warnings = []
    for policy, current_report in mapping.get("policies", {}).items():
        previous_report = baseline.get("policies", {}).get(policy)
        if not previous_report:
            continue
        current = current_report["aggregate"]
        previous = previous_report["aggregate"]
        current_p95 = current["stage_latency_ns"]["map_update"]["p95"]
        previous_p95 = previous["stage_latency_ns"]["map_update"]["p95"]
        if current_p95 > previous_p95 * 1.2:
            warnings.append(f"{policy} p95 map latency increased by more than 20%")
        if (
            current["peak_rss_bytes"]
            and previous["peak_rss_bytes"]
            and current["peak_rss_bytes"] > previous["peak_rss_bytes"] * 1.2
        ):
            warnings.append(f"{policy} peak RSS increased by more than 20%")
    return warnings


def render(
    map_path: Path | None,
    perception_path: Path | None,
    baseline_path: Path | None = None,
) -> str:
    mapping, perception, baseline = (
        _json(map_path),
        _json(perception_path),
        _json(baseline_path),
    )
    provenance = (mapping or {}).get("provenance", {})
    frame = provenance.get("frame_range", {})
    lines = [
        "## Veyra SemanticPOSS benchmark",
        "",
        f"- Dataset: `{(mapping or perception or {}).get('dataset', 'n/a')}` / sequence `{frame.get('sequence', (mapping or perception or {}).get('sequence', 'n/a'))}` / frames `{frame.get('count', 'n/a')}`",
        f"- Commit: `{provenance.get('git_sha', (perception or {}).get('reproducibility', {}).get('git_sha', 'n/a'))}`",
        f"- Dataset SHA-256: `{provenance.get('dataset_sha256', (perception or {}).get('reproducibility', {}).get('dataset_sha256', 'n/a'))}`",
        "",
        "### Map benchmark",
        "",
        _map_table(mapping),
        "",
        "### Reference baseline",
        "",
        _reference_summary(mapping),
        "",
        "### UtilityLOD ablation",
        "",
        _ablation_table(mapping),
        "",
        "### Perception benchmark",
        "",
        _perception_table(perception),
        "",
        _perception_status_summary(perception),
        "",
        "### Range-binned semantic quality",
        "",
        _semantic_quality_summary(mapping),
        "",
        _field_retention_summary(mapping),
        "",
        "### Regression status",
        "",
    ]
    hard_fail = _hard_failure(mapping, perception)
    if baseline:
        warnings = _performance_warnings(mapping, baseline)
        lines.append(
            "Performance comparison: **WARNING** — " + "; ".join(warnings)
            if warnings
            else "Performance comparison: **UNCHANGED/IMPROVED** within the initial 20% hosted-runner tolerance."
        )
    else:
        lines.append(
            "Performance comparison: WARNING — no trusted main baseline artifact was available for this run."
        )
    lines.append(f"Correctness gate: **{'HARD FAILURE' if hard_fail else 'PASS'}**")
    return "\n".join(lines) + "\n"


def _reference_summary(report: dict[str, Any] | None) -> str:
    reference = (report or {}).get("reference_baselines", {}).get("uniform_5cm_3d")
    if not reference:
        return "Analytical 5 cm 3D reference: unavailable."
    return (
        "Analytical 5 cm 3D reference: "
        f"{reference.get('dense_voxel_count', 'n/a'):,} dense voxels, "
        f"{_mb(reference.get('estimated_dense_bytes'))}; "
        "not executed through the map engine and not a measured RSS value."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", type=Path)
    parser.add_argument("--perception", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-correctness", action="store_true")
    args = parser.parse_args()
    rendered = render(args.map, args.perception, args.baseline)
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return (
        1
        if args.fail_on_correctness
        and _hard_failure(_json(args.map), _json(args.perception))
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
