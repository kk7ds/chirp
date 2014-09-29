# Copyright 2014 Ron Wellsted <ron@wellsted.org.uk> M0RNW
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
from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
                RadioSettingValueBoolean, RadioSettingValueList, \
                RadioSettingValueInteger, RadioSettingValueString

if os.getenv("CHIRP_DEBUG"):
    CHIRP_DEBUG = True
else:
    CHIRP_DEBUG = False

KGUV8D_DTCS = sorted(chirp_common.DTCS_CODES)

CMD_ID = 128
CMD_END = 129
CMD_RD = 130
CMD_WR = 131

MEM_VALID = 158

AB_LIST = ["A", "B"]
STEPS = [5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0, 100.0]
STEP_LIST = [str(x) for x in STEPS]
ROGER_LIST = ["Off", "BOT", "EOT", "Both"]
TIMEOUT_LIST = ["Off"] + [str(x) + "s" for x in range(15, 901, 15)]
VOX_LIST = ["Off"] + ["%s" % x for x in range(1, 10)]
BANDWIDTH_LIST = ["Wide", "Narrow"]
VOICE_LIST = ["Off", "On"]
LANGUAGE_LIST = ["English", "Chinese"]
SCANMODE_LIST = ["TO", "CO", "SE"]
PF1KEY_LIST = ["Call", "VFTX"]
PF3KEY_LIST = ["Scan", "Lamp", "Tele Alarm", "SOS-CH", "Radio", "Disable"]
WORKMODE_LIST = ["VFO", "Channel No.", "Frequency + No", "Name"]
BACKLIGHT_LIST = ["Always On"] + [str(x) + "s" for x in range(1, 21)] + \
                ["Always Off"]
OFFSET_LIST = ["+", "-"]
PONMSG_LIST = ["Bitmap", "Battery Volts"]
SPMUTE_LIST = ["QT*DTMF", "QT+DTMF", "QT"]
DTMFST_LIST = ["DT-ST", "ANI-ST", "DT-ANI", "Off"]
RPTSET_LIST = ["X-DIRPT", "X-TWRPT"]
ALERTS = [1750, 2100, 1000, 1450]
ALERTS_LIST = [str(x) for x in ALERTS]
PTTID_LIST = ["BOT", "EOT", "Both"]
RING_LIST = ["Off"] + ["%s" % x for x in range(1, 11)]
SCANGRP_LIST = ["All"] + ["%s" % x for x in range(1, 11)]
SCQT_LIST = ["All", "Decoder", "Encoder"]
SMUTESET_LIST = ["Off", "Tx", "Rx", "Tx/Rx"]

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
        char    model[8];
        u8      unknown[2];
        char    oem1[10];
        char    oem2[10];
        char    unknown2[8];
        char    version[10];
        u8      unknown3[6];
        char    date[8];
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
        u8      workmode_a;
        u8      workmode_b;
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
        u8      ring;
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
        u8      unknown1:5,
                power:1,
                unknown2:2;
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
        u8      unknown1:5,
                power:1,
                unknown2:2;
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
        u8      unknown1:5,
                power:1,
                unknown2:2;
        u8      unknown3:2,
                scan_add:1,
                unknown4:2,
                mute_mode:2,
                iswide:1;
        u16     padding;
    } memory[1000];

    #seekto 0x4780;
    struct {
        char    name[8];
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
    _file_ident = "KGUV8D"
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
        if CHIRP_DEBUG:
            print "Sent:\n%s" % util.hexprint(_packet)
        self.pipe.write(_packet)

    def _read_record(self):
        # read 4 chars for the header
        _header = self.pipe.read(4)
        _length = ord(_header[3])
        _packet = self.pipe.read(_length)
        _cs = self._checksum(_header[1:])
        _cs += self._checksum(_packet)
        _cs %= 256
        _rcs = ord(self.pipe.read(1))
        if CHIRP_DEBUG:
            print "_cs =", _cs
            print "_rcs=", _rcs
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
##
    @classmethod
    def match_model(cls, filedata, filename):
        return cls._file_ident in filedata[0x400:0x408]

    def _identify(self):
        """Do the identification dance"""
        for _i in range(0, 10):
            self._write_record(CMD_ID)
            _chksum_err, _resp = self._read_record()
            if CHIRP_DEBUG:
                print "Got:\n%s" % util.hexprint(_resp)
            if _chksum_err:
                print "Checksum error: retrying ident..."
                time.sleep(0.100)
                continue
            if CHIRP_DEBUG:
                print "Model %s" % util.hexprint(_resp[0:7])
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
        except Exception, e:
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
        except Exception, e:
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
                print util.hexprint(resp)
                raise Exception("Checksum error on read")
            if CHIRP_DEBUG:
                print "Got:\n%s" % util.hexprint(resp)
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
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        return

    def _do_upload(self, start, end, blocksize):
        ptr = start
        for i in range(start, end, blocksize):
            req = chr(i / 256) + chr(i % 256)
            chunk = self.get_mmap()[ptr:ptr + blocksize]
            self._write_record(CMD_WR, req + chunk)
            if CHIRP_DEBUG:
                print util.hexprint(req + chunk)
            cserr, ack = self._read_record()
            if CHIRP_DEBUG:
                print util.hexprint(ack)
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
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 8
        rf.valid_duplexes = ["", "+", "-", "split"]
        rf.valid_bands = [(134000000, 175000000),  # supports 2m
                          (400000000, 520000000)]  # supports 70cm
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.memory_bounds = (1, 999)  # 999 memories
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number
        _valid = self._memobj.valid[mem.number]

        if CHIRP_DEBUG:
            print number, _valid == MEM_VALID
        if _valid != MEM_VALID:
            mem.empty = True
            return mem
        else:
            mem.empty = False

        mem.freq = int(_mem.rxfreq) * 10

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _nam.name:
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0x3fff]:
            txmode = ""
        elif _mem.txtone >= 0x8000 and _mem.txtone < 0xc000:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone % 16384) / 10.0
        elif _mem.txtone >= 0x4000 and _mem.txtone < 0x8000:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = KGUV8D_DTCS[index]
        else:
            print "Bug: txtone is %04x" % _mem.txtone

        if _mem.rxtone in [0, 0x3fff]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone % 16384) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.rx_dtcs = KGUV8D_DTCS[index]
        else:
            print "Bug: rxtone is %04x" % _mem.rxtone

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan_add:
            mem.skip = "S"

        mem.power = self.POWER_LEVELS[_mem.power]
        mem.mode = _mem.iswide and "FM" or "NFM"
        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0x8000
            return val

        if mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
        elif mem.tmode == "Tone":
            tx_mode = mem.tmode
            rx_mode = None
        else:
            tx_mode = rx_mode = mem.tmode

        if tx_mode == "DTCS":
            _mem.txtone = mem.tmode != "DTCS" and \
                _set_dcs(mem.dtcs, mem.dtcs_polarity[0]) or \
                _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[0])
            _mem.txtone += 0x4000
        elif tx_mode:
            _mem.txtone = tx_mode == "Tone" and \
                int(mem.rtone * 10) or int(mem.ctone * 10)
            _mem.txtone += 0x8000
        else:
            _mem.txtone = 0

        if rx_mode == "DTCS":
            _mem.rxtone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            _mem.rxtone += 0x4000
        elif rx_mode:
            _mem.rxtone = int(mem.ctone * 10)
            _mem.rxtone += 0x8000
        else:
            _mem.rxtone = 0

        if CHIRP_DEBUG:
            print "Set TX %s (%i) RX %s (%i)" % (tx_mode, _mem.txtone,
                                                 rx_mode, _mem.rxtone)

    def set_memory(self, mem):
        number = mem.number

        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        if mem.empty:
            wipe_memory(_mem, "\x00")
            self._memobj.valid[mem.number] = 0
            return

        _mem.rxfreq = int(mem.freq / 10)
        if mem.duplex == "split":
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
        _mem.skip = mem.skip != "S"
        _mem.iswide = mem.mode != "NFM"

        self._set_tone(mem, _mem)

        if mem.power:
            _mem.power = not self.POWER_LEVELS.index(mem.power)
        else:
            _mem.power = True

        for i in range(0, len(mem.name)):
            if mem.name[i]:
                _nam.name[i] = mem.name[i]
        self._memobj.valid[mem.number] = MEM_VALID

    def _get_settings(self):
        _settings = self._memobj.settings
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        cfg_grp = RadioSettingGroup("cfg_grp", "Configuration Settings")
        vfo_grp = RadioSettingGroup("vfo_grp", "VFO Settings")
        key_grp = RadioSettingGroup("key_grp", "Key Settings")
        scn_grp = RadioSettingGroup("scn_grp", "Scan Group")
        cal_grp = RadioSettingGroup("cal_grp", "Call Group")
        lmt_grp = RadioSettingGroup("lmt_grp", "Frequency Limits")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")
        group = RadioSettingGroup("top", "All Settings", cfg_grp,
                        vfo_grp, key_grp, scn_grp, cal_grp, lmt_grp, oem_grp)

        #
        # Configuration Settings
        #
        rs = RadioSetting("ponmsg", "Poweron message", RadioSettingValueList(
                        PONMSG_LIST, PONMSG_LIST[self._memobj.settings.ponmsg]))
        cfg_grp.append(rs)
        rs = RadioSetting("voice", "Voice Guide", RadioSettingValueBoolean(
                            self._memobj.settings.voice))
        cfg_grp.append(rs)
        rs = RadioSetting("timeout", "Timeout Timer",
                        RadioSettingValueInteger(15, 900,
                            self._memobj.settings.timeout * 15, 15))
        cfg_grp.append(rs)
        rs = RadioSetting("toalarm", "Timeout Alarm",
                        RadioSettingValueInteger(0, 10,
                            self._memobj.settings.toalarm))
        cfg_grp.append(rs)
        rs = RadioSetting("channel_menu", "Menu available in channel mode",
                        RadioSettingValueBoolean(
                            self._memobj.settings.channel_menu))
        cfg_grp.append(rs)
        rs = RadioSetting("power_save", "Power save", RadioSettingValueBoolean(
                            self._memobj.settings.power_save))
        cfg_grp.append(rs)
        rs = RadioSetting("autolock", "Autolock", RadioSettingValueBoolean(
                            self._memobj.settings.autolock))
        cfg_grp.append(rs)
        rs = RadioSetting("keylock", "Keypad Lock", RadioSettingValueBoolean(
                            self._memobj.settings.keylock))
        cfg_grp.append(rs)
        rs = RadioSetting("beep", "Keypad Beep", RadioSettingValueBoolean(
                            self._memobj.settings.keylock))
        cfg_grp.append(rs)
        rs = RadioSetting("stopwatch", "Stopwatch", RadioSettingValueBoolean(
                            self._memobj.settings.keylock))
        cfg_grp.append(rs)

        #
        # VFO Settings
        #
        #settings:
        #   u8    workmode_a;
        #   u8    workmode_b;
        #   u16   work_cha;
        #   u16   work_chb;
        # vfoa/b:
        #   u32   rxfreq;
        #   u32   txoffset;
        #   u16   rxtone;
        #   u16   txtone;
        #   u8    unknown1:5,
        #         power:1,
        #         unknown2:;
        #   u8    unknown3:1,
        #         shift_dir:2
        #         unknown4:2,
        #         mute_mode:2,
        #         iswide:1;
        #   u8    step;
        #   u8    squelch;

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
            _ani += chr(i + 0x30)
        val = RadioSettingValueString(0, 6, _ani)
        val.set_mutable(True)
        rs = RadioSetting("ani", "ANI code", val)
        key_grp.append(rs)
        rs = RadioSetting("pf1_func", "PF1 Key function", RadioSettingValueList(
                            PF1KEY_LIST,
                            PF1KEY_LIST[self._memobj.settings.pf1_func]))
        key_grp.append(rs)
        rs = RadioSetting("pf3_func", "PF3 Key function", RadioSettingValueList(
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
                            RadioSettingValueInteger(400000000, 520000000,
                                self._memobj.uhf_limits.rx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("urx_stop", "UHF RX Upper Limit",
                            RadioSettingValueInteger(400000000, 520000000,
                                self._memobj.uhf_limits.rx_stop * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("utx_start", "UHF TX Lower Limit",
                            RadioSettingValueInteger(400000000, 520000000,
                                self._memobj.uhf_limits.tx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("utx_stop", "UHF TX Upper Limit",
                            RadioSettingValueInteger(400000000, 520000000,
                                self._memobj.uhf_limits.tx_stop * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vrx_start", "VHF RX Lower Limit",
                            RadioSettingValueInteger(134000000, 174997500,
                                self._memobj.vhf_limits.rx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vrx_stop", "VHF RX Upper Limit",
                            RadioSettingValueInteger(134000000, 174997500,
                                self._memobj.vhf_limits.rx_stop * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vtx_start", "VHF TX Lower Limit",
                            RadioSettingValueInteger(134000000, 174997500,
                                self._memobj.vhf_limits.tx_start * 10, 5000))
        lmt_grp.append(rs)
        rs = RadioSetting("vtx_stop", "VHF TX Upper Limit",
                            RadioSettingValueInteger(134000000, 174997500,
                                self._memobj.vhf_limits.tx_stop * 10, 5000))
        lmt_grp.append(rs)

        #
        # OEM info
        #
        # struct {
        #       char    model[8];
        #       u8      unknown[2];
        #       char    oem1[10];
        #       char    oem2[10];
        #       char    unknown2[8];
        #       char    version[10];
        #       u8      unknown3[6];
        #       char    date[8];
        # } oem_info;
        _str = str(self._memobj.oem_info.model).split("\0")[0]
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("model", "Model", val)
        oem_grp.append(rs)
        _str = str(self._memobj.oem_info.oem1).split("\0")[0]
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem1", "OEM String 1", val)
        oem_grp.append(rs)
        _str = str(self._memobj.oem_info.oem2).split("\0")[0]
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem2", "OEM String 2", val)
        oem_grp.append(rs)
        _str = str(self._memobj.oem_info.version).split("\0")[0]
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("version", "Software Version", val)
        oem_grp.append(rs)
        _str = str(self._memobj.oem_info.date).split("\0")[0]
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
            print "Failed to parse settings:"
            traceback.print_exc()
            return None
