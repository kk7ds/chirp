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
from chirp import chirp_common, yaesu_clone, memmap, bitwise, directory
from chirp import errors
from textwrap import dedent

ACK = "\x06"

def _send(pipe, data):
    pipe.write(data)
    echo = pipe.read(len(data))
    if echo != data:
        raise errors.RadioError("Error reading echo (Bad cable?)")

def _download(radio):
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

    _send(radio.pipe, ACK)

    for i in range(0, 448):
        chunk = radio.pipe.read(64)
        data += chunk
        _send(radio.pipe, ACK)
        if len(chunk) == 1 and i == 447:
            break
        elif len(chunk) != 64:
            raise Exception("Reading block %i was short (%i)" % (i, len(chunk)))
        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i * 64
            status.max = radio.get_memsize()
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    return memmap.MemoryMap(data)

def _upload(radio):
    _send(radio.pipe, radio.get_mmap()[0:8])

    ack = radio.pipe.read(1)
    if ack != ACK:
        raise Exception("Radio did not respond")

    for i in range(0, 448):
        offset = 8 + (i * 64)
        _send(radio.pipe, radio.get_mmap()[offset:offset+64])
        ack = radio.pipe.read(1)
        if ack != ACK:
            raise Exception(_("Radio did not ack block %i") % i)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = offset+64
            status.max = radio.get_memsize()
            status.msg = "Cloning to radio"
            radio.status_fn(status)            

def _decode_freq(freqraw):
    freq = int(freqraw) * 10000
    if freq > 8000000000:
        freq = (freq - 8000000000) + 5000

    if freq > 4000000000:
        freq -= 4000000000
        for i in range(0, 3):
            freq += 2500
            if chirp_common.required_step(freq) == 12.5:
                break

    return freq

def _encode_freq(freq):
    freqraw = freq / 10000
    flags = 0x00
    if ((freq / 1000) % 10) >= 5:
        flags += 0x80
    if chirp_common.is_fractional_step(freq):
        flags += 0x40
    return freqraw, flags

def _decode_name(mem):
    name = ""
    for i in mem:
        if i == 0xFF:
            break
        try:
            name += CHARSET[i]
        except IndexError:
            print "Unknown char index: %i " % (i)
    return name


def _encode_name(mem):
    name = [None]*6
    for i in range(0, 6):
        try:
            name[i] = CHARSET.index(mem[i]) 
        except IndexError:
            name[i] = CHARSET.index(" ")

    return name


MEM_FORMAT = """
#seekto 0x0248;
struct {
  u8 used:1,
     unknown1:1,
     isnarrow:1,
     isam:1,
     duplex:4;
  bbcd freq[3];
  u8 unknown2:1,
     step:3, 
     unknown2_1:1,
     tmode:3;
  bbcd tx_freq[3];
  u8 power:2,
     tone:6;
  u8 unknown4:1,
     dtcs:7;
  u8 unknown5[2];
  u8 offset;
  u8 unknown6[3];
} memory[1000];

#seekto 0x6EC8;
// skips:2 for Memory M in [1, 1000] is in flags[(M-1)/4].skip((M-1)%4).
// Interpret with SKIPS[].
// PMS memories L0 - U50 aka memory 1001 - 1100 don't have skip flags.
struct {
  u8 skip3:2,
     skip2:2,
     skip1:2,
     skip0:2;
} flags[250];

#seekto 0x4708;
struct {
  u8 name[6];
  u8 use_name:1,
     unknown1:7;
  u8 valid:1,
     unknown2:7;
} names[1000];

#seekto 0x69C8;
struct {
  bbcd memory[128];
} banks[10];

#seekto 0x6FC8;
u8 checksum;
"""

DUPLEX = ["", "", "-", "+", "split"]
TMODES = ["", "Tone", "TSQL", "TSQL-R", "DTCS"]
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.0),
                chirp_common.PowerLevel("Mid", watts=2.0),
                chirp_common.PowerLevel("Low", watts=0.5)]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
SKIPS = ["", "S", "P"]
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ [?]^__|`?$%&-()*+,-,/|;/=>?@"

class FT60BankModel(chirp_common.BankModel):
    def get_num_mappings(self):
        return 10

    def get_mappings(self):
        banks = []
        for i in range(0, self.get_num_mappings()):
            bank = chirp_common.Bank(self, "%i" % (i + 1), "Bank %i" % (i + 1))
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_mapping(self, memory, bank):
        number = (memory.number - 1) / 8
        mask = 1 << ((memory.number - 1) & 7)
        self._radio._memobj.banks[bank.index].memory[number].set_bits(mask)

    def remove_memory_from_mapping(self, memory, bank):
        number = (memory.number - 1) / 8
        mask = 1 << ((memory.number - 1) & 7)
        if self._radio._memobj.banks[bank.index].memory[number].get_bits(mask) != mask:
            raise Exception("Memory %i is not in bank %s." % \
                            (memory.number, bank))
        self._radio._memobj.banks[bank.index].memory[number].clr_bits(mask)

    def get_mapping_memories(self, bank):
        memories = []
        for i in range(*self._radio.get_features().memory_bounds):
            number = (i - 1) / 8
            mask = 1 << ((i - 1) & 7)
            if self._radio._memobj.banks[bank.index].memory[number].get_bits(mask) == mask:
                memories.append(self._radio.get_memory(i))
        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            number = (memory.number - 1) / 8
            mask = 1 << ((memory.number - 1) & 7)
            if self._radio._memobj.banks[bank.index].memory[number].get_bits(mask) == mask:
                banks.append(bank)
        return banks

@directory.register
class FT60Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FT-60"""
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "FT-60"
    _model = "AH017"

    _memsize = 28617

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to MIC/SP jack.
            3. Press and hold in the [MONI] switch while turning the
                 radio on.
            4. Rotate the DIAL job to select "F8 CLONE".
            5. Press the [F/W] key momentarily.
            6. <b>After clicking OK</b>, press the [PTT] switch to send image."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to MIC/SP jack.
            3. Press and hold in the [MONI] switch while turning the
                 radio on.
            4. Rotate the DIAL job to select "F8 CLONE".
            5. Press the [F/W] key momentarily.
            6. Press the [MONI] switch ("--RX--" will appear on the LCD)."""))
        return rp
        
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 1000)
        rf.valid_duplexes = DUPLEX
        rf.valid_tmodes = TMODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tuning_steps = STEPS
        rf.valid_skips = SKIPS
        rf.valid_characters = CHARSET
        rf.valid_name_length = 6
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_bands = [(108000000, 520000000), (700000000, 999990000)]
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_bank = True
        rf.has_dtcs_polarity = False

        return rf

    def get_bank_model(self):
        return FT60BankModel(self)

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x6FC7) ]

    def sync_in(self):
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()
        self.check_checksums()

    def sync_out(self):
        self.update_checksums()
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1]) + \
            repr(self._memobj.flags[(number - 1) / 4]) + \
            repr(self._memobj.names[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _skp = self._memobj.flags[(number - 1) / 4]
        _nam = self._memobj.names[number - 1]

        skip = _skp["skip%i" % ((number - 1) % 4)]

        mem = chirp_common.Memory()
        mem.number = number

        if not _mem.used:
            mem.empty = True
            return mem

        mem.freq = _decode_freq(_mem.freq)
        mem.offset = int(_mem.offset) * 50000

        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = _decode_freq(_mem.tx_freq)
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.power = POWER_LEVELS[_mem.power]
        mem.mode = _mem.isam and "AM" or _mem.isnarrow and "NFM" or "FM"
        mem.tuning_step = STEPS[_mem.step]
        mem.skip = SKIPS[skip]

        if _nam.use_name and _nam.valid:
            mem.name = _decode_name(_nam.name).rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _skp = self._memobj.flags[(mem.number - 1) / 4]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            _mem.used = False
            return

        if not _mem.used:
            _mem.set_raw("\x00" * 16)
            _mem.used = 1
            print "Wiped"

        _mem.freq, flags = _encode_freq(mem.freq)
        _mem.freq[0].set_bits(flags)
        if mem.duplex == "split":
            _mem.tx_freq, flags = _encode_freq(mem.offset)
            _mem.tx_freq[0].set_bits(flags)
            _mem.offset = 0
        else:
            _mem.tx_freq = 0
            _mem.offset = mem.offset / 50000
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.power = mem.power and POWER_LEVELS.index(mem.power) or 0
        _mem.isnarrow = mem.mode == "NFM"
        _mem.isam = mem.mode == "AM"
        _mem.step = STEPS.index(mem.tuning_step)

        _skp["skip%i" % ((mem.number - 1) % 4)] = SKIPS.index(mem.skip)

        _nam.name = _encode_name(mem.name)
        _nam.use_name = mem.name.strip() and True or False
        _nam.valid = _nam.use_name
