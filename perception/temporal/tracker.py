"""Ego-motion-compensated, geometry-first temporal association.

The tracker accepts points already expressed in the stable world frame and the
source pose for each frame. Semantic classes are used only to avoid associating
incompatible clusters; they never imply motion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MotionEvidence:
    """Per-point temporal evidence aligned with one input frame."""

    motion_probability: np.ndarray
    velocity_xy: np.ndarray
    state: np.ndarray
    persistence: np.ndarray

    def __post_init__(self) -> None:
        probability = np.asarray(self.motion_probability, dtype=np.float32).reshape(-1)
        velocity = np.asarray(self.velocity_xy, dtype=np.float32)
        states = np.asarray(self.state, dtype=str).reshape(-1)
        persistence = np.asarray(self.persistence, dtype=np.int32).reshape(-1)
        count = probability.size
        if velocity.shape != (count, 2):
            raise ValueError("velocity_xy must have shape (N, 2)")
        if states.size != count or persistence.size != count:
            raise ValueError("motion evidence fields must be aligned")
        if np.any((probability < 0.0) | (probability > 1.0)):
            raise ValueError("motion probability must be in [0, 1]")
        if not np.all(np.isfinite(velocity)):
            raise ValueError("velocity_xy must contain finite values")
        if np.any(~np.isin(states, ["static", "possibly_moving", "moving", "unknown"])):
            raise ValueError("motion state contains an invalid value")
        if np.any(persistence < 1):
            raise ValueError("persistence must be positive for reported points")
        for array in (probability, velocity, states, persistence):
            array.setflags(write=False)
        object.__setattr__(self, "motion_probability", probability)
        object.__setattr__(self, "velocity_xy", velocity)
        object.__setattr__(self, "state", states)
        object.__setattr__(self, "persistence", persistence)


@dataclass
class _Track:
    track_id: int
    semantic_class: int
    centroid: np.ndarray
    velocity_xy: np.ndarray
    last_timestamp: float
    persistence: int = 1
    missed_frames: int = 0


class TemporalTracker:
    """Associate same-class spatial clusters in the stable world frame.

    ``points`` are ``XYZI`` world-frame values. The pose is validated and kept
    in the update contract so callers can pass it alongside the timestamp;
    ego-motion compensation has already happened at the observation boundary.
    Association is nearest-centroid, one-to-one, and deterministic by input
    cluster order and track id.
    """

    def __init__(
        self,
        *,
        cluster_tolerance_m: float = 0.5,
        association_distance_m: float = 2.0,
        static_speed_mps: float = 0.15,
        moving_speed_mps: float = 0.5,
        stale_after_frames: int = 3,
    ) -> None:
        if cluster_tolerance_m <= 0 or association_distance_m <= 0:
            raise ValueError("spatial thresholds must be positive")
        if not 0 <= static_speed_mps < moving_speed_mps:
            raise ValueError("speed thresholds must satisfy 0 <= static < moving")
        if stale_after_frames < 1:
            raise ValueError("stale_after_frames must be positive")
        self.cluster_tolerance_m = float(cluster_tolerance_m)
        self.association_distance_m = float(association_distance_m)
        self.static_speed_mps = float(static_speed_mps)
        self.moving_speed_mps = float(moving_speed_mps)
        self.stale_after_frames = int(stale_after_frames)
        self._tracks: dict[int, _Track] = {}
        self._next_track_id = 0
        self._last_timestamp: float | None = None

    @property
    def active_track_count(self) -> int:
        return len(self._tracks)

    def reset(self) -> None:
        """Drop all temporal state before starting a new sequence."""
        self._tracks.clear()
        self._next_track_id = 0
        self._last_timestamp = None

    def update(
        self,
        points: np.ndarray,
        semantic_class: np.ndarray,
        pose: np.ndarray,
        *,
        timestamp: float,
    ) -> MotionEvidence:
        points = np.asarray(points, dtype=np.float32)
        labels = np.asarray(semantic_class, dtype=np.int32).reshape(-1)
        transform = np.asarray(pose, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 4:
            raise ValueError("points must have shape (N, 4)")
        if not np.all(np.isfinite(points)):
            raise ValueError("points must contain finite XYZI values")
        if labels.size != points.shape[0]:
            raise ValueError("semantic_class must align with points")
        if transform.shape != (4, 4):
            raise ValueError("pose must have shape (4, 4)")
        if not np.all(np.isfinite(transform)) or not np.allclose(
            transform[3], [0.0, 0.0, 0.0, 1.0]
        ):
            raise ValueError("pose must be a finite homogeneous transform")
        if not np.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("timestamps must be non-decreasing within a sequence")
        self._last_timestamp = float(timestamp)
        world = points[:, :3].astype(np.float64, copy=False)
        clusters = self._clusters(world, labels)
        assignments: dict[int, _Track] = {}
        used: set[int] = set()
        for indices in clusters:
            centroid = world[indices].mean(axis=0)[:2]
            label = int(labels[indices[0]])
            candidate = min(
                (
                    track
                    for track in self._tracks.values()
                    if track.track_id not in used and track.semantic_class == label
                ),
                key=lambda track: (
                    np.linalg.norm(centroid - track.centroid),
                    track.track_id,
                ),
                default=None,
            )
            if (
                candidate is not None
                and np.linalg.norm(centroid - candidate.centroid)
                <= self.association_distance_m
            ):
                dt = float(timestamp - candidate.last_timestamp)
                velocity = (
                    (centroid - candidate.centroid) / dt if dt > 0 else np.zeros(2)
                )
                candidate.centroid = centroid
                candidate.velocity_xy = velocity
                candidate.last_timestamp = float(timestamp)
                candidate.persistence += 1
                candidate.missed_frames = 0
                used.add(candidate.track_id)
            else:
                candidate = _Track(
                    self._next_track_id,
                    label,
                    centroid,
                    np.zeros(2, dtype=np.float64),
                    float(timestamp),
                )
                self._next_track_id += 1
                self._tracks[candidate.track_id] = candidate
                used.add(candidate.track_id)
            assignments[id(indices)] = candidate

        for track_id in list(self._tracks):
            if track_id not in used:
                self._tracks[track_id].missed_frames += 1
                if self._tracks[track_id].missed_frames >= self.stale_after_frames:
                    del self._tracks[track_id]

        probability = np.zeros(points.shape[0], dtype=np.float32)
        velocity = np.zeros((points.shape[0], 2), dtype=np.float32)
        state = np.full(points.shape[0], "static", dtype="<U15")
        persistence = np.ones(points.shape[0], dtype=np.int32)
        for indices in clusters:
            track = assignments[id(indices)]
            speed = float(np.linalg.norm(track.velocity_xy))
            probability[indices] = self._probability(speed)
            velocity[indices] = track.velocity_xy
            state[indices] = self._state(speed)
            persistence[indices] = track.persistence
        return MotionEvidence(probability, velocity, state, persistence)

    def _clusters(self, world: np.ndarray, labels: np.ndarray) -> list[np.ndarray]:
        """Return deterministic, radius-connected components per semantic class."""

        clusters: list[np.ndarray] = []
        # The cell diagonal is no wider than the tolerance. Same-cell points
        # are therefore always connected, while neighbouring cells are merged
        # only after an exact radial-distance test.
        bucket_size = self.cluster_tolerance_m / np.sqrt(2.0)
        radius_squared = self.cluster_tolerance_m**2
        for label in sorted(np.unique(labels).tolist()):
            label_indices = np.flatnonzero(labels == label)
            local_xy = world[label_indices, :2]
            bucket_coords = np.floor(local_xy / bucket_size).astype(np.int64)
            bucket_lists: dict[tuple[int, int], list[int]] = {}
            for local_index, bucket in enumerate(bucket_coords):
                bucket_lists.setdefault((int(bucket[0]), int(bucket[1])), []).append(
                    local_index
                )
            parent = np.arange(label_indices.size, dtype=np.intp)

            def find(index: int, parents: np.ndarray = parent) -> int:
                while parents[index] != index:
                    parents[index] = parents[parents[index]]
                    index = int(parents[index])
                return index

            def union(left: int, right: int, parents: np.ndarray = parent) -> None:
                left_root, right_root = find(left), find(right)
                if left_root != right_root:
                    parents[max(left_root, right_root)] = min(left_root, right_root)

            for key, members in bucket_lists.items():
                for member in members[1:]:
                    union(members[0], member)
                left = np.asarray(members, dtype=np.intp)
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        neighbor_key = (key[0] + dx, key[1] + dy)
                        if neighbor_key <= key or neighbor_key not in bucket_lists:
                            continue
                        right = np.asarray(bucket_lists[neighbor_key], dtype=np.intp)
                        if self._cells_connect(
                            local_xy[left], local_xy[right], radius_squared
                        ):
                            # Every point within either cell is already
                            # connected to its first member, so one exact
                            # cross-cell edge joins both components.
                            union(int(left[0]), int(right[0]))
            components: dict[int, list[int]] = {}
            for local_index in range(label_indices.size):
                components.setdefault(find(local_index), []).append(local_index)
            clusters.extend(
                label_indices[np.asarray(members, dtype=np.intp)]
                for _, members in sorted(components.items())
            )
        return clusters

    @staticmethod
    def _cells_connect(
        left: np.ndarray, right: np.ndarray, radius_squared: float
    ) -> bool:
        """Check whether two occupied cells have an exact cross-cell edge.

        Chunking bounds temporary memory and stops at the first valid edge;
        unlike enumerating every neighbouring pair, dense ground returns do
        not turn one connected component into millions of union operations.
        """

        for start in range(0, left.shape[0], 256):
            delta = left[start : start + 256, None, :] - right[None, :, :]
            if np.any(np.einsum("ijk,ijk->ij", delta, delta) <= radius_squared):
                return True
        return False

    def _probability(self, speed: float) -> float:
        if speed <= self.static_speed_mps:
            return 0.0
        return min(
            1.0,
            (speed - self.static_speed_mps)
            / (self.moving_speed_mps - self.static_speed_mps),
        )

    def _state(self, speed: float) -> str:
        if speed <= self.static_speed_mps:
            return "static"
        if speed >= self.moving_speed_mps:
            return "moving"
        return "possibly_moving"


__all__ = ["MotionEvidence", "TemporalTracker"]
