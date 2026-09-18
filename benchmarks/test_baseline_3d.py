"""Unit tests for the measured sparse 3D baseline (no dataset required)."""

from __future__ import annotations

import unittest

import numpy as np

from benchmarks.baseline_3d import (
    BYTES_PER_ENTRY,
    VOXEL_SIZE_M,
    SparseVoxelBaseline,
    frame_voxel_keys,
    pack_voxel_keys,
    unpack_voxel_keys,
)
from benchmarks.run_benchmark import analytical_3d_reference_bounds


class Baseline3DTests(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        indices = np.array(
            [[0, 0, 0], [-2000, 1500, -300], [1939, 2066, 362], [1, -1, 2]],
            dtype=np.int64,
        )
        np.testing.assert_array_equal(
            unpack_voxel_keys(pack_voxel_keys(indices)), indices
        )

    def test_pack_is_injective(self):
        indices = np.array([[i, -i, 2 * i] for i in range(-500, 500)], dtype=np.int64)
        packed = pack_voxel_keys(indices)
        self.assertEqual(len(set(packed.tolist())), len(indices))

    def test_same_voxel_points_share_one_key(self):
        points = np.array(
            [
                [0.001, 0.001, 0.001],
                [0.049, 0.049, 0.049],
                [0.051, 0.001, 0.001],
            ]
        )
        keys = frame_voxel_keys(points)
        self.assertEqual(len(keys), 2)

    def test_voxel_size_is_five_cm(self):
        self.assertEqual(VOXEL_SIZE_M, 0.05)

    def test_frame_voxelization_rejects_empty_and_nonfinite(self):
        with self.assertRaises(ValueError):
            frame_voxel_keys(np.zeros((0, 3)))
        with self.assertRaises(ValueError):
            frame_voxel_keys(np.array([[np.inf, 0.0, 0.0]]))

    def test_baseline_accumulates_unique_voxels_and_accounts_bytes(self):
        baseline = SparseVoxelBaseline()
        first = np.array([[0.01, 0.0, 0.0], [5.0, 5.0, 1.0]])
        second = np.array([[0.02, 0.0, 0.0], [6.0, 6.0, 1.0]])
        self.assertEqual(baseline.insert_frame(first), 2)
        self.assertEqual(baseline.insert_frame(second), 1)
        self.assertEqual(len(baseline.voxels), 3)
        self.assertEqual(baseline.accounted_bytes, 3 * BYTES_PER_ENTRY)
        self.assertEqual(len(baseline.insert_latency_ns), 2)
        self.assertTrue(all(value > 0 for value in baseline.insert_latency_ns))

    def test_accounting_unit_is_documented_32_bytes(self):
        self.assertEqual(BYTES_PER_ENTRY, 32)

    def test_measured_occupancy_never_exceeds_analytical_dense_count(self):
        points = np.array(
            [[x * 0.05 + 0.01, 0.0, 0.0] for x in range(10)], dtype=np.float64
        )
        occupied = len(frame_voxel_keys(points))
        reference = analytical_3d_reference_bounds(
            points.min(axis=0), points.max(axis=0)
        )
        self.assertEqual(reference["status"], "analytical_only")
        self.assertLessEqual(occupied, reference["dense_voxel_count"])


if __name__ == "__main__":
    unittest.main()
