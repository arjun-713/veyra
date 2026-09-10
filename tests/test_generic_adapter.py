import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.generic.adapter import ManifestDataset


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
        self.assertIsNone(
            frame.provenance.label_source
            if hasattr(frame.provenance, "label_source")
            else None
        )

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


if __name__ == "__main__":
    unittest.main()
