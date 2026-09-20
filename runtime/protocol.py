"""Bounded, versioned local transport. All binary quantities are little endian."""

from __future__ import annotations

import json
import struct
import threading
from collections import deque

HEADER = struct.Struct("<4sHHII")
MAX_METADATA = 1024 * 1024
MAX_PAYLOAD = 32 * 1024 * 1024
MAX_REQUEST = 65536


def encode_message(metadata: dict, payload: bytes = b"") -> bytes:
    data = json.dumps(metadata, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_METADATA or len(payload) > MAX_PAYLOAD:
        raise ValueError("message size exceeds protocol limit")
    return (
        HEADER.pack(b"VYRA", 1, 2 if payload else 1, len(data), len(payload))
        + data
        + payload
    )


def _read_exact(stream, count):
    chunks = bytearray()
    while len(chunks) < count:
        chunk = stream.read(count - len(chunks))
        if not chunk:
            raise EOFError("truncated runtime message")
        chunks.extend(chunk)
    return bytes(chunks)


def read_message(stream):
    magic, version, kind, metadata_size, payload_size = HEADER.unpack(
        _read_exact(stream, HEADER.size)
    )
    if magic != b"VYRA" or version != 1 or kind not in (1, 2):
        raise ValueError("unsupported runtime protocol")
    if metadata_size > MAX_METADATA or payload_size > MAX_PAYLOAD:
        raise ValueError("message size exceeds protocol limit")
    metadata = json.loads(_read_exact(stream, metadata_size))
    if not isinstance(metadata, dict):
        raise TypeError("metadata must be an object")
    return metadata, _read_exact(stream, payload_size)


class Outbox:
    """Control responses are bounded; telemetry and visualization are latest-only."""

    def __init__(self, capacity=64):
        self.capacity = capacity
        self._control = deque()
        self._latest = {}
        self._condition = threading.Condition()
        self.closed = False
        self.visualization_dropped = 0

    def publish(self, metadata, payload=b""):
        with self._condition:
            if self.closed:
                return False
            kind = metadata.get("type")
            if kind in ("visualization", "telemetry", "status"):
                if kind == "visualization" and kind in self._latest:
                    self.visualization_dropped += 1
                self._latest[kind] = (metadata, payload)
            else:
                if len(self._control) >= self.capacity:
                    raise BufferError("control response queue is full")
                self._control.append((metadata, payload))
            self._condition.notify()
            return True

    def take(self, timeout=None):
        with self._condition:
            self._condition.wait_for(
                lambda: self._control or self._latest or self.closed, timeout
            )
            if self._control:
                return self._control.popleft()
            for kind in ("status", "telemetry", "visualization"):
                if kind in self._latest:
                    return self._latest.pop(kind)
            return None

    def close(self):
        with self._condition:
            self.closed = True
            self._condition.notify_all()
