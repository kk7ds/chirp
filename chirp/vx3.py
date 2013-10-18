# Copyright 2011 Rick Farina <sidhayn@gmail.com>
#     based on modification of Dan Smith's original work
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

from chirp import chirp_common, yaesu_clone, directory
from chirp import bitwise
from textwrap import dedent

#interesting offsets which may be checksums needed later
#0x0393 checksum1?
#0x0453 checksum1a?
#0x0409 checksum2?
#0x04C9 checksum2a?

MEM_FORMAT = """
#seekto 0x7F4A;
u8 checksum;

#seekto 0x0B7A;
struct {
  u8 name[6];
} bank_names[24];

#seekto 0x0E0A;
struct {
  u16 channels[100];
} banks[24];

#seekto 0x02EE;
struct {
    u16 in_use;
} bank_used[24];


#seekto 0x20CA;
struct {
  u8 even_pskip:1,
     even_skip:1,
     even_valid:1,
     even_masked:1,
     odd_pskip:1,
     odd_skip:1,
     odd_valid:1,
     odd_masked:1;
} flags[900];

#seekto 0x244A;
struct {
  u8   unknown1a:2,
       txnarrow:1,
       clockshift:1,
       unknown1b:4;
  u8   mode:2,
       duplex:2,
       tune_step:4;
  bbcd freq[3];
  u8   power:2,
       unknown2:4,
       tmode:2;
  u8   name[6];
  bbcd offset[3];
  u8   unknown3:2,
       tone:6;
  u8   unknown4:1,
       dcs:7;
  u8   unknown5;
  u8   unknown6;
  u8   unknown7:4,
       automode:1,
       unknown8:3;
} memory[1000];
"""

#fix auto mode setting and auto step setting

DUPLEX = ["", "-", "+", "split"]
MODES  = ["FM", "AM", "WFM", "Auto", "NFM"] # NFM handled specially in radio
TMODES = ["", "Tone", "TSQL", "DTCS"]

#still need to verify 9 is correct, and add auto: look at byte 1 and 20
STEPS = [ 5.0, 9, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0 ]
#STEPS = list(chirp_common.TUNING_STEPS)
#STEPS.remove(6.25)
#STEPS.remove(30.0)
#STEPS.append(100.0)
#STEPS.append(9.0) #this fails because 9 is out of order in the list

#Empty char should be 0xFF but right now we are coding in a space
CHARSET = list("0123456789" + \
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ " + \
                   "+-/\x00[](){}\x00\x00_" + \
                   ("\x00" * 13) + "*" + "\x00\x00,'|\x00\x00\x00\x00" + \
                   ("\x00" * 64))

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=1.50),
                chirp_common.PowerLevel("Low", watts=0.10)]

class VX3Bank(chirp_common.NamedBank):
    """A VX3 Bank"""
    def get_name(self):
        _bank = self._model._radio._memobj.bank_names[self.index]
        name = ""
        for i in _bank.name:
            if i == 0xFF:
                break
            name += CHARSET[i & 0x7F]
        return name

    def set_name(self, name):
        name = name.upper()
        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = [CHARSET.index(x) for x in name.ljust(6)[:6]]

class VX3BankModel(chirp_common.BankModel):
    """A VX-3 bank model"""

    def get_num_mappings(self):
        return len(self.get_mappings())

    def get_mappings(self):
        banks = self._radio._memobj.banks
        bank_mappings = []
        for index, _bank in enumerate(banks):
            bank = VX3Bank(self, "%i" % index, "b%i" % (index + 1))
            bank.index = index
            bank_mappings.append(bank)

        return bank_mappings

    def _get_channel_numbers_in_bank(self, bank):
        _bank_used = self._radio._memobj.bank_used[bank.index]
        if _bank_used.in_use == 0xFFFF:
            return set()

        _members = self._radio._memobj.banks[bank.index]
        return set([int(ch) + 1 for ch in _members.channels if ch != 0xFFFF])

    def _update_bank_with_channel_numbers(self, bank, channels_in_bank):
        _members = self._radio._memobj.banks[bank.index]
        if len(channels_in_bank) > len(_members.channels):
            raise Exception("Too many entries in bank %d" % bank.index)

        empty = 0
        for index, channel_number in enumerate(sorted(channels_in_bank)):
            _members.channels[index] = channel_number - 1
            empty = index + 1
        for index in range(empty, len(_members.channels)):
            _members.channels[index] = 0xFFFF

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        channels_in_bank.add(memory.number)
        self._update_bank_with_channel_numbers(bank, channels_in_bank)
        _bank_used = self._radio._memobj.bank_used[bank.index]
        _bank_used.in_use = 0x0000

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" % \
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        if not channels_in_bank:
            _bank_used = self._radio._memobj.bank_used[bank.index]
            _bank_used.in_use = 0xFFFF

    def get_mapping_memories(self, bank):
        memories = []
        for channel in self._get_channel_numbers_in_bank(bank):
            memories.append(self._radio.get_memory(channel))

        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._get_channel_numbers_in_bank(bank):
                banks.append(bank)

        return banks

def _wipe_memory(mem):
    mem.set_raw("\x00" * (mem.size() / 8))
    #the following settings are set to match the defaults
    #on the radio, some of these fields are unknown
    mem.name = [0xFF for _i in range(0, 6)]
    mem.unknown5 = 0x0D #not sure what this is
    mem.unknown7 = 0x01 #this likely is part of autostep
    mem.automode = 0x01 #autoselect mode

@directory.register
class VX3Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-3"""
    BAUD_RATE = 19200
    VENDOR = "Yaesu"
    MODEL = "VX-3"

    # 41 48 30 32 38
    _model = "AH028"
    _memsize = 32587
    _block_lengths = [ 10, 32577 ]
    #right now this reads in 45 seconds and writes in 123 seconds
    #attempts to speed it up appear unstable, more testing required
    _block_size = 8

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to MIC/SP jack.
            3. Press and hold in the [F/W] key while turning the radio on
                 ("CLONE" will appear on the display).
            4. <b>After clicking OK</b>, press the [BAND] key to send image."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to MIC/SP jack.
            3. Press and hold in the [F/W] key while turning the radio on
                 ("CLONE" will appear on the display).
            4. Press the [V/M] key ("-WAIT-" will appear on the LCD)."""))
        return rp
        
    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x7F49) ]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = True
        rf.has_bank_names = True
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(set(MODES))
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(500000, 999000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.memory_bounds = (1, 900)
        rf.can_odd_split = True
        rf.has_ctone = False
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        _flag = self._memobj.flags[(number-1)/2]

        nibble = ((number-1) % 2) and "even" or "odd"
        used = _flag["%s_masked" % nibble]
        valid = _flag["%s_valid" % nibble]
        pskip = _flag["%s_pskip" % nibble]
        skip = _flag["%s_skip" % nibble]

        mem = chirp_common.Memory()
        mem.number = number

        if not used:
            mem.empty = True
        if not valid:
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
        if _mem.txnarrow and _mem.mode == MODES.index("FM"):
            # FM narrow
            mem.mode = "NFM"
        else:        
            mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.skip = pskip and "P" or skip and "S" or ""
        mem.power = POWER_LEVELS[~_mem.power & 0x01]

        for i in _mem.name:
            if i == 0xFF:
                break
            mem.name += CHARSET[i & 0x7F]
        mem.name = mem.name.rstrip()
        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        _flag = self._memobj.flags[(mem.number-1)/2]

        nibble = ((mem.number-1) % 2) and "even" or "odd"
      
        used = _flag["%s_masked" % nibble]
        valid = _flag["%s_valid" % nibble]

        if not mem.empty and not valid:
            _wipe_memory(_mem)

        if mem.empty and valid and not used:
            _flag["%s_valid" % nibble] = False
            return
        _flag["%s_masked" % nibble] = not mem.empty

        if mem.empty:
            return

        _flag["%s_valid" % nibble] = True

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        if mem.mode == "NFM":
            _mem.mode = MODES.index("FM")
            _mem.txnarrow = True
        else:
            _mem.mode = MODES.index(mem.mode)
            _mem.txnarrow = False
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        if mem.power == POWER_LEVELS[1]: # Low
            _mem.power = 0x00
        else: # Default to High
            _mem.power = 0x03

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        for i in range(0, 6):
            _mem.name[i] = CHARSET.index(mem.name.ljust(6)[i])
        if mem.name.strip():
            _mem.name[0] |= 0x80
      
    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)
        return msgs

    def get_bank_model(self):
        return VX3BankModel(self)
