from __future__ import annotations

import unittest

import numpy as np

from benchmarks.costmap_eval import (
    QUADRUPED_PROFILE,
    UGV_PROFILE,
    CostGrid,
    build_cost_grid,
    plan_grid,
)


class CostmapEvaluationTests(unittest.TestCase):
    def test_astar_and_dijkstra_return_equal_optimal_cost(self):
        traversable = np.ones((7, 7), dtype=bool)
        traversable[1:6, 3] = False
        traversable[3, 3] = True
        costs = np.ones((7, 7), dtype=np.float32)
        costs[3, 3] = 4.0
        grid = CostGrid(0, 0, traversable, costs)

        astar = plan_grid(grid, (0, 3), (6, 3), algorithm="astar")
        dijkstra = plan_grid(grid, (0, 3), (6, 3), algorithm="dijkstra")

        self.assertTrue(astar["success"])
        self.assertTrue(dijkstra["success"])
        self.assertAlmostEqual(astar["path_cost"], dijkstra["path_cost"])
        self.assertGreater(astar["path_length_m"], 0.0)
        self.assertLessEqual(astar["expanded_nodes"], dijkstra["expanded_nodes"])

    def test_planner_rejects_unknown_and_blocked_endpoints(self):
        grid = CostGrid(
            0,
            0,
            np.array([[True, False, True]], dtype=bool),
            np.ones((1, 3), dtype=np.float32),
        )

        result = plan_grid(grid, (0, 0), (2, 0), algorithm="astar")

        self.assertFalse(result["success"])
        self.assertEqual(result["path"], [])
        self.assertIsNone(result["path_length_m"])

    def test_equal_cost_routes_are_deterministic(self):
        grid = CostGrid(
            0, 0, np.ones((5, 5), dtype=bool), np.ones((5, 5), dtype=np.float32)
        )

        first = plan_grid(grid, (0, 0), (4, 4), algorithm="astar")
        second = plan_grid(grid, (0, 0), (4, 4), algorithm="astar")

        self.assertEqual(first["path"], second["path"])

    def test_reference_hazards_are_counted_independently_of_the_profile_costmap(self):
        planning_grid = CostGrid(
            10,
            -2,
            np.ones((1, 5), dtype=bool),
            np.ones((1, 5), dtype=np.float32),
        )
        reference = CostGrid(
            10,
            -2,
            np.array([[True, True, False, True, True]], dtype=bool),
            np.ones((1, 5), dtype=np.float32),
            unknown=np.zeros((1, 5), dtype=bool),
            hazards=np.array([[False, False, True, False, False]], dtype=bool),
        )

        result = plan_grid(
            planning_grid,
            (10, -2),
            (14, -2),
            reference_grid=reference,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["reference_hazard_crossings"], 1)
        self.assertEqual(result["reference_unknown_crossings"], 0)

    def test_missing_reference_is_reported_as_unavailable_not_zero(self):
        grid = CostGrid(
            0, 0, np.ones((1, 2), dtype=bool), np.ones((1, 2), dtype=np.float32)
        )

        result = plan_grid(grid, (0, 0), (1, 0))

        self.assertIsNone(result["reference_hazard_crossings"])
        self.assertIsNone(result["reference_unknown_crossings"])

    def test_resolution_boundary_count_uses_local_indices_at_nonzero_origin(self):
        grid = CostGrid(
            -3,
            7,
            np.ones((1, 3), dtype=bool),
            np.ones((1, 3), dtype=np.float32),
            levels=np.array([[0, 1, 1]], dtype=np.int8),
        )

        result = plan_grid(grid, (-3, 7), (-1, 7))

        self.assertTrue(result["success"])
        self.assertEqual(result["resolution_boundary_crossings"], 1)

    def test_planner_search_expansion_limit_is_reported(self):
        grid = CostGrid(
            0, 0, np.ones((20, 20), dtype=bool), np.ones((20, 20), dtype=np.float32)
        )

        result = plan_grid(grid, (0, 0), (19, 19), max_expansions=1)

        self.assertFalse(result["success"])
        self.assertEqual(result["failure"], "search_limit")
        self.assertLessEqual(result["expanded_nodes"], 1)

    def test_planner_ablation_report_reuses_each_policy_snapshot_for_both_profiles(
        self,
    ):
        from benchmarks.costmap_eval import planner_evaluation_report

        snapshot = {
            "leaves": [
                {
                    "level": 0,
                    "ix": ix,
                    "iy": iy,
                    "semantic_class": 9,
                    "semantic_confidence": 1.0,
                    "ground_count": 4,
                    "ground_mean_z": 0.0,
                    "ground_stddev_m": 0.01,
                    "ground_gradient_x": 0.5 if (ix, iy) == (2, 1) else 0.0,
                    "ground_gradient_y": 0.0,
                    "ground_gradient_count": 4,
                    "obstacle_count": 0,
                    "overhead_count": 0,
                    "drivable_evidence": 1.0,
                    "terrain_confidence": 1.0,
                    "geometry_complexity": 0.0,
                    "occupancy_logodds": 847,
                }
                for iy in range(3)
                for ix in range(5)
            ]
        }
        snapshots = {
            policy: {"stream_digest": "same", **snapshot}
            for policy in ("uniform5", "uniform40", "distance_lod", "utility_lod")
        }

        result = planner_evaluation_report(snapshots)

        self.assertEqual(result["status"], "measured")
        self.assertTrue(result["same_physical_snapshot_for_profiles"]["uniform5"])
        ugv = [
            item
            for item in result["runs"]
            if item["policy"] == "uniform5" and item["profile"] == "ugv_eval"
        ]
        self.assertEqual(len(ugv), 6)
        self.assertEqual(
            {tuple(item["start"]) for item in ugv}, {tuple(ugv[0]["start"])}
        )
        self.assertEqual({tuple(item["goal"]) for item in ugv}, {tuple(ugv[0]["goal"])})
        self.assertTrue(all(item["status"] == "measured" for item in ugv))
        ugv_full = next(item for item in ugv if item["ablation"] == "full")
        quadruped_full = next(
            item
            for item in result["runs"]
            if item["policy"] == "uniform5"
            and item["profile"] == "quadruped_eval"
            and item["ablation"] == "full"
        )
        self.assertNotEqual(ugv_full["path_sha256"], quadruped_full["path_sha256"])

    def test_planner_comparison_is_invalid_when_policy_stream_digests_differ(self):
        from benchmarks.costmap_eval import planner_evaluation_report

        leaf = {
            "level": 0,
            "ix": 0,
            "iy": 0,
            "semantic_class": 9,
            "semantic_confidence": 1.0,
            "ground_count": 1,
            "ground_mean_z": 0.0,
            "ground_stddev_m": 0.0,
            "ground_gradient_x": 0.0,
            "ground_gradient_y": 0.0,
            "ground_gradient_count": 1,
            "obstacle_count": 0,
            "overhead_count": 0,
            "drivable_evidence": 1.0,
            "terrain_confidence": 1.0,
            "geometry_complexity": 0.0,
            "occupancy_logodds": 847,
        }
        snapshots = {
            policy: {"stream_digest": "stream-a", "leaves": [leaf]}
            for policy in ("uniform5", "uniform40", "distance_lod", "utility_lod")
        }
        snapshots["utility_lod"]["stream_digest"] = "stream-b"

        result = planner_evaluation_report(snapshots)

        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["same_input_for_all_policies"])
        self.assertIn("stream digest", result["reason"])
        self.assertEqual(result["runs"], [])

    def test_planner_uses_one_bounded_uniform5_reference_roi_for_all_policies(self):
        from benchmarks.costmap_eval import planner_evaluation_report

        leaves = [
            {
                "level": 0,
                "ix": ix,
                "iy": iy,
                "semantic_class": 9,
                "semantic_confidence": 1.0,
                "ground_count": 1,
                "ground_mean_z": 0.0,
                "ground_stddev_m": 0.0,
                "ground_gradient_x": 0.0,
                "ground_gradient_y": 0.0,
                "ground_gradient_count": 1,
                "obstacle_count": 0,
                "overhead_count": 0,
                "drivable_evidence": 1.0,
                "terrain_confidence": 1.0,
                "geometry_complexity": 0.0,
                "occupancy_logodds": -405,
            }
            for iy in range(5)
            for ix in range(5)
        ]
        snapshots = {
            policy: {"stream_digest": "same-stream", "leaves": leaves}
            for policy in ("uniform5", "uniform40", "distance_lod", "utility_lod")
        }

        result = planner_evaluation_report(
            snapshots, max_grid_cells=9, max_expansions=100
        )

        self.assertEqual(result["status"], "measured")
        self.assertEqual(result["same_input_for_all_policies"], True)
        self.assertEqual(result["evaluation_roi"]["width_cells"], 3)
        self.assertEqual(result["evaluation_roi"]["height_cells"], 3)
        self.assertLessEqual(
            result["evaluation_roi"]["width_cells"]
            * result["evaluation_roi"]["height_cells"],
            9,
        )
        self.assertTrue(all(item["status"] == "measured" for item in result["runs"]))

    def test_planner_uses_geometric_ground_support_when_semantics_are_unknown(self):
        from benchmarks.costmap_eval import planner_evaluation_report

        leaves = [
            {
                "level": 0,
                "ix": ix,
                "iy": iy,
                "semantic_class": 0,
                "semantic_confidence": 0.0,
                "ground_count": 4,
                "ground_mean_z": 0.0,
                "ground_stddev_m": 0.01,
                "ground_gradient_x": 0.0,
                "ground_gradient_y": 0.0,
                "ground_gradient_count": 4,
                "obstacle_count": 0,
                "overhead_count": 0,
                "drivable_evidence": 0.0,
                "terrain_confidence": 0.9,
                "occupancy_logodds": 0,
            }
            for iy in range(3)
            for ix in range(3)
        ]
        snapshots = {
            policy: {"stream_digest": "same", "leaves": leaves}
            for policy in ("uniform5", "uniform40", "distance_lod", "utility_lod")
        }

        report = planner_evaluation_report(snapshots)

        self.assertEqual(report["status"], "measured")
        self.assertEqual(
            report["endpoint_selection"],
            "same per-profile endpoints for every policy and ablation, selected from largest 4-connected Uniform5 geometric-ground-support component; this does not assert semantic drivable status",
        )
        self.assertIsNotNone(report["endpoints_by_profile"]["ugv_eval"])
        geometry = next(
            row
            for row in report["runs"]
            if row["policy"] == "uniform5"
            and row["profile"] == "ugv_eval"
            and row["ablation"] == "geometry_only"
        )
        full = next(
            row
            for row in report["runs"]
            if row["policy"] == "uniform5"
            and row["profile"] == "ugv_eval"
            and row["ablation"] == "full"
        )
        self.assertTrue(geometry["planner_success"])
        self.assertFalse(full["planner_success"])
        self.assertEqual(full["failure"], "start_or_goal_unknown_or_blocked")

    def test_roi_clips_coarse_leaf_to_world_aligned_fine_bins(self):
        from benchmarks.costmap_eval import UGV_PROFILE, build_cost_grid

        snapshot = {
            "leaves": [
                {"level": 1, "ix": 0, "iy": 0, "occupancy_logodds": -405},
                {"level": 0, "ix": 2, "iy": 0, "occupancy_logodds": -405},
            ]
        }

        grid = build_cost_grid(
            snapshot,
            UGV_PROFILE,
            ablation="occupancy_only",
            max_grid_cells=4,
            roi_bounds=(1, 0, 2, 2),
        )

        self.assertEqual((grid.origin_ix, grid.origin_iy), (1, 0))
        self.assertEqual(grid.traversable.shape, (2, 1))
        self.assertTrue(grid.traversable.all())
        self.assertTrue((grid.levels == 1).all())

    def test_snapshot_rasterization_uses_ground_layers_and_profile_slope_limits(self):
        snapshot = {
            "leaves": [
                {
                    "level": 0,
                    "ix": 0,
                    "iy": 0,
                    "ground_count": 4,
                    "ground_mean_z": 0.0,
                    "ground_stddev_m": 0.01,
                    "ground_gradient_x": 0.5,
                    "ground_gradient_y": 0.0,
                    "ground_gradient_count": 4,
                    "semantic_class": 9,
                    "semantic_confidence": 1.0,
                    "obstacle_count": 0,
                    "overhead_count": 0,
                    "drivable_evidence": 1.0,
                    "terrain_confidence": 0.9,
                    "occupancy_logodds": 847,
                },
                {
                    "level": 0,
                    "ix": 1,
                    "iy": 0,
                    "ground_count": 4,
                    "ground_mean_z": 0.0,
                    "ground_stddev_m": 0.01,
                    "ground_gradient_x": 0.5,
                    "ground_gradient_y": 0.0,
                    "ground_gradient_count": 4,
                    "semantic_class": 9,
                    "semantic_confidence": 1.0,
                    "obstacle_count": 0,
                    "overhead_count": 0,
                    "drivable_evidence": 1.0,
                    "terrain_confidence": 0.9,
                    "occupancy_logodds": 847,
                },
            ]
        }

        ugv = build_cost_grid(snapshot, UGV_PROFILE, ablation="full")
        quadruped = build_cost_grid(snapshot, QUADRUPED_PROFILE, ablation="full")

        self.assertEqual(ugv.traversable.tolist(), [[False, False]])
        self.assertEqual(quadruped.traversable.tolist(), [[True, True]])

    def test_full_costmap_uses_robot_profile_not_generic_drivable_threshold(self):
        snapshot = {
            "leaves": [
                {
                    "level": 0,
                    "ix": 0,
                    "iy": 0,
                    "semantic_class": 9,
                    "semantic_confidence": 1.0,
                    "ground_count": 4,
                    "ground_mean_z": 0.0,
                    "ground_stddev_m": 0.01,
                    "ground_gradient_x": 0.5,
                    "ground_gradient_y": 0.0,
                    "ground_gradient_count": 4,
                    "obstacle_count": 0,
                    "overhead_count": 0,
                    "drivable_evidence": -0.8,
                    "terrain_confidence": 0.9,
                }
            ]
        }

        wheeled = build_cost_grid(snapshot, UGV_PROFILE, ablation="full")
        quadruped = build_cost_grid(snapshot, QUADRUPED_PROFILE, ablation="full")

        self.assertFalse(wheeled.traversable[0, 0])
        self.assertTrue(quadruped.traversable[0, 0])
        self.assertFalse(quadruped.unknown[0, 0])

    def test_missing_ground_evidence_is_unknown_not_free(self):
        snapshot = {
            "leaves": [
                {
                    "level": 0,
                    "ix": 0,
                    "iy": 0,
                    "count": 10,
                    "mean_z": 0.0,
                    "occupancy_logodds": -1992,
                }
            ]
        }

        grid = build_cost_grid(snapshot, UGV_PROFILE, ablation="full")

        self.assertEqual(grid.traversable.tolist(), [[False]])
        self.assertEqual(grid.unknown.tolist(), [[True]])

    def test_coarse_leaf_expands_to_nonoverlapping_five_centimeter_evaluation_cells(
        self,
    ):
        snapshot = {
            "leaves": [
                {
                    "level": 2,
                    "ix": -1,
                    "iy": 3,
                    "count": 16,
                    "ground_count": 16,
                    "ground_mean_z": 1.0,
                    "ground_stddev_m": 0.01,
                    "ground_gradient_x": 0.0,
                    "ground_gradient_y": 0.0,
                    "ground_gradient_count": 16,
                    "semantic_class": 9,
                    "semantic_confidence": 1.0,
                    "obstacle_count": 0,
                    "overhead_count": 0,
                    "drivable_evidence": 1.0,
                    "terrain_confidence": 0.9,
                    "occupancy_logodds": 847,
                }
            ]
        }

        grid = build_cost_grid(snapshot, UGV_PROFILE, ablation="full")

        self.assertEqual(grid.origin_ix, -4)
        self.assertEqual(grid.origin_iy, 12)
        self.assertEqual(grid.traversable.shape, (4, 4))
        self.assertTrue(np.all(grid.traversable))

    def test_semantics_only_uses_canonical_road_allowlist_and_obstacle_classes(self):
        snapshot = {
            "leaves": [
                {
                    "level": 0,
                    "ix": 0,
                    "iy": 0,
                    "semantic_class": 9,
                    "semantic_confidence": 1.0,
                },
                {
                    "level": 0,
                    "ix": 1,
                    "iy": 0,
                    "semantic_class": 18,
                    "semantic_confidence": 1.0,
                },
                {
                    "level": 0,
                    "ix": 2,
                    "iy": 0,
                    "semantic_class": 0,
                    "semantic_confidence": 1.0,
                },
            ]
        }

        grid = build_cost_grid(snapshot, UGV_PROFILE, ablation="semantics_only")

        self.assertEqual(grid.traversable.tolist(), [[True, False, False]])
        self.assertEqual(grid.hazards.tolist(), [[False, True, False]])
        self.assertEqual(grid.unknown.tolist(), [[False, False, True]])

    def test_same_physical_slope_map_yields_profile_specific_paths(self):
        snapshot = {
            "leaves": [
                {
                    "level": 0,
                    "ix": ix,
                    "iy": iy,
                    "semantic_class": 9,
                    "semantic_confidence": 1.0,
                    "ground_count": 4,
                    "ground_mean_z": 0.0,
                    "ground_stddev_m": 0.01,
                    "ground_gradient_x": 0.0 if iy != 1 or ix != 2 else 0.5,
                    "ground_gradient_y": 0.0,
                    "ground_gradient_count": 4,
                    "obstacle_count": 0,
                    "overhead_count": 0,
                    "drivable_evidence": 1.0,
                    "terrain_confidence": 1.0,
                }
                for iy in range(3)
                for ix in range(5)
            ]
        }
        start, goal = (0, 1), (4, 1)

        ugv = plan_grid(build_cost_grid(snapshot, UGV_PROFILE), start, goal)
        quadruped = plan_grid(build_cost_grid(snapshot, QUADRUPED_PROFILE), start, goal)

        self.assertTrue(ugv["success"])
        self.assertTrue(quadruped["success"])
        self.assertNotEqual(ugv["path"], quadruped["path"])
        self.assertNotIn((2, 1), ugv["path"])
        self.assertIn((2, 1), quadruped["path"])

    def test_geometry_and_full_ablations_consume_geometry_and_uncertainty_evidence(
        self,
    ):
        leaves = []
        for ix, complexity, confidence in ((0, 0.0, 1.0), (1, 1.0, 0.4)):
            leaves.append(
                {
                    "level": 0,
                    "ix": ix,
                    "iy": 0,
                    "semantic_class": 9,
                    "semantic_confidence": confidence,
                    "ground_count": 4,
                    "ground_mean_z": 0.0,
                    "ground_stddev_m": 0.0,
                    "ground_gradient_x": 0.0,
                    "ground_gradient_y": 0.0,
                    "ground_gradient_count": 4,
                    "obstacle_count": 0,
                    "overhead_count": 0,
                    "drivable_evidence": 1.0,
                    "terrain_confidence": confidence,
                    "geometry_complexity": complexity,
                }
            )
        snapshot = {"leaves": leaves}

        geometry = build_cost_grid(snapshot, UGV_PROFILE, ablation="geometry_only")
        full = build_cost_grid(snapshot, UGV_PROFILE, ablation="full")

        self.assertGreater(geometry.costs[0, 1], geometry.costs[0, 0])
        self.assertGreater(full.costs[0, 1], full.costs[0, 0])

    def test_five_centimeter_raster_rejects_misleading_custom_resolution(self):
        with self.assertRaisesRegex(ValueError, "fixed at 0.05 m"):
            build_cost_grid({"leaves": []}, UGV_PROFILE, cell_size_m=0.10)


if __name__ == "__main__":
    unittest.main()
