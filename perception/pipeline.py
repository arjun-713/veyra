"""Composition of dataset frames and optional perception backends."""

from __future__ import annotations

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
    ) -> None:
        self.semantic_provider = semantic_provider or GroundTruthSemanticProvider()
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
        if mode not in {"ground_truth", "salsanext", "onnx"}:
            raise PerceptionConfigurationError(
                "semantic.mode must be explicitly configured as ground_truth, "
                "salsanext, or onnx"
            )
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
            observation_quality=(self._quality(semantic.semantic_confidence, terrain)),
            height_above_ground=(
                hag if hag is not None else frame.height_above_ground
            ),
            raw_semantic_class=frame.raw_semantic_class,
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
            ),
            timings_ms={**timings, "total": (perf_counter() - started) * 1000},
        )

    @staticmethod
    def _quality(semantic_confidence: np.ndarray, terrain: Any | None) -> np.ndarray:
        if terrain is None:
            return np.asarray(semantic_confidence, dtype=np.float32)
        return np.minimum(
            np.asarray(semantic_confidence, dtype=np.float32),
            np.asarray(terrain.confidence, dtype=np.float32),
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
