# Copyright 2026 Michael Kent
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

"""Icom IC-2800H driver.

Memory map decoded from CS-2800 .icf images (model 20 47 00 01, 4000 bytes).

Each band has 99 memories of 17 bytes:

  byte 0-1  BCD frequency, 100 kHz resolution (16 40 -> 164.0 MHz)
  byte 2    hi nibble: 10 kHz digit, lo nibble: kHz digit in 500 Hz units
  byte 3    is_12_5:1  skip:2  empty:1  narrow:1  am:1  duplex:2
  byte 4    tmode:2  unknown:3  tuning_step:3
  byte 5-6  rtone (TONE):6  ctone (TSQL):6  unknown:4   (50-tone CTCSS list)
  byte 7    BCD offset, 100 kHz resolution
  byte 8    unknown
  byte 9-16 name, 8 ASCII chars, space padded

VHF memories start at 0x0000, UHF at 0x0740.
"""

import logging

from chirp import bitwise, chirp_common, directory, errors
from chirp.drivers import icf
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

MEM_BODY = """
  bbcd freq[2];
  u8   freq_10khz:4,
       freq_500hz:4;
  u8   is_12_5:1,
       pskip:1,
       mskip:1,
       empty:1,
       narrow:1,
       am:1,
       duplex:2;
  u8   tmode:2,
       unknown1:3,
       tuning_step:3;
  u16  rtone:6,
       ctone:6,
       unknown2:4;
  bbcd offset;
  u8   unknown3;
"""

MEM_FORMAT = """
struct mem {""" + MEM_BODY + """  char name[8];
};

struct edge {""" + MEM_BODY + """};

#seekto 0x0000;
struct mem vhf[99];
struct edge vhf_edges[6];
struct mem vhf_call;

#seekto 0x0740;
struct mem uhf[99];
struct edge uhf_edges[6];
struct mem uhf_call;

#seekto 0x0E80;
struct {
  u8 length;
  u8 digits[8];
} dtmf[14];

#seekto 0x0EFF;
u8 dtmf_speed;

#seekto 0x0F3C;
u8 vhf_scan_resume;
u8 unknown_f3d[2];
u8 unknown_f3f_hi:1,
   vhf_power:2,
   unknown_f3f_lo:5;

#seekto 0x0F4C;
u8 uhf_scan_resume;
u8 unknown_f4d[2];
u8 unknown_f4f_hi:1,
   uhf_power:2,
   unknown_f4f_lo:5;

#seekto 0x0F50;
struct {
  u8 beep;
  u8 tot;
  u8 auto_repeater;
  u8 apo;
  u8 fan;
  u8 packet;
  u8 sql_delay;
  u8 mic_address;
  u8 sub_mute;
  u8 sub_beep;
  u8 rf_att;
  u8 mem_name;
  u8 key_f1;
  u8 key_f2;
  u8 key_up;
  u8 key_dn;
  u8 display_type;
  u8 brightness;
  u8 contrast;
  u8 unknown_f63[3];
  u8 dtmf_bank;
  u8 dtmf_channel;
} settings;

#seekto 0x0F70;
char comment[16];
char opening_title[8];
"""

DUPLEX = ["", "", "+", "-"]
TMODES = ["", "Tone", "", "TSQL"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0]
NAME_LEN = 8
CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + "-/+*()=.,"

SPECIALS = ["P1A", "P1B", "P2A", "P2B", "P3A", "P3B", "C"]

TOT_LIST = ["Off", "3 min", "5 min", "15 min", "30 min"]
APO_LIST = ["Off", "30 min", "1 hour", "2 hours"]
FAN_LIST = ["Automatic", "On"]
PACKET_LIST = ["1200", "9600"]
SQL_DELAY_LIST = ["Short", "Long"]
SCAN_RESUME_LIST = ["5s", "10s", "15s", "Pause"]
POWER_LIST = ["Low", "Mid-Lo", "Mid-Hi", "High"]
DISPLAY_LIST = ["Type A", "Type B", "Type C", "Type D"]
MIC_ADDR_LIST = [str(i) for i in range(1, 8)]
KEY_LIST = ["VHF MAIN", "VHF V/MHz", "VHF M/C", "VHF MONI",
            "UHF MAIN", "UHF V/MHz", "UHF M/C", "UHF MONI",
            "VHF EDIT", "VHF TONE", "VHF MW", "DTMF",
            "UHF EDIT", "UHF TONE", "UHF MW", "DISP", "Dn", "Up"]
DTMF_CHARS = "0123456789ABCD*#"
DTMF_NAMES = ["D%X" % i for i in range(14)]
# Channel selection is two bytes: D0 = 01 00, D1..DD = 02 (n - 1)
# (confirmed for D0, D5 and DA)
DTMF_SPEED_LIST = ["100ms", "200ms", "300ms", "500ms"]
TITLE_CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + "-/+*()=., "

BANDS = {
    "VHF": ("vhf", [(118000000, 174000000)]),
    "UHF": ("uhf", [(400000000, 470000000)]),
}


def _get_freq(_mem):
    return (int(_mem.freq) * 100000 +
            int(_mem.freq_10khz) * 10000 +
            int(_mem.freq_500hz) * 500)


def _set_freq(_mem, freq, step_khz):
    _mem.freq = freq // 100000
    _mem.freq_10khz = (freq // 10000) % 10
    _mem.freq_500hz = (freq % 10000) // 500
    # Rule inferred from every channel in the sample image: the radio
    # flags channels on the 12.5 kHz raster that need it.
    _mem.is_12_5 = int(freq % 5000 != 0 or
                       (step_khz == 12.5 and freq % 12500 == 0))


class IC2800Band(icf.IcomCloneModeRadio):
    """Shared memory logic for one band of the IC-2800H"""
    VENDOR = "Icom"
    MODEL = "IC-2800H"
    _model = "\x20\x47\x00\x01"
    _memsize = 0x0FA0
    _endframe = "Icom Inc\x2e"   # matches the radio's own end frame
    _ranges = [(0x0000, 0x0FA0, 32)]
    _band = "VHF"

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def _mems(self):
        return getattr(self._memobj, BANDS[self._band][0])

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 99)
        rf.has_bank = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_ctone = True
        rf.has_rx_dtcs = False
        rf.has_cross = False
        rf.has_tuning_step = True
        rf.has_name = True
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_duplexes = ["", "+", "-"]
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = BANDS[self._band][1]
        rf.valid_skips = ["", "S"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = NAME_LEN
        rf.can_odd_split = False
        rf.has_settings = True
        rf.valid_special_chans = list(SPECIALS)
        return rf

    def _locate(self, number):
        """Return (struct, number, extd_number, has_name)"""
        prefix = BANDS[self._band][0]
        if isinstance(number, str):
            extd = number
            number = 100 + SPECIALS.index(number)
        elif number > 99:
            extd = SPECIALS[number - 100]
        else:
            return self._mems()[number - 1], number, "", True
        if extd == "C":
            return getattr(self._memobj, prefix + "_call"), number, extd, True
        edges = getattr(self._memobj, prefix + "_edges")
        return edges[SPECIALS.index(extd)], number, extd, False

    def get_raw_memory(self, number):
        return repr(self._locate(number)[0])

    def get_memory(self, number):
        _mem, number, extd, has_name = self._locate(number)
        mem = chirp_common.Memory()
        mem.number = number
        if extd:
            mem.extd_number = extd
            mem.immutable = ["number", "extd_number", "skip"]
            if not has_name:
                mem.immutable.append("name")

        if _mem.empty and extd != "C":
            mem.empty = True
            return mem

        mem.freq = _get_freq(_mem)
        if has_name:
            mem.name = str(_mem.name).rstrip()
        mem.duplex = DUPLEX[_mem.duplex]
        mem.offset = int(_mem.offset) * 100000
        if _mem.am:
            mem.mode = "AM"
        elif _mem.narrow:
            mem.mode = "NFM"
        else:
            mem.mode = "FM"
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.tuning_step = STEPS[_mem.tuning_step]
        if extd:
            return mem
        mem.skip = "S" if _mem.mskip else ""

        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("pskip", "Program scan skip",
                          RadioSettingValueBoolean(bool(_mem.pskip)))
        mem.extra.append(rs)
        return mem

    def set_memory(self, mem):
        _mem, number, extd, has_name = self._locate(mem.extd_number or
                                                    mem.number)

        if mem.empty:
            if extd == "C":
                raise errors.RadioError("The call channel cannot be empty")
            _mem.empty = 1
            if has_name:
                _mem.name = " " * NAME_LEN
            return

        _mem.empty = 0
        step = mem.tuning_step if mem.tuning_step in STEPS else 5.0
        _mem.tuning_step = STEPS.index(step)
        _set_freq(_mem, mem.freq, step)
        if has_name:
            _mem.name = mem.name.ljust(NAME_LEN)[:NAME_LEN]
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.offset = mem.offset // 100000
        _mem.am = int(mem.mode == "AM")
        _mem.narrow = int(mem.mode == "NFM")
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        if extd:
            return
        _mem.mskip = int(mem.skip == "S")
        _mem.pskip = 0
        for setting in mem.extra:
            if setting.get_name() == "pskip":
                _mem.pskip = int(bool(setting.value))
        if _mem.pskip:
            # The radio only uses 00, 01 and 11: program skip implies memory
            _mem.mskip = 1

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if not mem.empty:
            if mem.freq % 2500:
                msgs.append(chirp_common.ValidationError(
                    "Frequency must be on a 2.5 kHz boundary "
                    "(no 6.25 kHz step on this radio)"))
            if mem.offset % 100000:
                msgs.append(chirp_common.ValidationError(
                    "Offset must be a multiple of 100 kHz"))
            if mem.mode == "AM" and not 118000000 <= mem.freq < 137000000:
                msgs.append(chirp_common.ValidationWarning(
                    "The radio only allows AM in the airband"))
        return msgs

    def get_settings(self):
        _set = self._memobj.settings
        m = self._memobj

        def lst(name, label, options, obj, attr):
            val = int(getattr(obj, attr))
            if val >= len(options):
                LOG.warning("%s: unexpected value %i", name, val)
                return None
            rs = RadioSetting(name, label,
                              RadioSettingValueList(options,
                                                    current_index=val))
            rs.set_apply_callback(
                lambda s, o=obj, a=attr: setattr(o, a, int(s.value)))
            return rs

        def flag(name, label, attr):
            rs = RadioSetting(name, label,
                              RadioSettingValueBoolean(bool(getattr(_set,
                                                                    attr))))
            rs.set_apply_callback(
                lambda s, a=attr: setattr(_set, a, int(bool(s.value))))
            return rs

        def add(group, rs):
            if rs is not None:
                group.append(rs)

        common = RadioSettingGroup("common", "Common")
        add(common, flag("beep", "Operation beep", "beep"))
        add(common, flag("sub_mute", "Sub band mute", "sub_mute"))
        add(common, flag("sub_beep", "Sub band beep", "sub_beep"))
        add(common, flag("rf_att", "RF attenuator", "rf_att"))
        add(common, flag("mem_name", "Memory name display", "mem_name"))
        add(common, lst("tot", "Tx time-out timer", TOT_LIST, _set, "tot"))
        add(common, lst("apo", "Auto power-off", APO_LIST, _set, "apo"))
        add(common, lst("fan", "Cooling fan", FAN_LIST, _set, "fan"))
        add(common, lst("packet", "Packet BPS", PACKET_LIST, _set,
                        "packet"))
        add(common, lst("sql_delay", "Squelch delay", SQL_DELAY_LIST, _set,
                        "sql_delay"))

        bands = RadioSettingGroup("bands", "Bands")
        add(bands, lst("vhf_scan_resume", "VHF scan resume",
                       SCAN_RESUME_LIST, m, "vhf_scan_resume"))
        add(bands, lst("vhf_power", "VHF RF power", POWER_LIST, m,
                       "vhf_power"))
        add(bands, lst("uhf_scan_resume", "UHF scan resume",
                       SCAN_RESUME_LIST, m, "uhf_scan_resume"))
        add(bands, lst("uhf_power", "UHF RF power", POWER_LIST, m,
                       "uhf_power"))

        display = RadioSettingGroup("display", "Display")
        for attr, label in (("contrast", "Contrast"),
                            ("brightness", "Brightness")):
            rs = RadioSetting(attr, label + " (0-32)",
                              RadioSettingValueInteger(
                                  0, 32, min(int(getattr(_set, attr)), 32)))
            rs.set_apply_callback(
                lambda s, a=attr: setattr(_set, a, int(s.value)))
            display.append(rs)
        add(display, lst("display_type", "Display type", DISPLAY_LIST, _set,
                         "display_type"))
        title = str(m.opening_title).rstrip()
        rs = RadioSetting("opening_title", "Opening title",
                          RadioSettingValueString(0, 8, title, False,
                                                  TITLE_CHARSET))
        rs.set_apply_callback(
            lambda s: setattr(m, "opening_title", str(s.value).ljust(8)))
        display.append(rs)
        comment = str(m.comment).rstrip()
        rs = RadioSetting("comment", "Comment",
                          RadioSettingValueString(0, 16, comment, False))
        rs.set_apply_callback(
            lambda s: setattr(m, "comment", str(s.value).ljust(16)))
        display.append(rs)

        mic = RadioSettingGroup("mic", "Microphone")
        for attr, label in (("key_f1", "HM-98 F-1 key"),
                            ("key_f2", "HM-98 F-2 key"),
                            ("key_up", "UP key"), ("key_dn", "DN key")):
            add(mic, lst(attr, label, KEY_LIST, _set, attr))
        addr = int(_set.mic_address)
        if 1 <= addr <= 7:
            rs = RadioSetting("mic_address", "HM-90 mic address",
                              RadioSettingValueList(
                                  MIC_ADDR_LIST, current_index=addr - 1))
            rs.set_apply_callback(
                lambda s: setattr(_set, "mic_address",
                                  int(s.value) + 1))
            mic.append(rs)

        dtmf = RadioSettingGroup("dtmf", "DTMF autodial")
        add(dtmf, lst("dtmf_speed", "DTMF speed", DTMF_SPEED_LIST, m,
                      "dtmf_speed"))
        bank, chan = int(_set.dtmf_bank), int(_set.dtmf_channel)
        if bank == 1:
            current = 0
        elif bank == 2 and chan < 13:
            current = chan + 1
        else:
            current = None
            LOG.warning("Unexpected DTMF channel bytes %02x %02x",
                        bank, chan)
        if current is not None:
            rs = RadioSetting("dtmf_channel", "DTMF channel selection",
                              RadioSettingValueList(DTMF_NAMES,
                                                    current_index=current))

            def _apply_dtmf_channel(setting):
                index = int(setting.value)
                if index == 0:
                    _set.dtmf_bank, _set.dtmf_channel = 1, 0
                else:
                    _set.dtmf_bank, _set.dtmf_channel = 2, index - 1
            rs.set_apply_callback(_apply_dtmf_channel)
            dtmf.append(rs)
        for i, label in enumerate(DTMF_NAMES):
            rs = RadioSetting("dtmf_%i" % i, label,
                              RadioSettingValueString(
                                  0, 16, self._get_dtmf(i), False,
                                  DTMF_CHARS))
            rs.set_apply_callback(
                lambda s, i=i: self._set_dtmf(i, str(s.value).strip()))
            dtmf.append(rs)

        return RadioSettings(common, bands, display, mic, dtmf)

    def _get_dtmf(self, index):
        entry = self._memobj.dtmf[index]
        length = min(int(entry.length), 16)
        nibbles = []
        for b in entry.digits:
            nibbles += [int(b) >> 4, int(b) & 0x0F]
        return "".join(DTMF_CHARS[n] for n in nibbles[:length])

    def _set_dtmf(self, index, value):
        entry = self._memobj.dtmf[index]
        entry.length = len(value)
        # Only touch the bytes the digits occupy; CS-2800 leaves its own
        # padding in the rest (a full 16-digit entry uses all 8 bytes)
        for pos, char in enumerate(value):
            byte = entry.digits[pos // 2]
            nib = DTMF_CHARS.index(char)
            if pos % 2:
                byte.set_value((int(byte) & 0xF0) | nib)
            else:
                byte.set_value((int(byte) & 0x0F) | (nib << 4))

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
            elif element.has_apply_callback() and element.changed():
                element.run_apply_callback()


@directory.register
class IC2800Radio(IC2800Band):
    """Icom IC-2800H"""

    def get_features(self):
        rf = super().get_features()
        rf.has_sub_devices = self.VARIANT == ""
        return rf

    def get_sub_devices(self):
        return [IC2800VHF(self._mmap), IC2800UHF(self._mmap)]


class IC2800VHF(IC2800Radio):
    VARIANT = "VHF"
    _band = "VHF"


class IC2800UHF(IC2800Radio):
    VARIANT = "UHF"
    _band = "UHF"
