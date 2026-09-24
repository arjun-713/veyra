"""Evaluation-only conversion from immutable map leaves to robot cost grids.

This module does not alter mapper policy or claim a certified robot model.
Profiles are explicit evaluation assumptions, unknown cells are blocked, and
the fine 5 cm raster exists only for bounded offline path-comparison runs.
"""

from __future__ import annotations

import csv
import hashlib
import heapq
import json
import math
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np

CELL_SIZE_M = 0.05
OCCUPIED_THRESHOLD = 847
FREE_THRESHOLD = -405


@dataclass(frozen=True)
class VehicleCostProfile:
    """Illustrative planning envelope; not a vehicle safety certification."""

    name: str
    max_slope_rad: float
    max_roughness_m: float
    max_step_m: float
    min_clearance_m: float

    def __post_init__(self) -> None:
        values = (
            self.max_slope_rad,
            self.max_roughness_m,
            self.max_step_m,
            self.min_clearance_m,
        )
        if not self.name or not all(
            math.isfinite(value) and value >= 0.0 for value in values
        ):
            raise ValueError(
                "vehicle evaluation profile values must be finite and non-negative"
            )
        if self.max_slope_rad > math.pi / 2.0:
            raise ValueError("vehicle evaluation max_slope_rad must be at most pi/2")


# Explicit starting assumptions for comparative evaluation only. Tune these
# from the target platform specification before interpreting operationally.
UGV_PROFILE = VehicleCostProfile("ugv_eval", math.radians(18.0), 0.08, 0.12, 1.20)
QUADRUPED_PROFILE = VehicleCostProfile(
    "quadruped_eval", math.radians(35.0), 0.16, 0.28, 0.45
)


@dataclass(frozen=True)
class CostGrid:
    origin_ix: int
    origin_iy: int
    traversable: np.ndarray
    costs: np.ndarray
    unknown: np.ndarray | None = None
    hazards: np.ndarray | None = None
    levels: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.traversable.ndim != 2 or self.costs.shape != self.traversable.shape:
            raise ValueError(
                "cost-grid traversability and costs must be aligned 2D arrays"
            )
        if np.any(~np.isfinite(self.costs)) or np.any(self.costs < 1.0):
            raise ValueError("traversal costs must be finite and at least 1")
        for name in ("unknown", "hazards", "levels"):
            value = getattr(self, name)
            if value is not None and value.shape != self.traversable.shape:
                raise ValueError(f"cost-grid {name} must match the grid shape")


_ABLATIONS = {
    "occupancy_only",  # historical control
    "semantics_only",
    "slope_only",
    "geometry_only",
    "semantics_slope",
    "full",
}
_ABLATION_ORDER = (
    "occupancy_only",
    "semantics_only",
    "slope_only",
    "geometry_only",
    "semantics_slope",
    "full",
)
_PUBLIC_POLICIES = ("uniform5", "uniform40", "distance_lod", "utility_lod")

# Veyra's SemanticKITTI-learning taxonomy. Only road and parking are
# considered traversable by semantics alone. Other classes are either known
# obstacle classes or conservatively unknown; these assumptions are not a
# robot safety certification.
_SEMANTIC_DRIVABLE = {9, 10}
_SEMANTIC_OBSTACLES = set(range(1, 9)) | {13, 14, 16, 18, 19}


def _require_common_resolution(cell_size_m: float) -> None:
    if not math.isfinite(cell_size_m) or not math.isclose(
        cell_size_m, CELL_SIZE_M, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("common evaluation lattice is fixed at 0.05 m")


def _active_leaf_bounds(snapshot: dict) -> list[tuple[int, int, int, int]]:
    bounds = []
    for leaf in snapshot.get("leaves", []):
        level, ix, iy = int(leaf["level"]), int(leaf["ix"]), int(leaf["iy"])
        if not 0 <= level <= 3:
            raise ValueError("leaf level must be in [0,3]")
        scale = 1 << level
        bounds.append((ix * scale, iy * scale, (ix + 1) * scale, (iy + 1) * scale))
    return bounds


def _bounded_reference_roi(
    snapshot: dict, max_grid_cells: int
) -> tuple[int, int, int, int]:
    """Choose a deterministic, centered 5 cm ROI from Uniform5 active bounds."""
    if (
        isinstance(max_grid_cells, bool)
        or not isinstance(max_grid_cells, int)
        or max_grid_cells <= 0
    ):
        raise ValueError("max_grid_cells must be a positive integer")
    bounds = _active_leaf_bounds(snapshot)
    if not bounds:
        return (0, 0, 0, 0)

    min_x = min(item[0] for item in bounds)
    min_y = min(item[1] for item in bounds)
    max_x = max(item[2] for item in bounds)
    max_y = max(item[3] for item in bounds)
    full_width, full_height = max_x - min_x, max_y - min_y
    if full_width * full_height <= max_grid_cells:
        return (min_x, min_y, max_x, max_y)

    # Preserve the bounding-box aspect ratio while keeping the dense temporary
    # arrays under the configured cell budget. The exact crop is derived only
    # from Uniform5 and then reused unchanged for every policy/profile/ablation.
    width = min(
        full_width,
        max(1, int(math.sqrt(max_grid_cells * full_width / full_height))),
    )
    height = min(full_height, max(1, max_grid_cells // width))
    while width * height > max_grid_cells:
        if width >= height and width > 1:
            width -= 1
        elif height > 1:
            height -= 1
        else:
            break
    origin_x = min_x + (full_width - width) // 2
    origin_y = min_y + (full_height - height) // 2
    return (origin_x, origin_y, origin_x + width, origin_y + height)


def _semantic_evidence(leaf: dict) -> tuple[bool, bool, bool]:
    semantic_class = leaf.get("semantic_class")
    confidence = leaf.get("semantic_confidence")
    parsed_confidence = float(confidence) if confidence is not None else math.nan
    if (
        isinstance(semantic_class, bool)
        or not isinstance(semantic_class, int)
        or semantic_class < 0
        or not math.isfinite(parsed_confidence)
        or not 0.0 <= parsed_confidence <= 1.0
        or parsed_confidence == 0.0
    ):
        return False, False, False
    return (
        semantic_class in _SEMANTIC_DRIVABLE,
        semantic_class in _SEMANTIC_OBSTACLES,
        semantic_class in _SEMANTIC_DRIVABLE | _SEMANTIC_OBSTACLES,
    )


def build_cost_grid(
    snapshot: dict,
    profile: VehicleCostProfile,
    *,
    ablation: str = "full",
    cell_size_m: float = CELL_SIZE_M,
    max_grid_cells: int = 4_000_000,
    roi_bounds: tuple[int, int, int, int] | None = None,
) -> CostGrid:
    """Rasterize active leaves into one bounded, world-aligned 5 cm grid.

    Each active dyadic leaf owns exactly ``4**level`` fine bins. Duplicate
    owners are rejected rather than resolved by iteration order. Missing
    evidence stays unknown. A rectangle exceeding ``max_grid_cells`` fails
    explicitly instead of silently clipping the scenario.
    """
    if ablation not in _ABLATIONS:
        raise ValueError(f"unsupported planner layer ablation: {ablation}")
    _require_common_resolution(cell_size_m)
    if (
        isinstance(max_grid_cells, bool)
        or not isinstance(max_grid_cells, int)
        or max_grid_cells <= 0
    ):
        raise ValueError("max_grid_cells must be a positive integer")

    leaves = snapshot.get("leaves", [])
    bounds = _active_leaf_bounds(snapshot)
    if not bounds:
        empty = np.zeros((0, 0), dtype=bool)
        return CostGrid(0, 0, empty, np.zeros((0, 0), dtype=np.float32), empty, empty)

    if roi_bounds is None:
        origin_ix = min(item[0] for item in bounds)
        origin_iy = min(item[1] for item in bounds)
        end_ix = max(item[2] for item in bounds)
        end_iy = max(item[3] for item in bounds)
    else:
        if len(roi_bounds) != 4 or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in roi_bounds
        ):
            raise ValueError("roi_bounds must contain four integer 5 cm lattice bounds")
        origin_ix, origin_iy, end_ix, end_iy = roi_bounds
        if end_ix <= origin_ix or end_iy <= origin_iy:
            raise ValueError("roi_bounds must have positive width and height")
    width, height = end_ix - origin_ix, end_iy - origin_iy
    if width * height > max_grid_cells:
        raise ValueError(
            f"evaluation grid {width}x{height} exceeds max_grid_cells={max_grid_cells}"
        )

    traversable = np.zeros((height, width), dtype=bool)
    unknown = np.ones((height, width), dtype=bool)
    hazards = np.zeros((height, width), dtype=bool)
    costs = np.ones((height, width), dtype=np.float32)
    levels = np.full((height, width), -1, dtype=np.int8)
    occupied = np.zeros((height, width), dtype=bool)

    for leaf, (min_ix, min_iy, max_ix, max_iy) in zip(leaves, bounds, strict=True):
        clipped_min_x = max(min_ix, origin_ix)
        clipped_min_y = max(min_iy, origin_iy)
        clipped_max_x = min(max_ix, end_ix)
        clipped_max_y = min(max_iy, end_iy)
        if clipped_min_x >= clipped_max_x or clipped_min_y >= clipped_max_y:
            continue
        x0, y0 = clipped_min_x - origin_ix, clipped_min_y - origin_iy
        x1, y1 = clipped_max_x - origin_ix, clipped_max_y - origin_iy
        region = np.s_[y0:y1, x0:x1]
        if np.any(occupied[region]):
            raise ValueError("active map leaves overlap in the 5 cm evaluation grid")
        occupied[region] = True
        levels[region] = int(leaf["level"])

        logodds = int(leaf.get("occupancy_logodds", 0))
        occupancy_known = logodds <= FREE_THRESHOLD or logodds >= OCCUPIED_THRESHOLD
        is_free = logodds <= FREE_THRESHOLD
        if ablation == "occupancy_only":
            traversable[region] = is_free
            unknown[region] = not occupancy_known
            hazards[region] = not is_free and occupancy_known
            continue

        semantic_drivable, semantic_hazard, semantic_known = _semantic_evidence(leaf)
        if ablation == "semantics_only":
            if semantic_drivable:
                traversable[region] = True
                unknown[region] = False
            elif semantic_hazard:
                hazards[region] = True
                unknown[region] = False
            continue

        ground_count = int(leaf.get("ground_count", 0))
        ground_z = float(leaf.get("ground_mean_z", math.nan))
        roughness = float(leaf.get("ground_stddev_m", math.nan))
        geometry_complexity = float(leaf.get("geometry_complexity", math.nan))
        if math.isfinite(geometry_complexity) and not 0.0 <= geometry_complexity <= 1.0:
            raise ValueError("geometry_complexity must be within [0,1] when available")
        has_ground = ground_count > 0 and math.isfinite(ground_z)
        has_geometry = has_ground and math.isfinite(roughness)
        slope = None
        if ablation in {"slope_only", "semantics_slope", "full"}:
            gx = float(leaf.get("ground_gradient_x", math.nan))
            gy = float(leaf.get("ground_gradient_y", math.nan))
            gradient_count = int(leaf.get("ground_gradient_count", 0))
            if (
                has_ground
                and gradient_count > 0
                and math.isfinite(gx)
                and math.isfinite(gy)
            ):
                slope = math.atan(math.hypot(gx, gy))

        if ablation == "slope_only":
            if slope is None:
                continue
            blocked = slope > profile.max_slope_rad
            traversable[region] = not blocked
            unknown[region] = False
            hazards[region] = blocked
            costs[region] = np.float32(
                1.0 + 0.5 * min(slope / max(profile.max_slope_rad, 1e-6), 2.0)
            )
            continue

        if ablation == "semantics_slope":
            if slope is None or not semantic_known:
                continue
            blocked = (
                semantic_hazard
                or not semantic_drivable
                or slope > profile.max_slope_rad
            )
            traversable[region] = not blocked
            unknown[region] = False
            hazards[region] = semantic_hazard or slope > profile.max_slope_rad
            costs[region] = np.float32(
                1.0 + 0.5 * min(slope / max(profile.max_slope_rad, 1e-6), 2.0)
            )
            continue

        if not has_geometry:
            continue
        obstacle_count = int(leaf.get("obstacle_count", 0))
        overhead_count = int(leaf.get("overhead_count", 0))
        obstacle_min = float(leaf.get("obstacle_min_z", math.nan))
        overhead_min = float(leaf.get("overhead_min_z", math.nan))
        obstacle_height = (
            obstacle_min - ground_z
            if obstacle_count and math.isfinite(obstacle_min)
            else 0.0
        )
        clearance = (
            overhead_min - ground_z
            if overhead_count and math.isfinite(overhead_min)
            else math.inf
        )
        blocked = roughness > profile.max_roughness_m
        blocked |= obstacle_count > 0 and obstacle_height > profile.max_step_m
        blocked |= overhead_count > 0 and clearance < profile.min_clearance_m

        if ablation == "geometry_only":
            traversable[region] = not blocked
            unknown[region] = False
            hazards[region] = blocked
            roughness_cost = roughness / max(profile.max_roughness_m, 1e-6)
            complexity_cost = (
                geometry_complexity if math.isfinite(geometry_complexity) else 0.0
            )
            costs[region] = np.float32(
                1.0 + 0.5 * min(roughness_cost, 2.0) + 0.5 * complexity_cost
            )
            continue

        if ablation == "full":
            # Apply the robot profile to physical measurements here. The
            # upstream drivable_evidence is a generic terrain-stage label
            # under that stage's configured thresholds; treating it as a
            # universal veto would bake one vehicle's limits into every
            # downstream profile. Unknown semantics, terrain confidence, or
            # slope is still not a free cell.
            if slope is None or not semantic_known or not semantic_drivable:
                if semantic_hazard:
                    hazards[region] = True
                    unknown[region] = False
                continue
            semantic_confidence = float(leaf.get("semantic_confidence", math.nan))
            confidence = float(leaf.get("terrain_confidence", math.nan))
            if (
                not math.isfinite(semantic_confidence)
                or semantic_confidence <= 0.0
                or not math.isfinite(confidence)
                or confidence <= 0.0
            ):
                continue
            blocked |= slope > profile.max_slope_rad

        traversable[region] = not blocked
        unknown[region] = False
        hazards[region] = blocked
        roughness_cost = roughness / max(profile.max_roughness_m, 1e-6)
        slope_cost = 0.0 if slope is None else slope / max(profile.max_slope_rad, 1e-6)
        complexity_cost = (
            geometry_complexity if math.isfinite(geometry_complexity) else 0.0
        )
        uncertainty_cost = 0.0
        if ablation == "full":
            uncertainty_cost = 1.0 - min(semantic_confidence, confidence)
        costs[region] = np.float32(
            1.0
            + 0.5 * min(roughness_cost, 2.0)
            + 0.5 * min(slope_cost, 2.0)
            + 0.5 * complexity_cost
            + 0.5 * uncertainty_cost
        )

    return CostGrid(origin_ix, origin_iy, traversable, costs, unknown, hazards, levels)


def plan_grid(
    grid: CostGrid,
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    algorithm: str = "astar",
    cell_size_m: float = CELL_SIZE_M,
    reference_grid: CostGrid | None = None,
    max_expansions: int = 1_000_000,
) -> dict:
    """Run deterministic 8-connected A* or Dijkstra over a CostGrid."""
    if algorithm not in {"astar", "dijkstra"}:
        raise ValueError("algorithm must be 'astar' or 'dijkstra'")
    _require_common_resolution(cell_size_m)
    if (
        isinstance(max_expansions, bool)
        or not isinstance(max_expansions, int)
        or max_expansions <= 0
    ):
        raise ValueError("max_expansions must be a positive integer")
    started = time.perf_counter_ns()
    start_local = (start[0] - grid.origin_ix, start[1] - grid.origin_iy)
    goal_local = (goal[0] - grid.origin_ix, goal[1] - grid.origin_iy)
    height, width = grid.traversable.shape

    def valid(cell: tuple[int, int]) -> bool:
        x, y = cell
        return 0 <= x < width and 0 <= y < height and bool(grid.traversable[y, x])

    if not valid(start_local) or not valid(goal_local):
        return {
            "success": False,
            "algorithm": algorithm,
            "path": [],
            "path_length_m": None,
            "path_cost": None,
            "expanded_nodes": 0,
            "hazard_cells": 0,
            "resolution_boundary_crossings": 0,
            "reference_hazard_crossings": None,
            "reference_unknown_crossings": None,
            "reference_path_coverage": None,
            "planning_time_ns": time.perf_counter_ns() - started,
            "failure": "start_or_goal_unknown_or_blocked",
        }

    offsets = tuple(
        sorted(
            ((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy),
            key=lambda item: (item[1], item[0]),
        )
    )

    def heuristic(cell: tuple[int, int]) -> float:
        return cell_size_m * math.hypot(
            goal_local[0] - cell[0], goal_local[1] - cell[1]
        )

    queue = [
        (
            heuristic(start_local) if algorithm == "astar" else 0.0,
            0.0,
            start_local[1],
            start_local[0],
        )
    ]
    costs_so_far = {start_local: 0.0}
    parent: dict[tuple[int, int], tuple[int, int]] = {}
    expanded = 0
    while queue and expanded < max_expansions:
        _priority, current_cost, y, x = heapq.heappop(queue)
        current = (x, y)
        if current_cost > costs_so_far.get(current, math.inf) + 1e-12:
            continue
        expanded += 1
        if current == goal_local:
            break
        for dx, dy in offsets:
            neighbor = (x + dx, y + dy)
            if not valid(neighbor):
                continue
            diagonal = dx != 0 and dy != 0
            if diagonal and (not valid((x + dx, y)) or not valid((x, y + dy))):
                continue
            step = cell_size_m * (math.sqrt(2.0) if diagonal else 1.0)
            next_cost = (
                current_cost
                + step
                * (
                    float(grid.costs[y, x])
                    + float(grid.costs[neighbor[1], neighbor[0]])
                )
                * 0.5
            )
            if next_cost + 1e-12 >= costs_so_far.get(neighbor, math.inf):
                continue
            costs_so_far[neighbor] = next_cost
            parent[neighbor] = current
            estimate = next_cost + (
                heuristic(neighbor) if algorithm == "astar" else 0.0
            )
            heapq.heappush(queue, (estimate, next_cost, neighbor[1], neighbor[0]))

    if goal_local not in costs_so_far:
        failure = "search_limit" if queue else "no_path"
        return {
            "success": False,
            "algorithm": algorithm,
            "path": [],
            "path_length_m": None,
            "path_cost": None,
            "expanded_nodes": expanded,
            "hazard_cells": 0,
            "resolution_boundary_crossings": 0,
            "reference_hazard_crossings": None,
            "reference_unknown_crossings": None,
            "reference_path_coverage": None,
            "planning_time_ns": time.perf_counter_ns() - started,
            "failure": failure,
        }

    local_path = [goal_local]
    while local_path[-1] != start_local:
        local_path.append(parent[local_path[-1]])
    local_path.reverse()
    path = [(x + grid.origin_ix, y + grid.origin_iy) for x, y in local_path]
    length = sum(
        cell_size_m * math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(path)
    )
    hazards = (
        sum(bool(grid.hazards[y, x]) for x, y in local_path)
        if grid.hazards is not None
        else 0
    )
    boundary_crossings = 0
    if grid.levels is not None:
        boundary_crossings = sum(
            grid.levels[a[1], a[0]] != grid.levels[b[1], b[0]]
            for a, b in pairwise(local_path)
        )
    reference_hazards = None
    reference_unknown = None
    reference_coverage = None
    if reference_grid is not None:
        reference_hazards = 0
        reference_unknown = 0
        reference_covered = 0
        for x, y in path:
            reference_x = x - reference_grid.origin_ix
            reference_y = y - reference_grid.origin_iy
            inside = (
                0 <= reference_x < reference_grid.traversable.shape[1]
                and 0 <= reference_y < reference_grid.traversable.shape[0]
            )
            if not inside:
                reference_unknown += 1
                continue
            reference_covered += 1
            is_unknown = (
                bool(reference_grid.unknown[reference_y, reference_x])
                if reference_grid.unknown is not None
                else False
            )
            if is_unknown:
                reference_unknown += 1
                continue
            is_hazard = (
                bool(reference_grid.hazards[reference_y, reference_x])
                if reference_grid.hazards is not None
                else not bool(reference_grid.traversable[reference_y, reference_x])
            )
            reference_hazards += int(is_hazard)
        reference_coverage = reference_covered / len(path) if path else None
    return {
        "success": True,
        "algorithm": algorithm,
        "path": path,
        "path_length_m": length,
        "path_cost": costs_so_far[goal_local],
        "expanded_nodes": expanded,
        "hazard_cells": int(hazards),
        "resolution_boundary_crossings": int(boundary_crossings),
        "reference_hazard_crossings": reference_hazards,
        "reference_unknown_crossings": reference_unknown,
        "reference_path_coverage": reference_coverage,
        "planning_time_ns": time.perf_counter_ns() - started,
        "failure": None,
    }


def _physical_snapshot_digest(snapshot: dict) -> str:
    leaves = snapshot.get("leaves", [])
    ordered = sorted(
        leaves,
        key=lambda leaf: (
            int(leaf["level"]),
            int(leaf["ix"]),
            int(leaf["iy"]),
        ),
    )
    encoded = json.dumps(
        ordered, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reference_endpoints(
    grid: CostGrid,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Pick endpoints from the largest 4-connected supported component."""
    if not grid.traversable.size or not np.any(grid.traversable):
        return None
    from scipy.ndimage import label

    labels, component_count = label(
        grid.traversable,
        structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8),
    )
    if component_count == 0:
        return None
    sizes = np.bincount(labels.ravel(), minlength=component_count + 1)
    sizes[0] = 0
    largest = int(np.argmax(sizes))
    first_local = None
    last_local = None
    for y, row in enumerate(labels):
        columns = np.flatnonzero(row == largest)
        if columns.size:
            if first_local is None:
                first_local = (int(columns[0]), y)
            last_local = (int(columns[-1]), y)
    if first_local is None or last_local is None or first_local == last_local:
        return None
    start = (first_local[0] + grid.origin_ix, first_local[1] + grid.origin_iy)
    goal = (last_local[0] + grid.origin_ix, last_local[1] + grid.origin_iy)
    return start, goal


def planner_evaluation_report(
    snapshots_by_policy: dict[str, dict],
    *,
    max_grid_cells: int = 4_000_000,
    max_expansions: int = 1_000_000,
) -> dict:
    """Evaluate deterministic layer ablations against one Uniform5 reference.

    Each policy snapshot is reused unchanged for both vehicle profiles. One
    start/goal pair per profile is selected from the largest connected
    geometric-ground-support component of Uniform5 and reused for every map
    policy and ablation. Full/semantic costmaps still treat missing semantic or
    terrain evidence as unknown and may reject those endpoints. Failed/no-path
    results remain explicit.
    """
    reference_snapshot = snapshots_by_policy.get("uniform5")
    if not isinstance(reference_snapshot, dict) or not reference_snapshot.get("leaves"):
        return {
            "schema_version": 1,
            "status": "unavailable",
            "reason": "Uniform5 leaf snapshot is required as the high-resolution representation reference",
            "reference_is_ground_truth": False,
            "runs": [],
            "same_physical_snapshot_for_profiles": {},
        }

    profiles = (UGV_PROFILE, QUADRUPED_PROFILE)
    profile_rows = {
        profile.name: {
            "max_slope_rad": profile.max_slope_rad,
            "max_roughness_m": profile.max_roughness_m,
            "max_step_m": profile.max_step_m,
            "min_clearance_m": profile.min_clearance_m,
            "status": "illustrative_evaluation_assumptions_not_robot_certification",
        }
        for profile in profiles
    }
    snapshot_digests = {
        policy: _physical_snapshot_digest(snapshot)
        for policy, snapshot in snapshots_by_policy.items()
        if isinstance(snapshot, dict) and snapshot.get("leaves")
    }
    shared_snapshot = {
        policy: snapshot_digests.get(policy) is not None for policy in _PUBLIC_POLICIES
    }
    input_digests = {
        policy: snapshots_by_policy.get(policy, {}).get("stream_digest")
        for policy in _PUBLIC_POLICIES
        if isinstance(snapshots_by_policy.get(policy), dict)
    }
    all_inputs_match = (
        len(input_digests) == len(_PUBLIC_POLICIES)
        and all(isinstance(value, str) and value for value in input_digests.values())
        and len(set(input_digests.values())) == 1
    )
    if not all_inputs_match:
        return {
            "schema_version": 1,
            "status": "invalid",
            "reason": "policy stream digests are missing or differ; comparative planner evaluation requires identical input",
            "reference": "Uniform5-derived physical evidence, not surveyed ground truth",
            "reference_is_ground_truth": False,
            "reference_policy": "uniform5",
            "evaluation_lattice_m": CELL_SIZE_M,
            "same_input_for_all_policies": False,
            "input_stream_digest_by_policy": input_digests,
            "runs": [],
            "endpoints_by_profile": {},
            "weighted_score_used": False,
        }
    evaluation_roi = _bounded_reference_roi(reference_snapshot, max_grid_cells)
    roi_width = evaluation_roi[2] - evaluation_roi[0]
    roi_height = evaluation_roi[3] - evaluation_roi[1]
    reference_bounds = _active_leaf_bounds(reference_snapshot)
    full_roi = (
        min(item[0] for item in reference_bounds),
        min(item[1] for item in reference_bounds),
        max(item[2] for item in reference_bounds),
        max(item[3] for item in reference_bounds),
    )
    roi_metadata = {
        "bounds_5cm_lattice_exclusive": list(evaluation_roi),
        "bounds_xy_m_exclusive": [value * CELL_SIZE_M for value in evaluation_roi],
        "width_cells": roi_width,
        "height_cells": roi_height,
        "cropped_from_uniform5_bounds": evaluation_roi != full_roi,
        "selection": "centered_aspect_preserving_uniform5_active_bounds_crop",
    }
    runs: list[dict] = []
    endpoint_by_profile: dict[str, dict | None] = {}

    for profile in profiles:
        try:
            reference_grid = build_cost_grid(
                reference_snapshot,
                profile,
                ablation="full",
                max_grid_cells=max_grid_cells,
                roi_bounds=evaluation_roi,
            )
        except ValueError as error:
            endpoint_by_profile[profile.name] = None
            for policy in _PUBLIC_POLICIES:
                for ablation in _ABLATION_ORDER:
                    runs.append(
                        {
                            "policy": policy,
                            "profile": profile.name,
                            "ablation": ablation,
                            "status": "unavailable",
                            "reason": f"Uniform5 reference grid failed: {error}",
                            "planner_success": None,
                        }
                    )
            continue

        endpoint_grid = build_cost_grid(
            reference_snapshot,
            profile,
            ablation="geometry_only",
            max_grid_cells=max_grid_cells,
            roi_bounds=evaluation_roi,
        )
        endpoints = _reference_endpoints(endpoint_grid)
        endpoint_by_profile[profile.name] = (
            None
            if endpoints is None
            else {"start": list(endpoints[0]), "goal": list(endpoints[1])}
        )
        for policy in _PUBLIC_POLICIES:
            snapshot = snapshots_by_policy.get(policy)
            physical_digest = snapshot_digests.get(policy)
            if not isinstance(snapshot, dict) or not snapshot.get("leaves"):
                for ablation in _ABLATION_ORDER:
                    runs.append(
                        {
                            "policy": policy,
                            "profile": profile.name,
                            "ablation": ablation,
                            "status": "unavailable",
                            "reason": "policy leaf snapshot was not captured",
                            "planner_success": None,
                        }
                    )
                continue
            for ablation in _ABLATION_ORDER:
                row = {
                    "policy": policy,
                    "profile": profile.name,
                    "ablation": ablation,
                    "status": "measured",
                    "source_stream_digest": snapshot.get("stream_digest"),
                    "physical_snapshot_sha256": physical_digest,
                    "same_physical_snapshot_for_profiles": shared_snapshot[policy],
                }
                if endpoints is None:
                    row.update(
                        {
                            "status": "unavailable",
                            "reason": "Uniform5 reference has no multi-cell connected geometric-ground-support component",
                            "planner_success": None,
                        }
                    )
                    runs.append(row)
                    continue
                row["start"], row["goal"] = list(endpoints[0]), list(endpoints[1])
                try:
                    grid = build_cost_grid(
                        snapshot,
                        profile,
                        ablation=ablation,
                        max_grid_cells=max_grid_cells,
                        roi_bounds=evaluation_roi,
                    )
                except ValueError as error:
                    row.update(
                        {
                            "status": "invalid",
                            "reason": str(error),
                            "planner_success": None,
                        }
                    )
                    runs.append(row)
                    continue
                result = plan_grid(
                    grid,
                    endpoints[0],
                    endpoints[1],
                    algorithm="astar",
                    reference_grid=reference_grid,
                    max_expansions=max_expansions,
                )
                path = result.pop("path")
                row.update(
                    {
                        "planner_success": result["success"],
                        "path_length_m": result["path_length_m"],
                        "path_cost": result["path_cost"],
                        "planning_time_ms": result["planning_time_ns"] / 1_000_000.0,
                        "expanded_nodes": result["expanded_nodes"],
                        "reference_hazard_crossings": result[
                            "reference_hazard_crossings"
                        ],
                        "reference_unknown_crossings": result[
                            "reference_unknown_crossings"
                        ],
                        "reference_path_coverage": result["reference_path_coverage"],
                        "resolution_boundary_crossings": result[
                            "resolution_boundary_crossings"
                        ],
                        "path_cell_count": len(path),
                        "path_sha256": hashlib.sha256(
                            json.dumps(path, separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                        if path
                        else None,
                        "failure": result["failure"],
                        "costmap_lattice_m": CELL_SIZE_M,
                    }
                )
                if result["failure"] == "search_limit":
                    row["status"] = "partial"
                runs.append(row)

    return {
        "schema_version": 1,
        "status": "measured"
        if runs and all(item["status"] == "measured" for item in runs)
        else "partial",
        "reference": "Uniform5-derived physical evidence, not surveyed ground truth",
        "reference_is_ground_truth": False,
        "reference_policy": "uniform5",
        "evaluation_lattice_m": CELL_SIZE_M,
        "evaluation_roi": roi_metadata,
        "algorithm": "deterministic 8-connected A*; no diagonal corner cutting; expansion limit enforced",
        "endpoint_selection": "same per-profile endpoints for every policy and ablation, selected from largest 4-connected Uniform5 geometric-ground-support component; this does not assert semantic drivable status",
        "profile_assumptions": profile_rows,
        "same_input_for_all_policies": all_inputs_match,
        "input_stream_digest_by_policy": input_digests,
        "same_physical_snapshot_for_profiles": shared_snapshot,
        "physical_snapshot_sha256": snapshot_digests,
        "endpoints_by_profile": endpoint_by_profile,
        "ablation_order": list(_ABLATION_ORDER),
        "runs": runs,
        "hazard_metric_definition": "path cells marked hazardous or unknown by the profile-specific Uniform5 full-evidence reference; relative planner fidelity only, not absolute safety truth",
        "cost_definition": "base 1.0 plus 0.5 times capped normalized roughness, 0.5 times capped normalized slope, 0.5 times normalized geometry complexity when available, and in full mode 0.5 times one minus the lesser of semantic and terrain confidence; hard hazards are blocked",
    }


def write_planner_evaluation_artifacts(
    report: dict, output_dir: str | Path
) -> dict[str, str]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "planner_ablation.json"
    csv_path = destination / "planner_ablation.csv"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    fields = (
        "policy",
        "profile",
        "ablation",
        "status",
        "planner_success",
        "start",
        "goal",
        "path_length_m",
        "planning_time_ms",
        "path_cost",
        "reference_hazard_crossings",
        "reference_unknown_crossings",
        "reference_path_coverage",
        "expanded_nodes",
        "resolution_boundary_crossings",
        "path_cell_count",
        "path_sha256",
        "failure",
        "reason",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report.get("runs", []))
    return {"json": str(json_path), "csv": str(csv_path)}


__all__ = [
    "CELL_SIZE_M",
    "QUADRUPED_PROFILE",
    "UGV_PROFILE",
    "CostGrid",
    "VehicleCostProfile",
    "build_cost_grid",
    "plan_grid",
    "planner_evaluation_report",
    "write_planner_evaluation_artifacts",
]
