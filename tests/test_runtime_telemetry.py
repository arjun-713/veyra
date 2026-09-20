import os
import unittest

from runtime.telemetry import Telemetry, rss_bytes


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


if __name__ == "__main__":
    unittest.main()
