# Copyright 2014 Ron Wellsted <ron@m0rnw.uk> M0RNW
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

"""Wouxun KG-UV8D radio management module"""

import time
import os
import logging
from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettings

LOG = logging.getLogger(__name__)

CMD_ID = 128
CMD_END = 129
CMD_RD = 130
CMD_WR = 131

MEM_VALID = 158

AB_LIST = ["A", "B"]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]
STEP_LIST = [str(x) for x in STEPS]
ROGER_LIST = ["Off", "BOT", "EOT", "Both"]
TIMEOUT_LIST = ["Off"] + [str(x) + "s" for x in range(15, 901, 15)]
VOX_LIST = ["Off"] + ["%s" % x for x in range(1, 10)]
BANDWIDTH_LIST = ["Narrow", "Wide"]
VOICE_LIST = ["Off", "On"]
LANGUAGE_LIST = ["Chinese", "English"]
SCANMODE_LIST = ["TO", "CO", "SE"]
PF1KEY_LIST = ["Call", "VFTX"]
PF3KEY_LIST = ["Scan", "Lamp", "Tele Alarm", "SOS-CH", "Radio", "Disable"]
WORKMODE_LIST = ["VFO", "Channel No.", "Ch. No.+Freq.", "Ch. No.+Name"]
BACKLIGHT_LIST = ["Always On"] + [str(x) + "s" for x in range(1, 21)] + \
    ["Always Off"]
OFFSET_LIST = ["+", "-"]
PONMSG_LIST = ["Bitmap", "Battery Volts"]
SPMUTE_LIST = ["QT", "QT+DTMF", "QT*DTMF"]
DTMFST_LIST = ["DT-ST", "ANI-ST", "DT-ANI", "Off"]
DTMF_TIMES = ["%s" % x for x in range(50, 501, 10)]
RPTSET_LIST = ["X-TWRPT", "X-DIRRPT"]
ALERTS = [1750, 2100, 1000, 1450]
ALERTS_LIST = [str(x) for x in ALERTS]
PTTID_LIST = ["BOT", "EOT", "Both"]
LIST_10 = ["Off"] + ["%s" % x for x in range(1, 11)]
SCANGRP_LIST = ["All"] + ["%s" % x for x in range(1, 11)]
SCQT_LIST = ["All", "Decoder", "Encoder"]
SMUTESET_LIST = ["Off", "Tx", "Rx", "Tx/Rx"]
POWER_LIST = ["Lo", "Hi"]
HOLD_TIMES = ["Off"] + ["%s" % x for x in range(100, 5001, 100)]
RPTMODE_LIST = ["Radio", "Repeater"]

# memory slot 0 is not used, start at 1 (so need 1000 slots, not 999)
# structure elements whose name starts with x are currently unidentified
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
        u8     model[8];
        u8     unknown[2];
        u8     oem1[10];
        u8     oem2[10];
        u8     unknown2[8];
        u8     version[10];
        u8     unknown3[6];
        u8     date[8];
    } oem_info;

    #seekto 0x0480;
    struct {
        u16    lower;
        u16    upper;
    } scan_groups[10];

    #seekto 0x0500;
    struct {
        u8    call_code[6];
    } call_groups[20];

    #seekto 0x0580;
    struct {
        char    call_name[6];
    } call_group_name[20];

    #seekto 0x0800;
    struct {
        u8      ponmsg;
        char    dispstr[15];
        u8 x0810;
        u8 x0811;
        u8 x0812;
        u8 x0813;
        u8 x0814;
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
        u8      mode_sw_pwd[6];
        u8      reset_pwd[6];
        u16     pri_ch;
        u8      ani_sw;
        u8      ptt_delay;
        u8      ani[6];
        u8      dtmf_st;
        u8      bcl_a;
        u8      bcl_b;
        u8      ptt_id;
        u8      prich_sw;
        u8      rpt_set;
        u8      rpt_spk;
        u8      rpt_ptt;
        u8      alert;
        u8      pf1_func;
        u8      pf3_func;
        u8      workmode_b;
        u8      workmode_a;
        u8 x0845;
        u8      dtmf_tx_time;
        u8      dtmf_interval;
        u8      main_ab;
        u16     work_cha;
        u16     work_chb;
        u8 x084d;
        u8 x084e;
        u8 x084f;
        u8 x0850;
        u8 x0851;
        u8 x0852;
        u8 x0853;
        u8 x0854;
        u8      rpt_mode;
        u8      language;
        u8 x0857;
        u8 x0858;
        u8 x0859;
        u8 x085a;
        u8 x085b;
        u8 x085c;
        u8 x085d;
        u8 x085e;
        u8      single_display;
        u8      ring_time;
        u8      scg_a;
        u8      scg_b;
        u8 x0863;
        u8      rpt_tone;
        u8      rpt_hold;
        u8      scan_det;
        u8      sc_qt;
        u8 x0868;
        u8      smuteset;
        u8      callcode;
    } settings;

    #seekto 0x0880;
    struct {
        u32     rxfreq;
        u32     txoffset;
        u16     rxtone;
        u16     txtone;
        u8      unknown1:6,
                power:1,
                unknown2:1;
        u8      unknown3:1,
                shift_dir:2
                unknown4:2,
                mute_mode:2,
                iswide:1;
        u8      step;
        u8      squelch;
      } vfoa;

    #seekto 0x08c0;
    struct {
        u32     rxfreq;
        u32     txoffset;
        u16     rxtone;
        u16     txtone;
        u8      unknown1:6,
                power:1,
                unknown2:1;
        u8      unknown3:1,
                shift_dir:2
                unknown4:2,
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
        u8      unknown1:6,
                power:1,
                unknown2:1;
        u8      unknown3:2,
                scan_add:1,
                unknown4:2,
                mute_mode:2,
                iswide:1;
        u16     padding;
    } memory[1000];

    #seekto 0x4780;
    struct {
        u8    name[8];
    } names[1000];

    #seekto 0x6700;
    u8          valid[1000];
    """

# Support for the Wouxun KG-UV8D radio
# Serial coms are at 19200 baud
# The data is passed in variable length records
# Record structure:
#  Offset   Usage
#    0      start of record (\x7d)
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


@directory.register
class KGUV8DRadio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):

    """Wouxun KG-UV8D"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV8D"
    _model = "KG-UV8D"
    _file_ident = b"KGUV8D"
    BAUD_RATE = 19200
    POWER_LEVELS = [chirp_common.PowerLevel("L", watts=1),
                    chirp_common.PowerLevel("H", watts=5)]
    _mmap = ""

    def _checksum(self, data):
        cs = 0
        for byte in data:
            cs += ord(byte)
        return cs % 256

    def _write_record(self, cmd, payload=None):
        # build the packet
        _packet = '\x7d' + chr(cmd) + '\xff'
        _length = 0
        if payload:
            _length = len(payload)
        # update the length field
        _packet += chr(_length)
        if payload:
            # add the chars to the packet
            _packet += payload
        # calculate and add the checksum to the packet
        _packet += chr(self._checksum(_packet[1:]))
        LOG.debug("Sent:\n%s" % util.hexprint(_packet))
        self.pipe.write(_packet)

    def _read_record(self):
        # read 4 chars for the header
        _header = self.pipe.read(4)
        if len(_header) != 4:
            raise errors.RadioError('Radio did not respond')
        _length = ord(_header[3])
        _packet = self.pipe.read(_length)
        _cs = self._checksum(_header[1:])
        _cs += self._checksum(_packet)
        _cs %= 256
        _rcs = ord(self.pipe.read(1))
        LOG.debug("_cs =%x", _cs)
        LOG.debug("_rcs=%x", _rcs)
        return (_rcs != _cs, _packet)

# Identify the radio
#
# A Gotcha: the first identify packet returns a bad checksum, subsequent
# attempts return the correct checksum... (well it does on my radio!)
#
# The ID record returned by the radio also includes the current frequency range
# as 4 bytes big-endian in 10Hz increments
#
# Offset
#  0:10     Model, zero padded (Use first 7 chars for 'KG-UV8D')
#  11:14    UHF rx lower limit (in units of 10Hz)
#  15:18    UHF rx upper limit
#  19:22    UHF tx lower limit
#  23:26    UHF tx upper limit
#  27:30    VHF rx lower limit
#  31:34    VHF rx upper limit
#  35:38    VHF tx lower limit
#  39:42    VHF tx upper limit
#
    @classmethod
    def match_model(cls, filedata, filename):
        return cls._file_ident in filedata[0x400:0x408]

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
            LOG.debug("Model %s" % util.hexprint(_resp[0:7]))
            if _resp[0:7] == self._model:
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

    # TODO: This is a dumb, brute force method of downlolading the memory.
    # it would be smarter to only load the active areas and none of
    # the padding/unused areas.
    def _download(self):
        """Talk to a wouxun KG-UV8D and do a download"""
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
            req = chr(i / 256) + chr(i % 256) + chr(blocksize)
            self._write_record(CMD_RD, req)
            cs_error, resp = self._read_record()
            if cs_error:
                # TODO: probably should retry a few times here
                LOG.debug(util.hexprint(resp))
                raise Exception("Checksum error on read")
            LOG.debug("Got:\n%s" % util.hexprint(resp))
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
        """Talk to a wouxun KG-UV8D and do a upload"""
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
            req = chr(i / 256) + chr(i % 256)
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
        # TODO: This probably needs to be setup correctly to match the true
        # features of the radio
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
        rf.valid_tuning_steps = STEPS
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
        rf.valid_bands = [(134000000, 175000000),  # supports 2m
                          (400000000, 520000000)]  # supports 70cm
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.memory_bounds = (1, 999)  # 999 memories
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is currently under development. "
                           "There are no known issues with it, but you should "
                           "proceed with caution.")
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol

        tpol = False
        if _mem.txtone != 0xFFFF and (_mem.txtone & 0x2800) == 0x2800:
            tcode, tpol = _get_dcs(_mem.txtone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.txtone != 0xFFFF and _mem.txtone != 0x0:
            mem.rtone = (_mem.txtone & 0x7fff) / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        rpol = False
        if _mem.rxtone != 0xFFFF and (_mem.rxtone & 0x2800) == 0x2800:
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

        mem.power = self.POWER_LEVELS[_mem.power]
        mem.mode = _mem.iswide and "FM" or "NFM"
        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0x8000
            return val

        rx_mode = tx_mode = None
        rxtone = txtone = 0xFFFF

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
        # set the power
        if mem.power:
            _mem.power = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.power = True
        # TODO: set the correct mute mode, for now just
        # set to mute mode to QT (not QT+DTMF or QT*DTMF)
        _mem.mute_mode = 0

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
        cfg_grp = RadioSettingGroup("cfg_grp", "Configuration")
        vfoa_grp = RadioSettingGroup("vfoa_grp", "VFO A Settings")
        vfob_grp = RadioSettingGroup("vfob_grp", "VFO B Settings")
        key_grp = RadioSettingGroup("key_grp", "Key Settings")
        lmt_grp = RadioSettingGroup("lmt_grp", "Frequency Limits")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")

        group = RadioSettings(cfg_grp, vfoa_grp, vfob_grp,
                              key_grp, lmt_grp, oem_grp)

        #
        # Configuration Settings
        #
        rs = RadioSetting("channel_menu", "Menu available in channel mode",
                          RadioSettingValueBoolean(_settings.channel_menu))
        cfg_grp.append(rs)
        rs = RadioSetting("ponmsg", "Poweron message",
                          RadioSettingValueList(
                              PONMSG_LIST, PONMSG_LIST[_settings.ponmsg]))
        cfg_grp.append(rs)
        rs = RadioSetting("voice", "Voice Guide",
                          RadioSettingValueBoolean(_settings.voice))
        cfg_grp.append(rs)
        rs = RadioSetting("language", "Language",
                          RadioSettingValueList(LANGUAGE_LIST,
                                                LANGUAGE_LIST[_settings.
                                                              language]))
        cfg_grp.append(rs)
        rs = RadioSetting("timeout", "Timeout Timer",
                          RadioSettingValueInteger(15, 900,
                                                   _settings.timeout * 15, 15))
        cfg_grp.append(rs)
        rs = RadioSetting("toalarm", "Timeout Alarm",
                          RadioSettingValueInteger(0, 10, _settings.toalarm))
        cfg_grp.append(rs)
        rs = RadioSetting("roger_beep", "Roger Beep",
                          RadioSettingValueBoolean(_settings.roger_beep))
        cfg_grp.append(rs)
        rs = RadioSetting("power_save", "Power save",
                          RadioSettingValueBoolean(_settings.power_save))
        cfg_grp.append(rs)
        rs = RadioSetting("autolock", "Autolock",
                          RadioSettingValueBoolean(_settings.autolock))
        cfg_grp.append(rs)
        rs = RadioSetting("keylock", "Keypad Lock",
                          RadioSettingValueBoolean(_settings.keylock))
        cfg_grp.append(rs)
        rs = RadioSetting("beep", "Keypad Beep",
                          RadioSettingValueBoolean(_settings.beep))
        cfg_grp.append(rs)
        rs = RadioSetting("stopwatch", "Stopwatch",
                          RadioSettingValueBoolean(_settings.stopwatch))
        cfg_grp.append(rs)
        rs = RadioSetting("backlight", "Backlight",
                          RadioSettingValueList(BACKLIGHT_LIST,
                                                BACKLIGHT_LIST[_settings.
                                                               backlight]))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_st", "DTMF Sidetone",
                          RadioSettingValueList(DTMFST_LIST,
                                                DTMFST_LIST[_settings.
                                                            dtmf_st]))
        cfg_grp.append(rs)
        rs = RadioSetting("ani-id_sw", "ANI-ID Switch",
                          RadioSettingValueBoolean(_settings.ani_sw))
        cfg_grp.append(rs)
        rs = RadioSetting("ptt-id_delay", "PTT-ID Delay",
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[_settings.ptt_id]))
        cfg_grp.append(rs)
        rs = RadioSetting("ring_time", "Ring Time",
                          RadioSettingValueList(LIST_10,
                                                LIST_10[_settings.ring_time]))
        cfg_grp.append(rs)
        rs = RadioSetting("scan_rev", "Scan Mode",
                          RadioSettingValueList(SCANMODE_LIST,
                                                SCANMODE_LIST[_settings.
                                                              scan_rev]))
        cfg_grp.append(rs)
        rs = RadioSetting("vox", "VOX",
                          RadioSettingValueList(LIST_10,
                                                LIST_10[_settings.vox]))
        cfg_grp.append(rs)
        rs = RadioSetting("prich_sw", "Priority Channel Switch",
                          RadioSettingValueBoolean(_settings.prich_sw))
        cfg_grp.append(rs)
        rs = RadioSetting("pri_ch", "Priority Channel",
                          RadioSettingValueInteger(1, 999, _settings.pri_ch))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_mode", "Radio Mode",
                          RadioSettingValueList(RPTMODE_LIST,
                                                RPTMODE_LIST[_settings.
                                                             rpt_mode]))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_set", "Repeater Setting",
                          RadioSettingValueList(RPTSET_LIST,
                                                RPTSET_LIST[_settings.
                                                            rpt_set]))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_spk", "Repeater Mode Speaker",
                          RadioSettingValueBoolean(_settings.rpt_spk))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_ptt", "Repeater PTT",
                          RadioSettingValueBoolean(_settings.rpt_ptt))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_tx_time", "DTMF Tx Duration",
                          RadioSettingValueList(DTMF_TIMES,
                                                DTMF_TIMES[_settings.
                                                           dtmf_tx_time]))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_interval", "DTMF Interval",
                          RadioSettingValueList(DTMF_TIMES,
                                                DTMF_TIMES[_settings.
                                                           dtmf_interval]))
        cfg_grp.append(rs)
        rs = RadioSetting("alert", "Alert Tone",
                          RadioSettingValueList(ALERTS_LIST,
                                                ALERTS_LIST[_settings.alert]))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_tone", "Repeater Tone",
                          RadioSettingValueBoolean(_settings.rpt_tone))
        cfg_grp.append(rs)
        rs = RadioSetting("rpt_hold", "Repeater Hold Time",
                          RadioSettingValueList(HOLD_TIMES,
                                                HOLD_TIMES[_settings.
                                                           rpt_hold]))
        cfg_grp.append(rs)
        rs = RadioSetting("scan_det", "Scan DET",
                          RadioSettingValueBoolean(_settings.scan_det))
        cfg_grp.append(rs)
        rs = RadioSetting("sc_qt", "SC-QT",
                          RadioSettingValueList(SCQT_LIST,
                                                SCQT_LIST[_settings.smuteset]))
        cfg_grp.append(rs)
        rs = RadioSetting("smuteset", "SubFreq Mute",
                          RadioSettingValueList(SMUTESET_LIST,
                                                SMUTESET_LIST[_settings.
                                                              smuteset]))
        cfg_grp.append(rs)
        _pwd = "".join(map(chr, _settings.mode_sw_pwd))
        val = RadioSettingValueString(0, 6, _pwd)
        val.set_mutable(True)
        rs = RadioSetting("mode_sw_pwd", "Mode Switch Password", val)
        cfg_grp.append(rs)
        _pwd = "".join(map(chr, _settings.reset_pwd))
        val = RadioSettingValueString(0, 6, _pwd)
        val.set_mutable(True)
        rs = RadioSetting("reset_pwd", "Reset Password", val)
        cfg_grp.append(rs)
        #
        # VFO A Settings
        #
        rs = RadioSetting("vfoa_mode", "VFO A Workmode",
                          RadioSettingValueList(WORKMODE_LIST,
                                                WORKMODE_LIST[_settings.
                                                              workmode_a]))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa_chan", "VFO A Channel",
                          RadioSettingValueInteger(1, 999, _settings.work_cha))
        vfoa_grp.append(rs)
        rs = RadioSetting("rxfreqa", "VFO A Rx Frequency",
                          RadioSettingValueInteger(
                              134000000, 520000000, _vfoa.rxfreq * 10, 5000))
        vfoa_grp.append(rs)
        rs = RadioSetting("txoffa", "VFO A Tx Offset",
                          RadioSettingValueInteger(
                              0, 520000000, _vfoa.txoffset * 10, 5000))
        vfoa_grp.append(rs)
        #   u16   rxtone;
        #   u16   txtone;
        rs = RadioSetting("vfoa_power", "VFO A Power",
                          RadioSettingValueList(
                              POWER_LIST, POWER_LIST[_vfoa.power]))
        vfoa_grp.append(rs)
        #         shift_dir:2
        rs = RadioSetting("vfoa_iswide", "VFO A NBFM",
                          RadioSettingValueList(
                              BANDWIDTH_LIST, BANDWIDTH_LIST[_vfoa.iswide]))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa_mute_mode", "VFO A Mute",
                          RadioSettingValueList(
                              SPMUTE_LIST, SPMUTE_LIST[_vfoa.mute_mode]))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa_step", "VFO A Step (kHz)",
                          RadioSettingValueList(
                              STEP_LIST, STEP_LIST[_vfoa.step]))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa_squelch", "VFO A Squelch",
                          RadioSettingValueList(
                              LIST_10, LIST_10[_vfoa.squelch]))
        vfoa_grp.append(rs)
        rs = RadioSetting("bcl_a", "Busy Channel Lock-out A",
                          RadioSettingValueBoolean(_settings.bcl_a))
        vfoa_grp.append(rs)
        #
        # VFO B Settings
        #
        rs = RadioSetting("vfob_mode", "VFO B Workmode",
                          RadioSettingValueList(
                              WORKMODE_LIST,
                              WORKMODE_LIST[_settings.workmode_b]))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob_chan", "VFO B Channel",
                          RadioSettingValueInteger(1, 999, _settings.work_chb))
        vfob_grp.append(rs)
        rs = RadioSetting("rxfreqb", "VFO B Rx Frequency",
                          RadioSettingValueInteger(
                              134000000, 520000000, _vfob.rxfreq * 10, 5000))
        vfob_grp.append(rs)
        rs = RadioSetting("txoffb", "VFO B Tx Offset",
                          RadioSettingValueInteger(
                              0, 520000000, _vfob.txoffset * 10, 5000))
        vfob_grp.append(rs)
        #   u16   rxtone;
        #   u16   txtone;
        rs = RadioSetting("vfob_power", "VFO B Power",
                          RadioSettingValueList(
                              POWER_LIST, POWER_LIST[_vfob.power]))
        vfob_grp.append(rs)
        #         shift_dir:2
        rs = RadioSetting("vfob_iswide", "VFO B NBFM",
                          RadioSettingValueList(
                              BANDWIDTH_LIST, BANDWIDTH_LIST[_vfob.iswide]))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob_mute_mode", "VFO B Mute",
                          RadioSettingValueList(
                              SPMUTE_LIST, SPMUTE_LIST[_vfob.mute_mode]))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob_step", "VFO B Step (kHz)",
                          RadioSettingValueList(
                              STEP_LIST, STEP_LIST[_vfob.step]))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob_squelch", "VFO B Squelch",
                          RadioSettingValueList(
                              LIST_10, LIST_10[_vfob.squelch]))
        vfob_grp.append(rs)
        rs = RadioSetting("bcl_b", "Busy Channel Lock-out B",
                          RadioSettingValueBoolean(_settings.bcl_b))
        vfob_grp.append(rs)
        #
        # Key Settings
        #
        _msg = str(_settings.dispstr).split("\0")[0]
        val = RadioSettingValueString(0, 15, _msg)
        val.set_mutable(True)
        rs = RadioSetting("dispstr", "Display Message", val)
        key_grp.append(rs)
        _ani = ""
        for i in _settings.ani:
            if i < 10:
                _ani += chr(i + 0x30)
            else:
                break
        val = RadioSettingValueString(0, 6, _ani)
        val.set_mutable(True)
        rs = RadioSetting("ani", "ANI code", val)
        key_grp.append(rs)
        rs = RadioSetting("pf1_func", "PF1 Key function",
                          RadioSettingValueList(
                              PF1KEY_LIST,
                              PF1KEY_LIST[self._memobj.settings.pf1_func]))
        key_grp.append(rs)
        rs = RadioSetting("pf3_func", "PF3 Key function",
                          RadioSettingValueList(
                              PF3KEY_LIST,
                              PF3KEY_LIST[self._memobj.settings.pf3_func]))
        key_grp.append(rs)

        #
        # Scan Group Settings
        #
        # settings:
        #   u8    scg_a;
        #   u8    scg_b;
        #
        #   struct {
        #       u16    lower;
        #       u16    upper;
        #   } scan_groups[10];

        #
        # Call group settings
        #

        #
        # Limits settings
        #
        rs = RadioSetting("urx_start", "UHF RX Lower Limit",
                          RadioSettingValueInteger(
                              400000000, 520000000,
                              self._memobj.uhf_limits.rx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("urx_stop", "UHF RX Upper Limit",
                          RadioSettingValueInteger(
                              400000000, 520000000,
                              self._memobj.uhf_limits.rx_stop * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("utx_start", "UHF TX Lower Limit",
                          RadioSettingValueInteger(
                              400000000, 520000000,
                              self._memobj.uhf_limits.tx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("utx_stop", "UHF TX Upper Limit",
                          RadioSettingValueInteger(
                              400000000, 520000000,
                              self._memobj.uhf_limits.tx_stop * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vrx_start", "VHF RX Lower Limit",
                          RadioSettingValueInteger(
                              134000000, 174997500,
                              self._memobj.vhf_limits.rx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vrx_stop", "VHF RX Upper Limit",
                          RadioSettingValueInteger(
                              134000000, 174997500,
                              self._memobj.vhf_limits.rx_stop * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vtx_start", "VHF TX Lower Limit",
                          RadioSettingValueInteger(
                              134000000, 174997500,
                              self._memobj.vhf_limits.tx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vtx_stop", "VHF TX Upper Limit",
                          RadioSettingValueInteger(
                              134000000, 174997500,
                              self._memobj.vhf_limits.tx_stop * 10, 5000))
        lmt_grp.append(rs)

        #
        # OEM info
        #
        def _decode(lst):
            _str = ''.join([chr(c) for c in lst
                            if chr(c) in chirp_common.CHARSET_ASCII])
            return _str

        _str = _decode(self._memobj.oem_info.model)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("model", "Model", val)
        oem_grp.append(rs)
        _str = _decode(self._memobj.oem_info.oem1)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem1", "OEM String 1", val)
        oem_grp.append(rs)
        _str = _decode(self._memobj.oem_info.oem2)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem2", "OEM String 2", val)
        oem_grp.append(rs)
        _str = _decode(self._memobj.oem_info.version)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("version", "Software Version", val)
        oem_grp.append(rs)
        _str = _decode(self._memobj.oem_info.date)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("date", "OEM Date", val)
        oem_grp.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None
