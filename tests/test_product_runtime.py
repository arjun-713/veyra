"""Product boundaries: bounded transport, validated controls and real replay."""

import importlib.util
import io
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_engine_service import require_binary

BENCHMARK_RELATIVE = "build/apps/benchmark/veyra_benchmark"


class ProductProtocolTests(unittest.TestCase):
    def test_protocol_package_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("runtime"))

    def test_visualization_frame_preserves_binary_payload(self):
        from runtime.protocol import encode_message, read_message

        payload = struct.pack("<8f", 1, 2, 3, 0.5, 7, 1, 0, 0.2)
        packet = encode_message({"type": "visualization", "index": 4}, payload)
        self.assertEqual(packet[:8], b"VYRA\x01\x00\x02\x00")
        metadata, output = read_message(io.BytesIO(packet))
        self.assertEqual(metadata["index"], 4)
        self.assertEqual(output, payload)

    def test_oversized_header_rejected_before_reading_body(self):
        from runtime.protocol import read_message

        with self.assertRaisesRegex(ValueError, "size"):
            read_message(io.BytesIO(struct.pack("<4sHHII", b"VYRA", 1, 1, 2**31, 0)))

    def test_latest_visualization_replaces_pending_frame(self):
        from runtime.protocol import Outbox

        box = Outbox(capacity=2)
        box.publish({"type": "visualization", "index": 1}, b"a")
        box.publish({"type": "visualization", "index": 2}, b"b")
        box.publish({"type": "response", "id": "control"})
        self.assertEqual(box.take()[0]["id"], "control")
        self.assertEqual(box.take()[0]["index"], 2)
        self.assertEqual(box.visualization_dropped, 1)

    def test_cli_responds_to_status_and_shuts_down_on_eof(self):
        process = subprocess.run(
            [sys.executable, "-m", "runtime"],
            input=b'{"id":"s","command":"status","args":{}}\n',
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        from runtime.protocol import read_message

        stream = io.BytesIO(process.stdout)
        messages = []
        while stream.tell() < len(process.stdout):
            messages.append(read_message(stream)[0])
        response = next(message for message in messages if message.get("id") == "s")
        self.assertEqual(response["status"]["state"], "unconfigured")


class ProductConfigTests(unittest.TestCase):
    def test_default_session_pipeline_enables_ground_and_terrain_evidence(self):
        from runtime.config import validate_config

        config = validate_config(
            {
                "dataset": "generic",
                "dataset_root": "/tmp",
                "sequence": "00",
                "pipeline": {"semantic": {"mode": "ground_truth"}},
            },
            Path.cwd(),
            check_paths=False,
        )

        self.assertEqual(config["pipeline"]["semantic"], {"mode": "ground_truth"})
        self.assertTrue(config["pipeline"]["ground"]["enabled"])
        self.assertTrue(config["pipeline"]["terrain"]["enabled"])
        self.assertFalse(config["pipeline"]["temporal"]["enabled"])

    def test_rejects_unsafe_and_nonfinite_configuration(self):
        from runtime.config import validate_config

        for changed in (
            {"map": {"policy": "shell"}},
            {"playback": {"fps": float("nan")}},
            {"visualization": {"point_budget": 100001}},
        ):
            config = {
                "dataset": "generic",
                "dataset_root": "/tmp",
                "sequence": "00",
                **changed,
            }
            with self.assertRaises(ValueError):
                validate_config(config, Path.cwd(), check_paths=False)

    def test_unknown_configuration_fields_are_rejected(self):
        from runtime.config import validate_config

        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_config(
                {
                    "dataset": "generic",
                    "dataset_root": "/tmp",
                    "sequence": "00",
                    "shell": "rm",
                },
                Path.cwd(),
                check_paths=False,
            )

    def test_imported_config_cannot_launch_an_arbitrary_executable(self):
        from runtime.config import validate_config

        with self.assertRaisesRegex(ValueError, "installed Veyra backend"):
            validate_config(
                {
                    "dataset": "generic",
                    "dataset_root": "/tmp",
                    "sequence": "00",
                    "map": {"executable": "/tmp/evil", "policy": "distance_lod"},
                },
                Path.cwd(),
                check_paths=False,
            )

    def test_resource_profile_and_governor_override_are_validated(self):
        from runtime.config import validate_config

        base = {"dataset": "generic", "dataset_root": "/tmp", "sequence": "00"}
        config = validate_config(
            {
                **base,
                "map": {
                    "resource_profile": "performance",
                    "governor_override": "conserve",
                },
            },
            Path.cwd(),
            check_paths=False,
        )
        self.assertEqual(config["map"]["resource_profile"], "performance")
        self.assertEqual(config["map"]["governor_override"], "conserve")
        for field, value in (
            ("resource_profile", "extreme"),
            ("governor_override", "shell"),
        ):
            with self.assertRaises(ValueError):
                validate_config(
                    {**base, "map": {field: value}}, Path.cwd(), check_paths=False
                )


class ProductTelemetryTests(unittest.TestCase):
    def test_sample_ratios_use_sample_count_not_full_scan_size(self):
        from runtime.telemetry import Telemetry

        state = {
            "state": "paused",
            "index": 0,
            "frames": 10,
            "queue_depth": 0,
            "dropped_frames": 0,
            "visualization_dropped": 0,
        }
        report = Telemetry().report(
            state,
            {
                "n_points": 1000,
                "ground": [True, False, True, False],
                "semantic_labels": [0, 1, 0, 9],
                "pipeline_status": {
                    "ground": "pypatchworkpp.patchworkpp",
                    "semantic": "ground_truth",
                },
            },
            None,
            None,
        )
        self.assertEqual(report["perception"]["ground_ratio"], 0.5)
        self.assertEqual(report["perception"]["unknown_ratio"], 0.5)
        self.assertEqual(report["perception"]["sampled_points"], 4)
        self.assertIsNone(report["fps"])

    def test_unavailable_ground_is_not_a_measured_zero_ratio(self):
        from runtime.telemetry import Telemetry

        state = {
            "state": "paused",
            "index": 0,
            "frames": 10,
            "queue_depth": 0,
            "dropped_frames": 0,
            "visualization_dropped": 0,
        }
        report = Telemetry().report(
            state,
            {
                "n_points": 2,
                "ground": [False, False],
                "pipeline_status": {"ground": "unavailable"},
            },
            None,
            None,
        )
        self.assertIsNone(report["perception"]["ground_ratio"])

    def test_runtime_execution_device_wins_over_static_config(self):
        from runtime.telemetry import Telemetry

        state = {
            "state": "running",
            "index": 0,
            "frames": 10,
            "queue_depth": 0,
            "dropped_frames": 0,
            "visualization_dropped": 0,
        }
        base = {
            "n_points": 1,
            "pipeline_status": {
                "semantic": "model",
                "semantic_execution": "CPUExecutionProvider",
            },
        }
        report = Telemetry().report(state, base, None, None, {"mode": "salsanext"})
        self.assertEqual(
            report["perception"]["execution_provider"], "CPUExecutionProvider"
        )

    def test_ground_truth_neural_bypass_is_explicit(self):
        from runtime.telemetry import Telemetry

        state = {
            "state": "running",
            "index": 0,
            "frames": 10,
            "queue_depth": 0,
            "dropped_frames": 0,
            "visualization_dropped": 0,
        }
        report = Telemetry().report(
            state,
            {
                "n_points": 1,
                "pipeline_status": {
                    "semantic": "ground_truth",
                    "semantic_execution": "bypassed",
                },
            },
            None,
            None,
            {"mode": "ground_truth"},
        )
        self.assertEqual(report["perception"]["provider"], "Ground Truth")
        self.assertEqual(report["perception"]["execution_provider"], "bypassed")

    def test_map_counts_governor_and_topology_rates_use_engine_schema(self):
        from runtime.telemetry import Telemetry

        report = Telemetry().report(
            {
                "state": "running",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 2,
                "visualization_dropped": 0,
            },
            {
                "map": {
                    "snapshot": {
                        "active_leaf_count": 7,
                        "topology_change_count": 3,
                        "levels": {"0": 4, "1": 3},
                    },
                    "metrics": {
                        "topology": {
                            "per_frame": {
                                "splits": {"mean": 1.5},
                                "merges": {"mean": 0.5},
                            }
                        }
                    },
                    "governor": {"state": "approaching_budget"},
                }
            },
            None,
            None,
        )
        self.assertEqual(report["map"]["active_cells"], 7)
        self.assertEqual(report["map"]["splits_per_frame"], 1.5)
        self.assertEqual(report["map"]["merges_per_frame"], 0.5)
        self.assertEqual(report["governor"]["state"], "approaching_budget")


if __name__ == "__main__":
    unittest.main()


class ReplayRegressionTests(unittest.TestCase):
    def test_seek_maps_each_intermediate_observation(self):
        from tests.test_runtime_player import RuntimePlayerTests, _write_frame

        class Counter:
            def __init__(self):
                self.points = 0

            def process_frame(self, frame):
                self.points += len(frame.points)
                return {"status": "available", "point_count": self.points}

            def reset(self):
                self.points = 0

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(3):
                _write_frame(root, "00000", f"{index:06d}", index)
            _write_frame(root, "00001", "000000", 0)
            session = RuntimePlayerTests()._runtime(root)
            session.map_runner = Counter()
            frame = session.frame_payload(2, budget=10)
            self.assertEqual(frame["map"]["point_count"], 6)
            self.assertEqual(
                session.frame_payload(1, budget=10)["map"]["point_count"], 4
            )
            session.close()

    def test_invalid_sequence_preserves_session(self):
        from tests.test_runtime_player import RuntimePlayerTests, _write_frame

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "00000", "000000", 0)
            _write_frame(root, "00001", "000000", 0)
            session = RuntimePlayerTests()._runtime(root)
            with self.assertRaises((ValueError, FileNotFoundError, KeyError)):
                session.select_sequence("missing", budget=10)
            self.assertEqual(session.status()["sequence"], "00000")

    def test_binary_frame_keeps_numpy_arrays(self):
        import numpy as np

        from tests.test_runtime_player import RuntimePlayerTests, _write_frame

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "00000", "000000", 0)
            _write_frame(root, "00001", "000000", 0)
            session = RuntimePlayerTests()._runtime(root)
            frame = session.frame_payload(0, budget=10, binary=True)
            self.assertIsInstance(frame["points"], np.ndarray)
            self.assertEqual(frame["points"].shape, (2, 3))


class BridgeLifecycleTests(unittest.TestCase):
    def test_hung_child_has_bounded_response_timeout_and_close(self):
        from viewer.runtime import PersistentMapEngine

        with tempfile.TemporaryDirectory() as raw:
            executable = Path(raw) / "hung.py"
            executable.write_text(
                "#!" + sys.executable + "\nimport time\ntime.sleep(60)\n"
            )
            executable.chmod(0o755)
            started = time.monotonic()
            engine = PersistentMapEngine(executable, timeout_s=0.1)
            result = engine.status()
            engine.close()
            self.assertEqual(result["status"], "unavailable")
            self.assertLess(time.monotonic() - started, 3)


class ProductServiceTests(unittest.TestCase):
    def test_unknown_command_does_not_change_runtime_state(self):
        from runtime.service import ProductRuntime

        service = ProductRuntime(Path.cwd())
        response = service.handle({"id": "bad", "command": "shell", "args": {}})
        self.assertFalse(response["ok"])
        self.assertEqual(response["status"]["state"], "unconfigured")
        service.close()

    def test_layer_command_is_safe_before_a_dataset_is_open(self):
        from runtime.service import ProductRuntime

        service = ProductRuntime(Path.cwd())
        response = service.handle(
            {"id": "layer", "command": "layer", "args": {"layer": "lod"}}
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["status"]["layer"], "lod")
        service.close()

    def test_metrics_command_returns_explicit_unavailable_state_before_frames(self):
        from runtime.service import ProductRuntime

        service = ProductRuntime(Path.cwd())
        response = service.handle({"id": "metrics", "command": "metrics", "args": {}})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["status"], "unavailable")
        service.close()

    def test_validation_requires_a_configured_real_session(self):
        from runtime.service import ProductRuntime

        service = ProductRuntime(Path.cwd())
        response = service.handle(
            {"id": "validation", "command": "validation", "args": {}}
        )
        self.assertFalse(response["ok"])
        self.assertIn("configure a dataset", response["error"]["message"])
        service.close()

    def test_real_dataset_playback_seek_policy_reset_and_visualization(self):
        from runtime.service import ProductRuntime
        from tests.test_runtime_player import _write_frame

        mapper = require_binary(self, "VEYRA_BENCHMARK_BINARY", BENCHMARK_RELATIVE)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(3):
                _write_frame(root, "00000", f"{index:06d}", index)
            service = ProductRuntime(Path.cwd())
            config = {
                "dataset": "rellis3d",
                "dataset_root": str(root),
                "sequence": "00000",
                "map": {
                    "executable": str(mapper),
                    "policy": "distance_lod",
                },
                "pipeline": {"semantic": {"mode": "ground_truth"}},
            }

            def call(command, **args):
                result = service.handle(
                    {"id": command, "command": command, "args": args}
                )
                self.assertTrue(result["ok"], result)
                return result

            try:
                self.assertEqual(
                    call("configure", config=config)["status"]["state"], "ready"
                )
                call("seek", index=2)
                self.assertEqual(service.status()["index"], 2)
                events = []
                while (event := service.outbox.take(timeout=0)) is not None:
                    events.append(event)
                visual = next(
                    event for event in events if event[0]["type"] == "visualization"
                )
                self.assertEqual(visual[0]["points"]["count"], 2)
                self.assertGreater(len(visual[1]), 0)
                self.assertEqual(visual[0]["layers"]["utility"], "available")
                self.assertEqual(visual[0]["cells"]["stride"], 68)
                call("policy", policy="uniform40")
                self.assertEqual(service.status()["policy"], "uniform40")
                self.assertEqual(service.status()["index"], -1)
                call("policy", policy="utility_lod")
                governor = call("governor", mode="disabled")["result"]["governor"]
                self.assertEqual(governor["state"], "disabled")
                call("step")
                self.assertEqual(service.status()["index"], 0)
                call("reset")
                self.assertEqual(service.status()["index"], -1)
                call("start")
                service.tick()
                call("pause")
                self.assertEqual(service.status()["state"], "paused")
            finally:
                service.close()

    def test_benchmark_respects_the_session_frame_limit_and_announces_its_artifact(
        self,
    ):
        import json

        from runtime.service import ProductRuntime
        from tests.test_runtime_player import _write_frame

        import os
        from unittest import mock

        mapper = require_binary(self, "VEYRA_BENCHMARK_BINARY", BENCHMARK_RELATIVE)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            # Never read or pollute the user's durable benchmark cache.
            isolate = mock.patch.dict(
                os.environ, {"VEYRA_BENCHMARK_CACHE_DIR": str(root / "cache")}
            )
            isolate.start()
            self.addCleanup(isolate.stop)
            for index in range(5):
                _write_frame(root, "00000", f"{index:06d}", index)
            service = ProductRuntime(Path.cwd())
            config = {
                "dataset": "rellis3d",
                "dataset_root": str(root),
                "sequence": "00000",
                "map": {"executable": str(mapper), "policy": "distance_lod"},
                "pipeline": {"semantic": {"mode": "ground_truth"}},
                "playback": {"frame_limit": 3, "full_sequence": False},
            }
            try:
                configured = service.handle(
                    {"id": "c", "command": "configure", "args": {"config": config}}
                )
                self.assertTrue(configured["ok"], configured)
                self.assertEqual(service.status()["frames"], 3)
                rejected = service.handle(
                    {"id": "b", "command": "benchmark", "args": {"count": 5}}
                )
                self.assertFalse(rejected["ok"])
                self.assertIn("provides 3", rejected["error"]["message"])
                self.assertIn("frame limit", rejected["error"]["message"])

                started = service.handle(
                    {
                        "id": "b",
                        "command": "benchmark",
                        "args": {"count": 3, "warmup_frames": 0},
                    }
                )
                self.assertTrue(started["ok"], started)
                deadline = time.monotonic() + 240
                completion = None
                while completion is None and time.monotonic() < deadline:
                    event = service.outbox.take(timeout=0.5)
                    if event and event[0].get("type") == "benchmark":
                        completion = event[0]
                self.assertIsNotNone(completion, "benchmark did not finish")
                self.assertEqual(completion["state"], "complete", completion)
                self.assertNotIn("report", completion)
                artifact = Path(completion["artifact"])
                self.assertEqual(artifact.stat().st_size, completion["artifact_bytes"])
                report = json.loads(artifact.read_text())
                self.assertEqual(report["provenance"]["frame_range"]["count"], 3)
                self.assertEqual(
                    report["quality_resource"]["same_input_for_all_policies"], True
                )
            finally:
                service.close()

    def test_real_semanticposs_frame_emits_nonempty_v2_visualization(self):
        from runtime.service import ProductRuntime

        root = Path(__file__).parents[1] / "data/raw/semanticposs/dataset"
        if not root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")
        mapper = require_binary(
            self, "VEYRA_MAPPER", "build/apps/runtime/veyra_runtime"
        )
        service = ProductRuntime(Path.cwd())
        config = {
            "dataset": "semanticposs",
            "dataset_root": str(root),
            "sequence": "00",
            "map": {"executable": str(mapper), "policy": "distance_lod"},
            "pipeline": {"semantic": {"mode": "ground_truth"}},
        }

        def call(command, **args):
            result = service.handle({"id": command, "command": command, "args": args})
            self.assertTrue(result["ok"], result)
            return result

        try:
            call("configure", config=config)
            call("step")
            events = []
            while (event := service.outbox.take(timeout=0)) is not None:
                events.append(event)
            visual = next(
                event for event in events if event[0]["type"] == "visualization"
            )
            metadata, payload = visual
            self.assertEqual(metadata["schema_version"], 3)
            self.assertGreater(metadata["points"]["count"], 0)
            self.assertGreater(metadata["cells"]["count"], 0)
            self.assertEqual(metadata["points"]["stride"], 68)
            self.assertEqual(metadata["cells"]["stride"], 68)
            self.assertEqual(
                metadata["physical_layers"]["offset"],
                metadata["points"]["count"] * 68 + metadata["cells"]["count"] * 68,
            )
            self.assertEqual(metadata["physical_layers"]["version"], 1)
            self.assertEqual(
                metadata["physical_layers"]["count"], metadata["cells"]["count"]
            )
            self.assertEqual(metadata["physical_layers"]["stride"], 60)
            self.assertEqual(
                len(payload),
                metadata["physical_layers"]["offset"]
                + metadata["physical_layers"]["count"] * 60,
            )
        finally:
            service.close()

    def test_benchmark_binary_prefers_staged_package_over_dev_build(self):
        import tempfile

        from runtime.service import ProductRuntime

        service = ProductRuntime(Path.cwd())
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staged = root / "staged" / "bin" / "veyra_benchmark"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"staged")
            fallback = (
                root / "repo" / "build" / "apps" / "benchmark" / "veyra_benchmark"
            )
            fallback.parent.mkdir(parents=True)
            fallback.write_bytes(b"dev")
            service.repo = root / "staged"
            self.assertEqual(service._benchmark_binary(), staged)
            staged.unlink()
            service.repo = root / "repo"
            self.assertEqual(service._benchmark_binary(), fallback)
            fallback.unlink()
            with self.assertRaisesRegex(ValueError, "not available"):
                service._benchmark_binary()
        service.close()
