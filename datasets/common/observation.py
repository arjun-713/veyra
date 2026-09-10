"""Typed, dataset-independent data exchanged by perception and mapping."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _as_array(value: np.ndarray, *, dtype: np.dtype | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if not np.all(np.isfinite(array)) and np.issubdtype(array.dtype, np.floating):
        raise ValueError("observation arrays must contain finite values")
    return array


def _freeze(array: np.ndarray) -> np.ndarray:
    array = np.array(array, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class FrameProvenance:
    """State exactly which dataset metadata was consumed for a frame.

    A missing pose, time, or calibration file is meaningful runtime state. It
    must not be mistaken for a measured identity transform or generated time.
    """

    coordinate_frame: str = "unspecified"
    timestamp_source: str = "unspecified"
    pose_source: str = "unspecified"
    calibration_source: str = "unspecified"

    def __post_init__(self) -> None:
        if self.coordinate_frame not in {
            "world",
            "lidar",
            "calibrated_lidar",
            "unspecified",
        }:
            raise ValueError("coordinate_frame is invalid")
        if self.timestamp_source not in {"dataset", "absent", "unspecified"}:
            raise ValueError("timestamp_source is invalid")
        for name in ("pose_source", "calibration_source"):
            if getattr(self, name) not in {"dataset", "identity_absent", "unspecified"}:
                raise ValueError(f"{name} is invalid")
        if self.coordinate_frame == "world" and self.pose_source != "dataset":
            raise ValueError("world coordinates require a dataset pose")


@dataclass(frozen=True)
class PoseSE3:
    """A rigid transform from the LiDAR frame into the configured world frame."""

    matrix: np.ndarray
    timestamp: float | None = None

    def __post_init__(self) -> None:
        if self.timestamp is not None and not np.isfinite(self.timestamp):
            raise ValueError("PoseSE3.timestamp must be finite")
        matrix = _as_array(self.matrix, dtype=np.float64)
        if matrix.shape != (4, 4):
            raise ValueError("PoseSE3.matrix must have shape (4, 4)")
        if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0]):
            raise ValueError("PoseSE3.matrix must be homogeneous")
        rotation = matrix[:3, :3]
        if not np.allclose(
            rotation.T @ rotation, np.eye(3), atol=2e-3
        ) or not np.isclose(np.linalg.det(rotation), 1.0, atol=2e-3):
            raise ValueError("PoseSE3.matrix rotation must be rigid")
        object.__setattr__(self, "matrix", _freeze(matrix))

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
        if self.timestamp is not None and not np.isfinite(self.timestamp):
            raise ValueError("LidarFrame.timestamp must be finite")
        points = _as_array(self.points, dtype=np.float32)
        if points.ndim != 2 or points.shape[1] != 4:
            raise ValueError(
                "LidarFrame.points must have shape (N, 4): XYZ plus intensity"
            )
        object.__setattr__(self, "points", _freeze(points))


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
        object.__setattr__(self, "semantic_class", _freeze(classes))
        object.__setattr__(self, "semantic_confidence", _freeze(confidence))


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
    terrain_confidence: np.ndarray | None = None
    step: np.ndarray | None = None
    motion_state: np.ndarray | None = None
    observation_quality: np.ndarray | None = None
    raw_semantic_class: np.ndarray | None = None
    provenance: FrameProvenance = FrameProvenance()

    def __post_init__(self) -> None:
        if self.timestamp is not None and not np.isfinite(self.timestamp):
            raise ValueError("ObservationFrame.timestamp must be finite")
        if not isinstance(self.provenance, FrameProvenance):
            raise TypeError("provenance must be a FrameProvenance")
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
        optional_arrays = {
            "raw_semantic_class": arrays["semantic_class"].copy()
            if self.raw_semantic_class is None
            else np.asarray(self.raw_semantic_class, dtype=np.int32),
            "terrain_confidence": np.zeros(count, dtype=np.float32)
            if self.terrain_confidence is None
            else np.asarray(self.terrain_confidence, dtype=np.float32),
            "step": np.full(count, np.nan, dtype=np.float32)
            if self.step is None
            else np.asarray(self.step, dtype=np.float32),
            "motion_state": np.full(count, "unknown", dtype="U15")
            if self.motion_state is None
            else np.asarray(self.motion_state, dtype=str),
            "observation_quality": arrays["semantic_confidence"].copy()
            if self.observation_quality is None
            else np.asarray(self.observation_quality, dtype=np.float32),
        }
        if any(array.ndim != 1 or array.shape[0] != count for array in arrays.values()):
            raise ValueError("all ObservationFrame per-point fields must have length N")
        if any(
            array.ndim != 1 or array.shape[0] != count
            for array in optional_arrays.values()
        ):
            raise ValueError("all optional ObservationFrame fields must have length N")
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
        if np.any(
            ~np.isin(arrays["drivable"], ["drivable", "non_drivable", "unknown"])
        ):
            raise ValueError("drivable must be drivable, non_drivable, or unknown")
        if np.any(
            ~np.isin(
                optional_arrays["motion_state"],
                ["static", "possibly_moving", "moving", "unknown"],
            )
        ):
            raise ValueError("motion_state contains an invalid value")
        for name in ("terrain_confidence", "observation_quality"):
            if np.any(~np.isfinite(optional_arrays[name])) or np.any(
                (optional_arrays[name] < 0.0) | (optional_arrays[name] > 1.0)
            ):
                raise ValueError(f"{name} must be finite and within [0, 1]")
        object.__setattr__(self, "points", _freeze(points))
        object.__setattr__(self, "velocity_xy", _freeze(velocity))
        for name, array in arrays.items():
            object.__setattr__(self, name, _freeze(array))
        for name, array in optional_arrays.items():
            object.__setattr__(self, name, _freeze(array))


__all__ = [
    "FrameProvenance",
    "LidarFrame",
    "ObservationFrame",
    "PoseSE3",
    "SemanticFrame",
]
