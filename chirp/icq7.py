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

from chirp import chirp_common, icf, errors, util
from chirp import bitwise
from chirp.memmap import MemoryMap
from chirp.chirp_common import to_GHz, from_GHz

mem_format = """
struct {
  bbcd freq[3];
  u8  fractional:1,
      unknown:7;
  bbcd offset[2];
  u16 ctone:6
      rtone:6,
      tune_step:4;
} memory[200];

#seekto 0x0690;
struct {
  u8 tmode:2,
     duplex:2,
     skip:1,
     pskip:1,
     mode:2;
} flags[200];

#seekto 0x0690;
u8 flags_whole[200];
"""

TMODES = ["", "", "Tone", "TSQL", "TSQL"] # last one is pocket beep
DUPLEX = ["", "", "-", "+"]
MODES  = ["FM", "WFM", "AM"]
STEPS  = list(chirp_common.TUNING_STEPS) + [100.0]

class ICQ7Radio(icf.IcomCloneModeRadio):
    VENDOR = "Icom"
    MODEL = "IC-Q7A"

    _model = "\x19\x95\x00\x01"
    _memsize = 0x7C0
    _endframe = "Icom Inc\x2e"

    _ranges = [(0x0000, 0x07C0, 16)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 199)
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [( 30000000,  823995000),
                          (849000000,  868995000),
                          (894000000, 1309995000)]
        rf.valid_skips = ["", "S", "P"]
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_name = False
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]

        mem = chirp_common.Memory()
        mem.number = number
        if self._memobj.flags_whole[number] == 0xFF:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 1000
        if _mem.fractional:
            mem.freq = chirp_common.fix_rounded_step(mem.freq)
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        try:
            mem.tuning_step = STEPS[_mem.tune_step]
        except IndexError:
            print "Invalid tune step index %i" % _mem.tune_step
        mem.tmode = TMODES[_flag.tmode]
        mem.duplex = DUPLEX[_flag.duplex]
        mem.mode = MODES[_flag.mode]
        if _flag.pskip:
            mem.skip = "P"
        elif _flag.skip:
            mem.skip = "S"

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flag = self._memobj.flags[mem.number]
        
        if mem.empty:
            self._memobj.flags_whole[mem.number] = 0xFF
            return

        if mem.freq > to_GHz(1):
            _mem.freq = (mem.freq / 1000) - to_GHz(1)
            upper = from_GHz(mem.freq) << 4
            _mem.freq[0].clr_bits(0xF0)
            _mem.freq[0].set_bits(upper)
        else:
            _mem.freq = mem.freq / 1000
        _mem.fractional = chirp_common.is_fractional_step(mem.freq)
        _mem.offset = mem.offset / 1000
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        _flag.tmode = TMODES.index(mem.tmode)
        _flag.duplex = DUPLEX.index(mem.duplex)
        _flag.mode = MODES.index(mem.mode)
        _flag.skip = mem.skip == "S" and 1 or 0
        _flag.pskip = mem.skip == "P" and 1 or 0
