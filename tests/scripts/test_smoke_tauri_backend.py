import unittest

from runtime.protocol import encode_message


class SmokeTauriBackendTests(unittest.TestCase):
    def test_requires_a_successful_matching_status_not_merely_vyra_magic(self):
        from scripts.smoke_tauri_backend import validate_runtime_output

        status = {
            "type": "response",
            "id": "release-smoke",
            "ok": True,
            "result": {"state": "unconfigured", "error": None},
        }
        self.assertEqual(
            validate_runtime_output(encode_message(status)), status["result"]
        )
        for response in (
            {**status, "ok": False},
            {**status, "id": "different-request"},
            {**status, "result": {"state": "error", "error": "backend missing"}},
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                validate_runtime_output(encode_message(response))

    def test_rejects_empty_malformed_or_truncated_transport(self):
        from scripts.smoke_tauri_backend import validate_runtime_output

        packet = encode_message(
            {
                "type": "response",
                "id": "release-smoke",
                "ok": True,
                "result": {"state": "unconfigured"},
            }
        )
        for data in (b"", b"VYRA", packet[:-1], b"BAD!" + packet[4:]):
            with self.subTest(data=data), self.assertRaises((ValueError, EOFError)):
                validate_runtime_output(data)
