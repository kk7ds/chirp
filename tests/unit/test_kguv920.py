# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import struct

import unittest

from chirp.drivers import kguv920pa
from chirp import memmap


class FakeSerial:
    def __init__(self):
        self.ibuf = b''
        self.obuf = b''

    def write(self, b):
        assert isinstance(b, bytes)
        self.obuf += b

    def read(self, n):
        print('read %i (rem %i)' % (n, len(self.ibuf)))
        r = self.ibuf[:n]
        self.ibuf = self.ibuf[n:]
        return r


class TestClone(unittest.TestCase):
    def test_identify(self):
        s = FakeSerial()
        s.ibuf = struct.pack(
            'BBBB10sB', 0, 0, 0,
            len(kguv920pa.KGUV920PARadio._model),
            kguv920pa._str_encode(kguv920pa.KGUV920PARadio._model), 3)
        print(s.ibuf)
        d = kguv920pa.KGUV920PARadio(s)
        d._identify()

    def test_download(self):
        s = FakeSerial()
        oneresp = struct.pack('xxxB16sB', 0x10, b'\x01' * 16, 0)
        s.ibuf = oneresp * 2
        d = kguv920pa.KGUV920PARadio(s)
        d._do_download(0, 0x20, 0x10)

    def test_upload(self):
        s = FakeSerial()
        s.ibuf = (struct.pack('>xxxBHB', 0x02, 0, 2) +
                  struct.pack('>xxxBHB', 0x02, 0x10, 2))
        d = kguv920pa.KGUV920PARadio(s)
        d._mmap = memmap.MemoryMapBytes(b'\x00' * 0x20)
        d._do_upload(0, 0x20, 0x10)
