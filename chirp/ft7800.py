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

import time
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
     unknown5:2,
     tmode:2;
  bbcd split[3];
  u8 power:2,
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
    list("\x00" * 100)

POWER_LEVELS_VHF = [chirp_common.PowerLevel("Hi", watts=50),
                    chirp_common.PowerLevel("Mid1", watts=20),
                    chirp_common.PowerLevel("Mid2", watts=10),
                    chirp_common.PowerLevel("Low", watts=5)]

POWER_LEVELS_UHF = [chirp_common.PowerLevel("Hi", watts=35),
                    chirp_common.PowerLevel("Mid1", watts=20),
                    chirp_common.PowerLevel("Mid2", watts=10),
                    chirp_common.PowerLevel("Low", watts=5)]

def send(s, data):

    for i in data:
        s.write(i)
        time.sleep(0.002)
    s.read(len(data))

def download(radio):
    data = ""

    chunk = ""
    for i in range(0, 30):
        chunk += radio.pipe.read(radio._block_lengths[0])
        if chunk:
            break

    if len(chunk) != radio._block_lengths[0]:
        raise Exception("Failed to read header (%i)" % len(chunk))
    data += chunk

    send(radio.pipe, ACK)

    for i in range(0, radio._block_lengths[1], 64):
        chunk = radio.pipe.read(64)
        data += chunk
        if len(chunk) != 64:
            break
            raise Exception("No block at %i" % i)
        time.sleep(0.01)
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
            time.sleep(0.01)

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

    _model = "AH016"
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
        rf.valid_tuning_steps = STEPS
        rf.valid_bands = [(108000000, 520000000), (700000000, 990000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_power_levels = POWER_LEVELS_VHF
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.can_odd_split = True
        return rf

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x7B47) ]

    def sync_in(self):
        t = time.time()
        self._mmap = download(self)
        print "Download finished in %i seconds" % (time.time() - t)
        self.check_checksums()
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def sync_out(self):
        self.update_checksums()
        t = time.time()
        upload(self)
        print "Upload finished in %i seconds" % (time.time() - t)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def _get_mem_freq(self, mem, _mem):
        f = mem.freq
        # Ugh.  The 0x80 and 0x40 indicate values to add to get the
        # real frequency.  Gross.

        if f > 8000000000:
            f = (f - 8000000000) + 5000

        if f > 4000000000:
            f -= 4000000000
            for i in range(0, 3):
                f += 2500
                if chirp_common.required_step(f) == 12.5:
                    break

        return f

    def _set_mem_freq(self, mem, _mem):
        f = mem.freq
        if ((f / 1000) % 10) == 5:
            f += 8000000000
        elif chirp_common.is_fractional_step(mem.freq):
            f += 4000000000

        return int(f / 10000)

    def _get_mem_offset(self, mem, _mem):
        if mem.duplex == "split":
            return int(_mem.split) * 10000
        else:
            return (_mem.offset * 5) * 10000

    def _set_mem_offset(self, mem, _mem):
        if mem.duplex == "split":
            _mem.split = int(mem.offset / 10000)
        else:
            _mem.offset = (int(mem.offset / 10000) / 5)

    def _get_mem_name(self, mem, _mem):
        _nam = self._memobj.names[mem.number - 1]

        name = ""
        if _nam.used:
            for i in str(_nam.name):
                name += CHARSET[ord(i)]

        return name.rstrip()

    def _set_mem_name(self, mem, _mem):
        _nam = self._memobj.names[mem.number - 1]

        if mem.name.rstrip():
            name = [chr(CHARSET.index(x)) for x in mem.name.ljust(6)[:6]]
            _nam.name = "".join(name)
            _nam.used = 1
            _nam.enabled = 1
        else:
            _nam.used = 0
            _nam.enabled = 0

    def _get_mem_skip(self, mem, _mem):
        _flg = self._memobj.flags[(mem.number - 1) / 4]
        flgidx = (mem.number - 1) % 4
        return SKIPS[_flg["skip%i" % flgidx]]

    def _set_mem_skip(self, mem, _mem):
        _flg = self._memobj.flags[(mem.number - 1) / 4]
        flgidx = (mem.number - 1) % 4
        _flg["skip%i" % flgidx] = SKIPS.index(mem.skip)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number
        mem.empty = not _mem.used
        if mem.empty:
            return mem

        mem.freq = int(_mem.freq) * 10000
        mem.freq = self._get_mem_freq(mem, _mem)

        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tmode]
        mem.mode = _mem.mode_am and "AM" or "FM"
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        if self.get_features().has_tuning_step:
            mem.tuning_step = STEPS[_mem.tune_step]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.offset = self._get_mem_offset(mem, _mem)
        mem.name = self._get_mem_name(mem, _mem)

        if int(mem.freq / 100) == 4:
            mem.power = POWER_LEVELS_UHF[_mem.power]
        else:
            mem.power = POWER_LEVELS_VHF[_mem.power]

        mem.skip = self._get_mem_skip(mem, _mem)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        _mem.used = int(not mem.empty)
        if mem.empty:
            return

        _mem.freq = self._set_mem_freq(mem, _mem)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.mode_am = mem.mode == "AM" and 1 or 0
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        if self.get_features().has_tuning_step:
            _mem.tune_step = STEPS.index(mem.tuning_step)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.split = mem.duplex == "split" and int (mem.offset / 10000) or 0
        if mem.power:
            _mem.power = POWER_LEVELS_VHF.index(mem.power)
        else:
            _mem.power = 0
        _mem.unknown5 = 0 # Make sure we don't leave garbage here

        # NB: Leave offset after mem name for the 8800!
        self._set_mem_name(mem, _mem)
        self._set_mem_offset(mem, _mem)

        self._set_mem_skip(mem, _mem)


class FT7900Radio(FT7800Radio):
    MODEL = "FT-7900"

mem_format_8800 = """
#seekto %s;
struct {
  u8 used:1,
     unknown1:2,
     mode_am:1,
     unknown2:1,
     duplex:3;
  bbcd freq[3];
  u8 unknown3:1,
     tune_step:3,
     power:2,
     tmode:2;
  bbcd split[3];
  u8 nameused:1,
     unknown5:1,
     tone:6;
  u8 namevalid:1,
     dtcs:7;
  u8 name[6];
} memory[500];

#seekto 0x51C8;
struct {
  u8 skip0:2,
     skip1:2,
     skip2:2,
     skip3:2;
} flags[250];

#seekto 0x7B48;
u8 checksum;
"""

class FT8800Radio(FT7800Radio):
    MODEL = "FT-8800"

    _model = "AH018"
    _memsize = 22217

    _block_lengths = [8, 22208, 1]
    _block_size = 64

    _memstart = ""

    def get_features(self):
        rf = FT7800Radio.get_features(self)
        rf.has_sub_devices = self.VARIANT == ""
        rf.memory_bounds = (1, 499)
        return rf

    def get_sub_devices(self):
        return [FT8800RadioLeft(self._mmap), FT8800RadioRight(self._mmap)]

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x56C7) ]

    def process_mmap(self):
        if not self._memstart:
            return

        self._memobj = bitwise.parse(mem_format_8800 % self._memstart,
                                     self._mmap)

    def _get_mem_offset(self, mem, _mem):
        if mem.duplex == "split":
            return int(_mem.split) * 10000

        # The offset is packed into the upper two bits of the last four
        # bytes of the name (?!)
        val = 0
        for i in _mem.name[2:6]:
            val <<= 2
            val |= ((i & 0xC0) >> 6)

        return (val * 5) * 10000

    def _set_mem_offset(self, mem, _mem):
        if mem.duplex == "split":
            _mem.split = int(mem.offset / 10000)
            return

        val = int(mem.offset / 10000) / 5
        for i in reversed(range(2, 6)):
            _mem.name[i] = (_mem.name[i] & 0x3F) | ((val & 0x03) << 6)
            val >>= 2

    def _get_mem_name(self, mem, _mem):
        name = ""
        if _mem.namevalid:
            for i in _mem.name:
                index = int(i) & 0x3F
                if index < len(CHARSET):
                    name += CHARSET[index]

        return name.rstrip()

    def _set_mem_name(self, mem, _mem):
        _mem.name = [CHARSET.index(x) for x in mem.name.ljust(6)[:6]]
        _mem.namevalid = 1
        _mem.nameused = bool(mem.name.rstrip())

class FT8800RadioLeft(FT8800Radio):
    VARIANT = "Left"
    _memstart = "0x0948"

class FT8800RadioRight(FT8800Radio):
    VARIANT = "Right"
    _memstart = "0x2948"

mem_format_8900 = """
#seekto 0x0708;
struct {
  u8 used:1,
     skip:2,
     sub_used:1,
     unknown2:1,
     duplex:3;
  bbcd freq[3];
  u8 mode_am:1,
     unknown3:1,
     nameused:1,
     unknown4:1,
     power:2,
     tmode:2;
  bbcd split[3];
  u8 unknown5:2,
     tone:6;
  u8 namevalid:1,
     dtcs:7;
  u8 name[6];
} memory[799];

#seekto 0x51C8;
struct {
  u8 skip0:2,
     skip1:2,
     skip2:2,
     skip3:2;
} flags[400];

#seekto 0x7B48;
u8 checksum;
"""
        
class FT8900Radio(FT8800Radio):
    MODEL = "FT-8900"

    _model = "AH008"
    _memsize = 14793
    _block_lengths = [8, 14784, 1]

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format_8900, self._mmap)

    def get_features(self):
        rf = FT8800Radio.get_features(self)
        rf.has_sub_devices = False
        rf.valid_bands = [( 28000000,  29700000),
                          ( 50000000,  54000000),
                          (108000000, 180000000),
                          (320000000, 480000000),
                          (700000000, 985000000)]
        rf.memory_bounds = (1, 799)
        rf.has_tuning_step = False

        return rf

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x39C7) ]

    def _get_mem_skip(self, mem, _mem):
        return SKIPS[_mem.skip]

    def _set_mem_skip(self, mem, _mem):
        _mem.skip = SKIPS.index(mem.skip)

    def set_memory(self, mem):
        FT8800Radio.set_memory(self, mem)

        # The 8900 has a bit flag that tells the radio whether or not
        # the memory should show up on the sub (right) band
        _mem = self._memobj.memory[mem.number - 1]
        if mem.freq < 108000000 or mem.freq > 480000000:
            _mem.sub_used = 0;
        else:
            _mem.sub_used = 1
