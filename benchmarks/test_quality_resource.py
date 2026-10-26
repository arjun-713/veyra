"""Quality resource regression suite."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from benchmarks.reconstruction import (
    reconstruct_from_leaves,
    reconstruction_report,
    reference_cloud,
    voxel_downsample,
)
from benchmarks.render_report import (
    _field_retention_summary,
    _hard_failure,
    _perception_status_summary,
    _perception_table,
    render,
)
from benchmarks.tradeoff_plot import policy_points, render_svg

# Quality resource


def report_fixture():
    import math

    policies = {}
    values = {
        "uniform5": (1000, 100, 1.00, 1.00, 0.000),
        "uniform40": (100, 40, 0.70, 0.90, 0.030),
        "distance_lod": (300, 30, 0.90, 0.95, 0.012),
        "utility_lod": (500, 50, 0.89, 0.95, 0.014),
    }
    for policy, (memory, latency_ms, accuracy, completion, chamfer) in values.items():
        surface = {
            "status": "measured",
            "reference_is_ground_truth": False,
            "reference_bins": 100,
            "matched_bins": 100,
            "height_accuracy_10cm": accuracy,
            "completion_fraction": completion,
            "symmetric_chamfer_m": chamfer,
            "elevation_rmse_m": chamfer / math.sqrt(2.0),
        }
        quality = {
            "high_resolution_surface_comparison": surface,
            "field_retention": {
                "semantic": {"retention_fraction": 0.8},
                "task_classes": {
                    "members": {
                        name: {"retention_fraction": 0.75}
                        for name in ("pedestrian", "pole", "vehicle")
                    }
                },
            },
        }
        policies[policy] = {
            "runs": [
                {
                    "stream_digest": "same-stream",
                    "metrics": {
                        "memory": {
                            "logical_map_bytes": memory,
                            "allocated_map_bytes": memory * 2,
                        }
                    },
                    "quality": quality,
                }
            ],
            "aggregate": {
                "peak_rss_bytes": memory * 3,
                "measured_frame_count": 50,
                "fps": {"p50": 12.0},
                "stage_latency_ns": {
                    "map_update": {
                        "count": 16,
                        "p50": latency_ms * 500_000,
                        "p95": latency_ms * 1_000_000,
                        "p99": latency_ms * 1_000_000,
                    },
                    "frame_pipeline": {"p50": latency_ms * 2_000_000},
                },
                "final_leaves_per_level": {"0": 5, "1": 4, "2": 3, "3": 2},
            },
        }
    return {
        "schema_version": 2,
        "dataset": "fixture",
        "sequence": "00",
        "provenance": {"selection_digest": "same-input"},
        "policies": policies,
    }


class QualityResourceTests(unittest.TestCase):
    def test_extracts_four_policy_quality_and_cost_from_existing_artifact(self):
        from benchmarks.quality_resource import comparison_rows

        rows = comparison_rows(report_fixture())

        self.assertEqual(
            {row["policy"] for row in rows},
            {"uniform5", "uniform40", "distance_lod", "utility_lod"},
        )
        distance = next(row for row in rows if row["policy"] == "distance_lod")
        self.assertEqual(distance["logical_map_bytes"], 300)
        self.assertEqual(distance["map_update_p50_ms"], 15.0)
        self.assertEqual(distance["map_update_p95_ms"], 30.0)
        self.assertEqual(distance["height_accuracy_10cm"], 0.90)
        self.assertEqual(distance["completion_fraction"], 0.95)
        self.assertEqual(distance["symmetric_chamfer_m"], 0.012)
        self.assertEqual(distance["chamfer_distance_m"], 0.012)
        self.assertEqual(distance["runtime_per_frame_ms"], 60.0)
        self.assertEqual(distance["runtime_ms"], 60.0)
        self.assertEqual(distance["rss_bytes"], 900)

    def test_latency_frontier_uses_p50_when_p95_sample_count_is_insufficient(self):
        from benchmarks.quality_resource import build_quality_resource_report

        report = build_quality_resource_report(report_fixture())

        self.assertEqual(report["latency_plot_metric"], "map_update_p50_ms")
        self.assertIn(
            "p50",
            report["pareto"]["latency_vs_height_accuracy"]["x_metric"],
        )
        joint_metrics = {
            objective["metric"]
            for objective in report["pareto"]["joint_resource_quality"]["objectives"]
        }
        self.assertIn("map_update_p50_ms", joint_metrics)
        self.assertNotIn("map_update_p95_ms", joint_metrics)
        distance = next(
            row for row in report["policies"] if row["policy"] == "distance_lod"
        )
        self.assertEqual(distance["map_update_sample_count"], 16)
        self.assertFalse(distance["map_update_p95_reliable"])

    def test_pareto_frontier_marks_utility_as_dominated_without_weighting(self):
        from benchmarks.quality_resource import pareto_summary

        summary = pareto_summary(comparison_rows_fixture())
        memory_accuracy = summary["memory_vs_height_accuracy"]
        self.assertEqual(memory_accuracy["dominated"]["utility_lod"], ["distance_lod"])
        self.assertIn("uniform5", memory_accuracy["frontier"])
        self.assertIn("distance_lod", memory_accuracy["frontier"])
        rss_accuracy = summary["rss_vs_height_accuracy"]
        self.assertEqual(rss_accuracy["dominated"]["utility_lod"], ["distance_lod"])
        joint = summary["joint_resource_quality"]
        self.assertIn("distance_lod", joint["dominated"]["utility_lod"])
        self.assertFalse(joint["weighted_score_used"])

    def test_artifact_writer_emits_truthful_table_summary_and_all_svg_plots(self):
        from benchmarks.quality_resource import write_quality_resource_artifacts

        report = report_fixture()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_quality_resource_artifacts(report, Path(directory))

            summary = json.loads(Path(paths["json"]).read_text())
            with Path(paths["csv"]).open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(summary["selection_digest"], "same-input")
            self.assertFalse(summary["reference"]["is_ground_truth"])
            self.assertTrue(summary["same_input_for_all_policies"])
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[2]["height_accuracy_10cm"], "0.9")
            self.assertIn(
                "distance_lod",
                summary["pareto"]["joint_resource_quality"]["dominated"]["utility_lod"],
            )
            self.assertEqual(len(paths["plots"]), 9)
            self.assertTrue(Path(paths["plots"]["rss_vs_height_accuracy"]).is_file())
            for plot_path in paths["plots"].values():
                svg = Path(plot_path).read_text()
                self.assertIn("<svg", svg)
                for policy in ("Uniform5", "Uniform40", "DistanceLOD", "UtilityLOD"):
                    self.assertIn(policy, svg)

    def test_unavailable_comparison_metrics_remain_null(self):
        from benchmarks.quality_resource import comparison_rows

        row = next(
            row
            for row in comparison_rows({"policies": {}})
            if row["policy"] == "uniform5"
        )
        self.assertEqual(row["status"], "unavailable")
        self.assertIsNone(row.get("height_accuracy_10cm"))
        self.assertNotEqual(row.get("height_accuracy_10cm"), 0.0)

    def test_equal_policies_are_both_pareto_efficient(self):
        from benchmarks.quality_resource import pareto_frontier

        rows = [
            {"policy": "a", "logical_map_bytes": 10, "height_accuracy_10cm": 0.8},
            {"policy": "b", "logical_map_bytes": 10, "height_accuracy_10cm": 0.8},
        ]
        result = pareto_frontier(
            rows,
            x_metric="logical_map_bytes",
            x_direction="min",
            y_metric="height_accuracy_10cm",
            y_direction="max",
        )
        self.assertEqual(result["frontier"], ["a", "b"])
        self.assertEqual(result["dominated"], {})

    def test_missing_metrics_are_not_coerced_to_zero_or_pareto_wins(self):
        from benchmarks.quality_resource import pareto_frontier

        result = pareto_frontier(
            [
                {
                    "policy": "measured",
                    "logical_map_bytes": 10,
                    "height_accuracy_10cm": 0.8,
                },
                {
                    "policy": "missing",
                    "logical_map_bytes": 1,
                    "height_accuracy_10cm": None,
                },
            ],
            x_metric="logical_map_bytes",
            x_direction="min",
            y_metric="height_accuracy_10cm",
            y_direction="max",
        )
        self.assertEqual(result["frontier"], ["measured"])
        self.assertEqual(result["unavailable"], ["missing"])


def comparison_rows_fixture():
    return [
        {
            "policy": "uniform5",
            "logical_map_bytes": 1000,
            "rss_bytes": 3000,
            "map_update_p95_ms": 100,
            "height_accuracy_10cm": 1.00,
            "completion_fraction": 1.00,
            "symmetric_chamfer_m": 0.0,
        },
        {
            "policy": "uniform40",
            "logical_map_bytes": 100,
            "rss_bytes": 300,
            "map_update_p95_ms": 40,
            "height_accuracy_10cm": 0.70,
            "completion_fraction": 0.90,
            "symmetric_chamfer_m": 0.03,
        },
        {
            "policy": "distance_lod",
            "logical_map_bytes": 300,
            "rss_bytes": 900,
            "map_update_p95_ms": 30,
            "height_accuracy_10cm": 0.90,
            "completion_fraction": 0.95,
            "symmetric_chamfer_m": 0.012,
        },
        {
            "policy": "utility_lod",
            "logical_map_bytes": 500,
            "rss_bytes": 1500,
            "map_update_p95_ms": 50,
            "height_accuracy_10cm": 0.89,
            "completion_fraction": 0.95,
            "symmetric_chamfer_m": 0.014,
        },
    ]


# Reconstruction


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
            reconstruct_from_leaves(
                [leaf(0, 0, 0, obstacle_count=1, obstacle_min_z=0.0)]
            )

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


# Render report


class RenderReportTests(unittest.TestCase):
    def test_invalid_measured_semantic_quality_is_a_hard_failure(self):
        self.assertTrue(
            _hard_failure(
                {"semantic_quality": {"status": "measured", "overall": {"miou": 1.1}}},
                {"timings": {}},
            )
        )

    def test_invalid_observed_mixed_resolution_topology_is_a_hard_failure(self):
        self.assertTrue(
            _hard_failure(
                {
                    "policies": {
                        "uniform5": {
                            "aggregate": {
                                "quality": [
                                    {
                                        "point_conservation": {"holds": True},
                                        "duplicate_ownership": {"holds": True},
                                        "mixed_resolution_topology": {
                                            "status": "invalid"
                                        },
                                    }
                                ]
                            }
                        }
                    },
                },
                {"timings": {"semantic": {}}},
            )
        )

    def test_report_renders_all_policy_and_perception_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_report = {
                "dataset": "semanticposs",
                "semantic_quality": {
                    "status": "measured",
                    "overall": {"points": 2, "accuracy": 1.0, "miou": 1.0},
                    "range_bins": [
                        {
                            "min_m": 0.0,
                            "max_m": 10.0,
                            "points": 2,
                            "accuracy": 1.0,
                            "miou": 1.0,
                        }
                    ],
                },
                "provenance": {
                    "git_sha": "abc",
                    "dataset_sha256": "def",
                    "frame_range": {"sequence": "00", "count": 1},
                },
                "policies": {
                    policy: {
                        "aggregate": {
                            "fps": {"p50": 10},
                            "stage_latency_ns": {
                                "map_update": {
                                    "p50": 1_000_000,
                                    "p95": 2_000_000,
                                    "p99": 3_000_000,
                                }
                            },
                            "peak_rss_bytes": 1_048_576,
                            "final_leaves_per_level": {"0": 1},
                            "topology_churn_per_frame": {"p95": 1},
                            "quality": [
                                {
                                    "point_conservation": {"holds": True},
                                    "duplicate_ownership": {"holds": True},
                                    "elevation_vs_fine_reference": {
                                        "rmse_m": 0.1,
                                        "coverage": 1.0,
                                    },
                                }
                            ],
                        },
                        "runs": [
                            {
                                "metrics": {
                                    "memory": {
                                        "logical_map_bytes": 1,
                                        "allocated_map_bytes": 2,
                                    }
                                }
                            }
                        ],
                    }
                    for policy in (
                        "uniform5",
                        "uniform40",
                        "distance_lod",
                        "utility_lod",
                    )
                },
            }
            perception = {
                "reproducibility": {"git_sha": "abc"},
                "status": {"semantic": "model", "ground": "patchworkpp"},
                "config": {"semantic": {"mode": "salsanext"}},
                "timings": {
                    "dataset_load": {"p50_ms": 4, "p95_ms": 5, "p99_ms": 6},
                    "semantic": {"mean_ms": 1, "p50_ms": 1, "p95_ms": 2, "p99_ms": 3},
                    "bridge": {"p50_ms": 0.1, "p95_ms": 0.2, "p99_ms": 0.3},
                },
            }
            map_path, perception_path = root / "map.json", root / "perception.json"
            map_path.write_text(json.dumps(map_report))
            perception_path.write_text(json.dumps(perception))
            report = render(map_path, perception_path)
        self.assertIn("Uniform5", report)
        self.assertIn("UtilityLOD", report)
        self.assertIn("SalsaNext", report)
        self.assertIn("Dataset load", report)
        self.assertIn("Bridge", report)
        self.assertIn("Backend status", report)
        self.assertIn("Analytical 5 cm 3D reference", report)
        self.assertIn("Range-binned semantic quality", report)
        self.assertIn("100.0%", report)
        self.assertIn("Correctness gate: **PASS**", report)
        self.assertIn("Elevation coverage", report)
        self.assertIn("100.0%", report)
        self.assertIn("Ablation matrix was not included", report)

    def test_ground_truth_semantic_timing_uses_actual_provider(self):
        report = _perception_table(
            {
                "config": {"semantic": {"mode": "ground_truth"}},
                "timings": {
                    "semantic": {"p50_ms": 0.09, "p95_ms": 0.10, "p99_ms": 0.11}
                },
            }
        )
        self.assertIn("Ground Truth | 0.09 ms", report)
        self.assertNotIn("SalsaNext", report)

    def test_semantic_timing_prefers_actual_provider_over_requested_mode(self):
        report = _perception_table(
            {
                "config": {"semantic": {"mode": "cenet"}},
                "timings": {
                    "semantic": {"p50_ms": 0.09, "p95_ms": 0.10, "p99_ms": 0.11}
                },
            },
            {"perception": {"status": {"semantic": "ground_truth"}}},
        )
        self.assertIn("Ground Truth | 0.09 ms", report)
        self.assertNotIn("CENet |", report)

    def test_backend_status_falls_back_to_map_artifact(self):
        status = _perception_status_summary(
            {"config": {"semantic": {"mode": "ground_truth"}}},
            {
                "perception": {
                    "status": {"semantic": "ground_truth", "ground": "patchworkpp"}
                }
            },
        )
        self.assertIn("semantic=`ground_truth`", status)
        self.assertIn("ground=`patchworkpp`", status)

    def test_report_renders_partial_ablation_without_breaking_old_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.json"
            path.write_text(
                json.dumps(
                    {
                        "utility_ablation": {
                            "status": "partial",
                            "required_policies": [
                                "ablation_distance",
                                "ablation_geometry",
                            ],
                            "full_vs_distance_assessment": "unavailable",
                            "members": {
                                "ablation_distance": {
                                    "signals": [],
                                    "measurements": {
                                        "elevation_rmse_m": 0.2,
                                        "map_latency_p95_ns": 2_000_000,
                                    },
                                    "delta_vs_distance": {
                                        "elevation_rmse_m": 0.0,
                                        "peak_rss_fraction": 0.0,
                                    },
                                }
                            },
                        }
                    }
                )
            )
            report = render(path, None)
        self.assertIn("distance only", report)
        self.assertIn("ablation_geometry | not run", report)
        self.assertIn("Status: **partial**", report)

    def test_report_renders_scalar_field_retention_values(self):
        report = _field_retention_summary(
            {
                "policies": {
                    "uniform5": {
                        "aggregate": {
                            "quality": [
                                {
                                    "field_retention": {
                                        "status": "unavailable",
                                        "semantic_confidence": "not recorded",
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        )
        self.assertIn("Field retention: unavailable", report)
        self.assertIn("semantic_confidence: not recorded", report)


if __name__ == "__main__":
    unittest.main()
