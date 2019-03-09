# Copyright 2013 Jens Jensen AF5MI <kd4tjx@yahoo.com>
# Based on work by Jim Unroe, Dan Smith, et al.
# Special thanks to Mats SM0BTP for equipment donation.
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

import struct
import time
import os
import logging

from chirp.drivers import uv5r
from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, InvalidValueError, RadioSettings
from textwrap import dedent

LOG = logging.getLogger(__name__)


BJUV55_MODEL = "\x50\xBB\xDD\x55\x63\x98\x4D"

COLOR_LIST = ["Off", "Blue", "Red", "Pink"]

STEPS = list(uv5r.STEPS)
STEPS.remove(2.5)
STEP_LIST = [str(x) for x in STEPS]

MEM_FORMAT = """
#seekto 0x0008;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:3,
     isuhf:1,
     scode:4;
  u8 unknown1:7,
     txtoneicon:1;
  u8 mailicon:3,
     unknown2:4,
     lowpower:1;
  u8 unknown3:1,
     wide:1,
     unknown4:2,
     bcl:1,
     scan:1,
     pttid:2;
} memory[128];

#seekto 0x0B08;
struct {
  u8 code[5];
  u8 unused[11];
} pttid[15];

#seekto 0x0C88;
struct {
  u8 inspection[5];
  u8 monitor[5];
  u8 alarmcode[5];
  u8 unknown1;
  u8 stun[5];
  u8 kill[5];
  u8 revive[5];
  u8 unknown2;
  u8 master_control_id[5];
  u8 vice_control_id[5];
  u8 code[5];
  u8 unused1:6,
     aniid:2;
  u8 unknown[2];
  u8 dtmfon;
  u8 dtmfoff;
} ani;

#seekto 0x0E28;
struct {
  u8 squelch;
  u8 step;
  u8 tdrab;
  u8 tdr;
  u8 vox;
  u8 timeout;
  u8 unk2[6];
  u8 abr;
  u8 beep;
  u8 ani;
  u8 unknown3[2];
  u8 voice;
  u8 ring_time;
  u8 dtmfst;
  u8 unknown5;
  u8 unknown12:6,
     screv:2;
  u8 pttid;
  u8 pttlt;
  u8 mdfa;
  u8 mdfb;
  u8 bcl;
  u8 autolk;
  u8 sftd;
  u8 unknown6[3];
  u8 wtled;
  u8 rxled;
  u8 txled;
  u8 unknown7[5];
  u8 save;
  u8 unknown8;
  u8 displayab:1,
     unknown1:2,
     fmradio:1,
     alarm:1,
     unknown2:1,
     reset:1,
     menu:1;
  u8 vfomrlock;
  u8 workmode;
  u8 keylock;
  u8 workmode_channel;
  u8 password[6];
  u8 unknown10[11];
} settings;

#seekto 0x0E7E;
struct {
  u8 mrcha;
  u8 mrchb;
} wmchannel;

#seekto 0x0F10;
struct {
  u8 freq[8];
  u8 unknown1;
  u8 offset[4];
  u8 unknown2;
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:7,
     band:1;
  u8 unknown3;
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown4;
  u8 unused3:1
     step:3,
     unused4:4;
  u8 txpower:1,
     widenarr:1,
     unknown5:6;
} vfoa;

#seekto 0x0F30;
struct {
  u8 freq[8];
  u8 unknown1;
  u8 offset[4];
  u8 unknown2;
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:7,
     band:1;
  u8 unknown3;
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown4;
  u8 unused3:1
     step:3,
     unused4:4;
  u8 txpower:1,
     widenarr:1,
     unknown5:6;
} vfob;

#seekto 0x0F57;
u8 fm_preset;

#seekto 0x1008;
struct {
  char name[6];
  u8 unknown2[10];
} names[128];

#seekto 0x%04X;
struct {
  char line1[7];
  char line2[7];
} poweron_msg;

#seekto 0x1838;
struct {
  char line1[7];
  char line2[7];
} firmware_msg;

#seekto 0x1849;
u8 power_vhf_hi[14]; // 136-174 MHz, 3 MHz divisions
u8 power_uhf_hi[14]; // 400-470 MHz, 5 MHz divisions
#seekto 0x1889;
u8 power_vhf_lo[14];
u8 power_uhf_lo[14];

struct limit {
  u8 enable;
  bbcd lower[2];
  bbcd upper[2];
};

#seekto 0x1908;
struct {
    struct limit vhf;
    u8 unk11[11];
    struct limit uhf;
} limits;

"""


@directory.register
class BaojieBJUV55Radio(uv5r.BaofengUV5R):
    VENDOR = "Baojie"
    MODEL = "BJ-UV55"
    _basetype = ["BJ55"]
    _idents = [BJUV55_MODEL]
    _mem_params = (0x1928  # poweron_msg offset
                   )
    _fw_ver_file_start = 0x1938
    _fw_ver_file_stop = 0x193E

    def get_features(self):
        rf = super(BaojieBJUV55Radio, self).get_features()
        rf.valid_name_length = 6
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params, self._mmap)

    def set_memory(self, mem):
        super(BaojieBJUV55Radio, self).set_memory(mem)
        _mem = self._memobj.memory[mem.number]
        if (mem.freq - mem.offset) > (400 * 1000000):
            _mem.isuhf = True
        else:
            _mem.isuhf = False
        if mem.tmode in ["Tone", "TSQL"]:
            _mem.txtoneicon = True
        else:
            _mem.txtoneicon = False

    def _get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        group = RadioSettings(basic, advanced)

        rs = RadioSetting("squelch", "Carrier Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueInteger(0, 4, _settings.save))
        basic.append(rs)

        rs = RadioSetting("abr", "Backlight",
                          RadioSettingValueBoolean(_settings.abr))
        basic.append(rs)

        rs = RadioSetting("tdr", "Dual Watch (BDR)",
                          RadioSettingValueBoolean(_settings.tdr))
        advanced.append(rs)

        rs = RadioSetting("tdrab", "Dual Watch TX Priority",
                          RadioSettingValueList(
                              uv5r.TDRAB_LIST,
                              uv5r.TDRAB_LIST[_settings.tdrab]))
        advanced.append(rs)

        rs = RadioSetting("alarm", "Alarm",
                          RadioSettingValueBoolean(_settings.alarm))
        advanced.append(rs)

        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting("timeout", "Timeout Timer",
                          RadioSettingValueList(
                              uv5r.TIMEOUT_LIST,
                              uv5r.TIMEOUT_LIST[_settings.timeout]))
        basic.append(rs)

        rs = RadioSetting("screv", "Scan Resume",
                          RadioSettingValueList(
                              uv5r.RESUME_LIST,
                              uv5r.RESUME_LIST[_settings.screv]))
        advanced.append(rs)

        rs = RadioSetting("mdfa", "Display Mode (A)",
                          RadioSettingValueList(
                              uv5r.MODE_LIST, uv5r.MODE_LIST[_settings.mdfa]))
        basic.append(rs)

        rs = RadioSetting("mdfb", "Display Mode (B)",
                          RadioSettingValueList(
                              uv5r.MODE_LIST, uv5r.MODE_LIST[_settings.mdfb]))
        basic.append(rs)

        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueBoolean(_settings.bcl))
        advanced.append(rs)

        rs = RadioSetting("autolk", "Automatic Key Lock",
                          RadioSettingValueBoolean(_settings.autolk))
        advanced.append(rs)

        rs = RadioSetting("fmradio", "Broadcast FM Radio",
                          RadioSettingValueBoolean(_settings.fmradio))
        advanced.append(rs)

        rs = RadioSetting("wtled", "Standby LED Color",
                          RadioSettingValueList(
                              COLOR_LIST, COLOR_LIST[_settings.wtled]))
        basic.append(rs)

        rs = RadioSetting("rxled", "RX LED Color",
                          RadioSettingValueList(
                              COLOR_LIST, COLOR_LIST[_settings.rxled]))
        basic.append(rs)

        rs = RadioSetting("txled", "TX LED Color",
                          RadioSettingValueList(
                              COLOR_LIST, COLOR_LIST[_settings.txled]))
        basic.append(rs)

        rs = RadioSetting("reset", "RESET Menu",
                          RadioSettingValueBoolean(_settings.reset))
        advanced.append(rs)

        rs = RadioSetting("menu", "All Menus",
                          RadioSettingValueBoolean(_settings.menu))
        advanced.append(rs)

        if len(self._mmap.get_packed()) == 0x1808:
            # Old image, without aux block
            return group

        other = RadioSettingGroup("other", "Other Settings")
        group.append(other)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        _msg = self._memobj.poweron_msg
        rs = RadioSetting("poweron_msg.line1", "Power-On Message 1",
                          RadioSettingValueString(0, 7, _filter(_msg.line1)))
        other.append(rs)
        rs = RadioSetting("poweron_msg.line2", "Power-On Message 2",
                          RadioSettingValueString(0, 7, _filter(_msg.line2)))
        other.append(rs)

        limit = "limits"
        vhf_limit = getattr(self._memobj, limit).vhf
        rs = RadioSetting("%s.vhf.lower" % limit, "VHF Lower Limit (MHz)",
                          RadioSettingValueInteger(
                              1, 1000, vhf_limit.lower))
        other.append(rs)

        rs = RadioSetting("%s.vhf.upper" % limit, "VHF Upper Limit (MHz)",
                          RadioSettingValueInteger(
                              1, 1000, vhf_limit.upper))
        other.append(rs)

        rs = RadioSetting("%s.vhf.enable" % limit, "VHF TX Enabled",
                          RadioSettingValueBoolean(vhf_limit.enable))
        other.append(rs)

        uhf_limit = getattr(self._memobj, limit).uhf
        rs = RadioSetting("%s.uhf.lower" % limit, "UHF Lower Limit (MHz)",
                          RadioSettingValueInteger(
                              1, 1000, uhf_limit.lower))
        other.append(rs)
        rs = RadioSetting("%s.uhf.upper" % limit, "UHF Upper Limit (MHz)",
                          RadioSettingValueInteger(
                              1, 1000, uhf_limit.upper))
        other.append(rs)
        rs = RadioSetting("%s.uhf.enable" % limit, "UHF TX Enabled",
                          RadioSettingValueBoolean(uhf_limit.enable))
        other.append(rs)

        workmode = RadioSettingGroup("workmode", "Work Mode Settings")
        group.append(workmode)

        options = ["A", "B"]
        rs = RadioSetting("displayab", "Display Selected",
                          RadioSettingValueList(
                              options, options[_settings.displayab]))
        workmode.append(rs)

        options = ["Frequency", "Channel"]
        rs = RadioSetting("workmode", "VFO/MR Mode",
                          RadioSettingValueList(
                              options, options[_settings.workmode]))
        workmode.append(rs)

        rs = RadioSetting("keylock", "Keypad Lock",
                          RadioSettingValueBoolean(_settings.keylock))
        workmode.append(rs)

        _mrcna = self._memobj.wmchannel.mrcha
        rs = RadioSetting("wmchannel.mrcha", "MR A Channel",
                          RadioSettingValueInteger(0, 127, _mrcna))
        workmode.append(rs)

        _mrcnb = self._memobj.wmchannel.mrchb
        rs = RadioSetting("wmchannel.mrchb", "MR B Channel",
                          RadioSettingValueInteger(0, 127, _mrcnb))
        workmode.append(rs)

        def convert_bytes_to_freq(bytes):
            real_freq = 0
            for byte in bytes:
                real_freq = (real_freq * 10) + byte
            return chirp_common.format_freq(real_freq * 10)

        def my_validate(value):
            value = chirp_common.parse_freq(value)
            if 17400000 <= value and value < 40000000:
                raise InvalidValueError("Can't be between 174.00000-400.00000")
            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            obj.band = value >= 40000000
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(
                0, 10, convert_bytes_to_freq(self._memobj.vfoa.freq))
        val1a.set_validate_callback(my_validate)
        rs = RadioSetting("vfoa.freq", "VFO A Frequency", val1a)
        rs.set_apply_callback(apply_freq, self._memobj.vfoa)
        workmode.append(rs)

        val1b = RadioSettingValueString(
                0, 10, convert_bytes_to_freq(self._memobj.vfob.freq))
        val1b.set_validate_callback(my_validate)
        rs = RadioSetting("vfob.freq", "VFO B Frequency", val1b)
        rs.set_apply_callback(apply_freq, self._memobj.vfob)
        workmode.append(rs)

        options = ["Off", "+", "-"]
        rs = RadioSetting("vfoa.sftd", "VFO A Shift",
                          RadioSettingValueList(
                              options, options[self._memobj.vfoa.sftd]))
        workmode.append(rs)

        rs = RadioSetting("vfob.sftd", "VFO B Shift",
                          RadioSettingValueList(
                              options, options[self._memobj.vfob.sftd]))
        workmode.append(rs)

        def convert_bytes_to_offset(bytes):
            real_offset = 0
            for byte in bytes:
                real_offset = (real_offset * 10) + byte
            return chirp_common.format_freq(real_offset * 10000)

        def apply_offset(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10000
            for i in range(3, -1, -1):
                obj.offset[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(
                0, 10, convert_bytes_to_offset(self._memobj.vfoa.offset))
        rs = RadioSetting("vfoa.offset", "VFO A Offset (0.00-69.95)", val1a)
        rs.set_apply_callback(apply_offset, self._memobj.vfoa)
        workmode.append(rs)

        val1b = RadioSettingValueString(
                0, 10, convert_bytes_to_offset(self._memobj.vfob.offset))
        rs = RadioSetting("vfob.offset", "VFO B Offset (0.00-69.95)", val1b)
        rs.set_apply_callback(apply_offset, self._memobj.vfob)
        workmode.append(rs)

        options = ["High", "Low"]
        rs = RadioSetting("vfoa.txpower", "VFO A Power",
                          RadioSettingValueList(
                              options, options[self._memobj.vfoa.txpower]))
        workmode.append(rs)

        rs = RadioSetting("vfob.txpower", "VFO B Power",
                          RadioSettingValueList(
                              options, options[self._memobj.vfob.txpower]))
        workmode.append(rs)

        options = ["Wide", "Narrow"]
        rs = RadioSetting("vfoa.widenarr", "VFO A Bandwidth",
                          RadioSettingValueList(
                              options, options[self._memobj.vfoa.widenarr]))
        workmode.append(rs)

        rs = RadioSetting("vfob.widenarr", "VFO B Bandwidth",
                          RadioSettingValueList(
                              options, options[self._memobj.vfob.widenarr]))
        workmode.append(rs)

        options = ["%s" % x for x in range(1, 16)]
        rs = RadioSetting("vfoa.scode", "VFO A PTT-ID",
                          RadioSettingValueList(
                              options, options[self._memobj.vfoa.scode]))
        workmode.append(rs)

        rs = RadioSetting("vfob.scode", "VFO B PTT-ID",
                          RadioSettingValueList(
                              options, options[self._memobj.vfob.scode]))
        workmode.append(rs)

        rs = RadioSetting("vfoa.step", "VFO A Tuning Step",
                          RadioSettingValueList(
                              STEP_LIST, STEP_LIST[self._memobj.vfoa.step]))
        workmode.append(rs)
        rs = RadioSetting("vfob.step", "VFO B Tuning Step",
                          RadioSettingValueList(
                              STEP_LIST, STEP_LIST[self._memobj.vfob.step]))
        workmode.append(rs)

        fm_preset = RadioSettingGroup("fm_preset", "FM Radio Preset")
        group.append(fm_preset)

        preset = self._memobj.fm_preset / 10.0 + 87
        rs = RadioSetting("fm_preset", "FM Preset(MHz)",
                          RadioSettingValueFloat(87, 107.5, preset, 0.1, 1))
        fm_preset.append(rs)

        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        group.append(dtmf)
        dtmfchars = "0123456789 *#ABCD"

        for i in range(0, 15):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 5, _code, False)
            val.set_charset(dtmfchars)
            rs = RadioSetting("pttid/%i.code" % i,
                              "PTT ID Code %i" % (i + 1), val)

            def apply_code(setting, obj):
                code = []
                for j in range(0, 5):
                    try:
                        code.append(dtmfchars.index(str(setting.value)[j]))
                    except IndexError:
                        code.append(0xFF)
                obj.code = code
            rs.set_apply_callback(apply_code, self._memobj.pttid[i])
            dtmf.append(rs)

        _codeobj = self._memobj.ani.code
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("ani.code", "ANI Code", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 5):
                try:
                    code.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code
        rs.set_apply_callback(apply_code, self._memobj.ani)
        dtmf.append(rs)

        options = ["Off", "BOT", "EOT", "Both"]
        rs = RadioSetting("ani.aniid", "ANI ID",
                          RadioSettingValueList(
                              options, options[self._memobj.ani.aniid]))
        dtmf.append(rs)

        _codeobj = self._memobj.ani.alarmcode
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("ani.alarmcode", "Alarm Code", val)

        def apply_code(setting, obj):
            alarmcode = []
            for j in range(5):
                try:
                    alarmcode.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    alarmcode.append(0xFF)
            obj.alarmcode = alarmcode
        rs.set_apply_callback(apply_code, self._memobj.ani)
        dtmf.append(rs)

        rs = RadioSetting("dtmfst", "DTMF Sidetone",
                          RadioSettingValueList(
                              uv5r.DTMFST_LIST,
                              uv5r.DTMFST_LIST[_settings.dtmfst]))
        dtmf.append(rs)

        rs = RadioSetting("ani.dtmfon", "DTMF Speed (on)",
                          RadioSettingValueList(
                              uv5r.DTMFSPEED_LIST,
                              uv5r.DTMFSPEED_LIST[self._memobj.ani.dtmfon]))
        dtmf.append(rs)

        rs = RadioSetting("ani.dtmfoff", "DTMF Speed (off)",
                          RadioSettingValueList(
                              uv5r.DTMFSPEED_LIST,
                              uv5r.DTMFSPEED_LIST[self._memobj.ani.dtmfoff]))
        dtmf.append(rs)

        return group

    def _set_fm_preset(self, settings):
        for element in settings:
            try:
                val = element.value
                value = int(val.get_value() * 10 - 870)
                LOG.debug("Setting fm_preset = %s" % (value))
                self._memobj.fm_preset = value
            except Exception, e:
                LOG.debug(element.get_name())
                raise
