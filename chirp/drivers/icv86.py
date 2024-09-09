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
    RadioSettingValueBoolean, RadioSettings

LOG = logging.getLogger(__name__)


ICV86_MEM_FORMAT = """
#seekto 0x040;
u8 skips[26];

#seekto 0x060;
u8 used[26];

#seekto 0x00BF;
struct {
  u8 reserved1[8];
  u8 reserved2:6,
     disp_type:2;
  u8 reserved3;
  u8 reserved4:7,
     dial_assignment:1;
  u8 reserved5[8];
  u8 reserved6:6,
     lcd:2;
  u8 reserved7[2];
  u8 reserved8:6,
     mic:2;
} settings;

#seekto 0x0200;
struct {
  ul32 freq;
  ul32 offset;
  char name[5];
  u8 reserved1:2,
     rtone:6;
  u8 reserved2:2,
     ctone:6;
  u8 reserved3:1,
     dtcs:7;
  u8 reserved4:5,
     tuning_step:3;
  u8 reserved5:2,
     mode:1,
     rev:1,
     duplex:2,
     reserved6:2;
  u8 reserved7:2,
     dtcs_polarity:2,
     tmode:4;
  u8 reserved8:5,
     tx:1,
     power:2;
  u8 reserved9;
  u8 reserved10;
  u8 reserved11;
  u8 reserved12;
} memory[207];

"""

SPECIAL = {
    "0A": 200, "0B": 201,
    "1A": 202, "1B": 203,
    "2A": 204, "2B": 205,
    "C": 206,
}

SPECIAL_REV = {
    200: "0A", 201: "0B",
    202: "1A", 203: "1B",
    204: "2A", 205: "2B",
    206: "C",
}

TMODES = ["", "Tone", "TSQL", "DTCS", "DTCS-R"]
MODES = ["FM", "NFM"]
SKIPS = ["", "S"]
DUPLEXES = ["", "-", "+"]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]
TUNING_STEPS = [5., 10., 12.5, 15., 20., 25., 30., 50.]
POWER_LEVELS = [
    chirp_common.PowerLevel("High", watts=5.5),
    chirp_common.PowerLevel("Low", watts=0.5),
    chirp_common.PowerLevel("Mid", watts=2.5),
    chirp_common.PowerLevel("Extra High", watts=7.0),
]


@directory.register
class ICV86Radio(icf.IcomCloneModeRadio):
    """Icom IC-V86"""
    VENDOR = "Icom"
    MODEL = "IC-V86"

    _model = "\x40\x66\x00\x01"
    _memsize = 5504
    _endframe = "Icom Inc\x2eAC"

    _ranges = [(0x0000, 5504, 32)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.memory_bounds = (0, 199)
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_duplexes = DUPLEXES
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = SKIPS
        rf.valid_name_length = 5
        rf.valid_special_chans = sorted(SPECIAL.keys())
        rf.valid_bands = [(136000000, 174000000)]
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

        setmode = RadioSettingGroup("setmode", "General Settings")

        settings = RadioSettings(setmode)

        # LCD Backlight
        opts = ["Off", "On", "Auto"]
        setmode.append(
            RadioSetting(
                "lcd", "LCD Backlight",
                RadioSettingValueList(opts, current_index=_settings.lcd)))

        # Mic Gain
        rs = RadioSetting("mic", "Mic Gain",
                          RadioSettingValueInteger(1, 4, _settings.mic + 1))

        def apply_mic(s, obj):
            setattr(obj, s.get_name(), int(s.value) - 1)
        rs.set_apply_callback(apply_mic, self._memobj.settings)
        setmode.append(rs)

        # Dial Assignment
        opts = ["Volume", "Tuning"]
        setmode.append(
            RadioSetting(
                "dial_assignment", "Dial Assignment",
                RadioSettingValueList(opts, current_index=_settings.dial_assignment)))

        # Display Type
        opts = ["Frequency", "Channel", "Name"]
        setmode.append(
            RadioSetting(
                "disp_type", "Display Type",
                RadioSettingValueList(opts, current_index=_settings.disp_type)))

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

    def _get_memory(self, number):
        bit = 1 << (number % 8)
        byte = int(number / 8)

        mem = chirp_common.Memory()
        mem.number = number

        _mem = self._memobj.memory[number]

        if number < 200:
            _usd = self._memobj.used[byte]
            _skp = self._memobj.skips[byte]
        else:
            mem.extd_number = SPECIAL_REV[number]
            mem.immutable = ["name", "number", "extd_number", "skip"]
            _usd = self._memobj.used[byte] if (number <= 206) else None
            _skp = None

        if _usd is not None and (_usd & bit):
            mem.empty = True
            return mem

        mem.freq = _mem.freq
        mem.offset = int(_mem.offset)
        if number < 200:
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

        # Extras
        mem.extra = RadioSettingGroup("extra", "Extra")
        rev = RadioSetting("rev", "Reverse duplex",
                           RadioSettingValueBoolean(bool(_mem.rev)))
        rev.set_doc("Reverse duplex")
        mem.extra.append(rev)

        tx = RadioSetting("tx", "Tx permission",
                          RadioSettingValueBoolean(bool(_mem.tx)))
        tx.set_doc("Tx permission")
        mem.extra.append(tx)

        if _skp is not None:
            mem.skip = (_skp & bit) and "S" or ""

        return mem

    def get_memory(self, number):
        if not self._mmap:
            self.sync_in()

        assert (self._mmap)

        if isinstance(number, str):
            try:
                number = SPECIAL[number]
            except KeyError:
                raise errors.InvalidMemoryLocation("Unknown channel %s" % number)

        return self._get_memory(number)

    def _fill_memory(self, number):
        _mem = self._memobj.memory[number]

        assert (_mem)

        # zero-fill
        _mem.freq = 146010000
        _mem.offset = 146010000
        _mem.name = str("").ljust(5)
        _mem.reserved1 = 0x0
        _mem.rtone = 0x8
        _mem.reserved2 = 0x0
        _mem.ctone = 0x8
        _mem.reserved3 = 0x0
        _mem.dtcs = 0x0
        _mem.reserved4 = 0x0
        _mem.tuning_step = 0x0
        _mem.reserved5 = 0x0
        _mem.mode = 0x0
        _mem.rev = 0x0
        _mem.duplex = 0x0
        _mem.reserved6 = 0x0
        _mem.reserved7 = 0x0
        _mem.dtcs_polarity = 0x0
        _mem.tmode = 0x0
        _mem.tx = 0x1
        _mem.reserved8 = 0x0
        _mem.power = 0x0
        _mem.reserved9 = 0x0
        _mem.reserved10 = 0x0
        _mem.reserved11 = 0x0
        _mem.reserved12 = 0x0

    def _set_memory(self, mem):
        bit = 1 << (mem.number % 8)
        byte = int(mem.number / 8)

        _mem = self._memobj.memory[mem.number]
        _usd = self._memobj.used[byte] if mem.number <= 206 else None
        _skp = self._memobj.skips[byte] if mem.number < 200 else None

        assert (_mem)

        if mem.empty:
            self._fill_memory(mem.number)
            if _usd is not None:
                _usd |= bit
            return

        if _usd is None or (_usd & bit):
            self._fill_memory(mem.number)

        _mem.freq = mem.freq
        _mem.offset = int(mem.offset)
        _mem.name = str(mem.name).ljust(5)
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
            _usd &= ~bit

        if _skp is not None:
            if mem.skip == "S":
                _skp |= bit
            else:
                _skp &= ~bit

    def set_memory(self, mem):
        if not self._mmap:
            self.sync_in()

        assert (self._mmap)

        return self._set_memory(mem)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number]) + \
            repr(self._memobj.used[(number)])
