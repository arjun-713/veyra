"""Dataset-independent frame, adapter, and observation contracts."""

from .adapter import DatasetAdapter, DatasetFrameRef
from .observation import (
    LidarFrame,
    ObservationFrame,
    PoseSE3,
    SemanticFrame,
)
from .taxonomy import UNKNOWN_CLASS, map_dataset_labels

__all__ = [
    "UNKNOWN_CLASS",
    "DatasetAdapter",
    "DatasetFrameRef",
    "LidarFrame",
    "ObservationFrame",
    "PoseSE3",
    "SemanticFrame",
    "map_dataset_labels",
]
