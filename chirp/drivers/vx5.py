# Copyright 2011 Dan Smith <dsmith@danplanet.com>
# Copyright 2012 Tom Hayward <tom@tomh.us>
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
from chirp import chirp_common, directory, errors, bitwise
from textwrap import dedent

MEM_FORMAT = """
struct mem_struct {
  u8 unknown1:2,
     half_deviation:1,
     cpu_shift:1,
     unknown2:1,
     sp_rx1:1,
     unknown3:1,
     sp_rx2:1;
  u8 unknown4:4,
     tuning_step:4;
  bbcd freq[3];
  u8 icon:6,
     mode:2;
  char name[8];
  bbcd offset[3];
  u8 tmode:4,
     power:2,
     duplex:2;
  u8 unknown5:2,
     tone:6;
  u8 unknown6:1,
     dtcs:7;
  u8 unknown7;
  u8 unknown8;
};

struct flag_struct {
  u8 zeros:4,
     pskip:1,
     skip:1,
     visible:1,
     used:1;
};

#seekto 0x002A;
struct {
  u8 current_member;
} bank_used[5];

#seekto 0x0032;
struct {
  struct {
    u8 status;
    u8 channel;
  } members[24];
} bank_groups[5];

#seekto 0x012A;
struct flag_struct flag[220];
struct flag_struct specialflag[20];

#seekto 0x026A;
struct mem_struct memory[220];
struct mem_struct special[50];

#seekto 0x1D03;
u8 current_bank;
"""

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "AM", "WFM"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("L3", watts=2.50),
                chirp_common.PowerLevel("L2", watts=1.00),
                chirp_common.PowerLevel("L1", watts=0.05)]
SPECIALS = ["%s%d" % (c, i + 1) for i in range(0, 10) for c in ('L', 'U')]


class VX5BankModel(chirp_common.BankModel):
    def get_num_mappings(self):
        return 5

    def get_mappings(self):
        banks = []
        for i in range(0, self.get_num_mappings()):
            bank = chirp_common.Bank(self, "%i" % (i+1), "MG%i" % (i+1))
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_mapping(self, memory, bank):
        _members = self._radio._memobj.bank_groups[bank.index].members
        _bank_used = self._radio._memobj.bank_used[bank.index]
        for i in range(0, len(_members)):
            if _members[i].status == 0xFF:
                # LOG.debug("empty found, inserting %d at %d" %
                #           (memory.number, i))
                if self._radio._memobj.current_bank == 0xFF:
                    self._radio._memobj.current_bank = bank.index
                _members[i].status = 0x00
                _members[i].channel = memory.number - 1
                _bank_used.current_member = i
                return True
        raise Exception(_("{bank} is full").format(bank=bank))

    def remove_memory_from_mapping(self, memory, bank):
        _members = self._radio._memobj.bank_groups[bank.index].members
        _bank_used = self._radio._memobj.bank_used[bank.index]

        found = False
        remaining_members = 0
        for i in range(0, len(_members)):
            if _members[i].status == 0x00:
                if _members[i].channel == (memory.number - 1):
                    _members[i].status = 0xFF
                    found = True
                else:
                    remaining_members += 1

        if not found:
            raise Exception(_("Memory {num} not in "
                              "bank {bank}").format(num=memory.number,
                                                    bank=bank))
        if not remaining_members:
            _bank_used.current_member = 0xFF

    def get_mapping_memories(self, bank):
        memories = []

        _members = self._radio._memobj.bank_groups[bank.index].members
        _bank_used = self._radio._memobj.bank_used[bank.index]

        if _bank_used.current_member == 0xFF:
            return memories

        for member in _members:
            if member.status == 0xFF:
                continue
            memories.append(self._radio.get_memory(member.channel+1))
        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in [x.number for x in
                                 self.get_mapping_memories(bank)]:
                    banks.append(bank)
        return banks


@directory.register
class VX5Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-5"""
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "VX-5"

    _model = ""
    _memsize = 8123
    _block_lengths = [10, 16, 8097]
    _block_size = 8

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, 0x1FB9, 0x1FBA)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = True
        rf.has_bank = True
        rf.has_ctone = False
        rf.has_dtcs_polarity = False
        rf.valid_modes = MODES + ["NFM"]
        rf.valid_tmodes = TMODES
        rf.valid_tuning_steps = STEPS
        rf.valid_duplexes = DUPLEX
        rf.memory_bounds = (1, 220)
        rf.valid_bands = [(500000,    16000000),
                          (48000000,  729000000),
                          (800000000, 999000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 8
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_special_chans = SPECIALS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def get_memory(self, number):
        mem = chirp_common.Memory()
        if isinstance(number, str):
            mem.number = len(self._memobj.memory) + SPECIALS.index(number) + 1
            mem.extd_number = number
            _mem = self._memobj.special[mem.number -
                                        len(self._memobj.memory) - 1]
            _flg = self._memobj.specialflag[mem.number -
                                            len(self._memobj.memory) - 1]
        elif number > len(self._memobj.memory):
            mem.number = number
            mem.extd_number = SPECIALS[number - len(self._memobj.memory) - 1]
            _mem = self._memobj.special[mem.number -
                                        len(self._memobj.memory) - 1]
            _flg = self._memobj.specialflag[mem.number -
                                            len(self._memobj.memory) - 1]
        else:
            mem.number = number
            _mem = self._memobj.memory[mem.number - 1]
            _flg = self._memobj.flag[mem.number - 1]

        if not _flg.visible:
            mem.empty = True
        if not _flg.used:
            mem.empty = True
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.duplex = DUPLEX[_mem.duplex]
        mem.name = self.filter_name(str(_mem.name).rstrip())
        mem.mode = MODES[_mem.mode]
        if mem.mode == "FM" and _mem.half_deviation:
            mem.mode = "NFM"
        mem.tuning_step = STEPS[_mem.tuning_step]
        mem.offset = int(_mem.offset) * 1000
        mem.power = POWER_LEVELS[3 - _mem.power]
        mem.tmode = TMODES[_mem.tmode & 0x3]  # masked so bad mems can be read
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        mem.rtone = mem.ctone = chirp_common.OLD_TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]

        mem.skip = _flg.pskip and "P" or _flg.skip and "S" or ""

        return mem

    def set_memory(self, mem):
        if mem.number > len(self._memobj.memory):
            _mem = self._memobj.special[mem.number -
                                        len(self._memobj.memory) - 1]
            _flg = self._memobj.specialflag[mem.number -
                                            len(self._memobj.memory) - 1]
        else:
            _mem = self._memobj.memory[mem.number - 1]
            _flg = self._memobj.flag[mem.number - 1]

        # initialize new channel to safe defaults
        if not mem.empty and not _flg.used:
            _flg.used = True
            _mem.unknown1 = 0x00
            _mem.unknown2 = 0x0
            _mem.unknown3 = 0x0
            _mem.unknown4 = 0x0000
            _mem.unknown5 = 0x0
            _mem.unknown6 = 0x0
            _mem.unknown7 = 0x00
            _mem.unknown8 = 0x00
            _mem.cpu_shift = 0x0
            _mem.sp_rx1 = 0x0
            _mem.sp_rx2 = 0x0

            _mem.icon = 12  # file cabinet icon

        if mem.empty and _flg.used and not _flg.visible:
            _flg.used = False
            return
        _flg.visible = not mem.empty
        if mem.empty:
            self._wipe_memory_banks(mem)
            return

        _mem.freq = int(mem.freq / 1000)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.name = mem.name.ljust(8)
        if mem.mode == "NFM":
            _mem.mode = MODES.index("FM")
            _mem.half_deviation = 1
        else:
            _mem.mode = MODES.index(mem.mode)
            _mem.half_deviation = 0
        _mem.tuning_step = STEPS.index(mem.tuning_step)
        _mem.offset = int(mem.offset / 1000)
        if mem.power:
            _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0
        _mem.tmode = TMODES.index(mem.tmode)
        try:
            _mem.tone = chirp_common.OLD_TONES.index(mem.rtone)
        except ValueError:
            raise errors.UnsupportedToneError(
                ("This radio does not support tone %s" % mem.rtone))
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)

        _flg.skip = mem.skip == "S"
        _flg.pskip = mem.skip == "P"

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to MIC/EAR jack.
            3. Press and hold in the [F/W] key while turning the radio on
                ("CLONE" will appear on the display).
            4. <b>After clicking OK</b>, press the [VFO(DW)SC] key to receive
                the image from the radio."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to MIC/EAR jack.
            3. Press and hold in the [F/W] key while turning the radio on
                ("CLONE" will appear on the display).
            4. Press the [MR(SKP)SC] key ("CLONE WAIT" will appear
                on the LCD).
            5. Click OK to send image to radio."""))
        return rp

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    def get_bank_model(self):
        return VX5BankModel(self)
