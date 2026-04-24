# Baofeng MP31 (38-channel) driver for CHIRP
# Based on h777.py from the CHIRP project (GPLv3)
# Modified by Torben Massat (KD9ZTC), 2025
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See <https://www.gnu.org/licenses/> for details.

# Much of the following was created with the help of ChatGPT, and troubleshooting was done by me
# WARNING: experimental. BACKUP your radio before uploading.
# Based closely on h777.py (Andrew Morgan) with memory expanded to 38 slots
# and memsize adjusted to match a 1385-byte dump (0x0569).

import time
import struct
import unittest
import logging

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettings

LOG = logging.getLogger(__name__)

# EEPROM memory layout parsed by bitwise.
# Each of the 38 channel slots starts at 0x0000 and is 12 bytes wide.
# Channel fields:
#   rxfreq/txfreq: BCD-encoded frequency in 10 Hz units; txfreq=0xFFFFFFFF means TX-off
#   rtone/ttone:   RX/TX CTCSS (freq*10) or DCS tone; 0xFFFF = no tone
#   skip:          1 = skip during scan
#   highpower:     1 = high power (5 W), 0 = low (1 W)
#   narrow:        1 = NFM (12.5 kHz), 0 = FM (25 kHz)
#   beatshift:     beat-shift/scramble, inverted (0 = on)
#   bcl:           busy channel lockout, inverted (0 = on)
# The settings block at 0x02B0 holds global radio config (VOX, scan, alarm, etc.)
#   voxlevel:      stored as 0–4 in EEPROM, displayed as 1–5
MEM_FORMAT = """
#seekto 0x0000;
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    lbcd rtone[2];
    lbcd ttone[2];
    u8 unknown3:1,
       unknown2:1,
       unknown1:1,
       skip:1,
       highpower:1,
       narrow:1,
       beatshift:1,
       bcl:1;
    u8 unknown4[3];
} memory[38];
#seekto 0x02B0;
struct {
    u8 voiceprompt;
    u8 voicelanguage;
    u8 scan;
    u8 vox;
    u8 voxlevel;
    u8 voxinhibitonrx;
    u8 lowvolinhibittx;
    u8 highvolinhibittx;
    u8 alarm;
    u8 fmradio;
} settings;
"""

# Extended settings block shared with H777-family radios.
# Fields at 0x026B:
#   squelchlevel: 0 = open, 9 = tight (inverted for display: display_val = 9 - stored)
#   timeout:      TX timeout — 0 = off, N = N*30 s in EEPROM (MP31 uses N*60 s steps in UI)
#   scanmode:     0 = carrier, 1 = time
#   sidekey:      index into SIDEKEYFUNCTION_LIST
H777_SETTINGS2 = """
#seekto 0x026B;
struct {
    u8 squelchlevel;
    u8 batterysaver;
    u8 voxdelay;
    u8 timeout;
    u8 scanmode;
    u8 beep;
    u8 sidekey;
    u8 rxemergency;
} settings2;

"""

# Alternative settings2 layout used by the BF-1900; not used by the MP31
# but kept here for reference / future alias support.
BF1900_SETTINGS2 = """
#seekto 0x026B;
struct {
    u8 unused:6,
    u8 batterysaver:1,
    u8 beep:1;
    u8 squelchlevel;
    u8 scanmode;
    u8 timeouttimer;
    u8 unused2[4];
} settings2;
"""

# Single-byte acknowledgement sent by the radio after each command/block.
CMD_ACK = b"\x06"
# All reads and writes transfer exactly 8 bytes per transaction.
BLOCK_SIZE = 0x08
# Address ranges written during an upload, broken into three segments:
#   0x0000–0x010F  channel memories
#   0x02B0–0x02BF  main settings
#   0x0380–0x03DF  extended settings / VFO data
UPLOAD_BLOCKS = [list(range(0x0000, 0x0110, 8)),
                 list(range(0x02b0, 0x02c0, 8)),
                 list(range(0x0380, 0x03e0, 8))]

VOICE_LIST = ["English", "Chinese"]
# Timeout timer options shown in the UI; index maps to 30-second increments.
TIMEOUTTIMER_LIST = ["Off", "30 seconds", "60 seconds", "90 seconds",
                     "120 seconds", "150 seconds", "180 seconds",
                     "210 seconds", "240 seconds", "270 seconds",
                     "300 seconds"]
# High bit of the upper tone byte signals DTCS (vs. CTCSS).
DTCS_FLAG = 0x80
# Second-highest bit signals reversed DTCS polarity (R vs. N).
DTCS_REV_FLAG = 0x40


def _h777_enter_programming_mode(serial, radio_cls):
    """Initiate programming mode and return the 8-byte radio identification string.

    Sends the two-phase handshake expected by H777-family firmware:
      1. 0x02 wake byte + PROGRAM_CMD → radio replies with ACK
      2. 0x02 request → radio sends 8-byte ident string → we ACK it
    Raises RadioError on any communication failure or unexpected response.
    """
    # Increase default timeout from .25 to .5 for all serial communications
    serial.timeout = 0.5

    try:
        serial.write(b"\x02")
        time.sleep(0.1)
        serial.write(radio_cls.PROGRAM_CMD)
        ack = serial.read(1)
    except Exception as e:
        LOG.warning('Failed to send program command: %s', e)
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio to program command")
    elif ack != CMD_ACK:
        LOG.warning('Ack from program command was %r, expected %r',
                    ack, CMD_ACK)
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write(b"\x02")
        # At least one version of the Baofeng BF-888S has a consistent
        # ~0.33s delay between sending the first five bytes of the
        # version data and the last three bytes. We need to raise the
        # timeout so that the read doesn't finish early.
        ident = serial.read(8)
    except Exception as e:
        LOG.warning('Failed to read ident: %s', e)
        raise errors.RadioError("Error communicating with radio")

    if ident:
        LOG.info('Radio identified with:\n%s', util.hexprint(ident))
        try:
            serial.write(CMD_ACK)
            ack = serial.read(1)
            if ack != CMD_ACK:
                raise errors.RadioError("Bad ACK after reading ident")
        except:
            raise errors.RadioError('No ACK after reading ident')
        return ident

    raise errors.RadioError('No identification received from radio')


def _h777_exit_programming_mode(serial):
    """Send the 'E' exit command to release the radio from programming mode."""
    try:
        serial.write(b"E")
    except Exception as e:
        LOG.warning('Failed to send exit command: %s', e)
        raise errors.RadioError("Radio refused to exit programming mode")


def _h777_read_block(radio, block_addr, block_size):
    """Read one 8-byte block from the radio at block_addr.

    Sends an 'R' read command and validates the echoed header before
    returning the payload bytes.  Returns None (instead of raising) on
    any per-block failure so the caller can decide whether to abort or skip.
    """
    serial = radio.pipe

    # Command format: 'R' + 2-byte big-endian address + 1-byte length
    cmd = struct.pack(">cHb", b'R', block_addr, BLOCK_SIZE)
    # The radio echoes back a 'W' header with the same address/length prefix
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + BLOCK_SIZE)
        if response[:4] != expectedresponse:
            LOG.warning('Got %r expected %r, skipping block %04x' % (
                response[:4], expectedresponse, block_addr))
            return None

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except Exception as e:
        LOG.warning("Exception reading block %04x: %s, skipping" % (block_addr, e))
        return None

    if ack != CMD_ACK:
        LOG.warning("No ACK for block %04x, skipping" % block_addr)
        return None

    return block_data


def _h777_write_block(radio, block_addr, block_size):
    """Write one 8-byte block from the radio's memory map to block_addr.

    Sends a 'W' write command followed immediately by the 8 data bytes
    and waits for an ACK.  Raises RadioError if the radio does not ACK.
    """
    serial = radio.pipe

    # Command format: 'W' + 2-byte big-endian address + 1-byte length
    cmd = struct.pack(">cHb", b'W', block_addr, BLOCK_SIZE)
    data = radio.get_mmap().get_byte_compatible()[block_addr:block_addr + 8]

    radio.pipe.log('Writing %i block at %04x' % (BLOCK_SIZE, block_addr))

    try:
        serial.write(cmd + data)
        # Time required to write data blocks varies between individual
        # radios of the Baofeng BF-888S model. The longest seen is
        # ~0.31s.
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def _h777_enter_single_programming_mode(radio):
    """Enter programming mode and verify the radio's ident string matches IDENT.

    Used when exactly one model is registered (i.e. no multi-model detection).
    Raises RadioError if the ident is missing or does not match any expected value.
    """
    ident = _h777_enter_programming_mode(radio.pipe, radio.__class__)
    if not ident:
        raise errors.RadioError('Radio did not identify')
    if not any(rc_ident in ident for rc_ident in radio.IDENT):
        LOG.warning('Expected %s for %s but got:\n%s',
                    radio.IDENT, radio.__class__.__name__,
                    util.hexprint(ident))
        raise errors.RadioError('Incorrect model')


def do_download(radio):
    """Clone all data from the radio into a MemoryMapBytes image.

    Iterates over radio._ranges in BLOCK_SIZE steps, reading each block
    and concatenating the results.  Returns the completed memory map.
    """
    LOG.debug("download")

    if len(radio.detected_models()) <= 1:
        LOG.debug('Entering programming mode for %s', radio.__class__.__name__)
        _h777_enter_single_programming_mode(radio)
    else:
        LOG.debug('Already in programming mode for %s',
                  radio.__class__.__name__)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, BLOCK_SIZE):
            status.cur = addr + BLOCK_SIZE
            radio.status_fn(status)

            radio.pipe.log('Reading %i block at %04x' % (BLOCK_SIZE, addr))
            block = _h777_read_block(radio, addr, BLOCK_SIZE)
            if block is None:
                raise errors.RadioError("Failed to read block at %04x" % addr)
            data += block

    _h777_exit_programming_mode(radio.pipe)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    """Write the in-memory image back to the radio.

    Enters programming mode, iterates over radio._ranges, and writes each
    block before sending the exit command.
    """
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _h777_enter_single_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, BLOCK_SIZE):
            status.cur = addr + BLOCK_SIZE
            radio.status_fn(status)
            _h777_write_block(radio, addr, BLOCK_SIZE)

    _h777_exit_programming_mode(radio.pipe)


# OEM alias: the Pxton PX999S appears to be the same hardware as the MP31.
class Pxtonpx999s(chirp_common.Alias):
    VENDOR = 'Pxton'
    MODEL = 'px999s'

@directory.register
class MP31Radio(chirp_common.CloneModeRadio):
    """Baofeng MP31"""
    VENDOR = "Baofeng"
    MODEL = "MP31"
    # Seven-byte program command sent after the 0x02 wake byte.
    PROGRAM_CMD = b'PROGRAM'
    # Expected prefix(es) in the 8-byte ident response from the radio.
    IDENT = [b"P3107", ]
    BAUD_RATE = 9600

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("High", watts=5.00)]
    VALID_BANDS = (400000000, 490000000)
    MAX_VOXLEVEL = 5
    ALIASES = [Pxtonpx999s]
    SIDEKEYFUNCTION_LIST = ["Off", "Monitor", "Transmit Power", "Alarm"]
    SCANMODE_LIST = ["Carrier", "Time"]

    # Only read addresses the radio actually responds to (confirmed via debug log)
    _ranges = [
        (0x0000, 0x0400),
    ]
    _memsize = 0x0400
    # The radio labels its channels 1–38 but the EEPROM stores them in reverse
    # order.  MEMORY_ROTATION is used to map CHIRP channel numbers to EEPROM
    # indices: eeprom_index = MEMORY_ROTATION - (number - 1).
    MEMORY_COUNT = 38
    MEMORY_ROTATION = 37

    _has_fm = True
    _has_sidekey = True
    _has_scanmodes = True
    _has_scramble = True

    def get_features(self):
        """Declare the capabilities and constraints of the MP31 to CHIRP."""
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.valid_modes = ["NFM", "FM"]  # 12.5 kHz, 25 kHz.
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.can_odd_split = True
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.has_name = False
        rf.memory_bounds = (1, 38)
        rf.valid_bands = [self.VALID_BANDS]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0,
                                 50.0, 100.0]

        return rf

    def process_mmap(self):
        """Parse the raw memory map into structured objects using MEM_FORMAT."""
        self._memobj = bitwise.parse(MEM_FORMAT + H777_SETTINGS2, self._mmap)

    def sync_in(self):
        """Download image from radio and parse it."""
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        """Upload the current image to the radio."""
        do_upload(self)

    def get_raw_memory(self, number):
        """Return a raw hex string for channel number (1-based), for debugging."""
        return repr(self._memobj.memory[number - 1])

    def _decode_tone(self, memval):
        """Decode a raw 2-byte EEPROM tone value into (mode, value, polarity).

        Returns:
            ('', None, None)        — no tone
            ('Tone', float, None)   — CTCSS frequency in Hz (e.g. 88.5)
            ('DTCS', int, 'N'|'R')  — DCS code and polarity
        """
        # Tell bitwise to ignore the flag bits when converting to an integer
        memval[1].ignore_bits(DTCS_FLAG | DTCS_REV_FLAG)
        is_dtcs = memval[1].get_bits(DTCS_FLAG)
        is_rev = memval[1].get_bits(DTCS_REV_FLAG)
        if memval.get_raw() == b"\xFF\xFF":
            # 0xFFFF is the sentinel for "no tone programmed"
            return '', None, None
        elif is_dtcs:
            return 'DTCS', int(memval), 'R' if is_rev else 'N'
        else:
            # CTCSS is stored as frequency * 10 (e.g. 885 = 88.5 Hz)
            return 'Tone', int(memval) / 10.0, None

    def _encode_tone(self, memval, mode, value, pol):
        """Encode a CHIRP tone tuple back into the 2-byte EEPROM format.

        Args:
            memval: the lbcd[2] field in the memory struct
            mode:   '', 'Tone', or 'DTCS'
            value:  CTCSS frequency (float) or DCS code (int); ignored for ''
            pol:    'N' or 'R' for DTCS; ignored otherwise
        """
        memval[1].ignore_bits(DTCS_FLAG | DTCS_REV_FLAG)
        if mode == '':
            # No tone — fill both bytes with 0xFF
            memval.fill_raw(b'\xFF')
        elif mode == 'Tone':
            # Store CTCSS as integer tenths of Hz; clear DCS flags
            memval[1].clr_bits(DTCS_FLAG | DTCS_REV_FLAG)
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            memval[1].set_bits(DTCS_FLAG)
            if pol == 'R':
                memval[1].set_bits(DTCS_REV_FLAG)
            else:
                memval[1].clr_bits(DTCS_REV_FLAG)
            memval.set_value(value)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def get_memory(self, number):
        """Read channel number (1-based) from the image and return a Memory object."""
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()

        mem.number = number
        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        # All-0xFF in the RX frequency field also means the channel is empty
        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        # Determine duplex mode from the relationship between RX and TX frequencies
        if _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            # TX disabled (simplex listen-only or monitor channel)
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            # Simplex: RX == TX
            mem.duplex = ""
            mem.offset = 0
        else:
            # Offset: determine sign from which frequency is higher
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = not _mem.narrow and "FM" or "NFM"
        mem.power = self.POWER_LEVELS[_mem.highpower]

        mem.skip = _mem.skip and "S" or ""

        txtone = self._decode_tone(_mem.ttone)
        rxtone = self._decode_tone(_mem.rtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # Extra per-channel settings exposed in the CHIRP "Properties" tab
        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueBoolean(not _mem.bcl))
        mem.extra.append(rs)
        if self._has_scramble:
            # beatshift is the radio's name for the audio scrambler
            rs = RadioSetting("beatshift", "Beat Shift(scramble)",
                              RadioSettingValueBoolean(not _mem.beatshift))
            mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        """Write a Memory object into the in-memory image at channel mem.number."""
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            # Erase the channel by filling all bytes with 0xFF
            _mem.set_raw("\xFF" * (_mem.size() // 8))
            return

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            # Disable TX by setting all TX frequency bytes to 0xFF
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            # Simplex: TX == RX
            _mem.txfreq = mem.freq / 10

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.ttone, *txtone)
        self._encode_tone(_mem.rtone, *rxtone)

        _mem.narrow = 'N' in mem.mode
        _mem.highpower = mem.power == self.POWER_LEVELS[1]
        _mem.skip = mem.skip == "S"

        for setting in mem.extra:
            # NOTE: Only two settings right now, both are inverted
            setattr(_mem, setting.get_name(), not int(setting.value))

        # When set to one, official programming software (BF-480) shows always
        # "WFM", even if we choose "NFM". Therefore, for compatibility
        # purposes, we will set these to zero.
        _mem.unknown1 = 0
        _mem.unknown2 = 0
        _mem.unknown3 = 0

    def get_settings(self):
        """Return all user-adjustable settings for the Baofeng MP31 (38-channel)"""
        basic = RadioSettingGroup("basic", "Basic Settings")

        # --- SETTINGS BLOCK (10-byte) ---
        # Voice prompt
        rs = RadioSetting("settings.voiceprompt", "Voice Prompt",
                          RadioSettingValueBoolean(self._memobj.settings.voiceprompt))
        basic.append(rs)

        # Scan enable
        rs = RadioSetting("settings.scan", "Scan Enable",
                          RadioSettingValueBoolean(self._memobj.settings.scan))
        basic.append(rs)

        # VOX
        rs = RadioSetting("settings.vox", "VOX",
                          RadioSettingValueBoolean(self._memobj.settings.vox))
        basic.append(rs)

        # VOX sensitivity: EEPROM stores 0–4, UI shows 1–5
        rs = RadioSetting("settings.voxlevel", "VOX Level",
                          RadioSettingValueInteger(1, 5, self._memobj.settings.voxlevel + 1))
        basic.append(rs)

        # --- SETTINGS2 BLOCK (extended) ---
        # Squelch (inverted scale: 0=open, 9=closed).
        # Clamp stored value to 0–9 before inverting; uninitialized EEPROM
        # can contain 0xFF, which would produce a negative display value.
        stored = min(9, int(self._memobj.settings2.squelchlevel))
        display_val = 9 - stored  # invert so 0 = open squelch in the UI
        rs = RadioSetting("settings2.squelchlevel", "Squelch Level",
                          RadioSettingValueInteger(0, 9, display_val))
        basic.append(rs)

        # Battery Saver
        rs = RadioSetting("settings2.batterysaver", "Battery Saver",
                          RadioSettingValueBoolean(self._memobj.settings2.batterysaver))
        basic.append(rs)

        # Timeout Timer (Off = 0, then 30s steps up to 300s)
        try:
            val = int(self._memobj.settings2.timeout)
        except Exception:
            val = 0
        # Convert EEPROM increment (N * 30 s) to actual seconds for display
        seconds = 0 if val == 0 else val * 30
        options = [str(x) for x in [0,60,120,180,240,300,360,420,480,540,600]]
        cur_str = str(seconds) if str(seconds) in options else "0"
        rs = RadioSetting("settings2.timeout", "Timeout Timer (s)",
                          RadioSettingValueList(options,
                                               current_index=options.index(cur_str)))
        basic.append(rs)

        return RadioSettings(basic)

    def set_settings(self, settings):
        """Apply user-selected settings back into memory structure"""
        for element in settings:
            if not isinstance(element, RadioSetting):
                # Recurse into groups
                self.set_settings(element)
                continue

            name = element.get_name()
            value = element.value.get_value()

            # --- SETTINGS BLOCK (10-byte) ---
            if name == "settings.voiceprompt":
                self._memobj.settings.voiceprompt = bool(value)

            elif name == "settings.scan":
                self._memobj.settings.scan = bool(value)

            elif name == "settings.vox":
                self._memobj.settings.vox = bool(value)

            elif name == "settings.voxlevel":
                # GUI 1–5 → EEPROM 0–4
                self._memobj.settings.voxlevel = int(value) - 1

            # --- SETTINGS2 BLOCK (extended) ---
            elif name == "settings2.squelchlevel":
                # GUI 0=open, 9=closed → EEPROM inverted (9–value)
                self._memobj.settings2.squelchlevel = 9 - int(value)

            elif name == "settings2.batterysaver":
                self._memobj.settings2.batterysaver = bool(value)

            elif name == "settings2.timeout":
                # GUI shows seconds (0, 60, 120, … 600)
                sec = int(value)
                if sec == 0:
                    self._memobj.settings2.timeout = 0
                else:
                    # EEPROM byte increments by 60 s
                    self._memobj.settings2.timeout = int(sec / 60)
