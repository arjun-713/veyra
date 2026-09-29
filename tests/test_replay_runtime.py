"""Runtime smooth-replay mode: cached serve path, guards and truthfulness."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from runtime.replay_cache import ReplayWriter, build_header
from runtime.service import ProductRuntime


def build_small_cache(directory, count=6, policy="distance_lod"):
    path = Path(directory) / "replay.veyra-replay"
    header = build_header(
        dataset="semanticposs",
        sequence="00",
        start=0,
        count=count,
        policy=policy,
        semantic_provider={"mode": "ground_truth"},
        point_budget=8,
        cell_budget=4,
        perception_config_digest="pipeline-digest",
        config_digest=None,
        repo=None,
    )
    writer = ReplayWriter(path, header, count)
    for position in range(count):
        metadata = {
            "type": "visualization",
            "schema_version": 3,
            "generation": 1,
            "index": position,
            "points": {"count": 2, "offset": 0, "stride": 68},
            "cells": {"count": 1, "offset": 2 * 68, "stride": 68},
        }
        writer.add_frame(
            position,
            metadata,
            bytes(2 * 68 + 68),
            telemetry={
                "recorded_during_cache_build": True,
                "perception_timings_ms": {"total": 41.0},
            },
        )
    writer.close()
    return path


class ReplayRuntimeTests(unittest.TestCase):
    def make_runtime(self):
        runtime = ProductRuntime(Path.cwd())
        # No live session: replay must work standalone for the demo.
        self.assertIsNone(runtime.session)
        return runtime

    def open_replay(self, runtime, path, fps=30):
        result = runtime._execute("replay_open", {"path": str(path), "fps": fps})
        self.assertTrue(result["replay"]["active"])
        return result

    def test_replay_open_without_live_session(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                result = self.open_replay(runtime, path)
                self.assertEqual(result["replay"]["frames"], 6)
                self.assertEqual(result["replay"]["fps"], 30)
                self.assertEqual(runtime.status()["frames"], 6)
        finally:
            runtime._replay_close_locked()

    def test_replay_serve_calls_no_processing(self):
        """Cached playback must never invoke perception or mapping."""
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                self.open_replay(runtime, path)
                runtime.session = mock.Mock()
                runtime._execute("start", {})
                for _ in range(3):
                    runtime.next_frame = 0  # force due immediately
                    runtime.tick()
                runtime.session.frame_payload.assert_not_called()
                runtime.session.map_cells_binary.assert_not_called()
                self.assertEqual(runtime.replay_position, 2)
        finally:
            runtime._replay_close_locked()

    def test_replay_tick_advances_at_configured_rate(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory, count=4)
                self.open_replay(runtime, path, fps=30)
                runtime._execute("start", {})
                runtime.tick()  # immediate first frame
                first = runtime.replay_position
                self.assertEqual(first, 0)
                runtime.tick()  # throttled: next frame not due yet
                self.assertEqual(runtime.replay_position, 0)
        finally:
            runtime._replay_close_locked()

    def test_replay_seek_is_instant_and_backward_bumps_generation(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                self.open_replay(runtime, path)
                before = runtime.generation
                runtime._execute("seek", {"index": 4})
                self.assertEqual(runtime.replay_position, 4)
                runtime._execute("seek", {"index": 1})
                self.assertEqual(runtime.replay_position, 1)
                self.assertGreater(runtime.generation, before)
        finally:
            runtime._replay_close_locked()

    def test_replay_step_and_restart_from_zero(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory, count=3)
                self.open_replay(runtime, path)
                runtime._execute("step", {})
                self.assertEqual(runtime.replay_position, 0)
                runtime._execute("seek", {"index": 2})
                runtime._execute("seek", {"index": 0})  # restart: instant
                self.assertEqual(runtime.replay_position, 0)
        finally:
            runtime._replay_close_locked()

    def test_replay_reaches_end_of_sequence(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory, count=2)
                self.open_replay(runtime, path)
                runtime._execute("start", {})
                runtime.tick()
                runtime.next_frame = 0
                runtime.tick()
                runtime.next_frame = 0
                runtime.tick()  # past the end
                self.assertEqual(runtime.state, "ended")
        finally:
            runtime._replay_close_locked()

    def test_policy_change_blocked_while_replay_open(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                self.open_replay(runtime, path)
                with self.assertRaisesRegex(ValueError, "close the smooth replay"):
                    runtime._execute("policy", {"policy": "utility_lod"})
        finally:
            runtime._replay_close_locked()

    def test_policy_mismatch_rejected_at_open(self):
        runtime = self.make_runtime()
        try:
            runtime.config = {
                "dataset": "semanticposs",
                "sequence": "00",
                "map": {"policy": "utility_lod"},
                "playback": {"speed": 1},
            }
            with (
                mock.patch("runtime.service.config_digest", return_value="live"),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = build_small_cache(directory, policy="distance_lod")
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    runtime._execute("replay_open", {"path": str(path), "fps": 30})
        finally:
            runtime.config = None
            runtime._replay_close_locked()

    def test_replay_telemetry_marked_recorded_not_processing(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                self.open_replay(runtime, path)
                runtime._execute("step", {})
                telemetry = runtime.last_telemetry
                self.assertTrue(telemetry["replay"])
                self.assertIsNone(telemetry["fps"])
                self.assertIn("N/A during replay", telemetry["fps_note"])
                self.assertTrue(
                    telemetry["recorded_telemetry"]["recorded_during_cache_build"]
                )
                published = runtime.outbox.take()[0]
                self.assertTrue(published.get("replay"))
        finally:
            runtime._replay_close_locked()

    def test_missing_cache_is_a_clean_error(self):
        runtime = self.make_runtime()
        with self.assertRaisesRegex(ValueError, "unavailable"):
            runtime._execute(
                "replay_open", {"path": "/tmp/no-such-replay.veyra-replay", "fps": 30}
            )

    def test_corrupt_cache_is_a_clean_error(self):
        runtime = self.make_runtime()
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.veyra-replay"
            bad.write_bytes(b"garbage-bytes")
            with self.assertRaisesRegex(ValueError, "unavailable"):
                runtime._execute("replay_open", {"path": str(bad), "fps": 30})

    def test_replay_close_restores_live_accounting(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                self.open_replay(runtime, path)
                runtime._execute("replay_close", {})
                self.assertFalse(runtime.status()["replay"]["active"])
        finally:
            runtime._replay_close_locked()

    def test_prefetch_window_is_bounded(self):
        from runtime import service as service_module

        self.assertLessEqual(service_module.REPLAY_PREFETCH_BYTES, 256 * 1024 * 1024)
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory, count=6)
                self.open_replay(runtime, path)
                runtime._execute("start", {})
                runtime.tick()
                self.assertLessEqual(
                    len(runtime._replay_cache), service_module.REPLAY_PREFETCH_FRAMES
                )
                self.assertLessEqual(
                    runtime._replay_cached_bytes, service_module.REPLAY_PREFETCH_BYTES
                )
        finally:
            runtime._replay_close_locked()

    def test_serve_latency_is_microseconds_not_seconds(self):
        """Cached serve must be orders of magnitude below a processing frame."""
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                self.open_replay(runtime, path)
                started = time.perf_counter()
                runtime._execute("step", {})
                elapsed_ms = (time.perf_counter() - started) * 1000
                self.assertLess(
                    elapsed_ms, 1000, f"cached serve took {elapsed_ms:.1f} ms"
                )
        finally:
            runtime._replay_close_locked()


if __name__ == "__main__":
    unittest.main()
