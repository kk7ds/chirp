# Copyright 2011 Dan Smith <dsmith@danplanet.com>
# Copyright 2012 Tom Hayward <tom@tomh.us>
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

from chirp import chirp_common, yaesu_clone, util, directory
from chirp import bitwise

mem_format = """
#seekto 0x012A;
struct {
  u8 zeros:4,
     pskip: 1,
     skip: 1,
     visible: 1,
     used: 1;
} flag[220];

#seekto 0x0269;
struct {
  u8 unknown1;
  u8 unknown2:2,
     half_deviation:1,
     unknown3:5;
  u8 unknown4:4,
     tuning_step:4;
  bbcd freq[3];
  u8 unknown5:6,
     mode:2;
  char name[8];
  bbcd offset[3];
  u8 power:2,
     tmode:2,
     unknown6:2,
     duplex:2;
  u8 unknown7:2,
     tone:6;
  u8 unknown8:1,
     dtcs:7;
  u8 unknown9;
} memory[220];
"""

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "AM", "WFM"]
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(6.25)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.append(9.0)

@directory.register
class VX5Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "VX-5"

    _model = ""
    _memsize = 8123
    _block_lengths = [10, 16, 8097]
    _block_size = 8

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x1FB9) ]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs_polarity = False
        rf.valid_modes = MODES + ["NFM"]
        rf.valid_tmodes = TMODES
        rf.valid_duplexes = DUPLEX
        rf.memory_bounds = (1, 220)
        rf.valid_bands = [(   500000,  16000000),
                          ( 48000000, 729000000),
                          (800000000, 999000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_name_length = 8
        rf.valid_characters = chirp_common.CHARSET_ASCII
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        _flg = self._memobj.flag[number-1]

        mem = chirp_common.Memory()
        mem.number = number

        if not _flg.used or not _flg.visible:
            mem.empty = True
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.duplex = DUPLEX[_mem.duplex]
        mem.name = str(_mem.name).rstrip()
        mem.mode = MODES[_mem.mode]
        if mem.mode == "FM" and _mem.half_deviation:
            mem.mode = "NFM"
        mem.tuning_step = STEPS[_mem.tuning_step]
        mem.offset = int(_mem.offset) * 1000
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]

        mem.skip = _flg.pskip and "P" or _flg.skip and "S" or ""

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        _flg = self._memobj.flag[mem.number-1]
        
        _flg.used = not mem.empty
        _flg.visible = not mem.empty
        if mem.empty:
            return

        _mem.freq = int(mem.freq / 1000)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.name = mem.name.ljust(8)
        if mem.mode == "NFM":
            _mem.mode = MODES.index("FM")
            _mem.half_deviation = 1
        else:
            _mem.mode = MODES.index(mem.mode)
            _mem.half_deviation = 0
        _mem.tuning_step = STEPS.index(mem.tuning_step)
        _mem.offset = int(mem.offset / 1000)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)

        _flg.skip = mem.skip == "S"
        _flg.pskip = mem.skip == "P"

    def filter_name(self, name):
        return chirp_common.name8(name)

    @classmethod
    def match_model(cls, filedata):
        return len(filedata) == cls._memsize
