import os
import unittest

from runtime.telemetry import Telemetry, processing_fps, rss_bytes


class RuntimeTelemetryTests(unittest.TestCase):
    def test_rss_measurement_reads_the_named_process(self):
        self.assertGreater(rss_bytes(os.getpid()), 0)

    def test_report_keeps_stage_status_backend_and_provenance_separate(self):
        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "pipeline_status": {
                    "semantic": "model",
                    "ground": "available",
                    "terrain": "skipped",
                    "temporal": "unavailable",
                },
                "perception_timings_ms": {"semantic": 12.0},
                "pose": {
                    "provenance": {
                        "coordinate_frame": "lidar",
                        "timestamp_source": "absent",
                        "pose_source": "identity_absent",
                        "calibration_source": "identity_absent",
                    }
                },
                "map": {"metrics": {}, "snapshot": {}},
            },
            None,
            None,
        )
        self.assertEqual(report["perception"]["backend"], "model")
        self.assertEqual(report["perception"]["status"]["terrain"], "skipped")
        self.assertEqual(
            report["perception"]["provenance"]["timestamp_source"], "absent"
        )

    def test_report_exposes_measured_perception_evidence_without_fabricating_tracks(
        self,
    ):
        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "n_points": 4,
                "ground": [1, 1, 0, 0],
                "semantic_labels": [0, 1, 1, 6],
                "semantic_confidence": [0.0, 0.8, 0.9, 0.7],
                "drivable": ["drivable", "drivable", "unknown", "non_drivable"],
                "motion_state": ["STATIC", "STATIC", "MOVING", "STATIC"],
                "pipeline_status": {
                    "semantic": "model",
                    "ground": "pypatchworkpp.patchworkpp",
                },
                "perception_timings_ms": {},
                "map": {"snapshot": {"active_leaf_count": 1}, "metrics": {}},
            },
            None,
            None,
            {"provider": "salsanext", "execution_provider": "CPUExecutionProvider"},
        )
        self.assertEqual(report["perception"]["points"], 4)
        self.assertEqual(report["perception"]["ground_ratio"], 0.5)
        self.assertAlmostEqual(report["perception"]["semantic_confidence_mean"], 0.6)
        self.assertEqual(report["perception"]["drivable_counts"]["unknown"], 1)
        self.assertIsNone(report["perception"]["track_counts"])
        self.assertEqual(report["health"]["mapper"], "available")

    def test_missing_ground_status_is_fail_closed_not_measured(self):
        # Regression pin for PR #41 review (arjun-713) / PR #42 da881f6:
        # the real PipelineStatus dataclass + viewer serializer always emit
        # all four stage keys, so a missing "ground" key means unknown
        # provenance (synthetic input or dropped-key plumbing fault) and must
        # stay UNAVAILABLE instead of rendering a ratio from the array.
        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "n_points": 4,
                "ground": [1, 1, 0, 0],
                "semantic_labels": [0, 1, 1, 6],
                "pipeline_status": {"semantic": "model"},
                "perception_timings_ms": {},
                "map": {"snapshot": {"active_leaf_count": 1}, "metrics": {}},
            },
            None,
            None,
        )
        self.assertIsNone(report["perception"]["ground_ratio"])


class ProcessingFpsTests(unittest.TestCase):
    def test_idle_time_before_playback_does_not_dilute_throughput(self):
        # One preview frame, a 60 s pause, then ten frames at 2 fps.
        completed = [0.0] + [60.0 + 0.5 * index for index in range(10)]
        self.assertAlmostEqual(processing_fps(completed), 2.0)

    def test_fewer_than_two_recent_completions_is_unavailable(self):
        self.assertIsNone(processing_fps([]))
        self.assertIsNone(processing_fps([0.0, 30.0]))


if __name__ == "__main__":
    unittest.main()
