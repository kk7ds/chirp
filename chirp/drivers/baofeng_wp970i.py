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

# Baofeng WP970I magic string
MSTRING_WP970I = b"\x50\xBB\xFF\x20\x14\x04\x13"

# Baofeng UV-9G magic string
MSTRING_UV9G = b"\x50\xBB\xFF\x20\x12\x05\x25"

# Baofeng UV-S9X3 magic string
MSTRING_UVS9X3 = b"\x50\xBB\xFF\x20\x12\x07\x25"


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
LIST_TIMEOUT = ["%s sec" % x for x in range(15, 615, 15)]
LIST_TXPOWER = ["High", "Mid", "Low"]
LIST_VOICE = ["Off", "English", "Chinese"]
LIST_WORKMODE = ["Frequency", "Channel"]

TXP_CHOICES = ["High", "Low"]
TXP_VALUES = [0x00, 0x02]


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if len(data) > 0x2008:
        rid = data[0x2008:0x2010]
        return rid.startswith(cls.MODEL.encode())
    elif len(data) == 0x2008:
        rid = data[0x1EF0:0x1EF7]
        return rid in cls._fileid
    else:
        return False


class WP970I(bfc.BaofengCommonHT):
    """Baofeng WP970I"""
    VENDOR = "Baofeng"
    MODEL = "WP970I"

    _tri_band = False
    _fileid = []
    _magic = [MSTRING_WP970I, ]
    _magic_response_length = 8
    _fw_ver_start = 0x1EF0
    _recv_block_size = 0x40
    _mem_size = 0x2000
    _ack_block = True

    _ranges = [(0x0000, 0x0DF0),
               (0x0E00, 0x1800),
               (0x1EE0, 0x1EF0),
               (0x1F60, 0x1F70),
               (0x1F80, 0x1F90),
               (0x1FC0, 0x1FD0)]
    _send_block_size = 0x10

    MODES = ["NFM", "FM"]
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "!@#$%^&*()+-=[]:\";'<>?,./"
    LENGTH_NAME = 6
    SKIP_VALUES = ["", "S"]
    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Med",  watts=3.00),
                    chirp_common.PowerLevel("Low",  watts=1.00)]
    _vhf_range = (130000000, 180000000)
    _vhf2_range = (200000000, 260000000)
    _uhf_range = (400000000, 521000000)
    VALID_BANDS = [_vhf_range,
                   _uhf_range]
    PTTID_LIST = LIST_PTTID
    SCODE_LIST = LIST_SCODE

    MEM_FORMAT = """
    // #seekto 0x0000;
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
         unknown2:3,
         lowpower:2;
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
      u8 unused1:6,
         aniid:2;
      u8 unknown[2];
      u8 dtmfon;
      u8 dtmfoff;
    } ani;

    #seekto 0x0E20;
    struct {
      u8 squelch;
      u8 step;
      u8 unknown_e22;
      u8 save;
      u8 vox;
      u8 unknown_e25;
      u8 abr;
      u8 tdr;
      u8 beep;
      u8 timeout;
      u8 unknown_e2a[4];
      u8 voice;
      u8 unknown_e2f;
      u8 dtmfst;
      u8 unknown_e31;
      u8 unknown_e32:6,
         screv:2;
      u8 pttid;
      u8 pttlt;
      u8 mdfa;
      u8 mdfb;
      u8 bcl;
      u8 autolk;
      u8 sftd;
      u8 unknown_e3a[3];
      u8 wtled;
      u8 rxled;
      u8 txled;
      u8 almod;
      u8 band;
      u8 tdrab;
      u8 ste;
      u8 rpste;
      u8 rptrl;
      u8 ponmsg;
      u8 roger;
      u8 rogerrx;
      u8 tdrch;
      u8 displayab:1,
         unknown_e4a1:2,
         fmradio:1,
         alarm:1,
         unknown_e4a2:1,
         reset:1,
         menu:1;
      u8 unknown_e4b:6,
         singleptt:1,
         vfomrlock:1;
      u8 workmode;
      u8 keylock;
    } settings;

    #seekto 0x0E76;
    struct {
      u8 unused1:1,
         mrcha:7;
      u8 unused2:1,
         mrchb:7;
    } wmchannel;

    struct vfo {
      u8 unknown0[8];
      u8 freq[8];
      u8 offset[6];
      ul16 rxtone;
      ul16 txtone;
      u8 unused1:7,
         band:1;
      u8 unknown3;
      u8 unused2:2,
         sftd:2,
         scode:4;
      u8 unknown4;
      u8 unused3:1,
         step:3,
         unused4:4;
      u8 unused5:1,
         widenarr:1,
         unused6:4,
         txpower3:2;
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
      u8 unknown1[9];
    } names[128];

    #seekto 0x1ED0;
    struct {
      char line1[7];
      char line2[7];
    } sixpoweron_msg;

    #seekto 0x1EE0;
    struct {
      char line1[7];
      char line2[7];
    } poweron_msg;

    #seekto 0x1EF0;
    struct {
      char line1[7];
      char line2[7];
    } firmware_msg;

    struct squelch {
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
    };

    #seekto 0x1F60;
    struct {
      struct squelch vhf;
      u8 unknown1[6];
      u8 unknown2[16];
      struct squelch uhf;
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
      struct limit vhf2;
    } limits;

    """

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a beta version.\n'
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

    def get_features(self):
        rf = bfc.BaofengCommonHT.get_features(self)
        rf.valid_tuning_steps = STEPS
        return rf

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

        rs = RadioSetting("settings.autolk", "Automatic Key Lock",
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

        val = _mem.settings.almod
        rs = RadioSetting("settings.almod", "Alarm Mode",
                          RadioSettingValueList(
                              LIST_ALMOD, current_index=val))
        basic.append(rs)

        if _mem.settings.tdrab > 0x02:
            val = 0x00
        else:
            val = _mem.settings.tdrab
        rs = RadioSetting("settings.tdrab", "Dual Watch TX Priority",
                          RadioSettingValueList(
                              LIST_OFFAB, current_index=val))
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
        val = RadioSettingValueString(0, 7, _filter(_msg.line1))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line1", "Firmware Message 1", val)
        other.append(rs)

        val = RadioSettingValueString(0, 7, _filter(_msg.line2))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line2", "Firmware Message 2", val)
        other.append(rs)

        _msg = _mem.sixpoweron_msg
        val = RadioSettingValueString(0, 7, _filter(_msg.line1))
        val.set_mutable(False)
        rs = RadioSetting("sixpoweron_msg.line1", "6+Power-On Message 1", val)
        other.append(rs)
        val = RadioSettingValueString(0, 7, _filter(_msg.line2))
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

        lower = 130
        upper = 179
        rs = RadioSetting("limits.vhf.lower", "VHF Lower Limit (MHz)",
                          RadioSettingValueInteger(
                              lower, upper, _mem.limits.vhf.lower))
        other.append(rs)

        rs = RadioSetting("limits.vhf.upper", "VHF Upper Limit (MHz)",
                          RadioSettingValueInteger(
                              lower, upper, _mem.limits.vhf.upper))
        other.append(rs)

        if self._tri_band:
            lower = 200
            upper = 260
            rs = RadioSetting("limits.vhf2.lower", "VHF2 Lower Limit (MHz)",
                              RadioSettingValueInteger(
                                  lower, upper, _mem.limits.vhf2.lower))
            other.append(rs)

            rs = RadioSetting("limits.vhf2.upper", "VHF2 Upper Limit (MHz)",
                              RadioSettingValueInteger(
                                  lower, upper, _mem.limits.vhf2.upper))
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
            value = chirp_common.parse_freq(value)
            msg = ("Can't be less than %i.0000")
            if value > 99000000 and value < 130 * 1000000:
                raise InvalidValueError(msg % (130))
            msg = ("Can't be between %i.9975-%i.0000")
            if (179 + 1) * 1000000 <= value and value < 400 * 1000000:
                raise InvalidValueError(msg % (179, 400))
            msg = ("Can't be greater than %i.9975")
            if value > 99000000 and value > (520 + 1) * 1000000:
                raise InvalidValueError(msg % (520))
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

        def apply_txpower_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(
                      setting.value) + " from list")
            val = str(setting.value)
            index = TXP_CHOICES.index(val)
            val = TXP_VALUES[index]
            obj.set_value(val)

        if self._tri_band:
            if _mem.vfo.a.txpower3 in TXP_VALUES:
                idx = TXP_VALUES.index(_mem.vfo.a.txpower3)
            else:
                idx = TXP_VALUES.index(0x00)
            rs = RadioSettingValueList(TXP_CHOICES, current_index=idx)
            rset = RadioSetting("vfo.a.txpower3", "VFO A Power", rs)
            rset.set_apply_callback(apply_txpower_listvalue,
                                    _mem.vfo.a.txpower3)
            work.append(rset)

            if _mem.vfo.b.txpower3 in TXP_VALUES:
                idx = TXP_VALUES.index(_mem.vfo.b.txpower3)
            else:
                idx = TXP_VALUES.index(0x00)
            rs = RadioSettingValueList(TXP_CHOICES, current_index=idx)
            rset = RadioSetting("vfo.b.txpower3", "VFO B Power", rs)
            rset.set_apply_callback(apply_txpower_listvalue,
                                    _mem.vfo.b.txpower3)
            work.append(rset)
        else:
            rs = RadioSetting(
                "vfo.a.txpower3", "VFO A Power",
                RadioSettingValueList(
                    LIST_TXPOWER, current_index=min(
                        _mem.vfo.a.txpower3, 0x02)))
            work.append(rs)

            rs = RadioSetting(
                "vfo.b.txpower3", "VFO B Power",
                RadioSettingValueList(
                    LIST_TXPOWER, current_index=min(
                        _mem.vfo.b.txpower3, 0x02)))
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
        value = self._memobj.fm_presets
        value_shifted = ((value & 0x00FF) << 8) | ((value & 0xFF00) >> 8)
        if value_shifted >= 65.0 * 10 and value_shifted <= 108.0 * 10:
            # storage method 3 (discovered 2022)
            self._bw_shift = True
            preset = value_shifted / 10.0
        elif value >= 65.0 * 10 and value <= 108.0 * 10:
            # storage method 2
            preset = value / 10.0
        elif value <= 108.0 * 10 - 650:
            # original storage method (2012)
            preset = value / 10.0 + 65
        else:
            # unknown (undiscovered method or no FM chip?)
            preset = False
        if preset:
            rs = RadioSettingValueFloat(65, 108.0, preset, 0.1, 1)
            rset = RadioSetting("fm_presets", "FM Preset(MHz)", rs)
            fm_preset.append(rset)

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
        for band in ["vhf", "uhf"]:
            for index in range(0, 10):
                key = "squelch.%s.sql%i" % (band, index)
                if band == "vhf":
                    _obj = self._memobj.squelch.vhf
                elif band == "uhf":
                    _obj = self._memobj.squelch.uhf
                val = RadioSettingValueInteger(0, 123,
                                               getattr(
                                                   _obj, "sql%i" % (index)))
                if index == 0:
                    val.set_mutable(False)
                name = "%s Squelch %i" % (band.upper(), index)
                rs = RadioSetting(key, name, val)
                service.append(rs)

        return top

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) in [0x2008, 0x2010]:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False


class RH5XAlias(chirp_common.Alias):
    VENDOR = "Rugged"
    MODEL = "RH5X"


class UV82IIIAlias(chirp_common.Alias):
    VENDOR = "Baofeng"
    MODEL = "UV-82III"


class UV9RPROAlias(chirp_common.Alias):
    VENDOR = "Baofeng"
    MODEL = "UV-9R Pro"


@directory.register
class BFA58(WP970I):
    """Baofeng BF-A58"""
    VENDOR = "Baofeng"
    MODEL = "BF-A58"
    LENGTH_NAME = 7
    ALIASES = [RH5XAlias, UV9RPROAlias]

    _fileid = ["BFT515 ", "BFT517 "]


@directory.register
class UV82WP(WP970I):
    """Baofeng UV82-WP"""
    VENDOR = "Baofeng"
    MODEL = "UV-82WP"


@directory.register
class GT3WP(WP970I):
    """Baofeng GT-3WP"""
    VENDOR = "Baofeng"
    MODEL = "GT-3WP"
    LENGTH_NAME = 7


@directory.register
class RT6(WP970I):
    """Retevis RT6"""
    VENDOR = "Retevis"
    MODEL = "RT6"


@directory.register
class BFA58S(WP970I):
    VENDOR = "Baofeng"
    MODEL = "BF-A58S"
    LENGTH_NAME = 7
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]
    ALIASES = [UV82IIIAlias]
    _tri_band = True

    def get_features(self):
        rf = WP970I.get_features(self)
        rf.valid_bands = [self._vhf_range,
                          self._vhf2_range,
                          self._uhf_range]
        return rf


@directory.register
class UVS9X3(BFA58S):
    VENDOR = "Baofeng"
    MODEL = "UV-S9X3"
    ALIASES = []
    _magic = [MSTRING_UVS9X3, ]


@directory.register
class BF5RXRadio(BFA58S):
    VENDOR = "Baofeng"
    MODEL = "5RX"
    ALIASES = []
    _magic = [MSTRING_UVS9X3, ]

    _air_range = (108000000, 136000000)
    _vhf_range = (136000000, 174000000)
    _vhf2_range = (200000000, 260000000)
    _uhf2_range = (350000000, 390000000)
    _uhf_range = (400000000, 520000000)

    def get_features(self):
        rf = WP970I.get_features(self)
        rf.valid_bands = [self._air_range,
                          self._vhf_range,
                          self._vhf2_range,
                          self._uhf2_range,
                          self._uhf_range]
        return rf


@directory.register
class UV9R(WP970I):
    """Baofeng UV-9R"""
    VENDOR = "Baofeng"
    MODEL = "UV-9R"
    LENGTH_NAME = 7


@directory.register
class UV9G(WP970I):
    """Baofeng UV-9G"""
    VENDOR = "Baofeng"
    MODEL = "UV-9G"
    LENGTH_NAME = 7

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Med",  watts=1.00),
                    chirp_common.PowerLevel("Low",  watts=0.50)]
    _magic = [MSTRING_UV9G, ]
    _gmrs = False  # sold as GMRS radio but supports full band TX/RX

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False
