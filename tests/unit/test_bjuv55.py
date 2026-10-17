import random
import struct
import unittest
from unittest import mock

from chirp import memmap
from chirp.drivers import bjuv55

IDENT = b'\xAA\x42\x4A\x35\x35\x00\x00\xDD'


class FakeBJUV55Serial:
    """Behaves like a Serial with a BJ-UV55 holding the given memory"""

    def __init__(self, memory):
        self.memory = bytearray(memory)
        self.inbuf = b''
        self.outbuf = b''
        self.timeout = 1

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
                self.outbuf += IDENT
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
                    # The firmware version read runs past the end
                    self.outbuf += bytes(
                        self.memory[addr:addr + size]).ljust(size, b'\xFF')
                else:
                    if len(self.inbuf) < 4 + size:
                        return
                    self.memory[addr:addr + size] = self.inbuf[4:4 + size]
                    self.inbuf = self.inbuf[4 + size:]
                    self.outbuf += b'\x06'
            else:
                raise Exception('Unexpected data %r' % self.inbuf)

    def read(self, size=1):
        data = self.outbuf[:size]
        self.outbuf = self.outbuf[size:]
        return data


class TestBJUV55Clone(unittest.TestCase):
    def setUp(self):
        self.memory = bytearray(random.Random(55).randbytes(0x2000))
        # Firmware version
        self.memory[0x1FF0:0x1FF6] = b'BJ55\x00\x00'
        sleep = mock.patch('time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def _image(self):
        return IDENT + self.memory[:0x1800] + self.memory[0x1EC0:]

    def test_upload(self):
        radio = bjuv55.BaojieBJUV55Radio(memmap.MemoryMapBytes(self._image()))
        radio.status_fn = lambda status: None
        radio.set_pipe(FakeBJUV55Serial(b'\xFF' * 0x2000))
        radio.sync_out()
        self.assertEqual(self.memory[:0x1800], radio.pipe.memory[:0x1800])
        self.assertEqual(self.memory[0x1EC0:], radio.pipe.memory[0x1EC0:])
