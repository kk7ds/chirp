# Copyright 2026 赵昕 BG8ADW
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

"""Boristone BR-3 (堡利斯通 BR-3)

The BR-3 is a TDXone TD-Q8A compatible radio, so it reuses that driver's
memory map and channel handling and only supplies what differs:

  * the clone protocol, implemented here on bytes.  The TD-Q8A driver still
    speaks the Python 2 string API, which cannot work on current CHIRP, and
    it ignores the handshake for about 200 ms after the port is opened (the
    vendor CPS sleeps 200 ms and purges both buffers first) and answers 0x00
    for a few seconds after an upload while it commits.
  * the channel bands: 136-174 and 400-480 MHz.  The 66-88 MHz segment the
    box advertises is broadcast FM receive only.
  * the first channel flag byte: the vendor CPS keeps the DTMF flag in bit 1
    and busy-channel-lockout in bit 3.
  * the tone model: the BR-3 supports DCS (0x2800 | octal code, bit 15 for
    the inverted "DIxxx" polarity) like other Kenwood-derived radios.

The vendor CPS stores codeplugs as *.TD6: a two byte "\\x06\\x02" header
followed by the 0x1FFF byte memory image, i.e. the image starts at file
offset 2.
"""

import logging
import struct
import time

from chirp import chirp_common, directory, errors, kenwood_tone, memmap
from chirp.drivers import tdxone_tdq8a

LOG = logging.getLogger(__name__)

# Same map as the TD-Q8A, but this radio's first flag byte is laid out
# differently (DTMF in bit 1, BCL in bit 3).
FLAGS_BR3 = """u8 unknown1:4,
     bcl:1,           // Busy Channel Lockout
     unknown2:1,
     dtmf:1,          // DTMF
     unknown3:1"""

# The box says 66-88 / 136-174 / 400-480 MHz, but the 66-88 MHz segment is
# broadcast FM receive only, so it cannot be used for a channel.
VALID_BANDS = [(136000000, 174000000),
               (400000000, 480000000)]

# DCS codes offered by the vendor CPS (three octal digits each)
DCS_CODES = [23, 25, 26, 31, 32, 36, 43, 47, 51, 53, 54, 65, 71, 72, 73, 74,
             114, 115, 116, 122, 125, 131, 132, 134, 143, 145, 152, 155, 156,
             162, 165, 172, 174, 205, 212, 223, 225, 226, 243, 244, 245, 246,
             251, 252, 255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325,
             331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412, 413, 423,
             431, 432, 445, 446, 452, 454, 455, 462, 464, 465, 466, 503, 506,
             516, 523, 526, 532, 546, 565, 606, 612, 624, 627, 631, 632, 645,
             654, 662, 664, 703, 712, 723, 731, 732, 734, 743, 754]


@directory.register
class BoristoneBR3(tdxone_tdq8a.TDXoneTDQ8A):
    """Boristone BR-3 (堡利斯通 BR-3)"""

    # About the name: the brand on the box is 堡利斯通 (pinyin "baolisitong")
    # and the vendor CPS carries no Latin form at all - its About box only
    # says "BR-3(7RL) 1.0 version".  The one Latin spelling that shows up
    # anywhere is on the Chinese retail listings, which write it as
    # 堡利斯通（BORISTONE）, so that is what is used here; the identifiers
    # have to be ASCII.  Looking for "BR-3" still finds it, since the model
    # number is on the box in Latin.
    VENDOR = "Boristone"
    MODEL = "BR-3"

    BAUD_RATE = 9600
    # Note: MAGIC is the image metadata marker inherited from CHIRP, so the
    # clone handshake string needs a name of its own.
    CLONE_MAGIC = b"\x02PYNCRAM"
    IDENT_PREFIX = b"P3107"
    ACK = b"\x06"

    _model = b'BR-3'
    _ranges = [(0x0010, 0x0810),
               (0x0E20, 0x0E60),
               (0x0F10, 0x0F50),
               (0x1010, 0x1810),
               (0x1F10, 0x1F30)]

    MEM_FLAGS = FLAGS_BR3
    # the vendor CPS writes 0xff into both, keeping the unknown bits set
    DEFAULT_FLAGS = 0xff
    EMPTY_FLAGS = 0xff
    # The vendor CPS writes 0xFFFF for "no tone" (0x0000 would be shown as
    # "0.0" instead of "None"), so start from there.  A CTCSS tone is stored
    # as the plain frequency times ten, with no flag bit: every one of the 108
    # CTCSS words in the stock codeplug is e.g. 0x0375 for 88.5 Hz.  Setting
    # tone_flag to 0x8000 (the model's default) makes the radio ignore the
    # tone, so it has to be off here even though that same bit means "reverse"
    # for DCS.
    TONE_MODEL = kenwood_tone.KenwoodToneModel(dcs_base=0x2800,
                                               pol_mask=0x8000,
                                               tone_init=0xffff,
                                               tone_flag=0x0000)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('The Boristone BR-3 driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def get_features(self):
        rf = super().get_features()
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_dtcs_codes = DCS_CODES
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->DTCS", "Tone->DTCS",
                                "DTCS->Tone", "->Tone", "->DTCS"]
        rf.valid_bands = VALID_BANDS
        return rf

    def _clone_prepare(self):
        """Give the radio the 200 ms it wants before it accepts the handshake

        Measured on hardware: sending the magic bytes right after the port is
        opened gets no answer at all, and the next attempt gets the ident
        string instead of the 0x06 ACK because the radio is still sitting in
        the previous state.  The vendor CPS always sleeps 200 ms and purges
        both buffers before it talks, which is exactly what we do here.
        """
        self.pipe.baudrate = self.BAUD_RATE
        time.sleep(0.2)
        try:
            self.pipe.reset_input_buffer()
        except Exception:
            pass
        try:
            self.pipe.flush()
        except Exception:
            pass

    def _recv_exact(self, count, timeout=1.0):
        """Read exactly @count bytes or raise"""
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while len(buf) < count:
            try:
                chunk = self.pipe.read(count - len(buf))
            except Exception as e:
                raise errors.RadioError(
                    "Error reading from radio: %s" % e)
            if chunk:
                buf += chunk
                continue
            if time.monotonic() > deadline:
                raise errors.RadioError(
                    "No response from radio (wanted %i bytes)" % count)
            time.sleep(0.01)
        return bytes(buf)

    def _send(self, data):
        try:
            self.pipe.write(data)
        except Exception as e:
            raise errors.RadioError("Error writing to radio: %s" % e)

    def _ident(self):
        """Enter clone mode, retrying the handshake a few times"""
        error = None
        # after an upload the radio answers 0x00 for a few seconds while it
        # commits, so retry patiently rather than failing the whole clone
        for attempt in range(0, 4):
            if attempt:
                time.sleep(2.0)
            self._clone_prepare()
            try:
                self._send(self.CLONE_MAGIC)
                if self._recv_exact(1) != self.ACK:
                    raise errors.RadioError(
                        "Unexpected response from radio to the handshake")
                self._send(b"\x02")
                ident = self._recv_exact(8)
                if not ident.startswith(self.IDENT_PREFIX):
                    raise errors.RadioError(
                        "Unexpected ident response %r" % ident)
                LOG.debug("Ident response: %r", ident)
                self._send(self.ACK)
                if self._recv_exact(1) != self.ACK:
                    raise errors.RadioError(
                        "Radio refused to enter clone mode")
                return ident
            except errors.RadioError as e:
                LOG.warning("Handshake attempt %i failed: %s", attempt + 1, e)
                error = e
        raise error

    def _read_block(self, addr):
        self._send(struct.pack(">BHB", ord("R"), addr,
                               self._recv_block_size))
        cmd, got_addr, length = struct.unpack(">BHB", self._recv_exact(4))
        if cmd != ord("W") or got_addr != addr or \
                length != self._recv_block_size:
            raise errors.RadioError(
                "Invalid answer for block 0x%04x: %02x %04x %02x" % (
                    addr, cmd, got_addr, length))
        data = self._recv_exact(self._recv_block_size)
        self._send(self.ACK)
        if self._recv_exact(1) != self.ACK:
            raise errors.RadioError(
                "Radio refused to send block 0x%04x" % addr)
        return data

    def _write_block(self, addr, data):
        self._send(struct.pack(">BHB", ord("W"), addr, len(data)) + data)
        if self._recv_exact(1) != self.ACK:
            raise errors.RadioError("Bad ack writing block 0x%04x" % addr)

    def sync_in(self):
        """Download from the radio"""
        self._ident()
        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        status.max = self._mem_size // self._recv_block_size
        image = bytearray()
        for index, addr in enumerate(range(0, self._mem_size,
                                           self._recv_block_size)):
            status.cur = index
            self.status_fn(status)
            image += self._read_block(addr)

        self._mmap = memmap.MemoryMapBytes(bytes(image))
        self.process_mmap()

    def sync_out(self):
        """Upload to the radio"""
        self._ident()
        # the vendor CPS always reads one block back before it starts writing
        self._read_block(0x0F80)

        image = self.get_mmap().get_packed()

        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        status.max = sum(end - start for start, end in self._ranges) // \
            self._send_block_size
        cur = 0
        for start, end in self._ranges:
            for addr in range(start, end, self._send_block_size):
                self._write_block(
                    addr, image[addr:addr + self._send_block_size])
                status.cur = cur
                self.status_fn(status)
                cur += 1
