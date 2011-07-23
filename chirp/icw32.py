#!/usr/bin/python
#
# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

mem_format = """
#seekto 0x%x;
struct {
  bbcd freq[3];
  bbcd offset[3];
  u8 rtone;
  u8 ctone;
  char name[8];
} memory[111];

#seekto 0x%x;
struct {
  u8 empty:1,
     skip:1,
     tmode:2,
     duplex:2,
     unk3:1,
     am:1;
} flag[111];

#seekto 0x0F20;
struct {
  bbcd freq[3];
  bbcd offset[3];
  u8 rtone;
  u8 ctone;
} callchans[2];

"""

DUPLEX = ["", "", "-", "+"]
TONE = ["", "", "Tone", "TSQL"]

class ICW32ARadio(icf.IcomCloneModeRadio):
    VENDOR = "Icom"
    MODEL = "IC-W32A"

    _model = "\x18\x82\x00\x01"
    _memsize = 4064
    _endframe = "Icom Inc\x2e"

    _ranges = [(0x0000, 0x0FE0, 16)]

    _limits = (0, 0)
    _mem_positions = (0, 1)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 99)
        rf.valid_bands = [self._limits]
        if int(self._limits[0] / 100) == 1:
            rf.valid_modes = ["FM", "AM"]
        else:
            rf.valid_modes = ["FM"]
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_name_length = 8

        rf.has_sub_devices = self.VARIANT == ""
        rf.has_ctone = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_mode = "AM" in rf.valid_modes
        rf.has_tuning_step = False
        rf.has_bank = False

        return rf

    def process_mmap(self):
        format = mem_format % self._mem_positions
        self._memobj = bitwise.parse(format, self._mmap)

    def get_raw_memory(self, number):
        return self._memobj.memory[number].get_raw()

    def _get_special(self):
        special = {}
        for i in range(0, 5):
            special["M%iA" % (i+1)] = 100 + i*2
            special["M%iB" % (i+1)] = 100 + i*2 + 1

        return special            

    def get_special_locations(self):
        return sorted(self._get_special().keys())

    def get_memory(self, number):
        if isinstance(number, str):
            number = self._get_special()[number]

        _mem = self._memobj.memory[number]
        _flg = self._memobj.flag[number]

        mem = chirp_common.Memory()
        mem.number = number

        if number < 100:
            # Normal memories
            mem.skip = _flg.skip and "S" or ""
        else:
            # Special memories
            mem.extd_number = util.get_dict_rev(self._get_special(), number)

        if _flg.empty:
            mem.empty = True
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = int(_mem.offset) * 100
        if str(_mem.name)[0] != chr(0xFF):
            mem.name = str(_mem.name).rstrip()
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]

        mem.mode = _flg.am and "AM" or "FM"
        mem.duplex = DUPLEX[_flg.duplex]
        mem.tmode = TONE[_flg.tmode]

        if number > 100:
            mem.immutable = ["number", "skip", "extd_number", "name"]

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flg = self._memobj.flag[mem.number]

        _flg.empty = mem.empty
        if mem.empty:
            return

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 100
        if mem.name:
            _mem.name = mem.name.ljust(8)[:8]
        else:
            _mem.name = "".join(["\xFF" * 8])
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)

        _flg.duplex = DUPLEX.index(mem.duplex)
        _flg.tmode = TONE.index(mem.tmode)
        _flg.skip = mem.skip == "S"
        _flg.am = mem.mode == "AM"

    def get_sub_devices(self):
        return [ICW32ARadioVHF(self._mmap), ICW32ARadioUHF(self._mmap)]

class ICW32ARadioVHF(ICW32ARadio):
    VARIANT = "VHF"
    _limits = (118000000, 174000000)
    _mem_positions = (0x0000, 0x0DC0)

class ICW32ARadioUHF(ICW32ARadio):
    VARIANT = "UHF"
    _limits = (400000000, 470000000)
    _mem_positions = (0x06E0, 0x0E2E)
