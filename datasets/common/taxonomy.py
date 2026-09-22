"""Versioned mappings into Veyra's SemanticKITTI-learning target taxonomy."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Integral

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

# RELLIS raw labels are converted by meaning into Veyra's SemanticKITTI-
# learning space.  This is deliberately not the upstream RELLIS learning_map:
# that map's class 1 is RELLIS grass, while Veyra class 1 is car.  Raw IDs are
# retained by the adapter separately from this semantic projection.
RELLIS_LABELS: dict[int, VeyraClass] = {
    0: 0,
    1: 17,  # dirt -> terrain
    3: 15,  # grass -> vegetation
    4: 15,  # tree -> vegetation
    5: 18,  # pole -> pole
    6: 0,  # water has no honest SemanticKITTI equivalent
    7: 0,  # sky is outside the point semantic taxonomy
    8: 5,  # vehicle -> other-vehicle
    9: 0,  # generic object is underspecified
    10: 9,  # asphalt -> road
    12: 13,  # building -> building
    15: 16,  # log -> trunk
    17: 6,  # person -> person
    18: 14,  # fence -> fence
    19: 15,  # bush -> vegetation
    23: 0,  # concrete is a material, not a SemanticKITTI class
    27: 0,  # barrier has no honest SemanticKITTI equivalent
    31: 0,  # puddle has no honest SemanticKITTI equivalent
    33: 17,  # mud -> terrain
    34: 0,  # rubble has no honest SemanticKITTI equivalent
}

# PandaSet semantic segmentation ``classes.json`` (42 classes, identical in every
# labelled sequence). Mapped by meaning; atmospheric returns (smoke, exhaust,
# spray, reflection) and classes without an honest target stay unknown.
PANDASET_LABELS: dict[int, VeyraClass] = {
    5: 15,  # vegetation -> vegetation
    6: 12,  # ground (unpaved, non-road) -> other-ground
    7: 9,  # road -> road
    8: 9,  # lane line marking -> road
    9: 9,  # stop line marking -> road
    10: 9,  # other road marking -> road
    11: 11,  # sidewalk -> sidewalk
    12: 12,  # driveway -> other-ground
    13: 1,  # car -> car
    14: 1,  # pickup truck -> car (SemanticKITTI convention)
    15: 4,  # medium-sized truck -> truck
    16: 4,  # semi-truck -> truck
    17: 5,  # towed object -> other-vehicle
    18: 3,  # motorcycle -> motorcycle
    19: 5,  # construction vehicle -> other-vehicle
    20: 5,  # uncommon vehicle -> other-vehicle
    21: 5,  # pedicab -> other-vehicle
    22: 5,  # emergency vehicle -> other-vehicle
    23: 5,  # bus -> other-vehicle (SemanticKITTI learning_map)
    26: 2,  # bicycle -> bicycle
    27: 5,  # train -> other-vehicle (SemanticKITTI on-rails)
    28: 5,  # trolley -> other-vehicle
    29: 5,  # tram / subway -> other-vehicle
    30: 6,  # pedestrian -> person
    31: 6,  # pedestrian with object -> person
    35: 14,  # road barriers -> fence (guard rails in SemanticKITTI)
    36: 19,  # signs -> traffic-sign
    38: 19,  # construction signs -> traffic-sign
    39: 14,  # temporary construction barriers -> fence
    41: 13,  # building -> building
}

DATASET_TAXONOMY_VERSIONS = {
    "semantickitti": "SemanticKITTI-v1.1-learning_map",
    "semanticposs": "SemanticPOSS-v1.0-LABEL_DICT",
    "rellis3d": "RELLIS-3D-v1.1-learning_map",
    "pandaset": "PandaSet-semseg-classes-v1",
}


def map_dataset_labels(
    labels: np.ndarray, mapping: Mapping[int, int] | None = None
) -> np.ndarray:
    """Map raw dataset IDs without allocating a range-sized lookup table.

    Labels must be integer arrays (or finite, integral floating-point values);
    strings, fractional values, NaNs, and infinities are rejected rather than
    silently coerced into a potentially wrong class.
    """

    raw = np.asarray(labels)
    if raw.dtype.kind == "b":
        raise TypeError("labels must be integer-valued, not boolean")
    if raw.dtype.kind in "iu":
        if raw.dtype.kind == "u" and raw.size and np.max(raw) > np.iinfo(np.int64).max:
            raise ValueError("unsigned labels exceed supported integer range")
        integer_labels = raw.astype(np.int64, copy=False).reshape(-1)
    elif raw.dtype.kind == "f":
        if not np.all(np.isfinite(raw)) or not np.all(raw == np.floor(raw)):
            raise ValueError("labels must contain finite integer values")
        if raw.size and (
            np.min(raw) < np.iinfo(np.int64).min or np.max(raw) > np.iinfo(np.int64).max
        ):
            raise ValueError("labels exceed supported integer range")
        integer_labels = raw.astype(np.int64).reshape(-1)
    else:
        raise TypeError("labels must be a numeric integer array")

    table = mapping if mapping is not None else {}
    entries = []
    for key, value in table.items():
        if (
            isinstance(key, bool)
            or not isinstance(key, Integral)
            or isinstance(value, bool)
            or not isinstance(value, Integral)
            or int(key) < np.iinfo(np.int64).min
            or int(key) > np.iinfo(np.int64).max
            or int(value) < 0
        ):
            raise TypeError("mapping keys and values must be non-negative integers")
        entries.append((int(key), int(value)))

    result = np.full(integer_labels.shape, UNKNOWN_CLASS, dtype=np.int32)
    if not entries:
        return result
    entries.sort(key=lambda item: item[0])
    keys = np.asarray([item[0] for item in entries], dtype=np.int64)
    values = np.asarray([item[1] for item in entries], dtype=np.int32)
    positions = np.searchsorted(keys, integer_labels, side="left")
    valid = positions < len(keys)
    valid &= keys[np.minimum(positions, len(keys) - 1)] == integer_labels
    result[valid] = values[positions[valid]]
    return result


__all__ = [
    "DATASET_TAXONOMY_VERSIONS",
    "PANDASET_LABELS",
    "RELLIS_LABELS",
    "SEMANTICKITTI_LABELS",
    "SEMANTIC_POSS_LABELS",
    "TAXONOMY_VERSION",
    "UNKNOWN_CLASS",
    "map_dataset_labels",
]
