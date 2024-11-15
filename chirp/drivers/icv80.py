# Copyright 2008 Dan Smith <dsmith at danplanet.com>
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

import logging

from chirp.drivers import icf
from chirp import chirp_common, bitwise, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList, RadioSettingValueBoolean, \
    RadioSettings

LOG = logging.getLogger(__name__)


ICV80_MEM_FORMAT = """
struct {
  ul16 freq;
  ul16 offset;
  char name[5];
  u8 unknown0:2,
     rtone:6;
  u8 unknown1:2,
     ctone:6;
  u8 unknown2:1,
     dtcs:7;
  u8 unknown3:5,
     tuning_step:3;
  u8 unknown4:2,
     mode:1,
     reverse_duplex:1,
     duplex:2,
     mult:2;
  u8 unknown6:2,
     dtcs_polarity:2,
     unknown8:2,
     tmode:2;
  u8 unknown9:5,
     tx_inhibit:1,
     power:2;
} memory[207];

u8 skip[32];

u8 unused[32];

#seekto 0x0e50;
struct {
  u8 unknown1:6,
     beep:2;
  u8 unknown2:3,
     tot:5;
  u8 unknown3;
  u8 unknown4:6,
     auto_pwr_off:2;
  u8 unknown5:6,
     lockout:2;
  u8 unknown6:7,
     squelch_delay:1;
  u8 unknown7_0;
  u8 unknown7_1:6,
     mem_display1:2;
  u8 unknown8:6,
     mem_display2:2; // CS stores the display value here as well
  u8 unknown9:7,
     dial_func:1;
  u8 unknown10:7,
     lcd:1;
  u8 unknown11:5,
     pwr_save:3;
  u8 unknown12:7,
     sel_speed:1;
  u8 unknown13:6,
     mic_mode:2;
  u8 unknown14:6,
     battery_save:2;
  u8 unknown15;
  u8 unknown16:6,
     resume:2;
  u8 unknown17:5,
     func_mode:3;
  u8 unknown18:6,
     backlight:2;
  u8 unknown19;
  u8 unknown:4,
     vox_gain:4;
  u8 unknown20:6,
     mic_gain:2;
  u8 unknown21:5,
     vox_delay:3;
  u8 unknown22:4,
     vox_tot:4;
  u8 unknown23[2];
  u8 unknown24:6,
     edge:2;
  u8 unknown25;
  u8 unknown26:7,
     auto_low_pwr:1;
  u8 unknown27[3];

} settings;


"""

SPECIAL_CHANNELS = {
    "1A": 200, "1B": 201,
    "2A": 202, "2B": 203,
    "3A": 204, "3B": 205,
    "C": 206,
}

TMODES = ["", "Tone", "TSQL", "DTCS"]
MODES = ["FM", "NFM"]
SKIPS = ["", "S"]
DUPLEXES = ["", "-", "+"]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]
TUNING_STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0]
POWER_LEVELS = [
    chirp_common.PowerLevel("High", watts=5.5),
    chirp_common.PowerLevel("Low", watts=0.5),
    chirp_common.PowerLevel("Mid", watts=2.5)
]


@directory.register
class ICV80Radio(icf.IcomCloneModeRadio, chirp_common.ExperimentalRadio):
    """Icom IC-V80"""
    VENDOR = "Icom"
    MODEL = "IC-V80"

    _model = "\x32\x54\x00\x01"
    _memsize = 0x0E80
    _endframe = "Icom Inc\x2e7C"
    _can_hispeed = True
    _ranges = [(0x0000, 0x0CE0, 32),
               (0x0CE0, 0x0D40, 16),
               (0x0D40, 0x0E00, 32),
               (0x0E00, 0x0E20, 16),
               (0x0E20, 0x0E60, 32),
               (0x0E60, 0x0E70, 16),
               (0x0E70, 0x0E72,  2),
               (0x0E72, 0x0E77,  5),
               (0x0E77, 0x0E78,  1),
               (0x0E78, 0x0E80,  8),
               ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is currently under development, "
                           "and not all the features or functions may work as"
                           "expected. You should proceed with caution.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.memory_bounds = (0, 199)
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_duplexes = DUPLEXES + ['off']
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = SKIPS
        rf.valid_name_length = 5
        rf.valid_special_chans = sorted(SPECIAL_CHANNELS.keys())
        rf.valid_bands = [(136000000, 174000000)]
        rf.has_ctone = True
        rf.has_offset = True
        rf.has_bank = False
        rf.has_settings = True

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(ICV80_MEM_FORMAT, self._mmap)

    def get_settings(self):
        _settings = self._memobj.settings

        setmode = RadioSettingGroup("setmode", "Set Mode")
        display = RadioSettingGroup("display", "Display")
        sounds = RadioSettingGroup("sounds", "Sounds")
        scan = RadioSettingGroup("scan", "Scan")
        settings = RadioSettings(setmode, display, sounds, scan)

        # TOT
        opts = ["Off"] + ["%d min" % t for t in range(1, 31)]
        setmode.append(
            RadioSetting(
                "tot", "Time out Timer",
                RadioSettingValueList(opts, current_index=_settings.tot)))

        # Lockout
        opts = ["Off", "Rpt", "Busy"]
        setmode.append(
            RadioSetting(
                "lockout", "Lockout",
                RadioSettingValueList(opts, current_index=_settings.lockout)))

        # Auto Power Off
        opts = ["Off", "30 min", "1 hr", "2 hrs"]
        setmode.append(
            RadioSetting(
                "auto_pwr_off", "Auto Power Off",
                RadioSettingValueList(
                    opts, current_index=_settings.auto_pwr_off)))

        # Power Save
        opts = ["Off", "1:2", "1:8", "1:16", "Auto"]
        setmode.append(
            RadioSetting(
                "pwr_save", "Power Save",
                RadioSettingValueList(opts, current_index=_settings.pwr_save)))

        # Battery Save
        opts = ["Off", "Ni-MH", "Li-Ion"]
        setmode.append(
            RadioSetting(
                "battery_save", "Battery Save",
                RadioSettingValueList(
                    opts, current_index=_settings.battery_save)))

        # Auto Low Power
        opts = ["Off", "On"]
        setmode.append(
            RadioSetting(
                "auto_low_pwr", "Auto Low Power",
                RadioSettingValueList(
                    opts, current_index=_settings.auto_low_pwr)))

        # Squelch Delay
        opts = ["Short", "Long"]
        setmode.append(
            RadioSetting(
                "squelch_delay", "Squelch Delay",
                RadioSettingValueList(
                    opts, current_index=_settings.squelch_delay)))

        # MIC Simple Mode
        opts = ["Simple", "Normal 1", "Normal 2"]
        setmode.append(
            RadioSetting(
                "mic_mode", "Mic Simple Mode",
                RadioSettingValueList(opts, current_index=_settings.mic_mode)))

        # MIC Gain
        opts = ["1", "2", "3", "4"]
        setmode.append(
            RadioSetting(
                "mic_gain", "Mic Gain",
                RadioSettingValueList(opts, current_index=_settings.mic_gain)))

        # VOX Gain
        opts = ["Off"] + ["%d" % t for t in range(1, 11)]
        setmode.append(
            RadioSetting(
                "vox_gain", "VOX Gain",
                RadioSettingValueList(opts, current_index=_settings.vox_gain)))

        # VOX Delay
        opts = ["0.5 sec", "1.0 sec", "1.5 sec", "2.0 sec", "2.5 sec",
                "3.0 sec"]
        setmode.append(
            RadioSetting(
                "vox_delay", "VOX Delay",
                RadioSettingValueList(
                    opts, current_index=_settings.vox_delay)))

        # VOX Time out Timer
        opts = ["Off", "1 min", "2 min", "3 min", "4 min", "5 min", "10 min",
                "15 min"]
        setmode.append(
            RadioSetting(
                "vox_tot", "VOX Time-Out Timer",
                RadioSettingValueList(opts, current_index=_settings.vox_tot)))

        # Select Speed
        opts = ["Manual", "Auto"]
        setmode.append(
            RadioSetting(
                "sel_speed", "Select Speed",
                RadioSettingValueList(
                    opts, current_index=_settings.sel_speed)))

        # Dial Function
        opts = ["Audio Volume", "Tuning Dial"]
        setmode.append(
            RadioSetting(
                "dial_func", "Dial Function",
                RadioSettingValueList(
                    opts, current_index=_settings.dial_func)))

        # Function Mode
        opts = ["0 sec", "1 sec", "2 sec", "3 sec", "Manual"]
        setmode.append(
            RadioSetting(
                "func_mode", "Function Mode",
                RadioSettingValueList(
                    opts, current_index=_settings.func_mode)))

        # Backlight
        opts = ["Off", "On", "Auto"]
        display.append(
            RadioSetting(
                "backlight", "Backlight",
                RadioSettingValueList(
                    opts, current_index=_settings.backlight)))

        # LCD Contrast
        opts = ["Low", "Auto"]
        display.append(
            RadioSetting(
                "lcd", "LCD Contrast",
                RadioSettingValueList(opts, current_index=_settings.lcd)))

        # Memory Display
        opts = ["Frequency", "Channel", "Name"]
        display.append(
            RadioSetting(
                "mem_display1", "Memory Display",
                RadioSettingValueList(
                    opts, current_index=_settings.mem_display1)))

        # Beep
        opts = ["Off", "1", "2", "3"]
        sounds.append(
            RadioSetting(
                "beep", "Beep",
                RadioSettingValueList(opts, current_index=_settings.beep)))

        # Edge
        opts = ["All", "P1", "P2", "P3"]
        scan.append(
            RadioSetting(
                "edge", "Edge",
                RadioSettingValueList(opts, current_index=_settings.edge)))

        # Resume
        opts = ["T-5", "T-10", "T-15", "P-2"]
        scan.append(
            RadioSetting(
                "resume", "Resume",
                RadioSettingValueList(opts, current_index=_settings.resume)))

        return settings

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue

            try:
                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    element.run_apply_callback()
                else:
                    setting = element.get_name()
                    LOG.debug("Setting %s = %s" % (setting, element.value))
                    setattr(_settings, setting, element.value)
                    # This appears to need to be mirrored?
                    if element.get_name() == 'mem_display1':
                        _settings.mem_display2 = _settings.mem_display1
            except Exception:
                LOG.debug(element.get_name())
                raise

    def _get_memory(self, number, extd_number=None):
        bit = 1 << (number % 8)
        byte = number // 8

        _mem = self._memobj.memory[number]
        _unused = self._memobj.unused[byte]
        _skip = self._memobj.skip[byte]

        mem = chirp_common.Memory(number)

        if extd_number is not None:
            mem.extd_number = extd_number
            mem.immutable = ["name", "number", "extd_number", "skip"]
            if extd_number == "C":
                _unused = False

        if (_unused & bit):
            mem.empty = True
            return mem

        if int(_mem.mult):
            mult = 6250
        else:
            mult = 5000
        mem.freq = int(_mem.freq) * mult
        mem.offset = int(_mem.offset) * mult
        if mem.extd_number == "":
            mem.name = str(_mem.name).rstrip()
            mem.skip = (_skip & bit) and "S" or ""
        if _mem.tx_inhibit:
            mem.duplex = 'off'
        else:
            mem.duplex = DUPLEXES[_mem.duplex]
        mem.power = POWER_LEVELS[_mem.power]
        mem.tuning_step = TUNING_STEPS[_mem.tuning_step]
        mem.mode = MODES[_mem.mode]
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_polarity]

        # Reverse duplex
        mem.extra = RadioSettingGroup("extra", "Extra")
        rev = RadioSetting("reverse_duplex", "Reverse duplex",
                           RadioSettingValueBoolean(bool(_mem.reverse_duplex)))
        rev.set_doc("Reverse duplex")
        mem.extra.append(rev)

        return mem

    def get_memory(self, number):
        extd_number = None
        if isinstance(number, str):
            try:
                extd_number = number
                number = SPECIAL_CHANNELS[number]
            except KeyError:
                raise errors.InvalidMemoryLocation(
                    "Unknown channel %s" % number)

        return self._get_memory(number, extd_number)

    def _fill_memory(self, mem):
        number = mem.number
        _mem = self._memobj.memory[number]

        # zero-fill
        _mem.freq = 146010000 // 5000
        _mem.offset = 600000 // 5000
        _mem.name = str("").ljust(5)
        _mem.duplex = 0x0
        _mem.reverse_duplex = 0x0
        _mem.tx_inhibit = 0x1
        _mem.power = 0x0
        _mem.tuning_step = 0x0
        _mem.mode = 0x0
        _mem.tmode = 0x0
        _mem.rtone = 0x8
        _mem.ctone = 0x8
        _mem.dtcs = 0x0
        _mem.dtcs_polarity = 0x0

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def set_memory(self, mem):
        bit = 1 << (mem.number % 8)
        byte = mem.number // 8

        _mem = self._memobj.memory[mem.number]
        _unused = self._memobj.unused[byte]
        _skip = (mem.extd_number == "") and self._memobj.skip[byte] or None
        assert (_mem)

        if mem.empty:
            self._fill_memory(mem)
            _unused |= bit
            if _skip is not None:
                _skip |= bit
            return

        _mem.set_raw(b'\x00' * 16)

        if chirp_common.required_step(mem.freq) == 12.5:
            mult = 6250
        else:
            mult = 5000
        _mem.mult = 0 if mult == 5000 else 3
        _mem.freq = mem.freq // mult
        _mem.offset = int(mem.offset) // mult
        _mem.name = str(mem.name).ljust(5)
        try:
            _mem.duplex = DUPLEXES.index(mem.duplex)
        except ValueError:
            _mem.duplex = 0
        power = mem.power or POWER_LEVELS[0]
        _mem.power = POWER_LEVELS.index(power)
        _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
        _mem.mode = MODES.index(mem.mode)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCS_POLARITY.index(mem.dtcs_polarity)
        _mem.tx_inhibit = mem.duplex == 'off'

        # Set used
        _unused &= ~bit

        # Set skip
        if _skip is not None:
            if mem.skip == "S":
                _skip |= bit
            else:
                _skip &= ~bit

        if mem.extra:
            _mem.reverse_duplex = mem.extra['reverse_duplex'].value

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])
