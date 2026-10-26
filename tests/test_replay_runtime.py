"""Runtime smooth-replay mode: cached serve path, guards and truthfulness."""

import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from runtime.protocol import Outbox
from runtime.replay_cache import ReplayReader, ReplayWriter, build_header
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


def wait_until(predicate, timeout=1):
    deadline = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() >= deadline:
            raise AssertionError("timed out waiting for replay prefetch")
        time.sleep(0.001)


class RecordingOutbox(Outbox):
    """Observe backend publications while retaining the real bounded transport."""

    def __init__(self):
        super().__init__()
        self.snapshots = []

    def publish(self, metadata, payload=b""):
        if metadata.get("type") == "visualization":
            self.snapshots.append((metadata, payload))
        return super().publish(metadata, payload)


class ReplayRuntimeTests(unittest.TestCase):
    def make_runtime(self):
        runtime = ProductRuntime(Path.cwd())
        self.addCleanup(runtime.close)
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

    def test_pause_responds_while_first_cache_read_is_blocked(self):
        """Bulk prefetch on the control worker prevents Play/Pause responses."""
        runtime = self.make_runtime()
        reading = threading.Event()
        release = threading.Event()
        original = ReplayReader.read_frame

        def slow_read(reader, position, **kwargs):
            reading.set()
            if not release.wait(3):
                raise TimeoutError("test cache read was not released")
            return original(reader, position, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            path = build_small_cache(directory, count=488)
            self.open_replay(runtime, path)
            worker = threading.Thread(target=runtime.run, daemon=True)
            try:
                with mock.patch.object(ReplayReader, "read_frame", slow_read):
                    worker.start()
                    runtime.submit({"id": "play", "command": "start", "args": {}})
                    self.assertTrue(reading.wait(1), "cache read never started")
                    runtime.submit({"id": "pause", "command": "pause", "args": {}})
                    responses = {}
                    deadline = time.monotonic() + 0.5
                    while time.monotonic() < deadline and "pause" not in responses:
                        event = runtime.outbox.take(timeout=0.02)
                        if event and event[0].get("type") == "response":
                            responses[event[0]["id"]] = event[0]
                    self.assertIn("pause", responses, "Pause blocked behind cache I/O")
                    self.assertTrue(responses["play"]["ok"])
                    self.assertEqual(responses["pause"]["status"]["state"], "paused")
                    self.assertEqual(runtime.replay_position, -1)
            finally:
                release.set()
                runtime.stopping.set()
                worker.join(2)
                if not worker.is_alive():
                    runtime.close()

    def test_replay_rate_changes_deadline_without_rewinding(self):
        """A rate command must take effect while paused and while playing."""
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.open_replay(runtime, build_small_cache(directory))
                runtime._execute("seek", {"index": 2})
                generation = runtime.generation
                for fps in (15, 30, 60):
                    with (
                        self.subTest(fps=fps),
                        mock.patch(
                            "runtime.service.time.monotonic", return_value=100.0
                        ),
                    ):
                        response = runtime.handle(
                            {
                                "id": "rate",
                                "command": "replay_rate",
                                "args": {"fps": fps},
                            }
                        )
                        self.assertTrue(response["ok"], response)
                        self.assertEqual(response["result"]["replay"]["fps"], fps)
                        self.assertEqual(
                            response["status"]["replay"]["effective_fps"], fps
                        )
                        self.assertEqual(runtime.replay_position, 2)
                        self.assertEqual(runtime.generation, generation)
                        runtime._execute("start", {})
                        runtime._execute("replay_rate", {"fps": fps})
                        self.assertAlmostEqual(runtime.next_frame, 100.0 + 1 / fps)
                        self.assertEqual(runtime.state, "running")
                        runtime._execute("pause", {})
        finally:
            runtime.close()

    def test_worker_waits_for_60fps_deadline_instead_of_fixed_20ms(self):
        """The command queue wait must not cap a warmed replay at 50 FPS."""
        runtime = self.make_runtime()
        waits = []

        def stop_after_wait(*, timeout):
            waits.append(timeout)
            runtime.stopping.set()
            raise queue.Empty

        with tempfile.TemporaryDirectory() as directory:
            self.open_replay(runtime, build_small_cache(directory), fps=60)
            runtime.state = "running"
            runtime.next_frame = 100.0 + 1 / 60
            with (
                mock.patch("runtime.service.time.monotonic", return_value=100.0),
                mock.patch.object(runtime.commands, "get", stop_after_wait),
            ):
                runtime.run()
            self.assertEqual(len(waits), 1)
            self.assertAlmostEqual(waits[0], 1 / 60)

    def test_prefetch_admission_never_exceeds_encoded_byte_budget(self):
        """Checking after allocation admits one frame beyond the byte cap."""
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                with ReplayReader(path) as reader:
                    budget = reader._entries[0][1] + reader._entries[0][2] + 1
                with mock.patch("runtime.service.REPLAY_PREFETCH_BYTES", budget):
                    self.open_replay(runtime, path)
                    runtime._execute("start", {})
                    wait_until(lambda: runtime._replay_status()["prefetch_frames"] > 0)
                    status = runtime._replay_status()
                    self.assertLessEqual(status["prefetch_bytes"], budget)
        finally:
            runtime.close()

    def test_last_snapshot_remains_running_until_pause(self):
        """The last frame stays active so the next scheduled tick can loop."""
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.open_replay(runtime, build_small_cache(directory, count=1))
                runtime._execute("start", {})
                wait_until(lambda: runtime._replay_status()["prefetch_frames"] == 1)
                runtime.tick()
                self.assertEqual(runtime.replay_position, 0)
                self.assertEqual(runtime.status()["state"], "running")
        finally:
            runtime.close()

    def test_replay_close_stops_playback_instead_of_entering_live_tick(self):
        """Closing a running standalone cache must not fall through to live work."""
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.open_replay(runtime, build_small_cache(directory))
                runtime._execute("start", {})
                runtime._execute("replay_close", {})
                self.assertEqual(runtime.state, "unconfigured")
                runtime.tick()
                self.assertFalse(runtime.status()["replay"]["active"])
        finally:
            runtime.close()

    def test_replay_close_without_cache_preserves_live_playback_state(self):
        runtime = self.make_runtime()
        runtime.state = "running"
        runtime.generation = 7
        runtime.last_telemetry = {"type": "telemetry", "index": 5}
        runtime._execute("replay_close", {})
        self.assertEqual(runtime.state, "running")
        self.assertEqual(runtime.generation, 7)
        self.assertEqual(runtime.last_telemetry["index"], 5)

    def test_all_488_snapshots_publish_in_order_at_15_30_60fps(self):
        """A clock jump or underrun must never skip a cached snapshot."""
        for fps in (15, 30, 60):
            with self.subTest(fps=fps), tempfile.TemporaryDirectory() as directory:
                runtime = self.make_runtime()
                runtime.outbox = RecordingOutbox()
                try:
                    self.open_replay(
                        runtime, build_small_cache(directory, count=488), fps
                    )
                    clock = 100.0
                    with mock.patch("runtime.service.time.monotonic") as now:
                        now.return_value = clock
                        runtime._execute("start", {})
                        generation = runtime.generation
                        for position in range(488):
                            # Synchronize with real disk reads; only the presentation
                            # clock is virtual, so the suite need not wait 57 seconds.
                            wait_until(
                                lambda position=position, runtime=runtime: (
                                    position in runtime._replay_prefetcher._frames
                                )
                            )
                            now.return_value = clock - 0.000001
                            runtime.tick()
                            self.assertEqual(len(runtime.outbox.snapshots), position)
                            now.return_value = clock
                            runtime.tick()
                            self.assertEqual(runtime.replay_position, position)
                            self.assertAlmostEqual(runtime.next_frame, clock + 1 / fps)
                            if position == 200:
                                runtime._execute("pause", {})
                                now.return_value = clock + 10
                                runtime.tick()
                                self.assertEqual(runtime.replay_position, 200)
                                runtime._execute("start", {})
                                clock += 10
                            else:
                                clock += 1 / fps
                        indices = [
                            meta["index"] for meta, _ in runtime.outbox.snapshots
                        ]
                        self.assertEqual(indices, list(range(488)))
                        self.assertEqual(runtime.generation, generation)
                        self.assertEqual(runtime.state, "running")
                        self.assertIsNone(runtime.last_telemetry["fps"])
                finally:
                    runtime.close()

    def test_replay_rate_rejects_invalid_values_without_changing_playhead(self):
        runtime = self.make_runtime()
        with tempfile.TemporaryDirectory() as directory:
            self.open_replay(runtime, build_small_cache(directory))
            runtime._execute("step", {})
            for fps in (0, 10, 29, 61, True, "30", None, float("nan")):
                with self.subTest(fps=fps):
                    response = runtime.handle(
                        {"id": "rate", "command": "replay_rate", "args": {"fps": fps}}
                    )
                    self.assertFalse(response["ok"])
                    self.assertEqual(runtime.replay_fps, 30)
                    self.assertEqual(runtime.replay_position, 0)
            runtime._execute("replay_close", {})
            response = runtime.handle(
                {"id": "rate", "command": "replay_rate", "args": {"fps": 60}}
            )
            self.assertFalse(response["ok"])

    def test_speed_and_rate_reset_deadline_and_report_effective_rate(self):
        runtime = self.make_runtime()
        with tempfile.TemporaryDirectory() as directory:
            self.open_replay(runtime, build_small_cache(directory))
            with mock.patch("runtime.service.time.monotonic", return_value=100.0):
                runtime._execute("start", {})
                runtime._execute("speed", {"speed": 2})
                self.assertAlmostEqual(runtime.next_frame, 100 + 1 / 60)
                response = runtime.handle(
                    {"id": "rate", "command": "replay_rate", "args": {"fps": 15}}
                )
                self.assertTrue(response["ok"])
                self.assertEqual(response["result"]["replay"]["effective_fps"], 30)
                self.assertAlmostEqual(runtime.next_frame, 100 + 1 / 30)

    def test_unreadable_prefetch_reports_error_without_stopping_control_worker(self):
        runtime = self.make_runtime()
        with tempfile.TemporaryDirectory() as directory:
            self.open_replay(runtime, build_small_cache(directory))
            worker = threading.Thread(target=runtime.run, daemon=True)
            try:
                with mock.patch.object(
                    ReplayReader, "read_frame", side_effect=OSError("disk read failed")
                ):
                    worker.start()
                    runtime.submit({"id": "play", "command": "start", "args": {}})
                    wait_until(lambda: runtime.status()["state"] == "error")
                    self.assertEqual(runtime.replay_position, -1)
                    self.assertIn(
                        "disk read failed", runtime.status()["error"]["message"]
                    )
                    self.assertTrue(worker.is_alive())
                    runtime.submit(
                        {"id": "close", "command": "replay_close", "args": {}}
                    )
                    wait_until(lambda: not runtime.status()["replay"]["active"])
                    self.assertEqual(runtime.state, "unconfigured")
            finally:
                runtime.stopping.set()
                worker.join(2)

    def test_closed_prefetch_cannot_publish_into_reopened_cache(self):
        runtime = self.make_runtime()
        reading = threading.Event()
        release = threading.Event()
        original = ReplayReader.read_frame

        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            first_path = build_small_cache(first, count=3)
            second_path = build_small_cache(second, count=2)
            self.open_replay(runtime, first_path)
            retired = runtime._replay_prefetcher

            def slow_first(reader, position, **kwargs):
                if reader.path == first_path:
                    reading.set()
                    release.wait(2)
                return original(reader, position, **kwargs)

            try:
                with mock.patch.object(ReplayReader, "read_frame", slow_first):
                    runtime._execute("start", {})
                    self.assertTrue(reading.wait(1))
                    runtime._execute("replay_close", {})
                    self.open_replay(runtime, second_path)
                    generation = runtime.generation
                    runtime._execute("start", {})
                    wait_until(lambda: runtime._replay_status()["prefetch_frames"] == 2)
                    release.set()
                    retired._thread.join(1)
                    self.assertFalse(retired._thread.is_alive())
                    self.assertTrue(retired._reader._stream.closed)
                    runtime.tick()
                    self.assertEqual(runtime.replay_position, 0)
                    self.assertEqual(runtime.generation, generation)
                    self.assertEqual(runtime.status()["frames"], 2)
            finally:
                release.set()
                runtime.close()

    def test_replay_serve_calls_no_processing(self):
        """Cached playback must never invoke perception or mapping."""
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory)
                self.open_replay(runtime, path)
                runtime.session = mock.Mock()
                # Status reads the sequence length; that is not processing.
                runtime.session.status.return_value = {"frames": 2}
                runtime._execute("start", {})
                wait_until(lambda: runtime._replay_status()["prefetch_frames"] >= 3)
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
                wait_until(lambda: runtime._replay_status()["prefetch_frames"] >= 1)
                runtime.tick()  # immediate first frame
                first = runtime.replay_position
                self.assertEqual(first, 0)
                runtime.tick()  # throttled: next frame not due yet
                self.assertEqual(runtime.replay_position, 0)
        finally:
            runtime._replay_close_locked()

    def test_worker_wait_tracks_60_fps_deadline_instead_of_20_ms_poll(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.open_replay(runtime, build_small_cache(directory), fps=60)
                runtime._execute("start", {})
                runtime.next_frame = 100.0 + 1 / 60
                self.assertAlmostEqual(runtime._command_wait_timeout(100.0), 1 / 60)
                self.assertEqual(runtime._command_wait_timeout(101.0), 0.0)
        finally:
            runtime._replay_close_locked()

    def test_replay_deadline_does_not_accumulate_worker_lateness(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.open_replay(runtime, build_small_cache(directory), fps=60)
                runtime._execute("start", {})
                wait_until(lambda: runtime._replay_status()["prefetch_frames"] >= 1)
                runtime.next_frame = 100.0
                with mock.patch("runtime.service.time.monotonic", return_value=100.01):
                    runtime.tick()
                self.assertAlmostEqual(runtime.next_frame, 100.0 + 1 / 60)
        finally:
            runtime._replay_close_locked()

    def test_replay_stall_restarts_cadence_instead_of_bursting(self):
        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                self.open_replay(runtime, build_small_cache(directory), fps=60)
                runtime._execute("start", {})
                wait_until(lambda: runtime._replay_status()["prefetch_frames"] >= 1)
                runtime.next_frame = 100.0
                with mock.patch("runtime.service.time.monotonic", return_value=102.0):
                    runtime.tick()
                self.assertAlmostEqual(runtime.next_frame, 102.0 + 1 / 60)
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
                wait_until(lambda: runtime._replay_status()["prefetch_frames"] == 2)
                runtime.tick()
                runtime.next_frame = 0
                runtime.tick()
                runtime.next_frame = 0
                before = runtime.generation
                runtime._replay_prefetch(-1)
                wait_until(lambda: 0 in runtime._replay_prefetcher._frames)
                runtime.tick()  # loop to the first real cached scan
                self.assertEqual(runtime.replay_position, 0)
                self.assertEqual(runtime.state, "running")
                self.assertGreater(runtime.generation, before)
                runtime._execute("pause", {})
                runtime.next_frame = 0
                runtime.tick()
                self.assertEqual(runtime.replay_position, 0)
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

    def test_policy_change_during_session_replay_prepares_new_policy_cache(self):
        runtime = self.make_runtime()
        config = {
            "dataset": "semanticposs",
            "sequence": "00",
            "map": {"policy": "distance_lod"},
            "playback": {"fps": 30.0, "speed": 1.0, "full_sequence": True},
        }
        session = mock.Mock()
        session.status.return_value = {"frames": 6}
        try:
            with (
                tempfile.TemporaryDirectory() as directory,
                mock.patch(
                    "runtime.service.validate_config", side_effect=lambda c, _: c
                ),
                mock.patch.object(runtime, "_create_session", return_value=session),
                mock.patch("runtime.replay_cache.check_compatible", return_value=None),
                mock.patch.object(runtime, "_prepare_auto_replay") as prepare,
            ):
                runtime._configure(config)
                self.open_replay(runtime, build_small_cache(directory))
                runtime._execute("policy", {"policy": "utility_lod"})
                self.assertIsNone(runtime.replay_reader)
                self.assertEqual(runtime.config["map"]["policy"], "utility_lod")
                self.assertEqual(runtime._auto_replay["state"], "pending")
                prepare.assert_called_once()
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

        runtime = self.make_runtime()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = build_small_cache(directory, count=6)
                self.open_replay(runtime, path)
                runtime._execute("start", {})
                wait_until(lambda: runtime._replay_status()["prefetch_frames"] > 0)
                runtime.tick()
                status = runtime._replay_status()
                self.assertLessEqual(
                    status["prefetch_frames"], service_module.REPLAY_PREFETCH_FRAMES
                )
                self.assertLessEqual(
                    status["prefetch_bytes"] + status["prefetch_in_flight_bytes"],
                    service_module.REPLAY_PREFETCH_BYTES,
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


class ReplayBackwardsCompatTests(unittest.TestCase):
    def test_publish_status_survives_foreign_constructed_runtime(self):
        """Guards CI: tests build ProductRuntime via __new__ without replay fields."""
        import queue
        import threading

        from runtime.protocol import Outbox
        from runtime.telemetry import Telemetry

        runtime = ProductRuntime.__new__(ProductRuntime)
        runtime.session = None
        runtime.config = None
        runtime.state = "ready"
        runtime.layer = "semantic"
        runtime.index = 3
        runtime.generation = 0
        runtime.error = None
        runtime.dropped_frames = 0
        runtime.telemetry = Telemetry()
        runtime.last_visual = 0.0
        runtime.outbox = Outbox()
        runtime.commands = queue.Queue()
        runtime._status_lock = threading.Lock()
        runtime._cached_status = {}
        runtime._publish_status()
        status = runtime.status()
        self.assertEqual(status["replay"], {"active": False})
