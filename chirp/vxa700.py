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

from chirp import chirp_common, util, directory, memmap, errors
from chirp import bitwise

import time
import struct

def debug(string):
    pass
    print string

def send(radio, data):
    debug("Sending %s" % repr(data))
    radio.pipe.write(data)
    radio.pipe.flush()
    echo = radio.pipe.read(len(data))
    if len(echo) != len(data):
        raise errors.RadioError("Invalid echo")

def spoonfeed(radio, data):
    count = 0
    debug("Writing %i:\n%s" % (len(data), util.hexprint(data)))
    for byte in data:
        radio.pipe.write(byte)
        time.sleep(0.004)
        echo = radio.pipe.read(1)
        if echo != byte:
            print "%02x != %02x" % (ord(echo), ord(byte))
            raise errors.RadioError("No echo?")
        count += 1

def download(radio):
    count = 0
    data = ""
    while len(data) < radio._memsize:
        count += 1
        chunk = radio.pipe.read(133)
        if len(chunk) == 0 and len(data) == 0 and count < 30:
            continue
        if len(chunk) != 132:
            raise errors.RadioError("Got short block (length %i)" % len(chunk))

        flag, length, block = struct.unpack("BBB", chunk[:3])
        checksum = ord(chunk[-1])

        flag, length, block, _data, checksum = struct.unpack("BBB128sB", chunk)

        cs = 0
        for byte in chunk[:-1]:
            cs += ord(byte)
        if (cs % 256) != checksum:
            raise errors.RadioError("Invalid checksum at 0x%02x" % len(data))

        data += _data
        send(radio, "\x06")

        if radio.status_fn:
            status = chirp_common.Status()
            status.msg = "Cloning from radio"
            status.cur = len(data)
            status.max = radio._memsize
            radio.status_fn(status)

    return memmap.MemoryMap(data)

def upload(radio):
    for i in range(0, radio._memsize, 128):
        chunk = radio._mmap[i:i+128]
        cs = 0x20 + 130 + (i / 128)
        for byte in chunk:
            cs += ord(byte)
        spoonfeed(radio,
                  struct.pack("BBB128sB",
                              0x20,
                              130,
                              i / 128,
                              chunk,
                              cs % 256))
        radio.pipe.write("")
        start = time.time()
        ack = radio.pipe.read(1)
        if ack != "\x06":
            print repr(ack)
            raise errors.RadioError("Radio did not ack block %i" % (i / 132))
        radio.pipe.read(1)
        if radio.status_fn:
            status = chirp_common.Status()
            status.msg = "Cloning to radio"
            status.cur = i
            status.max = radio._memsize
            radio.status_fn(status)

mem_format = """
struct memory_struct {
  u8 unknown1;
  u8 unknown2:2,
     isfm:1,
     power:2,
     step:3;
  u8 unknown5:3,
     skip:1,
     duplex:2,
     unknown6:2;
  u8 tmode:2,
     unknown7:6;
  u8 unknown8;
  u8 unknown9:2,
     tone:6;
  u8 dtcs;
  u8 name[8];
  u16 freq;
  u8 offset;
};

u8 headerbytes[6];

#seekto 0x0006;
u8 invisible_bits[13];
u8 bitfield_pad[3];
u8 invalid_bits[13];

#seekto 0x017F;
struct memory_struct memory[100];
"""

CHARSET = "".join(["%i" % i for i in range(0, 10)]) + \
    "".join([chr(ord("A") + i) for i in range(0, 26)]) + \
    "".join([chr(ord("a") + i) for i in range(0,26)]) + \
    "., :;!\"#$%&'()*+-/=<>?@[?]^_`{|}????~??????????????????????????"
            
TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", ""]
POWER = [chirp_common.PowerLevel("Low1", watts=0.050),
         chirp_common.PowerLevel("Low2", watts=1.000),
         chirp_common.PowerLevel("Low3", watts=2.500),
         chirp_common.PowerLevel("High", watts=5.000)]

@directory.register
class VXA700Radio(chirp_common.CloneModeRadio):
    VENDOR = "Vertex Standard"
    MODEL = "VXA-700"
    _memsize = 4096

    def sync_in(self):
        try:
            self._mmap = download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with the radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        #header[4] = 0x00 <- default
        #            0xFF <- air band only
        #            0x01 <- air band only
        #            0x02 <- air band only
        try:
            upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with the radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False
        rf.valid_tmodes = TMODES
        rf.valid_name_length = 8
        rf.valid_characters = CHARSET
        rf.valid_skips = ["", "S"]
        rf.valid_bands = [(88000000, 165000000)]
        rf.valid_tuning_steps = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
        rf.valid_modes = ["AM", "FM"]
        rf.valid_power_levels = POWER
        rf.memory_bounds = (1,100)
        return rf

    def _get_mem(self, number):
        return self._memobj.memory[number - 1]

    def get_raw_memory(self, number):
        _mem = self._get_mem(number)
        return repr(_mem) + util.hexprint(_mem.get_raw())

    def get_memory(self, number):
        _mem = self._get_mem(number)
        byte = (number - 1) / 8;
        bit = 1 << ((number - 1) % 8);

        mem = chirp_common.Memory()
        mem.number = number

        if self._memobj.invisible_bits[byte] & bit:
            mem.empty = True
        if self._memobj.invalid_bits[byte] & bit:
            mem.empty = True
            return mem

        if _mem.step & 0x05: # Not sure this is right, but it seems to be
            mult = 6250
        else:
            mult = 5000

        mem.freq = int(_mem.freq) * mult
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.offset = int(_mem.offset) * 5000 * 10
        mem.mode = _mem.isfm and "FM" or "AM"
        mem.skip = _mem.skip and "S" or ""
        mem.power = POWER[_mem.power]

        for char in _mem.name:
            try:
                mem.name += CHARSET[char]
            except IndexError:
                break
        mem.name = mem.name.rstrip()

        return mem

    def _wipe_memory(self, _mem):
        _mem.set_raw("\x00" * (_mem.size() / 8))

    def set_memory(self, mem):
        _mem = self._get_mem(mem.number)
        byte = (mem.number - 1) / 8;
        bit = 1 << ((mem.number - 1) % 8);

        if mem.empty and self._memobj.invisible_bits[byte] & bit:
            self._memobj.invalid_bits[byte] |= bit
            return
        if mem.empty:
            self._memobj.invisible_bits[byte] |= bit
            return

        if self._memobj.invalid_bits[byte] & bit:
            self._wipe_memory(_mem)

        self._memobj.invisible_bits[byte] &= ~bit
        self._memobj.invalid_bits[byte] &= ~bit

        if chirp_common.required_step(mem.freq) == 12.5:
            mult = 6250
            _mem.step = 0x05
        else:
            mult = 5000
            _mem.step = 0x00

        _mem.freq = mem.freq / mult
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.offset = mem.offset / 5000 / 10
        _mem.isfm = mem.mode == "FM"
        _mem.skip = mem.skip == "S"
        try:
            _mem.power = POWER.index(mem.power)
        except:
            _mem.power = 3 # High

        for i in range(0, 8):
            try:
                _mem.name[i] = CHARSET.index(mem.name[i])
            except IndexError:
                _mem.name[i] = 0x40

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            ord(filedata[5]) == 0x0F
