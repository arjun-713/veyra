import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.run_benchmark import (
    POLICY_ADAPTERS,
    UTILITY_ABLATION_POLICY_NAMES,
    load_selection,
    mapping_quality_report,
    summarize_perception,
    utility_ablation_report,
)


class ProductBenchmarkTests(unittest.TestCase):
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
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["utility_ablation"]["status"], "complete")
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
