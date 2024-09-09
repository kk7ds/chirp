# Copyright 2022 Matthew Handley <kf7tal@gmail.com>
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

"""Wouxun KG-UV920P-A radio management module based"""

import time
import logging
from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettingValueMap, RadioSettingValueFloat, RadioSettings
import struct

LOG = logging.getLogger(__name__)

CMD_ID = 0x80
CMD_END = 0x81
CMD_RD = 0x82
CMD_WR = 0x83

CHARSET_NUMERIC = "0123456789"
CHARSET = "0123456789" + \
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

M_POWER_MAP = [('10', 1),
               ('20', 2)]
ROGER_LIST = ["Off", "BOT", "EOT", "Both"]
VOICE_LIST = ["Off", "Chinese", "English"]
SC_REV_MAP = [('Timeout (TO)',  1),
              ('Carrier (CO)',  2),
              ('Stop (SE)',     3)]
TOT_MAP = [('%d' % i, int('%02d' % i, 16)) for i in range(1, 61)]
TOA_MAP = [('Off', 0)] + \
          [('%d' % i, int('%02d' % i, 16)) for i in range(1, 11)]
RING_MAP = [('Off', 0)] + \
           [('%d' % i, int('%02d' % i, 16)) for i in range(1, 11)]
DTMF_ST_LIST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
PTT_ID_LIST = ["BOT", "EOT", "Both"]
PTT_ID_MAP = [('BOT',  1),
              ('EOT',  2),
              ('Both', 3)]
BACKLIGHT_LIST = ["Off", "White", "Blue", "Green"]
SPEAKER_MAP = [('1',   1),
               ('2',   2),
               ('1+2', 3)]
RPT_MODE_LIST = ["Off", "X-DIRPT", "X-TWRPT", "CRPT-RX", "CRPT-TX"]
APO_TIME_LIST = ["Off", "30", "60", "90", "120", "150"]
ALERT_MAP = [('1750', 1),
             ('2100', 2),
             ('1000', 3),
             ('1450', 4)]
FAN_MODE_LIST = ["TX", "Hi-Temp/TX", "Always"]
SCAN_GROUP_LIST = ["All", "1", "2", "3", "4"]
WORKMODE_MAP = [('VFO',             1),
                ('Ch. No.',         2),
                ('Ch. No.+Freq.',   3),
                ('Ch. No.+Name',    4)]
AB_LIST = ["A", "B"]
POWER_MAP = [('L', 0),
             ('M', 1),
             ('H', 3)]
BANDWIDTH_MAP = [('NFM', 0b11),
                 ('FM',  0b00)]
SCRAMBLER_LIST = ["Off", "1", "2", "3", "4", "5", "6", "7", "8"]
ANS_LIST = ["Off", "Normal", "Strong"]
DTMF_TIMES = [str(x) for x in range(80, 501, 20)]
DTMF_INTERVALS = [str(x) for x in range(60, 501, 20)]
ROGER_TIMES = [str(x) for x in range(20, 1001, 20)]
PTT_ID_DELAY_MAP = [(str(x), x/100) for x in range(100, 1001, 100)]
ROGER_INTERVALS = ROGER_TIMES
TONE_MAP = [('Off', 0x0000)] + \
           [('%.1f' % tone, int(tone * 10)) for tone in chirp_common.TONES] + \
           [('DN%d' % tone, int(0x8000 + tone * 10))
               for tone in chirp_common.DTCS_CODES] + \
           [('DR%d' % tone, int(0xC000 + tone * 10))
               for tone in chirp_common.DTCS_CODES]
DUPLEX_LIST = ["Off", "+", "-"]

# structure elements whose name starts with x are currently unidentified
_MEM_FORMAT = """
    #seekto 0x0040;
    struct {
        u8      left[8];
        u8      right[8];
    } ponmsg;

    // Limit changes here don't persist, so may be incorrect. Currently unused
    // in driver.
    #seekto 0x0070;
    struct {
        u16    uhf_rx_start;    // 0x0070
        u16    uhf_rx_stop;     // 0x0072
        u16    vhf_rx_start;    // 0x0074
        u16    vhf_rx_stop;     // 0x0076

        u16    uhf_tx_start;    // 0x0078
        u16    uhf_tx_stop;     // 0x007A
        u16    vhf_tx_start;    // 0x007C
        u16    vhf_tx_stop;     // 0x007E
    } limits;

    #seekto 0x0068;
    struct {
        u8     unknown1[8];     // 0x0068
        u8     x0070[368];
        u8     x01E0[8];
        u8     x01E8[8];
        u8     model[8];        // 0x01F0
        u8     date[8];
        u8     oem1[8];
        u8     oem2[8];
        u8     unknown2[8];
        u8     unknown3[8];
    } oem_info;

    #seekto 0x0250;
    struct {
        u32     rxfreq;
        u32     txoffset;
        u16     txtone;
        u16     rxtone;
        u8      unknown1_7downto5:3,
                mute_mode:2,
                unknown1_3downto0:3;
        u8      named:1,
                scan_add:1,
                power:2,
                unknown2_32:2,
                isnarrow:2;
        u8      unknown3_7downto2:6,
                duplex:2;
        u8      unknown4:3,
                compander:1,
                scrambler:4;
    } vfoa;

    #seekto 0x0260;
    struct {
        u32     rxfreq;
        u32     txoffset;
        u16     txtone;
        u16     rxtone;
        u8      unknown1_7downto5:3,
                mute_mode:2,
                unknown1_3downto0:3;
        u8      named:1,
                scan_add:1,
                power:2,
                unknown2_3downto2:2,
                isnarrow:2;
        u8      unknown3_7downto2:6,
                duplex:2;
        u8      unknown4:3,
                compander:1,
                scrambler:4;
    } vfob;

    #seekto 0x0270;
    struct {
        u8      rc_power;       // 0x0270
        u8      voice;          // 0x0271
        u8      tot;            // 0x0272
        u8      toa;            // 0x0273
        u8      roger;          // 0x0274
        u8      sc_rev;         // 0x0275
        u8      dtmf_st;        // 0x0276
        u8      ptt_id;         // 0x0277
        u8      ring;           // 0x0278
        u8      ani_sw;         // 0x0279
        u8      x027A;
        u8      alert;          // 0x027B
        u8      bcl_a;          // 0x027C
        u8      pri_ch_sw;      // 0x027D
        u8      scan_group;     // 0x027E
        u8      ptt_id_delay;   // 0x027F

        u8      x0280;
        u8      x0281;
        u8      beep;           // 0x0282
        u8      x0283;
        u8      x0284;
        u8      tx_led;         // 0x0285
        u8      wt_led;         // 0x0286
        u8      rx_led;         // 0x0287
        u8      active_display; // 0x0288
        u8      workmode_a;     // 0x0289
        u8      workmode_b;     // 0x028A
        u8      squelch_a;      // 0x028B
        u8      squelch_b;      // 0x028C
        u8      step_a;         // 0x028D
        u8      step_b;         // 0x028E
        u8      single_display; // 0x028F

        u8      x0290;
        u16     work_cha;       // 0x0291
        u8      x0293;
        u16     work_chb;       // 0x0294
        u8      dtmf_time;      // 0x0296
        u8      x0297;
        u8      dtmf_interval;  // 0x0298
        u8      x0299;
        u16     pri_ch;         // 0x029A
        u8      x029C;
        u8      x029D;
        u8      speaker;        // 0x029E
        u8      x029F;

        u8      rpt_spk;        // 0x02A0
        u8      rpt_ptt;        // 0x02A1
        u8      autolock;       // 0x02A2
        u8      apo_time;       // 0x02A3
        u8      low_v;          // 0x02A4
        u8      fan_mode;       // 0x02A5
        u8      x02A6;
        u8      rc_sw;          // 0x02A7
        u8      x02A8;
        u8      roger_time;     // 0x02A9
        u8      roger_int;      // 0x02AA
        u8      bcl_b;          // 0x02AB
        u8      m_power_set;    // 0x02AC
        u8      x02AD;
        u8      ans;            // 0x02AE
        u8      x02AF;

        u8      ani[3];         // 0x02B0
        u8      x02B3;
        u8      ani_mcc[3];     // 0x02B4
        u8      x02B7;
        u8      ani_scc[3];     // 0x02B8
        u8      x02BB;
        u8      ani_ctrl[3];    // 0x02BC
        u8      x02BF;

        u8      roger_begin[4]; // 0x02C0
        u8      roger_end[4];   // 0x02C4
        u8      x02C8[8];

        u16     grp1_lower;     // 0x02D0
        u16     grp1_upper;
        u16     grp2_lower;     // 0x02D4
        u16     grp2_upper;
        u16     grp3_lower;     // 0x02D8
        u16     grp3_upper;
        u16     grp4_lower;     // 0x02DC
        u16     grp4_upper;

        u8      x02E0[16];
        u8      x02F0[16];
        u8      x0300[16];

        u8      x0310[7];
        u8      rpt_tone;       // 0x0317
        u8      x0318[8];

        u8      x0320[16];
        u8      x0330[16];
        u8      x0340[16];
        u8      x0350[16];
        u8      x0360[16];
        u8      x0370[16];
        u8      x0380[16];
        u8      x0390[16];
        u8      x03A0[16];
        u8      x03B0[16];

        u8      rpt_mode;       // 0x03C0
        u8      x03C1;
        u8      x03C2;
        u8      x03C3;
        u8      x03C4;
        u8      x03C5;
        u8      scan_det;       // 0x0x3C6
    } settings;

    #seekto 0x0400;
    struct {
        u16     freq;
    } fm_preset[20];

    #seekto 0x0800;
    struct {
        u32     rxfreq;
        u32     txfreq;
        u16     txtone;
        u16     rxtone;
        u8      unknown1_7downto5:3,
                mute_mode:2,
                unknown1_3downto0:3;
        u8      named:1,
                scan_add:1,
                power:2,
                unknown2_32:2,
                isnarrow:2;
        u8      unknown3_7downto2:6,
                shift_dir:2;
        u8      unknown4:3,
                compander:1,
                scrambler:4;
    } memory[999];

    #seekto 0x4700;
    struct {
        u8      name[8];
    } names[999];
    """


def _checksum(data):
    cs = 0
    for byte in data:
        cs += byte
    return cs % 16


def _str_decode(in_str):
    out_str = ''
    for c in in_str:
        if c < len(CHARSET):
            out_str += CHARSET[c]
    return out_str.rstrip()


def _str_encode(in_str):
    out_str = []
    for c in in_str:
        try:
            out_str.append(CHARSET.index(c))
        except ValueError:
            pass
    while len(out_str) < 8:
        out_str.append(CHARSET.index(' '))
    return bytes(out_str)


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


def _ani_decode(in_ani):
    return ''.join(['%02x' % b for b in in_ani]).strip('c')


def _ani_encode(in_ani):
    ani_str = ''
    while len(in_ani) < 6:
        in_ani += 'c'
    for i in range(3):
        ani_str += chr(int(in_ani[i*2:i*2+2], 16))
    return ani_str


def _chnum_decode(in_ch):
    return int(('%04x' % in_ch)[0:3])


def _chnum_encode(in_ch):
    return int('%03d0' % in_ch, 16)


def _roger_decode(in_roger):
    return ''.join(['%02x' % b for b in in_roger]).strip('ef')


def _roger_encode(in_roger):
    roger_str = ''
    in_roger = 'e' + in_roger
    while len(in_roger) < 8:
        in_roger += 'f'
    for i in range(4):
        roger_str += chr(int(in_roger[i*2:i*2+2], 16))
    return roger_str


def _get_tone(_mem, mem):
    def _get_dcs(val):
        code = (val & 0x3FF)
        pol = (val & 0x4000) and "R" or "N"
        return code, pol

    tpol = False
    if _mem.txtone != 0xFFFF and (_mem.txtone & 0x8000) == 0x8000:
        tcode, tpol = _get_dcs(_mem.txtone)
        mem.dtcs = tcode
        txmode = "DTCS"
    elif _mem.txtone != 0xFFFF and _mem.txtone != 0x0:
        mem.rtone = (_mem.txtone & 0xFff) / 10.0
        txmode = "Tone"
    else:
        txmode = ""

    rpol = False
    if _mem.rxtone != 0xFFFF and (_mem.rxtone & 0x8000) == 0x8000:
        rcode, rpol = _get_dcs(_mem.rxtone)
        mem.rx_dtcs = rcode
        rxmode = "DTCS"
    elif _mem.rxtone != 0xFFFF and _mem.rxtone != 0x0:
        mem.ctone = (_mem.rxtone & 0xFff) / 10.0
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


def _set_tone(mem, _mem):
    def _set_dcs(code, pol):
        val = (code & 0x3FF) + 0x8000
        if pol == "R":
            val += 0x4000
        return val

    rx_mode = tx_mode = None
    rxtone = txtone = 0

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


# Support for the Wouxun KG-UV920P-A radio
# Serial coms are at 19200 baud
# The data is passed in variable length records
# Record structure:
#  Offset   Usage
#    0      start of record (\x7e)
#    1      Command (\x80 Identify \x81 End/Reboot \x82 Read \x83 Write)
#    2      direction (\xff PC-> Radio, \x00 Radio -> PC)
#    3      length of payload (excluding header/checksum) (n)
#    4      payload (n bytes)
#    4+n+1  checksum - byte sum (% 16) of bytes 1 -> 4+n
#
# Memory Read Records:
# the payload is 3 bytes, first 2 are offset (big endian),
# 3rd is number of bytes to read
# Memory Write Records:
# 2 bytes location + data.


@directory.register
class KGUV920PARadio(chirp_common.CloneModeRadio,
                     chirp_common.ExperimentalRadio):

    """Wouxun KG-UV920P-A"""
    VENDOR = "Wouxun"
    MODEL = "KG-UV920P-A"
    _model = "KG-UV920Rr"   # what the radio responds to CMD_ID with
    _file_ident = b"KGUV920PA"
    BAUD_RATE = 19200
    POWER_LEVELS = [chirp_common.PowerLevel("L", watts=5),
                    chirp_common.PowerLevel("M", watts=20),
                    chirp_common.PowerLevel("H", watts=50)]

    def _write_record(self, cmd, payload=None):
        _length = 0
        if payload:
            _length = len(payload)
        _packet = struct.pack('BBBB', 0x7E, cmd, 0xFF, _length)
        if payload:
            # add the chars to the packet
            _packet += payload
        # calculate and add the checksum to the packet
        _packet += bytes([_checksum(_packet[1:])])
        LOG.debug("Sent:\n%s" % util.hexprint(_packet))
        self.pipe.write(_packet)

    def _read_record(self):
        # read 4 chars for the header
        _header = self.pipe.read(4)
        if len(_header) != 4:
            raise errors.RadioError('Radio did not respond')
        _length = _header[3]
        _packet = self.pipe.read(_length)
        _cs = _checksum(_header[1:])
        _cs += _checksum(_packet)
        _cs %= 16
        try:
            _rcs = self.pipe.read(1)[0]
        except (TypeError, IndexError):
            raise errors.RadioError('Radio did not respond')
        if _rcs != _cs:
            LOG.error("_cs =%x", _cs)
            LOG.error("_rcs=%x", _rcs)
        return (_rcs != _cs, _packet)

    @classmethod
    def match_model(cls, filedata, filename):
        return cls._file_ident in filedata[0x400:0x408]

    def _identify(self):
        """
        Offset
          0:10     Model 'KG-UV920Rr'
          11:      Not used (limits)
        """
        self._write_record(CMD_ID)
        time.sleep(0.6)
        _chksum_err, _resp = self._read_record()
        LOG.debug("Got:\n%s" % util.hexprint(_resp))
        if _chksum_err:
            raise Exception("Checksum error")
        if len(_resp) == 0:
            raise Exception("Radio not responding")
        reported_model = _str_decode(_resp[0:10])
        if reported_model != self._model:
            raise Exception("Unable to identify radio (Got %s, Expected)" %
                            reported_model, self._model)

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

    # TODO: This is a dumb, brute force method of downloading the memory.
    # it would be smarter to only load the active areas and none of
    # the padding/unused areas.
    def _download(self):
        """Talk to a Wouxun KG-UV920P-A and do a download"""
        try:
            self._identify()
            return self._do_download(0, 0x6640, 0x40)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Unknown error during download process')
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def _do_download(self, start, end, blocksize):
        # allocate & fill memory
        image = b""
        for i in range(start, end, blocksize):
            req = struct.pack('>HB', i, blocksize)
            self._write_record(CMD_RD, req)
            cs_error, resp = self._read_record()
            if cs_error:
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
        return memmap.MemoryMapBytes(image)

    def _upload(self):
        """Talk to a Wouxun KG-UV920P-A and do a upload"""
        try:
            self._identify()
            self._do_upload(0x0000, 0x6640, 0x40)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        return

    def _do_upload(self, start, end, blocksize):
        ptr = start
        for i in range(start, end, blocksize):
            req = struct.pack('>H', i)
            chunk = self.get_mmap()[ptr:ptr + blocksize]
            self._write_record(CMD_WR, req + chunk)
            LOG.debug(util.hexprint(req + chunk))
            cserr, ack = self._read_record()
            LOG.debug(util.hexprint(ack))
            j = struct.unpack('>H', ack[0:2])[0]
            if cserr or j != ptr:
                print(cserr)
                print(j)
                print(ptr)
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
        rf.valid_bands = [(136000000, 175000000),  # supports 2m
                          (420000000, 520000000)]  # supports 70cm
        rf.valid_characters = CHARSET
        rf.memory_bounds = (1, 999)  # 999 memories
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is a beta version. "
                           "There are no known issues with it, but you should "
                           "proceed with caution.")
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._memobj.memory[mem.number-1]

        if _mem.rxfreq & 0xFF000000 == 0xFF000000:
            mem.empty = True
            return mem
        else:
            mem.empty = False

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
            mem.name = _str_decode(self._memobj.names[number-1].name)
        else:
            mem.name = ''

        _get_tone(_mem, mem)

        mem.skip = "" if bool(_mem.scan_add) else "S"

        if _mem.power == 3:
            mem.power = self.POWER_LEVELS[2]
        else:
            mem.power = self.POWER_LEVELS[_mem.power]

        mem.mode = _mem.isnarrow and "NFM" or "FM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        _scram = _mem.scrambler
        if _mem.scrambler > 8:
            _scram = 0
        rs = RadioSetting("scrambler", "Scrambler",
                          RadioSettingValueList(SCRAMBLER_LIST,
                                                current_index=_scram))
        mem.extra.append(rs)

        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(_mem.compander))
        mem.extra.append(rs)

        rs = RadioSetting("mute_mode", "Mute",
                          RadioSettingValueMap(MUTE_MODE_MAP, _mem.mute_mode))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        number = mem.number

        _mem = self._memobj.memory[number-1]
        _nam = self._memobj.names[number-1]

        if mem.empty:
            _mem.set_raw("\xFF" * (_mem.size() // 8))
            _nam.set_raw(_str_encode(""))
            _mem.rxfreq = 0xFFFFFFFF
            return

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

        _mem.isnarrow = 0b11 * int(mem.mode == "NFM")

        # set the tone
        _set_tone(mem, _mem)

        # set the power
        if mem.power:
            idx = self.POWER_LEVELS.index(mem.power)
            if idx == 2:
                _mem.power = 3
            else:
                _mem.power = idx
        else:
            _mem.power = True

        if len(mem.name) > 0:
            _mem.named = True
            name_encoded = _str_encode(mem.name)
            for i in range(0, 8):
                _nam.name[i] = name_encoded[i]
        else:
            _mem.named = False

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def _get_settings(self):
        _settings = self._memobj.settings
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _fm_preset = self._memobj.fm_preset

        cfg_grp = RadioSettingGroup("cfg_grp", "Configuration")
        ui_grp = RadioSettingGroup("ui_grp", "User Interface")
        vfoa_grp = RadioSettingGroup("vfoa_grp", "VFO A")
        vfob_grp = RadioSettingGroup("vfob_grp", "VFO B")
        scn_grp = RadioSettingGroup("scn_grp", "Scan")
        rpt_grp = RadioSettingGroup("rmt_grp", "Repeater")
        rmt_grp = RadioSettingGroup("rmt_grp", "Remote Control")
        fmp_grp = RadioSettingGroup("fmp_grp", "FM Radio Presets")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")

        group = RadioSettings(cfg_grp, ui_grp, vfoa_grp, vfob_grp, scn_grp,
                              rpt_grp, rmt_grp, fmp_grp, oem_grp)

        #
        # Configuration Settings
        #
        rs = RadioSetting("m_power_set", "Medium Power Level (W)",
                          RadioSettingValueMap(M_POWER_MAP,
                                               _settings.m_power_set))
        cfg_grp.append(rs)
        rs = RadioSetting("roger", "Roger Beep",
                          RadioSettingValueList(ROGER_LIST,
                                                current_index=_settings.roger))
        cfg_grp.append(rs)
        rs = RadioSetting("roger_time", "Roger Tx Duration (ms)",
                          RadioSettingValueList(
                              ROGER_TIMES,
                              current_index=_settings.roger_time))
        cfg_grp.append(rs)
        rs = RadioSetting("roger_int", "Roger Interval (ms)",
                          RadioSettingValueList(
                              ROGER_INTERVALS,
                              current_index=_settings.roger_int))
        cfg_grp.append(rs)
        val = RadioSettingValueString(1, 6,
                                      _roger_decode(_settings.roger_begin),
                                      False, CHARSET_NUMERIC)
        rs = RadioSetting("roger_begin", "Roger Begin", val)
        cfg_grp.append(rs)
        val = RadioSettingValueString(1, 6,
                                      _roger_decode(_settings.roger_end),
                                      False, CHARSET_NUMERIC)
        rs = RadioSetting("roger_end", "Roger End", val)
        cfg_grp.append(rs)
        rs = RadioSetting("tot", "Time-Out Timer (TOT) (Min)",
                          RadioSettingValueMap(TOT_MAP, _settings.tot))
        cfg_grp.append(rs)
        rs = RadioSetting("toa", "Time-Out Alarm (TOA) (Sec)",
                          RadioSettingValueMap(TOA_MAP, _settings.toa))
        cfg_grp.append(rs)
        rs = RadioSetting("ani_sw", "Caller ID Tx",
                          RadioSettingValueBoolean(_settings.ani_sw))
        cfg_grp.append(rs)
        rs = RadioSetting("ptt_id", "Caller ID Tx Mode",
                          RadioSettingValueMap(PTT_ID_MAP, _settings.ptt_id))
        cfg_grp.append(rs)
        rs = RadioSetting("ptt_id_delay", "Caller ID Tx Delay (ms)",
                          RadioSettingValueMap(PTT_ID_DELAY_MAP,
                                               _settings.ptt_id_delay))
        cfg_grp.append(rs)
        rs = RadioSetting("ring", "Ring Time (Sec)",
                          RadioSettingValueMap(RING_MAP, _settings.ring))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_st", "DTMF Sidetone",
                          RadioSettingValueList(
                              DTMF_ST_LIST,
                              current_index=_settings.dtmf_st))
        cfg_grp.append(rs)
        rs = RadioSetting("pri_ch_sw", "Priority Channel Switch",
                          RadioSettingValueBoolean(_settings.pri_ch_sw))
        cfg_grp.append(rs)
        rs = RadioSetting("pri_ch", "Priority Channel",
                          RadioSettingValueInteger(
                              1, 999, _chnum_decode(_settings.pri_ch)))
        cfg_grp.append(rs)
        rs = RadioSetting("apo_time", "Auto Power-Off (Min)",
                          RadioSettingValueList(
                              APO_TIME_LIST,
                              current_index=_settings.apo_time))
        cfg_grp.append(rs)
        rs = RadioSetting("alert", "Alert Pulse (Hz)",
                          RadioSettingValueMap(ALERT_MAP, _settings.alert))
        cfg_grp.append(rs)
        rs = RadioSetting("fan_mode", "Fan Mode",
                          RadioSettingValueList(
                              FAN_MODE_LIST,
                              current_index=_settings.fan_mode))
        cfg_grp.append(rs)
        rs = RadioSetting("low_v", "Low Voltage Shutoff",
                          RadioSettingValueBoolean(_settings.low_v))
        cfg_grp.append(rs)
        rs = RadioSetting("ans", "Noise Reduction",
                          RadioSettingValueList(ANS_LIST,
                                                current_index=_settings.ans))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_time", "DTMF Tx Duration (ms)",
                          RadioSettingValueList(
                              DTMF_TIMES,
                              current_index=_settings.dtmf_time))
        cfg_grp.append(rs)
        rs = RadioSetting("dtmf_interval", "DTMF Interval (ms)",
                          RadioSettingValueList(
                              DTMF_INTERVALS,
                              current_index=_settings.dtmf_interval))
        cfg_grp.append(rs)

        #
        # UI Settings
        #
        rs = RadioSetting("ponmsg.left",
                          "Power On Message Left & \n Single Band Message",
                          RadioSettingValueString(
                              0, 8, _str_decode(self._memobj.ponmsg.left)))
        ui_grp.append(rs)
        rs = RadioSetting("ponmsg.right", "Power On Message Right",
                          RadioSettingValueString(
                              0, 8, _str_decode(self._memobj.ponmsg.right)))
        ui_grp.append(rs)
        rs = RadioSetting("autolock", "Autolock",
                          RadioSettingValueBoolean(_settings.autolock))
        ui_grp.append(rs)
        rs = RadioSetting("speaker", "Speaker Select",
                          RadioSettingValueMap(SPEAKER_MAP, _settings.speaker))
        ui_grp.append(rs)
        rs = RadioSetting("voice", "Voice Guide",
                          RadioSettingValueList(VOICE_LIST,
                                                current_index=_settings.voice))
        ui_grp.append(rs)
        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
        ui_grp.append(rs)
        rs = RadioSetting("active_display", "Active Display",
                          RadioSettingValueList(
                              AB_LIST,
                              current_index=_settings.active_display))
        ui_grp.append(rs)
        rs = RadioSetting("single_display", "Single Display",
                          RadioSettingValueBoolean(_settings.single_display))
        ui_grp.append(rs)
        rs = RadioSetting("tx_led", "TX Backlight",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=_settings.tx_led))
        ui_grp.append(rs)
        rs = RadioSetting("wt_led", "Standby Backlight",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=_settings.wt_led))
        ui_grp.append(rs)
        rs = RadioSetting("rx_led", "Rx Backlight",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=_settings.rx_led))
        ui_grp.append(rs)

        #
        # VFO A Settings
        #
        rs = RadioSetting("workmode_a", "Workmode",
                          RadioSettingValueMap(
                              WORKMODE_MAP, _settings.workmode_a))
        vfoa_grp.append(rs)
        rs = RadioSetting("work_cha", "Channel",
                          RadioSettingValueInteger(
                              1, 999, _chnum_decode(_settings.work_cha)))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.rxfreq", "Rx Frequency",
                          RadioSettingValueInteger(
                              137000000, 470000000,
                              _freq_decode(_vfoa.rxfreq), 2500))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.txoffset", "Tx Offset",
                          RadioSettingValueInteger(
                              0, 470000000,
                              _freq_decode(_vfoa.txoffset), 2500))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.rxtone", "Rx Tone",
                          RadioSettingValueMap(TONE_MAP, _vfoa.rxtone))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.txtone", "Tx Tone",
                          RadioSettingValueMap(TONE_MAP, _vfoa.txtone))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.power", "Power",
                          RadioSettingValueMap(POWER_MAP, _vfoa.power))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.duplex", "Duplex",
                          RadioSettingValueList(DUPLEX_LIST,
                                                current_index=_vfoa.duplex))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.isnarrow", "Mode",
                          RadioSettingValueMap(BANDWIDTH_MAP, _vfoa.isnarrow))
        vfoa_grp.append(rs)
        _vfoa_scram = _vfoa.scrambler
        if _vfoa_scram > 8:
            _vfoa_scram = 0
        rs = RadioSetting("vfoa.scrambler", "Scrambler",
                          RadioSettingValueList(SCRAMBLER_LIST,
                                                current_index=_vfoa_scram))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.compander", "Compander",
                          RadioSettingValueBoolean(_vfoa.compander))
        vfoa_grp.append(rs)
        rs = RadioSetting("vfoa.mute_mode", "Mute",
                          RadioSettingValueMap(MUTE_MODE_MAP,
                                               _vfoa.mute_mode))
        vfoa_grp.append(rs)
        rs = RadioSetting("step_a", "Step (kHz)",
                          RadioSettingValueList(
                              STEP_LIST, current_index=_settings.step_a))
        vfoa_grp.append(rs)
        rs = RadioSetting("squelch_a", "Squelch",
                          RadioSettingValueInteger(
                              0, 9, _settings.squelch_a))
        vfoa_grp.append(rs)
        rs = RadioSetting("bcl_a", "Busy Channel Lock-out",
                          RadioSettingValueBoolean(_settings.bcl_a))
        vfoa_grp.append(rs)

        #
        # VFO B Settings
        #
        rs = RadioSetting("workmode_b", "Workmode",
                          RadioSettingValueMap(
                              WORKMODE_MAP, _settings.workmode_b))
        vfob_grp.append(rs)
        rs = RadioSetting("work_chb", "Channel",
                          RadioSettingValueInteger(
                              1, 999, _chnum_decode(_settings.work_chb)))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.rxfreq", "Rx Frequency",
                          RadioSettingValueInteger(
                              137000000, 470000000,
                              _freq_decode(_vfob.rxfreq), 2500))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.txoffset", "Tx Offset",
                          RadioSettingValueInteger(
                              0, 470000000,
                              _freq_decode(_vfob.txoffset), 2500))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.rxtone", "Rx Tone",
                          RadioSettingValueMap(TONE_MAP, _vfob.rxtone))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.txtone", "Tx Tone",
                          RadioSettingValueMap(TONE_MAP, _vfob.txtone))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.power", "Power",
                          RadioSettingValueMap(POWER_MAP, _vfob.power))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.duplex", "Duplex",
                          RadioSettingValueList(DUPLEX_LIST,
                                                current_index=_vfob.duplex))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.isnarrow", "Mode",
                          RadioSettingValueMap(BANDWIDTH_MAP, _vfob.isnarrow))
        vfob_grp.append(rs)
        _vfob_scram = _vfob.scrambler
        if _vfob_scram > 8:
            _vfob_scram = 0
        rs = RadioSetting("vfob.scrambler", "Scrambler",
                          RadioSettingValueList(SCRAMBLER_LIST,
                                                current_index=_vfob_scram))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.compander", "Compander",
                          RadioSettingValueBoolean(_vfob.compander))
        vfob_grp.append(rs)
        rs = RadioSetting("vfob.mute_mode", "Mute",
                          RadioSettingValueMap(MUTE_MODE_MAP, _vfob.mute_mode))
        vfob_grp.append(rs)
        rs = RadioSetting("step_b", "Step (kHz)",
                          RadioSettingValueList(
                              STEP_LIST, current_index=_settings.step_b))
        vfob_grp.append(rs)
        rs = RadioSetting("squelch_b", "Squelch",
                          RadioSettingValueInteger(
                              0, 9, _settings.squelch_b))
        vfob_grp.append(rs)
        rs = RadioSetting("bcl_b", "Busy Channel Lock-out",
                          RadioSettingValueBoolean(_settings.bcl_b))
        vfob_grp.append(rs)

        #
        # Scan Settings
        #
        rs = RadioSetting("sc_rev", "Scan Resume Mode",
                          RadioSettingValueMap(SC_REV_MAP, _settings.sc_rev))
        scn_grp.append(rs)
        rs = RadioSetting("scan_group", "Scan Group", RadioSettingValueList(
            SCAN_GROUP_LIST, current_index=_settings.scan_group))
        scn_grp.append(rs)
        rs = RadioSetting("grp1_lower", "Group 1 Lower",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp1_lower))
        scn_grp.append(rs)
        rs = RadioSetting("grp1_upper", "Group 1 Upper",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp1_upper))
        scn_grp.append(rs)
        rs = RadioSetting("grp2_lower", "Group 2 Lower",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp2_lower))
        scn_grp.append(rs)
        rs = RadioSetting("grp2_upper", "Group 2 Upper",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp2_upper))
        scn_grp.append(rs)
        rs = RadioSetting("grp3_lower", "Group 3 Lower",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp3_lower))
        scn_grp.append(rs)
        rs = RadioSetting("grp3_upper", "Group 3 Upper",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp3_upper))
        scn_grp.append(rs)
        rs = RadioSetting("grp4_lower", "Group 4 Lower",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp4_lower))
        scn_grp.append(rs)
        rs = RadioSetting("grp4_upper", "Group 4 Upper",
                          RadioSettingValueInteger(1, 999,
                                                   _settings.grp4_upper))
        scn_grp.append(rs)
        rs = RadioSetting("scan_det", "Scan DET",
                          RadioSettingValueBoolean(_settings.scan_det))
        scn_grp.append(rs)

        #
        # Repeater Settings
        #
        rs = RadioSetting("rpt_spk", "Speaker",
                          RadioSettingValueBoolean(_settings.rpt_spk))
        rpt_grp.append(rs)
        rs = RadioSetting("rpt_ptt", "PTT",
                          RadioSettingValueBoolean(_settings.rpt_ptt))
        rpt_grp.append(rs)
        rs = RadioSetting("rpt_mode", "Mode", RadioSettingValueList(
            RPT_MODE_LIST, current_index=_settings.rpt_mode))
        rpt_grp.append(rs)
        rs = RadioSetting("rpt_tone", "Tone",
                          RadioSettingValueBoolean(_settings.rpt_tone))
        rpt_grp.append(rs)

        #
        # Remote Settings
        #
        rs = RadioSetting("rc_sw", "Remote Control",
                          RadioSettingValueBoolean(_settings.rc_sw))
        rmt_grp.append(rs)
        rs = RadioSetting("rc_power", "Remote Control Power",
                          RadioSettingValueBoolean(_settings.rc_power))
        rmt_grp.append(rs)
        val = RadioSettingValueString(3, 6, _ani_decode(_settings.ani),
                                      False, CHARSET_NUMERIC)
        rs = RadioSetting("ani", "Caller ID (ANI)", val)
        rmt_grp.append(rs)
        val = RadioSettingValueString(3, 6, _ani_decode(_settings.ani_mcc),
                                      False, CHARSET_NUMERIC)
        rs = RadioSetting("ani_mcc", "MCC-Edit", val)
        rmt_grp.append(rs)
        val = RadioSettingValueString(3, 6, _ani_decode(_settings.ani_scc),
                                      False, CHARSET_NUMERIC)
        rs = RadioSetting("ani_scc", "SCC-Edit", val)
        rmt_grp.append(rs)
        val = RadioSettingValueString(3, 6, _ani_decode(_settings.ani_ctrl),
                                      False, CHARSET_NUMERIC)
        rs = RadioSetting("ani_ctrl", "Control", val)
        rmt_grp.append(rs)

        #
        # FM Radio Presets Settings
        #
        for i in range(1, 21):
            val = _fm_preset[i-1].freq / 100.0
            rs = RadioSetting(str(i), str(i),
                              RadioSettingValueFloat(65.00, 108.00,
                                                     val, precision=2))
            fmp_grp.append(rs)

        #
        # OEM info
        #
        _str = _str_decode(self._memobj.oem_info.model)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("model", "Model", val)
        oem_grp.append(rs)
        _str = _str_decode(self._memobj.oem_info.date)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("date", "OEM Date", val)
        oem_grp.append(rs)
        _str = _str_decode(self._memobj.oem_info.oem1)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem1", "OEM String 1", val)
        oem_grp.append(rs)
        _str = _str_decode(self._memobj.oem_info.oem2)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("oem2", "OEM String 2", val)
        oem_grp.append(rs)
        _str = _str_decode(self._memobj.oem_info.unknown1)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("unknown1", "Unknown String 1", val)
        oem_grp.append(rs)
        _str = _str_decode(self._memobj.oem_info.unknown2)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("unknown2", "Unknown String 2", val)
        oem_grp.append(rs)
        _str = _str_decode(self._memobj.oem_info.unknown3)
        val = RadioSettingValueString(0, 15, _str)
        val.set_mutable(False)
        rs = RadioSetting("unknown3", "Unknown String 3", val)
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
        for group in settings:
            for element in group:
                name = element.get_name()
                if "." in name:
                    bits = name.split(".")
                    obj = self._memobj
                    for bit in bits[:-1]:
                        if "/" in bit:
                            bit, index = bit.split("/", 1)
                            index = int(index)
                            obj = getattr(obj, bit)[index]
                        else:
                            obj = getattr(obj, bit)
                    setting = bits[-1]
                else:
                    obj = self._memobj.settings
                    setting = element.get_name()

                #
                # Special Configuration Settings
                #
                if group.get_name() == 'cfg_grp':
                    if name == 'roger_begin':
                        value = _roger_encode(element[0].get_value())
                        for i in range(0, 4):
                            obj.roger_begin[i] = ord(value[i])
                        continue
                    elif name == 'roger_end':
                        value = _roger_encode(element[0].get_value())
                        for i in range(0, 4):
                            obj.roger_end[i] = ord(value[i])
                        continue
                    elif name == 'pri_ch':
                        value = _chnum_encode(element[0].get_value())
                        setattr(obj, setting, value)
                        continue

                #
                # Special UI Settings
                #
                if group.get_name() == 'ui_grp':
                    if name == 'ponmsg.left':
                        value = _str_encode(element[0].get_value())
                        for i in range(0, 8):
                            self._memobj.ponmsg.left[i] = value[i]
                        continue
                    elif name == 'ponmsg.right':
                        value = _str_encode(element[0].get_value())
                        for i in range(0, 8):
                            self._memobj.ponmsg.right[i] = value[i]
                        continue

                #
                # Special VFO A Settings
                #
                if (group.get_name() == 'vfoa_grp') or \
                   (group.get_name() == 'vfob_grp'):
                    if (setting == 'rxfreq') or \
                       (setting == 'txoffset'):
                        value = _freq_encode(element[0].get_value())
                        setattr(obj, setting, value)
                        continue
                    elif (setting == 'work_cha') or \
                         (setting == 'work_chb'):
                        value = _chnum_encode(element[0].get_value())
                        setattr(obj, setting, value)
                        continue

                #
                # Special VFO B Settings
                #
                if group.get_name() == 'vfob_grp':
                    pass

                #
                # Special Scan settings
                #
                if group.get_name() == 'scn_grp':
                    pass

                #
                # Special Repeater settings
                #
                if group.get_name() == 'rpt_grp':
                    pass

                #
                # Special Remote settings
                #
                if group.get_name() == 'rmt_grp':
                    if name == 'ani':
                        value = _ani_encode(element[0].get_value())
                        for i in range(0, 3):
                            obj.ani[i] = ord(value[i])
                        continue
                    elif name == 'ani_mcc':
                        value = _ani_encode(element[0].get_value())
                        for i in range(0, 3):
                            obj.ani_mcc[i] = ord(value[i])
                        continue
                    elif name == 'ani_scc':
                        value = _ani_encode(element[0].get_value())
                        for i in range(0, 3):
                            obj.ani_scc[i] = ord(value[i])
                        continue
                    elif name == 'ani_ctrl':
                        value = _ani_encode(element[0].get_value())
                        for i in range(0, 3):
                            obj.ani_ctrl[i] = ord(value[i])
                        continue

                #
                # FM Radio Presets Settings
                #
                if group.get_name() == 'fmp_grp':
                    value = int(element[0].get_value() * 100)
                    self._memobj.fm_preset[int(name)-1].freq = value
                    continue

                #
                # Generic Settings
                #
                if element[0].__class__ is RadioSettingValueList:
                    value = element[0].get_options().index(
                        element[0].get_value())
                    setattr(obj, setting, value)
                elif element[0].__class__ is RadioSettingValueMap:
                    value = element[0].get_mem_val()
                    setattr(obj, setting, value)
                elif element[0].__class__ is RadioSettingValueBoolean:
                    value = element[0].get_value()
                    setattr(obj, setting, value)
                elif element[0].__class__ is RadioSettingValueInteger:
                    value = element[0].get_value()
                    setattr(obj, setting, value)
                else:
                    LOG.debug("Unable to set_setting %s" % name)
