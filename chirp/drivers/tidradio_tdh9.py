# Copyright 2024 Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# Protocol reverse-engineered from USB capture of TIDRadioCPS.
# VID 4C4A / PID 4155, 115200 baud CDC serial.
# Handshake: b'PVOJH\x5c\x14' (same as TD-H3), ident response: 8 bytes.
# Read/write: 32-byte blocks with 1-byte checksum.
# End session: b'CE' + 30 null bytes.

import struct
import logging
import time
from textwrap import dedent

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import (
    InvalidValueError, RadioSetting, RadioSettingGroup,
    RadioSettingValueList, RadioSettingValueBoolean, RadioSettings)

LOG = logging.getLogger(__name__)

# Handshake bytes sent to radio to enter programming mode.
# Shared with TD-H3 family; differs only in baud rate (115200 vs 38400).
_TDH9_MAGIC = b'PVOJH\x5c\x14'

# The identify response uniquely identifies a TD-H9.
# Captured from USB trace of TIDRadioCPS with a TD-H9.
# Layout from radio: b'TDH9' + 4 trailing bytes.
TDH9_IDENT = b'TDH9\xff\xff\xff\x4e'

BLOCK_SIZE = 0x20
MEMSIZE = 0x3124   # 259 blocks × 32 bytes; exclusive end address

# Codeplug image layout (CHIRP stores an 8-byte ident prefix then radio
# memory). All #seekto values below are image offsets (radio addr + 8).
MEM_FORMAT = """
#seekto 0x0018;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  lbcd rxtone[2];
  lbcd txtone[2];
  u8 lowpower:2,
     wide:1,
     unknown1:5;
  u8 unknown2:2,
     unknown_2000:1,
     unknown3:2,
     unknown4:2,
     scanadd:1;
  u8 unknown5;
  u8 unknown6;
} memory[199];

#seekto 0x0CA8;
struct {
  u8 txled:1,
     rxled:1,
     unknown_a5:4,
     dtmfst:1,
     unknown_a0:1;
  u8 unknown_b7:1,
     voiceprompt:1,
     unknown_b5:3,
     btnvoice:1,
     unknown_b1:1,
     tailclean:1;
  u8 unknown_c;
  u8 unknown_d7:5,
     dbrx:1,
     unknown_d1:2;
  u8 unknown_e[5];
  u8 squelch;
  u8 tot;
  u8 unknown_f1:1,
     rogerprompt:1,
     unknown_f2:6;
} settings;

#seekto 0x0D48;
struct {
  char name[8];
} names[199];
"""

SQUELCH_LIST = [str(x) for x in range(0, 10)]
TOT_LIST = ["Off", "30S", "60S", "90S", "120S", "3Min", "5Min", "10Min"]
POWER_LEVELS = [
    chirp_common.PowerLevel("High", watts=10.0),
    chirp_common.PowerLevel("Low",  watts=1.0),
    chirp_common.PowerLevel("Mid",  watts=5.0),
]
# Indices match lowpower bit field: 0=HIGH, 1=LOW, 2=MID
POWER_MAP = {0: "High", 1: "Low", 2: "Mid"}


# ── Protocol helpers ─────────────────────────────────────────────────────────

def _do_status(radio, addr):
    status = chirp_common.Status()
    status.msg = "Cloning"
    status.cur = addr
    status.max = MEMSIZE
    radio.status_fn(status)


def _ident(serial):
    """Perform handshake + identify. Returns 8-byte ident response."""
    serial.timeout = 2
    serial.reset_input_buffer()
    serial.write(_TDH9_MAGIC)
    ack = serial.read(1)
    if not ack:
        raise errors.RadioNoResponse()
    if ack != b'\x06':
        raise errors.RadioError(
            "Radio refused programming mode (expected ACK, got %r)" % ack)

    serial.write(b'\x02')
    ident = serial.read(8)
    if len(ident) != 8:
        raise errors.RadioError(
            "Identify: short read (%d bytes)" % len(ident))

    serial.write(b'\x06')
    ack2 = serial.read(1)
    if ack2 != b'\x06':
        raise errors.RadioError(
            "Radio refused after identify (expected ACK, got %r)" % ack2)

    return ident


def _read_block(serial, addr):
    """Read one 32-byte block at radio address *addr*. Returns 32 bytes."""
    cmd = struct.pack(">cHB", b'R', addr, BLOCK_SIZE)
    serial.write(cmd)

    hdr = serial.read(4)
    if len(hdr) != 4:
        raise errors.RadioError(
            "Read at %04x: header timeout (%d bytes)" % (addr, len(hdr)))
    if hdr[0:1] != b'W' or hdr[1:3] != cmd[1:3]:
        raise errors.RadioError(
            "Read at %04x: unexpected header %r" % (addr, hdr))

    data = serial.read(BLOCK_SIZE)
    if len(data) != BLOCK_SIZE:
        raise errors.RadioError(
            "Read at %04x: data timeout (%d bytes)" % (addr, len(data)))

    chk_got = serial.read(1)
    if not chk_got:
        raise errors.RadioError("Read at %04x: checksum timeout" % addr)
    chk_exp = sum(data) & 0xFF
    if chk_got[0] != chk_exp:
        raise errors.RadioError(
            "Read at %04x: checksum mismatch (expected %02x, got %02x)"
            % (addr, chk_exp, chk_got[0]))

    return bytes(data)


def _write_block(serial, addr, data):
    """Write one 32-byte block to radio address *addr*."""
    assert len(data) == BLOCK_SIZE
    chk = sum(data) & 0xFF
    cmd = struct.pack(">cHB", b'W', addr, BLOCK_SIZE)
    serial.write(cmd + bytes(data) + bytes([chk]))

    ack = serial.read(1)
    if ack != b'\x06':
        raise errors.RadioError(
            "Write at %04x: no ACK (got %r)" % (addr, ack))


def _end_session(serial):
    """Send the 32-byte end-of-session command (b'CE' + 30 nulls)."""
    serial.write(b'CE' + b'\x00' * 30)
    time.sleep(0.1)  # give radio time to return to idle before next session


def _do_download(radio):
    ident = _ident(radio.pipe)
    radio.pipe.log('Ident: %s' % util.hexprint(ident))

    buf = bytearray(MEMSIZE)
    for addr in range(0, MEMSIZE, BLOCK_SIZE):
        radio.pipe.log('Read block %04x' % addr)
        block = _read_block(radio.pipe, addr)
        buf[addr:addr + BLOCK_SIZE] = block
        _do_status(radio, addr)

    _end_session(radio.pipe)
    _do_status(radio, MEMSIZE)

    return memmap.MemoryMapBytes(ident + bytes(buf))


def _do_upload(radio):
    ident = _ident(radio.pipe)
    radio.pipe.log('Ident: %s' % util.hexprint(ident))

    # mmap layout: [8-byte ident][radio memory 0x0000..0x3123]
    mmap = radio.get_mmap()

    for addr in range(0, MEMSIZE, BLOCK_SIZE):
        radio.pipe.log('Write block %04x' % addr)
        block = bytes(mmap[addr + 8: addr + 8 + BLOCK_SIZE])
        _write_block(radio.pipe, addr, block)
        _do_status(radio, addr)

    _end_session(radio.pipe)
    _do_status(radio, MEMSIZE)


# ── Radio class ──────────────────────────────────────────────────────────────

@directory.register
class TDH9(chirp_common.CloneModeRadio):
    """TIDRADIO TD-H9"""
    VENDOR = "TIDRADIO"
    MODEL = "TD-H9"
    BAUD_RATE = 115200
    MODES = ["FM", "NFM", "AM"]

    ident_mode = TDH9_IDENT
    _memsize = MEMSIZE
    _txbands = [(136000000, 175000000), (400000000, 521000000)]
    _rxbands = []

    _tx_power = POWER_LEVELS

    _idents = [_TDH9_MAGIC]

    @classmethod
    def detect_from_serial(cls, pipe):
        # Build a map of handshake magic → [subclasses] so we only send each
        # magic once even if multiple variants share it.
        uniq_idents = {}
        for subclass in cls.detected_models():
            magic = subclass._idents[0]
            uniq_idents.setdefault(magic, [])
            uniq_idents[magic].append(subclass)

        for magic, classes in uniq_idents.items():
            try:
                radio_ident = _ident(pipe)
            except errors.RadioError:
                continue
            # Close the session immediately so download/upload can open fresh.
            _end_session(pipe)
            for rclass in classes:
                if rclass.ident_mode == radio_ident:
                    return rclass
            LOG.warning('TD-H9 ident %r matched no subclass; using base class',
                        radio_ident)
            return cls
        raise errors.RadioNoResponse()

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = dedent("""\
            1. Turn the radio on.
            2. Connect the radio via USB-C.
            3. The radio should appear as a COM port in Device Manager.
            4. Click OK to download.""")
        rp.pre_upload = dedent("""\
            1. Turn the radio on.
            2. Connect the radio via USB-C.
            3. The radio should appear as a COM port in Device Manager.
            4. Click OK to upload.""")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5,
                                 15.0, 20.0, 25.0, 50.0]
        rf.can_odd_split = True
        rf.valid_name_length = 8
        rf.valid_characters = (chirp_common.CHARSET_ALPHANUMERIC +
                               "!@#$%^&*()+-=[]:\";'<>?,./")
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone", "DTCS->", "->DTCS",
            "Tone->DTCS", "DTCS->Tone", "->Tone", "DTCS->DTCS"]
        rf.valid_power_levels = self._tx_power
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = self.MODES
        rf.valid_bands = sorted(self._txbands + self._rxbands)
        rf.memory_bounds = (1, 199)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = _do_download(self)
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def sync_out(self):
        try:
            _do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    # ── Tone encode/decode (same scheme as TDH8 family) ──────────────────────

    def _decode_tone(self, val):
        val = int(val)
        if val in (0, 16665):
            return '', None, None
        elif val >= 12000:
            return 'DTCS', val - 12000, 'R'
        elif val >= 8000:
            return 'DTCS', val - 8000, 'N'
        else:
            return 'Tone', val / 10.0, None

    def _encode_tone(self, memval, mode, value, pol):
        if mode == "":
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            flag = 0x80 if pol == 'N' else 0xC0
            memval.set_value(value)
            memval[1].set_bits(flag)
        else:
            raise Exception("Invalid tone mode: %s" % mode)

    # ── Channel read/write ───────────────────────────────────────────────────

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        # Empty: rxfreq==0 (written by CPS) or all-0xFF (fresh radio)
        if (int(_mem.rxfreq) == 0 or
                _mem.rxfreq.get_raw() == b'\xff\xff\xff\xff'):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if _mem.txfreq.get_raw() == b'\xff\xff\xff\xff':
            mem.duplex = 'off'
            mem.offset = 0
        else:
            chirp_common.split_to_offset(mem,
                                         int(_mem.rxfreq) * 10,
                                         int(_mem.txfreq) * 10)

        # Mode
        if chirp_common.in_range(mem.freq, [(108000000, 135999999)]):
            mem.mode = 'AM'
        elif _mem.wide:
            mem.mode = 'NFM'
        else:
            mem.mode = 'FM'

        # Power: 0=High, 1=Low, 2=Mid
        try:
            mem.power = self._tx_power[int(_mem.lowpower)]
        except IndexError:
            mem.power = self._tx_power[0]

        # Channel name
        name = ""
        for char in _nam.name:
            c = str(char)
            if c in ('\x00', '\xff'):
                break
            name += c
        mem.name = name.rstrip()

        # Tones
        rxtone = self._decode_tone(int(_mem.rxtone))
        txtone = self._decode_tone(int(_mem.txtone))
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # Scan
        mem.skip = '' if _mem.scanadd else 'S'

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            _mem.fill_raw(b'\x00')
            # Mark tones as unused (0xFF 0xFF)
            _mem.rxtone[0].set_raw(0xFF)
            _mem.rxtone[1].set_raw(0xFF)
            _mem.txtone[0].set_raw(0xFF)
            _mem.txtone[1].set_raw(0xFF)
            return

        _mem.fill_raw(b'\x00')

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == '':
            _mem.txfreq = mem.freq / 10
        elif mem.duplex == 'split':
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == '+':
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == '-':
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == 'off':
            _mem.txfreq.fill_raw(b'\xFF')
        else:
            _mem.txfreq = mem.freq // 10

        # Mode
        _mem.wide = 1 if mem.mode == 'NFM' else 0

        # Power: map back to 0/1/2
        try:
            _mem.lowpower = self._tx_power.index(
                mem.power or self._tx_power[0])
        except ValueError:
            _mem.lowpower = 0

        # Name
        for i in range(8):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = '\x00'

        # Tones
        txtone, rxtone = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)

        # Scan
        _mem.scanadd = 1 if mem.skip != 'S' else 0

        # Preserve the 0x2000 flag bit (bit 13 of the 32-bit flags word,
        # = bit 5 of byte+13). The CPS always sets this; purpose unknown.
        _mem.unknown_2000 = 1

    # ── Settings ─────────────────────────────────────────────────────────────

    def get_settings(self):
        try:
            return self._get_settings()
        except Exception as e:
            raise InvalidValueError("Settings read failed: %s" % e) from e

    def _get_settings(self):
        s = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        basic.append(RadioSetting(
            "squelch", "Squelch Level",
            RadioSettingValueList(SQUELCH_LIST, current_index=int(s.squelch))))

        basic.append(RadioSetting(
            "tot", "Time-Out Timer",
            RadioSettingValueList(TOT_LIST, current_index=int(s.tot))))

        basic.append(RadioSetting(
            "btnvoice", "Key Beep",
            RadioSettingValueBoolean(bool(s.btnvoice))))

        basic.append(RadioSetting(
            "rogerprompt", "Roger Beep",
            RadioSettingValueBoolean(bool(s.rogerprompt))))

        basic.append(RadioSetting(
            "dbrx", "Dual Watch",
            RadioSettingValueBoolean(bool(s.dbrx))))

        basic.append(RadioSetting(
            "txled", "TX Screen (Display on TX)",
            RadioSettingValueBoolean(bool(s.txled))))

        basic.append(RadioSetting(
            "rxled", "RX Screen (Display on RX)",
            RadioSettingValueBoolean(bool(s.rxled))))

        basic.append(RadioSetting(
            "dtmfst", "DTMF Sidetone",
            RadioSettingValueBoolean(bool(s.dtmfst))))

        basic.append(RadioSetting(
            "voiceprompt", "Voice Announce",
            RadioSettingValueBoolean(bool(s.voiceprompt))))

        basic.append(RadioSetting(
            "tailclean", "Tail Eliminate",
            RadioSettingValueBoolean(bool(s.tailclean))))

        return group

    def set_settings(self, settings):
        s = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                name = element.get_name()
                if name == "squelch":
                    s.squelch = int(element.value)
                elif name == "tot":
                    s.tot = TOT_LIST.index(str(element.value))
                elif name == "btnvoice":
                    s.btnvoice = bool(element.value)
                elif name == "rogerprompt":
                    s.rogerprompt = bool(element.value)
                elif name == "dbrx":
                    s.dbrx = bool(element.value)
                elif name == "txled":
                    s.txled = bool(element.value)
                elif name == "rxled":
                    s.rxled = bool(element.value)
                elif name == "dtmfst":
                    s.dtmfst = bool(element.value)
                elif name == "voiceprompt":
                    s.voiceprompt = bool(element.value)
                elif name == "tailclean":
                    s.tailclean = bool(element.value)
                else:
                    LOG.warning("Unknown setting: %s", name)
            except Exception:
                LOG.debug("Failed to set %s", element.get_name(),
                          exc_info=True)
                raise

    def get_tx_bands(self):
        return self._txbands

    def validate_memory(self, mem):
        msgs = []
        airband = (108000000, 135999999)
        if chirp_common.in_range(mem.freq, [airband]) and mem.mode != 'AM':
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range requires AM mode')))
        if (not chirp_common.in_range(mem.freq, [airband]) and
                mem.mode == 'AM'):
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range must not be AM mode')))
        if not chirp_common.in_range(mem.freq, self._txbands) and \
                mem.duplex != 'off':
            msgs.append(chirp_common.ValidationError(
                _('Frequency outside TX bands; set duplex=off for RX only')))
        return msgs + super().validate_memory(mem)


# ── Mode variants ────────────────────────────────────────────────────────────
# The TD-H9 ships in three firmware modes: Normal, HAM, and GMRS.
# Each returns a different 8-byte ident, all confirmed from hardware.

@directory.register
@directory.detected_by(TDH9)
class TDH9_HAM(TDH9):
    """TIDRADIO TD-H9 (HAM mode)"""
    MODEL = "TD-H9-HAM"
    _idents = [_TDH9_MAGIC]
    ident_mode = b'TDH9\xff\xff\xffH'

    # Per H9_Ham_Version_User_Manual.pdf Appendix B / Main Features:
    # TX: 136-174, 220-260, 350-390, 400-520 MHz
    # RX scan adds: FM 87-108, AM 108-136 MHz
    _txbands = [(136000000, 174000000), (220000000, 260000000),
                (350000000, 390000000), (400000000, 520000000)]
    _rxbands = [(87000000, 108000000),   # FM broadcast, RX only
                (108000000, 136000000)]  # Airband AM, RX only


@directory.register
@directory.detected_by(TDH9)
class TDH9_GMRS(TDH9):
    """TIDRADIO TD-H9 (GMRS mode)"""
    MODEL = "TD-H9-GMRS"
    _idents = [_TDH9_MAGIC]
    ident_mode = b'TDH9\xff\xff\xffG'

    # Per H9_GMRS_Version_User_Manual.pdf Appendix B / Main Features:
    # TX: GMRS channels only (462-468 MHz range)
    # RX scan: 87-108 FM, 108-136 AM, 136-174, 240-260, 350-370, 400-520 MHz
    _txbands = [(462000000, 468000000)]
    _rxbands = [(87000000, 108000000),
                (108000000, 136000000),
                (136000000, 174000000),
                (240000000, 260000000),
                (350000000, 370000000),
                (400000000, 462000000),
                (468000000, 520000000)]
    _tx_power = [
        chirp_common.PowerLevel("High", watts=5.0),
        chirp_common.PowerLevel("Low",  watts=1.0),
        chirp_common.PowerLevel("Mid",  watts=2.5),
    ]
