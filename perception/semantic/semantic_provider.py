"""Dataset-independent semantic inference boundary.

Providers operate on XYZI points and return mapped Veyra class IDs. Model
loading is deliberately outside this module: callers must inject an already
configured ONNX Runtime-compatible session.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class SemanticProviderConfigurationError(ValueError):
    """The provider was not configured with a usable explicit backend."""


class SemanticProviderUnavailableError(RuntimeError):
    """The explicitly configured backend cannot execute inference."""


@dataclass(frozen=True)
class SemanticResult:
    """Per-point semantic class and confidence returned by a provider."""

    semantic_class: np.ndarray
    semantic_confidence: np.ndarray
    mode: str

    def __post_init__(self) -> None:
        classes = np.array(self.semantic_class, dtype=np.int32, copy=True)
        confidence = np.array(self.semantic_confidence, dtype=np.float32, copy=True)
        if classes.ndim != 1 or confidence.ndim != 1:
            raise ValueError("semantic result arrays must be one-dimensional")
        if classes.shape != confidence.shape:
            raise ValueError("semantic result arrays must be aligned")
        if not np.all(np.isfinite(confidence)) or np.any(
            (confidence < 0.0) | (confidence > 1.0)
        ):
            raise ValueError("semantic confidence must be finite and in [0, 1]")
        if self.mode not in {"ground_truth", "model"}:
            raise ValueError("semantic mode must be 'ground_truth' or 'model'")
        object.__setattr__(self, "semantic_class", classes)
        object.__setattr__(self, "semantic_confidence", confidence)
        classes.setflags(write=False)
        confidence.setflags(write=False)


class SemanticProvider(Protocol):
    """Boundary consumed by the perception pipeline."""

    def infer(
        self, points: np.ndarray, labels: np.ndarray | None = None
    ) -> SemanticResult:
        """Return one semantic result for each XYZI point."""


class GroundTruthSemanticProvider:
    """Use already mapped dataset labels as deterministic semantic output."""

    def infer(
        self, points: np.ndarray, labels: np.ndarray | None = None
    ) -> SemanticResult:
        # Ground-truth callers may pass mapped labels as the sole argument;
        # pipeline callers can pass the same labels in the second slot next to
        # the corresponding XYZI points.
        classes = np.asarray(points if labels is None else labels, dtype=np.int32)
        if classes.ndim != 1:
            raise ValueError("ground-truth labels must be one-dimensional")
        return SemanticResult(
            semantic_class=classes,
            semantic_confidence=np.ones(classes.shape, dtype=np.float32),
            mode="ground_truth",
        )


class _SessionLike(Protocol):
    def get_inputs(self) -> list[Any]: ...

    def get_outputs(self) -> list[Any]: ...

    def run(
        self, output_names: list[str], feed: dict[str, np.ndarray]
    ) -> list[Any]: ...


class OnnxSemanticProvider:
    """Run an explicitly injected ONNX Runtime-compatible semantic session.

    The session must expose two outputs: integer/raw class IDs and a
    per-point confidence probability. The mapping is applied to raw IDs and
    unknown IDs map to ``default_class``.
    """

    def __init__(
        self,
        *,
        session: _SessionLike | None = None,
        model: _SessionLike | None = None,
        mapping: Mapping[int, int],
        default_class: int = 0,
    ) -> None:
        if session is not None and model is not None:
            raise SemanticProviderConfigurationError(
                "supply exactly one explicit ONNX session or model"
            )
        backend = session if session is not None else model
        if backend is None or isinstance(backend, (str, bytes)):
            raise SemanticProviderConfigurationError(
                "an explicit ONNX Runtime session or model is required; "
                "weights are never downloaded automatically"
            )
        self._session = backend
        self._mapping = dict(mapping)
        self._default_class = int(default_class)
        self._input_name, self._label_name, self._confidence_name = (
            self._validate_metadata()
        )

    @classmethod
    def from_model_path(
        cls,
        model_path: str | Path,
        *,
        mapping: Mapping[int, int],
        default_class: int = 0,
        providers: list[str] | None = None,
    ) -> OnnxSemanticProvider:
        """Open a supplied local ONNX model without downloading weights."""

        path = Path(model_path)
        if not path.is_file():
            raise SemanticProviderConfigurationError(
                f"ONNX semantic model does not exist: {path}"
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise SemanticProviderConfigurationError(
                "onnxruntime is required for model-path semantic inference; "
                "install it explicitly with the selected execution provider"
            ) from exc
        try:
            session = ort.InferenceSession(str(path), providers=providers)
        except Exception as exc:  # runtime exception classes differ by release
            raise SemanticProviderUnavailableError(
                f"could not initialize configured ONNX model: {path}"
            ) from exc
        return cls(session=session, mapping=mapping, default_class=default_class)

    def _validate_metadata(self) -> tuple[str, str, str]:
        try:
            inputs = self._session.get_inputs()
            outputs = self._session.get_outputs()
        except (AttributeError, TypeError) as exc:
            raise SemanticProviderConfigurationError(
                "ONNX backend must expose get_inputs/get_outputs metadata"
            ) from exc
        if len(inputs) != 1 or len(outputs) != 2:
            raise SemanticProviderConfigurationError(
                "semantic ONNX model must have one input and two outputs "
                "(class IDs, confidence)"
            )
        input_info, label_info, confidence_info = inputs[0], outputs[0], outputs[1]
        input_shape = getattr(input_info, "shape", None)
        if (
            input_shape is not None
            and input_shape
            and input_shape[-1] not in (None, 4, "4")
        ):
            raise SemanticProviderConfigurationError(
                "semantic ONNX input must have XYZI width 4"
            )
        for info, name in ((label_info, "class"), (confidence_info, "confidence")):
            shape = getattr(info, "shape", None)
            if shape is not None and len(shape) not in (1, 2):
                raise SemanticProviderConfigurationError(
                    f"semantic ONNX {name} output must be shaped (N,) or (N, 1)"
                )
            if (
                shape is not None
                and len(shape) == 2
                and shape[-1] not in (None, 1, "1")
            ):
                raise SemanticProviderConfigurationError(
                    f"semantic ONNX {name} output must have width 1"
                )
        return input_info.name, label_info.name, confidence_info.name

    def infer(
        self, points: np.ndarray, labels: np.ndarray | None = None
    ) -> SemanticResult:
        del labels
        points_array = np.asarray(points, dtype=np.float32)
        if points_array.ndim != 2 or points_array.shape[1] != 4:
            raise ValueError("semantic inference points must have shape (N, 4)")
        if not np.all(np.isfinite(points_array)):
            raise ValueError("semantic inference points must be finite")
        try:
            outputs = self._session.run(
                [self._label_name, self._confidence_name],
                {self._input_name: points_array},
            )
        except Exception as exc:  # backend exceptions are not stable across runtimes
            raise SemanticProviderUnavailableError(
                "the configured ONNX semantic backend could not run inference"
            ) from exc
        if len(outputs) != 2:
            raise ValueError(
                "semantic ONNX inference must return class IDs and confidence"
            )
        raw_classes = np.asarray(outputs[0]).reshape(-1)
        confidence = np.asarray(outputs[1], dtype=np.float32).reshape(-1)
        if (
            raw_classes.shape != (points_array.shape[0],)
            or confidence.shape != raw_classes.shape
        ):
            raise ValueError("semantic ONNX outputs must contain one value per point")
        mapped = np.array(
            [self._mapping.get(int(raw), self._default_class) for raw in raw_classes],
            dtype=np.int32,
        )
        return SemanticResult(mapped, confidence, mode="model")


__all__ = [
    "GroundTruthSemanticProvider",
    "OnnxSemanticProvider",
    "SemanticProvider",
    "SemanticProviderConfigurationError",
    "SemanticProviderUnavailableError",
    "SemanticResult",
]
