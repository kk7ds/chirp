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

import re
import logging

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings
from chirp.settings import RadioSettingValueInteger, RadioSettingValueString
from chirp.settings import RadioSettingValueList, RadioSettingValueBoolean

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x047f;
struct {
  u8 flag;
  u16 unknown;
  struct {
    u8 padded_yaesu[16];
  } message;
} opening_message;

#seekto 0x049a;
struct {
  u8 vfo_a;
  u8 vfo_b;
} squelch;

#seekto 0x04bf;
struct {
  u8 beep;
} beep_select;

#seekto 0x04cc;
struct {
  u8 lcd_dimmer;
  u8 dtmf_delay;
  u8 unknown0[3];
  u8 unknown1:4,
     lcd_contrast:4;
  u8 lamp;
  u8 unknown2[7];
  u8 scan_restart;
  u8 unknown3;
  u8 scan_resume;
  u8 unknown4[6];
  u8 tot;
  u8 unknown5[3];
  u8 unknown6:2,
     scan_lamp:1,
     unknown7:2,
     dtmf_speed:1,
     unknown8:1,
     dtmf_mode:1;
  u8 busy_led:1,
     unknown9:7;
  u8 unknown10[2];
  u8 vol_mode:1,
     unknown11:7;
} scan_settings;

#seekto 0x54a;
struct {
    u16 in_use;
} bank_used[24];

#seekto 0x064a;
struct {
  u8 unknown0[4];
  u8 frequency_band;
  u8 unknown1:6,
     manual_or_mr:2;
  u8 unknown2:7,
     mr_banks:1;
  u8 unknown3;
  u16 mr_index;
  u16 bank_index;
  u16 bank_enable;
  u8 unknown4[5];
  u8 unknown5:6,
     power:2;
  u8 unknown6:4,
     tune_step:4;
  u8 unknown7:6,
     duplex:2;
  u8 unknown8:6,
     tone_mode:2;
  u8 unknown9:2,
     tone:6;
  u8 unknown10;
  u8 unknown11:6,
     mode:2;
  bbcd freq0[4];
  bbcd offset_freq[4];
  u8 unknown12[2];
  char label[16];
  u8 unknown13[6];
  bbcd band_lower[4];
  bbcd band_upper[4];
  bbcd rx_freq[4];
  u8 unknown14[22];
  bbcd freq1[4];
  u8 unknown15[11];
  u8 unknown16:3,
     volume:5;
  u8 unknown17[18];
  u8 active_menu_item;
  u8 checksum;
} vfo_info[6];

#seekto 0x094a;
struct {
  u8 memory[16];
} dtmf[10];

#seekto 0x135A;
struct {
  u8 unknown[2];
  u8 name[16];
} bank_info[24];

#seekto 0x198a;
struct {
    u16 channel[100];
} bank_members[24];

#seekto 0x2C4A;
struct {
  u8 nosubvfo:1,
     unknown:3,
     pskip:1,
     skip:1,
     used:1,
     valid:1;
} flag[900];

#seekto 0x328A;
struct {
  u8 unknown1a:2,
     half_deviation:1, // This is not really right, maybe auto?
     unknown1b:5;
  u8 mode:2,
     duplex:2,
     tune_step:4;
  bbcd freq[3];
  u8 power:2,
     unknown2:4,
     tone_mode:2;
  u8 charsetbits[2];
  char label[16];
  bbcd offset[3];
  u8 unknown5:2,
     tone:6;
  u8 unknown6:1,
     dcs:7;
  u8 pr_frequency;
  u8 unknown7;
  u8 unknown8a:3,
     unknown8b:1,
     rx_mode_auto:1,
     unknown8c:3;
} memory[900];

#seekto 0xC0CA;
struct {
  u8 unknown0:6,
     rx_baud:2;
  u8 unknown1:4,
     tx_delay:4;
  u8 custom_symbol;
  u8 unknown2;
  struct {
    char callsign[6];
    u8 ssid;
  } my_callsign;
  u8 unknown3:4,
     selected_position_comment:4;
  u8 unknown4;
  u8 set_time_manually:1,
     tx_interval_beacon:1,
     ring_beacon:1,
     ring_msg:1,
     aprs_mute:1,
     unknown6:1,
     tx_smartbeacon:1,
     af_dual:1;
  u8 unknown7:1,
     aprs_units_wind_mph:1,
     aprs_units_rain_inch:1,
     aprs_units_temperature_f:1,
     aprs_units_altitude_ft:1,
     unknown8:1,
     aprs_units_distance_m:1,
     aprs_units_position_mmss:1;
  u8 unknown9:6,
     aprs_units_speed:2;
  u8 unknown11:1,
     filter_other:1,
     filter_status:1,
     filter_item:1,
     filter_object:1,
     filter_weather:1,
     filter_position:1,
     filter_mic_e:1;
  u8 unknown12:2,
     timezone:6;
  u8 unknown13:4,
     beacon_interval:4;
  u8 unknown14;
  u8 unknown15:7,
     latitude_sign:1;
  u8 latitude_degree;
  u8 latitude_minute;
  u8 latitude_second;
  u8 unknown16:7,
     longitude_sign:1;
  u8 longitude_degree;
  u8 longitude_minute;
  u8 longitude_second;
  u8 unknown17:4,
     selected_position:4;
  u8 unknown18:5,
     selected_beacon_status_txt:3;
  u8 unknown19:6,
     gps_units_altitude_ft:1,
     gps_units_position_sss:1;
  u8 unknown20:6,
     gps_units_speed:2;
  u8 unknown21[4];
  struct {
    struct {
      char callsign[6];
      u8 ssid;
    } entry[8];
  } digi_path_7;
  u8 unknown22[2];
} aprs;

#seekto 0x%04X;
struct {
  char padded_string[16];
} aprs_msg_macro[%d];

#seekto 0x%04X;
struct {
  u8 unknown23:5,
     selected_msg_group:3;
  u8 unknown24;
  struct {
    char padded_string[9];
  } msg_group[8];
  u8 unknown25[4];
  u8 active_smartbeaconing;
  struct {
    u8 low_speed_mph;
    u8 high_speed_mph;
    u8 slow_rate_min;
    u8 fast_rate_sec;
    u8 turn_angle;
    u8 turn_slop;
    u8 turn_time_sec;
  } smartbeaconing_profile[3];
  u8 unknown26:2,
     flash_msg:6;
  u8 unknown27:2,
     flash_grp:6;
  u8 unknown28:2,
     flash_bln:6;
  u8 selected_digi_path;
  struct {
    struct {
      char callsign[6];
      u8 ssid;
    } entry[2];
  } digi_path_3_6[4];
  u8 unknown30:6,
     selected_my_symbol:2;
  u8 unknown31[3];
  u8 unknown32:2,
     vibrate_msg:6;
  u8 unknown33:2,
     vibrate_grp:6;
  u8 unknown34:2,
     vibrate_bln:6;
} aprs2;

#seekto 0x%04X;
struct {
  bbcd date[3];
  u8 unknown1;
  bbcd time[2];
  u8 sequence;
  u8 unknown2;
  u8 sender_callsign[7];
  u8 data_type;
  u8 yeasu_data_type;
  u8 unknown3;
  u8 unknown4:1,
     callsign_is_ascii:1,
     unknown5:6;
  u8 unknown6;
  u16 pkt_len;
  u16 in_use;
} aprs_beacon_meta[%d];

#seekto 0x%04X;
struct {
  u8 dst_callsign[6];
  u8 dst_callsign_ssid;
  u8 src_callsign[6];
  u8 src_callsign_ssid;
  u8 path_and_body[%d];
} aprs_beacon_pkt[%d];

#seekto 0xf92a;
struct {
  char padded_string[60];
} aprs_beacon_status_txt[5];

#seekto 0xFECA;
u8 checksum;
"""

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "AM", "WFM"]
STEPS = [5.0, 6.25, 8.33, 9.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0,
         100.0, 200.0]
SKIPS = ["", "S", "P"]
VX8_DTMF_CHARS = list("0123456789ABCD*#-")

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    [" "] + \
    [chr(x) for x in range(ord("a"), ord("z")+1)] + \
    list(".,:;*#_-/&()@!?^ ") + list("\x00" * 100)

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("L3", watts=2.50),
                chirp_common.PowerLevel("L2", watts=1.00),
                chirp_common.PowerLevel("L1", watts=0.05)]


class VX8Bank(chirp_common.NamedBank):
    """A VX-8 bank"""

    def get_name(self):
        _bank = self._model._radio._memobj.bank_info[self.index]
        _bank_used = self._model._radio._memobj.bank_used[self.index]

        name = ""
        for i in _bank.name:
            if i == 0xFF:
                break
            name += CHARSET[i & 0x7F]
        return name.rstrip()

    def set_name(self, name):
        _bank = self._model._radio._memobj.bank_info[self.index]
        _bank.name = [CHARSET.index(x) for x in name.ljust(16)[:16]]


class VX8BankModel(chirp_common.BankModel):
    """A VX-8 bank model"""
    def __init__(self, radio, name='Banks'):
        super(VX8BankModel, self).__init__(radio, name)

        _banks = self._radio._memobj.bank_info
        self._bank_mappings = []
        for index, _bank in enumerate(_banks):
            bank = VX8Bank(self, "%i" % index, "BANK-%i" % index)
            bank.index = index
            self._bank_mappings.append(bank)

    def get_num_mappings(self):
        return len(self._bank_mappings)

    def get_mappings(self):
        return self._bank_mappings

    def _channel_numbers_in_bank(self, bank):
        _bank_used = self._radio._memobj.bank_used[bank.index]
        if _bank_used.in_use == 0xFFFF:
            return set()

        _members = self._radio._memobj.bank_members[bank.index]
        return set([int(ch) + 1 for ch in _members.channel if ch != 0xFFFF])

    def update_vfo(self):
        chosen_bank = [None, None]
        chosen_mr = [None, None]

        flags = self._radio._memobj.flag

        # Find a suitable bank and MR for VFO A and B.
        for bank in self.get_mappings():
            for channel in self._channel_numbers_in_bank(bank):
                chosen_bank[0] = bank.index
                chosen_mr[0] = channel
                if not flags[channel].nosubvfo:
                    chosen_bank[1] = bank.index
                    chosen_mr[1] = channel
                    break
            if chosen_bank[1]:
                break

        for vfo_index in (0, 1):
            # 3 VFO info structs are stored as 3 pairs of (master, backup)
            vfo = self._radio._memobj.vfo_info[vfo_index * 2]
            vfo_bak = self._radio._memobj.vfo_info[(vfo_index * 2) + 1]

            if vfo.checksum != vfo_bak.checksum:
                LOG.warn("VFO settings are inconsistent with backup")
            else:
                if ((chosen_bank[vfo_index] is None) and
                        (vfo.bank_index != 0xFFFF)):
                    LOG.info("Disabling banks for VFO %d" % vfo_index)
                    vfo.bank_index = 0xFFFF
                    vfo.mr_index = 0xFFFF
                    vfo.bank_enable = 0xFFFF
                elif ((chosen_bank[vfo_index] is not None) and
                        (vfo.bank_index == 0xFFFF)):
                    LOG.debug("Enabling banks for VFO %d" % vfo_index)
                    vfo.bank_index = chosen_bank[vfo_index]
                    vfo.mr_index = chosen_mr[vfo_index]
                    vfo.bank_enable = 0x0000
                vfo_bak.bank_index = vfo.bank_index
                vfo_bak.mr_index = vfo.mr_index
                vfo_bak.bank_enable = vfo.bank_enable

    def _update_bank_with_channel_numbers(self, bank, channels_in_bank):
        _members = self._radio._memobj.bank_members[bank.index]
        if len(channels_in_bank) > len(_members.channel):
            raise Exception("Too many entries in bank %d" % bank.index)

        empty = 0
        for index, channel_number in enumerate(sorted(channels_in_bank)):
            _members.channel[index] = channel_number - 1
            empty = index + 1
        for index in range(empty, len(_members.channel)):
            _members.channel[index] = 0xFFFF

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._channel_numbers_in_bank(bank)
        channels_in_bank.add(memory.number)
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        _bank_used = self._radio._memobj.bank_used[bank.index]
        _bank_used.in_use = 0x06

        self.update_vfo()

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        if not channels_in_bank:
            _bank_used = self._radio._memobj.bank_used[bank.index]
            _bank_used.in_use = 0xFFFF

        self.update_vfo()

    def get_mapping_memories(self, bank):
        memories = []
        for channel in self._channel_numbers_in_bank(bank):
            memories.append(self._radio.get_memory(channel))

        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._channel_numbers_in_bank(bank):
                banks.append(bank)

        return banks


def _wipe_memory(mem):
    mem.set_raw("\x00" * (mem.size() // 8))


@directory.register
class VX8Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-8"""
    BAUD_RATE = 38400
    VENDOR = "Yaesu"
    MODEL = "VX-8R"

    _model = b"AH029"
    _memsize = 65227
    _block_lengths = [10, 65217]
    _block_size = 32
    _mem_params = (0xC128,  # APRS message macros
                   5,       # Number of message macros
                   0xC178,  # APRS2
                   0xC24A,  # APRS beacon metadata address.
                   40,      # Number of beacons stored.
                   0xC60A,  # APRS beacon content address.
                   194,     # Length of beacon data stored.
                   40)      # Number of beacons stored.
    _has_vibrate = False
    _has_af_dual = True

    _SG_RE = re.compile(r"(?P<sign>[-+NESW]?)(?P<d>[\d]+)[\s\.,]*"
                        r"(?P<m>[\d]*)[\s\']*(?P<s>[\d]*)")

    _RX_BAUD = ("off", "1200 baud", "9600 baud")
    _TX_DELAY = ("100ms", "200ms", "300ms",
                 "400ms", "500ms", "750ms", "1000ms")
    _WIND_UNITS = ("m/s", "mph")
    _RAIN_UNITS = ("mm", "inch")
    _TEMP_UNITS = ("C", "F")
    _ALT_UNITS = ("m", "ft")
    _DIST_UNITS = ("km", "mile")
    _POS_UNITS = ("dd.mmmm'", "dd mm'ss\"")
    _SPEED_UNITS = ("km/h", "knot", "mph")
    _TIME_SOURCE = ("manual", "GPS")
    _TZ = ("-13:00", "-13:30", "-12:00", "-12:30", "-11:00", "-11:30",
           "-10:00", "-10:30", "-09:00", "-09:30", "-08:00", "-08:30",
           "-07:00", "-07:30", "-06:00", "-06:30", "-05:00", "-05:30",
           "-04:00", "-04:30", "-03:00", "-03:30", "-02:00", "-02:30",
           "-01:00", "-01:30", "-00:00", "-00:30", "+01:00", "+01:30",
           "+02:00", "+02:30", "+03:00", "+03:30", "+04:00", "+04:30",
           "+05:00", "+05:30", "+06:00", "+06:30", "+07:00", "+07:30",
           "+08:00", "+08:30", "+09:00", "+09:30", "+10:00", "+10:30",
           "+11:00", "+11:30")
    _BEACON_TYPE = ("Off", "Interval")
    _BEACON_INT = ("15s", "30s", "1m", "2m", "3m", "5m", "10m", "15m",
                   "30m")
    _DIGI_PATHS = ("OFF", "WIDE1-1", "WIDE1-1, WIDE2-1", "Digi Path 4",
                   "Digi Path 5", "Digi Path 6", "Digi Path 7", "Digi Path 8")
    _MSG_GROUP_NAMES = ("Message Group 1", "Message Group 2",
                        "Message Group 3", "Message Group 4",
                        "Message Group 5", "Message Group 6",
                        "Message Group 7", "Message Group 8")
    _POSITIONS = ("GPS", "Manual Latitude/Longitude",
                  "Manual Latitude/Longitude", "P1", "P2", "P3", "P4",
                  "P5", "P6", "P7", "P8", "P9", "P10")
    _FLASH = ("OFF", "ON")
    _BEEP_SELECT = ("Off", "Key+Scan", "Key")
    _SQUELCH = ["%d" % x for x in range(0, 16)]
    _VOLUME = ["%d" % x for x in range(0, 33)]
    _OPENING_MESSAGE = ("Off", "DC", "Message", "Normal")
    _SCAN_RESUME = ["%.1fs" % (0.5 * x) for x in range(4, 21)] + \
                   ["Busy", "Hold"]
    _SCAN_RESTART = ["%.1fs" % (0.1 * x) for x in range(1, 10)] + \
                    ["%.1fs" % (0.5 * x) for x in range(2, 21)]
    _LAMP_KEY = ["Key %d sec" % x for x in range(2, 11)] + \
                ["Continuous", "OFF"]
    _LCD_CONTRAST = ["Level %d" % x for x in range(1, 33)]
    _LCD_DIMMER = ["Level %d" % x for x in range(1, 5)]
    _TOT_TIME = ["Off"] + ["%.1f min" % (0.5 * x) for x in range(1, 21)]
    _OFF_ON = ("Off", "On")
    _VOL_MODE = ("Normal", "Auto Back")
    _DTMF_MODE = ("Manual", "Auto")
    _DTMF_SPEED = ("50ms", "100ms")
    _DTMF_DELAY = ("50ms", "250ms", "450ms", "750ms", "1000ms")
    _MY_SYMBOL = ("/[ Person", "/b Bike", "/> Car", "User selected")

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to DATA jack.\n"
            "3. Press and hold in the [FW] key while turning the radio on\n"
            "     (\"CLONE\" will appear on the display).\n"
            "4. <b>After clicking OK</b>, press the [BAND] key to send"
            " image.\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect cable to DATA jack.\n"
            "3. Press and hold in the [FW] key while turning the radio on\n"
            "     (\"CLONE\" will appear on the display).\n"
            "4. Press the [MODE] key (\"-WAIT-\" will appear on the LCD).\n")
        return rp

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(500000, 999900000)]
        rf.valid_skips = SKIPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 16
        rf.memory_bounds = (1, 900)
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_bank_names = True
        rf.has_settings = True
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x064A, 0x06C8),
                yaesu_clone.YaesuChecksum(0x06CA, 0x0748),
                yaesu_clone.YaesuChecksum(0x074A, 0x07C8),
                yaesu_clone.YaesuChecksum(0x07CA, 0x0848),
                yaesu_clone.YaesuChecksum(0x0000, 0xFEC9)]

    @staticmethod
    def _add_ff_pad(val, length):
        return val.ljust(length, "\xFF")[:length]

    @classmethod
    def _strip_ff_pads(cls, messages):
        result = []
        for msg_text in messages:
            result.append(str(msg_text).rstrip("\xFF"))
        return result

    def get_memory(self, number):
        flag = self._memobj.flag[number-1]
        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number
        if not flag.used:
            mem.empty = True
        if not flag.valid:
            mem.empty = True
            return mem
        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tone_mode]
        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.power = POWER_LEVELS[3 - _mem.power]
        mem.skip = flag.pskip and "P" or flag.skip and "S" or ""

        charset = ''.join(CHARSET).ljust(256, '.')
        mem.name = str(_mem.label).rstrip("\xFF").translate(charset).rstrip()

        return mem

    def _debank(self, mem):
        bm = self.get_bank_model()
        for bank in bm.get_memory_mappings(mem):
            bm.remove_memory_from_mapping(mem, bank)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        flag = self._memobj.flag[mem.number-1]

        self._debank(mem)

        if not mem.empty and not flag.valid:
            _wipe_memory(_mem)

        if mem.empty and flag.valid and not flag.used:
            flag.valid = False
            return
        flag.used = not mem.empty
        flag.valid = flag.used

        if mem.empty:
            return

        if mem.freq < 30000000 or \
                (mem.freq > 88000000 and mem.freq < 108000000) or \
                mem.freq > 580000000:
            flag.nosubvfo = True   # Masked from VFO B
        else:
            flag.nosubvfo = False  # Available in both VFOs

        _mem.freq = int(mem.freq / 1000)
        _mem.offset = int(mem.offset / 1000)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tone_mode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.half_deviation = 0
        _mem.mode = MODES.index(mem.mode)
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        if mem.power:
            _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        label = "".join([chr(CHARSET.index(x)) for x in mem.name.rstrip()])
        _mem.label = self._add_ff_pad(label, 16)
        # We only speak English here in chirpville
        _mem.charsetbits[0] = 0x00
        _mem.charsetbits[1] = 0x00

        flag.skip = mem.skip == "S"
        flag.pskip = mem.skip == "P"

    def get_bank_model(self):
        return VX8BankModel(self)

    @classmethod
    def _digi_path_to_str(cls, path):
        path_cmp = []
        for entry in path.entry:
            callsign = str(entry.callsign).rstrip("\xFF")
            if not callsign:
                break
            path_cmp.append("%s-%d" % (callsign, entry.ssid))
        return ",".join(path_cmp)

    @staticmethod
    def _latlong_sanity(sign, l_d, l_m, l_s, is_lat):
        if sign not in (0, 1):
            sign = 0
        if is_lat:
            d_max = 90
        else:
            d_max = 180
        if l_d < 0 or l_d > d_max:
            l_d = 0
            l_m = 0
            l_s = 0
        if l_m < 0 or l_m > 60:
            l_m = 0
            l_s = 0
        if l_s < 0 or l_s > 60:
            l_s = 0
        return sign, l_d, l_m, l_s

    @classmethod
    def _latlong_to_str(cls, sign, l_d, l_m, l_s, is_lat, to_sexigesimal=True):
        sign, l_d, l_m, l_s = cls._latlong_sanity(sign, l_d, l_m, l_s, is_lat)
        mult = sign and -1 or 1
        if to_sexigesimal:
            return "%d,%d'%d\"" % (mult * l_d, l_m, l_s)
        return "%0.5f" % (mult * l_d + (l_m / 60.0) + (l_s / (60.0 * 60.0)))

    @classmethod
    def _str_to_latlong(cls, lat_long, is_lat):
        sign = 0
        result = [0, 0, 0]

        lat_long = lat_long.strip()

        if not lat_long:
            return 1, 0, 0, 0

        try:
            # DD.MMMMM is the simple case, try that first.
            val = float(lat_long)
            if val < 0:
                sign = 1
            val = abs(val)
            result[0] = int(val)
            result[1] = int(val * 60) % 60
            result[2] = int(val * 3600) % 60
        except ValueError:
            # Try DD MM'SS" if DD.MMMMM failed.
            match = cls._SG_RE.match(lat_long.strip())
            if match:
                if match.group("sign") and (match.group("sign") in "SE-"):
                    sign = 1
                else:
                    sign = 0
                if match.group("d"):
                    result[0] = int(match.group("d"))
                if match.group("m"):
                    result[1] = int(match.group("m"))
                if match.group("s"):
                    result[2] = int(match.group("s"))
            elif len(lat_long) > 4:
                raise Exception("Lat/Long should be DD MM'SS\" or DD.MMMMM")

        return cls._latlong_sanity(sign, result[0], result[1], result[2],
                                   is_lat)

    def _get_aprs_general_settings(self):
        menu = RadioSettingGroup("aprs_general", "APRS General")
        aprs = self._memobj.aprs
        aprs2 = self._memobj.aprs2

        val = RadioSettingValueString(
                0, 6, str(aprs.my_callsign.callsign).rstrip("\xFF"))
        rs = RadioSetting("aprs.my_callsign.callsign", "My Callsign", val)
        rs.set_apply_callback(self.apply_callsign, aprs.my_callsign)
        menu.append(rs)

        val = RadioSettingValueList(
            chirp_common.APRS_SSID,
            current_index=aprs.my_callsign.ssid)
        rs = RadioSetting("aprs.my_callsign.ssid", "My SSID", val)
        menu.append(rs)

        val = RadioSettingValueList(self._MY_SYMBOL,
                                    current_index=aprs2.selected_my_symbol)
        rs = RadioSetting("aprs2.selected_my_symbol", "My Symbol", val)
        menu.append(rs)

        symbols = list(chirp_common.APRS_SYMBOLS)
        selected = aprs.custom_symbol
        if aprs.custom_symbol >= len(chirp_common.APRS_SYMBOLS):
            symbols.append("%d" % aprs.custom_symbol)
            selected = len(symbols) - 1
        val = RadioSettingValueList(symbols, current_index=selected)
        rs = RadioSetting("aprs.custom_symbol_text", "User Selected Symbol",
                          val)
        rs.set_apply_callback(self.apply_custom_symbol, aprs)
        menu.append(rs)

        val = RadioSettingValueList(
            chirp_common.APRS_POSITION_COMMENT,
            current_index=aprs.selected_position_comment)
        rs = RadioSetting("aprs.selected_position_comment", "Position Comment",
                          val)
        menu.append(rs)

        latitude = self._latlong_to_str(aprs.latitude_sign,
                                        aprs.latitude_degree,
                                        aprs.latitude_minute,
                                        aprs.latitude_second,
                                        True, aprs.aprs_units_position_mmss)
        longitude = self._latlong_to_str(aprs.longitude_sign,
                                         aprs.longitude_degree,
                                         aprs.longitude_minute,
                                         aprs.longitude_second,
                                         False, aprs.aprs_units_position_mmss)

        # TODO: Rebuild this when aprs_units_position_mmss changes.
        # TODO: Rebuild this when latitude/longitude change.
        # TODO: Add saved positions p1 - p10 to memory map.
        position_str = list(self._POSITIONS)
        # position_str[1] = "%s %s" % (latitude, longitude)
        # position_str[2] = "%s %s" % (latitude, longitude)
        val = RadioSettingValueList(position_str,
                                    current_index=aprs.selected_position)
        rs = RadioSetting("aprs.selected_position", "My Position", val)
        menu.append(rs)

        val = RadioSettingValueString(0, 10, latitude)
        rs = RadioSetting("latitude", "Manual Latitude", val)
        rs.set_apply_callback(self.apply_lat_long, aprs)
        menu.append(rs)

        val = RadioSettingValueString(0, 11, longitude)
        rs = RadioSetting("longitude", "Manual Longitude", val)
        rs.set_apply_callback(self.apply_lat_long, aprs)
        menu.append(rs)

        val = RadioSettingValueList(
                self._TIME_SOURCE, current_index=aprs.set_time_manually)
        rs = RadioSetting("aprs.set_time_manually", "Time Source", val)
        menu.append(rs)

        val = RadioSettingValueList(self._TZ, current_index=aprs.timezone)
        rs = RadioSetting("aprs.timezone", "Timezone", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._SPEED_UNITS, current_index=aprs.aprs_units_speed)
        rs = RadioSetting("aprs.aprs_units_speed", "APRS Speed Units", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._SPEED_UNITS, current_index=aprs.gps_units_speed)
        rs = RadioSetting("aprs.gps_units_speed", "GPS Speed Units", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._ALT_UNITS, current_index=aprs.aprs_units_altitude_ft)
        rs = RadioSetting("aprs.aprs_units_altitude_ft", "APRS Altitude Units",
                          val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._ALT_UNITS, current_index=aprs.gps_units_altitude_ft)
        rs = RadioSetting("aprs.gps_units_altitude_ft", "GPS Altitude Units",
                          val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._POS_UNITS,
                current_index=aprs.aprs_units_position_mmss)
        rs = RadioSetting("aprs.aprs_units_position_mmss",
                          "APRS Position Format", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._POS_UNITS, current_index=aprs.gps_units_position_sss)
        rs = RadioSetting("aprs.gps_units_position_sss",
                          "GPS Position Format", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._DIST_UNITS,
                current_index=aprs.aprs_units_distance_m)
        rs = RadioSetting("aprs.aprs_units_distance_m", "APRS Distance Units",
                          val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._WIND_UNITS, current_index=aprs.aprs_units_wind_mph)
        rs = RadioSetting("aprs.aprs_units_wind_mph", "APRS Wind Speed Units",
                          val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._RAIN_UNITS, current_index=aprs.aprs_units_rain_inch)
        rs = RadioSetting("aprs.aprs_units_rain_inch", "APRS Rain Units", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._TEMP_UNITS,
                current_index=aprs.aprs_units_temperature_f)
        rs = RadioSetting("aprs.aprs_units_temperature_f",
                          "APRS Temperature Units", val)
        menu.append(rs)

        return menu

    def _get_aprs_rx_settings(self):
        menu = RadioSettingGroup("aprs_rx", "APRS Receive")
        aprs = self._memobj.aprs
        aprs2 = self._memobj.aprs2

        val = RadioSettingValueList(self._RX_BAUD, current_index=aprs.rx_baud)
        rs = RadioSetting("aprs.rx_baud", "Modem RX", val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.aprs_mute)
        rs = RadioSetting("aprs.aprs_mute", "APRS Mute", val)
        menu.append(rs)

        if self._has_af_dual:
            val = RadioSettingValueBoolean(aprs.af_dual)
            rs = RadioSetting("aprs.af_dual", "AF Dual", val)
            menu.append(rs)

        val = RadioSettingValueBoolean(aprs.ring_msg)
        rs = RadioSetting("aprs.ring_msg", "Ring on Message RX", val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.ring_beacon)
        rs = RadioSetting("aprs.ring_beacon", "Ring on Beacon RX", val)
        menu.append(rs)

        val = RadioSettingValueList(self._FLASH,
                                    current_index=aprs2.flash_msg)
        rs = RadioSetting("aprs2.flash_msg", "Flash on personal message", val)
        menu.append(rs)

        if self._has_vibrate:
            val = RadioSettingValueList(self._FLASH,
                                        current_index=aprs2.vibrate_msg)
            rs = RadioSetting("aprs2.vibrate_msg",
                              "Vibrate on personal message", val)
            menu.append(rs)

        val = RadioSettingValueList(self._FLASH[:10],
                                    current_index=aprs2.flash_bln)
        rs = RadioSetting("aprs2.flash_bln", "Flash on bulletin message", val)
        menu.append(rs)

        if self._has_vibrate:
            val = RadioSettingValueList(self._FLASH[:10],
                                        current_index=aprs2.vibrate_bln)
            rs = RadioSetting("aprs2.vibrate_bln",
                              "Vibrate on bulletin message", val)
            menu.append(rs)

        val = RadioSettingValueList(self._FLASH[:10],
                                    current_index=aprs2.flash_grp)
        rs = RadioSetting("aprs2.flash_grp", "Flash on group message", val)
        menu.append(rs)

        if self._has_vibrate:
            val = RadioSettingValueList(self._FLASH[:10],
                                        current_index=aprs2.vibrate_grp)
            rs = RadioSetting("aprs2.vibrate_grp",
                              "Vibrate on group message", val)
            menu.append(rs)

        filter_val = [m.padded_string for m in aprs2.msg_group]
        filter_val = self._strip_ff_pads(filter_val)
        for index, filter_text in enumerate(filter_val):
            val = RadioSettingValueString(0, 9, filter_text)
            rs = RadioSetting("aprs2.msg_group_%d" % index,
                              "Message Group %d" % (index + 1), val)
            menu.append(rs)
            rs.set_apply_callback(self.apply_ff_padded_string,
                                  aprs2.msg_group[index])
        # TODO: Use filter_val as the list entries and update it on edit.
        val = RadioSettingValueList(
            self._MSG_GROUP_NAMES,
            current_index=aprs2.selected_msg_group)
        rs = RadioSetting("aprs2.selected_msg_group", "Selected Message Group",
                          val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.filter_mic_e)
        rs = RadioSetting("aprs.filter_mic_e", "Receive Mic-E Beacons", val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.filter_position)
        rs = RadioSetting("aprs.filter_position", "Receive Position Beacons",
                          val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.filter_weather)
        rs = RadioSetting("aprs.filter_weather", "Receive Weather Beacons",
                          val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.filter_object)
        rs = RadioSetting("aprs.filter_object", "Receive Object Beacons", val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.filter_item)
        rs = RadioSetting("aprs.filter_item", "Receive Item Beacons", val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.filter_status)
        rs = RadioSetting("aprs.filter_status", "Receive Status Beacons", val)
        menu.append(rs)

        val = RadioSettingValueBoolean(aprs.filter_other)
        rs = RadioSetting("aprs.filter_other", "Receive Other Beacons", val)
        menu.append(rs)

        return menu

    def _get_aprs_tx_settings(self):
        menu = RadioSettingGroup("aprs_tx", "APRS Transmit")
        aprs = self._memobj.aprs
        aprs2 = self._memobj.aprs2

        beacon_type = (aprs.tx_smartbeacon << 1) | aprs.tx_interval_beacon
        val = RadioSettingValueList(
                self._BEACON_TYPE, current_index=beacon_type)
        rs = RadioSetting("aprs.transmit", "TX Beacons", val)
        rs.set_apply_callback(self.apply_beacon_type, aprs)
        menu.append(rs)

        val = RadioSettingValueList(
                self._TX_DELAY, current_index=aprs.tx_delay)
        rs = RadioSetting("aprs.tx_delay", "TX Delay", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._BEACON_INT, current_index=aprs.beacon_interval)
        rs = RadioSetting("aprs.beacon_interval", "Beacon Interval", val)
        menu.append(rs)

        desc = []
        status = [m.padded_string for m in self._memobj.aprs_beacon_status_txt]
        status = self._strip_ff_pads(status)
        for index, msg_text in enumerate(status):
            val = RadioSettingValueString(0, 60, msg_text)
            desc.append("Beacon Status Text %d" % (index + 1))
            rs = RadioSetting("aprs_beacon_status_txt_%d" % index, desc[-1],
                              val)
            rs.set_apply_callback(self.apply_ff_padded_string,
                                  self._memobj.aprs_beacon_status_txt[index])
            menu.append(rs)
        val = RadioSettingValueList(
            desc, current_index=aprs.selected_beacon_status_txt)
        rs = RadioSetting("aprs.selected_beacon_status_txt",
                          "Beacon Status Text", val)
        menu.append(rs)

        message_macro = [m.padded_string for m in self._memobj.aprs_msg_macro]
        message_macro = self._strip_ff_pads(message_macro)
        for index, msg_text in enumerate(message_macro):
            val = RadioSettingValueString(0, 16, msg_text)
            rs = RadioSetting("aprs_msg_macro_%d" % index,
                              "Message Macro %d" % (index + 1), val)
            rs.set_apply_callback(self.apply_ff_padded_string,
                                  self._memobj.aprs_msg_macro[index])
            menu.append(rs)

        path_str = list(self._DIGI_PATHS)

        path_str[7] = self._digi_path_to_str(aprs.digi_path_7)
        val = RadioSettingValueString(0, 88, path_str[7])
        rs = RadioSetting("aprs.digi_path_7", "Digi Path 8 (8 entries)", val)
        rs.set_apply_callback(self.apply_digi_path, aprs.digi_path_7)
        menu.append(rs)

        # Show friendly messages for empty slots rather than blanks.
        # TODO: Rebuild this when digi_path_[34567] change.
        # path_str[3] = path_str[3] or self._DIGI_PATHS[3]
        # path_str[4] = path_str[4] or self._DIGI_PATHS[4]
        # path_str[5] = path_str[5] or self._DIGI_PATHS[5]
        # path_str[6] = path_str[6] or self._DIGI_PATHS[6]
        # path_str[7] = path_str[7] or self._DIGI_PATHS[7]

        path_str[7] = self._DIGI_PATHS[7]
        val = RadioSettingValueList(path_str,
                                    current_index=aprs2.selected_digi_path)
        rs = RadioSetting("aprs2.selected_digi_path",
                          "Selected Digi Path", val)
        menu.append(rs)

        return menu

    def _get_dtmf_settings(self):
        menu = RadioSettingGroup("dtmf_settings", "DTMF")
        dtmf = self._memobj.scan_settings

        val = RadioSettingValueList(
            self._DTMF_MODE,
            current_index=dtmf.dtmf_mode)
        rs = RadioSetting("scan_settings.dtmf_mode", "DTMF Mode", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._DTMF_SPEED,
            current_index=dtmf.dtmf_speed)
        rs = RadioSetting("scan_settings.dtmf_speed",
                          "DTMF AutoDial Speed", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._DTMF_DELAY,
            current_index=dtmf.dtmf_delay)
        rs = RadioSetting("scan_settings.dtmf_delay",
                          "DTMF AutoDial Delay", val)
        menu.append(rs)

        for i in range(10):
            name = "dtmf_%02d" % i
            dtmfsetting = self._memobj.dtmf[i]
            dtmfstr = ""
            for c in dtmfsetting.memory:
                if c == 0xFF:
                    break
                if c < len(VX8_DTMF_CHARS):
                    dtmfstr += VX8_DTMF_CHARS[c]
            dtmfentry = RadioSettingValueString(0, 16, dtmfstr)
            dtmfentry.set_charset(VX8_DTMF_CHARS + list("abcd "))
            rs = RadioSetting(name, name.upper(), dtmfentry)
            rs.set_apply_callback(self.apply_dtmf, i)
            menu.append(rs)

        return menu

    def _get_misc_settings(self):
        menu = RadioSettingGroup("misc_settings", "Misc")
        scan_settings = self._memobj.scan_settings

        val = RadioSettingValueList(
            self._LCD_DIMMER,
            current_index=scan_settings.lcd_dimmer)
        rs = RadioSetting("scan_settings.lcd_dimmer", "LCD Dimmer", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._LCD_CONTRAST,
            current_index=scan_settings.lcd_contrast - 1)
        rs = RadioSetting("scan_settings.lcd_contrast", "LCD Contrast",
                          val)
        rs.set_apply_callback(self.apply_lcd_contrast, scan_settings)
        menu.append(rs)

        val = RadioSettingValueList(
            self._LAMP_KEY,
            current_index=scan_settings.lamp)
        rs = RadioSetting("scan_settings.lamp", "Lamp", val)
        menu.append(rs)

        beep_select = self._memobj.beep_select

        val = RadioSettingValueList(
            self._BEEP_SELECT,
            current_index=beep_select.beep)
        rs = RadioSetting("beep_select.beep", "Beep Select", val)
        menu.append(rs)

        opening_message = self._memobj.opening_message

        val = RadioSettingValueList(
            self._OPENING_MESSAGE,
            current_index=opening_message.flag)
        rs = RadioSetting("opening_message.flag", "Opening Msg Mode",
                          val)
        menu.append(rs)

        msg = ""
        for i in opening_message.message.padded_yaesu:
            if i == 0xFF:
                break
            msg += CHARSET[i & 0x7F]
        val = RadioSettingValueString(0, 16, msg)
        rs = RadioSetting("opening_message.message.padded_yaesu",
                          "Opening Message", val)
        rs.set_apply_callback(self.apply_ff_padded_yaesu,
                              opening_message.message)
        menu.append(rs)

        return menu

    def _get_scan_settings(self):
        menu = RadioSettingGroup("scan_settings", "Scan")
        scan_settings = self._memobj.scan_settings

        val = RadioSettingValueList(
            self._VOL_MODE,
            current_index=scan_settings.vol_mode)
        rs = RadioSetting("scan_settings.vol_mode", "Volume Mode", val)
        menu.append(rs)

        vfoa = self._memobj.vfo_info[0]
        val = RadioSettingValueList(
            self._VOLUME,
            current_index=vfoa.volume)
        rs = RadioSetting("vfo_info[0].volume", "VFO A Volume", val)
        rs.set_apply_callback(self.apply_volume, 0)
        menu.append(rs)

        vfob = self._memobj.vfo_info[1]
        val = RadioSettingValueList(
            self._VOLUME,
            current_index=vfob.volume)
        rs = RadioSetting("vfo_info[1].volume", "VFO B Volume", val)
        rs.set_apply_callback(self.apply_volume, 1)
        menu.append(rs)

        squelch = self._memobj.squelch
        val = RadioSettingValueList(
            self._SQUELCH,
            current_index=squelch.vfo_a)
        rs = RadioSetting("squelch.vfo_a", "VFO A Squelch", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._SQUELCH,
            current_index=squelch.vfo_b)
        rs = RadioSetting("squelch.vfo_b", "VFO B Squelch", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._SCAN_RESTART,
            current_index=scan_settings.scan_restart)
        rs = RadioSetting("scan_settings.scan_restart", "Scan Restart", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._SCAN_RESUME,
            current_index=scan_settings.scan_resume)
        rs = RadioSetting("scan_settings.scan_resume", "Scan Resume", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._OFF_ON,
            current_index=scan_settings.busy_led)
        rs = RadioSetting("scan_settings.busy_led", "Busy LED", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._OFF_ON,
            current_index=scan_settings.scan_lamp)
        rs = RadioSetting("scan_settings.scan_lamp", "Scan Lamp", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._TOT_TIME,
            current_index=scan_settings.tot)
        rs = RadioSetting("scan_settings.tot", "Transmit Timeout (TOT)", val)
        menu.append(rs)

        return menu

    def _get_settings(self):
        top = RadioSettings(self._get_aprs_general_settings(),
                            self._get_aprs_rx_settings(),
                            self._get_aprs_tx_settings(),
                            self._get_dtmf_settings(),
                            self._get_misc_settings(),
                            self._get_scan_settings())
        return top

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    @staticmethod
    def apply_custom_symbol(setting, obj):
        # Ensure new value falls within known bounds, otherwise leave it as
        # it's a custom value from the radio that's outside our list.
        if setting.value.get_value() in chirp_common.APRS_SYMBOLS:
            setattr(obj, "custom_symbol",
                    chirp_common.APRS_SYMBOLS.index(setting.value.get_value()))

    @classmethod
    def _apply_callsign(cls, callsign, obj, default_ssid=None):
        ssid = default_ssid
        dash_index = callsign.find("-")
        if dash_index >= 0:
            ssid = callsign[dash_index + 1:]
            callsign = callsign[:dash_index]
            try:
                ssid = int(ssid) % 16
            except ValueError:
                ssid = default_ssid
        setattr(obj, "callsign", cls._add_ff_pad(callsign, 6))
        if ssid is not None:
            setattr(obj, "ssid", ssid)

    def apply_beacon_type(cls, setting, obj):
        beacon_type = str(setting.value.get_value())
        beacon_index = cls._BEACON_TYPE.index(beacon_type)
        tx_smartbeacon = beacon_index >> 1
        tx_interval_beacon = beacon_index & 1
        if tx_interval_beacon:
            setattr(obj, "tx_interval_beacon", 1)
            setattr(obj, "tx_smartbeacon", 0)
        elif tx_smartbeacon:
            setattr(obj, "tx_interval_beacon", 0)
            setattr(obj, "tx_smartbeacon", 1)
        else:
            setattr(obj, "tx_interval_beacon", 0)
            setattr(obj, "tx_smartbeacon", 0)

    @classmethod
    def apply_callsign(cls, setting, obj, default_ssid=None):
        # Uppercase, strip SSID then FF pad to max string length.
        callsign = setting.value.get_value().upper()
        cls._apply_callsign(callsign, obj, default_ssid)

    def apply_digi_path(self, setting, obj):
        # Parse and map to aprs.digi_path_4_7[0-3] or aprs.digi_path_8
        # and FF terminate.
        path = str(setting.value.get_value())
        callsigns = [c.strip() for c in path.split(",")]
        for index in range(len(obj.entry)):
            try:
                self._apply_callsign(callsigns[index], obj.entry[index], 0)
            except IndexError:
                self._apply_callsign("", obj.entry[index], 0)
        if len(callsigns) > len(obj.entry):
            raise Exception("This path only supports %d entries" % (index + 1))

    @classmethod
    def apply_ff_padded_string(cls, setting, obj):
        # FF pad.
        val = setting.value.get_value()
        max_len = getattr(obj, "padded_string").size() // 8
        val = str(val).rstrip()
        setattr(obj, "padded_string", cls._add_ff_pad(val, max_len))

    @classmethod
    def apply_lat_long(cls, setting, obj):
        name = setting.get_name()
        is_latitude = name.endswith("latitude")
        lat_long = setting.value.get_value().strip()
        sign, l_d, l_m, l_s = cls._str_to_latlong(lat_long, is_latitude)
        LOG.debug("%s: %d %d %d %d" % (name, sign, l_d, l_m, l_s))
        setattr(obj, "%s_sign" % name, sign)
        setattr(obj, "%s_degree" % name, l_d)
        setattr(obj, "%s_minute" % name, l_m)
        setattr(obj, "%s_second" % name, l_s)

    def set_settings(self, settings):
        _mem = self._memobj
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
                        LOG.error("vx8.set_settings: %s", e)
                    continue

                # Find the object containing setting.
                obj = _mem
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

    def apply_ff_padded_yaesu(cls, setting, obj):
        # FF pad yaesus custom string format.
        rawval = setting.value.get_value()
        max_len = getattr(obj, "padded_yaesu").size() / 8
        rawval = str(rawval).rstrip()
        val = [CHARSET.index(x) for x in rawval]
        for x in range(len(val), max_len):
            val.append(0xFF)
        obj.padded_yaesu = val

    def apply_volume(cls, setting, vfo):
        val = setting.value.get_value()
        cls._memobj.vfo_info[(vfo*2)].volume = val
        cls._memobj.vfo_info[(vfo*2)+1].volume = val

    def apply_lcd_contrast(cls, setting, obj):
        rawval = setting.value.get_value()
        val = cls._LCD_CONTRAST.index(rawval) + 1
        obj.lcd_contrast = val

    def apply_dtmf(cls, setting, i):
        rawval = setting.value.get_value().upper().rstrip()
        val = [VX8_DTMF_CHARS.index(x) for x in rawval]
        for x in range(len(val), 16):
            val.append(0xFF)
        cls._memobj.dtmf[i].memory = val


@directory.register
class VX8DRadio(VX8Radio):
    """Yaesu VX-8DR"""
    MODEL = "VX-8DR"
    _model = b"AH29D"
    _mem_params = (0xC128,  # APRS message macros
                   7,       # Number of message macros
                   0xC198,  # APRS2
                   0xC24A,  # APRS beacon metadata address.
                   50,      # Number of beacons stored.
                   0xC6FA,  # APRS beacon content address.
                   146,     # Length of beacon data stored.
                   50)      # Number of beacons stored.

    _TX_DELAY = ("100ms", "150ms", "200ms", "250ms", "300ms",
                 "400ms", "500ms", "750ms", "1000ms")
    _BEACON_TYPE = ("Off", "Interval", "SmartBeaconing")
    _SMARTBEACON_PROFILE = ("Off", "Type 1", "Type 2", "Type 3")
    _POSITIONS = ("GPS", "Manual Latitude/Longitude",
                  "Manual Latitude/Longitude", "P1", "P2", "P3", "P4",
                  "P5", "P6", "P7", "P8", "P9")
    _FLASH = ("OFF", "2 seconds", "4 seconds", "6 seconds", "8 seconds",
              "10 seconds", "20 seconds", "30 seconds", "60 seconds",
              "CONTINUOUS", "every 2 seconds", "every 3 seconds",
              "every 4 seconds", "every 5 seconds", "every 6 seconds",
              "every 7 seconds", "every 8 seconds", "every 9 seconds",
              "every 10 seconds", "every 20 seconds", "every 30 seconds",
              "every 40 seconds", "every 50 seconds", "every minute",
              "every 2 minutes", "every 3 minutes", "every 4 minutes",
              "every 5 minutes", "every 6 minutes", "every 7 minutes",
              "every 8 minutes", "every 9 minutes", "every 10 minutes")
    _LCD_CONTRAST = ["Level %d" % x for x in range(1, 16)]
    _MY_SYMBOL = ("/[ Person", "/b Bike", "/> Car", "User selected")

    def _get_aprs_tx_settings(self):
        menu = RadioSettingGroup("aprs_tx", "APRS Transmit")
        aprs = self._memobj.aprs
        aprs2 = self._memobj.aprs2

        beacon_type = (aprs.tx_smartbeacon << 1) | aprs.tx_interval_beacon
        val = RadioSettingValueList(
                self._BEACON_TYPE, current_index=beacon_type)
        rs = RadioSetting("aprs.transmit", "TX Beacons", val)
        rs.set_apply_callback(self.apply_beacon_type, aprs)
        menu.append(rs)

        val = RadioSettingValueList(
                self._TX_DELAY, current_index=aprs.tx_delay)
        rs = RadioSetting("aprs.tx_delay", "TX Delay", val)
        menu.append(rs)

        val = RadioSettingValueList(
                self._BEACON_INT, current_index=aprs.beacon_interval)
        rs = RadioSetting("aprs.beacon_interval", "Beacon Interval", val)
        menu.append(rs)

        desc = []
        status = [m.padded_string for m in self._memobj.aprs_beacon_status_txt]
        status = self._strip_ff_pads(status)
        for index, msg_text in enumerate(status):
            val = RadioSettingValueString(0, 60, msg_text)
            desc.append("Beacon Status Text %d" % (index + 1))
            rs = RadioSetting("aprs_beacon_status_txt_%d" % index, desc[-1],
                              val)
            rs.set_apply_callback(self.apply_ff_padded_string,
                                  self._memobj.aprs_beacon_status_txt[index])
            menu.append(rs)
        val = RadioSettingValueList(
            desc, current_index=aprs.selected_beacon_status_txt)
        rs = RadioSetting("aprs.selected_beacon_status_txt",
                          "Beacon Status Text", val)
        menu.append(rs)

        message_macro = [m.padded_string for m in self._memobj.aprs_msg_macro]
        message_macro = self._strip_ff_pads(message_macro)
        for index, msg_text in enumerate(message_macro):
            val = RadioSettingValueString(0, 16, msg_text)
            rs = RadioSetting("aprs_msg_macro_%d" % index,
                              "Message Macro %d" % (index + 1), val)
            rs.set_apply_callback(self.apply_ff_padded_string,
                                  self._memobj.aprs_msg_macro[index])
            menu.append(rs)

        path_str = list(self._DIGI_PATHS)
        path_str[3] = self._digi_path_to_str(aprs2.digi_path_3_6[0])
        val = RadioSettingValueString(0, 22, path_str[3])
        rs = RadioSetting("aprs2.digi_path_3", "Digi Path 4 (2 entries)", val)
        rs.set_apply_callback(self.apply_digi_path, aprs2.digi_path_3_6[0])
        menu.append(rs)

        path_str[4] = self._digi_path_to_str(aprs2.digi_path_3_6[1])
        val = RadioSettingValueString(0, 22, path_str[4])
        rs = RadioSetting("aprs2.digi_path_4", "Digi Path 5 (2 entries)", val)
        rs.set_apply_callback(self.apply_digi_path, aprs2.digi_path_3_6[1])
        menu.append(rs)

        path_str[5] = self._digi_path_to_str(aprs2.digi_path_3_6[2])
        val = RadioSettingValueString(0, 22, path_str[5])
        rs = RadioSetting("aprs2.digi_path_5", "Digi Path 6 (2 entries)", val)
        rs.set_apply_callback(self.apply_digi_path, aprs2.digi_path_3_6[2])
        menu.append(rs)

        path_str[6] = self._digi_path_to_str(aprs2.digi_path_3_6[3])
        val = RadioSettingValueString(0, 22, path_str[6])
        rs = RadioSetting("aprs2.digi_path_6", "Digi Path 7 (2 entries)", val)
        rs.set_apply_callback(self.apply_digi_path, aprs2.digi_path_3_6[3])
        menu.append(rs)

        path_str[7] = self._digi_path_to_str(aprs.digi_path_7)
        val = RadioSettingValueString(0, 88, path_str[7])
        rs = RadioSetting("aprs.digi_path_7", "Digi Path 8 (8 entries)", val)
        rs.set_apply_callback(self.apply_digi_path, aprs.digi_path_7)
        menu.append(rs)

        # Show friendly messages for empty slots rather than blanks.
        # TODO: Rebuild this when digi_path_[34567] change.
        # path_str[3] = path_str[3] or self._DIGI_PATHS[3]
        # path_str[4] = path_str[4] or self._DIGI_PATHS[4]
        # path_str[5] = path_str[5] or self._DIGI_PATHS[5]
        # path_str[6] = path_str[6] or self._DIGI_PATHS[6]
        # path_str[7] = path_str[7] or self._DIGI_PATHS[7]
        path_str[3] = self._DIGI_PATHS[3]
        path_str[4] = self._DIGI_PATHS[4]
        path_str[5] = self._DIGI_PATHS[5]
        path_str[6] = self._DIGI_PATHS[6]
        path_str[7] = self._DIGI_PATHS[7]
        val = RadioSettingValueList(path_str,
                                    current_index=aprs2.selected_digi_path)
        rs = RadioSetting("aprs2.selected_digi_path",
                          "Selected Digi Path", val)
        menu.append(rs)

        return menu

    def _get_aprs_smartbeacon(self):
        menu = RadioSettingGroup("aprs_smartbeacon", "APRS SmartBeacon")
        aprs2 = self._memobj.aprs2

        val = RadioSettingValueList(
           self._SMARTBEACON_PROFILE,
           current_index=aprs2.active_smartbeaconing)
        rs = RadioSetting("aprs2.active_smartbeaconing",
                          "SmartBeacon profile", val)
        menu.append(rs)

        for profile in range(3):
            pfx = "type%d" % (profile + 1)
            path = "aprs2.smartbeaconing_profile[%d]" % profile
            prof = aprs2.smartbeaconing_profile[profile]

            low_val = RadioSettingValueInteger(2, 30, prof.low_speed_mph)
            high_val = RadioSettingValueInteger(3, 70, prof.high_speed_mph)
            low_val.get_max = lambda: min(30, int(high_val.get_value()) - 1)

            rs = RadioSetting("%s.low_speed_mph" % path,
                              "%s Low Speed (mph)" % pfx, low_val)
            menu.append(rs)

            rs = RadioSetting("%s.high_speed_mph" % path,
                              "%s High Speed (mph)" % pfx, high_val)
            menu.append(rs)

            val = RadioSettingValueInteger(1, 100, prof.slow_rate_min)
            rs = RadioSetting("%s.slow_rate_min" % path,
                              "%s Slow rate (minutes)" % pfx, val)
            menu.append(rs)

            val = RadioSettingValueInteger(10, 180, prof.fast_rate_sec)
            rs = RadioSetting("%s.fast_rate_sec" % path,
                              "%s Fast rate (seconds)" % pfx, val)
            menu.append(rs)

            val = RadioSettingValueInteger(5, 90, prof.turn_angle)
            rs = RadioSetting("%s.turn_angle" % path,
                              "%s Turn angle (degrees)" % pfx, val)
            menu.append(rs)

            val = RadioSettingValueInteger(1, 255, prof.turn_slop)
            rs = RadioSetting("%s.turn_slop" % path,
                              "%s Turn slop" % pfx, val)
            menu.append(rs)

            val = RadioSettingValueInteger(5, 180, prof.turn_time_sec)
            rs = RadioSetting("%s.turn_time_sec" % path,
                              "%s Turn time (seconds)" % pfx, val)
            menu.append(rs)

        return menu

    def _get_settings(self):
        top = RadioSettings(self._get_aprs_general_settings(),
                            self._get_aprs_rx_settings(),
                            self._get_aprs_tx_settings(),
                            self._get_aprs_smartbeacon(),
                            self._get_dtmf_settings(),
                            self._get_misc_settings(),
                            self._get_scan_settings())
        return top


@directory.register
class VX8GERadio(VX8DRadio):
    """Yaesu VX-8GE"""
    MODEL = "VX-8GE"
    _model = b"AH041"
    _has_vibrate = True
    _has_af_dual = False
