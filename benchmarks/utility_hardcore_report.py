"""Small dependency-free diagnostic artifacts for frozen UtilityLOD challenges.

Plots use only measured row values. Empty plots explicitly say UNAVAILABLE.
"""

from __future__ import annotations

import csv
import html
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


SIGNALS = (
    "geometry",
    "semantic",
    "motion",
    "traversability_risk",
    "semantic_uncertainty",
)
COLORS = {
    "uniform5": "#16a6aa",
    "uniform40": "#737d8c",
    "distance_lod": "#3576dc",
    "utility_lod": "#da6a32",
    "a1_geometry": "#84943b",
    "a2_semantics": "#9b63bc",
    "a3_geometry_semantics": "#bd8648",
    "a4_geometry_semantics_motion": "#ca4f91",
}


def _unique_telemetry(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, float | None]] = set()
    selected = []
    for row in rows:
        key = (row["selection_digest"], row["policy"], row["budget_fraction"])
        if key not in seen and row.get("promotion_telemetry"):
            seen.add(key)
            selected.append(row)
    return selected


def _quantile_from_histogram(bins: list[int], fraction: float) -> float | None:
    total = sum(bins)
    if not total:
        return None
    rank = math.ceil(total * fraction)
    cumulative = 0
    for index, count in enumerate(bins):
        cumulative += count
        if cumulative >= rank:
            return (index + 0.5) / len(bins)
    return None


def signal_distributions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [
        row for row in _unique_telemetry(rows) if row["policy"] == "utility_lod"
    ]
    histograms = {name: [0] * 20 for name in (*SIGNALS, "utility_score")}
    exact_zero = defaultdict(int)
    near_one = defaultdict(int)
    weighted = defaultdict(float)
    raw = defaultdict(float)
    transitions = defaultdict(int)
    extrema: dict[str, tuple[float, float]] = {}
    above_split = below_merge = 0
    for row in selected:
        telemetry = row["promotion_telemetry"]
        for name in SIGNALS:
            signal = telemetry["signals"][name]
            histograms[name] = [
                a + int(b)
                for a, b in zip(histograms[name], signal["histogram"], strict=True)
            ]
            exact_zero[name] += int(signal["exact_zero_count"])
            near_one[name] += int(signal["near_one_count"])
            raw[name] += float(signal["raw_sum"])
            weighted[name] += float(signal["weighted_sum"])
            observed = (float(signal.get("min", 0.0)), float(signal.get("max", 0.0)))
            extrema[name] = (
                (min(extrema[name][0], observed[0]), max(extrema[name][1], observed[1]))
                if name in extrema
                else observed
            )
        histograms["utility_score"] = [
            a + int(b)
            for a, b in zip(
                histograms["utility_score"], telemetry["utility_histogram"], strict=True
            )
        ]
        exact_zero["utility_score"] += int(telemetry["utility_exact_zero_count"])
        near_one["utility_score"] += int(telemetry["utility_near_one_count"])
        observed_utility = (
            float(telemetry.get("utility_min", 0.0)),
            float(telemetry.get("utility_max", 0.0)),
        )
        extrema["utility_score"] = (
            (
                min(extrema["utility_score"][0], observed_utility[0]),
                max(extrema["utility_score"][1], observed_utility[1]),
            )
            if "utility_score" in extrema
            else observed_utility
        )
        above_split += int(telemetry.get("utility_above_split_count", 0))
        below_merge += int(telemetry.get("utility_below_merge_count", 0))
        for entry in telemetry["transition_reason_masks"]:
            transitions[int(entry["mask"])] += int(entry["count"])
    distributions = {}
    for name, bins in histograms.items():
        count = sum(bins)
        distributions[name] = {
            "sample_count": count,
            "min": extrema[name][0] if name in extrema else None,
            "max": extrema[name][1] if name in extrema else None,
            "histogram_20_equal_bins_0_to_1": bins,
            "quantiles_are_bin_midpoint_approximations": True,
            "p10": _quantile_from_histogram(bins, 0.1),
            "p25": _quantile_from_histogram(bins, 0.25),
            "p50": _quantile_from_histogram(bins, 0.5),
            "p75": _quantile_from_histogram(bins, 0.75),
            "p90": _quantile_from_histogram(bins, 0.9),
            "p95": _quantile_from_histogram(bins, 0.95),
            "p99": _quantile_from_histogram(bins, 0.99),
            "exact_zero_fraction": exact_zero[name] / count if count else None,
            "near_one_fraction": near_one[name] / count if count else None,
            "raw_mean": raw[name] / count if count and name in SIGNALS else None,
            "weighted_mean": weighted[name] / count
            if count and name in SIGNALS
            else None,
            "above_split_threshold_fraction": above_split / count
            if count and name == "utility_score"
            else None,
            "below_merge_threshold_fraction": below_merge / count
            if count and name == "utility_score"
            else None,
        }
    return {
        "scope": "full UtilityLOD baseline; one telemetry aggregate per unique stream",
        "selection_count": len(selected),
        "distributions": distributions,
        "transition_reason_mask_counts": dict(sorted(transitions.items())),
        "reason_mask_bits": {
            str(i): name
            for i, name in enumerate((*SIGNALS, "safety_override", "predictive"))
        },
        "limitation": "transition mask describes the triggering observation, not all observations in its state cell",
    }


def _csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def _numeric(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _scatter(
    path: Path,
    title: str,
    x_label: str,
    y_label: str,
    points: list[tuple[float, float, str]],
    *,
    note: str = "",
) -> None:
    width, height = 900, 520
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#101820"/>',
        f'<text x="55" y="45" fill="#f0f4f8" font-size="22">{html.escape(title)}</text>',
        f'<text x="55" y="75" fill="#aab9c7" font-size="13">{html.escape(note)}</text>',
    ]
    if points:
        xmin, xmax = min(x for x, _, _ in points), max(x for x, _, _ in points)
        ymin, ymax = min(y for _, y, _ in points), max(y for _, y, _ in points)
        if xmin == xmax:
            xmin -= 0.5
            xmax += 0.5
        if ymin == ymax:
            ymin -= 0.5
            ymax += 0.5
        elements.extend(
            [
                '<path d="M80 95 V445 H855" fill="none" stroke="#667787"/>',
                f'<text x="460" y="490" text-anchor="middle" fill="#c7d4df" font-size="15">{html.escape(x_label)}</text>',
                f'<text x="20" y="275" transform="rotate(-90 20 275)" text-anchor="middle" fill="#c7d4df" font-size="15">{html.escape(y_label)}</text>',
                f'<text x="80" y="465" fill="#91a5b5" font-size="11">{xmin:.3g}</text>',
                f'<text x="855" y="465" text-anchor="end" fill="#91a5b5" font-size="11">{xmax:.3g}</text>',
                f'<text x="70" y="440" text-anchor="end" fill="#91a5b5" font-size="11">{ymin:.3g}</text>',
                f'<text x="70" y="100" text-anchor="end" fill="#91a5b5" font-size="11">{ymax:.3g}</text>',
            ]
        )
        for x, y, policy in points:
            px = 80 + 775 * (x - xmin) / (xmax - xmin)
            py = 445 - 350 * (y - ymin) / (ymax - ymin)
            elements.append(
                f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{COLORS.get(policy, "#e8c35a")}" opacity="0.8"><title>{html.escape(policy)}: {x:.4g}, {y:.4g}</title></circle>'
            )
        legend = " | ".join(sorted({policy for _, _, policy in points}))
        elements.append(
            f'<text x="855" y="45" text-anchor="end" fill="#9db2c1" font-size="11">{html.escape(legend)}</text>'
        )
    else:
        elements.append(
            '<text x="450" y="270" text-anchor="middle" fill="#91a5b5" font-size="22">UNAVAILABLE: no measured values</text>'
        )
    elements.append("</svg>")
    path.write_text("\n".join(elements) + "\n")


def write_diagnostics(destination: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    distribution = signal_distributions(rows)
    (destination / "signal_distributions.json").write_text(
        json.dumps(distribution, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    unique = _unique_telemetry(rows)
    attribution = []
    for row in unique:
        telemetry = row["promotion_telemetry"]
        for name in SIGNALS:
            attribution.append(
                {
                    "dataset": row["dataset"],
                    "policy": row["policy"],
                    "selection_digest": row["selection_digest"],
                    "signal": name,
                    "raw_sum": telemetry["signals"][name]["raw_sum"],
                    "weighted_sum": telemetry["signals"][name]["weighted_sum"],
                    "decisions": telemetry["decisions"],
                    "promotion_transitions": sum(
                        item["count"] for item in telemetry["promotion_transitions"]
                    ),
                    "budget_suppressed": telemetry["budget_suppressed"],
                }
            )
    _csv(
        destination / "promotion_attribution.csv",
        attribution,
        [
            "dataset",
            "policy",
            "selection_digest",
            "signal",
            "raw_sum",
            "weighted_sum",
            "decisions",
            "promotion_transitions",
            "budget_suppressed",
        ],
    )
    utility_rows = [row for row in rows if row["policy"].startswith(("utility", "a"))]
    misses = [
        {
            "challenge_id": row["challenge_id"],
            "policy": row["policy"],
            "eligible_critical_bins": row["promotion_recall_denominator"],
            "missed_critical_bins": row["missed_critical_bins"],
            "root_cause": "not attributable from final topology and aggregate signals alone",
        }
        for row in utility_rows
    ]
    _csv(
        destination / "missed_promotions.csv",
        misses,
        [
            "challenge_id",
            "policy",
            "eligible_critical_bins",
            "missed_critical_bins",
            "root_cause",
        ],
    )
    wasted = [
        {
            "challenge_id": row["challenge_id"],
            "policy": row["policy"],
            "promoted_bins": row["promoted_bins"],
            "wasted_promotion_ratio": row["wasted_promotion_ratio"],
            "definition": "outside frozen region and no absolute elevation-error reduction",
        }
        for row in utility_rows
    ]
    _csv(
        destination / "wasted_promotions.csv",
        wasted,
        [
            "challenge_id",
            "policy",
            "promoted_bins",
            "wasted_promotion_ratio",
            "definition",
        ],
    )
    return distribution


def write_plots(
    destination: Path, rows: list[dict[str, Any]], distribution: dict[str, Any]
) -> None:
    plots = destination / "plots"
    plots.mkdir(exist_ok=True)

    def paired(
        filename: str,
        title: str,
        x_field: str,
        y_field: str,
        x_scale: float = 1.0,
        allowed: set[str] | None = None,
    ) -> None:
        points = []
        for row in rows:
            if allowed is not None and row["policy"] not in allowed:
                continue
            x, y = _numeric(row.get(x_field)), _numeric(row.get(y_field))
            if x is not None and y is not None:
                points.append((x / x_scale, y, row["policy"]))
        _scatter(
            plots / filename,
            title,
            x_field.replace("_", " "),
            y_field.replace("_", " "),
            points,
            note="Measured challenge rows; colors identify policies, hover for values",
        )

    paired(
        "01_critical_retention_vs_memory.svg",
        "Critical semantic retention vs logical memory",
        "logical_map_bytes",
        "semantic_retention_critical",
        1e6,
    )
    paired(
        "02_critical_accuracy_vs_memory.svg",
        "Critical 10 cm height accuracy vs logical memory",
        "logical_map_bytes",
        "critical_accuracy_10cm",
        1e6,
    )
    paired(
        "03_critical_chamfer_vs_memory.svg",
        "Critical Chamfer vs logical memory",
        "logical_map_bytes",
        "critical_chamfer_m",
        1e6,
    )
    paired(
        "04_critical_retention_vs_latency.svg",
        "Critical retention vs map p95",
        "map_p95_ms",
        "semantic_retention_critical",
    )
    budget_names = {row["policy"] for row in rows if row["budget_fraction"] is not None}
    paired(
        "05_budget_vs_retention.svg",
        "Utility budget vs critical retention",
        "budget_fraction",
        "semantic_retention_critical",
        allowed=budget_names,
    )
    paired(
        "06_budget_vs_memory.svg",
        "Utility budget vs logical bytes",
        "budget_fraction",
        "logical_map_bytes",
        allowed=budget_names,
    )
    paired(
        "07_precision_vs_budget.svg",
        "Promotion precision vs budget",
        "budget_fraction",
        "promotion_precision",
        allowed=budget_names,
    )
    paired(
        "08_recall_vs_budget.svg",
        "Promotion recall vs budget",
        "budget_fraction",
        "promotion_recall",
        allowed=budget_names,
    )
    reason_points = [
        (float(mask), float(count), "utility_lod")
        for mask, count in distribution["transition_reason_mask_counts"].items()
    ]
    _scatter(
        plots / "09_promotions_by_signal_mask.svg",
        "Promotion transitions by reason mask",
        "bit mask",
        "transitions",
        reason_points,
        note="Bits: geometry, semantic, motion, terrain, uncertainty, safety, predictive",
    )
    type_index = {
        name: index
        for index, name in enumerate(sorted({row["challenge_type"] for row in rows}))
    }
    _scatter(
        plots / "10_wasted_ratio_by_type.svg",
        "Wasted promotion ratio by challenge type",
        "challenge type index",
        "wasted ratio",
        [
            (float(type_index[row["challenge_type"]]), value, row["policy"])
            for row in rows
            if row["policy"] == "utility_lod"
            and (value := _numeric(row.get("wasted_promotion_ratio"))) is not None
        ],
        note="Type index: "
        + ", ".join(f"{index}={name}" for name, index in type_index.items()),
    )
    signal_points = [
        (float(bin_index) / 20, float(count) / max(1, data["sample_count"]), name)
        for name, data in distribution["distributions"].items()
        for bin_index, count in enumerate(data["histogram_20_equal_bins_0_to_1"])
    ]
    _scatter(
        plots / "11_signal_distributions.svg",
        "Utility signal distributions",
        "score bin lower bound",
        "fraction",
        signal_points,
        note="20 equal bins; points reflect measured policy decisions",
    )
    paired(
        "12_churn_vs_budget.svg",
        "Topology churn vs budget",
        "budget_fraction",
        "topology_churn_p95",
        allowed=budget_names,
    )
    lookup = {
        (row["challenge_id"], row["policy"]): row
        for row in rows
        if row["budget_fraction"] is None
    }
    object_points = []
    for challenge_id in {
        row["challenge_id"]
        for row in rows
        if row["challenge_type"] == "semantic_object"
    }:
        distance, utility = (
            lookup.get((challenge_id, "distance_lod")),
            lookup.get((challenge_id, "utility_lod")),
        )
        if distance and utility:
            x, y = (
                _numeric(distance["semantic_retention_critical"]),
                _numeric(utility["semantic_retention_critical"]),
            )
            if x is not None and y is not None:
                object_points.append((x, y, utility["relevant_class"] or "object"))
    _scatter(
        plots / "13_per_object_retention.svg",
        "Distance vs Utility object-patch retention",
        "Distance retention",
        "Utility retention",
        object_points,
    )
    gain_points = []
    for challenge_id in {row["challenge_id"] for row in rows}:
        distance, utility = (
            lookup.get((challenge_id, "distance_lod")),
            lookup.get((challenge_id, "utility_lod")),
        )
        if distance and utility:
            critical = _numeric(utility["critical_accuracy_10cm"])
            background = _numeric(utility["background_accuracy_10cm"])
            if critical is not None and background is not None:
                gain_points.append(
                    (
                        background - float(distance["background_accuracy_10cm"]),
                        critical - float(distance["critical_accuracy_10cm"]),
                        utility["challenge_type"],
                    )
                )
    _scatter(
        plots / "14_critical_vs_background_gain.svg",
        "Critical vs background height-accuracy gain",
        "background gain",
        "critical gain",
        gain_points,
    )
