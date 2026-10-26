"""Utility hardcore regression suite."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from benchmarks.protocol import stream_bytes
from benchmarks.test_runtime import frame
from benchmarks.utility_hardcore import (
    contiguous_window,
    manifest_digest,
    regional_comparison,
    select_geometry_candidates,
    select_semantic_candidate,
)
from benchmarks.utility_hardcore_report import signal_distributions, write_plots
from benchmarks.utility_hardcore_run import (
    _annotate_efficiency,
    _critical_bins,
    _variants,
    _world_xy,
    load_manifest,
    memory_budget_config,
)
from tests.test_engine_service import require_binary

# Utility hardcore

"""Contract tests for frozen, policy-blind challenge selection and scoring."""


class UtilityChallengeTests(unittest.TestCase):
    def test_motion_region_keeps_one_dataset_instance(self):
        from benchmarks.utility_challenge import _motion_candidate

        points = np.asarray(
            [[40.0 + i * 0.01, 0.0, 0.0, 0.0] for i in range(25)]
            + [[50.0 + i * 0.01, 0.0, 0.0, 0.0] for i in range(22)]
        )
        selected = _motion_candidate(
            points, np.full(47, 252), np.asarray([10] * 25 + [20] * 22)
        )
        self.assertEqual(selected["instance_id"], 10)
        self.assertLess(selected["bbox_xy_m"][2] - selected["bbox_xy_m"][0], 2.0)

    def test_motion_instance_id_is_scoped_by_raw_class(self):
        from benchmarks.utility_challenge import _motion_candidate

        points = np.asarray(
            [[40.0 + i * 0.01, 0.0, 0.0, 0.0] for i in range(25)]
            + [[50.0 + i * 0.01, 0.0, 0.0, 0.0] for i in range(22)]
        )
        selected = _motion_candidate(
            points, np.asarray([252] * 25 + [254] * 22), np.ones(47)
        )
        self.assertEqual(selected["raw_moving_ids"], [252])
        self.assertLess(selected["bbox_xy_m"][2] - selected["bbox_xy_m"][0], 2.0)

    def test_benchmark_command_requests_opt_in_promotion_telemetry(self):
        from pathlib import Path

        from benchmarks.run_benchmark import POLICY_ADAPTERS, _command

        command = _command(
            "/bin/veyra_benchmark",
            POLICY_ADAPTERS["utility_lod"],
            {
                "ranges_m": [[0, 10], [10, 30], [30, 60], [60, 100]],
                "levels": [0.05, 0.1, 0.2, 0.4],
            },
            100.0,
            1,
            Path("/tmp/veyra"),
            promotion_telemetry=True,
        )
        self.assertIn("--promotion-telemetry", command)

    def test_benchmark_command_defaults_to_deterministic_governor(self):
        from pathlib import Path

        from benchmarks.run_benchmark import POLICY_ADAPTERS, _command

        arguments = (
            "/bin/veyra_benchmark",
            POLICY_ADAPTERS["utility_lod"],
            {
                "ranges_m": [[0, 10], [10, 30], [30, 60], [60, 100]],
                "levels": [0.05, 0.1, 0.2, 0.4],
            },
            100.0,
            1,
            Path("/tmp/veyra"),
        )
        # Wall-clock evidence must not steer benchmark maps unless asked for.
        self.assertIn("--deterministic-governor", _command(*arguments))
        self.assertNotIn(
            "--deterministic-governor",
            _command(*arguments, deterministic_governor=False),
        )

    def test_window_never_crosses_missing_original_frame_ids(self):
        self.assertEqual(contiguous_window([0, 1, 2, 400, 401, 402], 401, 3), (3, 6))
        self.assertIsNone(contiguous_window([0, 1, 400, 401], 400, 3))

    def test_geometry_selection_separates_rough_and_flat_at_similar_range(self):
        rough = [[40.1, 0.1, z, 0] for z in ([0.0, 0.6] * 8)]
        flat = [[42.1, 0.1, z, 0] for z in ([0.0, 0.01] * 8)]
        result = select_geometry_candidates(np.asarray(rough + flat), min_points=12)
        self.assertIsNotNone(result["geometry_hazard"])
        self.assertIsNotNone(result["flat_control"])
        self.assertGreater(result["geometry_hazard"]["height_iqr_m"], 0.25)
        self.assertLess(result["flat_control"]["height_iqr_m"], 0.04)
        self.assertLess(
            abs(
                result["geometry_hazard"]["mean_range_m"]
                - result["flat_control"]["mean_range_m"]
            ),
            5.0,
        )

    def test_runner_can_retain_real_leaf_rows_for_spatial_challenge_scoring(self):
        from benchmarks.run_benchmark import _finalize_policy_runs

        snapshot = {
            "point_count": 1,
            "leaves": [{"level": 0, "ix": 0, "iy": 0, "count": 1, "mean_z": 2.0}],
        }
        runs = {
            "uniform5": [
                {
                    "snapshot": snapshot,
                    "metrics": {"stream": {"rejected_out_of_window": 0}},
                }
            ]
        }
        _finalize_policy_runs(runs, {"point_count": 1}, compact=False)
        self.assertEqual(runs["uniform5"][0]["snapshot"]["leaves"][0]["mean_z"], 2.0)

    def test_object_selection_uses_labels_and_range_before_policy_data(self):
        points = np.array(
            [[40.0, 0.0, 1.0, 0], [40.1, 0.0, 1.0, 0], [5.0, 0.0, 1.0, 0]],
            dtype=np.float32,
        )
        classes = np.array([6, 6, 6], dtype=np.int32)
        instances = np.array([12, 12, 13], dtype=np.int32)
        selected = select_semantic_candidate(
            points,
            classes,
            instances,
            class_id=6,
            lower_m=30,
            upper_m=60,
            min_points=2,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected["instance_id"], 12)
        self.assertEqual(selected["points"], 2)
        self.assertEqual(selected["range_band_m"], [30, 60])
        self.assertLessEqual(selected["bbox_xy_m"][0], 40.0)

    def test_uninstanced_returns_from_distant_patches_are_not_one_object(self):
        points = np.asarray(
            [[40.0 + index * 0.01, 0.0, 0.0, 0.0] for index in range(10)]
            + [[50.0 + index * 0.01, 0.0, 0.0, 0.0] for index in range(10)]
        )
        selected = select_semantic_candidate(
            points,
            np.full(20, 18),
            np.zeros(20),
            class_id=18,
            lower_m=30,
            upper_m=60,
            min_points=20,
        )
        self.assertIsNone(selected)

    def test_frozen_manifest_digest_changes_if_challenge_region_changes(self):
        first = {"schema_version": 1, "challenges": [{"bbox_xy_m": [0, 0, 1, 1]}]}
        second = {"schema_version": 1, "challenges": [{"bbox_xy_m": [0, 0, 2, 1]}]}
        self.assertNotEqual(manifest_digest(first), manifest_digest(second))
        self.assertEqual(manifest_digest(first), manifest_digest(dict(first)))

    def test_regional_score_distinguishes_critical_from_background_promotion(self):
        reference = {
            "mean_z_by_cell": {(0, 0): 1.0, (20, 0): 2.0},
            "mean_range_by_cell": {(0, 0): 40.0, (20, 0): 40.0},
        }
        distance = {
            "leaves": [
                {"level": 2, "ix": 0, "iy": 0, "mean_z": 0.0, "count": 1},
                {"level": 2, "ix": 5, "iy": 0, "mean_z": 2.0, "count": 1},
            ]
        }
        utility = {
            "leaves": [
                {"level": 1, "ix": 0, "iy": 0, "mean_z": 1.0, "count": 1},
                {"level": 2, "ix": 5, "iy": 0, "mean_z": 2.0, "count": 1},
            ]
        }
        scored = regional_comparison(
            reference, distance, utility, bbox_xy_m=[-0.1, -0.1, 0.1, 0.1]
        )
        self.assertEqual(scored["promoted_bins"], 1)
        self.assertEqual(scored["promotion_precision"], 1.0)
        self.assertEqual(scored["promotion_recall"], 1.0)
        self.assertEqual(scored["critical"]["utility_lod"]["height_accuracy_10cm"], 1.0)
        self.assertEqual(
            scored["critical"]["distance_lod"]["height_accuracy_10cm"], 0.0
        )

    def test_object_support_mask_excludes_non_object_bins_inside_bbox(self):
        reference = {"mean_z_by_cell": {(0, 0): 0.0, (20, 0): 0.0}}
        distance = {
            "leaves": [
                {"level": 1, "ix": 0, "iy": 0, "mean_z": 0.0, "count": 1},
                {"level": 1, "ix": 10, "iy": 0, "mean_z": 0.0, "count": 1},
            ]
        }
        utility = {
            "leaves": [
                {"level": 1, "ix": 0, "iy": 0, "mean_z": 0.0, "count": 1},
                {"level": 0, "ix": 20, "iy": 0, "mean_z": 0.0, "count": 1},
            ]
        }
        scored = regional_comparison(
            reference,
            distance,
            utility,
            bbox_xy_m=[-1.0, -1.0, 2.0, 1.0],
            critical_bins={(0, 0)},
        )
        self.assertEqual(scored["promotion_precision"], 0.0)


# Utility hardcore run

"""Fail-closed checks for frozen scenes and comparable governor budgets."""


class HardcoreRunnerTests(unittest.TestCase):
    def test_frozen_real_semantic_region_has_world_aligned_support(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = load_manifest(repo / "benchmarks/utility_challenge_manifest.json")
        challenge = next(
            item
            for item in manifest["challenges"]
            if item["dataset"] == "semanticposs"
            and item["challenge_type"] == "semantic_object"
        )
        if not (repo / challenge["source_scan_path"]).is_file():
            self.skipTest("frozen SemanticPOSS source scan not staged")
        self.assertGreater(len(_critical_bins(repo, challenge)), 0)

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

    def test_world_aligned_adapter_points_are_not_transformed_twice(self):
        pose = np.eye(4)
        pose[:3, 3] = [10.0, -2.0, 0.0]
        transformed = _world_xy(
            np.array([[11.0, 0.0, 0.0, 0.5]]), pose, coordinate_frame="world"
        )
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


# Utility diagnostics

"""Exercise bounded production-policy diagnostics through the real executable."""


class UtilityDiagnosticsTests(unittest.TestCase):
    def test_native_pipeline_logs_do_not_contaminate_json_stdout(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json, os; "
                    "from benchmarks.utility_diagnostics import pipeline_logs_to_stderr; "
                    "\nwith pipeline_logs_to_stderr():\n"
                    " os.write(1, b'Patchwork native initialization\\n')\n"
                    " print('Python pipeline log', flush=True)\n"
                    "print(json.dumps({'valid': True}))"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"valid": True})
        self.assertIn("Patchwork native initialization", result.stderr)
        self.assertIn("Python pipeline log", result.stderr)

    def test_diagnostic_selection_is_bounded(self):
        from benchmarks.utility_diagnostics import validate_selection

        validate_selection(0, 2)
        for start, count in ((-1, 2), (0, 0), (0, 9)):
            with self.subTest(start=start, count=count), self.assertRaises(ValueError):
                validate_selection(start, count)

    def test_opt_in_diagnostics_preserve_map_and_explain_support_gates(self):
        binary = require_binary(
            self, "VEYRA_BENCHMARK_BINARY", "build/apps/benchmark/veyra_benchmark"
        )
        import numpy as np

        observations = []
        for index in range(4):
            original = frame(timestamp=float(index + 1), frame_id=str(index))
            points = original.points.copy()
            points[:, 0] += 45
            observations.append(
                replace(
                    original, points=points, drivable=np.full(2, "unknown", dtype="U15")
                )
            )
        payload, _ = stream_bytes(observations)
        reports = []
        for flags in ([], ["--promotion-telemetry"]):
            result = subprocess.run(
                [
                    str(binary),
                    "--policy",
                    "utility_lod",
                    "--include-leaf-details",
                    *flags,
                ],
                input=payload,
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            reports.append(json.loads(result.stdout))
        plain, diagnostic = reports
        self.assertNotIn("promotion_telemetry", plain)
        self.assertEqual(plain["snapshot"], diagnostic["snapshot"])
        self.assertGreater(len(plain["snapshot"]["leaves"]), 0)
        evidence = diagnostic["promotion_telemetry"]
        self.assertEqual(evidence["diagnostics_version"], 1)
        self.assertEqual(
            sum(evidence["decision_reasons"].values()), evidence["decisions"]
        )
        self.assertEqual(
            sum(evidence["support_histograms"]["point_density"]), evidence["decisions"]
        )
        # Both returns share one 40cm region around 45m in each scan. The
        # range-aware expected support is 3: measured density=2/3, bin 13.
        # Repeating four frames must not accumulate density across scans.
        self.assertEqual(evidence["support_histograms"]["point_density"][13], 8)
        self.assertEqual(evidence["support_histograms"]["point_density"][19], 0)
        self.assertGreater(evidence["quality_failed"], 0)
        self.assertEqual(evidence["density_failed"], 0)
        self.assertEqual(
            sum(row["decisions"] for row in evidence["classes"]), evidence["decisions"]
        )
        self.assertLess(
            evidence["signals"]["semantic"]["effective_weighted_sum"],
            evidence["signals"]["semantic"]["weighted_sum"],
        )


if __name__ == "__main__":
    unittest.main()
