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

from chirp import chirp_common, yaesu_clone, memmap
from chirp import bitwise, util, errors

ACK = chr(0x06)

mem_format = """
#seekto 0x04C8;
struct {
  u8 used:1,
     unknown1:2,
     mode_am:1,
     unknown2:1,
     duplex:3;
  bbcd freq[3];
  u8 unknown3:1,
     tune_step:3,
     unknown4:2,
     tmode:2;
  bbcd split[3];
  u8 unknown5:2,
     tone:6;
  u8 unknown6:1,
     dtcs:7;
  u8 unknown7[2];
  u8 offset;
  u8 unknown9[3];
} memory[1000];

#seekto 0x4988;
struct {
  char name[6];
  u8 enabled:1,
     unknown1:7;
  u8 used:1,
     unknown2:7;
} names[1000];

#seekto 0x7648;
struct {
  u8 skip0:2,
     skip1:2,
     skip2:2,
     skip3:2;
} flags[250];

#seekto 0x7B48;
u8 checksum;
"""

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "", "-", "+", "split"]
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(6.25)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.append(9.0)

SKIPS = ["", "S", "P", ""]

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    list(" " * 10) + \
    list("*+,- /|      [ ] _") + \
    list("?" * 100)

def send(s, data):
    #print "Sending %i:\n%s" % (len(data), util.hexprint(data))
    s.write(data)
    s.read(len(data))

def download(radio):
    data = ""

    chunk = ""
    for i in range(0, 30):
        chunk += radio.pipe.read(radio._block_lengths[0])
        if chunk:
            break

    if len(chunk) != radio._block_lengths[0]:
        raise Exception("Failed to read header")
    data += chunk

    send(radio.pipe, ACK)

    for i in range(0, radio._block_lengths[1], 64):
        chunk = radio.pipe.read(64)
        data += chunk
        if len(chunk) != 64:
            break
            raise Exception("No block at %i" % i)
        send(radio.pipe, ACK)
        if radio.status_fn:
            status = chirp_common.Status()
            status.max = radio._memsize
            status.cur = i+len(chunk)
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    data += radio.pipe.read(1)
    send(radio.pipe, ACK)

    return memmap.MemoryMap(data)

def upload(radio):
    cur = 0
    for block in radio._block_lengths:
        for i in range(0, block, 64):
            length = min(64, block)
            #print "i=%i length=%i range: %i-%i" % (i, length,
            #                                       cur, cur+length)
            send(radio.pipe, radio._mmap[cur:cur+length])
            if radio.pipe.read(1) != ACK:
                raise errors.RadioError("Radio did not ack block at %i" % cur)
            cur += length
            #time.sleep(0.1)

            if radio.status_fn:
                s = chirp_common.Status()
                s.cur = cur
                s.max = radio._memsize
                s.msg = "Cloning to radio"
                radio.status_fn(s)

class FT7800Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "FT-7800"

    _memsize = 31561

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 999)
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs_polarity = False
        rf.valid_modes = ["FM", "AM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(108.0, 520.0), (700.0, 990.0)]
        rf.valid_skips = ["", "S", "P"]
        rf.can_odd_split = True
        return rf

    def _update_checksum(self):
        cs = 0
        for i in range(0, 0x7B48):
            cs += ord(self._mmap[i])
        cs %= 256
        print "Checksum old=%02x new=%02x" % (self._memobj.checksum, cs)
        self._memobj.checksum = cs

    def sync_in(self):
        self._mmap = download(self)
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def sync_out(self):
        self._update_checksum()
        upload(self)

    def get_raw_memory(self, number):
        return self._memobj.memory[number-1].get_raw()

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _flg = self._memobj.flags[(number - 1) / 4]
        _nam = self._memobj.names[number - 1]

        mem = chirp_common.Memory()
        mem.number = number
        mem.empty = not _mem.used
        if mem.empty:
            return mem

        mem.freq = (int(_mem.freq) / 100.0)
        if mem.freq > 4000:
            # Dirty hack because the high-order digit has 0x40
            # if 12.5kHz step
            mem.freq -= 4000
            mem.freq += .00250

        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tmode]
        mem.mode = _mem.mode_am and "AM" or "FM"
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = int(_mem.split) / 100.0
        else:
            mem.offset = (_mem.offset * 5) / 100.0

        if _nam.used:
            for i in str(_nam.name):
                mem.name += CHARSET[ord(i)]
        else:
            mem.name = ""

        flgidx = (number - 1) % 4
        mem.skip = SKIPS[_flg["skip%i" % flgidx]]

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _flg = self._memobj.flags[(mem.number - 1) / 4]
        _nam = self._memobj.names[mem.number - 1]

        _mem.used = int(not mem.empty)
        if mem.empty:
            return

        if chirp_common.is_12_5(mem.freq):
            f = mem.freq - 0.0025
            f += 4000
        else:
            f = mem.freq

        _mem.freq = int(f * 100)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.mode_am = mem.mode == "AM" and 1 or 0
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.offset = (int(mem.offset * 100) / 5)
        _mem.split = mem.duplex == "split" and int (mem.offset * 100) or 0

        if mem.name.rstrip():
            name = [chr(CHARSET.index(x)) for x in mem.name.ljust(6)]
            _nam.name = "".join(name)
            _nam.used = 1
            _nam.enabled = 1
        else:
            _nam.used = 0
            _nam.enabled = 0

        flgidx = (mem.number - 1) % 4
        _flg["skip%i" % flgidx] = SKIPS.index(mem.skip)

class FT7900Radio(FT7800Radio):
    MODEL = "FT-7900"
