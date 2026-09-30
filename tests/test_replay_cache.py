"""Replay cache schema, provenance, ordering and corruption tests."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

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

    def test_policy_mismatch_invalidates_cache(self):
        header = make_header()
        reason = check_compatible(header, policy="distance_lod")
        self.assertIn("distance_lod", reason)
        self.assertIn("utility_lod", reason)

    def test_config_change_invalidates_cache(self):
        header = make_header()
        reason = check_compatible(header, policy="utility_lod", config_digest="changed")
        self.assertIn("rebuild", reason)

    def test_matching_config_is_compatible(self):
        header = make_header()
        self.assertIsNone(
            check_compatible(header, policy="utility_lod", config_digest="def")
        )

    def test_missing_provenance_rejected(self):
        header = make_header()
        del header["policy"]
        with (
            self.assertRaisesRegex(ValueError, "provenance"),
            tempfile.TemporaryDirectory() as directory,
        ):
            ReplayWriter(Path(directory) / "x.veyra-replay", header, 1)

    def test_corrupt_magic_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory)
            raw = bytearray(path.read_bytes())
            raw[0:8] = b"NOTVEYRA"
            path.write_bytes(bytes(raw))
            with self.assertRaisesRegex(ReplayError, "magic"):
                ReplayReader(path)

    def test_truncated_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.write_cache(directory)
            raw = path.read_bytes()
            path.write_bytes(raw[: len(raw) // 2])
            with self.assertRaisesRegex(ReplayError, "truncat|outside"):
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


if __name__ == "__main__":
    unittest.main()
