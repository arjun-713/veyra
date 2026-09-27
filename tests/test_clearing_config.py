"""Visibility clearing must survive the shared product configuration boundary."""

import unittest
from pathlib import Path

from runtime.config import validate_config


class ClearingConfigTests(unittest.TestCase):
    def test_explicit_opt_in_survives_normalization_and_bad_types_are_rejected(self):
        base = {"dataset": "generic", "dataset_root": "/tmp", "sequence": "00"}
        for enabled in (False, True):
            config = validate_config(
                {**base, "map": {"clear_free_space": enabled}},
                Path.cwd(),
                check_paths=False,
            )
            self.assertIs(config["map"]["clear_free_space"], enabled)
        self.assertFalse(
            validate_config(base, Path.cwd(), check_paths=False)["map"][
                "clear_free_space"
            ]
        )
        for invalid in ("false", 1, None):
            with self.assertRaisesRegex(TypeError, "boolean"):
                validate_config(
                    {**base, "map": {"clear_free_space": invalid}},
                    Path.cwd(),
                    check_paths=False,
                )
