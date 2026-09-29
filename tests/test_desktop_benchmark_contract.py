"""Producer-to-desktop contract for the schema-v2 benchmark report (issue #58).

Runs the real benchmark harness and C++ binary on a tiny generic dataset,
announces it exactly as the runtime does, and parses the artifact with the
desktop's canonical TypeScript reader. Skips only when the benchmark binary or
Node.js is unavailable; it never substitutes a hand-written report.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from runtime.service import benchmark_completion_event

REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / "apps" / "desktop"


def benchmark_binary() -> Path | None:
    configured = os.environ.get("VEYRA_BENCHMARK_BINARY")
    candidate = (
        Path(configured)
        if configured
        else REPO / "build" / "apps" / "benchmark" / "veyra_benchmark"
    )
    return candidate if candidate.is_file() else None


def write_tiny_generic_dataset(root: Path, frames: int = 4) -> None:
    """A flat ground patch plus a box, seen from a slowly advancing pose."""
    rng = np.random.default_rng(7)
    ground = np.column_stack(
        [
            rng.uniform(-35, 35, 3000),
            rng.uniform(-35, 35, 3000),
            rng.normal(0, 0.02, 3000),
        ]
    )
    box = np.column_stack(
        [rng.uniform(4, 5, 400), rng.uniform(-0.5, 0.5, 400), rng.uniform(0, 1.2, 400)]
    )
    points = np.vstack([ground, box])
    cloud = np.column_stack([points, np.full(len(points), 0.5)]).astype("<f4")
    cloud.tofile(root / "scan.bin")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": "desktop-contract-fixture",
                "point_schema": {
                    "format": "xyzi",
                    "coordinate_frame": "sensor",
                    "intensity_semantics": "reflectance",
                },
                "taxonomy": {"version": "v1", "mapping": {}},
                "frames": [
                    {
                        "sequence": "s",
                        "frame_id": f"{index:06d}",
                        "timestamp_s": index * 0.1,
                        "pose_sensor_to_world": [
                            [1, 0, 0, 0.2 * index],
                            [0, 1, 0, 0],
                            [0, 0, 1, 0],
                            [0, 0, 0, 1],
                        ],
                        "points": {"path": "scan.bin", "format": "xyzi_f32_bin"},
                    }
                    for index in range(frames)
                ],
            }
        )
    )


def run_real_benchmark(binary: Path, root: Path, output: Path, csv: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.run_benchmark",
            "--repo",
            str(REPO),
            "--binary",
            str(binary),
            "--dataset",
            "generic",
            "--dataset-root",
            str(root),
            "--sequence",
            "s",
            "--count",
            "4",
            "--warmup-frames",
            "0",
            "--repetitions",
            "1",
            "--skip-perception",
            "--output",
            str(output),
            "--csv-output",
            str(csv),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr[-4000:])


def parse_with_desktop(report_path: Path) -> dict:
    """Run the desktop's canonical reader (benchmark-report.ts) on a file."""
    script = f"""
import {{readFileSync}} from 'node:fs';
import * as contract from './src/renderer/benchmark-report.ts';
const raw = JSON.parse(readFileSync({json.dumps(str(report_path))}, 'utf8'));
const accepted = contract.acceptBenchmarkReport(raw, 'generated');
console.log(JSON.stringify({{
  complete: accepted.complete, issues: accepted.issues,
  rows: contract.qualityResourceRows(accepted.report),
  semantic: contract.semanticQuality(accepted.report),
  baselines: contract.referenceBaselines(accepted.report),
  storage: contract.storageComparison(accepted.report),
  provenance: contract.reportProvenance(accepted.report),
  scope: contract.comparisonScope(accepted.report),
  exported: JSON.stringify(accepted.report) === JSON.stringify(raw),
}}));
"""
    completed = subprocess.run(
        [
            "node",
            "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            script,
        ],
        cwd=DESKTOP,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr[-4000:])
    return json.loads(completed.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the desktop reader")
class DesktopBenchmarkContractTests(unittest.TestCase):
    def test_real_benchmark_completion_reaches_the_desktop_intact(self):
        binary = benchmark_binary()
        if binary is None:
            self.skipTest("build veyra_benchmark or set VEYRA_BENCHMARK_BINARY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_tiny_generic_dataset(root)
            output, csv = root / "benchmark.json", root / "benchmark.csv"
            run_real_benchmark(binary, root, output, csv)
            event = benchmark_completion_event(output, csv)
            self.assertEqual(event["artifact_bytes"], output.stat().st_size)
            self.assertNotIn("report", event)
            parsed = parse_with_desktop(Path(event["artifact"]))

        self.assertTrue(parsed["complete"], parsed["issues"])
        self.assertTrue(parsed["exported"], "export must preserve the full report")
        rows = {row["policy"]: row for row in parsed["rows"]}
        self.assertEqual(
            set(rows), {"uniform5", "uniform40", "distance_lod", "utility_lod"}
        )
        for policy, row in rows.items():
            self.assertEqual(row["source"], "quality_resource", policy)
            self.assertGreater(row["logicalBytes"], 0, policy)
            self.assertGreater(row["activeCells"], 0, policy)
            self.assertIsNotNone(row["mapP50Ms"], policy)
            # Four samples cannot support tail claims.
            self.assertFalse(row["p95Reliable"], policy)
        self.assertEqual(rows["uniform5"]["completion"], 1.0)
        self.assertLessEqual(
            rows["uniform40"]["logicalBytes"], rows["uniform5"]["logicalBytes"]
        )
        self.assertEqual(parsed["scope"]["latencyMetric"], "p50")
        self.assertTrue(parsed["scope"]["sameInput"])
        self.assertFalse(parsed["scope"]["referenceIsGroundTruth"])
        # Generic manifests have no paired semantic evaluation: unavailable, not 0.
        self.assertEqual(parsed["semantic"]["status"], "unavailable")
        self.assertIsNone(parsed["semantic"]["miou"])
        kinds = {item["key"]: item["kind"] for item in parsed["baselines"]}
        self.assertEqual(kinds["uniform_5cm_3d"], "analytical")
        # The measured sparse 3D reference is emitted by default now.
        self.assertEqual(kinds["sparse_5cm_3d"], "measured")
        storage = {item["key"]: item for item in parsed["storage"]}
        self.assertEqual(
            list(storage),
            [
                "dense_3d",
                "sparse_3d",
                "uniform5",
                "uniform40",
                "distance_lod",
                "utility_lod",
            ],
        )
        self.assertEqual(storage["dense_3d"]["kind"], "analytical")
        self.assertEqual(storage["sparse_3d"]["kind"], "measured")
        for key, item in storage.items():
            self.assertGreater(item["bytes"], 0, key)
            if key not in {"dense_3d", "sparse_3d"}:
                self.assertEqual(item["kind"], "measured", key)
                self.assertGreater(item["timesSmallerThanDense"], 1, key)
                self.assertIsNotNone(item["timesSmallerThanSparse"], key)
        self.assertIsNotNone(parsed["provenance"]["gitSha"])
        self.assertFalse(parsed["provenance"]["perceptionExecuted"])

    def test_runtime_refuses_to_announce_an_unsupported_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "benchmark.json"
            output.write_text(json.dumps({"schema_version": 1, "policies": {}}))
            with self.assertRaisesRegex(RuntimeError, "unsupported report schema"):
                benchmark_completion_event(output, output.with_suffix(".csv"))
            output.write_text(json.dumps({"schema_version": 2, "policies": {}}))
            with self.assertRaisesRegex(RuntimeError, "missing provenance"):
                benchmark_completion_event(output, output.with_suffix(".csv"))


if __name__ == "__main__":
    unittest.main()
