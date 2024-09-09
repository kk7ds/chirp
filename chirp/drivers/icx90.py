# -*- coding: utf-8 -*-
# Copyright 2018-2020 Jaroslav Škarvada <jskarvad@redhat.com>
# Based on various code from the CHIRP

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

import logging

from chirp.drivers import icf
from chirp import chirp_common, bitwise, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
import argparse

ICX90_MEM_FORMAT = """
struct mem_item {
  ul24 freq;
  u8 dtcs_polarity:2,
     unknown_1:2,
     offset_freq_mult:1,
     unknown_2:2,
     freq_mult:1;
  u8 unknown_3:1,
     duplex:2,
     mode:2,
     tone_mode:3;
  ul16 offset_freq;
  u8 dtcs;
  u8 tx_tone_lo:4,
     tune_step:4;
  u8 rx_tone:6,
     tx_tone_hi:2;
  char name[6];
};
struct bank_item {
  u8 invisible_channel:1,
     prog_skip:1,
     mem_skip:1,
     bank_index:5;
  u8 bank_channel;
};
struct tv_mem_item {
  u8 fixed:7,
     mode:1;
  ul24 freq;
  char name[4];
};

struct mem_item memory[500];
struct mem_item scan_edges[50];
struct bank_item banks[500];
u8 unknown_4[120];
struct mem_item vfo_a_band[10];
struct mem_item vfo_b_band[10];
struct mem_item call_channels[5];
struct tv_mem_item tv_memory[68];
u8 unknown_5[35];
ul16 mem_channel;
u8 autodial;
u8 unknown_6[8];
u8 unknown_7:6,
   skip_scan:1,
   unknown_8:1;
u8 squelch_level;
struct {
  char dtmf_digits[16];
} dtmf_codes[10];
u8 tv_channel_skip[68];
u8 unknown_9[128];
u8 scan_resume;
u8 scan_pause;
u8 unknown_10;
u8 beep_volume;
u8 beep;
u8 backlight;
u8 busy_led;
u8 auto_power_off;
u8 power_save;
u8 monitor;
u8 dial_speedup;
u8 unknown_11;
u8 auto_repeater;
u8 dtmf_speed;
u8 hm_75a_function;
u8 wx_alert;
u8 expand_1;
u8 scan_stop_beep;
u8 scan_stop_light;
u8 unknown_12;
u8 light_position;
u8 light_color;
u8 unknown_13;
u8 band_edge_beep;
u8 auto_power_on;
u8 key_lock;
u8 ptt_lock;
u8 lcd_contrast;
u8 opening_message;
u8 expand_2;
u8 unknown_14;
u8 busy_lockout;
u8 timeout_timer;
u8 active_band;
u8 split;
u8 fm_narrow;
u8 morse_code_enable;
u8 morse_code_speed;
u8 unknown_15[22];
char opening_message_text[6];
u8 unknown_16[186];
u8 unknown_17:4,
   tune_step:4;
u8 unknown_18[4];
u8 band_selected;
u8 unknown_19[2];
u8 unknown_20:2,
   attenuator:1,
   vfo:1,
   power:1,
   dial_select:1,
   memory_name:1,
   memory_display:1;
u8 unknown_21[2];
u8 mode:4,
   unknown_22:4;
u8 unknown_23[9];
char alpha_tag[6];
u8 vfo_scan;
u8 memory_scan;
u8 unknown_24;
u8 tv_channel;
u8 wx_channel;
char comment[16];
"""

LOG = logging.getLogger(__name__)

# in bytes
MEM_ITEM_SIZE = 16
TV_MEM_ITEM_SIZE = 8

BANK_INDEX = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "L", "N", "O",
              "P", "Q", "R", "T", "U", "Y"]
MEM_NUM = 500
BANKS = 18
BANK_NUM = 100
BANK_INDEX_NUM = len(BANK_INDEX)
DTMF_AUTODIAL_NUM = 10
DTMF_DIGITS_NUM = 16
OPENING_MESSAGE_LEN = 6
COMMENT_LEN = 16
BANDS = 10
TV_CHANNELS = 68

CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789()*+-,/|= "
NAME_LENGTH = 6
TV_NAME_LENGTH = 4
DUPLEX = ["", "-", "+", ""]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]
TONE_MODE = ["", "Tone", "TSQL", "DTCS"]
TUNE_STEP = [5.0, 6.25, 8.33, 9.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0, 200.0]
TUNE_STEP_STR = [str(x) for x in TUNE_STEP]
MODE = ["FM", "WFM", "AM"]
TV_MODE = ["WFM", "AM"]

SQUELCH_LEVEL = ["Open", "Auto", "Level 1", "Level 2", "Level 3", "Level 4", "Level 5",
                 "Level 6", "Level 7", "Level 8", "Level 9"]
AUTODIAL = ["Tone call", "D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
DTMF_SPEED = ["100 ms", "200 ms", "300 ms", "400 ms"]
SCAN_RESUME = ["0 s", "1 s", "2 s", "3 s", "4 s", "5 s", "Hold"]
SCAN_PAUSE = ["2 s", "4 s", "6 s", "8 s", "10 s", "12 s", "14 s", "16 s", "18 s", "20 s", "Hold"]
BEEP_VOLUME = ["Volume", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
               "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25",
               "26", "27", "28", "29", "30", "31"]
BACKLIGHT = ["Off", "On", "Auto"]
AUTO_POWER_OFF = ["Off", "30 min", "60 min", "90 min", "120 min"]
POWER_SAVE = ["Off", "1:1", "1:4", "1:8", "1:16", "Auto"]
MONITOR = ["Push", "Hold"]
AUTO_REPEATER = ["Off", "Duplex only", "Duplex & tone"]
HM_75A_FUNCTION = ["Simple", "Normal 1", "Normal 2"]
LIGHT_POSITION = ["LCD", "Key", "All"]
LIGHT_COLOR = ["Green", "Orange", "Red"]
AUTO_POWER_ON = ["Off", "00:30", "01:00", "01:30", "02:00", "02:30", "03:00", "03:30", "04:00",
                 "04:30", "05:00", "05:30", "06:00", "06:30", "07:00", "07:30", "08:00",
                 "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00",
                 "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00",
                 "16:30", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00",
                 "20:30", "21:00", "21:30", "22:00", "22:30", "23:00", "23:30", "24:00"]
KEY_LOCK = ["Normal", "No squelch", "No volume", "All"]
LCD_CONTRAST = ["1", "2", "3", "4"]
TIMEOUT_TIMER = ["Off", "1 min", "3 min", "5 min", "10 min"]
ACTIVE_BAND = ["All", "Single"]
MORSE_CODE_SPEED = ["10 WPM", "15 WPM", "20 WPM", "25 WPM"]
WX_CHANNEL = ["WX01", "WX02", "WX03", "WX04", "WX05", "WX06", "WX07", "WX08", "WX09", "WX10"]
MEMORY_DISPLAY = ["Channel", "Bank"]
DIAL_SELECT = ["Normal", "Volume"]
POWER = ["High", "Low"]
VFO = ["A", "B"]
OPERATION_MODE = ["VFO", "Memory", "Call channel", "TV"]
VFO_SCAN = ["All", "Band", "P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8",
            "P9", "P10", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18",
            "P19", "P20", "P21", "P22", "P23", "P24"]
MEMORY_SCAN = ["All", "Bank", "Sel BC", "Sel 5 MHz", "Sel 50 MHz", "Sel WFM", "Sel Air",
               "Sel 144 MHz", "Sel 220 MHz", "Sel 300 MHz", "Sel 440 MHz", "Sel 800 MHz"]


class ICx90BankModel(icf.IcomIndexedBankModel):
    bank_index = BANK_INDEX

    def get_mappings(self):
        banks = []

        if (self._radio._num_banks != len(type(self).bank_index)):
            raise Exception("Invalid number of banks %d, supported only %d banks" %
                            (self._radio._num_banks, len(type(self).bank_index)))

        for i in range(0, self._radio._num_banks):
            index = type(self).bank_index[i]
            bank = self._radio._bank_class(self, index, "BANK-%s" % index)
            bank.index = i
            banks.append(bank)

        return banks


class ICT90_Alias(chirp_common.Alias):
    VENDOR = "Icom"
    MODEL = "IC-T90"


@directory.register
class ICx90Radio(icf.IcomCloneModeRadio):
    """Icom IC-E/T90"""
    VENDOR = "Icom"
    MODEL = "IC-E90"

    ALIASES = [ICT90_Alias]

    _model = "\x25\x07\x00\x01"
    _memsize = 0x2d40
    _endframe = "Icom Inc."

    _ranges = [(0x0000, 0x2d40, 32)]
    _num_banks = BANKS
    _bank_index_bounds = (0, BANK_NUM - 1)
    _can_hispeed = False

    def __init__(self, pipe):
        icf.IcomCloneModeRadio.__init__(self, pipe)

    def special_add(self, key, item_type, num, unique_idx):
        item = {}
        item["item_type"] = item_type
        item["num"] = num
        item["uidx"] = unique_idx
        self.special[key] = item

    def init_special(self):
        self.special = {}
        i = 0
        # program scan edges
        for x in range(25):
            self.special_add("Scan edge: %02dA" % x, "scan_edge", x * 2, i)
            self.special_add("Scan edge: %02dB" % x, "scan_edge", x * 2 + 1, i + 1)
            i += 2
        # call channels
        for x in range(5):
            self.special_add("Call ch: %d" % x, "call_chan", x, i)
            i += 1
        # VFO A
        for x in range(10):
            self.special_add("VFO A: %d" % x, "vfo_a", x, i)
            i += 1
        # VFO B
        for x in range(10):
            self.special_add("VFO B: %d" % x, "vfo_b", x, i)
            i += 1

    def get_sub_devices(self):
        return [ICx90Radio_ham(self._mmap), ICx90Radio_tv(self._mmap)]

    def clear_bank(self, loc):
        # it seems that empty invisible channel which isn't in bank is defined in bank_item by bytes 0x9f 0x00,
        # i.e. it has invisible_channel == 1
        # it seems that non-empty visible channel which isn't in bank is defined in bank_item by bytes 0x1f 0x00,
        # i.e. it has invisible_channel == 0
        # so do not touch the invisible_channel (the bit 7 of the first byte) here and only
        # set the rest of the bits
        self.memobj.banks[loc].bank_index = 0x1f
        self.memobj.banks[loc].prog_skip = 0
        self.memobj.banks[loc].mem_skip = 0
        self.memobj.banks[loc].bank_channel = 0

    # it seems the bank driver has different terminology about bank number and index
    # so in fact _get_bank and _set_bank are about indexes (i.e index in the array
    # of bank names - A .. Y
    # and _get_bank_index and _set_bank_index are about positions in the bank (0..99)
    def _get_bank(self, loc):
        i = self.memobj.banks[loc].bank_index
        return i if i < BANK_INDEX_NUM else None

    def _set_bank(self, loc, bank):
        if bank is None:
            self.clear_bank(loc)
        else:
            self.memobj.banks[loc].bank_index = bank
            # it seems if invisible_channel == 1 the channel is invisible (deleted)
            # so set it explicitly as visible
            self.memobj.banks[loc].invisible_channel = 0

    def _get_bank_index(self, loc):
        i = self.memobj.banks[loc].bank_channel
        return i if i < BANK_NUM else None

    def _set_bank_index(self, loc, index):
        self.memobj.banks[loc].bank_channel = index

    def get_features(self):
        self.init_special()
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_name = True
        rf.has_bank = True
        rf.has_bank_index = True
        rf.has_bank_names = False
        rf.can_delete = True
        rf.has_ctone = True
        rf.has_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_tuning_step = True
        rf.has_comment = False
        rf.memory_bounds = (0, MEM_NUM - 1)
        rf.has_sub_devices = True
        rf.valid_characters = CHARSET
        rf.valid_modes = list(MODE)
        rf.valid_tmodes = list(TONE_MODE)
        rf.valid_duplexes = list(DUPLEX)[:-1]
        rf.valid_tuning_steps = list(TUNE_STEP)
        rf.valid_bands = [(495000, 999990000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_name_length = NAME_LENGTH
        rf.valid_special_chans = sorted(self.special.keys())

        return rf

    def map_dtmf_chirp2icom(self, item):
        item = str(item).upper()
        if item == "*":
            item = "E"
        elif item == "#":
            item = "F"
        elif item == " ":
            return 0xff
        try:
            ret = int(item, 16)
        except ValueError:
            raise errors.InvalidDataError("invalid DTMF number '%s'" % item)
        return ret

    def dtmf_chirp2icom(self, dtmf):
        return "".join(map(self.map_dtmf_chirp2icom, str(dtmf).rjust(DTMF_DIGITS_NUM)))

    def map_dtmf_icom2chirp(self, item):
        item = ord(item)
        if item == 0xff:
            return " "
        else:
            item &= 0x0f
            if item < 10:
                return str(item)
            else:
                return ["A", "B", "C", "D", "*", "#"][item - 10]

    def dtmf_icom2chirp(self, dtmf):
        return "".join(map(self.map_dtmf_icom2chirp, str(dtmf)))

    def apply_dtmf_autodial(self, setting, obj):
        obj = self.dtmf_chirp2icom(setting.value)

    def get_settings(self):
        try:
            _squelch = 1
            basic = RadioSettingGroup("basic", "Basic")
            expand_1 = RadioSettingGroup("expand_1", "Expand 1")
            expand_2 = RadioSettingGroup("expand_2", "Expand 2")
            dtmf_autodial = RadioSettingGroup("dtmf_autodial", "DTMF autodial")
            group = RadioSettings(basic, expand_1, expand_2, dtmf_autodial)

            # basic
            basic.append(RadioSetting("mem_channel", "Current memory channel",
                         RadioSettingValueInteger(0, MEM_NUM - 1, self.memobj.mem_channel)))
            basic.append(RadioSetting("squelch_level", "Squelch level",
                         RadioSettingValueList(SQUELCH_LEVEL,
                                               current_index=self.memobj.squelch_level)))
            basic.append(RadioSetting("scan_resume", "Scan resume",
                         RadioSettingValueList(SCAN_RESUME,
                                               current_index=self.memobj.scan_resume)))
            basic.append(RadioSetting("scan_pause", "Scan pause",
                         RadioSettingValueList(SCAN_PAUSE,
                                               current_index=self.memobj.scan_pause)))
            basic.append(RadioSetting("beep_volume", "Beep audio",
                         RadioSettingValueList(BEEP_VOLUME,
                                               current_index=self.memobj.beep_volume)))
            basic.append(RadioSetting("beep", "Operation beep",
                         RadioSettingValueBoolean(self.memobj.beep)))
            basic.append(RadioSetting("backlight", "LCD backlight",
                         RadioSettingValueList(BACKLIGHT,
                                               current_index=self.memobj.backlight)))
            basic.append(RadioSetting("busy_led", "Busy LED",
                         RadioSettingValueBoolean(self.memobj.busy_led)))
            basic.append(RadioSetting("auto_power_off", "Auto power off",
                         RadioSettingValueList(AUTO_POWER_OFF,
                                               current_index=self.memobj.auto_power_off)))
            basic.append(RadioSetting("power_save", "Power save",
                         RadioSettingValueList(POWER_SAVE,
                                               current_index=self.memobj.power_save)))
            basic.append(RadioSetting("monitor", "Monitor",
                         RadioSettingValueList(MONITOR,
                                               current_index=self.memobj.monitor)))
            basic.append(RadioSetting("dial_speedup", "Dial speedup",
                         RadioSettingValueBoolean(self.memobj.dial_speedup)))
            basic.append(RadioSetting("auto_repeater", "Auto repeater",
                         RadioSettingValueList(AUTO_REPEATER,
                                               current_index=self.memobj.auto_repeater)))
            basic.append(RadioSetting("hm_75a_function", "HM-75A function",
                         RadioSettingValueList(HM_75A_FUNCTION,
                                               current_index=self.memobj.hm_75a_function)))
            basic.append(RadioSetting("wx_alert", "WX alert",
                         RadioSettingValueBoolean(self.memobj.wx_alert)))
            basic.append(RadioSetting("wx_channel", "Current WX channel",
                         RadioSettingValueList(WX_CHANNEL,
                                               current_index=self.memobj.wx_channel)))
            basic.append(RadioSetting("comment", "Comment",
                         RadioSettingValueString(0, COMMENT_LEN,
                                                 str(self.memobj.comment),
                                                 autopad=True)))
            basic.append(RadioSetting("tune_step", "Current tune step",
                         RadioSettingValueList(TUNE_STEP_STR,
                                               current_index=self.memobj.tune_step)))
            basic.append(RadioSetting("band_selected", "Selected band",
                         RadioSettingValueInteger(0, BANDS - 1, self.memobj.band_selected)))
            basic.append(RadioSetting("memory_display", "Memory display",
                         RadioSettingValueList(MEMORY_DISPLAY,
                                               current_index=self.memobj.memory_display)))
            basic.append(RadioSetting("memory_name", "Memory name",
                         RadioSettingValueBoolean(self.memobj.memory_name)))
            basic.append(RadioSetting("dial_select", "Dial select",
                         RadioSettingValueList(DIAL_SELECT,
                                               current_index=self.memobj.dial_select)))
            basic.append(RadioSetting("power", "RF power",
                         RadioSettingValueList(POWER,
                                               current_index=self.memobj.power)))
            basic.append(RadioSetting("vfo", "Current VFO",
                         RadioSettingValueList(VFO,
                                               current_index=self.memobj.vfo)))
            basic.append(RadioSetting("attenuator", "RF attenuator",
                         RadioSettingValueBoolean(self.memobj.attenuator)))
            basic.append(RadioSetting("skip_scan", "Skip scan",
                         RadioSettingValueBoolean(self.memobj.skip_scan)))
# TODO: this needs to be reverse engineered, because the following commented
# code does not seem correct
#            basic.append(RadioSetting("mode", "Current mode",
#                         RadioSettingValueList(OPERATION_MODE,
#                         OPERATION_MODE[self.memobj.mode])))
            basic.append(RadioSetting("vfo_scan", "VFO scan",
                         RadioSettingValueList(VFO_SCAN,
                                               current_index=self.memobj.vfo_scan)))
            basic.append(RadioSetting("memory_scan", "Memory scan",
                         RadioSettingValueList(MEMORY_SCAN,
                                               current_index=self.memobj.memory_scan)))
            basic.append(RadioSetting("tv_channel", "Current TV channel",
                         RadioSettingValueInteger(0, TV_CHANNELS - 1, self.memobj.tv_channel)))

            # DTMF auto dial
            dtmf_autodial.append(RadioSetting("autodial", "Autodial",
                                 RadioSettingValueList(AUTODIAL,
                                                       current_index=self.memobj.autodial)))
            dtmf_autodial.append(RadioSetting("dtmf_speed", "Speed",
                                 RadioSettingValueList(DTMF_SPEED,
                                                       current_index=self.memobj.dtmf_speed)))
            for x in range(DTMF_AUTODIAL_NUM):
                rs = RadioSetting("dtmf_codes[%d].dtmf_digits" % x, "DTMF autodial: %d" % x,
                                  RadioSettingValueString(0, DTMF_DIGITS_NUM,
                                                          self.dtmf_icom2chirp(self.memobj.dtmf_codes[x].dtmf_digits),
                                                          autopad=True, charset="0123456789ABCD*#abcd "))
                rs.set_apply_callback(self.apply_dtmf_autodial, self.memobj.dtmf_codes[x].dtmf_digits)
                dtmf_autodial.append(rs)

            # expand 1
            expand_1.append(RadioSetting("expand_1", "Expand 1",
                            RadioSettingValueBoolean(self.memobj.expand_1)))
            expand_1.append(RadioSetting("scan_stop_beep", "Scan stop beep",
                            RadioSettingValueBoolean(self.memobj.scan_stop_beep)))
            expand_1.append(RadioSetting("scan_stop_light", "Scan stop light",
                            RadioSettingValueBoolean(self.memobj.scan_stop_light)))
            expand_1.append(RadioSetting("light_postion", "Light position",
                            RadioSettingValueList(LIGHT_POSITION,
                                                  current_index=self.memobj.light_position)))
            expand_1.append(RadioSetting("light_color", "Light color",
                            RadioSettingValueList(LIGHT_COLOR,
                                                  current_index=self.memobj.light_color)))
            expand_1.append(RadioSetting("band_edge_beep", "Band edge beep",
                            RadioSettingValueBoolean(self.memobj.band_edge_beep)))
            expand_1.append(RadioSetting("auto_power_on", "Auto power on",
                            RadioSettingValueList(AUTO_POWER_ON,
                                                  current_index=self.memobj.auto_power_on)))
            expand_1.append(RadioSetting("key_lock", "Key lock",
                            RadioSettingValueList(KEY_LOCK,
                                                  current_index=self.memobj.key_lock)))
            expand_1.append(RadioSetting("ptt_lock", "PTT lock",
                            RadioSettingValueBoolean(self.memobj.ptt_lock)))
            expand_1.append(RadioSetting("lcd_contrast", "LCD contrast",
                            RadioSettingValueList(LCD_CONTRAST,
                                                  current_index=self.memobj.lcd_contrast)))
            expand_1.append(RadioSetting("opening_message", "Opening message",
                            RadioSettingValueBoolean(self.memobj.opening_message)))
            expand_1.append(RadioSetting("opening_message_text", "Opening message",
                            RadioSettingValueString(0, OPENING_MESSAGE_LEN,
                                                    str(self.memobj.opening_message_text),
                                                    autopad=True, charset=CHARSET)))

            # expand 2
            expand_2.append(RadioSetting("expand_2", "Expand 2",
                            RadioSettingValueBoolean(self.memobj.expand_2)))
            expand_2.append(RadioSetting("busy_lockout", "Busy lock out",
                            RadioSettingValueBoolean(self.memobj.busy_lockout)))
            expand_2.append(RadioSetting("timeout_timer", "Timeout timer",
                            RadioSettingValueList(TIMEOUT_TIMER,
                                                  current_index=self.memobj.timeout_timer)))
            expand_2.append(RadioSetting("active_band", "Active band",
                            RadioSettingValueList(ACTIVE_BAND,
                                                  current_index=self.memobj.active_band)))
            expand_2.append(RadioSetting("fm_narrow", "FM narrow",
                            RadioSettingValueBoolean(self.memobj.fm_narrow)))
            expand_2.append(RadioSetting("split", "Split",
                            RadioSettingValueBoolean(self.memobj.split)))
            expand_2.append(RadioSetting("morse_code_enable", "Morse code synthesizer",
                            RadioSettingValueBoolean(self.memobj.morse_code_enable)))
            expand_2.append(RadioSetting("morse_code_speed", "Morse code speed",
                            RadioSettingValueList(MORSE_CODE_SPEED,
                                                  current_index=self.memobj.morse_code_speed)))

            return group
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    try:
                        element.run_apply_callback()
                    except NotImplementedError as e:
                        LOG.error("icx90: %s", e)
                    continue

                # Find the object containing setting.
                obj = self.memobj
                bits = element.get_name().split(".")
                setting = bits[-1]
                for name in bits[:-1]:
                    if name.endswith("]"):
                        name, index = name.split("[")
                        index = int(index[:-1])
                        obj = getattr(obj, name)[index]
                    else:
                        obj = getattr(obj, name)

                try:
                    old_val = getattr(obj, setting)
                    LOG.debug("Setting %s(%r) <= %s" % (
                        element.get_name(), old_val, element.value))
                    setattr(obj, setting, element.value)
                except AttributeError as e:
                    LOG.error("Setting %s is not in the memory map: %s" %
                              (element.get_name(), e))
            except Exception:
                LOG.debug(element.get_name())
                raise

    def process_mmap(self):
        self.memobj = bitwise.parse(ICX90_MEM_FORMAT, self._mmap)

    def sync_in(self):
        icf.IcomCloneModeRadio.sync_in(self)
        self.process_mmap()

    def sync_out(self):
        icf.IcomCloneModeRadio.sync_out(self)

    def freq_chirp2icom(self, freq):
        if chirp_common.is_fractional_step(freq):
            mult = 6250
            multr = 1
        else:
            mult = 5000
            multr = 0

        return (freq / mult, multr)

    def freq_icom2chirp(self, freq, mult):
        return freq * (6250 if mult else 5000)

    def get_skip(self, number):
        bank_item = self.memobj.banks[number]
        if bank_item.prog_skip:
            return "P"
        elif bank_item.mem_skip:
            return "S"
        return ""

    def set_skip(self, number, skip):
        bank_item = self.memobj.banks[number]
        if skip == "P":
            bank_item.prog_skip = 1
            bank_item.mem_skip = 1
        elif skip == "S":
            bank_item.prog_skip = 0
            bank_item.mem_skip = 1
        elif skip == "":
            bank_item.prog_skip = 0
            bank_item.mem_skip = 0
        else:
            raise errors.InvalidDataError("skip '%s' not supported" % skip)

    # returns (memobj.mem_item, is_special_channel, unique_idx)
    def get_mem_item(self, number):
        try:
            item_type = self.special[number]["item_type"]
            num = self.special[number]["num"]
            unique_idx = self.special[number]["uidx"]
            if item_type == "scan_edge":
                return (self.memobj.scan_edges[num], True, unique_idx)
            elif item_type == "call_chan":
                return (self.memobj.call_channels[num], True, unique_idx)
            elif item_type == "vfo_a":
                return (self.memobj.vfo_a_band[num], True, unique_idx)
            elif item_type == "vfo_b":
                return (self.memobj.vfo_b_band[num], True, unique_idx)
            else:
                raise errors.InvalidDataError("unknown special channel type '%s'" % item_type)
        except KeyError:
            return (self.memobj.memory[number], False, number)

    def get_raw_memory(self, number):
        (mem_item, special, unique_idx) = self.get_mem_item(number)
        return repr(mem_item)

    def get_memory(self, number):
        mem = chirp_common.Memory()

        (mem_item, special, unique_idx) = self.get_mem_item(number)

        freq = self.freq_icom2chirp(mem_item.freq, mem_item.freq_mult)
        if freq == 0:
            mem.empty = True
        else:
            mem.empty = False
            mem.freq = freq
            if special:
                mem.name = " " * NAME_LENGTH
            else:
                mem.name = str(mem_item.name).rstrip("\x00 ")
            mem.rtone = chirp_common.TONES[(mem_item.tx_tone_hi << 4) + mem_item.tx_tone_lo]
            mem.ctone = chirp_common.TONES[mem_item.rx_tone]
            mem.dtcs = chirp_common.DTCS_CODES[mem_item.dtcs]
            mem.dtcs_polarity = DTCS_POLARITY[mem_item.dtcs_polarity]
            mem.offset = self.freq_icom2chirp(mem_item.offset_freq, mem_item.offset_freq_mult)
            mem.duplex = DUPLEX[mem_item.duplex]
            mem.tmode = TONE_MODE[mem_item.tone_mode]
            mem.tuning_step = TUNE_STEP[mem_item.tune_step]
            mem.mode = MODE[mem_item.mode]
            if not special:
                mem.skip = self.get_skip(number)
        if special:
            mem.extd_number = number
            mem.number = -len(self.special) + unique_idx
        else:
            mem.number = number

        return mem

    def set_memory(self, memory):
        (mem_item, special, unique_idx) = self.get_mem_item(
            memory.extd_number or memory.number)
        if memory.empty:
            mem_item.set_raw("\x00" * MEM_ITEM_SIZE)
            self.clear_bank(memory.number)
            self.memobj.banks[memory.number].invisible_channel = 1
        else:
            (mem_item.freq, mem_item.freq_mult) = self.freq_chirp2icom(memory.freq)
            if special:
                mem_item.name = " " * NAME_LENGTH
            else:
                self.memobj.banks[memory.number].invisible_channel = 0

                for x in range(NAME_LENGTH):
                    try:
                        mem_item.name[x] = str(memory.name[x])
                    except IndexError:
                        mem_item.name[x] = " "
            mem_item.tx_tone_hi = chirp_common.TONES.index(memory.rtone) >> 4
            mem_item.tx_tone_lo = chirp_common.TONES.index(memory.rtone) & 0x0f
            mem_item.rx_tone = chirp_common.TONES.index(memory.ctone)
            mem_item.dtcs = chirp_common.DTCS_CODES.index(memory.dtcs)
            mem_item.dtcs_polarity = DTCS_POLARITY.index(memory.dtcs_polarity)
            (mem_item.offset_freq, mem_item.offset_freq_mult) = self.freq_chirp2icom(memory.offset)
            mem_item.duplex = DUPLEX.index(memory.duplex)
            mem_item.tone_mode = TONE_MODE.index(memory.tmode)
            mem_item.tune_step = TUNE_STEP.index(memory.tuning_step)
            mem_item.mode = MODE.index(memory.mode)
            if not special:
                self.set_skip(memory.number, memory.skip)

    def get_bank_model(self):
        return ICx90BankModel(self)


class ICx90Radio_ham(ICx90Radio):
    VARIANT = 'Radio'

    def get_features(self):
        rf = ICx90Radio.get_features(self)
        rf.has_sub_devices = False

        return rf


class ICx90Radio_tv(ICx90Radio):
    VARIANT = "TV"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_name = True
        rf.has_bank = False
        rf.has_bank_index = False
        rf.has_bank_names = False
        rf.can_delete = True
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False
        rf.has_comment = False
        rf.has_sub_devices = False
        rf.memory_bounds = (0, TV_CHANNELS - 1)
        rf.valid_characters = CHARSET
        rf.valid_modes = list(TV_MODE)
        rf.valid_tmodes = []
        rf.valid_duplexes = [""]
        rf.valid_tuning_steps = []
        rf.valid_bands = [(46750000, 957750000)]
        rf.valid_skips = ["", "S"]
        rf.valid_name_length = TV_NAME_LENGTH
        rf.valid_special_chans = []

        return rf

    def get_bank_model(self):
        return None

    def freq_chirp2icom(self, freq):
        return freq / 5000

    def freq_icom2chirp(self, freq):
        return freq * 5000

    def get_skip(self, number):
        if self.memobj.tv_channel_skip[number] == 2:
            return "S"
        return ""

    def set_skip(self, number, skip):
        if skip == "S":
            self.memobj.tv_channel_skip[number] = 2
        elif skip == "":
            self.memobj.tv_channel_skip[number] = 0
        else:
            raise errors.InvalidDataError("skip '%s' not supported" % skip)

    def get_raw_memory(self, number):
        return repr(self.memobj.tv_memory[number])

    def get_memory(self, number):
        mem = chirp_common.Memory()

        mem_item = self.memobj.tv_memory[number]

        mem.freq = self.freq_icom2chirp(mem_item.freq)
        if self.memobj.tv_channel_skip[number] == 1:
            mem.empty = True
            mem.mode = TV_MODE[0]
        else:
            mem.empty = False
            mem.name = str(mem_item.name).rstrip("\x00 ")
            mem.mode = TV_MODE[mem_item.mode]
            mem.skip = self.get_skip(number)
        mem.number = number

        return mem

    def set_memory(self, memory):
        mem_item = self.memobj.tv_memory[memory.number]
        if memory.empty:
            self.memobj.tv_channel_skip[memory.number] = 1
            mem_item.set_raw("\x00" * TV_MEM_ITEM_SIZE)
        else:
            mem_item.freq = self.freq_chirp2icom(memory.freq)
            for x in range(TV_NAME_LENGTH):
                try:
                    mem_item.name[x] = str(memory.name[x])
                except IndexError:
                    mem_item.name[x] = " "

            mem_item.mode = TV_MODE.index(memory.mode)
            self.set_skip(memory.number, memory.skip)


def dump_banks(icx90, template_file):
    mb = icx90.get_features().memory_bounds
    with open(template_file, "w") as f:
        for mi in range(mb[0], mb[1] + 1):
            mem = icx90.get_memory(mi)
            bank = icx90._get_bank(mi)
            if bank is not None:
                bank = BANK_INDEX[bank]
            bank_pos = icx90._get_bank_index(mi)
            if not mem.empty and bank is not None and bank_pos is not None:
                f.write("%s;%s;%d\n" % (mem.name, bank, bank_pos))


def read_template_file(template_file):
    banks_templ = {}
    with open(template_file, "r") as f:
        for line in f:
            l = line.split(";")
            l[1] = BANK_INDEX.index(l[1])
            banks_templ[l[0]] = l[1:]
    return banks_templ


def reorder_banks(icx90, preserve_position, preserve_unknown, banks_templ):
    banks_cnt = []
    mb = icx90.get_features().memory_bounds
    for i in range(0, BANKS):
        banks_cnt.append(0)
    for mi in range(mb[0], mb[1] + 1):
        mem = icx90.get_memory(mi)
        if preserve_unknown:
            bank = icx90._get_bank(mi)
            bank_pos = icx90._get_bank_index(mi)
        else:
            bank = None
            bank_pos = 0
        if not mem.empty:
            if mem.name in banks_templ:
                bank = int(banks_templ[mem.name][0])
                if preserve_position:
                    bank_pos = int(banks_templ[mem.name][1])
                else:
                    bank_pos = banks_cnt[bank]
                    banks_cnt[bank] += 1
                print("%s\t-> %s, %02d" % (mem.name, BANK_INDEX[bank], bank_pos))
            # explicitly set non empty channel as visible
            icx90.memobj.banks[mi].invisible_channel = 0
        if bank >= BANKS or bank_pos >= BANK_NUM:
            bank = None
            bank_pos = 0
        icx90._set_bank(mi, bank)
        icx90._set_bank_index(mi, bank_pos)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Icom IC-E90 banks handling helper.")
    parser.add_argument("icx90_img_file", help="IC-X90 IMG file.")
    parser.add_argument("template_file", help="Banks template file.")
    parser.add_argument("-r", "--read-banks", action="store_true",
                        help="Read banks content and store it to template file.")
    parser.add_argument("-f", "--fix-banks", action="store_true",
                        help="Fix banks content, reorder channels in banks according to the provided template file and write it to IMG file.")
    parser.add_argument("-p", "--preserve-position", action="store_true",
                        help="Preserve bank position as in the template file if possible, otherwise put channels to banks according their position in the memory.")
    parser.add_argument("-u", "--preserve-unknown", action="store_true",
                        help="Preserve channels in banks if they aren't in the template file and don't conflicts with the template file, otherwise remove them from the banks.")
    parser.add_argument("-b", "--backup_img", action="store_true",
                        help="Backup IMG file before changing it.")

    args = vars(parser.parse_args())

    options_ok = True
    try:
        icx90_img_file = str(args.pop("icx90_img_file"))
        template_file = str(args.pop("template_file"))
    except KeyError:
        options_ok = False

    if options_ok and (args["read_banks"] or args["fix_banks"]):
        icx90 = ICx90Radio(icx90_img_file)
        if args["read_banks"]:
            dump_banks(icx90, template_file)
        elif args["fix_banks"]:
            banks_templ = read_template_file(template_file)
            if args["backup_img"]:
                icx90.save_mmap(icx90_img_file + ".bak")
            reorder_banks(icx90, args["preserve_position"], args["preserve_unknown"], banks_templ)
            icx90.save_mmap(icx90_img_file)
    else:
        parser.print_help()
