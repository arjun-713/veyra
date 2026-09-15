from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.render_report import render


class RenderReportTests(unittest.TestCase):
    def test_report_renders_all_policy_and_perception_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_report = {
                "dataset": "semanticposs",
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
                "timings": {
                    "semantic": {"mean_ms": 1, "p50_ms": 1, "p95_ms": 2, "p99_ms": 3}
                },
            }
            map_path, perception_path = root / "map.json", root / "perception.json"
            map_path.write_text(json.dumps(map_report))
            perception_path.write_text(json.dumps(perception))
            report = render(map_path, perception_path)
        self.assertIn("Uniform5", report)
        self.assertIn("UtilityLOD", report)
        self.assertIn("SalsaNext", report)
        self.assertIn("Correctness gate: **PASS**", report)
        self.assertIn("Elevation coverage", report)
        self.assertIn("100.0%", report)
        self.assertIn("Ablation matrix was not included", report)

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


if __name__ == "__main__":
    unittest.main()
