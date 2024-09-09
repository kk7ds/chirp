# Copyright 2022 Mel Terechenok <melvin.terechenok@gmail.com>
# KG-UV980P , KG-1000G, KG-1000G Plus unified driver using
# KG-935G, KG-UV8H, KG-UV920P, and KG-UV9D Plus drivers as resources
#
# Based on the previous work of Pavel Milanes CO7WT <pavelmc@gmail.com>
# and Krystian Struzik <toner_82@tlen.pl>
# who figured out the crypt used and made possible the
# Wuoxun KG-UV8D Plus driver.
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

"""Wouxun KG-UV980P radio management module"""

import time
import logging
import struct

from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettingValueMap, RadioSettings


LOG = logging.getLogger(__name__)


CMD_ID = 0x80
CMD_END = 0x81
CMD_RD = 0x82
CMD_WR = 0x83
DIR_TO = 0xFF
DIR_FROM = 0x00


# This is used to write the configuration of the radio base on info
# gleaned from the downloaded app. There are empty spaces and we honor
# them because we don't know what they are (yet) although we read the
# whole of memory.
# Max Write Size = 64 for comm protocol

config_map = (          # map address, write size, write count
    # (0x0, 64, 512),     # 0 to 8000 - full write use only
    (0x4c,  12, 1),    # Mode PSW --  Display name
    (0x60,  16, 3),    # Freq Limits
    (0x740,  40, 1),    # FM chan 1-20
    (0x830,  16, 13),    # General settings
    (0x900, 8, 1),       # General settings
    (0x940,  64, 2),    # Scan groups and names
    (0xa00,  64, 249),  # Memory Channels 1-996
    (0x4840, 48, 1),    # Memory Channels 997-999
    (0x4900, 64, 124),  # Memory Names    1-992
    (0x6800, 8, 7),    # Memory Names    997-999
    (0x7000, 64, 15),    # mem valid 1 -960
    (0x73c0, 39, 1),    # mem valid 961 - 999
)


MEM_VALID = 0x00
MEM_INVALID = [0x80]
TX_BLANK = 0x40
RX_BLANK = 0x80

CHARSET_NUMERIC = "0123456789"
CHARSET = "0123456789" + \
          ":;<=>?@" + \
          "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + \
          "[\\]^_`" + \
          "abcdefghijklmnopqrstuvwxyz" + \
          "{|}~\x4E" + \
          " !\"#$%&'()*+,-./"

SCANNAME_CHARSET = "0123456789" + \
          ":;<=>?@" + \
          "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + \
          "[\\]^_`" + \
          "abcdefghijklmnopqrstuvwxyz" + \
          "{|}~\x4E" + \
          " !\"#$%&'()*+,-./"

MUTE_MODE_MAP = [('QT',      0b01),
                 ('QT*DTMF', 0b10),
                 ('QT+DTMF', 0b11)]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 30.0, 50.0, 100.0]
STEP_LIST = [str(x) for x in STEPS]
SQL_LIST = [int(i) for i in range(0, 10)]
M_POWER_MAP = [('1 = 20W', 1),
               ('2 = 10W', 2)]
ROGER_LIST = ["Off", "BOT", "EOT", "Both"]
VOICE_MAP = [('Off', 0),
             ('Chinese', 1),
             ('On / English', 2)]
VOICE_MAP_1000GPLUS = [('Off', 0),
                       ('On', 2)]
SC_REV_MAP = [('Timeout (TO)',  1),
              ('Carrier (CO)',  2),
              ('Stop (SE)',     3)]
TOT_MAP = [('%d min' % i, int('%02d' % i, 10)) for i in range(1, 61)]
TOT_MAP_1000GPLUS = [('%d min' % i, int('%02d' % i, 16)) for i in range(1, 61)]
TOA_LIST = ["Off", "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s", "10s"]
TOA_MAP = [('Off', 0)] + \
          [('%ds' % i, int('%02d' % i, 16)) for i in range(1, 11)]
RING_LIST = ["Off", "1s", "2s", "3s", "4s", "5s", "6s", "7s",
             "8s", "9s", "10s"]
RING_MAP = [('Off', 0)] + \
           [('%ds' % i, int('%02d' % i, 10)) for i in range(1, 11)]
DTMF_ST_LIST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
DTMF_ST_LIST_1000GPLUS = ["Off", "DTMF", "ID", "DTMF+ID"]

PTT_ID_MAP = [('BOT',  1),
              ('EOT',  2),
              ('Both', 3)]
PTT_ID_MAP_1000GPLUS = [('Off', 0),
                        ('BOT',  1),
                        ('EOT',  2),
                        ('Both', 3)]
BACKLIGHT_LIST = ["Off", "Red", "Orange", "Green"]
SPEAKER_MAP = [('SPK_1',   1),
               ('SPK_2',   2),
               ('SPK_1+2', 3)]
SPEAKER_MAP_1000GPLUS = [('RADIO',   1),
                         ('MIC',   2),
                         ('BOTH', 3)]
RPT_MODE_LIST = ["Radio", "X-DIRPT", "X-TWRPT", "RPT-RX", "T-W RPT"]
RPT_MODE_MAP = [("OFF", 0),
                ("RPT-RX", 3),
                ("RPT-TX", 4)]
APO_TIME_LIST = ["Off", "30", "60", "90", "120", "150"]
ALERT_MAP = [('1750', 1),
             ('2100', 2),
             ('1000', 3),
             ('1450', 4)]
FAN_MODE_LIST = ["TX", "Hi-Temp/TX", "Always"]
SCAN_GROUP_LIST = ["All"] + ["%s" % x for x in range(1, 11)]
WORKMODE_MAP = [('VFO',             1),
                ('Ch. No.',         2),
                ('Ch. No.+Freq.',   3),
                ('Ch. No.+Name',    4)]
WORKMODE_MAP_1000GPLUS = [('Freq',   1),
                          ('Ch-Num',  2),
                          ('Ch-Freq', 3),
                          ('Ch-Name', 4)]

VFOBAND_MAP = [("150M", 0),
               ("450M", 1),
               ("20M", 2),
               ("50M", 3),
               ("350M", 4),
               ("850M", 5)]
AB_LIST = ["A", "B"]
POWER_MAP = [('Low', 0),
             ('Med', 1),
             ('Med2', 2),
             ('High', 3)]
BANDWIDTH_MAP = [('Narrow', 1),
                 ('Wide',  0)]
SCRAMBLER_LIST = ["Off", "1", "2", "3", "4", "5", "6", "7", "8"]
ANS_LIST = ["Off", "Normal", "Strong"]
DTMF_TIMES = [str(x) for x in range(80, 501, 20)]
DTMF_INTERVALS = [str(x) for x in range(60, 501, 20)]
ROGER_TIMES = [str(x) for x in range(20, 1001, 20)]
# For py3 compliance x/100 must be changed to x//100
PTT_ID_DELAY_MAP = [(str(x), x//100) for x in range(100, 1001, 100)]
ROGER_INTERVALS = ROGER_TIMES
TONE_MAP = [('Off', 0x0000)] + \
           [('%.1f' % tone, int(tone * 10)) for tone in chirp_common.TONES] + \
           [('DN%d' % tone, int(0x8000 + tone))
               for tone in chirp_common.DTCS_CODES] + \
           [('DI%d' % tone, int(0xC000 + tone))
               for tone in chirp_common.DTCS_CODES]
DUPLEX_LIST = ["Off", "Plus", "Minus"]
SC_QT_MAP = [("Decoder - Rx QT/DT MEM", 1), ("Encoder- Tx QT/DT MEM", 2),
             ("All- RxTx QT/DT MEM", 3)]
SC_QT_MAP_1000GPLUS = [("Rx", 1), ("Tx", 2),
                       ("Tx/Rx", 3)]

HOLD_TIMES = ["Off"] + ["%s" % x for x in range(100, 5001, 100)]
PF1_SETTINGS = ["Off", "Stun", "Kill", "Monitor", "Inspection"]
PF1_SETTINGS_1000GPLUS = ["OFF", "Reverse", "Pri-Sel", "Pri-Scan", "Squelch",
                          "TX PWR", "Scan", "Scan CTCSS",
                          "Scan DCS", "FM Radio", "Weather", "Ch-Add", "W-N",
                          "TDR", "WORKMODE", "Band", "Repeater", "Lock",
                          "Monitor"]

ABR_LIST = ["Always", "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s",
            "9s", "10s", "11s", "12s", "13s", "14s", "15s", "16s", "17s",
            "18s", "19s", "20s", "Off"]
KEY_LIST = ["Off", "B/SW", "MENCH", "H-M-L", "VFO/MR", "SET-D", "TDR",
            "SQL", "SCAN", "FM-Radio", "Scan CTCSS", "Scan DCS"]
KEY_LIST_1000GPLUS = ["OFF", "Reverse", "Pri-Sel", "Pri-Scan", "Squelch",
                      "TX PWR", "Scan", "Scan CTCSS", "Scan DCS",
                      "FM Radio", "Weather", "Ch-Add", "W-N", "TDR",
                      "WORKMODE", "Band", "Repeater", "Lock", "Monitor"]

RC_POWER_LIST = ["RC Stop", "RC Open"]
ACTIVE_AREA_LIST = ["Area A - Left", "Area B - Right"]
TDR_LIST = ["TDR ON", "TDR OFF"]
PRI_CH_SCAN_LIST = ["Off", "ON-Stby", "On-Always"]

# memory slot 0 is not used, start at 1 (so need 1000 slots, not 999)
# structure elements whose name starts with x are currently unidentified

_MEM_FORMAT = """
    #seekto 0x004c;
    struct {
        u24 mode_psw;
        u8  xunk04F;
        u8  display_name[8];
    } oem;

    #seekto 0x0060;
    struct {
        bbcd    limit_144M_ChA_rx_start[2];
        bbcd    limit_144M_ChA_rx_stop[2];
        bbcd    limit_70cm_rx_start[2];
        bbcd    limit_70cm_rx_stop[2];
        bbcd    limit_10m_rx_start[2];
        bbcd    limit_10m_rx_stop[2];
        bbcd    limit_6m_rx_start[2];
        bbcd    limit_6m_rx_stop[2];
        bbcd    limit_350M_rx_start[2];
        bbcd    limit_350M_rx_stop[2];
        bbcd    limit_850M_rx_start[2];
        bbcd    limit_850M_rx_stop[2];
        bbcd    limit_144M_tx_start[2];
        bbcd    limit_144M_tx_stop[2];
        bbcd    limit_70cm_tx_start[2];
        bbcd    limit_70cm_tx_stop[2];
        bbcd    limit_10m_tx_start[2];
        bbcd    limit_10m_tx_stop[2];
        bbcd    limit_6m_tx_start[2];
        bbcd    limit_6m_tx_stop[2];
        bbcd    limit_144M_ChB_rx_start[2];
        bbcd    limit_144M_ChB_rx_stop[2];
    } bandlimits;


    #seekto 0x0740;
    struct {
        u16    FM_radio1;
        u16    FM_radio2;
        u16    FM_radio3;
        u16    FM_radio4;
        u16    FM_radio5;
        u16    FM_radio6;
        u16    FM_radio7;
        u16    FM_radio8;
        u16    FM_radio9;
        u16    FM_radio10;
        u16    FM_radio11;
        u16    FM_radio12;
        u16    FM_radio13;
        u16    FM_radio14;
        u16    FM_radio15;
        u16    FM_radio16;
        u16    FM_radio17;
        u16    FM_radio18;
        u16    FM_radio19;
        u16    FM_radio20;
        u16    FM_radio21;
        u16    FM_radio22;
        u8  x76c_pad[196];
        u32  vfofreq1;     // 0x0830
        u32  vfoofst1;
        u16  txtone1;
        u16  rxtone1;
        u8  xunk83C_1:3,
            mute1:2,
            xunk83C_2:3;
        u8  xunk83d_1:1,
            xunk83d_2:1,
            xunk83d_3:1,
            power1:2,
            am_mode1:1,
            xunk83d_7:1,
            narrow1:1;
        u8  xunk83e:6,
            shft_dir1:2;
        u8  xunk83F:3,
            compander1:1,
            scrambler1:4;
        u32  vfofreq2;
        u32  vfoofst2;
        u16  txtone2;
        u16  rxtone2;
        u8  xunk84C_1:3,
            mute2:2,
            xunk84C_2:3;
        u8  xunk84d_1:1,
            xunk84d_2:1,
            xunk84d_3:1,
            power2:2,
            am_mode2:1,
            xunk84d_7:1,
            narrow2:1;
        u8  xunk84e:6,
            shft_dir2:2;
        u8  xunk84F:3,
            compander2:1,
            scrambler2:4;
        u32  vfofreq3;
        u32  vfoofst3;
        u16  txtone3;
        u16  rxtone3;
        u8  xunk85C_1:3,
            mute3:2,
            xunk85C_2:3;
        u8  xunk85d_1:1,
            xunk85d_2:1,
            xunk85d_3:1,
            power3:2,
            am_mode3:1,
            xunk85d_7:1,
            narrow3:1;
        u8  xunk85e:6,
            shft_dir3:2;
        u8  xunk85F:3,
            compander3:1,
            scrambler3:4;
        u32  vfofreq4;
        u32  vfoofst4;
        u16  txtone4;
        u16  rxtone4;
        u8  xunk86C_1:3,
            mute4:2,
            xunk86C_2:3;
        u8  xunk86d_1:1,
            xunk86d_2:1,
            xunk86d_3:1,
            power4:2,
            am_mode4:1,
            xunk86d_7:1,
            narrow4:1;
        u8  xunk86e:6,
            shft_dir4:2;
        u8  xunk86F:3,
            compander4:1,
            scrambler4:4;
        u32  vfofreq5;
        u32  vfoofst5;
        u16  txtone5;
        u16  rxtone5;
        u8  xunk87C_1:3,
            mute5:2,
            xunk87C_2:3;
        u8  xunk87d_1:1,
            xunk87d_2:1,
            xunk87d_3:1,
            power5:2,
            am_mode5:1,
            xunk87d_7:1,
            narrow5:1;
        u8  xunk87e:6,
            shft_dir5:2;
        u8  xunk87F:3,
            compander5:1,
            scrambler5:4;
        u32  vfofreq6;
        u32  vfoofst6;
        u16  txtone6;
        u16  rxtone6;
        u8  xunk88C_1:3,
            mute6:2,
            xunk88C_2:3;
        u8  xunk88d_1:1,
            xunk88d_2:1,
            xunk88d_3:1,
            power6:2,
            am_mode6:1,
            xunk88d_7:1,
            narrow6:1;
        u8  xunk88e:6,
            shft_dir6:2;
        u8  xunk8F:3,
            compander6:1,
            scrambler6:4;
        u32  vfofreq7;
        u32  vfoofst7;
        u16  txtone7;
        u16  rxtone7;
        u8  xunk89C_1:3,
            mute7:2,
            xunk89C_2:3;
        u8  xunk89d_1:1,
            xunk89d_2:1,
            xunk89d_3:1,
            power7:2,
            am_mode7:1,
            xunk89d_7:1,
            narrow7:1;
        u8  xunk89e:6,
            shft_dir7:2;
        u8  xunk89F:3,
            compander7:1,
            scrambler7:4;
        u8  x8a0;
        u16  vfochan_a;
        u8  x8a3;
        u16  vfochan_b;
        u16  pri_ch;
        u8  x8a8;
        u8  x8a9;
        u8  scan_a_act;
        u8  scan_b_act;
        u8  m_pwr;
        u8  hold_time_rpt;
        u8  spk_cont;
        u8  x8af;
        u8  rc_power;
        u8  voice;
        u8  tot;
        u8  toa;
        u8  roger;
        u8  sc_rev;
        u8  dtmfsf;
        u8  ptt_id;
        u8  ring;
        u8  ani_sw;
        u8  rc_sw;
        u8  alert;
        u8  bcl_a;
        u8  prich_sw;
        u8  x8bE;
        u8  ptt_id_dly;
        u8  menu;
        u8  x8c1;
        u8  beep;
        u8  key_lock;
        u8  x8c4;
        u8  tx_led;
        u8  wt_led;
        u8  rx_led;
        u8  act_area;
        u8  vfomode_a;
        u8  vfomode_b;
        u8  vfosquelch_a;
        u8  vfosquelch_b;
        u8  vfostep_a;
        u8  vfostep_b;
        u8  tdr_off;
        u8  rpt_spk;       //x8d0
        u8  rpt_ptt;
        u8  autolock;
        u8  apo_time;
        u8  low_v;
        u8  fan;
        u8  rpt_set_model;
        u8  pf1_set;
        u8  auto_am;
        u8  dtmf_time;
        u8  dtmf_int;
        u8  bcl_b;
        u8  rpt_tone;
        u8  sc_qt;
        u8  vfoband_a;
        u8  x8dF;
        u24  ani_edit;
        u8  x8e3;
        u24  mcc_edit;
        u8  x8e7;
        u24  scc_edit;
        u8  x8eB;
        u24  ctrl_edit;
        u8  x8eF;
        u8  KeyA;
        u8  KeyB;
        u8  KeyC;
        u8  ABR;
        u8  x8f4;
        u8  x8f5;
        u8  KeyD;       // KG-1000G Plus ONLY
        u8  x8f7;
        u8  x8f8;
        u8  x8f9;
        u8  x8fA;
        u8  x8fB;
        u8  x8fC;
        u8  x8fD;
        u8  x8fE;
        u8  x8fF;
        u16  FM_radio_cur_freq;
        u8  x902;
        u8  scan_det;
        u8  x904;
        u8  thr_vol_tx;
        u16  thr_vol_lvl;
        u8  x908;
        u8  x909;
        u8  x90A;
        u8  x90B;
        u8  x90C;
        u8  x90D;
        u8  x90E;
        u8  x90F;
        u8  x910pad[48];
        u16  scanlower1; // x940
        u16  scanupper1;
        u16  scanlower2;
        u16  scanupper2;
        u16  scanlower3;
        u16  scanupper3;
        u16  scanlower4;
        u16  scanupper4;
        u16  scanlower5;
        u16  scanupper5;
        u16  scanlower6;
        u16  scanupper6;
        u16  scanlower7;
        u16  scanupper7;
        u16  scanlower8;
        u16  scanupper8;
        u16  scanlower9;
        u16  scanupper9;
        u16  scanlower10;
        u16  scanupper10;
        u8  scanname0[8]; // x968
        u8  scanname1[8];
        u8  scanname2[8];
        u8  scanname3[8];
        u8  scanname4[8];
        u8  scanname5[8];
        u8  scanname6[8];
        u8  scanname7[8];
        u8  scanname8[8];
        u8  scanname9[8];
        u8  scanname10[8];
     } settings;


    #seekto 0x09f0;
    struct {
        u32     rxfreq;
        u32     txfreq;
        u16     txtone;
        u16     rxtone;
        u8      unknown1:3,
                mute_mode:2,
                unknown2:3;
        u8      named:1,
                scan_add:1,
                extra_power_bit:1,
                power:2,
                am_mode:1,
                unknownbit2:1,
                isnarrow:1;
        u8      unknown3:6,
                Unknown4_shft_dir:2;
        u8      unknown5:3,
                compander:1,
                scrambler:4;
    } memory[1000];

    #seekto 0x48f8;
    struct {
        u8    name[8];
    } names[1000];

    #seekto 0x6fff;
    u8          valid[1000];
    """


def _freq_decode(in_freq, bytes=4):
    out_freq = 0
    for i in range(bytes*2):
        out_freq += (in_freq & 0xF) * (10 ** i)
        in_freq = in_freq >> 4
    if bytes == 4:
        return out_freq * 10
    elif bytes == 2:
        return out_freq * 100000


def _freq_encode(in_freq, bytes=4):
    if bytes == 4:
        return int('%08d' % (in_freq / 10), 16)
    elif bytes == 2:
        return int('%04d' % (in_freq / 100000), 16)


def _oem_str_decode(in_str):
    out_str = ''
    stopchar = False
    for c in in_str:
        if c != 0x50 and stopchar is False:
            if chr(c+48) in chirp_common.CHARSET_ASCII:
                out_str += chr(c+48)
        else:
            out_str += ''
            stopchar = True
    return out_str


def _oem_str_encode(in_str):
    out_str = ''
    LOG.debug("OEM Input String = %s", in_str)
    for c in in_str:
        try:
            out_str += chr(int(ord(c))-48)
        except ValueError:
            pass
    while len(out_str) < 8:
        out_str += chr(0x50)
    LOG.debug("OEM Output String = %s", out_str)
    return out_str


# OEM String Encode for KG-1000G Plus
def _oem_str_decode_1000GPLUS(in_str):
    LOG.debug("decode OEM Input String = %s", in_str)
    out_str = ''
    for c in in_str:
        # 1000G+ character mapping starts with P = 32 and O = 127
        if 127 >= c >= 80:
            out_str += chr(c - 48)
        elif 32 <= c < 80:
            out_str += chr(c+48)
        else:
            out_str += ''
    LOG.debug("decode OEM Output String = %s", out_str)
    return out_str


# OEM String Encode for KG-1000G Plus
def _oem_str_encode_1000GPLUS(in_str):
    out_str = ''
    LOG.debug("encode OEM Input String = %s", in_str)
    for c in in_str:
        if 32 <= ord(c) < 80:
            out_str += chr(int(ord(c)) + 48)
        elif 127 >= ord(c) >= 80:
            out_str += chr(int(ord(c)) - 48)
    while len(out_str) < 8:
        out_str += chr(0x50)
    LOG.debug("encode OEM Output String = %s", out_str)
    return out_str


def _str_decode(in_str):
    out_str = ''
    stopchar = False
    for c in in_str:
        if c != 0x00 and stopchar is False:
            if chr(c) in chirp_common.CHARSET_ASCII:
                out_str += chr(c)
        else:
            out_str += ''
            stopchar = True
    return out_str


def _str_encode(in_str):
    out_str = ''
    for c in in_str:
        try:
            out_str += chr(ord(c))
        except ValueError:
            pass
    while len(out_str) < 8:
        out_str += chr(0x00)
    if out_str == "        " or out_str == "":
        out_str = "\x00\x00\x00\x00\x00\x00\x00\x00"
    return out_str


def _chnum_decode(in_ch):
    return int(('%04x' % in_ch)[0:3])


def _chnum_encode(in_ch):
    return int('%03d0' % in_ch, 16)

# Support for the Wouxun KG-UV980P radio
# Serial coms are at 19200 baud
# The data is passed in variable length records
# Record structure:
#  Offset   Usage
#    0      start of record (\x7c)
#    1      Command (\x80 Identify \x81 End/Reboot \x82 Read \x83 Write)
#    2      direction (\xff PC-> Radio, \x00 Radio -> PC)
#    3      length of payload (excluding header/checksum) (n)
#    4      payload (n bytes)
#    4+n+1  checksum - only lower 4 bits of byte sum (% 256) of bytes 1 -> 4+n
#
# Memory Read Records:
# the payload is 3 bytes, first 2 are offset (big endian),
# 3rd is number of bytes to read
# Memory Write Records:
# the maximum payload size (from the Wouxun software) seems to be 66 bytes
#  (2 bytes location + 64 bytes data).


@directory.register
class KG980PRadio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):

    """Wouxun KG-UV980P"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV980P"
    _model = b"KG-UV950R2"
    _file_ident = b"980P"
    BAUD_RATE = 19200
    # Start Byte for Communication messages
    _record_start = 0xDA
    # _cs_size = 0x0F for 4-bit checksum, 0xFF for 8-Bit checksum
    _cs_size = 0x0F
    # _valxor = value needed to encrypt/decrypt the bytes to/from the radio
    _valxor = 0x57
    POWER_LEVELS = [chirp_common.PowerLevel("L", watts=1.0),
                    chirp_common.PowerLevel("M", watts=20.0),
                    chirp_common.PowerLevel("H", watts=50.0)]

    def _checksum(self, data):
        cs = 0
        for byte in data:
            cs += byte
        return ((cs % 256) & self._cs_size)

    def _write_record(self, cmd, payload=b''):
        _packet = struct.pack('BBBB', self._record_start, cmd, 0xFF,
                              len(payload))
        checksum = bytes([self._checksum(_packet[1:] + payload)])
        _packet += self.encrypt(payload + checksum)
        LOG.debug("Sent:\n%s" % util.hexprint(_packet))
        self.pipe.write(_packet)

    def _read_record(self):
        # read 4 chars for the header
        _header = self.pipe.read(4)
        if len(_header) != 4:
            raise errors.RadioError('Radio did not respond')
        _length = struct.unpack('xxxB', _header)[0]
        _packet = self.pipe.read(_length)
        _rcs_xor = _packet[-1]
        _packet = self.decrypt(_packet)
        _cs = self._checksum(_header[1:])
        _cs += self._checksum(_packet)
        _cs %= 256
        _cs = _cs & self._cs_size
        _rcs = self.strxor(self.pipe.read(1)[0], _rcs_xor)[0]
        return (_rcs != _cs, _packet)

    def decrypt(self, data):
        result = b''
        for i in range(len(data)-1, 0, -1):
            result += self.strxor(data[i], data[i - 1])
        result += self.strxor(data[0], self._valxor)
        return result[::-1]

    def encrypt(self, data):
        result = self.strxor(self._valxor, data[0])
        for i in range(1, len(data), 1):
            result += self.strxor(result[i - 1], data[i])
        return result

    def strxor(self, xora, xorb):
        return bytes([xora ^ xorb])

    # Identify the radio
    #
    # A Gotcha: the first identify packet returns a bad checksum, subsequent
    # attempts return the correct checksum... (well it does on my radio!)
    #
    # The ID record returned by the radio also includes the
    # current frequency range
    # as 4 bytes big-endian in 10 Hz increments
    #
    # Offset
    #  0:10     Model, zero padded

    def _identify(self):
        """Do the identification dance"""
        for _i in range(0, 3):
            LOG.debug("ID try #"+str(_i))
            self._write_record(CMD_ID)
            _chksum_err, _resp = self._read_record()
            if len(_resp) == 0:
                raise errors.RadioError("Radio not responding")
            else:
                LOG.debug("Got:\n%s" % util.hexprint(_resp))
                LOG.debug("Model received is %s" % _resp[0:10])
                LOG.debug("Model expected is %s" % self._model)
                if _chksum_err:
                    LOG.error("Checksum error: retrying ident...")
                    time.sleep(0.100)
                    continue
                else:
                    LOG.debug("checksum passed")
                    if _resp[0:8] == self._model[0:8]:
                        LOG.debug("Passed identify")
                        break
                    else:
                        LOG.debug("FAILED to identify")
                        raise errors.RadioError("Failed Identification")

    def _finish(self):
        self._write_record(CMD_END)

    def process_mmap(self):
        self._memobj = bitwise.parse(_MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = self._download()
        except errors.RadioError:
            raise
        except Exception:
            raise errors.RadioError("Failed to communicate with radio: %s")
        self.process_mmap()

    def sync_out(self):
        self._upload()

    # TODO: Load all memory.
    # It would be smarter to only load the active areas and none of
    # the padding/unused areas. Padding still need to be investigated.
    def _download(self):
        """Talk to a Wouxun KG-UV980P and do a download"""
        try:
            self._identify()
            return self._do_download(0, 32768, 64)
        except errors.RadioError:
            raise
        except Exception:
            LOG.exception('Unknown error during download process')
            raise errors.RadioError("Failed to communicate with radio: %s")

    def _do_download(self, start, end, size):
        # allocate & fill memory
        LOG.debug("Start Download")
        image = b""
        for i in range(start, end, size):
            req = struct.pack("BBB", int(i / 256), int(i % 256), int(size))
            self._write_record(CMD_RD, req)
            cs_error, resp = self._read_record()
            if cs_error:
                LOG.debug(util.hexprint(resp))
                raise errors.RadioError("Checksum error on read")
            image += resp[2:]
            if self.status_fn:
                status = chirp_common.Status()
                status.cur = i
                status.max = end
                status.msg = "Cloning from radio"
                self.status_fn(status)
        self._finish()
        LOG.debug("Download Completed")
        return memmap.MemoryMapBytes(image)

    def _upload(self):
        """Talk to a Wouxun KG-UV980P and do a upload"""
        try:
            self._identify()
            LOG.debug("Done with Upload Identify")
            self._do_upload()
            LOG.debug("Done with Mem and Settings Upload")
            self._finish()
        except errors.RadioError:
            raise
        except Exception:
            raise errors.RadioError("Failed to communicate with radio: %s")
        return

    def _do_upload(self):
        LOG.debug("Start of _do_upload")
        cfg_map = config_map
        endwrite = 0x73E7
        for start, blocksize, count in cfg_map:
            end = start + (blocksize * count)
            LOG.debug("start = " + str(start))
            LOG.debug("end = " + str(end))
            LOG.debug("blksize = " + str(blocksize))

            for addr in range(start, end, blocksize):
                ptr = addr
                req = struct.pack('>H', addr)
                chunk = self.get_mmap()[ptr:ptr + blocksize]
                self._write_record(CMD_WR, req + chunk)
                LOG.debug(util.hexprint(req + chunk))
                cserr, ack = self._read_record()
                LOG.debug(util.hexprint(ack))
                j = struct.unpack('>H', ack)[0]
                if cserr or j != ptr:
                    raise errors.RadioError("Radio did not ack block %i" % ptr)
                ptr += blocksize
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = ptr
                    status.max = endwrite
                    status.msg = "Cloning to radio"
                    self.status_fn(status)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->Tone",
            "->DTCS",
            "DTCS->DTCS",
        ]
        rf.valid_modes = ["FM", "NFM", "AM", "NAM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 8
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_bands = [(26000000, 299999990),  # supports VHF
                          (300000000, 999999990)]  # supports UHF

        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.memory_bounds = (1, 999)  # 999 memories
        rf.valid_tuning_steps = STEPS
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is experimental and may contain bugs. \n'
             'USE AT YOUR OWN RISK  - '
             'SAVE A COPY OF DOWNLOAD FROM YOUR RADIO BEFORE MAKING CHANGES\n'
             'Modification of Freq Limit Interfaces is done '
             'AT YOUR OWN RISK and may affect performance or certification'
             )
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _get_tone(self, _mem, mem):
        #  - corrected the Polarity decoding to match 980P implementation
        # use 0x4000 bit mask for R
        #  - 0x4000 appears to be the bit mask for Inverted DCS tones
        #  - n DCS Tone will be 0x8xxx values - i DCS Tones will
        # be 0xCxxx values.
        #  - Chirp Uses N for n DCS Tones and R for i DCS Tones
        #  - 980P encodes DCS tone # in decimal -  NOT OCTAL
        def _get_dcs(val):
            code = int("%03d" % (val & 0x07FF))
            pol = (val & 0x4000) and "R" or "N"
            return code, pol
        #  - Modified the function below to bitwise AND with 0x4000
        # to check for 980P DCS Tone decoding
        #  0x8000 appears to be the bit mask for DCS tones
        tpol = False
        #  Beta 1.1 - Fix the txtone compare to 0x8000 - was rxtone.
        if _mem.txtone != 0xFFFF and (_mem.txtone & 0x8000) == 0x8000:
            tcode, tpol = _get_dcs(_mem.txtone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.txtone != 0xFFFF and _mem.txtone != 0x0:
            mem.rtone = (_mem.txtone & 0x7fff) / 10.0
            txmode = "Tone"
        else:
            txmode = ""
        #  - Modified the function below to bitwise AND with 0x4000
        # to check for 980P DCS Tone decoding
        rpol = False
        if _mem.rxtone != 0xFFFF and (_mem.rxtone & 0x8000) == 0x8000:
            rcode, rpol = _get_dcs(_mem.rxtone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rxtone != 0xFFFF and _mem.rxtone != 0x0:
            mem.ctone = (_mem.rxtone & 0x7fff) / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        # always set it even if no dtcs is used
        mem.dtcs_polarity = "%s%s" % (tpol or "N", rpol or "N")

    def get_memory(self, number):
        _mem = self._memobj.memory[number]

        mem = chirp_common.Memory()
        mem.number = number
        _valid = self._memobj.valid[mem.number]
        _nam = self._memobj.names[number]

        # Handle deleted channel quirks due to radio firmware
        # not always clearing the valid channel indicators
        # _valid == 0x80 indicates channel was deleted thru radio menu and
        # only part of the channel structure data is cleared by firmware
        # _valid == 0x00 indicates the channel is Valid
        # all other values the firmware uses for _valid: look for valid
        # Rx and Tx freq values to determine validity
        if (_valid in MEM_INVALID or
           ((_valid != MEM_VALID) & ((_mem.rxfreq == 0xFFFFFFFF) or
                                     _mem.rxfreq == 0x00000000))):
            mem.empty = True
            if _valid == 0x80:
                LOG.debug("Ch %s was deleted by using radio menu" % number)
                LOG.debug("Current Memory: \n%s" % _mem)
                LOG.debug("Clearing Ch %s memory" % number)
                _mem.set_raw(b"\xFF" * (_mem.size() // 8))
                _nam.set_raw(b"\xFF" * (_nam.size() // 8))
            self._memobj.valid[mem.number] = 0xFF
            return mem
        elif (_valid != MEM_VALID) & ((_mem.rxfreq != 0xFFFFFFFF) and
                                      (_mem.rxfreq != 0x00000000)):
            mem.empty = False
            self._memobj.valid[mem.number] = MEM_VALID
        else:
            mem.empty = False
        mem.freq = int(_mem.rxfreq) * 10
        _rxfreq = _freq_decode(_mem.rxfreq)
        _txfreq = _freq_decode(_mem.txfreq)
        mem.freq = _rxfreq

        if _mem.txfreq == 0xFFFFFFFF:
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        elif int(_rxfreq) == int(_txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(_rxfreq - _txfreq) > 70000000:
            mem.duplex = "split"
            mem.offset = _txfreq
        else:
            mem.duplex = _rxfreq > _txfreq and "-" or "+"
            mem.offset = abs(_rxfreq - _txfreq)

        if _mem.named:
            mem.name = _str_decode(self._memobj.names[number].name)
            # Remove trailing whitespaces from the name
            mem.name = mem.name.rstrip()
        else:
            mem.name = ''

        self._get_tone(_mem, mem)

        mem.skip = "" if bool(_mem.scan_add) else "S"

        pwr_index = _mem.power
        if _mem.power == 3:
            pwr_index = 2
        if _mem.power:
            mem.power = self.POWER_LEVELS[pwr_index]
        else:
            mem.power = self.POWER_LEVELS[0]

        if _mem.am_mode:
            if _mem.isnarrow:
                mem.mode = "NAM"
            else:
                mem.mode = "AM"
        else:
            mem.mode = _mem.isnarrow and "NFM" or "FM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        # Scrambler >8 is invalid default to off
        if _mem.scrambler > 8:
            _mem.scrambler = 0

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            #  Change to 0x8000 to
            # set the bit for DCS- code is a decimal version
            # of the code # - NOT OCTAL
            val = code | 0x8000
            if pol == "R":
                #  Change to 0x4000 to set the bit for
                # i/R polarity
                val += 0x4000
            return val

        rx_mode = tx_mode = None
        rxtone = txtone = 0x0000

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            txtone = int(mem.rtone * 10)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rxtone = txtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rxtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                txtone = int(mem.rtone * 10)
            if rx_mode == "DTCS":
                rxtone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rxtone = int(mem.ctone * 10)

        _mem.rxtone = rxtone
        _mem.txtone = txtone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.txtone, rx_mode, _mem.rxtone))

    def set_memory(self, mem):
        # _mem = Stored Memory value
        # mem = New value from user entry
        number = mem.number
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        if mem.empty:
            self._memobj.valid[number] = 0xFF
            _mem.set_raw(b"\xFF" * (_mem.size() // 8))
            self._memobj.names[number].set_raw(b"\xFF" * (_nam.size() // 8))
        else:
            if len(mem.name) > 0:
                _mem.named = True
                name_encoded = _str_encode(mem.name)
                for i in range(0, 8):
                    _nam.name[i] = ord(name_encoded[i])
            else:
                _mem.named = False

            _mem.rxfreq = _freq_encode(mem.freq)
            if mem.duplex == "off":
                _mem.txfreq = 0xFFFFFFFF
            elif mem.duplex == "split":
                _mem.txfreq = _freq_encode(mem.offset)
            elif mem.duplex == "+":
                _mem.txfreq = _freq_encode(mem.freq + mem.offset)
            elif mem.duplex == "-":
                _mem.txfreq = _freq_encode(mem.freq - mem.offset)
            else:
                _mem.txfreq = _freq_encode(mem.freq)

            _mem.scan_add = int(mem.skip != "S")

            if mem.mode == "AM":
                _mem.am_mode = True
                _mem.isnarrow = False
            elif mem.mode == "NAM":
                _mem.am_mode = True
                _mem.isnarrow = True
            else:
                _mem.am_mode = False
                if mem.mode == "NFM":
                    _mem.isnarrow = True
                else:
                    _mem.isnarrow = False

            # set the tone
            self._set_tone(mem, _mem)
            #  set the scrambler and compander to off by default
            #  This changes them in the channel memory
            _mem.scrambler = 0
            _mem.compander = 0
            # set the power
            # Updated to resolve "Illegal set on attribute power" Warning
            if str(mem.power) == "None":
                _mem.power = 0  # Default to Low power
            else:
                index = self.POWER_LEVELS.index(mem.power)
                if index == 2:
                    _mem.power = 0b11  # Force H to value of binary 3
                else:
                    _mem.power = index
            # Not sure what this bit does yet but it causes
            # the radio to display
            # MED power when the CPS shows Low Power.
            # Forcing it to 0 to keep them
            # consistent
            _mem.extra_power_bit = 0
            # Set other unknowns to 0 to match default CPS values
            _mem.unknown1 = 0
            _mem.unknown2 = 0
            _mem.unknownbit2 = 0
            _mem.unknown3 = 0
            _mem.Unknown4_shft_dir = 0
            _mem.unknown5 = 0

            #  set to mute mode to QT (not QT+DTMF or QT*DTMF) by default
            #  This changes them in the channel memory
            _mem.mute_mode = 1
            self._memobj.valid[number] = MEM_VALID

    def _get_settings(self):
        _settings = self._memobj.settings
        _oem = self._memobj.oem

        cfg_grp = RadioSettingGroup("cfg_grp", "Config Settings")
        cfg1_grp = RadioSettingGroup("cfg1_grp", "Config Settings 1")
        cfg2_grp = RadioSettingGroup("cfg2_grp", "Config Settings 2")
        if self.MODEL == "KG-1000G Plus":
            vfoaname = "Area A Settings"
        else:
            vfoaname = "VFO A Settings"
        vfoa_grp = RadioSettingGroup("vfoa_grp", vfoaname)
        vfo150_grp = RadioSettingGroup("vfo150_grp", "150M Settings")
        vfo450_grp = RadioSettingGroup("vfo450_grp", "450M Settings")
        vfo20_grp = RadioSettingGroup("vfo20_grp", "20M Settings")
        vfo50_grp = RadioSettingGroup("vfo50_grp", "50M Settings")
        vfo350_grp = RadioSettingGroup("vfo350_grp", "350M Settings")
        vfo850_grp = RadioSettingGroup("vfo850_grp", "850M Settings")
        if self.MODEL == "KG-1000G Plus":
            vfobname = "Area B Settings"
        else:
            vfobname = "VFO B Settings"
        vfob_grp = RadioSettingGroup("vfob_grp", vfobname)

        fmradio_grp = RadioSettingGroup("fmradio_grp", "FM Broadcast Memory")
        lmt_grp = RadioSettingGroup("lmt_grp", "Frequency Limits")
        lmwrn_grp = RadioSettingGroup("lmwrn_grp", "USE AT YOUR OWN RISK")
        rxlim_grp = RadioSettingGroup("rxlim_grp", "Rx Limits")
        txlim_grp = RadioSettingGroup("txlim_grp", "Tx Limits")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")
        scan_grp = RadioSettingGroup("scan_grp", "Scan Group")
        scanname_grp = RadioSettingGroup("scanname_grp", "Scan Names")
        remote_grp = RadioSettingGroup("remote_grp", "Remote Settings")
        extra_grp = RadioSettingGroup("extra_grp",
                                      "Extra Settings")
        if self.MODEL == "KG-1000G Plus":
            vfoname = "Freq Mode Settings"
        else:
            vfoname = "VFO Settings"
        vfo_grp = RadioSettingGroup("vfo_grp",
                                    vfoname)
        extra_grp.append(oem_grp)
        cfg_grp.append(cfg1_grp)
        cfg_grp.append(cfg2_grp)
        lmt_grp.append(lmwrn_grp)
        lmt_grp.append(rxlim_grp)
        extra_grp.append(lmt_grp)
        vfo_grp.append(vfoa_grp)
        vfo_grp.append(vfob_grp)
        vfoa_grp.append(vfo150_grp)
        vfoa_grp.append(vfo450_grp)
        if self.MODEL == "KG-UV980P":
            vfoa_grp.append(vfo20_grp)
            lmt_grp.append(txlim_grp)
        vfoa_grp.append(vfo50_grp)
        vfoa_grp.append(vfo350_grp)
        vfoa_grp.append(vfo850_grp)
        scan_grp.append(scanname_grp)

        group = RadioSettings(cfg_grp, vfo_grp, fmradio_grp,
                              remote_grp, scan_grp, extra_grp)

        # Configuration Settings
        if self.MODEL == "KG-1000G Plus":
            voicemap = VOICE_MAP_1000GPLUS
            pttidmap = PTT_ID_MAP_1000GPLUS
            pttidlabel = "DTMF ID"
            dtmflist = DTMF_ST_LIST_1000GPLUS
            dtmflabel = "Sidetone"
            spkmap = SPEAKER_MAP_1000GPLUS
            key_l = KEY_LIST_1000GPLUS
            scqt = SC_QT_MAP_1000GPLUS
            pf1set = PF1_SETTINGS_1000GPLUS
            wmmap = WORKMODE_MAP_1000GPLUS
            totmap = TOT_MAP_1000GPLUS
            lowvlabel = "Voltage Alert"
            fanlabel = "Fan Setting"
            alerttonelabel = "Alert Tone(Hz)"
            tonescanlabel = "Tone Save"
            pttdelaylabel = "DTMF ID Delay (ms)"
            scandetlabel = "Tone Scan"
            txvoltlabel = "Tx Voltage Limit"
            holdtimrptlabel = "Repeater Hold Time (ms)"
            thrvollvllabel = "Tx Voltage Min"
            modepswlabel = "Freq Mode Password"
            narrow1label = "150M W/N"
            mute1label = "150M SP Mute"
            scram1label = "150M Descrambler"
            narrow2label = "450M W/N"
            mute2label = "450M SP Mute"
            scram2label = "450M Descrambler"
            narrow3label = "20M W/N"
            mute3label = "20M SP Mute"
            scram3label = "20M Descrambler"
            narrow4label = "50M W/N"
            mute4label = "50M SP Mute"
            scram4label = "50M Descrambler"
            narrow5label = "350M W/N"
            mute5label = "350M SP Mute"
            scram5label = "350M Descrambler"
            narrow6label = "850M W/N"
            mute6label = "850M SP Mute"
            scram6label = "850M Descrambler"
            narrow7label = "W/N"
            mute7label = "SP Mute"
            scram7label = "Descrambler"
        else:   # 980P or 1000G radios
            voicemap = VOICE_MAP
            pttidmap = PTT_ID_MAP
            pttidlabel = "Caller ID Tx Mode (PTT_ID)"
            dtmflist = DTMF_ST_LIST
            dtmflabel = "DTMF Sidetone"
            spkmap = SPEAKER_MAP
            key_l = KEY_LIST
            scqt = SC_QT_MAP
            pf1set = PF1_SETTINGS
            wmmap = WORKMODE_MAP
            totmap = TOT_MAP
            lowvlabel = "Low Voltage Shutoff"
            fanlabel = "Fan Mode"
            alerttonelabel = "Alert Pulse (Hz)"
            tonescanlabel = "CTCSS/DCS Scan"
            pttdelaylabel = "Caller ID Tx Delay PTT-ID-DLY (ms)"
            scandetlabel = "Scan DET"
            txvoltlabel = "Threshold Voltage Tx"
            holdtimrptlabel = "Hold Time of Repeat (ms)"
            thrvollvllabel = "Threshold Voltage Level"
            modepswlabel = "MODE PSW"
            narrow1label = "150M Bandwidth"
            mute1label = "150M Mute Mode"
            scram1label = "150M Scrambler"
            narrow2label = "450M Bandwidth"
            mute2label = "450M Mute Mode"
            scram2label = "450M Scrambler"
            narrow3label = "20M Bandwidth"
            mute3label = "20M Mute Mode"
            scram3label = "20M Scrambler"
            narrow4label = "50M Bandwidth"
            mute4label = "50M Mute Mode"
            scram4label = "50M Scrambler"
            narrow5label = "350M Bandwidth"
            mute5label = "350M Mute Mode"
            scram5label = "350M Scrambler"
            narrow6label = "850M Bandwidth"
            mute6label = "850M Mute Mode"
            scram6label = "850M Scrambler"
            narrow7label = "Bandwidth"
            mute7label = "Mute Mode"
            scram7label = "Scrambler"

        rs = RadioSetting("roger", "Roger Beep",
                          RadioSettingValueList(ROGER_LIST,
                                                current_index=_settings.
                                                roger))
        cfg1_grp.append(rs)

        rs = RadioSetting("beep", "Keypad Beep",
                          RadioSettingValueBoolean(_settings.beep))
        cfg1_grp.append(rs)

        rs = RadioSetting("voice", "Voice Guide",
                          RadioSettingValueMap(voicemap,
                                               _settings.voice))
        cfg1_grp.append(rs)

        rs = RadioSetting("bcl_a", "Busy Channel Lock-out A",
                          RadioSettingValueBoolean(_settings.bcl_a))
        cfg1_grp.append(rs)

        rs = RadioSetting("bcl_b", "Busy Channel Lock-out B",
                          RadioSettingValueBoolean(_settings.bcl_b))
        cfg1_grp.append(rs)

        rs = RadioSetting("sc_rev", "Scan Mode",
                          RadioSettingValueMap(SC_REV_MAP, _settings.sc_rev))
        cfg1_grp.append(rs)
        rs = RadioSetting("tot", "Timeout Timer (TOT)",
                          RadioSettingValueMap(
                              totmap, _settings.tot))
        cfg1_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("toa", "Timeout Alarm (TOA)",
                              RadioSettingValueList(
                                  TOA_LIST, current_index=_settings.toa))
        else:
            rs = RadioSetting("toa", "Overtime Alarm (TOA)",
                              RadioSettingValueMap(
                                  TOA_MAP, _settings.toa))
        cfg1_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("ani_sw", "Caller ID Tx - ANI-SW",
                              RadioSettingValueBoolean(_settings.ani_sw))
            cfg1_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("ring", "Ring Time (Sec)",
                              RadioSettingValueList(
                                  RING_LIST,
                                  current_index=_settings.ring))
        else:
            rs = RadioSetting("ring", "Ring Time (Sec)",
                              RadioSettingValueMap(
                                  RING_MAP, _settings.ring))
        cfg1_grp.append(rs)

        rs = RadioSetting("dtmfsf", dtmflabel,
                          RadioSettingValueList(
                              dtmflist,
                              current_index=_settings.dtmfsf))
        cfg1_grp.append(rs)

        rs = RadioSetting("ptt_id", pttidlabel,
                          RadioSettingValueMap(pttidmap, _settings.ptt_id))
        cfg1_grp.append(rs)

        rs = RadioSetting("wt_led", "Standby / WT LED",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=_settings.wt_led))
        cfg1_grp.append(rs)

        rs = RadioSetting("tx_led", "TX LED",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=_settings.tx_led))
        cfg1_grp.append(rs)

        rs = RadioSetting("rx_led", "Rx LED",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=_settings.rx_led))
        cfg1_grp.append(rs)

        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("prich_sw", "Priority Scan",
                              RadioSettingValueList(
                                  PRI_CH_SCAN_LIST,
                                  current_index=_settings.prich_sw))
            cfg1_grp.append(rs)
        else:
            rs = RadioSetting("prich_sw", "Priority Channel Scan",
                              RadioSettingValueBoolean(_settings.prich_sw))
            cfg1_grp.append(rs)

        rs = RadioSetting("spk_cont", "Speaker Control",
                          RadioSettingValueMap(
                              spkmap,
                              _settings.spk_cont))
        cfg1_grp.append(rs)

        rs = RadioSetting("autolock", "Autolock",
                          RadioSettingValueBoolean(_settings.autolock))
        cfg1_grp.append(rs)

        rs = RadioSetting("low_v", lowvlabel,
                          RadioSettingValueBoolean(_settings.low_v))
        cfg1_grp.append(rs)

        rs = RadioSetting("fan", fanlabel,
                          RadioSettingValueList(
                              FAN_MODE_LIST,
                              current_index=_settings.fan))
        cfg1_grp.append(rs)

        rs = RadioSetting("apo_time", "Auto Power-Off (Min)",
                          RadioSettingValueList(
                              APO_TIME_LIST,
                              current_index=_settings.apo_time))
        cfg1_grp.append(rs)

        rs = RadioSetting("alert", alerttonelabel,
                          RadioSettingValueMap(ALERT_MAP, _settings.alert))
        cfg1_grp.append(rs)
        rs = RadioSetting("m_pwr", "Medium Power Level (W)",
                          RadioSettingValueMap(M_POWER_MAP,
                                               _settings.m_pwr))
        cfg1_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("rpt_set_model", "Model (RPT-SET)",
                              RadioSettingValueList(
                                  RPT_MODE_LIST,
                                  current_index=_settings.rpt_set_model))
        else:
            rs = RadioSetting("rpt_set_model", "Repeater Mode",
                              RadioSettingValueMap(
                                  RPT_MODE_MAP,
                                  _settings.rpt_set_model))
        cfg2_grp.append(rs)

        rs = RadioSetting("rpt_spk", "Repeater Speaker Switch (RPT-SPK)",
                          RadioSettingValueBoolean(_settings.rpt_spk))
        cfg2_grp.append(rs)

        rs = RadioSetting("rpt_ptt", "Repeater PTT (RPT-PTT)",
                          RadioSettingValueBoolean(_settings.rpt_ptt))
        cfg2_grp.append(rs)

        rs = RadioSetting("dtmf_time", "DTMF Tx Duration (ms)",
                          RadioSettingValueList(
                              DTMF_TIMES,
                              current_index=_settings.dtmf_time))
        cfg2_grp.append(rs)
        rs = RadioSetting("dtmf_int", "DTMF Interval (ms)",
                          RadioSettingValueList(
                              DTMF_INTERVALS,
                              current_index=_settings.dtmf_int))
        cfg2_grp.append(rs)

        rs = RadioSetting("sc_qt", tonescanlabel,
                          RadioSettingValueMap(
                              scqt, _settings.sc_qt))
        cfg2_grp.append(rs)

        rs = RadioSetting("pri_ch", "Priority Channel",
                          RadioSettingValueInteger(
                              1, 999, _chnum_decode(_settings.pri_ch)))
        cfg2_grp.append(rs)

        rs = RadioSetting("ptt_id_dly", pttdelaylabel,
                          RadioSettingValueMap(PTT_ID_DELAY_MAP,
                                               _settings.ptt_id_dly))
        cfg2_grp.append(rs)

        rs = RadioSetting("rc_sw", "Remote Control RC-SW",
                          RadioSettingValueBoolean(_settings.rc_sw))
        cfg2_grp.append(rs)

        rs = RadioSetting("scan_det", scandetlabel,
                          RadioSettingValueBoolean(_settings.scan_det))
        cfg2_grp.append(rs)

        rs = RadioSetting("menu", "Menu Available",
                          RadioSettingValueBoolean(_settings.menu))
        cfg2_grp.append(rs)

        rs = RadioSetting("thr_vol_tx", txvoltlabel,
                          RadioSettingValueBoolean(_settings.thr_vol_tx))
        cfg2_grp.append(rs)

        rs = RadioSetting("hold_time_rpt", holdtimrptlabel,
                          RadioSettingValueList(
                              HOLD_TIMES,
                              current_index=_settings.hold_time_rpt))
        cfg2_grp.append(rs)

        rs = RadioSetting("auto_am", "Auto AM",
                          RadioSettingValueBoolean(_settings.auto_am))
        cfg2_grp.append(rs)

        rs = RadioSetting("rpt_tone", "Repeat Tone",
                          RadioSettingValueBoolean(_settings.rpt_tone))
        cfg2_grp.append(rs)

        rs = RadioSetting("pf1_set", "PF1 setting",
                          RadioSettingValueList(
                              pf1set,
                              current_index=_settings.pf1_set))
        cfg2_grp.append(rs)

        rs = RadioSetting("settings.thr_vol_lvl", thrvollvllabel,
                          RadioSettingValueFloat(
                           9.5, 10.5, _settings.thr_vol_lvl / 100.0, 0.1, 1))
        cfg2_grp.append(rs)

        dtmfchars = "0123456789"
        _code = ''
        test = int(_oem.mode_psw)
        _codeobj = '0x{0:0{1}X}'.format(test, 6)
        LOG.debug("codeobj = %s" % _codeobj)
        _psw = str(_codeobj)
        for i in range(2, 8):
            LOG.debug("psw[i] = %s" % _psw[i])
            if _psw[i] in dtmfchars:
                _code += _psw[i]
        val_psw = RadioSettingValueString(6, 6, _code, False)
        val_psw.set_charset(dtmfchars)
        rs = RadioSetting("oem.mode_psw", modepswlabel, val_psw)

        def apply_psw_id(setting, obj):
            val2 = hex(int(str(val_psw), 16))
            if (int(val2, 16) != 0):
                while len(val2) < 8:
                    val2 += '0'
            psw = int(str(val2), 16)
            obj.mode_psw = psw
        rs.set_apply_callback(apply_psw_id, _oem)
        cfg2_grp.append(rs)

        rs = RadioSetting("ABR", "Backlight On Time (ABR)",
                          RadioSettingValueList(
                              ABR_LIST,
                              current_index=_settings.ABR))
        cfg2_grp.append(rs)

        rs = RadioSetting("KeyA", "Key A",
                          RadioSettingValueList(
                              key_l,
                              current_index=_settings.KeyA))
        cfg2_grp.append(rs)
        rs = RadioSetting("KeyB", "Key B",
                          RadioSettingValueList(
                              key_l,
                              current_index=_settings.KeyB))
        cfg2_grp.append(rs)
        rs = RadioSetting("KeyC", "Key C",
                          RadioSettingValueList(
                              key_l,
                              current_index=_settings.KeyC))
        cfg2_grp.append(rs)

        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("KeyD", "Key D",
                              RadioSettingValueList(
                                  KEY_LIST_1000GPLUS,
                                  current_index=_settings.KeyD))
            cfg2_grp.append(rs)

        rs = RadioSetting("key_lock", "Key Lock Active",
                          RadioSettingValueBoolean(_settings.key_lock))
        cfg2_grp.append(rs)

        rs = RadioSetting("act_area", "Active Area (BAND)",
                          RadioSettingValueList(
                              ACTIVE_AREA_LIST,
                              current_index=_settings.act_area))
        cfg2_grp.append(rs)
        rs = RadioSetting("tdr_off", "TDR",
                          RadioSettingValueList(
                              TDR_LIST,
                              current_index=_settings.tdr_off))
        cfg2_grp.append(rs)

        # Freq Limits settings

        # Convert Integer back to correct limit HEX value:
        s = self._memobj

        _temp = int(s.bandlimits.limit_144M_ChA_rx_start) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChA_rx_start",
                          "144M Area A Rx Lower Limit (MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_144M_ChA_rx_stop) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChA_rx_stop",
                          "144M Area A Rx Upper Limit (+ .9975 MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_144M_ChB_rx_start) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChB_rx_start",
                          "144M Area B Rx Lower Limit (MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_144M_ChB_rx_stop) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChB_rx_stop",
                          "144M Area B Rx Upper Limit (+ .9975 MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_70cm_rx_start) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_70cm_rx_start",
                          "450M Rx Lower Limit (MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_70cm_rx_stop) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_70cm_rx_stop",
                          "450M Rx Upper Limit (+ .9975 MHz)",
                          val)
        rxlim_grp.append(rs)

        if self.MODEL == "KG-UV980P":
            _temp = int(s.bandlimits.limit_10m_rx_start) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_10m_rx_start",
                              "20M Rx Lower Limit (MHz)",
                              val)
            rxlim_grp.append(rs)

            _temp = int(s.bandlimits.limit_10m_rx_stop) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_10m_rx_stop",
                              "20M Rx Upper Limit (+ .9975 MHz)",
                              val)
            rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_6m_rx_start) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_6m_rx_start",
                          "50M Rx Lower Limit (MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_6m_rx_stop) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_6m_rx_stop",
                          "50M Rx Upper Limit (+ .9975 MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_350M_rx_start) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_350M_rx_start",
                          "350M Rx Lower Limit (MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_350M_rx_stop) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_350M_rx_stop",
                          "350M Rx Upper Limit (+ .9975 MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_850M_rx_start) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_850M_rx_start",
                          "850M Rx Lower Limit (MHz)",
                          val)
        rxlim_grp.append(rs)

        _temp = int(s.bandlimits.limit_850M_rx_stop) // 10
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_850M_rx_stop",
                          "850M Rx Upper Limit (+ .9975 MHz)",
                          val)
        rxlim_grp.append(rs)
        if self.MODEL == "KG-UV980P":
            _temp = int(s.bandlimits.limit_144M_tx_start) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_144M_tx_start",
                              "144M Tx Lower Limit (MHz)",
                              val)
            txlim_grp.append(rs)

            _temp = int(s.bandlimits.limit_144M_tx_stop) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_144M_tx_stop",
                              "144M Tx Upper Limit (+ .9975 MHz)",
                              val)
            txlim_grp.append(rs)

            _temp = int(s.bandlimits.limit_70cm_tx_start) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_70cm_tx_start",
                              "450M Tx Lower Limit (MHz)",
                              val)
            txlim_grp.append(rs)

            _temp = int(s.bandlimits.limit_70cm_tx_stop) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_70cm_tx_stop",
                              "450M tx Upper Limit (+ .9975 MHz)",
                              val)
            txlim_grp.append(rs)

            if self.MODEL == "KG-UV980P":
                _temp = int(s.bandlimits.limit_10m_tx_start) // 10
                val = RadioSettingValueInteger(0, 999, _temp)
                rs = RadioSetting("bandlimits.limit_10m_tx_start",
                                  "20M tx Lower Limit (MHz)",
                                  val)
                txlim_grp.append(rs)

                _temp = int(s.bandlimits.limit_10m_tx_stop) // 10
                val = RadioSettingValueInteger(0, 999, _temp)
                rs = RadioSetting("bandlimits.limit_10m_tx_stop",
                                  "20M tx Upper Limit (+ .9975 MHz)",
                                  val)
                txlim_grp.append(rs)

            _temp = int(s.bandlimits.limit_6m_tx_start) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_6m_tx_start",
                              "50M tx Lower Limit (MHz)",
                              val)
            txlim_grp.append(rs)

            _temp = int(s.bandlimits.limit_6m_tx_stop) // 10
            val = RadioSettingValueInteger(0, 999, _temp)
            rs = RadioSetting("bandlimits.limit_6m_tx_stop",
                              "50M tx Upper Limit (+ .9975 MHz)",
                              val)
            txlim_grp.append(rs)

        # VFO Settings
        rs = RadioSetting("vfomode_a", "Working Mode",
                          RadioSettingValueMap(wmmap,
                                               _settings.vfomode_a))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfoband_a", "Current Band",
                          RadioSettingValueMap(VFOBAND_MAP,
                                               _settings.vfoband_a))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfochan_a", "Active/Work Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _chnum_decode(
                                                    _settings.vfochan_a)))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfosquelch_a", "Squelch",
                          RadioSettingValueInteger(0, 9,
                                                   _settings.vfosquelch_a))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfostep_a", "Step",
                          RadioSettingValueList(
                            STEP_LIST,
                            current_index=_settings.vfostep_a))
        vfoa_grp.append(rs)

        # #####################

        rs = RadioSetting("vfofreq1", "150M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq1) /
                                             1000000.0), 0.000001, 6))
        vfo150_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("vfoofst1", "150M Offset",
                              RadioSettingValueFloat(
                                0, 999.999999, (_freq_decode
                                                (_settings.vfoofst1) /
                                                1000000.0), 0.000001, 6))
            vfo150_grp.append(rs)

        rs = RadioSetting("rxtone1", "150M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone1))
        vfo150_grp.append(rs)

        rs = RadioSetting("txtone1", "150M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone1))
        vfo150_grp.append(rs)

        rs = RadioSetting("power1", "150M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power1))
        vfo150_grp.append(rs)

        rs = RadioSetting("narrow1", narrow1label,
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow1))
        vfo150_grp.append(rs)

        rs = RadioSetting("mute1", mute1label,
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute1))
        vfo150_grp.append(rs)

        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("shft_dir1", "150M Repeater",
                              RadioSettingValueBoolean(
                                _settings.shft_dir1))
        else:
            rs = RadioSetting("shft_dir1", "150M Shift Direction",
                              RadioSettingValueList(
                                DUPLEX_LIST,
                                current_index=_settings.shft_dir1))
        vfo150_grp.append(rs)

        rs = RadioSetting("compander1", "150M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander1))
        vfo150_grp.append(rs)

        rs = RadioSetting("scrambler1", scram1label,
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            current_index=_settings.scrambler1))
        vfo150_grp.append(rs)
        rs = RadioSetting("am_mode1", "150M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode1))
        vfo150_grp.append(rs)

        # ###########################

        rs = RadioSetting("vfofreq2", "450M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode(
                                             _settings.vfofreq2) /
                                             1000000.0), 0.000001, 6))
        vfo450_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("vfoofst2", "450M Offset",
                              RadioSettingValueFloat(
                                0, 999.999999, (_freq_decode(
                                                _settings.vfoofst2) /
                                                1000000.0), 0.000001, 6))
            vfo450_grp.append(rs)

        rs = RadioSetting("rxtone2", "450M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone2))
        vfo450_grp.append(rs)

        rs = RadioSetting("txtone2", "450M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone2))
        vfo450_grp.append(rs)

        rs = RadioSetting("power2", "450M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power2))
        vfo450_grp.append(rs)

        rs = RadioSetting("narrow2", narrow2label,
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow2))
        vfo450_grp.append(rs)

        rs = RadioSetting("mute2", mute2label,
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute2))
        vfo450_grp.append(rs)

        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("shft_dir2", "450M Repeater",
                              RadioSettingValueBoolean(
                                _settings.shft_dir2))
        else:
            rs = RadioSetting("shft_dir2", "450M Shift Direction",
                              RadioSettingValueList(
                                DUPLEX_LIST,
                                current_index=_settings.shft_dir2))
        vfo450_grp.append(rs)

        rs = RadioSetting("compander2", "450M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander2))
        vfo450_grp.append(rs)

        rs = RadioSetting("scrambler2", scram2label,
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            current_index=_settings.scrambler2))
        vfo450_grp.append(rs)

        rs = RadioSetting("am_mode2", "450M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode2))
        vfo450_grp.append(rs)

        # ###########################
        if self.MODEL == "KG-UV980P":
            rs = RadioSetting("vfofreq3", "20M Freq",
                              RadioSettingValueFloat(
                                0, 999.999999, (_freq_decode(
                                                _settings.vfofreq3) /
                                                1000000.0), 0.000001, 6))
            vfo20_grp.append(rs)

            if self.MODEL == "KG-UV980P":
                rs = RadioSetting("vfoofst3", "20M Offset",
                                  RadioSettingValueFloat(
                                    0, 999.999999, (_freq_decode(
                                                    _settings.vfoofst3) /
                                                    1000000.0), 0.000001, 6))
                vfo20_grp.append(rs)

            rs = RadioSetting("rxtone3", "20M Rx tone",
                              RadioSettingValueMap(
                                TONE_MAP, _settings.rxtone3))
            vfo20_grp.append(rs)

            rs = RadioSetting("txtone3", "20M Tx tone",
                              RadioSettingValueMap(
                                TONE_MAP, _settings.txtone3))
            vfo20_grp.append(rs)

            rs = RadioSetting("power3", "20M Power",
                              RadioSettingValueMap(
                                POWER_MAP, _settings.power3))
            vfo20_grp.append(rs)

            rs = RadioSetting("narrow3", narrow3label,
                              RadioSettingValueMap(
                                BANDWIDTH_MAP, _settings.narrow3))
            vfo20_grp.append(rs)

            rs = RadioSetting("mute3", mute3label,
                              RadioSettingValueMap(
                                MUTE_MODE_MAP, _settings.mute3))
            vfo20_grp.append(rs)

            if self.MODEL == "KG-1000G Plus":
                rs = RadioSetting("shft_dir3", "20M Repeater",
                                  RadioSettingValueBoolean(
                                    _settings.shft_dir3))
            else:
                rs = RadioSetting("shft_dir3", "20M Shift Direction",
                                  RadioSettingValueList(
                                    DUPLEX_LIST,
                                    current_index=_settings.shft_dir3))
            vfo20_grp.append(rs)

            rs = RadioSetting("compander3", "20M Compander",
                              RadioSettingValueBoolean(
                                _settings.compander3))
            vfo20_grp.append(rs)

            rs = RadioSetting("scrambler3", scram3label,
                              RadioSettingValueList(
                                SCRAMBLER_LIST,
                                current_index=_settings.scrambler3))
            vfo20_grp.append(rs)

            rs = RadioSetting("am_mode3", "20M AM Mode",
                              RadioSettingValueBoolean(
                                _settings.am_mode3))
            vfo20_grp.append(rs)

        # ###########################

        rs = RadioSetting("vfofreq4", "50M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode(
                                             _settings.vfofreq4) /
                                             1000000.0), 0.000001, 6))
        vfo50_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("vfoofst4", "50M Offset",
                              RadioSettingValueFloat(
                                0, 999.999999, (_freq_decode(
                                                _settings.vfoofst4) /
                                                1000000.0), 0.000001, 6))
            vfo50_grp.append(rs)

        rs = RadioSetting("rxtone4", "50M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone4))
        vfo50_grp.append(rs)

        rs = RadioSetting("txtone4", "50M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone4))
        vfo50_grp.append(rs)

        rs = RadioSetting("power4", "50M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power4))
        vfo50_grp.append(rs)

        rs = RadioSetting("narrow4", narrow4label,
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow4))
        vfo50_grp.append(rs)

        rs = RadioSetting("mute4", mute4label,
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute4))
        vfo50_grp.append(rs)

        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("shft_dir4", "50M Repeater",
                              RadioSettingValueBoolean(
                                _settings.shft_dir4))
        else:
            rs = RadioSetting("shft_dir4", "50M Shift Direction",
                              RadioSettingValueList(
                                DUPLEX_LIST,
                                current_index=_settings.shft_dir4))
        vfo50_grp.append(rs)

        rs = RadioSetting("compander4", "50M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander4))
        vfo50_grp.append(rs)

        rs = RadioSetting("scrambler4", scram4label,
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            current_index=_settings.scrambler4))
        vfo50_grp.append(rs)

        rs = RadioSetting("am_mode4", "50M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode4))
        vfo50_grp.append(rs)
        # ###########################
        rs = RadioSetting("vfofreq5", "350M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode(
                                             _settings.vfofreq5) /
                                             1000000.0), 0.000001, 6))
        vfo350_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("vfoofst5", "350M Offset",
                              RadioSettingValueFloat(
                                0, 999.999999, (_freq_decode(
                                                _settings.vfoofst5) /
                                                1000000.0), 0.000001, 6))
            vfo350_grp.append(rs)

        rs = RadioSetting("rxtone5", "350M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone5))
        vfo350_grp.append(rs)

        rs = RadioSetting("txtone5", "350M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone5))
        vfo350_grp.append(rs)

        rs = RadioSetting("power5", "350M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power5))
        vfo350_grp.append(rs)

        rs = RadioSetting("narrow5", narrow5label,
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow5))
        vfo350_grp.append(rs)

        rs = RadioSetting("mute5", mute5label,
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute5))
        vfo350_grp.append(rs)

        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("shft_dir5", "350M Repeater",
                              RadioSettingValueBoolean(
                                _settings.shft_dir5))
        else:
            rs = RadioSetting("shft_dir5", "350M Shift Direction",
                              RadioSettingValueList(
                                DUPLEX_LIST,
                                current_index=_settings.shft_dir5))
        vfo350_grp.append(rs)

        rs = RadioSetting("compander5", "350M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander5))
        vfo350_grp.append(rs)

        rs = RadioSetting("scrambler5", scram5label,
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            current_index=_settings.scrambler5))
        vfo350_grp.append(rs)

        rs = RadioSetting("am_mode5", "350M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode5))
        vfo350_grp.append(rs)

        # ############################
        rs = RadioSetting("vfofreq6", "850M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode(
                                             _settings.vfofreq6) /
                                             1000000.0), 0.000001, 6))
        vfo850_grp.append(rs)
        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("vfoofst6", "850M Offset",
                              RadioSettingValueFloat(
                                0, 999.999999, (_freq_decode(
                                                _settings.vfoofst6) /
                                                1000000.0), 0.000001, 6))
            vfo850_grp.append(rs)

        rs = RadioSetting("rxtone6", "850M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone6))
        vfo850_grp.append(rs)

        rs = RadioSetting("txtone6", "850M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone6))
        vfo850_grp.append(rs)

        rs = RadioSetting("power6", "850M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power6))
        vfo850_grp.append(rs)

        rs = RadioSetting("narrow6", narrow6label,
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow6))
        vfo850_grp.append(rs)

        rs = RadioSetting("mute6", mute6label,
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute6))
        vfo850_grp.append(rs)

        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("shft_dir6", "850M Repeater",
                              RadioSettingValueBoolean(
                                _settings.shft_dir6))
        else:
            rs = RadioSetting("shft_dir6", "850M Shift Direction",
                              RadioSettingValueList(
                                DUPLEX_LIST,
                                current_index=_settings.shft_dir6))
        vfo850_grp.append(rs)

        rs = RadioSetting("compander6", "850M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander6))
        vfo850_grp.append(rs)

        rs = RadioSetting("scrambler6", scram6label,
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            current_index=_settings.scrambler6))
        vfo850_grp.append(rs)

        rs = RadioSetting("am_mode6", "850M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode6))
        vfo850_grp.append(rs)

        # ###########################

        rs = RadioSetting("vfomode_b", "Working Mode",
                          RadioSettingValueMap(wmmap,
                                               _settings.vfomode_b))
        vfob_grp.append(rs)

        rs = RadioSetting("vfochan_b", "Active/Work Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _chnum_decode(
                                                    _settings.vfochan_b)))
        vfob_grp.append(rs)

        rs = RadioSetting("vfofreq7", "Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode(
                                             _settings.vfofreq7) /
                                             1000000.0), 0.000001, 6))
        vfob_grp.append(rs)

        if self.MODEL != "KG-1000G Plus":
            rs = RadioSetting("vfoofst7", "Offset",
                              RadioSettingValueFloat(
                                0, 999.999999, (_freq_decode(
                                                _settings.vfoofst7) /
                                                1000000.0), 0.000001, 6))
            vfob_grp.append(rs)

        rs = RadioSetting("rxtone7", "Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone7))
        vfob_grp.append(rs)

        rs = RadioSetting("txtone7", "Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone7))
        vfob_grp.append(rs)
        rs = RadioSetting("power7", "Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power7))
        vfob_grp.append(rs)
        rs = RadioSetting("narrow7", narrow7label,
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow7))
        vfob_grp.append(rs)
        rs = RadioSetting("mute7", mute7label,
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute7))
        vfob_grp.append(rs)
        if self.MODEL == "KG-1000G Plus":
            rs = RadioSetting("shft_dir7", "Repeater",
                              RadioSettingValueBoolean(
                                _settings.shft_dir7))
        else:
            rs = RadioSetting("shft_dir7", "Shift Direction",
                              RadioSettingValueList(
                                DUPLEX_LIST,
                                current_index=_settings.shft_dir7))
        vfob_grp.append(rs)
        rs = RadioSetting("compander7", "Compander",
                          RadioSettingValueBoolean(
                            _settings.compander7))
        vfob_grp.append(rs)

        rs = RadioSetting("scrambler7", scram7label,
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            current_index=_settings.scrambler7))
        vfob_grp.append(rs)

        rs = RadioSetting("vfosquelch_b", "Squelch",
                          RadioSettingValueInteger(0, 9,
                                                   _settings.vfosquelch_b))
        vfob_grp.append(rs)
        rs = RadioSetting("vfostep_b", "Step",
                          RadioSettingValueList(
                            STEP_LIST,
                            current_index=_settings.vfostep_b))
        vfob_grp.append(rs)

        # Scan Group Settings
        def _decode(lst):
            LOG.debug("lst %s", lst)
            _str = ''.join([chr(c) for c in lst
                            if chr(c) in SCANNAME_CHARSET])
            return _str

        rs = RadioSetting("scan_a_act", "Scan A Active Group",
                          RadioSettingValueList(
                            SCAN_GROUP_LIST,
                            current_index=_settings.scan_a_act))
        scan_grp.append(rs)
        rs = RadioSetting("scan_b_act", "Scan B Active Group",
                          RadioSettingValueList(
                             SCAN_GROUP_LIST,
                             current_index=_settings.scan_b_act))
        scan_grp.append(rs)

        for i in range(1, 11):
            x = str(i)
            _str = _decode(getattr(_settings, 'scanname%s' % x))
            LOG.debug("ScanName %s", i)
            LOG.debug("is %s", _str)
            # CPS treats PPPPPP as a blank name as it is the factory reset
            # value"
            # The Radio treats PPPPPPP as a blank name and can display 8
            # chars"
            # Force Chirp to blank out the scan name if value is PPPPPPP
            # to match the radio"
            # Blank out the name if first 6 are spaces or null and the
            # 7th is a P to handle
            # firmware peculiarities in handling all 8 characters.
            if _str[0:7] == "PPPPPPP":
                _str = ""
            if self.MODEL != "KG-1000G Plus":
                if _str[0:7] == "\x00\x00\x00\x00\x00\x00P":
                    _str = ""
                elif _str[0:7] == "\x20\x20\x20\x20\x20\x20P":
                    _str = ""
            else:
                if _str[0:6] == "\x00\x00\x00\x00\x00\x00":
                    _str = ""
                elif _str[0:6] == "\x20\x20\x20\x20\x20\x20":
                    _str = ""
                elif (len(_str) == 2) & (_str[0:2] == "PP"):
                    _str = ""
            rs = RadioSetting("scanname" + x, "Scan Name " + x,
                              RadioSettingValueString(0, 8, _str))
            scanname_grp.append(rs)

            val = getattr(_settings, 'scanlower%i' % i)
            rs = RadioSetting("scanlower%i" % i, "Scan Lower %i" % i,
                              RadioSettingValueInteger(1, 999, val))
            scan_grp.append(rs)
            val = getattr(_settings, 'scanupper%i' % i)
            rs = RadioSetting("scanupper%i" % i, "Scan Upper %i" % i,
                              RadioSettingValueInteger(1, 999, val))
            scan_grp.append(rs)
# remote settings
        rs = RadioSetting("rc_power", "RC Power",
                          RadioSettingValueList(
                           RC_POWER_LIST,
                           current_index=_settings.rc_power))
        remote_grp.append(rs)

        def decode_remote_vals(self, setting):
            # parse the id value and replace all C with empty
            # C indicates the end of the id value
            code = ('%06X' % int(setting)).replace('C', '')
            return int(code), code

        def apply_remote_id(setting, obj, val):
            val = str(val)
            value = int(val.ljust(3, '0').ljust(6, 'C'), 16)
            setattr(obj, setting.get_name(), value)

        val_ani, code_val = decode_remote_vals(self, _settings.ani_edit)
        LOG.debug("ani = %s" % val_ani)
        val_ani = RadioSettingValueString(3, 6, code_val, False)
        val_ani.set_charset(dtmfchars)
        rs = RadioSetting("settings.ani_edit", "ANI Edit", val_ani)

        def apply_ani_id(setting, obj):
            LOG.debug("val= %s" % val_ani)
            if str(val_ani)[0] == "0":
                raise errors.RadioError("ANI EDIT must start with \
                                        Non-Zero Digit")
            val = str(val_ani)
            value = int(val.ljust(3, '0').ljust(6, 'C'), 16)
            obj.ani_edit = value
        rs.set_apply_callback(apply_ani_id, _settings)
        remote_grp.append(rs)

        val_mcc, code_val = decode_remote_vals(self, _settings.mcc_edit)
        LOG.debug("mcc = %s" % val_mcc)
        val_mcc = RadioSettingValueString(3, 6, code_val, False)
        val_mcc.set_charset(dtmfchars)
        rs = RadioSetting("mcc_edit", "MCC Edit", val_mcc)

        rs.set_apply_callback(apply_remote_id, _settings, val_mcc)
        remote_grp.append(rs)

        val_scc, code_val = decode_remote_vals(self, _settings.scc_edit)
        LOG.debug("scc = %s" % val_scc)
        val_scc = RadioSettingValueString(3, 6, code_val, False)
        val_scc.set_charset(dtmfchars)
        rs = RadioSetting("scc_edit", "SCC Edit", val_scc)

        rs.set_apply_callback(apply_remote_id, _settings, val_scc)
        remote_grp.append(rs)

        val_ctrl, code_val = decode_remote_vals(self, _settings.ctrl_edit)
        LOG.debug("ctrl = %s" % val_ctrl)
        val_ctrl = RadioSettingValueString(3, 6, code_val, False)
        val_ctrl.set_charset(dtmfchars)
        rs = RadioSetting("ctrl_edit", "CTRL Edit", val_ctrl)

        rs.set_apply_callback(apply_remote_id, _settings, val_ctrl)
        remote_grp.append(rs)

        # OEM Settings
        if self.MODEL != "KG-1000G Plus":
            _oem_name = _oem_str_decode(self._memobj.oem.display_name)
        else:
            displayname = self._memobj.oem.display_name
            _oem_name = _oem_str_decode_1000GPLUS(displayname)

        rs = RadioSetting("oem.display_name", "Area Message",
                          RadioSettingValueString(1, 8, _oem_name))
        oem_grp.append(rs)

        # FM RADIO PRESETS

        # memory stores raw integer value like 7600
        # radio will divide 7600 by 100 and interpret correctly at 76.0 MHz

        for i in range(1, 21):
            # chan = str(i)
            fmname = "FM_radio%i" % i
            fmlabel = "FM Preset %i" % i
            fmvalue = getattr(_settings, fmname)
            # some CPS versions store values with .01 MHz in error
            # eg 99.5 MHz is stored as 0x26df = 9951 dec = 99.51 MHz
            # even though the radio properly displays 99.5
            # this will drop the 0.01 MHz for Chirp Displayed values
            fmvalue = fmvalue // 10 / 10
            rs = RadioSetting(fmname, fmlabel,
                              RadioSettingValueFloat(76.0, 108.0,
                                                     fmvalue,
                                                     0.1, 1))
            fmradio_grp.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except Exception:
            LOG.exception("Failed to parse settings: %s")
            return None

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        if self._is_freq(element):
                            #  rescale freq values to match radio
                            # expected values
                            value = _freq_encode(
                                element[0].get_value()*1000000.0)
                            setattr(obj, setting, value)

                        elif self._is_fmradio_or_voltage(element):
                            #  rescale FM Radio values to match radio
                            # expected values
                            setattr(obj, setting,
                                    int(element.values()[0]._current * 100.0))

                        elif self._is_limit(element):
                            setattr(obj, setting,
                                    int(element[0].get_value()) * 10)

                        # Special VFO A Settings
                        #
                        elif self._is_chan(element):
                            value = _chnum_encode(element[0].get_value())
                            setattr(obj, setting, value)
                            continue
                        elif self._is_display_name(element):
                            string = element[0].get_value()
                            if self.MODEL != "KG-1000G Plus":
                                nameenc = _oem_str_encode(string)
                            else:
                                nameenc = _oem_str_encode_1000GPLUS(string)
                            for i in range(0, 8):
                                LOG.debug("nameenc %s" % (nameenc[i]))
                                self._memobj.oem.display_name[i] = \
                                    ord(nameenc[i])

                        elif self._is_scan_name(element):
                            string = element[0].get_value()
                            LOG.debug("string %s" % (string))
                            value = _str_encode(string)
                            LOG.debug("scaname %s" % (value))
                            setattr(obj, setting, value.encode())
                        else:
                            setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _is_freq(self, element):
        return ("rxfreq" in element.get_name() or
                "txoffset" in element.get_name() or
                "vfofreq" in element.get_name() or
                "vfoofst" in element.get_name())

    def _is_limit(self, element):
        return "limit" in element.get_name()

    def _is_fmradio_or_voltage(self, element):
        return ("FM_radio" in element.get_name() or
                "thr_vol_lvl" in element.get_name())

    def _is_chan(self, element):
        return ("vfochan" in element.get_name() or
                "pri_ch" in element.get_name())

    def _is_display_name(self, element):
        return "display_name" in element.get_name()

    def _is_scan_name(self, element):
        return "scanname" in element.get_name()


@directory.register
class KG1000GRadio(KG980PRadio):

    # """Wouxun KG-1000G"""
    VENDOR = "Wouxun"
    MODEL = "KG-1000G"


@directory.register
class KG1000GPlusRadio(KG980PRadio):

    # """Wouxun KG-1000G Plus"""
    VENDOR = "Wouxun"
    MODEL = "KG-1000G Plus"
