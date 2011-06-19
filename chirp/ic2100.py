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

from chirp import chirp_common, icf, util
from chirp import bitwise, memmap

mem_format = """
struct {
  bbcd  freq[2];
  u8    freq_10khz:4,
        freq_1khz:3,
        zero:1;
  u8    unknown1;
  bbcd  offset[2];
  u8    is_12_5:1,
        unknownbits:3,
        duplex:2,
        tmode:2;
  u8    ctone;
  u8    rtone;
  char  name[6];
  u8    unknown3;
} memory[100];

#seekto 0x0640;
struct {
  bbcd  freq[3];
  u8    unknown1;
  bbcd  offset[2];
  u8    unknownbits:4,
        duplex:2,
        tmode:2;
  u8    ctone;
  u8    rtone;
} special[7];

#seekto 0x0680;
struct {
  bbcd  freq[3];
  u8    unknown1;
  bbcd  offset[2];
  u8    unknownbits:4,
        duplex:2,
        tmode:2;
  u8    ctone;
  u8    rtone;
} call[2];

#seekto 0x06F0;
struct {
  u8 flagbits;
} skipflags[14];

#seekto 0x0700;
struct {
  u8 flagbits;
} usedflags[14];

"""

TMODES = ["", "Tone", "", "TSQL"]
DUPLEX = ["", "", "+", "-"]
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(6.25)

class IC2100Radio(icf.IcomCloneModeRadio):
    VENDOR = "Icom"
    MODEL = "IC-2100H"

    _model = "\x20\x88\x00\x01"
    _memsize = 2016
    _endframe = "Icom Inc\x2e"

    _ranges = [(0x0000, 0x07E0, 32)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 100)
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_mode = False
        rf.valid_modes = ["FM"]
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(118000000, 174000000)]
        rf.valid_skips = ["", "S"]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def _get_special(self):
        special = { "C": 506 }
        for i in range(0, 3):
            idA = "%iA" % (i+1)
            idB = "%iB" % (i+1)
            num = 500 + (i * 2)
            special[idA] = num
            special[idB] = num + 1

        return special

    def get_special_locations(self):
        return sorted(self._get_special().keys())

    def __get_freq(self, mem):
        freq = (int(mem.freq) * 100000) + \
            (mem.freq_10khz * 10000) + \
            (mem.freq_1khz * 1000)

        if mem.is_12_5:
            if chirp_common.is_12_5(freq):
                pass
            elif mem.freq_1khz == 2:
                freq += 500
            elif mem.freq_1khz == 5:
                freq += 2500
            elif mem.freq_1khz == 7:
                freq += 500
            else:
                raise Exception("Unable to resolve 12.5kHz: %i" % freq)

        return freq

    def __set_freq(self, mem, freq):
        mem.freq = freq / 100000
        mem.freq_10khz = (freq / 10000) % 10
        khz = (freq / 1000) % 10
        mem.freq_1khz = khz
        mem.is_12_5 = chirp_common.is_12_5(freq)

    def __get_offset(self, mem):
        raw = memmap.MemoryMap(mem.get_raw())
        if ord(raw[5]) & 0x0A:
            raw[5] = ord(raw[5]) & 0xF0
            mem.set_raw(raw.get_packed())
            offset = int(mem.offset) * 1000 + 5000
            raw[5] = ord(raw[5]) | 0x0A
            mem.set_raw(raw.get_packed())
            return offset
        else:
            return int(mem.offset) * 1000

    def __set_offset(self, mem, offset):
        if (offset % 10) == 5000:
            extra = 0x0A
            offset -= 5000
        else:
            extra = 0x00

        mem.offset = offset / 1000
        raw = memmap.MemoryMap(mem.get_raw())
        raw[5] = ord(raw[5]) | extra
        mem.set_raw(raw.get_packed())

    def get_memory(self, number):
        mem = chirp_common.Memory()

        if isinstance(number, str):
            if number == "C":
                number = self._get_special()[number]
                _mem = self._memobj.call[0]
            else:
                number = self._get_special()[number]
                _mem = self._memobj.special[number - 500]
            empty = False
        else:
            number -= 1
            _mem = self._memobj.memory[number]
            _emt = self._memobj.usedflags[number / 8].flagbits
            empty = (1 << (number % 8)) & int(_emt)
            if not empty:
                mem.name = str(_mem.name).rstrip()
            _skp = self._memobj.skipflags[number / 8].flagbits
            isskip = (1 << (number % 8)) & int(_skp)

        mem.number = number + 1

        if number <= 100:
            mem.skip = isskip and "S" or ""
        else:
            mem.extd_number = util.get_dict_rev(self._get_special(), number)
            mem.immutable = ["number", "skip", "extd_number"]

        if empty:
            mem.empty = True
            return mem

        mem.freq = self.__get_freq(_mem)
        mem.offset = self.__get_offset(_mem)
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        
        return mem

    def _wipe_memory(self, mem, char):
        mem.set_raw(char * (mem.size() / 8))

    def set_memory(self, mem):
        if mem.number == "C":
            _mem = self._memobj.call[0]
        elif isinstance(mem.number, str):
            _mem = self._memobj.special[self._get_special[number] - 500]
        else:
            number = mem.number - 1
            _mem = self._memobj.memory[number]
            _emt = self._memobj.usedflags[number / 8].flagbits
            mask = 1 << (number % 8)
            if mem.empty:
                _emt |= mask
            else:
                _emt &= ~mask
            _skp = self._memobj.skipflags[number / 8].flagbits
            if mem.skip == "S":
                _skp |= mask
            else:
                _skp &= ~mask
            _mem.name = mem.name.ljust(6)

        self.__set_freq(_mem, mem.freq)
        self.__set_offset(_mem, mem.offset)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)

    def get_raw_memory(self, number):
        return self._memobj.memory[number].get_raw()
