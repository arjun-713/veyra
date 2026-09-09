import unittest

import numpy as np

from datasets.common.observation import ObservationFrame, PoseSE3


class ObservationContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
