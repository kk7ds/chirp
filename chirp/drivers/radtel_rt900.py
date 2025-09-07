# Copyright 2025 Fred Trimble <chirpdriver@gmail.com>
# CHIRP driver for Ratel RT-900 Series radios
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

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)

from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettingSubGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
    RadioSettingValueMap,
    InvalidValueError
)
from textwrap import dedent
from chirp.drivers import (
    baofeng_uv17Pro,
    mml_jc8810,
    baofeng_common as bfc
)

import struct

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  lbcd rxfreq[4];     // 0-3
  lbcd txfreq[4];     // 4-7
  ul16 rxtone;        // 8-9
  ul16 txtone;        // A-B
  u8 unknown1:4,      // C
     scode:4;         //     Signaling
  u8 unknown2:6,      // D
     pttid:2;         //     PTT-ID
  u8 scramble:6,      //     Scramble
     txpower:2;       //     Power Level  0 = H, 1 = L, 2 = M
  u8 unknown4:1,      // F
     narrow:1,        //     Bandwidth  0 = Wide, 1 = Narrow
     encrypt:2,       //     Encrypt
     bcl:1,           //     BCL
     scan:1,          //     Scan  0 = Skip, 1 = Scan
     am_modulation:1, //     Per chan AM modulation
     learning:1;      //     Learning
  lbcd code[3];       // 0-2 Code
  u8 unknown6;        // 3
  char name[12];      // 4-F 12-character Alpha Tag
} memory[%d];

// vfo settings, 32 bytes
struct vfo {
  u8 freq[8];               // vfo freq
  ul16 rxtone;              // coded RX CTCSS/DTC tone
  ul16 txtone;              // coded TX CTCSS/DTC tone
  u8 unknown0[2];
  u8 unknown1:2,
     sftd:2,                // offset direction, 0 == OFF, 1 == +, 2 == -
     scode:4;               // scode 0-15
  u8 unknown2;
  u8 unknown3:3,
     scramble:3,            // 0b0 == OFF, 0b100 == ON
     txpower:2;             // TX power, 0b0 == HIGH, 0b1 == Middle,
                            //    0b2 == LOW
  u8 unknown5:1,
     widenarr:1,            // Bandwidth, 0b0 == WIDE, 0b1 == NARROW
     voicepri:2,            // Voice privacy encryption, 0b00 == OFF,
                            //   0b01 == ENCRY1, 2 == ENCRY2, 0b11 == ENCRY3
     unknown6:2,
     rxmod:1,               // RX Modulation, 0b0 == FM, 0b1 == AM
     unknown7:1;
  u8 unknown8;
  u8 step;                  // vfo tuning step size index: 0 == 2.5K, ...
                            //   6 == 50K, 7 == 8.33K: 0x8013, 0x8033
  u8 offset[6];             // TX freq offset: 0x814, 0x834
  u8 unknown9[6];
};

#seekto 0x8000; // vfo a & b
struct {
  struct vfo a;
  struct vfo b;
} vfo;

#seekto 0x9000;
struct {
  u8 unused:4,        // 9000
     sql:4;           //      Squelch Level
  u8 unused_9001:6,   // 9001
     save:2;          //      Battery Save
  u8 unused_9002:4,   // 9002
     vox:4;           //      VOX Level
  u8 unused_9003:4,   // 9003
     abr:4;           //      Auto BackLight
  u8 unused_9004:7,   // 9004
     tdr:1;           //      TDR
  u8 unused_9005:5,   // 9005
     tot:3;           //      Time-out Timer
  u8 unused_9006:7,   // 9006
     beep:1;          //      Beep
  u8 unused_9007:7,   // 9007
     voice:1;         //      Voice Prompt
  u8 unused_9008:7,   // 9008
     language:1;      //      Language
  u8 unused_9009:6,   // 9009
     dtmfst:2;        //      DTMF ST
  u8 unused_900a:6,   // 900A
     screv:2;         //      Scan Mode
  u8 unused_900B:4,   // 900B
     pttid:4;         //      PTT-ID
  u8 unused_900c:5,   // 900C
     pttlt:3;         //      PTT Delay
  u8 unused_900d:6,   // 900D
     mdfa:2;          //      Channel_A Display
  u8 unused_900e:6,   // 900E
     mdfb:2;          //      Channel_B Display
  u8 busy_lock;    //      Busy Lock
  u8 unused_9010:4,   // 9010
     autolk:4;        //      Key Auto Lock
  u8 unused_9011:6,   // 9011
     almode:2;        //      Alarm Mode
  u8 unused_9012:7,   // 9012
     alarmsound:1;    //      Alarm Sound
  u8 unused_9013:6,   // 9013
     dualtx:2;        //      Dual TX
  u8 unused_9014:7,   // 9014
     ste:1;           //      Tail Noise Clear
  u8 unused_9015:4,   // 9015
     rpste:4;         //      RPT Noise Clear
  u8 unused_9016:4,   // 9016
     rptrl:4;         //      RPT Noise Delay
  u8 unused_9017:6,   // 9017
     roger:2;         //      Roger
  u8 tx_ab;           //      TX A/B
  u8 unused_9019:7,   // 9019
     fmradio:1;       //      FM Radio
  u8 unused_901a1:3,  // 901A
     vfomrb:1,        //      WorkMode B
     unused_901a2:3,  //
     vfomra:1;        //      WorkMode A
  u8 unused_901b:7,   // 901B
     kblock:1;        //      KB Lock
  u8 unused_901c:7,   // 901C
     ponmsg:1;        //      Power On Msg
  u8 bluetooth;       //      Bluetooth ON/OFF
  u8 unused_901e:6,   // 901E
     tone:2;          //      Pilot
  u8 unknown_901f;    // 901F
  u8 unused_9020:4,   // 9020
     voxd:4;          //      VOX Delay
  u8 unused_9021:4,   // 9021
     menuquit:4;      //      Menu Auto Quit
  u8 unused_9022:7,   // 9022
     tailcode:1;      //      Tail Code (RT-470L)
  u8 unknown_9023;    // 9023
  u8 single_mode ;    // 9024 Single Mode (RT-900 BT)
  u8 unknown_9025;    // 9025
  u8 unknown_9026;    // 9026
  u8 unknown_9027;    // 9027
  u8 unknown_9028;    // 9028
  u8 unused_9029:6,   // 9029
     qtsave:2;        //      QT Save Type
  u8 skey2_sp;        // 902A Skey2 Short
  u8 skey2_lp;        // 902B Skey2 Long
  u8 skey3_sp;        // 902C Skey3 Short
  u8 skey3_lp;        // 902D Skey3 Long
  u8 topkey_sp;       // 902E Top Key (RT-470L)
  u8 unused_902f:6,   // 902F
     rxendtail:2;     //      RX END TAIL (RT-470)
  u8 am_mode ;        // 9030 AM Mode (RT-900)
  u8 noise_reduction; // 9031 NOISE REDUCTION
  u8 unknown_9032;    // 9032
  u8 unknown_9033;    // 9033
  u8 unknown_9034;    // 9034
  u8 unknown_9035;    // 9035
  u8 unknown_9036;    // 9036
  u8 unknown_9037;    // 9037
  u8 unknown_9038;    // 9038
  u8 unknown_9039;    // 9039
  u8 unknown_903a;    // 903a
  u8 unknown_903b;    // 903b
  u8 dis_s_table;     // 903b DIS S TABLE (A36plus 8w)
} settings;

#seekto 0xA006;
struct {
  u8 unknown_A006;    // A006
  u8 unused_a007:5,   // A007
     dtmfon:3;        //      DTMF Speed (on time)
  u8 unused_a008:5,   // A008
     dtmfoff:3;       //      DTMF Speed (off time)
} dtmf;

#seekto 0xA020;
struct {
  u8 code[5];         //      5-character DTMF Encoder Groups
  u8 unused[11];
} pttid[15];

#seekto 0xD000; // radio operationg mode
struct {
  u8 radio_mode;
} opmode;

"""

CMD_ACK = b"\x06"
DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
DTMF_CHARS = "0123456789 *#ABCD"

TXPOWER_HIGH = 0x00
TXPOWER_MID = 0x01
TXPOWER_LOW = 0x02

ABR_LIST = ["On", "5 seconds", "10 seconds", "15 seconds", "20 seconds",
            "30 seconds", "1 minute", "2 minutes", "3 minutes"]
ALMODE_LIST = ["Site", "Tone", "Code"]
AUTOLK_LIST = ["Off"] + ABR_LIST[1:4]
DTMFSPEED_LIST = ["50 ms", "100 ms", "200 ms", "300 ms", "500 ms"]
DTMFST_LIST = ["Off", "KeyBoard Side Tone", "ANI Side Tone", "KB ST + ANI ST"]
DUALTX_LIST = ["Off", "A", "B"]
LANGUAGE_LIST = ["English", "Chinese"]
MDF_LIST = ["Name", "Frequency", "Channel"]
MENUQUIT_LIST = ["%s seconds" % x for x in range(5, 55, 5)] + ["60 seconds"]
OFF1TO9_LIST = ["Off"] + ["%s" % x for x in range(1, 10)]
PONMSG_LIST = ["Logo", "Voltage"]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 16)]
PTTLT_LIST = ["None", "100 ms"] + \
             ["%s ms" % x for x in range(200, 1200, 200)]
QTSAVE_LIST = ["All", "TX", "RX"]
ROGER_LIST = ["OFF", "BEEP", "TONE1200"]
RPSTE_LIST = ["Off"] + ["%s ms" % x for x in range(100, 1100, 100)]
SAVE_LIST = ["Off", "Normal Mode", "Super Mode", "Deep Mode"]
SCREV_LIST = ["Time (TO)", "Carrier (CO)", "Search (SE)"]
TONE_LIST = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
TOT_LIST = ["Off", "15S", "30S", "45S", "60S",
            "75S"]
VOXD_LIST = ["%s seconds" % str(x / 10) for x in range(5, 21)]
WORKMODE_LIST = ["VFO Mode", "Channel Mode"]


def get_default_features(self):
    rf = chirp_common.RadioFeatures()
    rf.has_settings = True
    rf.has_bank = False
    rf.has_ctone = True
    rf.has_cross = True
    rf.has_rx_dtcs = True
    rf.has_tuning_step = False
    rf.can_odd_split = True
    rf.has_name = True
    rf.valid_name_length = 12
    rf.valid_characters = self._valid_chars
    rf.valid_skips = ["", "S"]
    rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
    rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                            "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
    rf.valid_power_levels = self.POWER_LEVELS
    rf.valid_duplexes = ["", "-", "+", "split", "off"]
    rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
    rf.valid_dtcs_codes = DTCS
    rf.memory_bounds = (1, self._upper)
    rf.valid_tuning_steps = [2.5, 5., 6.25, 8.33, 10., 12.5, 20., 25., 50.]
    rf.valid_bands = self.VALID_BANDS
    return rf


def _enter_programming_mode(radio):
    serial = radio.pipe
    mml_jc8810._enter_programming_mode(radio)

    try:
        ident = serial.read(8)
        serial.write(radio._cryptsetup)
        ack = serial.read(1)
        if ack != CMD_ACK:
            raise errors.RadioError("Error setting up encryption")
    except Exception:
        raise errors.RadioError("Error communicating with radio")
    if ident not in radio._fingerprint2:
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown secondary"
                                " identification string")


def _exit_programming_mode(radio):
    mml_jc8810._exit_programming_mode(radio)


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"R" + cmd[1:]

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]
    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if block_addr >= 0xf000:
        return block_data
    else:
        return baofeng_uv17Pro._crypt(1, block_data)


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]
    if block_addr < 0xf000:
        data = baofeng_uv17Pro._crypt(1, data)

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except Exception:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("Downloading...")
    _enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        radio.pipe.log('Sending request for %04x' % addr)

    _exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    LOG.debug("Uploading...")
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    # calc actual upload size
    for r in radio._ranges:
        status.max += (r[1] - r[0]) + 1

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            radio.pipe.log('Sending address %04x' % addr)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)

    _exit_programming_mode(radio)


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return True


@directory.register
class RT900BT(chirp_common.CloneModeRadio):
    # ==========
    # Notice to developers:
    # The RT-900 BT support in this driver is currently based upon V1.20P
    # firmware.
    # ==========
    """Radtel RT-900 BT 999"""
    VENDOR = "Radtel"
    MODEL = "RT-900_BT"
    BAUD_RATE = 57600
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x40

    VALID_BANDS = [(18000000, 1000000000)]
    _AIRBAND = (108000000, 136975000)
    _MIL_AIRBAND = (225000000, 399950000)
    _AIRBANDS = [_AIRBAND]  # + [_MIL_AIRBAND]
    # secret Power-ON + PTT + <key-press> combos for some modes:
    #   8: Super
    #   OK: GMRS
    #   EXIT: Factory
    #   2: 144-146/430-440
    _RADIO_MODE_MAP = [
        ("Default", 0xff), ("GMRS", 0xa5),
        ("PMR", 0x66), ("144-146/430-440", 0x55),
        ("Super", 0x56), ("Factory", 0x00),
        ("unknown Mode 2", 0x28)
    ]
    POWER_LEVELS = [
        chirp_common.PowerLevel("High", watts=8.00),
        chirp_common.PowerLevel("Middle", watts=4.00),
        chirp_common.PowerLevel("Low", watts=1.00)
    ]

    SKEY_LIST = ["Radio",
                 "TX Power",
                 "Scan",
                 "Search",
                 "NOAA",
                 "SOS",
                 "Switch AM/FM",
                 "Bluetooth"]
    SKEY_SP_LIST = SKEY_LIST

    _upper = 999  # fw 1.20 expands from 512 to 999 channels_steps,
    _mem_params = (_upper  # number of channels
                   )

    _magic = b"PROGRAMBT80U"
    _fingerprint = [b"\x01\x36\x01\x80\x04\x00\x05\x20",
                    b"\x01\x00\x01\x80\x04\x00\x05\x20",
                    ]  # fw V1.20P for RT-900 BT
    _fingerprint2 = [b"\x02\x00\x02\x60\x01\x03\x30\x04",
                     ]  # fw V1.20P for RT-900 BT
    _cryptsetup = (b'SEND \x01\x01\x00\x00\x00\x00\x00\x00\x00\x00' +
                   b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

    _ranges = [
        (0x0000, 0x7CE0),  # FW V1.20P,
                           # 0x7CE0 equals 999 channels of 32 bytes each
                           # 999 * 32 = 0x7ce0
        (0x8000, 0x8040),
        (0x9000, 0x9040),
        (0xA000, 0xA140),
        (0xD000, 0xD040)  # Radio mode hidden setting
     ]

    _calibration = (0xF000, 0xF250)  # Calibration data
    _memsize = 0xF250  # Including calibration data

    _has_bt_denoise = True
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = True
    _valid_chars = chirp_common.CHARSET_ALPHANUMERIC + \
        "`~!@#$%^&*()-=_+[]\\{}|;':\",./<>?"

    _steps = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0, 8.33]
    # _step_list = ['%#.3g K' % x for x in _steps]
    _step_map = [("2.5 K", 0), ("5.0 K", 1), ("6.25 K", 2), ("8.33 K", 8),
                 ("10.0 K", 3), ("12.5 K", 4), ("20.0 K", 5), ("25.0 K", 6),
                 ("50.0 K", 7)]
    _bandwidth_list = ["Wide (25 KHz)", "Narrow (12.5 KHz)"]
    _offset_list = ["Off", "+", "-"]
    _rx_modulation_list = ["FM", "AM"]
    _scode_list = ["%s" % x for x in range(1, 16)]
    _voicepri_list = ["Off", "ENCRY1", "ENCRY2", "ENCRY3"]
    _scramble_map = [("Off", 0x00), ("On", 0x04)]

    _code_list_ctcss = ["%2.1fHz" % x for x in sorted(chirp_common.TONES)]
    _code_list_ctcss.insert(0, "Off")
    _dcs = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    _code_list_dcsn = ["D%03iN" % x for x in _dcs]
    _code_list_dcsi = ["D%03iI" % x for x in _dcs]
    _code_list = _code_list_ctcss + _code_list_dcsn + _code_list_dcsi

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_settings(self):
        _dtmf = self._memobj.dtmf
        _settings = self._memobj.settings
        _radio_mode = self._memobj.opmode.radio_mode
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Menu 12: TOT
        rs = RadioSettingValueList(TOT_LIST, current_index=_settings.tot)
        rset = RadioSetting("tot", "Time Out Timer", rs)
        basic.append(rset)

        # Menu 00: SQL
        rs = RadioSettingValueInteger(0, 9, _settings.sql)
        rset = RadioSetting("sql", "Squelch Level", rs)
        basic.append(rset)

        # Menu 13: VOX
        rs = RadioSettingValueList(OFF1TO9_LIST, current_index=_settings.vox)
        rset = RadioSetting("vox", "VOX", rs)
        basic.append(rset)

        # Menu 39: VOX DELAY
        rs = RadioSettingValueList(VOXD_LIST, current_index=_settings.voxd)
        rset = RadioSetting("voxd", "VOX Delay", rs)
        basic.append(rset)

        # Menu 15: VOICE
        rs = RadioSettingValueBoolean(_settings.voice)
        rset = RadioSetting("voice", "Voice Prompts", rs)
        basic.append(rset)

        # Menu 17: LANGUAGE
        rs = RadioSettingValueList(LANGUAGE_LIST,
                                   current_index=_settings.language)
        rset = RadioSetting("language", "Language", rs)
        basic.append(rset)

        # Menu 23: ABR
        rs = RadioSettingValueList(ABR_LIST, current_index=_settings.abr)
        rset = RadioSetting("abr", "Auto BackLight", rs)
        basic.append(rset)

        # Menu 19: SC-REV
        rs = RadioSettingValueList(SCREV_LIST, current_index=_settings.screv)
        rset = RadioSetting("screv", "Scan Resume Method", rs)
        basic.append(rset)

        # Menu 10: SAVE
        rs = RadioSettingValueList(SAVE_LIST,
                                   current_index=_settings.save)
        rset = RadioSetting("save", "Battery Save Mode", rs)
        basic.append(rset)

        # Menu 42: MDF-A
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfa)
        rset = RadioSetting("mdfa", "Memory Display Format A", rs)
        basic.append(rset)

        # Menu 43: MDF-B
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfb)
        rset = RadioSetting("mdfb", "Memory Display Format B", rs)
        basic.append(rset)

        # Menu 33: DTMFST (DTMF ST)
        rs = RadioSettingValueList(DTMFST_LIST, current_index=_settings.dtmfst)
        rset = RadioSetting("dtmfst", "DTMF Side Tone", rs)
        basic.append(rset)

        # Menu 37: PTT-LT
        rs = RadioSettingValueList(PTTLT_LIST, current_index=_settings.pttlt)
        rset = RadioSetting("pttlt", "PTT Delay", rs)
        basic.append(rset)

        # Menu 36: TONE
        rs = RadioSettingValueList(TONE_LIST, current_index=_settings.tone)
        rset = RadioSetting("tone", "Tone-burst Frequency", rs)
        basic.append(rset)

        # Mneu 29: POWER ON MSG
        rs = RadioSettingValueList(PONMSG_LIST, current_index=_settings.ponmsg)
        rset = RadioSetting("ponmsg", "Power On Message", rs)
        basic.append(rset)

        # Menu 46: STE
        rs = RadioSettingValueBoolean(_settings.ste)
        rset = RadioSetting("ste", "Squelch Tail Eliminate (HT to HT)", rs)
        basic.append(rset)

        # Menu 40: RP-STE
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rpste)
        rset = RadioSetting("rpste", "Squelch Tail Eliminate (repeater)", rs)
        basic.append(rset)

        # Menu 41: RPT-RL
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rptrl)
        rset = RadioSetting("rptrl", "STE Repeater Delay", rs)
        basic.append(rset)

        # Menu 38: MENU EXIT TIME
        rs = RadioSettingValueList(MENUQUIT_LIST,
                                   current_index=_settings.menuquit)
        rset = RadioSetting("menuquit", "Menu Auto Quit", rs)
        basic.append(rset)

        # Menu 34: AUTOLOCK
        rs = RadioSettingValueList(AUTOLK_LIST, current_index=_settings.autolk)
        rset = RadioSetting("autolk", "Key Auto Lock", rs)
        basic.append(rset)

        # Menu 28: CDCSS SAVE MODE
        rs = RadioSettingValueList(QTSAVE_LIST, current_index=_settings.qtsave)
        rset = RadioSetting("qtsave", "QT Save Type", rs)
        basic.append(rset)

        # Menu 47: AL-MODE
        rs = RadioSettingValueList(ALMODE_LIST, current_index=_settings.almode)
        rset = RadioSetting("almode", "Alarm Mode", rs)
        basic.append(rset)

        # Menu 11: ROGER
        rs = RadioSettingValueList(ROGER_LIST, current_index=_settings.roger)
        rset = RadioSetting("roger", "Roger", rs)
        basic.append(rset)

        # Menu 44: Alarm Mode
        rs = RadioSettingValueBoolean(_settings.alarmsound)
        rset = RadioSetting("alarmsound", "Alarm Sound", rs)
        basic.append(rset)

        # Menu 44: TDR
        rs = RadioSettingValueBoolean(_settings.tdr)
        rset = RadioSetting("tdr", "TDR", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(not _settings.fmradio)
        rset = RadioSetting("fmradio", "FM Radio", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.kblock)
        rset = RadioSetting("kblock", "KB Lock", rs)
        basic.append(rset)

        # Menu 16: BEEP PROMPT
        rs = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("beep", "Beep", rs)
        basic.append(rset)

        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        group.append(dtmf)

        def apply_code(setting, obj, length):
            code = []
            for j in range(0, length):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code

        for i in range(0, 15):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            rs = RadioSettingValueString(0, 5, _code, False)
            rs.set_charset(DTMF_CHARS)
            rset = RadioSetting("pttid/%i.code" % i,
                                "PTT-ID Code %i" % (i + 1), rs)
            rset.set_apply_callback(apply_code, self._memobj.pttid[i], 5)
            dtmf.append(rset)

        rs = RadioSettingValueList(DTMFSPEED_LIST,
                                   current_index=_dtmf.dtmfon)
        rset = RadioSetting("dtmf.dtmfon", "DTMF Speed (on)", rs)
        dtmf.append(rset)

        rs = RadioSettingValueList(DTMFSPEED_LIST,
                                   current_index=_dtmf.dtmfoff)
        rset = RadioSetting("dtmf.dtmfoff", "DTMF Speed (off)", rs)
        dtmf.append(rset)

        rs = RadioSettingValueList(
            PTTID_LIST, current_index=_settings.pttid)
        rset = RadioSetting("pttid", "PTT ID", rs)
        dtmf.append(rset)

        spec = RadioSettingGroup("spec", self.MODEL + " Specific")
        group.append(spec)

        # secret radio mode setting (no menu). PTT + 8 for Super Mode
        rs = RadioSettingValueMap(self._RADIO_MODE_MAP, _radio_mode)
        rset = RadioSetting(
            "opmode.radio_mode", "Radio Operating Mode", rs
        )
        rset.set_warning(
            'This should only be used to change the operating MODE of your '
            'radio if you understand the legalities and implications of '
            'doing so. The change may enable the radio to transmit on '
            'frequencies it is not Type Accepted to do and my be in '
            'violation of FCC and other governing agency regulations.\n\n'
            'It may make your saved image files incompatible with the radio '
            'and non-usable until you change the radio MODE back to the '
            'MODE in effect when the image file was saved. After the '
            'changed image is uploaded, the radio may have to turned OFF '
            'and back ON to have the MODE changes take full effect.\n'
            'DO NOT attempt to edit any settings until uploading to and '
            'downloading from the radio with the new operating MODE.')
        spec.append(rset)

        if self._has_bt_denoise:
            # Menu 46: Noise reduction
            rs = RadioSettingValueBoolean(_settings.noise_reduction)
            rset = RadioSetting("noise_reduction", "Noise reduction", rs)
            spec.append(rset)

            # Menu 47: Bluetooth
            rs = RadioSettingValueBoolean(_settings.bluetooth)
            rset = RadioSetting("bluetooth", "Bluetooth", rs)
            spec.append(rset)

        # Menu 23: PF2 Short
        rs = RadioSettingValueList(self.SKEY_SP_LIST,
                                   current_index=_settings.skey2_sp)
        rset = RadioSetting("skey2_sp", "PF2 Key (Short Press)", rs)
        spec.append(rset)

        # Menu 24: PF2 Long - one byte shift in settings data
        rs = RadioSettingValueList(
            self.SKEY_LIST, current_index=_settings.skey2_lp)
        rset = RadioSetting("skey2_lp", "PF2 Key (Long Press)", rs)
        spec.append(rset)

        # Menu 25: PF3 Short
        rs = RadioSettingValueList(
            self.SKEY_LIST, current_index=_settings.skey3_sp)
        rset = RadioSetting("skey3_sp", "PF3 Key (Short Press)", rs)
        spec.append(rset)

        if self.MODEL not in ["RT-900_BT", "RT-920"]:
            # Menu 50: AM/FM Mode
            if self._has_am_switch:
                rs = RadioSettingValueBoolean(_settings.am_mode)
                rset = RadioSetting("am_mode", "AM Mode", rs)
                spec.append(rset)

        # Menu 7: TDR - Dual freq standby
        rs = RadioSettingValueBoolean(_settings.tdr)
        rset = RadioSetting("tdr", "TDR - Dual frequency standby", rs)
        spec.append(rset)

        if self._has_single_mode:
            # Menu 51: Single Mode - Single fre channel display
            rs = RadioSettingValueBoolean(_settings.single_mode)
            rset = RadioSetting("single_mode", "Single Mode", rs)
            spec.append(rset)

        # VFO A/B settings
        abblock = RadioSettingGroup("abblock", "VFO A/B Channel")
        spec.append(abblock)

        vfo = self._memobj.vfo

        # Menu 21: VFO A/B BCL (Busy lock)
        rs = RadioSettingValueBoolean(_settings.busy_lock)
        rset = RadioSetting("busy_lock", "BCL", rs)
        abblock.append(rset)

        # Menu 30 VFO DTMF code
        rs = RadioSettingValueList(
            PTTID_LIST,
            current_index=_settings.pttid
            # current_index=self._memobj.vfodtmf.code
        )
        rset = RadioSetting("pttid", "DTMF Code", rs)
        abblock.append(rset)

        # Menu 42: TX-A/B
        rs = RadioSettingValueList(
            DUALTX_LIST, current_index=_settings.dualtx)
        rset = RadioSetting("dualtx", "TX-A/B", rs)
        abblock.append(rset)

        # VFO A channel sub menu
        achannel = RadioSettingSubGroup("achannel", "VFO A Channel")
        abblock.append(achannel)

        # Work Mode A
        rs = RadioSettingValueList(WORKMODE_LIST,
                                   current_index=_settings.vfomra)
        rset = RadioSetting("vfomra", "Work Mode", rs)
        achannel.append(rset)

        # VFO A Freq
        def freq_validate(value):
            _radio_mode = self._memobj.opmode.radio_mode
            _vhf_lower = 0.0
            _uhf_upper = 0.0
            if _radio_mode in [0x00, 0x56, 0xff]:  # Factory,Super,Default
                _vhf_lower = 18.0
            else:
                _vhf_lower = 108.0
            _vhf_upper = 299.99875
            _uhf_lower = 300.0
            if _radio_mode in [0x00, 0x56]:  # Factory,Super
                _uhf_upper = 999.99875
            else:
                _uhf_upper = 519.99875

            value = chirp_common.parse_freq(value)
            msg = ("Can't be less than %i.0000")
            if value < _vhf_lower * 1000000:
                raise InvalidValueError(msg % _vhf_lower)
            msg = ("Can't be between %i.9975-%i.0000")
            if _vhf_upper * 1000000 <= value and \
                    value < _uhf_lower * 1000000:
                raise InvalidValueError(msg % (_vhf_upper - 1, _uhf_lower))
            msg = ("Can't be greater than %i.9975")
            if value > _uhf_upper * 1000000:
                raise InvalidValueError(msg % (_uhf_upper - 1))

            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        rs = RadioSettingValueString(
            0, 10, bfc.bcd_decode_freq(vfo.a.freq)
        )
        rs.set_validate_callback(freq_validate)
        rset = RadioSetting("vfo.a.freq", "Frequency", rs)
        rset.set_apply_callback(apply_freq, vfo.a)
        achannel.append(rset)

        # Menu 01: A Step
        rs = RadioSettingValueMap(
            self._step_map, vfo.a.step
        )
        rset = RadioSetting("vfo.a.step", "Tuning Step", rs)
        achannel.append(rset)

        # Menu 02: TX Power
        rs = RadioSettingValueList(
            [str(x) for x in self.POWER_LEVELS],
            current_index=vfo.a.txpower
        )
        rset = RadioSetting("vfo.a.txpower", "TX Power", rs)
        achannel.append(rset)

        # Menu 05: Wide/Narrow Band
        rs = RadioSettingValueList(
            self._bandwidth_list, current_index=vfo.a.widenarr
        )
        rset = RadioSetting("vfo.a.widenarr", "Bandwidth", rs)
        achannel.append(rset)

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

        # Menu 12,13: RX ctcss/dtsc
        rs = RadioSettingValueList(
            self._code_list,
            current_index=self._code_list.index(
                self.decode(vfo.a.rxtone)
            )
        )
        rset = RadioSetting("vfo.a.rxtone", "RX CTCSS/DCS", rs)
        achannel.append(rset)

        # Menu 14,15: TX ctcss/dtsc
        rs = RadioSettingValueList(
            self._code_list,
            current_index=self._code_list.index(
                self.decode(vfo.a.txtone)
            )
        )
        rset = RadioSetting("vfo.a.txtone", "TX CTCSS/DCS", rs)
        achannel.append(rset)

        # Menu 16: Voice Privacy (encryption)
        rs = RadioSettingValueList(
            self._voicepri_list,
            current_index=vfo.a.voicepri
        )
        rset = RadioSetting(
            "vfo.a.voicepri",
            "Voice Privacy - Subtone Encryption",
            rs
        )
        achannel.append(rset)

        # Menu 26: Offset
        rs = RadioSettingValueString(
            0, 10, convert_bytes_to_offset(vfo.a.offset)
        )
        rset = RadioSetting("vfo.a.offset", "Offset (MHz)", rs)
        rset.set_apply_callback(apply_offset, vfo.a)
        achannel.append(rset)

        # Menu 27: Offset direction
        rs = RadioSettingValueList(
            self._offset_list, current_index=vfo.a.sftd
        )
        rset = RadioSetting("vfo.a.sftd", "Offset Direction", rs)
        achannel.append(rset)

        # Menu 29: S-Code DTMF 1-15
        rs = RadioSettingValueList(
            self._scode_list, current_index=vfo.a.scode)
        rset = RadioSetting("vfo.a.scode", "S-CODE", rs)
        achannel.append(rset)

        # Menu 45: Scramble
        rs = RadioSettingValueMap(self._scramble_map, vfo.a.scramble)
        rset = RadioSetting("vfo.a.scramble", "Scramble", rs)
        achannel.append(rset)

        # Menu 50: RX Modulation
        if self._has_am_per_channel:
            rs = RadioSettingValueList(
                self._rx_modulation_list,
                current_index=vfo.a.rxmod
            )
            rset = RadioSetting("vfo.a.rxmod", "RX Modulation", rs)
            achannel.append(rset)

        # VFO B channel sub menu
        bchannel = RadioSettingSubGroup("bchannel", "VFO B Channel")
        abblock.append(bchannel)

        # Work Mode B
        rs = RadioSettingValueList(WORKMODE_LIST,
                                   current_index=_settings.vfomrb)
        rset = RadioSetting("vfomrb", "Work Mode", rs)
        bchannel.append(rset)

        # VFO B Freq
        rs = RadioSettingValueString(
            0, 10, bfc.bcd_decode_freq(vfo.b.freq)
        )
        rs.set_validate_callback(freq_validate)
        rset = RadioSetting("vfo.b.freq", "Frequency", rs)
        rset.set_apply_callback(apply_freq, vfo.b)
        bchannel.append(rset)

        # Menu 01: B Step
        rs = RadioSettingValueMap(
            self._step_map, vfo.b.step
        )
        rset = RadioSetting("vfo.b.step", "Tuning Step", rs)
        bchannel.append(rset)

        # Menu 02: TX Power
        rs = RadioSettingValueList(
            [str(x) for x in self.POWER_LEVELS],
            current_index=vfo.b.txpower
        )
        rset = RadioSetting("vfo.b.txpower", "TX Power", rs)
        bchannel.append(rset)

        # Menu 05: Wide/Narrow Band
        rs = RadioSettingValueList(
            self._bandwidth_list, current_index=vfo.b.widenarr
        )
        rset = RadioSetting("vfo.b.widenarr", "Bandwidth", rs)
        bchannel.append(rset)

        # Menu 12,13: RX ctcss/dtsc
        rs = RadioSettingValueList(
            self._code_list,
            current_index=self._code_list.index(
                self.decode(vfo.b.rxtone)
            )
        )
        rset = RadioSetting("vfo.b.rxtone", "RX CTCSS/DCS", rs)
        bchannel.append(rset)

        # Menu 14,15: TX ctcss/dtsc
        rs = RadioSettingValueList(
            self._code_list,
            current_index=self._code_list.index(
                self.decode(vfo.b.txtone)
            )
        )
        rset = RadioSetting("vfo.b.txtone", "TX CTCSS/DCS", rs)
        bchannel.append(rset)

        # Menu 16: Voice Privacy (encryption)
        rs = RadioSettingValueList(
            self._voicepri_list,
            current_index=vfo.b.voicepri
        )
        rset = RadioSetting("vfo.b.voicepri",
                            "Voice Privacy - Subtone Encryption", rs)
        bchannel.append(rset)

        # Menu 26: Offset
        rs = RadioSettingValueString(
                    0, 10, convert_bytes_to_offset(vfo.b.offset)
        )
        rset = RadioSetting("vfo.b.offset", "Offset (MHz)", rs)
        rset.set_apply_callback(apply_offset, vfo.b)
        bchannel.append(rset)

        # Menu 27: Offset direction
        rs = RadioSettingValueList(
            self._offset_list, current_index=vfo.b.sftd
        )
        rset = RadioSetting("vfo.b.sftd", "Offset Direction", rs)
        bchannel.append(rset)

        # Menu 29: S-Code DTMF 1-15
        rs = RadioSettingValueList(
            self._scode_list, current_index=vfo.b.scode)
        rset = RadioSetting("vfo.b.scode", "S-CODE", rs)
        bchannel.append(rset)

        # Menu 45: Scramble
        rs = RadioSettingValueMap(self._scramble_map, vfo.b.scramble)
        rset = RadioSetting("vfo.b.scramble", "Scramble", rs)
        bchannel.append(rset)

        # Menu 50: RX Modulation
        if self._has_am_per_channel:
            rs = RadioSettingValueList(
                self._rx_modulation_list, current_index=vfo.b.rxmod
            )
            rset = RadioSetting("vfo.b.rxmod", "RX Modulation", rs)
            bchannel.append(rset)

        return group

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a beta version ONLY for the RT-900 BT'
             ' running Firmware V.1.20P.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        rp.pre_download = (dedent("""\
            1. Turn radio off.
            2. Connect cable to mic/spkr connector.
            3. Make sure connector is firmly connected.
            4. Turn radio on (volume may need to be set at 100%).
            5. Ensure that the radio is tuned to channel with no activity.
            6. Click OK to download image from device."""))
        rp.pre_upload = (dedent("""\
            1. Turn radio off.
            2. Connect cable to mic/spkr connector.
            3. Make sure connector is firmly connected.
            4. Turn radio on (volume may need to be set at 100%).
            5. Ensure that the radio is tuned to channel with no activity.
            6. Click OK to upload image to device."""))
        return rp

    # decode radio stored tone code into human readable form
    def decode(self, code):
        if code in [0, 0xffff]:
            tone = 'Off'  # Off
        elif code >= 0x0258:  # CTCSS
            tone = "%2.1fHz" % (int(code) / 10.0)
        elif code <= 0x0258:  # DCS
            if code > 0x69:  # inverse
                index = code - 0x6a
                dtcs_pol = 'I'
            else:  # normal
                index = code - 1
                dtcs_pol = 'N'
            tone = 'D' + "%03i" % (self._dcs[index]) + dtcs_pol
        else:
            msg = "Invalid tone code from radio: %s" % hex(code)
            LOG.exception(msg)
            raise InvalidValueError(msg)

        return tone

    # encode human readable tone text into radio storable tone code
    def encode(self, tone):
        if tone == "Off":
            code = 0
        elif tone.endswith('Hz'):  # CTCSS
            code = int(float(tone[0:tone.index('Hz')]) * 10)
        elif tone.startswith('D'):  # DCS
            index = self._dcs.index(int(tone[1:4]))
            if tone.endswith('I'):  # inverse
                code = index + 0x6a
            elif tone.endswith('N'):  # normal
                code = index + 1
            else:
                msg = "Unknown CTCSS/DTC tone: %s" % tone
                LOG.exception(msg)
                raise InvalidValueError(msg)
        return code

    def get_features(self):
        rf = get_default_features(self)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_modes = ["FM", "NFM", "AM", "NAM"]  # 25kHz, 12.5kHz, AM, NAM
        rf.valid_tuning_steps = self._steps
        return rf

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number - 1]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if _mem.get_raw()[:1] == b"\xFF":
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        if mem.freq == 0:
            mem.empty = True
        # tx freq can be blank
        if _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if _split(self.get_features(), mem.freq, int(
                          _mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        for char in _mem.name:
            if str(char) == "\xFF":
                char = " "  # may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip().replace('\x00', '')

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = DTCS[index]
        else:
            LOG.warning("Bug: txtone is %04x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.rx_dtcs = DTCS[index]
        else:
            LOG.warning("Bug: rxtone is %04x" % _mem.rxtone)

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

        if not _mem.scan:
            mem.skip = "S"

        _levels = self.POWER_LEVELS

        if _mem.txpower == TXPOWER_HIGH:
            mem.power = _levels[0]
        elif _mem.txpower == TXPOWER_MID:
            mem.power = _levels[1]
        elif _mem.txpower == TXPOWER_LOW:
            mem.power = _levels[2]
        else:
            LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                      (mem.name, _mem.txpower))

        mem.mode = _mem.narrow and "NFM" or "FM"

        if chirp_common.in_range(
            mem.freq, self._AIRBANDS
        ) or _mem.am_modulation == 0b1:
            mem.mode = _mem.narrow and "NAM" or 'AM'

        mem.extra = RadioSettingGroup("Extra", "extra")

        # Encryption
        rs = RadioSettingValueList(
            self._voicepri_list,
            current_index=_mem.encrypt
        )
        rset = RadioSetting("encrypt", "Voice Privacy", rs)
        mem.extra.append(rset)

        # Scramble
        rs = RadioSettingValueMap(self._scramble_map, _mem.scramble)
        rset = RadioSetting("scramble", "Scramble", rs)
        mem.extra.append(rset)

        # BCL (Busy Channel Lockout)
        rs = RadioSettingValueBoolean(_mem.bcl)
        rset = RadioSetting("bcl", "BCL", rs)
        mem.extra.append(rset)

        # PTT-ID
        rs = RadioSettingValueList(PTTID_LIST, current_index=_mem.pttid)
        rset = RadioSetting("pttid", "PTT ID", rs)
        mem.extra.append(rset)

        # Signal (DTMF Encoder Group #)
        rs = RadioSettingValueList(PTTIDCODE_LIST, current_index=_mem.scode)
        rset = RadioSetting("scode", "PTT ID Code", rs)
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xff" * 32)
            return

        _mem.set_raw("\x00" * 16 + "\xFF" * 16)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _mem.name[i] = mem.name[i]
            except IndexError:
                _mem.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = DTCS.index(mem.dtcs) + 1
            _mem.rxtone = DTCS.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = DTCS.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = DTCS.index(mem.rx_dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.narrow = mem.mode == "NFM"

        _levels = self.POWER_LEVELS
        if mem.power is None:
            _mem.txpower = TXPOWER_HIGH
        elif mem.power == _levels[0]:
            _mem.txpower = TXPOWER_HIGH
        elif mem.power == _levels[1]:
            _mem.txpower = TXPOWER_MID
        elif mem.power == _levels[2]:
            _mem.txpower = TXPOWER_LOW
        else:
            LOG.error('%s: set_mem: unhandled power level: %s' %
                      (mem.name, mem.power))

        match mem.mode:
            case 'AM':  # radio allows AM per channel
                _mem.am_modulation = 0b1
                _mem.narrow = 0b0
            case "NAM":  # radio allows narrow AM per channel
                _mem.am_modulation = 0b1
                _mem.narrow = 0b1
            case 'FM':
                _mem.am_modulation = 0b0
                _mem.narrow = 0b0
            case 'NFM':
                _mem.am_modulation = 0b0
                _mem.narrow = 0b1

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def validate_memory(self, mem):
        msgs = []
        in_range = chirp_common.in_range
        AM_mode = 'AM' in mem.mode

        if in_range(mem.freq, self._AIRBANDS) and not AM_mode:
            msgs.append(chirp_common.ValidationMessage(
                _('Frequency in this range requires AM mode')))
        return msgs + super().validate_memory(mem)

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
                    elif setting == "fmradio":
                        setattr(obj, setting, not int(element.value))
                    elif setting in ["rxtone", "txtone"]:
                        setattr(
                            obj, setting,
                            self.encode(
                                self._code_list[int(element.value)]
                            )
                        )
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name(), e)
                    raise

    def process_mmap(self):
        mem_format = MEM_FORMAT % self._mem_params
        self._memobj = bitwise.parse(mem_format, self._mmap)


@directory.register
class RT900(RT900BT):
    # ==========
    # Notice to developers:
    # The RT-900 support in this driver is currently based upon stock
    # factory firmware.
    # ==========

    """Radtel RT-900 (without Bluetooth)"""
    VENDOR = "Radtel"
    MODEL = "RT-900"

    _has_bt_denoise = False
    _has_am_per_channel = False
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = False

    _upper = 512  # fw 1.04P expands from 256 to 512 channels

    SKEY_LIST = ["FM Radio",
                 "TX Power Level",
                 "Scan",
                 "Search",
                 "NOAA Weather",
                 "SOS",
                 "Flashlight"  # Not used in BT model
                 ]
    SKEY_SP_LIST = SKEY_LIST

    def get_features(self):
        rf = super().get_features()
        # So far no firmware update to test new range availability yet
        # rf.valid_bands = [(18000000, 1000000000)]
        return rf

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the RT-900\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp


@directory.register
class RT910BT(RT900BT):
    # ==========
    # Notice to developers:
    # The RT-910 BT support in this driver is currently based upon Vx.yyP
    # firmware with 15 banks/zones of 64 channels steps.
    # ==========
    """Radtel RT-910_BT 960"""
    VENDOR = "Radtel"
    MODEL = "RT-910_BT"

    SKEY_LIST = ["Radio",
                 "TX Power",
                 "Scan",
                 "Search",
                 "NOAA",
                 "SOS",
                 "Spectrum"]
    SKEY_SP_LIST = SKEY_LIST + ["PTTB"]

    _upper = 960  # fw V0.24P supports 960 channels

    _mem_params = (_upper,  # number of channels
                   )
    _ranges = [
        (0x0000, 0x7800),  # 15 zones of 64 frequencies,
                           # equals 960 channels of 32 bytes each
                           # 15 * 64 * 32 = 0x7800
        (0x8000, 0x8040),
        (0x9000, 0x9040),
        (0xA000, 0xA140),
        (0xD000, 0xD040)  # Radio mode hidden setting
    ]

    _has_bt_denoise = True
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = False

    def get_bank_model(self):
        return chirp_common.StaticBankModel(self, banks=15)

    def get_features(self):
        rf = super().get_features()
        rf.has_bank = True  # Firmware Vx.yyP supports 15
        #                     "static zones" of 64 frequencies
        rf.valid_tuning_steps = self._steps
        return rf

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the RT-910 BT'
             ' running Firmware V0x.yy\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp


@directory.register
class RT910(RT910BT):
    # ==========
    # Notice to developers:
    # The RT-910 support in this driver is currently based upon V0.09P
    # firmware with 15 banks/zones of 64 channels steps.
    # ==========
    """Radtel RT-910 512 (without Bluetooth)"""
    VENDOR = "Radtel"
    MODEL = "RT-910"

    _upper = 512  # fw V0.09P supports 512 channels

    _mem_params = (_upper,  # number of channels
                   )
    _ranges = [
        (0x0000, 0x4000),  # 8 zones of 64 frequencies,
                           # equals 512 channels of 32 bytes each
                           # 8 * 64 * 32 = 0x4000
        (0x8000, 0x8040),
        (0x9000, 0x9040),
        (0xA000, 0xA140),
        (0xD000, 0xD040)  # Radio mode hidden setting
    ]

    _has_bt_denoise = False
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = False

    def get_bank_model(self):
        return chirp_common.StaticBankModel(self, banks=8)

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the RT-910'
             ' Non Bluetooth running Firmware V0.09\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp


@directory.register
class RT920(RT900BT):
    # ==========
    # Notice to developers:
    # The RT-920 support in this driver is currently based upon V0.14P
    # firmware with 15 banks/zones of 64 channels steps.
    # Also known to work on the SHJ H28Y Pro V0.07 firmware
    # ==========
    """Radtel RT-920"""
    VENDOR = "Radtel"
    MODEL = "RT-920"

    # _magic = b"PROGRAMBT80U"  # RT-900
    _magic = b"PROGRAMBT11U"  # RT-920
    #  step of 1.25 to allow UK CB Freqs
    _steps = [1.25, 2.5, 5.0, 6.25, 8.33, 10.0, 12.5, 20.0, 25.0, 50.0]

    SKEY_LIST = ["Radio",
                 "TX Power",
                 "Scan",
                 "Search",
                 "NOAA",
                 "SOS",
                 "Spectrum"]
    SKEY_SP_LIST = SKEY_LIST + ["PTTB"]

    _upper = 960  # fw V0.24P supports 960 channels
    _mem_params = (_upper,  # number of channels
                   )
    _ranges = [
        (0x0000, 0x7800),  # 15 zones of 64 frequencies,
                           # equals 960 channels of 32 bytes each
                           # 15 * 64 * 32 = 0x7800
        (0x8000, 0x8040),
        (0x9000, 0x9040),
        (0xA000, 0xA140),
        (0xD000, 0xD040)  # Radio mode hidden setting
    ]

    _has_bt_denoise = True
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = False

    def get_bank_model(self):
        return chirp_common.StaticBankModel(self, banks=15)

    def get_features(self):
        rf = super().get_features()
        rf.has_bank = True  # Firmware V0.14P supports 15
        #                     "static zones" of 64 frequencies
        rf.valid_tuning_steps = self._steps
        return rf

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the RT-920'
             ' running Firmware V0.14P\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp
