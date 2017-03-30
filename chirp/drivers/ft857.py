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
class FT857Radio(ft817.FT817Radio):
    """Yaesu FT-857/897"""
    MODEL = "FT-857/897"
    _model = ""

    TMODES = {
        0x04: "Tone",
        0x05: "TSQL",
        # 0x08 : "DTCS Enc", not supported in UI yet
        0x0a: "DTCS",
        0xff: "Cross",
        0x00: "",
    }
    TMODES_REV = dict(zip(TMODES.values(), TMODES.keys()))

    CROSS_MODES = {
        0x01: "->Tone",
        0x02: "->DTCS",
        0x04: "Tone->",
        0x05: "Tone->Tone",
        0x06: "Tone->DTCS",
        0x08: "DTCS->",
        0x09: "DTCS->Tone",
        0x0a: "DTCS->DTCS",
    }
    CROSS_MODES_REV = dict(zip(CROSS_MODES.values(), CROSS_MODES.keys()))

    _memsize = 7341
    # block 9 (140 Bytes long) is to be repeted 40 times
    # should be 42 times but this way I can use original 817 functions
    _block_lengths = [2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140,
                      38, 176]
    # warning ranges has to be in this exact order
    VALID_BANDS = [(100000, 33000000), (33000000, 56000000),
                   (76000000, 108000000), (108000000, 137000000),
                   (137000000, 164000000), (420000000, 470000000)]

    CHARSET = list(chirp_common.CHARSET_ASCII)
    for i in "\\{|}":
        CHARSET.remove(i)

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

        #seekto 0x00;
        struct {
            u16 radioconfig;
            u8  mem_vfo:2,
                m_tune:1,
                home:1,
                pms_tune:1,
                qmb:1,
                mt_qmb:1,
                vfo_ab:1;
            u8  unknown;
            u8  fst:1,
                lock:1,
                nb:1,
                unknown1:2,
                disp:1,
                agc:2;
            u8  vox:1,
                unknown2:1,
                bk:1,
                kyr:1,
                cw_speed_unit:1,
                cw_key_rev:1,
                pwr_meter_mode:2;
            u8  vfo_b_freq_range:4,
                vfo_a_freq_range:4;
            u8  unknown3;
            u8  disp_mode:2,
                unknown4:2,
                disp_contrast:4;
            u8  unknown5:4,
                clar_dial_sel:2,
                beep_tone:2;
            u8  arts_beep:2,
                dial_step:1,
                arts_id:1,
                unknown6:1,
                pkt_rate:1,
                unknown7:2;
            u8  unknown8:2,
                lock_mode:2,
                unknown9:1,
                cw_pitch:3;
            u8  sql_rf_gain:1,
                ars_144:1,
                ars_430:1,
                cw_weight:5;
            u8  cw_delay;
            u8  cw_delay_hi:1
                cw_sidetone:7;
            u8  unknown10:2,
                cw_speed:6;
            u8  disable_amfm_dial:1,
                vox_gain:7;
            u8  cat_rate:2,
                emergency:1,
                vox_delay:5;
            u8  dig_mode:3,
                mem_group:1,
                unknown11:1,
                apo_time:3;
            u8  dcs_inv:2,
                unknown12:1,
                tot_time:5;
            u8  mic_scan:1,
                ssb_mic:7;
            u8  cw_paddle:1,
                am_mic:7;
            u8  unknown13:1,
                fm_mic:7;
            u8  unknown14:1,
                dig_mic:7;
            u8  extended_menu:1,
                pkt1200:7;
            u8  unknown15:1,
                pkt9600:7;
            i16 dig_shift;
            i16 dig_disp;
            i8  r_lsb_car;
            i8  r_usb_car;
            i8  t_lsb_car;
            i8  t_usb_car;
            u8  unknown16:1,
                menu_item:7;
            u8  unknown17[5];
            u8  unknown18:1,
                mtr_peak_hold:1,
                mic_sel:2,
                cat_lin_tun:2,
                unknown19:1,
                split_tone:1;
            u8  unknown20:1,
                beep_vol:7;
            u8  unknown21:1,
                dig_vox:7;
            u8  ext_menu:1,
                home_vfo:1,
                scan_mode:2,
                scan_resume:4;
            u8  cw_auto_mode:1,
                cw_training:2,
                cw_qsk:3,
                cw_bfo:2;
            u8  dsp_nr:4,
                dsp_bpf:2,
                dsp_mic_eq:2;
            u8  unknown22:3,
                dsp_lpf:5;
            u8  mtr_atx_sel:3,
                unknown23:1,
                dsp_hpf:4;
            u8  unknown24:2,
                disp_intensity:2,
                unknown25:1,
                disp_color:3;
            u8  unknown26:1,
                disp_color_vfo:1,
                disp_color_mtr:1,
                disp_color_mode:1,
                disp_color_memgrp:1,
                unknown27:1,
                disp_color_band:1,
                disp_color_arts:1;
            u8  unknown28:3,
                disp_color_fix:5;
            u8  unknown29:1,
                nb_level:7;
            u8  unknown30:1,
                proc_level:7;
            u8  unknown31:1,
                rf_power_hf:7;
            u8  unknown32:2,
                tuner_atas:3,
                mem_vfo_dial_mode:3;
            u8  pg_a;
            u8  pg_b;
            u8  pg_c;
            u8  pg_acc;
            u8  pg_p1;
            u8  pg_p2;
            u8  unknown33:3,
                xvtr_sel:2,
                unknown33_1:2,
                op_filter1:1;
            u8  unknown34:6,
                tx_if_filter:2;
            u8  unknown35:3,
                xvtr_a_negative:1,
                xvtr_b_negative:1,
                mtr_arx_sel:3;
            u8  beacon_time;
            u8  unknown36[2];
            u8  dig_vox_enable:1,
                unknown37:2,
                scope_peakhold:1,
                scope_width:2,
                proc:1,
                unknown38:1;
            u8  unknown39:1,
                rf_power_6m:7;
            u8  unknown40:1,
                rf_power_vhf:7;
            u8  unknown41:1,
                rf_power_uhf:7;
        } settings;

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

        #seekto 0x1bf3;
        u8 arts_idw[10];
        u8 beacon_text1[40];
        u8 beacon_text2[40];
        u8 beacon_text3[40];
        u32 xvtr_a_offset;
        u32 xvtr_b_offset;
        u8 op_filter1_name[4];
        u8 op_filter2_name[4];

        #seekto 0x1CAD;
        struct mem_struct sixtymeterchannels[5];

    """

    _CALLSIGN_CHARSET = [chr(x) for x in range(ord("0"), ord("9") + 1) +
                         range(ord("A"), ord("Z") + 1)] + [" ", "/"]
    _CALLSIGN_CHARSET_REV = dict(zip(_CALLSIGN_CHARSET,
                                 range(0, len(_CALLSIGN_CHARSET))))
    _BEACON_CHARSET = _CALLSIGN_CHARSET + ["+", "."]
    _BEACON_CHARSET_REV = dict(zip(_BEACON_CHARSET,
                               range(0, len(_BEACON_CHARSET))))

    # WARNING Index are hard wired in memory management code !!!
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
        "VFOb-144M": -8,
        "VFOb-430M": -7,
        "VFOb-HF": -6,
        "HOME HF": -5,
        "HOME 50M": -4,
        "HOME 144M": -3,
        "HOME 430M": -2,
        "QMB": -1,
    }
    FIRST_VFOB_INDEX = -6
    LAST_VFOB_INDEX = -21
    FIRST_VFOA_INDEX = -22
    LAST_VFOA_INDEX = -37

    SPECIAL_PMS = {
        "PMS-1L": -47,
        "PMS-1U": -46,
        "PMS-2L": -45,
        "PMS-2U": -44,
        "PMS-3L": -43,
        "PMS-3U": -42,
        "PMS-4L": -41,
        "PMS-4U": -40,
        "PMS-5L": -39,
        "PMS-5U": -38,
    }
    LAST_PMS_INDEX = -47

    SPECIAL_MEMORIES.update(SPECIAL_PMS)

    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))

    FILTERS = ["CFIL", "FIL1", "FIL2"]
    PROGRAMMABLEOPTIONS = [
        "MFa:A/B",              "MFa:A=B",          "MFa:SPL",
        "MFb:MW",               "MFb:SKIP/MCLR",    "MFb:TAG",
        "MFc:STO",              "MFc:RCL",          "MFc:PROC",
        "MFd:RPT",              "MFd:REV",          "MFd:VOX",
        "MFe:TON/ENC",          "MFe:TON/DEC",      "MFe:TDCH",
        "MFf:ARTS",             "MFf:SRCH",         "MFf:PMS",
        "MFg:SCN",              "MFg:PRI",          "MFg:DW",
        "MFh:SCOP",             "MFh:WID",          "MFh:STEP",
        "MFi:MTR",              "MFi:SWR",          "MFi:DISP",
        "MFj:SPOT",             "MFj:BK",           "MFj:KYR",
        "MFk:TUNE",             "MFk:DOWN",         "MFk:UP",
        "MFl:NB",               "MFl:AGC",          "MFl:AGC SEL",
        "MFm:IPO",              "MFm:ATT",          "MFm:NAR",
        "MFn:CFIL",             "MFn:FIL1",         "MFn:FIL2",
        "MFo:PLY1",             "MFo:PLY2",         "MFo:PLY3",
        "MFp:DNR",              "MFp:DNF",          "MFp:DBF",
        "01:EXT MENU",          "02:144MHz ARS",    "03:430MHz ARS",
        "04:AM&FM DIAL",        "05:AM MIC GAIN",   "06:AM STEP",
        "07:APO TIME",          "08:ARTS BEEP",     "09:ARTS ID",
        "10:ARTS IDW",          "11:BEACON TEXT",   "12:BEACON TIME",
        "13:BEEP TONE",         "14:BEEP VOL",      "15:CAR LSB R",
        "16:CAR LSB T",         "17:CAR USB R",     "18:CAR USB T",
        "19:CAT RATE",          "20:CAT/LIN/TUN",   "21:CLAR DIAL SEL",
        "22:CW AUTO MODE",      "23:CW BFO",        "24:CW DELAY",
        "25:CW KEY REV",        "26:CW PADDLE",     "27:CW PITCH",
        "28:CW QSK",            "29:CW SIDE TONE",  "30:CW SPEED",
        "31:CW TRAINING",       "32:CW WEIGHT",     "33:DCS CODE",
        "34:DCS INV",           "35:DIAL STEP",     "36:DIG DISP",
        "37:DIG GAIN",          "38:DIG MODE",      "39:DIG SHIFT",
        "40:DIG VOX",           "41:DISP COLOR",    "42:DISP CONTRAST",
        "43:DISP INTENSITY",    "44:DISP MODE",     "45:DSP BPF WIDTH",
        "46:DSP HPF CUTOFF",    "47:DSP LPF CUTOFF", "48:DSP MIC EQ",
        "49:DSP NR LEVEL",      "50:EMERGENCY",     "51:FM MIC GAIN",
        "52:FM STEP",           "53:HOME->VFO",     "54:LOCK MODE",
        "55:MEM GROUP",         "56:MEM TAG",       "57:MEM/VFO DIAL MODE",
        "58:MIC SCAN",          "59:MIC SEL",       "60:MTR ARX",
        "61:MTR ATX",           "62:MTR PEAK HOLD", "63:NB LEVEL",
        "64:OP FILTER",         "71:PKT 1200",      "72:PKT 9600",
        "73:PKT RATE",          "74:PROC LEVEL",    "75:RF POWER SET",
        "76:RPT SHIFT",         "77:SCAN MODE",     "78:SCAN RESUME",
        "79:SPLIT TONE",        "80:SQL/RF GAIN",   "81:SSB MIC GAIN",
        "82:SSB STEP",          "83:TONE FREQ",     "84:TX TIME",
        "85:TUNER/ATAS",        "86:TX IF FILTER",  "87:VOX DELAY",
        "88:VOX GAIN",          "89:XVTR A FREQ",   "90:XVTR B FREQ",
        "91:XVTR SEL",
        "MONI", "Q.SPL", "TCALL", "ATC", "USER"]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to CAT/LINEAR jack.
            3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys while
                 turning the radio on ("CLONE MODE" will appear on the
                 display).
            4. <b>After clicking OK</b>,
                 press the [C](SEND) key to send image."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to ACC jack.
            3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys while
                 turning the radio on ("CLONE MODE" will appear on the
                 display).
            4. Press the [A](RCV) key ("receiving" will appear on the LCD)."""
                                 ))
        return rp

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
        elif mem.tmode == "DTCS Enc":   # UI does not support it yet but
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
        elif mem.tmode == "DTCS Enc":   # UI does not support it yet but
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

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        cw = RadioSettingGroup("cw", "CW")
        packet = RadioSettingGroup("packet", "Digital & packet")
        panel = RadioSettingGroup("panel", "Panel settings")
        extended = RadioSettingGroup("extended", "Extended")
        panelcontr = RadioSettingGroup("panelcontr", "Panel controls")

        top = RadioSettings(basic, cw, packet,
                            panelcontr, panel, extended)

        rs = RadioSetting("extended_menu", "Extended menu",
                          RadioSettingValueBoolean(_settings.extended_menu))
        extended.append(rs)
        rs = RadioSetting("ars_144", "144MHz ARS",
                          RadioSettingValueBoolean(_settings.ars_144))
        basic.append(rs)
        rs = RadioSetting("ars_430", "430MHz ARS",
                          RadioSettingValueBoolean(_settings.ars_430))
        basic.append(rs)
        options = ["enable", "disable"]
        rs = RadioSetting("disable_amfm_dial", "AM&FM Dial",
                          RadioSettingValueList(options,
                                                options[
                                                    _settings.disable_amfm_dial
                                                        ]))
        panel.append(rs)
        rs = RadioSetting("am_mic", "AM mic gain",
                          RadioSettingValueInteger(0, 100, _settings.am_mic))
        basic.append(rs)
        options = ["OFF", "1h", "2h", "3h", "4h", "5h", "6h"]
        rs = RadioSetting("apo_time", "APO time",
                          RadioSettingValueList(options,
                                                options[_settings.apo_time]))
        basic.append(rs)
        options = ["OFF", "Range", "All"]
        rs = RadioSetting("arts_beep", "ARTS beep",
                          RadioSettingValueList(options,
                                                options[_settings.arts_beep]))
        basic.append(rs)
        rs = RadioSetting("arts_id", "ARTS ID",
                          RadioSettingValueBoolean(_settings.arts_id))
        extended.append(rs)
        st = RadioSettingValueString(0, 10,
                                     safe_charset_string(
                                         self._memobj.arts_idw,
                                         self._CALLSIGN_CHARSET)
                                     )
        st.set_charset(self._CALLSIGN_CHARSET)
        rs = RadioSetting("arts_idw", "ARTS IDW", st)
        extended.append(rs)
        st = RadioSettingValueString(0, 40,
                                     safe_charset_string(
                                         self._memobj.beacon_text1,
                                         self._BEACON_CHARSET)
                                     )
        st.set_charset(self._BEACON_CHARSET)
        rs = RadioSetting("beacon_text1", "Beacon text1", st)
        extended.append(rs)
        st = RadioSettingValueString(0, 40,
                                     safe_charset_string(
                                         self._memobj.beacon_text2,
                                         self._BEACON_CHARSET)
                                     )
        st.set_charset(self._BEACON_CHARSET)
        rs = RadioSetting("beacon_text2", "Beacon text2", st)
        extended.append(rs)
        st = RadioSettingValueString(0, 40,
                                     safe_charset_string(
                                         self._memobj.beacon_text3,
                                         self._BEACON_CHARSET)
                                     )
        st.set_charset(self._BEACON_CHARSET)
        rs = RadioSetting("beacon_text3", "Beacon text3", st)
        extended.append(rs)
        options = ["OFF"] + ["%i sec" % i for i in range(1, 256)]
        rs = RadioSetting("beacon_time", "Beacon time",
                          RadioSettingValueList(options,
                                                options[_settings.beacon_time])
                          )
        extended.append(rs)
        options = ["440Hz", "880Hz", "1760Hz"]
        rs = RadioSetting("beep_tone", "Beep tone",
                          RadioSettingValueList(options,
                                                options[_settings.beep_tone]))
        panel.append(rs)
        rs = RadioSetting("beep_vol", "Beep volume",
                          RadioSettingValueInteger(0, 100, _settings.beep_vol))
        panel.append(rs)
        rs = RadioSetting("r_lsb_car", "LSB Rx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.r_lsb_car))
        extended.append(rs)
        rs = RadioSetting("r_usb_car", "USB Rx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.r_usb_car))
        extended.append(rs)
        rs = RadioSetting("t_lsb_car", "LSB Tx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.t_lsb_car))
        extended.append(rs)
        rs = RadioSetting("t_usb_car", "USB Tx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.t_usb_car))
        extended.append(rs)
        options = ["4800", "9600", "38400"]
        rs = RadioSetting("cat_rate", "CAT rate",
                          RadioSettingValueList(options,
                                                options[_settings.cat_rate]))
        basic.append(rs)
        options = ["CAT", "Linear", "Tuner"]
        rs = RadioSetting("cat_lin_tun", "CAT/LIN/TUN selection",
                          RadioSettingValueList(options,
                                                options[_settings.cat_lin_tun])
                          )
        extended.append(rs)
        options = ["MAIN", "VFO/MEM", "CLAR"]
        # TODO test the 3 options on non D radio
        # which have only SEL and MAIN
        rs = RadioSetting("clar_dial_sel", "Clarifier dial selection",
                          RadioSettingValueList(options,
                                                options[
                                                    _settings.clar_dial_sel]))
        panel.append(rs)
        rs = RadioSetting("cw_auto_mode", "CW Automatic mode",
                          RadioSettingValueBoolean(_settings.cw_auto_mode))
        cw.append(rs)
        options = ["USB", "LSB", "AUTO"]
        rs = RadioSetting("cw_bfo", "CW BFO",
                          RadioSettingValueList(options,
                                                options[_settings.cw_bfo]))
        cw.append(rs)
        options = ["FULL"] + ["%i ms" % (i * 10) for i in range(3, 301)]
        val = (_settings.cw_delay + _settings.cw_delay_hi * 256) - 2
        rs = RadioSetting("cw_delay", "CW delay",
                          RadioSettingValueList(options, options[val]))
        cw.append(rs)
        options = ["Normal", "Reverse"]
        rs = RadioSetting("cw_key_rev", "CW key reverse",
                          RadioSettingValueList(options,
                                                options[_settings.cw_key_rev]))
        cw.append(rs)
        rs = RadioSetting("cw_paddle", "CW paddle",
                          RadioSettingValueBoolean(_settings.cw_paddle))
        cw.append(rs)
        options = ["%i Hz" % i for i in range(400, 801, 100)]
        rs = RadioSetting("cw_pitch", "CW pitch",
                          RadioSettingValueList(options,
                                                options[_settings.cw_pitch]))
        cw.append(rs)
        options = ["%i ms" % i for i in range(5, 31, 5)]
        rs = RadioSetting("cw_qsk", "CW QSK",
                          RadioSettingValueList(options,
                                                options[_settings.cw_qsk]))
        cw.append(rs)
        rs = RadioSetting("cw_sidetone", "CW sidetone volume",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.cw_sidetone))
        cw.append(rs)
        options = ["%i wpm" % i for i in range(4, 61)]
        rs = RadioSetting("cw_speed", "CW speed",
                          RadioSettingValueList(options,
                                                options[_settings.cw_speed]))
        cw.append(rs)
        options = ["Numeric", "Alphabet", "AlphaNumeric"]
        rs = RadioSetting("cw_training", "CW trainig",
                          RadioSettingValueList(options,
                                                options[_settings.cw_training])
                          )
        cw.append(rs)
        options = ["1:%1.1f" % (i / 10) for i in range(25, 46, 1)]
        rs = RadioSetting("cw_weight", "CW weight",
                          RadioSettingValueList(options,
                                                options[_settings.cw_weight]))
        cw.append(rs)
        options = ["Tn-Rn", "Tn-Riv", "Tiv-Rn", "Tiv-Riv"]
        rs = RadioSetting("dcs_inv", "DCS inv",
                          RadioSettingValueList(options,
                                                options[_settings.dcs_inv]))
        extended.append(rs)
        options = ["Fine", "Coarse"]
        rs = RadioSetting("dial_step", "Dial step",
                          RadioSettingValueList(options,
                                                options[_settings.dial_step]))
        panel.append(rs)
        rs = RadioSetting("dig_disp", "Dig disp (*10 Hz)",
                          RadioSettingValueInteger(-300, 300,
                                                   _settings.dig_disp))
        packet.append(rs)
        rs = RadioSetting("dig_mic", "Dig gain",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.dig_mic))
        packet.append(rs)
        options = ["RTTYL", "RTTYU", "PSK31-L", "PSK31-U", "USER-L", "USER-U"]
        rs = RadioSetting("dig_mode", "Dig mode",
                          RadioSettingValueList(options,
                                                options[_settings.dig_mode]))
        packet.append(rs)
        rs = RadioSetting("dig_shift", "Dig shift (*10 Hz)",
                          RadioSettingValueInteger(-300, 300,
                                                   _settings.dig_shift))
        packet.append(rs)
        rs = RadioSetting("dig_vox", "Dig vox",
                          RadioSettingValueInteger(0, 100, _settings.dig_vox))
        packet.append(rs)
        options = ["ARTS", "BAND", "FIX", "MEMGRP", "MODE", "MTR", "VFO"]
        rs = RadioSetting("disp_color", "Display color mode",
                          RadioSettingValueList(options,
                                                options[_settings.disp_color]))
        panel.append(rs)
        rs = RadioSetting("disp_color_arts", "Display color ARTS set",
                          RadioSettingValueInteger(0, 1,
                                                   _settings.disp_color_arts))
        panel.append(rs)
        rs = RadioSetting("disp_color_band", "Display color band set",
                          RadioSettingValueInteger(0, 1,
                                                   _settings.disp_color_band))
        panel.append(rs)
        rs = RadioSetting("disp_color_memgrp",
                          "Display color memory group set",
                          RadioSettingValueInteger(0, 1,
                                                   _settings.disp_color_memgrp)
                          )
        panel.append(rs)
        rs = RadioSetting("disp_color_mode", "Display color mode set",
                          RadioSettingValueInteger(0, 1,
                                                   _settings.disp_color_mode))
        panel.append(rs)
        rs = RadioSetting("disp_color_mtr", "Display color meter set",
                          RadioSettingValueInteger(0, 1,
                                                   _settings.disp_color_mtr))
        panel.append(rs)
        rs = RadioSetting("disp_color_vfo", "Display color VFO set",
                          RadioSettingValueInteger(0, 1,
                                                   _settings.disp_color_vfo))
        panel.append(rs)
        rs = RadioSetting("disp_color_fix", "Display color fix set",
                          RadioSettingValueInteger(1, 32,
                                                   _settings.disp_color_fix + 1
                                                   ))
        panel.append(rs)
        rs = RadioSetting("disp_contrast", "Contrast",
                          RadioSettingValueInteger(3, 15,
                                                   _settings.disp_contrast + 2)
                          )
        panel.append(rs)
        rs = RadioSetting("disp_intensity", "Intensity",
                          RadioSettingValueInteger(1, 3,
                                                   _settings.disp_intensity))
        panel.append(rs)
        options = ["OFF", "Auto1", "Auto2", "ON"]
        rs = RadioSetting("disp_mode", "Display backlight mode",
                          RadioSettingValueList(options,
                                                options[_settings.disp_mode]))
        panel.append(rs)
        options = ["60Hz", "120Hz", "240Hz"]
        rs = RadioSetting("dsp_bpf", "Dsp band pass filter",
                          RadioSettingValueList(options,
                                                options[_settings.dsp_bpf]))
        cw.append(rs)
        options = ["100Hz", "160Hz", "220Hz", "280Hz", "340Hz", "400Hz",
                   "460Hz", "520Hz", "580Hz", "640Hz", "720Hz", "760Hz",
                   "820Hz", "880Hz", "940Hz", "1000Hz"]
        rs = RadioSetting("dsp_hpf", "Dsp hi pass filter cut off",
                          RadioSettingValueList(options,
                                                options[_settings.dsp_hpf]))
        basic.append(rs)
        options = ["1000Hz", "1160Hz", "1320Hz", "1480Hz", "1650Hz", "1800Hz",
                   "1970Hz", "2130Hz", "2290Hz", "2450Hz", "2610Hz", "2770Hz",
                   "2940Hz", "3100Hz", "3260Hz", "3420Hz", "3580Hz", "3740Hz",
                   "3900Hz", "4060Hz", "4230Hz", "4390Hz", "4550Hz", "4710Hz",
                   "4870Hz", "5030Hz", "5190Hz", "5390Hz", "5520Hz", "5680Hz",
                   "5840Hz", "6000Hz"]
        rs = RadioSetting("dsp_lpf", "Dsp low pass filter cut off",
                          RadioSettingValueList(options,
                                                options[_settings.dsp_lpf]))
        basic.append(rs)
        options = ["OFF", "LPF", "HPF", "BOTH"]
        rs = RadioSetting("dsp_mic_eq", "Dsp mic equalization",
                          RadioSettingValueList(options,
                                                options[_settings.dsp_mic_eq]))
        basic.append(rs)
        rs = RadioSetting("dsp_nr", "DSP noise reduction level",
                          RadioSettingValueInteger(1, 16,
                                                   _settings.dsp_nr + 1))
        basic.append(rs)
        # emergency only for US model
        rs = RadioSetting("fm_mic", "FM mic gain",
                          RadioSettingValueInteger(0, 100, _settings.fm_mic))
        basic.append(rs)
        rs = RadioSetting("home_vfo", "Enable HOME to VFO moving",
                          RadioSettingValueBoolean(_settings.home_vfo))
        panel.append(rs)
        options = ["Dial", "Freq", "Panel", "All"]
        rs = RadioSetting("lock_mode", "Lock mode",
                          RadioSettingValueList(options,
                                                options[_settings.lock_mode]))
        panel.append(rs)
        rs = RadioSetting("mem_group", "Mem group",
                          RadioSettingValueBoolean(_settings.mem_group))
        basic.append(rs)
        options = ["CW SIDETONE", "CW SPEED", "MHz/MEM GRP", "MIC GAIN",
                   "NB LEVEL", "RF POWER", "STEP"]
        rs = RadioSetting("mem_vfo_dial_mode", "Mem/VFO dial mode",
                          RadioSettingValueList(options,
                                                options[
                                                    _settings.mem_vfo_dial_mode
                                                       ]))
        panel.append(rs)
        rs = RadioSetting("mic_scan", "Mic scan",
                          RadioSettingValueBoolean(_settings.mic_scan))
        basic.append(rs)
        options = ["NOR", "RMT", "CAT"]
        rs = RadioSetting("mic_sel", "Mic selection",
                          RadioSettingValueList(options,
                                                options[_settings.mic_sel]))
        extended.append(rs)
        options = ["SIG", "CTR", "VLT", "N/A", "FS", "OFF"]
        rs = RadioSetting("mtr_arx_sel", "Meter receive selection",
                          RadioSettingValueList(options,
                                                options[_settings.mtr_arx_sel])
                          )
        extended.append(rs)
        options = ["PWR", "ALC", "MOD", "SWR", "VLT", "N/A", "OFF"]
        rs = RadioSetting("mtr_atx_sel", "Meter transmit selection",
                          RadioSettingValueList(options,
                                                options[_settings.mtr_atx_sel])
                          )
        extended.append(rs)
        rs = RadioSetting("mtr_peak_hold", "Meter peak hold",
                          RadioSettingValueBoolean(_settings.mtr_peak_hold))
        extended.append(rs)
        rs = RadioSetting("nb_level", "Noise blanking level",
                          RadioSettingValueInteger(0, 100, _settings.nb_level))
        basic.append(rs)
        st = RadioSettingValueString(0, 4,
                                     safe_charset_string(
                                         self._memobj.op_filter1_name,
                                         self._CALLSIGN_CHARSET)
                                     )
        st.set_charset(self._CALLSIGN_CHARSET)
        rs = RadioSetting("op_filter1_name", "Optional filter1 name", st)
        extended.append(rs)
        st = RadioSettingValueString(0, 4,
                                     safe_charset_string(
                                         self._memobj.op_filter2_name,
                                         self._CALLSIGN_CHARSET)
                                     )
        st.set_charset(self._CALLSIGN_CHARSET)
        rs = RadioSetting("op_filter2_name", "Optional filter2 name", st)
        extended.append(rs)
        rs = RadioSetting("pg_a", "Programmable key MFq:A",
                          RadioSettingValueList(self.PROGRAMMABLEOPTIONS,
                                                self.PROGRAMMABLEOPTIONS[
                                                    _settings.pg_a]))
        extended.append(rs)
        rs = RadioSetting("pg_b", "Programmable key MFq:B",
                          RadioSettingValueList(self.PROGRAMMABLEOPTIONS,
                                                self.PROGRAMMABLEOPTIONS[
                                                    _settings.pg_b]))
        extended.append(rs)
        rs = RadioSetting("pg_c", "Programmable key MFq:C",
                          RadioSettingValueList(self.PROGRAMMABLEOPTIONS,
                                                self.PROGRAMMABLEOPTIONS[
                                                    _settings.pg_c]))
        extended.append(rs)
        rs = RadioSetting("pg_acc", "Programmable mic key ACC",
                          RadioSettingValueList(self.PROGRAMMABLEOPTIONS,
                                                self.PROGRAMMABLEOPTIONS[
                                                    _settings.pg_acc]))
        extended.append(rs)
        rs = RadioSetting("pg_p1", "Programmable mic key P1",
                          RadioSettingValueList(self.PROGRAMMABLEOPTIONS,
                                                self.PROGRAMMABLEOPTIONS[
                                                    _settings.pg_p1]))
        extended.append(rs)
        rs = RadioSetting("pg_p2", "Programmable mic key P2",
                          RadioSettingValueList(self.PROGRAMMABLEOPTIONS,
                                                self.PROGRAMMABLEOPTIONS[
                                                    _settings.pg_p2]))
        extended.append(rs)
        rs = RadioSetting("pkt1200", "Packet 1200 gain level",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.pkt1200))
        packet.append(rs)
        rs = RadioSetting("pkt9600", "Packet 9600 gain level",
                          RadioSettingValueInteger(0, 100, _settings.pkt9600))
        packet.append(rs)
        options = ["1200", "9600"]
        rs = RadioSetting("pkt_rate", "Packet rate",
                          RadioSettingValueList(options,
                                                options[_settings.pkt_rate]))
        packet.append(rs)
        rs = RadioSetting("proc_level", "Proc level",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.proc_level))
        basic.append(rs)
        rs = RadioSetting("rf_power_hf", "Rf power set HF",
                          RadioSettingValueInteger(5, 100,
                                                   _settings.rf_power_hf))
        basic.append(rs)
        rs = RadioSetting("rf_power_6m", "Rf power set 6m",
                          RadioSettingValueInteger(5, 100,
                                                   _settings.rf_power_6m))
        basic.append(rs)
        rs = RadioSetting("rf_power_vhf", "Rf power set VHF",
                          RadioSettingValueInteger(5, 50,
                                                   _settings.rf_power_vhf))
        basic.append(rs)
        rs = RadioSetting("rf_power_uhf", "Rf power set UHF",
                          RadioSettingValueInteger(2, 20,
                                                   _settings.rf_power_uhf))
        basic.append(rs)
        options = ["TIME", "BUSY", "STOP"]
        rs = RadioSetting("scan_mode", "Scan mode",
                          RadioSettingValueList(options,
                                                options[_settings.scan_mode]))
        basic.append(rs)
        rs = RadioSetting("scan_resume", "Scan resume",
                          RadioSettingValueInteger(1, 10,
                                                   _settings.scan_resume))
        basic.append(rs)
        rs = RadioSetting("split_tone", "Split tone enable",
                          RadioSettingValueBoolean(_settings.split_tone))
        extended.append(rs)
        options = ["RF-Gain", "Squelch"]
        rs = RadioSetting("sql_rf_gain", "Squelch/RF-Gain",
                          RadioSettingValueList(options,
                                                options[_settings.sql_rf_gain])
                          )
        panel.append(rs)
        rs = RadioSetting("ssb_mic", "SSB Mic gain",
                          RadioSettingValueInteger(0, 100, _settings.ssb_mic))
        basic.append(rs)
        options = ["Off"] + ["%i" % i for i in range(1, 21)]
        rs = RadioSetting("tot_time", "Time-out timer",
                          RadioSettingValueList(options,
                                                options[_settings.tot_time]))
        basic.append(rs)
        options = ["OFF", "ATAS(HF)", "ATAS(HF&50)", "ATAS(ALL)", "TUNER"]
        rs = RadioSetting("tuner_atas", "Tuner/ATAS device",
                          RadioSettingValueList(options,
                                                options[_settings.tuner_atas]))
        extended.append(rs)
        rs = RadioSetting("tx_if_filter", "Transmit IF filter",
                          RadioSettingValueList(self.FILTERS,
                                                self.FILTERS[
                                                    _settings.tx_if_filter]))
        basic.append(rs)
        rs = RadioSetting("vox_delay", "VOX delay (*100 ms)",
                          RadioSettingValueInteger(1, 30, _settings.vox_delay))
        basic.append(rs)
        rs = RadioSetting("vox_gain", "VOX Gain",
                          RadioSettingValueInteger(1, 100, _settings.vox_gain))
        basic.append(rs)
        rs = RadioSetting("xvtr_a", "Xvtr A displacement",
                          RadioSettingValueInteger(
                              -4294967295, 4294967295,
                              self._memobj.xvtr_a_offset *
                              (-1 if _settings.xvtr_a_negative else 1)))

        extended.append(rs)
        rs = RadioSetting("xvtr_b", "Xvtr B displacement",
                          RadioSettingValueInteger(
                              -4294967295, 4294967295,
                              self._memobj.xvtr_b_offset *
                              (-1 if _settings.xvtr_b_negative else 1)))
        extended.append(rs)
        options = ["OFF", "XVTR A", "XVTR B"]
        rs = RadioSetting("xvtr_sel", "Transverter function selection",
                          RadioSettingValueList(options,
                                                options[_settings.xvtr_sel]))
        extended.append(rs)

        rs = RadioSetting("disp", "Display large",
                          RadioSettingValueBoolean(_settings.disp))
        panel.append(rs)
        rs = RadioSetting("nb", "Noise blanker",
                          RadioSettingValueBoolean(_settings.nb))
        panelcontr.append(rs)
        options = ["Auto", "Fast", "Slow", "Off"]
        rs = RadioSetting("agc", "AGC",
                          RadioSettingValueList(options,
                                                options[_settings.agc]))
        panelcontr.append(rs)
        options = ["PWR", "ALC", "SWR", "MOD"]
        rs = RadioSetting("pwr_meter_mode", "Power meter mode",
                          RadioSettingValueList(options,
                                                options[
                                                    _settings.pwr_meter_mode]))
        panelcontr.append(rs)
        rs = RadioSetting("vox", "Vox",
                          RadioSettingValueBoolean(_settings.vox))
        panelcontr.append(rs)
        rs = RadioSetting("bk", "Semi break-in",
                          RadioSettingValueBoolean(_settings.bk))
        cw.append(rs)
        rs = RadioSetting("kyr", "Keyer",
                          RadioSettingValueBoolean(_settings.kyr))
        cw.append(rs)
        options = ["enabled", "disabled"]
        rs = RadioSetting("fst", "Fast",
                          RadioSettingValueList(options, options[_settings.fst]
                                                ))
        panelcontr.append(rs)
        options = ["enabled", "disabled"]
        rs = RadioSetting("lock", "Lock",
                          RadioSettingValueList(options,
                                                options[_settings.lock]))
        panelcontr.append(rs)
        rs = RadioSetting("scope_peakhold", "Scope max hold",
                          RadioSettingValueBoolean(_settings.scope_peakhold))
        panelcontr.append(rs)
        options = ["21", "31", "127"]
        rs = RadioSetting("scope_width", "Scope width (channels)",
                          RadioSettingValueList(options,
                                                options[_settings.scope_width])
                          )
        panelcontr.append(rs)
        rs = RadioSetting("proc", "Speech processor",
                          RadioSettingValueBoolean(_settings.proc))
        panelcontr.append(rs)

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                if "." in element.get_name():
                    bits = element.get_name().split(".")
                    obj = self._memobj
                    for bit in bits[:-1]:
                        obj = getattr(obj, bit)
                    setting = bits[-1]
                else:
                    obj = _settings
                    setting = element.get_name()
                try:
                    LOG.debug("Setting %s(%s) <= %s" % (setting,
                              getattr(obj, setting), element.value))
                except AttributeError:
                    LOG.debug("Setting %s <= %s" % (setting, element.value))
                if setting == "arts_idw":
                    self._memobj.arts_idw = \
                        [self._CALLSIGN_CHARSET_REV[x]
                         for x in str(element.value)]
                elif setting in ["beacon_text1", "beacon_text2",
                                 "beacon_text3", "op_filter1_name",
                                 "op_filter2_name"]:
                    setattr(self._memobj, setting,
                            [self._BEACON_CHARSET_REV[x]
                             for x in str(element.value)])
                elif setting == "cw_delay":
                    val = int(element.value) + 2
                    setattr(obj, "cw_delay_hi", val / 256)
                    setattr(obj, setting, val & 0xff)
                elif setting == "dig_vox":
                    val = int(element.value)
                    setattr(obj, "dig_vox_enable", int(val > 0))
                    setattr(obj, setting, val)
                elif setting in ["disp_color_fix", "dsp_nr"]:
                    setattr(obj, setting, int(element.value) - 1)
                elif setting == "disp_contrast":
                    setattr(obj, setting, int(element.value) - 2)
                elif setting in ["xvtr_a", "xvtr_b"]:
                    val = int(element.value)
                    setattr(obj, setting + "_negative", int(val < 0))
                    setattr(self._memobj, setting + "_offset", abs(val))
                else:
                    setattr(obj, setting, element.value)
            except:
                LOG.debug(element.get_name())
                raise


@directory.register
class FT857USRadio(FT857Radio):
    """Yaesu FT857/897 (US version)"""
    # seems that radios configured for 5MHz operations send one paket more
    # than others so we have to distinguish sub models
    MODEL = "FT-857/897 (US)"

    _model = ""
    _US_model = True
    _memsize = 7481
    # block 9 (140 Bytes long) is to be repeted 40 times
    # should be 42 times but this way I can use original 817 functions
    _block_lengths = [2, 82, 252, 196, 252, 196, 212, 55, 140, 140, 140, 38,
                      176, 140]

    SPECIAL_60M = {
        "M-601": -52,
        "M-602": -51,
        "M-603": -50,
        "M-604": -49,
        "M-605": -48,
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

        mem.immutable = ["number", "rtone", "ctone",
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

    def get_settings(self):
        top = FT857Radio.get_settings(self)
        basic = top[0]
        rs = RadioSetting("emergency", "Emergency",
                          RadioSettingValueBoolean(
                              self._memobj.settings.emergency))
        basic.append(rs)
        return top
