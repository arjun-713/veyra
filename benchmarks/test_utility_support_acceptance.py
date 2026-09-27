"""Acceptance must not hide a loss of task support behind finer topology."""

import unittest
from pathlib import Path

from benchmarks.utility_hardcore_run import load_manifest
from benchmarks.utility_support_acceptance import (
    acceptance,
    compact,
    frozen_semantic_window,
)


class SupportAcceptanceTests(unittest.TestCase):
    def test_unchanged_selection_contains_four_existing_masks(self):
        manifest = load_manifest(
            Path(__file__).resolve().parents[1]
            / "benchmarks/utility_challenge_manifest.json"
        )
        selected = frozen_semantic_window(manifest)
        self.assertEqual(len(selected), 4)
        self.assertTrue(
            all(
                item["frame_start"] == 0 and item["frame_end_exclusive"] == 10
                for item in selected
            )
        )

    def test_compaction_preserves_cache_accounting_and_provenance(self):
        report = {
            "provenance": {"git_sha": "abc"},
            "snapshot": {"leaves": [1], "memory": {"detail_sketch_logical_bytes": 12}},
        }
        result = compact(report)
        self.assertEqual(result["provenance"], report["provenance"])
        self.assertEqual(result["snapshot"]["memory"], report["snapshot"]["memory"])
        self.assertNotIn("leaves", result["snapshot"])

    def test_better_accuracy_without_completion_cannot_pass(self):
        baseline = dict(
            challenge_id="x",
            policy="distance_lod",
            promotion_recall=0.0,
            promotion_precision=0.0,
            critical_completion=1.0,
            semantic_retention_critical=1.0,
            critical_accuracy_10cm=0.5,
            critical_chamfer_m=0.1,
        )
        utility = dict(
            baseline,
            policy="utility_lod",
            promotion_recall=0.1,
            promotion_precision=0.1,
            critical_accuracy_10cm=0.6,
            critical_completion=0.8,
        )
        self.assertEqual(
            acceptance([baseline, utility])["critical_benefit_gate"], "NO_GO"
        )
        utility["critical_completion"] = 1.0
        self.assertEqual(
            acceptance([baseline, utility])["critical_benefit_gate"], "PASS"
        )
        utility["critical_chamfer_m"] = None
        self.assertEqual(
            acceptance([baseline, utility])["critical_benefit_gate"], "NO_GO"
        )


if __name__ == "__main__":
    unittest.main()
