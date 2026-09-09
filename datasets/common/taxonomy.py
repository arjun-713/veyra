"""Deterministic mapping from dataset labels to Veyra semantic classes."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

UNKNOWN_CLASS = 0


def map_dataset_labels(
    labels: np.ndarray, mapping: Mapping[int, int] | None = None
) -> np.ndarray:
    """Map raw dataset IDs, retaining unknown IDs as Veyra class zero."""

    raw = np.asarray(labels).reshape(-1)
    table = mapping or {}
    return np.array(
        [table.get(int(label), UNKNOWN_CLASS) for label in raw], dtype=np.int32
    )


__all__ = ["UNKNOWN_CLASS", "map_dataset_labels"]
