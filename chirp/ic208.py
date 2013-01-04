# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common, icf, errors, directory
from chirp import bitwise

MEM_FORMAT = """
struct {
  u24 freq;
  u16 offset;  
  u8  power:2,
      rtone:6;
  u8  duplex:2,
      ctone:6;
  u8  unknown1:1,
      dtcs:7;
  u8  tuning_step:4,
      unknown2:4;
  u8  unknown3;
  u8  alt_mult:1,
      unknown4:1,
      is_fm:1,
      is_wide:1,
      unknown5:2,
      tmode:2;
  u16 dtcs_polarity:2,
      usealpha:1,
      empty:1,
      name1:6,
      name2:6;
  u24 name3:6,
      name4:6,
      name5:6,
      name6:6;
} memory[500];

#seekto 0x1FE0;
struct {
  u8 unknown1:1,
     empty:1,
     pskip:1,
     skip:1,
     bank:4;
} flags[500];

"""

MODES = ["AM", "FM", "NFM", "NAM"]
TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "", "-", "+"]
DTCS_POL = ["NN", "NR", "RN", "RR"]
STEPS = [5.0, 10.0, 12.5, 15, 20.0, 25.0, 30.0, 50.0, 100.0, 200.0]
POWER = [chirp_common.PowerLevel("High", watts=50),
         chirp_common.PowerLevel("Low", watts=5),
         chirp_common.PowerLevel("Mid", watts=15),
         ]

IC208_SPECIAL = {
    "C2" : 510,
    "C1" : 511,
    }
IC208_SPECIAL_REV = {
    510 : "C2",
    511 : "C1",
    }

for i in range(0, 5):
    idA = "%iA" % (i + 1)
    idB = "%iB" % (i + 1)
    num = 500 + i * 2
    IC208_SPECIAL[idA] = num
    IC208_SPECIAL[idB] = num + 1
    IC208_SPECIAL_REV[num] = idA
    IC208_SPECIAL_REV[num+1] = idB

ALPHA_CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"
NUMERIC_CHARSET = "0123456789+-=*/()|"

def get_name(_mem):
    """Decode the name from @_mem"""
    def _get_char(val):
        if val == 0:
            return " "
        elif val & 0x20:
            return ALPHA_CHARSET[val & 0x1F]
        else:
            return NUMERIC_CHARSET[val & 0x0F]

    name_bytes = [_mem.name1, _mem.name2, _mem.name3,
                  _mem.name4, _mem.name5, _mem.name6]
    name = ""
    for val in name_bytes:
        name += _get_char(val)

    return name.rstrip()

def set_name(_mem, name):
    """Encode @name in @_mem"""
    def _get_index(char):
        if char == " ":
            return 0
        elif char.isalpha():
            return ALPHA_CHARSET.index(char) | 0x20
        else:
            return NUMERIC_CHARSET.index(char) | 0x10

    name = name.ljust(6)[:6]

    _mem.usealpha = bool(name.strip())

    # The element override calling convention makes this harder to automate.
    # It's just six, so do it manually
    _mem.name1 = _get_index(name[0])
    _mem.name2 = _get_index(name[1])
    _mem.name3 = _get_index(name[2])
    _mem.name4 = _get_index(name[3])
    _mem.name5 = _get_index(name[4])
    _mem.name6 = _get_index(name[5])

@directory.register
class IC208Radio(icf.IcomCloneModeRadio):
    """Icom IC800"""
    VENDOR = "Icom"
    MODEL = "IC-208H"

    _model = "\x26\x32\x00\x01"
    _memsize = 0x2600
    _endframe = "Icom Inc\x2e30"
    _can_hispeed = True

    _memories = []

    _ranges = [(0x0000, 0x2600, 32)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 100)
        rf.has_bank = True
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_tmodes = list(TMODES)
        rf.valid_modes = list(MODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_power_levels = list(POWER)
        rf.valid_skips = ["", "S", "P"]
        rf.valid_bands = [(118000000, 173995000),
                          (230000000, 549995000),
                          (810000000, 999990000)]
        return rf

    def get_raw_memory(self, number):
        return (repr(self._memobj.memory[number - 1]) +
                repr(self._memobj.flags[number - 1]))

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)


    def _get_bank(self, loc):
        _flg = self._memobj.flags[loc-1]
        if _flg.bank >= 0x0A:
            return None
        else:
            return _flg.bank

    def _set_bank(self, loc, bank):
        _flg = self._memobj.flags[loc-1]
        if bank is None:
            _flg.bank = 0x0A
        else:
            _flg.bank = bank

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _flg = self._memobj.flags[number - 1]
        mem = chirp_common.Memory()
        mem.number = number
        if _flg.empty:
            mem.empty = True
            return mem

        mult = _mem.alt_mult and 6250 or 5000
        mem.freq = int(_mem.freq) * mult
        mem.offset = int(_mem.offset) * 5000
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCS_POL[_mem.dtcs_polarity]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.tmode = TMODES[_mem.tmode]
        mem.mode = ((not _mem.is_wide and "N" or "") +
                    (_mem.is_fm and "FM" or "AM"))
        mem.tuning_step = STEPS[_mem.tuning_step]
        mem.name = get_name(_mem)
        mem.power = POWER[_mem.power]
        mem.skip = _flg.pskip and "P" or _flg.skip and "S" or ""

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _flg = self._memobj.flags[mem.number - 1]

        if mem.empty:
            _flg.empty = True
            self._set_bank(mem.number, None)
            return

        if _flg.empty:
            _mem.set_raw("\x00" * 16)
        _flg.empty = False

        _mem.alt_mult = chirp_common.is_fractional_step(mem.freq)
        _mem.freq = mem.freq / (_mem.alt_mult and 6250 or 5000)
        _mem.offset = mem.offset / 5000
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCS_POL.index(mem.dtcs_polarity)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.is_fm = "FM" in mem.mode
        _mem.is_wide = mem.mode[0] != "N"
        _mem.tuning_step = STEPS.index(mem.tuning_step)
        set_name(_mem, mem.name)
        try:
            _mem.power = POWER.index(mem.power)
        except Exception:
            pass
        _flg.skip = mem.skip == "S"
        _flg.pskip = mem.skip == "P"

