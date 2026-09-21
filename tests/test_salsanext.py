import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from perception.semantic.salsanext import (
    _FOV_DOWN_DEGREES,
    _FOV_UP_DEGREES,
    _IMAGE_HEIGHT,
    _IMAGE_WIDTH,
    _LEARNING_CLASSES,
    SalsaNextSemanticProvider,
    model_contract,
    project_scan,
    unproject_scores,
)

_REPO = Path(__file__).parents[1]
_DEFAULT_MODEL = _REPO / "data/cache/models/salsanext-onnx-float/salsanext.onnx"
_REAL_MODEL = Path(os.environ.get("VEYRA_SALSANEXT_MODEL", _DEFAULT_MODEL))
_REAL_SEMANTICPOSS = Path(
    os.environ.get("VEYRA_SEMANTICPOSS_ROOT", _REPO / "data/raw/semanticposs/dataset")
)


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

    # --- Geometry/taxonomy verification (closure: semantic correctness) ---

    @staticmethod
    def _upstream_pixel(points):
        """Independent transcription of TiagoCortinhal/SalsaNext
        ``train/common/laserscan.py::do_range_projection`` (MIT).

        Returns clamped (row, col) per point without any validity mask;
        upstream clamps out-of-FOV points to edge rows instead of rejecting
        them, and assigns pixels far-to-near so the nearest return wins.
        """
        fov_up = np.deg2rad(_FOV_UP_DEGREES)
        fov_down = np.deg2rad(_FOV_DOWN_DEGREES)
        fov = abs(fov_up) + abs(fov_down)
        depth = np.linalg.norm(points[:, :3], axis=1)
        yaw = -np.arctan2(points[:, 1], points[:, 0])
        with np.errstate(invalid="ignore", divide="ignore"):
            pitch = np.arcsin(np.clip(points[:, 2] / np.maximum(depth, 1e-12), -1, 1))
        cols = np.clip(
            np.floor(0.5 * (yaw / np.pi + 1.0) * _IMAGE_WIDTH), 0, _IMAGE_WIDTH - 1
        ).astype(np.intp)
        rows = np.clip(
            np.floor((1.0 - (pitch + abs(fov_down)) / fov) * _IMAGE_HEIGHT),
            0,
            _IMAGE_HEIGHT - 1,
        ).astype(np.intp)
        return rows, cols, depth

    def test_projection_matches_upstream_salsanext_formulas(self):
        rng = np.random.default_rng(26053)
        radius = rng.uniform(2, 60, size=500)
        yaw = rng.uniform(-np.pi, np.pi, size=500)
        pitch = rng.uniform(
            np.deg2rad(_FOV_DOWN_DEGREES + 0.05),
            np.deg2rad(_FOV_UP_DEGREES - 0.05),
            size=500,
        )
        points = np.column_stack(
            [
                radius * np.cos(pitch) * np.cos(yaw),
                -radius * np.cos(pitch) * np.sin(yaw),
                radius * np.sin(pitch),
                rng.uniform(0, 1, size=500),
            ]
        ).astype(np.float32)
        tensor, rows, cols, valid = project_scan(points)
        expected_rows, expected_cols, depth = self._upstream_pixel(points)
        self.assertTrue(valid.all())
        np.testing.assert_array_equal(rows, expected_rows)
        np.testing.assert_array_equal(cols, expected_cols)
        # Nearest return wins each pixel, matching upstream far-to-near order.
        order = np.argsort(depth, kind="stable")
        seen = set()
        for index in order:
            key = (int(rows[index]), int(cols[index]))
            if key in seen:
                continue
            seen.add(key)
            raw = np.array([depth[index], *points[index]], dtype=np.float32)
            means = np.array([12.12, 10.88, 0.23, -1.04, 0.21], dtype=np.float32)
            stds = np.array([12.32, 11.47, 6.91, 0.86, 0.16], dtype=np.float32)
            np.testing.assert_allclose(
                tensor[0, :, key[0], key[1]], (raw - means) / stds, rtol=1e-5
            )

    def test_projection_is_deterministic_including_ties(self):
        points = np.array(
            [[10, 0, 0, 0.2], [10, 0, 0, 0.9], [0, 10, 0, 0.4]], np.float32
        )
        first = project_scan(points)
        repeat = project_scan(points.copy())
        for former, latter in zip(first, repeat):
            np.testing.assert_array_equal(former, latter)
        # Exact ties keep the first input return's full channel values in
        # each ordering: deterministic, but order-dependent by design.
        reversed_scan = project_scan(points[::-1].copy())
        self.assertAlmostEqual(
            float(first[0][0, 4, 6, 1024]), (0.2 - 0.21) / 0.16, places=6
        )
        self.assertAlmostEqual(
            float(reversed_scan[0][0, 4, 6, 1024]), (0.9 - 0.21) / 0.16, places=6
        )
        np.testing.assert_array_equal(first[1], reversed_scan[1][::-1])
        np.testing.assert_array_equal(first[2], reversed_scan[2][::-1])
        np.testing.assert_array_equal(first[3], reversed_scan[3][::-1])

    def test_round_trip_preserves_point_order_through_unprojection(self):
        rng = np.random.default_rng(7)
        radius = rng.uniform(3, 40, size=64)
        yaw = rng.uniform(-np.pi, np.pi, size=64)
        pitch = rng.uniform(-0.3, 0.03, size=64)
        points = np.column_stack(
            [
                radius * np.cos(pitch) * np.cos(yaw),
                -radius * np.cos(pitch) * np.sin(yaw),
                radius * np.sin(pitch),
                rng.uniform(0, 1, size=64),
            ]
        ).astype(np.float32)
        permutation = rng.permutation(len(points))
        shuffled = points[permutation]
        _, rows, cols, valid = project_scan(shuffled)
        self.assertTrue(valid.all())
        scores = np.zeros((1, 20, 64, 2048), np.float32)
        scores[:, 0] = 1.0
        target = (np.arange(len(shuffled)) % 19) + 1
        for position, cls in enumerate(target):
            scores[0, :, rows[position], cols[position]] = 0.0
            scores[0, cls, rows[position], cols[position]] = 0.8
            scores[0, 0, rows[position], cols[position]] = 0.2
        result = unproject_scores(scores, rows, cols, valid)
        # Pixels shared by colliding returns carry the last-written class;
        # every point must still read its own pixel in input order.
        # (Advanced indexing yields (N, C): one row per point, in order.)
        expected = scores[0, :, rows, cols].argmax(axis=1)
        np.testing.assert_array_equal(result.semantic_class, expected)
        np.testing.assert_allclose(
            result.semantic_confidence, scores[0, :, rows, cols].max(axis=1)
        )
        self.assertEqual(result.mode, "model")

    def test_colliding_returns_share_nearest_prediction(self):
        points = np.array(
            [[30, 0, 0, 0.5], [10, 0, 0, 0.5], [0, 10, 0, 0.5]], np.float32
        )
        tensor, rows, cols, valid = project_scan(points)
        self.assertEqual((rows[0], cols[0]), (rows[1], cols[1]))
        means = np.array([12.12, 10.88, 0.23, -1.04, 0.21], np.float32)
        stds = np.array([12.32, 11.47, 6.91, 0.86, 0.16], np.float32)
        self.assertAlmostEqual(
            float(tensor[0, 0, rows[0], cols[0]]), (10 - means[0]) / stds[0]
        )
        scores = np.zeros((1, 20, 64, 2048), np.float32)
        scores[:, 0] = 1.0
        scores[0, :, rows[0], cols[0]] = 0.0
        scores[0, 13, rows[0], cols[0]] = 0.7
        scores[0, 9, rows[0], cols[0]] = 0.3
        result = unproject_scores(scores, rows, cols, valid)
        np.testing.assert_array_equal(result.semantic_class, [13, 13, 0])
        np.testing.assert_allclose(result.semantic_confidence, [0.7, 0.7, 0.0])

    def test_tensor_channel_layout_and_masked_normalization(self):
        contract = model_contract()
        self.assertEqual(contract["channels"], ("range", "x", "y", "z", "remission"))
        points = np.array([[10, 0, 0, 0.2]], np.float32)
        tensor, rows, cols, valid = project_scan(points)
        self.assertTrue(valid.all())
        means = np.asarray(contract["normalization_means"], np.float32)
        stds = np.asarray(contract["normalization_stds"], np.float32)
        raw = np.array([10, 10, 0, 0, 0.2], np.float32)
        np.testing.assert_allclose(
            tensor[0, :, rows[0], cols[0]], (raw - means) / stds, rtol=1e-6
        )
        occupied = np.zeros((64, 2048), bool)
        occupied[rows, cols] = True
        self.assertTrue((tensor[0, :, ~occupied] == 0).all())

    def test_learning_ids_match_upstream_semantic_kitti_map(self):
        # Upstream TiagoCortinhal/SalsaNext
        # train/tasks/semantic/config/labels/semantic-kitti.yaml `learning_map`.
        upstream_learning_map = {
            0: 0,
            1: 0,
            10: 1,
            11: 2,
            13: 5,
            15: 3,
            16: 5,
            18: 4,
            20: 5,
            30: 6,
            31: 7,
            32: 8,
            40: 9,
            44: 10,
            48: 11,
            49: 12,
            50: 13,
            51: 14,
            52: 0,
            60: 9,
            70: 15,
            71: 16,
            72: 17,
            80: 18,
            81: 19,
            99: 0,
            252: 1,
            253: 7,
            254: 6,
            255: 8,
            256: 5,
            257: 5,
            258: 4,
            259: 5,
        }
        from datasets.common.taxonomy import SEMANTICKITTI_LABELS

        self.assertEqual(dict(SEMANTICKITTI_LABELS), upstream_learning_map)
        # learning_map_inv order defines the 20 output channels.
        expected_names = (
            "unlabeled",
            "car",
            "bicycle",
            "motorcycle",
            "truck",
            "other-vehicle",
            "person",
            "bicyclist",
            "motorcyclist",
            "road",
            "parking",
            "sidewalk",
            "other-ground",
            "building",
            "fence",
            "vegetation",
            "trunk",
            "terrain",
            "pole",
            "traffic-sign",
        )
        self.assertEqual(_LEARNING_CLASSES, expected_names)
        # Training ignores class 0; the provider must report it at zero
        # confidence rather than as usable evidence.
        scores = np.zeros((1, 20, 64, 2048), np.float32)
        scores[:, 0] = 1.0
        result = unproject_scores(
            scores, np.array([3]), np.array([5]), np.array([True])
        )
        self.assertEqual(int(result.semantic_class[0]), 0)
        self.assertEqual(float(result.semantic_confidence[0]), 0.0)

    def test_fov_boundaries_are_explicit_unknown(self):
        def point_at_pitch(degrees):
            pitch = np.deg2rad(degrees)
            return [10 * np.cos(pitch), 0, 10 * np.sin(pitch), 0.5]

        points = np.array(
            [
                point_at_pitch(_FOV_UP_DEGREES),
                point_at_pitch(_FOV_DOWN_DEGREES),
                point_at_pitch(_FOV_UP_DEGREES + 0.1),
                point_at_pitch(_FOV_DOWN_DEGREES - 0.1),
                [0, 0, 0, 0.5],
            ],
            np.float32,
        )
        _, rows, cols, valid = project_scan(points)
        np.testing.assert_array_equal(valid, [True, True, False, False, False])
        scores = np.zeros((1, 20, 64, 2048), np.float32)
        scores[:, 0] = 1.0
        result = unproject_scores(scores, rows, cols, valid)
        np.testing.assert_array_equal(result.semantic_class, [0, 0, 0, 0, 0])
        np.testing.assert_array_equal(result.semantic_confidence, [0, 0, 0, 0, 0])

    def test_onnx_export_matches_contract_when_model_present(self):
        if not _REAL_MODEL.is_file():
            self.skipTest(f"SalsaNext ONNX asset absent: {_REAL_MODEL}")
        provider = SalsaNextSemanticProvider(_REAL_MODEL, threads=1)
        self.assertEqual(provider.input_name is not None, True)
        points = np.array(
            [[10, 0, 0, 0.2], [0, 10, -1, 0.4], [1, 0, 2, 0.5]], np.float32
        )
        result = provider.infer(points)
        self.assertEqual(result.mode, "model")
        self.assertEqual(result.semantic_class.shape, (3,))
        self.assertEqual(result.semantic_confidence.shape, (3,))
        # The out-of-FOV return stays failure-safe unknown at zero confidence.
        self.assertEqual(int(result.semantic_class[2]), 0)
        self.assertEqual(float(result.semantic_confidence[2]), 0.0)
        self.assertTrue(
            bool(((result.semantic_class >= 0) & (result.semantic_class < 20)).all())
        )

    def test_real_poss_frame_pins_sensor_mismatch_when_available(self):
        frame = _REAL_SEMANTICPOSS / "sequences/00/velodyne/000000.bin"
        label = _REAL_SEMANTICPOSS / "sequences/00/labels/000000.label"
        if not (frame.is_file() and label.is_file()):
            self.skipTest(f"SemanticPOSS data absent: {frame}")
        points = np.fromfile(frame, dtype=np.float32).reshape(-1, 4)
        # Pandora byte-valued intensity, not KITTI float remission.
        self.assertGreaterEqual(float(points[:, 3].min()), 1.0)
        self.assertLessEqual(float(points[:, 3].max()), 255.0)
        depth = np.linalg.norm(points[:, :3], axis=1)
        pitch = np.degrees(
            np.arcsin(np.clip(points[:, 2] / np.maximum(depth, 1e-9), -1, 1))
        )
        # Pandora nominal vertical FOV is [-16, +7] degrees (CENet poss.yml);
        # the KITTI-trained checkpoint only covers [-25, +3].
        self.assertGreaterEqual(float(pitch.min()), -16.5)
        self.assertLessEqual(float(pitch.max()), 7.5)
        _, rows, _, valid = project_scan(points, intensity_scale=255)
        self.assertGreater(float(valid.mean()), 0.85)
        self.assertLess(float(valid.mean()), 0.95)
        # A 40-beam Pandora scan cannot fill the 64-row KITTI range image.
        self.assertLessEqual(int(np.unique(rows[valid]).size), 40)


if __name__ == "__main__":
    unittest.main()
