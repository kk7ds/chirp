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

import struct
import logging

from chirp.drivers import icf
from chirp import chirp_common, directory, bitwise
from chirp.chirp_common import to_GHz, from_GHz
from chirp.settings import RadioSetting, RadioSettingGroup, \
                RadioSettingValueBoolean, RadioSettingValueList, \
                RadioSettingValueInteger, RadioSettingValueString, \
                RadioSettingValueFloat, RadioSettings


LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  bbcd freq[3];
  u8  fractional:1,
      unknown:7;
  bbcd offset[2];
  u16 ctone:6
      rtone:6,
      tune_step:4;
} memory[200];

#seekto 0x0690;
struct {
  u8 tmode:2,
     duplex:2,
     skip:1,
     pskip:1,
     mode:2;
} flags[200];

#seekto 0x0690;
u8 flags_whole[200];

#seekto 0x0767;
struct {
i8 rit;
u8 squelch;
u8 lock:1,
   ritfunct:1,
   unknown:6;
u8 unknown1[6];
u8 d_sel;
u8 autorp;
u8 priority;
u8 resume;
u8 pause;
u8 p_scan;
u8 bnk_scan;
u8 expand;
u8 ch;
u8 beep;
u8 light;
u8 ap_off;
u8 p_save;
u8 monitor;
u8 speed;
u8 edge;
u8 lockgroup;
} settings;

"""

TMODES = ["", "", "Tone", "TSQL", "TSQL"]  # last one is pocket beep
DUPLEX = ["", "", "-", "+"]
MODES = ["FM", "WFM", "AM", "Auto"]
STEPS = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]
AUTORP_LIST = ["Off", "Duplex Only", "Duplex and Tone"]
LOCKGROUP_LIST = ["Normal", "No Squelch", "No Volume", "All"]
SQUELCH_LIST = ["Open", "Auto"] + ["L%s" % x for x in range(1, 10)]
MONITOR_LIST = ["Push", "Hold"]
LIGHT_LIST = ["Off", "On", "Auto"]
PRIORITY_LIST = ["Off", "On", "Bell"]
BANKSCAN_LIST = ["Off", "Bank 0", "Bank 1"]
EDGE_LIST = ["%sP" % x for x in range(0, 20)] + ["Band", "All"]
PAUSE_LIST = ["%s sec" % x for x in range(2, 22, 2)] + ["Hold"]
RESUME_LIST = ["%s sec" % x for x in range(0, 6)]
APOFF_LIST = ["Off"] + ["%s min" % x for x in range(30, 150, 30)]
D_SEL_LIST = ["100 KHz", "1 MHz", "10 MHz"]


@directory.register
class ICQ7Radio(icf.IcomCloneModeRadio):
    """Icom IC-Q7A"""
    VENDOR = "Icom"
    MODEL = "IC-Q7A"

    _model = "\x19\x95\x00\x01"
    _memsize = 0x7C0
    _endframe = "Icom Inc\x2e"

    _ranges = [(0x0000, 0x07C0, 16)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.memory_bounds = (0, 199)
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(1000000,   823995000),
                          (849000000, 868995000),
                          (894000000, 1309995000)]
        rf.valid_skips = ["", "S", "P"]
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_name = False
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return (repr(self._memobj.memory[number]) +
                repr(self._memobj.flags[number]))

    def validate_memory(self, mem):
        if mem.freq < 30000000 and mem.mode != 'AM':
            return [chirp_common.ValidationError(
                'Only AM is allowed below 30MHz')]
        return icf.IcomCloneModeRadio.validate_memory(self, mem)

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]

        mem = chirp_common.Memory()
        mem.number = number
        if self._memobj.flags_whole[number] == 0xFF:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 1000
        if _mem.fractional:
            mem.freq = chirp_common.fix_rounded_step(mem.freq)
        mem.offset = int(_mem.offset) * 1000
        try:
            mem.rtone = chirp_common.TONES[_mem.rtone]
        except IndexError:
            mem.rtone = 88.5
        try:
            mem.ctone = chirp_common.TONES[_mem.ctone]
        except IndexError:
            mem.ctone = 88.5
        try:
            mem.tuning_step = STEPS[_mem.tune_step]
        except IndexError:
            LOG.error("Invalid tune step index %i" % _mem.tune_step)
        mem.tmode = TMODES[_flag.tmode]
        mem.duplex = DUPLEX[_flag.duplex]
        if mem.freq < 30000000:
            mem.mode = "AM"
        else:
            mem.mode = MODES[_flag.mode]
        if _flag.pskip:
            mem.skip = "P"
        elif _flag.skip:
            mem.skip = "S"

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flag = self._memobj.flags[mem.number]

        if mem.empty:
            self._memobj.flags_whole[mem.number] = 0xFF
            return

        _mem.set_raw("\x00" * 8)

        if mem.freq > to_GHz(1):
            _mem.freq = (mem.freq // 1000) - to_GHz(1)
            upper = from_GHz(mem.freq) << 4
            _mem.freq[0].clr_bits(0xF0)
            _mem.freq[0].set_bits(upper)
        else:
            _mem.freq = mem.freq / 1000
        _mem.fractional = chirp_common.is_fractional_step(mem.freq)
        _mem.offset = mem.offset / 1000
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        _flag.tmode = TMODES.index(mem.tmode)
        _flag.duplex = DUPLEX.index(mem.duplex)
        _flag.mode = MODES.index(mem.mode)
        _flag.skip = mem.skip == "S" and 1 or 0
        _flag.pskip = mem.skip == "P" and 1 or 0

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        rs = RadioSetting("ch", "Channel Indication Mode",
                          RadioSettingValueBoolean(_settings.ch))
        basic.append(rs)

        rs = RadioSetting("expand", "Expanded Settings Mode",
                          RadioSettingValueBoolean(_settings.expand))
        basic.append(rs)

        rs = RadioSetting("beep", "Beep Tones",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting("autorp", "Auto Repeater Function",
                          RadioSettingValueList(
                              AUTORP_LIST, AUTORP_LIST[_settings.autorp]))
        basic.append(rs)

        rs = RadioSetting("ritfunct", "RIT Runction",
                          RadioSettingValueBoolean(_settings.ritfunct))
        basic.append(rs)

        rs = RadioSetting("rit", "RIT Shift (KHz)",
                          RadioSettingValueInteger(-7, 7, _settings.rit))
        basic.append(rs)

        rs = RadioSetting("lock", "Lock",
                          RadioSettingValueBoolean(_settings.lock))
        basic.append(rs)

        rs = RadioSetting("lockgroup", "Lock Group",
                          RadioSettingValueList(
                              LOCKGROUP_LIST,
                              LOCKGROUP_LIST[_settings.lockgroup]))
        basic.append(rs)

        rs = RadioSetting("squelch", "Squelch",
                          RadioSettingValueList(
                              SQUELCH_LIST, SQUELCH_LIST[_settings.squelch]))
        basic.append(rs)

        rs = RadioSetting("monitor", "Monitor Switch Function",
                          RadioSettingValueList(
                              MONITOR_LIST,
                              MONITOR_LIST[_settings.monitor]))
        basic.append(rs)

        rs = RadioSetting("light", "Display Backlighting",
                          RadioSettingValueList(
                              LIGHT_LIST, LIGHT_LIST[_settings.light]))
        basic.append(rs)

        rs = RadioSetting("priority", "Priority Watch Operation",
                          RadioSettingValueList(
                              PRIORITY_LIST,
                              PRIORITY_LIST[_settings.priority]))
        basic.append(rs)

        rs = RadioSetting("p_scan", "Frequency Skip Function",
                          RadioSettingValueBoolean(_settings.p_scan))
        basic.append(rs)

        rs = RadioSetting("bnk_scan", "Memory Bank Scan Selection",
                          RadioSettingValueList(
                              BANKSCAN_LIST,
                              BANKSCAN_LIST[_settings.bnk_scan]))
        basic.append(rs)

        rs = RadioSetting("edge", "Band Edge Scan Selection",
                          RadioSettingValueList(
                              EDGE_LIST, EDGE_LIST[_settings.edge]))
        basic.append(rs)

        rs = RadioSetting("pause", "Scan Pause Time",
                          RadioSettingValueList(
                              PAUSE_LIST, PAUSE_LIST[_settings.pause]))
        basic.append(rs)

        rs = RadioSetting("resume", "Scan Resume Time",
                          RadioSettingValueList(
                              RESUME_LIST, RESUME_LIST[_settings.resume]))
        basic.append(rs)

        rs = RadioSetting("p_save", "Power Saver",
                          RadioSettingValueBoolean(_settings.p_save))
        basic.append(rs)

        rs = RadioSetting("ap_off", "Auto Power-off Function",
                          RadioSettingValueList(
                              APOFF_LIST, APOFF_LIST[_settings.ap_off]))
        basic.append(rs)

        rs = RadioSetting("speed", "Dial Speed Acceleration",
                          RadioSettingValueBoolean(_settings.speed))
        basic.append(rs)

        rs = RadioSetting("d_sel", "Dial Select Step",
                          RadioSettingValueList(
                              D_SEL_LIST, D_SEL_LIST[_settings.d_sel]))
        basic.append(rs)

        return group

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise
