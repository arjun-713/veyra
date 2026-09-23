"""Reconstruction quality of a final map against its own input points.

The standard reconstruction metrics (as used by Tanks and Temples, NICE-SLAM
and voxel-map evaluations) compare two point sets:

* **Accuracy** -- distance from each reconstructed point to the nearest
  reference point (is what the map claims actually there?).
* **Completion** -- distance from each reference point to the nearest
  reconstructed point (is what was observed still represented?).
* **Chamfer-L1** -- the mean of the two, plus precision / recall / F-score at
  fixed distance thresholds.

Protocol (v1), identical for every policy:

* Reference: the accepted, world-frame input points of the evaluated frames,
  restricted to the final map window, voxel-averaged at ``voxel_m`` so dense
  near-field returns do not dominate the means.
* Reconstruction: each active leaf becomes points at the centres of the
  voxels it claims at its own resolution ``s``. The ground layer contributes
  one voxel at its mean height; obstacle and overhead layers contribute the
  voxels spanning ``[min_z, max_z]``. This is how occupancy/voxel maps are
  scored, and it is what makes coarse cells pay for the detail they drop.

Distances are exact Euclidean nearest neighbours (``scipy.spatial.cKDTree``),
so the result is deterministic for identical inputs.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

PROTOCOL = "veyra-reconstruction-v1"
DEFAULT_VOXEL_M = 0.05
DEFAULT_THRESHOLDS_M: tuple[float, ...] = (0.05, 0.10, 0.20)
# Range bands measured from the final vehicle position, matching the
# DistanceLOD hierarchy so the near field can be read separately.
RANGE_BANDS_M: tuple[tuple[float, float], ...] = (
    (0.0, 10.0),
    (10.0, 30.0),
    (30.0, 60.0),
    (60.0, 100.0),
)


def voxel_downsample(points: np.ndarray, voxel_m: float) -> np.ndarray:
    """Centroid of the points in each occupied ``voxel_m`` cube."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(points) == 0:
        return points
    keys = np.floor(points / voxel_m).astype(np.int64)
    _, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.reshape(-1)
    sums = np.zeros((len(counts), 3))
    np.add.at(sums, inverse, points)
    return sums / counts[:, None]


def reference_cloud(
    frames: Iterable[Any],
    *,
    center_xy: Sequence[float],
    radius_m: float,
    voxel_m: float = DEFAULT_VOXEL_M,
) -> np.ndarray:
    """World-frame input points inside the final window, voxel-averaged."""
    chunks = [np.asarray(frame.points, dtype=np.float64)[:, :3] for frame in frames]
    points = np.concatenate(chunks) if chunks else np.empty((0, 3))
    offset = points[:, :2] - np.asarray(center_xy, dtype=np.float64)
    inside = np.einsum("ij,ij->i", offset, offset) <= radius_m * radius_m
    return voxel_downsample(points[inside], voxel_m)


def _column(xy: tuple[float, float], low: float, high: float, size: float) -> list[tuple]:
    if not (math.isfinite(low) and math.isfinite(high)) or high < low:
        return []
    slabs = max(1, math.ceil((high - low) / size - 1e-9))
    step = (high - low) / slabs
    return [(xy[0], xy[1], low + (index + 0.5) * step if step else low) for index in range(slabs)]


def reconstruct_from_leaves(leaves: Iterable[dict[str, Any]]) -> np.ndarray:
    """Voxel centres claimed by each active leaf's populated layers."""
    rows: list[tuple[float, float, float]] = []
    for leaf in leaves:
        if int(leaf.get("count", 0)) <= 0:
            continue
        size = 0.05 * 2 ** int(leaf["level"])
        xy = ((int(leaf["ix"]) + 0.5) * size, (int(leaf["iy"]) + 0.5) * size)
        if int(leaf.get("ground_count", 0)) > 0:
            rows.append((xy[0], xy[1], float(leaf["ground_mean_z"])))
        for layer in ("obstacle", "overhead"):
            if int(leaf.get(f"{layer}_count", 0)) > 0:
                if f"{layer}_max_z" not in leaf:
                    raise ValueError(
                        f"leaf details lack {layer}_max_z; rebuild veyra_benchmark"
                    )
                rows.extend(
                    _column(
                        xy,
                        float(leaf[f"{layer}_min_z"]),
                        float(leaf[f"{layer}_max_z"]),
                        size,
                    )
                )
    return np.asarray(rows, dtype=np.float64).reshape(-1, 3)


def _summary(distances: np.ndarray) -> dict[str, float | None]:
    if len(distances) == 0:
        return {"mean_m": None, "median_m": None, "p90_m": None}
    return {
        "mean_m": float(np.mean(distances)),
        "median_m": float(np.median(distances)),
        "p90_m": float(np.percentile(distances, 90)),
    }


def _thresholded(
    accuracy: np.ndarray, completion: np.ndarray, thresholds: Sequence[float]
) -> list[dict[str, float | None]]:
    rows = []
    for tau in thresholds:
        precision = float(np.mean(accuracy < tau)) if len(accuracy) else None
        recall = float(np.mean(completion < tau)) if len(completion) else None
        fscore = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall > 0
            else (0.0 if precision is not None and recall is not None else None)
        )
        rows.append(
            {"threshold_m": tau, "precision": precision, "recall": recall, "fscore": fscore}
        )
    return rows


def reconstruction_report(
    reconstruction: np.ndarray,
    reference: np.ndarray,
    *,
    center_xy: Sequence[float] = (0.0, 0.0),
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS_M,
    voxel_m: float = DEFAULT_VOXEL_M,
) -> dict[str, Any]:
    """Accuracy, completion, Chamfer-L1 and F-scores, overall and by range."""
    reconstruction = np.asarray(reconstruction, dtype=np.float64).reshape(-1, 3)
    reference = np.asarray(reference, dtype=np.float64).reshape(-1, 3)
    base = {
        "protocol": PROTOCOL,
        "voxel_m": voxel_m,
        "reference_points": len(reference),
        "reconstruction_points": len(reconstruction),
    }
    if len(reference) == 0 or len(reconstruction) == 0:
        return {
            **base,
            "status": "unavailable",
            "reason": "empty reference or reconstruction",
        }
    accuracy = cKDTree(reference).query(reconstruction)[0]
    completion = cKDTree(reconstruction).query(reference)[0]
    acc, comp = _summary(accuracy), _summary(completion)
    center = np.asarray(center_xy, dtype=np.float64)
    recon_range = np.hypot(*(reconstruction[:, :2] - center).T)
    ref_range = np.hypot(*(reference[:, :2] - center).T)
    by_range = []
    for low, high in RANGE_BANDS_M:
        in_recon = (recon_range >= low) & (recon_range < high)
        in_ref = (ref_range >= low) & (ref_range < high)
        band_acc, band_comp = _summary(accuracy[in_recon]), _summary(completion[in_ref])
        by_range.append(
            {
                "min_m": low,
                "max_m": high,
                "reference_points": int(in_ref.sum()),
                "reconstruction_points": int(in_recon.sum()),
                "accuracy_mean_m": band_acc["mean_m"],
                "completion_mean_m": band_comp["mean_m"],
                "chamfer_l1_m": (
                    (band_acc["mean_m"] + band_comp["mean_m"]) / 2
                    if band_acc["mean_m"] is not None and band_comp["mean_m"] is not None
                    else None
                ),
            }
        )
    return {
        **base,
        "status": "available",
        "accuracy": acc,
        "completion": comp,
        "chamfer_l1_m": (acc["mean_m"] + comp["mean_m"]) / 2,
        "thresholds": _thresholded(accuracy, completion, thresholds),
        "by_range": by_range,
        "scope": (
            "reference = accepted input points inside the final window, "
            f"{voxel_m * 100:g} cm voxel centroids; reconstruction = voxel centres "
            "claimed by active leaves at their own resolution"
        ),
    }
