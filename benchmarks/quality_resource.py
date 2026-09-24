"""Schema-tolerant quality/resource extraction and Pareto comparisons."""

from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path
from typing import Any

PUBLIC_POLICIES = ("uniform5", "uniform40", "distance_lod", "utility_lod")


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _fraction(surface: dict[str, Any], field: str) -> float | None:
    value = _finite(surface.get(field))
    return value if value is not None and 0.0 <= value <= 1.0 else None


def comparison_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one row per public policy; absent measurements stay null."""
    policies = report.get("policies", {})
    rows = []
    for name in PUBLIC_POLICIES:
        policy = policies.get(name)
        if not isinstance(policy, dict):
            rows.append({"policy": name, "status": "unavailable"})
            continue
        runs = policy.get("runs") or []
        run = runs[-1] if runs else {}
        aggregate = policy.get("aggregate") or {}
        quality = run.get("quality") or {}
        quality_repetitions = aggregate.get("quality") or []
        surfaces = [
            item.get("high_resolution_surface_comparison") or {}
            for item in quality_repetitions
            if isinstance(item, dict)
        ] or [quality.get("high_resolution_surface_comparison") or {}]
        surface = surfaces[-1]
        memory = (run.get("metrics") or {}).get("memory") or {}
        latency = (aggregate.get("stage_latency_ns") or {}).get("map_update") or {}
        levels = aggregate.get("final_leaves_per_level") or {}
        retention = quality.get("field_retention") or {}
        task_members = (retention.get("task_classes") or {}).get("members") or {}

        def retention_fraction(
            field: str, task_members: dict[str, Any] = task_members
        ) -> float | None:
            item = task_members.get(field) or {}
            return _fraction(item, "retention_fraction")

        def mean_fraction(
            field: str, surfaces: list[dict[str, Any]] = surfaces
        ) -> float | None:
            measured = [
                value
                for item in surfaces
                if (value := _fraction(item, field)) is not None
            ]
            return sum(measured) / len(measured) if measured else None

        def mean_number(
            field: str,
            alias: str | None = None,
            surfaces: list[dict[str, Any]] = surfaces,
        ) -> float | None:
            measured = [
                number
                for item in surfaces
                if (
                    number := _finite(
                        item.get(field, item.get(alias) if alias else None)
                    )
                )
                is not None
            ]
            return sum(measured) / len(measured) if measured else None

        status = surface.get("status", "unavailable")
        runtime_ms = _ns_to_ms(
            ((aggregate.get("stage_latency_ns") or {}).get("frame_pipeline") or {}).get(
                "p50"
            )
        )
        rows.append(
            {
                "policy": name,
                "status": status,
                "logical_map_bytes": _finite(memory.get("logical_map_bytes")),
                "allocated_map_bytes": _finite(memory.get("allocated_map_bytes")),
                "rss_bytes": _finite(aggregate.get("peak_rss_bytes")),
                "active_cells": sum(int(value) for value in levels.values())
                if levels
                else None,
                "map_update_p50_ms": _ns_to_ms(latency.get("p50")),
                "map_update_p95_ms": _ns_to_ms(latency.get("p95")),
                "map_update_p99_ms": _ns_to_ms(latency.get("p99")),
                "map_update_sample_count": _finite(latency.get("count")),
                "map_update_p95_reliable": _finite(latency.get("count")) is not None
                and _finite(latency.get("count")) >= 20,
                "map_update_p99_reliable": _finite(latency.get("count")) is not None
                and _finite(latency.get("count")) >= 100,
                "runtime_per_frame_ms": runtime_ms,
                "runtime_ms": runtime_ms,
                "processing_fps_p50": _finite((aggregate.get("fps") or {}).get("p50")),
                "height_accuracy_05cm": mean_fraction("height_accuracy_05cm"),
                "height_accuracy_10cm": mean_fraction("height_accuracy_10cm"),
                "height_accuracy_20cm": mean_fraction("height_accuracy_20cm"),
                "completion_fraction": mean_fraction("completion_fraction"),
                "symmetric_chamfer_m": mean_number(
                    "symmetric_chamfer_m", "chamfer_distance_m"
                ),
                "chamfer_distance_m": mean_number(
                    "chamfer_distance_m", "symmetric_chamfer_m"
                ),
                "elevation_rmse_m": mean_number("elevation_rmse_m"),
                "semantic_retention_fraction": _fraction(
                    retention.get("semantic") or {}, "retention_fraction"
                ),
                "pedestrian_retention_fraction": retention_fraction("pedestrian"),
                "pole_retention_fraction": retention_fraction("pole"),
                "vehicle_retention_fraction": retention_fraction("vehicle"),
                "reference": surface.get("reference"),
                "reference_is_ground_truth": surface.get("reference_is_ground_truth"),
                "reference_bins": surface.get("reference_bins"),
                "matched_bins": surface.get("matched_bins"),
            }
        )
    return rows


def _ns_to_ms(value: Any) -> float | None:
    number = _finite(value)
    return None if number is None else number / 1_000_000.0


def pareto_frontier(
    rows: list[dict[str, Any]],
    *,
    x_metric: str,
    x_direction: str,
    y_metric: str,
    y_direction: str,
) -> dict[str, Any]:
    """Compute a two-objective frontier without weighted/scalar scores."""
    if x_direction not in {"min", "max"} or y_direction not in {"min", "max"}:
        raise ValueError("Pareto directions must be 'min' or 'max'")
    valid: list[tuple[str, float, float]] = []
    unavailable = []
    for row in rows:
        name = str(row.get("policy", ""))
        x, y = _finite(row.get(x_metric)), _finite(row.get(y_metric))
        if not name or x is None or y is None:
            if name:
                unavailable.append(name)
            continue
        valid.append((name, x, y))

    def no_worse(a: float, b: float, direction: str) -> bool:
        return a <= b if direction == "min" else a >= b

    def strictly_better(a: float, b: float, direction: str) -> bool:
        return a < b if direction == "min" else a > b

    dominated: dict[str, list[str]] = {}
    frontier = []
    for name, x, y in valid:
        dominators = [
            other_name
            for other_name, other_x, other_y in valid
            if other_name != name
            and no_worse(other_x, x, x_direction)
            and no_worse(other_y, y, y_direction)
            and (
                strictly_better(other_x, x, x_direction)
                or strictly_better(other_y, y, y_direction)
            )
        ]
        if dominators:
            dominated[name] = sorted(dominators)
        else:
            frontier.append(name)
    return {
        "x_metric": x_metric,
        "x_direction": x_direction,
        "y_metric": y_metric,
        "y_direction": y_direction,
        "frontier": sorted(frontier),
        "dominated": dominated,
        "unavailable": sorted(unavailable),
        "weighted_score_used": False,
    }


def pareto_summary(
    rows: list[dict[str, Any]], *, latency_metric: str = "map_update_p95_ms"
) -> dict[str, Any]:
    if latency_metric not in {"map_update_p50_ms", "map_update_p95_ms"}:
        raise ValueError("latency_metric must be a supported map-update percentile")
    comparisons = {
        "memory_vs_height_accuracy": (
            "logical_map_bytes",
            "min",
            "height_accuracy_10cm",
            "max",
        ),
        "memory_vs_completion": (
            "logical_map_bytes",
            "min",
            "completion_fraction",
            "max",
        ),
        "memory_vs_chamfer": ("logical_map_bytes", "min", "symmetric_chamfer_m", "min"),
        "rss_vs_height_accuracy": ("rss_bytes", "min", "height_accuracy_10cm", "max"),
        "rss_vs_completion": ("rss_bytes", "min", "completion_fraction", "max"),
        "rss_vs_chamfer": ("rss_bytes", "min", "symmetric_chamfer_m", "min"),
        "latency_vs_height_accuracy": (
            latency_metric,
            "min",
            "height_accuracy_10cm",
            "max",
        ),
        "latency_vs_completion": (latency_metric, "min", "completion_fraction", "max"),
        "latency_vs_chamfer": (latency_metric, "min", "symmetric_chamfer_m", "min"),
        "joint_resource_quality": (
            "logical_map_bytes,map_update_p95_ms,height_accuracy_10cm,completion_fraction,symmetric_chamfer_m",
            "mixed",
            "see_objectives",
            "mixed",
        ),
    }
    result = {
        name: pareto_frontier(
            rows,
            x_metric=axes[0],
            x_direction=axes[1],
            y_metric=axes[2],
            y_direction=axes[3],
        )
        for name, axes in comparisons.items()
        if name != "joint_resource_quality"
    }
    objectives = (
        ("logical_map_bytes", "min"),
        (latency_metric, "min"),
        ("height_accuracy_10cm", "max"),
        ("completion_fraction", "max"),
        ("symmetric_chamfer_m", "min"),
    )
    valid_rows = [
        row
        for row in rows
        if all(_finite(row.get(metric)) is not None for metric, _ in objectives)
    ]
    joint_dominated: dict[str, list[str]] = {}
    for row in valid_rows:
        dominators = []
        for candidate in valid_rows:
            if candidate is row:
                continue
            no_worse = all(
                (float(candidate[metric]) <= float(row[metric]))
                if direction == "min"
                else (float(candidate[metric]) >= float(row[metric]))
                for metric, direction in objectives
            )
            strictly_better = any(
                (float(candidate[metric]) < float(row[metric]))
                if direction == "min"
                else (float(candidate[metric]) > float(row[metric]))
                for metric, direction in objectives
            )
            if no_worse and strictly_better:
                dominators.append(str(candidate["policy"]))
        if dominators:
            joint_dominated[str(row["policy"])] = sorted(dominators)
    result["joint_resource_quality"] = {
        "objectives": [
            {"metric": metric, "direction": direction}
            for metric, direction in objectives
        ],
        "frontier": sorted(
            str(row["policy"])
            for row in valid_rows
            if str(row["policy"]) not in joint_dominated
        ),
        "dominated": joint_dominated,
        "unavailable": sorted(
            str(row.get("policy"))
            for row in rows
            if row not in valid_rows and row.get("policy")
        ),
        "weighted_score_used": False,
    }
    return result


def build_quality_resource_report(report: dict[str, Any]) -> dict[str, Any]:
    """Attach policy-neutral quality/resource rows and unweighted frontiers."""
    rows = comparison_rows(report)
    required = (
        "logical_map_bytes",
        "map_update_p95_ms",
        "height_accuracy_10cm",
        "completion_fraction",
        "chamfer_distance_m",
        "elevation_rmse_m",
    )
    measured = [
        row
        for row in rows
        if all(_finite(row.get(metric)) is not None for metric in required)
    ]
    latency_p95_is_reliable = len(rows) == len(PUBLIC_POLICIES) and all(
        row.get("map_update_p95_reliable") is True for row in rows
    )
    latency_plot_metric = (
        "map_update_p95_ms" if latency_p95_is_reliable else "map_update_p50_ms"
    )
    provenance = report.get("provenance") or {}
    input_stream_digests: dict[str, str] = {}
    for name in PUBLIC_POLICIES:
        policy = report.get("policies", {}).get(name) or {}
        runs = policy.get("runs") or []
        digest = runs[-1].get("stream_digest") if runs else None
        if isinstance(digest, str) and digest:
            input_stream_digests[name] = digest
    stream_digests = list(input_stream_digests.values())
    same_input = (
        len(stream_digests) == len(PUBLIC_POLICIES)
        and all(isinstance(digest, str) and digest for digest in stream_digests)
        and len(set(stream_digests)) == 1
    )
    return {
        "schema_version": 1,
        "status": "measured"
        if len(measured) == len(PUBLIC_POLICIES) and same_input
        else "partial",
        "dataset": report.get("dataset"),
        "sequence": report.get("sequence"),
        "frame_range": provenance.get("frame_range"),
        "selection_digest": provenance.get("selection_digest"),
        "same_input_for_all_policies": same_input,
        "input_stream_digests": input_stream_digests,
        "reference": {
            "name": "Uniform5 high-resolution representation",
            "is_ground_truth": False,
            "definition": (
                "Observed Uniform5 map support from the same dataset selection, "
                "poses, accepted observations, and world coordinate frame; not surveyed truth."
            ),
        },
        "metric_definitions": {
            "height_accuracy_10cm": "matched common 5cm XY bins with absolute elevation error <= 0.10m; higher is better",
            "completion_fraction": "uniquely owned valid reference bins / all valid Uniform5 reference bins; higher is better",
            "chamfer_distance_m": "mean of the two directed unsquared 3D nearest-neighbour distances in metres on matched common-support bins; lower is better",
            "elevation_rmse_m": "root mean square vertical error in metres on matched common-support bins; lower is better",
            "map_update_p95_ms": "95th percentile C++ map-update call latency; excludes parsing, snapshots, and serialization",
            "runtime_per_frame_ms": "median C++ frame_pipeline latency per processed frame; not perception or renderer latency",
            "latency_frontier": "uses map-update p95 only when all four policies have at least 20 samples; otherwise uses map-update p50",
            "logical_map_bytes": "logical map payload accounting, distinct from process RSS",
            "rss_bytes": "measured benchmark process peak RSS; includes non-map process memory",
        },
        "policies": rows,
        "measured_policy_count": len(measured),
        "unavailable_policies": [
            row["policy"] for row in rows if row.get("status") == "unavailable"
        ],
        "latency_plot_metric": latency_plot_metric,
        "pareto": pareto_summary(rows, latency_metric=latency_plot_metric),
        "weighted_score_used": False,
    }


_PLOT_SPECS = (
    (
        "memory_vs_height_accuracy",
        "logical_map_bytes",
        "height_accuracy_10cm",
        "Logical map memory (MiB; lower is better)",
        "Height accuracy @ 10cm (higher is better)",
        "memory_vs_height_accuracy",
    ),
    (
        "memory_vs_completion",
        "logical_map_bytes",
        "completion_fraction",
        "Logical map memory (MiB; lower is better)",
        "Completion fraction (higher is better)",
        "memory_vs_completion",
    ),
    (
        "memory_vs_chamfer",
        "logical_map_bytes",
        "chamfer_distance_m",
        "Logical map memory (MiB; lower is better)",
        "Symmetric Chamfer (m; lower is better)",
        "memory_vs_chamfer",
    ),
    (
        "rss_vs_height_accuracy",
        "rss_bytes",
        "height_accuracy_10cm",
        "Measured process peak RSS (MiB; lower is better)",
        "Height accuracy @ 10cm (higher is better)",
        "rss_vs_height_accuracy",
    ),
    (
        "rss_vs_completion",
        "rss_bytes",
        "completion_fraction",
        "Measured process peak RSS (MiB; lower is better)",
        "Completion fraction (higher is better)",
        "rss_vs_completion",
    ),
    (
        "rss_vs_chamfer",
        "rss_bytes",
        "chamfer_distance_m",
        "Measured process peak RSS (MiB; lower is better)",
        "Symmetric Chamfer (m; lower is better)",
        "rss_vs_chamfer",
    ),
)
_DISPLAY = {
    "uniform5": ("Uniform5", "#2576d2"),
    "uniform40": ("Uniform40", "#e38a24"),
    "distance_lod": ("DistanceLOD", "#18946b"),
    "utility_lod": ("UtilityLOD", "#a24bc4"),
}


def _plot_svg(
    rows: list[dict[str, Any]],
    *,
    name: str,
    x_metric: str,
    y_metric: str,
    x_label: str,
    y_label: str,
    frontier_name: str,
    latency_metric: str = "map_update_p95_ms",
) -> str:
    width, height = 960, 620
    left, top, right, bottom = 110.0, 72.0, 760.0, 465.0
    points = [
        (row, _finite(row.get(x_metric)), _finite(row.get(y_metric))) for row in rows
    ]
    valid = [(row, x, y) for row, x, y in points if x is not None and y is not None]
    is_memory_metric = x_metric in {"logical_map_bytes", "rss_bytes"}
    x_values = [x / 1048576.0 if is_memory_metric else x for _, x, _ in valid]
    y_values = [y for _, _, y in valid]
    if x_values:
        x_low, x_high = min(x_values), max(x_values)
        x_pad = max((x_high - x_low) * 0.08, abs(x_low) * 0.04, 0.01)
        x_low, x_high = x_low - x_pad, x_high + x_pad
    else:
        x_low, x_high = 0.0, 1.0
    if y_metric in {"height_accuracy_10cm", "completion_fraction"}:
        y_low, y_high = 0.0, 1.0
    elif y_values:
        y_low, y_high = min(y_values), max(y_values)
        y_pad = max((y_high - y_low) * 0.10, abs(y_low) * 0.04, 0.0001)
        y_low, y_high = max(0.0, y_low - y_pad), y_high + y_pad
    else:
        y_low, y_high = 0.0, 1.0
    if x_high <= x_low:
        x_high = x_low + 1.0
    if y_high <= y_low:
        y_high = y_low + 1.0

    def x_position(value: float) -> float:
        scaled = value / 1048576.0 if is_memory_metric else value
        return left + (scaled - x_low) / (x_high - x_low) * (right - left)

    def y_position(value: float) -> float:
        return bottom - (value - y_low) / (y_high - y_low) * (bottom - top)

    frontier = set(
        pareto_summary(rows, latency_metric=latency_metric)
        .get(frontier_name, {})
        .get("frontier", [])
    )
    title = name.replace("_", " ").title()
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{left}" y="34" font-family="sans-serif" font-size="21" font-weight="600" fill="#17202b">{html.escape(title)}</text>',
        f'<text x="{left}" y="56" font-family="sans-serif" font-size="12" fill="#596575">Same input; Uniform5 is a representation reference, not ground truth.</text>',
    ]
    for tick in range(6):
        fraction = tick / 5.0
        x_value = x_low + fraction * (x_high - x_low)
        y_value = y_low + fraction * (y_high - y_low)
        x = left + fraction * (right - left)
        y = bottom - fraction * (bottom - top)
        x_text = f"{x_value:.3g}"
        lines.extend(
            [
                f'<line x1="{x}" y1="{top}" x2="{x}" y2="{bottom}" stroke="#e4e9ef"/>',
                f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#e4e9ef"/>',
                f'<text x="{x}" y="{bottom + 22}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#596575">{html.escape(x_text)}</text>',
                f'<text x="{left - 10}" y="{y + 4}" text-anchor="end" font-family="sans-serif" font-size="11" fill="#596575">{y_value:.3g}</text>',
            ]
        )
    lines.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#344054" stroke-width="1.5"/>',
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#344054" stroke-width="1.5"/>',
            f'<text x="{(left + right) / 2}" y="{bottom + 50}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#17202b">{html.escape(x_label)}</text>',
            f'<text x="24" y="{(top + bottom) / 2}" transform="rotate(-90 24 {(top + bottom) / 2})" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#17202b">{html.escape(y_label)}</text>',
        ]
    )
    by_policy = {row.get("policy"): row for row in rows}
    for index, policy in enumerate(PUBLIC_POLICIES):
        display, color = _DISPLAY[policy]
        row = by_policy.get(policy, {})
        value_x, value_y = _finite(row.get(x_metric)), _finite(row.get(y_metric))
        legend_y = top + 26 + index * 28
        if value_x is not None and value_y is not None:
            x = x_position(value_x)
            y = y_position(value_y)
            stroke = "#111827" if policy in frontier else "#ffffff"
            lines.append(
                f'<circle data-policy="{policy}" data-x="{value_x:.12g}" data-y="{value_y:.12g}" cx="{x:.2f}" cy="{y:.2f}" r="7" fill="{color}" stroke="{stroke}" stroke-width="3"/>'
            )
            legend_label = display + (" [Pareto]" if policy in frontier else "")
        else:
            legend_label = display + " (unavailable)"
        lines.extend(
            [
                f'<circle cx="{right + 24}" cy="{legend_y - 4}" r="6" fill="{color}"/>',
                f'<text x="{right + 38}" y="{legend_y}" font-family="sans-serif" font-size="12" fill="#344054">{html.escape(legend_label)}</text>',
            ]
        )
    lines.extend(
        [
            f'<text x="{left}" y="{height - 30}" font-family="sans-serif" font-size="11" fill="#596575">Pareto-efficient points outlined in dark; no weighted score is used.</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def write_quality_resource_artifacts(
    report: dict[str, Any], output_dir: str | Path
) -> dict[str, Any]:
    """Write reproducible JSON/CSV tables and dependency-free vector plots."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary = report.get("quality_resource") or build_quality_resource_report(report)
    json_path = destination / "quality_resource_table.json"
    csv_path = destination / "quality_resource_table.csv"
    pareto_path = destination / "pareto_summary.json"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    pareto_path.write_text(
        json.dumps(summary["pareto"], indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    fields = (
        "policy",
        "status",
        "logical_map_bytes",
        "allocated_map_bytes",
        "rss_bytes",
        "active_cells",
        "map_update_p50_ms",
        "map_update_p95_ms",
        "map_update_p99_ms",
        "map_update_sample_count",
        "map_update_p95_reliable",
        "map_update_p99_reliable",
        "runtime_per_frame_ms",
        "runtime_ms",
        "processing_fps_p50",
        "height_accuracy_05cm",
        "height_accuracy_10cm",
        "height_accuracy_20cm",
        "completion_fraction",
        "chamfer_distance_m",
        "elevation_rmse_m",
        "semantic_retention_fraction",
        "pedestrian_retention_fraction",
        "pole_retention_fraction",
        "vehicle_retention_fraction",
        "reference_bins",
        "matched_bins",
        "reference_is_ground_truth",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary["policies"])

    latency_metric = summary.get("latency_plot_metric", "map_update_p95_ms")
    percentile = "p95" if latency_metric == "map_update_p95_ms" else "p50"
    plot_specs = (
        *_PLOT_SPECS,
        (
            "latency_vs_height_accuracy",
            latency_metric,
            "height_accuracy_10cm",
            f"Map-update {percentile} latency (ms; lower is better)",
            "Height accuracy @ 10cm (higher is better)",
            "latency_vs_height_accuracy",
        ),
        (
            "latency_vs_completion",
            latency_metric,
            "completion_fraction",
            f"Map-update {percentile} latency (ms; lower is better)",
            "Completion fraction (higher is better)",
            "latency_vs_completion",
        ),
        (
            "latency_vs_chamfer",
            latency_metric,
            "chamfer_distance_m",
            f"Map-update {percentile} latency (ms; lower is better)",
            "Symmetric Chamfer (m; lower is better)",
            "latency_vs_chamfer",
        ),
    )
    plots: dict[str, str] = {}
    for name, x_metric, y_metric, x_label, y_label, frontier_name in plot_specs:
        plot_path = destination / f"{name}.svg"
        plot_path.write_text(
            _plot_svg(
                summary["policies"],
                name=name,
                x_metric=x_metric,
                y_metric=y_metric,
                x_label=x_label,
                y_label=y_label,
                frontier_name=frontier_name,
                latency_metric=latency_metric,
            ),
            encoding="utf-8",
        )
        plots[name] = str(plot_path)
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "pareto": str(pareto_path),
        "plots": plots,
    }


__all__ = [
    "build_quality_resource_report",
    "comparison_rows",
    "pareto_frontier",
    "pareto_summary",
    "write_quality_resource_artifacts",
]
