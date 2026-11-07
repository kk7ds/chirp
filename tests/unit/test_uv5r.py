import copy
import os
import struct
import unittest
from unittest import mock

from chirp import memmap
from chirp import settings
from chirp.drivers import uv5r

TEST_IMAGE = os.path.join(os.path.dirname(__file__),
                          '..', 'images', 'Baofeng_UV-5R.img')
# Main block the default upload ranges skip
SKIPPED_BLOCK = 0x0CF0


class FakeUV5RSerial:
    """Behaves like a Serial with a UV-5R holding the given image"""

    def __init__(self, image):
        self.image = bytearray(image)
        self.inbuf = b''
        self.outbuf = b''
        self.written = []
        self.timeout = 1

    def _radio_bytes(self, addr, size):
        if addr >= 0x1EC0:
            offset = 0x1808 + addr - 0x1EC0
        elif addr < 0x1800:
            offset = addr + 8
        else:
            return b'\xFF' * size
        return bytes(self.image[offset:offset + size])

    def write(self, data):
        self.inbuf += data
        while self.inbuf:
            if self.inbuf[:1] == b'\x50':
                # The ident magic is seven bytes, written one at a time
                if len(self.inbuf) < 7:
                    return
                self.inbuf = self.inbuf[7:]
                self.outbuf += b'\x06'
            elif self.inbuf[:1] == b'\x02':
                self.inbuf = self.inbuf[1:]
                self.outbuf += bytes(self.image[:8])
            elif self.inbuf[:1] == b'\x06':
                self.inbuf = self.inbuf[1:]
                self.outbuf += b'\x06'
            elif self.inbuf[:1] in (b'S', b'X'):
                if len(self.inbuf) < 4:
                    return
                cmd, addr, size = struct.unpack('>BHB', self.inbuf[:4])
                if cmd == ord('S'):
                    self.inbuf = self.inbuf[4:]
                    self.outbuf += struct.pack('>BHB', ord('X'), addr, size)
                    self.outbuf += self._radio_bytes(addr, size)
                else:
                    if len(self.inbuf) < 4 + size:
                        return
                    self.inbuf = self.inbuf[4 + size:]
                    self.written.append(addr)
                    self.outbuf += b'\x06'
            else:
                raise Exception('Unexpected data %r' % self.inbuf)

    def read(self, size=1):
        data = self.outbuf[:size]
        self.outbuf = self.outbuf[size:]
        return data


class TestUV5RRangeOverride(unittest.TestCase):
    def setUp(self):
        with open(TEST_IMAGE, 'rb') as f:
            self.image = f.read()
        self.radio = uv5r.BaofengUV5R(None)
        self.radio._mmap = memmap.MemoryMapBytes(self.image)
        self.radio.process_mmap()
        self.radio.status_fn = lambda status: None
        self.settings = self.radio.get_settings()
        sleep = mock.patch('time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def _get_setting(self, name, group=None):
        for element in self.settings if group is None else group.values():
            if isinstance(element, settings.RadioSetting):
                if element.get_name() == name:
                    return element
            else:
                found = self._get_setting(name, element)
                if found:
                    return found

    def _apply(self, **values):
        # Like the settings editor, send the whole tree on every change
        for name, value in values.items():
            self._get_setting(name).value = value
        self.radio.set_settings(copy.deepcopy(self.settings))

    def _upload(self):
        self.radio.set_pipe(FakeUV5RSerial(self.image))
        self.radio.sync_out()
        return self.radio.pipe.written

    def test_upload_all_ranges(self):
        self._apply(allrange='UseAtOwnRisk')
        self.assertTrue(self.radio._all_range_flag)
        self.assertIn(SKIPPED_BLOCK, self._upload())
        self.assertFalse(self.radio._all_range_flag)

    def test_used_override_not_reapplied(self):
        self._apply(allrange='UseAtOwnRisk')
        self._upload()
        self._apply(squelch=5)
        self.assertFalse(self.radio._all_range_flag)
        self.assertNotIn(SKIPPED_BLOCK, self._upload())

    def test_override_entered_again(self):
        self._apply(allrange='UseAtOwnRisk')
        self._upload()
        self._apply(allrange='Default')
        self._apply(allrange='UseAtOwnRisk')
        self.assertTrue(self.radio._all_range_flag)

    def test_override_after_settings_reload(self):
        self._apply(allrange='UseAtOwnRisk')
        self._upload()
        self.settings = self.radio.get_settings()
        self.assertEqual('Default',
                         str(self._get_setting('allrange').value).strip())
        self._apply(allrange='UseAtOwnRisk')
        self.assertTrue(self.radio._all_range_flag)
