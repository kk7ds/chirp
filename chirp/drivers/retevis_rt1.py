# Copyright 2016 Jim Unroe <rock.unroe@gmail.com>
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
import logging

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    InvalidValueError, RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  lbcd rxtone[2];
  lbcd txtone[2];
  u8 bcl:1,         // Busy Lock
     epilogue:1,    // Epilogue (STE)
     scramble:1,    // Scramble
     compander:1,   // Compander
     skip:1,        // Scan Add
     wide:1,        // Bandwidth
     unknown1:1,
     highpower:1;   // Power Level
  u8 unknown2[3];
} memory[16];

#seekto 0x0120;
struct {
  u8 hivoltnotx:1,  // TX Inhibit when voltage too high
     lovoltnotx:1,  // TX Inhibit when voltage too low
     unknown1:1,
     alarm:1,       // Incept Alarm
     scan:1,        // Scan
     tone:1,        // Tone
     voice:2;       // Voice
  u8 unknown2:1,
     ssave:3,       // Super Battery Save
     unknown3:1,
     save:3;        // Battery Save
  u8 squelch;       // Squelch
  u8 tot;           // Time Out Timer
  u8 voxi:1,        // VOX Inhibit on Receive
     voxd:2,        // VOX Delay
     voxc:1,        // VOX Control
     voxg:4;        // VOX Gain
  u8 unknown4:4,
     scanspeed:4;   // Scan Speed
  u8 unknown5:3,
     scandelay:5;   // Scan Delay
  u8 unknown6:3,
     prioritych:5;  // Priority Channel
  u8 k1shortp;      // Key 1 Short Press
  u8 k2shortp;      // Key 2 Short Press
  u8 k1longp;       // Key 1 Long Press
  u8 k2longp;       // Key 2 Long Press
  u8 lpt;           // Long Press Time
} settings;

#seekto 0x0170;
struct {
  char fp[8];
} fingerprint;
"""

CMD_ACK = "\x06"

RT1_POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=5.00),
                    chirp_common.PowerLevel("High", watts=9.00)]

RT1_DTCS = sorted(chirp_common.DTCS_CODES + [645])

LIST_LPT = ["0.5", "1.0", "1.5", "2.0", "2.5"]
LIST_SHORT_PRESS = ["Off", "Monitor On/Off", "Power High/Low", "Alarm", "Volt"]
LIST_LONG_PRESS = ["Off", "Monitor On/Off", "Monitor(momentary)",
                   "Power High/Low", "Alarm", "Volt", "TX 1750 Hz"]
LIST_VOXDELAY = ["0.5", "1.0", "2.0", "3.0"]
LIST_VOICE = ["Off", "English", "Chinese"]
LIST_TIMEOUTTIMER = ["Off"] + ["%s" % x for x in range(30, 330, 30)]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SSAVE = ["Off"] + ["%s" % x for x in range(1, 7)]
LIST_PRIORITYCH = ["Off"] + ["%s" % x for x in range(1, 17)]
LIST_SCANSPEED = ["%s" % x for x in range(100, 550, 50)]
LIST_SCANDELAY = ["%s" % x for x in range(3, 31)]

SETTING_LISTS = {
    "lpt": LIST_LPT,
    "k1shortp": LIST_SHORT_PRESS,
    "k1longp": LIST_LONG_PRESS,
    "k2shortp": LIST_SHORT_PRESS,
    "k2longp": LIST_LONG_PRESS,
    "voxd": LIST_VOXDELAY,
    "voice": LIST_VOICE,
    "tot": LIST_TIMEOUTTIMER,
    "save": LIST_SAVE,
    "ssave": LIST_SSAVE,
    "prioritych": LIST_PRIORITYCH,
    "scanspeed": LIST_SCANSPEED,
    "scandelay": LIST_SCANDELAY,
    }

# Retevis RT1 fingerprints
RT1_VHF_fp = "PXT8K" + "\xF0\x00\x00"   # RT1 VHF model
RT1_UHF_fp = "PXT8K" + "\xF3\x00\x00"   # RT1 UHF model

MODELS = [RT1_VHF_fp, RT1_UHF_fp]


def _model_from_data(data):
    return data[0x0170:0x0178]


def _model_from_image(radio):
    return _model_from_data(radio.get_mmap())


def _get_radio_model(radio):
    block = _rt1_read_block(radio, 0x0170, 0x10)
    version = block[0:8]
    return version


def _rt1_enter_programming_mode(radio):
    serial = radio.pipe

    magic = ["PROGRAMa", "PROGRAMb"]
    for i in range(0, 2):

        try:
            LOG.debug("sending " + magic[i])
            serial.write(magic[i])
            ack = serial.read(1)
        except:
            _rt1_exit_programming_mode(radio)
            raise errors.RadioError("Error communicating with radio")

        if not ack:
            _rt1_exit_programming_mode(radio)
            raise errors.RadioError("No response from radio")
        elif ack != CMD_ACK:
            LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
            _rt1_exit_programming_mode(radio)
            raise errors.RadioError("Radio refused to enter programming mode")

    try:
        LOG.debug("sending " + util.hexprint("\x02"))
        serial.write("\x02")
        ident = serial.read(16)
    except:
        _rt1_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if not ident.startswith("PXT8K"):
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ident))
        _rt1_exit_programming_mode(radio)
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        LOG.debug("sending " + util.hexprint("MXT8KCUMHS1X7BN/"))
        serial.write("MXT8KCUMHS1X7BN/")
        ack = serial.read(1)
    except:
        _rt1_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != "\xB2":
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
        _rt1_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        LOG.debug("sending " + util.hexprint(CMD_ACK))
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _rt1_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
        _rt1_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")

    # DEBUG
    LOG.info("Positive ident, this is a %s %s" % (radio.VENDOR, radio.MODEL))


def _rt1_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write("E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _rt1_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)

        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            _rt1_exit_programming_mode(radio)
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _rt1_exit_programming_mode(radio)
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        _rt1_exit_programming_mode(radio)
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _rt1_write_block(radio, block_addr, block_size):
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
        _rt1_exit_programming_mode(radio)
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _rt1_enter_programming_mode(radio)

    data = ""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio._block_size):
        status.cur = addr + radio._block_size
        radio.status_fn(status)

        block = _rt1_read_block(radio, addr, radio._block_size)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _rt1_exit_programming_mode(radio)

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _rt1_enter_programming_mode(radio)

    image_model = _model_from_image(radio)
    LOG.info("Image Version is %s" % repr(image_model))

    radio_model = _get_radio_model(radio)
    LOG.info("Radio Version is %s" % repr(radio_model))

    bands = ["VHF", "UHF"]
    image_band = radio_band = "unknown"
    for i in range(0,2):
        if image_model == MODELS[i]:
            image_band = bands[i]
        if radio_model == MODELS[i]:
            radio_band = bands[i]

    if image_model != radio_model:
        _rt1_exit_programming_mode(radio)
        msg = ("The upload was stopped because the band supported by "
               "the image (%s) does not match the band supported by "
               "the radio (%s).")
        raise errors.RadioError(msg % (image_band, radio_band))

    status.cur = 0
    status.max = 0x0190

    for start_addr, end_addr, block_size in radio._ranges:
        for addr in range(start_addr, end_addr, block_size):
            status.cur = addr + block_size
            radio.status_fn(status)
            _rt1_write_block(radio, addr, block_size)

    _rt1_exit_programming_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x0170:0x0176]

    return rid.startswith("PXT8K")


@directory.register
class RT1Radio(chirp_common.CloneModeRadio):
    """Retevis RT1"""
    VENDOR = "Retevis"
    MODEL = "RT1"
    BAUD_RATE = 2400

    _ranges = [
               (0x0000, 0x0190, 0x10),
              ]
    _memsize = 0x0400
    _block_size = 0x10
    _vhf_range = (134000000, 175000000)
    _uhf_range = (400000000, 521000000)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = RT1_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]  # 12.5 KHz, 25 kHz.
        rf.memory_bounds = (1, 16)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        if self._mmap is None:
            rf.valid_bands = [self._vhf_range, self._uhf_range]
        elif self._my_band() == RT1_VHF_fp:
            rf.valid_bands = [self._vhf_range]
        elif self._my_band() == RT1_UHF_fp:
            rf.valid_bands = [self._uhf_range]

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

    def decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        if val.get_raw() == "\xFF\xFF":
            return '', None, None

        val = int(val)
        if val >= 12000:
            a = val - 12000
            return 'DTCS', a, 'R'
        elif val >= 8000:
            a = val - 8000
            return 'DTCS', a, 'N'
        else:
            a = val / 10.0
            return 'Tone', a, None

    def encode_tone(self, memval, mode, value, pol):
        """Parse the tone data to encode from UI to mem"""
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

    def _my_band(self):
        model_tag = _model_from_image(self)
        return model_tag

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

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        rxtone = txtone = None
        txtone = self.decode_tone(_mem.txtone)
        rxtone = self.decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.power = RT1_POWER_LEVELS[_mem.highpower]

        if _mem.skip:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(not _mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("epilogue", "Epilogue(STE)",
                          RadioSettingValueBoolean(not _mem.epilogue))
        mem.extra.append(rs)

        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(not _mem.compander))
        mem.extra.append(rs)

        rs = RadioSetting("scramble", "Scramble",
                          RadioSettingValueBoolean(not _mem.scramble))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
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

        _mem.wide = mem.mode == "FM"

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.txtone, txmode, txtone, txpol)
        self.encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        _mem.highpower = mem.power == RT1_POWER_LEVELS[1]

        _mem.skip = mem.skip == "S"

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), not int(setting.value))

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        rs = RadioSetting("lpt", "Long Press Time[s]",
                          RadioSettingValueList(
                              LIST_LPT,
                              LIST_LPT[_settings.lpt]))
        basic.append(rs)

        if _settings.k1shortp > 4:
            val = 1
        else:
            val = _settings.k1shortp
        rs = RadioSetting("k1shortp", "Key 1 Short Press",
                          RadioSettingValueList(
                              LIST_SHORT_PRESS,
                              LIST_SHORT_PRESS[val]))
        basic.append(rs)

        if _settings.k1longp > 6:
            val = 3
        else:
            val = _settings.k1longp
        rs = RadioSetting("k1longp", "Key 1 Long Press",
                          RadioSettingValueList(
                              LIST_LONG_PRESS,
                              LIST_LONG_PRESS[val]))
        basic.append(rs)

        if _settings.k2shortp > 4:
            val = 4
        else:
            val = _settings.k2shortp
        rs = RadioSetting("k2shortp", "Key 2 Short Press",
                          RadioSettingValueList(
                              LIST_SHORT_PRESS,
                              LIST_SHORT_PRESS[val]))
        basic.append(rs)

        if _settings.k2longp > 6:
            val = 4
        else:
            val = _settings.k2longp
        rs = RadioSetting("k2longp", "Key 2 Long Press",
                          RadioSettingValueList(
                              LIST_LONG_PRESS,
                              LIST_LONG_PRESS[val]))
        basic.append(rs)

        rs = RadioSetting("voxc", "VOX Control",
                          RadioSettingValueBoolean(not _settings.voxc))
        basic.append(rs)

        if _settings.voxg > 8:
            val = 4
        else:
            val = _settings.voxg + 1
        rs = RadioSetting("voxg", "VOX Gain",
                          RadioSettingValueInteger(1, 9, val))
        basic.append(rs)

        rs = RadioSetting("voxd", "VOX Delay Time",
                          RadioSettingValueList(
                              LIST_VOXDELAY,
                              LIST_VOXDELAY[_settings.voxd]))
        basic.append(rs)

        rs = RadioSetting("voxi", "VOX Inhibit on Receive",
                          RadioSettingValueBoolean(not _settings.voxi))
        basic.append(rs)

        if _settings.squelch > 8:
            val = 4
        else:
            val = _settings.squelch
        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, val))
        basic.append(rs)

        if _settings.voice == 3:
            val = 1
        else:
            val = _settings.voice
        rs = RadioSetting("voice", "Voice Prompts",
                          RadioSettingValueList(
                              LIST_VOICE,
                              LIST_VOICE[val]))
        basic.append(rs)

        rs = RadioSetting("tone", "Tone",
                          RadioSettingValueBoolean(_settings.tone))
        basic.append(rs)

        rs = RadioSetting("lovoltnotx", "TX Inhibit (when battery < 6 volts)",
                          RadioSettingValueBoolean(_settings.lovoltnotx))
        basic.append(rs)

        rs = RadioSetting("hivoltnotx", "TX Inhibit (when battery > 9 volts)",
                          RadioSettingValueBoolean(_settings.hivoltnotx))
        basic.append(rs)

        if _settings.tot > 10:
            val = 6
        else:
            val = _settings.tot
        rs = RadioSetting("tot", "Time-out Timer[s]",
                          RadioSettingValueList(
                              LIST_TIMEOUTTIMER,
                              LIST_TIMEOUTTIMER[val]))
        basic.append(rs)

        if _settings.save < 3:
            val = 0
        else:
            val = _settings.save - 3
        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueList(
                              LIST_SAVE,
                              LIST_SAVE[val]))
        basic.append(rs)

        rs = RadioSetting("ssave", "Super Battery Saver[s]",
                          RadioSettingValueList(
                              LIST_SSAVE,
                              LIST_SSAVE[_settings.ssave]))
        basic.append(rs)

        rs = RadioSetting("alarm", "Incept Alarm",
                          RadioSettingValueBoolean(_settings.alarm))
        basic.append(rs)

        rs = RadioSetting("scan", "Scan Function",
                          RadioSettingValueBoolean(_settings.scan))
        basic.append(rs)

        if _settings.prioritych > 15:
            val = 0
        else:
            val = _settings.prioritych + 1
        rs = RadioSetting("prioritych", "Priority Channel",
                          RadioSettingValueList(
                              LIST_PRIORITYCH,
                              LIST_PRIORITYCH[val]))
        basic.append(rs)

        if _settings.scanspeed > 8:
            val = 4
        else:
            val = _settings.scanspeed
        rs = RadioSetting("scanspeed", "Scan Speed[ms]",
                          RadioSettingValueList(
                          LIST_SCANSPEED,
                          LIST_SCANSPEED[val]))
        basic.append(rs)

        if _settings.scandelay > 27:
            val = 12
        else:
            val = _settings.scandelay
        rs = RadioSetting("scandelay", "Scan Droupout Delay Time[s]",
                          RadioSettingValueList(
                              LIST_SCANDELAY,
                              LIST_SCANDELAY[val]))
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

                    if setting == "voxc":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "voxg":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "voxi":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "voice":
                        if int(element.value) == 2:
                            setattr(obj, setting, int(element.value) + 1)
                        else:
                            setattr(obj, setting, int(element.value))
                    elif setting == "save":
                        setattr(obj, setting, int(element.value) + 3)
                    elif setting == "prioritych":
                        if int(element.value) == 0:
                            setattr(obj, setting, int(element.value) + 31)
                        else:
                            setattr(obj, setting, int(element.value) - 1)
                    elif element.value.get_mutable():
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
        if len(filedata) in [0x0400, ]:
            match_size = True
        
        # testing the model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False
