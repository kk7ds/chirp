#
# Copyright 2012 Filippi Marco <iz3gme.marco@gmail.com>
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

from chirp import ft817, chirp_common, errors, directory
from chirp import bitwise

mem_format = """
#seekto 0x4a9;
u8 visible[25];

#seekto 0x4c4;
u8 filled[25];

#seekto 0x4df;
struct {
  u8   tag_on_off:1,
       tag_default:1,
       unknown1:3,
       mode:3;
  u8   duplex:2,
       is_duplex:1,
       is_cwdig_narrow:1,
       is_fm_narrow:1,
       freq_range:3;
  u8   skip:1,
       unknokwn1_1:1,
       ipo:1,
       att:1,
       unknown2:4;
  u8   ssb_step:2,
       am_step:3,
       fm_step:3;
  u8   unknown3:3,
       is_split_tone:1,
       tmode:4;
  u8   unknown4:2,
       tx_mode:3,
       tx_freq_range:3;
  u8   unknown5:1,
       unknown_flag:1,
       tone:6;
  u8   unknown6:8;
  u8   unknown7:1,
       dcs:7;
  u8   unknown8:8;
  ul16 rit;
  u32 freq;
  u32 offset;
  u8   name[8];
} memory[200];

#seekto 0x1CAD;
struct {
  u8   tag_on_off:1,
       tag_default:1,
       unknown1:3,
       mode:3;
  u8   duplex:2,
       is_duplex:1,
       is_cwdig_narrow:1,
       is_fm_narrow:1,
       freq_range:3;
  u8   skip:1,
       unknokwn1_1:1,
       ipo:1,
       att:1,
       unknown2:4;
  u8   ssb_step:2,
       am_step:3,
       fm_step:3;
  u8   unknown3:3,
       is_split_tone:1,
       tmode:4;
  u8   unknown4:2,
       tx_mode:3,
       tx_freq_range:3;
  u8   unknown5:1,
       unknown_flag:1,
       tone:6;
  u8   unknown6:8;
  u8   unknown7:1,
       dcs:7;
  u8   unknown8:8;
  ul16 rit;
  u32 freq;
  u32 offset;
  u8   name[8];
} sixtymeterchannels[5];

"""



@directory.register
class FT857Radio(ft817.FT817Radio):
    MODEL = "FT-857"

    TMODES = {
        0x04 : "Tone",
        0x05 : "TSQL",
        0x0a : "DTCS",
        0xff : "Cross",
        0x00 : "",
    }
    TMODES_REV = {
        ""      : 0x00,
        "Cross" : 0xff,
        "DTCS"  : 0x0a,
        "TSQL"  : 0x05,
        "Tone"  : 0x04,
    }

    CROSS_MODES = {
        0x08 : "DCS->Off",
        0x06 : "Tone->DCS",
        0x09 : "DCS->CTCSS",
        0x01 : "Off->Tone",
        0x02 : "Off->DCS",
    }

    CROSS_MODES_REV = {
        "DCS->Off"   : 0x08,
        "Tone->DCS"  : 0x06,
        "DCS->CTCSS" : 0x09,
        "Off->Tone"  : 0x01,
        "Off->DCS"   : 0x02,
    }

    _model = ""
    _memsize = 7341
    # block 9 (140 Bytes long) is to be repeted 40 times 
    # should be 42 times but this way I cam use original 817 functions
    _block_lengths = [ 2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140, 38, 176]
    VALID_BANDS = [(100000,33000000), (33000000,56000000), (76000000,108000000), (108000000,137000000), (137000000,164000000), (420000000,470000000)] # warning ranges has to be in this exact order

    def get_features(self):
        rf = ft817.FT817Radio.get_features(self)
        rf.has_cross = True
        rf.valid_tmodes = self.TMODES_REV.keys()
        rf.valid_cross_modes = self.CROSS_MODES_REV.keys()
        return rf

    def get_duplex(self, mem, _mem):
        # radio set is_duplex only for + and - but not for split
        # at the same time it does not complain if we set it same way 817 does (so no set_duplex here)
        mem.duplex = self.DUPLEX[_mem.duplex]

    def get_tmode(self, mem, _mem):
	# I do not use is_split_tone here because the radio sometimes set it also for standard tone mode
        try:
            mem.tmode = self.TMODES[int(_mem.tmode)]
        except KeyError:
            mem.tmode = "Cross"
            mem.cross_mode = self.CROSS_MODES[int(_mem.tmode)]

    def set_tmode(self, mem, _mem):
        if mem.tmode != "Cross":
            _mem.is_split_tone = 0
            _mem.tmode = self.TMODES_REV[mem.tmode]
        else:
            _mem.tmode = self.CROSS_MODES_REV[mem.cross_mode]
            _mem.is_split_tone = 1

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

SPECIAL_60M = {
    "M-601" : -1,
    "M-602" : -2,
    "M-603" : -3,
    "M-604" : -4,
    "M-605" : -5,
    }

@directory.register
class FT857_US_Radio(FT857Radio):
    # seems that radios configured for 5MHz operations send one paket more than others
    # so we have to distinguish sub models
    MODEL = "FT-857 (US Version)"

    _model = ""
    _memsize = 7481
    # block 9 (140 Bytes long) is to be repeted 40 times 
    # should be 42 times but this way I cam use original 817 functions
    _block_lengths = [ 2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140, 38, 176, 140]


    def get_special_locations(self):
        return SPECIAL_60M.keys()

    def _get_special(self, number):
        mem = chirp_common.Memory()
        mem.number = SPECIAL_60M[number]
        mem.extd_number = number

        _mem = self._memobj.sixtymeterchannels[abs(mem.number)-1]

        self._get_memory(mem, _mem)

        mem.immutable = ["number", "skip", "rtone", "ctone",
                         "extd_number", "name", "dtcs", "tmode", "cross_mode",
                         "dtcs_polarity", "power", "duplex", "offset",
                         "tuning_step", "comment", "empty"]

        return mem

    def _set_special(self, mem):
        cur_mem = self._get_special(mem.extd_number)

        for key in cur_mem.immutable:
            if cur_mem.__dict__[key] != mem.__dict__[key]:
                raise errors.RadioError("Editing field `%s' " % key +
                                        "is not supported on M-60x channels")

        if mem.mode not in ["USB", "LSB", "CW", "CWR", "NCW", "NCWR", "DIG"]:
            raise errors.RadioError(_("Mode {mode} is not valid "
                                      "in 60m channels").format(mode=mem.mode))
        _mem = self._memobj.sixtymeterchannels[abs(mem.number)-1]
        self._set_memory(mem, _mem)

    def get_memory(self, number):
        if isinstance(number, str):
            return self._get_special(number)
        else:
            return FT857Radio.get_memory(self, number)

    def set_memory(self, memory):
        if memory.number < 0:
            return self._set_special(memory)
        else:
            return FT857Radio.set_memory(self, memory)
