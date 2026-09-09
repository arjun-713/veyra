"""Typed, dataset-independent data exchanged by perception and mapping."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _as_array(value: np.ndarray, *, dtype: np.dtype | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if not np.all(np.isfinite(array)) and np.issubdtype(array.dtype, np.floating):
        raise ValueError("observation arrays must contain finite values")
    return array


@dataclass(frozen=True)
class PoseSE3:
    """A rigid transform from the LiDAR frame into the configured world frame."""

    matrix: np.ndarray
    timestamp: float | None = None

    def __post_init__(self) -> None:
        matrix = _as_array(self.matrix, dtype=np.float64)
        if matrix.shape != (4, 4):
            raise ValueError("PoseSE3.matrix must have shape (4, 4)")
        if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0]):
            raise ValueError("PoseSE3.matrix must be homogeneous")
        object.__setattr__(self, "matrix", matrix)

    @classmethod
    def identity(cls, timestamp: float | None = None) -> PoseSE3:
        return cls(np.eye(4, dtype=np.float64), timestamp=timestamp)


@dataclass(frozen=True)
class LidarFrame:
    """Raw, ordered LiDAR points plus their dataset pose."""

    dataset: str
    sequence: str
    frame_id: str
    points: np.ndarray
    pose: PoseSE3
    timestamp: float | None = None

    def __post_init__(self) -> None:
        points = _as_array(self.points, dtype=np.float32)
        if points.ndim != 2 or points.shape[1] != 4:
            raise ValueError(
                "LidarFrame.points must have shape (N, 4): XYZ plus intensity"
            )
        object.__setattr__(self, "points", points)


@dataclass(frozen=True)
class SemanticFrame:
    """Per-point semantic result from ground truth or a model provider."""

    semantic_class: np.ndarray
    semantic_confidence: np.ndarray
    mode: str = "ground_truth"

    def __post_init__(self) -> None:
        classes = _as_array(self.semantic_class, dtype=np.int32).reshape(-1)
        confidence = _as_array(self.semantic_confidence, dtype=np.float32).reshape(-1)
        if classes.shape != confidence.shape:
            raise ValueError("semantic class and confidence arrays must be aligned")
        if np.any((confidence < 0.0) | (confidence > 1.0)):
            raise ValueError("semantic confidence must be in [0, 1]")
        if self.mode not in {"ground_truth", "model"}:
            raise ValueError("semantic mode must be 'ground_truth' or 'model'")
        object.__setattr__(self, "semantic_class", classes)
        object.__setattr__(self, "semantic_confidence", confidence)


@dataclass(frozen=True)
class ObservationFrame:
    """The stable perception-to-mapping boundary.

    Per-point fields all have length N, where ``points`` has shape (N, 4).
    ``velocity_xy`` has shape (N, 2). Fields not computed by the current
    perception stage are represented explicitly with unknown/default values.
    """

    timestamp: float | None
    pose: PoseSE3
    points: np.ndarray
    semantic_class: np.ndarray
    semantic_confidence: np.ndarray
    ground: np.ndarray
    drivable: np.ndarray
    slope: np.ndarray
    roughness: np.ndarray
    height_complexity: np.ndarray
    motion_probability: np.ndarray
    velocity_xy: np.ndarray
    dataset: str = ""
    sequence: str = ""
    frame_id: str = ""

    def __post_init__(self) -> None:
        points = _as_array(self.points, dtype=np.float32)
        if points.ndim != 2 or points.shape[1] != 4:
            raise ValueError("ObservationFrame.points must have shape (N, 4)")
        count = points.shape[0]
        one_dimensional = (
            "semantic_class",
            "semantic_confidence",
            "ground",
            "drivable",
            "slope",
            "roughness",
            "height_complexity",
            "motion_probability",
        )
        arrays = {name: np.asarray(getattr(self, name)) for name in one_dimensional}
        arrays["semantic_class"] = arrays["semantic_class"].astype(np.int32, copy=False)
        arrays["semantic_confidence"] = arrays["semantic_confidence"].astype(
            np.float32, copy=False
        )
        arrays["ground"] = arrays["ground"].astype(bool, copy=False)
        arrays["drivable"] = arrays["drivable"].astype(str, copy=False)
        for name in (
            "slope",
            "roughness",
            "height_complexity",
            "motion_probability",
        ):
            arrays[name] = arrays[name].astype(np.float32, copy=False)
        if any(array.ndim != 1 or array.shape[0] != count for array in arrays.values()):
            raise ValueError("all ObservationFrame per-point fields must have length N")
        velocity = _as_array(self.velocity_xy, dtype=np.float32)
        if velocity.shape != (count, 2):
            raise ValueError("ObservationFrame.velocity_xy must have shape (N, 2)")
        if np.any(
            (arrays["semantic_confidence"] < 0.0)
            | (arrays["semantic_confidence"] > 1.0)
        ):
            raise ValueError("semantic confidence must be in [0, 1]")
        if np.any(
            (arrays["motion_probability"] < 0.0) | (arrays["motion_probability"] > 1.0)
        ):
            raise ValueError("motion probability must be in [0, 1]")
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "velocity_xy", velocity)
        for name, array in arrays.items():
            object.__setattr__(self, name, array)


__all__ = ["LidarFrame", "ObservationFrame", "PoseSE3", "SemanticFrame"]
