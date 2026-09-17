import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.validate_temporal import (
    TemporalValidationError,
    validate_frames,
)


class TemporalValidationTests(unittest.TestCase):
    def _dataset_root(self, *, timestamps: str | None) -> Path:
        directory = Path(self._temporary.name)
        sequence = directory / "sequences" / "00"
        (sequence / "velodyne").mkdir(parents=True)
        (sequence / "labels").mkdir()
        for frame_id, x in (("000000", 0.0), ("000001", 1.0)):
            np.array([[x, 0.0, 0.0, 1.0]], dtype=np.float32).tofile(
                sequence / "velodyne" / f"{frame_id}.bin"
            )
            np.array([10], dtype=np.uint32).tofile(
                sequence / "labels" / f"{frame_id}.label"
            )
        (sequence / "poses.txt").write_text(
            "1 0 0 0 0 1 0 0 0 0 1 0\n1 0 0 0 0 1 0 0 0 0 1 0\n"
        )
        (sequence / "calib.txt").write_text("Tr: 1 0 0 0 0 1 0 0 0 0 1 0\n")
        if timestamps is not None:
            (sequence / "times.txt").write_text(timestamps)
        return directory

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._temporary.cleanup()

    def test_validator_requires_dataset_timestamp_provenance(self):
        root = self._dataset_root(timestamps=None)

        with self.assertRaisesRegex(TemporalValidationError, "timestamp"):
            validate_frames(root, "00", count=2)

    def test_validator_rejects_non_increasing_dataset_timestamps(self):
        root = self._dataset_root(timestamps="1.0\n1.0\n")

        with self.assertRaisesRegex(TemporalValidationError, "strictly"):
            validate_frames(root, "00", count=2)

    def test_validator_returns_only_dataset_backed_temporal_evidence(self):
        root = self._dataset_root(timestamps="1.0\n2.0\n")

        result = validate_frames(root, "00", count=2)

        self.assertTrue(result["temporal_proven"])
        self.assertEqual(result["provenance"]["timestamp_sources"], ["dataset"])
        self.assertEqual(result["provenance"]["pose_sources"], ["dataset"])
        self.assertEqual(result["frames"][0]["timestamp_s"], 1.0)
        self.assertEqual(result["frames"][1]["timestamp_s"], 2.0)
        self.assertEqual(result["frames"][1]["motion_samples"], 1)
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
