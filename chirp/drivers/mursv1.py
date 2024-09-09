# Copyright 2018:
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

from chirp.drivers import baofeng_common
from chirp import chirp_common, directory
from chirp import bitwise
from chirp import bandplan_na
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings

LOG = logging.getLogger(__name__)

# #### MAGICS #########################################################

# BTECH MURS-V1 magic string
MSTRING_MURSV1 = b"\x50\x5F\x20\x15\x12\x15\x4D"

# #### ID strings #####################################################

# BTECH MURS-V1
MURSV1_fp1 = b"USM2402"

DTMF_CHARS = "0123456789 *#ABCD"

LIST_AB = ["A", "B"]
LIST_ALMOD = ["Off", "Site", "Tone", "Code"]
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
LIST_RTONE = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SHIFTD = ["Off", "+", "-"]
LIST_STEDELAY = ["Off"] + ["%s ms" % x for x in range(100, 1100, 100)]
LIST_TIMEOUT = ["%s sec" % x for x in range(15, 615, 15)]
LIST_TXPOWER = ["High", "Low"]
LIST_VOICE = ["Off", "English", "Chinese"]
LIST_WORKMODE = ["Frequency", "Channel"]

MURS_FREQS = bandplan_na.ALL_MURS_FREQS * 3


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x1EF0:0x1EF7]

    if rid in cls._fileid:
        return True

    return False


@directory.register
class MURSV1(baofeng_common.BaofengCommonHT):
    """BTech MURS-V1"""
    VENDOR = "BTECH"
    MODEL = "MURS-V1"

    _fileid = [MURSV1_fp1, ]

    _magic = [MSTRING_MURSV1, ]
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
    LENGTH_NAME = 7
    SKIP_VALUES = ["", "S"]
    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=.50)]
    VALID_BANDS = [(151820000, 154600250)]
    PTTID_LIST = LIST_PTTID
    SCODE_LIST = LIST_SCODE

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = False
        rf.has_name = True
        rf.has_offset = False
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_name_length = self.LENGTH_NAME
        rf.valid_duplexes = []
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_skips = self.SKIP_VALUES
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (1, 15)
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = self.VALID_BANDS

        return rf

    MEM_FORMAT = """
    #seekto 0x0010;
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
    } memory[15];

    #seekto 0x0B00;
    struct {
      u8 code[5];
      u8 unused[11];
    } pttid[15];

    #seekto 0x0C80;
    struct {
      u8 unknown222[5];
      u8 unknown333[5];
      u8 alarm[5];
      u8 unknown1;
      u8 unknown555[5];
      u8 unknown666[5];
      u8 unknown777[5];
      u8 unknown2;
      u8 unknown60606[5];
      u8 unknown70707[5];
      u8 code[5];
      u8 unused1:6,
         aniid:2;
      u8 unknown[2];
      u8 dtmfon;
      u8 dtmfoff;
    } ani;

    #seekto 0x0E20;
    struct {
      u8 unused01:4,
         squelch:4;
      u8 unused02;
      u8 unused03;
      u8 unused04:5,
         save:3;
      u8 unused05:4,
         vox:4;
      u8 unused06;
      u8 unused07:4,
         abr:4;
      u8 unused08:7,
         tdr:1;
      u8 unused09:7,
         beep:1;
      u8 unused10:2,
         timeout:6;
      u8 unused11[4];
      u8 unused12:6,
         voice:2;
      u8 unused13;
      u8 unused14:6,
         dtmfst:2;
      u8 unused15;
      u8 unused16:6,
         screv:2;
      u8 unused17:6,
         pttid:2;
      u8 unused18:2,
         pttlt:6;
      u8 unused19:6,
         mdfa:2;
      u8 unused20:6,
         mdfb:2;
      u8 unused21;
      u8 unused22:7,
         sync:1;
      u8 unused23[4];
      u8 unused24:6,
         wtled:2;
      u8 unused25:6,
         rxled:2;
      u8 unused26:6,
         txled:2;
      u8 unused27:6,
         almod:2;
      u8 unused28:7,
         dbptt:1;
      u8 unused29:6,
         tdrab:2;
      u8 unused30:7,
         ste:1;
      u8 unused31:4,
         rpste:4;
      u8 unused32:4,
         rptrl:4;
      u8 unused33:7,
         ponmsg:1;
      u8 unused34:7,
         roger:1;
      u8 unused35:6,
         rtone:2;
      u8 unused36;
      u8 unused37:6,
         rogerrx:2;
      u8 unused38;
      u8 displayab:1,
         unknown1:2,
         fmradio:1,
         alarm:1,
         unknown2:1,
         reset:1,
         menu:1;
      u8 unused39;
      u8 workmode;
      u8 keylock;
      u8 cht;
    } settings;

    #seekto 0x0E76;
    struct {
      u8 unused1:1,
         mrcha:7;
      u8 unused2:1,
         mrchb:7;
    } wmchannel;

    #seekto 0x0F4E;
    u16 fm_presets;

    #seekto 0x1010;
    struct {
      char name[7];
      u8 unknown1[9];
    } names[15];

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
    } squelch;

    """

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('The BTech MURS-V1 driver is a beta version.\n'
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

    def _get_mem(self, number):
        return self._memobj.memory[number - 1]

    def _get_nam(self, number):
        return self._memobj.names[number - 1]

    def get_memory(self, number):
        _mem = self._get_mem(number)
        _nam = self._get_nam(number)

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:1] == b"\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "  # The OEM software may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = self.DTCS_CODES[index]
        else:
            LOG.warn("Bug: txtone is %04x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.rx_dtcs = self.DTCS_CODES[index]
        else:
            LOG.warn("Bug: rxtone is %04x" % _mem.rxtone)

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        levels = self.POWER_LEVELS
        try:
            mem.power = levels[_mem.lowpower]
        except IndexError:
            LOG.error("Radio reported invalid power level %s (in %s)" %
                      (_mem.power, levels))
            mem.power = levels[0]

        mem.mode = _mem.wide and "FM" or "NFM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(self.PTTID_LIST,
                                                current_index=_mem.pttid))
        mem.extra.append(rs)

        rs = RadioSetting("scode", "S-CODE",
                          RadioSettingValueList(self.SCODE_LIST,
                                                current_index=_mem.scode))
        mem.extra.append(rs)

        immutable = []

        if mem.freq in MURS_FREQS:
            if mem.number >= 1 and mem.number <= 15:
                MURS_FREQ = MURS_FREQS[mem.number - 1]
                mem.freq = MURS_FREQ
                mem.duplex == ''
                mem.offset = 0
                immutable = ["empty", "freq", "duplex", "offset"]
            if mem.freq in bandplan_na.MURS_NFM:
                mem.mode = "NFM"
                immutable += ["mode"]

        mem.immutable = immutable

        return mem

    def _set_mem(self, number):
        return self._memobj.memory[number - 1]

    def _set_nam(self, number):
        return self._memobj.names[number - 1]

    def set_memory(self, mem):
        _mem = self._set_mem(mem.number)
        _nam = self._set_nam(mem.number)

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

        _mem.set_raw("\x00" * 16)

        _mem.rxfreq = mem.freq / 10

        _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = self.DTCS_CODES.index(mem.dtcs) + 1
            _mem.rxtone = self.DTCS_CODES.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = self.DTCS_CODES.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = self.DTCS_CODES.index(mem.rx_dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "FM"

        if mem.power:
            _mem.lowpower = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.lowpower = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                setattr(_mem, setting.get_name(), setting.value)
        else:
            # there are no extra settings, load defaults
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.scode = 0

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

        if _mem.settings.pttlt > 0x32:
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

        rs = RadioSetting("settings.sync", "Sync A & B",
                          RadioSettingValueBoolean(_mem.settings.sync))
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

        rs = RadioSetting("settings.dbptt", "Double PTT",
                          RadioSettingValueBoolean(_mem.settings.dbptt))
        basic.append(rs)

        rs = RadioSetting("settings.ste", "Squelch Tail Eliminate (HT to HT)",
                          RadioSettingValueBoolean(_mem.settings.ste))
        basic.append(rs)

        rs = RadioSetting(
            "settings.ponmsg", "Power-On Message",
            RadioSettingValueList(
                LIST_PONMSG, current_index=_mem.settings.ponmsg))
        basic.append(rs)

        rs = RadioSetting("settings.roger", "Roger Beep",
                          RadioSettingValueBoolean(_mem.settings.roger))
        basic.append(rs)

        rs = RadioSetting(
            "settings.rtone", "Tone Burst Frequency",
            RadioSettingValueList(
                LIST_RTONE, current_index=_mem.settings.rtone))
        basic.append(rs)

        rs = RadioSetting("settings.rogerrx", "Roger Beep (RX)",
                          RadioSettingValueList(
                             LIST_OFFAB, current_index=_mem.settings.rogerrx))
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

        # Work mode settings
        rs = RadioSetting("settings.displayab", "Display",
                          RadioSettingValueList(
                              LIST_AB, current_index=_mem.settings.displayab))
        work.append(rs)

        rs = RadioSetting("settings.keylock", "Keypad Lock",
                          RadioSettingValueBoolean(_mem.settings.keylock))
        work.append(rs)

        rs = RadioSetting("wmchannel.mrcha", "MR A Channel",
                          RadioSettingValueInteger(1, 15,
                                                   _mem.wmchannel.mrcha))
        work.append(rs)

        rs = RadioSetting("wmchannel.mrchb", "MR B Channel",
                          RadioSettingValueInteger(1, 15,
                                                   _mem.wmchannel.mrchb))
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

        def apply_alarmcode(setting, obj, length):
            code = []
            for j in range(0, length):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.alarm = code

        _codeobj = self._memobj.ani.alarm
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("ani.alarm", "Alarm Code", val)
        rs.set_apply_callback(apply_alarmcode, self._memobj.ani, 5)
        dtmfe.append(rs)

        # Service settings
        for index in range(0, 10):
            key = "squelch.vhf.sql%i" % (index)
            _obj = self._memobj.squelch.vhf
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
        if len(filedata) == 0x2008:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False
