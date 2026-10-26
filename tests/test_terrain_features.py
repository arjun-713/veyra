"""Terrain features regression suite."""

import importlib.util
import time
import unittest
from pathlib import Path

import numpy as np

from datasets.semanticposs import SemanticPOSSDataset
from perception.ground.patchworkpp import (
    GroundEvidence,
    PatchworkPPGroundSegmenter,
    PatchworkPPUnavailableError,
)
from perception.ground.quality import (
    aggregate_ground_quality_reports,
    ground_quality_report,
)
from perception.terrain.features import TerrainAnalyzer, TerrainEvidence

# Terrain features


class SyntheticGroundEvidence:
    def __init__(self, mask, confidence):
        self.mask = np.asarray(mask, dtype=bool)
        self.confidence = np.asarray(confidence, dtype=np.float32)


def grid(size=9, spacing=0.5, height=None):
    axis = (np.arange(size, dtype=np.float32) - size // 2) * spacing
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    zz = np.zeros_like(xx) if height is None else height(xx, yy)
    return np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))


class TerrainAnalyzerTests(unittest.TestCase):
    def test_original_semanticposs_frame_has_recorded_terrain_stage_cost(self):
        root = Path("data/raw/semanticposs/dataset")
        if not root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")
        frames = list(SemanticPOSSDataset(root).replay("00", end=3, max_range_m=100.0))
        elapsed_s = []
        for frame in frames:
            ground = SyntheticGroundEvidence(
                np.isin(frame.semantic_class, [9, 10, 11, 12, 17]),
                np.ones(len(frame.points), dtype=np.float32),
            )
            start = time.perf_counter()
            evidence = TerrainAnalyzer(min_ground_neighbors=3).analyze(
                frame.points, ground
            )
            elapsed_s.append(time.perf_counter() - start)
            self.assertEqual(evidence.drivable.shape, (len(frame.points),))
        milliseconds = np.asarray(elapsed_s) * 1000.0
        print(
            "terrain semanticposs/00 frames=3 "
            f"points={[len(frame.points) for frame in frames]} "
            f"p50_ms={np.percentile(milliseconds, 50):.3f} "
            f"p95_ms={np.percentile(milliseconds, 95):.3f} "
            f"p99_ms={np.percentile(milliseconds, 99):.3f}"
        )
        self.assertLess(float(np.max(elapsed_s)), 10.0)

    def test_flat_ground_is_drivable_with_negligible_geometry(self):
        points = grid()
        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertIsInstance(evidence, TerrainEvidence)
        self.assertEqual(evidence.slope.shape, (len(points),))
        self.assertEqual(evidence.roughness.shape, (len(points),))
        self.assertTrue(np.all(evidence.drivable == "drivable"))
        self.assertLess(float(np.nanmax(evidence.slope)), 1e-5)
        self.assertLess(float(np.nanmax(evidence.roughness)), 1e-5)
        self.assertTrue(np.all(evidence.confidence > 0.9))
        self.assertTrue(np.allclose(evidence.gradient_x, 0.0, atol=1e-5))
        self.assertTrue(np.allclose(evidence.gradient_y, 0.0, atol=1e-5))

    def test_ground_plane_direction_is_retained_not_only_slope_magnitude(self):
        points = grid(size=11, spacing=0.5, height=lambda x, y: 0.4 * x - 0.2 * y)
        evidence = TerrainAnalyzer(min_ground_neighbors=3).analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertAlmostEqual(
            float(np.nanmedian(evidence.gradient_x)), 0.4, delta=0.02
        )
        self.assertAlmostEqual(
            float(np.nanmedian(evidence.gradient_y)), -0.2, delta=0.02
        )

    def test_steep_rough_ground_is_non_drivable(self):
        points = grid(height=lambda x, y: 0.9 * x + 0.12 * np.sin(9.0 * x + 3.0 * y))
        ground = SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))

        evidence = TerrainAnalyzer().analyze(points, ground)

        self.assertGreater(float(np.nanmedian(evidence.slope)), 0.5)
        self.assertGreater(float(np.nanmedian(evidence.roughness)), 0.02)
        self.assertTrue(np.any(evidence.drivable == "non_drivable"))

    def test_height_discontinuity_marks_step_indicator(self):
        points = grid(height=lambda x, y: np.where(x >= 0.0, 0.6, 0.0))
        ground = SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))

        evidence = TerrainAnalyzer().analyze(points, ground)

        self.assertGreater(float(np.max(evidence.step)), 0.0)
        self.assertTrue(np.any(evidence.height_complexity > 0.1))

    def test_step_indicator_preserves_large_discontinuity_magnitude(self):
        points = grid(
            size=17, spacing=0.25, height=lambda x, y: np.where(x >= 0.0, 0.8, 0.0)
        )
        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertGreater(float(np.nanmax(evidence.step)), 0.5)

    def test_height_complexity_is_bounded_for_map_evidence(self):
        points = grid(height=lambda x, y: 2.0 * x)
        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertTrue(np.all(np.isfinite(evidence.height_complexity)))
        self.assertTrue(np.all(evidence.height_complexity <= 1.0))

    def test_sparse_or_missing_ground_stays_unknown(self):
        points = grid(size=3)
        mask = np.zeros(len(points), dtype=bool)
        ground = SyntheticGroundEvidence(mask, np.zeros(len(points)))

        evidence = TerrainAnalyzer().analyze(points, ground)

        self.assertTrue(np.all(evidence.drivable == "unknown"))
        self.assertTrue(np.all(evidence.confidence == 0.0))
        self.assertTrue(np.all(np.isnan(evidence.slope)))

    def test_empty_and_nonfinite_inputs_are_not_silently_classified(self):
        empty = np.empty((0, 3), dtype=np.float32)
        empty_ground = SyntheticGroundEvidence(np.empty(0, dtype=bool), np.empty(0))
        evidence = TerrainAnalyzer().analyze(empty, empty_ground)
        self.assertEqual(evidence.drivable.shape, (0,))

        invalid = np.zeros((3, 3), dtype=np.float32)
        invalid[0, 0] = np.nan
        with self.assertRaises(ValueError):
            TerrainAnalyzer().analyze(
                invalid, SyntheticGroundEvidence(np.ones(3), np.ones(3))
            )

    def test_duck_typed_ground_mask_without_confidence_is_supported(self):
        points = grid(size=5)

        class MaskOnly:
            mask = np.ones(len(points), dtype=bool)

        evidence = TerrainAnalyzer().analyze(points, MaskOnly())

        self.assertTrue(np.all(evidence.drivable == "drivable"))

    def test_non_ground_obstacle_in_ground_bucket_stays_unknown(self):
        points = np.vstack(
            (
                grid(size=5, spacing=0.2),
                np.array([[0.0, 0.0, 2.0]], dtype=np.float32),
            )
        )
        mask = np.ones(len(points), dtype=bool)
        mask[-1] = False

        evidence = TerrainAnalyzer(min_ground_neighbors=3).analyze(
            points, SyntheticGroundEvidence(mask, np.ones(len(points)))
        )

        self.assertEqual(evidence.drivable[-1], "unknown")
        self.assertEqual(float(evidence.confidence[-1]), 0.0)
        self.assertTrue(np.isnan(evidence.slope[-1]))

    def test_collinear_ground_support_stays_unknown(self):
        x = np.linspace(-1.0, 1.0, 9, dtype=np.float32)
        points = np.column_stack((x, np.zeros_like(x), np.zeros_like(x)))

        evidence = TerrainAnalyzer(min_ground_neighbors=3).analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertTrue(np.all(evidence.drivable == "unknown"))
        self.assertTrue(np.all(np.isnan(evidence.slope)))

    def test_nonfinite_configuration_is_rejected(self):
        for keyword in (
            "neighborhood_radius",
            "max_slope",
            "max_roughness",
            "max_step",
        ):
            with self.subTest(keyword=keyword), self.assertRaises(ValueError):
                TerrainAnalyzer(**{keyword: np.nan})

        with self.assertRaises(ValueError):
            TerrainAnalyzer(min_ground_neighbors=2.5)

    def test_zero_confidence_ground_stays_unknown(self):
        points = grid()

        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.zeros(len(points)))
        )

        self.assertTrue(np.all(evidence.drivable == "unknown"))
        self.assertTrue(np.all(evidence.confidence == 0.0))

    def test_dense_ground_sampling_cannot_hide_height_hazard(self):
        x = np.linspace(-0.2, 0.2, 1000, dtype=np.float32)
        y = 0.1 * np.sin(np.arange(len(x), dtype=np.float32))
        z = np.zeros_like(x)
        z[1] = 1.0
        points = np.column_stack((x, y, z))

        evidence = TerrainAnalyzer(min_ground_neighbors=3).analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertEqual(evidence.drivable[1], "non_drivable")
        self.assertGreater(float(evidence.step[1]), 0.2)

    def test_slope_matches_analytic_grade_on_gentle_plane(self):
        axis = (np.arange(25, dtype=np.float64) - 12) * 0.3
        xx, yy = np.meshgrid(axis, axis, indexing="xy")
        points = np.column_stack((xx.ravel(), yy.ravel(), (0.1 * xx).ravel()))

        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        # A 10% grade is well inside the default 0.45 rad slope budget.
        self.assertAlmostEqual(
            float(np.nanmedian(evidence.slope)), np.arctan(0.1), delta=0.005
        )
        self.assertLess(float(np.nanmax(evidence.roughness)), 1e-6)
        self.assertTrue(np.all(evidence.drivable == "drivable"))

    def test_roughness_channel_marks_washboard_ground_non_drivable(self):
        axis = (np.arange(25, dtype=np.float64) - 12) * 0.3
        xx, yy = np.meshgrid(axis, axis, indexing="xy")
        zz = 0.15 * np.sin(2.0 * np.pi * xx) * np.sin(2.0 * np.pi * yy)
        points = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))

        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        # Plane-fit residual must see the 0.15 m washboard while the fitted
        # grade stays near zero, so the veto comes from surface texture.
        self.assertGreater(float(np.nanmedian(evidence.roughness)), 0.05)
        self.assertLess(float(np.nanmedian(evidence.roughness)), 0.12)
        self.assertLess(float(np.nanmedian(evidence.slope)), 0.05)
        self.assertGreater(float(np.nanmedian(evidence.height_complexity)), 0.05)
        self.assertTrue(np.all(evidence.drivable == "non_drivable"))

    def test_step_magnitude_is_recovered_on_curb_discontinuity(self):
        axis = (np.arange(25, dtype=np.float64) - 12) * 0.3
        xx, yy = np.meshgrid(axis, axis, indexing="xy")
        zz = np.where(xx >= 0.0, 0.3, 0.0)
        points = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))

        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertGreater(float(np.nanmax(evidence.step)), 0.29)
        self.assertLessEqual(float(np.nanmax(evidence.step)), 0.31)
        self.assertGreater(
            float(np.count_nonzero(evidence.drivable == "non_drivable")) / len(points),
            0.2,
        )

    def test_elevated_flat_plane_has_negligible_height_spread(self):
        # Regression: height spread must be elevation-invariant.  A flat
        # plane at z=5 m is exactly as drivable as one at z=0 m.
        axis = (np.arange(25, dtype=np.float64) - 12) * 0.3
        xx, yy = np.meshgrid(axis, axis, indexing="xy")
        points = np.column_stack((xx.ravel(), yy.ravel(), np.full(xx.size, 5.0)))

        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertLess(float(np.nanmax(evidence.height_complexity)), 1e-6)
        self.assertLess(float(np.nanmax(evidence.slope)), 1e-6)
        self.assertTrue(np.all(evidence.drivable == "drivable"))

    def test_step_ignores_empty_cells_at_support_edge(self):
        # A flat patch surrounded by empty space has no neighbor heights to
        # compare against; the zero fill of empty cells must not fabricate a
        # phantom step that vetoes genuinely flat ground.
        axis = (np.arange(9, dtype=np.float64) - 4) * 0.5
        xx, yy = np.meshgrid(axis, axis, indexing="xy")
        points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size)))

        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertEqual(float(np.nanmax(evidence.step)), 0.0)
        self.assertTrue(np.all(evidence.drivable == "drivable"))

    def test_sparse_ground_patch_stays_unknown(self):
        points = grid(size=2, spacing=2.0)

        evidence = TerrainAnalyzer(min_ground_neighbors=6).analyze(
            points, SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        # Four isolated returns cannot form a supported neighborhood.
        self.assertTrue(np.all(evidence.drivable == "unknown"))
        self.assertTrue(np.all(evidence.confidence == 0.0))

    def test_non_ground_slab_is_never_counted_as_drivable(self):
        ground_points = grid(size=9, spacing=0.5)
        slab = grid(size=5, spacing=0.2).copy()
        slab[:, 2] += 2.0
        points = np.vstack((ground_points, slab)).astype(np.float64)
        mask = np.ones(len(points), dtype=bool)
        mask[len(ground_points) :] = False

        evidence = TerrainAnalyzer().analyze(
            points, SyntheticGroundEvidence(mask, np.ones(len(points)))
        )

        slab_labels = evidence.drivable[len(ground_points) :]
        self.assertTrue(np.all(slab_labels == "unknown"))
        self.assertTrue(np.all(evidence.drivable[~mask] != "drivable"))
        self.assertGreater(
            float(
                np.count_nonzero(evidence.drivable[: len(ground_points)] == "drivable")
            )
            / len(ground_points),
            0.5,
        )

    def test_realistic_scan_size_completes_with_aligned_outputs(self):
        rng = np.random.default_rng(20250915)
        points = np.column_stack(
            (
                rng.uniform(-45.0, 45.0, 60_000),
                rng.uniform(-45.0, 45.0, 60_000),
                rng.normal(0.0, 0.02, 60_000),
            )
        )
        ground = SyntheticGroundEvidence(np.ones(len(points)), np.ones(len(points)))

        evidence = TerrainAnalyzer().analyze(points, ground)

        self.assertEqual(evidence.drivable.shape, (60_000,))
        self.assertEqual(evidence.confidence.shape, (60_000,))
        self.assertTrue(np.any(evidence.drivable != "unknown"))

    def test_non_ground_returns_beyond_ground_support_do_not_change_evidence(self):
        # The raster spans only the ground support. Distant non-ground returns
        # (buildings, far clutter) widen the scan extent but must not change
        # a single bit of the evidence computed for the ground patch.
        rng = np.random.default_rng(20260927)
        ground_points = np.column_stack(
            (
                rng.uniform(-12.0, 9.0, 4_000),
                rng.uniform(-7.0, 15.0, 4_000),
                rng.normal(0.0, 0.05, 4_000) + 0.1 * rng.uniform(-1, 1, 4_000),
            )
        )
        confidence = rng.uniform(0.2, 1.0, 4_000)
        clutter = np.column_stack(
            (
                rng.uniform(-150.0, 170.0, 3_000),
                rng.uniform(-160.0, 140.0, 3_000),
                rng.uniform(-2.0, 12.0, 3_000),
            )
        )
        points = np.vstack((ground_points, clutter))
        order = rng.permutation(len(points))
        mask = np.arange(len(points)) < len(ground_points)
        analyzer = TerrainAnalyzer()

        alone = analyzer.analyze(
            ground_points,
            SyntheticGroundEvidence(np.ones(len(ground_points)), confidence),
        )
        mixed = analyzer.analyze(
            points[order],
            SyntheticGroundEvidence(
                mask[order], np.concatenate((confidence, np.ones(len(clutter))))[order]
            ),
        )

        inverse = np.argsort(order)[: len(ground_points)]
        for name in (
            "slope",
            "roughness",
            "height_complexity",
            "step",
            "drivable",
            "confidence",
            "gradient_x",
            "gradient_y",
        ):
            np.testing.assert_array_equal(
                getattr(mixed, name)[inverse], getattr(alone, name), err_msg=name
            )
        clutter_rows = np.argsort(order)[len(ground_points) :]
        self.assertTrue(np.all(mixed.drivable[clutter_rows] == "unknown"))
        self.assertTrue(np.all(np.isnan(mixed.slope[clutter_rows])))
        self.assertTrue(np.all(mixed.confidence[clutter_rows] == 0.0))

    def test_raster_bound_still_covers_the_full_point_extent(self):
        # The bounded-raster guard is judged on every return, not only on the
        # ground support, and still fails closed when there is no ground.
        ground_patch = grid()
        far = np.array([[3_000.0, 3_000.0, 0.0]])
        points = np.vstack((ground_patch, far))
        with_ground = np.concatenate((np.ones(len(ground_patch)), [0.0]))
        for mask in (with_ground, np.zeros(len(points))):
            with self.assertRaisesRegex(ValueError, "too large"):
                TerrainAnalyzer().analyze(
                    points, SyntheticGroundEvidence(mask, np.ones(len(points)))
                )


# Patchworkpp ground


class GroundEvidenceTests(unittest.TestCase):
    def test_ground_quality_report_is_explicit_for_binary_predictions(self):
        report = ground_quality_report(
            np.array([True, True, False, False]),
            np.array([True, False, False, True]),
        )

        self.assertEqual(report["evaluated_points"], 4)
        self.assertEqual(report["true_positive"], 1)
        self.assertEqual(report["false_positive"], 1)
        self.assertEqual(report["false_negative"], 1)
        self.assertAlmostEqual(report["precision"], 0.5)
        self.assertAlmostEqual(report["recall"], 0.5)
        self.assertAlmostEqual(report["f1"], 0.5)
        self.assertAlmostEqual(report["iou"], 1 / 3)

    def test_ground_quality_rejects_misaligned_masks(self):
        with self.assertRaises(ValueError):
            ground_quality_report(np.array([True]), np.array([True, False]))

    def test_ground_quality_aggregation_uses_micro_counts(self):
        report = aggregate_ground_quality_reports(
            [
                ground_quality_report([True, False], [True, False]),
                ground_quality_report([False, False, True], [True, False, False]),
            ]
        )

        self.assertEqual(report["evaluated_points"], 5)
        self.assertEqual(report["true_positive"], 1)
        self.assertEqual(report["false_negative"], 1)
        self.assertAlmostEqual(report["recall"], 0.5)

    def test_evidence_is_point_aligned_and_preserves_backend_metadata(self):
        evidence = GroundEvidence(
            mask=np.array([True, False, True]),
            confidence=np.array([0.9, 0.1, 1.0], dtype=np.float32),
            backend="test-backend",
        )

        self.assertEqual(evidence.mask.shape, (3,))
        self.assertEqual(evidence.confidence.shape, (3,))
        self.assertEqual(evidence.backend, "test-backend")

    def test_evidence_rejects_misaligned_outputs(self):
        with self.assertRaises(ValueError):
            GroundEvidence(
                mask=np.array([True, False]),
                confidence=np.array([0.5]),
                backend="test-backend",
            )

    def test_official_binding_api_is_used(self):
        class Parameters:
            pass

        class Backend:
            def __init__(self, params):
                self.params = params
                self.points = None

            def estimateGround(self, points):
                self.points = points

            def getGroundIndices(self):
                return [0, 2]

        segmenter = PatchworkPPGroundSegmenter(module_names=("fake",))
        import sys
        import types

        module = types.ModuleType("fake")
        module.Parameters = Parameters
        module.patchworkpp = Backend
        sys.modules["fake"] = module
        evidence = segmenter.segment(np.zeros((3, 4), dtype=np.float32))
        np.testing.assert_array_equal(evidence.mask, [True, False, True])

    def test_parameter_overrides_are_applied_to_official_binding(self):
        class Parameters:
            max_range = 80.0
            min_range = 2.7

        class Backend:
            def __init__(self, params):
                self.params = params

            def estimateGround(self, points):
                del points

            def getGroundIndices(self):
                return [0]

        import sys
        import types

        module = types.ModuleType("fake_parameters")
        module.Parameters = Parameters
        module.patchworkpp = Backend
        sys.modules["fake_parameters"] = module
        segmenter = PatchworkPPGroundSegmenter(
            module_names=("fake_parameters",),
            parameter_overrides={"max_range": 100.0, "min_range": 0.0},
        )

        segmenter.segment(np.zeros((1, 4), dtype=np.float32))

        self.assertEqual(segmenter._binding.params.max_range, 100.0)
        self.assertEqual(segmenter._binding.params.min_range, 0.0)

    def test_unknown_parameter_is_a_configuration_error(self):
        class Parameters:
            max_range = 80.0

        class Backend:
            def __init__(self, params):
                del params

            def estimateGround(self, points):
                del points

            def getGroundIndices(self):
                return []

        import sys
        import types

        module = types.ModuleType("fake_invalid_parameters")
        module.Parameters = Parameters
        module.patchworkpp = Backend
        sys.modules["fake_invalid_parameters"] = module

        with self.assertRaisesRegex(ValueError, "not supported"):
            PatchworkPPGroundSegmenter(
                module_names=("fake_invalid_parameters",),
                parameter_overrides={"not_a_parameter": 1},
            ).segment(np.zeros((1, 4), dtype=np.float32))


class PatchworkPPGroundSegmenterTests(unittest.TestCase):
    def test_availability_reports_a_fail_closed_diagnostic(self):
        availability = PatchworkPPGroundSegmenter(
            module_names=("module-that-is-not-installed",)
        ).availability()

        self.assertFalse(availability.available)
        self.assertIn("module-that-is-not-installed", availability.diagnostic)

    @unittest.skipUnless(
        importlib.util.find_spec("pypatchworkpp"),
        "optional pypatchworkpp dependency is not installed",
    )
    def test_installed_official_backend_smoke(self):
        points = np.column_stack(
            (
                np.linspace(1.0, 30.0, 2048),
                np.zeros(2048),
                np.zeros(2048),
                np.ones(2048),
            )
        ).astype(np.float32)
        evidence = PatchworkPPGroundSegmenter().segment(points)
        self.assertEqual(evidence.mask.shape, (2048,))
        self.assertEqual(evidence.backend, "pypatchworkpp.patchworkpp")

    def test_missing_backend_has_actionable_error(self):
        segmenter = PatchworkPPGroundSegmenter(
            module_names=("module-that-is-not-installed",),
            executable_names=(),
        )

        with self.assertRaises(PatchworkPPUnavailableError) as context:
            segmenter.segment(np.zeros((2, 4), dtype=np.float32))

        self.assertIn("Patchwork++", str(context.exception))
        self.assertIn("module-that-is-not-installed", str(context.exception))

    def test_real_rellis_frame_executes_patchworkpp_on_cpu(self):
        if not importlib.util.find_spec("pypatchworkpp"):
            self.skipTest("requires pypatchworkpp for real RELLIS smoke test")

        dataset_root = Path("data/raw/rellis3d/Rellis-3D")
        if not dataset_root.is_dir():
            self.skipTest("original local RELLIS-3D data is unavailable")

        from datasets.rellis import Rellis3DDataset

        dataset = Rellis3DDataset(dataset_root, sequences=["00000"])
        frame = dataset.load_frame("00000", dataset.list_frames("00000")[0].frame_id)

        started = time.perf_counter()
        evidence = PatchworkPPGroundSegmenter().segment(frame.points)
        elapsed_s = time.perf_counter() - started

        self.assertEqual(evidence.mask.shape, (frame.points.shape[0],))
        self.assertEqual(evidence.confidence.shape, evidence.mask.shape)
        self.assertTrue(np.all(np.isfinite(evidence.confidence)))
        ground_ratio = float(np.mean(evidence.mask))
        self.assertGreater(ground_ratio, 0.001)
        self.assertLess(ground_ratio, 0.999)
        self.assertGreater(elapsed_s, 0.0)
        print(
            "real RELLIS Patchwork++: "
            f"points={frame.points.shape[0]} ground_ratio={ground_ratio:.4f} "
            f"elapsed_s={elapsed_s:.6f}"
        )

    def test_real_semanticposs_ground_quality_is_measurable(self):
        if not importlib.util.find_spec("pypatchworkpp"):
            self.skipTest("requires pypatchworkpp for real SemanticPOSS validation")
        dataset_root = Path("data/raw/semanticposs/dataset")
        if not dataset_root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")

        from datasets.semanticposs import SemanticPOSSDataset

        reports = []
        dataset = SemanticPOSSDataset(dataset_root, sequences=["00"])
        segmenter = PatchworkPPGroundSegmenter(
            parameter_overrides={"min_range": 0.0, "max_range": 100.0}
        )
        for frame in dataset.replay("00", end=3, max_range_m=100.0):
            sensor = frame.points.copy()
            sensor[:, :3] = (
                sensor[:, :3] - frame.pose.matrix[:3, 3]
            ) @ frame.pose.matrix[:3, :3]
            evidence = segmenter.segment(sensor)
            reports.append(
                ground_quality_report(evidence.mask, frame.raw_semantic_class == 22)
            )

        aggregate = aggregate_ground_quality_reports(reports)
        self.assertGreater(aggregate["recall"], 0.85)
        self.assertGreater(aggregate["precision"], 0.65)
        self.assertGreater(aggregate["f1"], 0.75)
        print(
            "real SemanticPOSS Patchwork++ ground quality: "
            f"frames={aggregate['frames']} precision={aggregate['precision']:.4f} "
            f"recall={aggregate['recall']:.4f} f1={aggregate['f1']:.4f} "
            f"iou={aggregate['iou']:.4f}"
        )


if __name__ == "__main__":
    unittest.main()
