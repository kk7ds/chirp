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

"""Weierwei VEV-V8 Plus radio management module

The VEV-V8 Plus is programmed with the Linton LT-6100E software ("MCP6100",
VB6 + MSComm32).  The link runs at 9600 8N1 with very small frames:

    cmd | len | payload[len] | checksum     checksum = XOR of all prev bytes

Commands:

    0x02  handshake, fixed payload 46 4c 74 06 45 04
          the radio answers 0x06 with the ident string "Linton"
    0x06  empty payload: enters the read/write session (answered by 0x06)
    0x52  read:  addr_hi addr_lo count
          the radio answers 0x57 with addr_hi addr_lo data[count]
    0x57  write: addr_hi addr_lo data[..]
          the radio answers 0x06 with an empty payload
    0x64  end of session, payload 0x6f

The radio ignores everything for the first three seconds after the port is
opened, and the first handshake frame is often lost.

Memory map (8192 bytes, 16 bit addresses):

    0x0310  199 channels, 16 bytes each
    0x0000-0x030f  settings (not decoded, preserved as-is)

Channel record:

    +0  receive frequency, 6 digit BCD in kHz, three bytes
    +3  bit 3 (0x08) adds 500 Hz
    +4  transmit frequency, same encoding
    +8  receive CTCSS index (0xff = none)
    +9  0x82 when a receive tone is set
    +10 transmit CTCSS index
    +11 0x81 when a transmit tone is set
    +12, +13  always 0xff, unknown
    +14 bit 7 = high power, bit 6 = wide bandwidth
    +15 unknown (0x70 on every channel written by the vendor software)

The CTCSS index is the position in the standard CTCSS table plus two, so
index 6 is 77.0 Hz, 10 is 88.5 Hz and 14 is 100.0 Hz.

Verified on a real radio: 8192 bytes downloaded, uploaded again and read
back - no differences.  The power and bandwidth bits were confirmed by
writing them and reading the channel back with the vendor software.
"""

import logging
import time

from chirp import bitwise, chirp_common, directory, errors, memmap

LOG = logging.getLogger(__name__)

MEM_SIZE = 0x2000
BLOCK_SIZE = 16

CHANNEL_START = 0x0310
CHANNEL_COUNT = 199
CHANNEL_SIZE = 16

HANDSHAKE = bytes([0x02, 0x06, 0x46, 0x4c, 0x74, 0x06, 0x45, 0x04, 0x3d])
PROBE = bytes([0x06, 0x00, 0x06])
END = bytes([0x64, 0x01, 0x6f, 0x0a])

CMD_READ = 0x52
CMD_WRITE = 0x57

IDENT_MODEL = b"Linton"

RX_TONE_FLAG = 0x82
TX_TONE_FLAG = 0x81
NO_TONE = 0xFF
TONE_OFFSET = 2

POWER_HIGH = 0x80
BANDWIDTH_WIDE = 0x40
FREQ_HALF_KHZ = 0x08

DEFAULT_FLAGS = POWER_HIGH | BANDWIDTH_WIDE

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.0),
                chirp_common.PowerLevel("Low", watts=1.0)]
DEFAULT_UNKNOWN15 = 0x70

MEM_FORMAT = """
#seekto 0x0310;
struct {
  u8 rx_freq[4];
  u8 tx_freq[4];
  u8 rx_tone;
  u8 rx_tone_flag;
  u8 tx_tone;
  u8 tx_tone_flag;
  u8 unknown12;
  u8 unknown13;
  u8 flags;
  u8 unknown15;
} memory[199];
"""


def _bcd_to_int(data):
    value = 0
    for byte in data:
        high = byte >> 4
        low = byte & 0x0F
        if high > 9 or low > 9:
            return None
        value = value * 100 + high * 10 + low
    return value


def _int_to_bcd(value, length):
    data = bytearray(length)
    for index in range(length - 1, -1, -1):
        value, low = divmod(value, 10)
        value, high = divmod(value, 10)
        data[index] = (high << 4) | low
    return bytes(data)


def _decode_freq(raw):
    khz = _bcd_to_int(raw[0:3])
    if khz is None:
        return None
    hz = khz * 1000
    if raw[3] & FREQ_HALF_KHZ:
        hz += 500
    return hz


def _encode_freq(hz):
    """Encode a frequency as BCD kilohertz plus a 500 Hz bit."""
    hz = int(hz)
    khz, rem = divmod(hz, 1000)
    if rem >= 750:
        khz += 1
        rem = 0
        extra = 0
    elif rem >= 250:
        extra = FREQ_HALF_KHZ
    else:
        extra = 0
    return _int_to_bcd(khz, 3) + bytes([extra])


def _tone_to_index(tone):
    try:
        return chirp_common.TONES.index(tone) + TONE_OFFSET
    except ValueError:
        return None


def _index_to_tone(index):
    position = index - TONE_OFFSET
    if 0 <= position < len(chirp_common.TONES):
        return chirp_common.TONES[position]
    return None


@directory.register
class VEVV8PlusRadio(chirp_common.CloneModeRadio):
    """Weierwei VEV-V8 Plus"""

    VENDOR = "Weierwei"
    MODEL = "VEV-V8 Plus"
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = False

    _memsize = MEM_SIZE
    _file_extension = "img"

    POWER_LEVELS = POWER_LEVELS

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver was reverse engineered from the LT-6100E "
            "programming software and tested on a VEV-V8 Plus.  Channel "
            "names are not decoded (the vendor software has an alias column "
            "whose storage has not been located) and DCS is not implemented.")
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
        rf.valid_duplexes = ["", "+", "-", "split"]
        rf.valid_tuning_steps = [5.0, 10.0, 12.5, 25.0]
        rf.valid_tones = list(chirp_common.TONES)
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = [(400000000, 470000000)]
        rf.valid_skips = [""]
        rf.memory_bounds = (1, CHANNEL_COUNT)
        rf.can_odd_split = True
        return rf

    # ---- serial link ----
    def _flush_input(self):
        try:
            pending = self.pipe.in_waiting
            if pending:
                self.pipe.read(pending)
        except Exception:
            pass

    def _read_soft(self, count):
        """Read up to ``count`` bytes, returning None on timeout."""
        data = b""
        while len(data) < count:
            try:
                chunk = self.pipe.read(count - len(data))
            except Exception:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def _start_session(self):
        # the radio ignores everything for the first few seconds
        time.sleep(3.0)
        self._flush_input()
        for _i in range(10):
            try:
                self.pipe.write(HANDSHAKE)
                self.pipe.flush()
            except Exception as e:
                raise errors.RadioError("Serial error: %s" % e)
            time.sleep(0.35)
            ident = self.pipe.read(64)
            if ident:
                LOG.debug("Ident: %r", ident)
                if IDENT_MODEL not in ident:
                    LOG.warning("Unexpected ident %r", ident)
                break
        else:
            raise errors.RadioError("Radio did not answer the handshake")
        self.pipe.write(PROBE)
        self.pipe.flush()
        time.sleep(0.25)
        self._flush_input()

    def _end_session(self):
        try:
            self.pipe.write(END)
            self.pipe.flush()
            time.sleep(0.2)
        except Exception:
            pass

    def _read_block(self, addr, count=BLOCK_SIZE, tries=4):
        frame = bytes([CMD_READ, 3, (addr >> 8) & 0xFF, addr & 0xFF, count])
        checksum = 0
        for byte in frame:
            checksum ^= byte
        frame += bytes([checksum])
        for _i in range(tries):
            self._flush_input()
            self.pipe.write(frame)
            self.pipe.flush()
            reply = self._read_soft(count + 5)
            if reply is None:
                continue
            if reply[0] != CMD_WRITE or reply[1] != count + 2:
                continue
            if ((reply[2] << 8) | reply[3]) != addr:
                continue
            checksum = 0
            for byte in reply[:count + 4]:
                checksum ^= byte
            if checksum != reply[count + 4]:
                continue
            return reply[4:4 + count]
        raise errors.RadioError("Read failed at %#06x" % addr)

    def _write_block(self, addr, data, tries=4):
        payload = bytes([(addr >> 8) & 0xFF, addr & 0xFF]) + bytes(data)
        frame = bytes([CMD_WRITE, len(payload)]) + payload
        checksum = 0
        for byte in frame:
            checksum ^= byte
        frame += bytes([checksum])
        for _i in range(tries):
            self._flush_input()
            self.pipe.write(frame)
            self.pipe.flush()
            ack = self.pipe.read(3)
            if ack == b"\x06\x00\x06":
                return
        raise errors.RadioError("Write failed at %#06x" % addr)

    def sync_in(self):
        self._start_session()
        try:
            image = bytearray()
            for addr in range(0, MEM_SIZE, BLOCK_SIZE):
                image += self._read_block(addr)
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = addr
                    status.max = MEM_SIZE
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
            for addr in range(0, MEM_SIZE, BLOCK_SIZE):
                self._write_block(addr, image[addr:addr + BLOCK_SIZE])
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = addr
                    status.max = MEM_SIZE
                    status.msg = "Cloning to radio"
                    self.status_fn(status)
        finally:
            self._end_session()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # ---- channel conversion ----
    def _tone_to_index(self, tone):
        return _tone_to_index(tone)

    def _index_to_tone(self, index):
        return _index_to_tone(index)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        rx = _decode_freq(_mem.rx_freq)
        tx = _decode_freq(_mem.tx_freq)
        if rx is None or rx == 0:
            mem.empty = True
            return mem

        mem.freq = rx
        if tx is None:
            tx = rx
        if tx > rx:
            mem.duplex = "+"
            mem.offset = tx - rx
        elif tx < rx:
            mem.duplex = "-"
            mem.offset = rx - tx
        else:
            mem.duplex = ""
            mem.offset = 0

        mem.power = self.POWER_LEVELS[0] if _mem.flags & POWER_HIGH \
            else self.POWER_LEVELS[1]
        mem.mode = "FM" if _mem.flags & BANDWIDTH_WIDE else "NFM"

        rtone = None
        ttone = None
        if _mem.rx_tone_flag == RX_TONE_FLAG:
            rtone = self._index_to_tone(_mem.rx_tone)
        if _mem.tx_tone_flag == TX_TONE_FLAG:
            ttone = self._index_to_tone(_mem.tx_tone)

        if ttone is not None and rtone is not None and ttone == rtone:
            mem.tmode = "TSQL"
            mem.rtone = ttone
            mem.ctone = rtone
        elif ttone is not None and rtone is not None:
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
        if mem.empty:
            self._memobj.memory[mem.number - 1].set_raw(b"\xff" * CHANNEL_SIZE)
            return

        _mem = self._memobj.memory[mem.number - 1]
        rx = mem.freq
        if mem.duplex == "+":
            tx = rx + mem.offset
        elif mem.duplex == "-":
            tx = rx - mem.offset
        elif mem.duplex == "split":
            tx = mem.offset
        else:
            tx = rx

        _mem.rx_freq = _encode_freq(rx)
        _mem.tx_freq = _encode_freq(tx)

        _mem.rx_tone = NO_TONE
        _mem.rx_tone_flag = 0x00
        _mem.tx_tone = NO_TONE
        _mem.tx_tone_flag = 0x00

        ttone = None
        rtone = None
        if mem.tmode == "Tone":
            ttone = mem.rtone
        elif mem.tmode == "TSQL":
            # CHIRP keeps the two tones of a TSQL memory in rtone/ctone and
            # compares ctone; the radio stores one tone per direction.
            ttone = mem.ctone
            rtone = mem.ctone
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "Tone":
                ttone = mem.rtone
            if rx_mode == "Tone":
                rtone = mem.ctone

        if ttone is not None:
            index = self._tone_to_index(ttone)
            if index is not None:
                _mem.tx_tone = index
                _mem.tx_tone_flag = TX_TONE_FLAG
        if rtone is not None:
            index = self._tone_to_index(rtone)
            if index is not None:
                _mem.rx_tone = index
                _mem.rx_tone_flag = RX_TONE_FLAG

        flags = _mem.flags
        if mem.power is None or mem.power == self.POWER_LEVELS[0]:
            flags |= POWER_HIGH
        else:
            flags &= ~POWER_HIGH
        if mem.mode == "FM":
            flags |= BANDWIDTH_WIDE
        else:
            flags &= ~BANDWIDTH_WIDE
        _mem.flags = flags
        if _mem.unknown15 in (0x00, 0xFF):
            _mem.unknown15 = DEFAULT_UNKNOWN15

    def validate_memory(self, mem):
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)
        if mem.empty:
            return msgs
        if mem.tmode == "Cross" and mem.cross_mode not in (
                "Tone->Tone", "->Tone"):
            msgs.append(chirp_common.ValidationWarning(
                "This radio only supports Tone->Tone and ->Tone cross modes"))
        if mem.power and str(mem.power) == "High" and mem.mode == "NFM":
            msgs.append(chirp_common.ValidationWarning(
                "The radio always uses wide bandwidth on high power"))
        if mem.freq % 500 or mem.offset % 500:
            msgs.append(chirp_common.ValidationWarning(
                "Frequencies are stored in 500 Hz steps"))
        return msgs
