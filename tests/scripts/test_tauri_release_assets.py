from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_tauri_release_manifest import build_manifest, stage_release
from scripts.stage_tauri_release_assets import stage_installers


class StageTauriReleaseAssetsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
