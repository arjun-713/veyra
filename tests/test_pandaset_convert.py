import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.common.taxonomy import PANDASET_LABELS
from datasets.generic import ManifestDataset
from datasets.pandaset.convert import (
    beam_origin_pose,
    convert,
    pose_matrix,
    world_to_sensor,
)

YAW_90 = {
    "position": {"x": 10.0, "y": -4.0, "z": 0.5},
    "heading": {"w": np.sqrt(0.5), "x": 0.0, "y": 0.0, "z": np.sqrt(0.5)},
}


class PandaSetPoseTests(unittest.TestCase):
    def test_quaternion_pose_is_rigid_sensor_to_world(self):
        matrix = pose_matrix(YAW_90)
        np.testing.assert_allclose(
            matrix[:3, :3] @ matrix[:3, :3].T, np.eye(3), atol=1e-12
        )
        # Sensor +x (forward) points along world +y after a 90 degree yaw.
        np.testing.assert_allclose(matrix[:3, :3] @ [1, 0, 0], [0, 1, 0], atol=1e-12)
        np.testing.assert_allclose(matrix[:3, 3], [10, -4, 0.5])

    def test_world_to_sensor_inverts_pose(self):
        matrix = pose_matrix(YAW_90)
        sensor = np.array([[1.0, 2.0, -1.8], [30.0, -5.0, 2.0]])
        world = sensor @ matrix[:3, :3].T + matrix[:3, 3]
        np.testing.assert_allclose(world_to_sensor(world, matrix), sensor, atol=1e-9)

    def test_beam_origin_lifts_along_sensor_up_axis(self):
        lifted = beam_origin_pose(pose_matrix(YAW_90), 1.55)
        np.testing.assert_allclose(lifted[:3, 3], [10, -4, 2.05], atol=1e-12)
        np.testing.assert_allclose(lifted[:3, :3], pose_matrix(YAW_90)[:3, :3])

    def test_taxonomy_targets_are_valid_and_atmospherics_stay_unknown(self):
        self.assertTrue(all(0 < value <= 19 for value in PANDASET_LABELS.values()))
        for atmospheric in (1, 2, 3, 4):  # smoke, exhaust, spray, reflection
            self.assertNotIn(atmospheric, PANDASET_LABELS)


@unittest.skipUnless(importlib.util.find_spec("pandas"), "pandas is conversion-only")
class PandaSetConvertTests(unittest.TestCase):
    def test_converted_manifest_replays_world_points_and_labels(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp, "raw"), Path(tmp, "veyra")
            lidar = source / "007" / "lidar"
            semseg = source / "007" / "annotations" / "semseg"
            lidar.mkdir(parents=True)
            semseg.mkdir(parents=True)
            world = np.array([[12.0, -2.0, -1.0], [10.0, 6.0, 3.0], [11.0, -4.0, 0.0]])
            pd.DataFrame(
                {
                    "x": world[:, 0],
                    "y": world[:, 1],
                    "z": world[:, 2],
                    "i": [5.0, 200.0, 9.0],
                    "t": [0.0, 0.0, 0.0],
                    "d": [0, 0, 1],
                }
            ).to_pickle(lidar / "00.pkl.gz")
            pd.DataFrame({"class": [7, 41, 13]}).to_pickle(semseg / "00.pkl.gz")
            (lidar / "poses.json").write_text(json.dumps([YAW_90]))
            (lidar / "timestamps.json").write_text(json.dumps([1557540585.3]))

            manifest = convert(source, output, [], "pandar64", origin_offset_m=1.5)
            data = json.loads(manifest.read_text())
            self.assertEqual(
                data["point_schema"]["sensor_origin"]["offset_above_published_pose_m"],
                1.5,
            )

            frame = ManifestDataset(output).load_frame("007", "00")
            # The PandarGT return (d=1) is excluded; world geometry round-trips.
            np.testing.assert_allclose(frame.points[:, :3], world[:2], atol=1e-4)
            np.testing.assert_allclose(frame.points[:, 3], [5.0, 200.0])
            self.assertEqual(frame.semantic_class.tolist(), [9, 13])  # road, building
            self.assertEqual(frame.provenance.coordinate_frame, "world")
            self.assertAlmostEqual(frame.timestamp, 1557540585.3)


if __name__ == "__main__":
    unittest.main()
