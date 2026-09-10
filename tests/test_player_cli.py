import subprocess
import tempfile
import unittest
from pathlib import Path


class PlayerCliTests(unittest.TestCase):
    def test_player_requires_a_viewer_runtime_config(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as raw:
            player = Path(raw) / "veyra_player"
            subprocess.run(
                [
                    "c++",
                    "-std=c++20",
                    str(repo / "apps/player/main.cpp"),
                    "-o",
                    str(player),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [str(player)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--runtime-config", result.stderr)


if __name__ == "__main__":
    unittest.main()
