# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings

LOG = logging.getLogger(__name__)


ICV86_MEM_FORMAT = """
#seekto 0x020;
lbit pskips[208];

#seekto 0x040;
lbit skips[208];

#seekto 0x060;
lbit used[208];

struct {
  #seekto 0x010;
  char comment[16];

  #seekto 0x0FD;
  u8 wx_channel;

  #seekto 0x100;
  u8 reserved1:6,
     beep:2;
  u8 reserved2:3,
     tot:5;
  u8 reserved3;
  u8 reserved4:6,
     auto_pwr:2;
  u8 reserved5:6,
     lockout:2;
  u8 reserved6:7,
     sql_delay:1;
  u8 reserved7;
  u8 reserved8:6,
     disp_type:2;
  u8 reserved9;
  u8 reserved10:5,
     pwr_save:3;
  u8 reserved11:7,
     dial_speedup:1;
  u8 reserved12:6,
     simple_mode:2;
  u8 reserved13:7,
     ant:1;
  u8 reserved14:7,
     monitor:1;
  u8 reserved15;
  u8 reserved16;
  u8 reserved17:6,
     pause_timer:2;
  u8 reserved18;
  u8 reserved19:7,
     skip_scan:1;
  u8 reserved20:6,
     lcd:2;
  u8 reserved21:7,
     wx:1;
  u8 reserved22:6,
     mic:2;
  u8 reserved23:4,
     vox_gain:4;
  u8 reserved24:5,
     vox_delay:3;
  u8 reserved25:5,
     vox_tot:3;
  u8 reserved26;
  u8 reserved27;
  u8 reserved28:5,
     edge:3;
  u8 reserved29;
  u8 reserved30:7,
     auto_low:1;
  u8 reserved31:7,
     volt:1;
  u8 reserved32:7,
     ctcss_burst:1;
  u8 reserved33;
  u8 reserved34;
  u8 reserved35;
  u8 reserved36:7,
     vox:1;
  u8 reserved37;
  u8 reserved38;
  u8 reserved39:6,
     p_short:2;
  u8 reserved40:6,
     p_long:2;
} settings;

#seekto 0x0240;
struct {
  ul32 freq;
  ul32 offset;
  char name[6];
  u8 reserved1:2,
     rtone:6;
  u8 reserved2:2,
     ctone:6;
  u8 reserved3:1,
     dtcs:7;
  u8 reserved4:4,
     tuning_step:4;
  u8 reserved5:2,
     mode:1,
     rev:1,
     duplex:2,
     reserved6:2;
  u8 reserved7:2,
     dtcs_polarity:2,
     tmode:4;
  u8 reserved8:5,
     tx_inhibit:1,
     power:2;
  u8 reserved9;
  u8 reserved10;
  u8 reserved11;
} memory[208];

"""

SPECIAL = {
    "1A": 200, "1B": 201,
    "2A": 202, "2B": 203,
    "3A": 204, "3B": 205,
    "C0": 206, "C1": 207,
}

TMODES = ["", "Tone", "TSQL", "DTCS"]
MODES = ["FM", "NFM"]
SKIPS = ["", "S", "P"]
DUPLEXES = ["", "-", "+"]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]
TUNING_STEPS = [5., 10., 12.5, 15., 20., 25., 30., 50., 100., 125., 200.]
POWER_LEVELS = [
    chirp_common.PowerLevel("High", watts=5.0),
    chirp_common.PowerLevel("Low", watts=0.5),
    chirp_common.PowerLevel("Mid", watts=2.5),
]


@directory.register
class ICVT10Radio(icf.IcomCloneModeRadio):
    """Icom IC-T10"""
    VENDOR = "Icom"
    MODEL = "IC-T10"

    _model = "\x43\x28\x00\x01"
    _memsize = 5888
    _endframe = "Icom Inc\x2eB8"

    _ranges = [(0x0000, 5888, 32)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.memory_bounds = (0, 199)
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_duplexes = DUPLEXES
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = SKIPS
        rf.valid_name_length = 6
        rf.valid_special_chans = list(SPECIAL.keys())
        rf.valid_bands = [(136000000, 174000000), (400000000, 479000000)]
        rf.has_ctone = True
        rf.has_offset = True
        rf.has_bank = False
        rf.has_settings = True

        return rf

    def __init__(self, pipe):
        icf.IcomCloneModeRadio.__init__(self, pipe)

    def sync_in(self):
        icf.IcomCloneModeRadio.sync_in(self)

    def sync_out(self):
        icf.IcomCloneModeRadio.sync_out(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(ICV86_MEM_FORMAT, self._mmap)

    def get_settings(self):
        _settings = self._memobj.settings

        setmode = RadioSettingGroup("setmode", "Set Mode")
        assign = RadioSettingGroup("assign", "Key Assign")
        display = RadioSettingGroup("display", "Display")
        sounds = RadioSettingGroup("sounds", "Sounds")
        scan = RadioSettingGroup("Scan", "Scan")
        fm = RadioSettingGroup("fm", "FM Radio")
        wx = RadioSettingGroup("wx", "WX")

        settings = RadioSettings(
            setmode, assign, display, sounds, scan, fm, wx)

        # Timeout Timer
        opts = ["Off"] + ["%s min" % x for x in range(1, 31)]
        setmode.append(
            RadioSetting(
                "tot", "Timeout Timer",
                RadioSettingValueList(opts, current_index=_settings.tot)))

        # Auto Power Off
        opts = ["Off", "30 min", "1 hr", "2 hrs"]
        setmode.append(
            RadioSetting(
                "auto_pwr", "Auto Power Off",
                RadioSettingValueList(opts, current_index=_settings.auto_pwr)))

        # Lockout
        opts = ["Off", "Rpt", "Busy"]
        setmode.append(
            RadioSetting(
                "lockout", "Lockout",
                RadioSettingValueList(opts, current_index=_settings.lockout)))

        # Squelch Delay
        opts = ["Short", "Long"]
        setmode.append(
            RadioSetting(
                "sql_delay", "Squelch Delay",
                RadioSettingValueList(
                    opts, current_index=_settings.sql_delay)))

        # Power Save
        opts = ["Off", "1:2", "1:8", "1:16", "Auto"]
        setmode.append(
            RadioSetting(
                "pwr_save", "Power Save",
                RadioSettingValueList(opts, current_index=_settings.pwr_save)))

        # Dial Speed-up
        setmode.append(
            RadioSetting(
                "dial_speedup", "Dial Speed-Up",
                RadioSettingValueBoolean(bool(_settings.dial_speedup))))

        # Mic Simple Mode
        opts = ["Simple", "Normal-1", "Normal-2"]
        setmode.append(
            RadioSetting(
                "simple_mode", "Mic Simple Mode",
                RadioSettingValueList(
                    opts, current_index=_settings.simple_mode)))

        # Mic Gain
        rs = RadioSetting(
                "mic", "Mic Gain",
                RadioSettingValueInteger(1, 4, _settings.mic + 1))
        rs.set_apply_callback(
            lambda s, obj: setattr(obj, s.get_name(), int(s.value) - 1),
            self._memobj.settings)
        setmode.append(rs)

        # Auto Low Power
        setmode.append(
            RadioSetting(
                "auto_low", "Auto Low Power",
                RadioSettingValueBoolean(bool(_settings.auto_low))))

        # Vox Function
        setmode.append(
            RadioSetting(
                "vox", "Vox Function",
                RadioSettingValueBoolean(bool(_settings.vox))))

        # Vox Gain
        opts = ["Off"] + ["%s" % x for x in range(1, 11)]
        setmode.append(
            RadioSetting(
                "vox_gain", "Vox Gain",
                RadioSettingValueList(
                    opts, current_index=_settings.vox_gain)))

        # Vox Delay
        opts = ["0.5 seconds", "1.0 seconds", "1.5 seconds", "2.0 seconds",
                "2.5 seconds", "3.0 seconds"]
        setmode.append(
            RadioSetting(
                "vox_delay", "Vox Delay",
                RadioSettingValueList(
                    opts, current_index=_settings.vox_delay)))

        # VOX Time out Timer
        opts = ["Off", "1 min", "2 min", "3 min", "4 min", "5 min",
                "10 min", "15 min"]
        setmode.append(
            RadioSetting(
                "vox_tot", "VOX Time-Out Timer",
                RadioSettingValueList(opts, current_index=_settings.vox_tot)))

        # CTCSS Burst
        setmode.append(
            RadioSetting(
                "ctcss_burst", "CTCSS Burst",
                RadioSettingValueBoolean(bool(_settings.ctcss_burst))))

        # Monitor
        opts = ["Push", "Hold"]
        setmode.append(
            RadioSetting(
                "monitor", "Monitor",
                RadioSettingValueList(opts, current_index=_settings.monitor)))

        # Comment
        setmode.append(
            RadioSetting(
                "comment", "Comment",
                RadioSettingValueString(
                    0, 16, str(_settings.comment).rstrip(), autopad=False)))

        # P (Short)
        opts = ["Null", "TS", "MHz", "T-CALL"]
        assign.append(
            RadioSetting(
                "p_short", "P (Short)",
                RadioSettingValueList(opts, current_index=_settings.p_short)))

        # P (Long)
        opts = ["Null", "TS", "MHz", "T-CALL"]
        assign.append(
            RadioSetting(
                "p_long", "P (Short)",
                RadioSettingValueList(opts, current_index=_settings.p_long)))

        # Backlight
        opts = ["Off", "On", "Auto"]
        display.append(
            RadioSetting(
                "lcd", "Backlight",
                RadioSettingValueList(opts, current_index=_settings.lcd)))

        # Display Type
        opts = ["Frequency", "Channel", "Name"]
        display.append(
            RadioSetting(
                "disp_type", "Display Type",
                RadioSettingValueList(
                    opts, current_index=_settings.disp_type)))

        # Voltage Indicator
        opts = ["Off", "On"]
        display.append(
            RadioSetting(
                "volt", "Voltage Indicator",
                RadioSettingValueList(opts, current_index=_settings.volt)))

        # Timeout Timer
        opts = ["Off"] + ["%d" % x for x in range(1, 4)]
        sounds.append(
            RadioSetting(
                "beep", "Beep Level",
                RadioSettingValueList(opts, current_index=_settings.beep)))

        # Program Skip Scan
        scan.append(
            RadioSetting(
                "skip_scan", "Program Skip Scan",
                RadioSettingValueBoolean(bool(_settings.skip_scan))))

        # Edge
        opts = ["All", "Band", "P1", "P2", "P3"]
        scan.append(
            RadioSetting(
                "edge", "Edge",
                RadioSettingValueList(opts, current_index=_settings.edge)))

        # Pause Timer
        opts = ["T-5", "T-10", "T-15", "P-2"]
        scan.append(
            RadioSetting(
                "pause_timer", "Pause Timer",
                RadioSettingValueList(
                    opts, current_index=_settings.pause_timer)))

        # Earphone Antenna
        opts = ["Not Used", "Use"]
        fm.append(
            RadioSetting(
                "ant", "Earphone Antenna",
                RadioSettingValueList(opts, current_index=_settings.ant)))

        # WX Alert
        wx.append(
            RadioSetting(
                "wx", "WX Alert",
                RadioSettingValueBoolean(bool(_settings.wx))))

        # Mic Gain
        rs = RadioSetting(
                "wx_channel", "WX Channel",
                RadioSettingValueInteger(1, 10, _settings.wx_channel + 1))
        rs.set_apply_callback(
            lambda s, obj: setattr(obj, s.get_name(), int(s.value) - 1),
            self._memobj.settings)
        wx.append(rs)

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
            except Exception:
                LOG.debug(element.get_name())
                raise

    def _get_extra(self, mem):
        ext = RadioSettingGroup("extra", "Extra")

        rev = RadioSetting("rev", "Reverse duplex",
                           RadioSettingValueBoolean(bool(mem.rev)))
        rev.set_doc("Reverse duplex")
        ext.append(rev)

        tx_inhibit = RadioSetting("tx_inhibit", "Tx inhibit",
                                  RadioSettingValueBoolean(
                                    bool(mem.tx_inhibit)))
        tx_inhibit.set_doc("Tx inhibit")
        ext.append(tx_inhibit)

        return ext

    def _get_memory(self, number, extd_number):
        mem = chirp_common.Memory()
        mem.number = number

        _mem = self._memobj.memory[number]

        if extd_number is None:
            _usd = self._memobj.used[number]
            _skp = self._memobj.skips[number]
            _psk = self._memobj.pskips[number]
        else:
            mem.extd_number = extd_number
            mem.immutable = ["number", "extd_number"]
            if (number >= 206):
                mem.immutable.append("skip")
            _usd = self._memobj.used[number] if (number < 206) else None
            _skp = self._memobj.skips[number] if (number < 206) else None
            _psk = self._memobj.pskips[number] if (number < 206) else None

        if _usd is not None and _usd:
            mem.empty = True
            return mem

        mem.freq = _mem.freq
        mem.offset = int(_mem.offset)
        mem.name = str(_mem.name).rstrip()
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.tuning_step = TUNING_STEPS[_mem.tuning_step]
        mem.mode = MODES[_mem.mode]
        mem.duplex = DUPLEXES[_mem.duplex]
        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_polarity]
        mem.tmode = TMODES[_mem.tmode]
        mem.power = POWER_LEVELS[_mem.power]

        mem.extra = self._get_extra(_mem)

        if _skp is not None:
            mem.skip = (_psk and "P") or (_skp and "S") or ""

        return mem

    def get_memory(self, number):
        extd_number = None
        if isinstance(number, str):
            try:
                extd_number = number
                number = dict(SPECIAL)[number]
            except KeyError:
                raise errors.InvalidMemoryLocation(
                    "Unknown channel %s" % number)

        return self._get_memory(number, extd_number)

    def _fill_memory(self, number):
        _mem = self._memobj.memory[number]

        # Default values
        _mem.fill_raw(b'\x00')
        _mem.freq = 146010000
        _mem.offset = 146010000
        _mem.name = str("").ljust(6)
        _mem.rtone = 0x8
        _mem.ctone = 0x8

    def _set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _usd = self._memobj.used[mem.number] if mem.number < 206 else None
        _skp = self._memobj.skips[mem.number] if mem.number < 206 else None
        _psk = self._memobj.pskips[mem.number] if mem.number < 206 else None

        if mem.empty:
            self._fill_memory(mem.number)
            if _usd is not None:
                _usd |= 1
            return

        if _usd is None or _usd:
            self._fill_memory(mem.number)

        _mem.freq = mem.freq
        _mem.offset = int(mem.offset)
        _mem.name = str(mem.name).ljust(6)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
        _mem.mode = MODES.index(mem.mode)
        _mem.duplex = DUPLEXES.index(mem.duplex)
        _mem.dtcs_polarity = DTCS_POLARITY.index(mem.dtcs_polarity)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.power = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

        if _usd is not None:
            _usd &= 0

        if _skp is not None:
            _skp &= 0
            _psk &= 0
            if mem.skip == "S":
                _skp |= 1
            elif mem.skip == "P":
                _psk |= 1

    def set_memory(self, mem):
        return self._set_memory(mem)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number]) + \
            repr(self._memobj.used[(number)])
