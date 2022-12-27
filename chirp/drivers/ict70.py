# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

from chirp.drivers import icf
from chirp import chirp_common, directory, bitwise

MEM_FORMAT = """
struct {
  u24 freq;
  ul16 offset;
  char name[6];
  u8 unknown2:2,
     rtone:6;
  u8 unknown3:2,
     ctone:6;
  u8 unknown4:1,
     dtcs:7;
  u8 tuning_step:4,
     narrow:1,
     unknown5:1,
     duplex:2;
  u8 unknown6:1,
     power:2,
     dtcs_polarity:2,
     tmode:3;
} memory[300];

#seekto 0x12E0;
u8 used[38];

#seekto 0x1306;
u8 skips[38];

#seekto 0x132C;
u8 pskips[38];

#seekto 0x1360;
struct {
  u8 bank;
  u8 index;
} banks[300];

#seekto 0x16D0;
struct {
  char name[6];
} bank_names[26];

"""

TMODES = ["", "Tone", "TSQL", "TSQL", "DTCS", "DTCS"]
DUPLEX = ["", "-", "+"]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]
TUNING_STEPS = [5.0, 5.0, 5.0, 5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0,
                50.0, 100.0, 125.0, 200.0]
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5),
                chirp_common.PowerLevel("Low", watts=0.5),
                chirp_common.PowerLevel("Mid", watts=1.0),
                ]


class ICT70Bank(icf.IcomBank):
    """ICT70 bank"""
    def get_name(self):
        _bank = self._model._radio._memobj.bank_names[self.index]
        return str(_bank.name).rstrip()

    def set_name(self, name):
        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = name.ljust(6)[:6]


@directory.register
class ICT70Radio(icf.IcomCloneModeRadio):
    """Icom IC-T70"""
    VENDOR = "Icom"
    MODEL = "IC-T70"

    _model = "\x32\x53\x00\x01"
    _memsize = 0x19E0
    _endframe = "Icom Inc\x2eCF"

    _ranges = [(0x0000, 0x19E0, 32)]

    _num_banks = 26
    _bank_class = ICT70Bank

    def _get_bank(self, loc):
        _bank = self._memobj.banks[loc]
        if _bank.bank != 0xFF:
            return _bank.bank
        else:
            return None

    def _set_bank(self, loc, bank):
        _bank = self._memobj.banks[loc]
        if bank is None:
            _bank.bank = 0xFF
        else:
            _bank.bank = bank

    def _get_bank_index(self, loc):
        _bank = self._memobj.banks[loc]
        return _bank.index

    def _set_bank_index(self, loc, index):
        _bank = self._memobj.banks[loc]
        _bank.index = index

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 299)
        rf.valid_tmodes = TMODES
        rf.valid_duplexes = DUPLEX
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_bands = [(136000000, 174000000), (400000000, 479000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_name_length = 6
        rf.has_ctone = True
        rf.has_bank = True
        rf.has_bank_index = True
        rf.has_bank_names = True
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        bit = 1 << (number % 8)
        byte = int(number / 8)

        _mem = self._memobj.memory[number]
        _usd = self._memobj.used[byte]
        _skp = self._memobj.skips[byte]
        _psk = self._memobj.pskips[byte]

        mem = chirp_common.Memory()
        mem.number = number

        if _usd & bit:
            mem.empty = True
            return mem

        if _mem.freq & 0x800000:
            mem.freq = (_mem.freq & ~0x800000) * 6250
        else:
            mem.freq = _mem.freq * 5000
        mem.offset = _mem.offset * 5000
        mem.name = str(_mem.name).rstrip()
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.tuning_step = TUNING_STEPS[_mem.tuning_step]
        mem.mode = _mem.narrow and "NFM" or "FM"
        mem.duplex = DUPLEX[_mem.duplex]
        mem.power = POWER_LEVELS[_mem.power]
        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_polarity]
        mem.tmode = TMODES[_mem.tmode]
        mem.skip = (_psk & bit and "P") or (_skp & bit and "S") or ""

        return mem

    def set_memory(self, mem):
        bit = 1 << (mem.number % 8)
        byte = int(mem.number / 8)

        _mem = self._memobj.memory[mem.number]
        _usd = self._memobj.used[byte]
        _skp = self._memobj.skips[byte]
        _psk = self._memobj.pskips[byte]

        _mem.set_raw("\x00" * (_mem.size() // 8))

        if mem.empty:
            _usd |= bit
            return

        _usd &= ~bit

        if chirp_common.is_12_5(mem.freq):
            _mem.freq = (mem.freq // 6250) | 0x800000
        else:
            _mem.freq = mem.freq // 5000
        _mem.offset = mem.offset // 5000
        _mem.name = mem.name.ljust(6)[:6]
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
        _mem.narrow = mem.mode == "NFM"
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.dtcs_polarity = DTCS_POLARITY.index(mem.dtcs_polarity)
        _mem.tmode = TMODES.index(mem.tmode)
        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        if mem.skip == "S":
            _skp |= bit
            _psk &= ~bit
        elif mem.skip == "P":
            _skp &= ~bit
            _psk |= bit
        else:
            _skp &= ~bit
            _psk &= ~bit
