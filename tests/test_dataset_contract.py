"""Dataset contract regression suite."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.common.observation import (
    FrameProvenance,
    ObservationFrame,
    PoseSE3,
)
from datasets.common.taxonomy import PANDASET_LABELS, RELLIS_LABELS, map_dataset_labels
from datasets.generic import ManifestDataset as PandaSetManifestDataset
from datasets.generic.adapter import ManifestDataset
from datasets.pandaset.convert import (
    beam_origin_pose,
    convert,
    pose_matrix,
    world_to_sensor,
)
from scripts.validate_dataset_capabilities import build_report

# Generic adapter


def _manifest(root: Path, frames, *, mapping=None):
    data = {
        "schema_version": 1,
        "dataset": "fixture",
        "point_schema": {
            "format": "xyzi",
            "coordinate_frame": "sensor",
            "intensity_semantics": "reflectance",
        },
        "taxonomy": {
            "version": "fixture-v1",
            "mapping": mapping if mapping is not None else {"10": 1, "20": 2},
        },
        "frames": frames,
    }
    (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")


class GenericManifestAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "points").mkdir()
        points = np.array(
            [[1, 0, 0, 0.5], [100, 0, 0, 0.7], [0, 2, 0, 0.9]], dtype=np.float32
        )
        points.tofile(self.root / "points" / "a.bin")
        np.save(self.root / "points" / "b.npy", points)
        np.array([10, 20, 99], dtype=np.uint32).tofile(self.root / "labels.label")
        np.save(self.root / "labels.npy", np.array([10, 20, 99], dtype=np.int32))

    def tearDown(self):
        self.tmp.cleanup()

    def frame(
        self,
        sequence="s",
        frame_id="000001",
        point="points/a.bin",
        point_format="xyzi_f32_bin",
        labels="labels.label",
        label_format="uint32_label",
    ):
        item = {
            "sequence": sequence,
            "frame_id": frame_id,
            "points": {"path": point, "format": point_format},
        }
        if labels is not None:
            item["labels"] = {"path": labels, "format": label_format}
        return item

    def test_requires_schema_taxonomy_and_point_convention(self):
        _manifest(self.root, [self.frame()])
        data = json.loads((self.root / "manifest.json").read_text())
        data.pop("schema_version", None)
        (self.root / "manifest.json").write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            ManifestDataset(self.root)

    def test_duplicate_ids_and_deterministic_order_are_rejected_and_explicit(self):
        _manifest(self.root, [self.frame(frame_id="b"), self.frame(frame_id="a")])
        dataset = ManifestDataset(self.root)
        self.assertEqual([f.frame_id for f in dataset.list_frames("s")], ["a", "b"])
        _manifest(self.root, [self.frame(), self.frame()])
        with self.assertRaises(ValueError):
            ManifestDataset(self.root)

    def test_safe_paths_are_relative_to_root(self):
        _manifest(self.root, [self.frame(point="../escape.bin")])
        with self.assertRaises(ValueError):
            ManifestDataset(self.root)

    def test_bin_labels_map_unknown_to_zero_with_zero_confidence_and_preserve_raw(self):
        _manifest(self.root, [self.frame()])
        frame = ManifestDataset(self.root).load_frame("s", "000001")
        np.testing.assert_array_equal(frame.semantic_class, [1, 2, 0])
        np.testing.assert_array_equal(frame.semantic_confidence, [1, 1, 0])
        np.testing.assert_array_equal(frame.raw_semantic_class, [10, 20, 99])

    def test_npy_formats_are_supported_without_pickle(self):
        _manifest(
            self.root,
            [
                self.frame(
                    point="points/b.npy",
                    point_format="xyzi_f32_npy",
                    labels="labels.npy",
                    label_format="integer_npy",
                )
            ],
        )
        frame = ManifestDataset(self.root).load_frame("s", "000001")
        np.testing.assert_allclose(
            frame.points, np.load(self.root / "points" / "b.npy", allow_pickle=False)
        )
        bad = np.array([{"x": 1}], dtype=object)
        np.save(self.root / "bad.npy", bad)
        _manifest(
            self.root,
            [self.frame(point="bad.npy", point_format="xyzi_f32_npy", labels=None)],
        )
        with self.assertRaises(ValueError):
            ManifestDataset(self.root).load_frame("s", "000001")

    def test_missing_labels_are_unknown_not_ground_truth(self):
        _manifest(self.root, [self.frame(labels=None)])
        frame = ManifestDataset(self.root).load_frame("s", "000001")
        np.testing.assert_array_equal(frame.semantic_class, np.zeros(3, dtype=np.int32))
        np.testing.assert_array_equal(
            frame.semantic_confidence, np.zeros(3, dtype=np.int32)
        )
        self.assertEqual(frame.provenance.label_source, "absent")

    def test_pose_timestamp_and_sensor_range_filter(self):
        item = self.frame()
        item["timestamp_s"] = 12.5
        item["pose_sensor_to_world"] = [
            [1, 0, 0, 10],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ]
        _manifest(self.root, [item])
        frame = ManifestDataset(self.root).load_frame("s", "000001", max_range_m=2.1)
        self.assertEqual(frame.points.shape[0], 2)
        np.testing.assert_allclose(frame.points[:, 0], [11, 10], atol=1e-6)
        self.assertEqual(frame.timestamp, 12.5)
        self.assertEqual(frame.provenance.pose_source, "dataset")

    def test_malformed_nonfinite_and_unaligned_inputs_fail(self):
        bad = np.array([[np.nan, 0, 0, 1]], dtype=np.float32)
        bad.tofile(self.root / "nan.bin")
        _manifest(self.root, [self.frame(point="nan.bin", labels=None)])
        with self.assertRaises(ValueError):
            ManifestDataset(self.root).load_frame("s", "000001")

        np.array([10], dtype=np.uint32).tofile(self.root / "short.label")
        _manifest(
            self.root,
            [self.frame(point="points/a.bin", labels="short.label")],
        )
        with self.assertRaisesRegex(ValueError, "one non-negative integer"):
            ManifestDataset(self.root).load_frame("s", "000001")
        (self.root / "odd.bin").write_bytes(b"123")
        _manifest(self.root, [self.frame(point="odd.bin", labels=None)])
        with self.assertRaises(ValueError):
            ManifestDataset(self.root).load_frame("s", "000001")

    def test_replay_rejects_bad_ranges_and_does_not_rescan_manifest(self):
        _manifest(self.root, [self.frame(frame_id="0"), self.frame(frame_id="1")])
        dataset = ManifestDataset(self.root)
        (self.root / "manifest.json").write_text("not json")
        self.assertEqual([f.frame_id for f in dataset.list_frames("s")], ["0", "1"])
        with self.assertRaises(ValueError):
            list(dataset.replay("s", start=-1))
        with self.assertRaises(ValueError):
            list(dataset.replay("s", stride=0))

    def test_real_local_semanticposs_frame_can_be_manifest_loaded(self):
        root = Path("data/raw/semanticposs/dataset")
        scan = root / "sequences/00/velodyne/000000.bin"
        label = root / "sequences/00/labels/000000.label"
        pose_file = root / "sequences/00/poses.txt"
        if not (scan.exists() and label.exists() and pose_file.exists()):
            self.skipTest("local SemanticPOSS frame unavailable")
        pose = np.loadtxt(pose_file, dtype=np.float64)[0].reshape(3, 4)
        matrix = np.eye(4)
        matrix[:3, :] = pose
        data = {
            "schema_version": 1,
            "dataset": "local-semanticposs",
            "point_schema": {
                "format": "xyzi",
                "coordinate_frame": "sensor",
                "intensity_semantics": "reflectance",
            },
            "taxonomy": {"version": "local-proof", "mapping": {}},
            "frames": [
                {
                    "sequence": "00",
                    "frame_id": "000000",
                    "points": {
                        "path": "sequences/00/velodyne/000000.bin",
                        "format": "xyzi_f32_bin",
                    },
                    "labels": {
                        "path": "sequences/00/labels/000000.label",
                        "format": "uint32_label",
                    },
                    "pose_sensor_to_world": matrix.tolist(),
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(data, handle)
            manifest = Path(handle.name)
        try:
            frame = ManifestDataset(root, manifest).load_frame("00", "000000")
            self.assertGreater(frame.points.shape[0], 0)
            self.assertEqual(frame.provenance.pose_source, "dataset")
            self.assertIsNone(frame.timestamp)
        finally:
            manifest.unlink(missing_ok=True)


# Dataset validation


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


# Pandaset convert

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

            frame = PandaSetManifestDataset(output).load_frame("007", "00")
            # The PandarGT return (d=1) is excluded; world geometry round-trips.
            np.testing.assert_allclose(frame.points[:, :3], world[:2], atol=1e-4)
            np.testing.assert_allclose(frame.points[:, 3], [5.0, 200.0])
            self.assertEqual(frame.semantic_class.tolist(), [9, 13])  # road, building
            self.assertEqual(frame.provenance.coordinate_frame, "world")
            self.assertAlmostEqual(frame.timestamp, 1557540585.3)


# Observation contract


class ObservationContractTests(unittest.TestCase):
    def test_probabilities_reject_nan_and_geometry_rejects_infinity(self):
        for name in ("semantic_confidence", "motion_probability"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _frame(**{name: [np.nan, 0.5]})
        for name in ("slope", "roughness", "height_complexity", "step"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _frame(**{name: [np.inf, 0.0]})
        # NaN remains the documented representation for uncomputed geometry.
        self.assertTrue(np.isnan(_frame(slope=[np.nan, np.nan]).slope).all())

    def test_semantic_classes_must_not_silently_truncate(self):
        with self.assertRaises(ValueError):
            _frame(semantic_class=[1.5, 2])
        with self.assertRaises(ValueError):
            _frame(raw_semantic_class=[1.5, 2])

    def test_observation_frame_keeps_all_point_fields_aligned(self):
        pose = PoseSE3(np.eye(4), timestamp=1.25)
        points = np.array(
            [[1.0, 2.0, 3.0, 0.5], [4.0, 5.0, 6.0, 0.75]], dtype=np.float32
        )

        frame = ObservationFrame(
            timestamp=1.25,
            pose=pose,
            points=points,
            semantic_class=np.array([3, 4], dtype=np.int32),
            semantic_confidence=np.array([1.0, 0.8], dtype=np.float32),
            ground=np.array([True, False]),
            drivable=np.array(["drivable", "unknown"]),
            slope=np.array([0.1, 0.2], dtype=np.float32),
            roughness=np.array([0.01, 0.04], dtype=np.float32),
            height_complexity=np.array([0.0, 0.5], dtype=np.float32),
            motion_probability=np.array([0.0, 0.25], dtype=np.float32),
            velocity_xy=np.array([[0.0, 0.0], [1.0, 2.0]], dtype=np.float32),
        )

        self.assertEqual(frame.points.shape, (2, 4))
        self.assertEqual(frame.semantic_class.shape, (2,))
        self.assertEqual(frame.velocity_xy.shape, (2, 2))
        np.testing.assert_array_equal(frame.semantic_class, [3, 4])

    def test_ground_gradients_are_aligned_and_missing_gradient_is_nan(self):
        value = _frame(ground_gradient_x=[0.25, -0.5], ground_gradient_y=[0.1, 0.2])
        np.testing.assert_array_equal(value.ground_gradient_x, [0.25, -0.5])
        np.testing.assert_allclose(
            value.ground_gradient_y, [0.1, 0.2], rtol=0.0, atol=1e-7
        )
        self.assertTrue(np.isnan(_frame().ground_gradient_x).all())
        with self.assertRaisesRegex(ValueError, "optional ObservationFrame fields"):
            _frame(ground_gradient_x=[0.1])
        with self.assertRaisesRegex(
            ValueError, "ground_gradient_x must be finite or NaN"
        ):
            _frame(ground_gradient_x=[np.inf, 0.0])

    def test_pose_and_frame_timestamp_contracts(self):
        scaled = np.eye(4)
        scaled[0, 0] = 2.0
        for matrix in (np.eye(3), scaled):
            with self.subTest(matrix=matrix.tolist()), self.assertRaises(ValueError):
                PoseSE3(matrix)
        with self.assertRaises(ValueError):
            PoseSE3.identity(timestamp=float("nan"))
        with self.assertRaises(ValueError):
            _frame(timestamp=float("inf"))

    def test_observation_rejects_invalid_states_and_freezes_arrays(self):
        with self.assertRaises(ValueError):
            _frame(drivable=["maybe", "unknown"])
        with self.assertRaises(ValueError):
            _frame(motion_state=["static", "flying"])

        frame = _frame()
        with self.assertRaises(ValueError):
            frame.points[0, 0] = 99.0

    def test_observation_preserves_raw_labels_separately_from_mapped_labels(self):
        frame = _frame(
            raw_semantic_class=np.array([42, 7], dtype=np.int32),
            semantic_class=np.array([3, 1], dtype=np.int32),
        )

        np.testing.assert_array_equal(frame.raw_semantic_class, [42, 7])
        np.testing.assert_array_equal(frame.semantic_class, [3, 1])
        with self.assertRaises(ValueError):
            frame.raw_semantic_class[0] = 99

    def test_observation_preserves_optional_instance_ids_without_aliasing_semantics(
        self,
    ):
        frame = _frame(
            raw_semantic_class=np.array([42, 7], dtype=np.int32),
            semantic_class=np.array([3, 1], dtype=np.int32),
            instance_id=np.array([12, 0], dtype=np.int32),
        )

        np.testing.assert_array_equal(frame.instance_id, [12, 0])
        np.testing.assert_array_equal(frame.raw_semantic_class, [42, 7])
        with self.assertRaises(ValueError):
            frame.instance_id[0] = 99

    def test_observation_rejects_nan_point_coordinates(self):
        points = np.zeros((2, 4), dtype=np.float32)
        points[1, 2] = np.nan

        with self.assertRaises(ValueError):
            _frame(points=points)

    def test_metadata_provenance_makes_missing_sources_explicit(self):
        frame = _frame(
            timestamp=None,
            provenance=FrameProvenance(
                coordinate_frame="lidar",
                timestamp_source="absent",
                pose_source="identity_absent",
                calibration_source="identity_absent",
            ),
        )

        self.assertEqual(frame.provenance.coordinate_frame, "lidar")
        self.assertEqual(frame.provenance.timestamp_source, "absent")

    def test_height_complexity_rejects_unbounded_map_evidence(self):
        with self.assertRaises(ValueError):
            ObservationFrame(
                timestamp=1.0,
                pose=PoseSE3.identity(timestamp=1.0),
                points=np.zeros((1, 4), dtype=np.float32),
                semantic_class=np.array([1]),
                semantic_confidence=np.array([1.0]),
                ground=np.array([True]),
                drivable=np.array(["drivable"]),
                slope=np.array([0.0]),
                roughness=np.array([0.0]),
                height_complexity=np.array([1.01]),
                motion_probability=np.array([0.0]),
                velocity_xy=np.zeros((1, 2)),
            )


def _frame(**overrides):
    values = {
        "timestamp": 1.0,
        "pose": PoseSE3.identity(timestamp=1.0),
        "points": np.zeros((2, 4), dtype=np.float32),
        "semantic_class": np.zeros(2, dtype=np.int32),
        "semantic_confidence": np.ones(2, dtype=np.float32),
        "ground": np.zeros(2, dtype=bool),
        "drivable": np.full(2, "unknown"),
        "slope": np.zeros(2, dtype=np.float32),
        "roughness": np.zeros(2, dtype=np.float32),
        "height_complexity": np.zeros(2, dtype=np.float32),
        "motion_probability": np.zeros(2, dtype=np.float32),
        "velocity_xy": np.zeros((2, 2), dtype=np.float32),
        "motion_state": np.full(2, "unknown"),
    }
    values.update(overrides)
    return ObservationFrame(**values)


# Taxonomy


class TaxonomyTests(unittest.TestCase):
    def test_rellis_maps_by_class_meaning_into_veyra_space(self):
        # RELLIS raw IDs from the upstream labels file.  The expected values
        # are Veyra SemanticKITTI-learning IDs, not RELLIS learning IDs.
        raw = np.array([3, 4, 5, 6, 8, 10, 12, 15, 17, 18, 19, 33], dtype=np.uint16)

        mapped = map_dataset_labels(raw, RELLIS_LABELS)

        np.testing.assert_array_equal(
            mapped, [15, 15, 18, 0, 5, 9, 13, 16, 6, 14, 15, 17]
        )

    def test_mapping_preserves_shape_contract_and_handles_large_ids_without_lut(self):
        raw = np.array([[3, 2**63 - 1], [-7, 999999999999]], dtype=np.int64)

        mapped = map_dataset_labels(raw, {3: 15})

        self.assertEqual(mapped.dtype, np.int32)
        self.assertEqual(mapped.shape, (4,))
        np.testing.assert_array_equal(mapped, [15, 0, 0, 0])

    def test_mapping_rejects_non_integral_or_non_numeric_labels(self):
        for labels in (np.array([1.5]), np.array([np.nan]), np.array(["3"])):
            with (
                self.subTest(labels=labels),
                self.assertRaises((TypeError, ValueError)),
            ):
                map_dataset_labels(labels, {3: 15})


if __name__ == "__main__":
    unittest.main()
