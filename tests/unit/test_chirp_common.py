from tests.unit import base
from chirp import chirp_common

class TestUtilityFunctions(base.BaseTest):
    def test_parse_freq_whole(self):
        self.assertEqual(chirp_common.parse_freq("146.520000"), 146520000)
        self.assertEqual(chirp_common.parse_freq("146.5200"), 146520000)
        self.assertEqual(chirp_common.parse_freq("146.52"), 146520000)
        self.assertEqual(chirp_common.parse_freq("146"), 146000000)
        self.assertEqual(chirp_common.parse_freq("1250"), 1250000000)
        self.assertEqual(chirp_common.parse_freq("123456789"),
                         123456789000000)

    def test_parse_freq_decimal(self):
        self.assertEqual(chirp_common.parse_freq("1.0"), 1000000)
        self.assertEqual(chirp_common.parse_freq("1.000000"), 1000000)
        self.assertEqual(chirp_common.parse_freq("1.1"), 1100000)
        self.assertEqual(chirp_common.parse_freq("1.100"), 1100000)

    def test_parse_freq_whitespace(self):
        self.assertEqual(chirp_common.parse_freq("1  "), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1"), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1  "), 1000000)

        self.assertEqual(chirp_common.parse_freq("1.0  "), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1.0"), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1.0  "), 1000000)
        self.assertEqual(chirp_common.parse_freq(""), 0)
        self.assertEqual(chirp_common.parse_freq(" "), 0)

    def test_parse_freq_bad(self):
        self.assertRaises(ValueError, chirp_common.parse_freq, "a")
        self.assertRaises(ValueError, chirp_common.parse_freq, "1.a")
        self.assertRaises(ValueError, chirp_common.parse_freq, "a.b")
        self.assertRaises(ValueError, chirp_common.parse_freq,
                          "1.0000001")

    def test_format_freq(self):
        self.assertEqual(chirp_common.format_freq(146520000), "146.520000")
        self.assertEqual(chirp_common.format_freq(54000000), "54.000000")
        self.assertEqual(chirp_common.format_freq(1800000), "1.800000")
        self.assertEqual(chirp_common.format_freq(1), "0.000001")
        self.assertEqual(chirp_common.format_freq(1250000000), "1250.000000")
