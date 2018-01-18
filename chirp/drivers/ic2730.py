# Copyright 2018 Rhett Robinson <rrhett@gmail.com>
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
from chirp import chirp_common, util, directory, bitwise, memmap


# Still missing:
# - scan edges
# - priority watch
# - hope channel beep
# - DTMF memory
# - weather channel alert
MEM_FORMAT = """
struct {
  u24  freq;
  u16  offset;
  u8   tune_step:4,
       unknown5:3,
       mode:1;
  u8   unknown6:2,
       rtone:6;
  u8   unknown7:2,
       ctone:6;
  u8   unknown8;
  u8   dtcs;
  u8   tmode:4,
       duplex:2,
       dtcs_polarity:2;
  char name[6];
} memory[1002];

#seekto 0x42c0;
u8 used_flags[125];

#seekto 0x433e;
u8 skip_flags[125];
u8 pskip_flags[125];

#seekto 0x4440;
struct {
  u8 bank;
  u8 index;
} bank_info[1000];

#seekto 0x4c50;
struct {
  char name[6];
} bank_names[10];

#seekto 0x5004;
u8   unknown12:4,
     autorptr:2,
     unknown13:2;

#seekto 0x5030;
u8   unknown14:6,
     backlight:2;

#seekto 0x5056;
u8   unknown15:6,
     power:2;

#seekto 0x5220;
u16  left_memory;
u16  right_memory;

#seekto 0x5280;
u16  mem_writes_count;
"""

# Guessing some of these intermediate values are with the Pocket Beep function,
# but I haven't reliably reproduced these.
TMODES = ["", "Tone", "??0", "TSQL", "??1", "DTCS", "TSQL-R", "DTCS-R",
       "DTC.OFF", "TON.DTC", "DTC.TSQ", "TON.TSQ"]
DUPLEX = ["", "-", "+"]
MODES = ["FM", "NFM"]
DTCSP = ["NN", "NR", "RN", "RR"]

AUTOREPEATER = ["OFF", "DUP", "DUP.TON"]


class IC2730Bank(icf.IcomNamedBank):
    """An IC2730 bank"""
    def get_name(self):
        _banks = self._model._radio._memobj.bank_names
        return str(_banks[self.index].name).rstrip()

    def set_name(self, name):
        _banks = self._model._radio._memobj.bank_names
        _banks[self.index].name = str(name).ljust(6)[:6]


def _get_special():
    special = {"C0": 1000,
               "C1": 1001}
    return special


def _resolve_memory_number(number):
    if isinstance(number, str):
        return _get_special()[number]
    else:
        return number


def _wipe_memory(mem, char):
    mem.set_raw(char * (mem.size() / 8))


@directory.register
class IC2730Radio(icf.IcomRawCloneModeRadio):
    """Icom IC-2730A"""
    VENDOR = "Icom"
    MODEL = "IC-2730A"

    _model = "\x35\x98\x00\x01"
    _memsize = 21312 # 0x5340
    _endframe = "Icom Inc\x2e4E"

    _ranges = [(0x0000, 0x5300, 64),
               (0x5300, 0x5310, 16),
               (0x5310, 0x5340, 48),
               ]

    _num_banks = 10
    _bank_class = IC2730Bank
    _can_hispeed = True

    def _get_bank(self, loc):
        _bank = self._memobj.bank_info[loc]
        if _bank.bank == 0x1F:
            return None
        else:
            return _bank.bank

    def _set_bank(self, loc, bank):
        _bank = self._memobj.bank_info[loc]
        if bank is None:
            _bank.bank = 0x1F
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
        rf.memory_bounds = (0, 999)
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(set(DUPLEX))
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS[0:9])
        rf.valid_bands = [(118000000, 174000000),
                          (375000000, 550000000),
                          ]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 6
        rf.valid_special_chans = sorted(_get_special().keys())

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        bitpos = (1 << (number % 8))
        bytepos = number / 8

        _mem = self._memobj.memory[number]
        _used = self._memobj.used_flags[bytepos]

        is_used = ((_used & bitpos) == 0)

        mem = chirp_common.Memory()

        mem.number = number

        _skip = self._memobj.skip_flags[bytepos]
        _pskip = self._memobj.pskip_flags[bytepos]
        if _skip & bitpos:
            mem.skip = "S"
        elif _pskip & bitpos:
            mem.skip = "P"

        if not is_used:
            mem.empty = True
            return mem

        # Frequencies are stored as kHz/5
        mem.freq = int(_mem.freq) * 5000
        mem.offset = int(_mem.offset) * 5000
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
            self._set_bank(mem.number, None)
            return

        _used &= ~bitpos
        if was_empty:
            _wipe_memory(_mem, "\x00")

        _mem.freq = mem.freq / 5000
        _mem.offset = mem.offset / 5000
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCSP.index(mem.dtcs_polarity)
        _mem.tune_step = chirp_common.TUNING_STEPS.index(mem.tuning_step)
        _mem.name = mem.name.ljust(6)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])
