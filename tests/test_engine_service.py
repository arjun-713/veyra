"""Dedicated mapper service lifecycle and bounded long-run reports."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def built_binary(variable, relative):
    """Resolve a compiled helper, preferring an explicit environment override.

    Relative defaults are anchored to the repository root so the tests do not
    depend on the working directory they are discovered from.
    """
    override = os.environ.get(variable) or ""
    if override.strip():
        return Path(override.strip()).expanduser().resolve()
    return (REPO_ROOT / relative).resolve()


def require_binary(case, variable, relative):
    """Skip when the compiled helper has not been built.

    The C++ apps are built by the product workflow; the Python-only CI job does
    not build them, and an unbuilt binary is a missing prerequisite rather than
    a product defect.
    """
    binary = built_binary(variable, relative)
    if not binary.is_file():
        case.skipTest(
            f"{binary} is not built: configure with -DVEYRA_BUILD_APPS=ON and "
            f"build, or set {variable} to an existing executable"
        )
    return binary


RUNTIME_RELATIVE = "build/apps/runtime/veyra_runtime"


class EngineServiceTests(unittest.TestCase):
    def setUp(self):
        self.binary = require_binary(self, "VEYRA_RUNTIME_BINARY", RUNTIME_RELATIVE)

    def test_manual_governor_override_is_reported_and_validated(self):
        binary = self.binary
        result = subprocess.run(
            [str(binary), "--engine", "--policy", "utility_lod"],
            input="VEYRA_ENGINE 2\nG disabled\nS\nG automatic\nS\nC\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
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
        binary = self.binary
        reports = []
        for payload, handshake in (
            ("".join(frame_records(frame)).encode(), b"VEYRA_ENGINE 3\n"),
            (binary_frame_bytes(frame), b"VEYRA_ENGINE 3\n"),
        ):
            result = subprocess.run(
                [str(binary), "--engine", "--policy", "uniform5"],
                input=handshake + payload + b"M 100\nC\n",
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            messages = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(messages[1]["status"], "available", messages)
            self.assertIn("u", messages[2]["cells"][0])
            self.assertGreaterEqual(messages[2]["cells"][0]["u"], 0)
            self.assertLessEqual(messages[2]["cells"][0]["u"], 1)
            reports.append((messages[1]["input"], messages[1]["snapshot"], messages[2]))
        self.assertEqual(reports[0], reports[1])

    def test_batch_binary_stream_preserves_full_report_contract(self):
        from benchmarks.protocol import binary_stream_file
        from benchmarks.test_runtime import frame as make_frame

        with (
            self.subTest("native batch path"),
            tempfile.TemporaryDirectory(prefix="veyra-binary-batch-") as directory,
        ):
            stream_path = Path(directory) / "observations.stream"
            digest = binary_stream_file(
                (make_frame(frame_id=f"{index:06d}") for index in range(2)),
                stream_path,
            )
            with stream_path.open("rb") as stream_input:
                result = subprocess.run(
                    [str(self.binary), "--binary-input", "--policy", "uniform5"],
                    stdin=stream_input,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            report = json.loads(result.stdout)
            self.assertEqual(report["stream_digest"], digest)
            self.assertEqual(report["input_frames"], 2)
            self.assertEqual(report["metrics"]["frame_count"], 2)
            self.assertEqual(len(report["frame_metrics"]), 2)

    def test_batch_binary_stream_reports_frame_scoped_conservation_after_eviction(self):
        from benchmarks.protocol import binary_stream_file
        from benchmarks.test_runtime import frame as make_frame

        with tempfile.TemporaryDirectory(
            prefix="veyra-window-conservation-"
        ) as directory:
            stream_path = Path(directory) / "observations.stream"
            binary_stream_file(
                (
                    make_frame(
                        frame_id=f"{index:06d}",
                        pose_x=index * 250.0,
                        world_points_follow_pose=True,
                    )
                    for index in range(2)
                ),
                stream_path,
            )
            with stream_path.open("rb") as stream_input:
                result = subprocess.run(
                    [str(self.binary), "--binary-input", "--policy", "uniform5"],
                    stdin=stream_input,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            report = json.loads(result.stdout)
            conservation = report["frame_metrics"][-1]["point_conservation"]
            self.assertTrue(conservation["holds"])
            self.assertEqual(conservation["scope"], "active_window_after_frame")

    def test_dedicated_engine_retains_bounded_history_across_1000_frames(self):
        binary = self.binary
        frame = "F 1 1 1 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0\nE\n"
        result = subprocess.run(
            [str(binary), "--engine", "--policy", "distance_lod"],
            input="VEYRA_ENGINE 2\n" + frame * 1001 + "S\nR\nS\nC\n",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
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
