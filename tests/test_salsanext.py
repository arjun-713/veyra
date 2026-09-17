import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from perception.semantic.salsanext import (
    SalsaNextSemanticProvider,
    model_contract,
    project_scan,
    unproject_scores,
)


_REPO = Path(__file__).parents[1]
_DEFAULT_MODEL = _REPO / "data/cache/models/salsanext-onnx-float/salsanext.onnx"
_REAL_MODEL = Path(os.environ.get("VEYRA_SALSANEXT_MODEL", _DEFAULT_MODEL))
_REAL_SEMANTICPOSS = _REPO / "data/raw/semanticposs/dataset"


class SalsaNextTests(unittest.TestCase):
    def test_pinned_contract_matches_upstream_salsanext_sensor_and_learning_ids(self):
        contract = model_contract()
        self.assertEqual(contract["image_shape"], (64, 2048))
        self.assertEqual(contract["fov_degrees"], {"up": 3.0, "down": -25.0})
        self.assertEqual(len(contract["learning_classes"]), 20)
        self.assertEqual(contract["learning_classes"][1], "car")
        self.assertEqual(contract["learning_classes"][18], "pole")

    def test_provider_declares_semantickitti_dataset_capability(self):
        self.assertEqual(
            SalsaNextSemanticProvider.supported_datasets, frozenset({"semantickitti"})
        )

    def test_projection_uses_nearest_return_and_keeps_first_point(self):
        points = np.array(
            [[10, 0, 0, 0.2], [20, 0, 0, 0.8], [0, 10, 0, 0.4]], np.float32
        )
        tensor, rows, cols, valid = project_scan(points)
        self.assertEqual(tensor.shape, (1, 5, 64, 2048))
        np.testing.assert_array_equal(cols, [1024, 1024, 512])
        np.testing.assert_array_equal(rows, [6, 6, 6])
        self.assertTrue(valid.all())
        self.assertAlmostEqual(
            float(tensor[0, 0, 6, 1024]), (10 - 12.12) / 12.32, places=6
        )
        self.assertAlmostEqual(
            float(tensor[0, 4, 6, 1024]), (0.2 - 0.21) / 0.16, places=6
        )
        self.assertTrue(np.all(tensor[:, :, 0, 0] == 0))

    def test_out_of_fov_and_zero_returns_are_unknown(self):
        points = np.array([[0, 0, 0, 0], [1, 0, 2, 0.5], [10, 0, -1, 0.5]], np.float32)
        _, rows, cols, valid = project_scan(points)
        np.testing.assert_array_equal(valid, [False, False, True])
        scores = np.zeros((1, 20, 64, 2048), np.float32)
        scores[:, 6] = 0.75
        scores[:, 9] = 0.25
        result = unproject_scores(scores, rows, cols, valid)
        np.testing.assert_array_equal(result.semantic_class, [0, 0, 6])
        np.testing.assert_allclose(result.semantic_confidence, [0, 0, 0.75])

    def test_unprojection_preserves_order_and_probabilities_without_second_softmax(
        self,
    ):
        scores = np.zeros((1, 20, 64, 2048), np.float32)
        scores[:, 0] = 1
        scores[0, 0, 1, 2] = 0
        scores[0, 7, 1, 2] = 0.9
        scores[0, 9, 1, 2] = 0.1
        result = unproject_scores(
            scores, np.array([1, 0, 1]), np.array([2, 0, 2]), np.ones(3, bool)
        )
        np.testing.assert_array_equal(result.semantic_class, [7, 0, 7])
        np.testing.assert_allclose(result.semantic_confidence, [0.9, 0, 0.9])

    def test_invalid_probability_outputs_fail(self):
        for value in (np.nan, np.inf, -1.0, 2.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                unproject_scores(
                    np.full((1, 20, 64, 2048), value, np.float32),
                    np.array([0]),
                    np.array([0]),
                    np.array([True]),
                )

    def test_invalid_scan_fails_before_inference(self):
        for points in (np.zeros((3, 3)), np.array([[np.nan, 0, 0, 1]])):
            with self.assertRaises(ValueError):
                project_scan(points)

    def test_intensity_scale_is_explicit_and_normalized(self):
        points = np.array([[10, 0, 0, 51]], np.float32)
        with self.assertRaises(ValueError):
            project_scan(points)
        tensor, rows, cols, _ = project_scan(points, intensity_scale=255)
        self.assertAlmostEqual(
            float(tensor[0, 4, rows[0], cols[0]]), (0.2 - 0.21) / 0.16, places=6
        )

    def test_invalid_model_is_rejected_by_real_runtime(self):
        if importlib.util.find_spec("onnxruntime") is None:
            self.skipTest("requires onnxruntime for ONNX model validation")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.onnx"
            path.write_bytes(b"not an onnx model")
            with self.assertRaises(ValueError):
                SalsaNextSemanticProvider(path)

    def test_semanticposs_is_not_presented_as_a_salsanext_quality_path(self):
        self.assertNotIn("semanticposs", SalsaNextSemanticProvider.supported_datasets)


if __name__ == "__main__":
    unittest.main()
