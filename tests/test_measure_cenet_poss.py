import unittest

from scripts import measure_cenet_poss


class CENetMeasurementTests(unittest.TestCase):
    def test_macos_ru_maxrss_bytes_are_reported_as_mib(self):
        self.assertEqual(
            measure_cenet_poss._rss_to_mib(4 * 1024 * 1024 * 1024, system="Darwin"),
            4096.0,
        )

    def test_linux_ru_maxrss_kib_are_reported_as_mib(self):
        self.assertEqual(
            measure_cenet_poss._rss_to_mib(4 * 1024 * 1024, system="Linux"), 4096.0
        )
