"""Run reproducible, multi-frame Veyra policy benchmarks on local data only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from benchmarks.protocol import PROTOCOL_VERSION, binary_stream_file
from datasets.generic import ManifestDataset
from datasets.rellis import Rellis3DDataset
from datasets.semantickitti import SemanticKITTIDataset
from datasets.semanticposs import SemanticPOSSDataset
from perception.pipeline import load_perception_pipeline

SCHEMA_VERSION = 2


@dataclass(frozen=True)
class PolicyAdapter:
    name: str
    cpp_policy: str | None
    available: bool
    integration_note: str
    utility_config: str = "utility_lod.yaml"
    suite: str = "public"
    signals: tuple[str, ...] = ()


POLICY_ADAPTERS = {
    "uniform5": PolicyAdapter("uniform5", "uniform5", True, "public adapter available"),
    "uniform40": PolicyAdapter(
        "uniform40", "uniform40", True, "public adapter available"
    ),
    "distance_lod": PolicyAdapter(
        "distance_lod", "distance_lod", True, "public adapter available"
    ),
    "utility_lod": PolicyAdapter(
        "utility_lod",
        "utility_lod",
        True,
        "stateful public map/policy adapter available",
        signals=("geometry", "semantics", "motion", "traversability", "uncertainty"),
    ),
    "ablation_distance": PolicyAdapter(
        "ablation_distance",
        "distance_lod",
        True,
        "distance-only control",
        suite="utility_ablation",
    ),
    "ablation_geometry": PolicyAdapter(
        "ablation_geometry",
        "utility_lod",
        True,
        "distance plus geometry",
        "utility_lod-geometry.yaml",
        "utility_ablation",
        ("geometry",),
    ),
    "ablation_semantics": PolicyAdapter(
        "ablation_semantics",
        "utility_lod",
        True,
        "distance plus semantic evidence",
        "utility_lod-semantics.yaml",
        "utility_ablation",
        ("semantics", "uncertainty"),
    ),
    "ablation_motion": PolicyAdapter(
        "ablation_motion",
        "utility_lod",
        True,
        "distance plus motion",
        "utility_lod-motion.yaml",
        "utility_ablation",
        ("motion",),
    ),
    "ablation_traversability": PolicyAdapter(
        "ablation_traversability",
        "utility_lod",
        True,
        "distance plus traversability risk",
        "utility_lod-traversability.yaml",
        "utility_ablation",
        ("traversability",),
    ),
}

PUBLIC_POLICY_NAMES = tuple(
    name for name, adapter in POLICY_ADAPTERS.items() if adapter.suite == "public"
)
UTILITY_ABLATION_POLICY_NAMES = (
    "ablation_distance",
    "ablation_geometry",
    "ablation_semantics",
    "ablation_motion",
    "ablation_traversability",
    "utility_lod",
)


def nearest_rank_summary(samples: list[int | float]) -> dict[str, int | float]:
    """Same nearest-rank p50/p95/p99 convention as the C++ collector."""
    if not samples:
        raise ValueError("cannot summarize an empty sample set")
    ordered = sorted(samples)

    def rank(percentile: float) -> int | float:
        return ordered[
            max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
        ]

    return {
        "count": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "p50": rank(0.50),
        "p95": rank(0.95),
        "p99": rank(0.99),
    }


# Nearest-rank tails on tiny samples are just the max. These thresholds mark
# when a published p95/p99 deserves to be read as a tail rather than as
# "the largest of a handful of frames". Advisory only: short runs (e.g. the
# 2-frame product-CI ablation smoke) remain valid executions.
MIN_SAMPLES_FOR_P95 = 20
MIN_SAMPLES_FOR_P99 = 100


def tail_reliability(count: int) -> dict[str, bool | int]:
    """Flag whether nearest-rank tails on ``count`` samples are meaningful."""
    samples = int(count)
    return {
        "samples": samples,
        "p95_reliable": samples >= MIN_SAMPLES_FOR_P95,
        "p99_reliable": samples >= MIN_SAMPLES_FOR_P99,
    }


def sample_adequacy_report(
    measured_frames_per_run: int, repetitions: int
) -> dict[str, Any]:
    """Describe tail reliability for the per-policy sample budgets of a run."""
    return {
        "measured_frames_per_run": int(measured_frames_per_run),
        "repetitions": int(repetitions),
        "stage_latency_samples_per_policy": tail_reliability(
            int(measured_frames_per_run) * int(repetitions)
        ),
        "fps_samples_per_policy": tail_reliability(int(repetitions)),
        "note": (
            "nearest-rank p95 needs >=20 samples and p99 >=100; "
            "short-run tails equal the max and are descriptive only, "
            "not SLO evidence"
        ),
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_sha(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _pull_request_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        event = json.loads(Path(event_path).read_text())
        return event.get("pull_request", {}).get("number")
    except (OSError, TypeError, json.JSONDecodeError):
        return None


def _host_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def hardware_metadata(profile: str) -> dict[str, Any]:
    """Capture runtime provenance; config profiles never invent hardware values."""
    cpu_model = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "profile": profile,
        "capture": "runtime",
        "os": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": cpu_model or platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": _host_memory_bytes(),
    }


def summarize_perception(
    dataset: str,
    sequence: str,
    records: list[dict[str, Any]],
    *,
    bridge_samples_ns: list[int] | None = None,
) -> dict[str, Any]:
    """Summarize the exact perception pass shared by every map policy.

    The benchmark keeps the detailed per-frame records out of the map report,
    but exports this compact artifact so CI can display stage tails without
    running the neural pipeline a second time.
    """
    if not records:
        raise ValueError("cannot summarize an empty perception selection")
    timing_names = tuple(records[0]["timings_ms"])
    if any(tuple(record["timings_ms"]) != timing_names for record in records):
        raise ValueError("perception timing stages must be consistent")
    statuses: dict[str, str] = {}
    for name in records[0]["status"]:
        values = {str(record["status"].get(name, "unavailable")) for record in records}
        statuses[name] = next(iter(values)) if len(values) == 1 else "mixed"

    def latency(values: list[float]) -> dict[str, float | int]:
        summary = nearest_rank_summary(values)
        return {
            "p50_ms": float(summary["p50"]),
            "p95_ms": float(summary["p95"]),
            "p99_ms": float(summary["p99"]),
            "mean_ms": float(summary["mean"]),
            "max_ms": float(summary["max"]),
            "samples": int(summary["count"]),
        }

    timing_reports = {
        name: latency([float(record["timings_ms"][name]) for record in records])
        for name in timing_names
    }
    load_values = [
        float(record["dataset_load_ms"])
        for record in records
        if record.get("dataset_load_ms") is not None
    ]
    if load_values:
        timing_reports["dataset_load"] = latency(load_values)
    if bridge_samples_ns:
        timing_reports["bridge"] = latency(
            [float(value) / 1_000_000.0 for value in bridge_samples_ns]
        )
    return {
        "dataset": dataset,
        "sequence": sequence,
        "frames": len(records),
        "points_processed": sum(int(record["points"]) for record in records),
        "failures": 0,
        "status": statuses,
        "ground_ratio": sum(float(record["ground_fraction"]) for record in records)
        / len(records),
        "known_terrain_fraction": sum(
            float(record["known_terrain_fraction"]) for record in records
        )
        / len(records),
        "known_motion_fraction": sum(
            float(record["known_motion_fraction"]) for record in records
        )
        / len(records),
        "timings": timing_reports,
        "bridge_scope": (
            "C++ protocol_parse_and_validate across measured policy streams"
            if bridge_samples_ns
            else "not measured"
        ),
    }


def analytical_3d_reference(points: np.ndarray) -> dict[str, Any]:
    """Describe a dense 5 cm 3D reference without executing it as a policy.

    The reference is deliberately analytical: materializing a dense 3D grid
    would be an unfair and potentially unbounded comparison for this sparse
    2.5D engine. Its estimate is still useful for showing the scale of the
    conventional representation, while the explicit status prevents it from
    being mistaken for measured runtime or RSS.
    """
    values = np.asarray(points)
    if values.ndim != 2 or values.shape[1] < 3 or values.shape[0] == 0:
        raise ValueError("3D reference requires a non-empty array with XYZ columns")
    xyz = values[:, :3].astype(np.float64, copy=False)
    if not np.isfinite(xyz).all():
        raise ValueError("3D reference points must be finite")
    return analytical_3d_reference_bounds(xyz.min(axis=0), xyz.max(axis=0))


def analytical_3d_reference_bounds(
    minimum: np.ndarray, maximum: np.ndarray
) -> dict[str, Any]:
    """Build the analytical 3D reference from streaming XYZ bounds."""
    minimum = np.asarray(minimum, dtype=np.float64)
    maximum = np.asarray(maximum, dtype=np.float64)
    if minimum.shape != (3,) or maximum.shape != (3,):
        raise ValueError("3D reference bounds must contain three coordinates")
    if not np.isfinite(minimum).all() or not np.isfinite(maximum).all():
        raise ValueError("3D reference bounds must be finite")
    if np.any(maximum < minimum):
        raise ValueError("3D reference maximum must not precede minimum")
    voxel_size = 0.05
    dimensions = np.maximum(
        1, np.ceil((maximum - minimum) / voxel_size).astype(np.int64) + 1
    )
    dense_voxel_count = int(np.prod(dimensions, dtype=object))
    return {
        "status": "analytical_only",
        "executed_through_map_engine": False,
        "representation": "dense_uniform_3d_voxels",
        "voxel_size_m": voxel_size,
        "bounds_min_m": minimum.tolist(),
        "bounds_max_m": maximum.tolist(),
        "dimensions": dimensions.tolist(),
        "dense_voxel_count": dense_voxel_count,
        "estimated_bytes_per_voxel": 16,
        "estimated_dense_bytes": dense_voxel_count * 16,
        "warning": "memory estimate only; no dense grid was allocated or timed",
    }


class SemanticQualityAccumulator:
    """Accumulate range-binned semantic confusion without retaining frames."""

    _BINS = ((0.0, 10.0), (10.0, 30.0), (30.0, 60.0), (60.0, 100.0))

    def __init__(self) -> None:
        self._confusion: list[dict[tuple[int, int], int]] = [{} for _ in self._BINS]

    def update(self, reference: Any, prediction: Any) -> None:
        if reference.points.shape != prediction.points.shape:
            raise ValueError("semantic quality requires point-aligned frames")
        ranges = np.linalg.norm(reference.points[:, :3], axis=1)
        truth = np.asarray(reference.semantic_class, dtype=np.int32)
        predicted = np.asarray(prediction.semantic_class, dtype=np.int32)
        for index, (lower, upper) in enumerate(self._BINS):
            mask = (ranges >= lower) & (ranges < upper)
            if not np.any(mask):
                continue
            pairs, counts = np.unique(
                np.column_stack((truth[mask], predicted[mask])),
                axis=0,
                return_counts=True,
            )
            confusion = self._confusion[index]
            for (actual, inferred), count in zip(pairs, counts, strict=True):
                key = (int(actual), int(inferred))
                confusion[key] = confusion.get(key, 0) + int(count)

    @staticmethod
    def _score(confusion: dict[tuple[int, int], int]) -> dict[str, Any]:
        total = sum(confusion.values())
        if not total:
            return {"points": 0, "accuracy": None, "miou": None, "classes": {}}
        classes = sorted({item for pair in confusion for item in pair})
        class_iou: dict[str, float] = {}
        for class_id in classes:
            true_positive = confusion.get((class_id, class_id), 0)
            false_positive = sum(
                count
                for (actual, inferred), count in confusion.items()
                if inferred == class_id and actual != class_id
            )
            false_negative = sum(
                count
                for (actual, inferred), count in confusion.items()
                if actual == class_id and inferred != class_id
            )
            union = true_positive + false_positive + false_negative
            class_iou[str(class_id)] = true_positive / union if union else 1.0
        correct = sum(
            count
            for (actual, inferred), count in confusion.items()
            if actual == inferred
        )
        return {
            "points": total,
            "accuracy": correct / total,
            "miou": float(np.mean(list(class_iou.values()))),
            "classes": class_iou,
        }

    def report(self) -> dict[str, Any]:
        combined: dict[tuple[int, int], int] = {}
        for confusion in self._confusion:
            for key, count in confusion.items():
                combined[key] = combined.get(key, 0) + count
        return {
            "status": "measured",
            "reference": "adapter semantic_class labels",
            "prediction": "perception output semantic_class",
            "overall": self._score(combined),
            "range_bins": [
                {
                    "min_m": lower,
                    "max_m": upper,
                    **self._score(confusion),
                }
                for (lower, upper), confusion in zip(
                    self._BINS, self._confusion, strict=True
                )
            ],
        }


def semantic_range_quality_report(
    reference_frames: list[Any], predicted_frames: list[Any]
) -> dict[str, Any]:
    """Compare mapped semantic IDs against adapter labels in distance bins."""
    if len(reference_frames) != len(predicted_frames) or not reference_frames:
        raise ValueError(
            "semantic quality requires equally sized non-empty frame lists"
        )
    accumulator = SemanticQualityAccumulator()
    for reference, prediction in zip(reference_frames, predicted_frames):
        accumulator.update(reference, prediction)
    return accumulator.report()


def _fine_cell_owners(
    snapshot: dict[str, Any], fine_bins: set[tuple[int, int]]
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """Return active leaves covering each observed L0 (5 cm) bin.

    The map emits integer dyadic IDs.  Testing ownership from those IDs is
    independent of the mapper's aggregate invariant flag and is bounded by
    four level checks per observed bin.  Bins outside the observed input are
    deliberately not considered: a sparse map is allowed to have no leaf in
    unobserved space.
    """
    by_id: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for leaf in snapshot.get("leaves", []):
        try:
            level = int(leaf["level"])
            ix = int(leaf["ix"])
            iy = int(leaf["iy"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("leaf details must contain integer level/ix/iy") from error
        if not 0 <= level <= 3:
            raise ValueError("leaf level must be in [0,3]")
        by_id.setdefault((level, ix, iy), []).append(leaf)
    owners = {key: [] for key in fine_bins}
    for key in fine_bins:
        for level in range(4):
            owners[key].extend(by_id.get((level, key[0] >> level, key[1] >> level), []))
    return owners


def mixed_resolution_topology_report(
    snapshot: dict[str, Any], fine_bins: set[tuple[int, int]]
) -> dict[str, Any]:
    """Check leaf geometry over the observed input domain.

    This checks duplicate IDs, parent/descendant exclusivity, and exactly-one
    ownership for every observed fine bin.  It does not claim that a sparse
    map covers unobserved world space.
    """
    leaves = snapshot.get("leaves", [])
    ids: list[tuple[int, int, int]] = []
    for leaf in leaves:
        try:
            identifier = (int(leaf["level"]), int(leaf["ix"]), int(leaf["iy"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("leaf details must contain integer level/ix/iy") from error
        if not 0 <= identifier[0] <= 3:
            raise ValueError("leaf level must be in [0,3]")
        ids.append(identifier)
    id_set = set(ids)
    duplicate_leaf_ids = len(ids) - len(id_set)
    parent_descendant_conflicts = 0
    for level, ix, iy in id_set:
        # L0 is finest and L3 is coarsest.  A finer leaf's active ancestors
        # therefore have larger numeric levels, exactly like CellId::parent.
        for ancestor_level in range(level + 1, 4):
            shift = ancestor_level - level
            if (ancestor_level, ix >> shift, iy >> shift) in id_set:
                parent_descendant_conflicts += 1
                break
    owners = _fine_cell_owners(snapshot, fine_bins)
    gap = sum(not values for values in owners.values())
    overlap = sum(len(values) > 1 for values in owners.values())
    covered = len(fine_bins) - gap
    valid = (
        not duplicate_leaf_ids
        and not parent_descendant_conflicts
        and not gap
        and not overlap
    )
    return {
        "status": "valid" if valid else "invalid",
        "scope": "observed 5cm reference bins only; unobserved sparse space is excluded",
        "leaf_count": len(ids),
        "duplicate_leaf_ids": duplicate_leaf_ids,
        "parent_descendant_exclusive": parent_descendant_conflicts == 0,
        "parent_descendant_conflicts": parent_descendant_conflicts,
        "observed_bins": {
            "total": len(fine_bins),
            "covered": covered,
            "gap": gap,
            "overlap": overlap,
            "exactly_one_owner": gap == 0 and overlap == 0,
        },
    }


def field_retention_report(
    frames: list[Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Compare retained leaf evidence with fine-bin source evidence.

    The current public C++ benchmark snapshot may omit semantic/drivable leaf
    fields.  In that case each field is explicitly unavailable rather than
    inferred from topology or elevation.
    """
    fine: dict[tuple[int, int], dict[str, Any]] = {}
    for frame in frames:
        for index, point in enumerate(frame.points):
            key = (math.floor(float(point[0]) * 20), math.floor(float(point[1]) * 20))
            item = fine.setdefault(key, {"classes": {}, "hazard": False})
            semantic = int(np.asarray(frame.semantic_class)[index])
            if semantic != 0:
                item["classes"][semantic] = item["classes"].get(semantic, 0) + 1
            item["hazard"] = (
                item["hazard"]
                or str(np.asarray(frame.drivable)[index]) == "non_drivable"
            )
    owners = _fine_cell_owners(snapshot, set(fine))

    semantic = {
        "status": "unavailable",
        "reason": "snapshot leaves omit semantic_class",
    }
    hazard = {
        "status": "unavailable",
        "reason": "snapshot leaves omit drivable_evidence",
    }
    if all("semantic_class" in leaf for leaf in snapshot.get("leaves", [])):
        relevant = [item for item in fine.values() if item["classes"]]
        retained = 0
        for key, item in fine.items():
            if not item["classes"] or len(owners[key]) != 1:
                continue
            expected = max(item["classes"], key=item["classes"].get)
            retained += int(int(owners[key][0]["semantic_class"]) == expected)
        semantic = {
            "status": "measured",
            "reference_bins": len(relevant),
            "covered_bins": sum(
                bool(item["classes"]) and len(owners[key]) == 1
                for key, item in fine.items()
            ),
            "retained_bins": retained,
            "retention_fraction": retained / len(relevant) if relevant else None,
            "reference": "dominant nonzero semantic class per observed 5cm bin",
        }
    if all("drivable_evidence" in leaf for leaf in snapshot.get("leaves", [])):
        relevant = [item for item in fine.values() if item["hazard"]]
        retained = sum(
            int(owners[key][0]["drivable_evidence"] < 0)
            for key, item in fine.items()
            if item["hazard"] and len(owners[key]) == 1
        )
        hazard = {
            "status": "measured",
            "reference_bins": len(relevant),
            "covered_bins": sum(
                item["hazard"] and len(owners[key]) == 1 for key, item in fine.items()
            ),
            "retained_bins": retained,
            "retention_fraction": retained / len(relevant) if relevant else None,
            "reference": "any non-drivable evidence per observed 5cm bin",
        }
    # Task-class retention isolates the small/thin classes UtilityLOD exists to
    # protect at range. Groups use Veyra SemanticKITTI-learning IDs: pole 18,
    # pedestrian person 6 / bicyclist 7, vehicle 1-5. Additive detail only: the
    # overall semantic/hazard status contract above is unchanged.
    task_classes: dict[str, Any] = {
        "status": "unavailable",
        "reason": "snapshot leaves omit semantic_class",
    }
    if all("semantic_class" in leaf for leaf in snapshot.get("leaves", [])):
        groups = {
            "pole": {18},
            "pedestrian": {6, 7},
            "vehicle": {1, 2, 3, 4, 5},
        }
        members: dict[str, Any] = {}
        for group, classes in groups.items():
            relevant_bins = [
                key
                for key, item in fine.items()
                if item["classes"]
                and max(item["classes"], key=item["classes"].get) in classes
            ]
            retained_bins = sum(
                int(int(owners[key][0]["semantic_class"]) in classes)
                for key in relevant_bins
                if len(owners[key]) == 1
            )
            members[group] = {
                "status": "measured",
                "class_ids": sorted(classes),
                "reference_bins": len(relevant_bins),
                "covered_bins": sum(len(owners[key]) == 1 for key in relevant_bins),
                "retained_bins": retained_bins,
                "retention_fraction": retained_bins / len(relevant_bins)
                if relevant_bins
                else None,
                "reference": "dominant nonzero semantic class per observed 5cm bin",
            }
        task_classes = {"status": "measured", "members": members}
    field_statuses = {semantic["status"], hazard["status"]}
    status = (
        "measured"
        if field_statuses == {"measured"}
        else "partial"
        if "measured" in field_statuses
        else "unavailable"
    )
    return {
        "status": status,
        "semantic": semantic,
        "terrain_hazard": hazard,
        "task_classes": task_classes,
    }


def mapping_quality_report(
    input_points: np.ndarray | int,
    rejected_out_of_window: int,
    snapshot: dict[str, Any],
    fine_reference: dict[str, Any],
    *,
    frames: list[Any] | None = None,
) -> dict[str, Any]:
    """Measure only conservation/topology/elevation evidence exposed by the map."""
    point_count = int(snapshot["point_count"])
    nonspatial = int(snapshot.get("nonspatial_prior_point_count", 0))
    leaf_count = sum(int(leaf["count"]) for leaf in snapshot.get("leaves", []))
    input_count = (
        int(input_points)
        if isinstance(input_points, (int, np.integer))
        else len(input_points)
    )
    expected = input_count - int(rejected_out_of_window)
    conservation = point_count == expected
    split_merge = leaf_count + nonspatial == point_count
    errors: list[float] = []
    reference = fine_reference["mean_z_by_cell"]
    # Reconstruct each observed fine bin from its active owner. Averaging the
    # reference inside a coarse leaf hides precisely the detail LOD discards.
    # Four lookups per reference bin also avoid leaf_count * reference_count.
    owners = {
        (int(leaf["level"]), int(leaf["ix"]), int(leaf["iy"])): (
            float(leaf["mean_z"]),
            int(leaf["level"]),
        )
        for leaf in snapshot.get("leaves", [])
        if int(leaf["count"]) > 0
    }
    band_errors: dict[tuple[float, float], list[float]] = {
        band: [] for band in _RANGE_BANDS
    }
    band_levels: dict[tuple[float, float], list[int]] = {
        band: [] for band in _RANGE_BANDS
    }
    band_reference: dict[tuple[float, float], int] = {band: 0 for band in _RANGE_BANDS}
    mean_range_by_cell = fine_reference.get("mean_range_by_cell", {})
    for (ix, iy), value in reference.items():
        for level in range(4):
            estimate = owners.get((level, ix >> level, iy >> level))
            if estimate is not None:
                errors.append(estimate[0] - value)
                cell_range = mean_range_by_cell.get((ix, iy))
                if cell_range is not None:
                    for band in _RANGE_BANDS:
                        if band[0] <= cell_range < band[1]:
                            band_errors[band].append(estimate[0] - value)
                            band_levels[band].append(estimate[1])
                            break
                break
    for ix, iy in reference:
        cell_range = mean_range_by_cell.get((ix, iy))
        if cell_range is not None:
            for band in _RANGE_BANDS:
                if band[0] <= cell_range < band[1]:
                    band_reference[band] += 1
                    break
    rmse = (
        math.sqrt(sum(error * error for error in errors) / len(errors))
        if errors
        else None
    )
    elevation_by_range = []
    for band in _RANGE_BANDS:
        band_err = band_errors[band]
        levels = band_levels[band]
        elevation_by_range.append(
            {
                "min_m": band[0],
                "max_m": band[1],
                "reference_bins": band_reference[band],
                "sample_count": len(band_err),
                "coverage": (
                    len(band_err) / band_reference[band]
                    if band_reference[band]
                    else None
                ),
                "rmse_m": (
                    math.sqrt(sum(e * e for e in band_err) / len(band_err))
                    if band_err
                    else None
                ),
                "mean_owner_level": (sum(levels) / len(levels) if levels else None),
                "scope": (
                    "observed 5cm bins banded by mean point range; "
                    "unavailable without retained source frames"
                    if mean_range_by_cell
                    else "unavailable: source frames were not retained"
                ),
            }
        )
    topology = mixed_resolution_topology_report(snapshot, set(reference))
    retention = (
        field_retention_report(frames, snapshot)
        if frames is not None
        else {
            "status": "unavailable",
            "reason": "source ObservationFrames were not supplied",
            "semantic": {
                "status": "unavailable",
                "reason": "source ObservationFrames were not supplied",
            },
            "terrain_hazard": {
                "status": "unavailable",
                "reason": "source ObservationFrames were not supplied",
            },
        }
    )
    return {
        "point_conservation": {
            "holds": conservation,
            "expected_points": expected,
            "snapshot_points": point_count,
        },
        "duplicate_ownership": {
            "holds": bool(
                topology["duplicate_leaf_ids"] == 0
                and topology["observed_bins"]["overlap"] == 0
                and topology["parent_descendant_exclusive"]
            ),
            "source": "independent active-leaf ID and observed-bin ownership check",
            "map_reported_flag": snapshot.get("invariant_no_parent_descendant_overlap"),
        },
        "split_merge_conservation": {
            "holds": split_merge,
            "leaf_stat_points": leaf_count,
            "nonspatial_prior_points": nonspatial,
            "snapshot_points": point_count,
        },
        "elevation_vs_fine_reference": {
            "sample_count": len(errors),
            "rmse_m": rmse,
            "reference": "5cm input-point bins",
            "reference_bins": len(reference),
            "coverage": len(errors) / len(reference) if reference else None,
            "scope": "observed reference bins covered by final active leaves; excludes evicted/uncovered bins",
            "by_range": elevation_by_range,
        },
        "mixed_resolution_topology": topology,
        "field_retention": retention,
    }


# Veyra distance hierarchy for range-banded map quality. A bin belongs to the
# band containing its mean point range; bands are half-open [min, max).
_RANGE_BANDS: tuple[tuple[float, float], ...] = (
    (0.0, 10.0),
    (10.0, 30.0),
    (30.0, 60.0),
    (60.0, 100.0),
)


def _fine_reference(frames: list[Any]) -> dict[str, Any]:
    bins: dict[tuple[int, int], tuple[float, float, int]] = {}
    for frame in frames:
        pose = np.asarray(frame.pose.matrix, dtype=np.float64)
        origin_x, origin_y = float(pose[0, 3]), float(pose[1, 3])
        for x, y, z, _intensity in frame.points:
            key = (math.floor(float(x) * 20), math.floor(float(y) * 20))
            total_z, total_r, count = bins.get(key, (0.0, 0.0, 0))
            point_range = math.hypot(float(x) - origin_x, float(y) - origin_y)
            bins[key] = (total_z + float(z), total_r + point_range, count + 1)
    return {
        "mean_z_by_cell": {
            key: total_z / count for key, (total_z, _total_r, count) in bins.items()
        },
        "mean_range_by_cell": {
            key: total_r / count for key, (_total_z, total_r, count) in bins.items()
        },
    }


def _fine_reference_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Use the executed Uniform5 map as the fine elevation reference.

    Uniform5 owns the same world-aligned 5 cm bins as the source stream, so
    its sufficient-statistic means are the exact reference needed by the
    adaptive comparisons. This avoids rebuilding a Python dictionary from
    every point in a long sequence.
    """
    return {
        "mean_z_by_cell": {
            (int(leaf["ix"]), int(leaf["iy"])): float(leaf["mean_z"])
            for leaf in snapshot.get("leaves", [])
            if int(leaf.get("level", -1)) == 0 and int(leaf.get("count", 0)) > 0
        }
    }


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Drop optional leaf rows after quality calculations have consumed them."""
    compact = dict(snapshot)
    compact.pop("leaves", None)
    return compact


def _finalize_policy_runs(
    runs_by_policy: dict[str, list[dict[str, Any]]],
    selection: dict[str, Any],
    *,
    frames: list[Any] | None = None,
) -> dict[str, Any]:
    """Attach quality reports, then release long-run leaf-detail payloads.

    ``frames`` is the retained source selection. It stays ``None`` on the
    default streaming path (bounded memory, retention unavailable); the
    opt-in ``--retain-frames`` path supplies it so field and task-class
    retention are measured on the identical stream every policy consumed.
    Retained frames also supply per-bin ranges, so the point-built reference
    (with range bands) is preferred over the Uniform5-snapshot reference
    whenever frames are available.
    """
    if frames is not None:
        fine_reference = _fine_reference(frames)
    else:
        fine_reference = (
            _fine_reference_from_snapshot(runs_by_policy["uniform5"][0]["snapshot"])
            if runs_by_policy.get("uniform5")
            else {"mean_z_by_cell": {}}
        )
    for runs in runs_by_policy.values():
        for result in runs:
            result["quality"] = mapping_quality_report(
                selection["point_count"],
                result["metrics"]["stream"]["rejected_out_of_window"],
                result["snapshot"],
                fine_reference,
                frames=frames,
            )
            if result.get("frame_metrics"):
                frame_conservation = result["frame_metrics"][-1].get(
                    "point_conservation"
                )
                if frame_conservation is not None:
                    result["quality"]["point_conservation"] = frame_conservation
            result["snapshot"] = _compact_snapshot(result["snapshot"])
    return fine_reference


def _detail_metric(snapshot: dict[str, Any]) -> dict[str, Any]:
    leaves = snapshot.get("leaves", [])
    total = sum(int(leaf["count"]) for leaf in leaves)
    weighted_level = (
        sum(int(leaf["count"]) * int(leaf["level"]) for leaf in leaves) / total
        if total
        else None
    )
    return {
        "weighted_mean_level": weighted_level,
        "weighted_resolution_m": None
        if weighted_level is None
        else 0.05 * (2**weighted_level),
        "basis": "leaf sufficient-statistic counts",
    }


def validate_hardware_profile(config: object, profile: str) -> None:
    if not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("configs/hardware_profiles.yaml must use schema_version 2")
    profiles = config.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("configs/hardware_profiles.yaml must define profiles")  # noqa: TRY004
    matched = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("name") == profile
    ]
    if len(matched) != 1 or matched[0].get("capture") != "runtime":
        raise ValueError(
            f"hardware profile must be one runtime-capture profile: {profile}"
        )


def compute_window_radius_m(frames: list[Any], configured_radius_m: float) -> float:
    """Return the smallest common world-frame window that contains all input."""
    required = float(configured_radius_m)
    for frame in frames:
        distance = np.hypot(
            frame.points[:, 0] - frame.pose.matrix[0, 3],
            frame.points[:, 1] - frame.pose.matrix[1, 3],
        )
        if distance.size:
            required = max(required, float(np.max(distance)))
    # The selected points are float32 while C++ parses decimal float64. Keep a
    # recorded 1 mm containment margin so a point exactly on the source crop
    # boundary is not rejected by representation-level roundoff.
    return required + 0.001


def _normalized_distance_config(distance_config: object) -> dict[str, Any]:
    """Normalize legacy detailed and current compact DistanceLOD configuration."""
    if not isinstance(distance_config, dict):
        raise ValueError("configs/distance_lod.yaml must contain a mapping")  # noqa: TRY004
    if "ranges_m" not in distance_config:
        boundaries = distance_config.get("distance_boundaries_m")
        maximum = distance_config.get("max_range_m")
        if distance_config.get("mode") != "distance_lod":
            raise ValueError("compact distance_lod mode must be distance_lod")
        if not isinstance(boundaries, list) or tuple(map(float, boundaries)) != (
            10.0,
            30.0,
            60.0,
        ):
            raise ValueError("compact distance_lod boundaries must be 10,30,60 m")
        if float(maximum) != 100.0:
            raise ValueError("compact distance_lod max range must be 100 m")
        return {
            "levels": [0.05, 0.10, 0.20, 0.40],
            "ranges_m": [[0.0, 10.0], [10.0, 30.0], [30.0, 60.0], [60.0, 100.0]],
            "frame": "odom",
            "source_schema": "compact",
        }
    return dict(distance_config)


def validate_configs(dataset_config: object, distance_config: object) -> None:
    if not isinstance(dataset_config, dict):
        raise ValueError("configs/datasets.yaml must contain a mapping")  # noqa: TRY004
    normalized = _normalized_distance_config(distance_config)
    if normalized.get("frame") != "odom":
        raise ValueError("distance_lod frame must be odom")
    levels, ranges = normalized.get("levels"), normalized.get("ranges_m")
    if not isinstance(levels, list) or tuple(map(float, levels)) != (
        0.05,
        0.10,
        0.20,
        0.40,
    ):
        raise ValueError(
            "distance_lod levels do not match supported dyadic resolutions"
        )
    if not isinstance(ranges, list) or len(ranges) != 4:
        raise ValueError("distance_lod.yaml must define four ranges")
    parsed_ranges: list[tuple[float, float]] = []
    for item in ranges:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(value, (int, float)) for value in item)
        ):
            raise ValueError("distance_lod ranges must be numeric [min,max] pairs")
        lower, upper = map(float, item)
        if lower >= upper:
            raise ValueError("distance_lod ranges must be increasing")
        parsed_ranges.append((lower, upper))
    if parsed_ranges[0][0] != 0.0:
        raise ValueError("distance_lod ranges must start at zero")
    if any(previous[1] != current[0] for previous, current in pairwise(parsed_ranges)):
        raise ValueError("distance_lod ranges must be contiguous")
    for name in ("semanticposs", "rellis3d"):
        entry = dataset_config.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"configs/datasets.yaml must define {name}")  # noqa: TRY004
        for key in ("root", "sequences", "scan_dir", "label_dir", "max_range_m"):
            if key not in entry:
                raise ValueError(f"dataset config for {name} missing {key}")
        if not isinstance(entry["root"], str) or Path(entry["root"]).is_absolute():
            raise ValueError(f"dataset root for {name} must be repository-relative")
        if not isinstance(entry["sequences"], list) or not entry["sequences"]:
            raise ValueError(f"dataset sequences for {name} must be non-empty")
        if (
            float(entry.get("min_range_m", 0.0)) < 0.0
            or float(entry["max_range_m"]) != parsed_ranges[-1][1]
        ):
            raise ValueError(f"dataset range for {name} must match distance_lod.yaml")


def stream_selection(
    repo: Path,
    dataset: str,
    sequence: str,
    start: int,
    count: int,
    *,
    run_perception: bool = True,
    perception_config: Path | None = None,
    dataset_root: Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Return a one-shot real-data frame iterator and bounded run metadata.

    The iterator owns the adapter and perception pipeline and processes one
    frame at a time. The metadata dictionary is populated as the iterator is
    consumed; callers must finish consuming it before using ``window_radius``
    or the aggregate bounds.
    """
    dataset_config = yaml.safe_load((repo / "configs/datasets.yaml").read_text())
    raw_distance_config = yaml.safe_load(
        (repo / "configs/distance_lod.yaml").read_text()
    )
    benchmark_config = yaml.safe_load((repo / "configs/benchmark.yaml").read_text())
    if (
        not isinstance(benchmark_config, dict)
        or benchmark_config.get("map_frame") != "odom"
    ):
        raise ValueError("configs/benchmark.yaml must declare map_frame: odom")
    validate_configs(dataset_config, raw_distance_config)
    distance_config = _normalized_distance_config(raw_distance_config)
    entry = dataset_config.get(dataset)
    if dataset == "generic" and dataset_root is not None:
        entry = {"root": str(dataset_root), "min_range_m": 0.0, "max_range_m": 100.0}
    if entry is None:
        raise ValueError(f"unknown dataset: {dataset}")
    root = (
        Path(dataset_root).resolve()
        if dataset_root is not None
        else repo / entry["root"]
    )
    if not root.is_dir():
        raise FileNotFoundError(f"configured dataset root does not exist: {root}")
    if dataset == "generic":
        adapter = ManifestDataset(root)
    else:
        adapter_type = {
            "semanticposs": SemanticPOSSDataset,
            "semantickitti": SemanticKITTIDataset,
            "rellis3d": Rellis3DDataset,
        }[dataset]
        adapter = adapter_type(
            root,
            sequences=[sequence] if dataset_root is not None else entry["sequences"],
            scan_dir=entry["scan_dir"],
            label_dir=entry["label_dir"],
        )
    if sequence not in adapter.list_sequences():
        raise ValueError(f"sequence {sequence} is not configured for {dataset}")
    if start < 0 or count <= 0:
        raise ValueError("start must be non-negative and count must be positive")

    state: dict[str, Any] = {
        "distance_config": distance_config,
        "entry": entry,
        "frames": 0,
        "point_count": 0,
        "min_xyz": np.full(3, np.inf, dtype=np.float64),
        "max_xyz": np.full(3, -np.inf, dtype=np.float64),
        "window_radius_m": float(entry["max_range_m"]),
        "perception_ns": [],
        "perception_records": [],
        "semantic_quality": SemanticQualityAccumulator() if run_perception else None,
    }

    def generate():
        pipeline = (
            load_perception_pipeline(
                perception_config or repo / "configs" / "perception.yaml"
            )
            if run_perception
            else None
        )
        replay = adapter.replay(
            sequence,
            start=start,
            end=start + count,
            min_range_m=float(entry.get("min_range_m", 0.0)),
            max_range_m=float(entry["max_range_m"]),
        )
        for _ in range(count):
            load_started = time.perf_counter_ns()
            try:
                source_frame = next(replay)
            except StopIteration:
                break
            load_duration_ms = (time.perf_counter_ns() - load_started) / 1_000_000.0
            output_frame = source_frame
            timings: dict[str, float] = {}
            if pipeline is not None:
                started = time.perf_counter_ns()
                output = pipeline.process(source_frame)
                output_frame = output.frame
                state["perception_ns"].append(time.perf_counter_ns() - started)
                timings = output.timings_ms
                state["perception_records"].append(
                    {
                        "points": len(source_frame.points),
                        "dataset_load_ms": load_duration_ms,
                        "timings_ms": timings,
                        "status": {
                            "semantic": output.status.semantic,
                            "ground": output.status.ground,
                            "terrain": output.status.terrain,
                            "temporal": output.status.temporal,
                        },
                        "ground_fraction": float(output_frame.ground.mean()),
                        "known_terrain_fraction": float(
                            (output_frame.drivable != "unknown").mean()
                        ),
                        "known_motion_fraction": float(
                            (output_frame.motion_state != "unknown").mean()
                        ),
                    }
                )
                state["semantic_quality"].update(source_frame, output_frame)
            points = np.asarray(output_frame.points[:, :3], dtype=np.float64)
            if points.size:
                state["min_xyz"] = np.minimum(state["min_xyz"], points.min(axis=0))
                state["max_xyz"] = np.maximum(state["max_xyz"], points.max(axis=0))
                state["point_count"] += len(points)
                distance = np.hypot(
                    points[:, 0] - output_frame.pose.matrix[0, 3],
                    points[:, 1] - output_frame.pose.matrix[1, 3],
                )
                if distance.size:
                    state["window_radius_m"] = max(
                        state["window_radius_m"], float(distance.max())
                    )
            state["frames"] += 1
            yield output_frame
        if state["frames"] == 0:
            raise ValueError("frame selection is empty")

    return generate(), state


def load_selection(
    repo: Path,
    dataset: str,
    sequence: str,
    start: int,
    count: int,
    *,
    run_perception: bool = True,
    perception_config: Path | None = None,
    dataset_root: Path | None = None,
    perception_records: list[dict[str, Any]] | None = None,
    reference_frames: list[Any] | None = None,
):
    dataset_config = yaml.safe_load((repo / "configs/datasets.yaml").read_text())
    raw_distance_config = yaml.safe_load(
        (repo / "configs/distance_lod.yaml").read_text()
    )
    benchmark_config = yaml.safe_load((repo / "configs/benchmark.yaml").read_text())
    if (
        not isinstance(benchmark_config, dict)
        or benchmark_config.get("map_frame") != "odom"
    ):
        raise ValueError("configs/benchmark.yaml must declare map_frame: odom")
    validate_configs(dataset_config, raw_distance_config)
    distance_config = _normalized_distance_config(raw_distance_config)
    entry = dataset_config.get(dataset)
    if dataset == "generic" and dataset_root is not None:
        entry = {"root": str(dataset_root), "min_range_m": 0.0, "max_range_m": 100.0}
    if entry is None:
        raise ValueError(f"unknown dataset: {dataset}")
    root = (
        Path(dataset_root).resolve()
        if dataset_root is not None
        else repo / entry["root"]
    )
    if not root.is_dir():
        raise FileNotFoundError(f"configured dataset root does not exist: {root}")
    if dataset == "generic":
        adapter = ManifestDataset(root)
    else:
        adapter_type = {
            "semanticposs": SemanticPOSSDataset,
            "semantickitti": SemanticKITTIDataset,
            "rellis3d": Rellis3DDataset,
        }[dataset]
        adapter = adapter_type(
            root,
            sequences=[sequence] if dataset_root is not None else entry["sequences"],
            scan_dir=entry["scan_dir"],
            label_dir=entry["label_dir"],
        )
    if sequence not in adapter.list_sequences():
        raise ValueError(f"sequence {sequence} is not configured for {dataset}")
    source_frames = []
    load_durations_ms: list[float] = []
    replay = adapter.replay(
        sequence,
        start=start,
        end=start + count,
        min_range_m=float(entry.get("min_range_m", 0.0)),
        max_range_m=float(entry["max_range_m"]),
    )
    while True:
        started = time.perf_counter_ns()
        try:
            source_frames.append(next(replay))
        except StopIteration:
            break
        load_durations_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
    if not source_frames:
        raise ValueError("frame selection is empty")
    if reference_frames is not None:
        reference_frames.extend(source_frames)
    processed, durations_ns = source_frames, []
    if run_perception:
        pipeline = load_perception_pipeline(
            perception_config or repo / "configs" / "perception.yaml"
        )
        processed = []
        for source_frame, load_duration_ms in zip(source_frames, load_durations_ms):
            started = time.perf_counter_ns()
            output = pipeline.process(source_frame)
            processed.append(output.frame)
            durations_ns.append(time.perf_counter_ns() - started)
            if perception_records is not None:
                perception_records.append(
                    {
                        "points": len(source_frame.points),
                        "dataset_load_ms": load_duration_ms,
                        "timings_ms": output.timings_ms,
                        "status": {
                            "semantic": output.status.semantic,
                            "ground": output.status.ground,
                            "terrain": output.status.terrain,
                            "temporal": output.status.temporal,
                        },
                        "ground_fraction": float(output.frame.ground.mean()),
                        "known_terrain_fraction": float(
                            (output.frame.drivable != "unknown").mean()
                        ),
                        "known_motion_fraction": float(
                            (output.frame.motion_state != "unknown").mean()
                        ),
                    }
                )
    return (
        processed,
        distance_config,
        entry,
        durations_ns,
        compute_window_radius_m(processed, float(entry["max_range_m"])),
    )


def _command(
    binary: str,
    adapter: PolicyAdapter,
    distance_config: dict[str, Any],
    window_radius_m: float,
    warmup_frames: int,
    repo: Path,
    governor_config: str | Path | None = None,
) -> list[str]:
    ranges = distance_config["ranges_m"]
    governor_path = (
        Path(governor_config)
        if governor_config is not None and Path(governor_config).is_absolute()
        else repo / str(governor_config or "configs/resource_governor.yaml")
    )
    return [
        binary,
        "--policy",
        str(adapter.cpp_policy),
        "--levels",
        ",".join(str(float(item)) for item in distance_config["levels"]),
        "--window-radius",
        str(window_radius_m),
        "--distance-boundaries",
        ",".join(str(float(item[1])) for item in ranges[:3]),
        "--warmup-frames",
        str(warmup_frames),
        "--binary-input",
        "--utility-config",
        str(repo / "configs" / adapter.utility_config),
        "--governor-config",
        str(governor_path),
        "--include-leaf-details",
    ]


def _execute_policy_runs(
    args: argparse.Namespace,
    repo: Path,
    requested: list[str],
    frame_iterator: Any,
    selection: dict[str, Any],
) -> tuple[
    str,
    float,
    dict[str, list[dict[str, Any]]],
    list[int],
    list[list[str]],
]:
    """Run policies from one staged stream and always remove the staging file."""
    stream_directory = tempfile.TemporaryDirectory(prefix="veyra-benchmark-stream-")
    try:
        stream_path = Path(stream_directory.name) / "observations.stream"
        digest = binary_stream_file(frame_iterator, stream_path)
        if selection["frames"] == 0:
            raise ValueError("frame selection is empty")
        window_radius_m = selection["window_radius_m"] + 0.001
        runs_by_policy: dict[str, list[dict[str, Any]]] = {
            policy: [] for policy in requested
        }
        bridge_samples_ns: list[int] = []
        execution_order: list[list[str]] = []
        for repetition in range(args.repetitions):
            order = (
                requested[repetition % len(requested) :]
                + requested[: repetition % len(requested)]
            )
            execution_order.append(order)
            for policy in order:
                adapter = POLICY_ADAPTERS[policy]
                with stream_path.open("rb") as stream_input:
                    completed = subprocess.run(
                        _command(
                            args.binary,
                            adapter,
                            selection["distance_config"],
                            window_radius_m,
                            args.warmup_frames,
                            repo,
                            getattr(
                                args,
                                "governor_config",
                                "configs/resource_governor.yaml",
                            ),
                        ),
                        stdin=stream_input,
                        capture_output=True,
                        check=False,
                    )
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"{policy} repetition {repetition} failed: "
                        f"{completed.stderr.decode(errors='replace').strip()}"
                    )
                result = json.loads(completed.stdout)
                if (
                    result.get("schema_version") != SCHEMA_VERSION
                    or result.get("stream_digest") != digest
                    or result.get("policy") != adapter.cpp_policy
                ):
                    raise RuntimeError(
                        f"{policy} repetition {repetition} violated benchmark contract"
                    )
                result["detail_metric"] = _detail_metric(result["snapshot"])
                bridge_samples_ns.extend(
                    int(frame["stages_ns"]["protocol_parse_and_validate"])
                    for frame in result["frame_metrics"]
                )
                runs_by_policy[policy].append(result)
        return (
            digest,
            window_radius_m,
            runs_by_policy,
            bridge_samples_ns,
            execution_order,
        )
    finally:
        stream_directory.cleanup()


def _aggregate_policy_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    stages: dict[str, list[int]] = {}
    churn, splits, merges, peak_rss = [], [], [], []
    late_frames = dropped_frames = rejected = 0
    governor_interventions = governor_actions_applied = 0
    drops_available = True
    fps = []
    for run in runs:
        memory, stream, metrics = (
            run["metrics"]["memory"],
            run["metrics"]["stream"],
            run["metrics"],
        )
        if memory["peak_rss_bytes"] is not None:
            peak_rss.append(memory["peak_rss_bytes"])
        if metrics["fps"] is not None:
            fps.append(metrics["fps"])
        late_frames += stream["late_frames"]
        rejected += stream["rejected_out_of_window"]
        if stream["dropped_frames"] is None:
            drops_available = False
        else:
            dropped_frames += stream["dropped_frames"]
        for frame in run["frame_metrics"]:
            churn.append(frame["topology_churn"])
            splits.append(frame["splits"])
            merges.append(frame["merges"])
            governor_interventions += int(frame.get("governor_interventions", 0))
            governor_actions_applied += int(frame.get("governor_actions_applied", 0))
            for name, value in frame["stages_ns"].items():
                stages.setdefault(name, []).append(value)
    return {
        "stage_latency_ns": {
            name: nearest_rank_summary(values)
            for name, values in sorted(stages.items())
        },
        "topology_churn_per_frame": nearest_rank_summary(churn),
        "splits_per_frame": nearest_rank_summary(splits),
        "merges_per_frame": nearest_rank_summary(merges),
        "late_frames": late_frames,
        "rejected_out_of_window": rejected,
        "dropped_frames": dropped_frames if drops_available else None,
        "peak_rss_bytes": max(peak_rss) if peak_rss else None,
        "measured_frame_count": sum(run["metrics"]["frame_count"] for run in runs),
        "fps": nearest_rank_summary(fps),
        "final_leaves_per_level": runs[-1]["snapshot"]["levels"],
        "quality": [run["quality"] for run in runs],
        "governor": {
            "interventions": governor_interventions,
            "actions_applied": governor_actions_applied,
            "final_status": runs[-1].get("governor"),
        },
    }


def _relative_delta(current: float | None, baseline: float | None):
    if current is None or baseline in (None, 0):
        return None
    return (float(current) - float(baseline)) / float(baseline)


def _absolute_delta(current: float | None, baseline: float | None):
    if current is None or baseline is None:
        return None
    return float(current) - float(baseline)


def utility_ablation_report(results: dict[str, Any]) -> dict[str, Any]:
    """Build a stable, self-describing comparison without inventing a score."""
    experiment_requested = any(
        name in results for name in UTILITY_ABLATION_POLICY_NAMES[:-1]
    )
    present = (
        [name for name in UTILITY_ABLATION_POLICY_NAMES if name in results]
        if experiment_requested
        else []
    )
    missing = [name for name in UTILITY_ABLATION_POLICY_NAMES if name not in results]
    members: dict[str, Any] = {}
    baseline = results.get("ablation_distance")

    def measured(policy: dict[str, Any]) -> dict[str, Any]:
        aggregate = policy["aggregate"]
        final_run = policy["runs"][-1]
        retention = final_run["quality"].get("field_retention", {})

        def retention_fraction(name: str) -> float | None:
            value = retention.get(name, {})
            fraction = value.get("retention_fraction")
            return None if fraction is None else float(fraction)

        return {
            "elevation_rmse_m": final_run["quality"]["elevation_vs_fine_reference"][
                "rmse_m"
            ],
            "weighted_mean_level": final_run["detail_metric"]["weighted_mean_level"],
            "map_latency_p95_ns": aggregate["stage_latency_ns"]["map_update"]["p95"],
            "peak_rss_bytes": aggregate["peak_rss_bytes"],
            "active_leaves": sum(aggregate["final_leaves_per_level"].values()),
            "semantic_retention_fraction": retention_fraction("semantic"),
            "terrain_hazard_retention_fraction": retention_fraction("terrain_hazard"),
        }

    baseline_metrics = measured(baseline) if baseline else None
    for name in present:
        metrics = measured(results[name])
        members[name] = {
            "signals": list(POLICY_ADAPTERS[name].signals),
            "measurements": metrics,
            "delta_vs_distance": {
                "elevation_rmse_m": None
                if baseline_metrics is None
                else _absolute_delta(
                    metrics["elevation_rmse_m"],
                    baseline_metrics["elevation_rmse_m"],
                ),
                "weighted_mean_level": None
                if baseline_metrics is None
                else _absolute_delta(
                    metrics["weighted_mean_level"],
                    baseline_metrics["weighted_mean_level"],
                ),
                "map_latency_fraction": None
                if baseline_metrics is None
                else _relative_delta(
                    metrics["map_latency_p95_ns"],
                    baseline_metrics["map_latency_p95_ns"],
                ),
                "peak_rss_fraction": None
                if baseline_metrics is None
                else _relative_delta(
                    metrics["peak_rss_bytes"], baseline_metrics["peak_rss_bytes"]
                ),
                "active_leaves_fraction": None
                if baseline_metrics is None
                else _relative_delta(
                    metrics["active_leaves"], baseline_metrics["active_leaves"]
                ),
                "semantic_retention_delta": None
                if baseline_metrics is None
                else _absolute_delta(
                    metrics["semantic_retention_fraction"],
                    baseline_metrics["semantic_retention_fraction"],
                ),
                "terrain_hazard_retention_delta": None
                if baseline_metrics is None
                else _absolute_delta(
                    metrics["terrain_hazard_retention_fraction"],
                    baseline_metrics["terrain_hazard_retention_fraction"],
                ),
            },
        }

    assessment = "unavailable"
    full = members.get("utility_lod", {}).get("measurements")
    if (
        baseline_metrics
        and full
        and None
        not in (
            baseline_metrics["elevation_rmse_m"],
            full["elevation_rmse_m"],
        )
    ):
        quality_improved = (
            full["elevation_rmse_m"] < baseline_metrics["elevation_rmse_m"]
        )
        no_resource_increase = all(
            full[key] <= baseline_metrics[key]
            for key in ("map_latency_p95_ns", "peak_rss_bytes", "active_leaves")
            if full[key] is not None and baseline_metrics[key] is not None
        )
        if quality_improved and no_resource_increase:
            assessment = "quality_improved_without_measured_resource_increase"
        elif quality_improved:
            assessment = "quality_improved_with_measured_resource_increase"
        else:
            assessment = "no_measured_quality_improvement"
    return {
        "status": "complete" if not missing else "partial" if present else "not_run",
        "baseline": "ablation_distance",
        "required_policies": list(UTILITY_ABLATION_POLICY_NAMES),
        "missing_policies": missing,
        "members": members,
        "full_vs_distance_assessment": assessment,
        "interpretation": {
            "elevation_rmse_m": "negative delta is better",
            "weighted_mean_level": "negative delta means finer retained detail",
            "resource_fractions": "negative delta uses less measured resource",
            "assessment": "descriptive result on this selection; no cross-hardware or general quality claim",
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    if (
        args.start < 0
        or args.count <= 0
        or args.warmup_frames < 0
        or args.repetitions <= 0
    ):
        raise ValueError(
            "start/warmup must be non-negative and count/repetitions positive"
        )
    if args.warmup_frames >= args.count:
        raise ValueError("warmup_frames must be smaller than count")
    requested = [item.strip() for item in args.policies.split(",") if item.strip()]
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("policies must be a non-empty, unique comma-separated list")
    unknown = set(requested) - POLICY_ADAPTERS.keys()
    if unknown:
        raise ValueError(f"unknown policies: {', '.join(sorted(unknown))}")
    unavailable = [name for name in requested if not POLICY_ADAPTERS[name].available]
    if unavailable:
        raise ValueError(f"policy adapter unavailable: {', '.join(unavailable)}")
    hardware_config = yaml.safe_load(
        (repo / "configs/hardware_profiles.yaml").read_text()
    )
    validate_hardware_profile(hardware_config, args.hardware_profile)
    perception_config_path = (
        repo / args.perception_config
        if not Path(args.perception_config).is_absolute()
        else Path(args.perception_config)
    )
    retained_frames: list[Any] | None = None
    if getattr(args, "retain_frames", False):
        # Materialized path (opt-in): keep the source selection in memory so
        # field and task-class retention are measured on the identical stream
        # every policy consumed. The default streaming path is unchanged.
        perception_records: list[dict[str, Any]] = []
        reference_frames: list[Any] = []
        (
            retained_frames,
            distance_config,
            _entry,
            perception_ns,
            materialized_radius_m,
        ) = load_selection(
            repo,
            args.dataset,
            args.sequence,
            args.start,
            args.count,
            run_perception=not args.skip_perception,
            perception_config=perception_config_path,
            dataset_root=getattr(args, "dataset_root", None),
            perception_records=perception_records,
            reference_frames=reference_frames,
        )
        semantic_quality = (
            SemanticQualityAccumulator() if not args.skip_perception else None
        )
        if semantic_quality is not None:
            for source_frame, predicted_frame in zip(
                reference_frames, retained_frames, strict=True
            ):
                semantic_quality.update(source_frame, predicted_frame)
        min_xyz = np.full(3, np.inf, dtype=np.float64)
        max_xyz = np.full(3, -np.inf, dtype=np.float64)
        point_count = 0
        for output_frame in retained_frames:
            points = np.asarray(output_frame.points[:, :3], dtype=np.float64)
            if points.size:
                min_xyz = np.minimum(min_xyz, points.min(axis=0))
                max_xyz = np.maximum(max_xyz, points.max(axis=0))
                point_count += len(points)
        selection = {
            "distance_config": distance_config,
            "frames": len(retained_frames),
            "point_count": point_count,
            "min_xyz": min_xyz,
            "max_xyz": max_xyz,
            "window_radius_m": materialized_radius_m,
            "perception_ns": perception_ns,
            "perception_records": perception_records,
            "semantic_quality": semantic_quality,
        }
        frame_iterator = iter(retained_frames)
    else:
        frame_iterator, selection = stream_selection(
            repo,
            args.dataset,
            args.sequence,
            args.start,
            args.count,
            run_perception=not args.skip_perception,
            dataset_root=getattr(args, "dataset_root", None),
            perception_config=perception_config_path,
        )
    digest, window_radius_m, runs_by_policy, bridge_samples_ns, execution_order = (
        _execute_policy_runs(args, repo, requested, frame_iterator, selection)
    )
    three_d_reference = analytical_3d_reference_bounds(
        selection["min_xyz"], selection["max_xyz"]
    )
    fine_reference = _finalize_policy_runs(
        runs_by_policy, selection, frames=retained_frames
    )
    results: dict[str, Any] = {}
    for policy in requested:
        adapter, runs = POLICY_ADAPTERS[policy], runs_by_policy[policy]
        results[policy] = {
            "adapter": {
                "cpp_policy": adapter.cpp_policy,
                "available": adapter.available,
                "integration_note": adapter.integration_note,
                "utility_config": adapter.utility_config,
                "suite": adapter.suite,
                "signals": list(adapter.signals),
            },
            "runs": runs,
            "aggregate": _aggregate_policy_runs(runs),
        }
    governor_config_arg = getattr(
        args, "governor_config", "configs/resource_governor.yaml"
    )
    governor_config_path = (
        Path(governor_config_arg)
        if Path(governor_config_arg).is_absolute()
        else repo / governor_config_arg
    )
    if not governor_config_path.is_file():
        raise ValueError(f"governor config does not exist: {governor_config_path}")
    config_paths = [
        repo / args.perception_config,
        repo / "configs/datasets.yaml",
        repo / "configs/distance_lod.yaml",
        *{
            repo / "configs" / POLICY_ADAPTERS[policy].utility_config
            for policy in requested
        },
        governor_config_path,
        repo / "configs/benchmark.yaml",
        repo / "configs/hardware_profiles.yaml",
    ]
    if "utility_lod" in results and "distance_lod" in results:
        utility_detail = results["utility_lod"]["runs"][-1]["detail_metric"]
        distance_detail = results["distance_lod"]["runs"][-1]["detail_metric"]
        utility_level = utility_detail["weighted_mean_level"]
        distance_level = distance_detail["weighted_mean_level"]
        detail_delta = (
            None
            if utility_level is None or distance_level is None
            else utility_level - distance_level
        )
    else:
        detail_delta = None
    compiler = None
    try:
        compiler = subprocess.run(
            [os.environ.get("CXX", "c++"), "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        pass
    config_digests = {path.name: _sha256_file(path) for path in config_paths}
    aggregate_config_digest = hashlib.sha256(
        json.dumps(config_digests, sort_keys=True).encode("utf-8")
    ).hexdigest()
    model_path = repo / "configs" / "perception-salsanext.yaml"
    model_config = (
        yaml.safe_load(model_path.read_text()) if model_path.is_file() else {}
    )
    model_value = (
        model_config.get("semantic", {}).get("model_path")
        if isinstance(model_config, dict)
        else None
    )
    checkpoint = repo / model_value if isinstance(model_value, str) else None
    perception_report = (
        summarize_perception(
            args.dataset,
            args.sequence,
            selection["perception_records"],
            bridge_samples_ns=bridge_samples_ns,
        )
        if selection["perception_records"]
        else None
    )
    semantic_quality = (
        selection["semantic_quality"].report()
        if args.dataset in {"semanticposs", "rellis3d", "semantickitti"}
        and not args.skip_perception
        else {
            "status": "unavailable",
            "reason": "paired adapter labels are unavailable for this selection",
        }
    )
    measured_frames_per_run = max(0, selection["frames"] - args.warmup_frames)
    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": {
            "protocol_version": PROTOCOL_VERSION,
            "selection_digest": digest,
            "config_sha256": config_digests,
            "config_digest": aggregate_config_digest,
            "dataset_sha256": args.dataset_sha256,
            "model_checkpoint_sha256": _sha256_file(checkpoint)
            if checkpoint and checkpoint.is_file()
            else None,
            "git_sha": _git_sha(repo),
            "pull_request_number": _pull_request_number(),
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "workflow_event": os.environ.get("GITHUB_EVENT_NAME"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "frame_range": {
                "sequence": args.sequence,
                "start": args.start,
                "end_exclusive": args.start + args.count,
                "count": selection["frames"],
            },
            "compiler": compiler,
            "build_type": args.build_type,
            "perception_executed": not args.skip_perception,
            "hardware": hardware_metadata(args.hardware_profile),
            "repetitions": args.repetitions,
            "warmup_frames": args.warmup_frames,
            "sample_adequacy": sample_adequacy_report(
                measured_frames_per_run, args.repetitions
            ),
            "policy_execution_order": execution_order,
            "map_window_radius_m": window_radius_m,
            "measurement_scope": {
                "perception": "Python PerceptionPipeline processing, shared once before all policy runs"
                if not args.skip_perception
                else "not run; source dataset frames were sent directly to the map",
                "map_window_follow": "C++ public map window-center update from the transmitted world-frame pose; excludes serialization",
                "map_update": "C++ map update calls only; excludes protocol parsing, snapshotting, and JSON/CSV serialization",
                "protocol_parse_and_validate": "C++ token parsing and Observation construction; excludes stdin I/O",
                "snapshot_and_topology": "C++ map snapshot plus topology extraction; excludes JSON/CSV serialization",
            },
        },
        "dataset": args.dataset,
        "sequence": args.sequence,
        "start": args.start,
        "input_frames": selection["frames"],
        "measured_frames_per_run": measured_frames_per_run,
        "shared_stage_latency_ns": {
            "perception": nearest_rank_summary(selection["perception_ns"])
            if selection["perception_ns"]
            else None
        },
        "perception": perception_report,
        "semantic_quality": semantic_quality,
        "reference_baselines": {
            "uniform_5cm_3d": three_d_reference,
            "uniform_5cm_2d": {
                "status": "executed_as_fine_reference",
                "reference_bins": len(fine_reference["mean_z_by_cell"]),
                "representation": "sparse_2d_elevation_bins",
                "voxel_size_m": 0.05,
            },
        },
        "utility_vs_distance_detail": {
            "weighted_mean_level_delta": detail_delta,
            "interpretation": "negative means UtilityLOD retained finer leaves on identical input; detail alone is not quality gain",
        },
        "utility_ablation": utility_ablation_report(results),
        "policies": results,
    }


def _write_csv(path: Path, result: dict[str, Any]) -> None:
    fields = (
        "schema_version",
        "dataset",
        "sequence",
        "policy",
        "selection_digest",
        "repetitions",
        "measured_frame_count",
        "map_update_mean_ns",
        "map_update_p50_ns",
        "map_update_p95_ns",
        "map_update_p99_ns",
        "map_update_max_ns",
        "topology_churn_p95",
        "splits_p95",
        "merges_p95",
        "fps_p50",
        "fps_p95",
        "fps_p99",
        "logical_map_bytes",
        "allocated_map_bytes",
        "late_frames",
        "dropped_frames",
        "rejected_out_of_window",
        "peak_rss_bytes",
        "elevation_vs_fine_rmse_m",
        "elevation_reference_coverage",
        "governor_interventions",
        "governor_actions_applied",
        "point_conservation",
        "duplicate_ownership",
        "seam_boundary_status",
        "seam_gap_bins",
        "seam_overlap_bins",
        "semantic_retention_fraction",
        "terrain_hazard_retention_fraction",
        "semantic_miou",
        "semantic_miou_0_10m",
        "semantic_miou_10_30m",
        "semantic_miou_30_60m",
        "semantic_miou_60_100m",
        "analytical_3d_dense_voxels",
        "analytical_3d_estimated_bytes",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for policy, report in result["policies"].items():
            aggregate, map_update = (
                report["aggregate"],
                report["aggregate"]["stage_latency_ns"]["map_update"],
            )
            writer.writerow(
                {
                    "schema_version": result["schema_version"],
                    "dataset": result["dataset"],
                    "sequence": result["sequence"],
                    "policy": policy,
                    "selection_digest": result["provenance"]["selection_digest"],
                    "repetitions": result["provenance"]["repetitions"],
                    "measured_frame_count": aggregate["measured_frame_count"],
                    "map_update_mean_ns": map_update["mean"],
                    "map_update_p50_ns": map_update["p50"],
                    "map_update_p95_ns": map_update["p95"],
                    "map_update_p99_ns": map_update["p99"],
                    "map_update_max_ns": map_update["max"],
                    "topology_churn_p95": aggregate["topology_churn_per_frame"]["p95"],
                    "splits_p95": aggregate["splits_per_frame"]["p95"],
                    "merges_p95": aggregate["merges_per_frame"]["p95"],
                    "fps_p50": aggregate["fps"]["p50"],
                    "fps_p95": aggregate["fps"]["p95"],
                    "fps_p99": aggregate["fps"]["p99"],
                    "logical_map_bytes": report["runs"][-1]["metrics"]["memory"][
                        "logical_map_bytes"
                    ],
                    "allocated_map_bytes": report["runs"][-1]["metrics"]["memory"][
                        "allocated_map_bytes"
                    ],
                    "late_frames": aggregate["late_frames"],
                    "dropped_frames": aggregate["dropped_frames"],
                    "rejected_out_of_window": aggregate["rejected_out_of_window"],
                    "peak_rss_bytes": aggregate["peak_rss_bytes"],
                    "elevation_vs_fine_rmse_m": report["runs"][-1]["quality"][
                        "elevation_vs_fine_reference"
                    ]["rmse_m"],
                    "elevation_reference_coverage": report["runs"][-1]["quality"][
                        "elevation_vs_fine_reference"
                    ]["coverage"],
                    "governor_interventions": aggregate["governor"]["interventions"],
                    "governor_actions_applied": aggregate["governor"][
                        "actions_applied"
                    ],
                    "point_conservation": all(
                        item["point_conservation"]["holds"]
                        for item in aggregate["quality"]
                    ),
                    "duplicate_ownership": all(
                        item["duplicate_ownership"]["holds"]
                        for item in aggregate["quality"]
                    ),
                    "seam_boundary_status": aggregate["quality"][-1][
                        "mixed_resolution_topology"
                    ]["status"],
                    "seam_gap_bins": aggregate["quality"][-1][
                        "mixed_resolution_topology"
                    ]["observed_bins"]["gap"],
                    "seam_overlap_bins": aggregate["quality"][-1][
                        "mixed_resolution_topology"
                    ]["observed_bins"]["overlap"],
                    "semantic_retention_fraction": aggregate["quality"][-1][
                        "field_retention"
                    ]["semantic"].get("retention_fraction"),
                    "terrain_hazard_retention_fraction": aggregate["quality"][-1][
                        "field_retention"
                    ]["terrain_hazard"].get("retention_fraction"),
                    "semantic_miou": result["semantic_quality"]
                    .get("overall", {})
                    .get("miou"),
                    **{
                        f"semantic_miou_{int(item['min_m'])}_{int(item['max_m'])}m": item.get(
                            "miou"
                        )
                        for item in result["semantic_quality"].get("range_bins", [])
                    },
                    "analytical_3d_dense_voxels": result["reference_baselines"][
                        "uniform_5cm_3d"
                    ]["dense_voxel_count"],
                    "analytical_3d_estimated_bytes": result["reference_baselines"][
                        "uniform_5cm_3d"
                    ]["estimated_dense_bytes"],
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--binary", required=True)
    parser.add_argument(
        "--dataset",
        choices=("semanticposs", "rellis3d", "semantickitti", "generic"),
        required=True,
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="Explicit local dataset root; preserves repository config and provenance",
    )
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--warmup-frames", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--policies", default="uniform5,uniform40,distance_lod,utility_lod"
    )
    parser.add_argument("--hardware-profile", default="auto")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--skip-perception", action="store_true")
    parser.add_argument(
        "--retain-frames",
        action="store_true",
        help="Retain the source selection in memory to measure field and "
        "task-class retention on the identical stream every policy consumes; "
        "default streams frames with bounded memory and reports retention "
        "as unavailable",
    )
    parser.add_argument("--dataset-sha256")
    parser.add_argument("--build-type", default="Release")
    parser.add_argument("--perception-config", default="configs/perception.yaml")
    parser.add_argument(
        "--governor-config",
        default="configs/resource_governor.yaml",
        help="Governor budget file passed to the C++ benchmark binary "
        "(relative paths resolve against --repo; default keeps the "
        "deployed budget)",
    )
    parser.add_argument(
        "--perception-output",
        type=Path,
        help="Write the shared perception report from this run to JSON",
    )
    args = parser.parse_args()
    try:
        result = run(args)
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        yaml.YAMLError,
        json.JSONDecodeError,
    ) as error:
        print(f"veyra benchmark: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    if args.csv_output:
        _write_csv(args.csv_output, result)
    if args.perception_output:
        if result["perception"] is None:
            raise ValueError("perception output requested for a map-only run")
        args.perception_output.parent.mkdir(parents=True, exist_ok=True)
        args.perception_output.write_text(
            json.dumps(
                {
                    **result["perception"],
                    "reproducibility": result["provenance"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    if not args.output:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
