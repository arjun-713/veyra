import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from scripts.fetch_semantic_model import fetch
from scripts.validate_perception import (
    confusion_report,
    latency_summary,
    reproducibility_metadata,
)


class PerceptionValidationTests(unittest.TestCase):
    def test_reproducibility_metadata_records_selection_and_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "perception.yaml"
            model = root / "model.onnx"
            config.write_text("semantic:\n  model_path: model.onnx\n")
            model.write_bytes(b"model")
            config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
            metadata = reproducibility_metadata(
                repo=root,
                config_path=config,
                config_data={"semantic": {"model_path": "model.onnx"}},
                dataset_sha256="a" * 64,
                sequence="00",
                start=4,
                count=64,
            )
        self.assertEqual(
            metadata["frame_range"],
            {"sequence": "00", "start": 4, "end_exclusive": 68, "count": 64},
        )
        self.assertEqual(metadata["dataset_sha256"], "a" * 64)
        self.assertEqual(metadata["config_sha256"], config_sha)
        self.assertEqual(
            metadata["model_checkpoint_sha256"], hashlib.sha256(b"model").hexdigest()
        )
        self.assertIn("cpu", metadata["runner"])

    def test_range_metrics_include_wrong_unknown_predictions(self):
        matrix = np.zeros((20, 20), np.int64)
        matrix[1, 1], matrix[1, 0], matrix[9, 1], matrix[9, 9] = 2, 1, 1, 2
        report = confusion_report(matrix)
        self.assertEqual(report["evaluated_points"], 6)
        self.assertAlmostEqual(report["accuracy"], 4 / 6)
        self.assertAlmostEqual(report["mean_iou"], (2 / 4 + 2 / 3) / 2)
        self.assertIsNone(confusion_report(np.zeros((20, 20)))["accuracy"])

    def test_latency_tails_and_invalid_samples(self):
        report = latency_summary([1, 2, 3, 4, 10])
        self.assertEqual(report["p50_ms"], 3)
        self.assertEqual(report["max_ms"], 10)
        self.assertAlmostEqual(report["p95_ms"], 8.8)
        for values in ([], [np.nan], [-1]):
            with self.assertRaises(ValueError):
                latency_summary(values)

    def test_asset_fetch_checks_archive_and_extracted_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "asset.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("model/model.onnx", b"test-only payload")
            manifest = {
                "url": archive.as_uri(),
                "size_bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "model": "model/model.onnx",
                "files": {
                    "model/model.onnx": hashlib.sha256(b"test-only payload").hexdigest()
                },
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            self.assertEqual(
                fetch(root / "download", path).read_bytes(), b"test-only payload"
            )
            manifest["files"]["model/model.onnx"] = "0" * 64
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                fetch(root / "bad", path)


if __name__ == "__main__":
    unittest.main()
