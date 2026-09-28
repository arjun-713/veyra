from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.render_report import (
    _field_retention_summary,
    _hard_failure,
    _perception_status_summary,
    _perception_table,
    render,
)


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
