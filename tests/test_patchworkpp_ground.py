import importlib.util
import time
import unittest
from pathlib import Path

import numpy as np

from perception.ground.patchworkpp import (
    GroundEvidence,
    PatchworkPPGroundSegmenter,
    PatchworkPPUnavailableError,
)


class GroundEvidenceTests(unittest.TestCase):
    def test_evidence_is_point_aligned_and_preserves_backend_metadata(self):
        evidence = GroundEvidence(
            mask=np.array([True, False, True]),
            confidence=np.array([0.9, 0.1, 1.0], dtype=np.float32),
            backend="test-backend",
        )

        self.assertEqual(evidence.mask.shape, (3,))
        self.assertEqual(evidence.confidence.shape, (3,))
        self.assertEqual(evidence.backend, "test-backend")

    def test_evidence_rejects_misaligned_outputs(self):
        with self.assertRaises(ValueError):
            GroundEvidence(
                mask=np.array([True, False]),
                confidence=np.array([0.5]),
                backend="test-backend",
            )

    def test_official_binding_api_is_used(self):
        class Parameters:
            pass

        class Backend:
            def __init__(self, params):
                self.params = params
                self.points = None

            def estimateGround(self, points):
                self.points = points

            def getGroundIndices(self):
                return [0, 2]

        segmenter = PatchworkPPGroundSegmenter(module_names=("fake",))
        import sys
        import types

        module = types.ModuleType("fake")
        module.Parameters = Parameters
        module.patchworkpp = Backend
        sys.modules["fake"] = module
        evidence = segmenter.segment(np.zeros((3, 4), dtype=np.float32))
        np.testing.assert_array_equal(evidence.mask, [True, False, True])


class PatchworkPPGroundSegmenterTests(unittest.TestCase):
    def test_availability_reports_a_fail_closed_diagnostic(self):
        availability = PatchworkPPGroundSegmenter(
            module_names=("module-that-is-not-installed",)
        ).availability()

        self.assertFalse(availability.available)
        self.assertIn("module-that-is-not-installed", availability.diagnostic)

    @unittest.skipUnless(
        importlib.util.find_spec("pypatchworkpp"),
        "optional pypatchworkpp dependency is not installed",
    )
    def test_installed_official_backend_smoke(self):
        points = np.column_stack(
            (
                np.linspace(1.0, 30.0, 2048),
                np.zeros(2048),
                np.zeros(2048),
                np.ones(2048),
            )
        ).astype(np.float32)
        evidence = PatchworkPPGroundSegmenter().segment(points)
        self.assertEqual(evidence.mask.shape, (2048,))
        self.assertEqual(evidence.backend, "pypatchworkpp.patchworkpp")

    def test_missing_backend_has_actionable_error(self):
        segmenter = PatchworkPPGroundSegmenter(
            module_names=("module-that-is-not-installed",),
            executable_names=(),
        )

        with self.assertRaises(PatchworkPPUnavailableError) as context:
            segmenter.segment(np.zeros((2, 4), dtype=np.float32))

        self.assertIn("Patchwork++", str(context.exception))
        self.assertIn("module-that-is-not-installed", str(context.exception))

    def test_real_rellis_frame_executes_patchworkpp_on_cpu(self):
        if not importlib.util.find_spec("pypatchworkpp"):
            self.skipTest("requires pypatchworkpp for real RELLIS smoke test")

        from datasets.rellis import Rellis3DDataset

        dataset = Rellis3DDataset(
            Path("data/raw/rellis3d/Rellis-3D"), sequences=["00000"]
        )
        frame = dataset.load_frame("00000", dataset.list_frames("00000")[0].frame_id)

        started = time.perf_counter()
        evidence = PatchworkPPGroundSegmenter().segment(frame.points)
        elapsed_s = time.perf_counter() - started

        self.assertEqual(evidence.mask.shape, (frame.points.shape[0],))
        self.assertEqual(evidence.confidence.shape, evidence.mask.shape)
        self.assertTrue(np.all(np.isfinite(evidence.confidence)))
        ground_ratio = float(np.mean(evidence.mask))
        self.assertGreater(ground_ratio, 0.001)
        self.assertLess(ground_ratio, 0.999)
        self.assertGreater(elapsed_s, 0.0)
        print(
            "real RELLIS Patchwork++: "
            f"points={frame.points.shape[0]} ground_ratio={ground_ratio:.4f} "
            f"elapsed_s={elapsed_s:.6f}"
        )


if __name__ == "__main__":
    unittest.main()
