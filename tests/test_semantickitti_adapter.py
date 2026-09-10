import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.semantickitti import SemanticKITTIDataset


class SemanticKITTIAdapterTests(unittest.TestCase):
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
        np.testing.assert_allclose(frame.points[:, 0], [13.0])
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
