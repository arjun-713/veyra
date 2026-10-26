"""Replay cache regression suite."""

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from runtime.auto_replay import CELL_SELECTION, cache_path, prepare, ready_cache
from runtime.config import PRESETS, config_digest, validate_config
from runtime.replay_cache import (
    REPLAY_SCHEMA,
    ReplayError,
    ReplayPrefetch,
    ReplayReader,
    ReplayWriter,
    build_header,
    check_compatible,
    default_cache_path,
)
from runtime.service import ProductRuntime
from scripts.export_demo_clip import (
    decode_cells,
    decode_points,
    rasterize,
    write_ppm,
)
from scripts.prepare_replay_cache import cache_pipeline, cache_playback, parse_args

# Replay cache

"""Replay cache schema, provenance, ordering and corruption tests."""


def make_header(**overrides):
    header = build_header(
        dataset="semanticposs",
        sequence="00",
        start=0,
        count=3,
        policy="utility_lod",
        semantic_provider={"mode": "ground_truth"},
        point_budget=15000,
        cell_budget=10000,
        perception_config_digest="abc",
        config_digest="def",
        repo=None,
    )
    header.update(overrides)
    return header


def make_frame(index):
    metadata = {
        "type": "visualization",
        "schema_version": 3,
        "generation": 1,
        "index": index,
        "points": {"count": 2, "offset": 0, "stride": 68},
        "cells": {"count": 1, "offset": 2 * 68, "stride": 68},
    }
    payload = bytes(2 * 68 + 68)
    return metadata, payload


class ReplayCacheTests(unittest.TestCase):
    def write_cache(self, directory, count=3, **overrides):
        path = Path(directory) / "test.veyra-replay"
        header = make_header(count=count, **overrides)
        writer = ReplayWriter(path, header, count)
        for position in range(count):
            metadata, payload = make_frame(position)
            writer.add_frame(
                position,
                metadata,
                payload,
                telemetry={"recorded_during_cache_build": True},
            )
        summary = writer.close()
        return path, header, summary

    def test_round_trip_preserves_metadata_and_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory)
            with ReplayReader(path) as reader:
                self.assertEqual(len(reader), 3)
                self.assertEqual(reader.frame_indices, [0, 1, 2])
                metadata, payload = reader.read_frame(1)
                self.assertEqual(metadata["index"], 1)
                self.assertEqual(metadata["replay_frame"], 1)
                self.assertTrue(
                    metadata["recorded_telemetry"]["recorded_during_cache_build"]
                )
                self.assertEqual(len(payload), 2 * 68 + 68)

    def test_frame_ordering_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "order.veyra-replay"
            writer = ReplayWriter(path, make_header(), 2)
            metadata, payload = make_frame(5)
            writer.add_frame(5, metadata, payload)
            # Duplicate index must fail the build, never silently reorder.
            writer.add_frame(5, metadata, payload)
            with self.assertRaisesRegex(ReplayError, "unique"):
                writer.close()

    def test_incomplete_build_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.veyra-replay"
            writer = ReplayWriter(path, make_header(), 3)
            metadata, payload = make_frame(0)
            writer.add_frame(0, metadata, payload)
            with self.assertRaisesRegex(ReplayError, "incomplete"):
                writer.close()

    def test_cache_compatibility_uses_policy_and_configuration(self):
        cases = (
            ("distance_lod", None, ("distance_lod", "utility_lod")),
            ("utility_lod", "changed", ("rebuild",)),
            ("utility_lod", "def", ()),
        )
        for policy, digest, messages in cases:
            with self.subTest(policy=policy, digest=digest):
                kwargs = {} if digest is None else {"config_digest": digest}
                reason = check_compatible(make_header(), policy=policy, **kwargs)
                if not messages:
                    self.assertIsNone(reason)
                for message in messages:
                    self.assertIn(message, reason)

    def test_missing_provenance_rejected(self):
        header = make_header()
        del header["policy"]
        with (
            self.assertRaisesRegex(ValueError, "provenance"),
            tempfile.TemporaryDirectory() as directory,
        ):
            ReplayWriter(Path(directory) / "x.veyra-replay", header, 1)

    def test_damaged_cache_files_fail_closed(self):
        for damage, message in (("magic", "magic"), ("truncate", "truncat|outside")):
            with (
                self.subTest(damage=damage),
                tempfile.TemporaryDirectory() as directory,
            ):
                path, _, _ = self.write_cache(directory)
                raw = bytearray(path.read_bytes())
                if damage == "magic":
                    raw[:8] = b"NOTVEYRA"
                else:
                    raw = raw[: len(raw) // 2]
                path.write_bytes(raw)
                with self.assertRaisesRegex(ReplayError, message):
                    ReplayReader(path)

    def test_checksum_catches_blob_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory)
            with ReplayReader(path) as reader:
                self.assertEqual(len(reader), 3)
                # Flip a byte in the last payload blob.
                raw = bytearray(path.read_bytes())
                raw[-1] ^= 0xFF
                path.write_bytes(bytes(raw))
            with (
                ReplayReader(path) as reader,
                self.assertRaisesRegex(ReplayError, "checksum"),
            ):
                reader.read_frame(2, verify=True)

    def test_missing_file_reports_clearly(self):
        with self.assertRaisesRegex(ReplayError, "not found"):
            ReplayReader("/tmp/does-not-exist-veyra.veyra-replay")

    def test_position_out_of_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory)
            with (
                ReplayReader(path) as reader,
                self.assertRaisesRegex(ReplayError, "out of range"),
            ):
                reader.read_frame(99)

    def test_end_of_sequence_is_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory, count=5)
            with ReplayReader(path) as reader:
                self.assertEqual(len(reader), 5)
                self.assertEqual(reader.frame_indices[-1], 4)
                self.assertGreater(reader.disk_bytes(), 0)
                self.assertGreater(reader.avg_frame_bytes(), 0)

    def test_default_path_is_gitignored_cache_dir(self):
        path = default_cache_path(
            dataset="semanticposs",
            sequence="00",
            start=0,
            count=488,
            policy="utility_lod",
            provider="ground_truth",
            point_budget=15000,
            cell_budget=10000,
        )
        self.assertTrue(str(path).startswith("data/cache/replays/"))
        self.assertTrue(str(path).endswith(".veyra-replay"))

    def test_header_carries_full_provenance(self):
        header = make_header()
        for key in (
            "dataset",
            "sequence",
            "policy",
            "config_digest",
            "code_sha",
            "replay_schema",
        ):
            self.assertIn(key, header)
        self.assertEqual(header["replay_schema"], REPLAY_SCHEMA)

    def test_prefetch_retarget_discards_in_flight_frame_and_reclaims_bytes(self):
        """Seeking while disk I/O runs must discard old data and exact byte costs."""
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory, count=6)
            reader = ReplayReader(path)
            frame_size = reader._entries[0][1] + reader._entries[0][2]
            reading = threading.Event()
            release = threading.Event()
            original = reader.read_frame

            def slow_first(position):
                if position == 0:
                    reading.set()
                    release.wait(2)
                return original(position)

            reader.read_frame = slow_first
            prefetch = ReplayPrefetch(reader, max_frames=2, max_bytes=2 * frame_size)
            try:
                prefetch.request(0)
                self.assertTrue(reading.wait(1))
                self.assertEqual(
                    prefetch.status()["prefetch_in_flight_bytes"], frame_size
                )
                prefetch.request(4)
                release.set()
                deadline = time.perf_counter() + 1
                while prefetch.status()["prefetch_frames"] != 2:
                    if time.perf_counter() > deadline:
                        self.fail("prefetch did not fill the new seek window")
                    time.sleep(0.001)
                self.assertIsNone(prefetch.take(0))
                self.assertEqual(prefetch.status()["prefetch_bytes"], 2 * frame_size)
                # Advancing the window evicts frame 4 with its full encoded cost.
                prefetch.request(5)
                self.assertEqual(prefetch.status()["prefetch_bytes"], frame_size)
                metadata, payload = prefetch.take(5)
                self.assertEqual(metadata["index"], 5)
                self.assertEqual(payload, bytes(204))
                self.assertEqual(prefetch.status()["prefetch_bytes"], 0)
            finally:
                release.set()
                prefetch.close()
                prefetch._thread.join(1)
                self.assertFalse(prefetch._thread.is_alive())
                self.assertTrue(reader._stream.closed)

    def test_backward_seek_prioritizes_missing_near_frame_when_byte_budget_full(self):
        """Retained future frames must not starve an earlier requested frame."""
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory, count=6)
            reader = ReplayReader(path)
            frame_size = reader._entries[0][1] + reader._entries[0][2]
            prefetch = ReplayPrefetch(reader, max_frames=64, max_bytes=2 * frame_size)
            try:
                prefetch.request(4)
                deadline = time.perf_counter() + 1
                while prefetch.status()["prefetch_frames"] != 2:
                    if time.perf_counter() > deadline:
                        self.fail("prefetch did not warm frames 4 and 5")
                    time.sleep(0.001)
                # The new 64-frame window still includes both old frames, but
                # their bytes must yield to frame 1 at the start of the window.
                prefetch.request(1)
                deadline = time.perf_counter() + 0.5
                frame = None
                while frame is None and time.perf_counter() < deadline:
                    frame = prefetch.take(1)
                    time.sleep(0.001)
                self.assertIsNotNone(
                    frame, "future frames exhausted the budget before frame 1"
                )
                self.assertEqual(frame[0]["index"], 1)
                status = prefetch.status()
                self.assertLessEqual(
                    status["prefetch_bytes"] + status["prefetch_in_flight_bytes"],
                    2 * frame_size,
                )
            finally:
                prefetch.close()
                prefetch._thread.join(1)


# Auto replay

"""Automatic smooth replay preparation and cache reuse."""


def make_config():
    return {
        "dataset": "semanticposs",
        "dataset_root": "/dataset",
        "sequence": "00",
        "map": {"policy": "distance_lod", "executable": "/backend/veyra_runtime"},
        "playback": {"fps": 30.0, "speed": 1.0, "full_sequence": True},
        "visualization": {"point_budget": 8, "cell_budget": 4},
        "pipeline": {"semantic": {"mode": "ground_truth"}},
    }


class AutoReplayTests(unittest.TestCase):
    def test_full_sequence_configuration_schedules_preparation_after_preview(self):
        config = make_config()
        runtime = ProductRuntime(Path.cwd())
        session = mock.Mock()
        session.status.return_value = {"frames": 488}
        with (
            mock.patch("runtime.service.validate_config", return_value=config),
            mock.patch.object(runtime, "_create_session", return_value=session),
        ):
            runtime._configure(config, prepare_replay=True)
        runtime._publish_status()
        self.assertEqual(runtime.status()["auto_replay"]["state"], "pending")
        self.assertEqual(runtime._auto_replay["state"], "pending")
        self.assertEqual(runtime._auto_replay_config, config)
        self.assertIsNone(runtime._auto_replay_thread)
        runtime.close()

    def test_ready_cache_requires_matching_configuration_and_frame_count(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as directory:
            path = cache_path(config, 2, Path(directory))
            self.assertIsNone(ready_cache(path, config, 2))
            path.parent.mkdir(parents=True, exist_ok=True)
            header = build_header(
                dataset="semanticposs",
                sequence="00",
                start=0,
                count=2,
                policy="distance_lod",
                semantic_provider={"mode": "ground_truth"},
                point_budget=8,
                cell_budget=4,
                perception_config_digest="pipeline",
                config_digest=config_digest(config),
                repo=None,
            )

            def write(extra):
                writer = ReplayWriter(path, {**header, **extra}, 2)
                for index in range(2):
                    writer.add_frame(
                        index, {"type": "visualization", "index": index}, b"frame"
                    )
                writer.close()

            # A cache from before whole-map folding holds a nearest-N disc.
            write({})
            self.assertIsNone(ready_cache(path, config, 2))
            write({"cell_selection": CELL_SELECTION})
            self.assertEqual(ready_cache(path, config, 2), path)
            changed = make_config()
            changed["playback"]["fps"] = 60.0
            self.assertIsNone(ready_cache(path, changed, 2))
            self.assertIsNone(ready_cache(path, config, 3))

    def test_configured_runtime_reuses_ready_cache_without_mapping_again(self):
        config = make_config()
        runtime = ProductRuntime(Path.cwd())
        runtime.config = config
        runtime.session = mock.Mock()
        runtime.session.status.return_value = {"frames": 2}
        runtime._auto_replay_config = config
        with (
            mock.patch(
                "runtime.auto_replay.cache_path",
                return_value=Path("/cache/ready.veyra-replay"),
            ),
            mock.patch(
                "runtime.auto_replay.ready_cache",
                return_value=Path("/cache/ready.veyra-replay"),
            ),
            mock.patch("runtime.auto_replay.prepare") as prepare,
        ):
            runtime._prepare_auto_replay()
        self.assertEqual(runtime.status()["auto_replay"]["state"], "ready")
        self.assertEqual(runtime.status()["auto_replay"]["frames"], 2)
        prepare.assert_not_called()
        runtime.close()

    def test_new_cache_prepares_in_background_and_announces_ready(self):
        config = make_config()
        runtime = ProductRuntime(Path.cwd())
        runtime.config = config
        runtime.session = mock.Mock()
        runtime.session.status.return_value = {"frames": 2}
        runtime._auto_replay_config = config
        path = Path("/cache/new.veyra-replay")
        with (
            mock.patch("runtime.auto_replay.cache_path", return_value=path),
            mock.patch("runtime.auto_replay.ready_cache", return_value=None),
            mock.patch("runtime.auto_replay.prepare", return_value=path) as prepare,
        ):
            runtime._prepare_auto_replay()
            runtime._auto_replay_thread.join(timeout=2)
        self.assertEqual(runtime.status()["auto_replay"]["state"], "ready")
        self.assertEqual(runtime.status()["auto_replay"]["path"], str(path))
        prepare.assert_called_once()
        runtime.close()

    def test_preparation_records_each_real_frame_and_publishes_complete_cache(self):
        config = make_config()
        frame = {
            "map": {"status": "available", "snapshot": {"active_leaf_count": 1}},
            "pipeline_status": {"semantic": "ground_truth"},
            "perception_timings_ms": {"total": 1.0},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "complete.veyra-replay"
            with (
                mock.patch("runtime.service.ProductRuntime") as runtime_type,
                mock.patch("runtime.auto_replay.pack_visualization") as pack,
            ):
                builder = runtime_type.return_value
                builder._frame_count.return_value = 2
                builder.generation = 1
                builder.session.frame_payload.return_value = frame
                builder.session.map_cells_binary.return_value = {"status": "available"}
                pack.side_effect = [
                    ({"type": "visualization", "index": 0}, b"first"),
                    ({"type": "visualization", "index": 1}, b"second"),
                ]
                progress = []
                result = prepare(
                    config,
                    Path.cwd(),
                    2,
                    path,
                    lambda done, total: progress.append((done, total)),
                    lambda: False,
                )
                self.assertEqual(result, path)
                self.assertEqual(progress, [(1, 2), (2, 2)])
                self.assertEqual(builder.session.frame_payload.call_count, 2)
                builder.close.assert_called_once()
            with ReplayReader(path, verify=True) as reader:
                self.assertEqual(len(reader), 2)
                self.assertEqual(reader.read_frame(1)[1], b"second")
                self.assertTrue(
                    reader.read_frame(0)[0]["recorded_telemetry"][
                        "recorded_during_cache_build"
                    ]
                )
            self.assertEqual(list(path.parent.glob("*.part")), [])

    def test_cancelled_preparation_removes_partial_cache(self):
        config = make_config()
        frame = {
            "map": {"status": "available", "snapshot": {}},
            "pipeline_status": {"semantic": "ground_truth"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cancelled.veyra-replay"
            done = []
            with (
                mock.patch("runtime.service.ProductRuntime") as runtime_type,
                mock.patch(
                    "runtime.auto_replay.pack_visualization",
                    return_value=({"type": "visualization", "index": 0}, b"frame"),
                ),
            ):
                builder = runtime_type.return_value
                builder._frame_count.return_value = 2
                builder.generation = 1
                builder.session.frame_payload.return_value = frame
                builder.session.map_cells_binary.return_value = {"status": "available"}
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    prepare(
                        config,
                        Path.cwd(),
                        2,
                        path,
                        lambda current, total: done.append(current),
                        lambda: bool(done),
                    )
            self.assertEqual(done, [1])
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob("*.part")), [])


# Prepare replay cache

"""Cache preparation must preserve the desktop session playback contract."""


class PrepareReplayCacheTests(unittest.TestCase):
    def test_default_cache_pipeline_matches_desktop_session_digest(self):
        args = parse_args(["--preset", "LowResource", "--fps", "30"])
        common = {
            "dataset": "generic",
            "dataset_root": "/tmp",
            "sequence": "demo",
            "preset": "LowResource",
            "playback": {"fps": 30, "full_sequence": True},
        }
        desktop = validate_config(
            {
                **common,
                "pipeline": {
                    "semantic": {"mode": "ground_truth"},
                    "ground": {
                        "enabled": True,
                        "parameter_overrides": {"min_range": 0, "max_range": 100},
                    },
                    "terrain": {"enabled": True},
                    "temporal": {"enabled": False},
                },
            },
            Path.cwd(),
            check_paths=False,
        )
        cache = validate_config(
            {**common, "pipeline": cache_pipeline(args)}, Path.cwd(), check_paths=False
        )
        self.assertEqual(config_digest(cache), config_digest(desktop))

    def test_cache_rate_uses_explicit_or_preset_value(self):
        for flags, expected in ((["--fps", "30"], 30), ([], 10)):
            with self.subTest(flags=flags):
                args = parse_args(["--preset", "LowResource", *flags])
                self.assertEqual(
                    cache_playback(args, PRESETS[args.preset]),
                    {"full_sequence": True, "fps": expected},
                )


# Demo export

"""Offline demo export: deterministic rendering of real cached snapshots."""


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_cache(directory, count=4):
    path = Path(directory) / "clip.veyra-replay"
    header = build_header(
        dataset="semanticposs",
        sequence="00",
        start=0,
        count=count,
        policy="distance_lod",
        semantic_provider={"mode": "ground_truth"},
        point_budget=64,
        cell_budget=8,
        perception_config_digest="p",
        config_digest="c",
        repo=None,
    )
    writer = ReplayWriter(path, header, count)
    rng = np.random.default_rng(7)
    for position in range(count):
        points = np.zeros((64, 17), dtype="<f4")
        points[:, 0] = rng.uniform(-20, 20, 64) + position  # drift, real per-frame data
        points[:, 1] = rng.uniform(-20, 20, 64)
        points[:, 2] = rng.uniform(-2, 3, 64)
        points[:, 4] = rng.integers(0, 20, 64)
        cells = np.zeros((8, 17), dtype="<f4")
        cells[:, 0] = rng.uniform(-20, 20, 8)
        cells[:, 1] = rng.uniform(-20, 20, 8)
        cells[:, 3] = 0.4
        payload = points.tobytes() + cells.tobytes()
        metadata = {
            "type": "visualization",
            "schema_version": 3,
            "generation": 1,
            "index": position,
            "points": {"count": 64, "offset": 0, "stride": 68},
            "cells": {"count": 8, "offset": 64 * 68, "stride": 68},
            "pose": [1, 0, 0, float(position)] + [0] * 12,
        }
        writer.add_frame(position, metadata, payload)
    writer.close()
    return path


class DemoExportTests(unittest.TestCase):
    def test_decode_round_trip_matches_cache_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            from runtime.replay_cache import ReplayReader

            path = build_cache(directory)
            with ReplayReader(path) as reader:
                meta, payload = reader.read_frame(2)
                points = decode_points(payload, meta)
                cells = decode_cells(payload, meta)
                self.assertEqual(points.shape, (64, 17))
                self.assertEqual(cells.shape, (8, 17))
                # Per-frame motion is real cached data, not interpolated.
                meta0, payload0 = reader.read_frame(0)
                self.assertGreater(
                    points[:, 0].mean(), decode_points(payload0, meta0)[:, 0].mean()
                )

    def test_rasterize_is_deterministic_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            from runtime.replay_cache import ReplayReader

            path = build_cache(directory)
            with ReplayReader(path) as reader:
                meta, payload = reader.read_frame(1)
                points = decode_points(payload, meta)
                cells = decode_cells(payload, meta)
                bounds = (-30.0, 30.0, -30.0, 30.0)
                first = rasterize(
                    points, cells, meta["pose"], width=320, height=180, bounds=bounds
                )
                second = rasterize(
                    points, cells, meta["pose"], width=320, height=180, bounds=bounds
                )
                np.testing.assert_array_equal(first, second)
                self.assertEqual(first.shape, (180, 320, 3))
                # Something actually drew (not a blank canvas).
                self.assertGreater((first != np.array([11, 18, 25])).sum(), 100)

    def test_ppm_frames_encode_to_mp4(self):
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("ffmpeg is not installed")
        with tempfile.TemporaryDirectory() as directory:
            from runtime.replay_cache import ReplayReader

            path = build_cache(directory, count=6)
            frames = Path(directory) / "frames"
            frames.mkdir()
            with ReplayReader(path) as reader:
                for number in range(len(reader)):
                    meta, payload = reader.read_frame(number)
                    img = rasterize(
                        decode_points(payload, meta),
                        decode_cells(payload, meta),
                        meta["pose"],
                        width=320,
                        height=180,
                        bounds=(-30.0, 30.0, -30.0, 30.0),
                    )
                    write_ppm(frames / f"frame_{number + 1:06d}.ppm", img)
            clip = Path(directory) / "demo.mp4"
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-framerate",
                    "30",
                    "-i",
                    str(frames / "frame_%06d.ppm"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(clip),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertGreater(clip.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
