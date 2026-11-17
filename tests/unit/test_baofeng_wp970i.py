import unittest
from unittest import mock

from chirp.drivers import baofeng_common as bfc
from chirp.drivers.baofeng_wp970i import BFA58, UV9RPROV2


class FakePipe:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))

    def read(self, amount):
        return b"\x06" * amount


class FakeRadio:
    MODEL = "WP970I"
    VENDOR = "BTECH"
    _ack_block = True
    _fw_ver_start = 0x1EF0
    _mem_size = 0x2000
    _send_block_size = 0x10
    _ranges = [(0x0000, 0x0010)]

    def __init__(self):
        self._mmap = bytes(i & 0xFF for i in range(self._mem_size))
        self.pipe = FakePipe()
        self.status_fn = lambda _status: None

    def get_mmap(self):
        return self._mmap


class FakeUV9RPROV2(UV9RPROV2):
    def __init__(self, mmap):
        self._mmap = mmap
        self.pipe = FakePipe()
        self.status_fn = lambda _status: None


class TestWP970IWriteFraming(unittest.TestCase):
    def test_existing_wp970i_upload_reads_aux_and_writes_full_blocks(self):
        self.assertNotIn("sync_out", BFA58.__dict__)
        radio = FakeRadio()
        aux = (b"\x00" * 14, b"\x00" * 0x60,
               b"\x00" * 0x10, b"\x00" * 0x30, False)
        with mock.patch.object(bfc, "_ident_radio") as mock_ident, \
                mock.patch.object(bfc, "_get_aux_data_from_radio",
                                  return_value=aux) as mock_aux, \
                mock.patch.object(bfc, "_get_data_from_image",
                                  side_effect=lambda _radio, start, end:
                                  b"\x00" * (end - start)):
            bfc._upload(radio)

        mock_ident.assert_called_once_with(radio)
        mock_aux.assert_called_once_with(radio)
        self.assertEqual(
            radio.pipe.writes,
            [b"\x58\x00\x00\x10" + bytes(range(0x10))])

    def test_uv9rpro_v2_class_attributes(self):
        self.assertIn("sync_out", UV9RPROV2.__dict__)
        self.assertEqual(
            UV9RPROV2._ranges,
            [
                (0x0000, 0x0810),
                (0x0A00, 0x0CF0),
                (0x0E00, 0x0E90),
                (0x0F00, 0x0F70),
                (0x1000, 0x1810),
            ],
        )

    def test_v2_upload_skips_aux_reads_and_shortens_empty_slots(self):
        mmap = bytearray(b"\xFF" * 0x2000)
        # Channel 0 at 0x0000 starts with 0xFF, but 0x0000 is always sent as a
        # full 16-byte block.
        # Channel 1 at 0x0010 is populated (non-0xFF).
        mmap[0x0010:0x0020] = bytes(range(0x10))
        # Channel 2 at 0x0020 is empty (0xFF).
        radio = FakeUV9RPROV2(bytes(mmap))
        radio._ranges = [(0x0000, 0x0030), (0x1000, 0x1020)]

        with mock.patch.object(bfc, "_ident_radio") as mock_ident, \
                mock.patch.object(bfc, "_get_aux_data_from_radio") as mock_aux:
            radio.sync_out()

        mock_ident.assert_called_once_with(radio)
        mock_aux.assert_not_called()
        self.assertEqual(
            radio.pipe.writes,
            [
                b"\x58\x00\x00\x10" + b"\xFF" * 0x10,
                b"\x58\x00\x10\x10" + bytes(range(0x10)),
                b"\x58\x00\x20\x01\xFF",
                b"\x58\x10\x00\x10" + b"\xFF" * 0x10,
                b"\x58\x10\x10\x01\xFF",
            ],
        )


if __name__ == "__main__":
    unittest.main()
