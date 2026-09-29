"""Offline demo export: deterministic rendering of real cached snapshots."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.replay_cache import ReplayWriter, build_header
from scripts.export_demo_clip import (
    decode_cells,
    decode_points,
    rasterize,
    write_ppm,
)


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
