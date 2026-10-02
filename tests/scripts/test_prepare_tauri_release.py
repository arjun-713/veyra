import json
import tempfile
import unittest
from pathlib import Path


class PrepareTauriReleaseTests(unittest.TestCase):
    def test_main_push_has_a_unique_stable_version_and_reruns_keep_it(self):
        from scripts.prepare_tauri_release import resolve_release

        for _ in range(2):
            self.assertEqual(
                resolve_release("0.1.0", "push", "refs/heads/main", 12),
                {"version": "0.1.12", "tag": "v0.1.12", "prerelease": False},
            )
        self.assertEqual(
            resolve_release("0.1.0", "push", "refs/heads/main", 13)["version"], "0.1.13"
        )

    def test_explicit_tag_and_manual_channels_preserve_semver(self):
        from scripts.prepare_tauri_release import resolve_release

        self.assertEqual(
            resolve_release("0.1.0", "push", "refs/tags/v0.2.0-rc.1", 1),
            {"version": "0.2.0-rc.1", "tag": "v0.2.0-rc.1", "prerelease": True},
        )
        self.assertEqual(
            resolve_release(
                "0.1.0", "workflow_dispatch", "refs/heads/main", 2, "v0.3.0", False
            ),
            {"version": "0.3.0", "tag": "v0.3.0", "prerelease": False},
        )
        self.assertTrue(
            resolve_release(
                "0.1.0", "workflow_dispatch", "refs/heads/main", 2, "v0.3.0-rc.1", False
            )["prerelease"]
        )

    def test_invalid_versions_feature_pushes_and_windows_overflow_fail_closed(self):
        from scripts.prepare_tauri_release import resolve_release

        for ref in (
            "refs/heads/feature",
            "refs/tags/v1.2",
            "refs/tags/v01.2.3",
            "refs/tags/v1.2.3-01",
            "refs/tags/v1.2.65536",
        ):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                resolve_release("0.1.0", "push", ref, 1)
        with self.assertRaises(ValueError):
            resolve_release("0.1.0", "push", "refs/heads/main", 65536)

    def test_stamps_only_product_versions_before_backend_packaging(self):
        from scripts.prepare_tauri_release import stamp_version

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "src-tauri").mkdir()
            config = root / "src-tauri/tauri.conf.json"
            config.write_text(
                json.dumps(
                    {
                        "version": "0.1.0",
                        "build": {"frontendDist": "../apps/desktop/dist"},
                    }
                )
            )
            cargo = root / "src-tauri/Cargo.toml"
            cargo.write_text(
                '[package]\nname = "veyra"\nversion = "0.1.0"\n\n[dependencies]\nserde = { version = "1" }\n'
            )
            stamp_version(root, "0.1.12")
            self.assertEqual(
                json.loads(config.read_text()),
                {
                    "version": "0.1.12",
                    "build": {"frontendDist": "../apps/desktop/dist"},
                },
            )
            self.assertIn('version = "0.1.12"', cargo.read_text())
            self.assertIn('serde = { version = "1" }', cargo.read_text())
