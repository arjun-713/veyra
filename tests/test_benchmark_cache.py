"""Durable four-policy benchmark cache: key, lookup, atomic store, cache hits."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from runtime import benchmark_cache
from runtime.config import POLICIES
from runtime.service import ProductRuntime, benchmark_completion_event


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
    args = dict(
        config={
            "dataset": "generic",
            "dataset_root": str(root),
            "pipeline": {"semantic": {"mode": "ground_truth"}},
        },
        sequence="00",
        start=0,
        count=5,
        warmup_frames=0,
        repetitions=1,
        hardware_profile="auto",
        binary=binary,
        repo=root,
    )
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
        self.assertEqual(base, benchmark_cache.cache_key(material(self.root, self.binary)))
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
        self.assertNotEqual(base, benchmark_cache.cache_key(material(self.root, self.binary)))

    def test_key_records_policies_binary_host_and_commit_fields(self):
        value = material(self.root, self.binary)
        self.assertEqual(value["policies"], list(POLICIES))
        self.assertEqual(value["binary"]["size"], len(b"binary-v1"))
        self.assertIsNotNone(value["binary"]["sha256"])
        self.assertIn("git_sha", value["repo"])  # null outside a git checkout
        self.assertIn("node", value["host"])

    def test_cache_directory_honours_environment_override(self):
        with mock.patch.dict(os.environ, {"VEYRA_BENCHMARK_CACHE_DIR": str(self.root / "c")}):
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
                    "k", self.material, self.output, self.csv, count=5, directory=self.cache
                )
            )
        self.output.write_text("{not json")
        self.assertIsNone(
            benchmark_cache.store("k", self.material, self.output, self.csv, directory=self.cache)
        )
        self.assertFalse(self.cache.exists() and any(self.cache.iterdir()))

    def test_tampered_or_half_written_entries_miss(self):
        self.output.write_text(json.dumps(full_report()))
        benchmark_cache.store("k", self.material, self.output, self.csv, directory=self.cache)
        (self.cache / "k.json").write_text(json.dumps(full_report(count=4)))
        self.assertIsNone(benchmark_cache.lookup("k", self.cache))
        benchmark_cache.store("k", self.material, self.output, self.csv, directory=self.cache)
        (self.cache / "k.meta.json").unlink()  # metadata is the commit marker
        self.assertIsNone(benchmark_cache.lookup("k", self.cache))

    def test_atomic_write_leaves_previous_entry_on_failure(self):
        self.output.write_text(json.dumps(full_report()))
        benchmark_cache.store("k", self.material, self.output, self.csv, directory=self.cache)
        before = (self.cache / "k.json").read_bytes()
        with mock.patch.object(benchmark_cache.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                benchmark_cache.store(
                    "k", self.material, self.output, self.csv, directory=self.cache
                )
        self.assertEqual((self.cache / "k.json").read_bytes(), before)
        self.assertFalse([p for p in self.cache.iterdir() if p.name.endswith(".part")])
        self.assertIsNotNone(benchmark_cache.lookup("k", self.cache))

    def test_serve_cached_waits_then_announces_a_labelled_completion(self):
        self.output.write_text(json.dumps(full_report()))
        benchmark_cache.store("k", self.material, self.output, self.csv, directory=self.cache)
        entry = benchmark_cache.lookup("k", self.cache)
        stopping = threading.Event()
        published, waits = [], []
        with mock.patch.object(stopping, "wait", side_effect=lambda s: waits.append(s) or False):
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
        benchmark_cache.store("k", self.material, self.output, self.csv, directory=self.cache)
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
        env = mock.patch.dict(os.environ, {"VEYRA_BENCHMARK_CACHE_DIR": str(self.cache)})
        env.start()
        self.addCleanup(env.stop)
        binary = self.root / "build" / "apps" / "benchmark" / (
            "veyra_benchmark.exe" if sys.platform == "win32" else "veyra_benchmark"
        )
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"bench")
        self.service = self.make_service()
        commit = mock.patch.object(
            benchmark_cache, "repo_commit", return_value={"git_sha": "abc", "dirty": False}
        )
        commit.start()
        self.addCleanup(commit.stop)
        self.popen = mock.patch("runtime.service.subprocess.Popen", FakePopen)
        self.popen.start()
        self.addCleanup(self.popen.stop)
        FakePopen.calls, FakePopen.code, FakePopen.report = 0, 0, full_report()
        self.delay = mock.patch.object(benchmark_cache, "present_delay", return_value=True)
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
        states = [event["state"] for event in events if event.get("type") == "benchmark"]
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


if __name__ == "__main__":
    unittest.main()
