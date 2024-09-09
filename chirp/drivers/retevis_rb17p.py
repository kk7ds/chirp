# Copyright 2022 Jim Unroe <rock.unroe@gmail.com>
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
import struct
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
  char name[10];      // 10-character Alpha Tag
} names[128];
#seekto 0x0810;
struct {
    u8 unknown01:5,
       dualwatch:1,
       workmode:2;
    u8 scanmode:2,
       unknown02:3,
       autokeylock:1,
       unknown03:2;
    u8 unknown04:1,
       beep:1,
       unknown05:1,
       voice:1,
       unknown06:1,
       noaa:1,
       batterysave:2;
    u8 squelchlevel;
    u8 unknown07:5,
       timeouttimer:2,
       unknown08:1;
    u8 alarmtype:1,
       voxdelay:3,
       voxlevel:4;
    u8 unknown10:2,
       backlight:2,
       unknown11:4;
    u8 unknown12[3];
    u8 unknown13:3,
       rogerbeep:1,
       unknown14:1,
       sidekey:3;
} settings;
#seekto 0x1000;
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    lbcd rxtone[2];
    lbcd txtone[2];
    u8 unknown1:4,
       compander:1,
       unknown2:1,
       highpower:1,
       unknown3:1;
    u8 unknown4:3,
       wide:1,
       scan:1,
       unknown5:1,
       bcl:2;
    u8 unknown6[2];
} memory[128];

"""

CMD_ACK = b"\x06"

ALARMTYPE_LIST = ["Local & Remote", "Local"]
BACKLIGHT_LIST = ["5 seconds", "10 seconds", "30 seconds", "Always"]
BATTERYSAVE_LIST = ["Off", "1:4", "1:8"]
SCANMODE_LIST = ["Time Operated", "Carrier Operated", "Search"]
SIDEKEY_LIST = ["Off", "Scan", "VOX", "2nd PTT", "NOAA", "Monitor"]
TIMEOUTTIMER_LIST = ["60 seconds", "120 seconds", "180 seconds"]
VOXDELAY_LIST = ["0.3", "0.5", "1", "1.5", "2", "2.5"]
VOXLEVEL_LIST = ["Off", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
WORKMODE_LIST = ["Frequencies", "Channel Numbers", "Names"]

BCL = ["Off", "Carrier", "QT/DCS"]

GMRS_FREQS1 = [462562500, 462587500, 462612500, 462637500, 462662500,
               462687500, 462712500]
GMRS_FREQS2 = [467562500, 467587500, 467612500, 467637500, 467662500,
               467687500, 467712500]
GMRS_FREQS3 = [462550000, 462575000, 462600000, 462625000, 462650000,
               462675000, 462700000, 462725000]
GMRS_FREQS = GMRS_FREQS1 + GMRS_FREQS2 + GMRS_FREQS3 * 2


def _enter_programming_mode(radio):
    serial = radio.pipe

    try:
        serial.write(b"\x02")
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
        serial.write(b"M" + b"\x02")
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


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
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
    _enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr, block_size in radio._ranges:
        for addr in range(start_addr, end_addr, block_size):
            status.cur = addr + block_size
            radio.status_fn(status)
            _write_block(radio, addr, block_size)


class RB17P_Base(chirp_common.CloneModeRadio):
    """Base class for Retevis RB17P"""
    VENDOR = "Retevis"
    MODEL = "RB17P Base"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x40

    VALID_BANDS = [(400000000, 470000000)]
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PGA588"
    _fingerprint = b"\xFF" * 8
    _upper = 128
    _gmrs = True
    _ranges = [(0x0000, 0x1800, 0x40),
               ]
    _memsize = 0x1800
    _valid_chars = chirp_common.CHARSET_ALPHANUMERIC + \
        "`~!@#$%^&*()-=_+[]\\{}|;':\",./<>?"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.valid_modes = ["NFM", "FM"]  # 12.5 kHz, 25 kHz.
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
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
        rf.has_name = True
        rf.valid_name_length = 10
        rf.valid_characters = self._valid_chars
        rf.memory_bounds = (1, 128)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = chirp_common.TUNING_STEPS

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
        _nam = self._memobj.names[number - 1]

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

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "  # may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        mem.mode = _mem.wide and "FM" or "NFM"

        mem.skip = not _mem.scan and "S" or ""

        txtone = self._decode_tone(_mem.txtone)
        rxtone = self._decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.power = self.POWER_LEVELS[1 - _mem.highpower]

        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueList(BCL, current_index=_mem.bcl))
        mem.extra.append(rs)
        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(_mem.compander))
        mem.extra.append(rs)

        immutable = []

        if self._gmrs:
            if mem.freq in GMRS_FREQS:
                if mem.freq in GMRS_FREQS1:
                    # Non-repeater GMRS channels (limit duplex)
                    mem.duplex == ''
                    mem.offset = 0
                    immutable = ["duplex", "offset"]
                elif mem.freq in GMRS_FREQS2:
                    # Non-repeater FRS channels (limit duplex, power)
                    mem.duplex == ''
                    mem.offset = 0
                    mem.mode = "NFM"
                    mem.power = self.POWER_LEVELS[1]
                    immutable = ["duplex", "offset", "mode", "power"]
                elif mem.freq in GMRS_FREQS3:
                    # GMRS repeater channels, always either simplex or +5 MHz
                    if mem.duplex != '+':
                        mem.duplex = ''
                        mem.offset = 0
                    else:
                        mem.offset = 5000000
            else:
                # Not a GMRS channel, so restrict duplex since it will be
                # forced to off.
                mem.duplex = 'off'
                mem.offset = 0
                immutable = ["duplex", "offset"]

        mem.immutable = immutable

        return mem

    def check_set_memory_immutable_policy(self, existing, new):
        existing.immutable = []
        super().check_set_memory_immutable_policy(existing, new)

    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b"\xFF" * (_mem.size() // 8))
            _nam.set_raw(b"\xFF" * (_nam.size() // 8))

            return

        _mem.set_raw(b"\x00" * (_mem.size() // 8))

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)

        if self.MODEL != "T18" and self.MODEL != "RB18":
            _mem.highpower = mem.power == self.POWER_LEVELS[0]

        _mem.wide = mem.mode == "FM"
        _mem.scan = mem.skip == ""

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), int(setting.value))

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        # Menu 01 - Work Mode
        rs = RadioSetting("workmode", "Work Mode",
                          RadioSettingValueList(
                              WORKMODE_LIST,
                              current_index=(_settings.workmode) - 1))
        basic.append(rs)

        # Menu 04 - Squelch
        rs = RadioSetting("squelchlevel", "Squelch level",
                          RadioSettingValueInteger(
                              0, 9, _settings.squelchlevel))
        basic.append(rs)

        # Menu 05 - Battery Save
        rs = RadioSetting("batterysave", "Battery Save",
                          RadioSettingValueList(
                              BATTERYSAVE_LIST,
                              current_index=_settings.batterysave))
        basic.append(rs)

        # Menu 06 - Dual Watch
        rs = RadioSetting("dualwatch", "Dual Watch",
                          RadioSettingValueBoolean(_settings.dualwatch))
        basic.append(rs)

        # Menu 07 - Backlight Duration[s]
        rs = RadioSetting("backlight", "Backlight Duration",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=_settings.backlight))
        basic.append(rs)

        # Menu 09 - Beep Tone
        rs = RadioSetting("beep", "Key Beep",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        # Menu 10 - Voice Annunciation
        rs = RadioSetting("voice", "Voice prompts",
                          RadioSettingValueBoolean(_settings.voice))
        basic.append(rs)

        # Menu 11 - Time out Timer[s]
        rs = RadioSetting("timeouttimer", "Timeout timer",
                          RadioSettingValueList(
                              TIMEOUTTIMER_LIST,
                              current_index=(_settings.timeouttimer) - 1))
        basic.append(rs)

        # Menu 12 - Roger Tone
        rs = RadioSetting("rogerbeep", "Roger beep",
                          RadioSettingValueBoolean(_settings.rogerbeep))
        basic.append(rs)

        # Menu 13 - SideKey
        rs = RadioSetting("sidekey", "Side Key",
                          RadioSettingValueList(
                              SIDEKEY_LIST,
                              current_index=_settings.sidekey))
        basic.append(rs)

        # Menu 14 - Auto Key Lock
        rs = RadioSetting("autokeylock", "Auto Key Lock",
                          RadioSettingValueBoolean(_settings.autokeylock))
        basic.append(rs)

        # Menu 17 - NOAA
        rs = RadioSetting("noaa", "NOAA",
                          RadioSettingValueBoolean(_settings.noaa))
        basic.append(rs)

        # Scan Mode
        rs = RadioSetting("scanmode", "Scan mode",
                          RadioSettingValueList(
                              SCANMODE_LIST,
                              current_index=_settings.scanmode))
        basic.append(rs)

        # Alarm Type
        rs = RadioSetting("alarmtype", "Alarm Type",
                          RadioSettingValueList(
                              ALARMTYPE_LIST,
                              current_index=_settings.alarmtype))
        basic.append(rs)

        # VOX Level
        rs = RadioSetting("voxlevel", "Vox level",
                          RadioSettingValueList(
                              VOXLEVEL_LIST,
                              current_index=_settings.voxlevel))
        basic.append(rs)

        # VOX Delay
        rs = RadioSetting("voxdelay", "Vox delay",
                          RadioSettingValueList(
                              VOXDELAY_LIST,
                              current_index=_settings.voxdelay))
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
                    elif setting == "timeouttimer":
                        setattr(obj, setting, int(element.value) + 1)
                    elif setting == "workmode":
                        setattr(obj, setting, int(element.value) + 1)
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # Radios that have always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RB17PRadio(RB17P_Base):
    """Retevis RB17P"""
    VENDOR = "Retevis"
    MODEL = "RB17P"
    _gmrs = True
    _ranges = [(0x0010, 0x0510, 0x40),
               (0x0810, 0x0830, 0x30),
               (0x1000, 0x1800, 0x40)
               ]

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        _msg_duplex = 'Duplex must be "off" for this frequency'
        _msg_offset = 'Only simplex or +5 MHz offset allowed on GMRS'

        if mem.freq not in GMRS_FREQS:
            if mem.duplex != "off":
                msgs.append(chirp_common.ValidationWarning(_msg_duplex))
        elif mem.duplex and mem.offset != 5000000:
            msgs.append(chirp_common.ValidationWarning(_msg_offset))

        return msgs
