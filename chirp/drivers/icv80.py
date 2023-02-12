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
from chirp import chirp_common, memmap, bitwise, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings

LOG = logging.getLogger(__name__)


ICV80_MEM_FORMAT = """

#seekto 0x0000;
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
     unknown5:2;
  u8 unknown6:2,
     dtcs_polarity:2,
     unknown8:2,
     tmode:2;
  u8 unknown8:5,
     tx_inhibit:1,
     power:2;
} memory[208];

#seekto 0x0cf0;
u8 skip[32];

#seekto 0x0d10;
u8 unused[32];

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
TUNING_STEPS = [5., 10., 12.5, 15., 20., 25., 30., 50.]
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
    _memsize = 3712
    _endframe = "Icom Inc\x2e"

    _ranges = [(0x0000, 3712, 16)]

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
        rf.valid_duplexes = DUPLEXES
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = SKIPS
        rf.valid_name_length = 5
        rf.valid_special_chans = sorted(SPECIAL_CHANNELS.keys())
        rf.valid_bands = [(136000000, 174000000)]
        rf.has_ctone = True
        rf.has_offset = True
        rf.has_bank = False
        rf.has_settings = False

        return rf

    def __init__(self, pipe):
        icf.IcomCloneModeRadio.__init__(self, pipe)

    def sync_in(self):
        icf.IcomCloneModeRadio.sync_in(self)

    def sync_out(self):
        icf.IcomCloneModeRadio.sync_out(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(ICV80_MEM_FORMAT, self._mmap)

    def _get_memory(self, number, extd_number = None):
        bit = 1 << (number % 8)
        byte = int(number / 8)

        _mem = self._memobj.memory[number]
        _unused = self._memobj.unused[byte]
        _skip = self._memobj.skip[byte]
        assert(_mem)

        mem = chirp_common.Memory(number)

        if not extd_number is None:
            mem.extd_number = extd_number
            mem.immutable = ["name", "number", "extd_number", "skip"]
            if extd_number == "C":
                _unused = False

        if (_unused & bit):
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 5000
        mem.offset = int(_mem.offset) * 5000
        if extd_number is None:
            mem.name = str(_mem.name).rstrip()
            mem.skip = (_skip & bit) and "S" or ""
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

        # Tx inhibit
        tx_inhibit = RadioSetting("tx_inhibit", "TX inhibit",
                           RadioSettingValueBoolean(bool(not _mem.tx_inhibit)))
        tx_inhibit.set_doc("TX inhibit")
        mem.extra.append(tx_inhibit)

        return mem

    def get_memory(self, number):
        if not self._mmap:
            self.sync_in()

        extd_number = None
        if isinstance(number, str):
            try:
                extd_number = number
                number = SPECIAL_CHANNELS[number]
            except KeyError:
                raise errors.InvalidMemoryLocation("Unknown channel %s" % number)

        return self._get_memory(number, extd_number)

    def _fill_memory(self, number):
        _mem = self._memobj.memory[number]
        assert(_mem)

        # zero-fill
        _mem.freq = 146010000 / 5000
        _mem.offset = 600000 / 5000
        _mem.name =  str("").ljust(5)
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


    def _set_memory(self, mem):
        bit = 1 << (number % 8)
        byte = int(number / 8)

        _mem = self._memobj.memory[mem.number]
        _unused = self._memobj.unused[byte]
        assert(_mem)

        if mem.empty:
            self._fill_memory(mem.number)
            _unused |= bit
            _skip |= bit
            return

        _mem.freq = mem.freq / 5000
        _mem.offset = int(mem.offset) / 5000
        _mem.name = str(mem.name).ljust(5)
        _mem.duplex = DUPLEXES.index(mem.duplex)
        _mem.power = POWER_LEVELS.index(mem.power)
        _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
        _mem.mode = MODES.index(mem.mode)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCS_POLARITY.index(mem.dtcs_polarity)

         # Set used
        _usd &= ~bit

         # Set skip
        if mem.skip == "S":
            _skp |= bit
        else:
            _skp &= ~bit

    def set_memory(self, mem):
        if not self._mmap:
            self.sync_in()
        assert(self._mmap)

        return self._set_memory(mem)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number]) + \
            repr(self._memobj.flags[(number)])

