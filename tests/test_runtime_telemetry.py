import os
import unittest
from unittest.mock import mock_open, patch

from runtime.telemetry import cpu_seconds, rss_bytes


class RuntimeProcessTelemetryTests(unittest.TestCase):

    def test_linux_rss_reads_resident_pages_from_procfs(self):
        proc_statm = mock_open(read_data="1234 25 10 2 0 4 0\n")

        with (
            patch("sys.platform", "linux"),
            patch("builtins.open", proc_statm),
            patch("runtime.telemetry.os.sysconf", return_value=4096),
        ):
            measured = rss_bytes(4321)

        self.assertEqual(measured, 102400)

    def test_linux_procfs_failures_remain_unavailable(self):
        with (
            patch("sys.platform", "linux"),
            patch("builtins.open", side_effect=PermissionError),
        ):
            self.assertIsNone(rss_bytes(4321))
            self.assertIsNone(cpu_seconds(4321))

    def test_linux_cpu_reads_user_and_system_ticks_from_procfs(self):
        fields_after_command = ["S"] + ["0"] * 10 + ["200", "100"]
        proc_stat = mock_open(
            read_data="4321 (mapper worker) " + " ".join(fields_after_command) + "\n"
        )

        with (
            patch("sys.platform", "linux"),
            patch("builtins.open", proc_stat),
            patch("runtime.telemetry.os.sysconf", return_value=100),
        ):
            measured = cpu_seconds(4321)

        self.assertEqual(measured, 3.0)

    def test_non_linux_external_process_counters_remain_unavailable(self):
        proc_stat = mock_open(
            read_data="4321 (mapper) S 0 0 0 0 0 0 0 0 0 0 0 200 100\n"
        )
        for platform in ("darwin", "win32"):
            with (
                self.subTest(platform=platform),
                patch("sys.platform", platform),
                patch("builtins.open", proc_stat),
            ):
                self.assertIsNone(rss_bytes(4321))
                self.assertIsNone(cpu_seconds(4321))

    def test_current_process_cpu_is_cross_platform(self):
        with patch("sys.platform", "darwin"):
            measured = cpu_seconds(os.getpid())

        self.assertIsInstance(measured, float)
        self.assertGreaterEqual(measured, 0.0)

    def test_invalid_process_ids_remain_unavailable(self):
        for process_id in (None, 0, -1, True, "123"):
            with self.subTest(process_id=process_id):
                self.assertIsNone(rss_bytes(process_id))
                self.assertIsNone(cpu_seconds(process_id))


if __name__ == "__main__":
    unittest.main()
