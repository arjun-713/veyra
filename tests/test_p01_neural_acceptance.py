"""P0.1 neural acceptance coverage (gaps beyond the hermetic suite).

Covers what ``test_neural_demo_failclosed.py`` (PR #65) and
``test_perception_pipeline.py::CenetModeTests`` do NOT:

1. the approved neural config (``configs/perception-cenet-semantic.yaml``)
   selects CENet and keeps ground/terrain required;
2. the approved fail-closed config never silently falls back to
   ground_truth (``allow_fallback false`` raises);
3. a missing CENet dependency fails closed (ImportError path);
4. the MODEL (non-fallback) path discloses end-to-end
   (pipeline -> _serialize -> telemetry/pack_visualization);
5. the mapper protocol accepts neural output point-aligned
   (``frame_records`` / ``binary_frame_bytes`` count == N);
6. the normal runtime path (``ProductRuntime._process_locked``)
   preserves provider metadata and visualization layers;
7. pipeline output stays point-aligned and order-preserving.

Hermetic only: no dataset, no checkpoint, no torch, no real inference.
The CENet backend is a NumPy-only fake patched over the provider
constructor. The real YAML is read (never modified).
"""

import copy
import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np
import yaml

from datasets.common.observation import ObservationFrame, PoseSE3
from perception.pipeline import PerceptionConfigurationError, PerceptionPipeline
from perception.semantic import GroundTruthSemanticProvider, SemanticResult

REPO_ROOT = Path(__file__).resolve().parents[1]
APPROVED_CONFIG = REPO_ROOT / "configs" / "perception-cenet-semantic.yaml"


class FakeCENet:
    """NumPy-only, order-preserving stand-in for CENetSemanticProvider."""

    supported_datasets = frozenset({"semanticposs"})

    def __init__(self, checkpoint_path, *, threads=4):
        self.checkpoint_path = Path(checkpoint_path)
        self.threads = threads

    @property
    def execution_device(self):
        return "cpu"

    def infer(self, points, labels=None):
        del labels
        count = int(np.asarray(points).shape[0])
        classes = (np.arange(count, dtype=np.int32) % 14).astype(np.int32)
        confidence = np.full(count, 0.9, dtype=np.float32)
        return SemanticResult(classes, confidence, "model")


def _frame(dataset="semanticposs", count=5):
    points = np.zeros((count, 4), dtype=np.float32)
    points[:, 0] = np.arange(count, dtype=np.float32)
    points[:, 3] = 1.0
    return ObservationFrame(
        timestamp=2.0,
        pose=PoseSE3.identity(2.0),
        points=points,
        semantic_class=np.zeros(count, dtype=np.int32),
        semantic_confidence=np.zeros(count, dtype=np.float32),
        ground=np.zeros(count, dtype=bool),
        drivable=np.full(count, "unknown"),
        slope=np.full(count, np.nan, dtype=np.float32),
        roughness=np.full(count, np.nan, dtype=np.float32),
        height_complexity=np.full(count, np.nan, dtype=np.float32),
        motion_probability=np.zeros(count, dtype=np.float32),
        velocity_xy=np.zeros((count, 2), dtype=np.float32),
        instance_id=np.arange(count, dtype=np.int32),
        dataset=dataset,
        sequence="00",
        frame_id="000007",
    )


def _approved_config(checkpoint, *, allow_fallback=False, drop_sha=True):
    """Load the real approved YAML, repointed at a hermetic checkpoint."""
    config = yaml.safe_load(APPROVED_CONFIG.read_text())
    config = copy.deepcopy(config)
    config["semantic"]["checkpoint"] = str(checkpoint)
    config["semantic"]["allow_fallback_to_ground_truth"] = allow_fallback
    if drop_sha:
        config["semantic"].pop("checkpoint_sha256", None)
    return config


def _clear_env():
    return mock.patch.dict(os.environ, {}, clear=False)


def _model_pipeline(checkpoint_path):
    """Approved-config-derived pipeline with the fake neural backend."""
    with _clear_env():
        os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
        with mock.patch("perception.semantic.cenet.CENetSemanticProvider", FakeCENet):
            return PerceptionPipeline.from_config(_approved_config(checkpoint_path))


class ApprovedConfigTests(unittest.TestCase):
    """The approved neural config selects CENet, fail-closed, ground+terrain."""

    def test_approved_yaml_shape_is_failclosed_cenet_with_required_stages(self):
        config = yaml.safe_load(APPROVED_CONFIG.read_text())
        semantic = config["semantic"]
        self.assertEqual(semantic["mode"], "cenet")
        self.assertIs(semantic["allow_fallback_to_ground_truth"], False)
        self.assertTrue(config["ground"]["enabled"])
        self.assertTrue(config["terrain"]["enabled"])
        self.assertEqual(
            list(config["required_stages"]), ["semantic", "ground", "terrain"]
        )
        self.assertTrue(str(semantic["checkpoint"]).strip())
        self.assertTrue(str(semantic.get("checkpoint_sha256") or "").strip())

    def test_approved_config_missing_weights_raises_never_silent_gt(self):
        with _clear_env():
            os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
            with self.assertRaises(PerceptionConfigurationError):
                PerceptionPipeline.from_config(
                    _approved_config("/nonexistent/cenet-weights.bin")
                )

    def test_approved_config_selects_cenet_provider(self):
        # The factory target exists (not a renamed/moved symbol).
        from perception.semantic.cenet import CENetSemanticProvider

        self.assertEqual(
            CENetSemanticProvider.supported_datasets, frozenset({"semanticposs"})
        )
        with TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            with _clear_env():
                os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
                with mock.patch(
                    "perception.semantic.cenet.CENetSemanticProvider", FakeCENet
                ):
                    pipeline = PerceptionPipeline.from_config(_approved_config(weights))
        self.assertIsInstance(pipeline.semantic_provider, FakeCENet)
        self.assertEqual(pipeline.semantic_requested_mode, "cenet")
        self.assertIsNone(pipeline.semantic_fallback_reason)
        self.assertEqual(pipeline.semantic_model_identity, str(weights))
        self.assertEqual(
            pipeline.semantic_required_datasets, frozenset({"semanticposs"})
        )

    def test_approved_config_keeps_ground_terrain_required(self):
        with TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            pipeline = _model_pipeline(weights)
        # Construction is the production path (from_config); sensor backends
        # stay lazy so no binding is needed to assert they remain enabled.
        self.assertIsNotNone(pipeline.ground_segmenter)
        self.assertIsNotNone(pipeline.terrain_analyzer)
        self.assertTrue(pipeline._ground_enabled)
        self.assertTrue(pipeline._terrain_enabled)
        self.assertEqual(
            tuple(pipeline.required_stages), ("semantic", "ground", "terrain")
        )


class MissingDependencyTests(unittest.TestCase):
    """Absent torch/CENet module fails closed, never silent GT."""

    def _config_with_weights(self, directory):
        weights = Path(directory) / "mock-weights.bin"
        weights.write_bytes(b"mock-cenet-weights")
        return _approved_config(weights)

    def test_missing_dependency_without_flag_raises(self):
        with TemporaryDirectory() as directory:
            with _clear_env():
                os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
                with mock.patch.dict(
                    "sys.modules", {"perception.semantic.cenet": None}
                ):
                    with self.assertRaises(PerceptionConfigurationError):
                        PerceptionPipeline.from_config(
                            self._config_with_weights(directory)
                        )

    def test_missing_dependency_with_flag_is_disclosed_gt(self):
        with TemporaryDirectory() as directory:
            with _clear_env():
                os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
                with mock.patch.dict(
                    "sys.modules", {"perception.semantic.cenet": None}
                ):
                    config = self._config_with_weights(directory)
                    config["semantic"]["allow_fallback_to_ground_truth"] = True
                    pipeline = PerceptionPipeline.from_config(config)
        self.assertIsInstance(pipeline.semantic_provider, GroundTruthSemanticProvider)
        self.assertIsNone(pipeline.semantic_model_identity)
        self.assertTrue((pipeline.semantic_fallback_reason or "").strip())
        output = pipeline.process(_frame())
        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertIsNone(output.status.semantic_model)


class ModelDisclosureTests(unittest.TestCase):
    """Non-fallback neural output discloses end-to-end (actual wins)."""

    def test_model_path_pipeline_serialize_telemetry(self):
        from runtime.telemetry import Telemetry
        from viewer.runtime import RuntimeSession

        with TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            pipeline = _model_pipeline(weights)
            output = pipeline.process(_frame())

        # 1. Pipeline status: actual model, verified identity + device.
        self.assertEqual(output.status.semantic, "model")
        self.assertEqual(output.status.semantic_requested, "cenet")
        self.assertEqual(output.status.semantic_model, str(weights))
        self.assertEqual(output.status.semantic_execution, "cpu")
        self.assertIsNone(output.status.semantic_fallback_reason)

        # 2. Viewer serializer forwards the model status unchanged.
        session = RuntimeSession.__new__(RuntimeSession)
        session.dataset = "semanticposs"
        session.sequence = "00"
        session.min_range_m = 0.0
        session.max_range_m = None
        session._frames = [object()]
        session.adapter = type("StubAdapter", (), {})()
        payload = session._serialize(output, 0, 10, {"status": "available"})
        self.assertEqual(payload["pipeline_status"]["semantic"], "model")
        self.assertEqual(payload["pipeline_status"]["semantic_model"], str(weights))
        self.assertEqual(payload["pipeline_status"]["semantic_execution"], "cpu")

        # 3. Telemetry derives from actual: model identity + cpu survive,
        # never "Ground Truth".
        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 10,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "n_points": 5,
                "semantic_labels": [0, 1, 2, 3, 4],
                "pipeline_status": dict(payload["pipeline_status"]),
            },
            None,
            None,
            {"mode": "cenet", "provider": "cenet", "checkpoint": str(weights)},
        )
        perception = report["perception"]
        self.assertNotEqual(perception["provider"], "Ground Truth")
        self.assertEqual(perception["model"], str(weights))
        self.assertEqual(perception["execution_provider"], "cpu")
        self.assertEqual(perception["backend"], "model")
        self.assertEqual(perception["semantic_actual"], "model")
        self.assertEqual(perception["semantic_requested"], "cenet")

        # 4. Visualization layers carry the neural status + full provenance.
        from runtime.visualization import pack_visualization

        metadata, _ = pack_visualization(
            payload,
            {"status": "available", "cells_binary": b"", "total_leaves": 0},
            0,
        )
        self.assertEqual(metadata["layers"]["semantic"], "model")
        self.assertEqual(metadata["pipeline_status"]["semantic"], "model")
        self.assertEqual(metadata["pipeline_status"]["semantic_model"], str(weights))


class MapperAlignmentTests(unittest.TestCase):
    """Neural output reaches the mapper point-aligned (in == out, ordered)."""

    def test_neural_output_encodes_point_aligned_for_mapper(self):
        from benchmarks.protocol import binary_frame_bytes, frame_records

        with TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            pipeline = _model_pipeline(weights)
        count = 5
        output = pipeline.process(_frame(count=count))
        frame = output.frame

        # Pipeline output is point-aligned with the input.
        self.assertEqual(frame.points.shape[0], count)
        for name in (
            "semantic_class",
            "semantic_confidence",
            "ground",
            "drivable",
            "observation_quality",
        ):
            self.assertEqual(
                np.asarray(getattr(frame, name)).reshape(-1).shape,
                (count,),
                f"{name} must contain one value per point",
            )
        # Order preserved: fake emits arange % 14, output must match exactly.
        np.testing.assert_array_equal(
            frame.semantic_class, np.arange(count, dtype=np.int32) % 14
        )

        # Mapper text protocol: F header + N point records + E trailer
        # (strict zip raises on any misaligned field).
        records = frame_records(frame)
        self.assertEqual(len(records), count + 2)
        self.assertTrue(records[0].startswith("F "))
        self.assertTrue(all(line.startswith("P ") for line in records[1:-1]))
        self.assertEqual(records[-1], "E\n")

        # Mapper binary protocol: point count header matches neural output.
        import struct

        blob = binary_frame_bytes(frame)
        header_line, _ = blob.split(b"\n", 1)
        self.assertEqual(header_line, f"B {count}".encode("ascii"))
        header = blob[len(header_line) + 1 : len(header_line) + 1 + 152]
        _stamp_in, _stamp_pose, _source, *_pose = struct.unpack("<QQQ16d", header)
        self.assertEqual(int(header_line.split()[1]), count)


class RuntimePreservationTests(unittest.TestCase):
    """Normal runtime path preserves provider metadata (service + layers)."""

    @staticmethod
    def _payload():
        from viewer.runtime import RuntimeSession

        with TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            pipeline = _model_pipeline(weights)
            output = pipeline.process(_frame())
        session = RuntimeSession.__new__(RuntimeSession)
        session.dataset = "semanticposs"
        session.sequence = "00"
        session.min_range_m = 0.0
        session.max_range_m = None
        session._frames = [object()]
        session.adapter = type("StubAdapter", (), {})()
        payload = session._serialize(
            output, 0, 10, {"status": "available"}, binary=True
        )
        return payload, str(weights)

    def _runtime(self, payload, checkpoint, *, allow_fallback):
        from runtime.service import ProductRuntime
        from runtime.telemetry import Telemetry

        class StubMapRunner:
            pid = 1234

        class StubSession:
            def __init__(self, frame_payload):
                self._frame_payload = frame_payload
                self.map_runner = StubMapRunner()

            def frame_payload(self, target, budget, binary=False):
                del target, budget, binary
                return self._frame_payload

            def status(self):
                return {"frames": 1}

            def map_cells_binary(self, budget):
                del budget
                return {
                    "status": "available",
                    "cells_binary": b"",
                    "total_leaves": 0,
                    "cell_count": 0,
                }

        class RecordingOutbox:
            def __init__(self):
                self.messages = []
                self.visualization_dropped = 0

            def publish(self, *args):
                self.messages.append(args)

        runtime = ProductRuntime.__new__(ProductRuntime)
        runtime.session = StubSession(payload)
        runtime.config = {
            "dataset": "semanticposs",
            "sequence": "00",
            "pipeline": {
                "semantic": {
                    "mode": "cenet",
                    "checkpoint": checkpoint,
                    "allow_fallback_to_ground_truth": allow_fallback,
                }
            },
            "visualization": {
                "point_budget": 100,
                "cell_budget": 100,
                "update_hz": 2,
            },
            "playback": {"speed": 1},
            "map": {"policy": "distance_lod"},
        }
        runtime.state = "ready"
        runtime.layer = "semantic"
        runtime.index = -1
        runtime.generation = 0
        runtime.error = None
        runtime.dropped_frames = 0
        runtime.telemetry = Telemetry()
        runtime.last_telemetry = None
        runtime.last_visual = 0.0
        runtime.outbox = RecordingOutbox()
        runtime.commands = queue.Queue()
        runtime._status_lock = threading.Lock()
        runtime._frame_in_flight = threading.Lock()
        runtime._cached_status = {}
        runtime._artifacts = tempfile.TemporaryDirectory(prefix="veyra-test-")
        self.addCleanup(runtime._artifacts.cleanup)
        return runtime

    def test_process_locked_preserves_model_metadata(self):
        payload, checkpoint = self._payload()
        runtime = self._runtime(payload, checkpoint, allow_fallback=False)
        runtime._process_locked(0, force_visual=True)

        visuals = [
            args[0]
            for args in runtime.outbox.messages
            if args and isinstance(args[0], dict) and "layers" in args[0]
        ]
        self.assertTrue(visuals, "expected a visualization message")
        metadata = visuals[-1]
        self.assertEqual(metadata["layers"]["semantic"], "model")
        self.assertEqual(metadata["pipeline_status"]["semantic"], "model")
        self.assertEqual(metadata["pipeline_status"]["semantic_model"], checkpoint)
        self.assertEqual(metadata["pipeline_status"]["semantic_execution"], "cpu")

        telemetry = runtime.last_telemetry
        self.assertIsNotNone(telemetry)
        self.assertEqual(telemetry["perception"]["semantic_actual"], "model")
        self.assertEqual(telemetry["perception"]["model"], checkpoint)
        self.assertEqual(telemetry["perception"]["execution_provider"], "cpu")
        self.assertNotEqual(telemetry["perception"]["provider"], "Ground Truth")

    def test_process_locked_rejects_unapproved_fallback(self):
        payload, checkpoint = self._payload()
        payload = copy.deepcopy(payload)
        payload["pipeline_status"]["semantic"] = "ground_truth"
        payload["pipeline_status"]["semantic_execution"] = "bypassed"
        payload["pipeline_status"]["semantic_model"] = None
        payload["pipeline_status"]["semantic_fallback_reason"] = (
            "mode 'cenet' requested but weights absent"
        )
        runtime = self._runtime(payload, checkpoint, allow_fallback=False)
        with self.assertRaisesRegex(RuntimeError, "allow_fallback_to_ground_truth"):
            runtime._process_locked(0, force_visual=True)


if __name__ == "__main__":
    unittest.main()
