import tempfile
import unittest
from pathlib import Path


class LowResourceRuntimeTests(unittest.TestCase):
    def test_default_config_is_persistent_low_resource_and_limits_playback(self):
        from runtime.config import validate_config

        config = validate_config(
            {
                "dataset": "generic",
                "dataset_root": "/tmp",
                "sequence": "demo",
            },
            Path.cwd(),
            check_paths=False,
        )

        self.assertEqual(config["preset"], "LowResource")
        self.assertEqual(config["map"]["policy"], "distance_lod")
        self.assertEqual(
            config["visualization"],
            {
                "point_budget": 15000,
                "cell_budget": 10000,
                "update_hz": 2.0,
                "max_in_flight": 1,
            },
        )
        self.assertEqual(config["playback"]["frame_limit"], 30)
        self.assertFalse(config["playback"]["full_sequence"])

    def test_full_sequence_is_an_explicit_override(self):
        from runtime.config import validate_config

        config = validate_config(
            {
                "dataset": "generic",
                "dataset_root": "/tmp",
                "sequence": "demo",
                "playback": {"full_sequence": True},
            },
            Path.cwd(),
            check_paths=False,
        )

        self.assertTrue(config["playback"]["full_sequence"])
        self.assertEqual(config["playback"]["frame_limit"], 30)

    def test_command_visual_is_not_throttled_but_playback_visual_is(self):
        import time

        from runtime.config import validate_config
        from runtime.service import ProductRuntime

        runtime = ProductRuntime(Path.cwd())
        runtime.config = validate_config(
            {"dataset": "generic", "dataset_root": "/tmp", "sequence": "demo"},
            Path.cwd(),
            check_paths=False,
        )
        runtime.last_visual = time.monotonic()
        try:
            self.assertTrue(runtime._should_publish_visual(force_visual=True))
            self.assertFalse(runtime._should_publish_visual(force_visual=False))
        finally:
            runtime.close()

    def test_seek_outside_default_window_is_rejected_for_a_small_session(self):
        from runtime.config import validate_config
        from runtime.service import ProductRuntime
        from tests.test_runtime_player import RuntimePlayerTests, _write_frame

        runtime = ProductRuntime(Path.cwd())
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(31):
                _write_frame(root, "00000", f"{index:06d}", float(index))
            _write_frame(root, "00001", "000000", 0.0)
            runtime.session = RuntimePlayerTests()._runtime(root)
            runtime.config = validate_config(
                {"dataset": "rellis3d", "dataset_root": str(root), "sequence": "00000"},
                Path.cwd(),
                check_paths=False,
            )
            runtime._publish_status()
            response = runtime.handle(
                {"id": "seek", "command": "seek", "args": {"index": 30}}
            )
            self.assertFalse(response["ok"])
            self.assertIn("between 0 and 29", response["error"]["message"])
            runtime.close()

    def test_runtime_rejects_a_second_frame_while_one_is_in_flight(self):
        from runtime.service import ProductRuntime

        runtime = ProductRuntime(Path.cwd())
        runtime._frame_in_flight.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "frame already in flight"):
                runtime._process(0)
        finally:
            runtime._frame_in_flight.release()
            runtime.close()


if __name__ == "__main__":
    unittest.main()
