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

from chirp.drivers import icf
from chirp import chirp_common, errors, directory, bitwise

MEM_FORMAT = """
#seekto 0x0020;
struct {
  u24 freq;
  u16 offset;
  u8  power:2,
      rtone:6;
  u8  duplex:2,
      ctone:6;
  u8  dtcs;
  u8  tuning_step:4,
      unknown1:4;
  u8  unknown2;
  u8  mult_flag:1,
      unknown3:5,
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
  u8 unknown5;
  u8 unknown6:1,
     digital_code:7;
  u8 urcall;
  u8 rpt1call;
  u8 rpt2call;
  u8 unknown7:1,
     mode:3,
     unknown8:4;
} memory[512];

#seekto 0x2BF4;
struct {
  u8 unknown1:1,
     empty:1,
     pskip:1,
     skip:1,
     bank:4;
} flags[512];

#seekto 0x3220;
struct {
  char call[8];
} mycalls[8];

#seekto 0x3250;
struct {
  char call[8];
} urcalls[99];

#seekto 0x3570;
struct {
  char call[8];
} rptcalls[59];
"""

MODES = ["FM", "NFM", "AM", "NAM", "DV", "FM", "FM", "FM"]
TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "", "-", "+"]
DTCS_POL = ["NN", "NR", "RN", "RR"]
STEPS = [5.0, 10.0, 12.5, 15, 20.0, 25.0, 30.0, 50.0, 100.0, 200.0, 6.25]
POWER_LEVELS = [chirp_common.PowerLevel('High', watts=50),
                chirp_common.PowerLevel('Low', watts=5),
                chirp_common.PowerLevel('Mid', watts=15)]

ID800_SPECIAL = {
    "C2": 510,
    "C1": 511,
    }
ID800_SPECIAL_REV = {
    510: "C2",
    511: "C1",
    }

for i in range(0, 5):
    idA = "%iA" % (i + 1)
    idB = "%iB" % (i + 1)
    num = 500 + i * 2
    ID800_SPECIAL[idA] = num
    ID800_SPECIAL[idB] = num + 1
    ID800_SPECIAL_REV[num] = idA
    ID800_SPECIAL_REV[num+1] = idB

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
class ID800v2Radio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    """Icom ID800"""
    VENDOR = "Icom"
    MODEL = "ID-800H"
    VARIANT = "v2"

    _model = "\x27\x88\x02\x00"
    _memsize = 14528
    _endframe = "Icom Inc\x2eCB"
    _can_hispeed = True

    _memories = []

    _ranges = [(0x0020, 0x2B18, 32),
               (0x2B18, 0x2B20,  8),
               (0x2B20, 0x2BE0, 32),
               (0x2BE0, 0x2BF4, 20),
               (0x2BF4, 0x2C00, 12),
               (0x2C00, 0x2DE0, 32),
               (0x2DE0, 0x2DF4, 20),
               (0x2DF4, 0x2E00, 12),
               (0x2E00, 0x2E20, 32),

               (0x2F00, 0x3070, 32),

               (0x30D0, 0x30E0, 16),
               (0x30E0, 0x3160, 32),
               (0x3160, 0x3180, 16),
               (0x3180, 0x31A0, 32),
               (0x31A0, 0x31B0, 16),

               (0x3220, 0x3240, 32),
               (0x3240, 0x3260, 16),
               (0x3260, 0x3560, 32),
               (0x3560, 0x3580, 16),
               (0x3580, 0x3720, 32),
               (0x3720, 0x3780,  8),

               (0x3798, 0x37A0,  8),
               (0x37A0, 0x37B0, 16),
               (0x37B0, 0x37B1,  1),

               (0x37D8, 0x37E0,  8),
               (0x37E0, 0x3898, 32),
               (0x3898, 0x389A,  2),

               (0x38A8, 0x38C0, 16), ]

    MYCALL_LIMIT = (1, 7)
    URCALL_LIMIT = (1, 99)
    RPTCALL_LIMIT = (1, 59)

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

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_implicit_calls = True
        rf.has_settings = True
        rf.has_bank = True
        rf.valid_modes = [x for x in MODES if x]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(118000000, 173995000), (230000000, 549995000),
                          (810000000, 999990000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_name_length = 6
        rf.valid_special_chans = sorted(ID800_SPECIAL.keys())
        rf.valid_power_levels = list(POWER_LEVELS)
        rf.memory_bounds = (1, 499)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        if isinstance(number, str):
            try:
                number = ID800_SPECIAL[number] + 1  # Because we subtract below
            except KeyError:
                raise errors.InvalidMemoryLocation("Unknown channel %s" %
                                                   number)

        _mem = self._memobj.memory[number-1]
        _flg = self._memobj.flags[number-1]

        if MODES[_mem.mode] == "DV":
            urcalls = self.get_urcall_list()
            rptcalls = self.get_repeater_call_list()
            mem = chirp_common.DVMemory()
            mem.dv_urcall = urcalls[_mem.urcall]
            mem.dv_rpt1call = rptcalls[_mem.rpt1call]
            mem.dv_rpt2call = rptcalls[_mem.rpt2call]
            mem.dv_code = _mem.digital_code
        else:
            mem = chirp_common.Memory()

        mem.number = number
        if _flg.empty:
            mem.empty = True
            return mem

        mult = _mem.mult_flag and 6250 or 5000
        mem.freq = _mem.freq * mult
        mem.offset = _mem.offset * 5000
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = MODES[_mem.mode]
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCS_POL[_mem.dtcs_polarity]
        mem.tuning_step = STEPS[_mem.tuning_step]
        mem.name = get_name(_mem)
        mem.power = POWER_LEVELS[_mem.power]

        mem.skip = _flg.pskip and "P" or _flg.skip and "S" or ""

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        _flg = self._memobj.flags[mem.number-1]

        _flg.empty = mem.empty
        if mem.empty:
            self._set_bank(mem.number, None)
            return

        mult = chirp_common.is_fractional_step(mem.freq) and 6250 or 5000
        _mem.mult_flag = mult == 6250
        _mem.freq = mem.freq / mult
        _mem.offset = mem.offset / 5000
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCS_POL.index(mem.dtcs_polarity)
        _mem.tuning_step = STEPS.index(mem.tuning_step)
        if mem.power in POWER_LEVELS:
            _mem.power = POWER_LEVELS.index(mem.power)
        set_name(_mem, mem.name)

        _flg.pskip = mem.skip == "P"
        _flg.skip = mem.skip == "S"

        if mem.mode == "DV":
            urcalls = self.get_urcall_list()
            rptcalls = self.get_repeater_call_list()
            if not isinstance(mem, chirp_common.DVMemory):
                raise errors.InvalidDataError("DV mode is not a DVMemory!")
            try:
                err = mem.dv_urcall
                _mem.urcall = urcalls.index(mem.dv_urcall)
                err = mem.dv_rpt1call
                _mem.rpt1call = rptcalls.index(mem.dv_rpt1call)
                err = mem.dv_rpt2call
                _mem.rpt2call = rptcalls.index(mem.dv_rpt2call)
            except IndexError:
                raise errors.InvalidDataError("DV Call %s not in list" % err)
        else:
            _mem.urcall = 0
            _mem.rpt1call = 0
            _mem.rpt2call = 0

    def sync_in(self):
        icf.IcomCloneModeRadio.sync_in(self)
        self.process_mmap()

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def get_urcall_list(self):
        calls = ["CQCQCQ"]

        for i in range(*self.URCALL_LIMIT):
            calls.append(str(self._memobj.urcalls[i-1].call).rstrip())

        return calls

    def get_repeater_call_list(self):
        calls = ["*NOTUSE*"]

        for i in range(*self.RPTCALL_LIMIT):
            calls.append(str(self._memobj.rptcalls[i-1].call).rstrip())

        return calls

    def get_mycall_list(self):
        calls = []

        for i in range(*self.MYCALL_LIMIT):
            calls.append(str(self._memobj.mycalls[i-1].call).rstrip())

        return calls

    def set_urcall_list(self, calls):
        for i in range(*self.URCALL_LIMIT):
            try:
                call = calls[i].upper()  # Skip the implicit CQCQCQ
            except IndexError:
                call = " " * 8

            self._memobj.urcalls[i-1].call = call.ljust(8)[:8]

    def set_repeater_call_list(self, calls):
        for i in range(*self.RPTCALL_LIMIT):
            try:
                call = calls[i].upper()  # Skip the implicit blank
            except IndexError:
                call = " " * 8

            self._memobj.rptcalls[i-1].call = call.ljust(8)[:8]

    def set_mycall_list(self, calls):
        for i in range(*self.MYCALL_LIMIT):
            try:
                call = calls[i-1].upper()
            except IndexError:
                call = " " * 8

            self._memobj.mycalls[i-1].call = call.ljust(8)[:8]
