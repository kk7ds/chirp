# Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
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

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise

mem_format = """
#seekto 0x0008;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown1[2];
  u8 unknown2:7,
     lowpower:1;
  u8 unknown3:1,
     wide:1,
     unknown4:3,
     scan:1,
     unknown5:2;
} memory[128];

#seekto 0x1000;
struct {
  u8 unknown1[8];
  char name[6];
  u8 unknown2[2];
} names[128];
"""

def do_status(radio, block):
    s = chirp_common.Status()
    s.msg = "Cloning"
    s.cur = block
    s.max = radio._memsize
    radio.status_fn(s)

def do_ident(radio):
    serial = radio.pipe

    serial.write("\x50\xBB\xFF\x01\x25\x98\x4D")
    ack = serial.read(1)
    
    if ack != "\x06":
        print repr(ack)
        raise errors.RadioError("Radio did not respond")

    serial.write("\x02")
    ident = serial.read(8)

    print "Ident:\n%s" % util.hexprint(ident)

    serial.write("\x06")
    ack = serial.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio refused clone")

    return ident

def do_download(radio):
    serial = radio.pipe

    data = do_ident(radio)

    for i in range(0, radio._memsize - 0x08, 0x40):
        msg = struct.pack(">BHB", ord("S"), i, 0x40)
        serial.write(msg)

        answer = serial.read(4)
        if len(answer) != 4:
            raise errors.RadioError("Radio refused to send block 0x%04x" % i)

        cmd, addr, size = struct.unpack(">BHB", answer)
        if cmd != ord("X") or addr != i or size != 0x40:
            print "Invalid answer for block 0x%04x:" % i
            print "CMD: %s  ADDR: %04x  SIZE: %02x" % (cmd, addr, size)
            raise errors.RadioError("Unknown response from radio")

        chunk = serial.read(0x40)
        if not chunk:
            raise errors.RadioError("Radio did not send block 0x%04x" % i)
        elif len(chunk) != 0x40:
            print "Chunk length was 0x%04i" % len(chunk)
            raise errors.RadioError("Radio sent incomplete block 0x%04x" % i)
        data += chunk
        serial.write("\x06")

        ack = serial.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio refused to send block 0x%04x" % i)

        do_status(radio, i)

    return memmap.MemoryMap(data)

def do_upload(radio):
    serial = radio.pipe

    do_ident(radio)

    for i in range(0x08, radio._memsize, 0x10):
        msg = struct.pack(">BHB", ord("X"), i - 0x08, 0x10)
        serial.write(msg + radio._mmap[i:i+0x10])

        ack = serial.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio refused to accept block 0x%04x" % i)
        do_status(radio, i)

UV5R_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=4.00),
                     chirp_common.PowerLevel("Low",  watts=1.00)]

# Uncomment this to actually register this radio in CHIRP
@directory.register
class BaofengUV5R(chirp_common.CloneModeRadio):
    VENDOR = "Baofeng"
    MODEL = "UV-5R"
    BAUD_RATE = 9600

    _memsize = 0x1808

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS"]
        rf.valid_power_levels = UV5R_POWER_LEVELS
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_bands = [(136000000, 174000000), (420000000, 450000000)]
        rf.memory_bounds = (0, 127)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10
        
        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _nam.name:
            if str(char) == "\xFF":
                break
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]

        if _mem.txtone == 0:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = chirp_common.DTCS_CODES[index]
        else:
            print "Bug: txtone is %04x" % _mem.txtone

        if _mem.rxtone == 0:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.dtcs = chirp_common.DTCS_CODES[index]
        else:
            print "Bug: rxtone is %04x" % _mem.rxtone

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS":
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        mem.power = UV5R_POWER_LEVELS[_mem.lowpower]
        mem.mode = _mem.wide and "FM" or "NFM"

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _nam = self._memobj.names[mem.number]

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            return

        _mem.rxfreq = mem.freq / 10
        if mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        for i in range(0, 6):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = chirp_common.DTCS_CODES.index(mem.dtcs) + 1
            _mem.rxtone = chirp_common.DTCS_CODES.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = chirp_common.DTCS_CODES.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = chirp_common.DTCS_CODES.index(mem.dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "FM"
        _mem.lowpower = mem.power == UV5R_POWER_LEVELS[0]
