# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import logging

from chirp import bitwise
from chirp.drivers import icf
from chirp import chirp_common, directory

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  ul16 freq;
  ul16 offset;
  char name[5];
  u8 unknown1:2,
     rtone:6;
  u8 unknown2:2,
     ctone:6;
  u8 dtcs;
  u8 unknown3[5];
  u8 tuning_step:4,
    unknown4:4;
  u8 unknown5[3];
  u8 mult:1,
     unknown6_0:1,
     narrow:1,
     unknown6:1,
     unknown7:2,
     tmode:2;
  u8 dtcs_pol:2,
     duplex:2,
     unknown9:4;
  u8 unknown10:1,
     txinhibit:1,
     unknown11:2,
     dvmode:1,
     unknown12:3;
} memories[207];

#seekto 0x1370;
struct {
    u8 unknown:2,
       empty:1,
       skip:1,
       bank:4;
} flags[206];

struct dvcall {
    char call[8];
    char pad[8];
};

#seekto 0x15E0;
struct dvcall mycall[6];
#seekto 0x1640;
struct dvcall urcall[6];
#seekto 0x16A0;
struct dvcall rptcall[6];
#seekto 0x1700;

#seekto 0x1930;
u8 isuhf;
"""


TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEXES = ["", '-', '+']
TUNING_STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0]
DTCS_POLARITY = ['NN', 'NR', 'RN', 'RR']
SPECIALS = ['L0', 'U0', 'L1', 'U1', 'L2', 'U2', 'C']


class ICx8xRadio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    """Icom IC-V/U82"""
    VENDOR = "Icom"
    MODEL = "IC-V82/U82"

    _model = "\x28\x26\x00\x01"
    _memsize = 6464
    _endframe = "Icom Inc\x2eCD"
    _can_hispeed = False
    _double_ident = True

    _memories = []

    _ranges = [(0x0000, 0x1340, 32),
               (0x1340, 0x1360, 16),
               (0x1360, 0x136B,  8),

               (0x1370, 0x1440, 32),

               (0x1460, 0x15D0, 32),

               (0x15E0, 0x1930, 32),

               (0x1938, 0x1940,  8),
               ]

    MYCALL_LIMIT = (0, 6)
    URCALL_LIMIT = (0, 6)
    RPTCALL_LIMIT = (0, 6)

    def _get_bank(self, loc):
        bank = int(self._memobj.flags[loc].bank)
        if bank > 9:
            return None
        else:
            return bank

    def _set_bank(self, loc, bank):
        if bank is None:
            self._memobj.flags[loc].bank = 0x0A
        else:
            self._memobj.flags[loc].bank = bank

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 199)
        rf.valid_modes = ["FM", "NFM", "DV"]
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEXES)
        rf.valid_tuning_steps = list(TUNING_STEPS)
        rf.valid_skips = ["", "S"]
        rf.valid_name_length = 5
        rf.valid_special_chans = list(SPECIALS)

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        if isinstance(number, str):
            mem.extd_number = number
            number = 200 + SPECIALS.index(number)

        _mem = self._memobj.memories[number]

        if number < 206:
            _flg = self._memobj.flags[number]
            mem.skip = _flg.skip and 'S' or ''
            empty = _flg.empty
        else:
            empty = False

        if _mem.mult:
            mult = 6250
        else:
            mult = 5000

        mem.number = number
        if empty:
            mem.empty = True
            return mem

        mem.name = str(_mem.name).rstrip()
        if _mem.dvmode:
            mem.mode = 'DV'
        elif _mem.narrow:
            mem.mode = 'NFM'
        else:
            mem.mode = 'FM'
        mem.duplex = DUPLEXES[_mem.duplex]
        mem.tmode = TMODES[_mem.tmode]
        mem.tuning_step = TUNING_STEPS[_mem.tuning_step]
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_pol]

        mem.freq = (_mem.freq * mult) + chirp_common.to_MHz(self._base)
        mem.offset = _mem.offset * 5000

        return mem

    def set_memory(self, memory):
        _mem = self._memobj.memories[memory.number]
        if memory.number < 206:
            _flg = self._memobj.flags[memory.number]
            _flg.skip = memory.skip == 'S'
            _flg.empty = memory.empty

        if memory.empty:
            return

        _mem.mult = chirp_common.is_fractional_step(memory.freq)
        if _mem.mult:
            mult = 6250
        else:
            mult = 5000
        _mem.freq = (memory.freq - chirp_common.to_MHz(self._base)) // mult
        _mem.offset = memory.offset // 5000
        _mem.name = memory.name[:5].ljust(5)
        _mem.dvmode = memory.mode == 'DV'
        _mem.narrow = memory.mode == 'NFM'
        _mem.duplex = DUPLEXES.index(memory.duplex)
        _mem.tmode = TMODES.index(memory.tmode)
        _mem.tuning_step = TUNING_STEPS.index(memory.tuning_step)
        _mem.rtone = chirp_common.TONES.index(memory.rtone)
        _mem.ctone = chirp_common.TONES.index(memory.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(memory.dtcs)
        _mem.dtcs_pol = DTCS_POLARITY.index(memory.dtcs_polarity)

    def get_raw_memory(self, number):
        if isinstance(number, str):
            number = 200 + SPECIALS.index(number)

        return repr(self._memobj.memories[number])

    def get_urcall_list(self):
        calls = []

        for i in range(*self.URCALL_LIMIT):
            calls.append(str(self._memobj.urcall[i].call).rstrip())

        return calls

    def get_repeater_call_list(self):
        calls = []

        for i in range(*self.RPTCALL_LIMIT):
            calls.append(str(self._memobj.rptcall[i].call).rstrip())

        return calls

    def get_mycall_list(self):
        calls = []

        for i in range(*self.MYCALL_LIMIT):
            calls.append(str(self._memobj.mycall[i].call).rstrip())

        return calls

    def set_urcall_list(self, calls):
        for i in range(*self.URCALL_LIMIT):
            try:
                call = calls[i].ljust(8)
            except IndexError:
                call = " " * 8
            self._memobj.urcall[i].call = call

    def set_repeater_call_list(self, calls):
        for i in range(*self.RPTCALL_LIMIT):
            try:
                call = calls[i].ljust(8)
            except IndexError:
                call = " " * 8
            self._memobj.rptcall[i].call = call

    def set_mycall_list(self, calls):
        for i in range(*self.MYCALL_LIMIT):
            try:
                call = calls[i].ljust(8)
            except IndexError:
                call = " " * 8
            self._memobj.mycall[i].call = call


@directory.register
class ICV82Radio(ICx8xRadio):
    MODEL = 'IC-V82'
    _base = 0

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = [(118000000, 176000000)]
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        if super().match_model(filedata, filename):
            return filedata[0x1930] == 0


@directory.register
class ICU82Radio(ICx8xRadio):
    MODEL = 'IC-U82'
    _base = 400

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = [(420000000, 470000000)]
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        if super().match_model(filedata, filename):
            return filedata[0x1930] == 1
