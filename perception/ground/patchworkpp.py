"""A strict integration boundary for an installed Patchwork++ binding.

This module deliberately does not provide a geometric fallback. Ground labels
are safety-relevant evidence, so silently replacing Patchwork++ with another
algorithm would make results look valid while changing their meaning.
"""

import importlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np


class PatchworkPPUnavailableError(RuntimeError):
    """Raised when no supported Patchwork++ Python binding can be used."""


@dataclass(frozen=True)
class GroundBackendAvailability:
    """A displayable result of official Patchwork++ binding discovery."""

    available: bool
    backend: str | None
    diagnostic: str


@dataclass(frozen=True)
class GroundEvidence:
    """Per-point ground evidence returned by a ground segmenter."""

    mask: np.ndarray
    confidence: np.ndarray
    backend: str

    def __post_init__(self) -> None:
        mask = np.array(self.mask, dtype=bool, copy=True)
        confidence = np.array(self.confidence, dtype=np.float32, copy=True)
        if mask.ndim != 1 or confidence.ndim != 1:
            raise ValueError("ground mask and confidence must be one-dimensional")
        if mask.shape != confidence.shape:
            raise ValueError("ground mask and confidence must have identical shape")
        if not np.all(np.isfinite(confidence)) or np.any(
            (confidence < 0.0) | (confidence > 1.0)
        ):
            raise ValueError("ground confidence must be finite and within [0, 1]")
        if not self.backend:
            raise ValueError("ground backend must be a non-empty name")
        object.__setattr__(self, "mask", mask)
        object.__setattr__(self, "confidence", confidence)
        mask.setflags(write=False)
        confidence.setflags(write=False)


class PatchworkPPGroundSegmenter:
    """Run a supported, installed Patchwork++ Python binding.

    The binding is loaded lazily so applications can import the perception
    package on machines that do not have the optional dependency installed.
    ``module_names`` is injectable for deterministic discovery tests, while
    the default list contains only known Patchwork++ binding names.
    """

    _DEFAULT_MODULES = ("pypatchworkpp",)

    def __init__(
        self,
        *,
        module_names: Iterable[str] | None = None,
        executable_names: Iterable[str] = (),
    ) -> None:
        # executable_names is retained as diagnostic context, but an arbitrary
        # executable cannot be treated as Patchwork++ without a defined API.
        self._module_names = tuple(module_names or self._DEFAULT_MODULES)
        self._executable_names = tuple(executable_names)
        self._binding: Any | None = None
        self._backend_name: str | None = None

    def segment(self, points: np.ndarray) -> GroundEvidence:
        """Return aligned Patchwork++ ground mask and confidence."""

        points = np.asarray(points, dtype=np.float32)
        if points.ndim != 2 or points.shape[1] not in (3, 4):
            raise ValueError("points must have shape (N, 3) or (N, 4)")
        if not np.all(np.isfinite(points)):
            raise ValueError("points must contain finite coordinates")
        binding, backend_name = self._load_binding()
        mask, confidence = self._invoke(binding, points)
        return GroundEvidence(mask, confidence, backend_name)

    def availability(self) -> GroundBackendAvailability:
        """Report whether a genuine binding can load; never use a fallback."""

        try:
            _, backend_name = self._load_binding()
        except PatchworkPPUnavailableError as error:
            return GroundBackendAvailability(False, None, str(error))
        return GroundBackendAvailability(True, backend_name, "official binding loaded")

    def _load_binding(self) -> tuple[Any, str]:
        if self._binding is not None and self._backend_name is not None:
            return self._binding, self._backend_name

        failures: list[str] = []
        for module_name in self._module_names:
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                failures.append(f"{module_name}: {exc}")
                continue
            factory = getattr(module, "patchworkpp", None)
            parameters = getattr(module, "Parameters", None)
            if not callable(factory) or not callable(parameters):
                failures.append(
                    f"{module_name}: official Parameters/patchworkpp API is missing"
                )
                continue
            try:
                binding = factory(parameters())
            except (ImportError, RuntimeError, TypeError, ValueError) as exc:
                failures.append(f"{module_name}.patchworkpp: {exc}")
                continue
            self._binding = binding
            self._backend_name = f"{module_name}.patchworkpp"
            return binding, self._backend_name

        attempted = ", ".join(self._module_names)
        executable_note = (
            f"; executable candidates not used without a defined binding API: "
            f"{', '.join(self._executable_names)}"
            if self._executable_names
            else ""
        )
        detail = " | ".join(failures) if failures else "no candidates configured"
        raise PatchworkPPUnavailableError(
            "Patchwork++ is unavailable: install/configure a supported Python "
            f"binding (tried {attempted}){executable_note}. Diagnostics: {detail}"
        )

    @staticmethod
    def _invoke(binding: Any, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        estimate = getattr(binding, "estimateGround", None)
        get_indices = getattr(binding, "getGroundIndices", None)
        if not callable(estimate) or not callable(get_indices):
            raise PatchworkPPUnavailableError(
                "Patchwork++ binding does not expose the official "
                "estimateGround(points)/getGroundIndices() API"
            )
        estimate(points)
        indices = np.asarray(get_indices(), dtype=np.intp).reshape(-1)
        if np.any(indices < 0) or np.any(indices >= points.shape[0]):
            raise ValueError("Patchwork++ returned an out-of-range ground index")
        mask = np.zeros(points.shape[0], dtype=bool)
        mask[indices] = True
        # The official binding exposes a binary mask, not calibrated confidence.
        # Use binary support confidence and document that it is not a probability.
        return mask, mask.astype(np.float32)

    @staticmethod
    def _unpack_result(result: Any, point_count: int) -> tuple[np.ndarray, np.ndarray]:
        if isinstance(result, dict):
            mask = result.get("mask", result.get("ground_mask"))
            confidence = result.get("confidence", result.get("ground_confidence"))
        elif isinstance(result, (tuple, list)) and len(result) == 2:
            mask, confidence = result
        else:
            mask = getattr(result, "mask", getattr(result, "ground_mask", None))
            confidence = getattr(
                result, "confidence", getattr(result, "ground_confidence", None)
            )
        if mask is None or confidence is None:
            raise ValueError("Patchwork++ result must contain mask and confidence")
        mask = np.asarray(mask, dtype=bool)
        confidence = np.asarray(confidence, dtype=np.float32)
        if mask.shape != (point_count,) or confidence.shape != (point_count,):
            raise ValueError(
                "Patchwork++ result must provide one mask and confidence value "
                f"per point; expected ({point_count},)"
            )
        return mask, confidence
