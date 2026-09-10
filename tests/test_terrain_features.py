import time
import unittest
from pathlib import Path

import numpy as np

from datasets.semanticposs import SemanticPOSSDataset
from perception.terrain.features import TerrainAnalyzer, TerrainEvidence


class GroundEvidence:
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
            ground = GroundEvidence(
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
            points, GroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertIsInstance(evidence, TerrainEvidence)
        self.assertEqual(evidence.slope.shape, (len(points),))
        self.assertEqual(evidence.roughness.shape, (len(points),))
        self.assertTrue(np.all(evidence.drivable == "drivable"))
        self.assertLess(float(np.nanmax(evidence.slope)), 1e-5)
        self.assertLess(float(np.nanmax(evidence.roughness)), 1e-5)
        self.assertTrue(np.all(evidence.confidence > 0.9))

    def test_steep_rough_ground_is_non_drivable(self):
        points = grid(height=lambda x, y: 0.9 * x + 0.12 * np.sin(9.0 * x + 3.0 * y))
        ground = GroundEvidence(np.ones(len(points)), np.ones(len(points)))

        evidence = TerrainAnalyzer().analyze(points, ground)

        self.assertGreater(float(np.nanmedian(evidence.slope)), 0.5)
        self.assertGreater(float(np.nanmedian(evidence.roughness)), 0.02)
        self.assertTrue(np.any(evidence.drivable == "non_drivable"))

    def test_height_discontinuity_marks_step_indicator(self):
        points = grid(height=lambda x, y: np.where(x >= 0.0, 0.6, 0.0))
        ground = GroundEvidence(np.ones(len(points)), np.ones(len(points)))

        evidence = TerrainAnalyzer().analyze(points, ground)

        self.assertGreater(float(np.max(evidence.step)), 0.0)
        self.assertTrue(np.any(evidence.height_complexity > 0.1))

    def test_sparse_or_missing_ground_stays_unknown(self):
        points = grid(size=3)
        mask = np.zeros(len(points), dtype=bool)
        ground = GroundEvidence(mask, np.zeros(len(points)))

        evidence = TerrainAnalyzer().analyze(points, ground)

        self.assertTrue(np.all(evidence.drivable == "unknown"))
        self.assertTrue(np.all(evidence.confidence == 0.0))
        self.assertTrue(np.all(np.isnan(evidence.slope)))

    def test_empty_and_nonfinite_inputs_are_not_silently_classified(self):
        empty = np.empty((0, 3), dtype=np.float32)
        empty_ground = GroundEvidence(np.empty(0, dtype=bool), np.empty(0))
        evidence = TerrainAnalyzer().analyze(empty, empty_ground)
        self.assertEqual(evidence.drivable.shape, (0,))

        invalid = np.zeros((3, 3), dtype=np.float32)
        invalid[0, 0] = np.nan
        with self.assertRaises(ValueError):
            TerrainAnalyzer().analyze(invalid, GroundEvidence(np.ones(3), np.ones(3)))

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
            points, GroundEvidence(mask, np.ones(len(points)))
        )

        self.assertEqual(evidence.drivable[-1], "unknown")
        self.assertEqual(float(evidence.confidence[-1]), 0.0)
        self.assertTrue(np.isnan(evidence.slope[-1]))

    def test_collinear_ground_support_stays_unknown(self):
        x = np.linspace(-1.0, 1.0, 9, dtype=np.float32)
        points = np.column_stack((x, np.zeros_like(x), np.zeros_like(x)))

        evidence = TerrainAnalyzer(min_ground_neighbors=3).analyze(
            points, GroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertTrue(np.all(evidence.drivable == "unknown"))
        self.assertTrue(np.all(np.isnan(evidence.slope)))

    def test_nonfinite_configuration_is_rejected(self):
        for keyword in ("neighborhood_radius", "max_slope", "max_roughness", "max_step"):
            with self.subTest(keyword=keyword):
                with self.assertRaises(ValueError):
                    TerrainAnalyzer(**{keyword: np.nan})

        with self.assertRaises(ValueError):
            TerrainAnalyzer(min_ground_neighbors=2.5)

    def test_zero_confidence_ground_stays_unknown(self):
        points = grid()

        evidence = TerrainAnalyzer().analyze(
            points, GroundEvidence(np.ones(len(points)), np.zeros(len(points)))
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
            points, GroundEvidence(np.ones(len(points)), np.ones(len(points)))
        )

        self.assertEqual(evidence.drivable[1], "non_drivable")
        self.assertGreater(float(evidence.step[1]), 0.2)


if __name__ == "__main__":
    unittest.main()
