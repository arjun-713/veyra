import importlib.util
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np

from datasets.common.observation import FrameProvenance, ObservationFrame, PoseSE3
from datasets.rellis import Rellis3DDataset
from datasets.semanticposs import SemanticPOSSDataset
from perception.ground import GroundEvidence, PatchworkPPUnavailableError
from perception.pipeline import PerceptionPipeline, load_perception_pipeline
from perception.semantic import GroundTruthSemanticProvider, SemanticResult
from perception.temporal import MotionEvidence
from perception.terrain import TerrainEvidence


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
        np.testing.assert_allclose(output.frame.observation_quality, [0.9, 0.7, 0.0])

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
                    {"mode": "cenet", "checkpoint": "/nonexistent/cenet-weights.bin"}
                )
            )

        self.assertIsInstance(
            pipeline.semantic_provider, GroundTruthSemanticProvider
        )
        self.assertEqual(pipeline.semantic_requested_mode, "cenet")
        self.assertIsNotNone(pipeline.semantic_fallback_reason)
        self.assertIn(
            "/nonexistent/cenet-weights.bin", pipeline.semantic_fallback_reason
        )

        output = pipeline.process(_frame())

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
                    {"mode": "cenet", "checkpoint": "/nonexistent/config.bin"}
                )
            )

        self.assertIsInstance(
            pipeline.semantic_provider, GroundTruthSemanticProvider
        )
        reason = pipeline.semantic_fallback_reason or ""
        self.assertIn("/nonexistent/env-override.bin", reason)
        self.assertNotIn("/nonexistent/config.bin", reason)

    def test_cenet_mode_selects_neural_provider_without_real_inference(self):
        class FakeCENet:
            supported_datasets = frozenset({"semanticposs"})

            def __init__(self, checkpoint_path, *, threads=4):
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
            with mock.patch.dict(
                os.environ, {"VEYRA_CENET_CHECKPOINT": mock_checkpoint}
            ), mock.patch(
                "perception.semantic.cenet.CENetSemanticProvider", FakeCENet
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


if __name__ == "__main__":
    unittest.main()
