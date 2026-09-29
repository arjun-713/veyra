"""Visibility clearing must survive the shared product configuration boundary."""

import tempfile
import unittest
from pathlib import Path

from runtime.config import validate_config


class ClearingConfigTests(unittest.TestCase):
    def test_shared_service_forwards_clearing_to_the_persistent_mapper(self):
        from runtime.service import ProductRuntime
        from tests.test_engine_service import RUNTIME_RELATIVE, require_binary
        from tests.test_runtime_player import _write_frame

        # The Python-only CI job does not build the C++ mapper; an unbuilt
        # binary is a missing prerequisite, not a product defect.
        require_binary(self, "VEYRA_RUNTIME_BINARY", RUNTIME_RELATIVE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_frame(root, "00000", "000000", 0)
            config = validate_config(
                {
                    "dataset": "rellis3d",
                    "dataset_root": str(root),
                    "sequence": "00000",
                    "map": {"clear_free_space": True},
                },
                Path.cwd(),
                check_paths=False,
            )
            runtime = ProductRuntime(Path.cwd())
            session = runtime._create_session(config)
            try:
                self.assertTrue(session.map_runner.clear_free_space)
            finally:
                session.close()
                runtime.close()

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
