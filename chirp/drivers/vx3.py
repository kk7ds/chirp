# Copyright 2011 Rick Farina <sidhayn@gmail.com>
#     based on modification of Dan Smith's original work
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

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
from textwrap import dedent
import os
import re
import logging

LOG = logging.getLogger(__name__)

# interesting offsets which may be checksums needed later
# 0x0393 checksum1?
# 0x0453 checksum1a?
# 0x0409 checksum2?
# 0x04C9 checksum2a?

MEM_FORMAT = """
#seekto 0x7F4A;
u8 checksum;

#seekto 0x024A;
struct {
    u8  unk01_1:3,
        att_broadcast:1,
        att_marine:1,
        unk01_2:2
        att_wx:1;
    u8  unk02;
    u8  apo;
    u8  arts_beep;
    u8  unk04_1;
    u8  beep_level;
    u8  beep_mode;
    u8  unk04_2;
    u8  arts_cwid[16];
    u8  unk05[10];
    u8  channel_counter;
    u8  unk06_1[2];
    u8  dtmf_delay;
    u8  dtmf_chan_active;
    u8  unk06_2[5];
    u8  emergency_eai_time;
    u8  emergency_signal;
    u8  unk07[30];
    u8  fw_key_timer;
    u8  internet_key;
    u8  lamp;
    u8  lock_mode;
    u8  my_key;
    u8  mic_gain;
    u8  mem_ch_step;
    u8  unk08[3];
    u8  sql_fm;
    u8  sql_wfm;
    u8  radio_am_sql;
    u8  radio_fm_sql;
    u8  on_timer;
    u8  openmsg_mode;
    u8  openmsg[6];
    u8  pager_rxtone1;
    u8  pager_rxtone2;
    u8  pager_txtone1;
    u8  pager_txtone2;
    u8  password[4];
    u8  unk10;
    u8  priority_time;
    u8  ptt_delay;
    u8  rx_save;
    u8  scan_resume;
    u8  scan_restart;
    u8  sub_rx_timer;
    u8  unk11[7];
    u8  tot;
    u8  wake_up;
    u8  unk12[2];
    u8  vfo_mode:1,
        arts_cwid_enable:1,
        scan_lamp:1,
        fast_tone_search:1,
        ars:1,
        dtmf_speed:1,
        split_tone:1,
        dtmf_autodialer:1;
    u8  busy_led:1,
        tone_search_mute:1,
        unk14_1:1,
        bclo:1,
        band_edge_beep:1,
        unk14_2:2,
        txsave:1;
    u8  unk15_1:2,
        smart_search:1,
        emergency_eai:1,
        unk15_2:2,
        hm_rv:1,
        moni_tcall:1;
    u8  lock:1,
        unk16_1:1,
        arts:1,
        arts_interval:1,
        unk16_2:1,
        protect_memory:1,
        unk16_3:1,
        mem_storage:1;
    u8  vol_key_mode:1,
        unk17_1:2,
        wx_alert:1,
        temp_unit:1,
        unk17_2:2,
        password_active:1;
    u8  fm_broadcast_mode:1,
        fm_antenna:1,
        am_antenna:1,
        fm_speaker_out:1,
        home_vfo:1,
        unk18_1:2,
        priority_revert:1;
}   settings;

// banks?
#seekto 0x034D;
u8  banks_unk1;

#seekto 0x0356;
struct {
    u32 unmask;
} banks_unmask1;

#seekto 0x0409;
u8  banks_unk3;

#seekto 0x0416;
struct {
    u32 unmask;
} banks_unmask2;

#seekto 0x04CA;
struct {
    u8    memory[16];
}   dtmf[10];

#seekto 0x0B7A;
struct {
  u8 name[6];
} bank_names[24];

#seekto 0x0E0A;
struct {
  u16 channels[100];
} banks[24];

#seekto 0x02EE;
struct {
    u16 in_use;
} bank_used[24];

#seekto 0x03FE;
struct {
    u8  speaker;
    u8  earphone;
}   volumes;

#seekto 0x20CA;
struct {
  u8 even_pskip:1,
     even_skip:1,
     even_valid:1,  // TODO: should be "showname", i.e., show alpha name
     even_masked:1,
     odd_pskip:1,
     odd_skip:1,
     odd_valid:1,
     odd_masked:1;
} flags[999];

#seekto 0x244A;
struct {
  u8   unknown1a:2,
       txnarrow:1,
       clockshift:1,
       unknown1b:4;
  u8   mode:2,
       duplex:2,
       tune_step:4;
  bbcd freq[3];
  u8   power:2,
       unknown2:4,
       tmode:2;  // TODO: tmode should be 6 bits (extended tone modes)
  u8   name[6];
  bbcd offset[3];
  u8   unknown3:2,
       tone:6;
  u8   unknown4:1,
       dcs:7;
  u8   unknown5;
  u8   smetersquelch;
  u8   unknown7a:2,
       attenuate:1,
       unknown7b:1,
       automode:1,
       unknown8:1,
       bell:2;
} memory[999];
"""

# fix auto mode setting and auto step setting

DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "AM", "WFM", "Auto", "NFM"]  # NFM handled specially in radio
TMODES = ["", "Tone", "TSQL", "DTCS"]
# TODO: TMODES = ["", "Tone, "TSQL", "DTCS", "Rev Tone", "User Tone", "Pager",
#          "Message", "D Code", "Tone/DTCS", "DTCS/Tone"]

# still need to verify 9 is correct, and add auto: look at byte 1 and 20
STEPS = [5.0, 9, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
# STEPS = list(chirp_common.TUNING_STEPS)
# STEPS.remove(6.25)
# STEPS.remove(30.0)
# STEPS.append(100.0)
# STEPS.append(9.0) #this fails because 9 is out of order in the list

# Empty char should be 0xFF but right now we are coding in a space
CHARSET = list("0123456789" +
               "ABCDEFGHIJKLMNOPQRSTUVWXYZ " +
               "+-/\x00[](){}\x00\x00_" +
               ("\x00" * 13) + "*" + "\x00\x00,'|\x00\x00\x00\x00" +
               ("\x00" * 64))

DTMFCHARSET = list("0123456789ABCD*#")
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=1.50),
                chirp_common.PowerLevel("Low", watts=0.10)]


class VX3Bank(chirp_common.NamedBank):
    """A VX3 Bank"""
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


class VX3BankModel(chirp_common.BankModel):
    """A VX-3 bank model"""

    def get_num_mappings(self):
        return len(self.get_mappings())

    def get_mappings(self):
        banks = self._radio._memobj.banks
        bank_mappings = []
        for index, _bank in enumerate(banks):
            bank = VX3Bank(self, "%i" % index, "b%i" % (index + 1))
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
        _bank_used.in_use = ((len(channels_in_bank) - 1) * 2)
        _banks_unmask1 = self._radio._memobj.banks_unmask1
        _banks_unmask2 = self._radio._memobj.banks_unmask2
        _banks_unmask1.unmask = 0x0017FFFF
        _banks_unmask2.unmask = 0x0017FFFF

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        _bank_used = self._radio._memobj.bank_used[bank.index]
        if channels_in_bank:
            _bank_used.in_use = ((len(channels_in_bank) - 1) * 2)
        else:
            _bank_used.in_use = 0xFFFF

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


def _wipe_memory(mem):
    mem.set_raw("\x00" * (mem.size() // 8))
    # the following settings are set to match the defaults
    # on the radio, some of these fields are unknown
    mem.name = [0xFF for _i in range(0, 6)]
    mem.unknown5 = 0x0D  # not sure what this is
    mem.unknown7a = 0b0
    mem.unknown7b = 0b1
    mem.automode = 0x01  # autoselect mode


@directory.register
class VX3Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-3"""
    BAUD_RATE = 19200
    VENDOR = "Yaesu"
    MODEL = "VX-3"

    # 41 48 30 32 38
    _model = "AH028"
    _memsize = 32587
    _block_lengths = [10, 32577]
    # right now this reads in 45 seconds and writes in 41 seconds
    _block_size = 32

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
        rf.valid_modes = list(set(MODES))
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(500000, 999000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.memory_bounds = (1, 999)
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_settings = True
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        _flag = self._memobj.flags[(number-1)/2]

        nibble = ((number-1) % 2) and "even" or "odd"
        used = _flag["%s_masked" % nibble]
        valid = _flag["%s_valid" % nibble]
        pskip = _flag["%s_pskip" % nibble]
        skip = _flag["%s_skip" % nibble]

        mem = chirp_common.Memory()
        mem.number = number

        if not used:
            mem.empty = True
        if not valid:
            mem.empty = True
            mem.power = POWER_LEVELS[0]
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        if _mem.txnarrow and _mem.mode == MODES.index("FM"):
            # FM narrow
            mem.mode = "NFM"
        else:
            mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.skip = pskip and "P" or skip and "S" or ""
        mem.power = POWER_LEVELS[~_mem.power & 0x01]

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

        if not mem.empty and not valid:
            _wipe_memory(_mem)

        if mem.empty and valid and not used:
            _flag["%s_valid" % nibble] = False
            return
        _flag["%s_masked" % nibble] = not mem.empty

        if mem.empty:
            return

        _flag["%s_valid" % nibble] = True

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        if mem.mode == "NFM":
            _mem.mode = MODES.index("FM")
            _mem.txnarrow = True
        else:
            _mem.mode = MODES.index(mem.mode)
            _mem.txnarrow = False
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        if mem.power == POWER_LEVELS[1]:  # Low
            _mem.power = 0x00
        else:  # Default to High
            _mem.power = 0x03

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        for i in range(0, 6):
            _mem.name[i] = CHARSET.index(mem.name.ljust(6)[i])
        if mem.name.strip():
            _mem.name[0] |= 0x80

    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)
        return msgs

    def get_bank_model(self):
        return VX3BankModel(self)

    def _decode_chars(self, inarr):
        LOG.debug("@_decode_chars, type: %s" % type(inarr))
        LOG.debug(inarr)
        outstr = ""
        for i in inarr:
            if i == 0xFF:
                break
            outstr += CHARSET[i & 0x7F]
        return outstr.rstrip()

    def _encode_chars(self, instr, length=16):
        LOG.debug("@_encode_chars, type: %s" % type(instr))
        LOG.debug(instr)
        outarr = []
        instr = str(instr)
        for i in range(length):
            if i < len(instr):
                outarr.append(CHARSET.index(instr[i]))
            else:
                outarr.append(0xFF)
        return outarr

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        sound = RadioSettingGroup("sound", "Sound")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        arts = RadioSettingGroup("arts", "ARTS")
        eai = RadioSettingGroup("eai", "Emergency")
        msg = RadioSettingGroup("msg", "Messages")

        top = RadioSettings(basic, sound, arts, dtmf, eai, msg)

        basic.append(RadioSetting(
                "att_wx", "Attenuation WX",
                RadioSettingValueBoolean(_settings.att_wx)))

        basic.append(RadioSetting(
                "att_marine", "Attenuation Marine",
                RadioSettingValueBoolean(_settings.att_marine)))

        basic.append(RadioSetting(
                "att_broadcast", "Attenuation Broadcast",
                RadioSettingValueBoolean(_settings.att_broadcast)))

        basic.append(RadioSetting(
                "ars", "Auto Repeater Shift",
                RadioSettingValueBoolean(_settings.ars)))

        basic.append(RadioSetting(
                "home_vfo", "Home->VFO",
                RadioSettingValueBoolean(_settings.home_vfo)))

        basic.append(RadioSetting(
                "bclo", "Busy Channel Lockout",
                RadioSettingValueBoolean(_settings.bclo)))

        basic.append(RadioSetting(
                "busyled", "Busy LED",
                RadioSettingValueBoolean(_settings.busy_led)))

        basic.append(RadioSetting(
                "fast_tone_search", "Fast Tone search",
                RadioSettingValueBoolean(_settings.fast_tone_search)))

        basic.append(RadioSetting(
                "priority_revert", "Priority Revert",
                RadioSettingValueBoolean(_settings.priority_revert)))

        basic.append(RadioSetting(
                "protect_memory", "Protect memory",
                RadioSettingValueBoolean(_settings.protect_memory)))

        basic.append(RadioSetting(
                "scan_lamp", "Scan Lamp",
                RadioSettingValueBoolean(_settings.scan_lamp)))

        basic.append(RadioSetting(
                "split_tone", "Split tone",
                RadioSettingValueBoolean(_settings.split_tone)))

        basic.append(RadioSetting(
                "tone_search_mute", "Tone search mute",
                RadioSettingValueBoolean(_settings.tone_search_mute)))

        basic.append(RadioSetting(
                "txsave", "TX save",
                RadioSettingValueBoolean(_settings.txsave)))

        basic.append(RadioSetting(
                "wx_alert", "WX Alert",
                RadioSettingValueBoolean(_settings.wx_alert)))

        opts = ["Bar Int", "Bar Ext"]
        basic.append(RadioSetting(
                "am_antenna", "AM antenna",
                RadioSettingValueList(opts, opts[_settings.am_antenna])))

        opts = ["Ext Ant", "Earphone"]
        basic.append(RadioSetting(
                "fm_antenna", "FM antenna",
                RadioSettingValueList(opts, opts[_settings.fm_antenna])))

        opts = ["off"] + ["%0.1f" % (t / 60.0) for t in range(30, 750, 30)]
        basic.append(RadioSetting(
                "apo", "APO time (hrs)",
                RadioSettingValueList(opts, opts[_settings.apo])))

        opts = ["+/- 5 MHZ", "+/- 10 MHZ", "+/- 50 MHZ", "+/- 100 MHZ"]
        basic.append(RadioSetting(
                "channel_counter", "Channel counter",
                RadioSettingValueList(opts, opts[_settings.channel_counter])))

        opts = ["0.3", "0.5", "0.7", "1.0", "1.5"]
        basic.append(RadioSetting(
                "fw_key_timer", "FW key timer (s)",
                RadioSettingValueList(opts, opts[_settings.fw_key_timer])))

        opts = ["Home", "Reverse"]
        basic.append(RadioSetting(
                "hm_rv", "HM/RV key",
                RadioSettingValueList(opts, opts[_settings.hm_rv])))

        opts = ["%d" % t for t in range(2, 11)] + ["continuous", "off"]
        basic.append(RadioSetting(
                "lamp", "Lamp Timer (s)",
                RadioSettingValueList(opts, opts[_settings.lamp])))

        basic.append(RadioSetting(
                "lock", "Lock",
                RadioSettingValueBoolean(_settings.lock)))

        opts = ["key", "ptt", "key+ptt"]
        basic.append(RadioSetting(
                "lock_mode", "Lock mode",
                RadioSettingValueList(opts, opts[_settings.lock_mode])))

        opts = ["10", "20", "50", "100"]
        basic.append(RadioSetting(
                "mem_ch_step", "Memory Chan step",
                RadioSettingValueList(opts, opts[_settings.mem_ch_step])))

        opts = ["lower", "next"]
        basic.append(RadioSetting(
                "mem_storage", "Memory storage mode",
                RadioSettingValueList(opts, opts[_settings.mem_storage])))

        opts = ["%d" % t for t in range(1, 10)]
        basic.append(RadioSetting(
                "mic_gain", "Mic gain",
                RadioSettingValueList(opts, opts[_settings.mic_gain])))

        opts = ["monitor", "tone call"]
        basic.append(RadioSetting(
                "moni_tcall", "Moni/TCall button",
                RadioSettingValueList(opts, opts[_settings.moni_tcall])))

        opts = ["off"] + \
               ["%02d:%02d" % (t / 60, t % 60) for t in range(10, 1450, 10)]
        basic.append(RadioSetting(
                "on_timer", "On Timer (hrs)",
                RadioSettingValueList(opts, opts[_settings.on_timer])))

        opts2 = ["off"] + \
                ["0.%d" % t for t in range(1, 10)] + \
                ["%1.1f" % (t / 10.0) for t in range(10, 105, 5)]
        basic.append(RadioSetting(
                "priority_time", "Priority time",
                RadioSettingValueList(opts2, opts2[_settings.priority_time])))

        opts = ["off", "20", "50", "100", "200"]
        basic.append(RadioSetting(
                "ptt_delay", "PTT delay (ms)",
                RadioSettingValueList(opts, opts[_settings.ptt_delay])))

        basic.append(RadioSetting(
                "rx_save", "RX save (s)",
                RadioSettingValueList(opts2, opts2[_settings.rx_save])))

        basic.append(RadioSetting(
                "scan_restart", "Scan restart (s)",
                RadioSettingValueList(opts2, opts2[_settings.scan_restart])))

        opts = ["%1.1f" % (t / 10.0) for t in range(20, 105, 5)] + \
               ["busy", "hold"]
        basic.append(RadioSetting(
                "scan_resume", "Scan resume (s)",
                RadioSettingValueList(opts, opts[_settings.scan_resume])))

        opts = ["single", "continuous"]
        basic.append(RadioSetting(
                "smart_search", "Smart search",
                RadioSettingValueList(opts, opts[_settings.smart_search])))

        opts = ["off"] + ["TRX %d" % t for t in range(1, 11)] + ["hold"] + \
               ["TX %d" % t for t in range(1, 11)]
        basic.append(RadioSetting(
                "sub_rx_timer", "Sub RX timer",
                RadioSettingValueList(opts, opts[_settings.sub_rx_timer])))

        opts = ["C", "F"]
        basic.append(RadioSetting(
                "temp_unit", "Temperature unit",
                RadioSettingValueList(opts, opts[_settings.temp_unit])))

        opts = ["off"] + ["%1.1f" % (t / 10.0) for t in range(5, 105, 5)]
        basic.append(RadioSetting(
                "tot", "Time-out timer (mins)",
                RadioSettingValueList(opts, opts[_settings.tot])))

        opts = ["all", "band"]
        basic.append(RadioSetting(
                "vfo_mode", "VFO mode",
                RadioSettingValueList(opts, opts[_settings.vfo_mode])))

        opts = ["off"] + ["%d" % t for t in range(5, 65, 5)] + ["EAI"]
        basic.append(RadioSetting(
                "wake_up", "Wake up (s)",
                RadioSettingValueList(opts, opts[_settings.wake_up])))

        opts = ["hold", "3 secs"]
        basic.append(RadioSetting(
                "vol_key_mode", "Volume key mode",
                RadioSettingValueList(opts, opts[_settings.vol_key_mode])))

        # subgroup programmable keys

        opts = ["INTNET", "INT MR", "Set Mode (my key)"]
        basic.append(RadioSetting(
                "internet_key", "Internet key",
                RadioSettingValueList(opts, opts[_settings.internet_key])))

        keys = ["Antenna AM", "Antenna FM", "Antenna Attenuator",
                "Auto Power Off", "Auto Repeater Shift", "ARTS Beep",
                "ARTS Interval", "Busy Channel Lockout", "Bell Ringer",
                "Bell Select", "Bank Name", "Band Edge Beep", "Beep Level",
                "Beep Select", "Beep User", "Busy LED", "Channel Counter",
                "Clock Shift", "CW ID", "CW Learning", "CW Pitch",
                "CW Training", "DC Voltage", "DCS Code", "DCS Reverse",
                "DTMF A/M", "DTMF Delay", "DTMF Set", "DTMF Speed",
                "EAI Timer", "Emergency Alarm", "Ext Menu", "FW Key",
                "Half Deviation", "Home/Reverse", "Home > VFO", "INT Code",
                "INT Conn Mode", "INT A/M", "INT Set", "INT Key", "INTNET",
                "Lamp", "LED Light", "Lock", "Moni/T-Call", "Mic Gain",
                "Memory Display", "Memory Write Mode", "Memory Channel Step",
                "Memory Name Write", "Memory Protect", "Memory Skip",
                "Message List", "Message Reg", "Message Set", "On Timer",
                "Open Message", "Pager Answer Back", "Pager Receive Code",
                "Pager Transmit Code", "Pager Frequency", "Priority Revert",
                "Priority Timer", "Password", "PTT Delay",
                "Repeater Shift Direction", "Repeater Shift", "Receive Mode",
                "Smart Search", "Save Rx", "Save Tx", "Scan Lamp",
                "Scan Resume", "Scan Restart", "Speaker Out",
                "Squelch Level", "Squelch Type", "Squelch S Meter",
                "Squelch Split Tone", "Step", "Stereo", "Sub Rx", "Temp",
                "Tone Frequency", "Time Out Timer", "Tone Search Mute",
                "Tone Search Speed", "VFO Band", "VFO Skip", "Volume Mode",
                "Wake Up", "Weather Alert"]
        rs = RadioSetting(
                "my_key", "My key",
                RadioSettingValueList(keys, keys[_settings.my_key - 16]))
        # TODO: fix keys list isnt exactly right order
        # leave disabled in settings for now
        # basic.append(rs)

        # sound tab

        sound.append(RadioSetting(
                "band_edge_beep", "Band edge beep",
                RadioSettingValueBoolean(_settings.band_edge_beep)))

        opts = ["off", "key+scan", "key"]
        sound.append(RadioSetting(
                "beep_mode", "Beep mode",
                RadioSettingValueList(opts, opts[_settings.beep_mode])))

        _volumes = self._memobj.volumes

        opts = list(map(str, list(range(0, 33))))
        sound.append(RadioSetting(
                "speaker_vol", "Speaker volume",
                RadioSettingValueList(opts, opts[_volumes.speaker])))

        sound.append(RadioSetting(
                "earphone_vol", "Earphone volume",
                RadioSettingValueList(opts, opts[_volumes.earphone])))

        opts = ["auto", "speaker"]
        sound.append(RadioSetting(
                "fm_speaker_out", "FM Speaker out",
                RadioSettingValueList(opts, opts[_settings.fm_speaker_out])))

        opts = ["mono", "stereo"]
        sound.append(RadioSetting(
                "fm_broadcast_mode", "FM broadcast mode",
                RadioSettingValueList(
                    opts, opts[_settings.fm_broadcast_mode])))

        opts = list(map(str, list(range(16))))
        sound.append(RadioSetting(
                "sql_fm", "Squelch level (FM)",
                RadioSettingValueList(opts, opts[_settings.sql_fm])))

        opts = list(map(str, list(range(9))))
        sound.append(RadioSetting(
                "sql_wfm", "Squelch level (WFM)",
                RadioSettingValueList(opts, opts[_settings.sql_wfm])))

        opts = list(map(str, list(range(16))))
        sound.append(RadioSetting(
                "radio_am_sql", "Squelch level (Broadcast Radio AM)",
                RadioSettingValueList(opts, opts[_settings.radio_am_sql])))

        opts = list(map(str, list(range(9))))
        sound.append(RadioSetting(
                "radio_fm_sql", "Squelch level (Broadcast Radio FM)",
                RadioSettingValueList(opts, opts[_settings.radio_fm_sql])))

        # dtmf tab

        opts = ["manual", "auto"]
        dtmf.append(RadioSetting(
                "dtmf_autodialer", "DTMF autodialer mode",
                RadioSettingValueList(opts, opts[_settings.dtmf_autodialer])))

        opts = ["50", "250", "450", "750", "1000"]
        dtmf.append(RadioSetting(
                "dtmf_delay", "DTMF delay (ms)",
                RadioSettingValueList(opts, opts[_settings.dtmf_delay])))

        opts = ["50", "100"]
        dtmf.append(RadioSetting(
                "dtmf_speed", "DTMF speed (ms)",
                RadioSettingValueList(opts, opts[_settings.dtmf_speed])))

        opts = list(map(str, list(range(10))))
        dtmf.append(RadioSetting(
                "dtmf_chan_active", "DTMF active",
                RadioSettingValueList(
                    opts, opts[_settings.dtmf_chan_active])))

        for i in range(10):
            name = "dtmf" + str(i)
            dtmfsetting = self._memobj.dtmf[i]
            dtmfstr = ""
            for c in dtmfsetting.memory:
                if c < len(DTMFCHARSET):
                    dtmfstr += DTMFCHARSET[c]
            LOG.debug(dtmfstr)
            dtmfentry = RadioSettingValueString(0, 16, dtmfstr)
            dtmfentry.set_charset(DTMFCHARSET + list(" "))
            rs = RadioSetting(name, name.upper(), dtmfentry)
            dtmf.append(rs)

        # arts tab
        arts.append(RadioSetting(
                "arts", "ARTS",
                RadioSettingValueBoolean(_settings.arts)))

        opts = ["off", "in range", "always"]
        arts.append(RadioSetting(
                "arts_beep", "ARTS beep",
                RadioSettingValueList(opts, opts[_settings.arts_beep])))

        opts = ["15", "25"]
        arts.append(RadioSetting(
                "arts_interval", "ARTS interval",
                RadioSettingValueList(opts, opts[_settings.arts_interval])))

        arts.append(RadioSetting(
                "arts_cwid_enable", "CW ID",
                RadioSettingValueBoolean(_settings.arts_cwid_enable)))

        cwid = RadioSettingValueString(
                0, 16, self._decode_chars(_settings.arts_cwid.get_value()))
        cwid.set_charset(CHARSET)
        arts.append(RadioSetting("arts_cwid", "CW ID", cwid))

        # EAI tab

        eai.append(RadioSetting(
                "emergency_eai", "EAI",
                RadioSettingValueBoolean(_settings.emergency_eai)))

        opts = ["interval %dm" % t for t in range(1, 10)] + \
               ["interval %dm" % t for t in range(10, 55, 5)] + \
               ["continuous %dm" % t for t in range(1, 10)] + \
               ["continuous %dm" % t for t in range(10, 55, 5)]

        eai.append(RadioSetting(
                "emergency_eai_time", "EAI time",
                RadioSettingValueList(
                    opts, opts[_settings.emergency_eai_time])))

        opts = ["beep", "strobe", "beep+strobe", "beam",
                "beep+beam", "cw", "beep+cw", "cwt"]
        eai.append(RadioSetting(
                "emergency_signal", "emergency signal",
                RadioSettingValueList(
                    opts, opts[_settings.emergency_signal])))

        # msg tab

        opts = ["off", "dc voltage", "message"]
        msg.append(RadioSetting(
                "openmsg_mode", "Opening message mode",
                RadioSettingValueList(opts, opts[_settings.openmsg_mode])))

        openmsg = RadioSettingValueString(
                0, 6, self._decode_chars(_settings.openmsg.get_value()))
        openmsg.set_charset(CHARSET)
        msg.append(RadioSetting("openmsg", "Opening Message", openmsg))

        return top

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
                if re.match('dtmf\d', setting):
                    # set dtmf fields
                    dtmfstr = str(element.value).strip()
                    newval = []
                    for i in range(0, 16):
                        if i < len(dtmfstr):
                            newval.append(DTMFCHARSET.index(dtmfstr[i]))
                        else:
                            newval.append(0xFF)
                    LOG.debug(newval)
                    idx = int(setting[-1:])
                    _settings = self._memobj.dtmf[idx]
                    _settings.memory = newval
                    continue
                if re.match('.*_vol$', setting):
                    # volume fields
                    voltype = re.sub('_vol$', '', setting)
                    setattr(self._memobj.volumes, voltype, element.value)
                    continue
                if setting == "my_key":
                    # my_key is memory is off by 9 from list, beware hacks!
                    opts = element.value.get_options()
                    optsidx = opts.index(element.value.get_value())
                    idx = optsidx + 16
                    setattr(_settings, "my_key", idx)
                    continue
                oldval = getattr(_settings, setting)
                newval = element.value
                if setting == "arts_cwid":
                    newval = self._encode_chars(newval)
                if setting == "openmsg":
                    newval = self._encode_chars(newval, 6)
                LOG.debug("Setting %s(%s) <= %s" % (setting, oldval, newval))
                setattr(_settings, setting, newval)
            except Exception as e:
                LOG.debug(element.get_name())
                raise
