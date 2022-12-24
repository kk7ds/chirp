# Wouxun KG-935G Driver
# Updated by:
# melvin.terechenok@gmail.com

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

"""Wouxun KG-935G radio management module"""

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
CMD_RD = 130    # \82
CMD_WR = 131    # \83

MEM_VALID = 158

AB_LIST = ["A", "B"]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]
STEP_LIST = [str(x) for x in STEPS]
ROGER_LIST = ["Off", "Begin", "End", "Both"]
TIMEOUT_LIST = ["Off"] + [str(x) + "s" for x in range(15, 901, 15)]
VOX_LIST = ["Off"] + ["%s" % x for x in range(1, 10)]
BANDWIDTH_LIST = ["Narrow", "Wide"]
VOICE_LIST = ["Off", "On"]
LANGUAGE_LIST = ["Chinese", "English"]
SCANMODE_LIST = ["TO", "CO", "SE"]
# MRT - EDIT FOR 935G
PFKEYLONG_LIST = ["undef", "FRQ2-PTT", "Selec Call", "Scan", "Flashlight",
                  "Alarm", "SOS", "FM Radio", "Moni", "Strobe", "Weather",
                  "Tlk A", "Reverse", "CTC Scan", "DCS Scan", "BRT"]
PFKEYSHORT_LIST = ["undef", "Scan", "Flashlight", "Alarm", "SOS", "FM Radio",
                   "Moni", "Strobe", "Weather", "Tlk A", "Reverse",
                   "CTC Scan", "DCS Scan", "BRT"]
#
WORKMODE_LIST = ["VFO", "Ch.Number.", "Ch.Freq.", "Ch.Name"]
BACKLIGHT_LIST = ["Always On"] + [str(x) + "s" for x in range(1, 21)] + \
    ["Always Off"]
OFFSET_LIST = ["+", "-"]
PONMSG_LIST = ["MSG - Bitmap", "Battery Volts"]
SPMUTE_LIST = ["QT", "QT+DTMF", "QT*DTMF"]
DTMFST_LIST = ["OFF", "DTMF", "ANI", "DTMF+ANI"]
# DTMF_TIMES = [str(x) + "ms" for x in range(0, 501, 10)]
DTMF_TIMES = [('%dms' % dtmf, (dtmf // 10)) for dtmf in range(50, 501, 10)]
ALERTS = [1750, 2100, 1000, 1450]
ALERTS_LIST = [str(x) for x in ALERTS]
PTTID_LIST = ["BOT", "EOT", "Both"]
LIST_10 = ["Off"] + ["%s" % x for x in range(1, 11)]
SCANGRP_LIST = ["All"] + ["%s" % x for x in range(1, 11)]
SCQT_LIST = ["Decoder", "Encoder", "All"]
SMUTESET_LIST = ["Off", "Tx", "Rx", "Tx+Rx"]
POWER_LIST = ["Lo", "Mid", "Hi"]
HOLD_TIMES = ["Off"] + ["%s" % x for x in range(100, 5001, 100)]
RPTMODE_LIST = ["Radio", "Repeater"]
# MRT ADDED NEW LISTS
CALLGROUP_LIST = [str(x) for x in range(1, 21)]
THEME_LIST = ["White-1", "White-2", "Black-1", "Black-2"]
DSPBRTSBY_LIST = ["OFF", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
DSPBRTACT_MAP = [("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5),
                 ("6", 6), ("7", 7), ("8", 8), ("9", 9), ("10", 10)]
TONESCANSAVELIST = ["Rx", "Tx", "Tx/Rx"]
# PTTDELAY_LIST = [str(x) + "ms" for x in range(0, 3001, 100)]
PTTDELAY_TIMES = [('%dms' % pttdelay,
                  (pttdelay // 100)) for pttdelay in range(100, 3001, 100)]
SCRAMBLE_LIST = ["OFF"] + [str(x) for x in range(1, 9)]
ONOFF_LIST = ["OFF", "ON"]
# MRT - Map CTCSS Tones -  Value in mem is hex value of
# (ctcss tone * 10) + 0x8000
# MRT - 0x8000 is for CTCSS tones
# MRT - Map DCS Tones -  Value in mem is hex representation of
# DCS Tone# in Octal + either 0x4000 or 0x6000 for polarity
# MRT - 0x4000 is for DCS n tones
# MRT - 0x6000 is for DCS i tones
TONE_MAP = [('Off', 0x0000)] + \
           [('%.1f' % tone,
            int(0x8000 + tone * 10)) for tone in chirp_common.TONES] + \
           [('D%03dn' % tone, int(0x4000 + int(str(tone), 8)))
               for tone in chirp_common.DTCS_CODES] + \
           [('D%03di' % tone, int(0x6000 + int(str(tone), 8)))
               for tone in chirp_common.DTCS_CODES]


# memory slot 0 is not used, start at 1 (so need 1000 slots, not 999)
# structure elements whose name starts with x are currently unidentified

# MRT made Power = 4 bits to handle 935G's 3 power levels and
# to prevent display errors
# MRT beta 1.3 - updates to structure to match KG935G Custom
# programming SW configuration settings, FM Radio presets, Key Settings
# MRT beta 1.4 - modified some value names and merged FM Radio
# memories with other settings to resolve errors in UI implementation
_MEM_FORMAT = """
    #seekto 0x0044;
    struct {
        u32    rx_start;
        u32    rx_stop;
        u32    tx_start;
        u32    tx_stop;
    } uhf_limits;

    #seekto 0x0054;
    struct {
        u32    rx_start;
        u32    rx_stop;
        u32    tx_start;
        u32    tx_stop;
    } vhf_limits;

    #seekto 0x0400;
    struct {
        char     oem1[8];
        char     unknown[2];
        u8     unknown2[10];
        u8     unknown3[10];
        u8     unknown4[8];
        char     oem2[10];
        u8     version[6];
        char     date[8];
        u8     unknown5[2];
        char     model[8];
    } oem_info;

    #seekto 0x0480;
    struct {
        u16    Group_lower1;
        u16    Group_upper1;
        u16    Group_lower2;
        u16    Group_upper2;
        u16    Group_lower3;
        u16    Group_upper3;
        u16    Group_lower4;
        u16    Group_upper4;
        u16    Group_lower5;
        u16    Group_upper5;
        u16    Group_lower6;
        u16    Group_upper6;
        u16    Group_lower7;
        u16    Group_upper7;
        u16    Group_lower8;
        u16    Group_upper8;
        u16    Group_lower9;
        u16    Group_upper9;
        u16    Group_lower10;
        u16    Group_upper10;
    } scan_groups;

    #seekto 0x0500;
    struct {
        u8    call_code_1[6];
        u8    call_code_2[6];
        u8    call_code_3[6];
        u8    call_code_4[6];
        u8    call_code_5[6];
        u8    call_code_6[6];
        u8    call_code_7[6];
        u8    call_code_8[6];
        u8    call_code_9[6];
        u8    call_code_10[6];
        u8    call_code_11[6];
        u8    call_code_12[6];
        u8    call_code_13[6];
        u8    call_code_14[6];
        u8    call_code_15[6];
        u8    call_code_16[6];
        u8    call_code_17[6];
        u8    call_code_18[6];
        u8    call_code_19[6];
        u8    call_code_20[6];
    } call_groups;

    #seekto 0x0580;
    struct {
        char    call_name1[6];
        char    call_name2[6];
        char    call_name3[6];
        char    call_name4[6];
        char    call_name5[6];
        char    call_name6[6];
        char    call_name7[6];
        char    call_name8[6];
        char    call_name9[6];
        char    call_name10[6];
        char    call_name11[6];
        char    call_name12[6];
        char    call_name13[6];
        char    call_name14[6];
        char    call_name15[6];
        char    call_name16[6];
        char    call_name17[6];
        char    call_name18[6];
        char    call_name19[6];
        char    call_name20[6];
    } call_names;


    #seekto 0x0600;
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
        u16 unknown_pad_x0640[235];
        u8 unknown07fe;
        u8 unknown07ff;
        u8      ponmsg;
        char    dispstr[15];
        u8 unknown0810;
        u8 unknown0811;
        u8 unknown0812;
        u8 unknown0813;
        u8 unknown0814;
        u8      voice;
        u8      timeout;
        u8      toalarm;
        u8      channel_menu;
        u8      power_save;
        u8      autolock;
        u8      keylock;
        u8      beep;
        u8      stopwatch;
        u8      vox;
        u8      scan_rev;
        u8      backlight;
        u8      roger_beep;
        char      mode_sw_pwd[6];
        char      reset_pwd[6];
        u16     pri_ch;
        u8      ani_sw;
        u8      ptt_delay;
        u8      ani_code[6];
        u8      dtmf_st;
        u8      BCL_A;
        u8      BCL_B;
        u8      ptt_id;
        u8      prich_sw;
        u8 unknown083d;
        u8 unknown083e;
        u8 unknown083f;
        u8      alert;
        u8      pf1_shrt;
        u8      pf1_long;
        u8      pf2_shrt;
        u8      pf2_long;
        u8 unknown0845;
        u8      work_mode_a;
        u8      work_mode_b;
        u8      dtmf_tx_time;
        u8      dtmf_interval;
        u8      main_band;
        u16      work_ch_a;
        u16      work_ch_b;
        u8 unknown084f;
        u8 unknown0850;
        u8 unknown0851;
        u8 unknown0852;
        u8 unknown0853;
        u8 unknown0854;
        u8 unknown0855;
        u8 unknown0856;
        u8 unknown0857;
        u8 unknown0858;
        u8 unknown0859;
        u8 unknown085a;
        u8 unknown085b;
        u8 unknown085c;
        u8 unknown085d;
        u8 unknown085e;
        u8 unknown085f;
        u8 unknown0860;
        u8      TDR_single_mode;
        u8      ring_time;
        u8      ScnGrpA_Act;
        u8      ScnGrpB_Act;
        u8 unknown0865;
        u8      rpt_tone;
        u8 unknown0867;
        u8      scan_det;
        u8      ToneScnSave;
        u8 unknown086a;
        u8      smuteset;
        u8      cur_call_grp;
        u8      DspBrtAct;
        u8      DspBrtSby;
        u8 unknown086f;
        u8      theme;
        u8      wxalert;
        u8      VFO_repeater_a;
        u8      VFO_repeater_b;
        u8 unknown0874;
        u8 unknown0875;
        u8 unknown0876;
        u8 unknown0877;
        u8 unknown0878;
        u8 unknown0879;
        u8 unknown087a;
        u8 unknown087b;
        u8 unknown087c;
        u8 unknown087d;
        u8 unknown087e;
        u8 unknown087f;
    } settings;

    #seekto 0x0880;
    struct {
        u32     rxfreq;
        u32     unknown0;
        u16     rxtone;
        u16     txtone;
        u8      scrambler:4,
                power:4;
        u8      unknown3:1,
                unknown5:2,
                unknown4:1,
                cmpndr:1,
                mute_mode:2,
                iswide:1;
        u8      step;
        u8      squelch;
      } vfoa;

    #seekto 0x08c0;
    struct {
        u32     rxfreq;
        u32     unknown0;
        u16     rxtone;
        u16     txtone;
        u8      scrambler:4,
                power:4;
        u8      unknown3:1,
                unknown5:2,
                unknown4:1,
                cmpndr:1,
                mute_mode:2,
                iswide:1;
        u8      step;
        u8      squelch;
    } vfob;

    #seekto 0x0900;
    struct {
        u32     rxfreq;
        u32     txfreq;
        u16     rxtone;
        u16     txtone;
        u8      scrambler:4,
                power:4;
        u8      unknown3:2,
                scan_add:1,
                unknown4:1,
                compander:1,
                mute_mode:2,
                iswide:1;
        u8      unknown5;
        u8      unknown6;
    } memory[1000];

    #seekto 0x4780;
    struct {
        u8    name[8];
                u8    unknown[4];
    } names[1000];

    #seekto 0x7670;
    u8          valid[1000];
    """

# Support for the Wouxun KG-935G radio
# Serial coms are at 19200 baud
# The data is passed in variable length records
# Record structure:
#  Offset   Usage
#    0      start of record (\x7c)
#    1      Command (\x80 Identify \x81 End/Reboot \x82 Read \x83 Write)
#    2      direction (\xff PC-> Radio, \x00 Radio -> PC)
#    3      length of payload (excluding header/checksum) (n)
#    4      payload (n bytes)
#    4+n+1  checksum - byte sum (% 256) of bytes 1 -> 4+n
#
# Memory Read Records:
# the payload is 3 bytes, first 2 are offset (big endian),
# 3rd is number of bytes to read
# Memory Write Records:
# the maximum payload size (from the Wouxun software) seems to be 66 bytes
#  (2 bytes location + 64 bytes data).

# MRT 1.2 correct spelling of Wouxon


class KGUV8TRadio(chirp_common.Alias):
    VENDOR = "Wouxun"
    MODEL = "KG-UV8T"


@directory.register
class KG935GRadio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):

    """Wouxun KG-935G"""
    VENDOR = "Wouxun"
    MODEL = "KG-935G"
    _model = "KG-UV8D-B"
    _file_ident = b"935G"
    BAUD_RATE = 19200
# MRT - Added Medium Power level for 935G support
    POWER_LEVELS = [chirp_common.PowerLevel("L", watts=0.5),
                    chirp_common.PowerLevel("M", watts=4.5),
                    chirp_common.PowerLevel("H", watts=5.5)]
    _mmap = ""
    ALIASES = [KGUV8TRadio, ]

    def _checksum(self, data):
        cs = 0
        for byte in data:
            cs += ord(byte)
        return chr(cs % 256)

    def _write_record(self, cmd, payload=None):
        # build the packet
        _header = '\x7c' + chr(cmd) + '\xff'

        _length = 0
        if payload:
            _length = len(payload)

        # update the length field
        _header += chr(_length)

        if payload:
            # calculate checksum then add it with the payload
            # to the packet and encrypt
            crc = self._checksum(_header[1:] + payload)
            payload += crc
            _header += self.encrypt(payload)
        else:
            # calculate and add encrypted checksum to the packet
            crc = self._checksum(_header[1:])
            _header += self.strxor(crc, '\x57')

        try:
            self.pipe.write(_header)
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def _read_record(self):
        # read 4 chars for the header
        _header = self.pipe.read(4)
        if len(_header) != 4:
            raise errors.RadioError('Radio did not respond')
        _length = ord(_header[3])
        _packet = self.pipe.read(_length)
        _rcs_xor = _packet[-1]
        _packet = self.decrypt(_packet)
        _cs = ord(self._checksum(_header[1:] + _packet))
        # read the checksum and decrypt it
        _rcs = ord(self.strxor(self.pipe.read(1), _rcs_xor))
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
    #  0:10     Model, zero padded (Looks for 'KG-UV8D-B')

    @classmethod
    def match_model(cls, filedata, filename):
        id = cls._file_ident
        return cls._file_ident in filedata[0x426:0x430]

    def _identify(self):
        """Do the identification dance"""
        for _i in range(0, 10):
            self._write_record(CMD_ID)
            _chksum_err, _resp = self._read_record()
            LOG.debug("Got:\n%s" % util.hexprint(_resp))
            if _chksum_err:
                LOG.error("Checksum error: retrying ident...")
                time.sleep(0.100)
                continue
            LOG.debug("Model %s" % util.hexprint(_resp[0:9]))
            if _resp[0:9] == self._model:
                return
            if len(_resp) == 0:
                raise Exception("Radio not responding")
            else:
                raise Exception("Unable to identify radio")

    def _finish(self):
        self._write_record(CMD_END)

    def process_mmap(self):
        self._memobj = bitwise.parse(_MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = self._download()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        self._upload()

    # TODO: Load all memory.
    # It would be smarter to only load the active areas and none of
    # the padding/unused areas. Padding still need to be investigated.
    def _download(self):
        """Talk to a wouxun KG-935G and do a download"""
        try:
            self._identify()
            return self._do_download(0, 32768, 64)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Unknown error during download process')
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def _do_download(self, start, end, blocksize):
        # allocate & fill memory
        image = ""
        for i in range(start, end, blocksize):
            req = chr(i // 256) + chr(i % 256) + chr(blocksize)
            self._write_record(CMD_RD, req)
            cs_error, resp = self._read_record()
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
        """Talk to a wouxun KG-935G and do a upload"""
        try:
            self._identify()
            self._do_upload(0, 32768, 64)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        return

    def _do_upload(self, start, end, blocksize):
        ptr = start
        for i in range(start, end, blocksize):
            req = chr(i // 256) + chr(i % 256)
            chunk = self.get_mmap()[ptr:ptr + blocksize]
            self._write_record(CMD_WR, req + chunk)
            LOG.debug(util.hexprint(req + chunk))
            cserr, ack = self._read_record()
            LOG.debug(util.hexprint(ack))
            j = ord(ack[0]) * 256 + ord(ack[1])
            if cserr or j != ptr:
                raise Exception("Radio did not ack block %i" % ptr)
            ptr += blocksize
            if self.status_fn:
                status = chirp_common.Status()
                status.cur = i
                status.max = end
                status.msg = "Cloning to radio"
                self.status_fn(status)
        self._finish()

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
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 8
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
#   MRT - Open up channel memory freq range to support RxFreq limit expansion
        rf.valid_bands = [(30000000, 299999990),  # supports 2m
                          (300000000, 999999990)]  # supports 70cm
        # rf.valid_bands = [(self._memobj.vhf_limits.rx_start
        #                 , self._memobj.vhf_limits.rx_stop),  # supports 2m
        #                   (self._memobj.uhf_limits.rx_start
        #                 , self._memobj.uhf_limits.rx_stop)]  # supports 70cm

        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.memory_bounds = (1, 999)  # 999 memories
        rf.valid_tuning_steps = STEPS
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is experimental.  USE AT YOUR OWN RISK\n'
             '\n'
             'Please save a copy of the image from your radio with Chirp '
             'before modifying any values.\n'
             '\n'
             'Please keep a copy of your memories with the original Wouxon'
             'CPS software if you treasure them, this driver is new and'
             'may contain bugs.\n'
             '\n'
             ' All of the settings from the Wouxon Custom Programming'
             ' Software (CSP) have been mapped\n in addition to some bonus'
             ' settings that were found.\n'
             ' Changing the VHF/UHF Rx limits does expand receive range -'
             ' but radio performance\n'
             ' is not guaranteed-  and may void warranty or cause radio'
             ' to malfunction.\n'
             ' You can also customize the bottom banner from the OEMINFO '
             ' Model setting\n'
             )
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])
# MRT - corrected the Polarity decoding to match 935G implementation
# use 0x2000 bit mask for R
# MRT - 0x2000 appears to be the bit mask for Inverted DCS tones
# MRT - n DCS Tone will be 0x4xxx values - i DCS Tones will
# be 0x6xxx values.
# MRT - Chirp Uses N for n DCS Tones and R for i DCS Tones

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x2000) and "R" or "N"
            return code, pol
# MRT - Modified the function below to bitwise AND with 0x4000
# to check for 935G DCS Tone decoding
# MRT 0x4000 appears to be the bit mask for DCS tones
        tpol = False
# MRT Beta 1.1 - Fix the txtone compare to 0x4000 - was rxtone.
        if _mem.txtone != 0xFFFF and (_mem.txtone & 0x4000) == 0x4000:
            tcode, tpol = _get_dcs(_mem.txtone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.txtone != 0xFFFF and _mem.txtone != 0x0:
            mem.rtone = (_mem.txtone & 0x7fff) / 10.0
            txmode = "Tone"
        else:
            txmode = ""
# MRT - Modified the function below to bitwise AND with 0x4000
# to check for 935G DCS Tone decoding
        rpol = False
        if _mem.rxtone != 0xFFFF and (_mem.rxtone & 0x4000) == 0x4000:
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
        LOG.debug("%d %s", number, _valid == MEM_VALID)
        if _valid != MEM_VALID:
            mem.empty = True
            return mem
        else:
            mem.empty = False

        mem.freq = int(_mem.rxfreq) * 10

        if _mem.txfreq == 0xFFFFFFFF:
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _nam.name:
            if char != 0:
                mem.name += chr(char)
        mem.name = mem.name.rstrip()

        self._get_tone(_mem, mem)

        mem.skip = "" if bool(_mem.scan_add) else "S"
        _mem.power = _mem.power & 0x3
        if _mem.power > 2:
            _mem.power = 2
        mem.power = self.POWER_LEVELS[_mem.power]
        mem.mode = _mem.iswide and "FM" or "NFM"
        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            # MRT Change from + 0x2800 to bitwise OR with 0x4000 to
            # set the bit for DCS
            val = int("%i" % code, 8) | 0x4000
            if pol == "R":
                # MRT Change to 0x2000 from 0x8000 to set the bit for
                # i/R polarity
                val += 0x2000
            return val

        rx_mode = tx_mode = None
        rxtone = txtone = 0x0000

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            txtone = int(mem.rtone * 10) + 0x8000
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rxtone = txtone = int(mem.ctone * 10) + 0x8000
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rxtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                txtone = int(mem.rtone * 10) + 0x8000
            if rx_mode == "DTCS":
                rxtone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rxtone = int(mem.ctone * 10) + 0x8000

        _mem.rxtone = rxtone
        _mem.txtone = txtone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.txtone, rx_mode, _mem.rxtone))

    def set_memory(self, mem):
        number = mem.number

        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        if mem.empty:
            _mem.set_raw("\x00" * (_mem.size() // 8))
            self._memobj.valid[number] = 0
            self._memobj.names[number].set_raw("\x00" * (_nam.size() // 8))
            return

        _mem.rxfreq = int(mem.freq / 10)
        if mem.duplex == "off":
            _mem.txfreq = 0xFFFFFFFF
        elif mem.duplex == "split":
            _mem.txfreq = int(mem.offset / 10)
        elif mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "+":
            _mem.txfreq = int(mem.freq / 10) + int(mem.offset / 10)
        elif mem.duplex == "-":
            _mem.txfreq = int(mem.freq / 10) - int(mem.offset / 10)
        else:
            _mem.txfreq = int(mem.freq / 10)
        _mem.scan_add = int(mem.skip != "S")
        _mem.iswide = int(mem.mode == "FM")
        # set the tone
        self._set_tone(mem, _mem)
        # MRT set the scrambler and compander to off by default
        # MRT This changes them in the channel memory
        _mem.scrambler = 0
        _mem.compander = 0
        # set the power
        _mem.power = _mem.power & 0x3
        if mem.power:
            if _mem.power > 2:
                _mem.power = 2
            _mem.power = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.power = True
        # MRT set to mute mode to QT (not QT+DTMF or QT*DTMF) by default
        # MRT This changes them in the channel memory
        _mem.mute_mode = 0

        # MRT it is unknown what impact these values have
        # MRT This changes them in the channel memory to match what
        # Wouxun CPS shows when creating a channel
        # MRT It is likely that these are just left as is and not
        # written to by CPS - bit remnants of 0xFF in the unused memory
        # _mem.unknown1 = 0
        # MRT Set to 3 to TO MATCH CPS VALUES
        _mem.unknown3 = 3
        # MRT Set to 1 to TO MATCH CPS VALUES
        _mem.unknown4 = 1
        # MRT set unknown5 to 1 and unknown6 to 0
        _mem.unknown5 = 1
        _mem.unknown6 = 255

        for i in range(0, len(_nam.name)):
            if i < len(mem.name) and mem.name[i]:
                _nam.name[i] = ord(mem.name[i])
            else:
                _nam.name[i] = 0x0
        self._memobj.valid[mem.number] = MEM_VALID

    def _get_settings(self):
        _settings = self._memobj.settings
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _scan = self._memobj.scan_groups
        _call = self._memobj.call_groups
        _callname = self._memobj.call_names

        cfg_grp = RadioSettingGroup("cfg_grp", "Config Settings")
        vfoa_grp = RadioSettingGroup("vfoa_grp", "VFO A Settings")
        vfob_grp = RadioSettingGroup("vfob_grp", "VFO B Settings")
        key_grp = RadioSettingGroup("key_grp", "Key Settings")
        fmradio_grp = RadioSettingGroup("fmradio_grp", "FM Broadcast Memory")
        lmt_grp = RadioSettingGroup("lmt_grp", "Rx/Tx Frequency Limits")
        uhf_lmt_grp = RadioSettingGroup("uhf_lmt_grp", "UHF")
        vhf_lmt_grp = RadioSettingGroup("vhf_lmt_grp", "VHF")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")
        scan_grp = RadioSettingGroup("scan_grp", "Scan Group")
        call_grp = RadioSettingGroup("call_grp", "Call Settings")
        extra_grp = RadioSettingGroup("extra_grp",
                                      "Extra Settings"
                                      "\nNOT Changed by RESET or CPS")
        extra_grp.append(lmt_grp)
        extra_grp.append(oem_grp)
        group = RadioSettings(cfg_grp, vfoa_grp, vfob_grp,
                              fmradio_grp, key_grp, scan_grp,
                              call_grp, extra_grp)

    # Call Settings
        rs = RadioSetting("cur_call_grp", "Current Call Group",
                          RadioSettingValueList(CALLGROUP_LIST,
                                                CALLGROUP_LIST[_settings.
                                                               cur_call_grp]))
        call_grp.append(rs)

        callchars = "0123456789"
        for i in range(1, 21):
            callnum = str(i)
            _msg = ""
            _msg1 = str(eval("_callname.call_name"+callnum)).split("\0")[0]
# MRT - Handle default factory values of 0xFF or
# non-ascii values in Call Name memory
            for char in _msg1:
                if char < chr(0x20) or char > chr(0x7E):
                    # _msg += chr(0x20)
                    _msg += ""
                else:
                    _msg += str(char)
            val = RadioSettingValueString(0, 6, _msg)
            val.set_mutable(True)
            rs = RadioSetting("call_names.call_name"+callnum,
                              "Call Name "+callnum, val)
            call_grp.append(rs)

            _codeobj = eval("_call.call_code_"+callnum)
            _code = "".join([callchars[x] for x in _codeobj if int(x) < 0x0A])
            val = RadioSettingValueString(3, 6, _code, False)
            val.set_charset(callchars)
            rs = RadioSetting("call_code_"+callnum,
                              "Call Code " + callnum, val)

            def apply_call_code(setting, obj):
                value = []
                for j in range(0, 6):
                    try:
                        value.append(callchars.index(str(setting.value)[j]))
                    except IndexError:
                        value.append(0xFF)
                obj.call_code = value
            rs.set_apply_callback(apply_call_code,
                                  eval("_call.call_code_"+callnum))
            call_grp.append(rs)

        # Configuration Settings
        #
        rs = RadioSetting("DspBrtAct", "Display Brightness ACTIVE",
                          RadioSettingValueMap(DSPBRTACT_MAP,
                                               _settings.DspBrtAct))
        cfg_grp.append(rs)
        rs = RadioSetting("DspBrtSby", "Display Brightness STANDBY",
                          RadioSettingValueList(DSPBRTSBY_LIST,
                                                DSPBRTSBY_LIST[_settings.
                                                               DspBrtSby]))
        cfg_grp.append(rs)
        rs = RadioSetting("wxalert", "Weather Alert",
                          RadioSettingValueBoolean(_settings.wxalert))
        cfg_grp.append(rs)
        rs = RadioSetting("power_save", "Battery Saver",
                          RadioSettingValueBoolean(_settings.power_save))
        cfg_grp.append(rs)
        rs = RadioSetting("theme", "Theme",
                          RadioSettingValueList(
                              THEME_LIST, THEME_LIST[_settings.theme]))
        cfg_grp.append(rs)
        rs = RadioSetting("backlight", "Backlight Active Time",
                          RadioSettingValueList(BACKLIGHT_LIST,
                                                BACKLIGHT_LIST[_settings.
                                                               backlight]))
        cfg_grp.append(rs)
        rs = RadioSetting("scan_rev", "Scan Mode",
                          RadioSettingValueList(SCANMODE_LIST,
                                                SCANMODE_LIST[_settings.
                                                              scan_rev]))
        cfg_grp.append(rs)
        rs = RadioSetting("prich_sw", "Priority Channel Scan",
                          RadioSettingValueBoolean(_settings.prich_sw))
        cfg_grp.append(rs)
        rs = RadioSetting("pri_ch",
                          "Priority Channel - Can not be empty Channel",
                          RadioSettingValueInteger(1, 999, _settings.pri_ch))
        cfg_grp.append(rs)
        rs = RadioSetting("scan_det", "Scan Mode Tone Detect",
                          RadioSettingValueBoolean(_settings.scan_det))
        cfg_grp.append(rs)
        rs = RadioSetting("ToneScnSave", "Tone Scan Save",
                          RadioSettingValueList(TONESCANSAVELIST,
                                                TONESCANSAVELIST[_settings.
                                                                 ToneScnSave]))
        cfg_grp.append(rs)
        rs = RadioSetting("roger_beep", "Roger Beep",
                          RadioSettingValueList(ROGER_LIST,
                                                ROGER_LIST[_settings.
                                                           roger_beep]))
        cfg_grp.append(rs)
        rs = RadioSetting("timeout", "Timeout Timer (TOT)",
                          RadioSettingValueList(
                              TIMEOUT_LIST, TIMEOUT_LIST[_settings.timeout]))
        cfg_grp.append(rs)
        rs = RadioSetting("toalarm", "Timeout Alarm (TOA)",
                          RadioSettingValueInteger(0, 10, _settings.toalarm))
        cfg_grp.append(rs)
        rs = RadioSetting("vox", "VOX",
                          RadioSettingValueList(LIST_10,
                                                LIST_10[_settings.vox]))
        cfg_grp.append(rs)
        rs = RadioSetting("voice", "Voice Guide",
                          RadioSettingValueBoolean(_settings.voice))
        cfg_grp.append(rs)
        rs = RadioSetting("beep", "Keypad Beep",
                          RadioSettingValueBoolean(_settings.beep))
        cfg_grp.append(rs)
        rs = RadioSetting("BCL_B", "Busy Channel Lock-out A",
                          RadioSettingValueBoolean(_settings.BCL_A))
        cfg_grp.append(rs)
        rs = RadioSetting("BCL_A", "Busy Channel Lock-out B",
                          RadioSettingValueBoolean(_settings.BCL_B))
        cfg_grp.append(rs)
        rs = RadioSetting("smuteset", "Secondary Area Mute (SMUTESET)",
                          RadioSettingValueList(SMUTESET_LIST,
                                                SMUTESET_LIST[_settings.
                                                              smuteset]))
        cfg_grp.append(rs)
        rs = RadioSetting("ani_sw", "ANI-ID Switch (ANI-SW)",
                          RadioSettingValueBoolean(_settings.ani_sw))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_st", "DTMF Sidetone (SIDETONE)",
                          RadioSettingValueList(DTMFST_LIST,
                                                DTMFST_LIST[_settings.
                                                            dtmf_st]))
        cfg_grp.append(rs)
        rs = RadioSetting("alert", "Alert Tone",
                          RadioSettingValueList(ALERTS_LIST,
                                                ALERTS_LIST[_settings.alert]))
        cfg_grp.append(rs)
        rs = RadioSetting("ptt_delay", "PTT-DLY",
                          RadioSettingValueMap(PTTDELAY_TIMES,
                                               _settings.ptt_delay))
        cfg_grp.append(rs)
        rs = RadioSetting("ptt_id", "PTT-ID",
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[_settings.ptt_id]))
        cfg_grp.append(rs)
        rs = RadioSetting("ring_time", "Ring Time",
                          RadioSettingValueList(LIST_10,
                                                LIST_10[_settings.ring_time]))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_tone", "Repeater Tone",
                          RadioSettingValueBoolean(_settings.rpt_tone))
        cfg_grp.append(rs)
        rs = RadioSetting("stopwatch", "Timer / Stopwatch",
                          RadioSettingValueBoolean(_settings.stopwatch))
        cfg_grp.append(rs)
        rs = RadioSetting("autolock", "Autolock",
                          RadioSettingValueBoolean(_settings.autolock))
        cfg_grp.append(rs)
        rs = RadioSetting("keylock", "Keypad Lock",
                          RadioSettingValueBoolean(_settings.keylock))
        cfg_grp.append(rs)
        rs = RadioSetting("ponmsg", "Poweron message",
                          RadioSettingValueList(
                               PONMSG_LIST, PONMSG_LIST[_settings.ponmsg]))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_tx_time", "DTMF Transmit Time",
                          RadioSettingValueMap(DTMF_TIMES,
                                               _settings.dtmf_tx_time))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_interval", "DTMF Interval Time",
                          RadioSettingValueMap(DTMF_TIMES,
                                               _settings.dtmf_interval))
        cfg_grp.append(rs)
        rs = RadioSetting("channel_menu", "Menu available in channel mode",
                          RadioSettingValueBoolean(_settings.channel_menu))
        cfg_grp.append(rs)

        pswdchars = "0123456789"
        _msg = str(_settings.mode_sw_pwd).split("\0")[0]
        val = RadioSettingValueString(0, 6, _msg, False)
        val.set_mutable(True)
        val.set_charset(pswdchars)
        rs = RadioSetting("mode_sw_pwd", "Mode SW Pwd", val)
        cfg_grp.append(rs)

        _msg = str(_settings.reset_pwd).split("\0")[0]
        val = RadioSettingValueString(0, 6, _msg, False)
        val.set_charset(pswdchars)
        val.set_mutable(True)
        rs = RadioSetting("reset_pwd", "Reset Pwd", val)
        cfg_grp.append(rs)

        # Key Settings
        #
        _msg = str(_settings.dispstr).split("\0")[0]
        val = RadioSettingValueString(0, 15, _msg)
        val.set_mutable(True)
        rs = RadioSetting("dispstr",
                          "Display Message - Interface Display Edit", val)
        key_grp.append(rs)

        dtmfchars = "0123456789"
        _codeobj = _settings.ani_code
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x0A])
        val = RadioSettingValueString(3, 6, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("ani_code", "ANI Code", val)

        def apply_ani_id(setting, obj):
            value = []
            for j in range(0, 6):
                try:
                    value.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    value.append(0xFF)
            obj.ani_code = value
        rs.set_apply_callback(apply_ani_id, _settings)
        key_grp.append(rs)

        rs = RadioSetting("pf1_shrt", "PF1 SHORT Key function",
                          RadioSettingValueList(
                              PFKEYSHORT_LIST,
                              PFKEYSHORT_LIST[_settings.pf1_shrt]))
        key_grp.append(rs)
        rs = RadioSetting("pf1_long", "PF1 LONG Key function",
                          RadioSettingValueList(
                              PFKEYLONG_LIST,
                              PFKEYLONG_LIST[_settings.pf1_long]))
        key_grp.append(rs)
        rs = RadioSetting("pf2_shrt", "PF2 SHORT Key function",
                          RadioSettingValueList(
                              PFKEYSHORT_LIST,
                              PFKEYSHORT_LIST[_settings.pf2_shrt]))
        key_grp.append(rs)
        rs = RadioSetting("pf2_long", "PF2 LONG Key function",
                          RadioSettingValueList(
                              PFKEYLONG_LIST,
                              PFKEYLONG_LIST[_settings.pf2_long]))
        key_grp.append(rs)

#       SCAN GROUP settings
        rs = RadioSetting("ScnGrpA_Act", "Scan Group A Active",
                          RadioSettingValueList(SCANGRP_LIST,
                                                SCANGRP_LIST[_settings.
                                                             ScnGrpA_Act]))
        scan_grp.append(rs)
        rs = RadioSetting("ScnGrpB_Act", "Scan Group B Active",
                          RadioSettingValueList(SCANGRP_LIST,
                                                SCANGRP_LIST[_settings.
                                                             ScnGrpB_Act]))
        scan_grp.append(rs)

        for i in range(1, 11):
            scgroup = str(i)

            rs = RadioSetting("scan_groups.Group_lower"+scgroup,
                              "Scan Group "+scgroup+" Lower",
                              RadioSettingValueInteger(1, 999,
                                                       eval("self._memobj. \
                                                            scan_groups. \
                                                            Group_lower" +
                                                            scgroup)))
            scan_grp.append(rs)

            rs = RadioSetting("scan_groups.Group_upper"+scgroup,
                              "Scan Group "+scgroup+" Upper",
                              RadioSettingValueInteger(1, 999,
                                                       eval("self._memobj. \
                                                            scan_groups. \
                                                            Group_upper" +
                                                            scgroup)))
            scan_grp.append(rs)

        # VFO A Settings
        #
        rs = RadioSetting("work_mode_a", "VFO A Workmode",
                          RadioSettingValueList(WORKMODE_LIST,
                                                WORKMODE_LIST[_settings.
                                                              work_mode_a]))
        vfoa_grp.append(rs)
        rs = RadioSetting("work_ch_a", "VFO A Work Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.work_ch_a))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.rxfreq", "VFO A Rx Frequency (MHz)",
                          RadioSettingValueFloat(
                              30.00000, 999.999999,
                              (_vfoa.rxfreq / 100000.0), 0.000001, 6))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfoa.rxtone", "VFOA Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _vfoa.rxtone))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.txtone", "VFOA Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _vfoa.txtone))
        vfoa_grp.append(rs)


# MRT - AND power with 0x03 to display only the lower 2 bits for
# power level and to clear the upper bits
# MRT - any bits set in the upper 2 bits will cause radio to show
# invalid values for power level and a display glitch
# MRT - when PTT is pushed
        _vfoa.power = _vfoa.power & 0x3
        if _vfoa.power > 2:
            _vfoa.power = 2
        rs = RadioSetting("vfoa.power", "VFO A Power",
                          RadioSettingValueList(
                              POWER_LIST, POWER_LIST[_vfoa.power]))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.iswide", "VFO A Wide/Narrow",
                          RadioSettingValueList(
                              BANDWIDTH_LIST, BANDWIDTH_LIST[_vfoa.iswide]))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.mute_mode", "VFO A Mute (SP Mute)",
                          RadioSettingValueList(
                              SPMUTE_LIST, SPMUTE_LIST[_vfoa.mute_mode]))
        vfoa_grp.append(rs)
        rs = RadioSetting("VFO_repeater_a", "VFO A Repeater",
                          RadioSettingValueBoolean(_settings.VFO_repeater_a))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfoa.scrambler", "VFO A Descramble",
                          RadioSettingValueList(
                              SCRAMBLE_LIST, SCRAMBLE_LIST[_vfoa.scrambler]))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfoa.cmpndr", "VFO A Compander",
                          RadioSettingValueList(
                             ONOFF_LIST, ONOFF_LIST[_vfoa.cmpndr]))
        vfoa_grp.append(rs)

        rs = RadioSetting("vfoa.step", "VFO A Step (kHz)",
                          RadioSettingValueList(
                              STEP_LIST, STEP_LIST[_vfoa.step]))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.squelch", "VFO A Squelch",
                          RadioSettingValueList(
                              LIST_10, LIST_10[_vfoa.squelch]))
        vfoa_grp.append(rs)

        # VFO B Settings
        rs = RadioSetting("work_mode_b", "VFO B Workmode",
                          RadioSettingValueList(WORKMODE_LIST,
                                                WORKMODE_LIST[_settings.
                                                              work_mode_b]))
        vfob_grp.append(rs)
        rs = RadioSetting("work_ch_b", "VFO B Work Channel",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.work_ch_b))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.rxfreq", "VFO B Rx Frequency (MHz)",
                          RadioSettingValueFloat(
                              30.000000, 999.999999,
                              (_vfob.rxfreq / 100000.0), 0.000001, 6))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.rxtone", "VFOB Rx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _vfob.rxtone))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.txtone", "VFOB Tx tone",
                          RadioSettingValueMap(
                            TONE_MAP, _vfob.txtone))
        vfob_grp.append(rs)

# MRT - AND power with 0x03 to display only the lower 2 bits for
# power level and to clear the upper bits
# MRT - any bits set in the upper 2 bits will cause radio to show
# invalid values for power level and a display glitch
# MRT - when PTT is pushed
        _vfob.power = _vfob.power & 0x3
        if _vfob.power > 2:
            _vfob.power = 2
        rs = RadioSetting("vfob.power", "VFO B Power",
                          RadioSettingValueList(
                              POWER_LIST, POWER_LIST[_vfob.power]))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.iswide", "VFO B Wide/Narrow",
                          RadioSettingValueList(
                              BANDWIDTH_LIST, BANDWIDTH_LIST[_vfob.iswide]))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.mute_mode", "VFO B Mute (SP Mute)",
                          RadioSettingValueList(
                              SPMUTE_LIST, SPMUTE_LIST[_vfob.mute_mode]))
        vfob_grp.append(rs)
        rs = RadioSetting("VFO_repeater_b", "VFO B Repeater",
                          RadioSettingValueBoolean(_settings.VFO_repeater_b))
        vfob_grp.append(rs)

        rs = RadioSetting("vfob.scrambler", "VFO B Descramble",
                          RadioSettingValueList(
                              SCRAMBLE_LIST, SCRAMBLE_LIST[_vfob.scrambler]))
        vfob_grp.append(rs)

        rs = RadioSetting("vfob.cmpndr", "VFO B Compander",
                          RadioSettingValueList(
                              ONOFF_LIST, ONOFF_LIST[_vfob.cmpndr]))
        vfob_grp.append(rs)

        rs = RadioSetting("vfob.step", "VFO B Step (kHz)",
                          RadioSettingValueList(
                              STEP_LIST, STEP_LIST[_vfob.step]))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.squelch", "VFO B Squelch",
                          RadioSettingValueList(
                              LIST_10, LIST_10[_vfob.squelch]))
        vfob_grp.append(rs)

# FM RADIO PRESETS

# memory stores raw integer value like 760
# radio will divide 760 by 10 and interpret correctly at 76.0Mhz
        for i in range(1, 21):
            chan = str(i)
            rs = RadioSetting("FM_radio" + chan, "FM Preset" + chan,
                              RadioSettingValueFloat(76.0, 108.0,
                                                     eval("_settings. \
                                                          FM_radio" +
                                                          chan)/10.0,
                                                     0.1, 1))
            fmradio_grp.append(rs)

# Freq Limits settings
        #
        rs = RadioSetting("vhf_limits.rx_start", "VHF RX Lower Limit (MHz)",
                          RadioSettingValueFloat(
                              30.000000, 299.999999,
                              (self._memobj.vhf_limits.rx_start / 100000.0),
                              0.000001, 6))

        lmt_grp.append(rs)
        rs = RadioSetting("vhf_limits.rx_stop", "VHF RX Upper Limit (MHz)",
                          RadioSettingValueFloat(
                              30.000000, 299.999999,
                              (self._memobj.vhf_limits.rx_stop / 100000.0),
                              0.000001, 6))
        lmt_grp.append(rs)

        rs = RadioSetting("vhf_limits.tx_start", "VHF TX Lower Limit (MHz)",
                          RadioSettingValueFloat(
                              30.000000, 299.999999,
                              (self._memobj.vhf_limits.tx_start / 100000.0),
                              0.000001, 6))

        lmt_grp.append(rs)
        rs = RadioSetting("vhf_limits.tx_stop", "VHF TX Upper Limit (MHz)",
                          RadioSettingValueFloat(
                              30.000000, 299.999999,
                              (self._memobj.vhf_limits.tx_stop / 100000.0),
                              0.000001, 6))
        lmt_grp.append(rs)

# MRT - TX Limits do not appear to change radio's ability
#  to transmit on other freqs.
# MRT - Appears that the radio firmware prevent Tx
# on anything other than a valid GMRS Freq

        # rs = RadioSetting("vhf_limits.tx_start", "VHF TX Lower Limit",
        #                   RadioSettingValueInteger(
        #                       10000000, 299999999,
        #                       self._memobj.vhf_limits.tx_start * 10, 5000))
        # val.set_mutable(False)
        # vhf_lmt_grp.append(rs)
        # rs = RadioSetting("vhf_limits.tx_stop", "VHF TX Upper Limit",
        #                   RadioSettingValueInteger(
        #                       10000000, 299999999,
        #                       self._memobj.vhf_limits.tx_stop * 10, 5000))
        # val.set_mutable(False)
        # vhf_lmt_grp.append(rs)

        rs = RadioSetting("uhf_limits.rx_start", "UHF RX Lower Limit (MHz)",
                          RadioSettingValueFloat(
                              300.000000, 999.999999,
                              (self._memobj.uhf_limits.rx_start / 100000.0),
                              0.000001, 6))
        lmt_grp.append(rs)
        rs = RadioSetting("uhf_limits.rx_stop", "UHF RX Upper Limit (MHz)",
                          RadioSettingValueFloat(
                              300.000000, 999.999999,
                              (self._memobj.uhf_limits.rx_stop / 100000.0),
                              0.000001, 6))
        lmt_grp.append(rs)

        rs = RadioSetting("uhf_limits.tx_start", "UHF TX Lower Limit (MHz)",
                          RadioSettingValueFloat(
                              300.000000, 999.999999,
                              (self._memobj.uhf_limits.tx_start / 100000.0),
                              0.000001, 6))
        lmt_grp.append(rs)
        rs = RadioSetting("uhf_limits.tx_stop", "UHF TX Upper Limit (MHz)",
                          RadioSettingValueFloat(
                              300.000000, 999.999999,
                              (self._memobj.uhf_limits.tx_stop / 100000.0),
                              0.000001, 6))
        lmt_grp.append(rs)

        # rs = RadioSetting("uhf_limits.tx_start", "UHF TX Lower Limit",
        #                   RadioSettingValueInteger(
        #                       300000000, 999999999,
        #                       self._memobj.uhf_limits.tx_start * 10, 5000))
        # uhf_lmt_grp.append(rs)
        # rs = RadioSetting("uhf_limits.tx_stop", "UHF TX Upper Limit",
        #                   RadioSettingValueInteger(
        #                       300000000, 999999999,
        #                       self._memobj.uhf_limits.tx_stop * 10, 5000))
        # uhf_lmt_grp.append(rs)


# OEM info
        #
        def _decode(lst):
            _str = ''.join([chr(int(c)) for c in lst
                            if chr(int(c)) in chirp_common.CHARSET_ASCII])
            return _str

        def do_nothing(setting, obj):
            return

        _str = _decode(self._memobj.oem_info.model)
        val = RadioSettingValueString(0, 8, _str)
        val.set_mutable(True)
        rs = RadioSetting("oem_info.model", "Model / Bottom Banner", val)
        oem_grp.append(rs)
        _str = _decode(self._memobj.oem_info.oem1)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem_info.oem1", "OEM String 1", val)
        rs.set_apply_callback(do_nothing, _settings)
        oem_grp.append(rs)
        _str = _decode(self._memobj.oem_info.oem2)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem_info.oem2", "Firmware Version ??", val)
        rs.set_apply_callback(do_nothing, _settings)
        oem_grp.append(rs)
        # _str = _decode(self._memobj.oem_info.version)
        # val = RadioSettingValueString(0, 15, _str)
        # val.set_mutable(False)
        # rs = RadioSetting("oem_info.version", "Software Version", val)
        # rs.set_apply_callback(do_nothing, _settings)
        # oem_grp.append(rs)
        _str = _decode(self._memobj.oem_info.date)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem_info.date", "OEM Date", val)
        rs.set_apply_callback(do_nothing, _settings)
        oem_grp.append(rs)

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
                            setattr(obj, setting,
                                    int(element.values()[0]._current *
                                        100000.0))
                        elif self._is_fmradio(element):
                            # MRT rescale FM Radio values to match radio
                            # expected values
                            setattr(obj, setting,
                                    int(element.values()[0]._current * 10.0))
                        else:
                            setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise

    def _is_freq(self, element):
        return "rxfreq" in element.get_name() or \
         "txoffset" in element.get_name() or \
         "rx_start" in element.get_name() or \
         "rx_stop" in element.get_name() or \
         "tx_start" in element.get_name() or \
         "tx_stop" in element.get_name()

    def _is_fmradio(self, element):
        return "FM_radio" in element.get_name()
