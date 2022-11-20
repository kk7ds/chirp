from chirp import util
from tests.unit import base


class TestUtils(base.BaseTest):
    def test_hexprint_with_string(self):
        util.hexprint('00000000000000')

    def test_hexprint_with_bytes(self):
        util.hexprint(b'00000000000000')

    def test_hexprint_short(self):
        expected = ('000: 00 00 00 00 00 00 00 00   ........\n'
                    '008: 00                        ........\n')
        self.assertEqual(expected, util.hexprint(b'\x00' * 9))

    def test_hexprint_even(self):
        expected = '000: 00 00 00 00 00 00 00 00   ........\n'
        self.assertEqual(expected, util.hexprint(b'\x00' * 8))
