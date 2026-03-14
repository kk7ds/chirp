# Copyright 2026 Tony Gies <tgies@tgies.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
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

from chirp import bandplan_na
from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import MemSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettings

LOG = logging.getLogger(__name__)

# Serial protocol constants
CMD_ACK = b"\x06"
CMD_PROGRAM = b"\x02PROGRAM"
CMD_EXIT = b"\x62"
IDENT_PREFIX = b"SMP558"

# Memory layout constants
NUM_CHANNELS = 199
CH_START_ADDR = 0x0010
PAGE_STRIDE = 0x10
PAGE_SIZE = 0x20  # 32 bytes per page read
SETTINGS_ADDR = 0xE000
SETTINGS_OFFSET = NUM_CHANNELS * PAGE_SIZE  # 0x18E0
MEM_SIZE = (NUM_CHANNELS + 1) * PAGE_SIZE   # 6400

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("Mid", watts=20),
                chirp_common.PowerLevel("High", watts=40)]

# Tone encoding flags (big-endian u16 bitfield):
#   bit 15: DCS inverted polarity
#   bit 13: DCS mode
#   bit 11: set for DCS (not CTCSS)
#   bits 0-10: DCS code as int(octal, 8), or full u16 = CTCSS Hz*10
TONE_OFF = 0xFFFF
TONE_DCS_FLAG = 0x2000     # bit 13
TONE_INV_FLAG = 0x8000     # bit 15
TONE_DCS_MASK = 0x07FF     # bits 0-10: DCS code value

TOT_OPTIONS = ["Off", "30s", "60s", "90s", "120s", "150s",
               "180s", "210s", "240s", "270s", "300s"]

MEM_FORMAT = """
struct channel {
    u32 rxfreq;
    u32 txfreq;
    u16 rxtone;
    u16 txtone;
    u8 bandwidth;
    u8 txpower;
    char name[8];
    u8 pad[10];
};

struct settings {
    u8 busylock;
    u8 keytone;
    u8 tot;
    u8 squelch;
    u8 pad[28];
};

#seekto 0x0000;
struct channel memory[%d];

#seekto 0x%04X;
struct settings settings;
"""


# --- Serial protocol ---

def _enter_programming(radio):
    """Three-step handshake to enter programming mode."""
    serial = radio.pipe

    try:
        serial.write(CMD_PROGRAM)
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError(
            "Error communicating with radio")
    if ack != CMD_ACK:
        raise errors.RadioError(
            "Radio did not respond to program mode request")

    try:
        serial.write(b"\x02")
        ident = serial.read(8)
    except Exception:
        raise errors.RadioError(
            "Error communicating with radio")
    LOG.debug("Ident: %s", util.hexprint(ident))
    if not ident.startswith(IDENT_PREFIX):
        raise errors.RadioError(
            "Unsupported radio (ident %s)" % ident.hex())

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError(
            "Error communicating with radio")
    if ack != CMD_ACK:
        raise errors.RadioError(
            "Radio refused programming mode")


def _exit_programming(radio):
    try:
        radio.pipe.write(CMD_EXIT)
    except Exception:
        raise errors.RadioError(
            "Failed to exit programming mode")


def _read_page(radio, addr):
    """Read one 32-byte page. Response echoes R prefix (not W)."""
    serial = radio.pipe
    cmd = struct.pack(">cHB", b"R", addr, PAGE_SIZE)
    LOG.debug("Read page 0x%04X", addr)

    try:
        serial.write(cmd)
        response = serial.read(4 + PAGE_SIZE)
    except Exception:
        raise errors.RadioError(
            "Failed to read from radio at 0x%04X" % addr)

    if len(response) != 4 + PAGE_SIZE:
        raise errors.RadioError(
            "Short read at 0x%04X (%d bytes)" % (
                addr, len(response)))

    expected = struct.pack(">cHB", b"R", addr, PAGE_SIZE)
    if response[:4] != expected:
        raise errors.RadioError(
            "Bad read response at 0x%04X" % addr)

    return response[4:]


def _write_page(radio, addr, data):
    """Write one 32-byte page. Expects ACK."""
    serial = radio.pipe
    cmd = struct.pack(">cHB", b"W", addr, PAGE_SIZE)
    LOG.debug("Write page 0x%04X", addr)

    try:
        serial.write(cmd + data)
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError(
            "Failed to write to radio at 0x%04X" % addr)

    if ack != CMD_ACK:
        raise errors.RadioError(
            "No ACK after write at 0x%04X" % addr)


def do_download(radio):
    _enter_programming(radio)

    data = b""
    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.cur = 0
    status.max = NUM_CHANNELS + 1

    for i in range(NUM_CHANNELS):
        addr = CH_START_ADDR + i * PAGE_STRIDE
        data += _read_page(radio, addr)
        status.cur = i + 1
        radio.status_fn(status)

    data += _read_page(radio, SETTINGS_ADDR)
    status.cur = status.max
    radio.status_fn(status)

    _exit_programming(radio)
    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    _enter_programming(radio)

    status = chirp_common.Status()
    status.msg = "Uploading to radio"
    status.cur = 0
    status.max = NUM_CHANNELS + 1

    raw = radio.get_mmap().get_packed()

    for i in range(NUM_CHANNELS):
        addr = CH_START_ADDR + i * PAGE_STRIDE
        offset = i * PAGE_SIZE
        page = raw[offset:offset + PAGE_SIZE]
        _write_page(radio, addr, page)
        status.cur = i + 1
        radio.status_fn(status)

    _write_page(radio, SETTINGS_ADDR,
                raw[SETTINGS_OFFSET:SETTINGS_OFFSET + PAGE_SIZE])
    status.cur = status.max
    radio.status_fn(status)

    _exit_programming(radio)


# --- Tone encoding ---

def _decode_tone(value):
    """Decode 16-bit tone to (mode, value, polarity).

    Bit layout of the u16 tone value:
      bit 15: DCS inverted polarity
      bit 13: DCS mode flag
      bits 0-10: DCS code (as int(octal, 8))
      If DCS flag clear: full u16 is CTCSS Hz * 10
      0xFFFF = Off
    """
    if value == TONE_OFF:
        return '', None, None
    if value & TONE_DCS_FLAG:
        code_dec = value & TONE_DCS_MASK
        code_oct = int(oct(code_dec)[2:])
        pol = 'R' if value & TONE_INV_FLAG else 'N'
        return 'DTCS', code_oct, pol
    return 'Tone', value / 10.0, None


def _encode_tone(mode, value, polarity):
    """Encode tone to 16-bit value for radio."""
    if mode == '':
        return TONE_OFF
    elif mode == 'Tone':
        return int(value * 10)
    elif mode == 'DTCS':
        code_dec = int(str(value), 8)
        result = TONE_DCS_FLAG | 0x0800 | code_dec
        if polarity == 'R':
            result |= TONE_INV_FLAG
        return result
    raise errors.RadioError(
        "Unsupported tone mode: %s" % mode)


# --- Driver class ---

@directory.register
class RadioddityDB40G(chirp_common.CloneModeRadio):
    """Radioddity DB40-G"""
    VENDOR = "Radioddity"
    MODEL = "DB40-G"
    BAUD_RATE = 19200

    _memsize = MEM_SIZE

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.can_odd_split = True
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_skips = []
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 8
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_bands = [(400000000, 480000000)]
        rf.memory_bounds = (1, NUM_CHANNELS)
        rf.valid_tuning_steps = [5.0, 6.25, 12.5, 25.0]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(
            MEM_FORMAT % (NUM_CHANNELS, SETTINGS_OFFSET),
            self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        rxfreq = int(_mem.rxfreq)
        if rxfreq == 0 or rxfreq == 0xFFFFFFFF:
            mem.empty = True
            return mem

        mem.freq = rxfreq

        txfreq = int(_mem.txfreq)
        if txfreq == 0:
            mem.duplex = "off"
            mem.offset = 0
        elif txfreq == rxfreq:
            mem.duplex = ""
            mem.offset = 0
        elif txfreq > rxfreq:
            mem.duplex = "+"
            mem.offset = txfreq - rxfreq
        else:
            mem.duplex = "-"
            mem.offset = rxfreq - txfreq

        mem.mode = "FM" if _mem.bandwidth else "NFM"

        pwr = int(_mem.txpower)
        if 0 <= pwr < len(POWER_LEVELS):
            mem.power = POWER_LEVELS[pwr]
        else:
            mem.power = POWER_LEVELS[0]

        mem.name = str(_mem.name).rstrip("\x00 ")

        txtone = _decode_tone(int(_mem.txtone))
        rxtone = _decode_tone(int(_mem.rxtone))
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        return mem

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.empty:
            return msgs

        if mem.duplex == "split":
            tx_freq = mem.offset
        elif mem.duplex == "+":
            tx_freq = mem.freq + mem.offset
        elif mem.duplex == "-":
            tx_freq = mem.freq - mem.offset
        elif mem.duplex == "off":
            tx_freq = 0
        else:
            tx_freq = mem.freq

        if tx_freq:
            rpt = [f + 5000000
                   for f in bandplan_na.GMRS_HIRPT]
            all_tx = (list(bandplan_na.ALL_GMRS_FREQS)
                      + rpt)
            if tx_freq not in all_tx:
                msgs.append(
                    chirp_common.ValidationWarning(
                        "TX frequency %s is not a "
                        "standard GMRS frequency"
                        % chirp_common.format_freq(
                            tx_freq)))

            if tx_freq in bandplan_na.GMRS_HHONLY:
                if mem.power and \
                        mem.power != POWER_LEVELS[0]:
                    msgs.append(
                        chirp_common.ValidationWarning(
                            "GMRS 467 MHz channels "
                            "require low power"))
                if mem.mode != "NFM":
                    msgs.append(
                        chirp_common.ValidationWarning(
                            "GMRS 467 MHz channels "
                            "require narrowband"))

        return msgs

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b"\x00" * PAGE_SIZE)
            return

        _mem.rxfreq = mem.freq

        if mem.duplex == "off":
            _mem.txfreq = 0
        elif mem.duplex == "+":
            _mem.txfreq = mem.freq + mem.offset
        elif mem.duplex == "-":
            _mem.txfreq = mem.freq - mem.offset
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset
        else:
            _mem.txfreq = mem.freq

        _mem.bandwidth = 1 if mem.mode == "FM" else 0

        if mem.power:
            _mem.txpower = POWER_LEVELS.index(mem.power)
        else:
            _mem.txpower = 0

        _mem.name = mem.name.ljust(8, "\x00")[:8]

        ((txmode, txval, txpol),
         (rxmode, rxval, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        _mem.txtone = _encode_tone(txmode, txval, txpol)
        _mem.rxtone = _encode_tone(rxmode, rxval, rxpol)

    def get_settings(self):
        _s = self._memobj.settings

        basic = RadioSettingGroup("basic", "Basic Settings")

        rs = RadioSettingValueList(
            ["Off", "On"], current_index=int(_s.busylock))
        basic.append(MemSetting(
            "settings.busylock", "Busy Lock", rs))

        rs = RadioSettingValueList(
            ["Off", "On"], current_index=int(_s.keytone))
        basic.append(MemSetting(
            "settings.keytone", "Key Tone", rs))

        tot_val = int(_s.tot)
        if tot_val >= len(TOT_OPTIONS):
            tot_val = 0
        rs = RadioSettingValueList(
            TOT_OPTIONS, current_index=tot_val)
        basic.append(MemSetting(
            "settings.tot", "TX Timeout", rs))

        rs = RadioSettingValueInteger(
            0, 9, int(_s.squelch))
        basic.append(MemSetting(
            "settings.squelch", "Squelch Level", rs))

        return RadioSettings(basic)

    def set_settings(self, settings):
        settings.apply_to(self._memobj)
