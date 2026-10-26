"""3D-versus-2.5D storage evidence for the four-policy benchmark.

The SIH brief asks for "memory savings versus uniform high-resolution 3D".
This module produces the two 3D comparators that ``run_benchmark.py`` puts
beside every policy's 2.5D map bytes, on the identical staged input stream:

* **Sparse 5 cm 3D voxel hash (MEASURED voxel count).** Every point written
  to the staged binary stream (the exact float32 XYZ every policy consumed)
  is voxelized at 5 cm into a packed-key occupancy set. The occupied-voxel
  count is measured; bytes are *accounted* from that count at a documented
  per-entry size, not malloc-hooked. Two counts are kept: ``cumulative``
  (every voxel ever touched; the set never evicts) and ``final_window``
  (voxels whose centre lies in the mapper's final circular window, which is
  what a rolling 3D map would still hold at the end, comparable to the 2.5D
  policies' final map). Occupancy only: no height statistics, class or
  motion, so it is a lower bound on a feature-equivalent 3D map.
* **Dense 5 cm 3D grid (ANALYTICAL, never allocated).** A box covering the
  mapper window footprint (``2R x 2R``) and the stream's measured z span at
  16 B/voxel.

This module has no dependency on ``run_benchmark`` so both it and
``baseline_3d.py`` can import it without an import cycle.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from typing import Any

import numpy as np

VOXEL_SIZE_M = 0.05
# Logical payload: 8 B packed key + 8 B occupancy/count payload.
LOGICAL_BYTES_PER_VOXEL = 16
# Accounted allocation: logical payload + 16 B open-addressing hash-slot
# overhead for a typical dense hash table. Documented unit, not malloc-hooked.
BYTES_PER_ENTRY = 32
DENSE_BYTES_PER_VOXEL = 16
_BIAS = 1 << 20  # covers +/- ~52 km at 5 cm; real spans are ~+/-100 m
_MERGE_EVERY_KEYS = 4_000_000


def pack_voxel_keys(indices: np.ndarray) -> np.ndarray:
    """Pack (N,3) int64 voxel indices into one uint64 key per voxel."""
    biased = indices.astype(np.int64, copy=False) + _BIAS
    if np.any(biased < 0) or np.any(biased >= (1 << 21)):
        raise ValueError("voxel index outside 21-bit packing range")
    return (
        (biased[:, 0].astype(np.uint64) << 42)
        | (biased[:, 1].astype(np.uint64) << 21)
        | biased[:, 2].astype(np.uint64)
    )


def unpack_voxel_keys(packed: np.ndarray) -> np.ndarray:
    """Inverse of :func:`pack_voxel_keys`."""
    packed = np.asarray(packed, dtype=np.uint64)
    mask = np.uint64((1 << 21) - 1)
    indices = np.empty((packed.shape[0], 3), dtype=np.int64)
    indices[:, 0] = ((packed >> 42) & mask).astype(np.int64) - _BIAS
    indices[:, 1] = ((packed >> 21) & mask).astype(np.int64) - _BIAS
    indices[:, 2] = (packed & mask).astype(np.int64) - _BIAS
    return indices


def frame_voxel_keys(points_xyz: np.ndarray) -> np.ndarray:
    """Unique packed 5 cm voxel keys occupied by one frame's XYZ points."""
    xyz = np.asarray(points_xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] < 3 or xyz.shape[0] == 0:
        raise ValueError("frame voxelization requires non-empty XYZ points")
    if not np.isfinite(xyz[:, :3]).all():
        raise ValueError("frame points must be finite")
    indices = np.floor(xyz[:, :3] / VOXEL_SIZE_M).astype(np.int64)
    return np.unique(pack_voxel_keys(indices))


class SparseVoxelAccumulator:
    """Streaming 5 cm occupancy set over the staged benchmark stream.

    Keys are held as one sorted unique ``uint64`` array (merged in batches),
    so memory is ~8 B per occupied voxel rather than a Python ``set``.
    """

    def __init__(self) -> None:
        self._keys = np.empty(0, dtype=np.uint64)
        self._pending: list[np.ndarray] = []
        self._pending_count = 0
        self.frames = 0
        self.points = 0
        self.last_pose_xy: tuple[float, float] | None = None

    def add(self, points_xyz: np.ndarray, pose_xy: tuple[float, float]) -> None:
        # The staged binary stream carries XYZ as little-endian float32; the
        # mapper therefore sees float32 coordinates, so voxelize those.
        xyz = np.asarray(points_xyz[:, :3], dtype=np.float32).astype(np.float64)
        self.frames += 1
        self.last_pose_xy = (float(pose_xy[0]), float(pose_xy[1]))
        if xyz.shape[0] == 0:
            return
        self.points += int(xyz.shape[0])
        keys = frame_voxel_keys(xyz)
        self._pending.append(keys)
        self._pending_count += len(keys)
        if self._pending_count >= _MERGE_EVERY_KEYS:
            self._merge()

    def _merge(self) -> None:
        if self._pending:
            self._keys = np.unique(np.concatenate([self._keys, *self._pending]))
            self._pending = []
            self._pending_count = 0

    def keys(self) -> np.ndarray:
        self._merge()
        return self._keys

    def wrap(self, frames: Iterable[Any]) -> Iterator[Any]:
        """Yield ``frames`` unchanged while voxelizing each one."""
        for frame in frames:
            self.add(
                np.asarray(frame.points),
                (float(frame.pose.matrix[0, 3]), float(frame.pose.matrix[1, 3])),
            )
            yield frame

    def final_window_count(self, radius_m: float) -> int | None:
        """Occupied voxels whose centre lies in the final circular window."""
        if self.last_pose_xy is None or not math.isfinite(radius_m):
            return None
        keys = self.keys()
        if keys.size == 0:
            return 0
        centres = (
            unpack_voxel_keys(keys)[:, :2].astype(np.float64) + 0.5
        ) * VOXEL_SIZE_M
        dx = centres[:, 0] - self.last_pose_xy[0]
        dy = centres[:, 1] - self.last_pose_xy[1]
        return int(np.count_nonzero(dx * dx + dy * dy <= radius_m * radius_m))


def _voxel_bytes(count: int | None) -> dict[str, int | None]:
    return {
        "occupied_voxels": count,
        "logical_bytes": None if count is None else count * LOGICAL_BYTES_PER_VOXEL,
        "accounted_allocated_bytes": None if count is None else count * BYTES_PER_ENTRY,
    }


def sparse_3d_report(
    accumulator: SparseVoxelAccumulator,
    *,
    window_radius_m: float,
    selection_digest: str,
) -> dict[str, Any]:
    """Measured sparse 3D reference over the staged stream."""
    cumulative = int(accumulator.keys().size)
    window = accumulator.final_window_count(window_radius_m)
    return {
        "status": "measured",
        "evidence": "measured_voxel_count_accounted_bytes",
        "representation": "sparse_voxel_hash_occupancy_5cm",
        "voxel_size_m": VOXEL_SIZE_M,
        "input": {
            "source": "staged binary benchmark stream (float32 XYZ every policy consumed)",
            "selection_digest": selection_digest,
            "frames": accumulator.frames,
            "points": accumulator.points,
        },
        "window": {
            "radius_m": window_radius_m,
            "final_center_xy_m": list(accumulator.last_pose_xy)
            if accumulator.last_pose_xy
            else None,
            "membership": "voxel centre inside the mapper's final circular window",
        },
        "final_window": _voxel_bytes(window),
        "cumulative": _voxel_bytes(cumulative),
        "comparison_basis": "final_window",
        "logical_bytes_per_voxel": LOGICAL_BYTES_PER_VOXEL,
        "accounted_bytes_per_voxel": BYTES_PER_ENTRY,
        "memory_accounting": (
            "occupied-voxel counts are measured; bytes are accounted from them "
            "(logical: 8 B packed key + 8 B occupancy/count payload; allocated: "
            "logical + 16 B open-addressing slot overhead), not malloc-hooked"
        ),
        "information_content": (
            "occupancy only: no height statistics, semantic class, confidence or "
            "motion per voxel, so this is a lower bound for a feature-equivalent "
            "3D map"
        ),
        "rss": {
            "status": "not_isolated",
            "peak_rss_bytes": None,
            "reason": (
                "voxelized inside the Python benchmark harness alongside "
                "perception and staging; no process RSS is attributable to the "
                "voxel set. benchmarks/baseline_3d.py measures a standalone "
                "process peak RSS"
            ),
        },
    }


def dense_3d_window_estimate(
    window_radius_m: float, min_z_m: float, max_z_m: float
) -> dict[str, Any]:
    """Analytical dense 5 cm grid over the window footprint and z span."""
    if not (math.isfinite(window_radius_m) and window_radius_m > 0):
        raise ValueError("dense 3D window estimate requires a positive radius")
    if not (math.isfinite(min_z_m) and math.isfinite(max_z_m)) or max_z_m < min_z_m:
        raise ValueError("dense 3D window estimate requires a finite z span")
    side = max(1, math.ceil(2.0 * window_radius_m / VOXEL_SIZE_M))
    height = max(1, math.ceil((max_z_m - min_z_m) / VOXEL_SIZE_M) + 1)
    count = side * side * height
    return {
        "status": "analytical_only",
        "executed_through_map_engine": False,
        "representation": "dense_uniform_3d_voxels_window",
        "voxel_size_m": VOXEL_SIZE_M,
        "window_radius_m": window_radius_m,
        "footprint": "square 2R x 2R bounding the mapper's circular window",
        "z_span_m": [min_z_m, max_z_m],
        "dimensions": [side, side, height],
        "dense_voxel_count": count,
        "estimated_bytes_per_voxel": DENSE_BYTES_PER_VOXEL,
        "estimated_dense_bytes": count * DENSE_BYTES_PER_VOXEL,
        "warning": "memory estimate only; no dense grid was allocated or timed",
    }


def _ratio(numerator: Any, denominator: Any) -> float | None:
    if not isinstance(numerator, (int, float)) or isinstance(numerator, bool):
        return None
    if not isinstance(denominator, (int, float)) or isinstance(denominator, bool):
        return None
    if denominator <= 0 or not math.isfinite(numerator) or numerator < 0:
        return None
    return float(numerator) / float(denominator)


def storage_comparison_report(
    policies: dict[str, Any],
    sparse_3d: dict[str, Any],
    dense_3d: dict[str, Any],
    dense_3d_stream_bounds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-policy 2.5D bytes beside both 3D comparators, with ratios.

    Ratios are ``policy 2.5D bytes / 3D bytes``: below 1 means the 2.5D map
    is smaller. Missing inputs stay ``None`` (never zero).
    """
    basis = sparse_3d.get(sparse_3d.get("comparison_basis", "final_window"), {})
    sparse_logical = basis.get("logical_bytes")
    sparse_allocated = basis.get("accounted_allocated_bytes")
    dense_bytes = dense_3d.get("estimated_dense_bytes")
    rows: dict[str, Any] = {}
    for name, policy in policies.items():
        runs = policy.get("runs") or []
        memory = ((runs[-1] if runs else {}).get("metrics") or {}).get("memory") or {}
        levels = (policy.get("aggregate") or {}).get("final_leaves_per_level") or {}
        logical = memory.get("logical_map_bytes")
        allocated = memory.get("allocated_map_bytes")
        rows[name] = {
            "evidence": "measured",
            "logical_map_bytes": logical,
            "allocated_map_bytes": allocated,
            "active_cells": sum(int(value) for value in levels.values())
            if levels
            else None,
            "logical_over_sparse_3d_logical": _ratio(logical, sparse_logical),
            "allocated_over_sparse_3d_allocated": _ratio(allocated, sparse_allocated),
            "logical_over_dense_3d": _ratio(logical, dense_bytes),
            "allocated_over_dense_3d": _ratio(allocated, dense_bytes),
        }
    return {
        "schema_version": 1,
        "units": "bytes",
        "ratio_definition": "policy 2.5D bytes / 3D bytes; below 1 means the 2.5D map is smaller",
        "policy_bytes_source": "last repetition's final map (runs[-1].metrics.memory)",
        "sparse_3d": {
            "evidence": "measured",
            "basis": sparse_3d.get("comparison_basis", "final_window"),
            "occupied_voxels": basis.get("occupied_voxels"),
            "logical_bytes": sparse_logical,
            "accounted_allocated_bytes": sparse_allocated,
            "reference": "reference_baselines.sparse_5cm_3d",
        },
        "dense_3d": {
            "evidence": "analytical",
            "dense_voxel_count": dense_3d.get("dense_voxel_count"),
            "estimated_dense_bytes": dense_bytes,
            "reference": "reference_baselines.dense_5cm_3d_window",
        },
        "dense_3d_stream_bounds": {
            "evidence": "analytical",
            "estimated_dense_bytes": (dense_3d_stream_bounds or {}).get(
                "estimated_dense_bytes"
            ),
            "reference": "reference_baselines.uniform_5cm_3d",
        },
        "policies": rows,
    }
