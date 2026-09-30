"""Cache preparation must preserve the desktop session playback contract."""

import unittest

from pathlib import Path

from runtime.config import PRESETS, config_digest, validate_config
from scripts.prepare_replay_cache import cache_pipeline, cache_playback, parse_args


class PrepareReplayCacheTests(unittest.TestCase):
    def test_default_cache_pipeline_matches_desktop_session_digest(self):
        args = parse_args(["--preset", "LowResource", "--fps", "30"])
        common = {
            "dataset": "generic", "dataset_root": "/tmp", "sequence": "demo",
            "preset": "LowResource", "playback": {"fps": 30, "full_sequence": True},
        }
        desktop = validate_config({
            **common,
            "pipeline": {
                "semantic": {"mode": "ground_truth"},
                "ground": {"enabled": True, "parameter_overrides": {"min_range": 0, "max_range": 100}},
                "terrain": {"enabled": True}, "temporal": {"enabled": False},
            },
        }, Path.cwd(), check_paths=False)
        cache = validate_config({**common, "pipeline": cache_pipeline(args)}, Path.cwd(), check_paths=False)
        self.assertEqual(config_digest(cache), config_digest(desktop))

    def test_explicit_rate_is_recorded_in_cache_configuration(self):
        args = parse_args(["--preset", "LowResource", "--fps", "30"])
        self.assertEqual(
            cache_playback(args, PRESETS[args.preset]),
            {"full_sequence": True, "fps": 30},
        )

    def test_preset_rate_remains_available_for_existing_invocations(self):
        args = parse_args(["--preset", "LowResource"])
        self.assertEqual(
            cache_playback(args, PRESETS[args.preset]),
            {"full_sequence": True, "fps": 10},
        )


if __name__ == "__main__":
    unittest.main()
