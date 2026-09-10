"""Deterministic terrain features computed from world-frame point samples."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TerrainEvidence:
    """Per-point terrain evidence aligned with the input point array.

    ``slope`` is in radians, ``roughness`` is RMS plane residual in metres,
    ``height_complexity`` is the local standard deviation of height, and
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
        radius_squared = self.neighborhood_radius**2

        # A cell width equal to the query radius means a query can only touch
        # the 3x3 neighbouring buckets.  This bounds candidate discovery for
        # normal LiDAR densities without introducing a heavyweight dependency.
        bucket_size = self.neighborhood_radius
        buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        bucket_coords = np.floor(xyz[:, :2] / bucket_size).astype(np.int64)
        for index, bucket in enumerate(bucket_coords):
            buckets[(int(bucket[0]), int(bucket[1]))].append(index)

        # Fit once per query bucket, then broadcast to points in that bucket.
        # This keeps work proportional to occupied buckets and bounds the
        # amount of data used by a fit for pathological dense returns.
        max_fit_points = max(32, self.min_ground_neighbors * 16)
        for (bx, by), bucket_points in buckets.items():
            bucket_indices = np.asarray(bucket_points, dtype=np.intp)
            if not np.any(mask[bucket_indices]):
                continue
            candidates = [
                candidate
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                for candidate in buckets.get((int(bx + dx), int(by + dy)), ())
            ]
            candidates = [candidate for candidate in candidates if mask[candidate]]
            if not candidates:
                continue
            candidate_indices = np.asarray(candidates, dtype=np.intp)
            center = xyz[bucket_points, :2].mean(axis=0)
            offsets = xyz[candidate_indices, :2] - center
            local = np.einsum("ij,ij->i", offsets, offsets) <= radius_squared * 2.0
            neighbor_indices = candidate_indices[local]
            if neighbor_indices.size > max_fit_points:
                # Uniform caps are unsafe: a small height hazard can fall
                # between samples. Always retain both local height extrema,
                # then fill the remaining budget deterministically.
                hazard_indices = neighbor_indices[
                    [
                        np.argmin(xyz[neighbor_indices, 2]),
                        np.argmax(xyz[neighbor_indices, 2]),
                    ]
                ]
                sample_budget = max_fit_points - len(np.unique(hazard_indices))
                selected = np.linspace(
                    0,
                    neighbor_indices.size - 1,
                    max(0, sample_budget),
                    dtype=np.intp,
                )
                neighbor_indices = np.unique(
                    np.concatenate((hazard_indices, neighbor_indices[selected]))
                )
            neighbors = xyz[neighbor_indices, :3]
            if len(neighbors) < self.min_ground_neighbors:
                continue

            centered = neighbors - neighbors.sum(axis=0) / len(neighbors)
            xy = centered[:, :2]
            z = centered[:, 2]
            normal_matrix = xy.T @ xy
            rhs = xy.T @ z
            determinant = (
                normal_matrix[0, 0] * normal_matrix[1, 1]
                - normal_matrix[0, 1] * normal_matrix[1, 0]
            )
            if not np.isfinite(determinant) or np.isclose(determinant, 0.0):
                continue
            gradient = np.array(
                (
                    (normal_matrix[1, 1] * rhs[0] - normal_matrix[0, 1] * rhs[1])
                    / determinant,
                    (normal_matrix[0, 0] * rhs[1] - normal_matrix[1, 0] * rhs[0])
                    / determinant,
                )
            )
            predicted = xy @ gradient
            residuals = np.abs(z - predicted)
            slope_value = float(np.arctan(np.linalg.norm(gradient)))
            roughness_value = float(np.sqrt(np.sum(residuals**2) / len(residuals)))
            complexity_value = float(np.sqrt(np.sum(z**2) / len(z)))
            # A continuous slope has a large raw height range but no step;
            # use deviation from the locally fitted surface instead.
            step_value = float(np.max(residuals))

            support = min(1.0, len(neighbors) / (self.min_ground_neighbors * 2.0))
            confidence_value = float(np.mean(confidence[neighbor_indices]) * support)
            # Geometry is fitted from ground support, but it must not be
            # broadcast to obstacle/non-ground points sharing the XY bucket.
            indices = bucket_indices[mask[bucket_indices]]
            if indices.size == 0:
                continue
            slope[indices] = slope_value
            roughness[indices] = roughness_value
            complexity[indices] = complexity_value
            step[indices] = step_value
            output_confidence[indices] = confidence_value
            if confidence_value > 0.0:
                if (
                    slope_value <= self.max_slope
                    and roughness_value <= self.max_roughness
                    and step_value <= self.max_step
                ):
                    result[indices] = "drivable"
                else:
                    result[indices] = "non_drivable"

        return TerrainEvidence(
            slope=slope,
            roughness=roughness,
            height_complexity=complexity,
            step=step,
            drivable=result,
            confidence=output_confidence,
        )
