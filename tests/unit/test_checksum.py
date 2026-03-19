import unittest

from chirp import checksum


class TestCRC(unittest.TestCase):
    def test_crc16_xmodem(self):
        data = b"123456789"
        expected_crc = 0x31C3  # Known CRC-16/XMODEM for this data
        self.assertEqual(checksum.crc16_xmodem(data), expected_crc)

    def test_crc16_ibm_rev(self):
        data = b"123456789"
        expected_crc = 0xBB3D  # Known CRC for this data
        self.assertEqual(checksum.crc16_ibm_rev(data), expected_crc)

    def test_checksum_8bit(self):
        data = b"123456789"
        expected_checksum = 221  # Known checksum for this data
        self.assertEqual(checksum.checksum_8bit(data), expected_checksum)

    def test_checksum_xor(self):
        data = b"123456789"
        expected_checksum = 49  # Known XOR checksum for this data
        self.assertEqual(checksum.checksum_xor(data), expected_checksum)
