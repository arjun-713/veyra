"""Exercise the benchmark workflow's shell contract without downloading data."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


class BenchmarkWorkflowTests(unittest.TestCase):
    def test_non_transient_benchmark_failure_exits_with_original_status(self):
        repo = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load(
            (repo / ".github/workflows/benchmark.yml").read_text()
        )
        step = next(
            item
            for item in workflow["jobs"]["benchmark"]["steps"]
            if item.get("id") == "benchmark"
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artifacts/map").mkdir(parents=True)
            (root / "benchmarks").mkdir()
            script = root / "benchmarks/run_local.sh"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "echo called >> benchmark-calls.txt\n"
                "exit 7\n"
            )
            script.chmod(0o755)
            result = subprocess.run(
                ["bash", "-e", "-c", step["run"]],
                cwd=root,
                env={
                    **os.environ,
                    "PERCEPTION_MODE": "ground_truth",
                    "SEMANTIC_POSS_SEQUENCE": "00",
                    "SEMANTIC_POSS_COUNT": "1",
                    "BENCHMARK_REPETITIONS": "1",
                    "BENCHMARK_POLICIES": "distance_lod",
                    "SEMANTIC_POSS_ARCHIVE_SHA256": "test-digest",
                    "GITHUB_WORKSPACE": str(root),
                    "RUNNER_TEMP": str(root),
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual((root / "benchmark-calls.txt").read_text(), "called\n")
            self.assertIn("non-transient exit 7", result.stderr)


if __name__ == "__main__":
    unittest.main()
