"""Quality-versus-cost plot for benchmark results (dependency-free SVG).

One point per resolution policy: y is a reconstruction metric from
``benchmarks/reconstruction.py`` (Chamfer-L1 by default, lower is better),
x is a measured cost -- map update time per frame (p50, on the recorded
hardware) and the map's logical payload bytes. Several result files (for
example several sequences) may be passed; each becomes its own series.

    python -m benchmarks.tradeoff_plot results/*.json --output tradeoff.svg
"""

from __future__ import annotations

import argparse
import json
import math
from html import escape
from pathlib import Path
from typing import Any

POLICY_LABELS = {
    "uniform5": "Uniform 5 cm",
    "uniform40": "Uniform 40 cm",
    "distance_lod": "DistanceLOD",
    "utility_lod": "UtilityLOD",
}
POLICY_MARKERS = {"uniform5": "square", "uniform40": "triangle", "distance_lod": "circle", "utility_lod": "diamond"}
SERIES_COLORS = ("#2a6fdb", "#d9480f", "#2b8a3e", "#862e9c", "#c92a2a", "#1098ad")
METRICS = {
    "chamfer_l1_m": ("Chamfer-L1 (cm, lower is better)", 100.0),
    "accuracy_m": ("Accuracy (cm, lower is better)", 100.0),
    "completion_m": ("Completion (cm, lower is better)", 100.0),
    "fscore_10cm": ("F-score @ 10 cm (higher is better)", 1.0),
}
COSTS = {
    "time": ("Map update per frame, p50 (ms)", 1e-6),
    "memory": ("Logical map payload (MB)", 1e-6),
}


def policy_points(result: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    """Extract (cost, quality) per policy from one benchmark result."""
    points = []
    for policy, report in result.get("policies", {}).items():
        run = report["runs"][-1]
        rec = run.get("quality", {}).get("reconstruction", {})
        if rec.get("status") != "available":
            continue
        values = {
            "chamfer_l1_m": rec["chamfer_l1_m"],
            "accuracy_m": rec["accuracy"]["mean_m"],
            "completion_m": rec["completion"]["mean_m"],
            "fscore_10cm": next(
                (row["fscore"] for row in rec["thresholds"] if row["threshold_m"] == 0.10),
                None,
            ),
        }
        map_update = report["aggregate"]["stage_latency_ns"]["map_update"]["p50"]
        memory = run["metrics"]["memory"]["logical_map_bytes"]
        if values[metric] is None or map_update is None or memory is None:
            continue
        points.append(
            {
                "policy": policy,
                "quality": float(values[metric]),
                "time": float(map_update),
                "memory": float(memory),
            }
        )
    return points


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    span = high - low or abs(high) or 1.0
    raw = span / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), default=raw)
    start = math.floor(low / step) * step
    # End on the first tick at or above `high` so no point falls off the axis.
    ticks, value = [], start
    while not ticks or ticks[-1] < high - step * 1e-9:
        ticks.append(round(value, 10))
        value += step
    return ticks


def _marker(shape: str, x: float, y: float, color: str) -> str:
    if shape == "square":
        return f'<rect x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" fill="{color}"/>'
    if shape == "triangle":
        return f'<path d="M{x:.1f},{y - 7:.1f} L{x + 7:.1f},{y + 6:.1f} L{x - 7:.1f},{y + 6:.1f} Z" fill="{color}"/>'
    if shape == "diamond":
        return f'<path d="M{x:.1f},{y - 7:.1f} L{x + 7:.1f},{y:.1f} L{x:.1f},{y + 7:.1f} L{x - 7:.1f},{y:.1f} Z" fill="{color}"/>'
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>'


def _panel(series, cost: str, metric: str, left: float, top: float, width: float, height: float) -> list[str]:
    x_label, x_scale = COSTS[cost]
    y_label, y_scale = METRICS[metric]
    xs = [p[cost] * x_scale for _, points in series for p in points]
    ys = [p["quality"] * y_scale for _, points in series for p in points]
    x_ticks = _ticks(0.0, max(xs) * 1.08)
    y_ticks = _ticks(0.0, max(ys) * 1.12)
    x_max, y_max = x_ticks[-1] or 1.0, y_ticks[-1] or 1.0

    def px(value: float) -> float:
        return left + value / x_max * width

    def py(value: float) -> float:
        return top + height - value / y_max * height

    out = [f'<rect x="{left}" y="{top}" width="{width}" height="{height}" fill="none" stroke="#adb5bd"/>']
    for tick in x_ticks:
        out.append(f'<line x1="{px(tick):.1f}" y1="{top}" x2="{px(tick):.1f}" y2="{top + height}" stroke="#e9ecef"/>')
        out.append(f'<text x="{px(tick):.1f}" y="{top + height + 16}" text-anchor="middle" font-size="11">{tick:g}</text>')
    for tick in y_ticks:
        out.append(f'<line x1="{left}" y1="{py(tick):.1f}" x2="{left + width}" y2="{py(tick):.1f}" stroke="#e9ecef"/>')
        out.append(f'<text x="{left - 6}" y="{py(tick) + 4:.1f}" text-anchor="end" font-size="11">{tick:g}</text>')
    out.append(f'<text x="{left + width / 2}" y="{top + height + 36}" text-anchor="middle" font-size="12">{escape(x_label)}</text>')
    out.append(
        f'<text x="{left - 44}" y="{top + height / 2}" text-anchor="middle" font-size="12" '
        f'transform="rotate(-90 {left - 44} {top + height / 2})">{escape(y_label)}</text>'
    )
    for index, (_name, points) in enumerate(series):
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        for point in points:
            x, y = px(point[cost] * x_scale), py(point["quality"] * y_scale)
            # Shape identifies the policy and colour the series (see legends);
            # per-point labels collide when policies land close together.
            out.append(_marker(POLICY_MARKERS.get(point["policy"], "circle"), x, y, color))
    return out


def render_svg(series: list[tuple[str, list[dict[str, Any]]]], metric: str, title: str) -> str:
    """Two panels side by side: quality versus time, quality versus memory."""
    if not any(points for _, points in series):
        raise ValueError("no policy has an available reconstruction report")
    width, height = 1000, 500
    body = [
        f'<text x="{width / 2}" y="26" text-anchor="middle" font-size="15" font-weight="600">{escape(title)}</text>'
    ]
    body += _panel(series, "time", metric, 80, 50, 380, 330)
    body += _panel(series, "memory", metric, 580, 50, 380, 330)
    policies = [p for p in POLICY_LABELS if any(q["policy"] == p for _, pts in series for q in pts)]
    for index, policy in enumerate(policies):
        x, y = 80 + index * 150, height - 52
        body.append(_marker(POLICY_MARKERS.get(policy, "circle"), x + 5, y - 4, "#495057"))
        body.append(f'<text x="{x + 16}" y="{y}" font-size="11">{escape(POLICY_LABELS[policy])}</text>')
    for index, (name, _points) in enumerate(series):
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        x, y = 80 + index * 150, height - 22
        body.append(f'<rect x="{x}" y="{y - 9}" width="10" height="10" fill="{color}"/>')
        body.append(f'<text x="{x + 16}" y="{y}" font-size="11">{escape(name)}</text>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif">'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>' + "".join(body) + "</svg>\n"
    )


def series_name(result: dict[str, Any], path: Path) -> str:
    dataset, sequence = result.get("dataset"), result.get("sequence")
    return f"{dataset} {sequence}" if dataset and sequence else path.stem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--metric", choices=sorted(METRICS), default="chamfer_l1_m")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Map quality versus cost per resolution policy")
    args = parser.parse_args(argv)
    series = []
    for path in args.results:
        result = json.loads(path.read_text())
        series.append((series_name(result, path), policy_points(result, args.metric)))
    args.output.write_text(render_svg(series, args.metric, args.title))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
