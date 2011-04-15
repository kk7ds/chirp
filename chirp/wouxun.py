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

import struct
import time
from chirp import util, chirp_common, bitwise, memmap

mem_format = """
#seekto 0x0008;
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  ul16 rx_tone;
  ul16 tx_tone;
  u8 _3_unknown;
  u8 _2_unknown_1:1,
     skip:1,
     power_high:1,
     iswide:1,
     _2_unknown_3:4;
  u8 unknown[2];
} memory[128];

#seekto 0x1000;
struct {
  u8 unknown[8];
  u8 name[6];
  u8 pad[2];
} names[128];
"""

def identify(radio):
    for i in range(0, 5):
        radio.pipe.write("HiWOUXUN\x02")
        r = radio.pipe.read(9)
        if len(r) != 9:
            print "Retrying identification..."
            time.sleep(1)
            continue
        if r[2:8] != radio._model:
            raise Exception("I can't talk to this model")
        return
    if len(r) == 0:
        raise Exception("Radio not responding")
    else:
        raise Exception("Unable to identify radio")

def start_transfer(radio):
    radio.pipe.write("\x02\x06")
    time.sleep(0.05)
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise Exception("Radio refused transfer mode")    

def download(radio):
    identify(radio)
    start_transfer(radio)

    image = "\x01\x00\x00\x00\x00\x10\x00\x00"

    BLOCK_SIZE = 0x40
    #UPPER = 0xE79B
    UPPER = 0x2000
    for i in range(0x10, UPPER, BLOCK_SIZE):
        cmd = struct.pack(">cHb", "R", i, BLOCK_SIZE)
        radio.pipe.write(cmd)
        length = len(cmd) + BLOCK_SIZE
        r = radio.pipe.read(length)
        if len(r) != (len(cmd) + BLOCK_SIZE):
            raise Exception("Failed to read full block")
        
        radio.pipe.write("\x06")
        radio.pipe.read(1)
        image += r[4:]

        if radio.status_fn:
            s = chirp_common.Status()           
            s.cur = i
            s.max = UPPER
            s.msg = "Cloning from radio"
            radio.status_fn(s)
    
    return memmap.MemoryMap(image)

def upload(radio):
    identify(radio)
    start_transfer(radio)

    BLOCK_SIZE = 0x10
    UPPER = 0x2000
    ptr = 8
    for i in range(0, UPPER, BLOCK_SIZE):
        cmd = struct.pack(">cHb", "W", i+0x10, BLOCK_SIZE)
        chunk = radio._mmap[ptr:ptr+BLOCK_SIZE]
        ptr += BLOCK_SIZE
        radio.pipe.write(cmd + chunk)
        #print util.hexprint(cmd)
        #print util.hexprint(chunk)

        ack = radio.pipe.read(1)
        if not ack == "\x06":
            raise Exception("Radio did not ack block %i" % ptr)
        #radio.pipe.write(ack)

        if radio.status_fn:
            s = chirp_common.Status()
            s.cur = i
            s.max = UPPER
            s.msg = "Cloning to radio"
            radio.status_fn(s)

CHARSET = list("0123456789") + [chr(x + ord("A")) for x in range(0, 26)] + \
    list("?" * 128)

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                chirp_common.PowerLevel("Low", watts=1.00)]

class KGUVD1PRadio(chirp_common.CloneModeRadio):
    VENDOR = "Wouxun"
    MODEL = "KG-UVD1P"
    _model = "KG669V"

    def sync_in(self):
        self._mmap = download(self)
        self.process_mmap()

    def sync_out(self):
        upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LEVELS
        rf.has_ctone = False
        rf.has_tuning_step = False
        rf.memory_bounds = (1, 128)
        return rf

    def get_raw_memory(self, number):
        return self._memobj.memory[number - 1].get_raw()

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw() == ("\xff" * 16):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) / 100000.0
        mem.offset = (int(_mem.tx_freq) / 100000.0) - mem.freq
        if mem.offset < 0:
            mem.duplex = "-"
        elif mem.offset:
            mem.duplex = "+"
        mem.offset = abs(mem.offset)
        if not _mem.skip:
            mem.skip = "S"
        if not _mem.iswide:
            mem.mode = "NFM"
            
        if _mem.tx_tone == 0xFFFF:
            pass # No tone
        elif _mem.tx_tone > 0x2800:
            mem.dtcs = int("%03o" % (_mem.tx_tone - 0x2800))
            mem.tmode = "DTCS"
        else:
            mem.rtone = _mem.tx_tone / 10.0
            mem.tmode = _mem.tx_tone == _mem.rx_tone and "TSQL" or "Tone"

        mem.power = POWER_LEVELS[not _mem.power_high]

        for i in _nam.name:
            if i == 0xFF:
                break
            mem.name += CHARSET[i]

        return mem

    def wipe_memory(self, _mem, byte):
        _mem.set_raw(byte * (_mem.size() / 8))

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            self.wipe_memory(_mem, "\x00")
            return

        if _mem.get_raw() == ("\xFF" * 16):
            self.wipe_memory(_mem, "\x00")

        _mem.rx_freq = int(mem.freq * 100000)
        if mem.duplex == "+":
            _mem.tx_freq = int(mem.freq * 100000) + int(mem.offset * 100000)
        elif mem.duplex == "-":
            _mem.tx_freq = int(mem.freq * 100000) - int(mem.offset * 100000)
        else:
            _mem.tx_freq = int(mem.freq * 100000)
        _mem.skip = mem.skip != "S"
        _mem.iswide = mem.mode != "NFM"

        if mem.tmode == "DTCS":
            _mem.tx_tone = int("%i" % mem.dtcs, 8) + 0x2800
            _mem.rx_tone = _mem.tx_tone
        elif mem.tmode:
            _mem.tx_tone = int(mem.rtone * 10)
            _mem.rx_tone = mem.tmode == "TSQL" and _mem.tx_tone or 0xFFFF
        else:
            _mem.rx_tone = 0xFFFF
            _mem.tx_tone = 0xFFFF

        _mem.power_high = not POWER_LEVELS.index(mem.power)

        _nam.name = [0xFF] * 6
        for i in range(0, len(mem.name)):
            try:
                _nam.name[i] = CHARSET.index(mem.name[i])
            except IndexError:
                raise Exception("Character `%s' not supported")

    @classmethod
    def match_model(cls, filedata):
        return filedata[0:4] == "\x01\x00\x00\x00"

    def filter_name(self, name):
        newname = ""
        for i in name.upper():
            if len(newname) == 6:
                break
            elif i in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                newname += i
        return newname
