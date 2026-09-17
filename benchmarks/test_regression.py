"""Tests for the bounded, real-data acceptance harness."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.regression import (
    DEFAULT_SCAN_SHA256,
    DEFAULT_SCAN_URL,
    MAX_SCAN_BYTES,
    asset_manifest,
    correspondence_report,
    load_scan_frame,
    taxonomy_range_report,
    verify_download,
)


class RegressionHarnessTests(unittest.TestCase):
    def test_manifest_is_immutable_and_bounded(self):
        manifest = asset_manifest()

        self.assertEqual(manifest["url"], DEFAULT_SCAN_URL)
        self.assertEqual(manifest["sha256"], DEFAULT_SCAN_SHA256)
        self.assertLessEqual(manifest["size_bytes"], MAX_SCAN_BYTES)
        self.assertEqual(manifest["format"], "float32_xyzi")
        self.assertEqual(manifest["pose_source"], "absent")
        self.assertEqual(manifest["timestamp_source"], "absent")

    def test_verify_download_rejects_wrong_digest_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.bin"
            known_good = b"known-good-scan-bytes"
            path.write_bytes(known_good)
            good_sha256 = hashlib.sha256(known_good).hexdigest()
            verify_download(path, sha256=good_sha256, max_bytes=MAX_SCAN_BYTES)
            path.write_bytes(b"mutated-scan-bytes")
            with self.assertRaises(ValueError):
                verify_download(path, sha256=good_sha256, max_bytes=MAX_SCAN_BYTES)

            path.write_bytes(b"x" * (MAX_SCAN_BYTES + 1))
            with self.assertRaises(ValueError):
                verify_download(
                    path,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    max_bytes=MAX_SCAN_BYTES,
                )

    def test_load_scan_frame_preserves_missing_pose_and_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.bin"
            points = np.array([[1.0, 2.0, 3.0, 0.25]], dtype=np.float32)
            points.tofile(path)

            frame = load_scan_frame(path)

        self.assertEqual(frame.timestamp, None)
        self.assertEqual(frame.pose.timestamp, None)
        self.assertEqual(frame.provenance.timestamp_source, "absent")
        self.assertEqual(frame.provenance.pose_source, "identity_absent")
        self.assertEqual(frame.provenance.coordinate_frame, "lidar")
        np.testing.assert_array_equal(frame.points, points)

    def test_perception_report_requires_exact_input_output_point_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.bin"
            points = np.array(
                [[3.0, 4.0, 0.0, 0.25], [0.0, 0.0, 2.0, 0.5]], dtype=np.float32
            )
            points.tofile(path)
            frame = load_scan_frame(path)

        report = correspondence_report(frame, frame)
        self.assertTrue(report["xyz_intensity_exactly_preserved"])
        self.assertTrue(report["per_point_fields_aligned"])
        self.assertEqual(
            taxonomy_range_report(points, frame)["ground_truth_accuracy"], None
        )
        self.assertEqual(
            sum(
                bucket["points"]
                for bucket in taxonomy_range_report(points, frame)["range_bins"]
            ),
            len(points),
        )
        self.assertIsNone(
            taxonomy_range_report(points, frame)["range_bins"][-1]["max_m"]
        )
        json.dumps(taxonomy_range_report(points, frame), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
