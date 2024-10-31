# Copyright 2023:
# * Sander van der Wel, <svdwel@icloud.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging

from chirp.drivers import baofeng_common as bfc
from chirp import chirp_common, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, \
    RadioSettings, RadioSettingGroup
import struct
from chirp import errors, util

LOG = logging.getLogger(__name__)

# Baofeng UV-17L magic string
MSTRING_UV17L = b"PROGRAMBFNORMALU"
MSTRING_UV17PROGPS = b"PROGRAMCOLORPROU"
# Baofeng GM-5RH magic string
MSTRING_GM5RH = b"PROGRAMBFGMRS05U"
# BTECH BF-F8HP Pro magic string
MSTRING_BFF8HPPRO = b"PROGRAMBF5RTECHU"

DTMF_CHARS = "0123456789 *#ABCD"
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
LIST_STEPS = ["2.5", "5.0", "6.25", "10.0", "12.5", "20.0", "25.0", "50.0"]

LIST_AB = ["A", "B"]
LIST_BANDWIDTH = ["Wide", "Narrow"]
LIST_DTMFSPEED = ["%s ms" % x for x in [50, 100, 200, 300, 500]]
LIST_HANGUPTIME = ["%s s" % x for x in [3, 4, 5, 6, 7, 8, 9, 10]]
LIST_SIDE_TONE = ["Off", "Side Key", "ID", "Side + ID"]
LIST_PTTID = ["Off", "BOT", "EOT", "Both"]
LIST_TIMEOUT_ALARM = ["Off"] + ["%s sec" % x for x in range(1, 11)]
LIST_PILOT_TONE = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
LIST_VOICE = ["Off", "English", "Chinese"]
LIST_WORKMODE = ["Frequency", "Channel"]
LIST_SCANMODE = ["Time", "Carrier", "Search"]
LIST_ALARMMODE = ["Local", "Send Tone", "Send Code"]
LIST_QT_SAVEMODE = ["Both", "RX", "TX"]
LIST_RPT_TAIL_CLEAR = ["%s ms" % x for x in range(0, 1100, 100)]
LIST_VOX_DELAY_TIME = ["%s ms" % x for x in range(500, 2100, 100)]
LIST_VOX_LEVEL = ["Off"] + ["%s" % x for x in range(1, 10, 1)]
LIST_VOX_LEVEL_ALT = ["%s" % x for x in range(1, 10, 1)]
LIST_GPS_MODE = ["GPS", "Beidou", "GPS + Beidou"]
LIST_GPS_TIMEZONE = ["%s" % x for x in range(-12, 13, 1)]
LIST_SHIFTS = ["Off", "+", "-"]
CHARSET_GB2312 = chirp_common.CHARSET_ASCII
for x in range(0xB0, 0xD7):
    for y in range(0xA1, 0xFF):
        CHARSET_GB2312 += bytes([x, y]).decode('gb2312')


def model_match(cls, data):
    """Match the opened image to the correct version"""
    return data[cls.MEM_TOTAL:] == bytes(cls.MODEL, 'utf-8')


def _crypt(symbol_index, buffer):
    # Some weird encryption is used. From the table below, we only use "CO 7".
    tblEncrySymbol = [b"BHT ", b"CO 7", b"A ES", b" EIY", b"M PQ",
                      b"XN Y", b"RVB ", b" HQP", b"W RC", b"MS N",
                      b" SAT", b"K DH", b"ZO R", b"C SL", b"6RB ",
                      b" JCG", b"PN V", b"J PK", b"EK L", b"I LZ"]
    tbl_encrypt_symbols = tblEncrySymbol[symbol_index]
    dec_buffer = b""
    index1 = 0
    for index2 in range(len(buffer)):
        bool_encrypt_char = ((tbl_encrypt_symbols[index1] != 32) and
                             (buffer[index2] != 0) and
                             (buffer[index2] != 255) and
                             (buffer[index2] != tbl_encrypt_symbols[index1])
                             and (buffer[index2] !=
                                  (tbl_encrypt_symbols[index1] ^ 255)))
        if (bool_encrypt_char):
            dec_byte = buffer[index2] ^ tbl_encrypt_symbols[index1]
            dec_buffer += struct.pack('>B', dec_byte)
        else:
            dec_buffer += struct.pack('>B', buffer[index2])
        index1 = (index1 + 1) % 4
    return dec_buffer


def _sendmagic(radio, magic, response_len):
    bfc._rawsend(radio, magic)
    return bfc._rawrecv(radio, response_len)


def _do_ident(radio):
    # Flush input buffer
    bfc._clean_buffer(radio)

    # Ident radio
    ack = _sendmagic(radio, radio._magic, len(radio._fingerprint))

    if not ack.startswith(radio._fingerprint):
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond as expected (A)")

    for magic, resplen in radio._magics:
        _sendmagic(radio, magic, resplen)

    return True


def _download(radio):
    """Get the memory map"""

    # Put radio in program mode and identify it
    _do_ident(radio)
    data = b""

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    for i in range(len(radio.MEM_SIZES)):
        MEM_SIZE = radio.MEM_SIZES[i]
        MEM_START = radio.MEM_STARTS[i]
        for addr in range(MEM_START, MEM_START + MEM_SIZE,
                          radio.BLOCK_SIZE):
            frame = radio._make_read_frame(addr, radio.BLOCK_SIZE)
            # DEBUG
            LOG.debug("Frame=" + util.hexprint(frame))

            # Sending the read request
            bfc._rawsend(radio, frame)

            # Now we read data
            d = bfc._rawrecv(radio, radio.BLOCK_SIZE + 4)

            LOG.debug("Response Data= " + util.hexprint(d))
            d = _crypt(radio._encrsym, d[4:])

            # Aggregate the data
            data += d

            # UI Update
            status.cur = len(data) // radio.BLOCK_SIZE
            status.msg = "Cloning from radio..."
            radio.status_fn(status)
    return data


def _upload(radio):
    # Put radio in program mode and identify it
    _do_ident(radio)
    data = b""

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data_addr = 0x00
    radio_mem = radio.get_mmap()
    for i in range(len(radio.MEM_SIZES)):
        MEM_SIZE = radio.MEM_SIZES[i]
        MEM_START = radio.MEM_STARTS[i]
        for addr in range(MEM_START, MEM_START + MEM_SIZE,
                          radio.BLOCK_SIZE):
            data = radio_mem[data_addr:data_addr + radio.BLOCK_SIZE]
            data = _crypt(radio._encrsym, data)
            data_addr += radio.BLOCK_SIZE

            frame = radio._make_frame(b"W", addr, radio.BLOCK_SIZE, data)
            # DEBUG
            LOG.debug("Frame=" + util.hexprint(frame))

            # Sending the read request
            bfc._rawsend(radio, frame)

            # receiving the response
            ack = bfc._rawrecv(radio, 1)
            if ack != b"\x06":
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            # UI Update
            status.cur = data_addr // radio.BLOCK_SIZE
            status.msg = "Cloning to radio..."
            radio.status_fn(status)
    return data


@directory.register
class UV17Pro(bfc.BaofengCommonHT):
    """Baofeng UV-17Pro"""
    VENDOR = "Baofeng"
    MODEL = "UV-17Pro"

    MEM_STARTS = [0x0000, 0x9000, 0xA000, 0xD000]
    MEM_SIZES = [0x8040, 0x0040, 0x02C0, 0x0040]

    MEM_TOTAL = 0x8380
    BLOCK_SIZE = 0x40
    BAUD_RATE = 115200

    download_function = _download
    upload_function = _upload

    _gmrs = False
    _bw_shift = False
    _has_support_for_banknames = False
    _has_workmode_support = True
    _has_savemode = True

    _tri_band = True
    _fileid = []
    _magic = MSTRING_UV17L
    _fingerprint = b"\x06"
    _magics = [(b"\x46", 16),
               (b"\x4d", 15),
               (b"\x53\x45\x4E\x44\x21\x05\x0D\x01\x01\x01\x04\x11\x08\x05" +
                b"\x0D\x0D\x01\x11\x0F\x09\x12\x09\x10\x04\x00", 1)]
    _fw_ver_start = 0x1EF0
    _recv_block_size = 0x40
    _mem_size = MEM_TOTAL
    _ack_block = True
    _has_when_to_send_aniid = True
    _vfoscan = False
    _has_gps = False
    _has_voxsw = False
    _has_pilot_tone = False
    _has_send_id_delay = False
    _has_skey2_short = False
    _scode_offset = 0
    _encrsym = 1
    _has_voice = True
    _mem_positions = (0x8080, 0x80A0, 0x8280)

    MODES = ["NFM", "FM"]
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "!@#$%^&*()+-=[]:\";'<>?,./"
    LENGTH_NAME = 12
    SKIP_VALUES = ["", "S"]
    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    RXTX_CODES = ('Off', )
    LIST_PW_SAVEMODE = ["Off", "On"]
    for code in chirp_common.TONES:
        RXTX_CODES = (RXTX_CODES + (str(code), ))
    for code in DTCS_CODES:
        RXTX_CODES = (RXTX_CODES + ('D' + str(code) + 'N', ))
    for code in DTCS_CODES:
        RXTX_CODES = (RXTX_CODES + ('D' + str(code) + 'I', ))
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low",  watts=1.00)]
    _airband = (108000000, 135999999)
    _vhf_range = (136000000, 174000000)
    _vhf2_range = (200000000, 260000000)
    _uhf_range = (400000000, 520000000)
    _uhf2_range = (350000000, 390000000)

    VALID_BANDS = [_vhf_range, _vhf2_range,
                   _uhf_range]
    PTTID_LIST = LIST_PTTID
    SCODE_LIST = ["%s" % x for x in range(1, 21)]
    SQUELCH_LIST = ["Off"] + list("12345")
    LIST_POWERON_DISPLAY_TYPE = ["LOGO", "BATT voltage"]
    LIST_TIMEOUT = ["Off"] + ["%s sec" % x for x in range(15, 195, 15)]
    LIST_VOICE = ["English", "Chinese"]
    LIST_BACKLIGHT_TIMER = ["Always On"] + ["%s sec"
                                            % x for x in range(5, 25, 5)]
    LIST_MODE = ["Name", "Frequency", "Channel Number"]
    LIST_BEEP = ["Off", "Beep", "Voice", "Both"]
    LIST_MENU_QUIT_TIME = ["%s sec" % x for x in range(5, 55, 5)] + ["60 sec"]
    LIST_ID_DELAY = ["%s ms" % x for x in range(100, 3100, 100)]
    LIST_SEPARATE_CODE = ["A", "B", "C", "D", "*", "#"]
    LIST_GROUP_CALL_CODE = ["Off"] + LIST_SEPARATE_CODE
    LIST_SKEY2_SHORT = ["FM", "Scan", "Search", "Vox"]

    CHANNELS = 1000

    MEM_FORMAT = """
    struct {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      ul16 rxtone;
      ul16 txtone;
      u8 scode;
      u8 pttid;
      u8 lowpower;
      u8 unknown1:1,
         wide:1,
         sqmode:2,
         bcl:1,
         scan:1,
         unknown2:1,
         fhss:1;
      u8 unknown3;
      u8 unknown4;
      u8 unknown5;
      u8 unknown6;
      char name[12];
    } memory[1000];

    struct vfo_entry {
      u8 freq[8];
      ul16 rxtone;
      ul16 txtone;
      u8 unknown0;
      u8 bcl;
      u8 sftd:3,
         scode:5;
      u8 unknown1;
      u8 lowpower;
      u8 unknown2:1,
         wide:1,
         unknown3:5,
         fhss:1;
      u8 unknown4;
      u8 step;
      u8 offset[6];
      u8 unknown5[2];
      u8 sqmode;
      u8 unknown6[3];
      };

    #seekto 0x8000;
    struct {
      struct vfo_entry a;
      struct vfo_entry b;
    } vfo;

    struct {
      u8 squelch;
      u8 savemode;
      u8 vox;
      u8 backlight;
      u8 dualstandby;
      u8 tot;
      u8 beep;
      u8 voicesw;
      u8 voice;
      u8 sidetone;
      u8 scanmode;
      u8 pttid;
      u8 pttdly;
      u8 chadistype;
      u8 chbdistype;
      u8 bcl;
      u8 autolock;
      u8 alarmmode;
      u8 alarmtone;
      u8 unknown1;
      u8 tailclear;
      u8 rpttailclear;
      u8 rpttaildet;
      u8 roger;
      u8 a_or_b_selected; // a=0, b=1
      u8 fmenable;
      u8 chbworkmode:4,
         chaworkmode:4;
      u8 keylock;
      u8 powerondistype;
      u8 tone;
      u8 unknown4[2];
      u8 voxdlytime;
      u8 menuquittime;
      u8 unknown5[2];
      u8 dispani;
      u8 unknown11[3];
      u8 totalarm;
      u8 unknown6[2];
      u8 ctsdcsscantype;
      ul16 vfoscanmin;
      ul16 vfoscanmax;
      u8 gpsw;
      u8 gpsmode;
      u8 unknown7[2];
      u8 key2short;
      u8 unknown8[2];
      u8 rstmenu;
      u8 singlewatch;
      u8 hangup;
      u8 voxsw;
      u8 gpstimezone;
      u8 unknown10;
      u8 inputdtmf;
      u8 gpsunits;
      u8 pontime;
      char stationid[8];
    } settings;

    #seekto 0x%04X;
    struct {
      u8 code[5];
      u8 unknown[1];
      u8 unused1:6,
         aniid:2;
      u8 dtmfon;
      u8 dtmfoff;
      u8 separatecode;
      u8 groupcallcode;
    } ani;

    #seekto 0x%04X;
    struct {
      u8 code[5];
      char name[10];
      u8 unused;
    } pttid[20];

    struct {
      u8 unknown32[32];
      u8 code[16];
    } upcode;

    struct {
      u8 code[16];
    } downcode;

    #seekto 0x%04X;
    struct {
      char name[16];
    } bank_name[10];
    """

    def _make_read_frame(self, addr, length):
        """Pack the info in the header format"""
        frame = self._make_frame(b"\x52", addr, length)
        # Return the data
        return frame

    def _make_frame(self, cmd, addr, length, data=""):
        """Pack the info in the header format"""
        frame = cmd + struct.pack(">i", addr)[2:] + struct.pack("b", length)
        # add the data if set
        if len(data) != 0:
            frame += data
        # return the data
        return frame

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def process_mmap(self):
        """Process the mem map into the mem object"""
        # make lines shorter for style check.
        fmt = self.MEM_FORMAT % self._mem_positions
        self._memobj = bitwise.parse(fmt, self._mmap)

    # DTMF settings
    def apply_code(self, setting, obj, length):
        code = []
        for j in range(0, length):
            try:
                code.append(DTMF_CHARS.index(str(setting.value)[j]))
            except IndexError:
                code.append(0xFF)
        obj.code = code

    def _filterCodeName(self, name):
        fname = b""
        for char in name:
            if ord(str(char)) in [0, 255]:
                break
            fname += int(char).to_bytes(1, 'big')
        return fname.decode('gb2312').strip()

    def apply_codename(self, setting, obj):
        codename = (str(setting.value).encode('gb2312')[:10].ljust(10,
                    b"\xFF"))
        obj.name = codename

    def get_settings_common_dtmf(self, dtmfe, _mem):
        for i in range(0, len(self.SCODE_LIST)):
            # Signal Code
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([
                DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 5, _code, False)
            val.set_charset(DTMF_CHARS)
            pttid = RadioSetting("pttid/%i.code" % i,
                                 "Signal Code %i" % (i + 1), val)
            if self.MODEL == "BF-F8HP-PRO":
                pttid.set_doc("3 characters maximum")
            pttid.set_apply_callback(self.apply_code, self._memobj.pttid[i], 5)
            dtmfe.append(pttid)

            # Signal Code Name
            _nameobj = self._memobj.pttid[i]
            try:
                rs = RadioSetting(
                    "pttid/%i.name" % i,
                    "Signal Code %i Name" % (i + 1),
                    RadioSettingValueString(
                        0, 10, self._filterCodeName(_nameobj.name),
                        False, CHARSET_GB2312))
                rs.set_apply_callback(self.apply_codename, _nameobj)
                dtmfe.append(rs)
            except AttributeError:
                # UV17, et al do not have pttid.name
                pass

        _codeobj = self._memobj.ani.code
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("ani.code", "ANI Code", val)
        if self.MODEL == "BF-F8HP-PRO":
            rs.set_doc("3 characters maximum")
        rs.set_apply_callback(self.apply_code, self._memobj.ani, 5)
        dtmfe.append(rs)

    def get_settings_pro_dtmf(self, dtmfe, _mem):
        if _mem.ani.dtmfon > 0xC3:
            val = 0x03
        else:
            val = _mem.ani.dtmfon
        rs = RadioSetting("ani.dtmfon", "DTMF Speed (on)",
                          RadioSettingValueList(LIST_DTMFSPEED,
                                                current_index=val))
        dtmfe.append(rs)

        if _mem.ani.dtmfoff > 0xC3:
            val = 0x03
        else:
            val = _mem.ani.dtmfoff
        rs = RadioSetting("ani.dtmfoff", "DTMF Speed (off)",
                          RadioSettingValueList(LIST_DTMFSPEED,
                                                current_index=val))
        dtmfe.append(rs)

        if self._has_when_to_send_aniid:
            rs = RadioSetting(
                "ani.aniid", "When to send ANI ID",
                RadioSettingValueList(
                    LIST_PTTID, current_index=_mem.ani.aniid))
            dtmfe.append(rs)

        if _mem.settings.hangup >= len(LIST_HANGUPTIME):
            val = 0
        else:
            val = _mem.settings.hangup
        rs = RadioSetting("settings.hangup", "Hang-up time",
                          RadioSettingValueList(LIST_HANGUPTIME,
                                                current_index=val))
        dtmfe.append(rs)

    def get_settings_common_basic(self, basic, _mem):
        if _mem.settings.squelch >= len(self.SQUELCH_LIST):
            val = 0x00
        else:
            val = _mem.settings.squelch
        rs = RadioSetting("settings.squelch", "Squelch",
                          RadioSettingValueList(
                              self.SQUELCH_LIST, current_index=val))
        basic.append(rs)

        if _mem.settings.tot >= len(self.LIST_TIMEOUT):
            val = 0x03
        else:
            val = _mem.settings.tot
        rs = RadioSetting("settings.tot", "Timeout Timer",
                          RadioSettingValueList(
                              self.LIST_TIMEOUT, current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.dualstandby", "Dual Watch",
                          RadioSettingValueBoolean(_mem.settings.dualstandby))
        basic.append(rs)

        if _mem.settings.powerondistype >= len(self.LIST_POWERON_DISPLAY_TYPE):
            val = 0x00
        else:
            rs = RadioSetting("settings.powerondistype",
                              "Power On Display Type",
                              RadioSettingValueList(
                                  self.LIST_POWERON_DISPLAY_TYPE,
                                  current_index=_mem.settings.powerondistype))
            basic.append(rs)

        if self._has_voice:
            if _mem.settings.voice >= len(self.LIST_VOICE):
                val = 0x01
            else:
                val = _mem.settings.voice
            rs = RadioSetting("settings.voice", "Voice Prompt",
                              RadioSettingValueList(
                                  self.LIST_VOICE, current_index=val))
            basic.append(rs)

        rs = RadioSetting("settings.voicesw", "Enable Voice",
                          RadioSettingValueBoolean(_mem.settings.voicesw))
        basic.append(rs)

        if _mem.settings.backlight >= len(self.LIST_BACKLIGHT_TIMER):
            val = 0x00
        else:
            val = _mem.settings.backlight
        rs = RadioSetting("settings.backlight", "Backlight Timer",
                          RadioSettingValueList(
                              self.LIST_BACKLIGHT_TIMER,
                              current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.autolock", "Key Auto Lock",
                          RadioSettingValueBoolean(_mem.settings.autolock))
        basic.append(rs)

        rs = RadioSetting("settings.beep", "Beep",
                          RadioSettingValueList(
                              self.LIST_BEEP,
                              current_index=_mem.settings.beep))
        basic.append(rs)

        rs = RadioSetting("settings.roger", "Roger",
                          RadioSettingValueBoolean(_mem.settings.roger))
        basic.append(rs)

        rs = RadioSetting("settings.chadistype", "Channel A display type",
                          RadioSettingValueList(
                              self.LIST_MODE,
                              current_index=_mem.settings.chadistype))
        basic.append(rs)

        rs = RadioSetting("settings.chbdistype", "Channel B display type",
                          RadioSettingValueList(
                              self.LIST_MODE,
                              current_index=_mem.settings.chbdistype))
        basic.append(rs)

    def get_settings_pro_basic(self, basic, _mem):

        if _mem.settings.savemode > len(self.LIST_PW_SAVEMODE):
            val = 0x01  # assume values out of range are some form of "On"
        else:
            val = _mem.settings.savemode
        rs = RadioSetting("settings.savemode", "Save Mode",
                          RadioSettingValueList(self.LIST_PW_SAVEMODE,
                                                current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.totalarm", "Timeout Timer Alarm",
                          RadioSettingValueList(
                              LIST_TIMEOUT_ALARM,
                              current_index=_mem.settings.totalarm))
        basic.append(rs)

        if self._has_pilot_tone:
            rs = RadioSetting("settings.tone", "Pilot Tone",
                              RadioSettingValueList(
                                LIST_PILOT_TONE,
                                current_index=_mem.settings.tone))
            basic.append(rs)

        rs = RadioSetting("settings.sidetone", "Side Tone",
                          RadioSettingValueList(
                              LIST_SIDE_TONE,
                              current_index=_mem.settings.sidetone))
        basic.append(rs)

        rs = RadioSetting("settings.tailclear", "Tail Clear",
                          RadioSettingValueBoolean(_mem.settings.tailclear))
        basic.append(rs)

        rs = RadioSetting("settings.scanmode", "Scan Mode",
                          RadioSettingValueList(
                              LIST_SCANMODE,
                              current_index=_mem.settings.scanmode))
        basic.append(rs)

        rs = RadioSetting("settings.alarmmode", "Alarm Mode",
                          RadioSettingValueList(
                              LIST_ALARMMODE,
                              current_index=_mem.settings.alarmmode))
        basic.append(rs)

        rs = RadioSetting("settings.alarmtone", "Sound Alarm",
                          RadioSettingValueBoolean(_mem.settings.alarmtone))
        basic.append(rs)

        rs = RadioSetting("settings.keylock", "Key Lock",
                          RadioSettingValueBoolean(_mem.settings.keylock))
        basic.append(rs)

        rs = RadioSetting("settings.menuquittime", "Menu Quit Timer",
                          RadioSettingValueList(
                              self.LIST_MENU_QUIT_TIME,
                              current_index=_mem.settings.menuquittime))
        basic.append(rs)

        if self._has_send_id_delay:
            rs = RadioSetting("settings.pttdly", "Send ID Delay",
                              RadioSettingValueList(
                                self.LIST_ID_DELAY,
                                current_index=_mem.settings.pttdly))
            basic.append(rs)

        rs = RadioSetting("settings.ctsdcsscantype", "QT Save Mode",
                          RadioSettingValueList(
                              LIST_QT_SAVEMODE,
                              current_index=_mem.settings.ctsdcsscantype))
        basic.append(rs)

        def getKey2shortIndex(value):
            key_to_index = {0x07: 0,
                            0x1C: 1,
                            0x1D: 2,
                            0x2D: 3,
                            0x0A: 4}
            return key_to_index.get(int(value), 0)

        def apply_Key2short(setting, obj):
            val = str(setting.value)
            key_to_index = {'FM': 0x07,
                            'Scan': 0x1C,
                            'Search': 0x1D,
                            'Vox': 0x2D,
                            'TX Power': 0x0A}
            obj.key2short = key_to_index.get(val, 0x07)

        if self._has_skey2_short:
            rs = RadioSetting("settings.key2short", "Skey2 Short",
                              RadioSettingValueList(
                                self.LIST_SKEY2_SHORT,
                                current_index=getKey2shortIndex(
                                        _mem.settings.key2short)))
            rs.set_apply_callback(apply_Key2short, _mem.settings)
            basic.append(rs)

        rs = RadioSetting("settings.chaworkmode", "Channel A work mode",
                          RadioSettingValueList(
                              LIST_WORKMODE,
                              current_index=_mem.settings.chaworkmode))
        basic.append(rs)

        rs = RadioSetting("settings.chbworkmode", "Channel B work mode",
                          RadioSettingValueList(
                              LIST_WORKMODE,
                              current_index=_mem.settings.chbworkmode))
        basic.append(rs)

        rs = RadioSetting("settings.rpttailclear", "Rpt Tail Clear",
                          RadioSettingValueList(
                              LIST_RPT_TAIL_CLEAR,
                              current_index=_mem.settings.rpttailclear))
        basic.append(rs)

        rs = RadioSetting("settings.rpttaildet", "Rpt Tail Delay",
                          RadioSettingValueList(
                              LIST_RPT_TAIL_CLEAR,
                              current_index=_mem.settings.rpttaildet))
        basic.append(rs)

        rs = RadioSetting("settings.rstmenu", "Enable Menu Rst",
                          RadioSettingValueBoolean(_mem.settings.rstmenu))
        basic.append(rs)

        if self._has_voxsw:
            rs = RadioSetting("settings.voxsw", "Vox Switch",
                              RadioSettingValueBoolean(_mem.settings.voxsw))
            basic.append(rs)

            rs = RadioSetting("settings.vox", "Vox Level",
                              RadioSettingValueList(
                                LIST_VOX_LEVEL_ALT,
                                current_index=_mem.settings.vox))
            basic.append(rs)
        else:
            rs = RadioSetting("settings.vox", "Vox Level",
                              RadioSettingValueList(
                                LIST_VOX_LEVEL,
                                current_index=_mem.settings.vox))
            basic.append(rs)

        rs = RadioSetting("settings.voxdlytime", "Vox Delay Time",
                          RadioSettingValueList(
                              LIST_VOX_DELAY_TIME,
                              current_index=_mem.settings.voxdlytime))
        basic.append(rs)

        if self._has_gps:
            rs = RadioSetting("settings.gpsw", "GPS On",
                              RadioSettingValueBoolean(_mem.settings.gpsw))
            basic.append(rs)

            rs = RadioSetting("settings.gpsmode", "GPS Mode",
                              RadioSettingValueList(
                                LIST_GPS_MODE,
                                current_index=_mem.settings.gpsmode))
            basic.append(rs)

            rs = RadioSetting("settings.gpstimezone", "GPS Timezone",
                              RadioSettingValueList(
                                LIST_GPS_TIMEZONE,
                                current_index=_mem.settings.gpstimezone))
            basic.append(rs)

        rs = RadioSetting("settings.fmenable", "Disable FM radio",
                          RadioSettingValueBoolean(_mem.settings.fmenable))
        basic.append(rs)

    def get_settings_common_workmode(self, workmode, _mem):

        vfoA = RadioSettingGroup("vfoA", "VFO A")
        vfoB = RadioSettingGroup("vfoB", "VFO B")

        def my_validate(value):
            value = chirp_common.parse_freq(value)
            for band in self.VALID_BANDS:
                if value >= band[0] and value < band[1]:
                    return chirp_common.format_freq(value)
            msg = ("{0} is not in a valid band.".format(value))
            LOG.debug(msg)
            return chirp_common.format_freq(band[0])  # Default to valid value

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        freqA = RadioSettingValueString(0, 10,
                                        bfc.bcd_decode_freq(_mem.vfo.a.freq))
        freqA.set_validate_callback(my_validate)
        rs = RadioSetting("vfo.a.freq", "Frequency", freqA)
        rs.set_apply_callback(apply_freq, _mem.vfo.a)
        vfoA.append(rs)

        freqB = RadioSettingValueString(0, 10,
                                        bfc.bcd_decode_freq(_mem.vfo.b.freq))
        freqB.set_validate_callback(my_validate)
        rs = RadioSetting("vfo.b.freq", "Frequency", freqB)
        rs.set_apply_callback(apply_freq, _mem.vfo.b)
        vfoB.append(rs)

        if _mem.vfo.a.sftd >= len(LIST_SHIFTS):
            val = 0
        else:
            val = _mem.vfo.a.sftd
        rs = RadioSetting("vfo.a.sftd", "Shift",
                          RadioSettingValueList(
                              LIST_SHIFTS, current_index=val))
        vfoA.append(rs)

        if _mem.vfo.b.sftd >= len(LIST_SHIFTS):
            val = 0
        else:
            val = _mem.vfo.b.sftd
        rs = RadioSetting("vfo.b.sftd", "Shift",
                          RadioSettingValueList(
                              LIST_SHIFTS, current_index=val))
        vfoB.append(rs)

        def convert_bytes_to_offset(bytes):
            real_offset = 0
            for byte in bytes:
                real_offset = (real_offset * 10) + byte
            return chirp_common.format_freq(real_offset * 1000)

        def apply_offset(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 1000
            for i in range(5, -1, -1):
                obj.offset[i] = value % 10
                value /= 10

        offA = RadioSettingValueString(
                0, 10, convert_bytes_to_offset(_mem.vfo.a.offset))
        rs = RadioSetting("vfo.a.offset",
                          "Offset (0.0-999.999)", offA)
        rs.set_apply_callback(apply_offset, _mem.vfo.a)
        vfoA.append(rs)

        offB = RadioSettingValueString(
                0, 10, convert_bytes_to_offset(_mem.vfo.b.offset))
        rs = RadioSetting("vfo.b.offset",
                          "Offset (0.0-999.999)", offB)
        rs.set_apply_callback(apply_offset, _mem.vfo.b)
        vfoB.append(rs)

        POWER_LEVELS = [str(x) for x in self.POWER_LEVELS]
        if _mem.vfo.a.lowpower >= len(POWER_LEVELS):
            val = 0
        else:
            val = _mem.vfo.a.lowpower
        rs = RadioSetting("vfo.a.lowpower", "Power",
                          RadioSettingValueList(POWER_LEVELS,
                                                current_index=val))
        vfoA.append(rs)

        if _mem.vfo.b.lowpower >= len(POWER_LEVELS):
            val = 0
        else:
            val = _mem.vfo.b.lowpower
        rs = RadioSetting("vfo.b.lowpower", "Power",
                          RadioSettingValueList(POWER_LEVELS,
                                                current_index=val))
        vfoB.append(rs)

        if _mem.vfo.a.wide >= len(LIST_BANDWIDTH):
            val = 0
        else:
            val = _mem.vfo.a.wide
        rs = RadioSetting("vfo.a.wide", "Bandwidth",
                          RadioSettingValueList(LIST_BANDWIDTH,
                                                current_index=val))
        vfoA.append(rs)

        if _mem.vfo.b.wide >= len(LIST_BANDWIDTH):
            val = 0
        else:
            val = _mem.vfo.b.wide
        rs = RadioSetting("vfo.b.wide", "Bandwidth",
                          RadioSettingValueList(LIST_BANDWIDTH,
                                                current_index=val))
        vfoB.append(rs)

        if _mem.vfo.a.scode >= len(self.SCODE_LIST):
            val = 0
        else:
            val = _mem.vfo.a.scode
        rs = RadioSetting("vfo.a.scode", "Signal Code",
                          RadioSettingValueList(self.SCODE_LIST,
                                                current_index=val))
        vfoA.append(rs)

        if _mem.vfo.b.scode >= len(self.SCODE_LIST):
            val = 0
        else:
            val = _mem.vfo.b.scode
        rs = RadioSetting("vfo.b.scode", "Signal Code",
                          RadioSettingValueList(self.SCODE_LIST,
                                                current_index=val))
        vfoB.append(rs)

        if _mem.vfo.a.step >= len(STEPS):
            val = 0
        else:
            val = _mem.vfo.a.step
        rs = RadioSetting("vfo.a.step", "Tuning Step",
                          RadioSettingValueList(LIST_STEPS, current_index=val))
        vfoA.append(rs)

        if _mem.vfo.b.step >= len(STEPS):
            val = 0
        else:
            val = _mem.vfo.b.step
        rs = RadioSetting("vfo.b.step", "Tuning Step",
                          RadioSettingValueList(LIST_STEPS, current_index=val))
        vfoB.append(rs)

        workmode.append(vfoA)
        workmode.append(vfoB)

    def get_settings_common_bank(self, bank, _mem):

        def _filterName(name):
            fname = b""
            for char in name:
                if ord(str(char)) == 255:
                    break
                fname += int(char).to_bytes(1, 'big')
            return fname.decode('gb2312').strip()

        def apply_bankname(setting, obj):
            name = str(setting.value).encode('gb2312')[:16].ljust(16, b"\xff")
            obj.name = name

        if self._has_support_for_banknames:
            for i in range(0, 10):
                _nameobj = self._memobj.bank_name[i]
                rs = RadioSetting("bank_name/%i.name" % i,
                                  "Bank name %i" % (i + 1),
                                  RadioSettingValueString(
                                      0, 16, _filterName(_nameobj.name), False,
                                      CHARSET_GB2312))
                if self.MODEL == "BF-F8HP-PRO":
                    rs.set_doc("12 characters maximum (only the first 6 show "
                               "up on the main display)")
                rs.set_apply_callback(apply_bankname, _nameobj)
                bank.append(rs)

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        supported = []

        basic = RadioSettingGroup("basic", "Basic Settings")
        self.get_settings_common_basic(basic, _mem)
        self.get_settings_pro_basic(basic, _mem)
        supported.append(basic)  # add basic menu

        if self._has_workmode_support:
            workmode = RadioSettingGroup("workmode", "Work Mode Settings")
            self.get_settings_common_workmode(workmode, _mem)
            supported.append(workmode)  # add workmode menu if supported

        dtmfe = RadioSettingGroup("dtmfe", "DTMF Encode Settings")
        self.get_settings_common_dtmf(dtmfe, _mem)
        self.get_settings_pro_dtmf(dtmfe, _mem)
        supported.append(dtmfe)  # add dtmfe menu

        if self._has_support_for_banknames:
            bank = RadioSettingGroup("bank", "Bank names")
            self.get_settings_common_bank(bank, _mem)
            supported.append(bank)  # add bank menu if supported

        top = RadioSettings(*tuple(supported))
        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
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
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def sync_in(self):
        """Download from radio"""
        try:
            data = self.download_function()
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = memmap.MemoryMapBytes(data)

        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            self.upload_function()
        except errors.RadioError:
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_bank_model(self):
        return chirp_common.StaticBankModel(self, banks=10)

    def get_features(self):
        """Get the radio's features"""

        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_name_length = self.LENGTH_NAME
        if self._gmrs:
            rf.valid_duplexes = ["", "+", "off"]
        else:
            rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_skips = self.SKIP_VALUES
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (1, self.CHANNELS)
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = STEPS

        return rf

    def validate_memory(self, mem):
        msgs = []
        if 'AM' in self.MODES:
            if chirp_common.in_range(mem.freq,
                                     [self._airband]) and mem.mode != 'AM':
                msgs.append(chirp_common.ValidationWarning(
                    _('Frequency in this range requires AM mode')))
            if not chirp_common.in_range(mem.freq,
                                         [self._airband]) and mem.mode == 'AM':
                msgs.append(chirp_common.ValidationWarning(
                    _('Frequency in this range must not be AM mode')))

        return msgs + super().validate_memory(mem)

    def decode_tone(self, val):
        mode = ""
        pol = "N"
        if val in [0, 0xFFFF]:
            xval = 0
        elif val >= 0x0258:
            mode = "Tone"
            xval = int(val) / 10.0
        elif val <= 0x0258:
            mode = "DTCS"
            if val > 0x69:
                index = val - 0x6A
                pol = "R"
            else:
                index = val - 1
            xval = self.DTCS_CODES[index]
        else:
            LOG.warn("Bug: tone is %04x" % val)
        return mode, xval, pol

    def encode_tone(self, memtone, mode, tone, pol):
        if mode == "Tone":
            memtone.set_value(int(tone * 10))
        elif mode == "TSQL":
            memtone.set_value(int(tone * 10))
        elif mode == "DTCS":
            if pol == 'R':
                memtone.set_value(self.DTCS_CODES.index(tone) + 1 + 0x69)
            else:
                memtone.set_value(self.DTCS_CODES.index(tone) + 1)
        else:
            memtone.set_value(0)

    def split_txfreq(self, _mem, freq):
        if self._is_txinh(_mem):
            # TX freq not set
            duplex = "off"
            offset = 0
        else:
            offset = (int(_mem.txfreq) * 10) - freq
            if offset != 0:
                if bfc._split(self.get_features(), freq, int(
                          _mem.txfreq) * 10):
                    duplex = "split"
                    offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    offset = abs(offset)
                    duplex = "-"
                elif offset > 0:
                    duplex = "+"
            else:
                duplex = ""
                offset = 0
        return offset, duplex

    def get_memory_common(self, _mem, name, mem):
        if _mem.get_raw()[0] == 255:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        # TX freq set
        mem.offset, mem.duplex = self.split_txfreq(_mem, mem.freq)

        txtone = self.decode_tone(_mem.txtone)
        rxtone = self.decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        if not _mem.scan:
            mem.skip = "S"

        levels = self.POWER_LEVELS
        try:
            mem.power = levels[_mem.lowpower]
        except IndexError:
            mem.power = levels[0]

        mem.mode = _mem.wide and self.MODES[0] or self.MODES[1]
        if chirp_common.in_range(mem.freq, [self._airband]):
            print('freq %i means am' % mem.freq)
            mem.mode = "AM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(self.PTTID_LIST,
                                                current_index=_mem.pttid))
        mem.extra.append(rs)

        scode = (_mem.scode - self._scode_offset) % len(self.SCODE_LIST)
        rs = RadioSetting("scode", "S-CODE",
                          RadioSettingValueList(self.SCODE_LIST,
                                                current_index=scode))
        mem.extra.append(rs)

        if self.MODEL == "BF-F8HP-PRO":
            rs = RadioSetting("sqmode", "RX DTMF",
                              RadioSettingValueBoolean(_mem.sqmode))
            mem.extra.append(rs)

            rs = RadioSetting("fhss", "FHSS",
                              RadioSettingValueBoolean(_mem.fhss))
            mem.extra.append(rs)

        mem.name = str(name).replace('\xFF', ' ').replace('\x00', ' ').rstrip()

    def _get_raw_memory(self, number):
        return self._memobj.memory[number - 1]

    def get_raw_memory(self, number):
        return repr(self._get_raw_memory(number))

    def get_memory(self, number):
        _mem = self._get_raw_memory(number)

        mem = chirp_common.Memory()
        mem.number = number

        self.get_memory_common(_mem, _mem.name, mem)

        return mem

    def unsplit_txfreq(self, mem):
        _mem = self._get_raw_memory(mem.number)
        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

    def set_memory_common(self, mem, _mem):
        _mem.rxfreq = mem.freq / 10
        self.unsplit_txfreq(mem)

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.txtone, txmode, txtone, txpol)
        self.encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == self.MODES[0]

        if mem.power:
            _mem.lowpower = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.lowpower = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                if setting.get_name() == "scode":
                    setattr(_mem, setting.get_name(), str(int(setting.value) +
                                                          self._scode_offset))
                else:
                    setattr(_mem, setting.get_name(), setting.value)
        else:
            # there are no extra settings, load defaults
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.scode = self._scode_offset

    def set_memory(self, mem):
        _mem = self._get_raw_memory(mem.number)

        _mem.set_raw(b"\x00"*16 + b"\xff" * 16)

        if mem.empty:
            _mem.set_raw(b"\xff" * 32)
            return

        _namelength = self.get_features().valid_name_length
        _mem.name = mem.name.ljust(_namelength, '\xFF')

        self.set_memory_common(mem, _mem)


@directory.register
class UV25(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "UV-25"


@directory.register
class UV17ProGPS(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "UV-17ProGPS"

    _has_support_for_banknames = True
    _has_workmode_support = True
    _magic = MSTRING_UV17PROGPS
    _magics = [(b"\x46", 16),
               (b"\x4d", 7),
               (b"\x53\x45\x4E\x44\x21\x05\x0D\x01\x01" +
                b"\x01\x04\x11\x08\x05\x0D\x0D\x01\x11\x0F\x09\x12\x09" +
                b"\x10\x04\x00", 1)]
    _has_when_to_send_aniid = False
    _vfoscan = True
    _has_gps = True
    _has_voxsw = True
    _has_pilot_tone = True
    _has_send_id_delay = True
    _has_skey2_short = True
    VALID_BANDS = [UV17Pro._airband, UV17Pro._vhf_range, UV17Pro._vhf2_range,
                   UV17Pro._uhf_range, UV17Pro._uhf2_range]
    MODES = UV17Pro.MODES + ['AM']


@directory.register
class BF5RM(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "5RM"

    VALID_BANDS = [UV17Pro._airband, UV17Pro._vhf_range, UV17Pro._vhf2_range,
                   UV17Pro._uhf_range, UV17Pro._uhf2_range]
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=8.00),
                    chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("Medium", watts=5.00)]
    SCODE_LIST = ["%s" % x for x in range(1, 16)]
    SQUELCH_LIST = ["Off"] + list("123456789")
    LIST_PW_SAVEMODE = ["Off", "1:1", "1:2", "1:4"]
    _has_workmode_support = True
    MODES = UV17Pro.MODES + ['AM']


@directory.register
class BFK5Plus(BF5RM):
    VENDOR = "Baofeng"
    MODEL = "K5-Plus"


@directory.register
class GM5RH(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "GM-5RH"

    VALID_BANDS = [UV17Pro._vhf_range, UV17Pro._vhf2_range, UV17Pro._uhf_range]
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("Medium", watts=3.00)]
    SCODE_LIST = ["%s" % x for x in range(1, 16)]
    LIST_PW_SAVEMODE = ["Off", "1:1", "2:1", "3:1", "4:1"]
    _has_workmode_support = True

    _magic = MSTRING_GM5RH


@directory.register
class UV5GPlus(GM5RH):
    VENDOR = "Radioddity"
    MODEL = "UV-5G Plus"


@directory.register
class UV17RPlus(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "UV-17R-Plus"
    VALID_BANDS = [UV17Pro._airband, UV17Pro._vhf_range, UV17Pro._vhf2_range,
                   UV17Pro._uhf_range, UV17Pro._uhf2_range]
    MODES = UV17Pro.MODES + ['AM']


@directory.register
class F8HPPro(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "BF-F8HP-PRO"

    _magic = MSTRING_BFF8HPPRO
    _magics = [(b"\x46", 16),
               (b"\x4d", 6),
               (b"\x53\x45\x4E\x44\x12\x0D\x0A\x0A\x10\x03\x0D\x02\x11\x0C" +
                b"\x12\x0A\x11\x06\x04\x0E\x02\x09\x0D\x00\x00", 1)]
    _encrsym = 3
    VALID_BANDS = [UV17Pro._airband, UV17Pro._vhf_range, UV17Pro._vhf2_range,
                   UV17Pro._uhf_range, UV17Pro._uhf2_range]
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=8.00),
                    chirp_common.PowerLevel("Low",  watts=1.00),
                    chirp_common.PowerLevel('Mid', watts=3.00)]
    LIST_POWER_ON_TIME = ['3 Seconds', '5 Seconds', '10 Seconds']
    LIST_GPS_UNITS = ['km/h', 'MPH', 'kn']
    LIST_POWERON_DISPLAY_TYPE = ["LOGO", "BATT voltage", "Station ID"]
    LIST_BEEP = ["Off", "On"]
    LIST_MENU_QUIT_TIME = ["10 sec", "20 sec", "30 sec", "60 sec", "Off"]
    LIST_BACKLIGHT_TIMER = ["Always On", "5 sec", "10 sec", "15 sec",
                            "20 sec", "30 sec", "60 sec"]
    LIST_ID_DELAY = ["%s ms" % x for x in range(0, 1600, 100)]
    LIST_SKEY2_SHORT = ["FM", "Scan", "Search", "Vox", "TX Power"]
    MODES = UV17Pro.MODES + ['AM']

    _has_support_for_banknames = True
    _vfoscan = True
    _has_gps = True
    _has_voxsw = True
    _has_pilot_tone = True
    _has_send_id_delay = True
    _has_skey2_short = True
    _has_voice = False
    _has_when_to_send_aniid = False

    MEM_STARTS = [0x0000, 0x9000, 0xA000, 0xD000]
    MEM_SIZES = [0x8040, 0x0080, 0x02C0, 0x00C0]

    MEM_TOTAL = 0x8440
    _mem_positions = (0x80C0, 0x80E0, 0x8380)

    def get_settings_pro_dtmf(self, dtmfe, _mem):
        super().get_settings_pro_dtmf(dtmfe, _mem)

        rs = RadioSetting("ani.separatecode", "Separate Code",
                          RadioSettingValueList(
                            self.LIST_SEPARATE_CODE,
                            self.LIST_SEPARATE_CODE[_mem.ani.separatecode]))
        dtmfe.append(rs)

        rs = RadioSetting("ani.groupcallcode", "Group Call Code",
                          RadioSettingValueList(
                            self.LIST_GROUP_CALL_CODE,
                            self.LIST_GROUP_CALL_CODE[_mem.ani.groupcallcode]))
        dtmfe.append(rs)

        _codeobj = self._memobj.upcode.code
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 16, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("upcode.code", "Up Code", val)
        rs.set_apply_callback(self.apply_code, self._memobj.upcode, 16)
        dtmfe.append(rs)

        _codeobj = self._memobj.downcode.code
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 16, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("downcode.code", "Down Code", val)
        rs.set_apply_callback(self.apply_code, self._memobj.downcode, 16)
        dtmfe.append(rs)

    def get_settings_pro_basic(self, basic, _mem):
        super().get_settings_pro_basic(basic, _mem)

        rs = RadioSetting("settings.dispani", "Display ANI",
                          RadioSettingValueBoolean(_mem.settings.dispani))
        basic.append(rs)

        rs = RadioSetting("settings.pontime", "Power on Time",
                          RadioSettingValueList(
                            self.LIST_POWER_ON_TIME,
                            self.LIST_POWER_ON_TIME[_mem.settings.pontime]))
        basic.append(rs)

        rs = RadioSetting("settings.gpsunits", "GPS Speed Units",
                          RadioSettingValueList(
                            self.LIST_GPS_UNITS,
                            self.LIST_GPS_UNITS[_mem.settings.gpsunits]))
        basic.append(rs)

        rs = RadioSetting("settings.inputdtmf", "Input DTMF",
                          RadioSettingValueBoolean(_mem.settings.inputdtmf))
        basic.append(rs)

        rs = RadioSetting("settings.singlewatch", "Single Watch",
                          RadioSettingValueBoolean(_mem.settings.singlewatch))
        basic.append(rs)

        def _filterStationID(name):
            fname = b""
            for char in name:
                if ord(str(char)) in [0, 255]:
                    break
                fname += int(char).to_bytes(1, 'big')
            return fname.decode('gb2312').strip()

        def apply_stationid(setting, obj):
            stationid = (str(setting.value).encode('gb2312')[:8].ljust(8,
                         b"\xFF"))
            obj.stationid = stationid

        _nameobj = self._memobj.settings
        rs = RadioSetting("settings.stationid",
                          "StationID",
                          RadioSettingValueString(
                              0, 8, _filterStationID(_nameobj.stationid),
                              False, CHARSET_GB2312))
        rs.set_apply_callback(apply_stationid, _nameobj)
        basic.append(rs)


@directory.register
class UV5RH(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "UV-5RH"

    VALID_BANDS = [UV17Pro._airband, UV17Pro._vhf_range, UV17Pro._vhf2_range,
                   UV17Pro._uhf_range, UV17Pro._uhf2_range]
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=10.00),
                    chirp_common.PowerLevel("Low", watts=2.00),
                    chirp_common.PowerLevel("Medium", watts=5.00)]
    SCODE_LIST = ["%s" % x for x in range(1, 16)]
    SQUELCH_LIST = ["Off"] + list("123456789")
    LIST_PW_SAVEMODE = ["Off", "1:1", "1:2", "1:4"]
    MODES = UV17Pro.MODES + ['AM']
    _has_workmode_support = True
