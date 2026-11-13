# Copyright 2026 Dan Smith <chirp@f.danplanet.com>
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

import logging
import struct

from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.drivers import thd74

LOG = logging.getLogger(__name__)

ACK = b'\x06'
CR = b'\r'
# One byte past the highest address read in the capture (0x05BDFF).
IMAGE_SIZE = 0x05BE00
D750_FILE_DATA_SIZE = 0x1D7100
D750_TUNE_STEPS = [1.0, 2.5, 5.0, 6.25, 8.33, 10.0, 12.5, 15.0,
                   20.0, 25.0, 30.0, 50.0, 100.0]
D750_FILE_HEADER = (
    b'MCP-D750V1.00' + (b'\xFF' * 3) +
    b'TM-D750' + (b'\xFF' * 9) +
    b'\x00' + (b'\xFF' * 15) +
    (b'\xFF' * (5 * 16)) +
    b'K21' + (b'\xFF' * 13) +
    (b'\xFF' * (7 * 16)))


def _pack_address(address):
    """Pack the protocol's 24-bit address using a 32-bit integer format."""
    return struct.pack('>I', address)[1:]


def _unpack_address(address):
    """Unpack a 24-bit address by padding it to a 32-bit integer."""
    return struct.unpack('>I', b'\x00' + address)[0]


def _iter_read_requests():
    """Yield the observed address/length pairs in download order."""
    # Initial short, non-contiguous areas from the trace.
    yield 0x000008, 0x28
    yield 0x000038, 0xC8
    yield 0x000100, 0xA0
    yield 0x0001E0, 0x20

    # Large contiguous regions. A length of 256 is encoded as zero.
    for address in range(0x000200, 0x015000, 0x100):
        yield address, 256
    for address in range(0x024D00, 0x04C000, 0x100):
        yield address, 256
    for address in range(0x04CD00, 0x04CF00, 0x100):
        yield address, 256
    for address in range(0x04E400, 0x04FF00, 0x100):
        yield address, 256

    # The final six groups repeat at 0x2000-byte intervals.
    for base in range(0x050000, 0x05C000, 0x2000):
        yield base + 1, 0xFF
        for address in range(base + 0x100, base + 0x1100, 0x100):
            yield address, 256
        yield base + 0x1400, 0x80
        for address in range(base + 0x1800, base + 0x1E00, 0x100):
            yield address, 256


READ_REQUESTS = tuple(_iter_read_requests())


@directory.register
class TMD750Radio(thd74.THD75Radio):
    """Kenwood TM-D750 using the TH-D75 memory layout."""
    VENDOR = 'Kenwood'
    MODEL = 'TM-D750'
    BAUD_RATE = 115200
    FORMATS = [directory.register_format('Kenwood MCP-D750', '*.d750')]
    TUNE_STEPS = D750_TUNE_STEPS
    MCP_FILE_EXTENSION = '.d750'
    MCP_FILE_HEADER = D750_FILE_HEADER
    MCP_FILE_HEADER_SIZE = len(D750_FILE_HEADER)
    MCP_FILE_DATA_SIZE = D750_FILE_DATA_SIZE
    MCP_FILE_SIGNATURES = ((0, b'MCP-D750'), (0x10, b'TM-D750'))

    _memsize = IMAGE_SIZE

    @classmethod
    def get_prompts(cls):
        prompts = chirp_common.RadioPrompts()
        prompts.experimental = (
            'This driver is under development and is still experimental. '
            'Use at your own risk, but Kenwood radios are very robust and '
            'the author considers it safe.')
        return prompts

    def _command(self, command, response_length):
        self.pipe.write(command.encode('ascii') + CR)
        response = self.pipe.read(response_length)
        if len(response) != response_length:
            if not response:
                raise errors.RadioNoResponse()
            raise errors.RadioError(
                'Short response to %s: got %i bytes, expected %i' %
                (command, len(response), response_length))
        if not response.endswith(CR):
            raise errors.RadioError(
                'Invalid response terminator for %s: %s' %
                (command, response.hex(' ')))

        response = response.decode('ascii', errors='replace')
        LOG.debug('TM-D750 command %s -> %s', command, response.strip())
        return response.rstrip('\r\n')

    def _identify(self):
        response = self._command('ID', len(b'ID TM-D750\r'))
        if response != 'ID TM-D750':
            raise errors.RadioError('Unexpected radio ID: %s' % response)

        radio_type = self._command('TY', len(b'TY K,2,1\r'))
        firmware = self._command('FV', len(b'FV 1.03\r'))
        LOG.info('TM-D750 type %s, firmware %s', radio_type, firmware)

    def _enter_program_mode(self):
        response = self._command('0M PROGRAM', len(b'0M\r'))
        if response != '0M':
            raise errors.RadioError(
                'Unexpected response to program command: %s' % response)

    def _read_region(self, address, count):
        if not 0 <= address < IMAGE_SIZE or not 1 <= count <= 256:
            raise errors.RadioError('Invalid read range 0x%06X+%i' %
                                    (address, count))
        if address + count > IMAGE_SIZE:
            raise errors.RadioError('Read range exceeds image size')

        length = count & 0xFF
        request = struct.pack('>c3sB', b'R', _pack_address(address), length)
        self.pipe.log('Reading 0x%06X (%i bytes)' % (address, count))
        self.pipe.write(request)

        response = self.pipe.read(5)
        if len(response) != 5:
            if not response:
                raise errors.RadioNoResponse()
            raise errors.RadioError(
                'Short response header for 0x%06X: %s' %
                (address, response.hex(' ')))

        command, address_bytes, response_length = \
            struct.unpack('>c3sB', response)
        response_address = _unpack_address(address_bytes)
        if (command != b'W' or response_address != address or
                response_length != length):
            raise errors.RadioError(
                'Unexpected response for 0x%06X: %s' %
                (address, response.hex(' ')))

        data = self.pipe.read(count)
        if len(data) != count:
            raise errors.RadioError(
                'Short data at 0x%06X: got %i bytes, expected %i' %
                (address, len(data), count))

        self.pipe.write(ACK)
        if self.pipe.read(1) != ACK:
            raise errors.RadioError(
                'Radio did not acknowledge read at 0x%06X' % address)

        return data

    def _write_region(self, address, data):
        count = len(data)
        if not 0 <= address < IMAGE_SIZE or not 1 <= count <= 256:
            raise errors.RadioError('Invalid write range 0x%06X+%i' %
                                    (address, count))
        if address + count > IMAGE_SIZE:
            raise errors.RadioError('Write range exceeds image size')

        length = count & 0xFF
        request = (struct.pack('>c3sB', b'W', _pack_address(address),
                               length) + data)
        self.pipe.log('Writing 0x%06X (%i bytes)' % (address, count))
        self.pipe.write(request)

        if self.pipe.read(1) != ACK:
            raise errors.RadioError(
                'Radio did not acknowledge write at 0x%06X' % address)

    def _exit_program_mode(self, command=b'E', required=False):
        try:
            self.pipe.write(command)
            if self.pipe.read(1) != ACK:
                raise errors.RadioError(
                    'Radio did not acknowledge clone-mode exit')
        except Exception:
            if required:
                raise
            # Preserve the original transfer error, if any. This is also
            # best-effort when the radio has already dropped the connection.
            LOG.warning('Failed to confirm clone-mode exit', exc_info=True)

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = [(108000000, 524000000)]
        return rf

    def sync_in(self):
        try:
            self._sync_in()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                'Failed to communicate with radio: %s' % e)

    def _sync_in(self):
        self.pipe.timeout = 1.0
        self.pipe.baudrate = self.BAUD_RATE
        self._identify()

        try:
            self._enter_program_mode()

            image = bytearray(b'\xFF' * self._memsize)
            status = chirp_common.Status()
            status.msg = 'Reading TM-D750 memory'
            status.max = len(READ_REQUESTS)

            for index, (address, count) in enumerate(READ_REQUESTS, 1):
                data = self._read_region(address, count)
                image[address:address + count] = data

                if self.status_fn:
                    status.cur = index
                    self.status_fn(status)
        finally:
            self._exit_program_mode()

        self._mmap = memmap.MemoryMapBytes(bytes(image))
        self.process_mmap()

    def sync_out(self):
        try:
            self._sync_out()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                'Failed to communicate with radio: %s' % e)

    def _sync_out(self):
        if self._mmap is None or len(self._mmap) != self._memsize:
            raise errors.RadioError(
                'TM-D750 image must be exactly 0x%X bytes' % self._memsize)

        self.pipe.timeout = 1.0
        self.pipe.baudrate = self.BAUD_RATE
        self._identify()

        program_attempted = False
        original_header = None
        restore_header = False
        restore_failed = False
        upload_complete = False

        try:
            # The OEM software reads byte zero, writes 0xFF there while
            # transferring the image, then restores the byte it read.
            program_attempted = True
            self._enter_program_mode()

            original_header = self._read_region(0, 1)
            # Restore even if the following write times out: it may have
            # reached the radio despite a missing acknowledgement.
            restore_header = True
            self._write_region(0, b'\xFF')

            status = chirp_common.Status()
            status.cur = 0
            status.max = len(READ_REQUESTS)
            status.msg = 'Writing TM-D750 memory'

            for index, (address, count) in enumerate(READ_REQUESTS, 1):
                self._write_region(address,
                                   self._mmap[address:address + count])
                if self.status_fn:
                    status.cur = index
                    self.status_fn(status)

            upload_complete = True
        finally:
            try:
                if restore_header:
                    try:
                        self._write_region(0, original_header)
                    except Exception:
                        restore_failed = True
                        LOG.exception('Failed to restore TM-D750 header')
                        if upload_complete:
                            raise
            finally:
                if program_attempted:
                    self._exit_program_mode(
                        b'F', required=upload_complete and not restore_failed)
