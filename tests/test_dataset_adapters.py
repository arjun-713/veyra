"""Dataset adapters regression suite."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.common.taxonomy import (
    RELLIS_LABELS,
    SEMANTIC_POSS_LABELS,
    SEMANTICKITTI_LABELS,
    map_dataset_labels,
)
from datasets.rellis.adapter import Rellis3DDataset
from datasets.semantickitti import SemanticKITTIDataset
from datasets.semanticposs.adapter import SemanticPOSSDataset
from perception.pipeline import PerceptionPipeline

# Semanticposs adapter


def write_poss_frame(
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
    def test_caches_frame_and_metadata_indexes_per_sequence(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0])
            (root / "00" / "poses.txt").write_text("1 0 0 0 0 1 0 0 0 0 1 0\n")
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            refs = adapter.list_frames("00")
            frame = adapter.load_frame("00", "0", label_mapping={10: 1})
            (root / "00" / "poses.txt").write_text("malformed\n")
            (root / "00" / "velodyne" / "1.bin").write_bytes(
                (root / "00" / "velodyne" / "0.bin").read_bytes()
            )

            self.assertIs(adapter.list_frames("00"), refs)
            self.assertEqual(frame.frame_id, "0")
            self.assertEqual(
                adapter.load_frame("00", "0", label_mapping={10: 1}).frame_id, "0"
            )
            self.assertEqual(len(adapter._sequence_cache), 1)
            self.assertEqual(len(adapter._metadata_cache), 1)

    def test_rejects_negative_or_nonfinite_range_bounds(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0])
            adapter = SemanticPOSSDataset(root)
            for kwargs in (
                {"min_range_m": -1.0},
                {"min_range_m": float("nan")},
                {"max_range_m": 0.5, "min_range_m": 1.0},
            ):
                with self.assertRaises(ValueError):
                    adapter.load_frame("00", "0", **kwargs)

    def test_uses_the_versioned_semanticposs_label_taxonomy(self):
        raw = np.array([0, 4, 7, 8, 15, 22], dtype=np.uint32)

        mapped = map_dataset_labels(raw, SEMANTIC_POSS_LABELS)

        np.testing.assert_array_equal(mapped, [0, 6, 1, 16, 13, 12])

    def test_preserves_packed_semanticposs_instance_bits_after_range_crop(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0, 200.0])
            np.array([(12 << 16) | 10, (7 << 16) | 20], dtype=np.uint32).tofile(
                root / "00" / "labels" / "0.label"
            )

            frame = SemanticPOSSDataset(root).load_frame("00", "0", max_range_m=100)

        np.testing.assert_array_equal(frame.raw_semantic_class, [10])
        np.testing.assert_array_equal(frame.instance_id, [12])

    def test_range_crop_uses_lidar_range_before_world_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_poss_frame(root, "00", "0", [1.0, 200.0])
            (root / "00" / "poses.txt").write_text("1 0 0 1000 0 1 0 0 0 0 1 0\n")
            (root / "00" / "calib.txt").write_text("Tr: 1 0 0 0 0 1 0 0 0 0 1 0\n")

            frame = SemanticPOSSDataset(root).load_frame("00", "0", max_range_m=100.0)

        self.assertEqual(frame.points.shape, (1, 4))
        self.assertAlmostEqual(float(frame.points[0, 0]), 1001.0)

    def test_reports_present_pose_and_absent_timestamp_provenance(self):
        root = Path("data/raw/semanticposs/dataset")
        if not root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")

        frame = SemanticPOSSDataset(root).load_frame("00", "000000")

        self.assertEqual(frame.provenance.coordinate_frame, "world")
        self.assertEqual(frame.provenance.pose_source, "dataset")
        self.assertEqual(frame.provenance.calibration_source, "dataset")
        self.assertEqual(frame.provenance.timestamp_source, "absent")

    def test_reports_dataset_pose_and_timestamp_provenance_when_both_exist(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0])
            (root / "00" / "poses.txt").write_text("1 0 0 10 0 1 0 20 0 0 1 30\n")
            (root / "00" / "timestamps.txt").write_text("4.25\n")

            frame = SemanticPOSSDataset(root).load_frame("00", "0")

        self.assertEqual(frame.timestamp, 4.25)
        self.assertEqual(frame.provenance.timestamp_source, "dataset")
        self.assertEqual(frame.provenance.pose_source, "dataset")
        self.assertEqual(frame.provenance.coordinate_frame, "world")

    def test_original_local_frame_maps_real_labels_and_pipeline_contract(self):
        root = Path(__file__).parents[1] / "data/raw/semanticposs/dataset"
        if not root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")
        adapter = SemanticPOSSDataset(root, sequences=["00"])
        frame = adapter.load_frame("00", adapter.list_frames("00")[0].frame_id)
        self.assertGreater(frame.points.shape[0], 10_000)
        self.assertGreater(np.count_nonzero(frame.semantic_class), 0)

        output = PerceptionPipeline().process(frame)
        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertEqual(output.frame.points.shape, frame.points.shape)

    def test_real_taxonomy_maps_known_labels_and_preserves_unknown(self):
        mapped = map_dataset_labels(np.array([4, 7, 999]), SEMANTIC_POSS_LABELS)
        self.assertEqual(mapped.tolist(), [6, 1, 0])

    def test_frames_are_sorted_numerically_and_labels_are_paired(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "10", [10.0, 11.0])
            write_poss_frame(root, "00", "2", [2.0, 3.0])
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            self.assertEqual(
                [ref.frame_id for ref in adapter.list_frames("00")], ["2", "10"]
            )
            frame = adapter.load_frame("00", "2", label_mapping={10: 1, 20: 2})
            np.testing.assert_array_equal(frame.semantic_class, [1, 2])
            np.testing.assert_array_equal(frame.raw_semantic_class, [10, 20])
            np.testing.assert_array_equal(frame.semantic_confidence, [1.0, 1.0])

    def test_unknown_mapped_label_has_zero_semantic_confidence(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0, 2.0, 3.0])
            frame = SemanticPOSSDataset(root).load_frame(
                "00", "0", label_mapping={10: 1, 20: 2}
            )

            np.testing.assert_array_equal(frame.semantic_class, [1, 2, 0])
            np.testing.assert_array_equal(frame.semantic_confidence, [1.0, 1.0, 0.0])

    def test_optional_labels_are_explicitly_unknown(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0])
            (root / "00" / "labels" / "0.label").unlink()

            frame = SemanticPOSSDataset(root, require_labels=False).load_frame(
                "00", "0"
            )

        np.testing.assert_array_equal(frame.semantic_class, [0])
        np.testing.assert_array_equal(frame.semantic_confidence, [0.0])
        self.assertEqual(frame.provenance.label_source, "absent")

    def test_rejects_nonrigid_calibration_even_when_pose_is_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0])
            (root / "00" / "calib.txt").write_text("Tr: 2 0 0 0 0 1 0 0 0 0 1 0\n")

            with self.assertRaisesRegex(ValueError, "not a rigid"):
                SemanticPOSSDataset(root).load_frame("00", "0")

    def test_pose_and_calibration_transform_points_into_world(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0])
            (root / "poses").mkdir()
            (root / "poses" / "00.txt").write_text("1 0 0 10  0 1 0 20  0 0 1 30\n")
            (root / "calib").mkdir()
            (root / "calib" / "00.txt").write_text("Tr: 1 0 0 1  0 1 0 2  0 0 1 3\n")
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            frame = adapter.load_frame("00", "0", label_mapping={10: 1})

            np.testing.assert_allclose(frame.points[0, :3], [11.0, 20.0, 30.0])

    def test_range_crop_drops_points_outside_100_m_envelope(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0, 101.0])
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            frame = adapter.load_frame(
                "00", "0", label_mapping={10: 1, 20: 2}, max_range_m=100.0
            )

            self.assertEqual(frame.points.shape[0], 1)
            self.assertEqual(frame.points[0, 0], 1.0)

    def test_replay_is_deterministic_for_same_configuration(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "2", [2.0, 3.0])
            write_poss_frame(root, "00", "10", [10.0, 11.0])
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
            write_poss_frame(root / "sequences", "00", "0", [1.0])
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
            write_poss_frame(root, "00", "10", [10.0])
            write_poss_frame(root, "00", "2", [2.0])
            (root / "timestamps").mkdir()
            (root / "timestamps" / "00.txt").write_text("0.25\n0.50\n")
            adapter = SemanticPOSSDataset(root)

            frames = list(adapter.replay("00", label_mapping={10: 1}))

            self.assertEqual(adapter.list_sequences(), ["00"])
            self.assertEqual([frame.frame_id for frame in frames], ["2", "10"])
            self.assertEqual([frame.timestamp for frame in frames], [0.25, 0.50])

    def test_resolves_absolute_metadata_lines_for_partial_checkouts(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "400", [400.0])
            write_poss_frame(root, "00", "401", [401.0])
            lines = "".join(f"{i * 0.1:.1f}\n" for i in range(402))
            (root / "timestamps").mkdir()
            (root / "timestamps" / "00.txt").write_text(lines)
            adapter = SemanticPOSSDataset(root)

            frames = list(adapter.replay("00", label_mapping={10: 1}))

            self.assertEqual([frame.frame_id for frame in frames], ["400", "401"])
            self.assertEqual([frame.timestamp for frame in frames], [40.0, 40.1])

    def test_frame_index_without_total_lines_keeps_historical_numeric_behavior(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "2", [2.0])
            write_poss_frame(root, "00", "10", [10.0])
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            self.assertEqual(adapter._frame_index("00", "10", total_lines=None), 10)
            self.assertEqual(adapter._frame_index("00", "10", total_lines=1), 1)

    def test_rejects_scan_and_label_count_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0, 2.0])
            np.array([10], dtype=np.uint32).tofile(root / "00" / "labels" / "0.label")
            adapter = SemanticPOSSDataset(root, sequences=["00"])

            with self.assertRaises(ValueError):
                adapter.load_frame("00", "0")

    def test_rejects_nonfinite_scan_values(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_poss_frame(root, "00", "0", [1.0])
            np.array([[np.inf, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                root / "00" / "velodyne" / "0.bin"
            )

            with self.assertRaisesRegex(ValueError, "non-finite"):
                SemanticPOSSDataset(root).load_frame("00", "0")


# Semantickitti adapter


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

    def test_discovery_rejects_unmatched_label_files_before_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels" / "000000.label")
            np.array([10], dtype=np.uint32).tofile(sequence / "labels" / "000001.label")

            with self.assertRaisesRegex(ValueError, "label has no matching scan"):
                SemanticKITTIDataset(root).list_frames("00")

    def test_rejects_label_files_with_trailing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            label = sequence / "labels" / "000000.label"
            label.write_bytes(np.array([10], dtype=np.uint32).tobytes() + b"x")

            with self.assertRaisesRegex(ValueError, "complete uint32 label records"):
                SemanticKITTIDataset(root).load_frame("00", "000000")

    def test_absent_timestamp_is_never_generated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels" / "000000.label")
            (sequence / "poses.txt").write_text("1 0 0 0 0 1 0 0 0 0 1 0\n")

            frame = SemanticKITTIDataset(root).load_frame("00", "000000")

        self.assertIsNone(frame.timestamp)
        self.assertEqual(frame.provenance.timestamp_source, "absent")

    def test_rejects_nonfinite_dataset_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels" / "000000.label")
            (sequence / "times.txt").write_text("nan\n")

            with self.assertRaisesRegex(ValueError, "invalid timestamp"):
                SemanticKITTIDataset(root).load_frame("00", "000000")

    def test_world_frame_requires_dataset_pose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                sequence / "velodyne" / "000000.bin"
            )
            np.array([10], dtype=np.uint32).tofile(sequence / "labels" / "000000.label")

            frame = SemanticKITTIDataset(root).load_frame("00", "000000")

        self.assertEqual(frame.provenance.pose_source, "identity_absent")
        self.assertNotEqual(frame.provenance.coordinate_frame, "world")

    def test_partial_checkout_resolves_absolute_pose_and_timestamp_lines(self):
        # A partial scan checkout (middle frames missing on disk) must still
        # resolve the absolute poses.txt/times.txt lines named by the numeric
        # frame id, not the position inside list_frames.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = root / "sequences" / "00"
            (sequence / "velodyne").mkdir(parents=True)
            (sequence / "labels").mkdir()
            for frame_id in ("000000", "000002"):
                np.array([[1.0, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(
                    sequence / "velodyne" / f"{frame_id}.bin"
                )
                np.array([10], dtype=np.uint32).tofile(
                    sequence / "labels" / f"{frame_id}.label"
                )
            (sequence / "poses.txt").write_text(
                "1 0 0 0 0 1 0 0 0 0 1 0\n"
                "1 0 0 10 0 1 0 0 0 0 1 0\n"
                "1 0 0 20 0 1 0 0 0 0 1 0\n"
            )
            (sequence / "times.txt").write_text("0.0\n0.1\n0.2\n")

            adapter = SemanticKITTIDataset(root)
            frame = adapter.load_frame("00", "000002")
            self.assertAlmostEqual(frame.timestamp, 0.2)
            self.assertAlmostEqual(float(frame.pose.matrix[0, 3]), 20.0)
            replayed = list(adapter.replay("00", start=1, end=2))
            self.assertEqual([item.frame_id for item in replayed], ["000002"])
            self.assertAlmostEqual(replayed[0].timestamp, 0.2)
            self.assertAlmostEqual(float(replayed[0].pose.matrix[0, 3]), 20.0)

    def test_official_v11_taxonomy_ids_map_without_error(self):
        # Raw IDs from SemanticKITTI v1.1 `learning_map`, including the
        # moving classes 252-259 observed in the official sequence-08 labels.
        raw = np.array(sorted(SEMANTICKITTI_LABELS.keys()), dtype=np.uint32)
        mapped = map_dataset_labels(raw & 0xFFFF, SEMANTICKITTI_LABELS)
        for raw_id, veyra_id in zip(raw.tolist(), mapped.tolist()):
            self.assertEqual(veyra_id, SEMANTICKITTI_LABELS[int(raw_id)])
        unmapped = map_dataset_labels(np.array([2, 3, 7], dtype=np.uint32))
        np.testing.assert_array_equal(unmapped, [0, 0, 0])


# Rellis adapter


def write_rellis_frame(
    root: Path, sequence: str, frame_id: str, xs: list[float]
) -> None:
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
    def test_optional_labels_are_explicitly_unknown(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0])
            (
                root / "00000" / "vel_cloud_node_semantickitti_label_id" / "0.label"
            ).unlink()

            frame = Rellis3DDataset(root, require_labels=False).load_frame("00000", "0")

        np.testing.assert_array_equal(frame.semantic_class, [0])
        np.testing.assert_array_equal(frame.semantic_confidence, [0.0])
        self.assertEqual(frame.provenance.label_source, "absent")

    def test_reuses_one_explicit_sequence_index_for_frame_selection(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "10", [10.0])
            write_rellis_frame(root, "00000", "2", [2.0])
            adapter = Rellis3DDataset(root, sequences=["00000"])

            first = adapter.list_frames("00000")
            (root / "00000" / "vel_cloud_node_kitti_bin" / "99.bin").write_bytes(
                (root / "00000" / "vel_cloud_node_kitti_bin" / "10.bin").read_bytes()
            )

            self.assertEqual(
                [ref.frame_id for ref in adapter.list_frames("00000")], ["2", "10"]
            )
            self.assertIs(adapter.list_frames("00000"), first)

    def test_rejects_malformed_timestamp_and_pose_without_reparsing_each_frame(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0])
            (root / "timestamps").mkdir()
            (root / "timestamps" / "00000.txt").write_text("not-a-time\n")
            with self.assertRaisesRegex(ValueError, "invalid timestamp"):
                Rellis3DDataset(root).load_frame("00000", "0")

            (root / "timestamps" / "00000.txt").write_text("1.0\n")
            (root / "poses").mkdir()
            (root / "poses" / "00000.txt").write_text("1 0 0\n")
            with self.assertRaisesRegex(ValueError, "pose must contain 12 values"):
                Rellis3DDataset(root).load_frame("00000", "0")

    def test_metadata_cache_does_not_reread_cached_pose_text(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0])
            (root / "poses").mkdir()
            pose_path = root / "poses" / "00000.txt"
            pose_path.write_text("1 0 0 10 0 1 0 20 0 0 1 30\n")
            adapter = Rellis3DDataset(root)

            adapter.load_frame("00000", "0")
            pose_path.write_text("malformed\n")

            self.assertEqual(adapter.load_frame("00000", "0").frame_id, "0")

    def test_uses_the_versioned_rellis_learning_taxonomy(self):
        raw = np.array([0, 3, 4, 17, 18, 19, 23, 31, 33], dtype=np.uint32)

        mapped = map_dataset_labels(raw, RELLIS_LABELS)

        np.testing.assert_array_equal(mapped, [0, 15, 15, 6, 14, 15, 0, 0, 17])

    def test_reports_absent_metadata_without_claiming_world_coordinates(self):
        root = Path(__file__).parents[1] / "data/raw/rellis3d/Rellis-3D"
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
        self.assertEqual(mapped.tolist(), [15, 6, 0])

    def test_pairs_numeric_frames_and_extracts_low_16_labels(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "10", [10.0, 11.0])
            write_rellis_frame(root, "00000", "2", [2.0, 3.0])
            adapter = Rellis3DDataset(root, sequences=["00000"])

            self.assertEqual(
                [ref.frame_id for ref in adapter.list_frames("00000")], ["2", "10"]
            )
            frame = adapter.load_frame("00000", "2", label_mapping={10: 1, 20: 2})
            np.testing.assert_array_equal(frame.semantic_class, [1, 2])
            np.testing.assert_array_equal(frame.raw_semantic_class, [10, 20])

    def test_rejects_incomplete_scan_records_nonfinite_points_and_label_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0, 2.0])
            scan = root / "00000" / "vel_cloud_node_kitti_bin" / "0.bin"
            labels = (
                root / "00000" / "vel_cloud_node_semantickitti_label_id" / "0.label"
            )
            scan.write_bytes(b"123")
            labels.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "complete XYZ/intensity"):
                Rellis3DDataset(root).load_frame("00000", "0")

            np.array([[np.nan, 0.0, 0.0, 0.5]], dtype=np.float32).tofile(scan)
            np.array([10], dtype=np.uint32).tofile(labels)
            with self.assertRaisesRegex(ValueError, "non-finite"):
                Rellis3DDataset(root).load_frame("00000", "0")

            np.array(
                [[1.0, 0.0, 0.0, 0.5], [2.0, 0.0, 0.0, 0.5]], dtype=np.float32
            ).tofile(scan)
            np.array([10], dtype=np.uint32).tofile(labels)
            with self.assertRaisesRegex(ValueError, "length mismatch"):
                Rellis3DDataset(root).load_frame("00000", "0")

    def test_unknown_mapped_label_has_zero_semantic_confidence(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0, 2.0, 3.0])
            frame = Rellis3DDataset(root).load_frame(
                "00000", "0", label_mapping={10: 1, 20: 2}
            )

            np.testing.assert_array_equal(frame.semantic_class, [1, 2, 0])
            np.testing.assert_array_equal(frame.semantic_confidence, [1.0, 1.0, 0.0])

    def test_uses_explicit_metadata_root_and_rejects_unmatched_pose_rows(self):
        with (
            tempfile.TemporaryDirectory() as raw,
            tempfile.TemporaryDirectory() as metadata,
        ):
            root = Path(raw)
            metadata_root = Path(metadata)
            write_rellis_frame(root, "00000", "0", [1.0])
            sequence_metadata = metadata_root / "00000"
            sequence_metadata.mkdir()
            (sequence_metadata / "poses.txt").write_text(
                "1 0 0 0 0 1 0 0 0 0 1 0\n1 0 0 1 0 1 0 0 0 0 1 0\n"
            )
            (sequence_metadata / "calib.txt").write_text(
                "P0: 1 0 0 0 0 1 0 0 0 0 1 0\n"
                "P1: 1 0 0 0 0 1 0 0 0 0 1 0\n"
                "P2: 1 0 0 0 0 1 0 0 0 0 1 0\n"
                "P3: 1 0 0 0 0 1 0 0 0 0 1 0\n"
                "Tr: 1 0 0 0 0 1 0 0 0 0 1 0\n"
            )

            adapter = Rellis3DDataset(root, metadata_root=metadata_root)
            with self.assertRaisesRegex(ValueError, "cannot be aligned"):
                adapter.load_frame("00000", "0")

    def test_applies_pose_and_validates_camera_calibration_without_composing_it(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0])
            (root / "poses").mkdir()
            (root / "poses" / "00000.txt").write_text("1 0 0 10  0 1 0 20  0 0 1 30\n")
            (root / "calib").mkdir()
            (root / "calib" / "00000.txt").write_text(
                "Tr_velo_to_cam: 1 0 0 1  0 1 0 2  0 0 1 3\n"
            )

            frame = Rellis3DDataset(root).load_frame("00000", "0")

            np.testing.assert_allclose(frame.points[0, :3], [11.0, 20.0, 30.0])
            self.assertEqual(frame.pose.matrix[0, 3], 10.0)

    def test_uses_identity_pose_when_metadata_is_absent(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0])

            frame = Rellis3DDataset(root).load_frame("00000", "0")

            np.testing.assert_allclose(frame.points[0, :3], [1.0, 0.0, 0.0])
            np.testing.assert_allclose(frame.pose.matrix, np.eye(4))
            self.assertIsNone(frame.timestamp)

    def test_range_filter_and_replay_are_bounded_and_deterministic(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "2", [2.0, 101.0])
            write_rellis_frame(root, "00000", "10", [10.0, 11.0])
            adapter = Rellis3DDataset(root, sequences=["00000"])

            first = list(adapter.replay("00000", max_range_m=100.0))
            second = list(adapter.replay("00000", max_range_m=100.0))

            self.assertEqual([frame.frame_id for frame in first], ["2", "10"])
            self.assertEqual([frame.points.shape[0] for frame in first], [1, 2])
            for left, right in zip(first, second):
                np.testing.assert_array_equal(left.points, right.points)
                np.testing.assert_array_equal(left.semantic_class, right.semantic_class)

    def test_malformed_paths_report_useful_reason(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            missing = root / "does-not-exist"
            with self.assertRaisesRegex(FileNotFoundError, "root does not exist"):
                Rellis3DDataset(missing)

            (root / "00000").mkdir()
            with self.assertRaisesRegex(FileNotFoundError, "scan directory"):
                Rellis3DDataset(root).list_frames("00000")

            write_rellis_frame(root, "00000", "0", [1.0])
            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                Rellis3DDataset(root).load_frame("00000", "no-such-frame")

            (
                root / "00000" / "vel_cloud_node_semantickitti_label_id" / "0.label"
            ).unlink()
            with self.assertRaisesRegex(FileNotFoundError, "label file is missing"):
                Rellis3DDataset(root, require_labels=True).load_frame("00000", "0")

    def test_discovery_rejects_unmatched_label_files_before_replay(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0])
            labels = root / "00000" / "vel_cloud_node_semantickitti_label_id"
            np.array([10], dtype=np.uint32).tofile(labels / "000001.label")

            with self.assertRaisesRegex(ValueError, "label has no matching scan"):
                Rellis3DDataset(root).list_frames("00000")

    def test_rejects_label_files_with_trailing_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_rellis_frame(root, "00000", "0", [1.0])
            labels = (
                root / "00000" / "vel_cloud_node_semantickitti_label_id" / "0.label"
            )
            labels.write_bytes(labels.read_bytes() + b"x")

            with self.assertRaisesRegex(ValueError, "complete uint32 label records"):
                Rellis3DDataset(root).load_frame("00000", "0")


if __name__ == "__main__":
    unittest.main()
