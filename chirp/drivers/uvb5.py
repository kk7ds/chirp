# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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

from __future__ import division

import struct
import logging
from chirp import chirp_common, directory, bitwise, memmap, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
                RadioSettingValueBoolean, RadioSettingValueList, \
                RadioSettingValueInteger, RadioSettingValueString, \
                RadioSettingValueFloat, RadioSettings

LOG = logging.getLogger(__name__)

mem_format = """
struct memory {
  lbcd freq[4];
  lbcd offset[4];
  u8 unknown1:2,
     txpol:1,
     rxpol:1,
     compander:1,
     unknown2:3;
  u8 rxtone;
  u8 txtone;
  u8 pttid:1,
     scanadd:1,
     isnarrow:1,
     bcl:1,
     highpower:1,
     revfreq:1,
     duplex:2;
  u8 step;
  u8 unknown[3];
};

#seekto 0x0000;
char ident[32];
u8 blank[16];
struct memory vfo1;
struct memory channels[99];
#seekto 0x0850;
struct memory vfo2;

#seekto 0x09D0;
u16 fm_presets[16];

#seekto 0x0A30;
struct {
  u8 name[5];
} names[99];

#seekto 0x0D30;
struct {
  u8 squelch;
  u8 freqmode_ab:1,
     save_funct:1,
     backlight:1,
     beep_tone_disabled:1,
     roger:1,
     tdr:1,
     scantype:2;
  u8 language:1,
     workmode_b:1,
     workmode_a:1,
     workmode_fm:1,
     voice_prompt:1,
     fm:1,
     pttid:2;
  u8 unknown_0:5,
     timeout:3;
  u8 mdf_b:2,
     mdf_a:2,
     unknown_1:2,
     txtdr:2;
  u8 unknown_2:4,
     ste_disabled:1,
     unknown_3:2,
     sidetone:1;
  u8 vox;
  u8 unk1;
  u8 mem_chan_a;
  u16 fm_vfo;
  u8 unk4;
  u8 unk5;
  u8 mem_chan_b;
  u8 unk6;
  u8 last_menu; // number of last menu item accessed
} settings;

#seekto 0x0D50;
struct {
  u8 code[6];
} pttid;

#seekto 0x0F30;
struct {
  lbcd lower_vhf[2];
  lbcd upper_vhf[2];
  lbcd lower_uhf[2];
  lbcd upper_uhf[2];
} limits;

#seekto 0x0FF0;
struct {
  u8 vhfsquelch0;
  u8 vhfsquelch1;
  u8 vhfsquelch2;
  u8 vhfsquelch3;
  u8 vhfsquelch4;
  u8 vhfsquelch5;
  u8 vhfsquelch6;
  u8 vhfsquelch7;
  u8 vhfsquelch8;
  u8 vhfsquelch9;
  u8 unknown1[6];
  u8 uhfsquelch0;
  u8 uhfsquelch1;
  u8 uhfsquelch2;
  u8 uhfsquelch3;
  u8 uhfsquelch4;
  u8 uhfsquelch5;
  u8 uhfsquelch6;
  u8 uhfsquelch7;
  u8 uhfsquelch8;
  u8 uhfsquelch9;
  u8 unknown2[6];
  u8 vhfhipwr0;
  u8 vhfhipwr1;
  u8 vhfhipwr2;
  u8 vhfhipwr3;
  u8 vhfhipwr4;
  u8 vhfhipwr5;
  u8 vhfhipwr6;
  u8 vhfhipwr7;
  u8 vhflopwr0;
  u8 vhflopwr1;
  u8 vhflopwr2;
  u8 vhflopwr3;
  u8 vhflopwr4;
  u8 vhflopwr5;
  u8 vhflopwr6;
  u8 vhflopwr7;
  u8 uhfhipwr0;
  u8 uhfhipwr1;
  u8 uhfhipwr2;
  u8 uhfhipwr3;
  u8 uhfhipwr4;
  u8 uhfhipwr5;
  u8 uhfhipwr6;
  u8 uhfhipwr7;
  u8 uhflopwr0;
  u8 uhflopwr1;
  u8 uhflopwr2;
  u8 uhflopwr3;
  u8 uhflopwr4;
  u8 uhflopwr5;
  u8 uhflopwr6;
  u8 uhflopwr7;
} test;
"""


def do_ident(radio):
    radio.pipe.timeout = 3
    radio.pipe.write(b"\x05PROGRAM")
    for x in range(10):
        ack = radio.pipe.read(1)
        if ack == b'\x06':
            break
    else:
        raise errors.RadioError("Radio did not ack programming mode")
    radio.pipe.write(b"\x02")
    ident = radio.pipe.read(8)
    LOG.debug(util.hexprint(ident))
    if not ident.startswith(b'HKT511'):
        raise errors.RadioError("Unsupported model")
    radio.pipe.write(b"\x06")
    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise errors.RadioError("Radio did not ack ident")


def do_status(radio, direction, addr):
    status = chirp_common.Status()
    status.msg = "Cloning %s radio" % direction
    status.cur = addr
    status.max = 0x1000
    radio.status_fn(status)


def do_download(radio):
    do_ident(radio)
    data = b"KT511 Radio Program data v1.08\x00\x00"
    data += (b"\x00" * 16)
    firstack = None
    for i in range(0, 0x1000, 16):
        frame = struct.pack(">cHB", b"R", i, 16)
        radio.pipe.write(frame)
        result = radio.pipe.read(20)
        if frame[1:4] != result[1:4]:
            LOG.debug(util.hexprint(result))
            raise errors.RadioError("Invalid response for address 0x%04x" % i)
        radio.pipe.write(b"\x06")
        ack = radio.pipe.read(1)
        if not firstack:
            firstack = ack
        else:
            if not ack == firstack:
                LOG.debug("first ack: %s ack received: %s",
                          util.hexprint(firstack), util.hexprint(ack))
                raise errors.RadioError("Unexpected response")
        data += result[4:]
        do_status(radio, "from", i)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    do_ident(radio)
    data = radio._mmap.get_byte_compatible()[0x0030:]

    for i in range(0, 0x1000, 16):
        frame = struct.pack(">cHB", b"W", i, 16)
        frame += data[i:i + 16]
        radio.pipe.write(frame)
        ack = radio.pipe.read(1)
        if ack != b"\x06":
            # UV-B5/UV-B6 radios with 27 menus do not support service settings
            # and will stop ACKing when the upload reaches 0x0F10
            if i == 0x0F10:
                # must be a radio with 27 menus detected - stop upload
                break
            else:
                LOG.debug("Radio NAK'd block at address 0x%04x" % i)
                raise errors.RadioError(
                    "Radio NAK'd block at address 0x%04x" % i)
        LOG.debug("Radio ACK'd block at address 0x%04x" % i)
        do_status(radio, "to", i)


DUPLEX = ["", "-", "+"]
UVB5_STEPS = [5.00, 6.25, 10.0, 12.5, 20.0, 25.0]
CHARSET = "0123456789- ABCDEFGHIJKLMNOPQRSTUVWXYZ/_+*"
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                chirp_common.PowerLevel("High", watts=5)]


@directory.register
class BaofengUVB5(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):
    """Baofeng UV-B5"""
    VENDOR = "Baofeng"
    MODEL = "UV-B5"
    BAUD_RATE = 9600
    SPECIALS = {
        "VFO1": -2,
        "VFO2": -1,
    }

    _memsize = 0x1000

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This version of the UV-B5 driver allows you to '
             'modify the Test Mode settings of your radio. This has been '
             'tested and reports from other users indicate that it is a '
             'safe thing to do. However, modifications to these values may '
             'have unintended consequences, including damage to your '
             'device. You have been warned. Proceed at your own risk!')
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Turn radio on.\n"
            "5. Ensure that the radio is tuned to channel with no"
            " activity.\n"
            "6. Click OK to download image from device.\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Turn radio on.\n"
            "5. Ensure that the radio is tuned to channel with no"
            " activity.\n"
            "6. Click OK to upload image to device.\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_duplexes = DUPLEX + ["split"]
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 5
        rf.valid_tuning_steps = UVB5_STEPS
        rf.valid_bands = [(130000000, 175000000),
                          (220000000, 269000000),
                          (400000000, 520000000)]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_special_chans = list(self.SPECIALS.keys())
        rf.valid_power_levels = POWER_LEVELS
        rf.has_ctone = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.memory_bounds = (1, 99)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.channels[number - 1])

    def _decode_tone(self, _mem, which):
        def _get(field):
            return getattr(_mem, "%s%s" % (which, field))

        value = _get('tone')
        flag = _get('pol')

        if value > 155:
            mode = val = pol = None
        elif value > 50:
            mode = 'DTCS'
            val = chirp_common.DTCS_CODES[value - 51]
            pol = flag and 'R' or 'N'
        elif value:
            mode = 'Tone'
            val = chirp_common.TONES[value - 1]
            pol = None
        else:
            mode = val = pol = None

        return mode, val, pol

    def _encode_tone(self, _mem, which, mode, val, pol):
        def _set(field, value):
            setattr(_mem, "%s%s" % (which, field), value)

        _set("pol", 0)
        if mode == "Tone":
            _set("tone", chirp_common.TONES.index(val) + 1)
        elif mode == "DTCS":
            _set("tone", chirp_common.DTCS_CODES.index(val) + 51)
            _set("pol", pol == "R")
        else:
            _set("tone", 0)

    def _get_memobjs(self, number):
        if isinstance(number, str):
            return (getattr(self._memobj, number.lower()), None)
        elif number < 0:
            for k, v in list(self.SPECIALS.items()):
                if number == v:
                    return (getattr(self._memobj, k.lower()), None)
        else:
            return (self._memobj.channels[number - 1],
                    self._memobj.names[number - 1].name)

    def get_memory(self, number):
        _mem, _nam = self._get_memobjs(number)
        mem = chirp_common.Memory()
        if isinstance(number, str):
            mem.number = self.SPECIALS[number]
            mem.extd_number = number
        else:
            mem.number = number

        if _mem.freq.get_raw()[0] == 0xff:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 10

        chirp_common.split_tone_decode(
            mem,
            self._decode_tone(_mem, "tx"),
            self._decode_tone(_mem, "rx"))

        if 'step' in _mem and _mem.step > 0x05:
            _mem.step = 0x00
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = _mem.isnarrow and "NFM" or "FM"
        mem.skip = "" if _mem.scanadd else "S"
        mem.power = POWER_LEVELS[_mem.highpower]

        if _nam:
            for char in _nam:
                try:
                    mem.name += CHARSET[char]
                except IndexError:
                    break
            mem.name = mem.name.rstrip()

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("revfreq", "Reverse Duplex",
                          RadioSettingValueBoolean(_mem.revfreq))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueBoolean(_mem.pttid))
        mem.extra.append(rs)

        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(_mem.compander))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem, _nam = self._get_memobjs(mem.number)

        if mem.empty:
            if _nam is None:
                raise errors.InvalidValueError("VFO channels can not be empty")
            _mem.set_raw("\xFF" * 16)
            return

        if _mem.get_raw(asbytes=False) == ("\xFF" * 16):
            _mem.set_raw("\x00" * 13 + "\xFF" * 3)

        _mem.freq = mem.freq / 10

        if mem.duplex == "split":
            diff = mem.offset - mem.freq
            _mem.duplex = DUPLEX.index("-") if diff < 0 else DUPLEX.index("+")
            _mem.offset = abs(diff) / 10
        else:
            _mem.offset = mem.offset / 10
            _mem.duplex = DUPLEX.index(mem.duplex)

        tx, rx = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem, 'tx', *tx)
        self._encode_tone(_mem, 'rx', *rx)

        _mem.isnarrow = mem.mode == "NFM"
        _mem.scanadd = mem.skip == ""
        _mem.highpower = mem.power == POWER_LEVELS[1]

        if _nam:
            for i in range(0, 5):
                try:
                    _nam[i] = CHARSET.index(mem.name[i])
                except IndexError:
                    _nam[i] = 0xFF

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")

        group = RadioSettings(basic)

        options = ["Time", "Carrier", "Search"]
        rs = RadioSetting(
            "scantype", "Scan Type",
            RadioSettingValueList(
                options, current_index=_settings.scantype))
        basic.append(rs)

        options = ["Off"] + ["%s min" % x for x in range(1, 8)]
        rs = RadioSetting("timeout", "Time Out Timer",
                          RadioSettingValueList(
                              options, current_index=_settings.timeout))
        basic.append(rs)

        options = ["A", "B"]
        rs = RadioSetting("freqmode_ab", "Frequency Mode",
                          RadioSettingValueList(
                              options, current_index=_settings.freqmode_ab))
        basic.append(rs)

        options = ["Frequency Mode", "Channel Mode"]
        rs = RadioSetting("workmode_a", "Radio Work Mode(A)",
                          RadioSettingValueList(
                              options, current_index=_settings.workmode_a))
        basic.append(rs)

        rs = RadioSetting("workmode_b", "Radio Work Mode(B)",
                          RadioSettingValueList(
                              options, current_index=_settings.workmode_b))
        basic.append(rs)

        options = ["Frequency", "Name", "Channel"]
        rs = RadioSetting("mdf_a", "Display Format(F1)",
                          RadioSettingValueList(
                              options, current_index=_settings.mdf_a))
        basic.append(rs)

        rs = RadioSetting("mdf_b", "Display Format(F2)",
                          RadioSettingValueList(
                              options, current_index=_settings.mdf_b))
        basic.append(rs)

        rs = RadioSetting("mem_chan_a", "Mem Channel (A)",
                          RadioSettingValueInteger(
                              1, 99, _settings.mem_chan_a))
        basic.append(rs)

        rs = RadioSetting("mem_chan_b", "Mem Channel (B)",
                          RadioSettingValueInteger(
                              1, 99, _settings.mem_chan_b))
        basic.append(rs)

        options = ["Off", "BOT", "EOT", "Both"]
        rs = RadioSetting("pttid", "PTT-ID",
                          RadioSettingValueList(
                              options, current_index=_settings.pttid))
        basic.append(rs)

        dtmfchars = "0123456789ABCD*#"
        _codeobj = self._memobj.pttid.code
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 6, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("pttid.code", "PTT-ID Code", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 6):
                try:
                    code.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code
        rs.set_apply_callback(apply_code, self._memobj.pttid)
        basic.append(rs)

        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("vox", "VOX Level",
                          RadioSettingValueInteger(0, 9, _settings.vox))
        basic.append(rs)

        options = ["Frequency Mode", "Channel Mode"]
        rs = RadioSetting("workmode_fm", "FM Work Mode",
                          RadioSettingValueList(
                              options, current_index=_settings.workmode_fm))
        basic.append(rs)

        options = ["Current Frequency", "F1 Frequency", "F2 Frequency"]
        rs = RadioSetting("txtdr", "Dual Standby TX Priority",
                          RadioSettingValueList(options,
                                                current_index=_settings.txtdr))
        basic.append(rs)

        options = ["English", "Chinese"]
        rs = RadioSetting(
            "language", "Language",
            RadioSettingValueList(
                options, current_index=_settings.language))
        basic.append(rs)

        rs = RadioSetting("tdr", "Dual Standby",
                          RadioSettingValueBoolean(_settings.tdr))
        basic.append(rs)

        rs = RadioSetting("roger", "Roger Beep",
                          RadioSettingValueBoolean(_settings.roger))
        basic.append(rs)

        rs = RadioSetting("backlight", "Backlight",
                          RadioSettingValueBoolean(_settings.backlight))
        basic.append(rs)

        rs = RadioSetting("save_funct", "Save Mode",
                          RadioSettingValueBoolean(_settings.save_funct))
        basic.append(rs)

        rs = RadioSetting("fm", "FM Function",
                          RadioSettingValueBoolean(_settings.fm))
        basic.append(rs)

        rs = RadioSetting("beep_tone_disabled", "Beep Prompt",
                          RadioSettingValueBoolean(
                              not _settings.beep_tone_disabled))
        basic.append(rs)

        rs = RadioSetting("voice_prompt", "Voice Prompt",
                          RadioSettingValueBoolean(_settings.voice_prompt))
        basic.append(rs)

        rs = RadioSetting("sidetone", "DTMF Side Tone",
                          RadioSettingValueBoolean(_settings.sidetone))
        basic.append(rs)

        rs = RadioSetting("ste_disabled", "Squelch Tail Eliminate",
                          RadioSettingValueBoolean(not _settings.ste_disabled))
        basic.append(rs)

        _limit = int(self._memobj.limits.lower_vhf) // 10
        rs = RadioSetting("limits.lower_vhf", "VHF Lower Limit (MHz)",
                          RadioSettingValueInteger(128, 270, _limit))

        def apply_limit(setting, obj):
            value = int(setting.value) * 10
            obj.lower_vhf = value
        rs.set_apply_callback(apply_limit, self._memobj.limits)
        basic.append(rs)

        _limit = int(self._memobj.limits.upper_vhf) // 10
        rs = RadioSetting("limits.upper_vhf", "VHF Upper Limit (MHz)",
                          RadioSettingValueInteger(128, 270, _limit))

        def apply_limit(setting, obj):
            value = int(setting.value) * 10
            obj.upper_vhf = value
        rs.set_apply_callback(apply_limit, self._memobj.limits)
        basic.append(rs)

        _limit = int(self._memobj.limits.lower_uhf) // 10
        rs = RadioSetting("limits.lower_uhf", "UHF Lower Limit (MHz)",
                          RadioSettingValueInteger(400, 520, _limit))

        def apply_limit(setting, obj):
            value = int(setting.value) * 10
            obj.lower_uhf = value
        rs.set_apply_callback(apply_limit, self._memobj.limits)
        basic.append(rs)

        _limit = int(self._memobj.limits.upper_uhf) // 10
        rs = RadioSetting("limits.upper_uhf", "UHF Upper Limit (MHz)",
                          RadioSettingValueInteger(400, 520, _limit))

        def apply_limit(setting, obj):
            value = int(setting.value) * 10
            obj.upper_uhf = value
        rs.set_apply_callback(apply_limit, self._memobj.limits)
        basic.append(rs)

        fm_preset = RadioSettingGroup("fm_preset", "FM Radio Presets")
        group.append(fm_preset)

        for i in range(0, 16):
            if self._memobj.fm_presets[i] < 0x01AF:
                used = True
                preset = self._memobj.fm_presets[i] / 10.0 + 65
            else:
                used = False
                preset = 65
            rs = RadioSetting("fm_presets_%1i" % i, "FM Preset %i" % (i + 1),
                              RadioSettingValueBoolean(used),
                              RadioSettingValueFloat(65, 108, preset, 0.1, 1))
            fm_preset.append(rs)

        testmode = RadioSettingGroup("testmode", "Test Mode Settings")
        group.append(testmode)

        vhfdata = ["136-139", "140-144", "145-149", "150-154",
                   "155-159", "160-164", "165-169", "170-174"]
        uhfdata = ["400-409", "410-419", "420-429", "430-439",
                   "440-449", "450-459", "460-469", "470-479"]
        powernamedata = ["Hi", "Lo"]
        powerkeydata = ["hipwr", "lopwr"]

        for power in range(0, 2):
            for index in range(0, 8):
                key = "test.vhf%s%i" % (powerkeydata[power], index)
                name = "%s MHz %s Power" % (vhfdata[index],
                                            powernamedata[power])
                rs = RadioSetting(
                        key, name, RadioSettingValueInteger(
                            0, 255, getattr(
                                self._memobj.test,
                                "vhf%s%i" % (powerkeydata[power], index))))
                testmode.append(rs)

        for power in range(0, 2):
            for index in range(0, 8):
                key = "test.uhf%s%i" % (powerkeydata[power], index)
                name = "%s MHz %s Power" % (uhfdata[index],
                                            powernamedata[power])
                rs = RadioSetting(
                        key, name, RadioSettingValueInteger(
                            0, 255, getattr(
                                self._memobj.test,
                                "uhf%s%i" % (powerkeydata[power], index))))
                testmode.append(rs)

        for band in ["vhf", "uhf"]:
            for index in range(0, 10):
                key = "test.%ssquelch%i" % (band, index)
                name = "%s Squelch %i" % (band.upper(), index)
                rs = RadioSetting(
                        key, name, RadioSettingValueInteger(
                            0, 255, getattr(
                                self._memobj.test,
                                "%ssquelch%i" % (band, index))))
                testmode.append(rs)

        return group

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() == "fm_preset":
                    self._set_fm_preset(element)
                else:
                    self.set_settings(element)
                    continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "beep_tone_disabled":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "ste_disabled":
                        setattr(obj, setting, not int(element.value))
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _set_fm_preset(self, settings):
        for element in settings:
            try:
                index = (int(element.get_name().split("_")[-1]))
                val = element.value
                if list(val)[0].get_value():
                    value = int(list(val)[1].get_value() * 10 - 650)
                else:
                    value = 0x01AF
                LOG.debug("Setting fm_presets[%1i] = %s" % (index, value))
                setting = self._memobj.fm_presets
                setting[index] = value
            except Exception:
                LOG.debug(element.get_name())
                raise

    @classmethod
    def match_model(cls, filedata, filename):
        return (filedata.startswith(b"KT511 Radio Program data") and
                len(filedata) == (cls._memsize + 0x30))
