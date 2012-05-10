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

from chirp import chirp_common, yaesu_clone, util, directory
from chirp import bitwise

mem_format = """
#seekto 0x0611;
u8 checksum1;

#seekto 0x0691;
u8 checksum2;

#seekto 0x0742;
struct {
  u16 in_use;
} bank_used[9];

#seekto 0x0EA2;
struct {
  u16 members[48];
} bank_members[9];

#seekto 0x3F52;
u8 checksum3;

#seekto 0x1202;
struct {
  u8 even_pskip:1,
     even_skip:1,
     even_valid:1,
     even_masked:1,
     odd_pskip:1,
     odd_skip:1,
     odd_valid:1,
     odd_masked:1;
} flags[225];

#seekto 0x1322;
struct {
  u8   unknown1;
  u8   power:2,
       duplex:2,
       tune_step:4;
  bbcd freq[3];
  u8   zeros1:2,
       ones:2,
       zeros2:2,
       mode:2;
  u8   name[8];
  u8 zero;
  bbcd offset[3];
  u8   zeros3:2,
       tone:6;
  u8   zeros4:1,
       dcs:7;
  u8   zeros5:6,
       tmode:2;
  u8   charset;
} memory[450];
"""

DUPLEX = ["", "-", "+", "split"]
MODES  = ["FM", "AM", "WFM", "FM"] # last is auto
TMODES = ["", "Tone", "TSQL", "DTCS"]
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(6.25)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.append(9.0)

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [" "] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    [chr(x) for x in range(ord("a"), ord("z")+1)] + \
    list(".,:;!\"#$%&'()*+-.=<>?@[?]^_\\{|}") + \
    list("\x00" * 100)

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("L3", watts=2.50),
                chirp_common.PowerLevel("L2", watts=1.00),
                chirp_common.PowerLevel("L1", watts=0.05)]
POWER_LEVELS_220 = [chirp_common.PowerLevel("L2", watts=0.30),
                    chirp_common.PowerLevel("L1", watts=0.05)]

class VX7BankModel(chirp_common.BankModel):
    def get_num_banks(self):
        return 9

    def get_banks(self):
        banks = []
        for i in range(0, self.get_num_banks()):
            bank = chirp_common.Bank(self, "%i" % (i+1), "MG%i" % (i+1))
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_bank(self, memory, bank):
        _members = self._radio._memobj.bank_members[bank.index]
        _bank_used = self._radio._memobj.bank_used[bank.index]
        for i in range(0, 48):
            if _members.members[i] == 0xFFFF:
                _members.members[i] = memory.number - 1
                _bank_used.in_use = 0x0000
                break

    def remove_memory_from_bank(self, memory, bank):
        _members = self._radio._memobj.bank_members[bank.index].members
        _bank_used = self._radio._memobj.bank_used[bank.index]

        found = False
        remaining_members = 0
        for i in range(0, len(_members)):
            if _members[i] == (memory.number - 1):
                _members[i] = 0xFFFF
                found = True
            elif _members[i] != 0xFFFF:
                remaining_members += 1

        if not found:
            raise Exception(_("Memory {num} not in "
                              "bank {bank}").format(num=memory.number,
                                                    bank=bank))
        if not remaining_members:
            _bank_used.in_use = 0xFFFF

    def get_bank_memories(self, bank):
        memories = []

        _members = self._radio._memobj.bank_members[bank.index].members
        _bank_used = self._radio._memobj.bank_used[bank.index]

        if _bank_used.in_use == 0xFFFF:
            return memories

        for number in _members:
            if number == 0xFFFF:
                continue
            memories.append(self._radio.get_memory(number+1))
        return memories

    def get_memory_banks(self, memory):
        banks = []
        for bank in self.get_banks():
            if memory.number in [x.number for x in self.get_bank_memories(bank)]:
                    banks.append(bank)
        return banks

@directory.register
class VX7Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 19200
    VENDOR = "Yaesu"
    MODEL = "VX-7"

    _model = ""
    _memsize = 16211
    _block_lengths = [ 10, 8, 16193 ]
    _block_size = 8

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0592, 0x0610),
                 yaesu_clone.YaesuChecksum(0x0612, 0x0690),
                 yaesu_clone.YaesuChecksum(0x0000, 0x3F51),
                 ]

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = True
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(set(MODES))
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(500000, 999000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 8
        rf.memory_bounds = (1, 450)
        rf.can_odd_split = True
        rf.has_ctone = False
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        _flag = self._memobj.flags[(number-1)/2]

        nibble = ((number-1) % 2) and "even" or "odd"
        used = _flag["%s_masked" % nibble] and _flag["%s_valid" % nibble]
        pskip = _flag["%s_pskip" % nibble]
        skip = _flag["%s_skip" % nibble]

        mem = chirp_common.Memory()
        mem.number = number
        if not used:
            mem.empty = True
            mem.power = POWER_LEVELS[0]
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.skip = pskip and "P" or skip and "S" or ""

        if mem.freq > 220000000 and mem.freq < 225000000:
            mem.power = POWER_LEVELS_220[1 - _mem.power]
        else:
            mem.power = POWER_LEVELS[3 - _mem.power]

        for i in _mem.name:
            if i == "\xFF":
                break
            mem.name += CHARSET[i]
        mem.name = mem.name.rstrip()

        return mem

    def _wipe_memory(self, mem):
        mem.set_raw("\x00" * (mem.size() / 8))
        mem.unknown1 = 0x05
        mem.ones = 0x03

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        _flag = self._memobj.flags[(mem.number-1)/2]

        nibble = ((mem.number-1) % 2) and "even" or "odd"
        
        was_valid = int(_flag["%s_valid" % nibble])

        _flag["%s_masked" % nibble] = not mem.empty
        _flag["%s_valid" % nibble] = not mem.empty
        if mem.empty:
            return

        if not was_valid:
            self._wipe_memory(_mem)
            self._wipe_memory_banks(mem)

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        if mem.power:
            _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        for i in range(0, 8):
            _mem.name[i] = CHARSET.index(mem.name.ljust(8)[i])
        
    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)

        if mem.freq >= 222000000 and mem.freq <= 225000000:
            if str(mem.power) not in ["L1", "L2"]:
                msgs.append(chirp_common.ValidationError(\
                        "Power level %s not supported on 220MHz band" % mem.power))

        return msgs

    @classmethod
    def match_model(cls, filedata):
        return len(filedata) == cls._memsize

    def get_bank_model(self):
        return VX7BankModel(self)
