# Copyright 2012 Dan Smith <dsmith@danplanet.com>
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
from chirp import directory, bitwise, chirp_common

MEM_FORMAT = """
struct {
  u24 freq;
  u16 offset;
  u16 rtone:6,
      ctone:6,
      unknown2:1,
      mode:3;
  u8 dtcs;
  u8 tune_step:4,
     unknown5:4;
  u8 unknown4;
  u8 tmode:4,
     duplex:2,
     dtcs_polarity:2;
  char name[16];
  u8 unknow13;
  u8 urcall[7];
  u8 rpt1call[7];
  u8 rpt2call[7];
} memory[500];

#seekto 0x69C0;
u8 used_flags[70];

#seekto 0x6A06;
u8 skip_flags[69];

#seekto 0x6A4B;
u8 pskp_flags[69];

#seekto 0x6AC0;
struct {
  u8 bank;
  u8 index;
} banks[500];

#seekto 0x6F50;
struct {
  char name[16];
} bank_names[26];

#seekto 0x74BF;
struct {
  u8 unknown0;
  u24 freq;
  u16 offset;
  u8 unknown1[3];
  u8 call[7];
  char name[16];
  char subname[8];
  u8 unknown3[9];
} repeaters[700];

#seekto 0xFABC;
struct {
  u8 call[7];
} rptcall[700];

#seekto 0x10F20;
struct {
  char call[8];
  char tag[4];
} mycall[6];

#seekto 0x10F68;
struct {
  char call[8];
} urcall[200];

"""

TMODES = ["", "Tone", "TSQL", "TSQL", "DTCS", "DTCS", "TSQL-R", "DTCS-R"]
DUPLEX = ["", "-", "+"]
DTCS_POLARITY = ["NN", "NR", "RN", "RR"]
TUNING_STEPS = [5.0, 6.25, 0, 0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0,
                100.0, 125.0, 200.0]


def _decode_call(_call):
    # Why Icom, why?
    call = ""
    shift = 1
    acc = 0
    for val in _call:
        mask = (1 << (shift)) - 1
        call += chr((val >> shift) | acc)
        acc = (val & mask) << (7 - shift)
        shift += 1
    call += chr(acc)
    return call


def _encode_call(call):
    _call = [0x00] * 7
    for i in range(0, 7):
        val = ord(call[i]) << (i + 1)
        if i > 0:
            _call[i-1] |= (val & 0xFF00) >> 8
        _call[i] = val
    _call[6] |= (ord(call[7]) & 0x7F)

    return _call


def _get_freq(_mem):
    freq = int(_mem.freq)
    offs = int(_mem.offset)

    if freq & 0x00200000:
        mult = 6250
    else:
        mult = 5000

    freq &= 0x0003FFFF

    return (freq * mult), (offs * mult)


def _set_freq(_mem, freq, offset):
    if chirp_common.is_fractional_step(freq):
        mult = 6250
        flag = 0x00200000
    else:
        mult = 5000
        flag = 0x00000000

    _mem.freq = (freq // mult) | flag
    _mem.offset = (offset // mult)


class ID31Bank(icf.IcomBank):
    """A ID-31 Bank"""
    def get_name(self):
        _banks = self._model._radio._memobj.bank_names
        return str(_banks[self.index].name).rstrip()

    def set_name(self, name):
        _banks = self._model._radio._memobj.bank_names
        _banks[self.index].name = str(name).ljust(16)[:16]


@directory.register
class ID31Radio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    """Icom ID-31"""
    MODEL = "ID-31A"

    _memsize = 0x15500
    _model = "\x33\x22\x00\x01"
    _endframe = "Icom Inc\x2E\x41\x38"
    _num_banks = 26
    _bank_class = ID31Bank
    _can_hispeed = True

    _ranges = [(0x00000, 0x15500, 32)]

    MODES = {0: "FM", 1: "NFM", 5: "DV"}

    def _get_bank(self, loc):
        _bank = self._memobj.banks[loc]
        if _bank.bank == 0xFF:
            return None
        else:
            return _bank.bank

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
        rf.memory_bounds = (0, 499)
        rf.valid_bands = [(400000000, 479000000)]
        rf.has_settings = True
        rf.has_ctone = True
        rf.has_bank_index = True
        rf.has_bank_names = True
        rf.valid_tmodes = list(TMODES)
        rf.valid_tuning_steps = sorted(list(TUNING_STEPS))
        rf.valid_modes = list(self.MODES.values())
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 16
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _usd = self._memobj.used_flags[number / 8]
        _skp = self._memobj.skip_flags[number / 8]
        _psk = self._memobj.pskp_flags[number / 8]

        bit = (1 << (number % 8))

        if self.MODES[int(_mem.mode)] == "DV":
            mem = chirp_common.DVMemory()
        else:
            mem = chirp_common.Memory()
        mem.number = number

        if _usd & bit:
            mem.empty = True
            return mem

        mem.freq, mem.offset = _get_freq(_mem)
        mem.name = str(_mem.name).rstrip()
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_polarity]
        mem.tuning_step = TUNING_STEPS[_mem.tune_step]
        mem.mode = self.MODES[int(_mem.mode)]

        if mem.mode == "DV":
            mem.dv_urcall = _decode_call(_mem.urcall).rstrip()
            mem.dv_rpt1call = _decode_call(_mem.rpt1call).rstrip()
            mem.dv_rpt2call = _decode_call(_mem.rpt2call).rstrip()

        if _psk & bit:
            mem.skip = "P"
        elif _skp & bit:
            mem.skip = "S"

        return mem

    def set_memory(self, memory):
        _mem = self._memobj.memory[memory.number]
        _usd = self._memobj.used_flags[memory.number / 8]
        _skp = self._memobj.skip_flags[memory.number / 8]
        _psk = self._memobj.pskp_flags[memory.number / 8]

        bit = (1 << (memory.number % 8))

        if memory.empty:
            _usd |= bit
            self._set_bank(memory.number, None)
            return

        _usd &= ~bit

        _set_freq(_mem, memory.freq, memory.offset)
        _mem.name = memory.name.ljust(16)[:16]
        _mem.rtone = chirp_common.TONES.index(memory.rtone)
        _mem.ctone = chirp_common.TONES.index(memory.ctone)
        _mem.tmode = TMODES.index(memory.tmode)
        _mem.duplex = DUPLEX.index(memory.duplex)
        _mem.dtcs = chirp_common.DTCS_CODES.index(memory.dtcs)
        _mem.dtcs_polarity = DTCS_POLARITY.index(memory.dtcs_polarity)
        _mem.tune_step = TUNING_STEPS.index(memory.tuning_step)
        _mem.mode = next(i for i, mode in list(self.MODES.items())
                         if mode == memory.mode)

        if isinstance(memory, chirp_common.DVMemory):
            _mem.urcall = _encode_call(memory.dv_urcall.ljust(8))
            _mem.rpt1call = _encode_call(memory.dv_rpt1call.ljust(8))
            _mem.rpt2call = _encode_call(memory.dv_rpt2call.ljust(8))
        elif memory.mode == "DV":
            raise Exception("BUG")

        if memory.skip == "S":
            _skp |= bit
            _psk &= ~bit
        elif memory.skip == "P":
            _skp |= bit
            _psk |= bit
        else:
            _skp &= ~bit
            _psk &= ~bit

    def get_urcall_list(self):
        calls = []
        for i in range(0, 200):
            call = str(self._memobj.urcall[i].call)
            if call == "CALLSIGN":
                call = ""
            calls.append(call)
        return calls

    def get_mycall_list(self):
        calls = []
        for i in range(0, 6):
            calls.append(str(self._memobj.mycall[i].call))
        return calls

    def get_repeater_call_list(self):
        calls = []
        for rptcall in self._memobj.rptcall:
            call = _decode_call(rptcall.call)
            if call.rstrip() and not call == "CALLSIGN":
                calls.append(call)
        for repeater in self._memobj.repeaters:
            call = _decode_call(repeater.call)
            if call == "CALLSIGN":
                call = ""
            calls.append(call.rstrip())
        return calls

if __name__ == "__main__":
    print(repr(_decode_call(_encode_call("KD7REX B"))))
    print(repr(_decode_call(_encode_call("       B"))))
    print(repr(_decode_call(_encode_call("        "))))
