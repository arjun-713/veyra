"""Unit tests for the 3D-versus-2.5D storage comparators (no dataset)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from benchmarks.render_report import _storage_table
from benchmarks.storage_3d import (
    BYTES_PER_ENTRY,
    LOGICAL_BYTES_PER_VOXEL,
    SparseVoxelAccumulator,
    dense_3d_window_estimate,
    sparse_3d_report,
    storage_comparison_report,
)


def _frame(points, x=0.0, y=0.0):
    pose = np.eye(4)
    pose[0, 3], pose[1, 3] = x, y
    return SimpleNamespace(
        points=np.asarray(points, dtype=np.float32),
        pose=SimpleNamespace(matrix=pose),
    )


def _policy(logical, allocated, levels):
    return {
        "runs": [
            {"metrics": {"memory": {"logical_map_bytes": 1, "allocated_map_bytes": 1}}},
            {
                "metrics": {
                    "memory": {
                        "logical_map_bytes": logical,
                        "allocated_map_bytes": allocated,
                    }
                }
            },
        ],
        "aggregate": {"final_leaves_per_level": levels},
    }


class SparseAccumulatorTests(unittest.TestCase):
    def test_wrap_passes_frames_through_and_deduplicates_across_frames(self):
        accumulator = SparseVoxelAccumulator()
        frames = [
            _frame([[0.01, 0.01, 0.01, 1], [0.02, 0.02, 0.02, 1]]),
            _frame([[0.03, 0.04, 0.01, 1], [1.0, 1.0, 1.0, 1]], x=5.0),
        ]
        self.assertEqual(list(accumulator.wrap(frames)), frames)
        self.assertEqual(accumulator.frames, 2)
        self.assertEqual(accumulator.points, 4)
        self.assertEqual(int(accumulator.keys().size), 2)
        self.assertEqual(accumulator.last_pose_xy, (5.0, 0.0))

    def test_voxelizes_the_float32_coordinates_the_mapper_receives(self):
        # 0.05 - 1e-12 floors into voxel 0 in float64 but rounds to 0.05 in
        # float32, which is what the staged stream carries.
        accumulator = SparseVoxelAccumulator()
        accumulator.add(np.array([[0.05 - 1e-12, 0.0, 0.0]]), (0.0, 0.0))
        accumulator.add(np.array([[0.05, 0.0, 0.0]]), (0.0, 0.0))
        self.assertEqual(int(accumulator.keys().size), 1)

    def test_final_window_counts_only_voxels_inside_the_last_window(self):
        accumulator = SparseVoxelAccumulator()
        accumulator.add(np.array([[0.0, 0.0, 0.0], [50.0, 0.0, 0.0]]), (0.0, 0.0))
        accumulator.add(np.array([[60.0, 0.0, 0.0]]), (60.0, 0.0))
        self.assertEqual(accumulator.final_window_count(15.0), 2)
        report = sparse_3d_report(
            accumulator, window_radius_m=15.0, selection_digest="d"
        )
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["cumulative"]["occupied_voxels"], 3)
        self.assertEqual(report["final_window"]["occupied_voxels"], 2)
        self.assertEqual(
            report["final_window"]["logical_bytes"], 2 * LOGICAL_BYTES_PER_VOXEL
        )
        self.assertEqual(
            report["final_window"]["accounted_allocated_bytes"], 2 * BYTES_PER_ENTRY
        )
        self.assertEqual(report["rss"]["status"], "not_isolated")
        self.assertIsNone(report["rss"]["peak_rss_bytes"])

    def test_batched_merge_matches_single_unique(self):
        rng = np.random.default_rng(3)
        accumulator = SparseVoxelAccumulator()
        clouds = [rng.uniform(-20, 20, size=(5000, 3)) for _ in range(6)]
        for cloud in clouds:
            accumulator.add(cloud, (0.0, 0.0))
        expected = np.unique(
            np.floor(np.vstack(clouds).astype(np.float32).astype(np.float64) / 0.05),
            axis=0,
        )
        self.assertEqual(int(accumulator.keys().size), len(expected))


class DenseEstimateTests(unittest.TestCase):
    def test_window_box_dimensions_and_bytes(self):
        dense = dense_3d_window_estimate(10.0, -1.0, 1.0)
        self.assertEqual(dense["dimensions"], [400, 400, 41])
        self.assertEqual(dense["dense_voxel_count"], 400 * 400 * 41)
        self.assertEqual(dense["estimated_dense_bytes"], 400 * 400 * 41 * 16)
        self.assertEqual(dense["status"], "analytical_only")
        self.assertFalse(dense["executed_through_map_engine"])

    def test_rejects_invalid_spans(self):
        with self.assertRaises(ValueError):
            dense_3d_window_estimate(0.0, 0.0, 1.0)
        with self.assertRaises(ValueError):
            dense_3d_window_estimate(10.0, 1.0, 0.0)


class StorageComparisonTests(unittest.TestCase):
    def setUp(self):
        accumulator = SparseVoxelAccumulator()
        accumulator.add(np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]), (0.0, 0.0))
        self.sparse = sparse_3d_report(
            accumulator, window_radius_m=10.0, selection_digest="d"
        )
        self.dense = dense_3d_window_estimate(10.0, 0.0, 0.0)

    def test_ratios_use_last_repetition_and_final_window_basis(self):
        report = storage_comparison_report(
            {"uniform5": _policy(64, 128, {"0": 3, "1": 1})}, self.sparse, self.dense
        )
        row = report["policies"]["uniform5"]
        self.assertEqual(row["logical_map_bytes"], 64)
        self.assertEqual(row["active_cells"], 4)
        self.assertEqual(report["sparse_3d"]["logical_bytes"], 32)
        self.assertAlmostEqual(row["logical_over_sparse_3d_logical"], 2.0)
        self.assertAlmostEqual(row["allocated_over_sparse_3d_allocated"], 2.0)
        self.assertAlmostEqual(
            row["logical_over_dense_3d"], 64 / self.dense["estimated_dense_bytes"]
        )
        self.assertEqual(report["dense_3d"]["evidence"], "analytical")
        self.assertEqual(report["sparse_3d"]["evidence"], "measured")

    def test_missing_values_stay_null_not_zero(self):
        report = storage_comparison_report(
            {"uniform40": {"runs": [], "aggregate": {}}}, self.sparse, {}
        )
        row = report["policies"]["uniform40"]
        for key in (
            "logical_map_bytes",
            "allocated_map_bytes",
            "active_cells",
            "logical_over_sparse_3d_logical",
            "logical_over_dense_3d",
        ):
            self.assertIsNone(row[key], key)
        self.assertIsNone(report["dense_3d"]["estimated_dense_bytes"])

    def test_rendered_table_labels_evidence_and_ratios(self):
        report = storage_comparison_report(
            {"distance_lod": _policy(16, 32, {"0": 1})}, self.sparse, self.dense
        )
        table = _storage_table({"storage_comparison": report})
        self.assertIn("ANALYTICAL", table)
        self.assertIn("MEASURED count", table)
        self.assertIn("2.0x smaller", table)
        self.assertIn("unavailable", _storage_table({}))


if __name__ == "__main__":
    unittest.main()
