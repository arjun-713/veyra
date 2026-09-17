"""Deterministic terrain features computed from world-frame point samples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.ndimage import convolve


@dataclass(frozen=True)
class TerrainEvidence:
    """Per-point terrain evidence aligned with the input point array.

    ``slope`` is in radians, ``roughness`` is RMS plane residual in metres,
    ``height_complexity`` is a bounded local height-complexity score, and
    ``step`` is the largest local height discontinuity in metres.  A point
    is ``unknown`` when there is not enough trusted ground support.
    """

    slope: np.ndarray
    roughness: np.ndarray
    height_complexity: np.ndarray
    step: np.ndarray
    drivable: np.ndarray
    confidence: np.ndarray


class TerrainAnalyzer:
    """Extract conservative, local terrain evidence without external state."""

    def __init__(
        self,
        *,
        neighborhood_radius: float = 1.5,
        min_ground_neighbors: int = 6,
        max_slope: float = 0.45,
        max_roughness: float = 0.08,
        max_step: float = 0.20,
    ) -> None:
        numeric_config = (
            neighborhood_radius,
            max_slope,
            max_roughness,
            max_step,
        )
        if not all(np.isfinite(value) for value in numeric_config):
            raise ValueError("terrain configuration must be finite")
        if (
            neighborhood_radius <= 0
            or isinstance(min_ground_neighbors, bool)
            or int(min_ground_neighbors) != min_ground_neighbors
            or min_ground_neighbors < 3
        ):
            raise ValueError("invalid neighborhood configuration")
        if min(max_slope, max_roughness, max_step) < 0:
            raise ValueError("terrain thresholds must be non-negative")
        self.neighborhood_radius = float(neighborhood_radius)
        self.min_ground_neighbors = int(min_ground_neighbors)
        self.max_slope = float(max_slope)
        self.max_roughness = float(max_roughness)
        self.max_step = float(max_step)

    def analyze(self, points: np.ndarray, ground: Any) -> TerrainEvidence:
        """Return aligned terrain features for XYZ or XYZ-intensity points.

        ``ground`` is intentionally duck-typed: it must expose ``mask`` and
        may expose ``confidence``.  Only points with a true mask contribute
        to neighborhoods.  No ground support is treated as unknown, never
        as drivable.
        """
        xyz = np.asarray(points, dtype=np.float64)
        if xyz.ndim != 2 or xyz.shape[1] < 3:
            raise ValueError("points must have shape (N, 3+) ")
        if not np.all(np.isfinite(xyz)):
            raise ValueError("points must contain finite coordinates")
        count = xyz.shape[0]
        mask = np.asarray(ground.mask, dtype=bool)
        confidence_values = (
            ground.confidence if hasattr(ground, "confidence") else np.ones(count)
        )
        confidence = np.asarray(confidence_values, dtype=np.float64)
        if mask.shape != (count,) or confidence.shape != (count,):
            raise ValueError("ground fields must align with points")
        if np.any(~np.isfinite(confidence)) or np.any(
            (confidence < 0) | (confidence > 1)
        ):
            raise ValueError("ground confidence must be finite and within [0, 1]")

        slope = np.full(count, np.nan, dtype=np.float32)
        roughness = np.full(count, np.nan, dtype=np.float32)
        complexity = np.full(count, np.nan, dtype=np.float32)
        step = np.full(count, np.nan, dtype=np.float32)
        result = np.full(count, "unknown", dtype="U12")
        output_confidence = np.zeros(count, dtype=np.float32)
        if count == 0:
            return TerrainEvidence(
                slope=slope,
                roughness=roughness,
                height_complexity=complexity,
                step=step,
                drivable=result,
                confidence=output_confidence,
            )

        # Aggregate into a compact world-aligned raster first.  All local
        # sufficient statistics are then reduced by compiled ndimage kernels;
        # this removes the per-bucket Python candidate lists and least-squares
        # loop that dominated full LiDAR scans.
        cell_size = self.neighborhood_radius / 2.0
        cell_coords = np.floor(xyz[:, :2] / cell_size).astype(np.int64)
        min_cell = cell_coords.min(axis=0)
        max_cell = cell_coords.max(axis=0)
        width = int(max_cell[0] - min_cell[0] + 1)
        height = int(max_cell[1] - min_cell[1] + 1)
        flat_cells = (cell_coords[:, 1] - min_cell[1]) * width + (
            cell_coords[:, 0] - min_cell[0]
        )
        cell_count = width * height
        if cell_count > 4_000_000:
            raise ValueError(
                "terrain point extent is too large for the bounded raster analyzer"
            )

        support_mask = mask.astype(np.float64)
        flat_size = cell_count

        def aggregate(values: np.ndarray) -> np.ndarray:
            return np.bincount(
                flat_cells, weights=values * support_mask, minlength=flat_size
            ).reshape(height, width)

        counts = aggregate(np.ones(count, dtype=np.float64))
        sums = [aggregate(xyz[:, axis]) for axis in range(3)]
        second_moments = [
            aggregate(xyz[:, 0] * xyz[:, 0]),
            aggregate(xyz[:, 0] * xyz[:, 1]),
            aggregate(xyz[:, 1] * xyz[:, 1]),
            aggregate(xyz[:, 0] * xyz[:, 2]),
            aggregate(xyz[:, 1] * xyz[:, 2]),
            aggregate(xyz[:, 2] * xyz[:, 2]),
        ]
        confidence_sum = aggregate(confidence)
        ground_z = xyz[:, 2].copy()
        ground_z[~mask] = np.inf
        ground_min = np.full(flat_size, np.inf, dtype=np.float64)
        np.minimum.at(ground_min, flat_cells, ground_z)
        ground_z[~mask] = -np.inf
        ground_max = np.full(flat_size, -np.inf, dtype=np.float64)
        np.maximum.at(ground_max, flat_cells, ground_z)
        ground_min = ground_min.reshape(height, width)
        ground_max = ground_max.reshape(height, width)

        radius_cells = int(np.ceil(self.neighborhood_radius / cell_size))
        kernel_width = 2 * radius_cells + 1
        kernel = np.ones((kernel_width, kernel_width), dtype=np.float64)
        local = [
            convolve(values, kernel, mode="constant")
            for values in (*sums, *second_moments, counts, confidence_sum)
        ]
        sx, sy, sz, sxx, sxy, syy, sxz, syz, szz, local_count, local_confidence = local
        enough = local_count >= self.min_ground_neighbors
        with np.errstate(divide="ignore", invalid="ignore"):
            mean_x = sx / local_count
            mean_y = sy / local_count
            mean_z = sz / local_count
            cxx = sxx - sx * mean_x
            cxy = sxy - sx * mean_y
            cyy = syy - sy * mean_y
            cxz = sxz - sx * mean_z
            cyz = syz - sy * mean_z
            czz = szz - sz * mean_z
            determinant = cxx * cyy - cxy * cxy
            valid = enough & np.isfinite(determinant) & (np.abs(determinant) > 1e-12)
            gradient_x = np.divide(
                cyy * cxz - cxy * cyz,
                determinant,
                where=valid,
                out=np.zeros_like(determinant),
            )
            gradient_y = np.divide(
                cxx * cyz - cxy * cxz,
                determinant,
                where=valid,
                out=np.zeros_like(determinant),
            )
            residual_sum = czz - gradient_x * cxz - gradient_y * cyz
            roughness_grid = np.sqrt(np.maximum(residual_sum / local_count, 0.0))
            slope_grid = np.arctan(np.hypot(gradient_x, gradient_y))
            complexity_grid = np.tanh(np.sqrt(np.maximum(szz / local_count, 0.0)))
            confidence_grid = np.divide(
                local_confidence,
                local_count,
                where=local_count > 0,
                out=np.zeros_like(local_count),
            ) * np.minimum(1.0, local_count / (self.min_ground_neighbors * 2.0))

        # A discontinuity is represented by adjacent raster-cell height
        # changes, while the in-cell range retains isolated curb/return
        # hazards that averaging alone would hide.
        cell_mean_z = np.divide(
            sums[2], counts, where=counts > 0, out=np.zeros_like(counts)
        )
        neighbor_step = np.zeros_like(cell_mean_z)
        for axis, direction in ((0, 1), (0, -1), (1, 1), (1, -1)):
            shifted = np.roll(cell_mean_z, direction, axis=axis)
            boundary = [slice(None), slice(None)]
            boundary[axis] = 0 if direction > 0 else -1
            shifted[tuple(boundary)] = cell_mean_z[tuple(boundary)]
            neighbor_step = np.maximum(neighbor_step, np.abs(cell_mean_z - shifted))
        cell_range = np.where(
            counts > 0,
            np.maximum(0.0, ground_max - ground_min),
            0.0,
        )
        step_grid = np.maximum(neighbor_step, cell_range)
        valid &= np.isfinite(slope_grid + roughness_grid + complexity_grid)

        point_x = cell_coords[:, 0] - min_cell[0]
        point_y = cell_coords[:, 1] - min_cell[1]
        point_cell = (point_y * width + point_x).astype(np.intp)
        valid_flat = valid.ravel()
        ground_points = mask & valid_flat[point_cell]
        if np.any(ground_points):
            slope[ground_points] = slope_grid.ravel()[point_cell[ground_points]]
            roughness[ground_points] = roughness_grid.ravel()[point_cell[ground_points]]
            complexity[ground_points] = complexity_grid.ravel()[
                point_cell[ground_points]
            ]
            step[ground_points] = step_grid.ravel()[point_cell[ground_points]]
            output_confidence[ground_points] = confidence_grid.ravel()[
                point_cell[ground_points]
            ]
            drivable = (
                (slope[ground_points] <= self.max_slope)
                & (roughness[ground_points] <= self.max_roughness)
                & (step[ground_points] <= self.max_step)
                & (output_confidence[ground_points] > 0.0)
            )
            ground_indices = np.flatnonzero(ground_points)
            confident_indices = ground_indices[output_confidence[ground_points] > 0.0]
            confident_drivable = drivable[output_confidence[ground_points] > 0.0]
            result[confident_indices[confident_drivable]] = "drivable"
            result[confident_indices[~confident_drivable]] = "non_drivable"

        return TerrainEvidence(
            slope=slope,
            roughness=roughness,
            height_complexity=complexity,
            step=step,
            drivable=result,
            confidence=output_confidence,
        )
