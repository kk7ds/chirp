# Copyright 2023 Dan Smith <dsmith@danplanet.com>
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
import logging
from abc import ABC, abstractmethod

from chirp import util, errors

LOG = logging.getLogger(__name__)


# ############################################################################
#                                                 Radio Communication Protocol
# ############################################################################

# TODO Consider lifting this to common for all drivers to utilize
class RadioCommunicationProtocol(ABC):
    """Abstract base class for encapsulating the logic that communicates with
    the radio -- while remaining agnositic as to what content is being
    communicated.

    Usage example (within the download code, similar for upload):
        with MyProtocol(pipe, block_size, file_ident) as protocol:
            # `protocol.start_session()` is automatically called.
            # `protocol.verify_radio_ident()` is automatically called.

            for ...
                for ...
                    block = protocol.read_block(addr)
                    data += block

            # `protocol.end_session()` is automatically called.

    """

    def __init__(
        self, pipe, block_size: int, file_ident, echos_write=True
    ) -> None:
        """@file_ident can be a single ID or a list of multiple possible
        IDs."""
        assert block_size > 0 and block_size % 2 == 0
        self.pipe = pipe
        self.block_size = block_size
        self.file_idents = (
            [file_ident]
            if isinstance(file_ident, (bytes, str))
            else file_ident
        )
        self.echos_write = echos_write

    def __enter__(self):
        self.start_session()
        self._verify_radio_ident()
        return self  # what gets assigned to the `as` variable

    def __exit__(self, exc_type, exc_val, exc_tb):
        # This is called automatically when the `with` statement ends.
        # @exc_type,@exc_val, and @exc_tb are the type, value, and traceback
        # info, respectively, if an exception was raised within the body of
        # the with statement. Otherwise, all three are None.
        if exc_type is None:
            self.end_session()
        return False  # do not supress the exception, if any

    def read_bytes(self, length):
        """Reads the @length number of bytes from the pipe and returns the
        result. Raises errors.RadioError if the read is unsuccessful, or if
        the length of the result falls short of @length."""
        try:
            data = self.pipe.read(length)
        except Exception as e:
            LOG.error(f"Error reading from radio: {e}")
            raise errors.RadioError("Unable to read from radio") from e

        if len(data) != length:
            LOG.error(
                f"Short read from radio ({len(data)}, expected {length})"
            )
            LOG.debug(util.hexprint(data))
            raise errors.RadioError("Short read from radio")
        assert type(data) == bytes
        return data

    def write_bytes(self, data):
        """Writes @data to the pipe, then advances the pipe cursor to the end
        of what was just written. Raises errors.RadioError if the write is
        unsuccessful."""
        try:
            self.pipe.write(data)
            if self.echos_write:
                echoed = self.pipe.read(len(data))
                assert echoed == data
        except Exception as e:
            LOG.error(f"Error writing to radio: {e}")
            raise errors.RadioError("Unable to write to radio") from e

    def _verify_radio_ident(self):
        file_ident = self.inquire_model_number()
        if file_ident not in self.file_idents:
            LOG.debug(
                f"Model inquiry response was: {util.hexprint(file_ident)}"
            )
            raise errors.RadioError(
                f"Unsupported model for this driver: {str(file_ident)}"
            )

    @abstractmethod
    def start_session(self):
        """Implement this method with whatever handshake is required to begin
        a programming session with the radio. This method will be automatically
        called by the `with` statement before executing the code in the body.
        """
        pass

    @abstractmethod
    def end_session(self):
        """Implement this method with whatever command is required to end
        a programming session with the radio. This method will be automatically
        called by the `with` statement after executing the code in the body
        (assuming no uncaught exception is raised).
        """
        pass

    @abstractmethod
    def inquire_model_number(self) -> bytes:
        """Implement this method with whatever code is needed to ask the radio
        for its model number."""
        pass


class AnytoneProtocol(RadioCommunicationProtocol):
    """This class encapsulates the logic for communicating with any radio that
    uses the Anytone protocol, while remaining agnositic as to what content
    is actually being communicated (a data block is just a data block)."""

    ACK = b"\x06"
    CMD_BEGIN_PROGRAMMING_SESSION = b"PROGRAM"
    CMD_INQUIRE_MODEL = b"\x02"
    CMD_END_SESSION = b"\x45\x4E\x44"  # aka end frame
    CMD_READ = b"R"
    CMD_WRITE = b"W"
    ACK_CLEAN_START = b"QX\x06"
    MODEL_NUMBER_FIELD_LEN = 16  # Including the version info
    MODEL_NUMBER_LEN = 7  # The model number itself is 7
    # > = big-endian, c = char, H = unsigned short, b = signed char
    FRAME_HEADER_FORMAT = b">cHb"
    FRAME_FOOTER_FORMAT = b"BB"

    @classmethod
    def checksum(cls, data):
        """Anytone's checksum algorithm."""
        return sum(data) % 256

    def start_session(self):
        self.pipe.timeout = 1
        response = self._send_simple_command(
            self.CMD_BEGIN_PROGRAMMING_SESSION, len(self.ACK_CLEAN_START)
        )
        if response != self.ACK_CLEAN_START:
            LOG.debug(
                "Start of programming session response was: "
                f"{util.hexprint(response)}, expected: {self.ACK_CLEAN_START}"
            )
            raise errors.RadioError("Unsupported model or bad connection")

    def inquire_model_number(self) -> bytes:
        response = self._send_simple_command(
            self.CMD_INQUIRE_MODEL, self.MODEL_NUMBER_FIELD_LEN
        )
        file_ident: bytes = response[1 : self.MODEL_NUMBER_LEN + 1]
        file_ident.strip(b"\x00")
        return file_ident

    def end_session(self):
        result = self._send_simple_command(self.CMD_END_SESSION, 1)
        # FIXME I'm baffled as to why the radio sometimes returns \x06 as
        # it's supposed to but usually returns \x00
        if result not in [self.ACK, b"\x00"]:
            LOG.debug(f"End session response:\n{util.hexprint(result)}")
            raise errors.RadioError("Radio did not finish cleanly.")

    def _send_simple_command(self, cmd, response_length) -> bytes:
        self.write_bytes(cmd)
        response = self.read_bytes(response_length)
        LOG.debug(
            f"Cmd: {util.hexprint(cmd)}, "
            f"Response:\n{util.hexprint(response)}"
        )
        return response

    def _send_frame_command(self, cmd, addr, length, data=None) -> bytes:
        """Reads or writes a frame of data to the radio and then returns the
        response -- either the data that's read, or a simple acknowledgment in
        the case of a write."""
        frame = struct.pack(self.FRAME_HEADER_FORMAT, cmd, addr, length)
        if cmd == self.CMD_WRITE:
            frame += data
            frame += struct.pack(
                self.FRAME_FOOTER_FORMAT, self.checksum(frame[1:]), self.ACK
            )
        self.write_bytes(frame)
        LOG.debug(f"Sent Frame:\n{util.hexprint(frame)}")
        return (
            self.read_bytes(1)
            if cmd == self.CMD_WRITE
            else self.read_bytes(length + 6)
        )

    def read_block(self, addr, out_of=None) -> bytes:
        """Asks the radio to return one block's worth of data found at
        @addr. @out_of is the number of blocks total (optional; only used in
        debug massages)"""
        result = self._send_frame_command(self.CMD_READ, addr, self.block_size)
        out_of_part = f" of {out_of:4x}" if out_of else ""
        LOG.debug(
            f"Frame @{addr:4x} {out_of_part}...\n{util.hexprint(result)}"
        )
        header = result[:4]
        data = result[4:-2]
        # The following colon insures that a bytes type is returned (via an
        # iterable) rather than an int
        ack = result[-1:]

        if ack != self.ACK:
            LOG.debug(f"Expected ACK, got: {repr(ack)}")
            raise errors.RadioError("Radio NAK'd block at %04x" % addr)
        _cmd, _addr, _length = struct.unpack(self.FRAME_HEADER_FORMAT, header)
        if _addr != addr or _length != self.block_size:
            LOG.debug(
                "Block read error, Expected length %02x, but received %02x"
                % (self.block_size, _length)
            )
            LOG.debug(
                "Block read error, Expected addr %04x, but received %04x"
                % (addr, _addr)
            )
            raise errors.RadioError("Radio sent an unexpected data block.")
        cs = self.checksum(header[1:] + data)
        if cs != result[-2]:
            LOG.debug("Calculated checksum: %02x" % cs)
            LOG.debug("Actual checksum:     %02x" % result[-2])
            raise errors.RadioError("Block at 0x%04x failed checksum" % addr)
        return data

    def write_block(self, addr, data):
        """Sends @data to the radio with the instruction to write it to @addr.
        @data is expected to be exactly one block's worth."""
        result = self._send_frame_command(
            self.CMD_WRITE, addr, self.block_size, data
        )
        if result != self.ACK:
            LOG.debug(f"write_block() expected ACK, got: {repr(result)}")
            raise errors.RadioError(
                "Radio did not accept block at %04x" % addr
            )
