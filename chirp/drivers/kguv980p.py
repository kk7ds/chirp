# melvin.terechenok@gmail.com
# modify for KG-UV980P using KG-935G, KG-UV8H, KG-UV920P drivers as resources

# Copyright 2019 Pavel Milanes CO7WT <pavelmc@gmail.com>
#
# Based on the work of Krystian Struzik <toner_82@tlen.pl>
# who figured out the crypt used and made possible the
# Wuoxun KG-UV8D Plus driver, in which this work is based.
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

from pickle import FALSE, TRUE
import time
import os
import logging

from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettingValueMap, RadioSettings


LOG = logging.getLogger(__name__)

CMD_ID = 128    # \x80
CMD_END = 129   # \x81
CMD_RD = 130    # \x82
CMD_WR = 131    # \x83

# This is used to write the configuration of the radio base on info
# gleaned from the downloaded app. There are empty spaces and we honor
# them because we don't know what they are (yet) although we read the
# whole of memory.

config_map = (          # map address, write size, write count
    (0x4c,  12, 1),    # Mode PSW --  Display name
    (0x60,  44, 1),    # Freq Limits
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
TX_BLANK = 0x40
RX_BLANK = 0x80

CHARSET_NUMERIC = "0123456789"
CHARSET = "0123456789" + \
          ":;<=>?@" + \
          "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + \
          "[\]^_`" + \
          "abcdefghijklmnopqrstuvwxyz" + \
          "{|}~\x4E" + \
          " !\"#$%&'()*+,-./"

SCANNAME_CHARSET = "0123456789" + \
          ":;<=>?@" + \
          "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + \
          "[\]^_`" + \
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
VOICE_LIST = ["Off", "Chinese", "English"]
SC_REV_MAP = [('Timeout (TO)',  1),
              ('Carrier (CO)',  2),
              ('Stop (SE)',     3)]
TOT_MAP = [('%d min' % i, int('%02d' % i, 10)) for i in range(1, 61)]
TOA_LIST = ["Off", "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s", "10s"]
RING_LIST = ["Off", "1s", "2s", "3s", "4s", "5s", "6s", "7s",
             "8s", "9s", "10s"]
DTMF_ST_LIST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
PTT_ID_LIST = ["BOT", "EOT", "Both"]
PTT_ID_MAP = [('BOT',  1),
              ('EOT',  2),
              ('Both', 3)]
BACKLIGHT_LIST = ["Off", "Red", "Orange", "Green"]
SPEAKER_MAP = [('SPK_1',   1),
               ('SPK_2',   2),
               ('SPK_1+2', 3)]
RPT_MODE_LIST = ["Radio", "X-DIRPT", "X-TWRPT", "RPT-RX", "T-W RPT"]
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
PTT_ID_DELAY_MAP = [(str(x), x/100) for x in range(100, 1001, 100)]
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
HOLD_TIMES = ["Off"] + ["%s" % x for x in range(100, 5001, 100)]
PF1_SETTINGS = ["Off", "Stun", "Kill", "Monitor", "Inspection"]
ABR_LIST = ["Always", "1", "2", "3", "4", "5", "6", "7", "8",
            "9", "10", "11", "12", "13", "14", "15", "16", "17",
            "18", "19", "20", "Off"]
KEY_LIST = ["Off", "B/SW", "MENCH", "H-M-L", "VFO/MR", "SET-D", "TDR",
            "SQL", "SCAN", "FM-Radio", "Scan CTCSS", "Scan DCS"]
RC_POWER_LIST = ["RC Stop", "RC Open"]
ACTIVE_AREA_LIST = ["Area A - Left", "Area B - Right"]
TDR_LIST = ["TDR ON", "TDR OFF"]


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
        u16    limit_144M_ChA_rx_start;
        u16    limit_144M_ChA_rx_stop;
        u16    limit_70cm_rx_start;
        u16    limit_70cm_rx_stop;
        u16    limit_10m_rx_start;
        u16    limit_10m_rx_stop;
        u16    limit_6m_rx_start;
        u16    limit_6m_rx_stop;
        u16    limit_350M_rx_start;
        u16    limit_350M_rx_stop;
        u16    limit_850M_rx_start;
        u16    limit_850M_rx_stop;
        u16    limit_144M_ChA_tx_start;
        u16    limit_144M_ChA_tx_stop;
        u16    limit_70cm_tx_start;
        u16    limit_70cm_tx_stop;
        u16    limit_10m_tx_start;
        u16    limit_10m_tx_stop;
        u16    limit_6m_tx_start;
        u16    limit_6m_tx_stop;
        u16    limit_144M_ChB_rx_start;
        u16    limit_144M_ChB_rx_stop;
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
        u8  x8c3;
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
        u8  rpt_spk;
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
        u8  x8f6;
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
        char  scanname0[8]; // x968
        char  scanname1[8];
        char  scanname2[8];
        char  scanname3[8];
        char  scanname4[8];
        char  scanname5[8];
        char  scanname6[8];
        char  scanname7[8];
        char  scanname8[8];
        char  scanname9[8];
        char  scanname10[8];
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
                compander:1
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
    stopchar = FALSE
    for c in in_str:
        if c != 0x50 and stopchar == FALSE:
            if chr(c+48) in chirp_common.CHARSET_ASCII:
                out_str += chr(c+48)
        else:
            out_str += ''
            stopchar = TRUE
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
    LOG.debug("OEM Ouput String = %s", out_str)
    return out_str


def _str_decode(in_str):
    out_str = ''
    stopchar = FALSE
    for c in in_str:
        if c != 0x00 and stopchar == FALSE:
            if chr(c) in chirp_common.CHARSET_ASCII:
                out_str += chr(c)
        else:
            out_str += ''
            stopchar = TRUE
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
class KG980GRadio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):

    """Wouxun KG-UV980P"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV980P"
    _model = "KG-UV950R2"
    _file_ident = "980P"
    BAUD_RATE = 19200

    POWER_LEVELS = [chirp_common.PowerLevel("L", watts=1.0),
                    chirp_common.PowerLevel("M", watts=20.0),
                    chirp_common.PowerLevel("H", watts=50.0)]
    _mmap = ""

    def _checksum(self, data):
        cs = 0
        for byte in data:
            cs += ord(byte)
        return chr(cs % 256)

    # def _write_record_id(self):
    # _header = '\xda\x80\xff\x00\x58'
    #     LOG.error("Sent:\n%s" % util.hexprint(_header))
    # self.pipe.write(_header)

    def _write_record(self, cmd, payload=None):
        # build the packet
        _header = '\xda' + chr(cmd) + '\xff'

        _length = 0
        if payload:
            _length = len(payload)

        # update the length field
        _header += chr(_length)

        if payload:
            # calculate checksum then add it with the payload
            # to the packet and encrypt
            crc = self._checksum(_header[1:] + payload)
            # Checksum is only the lower 4 bits
            crc = chr(ord(crc) & 0xf)
            payload += crc
            _header += self.encrypt(payload)
        else:
            # calculate and add encrypted checksum to the packet
            crc = self._checksum(_header[1:])
            # Checksum is only the lower 4 bits
            crc = chr(ord(crc) & 0xf)
            _header += self.strxor(crc, '\x57')

        try:
            LOG.debug("Sent:\n%s" % util.hexprint(_header))
            self.pipe.write(_header)
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def _read_record(self):
        # read 4 chars for the header
        _header = self.pipe.read(4)
        # LOG.debug("header = " % util.hexprint(_header))
        if len(_header) != 4:
            raise errors.RadioError('Radio did not respond- header length')
        _length = ord(_header[3])
        _packet = self.pipe.read(_length)
        _rcs_xor = _packet[-1]
        _packet = self.decrypt(_packet)
        _cs = ord(self._checksum(_header[1:] + _packet))
        # It appears the checksum is only 4bits
        _cs = _cs & 0xf
        # read the checksum and decrypt it
        _rcs = ord(self.strxor(self.pipe.read(1), _rcs_xor))
        _rcs = _rcs & 0xf
        return (_rcs != _cs, _packet)

    def decrypt(self, data):
        result = ''
        for i in range(len(data)-1, 0, -1):
            result += self.strxor(data[i], data[i - 1])
        result += self.strxor(data[0], '\x57')
        return result[::-1]

    def encrypt(self, data):
        result = self.strxor('\x57', data[0])
        for i in range(1, len(data), 1):
            result += self.strxor(result[i - 1], data[i])
        return result

    def strxor(self, xora, xorb):
        return chr(ord(xora) ^ ord(xorb))

    # Identify the radio
    #
    # A Gotcha: the first identify packet returns a bad checksum, subsequent
    # attempts return the correct checksum... (well it does on my radio!)
    #
    # The ID record returned by the radio also includes the
    # current frequency range
    # as 4 bytes big-endian in 10Hz increments
    #
    # Offset
    #  0:10     Model, zero padded

    @classmethod
    def match_model(cls, filedata, filename):
        id = cls._file_ident
        return cls._file_ident in filedata[0x426:0x430]

    def _identify(self):
        """Do the identification dance"""
        for _i in range(0, 3):
            LOG.debug("ID try #"+str(_i))
            self._write_record(CMD_ID)
            _chksum_err, _resp = self._read_record()
            if len(_resp) == 0:
                raise Exception("Radio not responding")
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

    def _finish(self):
        self._write_record(CMD_END)

    def process_mmap(self):
        self._memobj = bitwise.parse(_MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = self._download()
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        self._upload()

    # TODO: Load all memory.
    # It would be smarter to only load the active areas and none of
    # the padding/unused areas. Padding still need to be investigated.
    def _download(self):
        """Talk to a wouxun KG-UV980P and do a download"""
        try:
            self._identify()
            return self._do_download(0, 32768, 64)
        except errors.RadioError:
            raise
        except Exception, e:
            LOG.exception('Unknown error during download process')
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def _do_download(self, start, end, blocksize):
        # allocate & fill memory
        LOG.debug("Start Download")
        image = ""
        for i in range(start, end, blocksize):
            req = chr(i / 256) + chr(i % 256) + chr(blocksize)
            self._write_record(CMD_RD, req)
            cs_error, resp = self._read_record()
            LOG.debug("Got:\n%s" % util.hexprint(resp))

            if cs_error:
                LOG.debug(util.hexprint(resp))
                raise Exception("Checksum error on read")
            # LOG.debug("Got:\n%s" % util.hexprint(resp))
            image += resp[2:]
            if self.status_fn:
                status = chirp_common.Status()
                status.cur = i
                status.max = end
                status.msg = "Cloning from radio"
                self.status_fn(status)
        self._finish()
        return memmap.MemoryMap(''.join(image))

    def _upload(self):
        """Talk to a wouxun KG-UV980P and do a upload"""
        try:
            self._identify()
            LOG.debug("Done with Upload Identify")
            # self._do_upload(0, 1856, 16)
            # LOG.debug("Done with Limits Upload")
            # self._do_upload(1856, 32768, 64)
            self._do_upload()
            LOG.debug("Done with Mem and Settings Upload")
            self._finish()
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        return

    def _do_upload(self):
        LOG.debug("Start of _do_upload")
        for ar, size, count in config_map:
            for addr in range(ar, ar + (size*count), size):
                start = ar
                ptr = start
                LOG.debug("ptr = " + str(ptr))
                end = ar + (size*count)
                blocksize = size
                LOG.debug("Start of loop in _do_upload index = "+str(addr))
                LOG.debug("Start %i End %i Size %i" % (start, end, blocksize))
                req = chr(addr / 256) + chr(addr % 256)
                LOG.debug("REQ")
                chunk = self.get_mmap()[addr:addr + blocksize]
                LOG.debug("CHUNK")
                self._write_record(CMD_WR, req + chunk)
    #            LOG.debug("Upload-- SENT : " % util.hexprint(_sent))
                cserr, ack = self._read_record()
                LOG.debug("Upload-- CSUM ERROR : " + str(cserr))
                LOG.debug("Upload-- RCVD :\n%s " % util.hexprint(ack))

                j = ord(ack[0]) * 256 + ord(ack[1])
                LOG.debug("j = " + str(j))
                LOG.debug("addr= " + str(addr))

                if cserr or j != addr:
                    raise Exception("Radio did not ack block %i" % addr)
                # ptr += blocksize
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = addr
                    status.max = 0x73e7
                    status.msg = "Cloning to radio"
                    self.status_fn(status)
        # self._finish()

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
#   MRT - Open up channel memory freq range to support RxFreq limit expansion
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
             '\nAll known CPS settings are implemented \n'
             '\n Additional settings found only on radio are also included'
             '\nMute, Compander and Scrambler are defaulted to '
             'QT, OFF , OFF for all channel memories\n'
             '\n'
             'Modification of Freq Limit Interfaces is done '
             'AT YOUR OWN RISK and '
             'may affect radio performance and may violate rules, '
             'regulations '
             'or laws in your jurisdiction.\n'
             )
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])
# MRT - corrected the Polarity decoding to match 980P implementation
# use 0x4000 bit mask for R
# MRT - 0x4000 appears to be the bit mask for Inverted DCS tones
# MRT - n DCS Tone will be 0x8xxx values - i DCS Tones will
# be 0xCxxx values.
# MRT - Chirp Uses N for n DCS Tones and R for i DCS Tones
# MRT - 980P encodes DCS tone # in decimal -  NOT OCTAL

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03d" % (val & 0x07FF))
            pol = (val & 0x4000) and "R" or "N"
            return code, pol
# MRT - Modified the function below to bitwise AND with 0x4000
# to check for 980P DCS Tone decoding
# MRT 0x8000 appears to be the bit mask for DCS tones
        tpol = False
# MRT Beta 1.1 - Fix the txtone compare to 0x8000 - was rxtone.
        if _mem.txtone != 0xFFFF and (_mem.txtone & 0x8000) == 0x8000:
            tcode, tpol = _get_dcs(_mem.txtone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.txtone != 0xFFFF and _mem.txtone != 0x0:
            mem.rtone = (_mem.txtone & 0x7fff) / 10.0
            txmode = "Tone"
        else:
            txmode = ""
# MRT - Modified the function below to bitwise AND with 0x4000
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

        LOG.debug("Got TX %s (%i) RX %s (%i)" %
                  (txmode, _mem.txtone, rxmode, _mem.rxtone))

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number
        _valid = self._memobj.valid[mem.number]

        LOG.debug("Mem %d valid is %s", number, _valid == MEM_VALID)
        LOG.debug("Rx Freq %s", _mem.rxfreq)
        if (_valid != MEM_VALID) & ((_mem.rxfreq == 0xFFFFFFFF) or
                                    _mem.rxfreq == 0x00000000):
            mem.empty = True
            _valid = 0xFF
            return mem
        elif (_valid != MEM_VALID) & ((_mem.rxfreq != 0xFFFFFFFF) and
                                      (_mem.rxfreq != 0x00000000)):
            LOG.debug("Changed chan %d %s", number, "to valid")
            _valid = MEM_VALID
            mem.empty = False
        else:
            _valid = MEM_VALID
            mem.empty = False
        mem.freq = int(_mem.rxfreq) * 10
        _rxfreq = _freq_decode(_mem.rxfreq)
        _txfreq = _freq_decode(_mem.txfreq)
        mem.freq = _rxfreq
        LOG.debug("Tx Freq is " + str(_mem.txfreq))
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
        else:
            mem.name = ''

        self._get_tone(_mem, mem)

        mem.skip = "" if bool(_mem.scan_add) else "S"

        LOG.debug("Mem Power " + str(_mem.power))
        pwr_index = _mem.power
        if _mem.power == 3:
            pwr_index = 2
            LOG.debug("Force Mem Power to" + str(pwr_index))
        if _mem.power:
            mem.power = self.POWER_LEVELS[pwr_index]
        else:
            mem.power = self.POWER_LEVELS[0]

        # mem.am_mode = _mem.power & 0x2

        # LOG.debug("Mem Power Index " + str(_mem.power))
#        mem.power = self.POWER_LEVELS[_mem.power]

        if _mem.am_mode:
            if _mem.isnarrow:
                mem.mode = "NAM"
            else:
                mem.mode = "AM"
        else:
            mem.mode = _mem.isnarrow and "NFM" or "FM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        _scram = _mem.scrambler
        if _mem.scrambler > 8:
            _scram = 0
        # rs = RadioSetting("scrambler", "Scrambler",
        #                   RadioSettingValueList(SCRAMBLER_LIST,
        #                                         SCRAMBLER_LIST[_scram]))
        # mem.extra.append(rs)

        # rs = RadioSetting("compander", "Compander",
        #                   RadioSettingValueBoolean(_mem.compander))
        # mem.extra.append(rs)

        # rs = RadioSetting("mute_mode", "Mute",
        #                   RadioSettingValueMap(MUTE_MODE_MAP,
        #                   _mem.mute_mode))
        # mem.extra.append(rs)

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            # MRT Change to 0x8000 to
            # set the bit for DCS- code is a decimal version
            # of the code # - NOT OCTAL
            val = int("%i" % code, 10) | 0x8000
            if pol == "R":
                # MRT Change to 0x4000 to set the bit for
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
        _valid = self._memobj.valid[mem.number]

        # if mem.empty:
        #     _mem.set_raw("\x00" * (_mem.size() / 8))
        #     self._memobj.valid[number] = 0
        #     self._memobj.names[number].set_raw("\x00" * (_nam.size() / 8))
        #     return

        if mem.empty:
            LOG.debug("Mem %s is Empty", number)
            self._memobj.valid[number] = 0xFF
            LOG.debug("Set Mem %s Not Valid", number)
            _mem.rxfreq = 0xFFFFFFFF
            LOG.debug("Set Rx Freq = FFFFFFF")
            _mem.txfreq = 0xFFFFFFFF
            LOG.debug("Set Tx Freq = FFFFFFF")
            self._memobj.names[number].set_raw("\xFF" * (_nam.size() / 8))
            LOG.debug("Name %s Cleared", number)
            # The following line is a hack to make CPS happy and not
            # show memory entries that were deleted with CHIRP
            # _mem=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            # LOG.debug("Set _mem = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF")
        else:
            LOG.debug("Mem %s is NOT Empty", number)
            if len(mem.name) > 0:
                LOG.debug("new name = %s", (mem.name))
                _mem.named = True
                name_encoded = _str_encode(mem.name)
                LOG.debug("name endcoded = %s", (name_encoded))
                LOG.debug("number = %s", (number))
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
            # MRT set the scrambler and compander to off by default
            # MRT This changes them in the channel memory
            _mem.scrambler = 0
            _mem.compander = 0
            # set the power
            if mem.power:
                _mem.power = self.POWER_LEVELS.index(mem.power)
            else:
                _mem.power = True
            LOG.debug("Set mem.power = %s" % mem.power)
            # pwr_index= mem.power
            # LOG.debug("pwr index = " + str(pwr_index))
            if str(mem.power) == "None":
                mem.power = self.POWER_LEVELS[1]
            index = self.POWER_LEVELS.index(mem.power)
            LOG.debug("index = %i", (index))
            if index == 2:
                _mem.power = 0b11
            else:
                _mem.power = self.POWER_LEVELS.index(mem.power)
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

            # if mem.power:
            #     _mem.power = self.POWER_LEVELS.index[mem.power]
            # else:
            #     _mem.power = True

            # MRT set to mute mode to QT (not QT+DTMF or QT*DTMF) by default
            # MRT This changes them in the channel memory
            _mem.mute_mode = 1

    def _get_settings(self):
        _settings = self._memobj.settings
        _limits = self._memobj.bandlimits
        _oem = self._memobj.oem
#        _vfoa = self._memobj.vfoa
#        _vfob = self._memobj.vfob
#        _scan = self._memobj.scan_groups
#        _call = self._memobj.call_groups
#        _callname = self._memobj.call_names
#        _fmpreset = self._memobj.fm_preset

        cfg_grp = RadioSettingGroup("cfg_grp", "Config Settings")
        cfg1_grp = RadioSettingGroup("cfg1_grp", "Config Settings 1")
        cfg2_grp = RadioSettingGroup("cfg2_grp", "Config Settings 2")
        vfoa_grp = RadioSettingGroup("vfoa_grp", "VFO A Settings")
        vfo150_grp = RadioSettingGroup("vfo150_grp", "150M Settings")
        vfo450_grp = RadioSettingGroup("vfo450_grp", "450M Settings")
        vfo20_grp = RadioSettingGroup("vfo20_grp", "20M Settings")
        vfo50_grp = RadioSettingGroup("vfo50_grp", "50M Settings")
        vfo350_grp = RadioSettingGroup("vfo350_grp", "350M Settings")
        vfo850_grp = RadioSettingGroup("vfo850_grp", "850M Settings")
        vfoabands_grp = RadioSettingGroup(
                            "vfoabands_grp", "VFO A Band Settings")
        vfob_grp = RadioSettingGroup("vfob_grp", "VFO B Settings")
        key_grp = RadioSettingGroup("key_grp", "Key Settings")
        fmradio_grp = RadioSettingGroup("fmradio_grp", "FM Broadcast Memory")
        lmt_grp = RadioSettingGroup("lmt_grp", "Frequency Limits")
        lmwrn_grp = RadioSettingGroup("lmwrn_grp", "USE AT YOUR OWN RISK")
        rxlim_grp = RadioSettingGroup("rxlim_grp", "Rx Limits")
        txlim_grp = RadioSettingGroup("txlim_grp", "Tx Limits")
        uhf_lmt_grp = RadioSettingGroup("uhf_lmt_grp", "UHF")
        vhf_lmt_grp = RadioSettingGroup("vhf_lmt_grp", "VHF")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")
        scan_grp = RadioSettingGroup("scan_grp", "Scan Group")
        scanname_grp = RadioSettingGroup("scanname_grp", "Scan Names")
        call_grp = RadioSettingGroup("call_grp", "Call Settings")
        remote_grp = RadioSettingGroup("remote_grp", "Remote Settings")
        extra_grp = RadioSettingGroup("extra_grp",
                                      "Extra Settings"
                                      "\nNOT Changed by RESET or CPS")
        vfo_grp = RadioSettingGroup("vfo_grp",
                                    "VFO Settings")
        memxtras_grp = RadioSettingGroup("memxtras_grp", "Memory Extras")
        extra_grp.append(oem_grp)
        cfg_grp.append(cfg1_grp)
        cfg_grp.append(cfg2_grp)
        lmt_grp.append(lmwrn_grp)
        lmt_grp.append(rxlim_grp)
        lmt_grp.append(txlim_grp)
        extra_grp.append(lmt_grp)
        vfo_grp.append(vfoa_grp)
        vfo_grp.append(vfob_grp)
        vfoa_grp.append(vfo150_grp)
        vfoa_grp.append(vfo450_grp)
        vfoa_grp.append(vfo20_grp)
        vfoa_grp.append(vfo50_grp)
        vfoa_grp.append(vfo350_grp)
        vfoa_grp.append(vfo850_grp)
        scan_grp.append(scanname_grp)

        group = RadioSettings(cfg_grp, vfo_grp, fmradio_grp,
                              remote_grp, scan_grp, extra_grp)

# Memory extras
        # rs = RadioSetting("_mem.mute_mode", "Mute Mode"+str(number),
        #                   RadioSettingValueBoolean(_mem.mute_mode))
        # memxtras_grp.append(rs)

# Configuration Settings

        rs = RadioSetting("roger", "Roger Beep",
                          RadioSettingValueList(ROGER_LIST,
                                                ROGER_LIST[_settings.
                                                           roger]))
        cfg1_grp.append(rs)

        rs = RadioSetting("beep", "Keypad Beep",
                          RadioSettingValueBoolean(_settings.beep))
        cfg1_grp.append(rs)

        rs = RadioSetting("voice", "Voice Guide",
                          RadioSettingValueBoolean(_settings.voice))
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
                              TOT_MAP, _settings.tot))
        cfg1_grp.append(rs)

        rs = RadioSetting("toa", "Timeout Alarm (TOA)",
                          RadioSettingValueList(
                              TOA_LIST, TOA_LIST[_settings.toa]))
        cfg1_grp.append(rs)

        rs = RadioSetting("ani_sw", "Caller ID Tx - ANI-SW",
                          RadioSettingValueBoolean(_settings.ani_sw))
        cfg1_grp.append(rs)

        rs = RadioSetting("ring", "Ring Time (Sec)",
                          RadioSettingValueList(
                              RING_LIST,
                              RING_LIST[_settings.ring]))
        cfg1_grp.append(rs)

        rs = RadioSetting("dtmfsf", "DTMF Sidetone",
                          RadioSettingValueList(
                              DTMF_ST_LIST,
                              DTMF_ST_LIST[_settings.dtmfsf]))
        cfg1_grp.append(rs)

        rs = RadioSetting("ptt_id", "Caller ID Tx Mode (PTT_ID)",
                          RadioSettingValueMap(PTT_ID_MAP, _settings.ptt_id))
        cfg1_grp.append(rs)

        rs = RadioSetting("wt_led", "Standby / WT LED",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              BACKLIGHT_LIST[_settings.wt_led]))
        cfg1_grp.append(rs)

        rs = RadioSetting("tx_led", "TX LED",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              BACKLIGHT_LIST[_settings.tx_led]))
        cfg1_grp.append(rs)

        rs = RadioSetting("rx_led", "Rx LED",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              BACKLIGHT_LIST[_settings.rx_led]))
        cfg1_grp.append(rs)

        rs = RadioSetting("prich_sw", "Priority Channel Scan",
                          RadioSettingValueBoolean(_settings.prich_sw))
        cfg1_grp.append(rs)

        rs = RadioSetting("spk_cont", "Speaker Control",
                          RadioSettingValueMap(
                              SPEAKER_MAP,
                              _settings.spk_cont))
        cfg1_grp.append(rs)

        rs = RadioSetting("autolock", "Autolock",
                          RadioSettingValueBoolean(_settings.autolock))
        cfg1_grp.append(rs)

        rs = RadioSetting("low_v", "Low Voltage Shutoff",
                          RadioSettingValueBoolean(_settings.low_v))
        cfg1_grp.append(rs)

        rs = RadioSetting("fan", "Fan Mode",
                          RadioSettingValueList(
                              FAN_MODE_LIST,
                              FAN_MODE_LIST[_settings.fan]))
        cfg1_grp.append(rs)

        rs = RadioSetting("apo_time", "Auto Power-Off (Min)",
                          RadioSettingValueList(
                              APO_TIME_LIST,
                              APO_TIME_LIST[_settings.apo_time]))
        cfg1_grp.append(rs)

        rs = RadioSetting("alert", "Alert Pulse (Hz)",
                          RadioSettingValueMap(ALERT_MAP, _settings.alert))
        cfg1_grp.append(rs)
        rs = RadioSetting("m_pwr", "Medium Power Level (W)",
                          RadioSettingValueMap(M_POWER_MAP,
                                               _settings.m_pwr))
        cfg1_grp.append(rs)

        rs = RadioSetting("rpt_set_model", "Model (RPT-SET)",
                          RadioSettingValueList(
                              RPT_MODE_LIST,
                              RPT_MODE_LIST[_settings.rpt_set_model]))
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
                              DTMF_TIMES[_settings.dtmf_time]))
        cfg2_grp.append(rs)
        rs = RadioSetting("dtmf_int", "DTMF Interval (ms)",
                          RadioSettingValueList(
                              DTMF_INTERVALS,
                              DTMF_INTERVALS[_settings.dtmf_int]))
        cfg2_grp.append(rs)

        rs = RadioSetting("sc_qt", "CTCSS/DCS Scan",
                          RadioSettingValueMap(
                              SC_QT_MAP, _settings.sc_qt))
        cfg2_grp.append(rs)

        rs = RadioSetting("pri_ch", "Priority Channel",
                          RadioSettingValueInteger(
                              1, 999, _chnum_decode(_settings.pri_ch)))
        cfg2_grp.append(rs)

        rs = RadioSetting("ptt_id_dly", "Caller ID Tx Delay PTT-ID-DLY (ms)",
                          RadioSettingValueMap(PTT_ID_DELAY_MAP,
                                               _settings.ptt_id_dly))
        cfg2_grp.append(rs)

        rs = RadioSetting("rc_sw", "Remote Control RC-SW",
                          RadioSettingValueBoolean(_settings.rc_sw))
        cfg2_grp.append(rs)

        rs = RadioSetting("scan_det", "Scan DET",
                          RadioSettingValueBoolean(_settings.scan_det))
        cfg2_grp.append(rs)

        rs = RadioSetting("menu", "Menu Available",
                          RadioSettingValueBoolean(_settings.menu))
        cfg2_grp.append(rs)

        rs = RadioSetting("thr_vol_tx", "Threshold Voltage Tx",
                          RadioSettingValueBoolean(_settings.thr_vol_tx))
        cfg2_grp.append(rs)

        rs = RadioSetting("hold_time_rpt", "Hold Time of Repeat (ms)",
                          RadioSettingValueList(
                              HOLD_TIMES,
                              HOLD_TIMES[_settings.hold_time_rpt]))
        cfg2_grp.append(rs)

        rs = RadioSetting("auto_am", "Auto AM",
                          RadioSettingValueBoolean(_settings.auto_am))
        cfg2_grp.append(rs)

        rs = RadioSetting("rpt_tone", "Repeat Tone",
                          RadioSettingValueBoolean(_settings.rpt_tone))
        cfg2_grp.append(rs)

        rs = RadioSetting("pf1_set", "PF1 setting",
                          RadioSettingValueList(
                              PF1_SETTINGS,
                              PF1_SETTINGS[_settings.pf1_set]))
        cfg2_grp.append(rs)

        rs = RadioSetting("settings.thr_vol_lvl", "Threshold Voltage Level",
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
        val_psw = int(_code)
        LOG.debug("psw = %s" % val_psw)
        val_psw = RadioSettingValueString(6, 6, _code, False)
        val_psw.set_charset(dtmfchars)
        rs = RadioSetting("oem.mode_psw", "MODE PSW", val_psw)

        def apply_psw_id(setting, obj):
            val2 = hex(int(str(val_psw), 16))
            LOG.debug("val2= %s" % val2)
            if (int(val2, 16) != 0):
                while len(val2) < 8:
                    val2 += '0'
            psw = int(str(val2), 16)
            LOG.debug("val3= %s" % psw)
            LOG.debug("val= %s" % val_psw)
            obj.mode_psw = psw
        rs.set_apply_callback(apply_psw_id, _oem)
        cfg2_grp.append(rs)

        rs = RadioSetting("ABR", "ABR (Backlight On Time)",
                          RadioSettingValueList(
                              ABR_LIST,
                              ABR_LIST[_settings.ABR]))
        cfg2_grp.append(rs)

        rs = RadioSetting("KeyA", "Key A",
                          RadioSettingValueList(
                              KEY_LIST,
                              KEY_LIST[_settings.KeyA]))
        cfg2_grp.append(rs)
        rs = RadioSetting("KeyB", "Key B",
                          RadioSettingValueList(
                              KEY_LIST,
                              KEY_LIST[_settings.KeyB]))
        cfg2_grp.append(rs)
        rs = RadioSetting("KeyC", "Key C",
                          RadioSettingValueList(
                              KEY_LIST,
                              KEY_LIST[_settings.KeyC]))
        cfg2_grp.append(rs)

        rs = RadioSetting("act_area", "Active Area (BAND)",
                          RadioSettingValueList(
                              ACTIVE_AREA_LIST,
                              ACTIVE_AREA_LIST[_settings.act_area]))
        cfg2_grp.append(rs)
        rs = RadioSetting("tdr_off", "TDR",
                          RadioSettingValueList(
                              TDR_LIST,
                              TDR_LIST[_settings.tdr_off]))
        cfg2_grp.append(rs)

# Freq Limits settings

        # Convert Integer back to correct limit HEX value:

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_144M_ChA_rx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChA_rx_start",
                          "144M ChA Rx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_144M_ChA_rx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChA_rx_stop",
                          "144M ChA Rx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_144M_ChB_rx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChB_rx_start",
                          "144M ChB Rx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_144M_ChB_rx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChB_rx_stop",
                          "144M ChB Rx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_70cm_rx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_70cm_rx_start",
                          "450M Rx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_70cm_rx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_70cm_rx_stop",
                          "450M Rx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_10m_rx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_10m_rx_start",
                          "20M Rx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_10m_rx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_10m_rx_stop",
                          "20M Rx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_6m_rx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_6m_rx_start",
                          "50M Rx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_6m_rx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_6m_rx_stop",
                          "50M Rx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_350M_rx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_350M_rx_start",
                          "350M Rx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_350M_rx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_350M_rx_stop",
                          "350M Rx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_850M_rx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_850M_rx_start",
                          "850M Rx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_850M_rx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_850M_rx_stop",
                          "850M Rx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        rxlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_144M_ChA_tx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChA_tx_start",
                          "144M ChA Tx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_144M_ChA_tx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_144M_ChA_tx_stop",
                          "144M ChA Tx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_70cm_tx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_70cm_tx_start",
                          "450M Tx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_70cm_tx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_70cm_tx_stop",
                          "450M tx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_10m_tx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_10m_tx_start",
                          "20M tx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_10m_tx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_10m_tx_stop",
                          "20M tx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_6m_tx_start, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_6m_tx_start",
                          "50M tx Lower Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

        _temp = str(hex(int("%i" %
                    self._memobj.bandlimits.limit_6m_tx_stop, 10)))
        _temp = int(int(_temp[2:])/10.0)
        val = RadioSettingValueInteger(0, 999, _temp)
        rs = RadioSetting("bandlimits.limit_6m_tx_stop",
                          "50M tx Upper Limit (MHz)",
                          RadioSettingValueInteger(0, 999,
                                                   val))
        txlim_grp.append(rs)

# VFO Settings
        rs = RadioSetting("vfomode_a", "VFO A Working Mode",
                          RadioSettingValueMap(WORKMODE_MAP,
                                               _settings.vfomode_a))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfoband_a", "VFO A Current Band",
                          RadioSettingValueMap(VFOBAND_MAP,
                                               _settings.vfoband_a))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfochan_a", "VFO A Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _chnum_decode(
                                                    _settings.vfochan_a)))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfosquelch_a", "VFO A Squelch",
                          RadioSettingValueInteger(0, 9,
                                                   _settings.vfosquelch_a))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfostep_a", "VFO A Step",
                          RadioSettingValueList(
                            STEP_LIST,
                            STEP_LIST[_settings.vfostep_a]))
        vfoa_grp.append(rs)

######################

        rs = RadioSetting("vfofreq1", "VFO 150M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq1) /
                                             1000000.0), 0.000001, 6))
        vfo150_grp.append(rs)

        rs = RadioSetting("vfoofst1", "VFO 150M Offset",
                          RadioSettingValueFloat(
                              0, 999.999999, (_freq_decode
                                              (_settings.vfoofst1) /
                                              1000000.0), 0.000001, 6))
        vfo150_grp.append(rs)

        rs = RadioSetting("rxtone1", "VFO 150M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone1))
        vfo150_grp.append(rs)

        rs = RadioSetting("txtone1", "VFO 150M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone1))
        vfo150_grp.append(rs)

        rs = RadioSetting("power1", "VFO 150M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power1))
        vfo150_grp.append(rs)

        rs = RadioSetting("narrow1", "VFO 150M Bandwidth",
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow1))
        vfo150_grp.append(rs)

        rs = RadioSetting("mute1", "VFO 150M Mute Mode",
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute1))
        vfo150_grp.append(rs)

        rs = RadioSetting("shft_dir1", "VFO 150M Shift Direction",
                          RadioSettingValueList(
                            DUPLEX_LIST,
                            DUPLEX_LIST[_settings.shft_dir1]))
        vfo150_grp.append(rs)

        rs = RadioSetting("compander1", "VFO 150M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander1))
        vfo150_grp.append(rs)

        rs = RadioSetting("scrambler1", "VFO 150M Scrambler",
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            SCRAMBLER_LIST[_settings.scrambler1]))
        vfo150_grp.append(rs)
        rs = RadioSetting("am_mode1", "VFO 150M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode1))
        vfo150_grp.append(rs)

############################

        rs = RadioSetting("vfofreq2", "VFO 450M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq2) /
                                             1000000.0), 0.000001, 6))
        vfo450_grp.append(rs)

        rs = RadioSetting("vfoofst2", "VFO 450M Offset",
                          RadioSettingValueFloat(
                              0, 999.999999, (_freq_decode
                                              (_settings.vfoofst2) /
                                              1000000.0), 0.000001, 6))
        vfo450_grp.append(rs)

        rs = RadioSetting("rxtone2", "VFO 450M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone2))
        vfo450_grp.append(rs)

        rs = RadioSetting("txtone2", "VFO 450M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone2))
        vfo450_grp.append(rs)

        rs = RadioSetting("power2", "VFO 450M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power2))
        vfo450_grp.append(rs)

        rs = RadioSetting("narrow2", "VFO 450M Bandwidth",
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow2))
        vfo450_grp.append(rs)

        rs = RadioSetting("mute2", "VFO 450M Mute Mode",
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute2))
        vfo450_grp.append(rs)

        rs = RadioSetting("shft_dir2", "VFO 450M Shift Direction",
                          RadioSettingValueList(
                            DUPLEX_LIST,
                            DUPLEX_LIST[_settings.shft_dir2]))
        vfo450_grp.append(rs)

        rs = RadioSetting("compander2", "VFO 450M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander2))
        vfo450_grp.append(rs)

        rs = RadioSetting("scrambler2", "VFO 450M Scrambler",
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            SCRAMBLER_LIST[_settings.scrambler2]))
        vfo450_grp.append(rs)

        rs = RadioSetting("am_mode2", "VFO 450M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode2))
        vfo450_grp.append(rs)

############################

        rs = RadioSetting("vfofreq3", "VFO 20M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq3) /
                                             1000000.0), 0.000001, 6))
        vfo20_grp.append(rs)

        rs = RadioSetting("vfoofst3", "VFO 20M Offset",
                          RadioSettingValueFloat(
                              0, 999.999999, (_freq_decode
                                              (_settings.vfoofst3) /
                                              1000000.0), 0.000001, 6))
        vfo20_grp.append(rs)

        rs = RadioSetting("rxtone3", "VFO 20M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone3))
        vfo20_grp.append(rs)

        rs = RadioSetting("txtone3", "VFO 20M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone3))
        vfo20_grp.append(rs)

        rs = RadioSetting("power3", "VFO 20M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power3))
        vfo20_grp.append(rs)

        rs = RadioSetting("narrow3", "VFO 20M Bandwidth",
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow3))
        vfo20_grp.append(rs)

        rs = RadioSetting("mute3", "VFO 20M Mute Mode",
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute3))
        vfo20_grp.append(rs)

        rs = RadioSetting("shft_dir3", "VFO 20M Shift Direction",
                          RadioSettingValueList(
                            DUPLEX_LIST,
                            DUPLEX_LIST[_settings.shft_dir3]))
        vfo20_grp.append(rs)

        rs = RadioSetting("compander3", "VFO 20M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander3))
        vfo20_grp.append(rs)

        rs = RadioSetting("scrambler3", "VFO 20M Scrambler",
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            SCRAMBLER_LIST[_settings.scrambler3]))
        vfo20_grp.append(rs)

        rs = RadioSetting("am_mode3", "VFO 20M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode3))
        vfo20_grp.append(rs)

############################

        rs = RadioSetting("vfofreq4", "VFO 50M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq4) /
                                             1000000.0), 0.000001, 6))
        vfo50_grp.append(rs)

        rs = RadioSetting("vfoofst4", "VFO 50M Offset",
                          RadioSettingValueFloat(
                              0, 999.999999, (_freq_decode
                                              (_settings.vfoofst4) /
                                              1000000.0), 0.000001, 6))
        vfo50_grp.append(rs)

        rs = RadioSetting("rxtone4", "VFO 50M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone4))
        vfo50_grp.append(rs)

        rs = RadioSetting("txtone4", "VFO 50M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone4))
        vfo50_grp.append(rs)

        rs = RadioSetting("power4", "VFO 50M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power4))
        vfo50_grp.append(rs)

        rs = RadioSetting("narrow4", "VFO 50M Bandwidth",
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow4))
        vfo50_grp.append(rs)

        rs = RadioSetting("mute4", "VFO 50M Mute Mode",
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute4))
        vfo50_grp.append(rs)

        rs = RadioSetting("shft_dir4", "VFO 50M Shift Direction",
                          RadioSettingValueList(
                            DUPLEX_LIST,
                            DUPLEX_LIST[_settings.shft_dir4]))
        vfo50_grp.append(rs)

        rs = RadioSetting("compander4", "VFO 50M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander4))
        vfo50_grp.append(rs)

        rs = RadioSetting("scrambler4", "VFO 50M Scrambler",
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            SCRAMBLER_LIST[_settings.scrambler4]))
        vfo50_grp.append(rs)

        rs = RadioSetting("am_mode4", "VFO 50M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode4))
        vfo50_grp.append(rs)
############################
        rs = RadioSetting("vfofreq5", "VFO 350M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq5) /
                                             1000000.0), 0.000001, 6))
        vfo350_grp.append(rs)

        rs = RadioSetting("vfoofst5", "VFO 350M Offset",
                          RadioSettingValueFloat(
                              0, 999.999999, (_freq_decode
                                              (_settings.vfoofst5) /
                                              1000000.0), 0.000001, 6))
        vfo350_grp.append(rs)

        rs = RadioSetting("rxtone5", "VFO 350M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone5))
        vfo350_grp.append(rs)

        rs = RadioSetting("txtone5", "VFO 350M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone5))
        vfo350_grp.append(rs)

        rs = RadioSetting("power5", "VFO 350M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power5))
        vfo350_grp.append(rs)

        rs = RadioSetting("narrow5", "VFO 350M Bandwidth",
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow5))
        vfo350_grp.append(rs)

        rs = RadioSetting("mute5", "VFO 350M Mute Mode",
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute5))
        vfo350_grp.append(rs)

        rs = RadioSetting("shft_dir5", "VFO 350M Shift Direction",
                          RadioSettingValueList(
                            DUPLEX_LIST,
                            DUPLEX_LIST[_settings.shft_dir5]))
        vfo350_grp.append(rs)

        rs = RadioSetting("compander5", "VFO 350M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander5))
        vfo350_grp.append(rs)

        rs = RadioSetting("scrambler5", "VFO 350M Scrambler",
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            SCRAMBLER_LIST[_settings.scrambler5]))
        vfo350_grp.append(rs)

        rs = RadioSetting("am_mode5", "VFO 350M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode5))
        vfo350_grp.append(rs)

# ############################
        rs = RadioSetting("vfofreq6", "VFO 850M Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq6) /
                                             1000000.0), 0.000001, 6))
        vfo850_grp.append(rs)

        rs = RadioSetting("vfoofst6", "VFO 850M Offset",
                          RadioSettingValueFloat(
                              0, 999.999999, (_freq_decode
                                              (_settings.vfoofst6) /
                                              1000000.0), 0.000001, 6))
        vfo850_grp.append(rs)

        rs = RadioSetting("rxtone6", "VFO 850M Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone6))
        vfo850_grp.append(rs)

        rs = RadioSetting("txtone6", "VFO 850M Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone6))
        vfo850_grp.append(rs)

        rs = RadioSetting("power6", "VFO 850M Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power6))
        vfo850_grp.append(rs)

        rs = RadioSetting("narrow6", "VFO 850M Bandwidth",
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow6))
        vfo850_grp.append(rs)

        rs = RadioSetting("mute6", "VFO 850M Mute Mode",
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute6))
        vfo850_grp.append(rs)

        rs = RadioSetting("shft_dir6", "VFO 850M Shift Direction",
                          RadioSettingValueList(
                            DUPLEX_LIST,
                            DUPLEX_LIST[_settings.shft_dir6]))
        vfo850_grp.append(rs)

        rs = RadioSetting("compander6", "VFO 850M Compander",
                          RadioSettingValueBoolean(
                            _settings.compander6))
        vfo850_grp.append(rs)

        rs = RadioSetting("scrambler6", "VFO 850M Scrambler",
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            SCRAMBLER_LIST[_settings.scrambler6]))
        vfo850_grp.append(rs)

        rs = RadioSetting("am_mode6", "VFO 850M AM Mode",
                          RadioSettingValueBoolean(
                            _settings.am_mode6))
        vfo850_grp.append(rs)

############################

        rs = RadioSetting("vfomode_b", "VFO B Working Mode",
                          RadioSettingValueMap(WORKMODE_MAP,
                                               _settings.vfomode_b))
        vfob_grp.append(rs)

        rs = RadioSetting("vfochan_b", "VFO B Work Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _chnum_decode(
                                                    _settings.vfochan_b)))
        vfob_grp.append(rs)

        rs = RadioSetting("vfofreq7", "VFO B Freq",
                          RadioSettingValueFloat(
                             0, 999.999999, (_freq_decode
                                             (_settings.vfofreq7) /
                                             1000000.0), 0.000001, 6))
        vfob_grp.append(rs)

        rs = RadioSetting("vfoofst7", "VFO B Offset",
                          RadioSettingValueFloat(
                              0, 999.999999, (_freq_decode
                                              (_settings.vfoofst7) /
                                              1000000.0), 0.000001, 6))
        vfob_grp.append(rs)

        rs = RadioSetting("rxtone7", "VFOB Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.rxtone7))
        vfob_grp.append(rs)

        rs = RadioSetting("txtone7", "VFOB Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _settings.txtone7))
        vfob_grp.append(rs)
        rs = RadioSetting("power7", "VFOB Power",
                          RadioSettingValueMap(
                            POWER_MAP, _settings.power7))
        vfob_grp.append(rs)
        rs = RadioSetting("narrow7", "VFOB Bandwidth",
                          RadioSettingValueMap(
                            BANDWIDTH_MAP, _settings.narrow7))
        vfob_grp.append(rs)
        rs = RadioSetting("mute7", "VFOB Mute Mode",
                          RadioSettingValueMap(
                            MUTE_MODE_MAP, _settings.mute7))
        vfob_grp.append(rs)
        rs = RadioSetting("shft_dir7", "VFOB Shift Direction",
                          RadioSettingValueList(
                            DUPLEX_LIST,
                            DUPLEX_LIST[_settings.shft_dir7]))
        vfob_grp.append(rs)
        rs = RadioSetting("compander7", "VFOB Compander",
                          RadioSettingValueBoolean(
                            _settings.compander7))
        vfob_grp.append(rs)

        rs = RadioSetting("scrambler7", "VFOB Scrambler",
                          RadioSettingValueList(
                            SCRAMBLER_LIST,
                            SCRAMBLER_LIST[_settings.scrambler7]))
        vfob_grp.append(rs)

        rs = RadioSetting("vfosquelch_b", "VFO B Squelch",
                          RadioSettingValueInteger(0, 9,
                                                   _settings.vfosquelch_b))
        vfob_grp.append(rs)
        rs = RadioSetting("vfostep_b", "VFO B Step",
                          RadioSettingValueList(
                            STEP_LIST,
                            STEP_LIST[_settings.vfostep_b]))
        vfob_grp.append(rs)
        # rs = RadioSetting("am_mode7", "VFOB AM Mode",
        #                   RadioSettingValueBoolean(
        #                     _settings.am_mode7))
        # vfob_grp.append(rs)

# Scan Group Settings
        def _decode(lst):
            _str = ''.join([chr(c) for c in lst
                            if chr(c) in SCANNAME_CHARSET])
            return _str

        rs = RadioSetting("scan_a_act", "Scan A Active Group",
                          RadioSettingValueList(
                            SCAN_GROUP_LIST,
                            SCAN_GROUP_LIST[_settings.scan_a_act]))
        scan_grp.append(rs)
        rs = RadioSetting("scan_b_act", "Scan B Active Group",
                          RadioSettingValueList(
                             SCAN_GROUP_LIST,
                             SCAN_GROUP_LIST[_settings.scan_b_act]))
        scan_grp.append(rs)

        for i in range(1, 11):
            x = str(i)
            _str = _decode(eval("_settings.scanname"+x))
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
            elif _str[0:7] == "\x00\x00\x00\x00\x00\x00P":
                _str = ""
            elif _str[0:7] == "\x20\x20\x20\x20\x20\x20P":
                _str = ""
            rs = RadioSetting("scanname" + x, "Scan Name " + x,
                              RadioSettingValueString(0, 8, _str))
            # rs = RadioSetting("scanname"+x, "Scan Name "+x, val)
            scanname_grp.append(rs)

            scngrp = str(i)
            rs = RadioSetting("scanlower"+scngrp, "Scan Lower "+scngrp,
                              RadioSettingValueInteger(1, 999,
                                                       eval(
                                                        "_settings.\
                                                        scanlower" +
                                                        scngrp)))
            scan_grp.append(rs)
            rs = RadioSetting("scanupper"+scngrp, "Scan Upper "+scngrp,
                              RadioSettingValueInteger(1, 999,
                                                       eval(
                                                        "_settings.scanupper" +
                                                        scngrp)))
            scan_grp.append(rs)
# remote settings
        rs = RadioSetting("rc_power", "RC Power",
                          RadioSettingValueList(
                           RC_POWER_LIST,
                           RC_POWER_LIST[_settings.rc_power]))
        remote_grp.append(rs)

        _code = ''
        test = int(_settings.ani_edit)
        _codeobj = '0x{0:0{1}X}'.format(test, 6)
        LOG.debug("codeobj = %s" % _codeobj)
        _ani = str(_codeobj)
        for i in range(2, 8):
            LOG.debug("ani[i] = %s" % _ani[i])
            if _ani[i] in dtmfchars:
                _code += _ani[i]
        val_ani = int(_code)
        LOG.debug("ani = %s" % val_ani)
        val_ani = RadioSettingValueString(3, 6, _code, False)
        val_ani.set_charset(dtmfchars)
        rs = RadioSetting("settings.ani_edit", "ANI Edit", val_ani)

        def apply_ani_id(setting, obj):
            temp = list()
            LOG.debug("val= %s" % val_ani)
            if str(val_ani)[0] == "0":
                raise errors.RadioError("ANI EDIT must start with \
                                        Non-Zero Digit")
            val2 = hex(int(str(val_ani), 16))
            LOG.debug("val2= %s" % val2)
            if (int(val2, 16) != 0):
                while len(val2) < 5:
                    val2 += '0'
                while len(val2) < 8:
                    val2 += 'C'
            ani = int(str(val2), 16)
            LOG.debug("ani= %s" % ani)
            LOG.debug("val= %s" % val_ani)
            obj.ani_edit = ani
        rs.set_apply_callback(apply_ani_id, _settings)
        remote_grp.append(rs)

        _code = ''
        test = int(_settings.mcc_edit)
        _codeobj = '0x{0:0{1}X}'.format(test, 6)
        LOG.debug("codeobj = %s" % _codeobj)
        _mcc = str(_codeobj)
        for i in range(2, 8):
            LOG.debug("mcc[i] = %s" % _mcc[i])
            if _mcc[i] in dtmfchars:
                _code += _mcc[i]
        val_mcc = int(_code)
        LOG.debug("mcc = %s" % val_mcc)
        val_mcc = RadioSettingValueString(3, 6, _code, False)
        val_mcc.set_charset(dtmfchars)
        rs = RadioSetting("mcc_edit", "MCC Edit", val_mcc)

        def apply_mcc_id(setting, obj):
            val2 = hex(int(str(val_mcc), 16))
            LOG.debug("val2= %s" % val2)
            if (int(val2, 16) != 0):
                while len(val2) < 5:
                    val2 += '0'
                while len(val2) < 8:
                    val2 += 'C'
            mcc = int(str(val2), 16)
            LOG.debug("val3= %s" % mcc)
            LOG.debug("val= %s" % val_mcc)
            obj.mcc_edit = mcc
        rs.set_apply_callback(apply_mcc_id, _settings)
        remote_grp.append(rs)

        _code = ''
        test = int(_settings.scc_edit)
        _codeobj = '0x{0:0{1}X}'.format(test, 6)
        LOG.debug("codeobj = %s" % _codeobj)
        _scc = str(_codeobj)
        for i in range(2, 8):
            LOG.debug("scc[i] = %s" % _scc[i])
            if _scc[i] in dtmfchars:
                _code += _scc[i]
        val_scc = int(_code)
        LOG.debug("scc = %s" % val_scc)
        val_scc = RadioSettingValueString(3, 6, _code, False)
        val_scc.set_charset(dtmfchars)
        rs = RadioSetting("scc_edit", "SCC Edit", val_scc)

        def apply_scc_id(setting, obj):
            val2 = hex(int(str(val_scc), 16))
            LOG.debug("val2= %s" % val2)
            if (int(val2, 16) != 0):
                while len(val2) < 5:
                    val2 += '0'
                while len(val2) < 8:
                    val2 += 'C'
            scc = int(str(val2), 16)
            LOG.debug("val3= %s" % scc)
            LOG.debug("val= %s" % val_scc)
            obj.scc_edit = scc
        rs.set_apply_callback(apply_scc_id, _settings)
        remote_grp.append(rs)

        _code = ''
        test = int(_settings.ctrl_edit)
        _codeobj = '0x{0:0{1}X}'.format(test, 6)
        LOG.debug("codeobj = %s" % _codeobj)
        _ctrl = str(_codeobj)
        for i in range(2, 8):
            LOG.debug("ctrl[i] = %s" % _ctrl[i])
            if _ctrl[i] in dtmfchars:
                _code += _ctrl[i]
        val_ctrl = int(_code)
        LOG.debug("ctrl = %s" % val_ctrl)
        val_ctrl = RadioSettingValueString(3, 6, _code, False)
        val_ctrl.set_charset(dtmfchars)
        rs = RadioSetting("ctrl_edit", "CTRL Edit", val_ctrl)

        def apply_ctrl_id(setting, obj):
            val2 = hex(int(str(val_ctrl), 16))
            LOG.debug("val2= %s" % val2)
            if (int(val2, 16) != 0):
                while len(val2) < 5:
                    val2 += '0'
                while len(val2) < 8:
                    val2 += 'C'
            ctrl = int(str(val2), 16)
            LOG.debug("val3= %s" % ctrl)
            LOG.debug("val= %s" % val_ctrl)
            obj.ctrl_edit = ctrl
        rs.set_apply_callback(apply_ctrl_id, _settings)
        remote_grp.append(rs)

# OEM Settings

        _oem_name = _oem_str_decode(self._memobj.oem.display_name)
        rs = RadioSetting("oem.display_name", "Display Banner Text",
                          RadioSettingValueString(1, 8, _oem_name))
        oem_grp.append(rs)

# FM RADIO PRESETS

# memory stores raw integer value like 7600
# radio will divide 7600 by 100 and interpret correctly at 76.0Mhz
        #
        # FM Radio Presets Settings
        #

        for i in range(1, 21):
            chan = str(i)
            rs = RadioSetting("FM_radio" + chan, "FM Preset " + chan,
                              RadioSettingValueFloat(76.0, 108.0,
                                                     eval(
                                                        "_settings.FM_radio" +
                                                        chan)/100.0,
                                                     0.1, 1))
            fmradio_grp.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
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
                            # setattr(obj, setting, int(element.value / 10))
                            # MRT rescale freq values to match radio
                            # expected values
                            value = _freq_encode(
                                element[0].get_value()*1000000.0)
                            setattr(obj, setting, value)

                        elif self._is_fmradio_or_voltage(element):
                            # MRT rescale FM Radio values to match radio
                            # expected values
                            setattr(obj, setting,
                                    int(element.values()[0]._current * 100.0))

                        elif self._is_limit(element):
                            setattr(obj, setting,
                                    int(str(element.values()[0].
                                        _current * 10), 16))
                # Special VFO A Settings
                #
                        elif self._is_chan(element):
                            value = _chnum_encode(element[0].get_value())
                            setattr(obj, setting, value)
                            continue
                #
                        elif self._is_display_name(element):
                            string = element[0].get_value()
                            nameenc = _oem_str_encode(string)
                            for i in range(0, 8):
                                LOG.debug("nameenc %s" % (nameenc[i]))
                                self._memobj.oem.display_name[i] = \
                                    ord(nameenc[i])
                                # setattr(obj, setting, int(ord(nameenc[i])))

                        elif self._is_scan_name(element):
                            string = element[0].get_value()
                            LOG.debug("string %s" % (string))
                            # scaname=element[0].get_name()
                            # LOG.debug("scanname %s" % (scaname))
                            value = _str_encode(string)
                            LOG.debug("scaname %s" % (value))
                            setattr(obj, setting, value)
                            # self._memobj.eval(scaname)[i] = ord(nameenc[i])
                            # setattr(obj, setting, int(ord(nameenc[i])))
                        else:
                            setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

    def _is_freq(self, element):
        return "rxfreq" in element.get_name() or \
               "txoffset" in element.get_name() or \
               "vfofreq" in element.get_name() or\
               "vfoofst" in element.get_name()
        #  "rx_start" in element.get_name() or \
        #  "rx_stop" in element.get_name() or \
        #  "tx_start" in element.get_name() or \
        #  "tx_stop" in element.get_name()

    def _is_limit(self, element):
        return "limit" in element.get_name()

    def _is_fmradio_or_voltage(self, element):
        return "FM_radio" in element.get_name() or\
                "thr_vol_lvl" in element.get_name()

    def _is_chan(self, element):
        return "vfochan" in element.get_name() or\
               "pri_ch" in element.get_name()

    def _is_display_name(self, element):
        return "display_name" in element.get_name()

    def _is_scan_name(self, element):
        return "scanname" in element.get_name()

    # def _is_vfofreq(self, element):
    #     return "vfofreq" in element.get_name() or\
    #            "vfoofst" in element.get_name()
