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

import time
from chirp import chirp_common, yaesu_clone, memmap, bitwise

ACK = "\x06"

def send(pipe, data):
    pipe.write(data)
    pipe.read(len(data))

def download(radio):
    data = ""
    for i in range(0, 10):
        chunk = radio.pipe.read(8)
        if len(chunk) == 8:
            data += chunk
            break
        elif chunk:
            raise Exception("Received invalid response from radio")
        time.sleep(1)
        print "Trying again..."

    if not data:
        raise Exception("Radio is not responding")

    send(radio.pipe, ACK)

    for i in range(0, 448):
        chunk = radio.pipe.read(64)
        data += chunk
        send(radio.pipe, ACK)
        if len(chunk) == 1 and i == 447:
            break
        elif len(chunk) != 64:
            raise Exception("Reading block %i was short (%i)" % (i, len(chunk)))
        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i * 64
            status.max = radio._memsize
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    return memmap.MemoryMap(data)

def upload(radio):
    send(radio.pipe, radio._mmap[0:8])

    ack = radio.pipe.read(1)
    if ack != ACK:
        raise Exception("Radio did not respond")

    for i in range(0, 448):
        offset = 8 + (i * 64)
        send(radio.pipe, radio._mmap[offset:offset+64])
        ack = radio.pipe.read(1)
        if ack != ACK:
            raise Exception("Radio did not ack block %i" % i)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = offset+64
            status.max = radio._memsize
            status.msg = "Cloning to radio"
            radio.status_fn(status)            

mem_format = """
#seekto 0x0238;
struct {
  u8 used:1,
     unknown1:1,
     isnarrow:1,
     isam:1,
     unknown1_1:2,
     duplex:2;
  bbcd freq[3];
  u8 unknown2:1,
     step:3, 
     unknown2_1:1,
     tmode:3;
  u8 unknown3[3];
  u8 power:2,
     tone:6;
  u8 unknown4:1,
     dtcs:7;
  u8 unknown5[2];
  u8 offset;
  u8 unknown6[3];
} memory[1000];

#seekto 0x6EC8;
struct {
  u8 skip0:2,
     skip1:2,
     skip2:2,
     skip3:2;
} flags[500];

#seekto 0x4700;
struct {
  u8 name[6];
  u8 use_name:1,
     unknown1:7;
  u8 valid:1,
     unknown2:7;
} names[1000];

#seekto 0x6FC8;
u8 checksum;
"""

DUPLEX = ["", "", "-", "+"]
TMODES = ["", "Tone", "TSQL", "TSQL-R", "DTCS"]
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.0),
                chirp_common.PowerLevel("Mid", watts=2.5),
                chirp_common.PowerLevel("Low", watts=1.0)]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
SKIPS = ["", "P", "S"]
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ [?]^__|`?$%&-()*+,-,/|;/=>?@"

class FT60Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "FT-60"
    _model = "AH017"

    _memsize = 28617

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 999)
        rf.valid_duplexes = DUPLEX
        rf.valid_tmodes = TMODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tuning_steps = STEPS
        rf.valid_skips = SKIPS
        rf.valid_characters = CHARSET
        rf.valid_name_length = 6
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_bands = [(108000000, 520000000), (700000000, 999990000)]
        rf.has_ctone = False
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        return rf

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x6FC7) ]

    def sync_in(self):
        self._mmap = download(self)
        self.process_mmap()

    def sync_out(self):
        self.update_checksums()
        upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number]) + \
            repr(self._memobj.flags[number/4]) + \
            repr(self._memobj.names[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _skp = self._memobj.flags[number/4]
        _nam = self._memobj.names[number]

        skip = _skp["skip%i" % (number%4)]

        mem = chirp_common.Memory()
        mem.number = number

        if not _mem.used:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 10000
        if mem.freq > 8000000000:
            mem.freq = (mem.freq - 8000000000) + 5000

        if mem.freq > 4000000000:
            mem.freq -= 4000000000
            for i in range(0, 3):
                mem.freq += 2500
                if chirp_common.required_step(mem.freq) == 12.5:
                    break
        
        mem.offset = int(_mem.offset) * 50000

        mem.duplex = DUPLEX[_mem.duplex]
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.power = POWER_LEVELS[_mem.power]
        mem.mode = _mem.isam and "AM" or _mem.isnarrow and "NFM" or "FM"
        mem.tuning_step = STEPS[_mem.step]
        mem.skip = SKIPS[skip]

        if _nam.use_name:
            for i in _nam.name:
                if i == 0xFF:
                    break
                try:
                    mem.name += CHARSET[i]
                except IndexError:
                    print "Memory %i: Unknown char index: %i " % (number, i)
            mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _skp = self._memobj.flags[mem.number/4]
        _nam = self._memobj.names[mem.number]

        if mem.empty:
            _mem.used = False
            return

        if not _mem.used:
            _mem.set_raw("\x00" * 16)
            _mem.used = 1
            print "Wiped"

        _mem.freq = mem.freq / 10000
        if ((mem.freq / 1000) % 10) == 5:
            _mem.freq[0].set_bits(0x80)
        if chirp_common.is_fractional_step(mem.freq):
            _mem.freq[0].set_bits(0x40)
        _mem.offset = mem.offset / 50000
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.power = mem.power and POWER_LEVELS.index(mem.power) or 0
        _mem.isnarrow = mem.mode == "NFM"
        _mem.isam = mem.mode == "AM"
        _mem.step = STEPS.index(mem.tuning_step)

        _skp["skip%i" % (mem.number%4)] = SKIPS.index(mem.skip)

        for i in range(0, 6):
            try:
                _nam.name[i] = CHARSET.index(mem.name[i])
            except IndexError:
                _nam.name[i] = CHARSET.index(" ")
            
        _nam.use_name = mem.name.strip() and True or False
            
