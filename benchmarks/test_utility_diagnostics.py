"""Exercise bounded production-policy diagnostics through the real executable."""

import json
import subprocess
import sys
import unittest
from dataclasses import replace

from benchmarks.protocol import stream_bytes
from benchmarks.test_runtime import frame
from tests.test_engine_service import require_binary


class UtilityDiagnosticsTests(unittest.TestCase):
    def test_native_pipeline_logs_do_not_contaminate_json_stdout(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json, os; "
                    "from benchmarks.utility_diagnostics import pipeline_logs_to_stderr; "
                    "\nwith pipeline_logs_to_stderr():\n"
                    " os.write(1, b'Patchwork native initialization\\n')\n"
                    " print('Python pipeline log', flush=True)\n"
                    "print(json.dumps({'valid': True}))"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"valid": True})
        self.assertIn("Patchwork native initialization", result.stderr)
        self.assertIn("Python pipeline log", result.stderr)

    def test_diagnostic_selection_is_bounded(self):
        from benchmarks.utility_diagnostics import validate_selection

        validate_selection(0, 2)
        for start, count in ((-1, 2), (0, 0), (0, 9)):
            with self.subTest(start=start, count=count), self.assertRaises(ValueError):
                validate_selection(start, count)

    def test_opt_in_diagnostics_preserve_map_and_explain_support_gates(self):
        binary = require_binary(
            self, "VEYRA_BENCHMARK_BINARY", "build/apps/benchmark/veyra_benchmark"
        )
        import numpy as np

        observations = []
        for index in range(4):
            original = frame(timestamp=float(index + 1), frame_id=str(index))
            points = original.points.copy()
            points[:, 0] += 45
            observations.append(
                replace(
                    original, points=points, drivable=np.full(2, "unknown", dtype="U15")
                )
            )
        payload, _ = stream_bytes(observations)
        reports = []
        for flags in ([], ["--promotion-telemetry"]):
            result = subprocess.run(
                [
                    str(binary),
                    "--policy",
                    "utility_lod",
                    "--include-leaf-details",
                    *flags,
                ],
                input=payload,
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            reports.append(json.loads(result.stdout))
        plain, diagnostic = reports
        self.assertNotIn("promotion_telemetry", plain)
        self.assertEqual(plain["snapshot"], diagnostic["snapshot"])
        self.assertGreater(len(plain["snapshot"]["leaves"]), 0)
        evidence = diagnostic["promotion_telemetry"]
        self.assertEqual(evidence["diagnostics_version"], 1)
        self.assertEqual(
            sum(evidence["decision_reasons"].values()), evidence["decisions"]
        )
        self.assertEqual(
            sum(evidence["support_histograms"]["point_density"]), evidence["decisions"]
        )
        # Both returns share one 40cm region around 45m in each scan. The
        # range-aware expected support is 3: measured density=2/3, bin 13.
        # Repeating four frames must not accumulate density across scans.
        self.assertEqual(evidence["support_histograms"]["point_density"][13], 8)
        self.assertEqual(evidence["support_histograms"]["point_density"][19], 0)
        self.assertGreater(evidence["quality_failed"], 0)
        self.assertEqual(evidence["density_failed"], 0)
        self.assertEqual(
            sum(row["decisions"] for row in evidence["classes"]), evidence["decisions"]
        )
        self.assertLess(
            evidence["signals"]["semantic"]["effective_weighted_sum"],
            evidence["signals"]["semantic"]["weighted_sum"],
        )
