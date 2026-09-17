import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from benchmarks.run_benchmark import (
    POLICY_ADAPTERS,
    UTILITY_ABLATION_POLICY_NAMES,
    SemanticQualityAccumulator,
    _compact_snapshot,
    analytical_3d_reference,
    field_retention_report,
    load_selection,
    mapping_quality_report,
    mixed_resolution_topology_report,
    semantic_range_quality_report,
    summarize_perception,
    utility_ablation_report,
)


class ProductBenchmarkTests(unittest.TestCase):
    def test_compact_snapshot_releases_optional_leaf_rows_after_quality(self):
        snapshot = {"levels": {"0": 1}, "leaves": [{"level": 0, "count": 1}]}
        compact = _compact_snapshot(snapshot)
        self.assertNotIn("leaves", compact)
        self.assertIn("leaves", snapshot)

    def test_streaming_semantic_quality_matches_batch_report(self):
        from benchmarks.test_runtime import frame

        reference = replace(frame(), semantic_class=np.array([1, 2]))
        prediction = replace(frame(), semantic_class=np.array([1, 3]))
        batch = semantic_range_quality_report([reference], [prediction])
        accumulator = SemanticQualityAccumulator()
        accumulator.update(reference, prediction)
        self.assertEqual(accumulator.report(), batch)

    def test_mixed_resolution_topology_checks_observed_bins_independently(self):
        report = mixed_resolution_topology_report(
            {
                "leaves": [
                    {"level": 1, "ix": 0, "iy": 0, "count": 2},
                    {"level": 0, "ix": 0, "iy": 0, "count": 1},
                ],
            },
            {(0, 0), (1, 0), (2, 0)},
        )
        self.assertEqual(report["status"], "invalid")
        self.assertFalse(report["parent_descendant_exclusive"])
        self.assertEqual(report["duplicate_leaf_ids"], 0)
        self.assertEqual(report["observed_bins"]["overlap"], 1)
        self.assertEqual(report["observed_bins"]["gap"], 1)

    def test_mixed_resolution_boundary_with_adjacent_leaves_has_one_owner(self):
        report = mixed_resolution_topology_report(
            {
                "leaves": [
                    {"level": 1, "ix": 1, "iy": 0, "count": 2},
                    {"level": 0, "ix": 0, "iy": 0, "count": 1},
                ],
            },
            {(0, 0), (2, 0), (3, 0)},
        )
        self.assertEqual(report["status"], "valid")
        self.assertTrue(report["parent_descendant_exclusive"])
        self.assertTrue(report["observed_bins"]["exactly_one_owner"])

    def test_field_retention_reports_semantic_and_hazard_preservation(self):
        from benchmarks.test_runtime import frame

        source = frame()
        snapshot = {
            "leaves": [
                {
                    "level": 1,
                    "ix": 0,
                    "iy": 0,
                    "count": 2,
                    "mean_z": 1.0,
                    "semantic_class": 1,
                    "drivable_evidence": -1.0,
                },
                {
                    "level": 1,
                    "ix": -1,
                    "iy": 0,
                    "count": 2,
                    "mean_z": 1.0,
                    "semantic_class": 2,
                    "drivable_evidence": -1.0,
                },
            ]
        }
        report = field_retention_report([source], snapshot)
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["semantic"]["reference_bins"], 2)
        self.assertEqual(report["semantic"]["retained_bins"], 2)
        self.assertEqual(report["terrain_hazard"]["reference_bins"], 1)
        self.assertEqual(report["terrain_hazard"]["retained_bins"], 1)

    def test_sih_validation_entrypoint_has_explicit_real_data_gate(self):
        repo = Path(__file__).resolve().parents[1]
        validator = repo / "scripts/validate_sih.sh"
        self.assertTrue(validator.is_file())
        content = validator.read_text()
        self.assertIn("--full", content)
        self.assertIn("SemanticPOSS", content)
        self.assertIn("benchmarks/run_local.sh", content)
        self.assertNotIn("|| true", content)

    def test_sih_validator_scales_warmup_for_short_real_data_runs(self):
        repo = Path(__file__).resolve().parents[1]
        content = (repo / "scripts/validate_sih.sh").read_text()
        self.assertIn('warmup_frames="${VEYRA_SIH_WARMUP_FRAMES:-10}"', content)
        self.assertIn("if ((warmup_frames >= frames)); then", content)
        self.assertIn('--warmup-frames "$warmup_frames"', content)

    def test_sih_validator_rejects_invalid_full_frame_count_before_build(self):
        repo = Path(__file__).resolve().parents[1]
        environment = {
            **os.environ,
            "VEYRA_SIH_FRAMES": "invalid",
            "VEYRA_PYTHON": "/definitely/not/a/python",
        }
        result = subprocess.run(
            ["bash", "scripts/validate_sih.sh", "--full"],
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("VEYRA_SIH_FRAMES must be a positive integer", result.stderr)

    def test_benchmark_workflows_do_not_hide_failed_evidence(self):
        repo = Path(__file__).resolve().parents[1]
        benchmark_workflow = (repo / ".github/workflows/benchmark.yml").read_text()
        report_workflow = (repo / ".github/workflows/benchmark-report.yml").read_text()
        self.assertIn(
            "Run shared perception and four-policy map benchmark", benchmark_workflow
        )
        self.assertNotIn("--output artifacts/summary.md || true", benchmark_workflow)
        self.assertNotIn("continue-on-error: true", report_workflow)
        self.assertIn("--fail-on-correctness", benchmark_workflow)
        self.assertIn("Overall mIoU", report_workflow)
        self.assertIn("Point conservation", report_workflow)
        self.assertIn("--skip-build", benchmark_workflow)
        self.assertIn("findJson('artifacts/map')", report_workflow)
        self.assertIn("findJson('artifacts/baseline')", report_workflow)

    def test_semantic_quality_is_reported_per_distance_bin(self):
        from benchmarks.test_runtime import frame

        reference = frame()
        prediction = replace(reference, semantic_class=reference.semantic_class.copy())
        report = semantic_range_quality_report([reference], [prediction])
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["overall"]["accuracy"], 1.0)
        self.assertEqual(report["overall"]["miou"], 1.0)
        self.assertEqual(report["range_bins"][0]["points"], 2)
        self.assertEqual(report["range_bins"][0]["miou"], 1.0)

    def test_perception_summary_reports_load_and_bridge_as_distinct_stages(self):
        report = summarize_perception(
            "semanticposs",
            "00",
            [
                {
                    "points": 3,
                    "dataset_load_ms": 4.0,
                    "timings_ms": {
                        "semantic": 10.0,
                        "ground": 2.0,
                        "terrain": 3.0,
                        "temporal": 0.0,
                        "total": 15.0,
                    },
                    "status": {
                        "semantic": "model",
                        "ground": "patchworkpp",
                        "terrain": "available",
                        "temporal": "disabled",
                    },
                    "ground_fraction": 0.5,
                    "known_terrain_fraction": 1.0,
                    "known_motion_fraction": 0.0,
                },
                {
                    "points": 4,
                    "dataset_load_ms": 6.0,
                    "timings_ms": {
                        "semantic": 20.0,
                        "ground": 4.0,
                        "terrain": 6.0,
                        "temporal": 1.0,
                        "total": 31.0,
                    },
                    "status": {
                        "semantic": "model",
                        "ground": "patchworkpp",
                        "terrain": "available",
                        "temporal": "disabled",
                    },
                    "ground_fraction": 0.75,
                    "known_terrain_fraction": 1.0,
                    "known_motion_fraction": 0.0,
                },
            ],
            bridge_samples_ns=[1_000_000, 3_000_000],
        )
        self.assertEqual(report["timings"]["dataset_load"]["p50_ms"], 4.0)
        self.assertEqual(report["timings"]["bridge"]["p95_ms"], 3.0)
        self.assertEqual(report["timings"]["semantic"]["samples"], 2)

    def test_analytical_3d_reference_is_explicitly_not_an_executed_policy(self):
        reference = analytical_3d_reference(
            np.array([[0.0, 0.0, 0.0, 0.0], [0.1, 0.2, 0.3, 0.0]], dtype=np.float32)
        )
        self.assertEqual(reference["status"], "analytical_only")
        self.assertFalse(reference["executed_through_map_engine"])
        self.assertEqual(reference["voxel_size_m"], 0.05)
        self.assertGreater(reference["dense_voxel_count"], 0)

    def test_perception_summary_preserves_stage_tails_and_statuses(self):
        report = summarize_perception(
            "semanticposs",
            "00",
            [
                {
                    "points": 12,
                    "timings_ms": {
                        "semantic": 10.0,
                        "ground": 2.0,
                        "terrain": 3.0,
                        "temporal": 0.0,
                        "total": 15.0,
                    },
                    "status": {
                        "semantic": "model",
                        "ground": "patchworkpp",
                        "terrain": "available",
                        "temporal": "disabled",
                    },
                    "ground_fraction": 0.5,
                    "known_terrain_fraction": 0.25,
                    "known_motion_fraction": 0.0,
                },
                {
                    "points": 20,
                    "timings_ms": {
                        "semantic": 20.0,
                        "ground": 4.0,
                        "terrain": 6.0,
                        "temporal": 1.0,
                        "total": 31.0,
                    },
                    "status": {
                        "semantic": "model",
                        "ground": "patchworkpp",
                        "terrain": "available",
                        "temporal": "disabled",
                    },
                    "ground_fraction": 0.75,
                    "known_terrain_fraction": 0.5,
                    "known_motion_fraction": 0.0,
                },
            ],
        )
        self.assertEqual(report["dataset"], "semanticposs")
        self.assertEqual(report["sequence"], "00")
        self.assertEqual(report["points_processed"], 32)
        self.assertEqual(report["timings"]["semantic"]["p50_ms"], 10.0)
        self.assertEqual(report["timings"]["semantic"]["p95_ms"], 20.0)
        self.assertEqual(
            report["status"],
            {
                "semantic": "model",
                "ground": "patchworkpp",
                "terrain": "available",
                "temporal": "disabled",
            },
        )
        self.assertAlmostEqual(report["ground_ratio"], 0.625)
        self.assertAlmostEqual(report["known_terrain_fraction"], 0.375)

    def test_utility_ablation_matrix_has_distance_components_and_full_policy(self):
        expected = {
            "ablation_distance",
            "ablation_geometry",
            "ablation_semantics",
            "ablation_motion",
            "utility_lod",
        }
        self.assertTrue(expected.issubset(POLICY_ADAPTERS))
        self.assertEqual(
            POLICY_ADAPTERS["ablation_distance"].cpp_policy, "distance_lod"
        )
        for name in expected - {"ablation_distance"}:
            self.assertEqual(POLICY_ADAPTERS[name].cpp_policy, "utility_lod")

    def test_ablation_report_is_explicit_about_directions_and_missing_members(self):
        def policy(rmse, level, latency, rss, leaves):
            return {
                "aggregate": {
                    "stage_latency_ns": {"map_update": {"p95": latency}},
                    "peak_rss_bytes": rss,
                    "final_leaves_per_level": {"0": leaves},
                },
                "runs": [
                    {
                        "quality": {"elevation_vs_fine_reference": {"rmse_m": rmse}},
                        "detail_metric": {"weighted_mean_level": level},
                    }
                ],
            }

        report = utility_ablation_report(
            {
                "ablation_distance": policy(0.4, 2.0, 100, 1_000, 20),
                "utility_lod": policy(0.2, 1.5, 110, 1_100, 24),
            }
        )
        self.assertEqual(report["status"], "partial")
        self.assertEqual(
            report["missing_policies"],
            ["ablation_geometry", "ablation_semantics", "ablation_motion"],
        )
        full = report["members"]["utility_lod"]
        self.assertAlmostEqual(full["delta_vs_distance"]["elevation_rmse_m"], -0.2)
        self.assertAlmostEqual(full["delta_vs_distance"]["map_latency_fraction"], 0.1)
        self.assertEqual(
            report["full_vs_distance_assessment"],
            "quality_improved_with_measured_resource_increase",
        )
        self.assertEqual(
            utility_ablation_report({"utility_lod": policy(0.2, 1.5, 110, 1100, 24)})[
                "status"
            ],
            "not_run",
        )

    def test_tiny_generic_dataset_executes_complete_ablation_matrix(self):
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        if not binary or not Path(binary).is_file():
            self.skipTest("set VEYRA_BENCHMARK_BINARY to run the C++ ablation smoke")
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            np.array(
                [[12.01, 0.01, 0.0, 0.5], [12.06, 0.01, 1.0, 0.6]],
                dtype="<f4",
            ).tofile(root / "scan.bin")
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "dataset": "fixture",
                        "point_schema": {
                            "format": "xyzi",
                            "coordinate_frame": "sensor",
                            "intensity_semantics": "reflectance",
                        },
                        "taxonomy": {"version": "v1", "mapping": {}},
                        "frames": [
                            {
                                "sequence": "s",
                                "frame_id": frame_id,
                                "points": {
                                    "path": "scan.bin",
                                    "format": "xyzi_f32_bin",
                                },
                            }
                            for frame_id in ("000001", "000002")
                        ],
                    }
                )
            )
            output = root / "result.json"
            csv_output = root / "result.csv"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo / "benchmarks/run_benchmark.py"),
                    "--repo",
                    str(repo),
                    "--binary",
                    binary,
                    "--dataset",
                    "generic",
                    "--dataset-root",
                    str(root),
                    "--sequence",
                    "s",
                    "--count",
                    "2",
                    "--warmup-frames",
                    "0",
                    "--repetitions",
                    "1",
                    "--skip-perception",
                    "--policies",
                    ",".join(UTILITY_ABLATION_POLICY_NAMES),
                    "--output",
                    str(output),
                    "--csv-output",
                    str(csv_output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["utility_ablation"]["status"], "complete")
            csv_header = csv_output.read_text().splitlines()[0]
            self.assertIn("semantic_miou", csv_header)
            self.assertIn("analytical_3d_estimated_bytes", csv_header)
            self.assertEqual(
                set(result["utility_ablation"]["members"]),
                set(UTILITY_ABLATION_POLICY_NAMES),
            )
            for policy in UTILITY_ABLATION_POLICY_NAMES:
                governor = result["policies"][policy]["aggregate"]["governor"]
                self.assertIn("interventions", governor)
                self.assertIn("actions_applied", governor)

    def test_coarse_mean_does_not_hide_lost_height_detail(self):
        report = mapping_quality_report(
            np.array([[0.01, 0.01, 0], [0.06, 0.01, 2]]),
            0,
            {
                "point_count": 2,
                "leaves": [{"level": 1, "ix": 0, "iy": 0, "count": 2, "mean_z": 1}],
                "invariant_no_parent_descendant_overlap": True,
            },
            {"mean_z_by_cell": {(0, 0): 0, (1, 0): 2, (10, 10): 4}},
        )["elevation_vs_fine_reference"]
        self.assertEqual(report["rmse_m"], 1.0)
        self.assertEqual(report["sample_count"], 2)
        self.assertAlmostEqual(report["coverage"], 2 / 3)

    def test_generic_selected_root_uses_existing_manifest_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            np.array([[1, 0, 2, 0.5]], dtype="<f4").tofile(root / "scan.bin")
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "dataset": "fixture",
                        "point_schema": {
                            "format": "xyzi",
                            "coordinate_frame": "sensor",
                            "intensity_semantics": "reflectance",
                        },
                        "taxonomy": {"version": "v1", "mapping": {"10": 1}},
                        "frames": [
                            {
                                "sequence": "s",
                                "frame_id": "000001",
                                "points": {
                                    "path": "scan.bin",
                                    "format": "xyzi_f32_bin",
                                },
                            }
                        ],
                    }
                )
            )
            frames, _, _, _, _ = load_selection(
                Path(__file__).resolve().parents[1],
                "generic",
                "s",
                0,
                1,
                run_perception=False,
                dataset_root=root,
            )
            self.assertEqual(len(frames), 1)
            np.testing.assert_allclose(frames[0].points, [[1, 0, 2, 0.5]])


if __name__ == "__main__":
    unittest.main()
