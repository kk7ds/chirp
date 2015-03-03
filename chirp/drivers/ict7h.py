# Copyright 2012 Eric Allen <ericpallen@gmail.com>
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

mem_format = """
struct {
  bbcd freq[2];
  u8  lastfreq:4,
      fraction:4;
  bbcd offset[2];
  u8  unknown;
  u8  rtone;
  u8  ctone;
} memory[60];

#seekto 0x0270;
struct {
  u8 empty:1,
     tmode:2,
     duplex:2,
     unknown3:1,
     skip:1,
     unknown4:1;
} flags[60];
"""

TMODES = ["", "", "Tone", "TSQL", "TSQL"]  # last one is pocket beep
DUPLEX = ["", "", "-", "+"]
MODES = ["FM"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0]


@directory.register
class ICT7HRadio(icf.IcomCloneModeRadio):
    VENDOR = "Icom"
    MODEL = "IC-T7H"

    _model = "\x18\x10\x00\x01"
    _memsize = 0x03B0
    _endframe = "Icom Inc\x2e"

    _ranges = [(0x0000, _memsize, 16)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 60)
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(118000000, 174000000),
                          (400000000, 470000000)]
        rf.valid_skips = ["", "S"]
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_name = False
        rf.has_tuning_step = False
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _flag = self._memobj.flags[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        mem.empty = _flag.empty == 1 and True or False

        mem.freq = int(_mem.freq) * 100000
        mem.freq += _mem.lastfreq * 10000
        mem.freq += int((_mem.fraction / 2.0) * 1000)

        mem.offset = int(_mem.offset) * 10000
        mem.rtone = chirp_common.TONES[_mem.rtone - 1]
        mem.ctone = chirp_common.TONES[_mem.ctone - 1]
        mem.tmode = TMODES[_flag.tmode]
        mem.duplex = DUPLEX[_flag.duplex]
        mem.mode = "FM"
        if _flag.skip:
            mem.skip = "S"

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _flag = self._memobj.flags[mem.number - 1]

        _mem.freq = int(mem.freq / 100000)
        topfreq = int(mem.freq / 100000) * 100000
        lastfreq = int((mem.freq - topfreq) / 10000)
        _mem.lastfreq = lastfreq
        midfreq = (mem.freq - topfreq - lastfreq * 10000)
        _mem.fraction = midfreq / 500

        _mem.offset = mem.offset / 10000
        _mem.rtone = chirp_common.TONES.index(mem.rtone) + 1
        _mem.ctone = chirp_common.TONES.index(mem.ctone) + 1
        _flag.tmode = TMODES.index(mem.tmode)
        _flag.duplex = DUPLEX.index(mem.duplex)
        _flag.skip = mem.skip == "S" and 1 or 0
        _flag.empty = mem.empty and 1 or 0
