"""Dedicated mapper service lifecycle and bounded long-run reports."""

import json
import os
import subprocess
import unittest
from pathlib import Path


class EngineServiceTests(unittest.TestCase):
    def test_manual_governor_override_is_reported_and_validated(self):
        binary = Path(
            os.environ.get("VEYRA_RUNTIME_BINARY", "build/apps/runtime/veyra_runtime")
        ).resolve()
        result = subprocess.run(
            [str(binary), "--engine", "--policy", "utility_lod"],
            input="VEYRA_ENGINE 2\nG disabled\nS\nG automatic\nS\nC\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(messages[1]["governor"]["state"], "disabled")
        self.assertTrue(messages[1]["governor"]["allow_optional_splits"])
        self.assertGreater(messages[1]["governor"]["budget"]["max_active_cells"], 0)
        self.assertGreater(messages[1]["governor"]["budget"]["target_frame_time_ms"], 0)
        self.assertEqual(messages[3]["governor"]["state"], "normal")

    def test_binary_observation_transport_matches_text_map_and_evidence(self):
        from benchmarks.protocol import binary_frame_bytes, frame_records
        from benchmarks.test_runtime import frame as make_frame

        frame = make_frame()
        binary = Path(
            os.environ.get("VEYRA_RUNTIME_BINARY", "build/apps/runtime/veyra_runtime")
        ).resolve()
        reports = []
        for payload in (
            "".join(frame_records(frame)).encode(),
            binary_frame_bytes(frame),
        ):
            result = subprocess.run(
                [str(binary), "--engine", "--policy", "uniform5"],
                input=b"VEYRA_ENGINE 2\n" + payload + b"M 100\nC\n",
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            messages = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(messages[1]["status"], "available", messages)
            self.assertIn("u", messages[2]["cells"][0])
            self.assertGreaterEqual(messages[2]["cells"][0]["u"], 0)
            self.assertLessEqual(messages[2]["cells"][0]["u"], 1)
            reports.append((messages[1]["input"], messages[1]["snapshot"], messages[2]))
        self.assertEqual(reports[0], reports[1])

    def test_dedicated_engine_retains_bounded_history_across_1000_frames(self):
        binary = Path(
            os.environ.get("VEYRA_RUNTIME_BINARY", "build/apps/runtime/veyra_runtime")
        )
        self.assertTrue(binary.is_file(), "dedicated mapper runtime must be built")
        frame = "F 1 1 1 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0\nE\n"
        result = subprocess.run(
            [str(binary.resolve()), "--engine", "--policy", "distance_lod"],
            input="VEYRA_ENGINE 2\n" + frame * 1001 + "S\nR\nS\nC\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(messages[0]["status"], "ready")
        report = messages[-4]
        self.assertEqual(report["metrics"]["frame_count"], 1001)
        self.assertLessEqual(len(report["frame_metrics"]), 1)
        self.assertLess(len(json.dumps(report)), 16000)
        self.assertEqual(messages[-2]["metrics"]["frame_count"], 0)
        self.assertEqual(messages[-1]["status"], "closed")


if __name__ == "__main__":
    unittest.main()
