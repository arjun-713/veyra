import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.common.taxonomy import RELLIS_LABELS, map_dataset_labels
from datasets.rellis.adapter import Rellis3DDataset


def write_frame(root: Path, sequence: str, frame_id: str, xs: list[float]) -> None:
    sequence_root = root / sequence
    scan_dir = sequence_root / "vel_cloud_node_kitti_bin"
    label_dir = sequence_root / "vel_cloud_node_semantickitti_label_id"
    scan_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    np.asarray([[x, 0.0, 0.0, 0.5] for x in xs], dtype=np.float32).tofile(
        scan_dir / f"{frame_id}.bin"
    )
    np.asarray([0x1000A, 0x20014, 0x30063][: len(xs)], dtype=np.uint32).tofile(
        label_dir / f"{frame_id}.label"
    )


class Rellis3DAdapterTests(unittest.TestCase):
    def test_uses_the_versioned_rellis_learning_taxonomy(self):
        raw = np.array([0, 3, 4, 17, 18, 19, 23, 31, 33], dtype=np.uint32)

        mapped = map_dataset_labels(raw, RELLIS_LABELS)

        np.testing.assert_array_equal(mapped, [0, 1, 2, 11, 12, 13, 14, 16, 17])

    def test_reports_absent_metadata_without_claiming_world_coordinates(self):
        root = Path("data/raw/rellis3d/Rellis-3D")
        if not root.is_dir():
            self.skipTest("original local RELLIS-3D data is unavailable")

        frame = Rellis3DDataset(root).load_frame("00000", "000000")

        self.assertEqual(frame.provenance.coordinate_frame, "lidar")
        self.assertEqual(frame.provenance.timestamp_source, "absent")
        self.assertEqual(frame.provenance.pose_source, "identity_absent")

    def test_original_local_frame_maps_real_labels(self):
        root = Path(__file__).parents[1] / "data/raw/rellis3d/Rellis-3D"
        if not root.is_dir():
            self.skipTest("original local RELLIS-3D data is unavailable")
        adapter = Rellis3DDataset(root, sequences=["00000"])
        frame = adapter.load_frame("00000", adapter.list_frames("00000")[0].frame_id)
        self.assertGreater(frame.points.shape[0], 10_000)
        self.assertGreater(np.count_nonzero(frame.semantic_class), 0)

    def test_real_taxonomy_maps_known_labels_and_preserves_unknown(self):
        mapped = map_dataset_labels(np.array([3, 17, 999]), RELLIS_LABELS)
        self.assertEqual(mapped.tolist(), [1, 11, 0])

    def test_pairs_numeric_frames_and_extracts_low_16_labels(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00000", "10", [10.0, 11.0])
            write_frame(root, "00000", "2", [2.0, 3.0])
            adapter = Rellis3DDataset(root, sequences=["00000"])

            self.assertEqual(
                [ref.frame_id for ref in adapter.list_frames("00000")], ["2", "10"]
            )
            frame = adapter.load_frame("00000", "2", label_mapping={10: 1, 20: 2})
            np.testing.assert_array_equal(frame.semantic_class, [1, 2])
            np.testing.assert_array_equal(frame.raw_semantic_class, [10, 20])

    def test_applies_real_pose_and_calibration_when_present(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00000", "0", [1.0])
            (root / "poses").mkdir()
            (root / "poses" / "00000.txt").write_text("1 0 0 10  0 1 0 20  0 0 1 30\n")
            (root / "calib").mkdir()
            (root / "calib" / "00000.txt").write_text(
                "Tr_velo_to_cam: 1 0 0 1  0 1 0 2  0 0 1 3\n"
            )

            frame = Rellis3DDataset(root).load_frame("00000", "0")

            np.testing.assert_allclose(frame.points[0, :3], [12.0, 22.0, 33.0])
            self.assertEqual(frame.pose.matrix[0, 3], 11.0)

    def test_uses_identity_pose_when_metadata_is_absent(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00000", "0", [1.0])

            frame = Rellis3DDataset(root).load_frame("00000", "0")

            np.testing.assert_allclose(frame.points[0, :3], [1.0, 0.0, 0.0])
            np.testing.assert_allclose(frame.pose.matrix, np.eye(4))
            self.assertIsNone(frame.timestamp)

    def test_range_filter_and_replay_are_bounded_and_deterministic(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00000", "2", [2.0, 101.0])
            write_frame(root, "00000", "10", [10.0, 11.0])
            adapter = Rellis3DDataset(root, sequences=["00000"])

            first = list(adapter.replay("00000", max_range_m=100.0))
            second = list(adapter.replay("00000", max_range_m=100.0))

            self.assertEqual([frame.frame_id for frame in first], ["2", "10"])
            self.assertEqual([frame.points.shape[0] for frame in first], [1, 2])
            for left, right in zip(first, second):
                np.testing.assert_array_equal(left.points, right.points)
                np.testing.assert_array_equal(left.semantic_class, right.semantic_class)

    def test_actual_local_data_smoke_is_skipped_when_unavailable(self):
        root = Path("data/raw/rellis3d/Rellis-3D")
        if not root.is_dir():
            self.skipTest("original local RELLIS-3D data is not available")
        adapter = Rellis3DDataset(root, sequences=["00000"])
        sequences = adapter.list_sequences()
        self.assertIn("00000", sequences)
        self.assertTrue(adapter.list_frames("00000"))


if __name__ == "__main__":
    unittest.main()
