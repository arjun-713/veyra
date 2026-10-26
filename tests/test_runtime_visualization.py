"""Runtime visualization regression suite."""

import dataclasses
import os
import struct
import unittest
from unittest.mock import patch

import numpy as np

from benchmarks import protocol
from benchmarks.test_runtime import frame as make_frame
from runtime.telemetry import Telemetry, processing_fps, rss_bytes
from runtime.visualization import pack_visualization

# Runtime visualization


class RuntimeVisualizationTests(unittest.TestCase):
    def test_visualization_payload_preserves_enriched_perception_fields(self):
        frame = {
            "shown": 1,
            "points": np.array([[1, 2, 3]], dtype=np.float32),
            "intensity": np.array([0.4], dtype=np.float32),
            "semantic_labels": np.array([9], dtype=np.int32),
            "raw_semantic_labels": np.array([42], dtype=np.int32),
            "ground": np.array([True]),
            "drivable": np.array(["non_drivable"]),
            "semantic_confidence": np.array([0.8], dtype=np.float32),
            "slope": np.array([0.2], dtype=np.float32),
            "roughness": np.array([0.3], dtype=np.float32),
            "height_complexity": np.array([0.4], dtype=np.float32),
            "motion_probability": np.array([0.5], dtype=np.float32),
            "velocity_xy": np.array([[1.2, -0.7]], dtype=np.float32),
            "observation_quality": np.array([0.6], dtype=np.float32),
            "terrain_confidence": np.array([0.7], dtype=np.float32),
            "step": np.array([0.9], dtype=np.float32),
            "pipeline_status": {
                "semantic": "model",
                "ground": "available",
                "terrain": "available",
                "temporal": "available",
                "diagnostics": [],
            },
            "index": 0,
            "dataset": "fixture",
            "seq": "00",
            "id": "000000",
            "pose": {
                "available": True,
                "matrix": np.eye(4).reshape(-1).tolist(),
                "provenance": {
                    "coordinate_frame": "world",
                    "timestamp_source": "dataset",
                    "pose_source": "dataset",
                    "calibration_source": "dataset",
                },
            },
            "n_points": 1,
        }
        cells = {
            "status": "available",
            "cells": [
                {
                    "l": 1,
                    "ix": -2,
                    "iy": 3,
                    "z": 4.5,
                    "zmin": 4.1,
                    "zmax": 4.9,
                    "zvar": 0.04,
                    "n": 42,
                    "c": 9,
                    "m": 0.25,
                    "q": 0.8,
                    "drivable_evidence": -0.4,
                    "u": 0.7,
                    "semantic_confidence": 0.9,
                    "ground_evidence": 0.6,
                    "terrain_confidence": 0.5,
                    "geometry_complexity": 0.3,
                    "physical_layers": [
                        1,
                        0,
                        0,
                        0,
                        0,
                        1,
                        0.3,
                        0.3,
                        0.3,
                        0,
                        1,
                        3,
                        3,
                        3,
                        0,
                    ],
                }
            ],
        }

        metadata, payload = pack_visualization(frame, cells, 1)

        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(metadata["points"], {"count": 1, "offset": 0, "stride": 68})
        self.assertEqual(
            metadata["cells"], {"count": 1, "offset": 17 * 4, "stride": 68}
        )
        self.assertEqual(metadata["provenance"]["timestamp_source"], "dataset")
        values = np.frombuffer(payload, dtype="<f4", count=17)
        np.testing.assert_allclose(
            values,
            [1, 2, 3, 0.4, 9, 42, 1, 2, 0.8, 0.2, 0.3, 0.4, 0.5, 1.2, -0.7, 0.6, 0.7],
        )
        mapped = np.frombuffer(payload, dtype="<f4", offset=17 * 4, count=17)
        np.testing.assert_allclose(
            mapped,
            [
                -0.15,
                0.35,
                4.5,
                0.1,
                9,
                0.25,
                0.8,
                -0.4,
                0.7,
                0.9,
                0.6,
                0.5,
                0.3,
                42,
                4.1,
                4.9,
                0.04,
            ],
        )
        self.assertEqual(
            metadata.get("physical_layers"),
            {"version": 1, "count": 1, "offset": 136, "stride": 60},
        )
        layers = np.frombuffer(payload, dtype="<f4", offset=136)
        np.testing.assert_allclose(layers, cells["cells"][0]["physical_layers"])

    def test_visualization_cell_rows_use_nan_for_fields_an_older_engine_omits(self):
        frame = {
            "shown": 0,
            "points": np.empty((0, 3), dtype=np.float32),
            "intensity": np.empty(0, dtype=np.float32),
            "semantic_labels": np.empty(0, dtype=np.int32),
            "raw_semantic_labels": np.empty(0, dtype=np.int32),
            "ground": np.empty(0, dtype=bool),
            "drivable": np.empty(0, dtype="U12"),
            "semantic_confidence": np.empty(0, dtype=np.float32),
            "slope": np.empty(0, dtype=np.float32),
            "roughness": np.empty(0, dtype=np.float32),
            "height_complexity": np.empty(0, dtype=np.float32),
            "motion_probability": np.empty(0, dtype=np.float32),
            "velocity_xy": np.empty((0, 2), dtype=np.float32),
            "observation_quality": np.empty(0, dtype=np.float32),
            "terrain_confidence": np.empty(0, dtype=np.float32),
            "step": np.empty(0, dtype=np.float32),
            "pipeline_status": {
                "semantic": "ground_truth",
                "ground": "unavailable",
                "terrain": "unavailable",
                "temporal": "unavailable",
                "diagnostics": [],
            },
            "index": 0,
            "dataset": "fixture",
            "seq": "00",
            "id": "000000",
            "pose": {
                "available": False,
                "matrix": np.eye(4).reshape(-1).tolist(),
                "provenance": {
                    "coordinate_frame": "lidar",
                    "timestamp_source": "absent",
                    "pose_source": "absent",
                    "calibration_source": "absent",
                },
            },
            "n_points": 0,
        }
        cells = {
            "status": "available",
            "cells": [
                {
                    "l": 0,
                    "ix": 0,
                    "iy": 0,
                    "z": 1.0,
                    "c": 0,
                    "m": 0.0,
                    "q": 0.0,
                    "d": 0.0,
                    "u": 0.0,
                }
            ],
        }
        metadata, payload = pack_visualization(frame, cells, 1)
        self.assertEqual(metadata["schema_version"], 3)
        self.assertNotIn("physical_layers", metadata)
        mapped = np.frombuffer(payload, dtype="<f4", offset=0, count=17)
        # Legacy ``d`` alias is honored; absent evidence stays NaN (Unavailable).
        self.assertEqual(mapped[7], 0.0)
        for position in (9, 10, 11, 12, 13, 14, 15, 16):
            self.assertTrue(np.isnan(mapped[position]))


# Runtime buffer reuse

"""Buffer-reusing runtime encoders must emit exactly the original bytes."""


def _reference_binary_frame(frame):
    """The pre-reuse encoder: structured array, np.select, tobytes, concat."""

    count = len(frame.points)
    missing = (1 << 64) - 1

    def stamp(value):
        return missing if value is None else round(float(value) * 1_000_000)

    source = int(frame.frame_id) if frame.frame_id.isdecimal() else missing
    header = struct.pack(
        "<QQQ16d",
        stamp(frame.timestamp),
        stamp(frame.pose.timestamp),
        source,
        *frame.pose.matrix.reshape(-1),
    )
    points = np.empty(count, dtype=protocol._BINARY_POINT)
    protocol._fill_binary_points(points, frame)
    for field, values, mapping in (
        ("drivable", frame.drivable, protocol._DRIVABLE),
        ("state", frame.motion_state, protocol._MOTION_STATE),
    ):
        points[field] = np.select(
            [values == key for key in mapping], list(mapping.values()), default=255
        )
    return f"B {count}\n".encode("ascii") + header + points.tobytes()


def _resized(frame, count, seed):
    rng = np.random.default_rng(seed)
    index = rng.integers(0, len(frame.points), count)
    replaced = {}
    for field in dataclasses.fields(frame):
        value = getattr(frame, field.name)
        if isinstance(value, np.ndarray) and value.shape[:1] == frame.points.shape[:1]:
            replaced[field.name] = value[index]
    replaced["drivable"] = np.array(["drivable", "non_drivable", "unknown"])[
        rng.integers(0, 3, count)
    ]
    replaced["motion_state"] = np.array(
        ["static", "possibly_moving", "moving", "unknown"]
    )[rng.integers(0, 4, count)]
    return dataclasses.replace(frame, **replaced)


class BinaryFrameEncoderTest(unittest.TestCase):
    def test_reused_buffer_matches_reference_bytes_across_sizes(self):
        base = make_frame()
        encoder = protocol.BinaryFrameEncoder()
        capacities = []
        for seed, count in enumerate((5000, 5100, 300, 0, 6000)):
            frame = _resized(base, count, seed) if count else base
            expected = _reference_binary_frame(frame)
            self.assertEqual(bytes(encoder.encode(frame)), expected)
            self.assertEqual(protocol.binary_frame_bytes(frame), expected)
            known = np.count_nonzero(
                np.isin(frame.drivable, ("drivable", "non_drivable"))
            )
            self.assertEqual(encoder.known_drivability_points, known)
            capacities.append(encoder.capacity)
        # Headroom absorbs the slightly larger frame and smaller frames reuse it.
        self.assertEqual(capacities[0], capacities[1])
        self.assertEqual(capacities[1], capacities[2])
        self.assertEqual(capacities[2], capacities[3])


class RuntimeEncodingTest(unittest.TestCase):
    def test_head_plus_payload_equals_encoded_message(self):
        from runtime.protocol import encode_head, encode_message

        payload = bytearray(struct.pack("<4f", 1, 2, 3, 4))
        metadata = {"type": "visualization", "index": 3}
        self.assertEqual(
            encode_head(metadata, payload) + payload,
            encode_message(metadata, payload),
        )
        self.assertEqual(
            encode_head({"type": "status"}), encode_message({"type": "status"})
        )

    def test_string_counts_match_numpy_unique(self):
        from runtime.telemetry import _STRING_COUNT_VOCABULARY, _string_counts

        rng = np.random.default_rng(3)
        words = np.array(["unknown", "drivable", "non_drivable", "moving", "b", "a"])
        diverse = np.array([f"label{i}" for i in range(_STRING_COUNT_VOCABULARY + 4)])
        for array in (
            words[rng.integers(0, len(words), 1000)],
            words[:1].repeat(7),
            diverse[rng.integers(0, len(diverse), 500)],
        ):
            unique, amounts = np.unique(array, return_counts=True)
            expected = {str(v): int(a) for v, a in zip(unique, amounts)}
            got = _string_counts(array)
            self.assertEqual(got, expected)
            self.assertEqual(list(got), list(expected))

    def test_physical_layer_payload_keeps_cell_order_across_frames(self):
        from runtime.visualization import pack_visualization

        frame = {
            "shown": 0,
            "points": np.empty((0, 3), dtype=np.float32),
            "intensity": np.empty(0, dtype=np.float32),
            "semantic_labels": np.empty(0, dtype=np.int32),
            "raw_semantic_labels": np.empty(0, dtype=np.int32),
            "ground": np.empty(0, dtype=bool),
            "drivable": np.empty(0, dtype="U12"),
            "semantic_confidence": np.empty(0, dtype=np.float32),
            "slope": np.empty(0, dtype=np.float32),
            "roughness": np.empty(0, dtype=np.float32),
            "height_complexity": np.empty(0, dtype=np.float32),
            "motion_probability": np.empty(0, dtype=np.float32),
            "velocity_xy": np.empty((0, 2), dtype=np.float32),
            "observation_quality": np.empty(0, dtype=np.float32),
            "terrain_confidence": np.empty(0, dtype=np.float32),
            "pipeline_status": {
                "semantic": "unavailable",
                "ground": "unavailable",
                "terrain": "unavailable",
                "temporal": "unavailable",
                "diagnostics": [],
            },
            "index": 0,
            "dataset": "fixture",
            "seq": "00",
            "id": "000000",
            "pose": {
                "available": False,
                "matrix": np.eye(4).reshape(-1),
                "provenance": {},
            },
            "n_points": 0,
        }
        rows = []
        for index, x in enumerate((10, 20)):
            rows.append(
                {
                    "l": 2,
                    "ix": index,
                    "iy": 0,
                    "z": float(x),
                    "c": 0,
                    "m": 0.0,
                    "q": 1.0,
                    "d": 0.0,
                    "u": 0.0,
                    "physical_layers": [float(index + 1)] * 15,
                }
            )
        cells = {"status": "available", "cells": rows}

        first_metadata, first_payload = pack_visualization(frame, cells, 1)
        second_metadata, second_payload = pack_visualization(frame, cells, 2)
        self.assertEqual(first_payload, second_payload)
        self.assertEqual(first_metadata["physical_layers"]["count"], 2)
        self.assertEqual(second_metadata["physical_layers"]["offset"], 136)
        physical = np.frombuffer(
            second_payload,
            dtype="<f4",
            offset=second_metadata["physical_layers"]["offset"],
        ).reshape(2, 15)
        np.testing.assert_array_equal(physical[:, 0], [1, 2])


# Runtime telemetry


class RuntimeTelemetryTests(unittest.TestCase):
    def test_report_exposes_monotonic_elapsed_time_separate_from_wall_clock(self):
        telemetry = Telemetry()
        telemetry.started_at = 100.0
        with (
            patch("runtime.telemetry.time.monotonic", return_value=102.5),
            patch("runtime.telemetry.time.time", return_value=1_800_000_000.0),
        ):
            report = telemetry.report(
                {
                    "state": "running",
                    "index": 0,
                    "frames": 1,
                    "queue_depth": 0,
                    "dropped_frames": 0,
                    "visualization_dropped": 0,
                },
                {"map": {"metrics": {}, "snapshot": {}}},
                None,
                None,
            )

        self.assertEqual(report["elapsed_ms"], 2500.0)
        self.assertEqual(report["timestamp"], 1_800_000_000.0)

    def test_report_preserves_mapper_latency_sample_count_for_percentile_gate(self):
        report = Telemetry().report(
            {
                "state": "running",
                "index": 18,
                "frames": 20,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "map": {
                    "metrics": {
                        "map_update_latency_ns": {
                            "count": 20,
                            "p50": 5_000_000,
                            "p95": 9_000_000,
                        }
                    },
                    "snapshot": {},
                }
            },
            None,
            None,
        )
        self.assertEqual(report["latency_ms"]["mapping_samples"], 20)
        self.assertEqual(report["latency_ms"]["mapping_p50"], 5.0)
        self.assertEqual(report["latency_ms"]["mapping_p95"], 9.0)

    def test_rss_measurement_reads_the_named_process(self):
        self.assertGreater(rss_bytes(os.getpid()), 0)

    def test_report_keeps_stage_status_backend_and_provenance_separate(self):
        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "pipeline_status": {
                    "semantic": "model",
                    "ground": "available",
                    "terrain": "skipped",
                    "temporal": "unavailable",
                },
                "perception_timings_ms": {"semantic": 12.0},
                "pose": {
                    "provenance": {
                        "coordinate_frame": "lidar",
                        "timestamp_source": "absent",
                        "pose_source": "identity_absent",
                        "calibration_source": "identity_absent",
                    }
                },
                "map": {"metrics": {}, "snapshot": {}},
            },
            None,
            None,
        )
        self.assertEqual(report["perception"]["backend"], "model")
        self.assertEqual(report["perception"]["status"]["terrain"], "skipped")
        self.assertEqual(
            report["perception"]["provenance"]["timestamp_source"], "absent"
        )

    def test_report_exposes_measured_perception_evidence_without_fabricating_tracks(
        self,
    ):
        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "n_points": 4,
                "ground": [1, 1, 0, 0],
                "semantic_labels": [0, 1, 1, 6],
                "semantic_confidence": [0.0, 0.8, 0.9, 0.7],
                "drivable": ["drivable", "drivable", "unknown", "non_drivable"],
                "motion_state": ["STATIC", "STATIC", "MOVING", "STATIC"],
                "pipeline_status": {
                    "semantic": "model",
                    "ground": "pypatchworkpp.patchworkpp",
                },
                "perception_timings_ms": {},
                "map": {"snapshot": {"active_leaf_count": 1}, "metrics": {}},
            },
            None,
            None,
            {"provider": "salsanext", "execution_provider": "CPUExecutionProvider"},
        )
        self.assertEqual(report["perception"]["points"], 4)
        self.assertEqual(report["perception"]["ground_ratio"], 0.5)
        self.assertAlmostEqual(report["perception"]["semantic_confidence_mean"], 0.6)
        self.assertEqual(report["perception"]["drivable_counts"]["unknown"], 1)
        self.assertIsNone(report["perception"]["track_counts"])
        self.assertEqual(report["health"]["mapper"], "available")

    def test_missing_ground_status_is_fail_closed_not_measured(self):
        # Regression pin for PR #41 review (arjun-713) / PR #42 da881f6:
        # the real PipelineStatus dataclass + viewer serializer always emit
        # all four stage keys, so a missing "ground" key means unknown
        # provenance (synthetic input or dropped-key plumbing fault) and must
        # stay UNAVAILABLE instead of rendering a ratio from the array.
        report = Telemetry().report(
            {
                "state": "paused",
                "index": 0,
                "frames": 1,
                "queue_depth": 0,
                "dropped_frames": 0,
                "visualization_dropped": 0,
            },
            {
                "n_points": 4,
                "ground": [1, 1, 0, 0],
                "semantic_labels": [0, 1, 1, 6],
                "pipeline_status": {"semantic": "model"},
                "perception_timings_ms": {},
                "map": {"snapshot": {"active_leaf_count": 1}, "metrics": {}},
            },
            None,
            None,
        )
        self.assertIsNone(report["perception"]["ground_ratio"])


class ProcessingFpsTests(unittest.TestCase):
    def test_idle_time_before_playback_does_not_dilute_throughput(self):
        # One preview frame, a 60 s pause, then ten frames at 2 fps.
        completed = [0.0] + [60.0 + 0.5 * index for index in range(10)]
        self.assertAlmostEqual(processing_fps(completed), 2.0)

    def test_fewer_than_two_recent_completions_is_unavailable(self):
        self.assertIsNone(processing_fps([]))
        self.assertIsNone(processing_fps([0.0, 30.0]))


if __name__ == "__main__":
    unittest.main()
