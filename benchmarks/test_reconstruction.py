import unittest
from types import SimpleNamespace

import numpy as np

from benchmarks.reconstruction import (
    reconstruct_from_leaves,
    reconstruction_report,
    reference_cloud,
    voxel_downsample,
)
from benchmarks.tradeoff_plot import policy_points, render_svg


def leaf(level, ix, iy, **layers):
    base = {"level": level, "ix": ix, "iy": iy, "count": 1}
    base.update(layers)
    return base


class ReconstructionMetricTests(unittest.TestCase):
    def test_identical_sets_score_perfectly(self):
        points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 1.0]])
        report = reconstruction_report(points, points)
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["accuracy"]["mean_m"], 0.0)
        self.assertEqual(report["completion"]["mean_m"], 0.0)
        self.assertEqual(report["chamfer_l1_m"], 0.0)
        self.assertTrue(all(row["fscore"] == 1.0 for row in report["thresholds"]))

    def test_accuracy_and_completion_are_directional(self):
        reference = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]])
        # The map claims only the first point, offset 3 cm vertically.
        reconstruction = np.array([[0.0, 0.0, 0.03]])
        report = reconstruction_report(reconstruction, reference)
        self.assertAlmostEqual(report["accuracy"]["mean_m"], 0.03)
        # Completion: 0.03 for the claimed point, ~10 m for the missing one.
        expected = (0.03 + np.hypot(10.0, 0.03)) / 2
        self.assertAlmostEqual(report["completion"]["mean_m"], expected)
        self.assertAlmostEqual(report["chamfer_l1_m"], (0.03 + expected) / 2)
        at_5cm = report["thresholds"][0]
        self.assertEqual((at_5cm["precision"], at_5cm["recall"]), (1.0, 0.5))

    def test_empty_inputs_are_unavailable_not_zero(self):
        report = reconstruction_report(np.empty((0, 3)), np.ones((2, 3)))
        self.assertEqual(report["status"], "unavailable")

    def test_range_bands_use_distance_from_the_final_vehicle_position(self):
        reference = np.array([[5.0, 0.0, 0.0], [45.0, 0.0, 0.0]])
        report = reconstruction_report(reference, reference, center_xy=(0.0, 0.0))
        counts = [band["reference_points"] for band in report["by_range"]]
        self.assertEqual(counts, [1, 0, 1, 0])


class ReconstructionSamplingTests(unittest.TestCase):
    def test_leaves_become_voxel_centres_at_their_own_resolution(self):
        points = reconstruct_from_leaves(
            [
                # 5 cm ground cell at z = -1.8.
                leaf(0, 0, 0, ground_count=3, ground_mean_z=-1.8),
                # 40 cm obstacle spanning 0..1.2 m -> three 40 cm voxels.
                leaf(3, 1, 0, obstacle_count=5, obstacle_min_z=0.0, obstacle_max_z=1.2),
                # Empty leaves contribute nothing.
                {"level": 1, "ix": 5, "iy": 5, "count": 0},
            ]
        )
        np.testing.assert_allclose(points[0], [0.025, 0.025, -1.8])
        column = points[1:]
        np.testing.assert_allclose(column[:, :2], [[0.6, 0.2]] * 3)
        np.testing.assert_allclose(column[:, 2], [0.2, 0.6, 1.0])

    def test_flat_obstacle_extent_is_one_voxel(self):
        points = reconstruct_from_leaves(
            [leaf(2, 0, 0, obstacle_count=1, obstacle_min_z=0.5, obstacle_max_z=0.5)]
        )
        np.testing.assert_allclose(points, [[0.1, 0.1, 0.5]])

    def test_missing_layer_extent_fails_loudly(self):
        with self.assertRaises(ValueError):
            reconstruct_from_leaves([leaf(0, 0, 0, obstacle_count=1, obstacle_min_z=0.0)])

    def test_reference_is_windowed_and_voxel_averaged(self):
        frame = SimpleNamespace(
            points=np.array(
                [[0.01, 0.01, 0.0, 1.0], [0.03, 0.03, 0.0, 1.0], [500.0, 0.0, 0.0, 1.0]]
            )
        )
        cloud = reference_cloud([frame], center_xy=(0.0, 0.0), radius_m=100.0)
        np.testing.assert_allclose(cloud, [[0.02, 0.02, 0.0]])
        self.assertEqual(len(voxel_downsample(np.empty((0, 3)), 0.05)), 0)


class TradeoffPlotTests(unittest.TestCase):
    @staticmethod
    def result(policy, chamfer, time_ns, memory):
        rec = {
            "status": "available",
            "chamfer_l1_m": chamfer,
            "accuracy": {"mean_m": chamfer},
            "completion": {"mean_m": chamfer},
            "thresholds": [{"threshold_m": 0.10, "fscore": 0.9}],
        }
        return policy, {
            "aggregate": {"stage_latency_ns": {"map_update": {"p50": time_ns}}},
            "runs": [
                {
                    "quality": {"reconstruction": rec},
                    "metrics": {"memory": {"logical_map_bytes": memory}},
                }
            ],
        }

    def test_points_and_svg_cover_every_available_policy(self):
        result = {
            "dataset": "generic",
            "sequence": "011",
            "policies": dict(
                [
                    self.result("uniform5", 0.04, 9e6, 80e6),
                    self.result("distance_lod", 0.07, 8e6, 20e6),
                ]
            ),
        }
        points = policy_points(result, "chamfer_l1_m")
        self.assertEqual({p["policy"] for p in points}, {"uniform5", "distance_lod"})
        svg = render_svg([("generic 011", points)], "chamfer_l1_m", "t")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("DistanceLOD", svg)
        self.assertIn("Logical map payload (MB)", svg)

    def test_plot_refuses_results_without_reconstruction(self):
        with self.assertRaises(ValueError):
            render_svg([("x", [])], "chamfer_l1_m", "t")


if __name__ == "__main__":
    unittest.main()
