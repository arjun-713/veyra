import itertools
import os
import time
import unittest
from dataclasses import FrozenInstanceError
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

    def test_global_association_prevents_same_class_cross_assignment_ghost(self):
        tracker = TemporalTracker(
            cluster_tolerance_m=0.2,
            association_distance_m=2.0,
            moving_speed_mps=0.5,
        )
        first = np.asarray(
            [[0.0, 0.0, 0.0, 1.0], [1.0, 0.0, 0.0, 1.0]], dtype=np.float32
        )
        labels = np.ones(2, dtype=np.int32)
        tracker.update(first, labels, np.eye(4), timestamp=0.0)

        # Both objects move +0.9 m. Greedy input-order matching assigns the
        # first detection to the track at 1.0 m (0.1 m away), then forces the
        # second detection onto the track at 0.0 m, producing -0.1 and 1.9 m/s
        # ghost velocities. A one-to-one global assignment must preserve +0.9.
        second = np.asarray(
            [[0.9, 0.0, 0.0, 1.0], [1.9, 0.0, 0.0, 1.0]], dtype=np.float32
        )
        evidence = tracker.update(second, labels, np.eye(4), timestamp=1.0)

        np.testing.assert_allclose(
            np.sort(np.linalg.norm(evidence.velocity_xy, axis=1)), [0.9, 0.9], atol=1e-6
        )
        self.assertTrue(np.all(evidence.state == "moving"))

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

    def test_active_tracks_snapshot_is_deterministic_and_read_only(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, stale_after_frames=2)
        points, labels = scan(2.0)
        tracker.update(points, labels, translation(0.0), timestamp=0.0)

        first = tracker.active_tracks()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].missed_frames, 0)
        self.assertEqual(first[0].persistence, 1)
        self.assertFalse(first[0].motion_valid)
        with self.assertRaises(FrozenInstanceError):
            first[0].persistence = 99  # frozen snapshot, not tracker state

        tracker.update(points, labels, translation(0.0), timestamp=1.0)
        second = tracker.active_tracks()
        self.assertEqual(second[0].track_id, first[0].track_id)
        self.assertEqual(second[0].persistence, 2)
        self.assertTrue(second[0].motion_valid)

        empty = np.empty((0, 4), dtype=np.float32)
        tracker.update(empty, np.empty(0, dtype=np.int32), np.eye(4), timestamp=2.0)
        ghost = tracker.active_tracks()
        self.assertEqual(len(ghost), 1)
        self.assertEqual(ghost[0].missed_frames, 1)
        tracker.update(empty, np.empty(0, dtype=np.int32), np.eye(4), timestamp=3.0)
        self.assertEqual(tracker.active_tracks(), ())

    def test_confirmed_motion_survives_consistent_frames(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, moving_speed_mps=0.5)
        first, labels = scan(10.0)
        tracker.update(first, labels, translation(0.0), timestamp=0.0)
        second, _ = scan(11.0)
        tracker.update(second, labels, translation(0.0), timestamp=1.0)
        third, _ = scan(12.0)
        evidence = tracker.update(third, labels, translation(0.0), timestamp=2.0)

        self.assertTrue(np.all(evidence.state == "moving"))
        snapshots = tracker.active_tracks()
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0].confirmed)

    def test_direction_flip_demotes_to_possibly_moving_never_static(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, moving_speed_mps=0.5)
        first, labels = scan(10.0)
        tracker.update(first, labels, translation(0.0), timestamp=0.0)
        second, _ = scan(11.0)
        tracker.update(second, labels, translation(0.0), timestamp=1.0)
        # Same distance, opposite direction: resampling jitter, not motion.
        third, _ = scan(10.0)
        evidence = tracker.update(third, labels, translation(0.0), timestamp=2.0)

        self.assertTrue(np.all(evidence.state == "possibly_moving"))
        self.assertFalse(tracker.active_tracks()[0].confirmed)

    def test_regime_change_demotes_without_asserting_static(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, moving_speed_mps=0.5)
        first, labels = scan(10.0)
        tracker.update(first, labels, translation(0.0), timestamp=0.0)
        second, _ = scan(11.0)
        tracker.update(second, labels, translation(0.0), timestamp=1.0)
        # Sudden stop after fast motion: uncertain, not confirmed rest.
        third, _ = scan(11.0)
        evidence = tracker.update(third, labels, translation(0.0), timestamp=2.0)

        self.assertTrue(np.all(evidence.state == "possibly_moving"))

    def test_confirmed_rest_recovers_after_consistent_frames(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, moving_speed_mps=0.5)
        points, labels = scan(10.0)
        tracker.update(points, labels, translation(0.0), timestamp=0.0)
        tracker.update(points, labels, translation(0.0), timestamp=1.0)
        evidence = tracker.update(points, labels, translation(0.0), timestamp=2.0)

        self.assertTrue(np.all(evidence.state == "static"))
        self.assertTrue(tracker.active_tracks()[0].confirmed)

    def test_confirmation_parameters_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            TemporalTracker(consistency_cosine=1.5)
        with self.assertRaises(ValueError):
            TemporalTracker(consistency_cosine=np.nan)
        with self.assertRaises(ValueError):
            TemporalTracker(consistency_ratio=0.5)

    def test_excluded_classes_keep_alignment_without_tracks(self) -> None:
        tracker = TemporalTracker(cluster_tolerance_m=0.3, exclude_classes=(7,))
        points = np.array(
            [[10.0, 0.0, 0.0, 1.0], [10.1, 0.0, 0.0, 1.0]], dtype=np.float32
        )
        labels = np.array([7, 7], dtype=np.int32)
        evidence = tracker.update(points, labels, np.eye(4), timestamp=0.0)

        self.assertEqual(tracker.active_track_count, 0)
        self.assertTrue(np.all(evidence.state == "unknown"))
        self.assertEqual(evidence.persistence.tolist(), [1, 1])

        mixed_labels = np.array([7, 1], dtype=np.int32)
        tracker.update(points, mixed_labels, np.eye(4), timestamp=1.0)
        self.assertEqual(tracker.active_track_count, 1)

    def test_excluded_classes_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            TemporalTracker(exclude_classes=(-1,))
        with self.assertRaises(ValueError):
            TemporalTracker(exclude_classes=(2, 2))

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

    def test_skipped_frames_use_timestamp_delta_for_velocity(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.3, moving_speed_mps=0.5)
        first, labels = scan(10.0)
        tracker.update(first, labels, translation(0.0), timestamp=0.0)

        # The frame at t=1 is absent. The displacement is therefore 2 m over
        # 2 s, not 2 m per assumed frame interval.
        second, _ = scan(12.0)
        evidence = tracker.update(second, labels, translation(0.0), timestamp=2.0)

        np.testing.assert_allclose(evidence.velocity_xy[:, 0], 1.0, atol=1e-6)
        self.assertTrue(np.all(evidence.state == "moving"))

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


class KittiSeq08TemporalTests(unittest.TestCase):
    """Real-sequential temporal proof on SemanticKITTI sequence 08.

    Runs only when a dataset-backed checkout is present (env
    ``SEMANTICKITTI_ROOT`` or ``data/raw/semantickitti/dataset`` with
    sequence 08 scans, labels, poses, and times); otherwise skips without
    inventing data. Every frame must carry dataset timestamp/pose/world
    provenance or the test fails closed.
    """

    SEQUENCE = "08"
    # Ground-surface classes consumed by the terrain branch; they report
    # unknown motion by construction instead of asserting false movement.
    EXCLUDE = (9, 10, 11, 12, 17)
    MAX_RANGE_M = 100.0

    def _root(self) -> Path | None:
        override = os.environ.get("SEMANTICKITTI_ROOT")
        candidates = ([Path(override)] if override else []) + [
            Path("data/raw/semantickitti/dataset")
        ]
        for root in candidates:
            if (root / "sequences" / self.SEQUENCE / "times.txt").is_file():
                return root
        return None

    def _frames(self, numbers: list[int]):
        from datasets.semantickitti import SemanticKITTIDataset

        root = self._root()
        if root is None:
            self.skipTest("SemanticKITTI sequence-08 checkout is unavailable")
        dataset = SemanticKITTIDataset(root)
        available = {ref.frame_id for ref in dataset.list_frames(self.SEQUENCE)}
        if any(f"{number:06d}" not in available for number in numbers):
            self.skipTest("required sequence-08 scans are not extracted")
        frames = [
            dataset.load_frame(
                self.SEQUENCE, f"{number:06d}", max_range_m=self.MAX_RANGE_M
            )
            for number in numbers
        ]
        for frame in frames:
            if frame.timestamp is None or not np.isfinite(frame.timestamp):
                self.fail(f"frame {frame.frame_id} lacks a dataset timestamp")
            if frame.provenance.timestamp_source != "dataset":
                self.fail("timestamp provenance is not 'dataset'")
            if frame.provenance.pose_source != "dataset":
                self.fail("pose provenance is not 'dataset'")
            if frame.provenance.coordinate_frame != "world":
                self.fail("frame is not in world coordinates")
        timestamps = [float(frame.timestamp) for frame in frames]
        if any(b <= a for a, b in itertools.pairwise(timestamps)):
            self.fail("dataset timestamps must strictly increase")
        return frames

    def _track(self, frames):
        tracker = TemporalTracker(exclude_classes=self.EXCLUDE)
        evidences = [
            tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
            for frame in frames
        ]
        return tracker, evidences

    def test_world_frame_keeps_pole_landmarks_stable(self) -> None:
        from scipy.spatial import cKDTree

        frames = self._frames([0, 1])
        clouds = []
        for frame in frames:
            mask = np.isin(frame.raw_semantic_class, [80, 81])
            mask &= np.linalg.norm(frame.points[:, :2], axis=1) < 40.0
            self.assertGreater(int(mask.sum()), 500)
            clouds.append(frame.points[mask][:, :3].astype(np.float64))
        distance, _ = cKDTree(clouds[1]).query(clouds[0])
        # Measured 0.038 m on this pair; the 0.15 m bound only guards the
        # ego-compensation contract (inverse convention drifts ~1.5 m).
        self.assertLess(float(np.median(distance)), 0.15)

    def test_moving_vehicle_tracked_with_consistent_velocity(self) -> None:
        frames = self._frames([43, 44, 45, 46, 47])
        _, evidences = self._track(frames)
        # Second observation (frame 44): confirmation applies from the third
        # observation on, so the safety property here is zero false-static on
        # the mover, not full confirmation (measured: 1801 possibly_moving,
        # 0 static of 10865 mover points).
        second = (frames[1].raw_semantic_class == 252) & (evidences[1].state != "unknown")
        self.assertLess(float(np.mean(evidences[1].state[second] == "static")), 0.1)
        medians = []
        for frame, evidence in zip(frames[2:], evidences[2:], strict=True):
            moving = (frame.raw_semantic_class == 252) & (evidence.state != "unknown")
            self.assertGreater(int(moving.sum()), 3000)
            static_share = float(np.mean(evidence.state[moving] == "static"))
            self.assertLess(static_share, 0.25)
            speed = np.linalg.norm(evidence.velocity_xy[moving], axis=1)
            moving_speed = speed[evidence.state[moving] == "moving"]
            self.assertGreater(len(moving_speed), 1000)
            self.assertGreater(float(np.median(moving_speed)), 2.0)
            self.assertLess(float(np.median(moving_speed)), 15.0)
            medians.append(np.median(evidence.velocity_xy[moving], axis=0))
        for first, second in itertools.pairwise(medians):
            cosine = float(
                np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second))
            )
            self.assertGreater(cosine, 0.9)
        # Slow movers (pedestrians, riders) must never be called static:
        # uncertain collapses to possibly_moving, which still excludes them
        # from static-map consumption.
        for frame, evidence in zip(frames[1:], evidences[1:], strict=True):
            for raw in (254, 253):
                mask = (frame.raw_semantic_class == raw) & (evidence.state != "unknown")
                if mask.sum() < 200:
                    continue
                self.assertLess(float(np.mean(evidence.state[mask] == "static")), 0.1)

    def test_parked_objects_do_not_report_confirmed_motion(self) -> None:
        frames = self._frames([43, 44, 45, 46, 47])
        _, evidences = self._track(frames)
        for frame, evidence in zip(frames[2:], evidences[2:], strict=True):
            for raw, bound in ((80, 0.15), (10, 0.5)):
                mask = (frame.raw_semantic_class == raw) & (evidence.state != "unknown")
                if mask.sum() < 200:
                    continue
                moving_share = float(np.mean(evidence.state[mask] == "moving"))
                self.assertLess(moving_share, bound)

    def test_quiet_window_bounds_false_motion(self) -> None:
        # Files 400-404 carry zero moving-label points, so every moving-state
        # point here is false motion. Compact objects (stable support) must
        # stay near-zero; extended surfaces during fast ego motion are the
        # known residual (drive-past support slide confirms), pinned below.
        frames = self._frames([400, 401, 402, 403, 404])
        _, evidences = self._track(frames)
        for frame, evidence in zip(frames[2:], evidences[2:], strict=True):
            for raw in (80, 30):
                mask = (frame.raw_semantic_class == raw) & (evidence.state != "unknown")
                if mask.sum() < 200:
                    continue
                self.assertLess(float(np.mean(evidence.state[mask] == "moving")), 0.05)
            valid = evidence.state != "unknown"
            self.assertGreater(int(valid.sum()), 1000)
            # Residual pin, not a proof: extended surfaces (walls, canopies)
            # confirm false motion via systematic drive-past support slide
            # (measured 0.39-0.49 here). Compact objects above carry the
            # separation proof; this bound only prevents silent regression.
            self.assertLess(float(np.mean(evidence.state[valid] == "moving")), 0.55)

    def test_relocation_expires_tracks_and_bounds_ghosts(self) -> None:
        frames = self._frames([98, 99, 400, 401, 402])
        tracker = TemporalTracker(exclude_classes=self.EXCLUDE)
        for frame in frames[:2]:
            tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
        before = {snapshot.track_id for snapshot in tracker.active_tracks()}
        self.assertGreater(len(before), 0)
        # A 343 m relocation gap exceeds stale_after_frames=3 and moves every
        # static structure far outside the association gate, so no phase-1
        # track may survive; the new scene gets fresh identities.
        for frame in frames[2:]:
            tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
        after = {snapshot.track_id for snapshot in tracker.active_tracks()}
        self.assertEqual(before & after, set())

    def test_same_scene_gap_reassociates_static_without_ghosts(self) -> None:
        frames = self._frames([4040, 4041, 4042, 4047, 4048, 4049])
        tracker = TemporalTracker(exclude_classes=self.EXCLUDE)
        for frame in frames[:3]:
            tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
        for frame in frames[3:]:
            tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
        # Static structure re-observed after a short gap re-associates instead
        # of spawning ghosts: every survivor must be freshly observed.
        for snapshot in tracker.active_tracks():
            self.assertLessEqual(snapshot.missed_frames, 2)

        continuous = self._frames(list(range(4040, 4050)))
        tracker = TemporalTracker(exclude_classes=self.EXCLUDE)
        worst_ghost = 0
        for frame in continuous:
            tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
            for snapshot in tracker.active_tracks():
                worst_ghost = max(worst_ghost, snapshot.missed_frames)
        self.assertLessEqual(worst_ghost, 2)

    def test_skipped_frames_use_dataset_timestamp_delta(self) -> None:
        dense = self._frames([43, 44, 45, 46, 47])
        sparse = self._frames([43, 45, 47])
        gaps = [
            float(second.timestamp) - float(first.timestamp)
            for first, second in itertools.pairwise(sparse)
        ]
        for gap in gaps:
            self.assertGreater(gap, 0.15)
            self.assertLess(gap, 0.3)
        _, dense_evidence = self._track(dense)
        _, sparse_evidence = self._track(sparse)
        dense_peak = max(
            float(np.linalg.norm(evidence.velocity_xy, axis=1).max())
            for evidence in dense_evidence[1:]
        )
        sparse_peak = max(
            float(np.linalg.norm(evidence.velocity_xy, axis=1).max())
            for evidence in sparse_evidence[1:]
        )
        self.assertGreater(dense_peak, 1.0)
        ratio = sparse_peak / dense_peak
        self.assertGreater(ratio, 0.4)
        self.assertLess(ratio, 2.5)
        # True movers must agree quantitatively, not just within the gate:
        # the pass-by car's median speed is dt-invariant across strides.
        dense_mover = []
        for frame, evidence in zip(dense[1:], dense_evidence[1:], strict=True):
            mask = (frame.raw_semantic_class == 252) & (evidence.state == "moving")
            if mask.sum() > 1000:
                dense_mover.append(
                    float(np.median(np.linalg.norm(evidence.velocity_xy[mask], axis=1)))
                )
        sparse_mover = []
        for frame, evidence in zip(sparse[1:], sparse_evidence[1:], strict=True):
            mask = (frame.raw_semantic_class == 252) & (evidence.state == "moving")
            if mask.sum() > 1000:
                sparse_mover.append(
                    float(np.median(np.linalg.norm(evidence.velocity_xy[mask], axis=1)))
                )
        self.assertTrue(len(dense_mover) >= 2)
        self.assertTrue(len(sparse_mover) >= 1)
        mover_ratio = float(np.median(sparse_mover)) / float(np.median(dense_mover))
        self.assertGreater(mover_ratio, 0.7)
        self.assertLess(mover_ratio, 1.4)

    def test_real_frame_updates_stay_within_sanity_budget(self) -> None:
        frames = self._frames([10, 11, 12, 13, 14])
        tracker = TemporalTracker(exclude_classes=self.EXCLUDE)
        worst_ms = 0.0
        for frame in frames:
            start = time.perf_counter()
            evidence = tracker.update(
                frame.points,
                frame.semantic_class,
                frame.pose.matrix,
                timestamp=float(frame.timestamp),
            )
            worst_ms = max(worst_ms, (time.perf_counter() - start) * 1000.0)
            self.assertEqual(evidence.persistence.shape, (len(frame.points),))
        print(f"kitti-temporal seq08 frames=5 worst_ms={worst_ms:.1f}")
        self.assertLess(worst_ms, 90000.0)


class MotionEvaluatorTests(unittest.TestCase):
    """Object-level motion-GT evaluator: synthetic contracts."""

    def _frame(self, xs, *, veyra=1, raw=252, instance=7, timestamp=0.0):
        from types import SimpleNamespace

        count = len(xs)
        return SimpleNamespace(
            points=np.asarray([[x, 0.0, 0.0, 1.0] for x in xs], dtype=np.float32),
            semantic_class=np.full(count, veyra, dtype=np.int32),
            raw_semantic_class=np.full(count, raw, dtype=np.int32),
            instance_id=np.full(count, instance, dtype=np.int32),
            timestamp=timestamp,
            pose=SimpleNamespace(matrix=np.eye(4, dtype=np.float64)),
            dataset="synthetic",
            sequence="s",
            frame_id=f"t{timestamp}",
        )

    def _cluster(self, center, count=6, spacing=0.1):
        return [center + (index - count / 2) * spacing for index in range(count)]

    def test_known_mover_scores_recall_one_and_zero_velocity_error(self):
        from perception.temporal import evaluate_motion

        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        frames = [
            self._frame(self._cluster(10.0 + index * 1.0), timestamp=float(index))
            for index in range(4)
        ]

        report = evaluate_motion(frames, tracker, min_object_points=3)

        self.assertEqual(report["status"], "SCORED")
        car = report["per_class"]["1"]
        self.assertEqual(car["association_recall"], 1.0)
        self.assertEqual(car["velocity_error_mps"]["n"], 3)
        self.assertAlmostEqual(car["velocity_error_mps"]["median"], 0.0, places=6)
        self.assertEqual(car["point_precision"], 1.0)
        # First frame has no velocity by construction (unknown, not wrong).
        self.assertLess(report["point_level"]["moving_state_recall"], 1.0)
        self.assertGreater(report["point_level"]["moving_state_recall"], 0.5)

    def test_stationary_mover_label_reports_no_motion(self):
        from perception.temporal import evaluate_motion

        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        frames = [
            self._frame(self._cluster(10.0), timestamp=float(index))
            for index in range(3)
        ]

        report = evaluate_motion(frames, tracker, min_object_points=3)

        self.assertEqual(report["status"], "SCORED")
        self.assertEqual(report["point_level"]["moving_state_recall"], 0.0)
        self.assertEqual(report["per_class"]["1"]["velocity_error_mps"]["median"], 0.0)

    def test_gate_saturation_is_excluded_not_scored(self):
        from perception.temporal import evaluate_motion

        # 5 m jumps at dt=0.1 s imply 50 m/s: far beyond the 2 m gate, so
        # every frame spawns a fresh track and the GT displacement measures
        # fragmentation, not velocity. It must be excluded, never scored.
        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        frames = [
            self._frame(self._cluster(10.0 + index * 5.0), timestamp=index * 0.1)
            for index in range(3)
        ]

        report = evaluate_motion(frames, tracker, min_object_points=3)

        self.assertEqual(report["status"], "SCORED")
        self.assertIsNone(report["per_class"]["1"]["velocity_error_mps"])
        self.assertGreater(report["gt_unreliable_excluded"], 0)

    def test_missing_timestamps_and_world_frame_yield_unknown(self):
        from types import SimpleNamespace

        from perception.temporal import evaluate_motion

        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        no_time = self._frame(self._cluster(10.0), timestamp=0.0)
        no_time = SimpleNamespace(**{**vars(no_time), "timestamp": None})
        report = evaluate_motion([no_time, no_time], tracker, min_object_points=3)
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertIn("timestamp", report["reason"])
        self.assertIsNone(report["velocity_error_mps"])

        from datasets.common.observation import FrameProvenance

        lidar_frame = self._frame(self._cluster(10.0), timestamp=0.0)
        lidar_frame = SimpleNamespace(
            **{
                **vars(lidar_frame),
                "provenance": FrameProvenance(
                    coordinate_frame="lidar",
                    timestamp_source="absent",
                    pose_source="identity_absent",
                    calibration_source="identity_absent",
                    label_source="dataset",
                ),
            }
        )
        report = evaluate_motion(
            [lidar_frame, lidar_frame], tracker, min_object_points=3
        )
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertIn("world", report["reason"])

    def test_unknown_report_requires_a_reason(self):
        from perception.temporal import unknown_report

        report = unknown_report("semanticposs", "00", reason="no timestamps published")
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertIsNone(report["association_recall"])
        with self.assertRaises(ValueError):
            unknown_report("semanticposs", "00", reason="  ")

    def test_snapshot_centroid_is_exposed_for_gating(self):
        tracker = TemporalTracker(cluster_tolerance_m=0.5)
        points = np.asarray(
            [[x, 0.0, 0.0, 1.0] for x in self._cluster(10.0)], dtype=np.float32
        )
        tracker.update(
            points, np.ones(len(points), dtype=np.int32), np.eye(4), timestamp=0.0
        )

        (snapshot,) = tracker.active_tracks()

        self.assertAlmostEqual(snapshot.centroid_xy[0], 9.95, places=5)
        self.assertAlmostEqual(snapshot.centroid_xy[1], 0.0, places=5)


class KittiSeq08MotionEvaluatorTests(unittest.TestCase):
    """Tiny real slices: the evaluator must reproduce the known seq08 truth.

    Traffic window 43-47 holds the pass-by car (raw 252, instance 4,
    5.6-7.6 m/s); the 400-402 control window holds zero moving labels.
    Skips honestly when the checkout is absent.
    """

    SEQUENCE = "08"
    EXCLUDE = (9, 10, 11, 12, 17)

    def _root(self):
        override = os.environ.get("SEMANTICKITTI_ROOT")
        candidates = ([Path(override)] if override else []) + [
            Path("data/raw/semantickitti/dataset")
        ]
        for root in candidates:
            if (root / "sequences" / self.SEQUENCE / "times.txt").is_file():
                return root
        return None

    def _evaluate(self, numbers):
        from datasets.semantickitti import SemanticKITTIDataset
        from perception.temporal import evaluate_motion

        root = self._root()
        if root is None:
            self.skipTest("SemanticKITTI sequence-08 checkout is unavailable")
        dataset = SemanticKITTIDataset(root)
        available = {ref.frame_id for ref in dataset.list_frames(self.SEQUENCE)}
        if any(f"{number:06d}" not in available for number in numbers):
            self.skipTest("required sequence-08 scans are not extracted")
        tracker = TemporalTracker(exclude_classes=self.EXCLUDE)
        frames = [
            dataset.load_frame(self.SEQUENCE, f"{number:06d}", max_range_m=100.0)
            for number in numbers
        ]
        return evaluate_motion(frames, tracker, min_object_points=200)

    def test_traffic_window_measures_the_pass_by_car(self):
        # Ten-frame window: velocity tails need samples (nearest-rank p95 on
        # the old 5-frame n=7 was max-dominated). Measured on 2026-09-22:
        # association_recall 1.0, velocity median ~0 / p95 1.56 (n=15),
        # raw252 recall 0.541, static control 0.0497.
        report = self._evaluate([43, 44, 45, 46, 47, 48, 49, 50, 51, 52])

        self.assertEqual(report["status"], "SCORED")
        car = report["per_class"]["1"]
        # Every scored car object holds a track identity across the window.
        self.assertEqual(car["association_recall"], 1.0)
        velocity = car["velocity_error_mps"]
        self.assertIsNotNone(velocity)
        self.assertGreaterEqual(velocity["n"], 4)
        # Ego-compensated GT displacement agrees with tracker velocity to
        # well inside the 2 m association gate per 0.104 s step.
        self.assertLess(velocity["median"], 0.5)
        self.assertLess(velocity["p95"], 2.0)
        raw252 = report["point_level"]["per_raw_recall"]["252"]
        self.assertGreater(raw252["recall"], 0.5)
        # Slow movers must surface as non-static even when unconfirmed.
        raw254 = report["point_level"]["per_raw_recall"]["254"]
        self.assertGreater(raw254["non_static_recall"], 0.5)
        # Parked controls stay quiet.
        self.assertLess(report["static_controls"]["10"]["moving_share"], 0.05)

    def test_quiet_window_has_no_moving_gt_and_quiet_controls(self):
        report = self._evaluate([400, 401, 402])

        self.assertEqual(report["status"], "SCORED")
        self.assertEqual(report["point_level"]["gt_moving_points"], 0)
        # No GT moving object exists, so no class carries object-level
        # scores; precision-only buckets (false motion on static classes)
        # may still be present and are the residual signal itself.
        self.assertTrue(
            all(bucket["gt_objects"] == 0 for bucket in report["per_class"].values())
        )
        self.assertLess(report["static_controls"]["10"]["moving_share"], 0.05)


if __name__ == "__main__":
    unittest.main()
