import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from datasets.common.observation import ObservationFrame, PoseSE3
from datasets.rellis import Rellis3DDataset
from datasets.semanticposs import SemanticPOSSDataset
from perception.ground import GroundEvidence, PatchworkPPUnavailableError
from perception.pipeline import PerceptionPipeline, load_perception_pipeline
from perception.semantic import SemanticResult
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
        dataset="synthetic-test",
        sequence="00",
        frame_id="000000",
    )


class PerceptionPipelineTests(unittest.TestCase):
    def test_checked_in_default_config_replays_original_semanticposs_and_rellis_frames(
        self,
    ):
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
                all(output.status.ground == "disabled" for output in outputs)
            )
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
        ).process(_frame())

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


if __name__ == "__main__":
    unittest.main()
