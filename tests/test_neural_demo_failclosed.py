"""Fail-closed neural-demo regression (issue #53).

Hermetic only: no dataset, no checkpoint, no torch, no real inference.
The CENet backend is a NumPy-only fake patched over the provider
constructor. Nothing here may touch production files, configs, or data/.
"""

import os
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np

from datasets.common.observation import ObservationFrame, PoseSE3
from perception.pipeline import PerceptionConfigurationError, PerceptionPipeline
from perception.semantic import GroundTruthSemanticProvider, SemanticResult


class FakeCENet:
    """NumPy-only stand-in for CENetSemanticProvider (mock weights only)."""

    supported_datasets = frozenset({"semanticposs"})

    def __init__(self, checkpoint_path, *, threads=4):
        self.checkpoint_path = Path(checkpoint_path)
        self.threads = threads
        self.inference_calls = 0

    @property
    def execution_device(self):
        # Verified device of this fake backend: CPU torch by contract.
        return "cpu"

    def infer(self, points, labels=None):
        del labels
        points_array = np.asarray(points, dtype=np.float32)
        if (
            points_array.ndim != 2
            or points_array.shape[1] != 4
            or not np.all(np.isfinite(points_array))
        ):
            raise ValueError("FakeCENet requires finite XYZI (N, 4)")
        self.inference_calls += 1
        count = points_array.shape[0]
        # Deterministic mix that always includes unknown (class 0) so the
        # class-0 -> 0.0 confidence contract is exercised every run.
        classes = np.arange(count, dtype=np.int32) % 3
        confidence = np.where(classes == 0, 0.99, 0.9).astype(np.float32)
        return SemanticResult(classes, confidence, "model")


def _base_config(semantic):
    return {
        "semantic": semantic,
        "ground": {"enabled": False},
        "terrain": {"enabled": False},
        "temporal": {"enabled": False},
    }


def _frame(dataset="semanticposs", count=3):
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
        frame_id="000000",
    )


def _clear_env():
    return mock.patch.dict(os.environ, {}, clear=False)


class MissingModelMasqueradeTests(unittest.TestCase):
    """mode cenet + bad checkpoint + no flag must raise, never masquerade."""

    def test_missing_checkpoint_without_flag_raises(self):
        with _clear_env():
            os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
            with self.assertRaises(PerceptionConfigurationError):
                PerceptionPipeline.from_config(
                    _base_config(
                        {
                            "mode": "cenet",
                            "checkpoint": "/nonexistent/cenet-weights.bin",
                        }
                    )
                )


class DisclosedFallbackTests(unittest.TestCase):
    """Same failure + explicit allow_fallback_to_ground_truth:true is GT."""

    def test_explicit_flag_falls_back_with_provenance(self):
        with _clear_env():
            os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
            pipeline = PerceptionPipeline.from_config(
                _base_config(
                    {
                        "mode": "cenet",
                        "checkpoint": "/nonexistent/cenet-weights.bin",
                        "allow_fallback_to_ground_truth": True,
                    }
                )
            )

        # Provider is ground truth; no neural model handle is retained.
        self.assertIsInstance(pipeline.semantic_provider, GroundTruthSemanticProvider)
        self.assertIsNone(getattr(pipeline, "semantic_model", None))
        self.assertIsNone(pipeline.semantic_model_identity)
        # Requested vs actual stay distinct.
        self.assertEqual(pipeline.semantic_requested_mode, "cenet")
        self.assertIsNotNone(pipeline.semantic_fallback_reason)
        self.assertTrue(pipeline.semantic_fallback_reason.strip())
        # Truthful exec: GT bypasses neural inference by construction.
        self.assertEqual(pipeline._provider_execution_device(), "bypassed")

        output = pipeline.process(_frame(dataset="semanticposs"))

        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertEqual(output.status.semantic_execution, "bypassed")
        self.assertTrue(
            any(
                "cenet" in diagnostic and "ground_truth" in diagnostic
                for diagnostic in output.status.diagnostics
            )
        )


class IncompatibleDatasetTests(unittest.TestCase):
    """Dataset gate holds even with the fallback flag (mock weights only)."""

    def test_cenet_gate_rejects_wrong_dataset_despite_fallback_flag(self):
        with TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            with (
                mock.patch.dict(os.environ, {"VEYRA_CENET_CHECKPOINT": str(weights)}),
                mock.patch(
                    "perception.semantic.cenet.CENetSemanticProvider", FakeCENet
                ),
            ):
                pipeline = PerceptionPipeline.from_config(
                    _base_config(
                        {
                            "mode": "cenet",
                            "checkpoint": "/mock/config.bin",
                            "allow_fallback_to_ground_truth": True,
                        }
                    )
                )
                self.assertIsInstance(pipeline.semantic_provider, FakeCENet)
                # Control: supported dataset runs.
                ok = pipeline.process(_frame(dataset="semanticposs"))
                self.assertEqual(ok.status.semantic, "model")
                calls = pipeline.semantic_provider.inference_calls
                # Incompatible dataset fails closed before inference.
                with self.assertRaises(PerceptionConfigurationError):
                    pipeline.process(replace(_frame(dataset="semantickitti")))
                self.assertEqual(pipeline.semantic_provider.inference_calls, calls)

    def test_fallback_pipeline_still_rejects_wrong_dataset(self):
        with _clear_env():
            os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
            pipeline = PerceptionPipeline.from_config(
                _base_config(
                    {
                        "mode": "cenet",
                        "checkpoint": "/nonexistent/cenet-weights.bin",
                        "allow_fallback_to_ground_truth": True,
                    }
                )
            )
        with self.assertRaises(PerceptionConfigurationError):
            pipeline.process(replace(_frame(dataset="semantickitti")))


class RequestedVsActualTests(unittest.TestCase):
    """Requested vs actual stay explicit end-to-end; provider from actual."""

    def test_fallback_provenance_survives_status_serialize_telemetry(self):
        from runtime.telemetry import Telemetry

        with _clear_env():
            os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
            pipeline = PerceptionPipeline.from_config(
                _base_config(
                    {
                        "mode": "cenet",
                        "checkpoint": "/nonexistent/cenet-weights.bin",
                        "allow_fallback_to_ground_truth": True,
                    }
                )
            )
        output = pipeline.process(_frame(dataset="semanticposs"))

        # 1. Pipeline status carries the actual backend, requested kept apart.
        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertEqual(pipeline.semantic_requested_mode, "cenet")
        self.assertNotEqual(output.status.semantic, pipeline.semantic_requested_mode)
        self.assertEqual(output.status.semantic_requested, "cenet")
        self.assertIsNone(output.status.semantic_model)
        self.assertTrue((output.status.semantic_fallback_reason or "").strip())

        # 2. Viewer serializer forwards the actual status unchanged.
        from viewer.runtime import RuntimeSession

        session = RuntimeSession.__new__(RuntimeSession)
        session.dataset = "semanticposs"
        session.sequence = "00"
        session.min_range_m = 0.0
        session.max_range_m = None
        session._frames = [object()]
        session.adapter = type("StubAdapter", (), {})()
        payload = session._serialize(output, 0, 10, {"status": "available"})
        self.assertEqual(payload["pipeline_status"]["semantic"], "ground_truth")
        self.assertEqual(payload["pipeline_status"]["semantic_execution"], "bypassed")
        self.assertEqual(payload["pipeline_status"]["semantic_requested"], "cenet")
        self.assertIsNone(payload["pipeline_status"]["semantic_model"])
        self.assertTrue(
            (payload["pipeline_status"]["semantic_fallback_reason"] or "").strip()
        )
        self.assertTrue(
            any(
                "cenet" in diagnostic and "ground_truth" in diagnostic
                for diagnostic in payload["pipeline_status"]["diagnostics"]
            )
        )

        # 3. Telemetry provider derives from the actual status, not the
        # requested config: requested cenet + actual ground_truth reads
        # "Ground Truth", never "cenet".
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
                "n_points": 3,
                "semantic_labels": [0, 1, 0],
                "pipeline_status": dict(payload["pipeline_status"]),
            },
            None,
            None,
            {"mode": "cenet", "provider": "cenet"},
        )
        self.assertEqual(report["perception"]["provider"], "Ground Truth")
        self.assertEqual(report["perception"]["execution_provider"], "bypassed")
        self.assertEqual(report["perception"]["backend"], "ground_truth")
        self.assertEqual(report["perception"]["semantic_requested"], "cenet")
        self.assertEqual(report["perception"]["semantic_actual"], "ground_truth")
        self.assertTrue(
            (report["perception"]["semantic_fallback_reason"] or "").strip()
        )


class TruthfulExecTests(unittest.TestCase):
    """Execution device is verified from the running provider (mock only)."""

    def test_fake_cenet_reports_cpu(self):
        with TemporaryDirectory() as directory:
            weights = Path(directory) / "mock-weights.bin"
            weights.write_bytes(b"mock-cenet-weights")
            with (
                mock.patch.dict(os.environ, {"VEYRA_CENET_CHECKPOINT": str(weights)}),
                mock.patch(
                    "perception.semantic.cenet.CENetSemanticProvider", FakeCENet
                ),
            ):
                pipeline = PerceptionPipeline.from_config(
                    _base_config({"mode": "cenet", "checkpoint": "/mock/x.bin"})
                )
        self.assertEqual(pipeline._provider_execution_device(), "cpu")
        output = pipeline.process(_frame(dataset="semanticposs"))
        self.assertEqual(output.status.semantic_execution, "cpu")

    def test_ground_truth_reports_bypassed(self):
        pipeline = PerceptionPipeline.from_config(
            _base_config({"mode": "ground_truth"})
        )
        self.assertEqual(pipeline._provider_execution_device(), "bypassed")


class TelemetryModelFailClosedTests(unittest.TestCase):
    """Review point 7 / issue #53: telemetry model is verified identity only.

    CENet config with checkpoint + allow_fallback, missing weights ->
    fallback. telemetry.perception.model must stay None/unavailable (never
    the configured checkpoint); the checkpoint may survive only under
    requested_model; fallback reason stays explicit.
    """

    def test_fallback_telemetry_model_never_refills_config_checkpoint(self):
        from runtime.telemetry import Telemetry

        checkpoint = "/nonexistent/cenet-weights.bin"
        with _clear_env():
            os.environ.pop("VEYRA_CENET_CHECKPOINT", None)
            pipeline = PerceptionPipeline.from_config(
                _base_config(
                    {
                        "mode": "cenet",
                        "checkpoint": checkpoint,
                        "allow_fallback_to_ground_truth": True,
                    }
                )
            )
        output = pipeline.process(_frame(dataset="semanticposs"))
        self.assertEqual(output.status.semantic, "ground_truth")
        self.assertIsNone(output.status.semantic_model)

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
                "n_points": 3,
                "semantic_labels": [0, 1, 0],
                "pipeline_status": {
                    "semantic": output.status.semantic,
                    "semantic_requested": output.status.semantic_requested,
                    "semantic_model": output.status.semantic_model,
                    "semantic_execution": output.status.semantic_execution,
                    "semantic_fallback_reason": output.status.semantic_fallback_reason,
                },
            },
            None,
            None,
            {"mode": "cenet", "provider": "cenet", "checkpoint": checkpoint},
        )
        perception = report["perception"]
        self.assertIn(perception["model"], (None, "unavailable"))
        self.assertNotEqual(perception["model"], checkpoint)
        self.assertTrue((perception["semantic_fallback_reason"] or "").strip())
        self.assertEqual(perception["requested_model"], checkpoint)
        self.assertEqual(perception["semantic_actual"], "ground_truth")
        self.assertEqual(perception["provider"], "Ground Truth")


class AlignmentConfidenceTests(unittest.TestCase):
    """FakeCENet stays N-aligned with finite [0,1] conf; class 0 -> 0.0."""

    def test_synthetic_points_aligned_finite_unknown_zero(self):
        rng = np.random.RandomState(7)
        count = 9
        points = rng.uniform(-30, 30, size=(count, 4)).astype(np.float32)
        points[:, 3] = rng.uniform(0, 255, size=count).astype(np.float32)
        self.assertTrue(bool(np.all(np.isfinite(points))))

        result = FakeCENet("/mock/weights.bin").infer(points)

        self.assertEqual(result.semantic_class.shape, (count,))
        self.assertEqual(result.semantic_confidence.shape, (count,))
        self.assertTrue(bool(np.all(np.isfinite(result.semantic_confidence))))
        self.assertTrue(
            bool(
                (
                    (result.semantic_confidence >= 0.0)
                    & (result.semantic_confidence <= 1.0)
                ).all()
            )
        )
        unknown = result.semantic_class == 0
        self.assertGreater(int(unknown.sum()), 0)
        np.testing.assert_array_equal(
            result.semantic_confidence[unknown],
            np.zeros(int(unknown.sum()), dtype=np.float32),
        )


if __name__ == "__main__":
    unittest.main()
