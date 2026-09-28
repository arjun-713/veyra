import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PackageBackendTests(unittest.TestCase):
    def test_runtime_requirements_select_intel_compatible_onnxruntime(self):
        from packaging.markers import default_environment
        from packaging.requirements import Requirement

        lines = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text().splitlines()
        requirements = [
            Requirement(line.strip())
            for line in lines
            if line.strip().startswith("onnxruntime")
        ]

        def selected_version(platform: str, machine: str) -> str:
            environment = default_environment()
            environment.update(sys_platform=platform, platform_machine=machine)
            selected = [item for item in requirements if item.marker.evaluate(environment)]
            self.assertEqual(len(selected), 1)
            return str(selected[0].specifier)

        self.assertEqual(selected_version("darwin", "x86_64"), "==1.23.2")
        self.assertEqual(selected_version("darwin", "arm64"), "==1.30.0")
        self.assertEqual(selected_version("linux", "x86_64"), "==1.30.0")

    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        for name in ("runtime", "viewer", "benchmarks", "perception", "datasets"):
            package = repo / name
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("\n")
            (package / "module.py").write_text("VALUE = 1\n")
        (repo / "runtime" / "__main__.py").write_text("\n")
        (repo / "src-tauri").mkdir()
        (repo / "src-tauri" / "tauri.conf.json").write_text(
            json.dumps({"version": "0.1.0"})
        )
        (repo / "configs").mkdir()
        (repo / "configs" / "utility_lod.yaml").write_text("enabled: true\n")
        (repo / "runtime" / "__pycache__").mkdir()
        (repo / "runtime" / "__pycache__" / "ignored.pyc").write_bytes(b"compiled")
        return repo

    def test_stages_only_runtime_code_and_emits_verified_manifest(self):
        from scripts.package_backend import stage_backend, verify_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = self._repo(root)
            mapper = repo / "build" / "apps" / "runtime" / "veyra_runtime"
            mapper.parent.mkdir(parents=True)
            mapper.write_bytes(b"native mapper")
            mapper.chmod(0o755)
            python = root / "python-runtime"
            (python / "bin").mkdir(parents=True)
            (python / "bin" / "python3").write_bytes(b"python")

            output = stage_backend(repo, root / "stage", mapper, python, "linux", "x64")
            manifest = verify_backend(output, "linux")

            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["platform"], "linux")
            self.assertEqual(manifest["arch"], "x64")
            self.assertTrue((output / "bin" / "veyra_runtime").is_file())
            self.assertTrue((output / "runtime" / "module.py").is_file())
            self.assertFalse((output / "runtime" / "__pycache__").exists())
            self.assertGreater(len(manifest["files"]), 5)
            self.assertEqual(
                json.loads((output / "manifest.json").read_text()), manifest
            )

    def test_manifest_records_the_packaged_source_identity(self):
        from scripts.package_backend import stage_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = self._repo(root)
            git = [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.email=t@example.test",
                "-c",
                "user.name=T",
            ]
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run([*git, "add", "runtime"], check=True)
            subprocess.run([*git, "commit", "-q", "-m", "packaged"], check=True)
            head = subprocess.run(
                [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip()
            (repo / "runtime/module.py").write_text("VALUE = 2\n")
            mapper = repo / "build/apps/runtime/veyra_runtime"
            mapper.parent.mkdir(parents=True)
            mapper.write_bytes(b"mapper")
            python = root / "python-runtime"
            (python / "bin").mkdir(parents=True)
            (python / "bin/python3").write_bytes(b"python")
            output = stage_backend(repo, root / "stage", mapper, python, "linux", "x64")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["source"]["git_sha"], head)
            self.assertIs(manifest["source"]["working_tree_dirty"], True)

    def test_rejects_symlinks_and_mapper_outside_repository(self):
        from scripts.package_backend import stage_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = self._repo(root)
            mapper = root / "untrusted-mapper"
            mapper.write_bytes(b"bad")
            python = root / "python-runtime"
            python.mkdir()
            with self.assertRaisesRegex(ValueError, "mapper"):
                stage_backend(repo, root / "stage", mapper, python, "linux", "x64")

    def test_materializes_internal_python_links_but_rejects_escaping_links(self):
        from scripts.package_backend import stage_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = self._repo(root)
            mapper = repo / "build/apps/runtime/veyra_runtime"
            mapper.parent.mkdir(parents=True)
            mapper.write_bytes(b"mapper")
            python = root / "python-runtime"
            (python / "bin").mkdir(parents=True)
            (python / "bin/python").write_bytes(b"python")
            (python / "bin/python3").symlink_to("python")
            output = stage_backend(repo, root / "stage", mapper, python, "linux", "x64")
            self.assertFalse((output / "python/bin/python3").is_symlink())
            self.assertEqual((output / "python/bin/python3").read_bytes(), b"python")

            (python / "escape").symlink_to(root / "outside")
            (root / "outside").write_bytes(b"outside")
            with self.assertRaisesRegex(ValueError, "escapes"):
                stage_backend(repo, root / "stage-2", mapper, python, "linux", "x64")

    def test_python_runtime_staging_omits_dangling_framework_symlinks(self):
        from scripts.package_backend import _copy_tree

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "python"
            destination = root / "staged-python"
            source.mkdir()
            dangling = source / "Frameworks/Tcl.framework/PrivateHeaders"
            dangling.parent.mkdir(parents=True)
            dangling.symlink_to(source / "missing-system-private-headers")

            _copy_tree(source, destination, materialize_internal_links=True)

            self.assertFalse(
                (destination / "Frameworks/Tcl.framework/PrivateHeaders").exists()
            )

    def test_virtual_environment_is_flattened_with_its_base_interpreter(self):
        from scripts.package_backend import stage_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = self._repo(root)
            mapper = repo / "build/apps/runtime/veyra_runtime"
            mapper.parent.mkdir(parents=True)
            mapper.write_bytes(b"mapper")

            base = root / "base-python"
            (base / "bin").mkdir(parents=True)
            (base / "bin/python3").write_bytes(b"base executable")
            (base / "lib/python3.13").mkdir(parents=True)
            (base / "lib/python3.13/encodings.py").write_text("# stdlib\n")

            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python3").write_bytes(b"venv executable")
            (venv / "lib/python3.13/site-packages/numpy").mkdir(parents=True)
            (venv / "lib/python3.13/site-packages/numpy/__init__.py").write_text(
                "# installed dependency\n"
            )
            (venv / "pyvenv.cfg").write_text(
                f"home = {base / 'bin'}\nversion = 3.13.0\n"
            )

            output = stage_backend(repo, root / "stage", mapper, venv, "linux", "x64")

            self.assertEqual(
                (output / "python/bin/python3").read_bytes(), b"base executable"
            )
            self.assertTrue(
                output.joinpath("python/lib/python3.13/encodings.py").is_file()
            )
            self.assertTrue(
                output.joinpath(
                    "python/lib/python3.13/site-packages/numpy/__init__.py"
                ).is_file()
            )
            self.assertFalse((output / "python/pyvenv.cfg").exists())

    def test_optional_benchmark_binary_is_staged_next_to_mapper(self):
        from scripts.package_backend import stage_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            (repo / "runtime").mkdir(parents=True)
            (repo / "runtime" / "__main__.py").write_text("\n")
            for name in ("viewer", "benchmarks", "perception", "datasets", "configs"):
                (repo / name).mkdir()
                (repo / name / "__init__.py").write_text("\n")
            (repo / "src-tauri").mkdir()
            (repo / "src-tauri" / "tauri.conf.json").write_text('{"version": "0.1.0"}')
            mapper = repo / "build" / "veyra_runtime"
            mapper.parent.mkdir(parents=True)
            mapper.write_bytes(b"mapper")
            benchmark = repo / "build" / "veyra_benchmark"
            benchmark.write_bytes(b"benchmark")
            python = root / "python-runtime"
            (python / "bin").mkdir(parents=True)
            (python / "bin" / "python3").write_bytes(b"python")

            output = stage_backend(
                repo,
                root / "stage",
                mapper,
                python,
                "linux",
                "x64",
                benchmark=benchmark,
            )
            self.assertEqual(
                (output / "bin" / "veyra_benchmark").read_bytes(), b"benchmark"
            )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertIn("bin/veyra_benchmark", manifest["files"])

            plain = stage_backend(repo, root / "plain", mapper, python, "linux", "x64")
            self.assertFalse((plain / "bin" / "veyra_benchmark").exists())

    def test_stage_discovers_dev_built_benchmark_when_flag_is_absent(self):
        from scripts.stage_tauri_backend import _default_benchmark

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertIsNone(_default_benchmark(root, "linux"))
            binary = root / "build" / "apps" / "benchmark" / "veyra_benchmark"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"benchmark")
            self.assertEqual(_default_benchmark(root, "linux"), binary)
            self.assertIsNone(_default_benchmark(root, "win32"))

    def test_release_checksums_are_stable_and_exclude_checksum_file(self):
        from scripts.release_checksums import write_checksums

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "b.zip").write_bytes(b"b")
            (root / "a.deb").write_bytes(b"a")
            output = write_checksums(root)
            lines = output.read_text().splitlines()
            self.assertEqual(
                [line.split("  ")[1] for line in lines], ["a.deb", "b.zip"]
            )
            self.assertNotIn("SHA256SUMS", output.read_text())

    def test_staging_rejects_dataset_or_model_assets(self):
        from scripts.package_backend import stage_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = self._repo(root)
            (repo / "datasets" / "scan.bin").write_bytes(b"dataset")
            mapper = repo / "build" / "apps" / "runtime" / "veyra_runtime"
            mapper.parent.mkdir(parents=True)
            mapper.write_bytes(b"mapper")
            python = root / "python-runtime"
            (python / "bin").mkdir(parents=True)
            (python / "bin" / "python3").write_bytes(b"python")
            with self.assertRaisesRegex(ValueError, "asset"):
                stage_backend(repo, root / "stage", mapper, python, "linux", "x64")

    def test_framework_virtual_environment_uses_its_recorded_executable(self):
        from scripts.package_backend import stage_backend

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = self._repo(root)
            mapper = repo / "build/apps/runtime/veyra_runtime"
            mapper.parent.mkdir(parents=True)
            mapper.write_bytes(b"mapper")
            # Homebrew/python.org layout: `home` has no bin/python3; the
            # prefix lives inside Python.framework/Versions/X.Y.
            cellar = root / "Cellar/python/3.12.14"
            (cellar / "bin").mkdir(parents=True)
            (cellar / "bin/python3.12").write_bytes(b"launcher")
            prefix = cellar / "Frameworks/Python.framework/Versions/3.12"
            (prefix / "bin").mkdir(parents=True)
            (prefix / "bin/python3.12").write_bytes(b"framework executable")
            (prefix / "bin/python3").symlink_to("python3.12")
            (prefix / "lib/python3.12").mkdir(parents=True)
            (prefix / "lib/python3.12/os.py").write_text("# stdlib\n")
            outside = root / "homebrew-site-packages"
            outside.mkdir()
            (prefix / "lib/python3.12/site-packages").symlink_to(outside)

            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python3").write_bytes(b"venv executable")
            (venv / "lib/python3.12/site-packages/numpy").mkdir(parents=True)
            (venv / "lib/python3.12/site-packages/numpy/__init__.py").write_text("\n")
            (venv / "pyvenv.cfg").write_text(
                f"home = {cellar / 'bin'}\n"
                f"executable = {prefix / 'bin/python3.12'}\n"
            )

            output = stage_backend(repo, root / "stage", mapper, venv, "linux", "x64")

            self.assertEqual(
                (output / "python/bin/python3").read_bytes(), b"framework executable"
            )
            self.assertTrue((output / "python/lib/python3.12/os.py").is_file())
            self.assertTrue(
                (output / "python/lib/python3.12/site-packages/numpy").is_dir(),
                "the venv overlay replaces the base site-packages link",
            )

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O relocation needs macOS")
    def test_darwin_relocation_vendors_libraries_and_leaves_no_absolute_links(self):
        from scripts.package_backend import _macho_dependencies, relocate_darwin_python

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            external = root / "homebrew/lib"
            external.mkdir(parents=True)
            (root / "dep.c").write_text("int dep(void) { return 41; }\n")
            (root / "main.c").write_text(
                "int dep(void);\nint main(void) { return dep() + 1; }\n"
            )
            library = external / "libdep.1.dylib"
            subprocess.check_call(
                [
                    "cc",
                    "-dynamiclib",
                    str(root / "dep.c"),
                    "-o",
                    str(library),
                    "-install_name",
                    str(library),
                ]
            )
            runtime = root / "python"
            (runtime / "bin").mkdir(parents=True)
            executable = runtime / "bin/python3"
            subprocess.check_call(
                ["cc", str(root / "main.c"), str(library), "-o", str(executable)]
            )

            self.assertEqual(relocate_darwin_python(runtime), ["libdep.1.dylib"])
            library.unlink()  # the build machine's copy is gone

            _, dependencies = _macho_dependencies(executable)
            self.assertIn("@loader_path/../lib/vendored/libdep.1.dylib", dependencies)
            self.assertEqual(subprocess.run([str(executable)], check=False).returncode, 42)
            subprocess.check_call(["codesign", "--verify", str(executable)])
