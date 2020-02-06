# Copyright 2017 Windsor Schmidt <windsor.schmidt@gmail.com>
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

from chirp import chirp_common, directory, bitwise
from chirp.drivers import icf
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList, RadioSettingValueBoolean, RadioSettings

# The Icom IC-2300H is a 65W, 144MHz mobile transceiver based on the IC-2200H.
# Unlike the IC-2200H, this model does not accept Icom's UT-118 D-STAR board.
#
# A simple USB interface based on a typical FT232RL breakout board was used
# during development of this module. A schematic diagram is as follows:
#
#
# 3.5mm plug from IC-2300H
# sleeve / ring / tip
# --.______________
#   |      |   |   \
#   |______|___|___/    FT232RL breakout
# --'    |   |        .------------------.
#        |   +--------| RXD              |
#        |   |   D1   |                  |
#        |   +--|>|---| TXD              | USB/PC
#        |   |   R1   |                  |-------->
#        |   +--[_]---| VCC (5V)         |
#        |            |                  |
#        +------------| GND              |
#                     `------------------'
#
# D1: 1N4148 shottky diode
# R1: 10K ohm resistor

MEM_FORMAT = """
#seekto 0x0000; // channel memories
struct {
  ul16 frequency;
  ul16 offset;
  char name[6];
  u8   repeater_tone;
  u8   ctcss_tone;
  u8   dtcs_code;
  u8   tuning_step:4,
       tone_mode:4;
  u8   unknown1:3,
       mode_narrow:1,
       power:2,
       unknown2:2;
  u8   dtcs_polarity:2,
       duplex:2,
       unknown3:1,
       reverse_duplex:1,
       unknown4:1,
       display_style:1;
} memory[200];
#seekto 0x1340; // channel memory flags
struct {
  u8   unknown5:2,
       empty:1,
       skip:1,
       bank:4;
} flags[200];
#seekto 0x1660; // power-on and regular set menu items
struct {
  u8   key_beep;
  u8   tx_timeout;
  u8   auto_repeater;
  u8   auto_power_off;
  u8   repeater_lockout;
  u8   squelch_delay;
  u8   squelch_type;
  u8   dtmf_speed;
  u8   display_type;
  u8   unknown6;
  u8   tone_burst;
  u8   voltage_display;
  u8   unknown7;
  u8   display_brightness;
  u8   display_color;
  u8   auto_dimmer;
  u8   display_contrast;
  u8   scan_pause_timer;
  u8   mic_gain;
  u8   scan_resume_timer;
  u8   weather_alert;
  u8   bank_link_enable;
  u8   bank_link[10];
} settings;
"""

TUNING_STEPS = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0]
TONE_MODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+"]
DTCSP = ["NN", "NR", "RN", "RR"]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=65),
                chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("MidLow", watts=10),
                chirp_common.PowerLevel("Mid", watts=25)]


def _wipe_memory(mem, char):
    mem.set_raw(char * (mem.size() // 8))


@directory.register
class IC2300Radio(icf.IcomCloneModeRadio):
    """Icom IC-2300"""
    VENDOR = "Icom"
    MODEL = "IC-2300H"

    _model = "\x32\x51\x00\x01"
    _memsize = 6304
    _endframe = "Icom Inc.C5\xfd"
    _can_hispeed = True
    _ranges = [(0x0000, 0x18a0, 32)]  # upload entire memory for now

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 199)
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = list(TONE_MODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(TUNING_STEPS)
        rf.valid_bands = [(136000000, 174000000)]  # USA tx range: 144-148MHz
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.has_settings = True
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def _get_bank(self, loc):
        _flag = self._memobj.flags[loc]
        if _flag.bank == 0x0a:
            return None
        else:
            return _flag.bank

    def _set_bank(self, loc, bank):
        _flag = self._memobj.flags[loc]
        if bank is None:
            _flag.bank = 0x0a
        else:
            _flag.bank = bank

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]
        mem = chirp_common.Memory()
        mem.number = number
        if _flag.empty:
            mem.empty = True
            return mem
        mult = int(TUNING_STEPS[_mem.tuning_step] * 1000)
        mem.freq = (_mem.frequency * mult)
        mem.offset = (_mem.offset * mult)
        mem.name = str(_mem.name).rstrip()
        mem.rtone = chirp_common.TONES[_mem.repeater_tone]
        mem.ctone = chirp_common.TONES[_mem.ctcss_tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs_code]
        mem.tuning_step = TUNING_STEPS[_mem.tuning_step]
        mem.tmode = TONE_MODES[_mem.tone_mode]
        mem.mode = "NFM" if _mem.mode_narrow else "FM"
        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_polarity]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.skip = "S" if _flag.skip else ""
        mem.power = POWER_LEVELS[_mem.power]

        # Reverse duplex
        mem.extra = RadioSettingGroup("extra", "Extra")
        rev = RadioSetting("reverse_duplex", "Reverse duplex",
                           RadioSettingValueBoolean(bool(_mem.reverse_duplex)))
        rev.set_doc("Reverse duplex")
        mem.extra.append(rev)

        # Memory display style
        opt = ["Frequency", "Label"]
        dsp = RadioSetting("display_style", "Display style",
                           RadioSettingValueList(opt, opt[_mem.display_style]))
        dsp.set_doc("Memory display style")
        mem.extra.append(dsp)

        return mem

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def set_memory(self, mem):
        number = mem.number
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]
        was_empty = int(_flag.empty)
        _flag.empty = mem.empty
        if mem.empty:
            _wipe_memory(_mem, "\xff")
            return
        if was_empty:
            _wipe_memory(_mem, "\x00")
        mult = mem.tuning_step * 1000
        _mem.frequency = (mem.freq / mult)
        _mem.offset = mem.offset / mult
        _mem.name = mem.name.ljust(6)
        _mem.repeater_tone = chirp_common.TONES.index(mem.rtone)
        _mem.ctcss_tone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs_code = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
        _mem.tone_mode = TONE_MODES.index(mem.tmode)
        _mem.mode_narrow = mem.mode.startswith("N")
        _mem.dtcs_polarity = DTCSP.index(mem.dtcs_polarity)
        _mem.duplex = DUPLEX.index(mem.duplex)
        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = POWER_LEVELS[0]
        _flag.skip = mem.skip != ""

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        front_panel = RadioSettingGroup("front_panel", "Front Panel Settings")
        top = RadioSettings(basic, front_panel)

        # Transmit timeout
        opt = ['Disabled', '1 minute'] + \
              [s + ' minutes' for s in map(str, range(2, 31))]
        rs = RadioSetting("tx_timeout", "Transmit timeout (min)",
                          RadioSettingValueList(opt, opt[
                              _settings.tx_timeout
                          ]))
        basic.append(rs)

        # Auto Repeater (USA model only)
        opt = ["Disabled", "Duplex Only", "Duplex and tone"]
        rs = RadioSetting("auto_repeater", "Auto repeater",
                          RadioSettingValueList(opt, opt[
                              _settings.auto_repeater
                          ]))
        basic.append(rs)

        # Auto Power Off
        opt = ["Disabled", "30 minutes", "60 minutes", "120 minutes"]
        rs = RadioSetting("auto_power_off", "Auto power off",
                          RadioSettingValueList(opt, opt[
                              _settings.auto_power_off
                          ]))
        basic.append(rs)

        # Squelch Delay
        opt = ["Short", "Long"]
        rs = RadioSetting("squelch_delay", "Squelch delay",
                          RadioSettingValueList(opt, opt[
                              _settings.squelch_delay
                          ]))
        basic.append(rs)

        # Squelch Type
        opt = ["Noise squelch", "S-meter squelch", "Squelch attenuator"]
        rs = RadioSetting("squelch_type", "Squelch type",
                          RadioSettingValueList(opt, opt[
                              _settings.squelch_type
                          ]))
        basic.append(rs)

        # Repeater Lockout
        opt = ["Disabled", "Repeater lockout", "Busy lockout"]
        rs = RadioSetting("repeater_lockout", "Repeater lockout",
                          RadioSettingValueList(opt, opt[
                              _settings.repeater_lockout
                          ]))
        basic.append(rs)

        # DTMF Speed
        opt = ["100ms interval, 5.0 cps",
               "200ms interval, 2.5 cps",
               "300ms interval, 1.6 cps",
               "500ms interval, 1.0 cps"]
        rs = RadioSetting("dtmf_speed", "DTMF speed",
                          RadioSettingValueList(opt, opt[
                              _settings.dtmf_speed
                          ]))
        basic.append(rs)

        # Scan pause timer
        opt = [s + ' seconds' for s in map(str, range(2, 22, 2))] + ['Hold']
        rs = RadioSetting("scan_pause_timer", "Scan pause timer",
                          RadioSettingValueList(
                              opt, opt[_settings.scan_pause_timer]))
        basic.append(rs)

        # Scan Resume Timer
        opt = ['Immediate'] + \
              [s + ' seconds' for s in map(str, range(1, 6))] + ['Hold']
        rs = RadioSetting("scan_resume_timer", "Scan resume timer",
                          RadioSettingValueList(
                              opt, opt[_settings.scan_resume_timer]))
        basic.append(rs)

        # Weather Alert (USA model only)
        rs = RadioSetting("weather_alert", "Weather alert",
                          RadioSettingValueBoolean(_settings.weather_alert))
        basic.append(rs)

        # Tone Burst
        rs = RadioSetting("tone_burst", "Tone burst",
                          RadioSettingValueBoolean(_settings.tone_burst))
        basic.append(rs)

        # Memory Display Type
        opt = ["Frequency", "Channel", "Name"]
        rs = RadioSetting("display_type", "Memory display",
                          RadioSettingValueList(opt,
                                                opt[_settings.display_type]))
        front_panel.append(rs)

        # Display backlight brightness;
        opt = ["1 (dimmest)", "2", "3", "4 (brightest)"]
        rs = RadioSetting("display_brightness", "Backlight brightness",
                          RadioSettingValueList(
                              opt,
                              opt[_settings.display_brightness]))
        front_panel.append(rs)

        # Display backlight color
        opt = ["Amber", "Yellow", "Green"]
        rs = RadioSetting("display_color", "Backlight color",
                          RadioSettingValueList(opt,
                                                opt[_settings.display_color]))
        front_panel.append(rs)

        # Display contrast
        opt = ["1 (lightest)", "2", "3", "4 (darkest)"]
        rs = RadioSetting("display_contrast", "Display contrast",
                          RadioSettingValueList(
                              opt,
                              opt[_settings.display_contrast]))
        front_panel.append(rs)

        # Auto dimmer
        opt = ["Disabled", "Backlight off", "1 (dimmest)", "2", "3"]
        rs = RadioSetting("auto_dimmer", "Auto dimmer",
                          RadioSettingValueList(opt,
                                                opt[_settings.auto_dimmer]))
        front_panel.append(rs)

        # Microphone gain
        opt = ["Low", "High"]
        rs = RadioSetting("mic_gain", "Microphone gain",
                          RadioSettingValueList(opt,
                                                opt[_settings.mic_gain]))
        front_panel.append(rs)

        # Key press beep
        rs = RadioSetting("key_beep", "Key press beep",
                          RadioSettingValueBoolean(_settings.key_beep))
        front_panel.append(rs)

        # Voltage Display;
        rs = RadioSetting("voltage_display", "Voltage display",
                          RadioSettingValueBoolean(_settings.voltage_display))
        front_panel.append(rs)

        # TODO: Add Bank Links settings to GUI

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            setting = element.get_name()
            setattr(_settings, setting, element.value)
