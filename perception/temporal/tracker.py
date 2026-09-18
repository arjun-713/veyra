"""Ego-motion-compensated, geometry-first temporal association.

The tracker accepts points already expressed in the stable world frame and the
source pose for each frame. Semantic classes are used only to avoid associating
incompatible clusters; they never imply motion.

Motion states are consistency-confirmed: the first velocity estimate of a
track is reported by speed exactly as measured, but from the third
observation on a track must show a regime-consistent velocity (same speed
regime, aligned direction) to keep a ``static`` or ``moving`` verdict.
Anything uncertain collapses to ``possibly_moving`` — never to ``static`` —
so downstream static-map consumers only ever see confirmed rest.
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
        if not np.all(np.isfinite(probability)) or np.any(
            (probability < 0.0) | (probability > 1.0)
        ):
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


@dataclass(frozen=True)
class TrackSnapshot:
    """Read-only view of one live track for validation and metrics."""

    track_id: int
    semantic_class: int
    persistence: int
    missed_frames: int
    speed_mps: float
    motion_valid: bool
    confirmed: bool
    centroid_xy: tuple[float, float] = (0.0, 0.0)


@dataclass
class _Track:
    track_id: int
    semantic_class: int
    centroid: np.ndarray
    velocity_xy: np.ndarray
    last_timestamp: float
    persistence: int = 1
    missed_frames: int = 0
    motion_valid: bool = False
    confirmed: bool = True


class TemporalTracker:
    """Associate same-class spatial clusters in the stable world frame.

    ``points`` are ``XYZI`` world-frame values. The pose is validated and kept
    in the update contract so callers can pass it alongside the timestamp;
    ego-motion compensation has already happened at the observation boundary.
    Association is nearest-centroid, one-to-one, and deterministic by input
    cluster order and track id.

    ``exclude_classes`` lists semantic classes that never form tracks (for
    example ground-surface classes already consumed by the terrain branch).
    Excluded points keep aligned ``unknown`` evidence rows without asserting
    any motion verdict.
    """

    def __init__(
        self,
        *,
        cluster_tolerance_m: float = 0.5,
        association_distance_m: float = 2.0,
        static_speed_mps: float = 0.15,
        moving_speed_mps: float = 0.5,
        stale_after_frames: int = 3,
        consistency_cosine: float = 0.5,
        consistency_ratio: float = 4.0,
        exclude_classes: tuple[int, ...] = (),
    ) -> None:
        thresholds = (
            cluster_tolerance_m,
            association_distance_m,
            static_speed_mps,
            moving_speed_mps,
            consistency_cosine,
            consistency_ratio,
        )
        if not all(np.isfinite(value) for value in thresholds):
            raise ValueError("tracker thresholds must be finite")
        if cluster_tolerance_m <= 0 or association_distance_m <= 0:
            raise ValueError("spatial thresholds must be positive")
        if not 0 <= static_speed_mps < moving_speed_mps:
            raise ValueError("speed thresholds must satisfy 0 <= static < moving")
        if stale_after_frames < 1:
            raise ValueError("stale_after_frames must be positive")
        if not -1.0 <= consistency_cosine <= 1.0:
            raise ValueError("consistency_cosine must lie in [-1, 1]")
        if consistency_ratio < 1.0:
            raise ValueError("consistency_ratio must be at least 1")
        excluded = tuple(int(value) for value in exclude_classes)
        if any(value < 0 for value in excluded):
            raise ValueError("exclude_classes must contain non-negative class IDs")
        if len(set(excluded)) != len(excluded):
            raise ValueError("exclude_classes must not contain duplicates")
        self.cluster_tolerance_m = float(cluster_tolerance_m)
        self.association_distance_m = float(association_distance_m)
        self.static_speed_mps = float(static_speed_mps)
        self.moving_speed_mps = float(moving_speed_mps)
        self.stale_after_frames = int(stale_after_frames)
        self.consistency_cosine = float(consistency_cosine)
        self.consistency_ratio = float(consistency_ratio)
        self.exclude_classes = excluded
        self._tracks: dict[int, _Track] = {}
        self._next_track_id = 0
        self._last_timestamp: float | None = None

    @property
    def active_track_count(self) -> int:
        return len(self._tracks)

    def active_tracks(self) -> tuple[TrackSnapshot, ...]:
        """Return deterministic read-only snapshots of live tracks.

        Snapshots are sorted by track id and expose no mutable state; they
        exist so validation can measure persistence, ghost lifetime, and
        velocity without touching tracker internals.
        """
        return tuple(
            TrackSnapshot(
                track_id=track.track_id,
                semantic_class=track.semantic_class,
                persistence=track.persistence,
                missed_frames=track.missed_frames,
                speed_mps=float(np.linalg.norm(track.velocity_xy))
                if track.motion_valid
                else 0.0,
                motion_valid=track.motion_valid,
                confirmed=track.confirmed,
                centroid_xy=(float(track.centroid[0]), float(track.centroid[1])),
            )
            for track in sorted(self._tracks.values(), key=lambda item: item.track_id)
        )

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
        rotation = transform[:3, :3]
        if (
            not np.all(np.isfinite(transform))
            or not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0])
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=2e-3)
            or not np.isclose(np.linalg.det(rotation), 1.0, atol=2e-3)
        ):
            raise ValueError("pose must be a finite homogeneous transform")
        if not np.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("timestamps must be non-decreasing within a sequence")
        self._last_timestamp = float(timestamp)
        world = points[:, :3].astype(np.float64, copy=False)
        if self.exclude_classes:
            tracked_mask = ~np.isin(labels, self.exclude_classes)
            tracked_index = np.flatnonzero(tracked_mask)
            clusters = [
                tracked_index[component]
                for component in self._clusters(
                    world[tracked_mask], labels[tracked_mask]
                )
            ]
        else:
            clusters = self._clusters(world, labels)
        assignments: dict[int, _Track] = {}
        used: set[int] = set()
        track_bucket_size = self.association_distance_m / np.sqrt(2.0)
        tracks_by_bucket: dict[tuple[int, int], list[_Track]] = {}
        for track in self._tracks.values():
            bucket = tuple(
                np.floor(track.centroid / track_bucket_size).astype(np.int64)
            )
            tracks_by_bucket.setdefault((int(bucket[0]), int(bucket[1])), []).append(
                track
            )
        for indices in clusters:
            centroid = world[indices].mean(axis=0)[:2]
            label = int(labels[indices[0]])
            bucket = np.floor(centroid / track_bucket_size).astype(np.int64)
            nearby_tracks: list[_Track] = []
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    nearby_tracks.extend(
                        tracks_by_bucket.get(
                            (int(bucket[0] + dx), int(bucket[1] + dy)), []
                        )
                    )
            candidate = min(
                (
                    track
                    for track in nearby_tracks
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
                motion_valid = dt > 0
                velocity = (
                    (centroid - candidate.centroid) / dt
                    if motion_valid
                    else np.zeros(2)
                )
                if motion_valid and candidate.motion_valid:
                    confirmed = self._velocity_confirmed(
                        candidate.velocity_xy, velocity
                    )
                else:
                    # First velocity estimate (or a repeated timestamp with no
                    # new information): report by speed exactly as measured.
                    # Confirmation applies from the third observation on.
                    confirmed = True
                candidate.centroid = centroid
                candidate.velocity_xy = velocity
                candidate.last_timestamp = float(timestamp)
                candidate.persistence += 1
                candidate.missed_frames = 0
                candidate.motion_valid = motion_valid
                candidate.confirmed = confirmed and motion_valid
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
                track_bucket = tuple(
                    np.floor(candidate.centroid / track_bucket_size).astype(np.int64)
                )
                tracks_by_bucket.setdefault(
                    (int(track_bucket[0]), int(track_bucket[1])), []
                ).append(candidate)
                used.add(candidate.track_id)
            assignments[id(indices)] = candidate

        for track_id in list(self._tracks):
            if track_id not in used:
                self._tracks[track_id].missed_frames += 1
                if self._tracks[track_id].missed_frames >= self.stale_after_frames:
                    del self._tracks[track_id]

        probability = np.zeros(points.shape[0], dtype=np.float32)
        velocity = np.zeros((points.shape[0], 2), dtype=np.float32)
        state = np.full(points.shape[0], "unknown", dtype="<U15")
        persistence = np.ones(points.shape[0], dtype=np.int32)
        for indices in clusters:
            track = assignments[id(indices)]
            if not track.motion_valid:
                continue
            speed = float(np.linalg.norm(track.velocity_xy))
            probability[indices] = self._probability(speed)
            velocity[indices] = track.velocity_xy
            state[indices] = (
                self._state(speed) if track.confirmed else "possibly_moving"
            )
            persistence[indices] = track.persistence
        return MotionEvidence(probability, velocity, state, persistence)

    def _clusters(self, world: np.ndarray, labels: np.ndarray) -> list[np.ndarray]:
        """Return deterministic exact radius-connected components per class."""

        clusters: list[np.ndarray] = []
        for label in sorted(np.unique(labels).tolist()):
            label_indices = np.flatnonzero(labels == label)
            components = self._radius_components(
                world[label_indices, :2], self.cluster_tolerance_m
            )
            clusters.extend(label_indices[component] for component in components)
        return clusters

    @staticmethod
    def _radius_components(points_xy: np.ndarray, tolerance: float) -> list[np.ndarray]:
        """Find exact radius components without constructing a radius graph.

        Delaunay contains the Euclidean minimum spanning tree, so filtering
        Delaunay edges at the radius threshold preserves the connected
        components of the full radius graph. Duplicate points are collapsed
        before geometry and expanded through ``inverse`` afterward.
        """

        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import Delaunay, QhullError, cKDTree

        unique_points, inverse = np.unique(
            np.asarray(points_xy, dtype=np.float64), axis=0, return_inverse=True
        )
        unique_count = unique_points.shape[0]
        if unique_count == 0:
            return []
        if unique_count == 1:
            return [np.arange(points_xy.shape[0], dtype=np.intp)]

        radius_squared = tolerance * tolerance
        if unique_count == 2:
            delta = unique_points[0] - unique_points[1]
            if float(np.dot(delta, delta)) <= radius_squared:
                return [np.arange(points_xy.shape[0], dtype=np.intp)]
            return TemporalTracker._expand_components(
                np.arange(unique_count, dtype=np.intp), inverse
            )
        # Delaunay is useful for small, sparse clusters, but its triangulation
        # cost and temporary memory become a poor fit for dense LiDAR scans.
        # Once a class contains a substantial number of returns, use a
        # compiled spatial radius query instead of a global triangulation.
        if unique_count >= 512:
            return TemporalTracker._spatial_radius_components(
                unique_points, inverse, tolerance
            )
        edges: np.ndarray
        if TemporalTracker._is_collinear(unique_points):
            order = TemporalTracker._dominant_axis_order(unique_points)
            consecutive = np.column_stack((order[:-1], order[1:]))
            deltas = unique_points[consecutive[:, 0]] - unique_points[consecutive[:, 1]]
            edges = consecutive[np.einsum("ij,ij->i", deltas, deltas) <= radius_squared]
        else:
            try:
                triangulation = Delaunay(unique_points)
                if np.asarray(triangulation.coplanar).size:
                    raise QhullError("Delaunay omitted coplanar vertices")
                simplices = np.asarray(triangulation.simplices, dtype=np.intp)
                candidate_edges = np.concatenate(
                    (
                        simplices[:, [0, 1]],
                        simplices[:, [1, 2]],
                        simplices[:, [2, 0]],
                    ),
                    axis=0,
                )
                edges = np.unique(np.sort(candidate_edges, axis=1), axis=0)
                deltas = unique_points[edges[:, 0]] - unique_points[edges[:, 1]]
                edges = edges[np.einsum("ij,ij->i", deltas, deltas) <= radius_squared]
            except QhullError:
                # query_ball_point visits one source point at a time, so its
                # temporary neighbor list is bounded by one local query and
                # does not materialize the full radius graph. No jitter is
                # used, preserving deterministic behavior for degenerate data.
                tree = cKDTree(unique_points)
                parent = np.arange(unique_count, dtype=np.intp)

                def find(index: int) -> int:
                    while parent[index] != index:
                        parent[index] = parent[parent[index]]
                        index = int(parent[index])
                    return index

                for index in range(unique_count):
                    neighbors = tree.query_ball_point(
                        unique_points[index], tolerance, return_sorted=True
                    )
                    for neighbor in neighbors:
                        if neighbor <= index:
                            continue
                        delta = unique_points[index] - unique_points[neighbor]
                        if float(np.dot(delta, delta)) <= radius_squared:
                            left, right = find(index), find(int(neighbor))
                            if left != right:
                                parent[max(left, right)] = min(left, right)
                component_labels = np.asarray([find(index) for index in parent])
                return TemporalTracker._expand_components(component_labels, inverse)

        if edges.size == 0:
            component_labels = np.arange(unique_count, dtype=np.intp)
        else:
            # ``directed=False`` makes connected_components treat each stored
            # edge as undirected, so storing both orientations only doubles
            # the CSR memory and sorting work for no semantic benefit.
            rows = edges[:, 0]
            columns = edges[:, 1]
            graph = csr_matrix(
                (np.ones(rows.size, dtype=np.uint8), (rows, columns)),
                shape=(unique_count, unique_count),
            )
            _, component_labels = connected_components(graph, directed=False)
        return TemporalTracker._expand_components(component_labels, inverse)

    @staticmethod
    def _spatial_radius_components(
        unique_points: np.ndarray, inverse: np.ndarray, tolerance: float
    ) -> list[np.ndarray]:
        """Compute exact components with SciPy's compiled spatial index.

        Delaunay triangulation is a poor dense-scan primitive: it creates a
        global triangulation for every semantic class even though temporal
        association only needs radius connectivity. ``query_pairs`` performs
        the exact radius search in compiled code and returns only qualifying
        edges; connected components then preserve the same semantics without
        Python point-by-point neighbour work.
        """

        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree

        edges = np.asarray(
            cKDTree(unique_points).query_pairs(float(tolerance), output_type="ndarray"),
            dtype=np.intp,
        )
        if edges.size == 0:
            component_labels = np.arange(unique_points.shape[0], dtype=np.intp)
        else:
            # connected_components symmetrizes an undirected graph; retaining
            # only query_pairs' canonical orientation halves sparse overhead.
            rows = edges[:, 0]
            columns = edges[:, 1]
            graph = csr_matrix(
                (np.ones(rows.size, dtype=np.uint8), (rows, columns)),
                shape=(unique_points.shape[0], unique_points.shape[0]),
            )
            _, component_labels = connected_components(graph, directed=False)
        return TemporalTracker._expand_components(component_labels, inverse)

    @staticmethod
    def _is_collinear(points_xy: np.ndarray) -> bool:
        if points_xy.shape[0] <= 2:
            return True
        base = points_xy[-1] - points_xy[0]
        cross = base[0] * (points_xy[:, 1] - points_xy[0, 1]) - base[1] * (
            points_xy[:, 0] - points_xy[0, 0]
        )
        return bool(np.all(cross == 0.0))

    @staticmethod
    def _dominant_axis_order(points_xy: np.ndarray) -> np.ndarray:
        axis = int(np.argmax(np.ptp(points_xy, axis=0)))
        other = 1 - axis
        return np.lexsort(
            (np.arange(points_xy.shape[0]), points_xy[:, other], points_xy[:, axis])
        )

    @staticmethod
    def _expand_components(
        component_labels: np.ndarray, inverse: np.ndarray
    ) -> list[np.ndarray]:
        groups: dict[int, list[int]] = {}
        for local_index, unique_index in enumerate(inverse):
            groups.setdefault(int(component_labels[unique_index]), []).append(
                local_index
            )
        return [
            np.asarray(members, dtype=np.intp)
            for _, members in sorted(groups.items(), key=lambda item: item[1][0])
        ]

    def _regime(self, speed: float) -> int:
        """Quantize a speed into rest (0), slow (1), or fast (2) bands."""
        if speed <= self.static_speed_mps:
            return 0
        if speed < self.moving_speed_mps:
            return 1
        return 2

    def _velocity_confirmed(
        self, previous: np.ndarray, current: np.ndarray
    ) -> bool:
        """Check whether two consecutive velocity estimates agree.

        Agreement means the same speed regime plus an aligned direction and
        a bounded speed ratio. Resampling jitter and wrong-neighbour
        associations flip direction or jump in magnitude between frames, so
        they fail here and collapse to ``possibly_moving`` instead of
        asserting ``static`` or ``moving``.
        """
        previous_speed = float(np.linalg.norm(previous))
        current_speed = float(np.linalg.norm(current))
        if self._regime(previous_speed) != self._regime(current_speed):
            return False
        if self._regime(current_speed) == 0:
            return True
        if current_speed <= 0.0 or previous_speed <= 0.0:
            return False
        cosine = float(np.dot(previous, current) / (previous_speed * current_speed))
        if cosine < self.consistency_cosine:
            return False
        ratio = max(previous_speed, current_speed) / min(
            previous_speed, current_speed
        )
        return bool(ratio <= self.consistency_ratio)

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


__all__ = ["MotionEvidence", "TemporalTracker", "TrackSnapshot"]
