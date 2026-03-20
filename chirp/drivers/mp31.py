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

CMD_ACK = b"\x06"
BLOCK_SIZE = 0x08
UPLOAD_BLOCKS = [list(range(0x0000, 0x0110, 8)),
                 list(range(0x02b0, 0x02c0, 8)),
                 list(range(0x0380, 0x03e0, 8))]

VOICE_LIST = ["English", "Chinese"]
TIMEOUTTIMER_LIST = ["Off", "30 seconds", "60 seconds", "90 seconds",
                     "120 seconds", "150 seconds", "180 seconds",
                     "210 seconds", "240 seconds", "270 seconds",
                     "300 seconds"]
DTCS_FLAG = 0x80
DTCS_REV_FLAG = 0x40


def _h777_enter_programming_mode(serial, radio_cls):
    # increase default timeout from .25 to .5 for all serial communications
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
    try:
        serial.write(b"E")
    except Exception as e:
        LOG.warning('Failed to send exit command: %s', e)
        raise errors.RadioError("Radio refused to exit programming mode")


def _h777_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, BLOCK_SIZE)
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
    serial = radio.pipe

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
    ident = _h777_enter_programming_mode(radio.pipe, radio.__class__)
    if not ident:
        raise errors.RadioError('Radio did not identify')
    if not any(rc_ident in ident for rc_ident in radio.IDENT):
        LOG.warning('Expected %s for %s but got:\n%s',
                    radio.IDENT, radio.__class__.__name__,
                    util.hexprint(ident))
        raise errors.RadioError('Incorrect model')


def do_download(radio):
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


class Pxtonpx999s(chirp_common.Alias):
    VENDOR = 'Pxton'
    MODEL = 'px999s'

@directory.register
class MP31Radio(chirp_common.CloneModeRadio):
    """Baofeng MP31"""
    VENDOR = "Baofeng"
    MODEL = "MP31"
    PROGRAM_CMD = b'PROGRAM'
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
    # Adjusting offset to align with verbal readout (Entry 1 is 38 on radio)
    MEMORY_COUNT = 38
    MEMORY_ROTATION = 37

    _has_fm = True
    _has_sidekey = True
    _has_scanmodes = True
    _has_scramble = True

    def get_features(self):
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
        self._memobj = bitwise.parse(MEM_FORMAT + H777_SETTINGS2, self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _decode_tone(self, memval):
        memval[1].ignore_bits(DTCS_FLAG | DTCS_REV_FLAG)
        is_dtcs = memval[1].get_bits(DTCS_FLAG)
        is_rev = memval[1].get_bits(DTCS_REV_FLAG)
        if memval.get_raw() == b"\xFF\xFF":
            return '', None, None
        elif is_dtcs:
            return 'DTCS', int(memval), 'R' if is_rev else 'N'
        else:
            return 'Tone', int(memval) / 10.0, None

    def _encode_tone(self, memval, mode, value, pol):
        memval[1].ignore_bits(DTCS_FLAG | DTCS_REV_FLAG)
        if mode == '':
            memval.fill_raw(b'\xFF')
        elif mode == 'Tone':
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
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()

        mem.number = number
        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = not _mem.narrow and "FM" or "NFM"
        mem.power = self.POWER_LEVELS[_mem.highpower]

        mem.skip = _mem.skip and "S" or ""

        txtone = self._decode_tone(_mem.ttone)
        rxtone = self._decode_tone(_mem.rtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueBoolean(not _mem.bcl))
        mem.extra.append(rs)
        if self._has_scramble:
            rs = RadioSetting("beatshift", "Beat Shift(scramble)",
                              RadioSettingValueBoolean(not _mem.beatshift))
            mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xFF" * (_mem.size() // 8))
            return

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
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
    
        rs = RadioSetting("settings.voxlevel", "VOX Level",
                          RadioSettingValueInteger(1, 5, self._memobj.settings.voxlevel + 1))
        basic.append(rs)
    
        # --- SETTINGS2 BLOCK (extended) ---
        # Squelch (inverted scale: 0=open, 9=closed)
        stored = self._memobj.settings2.squelchlevel
        display_val = 9 - stored
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
        seconds = 0 if val == 0 else val * 30
        options = [str(x) for x in [0,60,120,180,240,300,360,420,480,540,600]]
        if str(seconds) not in options:
            seconds = "0"
        rs = RadioSetting("settings2.timeout", "Timeout Timer (s)",
                          RadioSettingValueList(options, str(seconds)))
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

