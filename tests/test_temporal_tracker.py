import time
import unittest
from pathlib import Path

import numpy as np

from datasets.semanticposs import SemanticPOSSDataset
from perception.temporal.tracker import MotionEvidence, TemporalTracker


def translation(x: float, y: float = 0.0) -> np.ndarray:
    pose = np.eye(4, dtype=np.float64)
    pose[:2, 3] = [x, y]
    return pose


def scan(x: float, semantic_class: int = 1) -> tuple[np.ndarray, np.ndarray]:
    points = np.array([[x, 0.0, 0.0, 0.5], [x + 0.1, 0.0, 0.0, 0.6]], dtype=np.float32)
    labels = np.full(2, semantic_class, dtype=np.int32)
    return points, labels


class TemporalTrackerTests(unittest.TestCase):
    def test_connected_points_across_grid_boundary_form_one_track(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.5, association_distance_m=2.0)
        points = np.array(
            [[-0.1, 0.0, 0.0, 1.0], [0.1, 0.0, 0.0, 1.0]], dtype=np.float32
        )
        labels = np.array([1, 1], dtype=np.int32)

        tracker.update(points, labels, np.eye(4), timestamp=0.0)

        self.assertEqual(tracker.active_track_count, 1)

    def test_original_semanticposs_frame_has_recorded_temporal_cluster_cost(self):
        root = Path("data/raw/semanticposs/dataset")
        if not root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")
        frames = list(SemanticPOSSDataset(root).replay("00", end=3, max_range_m=100.0))
        elapsed_s = []
        cluster_counts = []
        tracker = TemporalTracker()
        for frame in frames:
            start = time.perf_counter()
            clusters = tracker._clusters(frame.points[:, :3], frame.semantic_class)
            elapsed_s.append(time.perf_counter() - start)
            cluster_counts.append(len(clusters))
            self.assertGreater(len(clusters), 0)
        milliseconds = np.asarray(elapsed_s) * 1000.0
        print(
            "temporal-cluster semanticposs/00 frames=3 "
            f"points={[len(frame.points) for frame in frames]} clusters={cluster_counts} "
            f"p50_ms={np.percentile(milliseconds, 50):.3f} "
            f"p95_ms={np.percentile(milliseconds, 95):.3f} "
            f"p99_ms={np.percentile(milliseconds, 99):.3f}"
        )
        self.assertLess(float(np.max(elapsed_s)), 10.0)

    def test_rejects_out_of_order_timestamps_and_can_reset(self):
        tracker = TemporalTracker()
        points = np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
        labels = np.array([1], dtype=np.int32)
        tracker.update(points, labels, np.eye(4), timestamp=2.0)
        with self.assertRaises(ValueError):
            tracker.update(points, labels, np.eye(4), timestamp=1.0)
        tracker.reset()
        self.assertEqual(tracker.active_track_count, 0)

    def test_ordering_survives_track_expiry(self):
        tracker = TemporalTracker(stale_after_frames=1)
        points = np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
        labels = np.array([1], dtype=np.int32)
        tracker.update(points, labels, np.eye(4), timestamp=2.0)
        tracker.update(
            np.empty((0, 4), dtype=np.float32), np.empty(0), np.eye(4), timestamp=3.0
        )
        with self.assertRaises(ValueError):
            tracker.update(points, labels, np.eye(4), timestamp=1.0)

    def test_empty_and_nan_frames_have_explicit_behavior(self):
        tracker = TemporalTracker()
        empty = tracker.update(
            np.empty((0, 4), dtype=np.float32),
            np.empty(0, dtype=np.int32),
            np.eye(4),
            timestamp=0.0,
        )
        self.assertEqual(empty.state.shape, (0,))
        points, labels = scan(0.0)
        points[0, 0] = np.nan
        with self.assertRaises(ValueError):
            tracker.update(points, labels, np.eye(4), timestamp=1.0)

    def test_ego_translation_keeps_stationary_world_geometry_static(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3)
        first, labels = scan(10.0)
        tracker.update(first, labels, translation(0.0), timestamp=0.0)

        second, _ = scan(10.0)
        evidence = tracker.update(second, labels, translation(1.0), timestamp=1.0)

        np.testing.assert_allclose(evidence.velocity_xy, 0.0)
        np.testing.assert_allclose(evidence.motion_probability, 0.0)
        self.assertTrue(np.all(evidence.state == "static"))

    def test_world_object_translation_is_associated_and_reported_as_motion(
        self,
    ) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, moving_speed_mps=0.5)
        first, labels = scan(10.0)
        tracker.update(first, labels, translation(0.0), timestamp=0.0)

        second, _ = scan(11.0)
        evidence = tracker.update(second, labels, translation(0.0), timestamp=1.0)

        self.assertTrue(np.all(evidence.state == "moving"))
        np.testing.assert_allclose(evidence.velocity_xy[:, 0], 1.0, atol=1e-6)
        self.assertTrue(np.all(evidence.motion_probability > 0.5))

    def test_semantic_vehicle_label_does_not_imply_motion(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, moving_speed_mps=0.5)
        points, labels = scan(4.0, semantic_class=10)
        tracker.update(points, labels, translation(0.0), timestamp=0.0)

        evidence = tracker.update(points, labels, translation(0.0), timestamp=1.0)

        self.assertTrue(np.all(evidence.state == "static"))
        np.testing.assert_allclose(evidence.motion_probability, 0.0)

    def test_outputs_are_aligned_and_persistence_increases_then_stale_tracks_decay(
        self,
    ) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, stale_after_frames=2)
        points, labels = scan(2.0)
        first = tracker.update(points, labels, translation(0.0), timestamp=0.0)
        second = tracker.update(points, labels, translation(0.0), timestamp=1.0)

        self.assertIsInstance(first, MotionEvidence)
        self.assertEqual(first.persistence.shape, (2,))
        self.assertEqual(second.persistence.tolist(), [2, 2])
        self.assertEqual(second.velocity_xy.shape, (2, 2))

        empty = np.empty((0, 4), dtype=np.float32)
        empty_labels = np.empty((0,), dtype=np.int32)
        tracker.update(empty, empty_labels, translation(0.0), timestamp=2.0)
        tracker.update(empty, empty_labels, translation(0.0), timestamp=3.0)
        self.assertEqual(tracker.active_track_count, 0)


if __name__ == "__main__":
    unittest.main()
