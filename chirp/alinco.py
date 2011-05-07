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

from chirp import chirp_common, bitwise, memmap

import time

DRx35_mem_format = """
#seekto 0x0200;
struct {
  u8 unknown1:4,
     isnarrow:1,
     unknown2:3;
  u8 unknown3:6,
     duplex:2;
  u8 unknown4:4,
     tmode:4;
  u8 unknown5;
  bbcd freq[3];
  u8 unknown6[2];
  bbcd offset[3];
  u8 rtone;
  u8 ctone;
  u8 dtcs_tx;
  u8 dtcs_rx;
  u8 name[7];
  u8 unknown8[9];
} memory[100];

#seekto 0x0130;
u8 skips[25];
"""

# Response length is:
# 1. \r\n
# 2. Four-digit address, followed by a colon
# 3. 16 bytes in hex (32 characters)
# 4. \r\n
RLENGTH = 2 + 5 + 32 + 2

class AlincoStyleRadio(chirp_common.CloneModeRadio):
    _memsize = 0

    def _send(self, data):
        self.pipe.write(data)
        self.pipe.read(len(data))

    def _download_chunk(self, addr):
        if addr % 16:
            raise Exception("Addr 0x%04x not on 16-byte boundary" % addr)

        cmd = "AL~F%04XR\r\n" % addr
        self._send(cmd)

        resp = self.pipe.read(RLENGTH).strip()
        addr, _data = resp.split(":", 1)
        data = ""
        for i in range(0, len(_data), 2):
            data += chr(int(_data[i:i+2], 16))

        if len(data) != 16:
            print "Response was:"
            print "|%s|"
            print "Which I converted to:"
            print util.hexprint(data)
            raise Exception("Radio returned less than 16 bytes")

        return data

    def _download(self, limit):
        data = ""
        for addr in range(0, limit, 16):
            data += self._download_chunk(addr)
            time.sleep(0.1)

            if self.status_fn:
                s = chirp_common.Status()
                s.cur = addr + 16
                s.max = self._memsize
                s.msg = "Downloading from radio"
                self.status_fn(s)

        self._send("AL~E\r\n")
        r = self.pipe.read(20)
        #print r

        return memmap.MemoryMap(data)

    def _identify(self):
        self._send("%s\r\n" % self._model)
        resp = self.pipe.read(6)
        return resp.strip() == "OK"

    def _upload_chunk(self, addr):
        if addr % 16:
            raise Exception("Addr 0x%04x not on 16-byte boundary" % addr)

        _data = self._mmap[addr:addr+16]
        data = "".join(["%02X" % ord(x) for x in _data])

        cmd = "AL~F%04XW%s\r\n" % (addr, data)
        self._send(cmd)

    def _upload(self, limit):
        if not self._identify():
            raise Exception("I can't talk to this model")

        for addr in range(0x100, limit, 16):
            self._upload_chunk(addr)
            time.sleep(0.1)

            if self.status_fn:
                s = chirp_common.Status()
                s.cur = addr + 16
                s.max = self._memsize
                s.msg = "Uploading to radio"
                self.status_fn(s)

        self._send("AL~E\r\n")
        r = self.pipe.read(20)
        #print r

    def process_mmap(self):
        self._memobj = bitwise.parse(DRx35_mem_format, self._mmap)

    def sync_in(self):
        self._mmap = self._download(self._memsize)
        self.process_mmap()

    def sync_out(self):
        self._upload(self._memsize)

    def get_raw_memory(self, number):
        return self._memobj.memory[number].get_raw()

DUPLEX = ["", "-", "+"]
TMODES = ["", "Tone", "", "TSQL"] + [""] * 12
TMODES[12] = "DTCS"
DCS_CODES = {
    "Alinco" : chirp_common.DTCS_CODES,
    "Jetstream" : [17] + chirp_common.DTCS_CODES,
}

CHARSET = (["\x00"] * 0x30) + \
    [chr(x + ord("0")) for x in range(0, 10)] + \
    [chr(x + ord("A")) for x in range(0, 26)] + [" "] + \
    list("?" * 128)

class DRx35Radio(AlincoStyleRadio):
    _range = (118000000, 155000000)

    def _get_name(self, mem, _mem):
        name = ""
        for i in _mem.name:
            if not i:
                break
            name += CHARSET[i]
        return name

    def _set_name(self, mem, _mem):
        name = [0x00] * 7
        j = 0
        for i in range(0, 7):
            try:
                name[j] = CHARSET.index(mem.name[i])
                j += 1
            except IndexError:
                pass
            except ValueError:
                pass
        return name

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_skips = ["", "S"]
        rf.valid_bands = [self._range]
        rf.memory_bounds = (0, 99)
        rf.has_ctone = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_dtcs_polarity = False
        rf.valid_tuning_steps = []
        return rf

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _skp = self._memobj.skips[number / 8]
        bit = (0x80 >> (number % 8))

        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = int(_mem.freq) * 1000
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.offset = int(_mem.offset)
        mem.tmode = TMODES[_mem.tmode]
        mem.dtcs = DCS_CODES[self.VENDOR][_mem.dtcs_tx]

        if _mem.isnarrow:
            mem.mode = "NFM"

        if _skp & bit:
            mem.skip = "S"

        mem.name = self._get_name(mem, _mem)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _skp = self._memobj.skips[mem.number / 8]
        bit = (0x80 >> (mem.number % 8))

        _mem.freq = mem.freq / 1000
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.offset = mem.offset
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.dtcs_tx = DCS_CODES[self.VENDOR].index(mem.dtcs)
        _mem.dtcs_rx = DCS_CODES[self.VENDOR].index(mem.dtcs)

        _mem.isnarrow = mem.mode == "NFM"

        if mem.skip:
            _skp |= bit
        else:
            _skp &= ~bit

        _mem.name = self._set_name(mem, _mem)
            
    def filter_name(self, name):
        return chirp_common._name(name, 7, True)

class DR135Radio(DRx35Radio):
    VENDOR = "Alinco"
    MODEL = "DR135T"

    _model = "DR135"
    _memsize = 4096
    _range = (118000000, 173000000)

    @classmethod
    def match_model(cls, filedata):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x01) and filedata[0x65] == chr(0x44)

class DR235Radio(DRx35Radio):
    VENDOR = "Alinco"
    MODEL = "DR235T"

    _model = "DR235"
    _memsize = 4096
    _range = (216000000, 280000000)

    @classmethod
    def match_model(cls, filedata):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x02) and filedata[0x65] == chr(0x22)

class DR435Radio(DRx35Radio):
    VENDOR = "Alinco"
    MODEL = "DR435T"

    _model = "DR435"
    _memsize = 4096
    _range = (350000000, 511000000)

    @classmethod
    def match_model(cls, filedata):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x04) and filedata[0x65] == chr(0x00)

class JT220MRadio(DRx35Radio):
    VENDOR = "Jetstream"
    MODEL = "JT220M"

    _model = "DR136"
    _memsize = 4096
    _range = (216000000, 280000000)

    @classmethod
    def match_model(cls, filedata):
        return len(filedata) == cls._memsize and \
            filedata[0x60:0x64] == "2009"
