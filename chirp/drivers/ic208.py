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

from chirp.drivers import icf
from chirp import chirp_common, directory, bitwise

MEM_FORMAT = """
struct memory {
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
};

struct memory memory[510];

struct {
  u8 unknown1:1,
     empty:1,
     pskip:1,
     skip:1,
     bank:4;
} flags[512];

struct memory call[2];

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

IC208_SPECIAL = []
for i in range(1, 6):
    IC208_SPECIAL.append("%iA" % i)
    IC208_SPECIAL.append("%iB" % i)

CHARSET = dict(list(zip([0x00, 0x08, 0x09, 0x0a, 0x0b, 0x0d, 0x0f],
                        " ()*+-/")) +
               list(zip(list(range(0x10, 0x1a)), "0123456789")) +
               [(0x1c, '|'), (0x1d, '=')] +
               list(zip(list(range(0x21, 0x3b)),
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ")))
CHARSET_REV = dict(list(zip(list(CHARSET.values()), list(CHARSET.keys()))))


def get_name(_mem):
    """Decode the name from @_mem"""
    def _get_char(val):
        try:
            return CHARSET[int(val)]
        except KeyError:
            return "*"

    name_bytes = [_mem.name1, _mem.name2, _mem.name3,
                  _mem.name4, _mem.name5, _mem.name6]
    name = ""
    for val in name_bytes:
        name += _get_char(val)

    return name.rstrip()


def set_name(_mem, name):
    """Encode @name in @_mem"""
    def _get_index(char):
        try:
            return CHARSET_REV[char]
        except KeyError:
            return CHARSET_REV["*"]

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
        rf.memory_bounds = (1, 500)
        rf.has_bank = True
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_tmodes = list(TMODES)
        rf.valid_modes = list(MODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_power_levels = list(POWER)
        rf.valid_skips = ["", "S", "P"]
        rf.valid_bands = [(118000000, 174000000),
                          (230000000, 550000000),
                          (810000000, 999995000)]
        rf.valid_special_chans = ["C1", "C2"] + sorted(IC208_SPECIAL)
        rf.valid_characters = "".join(list(CHARSET.values()))
        return rf

    def get_raw_memory(self, number):
        _mem, _flg, index = self._get_memory(number)
        return repr(_mem) + repr(_flg)

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

    def _get_memory(self, number):
        if isinstance(number, str):
            if "A" in number or "B" in number:
                index = 501 + IC208_SPECIAL.index(number)
                _mem = self._memobj.memory[index - 1]
                _flg = self._memobj.flags[index - 1]
            else:
                index = int(number[1]) - 1
                _mem = self._memobj.call[index]
                _flg = self._memobj.flags[510 + index]
                index = index + -10
        elif number <= 0:
            index = 10 - abs(number)
            _mem = self._memobj.call[index]
            _flg = self._memobj.flags[index + 510]
        else:
            index = number
            _mem = self._memobj.memory[number - 1]
            _flg = self._memobj.flags[number - 1]

        return _mem, _flg, index

    def get_memory(self, number):
        _mem, _flg, index = self._get_memory(number)

        mem = chirp_common.Memory()
        mem.number = index
        if isinstance(number, str):
            mem.extd_number = number
        else:
            mem.skip = _flg.pskip and "P" or _flg.skip and "S" or ""

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

        return mem

    def set_memory(self, mem):
        _mem, _flg, index = self._get_memory(mem.number)

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
        if not isinstance(mem.number, str):
            _flg.skip = mem.skip == "S"
            _flg.pskip = mem.skip == "P"
