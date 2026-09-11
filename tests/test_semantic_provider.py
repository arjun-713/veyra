import unittest

import numpy as np

from perception.semantic.semantic_provider import (
    GroundTruthSemanticProvider,
    OnnxSemanticProvider,
    SemanticProviderConfigurationError,
    SemanticResult,
)


class SemanticProviderTests(unittest.TestCase):
    def test_rejects_invalid_classes_before_integer_conversion(self):
        for value in (-1, 1.5, np.nan, np.inf, 2**32):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SemanticResult(np.array([value]), np.ones(1), "model")
                with self.assertRaises(ValueError):
                    GroundTruthSemanticProvider().infer(np.array([value]))

    def test_unknown_confidence_normalization_cannot_hide_invalid_probability(self):
        for value in (np.nan, np.inf, -0.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SemanticResult(np.array([0]), np.array([value]), "model")

    def test_onnx_rejects_fractional_raw_class_instead_of_truncating(self):
        session = _Session(
            input_shape=[None, 4],
            output_shapes=[[1], [1]],
            outputs=([7.5], [0.9]),
        )
        with self.assertRaises(ValueError):
            OnnxSemanticProvider(session=session, mapping={7: 3}).infer(
                np.zeros((1, 4), dtype=np.float32)
            )

    def test_ground_truth_unknown_has_no_semantic_confidence(self):
        result = GroundTruthSemanticProvider().infer(np.array([0, 9]))
        np.testing.assert_array_equal(result.semantic_class, [0, 9])
        np.testing.assert_array_equal(result.semantic_confidence, [0.0, 1.0])

    def test_ground_truth_preserves_mapped_labels_and_assigns_confidence_one(self):
        labels = np.array([7, 2, 7], dtype=np.int32)

        result = GroundTruthSemanticProvider().infer(labels)

        np.testing.assert_array_equal(result.semantic_class, labels)
        np.testing.assert_array_equal(
            result.semantic_confidence, np.ones(labels.size, dtype=np.float32)
        )
        self.assertEqual(result.mode, "ground_truth")

    def test_ground_truth_rejects_non_one_dimensional_labels(self):
        with self.assertRaises(ValueError):
            GroundTruthSemanticProvider().infer(np.zeros((2, 2), dtype=np.int32))

    def test_onnx_requires_explicit_session(self):
        with self.assertRaises(SemanticProviderConfigurationError):
            OnnxSemanticProvider(mapping={1: 11})

    def test_onnx_model_path_requires_the_installed_runtime_without_downloading(self):
        with self.assertRaises(SemanticProviderConfigurationError):
            OnnxSemanticProvider.from_model_path("missing-model.onnx", mapping={1: 11})

    def test_onnx_rejects_static_input_that_is_not_xyzi(self):
        session = _Session(input_shape=[1, 3], output_shapes=[[1], [1]])

        with self.assertRaises(SemanticProviderConfigurationError):
            OnnxSemanticProvider(session=session, mapping={1: 11})

    def test_onnx_maps_a_real_session_result_without_using_ground_truth_labels(self):
        session = _Session(
            input_shape=[None, 4],
            output_shapes=[[None], [None]],
            outputs=([7, 99], [0.75, 0.25]),
        )
        provider = OnnxSemanticProvider(session=session, mapping={7: 3})

        result = provider.infer(
            np.zeros((2, 4), dtype=np.float32), labels=np.array([1, 1])
        )

        np.testing.assert_array_equal(result.semantic_class, [3, 0])
        np.testing.assert_allclose(result.semantic_confidence, [0.75, 0.0])
        self.assertEqual(result.mode, "model")

    def test_onnx_rejects_output_not_aligned_to_points(self):
        session = _Session(
            input_shape=[None, 4],
            output_shapes=[[2], [2]],
            outputs=([1, 1], [1.0, 1.0]),
        )
        provider = OnnxSemanticProvider(session=session, mapping={1: 11})

        with self.assertRaises(ValueError):
            provider.infer(np.zeros((3, 4), dtype=np.float32))

    def test_onnx_rejects_nonfinite_point_input(self):
        session = _Session(input_shape=[None, 4], output_shapes=[[1], [1]])
        provider = OnnxSemanticProvider(session=session, mapping={1: 11})
        points = np.zeros((1, 4), dtype=np.float32)
        points[0, 0] = np.nan
        with self.assertRaises(ValueError):
            provider.infer(points)


class _ValueInfo:
    def __init__(self, shape):
        self.name = "tensor"
        self.shape = shape


class _Session:
    def __init__(self, input_shape, output_shapes, outputs=None):
        self._input = _ValueInfo(input_shape)
        self._outputs = [_ValueInfo(shape) for shape in output_shapes]
        self._values = outputs

    def get_inputs(self):
        return [self._input]

    def get_outputs(self):
        return self._outputs

    def run(self, output_names, feed):
        return self._values or ([1], [1.0])


if __name__ == "__main__":
    unittest.main()
