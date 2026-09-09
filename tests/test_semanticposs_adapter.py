import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.semanticposs.adapter import SemanticPOSSDataset


def write_frame(
    root: Path, sequence: str, frame_id: str, x_values: list[float]
) -> None:
    seq_root = root / sequence
    (seq_root / "velodyne").mkdir(parents=True, exist_ok=True)
    (seq_root / "labels").mkdir(parents=True, exist_ok=True)
    points = np.array([[x, 0.0, 0.0, 0.5] for x in x_values], dtype=np.float32)
    points.tofile(seq_root / "velodyne" / f"{frame_id}.bin")
    np.array([10, 20, 99][: len(points)], dtype=np.uint32).tofile(
        seq_root / "labels" / f"{frame_id}.label"
    )


class SemanticPOSSAdapterTests(unittest.TestCase):
    def test_frames_are_sorted_numerically_and_labels_are_paired(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00", "10", [10.0, 11.0])
            write_frame(root, "00", "2", [2.0, 3.0])
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            self.assertEqual(
                [ref.frame_id for ref in adapter.list_frames("00")], ["2", "10"]
            )
            frame = adapter.load_frame("00", "2", label_mapping={10: 1, 20: 2})
            np.testing.assert_array_equal(frame.semantic_class, [1, 2])
            np.testing.assert_array_equal(frame.semantic_confidence, [1.0, 1.0])

    def test_pose_and_calibration_transform_points_into_world(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00", "0", [1.0])
            (root / "poses").mkdir()
            (root / "poses" / "00.txt").write_text("1 0 0 10  0 1 0 20  0 0 1 30\n")
            (root / "calib").mkdir()
            (root / "calib" / "00.txt").write_text("Tr: 1 0 0 1  0 1 0 2  0 0 1 3\n")
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            frame = adapter.load_frame("00", "0", label_mapping={10: 1})

            np.testing.assert_allclose(frame.points[0, :3], [12.0, 22.0, 33.0])

    def test_range_crop_drops_points_outside_100_m_envelope(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00", "0", [1.0, 101.0])
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            frame = adapter.load_frame(
                "00", "0", label_mapping={10: 1, 20: 2}, max_range_m=100.0
            )

            self.assertEqual(frame.points.shape[0], 1)
            self.assertEqual(frame.points[0, 0], 1.0)

    def test_replay_is_deterministic_for_same_configuration(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00", "2", [2.0, 3.0])
            write_frame(root, "00", "10", [10.0, 11.0])
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            first = list(adapter.replay("00", label_mapping={10: 1, 20: 2}))
            second = list(adapter.replay("00", label_mapping={10: 1, 20: 2}))

            self.assertEqual([f.frame_id for f in first], ["2", "10"])
            self.assertEqual([f.frame_id for f in first], [f.frame_id for f in second])
            for left, right in zip(first, second):
                np.testing.assert_array_equal(left.points, right.points)
                np.testing.assert_array_equal(left.semantic_class, right.semantic_class)

    def test_supports_kitti_sequences_subdirectory_layout(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root / "sequences", "00", "0", [1.0])
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            frame = adapter.load_frame("00", "0", label_mapping={10: 1})

            self.assertEqual(frame.dataset, "semanticposs")
            self.assertEqual(frame.frame_id, "0")

    def test_rejects_malformed_scan_and_missing_label(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            seq_root = root / "00"
            (seq_root / "velodyne").mkdir(parents=True)
            (seq_root / "labels").mkdir(parents=True)
            np.array([1.0, 2.0, 3.0], dtype=np.float32).tofile(
                seq_root / "velodyne" / "0.bin"
            )
            np.array([10], dtype=np.uint32).tofile(seq_root / "labels" / "0.label")
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            with self.assertRaises(ValueError):
                adapter.load_frame("00", "0")

            (seq_root / "velodyne" / "0.bin").write_bytes(b"\x00" * 16)
            (seq_root / "labels" / "0.label").unlink()
            with self.assertRaises(FileNotFoundError):
                adapter.load_frame("00", "0")

    def test_reads_timestamps_by_sorted_frame_order(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00", "10", [10.0])
            write_frame(root, "00", "2", [2.0])
            (root / "timestamps").mkdir()
            (root / "timestamps" / "00.txt").write_text("0.25\n0.50\n")
            adapter = SemanticPOSSDataset(root)

            frames = list(adapter.replay("00", label_mapping={10: 1}))

            self.assertEqual(adapter.list_sequences(), ["00"])
            self.assertEqual([frame.frame_id for frame in frames], ["2", "10"])
            self.assertEqual([frame.timestamp for frame in frames], [0.25, 0.50])

    def test_rejects_scan_and_label_count_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_frame(root, "00", "0", [1.0, 2.0])
            np.array([10], dtype=np.uint32).tofile(root / "00" / "labels" / "0.label")
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            with self.assertRaises(ValueError):
                adapter.load_frame("00", "0")


if __name__ == "__main__":
    unittest.main()
