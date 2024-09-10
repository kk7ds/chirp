# Copyright 2017 SASANO Takayoshi (JG1UAA) <uaa@uaa.org.uk>
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

# memory number:
# 000 -  999	regular memory channels (supported, others not)
# 1000 - 1049	scan edges
# 1050 - 1249	auto write channels
# 1250		call channel (C0)
# 1251		call channel (C1)


MEM_FORMAT = """
struct {
  ul32 freq;
  ul32 offset;
  ul16 train_sql:2,
       tmode:3,
       duplex:2,
       train_tone:9;
  ul16 tuning_step:4,
       rtone:6,
       ctone:6;
  ul16 unknown0:6,
       mode:3,
       dtcs:7;
  u8   unknown1:6,
       dtcs_polarity:2;
  char name[6];
} memory[1251];

#seekto 0x6b1e;
struct {
  u8 bank;
  u8 index;
} banks[1050];

#seekto 0x689e;
u8 used[132];

#seekto 0x6922;
u8 skips[132];

#seekto 0x69a6;
u8 pskips[132];

#seekto 0x7352;
struct {
  char name[6];
} bank_names[18];

"""

MODES = ["FM", "WFM", "AM", "Auto"]
TMODES = ["", "Tone", "TSQL", "", "DTCS"]
DUPLEX = ["", "-", "+"]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]
TUNING_STEPS = [5.0, 6.25, 8.33, 9.0, 10.0, 12.5, 15.0, 20.0,
                25.0, 30.0, 50.0, 100.0, 200.0, 0.0]  # 0.0 as "Auto"


class ICP7Bank(icf.IcomBank):
    """ICP7 bank"""
    def get_name(self):
        _bank = self._model._radio._memobj.bank_names[self.index]
        return str(_bank.name).rstrip()

    def set_name(self, name):
        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = name.ljust(6)[:6]


@directory.register
class ICP7Radio(icf.IcomCloneModeRadio):
    """Icom IC-P7"""
    VENDOR = "Icom"
    MODEL = "IC-P7"

    _model = "\x28\x69\x00\x01"
    _memsize = 0x7500
    _endframe = "Icom Inc\x2e\x41\x38"

    _ranges = [(0x0000, 0x7500, 32)]

    _num_banks = 18
    _bank_class = ICP7Bank
    _can_hispeed = True

    def _get_bank(self, loc):
        _bank = self._memobj.banks[loc]
        if _bank.bank != 0xff:
            return _bank.bank
        else:
            return None

    def _set_bank(self, loc, bank):
        _bank = self._memobj.banks[loc]
        if bank is None:
            _bank.bank = 0xff
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
        rf.memory_bounds = (0, 999)
        rf.valid_tmodes = TMODES
        rf.valid_duplexes = DUPLEX
        rf.valid_modes = MODES
        rf.valid_bands = [(495000, 999990000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_tuning_steps = [x for x in TUNING_STEPS if x]
        rf.valid_name_length = 6
        rf.has_settings = True
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

        mem.freq = _mem.freq // 3
        mem.offset = _mem.offset // 3
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.tuning_step = TUNING_STEPS[_mem.tuning_step]
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_polarity]
        mem.name = str(_mem.name).rstrip()

        if _skp & bit:
            mem.skip = "P" if _psk & bit else "S"
        else:
            mem.skip = ""

        return mem

    def set_memory(self, mem):
        bit = 1 << (mem.number % 8)
        byte = int(mem.number / 8)

        _mem = self._memobj.memory[mem.number]
        _usd = self._memobj.used[byte]
        _skp = self._memobj.skips[byte]
        _psk = self._memobj.pskips[byte]

        if mem.empty:
            _usd |= bit

            # We use default value instead of zero-fill
            # to avoid unexpected behavior.
            _mem.freq = 15000
            _mem.offset = 479985000
            _mem.train_sql = ~0
            _mem.tmode = ~0
            _mem.duplex = ~0
            _mem.train_tone = ~0
            _mem.tuning_step = ~0
            _mem.rtone = ~0
            _mem.ctone = ~0
            _mem.unknown0 = 0
            _mem.mode = ~0
            _mem.dtcs = ~0
            _mem.unknown1 = ~0
            _mem.dtcs_polarity = ~0
            _mem.name = "      "

            _skp |= bit
            _psk |= bit

        else:
            _usd &= ~bit

            _mem.freq = mem.freq * 3
            _mem.offset = mem.offset * 3
            _mem.train_sql = 0  # Train SQL mode (0:off 1:Tone 2:MSK)
            _mem.tmode = TMODES.index(mem.tmode)
            _mem.duplex = DUPLEX.index(mem.duplex)
            _mem.train_tone = 228  # Train SQL Tone (x10 Hz)
            _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
            _mem.rtone = chirp_common.TONES.index(mem.rtone)
            _mem.ctone = chirp_common.TONES.index(mem.ctone)
            _mem.unknown0 = 0  # unknown (always zero)
            _mem.mode = MODES.index(mem.mode)
            _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
            _mem.unknown1 = ~0  # unknown (always one)
            _mem.dtcs_polarity = DTCS_POLARITY.index(mem.dtcs_polarity)
            _mem.name = mem.name.ljust(6)[:6]

            if mem.skip == "S":
                _skp |= bit
                _psk &= ~bit
            elif mem.skip == "P":
                _skp |= bit
                _psk |= bit
            else:
                _skp &= ~bit
                _psk &= ~bit
