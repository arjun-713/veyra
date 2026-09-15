import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.semantickitti import SemanticKITTIDataset


class SemanticKITTIAdapterTests(unittest.TestCase):
    def test_preserves_numeric_order_and_reuses_bounded_sequence_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for frame_id in ("10", "2"):
                sequence = root / "sequences" / "00"
                (sequence / "velodyne").mkdir(parents=True, exist_ok=True)
                (sequence / "labels").mkdir(exist_ok=True)
                np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                    sequence / "velodyne" / f"{frame_id}.bin"
                )
                np.array([10], dtype=np.uint32).tofile(
                    sequence / "labels" / f"{frame_id}.label"
                )
            adapter = SemanticKITTIDataset(root)
            refs = adapter.list_frames("00")
            (root / "sequences" / "00" / "velodyne" / "99.bin").write_bytes(
                (root / "sequences" / "00" / "velodyne" / "10.bin").read_bytes()
            )

            self.assertEqual(
                [ref.frame_id for ref in adapter.list_frames("00")], ["2", "10"]
            )
            self.assertIs(adapter.list_frames("00"), refs)

    def test_rejects_nonfinite_pose_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels" / "000000.label")
            (sequence / "poses.txt").write_text("nan 0 0 0 0 1 0 0 0 0 1 0\n")

            with self.assertRaises(ValueError):
                SemanticKITTIDataset(root).load_frame("00", "000000")

    def test_replays_calibrated_world_frame_with_timestamp_and_raw_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels" / "000000.label")
            (sequence / "times.txt").write_text("12.5\n")
            (sequence / "poses.txt").write_text("1 0 0 10 0 1 0 0 0 0 1 0\n")
            (sequence / "calib.txt").write_text("Tr: 1 0 0 2 0 1 0 0 0 0 1 0\n")

            frame = SemanticKITTIDataset(root).load_frame("00", "000000")

        self.assertEqual(frame.timestamp, 12.5)
        self.assertEqual(frame.provenance.coordinate_frame, "world")
        self.assertEqual(frame.provenance.timestamp_source, "dataset")
        np.testing.assert_allclose(frame.points[:, 0], [11.0])
        np.testing.assert_array_equal(frame.raw_semantic_class, [10])
        np.testing.assert_array_equal(frame.semantic_class, [1])

    def test_real_data_smoke_skips_only_when_the_configured_asset_is_missing(self):
        root = Path("data/raw/semantickitti/dataset")
        if not root.is_dir():
            self.skipTest("original local SemanticKITTI data is unavailable")
        frame = next(SemanticKITTIDataset(root).replay("00", end=1))
        self.assertEqual(frame.dataset, "semantickitti")

    def test_rejects_missing_labels_and_malformed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scan_dir = root / "sequences" / "00" / "velodyne"
            scan_dir.mkdir(parents=True)
            label_dir = root / "sequences" / "00" / "labels"
            label_dir.mkdir()
            np.array([1.0, 2.0, 3.0], dtype=np.float32).tofile(scan_dir / "000000.bin")
            np.array([10], dtype=np.uint32).tofile(label_dir / "000000.label")

            with self.assertRaises(ValueError):
                SemanticKITTIDataset(root).load_frame("00", "000000")


if __name__ == "__main__":
    unittest.main()
