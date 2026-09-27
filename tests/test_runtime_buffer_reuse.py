"""Buffer-reusing runtime encoders must emit exactly the original bytes."""

import dataclasses
import struct
import unittest

import numpy as np

from benchmarks import protocol
from benchmarks.test_runtime import frame as make_frame


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


if __name__ == "__main__":
    unittest.main()
