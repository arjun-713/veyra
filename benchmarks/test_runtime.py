"""Protocol and executable integration tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmarks.protocol import stream_bytes
from benchmarks.run_benchmark import (
    POLICY_ADAPTERS,
    PUBLIC_POLICY_NAMES,
    compute_window_radius_m,
    load_selection,
    mapping_quality_report,
    nearest_rank_summary,
    validate_configs,
)
from datasets.common.observation import ObservationFrame, PoseSE3


def frame(
    *,
    timestamp: float = 1.0,
    frame_id: str = "000010",
    pose_x: float = 1.5,
    world_points_follow_pose: bool = False,
) -> ObservationFrame:
    points = np.array(
        [[0.01, 0.01, 1.0, 0.5], [-0.06, 0.02, 2.0, 0.2]], dtype=np.float32
    )
    if world_points_follow_pose:
        points[:, 0] += pose_x
    return ObservationFrame(
        timestamp,
        PoseSE3(
            np.array(
                [
                    [1.0, 0.0, 0.0, pose_x],
                    [0.0, 1.0, 0.0, -2.0],
                    [0.0, 0.0, 1.0, 3.25],
                    [0.0, 0.0, 0.0, 1.0],
                ]
            ),
            timestamp=timestamp - 0.01,
        ),
        points,
        np.array([1, 2]),
        np.array([0.75, 0.25]),
        np.array([True, False]),
        np.array(["drivable", "non_drivable"]),
        np.array([0.1, 0.3]),
        np.array([0.2, 0.4]),
        np.array([0.5, 0.7]),
        np.array([0.2, 0.8]),
        np.array([[1.0, 2.0], [-3.0, 4.0]]),
        dataset="fixture",
        sequence="00",
        frame_id=frame_id,
        terrain_confidence=np.array([0.6, 0.8]),
        step=np.array([0.9, 1.1]),
        motion_state=np.array(["static", "moving"]),
        observation_quality=np.array([0.4, 0.6]),
        raw_semantic_class=np.array([101, 202]),
    )


class RuntimeTests(unittest.TestCase):
    def test_dataset_selection_uses_checked_in_perception_pipeline(self):
        repo = Path(__file__).resolve().parents[1]
        dataset_root = repo / "data" / "raw" / "rellis3d" / "Rellis-3D"
        if not dataset_root.is_dir():
            self.skipTest("original RELLIS-3D data is unavailable in CI")
        if importlib.util.find_spec("pypatchworkpp") is None:
            self.skipTest("Patchwork++ Python backend is unavailable")
        frames, _distance, _entry, _latencies, _radius = load_selection(
            repo, "rellis3d", "00000", 0, 1
        )
        self.assertGreater(float(np.mean(frames[0].ground)), 0.001)
        self.assertTrue(np.all(np.isfinite(frames[0].terrain_confidence)))

    def test_mapping_quality_report_checks_real_snapshot_evidence(self):
        report = mapping_quality_report(
            input_points=np.array(
                [[0.01, 0.01, 1.0], [0.06, 0.01, 1.2]], dtype=np.float64
            ),
            rejected_out_of_window=0,
            snapshot={
                "point_count": 2,
                "nonspatial_prior_point_count": 0,
                "invariant_no_parent_descendant_overlap": True,
                "leaves": [{"level": 0, "ix": 0, "iy": 0, "count": 2, "mean_z": 1.1}],
            },
            fine_reference={"mean_z_by_cell": {(0, 0): 1.1}},
        )

        self.assertTrue(report["point_conservation"]["holds"])
        self.assertTrue(report["duplicate_ownership"]["holds"])
        self.assertTrue(report["split_merge_conservation"]["holds"])
        self.assertEqual(report["elevation_vs_fine_reference"]["sample_count"], 1)

    def test_config_validation_rejects_non_odom_distance_config(self):
        with self.assertRaisesRegex(ValueError, "frame must be odom"):
            validate_configs(
                {"semanticposs": {"root": "data", "sequences": ["00"]}},
                {
                    "levels": [0.05, 0.1, 0.2, 0.4],
                    "ranges_m": [[0, 10], [10, 30], [30, 60], [60, 100]],
                    "frame": "map",
                },
            )

    def test_config_validation_rejects_non_contiguous_distance_ranges(self):
        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_configs(
                {"semanticposs": {"root": "data", "sequences": ["00"]}},
                {
                    "levels": [0.05, 0.1, 0.2, 0.4],
                    "ranges_m": [[0, 10], [11, 30], [30, 60], [60, 100]],
                    "frame": "odom",
                },
            )

    def test_config_validation_rejects_unsupported_levels(self):
        with self.assertRaisesRegex(ValueError, "levels"):
            validate_configs(
                {
                    "semanticposs": {
                        "root": "data",
                        "sequences": ["00"],
                        "scan_dir": "velodyne",
                        "label_dir": "labels",
                        "max_range_m": 100,
                    },
                    "rellis3d": {
                        "root": "data",
                        "sequences": ["00"],
                        "scan_dir": "scans",
                        "label_dir": "labels",
                        "max_range_m": 100,
                    },
                },
                {
                    "levels": [0.05, 0.1, 0.2, 0.8],
                    "ranges_m": [[0, 10], [10, 30], [30, 60], [60, 100]],
                    "frame": "odom",
                },
            )

    def test_config_validation_accepts_compact_distance_policy_config(self):
        validate_configs(
            {
                "semanticposs": {
                    "root": "data",
                    "sequences": ["00"],
                    "scan_dir": "velodyne",
                    "label_dir": "labels",
                    "max_range_m": 100,
                },
                "rellis3d": {
                    "root": "data",
                    "sequences": ["00000"],
                    "scan_dir": "scans",
                    "label_dir": "labels",
                    "max_range_m": 100,
                },
            },
            {
                "mode": "distance_lod",
                "distance_boundaries_m": [10.0, 30.0, 60.0],
                "max_range_m": 100.0,
            },
        )

    def test_runner_script_supports_direct_invocation(self):
        repo = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(repo / "benchmarks" / "run_benchmark.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("reproducible", completed.stdout)

    def test_stream_is_deterministic(self):
        stream, digest = stream_bytes([frame()])
        text = stream.decode("ascii")
        self.assertIn("VEYRA_STREAM 2", text)
        self.assertIn("F 1000000 990000 10", text)
        self.assertIn("1 0 0 1.5 0 1 0 -2 0 0 1 3.25 0 0 0 1 2", text)
        self.assertIn(
            "P 0.0099999997764825821 0.0099999997764825821 1 0.5 1 0.75 1 1 "
            "0.10000000149011612 0.20000000298023224 0.5 0.60000002384185791 "
            "0.89999997615814209 0.20000000298023224 0 1 2 0.40000000596046448 101",
            text,
        )
        self.assertEqual(text.count("F "), 1)
        self.assertIn(digest, text)

    def test_nearest_rank_summary_is_shared_by_runner_metrics(self):
        self.assertEqual(
            nearest_rank_summary([4, 1, 3, 2]),
            {"count": 4, "mean": 2.5, "min": 1, "max": 4, "p50": 2, "p95": 4, "p99": 4},
        )

    def test_window_radius_covers_selected_world_frame_points(self):
        selected = [frame(pose_x=250.0)]
        self.assertGreaterEqual(compute_window_radius_m(selected, 100.0), 250.01)

    def test_all_public_policy_adapters_are_available(self):
        self.assertEqual(
            set(PUBLIC_POLICY_NAMES),
            {"uniform5", "uniform40", "distance_lod", "utility_lod"},
        )
        self.assertTrue(
            all(POLICY_ADAPTERS[name].available for name in PUBLIC_POLICY_NAMES)
        )

    def test_actual_binary(self):
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        if not binary or not Path(binary).is_file():
            self.skipTest("set VEYRA_BENCHMARK_BINARY to the benchmark under test")
        stream, digest = stream_bytes([frame()])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            completed = subprocess.run(
                [binary, "--policy", "uniform5", "--output", str(output)],
                input=stream,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            result = json.loads(output.read_text())
        self.assertEqual(result["stream_digest"], digest)
        self.assertEqual(result["snapshot"]["point_count"], 2)
        self.assertEqual(result["metrics"]["frame_count"], 1)
        self.assertEqual(result["schema_version"], 2)
        frame_input = result["frame_metrics"][0]["input"]
        self.assertEqual(frame_input["timestamp_us"], 1_000_000)
        self.assertEqual(frame_input["pose_timestamp_us"], 990_000)
        self.assertEqual(frame_input["pose_translation_xyz"], [1.5, -2.0, 3.25])
        self.assertEqual(frame_input["quality"]["raw_semantic_class"]["mean"], 151.5)
        self.assertEqual(frame_input["quality"]["velocity_x"]["mean"], -1.0)
        self.assertEqual(frame_input["ground"]["true_count"], 1)

    def test_actual_binary_follows_transmitted_pose_window_center(self):
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        if not binary or not Path(binary).is_file():
            self.skipTest("set VEYRA_BENCHMARK_BINARY to the benchmark under test")
        completed = subprocess.run(
            [binary, "--policy", "uniform5"],
            input=stream_bytes([frame(pose_x=250.0, world_points_follow_pose=True)])[0],
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())

    def test_actual_binary_rejects_trailing_point_tokens(self):
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        if not binary or not Path(binary).is_file():
            self.skipTest("set VEYRA_BENCHMARK_BINARY to the benchmark under test")
        stream, _ = stream_bytes([frame()])
        first_point = next(
            line for line in stream.splitlines(keepends=True) if line.startswith(b"P ")
        )
        malformed = stream.replace(first_point, first_point.rstrip() + b" extra\n", 1)
        completed = subprocess.run(
            [binary, "--policy", "uniform5"],
            input=malformed,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("malformed point record", completed.stderr.decode())

    def test_actual_binary_supports_explicit_v1_compatibility_without_enriched_data(
        self,
    ):
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        if not binary or not Path(binary).is_file():
            self.skipTest("set VEYRA_BENCHMARK_BINARY to the benchmark under test")
        stream = (
            b"VEYRA_STREAM 1\nH legacy\nF 1000000 1\nP 1 0 0.2 7 1 1\nE\nD legacy\n"
        )
        completed = subprocess.run(
            [binary, "--policy", "uniform5"],
            input=stream,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        result = json.loads(completed.stdout)
        self.assertEqual(result["protocol_version"], 1)
        self.assertFalse(result["frame_metrics"][0]["input"]["pose_available"])
        self.assertIn("map_update_latency_ns", result["metrics"])
        self.assertEqual(
            result["metrics"]["measured_rss_bytes"],
            result["metrics"]["memory"]["current_rss_bytes"],
        )

    def test_actual_binary_rejects_duplicate_header_and_trailing_fields(self):
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        if not binary or not Path(binary).is_file():
            self.skipTest("set VEYRA_BENCHMARK_BINARY to the benchmark under test")
        stream, _ = stream_bytes([frame()])
        valid = stream.decode("ascii")
        for invalid in (
            valid.replace("VEYRA_STREAM 2\n", "VEYRA_STREAM 2\nVEYRA_STREAM 2\n", 1),
            valid.replace("\nE\n", "\nE extra\n", 1),
        ):
            completed = subprocess.run(
                [binary, "--policy", "uniform5"],
                input=invalid.encode("ascii"),
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)

    def test_actual_binary_reports_real_policy_metrics(self):
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        if not binary or not Path(binary).is_file():
            self.skipTest("set VEYRA_BENCHMARK_BINARY to the benchmark under test")
        stream, digest = stream_bytes(
            [frame(), frame(timestamp=1.1, frame_id="000011")]
        )
        for policy in ("uniform5", "uniform40", "distance_lod", "utility_lod"):
            completed = subprocess.run(
                [binary, "--policy", policy, "--include-leaf-details"],
                input=stream,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            result = json.loads(completed.stdout)
            self.assertEqual(result["stream_digest"], digest)
            self.assertEqual(result["policy"], policy)
            self.assertEqual(result["snapshot"]["point_count"], 4)
            self.assertIn("topology_churn", result["metrics"]["topology"]["per_frame"])
            self.assertIn("map_update", result["metrics"]["stage_latency_ns"])
            self.assertEqual(
                result["metrics"]["stage_latency_ns"]["map_update"]["count"], 2
            )
            self.assertEqual(
                result["metrics"]["memory"]["logical_map_bytes"],
                result["snapshot"]["logical_bytes"],
            )
            self.assertIsNotNone(result["metrics"]["memory"]["allocated_map_bytes"])
            self.assertEqual(
                result["snapshot"]["memory"]["allocated_bytes"],
                result["metrics"]["memory"]["allocated_map_bytes"],
            )
            self.assertTrue(
                result["snapshot"]["invariant_no_parent_descendant_overlap"]
            )
            self.assertEqual(
                result["snapshot"]["point_count"],
                sum(leaf["count"] for leaf in result["snapshot"]["leaves"]),
            )
            self.assertIn("p99", result["metrics"]["stage_latency_ns"]["map_update"])

    def test_real_configured_one_frame_smoke(self):
        repo = Path(__file__).resolve().parents[1]
        binary = os.environ.get("VEYRA_BENCHMARK_BINARY")
        data_root = repo / "data" / "raw" / "rellis3d" / "Rellis-3D"
        if os.environ.get("VEYRA_RUN_DATASET_BENCHMARK_TESTS") != "1":
            self.skipTest(
                "set VEYRA_RUN_DATASET_BENCHMARK_TESTS=1 for local dataset benchmark smoke"
            )
        if not binary or not Path(binary).is_file() or not data_root.is_dir():
            self.skipTest("requires the benchmark binary and local RELLIS-3D data")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            csv_output = Path(directory) / "result.csv"
            completed = subprocess.run(
                [
                    "python3",
                    str(repo / "benchmarks" / "run_benchmark.py"),
                    "--repo",
                    str(repo),
                    "--binary",
                    binary,
                    "--dataset",
                    "rellis3d",
                    "--sequence",
                    "00000",
                    "--count",
                    "3",
                    "--warmup-frames",
                    "1",
                    "--repetitions",
                    "2",
                    "--output",
                    str(output),
                    "--csv-output",
                    str(csv_output),
                ],
                cwd="/tmp",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text())
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["input_frames"], 3)
        self.assertEqual(result["measured_frames_per_run"], 2)
        self.assertEqual(
            result["policies"]["uniform5"]["runs"][0]["stream_digest"],
            result["policies"]["distance_lod"]["runs"][0]["stream_digest"],
        )
        self.assertGreater(
            result["policies"]["uniform5"]["runs"][0]["snapshot"]["point_count"], 0
        )
