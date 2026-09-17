"""Native Pandora / SemanticPOSS semantic provider.

Geometry contract mirrors CENet ``poss.yml`` (MIT, huixiancheng/CENet):
spherical projection, ``40 x 1800`` range image, vertical FOV ``-16..+7``
degrees, Hesai-Pandora sensor. The classifier is a per-point MLP trained
natively on SemanticPOSS byte-intensity scans
(see ``scripts/train_pandora_semantic.py``); weights ship as ``.npz``
(checkpoint provenance in ``configs/semantic-pandora-native-model.json``)
and the forward pass is NumPy-only so inference needs no torch/sklearn.

Input is sensor-frame XYZI with byte intensity in ``[0, 255]``; output
follows the original point order as Veyra canonical class IDs with
``mode="model"``. Unknown (raw 0 and unmapped raw IDs) maps to Veyra 0 at
zero confidence via the shared ``SEMANTIC_POSS_LABELS`` table.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from datasets.common.taxonomy import SEMANTIC_POSS_LABELS
from perception.semantic.semantic_provider import SemanticResult

PANDORA_FOV_UP_DEGREES = 7.0
PANDORA_FOV_DOWN_DEGREES = -16.0
PANDORA_IMAGE_HEIGHT = 40
PANDORA_IMAGE_WIDTH = 1800
PANDORA_INTENSITY_SCALE = 255.0

#: Measured Hesai-Pandora beam elevations (degrees), one per range-image row.
#: Extracted from dataset .tag layouts: every tag row carries exactly one
#: pitch value, stable to 3 decimals across seq-00/01/02 spot frames (see
#: reports/closure/semantic-finetune/RESULT.md). Row 0 sits at +7.3 deg,
#: above the nominal +7 deg spec; expect the tail to be valid, not unknown.
PANDORA_BEAM_ELEVATIONS_DEG = (
    7.300, 6.299, 5.293, 4.285, 3.272, 2.259, 1.924, 1.578, 1.244, 0.909,
    0.563, 0.228, -0.111, -0.449, -0.788, -1.127, -1.464, -1.803, -2.141,
    -2.479, -2.817, -3.154, -3.491, -3.829, -4.162, -4.504, -4.838, -5.169,
    -5.510, -5.843, -6.844, -7.840, -8.830, -9.814, -10.791, -11.760,
    -12.717, -13.668, -14.609, -15.539,
)
#: Validity envelope around the beam fan: contains every observed return
#: (extremes -15.539 / +7.300 deg) with margin; anything outside is a sensor
#: fault and stays unknown.
PANDORA_PITCH_VALID_MIN_DEG = -16.5
PANDORA_PITCH_VALID_MAX_DEG = 7.5

FEATURE_NAMES = ("x", "y", "z", "intensity", "range", "pitch")

#: SemanticPOSS v1.0 ``LABEL_DICT`` raw IDs learnable by the native head.
#: Raw 0 is unlabeled; 18/19/20 are don't-care and every other unlisted raw
#: ID folds into 0 at both train and inference time (never guessed).
POSS_NATIVE_KNOWN_IDS = (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 21, 22)
POSS_UNKNOWN_ID = 0

#: Coarse reporting groups. Mutually exclusive; cover every native label.
GROUP_NAMES = (
    "drivable",
    "non-drivable",
    "static",
    "pole",
    "vehicle",
    "pedestrian",
    "vegetation",
    "unknown",
)
GROUP_OF_NATIVE: dict[int, str] = {
    22: "drivable",
    14: "non-drivable",
    16: "non-drivable",
    15: "static",
    17: "static",
    13: "pole",
    10: "pole",
    11: "pole",
    12: "pole",
    7: "vehicle",
    21: "vehicle",
    6: "vehicle",
    4: "pedestrian",
    5: "pedestrian",
    9: "vegetation",
    8: "vegetation",
    0: "unknown",
}
GROUP_INDEX = {name: index for index, name in enumerate(GROUP_NAMES)}


def fold_to_native(raw_labels: np.ndarray) -> np.ndarray:
    """Fold raw SemanticPOSS IDs into the native head label space.

    Known IDs pass through; raw 0 and every unmapped ID (don't-care
    18/19/20 and anything else) become unknown (0).
    """
    raw = np.asarray(raw_labels).reshape(-1)
    known = np.asarray(POSS_NATIVE_KNOWN_IDS, dtype=np.int64)
    native = np.zeros(raw.shape, dtype=np.int32)
    mask = np.isin(raw, known)
    native[mask] = raw[mask].astype(np.int32)
    return native


def native_to_group_ids(native_labels: np.ndarray) -> np.ndarray:
    """Map native head labels to coarse group indices (see ``GROUP_NAMES``)."""
    native = np.asarray(native_labels).reshape(-1)
    groups = np.full(native.shape, GROUP_INDEX["unknown"], dtype=np.int32)
    for raw_id, name in GROUP_OF_NATIVE.items():
        if raw_id == POSS_UNKNOWN_ID:
            continue
        groups[native == raw_id] = GROUP_INDEX[name]
    return groups


def project_pandora_scan(
    points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project sensor-frame XYZI onto the native Pandora range image.

    Returns ``(rows, cols, valid)`` with one entry per input point in input
    order. ``valid`` is true for finite, positive-range returns inside the
    ``-16..+7`` degree vertical FOV; out-of-FOV rows/cols are clipped to the
    image edge but flagged invalid so they can never inherit a prediction.
    """
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 4 or not np.isfinite(points).all():
        raise ValueError("Pandora projection requires finite XYZI of shape (N, 4)")
    depth = np.linalg.norm(points[:, :3], axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        pitch = np.arcsin(
            np.clip(
                np.divide(
                    points[:, 2], depth, out=np.zeros_like(depth), where=depth > 0
                ),
                -1.0,
                1.0,
            )
        )
    up = np.deg2rad(PANDORA_FOV_UP_DEGREES)
    down = np.deg2rad(PANDORA_FOV_DOWN_DEGREES)
    valid = (depth > 0) & (pitch >= down) & (pitch <= up)
    yaw = -np.arctan2(points[:, 1], points[:, 0])
    cols = np.clip(
        np.floor(0.5 * (yaw / np.pi + 1) * PANDORA_IMAGE_WIDTH),
        0,
        PANDORA_IMAGE_WIDTH - 1,
    ).astype(np.intp)
    rows = np.clip(
        np.floor((1 - (pitch - down) / (up - down)) * PANDORA_IMAGE_HEIGHT),
        0,
        PANDORA_IMAGE_HEIGHT - 1,
    ).astype(np.intp)
    return rows, cols, valid


def project_pandora_beams(
    points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project onto true Pandora beam rows (see ``PANDORA_BEAM_ELEVATIONS_DEG``).

    Same ``(rows, cols, valid)`` contract as :func:`project_pandora_scan`,
    but rows are nearest-beam assignments reproducing the dataset tag layout
    instead of linear-pitch interpolation. Columns are identical.
    """
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 4 or not np.isfinite(points).all():
        raise ValueError("Pandora projection requires finite XYZI of shape (N, 4)")
    depth = np.linalg.norm(points[:, :3], axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        pitch_deg = np.degrees(
            np.arcsin(
                np.clip(
                    np.divide(
                        points[:, 2], depth, out=np.zeros_like(depth), where=depth > 0
                    ),
                    -1.0,
                    1.0,
                )
            )
        )
    valid = (
        (depth > 0)
        & (pitch_deg >= PANDORA_PITCH_VALID_MIN_DEG)
        & (pitch_deg <= PANDORA_PITCH_VALID_MAX_DEG)
    )
    yaw = -np.arctan2(points[:, 1], points[:, 0])
    cols = np.clip(
        np.floor(0.5 * (yaw / np.pi + 1) * PANDORA_IMAGE_WIDTH),
        0,
        PANDORA_IMAGE_WIDTH - 1,
    ).astype(np.intp)
    beams = np.asarray(PANDORA_BEAM_ELEVATIONS_DEG, dtype=np.float64)
    rows = np.argmin(
        np.abs(pitch_deg[:, None].astype(np.float64) - beams[None, :]), axis=1
    ).astype(np.intp)
    return rows, cols, valid


def extract_features(points: np.ndarray) -> np.ndarray:
    """Per-point MLP features. Must match ``train_pandora_semantic.py``."""
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 4 or not np.isfinite(points).all():
        raise ValueError("Pandora features require finite XYZI of shape (N, 4)")
    intensity = np.clip(points[:, 3], 0.0, PANDORA_INTENSITY_SCALE) / PANDORA_INTENSITY_SCALE
    depth = np.linalg.norm(points[:, :3], axis=1).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        pitch = np.arcsin(
            np.clip(
                np.divide(
                    points[:, 2],
                    np.maximum(depth, 1e-9),
                    out=np.zeros_like(depth),
                    where=depth > 0,
                ),
                -1.0,
                1.0,
            )
        ).astype(np.float32)
    return np.column_stack(
        [points[:, 0], points[:, 1], points[:, 2], intensity, depth, pitch]
    ).astype(np.float32)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.maximum(exp.sum(axis=1, keepdims=True), 1e-12)


def mlp_predict_proba(
    features: np.ndarray,
    scaler_mean: np.ndarray,
    scaler_scale: np.ndarray,
    coefs: list[np.ndarray],
    intercepts: list[np.ndarray],
    temperature: float = 1.0,
) -> np.ndarray:
    """NumPy reimplementation of the sklearn MLP forward pass (relu/hidden)."""
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    x = (features - scaler_mean) / scaler_scale
    for index, (coef, intercept) in enumerate(zip(coefs, intercepts)):
        x = x @ coef + intercept
        if index < len(coefs) - 1:
            np.maximum(x, 0.0, out=x)
    return _softmax(x / temperature)


def model_contract() -> dict[str, object]:
    """Return the native Pandora provider contract for measurement artifacts."""
    return {
        "projection": {
            "image_shape": (PANDORA_IMAGE_HEIGHT, PANDORA_IMAGE_WIDTH),
            "sensor": "Hesai-Pandora",
            "fov_degrees": {
                "up": PANDORA_FOV_UP_DEGREES,
                "down": PANDORA_FOV_DOWN_DEGREES,
            },
            "features": FEATURE_NAMES,
            "intensity": "byte [0, 255] / 255",
        },
        "labels": "SemanticPOSS-v1.0-LABEL_DICT native IDs, "
        "unmapped raw IDs fold to unknown",
        "taxonomy": "native -> Veyra via SEMANTIC_POSS_LABELS",
        "postprocessing": "per-point argmax, no KNN",
    }


class PandoraNativeSemanticProvider:
    """Native SemanticPOSS MLP provider; NumPy-only inference from ``.npz``."""

    # Trained and labelled for SemanticPOSS/Pandora. The pipeline dataset
    # gate uses this to accept POSS frames and refuse anything else.
    supported_datasets = frozenset({"semanticposs"})

    def __init__(self, checkpoint_path: str | Path) -> None:
        path = Path(checkpoint_path)
        if not path.is_file():
            raise ValueError(f"Pandora native checkpoint does not exist: {path}")
        try:
            archive = np.load(str(path), allow_pickle=False)
            self._scaler_mean = np.asarray(archive["scaler_mean"], dtype=np.float64)
            self._scaler_scale = np.asarray(archive["scaler_scale"], dtype=np.float64)
            n_layers = int(archive["n_layers"])
            coefs = [np.asarray(archive[f"coef_{i}"], dtype=np.float64) for i in range(n_layers)]
            intercepts = [
                np.asarray(archive[f"intercept_{i}"], dtype=np.float64)
                for i in range(n_layers)
            ]
            self._classes = np.asarray(archive["classes"], dtype=np.int32)
            self._temperature = float(archive["temperature"])
        except (KeyError, ValueError, OSError) as error:
            raise ValueError(
                f"checkpoint is not a Pandora native MLP archive: {error}"
            ) from error
        if (
            self._scaler_mean.shape != (len(FEATURE_NAMES),)
            or self._scaler_scale.shape != (len(FEATURE_NAMES),)
            or not np.all(np.isfinite(self._scaler_scale))
            or np.any(self._scaler_scale == 0.0)
            or n_layers < 1
            or self._classes.ndim != 1
            or self._classes.size < 2
            or not np.isfinite(self._temperature)
            or self._temperature <= 0.0
        ):
            raise ValueError("Pandora native checkpoint has invalid parameters")
        expected_in: int | None = None
        for coef, intercept in zip(coefs, intercepts):
            if (
                coef.ndim != 2
                or intercept.ndim != 1
                or coef.shape[1] != intercept.shape[0]
                or (expected_in is not None and coef.shape[0] != expected_in)
                or not np.all(np.isfinite(coef))
                or not np.all(np.isfinite(intercept))
            ):
                raise ValueError("Pandora native checkpoint has invalid layer shapes")
            expected_in = coef.shape[1]
        if coefs[0].shape[0] != len(FEATURE_NAMES) or coefs[-1].shape[1] != self._classes.size:
            raise ValueError("Pandora native checkpoint dimensions mismatch contract")
        self._coefs = coefs
        self._intercepts = intercepts
        self.checkpoint_path = path

    def infer(
        self, points: np.ndarray, labels: np.ndarray | None = None
    ) -> SemanticResult:
        del labels
        points_array = np.asarray(points, dtype=np.float32)
        if (
            points_array.ndim != 2
            or points_array.shape[1] != 4
            or not np.all(np.isfinite(points_array))
        ):
            raise ValueError("Pandora native inference requires finite XYZI (N, 4)")
        count = points_array.shape[0]
        if count == 0:
            return SemanticResult(
                np.zeros(0, np.int32), np.zeros(0, np.float32), "model"
            )
        features = extract_features(points_array)
        proba = mlp_predict_proba(
            features,
            self._scaler_mean,
            self._scaler_scale,
            self._coefs,
            self._intercepts,
            self._temperature,
        )
        best = proba.argmax(axis=1)
        native = self._classes[best]
        mapped = np.array(
            [SEMANTIC_POSS_LABELS.get(int(raw), 0) for raw in native], dtype=np.int32
        )
        confidence = proba[np.arange(count), best].astype(np.float32)
        return SemanticResult(mapped, confidence, "model")

    def infer_native(
        self, points: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(native_ids, probabilities)`` per point in input order."""
        points_array = np.asarray(points, dtype=np.float32)
        if (
            points_array.ndim != 2
            or points_array.shape[1] != 4
            or not np.all(np.isfinite(points_array))
        ):
            raise ValueError("Pandora native inference requires finite XYZI (N, 4)")
        proba = mlp_predict_proba(
            extract_features(points_array),
            self._scaler_mean,
            self._scaler_scale,
            self._coefs,
            self._intercepts,
            self._temperature,
        )
        return self._classes[proba.argmax(axis=1)], proba


__all__ = [
    "FEATURE_NAMES",
    "GROUP_INDEX",
    "GROUP_NAMES",
    "GROUP_OF_NATIVE",
    "PANDORA_BEAM_ELEVATIONS_DEG",
    "PANDORA_FOV_DOWN_DEGREES",
    "PANDORA_FOV_UP_DEGREES",
    "PANDORA_IMAGE_HEIGHT",
    "PANDORA_IMAGE_WIDTH",
    "PANDORA_INTENSITY_SCALE",
    "PANDORA_PITCH_VALID_MAX_DEG",
    "PANDORA_PITCH_VALID_MIN_DEG",
    "POSS_NATIVE_KNOWN_IDS",
    "POSS_UNKNOWN_ID",
    "PandoraNativeSemanticProvider",
    "extract_features",
    "fold_to_native",
    "mlp_predict_proba",
    "model_contract",
    "native_to_group_ids",
    "project_pandora_beams",
    "project_pandora_scan",
]
