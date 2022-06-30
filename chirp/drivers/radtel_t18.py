# Copyright 2021 Jim Unroe <rock.unroe@gmail.com>
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

import time
import os
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
#seekto 0x0010;
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    lbcd rxtone[2];
    lbcd txtone[2];
    u8 unknown1:1,
       compander:1,
       scramble:1,
       skip:1,
       highpower:1,
       narrow:1,
       unknown2:1,
       bcl:1;
    u8 unknown3[3];
} memory[%d];
#seekto 0x03C0;
struct {
    u8 unknown1:1,
       scanmode:1,
       vox:1,            // Retevis RB19 VOX
       speccode:1,
       voiceprompt:2,
       batterysaver:1,
       beep:1;
    u8 squelchlevel;
    u8 sidekey2;         // Retevis RT22S setting
                         // Retevis RB85 sidekey 1 short
                         // Retevis RB19 sidekey 2 long
    u8 timeouttimer;
    u8 voxlevel;
    u8 sidekey2S;
    u8 unused;
    u8 voxdelay;
    u8 sidekey1L;
    u8 sidekey2L;
    u8 unused2[3];
    u8 unknown3:4,
       unknown4:1,
       unknown5:2,
       power10w:1;       // Retevis RT85 power 10w on/off
                         // Retevis RT75 stop TX with low voltage
} settings;

#seekto 0x02B0;
struct {
    u8 voicesw;      // Voice SW            +
    u8 unknown1;
    u8 scan;         // Scan                +
    u8 vox;          // VOX                 +
    u8 voxgain;      // Vox Gain            +
    u8 voxnotxonrx;  // Rx Disable Vox      +
    u8 hivoltnotx;   // High Vol Inhibit TX +
    u8 lovoltnotx;   // Low Vol Inhibit TX  +
} settings2;
"""

MEM_FORMAT_RB18 = """
#seekto 0x0000;
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    lbcd rxtone[2];
    lbcd txtone[2];
    u8 jumpcode:1,
       unknown1:2,
       skip:1,
       highpower:1,
       narrow:1,
       unknown2:1,
       bcl:1;
    u8 unknown3[3];
} memory[%d];
#seekto 0x0630;
struct {
    u8 unk630:7,
       voice:1;
    u8 unk631:7,
       language:1;
    u8 unk632:7,
       scan:1;
    u8 unk633:7,
       vox:1;
    u8 unk634:5,
       vox_level:3;
    u8 unk635;
    u8 unk636:7,
       lovoltnotx:1;
    u8 unk637:7,
       hivoltnotx:1;
    u8 unknown2[8];
    u8 unk640:5,
       rogerbeep:1,
       batterysaver:1,
       beep:1;
    u8 squelchlevel;
    u8 unk642;
    u8 timeouttimer;
    u8 unk644:7,
       tail:1;
    u8 channel;
} settings;
"""

CMD_ACK = "\x06"

VOICE_LIST = ["Off", "Chinese", "English"]
VOICE_LIST2 = ["English", "Chinese"]
TIMEOUTTIMER_LIST = ["Off", "30 seconds", "60 seconds", "90 seconds",
                     "120 seconds", "150 seconds", "180 seconds",
                     "210 seconds", "240 seconds", "270 seconds",
                     "300 seconds"]
SCANMODE_LIST = ["Carrier", "Time"]
VOXLEVEL_LIST = ["Off", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
VOXDELAY_LIST = ["0.5 seconds", "1.0 seconds", "1.5 seconds",
                 "2.0 seconds", "2.5 seconds", "3.0 seconds"]
SIDEKEY19_LIST = ["Off", "Scan", "Emergency Alarm"]
SIDEKEY2_LIST = SIDEKEY19_LIST + ["Display Battery"]

SIDEKEY85SHORT_LIST = ["Off",
                       "Noise Cansellation On",
                       "Continuous Monitor",
                       "High/Low Power",
                       "Emergency Alarm",
                       "Show Battery",
                       "Scan",
                       "VOX",
                       "Busy Channel Lock"]
SIDEKEY85LONG_LIST = ["Off",
                      "Noise Cansellation On",
                      "Continuous Monitor",
                      "Monitor Momentary",
                      "High/Low Power",
                      "Emergency Alarm",
                      "Show Battery",
                      "Scan",
                      "VOX",
                      "Busy Channel Lock"]
SPECCODE_LIST = ["SpeCode 1", "SpeCode 2"]
SIDEKEY75_LIST = ["Off",
                  "Monitor Momentary",
                  "Scan",
                  "VOX",
                  "Monitor",
                  "Announciation"]

SETTING_LISTS = {
    "voiceprompt": VOICE_LIST,
    "language": VOICE_LIST2,
    "timeouttimer": TIMEOUTTIMER_LIST,
    "scanmode": SCANMODE_LIST,
    "voxlevel": VOXLEVEL_LIST,
    "voxdelay": VOXDELAY_LIST,
    "sidekey2": SIDEKEY2_LIST,
    "sidekey2": SIDEKEY19_LIST,
    "sidekey2": SIDEKEY85SHORT_LIST,
    "sidekey1L": SIDEKEY85LONG_LIST,
    "sidekey2S": SIDEKEY85SHORT_LIST,
    "sidekey2L": SIDEKEY85LONG_LIST,
    "speccode": SPECCODE_LIST
}

FRS_FREQS1 = [462.5625, 462.5875, 462.6125, 462.6375, 462.6625,
              462.6875, 462.7125]
FRS_FREQS2 = [467.5625, 467.5875, 467.6125, 467.6375, 467.6625,
              467.6875, 467.7125]
FRS_FREQS3 = [462.5500, 462.5750, 462.6000, 462.6250, 462.6500,
              462.6750, 462.7000, 462.7250]
FRS_FREQS = FRS_FREQS1 + FRS_FREQS2 + FRS_FREQS3

FRS16_FREQS = [462.5625, 462.5875, 462.6125, 462.6375,
               462.6625, 462.6250, 462.7250, 462.6875,
               462.7125, 462.5500, 462.5750, 462.6000,
               462.6500, 462.6750, 462.7000, 462.7250]

GMRS_FREQS = FRS_FREQS1 + FRS_FREQS2 + FRS_FREQS3 * 2

MURS_FREQS = [151.820, 151.880, 151.940, 154.570, 154.600]

PMR_FREQS1 = [446.00625, 446.01875, 446.03125, 446.04375, 446.05625,
              446.06875, 446.08125, 446.09375]
PMR_FREQS2 = [446.10625, 446.11875, 446.13125, 446.14375, 446.15625,
              446.16875, 446.18125, 446.19375]
PMR_FREQS = PMR_FREQS1 + PMR_FREQS2


def _t18_enter_programming_mode(radio):
    serial = radio.pipe

    try:
        serial.write("\x02")
        time.sleep(0.01)
        serial.write(radio._magic)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio")
    elif ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write("\x02")
        ident = serial.read(8)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ident.startswith(radio._fingerprint):
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _t18_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(radio.CMD_EXIT)
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _t18_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        if radio.ACK_BLOCK:
            serial.write(CMD_ACK)
            ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if radio.ACK_BLOCK:
        if ack != CMD_ACK:
            raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _t18_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _t18_enter_programming_mode(radio)

    data = ""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _t18_read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _t18_exit_programming_mode(radio)

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _t18_enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE):
            status.cur = addr + radio.BLOCK_SIZE
            radio.status_fn(status)
            _t18_write_block(radio, addr, radio.BLOCK_SIZE)

    _t18_exit_programming_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if len(data) == cls._memsize:
        rid = data[0x03D0:0x03D8]
        return "P558" in rid
    else:
        return False


@directory.register
class T18Radio(chirp_common.CloneModeRadio):
    """radtel T18"""
    VENDOR = "Radtel"
    MODEL = "T18"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x08
    CMD_EXIT = "b"
    ACK_BLOCK = True

    VALID_BANDS = [(400000000, 470000000)]

    _magic = "1ROGRAM"
    _fingerprint = "SMP558" + "\x00\x00"
    _upper = 16
    _mem_params = (_upper  # number of channels
                   )
    _frs = _murs = _pmr = _gmrs = False

    _ranges = [
        (0x0000, 0x03F0),
    ]
    _memsize = 0x03F0

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.valid_modes = ["NFM", "FM"]  # 12.5 KHz, 25 kHz.
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        if self.MODEL != "T18" and self.MODEL != "RB618":
            rf.valid_power_levels = self.POWER_LEVELS
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
        rf.memory_bounds = (1, self._upper)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = chirp_common.TUNING_STEPS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params, self._mmap)

    def validate_memory(self, mem):
        msgs = ""
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)

        _msg_freq = 'Memory location cannot change frequency'
        _msg_simplex = 'Memory location only supports Duplex:(None)'
        _msg_duplex = 'Memory location only supports Duplex: +'
        _msg_nfm = 'Memory location only supports Mode: NFM'
        _msg_txp = 'Memory location only supports Power: Low'

        # FRS only models
        if self._frs:
            # range of memories with values set by FCC rules
            if self._upper == 22:
                if mem.freq != int(FRS_FREQS[mem.number - 1] * 1000000):
                    # warn user can't change frequency
                    msgs.append(chirp_common.ValidationError(_msg_freq))
                if mem.number >= 8 and mem.number <= 14:
                    if str(mem.power) != "Low":
                        # warn user can't change power
                        msgs.append(chirp_common.ValidationError(_msg_txp))
            else:
                if mem.freq != int(FRS16_FREQS[mem.number - 1] * 1000000):
                    # warn user can't change frequency
                    msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 16/22 are simplex only
            if str(mem.duplex) != "":
                # warn user can't change duplex
                msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 1 - 16/22 are NFM only
            if str(mem.mode) != "NFM":
                # warn user can't change mode
                msgs.append(chirp_common.ValidationError(_msg_nfm))

        # GMRS only models
        if self._gmrs:
            # range of memories with values set by FCC rules
            if mem.freq != int(GMRS_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))
            if mem.number >= 8 and mem.number <= 14:
                if str(mem.power) != "Low":
                    # warn user can't change power
                    msgs.append(chirp_common.ValidationError(_msg_txp))

                if str(mem.mode) != "NFM":
                    # warn user can't change mode
                    msgs.append(chirp_common.ValidationError(_msg_nfm))

            if mem.number >= 1 and mem.number <= 22:
                # channels 1 - 22 are simplex only
                if str(mem.duplex) != "":
                    # warn user can't change duplex
                    msgs.append(chirp_common.ValidationError(_msg_simplex))

            if mem.number >= 23 and mem.number <= 30:
                # channels 23 - 30 are duplex + only
                if str(mem.duplex) != "+":
                    # warn user can't change duplex
                    msgs.append(chirp_common.ValidationError(_msg_duplex))

        # MURS only models
        if self._murs:
            # range of memories with values set by FCC rules
            if mem.freq != int(MURS_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 5 are simplex only
            if str(mem.duplex) != "":
                # warn user can't change duplex
                msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 1 - 3 are NFM only
            if mem.number <= 3:
                if mem.mode != "NFM":
                    # warn user can't change mode
                    msgs.append(chirp_common.ValidationError(_msg_nfm))

        # PMR only models
        if self._pmr:
            # range of memories with values set by PMR rules
            if mem.freq != int(PMR_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 16 are simplex only
            if str(mem.duplex) != "":
                # warn user can't change duplex
                msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 1 - 16 are NFM only
            if str(mem.mode) != "NFM":
                # warn user can't change mode
                msgs.append(chirp_common.ValidationError(_msg_nfm))

        return msgs

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _decode_tone(self, val):
        val = int(val)
        if val == 16665:
            return '', None, None
        elif val >= 12000:
            return 'DTCS', val - 12000, 'R'
        elif val >= 8000:
            return 'DTCS', val - 8000, 'N'
        else:
            return 'Tone', val / 10.0, None

    def _encode_tone(self, memval, mode, value, pol):
        if mode == '':
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            flag = 0x80 if pol == 'N' else 0xC0
            memval.set_value(value)
            memval[1].set_bits(flag)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()

        mem.number = number
        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == "\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if _mem.txfreq.get_raw() == "\xFF\xFF\xFF\xFF":
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = not _mem.narrow and "FM" or "NFM"

        mem.skip = _mem.skip and "S" or ""

        txtone = self._decode_tone(_mem.txtone)
        rxtone = self._decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        if self.MODEL != "T18" and self.MODEL != "RB618":
            mem.power = self.POWER_LEVELS[_mem.highpower]

        if self._frs:
            FRS_IMMUTABLE = ["freq", "duplex", "offset", "mode"]
            if self._upper == 22:
                if mem.number >= 8 and mem.number <= 14:
                    FRS_IMMUTABLE = FRS_IMMUTABLE + ["power"]

            mem.immutable = FRS_IMMUTABLE

        if self._gmrs:
            GMRS_IMMUTABLE = ["freq", "duplex", "offset"]
            if mem.number >= 8 and mem.number <= 14:
                GMRS_IMMUTABLE = GMRS_IMMUTABLE + ["mode", "power"]

            mem.immutable = GMRS_IMMUTABLE

        if self._murs:
            MURS_IMMUTABLE = ["freq", "duplex", "offset"]
            if mem.number <= 3:
                MURS_IMMUTABLE = MURS_IMMUTABLE + ["mode"]

            mem.immutable = MURS_IMMUTABLE

        if self._pmr:
            PMR_IMMUTABLE = ["freq", "duplex", "offset", "mode", "power"]
            mem.immutable = PMR_IMMUTABLE

        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueBoolean(not _mem.bcl))
        mem.extra.append(rs)
        if self.MODEL != "RB18" and self.MODEL != "RB618":
            rs = RadioSetting("scramble", "Scramble",
                              RadioSettingValueBoolean(not _mem.scramble))
            mem.extra.append(rs)
            rs = RadioSetting("compander", "Compander",
                              RadioSettingValueBoolean(not _mem.compander))
            mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            if self._frs:
                _mem.set_raw("\xFF" * 12 + "\x00" + "\xFF" * 3)
                if self._upper == 22:
                    FRS_FREQ = int(FRS_FREQS[mem.number - 1] * 100000)
                else:
                    FRS_FREQ = int(FRS16_FREQS[mem.number - 1] * 100000)
                _mem.rxfreq = _mem.txfreq = FRS_FREQ
                _mem.narrow = True
                _mem.highpower = True
                if self._upper == 22:
                    if mem.number >= 8 and mem.number <= 14:
                        _mem.highpower = False
            elif self._gmrs:
                _mem.set_raw("\xFF" * 12 + "\x00" + "\xFF" * 3)
                GMRS_FREQ = int(GMRS_FREQS[mem.number - 1] * 100000)
                if mem.number > 22:
                    _mem.rxfreq = GMRS_FREQ
                    _mem.txfreq = int(_mem.rxfreq) + 500000
                else:
                    _mem.rxfreq = _mem.txfreq = GMRS_FREQ
                if mem.number >= 8 and mem.number <= 14:
                    _mem.narrow = True
                    _mem.highpower = False
                else:
                    _mem.narrow = False
                    _mem.highpower = True
            elif self._murs:
                _mem.set_raw("\xFF" * 12 + "\x00" + "\xFF" * 3)
                MURS_FREQ = int(MURS_FREQS[mem.number - 1] * 100000)
                _mem.rxfreq = _mem.txfreq = MURS_FREQ
                _mem.highpower = True
                if mem.number <= 3:
                    _mem.narrow = True
                else:
                    _mem.narrow = False
            elif self._pmr:
                _mem.set_raw("\xFF" * 12 + "\x00" + "\xFF" * 3)
                PMR_FREQ = int(PMR_FREQS[mem.number - 1] * 100000)
                _mem.rxfreq = _mem.txfreq = PMR_FREQ
                _mem.narrow = True
                _mem.highpower = False
            else:
                _mem.set_raw("\xFF" * (_mem.size() / 8))

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
        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)

        if self.MODEL != "T18" and self.MODEL != "RB18":
            _mem.highpower = mem.power == self.POWER_LEVELS[1]

        _mem.narrow = 'N' in mem.mode
        _mem.skip = mem.skip == "S"

        for setting in mem.extra:
            # NOTE: Only three settings right now, all are inverted
            setattr(_mem, setting.get_name(), not int(setting.value))

    def get_settings(self):
        _settings = self._memobj.settings
        if self.MODEL == "FRS-B1":
            _settings2 = self._memobj.settings2
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        rs = RadioSetting("squelchlevel", "Squelch level",
                          RadioSettingValueInteger(
                              0, 9, _settings.squelchlevel))
        basic.append(rs)

        rs = RadioSetting("timeouttimer", "Timeout timer",
                          RadioSettingValueList(
                              TIMEOUTTIMER_LIST,
                              TIMEOUTTIMER_LIST[
                                  _settings.timeouttimer]))
        basic.append(rs)

        if self.MODEL == "RB18" or self.MODEL == "RB618":
            rs = RadioSetting("scan", "Scan",
                              RadioSettingValueBoolean(_settings.scan))
            basic.append(rs)
        elif self.MODEL == "FRS-B1":
            rs = RadioSetting("settings2.scan", "Scan",
                              RadioSettingValueBoolean(_settings2.scan))
            basic.append(rs)
        else:
            rs = RadioSetting("scanmode", "Scan mode",
                              RadioSettingValueList(
                                  SCANMODE_LIST,
                                  SCANMODE_LIST[_settings.scanmode]))
            basic.append(rs)

        if self.MODEL == "RT22S":
            rs = RadioSetting("voiceprompt", "Voice prompts",
                              RadioSettingValueBoolean(_settings.voiceprompt))
            basic.append(rs)
        elif self.MODEL == "RB18" or self.MODEL == "RB618":
            rs = RadioSetting("voice", "Voice prompts",
                              RadioSettingValueBoolean(_settings.voice))
            basic.append(rs)
        elif self.MODEL == "FRS-B1":
            rs = RadioSetting("settings2.voicesw", "Voice prompts",
                              RadioSettingValueBoolean(_settings2.voicesw))
            basic.append(rs)
        else:
            rs = RadioSetting("voiceprompt", "Voice prompts",
                              RadioSettingValueList(
                                  VOICE_LIST,
                                  VOICE_LIST[_settings.voiceprompt]))
            basic.append(rs)

        rs = RadioSetting("batterysaver", "Battery saver",
                          RadioSettingValueBoolean(_settings.batterysaver))
        basic.append(rs)

        if self.MODEL != "RB75":
            rs = RadioSetting("beep", "Beep",
                              RadioSettingValueBoolean(_settings.beep))
            basic.append(rs)

        if self.MODEL == "RB19" or self.MODEL == "RB19P" \
                or self.MODEL == "RB619":
            rs = RadioSetting("vox", "VOX",
                              RadioSettingValueBoolean(_settings.vox))
            basic.append(rs)

        if self.MODEL != "RB18" and self.MODEL != "RB618" \
                and self.MODEL != "FRS-B1":
            rs = RadioSetting("voxlevel", "Vox level",
                              RadioSettingValueList(
                                  VOXLEVEL_LIST,
                                  VOXLEVEL_LIST[_settings.voxlevel]))
            basic.append(rs)

            rs = RadioSetting("voxdelay", "VOX delay",
                              RadioSettingValueList(
                                  VOXDELAY_LIST,
                                  VOXDELAY_LIST[_settings.voxdelay]))
            basic.append(rs)

        if self.MODEL == "RT22S":
            rs = RadioSetting("sidekey2", "Side Key 2(Long)",
                              RadioSettingValueList(
                                  SIDEKEY2_LIST,
                                  SIDEKEY2_LIST[_settings.sidekey2]))
            basic.append(rs)

        if self.MODEL == "RB18" or self.MODEL == "RB618":
            rs = RadioSetting("language", "Language",
                              RadioSettingValueList(
                                  VOICE_LIST2,
                                  VOICE_LIST2[_settings.language]))
            basic.append(rs)

            rs = RadioSetting("tail", "Tail",
                              RadioSettingValueBoolean(_settings.tail))
            basic.append(rs)

            rs = RadioSetting("hivoltnotx", "High voltage no TX",
                              RadioSettingValueBoolean(_settings.hivoltnotx))
            basic.append(rs)

            rs = RadioSetting("lovoltnotx", "Low voltage no TX",
                              RadioSettingValueBoolean(_settings.lovoltnotx))
            basic.append(rs)

            rs = RadioSetting("vox", "VOX",
                              RadioSettingValueBoolean(_settings.vox))
            basic.append(rs)

            if _settings.vox_level > 4:
                val = 1
            else:
                val = _settings.vox_level + 1
            rs = RadioSetting("vox_level", "VOX level",
                              RadioSettingValueInteger(1, 5, val))
            basic.append(rs)

            rs = RadioSetting("rogerbeep", "Roger beep",
                              RadioSettingValueBoolean(_settings.rogerbeep))
            basic.append(rs)

        if self.MODEL == "RB85":
            rs = RadioSetting("speccode", "SpecCode Select",
                              RadioSettingValueList(
                                  SPECCODE_LIST,
                                  SPECCODE_LIST[_settings.speccode]))
            basic.append(rs)

            rs = RadioSetting("sidekey2", "Side Key 1(Short)",
                              RadioSettingValueList(
                                  SIDEKEY85SHORT_LIST,
                                  SIDEKEY85SHORT_LIST[_settings.sidekey2]))
            basic.append(rs)

            rs = RadioSetting("sidekey1L", "Side Key 1(Long)",
                              RadioSettingValueList(
                                  SIDEKEY85LONG_LIST,
                                  SIDEKEY85LONG_LIST[_settings.sidekey1L]))
            basic.append(rs)

            rs = RadioSetting("sidekey2S", "Side Key 2(Short)",
                              RadioSettingValueList(
                                  SIDEKEY85SHORT_LIST,
                                  SIDEKEY85SHORT_LIST[_settings.sidekey2S]))
            basic.append(rs)

            rs = RadioSetting("sidekey2L", "Side Key 2(Long)",
                              RadioSettingValueList(
                                  SIDEKEY85LONG_LIST,
                                  SIDEKEY85LONG_LIST[_settings.sidekey2L]))
            basic.append(rs)

            rs = RadioSetting("power10w", "Power 10W",
                              RadioSettingValueBoolean(_settings.power10w))
            basic.append(rs)

        if self.MODEL == "RB75":
            rs = RadioSetting("sidekey2", "Side Key 1(Short)",
                              RadioSettingValueList(
                                  SIDEKEY75_LIST,
                                  SIDEKEY75_LIST[_settings.sidekey2]))
            basic.append(rs)

            rs = RadioSetting("sidekey1L", "Side Key 1(Long)",
                              RadioSettingValueList(
                                  SIDEKEY75_LIST,
                                  SIDEKEY75_LIST[_settings.sidekey1L]))
            basic.append(rs)

            rs = RadioSetting("sidekey2S", "Side Key 2(Short)",
                              RadioSettingValueList(
                                  SIDEKEY75_LIST,
                                  SIDEKEY75_LIST[_settings.sidekey2S]))
            basic.append(rs)

            rs = RadioSetting("sidekey2L", "Side Key 2(Long)",
                              RadioSettingValueList(
                                  SIDEKEY75_LIST,
                                  SIDEKEY75_LIST[_settings.sidekey2L]))
            basic.append(rs)

            rs = RadioSetting("power10w", "Low Voltage Stop TX",
                              RadioSettingValueBoolean(_settings.power10w))
            basic.append(rs)

        if self.MODEL == "FRS-B1":
            rs = RadioSetting("settings2.hivoltnotx",
                              "High Voltage Inhibit TX",
                              RadioSettingValueBoolean(_settings2.hivoltnotx))
            basic.append(rs)

            rs = RadioSetting("settings2.lovoltnotx", "Low Voltage Inhibit TX",
                              RadioSettingValueBoolean(_settings2.lovoltnotx))
            basic.append(rs)

            rs = RadioSetting("settings2.vox", "Vox",
                              RadioSettingValueBoolean(_settings2.vox))
            basic.append(rs)

            rs = RadioSetting("settings2.voxnotxonrx", "Rx Disable VOX",
                              RadioSettingValueBoolean(_settings2.voxnotxonrx))
            basic.append(rs)

            rs = RadioSetting("settings2.voxgain", "Vox Gain",
                              RadioSettingValueInteger(
                                  1, 5, _settings2.voxgain))
            basic.append(rs)

        if self.MODEL == "RB19" or self.MODEL == "RB19P" \
                or self.MODEL == "RB619":
            rs = RadioSetting("sidekey2", "Left Navigation Button(Long)",
                              RadioSettingValueList(
                                  SIDEKEY19_LIST,
                                  SIDEKEY19_LIST[_settings.sidekey2]))
            basic.append(rs)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "vox_level":
                        setattr(obj, setting, int(element.value) - 1)
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        if cls.MODEL == "T18":
            match_size = False
            match_model = False

            # testing the file data size
            if len(filedata) == cls._memsize:
                match_size = True

            # testing the model fingerprint
            match_model = model_match(cls, filedata)

            if match_size and match_model:
                return True
            else:
                return False
        else:
            # Radios that have always been post-metadata, so never do
            # old-school detection
            return False


@directory.register
class RT22SRadio(T18Radio):
    """RETEVIS RT22S"""
    VENDOR = "Retevis"
    MODEL = "RT22S"
    ACK_BLOCK = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)]

    _magic = "9COGRAM"
    _fingerprint = "SMP558" + "\x02"
    _upper = 22
    _mem_params = (_upper  # number of channels
                   )
    _frs = True
    _pmr = False


@directory.register
class RB18Radio(T18Radio):
    """RETEVIS RB18"""
    VENDOR = "Retevis"
    MODEL = "RB18"
    BLOCK_SIZE = 0x10
    CMD_EXIT = "E"

    POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)]

    _magic = "PROGRAL"
    _fingerprint = "P3107" + "\xF7"
    _upper = 22
    _mem_params = (_upper  # number of channels
                   )
    _frs = True
    _pmr = False

    _ranges = [
        (0x0000, 0x0660),
    ]
    _memsize = 0x0660

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB18 %
                                     self._mem_params, self._mmap)

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RB618Radio(RB18Radio):
    """RETEVIS RB618"""
    VENDOR = "Retevis"
    MODEL = "RB618"

    _upper = 16
    _mem_params = (_upper  # number of channels
                   )
    _frs = False
    _pmr = True


@directory.register
class RT68Radio(T18Radio):
    """RETEVIS RT68"""
    VENDOR = "Retevis"
    MODEL = "RT68"
    ACK_BLOCK = False
    CMD_EXIT = ""

    POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)]

    _magic = "83OGRAM"
    _fingerprint = "\x06\x00\x00\x00\x00\x00\x00\x00"
    _upper = 16
    _mem_params = (_upper  # number of channels
                   )
    _frs = True
    _pmr = False

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RT668Radio(RT68Radio):
    """RETEVIS RT668"""
    VENDOR = "Retevis"
    MODEL = "RT668"

    _frs = False
    _pmr = True


@directory.register
class RB17Radio(RT68Radio):
    """RETEVIS RB17"""
    VENDOR = "Retevis"
    MODEL = "RB17"

    _magic = "A5OGRAM"
    _fingerprint = "\x53\x00\x00\x00\x00\x00\x00\x00"

    _frs = True
    _pmr = False
    _murs = False


@directory.register
class RB617Radio(RB17Radio):
    """RETEVIS RB617"""
    VENDOR = "Retevis"
    MODEL = "RB617"

    _frs = False
    _pmr = True
    _murs = False


@directory.register
class RB17VRadio(RB17Radio):
    """RETEVIS RB17V"""
    VENDOR = "Retevis"
    MODEL = "RB17V"

    VALID_BANDS = [(136000000, 174000000)]

    _upper = 5

    _frs = False
    _pmr = False
    _murs = True


@directory.register
class RB85Radio(T18Radio):
    """Retevis RB85"""
    VENDOR = "Retevis"
    MODEL = "RB85"
    ACK_BLOCK = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                    chirp_common.PowerLevel("High", watts=10.00)]

    _magic = "H19GRAM"
    _fingerprint = "SMP558" + "\x02"


@directory.register
class RB75Radio(T18Radio):
    """Retevis RB75"""
    VENDOR = "Retevis"
    MODEL = "RB75"
    ACK_BLOCK = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=5.00)]

    _magic = "KVOGRAM"
    _fingerprint = "SMP558" + "\x00"
    _upper = 30
    _mem_params = (_upper  # number of channels
                   )
    _gmrs = True


@directory.register
class FRSB1Radio(T18Radio):
    """BTECH FRS-B1"""
    VENDOR = "BTECH"
    MODEL = "FRS-B1"
    ACK_BLOCK = True

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)]

    _magic = "PROGRAM"
    _fingerprint = "P3107" + "\xF7\x00"
    _upper = 22
    _mem_params = (_upper  # number of channels
                   )
    _frs = True


@directory.register
class RB19Radio(T18Radio):
    """Retevis RB19"""
    VENDOR = "Retevis"
    MODEL = "RB19"
    ACK_BLOCK = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)]

    _magic = "9COGRAM"
    _fingerprint = "SMP558" + "\x02"
    _upper = 22
    _mem_params = (_upper  # number of channels
                   )
    _frs = True


@directory.register
class RB19PRadio(T18Radio):
    """Retevis RB19P"""
    VENDOR = "Retevis"
    MODEL = "RB19P"
    ACK_BLOCK = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=3.00)]

    _magic = "70OGRAM"
    _fingerprint = "SMP558" + "\x02"
    _upper = 30
    _mem_params = (_upper  # number of channels
                   )
    _gmrs = True


@directory.register
class RB619Radio(T18Radio):
    """Retevis RB619"""
    VENDOR = "Retevis"
    MODEL = "RB619"
    ACK_BLOCK = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.499),
                    chirp_common.PowerLevel("High", watts=0.500)]

    _magic = "9COGRAM"
    _fingerprint = "SMP558" + "\x02"
    _upper = 16
    _mem_params = (_upper  # number of channels
                   )
    _pmr = True
