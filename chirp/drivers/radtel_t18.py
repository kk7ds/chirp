# Copyright 2017 Jim Unroe <rock.unroe@gmail.com>
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
} memory[16];
#seekto 0x03C0;
struct {
    u8 unknown1:1,
       scanmode:1,
       unknown2:2,
       voiceprompt:2,
       batterysaver:1,
       beep:1;
    u8 squelchlevel;
    u8 unused2;
    u8 timeouttimer;
    u8 voxlevel;
    u8 unknown3;
    u8 unused;
    u8 voxdelay;
} settings;
"""

CMD_ACK = "\x06"
BLOCK_SIZE = 0x08

VOICE_LIST = ["Off", "Chinese", "English"]
TIMEOUTTIMER_LIST = ["Off", "30 seconds", "60 seconds", "90 seconds",
                     "120 seconds", "150 seconds", "180 seconds",
                     "210 seconds", "240 seconds", "270 seconds",
                     "300 seconds"]
SCANMODE_LIST = ["Carrier", "Time"]
VOXLEVEL_LIST = ["Off", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
VOXDELAY_LIST = ["0.5 seconds", "1.0 seconds", "1.5 seconds",
                 "2.0 seconds", "2.5 seconds", "3.0 seconds"]

SETTING_LISTS = {
    "voice": VOICE_LIST,
    "timeouttimer": TIMEOUTTIMER_LIST,
    "scanmode": SCANMODE_LIST,
    "voxlevel": VOXLEVEL_LIST,
    "voxdelay": VOXDELAY_LIST
}


def _t18_enter_programming_mode(radio):
    serial = radio.pipe

    try:
        serial.write("\x02")
        time.sleep(0.1)
        serial.write("1ROGRAM")
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

    if not ident.startswith("SMP558"):
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write("\x05")
        response = serial.read(6)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not response == ("\xFF" * 6):
        LOG.debug(util.hexprint(response))
        raise errors.RadioError("Radio returned unexpected response")

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
        serial.write("b")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _t18_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, BLOCK_SIZE)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + BLOCK_SIZE)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _t18_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, BLOCK_SIZE)
    data = radio.get_mmap()[block_addr:block_addr + 8]

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

    for addr in range(0, radio._memsize, BLOCK_SIZE):
        status.cur = addr + BLOCK_SIZE
        radio.status_fn(status)

        block = _t18_read_block(radio, addr, BLOCK_SIZE)
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
        for addr in range(start_addr, end_addr, BLOCK_SIZE):
            status.cur = addr + BLOCK_SIZE
            radio.status_fn(status)
            _t18_write_block(radio, addr, BLOCK_SIZE)

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
        rf.memory_bounds = (1, 16)
        rf.valid_bands = [(400000000, 470000000)]

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

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

        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueBoolean(not _mem.bcl))
        mem.extra.append(rs)
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

        _mem.narrow = 'N' in mem.mode
        _mem.skip = mem.skip == "S"

        for setting in mem.extra:
            # NOTE: Only three settings right now, all are inverted
            setattr(_mem, setting.get_name(), not int(setting.value))

    def get_settings(self):
        _settings = self._memobj.settings
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

        rs = RadioSetting("scanmode", "Scan mode",
                          RadioSettingValueList(
                              SCANMODE_LIST,
                              SCANMODE_LIST[_settings.scanmode]))
        basic.append(rs)

        rs = RadioSetting("voiceprompt", "Voice prompt",
                          RadioSettingValueList(
                              VOICE_LIST,
                              VOICE_LIST[_settings.voiceprompt]))
        basic.append(rs)

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

        rs = RadioSetting("batterysaver", "Battery saver",
                          RadioSettingValueBoolean(_settings.batterysaver))
        basic.append(rs)

        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
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
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise


    @classmethod
    def match_model(cls, filedata, filename):
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
