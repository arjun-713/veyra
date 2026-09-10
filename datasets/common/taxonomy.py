"""Versioned mappings into Veyra's SemanticKITTI-learning target taxonomy."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

UNKNOWN_CLASS = 0
VeyraClass = int
TAXONOMY_VERSION = "veyra-semantic-kitti-learning-v1"

# PRBonn/semantic-kitti-api config/semantic-kitti.yaml, SemanticKITTI v1.1.
SEMANTICKITTI_LABELS: dict[int, VeyraClass] = {
    0: 0,
    1: 0,
    10: 1,
    11: 2,
    13: 5,
    15: 3,
    16: 5,
    18: 4,
    20: 5,
    30: 6,
    31: 7,
    32: 8,
    40: 9,
    44: 10,
    48: 11,
    49: 12,
    50: 13,
    51: 14,
    52: 0,
    60: 9,
    70: 15,
    71: 16,
    72: 17,
    80: 18,
    81: 19,
    99: 0,
    252: 1,
    253: 7,
    254: 6,
    255: 8,
    256: 5,
    257: 5,
    258: 4,
    259: 5,
}

# Stable IDs consumed by mapping and visualization. Dataset IDs are kept
# explicit so a new dataset cannot silently turn known evidence into another class.
# SemanticPOSS v1.0 ``read_data.py`` LABEL_DICT. Classes with no honest target
# equivalent remain unknown instead of being guessed.
SEMANTIC_POSS_LABELS: dict[int, VeyraClass] = {
    0: 0,
    4: 6,
    5: 6,
    6: 7,
    7: 1,
    8: 16,
    9: 15,
    10: 19,
    11: 19,
    12: 19,
    13: 18,
    14: 0,
    15: 13,
    16: 0,
    17: 14,
    21: 2,
    22: 12,
}

# unmannedlab/RELLIS-3D ``utils/label_convert.py`` learning_map (v1.1 data).
RELLIS_LABELS: dict[int, VeyraClass] = {
    0: 0,
    1: 0,
    3: 1,
    4: 2,
    5: 3,
    6: 4,
    7: 5,
    8: 6,
    9: 7,
    10: 8,
    12: 9,
    15: 10,
    17: 11,
    18: 12,
    19: 13,
    23: 14,
    27: 15,
    29: 1,
    30: 1,
    31: 16,
    32: 4,
    33: 17,
    34: 18,
}

DATASET_TAXONOMY_VERSIONS = {
    "semantickitti": "SemanticKITTI-v1.1-learning_map",
    "semanticposs": "SemanticPOSS-v1.0-LABEL_DICT",
    "rellis3d": "RELLIS-3D-v1.1-learning_map",
}


def map_dataset_labels(
    labels: np.ndarray, mapping: Mapping[int, int] | None = None
) -> np.ndarray:
    """Map raw dataset IDs, retaining unmapped IDs as explicit unknown."""

    raw = np.asarray(labels).reshape(-1)
    table = mapping if mapping is not None else {}
    return np.array(
        [table.get(int(label), UNKNOWN_CLASS) for label in raw], dtype=np.int32
    )


__all__ = [
    "DATASET_TAXONOMY_VERSIONS",
    "RELLIS_LABELS",
    "SEMANTICKITTI_LABELS",
    "SEMANTIC_POSS_LABELS",
    "TAXONOMY_VERSION",
    "UNKNOWN_CLASS",
    "map_dataset_labels",
]
