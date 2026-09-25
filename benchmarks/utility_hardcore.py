"""Policy-blind challenge selection and task-region UtilityLOD evaluation.

The reference is observed Uniform5 representation, not surveyed terrain truth.
Challenge annotations are frozen from raw XYZ and dataset labels before a
policy executes. A promotion is a finer *final owner* on an observed 5 cm bin
than DistanceLOD; it is not a count of internal policy decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

from benchmarks.run_benchmark import elevation_surface_metrics


def manifest_digest(manifest: dict[str, Any]) -> str:
    """Hash semantic contents, excluding the stored digest itself."""
    payload = {key: value for key, value in manifest.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def select_semantic_candidate(
    points: np.ndarray,
    classes: np.ndarray,
    instances: np.ndarray,
    *,
    class_id: int,
    lower_m: float,
    upper_m: float,
    min_points: int = 20,
) -> dict[str, Any] | None:
    """Select an instance from GT and sensor-frame radial range only.

    The highest-support instance wins. Ties use the lower numeric instance ID.
    Uninstanced labels are treated as a class patch, explicitly marked as such.
    """
    xyz = np.asarray(points)
    labels = np.asarray(classes)
    ids = np.asarray(instances)
    if (
        xyz.ndim != 2
        or xyz.shape[1] < 3
        or labels.shape != (len(xyz),)
        or ids.shape != (len(xyz),)
    ):
        raise ValueError("points, classes and instances must be aligned")
    if min_points <= 0 or not 0 <= lower_m < upper_m:
        raise ValueError("invalid semantic selection threshold")
    radial = np.hypot(xyz[:, 0], xyz[:, 1])
    eligible = (labels == class_id) & (radial >= lower_m) & (radial < upper_m)
    if not np.any(eligible):
        return None
    nonzero = np.unique(ids[eligible & (ids > 0)])
    if len(nonzero):
        ranked = sorted(
            (
                (int(np.count_nonzero(eligible & (ids == item))), int(item))
                for item in nonzero
            ),
            key=lambda item: (-item[0], item[1]),
        )
        count, selected_id = ranked[0]
        chosen = eligible & (ids == selected_id)
        region_kind = "dataset_instance"
    else:
        # A semantic class may occupy the entire scan. Without instance IDs,
        # a fixed spatial patch is the honest unit; do not call it an object.
        cell = np.floor(xyz[eligible, :2] / 2.0).astype(np.int64)
        unique, counts = np.unique(cell, axis=0, return_counts=True)
        rank = sorted(
            range(len(unique)),
            key=lambda index: (
                -int(counts[index]),
                int(unique[index, 0]),
                int(unique[index, 1]),
            ),
        )[0]
        count, selected_id = int(counts[rank]), 0
        chosen = eligible & np.all(
            np.floor(xyz[:, :2] / 2.0).astype(np.int64) == unique[rank], axis=1
        )
        region_kind = "derived_2m_class_patch"
    if count < min_points:
        return None
    subset = xyz[chosen]
    pad = 0.5
    bbox = [
        float(subset[:, 0].min() - pad),
        float(subset[:, 1].min() - pad),
        float(subset[:, 0].max() + pad),
        float(subset[:, 1].max() + pad),
    ]
    return {
        "class_id": int(class_id),
        "instance_id": selected_id if selected_id else None,
        "region_kind": region_kind,
        "points": count,
        "range_band_m": [lower_m, upper_m],
        "bbox_xy_m": bbox,
    }


def contiguous_window(
    frame_ids: list[int], selected_id: int, count: int
) -> tuple[int, int] | None:
    """Return indices of a fixed-length original-ID-contiguous window."""
    if count <= 0 or len(set(frame_ids)) != len(frame_ids):
        raise ValueError("count must be positive and original frame IDs unique")
    try:
        selected = frame_ids.index(selected_id)
    except ValueError:
        return None
    start = selected
    while start > 0 and frame_ids[start] - frame_ids[start - 1] == 1:
        start -= 1
    end = selected + 1
    while end < len(frame_ids) and frame_ids[end] - frame_ids[end - 1] == 1:
        end += 1
    if end - start < count:
        return None
    window_start = min(max(selected - count // 2, start), end - count)
    return window_start, window_start + count


def select_geometry_candidates(
    points: np.ndarray,
    *,
    min_points: int = 12,
    lower_m: float = 30.0,
    upper_m: float = 60.0,
) -> dict[str, dict[str, Any] | None]:
    """Select first fixed-voxel high-IQR terrain and nearby low-IQR control.

    This is a height-variation screen, not a verified slope/terrain label.
    The full XYZ returns are used; vertical objects may enter the candidate.
    """
    xyz = np.asarray(points)
    if xyz.ndim != 2 or xyz.shape[1] < 3 or min_points <= 0:
        raise ValueError("geometry selection requires Nx3+ points and positive support")
    radial = np.hypot(xyz[:, 0], xyz[:, 1])
    selected = xyz[(radial >= lower_m) & (radial < upper_m)]
    if not len(selected):
        return {"geometry_hazard": None, "flat_control": None}
    cell = np.floor(selected[:, :2]).astype(np.int64)
    order = np.lexsort((cell[:, 1], cell[:, 0]))
    ordered_cells = cell[order]
    boundaries = np.r_[
        0,
        np.flatnonzero(np.any(np.diff(ordered_cells, axis=0), axis=1)) + 1,
        len(order),
    ]
    hazards: list[dict[str, Any]] = []
    flats: list[dict[str, Any]] = []
    for left, right in zip(boundaries[:-1], boundaries[1:], strict=True):
        if right - left < min_points:
            continue
        subset = selected[order[left:right]]
        q25, q75 = np.quantile(subset[:, 2], [0.25, 0.75])
        spread = float(q75 - q25)
        ix, iy = (int(value) for value in ordered_cells[left])
        candidate = {
            "bbox_xy_m": [ix, iy, ix + 1, iy + 1],
            "points": int(right - left),
            "height_iqr_m": spread,
            "mean_range_m": float(np.mean(np.hypot(subset[:, 0], subset[:, 1]))),
            "range_band_m": [lower_m, upper_m],
            "selection_cell_size_m": 1.0,
        }
        if spread >= 0.25:
            hazards.append(candidate)
        elif spread <= 0.04:
            flats.append(candidate)
    hazard = hazards[0] if hazards else None
    matched_flat = None
    if hazard:
        eligible = [
            item
            for item in flats
            if abs(item["mean_range_m"] - hazard["mean_range_m"]) <= 5.0
        ]
        matched_flat = (
            min(
                eligible,
                key=lambda item: (
                    abs(item["mean_range_m"] - hazard["mean_range_m"]),
                    item["bbox_xy_m"],
                ),
            )
            if eligible
            else None
        )
    return {"geometry_hazard": hazard, "flat_control": matched_flat}


def _subset_reference(
    reference: dict[str, Any], keys: set[tuple[int, int]]
) -> dict[str, Any]:
    return {
        "mean_z_by_cell": {
            key: value
            for key, value in reference["mean_z_by_cell"].items()
            if key in keys
        },
        "mean_range_by_cell": {
            key: value
            for key, value in reference.get("mean_range_by_cell", {}).items()
            if key in keys
        },
        "coordinate_frame": reference.get("coordinate_frame", "odom"),
    }


def _owners(
    snapshot: dict[str, Any], keys: set[tuple[int, int]]
) -> dict[tuple[int, int], dict[str, Any] | None]:
    by_id = {}
    for leaf in snapshot.get("leaves", []):
        identifier = (int(leaf["level"]), int(leaf["ix"]), int(leaf["iy"]))
        if identifier in by_id:
            raise ValueError("duplicate leaf identifier in challenge snapshot")
        by_id[identifier] = leaf
    found = {}
    for ix, iy in keys:
        matches = [
            by_id[(level, ix >> level, iy >> level)]
            for level in range(4)
            if (level, ix >> level, iy >> level) in by_id
        ]
        if len(matches) > 1:
            raise ValueError("overlapping leaf ownership in challenge snapshot")
        found[(ix, iy)] = matches[0] if matches else None
    return found


def regional_comparison(
    reference: dict[str, Any],
    distance: dict[str, Any],
    utility: dict[str, Any],
    *,
    bbox_xy_m: list[float],
    critical_bins: set[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Compare final observed support inside and outside a frozen XY region."""
    if len(bbox_xy_m) != 4 or not all(math.isfinite(value) for value in bbox_xy_m):
        raise ValueError("challenge bbox must contain four finite coordinates")
    x0, y0, x1, y1 = bbox_xy_m
    if not x0 < x1 or not y0 < y1:
        raise ValueError("challenge bbox must have positive area")
    keys = set(reference["mean_z_by_cell"])
    critical = {
        key
        for key in keys
        if x0 <= (key[0] + 0.5) * 0.05 < x1 and y0 <= (key[1] + 0.5) * 0.05 < y1
    }
    if critical_bins is not None:
        critical &= critical_bins
    background = keys - critical
    d_owners, u_owners = _owners(distance, keys), _owners(utility, keys)
    promoted = {
        key
        for key in keys
        if d_owners[key] is not None
        and u_owners[key] is not None
        and int(u_owners[key]["level"]) < int(d_owners[key]["level"])
    }
    eligible = {
        key
        for key in critical
        if d_owners[key] is not None and int(d_owners[key]["level"]) > 0
    }
    wasted = {
        key
        for key in promoted - critical
        if abs(float(u_owners[key]["mean_z"]) - float(reference["mean_z_by_cell"][key]))
        >= abs(float(d_owners[key]["mean_z"]) - float(reference["mean_z_by_cell"][key]))
    }

    def region_metrics(region: set[tuple[int, int]]) -> dict[str, Any]:
        subset = _subset_reference(reference, region)
        return {
            "distance_lod": elevation_surface_metrics(distance, subset),
            "utility_lod": elevation_surface_metrics(utility, subset),
        }

    return {
        "critical": region_metrics(critical),
        "background": region_metrics(background),
        "critical_reference_bins": len(critical),
        "background_reference_bins": len(background),
        "promoted_bins": len(promoted),
        "promoted_critical_bins": len(promoted & critical),
        "promoted_background_bins": len(promoted & background),
        "promotion_precision": len(promoted & critical) / len(promoted)
        if promoted
        else None,
        "promotion_recall": len(promoted & eligible) / len(eligible)
        if eligible
        else None,
        "promotion_recall_denominator": len(eligible),
        "promoted_eligible_bins": len(promoted & eligible),
        "missed_critical_bins": len(eligible - promoted),
        "wasted_promotion_ratio": len(wasted) / len(promoted) if promoted else None,
        "wasted_definition": "promoted background observed bins with no reduction in absolute elevation error",
    }
