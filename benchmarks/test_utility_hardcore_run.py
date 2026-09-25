"""Fail-closed checks for frozen scenes and comparable governor budgets."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.utility_hardcore import manifest_digest
from benchmarks.utility_hardcore_report import signal_distributions, write_plots
from benchmarks.utility_hardcore_run import (
    _annotate_efficiency,
    _variants,
    _world_xy,
    load_manifest,
    memory_budget_config,
)


class HardcoreRunnerTests(unittest.TestCase):
    def test_efficiency_ratio_is_undefined_without_extra_memory(self):
        rows = [
            {
                "challenge_id": "x",
                "policy": "distance_lod",
                "logical_map_bytes": 1_000_000,
                "critical_accuracy_10cm": 0.5,
                "semantic_retention_critical": 0.2,
                "critical_chamfer_m": 0.1,
            },
            {
                "challenge_id": "x",
                "policy": "utility_lod",
                "logical_map_bytes": 1_500_000,
                "critical_accuracy_10cm": 0.6,
                "semantic_retention_critical": 0.3,
                "critical_chamfer_m": 0.09,
            },
        ]
        _annotate_efficiency(rows)
        self.assertIsNone(rows[0]["critical_accuracy_gain_per_MB"])
        self.assertAlmostEqual(rows[1]["critical_accuracy_gain_per_MB"], 0.2)
        self.assertAlmostEqual(rows[1]["critical_chamfer_improvement_per_MB"], 0.02)

    def test_signal_summary_deduplicates_challenges_sharing_one_stream(self):
        telemetry = {
            "signals": {
                name: {
                    "histogram": [2] + [0] * 19,
                    "raw_sum": 0,
                    "weighted_sum": 0,
                    "exact_zero_count": 2,
                    "near_one_count": 0,
                }
                for name in (
                    "geometry",
                    "semantic",
                    "motion",
                    "traversability_risk",
                    "semantic_uncertainty",
                )
            },
            "utility_histogram": [2] + [0] * 19,
            "utility_exact_zero_count": 2,
            "utility_near_one_count": 0,
            "transition_reason_masks": [{"mask": 2, "count": 1}],
        }
        row = {
            "selection_digest": "same",
            "policy": "utility_lod",
            "budget_fraction": None,
            "promotion_telemetry": telemetry,
        }
        summary = signal_distributions([row, dict(row)])
        self.assertEqual(summary["distributions"]["semantic"]["sample_count"], 2)
        self.assertEqual(summary["transition_reason_mask_counts"][2], 1)

    def test_plots_label_missing_measured_series_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            write_plots(Path(directory), [], signal_distributions([]))
            plots = list((Path(directory) / "plots").glob("*.svg"))
            self.assertEqual(len(plots), 14)
            self.assertIn("UNAVAILABLE", plots[0].read_text())

    def test_ablation_preserves_cpp_compatible_distance_boundary_syntax(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            names = _variants(Path(directory), repo)
            self.assertEqual(len(names), 4)
            content = (Path(directory) / "a1_geometry.yaml").read_text()
            self.assertIn("distance_boundaries_m: [10.0, 30.0, 60.0]", content)
            self.assertIn("semantic_weight: 0.0", content)
            self.assertIn("geometry_weight: 0.20", content)

    def test_source_points_are_transformed_to_world_before_region_scoring(self):
        pose = np.eye(4)
        pose[:3, 3] = [10.0, -2.0, 0.0]
        transformed = _world_xy(np.array([[1.0, 2.0, 0.0, 0.5]]), pose)
        np.testing.assert_allclose(transformed, [[11.0, 0.0]])

    def test_modified_frozen_region_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            manifest = {
                "schema_version": 1,
                "challenges": [{"bbox_xy_m": [0, 0, 1, 1]}],
            }
            manifest["sha256"] = manifest_digest(manifest)
            path.write_text(json.dumps(manifest))
            self.assertEqual(load_manifest(path)["sha256"], manifest["sha256"])
            manifest["challenges"][0]["bbox_xy_m"][2] = 2
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_manifest(path)

    def test_budget_config_isolates_logical_bytes_and_preserves_safety_radius(self):
        source = {
            "max_logical_bytes": 1000,
            "pressure_ratio": 0.9,
            "near_field_radius_m": 10.0,
            "target_frame_time_ms": 100.0,
            "max_active_cells": 250000,
            "max_rss_bytes": 0,
            "overload_consecutive_frames": 3,
        }
        configured = memory_budget_config(source, 10_000)
        self.assertEqual(configured["near_field_radius_m"], 10.0)
        self.assertGreaterEqual(configured["max_logical_bytes"] * 0.9, 10_000)
        self.assertGreater(configured["max_active_cells"], source["max_active_cells"])
        self.assertGreater(
            configured["target_frame_time_ms"], source["target_frame_time_ms"]
        )
        self.assertEqual(source["max_logical_bytes"], 1000)


if __name__ == "__main__":
    unittest.main()
