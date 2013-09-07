# Copyright 2013 Jens Jensen <kd4tjx@yahoo.com>
#     based on modification of Dan Smith's and Rick Farina's original work
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

MEM_FORMAT = """
#seekto 0x7F52;
u8 checksum;

#seekto 0x016A;
u16 bank_use[20];

#seekto 0x05C2;
struct {
  u16 channel[100];
} banks[20];

#seekto 0x1562;
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

#seekto 0x17C2;
struct {
  u8   unknown1:2,
       txnarrow:1,
       clk:1,
       unknown2:4;
  u8   mode:2,
       duplex:2,
       tune_step:4;
  bbcd freq[3];
  u8   power:2,
       unknown3:4,
       tmode:2;
  u8   name[6];
  bbcd offset[3];
  u8   unknown4:2,
       tone:6;
  u8   unknown5:1,
       dcs:7;
  u8   unknown6;

} memory[1000];
"""

VX2_DUPLEX = ["", "-", "+", "split"]
VX2_MODES  = ["FM", "AM", "WFM", "Auto", "NFM"] # NFM handled specially in radio
VX2_TMODES = ["", "Tone", "TSQL", "DTCS"]

VX2_STEPS = [ 5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0, 9.0 ]

CHARSET = list("0123456789" + \
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ " + \
                   "+-/\x00[](){}\x00\x00_" + \
                   ("\x00" * 13) + "*" + "\x00\x00,'|\x00\x00\x00\x00" + \
                   ("\x00" * 64))

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=1.50),
                chirp_common.PowerLevel("Low", watts=0.10)]

class VX2Bank(chirp_common.Bank):
    """A VX2 Bank"""
    def get_name(self):
        _bank = self._model._radio._memobj.banks[self.index]
        name = "bank_" + str(self.index + 1)
        return name

class VX2BankModel(chirp_common.MTOBankModel):
    """A VX-2 bank model"""
    def get_num_mappings(self):
        return len(self._radio._memobj.banks)

    def get_mappings(self):
        _banks = self._radio._memobj.banks
        banks = []
        for i in range(0, self.get_num_mappings()):
            bank = VX2Bank(self, "%i" % i, "Bank-%i" % i)
            bank.index = i
            banks.append(bank)
        return banks

def _wipe_memory(mem):
    # TODO: implement memory wipe?
    mem.set_raw("\x00" * (mem.size() / 8))

@directory.register
class VX2Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-2"""
    MODEL = "VX-2"
    _model = "AH015"
    BAUD_RATE = 19200
    _block_lengths = [ 10, 8, 32577 ]
    _memsize = 32595

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False   # TODO: add bank support
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(set(VX2_MODES))
        rf.valid_tmodes = list(VX2_TMODES)
        rf.valid_duplexes = list(VX2_DUPLEX)
        rf.valid_tuning_steps = list(VX2_STEPS)
        rf.valid_bands = [(500000, 999000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.memory_bounds = (1, 1000)
        rf.can_odd_split = True
        rf.has_ctone = False
        return rf

    def _checksums(self):
        return [ yaesu_clone.YaesuChecksum(0x0000, 0x7F51) ]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
    
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
        mem.tmode = VX2_TMODES[_mem.tmode]
        mem.duplex = VX2_DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        if _mem.txnarrow and _mem.mode == VX2_MODES.index("FM"):
            # narrow + FM
            mem.mode = "NFM"
        else:
            mem.mode = VX2_MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = VX2_STEPS[_mem.tune_step]
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
        _mem.tmode = VX2_TMODES.index(mem.tmode)
        _mem.duplex = VX2_DUPLEX.index(mem.duplex)
        if mem.mode == "NFM":
            _mem.mode = VX2_MODES.index("FM")
            _mem.txnarrow = True
        else:
            _mem.mode = VX2_MODES.index(mem.mode)
            _mem.txnarrow = False
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = VX2_STEPS.index(mem.tuning_step)
        if mem.power == POWER_LEVELS[1]: # Low
            _mem.power = 0x00
        else: # Default to High
            _mem.power = 0x03

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        for i in range(0, 6):
            _mem.name[i] = CHARSET.index(mem.name.ljust(6)[i])
        if mem.name.strip():
            # empty name field, disable name display
            # leftmost bit of name chararr is: 1 = display freq, 0 = display name
            _mem.name[0] |= 0x80
        
        # for now, clear unknown fields
        for i in range(1,7):
            setattr(_mem, "unknown%i" % i, 0)
        
    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)
        return msgs

    def get_bank_model(self):
        return VX2BankModel(self)


