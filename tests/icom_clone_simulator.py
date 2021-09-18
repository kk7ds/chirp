# Copyright 2019 Dan Smith <dsmith@danplanet.com>
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

from builtins import bytes

import struct

from chirp.drivers import icf

import logging

LOG = logging.getLogger(__name__)


import sys
l = logging.getLogger()
l.level = logging.ERROR
l.addHandler(logging.StreamHandler(sys.stdout))

class FakeIcomRadio(object):
    def __init__(self, radio, mapfile=None):
        self._buffer = bytes(b'')
        self._radio = radio
        if not mapfile:
            self._memory = bytes(b'\x00') * radio.get_memsize()
        else:
            self.load_from_file(mapfile)

    def load_from_file(self, filename):
        with open(filename, 'rb') as f:
            self._memory = bytes(f.read())
        LOG.debug('Initialized %i bytes from %s' % (len(self._memory),
                                                    filename))

    def read(self, count):
        """read() from radio, so here we synthesize responses"""
        chunk = self._buffer[:count]
        self._buffer = self._buffer[count:]
        return chunk

    def queue(self, data):
        # LOG.debug('Queuing: %r' % data)
        self._buffer += data

    def make_response(self, cmd, payload):
        return bytes([
            0xFE, 0xFE,
            0xEF,  # Radio
            0xEE,  # PC
            cmd,
        ]) + payload + bytes([0xFD])

    @property
    def address_fmt(self):
        if self._radio.get_memsize() > 0x10000:
            return 'I'
        else:
            return 'H'

    def do_clone_out(self):
        LOG.debug('Clone from radio started')
        size = 16
        for addr in range(0, self._radio.get_memsize(), size):
            if len(self._memory[addr:]) < 4:
                # IC-W32E has an off-by-one hack for detection,
                # which will cause us to send a short one-byte
                # block of garbage, unlike the real radio. So,
                # if we get to the end and have a few bytes
                # left, don't be stupid.
                break
            header = bytes(struct.pack('>%sB' % self.address_fmt,
                                       addr, size))
            #LOG.debug('Header for %02x@%04x: %r' % (
            #    size, addr, header))
            chunk = []
            cs = 0
            for byte in header:
                chunk.extend(x for x in bytes(b'%02X' % byte))
                cs += byte
            #LOG.debug('Chunk so far: %r' % chunk)
            for byte in self._memory[addr:addr + size]:
                chunk.extend(x for x in bytes(b'%02X' % byte))
                cs += byte
            #LOG.debug('Chunk is %r' % chunk)

            vx = ((cs ^ 0xFFFF) + 1) & 0xFF
            chunk.extend(x for x in bytes(b'%02X' % vx))
            self.queue(self.make_response(icf.CMD_CLONE_DAT, bytes(chunk)))
            #LOG.debug('Stopping after first frame')
            #break
        self.queue(self.make_response(icf.CMD_CLONE_END, bytes([])))

    def do_clone_in(self):
        LOG.debug('Clone to radio started')
        self._memory = bytes(b'')

    def do_clone_data(self, payload_hex):
        if self.address_fmt == 'I':
            header_len = 5
        else:
            header_len = 3

        def hex_to_byte(hexchars):
            return int('%s%s' % (chr(hexchars[0]), chr(hexchars[1])), 16)

        payload_bytes = bytes([hex_to_byte(payload_hex[i:i+2])
                               for i in range(0, len(payload_hex), 2)])

        addr, size = struct.unpack('>%sB' % self.address_fmt, payload_bytes[:header_len])
        data = payload_bytes[header_len:-1]
        csum = payload_bytes[-1]

        #addr_hex = payload[0:size_offset]
        #size_hex = payload[size_offset:size_offset + 2]
        #data_hex = payload[size_offset + 2:-2]
        #csum_hex = payload[-2:]


        #addr = hex_to_byte(addr_hex[0:2]) << 8 | hex_to_byte(addr_hex[2:4])
        #size = hex_to_byte(size_hex)
        #csum = hex_to_byte(csum_hex)

        #data = []
        #for i in range(0, len(data_hex), 2):
        #    data.append(hex_to_byte(data_hex[i:i+2]))

        if len(data) != size:
            LOG.debug('Invalid frame size: expected %i, but got %i' % (
                size, len(data)))

        expected_addr = len(self._memory)
        if addr < expected_addr:
            LOG.debug('Frame goes back to %04x from %04x' % (addr,
                                                             expected_addr))
        if len(self._memory) != addr:
            LOG.debug('Filling gap between %04x and %04x' % (expected_addr,
                                                             addr))
            self._memory += (bytes(b'\x00') * (addr - expected_addr))

        # FIXME: Check checksum

        self._memory += data

    def write(self, data):
        """write() to radio, so here we process requests"""

        assert isinstance(data, bytes), 'Bytes required, %s received' % data.__class__

        if data[:12] == (bytes(b'\xFE') * 12):
            LOG.debug('Got hispeed kicker')
            data = data[12:]
            if data[2] == 0xFE:
                return

        src = data[2]
        dst = data[3]
        cmd = data[4]
        payload = data[5:-1]
        end = data[-1]

        LOG.debug('Received command: %r' % cmd)
        LOG.debug('  Full frame: %r' % data)

        model = self._radio.get_model() + bytes(b'\x00' * 20)

        if cmd == 0xE0:  # Ident
            # FIXME
            self.queue(self.make_response(0x01,  # Model
                                          model))
        elif cmd == icf.CMD_CLONE_OUT:
            self.do_clone_out()
        elif cmd == icf.CMD_CLONE_IN:
            self.do_clone_in()
        elif cmd == icf.CMD_CLONE_DAT:
            self.do_clone_data(payload)
        else:
            LOG.debug('Unknown command %i' % cmd)
            self.queue(self.make_response(0x00, bytes([0x01])))

        return len(data)

    def flush(self):
        return
