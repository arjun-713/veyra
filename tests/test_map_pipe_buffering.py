import io
import json
import queue
import unittest
from types import SimpleNamespace

from viewer.runtime import PersistentMapEngine


class MapPipeBufferingTests(unittest.TestCase):
    def test_large_response_is_read_in_chunks_without_losing_records(self):
        class CountingPipe(io.RawIOBase):
            def __init__(self, data):
                self.data = io.BytesIO(data)
                self.calls = 0

            def readable(self):
                return True

            def readinto(self, buffer):
                self.calls += 1
                return self.data.readinto(buffer)

        expected = {"status": "ok", "payload": "x" * 200_000}
        pipe = CountingPipe((json.dumps(expected) + '\n{"status":"next"}\n').encode())
        responses = queue.Queue()
        process = SimpleNamespace(stdout=pipe, poll=lambda: 0)
        PersistentMapEngine._read_stdout(None, process, responses)
        self.assertEqual(responses.get_nowait(), expected)
        self.assertEqual(responses.get_nowait(), {"status": "next"})
        self.assertEqual(responses.get_nowait()["status"], "unavailable")
        self.assertLess(pipe.calls, 20, "pipe must not issue a read per byte")
