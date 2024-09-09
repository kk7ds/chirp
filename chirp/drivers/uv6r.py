# Copyright 2016:
# * Jim Unroe KC9HI, <rock.unroe@gmail.com>
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

from chirp.drivers import baofeng_common as bfc
from chirp import chirp_common, directory
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, \
    InvalidValueError

LOG = logging.getLogger(__name__)

# #### MAGICS #########################################################

# Baofeng UV-6R magic string
MSTRING_UV6R = b"\x50\xBB\xFF\x20\x14\x11\x22"

# #### ID strings #####################################################

# Baofeng UV-6R
UV6R_fp1 = b" BF230#1"
UV6R_fp2 = b" BF230#2"

DTMF_CHARS = "0123456789 *#ABCD"
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]

LIST_AB = ["A", "B"]
LIST_ALMOD = ["Site", "Tone", "Code"]
LIST_BANDWIDTH = ["Wide", "Narrow"]
LIST_COLOR = ["Off", "Blue", "Orange", "Purple"]
LIST_DTMFSPEED = ["%s ms" % x for x in range(50, 2010, 10)]
LIST_DTMFST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
LIST_MODE = ["Channel", "Name", "Frequency"]
LIST_OFF1TO9 = ["Off"] + list("123456789")
LIST_OFF1TO10 = LIST_OFF1TO9 + ["10"]
LIST_OFFAB = ["Off"] + LIST_AB
LIST_RESUME = ["TO", "CO", "SE"]
LIST_PONMSG = ["Full", "Message"]
LIST_PTTID = ["Off", "BOT", "EOT", "Both"]
LIST_SCODE = ["%s" % x for x in range(1, 16)]
LIST_RPSTE = ["Off"] + ["%s" % x for x in range(1, 11)]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SHIFTD = ["Off", "+", "-"]
LIST_STEDELAY = ["Off"] + ["%s ms" % x for x in range(100, 1100, 100)]
LIST_STEP = [str(x) for x in STEPS]
LIST_TCALL = ["Off", "1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
LIST_TIMEOUT = ["%s sec" % x for x in range(15, 615, 15)]
LIST_TXPOWER = ["High", "Low"]
LIST_VOICE = ["Off", "English", "Chinese"]
LIST_WORKMODE = ["Frequency", "Channel"]


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    match_rid1 = False
    match_rid2 = False

    rid1 = data[0x1FF8:0x2000]

    if rid1 in cls._fileid:
        match_rid1 = True

    rid2 = data[0x1FD0:0x1FD5]

    if rid2 == cls.MODEL.encode():
        match_rid2 = True

    if match_rid1 and match_rid2:
        return True
    else:
        return False


@directory.register
class UV6R(bfc.BaofengCommonHT):
    """Baofeng UV-6R"""
    VENDOR = "Baofeng"
    MODEL = "UV-6R"

    _fileid = [UV6R_fp2, UV6R_fp1, ]

    _magic = [MSTRING_UV6R, ]
    _magic_response_length = 8
    _fw_ver_start = 0x1FF0
    _recv_block_size = 0x40
    _mem_size = 0x2000
    _ack_block = False

    _ranges = [(0x0000, 0x1800),
               (0x1F40, 0x1F50),
               (0x1FC0, 0x1FD0),
               (0x1FE0, 0x1FF0)]
    _send_block_size = 0x10

    MODES = ["FM", "NFM"]
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "!@#$%^&*()+-=[]:\";'<>?,./"
    LENGTH_NAME = 7  # older radios may only support 6 character names
    SKIP_VALUES = ["", "S"]
    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]
    VALID_BANDS = [(136000000, 174000000),
                   (400000000, 520000000)]
    PTTID_LIST = LIST_PTTID
    SCODE_LIST = LIST_SCODE

    MEM_FORMAT = """
    // #seekto 0x0000;
    struct {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      ul16 rxtone;
      ul16 txtone;
      u8 unknown0:4,
         scode:4;
      u8 unknown1;
      u8 unknown2:7,
         lowpower:1;
      u8 unknown3:1,
         wide:1,
         unknown4:2,
         bcl:1,
         scan:1,
         pttid:2;
    } memory[128];

    #seekto 0x0B00;
    struct {
      u8 code[5];
      u8 unused[11];
    } pttid[15];

    #seekto 0x0CAA;
    struct {
      u8 code[5];
      u8 unused:6,
         aniid:2;
      u8 unknown[2];
      u8 dtmfon;
      u8 dtmfoff;
    } ani;

    #seekto 0x0E20;
    struct {
      u8 unused00:4,
     squelch:4;
      u8 unused01:5,
         step:3;
      u8 unknown00;
      u8 unused02:5,
         save:3;
      u8 unused03:4,
         vox:4;
      u8 unknown01;
      u8 unused04:4,
         abr:4;
      u8 unused05:7,
         tdr:1;
      u8 unused06:7,
         beep:1;
      u8 unused07:2,
         timeout:6;
      u8 unused08:6,
         tcall:2;
      u8 unknown02[3];
      u8 unused09:6,
         voice:2;
      u8 unknown03;
      u8 unused10:6,
         dtmfst:2;
      u8 unknown04;
      u8 unused11:6,
         screv:2;
      u8 unused12:6,
         pttid:2;
      u8 unused13:2,
         pttlt:6;
      u8 unused14:6,
         mdfa:2;
      u8 unused15:6,
         mdfb:2;
      u8 unknown05;
      u8 unused16:7,
         autolk:1;
      u8 unknown06[4];
      u8 unused17:6,
         wtled:2;
      u8 unused18:6,
         rxled:2;
      u8 unused19:6,
         txled:2;
      u8 unused20:6,
         almod:2;
      u8 unknown07[2];
      u8 unused22:7,
         ste:1;
      u8 unused23:4,
         rpste:4;
      u8 unused24:4,
         rptrl:4;
      u8 unused25:7,
         ponmsg:1;
      u8 unused26:7,
         roger:1;
      u8 unknown08[2];
      u8 displayab:1,
         unknown09:2,
         fmradio:1,
         alarm:1,
         unknown10:1,
         reset:1,
         menu:1;
      u8 unknown11;
      u8 unused29:7,
         workmode:1;
      u8 unused30:7,
         keylock:1;
      u8 cht;
    } settings;

    #seekto 0x0E76;
    struct {
      u8 unused0:1,
         mrcha:7;
      u8 unused1:1,
         mrchb:7;
    } wmchannel;

    struct vfo {
      u8 unknown0[8];
      u8 freq[8];
      u8 offset[6];
      ul16 rxtone;
      ul16 txtone;
      u8 unused0:7,
         band:1;
      u8 unknown3;
      u8 unknown4:2,
         sftd:2,
         scode:4;
      u8 unknown5;
      u8 unknown6:1,
         step:3,
         unknown7:4;
      u8 txpower:1,
         widenarr:1,
         unknown8:6;
    };

    #seekto 0x0F00;
    struct {
      struct vfo a;
      struct vfo b;
    } vfo;

    #seekto 0x0F4E;
    u16 fm_presets;

    #seekto 0x1000;
    struct {
      char name[7];
      u8 unknown[9];
    } names[128];

    #seekto 0x1F40;
    struct {
      u8 sql0;
      u8 sql1;
      u8 sql2;
      u8 sql3;
      u8 sql4;
      u8 sql5;
      u8 sql6;
      u8 sql7;
      u8 sql8;
      u8 sql9;
    } squelch;

    struct limit {
      u8 enable;
      bbcd lower[2];
      bbcd upper[2];
    };

    #seekto 0x1FC0;
    struct {
      struct limit vhf;
      struct limit uhf;
    } limits;

    #seekto 0x1FD0;
    struct {
      char line1[8];
      char line2[8];
    } sixpoweron_msg;

    // #seekto 0x1FE0;
    struct {
      char line1[7];
      char line2[7];
    } poweron_msg;

    #seekto 0x1FF0;
    struct {
      char line1[8];
      char line2[8];
    } firmware_msg;

    """

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('The BTech UV-6R driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        other = RadioSettingGroup("other", "Other Settings")
        work = RadioSettingGroup("work", "Work Mode Settings")
        fm_preset = RadioSettingGroup("fm_preset", "FM Preset")
        dtmfe = RadioSettingGroup("dtmfe", "DTMF Encode Settings")
        service = RadioSettingGroup("service", "Service Settings")
        top = RadioSettings(basic, advanced, other, work, fm_preset, dtmfe,
                            service)

        # Basic settings
        if _mem.settings.squelch > 0x09:
            val = 0x00
        else:
            val = _mem.settings.squelch
        rs = RadioSetting("settings.squelch", "Squelch",
                          RadioSettingValueList(
                              LIST_OFF1TO9, current_index=val))
        basic.append(rs)

        if _mem.settings.save > 0x04:
            val = 0x00
        else:
            val = _mem.settings.save
        rs = RadioSetting("settings.save", "Battery Saver",
                          RadioSettingValueList(
                              LIST_SAVE, current_index=val))
        basic.append(rs)

        if _mem.settings.vox > 0x0A:
            val = 0x00
        else:
            val = _mem.settings.vox
        rs = RadioSetting("settings.vox", "Vox",
                          RadioSettingValueList(
                              LIST_OFF1TO10, current_index=val))
        basic.append(rs)

        if _mem.settings.abr > 0x0A:
            val = 0x00
        else:
            val = _mem.settings.abr
        rs = RadioSetting("settings.abr", "Backlight Timeout",
                          RadioSettingValueList(
                              LIST_OFF1TO10, current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.tdr", "Dual Watch",
                          RadioSettingValueBoolean(_mem.settings.tdr))
        basic.append(rs)

        rs = RadioSetting("settings.beep", "Beep",
                          RadioSettingValueBoolean(_mem.settings.beep))
        basic.append(rs)

        if _mem.settings.timeout > 0x27:
            val = 0x03
        else:
            val = _mem.settings.timeout
        rs = RadioSetting("settings.timeout", "Timeout Timer",
                          RadioSettingValueList(
                              LIST_TIMEOUT, current_index=val))
        basic.append(rs)

        if _mem.settings.voice > 0x02:
            val = 0x01
        else:
            val = _mem.settings.voice
        rs = RadioSetting("settings.voice", "Voice Prompt",
                          RadioSettingValueList(
                              LIST_VOICE, current_index=val))
        basic.append(rs)

        rs = RadioSetting(
            "settings.dtmfst", "DTMF Sidetone",
            RadioSettingValueList(
                LIST_DTMFST, current_index=_mem.settings.dtmfst))
        basic.append(rs)

        if _mem.settings.screv > 0x02:
            val = 0x01
        else:
            val = _mem.settings.screv
        rs = RadioSetting("settings.screv", "Scan Resume",
                          RadioSettingValueList(
                              LIST_RESUME, current_index=val))
        basic.append(rs)

        rs = RadioSetting(
            "settings.pttid", "When to send PTT ID",
            RadioSettingValueList(
                LIST_PTTID, current_index=_mem.settings.pttid))
        basic.append(rs)

        if _mem.settings.pttlt > 0x1E:
            val = 0x05
        else:
            val = _mem.settings.pttlt
        rs = RadioSetting("pttlt", "PTT ID Delay",
                          RadioSettingValueInteger(0, 50, val))
        basic.append(rs)

        rs = RadioSetting(
            "settings.mdfa", "Display Mode (A)",
            RadioSettingValueList(
                LIST_MODE, current_index=_mem.settings.mdfa))
        basic.append(rs)

        rs = RadioSetting(
            "settings.mdfb", "Display Mode (B)",
            RadioSettingValueList(
                LIST_MODE, current_index=_mem.settings.mdfb))
        basic.append(rs)

        rs = RadioSetting("settings.autolk", "Auto Lock Keypad",
                          RadioSettingValueBoolean(_mem.settings.autolk))
        basic.append(rs)

        rs = RadioSetting("settings.wtled", "Standby LED Color",
                          RadioSettingValueList(
                              LIST_COLOR, current_index=_mem.settings.wtled))
        basic.append(rs)

        rs = RadioSetting("settings.rxled", "RX LED Color",
                          RadioSettingValueList(
                              LIST_COLOR, current_index=_mem.settings.rxled))
        basic.append(rs)

        rs = RadioSetting("settings.txled", "TX LED Color",
                          RadioSettingValueList(
                              LIST_COLOR, current_index=_mem.settings.txled))
        basic.append(rs)

        if _mem.settings.almod > 0x02:
            val = 0x00
        else:
            val = _mem.settings.almod
        rs = RadioSetting("settings.almod", "Alarm Mode",
                          RadioSettingValueList(
                              LIST_ALMOD, current_index=val))
        basic.append(rs)

        if _mem.settings.tcall > 0x05:
            val = 0x00
        else:
            val = _mem.settings.tcall
        rs = RadioSetting("settings.tcall", "Tone Burst Frequency",
                          RadioSettingValueList(
                              LIST_TCALL, current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.ste", "Squelch Tail Eliminate (HT to HT)",
                          RadioSettingValueBoolean(_mem.settings.ste))
        basic.append(rs)

        if _mem.settings.rpste > 0x0A:
            val = 0x00
        else:
            val = _mem.settings.rpste
        rs = RadioSetting("settings.rpste",
                          "Squelch Tail Eliminate (repeater)",
                          RadioSettingValueList(
                              LIST_RPSTE, current_index=val))
        basic.append(rs)

        if _mem.settings.rptrl > 0x0A:
            val = 0x00
        else:
            val = _mem.settings.rptrl
        rs = RadioSetting("settings.rptrl", "STE Repeater Delay",
                          RadioSettingValueList(
                              LIST_STEDELAY, current_index=val))
        basic.append(rs)

        rs = RadioSetting(
            "settings.ponmsg", "Power-On Message",
            RadioSettingValueList(
                LIST_PONMSG, current_index=_mem.settings.ponmsg))
        basic.append(rs)

        rs = RadioSetting("settings.roger", "Roger Beep",
                          RadioSettingValueBoolean(_mem.settings.roger))
        basic.append(rs)

        # Advanced settings
        rs = RadioSetting("settings.reset", "RESET Menu",
                          RadioSettingValueBoolean(_mem.settings.reset))
        advanced.append(rs)

        rs = RadioSetting("settings.menu", "All Menus",
                          RadioSettingValueBoolean(_mem.settings.menu))
        advanced.append(rs)

        rs = RadioSetting("settings.fmradio", "Broadcast FM Radio",
                          RadioSettingValueBoolean(_mem.settings.fmradio))
        advanced.append(rs)

        rs = RadioSetting("settings.alarm", "Alarm Sound",
                          RadioSettingValueBoolean(_mem.settings.alarm))
        advanced.append(rs)

        # Other settings
        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        _msg = _mem.firmware_msg
        val = RadioSettingValueString(0, 8, _filter(_msg.line1))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line1", "Firmware Message 1", val)
        other.append(rs)

        val = RadioSettingValueString(0, 8, _filter(_msg.line2))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line2", "Firmware Message 2", val)
        other.append(rs)

        _msg = _mem.sixpoweron_msg
        val = RadioSettingValueString(0, 8, _filter(_msg.line1))
        val.set_mutable(False)
        rs = RadioSetting("sixpoweron_msg.line1", "6+Power-On Message 1", val)
        other.append(rs)
        val = RadioSettingValueString(0, 8, _filter(_msg.line2))
        val.set_mutable(False)
        rs = RadioSetting("sixpoweron_msg.line2", "6+Power-On Message 2", val)
        other.append(rs)

        _msg = _mem.poweron_msg
        rs = RadioSetting("poweron_msg.line1", "Power-On Message 1",
                          RadioSettingValueString(
                              0, 7, _filter(_msg.line1)))
        other.append(rs)
        rs = RadioSetting("poweron_msg.line2", "Power-On Message 2",
                          RadioSettingValueString(
                              0, 7, _filter(_msg.line2)))
        other.append(rs)

        lower = 136
        upper = 174
        rs = RadioSetting("limits.vhf.lower", "VHF Lower Limit (MHz)",
                          RadioSettingValueInteger(
                              lower, upper, _mem.limits.vhf.lower))
        other.append(rs)

        rs = RadioSetting("limits.vhf.upper", "VHF Upper Limit (MHz)",
                          RadioSettingValueInteger(
                              lower, upper, _mem.limits.vhf.upper))
        other.append(rs)

        lower = 400
        upper = 520
        rs = RadioSetting("limits.uhf.lower", "UHF Lower Limit (MHz)",
                          RadioSettingValueInteger(
                              lower, upper, _mem.limits.uhf.lower))
        other.append(rs)

        rs = RadioSetting("limits.uhf.upper", "UHF Upper Limit (MHz)",
                          RadioSettingValueInteger(
                              lower, upper, _mem.limits.uhf.upper))
        other.append(rs)

        # Work mode settings
        rs = RadioSetting("settings.displayab", "Display",
                          RadioSettingValueList(
                              LIST_AB, current_index=_mem.settings.displayab))
        work.append(rs)

        rs = RadioSetting("settings.workmode", "VFO/MR Mode",
                          RadioSettingValueList(
                              LIST_WORKMODE,
                              current_index=_mem.settings.workmode))
        work.append(rs)

        rs = RadioSetting("settings.keylock", "Keypad Lock",
                          RadioSettingValueBoolean(_mem.settings.keylock))
        work.append(rs)

        rs = RadioSetting("wmchannel.mrcha", "MR A Channel",
                          RadioSettingValueInteger(0, 127,
                                                   _mem.wmchannel.mrcha))
        work.append(rs)

        rs = RadioSetting("wmchannel.mrchb", "MR B Channel",
                          RadioSettingValueInteger(0, 127,
                                                   _mem.wmchannel.mrchb))
        work.append(rs)

        def my_validate(value):
            _vhf_lower = int(_mem.limits.vhf.lower)
            _vhf_upper = int(_mem.limits.vhf.upper)
            _uhf_lower = int(_mem.limits.uhf.lower)
            _uhf_upper = int(_mem.limits.uhf.upper)
            value = chirp_common.parse_freq(value)
            msg = ("Can't be less than %i.0000")
            if value > 99000000 and value < _vhf_lower * 1000000:
                raise InvalidValueError(msg % _vhf_lower)
            msg = ("Can't be between %i.9975-%i.0000")
            if _vhf_upper * 1000000 <= value and value < _uhf_lower * 1000000:
                raise InvalidValueError(msg % (_vhf_upper - 1, _uhf_lower))
            msg = ("Can't be greater than %i.9975")
            if value > 99000000 and value >= _uhf_upper * 1000000:
                raise InvalidValueError(msg % (_uhf_upper - 1))
            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(0, 10,
                                        bfc.bcd_decode_freq(_mem.vfo.a.freq))
        val1a.set_validate_callback(my_validate)
        rs = RadioSetting("vfo.a.freq", "VFO A Frequency", val1a)
        rs.set_apply_callback(apply_freq, _mem.vfo.a)
        work.append(rs)

        val1b = RadioSettingValueString(0, 10,
                                        bfc.bcd_decode_freq(_mem.vfo.b.freq))
        val1b.set_validate_callback(my_validate)
        rs = RadioSetting("vfo.b.freq", "VFO B Frequency", val1b)
        rs.set_apply_callback(apply_freq, _mem.vfo.b)
        work.append(rs)

        rs = RadioSetting("vfo.a.sftd", "VFO A Shift",
                          RadioSettingValueList(
                              LIST_SHIFTD, current_index=_mem.vfo.a.sftd))
        work.append(rs)

        rs = RadioSetting("vfo.b.sftd", "VFO B Shift",
                          RadioSettingValueList(
                              LIST_SHIFTD, current_index=_mem.vfo.b.sftd))
        work.append(rs)

        def convert_bytes_to_offset(bytes):
            real_offset = 0
            for byte in bytes:
                real_offset = (real_offset * 10) + byte
            return chirp_common.format_freq(real_offset * 1000)

        def apply_offset(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 1000
            for i in range(5, -1, -1):
                obj.offset[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(
                    0, 10, convert_bytes_to_offset(_mem.vfo.a.offset))
        rs = RadioSetting("vfo.a.offset",
                          "VFO A Offset", val1a)
        rs.set_apply_callback(apply_offset, _mem.vfo.a)
        work.append(rs)

        val1b = RadioSettingValueString(
                    0, 10, convert_bytes_to_offset(_mem.vfo.b.offset))
        rs = RadioSetting("vfo.b.offset",
                          "VFO B Offset", val1b)
        rs.set_apply_callback(apply_offset, _mem.vfo.b)
        work.append(rs)

        rs = RadioSetting("vfo.a.txpower", "VFO A Power",
                          RadioSettingValueList(
                              LIST_TXPOWER,
                              current_index=_mem.vfo.a.txpower))
        work.append(rs)

        rs = RadioSetting("vfo.b.txpower", "VFO B Power",
                          RadioSettingValueList(
                              LIST_TXPOWER,
                              current_index=_mem.vfo.b.txpower))
        work.append(rs)

        rs = RadioSetting("vfo.a.widenarr", "VFO A Bandwidth",
                          RadioSettingValueList(
                              LIST_BANDWIDTH,
                              current_index=_mem.vfo.a.widenarr))
        work.append(rs)

        rs = RadioSetting("vfo.b.widenarr", "VFO B Bandwidth",
                          RadioSettingValueList(
                              LIST_BANDWIDTH,
                              current_index=_mem.vfo.b.widenarr))
        work.append(rs)

        rs = RadioSetting("vfo.a.scode", "VFO A S-CODE",
                          RadioSettingValueList(
                              LIST_SCODE,
                              current_index=_mem.vfo.a.scode))
        work.append(rs)

        rs = RadioSetting("vfo.b.scode", "VFO B S-CODE",
                          RadioSettingValueList(
                              LIST_SCODE,
                              current_index=_mem.vfo.b.scode))
        work.append(rs)

        rs = RadioSetting("vfo.a.step", "VFO A Tuning Step",
                          RadioSettingValueList(
                              LIST_STEP, current_index=_mem.vfo.a.step))
        work.append(rs)
        rs = RadioSetting("vfo.b.step", "VFO B Tuning Step",
                          RadioSettingValueList(
                              LIST_STEP, current_index=_mem.vfo.b.step))
        work.append(rs)

        # broadcast FM settings
        _fm_presets = self._memobj.fm_presets
        if _fm_presets <= 108.0 * 10 - 650:
            preset = _fm_presets / 10.0 + 65
        elif _fm_presets >= 65.0 * 10 and _fm_presets <= 108.0 * 10:
            preset = _fm_presets / 10.0
        else:
            preset = 76.0
        rs = RadioSetting("fm_presets", "FM Preset(MHz)",
                          RadioSettingValueFloat(65, 108.0, preset, 0.1, 1))
        fm_preset.append(rs)

        # DTMF settings
        def apply_code(setting, obj, length):
            code = []
            for j in range(0, length):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code

        for i in range(0, 15):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 5, _code, False)
            val.set_charset(DTMF_CHARS)
            pttid = RadioSetting("pttid/%i.code" % i,
                                 "Signal Code %i" % (i + 1), val)
            pttid.set_apply_callback(apply_code, self._memobj.pttid[i], 5)
            dtmfe.append(pttid)

        if _mem.ani.dtmfon > 0xC3:
            val = 0x03
        else:
            val = _mem.ani.dtmfon
        rs = RadioSetting("ani.dtmfon", "DTMF Speed (on)",
                          RadioSettingValueList(LIST_DTMFSPEED,
                                                current_index=val))
        dtmfe.append(rs)

        if _mem.ani.dtmfoff > 0xC3:
            val = 0x03
        else:
            val = _mem.ani.dtmfoff
        rs = RadioSetting("ani.dtmfoff", "DTMF Speed (off)",
                          RadioSettingValueList(LIST_DTMFSPEED,
                                                current_index=val))
        dtmfe.append(rs)

        _codeobj = self._memobj.ani.code
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("ani.code", "ANI Code", val)
        rs.set_apply_callback(apply_code, self._memobj.ani, 5)
        dtmfe.append(rs)

        rs = RadioSetting("ani.aniid", "When to send ANI ID",
                          RadioSettingValueList(LIST_PTTID,
                                                current_index=_mem.ani.aniid))
        dtmfe.append(rs)

        # Service settings
        for index in range(0, 10):
            key = "squelch.sql%i" % (index)
            _obj = self._memobj.squelch
            val = RadioSettingValueInteger(0, 123,
                                           getattr(_obj, "sql%i" % (index)))
            if index == 0:
                val.set_mutable(False)
            name = "Squelch %i" % (index)
            rs = RadioSetting(key, name, val)
            service.append(rs)

        return top

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) in (0x2008, 0x2010):
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False
