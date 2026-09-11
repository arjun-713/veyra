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
                                    "elevation_vs_fine_reference": {"rmse_m": 0.1},
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


if __name__ == "__main__":
    unittest.main()
