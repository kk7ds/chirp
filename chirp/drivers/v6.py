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

Memory map: eight 256 byte pages at 0xA000, 0xA200, ... 0xAE00.  The gaps
between the pages are not mapped (a read there gets no answer).  Every page
holds eighteen 14 byte channel records followed by four filler bytes, so
channel n lives at ``PAGES[(n - 1) // 18] + ((n - 1) % 18) * 14``.  The
radio has 144 record slots but the first 128 are the ones the vendor
software shows.

Channel record:

    +0    receive frequency, coarse part, big endian, unit 100 kHz
    +2    bit 7 set on every channel of the vendor codeplug but one, bit 6 =
          wide bandwidth, bit 5 always set, low five bits = fine part
    +3    always zero
    +4    transmit offset, coarse part, unit 100 kHz
    +5    bit 7 = transmit below receive, bit 6 = transmit above receive
          (both set means no offset at all), bit 5 always set, low five bits
          = fine part
    +6    receive CTCSS index (position in the standard CTCSS table, 0 is
          67.0 Hz; whether a tone is set at all comes from offset 9)
    +7    transmit CTCSS index
    +8    bit 1 = high power
    +9    bit 6 always set, bit 5 = the fine parts count 5 kHz (else
          6.25 kHz), bit 3 always set, two bits that are 3 when the channel
          has no transmit tone, and bit 0 = a receive tone is set
    +10..13 always 0xff

The fine part is the remainder of the frequency inside a 100 kHz step,
counted in 5 kHz or 6.25 kHz units depending on bit 5 of the flags at
offset 9.  It is a plain five bit value, so it can exceed the 16/20 units
that fit one 100 kHz step - the vendor codeplug itself has a 17 there - and
the radio multiplies it out either way.  The vendor software only stores
5 kHz steps for the transmit offset, so a 2.5 kHz split is rounded when
written.

Verified on a real radio: the 77 programmed channels decode to the same
values the vendor software shows, and encoding the decoded values again
reproduces all 77 records byte for byte.  Writing a channel and reading it
back with the vendor software returns the frequency, offset, tone, power and
bandwidth that were written.
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
IDENT_LEN = 18

CMD_READ = 0x52
CMD_WRITE = 0x57
ACK = 0x06

# A channel without a transmit offset keeps this coarse value with both
# direction bits set; the vendor software writes exactly the same thing.
SIMPLEX_OFFSET = 0x0A

# Value of the two bit "no transmit tone" field when there is no transmit
# tone (zero means there is one)
NO_TX_TONE = 0b11

STEP_5K = 5000
STEP_6K25 = 6250

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.0),
                chirp_common.PowerLevel("Low", watts=1.0)]

TONE_TABLE = list(chirp_common.TONES)

MEM_FORMAT = """
#seekto 0x0000;
struct {
  struct {
    u16 freq;
    u8  unknown1:1,
        wide:1,
        unknown2:1,
        fine:5;
    u8  unknown3;
    u8  offset;
    u8  offset_down:1,
        offset_up:1,
        unknown4:1,
        offset_fine:5;
    u8  rtone;
    u8  ttone;
    u8  unknown8:6,
        high_power:1,
        unknown8b:1;
    u8  unknown9:1,
        unknown9b:1,
        step_5k:1,
        unknown9c:1,
        unknown9d:1,
        no_tx_tone:2,
        rx_tone:1;
    u8  unknown10[4];
  } ch[18];
  u8 pad[4];
} page[8];
"""


def encode_frequencies(rx, tx):
    """Return the fields that describe @rx and @tx in one channel record.

    The result is (rx_coarse, rx_fine, offset_coarse, offset_fine,
    direction, step_5k) where direction is zero for a channel without an
    offset, positive when the radio transmits above the receive frequency
    and negative when it transmits below it.
    """
    delta = int(tx) - int(rx)
    step_5k = int(rx) % STEP_5K == 0 and delta % STEP_5K == 0
    step = STEP_5K if step_5k else STEP_6K25

    rx_coarse, rx_rem = divmod(int(rx), 100000)
    rx_fine = int(round(rx_rem / step))
    if not delta:
        return rx_coarse, rx_fine, SIMPLEX_OFFSET, 0, 0, step_5k

    offset_coarse, offset_rem = divmod(abs(delta), 100000)
    offset_fine = int(round(offset_rem / step))
    return (rx_coarse, rx_fine, offset_coarse, offset_fine,
            1 if delta > 0 else -1, step_5k)


def decode_frequency(coarse, fine, step_5k):
    return coarse * 100000 + fine * (STEP_5K if step_5k else STEP_6K25)


def decode_offset(rx, coarse, fine, step_5k, offset_up, offset_down):
    if offset_up and offset_down:
        return int(rx)
    magnitude = coarse * 100000 + fine * (STEP_5K if step_5k else STEP_6K25)
    if offset_down:
        return int(rx) - magnitude
    return int(rx) + magnitude


def tone_to_index(tone):
    if tone is None:
        return 0
    try:
        return TONE_TABLE.index(tone)
    except ValueError:
        return 0


def index_to_tone(index):
    try:
        return TONE_TABLE[index]
    except IndexError:
        return None


def _record_index(number):
    index = number - 1
    return index // CHANNELS_PER_PAGE, index % CHANNELS_PER_PAGE


def _is_empty(raw):
    return bytes(raw) == bytes([0xFF]) * CHANNEL_SIZE


@directory.register
class VEVV6Radio(chirp_common.CloneModeRadio):
    """Weierwei VEV-V6"""

    VENDOR = "Weierwei"
    MODEL = "VEV-V6"
    BAUD_RATE = BAUD_RATE
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

    def _read(self, count):
        try:
            data = self.pipe.read(count)
        except Exception as e:
            # pyserial raises SerialException here; the clone test harness
            # substitutes its own class for it
            raise errors.RadioError("Error reading from radio: %s" % e)
        if len(data) != count:
            raise errors.RadioError(
                "Short read: wanted %i bytes, got %i" % (count, len(data)))
        return data

    def _write(self, data):
        try:
            self.pipe.write(data)
            self.pipe.flush()
        except Exception as e:
            raise errors.RadioError("Error writing to radio: %s" % e)

    def _start_session(self):
        # Close any session the radio may still think it is in, then
        # handshake.  At 2400 baud the four byte "DONE" takes a while to be
        # processed, and the radio answers the handshake with its ident.
        self._write(END)
        time.sleep(0.35)
        self._write(HANDSHAKE)
        ident = self._read(IDENT_LEN)
        LOG.debug("Ident: %s", ident.hex())

    def _end_session(self):
        # Best effort: the session is over either way and there is nothing
        # useful to report if the radio has already gone away
        try:
            self._write(END)
        except errors.RadioError:
            pass

    def _read_block(self, addr, count=READ_BLOCK):
        self._write(bytes([CMD_READ, count, (addr >> 8) & 0xFF,
                           addr & 0xFF]))
        reply = self._read(count + 1)
        if reply[0] != ACK:
            raise errors.RadioError(
                "Read of %#06x answered %s" % (addr, reply.hex()))
        return reply[1:]

    def _write_block(self, addr, data):
        self._write(bytes([CMD_WRITE, len(data), (addr >> 8) & 0xFF,
                           addr & 0xFF]) + bytes(data))
        if self._read(1)[0] != ACK:
            raise errors.RadioError("Write of %#06x was not acknowledged"
                                    % addr)

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

        if _is_empty(_mem.get_raw()) or int(_mem.freq) == 0xFFFF:
            mem.empty = True
            return mem

        step_5k = bool(_mem.step_5k)
        rx = decode_frequency(int(_mem.freq), int(_mem.fine), step_5k)
        mem.freq = rx

        tx = decode_offset(rx, int(_mem.offset), int(_mem.offset_fine),
                           step_5k, int(_mem.offset_up),
                           int(_mem.offset_down))
        if tx > rx:
            mem.duplex = "+"
            mem.offset = tx - rx
        elif tx < rx:
            mem.duplex = "-"
            mem.offset = rx - tx
        else:
            mem.duplex = ""
            mem.offset = 0

        mem.power = POWER_LEVELS[0] if _mem.high_power else POWER_LEVELS[1]
        mem.mode = "FM" if _mem.wide else "NFM"

        rtone = index_to_tone(int(_mem.rtone)) if _mem.rx_tone else None
        ttone = (None if int(_mem.no_tx_tone) == NO_TX_TONE
                 else index_to_tone(int(_mem.ttone)))
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
            _mem.fill_raw(b"\xff")
            return

        rx = mem.freq
        if mem.duplex == "+":
            tx = rx + mem.offset
        elif mem.duplex == "-":
            tx = rx - mem.offset
        else:
            tx = rx

        (rx_coarse, rx_fine, offset_coarse, offset_fine, direction,
         step_5k) = encode_frequencies(rx, tx)
        _mem.freq = rx_coarse
        _mem.fine = rx_fine
        _mem.wide = 1 if mem.mode == "FM" else 0
        _mem.offset = offset_coarse
        _mem.offset_fine = offset_fine
        # Both direction bits are set on a channel that has no offset, which
        # is how the vendor codeplug marks simplex channels
        _mem.offset_up = 1 if direction >= 0 else 0
        _mem.offset_down = 1 if direction <= 0 else 0
        _mem.unknown3 = 0x00

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
        _mem.high_power = 1 if (mem.power is None or
                                mem.power == POWER_LEVELS[0]) else 0
        # The bits the vendor software leaves clear, cleared here as well so
        # that a channel programmed from scratch looks like its own
        _mem.unknown8b = 0
        _mem.unknown9 = 0
        _mem.unknown9c = 0
        _mem.step_5k = 1 if step_5k else 0
        _mem.no_tx_tone = 0 if ttone else NO_TX_TONE
        _mem.rx_tone = 1 if rtone else 0
        _mem.unknown10.fill_raw(b"\xff")

    def validate_memory(self, mem):
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)
        if not mem.empty and mem.duplex in ("+", "-") \
                and mem.offset > 25500000:
            msgs.append(chirp_common.ValidationError(
                "The transmit offset cannot exceed 25.5 MHz"))
        return msgs
