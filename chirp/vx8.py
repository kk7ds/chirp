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

from chirp import chirp_common, yaesu_clone, directory
from chirp import bitwise

MEM_FORMAT = """
#seekto 0x54a;
struct {
    u16 in_use;
} bank_used[24];

#seekto 0x135A;
struct {
  u8 unknown[2];
  u8 name[16];
} bank_info[24];

#seekto 0x198a;
struct {
    u16 channel[100];
} bank_members[24];

#seekto 0x2C4A;
struct {
  u8 nosubvfo:1,
     unknown:3,
     pskip:1,
     skip:1,
     used:1,
     valid:1;
} flag[900];

#seekto 0x328A;
struct {
  u8 unknown1;
  u8 mode:2,
     duplex:2,
     tune_step:4;
  bbcd freq[3];
  u8 power:2,
     unknown2:4,
     tone_mode:2;
  u8 charsetbits[2];
  char label[16];
  bbcd offset[3];
  u8 unknown5:2,
     tone:6;
  u8 unknown6:1,
     dcs:7;
  u8 unknown7[3];
} memory[900];

#seekto 0xFECA;
u8 checksum;
"""

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]
MODES  = ["FM", "AM", "WFM"]
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.insert(2, 0.0) # There is a skipped tuning step ad index 2 (?)
SKIPS = ["", "S", "P"]

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    [" ",] + \
    [chr(x) for x in range(ord("a"), ord("z")+1)] + \
    list(".,:;*#_-/&()@!?^ ") + list("\x00" * 100)

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("L3", watts=2.50),
                chirp_common.PowerLevel("L2", watts=1.00),
                chirp_common.PowerLevel("L1", watts=0.05)]

class VX8Bank(chirp_common.NamedBank):
    """A VX-8 bank"""

    def get_name(self):
        _bank = self._model._radio._memobj.bank_info[self.index]
        _bank_used = self._model._radio._memobj.bank_used[self.index]
                      
        name = ""
        for i in _bank.name:
            if i == 0xFF:
                break
            name += CHARSET[i & 0x7F]
        return name.rstrip()

    def set_name(self, name):
        _bank = self._model._radio._memobj.bank_info[self.index]
        _bank.name = [CHARSET.index(x) for x in name.ljust(16)[:16]]

class VX8BankModel(chirp_common.BankModel):
    """A VX-8 bank model"""
    def get_num_banks(self):
        return 24

    def get_banks(self):
        banks = []
        _banks = self._radio._memobj.bank_info

        index = 0
        for _bank in _banks:
            bank = VX8Bank(self, "%i" % index, "BANK-%i" % index)
            bank.index = index
            banks.append(bank)
            index += 1

        return banks

    def add_memory_to_bank(self, memory, bank):
        _members = self._radio._memobj.bank_members[bank.index]
        _bank_used = self._radio._memobj.bank_used[bank.index]
        for i in range(0, 100):
            if _members.channel[i] == 0xFFFF:
                _members.channel[i] = memory.number - 1
                _bank_used.in_use = 0x06
                break

    def remove_memory_from_bank(self, memory, bank):
        _members = self._radio._memobj.bank_members[bank.index]
        _bank_used = self._radio._memobj.bank_used[bank.index]

        remaining_members = 0
        found = False
        for i in range(0, len(_members.channel)):
            if _members.channel[i] == (memory.number - 1):
                _members.channel[i] = 0xFFFF
                found = True
            elif _members.channel[i] != 0xFFFF:
                remaining_members += 1

        if not found:
            raise Exception("Memory %i is not in bank %s. Cannot remove" % \
                                (memory.number, bank))

        if not remaining_members:
            _bank_used.in_use = 0xFFFF

    def get_bank_memories(self, bank):
        memories = []
        _members = self._radio._memobj.bank_members[bank.index]
        _bank_used = self._radio._memobj.bank_used[bank.index]

        if _bank_used.in_use == 0xFFFF:
            return memories

        for channel in _members.channel:
            if channel != 0xFFFF:
                memories.append(self._radio.get_memory(int(channel)+1))

        return memories

    def get_memory_banks(self, memory):
        banks = []
        for bank in self.get_banks():
            if memory.number in \
                    [x.number for x in self.get_bank_memories(bank)]:
                banks.append(bank)

        return banks

def _wipe_memory(mem):
    mem.set_raw("\x00" * (mem.size() / 8))
    mem.unknown1 = 0x05

@directory.register
class VX8Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-8"""
    BAUD_RATE = 38400
    VENDOR = "Yaesu"
    MODEL = "VX-8"
    VARIANT = "R"

    _model = "AH029"
    _memsize = 65227
    _block_lengths = [ 10, 65217 ]
    _block_size = 32

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(500000, 999900000)]
        rf.valid_skips = SKIPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 16
        rf.memory_bounds = (1, 900)
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_bank_names = True
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0xFEC9) ]

    def get_memory(self, number):
        flag = self._memobj.flag[number-1]
        _mem = self._memobj.memory[number-1]

        mem = chirp_common.Memory()
        mem.number = number
        if not flag.used:
            mem.empty = True
        if not flag.valid:
            mem.empty = True
            return mem
        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tone_mode]
        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.power = POWER_LEVELS[3 - _mem.power]
        mem.skip = flag.pskip and "P" or flag.skip and "S" or ""

        for i in str(_mem.label):
            if i == "\xFF":
                break
            mem.name += CHARSET[ord(i)]

        return mem

    def _debank(self, mem):
        bm = self.get_bank_model()
        for bank in bm.get_memory_banks(mem):
            bm.remove_memory_from_bank(mem, bank)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        flag = self._memobj.flag[mem.number-1]

        if not mem.empty and not flag.valid:
            _wipe_memory(_mem)

        if mem.empty and flag.valid and not flag.used:
            flag.valid = False
            return
        flag.used = not mem.empty
        flag.valid = flag.used

        if mem.empty:
            return

        if mem.freq < 30000000 or \
                (mem.freq > 88000000 and mem.freq < 108000000) or \
                mem.freq > 580000000:
            flag.nosubvfo = True  # Masked from VFO B
        else:
            flag.nosubvfo = False # Available in both VFOs

        _mem.freq = int(mem.freq / 1000)
        _mem.offset = int(mem.offset / 1000)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tone_mode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        if mem.power:
            _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        label = "".join([chr(CHARSET.index(x)) for x in mem.name.rstrip()])
        _mem.label = label.ljust(16, "\xFF")
        # We only speak english here in chirpville
        _mem.charsetbits[0] = 0x00
        _mem.charsetbits[1] = 0x00

        flag.skip = mem.skip == "S"
        flag.pskip = mem.skip == "P"

    def get_bank_model(self):
        return VX8BankModel(self)

@directory.register
class VX8DRadio(VX8Radio):
    """Yaesu VX-8DR"""
    _model = "AH29D"
    VARIANT = "DR"
