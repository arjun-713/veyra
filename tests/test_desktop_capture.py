import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.desktop_flow_smoke import capture_screen


class DesktopCaptureTests(unittest.TestCase):
    def test_wayland_uses_requested_output_and_never_driver_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "viewer.png"
            request = Mock()
            with patch("scripts.desktop_flow_smoke.subprocess.run") as run:
                capture_screen(output, request, wayland=True)
            run.assert_called_once_with(
                ["wayland-screenshot", "snap", "-o", str(output)],
                check=True,
                timeout=15,
                capture_output=True,
                text=True,
            )
            request.assert_not_called()

    def test_permission_failure_is_not_silently_replaced(self):
        request = Mock()
        with (
            patch(
                "scripts.desktop_flow_smoke.subprocess.run",
                side_effect=subprocess.CalledProcessError(3, "wayland-screenshot"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            capture_screen(Path("unused.png"), request, wayland=True)
        request.assert_not_called()

    def test_native_driver_capture_is_explicit_and_decodes_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "overview.png"
            request = Mock(return_value=base64.b64encode(b"png bytes").decode())
            capture_screen(output, request, wayland=False)
            request.assert_called_once_with("/screenshot")
            self.assertEqual(output.read_bytes(), b"png bytes")
