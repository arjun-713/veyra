"""Composition of dataset frames and optional perception backends."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from datasets.common.observation import ObservationFrame
from perception.ground import PatchworkPPGroundSegmenter, height_above_ground
from perception.semantic import GroundTruthSemanticProvider, OnnxSemanticProvider
from perception.semantic.salsanext import SalsaNextSemanticProvider
from perception.temporal import TemporalTracker
from perception.terrain import TerrainAnalyzer


class PerceptionConfigurationError(ValueError):
    """Raised for an incomplete or contradictory perception configuration."""


@dataclass(frozen=True)
class PipelineStatus:
    """Backend status suitable for diagnostics and the visualizer."""

    semantic: str
    ground: str
    terrain: str
    temporal: str
    diagnostics: tuple[str, ...] = ()
    # Verified semantic execution device reported by the running provider
    # (e.g. "bypassed", "cpu", "CPUExecutionProvider", "cuda:0").
    # Never inferred from machine hardware. Defaults to unavailable.
    semantic_execution: str = "unavailable"
    semantic_requested: str | None = None
    semantic_fallback_reason: str | None = None
    semantic_model: str | None = None


@dataclass(frozen=True)
class PipelineOutput:
    frame: ObservationFrame
    status: PipelineStatus
    timings_ms: dict[str, float] = field(default_factory=dict)


class PerceptionPipeline:
    """Run deterministic perception stages over one adapter observation.

    Optional stages fail closed: their existing frame fields are preserved and
    status is marked ``unavailable``. No unavailable backend is replaced by a
    heuristic or fabricated result.
    """

    def __init__(
        self,
        *,
        semantic_provider: Any | None = None,
        ground_segmenter: Any | None = None,
        terrain_analyzer: Any | None = None,
        temporal_tracker: Any | None = None,
        ground_enabled: bool | None = None,
        terrain_enabled: bool | None = None,
        temporal_enabled: bool | None = None,
        required_stages: tuple[str, ...] = (),
        semantic_requested_mode: str | None = None,
        semantic_fallback_reason: str | None = None,
        semantic_model_identity: str | None = None,
        semantic_required_datasets: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.semantic_provider = semantic_provider or GroundTruthSemanticProvider()
        self.semantic_requested_mode = semantic_requested_mode
        self.semantic_fallback_reason = semantic_fallback_reason
        self.semantic_model_identity = semantic_model_identity
        self.semantic_required_datasets = (
            frozenset(semantic_required_datasets)
            if semantic_required_datasets is not None
            else None
        )
        self.ground_segmenter = ground_segmenter
        self.terrain_analyzer = terrain_analyzer
        self.temporal_tracker = temporal_tracker
        self._ground_enabled = ground_enabled
        self._terrain_enabled = terrain_enabled
        self._temporal_enabled = temporal_enabled
        if any(
            name not in {"semantic", "ground", "terrain", "temporal"}
            for name in required_stages
        ):
            raise PerceptionConfigurationError("unknown required perception stage")
        self.required_stages = tuple(required_stages)
        self._last_sequence_key: tuple[str, str] | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> PerceptionPipeline:
        """Construct explicit production stages from a validated config mapping."""

        if not isinstance(config, dict):
            raise PerceptionConfigurationError("perception config must be a mapping")
        semantic_config = cls._config_section(config, "semantic")
        mode = semantic_config.get("mode")
        if mode not in {"ground_truth", "salsanext", "onnx", "cenet"}:
            raise PerceptionConfigurationError(
                "semantic.mode must be explicitly configured as ground_truth, "
                "salsanext, onnx, or cenet"
            )
        semantic_requested_mode = str(mode)
        semantic_fallback_reason: str | None = None
        semantic_model_identity: str | None = None
        semantic_required_datasets: frozenset[str] | None = None
        if mode == "ground_truth":
            semantic_provider = GroundTruthSemanticProvider()
        elif mode == "salsanext":
            if not isinstance(semantic_config.get("model_path"), str):
                raise PerceptionConfigurationError("salsanext requires model_path")
            semantic_provider = SalsaNextSemanticProvider(
                semantic_config["model_path"],
                threads=semantic_config.get("threads", 2),
                intensity_scale=semantic_config.get("intensity_scale", 1.0),
            )
        elif mode == "onnx":
            mapping = semantic_config.get("mapping")
            model_path = semantic_config.get("model_path")
            if not isinstance(mapping, dict) or not isinstance(model_path, str):
                raise PerceptionConfigurationError(
                    "onnx semantic mode requires mapping and model_path"
                )
            providers = semantic_config.get("providers")
            if providers is not None and (
                not isinstance(providers, list)
                or not all(isinstance(item, str) for item in providers)
            ):
                raise PerceptionConfigurationError(
                    "onnx providers must be a string list"
                )
            semantic_provider = OnnxSemanticProvider.from_model_path(
                model_path,
                mapping={int(key): int(value) for key, value in mapping.items()},
                default_class=int(semantic_config.get("default_class", 0)),
                providers=providers,
            )
        elif mode == "cenet":
            allow_fallback_raw = semantic_config.get(
                "allow_fallback_to_ground_truth", False
            )
            if not isinstance(allow_fallback_raw, bool):
                raise PerceptionConfigurationError(
                    "semantic.allow_fallback_to_ground_truth must be boolean"
                )
            semantic_provider, semantic_fallback_reason = cls._cenet_provider(
                semantic_config, allow_fallback_raw
            )
            semantic_required_datasets = frozenset({"semanticposs"})
            if semantic_fallback_reason is None:
                checkpoint_path = getattr(semantic_provider, "checkpoint_path", None)
                if checkpoint_path is not None:
                    semantic_model_identity = str(checkpoint_path)
        else:
            raise PerceptionConfigurationError(f"unsupported semantic mode: {mode}")

        ground_config = cls._config_section(config, "ground")
        terrain_config = cls._config_section(config, "terrain")
        temporal_config = cls._config_section(config, "temporal")
        ground_enabled = cls._enabled(ground_config, "ground")
        terrain_enabled = cls._enabled(terrain_config, "terrain")
        temporal_enabled = cls._enabled(temporal_config, "temporal")
        if terrain_enabled and not ground_enabled:
            raise PerceptionConfigurationError(
                "terrain cannot be enabled without an explicit ground stage"
            )
        required = config.get("required_stages", [])
        if not isinstance(required, (list, tuple)) or not all(
            isinstance(name, str) for name in required
        ):
            raise PerceptionConfigurationError(
                "required_stages must be a list of stage names"
            )
        return cls(
            semantic_provider=semantic_provider,
            ground_segmenter=(
                PatchworkPPGroundSegmenter(**cls._options(ground_config))
                if ground_enabled
                else None
            ),
            terrain_analyzer=(
                TerrainAnalyzer(**cls._options(terrain_config))
                if terrain_enabled
                else None
            ),
            temporal_tracker=(
                TemporalTracker(**cls._options(temporal_config))
                if temporal_enabled
                else None
            ),
            ground_enabled=ground_enabled,
            terrain_enabled=terrain_enabled,
            temporal_enabled=temporal_enabled,
            required_stages=tuple(required),
            semantic_requested_mode=semantic_requested_mode,
            semantic_fallback_reason=semantic_fallback_reason,
            semantic_model_identity=semantic_model_identity,
            semantic_required_datasets=semantic_required_datasets,
        )

    #: Environment override for the CENet checkpoint; wins over config.
    CENET_CHECKPOINT_ENV_VAR = "VEYRA_CENET_CHECKPOINT"

    @classmethod
    def _cenet_provider(
        cls, semantic_config: dict[str, Any], allow_fallback: bool = False
    ) -> tuple[Any, str | None]:
        """Build the native CENet provider, fail-closed unless fallback is allowed.

        torch stays an optional dependency: it is imported only inside the
        CENet provider constructor, never at pipeline import time, so the
        core mapper runs without it. When the weights file is absent or the
        backend cannot be constructed, raise
        ``PerceptionConfigurationError`` unless ``allow_fallback`` is True,
        in which case return an explicit
        ``GroundTruthSemanticProvider`` plus a human-readable fallback
        reason (surfaced per-frame in ``PipelineStatus.diagnostics``).
        Status therefore stays honest: ``model`` only when CENet
        actually runs, ``ground_truth`` on approved fallback.
        """

        threads = semantic_config.get("threads", 4)
        if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
            raise PerceptionConfigurationError(
                "cenet threads must be a positive integer"
            )
        expected_sha = semantic_config.get("checkpoint_sha256")
        if expected_sha is not None and not isinstance(expected_sha, str):
            raise PerceptionConfigurationError(
                "cenet checkpoint_sha256 must be a hex string"
            )
        env_checkpoint = os.environ.get(cls.CENET_CHECKPOINT_ENV_VAR, "").strip()
        configured = semantic_config.get("checkpoint")
        if configured is None:
            configured = semantic_config.get("model_path", "")
        checkpoint = env_checkpoint or (
            configured if isinstance(configured, str) else ""
        )
        source = (
            f"env {cls.CENET_CHECKPOINT_ENV_VAR}"
            if env_checkpoint
            else "config checkpoint"
        )

        def _fallback(reason: str) -> tuple[Any, str]:
            if not allow_fallback:
                raise PerceptionConfigurationError(reason)
            return GroundTruthSemanticProvider(), reason

        if not checkpoint.strip():
            return _fallback(
                "mode 'cenet' requested but no checkpoint configured "
                "(set semantic.checkpoint or VEYRA_CENET_CHECKPOINT); "
                "fell back to ground_truth"
            )
        path = Path(checkpoint)
        if not path.is_file():
            return _fallback(
                f"mode 'cenet' requested but {source} weights absent: {path}; "
                "fell back to ground_truth"
            )
        if expected_sha:
            import hashlib

            digest = hashlib.sha256()
            try:
                with open(path, "rb") as stream:
                    for chunk in iter(lambda: stream.read(1 << 20), b""):
                        digest.update(chunk)
            except OSError as error:
                return _fallback(
                    f"mode 'cenet' requested but {source} weights unreadable: "
                    f"{path} ({error}); fell back to ground_truth"
                )
            if digest.hexdigest() != expected_sha.strip().lower():
                return _fallback(
                    f"mode 'cenet' requested but {source} weights failed "
                    f"sha256 verification: {path}; fell back to ground_truth"
                )
        try:
            from perception.semantic.cenet import CENetSemanticProvider
        except ImportError as error:
            return _fallback(
                f"mode 'cenet' requested but the CENet provider is unavailable "
                f"({error}); fell back to ground_truth"
            )
        try:
            return CENetSemanticProvider(path, threads=threads), None
        except Exception as error:  # noqa: BLE001 -- backend ctor raises
            # release-specific exception types (torch/ONNX/CUDA); the fallback
            # contract is failure-safe by design (never crash, return
            # ground_truth + reason), so narrowing would reintroduce crashes.
            return _fallback(
                f"mode 'cenet' requested but {source} backend unavailable "
                f"({type(error).__name__}: {error}); fell back to ground_truth"
            )

    @staticmethod
    def _config_section(config: dict[str, Any], name: str) -> dict[str, Any]:
        section = config.get(name, {})
        if not isinstance(section, dict):
            raise PerceptionConfigurationError(f"{name} config must be a mapping")
        return section

    @staticmethod
    def _enabled(section: dict[str, Any], name: str) -> bool:
        enabled = section.get("enabled", False)
        if not isinstance(enabled, bool):
            raise PerceptionConfigurationError(f"{name}.enabled must be boolean")
        return enabled

    @staticmethod
    def _options(section: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in section.items() if key != "enabled"}

    def process(self, frame: ObservationFrame) -> PipelineOutput:
        started = perf_counter()
        timings: dict[str, float] = {}
        self._require_dataset_compatibility(frame)
        if "temporal" in self.required_stages and (
            frame.timestamp is None
            or frame.provenance.coordinate_frame != "world"
            or frame.provenance.pose_source != "dataset"
            or frame.provenance.timestamp_source != "dataset"
        ):
            raise RuntimeError(
                "required temporal stage needs measured dataset pose and timestamp provenance"
            )
        if self.temporal_tracker is not None:
            sequence_key = (frame.dataset, frame.sequence)
            if (
                self._last_sequence_key is not None
                and sequence_key != self._last_sequence_key
            ):
                reset = getattr(self.temporal_tracker, "reset", None)
                if callable(reset):
                    reset()
            self._last_sequence_key = sequence_key
        points = frame.points
        sensor_points = points
        if frame.provenance.coordinate_frame in {"world", "calibrated_lidar"}:
            sensor_points = points.copy()
            sensor_points[:, :3] = (
                points[:, :3] - frame.pose.matrix[:3, 3]
            ) @ frame.pose.matrix[:3, :3]
        timings["sensor_transform"] = (perf_counter() - started) * 1000
        stage_started = perf_counter()
        semantic = self.semantic_provider.infer(sensor_points, frame.semantic_class)
        timings["semantic"] = (perf_counter() - stage_started) * 1000
        self._require_size(semantic.semantic_class, points.shape[0], "semantic class")
        self._require_size(
            semantic.semantic_confidence, points.shape[0], "semantic confidence"
        )

        ground = None
        ground_status = "unavailable"
        diagnostics: list[str] = []
        if self.semantic_fallback_reason is not None:
            diagnostics.append(
                f"semantic fallback to ground_truth: {self.semantic_fallback_reason}"
            )
        stage_started = perf_counter()
        if self._ground_enabled is False:
            ground_status = "disabled"
        elif self.ground_segmenter is not None:
            try:
                ground = self.ground_segmenter.segment(sensor_points)
                self._require_size(ground.mask, points.shape[0], "ground mask")
                ground_status = str(ground.backend)
            except RuntimeError as error:
                ground = None
                diagnostics.append(f"ground backend unavailable: {error}")
        # Height above the locally fitted ground. Computed here because the map
        # cannot: layer assignment needs a ground height, and the ground height
        # comes from the returns that layer assignment would select. Stays NaN
        # when no ground stage ran, which the map counts rather than assumes.
        hag = None
        if ground is not None:
            hag = height_above_ground(points, ground.mask)
            self._require_size(hag, points.shape[0], "height above ground")
        timings["ground"] = (perf_counter() - stage_started) * 1000

        terrain = None
        terrain_status = "unavailable"
        stage_started = perf_counter()
        if self._terrain_enabled is False:
            terrain_status = "disabled"
        elif ground is not None and self.terrain_analyzer is not None:
            terrain = self.terrain_analyzer.analyze(points, ground)
            self._require_size(terrain.drivable, points.shape[0], "terrain result")
            terrain_status = "available"
        timings["terrain"] = (perf_counter() - stage_started) * 1000

        motion = None
        temporal_status = "unavailable"
        stage_started = perf_counter()
        if self._temporal_enabled is False:
            temporal_status = "disabled"
        elif (
            self.temporal_tracker is not None
            and frame.timestamp is not None
            and np.isfinite(frame.timestamp)
            and frame.provenance.coordinate_frame == "world"
            and frame.provenance.pose_source == "dataset"
            and frame.provenance.timestamp_source == "dataset"
        ):
            motion = self.temporal_tracker.update(
                points,
                semantic.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
            self._require_size(
                motion.motion_probability, points.shape[0], "motion result"
            )
            if motion.track_id is not None:
                self._require_size(motion.track_id, points.shape[0], "track result")
            temporal_status = "available"
        elif self.temporal_tracker is not None:
            diagnostics.append(
                "temporal stage unavailable: requires dataset timestamp and world coordinates"
            )
        timings["temporal"] = (perf_counter() - stage_started) * 1000
        statuses = {
            "semantic": semantic.mode,
            "ground": ground_status,
            "terrain": terrain_status,
            "temporal": temporal_status,
        }
        for name in self.required_stages:
            if statuses[name] in {"disabled", "unavailable"}:
                raise RuntimeError(
                    f"required {name} stage {statuses[name]}: {diagnostics}"
                )

        output = ObservationFrame(
            timestamp=frame.timestamp,
            pose=frame.pose,
            points=points,
            semantic_class=semantic.semantic_class,
            semantic_confidence=semantic.semantic_confidence,
            ground=ground.mask if ground is not None else frame.ground,
            drivable=terrain.drivable if terrain is not None else frame.drivable,
            slope=terrain.slope if terrain is not None else frame.slope,
            roughness=terrain.roughness if terrain is not None else frame.roughness,
            height_complexity=(
                terrain.height_complexity
                if terrain is not None
                else frame.height_complexity
            ),
            motion_probability=(
                motion.motion_probability
                if motion is not None
                else frame.motion_probability
            ),
            velocity_xy=motion.velocity_xy if motion is not None else frame.velocity_xy,
            dataset=frame.dataset,
            sequence=frame.sequence,
            frame_id=frame.frame_id,
            terrain_confidence=(
                ground.confidence
                if terrain is None and ground is not None
                else terrain.confidence
                if terrain is not None
                else frame.terrain_confidence
            ),
            step=terrain.step if terrain is not None else frame.step,
            motion_state=motion.state if motion is not None else frame.motion_state,
            track_id=(
                motion.track_id
                if motion is not None and motion.track_id is not None
                else frame.track_id
            ),
            observation_quality=self._quality(
                semantic.semantic_confidence,
                terrain,
                ground.mask if ground is not None else frame.ground,
            ),
            height_above_ground=(hag if hag is not None else frame.height_above_ground),
            ground_gradient_x=(
                terrain.gradient_x
                if terrain is not None and terrain.gradient_x is not None
                else frame.ground_gradient_x
            ),
            ground_gradient_y=(
                terrain.gradient_y
                if terrain is not None and terrain.gradient_y is not None
                else frame.ground_gradient_y
            ),
            raw_semantic_class=frame.raw_semantic_class,
            instance_id=frame.instance_id,
            provenance=frame.provenance,
        )
        return PipelineOutput(
            frame=output,
            status=PipelineStatus(
                semantic=semantic.mode,
                ground=ground_status,
                terrain=terrain_status,
                temporal=temporal_status,
                diagnostics=tuple(diagnostics),
                semantic_execution=self._provider_execution_device(),
                semantic_requested=self.semantic_requested_mode,
                semantic_fallback_reason=self.semantic_fallback_reason,
                semantic_model=self.semantic_model_identity,
            ),
            timings_ms={**timings, "total": (perf_counter() - started) * 1000},
        )

    def _provider_execution_device(self) -> str:
        """Verified execution device from the running provider, same pattern
        as the dataset-capability gate: a convention attribute, never hardware
        sniffing. Unknown providers stay unavailable rather than guessed."""
        device = getattr(self.semantic_provider, "execution_device", None)
        return device if isinstance(device, str) and device else "unavailable"

    def _require_dataset_compatibility(self, frame: ObservationFrame) -> None:
        """Fail closed when a provider declares a dataset capability boundary."""

        requested = self.semantic_required_datasets
        if requested is not None:
            try:
                requested_datasets = frozenset(requested)
            except TypeError as error:
                raise PerceptionConfigurationError(
                    "semantic provider supported_datasets must be an iterable of dataset names"
                ) from error
            if frame.dataset not in requested_datasets:
                requested_names = ", ".join(sorted(requested_datasets)) or "none"
                raise PerceptionConfigurationError(
                    f"semantic mode {self.semantic_requested_mode} "
                    f"supports only {requested_names}, not {frame.dataset}"
                )
        supported = getattr(self.semantic_provider, "supported_datasets", None)
        if supported is None:
            return
        try:
            supported_datasets = frozenset(supported)
        except TypeError as error:
            raise PerceptionConfigurationError(
                "semantic provider supported_datasets must be an iterable of dataset names"
            ) from error
        if frame.dataset not in supported_datasets:
            supported_names = ", ".join(sorted(supported_datasets)) or "none"
            raise PerceptionConfigurationError(
                f"semantic provider {type(self.semantic_provider).__name__} "
                f"supports only {supported_names}, not {frame.dataset}"
            )

    @staticmethod
    def _quality(
        semantic_confidence: np.ndarray, terrain: Any | None, ground: np.ndarray
    ) -> np.ndarray:
        semantic = np.asarray(semantic_confidence, dtype=np.float32)
        if terrain is None:
            return semantic
        # Terrain support is meaningful for a ground surface, not for a pole,
        # person or vehicle. The mapper independently gates local sample support.
        return np.where(
            ground,
            np.minimum(semantic, np.asarray(terrain.confidence, dtype=np.float32)),
            semantic,
        )

    @staticmethod
    def _require_size(values: np.ndarray, count: int, name: str) -> None:
        if np.asarray(values).reshape(-1).shape != (count,):
            raise ValueError(f"{name} must contain one value per point")


def load_perception_pipeline(path: str | Path) -> PerceptionPipeline:
    """Load a local, explicit YAML configuration into a perception pipeline."""

    config_path = Path(path)
    if not config_path.is_file():
        raise PerceptionConfigurationError(
            f"perception configuration does not exist: {config_path}"
        )
    try:
        import yaml
    except ImportError as error:
        raise PerceptionConfigurationError(
            "PyYAML is required to load a perception configuration"
        ) from error
    try:
        config = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as error:
        raise PerceptionConfigurationError(
            f"invalid perception YAML: {config_path}"
        ) from error
    return PerceptionPipeline.from_config(config)


__all__ = [
    "PerceptionConfigurationError",
    "PerceptionPipeline",
    "PipelineOutput",
    "PipelineStatus",
    "load_perception_pipeline",
]
