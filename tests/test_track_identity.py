"""Genuine tracker identity through the production perception path.

Covers P0.2 Step 2: per-point ``track_id`` values are the temporal
tracker's own monotonic IDs (never regenerated, inferred, or reused),
survive pipeline processing and viewer serialization, and feed telemetry
``track_counts``. Unavailable identity (temporal disabled or unproven
metadata) stays unavailable -- never a fabricated zero.
"""

import unittest

import numpy as np

from datasets.common.observation import FrameProvenance, ObservationFrame, PoseSE3
from perception.pipeline import PerceptionPipeline
from perception.temporal import TemporalTracker
from runtime.telemetry import Telemetry
from viewer.runtime import RuntimeSession


def _world_frame(points, labels, timestamp):
    points = np.asarray(points, dtype=np.float32)
    labels = np.asarray(labels, dtype=np.int32)
    count = points.shape[0]
    return ObservationFrame(
        timestamp=float(timestamp),
        pose=PoseSE3.identity(float(timestamp)),
        points=points,
        semantic_class=labels,
        semantic_confidence=np.ones(count, dtype=np.float32),
        ground=np.zeros(count, dtype=bool),
        drivable=np.full(count, "unknown"),
        slope=np.zeros(count, dtype=np.float32),
        roughness=np.zeros(count, dtype=np.float32),
        height_complexity=np.zeros(count, dtype=np.float32),
        motion_probability=np.zeros(count, dtype=np.float32),
        velocity_xy=np.zeros((count, 2), dtype=np.float32),
        dataset="synthetic-test",
        sequence="00",
        frame_id="000000",
        provenance=FrameProvenance(
            coordinate_frame="world",
            pose_source="dataset",
            timestamp_source="dataset",
        ),
    )


def _cluster(x, semantic_class=1):
    points = np.array([[x, 0.0, 0.0, 1.0], [x + 0.1, 0.0, 0.0, 1.0]], dtype=np.float32)
    return points, np.full(2, semantic_class, dtype=np.int32)


def _serialize(output, binary=True):
    """Run the production viewer serializer without dataset IO."""

    class _StubAdapter:
        pass

    session = object.__new__(RuntimeSession)
    session.adapter = _StubAdapter()
    session.dataset = "synthetic-test"
    session.sequence = "00"
    session.min_range_m = 0.0
    session.max_range_m = None
    session._frames = [object(), object()]
    return session._serialize(
        output, 0, budget=1000, map_payload={"status": "unavailable"}, binary=binary
    )


def _state():
    return {
        "state": "paused",
        "index": 0,
        "frames": 1,
        "queue_depth": 0,
        "dropped_frames": 0,
        "visualization_dropped": 0,
    }


class TrackIdentityTests(unittest.TestCase):
    def test_disabled_temporal_keeps_identity_unavailable(self):
        points, labels = _cluster(0.0)
        for pipeline in (
            PerceptionPipeline(),
            PerceptionPipeline(temporal_enabled=False),
        ):
            output = pipeline.process(_world_frame(points, labels, 0.0))
            self.assertIn(output.status.temporal, {"unavailable", "disabled"})
            self.assertIsNone(output.frame.track_id)
            payload = _serialize(output)
            self.assertIsNone(payload["track_ids"])
            report = Telemetry().report(_state(), payload, None, None)
            self.assertIsNone(report["perception"]["track_counts"])

    def test_unproven_metadata_keeps_identity_unavailable(self):
        tracker = TemporalTracker()
        pipeline = PerceptionPipeline(temporal_tracker=tracker)
        points, labels = _cluster(0.0)
        frame = _world_frame(points, labels, 0.0)
        # Lidar-frame provenance must not advance the tracker.
        lidar_frame = ObservationFrame(
            timestamp=frame.timestamp,
            pose=frame.pose,
            points=frame.points,
            semantic_class=frame.semantic_class,
            semantic_confidence=frame.semantic_confidence,
            ground=frame.ground,
            drivable=frame.drivable,
            slope=frame.slope,
            roughness=frame.roughness,
            height_complexity=frame.height_complexity,
            motion_probability=frame.motion_probability,
            velocity_xy=frame.velocity_xy,
            dataset=frame.dataset,
            sequence=frame.sequence,
            frame_id=frame.frame_id,
            provenance=FrameProvenance(coordinate_frame="lidar"),
        )
        output = pipeline.process(lidar_frame)
        self.assertEqual(output.status.temporal, "unavailable")
        self.assertIsNone(output.frame.track_id)
        self.assertEqual(tracker.active_track_count, 0)
        report = Telemetry().report(_state(), _serialize(output), None, None)
        self.assertIsNone(report["perception"]["track_counts"])

    def test_genuine_id_survives_pipeline_and_serialization(self):
        tracker = TemporalTracker()
        pipeline = PerceptionPipeline(temporal_tracker=tracker)
        points, labels = _cluster(0.0)
        pipeline.process(_world_frame(points, labels, 0.0))
        output = pipeline.process(_world_frame(points, labels, 1.0))

        (live,) = tracker.active_tracks()
        # The production frame carries the tracker's own ID on every point,
        # and motion classification still reports a valid verdict.
        np.testing.assert_array_equal(output.frame.track_id, [live.track_id] * 2)
        self.assertTrue(
            np.all(
                np.isin(
                    output.frame.motion_state,
                    ["static", "possibly_moving", "moving", "unknown"],
                )
            )
        )

        payload = _serialize(output, binary=True)
        self.assertEqual(np.asarray(payload["track_ids"]).tolist(), [live.track_id] * 2)
        text_payload = _serialize(output, binary=False)
        self.assertEqual(text_payload["track_ids"], [live.track_id] * 2)

        report = Telemetry().report(_state(), payload, None, None)
        self.assertEqual(report["perception"]["track_counts"], {str(live.track_id): 2})

    def test_multi_track_count_matches_live_tracks(self):
        tracker = TemporalTracker()
        pipeline = PerceptionPipeline(temporal_tracker=tracker)
        first_points, first_labels = _cluster(0.0)
        second_points, second_labels = _cluster(50.0)
        points = np.concatenate([first_points, second_points])
        labels = np.concatenate([first_labels, second_labels])
        pipeline.process(_world_frame(points, labels, 0.0))
        output = pipeline.process(_world_frame(points, labels, 1.0))

        live_ids = sorted(snapshot.track_id for snapshot in tracker.active_tracks())
        self.assertEqual(len(live_ids), 2)
        self.assertEqual(len(set(output.frame.track_id.tolist())), 2)
        for track_id in output.frame.track_id.tolist():
            self.assertIn(track_id, live_ids)

        report = Telemetry().report(_state(), _serialize(output), None, None)
        track_counts = report["perception"]["track_counts"]
        self.assertEqual(len(track_counts), 2)
        self.assertEqual(len(track_counts), tracker.active_track_count)
        self.assertEqual(sum(track_counts.values()), 4)

    def test_deleted_track_disappears_without_id_reuse(self):
        tracker = TemporalTracker(stale_after_frames=2)
        pipeline = PerceptionPipeline(temporal_tracker=tracker)
        points, labels = _cluster(0.0)
        pipeline.process(_world_frame(points, labels, 0.0))
        (first,) = tracker.active_tracks()

        moved_points, moved_labels = _cluster(50.0)
        pipeline.process(_world_frame(moved_points, moved_labels, 1.0))
        output = pipeline.process(_world_frame(moved_points, moved_labels, 2.0))

        # The stale track is evicted by the existing lifecycle; the moved
        # cluster keeps its own fresh ID, which is never a reused value.
        (live,) = tracker.active_tracks()
        self.assertNotEqual(live.track_id, first.track_id)
        self.assertGreater(live.track_id, first.track_id)
        np.testing.assert_array_equal(output.frame.track_id, [live.track_id] * 2)

        report = Telemetry().report(_state(), _serialize(output), None, None)
        self.assertEqual(report["perception"]["track_counts"], {str(live.track_id): 2})

    def test_excluded_points_carry_no_fabricated_id(self):
        tracker = TemporalTracker(exclude_classes=(9,))
        points, labels = _cluster(0.0, semantic_class=9)
        evidence = tracker.update(points, labels, np.eye(4), timestamp=0.0)
        self.assertIsNotNone(evidence.track_id)
        np.testing.assert_array_equal(evidence.track_id, [-1, -1])
        self.assertEqual(tracker.active_track_count, 0)

        pipeline = PerceptionPipeline(
            temporal_tracker=TemporalTracker(exclude_classes=(9,))
        )
        output = pipeline.process(_world_frame(points, labels, 0.0))
        np.testing.assert_array_equal(output.frame.track_id, [-1, -1])
        report = Telemetry().report(_state(), _serialize(output), None, None)
        # Zero genuine tracks: an empty mapping, distinct from unavailable.
        self.assertEqual(report["perception"]["track_counts"], {})


if __name__ == "__main__":
    unittest.main()
