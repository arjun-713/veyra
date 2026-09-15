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
from perception.ground.quality import (
    aggregate_ground_quality_reports,
    ground_quality_report,
)


class GroundEvidenceTests(unittest.TestCase):
    def test_ground_quality_report_is_explicit_for_binary_predictions(self):
        report = ground_quality_report(
            np.array([True, True, False, False]),
            np.array([True, False, False, True]),
        )

        self.assertEqual(report["evaluated_points"], 4)
        self.assertEqual(report["true_positive"], 1)
        self.assertEqual(report["false_positive"], 1)
        self.assertEqual(report["false_negative"], 1)
        self.assertAlmostEqual(report["precision"], 0.5)
        self.assertAlmostEqual(report["recall"], 0.5)
        self.assertAlmostEqual(report["f1"], 0.5)
        self.assertAlmostEqual(report["iou"], 1 / 3)

    def test_ground_quality_rejects_misaligned_masks(self):
        with self.assertRaises(ValueError):
            ground_quality_report(np.array([True]), np.array([True, False]))

    def test_ground_quality_aggregation_uses_micro_counts(self):
        report = aggregate_ground_quality_reports(
            [
                ground_quality_report([True, False], [True, False]),
                ground_quality_report([False, False, True], [True, False, False]),
            ]
        )

        self.assertEqual(report["evaluated_points"], 5)
        self.assertEqual(report["true_positive"], 1)
        self.assertEqual(report["false_negative"], 1)
        self.assertAlmostEqual(report["recall"], 0.5)

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

    def test_parameter_overrides_are_applied_to_official_binding(self):
        class Parameters:
            max_range = 80.0
            min_range = 2.7

        class Backend:
            def __init__(self, params):
                self.params = params

            def estimateGround(self, points):
                del points

            def getGroundIndices(self):
                return [0]

        import sys
        import types

        module = types.ModuleType("fake_parameters")
        module.Parameters = Parameters
        module.patchworkpp = Backend
        sys.modules["fake_parameters"] = module
        segmenter = PatchworkPPGroundSegmenter(
            module_names=("fake_parameters",),
            parameter_overrides={"max_range": 100.0, "min_range": 0.0},
        )

        segmenter.segment(np.zeros((1, 4), dtype=np.float32))

        self.assertEqual(segmenter._binding.params.max_range, 100.0)
        self.assertEqual(segmenter._binding.params.min_range, 0.0)

    def test_unknown_parameter_is_a_configuration_error(self):
        class Parameters:
            max_range = 80.0

        class Backend:
            def __init__(self, params):
                del params

            def estimateGround(self, points):
                del points

            def getGroundIndices(self):
                return []

        import sys
        import types

        module = types.ModuleType("fake_invalid_parameters")
        module.Parameters = Parameters
        module.patchworkpp = Backend
        sys.modules["fake_invalid_parameters"] = module

        with self.assertRaisesRegex(ValueError, "not supported"):
            PatchworkPPGroundSegmenter(
                module_names=("fake_invalid_parameters",),
                parameter_overrides={"not_a_parameter": 1},
            ).segment(np.zeros((1, 4), dtype=np.float32))


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

        dataset_root = Path("data/raw/rellis3d/Rellis-3D")
        if not dataset_root.is_dir():
            self.skipTest("original local RELLIS-3D data is unavailable")

        from datasets.rellis import Rellis3DDataset

        dataset = Rellis3DDataset(dataset_root, sequences=["00000"])
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

    def test_real_semanticposs_ground_quality_is_measurable(self):
        if not importlib.util.find_spec("pypatchworkpp"):
            self.skipTest("requires pypatchworkpp for real SemanticPOSS validation")
        dataset_root = Path("data/raw/semanticposs/dataset")
        if not dataset_root.is_dir():
            self.skipTest("original local SemanticPOSS data is unavailable")

        from datasets.semanticposs import SemanticPOSSDataset

        reports = []
        dataset = SemanticPOSSDataset(dataset_root, sequences=["00"])
        segmenter = PatchworkPPGroundSegmenter(
            parameter_overrides={"min_range": 0.0, "max_range": 100.0}
        )
        for frame in dataset.replay("00", end=3, max_range_m=100.0):
            sensor = frame.points.copy()
            sensor[:, :3] = (
                sensor[:, :3] - frame.pose.matrix[:3, 3]
            ) @ frame.pose.matrix[:3, :3]
            evidence = segmenter.segment(sensor)
            reports.append(
                ground_quality_report(evidence.mask, frame.raw_semantic_class == 22)
            )

        aggregate = aggregate_ground_quality_reports(reports)
        self.assertGreater(aggregate["recall"], 0.85)
        self.assertGreater(aggregate["precision"], 0.65)
        self.assertGreater(aggregate["f1"], 0.75)
        print(
            "real SemanticPOSS Patchwork++ ground quality: "
            f"frames={aggregate['frames']} precision={aggregate['precision']:.4f} "
            f"recall={aggregate['recall']:.4f} f1={aggregate['f1']:.4f} "
            f"iou={aggregate['iou']:.4f}"
        )


if __name__ == "__main__":
    unittest.main()
