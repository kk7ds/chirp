#!/usr/bin/python
#
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

from chirp import chirp_common, yaesu_clone
from chirp import bitwise

mem_format = """
#seekto 0x2C4A;
struct {
  u8 flag;
} flag[900];

#seekto 0x328A;
struct {
  u8 unknown1;
  u8 mode:2,
     duplex:2,
     tune_step:4;
  bbcd freq[3];
  u8 unknown2:6,
     tone_mode:2;
  u8 unknown[2];
  char label[16];
  bbcd offset[3];
  u8 unknown3:2,
     tone:6;
  u8 unknown4:1,
     dcs:7;
  u8 unknown5[3];
} memory[900];

#seekto 0xFECA;
u8 checksum;
"""

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]
MODES  = ["FM", "AM", "WFM", "?"]
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.insert(2, 0.0) # There is a skipped tuning step ad index 2 (?)

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    [" ",] + \
    [chr(x) for x in range(ord("a"), ord("z")+1)] + \
    list(".,:;*#_-/&()@!?^ ") + list("?" * 100)

class VX8Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 38400
    VENDOR = "Yaesu"
    MODEL = "VX-8"

    _memsize = 65227

    _block_lengths = [ 10, 65217 ]
    _block_size = 32

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.valid_modes = ["FM", "WFM", "AM"]
        rf.memory_bounds = (1, 900)
        rf.can_odd_split = True
        rf.has_ctone = False
        return rf

    def get_raw_memory(self, number):
        return self._memobj.memory[number].get_raw()

    def _update_checksum(self):
        cs = 0
        for i in range(0x0000, 0xFECA):
            cs += ord(self._mmap[i])
        cs %= 256
        print "Checksum old=%02x new=%02x" % (self._memobj.checksum, cs)
        self._memobj.checksum = cs

    def get_memory(self, number):
        flag = self._memobj.flag[number-1].flag
        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number
        if flag != 0x03:
            mem.empty = True
            return mem
        mem.freq = int(_mem.freq) / 1000.0
        mem.offset = int(_mem.offset) / 1000.0
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tone_mode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = STEPS[_mem.tune_step]

        for i in str(_mem.label):
            if i == "\xFF":
                break
            mem.name += CHARSET[ord(i)]

        return mem

    def set_memory(self, mem):
        flag = self._memobj.flag[mem.number-1]
        if mem.empty:
            flag.flag = 0
            return
        flag.flag = 3

        _mem = self._memobj.memory[mem.number-1]

        _mem.freq = int(mem.freq * 1000)
        _mem.offset = int(mem.offset * 1000)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tone_mode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)

        label = "".join([chr(CHARSET.index(x)) for x in mem.name.rstrip()])
        _mem.label = label.ljust(16, "\xFF")

    def get_banks(self):
        return []

    def filter_name(self, name):
        return chirp_common.name16(name)
