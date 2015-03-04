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

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise
from textwrap import dedent

# flags.{even|odd}_pskip: These are actually "preferential *scan* channels".
# Is that what they mean on other radios as well?

# memory {
#   step_changed: Channel step has been changed. Bit stays on even after
#                 you switch back to default step. Don't know why you would
#                 care
#   half_deviation: 2.5 kHz deviation
#   cpu_shifted:  CPU freq has been shifted (to move a birdie out of channel)
#   power:        0-3: ["L1", "L2", "L3", "Hi"]
#   pager:        Set if this is a paging memory
#   tmodes:       0-7: ["", "Tone", "TSQL", "DTCS", "Rv Tn", "D Code",
#                       "T DCS", "D Tone"]
#                      Rv Tn: Reverse CTCSS - mutes receiver on tone
#                      The final 3 are for split:
#                      D Code: DCS Encode only
#                      T DCS:  Encodes tone, decodes DCS code
#                      D Tone: Encodes DCS code, decodes tone
# }
MEM_FORMAT = """
#seekto 0x018A;
struct {
    u16 in_use;
} bank_used[24];

#seekto 0x0214;
u16  banksoff1;
#seekto 0x0294;
u16  banksoff2;

#seekto 0x097A;
struct {
  u8 name[6];
} bank_names[24];

#seekto 0x0C0A;
struct {
  u16 channels[100];
} banks[24];

#seekto 0x1ECA;
struct {
  u8 even_pskip:1,
     even_skip:1,
     even_valid:1,
     even_masked:1,
     odd_pskip:1,
     odd_skip:1,
     odd_valid:1,
     odd_masked:1;
} flags[500];

#seekto 0x21CA;
struct {
  u8 unknown11:1,
     step_changed:1,
     half_deviation:1,
     cpu_shifted:1,
     unknown12:4;
  u8 mode:2,
     duplex:2,
     tune_step:4;
  bbcd freq[3];
  u8 power:2,
     unknown2:2,
     pager:1,
     tmode:3;
  u8 name[6];
  bbcd offset[3];
  u8 tone;
  u8 dcs;
  u8 unknown5;
} memory[999];
"""

DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "AM", "WFM", "FM"]  # last is auto
TMODES = ["", "Tone", "TSQL", "DTCS"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0,
         9.0, 200.0, 5.0]  # last is auto, 9.0k and 200.0k are unadvertised


CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    list(" +-/\x00[]__" + ("\x00" * 9) + "$%%\x00**.|=\\\x00@") + \
    list("\x00" * 100)

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("L3", watts=2.50),
                chirp_common.PowerLevel("L2", watts=1.00),
                chirp_common.PowerLevel("L1", watts=0.30)]
POWER_LEVELS_220 = [chirp_common.PowerLevel("Hi", watts=1.50),
                    chirp_common.PowerLevel("L3", watts=1.00),
                    chirp_common.PowerLevel("L2", watts=0.50),
                    chirp_common.PowerLevel("L1", watts=0.20)]


class VX6Bank(chirp_common.NamedBank):
    """A VX6 Bank"""
    def get_name(self):
        _bank = self._model._radio._memobj.bank_names[self.index]
        name = ""
        for i in _bank.name:
            if i == 0xFF:
                break
            name += CHARSET[i & 0x7F]
        return name.rstrip()

    def set_name(self, name):
        name = name.upper()
        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = [CHARSET.index(x) for x in name.ljust(6)[:6]]


class VX6BankModel(chirp_common.BankModel):
    """A VX-6 bank model"""

    def get_num_mappings(self):
        return len(self.get_mappings())

    def get_mappings(self):
        banks = self._radio._memobj.banks
        bank_mappings = []
        for index, _bank in enumerate(banks):
            bank = VX6Bank(self, "%i" % index, "b%i" % (index + 1))
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
        _bank_used.in_use = 0x0000  # enable

        # also needed for unit to recognize any banks?
        self._radio._memobj.banksoff1 = 0x0000
        self._radio._memobj.banksoff2 = 0x0000
        # TODO: turn back off (0xFFFF) when all banks are empty?

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        if not channels_in_bank:
            _bank_used = self._radio._memobj.bank_used[bank.index]
            _bank_used.in_use = 0xFFFF  # disable bank

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


@directory.register
class VX6Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-6"""
    BAUD_RATE = 19200
    VENDOR = "Yaesu"
    MODEL = "VX-6"

    _model = "AH021"
    _memsize = 32587
    _block_lengths = [10, 32578]
    _block_size = 16

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
        return [yaesu_clone.YaesuChecksum(0x0000, 0x7F49)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = True
        rf.has_bank_names = True
        rf.has_dtcs_polarity = False
        rf.valid_modes = ["FM", "WFM", "AM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = DUPLEX
        rf.valid_tuning_steps = STEPS
        rf.valid_power_levels = POWER_LEVELS
        rf.memory_bounds = (1, 999)
        rf.valid_bands = [(500000, 998990000)]
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.can_odd_split = True
        rf.has_ctone = False
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1]) + \
            repr(self._memobj.flags[(number-1)/2])

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        _flg = self._memobj.flags[(number-1)/2]

        nibble = ((number-1) % 2) and "even" or "odd"
        used = _flg["%s_masked" % nibble]
        valid = _flg["%s_valid" % nibble]
        pskip = _flg["%s_pskip" % nibble]
        skip = _flg["%s_skip" % nibble]

        mem = chirp_common.Memory()
        mem.number = number

        if not used:
            mem.empty = True
        if not valid:
            mem.empty = True
            mem.power = POWER_LEVELS[0]
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = chirp_common.fix_rounded_step(int(_mem.offset) * 1000)
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone & 0x3f]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = MODES[_mem.mode]
        if mem.mode == "FM" and _mem.half_deviation:
            mem.mode = "NFM"
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs & 0x7f]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.skip = pskip and "P" or skip and "S" or ""

        if mem.freq > 220000000 and mem.freq < 225000000:
            mem.power = POWER_LEVELS_220[3 - _mem.power]
        else:
            mem.power = POWER_LEVELS[3 - _mem.power]

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

        # initialize new channel to safe defaults
        if not mem.empty and not valid:
            _flag["%s_valid" % nibble] = True
            _mem.unknown11 = 0
            _mem.step_changed = 0
            _mem.cpu_shifted = 0
            _mem.unknown12 = 0
            _mem.unknown2 = 0
            _mem.pager = 0
            _mem.unknown5 = 0

        if mem.empty and valid and not used:
            _flag["%s_valid" % nibble] = False
            return
        _flag["%s_masked" % nibble] = not mem.empty

        if mem.empty:
            return

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        if mem.mode == "NFM":
            _mem.mode = MODES.index("FM")
            _mem.half_deviation = 1
        else:
            _mem.mode = MODES.index(mem.mode)
            _mem.half_deviation = 0
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        if mem.power:
            _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        _mem.name = [0xFF] * 6
        for i in range(0, 6):
            _mem.name[i] = CHARSET.index(mem.name.ljust(6)[i])

        if mem.name.strip():
            _mem.name[0] |= 0x80

    def get_bank_model(self):
        return VX6BankModel(self)
