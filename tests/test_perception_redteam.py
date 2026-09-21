"""Adversarial, ownership-safe tests for the Mallik perception boundary.

Synthetic cases below exercise contracts without pretending to be dataset
quality evidence.  The real-data case reads only the primary checkout's
ignored SemanticPOSS fixture when it is present.
"""

import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.protocol import binary_frame_bytes, frame_records, stream_file
from datasets.common.observation import (
    FrameProvenance,
    ObservationFrame,
    PoseSE3,
    SemanticFrame,
)
from datasets.semanticposs.adapter import SemanticPOSSDataset

PRIMARY_SEMANTIC_POSS = Path(
    "/home/arjun/Captain/SIH/Lidar/data/raw/semanticposs/dataset"
)


def _frame(**overrides) -> ObservationFrame:
    values = {
        "timestamp": 12.5,
        "pose": PoseSE3.identity(12.5),
        "points": np.array(
            [[10.0, 0.0, 1.0, 0.1], [20.0, 0.0, 2.0, 0.2]], dtype=np.float32
        ),
        "semantic_class": np.array([3, 4], dtype=np.int32),
        "semantic_confidence": np.array([0.25, 0.75], dtype=np.float32),
        "ground": np.array([True, False]),
        "drivable": np.array(["drivable", "unknown"]),
        "slope": np.array([0.1, np.nan], dtype=np.float32),
        "roughness": np.array([0.2, np.nan], dtype=np.float32),
        "height_complexity": np.array([0.3, np.nan], dtype=np.float32),
        "motion_probability": np.array([0.4, 0.0], dtype=np.float32),
        "velocity_xy": np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        "terrain_confidence": np.array([0.8, 0.0], dtype=np.float32),
        "step": np.array([0.5, np.nan], dtype=np.float32),
        "motion_state": np.array(["moving", "unknown"]),
        "observation_quality": np.array([0.9, 0.1], dtype=np.float32),
        "raw_semantic_class": np.array([30, 40], dtype=np.int32),
        "instance_id": np.array([7, 8], dtype=np.int32),
        "dataset": "synthetic-redteam",
        "sequence": "00",
        "frame_id": "000012",
        "provenance": FrameProvenance(
            coordinate_frame="world",
            timestamp_source="dataset",
            pose_source="dataset",
            calibration_source="dataset",
            label_source="dataset",
        ),
    }
    values.update(overrides)
    return ObservationFrame(**values)


class PerceptionRedTeamTests(unittest.TestCase):
    def test_evidence_utility_serializes_a_fixture_without_inventing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            sequence = root / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 2.0, 3.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne/0.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels/0.label")
            output = Path(directory) / "evidence.stream"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/emit_perception_evidence.py",
                    "--dataset-root",
                    str(root),
                    "--sequence",
                    "00",
                    "--frame-id",
                    "0",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["source_kind"], "synthetic_fixture")
        self.assertEqual(report["point_count"], 1)
        self.assertEqual(report["provenance"]["pose_source"], "identity_absent")
        self.assertEqual(report["provenance"]["timestamp_source"], "absent")
        self.assertTrue(report["serialized_path"].endswith("evidence.stream"))

    def test_synthetic_contract_preserves_point_order_and_all_labels(self):
        frame = _frame()
        records = frame_records(frame)
        point_records = [line.split() for line in records if line.startswith("P ")]

        self.assertEqual([float(row[1]) for row in point_records], [10.0, 20.0])
        self.assertEqual([int(row[5]) for row in point_records], [3, 4])
        self.assertEqual([int(row[-2]) for row in point_records], [30, 40])
        self.assertEqual([row[-1] for row in point_records], ["NA", "NA"])
        self.assertEqual([int(row[3]) for row in point_records], [1, 2])
        self.assertEqual([int(row[8]) for row in point_records], [1, 0])
        self.assertEqual(records[-1], "E\n")

    def test_synthetic_binary_bridge_retains_order_and_enriched_evidence(self):
        frame = _frame()
        payload = binary_frame_bytes(frame)
        self.assertTrue(payload.startswith(b"B 2\n"))
        header_size = struct.calcsize("<QQQ16d")
        point_bytes = payload[4 + header_size :]
        self.assertEqual(len(point_bytes), 2 * 71)
        row_dtype = np.dtype(
            [
                ("xyzi", "<f4", (4,)),
                ("semantic", "<u4"),
                ("confidence", "<f4"),
                ("ground", "u1"),
                ("drivable", "u1"),
                ("slope", "<f4"),
                ("roughness", "<f4"),
                ("complexity", "<f4"),
                ("terrain", "<f4"),
                ("step", "<f4"),
                ("motion", "<f4"),
                ("state", "u1"),
                ("velocity", "<f4", (2,)),
                ("quality", "<f4"),
                ("raw", "<i4"),
                ("height_above_ground", "<f4"),
            ]
        )
        rows = np.frombuffer(point_bytes, dtype=row_dtype)
        np.testing.assert_allclose(rows["xyzi"][:, 0], [10.0, 20.0])
        np.testing.assert_array_equal(rows["semantic"], [3, 4])
        np.testing.assert_allclose(rows["confidence"], [0.25, 0.75])
        np.testing.assert_array_equal(rows["raw"], [30, 40])
        np.testing.assert_allclose(rows["quality"], [0.9, 0.1])

    def test_synthetic_serialized_file_retains_digest_and_nan_sentinels(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "frame.stream"
            digest = stream_file([_frame()], output)
            serialized = output.read_text()

        self.assertIn(f"H {digest}\n", serialized)
        self.assertIn(f"D {digest}\n", serialized)
        self.assertIn(" NA ", serialized)
        self.assertNotIn("nan", serialized.lower())

    def test_semantic_ids_and_confidences_fail_closed_at_contract_boundary(self):
        for value in (-1, 2**31, 1.5, np.nan, np.inf):
            with (
                self.subTest(field="semantic_class", value=value),
                self.assertRaises(ValueError),
            ):
                _frame(semantic_class=np.array([value, 1]))
        for value in (-0.01, 1.01, np.nan, np.inf):
            with (
                self.subTest(field="semantic_confidence", value=value),
                self.assertRaises(ValueError),
            ):
                _frame(semantic_confidence=np.array([value, 0.5]))

    def test_semantic_provider_result_does_not_narrow_fractional_ids(self):
        with self.assertRaises(ValueError):
            SemanticFrame(
                semantic_class=np.array([1.5, 2.0]),
                semantic_confidence=np.array([0.5, 0.5]),
                mode="model",
            )

    def test_unknown_terrain_is_not_collapsed_to_free_when_ground_is_unavailable(self):
        from perception.pipeline import PerceptionPipeline

        class UnavailableGround:
            def segment(self, points):
                del points
                raise RuntimeError("fixture backend unavailable")

        output = PerceptionPipeline(ground_segmenter=UnavailableGround()).process(
            _frame()
        )
        self.assertEqual(output.status.ground, "unavailable")
        self.assertEqual(output.status.terrain, "unavailable")
        np.testing.assert_array_equal(output.frame.drivable, ["drivable", "unknown"])

    def test_missing_pose_or_time_never_advances_temporal_tracker(self):
        from perception.pipeline import PerceptionPipeline

        class MustNotRun:
            def update(self, *args, **kwargs):
                raise AssertionError("temporal tracker received unproven metadata")

        for provenance, timestamp in (
            (
                FrameProvenance(
                    coordinate_frame="lidar",
                    timestamp_source="dataset",
                    pose_source="identity_absent",
                    calibration_source="identity_absent",
                    label_source="dataset",
                ),
                12.5,
            ),
            (
                FrameProvenance(
                    coordinate_frame="world",
                    timestamp_source="absent",
                    pose_source="dataset",
                    calibration_source="dataset",
                    label_source="dataset",
                ),
                None,
            ),
        ):
            with self.subTest(provenance=provenance):
                output = PerceptionPipeline(temporal_tracker=MustNotRun()).process(
                    _frame(provenance=provenance, timestamp=timestamp)
                )
                self.assertEqual(output.status.temporal, "unavailable")

    def test_synthetic_scan_label_mismatch_is_rejected_before_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sequences"
            sequence = root / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.zeros((2, 4), dtype=np.float32).tofile(sequence / "velodyne/0.bin")
            np.array([1], dtype=np.uint32).tofile(sequence / "labels/0.label")
            with self.assertRaisesRegex(ValueError, "scan/label length mismatch"):
                SemanticPOSSDataset(root.parent).load_frame("00", "0")

    @unittest.skipUnless(
        PRIMARY_SEMANTIC_POSS.is_dir(),
        "primary checkout SemanticPOSS fixture is unavailable",
    )
    def test_real_semanticposs_fixture_preserves_source_contract(self):
        adapter = SemanticPOSSDataset(PRIMARY_SEMANTIC_POSS, sequences=["00"])
        reference = adapter.list_frames("00")[0]
        frame = adapter.load_frame("00", reference.frame_id)

        self.assertGreater(frame.points.shape[0], 10_000)
        self.assertEqual(frame.points.shape[0], frame.semantic_class.shape[0])
        self.assertEqual(frame.points.shape[0], frame.raw_semantic_class.shape[0])
        self.assertEqual(frame.provenance.coordinate_frame, "world")
        self.assertEqual(frame.provenance.pose_source, "dataset")
        self.assertEqual(frame.provenance.calibration_source, "dataset")
        self.assertEqual(frame.provenance.label_source, "dataset")
        self.assertTrue(np.isfinite(frame.points).all())
        self.assertTrue(
            ((frame.semantic_confidence >= 0) & (frame.semantic_confidence <= 1)).all()
        )


if __name__ == "__main__":
    unittest.main()
