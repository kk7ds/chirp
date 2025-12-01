import unittest

from chirp import crc


class TestCRC(unittest.TestCase):
    def test_crc16_xmodem(self):
        data = b"123456789"
        expected_crc = 0x31C3  # Known CRC-16/XMODEM for this data
        self.assertEqual(crc.crc16_xmodem(data), expected_crc)

    def test_crc16_ibm_rev(self):
        data = b"123456789"
        expected_crc = 0xBB3D  # Known CRC for this data
        self.assertEqual(crc.crc16_ibm_rev(data), expected_crc)
