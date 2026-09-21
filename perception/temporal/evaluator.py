"""Object-level motion-GT evaluator for the temporal tracker.

Observed tracker evidence (``scripts/validate_temporal.py``) proves the
tracker runs, but cannot say whether it is *right*: it has no notion of
which points truly move. This module closes that gap where the dataset
allows it:

* **KITTI (SemanticKITTI seq08):** moving-object masks come from the
  official motion labels (raw IDs 252-259: moving car/bicycle/person/
  rider/...). Objects are point groups sharing one dataset
  ``instance_id``; GT velocity is the world-frame centroid displacement
  between consecutive frames divided by the dataset timestamp delta
  (ego-motion is already compensated — points are in the adapter world
  frame built from official poses). Tracker tracks associate to GT
  objects by nearest-centroid gating within the tracker's own
  association gate, requiring the same mapped semantic class.
* **SemanticPOSS:** vehicle/person masks exist but the dataset publishes
  no timestamps, so no velocity can be derived and the tracker cannot
  run without inventing time → explicit ``UNKNOWN``.
* **RELLIS-3D:** no dataset poses/timestamps upstream, so points are not
  in a world frame and no ego-compensated displacement exists →
  explicit ``UNKNOWN``.

Honesty rules (fail closed, never invent):

* GT velocity is scored only when both endpoint groups are large enough
  (``min_object_points``), share the same majority raw class, and the
  implied GT speed fits inside the association gate
  (``association_distance_m / dt``); anything faster is indistinguishable
  from fragmentation or a fresh track, so it is reported as
  ``gt_unreliable_excluded`` rather than scored.
* Instance IDs are dataset groupings, not perfect identities: mixed-class
  instances are scored under their majority raw class and flagged.
* Only freshly observed tracks (``missed_frames == 0``) may associate;
  ghosts never score.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from datasets.common.taxonomy import SEMANTICKITTI_LABELS, map_dataset_labels

#: SemanticKITTI raw IDs whose labels assert motion (moving-car 252,
#: moving-bicyclist 253, moving-person 254, moving-motorcyclist 255,
#: moving-on-rails 256, moving-bus 257, moving-truck 258,
#: moving-other-vehicle 259).
KITTI_MOVING_RAW_IDS = frozenset({252, 253, 254, 255, 256, 257, 258, 259})

#: Static counterparts used as no-motion controls (car 10, person 30,
#: bicyclist 31, motorcyclist 32).
KITTI_STATIC_CONTROL_RAW_IDS = (10, 30, 31, 32)


class MotionEvaluationError(RuntimeError):
    """The supplied frames cannot be evaluated at all (empty input)."""


@dataclass(frozen=True)
class _GTObject:
    instance_id: int
    raw_majority: int
    veyra_class: int
    centroid_xy: np.ndarray
    count: int
    mixed: bool


def unknown_report(
    dataset: str, sequence: str, *, reason: str, frames_seen: int = 0
) -> dict:
    """Build the explicit UNKNOWN report used where GT is unknowable."""
    if not reason or not reason.strip():
        raise ValueError("an UNKNOWN report must carry a non-empty reason")
    return {
        "status": "UNKNOWN",
        "dataset": str(dataset),
        "sequence": str(sequence),
        "frames_seen": int(frames_seen),
        "reason": reason,
        "association_precision": None,
        "association_recall": None,
        "velocity_error_mps": None,
    }


def _provenance(frame) -> tuple[str, str, str]:
    provenance = getattr(frame, "provenance", None)
    if provenance is None:
        # Synthetic/test-only frames carry no provenance contract; they are
        # constructed directly in the world frame with dataset timestamps.
        return ("world", "dataset", "dataset")
    return (
        str(getattr(provenance, "coordinate_frame", "world")),
        str(getattr(provenance, "timestamp_source", "dataset")),
        str(getattr(provenance, "pose_source", "dataset")),
    )


def _gt_objects(
    raw: np.ndarray,
    instance: np.ndarray,
    points_xy: np.ndarray,
    *,
    min_object_points: int,
) -> tuple[list[_GTObject], int]:
    """Group moving-label points by dataset instance id.

    Returns (scored objects, fragment count). Groups below
    ``min_object_points`` are fragments: reported but never scored, since
    their centroids are resampling noise, not object motion.
    """
    objects: list[_GTObject] = []
    fragments = 0
    moving = np.isin(raw, list(KITTI_MOVING_RAW_IDS))
    frame_ids = np.unique(instance[moving])
    raw_of_instance: dict[int, set[int]] = {}
    for instance_id in frame_ids:
        raw_of_instance[int(instance_id)] = set(
            np.unique(raw[moving & (instance == instance_id)]).tolist()
        )
    for instance_id in sorted(raw_of_instance):
        for raw_id in sorted(raw_of_instance[instance_id]):
            members = np.flatnonzero(
                moving & (instance == instance_id) & (raw == raw_id)
            )
            if members.size < min_object_points:
                fragments += 1
                continue
            veyra = int(SEMANTICKITTI_LABELS.get(int(raw_id), 0))
            objects.append(
                _GTObject(
                    instance_id=int(instance_id),
                    raw_majority=int(raw_id),
                    veyra_class=veyra,
                    centroid_xy=points_xy[members].mean(axis=0),
                    count=int(members.size),
                    mixed=bool(len(raw_of_instance[instance_id]) > 1),
                )
            )
    return objects, fragments


def evaluate_motion(
    frames,
    tracker,
    *,
    min_object_points: int = 200,
) -> dict:
    """Run ``tracker`` over world-frame frames and score against motion GT.

    ``frames`` are dataset adapter frames (or duck-typed equivalents with
    ``points``, ``semantic_class``, ``raw_semantic_class``,
    ``instance_id``, ``timestamp``, ``pose.matrix``). The tracker is driven
    frame by frame; per-frame GT objects, associations, and velocity
    errors are aggregated per mapped (Veyra) class. Where GT is
    unknowable the result has ``status == "UNKNOWN"`` with a reason —
    never a score.
    """
    frames = list(frames)
    if not frames:
        raise MotionEvaluationError("evaluate_motion requires at least one frame")
    if min_object_points < 1:
        raise ValueError("min_object_points must be positive")

    dataset = str(getattr(frames[0], "dataset", ""))
    sequence = str(getattr(frames[0], "sequence", ""))
    gate = float(tracker.association_distance_m)

    for frame in frames:
        coordinate_frame, _, _ = _provenance(frame)
        if frame.timestamp is None or not np.isfinite(float(frame.timestamp)):
            return unknown_report(
                dataset or "unknown",
                sequence,
                reason=(
                    f"frame {getattr(frame, 'frame_id', '?')} has no finite "
                    "dataset timestamp; deriving velocity would invent time"
                ),
                frames_seen=len(frames),
            )
        if coordinate_frame != "world":
            return unknown_report(
                dataset or "unknown",
                sequence,
                reason=(
                    f"frame {getattr(frame, 'frame_id', '?')} is in "
                    f"{coordinate_frame!r}, not 'world': no dataset pose, so no "
                    "ego-compensated displacement exists"
                ),
                frames_seen=len(frames),
            )
        if (
            getattr(frame, "raw_semantic_class", None) is None
            or getattr(frame, "instance_id", None) is None
        ):
            return unknown_report(
                dataset or "unknown",
                sequence,
                reason=(
                    f"frame {getattr(frame, 'frame_id', '?')} carries no "
                    "raw/instance labels; moving-object masks are unknowable"
                ),
                frames_seen=len(frames),
            )

    timestamps = [float(frame.timestamp) for frame in frames]
    if any(b <= a for a, b in itertools.pairwise(timestamps)):
        raise MotionEvaluationError("dataset timestamps must strictly increase")

    per_class: dict[str, dict] = {}
    per_raw_recall: dict[str, dict] = {}
    static_controls: dict[str, dict] = {}
    frame_ids: list[str] = []
    max_measurable: list[float] = []
    gt_points_total = 0
    gt_points_moving_state = 0
    gt_points_nonstatic_state = 0
    moving_points_total = 0
    moving_points_gt = 0
    fragments_total = 0
    unreliable_total = 0
    previous_objects: dict[tuple[int, int], _GTObject] = {}
    previous_timestamp: float | None = None

    def class_bucket(veyra: int) -> dict:
        key = str(int(veyra))
        return per_class.setdefault(
            key,
            {
                "gt_objects": 0,
                "matched": 0,
                "velocity_errors": [],
                "unconfirmed_matches": 0,
                "mixed_instances": 0,
            },
        )

    for frame in frames:
        frame_ids.append(str(frame.frame_id))
        points = np.asarray(frame.points, dtype=np.float32)
        labels = np.asarray(frame.semantic_class, dtype=np.int32).reshape(-1)
        raw = np.asarray(frame.raw_semantic_class, dtype=np.int32).reshape(-1)
        instance = np.asarray(frame.instance_id, dtype=np.int32).reshape(-1)
        if raw.size != points.shape[0] or instance.size != points.shape[0]:
            raise MotionEvaluationError(
                f"frame {getattr(frame, 'frame_id', '?')}: raw/instance labels "
                "must align with points"
            )
        timestamp = float(frame.timestamp)
        evidence = tracker.update(
            points,
            labels,
            np.asarray(frame.pose.matrix, dtype=np.float64),
            timestamp=timestamp,
        )
        state = np.asarray(evidence.state)

        gt_mask = np.isin(raw, list(KITTI_MOVING_RAW_IDS))
        gt_points_total += int(gt_mask.sum())
        gt_points_moving_state += int(np.count_nonzero(gt_mask & (state == "moving")))
        gt_points_nonstatic_state += int(
            np.count_nonzero(
                gt_mask & ((state == "moving") | (state == "possibly_moving"))
            )
        )
        is_moving = state == "moving"
        moving_points_total += int(np.count_nonzero(is_moving))
        moving_points_gt += int(np.count_nonzero(is_moving & gt_mask))
        gt_veyra = map_dataset_labels(raw, SEMANTICKITTI_LABELS)
        for veyra in (
            sorted(
                set(np.unique(labels).tolist())
                | set(np.unique(gt_veyra[gt_mask]).tolist())
            )
            if gt_mask.any() or is_moving.any()
            else ()
        ):
            bucket = class_bucket(int(veyra))
            cell_gt = gt_mask & (gt_veyra == veyra)
            cell_moving = is_moving & (labels == veyra)
            bucket["point_gt_points"] = bucket.get("point_gt_points", 0) + int(
                cell_gt.sum()
            )
            bucket["point_recalled"] = bucket.get("point_recalled", 0) + int(
                np.count_nonzero(cell_gt & is_moving)
            )
            bucket["point_moving"] = bucket.get("point_moving", 0) + int(
                cell_moving.sum()
            )
            bucket["point_moving_gt"] = bucket.get("point_moving_gt", 0) + int(
                np.count_nonzero(cell_moving & gt_mask)
            )
        for raw_id in sorted(np.unique(raw[gt_mask]).tolist()) if gt_mask.any() else ():
            cell = per_raw_recall.setdefault(
                str(int(raw_id)),
                {"gt_points": 0, "moving_state": 0, "non_static_state": 0},
            )
            mask = raw == raw_id
            cell["gt_points"] += int(mask.sum())
            cell["moving_state"] += int(np.count_nonzero(mask & (state == "moving")))
            cell["non_static_state"] += int(
                np.count_nonzero(
                    mask & ((state == "moving") | (state == "possibly_moving"))
                )
            )
        for raw_id in KITTI_STATIC_CONTROL_RAW_IDS:
            mask = raw == raw_id
            if not mask.any():
                continue
            cell = static_controls.setdefault(
                str(int(raw_id)), {"points": 0, "moving_state": 0}
            )
            cell["points"] += int(mask.sum())
            cell["moving_state"] += int(np.count_nonzero(mask & (state == "moving")))

        objects, fragments = _gt_objects(
            raw,
            instance,
            points[:, :2].astype(np.float64),
            min_object_points=min_object_points,
        )
        fragments_total += fragments

        # Fresh tracks only: ghosts must never score.
        fresh = [
            snapshot
            for snapshot in tracker.active_tracks()
            if snapshot.missed_frames == 0
        ]
        claimed: set[int] = set()
        current: dict[tuple[int, int], _GTObject] = {}
        for obj in sorted(
            objects, key=lambda item: (item.instance_id, item.raw_majority)
        ):
            current[(obj.instance_id, obj.raw_majority)] = obj
            bucket = class_bucket(obj.veyra_class)
            bucket["gt_objects"] += 1
            if obj.mixed:
                bucket["mixed_instances"] += 1
            best = None
            best_distance = gate
            for snapshot in fresh:
                if snapshot.track_id in claimed:
                    continue
                if snapshot.semantic_class != obj.veyra_class:
                    continue
                distance = float(
                    np.linalg.norm(
                        np.asarray(snapshot.centroid_xy, dtype=np.float64)
                        - obj.centroid_xy
                    )
                )
                if distance <= best_distance + 1e-9 and (
                    best is None
                    or distance < best_distance - 1e-9
                    or snapshot.track_id < best.track_id
                ):
                    best = snapshot
                    best_distance = distance
            if best is None:
                continue
            claimed.add(best.track_id)
            bucket["matched"] += 1
            # Velocity pairs need a GT displacement and a live estimate.
            # First-frame matches have no displacement yet: neither scored
            # nor penalized. A missing predecessor on later frames means the
            # (instance, raw) group appeared, vanished, or fell below the
            # point floor — fragmentation, not measurable motion.
            if previous_timestamp is None:
                continue
            previous = previous_objects.get((obj.instance_id, obj.raw_majority))
            if previous is None:
                unreliable_total += 1
                continue
            dt = timestamp - previous_timestamp
            if dt <= 0:
                continue
            ceiling = gate / dt
            max_measurable.append(ceiling)
            gt_speed = float(
                np.linalg.norm(obj.centroid_xy - previous.centroid_xy) / dt
            )
            if gt_speed > ceiling:
                # Beyond the gate the tracker cannot hold the association;
                # a mismatch here measures fragmentation, not velocity.
                unreliable_total += 1
                continue
            if not best.motion_valid:
                continue
            if not best.confirmed:
                bucket["unconfirmed_matches"] += 1
                continue
            bucket["velocity_errors"].append(abs(float(best.speed_mps) - gt_speed))
        previous_objects = current
        previous_timestamp = timestamp

    for bucket in per_class.values():
        errors = np.asarray(bucket.pop("velocity_errors"), dtype=np.float64)
        bucket["velocity_error_mps"] = (
            {
                "median": float(np.median(errors)),
                "p95": float(np.percentile(errors, 95)),
                "max": float(errors.max()),
                "n": int(errors.size),
            }
            if errors.size
            else None
        )
        bucket["association_recall"] = (
            bucket["matched"] / bucket["gt_objects"] if bucket["gt_objects"] else None
        )
        gt_pts = bucket.pop("point_gt_points", 0)
        recalled = bucket.pop("point_recalled", 0)
        moving = bucket.pop("point_moving", 0)
        moving_gt = bucket.pop("point_moving_gt", 0)
        bucket["point_recall"] = recalled / gt_pts if gt_pts else None
        bucket["point_precision"] = moving_gt / moving if moving else None
    for cell in per_raw_recall.values():
        cell["recall"] = (
            cell["moving_state"] / cell["gt_points"] if cell["gt_points"] else None
        )
        cell["non_static_recall"] = (
            cell["non_static_state"] / cell["gt_points"] if cell["gt_points"] else None
        )
    for cell in static_controls.values():
        cell["moving_share"] = (
            cell["moving_state"] / cell["points"] if cell["points"] else None
        )

    return {
        "status": "SCORED",
        "dataset": dataset,
        "sequence": sequence,
        "frames": frame_ids,
        "gate": {
            "association_distance_m": gate,
            "meaning": (
                "max measurable GT speed is gate/dt per pair "
                f"(~{gate / 0.104:.1f} m/s at the 0.104 s KITTI rate); "
                "faster GT displacements are excluded as unreliable, not scored"
            ),
            "max_measurable_mps_observed": (
                {
                    "min": float(min(max_measurable)),
                    "max": float(max(max_measurable)),
                }
                if max_measurable
                else None
            ),
        },
        "per_class": per_class,
        "point_level": {
            "gt_moving_points": gt_points_total,
            "moving_state_recall": (
                gt_points_moving_state / gt_points_total if gt_points_total else None
            ),
            "non_static_recall": (
                gt_points_nonstatic_state / gt_points_total if gt_points_total else None
            ),
            "moving_state_precision": (
                moving_points_gt / moving_points_total if moving_points_total else None
            ),
            "per_raw_recall": per_raw_recall,
        },
        "static_controls": static_controls,
        "unscored_fragments_below_min_points": fragments_total,
        "gt_unreliable_excluded": unreliable_total,
        "min_object_points": min_object_points,
    }


__all__ = [
    "KITTI_MOVING_RAW_IDS",
    "KITTI_STATIC_CONTROL_RAW_IDS",
    "MotionEvaluationError",
    "evaluate_motion",
    "unknown_report",
]
