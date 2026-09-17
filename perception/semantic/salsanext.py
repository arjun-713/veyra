"""CPU SalsaNext inference using the published SemanticKITTI checkpoint.

Projection/normalization follow TiagoCortinhal/SalsaNext and Qualcomm's
v0.62.1 export (64x2048, five channels, 20 learning classes, no KNN).
The checkpoint outputs probabilities already. Never apply softmax twice.
Input is sensor-frame XYZI; output follows the original point order.
Out-of-FOV and zero-range returns are explicitly unknown at confidence zero.
Pixel collisions share the nearest return's prediction, as upstream's
non-KNN unprojection does; this is not an instance segmentation model.
"""

from pathlib import Path

import numpy as np

from perception.semantic.semantic_provider import SemanticResult

_MEANS = np.array([12.12, 10.88, 0.23, -1.04, 0.21], np.float32)[:, None, None]
_STDS = np.array([12.32, 11.47, 6.91, 0.86, 0.16], np.float32)[:, None, None]
_IMAGE_HEIGHT = 64
_IMAGE_WIDTH = 2048
_FOV_UP_DEGREES = 3.0
_FOV_DOWN_DEGREES = -25.0
_LEARNING_CLASSES = (
    "unlabeled",
    "car",
    "bicycle",
    "motorcycle",
    "truck",
    "other-vehicle",
    "person",
    "bicyclist",
    "motorcyclist",
    "road",
    "parking",
    "sidewalk",
    "other-ground",
    "building",
    "fence",
    "vegetation",
    "trunk",
    "terrain",
    "pole",
    "traffic-sign",
)


def model_contract() -> dict[str, object]:
    """Return the pinned export contract mirrored from upstream configuration."""
    return {
        "image_shape": (_IMAGE_HEIGHT, _IMAGE_WIDTH),
        "channels": ("range", "x", "y", "z", "remission"),
        "fov_degrees": {"up": _FOV_UP_DEGREES, "down": _FOV_DOWN_DEGREES},
        "normalization_means": tuple(float(value) for value in _MEANS[:, 0, 0]),
        "normalization_stds": tuple(float(value) for value in _STDS[:, 0, 0]),
        "learning_classes": _LEARNING_CLASSES,
        "postprocessing": "nearest_return_projection_without_knn",
    }


def project_scan(
    points: np.ndarray, *, intensity_scale: float = 1.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 4 or not np.isfinite(points).all():
        raise ValueError("SalsaNext requires finite sensor-frame XYZI of shape (N, 4)")
    if not np.isfinite(intensity_scale) or intensity_scale <= 0:
        raise ValueError("intensity_scale must be finite and positive")
    if np.any((points[:, 3] < 0) | (points[:, 3] > intensity_scale)):
        raise ValueError(
            "intensity outside configured sensor range; set intensity_scale explicitly"
        )
    points = points.copy()
    points[:, 3] /= intensity_scale
    depth = np.linalg.norm(points[:, :3], axis=1)
    pitch = np.arcsin(
        np.clip(
            np.divide(points[:, 2], depth, out=np.zeros_like(depth), where=depth > 0),
            -1,
            1,
        )
    )
    up, down = np.deg2rad(_FOV_UP_DEGREES), np.deg2rad(_FOV_DOWN_DEGREES)
    valid = (depth > 0) & (pitch >= down) & (pitch <= up)
    yaw = -np.arctan2(points[:, 1], points[:, 0])
    cols = np.clip(
        np.floor(0.5 * (yaw / np.pi + 1) * _IMAGE_WIDTH), 0, _IMAGE_WIDTH - 1
    ).astype(np.intp)
    rows = np.clip(
        np.floor((1 - (pitch - down) / (up - down)) * _IMAGE_HEIGHT),
        0,
        _IMAGE_HEIGHT - 1,
    ).astype(np.intp)
    image = np.zeros((5, _IMAGE_HEIGHT, _IMAGE_WIDTH), np.float32)
    # Stable ties use the first input return. Selecting unique pixels avoids
    # relying on NumPy's ordering of repeated fancy-index assignments.
    ordered = np.flatnonzero(valid)
    ordered = ordered[np.argsort(depth[ordered], kind="stable")]
    _, first = np.unique(rows[ordered] * 2048 + cols[ordered], return_index=True)
    selected = ordered[first]
    image[0, rows[selected], cols[selected]] = depth[selected]
    image[1:, rows[selected], cols[selected]] = points[selected].T
    occupied = np.zeros((_IMAGE_HEIGHT, _IMAGE_WIDTH), bool)
    occupied[rows[selected], cols[selected]] = True
    image = ((image - _MEANS) / _STDS) * occupied[None]
    return image[None], rows, cols, valid


def unproject_scores(
    scores: np.ndarray, rows: np.ndarray, cols: np.ndarray, valid: np.ndarray
) -> SemanticResult:
    scores = np.asarray(scores)
    if scores.shape != (1, len(_LEARNING_CLASSES), _IMAGE_HEIGHT, _IMAGE_WIDTH):
        raise ValueError(
            "SalsaNext output must be "
            f"(1, {len(_LEARNING_CLASSES)}, {_IMAGE_HEIGHT}, {_IMAGE_WIDTH})"
        )
    if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
        raise ValueError("SalsaNext output must contain finite probabilities in [0, 1]")
    # Only pixels assigned to actual returns need normalization validation.
    selected = scores[0, :, rows[valid], cols[valid]]
    if not np.allclose(selected.sum(axis=1), 1.0, atol=2e-3):
        raise ValueError("SalsaNext probabilities must sum to one")
    classes = np.zeros(len(rows), np.int32)
    confidence = np.zeros(len(rows), np.float32)
    if selected.size:
        # The checkpoint's learning IDs are Veyra's canonical taxonomy IDs.
        classes[valid] = selected.argmax(axis=1)
        confidence[valid] = selected.max(axis=1)
    return SemanticResult(classes, confidence, "model")


class SalsaNextSemanticProvider:
    """Load one explicit pretrained ONNX asset; reuse its bounded CPU session."""

    # This export is trained and labelled for SemanticKITTI.  The production
    # pipeline uses this capability to reject frames from another dataset
    # before preprocessing or ONNX inference starts.
    supported_datasets = frozenset({"semantickitti"})

    def __init__(
        self, model_path: str | Path, *, threads: int = 2, intensity_scale: float = 1.0
    ) -> None:
        if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
            raise ValueError("threads must be a positive integer")
        if not np.isfinite(intensity_scale) or intensity_scale <= 0:
            raise ValueError("intensity_scale must be finite and positive")
        self.intensity_scale = intensity_scale
        path = Path(model_path)
        if not path.is_file():
            raise ValueError(f"SalsaNext model does not exist: {path}")
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        try:
            self.session = ort.InferenceSession(
                str(path), options, providers=["CPUExecutionProvider"]
            )
        except Exception as error:
            raise ValueError(f"cannot load SalsaNext ONNX model: {error}") from error
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if (
            len(inputs) != 1
            or inputs[0].shape != [1, 5, _IMAGE_HEIGHT, _IMAGE_WIDTH]
            or inputs[0].type != "tensor(float)"
            or len(outputs) != 1
            or outputs[0].shape
            != [1, len(_LEARNING_CLASSES), _IMAGE_HEIGHT, _IMAGE_WIDTH]
        ):
            raise ValueError(
                "model is incompatible with the SalsaNext range-image contract"
            )
        self.input_name, self.output_name = inputs[0].name, outputs[0].name

    def infer(
        self, points: np.ndarray, labels: np.ndarray | None = None
    ) -> SemanticResult:
        tensor, rows, cols, valid = project_scan(
            points, intensity_scale=self.intensity_scale
        )
        if not valid.any():
            return SemanticResult(
                np.zeros(len(rows), np.int32), np.zeros(len(rows), np.float32), "model"
            )
        scores = self.session.run([self.output_name], {self.input_name: tensor})[0]
        return unproject_scores(scores, rows, cols, valid)
