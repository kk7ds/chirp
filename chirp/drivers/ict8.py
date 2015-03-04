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
from chirp import chirp_common, util, directory
from chirp import bitwise

mem_format = """
struct memory {
  bbcd freq[4];
  bbcd offset[2];
  u8 rtone;
  u8 ctone;
};

struct flags {
  u8 empty:1,
     skip:1,
     tmode:2,
     duplex:2,
     unknown2:2;
};

struct memory memory[100];

#seekto 0x0600;
struct flags flags[100];
"""

DUPLEX = ["", "", "-", "+"]
TMODES = ["", "", "Tone", "TSQL"]


@directory.register
class ICT8ARadio(icf.IcomCloneModeRadio):
    """Icom IC-T8A"""
    VENDOR = "Icom"
    MODEL = "IC-T8A"

    _model = "\x19\x03\x00\x01"
    _memsize = 0x07B0
    _endframe = "Icom Inc\x2e"

    _ranges = [(0x0000, 0x07B0, 16)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = TMODES
        rf.valid_duplexes = DUPLEX
        rf.valid_bands = [(50000000, 54000000),
                          (118000000, 174000000),
                          (400000000, 470000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_modes = ["FM"]
        rf.memory_bounds = (0, 99)
        rf.has_name = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False
        rf.has_mode = False
        rf.has_bank = False
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return (str(self._memobj.memory[number]) +
                str(self._memobj.duptone[number]))

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flg = self._memobj.flags[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _flg.empty:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = chirp_common.TONES[_mem.rtone - 1]
        mem.ctone = chirp_common.TONES[_mem.ctone - 1]
        mem.duplex = DUPLEX[_flg.duplex]
        mem.tmode = TMODES[_flg.tmode]
        mem.skip = _flg.skip and "S" or ""

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flg = self._memobj.flags[mem.number]

        if mem.empty:
            _flg.empty = True
            return

        _mem.set_raw("\x00" * 8)
        _flg.set_raw("\x00")

        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 1000
        _mem.rtone = chirp_common.TONES.index(mem.rtone) + 1
        _mem.ctone = chirp_common.TONES.index(mem.ctone) + 1
        _flg.duplex = DUPLEX.index(mem.duplex)
        _flg.tmode = TMODES.index(mem.tmode)
        _flg.skip = mem.skip == "S"
