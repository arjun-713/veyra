"""Benchmark cache regression suite."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from runtime import benchmark_cache
from runtime.config import POLICIES
from runtime.service import ProductRuntime, benchmark_completion_event

# Benchmark cache

"""Durable four-policy benchmark cache: key, lookup, atomic store, cache hits."""


def full_report(count: int = 5, policies=POLICIES) -> dict:
    return {
        "schema_version": 2,
        "dataset": "generic",
        "sequence": "00",
        "input_frames": count,
        "provenance": {
            "git_sha": "abc",
            "timestamp_utc": "2026-09-30T10:00:00+00:00",
            "frame_range": {"start": 0, "count": count},
            "hardware": {"processor": "Apple M3", "machine": "arm64"},
        },
        "policies": {name: {"runs": [{}]} for name in policies},
    }


def material(root: Path, binary: Path, **overrides) -> dict:
    args = {
        "config": {
            "dataset": "generic",
            "dataset_root": str(root),
            "pipeline": {"semantic": {"mode": "ground_truth"}},
        },
        "sequence": "00",
        "start": 0,
        "count": 5,
        "warmup_frames": 0,
        "repetitions": 1,
        "hardware_profile": "auto",
        "binary": binary,
        "repo": root,
    }
    args.update(overrides)
    return benchmark_cache.key_material(**args)


class CacheKeyTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.binary = self.root / "veyra_benchmark"
        self.binary.write_bytes(b"binary-v1")

    def tearDown(self):
        self._dir.cleanup()

    def test_key_is_stable_and_covers_every_result_input(self):
        base = benchmark_cache.cache_key(material(self.root, self.binary))
        self.assertEqual(
            base, benchmark_cache.cache_key(material(self.root, self.binary))
        )
        for change in (
            {"count": 6},
            {"start": 1},
            {"sequence": "01"},
            {"repetitions": 2},
            {"warmup_frames": 1},
            {"hardware_profile": "jetson"},
            {
                "config": {
                    "dataset": "generic",
                    "dataset_root": str(self.root),
                    "pipeline": {"semantic": {"mode": "neural"}},
                }
            },
        ):
            self.assertNotEqual(
                base,
                benchmark_cache.cache_key(material(self.root, self.binary, **change)),
                change,
            )
        self.binary.write_bytes(b"binary-v2")
        self.assertNotEqual(
            base, benchmark_cache.cache_key(material(self.root, self.binary))
        )

    def test_key_records_policies_binary_host_and_commit_fields(self):
        value = material(self.root, self.binary)
        self.assertEqual(value["policies"], list(POLICIES))
        self.assertEqual(value["binary"]["size"], len(b"binary-v1"))
        self.assertIsNotNone(value["binary"]["sha256"])
        self.assertIn("git_sha", value["repo"])  # null outside a git checkout
        self.assertIn("node", value["host"])

    def test_cache_directory_honours_environment_override(self):
        with mock.patch.dict(
            os.environ, {"VEYRA_BENCHMARK_CACHE_DIR": str(self.root / "c")}
        ):
            self.assertEqual(benchmark_cache.cache_directory(), self.root / "c")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VEYRA_BENCHMARK_CACHE_DIR", None)
            self.assertEqual(
                benchmark_cache.cache_directory(),
                Path.home() / ".cache" / "veyra" / "benchmarks",
            )


class StoreLookupTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.cache = self.root / "cache"
        self.output = self.root / "benchmark.json"
        self.csv = self.root / "benchmark.csv"
        self.csv.write_text("policy\n")
        self.material = {"host": {"node": "bench-host"}}

    def tearDown(self):
        self._dir.cleanup()

    def test_store_then_lookup_round_trips_with_provenance(self):
        self.output.write_text(json.dumps(full_report()))
        stored = benchmark_cache.store(
            "k1", self.material, self.output, self.csv, count=5, directory=self.cache
        )
        self.assertEqual(stored, self.cache / "k1.json")
        entry = benchmark_cache.lookup("k1", self.cache)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["report"].read_bytes(), self.output.read_bytes())
        self.assertEqual(entry["csv"], self.cache / "k1.csv")
        descriptor = benchmark_cache.cache_descriptor(entry)
        self.assertTrue(descriptor["hit"])
        self.assertEqual(descriptor["measured_at"], "2026-09-30T10:00:00+00:00")
        self.assertEqual(descriptor["host"], "bench-host")
        self.assertEqual(descriptor["processor"], "Apple M3")
        self.assertIsNone(benchmark_cache.lookup("other", self.cache))
        # No temporary files are left behind by the atomic writer.
        self.assertEqual(
            sorted(path.name for path in self.cache.iterdir()),
            ["k1.csv", "k1.json", "k1.meta.json"],
        )

    def test_partial_runs_are_never_stored(self):
        for report in (
            full_report(policies=POLICIES[:3]),  # missing a policy
            full_report(count=3),  # fewer frames than requested
            {"schema_version": 1, "policies": {}},
        ):
            self.output.write_text(json.dumps(report))
            self.assertIsNone(
                benchmark_cache.store(
                    "k",
                    self.material,
                    self.output,
                    self.csv,
                    count=5,
                    directory=self.cache,
                )
            )
        self.output.write_text("{not json")
        self.assertIsNone(
            benchmark_cache.store(
                "k", self.material, self.output, self.csv, directory=self.cache
            )
        )
        self.assertFalse(self.cache.exists() and any(self.cache.iterdir()))

    def test_tampered_or_half_written_entries_miss(self):
        self.output.write_text(json.dumps(full_report()))
        benchmark_cache.store(
            "k", self.material, self.output, self.csv, directory=self.cache
        )
        (self.cache / "k.json").write_text(json.dumps(full_report(count=4)))
        self.assertIsNone(benchmark_cache.lookup("k", self.cache))
        benchmark_cache.store(
            "k", self.material, self.output, self.csv, directory=self.cache
        )
        (self.cache / "k.meta.json").unlink()  # metadata is the commit marker
        self.assertIsNone(benchmark_cache.lookup("k", self.cache))

    def test_atomic_write_leaves_previous_entry_on_failure(self):
        self.output.write_text(json.dumps(full_report()))
        benchmark_cache.store(
            "k", self.material, self.output, self.csv, directory=self.cache
        )
        before = (self.cache / "k.json").read_bytes()
        with mock.patch.object(
            benchmark_cache.os, "replace", side_effect=OSError("disk")
        ):
            with self.assertRaises(OSError):
                benchmark_cache.store(
                    "k", self.material, self.output, self.csv, directory=self.cache
                )
        self.assertEqual((self.cache / "k.json").read_bytes(), before)
        self.assertFalse([p for p in self.cache.iterdir() if p.name.endswith(".part")])
        self.assertIsNotNone(benchmark_cache.lookup("k", self.cache))

    def test_serve_cached_waits_then_announces_a_labelled_completion(self):
        self.output.write_text(json.dumps(full_report()))
        benchmark_cache.store(
            "k", self.material, self.output, self.csv, directory=self.cache
        )
        entry = benchmark_cache.lookup("k", self.cache)
        stopping = threading.Event()
        published, waits = [], []
        with mock.patch.object(
            stopping, "wait", side_effect=lambda s: waits.append(s) or False
        ):
            benchmark_cache.serve_cached(
                entry, published.append, benchmark_completion_event, stopping
            )
        self.assertEqual(waits, [benchmark_cache.PRESENTATION_DELAY_S])
        self.assertTrue(2.0 <= benchmark_cache.PRESENTATION_DELAY_S <= 4.0)
        (event,) = published
        self.assertEqual(event["state"], "complete")
        self.assertEqual(event["artifact"], str(self.cache / "k.json"))
        self.assertTrue(event["cache"]["hit"])

    def test_serve_cached_is_silent_when_the_runtime_stops(self):
        self.output.write_text(json.dumps(full_report()))
        benchmark_cache.store(
            "k", self.material, self.output, self.csv, directory=self.cache
        )
        stopping = threading.Event()
        stopping.set()
        published = []
        benchmark_cache.serve_cached(
            benchmark_cache.lookup("k", self.cache),
            published.append,
            benchmark_completion_event,
            stopping,
        )
        self.assertEqual(published, [])


class FakePopen:
    """Stands in for the benchmark subprocess; writes (or fails to write) a report."""

    calls = 0
    report: dict | None = None
    code = 0

    def __init__(self, command, **_kwargs):
        type(self).calls += 1
        output = Path(command[command.index("--output") + 1])
        csv = Path(command[command.index("--csv-output") + 1])
        if self.report is not None:
            output.write_text(json.dumps(self.report))
            csv.write_text("policy\n")

    def wait(self, timeout=None):
        return self.code

    def poll(self):
        return self.code


class ServiceCacheTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.cache = self.root / "cache"
        env = mock.patch.dict(
            os.environ, {"VEYRA_BENCHMARK_CACHE_DIR": str(self.cache)}
        )
        env.start()
        self.addCleanup(env.stop)
        binary = (
            self.root
            / "build"
            / "apps"
            / "benchmark"
            / ("veyra_benchmark.exe" if sys.platform == "win32" else "veyra_benchmark")
        )
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"bench")
        self.service = self.make_service()
        commit = mock.patch.object(
            benchmark_cache,
            "repo_commit",
            return_value={"git_sha": "abc", "dirty": False},
        )
        commit.start()
        self.addCleanup(commit.stop)
        self.popen = mock.patch("runtime.service.subprocess.Popen", FakePopen)
        self.popen.start()
        self.addCleanup(self.popen.stop)
        FakePopen.calls, FakePopen.code, FakePopen.report = 0, 0, full_report()
        self.delay = mock.patch.object(
            benchmark_cache, "present_delay", return_value=True
        )
        self.delay_mock = self.delay.start()
        self.addCleanup(self.delay.stop)

    def make_service(self) -> ProductRuntime:
        service = ProductRuntime(self.root)
        service.config = {
            "dataset": "generic",
            "dataset_root": str(self.root),
            "sequence": "00",
            "pipeline": {"semantic": {"mode": "ground_truth"}},
        }
        service.session = mock.MagicMock()
        service.session.adapter.list_sequences.return_value = ["00"]
        service.session.status.return_value = {"frames": 10}
        service._cached_status = {"frames": 10}
        return service

    def close_service(self) -> None:
        self.service.config = self.service.session = None
        self.service.close()

    def tearDown(self):
        self.close_service()
        self._dir.cleanup()

    def run_benchmark(self, **args) -> tuple[dict, dict]:
        result = self.service._start_benchmark({"count": 5, **args})
        self.service._benchmark_thread.join(timeout=10)
        events = []
        while (item := self.service.outbox.take(timeout=0.01)) is not None:
            events.append(item[0])
        # Progress ("running") events precede the single terminal event.
        benchmark = [
            event
            for event in events
            if event.get("type") == "benchmark" and event.get("state") != "running"
        ]
        self.assertEqual(len(benchmark), 1, benchmark)
        return result, benchmark[0]

    def test_cancel_during_the_presentation_delay_withholds_the_cached_report(self):
        self.run_benchmark()
        self.close_service()
        self.service = self.make_service()
        released = threading.Event()

        def delay(_stopping):
            released.wait(timeout=5)
            return True

        self.delay_mock.side_effect = delay
        result = self.service._start_benchmark({"count": 5})
        self.assertTrue(result["cached"])
        self.assertEqual(self.service._cancel_benchmark(), {"state": "cancelling"})
        released.set()
        self.service._benchmark_thread.join(timeout=10)
        events = []
        while (item := self.service.outbox.take(timeout=0.01)) is not None:
            events.append(item[0])
        states = [
            event["state"] for event in events if event.get("type") == "benchmark"
        ]
        self.assertEqual(states, ["cancelled"])

    def test_second_run_is_served_from_cache_after_the_presentation_delay(self):
        result, fresh = self.run_benchmark()
        self.assertEqual(fresh["state"], "complete")
        self.assertFalse(fresh["cache"]["hit"])
        self.assertTrue(fresh["cache"]["stored"])
        self.assertEqual(FakePopen.calls, 1)
        self.delay_mock.assert_not_called()

        # A new runtime (fresh app start) reuses the durable entry.
        self.close_service()
        self.service = self.make_service()
        result, cached = self.run_benchmark()
        self.assertEqual(result, {"state": "running", "cached": True})
        self.assertEqual(FakePopen.calls, 1)
        self.delay_mock.assert_called_once()
        self.assertEqual(cached["state"], "complete")
        self.assertTrue(cached["cache"]["hit"])
        self.assertEqual(cached["cache"]["measured_at"], "2026-09-30T10:00:00+00:00")
        self.assertTrue(cached["artifact"].startswith(str(self.cache)))

    def test_force_reruns_and_refreshes_the_cache(self):
        self.run_benchmark()
        _, forced = self.run_benchmark(force=True)
        self.assertEqual(FakePopen.calls, 2)
        self.assertFalse(forced["cache"]["hit"])
        with self.assertRaises(ValueError):
            self.service._start_benchmark({"count": 5, "force": "yes"})

    def test_failed_and_partial_runs_are_not_cached(self):
        FakePopen.code = 1
        _, failed = self.run_benchmark()
        self.assertEqual(failed["state"], "error")
        FakePopen.code, FakePopen.report = 0, full_report(policies=POLICIES[:2])
        _, partial = self.run_benchmark()
        self.assertFalse(partial.get("cache", {}).get("stored", False))
        self.assertFalse(self.cache.exists() and any(self.cache.glob("*.meta.json")))
        FakePopen.report = full_report()
        _, fresh = self.run_benchmark()
        self.assertFalse(fresh["cache"]["hit"])
        self.assertEqual(FakePopen.calls, 3)

    def test_benchmark_command_accepts_force(self):
        from runtime.service import COMMANDS

        self.assertIn("force", COMMANDS["benchmark"])


# Desktop benchmark contract

"""Producer-to-desktop contract for the schema-v2 benchmark report (issue #58).

Runs the real benchmark harness and C++ binary on a tiny generic dataset,
announces it exactly as the runtime does, and parses the artifact with the
desktop's canonical TypeScript reader. Skips only when the benchmark binary or
Node.js is unavailable; it never substitutes a hand-written report.
"""


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
