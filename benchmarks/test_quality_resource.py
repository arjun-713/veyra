from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
