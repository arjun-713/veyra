import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.validate_dataset_capabilities import build_report


class DatasetCapabilityReportTests(unittest.TestCase):
    def test_report_records_real_adapter_evidence_and_unavailable_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sequence = root / "00000"
            (sequence / "vel_cloud_node_kitti_bin").mkdir(parents=True)
            (sequence / "vel_cloud_node_semantickitti_label_id").mkdir()
            np.array([[1, 2, 3, 4]], dtype=np.float32).tofile(
                sequence / "vel_cloud_node_kitti_bin" / "000000.bin"
            )
            np.array([0x0000A], dtype=np.uint32).tofile(
                sequence / "vel_cloud_node_semantickitti_label_id" / "000000.label"
            )

            report = build_report(
                dataset_name="rellis3d",
                root=root,
                sequences=["00000"],
                sample_limit=1,
            )

        self.assertEqual(report["status"], "validated_local")
        self.assertEqual(report["representative_frame_count"], 1)
        self.assertTrue(report["checks"]["point_label_alignment"])
        self.assertTrue(report["checks"]["deterministic_replay"])
        self.assertEqual(report["metadata"]["timestamp"]["status"], "unavailable")
        self.assertEqual(report["metadata"]["pose"]["status"], "unavailable")
        json.dumps(report)

    def test_absent_root_is_reported_without_claiming_validation(self):
        report = build_report(
            dataset_name="semantickitti",
            root=Path("/definitely/not/a/dataset"),
            sequences=["00"],
            sample_limit=1,
        )

        self.assertEqual(report["status"], "unvalidated_local")
        self.assertEqual(report["reason"], "local_root_unavailable")
        self.assertFalse(report["checks"]["deterministic_replay"])

    def test_malformed_local_data_is_reported_with_actionable_checkpoint(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            (sequence / "labels" / "000000.label").write_bytes(b"bad")

            report = build_report(
                dataset_name="semantickitti",
                root=root,
                sequences=["00"],
                sample_limit=1,
            )

        self.assertEqual(report["status"], "invalid_local_data")
        self.assertEqual(report["reason"], "frame_validation_failed")
        self.assertIn("complete uint32 label records", report["diagnostic"])

    def test_discovery_failure_is_reported_with_the_sequence_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "sequences" / "00").mkdir(parents=True)

            report = build_report(
                dataset_name="semantickitti",
                root=root,
                sequences=["00"],
                sample_limit=1,
            )

        self.assertEqual(report["status"], "invalid_local_data")
        self.assertEqual(report["reason"], "frame_discovery_failed")
        self.assertIn("semantickitti/00", report["diagnostic"])

    def test_missing_required_label_is_reported_during_discovery(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.zeros(4, dtype=np.float32).tofile(sequence / "velodyne" / "000000.bin")

            report = build_report(
                dataset_name="semantickitti",
                root=root,
                sequences=["00"],
                sample_limit=1,
            )

        self.assertEqual(report["reason"], "frame_discovery_failed")
        self.assertIn("label file is missing", report["diagnostic"])


if __name__ == "__main__":
    unittest.main()
