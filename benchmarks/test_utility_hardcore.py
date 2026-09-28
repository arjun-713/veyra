"""Contract tests for frozen, policy-blind challenge selection and scoring."""

from __future__ import annotations

import unittest

import numpy as np

from benchmarks.utility_hardcore import (
    contiguous_window,
    manifest_digest,
    regional_comparison,
    select_geometry_candidates,
    select_semantic_candidate,
)


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


if __name__ == "__main__":
    unittest.main()
