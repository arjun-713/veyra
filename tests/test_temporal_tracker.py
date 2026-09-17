import time
import unittest
from pathlib import Path
from unittest.mock import patch

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
    def test_radius_components_empty_input_returns_no_components(self):
        self.assertEqual(TemporalTracker._radius_components(np.empty((0, 2)), 0.5), [])

    def test_qhull_coplanar_omission_uses_exact_fallback(self):
        class FakeTriangulation:
            simplices = np.array([[0, 1, 2]], dtype=np.intp)
            coplanar = np.array([[3, 0, 0]], dtype=np.intp)

        points = np.array(
            [[0.0, 0.0], [0.4, 0.0], [0.0, 0.4], [0.4, 0.4]], dtype=np.float64
        )
        with patch("scipy.spatial.Delaunay", return_value=FakeTriangulation()):
            components = TemporalTracker._radius_components(points, 0.5)

        self.assertEqual(len(components), 1)
        np.testing.assert_array_equal(components[0], np.arange(4))

    def test_first_four_representatives_cannot_hide_a_cross_cell_bridge(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        left = [[x, 0.0, 0.0, 1.0] for x in (0.0, 0.05, 0.1, 0.15, 0.34)]
        right = [[x, 0.0, 0.0, 1.0] for x in (0.8, 0.81, 0.82, 0.83)]
        points = np.asarray(left + right, dtype=np.float32)
        labels = np.ones(len(points), dtype=np.int32)

        tracker.update(points, labels, np.eye(4), timestamp=0.0)

        self.assertEqual(tracker.active_track_count, 1)

    def test_radius_connectivity_handles_single_threshold_and_duplicates(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.5)

        for values, expected in (
            ([[0.0, 0.0], [0.5, 0.0]], 1),
            ([[0.0, 0.0], [0.50001, 0.0]], 2),
            ([[0.0, 0.0]], 1),
            ([[0.0, 0.0], [0.0, 0.0], [1.0, 0.0]], 2),
        ):
            points = np.asarray([[x, y, 0.0, 1.0] for x, y in values], dtype=np.float32)
            labels = np.ones(len(points), dtype=np.int32)
            tracker.reset()
            tracker.update(points, labels, np.eye(4), timestamp=0.0)
            self.assertEqual(tracker.active_track_count, expected)

    def test_large_radius_components_use_compiled_spatial_connectivity(self):
        """Dense scans must not build a global Delaunay graph per class."""
        points = np.asarray(
            [
                [x, y, 0.0, 1.0]
                for x in np.linspace(-2.0, 2.0, 25)
                for y in np.linspace(-2.0, 2.0, 25)
            ],
            dtype=np.float32,
        )
        labels = np.ones(len(points), dtype=np.int32)
        tracker = TemporalTracker(cluster_tolerance_m=0.5)

        with patch(
            "scipy.spatial.Delaunay",
            side_effect=AssertionError("large scans must use compiled connectivity"),
        ):
            components = tracker._clusters(points[:, :3].astype(np.float64), labels)

        self.assertEqual(len(components), 1)
        self.assertEqual(len(components[0]), len(points))

    def test_large_radius_components_build_csr_without_coo_conversion(self):
        """The dense path must avoid an avoidable COO-to-CSR conversion."""
        points = np.asarray(
            [
                [x, y, 0.0, 1.0]
                for x in np.linspace(-2.0, 2.0, 25)
                for y in np.linspace(-2.0, 2.0, 25)
            ],
            dtype=np.float32,
        )
        labels = np.ones(len(points), dtype=np.int32)
        tracker = TemporalTracker(cluster_tolerance_m=0.5)

        with patch(
            "scipy.sparse.coo_matrix",
            side_effect=AssertionError(
                "dense connectivity must construct CSR directly"
            ),
        ):
            components = tracker._clusters(points[:, :3].astype(np.float64), labels)

        self.assertEqual(len(components), 1)
        self.assertEqual(len(components[0]), len(points))

    def test_large_radius_components_match_bruteforce_connectivity(self):
        """The compiled fast path must preserve exact radius semantics."""
        rng = np.random.default_rng(17)
        points = rng.uniform(-3.0, 3.0, size=(520, 2))
        tolerance = 0.5
        parent = np.arange(len(points), dtype=np.intp)

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for left in range(len(points)):
            for right in range(left + 1, len(points)):
                if np.linalg.norm(points[left] - points[right]) <= tolerance:
                    left_root, right_root = find(left), find(right)
                    if left_root != right_root:
                        parent[max(left_root, right_root)] = min(left_root, right_root)
        expected = {}
        for index in range(len(points)):
            expected.setdefault(find(index), []).append(index)

        actual = TemporalTracker._radius_components(points, tolerance)
        self.assertEqual(
            {tuple(sorted(component.tolist())) for component in actual},
            {tuple(sorted(members)) for members in expected.values()},
        )

    def test_collinear_and_near_collinear_components_are_deterministic(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.41)
        points = np.asarray(
            [
                [0.8, -1e-10, 0.0, 1.0],
                [0.0, 0.0, 0.0, 1.0],
                [0.4, 1e-10, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        labels = np.ones(3, dtype=np.int32)

        first = tracker._clusters(points[:, :3].astype(np.float64), labels)
        permutation = np.array([2, 0, 1])
        permuted_points = points[permutation]
        second = tracker._clusters(
            permuted_points[:, :3].astype(np.float64), labels[permutation]
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        first_membership = {
            tuple(sorted(map(tuple, points[component, :2]))) for component in first
        }
        second_membership = {
            tuple(sorted(map(tuple, permuted_points[component, :2])))
            for component in second
        }
        self.assertEqual(first_membership, second_membership)

        near_collinear = np.array(
            [[0.0, 0.0], [0.5, 1e-13], [1.0, 0.0]], dtype=np.float64
        )
        self.assertFalse(TemporalTracker._is_collinear(near_collinear))

        collinear = np.asarray(
            [[0.0, 0.0, 0.0, 1.0], [0.4, 0.0, 0.0, 1.0], [0.8, 0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
        self.assertEqual(
            len(tracker._clusters(collinear[:, :3].astype(np.float64), labels)), 1
        )

    def test_first_observation_has_unknown_motion_evidence(self):
        tracker = TemporalTracker()
        points, labels = scan(2.0)

        evidence = tracker.update(points, labels, np.eye(4), timestamp=0.0)

        self.assertTrue(np.all(evidence.state == "unknown"))
        np.testing.assert_allclose(evidence.motion_probability, 0.0)
        np.testing.assert_allclose(evidence.velocity_xy, 0.0)

    def test_same_timestamp_does_not_invent_velocity_or_static_motion(self):
        tracker = TemporalTracker(moving_speed_mps=0.5)
        first, labels = scan(2.0)
        tracker.update(first, labels, np.eye(4), timestamp=1.0)

        second, _ = scan(2.8)
        evidence = tracker.update(second, labels, np.eye(4), timestamp=1.0)

        np.testing.assert_allclose(evidence.velocity_xy, 0.0)
        np.testing.assert_allclose(evidence.motion_probability, 0.0)
        self.assertTrue(np.all(evidence.state == "unknown"))

    def test_cross_cell_connectivity_checks_all_points_not_only_representatives(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        points = np.array(
            [
                [0.0, 0.0, 0.0, 1.0],
                [0.34, 0.0, 0.0, 1.0],
                [0.51, 0.0, 0.0, 1.0],
                [0.85, 0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        labels = np.ones(4, dtype=np.int32)

        tracker.update(points, labels, np.eye(4), timestamp=0.0)

        self.assertEqual(tracker.active_track_count, 1)

    def test_rejects_non_rigid_pose(self):
        tracker = TemporalTracker()
        pose = np.eye(4)
        pose[0, 1] = 0.2
        points, labels = scan(0.0)

        with self.assertRaises(ValueError):
            tracker.update(points, labels, pose, timestamp=0.0)

    def test_rejects_nan_configuration_and_evidence(self):
        config = {
            "cluster_tolerance_m": np.nan,
            "association_distance_m": np.nan,
            "static_speed_mps": np.nan,
            "moving_speed_mps": np.nan,
        }
        for name, value in config.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                TemporalTracker(**{name: value})

        with self.assertRaises(ValueError):
            MotionEvidence(
                np.array([np.nan]),
                np.zeros((1, 2)),
                np.array(["unknown"]),
                np.array([1]),
            )

    def test_connected_points_across_grid_boundary_form_one_track(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.5, association_distance_m=2.0)
        points = np.array(
            [[-0.1, 0.0, 0.0, 1.0], [0.1, 0.0, 0.0, 1.0]], dtype=np.float32
        )
        labels = np.array([1, 1], dtype=np.int32)

        tracker.update(points, labels, np.eye(4), timestamp=0.0)

        self.assertEqual(tracker.active_track_count, 1)

    def test_points_across_grid_seam_need_exact_radius_connectivity(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        points = np.array(
            [[0.0, 0.0, 0.0, 1.0], [0.5001, 0.0, 0.0, 1.0]], dtype=np.float32
        )
        labels = np.array([1, 1], dtype=np.int32)

        tracker.update(points, labels, np.eye(4), timestamp=0.0)

        self.assertEqual(tracker.active_track_count, 2)

    def test_different_labels_and_input_permutations_remain_separate_and_aligned(self):
        points = np.array(
            [[0.0, 0.0, 0.0, 1.0], [0.1, 0.0, 0.0, 1.0], [0.2, 0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
        labels = np.array([2, 1, 2], dtype=np.int32)
        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        first = tracker.update(points, labels, np.eye(4), timestamp=0.0)
        self.assertEqual(tracker.active_track_count, 2)

        tracker.reset()
        order = np.array([2, 0, 1])
        permuted = tracker.update(
            points[order], labels[order], np.eye(4), timestamp=0.0
        )
        np.testing.assert_array_equal(permuted.state, first.state[order])
        np.testing.assert_array_equal(permuted.persistence, first.persistence[order])

    def test_original_semanticposs_frame_stays_within_temporal_update_budget(self):
        root = Path("data/raw/semanticposs/dataset")
        if not root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")
        frames = list(SemanticPOSSDataset(root).replay("00", end=3, max_range_m=100.0))
        if any(
            frame.timestamp is None or frame.provenance.pose_source != "dataset"
            for frame in frames
        ):
            self.skipTest(
                "SemanticPOSS frames lack dataset timestamps or poses; "
                "full temporal timing cannot invent them"
            )
        elapsed_s = []
        cluster_counts = []
        tracker = TemporalTracker()
        for frame in frames:
            start = time.perf_counter()
            evidence = tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
            elapsed_s.append(time.perf_counter() - start)
            cluster_counts.append(tracker.active_track_count)
            self.assertEqual(evidence.persistence.shape, (len(frame.points),))
        milliseconds = np.asarray(elapsed_s) * 1000.0
        print(
            "temporal-cluster semanticposs/00 frames=3 "
            f"points={[len(frame.points) for frame in frames]} clusters={cluster_counts} "
            f"p50_ms={np.percentile(milliseconds, 50):.3f} "
            f"p95_ms={np.percentile(milliseconds, 95):.3f} "
            f"p99_ms={np.percentile(milliseconds, 99):.3f}"
        )
        # This is intentionally a generous CPU budget for the original
        # SemanticPOSS frame size, while still catching dense pair scans.
        self.assertLess(float(np.percentile(milliseconds, 95)), 4000.0)

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
