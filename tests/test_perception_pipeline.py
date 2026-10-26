"""Perception pipeline regression suite."""

import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np

from benchmarks.protocol import binary_frame_bytes, frame_records, stream_file
from datasets.common.observation import (
    FrameProvenance,
    ObservationFrame,
    PoseSE3,
    SemanticFrame,
)
from datasets.rellis import Rellis3DDataset
from datasets.semanticposs import SemanticPOSSDataset
from datasets.semanticposs.adapter import (
    SemanticPOSSDataset as RedTeamSemanticPOSSDataset,
)
from perception.ground import GroundEvidence, PatchworkPPUnavailableError
from perception.pipeline import PerceptionPipeline, load_perception_pipeline
from perception.semantic import GroundTruthSemanticProvider, SemanticResult
from perception.temporal import MotionEvidence
from perception.terrain import TerrainEvidence

# Perception pipeline


class _SemanticProvider:
    def infer(self, points, labels=None):
        del points, labels
        return SemanticResult(
            semantic_class=np.array([4, 7, 7], dtype=np.int32),
            semantic_confidence=np.array([0.9, 0.8, 0.8], dtype=np.float32),
            mode="ground_truth",
        )


class _DatasetAwareSemanticProvider:
    supported_datasets = frozenset({"semanticposs"})

    def __init__(self):
        self.inference_calls = 0

    def infer(self, points, labels=None):
        self.inference_calls += 1
        del points, labels
        return SemanticResult(
            semantic_class=np.array([4, 7, 7], dtype=np.int32),
            semantic_confidence=np.array([0.9, 0.8, 0.8], dtype=np.float32),
            mode="model",
        )


class _IncompatibleSemanticProvider:
    supported_datasets = frozenset({"semantickitti"})

    def infer(self, points, labels=None):
        raise AssertionError("incompatible provider must not be called")


class _GroundSegmenter:
    def segment(self, points):
        return GroundEvidence(
            mask=np.array([True, True, False]),
            confidence=np.array([1.0, 0.8, 0.0], dtype=np.float32),
            backend="test-patchworkpp",
        )


class _TerrainAnalyzer:
    def analyze(self, points, ground):
        del points, ground
        return TerrainEvidence(
            slope=np.array([0.1, 0.2, np.nan], dtype=np.float32),
            roughness=np.array([0.01, 0.02, np.nan], dtype=np.float32),
            height_complexity=np.array([0.03, 0.04, np.nan], dtype=np.float32),
            step=np.array([0.0, 0.1, np.nan], dtype=np.float32),
            drivable=np.array(["drivable", "drivable", "unknown"]),
            confidence=np.array([0.9, 0.7, 0.0], dtype=np.float32),
        )


class _TemporalTracker:
    def update(self, points, semantic_class, pose, *, timestamp):
        del points, semantic_class, pose, timestamp
        return MotionEvidence(
            motion_probability=np.array([0.0, 0.75, 0.75], dtype=np.float32),
            velocity_xy=np.array(
                [[0.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=np.float32
            ),
            state=np.array(["static", "moving", "moving"]),
            persistence=np.array([1, 2, 2], dtype=np.int32),
        )


def _frame(timestamp=2.0):
    return ObservationFrame(
        timestamp=timestamp,
        pose=PoseSE3.identity(timestamp),
        points=np.array(
            [[0.0, 0.0, 0.0, 1.0], [1.0, 0.0, 0.0, 1.0], [2.0, 0.0, 1.0, 1.0]],
            dtype=np.float32,
        ),
        semantic_class=np.array([0, 0, 0], dtype=np.int32),
        semantic_confidence=np.zeros(3, dtype=np.float32),
        ground=np.zeros(3, dtype=bool),
        drivable=np.full(3, "unknown"),
        slope=np.full(3, np.nan, dtype=np.float32),
        roughness=np.full(3, np.nan, dtype=np.float32),
        height_complexity=np.full(3, np.nan, dtype=np.float32),
        motion_probability=np.zeros(3, dtype=np.float32),
        velocity_xy=np.zeros((3, 2), dtype=np.float32),
        instance_id=np.array([7, 8, 9], dtype=np.int32),
        dataset="synthetic-test",
        sequence="00",
        frame_id="000000",
    )


class PerceptionPipelineTests(unittest.TestCase):
    def test_incompatible_provider_is_rejected_before_inference(self):
        with self.assertRaisesRegex(
            ValueError,
            "semantic provider .* supports only semantickitti, not semanticposs",
        ):
            PerceptionPipeline(
                semantic_provider=_IncompatibleSemanticProvider()
            ).process(replace(_frame(), dataset="semanticposs"))

    def test_dataset_compatible_labelled_provider_is_allowed(self):
        provider = _DatasetAwareSemanticProvider()

        output = PerceptionPipeline(semantic_provider=provider).process(
            replace(_frame(), dataset="semanticposs")
        )

        self.assertEqual(provider.inference_calls, 1)
        self.assertEqual(output.status.semantic, "model")

    def test_status_carries_verified_provider_execution_device(self):
        from perception.pipeline import PerceptionPipeline as Pipeline

        self.assertEqual(Pipeline()._provider_execution_device(), "bypassed")

        class NoDeviceProvider:
            supported_datasets = frozenset({"semanticposs"})

            def infer(self, points, labels=None):
                raise AssertionError("must not run")

        self.assertEqual(
            Pipeline(semantic_provider=NoDeviceProvider())._provider_execution_device(),
            "unavailable",
        )

    def test_config_requires_explicit_semantic_mode(self):
        with self.assertRaisesRegex(Exception, "semantic.mode"):
            PerceptionPipeline.from_config({"semantic": {}, "ground": {}})

    def test_optional_temporal_rejects_unproven_metadata_without_advancing(self):
        class MustNotAdvance:
            def update(self, *args, **kwargs):
                raise AssertionError("unproven metadata advanced tracker")

        result = PerceptionPipeline(temporal_tracker=MustNotAdvance()).process(_frame())
        self.assertEqual(result.status.temporal, "unavailable")
        self.assertTrue(result.status.diagnostics)
        np.testing.assert_array_equal(result.frame.motion_state, ["unknown"] * 3)

    def test_sensor_backends_receive_inverse_pose_without_changing_map_coordinates(
        self,
    ):
        class CoordinateSemantics:
            def infer(self, points, labels=None):
                return SemanticResult(
                    (points[:, 0] > 1.5).astype(np.int32), np.ones(len(points)), "model"
                )

        class CoordinateGround:
            def segment(self, points):
                return GroundEvidence(
                    points[:, 2] < 0.5, np.ones(len(points)), "coordinate-ground"
                )

        original = _frame()
        matrix = np.array([[0.0, -1, 0, 10], [1, 0, 0, -5], [0, 0, 1, 7], [0, 0, 0, 1]])
        points = original.points.copy()
        points[:, :3] = points[:, :3] @ matrix[:3, :3].T + matrix[:3, 3]
        frame = replace(
            original,
            points=points,
            pose=PoseSE3(matrix),
            provenance=FrameProvenance(coordinate_frame="world", pose_source="dataset"),
        )
        result = PerceptionPipeline(
            semantic_provider=CoordinateSemantics(), ground_segmenter=CoordinateGround()
        ).process(frame)
        np.testing.assert_array_equal(result.frame.semantic_class, [0, 0, 1])
        np.testing.assert_array_equal(result.frame.ground, [True, True, False])
        np.testing.assert_array_equal(result.frame.points, points)
        np.testing.assert_array_equal(result.frame.instance_id, [7, 8, 9])

    def test_strict_required_ground_failure_raises(self):
        class BrokenGround:
            def segment(self, points):
                raise RuntimeError("backend crashed")

        with self.assertRaises(RuntimeError):
            PerceptionPipeline(
                ground_segmenter=BrokenGround(), required_stages=("ground",)
            ).process(_frame())

    def test_strict_temporal_refuses_unproven_pose_metadata(self):
        class MustNotAdvance:
            def update(self, *args, **kwargs):
                raise AssertionError("invalid provenance advanced temporal state")

        with self.assertRaises(RuntimeError):
            PerceptionPipeline(
                temporal_tracker=MustNotAdvance(), required_stages=("temporal",)
            ).process(_frame())

    def test_checked_in_default_config_runs_ground_truth_ground_and_terrain(
        self,
    ):
        if not all(
            Path(root).is_dir()
            for root in ("data/raw/semanticposs/dataset", "data/raw/rellis3d/Rellis-3D")
        ):
            self.skipTest("requires original local SemanticPOSS and RELLIS datasets")
        if importlib.util.find_spec("pypatchworkpp") is None:
            self.skipTest("requires pypatchworkpp for real ground validation")
        pipeline = load_perception_pipeline("configs/perception.yaml")
        sources = (
            (SemanticPOSSDataset(Path("data/raw/semanticposs/dataset")), "00"),
            (Rellis3DDataset(Path("data/raw/rellis3d/Rellis-3D")), "00000"),
        )

        for adapter, sequence in sources:
            frames = list(adapter.replay(sequence, end=3, max_range_m=100.0))
            outputs = [pipeline.process(frame) for frame in frames]
            self.assertEqual(len(outputs), 3)
            self.assertTrue(
                all(output.status.semantic == "ground_truth" for output in outputs)
            )
            self.assertTrue(
                all(
                    output.status.ground not in {"disabled", "unavailable"}
                    for output in outputs
                )
            )
            self.assertTrue(
                all(output.status.terrain == "available" for output in outputs)
            )
            self.assertTrue(
                all(output.status.temporal == "disabled" for output in outputs)
            )
            self.assertTrue(all(np.any(output.frame.ground) for output in outputs))
            self.assertTrue(all(output.frame.points.shape[0] > 0 for output in outputs))

    def test_sequence_change_resets_an_enabled_temporal_tracker(self):
        class ResetAwareTracker(_TemporalTracker):
            def __init__(self):
                self.reset_count = 0

            def reset(self):
                self.reset_count += 1

        tracker = ResetAwareTracker()
        pipeline = PerceptionPipeline(
            semantic_provider=_SemanticProvider(), temporal_tracker=tracker
        )

        pipeline.process(_frame())
        pipeline.process(replace(_frame(), sequence="01"))

        self.assertEqual(tracker.reset_count, 1)

    def test_yaml_loader_builds_the_explicit_default_production_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "perception.yaml"
            path.write_text(
                "semantic:\n  mode: ground_truth\nground:\n  enabled: false\n"
                "terrain:\n  enabled: false\ntemporal:\n  enabled: false\n"
            )

            pipeline = load_perception_pipeline(path)

        self.assertEqual(pipeline.process(_frame()).status.ground, "disabled")

    def test_factory_configures_ground_truth_mode_and_explicitly_disabled_stages(self):
        pipeline = PerceptionPipeline.from_config(
            {
                "semantic": {"mode": "ground_truth"},
                "ground": {"enabled": False},
                "terrain": {"enabled": False},
                "temporal": {"enabled": False},
            }
        )

        output = pipeline.process(_frame())

        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertEqual(output.status.ground, "disabled")
        self.assertEqual(output.status.terrain, "disabled")
        self.assertEqual(output.status.temporal, "disabled")

    def test_ground_backend_diagnostic_is_not_silently_discarded(self):
        class BrokenGround:
            def segment(self, points):
                raise RuntimeError("backend crashed")

        output = PerceptionPipeline(ground_segmenter=BrokenGround()).process(_frame())
        self.assertEqual(output.status.ground, "unavailable")
        self.assertIn("backend crashed", output.status.diagnostics[0])

    def test_composes_injected_evidence_into_one_observation_frame(self):
        output = PerceptionPipeline(
            semantic_provider=_SemanticProvider(),
            ground_segmenter=_GroundSegmenter(),
            terrain_analyzer=_TerrainAnalyzer(),
            temporal_tracker=_TemporalTracker(),
        ).process(
            replace(
                _frame(),
                provenance=FrameProvenance(
                    coordinate_frame="world",
                    pose_source="dataset",
                    timestamp_source="dataset",
                ),
            )
        )

        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertEqual(output.status.ground, "test-patchworkpp")
        self.assertEqual(output.status.terrain, "available")
        self.assertEqual(output.status.temporal, "available")
        np.testing.assert_array_equal(output.frame.semantic_class, [4, 7, 7])
        np.testing.assert_array_equal(output.frame.ground, [True, True, False])
        np.testing.assert_array_equal(
            output.frame.drivable, ["drivable", "drivable", "unknown"]
        )
        np.testing.assert_allclose(output.frame.velocity_xy[:, 0], [0.0, 1.0, 1.0])
        np.testing.assert_array_equal(
            output.frame.motion_state, ["static", "moving", "moving"]
        )
        np.testing.assert_allclose(output.frame.observation_quality, [0.9, 0.7, 0.8])

    def test_missing_terrain_support_does_not_erase_weak_non_ground_semantics(self):
        class WeakObjectProvider(_SemanticProvider):
            def infer(self, points, labels=None):
                return replace(
                    super().infer(points, labels),
                    semantic_confidence=np.array([0.9, 0.8, 0.2], dtype=np.float32),
                )

        class UnsupportedTerrain(_TerrainAnalyzer):
            def analyze(self, points, ground):
                return replace(
                    super().analyze(points, ground),
                    confidence=np.zeros(3, dtype=np.float32),
                )

        output = PerceptionPipeline(
            semantic_provider=WeakObjectProvider(),
            ground_segmenter=_GroundSegmenter(),
            terrain_analyzer=UnsupportedTerrain(),
            temporal_enabled=False,
        ).process(_frame())

        # The actual ground stage, not the input's all-false mask, owns this gate.
        np.testing.assert_array_equal(output.frame.ground, [True, True, False])
        np.testing.assert_allclose(output.frame.observation_quality, [0.0, 0.0, 0.2])
        np.testing.assert_array_equal(output.frame.terrain_confidence, [0.0, 0.0, 0.0])
        self.assertEqual(output.frame.drivable[2], "unknown")
        self.assertEqual(output.status.temporal, "disabled")
        self.assertEqual(output.frame.motion_probability[2], 0.0)

    def test_without_terrain_quality_remains_semantic_confidence(self):
        output = PerceptionPipeline(
            semantic_provider=_SemanticProvider(),
            ground_segmenter=_GroundSegmenter(),
            terrain_enabled=False,
            temporal_enabled=False,
        ).process(_frame())
        np.testing.assert_allclose(output.frame.observation_quality, [0.9, 0.8, 0.8])
        self.assertEqual(output.status.terrain, "disabled")

    def test_unknown_semantics_do_not_gain_quality_from_non_ground_status(self):
        output = PerceptionPipeline(
            semantic_provider=GroundTruthSemanticProvider(),
            ground_segmenter=_GroundSegmenter(),
            terrain_analyzer=_TerrainAnalyzer(),
            temporal_enabled=False,
        ).process(_frame())
        np.testing.assert_array_equal(output.frame.semantic_class, [0, 0, 0])
        np.testing.assert_array_equal(output.frame.observation_quality, [0.0, 0.0, 0.0])
        self.assertEqual(output.frame.drivable[2], "unknown")

    def test_unavailable_optional_backends_are_reported_without_fabricated_evidence(
        self,
    ):
        class UnavailableGround:
            def segment(self, points):
                del points
                raise PatchworkPPUnavailableError("Patchwork++ unavailable")

        output = PerceptionPipeline(
            semantic_provider=_SemanticProvider(),
            ground_segmenter=UnavailableGround(),
        ).process(_frame())

        self.assertEqual(output.status.ground, "unavailable")
        self.assertEqual(output.status.terrain, "unavailable")
        self.assertEqual(output.status.temporal, "unavailable")
        np.testing.assert_array_equal(output.frame.ground, np.zeros(3, dtype=bool))
        np.testing.assert_array_equal(output.frame.drivable, np.full(3, "unknown"))
        self.assertTrue(np.all(np.isnan(output.frame.slope)))

    def test_missing_timestamp_skips_temporal_update(self):
        class ShouldNotRun:
            def update(self, *args, **kwargs):
                raise AssertionError("temporal tracker must not run without timestamp")

        output = PerceptionPipeline(
            semantic_provider=_SemanticProvider(),
            temporal_tracker=ShouldNotRun(),
        ).process(_frame(timestamp=None))

        self.assertEqual(output.status.temporal, "unavailable")
        np.testing.assert_array_equal(output.frame.motion_probability, np.zeros(3))


class CenetModeTests(unittest.TestCase):
    """`mode: cenet` wiring: neural selection plus failure-safe fallback.

    All cases are hermetic: no real checkpoint, no torch import, no real
    inference. The neural-selection case patches the provider constructor
    with a NumPy-only fake.
    """

    @staticmethod
    def _config(semantic):
        return {
            "semantic": semantic,
            "ground": {"enabled": False},
            "terrain": {"enabled": False},
            "temporal": {"enabled": False},
        }

    def test_cenet_mode_falls_back_to_ground_truth_when_weights_absent(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
            pipeline = PerceptionPipeline.from_config(
                self._config(
                    {
                        "mode": "cenet",
                        "checkpoint": "/nonexistent/cenet-weights.bin",
                        "allow_fallback_to_ground_truth": True,
                    }
                )
            )

        self.assertIsInstance(pipeline.semantic_provider, GroundTruthSemanticProvider)
        self.assertEqual(pipeline.semantic_requested_mode, "cenet")
        self.assertIsNotNone(pipeline.semantic_fallback_reason)
        self.assertIn(
            "/nonexistent/cenet-weights.bin", pipeline.semantic_fallback_reason
        )

        output = pipeline.process(replace(_frame(), dataset="semanticposs"))

        # Provenance stays explicit: fallback output is reported as ground
        # truth, never relabelled as neural output.
        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertTrue(
            any(
                "cenet" in diagnostic and "ground_truth" in diagnostic
                for diagnostic in output.status.diagnostics
            )
        )

    def test_cenet_env_override_wins_over_config_checkpoint(self):
        with mock.patch.dict(
            os.environ, {"VEYRA_CENET_CHECKPOINT": "/nonexistent/env-override.bin"}
        ):
            pipeline = PerceptionPipeline.from_config(
                self._config(
                    {
                        "mode": "cenet",
                        "checkpoint": "/nonexistent/config.bin",
                        "allow_fallback_to_ground_truth": True,
                    }
                )
            )

        self.assertIsInstance(pipeline.semantic_provider, GroundTruthSemanticProvider)
        reason = pipeline.semantic_fallback_reason or ""
        self.assertIn("/nonexistent/env-override.bin", reason)
        self.assertNotIn("/nonexistent/config.bin", reason)

    def test_cenet_mode_selects_neural_provider_without_real_inference(self):
        class FakeCENet:
            supported_datasets = frozenset({"semanticposs"})

            def __init__(self, checkpoint_path, *, threads=4, device="cpu"):
                self.checkpoint_path = Path(checkpoint_path)
                self.threads = threads

            def infer(self, points, labels=None):
                del labels
                count = np.asarray(points).shape[0]
                return SemanticResult(
                    np.zeros(count, dtype=np.int32),
                    np.zeros(count, dtype=np.float32),
                    "model",
                )

        with tempfile.TemporaryDirectory() as directory:
            mock_checkpoint = str(Path(directory) / "mock-weights.bin")
            Path(mock_checkpoint).write_bytes(b"mock-cenet-weights")
            with (
                mock.patch.dict(
                    os.environ, {"VEYRA_CENET_CHECKPOINT": mock_checkpoint}
                ),
                mock.patch(
                    "perception.semantic.cenet.CENetSemanticProvider", FakeCENet
                ),
            ):
                pipeline = PerceptionPipeline.from_config(
                    self._config(
                        {
                            "mode": "cenet",
                            "checkpoint": "/mock/config.bin",
                            "threads": 2,
                        }
                    )
                )

        self.assertIsInstance(pipeline.semantic_provider, FakeCENet)
        self.assertIsNone(pipeline.semantic_fallback_reason)
        self.assertEqual(pipeline.semantic_requested_mode, "cenet")
        # The env override reaches the provider constructor, not the config.
        self.assertEqual(
            pipeline.semantic_provider.checkpoint_path,
            Path(mock_checkpoint),
        )
        self.assertEqual(pipeline.semantic_provider.threads, 2)

        output = pipeline.process(replace(_frame(), dataset="semanticposs"))

        self.assertEqual(output.status.semantic, "model")
        self.assertFalse(
            any("fallback" in diagnostic for diagnostic in output.status.diagnostics)
        )

    def test_cenet_mode_rejects_invalid_threads(self):
        with self.assertRaisesRegex(Exception, "threads"):
            PerceptionPipeline.from_config(
                self._config(
                    {"mode": "cenet", "checkpoint": "/mock/x.bin", "threads": 0}
                )
            )

    def test_cenet_mode_rejects_invalid_device(self):
        for device in ("cuda", "gpu", 1, None):
            with self.assertRaisesRegex(Exception, "device"):
                PerceptionPipeline.from_config(
                    self._config(
                        {"mode": "cenet", "checkpoint": "/mock/x.bin", "device": device}
                    )
                )

    def test_cenet_device_fallback_is_visible_and_not_a_ground_truth_fallback(self):
        seen = {}

        class FakeAutoCENet:
            supported_datasets = frozenset({"semanticposs"})

            def __init__(self, checkpoint_path, *, threads=4, device="cpu"):
                seen["device"] = device
                self.checkpoint_path = Path(checkpoint_path)
                self.requested_device = device
                self.device_fallback_reason = None

            @property
            def execution_device(self):
                return "cpu" if self.device_fallback_reason else "mps:0"

            def infer(self, points, labels=None):
                del labels
                count = np.asarray(points).shape[0]
                return SemanticResult(
                    np.zeros(count, dtype=np.int32),
                    np.zeros(count, dtype=np.float32),
                    "model",
                )

        with tempfile.TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            with mock.patch(
                "perception.semantic.cenet.CENetSemanticProvider", FakeAutoCENet
            ):
                pipeline = PerceptionPipeline.from_config(
                    self._config(
                        {"mode": "cenet", "checkpoint": str(weights), "device": "auto"}
                    )
                )
        self.assertEqual(seen["device"], "auto")
        frame = replace(_frame(), dataset="semanticposs")
        accelerated = pipeline.process(frame).status
        self.assertEqual(accelerated.semantic_execution, "mps:0")
        self.assertEqual(accelerated.semantic_device_requested, "auto")
        self.assertIsNone(accelerated.semantic_device_fallback_reason)

        # A mid-run accelerator failure degrades to CPU: visible per frame,
        # the model still runs, and it is never a ground_truth fallback.
        pipeline.semantic_provider.device_fallback_reason = (
            "auto: MPS inference failed (RuntimeError: x); running on cpu"
        )
        degraded = pipeline.process(frame).status
        self.assertEqual(degraded.semantic, "model")
        self.assertEqual(degraded.semantic_execution, "cpu")
        self.assertIsNone(degraded.semantic_fallback_reason)
        self.assertIn("MPS inference failed", degraded.semantic_device_fallback_reason)
        self.assertTrue(
            any("semantic device fallback" in d for d in degraded.diagnostics)
        )

        from runtime.telemetry import Telemetry

        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "n_points": 3,
                "semantic_labels": [0, 0, 0],
                "pipeline_status": {
                    "semantic": degraded.semantic,
                    "ground": degraded.ground,
                    "terrain": degraded.terrain,
                    "temporal": degraded.temporal,
                    "diagnostics": list(degraded.diagnostics),
                    "semantic_execution": degraded.semantic_execution,
                    "semantic_requested": degraded.semantic_requested,
                    "semantic_fallback_reason": degraded.semantic_fallback_reason,
                    "semantic_device_requested": degraded.semantic_device_requested,
                    "semantic_device_fallback_reason": (
                        degraded.semantic_device_fallback_reason
                    ),
                },
            },
            None,
            None,
            {"mode": "cenet", "device": "auto"},
        )
        perception = report["perception"]
        self.assertEqual(perception["execution_provider"], "cpu")
        self.assertEqual(perception["semantic_actual"], "model")
        self.assertIsNone(perception["semantic_fallback_reason"])
        self.assertEqual(perception["semantic_device_requested"], "auto")
        self.assertIn(
            "MPS inference failed", perception["semantic_device_fallback_reason"]
        )

    def test_cenet_device_defaults_to_cpu(self):
        seen = {}

        class FakeCENet:
            supported_datasets = frozenset({"semanticposs"})

            def __init__(self, checkpoint_path, *, threads=4, device="cpu"):
                seen["device"] = device
                self.checkpoint_path = Path(checkpoint_path)

        with tempfile.TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            with mock.patch(
                "perception.semantic.cenet.CENetSemanticProvider", FakeCENet
            ):
                PerceptionPipeline.from_config(
                    self._config({"mode": "cenet", "checkpoint": str(weights)})
                )
        self.assertEqual(seen["device"], "cpu")

    def test_cenet_build_pipeline_keeps_blank_checkpoint_unresolved(self):
        from viewer.runtime import build_pipeline

        for blank in ("", "   "):
            with mock.patch.dict(os.environ):
                os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
                pipeline = build_pipeline(
                    {
                        "semantic": {
                            "mode": "cenet",
                            "checkpoint": blank,
                            "allow_fallback_to_ground_truth": True,
                        },
                        "ground": {"enabled": False},
                        "terrain": {"enabled": False},
                        "temporal": {"enabled": False},
                    },
                    repo_root="/tmp/RT2",
                )
            self.assertIsInstance(
                pipeline.semantic_provider, GroundTruthSemanticProvider
            )
            self.assertIn(
                "no checkpoint configured", pipeline.semantic_fallback_reason or ""
            )


# Perception redteam

"""Adversarial, ownership-safe tests for the Mallik perception boundary.

Synthetic cases below exercise contracts without pretending to be dataset
quality evidence.  The real-data case reads only the primary checkout's
ignored SemanticPOSS fixture when it is present.
"""


PRIMARY_SEMANTIC_POSS = Path(
    "/home/arjun/Captain/SIH/Lidar/data/raw/semanticposs/dataset"
)


def _redteam_frame(**overrides) -> ObservationFrame:
    values = {
        "timestamp": 12.5,
        "pose": PoseSE3.identity(12.5),
        "points": np.array(
            [[10.0, 0.0, 1.0, 0.1], [20.0, 0.0, 2.0, 0.2]], dtype=np.float32
        ),
        "semantic_class": np.array([3, 4], dtype=np.int32),
        "semantic_confidence": np.array([0.25, 0.75], dtype=np.float32),
        "ground": np.array([True, False]),
        "drivable": np.array(["drivable", "unknown"]),
        "slope": np.array([0.1, np.nan], dtype=np.float32),
        "roughness": np.array([0.2, np.nan], dtype=np.float32),
        "height_complexity": np.array([0.3, np.nan], dtype=np.float32),
        "motion_probability": np.array([0.4, 0.0], dtype=np.float32),
        "velocity_xy": np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        "terrain_confidence": np.array([0.8, 0.0], dtype=np.float32),
        "step": np.array([0.5, np.nan], dtype=np.float32),
        "motion_state": np.array(["moving", "unknown"]),
        "observation_quality": np.array([0.9, 0.1], dtype=np.float32),
        "raw_semantic_class": np.array([30, 40], dtype=np.int32),
        "instance_id": np.array([7, 8], dtype=np.int32),
        "dataset": "synthetic-redteam",
        "sequence": "00",
        "frame_id": "000012",
        "provenance": FrameProvenance(
            coordinate_frame="world",
            timestamp_source="dataset",
            pose_source="dataset",
            calibration_source="dataset",
            label_source="dataset",
        ),
    }
    values.update(overrides)
    return ObservationFrame(**values)


class PerceptionRedTeamTests(unittest.TestCase):
    def test_evidence_utility_serializes_a_fixture_without_inventing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            sequence = root / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 2.0, 3.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne/0.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels/0.label")
            output = Path(directory) / "evidence.stream"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/emit_perception_evidence.py",
                    "--dataset-root",
                    str(root),
                    "--sequence",
                    "00",
                    "--frame-id",
                    "0",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["source_kind"], "synthetic_fixture")
        self.assertEqual(report["point_count"], 1)
        self.assertEqual(report["provenance"]["pose_source"], "identity_absent")
        self.assertEqual(report["provenance"]["timestamp_source"], "absent")
        self.assertTrue(report["serialized_path"].endswith("evidence.stream"))

    def test_synthetic_contract_preserves_point_order_and_all_labels(self):
        frame = _redteam_frame()
        records = frame_records(frame)
        point_records = [line.split() for line in records if line.startswith("P ")]

        self.assertEqual([float(row[1]) for row in point_records], [10.0, 20.0])
        self.assertEqual([int(row[5]) for row in point_records], [3, 4])
        self.assertEqual([int(row[19]) for row in point_records], [30, 40])
        self.assertEqual([row[20] for row in point_records], ["NA", "NA"])
        self.assertEqual(
            [row[21:] for row in point_records], [["NA", "NA"], ["NA", "NA"]]
        )
        self.assertEqual([int(row[3]) for row in point_records], [1, 2])
        self.assertEqual([int(row[8]) for row in point_records], [1, 0])
        self.assertEqual(records[-1], "E\n")

    def test_synthetic_binary_bridge_retains_order_and_enriched_evidence(self):
        frame = _redteam_frame()
        payload = binary_frame_bytes(frame)
        self.assertTrue(payload.startswith(b"B 2\n"))
        header_size = struct.calcsize("<QQQ16d")
        point_bytes = payload[4 + header_size :]
        self.assertEqual(len(point_bytes), 2 * 79)
        row_dtype = np.dtype(
            [
                ("xyzi", "<f4", (4,)),
                ("semantic", "<u4"),
                ("confidence", "<f4"),
                ("ground", "u1"),
                ("drivable", "u1"),
                ("slope", "<f4"),
                ("roughness", "<f4"),
                ("complexity", "<f4"),
                ("terrain", "<f4"),
                ("step", "<f4"),
                ("motion", "<f4"),
                ("state", "u1"),
                ("velocity", "<f4", (2,)),
                ("quality", "<f4"),
                ("raw", "<i4"),
                ("height_above_ground", "<f4"),
                ("ground_gradient_x", "<f4"),
                ("ground_gradient_y", "<f4"),
            ]
        )
        rows = np.frombuffer(point_bytes, dtype=row_dtype)
        np.testing.assert_allclose(rows["xyzi"][:, 0], [10.0, 20.0])
        np.testing.assert_array_equal(rows["semantic"], [3, 4])
        np.testing.assert_allclose(rows["confidence"], [0.25, 0.75])
        np.testing.assert_array_equal(rows["raw"], [30, 40])
        np.testing.assert_allclose(rows["quality"], [0.9, 0.1])
        self.assertTrue(np.isnan(rows["ground_gradient_x"]).all())
        self.assertTrue(np.isnan(rows["ground_gradient_y"]).all())

    def test_synthetic_serialized_file_retains_digest_and_nan_sentinels(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "frame.stream"
            digest = stream_file([_redteam_frame()], output)
            serialized = output.read_text()

        self.assertIn(f"H {digest}\n", serialized)
        self.assertIn(f"D {digest}\n", serialized)
        self.assertIn(" NA ", serialized)
        self.assertNotIn("nan", serialized.lower())

    def test_semantic_ids_and_confidences_fail_closed_at_contract_boundary(self):
        for value in (-1, 2**31, 1.5, np.nan, np.inf):
            with (
                self.subTest(field="semantic_class", value=value),
                self.assertRaises(ValueError),
            ):
                _redteam_frame(semantic_class=np.array([value, 1]))
        for value in (-0.01, 1.01, np.nan, np.inf):
            with (
                self.subTest(field="semantic_confidence", value=value),
                self.assertRaises(ValueError),
            ):
                _redteam_frame(semantic_confidence=np.array([value, 0.5]))

    def test_semantic_provider_result_does_not_narrow_fractional_ids(self):
        with self.assertRaises(ValueError):
            SemanticFrame(
                semantic_class=np.array([1.5, 2.0]),
                semantic_confidence=np.array([0.5, 0.5]),
                mode="model",
            )

    def test_unknown_terrain_is_not_collapsed_to_free_when_ground_is_unavailable(self):
        from perception.pipeline import PerceptionPipeline

        class UnavailableGround:
            def segment(self, points):
                del points
                raise RuntimeError("fixture backend unavailable")

        output = PerceptionPipeline(ground_segmenter=UnavailableGround()).process(
            _redteam_frame()
        )
        self.assertEqual(output.status.ground, "unavailable")
        self.assertEqual(output.status.terrain, "unavailable")
        np.testing.assert_array_equal(output.frame.drivable, ["drivable", "unknown"])

    def test_missing_pose_or_time_never_advances_temporal_tracker(self):
        from perception.pipeline import PerceptionPipeline

        class MustNotRun:
            def update(self, *args, **kwargs):
                raise AssertionError("temporal tracker received unproven metadata")

        for provenance, timestamp in (
            (
                FrameProvenance(
                    coordinate_frame="lidar",
                    timestamp_source="dataset",
                    pose_source="identity_absent",
                    calibration_source="identity_absent",
                    label_source="dataset",
                ),
                12.5,
            ),
            (
                FrameProvenance(
                    coordinate_frame="world",
                    timestamp_source="absent",
                    pose_source="dataset",
                    calibration_source="dataset",
                    label_source="dataset",
                ),
                None,
            ),
        ):
            with self.subTest(provenance=provenance):
                output = PerceptionPipeline(temporal_tracker=MustNotRun()).process(
                    _redteam_frame(provenance=provenance, timestamp=timestamp)
                )
                self.assertEqual(output.status.temporal, "unavailable")

    def test_synthetic_scan_label_mismatch_is_rejected_before_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sequences"
            sequence = root / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.zeros((2, 4), dtype=np.float32).tofile(sequence / "velodyne/0.bin")
            np.array([1], dtype=np.uint32).tofile(sequence / "labels/0.label")
            with self.assertRaisesRegex(ValueError, "scan/label length mismatch"):
                RedTeamSemanticPOSSDataset(root.parent).load_frame("00", "0")

    @unittest.skipUnless(
        PRIMARY_SEMANTIC_POSS.is_dir(),
        "primary checkout SemanticPOSS fixture is unavailable",
    )
    def test_real_semanticposs_fixture_preserves_source_contract(self):
        adapter = RedTeamSemanticPOSSDataset(PRIMARY_SEMANTIC_POSS, sequences=["00"])
        reference = adapter.list_frames("00")[0]
        frame = adapter.load_frame("00", reference.frame_id)

        self.assertGreater(frame.points.shape[0], 10_000)
        self.assertEqual(frame.points.shape[0], frame.semantic_class.shape[0])
        self.assertEqual(frame.points.shape[0], frame.raw_semantic_class.shape[0])
        self.assertEqual(frame.provenance.coordinate_frame, "world")
        self.assertEqual(frame.provenance.pose_source, "dataset")
        self.assertEqual(frame.provenance.calibration_source, "dataset")
        self.assertEqual(frame.provenance.label_source, "dataset")
        self.assertTrue(np.isfinite(frame.points).all())
        self.assertTrue(
            ((frame.semantic_confidence >= 0) & (frame.semantic_confidence <= 1)).all()
        )


if __name__ == "__main__":
    unittest.main()
