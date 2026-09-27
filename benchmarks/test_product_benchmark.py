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
    _field_reference,
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
    def test_provenance_fingerprints_dirty_source_but_excludes_generated_reports(self):
        from benchmarks.run_benchmark import _git_source_state

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "audit@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Veyra Test"],
                check=True,
            )
            (repo / "tracked.py").write_text("VALUE = 1\\n")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.py"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "baseline"],
                check=True,
            )
            (repo / "tracked.py").write_text("VALUE = 2\\n")
            (repo / "benchmarks").mkdir()
            (repo / "benchmarks" / "new_eval.py").write_text("VALUE = 3\\n")
            (repo / "reports").mkdir()
            report_file = repo / "reports" / "result.json"
            report_file.write_text('{"run":1}')

            first = _git_source_state(repo)
            report_file.write_text('{"run":2}')
            second = _git_source_state(repo)
            self.assertTrue(first["working_tree_dirty"])
            self.assertFalse(first["execution_source_clean"])
            self.assertEqual(
                first["source_state_sha256"], second["source_state_sha256"]
            )
            self.assertEqual(
                first["untracked_source_files"], ["benchmarks/new_eval.py"]
            )

            (repo / "benchmarks" / "new_eval.py").write_text("VALUE = 4\\n")
            changed = _git_source_state(repo)
            self.assertNotEqual(
                first["source_state_sha256"], changed["source_state_sha256"]
            )

    def test_clean_source_gate_preserves_unrelated_untracked_artifacts(self):
        from benchmarks.run_benchmark import _git_source_state, run
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / ":memory:.ses").write_text("unrelated session")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Veyra Test",
                    "-c",
                    "user.email=audit@example.test",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "baseline",
                ],
                check=True,
            )
            state = _git_source_state(repo)
            self.assertTrue(state["working_tree_dirty"])
            self.assertTrue(state["execution_source_clean"])
            for name in ("widget.svelte", "helper.rs", "rules.cmake"):
                path = repo / name
                path.write_text("uncommitted runtime source\n")
                self.assertFalse(_git_source_state(repo)["execution_source_clean"])
                path.unlink()
            (repo / "new_source.py").write_text("VALUE = 1\n")
            args = SimpleNamespace(
                repo=repo,
                start=0,
                count=2,
                warmup_frames=0,
                repetitions=1,
                policies="uniform5",
                require_clean_source=True,
            )
            # Must reject dirty source BEFORE reading datasets or launching a mapper.
            with self.assertRaisesRegex(ValueError, "clean committed source"):
                run(args)

    def test_staged_backend_reports_its_manifest_identity_not_an_enclosing_repo(self):
        from benchmarks.run_benchmark import _source_identity

        with tempfile.TemporaryDirectory() as directory:
            enclosing = Path(directory)
            subprocess.run(["git", "init", "-q", str(enclosing)], check=True)
            backend = enclosing / "Veyra.app/Contents/Resources/backend"
            (backend / "runtime").mkdir(parents=True)
            (backend / "runtime/__main__.py").write_text("\n")
            (backend / "manifest.json").write_text(
                json.dumps(
                    {
                        "product": "veyra",
                        "source": {"git_sha": "abc123", "working_tree_dirty": False},
                    }
                )
            )
            identity = _source_identity(backend)
            self.assertEqual(identity["git_sha"], "abc123")
            self.assertIs(identity["working_tree_dirty"], False)
            self.assertEqual(identity["source_identity"], "backend_manifest")

            (backend / "manifest.json").unlink()
            self.assertEqual(_source_identity(backend)["source_identity"], "git")

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
        cached = field_retention_report(
            [source], snapshot, fine_reference=_field_reference([source])
        )
        self.assertEqual(report, cached)

    def test_sih_validation_entrypoint_has_explicit_real_data_gate(self):
        repo = Path(__file__).resolve().parents[1]
        validator = repo / "scripts/validate_sih.sh"
        self.assertTrue(validator.is_file())
        content = validator.read_text()
        self.assertIn("--full", content)
        self.assertIn("SemanticPOSS", content)
        self.assertIn("benchmarks/run_local.sh", content)
        self.assertIn("validate_submission_closure.py", content)
        self.assertNotIn("|| true", content)

    def test_full_sih_validation_requires_real_perception_evidence_first(self):
        repo = Path(__file__).resolve().parents[1]
        content = (repo / "scripts/validate_sih.sh").read_text()
        perception_validation = content.index("-m scripts.validate_perception")
        cpp_configuration = content.index("cmake -S . -B")
        benchmark = content.index("benchmarks/run_local.sh")
        self.assertLess(perception_validation, cpp_configuration)
        self.assertLess(perception_validation, benchmark)
        self.assertIn("VEYRA_SIH_PERCEPTION_CONFIG", content)
        self.assertIn('--perception-output "$perception_output"', content)
        self.assertNotIn('salsanext.onnx"', content)

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

    def test_full_sih_validator_reports_missing_real_data_before_build(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["bash", str(repo / "scripts/validate_sih.sh"), "--full"],
                cwd=directory,
                env={
                    **os.environ,
                    "VEYRA_SIH_FRAMES": "1",
                    "VEYRA_SIH_QUALITY_FRAMES": "1",
                    "VEYRA_SIH_BUILD_DIR": str(Path(directory) / "must-not-build"),
                },
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertIn("REAL DATA: UNAVAILABLE", result.stderr)
        self.assertIn("semanticposs/dataset", result.stderr)

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

    def test_ci_uses_tauri_for_fast_and_manual_desktop_validation(self):
        repo = Path(__file__).resolve().parents[1]
        ci = (repo / ".github/workflows/ci.yml").read_text()
        tauri = (repo / ".github/workflows/desktop-tauri.yml").read_text()
        self.assertFalse((repo / ".github/workflows/product.yml").exists())
        self.assertIn("branches: [main]", ci)
        self.assertIn("workflow_dispatch:", tauri)
        self.assertNotIn("pull_request:", tauri)
        self.assertIn("stage_tauri_backend.py", tauri)
        self.assertIn("resources/backend", tauri)

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
            [
                "ablation_geometry",
                "ablation_semantics",
                "ablation_motion",
                "ablation_traversability",
            ],
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

    def test_quality_metrics_compare_each_policy_to_common_observed_uniform5_bins(self):
        from benchmarks.run_benchmark import elevation_surface_metrics

        reference = {
            "mean_z_by_cell": {(0, 0): 0.0, (1, 0): 2.0, (2, 0): 4.0},
        }
        snapshot = {
            "leaves": [
                {"level": 1, "ix": 0, "iy": 0, "count": 2, "mean_z": 1.0},
            ]
        }

        result = elevation_surface_metrics(snapshot, reference, tolerance_m=0.10)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reference_bins"], 3)
        self.assertEqual(result["matched_bins"], 2)
        self.assertAlmostEqual(result["completion_fraction"], 2 / 3)
        self.assertEqual(result["height_accuracy_fraction_within_10cm"], 0.0)
        self.assertAlmostEqual(result["symmetric_chamfer_m"], 1.0)
        self.assertEqual(result["chamfer_sample_count"], 2)
        self.assertFalse(result["reference_is_ground_truth"])

    def test_range_bins_include_chamfer_from_the_same_common_support_queries(self):
        from benchmarks.run_benchmark import elevation_surface_metrics

        keys = ((0, 0), (100, 0), (200, 0))
        reference = {
            "mean_z_by_cell": {key: 0.0 for key in keys},
            "mean_range_by_cell": dict(zip(keys, (5.0, 20.0, 70.0), strict=True)),
        }
        snapshot = {
            "leaves": [
                {"level": 0, "ix": ix, "iy": iy, "count": 1, "mean_z": z}
                for (ix, iy), z in zip(keys, (0.0, 0.0, 0.2), strict=True)
            ]
        }

        result = elevation_surface_metrics(snapshot, reference)
        ranges = result["by_range"]

        self.assertEqual(ranges[0]["symmetric_chamfer_m"], 0.0)
        self.assertEqual(ranges[1]["symmetric_chamfer_m"], 0.0)
        self.assertGreater(ranges[3]["symmetric_chamfer_m"], 0.0)

    def test_range_chamfer_does_not_match_points_from_another_distance_band(self):
        from benchmarks.run_benchmark import elevation_surface_metrics

        keys = ((199, 0), (200, 0))
        result = elevation_surface_metrics(
            {
                "leaves": [
                    {"level": 0, "ix": ix, "iy": iy, "count": 1, "mean_z": z}
                    for (ix, iy), z in zip(keys, (0.0, 0.2), strict=True)
                ]
            },
            {
                "mean_z_by_cell": dict.fromkeys(keys, 0.0),
                "mean_range_by_cell": dict(zip(keys, (9.99, 10.01), strict=True)),
            },
        )

        # The far-band reconstruction contains only its own point, so its
        # symmetric Chamfer is the 20 cm vertical discrepancy. A global tree
        # can incorrectly match the adjacent near-band sample instead.
        self.assertAlmostEqual(result["by_range"][1]["symmetric_chamfer_m"], 0.2)

    def test_quality_metrics_keep_missing_reference_support_out_of_accuracy_denominator(
        self,
    ):
        from benchmarks.run_benchmark import elevation_surface_metrics

        result = elevation_surface_metrics(
            {"leaves": [{"level": 0, "ix": 0, "iy": 0, "count": 1, "mean_z": 3.0}]},
            {"mean_z_by_cell": {(0, 0): 3.0, (10, 10): -1.0}},
        )

        self.assertEqual(result["height_accuracy_fraction_within_10cm"], 1.0)
        self.assertEqual(result["completion_fraction"], 0.5)
        self.assertEqual(result["symmetric_chamfer_m"], 0.0)

    def test_quality_metrics_mark_empty_reference_unavailable_not_zero(self):
        from benchmarks.run_benchmark import elevation_surface_metrics

        result = elevation_surface_metrics({"leaves": []}, {"mean_z_by_cell": {}})

        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["height_accuracy_fraction_within_10cm"])
        self.assertIsNone(result["completion_fraction"])
        self.assertIsNone(result["symmetric_chamfer_m"])

    def test_quality_metrics_reject_duplicate_active_owners(self):
        from benchmarks.run_benchmark import elevation_surface_metrics

        result = elevation_surface_metrics(
            {
                "leaves": [
                    {"level": 1, "ix": 0, "iy": 0, "count": 4, "mean_z": 0.0},
                    {"level": 0, "ix": 1, "iy": 0, "count": 1, "mean_z": 0.0},
                ]
            },
            {"mean_z_by_cell": {(1, 0): 0.0}},
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["duplicate_owner_bins"], 1)
        self.assertIsNone(result["height_accuracy_10cm"])
        self.assertIsNone(result["symmetric_chamfer_m"])

    def test_quality_metrics_report_explicit_height_tolerances_and_rmse(self):
        from benchmarks.run_benchmark import elevation_surface_metrics

        reference = {"mean_z_by_cell": {(index, 0): 0.0 for index in range(4)}}
        snapshot = {
            "leaves": [
                {"level": 0, "ix": index, "iy": 0, "count": 1, "mean_z": error}
                for index, error in enumerate((0.0, 0.06, 0.12, 0.25))
            ]
        }

        result = elevation_surface_metrics(snapshot, reference)

        self.assertEqual(result["height_accuracy_05cm"], 0.25)
        self.assertEqual(result["height_accuracy_10cm"], 0.5)
        self.assertEqual(result["height_accuracy_20cm"], 0.75)
        self.assertAlmostEqual(
            result["elevation_rmse_m"], np.sqrt((0.06**2 + 0.12**2 + 0.25**2) / 4)
        )

    def test_quality_metrics_fail_closed_on_nonfinite_leaf_elevation(self):
        from benchmarks.run_benchmark import elevation_surface_metrics

        with self.assertRaisesRegex(ValueError, "leaf elevation must be finite"):
            elevation_surface_metrics(
                {
                    "leaves": [
                        {"level": 0, "ix": 0, "iy": 0, "count": 1, "mean_z": np.inf}
                    ]
                },
                {"mean_z_by_cell": {(0, 0): 0.0}},
            )

    def test_fine_reference_uses_the_final_active_uniform5_support(self):
        from benchmarks.run_benchmark import _fine_reference_for_snapshot
        from benchmarks.test_runtime import frame

        reference = _fine_reference_for_snapshot(
            [frame()],
            {"leaves": [{"level": 0, "ix": 0, "iy": 0, "count": 1, "mean_z": 8.0}]},
        )

        self.assertEqual(reference["mean_z_by_cell"], {(0, 0): 8.0})
        self.assertEqual(set(reference["mean_range_by_cell"]), {(0, 0)})

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
