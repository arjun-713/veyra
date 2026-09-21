import unittest

import numpy as np

from datasets.common.observation import (
    FrameProvenance,
    ObservationFrame,
    PoseSE3,
)


class ObservationContractTests(unittest.TestCase):
    def test_probabilities_reject_nan_and_geometry_rejects_infinity(self):
        for name in ("semantic_confidence", "motion_probability"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _frame(**{name: [np.nan, 0.5]})
        for name in ("slope", "roughness", "height_complexity", "step"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _frame(**{name: [np.inf, 0.0]})
        # NaN remains the documented representation for uncomputed geometry.
        self.assertTrue(np.isnan(_frame(slope=[np.nan, np.nan]).slope).all())

    def test_semantic_classes_must_not_silently_truncate(self):
        with self.assertRaises(ValueError):
            _frame(semantic_class=[1.5, 2])
        with self.assertRaises(ValueError):
            _frame(raw_semantic_class=[1.5, 2])

    def test_observation_frame_keeps_all_point_fields_aligned(self):
        pose = PoseSE3(np.eye(4), timestamp=1.25)
        points = np.array(
            [[1.0, 2.0, 3.0, 0.5], [4.0, 5.0, 6.0, 0.75]], dtype=np.float32
        )

        frame = ObservationFrame(
            timestamp=1.25,
            pose=pose,
            points=points,
            semantic_class=np.array([3, 4], dtype=np.int32),
            semantic_confidence=np.array([1.0, 0.8], dtype=np.float32),
            ground=np.array([True, False]),
            drivable=np.array(["drivable", "unknown"]),
            slope=np.array([0.1, 0.2], dtype=np.float32),
            roughness=np.array([0.01, 0.04], dtype=np.float32),
            height_complexity=np.array([0.0, 0.5], dtype=np.float32),
            motion_probability=np.array([0.0, 0.25], dtype=np.float32),
            velocity_xy=np.array([[0.0, 0.0], [1.0, 2.0]], dtype=np.float32),
        )

        self.assertEqual(frame.points.shape, (2, 4))
        self.assertEqual(frame.semantic_class.shape, (2,))
        self.assertEqual(frame.velocity_xy.shape, (2, 2))
        np.testing.assert_array_equal(frame.semantic_class, [3, 4])

    def test_pose_rejects_non_homogeneous_matrix(self):
        with self.assertRaises(ValueError):
            PoseSE3(np.eye(3))

    def test_observation_rejects_invalid_states_and_freezes_arrays(self):
        with self.assertRaises(ValueError):
            _frame(drivable=["maybe", "unknown"])
        with self.assertRaises(ValueError):
            _frame(motion_state=["static", "flying"])

        frame = _frame()
        with self.assertRaises(ValueError):
            frame.points[0, 0] = 99.0

    def test_observation_preserves_raw_labels_separately_from_mapped_labels(self):
        frame = _frame(
            raw_semantic_class=np.array([42, 7], dtype=np.int32),
            semantic_class=np.array([3, 1], dtype=np.int32),
        )

        np.testing.assert_array_equal(frame.raw_semantic_class, [42, 7])
        np.testing.assert_array_equal(frame.semantic_class, [3, 1])
        with self.assertRaises(ValueError):
            frame.raw_semantic_class[0] = 99

    def test_observation_preserves_optional_instance_ids_without_aliasing_semantics(
        self,
    ):
        frame = _frame(
            raw_semantic_class=np.array([42, 7], dtype=np.int32),
            semantic_class=np.array([3, 1], dtype=np.int32),
            instance_id=np.array([12, 0], dtype=np.int32),
        )

        np.testing.assert_array_equal(frame.instance_id, [12, 0])
        np.testing.assert_array_equal(frame.raw_semantic_class, [42, 7])
        with self.assertRaises(ValueError):
            frame.instance_id[0] = 99

    def test_pose_and_timestamp_require_finite_values(self):
        with self.assertRaises(ValueError):
            PoseSE3.identity(timestamp=float("nan"))
        with self.assertRaises(ValueError):
            _frame(timestamp=float("inf"))

    def test_observation_rejects_nan_point_coordinates(self):
        points = np.zeros((2, 4), dtype=np.float32)
        points[1, 2] = np.nan

        with self.assertRaises(ValueError):
            _frame(points=points)

    def test_pose_rejects_a_non_rigid_rotation(self):
        scaled = np.eye(4)
        scaled[0, 0] = 2.0

        with self.assertRaises(ValueError):
            PoseSE3(scaled)

    def test_metadata_provenance_makes_missing_sources_explicit(self):
        frame = _frame(
            timestamp=None,
            provenance=FrameProvenance(
                coordinate_frame="lidar",
                timestamp_source="absent",
                pose_source="identity_absent",
                calibration_source="identity_absent",
            ),
        )

        self.assertEqual(frame.provenance.coordinate_frame, "lidar")
        self.assertEqual(frame.provenance.timestamp_source, "absent")

    def test_height_complexity_rejects_unbounded_map_evidence(self):
        with self.assertRaises(ValueError):
            ObservationFrame(
                timestamp=1.0,
                pose=PoseSE3.identity(timestamp=1.0),
                points=np.zeros((1, 4), dtype=np.float32),
                semantic_class=np.array([1]),
                semantic_confidence=np.array([1.0]),
                ground=np.array([True]),
                drivable=np.array(["drivable"]),
                slope=np.array([0.0]),
                roughness=np.array([0.0]),
                height_complexity=np.array([1.01]),
                motion_probability=np.array([0.0]),
                velocity_xy=np.zeros((1, 2)),
            )


def _frame(**overrides):
    values = {
        "timestamp": 1.0,
        "pose": PoseSE3.identity(timestamp=1.0),
        "points": np.zeros((2, 4), dtype=np.float32),
        "semantic_class": np.zeros(2, dtype=np.int32),
        "semantic_confidence": np.ones(2, dtype=np.float32),
        "ground": np.zeros(2, dtype=bool),
        "drivable": np.full(2, "unknown"),
        "slope": np.zeros(2, dtype=np.float32),
        "roughness": np.zeros(2, dtype=np.float32),
        "height_complexity": np.zeros(2, dtype=np.float32),
        "motion_probability": np.zeros(2, dtype=np.float32),
        "velocity_xy": np.zeros((2, 2), dtype=np.float32),
        "motion_state": np.full(2, "unknown"),
    }
    values.update(overrides)
    return ObservationFrame(**values)


if __name__ == "__main__":
    unittest.main()
