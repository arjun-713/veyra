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
    ``height_complexity`` is ``tanh`` of the local height standard deviation
    (bounded in [0, 1) and invariant to absolute elevation), and ``step`` is
    the largest local height discontinuity in metres.  A point is ``unknown``
    when there is not enough trusted ground support.
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
            return np.bincount(flat_cells, weights=values, minlength=flat_size).reshape(
                height, width
            )

        scaled = np.stack(
            (
                np.ones(count, dtype=np.float64),
                xyz[:, 0],
                xyz[:, 1],
                xyz[:, 2],
                xyz[:, 0] * xyz[:, 0],
                xyz[:, 0] * xyz[:, 1],
                xyz[:, 1] * xyz[:, 1],
                xyz[:, 0] * xyz[:, 2],
                xyz[:, 1] * xyz[:, 2],
                xyz[:, 2] * xyz[:, 2],
                confidence,
            )
        )
        scaled *= support_mask
        counts = aggregate(scaled[0])
        sums = [aggregate(scaled[axis + 1]) for axis in range(3)]
        second_moments = [aggregate(scaled[index]) for index in range(4, 10)]
        confidence_sum = aggregate(scaled[10])
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
        # Exact zero-padded box sums via one stacked integral image.  This is
        # O(K*H*W) for K aggregated fields instead of K scipy convolutions at
        # O(K*H*W*k^2), which dominated full LiDAR scans.
        stacked = np.stack((*sums, *second_moments, counts, confidence_sum), axis=0)
        extent = 2 * radius_cells + 1
        integral = np.zeros(
            (stacked.shape[0], height + extent, width + extent), dtype=np.float64
        )
        # Place the unpadded raster directly with a zero border of
        # radius_cells instead of materializing a padded copy first.
        integral[
            :,
            1 + radius_cells : 1 + radius_cells + height,
            1 + radius_cells : 1 + radius_cells + width,
        ] = stacked
        np.cumsum(integral, axis=1, out=integral)
        np.cumsum(integral, axis=2, out=integral)
        local = (
            integral[:, extent:, extent:]
            - integral[:, :-extent, extent:]
            - integral[:, extent:, :-extent]
            + integral[:, :-extent, :-extent]
        )
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
            # Height spread is the local height standard deviation through a
            # bounded tanh map.  It must use the centered variance (czz), not
            # the raw second moment (szz): the latter grows with absolute
            # elevation and would mark flat but elevated ground as complex.
            complexity_grid = np.tanh(np.sqrt(np.maximum(czz / local_count, 0.0)))
            confidence_grid = np.divide(
                local_confidence,
                local_count,
                where=local_count > 0,
                out=np.zeros_like(local_count),
            ) * np.minimum(1.0, local_count / (self.min_ground_neighbors * 2.0))

        # A discontinuity is represented by adjacent raster-cell height
        # changes, while the in-cell range retains isolated curb/return
        # hazards that averaging alone would hide.  Only supported cells
        # participate: empty cells hold a zero fill value, and comparing real
        # heights against that fill would fabricate metre-scale phantom steps
        # at the edge of ground support.
        cell_mean_z = np.divide(
            sums[2], counts, where=counts > 0, out=np.zeros_like(counts)
        )
        has_support = counts > 0
        neighbor_step = np.zeros_like(cell_mean_z)
        vertical_pairs = has_support[1:, :] & has_support[:-1, :]
        vertical = np.where(
            vertical_pairs,
            np.abs(cell_mean_z[1:, :] - cell_mean_z[:-1, :]),
            0.0,
        )
        np.maximum(neighbor_step[1:, :], vertical, out=neighbor_step[1:, :])
        np.maximum(neighbor_step[:-1, :], vertical, out=neighbor_step[:-1, :])
        horizontal_pairs = has_support[:, 1:] & has_support[:, :-1]
        horizontal = np.where(
            horizontal_pairs,
            np.abs(cell_mean_z[:, 1:] - cell_mean_z[:, :-1]),
            0.0,
        )
        np.maximum(neighbor_step[:, 1:], horizontal, out=neighbor_step[:, 1:])
        np.maximum(neighbor_step[:, :-1], horizontal, out=neighbor_step[:, :-1])
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
