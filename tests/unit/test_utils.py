from chirp import util
from tests.unit import base


class TestUtils(base.BaseTest):
    def test_hexprint_with_string(self):
        util.hexprint('00000000000000')

    def test_hexprint_with_bytes(self):
        util.hexprint(b'00000000000000')

    def test_struct_pack(self):
        struct = util.StringStruct

        self.assertEqual('\x00',
                         struct.pack('b', 0))

    def test_struct_unpack(self):
        struct = util.StringStruct

        self.assertEqual((1,), struct.unpack('b', '\x01'))
