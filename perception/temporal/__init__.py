"""Deterministic temporal motion evidence for perception frames."""

from .evaluator import (
    KITTI_MOVING_RAW_IDS,
    KITTI_STATIC_CONTROL_RAW_IDS,
    MotionEvaluationError,
    evaluate_motion,
    unknown_report,
)
from .tracker import MotionEvidence, TemporalTracker, TrackSnapshot

__all__ = [
    "KITTI_MOVING_RAW_IDS",
    "KITTI_STATIC_CONTROL_RAW_IDS",
    "MotionEvaluationError",
    "MotionEvidence",
    "TemporalTracker",
    "TrackSnapshot",
    "evaluate_motion",
    "unknown_report",
]
