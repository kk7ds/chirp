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

"""FT857 - FT857/US management module"""

from chirp import ft817, chirp_common, errors, directory

@directory.register
class FT857Radio(ft817.FT817Radio):
    """Yaesu FT-857/897"""
    MODEL = "FT-857/897"
    _model = ""

    TMODES = {
        0x04 : "Tone",
        0x05 : "TSQL",
        # 0x08 : "DTCS Enc", not supported in UI yet
        0x0a : "DTCS",
        0xff : "Cross",
        0x00 : "",
    }
    TMODES_REV = dict(zip(TMODES.values(), TMODES.keys()))

    CROSS_MODES = {
        0x01 : "->Tone",
        0x02 : "->DTCS",
        # 0x04 : "Tone->", not supported in UI yet
        0x05 : "Tone->Tone",
        0x06 : "Tone->DTCS",
        0x08 : "DTCS->",
        0x09 : "DTCS->Tone",
        0x0a : "DTCS->DTCS",
    }
    CROSS_MODES_REV = dict(zip(CROSS_MODES.values(), CROSS_MODES.keys()))

    _memsize = 7341
    # block 9 (140 Bytes long) is to be repeted 40 times 
    # should be 42 times but this way I can use original 817 functions
    _block_lengths = [ 2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140,
                       38, 176]
    # warning ranges has to be in this exact order
    VALID_BANDS = [(100000, 33000000), (33000000, 56000000),
                   (76000000, 108000000), (108000000, 137000000),
                   (137000000, 164000000), (420000000, 470000000)]

    MEM_FORMAT = """
        struct mem_struct{
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
            unknown_toneflag:1,
            tone:6;
        u8   unknown6:1,
            unknown_rxtoneflag:1,
            rxtone:6;
        u8   unknown7:1,
            dcs:7;
        u8   unknown8:1,
            rxdcs:7;
        ul16 rit;
        u32 freq;
        u32 offset;
        u8   name[8];
        };
        
        #seekto 0x54;
        struct mem_struct vfoa[16];
        struct mem_struct vfob[16];
        struct mem_struct home[4];
        struct mem_struct qmb;
        struct mem_struct mtqmb;
        struct mem_struct mtune;
        
        #seekto 0x4a9;
        u8 visible[25];
        ul16 pmsvisible;
        
        #seekto 0x4c4;
        u8 filled[25];
        ul16 pmsfilled;
        
        #seekto 0x4df;
        struct mem_struct memory[200];
        struct mem_struct pms[10];
        
        #seekto 0x1CAD;
        struct mem_struct sixtymeterchannels[5];
    
    """

    # WARNING Index are hard wired in memory management code !!!
    SPECIAL_MEMORIES = {
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

    SPECIAL_PMS = {
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
    LAST_PMS_INDEX = -47

    SPECIAL_MEMORIES.update(SPECIAL_PMS)

    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))

    def get_features(self):
        rf = ft817.FT817Radio.get_features(self)
        rf.has_cross = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.valid_tmodes = self.TMODES_REV.keys()
        rf.valid_cross_modes = self.CROSS_MODES_REV.keys()
        return rf

    def _get_duplex(self, mem, _mem):
        # radio set is_duplex only for + and - but not for split
        # at the same time it does not complain if we set it same way 817 does
        # (so no set_duplex here)
        mem.duplex = self.DUPLEX[_mem.duplex]

    def _get_tmode(self, mem, _mem):
        if not _mem.is_split_tone:
            mem.tmode = self.TMODES[int(_mem.tmode)]
        else:
            mem.tmode = "Cross"
            mem.cross_mode = self.CROSS_MODES[int(_mem.tmode)]

        if mem.tmode == "Tone":
             mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        elif mem.tmode == "TSQL":
             mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        elif mem.tmode == "DTCS Enc": # UI does not support it yet but
                                      # this code has alreay been tested
             mem.dtcs = mem.rx_dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        elif mem.tmode == "DTCS":
             mem.dtcs = mem.rx_dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        elif mem.tmode == "Cross":
            mem.ctone = chirp_common.TONES[_mem.rxtone]
            # don't want to fail for this
            try:
                mem.rtone = chirp_common.TONES[_mem.tone]
            except IndexError:
                mem.rtone = chirp_common.TONES[0]
            mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
            mem.rx_dtcs = chirp_common.DTCS_CODES[_mem.rxdcs]

    def _set_tmode(self, mem, _mem):
        if mem.tmode != "Cross":
            _mem.is_split_tone = 0
            _mem.tmode = self.TMODES_REV[mem.tmode]
        else:
            _mem.tmode = self.CROSS_MODES_REV[mem.cross_mode]
            _mem.is_split_tone = 1

        if mem.tmode == "Tone":
            _mem.tone = _mem.rxtone = chirp_common.TONES.index(mem.rtone)
        elif mem.tmode == "TSQL":
            _mem.tone = _mem.rxtone = chirp_common.TONES.index(mem.ctone)
        elif mem.tmode == "DTCS Enc": # UI does not support it yet but
                                      # this code has alreay been tested
            _mem.dcs = _mem.rxdcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        elif mem.tmode == "DTCS":
            _mem.dcs = _mem.rxdcs = chirp_common.DTCS_CODES.index(mem.rx_dtcs)
        elif mem.tmode == "Cross":
            _mem.tone = chirp_common.TONES.index(mem.rtone)
            _mem.rxtone = chirp_common.TONES.index(mem.ctone)
            _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
            _mem.rxdcs = chirp_common.DTCS_CODES.index(mem.rx_dtcs)
        # have to put this bit to 0 otherwise we get strange display in tone
        # frequency (menu 83). See bug #88 and #163
        _mem.unknown_toneflag = 0
        # dunno if there's the same problem here but to be safe ...
        _mem.unknown_rxtoneflag = 0

@directory.register
class FT857USRadio(FT857Radio):
    """Yaesu FT857/897 (US version)"""
    # seems that radios configured for 5MHz operations send one paket more
    # than others so we have to distinguish sub models
    MODEL = "FT-857/897 (US)"

    _model = ""
    _memsize = 7481
    # block 9 (140 Bytes long) is to be repeted 40 times 
    # should be 42 times but this way I can use original 817 functions
    _block_lengths = [ 2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140, 38,
                       176, 140]

    SPECIAL_60M = {
        "M-601" : -52,
        "M-602" : -51,
        "M-603" : -50,
        "M-604" : -49,
        "M-605" : -48,
        }
    LAST_SPECIAL60M_INDEX = -52
    
    SPECIAL_MEMORIES = dict(FT857Radio.SPECIAL_MEMORIES)
    SPECIAL_MEMORIES.update(SPECIAL_60M)

    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))

    # this is identical to the one in FT817ND_US_Radio but we inherit from 857
    def _get_special_60m(self, number):
        mem = chirp_common.Memory()
        mem.number = self.SPECIAL_60M[number]
        mem.extd_number = number

        _mem = self._memobj.sixtymeterchannels[-self.LAST_SPECIAL60M_INDEX +
                                                mem.number]

        mem = self._get_memory(mem, _mem)

        mem.immutable = ["number", "skip", "rtone", "ctone",
                         "extd_number", "name", "dtcs", "tmode", "cross_mode",
                         "dtcs_polarity", "power", "duplex", "offset",
                         "comment", "empty"]

        return mem

    # this is identical to the one in FT817ND_US_Radio but we inherit from 857
    def _set_special_60m(self, mem):
        if mem.empty:
            # can't delete 60M memories!
            raise Exception("Sorry, 60M memory can't be deleted")

        cur_mem = self._get_special_60m(self.SPECIAL_MEMORIES_REV[mem.number])

        for key in cur_mem.immutable:
            if cur_mem.__dict__[key] != mem.__dict__[key]:
                raise errors.RadioError("Editing field `%s' " % key +
                                        "is not supported on M-60x channels")

        if mem.mode not in ["USB", "LSB", "CW", "CWR", "NCW", "NCWR", "DIG"]:
            raise errors.RadioError("Mode {mode} is not valid "
                                    "in 60m channels".format(mode=mem.mode))
        _mem = self._memobj.sixtymeterchannels[-self.LAST_SPECIAL60M_INDEX +
                                                mem.number]
        self._set_memory(mem, _mem)

    def get_memory(self, number):
        if number in self.SPECIAL_60M.keys():
            return self._get_special_60m(number)
        elif number < 0 and \
                self.SPECIAL_MEMORIES_REV[number] in self.SPECIAL_60M.keys():
            # I can't stop delete operation from loosing extd_number but
            # I know how to get it back
            return self._get_special_60m(self.SPECIAL_MEMORIES_REV[number])
        else:
            return FT857Radio.get_memory(self, number)

    def set_memory(self, memory):
        if memory.number in self.SPECIAL_60M.values():
            return self._set_special_60m(memory)
        else:
            return FT857Radio.set_memory(self, memory)
