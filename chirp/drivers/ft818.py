#
# Copyright 2012 Filippi Marco <iz3gme.marco@gmail.com>
# Copyright 2018 Vinny Stipo <v@xpctech.com>
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

"""FT818 management module"""

from chirp.drivers import ft817
from chirp import chirp_common, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
import os
import logging
from textwrap import dedent
from chirp.util import safe_charset_string

LOG = logging.getLogger(__name__)


@directory.register
class FT818Radio(ft817.FT817Radio):

    """Yaesu FT-818"""
    BAUD_RATE = 9600
    MODEL = "FT-818"
    _model = ""
    _memsize = 6573
    _block_lengths = [2, 40, 208, 208, 208, 208, 198, 53, 130, 118, 130]

    MEM_FORMAT = """
        struct mem_struct {
            u8  tag_on_off:1,
                tag_default:1,
                unknown1:3,
                mode:3;
            u8  duplex:2,
                is_duplex:1,
                is_cwdig_narrow:1,
                is_fm_narrow:1,
                freq_range:3;
            u8  skip:1,
                unknown2:1,
                ipo:1,
                att:1,
                unknown3:4;
            u8  ssb_step:2,
                am_step:3,
                fm_step:3;
            u8  unknown4:6,
                tmode:2;
            u8  unknown5:2,
                tx_mode:3,
                tx_freq_range:3;
            u8  unknown6:1,
                unknown_toneflag:1,
                tone:6;
            u8  unknown7:1,
                dcs:7;
            ul16 rit;
            u32 freq;
            u32 offset;
            u8  name[8];
        };

        #seekto 0x4;
        struct {
            u8  fst:1,
                lock:1,
                nb:1,
                pbt:1,
                unknownb:1,
                dsp:1,
                agc:2;
            u8  vox:1,
                vlt:1,
                bk:1,
                kyr:1,
                unknown5:1,
                cw_paddle:1,
                pwr_meter_mode:2;
            u8  vfob_band_select:4,
                vfoa_band_select:4;
            u8  unknowna;
            u8  backlight:2,
                color:2,
                contrast:4;
            u8  beep_freq:1,
                beep_volume:7;
            u8  arts_beep:2,
                main_step:1,
                cw_id:1,
                scope:1,
                pkt_rate:1,
                resume_scan:2;
            u8  op_filter:2,
                lock_mode:2,
                cw_pitch:4;
            u8  sql_rf_gain:1,
                ars_144:1,
                ars_430:1,
                cw_weight:5;
            u8  cw_delay;
            u8  unknown8:1,
                sidetone:7;
            u8  batt_chg:2,
                cw_speed:6;
            u8  disable_amfm_dial:1,
                vox_gain:7;
            u8  cat_rate:2,
                emergency:1,
                vox_delay:5;
            u8  dig_mode:3,
                mem_group:1,
                unknown9:1,
                apo_time:3;
            u8  dcs_inv:2,
                unknown10:1,
                tot_time:5;
            u8  mic_scan:1,
                ssb_mic:7;
            u8  mic_key:1,
                am_mic:7;
            u8  unknown11:1,
                fm_mic:7;
            u8  unknown12:1,
                dig_mic:7;
            u8  extended_menu:1,
                pkt_mic:7;
            u8  unknown14:1,
                pkt9600_mic:7;
            il16 dig_shift;
            il16 dig_disp;
            i8  r_lsb_car;
            i8  r_usb_car;
            i8  t_lsb_car;
            i8  t_usb_car;
            u8  unknown15:2,
                menu_item:6;
            u8  unknown16:4,
                menu_sel:4;
            u16 unknown17;
            u8  art:1,
                scn_mode:2,
                dw:1,
                pri:1,
                unknown18:1,
                tx_power:2;
            u8  spl:1,
                unknown:1,
                uhf_antenna:1,
                vhf_antenna:1,
                air_antenna:1,
                bc_antenna:1,
                sixm_antenna:1,
                hf_antenna:1;
        } settings;

        #seekto 0x2A;
        struct mem_struct vfoa[16];
        struct mem_struct vfob[16];
        struct mem_struct home[4];
        struct mem_struct qmb;
        struct mem_struct mtqmb;
        struct mem_struct mtune;

        #seekto 0x431;
        u8 visible[25];
        u8 pmsvisible;

        #seekto 0x44B;
        u8 filled[25];
        u8 pmsfilled;

        #seekto 0x465;
        struct mem_struct memory[200];
        struct mem_struct pms[2];

        #seekto 0x1903;
        u8 callsign[7];

        #seekto 0x19AD;
        struct mem_struct sixtymeterchannels[5];
    """

    SPECIAL_MEMORIES = {
        "VFOa-1.8M": -37,
        "VFOa-3.5M": -36,
        "VFOa-5M": -35,
        "VFOa-7M": -34,
        "VFOa-10M": -33,
        "VFOa-14M": -32,
        "VFOa-18M": -31,
        "VFOa-21M": -30,
        "VFOa-24M": -29,
        "VFOa-28M": -28,
        "VFOa-50M": -27,
        "VFOa-FM": -26,
        "VFOa-AIR": -25,
        "VFOa-144": -24,
        "VFOa-430": -23,
        "VFOa-HF": -22,
        "VFOb-1.8M": -21,
        "VFOb-3.5M": -20,
        "VFOb-5M": -19,
        "VFOb-7M": -18,
        "VFOb-10M": -17,
        "VFOb-14M": -16,
        "VFOb-18M": -15,
        "VFOb-21M": -14,
        "VFOb-24M": -13,
        "VFOb-28M": -12,
        "VFOb-50M": -11,
        "VFOb-FM": -10,
        "VFOb-AIR": -9,
        "VFOb-144": -8,
        "VFOb-430": -7,
        "VFOb-HF": -6,
        "HOME HF": -5,
        "HOME 50M": -4,
        "HOME 144": -3,
        "HOME 430": -2,
        "QMB": -1,
    }
    FIRST_VFOB_INDEX = -6
    LAST_VFOB_INDEX = -21
    FIRST_VFOA_INDEX = -22
    LAST_VFOA_INDEX = -37

    SPECIAL_PMS = {
        "PMS-L": -39,
        "PMS-U": -38,
    }
    LAST_PMS_INDEX = -39

    SPECIAL_MEMORIES.update(SPECIAL_PMS)

    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))


@directory.register
class FT818NDUSRadio(FT818Radio):

    """Yaesu FT-818ND (US version)"""
    MODEL = "FT-818ND (US)"

    _model = ""
    _US_model = True
    _memsize = 6703

    _block_lengths = [2, 40, 208, 208, 208, 208, 198, 53, 130, 118, 130, 130]

    SPECIAL_60M = {
        "M-601": -44,
        "M-602": -43,
        "M-603": -42,
        "M-604": -41,
        "M-605": -40,
    }
    LAST_SPECIAL60M_INDEX = -44

    SPECIAL_MEMORIES = dict(FT818Radio.SPECIAL_MEMORIES)
    SPECIAL_MEMORIES.update(SPECIAL_60M)

    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))

    def _get_special_60m(self, number):
        mem = chirp_common.Memory()
        mem.number = self.SPECIAL_60M[number]
        mem.extd_number = number

        _mem = self._memobj.sixtymeterchannels[-self.LAST_SPECIAL60M_INDEX +
                                               mem.number]

        mem = self._get_memory(mem, _mem)

        mem.immutable = ["number", "rtone", "ctone",
                         "extd_number", "name", "dtcs", "tmode", "cross_mode",
                         "dtcs_polarity", "power", "duplex", "offset",
                         "comment", "empty"]

        return mem

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
            return FT818Radio.get_memory(self, number)

    def set_memory(self, memory):
        if memory.number in self.SPECIAL_60M.values():
            return self._set_special_60m(memory)
        else:
            return FT818Radio.set_memory(self, memory)

    def get_settings(self):
        top = FT818Radio.get_settings(self)
        basic = top[0]
        rs = RadioSetting("emergency", "Emergency",
                          RadioSettingValueBoolean(
                              self._memobj.settings.emergency))
        basic.append(rs)
        return top
