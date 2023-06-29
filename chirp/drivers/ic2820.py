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

from chirp.drivers import icf
from chirp import chirp_common, util, directory, bitwise

MEM_FORMAT = """
struct {
  u32  freq;
  u32  offset;
  char urcall[8];
  char r1call[8];
  char r2call[8];
  u8   unknown1;
  u8   unknown2:1,
       duplex:2,
       tmode:3,
       unknown3:2;
  u16  ctone:6,
       rtone:6,
       tune_step:4;
  u16  dtcs:7,
       mode:3,
       unknown4:6;
  u8   unknown5:1,
       digital_code:7;
  u8   unknown6:2,
       dtcs_polarity:2,
       unknown7:4;
  char name[8];
} memory[522];

#seekto 0x61E0;
u8 used_flags[66];

#seekto 0x6222;
u8 skip_flags[65];
u8 pskip_flags[65];

#seekto 0x62A4;
struct {
  u8 bank;
  u8 index;
} bank_info[500];

#seekto 0x66C0;
struct {
  char name[8];
} bank_names[26];

#seekto 0x6970;
struct {
  char call[8];
  u8 unknown[4];
} mycall[6];

#seekto 0x69B8;
struct {
  char call[8];
} urcall[60];

struct {
  char call[8];
} rptcall[60];

"""

TMODES = ["", "Tone", "??0", "TSQL", "??1", "??2", "DTCS"]
DUPLEX = ["", "-", "+", "+"]  # Not sure about index 3
MODES = ["FM", "NFM", "AM", "??", "DV"]
DTCSP = ["NN", "NR", "RN", "RR"]

MEM_LOC_SIZE = 48


class IC2820Bank(icf.IcomNamedBank):
    """An IC2820 bank"""
    def get_name(self):
        _banks = self._model._radio._memobj.bank_names
        return str(_banks[self.index].name).rstrip()

    def set_name(self, name):
        _banks = self._model._radio._memobj.bank_names
        _banks[self.index].name = str(name).ljust(8)[:8]


def _get_special():
    special = {"C0": 500 + 20,
               "C1": 500 + 21}

    for i in range(0, 10):
        ida = "%iA" % i
        idb = "%iB" % i
        special[ida] = 500 + i * 2
        special[idb] = 500 + i * 2 + 1

    return special


def _resolve_memory_number(number):
    if isinstance(number, str):
        return _get_special()[number]
    else:
        return number


def _wipe_memory(mem, char):
    mem.set_raw(char * (mem.size() // 8))


@directory.register
class IC2820Radio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    """Icom IC-2820"""
    VENDOR = "Icom"
    MODEL = "IC-2820H"

    _model = "\x29\x70\x00\x01"
    _memsize = 44224
    _endframe = "Icom Inc\x2e68"

    _ranges = [(0x0000, 0x6960, 32),
               (0x6960, 0x6980, 16),
               (0x6980, 0x7160, 32),
               (0x7160, 0x7180, 16),
               (0x7180, 0xACC0, 32),
               ]

    _num_banks = 26
    _bank_class = IC2820Bank
    _can_hispeed = True

    MYCALL_LIMIT = (1, 7)
    URCALL_LIMIT = (1, 61)
    RPTCALL_LIMIT = (1, 61)

    _memories = {}

    def _get_bank(self, loc):
        _bank = self._memobj.bank_info[loc]
        if _bank.bank == 0xFF:
            return None
        else:
            return _bank.bank

    def _set_bank(self, loc, bank):
        _bank = self._memobj.bank_info[loc]
        if bank is None:
            _bank.bank = 0xFF
        else:
            _bank.bank = bank

    def _get_bank_index(self, loc):
        _bank = self._memobj.bank_info[loc]
        return _bank.index

    def _set_bank_index(self, loc, index):
        _bank = self._memobj.bank_info[loc]
        _bank.index = index

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank_index = True
        rf.has_bank_names = True
        rf.requires_call_lists = False
        rf.memory_bounds = (0, 499)
        rf.valid_modes = [x for x in MODES if '?' not in x]
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(set(DUPLEX))
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(118000000, 999990000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 8
        rf.valid_special_chans = sorted(_get_special().keys())

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        number = _resolve_memory_number(number)

        bitpos = (1 << (number % 8))
        bytepos = number / 8

        _mem = self._memobj.memory[number]
        _used = self._memobj.used_flags[bytepos]

        is_used = ((_used & bitpos) == 0)

        if is_used and MODES[_mem.mode] == "DV":
            mem = chirp_common.DVMemory()
            mem.dv_urcall = str(_mem.urcall).rstrip()
            mem.dv_rpt1call = str(_mem.r1call).rstrip()
            mem.dv_rpt2call = str(_mem.r2call).rstrip()
        else:
            mem = chirp_common.Memory()

        mem.number = number
        if number < 500:
            _skip = self._memobj.skip_flags[bytepos]
            _pskip = self._memobj.pskip_flags[bytepos]
            if _skip & bitpos:
                mem.skip = "S"
            elif _pskip & bitpos:
                mem.skip = "P"
        else:
            mem.extd_number = util.get_dict_rev(_get_special(), number)
            mem.immutable = ["number", "skip", "extd_number"]

        if not is_used:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq)
        mem.offset = int(_mem.offset)
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCSP[_mem.dtcs_polarity]
        if _mem.tune_step > 8:
            mem.tuning_step = 5.0  # Sometimes TS is garbage?
        else:
            mem.tuning_step = chirp_common.TUNING_STEPS[_mem.tune_step]
        mem.name = str(_mem.name).rstrip()

        return mem

    def set_memory(self, mem):
        bitpos = (1 << (mem.number % 8))
        bytepos = mem.number / 8

        _mem = self._memobj.memory[mem.number]
        _used = self._memobj.used_flags[bytepos]

        was_empty = _used & bitpos

        if mem.number < 500:
            skip = self._memobj.skip_flags[bytepos]
            pskip = self._memobj.pskip_flags[bytepos]
            if mem.skip == "S":
                skip |= bitpos
            else:
                skip &= ~bitpos
            if mem.skip == "P":
                pskip |= bitpos
            else:
                pskip &= ~bitpos

        if mem.empty:
            _used |= bitpos
            _wipe_memory(_mem, "\xFF")
            if mem.number < 500:
                self._set_bank(mem.number, None)
            return

        _used &= ~bitpos
        if was_empty:
            _wipe_memory(_mem, "\x00")

        _mem.freq = mem.freq
        _mem.offset = mem.offset
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCSP.index(mem.dtcs_polarity)
        _mem.tune_step = chirp_common.TUNING_STEPS.index(mem.tuning_step)
        _mem.name = mem.name.ljust(8)

        if isinstance(mem, chirp_common.DVMemory):
            _mem.urcall = mem.dv_urcall.ljust(8)
            _mem.r1call = mem.dv_rpt1call.ljust(8)
            _mem.r2call = mem.dv_rpt2call.ljust(8)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_urcall_list(self):
        _calls = self._memobj.urcall
        calls = []

        for i in range(*self.URCALL_LIMIT):
            calls.append(str(_calls[i-1].call))

        return calls

    def get_repeater_call_list(self):
        _calls = self._memobj.rptcall
        calls = []

        for i in range(*self.RPTCALL_LIMIT):
            calls.append(str(_calls[i-1].call))

        return calls

    def get_mycall_list(self):
        _calls = self._memobj.mycall
        calls = []

        for i in range(*self.MYCALL_LIMIT):
            calls.append(str(_calls[i-1].call))

        return calls

    def set_urcall_list(self, calls):
        _calls = self._memobj.urcall

        for i in range(*self.URCALL_LIMIT):
            try:
                call = calls[i-1]
            except IndexError:
                call = " " * 8

            _calls[i-1].call = call.ljust(8)[:8]

    def set_repeater_call_list(self, calls):
        _calls = self._memobj.rptcall

        for i in range(*self.RPTCALL_LIMIT):
            try:
                call = calls[i-1]
            except IndexError:
                call = " " * 8

            _calls[i-1].call = call.ljust(8)[:8]

    def set_mycall_list(self, calls):
        _calls = self._memobj.mycall

        for i in range(*self.MYCALL_LIMIT):
            try:
                call = calls[i-1]
            except IndexError:
                call = " " * 8

            _calls[i-1].call = call.ljust(8)[:8]
