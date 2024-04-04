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

import binascii
import os
import unittest
from unittest import mock

from chirp import directory
from chirp.drivers import alinco, alinco_dr735t
from chirp import memmap


class FakeAlincoSerial:
    """Behaves like a Serial with an Alinco radio connected"""

    def __init__(self, image):
        self.image = memmap.MemoryMapBytes(open(image, 'rb').read())
        self.readbuf = []
        self.ident = b''

    def zero(self):
        """Zero the mmap before an upload"""
        self.image = memmap.MemoryMapBytes(b'\x00' * len(self.image))

    def _handle_rw_dr735tn(self, data):
        if b'R' in data:
            addr_idx = data.index(b'R')-4
        elif b'W' in data:
            addr_idx = data.index(b'W')-4
        else:
            raise Exception('Unable to handle RW command %r' % data)
        addr = int(data[addr_idx: addr_idx+4], 16)
        cmd = chr(data[addr_idx+4])

        if cmd == 'R':
            bin_chunk = self.image[addr:addr+64]
            hex_chunk = binascii.hexlify(bin_chunk)
            assert (len(hex_chunk) == 128)
            self.readbuf.append(hex_chunk)
            self.readbuf.append(b'\r\n')

        if cmd == 'W':
            hex_chunk = data[addr_idx+5:addr_idx+128+5].decode()
            bin_chunk = binascii.unhexlify(hex_chunk)
            self.image[addr] = bin_chunk
            self.readbuf.append(b'OK\r\n')

    def _handle_rw(self, data):
        if b'R' in data:
            cmdindex = data.index(b'R')
        elif b'W' in data:
            cmdindex = data.index(b'W')
        else:
            raise Exception('Unable to handle RW command %r' % data)
        if cmdindex - 4 == 4:
            block_size = 16
        else:
            block_size = 64
        addr = int(data[4:cmdindex], 16)
        cmd = data[cmdindex:cmdindex + 1]
        if cmd == b'R':
            chunk = binascii.hexlify(self.image[addr:addr + block_size])
            if b'DJ175' in self.ident:
                # The DJ175 uses 16-byte blocks, but without the colon
                # separator
                self.readbuf.append(b'%s\r\n' % chunk)
            elif block_size == 64:
                self.readbuf.append(b'\r\n%s\r\n' % chunk)
            else:
                self.readbuf.append(b'\r\n%04X:%s\r\n' % (addr, chunk))
        elif cmd == b'W':
            chunk = binascii.unhexlify(data[cmdindex + 1:].rstrip())
            if len(chunk) != block_size:
                raise Exception('Expected %i, got %i' % (block_size,
                                                         len(chunk)))
            self.image[addr] = chunk
            if block_size == 64:
                self.readbuf.append(b'OK\r\n\r\n')
        else:
            raise Exception('Unable to handle command %s: %r' % (cmd, data))

    def write(self, data):
        """Write to the radio (i.e. buffer some response for read)"""
        # Serial port echo
        self.readbuf.append(data)

        ident_ack = b'OK\r\n\r\n'

        if data.startswith(b'DR'):
            self.ident = data.strip()
            self.readbuf.append(ident_ack)
        elif data.startswith(b'AL~DJ-G7'):
            self.ident = data.strip()
            self.readbuf.append(ident_ack)
        elif data.startswith(b'DJ'):
            self.ident = data.strip()
            self.readbuf.append(ident_ack)
        elif data.startswith(b'AL~F'):
            self._handle_rw(data)
        elif data.startswith(b'AL~E') and self.ident != b"DR735TN":
            self.readbuf.append(b'OK' * 10)
        elif data.startswith(b'AL~WHO'):
            # radio responds with model to WHO
            self.ident = b"DR735TN"
            # expect back "DR735TN\r\nOK\r\n"
            self.readbuf.append(self.ident+b"\r\n")
        elif data.startswith(b'AL~DR735J'):
            # this is somehow making the radio writeable...
            self.readbuf.append(b'OK\r\n')

        elif data.startswith(b'AL~RESET') and self.ident == b"DR735TN":
            self.readbuf.append(b'OK\r\n')

        elif data.startswith(b'AL~EEPEL'):
            self._handle_rw_dr735tn(data)

        else:
            raise Exception('Unable to handle %r' % data)

    def read(self, length):
        """Read from the radio (i.e. generate a radio's response)"""
        if len(self.readbuf[0]) == length:
            return self.readbuf.pop(0)
        else:
            raise Exception('Read of %i not match %i %r' % (
                length, len(self.readbuf[0]), self.readbuf[0]))


class AlincoCloneTest(unittest.TestCase):
    def _test_alinco_download(self, rclass, image):
        pipe = FakeAlincoSerial(image)
        radio = rclass(pipe)
        radio.sync_in()
        if not radio.NEEDS_COMPAT_SERIAL:
            self.assertIsInstance(radio._mmap, memmap.MemoryMapBytes)

    def _test_alinco_upload(self, rclass, image):
        pipe = FakeAlincoSerial(image)
        pipe.zero()
        radio = rclass(image)
        radio.pipe = pipe
        radio.sync_out()
        ref_image = open(image, 'rb').read()
        self.assertEqual(ref_image[0x200:rclass._memsize],
                         pipe.image.get_packed()[0x200:rclass._memsize])

    def _test_alinco(self, rclass):
        ident = directory.radio_class_id(rclass)
        image = os.path.join(os.path.dirname(__file__),
                             '..', 'images',
                             '%s.img' % ident)
        with mock.patch('time.sleep'):
            self._test_alinco_upload(rclass, image)
            self._test_alinco_download(rclass, image)

    def test_djg7(self):
        self._test_alinco(alinco.AlincoDJG7EG)

    def test_dr235(self):
        self._test_alinco(alinco.DR235Radio)

    def test_dr735(self):
        self._test_alinco(alinco_dr735t.AlincoDR735T)

    def test_dj175(self):
        # The 175 has a slightly different download string, so test it
        # specifically
        self._test_alinco(alinco.DJ175Radio)

    def test_all_alinco_identify(self):
        # Make sure all the alinco models have bytes for their _model
        # and can identify properly
        alincos = [x for x in directory.DRV_TO_RADIO.values()
                   if x.VENDOR == 'Alinco']
        for rclass in alincos:
            pipe = FakeAlincoSerial(__file__)
            radio = rclass(None)
            radio.pipe = pipe
            radio._identify()
            self.assertEqual(pipe.ident, radio._model)
