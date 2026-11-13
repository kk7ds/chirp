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

"""Baolisitong BR-3 (堡利斯通 BR-3)

The BR-3 is a TDXone TD-Q8A compatible radio, so the clone protocol and the
basic 0x2000 byte memory map are inherited from the TD-Q8A driver:

  * 9600 8N1; magic "\\x02PYNCRAM" -> ACK 0x06; "\\x02" -> "P3107...";
    "\\x06" -> ACK 0x06;
  * "R" + addr16 + len reads 64 bytes, "W" + addr16 + len + data writes
    16 bytes, each followed by a 0x06 ACK;
  * 128 channels of 16 bytes at 0x0010, names as CHARSET indices at 0x1010.

Differences from the TD-Q8A that this driver handles:

  * the channel bands are 136-174 and 400-480 MHz (the 66-88 MHz segment the
    box advertises is broadcast FM receive only);
  * the DTMF flag lives in bit 1 of the first flag byte (the vendor CPS shows
    its DTMF column following exactly that bit), not in bit 5;
  * the BR-3 supports DCS: 0x2800 | octal code, bit 15 meaning the inverted
    ("DIxxx") polarity.
  * timing: the radio ignores the handshake for ~200 ms after the port opens,
    and answers 0x00 for a few seconds after an upload.

The vendor CPS stores codeplugs as *.TD6: a two byte "\\x06\\x02" header
followed by the 0x1FFF byte memory image, i.e. the image starts at file
offset 2.
"""

import logging
import struct
import time

from chirp import chirp_common, bitwise, directory, errors, memmap
from chirp.drivers import tdxone_tdq8a
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean

LOG = logging.getLogger(__name__)

# The TD-Q8A memory map applies unchanged except for the first channel flag
# byte: its DTMF flag sits in bit 5 there, while the BR-3 vendor CPS keeps it
# in bit 1.  Patch that one declaration instead of duplicating the format.
MEM_FORMAT = tdxone_tdq8a.MEM_FORMAT.replace(
    "  u8 unknown1:2,\n"
    "     dtmf:1,          // DTMF\n"
    "     unknown2:1,\n"
    "     bcl:1,           // Busy Channel Lockout\n"
    "     unknown3:3;\n",
    "  u8 unknown1:4,\n"
    "     bcl:1,           // Busy Channel Lockout\n"
    "     unknown2:1,\n"
    "     dtmf:1,          // DTMF\n"
    "     unknown3:1;\n",
)
assert MEM_FORMAT != tdxone_tdq8a.MEM_FORMAT, "TD-Q8A flag layout changed"

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

DCS_BASE = 0x2800
DCS_INVERT = 0x8000
TONE_NONE = 0xFFFF

CROSS_MODES = ["Tone->Tone", "DTCS->DTCS", "Tone->DTCS", "DTCS->Tone",
               "->Tone", "->DTCS"]


@directory.register
class BaolisitongBR3(tdxone_tdq8a.TDXoneTDQ8A):
    """Baolisitong BR-3"""
    VENDOR = "Baolisitong"
    MODEL = "BR-3"

    NEEDS_COMPAT_SERIAL = False

    BAUD_RATE = 9600
    MAGIC = b"\x02PYNCRAM"
    IDENT_PREFIX = b"P3107"
    ACK = b"\x06"

    _model = b'BR-3'
    _mem_size = 0x2000
    _recv_block_size = 0x40
    _send_block_size = 0x10
    # VFO A/B are two 32-byte records at 0x0F10, i.e. 0x0F10-0x0F4F
    _ranges = [(0x0010, 0x0810),
               (0x0E20, 0x0E60),
               (0x0F10, 0x0F50),
               (0x1010, 0x1810),
               (0x1F10, 0x1F30)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('The Baolisitong BR-3 driver is a beta version.\n'
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
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.has_dtcs_polarity = True
        rf.valid_dtcs_codes = DCS_CODES
        rf.valid_cross_modes = CROSS_MODES
        rf.valid_bands = VALID_BANDS
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def _clone_prepare(self):
        """Give the radio the 200 ms it wants before it accepts the handshake

        Measured on hardware: sending the magic string right after the port is
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
                self._send(self.MAGIC)
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

        # CHIRP images carry the model name after the memory image
        image += self.MODEL.ljust(8).encode("ascii")
        self._mmap = memmap.MemoryMapBytes(bytes(image))
        self.process_mmap()

    def sync_out(self):
        """Upload to the radio"""
        self._ident()
        # the vendor CPS always reads one block back before it starts writing
        self._read_block(0x0F80)

        image = self.get_mmap().get_packed()
        if isinstance(image, str):
            image = image.encode("latin1")

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

    @staticmethod
    def _get_tone(raw):
        """Raw tone word -> (mode, value, polarity)"""
        raw = int(raw)
        if raw in (0x0000, TONE_NONE):
            return None, None, None
        if (raw & DCS_BASE) == DCS_BASE:
            polarity = "R" if raw & DCS_INVERT else "N"
            return "DTCS", int("%o" % (raw & 0x07FF)), polarity
        return "Tone", raw / 10.0, None

    @staticmethod
    def _set_tone(tone):
        """(mode, value, polarity) -> raw tone word"""
        mode, value, polarity = tone
        if mode == "Tone":
            return int(value * 10)
        if mode == "DTCS":
            raw = DCS_BASE | int(str(value), 8)
            if polarity == "R":
                raw |= DCS_INVERT
            return raw
        # The vendor CPS writes 0xFFFF for "no tone"; 0x0000 is accepted too
        # but the CPS shows it as "0.0" instead of "None", so match the CPS.
        return TONE_NONE

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if bytes(_mem.get_raw(asbytes=True))[0:4] == b"\xff\xff\xff\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if bytes(_mem.get_raw(asbytes=True))[4:8] == b"\xff\xff\xff\xff":
            mem.duplex = "off"
            mem.offset = 0
        else:
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset == 0:
                mem.offset = 0
            elif chirp_common.is_split(self.get_features().valid_bands,
                                       mem.freq, int(_mem.txfreq) * 10):
                mem.duplex = "split"
                mem.offset = int(_mem.txfreq) * 10
            elif offset < 0:
                mem.duplex = "-"
                mem.offset = abs(offset)
            else:
                mem.duplex = "+"
                mem.offset = offset

        name = ""
        for char in _nam.name:
            try:
                name += tdxone_tdq8a.CHARSET[int(char)]
            except IndexError:
                break
        mem.name = name.rstrip()

        chirp_common.split_tone_decode(mem,
                                       self._get_tone(_mem.txtone),
                                       self._get_tone(_mem.rxtone))

        mem.mode = int(_mem.wide) and "FM" or "NFM"
        mem.power = tdxone_tdq8a.POWER_LEVELS[1 - int(_mem.highpower)]
        if not int(_mem.scan):
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")
        mem.extra.append(RadioSetting(
            "dtmf", "DTMF",
            RadioSettingValueBoolean(bool(int(_mem.dtmf)))))
        mem.extra.append(RadioSetting(
            "bcl", "BCL",
            RadioSettingValueBoolean(bool(int(_mem.bcl)))))

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b"\xff" * 16)
            _nam.set_raw(b"\xff" * 16)
            return

        # The vendor CPS writes 0xff into both flag bytes, so start from there
        # and only clear the bits we actually understand.
        _mem.set_raw(b"\xff" * 16)

        _mem.rxfreq = mem.freq // 10

        if mem.duplex == "off":
            for index in range(0, 4):
                _mem.txfreq[index].set_raw(b"\xff")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) // 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) // 10
        else:
            _mem.txfreq = mem.freq // 10

        name = (mem.name or "")[:6].ljust(6)
        for index in range(0, 6):
            try:
                _nam.name[index] = tdxone_tdq8a.CHARSET.index(name[index])
            except ValueError:
                _nam.name[index] = 0xFF

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _mem.txtone = self._set_tone(txtone)
        _mem.rxtone = self._set_tone(rxtone)

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "FM"
        _mem.highpower = mem.power == tdxone_tdq8a.POWER_LEVELS[0]

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)
