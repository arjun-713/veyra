"""Tauri release regression suite."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.protocol import encode_message
from scripts.build_tauri_release_manifest import build_manifest, stage_release
from scripts.stage_tauri_release_assets import stage_installers

# Prepare tauri release


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


# Smoke tauri backend


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


# Tauri release assets


class StageTauriReleaseAssetsTests(unittest.TestCase):
    def test_publish_requires_all_six_native_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {
                "veyra-tauri-linux-x64": [
                    "Veyra_0.1.12_amd64.deb",
                    "Veyra-0.1.12-1.x86_64.rpm",
                    "Veyra_0.1.12_amd64.AppImage",
                ],
                "veyra-tauri-win32-x64": ["Veyra_0.1.12_x64-setup.exe"],
                "veyra-tauri-darwin-arm64": ["Veyra_0.1.12_aarch64.dmg"],
                "veyra-tauri-darwin-x64": ["Veyra_0.1.12_x64.dmg"],
            }
            for target, names in files.items():
                folder = root / target
                folder.mkdir()
                for name in names:
                    (folder / name).write_bytes(b"installer")
            manifest = build_manifest(root, "0.1.12", require_complete=True)
            self.assertEqual(len(manifest["artifacts"]), 6)
            (root / "veyra-tauri-win32-x64/Veyra_0.1.12_x64-setup.exe").unlink()
            with self.assertRaisesRegex(ValueError, "incomplete"):
                build_manifest(root, "0.1.12", require_complete=True)

    def test_stages_only_final_installer_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            (bundle / "deb").mkdir(parents=True)
            (bundle / "deb" / "Veyra_0.2.0_amd64.deb").write_bytes(b"deb")
            (bundle / "deb" / "control.tar.gz").write_bytes(b"metadata")
            output = root / "release-assets"

            staged = stage_installers(bundle, output, ["deb"])

            self.assertEqual([path.name for path in staged], ["Veyra_0.2.0_amd64.deb"])
            self.assertEqual(
                [path.name for path in output.iterdir()], ["Veyra_0.2.0_amd64.deb"]
            )

    def test_requires_each_requested_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bundle").mkdir()
            with self.assertRaisesRegex(FileNotFoundError, "no dmg installer"):
                stage_installers(root / "bundle", root / "out", ["dmg"])

    def test_windows_bundle_stages_setup_installer_not_runtime_exe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nsis = root / "bundle" / "nsis"
            nsis.mkdir(parents=True)
            (nsis / "Veyra_0.2.0_x64-setup.exe").write_bytes(b"setup")
            (nsis / "veyra_runtime.exe").write_bytes(b"runtime")
            staged = stage_installers(root / "bundle", root / "out", ["nsis"])
            self.assertEqual(
                [path.name for path in staged], ["Veyra_0.2.0_x64-setup.exe"]
            )

    def test_staging_rejects_a_nonempty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bundle").mkdir()
            output = root / "out"
            output.mkdir()
            (output / "stale.deb").write_bytes(b"stale")
            with self.assertRaisesRegex(ValueError, "not empty"):
                stage_installers(root / "bundle", output, ["deb"])

    def test_manifest_records_hash_size_and_target_and_rejects_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "veyra-tauri-linux-x64"
            target.mkdir()
            installer = target / "Veyra_0.2.0_amd64.deb"
            installer.write_bytes(b"known-installer")

            manifest = build_manifest(root, "0.2.0")

            artifact = manifest["artifacts"][0]
            self.assertEqual(artifact["filename"], installer.name)
            self.assertEqual(artifact["platform"], "linux")
            self.assertEqual(artifact["architecture"], "x64")
            self.assertEqual(artifact["size"], len(b"known-installer"))
            self.assertEqual(
                artifact["sha256"],
                "9a4a08c7b5c3c4826626b5a37b5e26cac0c522c71891765e48c3ac82e9c42ab0",
            )

    def test_manifest_rejects_duplicate_asset_names_and_empty_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for target in ("veyra-tauri-darwin-x64", "veyra-tauri-darwin-arm64"):
                folder = root / target
                folder.mkdir()
                (folder / "Veyra_0.2.0_x64.dmg").write_bytes(b"same")
            with self.assertRaisesRegex(ValueError, "duplicate release asset"):
                build_manifest(root, "0.2.0")

        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "no Tauri installer"),
        ):
            build_manifest(Path(temporary), "0.2.0")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_target = root / "veyra-tauri-linux-x64"
            wrong_target.mkdir()
            (wrong_target / "Veyra_0.2.0_x64.dmg").write_bytes(b"wrong-platform")
            with self.assertRaisesRegex(ValueError, "non-installer"):
                build_manifest(root, "0.2.0")

    def test_release_staging_flattens_installers_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_dir = root / "artifacts" / "veyra-tauri-linux-x64"
            artifact_dir.mkdir(parents=True)
            installer = artifact_dir / "Veyra_0.2.0_amd64.deb"
            installer.write_bytes(b"installer")
            output = root / "release-assets"

            manifest_path = stage_release(root / "artifacts", output, "0.2.0")

            self.assertTrue(manifest_path.is_file())
            self.assertTrue((output / installer.name).is_file())
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {installer.name, "release-manifest.json"},
            )

    def test_release_staging_rejects_nonempty_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_dir = root / "artifacts" / "veyra-tauri-linux-x64"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "Veyra_0.2.0_amd64.deb").write_bytes(b"installer")
            output = root / "release-assets"
            output.mkdir()
            (output / "old.exe").write_bytes(b"old")
            with self.assertRaisesRegex(ValueError, "not empty"):
                stage_release(root / "artifacts", output, "0.2.0")


class MacosDiskImageTests(unittest.TestCase):
    def test_signed_app_is_copied_then_image_is_created_and_verified(self):
        from unittest.mock import patch

        from scripts.package_macos_dmg import package_dmg

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "Veyra.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents" / "Info.plist").write_text("app")
            output = root / "output" / "Veyra_0.1.12_x64.dmg"
            calls = []

            def run(args, *, check, timeout):
                self.assertTrue(check)
                self.assertGreater(timeout, 0)
                calls.append(args)
                if args[:2] == ["hdiutil", "create"]:
                    folder = Path(args[args.index("-srcfolder") + 1])
                    self.assertEqual(
                        (folder / "Applications").readlink(), Path("/Applications")
                    )
                    self.assertEqual(Path(args[-1]), output)
                    output.write_bytes(b"verified image")

            with patch("scripts.package_macos_dmg.subprocess.run", side_effect=run):
                self.assertEqual(package_dmg(app, output), output)
            self.assertEqual(
                [args[:2] for args in calls],
                [
                    ["codesign", "--verify"],
                    ["ditto", str(app)],
                    ["hdiutil", "create"],
                    ["hdiutil", "verify"],
                ],
            )
            self.assertFalse(
                any("attach" in args or "detach" in args for args in calls)
            )

    def test_failed_image_creation_removes_partial_output(self):
        import subprocess
        from unittest.mock import patch

        from scripts.package_macos_dmg import package_dmg

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "Veyra.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents" / "Info.plist").write_text("app")
            output = root / "Veyra.dmg"

            def run(args, **_kwargs):
                if args[:2] == ["hdiutil", "create"]:
                    output.write_bytes(b"partial")
                    raise subprocess.CalledProcessError(1, args)

            with patch("scripts.package_macos_dmg.subprocess.run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    package_dmg(app, output)
            self.assertFalse(output.exists())

    def test_invalid_bundles_and_existing_images_fail_before_commands(self):
        from unittest.mock import patch

        from scripts.package_macos_dmg import package_dmg

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "Veyra.app"
            output = root / "Veyra.dmg"
            with patch("scripts.package_macos_dmg.subprocess.run") as run:
                with self.assertRaises(ValueError):
                    package_dmg(app, output)
                (app / "Contents").mkdir(parents=True)
                (app / "Contents" / "Info.plist").write_text("app")
                output.write_bytes(b"existing")
                with self.assertRaises(FileExistsError):
                    package_dmg(app, output)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
