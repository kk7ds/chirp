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

"""Weierwei VEV-V6 radio management module

The VEV-V6 is programmed with the "VEV V6" software, a VB6 program that
ships as an install package (Setup Factory 7) and keeps its channel list in
a text file with the ``.M21`` extension.

The link runs at 2400 8N1 and uses tiny frames without a checksum:

    cmd | len | payload[len]

Commands:

    "FEIJIE"  6 ASCII bytes, handshake.  The radio answers with an 18 byte
              ident packet (the last 15 bytes carry the 400.0/470.0 MHz band
              limits).
    0x52      read:  count addr_hi addr_lo (count is 1..16)
              the radio answers 0x06 followed by count data bytes
    0x57      write: count addr_hi addr_lo data[count]
              the radio answers with a single 0x06 byte
    "DONE"    four ASCII bytes, end of session

The radio answers nothing at all while it is in a bad state; a DTR pulse
followed by "DONE" usually brings it back (the vendor software has the same
problem and recovers the same way).

Memory map: eight 256 byte pages at 0xA000, 0xA200, ... 0xAE00.  The gaps
between the pages are not mapped (a read there gets no answer).  Every page
holds eighteen 14 byte channel records followed by four filler bytes, so
channel n lives at ``PAGES[(n - 1) // 18] + ((n - 1) % 18) * 14``.  The
radio has 144 record slots but the first 128 are the ones the vendor
software shows.

Channel record:

    +0    receive frequency, coarse part, big endian, unit 100 kHz
    +2    bit 7 set on every channel except one odd sample, bit 6 = wide
          bandwidth, bit 5 always set, low five bits = fine part
    +3    always zero
    +4    transmit offset, coarse part, unit 100 kHz
    +5    bit 7 = transmit below receive, bit 6 = transmit above receive,
          bit 5 always set, low five bits = fine part
    +6    receive CTCSS index (position in the standard CTCSS table, 0 is
          67.0 Hz; whether a tone is set at all comes from offset 9)
    +7    transmit CTCSS index
    +8    bit 1 = high power
    +9    bit 6 always set, bit 5 = fine part counts 5 kHz (else 6.25 kHz),
          low nibble: 0x08, plus 0x06 when no transmit tone, plus 0x01 when a
          receive tone is set
    +10..13 always 0xff

The fine part is the remainder of the frequency inside a 100 kHz step,
counted in 5 kHz or 6.25 kHz units depending on bit 5 of the flags at
offset 9.  The vendor software only stores 5 kHz steps for the transmit
offset, so a 2.5 kHz split is rounded when written.

Verified on a real radio: the 77 programmed channels decode to the same
values the vendor software shows, and encoding the decoded values again
reproduces 76 of the 77 records byte for byte (the odd one has bit 7 of
offset 2 clear).  Writing a channel and reading it back with the vendor
software returns the frequency, offset, tone, power and bandwidth that were
written.
"""

import logging
import time

from chirp import bitwise, chirp_common, directory, errors, memmap

LOG = logging.getLogger(__name__)

MEM_SIZE = 0x0800          # eight 256 byte pages, packed
PAGE_SIZE = 0x0100
PAGE_COUNT = 8
PAGE_ADDRS = [0xA000 + index * 0x0200 for index in range(PAGE_COUNT)]

CHANNELS_PER_PAGE = 18
CHANNEL_COUNT = 128
CHANNEL_SIZE = 14
READ_BLOCK = 16

BAUD_RATE = 2400

HANDSHAKE = b"FEIJIE"
END = b"DONE"

CMD_READ = 0x52
CMD_WRITE = 0x57
ACK = 0x06

STEP_5K = 0x20             # flags byte at offset 9
WIDE = 0x40                # flags byte at offset 2
POWER_HIGH = 0x02          # flags byte at offset 8
FILLER = 0xFF

DEFAULT_8 = 0xFE
LOW_POWER_8 = 0xFC
BASE_9 = 0x48              # bit 6 and the 0x08 low nibble bit
NO_TX_TONE = 0x06
RX_TONE = 0x01

SIMPLEX_OFFSET = (0x0A, 0xE0)
OFFSET_DOWN = 0xA0
OFFSET_UP = 0x60

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.0),
                chirp_common.PowerLevel("Low", watts=1.0)]

# The radio stores the position in the standard CTCSS table, so index 8 is
# 88.5 Hz.  Whether a tone is present at all is kept in the flags byte at
# offset 9, which is what makes 67.0 Hz (index 0) distinguishable from "no
# tone".
TONE_TABLE = list(chirp_common.TONES)

MEM_FORMAT = """
#seekto 0x0000;
struct {
  struct {
    u16 freq;
    u8 fine;
    u8 unknown3;
    u8 offset;
    u8 offset_fine;
    u8 rtone;
    u8 ttone;
    u8 flags8;
    u8 flags9;
    u8 unknown10;
    u8 unknown11;
    u8 unknown12;
    u8 unknown13;
  } ch[18];
  u8 pad[4];
} page[8];
"""


def encode_frequencies(rx, tx):
    """Return (rx_coarse, rx_fine, off_coarse, off_flags, step_5k)."""
    rx_coarse, rx_rem = divmod(int(rx), 100000)
    delta = int(tx) - int(rx)
    off_coarse, off_rem = divmod(abs(delta), 100000)
    if rx_rem % 5000 == 0 and (delta == 0 or off_rem % 5000 == 0):
        step, step5, limit = 5000, True, 20
    else:
        step, step5, limit = 6250, False, 16
    rx_fine = int(round(rx_rem / step))
    if rx_fine >= limit:
        rx_coarse += 1
        rx_fine = 0
    if delta == 0:
        return rx_coarse, rx_fine, *SIMPLEX_OFFSET, step5
    off_fine = int(round(off_rem / step))
    if off_fine >= limit:
        off_coarse += 1
        off_fine = 0
    base = OFFSET_DOWN if delta < 0 else OFFSET_UP
    return rx_coarse, rx_fine, off_coarse, base + off_fine, step5


def decode_frequency(coarse, fine, flags9):
    step = 5000 if flags9 & STEP_5K else 6250
    return coarse * 100000 + (fine & 0x1F) * step


def decode_offset(rx, coarse, flags, flags9):
    if (coarse, flags) == SIMPLEX_OFFSET:
        return int(rx)
    step = 5000 if flags9 & STEP_5K else 6250
    magnitude = coarse * 100000 + (flags & 0x1F) * step
    if flags & 0x80:
        return int(rx) - magnitude
    return int(rx) + magnitude


def tone_to_index(tone):
    if tone is None:
        return 0
    try:
        return chirp_common.TONES.index(tone)
    except ValueError:
        return 0


def index_to_tone(index):
    if 0 <= index < len(chirp_common.TONES):
        return chirp_common.TONES[index]
    return None


def _record_index(number):
    index = number - 1
    return index // CHANNELS_PER_PAGE, index % CHANNELS_PER_PAGE


def _is_empty(raw):
    return bytes(raw) == bytes([FILLER]) * CHANNEL_SIZE


@directory.register
class VEVV6Radio(chirp_common.CloneModeRadio):
    """Weierwei VEV-V6"""

    VENDOR = "Weierwei"
    MODEL = "VEV-V6"
    BAUD_RATE = BAUD_RATE
    NEEDS_COMPAT_SERIAL = False
    WANTS_DTR = True
    WANTS_RTS = True

    _memsize = MEM_SIZE
    _file_extension = "img"

    POWER_LEVELS = POWER_LEVELS

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver was reverse engineered from the VEV V6 programming "
            "software and tested on a real radio.  Channel names are not "
            "supported by the radio; DCS is not implemented; the transmit "
            "offset is stored in 5 kHz steps, so 2.5 kHz splits are rounded.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = False
        rf.has_offset = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "->Tone"]
        rf.valid_duplexes = ["", "+", "-"]
        rf.valid_tuning_steps = [5.0, 6.25, 12.5, 25.0]
        rf.valid_tones = TONE_TABLE
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = [(400000000, 470000000)]
        rf.valid_skips = [""]
        rf.memory_bounds = (1, CHANNEL_COUNT)
        rf.can_odd_split = False
        return rf

    # ---- serial link ----

    def _flush_input(self):
        try:
            pending = self.pipe.in_waiting
            if pending:
                self.pipe.read(pending)
        except Exception:
            pass

    def _read_hard(self, count, timeout=1.0):
        data = b""
        deadline = time.time() + timeout
        while len(data) < count and time.time() < deadline:
            chunk = self.pipe.read(count - len(data))
            if chunk:
                data += chunk
            else:
                time.sleep(0.002)
        return data

    def _pulse_dtr(self):
        try:
            self.pipe.dtr = False
            time.sleep(0.25)
            self.pipe.dtr = True
            time.sleep(0.35)
        except Exception:
            LOG.debug("DTR pulse not available")

    def _start_session(self):
        self._pulse_dtr()
        self._flush_input()
        try:
            self.pipe.write(END)
            self.pipe.flush()
        except Exception as e:
            raise errors.RadioError("Serial error: %s" % e)
        time.sleep(0.35)
        self._flush_input()
        for _i in range(6):
            try:
                self.pipe.write(HANDSHAKE)
                self.pipe.flush()
            except Exception as e:
                raise errors.RadioError("Serial error: %s" % e)
            ident = self._read_hard(18, timeout=0.6)
            if len(ident) >= 16:
                LOG.debug("Ident: %s", ident.hex())
                return
            time.sleep(0.2)
        raise errors.RadioError("Radio did not answer the handshake")

    def _end_session(self):
        try:
            self.pipe.write(END)
            self.pipe.flush()
            time.sleep(0.15)
        except Exception:
            pass

    def _read_block(self, addr, count=READ_BLOCK, tries=4):
        frame = bytes([CMD_READ, count, (addr >> 8) & 0xFF, addr & 0xFF])
        for _i in range(tries):
            self._flush_input()
            self.pipe.write(frame)
            self.pipe.flush()
            reply = self._read_hard(count + 1, timeout=0.8)
            if len(reply) == count + 1 and reply[0] == ACK:
                return reply[1:]
        raise errors.RadioError("Read failed at %#06x" % addr)

    def _write_block(self, addr, data, tries=4):
        frame = bytes([CMD_WRITE, len(data), (addr >> 8) & 0xFF,
                       addr & 0xFF]) + bytes(data)
        for _i in range(tries):
            self._flush_input()
            self.pipe.write(frame)
            self.pipe.flush()
            ack = self._read_hard(1, timeout=0.8)
            if ack == bytes([ACK]):
                return
        raise errors.RadioError("Write failed at %#06x" % addr)

    def sync_in(self):
        self._start_session()
        image = bytearray()
        try:
            for page, addr in enumerate(PAGE_ADDRS):
                for offset in range(0, PAGE_SIZE, READ_BLOCK):
                    image += self._read_block(addr + offset)
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = page + 1
                    status.max = PAGE_COUNT
                    status.msg = "Cloning from radio"
                    self.status_fn(status)
        finally:
            self._end_session()
        self._mmap = memmap.MemoryMapBytes(bytes(image))
        self.process_mmap()

    def sync_out(self):
        image = self._mmap.get_packed()
        self._start_session()
        try:
            for page, addr in enumerate(PAGE_ADDRS):
                for offset in range(0, PAGE_SIZE, READ_BLOCK):
                    chunk = image[page * PAGE_SIZE + offset:
                                  page * PAGE_SIZE + offset + READ_BLOCK]
                    self._write_block(addr + offset, chunk)
                    time.sleep(0.05)
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = page + 1
                    status.max = PAGE_COUNT
                    status.msg = "Cloning to radio"
                    self.status_fn(status)
        finally:
            self._end_session()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # ---- channel conversion ----

    def _get_record(self, number):
        page, index = _record_index(number)
        return self._memobj.page[page].ch[index]

    def get_memory(self, number):
        _mem = self._get_record(number)
        mem = chirp_common.Memory()
        mem.number = number

        if _is_empty(_mem.get_raw()) or _mem.freq == 0xFFFF:
            mem.empty = True
            return mem

        rx = decode_frequency(_mem.freq, _mem.fine, _mem.flags9)
        mem.freq = rx

        tx = decode_offset(rx, _mem.offset, _mem.offset_fine, _mem.flags9)
        if tx > rx:
            mem.duplex = "+"
            mem.offset = tx - rx
        elif tx < rx:
            mem.duplex = "-"
            mem.offset = rx - tx
        else:
            mem.duplex = ""
            mem.offset = 0

        mem.power = POWER_LEVELS[0] if _mem.flags8 & POWER_HIGH \
            else POWER_LEVELS[1]
        mem.mode = "FM" if _mem.fine & WIDE else "NFM"

        rtone = index_to_tone(_mem.rtone) if _mem.flags9 & RX_TONE else None
        ttone = (None if _mem.flags9 & NO_TX_TONE
                 else index_to_tone(_mem.ttone))
        if ttone is not None and rtone is not None:
            if ttone == rtone:
                mem.tmode = "TSQL"
            else:
                mem.tmode = "Cross"
                mem.cross_mode = "Tone->Tone"
            mem.rtone = ttone
            mem.ctone = rtone
        elif ttone is not None:
            mem.tmode = "Tone"
            mem.rtone = ttone
        elif rtone is not None:
            mem.tmode = "Cross"
            mem.cross_mode = "->Tone"
            mem.ctone = rtone
        else:
            mem.tmode = ""
        return mem

    def set_memory(self, mem):
        _mem = self._get_record(mem.number)
        if mem.empty:
            _mem.set_raw(bytes([FILLER]) * CHANNEL_SIZE)
            return

        rx = mem.freq
        if mem.duplex == "+":
            tx = rx + mem.offset
        elif mem.duplex == "-":
            tx = rx - mem.offset
        else:
            tx = rx

        rx_coarse, rx_fine, off_coarse, off_flags, step5 = \
            encode_frequencies(rx, tx)
        _mem.freq = rx_coarse
        # bit 7 is set on every record the vendor software writes but one, so
        # preserve whatever the slot already has instead of forcing it.
        _mem.fine = ((_mem.fine & 0x80) | (0x40 if mem.mode == "FM" else 0x00)
                     | 0x20 | (rx_fine & 0x1F))
        _mem.unknown3 = 0x00

        _mem.offset = off_coarse
        _mem.offset_fine = off_flags

        ttone = None
        rtone = None
        if mem.tmode == "Tone":
            ttone = mem.rtone
        elif mem.tmode == "TSQL":
            ttone = mem.ctone
            rtone = mem.ctone
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "Tone":
                ttone = mem.rtone
            if rx_mode == "Tone":
                rtone = mem.ctone

        _mem.rtone = tone_to_index(rtone)
        _mem.ttone = tone_to_index(ttone)

        _mem.flags8 = DEFAULT_8 if (mem.power is None or
                                    mem.power == POWER_LEVELS[0]) \
            else LOW_POWER_8
        _mem.flags9 = (BASE_9 | (STEP_5K if step5 else 0x00)
                       | (0x00 if ttone else NO_TX_TONE)
                       | (RX_TONE if rtone else 0x00))
        _mem.unknown10 = FILLER
        _mem.unknown11 = FILLER
        _mem.unknown12 = FILLER
        _mem.unknown13 = FILLER

    def validate_memory(self, mem):
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)
        if mem.empty:
            return msgs
        if mem.freq % 6250 and mem.freq % 5000:
            msgs.append(chirp_common.ValidationWarning(
                "Frequencies are stored in 5 or 6.25 kHz steps"))
        if mem.duplex in ("+", "-") and mem.offset > 25500000:
            msgs.append(chirp_common.ValidationError(
                "The transmit offset cannot exceed 25.5 MHz"))
        if (mem.duplex in ("+", "-")
                and mem.offset % 6250 and mem.offset % 5000):
            msgs.append(chirp_common.ValidationWarning(
                "The transmit offset is stored in 5 or 6.25 kHz steps"))
        if mem.tmode == "Cross" and mem.cross_mode not in (
                "Tone->Tone", "->Tone"):
            msgs.append(chirp_common.ValidationWarning(
                "This radio only supports Tone->Tone and ->Tone cross modes"))
        return msgs
