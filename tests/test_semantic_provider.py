import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from perception.semantic.cenet import (
    CENET_IMAGE_HEIGHT,
    CENET_IMAGE_WIDTH,
    CENET_LEARNING_TO_RAW,
    CENET_N_LEARNING_CLASSES,
    CENET_YAW_COL_OFFSET,
    CENetSemanticProvider,
    render_cenet_image,
)
from perception.semantic.pandora import (
    GROUP_INDEX,
    GROUP_NAMES,
    GROUP_OF_NATIVE,
    PANDORA_BEAM_ELEVATIONS_DEG,
    PANDORA_IMAGE_HEIGHT,
    PANDORA_IMAGE_WIDTH,
    POSS_NATIVE_KNOWN_IDS,
    PandoraNativeSemanticProvider,
    extract_features,
    fold_to_native,
    mlp_predict_proba,
    native_to_group_ids,
    project_pandora_beams,
    project_pandora_scan,
)
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

    def test_unknown_maps_to_zero_confidence_while_known_passes_through(self):
        # Failure-safe contract the SalsaNext path relies on: class 0 is
        # absence of evidence, never a confident prediction, even when the
        # backend reports high confidence for it.
        session = _Session(
            input_shape=[None, 4],
            output_shapes=[[None], [None]],
            outputs=([1, 2, 99], [0.8, 0.99, 0.6]),
        )
        provider = OnnxSemanticProvider(session=session, mapping={1: 9})
        result = provider.infer(np.zeros((3, 4), dtype=np.float32))
        np.testing.assert_array_equal(result.semantic_class, [9, 0, 0])
        np.testing.assert_allclose(result.semantic_confidence, [0.8, 0.0, 0.0])
        self.assertEqual(result.mode, "model")

    def test_semantic_result_zeroes_unknown_confidence_despite_backend_value(self):
        result = SemanticResult(np.array([0, 9]), np.array([0.99, 0.7]), "model")
        np.testing.assert_array_equal(result.semantic_class, [0, 9])
        np.testing.assert_allclose(result.semantic_confidence, [0.0, 0.7])


class _ValueInfo:
    def __init__(self, shape):
        self.name = "tensor"
        self.shape = shape


def _tiny_pandora_checkpoint(path: Path, *, temperature: float = 1.0) -> Path:
    """Write a deterministic 6 -> 4 -> 3 MLP archive for provider tests."""
    rng = np.random.RandomState(0)
    coef_0 = rng.normal(size=(6, 4))
    intercept_0 = rng.normal(size=4)
    coef_1 = rng.normal(size=(4, 3))
    intercept_1 = rng.normal(size=3)
    np.savez(
        path,
        scaler_mean=np.zeros(6),
        scaler_scale=np.ones(6),
        n_layers=np.array(2, dtype=np.int64),
        coef_0=coef_0,
        intercept_0=intercept_0,
        coef_1=coef_1,
        intercept_1=intercept_1,
        # Native IDs 22 (ground -> Veyra 12), 7 (car -> Veyra 1), 0 (unknown).
        classes=np.array([22, 7, 0], dtype=np.int32),
        temperature=np.array(temperature, dtype=np.float64),
    )
    return path


class PandoraProjectionTests(unittest.TestCase):
    def test_rejects_nonfinite_and_misshaped_input(self):
        with self.assertRaises(ValueError):
            project_pandora_scan(np.zeros((4, 3), dtype=np.float32))
        with self.assertRaises(ValueError):
            project_pandora_scan(np.zeros(4, dtype=np.float32))
        bad = np.zeros((2, 4), dtype=np.float32)
        bad[0, 0] = np.nan
        with self.assertRaises(ValueError):
            project_pandora_scan(bad)

    def test_rows_cols_bounded_and_deterministic(self):
        rng = np.random.RandomState(1)
        points = rng.uniform(-60, 60, size=(500, 4)).astype(np.float32)
        points[:, 3] = rng.uniform(0, 255, size=500).astype(np.float32)
        rows, cols, valid = project_pandora_scan(points)
        self.assertEqual(rows.shape, (500,))
        self.assertTrue(bool(((rows >= 0) & (rows < PANDORA_IMAGE_HEIGHT)).all()))
        self.assertTrue(bool(((cols >= 0) & (cols < PANDORA_IMAGE_WIDTH)).all()))
        rows2, cols2, valid2 = project_pandora_scan(points)
        np.testing.assert_array_equal(rows, rows2)
        np.testing.assert_array_equal(cols, cols2)
        np.testing.assert_array_equal(valid, valid2)

    def test_vertical_fov_edges_match_pandora_contract(self):
        # pitch = +7 deg -> row 0, pitch = -16 deg -> bottom row, both valid.
        up = np.deg2rad(7.0)
        down = np.deg2rad(-16.0)
        r = 20.0
        top = np.array([[r * np.cos(up), 0.0, r * np.sin(up), 100.0]], np.float32)
        bottom = np.array(
            [[r * np.cos(down), 0.0, r * np.sin(down), 100.0]], np.float32
        )
        rows, _, valid = project_pandora_scan(top)
        self.assertEqual(int(rows[0]), 0)
        self.assertTrue(bool(valid[0]))
        rows, _, valid = project_pandora_scan(bottom)
        self.assertEqual(int(rows[0]), PANDORA_IMAGE_HEIGHT - 1)
        self.assertTrue(bool(valid[0]))
        # Above (+10 deg) and below (-20 deg) the band are invalid.
        for deg in (10.0, -20.0):
            pitch = np.deg2rad(deg)
            point = np.array(
                [[r * np.cos(pitch), 0.0, r * np.sin(pitch), 100.0]], np.float32
            )
            _, _, valid = project_pandora_scan(point)
            self.assertFalse(bool(valid[0]))

    def test_yaw_wraps_full_circle(self):
        points = np.array(
            [
                [10.0, 0.0, -1.0, 50.0],
                [-10.0, 0.0, -1.0, 50.0],
                [0.0, 10.0, -1.0, 50.0],
                [0.0, -10.0, -1.0, 50.0],
            ],
            np.float32,
        )
        _, cols, valid = project_pandora_scan(points)
        self.assertTrue(bool(valid.all()))
        self.assertEqual(len(set(int(c) for c in cols)), 4)

    def test_real_pandora_frame_near_full_coverage(self):
        root = Path(
            os.environ.get(
                "VEYRA_SEMANTICPOSS_ROOT",
                Path(__file__).resolve().parents[1]
                / "data/raw/semanticposs/dataset",
            )
        )
        frame = root / "sequences/00/velodyne/000000.bin"
        if not frame.is_file():
            self.skipTest(f"SemanticPOSS data absent: {frame}")
        points = np.fromfile(frame, dtype=np.float32).reshape(-1, 4)
        rows, cols, valid = project_pandora_scan(points)
        # Native FOV covers all but the measured +7.0..+7.3 deg above-horizon
        # tail (SalsaNext covers only ~90.5%). Out-of-contract returns stay
        # invalid/unknown rather than inheriting an edge-row prediction.
        self.assertGreater(float(valid.mean()), 0.975)
        depth = np.linalg.norm(points[:, :3], axis=1)
        pitch = np.degrees(
            np.arcsin(np.clip(points[:, 2] / np.maximum(depth, 1e-9), -1, 1))
        )
        self.assertTrue(bool((pitch[~valid] > 7.0).all()))


class PandoraTaxonomyTests(unittest.TestCase):
    def test_known_ids_pass_through_unmapped_fold_to_unknown(self):
        raw = np.array([0, 4, 7, 22, 18, 19, 20, 99, 255], dtype=np.int64)
        np.testing.assert_array_equal(
            fold_to_native(raw), [0, 4, 7, 22, 0, 0, 0, 0, 0]
        )

    def test_groups_cover_every_native_label_exactly_once(self):
        covered = dict(GROUP_OF_NATIVE)
        self.assertEqual(covered[0], "unknown")
        for raw in POSS_NATIVE_KNOWN_IDS:
            self.assertIn(raw, covered)
        self.assertEqual(set(covered.values()), set(GROUP_NAMES))

    def test_native_to_group_ids_matches_table(self):
        native = np.array([22, 14, 15, 13, 7, 4, 9, 0], dtype=np.int32)
        expected = [GROUP_INDEX[name] for name in (
            "drivable", "non-drivable", "static", "pole",
            "vehicle", "pedestrian", "vegetation", "unknown",
        )]
        np.testing.assert_array_equal(native_to_group_ids(native), expected)

    def test_extract_features_contract(self):
        points = np.array([[3.0, 4.0, -1.5, 255.0]], np.float32)
        feats = extract_features(points)
        self.assertEqual(feats.shape, (1, 6))
        self.assertAlmostEqual(float(feats[0, 3]), 1.0)
        self.assertAlmostEqual(float(feats[0, 4]), np.sqrt(9 + 16 + 2.25), places=4)
        with self.assertRaises(ValueError):
            extract_features(np.zeros((1, 3), dtype=np.float32))


class PandoraNativeProviderTests(unittest.TestCase):
    def _provider(self, directory: str, **kwargs) -> PandoraNativeSemanticProvider:
        return PandoraNativeSemanticProvider(
            _tiny_pandora_checkpoint(Path(directory) / "tiny.npz", **kwargs)
        )

    def test_supported_datasets_accepts_poss_only(self):
        self.assertEqual(
            PandoraNativeSemanticProvider.supported_datasets, frozenset({"semanticposs"})
        )

    def test_infer_returns_aligned_veyra_classes_and_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self._provider(directory)
            points = np.array(
                [
                    [10.0, 0.0, -1.0, 50.0],
                    [20.0, 5.0, 2.0, 200.0],
                    [5.0, -3.0, 0.5, 10.0],
                ],
                np.float32,
            )
            result = provider.infer(points)
            self.assertEqual(result.mode, "model")
            self.assertEqual(result.semantic_class.shape, (3,))
            self.assertEqual(result.semantic_confidence.shape, (3,))
            # Tiny head predicts native {22, 7, 0} -> Veyra {12, 1, 0}.
            self.assertTrue(
                set(int(c) for c in result.semantic_class) <= {12, 1, 0}
            )
            self.assertTrue(
                bool(((result.semantic_confidence >= 0.0)
                      & (result.semantic_confidence <= 1.0)).all())
            )
            unknown = result.semantic_class == 0
            np.testing.assert_array_equal(
                result.semantic_confidence[unknown],
                np.zeros(int(unknown.sum()), dtype=np.float32),
            )

    def test_infer_preserves_point_order(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self._provider(directory)
            rng = np.random.RandomState(2)
            points = rng.uniform(-30, 30, size=(50, 4)).astype(np.float32)
            points[:, 3] = rng.uniform(0, 255, size=50).astype(np.float32)
            batched = provider.infer(points)
            for index in range(50):
                single = provider.infer(points[index : index + 1])
                self.assertEqual(
                    int(batched.semantic_class[index]), int(single.semantic_class[0])
                )
                self.assertAlmostEqual(
                    float(batched.semantic_confidence[index]),
                    float(single.semantic_confidence[0]),
                    places=6,
                )

    def test_infer_native_matches_veyra_projection(self):
        from datasets.common.taxonomy import SEMANTIC_POSS_LABELS

        with tempfile.TemporaryDirectory() as directory:
            provider = self._provider(directory)
            points = np.array([[8.0, 1.0, -0.5, 80.0]], np.float32)
            native, proba = provider.infer_native(points)
            self.assertEqual(proba.shape, (1, 3))
            self.assertAlmostEqual(float(proba.sum()), 1.0, places=5)
            result = provider.infer(points)
            self.assertEqual(
                int(result.semantic_class[0]),
                SEMANTIC_POSS_LABELS.get(int(native[0]), 0),
            )

    def test_temperature_flattens_confidence(self):
        points = np.array([[8.0, 1.0, -0.5, 80.0]], np.float32)
        with tempfile.TemporaryDirectory() as directory:
            cold = self._provider(directory, temperature=0.2).infer(points)
            hot = self._provider(directory, temperature=5.0).infer(points)
            self.assertGreaterEqual(
                float(cold.semantic_confidence[0]), float(hot.semantic_confidence[0])
            )

    def test_empty_input_returns_empty_result(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._provider(directory).infer(np.zeros((0, 4), np.float32))
            self.assertEqual(result.semantic_class.shape, (0,))
            self.assertEqual(result.mode, "model")

    def test_rejects_missing_corrupt_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.npz"
            with self.assertRaises(ValueError):
                PandoraNativeSemanticProvider(missing)
            corrupt = Path(directory) / "corrupt.npz"
            corrupt.write_bytes(b"not a checkpoint")
            with self.assertRaises(ValueError):
                PandoraNativeSemanticProvider(corrupt)
            provider = self._provider(directory)
            bad = np.zeros((1, 4), dtype=np.float32)
            bad[0, 2] = np.inf
            with self.assertRaises(ValueError):
                provider.infer(bad)
            with self.assertRaises(ValueError):
                provider.infer(np.zeros((1, 3), dtype=np.float32))

    def test_numpy_forward_matches_sklearn(self):
        sklearn_mlp = pytest_importorskip("sklearn.neural_network")
        scaler_cls = pytest_importorskip("sklearn.preprocessing").StandardScaler
        rng = np.random.RandomState(3)
        X = rng.normal(size=(60, 6))
        y = rng.randint(0, 3, size=60)
        scaler = scaler_cls()
        Xs = scaler.fit_transform(X)
        clf = sklearn_mlp.MLPClassifier(
            hidden_layer_sizes=(4,), max_iter=5, random_state=0
        ).fit(Xs, y)
        expected = clf.predict_proba(Xs)
        got = mlp_predict_proba(
            Xs,
            np.zeros(6),
            np.ones(6),
            [c.astype(np.float64) for c in clf.coefs_],
            [b.astype(np.float64) for b in clf.intercepts_],
        )
        np.testing.assert_allclose(got, expected, rtol=1e-5, atol=1e-6)


def pytest_importorskip(name: str):
    import importlib

    try:
        return importlib.import_module(name)
    except ImportError:
        raise unittest.SkipTest(f"optional dependency absent: {name}")


def _cenet_checkpoint() -> Path:
    here = Path(__file__).resolve().parents[1]
    candidates = [
        Path(
            os.environ.get(
                "VEYRA_CENET_CHECKPOINT",
                here / "data/cache/models/cenet-poss/SENet_valid_best",
            )
        ),
        Path(
            "/home/arjun/Captain/SIH/Lidar/data/cache/models/cenet-poss/"
            "SENet_valid_best"
        ),
        Path(
            "/home/arjun/Captain/SIH/Lidar/data/cache/cenet-work/model/"
            "SENet_valid_best"
        ),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise unittest.SkipTest(f"CENet checkpoint absent: {candidates[0]}")


def _poss_frame(frame_id: str = "000000") -> tuple[np.ndarray, np.ndarray]:
    root = Path(
        os.environ.get(
            "VEYRA_SEMANTICPOSS_ROOT",
            Path(__file__).resolve().parents[1] / "data/raw/semanticposs/dataset",
        )
    )
    scan = root / f"sequences/00/velodyne/{frame_id}.bin"
    label = root / f"sequences/00/labels/{frame_id}.label"
    if not scan.is_file() or not label.is_file():
        raise unittest.SkipTest(f"SemanticPOSS data absent: {scan}")
    points = np.fromfile(scan, dtype=np.float32).reshape(-1, 4)
    raw = np.fromfile(label, dtype=np.uint32) & 0xFFFF
    return points, raw.astype(np.int64)


class CENetRenderTests(unittest.TestCase):
    def test_render_contract_and_determinism(self):
        rng = np.random.RandomState(5)
        points = rng.uniform(-40, 40, size=(200, 4)).astype(np.float32)
        points[:, 3] = rng.uniform(0, 255, size=200).astype(np.float32)
        image, rows, cols, valid = render_cenet_image(points)
        self.assertEqual(
            image.shape, (1, 5, CENET_IMAGE_HEIGHT, CENET_IMAGE_WIDTH)
        )
        self.assertEqual(rows.shape, (200,))
        # Empty pixels are exactly zero (masked after normalization).
        occupied = np.zeros((CENET_IMAGE_HEIGHT, CENET_IMAGE_WIDTH), bool)
        occupied[rows[valid], cols[valid]] = True
        self.assertTrue(bool((image[0, :, ~occupied] == 0.0).all()))
        image2, rows2, cols2, valid2 = render_cenet_image(points)
        np.testing.assert_array_equal(image, image2)
        np.testing.assert_array_equal(rows, rows2)

    def test_render_applies_yaw_column_offset(self):
        # yaw = 0 (+x axis) -> analytic col 900 -> shifted col.
        points = np.array([[10.0, 0.0, -1.0, 50.0]], np.float32)
        _, rows, cols, valid = render_cenet_image(points)
        self.assertTrue(bool(valid[0]))
        self.assertEqual(int(cols[0]), (900 + CENET_YAW_COL_OFFSET) % CENET_IMAGE_WIDTH)

    def test_render_uses_raw_byte_remission(self):
        # Channel 4 must carry the raw byte value, not intensity/255:
        # reverse the normalization on an occupied pixel.
        from perception.semantic.cenet import CENET_MEANS, CENET_STDS

        points = np.array([[10.0, 0.0, -1.0, 200.0]], np.float32)
        image, rows, cols, valid = render_cenet_image(points)
        raw = (
            float(image[0, 4, rows[0], cols[0]]) * CENET_STDS[4] + CENET_MEANS[4]
        )
        self.assertAlmostEqual(raw, 200.0, places=3)

    def test_render_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            render_cenet_image(np.zeros((4, 3), dtype=np.float32))
        bad = np.zeros((2, 4), dtype=np.float32)
        bad[0, 0] = np.inf
        with self.assertRaises(ValueError):
            render_cenet_image(bad)

    def test_beam_rows_reproduce_dataset_tags(self):
        points, _ = _poss_frame()
        root = Path(
            os.environ.get(
                "VEYRA_SEMANTICPOSS_ROOT",
                Path(__file__).resolve().parents[1] / "data/raw/semanticposs/dataset",
            )
        )
        tags = np.fromfile(root / "sequences/00/tag/000000.tag", dtype=bool)
        tagidx = np.flatnonzero(tags)
        rows, _, valid = project_pandora_beams(points)
        # Beam rows reproduce the tag layout exactly for every return.
        np.testing.assert_array_equal(rows, tagidx // 1800)
        self.assertEqual(len(PANDORA_BEAM_ELEVATIONS_DEG), 40)


class CENetProviderTests(unittest.TestCase):
    def test_supported_datasets_accepts_poss_only(self):
        self.assertEqual(
            CENetSemanticProvider.supported_datasets, frozenset({"semanticposs"})
        )

    def test_rejects_missing_and_incompatible_checkpoints(self):
        pytest_importorskip("torch")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                CENetSemanticProvider(Path(directory) / "absent.bin")
            corrupt = Path(directory) / "corrupt.bin"
            corrupt.write_bytes(b"not a checkpoint")
            with self.assertRaises(ValueError):
                CENetSemanticProvider(corrupt)
            import torch

            incompatible = Path(directory) / "incompatible.bin"
            torch.save({"state_dict": {"wrong_name": torch.zeros(1)}}, incompatible)
            with self.assertRaises(ValueError):
                CENetSemanticProvider(incompatible)

    def test_rejects_nonfinite_and_empty_handling(self):
        checkpoint = _cenet_checkpoint()
        pytest_importorskip("torch")
        provider = CENetSemanticProvider(checkpoint, threads=1)
        bad = np.zeros((1, 4), dtype=np.float32)
        bad[0, 0] = np.nan
        with self.assertRaises(ValueError):
            provider.infer(bad)
        with self.assertRaises(ValueError):
            provider.infer(np.zeros((1, 3), dtype=np.float32))
        empty = provider.infer(np.zeros((0, 4), dtype=np.float32))
        self.assertEqual(empty.semantic_class.shape, (0,))
        self.assertEqual(empty.mode, "model")

    def test_real_checkpoint_output_is_probabilistic_and_ordered(self):
        checkpoint = _cenet_checkpoint()
        pytest_importorskip("torch")
        provider = CENetSemanticProvider(checkpoint, threads=1)
        points, _ = _poss_frame()
        sample = points[:2000]
        first = provider.infer(sample)
        second = provider.infer(sample)
        np.testing.assert_array_equal(first.semantic_class, second.semantic_class)
        self.assertEqual(first.mode, "model")
        # Per-point inference preserves order.
        single = provider.infer(sample[7:8])
        self.assertEqual(int(first.semantic_class[7]), int(single.semantic_class[0]))
        # Unknown stays failure-safe at zero confidence.
        unknown = first.semantic_class == 0
        np.testing.assert_array_equal(
            first.semantic_confidence[unknown],
            np.zeros(int(unknown.sum()), dtype=np.float32),
        )
        self.assertTrue(bool(((first.semantic_confidence >= 0.0)
                              & (first.semantic_confidence <= 1.0)).all()))

    def test_real_checkpoint_frame_accuracy_smoke(self):
        from datasets.common.taxonomy import SEMANTIC_POSS_LABELS, map_dataset_labels

        checkpoint = _cenet_checkpoint()
        pytest_importorskip("torch")
        provider = CENetSemanticProvider(checkpoint, threads=2)
        points, raw = _poss_frame()
        result = provider.infer(points)
        gt = map_dataset_labels(raw, SEMANTIC_POSS_LABELS)
        labelled = gt != 0
        accuracy = float(np.mean(result.semantic_class[labelled] == gt[labelled]))
        # Frame 000000 is the checkpoint author's training data; this pins
        # the integration (projection + weights + taxonomy), not generalization.
        # Held-out quality is measured in reports/closure/semantic-finetune/.
        self.assertGreater(accuracy, 0.80)


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
