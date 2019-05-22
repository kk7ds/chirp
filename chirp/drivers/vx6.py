# Copyright 2010 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings
from chirp.settings import RadioSettingValueString, RadioSettingValueList
from chirp.settings import RadioSettingValueBoolean
from textwrap import dedent
import re

# flags.{even|odd}_pskip: These are actually "preferential *scan* channels".
# Is that what they mean on other radios as well?

# memory {
#   step_changed: Channel step has been changed. Bit stays on even after
#                 you switch back to default step. Don't know why you would
#                 care
#   half_deviation: 2.5 kHz deviation
#   cpu_shifted:  CPU freq has been shifted (to move a birdie out of channel)
#   power:        0-3: ["L1", "L2", "L3", "Hi"]
#   pager:        Set if this is a paging memory
#   tmodes:       0-7: ["", "Tone", "TSQL", "DTCS", "Rv Tn", "D Code",
#                       "T DCS", "D Tone"]
#                      Rv Tn: Reverse CTCSS - mutes receiver on tone
#                      The final 3 are for split:
#                      D Code: DCS Encode only
#                      T DCS:  Encodes tone, decodes DCS code
#                      D Tone: Encodes DCS code, decodes tone
# }
MEM_FORMAT = """
#seekto 0x010A;
struct {
  u8 auto_power_off;
  u8 arts_beep;
  u8 bell;
  u8 beep_level;
  u8 arts_cwid_alpha[16];
  u8 unk1[2];
  u8 channel_counter_width;
  u8 lcd_dimmer;
  u8 last_dtmf;
  u8 unk2;
  u8 internet_code;
  u8 last_internet_dtmf;
  u8 unk3[3];
  u8 emergency;
  u8 unk4[16];
  u8 lamp;
  u8 lock;
  u8 unk5;
  u8 mic_gain;
  u8 unk6[2];
  u8 on_timer;
  u8 open_message_mode;
  u8 open_message[6];
  u8 unk7;
  u8 unk8:6,
     pager_answer_back:1,
     unk9:1;
  u8 pager_rx_tone1;
  u8 pager_rx_tone2;
  u8 pager_tx_tone1;
  u8 pager_tx_tone2;
  u8 password[4];
  u8 ptt_delay;
  u8 rf_squelch;
  u8 rx_save;
  u8 resume;
  u8 unk10[5];
  u8 tx_timeout;
  u8 wakeup;
  u8 vfo_mode:1,
     arts_cwid:1,
     scan_lamp:1,
     ts_speed:1,
     unk11:1,
     beep:1,
     unk12:1,
     dtmf_autodial:1;
  u8 busy_led:1,
     tone_search_mute:1,
     int_autodial:1,
     bclo:1,
     edge_beep:1,
     unk13:1,
     dmr_wrt:1,
     tx_saver:1;
  u8 unk14:2,
     smart_search:1,
     unk15:3,
     home_rev:1,
     moni_tcall:1;
  u8 unk16:3,
     arts_interval:1,
     unk17:3,
     memory_method:1;
  u8 unk18:2,
     internet_mode:1,
     wx_alert:1,
     unk19:1,
     att:1,
     unk20:2;
} settings;

#seekto 0x018A;
struct {
  u16 in_use;
} bank_used[24];

#seekto 0x01D8;
u8 clock_shift;

#seekto 0x0214;
u16 banksoff1;

#seekto 0x0248;
u8 lastsetting1;

#seekto 0x0294;
u16 banksoff2;

#seekto 0x0248;
u8 lastsetting2;

#seekto 0x02CA;
struct {
  u8 memory[16];
} dtmf[10];

#seekto 0x03CA;
struct {
  u8 memory[8];
  u8 empty_ff[8];
} internet_dtmf[64];

#seekto 0x097A;
struct {
  u8 name[6];
} bank_names[24];

#seekto 0x0C0A;
struct {
  u16 channels[100];
} banks[24];

#seekto 0x1ECA;
struct {
  u8 even_pskip:1,
     even_skip:1,
     even_valid:1,
     even_masked:1,
     odd_pskip:1,
     odd_skip:1,
     odd_valid:1,
     odd_masked:1;
} flags[500];

#seekto 0x21CA;
struct {
  u8 unknown11:1,
     step_changed:1,
     half_deviation:1,
     cpu_shifted:1,
     unknown12:4;
  u8 mode:2,
     duplex:2,
     tune_step:4;
  bbcd freq[3];
  u8 power:2,
     unknown2:2,
     pager:1,
     tmode:3;
  u8 name[6];
  bbcd offset[3];
  u8 tone;
  u8 dcs;
  u8 unknown5;
} memory[999];
"""

DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "AM", "WFM", "FM"]  # last is auto
TMODES = ["", "Tone", "TSQL", "DTCS"]
DTMFCHARSET = list("0123456789ABCD*#-")
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0,
         9.0, 200.0, 5.0]  # last is auto, 9.0k and 200.0k are unadvertised

CHARSET = ["%i" % int(x) for x in range(10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    list(" +-/\x00[]__" + ("\x00" * 9) + "$%%\x00**.|=\\\x00@") + \
    list("\x00" * 100)

PASS_CHARSET = list("0123456789ABCDEF")

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("L3", watts=2.50),
                chirp_common.PowerLevel("L2", watts=1.00),
                chirp_common.PowerLevel("L1", watts=0.30)]
POWER_LEVELS_220 = [chirp_common.PowerLevel("Hi", watts=1.50),
                    chirp_common.PowerLevel("L3", watts=1.00),
                    chirp_common.PowerLevel("L2", watts=0.50),
                    chirp_common.PowerLevel("L1", watts=0.20)]


class VX6Bank(chirp_common.NamedBank):
    """A VX6 Bank"""
    def get_name(self):
        _bank = self._model._radio._memobj.bank_names[self.index]
        name = ""
        for i in _bank.name:
            if i == 0xFF:
                break
            name += CHARSET[i & 0x7F]
        return name.rstrip()

    def set_name(self, name):
        name = name.upper()
        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = [CHARSET.index(x) for x in name.ljust(6)[:6]]


class VX6BankModel(chirp_common.BankModel):
    """A VX-6 bank model"""

    def get_num_mappings(self):
        return len(self.get_mappings())

    def get_mappings(self):
        banks = self._radio._memobj.banks
        bank_mappings = []
        for index, _bank in enumerate(banks):
            bank = VX6Bank(self, "%i" % index, "b%i" % (index + 1))
            bank.index = index
            bank_mappings.append(bank)

        return bank_mappings

    def _get_channel_numbers_in_bank(self, bank):
        _bank_used = self._radio._memobj.bank_used[bank.index]
        if _bank_used.in_use == 0xFFFF:
            return set()

        _members = self._radio._memobj.banks[bank.index]
        return set([int(ch) + 1 for ch in _members.channels if ch != 0xFFFF])

    def _update_bank_with_channel_numbers(self, bank, channels_in_bank):
        _members = self._radio._memobj.banks[bank.index]
        if len(channels_in_bank) > len(_members.channels):
            raise Exception("Too many entries in bank %d" % bank.index)

        empty = 0
        for index, channel_number in enumerate(sorted(channels_in_bank)):
            _members.channels[index] = channel_number - 1
            empty = index + 1
        for index in range(empty, len(_members.channels)):
            _members.channels[index] = 0xFFFF

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        channels_in_bank.add(memory.number)
        self._update_bank_with_channel_numbers(bank, channels_in_bank)
        _bank_used = self._radio._memobj.bank_used[bank.index]
        _bank_used.in_use = 0x0000  # enable

        # also needed for unit to recognize any banks?
        self._radio._memobj.banksoff1 = 0x0000
        self._radio._memobj.banksoff2 = 0x0000
        # TODO: turn back off (0xFFFF) when all banks are empty?

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        if not channels_in_bank:
            _bank_used = self._radio._memobj.bank_used[bank.index]
            _bank_used.in_use = 0xFFFF  # disable bank

    def get_mapping_memories(self, bank):
        memories = []
        for channel in self._get_channel_numbers_in_bank(bank):
            memories.append(self._radio.get_memory(channel))

        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._get_channel_numbers_in_bank(bank):
                banks.append(bank)

        return banks


@directory.register
class VX6Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-6"""
    BAUD_RATE = 19200
    VENDOR = "Yaesu"
    MODEL = "VX-6"

    _model = "AH021"
    _memsize = 32587
    _block_lengths = [10, 32577]
    _block_size = 16

    _APO = ("OFF", "30 min", "1 hour", "3 hour", "5 hour", "8 hour")
    _ARTSBEEP = ("Off", "In Range", "Always")
    _ARTS_INT = ("15 S", "25 S")
    _BELL = ("OFF", "1", "3", "5", "8", "Continuous")
    _BEEP_LEVEL = ["%i" % int(x) for x in range(1, 10)]
    _CH_CNT = ("5 MHZ", "10 MHZ", "50 MHZ", "100 MHZ")
    _DIM_LEVEL = ["%i" % int(x) for x in range(0, 13)]
    _EMERGENCY = ("Beep", "Strobe", "Bp+Str", "Beam", "Bp+Bem", "CW",
                  "Bp+CW", "CWT")
    _HOME_REV = ("HOME", "REV")
    _INT_CD = ["%i" % int(x) for x in range(0, 10)] + \
        [chr(x) for x in range(ord("A"), ord("F")+1)]
    _INT_MD = ("SRG: Sister Radio Group", "FRG: Friendly Radio Group")
    _LAMP = ("Key", "Continuous", "Off")
    _LOCK = ("Key", "Dial", "Key+Dial", "PTT", "Key+PTT", "Dial+PTT", "All")
    _MAN_AUTO = ("Manual", "Auto")
    _MEM_W_MD = ("Lower", "Next")
    _MONI_TCALL = ("MONI", "T-CALL")
    _NUM_1_9 = ["%i" % int(x) for x in range(1, 10)]
    _NUM_0_9 = ["%i" % int(x) for x in range(10)]
    _NUM_0_63 = ["%i" % int(x) for x in range(64)]
    _NUM_1_50 = ["%i" % int(x) for x in range(1, 51)]
    _ON_TIMER = ["OFF"] + \
        ["%02d:%02d" % (t / 60, t % 60) for t in range(10, 1450, 10)]
    _OPEN_MSG = ("Off", "DC Voltage", "Message")
    _PTT_DELAY = ("OFF", "20MS", "50MS", "100MS", "200MS")
    _RF_SQL = ("OFF", "S1", "S2", "S3", "S4", "S5",
               "S6", "S7", "S8", "S9", "S9+")
    _RX_SAVE = ("OFF", "200 ms", "300 MS", "500 MS", "1 S", "2 S")
    _RESUME = ("3 SEC", "5 SEC", "10 SEC", "BUSY", "HOLD")
    _SMART_SEARCH = ("SINGLE", "CONT")
    _TOT = ("OFF", "1MIN", "3MIN", "5MIN", "10MIN")
    _TS_SPEED = ("FAST", "SLOW")
    _VFO_MODE = ("ALL", "BAND")
    _WAKEUP = ("OFF", "5S", "10S", "20S", "30S", "EAI")

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
1. Turn radio off.
2. Connect cable to MIC/SP jack.
3. Press and hold in the [F/W] key while turning the radio on
     ("CLONE" will appear on the display).
4. <b>After clicking OK</b>, press the [BAND] key to send image."""))
        rp.pre_upload = _(dedent("""\
1. Turn radio off.
2. Connect cable to MIC/SP jack.
3. Press and hold in the [F/W] key while turning the radio on
     ("CLONE" will appear on the display).
4. Press the [V/M] key ("-WAIT-" will appear on the LCD)."""))
        return rp

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, 0x7F49)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = True
        rf.has_bank_names = True
        rf.has_dtcs_polarity = False
        rf.valid_modes = ["FM", "WFM", "AM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = DUPLEX
        rf.valid_tuning_steps = STEPS
        rf.valid_power_levels = POWER_LEVELS
        rf.memory_bounds = (1, 999)
        rf.valid_bands = [(500000, 998990000)]
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_settings = True
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1]) + \
            repr(self._memobj.flags[(number-1)/2])

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        _flg = self._memobj.flags[(number-1)/2]

        nibble = ((number-1) % 2) and "even" or "odd"
        used = _flg["%s_masked" % nibble]
        valid = _flg["%s_valid" % nibble]
        pskip = _flg["%s_pskip" % nibble]
        skip = _flg["%s_skip" % nibble]

        mem = chirp_common.Memory()
        mem.number = number

        if not used:
            mem.empty = True
        if not valid:
            mem.empty = True
            mem.power = POWER_LEVELS[0]
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = chirp_common.fix_rounded_step(int(_mem.offset) * 1000)
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone & 0x3f]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = MODES[_mem.mode]
        if mem.mode == "FM" and _mem.half_deviation:
            mem.mode = "NFM"
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs & 0x7f]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.skip = pskip and "P" or skip and "S" or ""

        if mem.freq > 220000000 and mem.freq < 225000000:
            mem.power = POWER_LEVELS_220[3 - _mem.power]
        else:
            mem.power = POWER_LEVELS[3 - _mem.power]

        for i in _mem.name:
            if i == 0xFF:
                break
            mem.name += CHARSET[i & 0x7F]
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        _flag = self._memobj.flags[(mem.number-1)/2]

        nibble = ((mem.number-1) % 2) and "even" or "odd"
        used = _flag["%s_masked" % nibble]
        valid = _flag["%s_valid" % nibble]

        # initialize new channel to safe defaults
        if not mem.empty and not valid:
            _flag["%s_valid" % nibble] = True
            _mem.unknown11 = 0
            _mem.step_changed = 0
            _mem.cpu_shifted = 0
            _mem.unknown12 = 0
            _mem.unknown2 = 0
            _mem.pager = 0
            _mem.unknown5 = 0

        if mem.empty and valid and not used:
            _flag["%s_valid" % nibble] = False
            return
        _flag["%s_masked" % nibble] = not mem.empty

        if mem.empty:
            return

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        if mem.mode == "NFM":
            _mem.mode = MODES.index("FM")
            _mem.half_deviation = 1
        else:
            _mem.mode = MODES.index(mem.mode)
            _mem.half_deviation = 0
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        if mem.power:
            _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        _mem.name = [0xFF] * 6
        for i in range(0, 6):
            _mem.name[i] = CHARSET.index(mem.name.ljust(6)[i])

        if mem.name.strip():
            _mem.name[0] |= 0x80

    def get_bank_model(self):
        return VX6BankModel(self)

    def _decode_chars(self, inarr):
        outstr = ""
        for i in inarr:
            if i == 0xFF:
                break
            outstr += CHARSET[i & 0x7F]
        return outstr.rstrip()

    def _encode_chars(self, instr, length=16):
        outarr = []
        instr = str(instr)
        for i in range(length):
            if i < len(instr):
                outarr.append(CHARSET.index(instr[i]))
            else:
                outarr.append(0xFF)
        return outarr

    def _get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        arts = RadioSettingGroup("arts", "ARTS")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        wires = RadioSettingGroup("wires", "WIRES")
        misc = RadioSettingGroup("misc", "Misc")
        top = RadioSettings(basic, arts, dtmf, wires, misc)

        # BASIC

        val = RadioSettingValueList(
            self._APO, self._APO[_settings.auto_power_off])
        rs = RadioSetting("auto_power_off", "Auto Power Off", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._BEEP_LEVEL, self._BEEP_LEVEL[_settings.beep_level])
        rs = RadioSetting("beep_level", "Beep Level", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._DIM_LEVEL, self._DIM_LEVEL[_settings.lcd_dimmer])
        rs = RadioSetting("lcd_dimmer", "Dimmer Level", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._LAMP, self._LAMP[_settings.lamp])
        rs = RadioSetting("lamp", "Keypad Lamp", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._LOCK, self._LOCK[_settings.lock])
        rs = RadioSetting("lock", "Lock", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._NUM_1_9, self._NUM_1_9[_settings.mic_gain])
        rs = RadioSetting("mic_gain", "Mic Gain", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._OPEN_MSG, self._OPEN_MSG[_settings.open_message_mode])
        rs = RadioSetting("open_message_mode",
                          "Open Message Mode", val)
        basic.append(rs)

        val = RadioSettingValueString(0, 6,
                                      self._decode_chars(
                                          _settings.open_message))
        val.set_charset(CHARSET)
        rs = RadioSetting("open_message", "Opening Message", val)
        basic.append(rs)

        passstr = ""
        for c in _settings.password:
            if c < len(PASS_CHARSET):
                passstr += PASS_CHARSET[c]
        val = RadioSettingValueString(0, 4, passstr)
        val.set_charset(PASS_CHARSET)
        rs = RadioSetting("password", "Password", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._RESUME, self._RESUME[_settings.resume])
        rs = RadioSetting("resume", "Scan Resume", val)
        basic.append(rs)

        val = RadioSettingValueList(
            self._MONI_TCALL, self._MONI_TCALL[_settings.moni_tcall])
        rs = RadioSetting("moni_tcall", "MONI/T-CALL switch", val)
        basic.append(rs)

        rs = RadioSetting("scan_lamp", "Scan Lamp",
                          RadioSettingValueBoolean(_settings.scan_lamp))
        basic.append(rs)

        rs = RadioSetting("beep", "Keypad Beep",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting("busy_led", "Busy LED",
                          RadioSettingValueBoolean(_settings.busy_led))
        basic.append(rs)

        rs = RadioSetting("bclo", "Busy Channel Lock-Out",
                          RadioSettingValueBoolean(_settings.bclo))
        basic.append(rs)

        rs = RadioSetting("wx_alert", "WX Alert",
                          RadioSettingValueBoolean(_settings.wx_alert))
        basic.append(rs)

        rs = RadioSetting("att", "Attenuator",
                          RadioSettingValueBoolean(_settings.att))
        basic.append(rs)

        # ARTS

        val = RadioSettingValueList(
            self._ARTS_INT, self._ARTS_INT[_settings.arts_interval])
        rs = RadioSetting("arts_interval", "ARTS Interval", val)
        arts.append(rs)

        val = RadioSettingValueList(
            self._ARTSBEEP, self._ARTSBEEP[_settings.arts_beep])
        rs = RadioSetting("arts_beep", "ARTS Beep", val)
        arts.append(rs)

        rs = RadioSetting("arts_cwid", "ARTS Send CWID",
                          RadioSettingValueBoolean(_settings.arts_cwid))
        arts.append(rs)

        val = RadioSettingValueString(0, 16,
                                      self._decode_chars(
                                          _settings.arts_cwid_alpha))
        val.set_charset(CHARSET)
        rs = RadioSetting("arts_cwid_alpha", "ARTS CW ID", val)
        arts.append(rs)

        # DTMF

        val = RadioSettingValueList(
            self._MAN_AUTO, self._MAN_AUTO[_settings.dtmf_autodial])
        rs = RadioSetting("dtmf_autodial", "DTMF Autodial", val)
        dtmf.append(rs)

        val = RadioSettingValueList(
            self._NUM_0_9, self._NUM_0_9[_settings.last_dtmf])
        rs = RadioSetting("last_dtmf", "Last DTMF Memory Set", val)
        dtmf.append(rs)

        for i in range(10):
            name = "dtmf_" + str(i)
            dtmfsetting = self._memobj.dtmf[i]
            dtmfstr = ""
            for c in dtmfsetting.memory:
                if c < len(DTMFCHARSET):
                    dtmfstr += DTMFCHARSET[c]
            dtmfentry = RadioSettingValueString(0, 16, dtmfstr)
            rs = RadioSetting(name, name.upper(), dtmfentry)
            dtmf.append(rs)

        # WIRES

        val = RadioSettingValueList(
            self._INT_CD, self._INT_CD[_settings.internet_code])
        rs = RadioSetting("internet_code", "Internet Code", val)
        wires.append(rs)

        val = RadioSettingValueList(
            self._INT_MD, self._INT_MD[_settings.internet_mode])
        rs = RadioSetting("internet_mode",
                          "Internet Link Connection mode", val)
        wires.append(rs)

        val = RadioSettingValueList(
            self._MAN_AUTO, self._MAN_AUTO[_settings.int_autodial])
        rs = RadioSetting("int_autodial", "Internet Autodial", val)
        wires.append(rs)

        val = RadioSettingValueList(
            self._NUM_0_63, self._NUM_0_63[_settings.last_internet_dtmf])
        rs = RadioSetting("last_internet_dtmf",
                          "Last Internet DTMF Memory Set", val)
        wires.append(rs)

        for i in range(64):
            name = "wires_dtmf_" + str(i)
            dtmfsetting = self._memobj.internet_dtmf[i]
            dtmfstr = ""
            for c in dtmfsetting.memory:
                if c < len(DTMFCHARSET):
                    dtmfstr += DTMFCHARSET[c]
            dtmfentry = RadioSettingValueString(0, 8, dtmfstr)
            rs = RadioSetting(name, name.upper(), dtmfentry)
            wires.append(rs)

        # MISC

        val = RadioSettingValueList(
            self._BELL, self._BELL[_settings.bell])
        rs = RadioSetting("bell", "CTCSS/DCS Bell", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._CH_CNT, self._CH_CNT[_settings.channel_counter_width])
        rs = RadioSetting("channel_counter_width",
                          "Channel Counter Search Width", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._EMERGENCY, self._EMERGENCY[_settings.emergency])
        rs = RadioSetting("emergency", "Emergency alarm", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._ON_TIMER, self._ON_TIMER[_settings.on_timer])
        rs = RadioSetting("on_timer", "On Timer", val)
        misc.append(rs)

        rs = RadioSetting("pager_answer_back", "Pager Answer Back",
                          RadioSettingValueBoolean(
                              _settings.pager_answer_back))
        misc.append(rs)

        val = RadioSettingValueList(
            self._NUM_1_50, self._NUM_1_50[_settings.pager_rx_tone1])
        rs = RadioSetting("pager_rx_tone1", "Pager RX Tone 1", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._NUM_1_50, self._NUM_1_50[_settings.pager_rx_tone2])
        rs = RadioSetting("pager_rx_tone2", "Pager RX Tone 2", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._NUM_1_50, self._NUM_1_50[_settings.pager_tx_tone1])
        rs = RadioSetting("pager_tx_tone1", "Pager TX Tone 1", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._NUM_1_50, self._NUM_1_50[_settings.pager_tx_tone2])
        rs = RadioSetting("pager_tx_tone2", "Pager TX Tone 2", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._PTT_DELAY, self._PTT_DELAY[_settings.ptt_delay])
        rs = RadioSetting("ptt_delay", "PTT Delay", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._RF_SQL, self._RF_SQL[_settings.rf_squelch])
        rs = RadioSetting("rf_squelch", "RF Squelch", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._RX_SAVE, self._RX_SAVE[_settings.rx_save])
        rs = RadioSetting("rx_save", "RX Save", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._TOT, self._TOT[_settings.tx_timeout])
        rs = RadioSetting("tx_timeout", "TOT", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._WAKEUP, self._WAKEUP[_settings.wakeup])
        rs = RadioSetting("wakeup", "Wakeup", val)
        misc.append(rs)

        rs = RadioSetting("edge_beep", "Band-Edge Beep",
                          RadioSettingValueBoolean(_settings.edge_beep))
        misc.append(rs)

        val = RadioSettingValueList(
            self._VFO_MODE, self._VFO_MODE[_settings.vfo_mode])
        rs = RadioSetting("vfo_mode", "VFO Band Edge Limiting", val)
        misc.append(rs)

        rs = RadioSetting("tone_search_mute", "Tone Search Mute",
                          RadioSettingValueBoolean(_settings.tone_search_mute))
        misc.append(rs)

        val = RadioSettingValueList(
            self._TS_SPEED, self._TS_SPEED[_settings.ts_speed])
        rs = RadioSetting("ts_speed", "Tone Search Speed", val)
        misc.append(rs)

        rs = RadioSetting("dmr_wrt", "Direct Memory Recall Overwrite",
                          RadioSettingValueBoolean(_settings.dmr_wrt))
        misc.append(rs)

        rs = RadioSetting("tx_saver", "TX Battery Saver",
                          RadioSettingValueBoolean(_settings.tx_saver))
        misc.append(rs)

        val = RadioSettingValueList(
            self._SMART_SEARCH, self._SMART_SEARCH[_settings.smart_search])
        rs = RadioSetting("smart_search", "Smart Search", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._HOME_REV, self._HOME_REV[_settings.home_rev])
        rs = RadioSetting("home_rev", "HM/RV(EMG)R/H key", val)
        misc.append(rs)

        val = RadioSettingValueList(
            self._MEM_W_MD, self._MEM_W_MD[_settings.memory_method])
        rs = RadioSetting("memory_method", "Memory Write Method", val)
        misc.append(rs)

        return top

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            pring(traceback.format_exc())
            return None

    def set_settings(self, uisettings):
        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                setting = element.get_name()
                _settings = self._memobj.settings
                if re.match('internet_dtmf_\d', setting):
                    # set dtmf fields
                    dtmfstr = str(element.value).strip()
                    newval = []
                    for i in range(0, 8):
                        if i < len(dtmfstr):
                            newval.append(DTMFCHARSET.index(dtmfstr[i]))
                        else:
                            newval.append(0xFF)
                    idx = int(setting[-1:])
                    _settings = self._memobj.internet_dtmf[idx]
                    _settings.memory = newval
                    continue
                elif re.match('dtmf_\d', setting):
                    # set dtmf fields
                    dtmfstr = str(element.value).strip()
                    newval = []
                    for i in range(0, 16):
                        if i < len(dtmfstr):
                            newval.append(DTMFCHARSET.index(dtmfstr[i]))
                        else:
                            newval.append(0xFF)
                    idx = int(setting[-1:])
                    _settings = self._memobj.dtmf[idx]
                    _settings.memory = newval
                    continue
                oldval = getattr(_settings, setting)
                newval = element.value
                if setting == "arts_cwid_alpha":
                    newval = self._encode_chars(newval)
                elif setting == "open_message":
                    newval = self._encode_chars(newval, 6)
                elif setting == "password":
                    newval = self._encode_chars(newval, 4)
                setattr(_settings, setting, newval)
            except Exception, e:
                raise
