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

mem_struct = """
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
}
"""

# there is a bug in bitwise_grammar that prevent the definition of single structures
# qmb should be only one mem_struct followed by
#""" + mem_struct + """ mtqmb;
# but both qmb and qmb[1] raise an exception so I had to define it as qmb[2]

mem_format = """
#seekto 0x54;
""" + mem_struct + """ vfoa[16];
""" + mem_struct + """ vfob[16];
""" + mem_struct + """ home[4];
""" + mem_struct + """ qmb[2];
""" + mem_struct + """ mtune;

#seekto 0x4a9;
u8 visible[25];
u16 pmsvisible;

#seekto 0x4c4;
u8 filled[25];
u16 pmsfilled;

#seekto 0x4df;
""" + mem_struct + """ memory[200];
""" + mem_struct + """ pms[10];

#seekto 0x1CAD;
""" + mem_struct + """ sixtymeterchannels[5];

"""


SPECIAL_PMS = {          # WARNING Index are hard wired in memory management code !!!
    "PMS-1L" : -47,
    "PMS-1U" : -46,
    "PMS-2L" : -45,
    "PMS-2U" : -44,
    "PMS-3L" : -43,
    "PMS-3U" : -42,
    "PMS-4L" : -41,
    "PMS-4U" : -40,
    "PMS-5L" : -39,
    "PMS-5U" : -38,
}


@directory.register
class FT857Radio(ft817.FT817Radio):
    MODEL = "FT-857"
    _model = ""

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

    _memsize = 7341
    # block 9 (140 Bytes long) is to be repeted 40 times 
    # should be 42 times but this way I can use original 817 functions
    _block_lengths = [ 2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140, 38, 176]

    SPECIAL_MEMORIES = {        # WARNING Index are hard wired in memory management code !!!
        "VFOa-1.8M" : -37,
        "VFOa-3.5M" : -36,
        "VFOa-5M" : -35,
        "VFOa-7M" : -34,
        "VFOa-10M" : -33,
        "VFOa-14M" : -32,
        "VFOa-18M" : -31,
        "VFOa-21M" : -30,
        "VFOa-24M" : -29,
        "VFOa-28M" : -28,
        "VFOa-50M" : -27,
        "VFOa-FM" : -26,
        "VFOa-AIR" : -25,
        "VFOa-144" : -24,
        "VFOa-430" : -23,
        "VFOa-HF" : -22,
        "VFOb-1.8M" : -21,
        "VFOb-3.5M" : -20,
        "VFOb-5M" : -19,
        "VFOb-7M" : -18,
        "VFOb-10M" : -17,
        "VFOb-14M" : -16,
        "VFOb-18M" : -15,
        "VFOb-21M" : -14,
        "VFOb-24M" : -13,
        "VFOb-28M" : -12,
        "VFOb-50M" : -11,
        "VFOb-FM" : -10,
        "VFOb-AIR" : -9,
        "VFOb-144M" : -8,
        "VFOb-430M" : -7,
        "VFOb-HF" : -6,
        "HOME HF" : -5,
        "HOME 50M" : -4,
        "HOME 144M" : -3,
        "HOME 430M" : -2,
        "QMB" : -1,
    }
    FIRST_VFOB_INDEX = -6
    LAST_VFOB_INDEX = -21
    FIRST_VFOA_INDEX = -22
    LAST_VFOA_INDEX = -37

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
	_mem.unknown_flag = 0	# have to put this bit to 0 otherwise we get strange display in tone frequency (menu 83)
				# see bug #88
        if mem.tmode != "Cross":
            _mem.is_split_tone = 0
            _mem.tmode = self.TMODES_REV[mem.tmode]
        else:
            _mem.tmode = self.CROSS_MODES_REV[mem.cross_mode]
            _mem.is_split_tone = 1

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_special_locations(self):
        lista = SPECIAL_PMS.keys()
        lista.extend(self.SPECIAL_MEMORIES)
        return lista

    def _get_special_pms(self, number):
        mem = chirp_common.Memory()
        mem.number = SPECIAL_PMS[number]
        mem.extd_number = number

	bitindex = -38 - mem.number
        used = ((self._memobj.pmsvisible & self._memobj.pmsfilled) >> bitindex) & 0x01
	print "mem.number %i bitindex %i pmsvisible %i pmsfilled %i used %i" % (mem.number, bitindex, self._memobj.pmsvisible, self._memobj.pmsfilled, used)
        if not used:
            mem.empty = True
            return mem

        _mem = self._memobj.pms[47 + mem.number]

        mem = self._get_memory(mem, _mem)

        mem.immutable = ["number", "skip", "rtone", "ctone",
                         "extd_number", "dtcs", "tmode", "cross_mode",
                         "dtcs_polarity", "power", "duplex", "offset",
                         "comment", "empty"]

        return mem

    def _set_special_pms(self, mem):
        cur_mem = self._get_special(mem.extd_number)

	bitindex = -38 - mem.number
	if mem.empty:
            self._memobj.pmsvisible &= ~ (1 << bitindex)
            self._memobj.pmsfilled = self._memobj.pmsvisible
            return
        self._memobj.pmsvisible |=  1 << bitindex
        self._memobj.pmsfilled = self._memobj.pmsvisible
        
        for key in cur_mem.immutable:
            if cur_mem.__dict__[key] != mem.__dict__[key]:
                raise errors.RadioError("Editing field `%s' " % key +
                                        "is not supported on PMS channels")

        _mem = self._memobj.pms[47 + mem.number]
        self._set_memory(mem, _mem)

    def get_memory(self, number):
        if number in SPECIAL_PMS.keys():
            return self._get_special_pms(number)
        else:
            return ft817.FT817Radio.get_memory(self, number)

    def set_memory(self, memory):
        if memory.extd_number in SPECIAL_PMS.keys():
            return self._set_special_pms(memory)
        else:
            return ft817.FT817Radio.set_memory(self, memory)

@directory.register
class FT857_US_Radio(FT857Radio):
    # seems that radios configured for 5MHz operations send one paket more than others
    # so we have to distinguish sub models
    MODEL = "FT-857 (US Version)"

    _model = ""
    _memsize = 7481
    # block 9 (140 Bytes long) is to be repeted 40 times 
    # should be 42 times but this way I can use original 817 functions
    _block_lengths = [ 2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140, 38, 176, 140]


    SPECIAL_60M = {
        "M-601" : -52,
        "M-602" : -51,
        "M-603" : -50,
        "M-604" : -49,
        "M-605" : -48,
        }
    LAST_SPECIAL60M_INDEX = -52
    
    def get_special_locations(self):
        lista = self.SPECIAL_60M.keys()
        lista.extend(FT857Radio.get_special_locations(self))
        return lista

    # this is identical to the one in FT817ND_US_Radio but we inherit from 857
    def _get_special_60M(self, number):
        mem = chirp_common.Memory()
        mem.number = self.SPECIAL_60M[number]
        mem.extd_number = number

        _mem = self._memobj.sixtymeterchannels[-self.LAST_SPECIAL60M_INDEX + mem.number]

        mem = self._get_memory(mem, _mem)

        mem.immutable = ["number", "skip", "rtone", "ctone",
                         "extd_number", "name", "dtcs", "tmode", "cross_mode",
                         "dtcs_polarity", "power", "duplex", "offset",
                         "comment", "empty"]

        return mem

    # this is identical to the one in FT817ND_US_Radio but we inherit from 857
    def _set_special_60M(self, mem):
        cur_mem = self._get_special(mem.extd_number)

        for key in cur_mem.immutable:
            if cur_mem.__dict__[key] != mem.__dict__[key]:
                raise errors.RadioError("Editing field `%s' " % key +
                                        "is not supported on M-60x channels")

        if mem.mode not in ["USB", "LSB", "CW", "CWR", "NCW", "NCWR", "DIG"]:
            raise errors.RadioError(_("Mode {mode} is not valid "
                                      "in 60m channels").format(mode=mem.mode))
        _mem = self._memobj.sixtymeterchannels[-self.LAST_SPECIAL60M_INDEX + mem.number]
        self._set_memory(mem, _mem)

    def get_memory(self, number):
        if number in self.SPECIAL_60M.keys():
            return self._get_special_60M(number)
        else:
            return FT857Radio.get_memory(self, number)

    def set_memory(self, memory):
        if memory.extd_number in self.SPECIAL_60M.keys():
            return self._set_special_60M(memory)
        else:
            return FT857Radio.set_memory(self, memory)
