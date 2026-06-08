# Copyright 2025, 2026 Fred Trimble <chirpdriver@gmail.com>
# Derived from prior copyrighted work:
# Copyright 2024 Pavel Moravec, OK2MOP <moravecp.cz@gmail.com>
# Copyright 2023 Jim Unroe <rock.unroe@gmail.com>
#
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
    RadioSettingValueInvertedBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
    RadioSettingValueMap,
    MemSetting,
    InvalidValueError,
)
from textwrap import dedent
from chirp.drivers import (
    baofeng_uv17Pro,
    mml_jc8810,
    baofeng_common as bfc,
)

import struct

LOG = logging.getLogger(__name__)

# FHSS Code is a 24-bit per-channel value. The OEM CPS represents an
# unset code as 0xFFFFFF in raw memory and as a blank field in the UI.
# When a code is set, the OEM also writes 0xA0 into the adjacent flag
# byte; when the code is cleared, that flag byte is restored to 0xFF.
FHSS_CODE_NULL = 0xFFFFFF
FHSS_CODE_FLAG_ACTIVE = 0xA0
FHSS_CODE_FLAG_NULL = 0xFF


def _fhss_code_to_text(raw_code):
    raw = int(raw_code)
    if raw == FHSS_CODE_NULL:
        return ""
    return "%06X" % (raw & 0x7FFFFF)


def _validate_fhss_code(value):
    s = str(value).strip()
    if s == "":
        return value
    try:
        v = int(s, 16)
    except ValueError:
        raise InvalidValueError(
            "FHSS Code must be a hex value (e.g. 1A2B3C) or blank")
    if not (0 <= v <= 0x7FFFFF):
        raise InvalidValueError(
            "FHSS Code must be between 000000 and 7FFFFF")
    return value


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
     learning:1;      //     FHSS Learning
  ul24 code;          // 0-2 FHSS Code (little-endian, 0-0x7FFFFF)
  u8 code_flag;       // 3   0xA0 when Code set, 0xFF when blank
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
  u8 unknown_9025;    // 9025 Always 0x01 on all RT-900 variants
  u8 unknown_9026;    // 9026
  u8 unknown_9027;    // 9027
  u8 zone_or_channel; // 9028 Zone or Channel (RT-920 fw V0.16)
                      //        0: Zone mode, 1: Channel mode
  u8 unused_9029:6,   // 9029
     qtsave:2;        //      QT Save Type
  u8 skey2_sp0;       // 902A Skey2 Short RT-900BT
  u8 skey2_sp1;       // 902B Skey2 Short, Long RT-900BT
  u8 skey2_lp;        // 902C Skey2 Long, Skey3 Short RT-900BT
  u8 skey3_sp;        // 902D Skey3 Short
  u8 topkey_sp;       // 902E Top Key (RT-470L)
  u8 unused_902f:6,   // 902F
     rxendtail:2;     //      RX END TAIL (RT-470)
  u8 am_mode ;        // 9030 AM Mode (RT-900)
  u8 noise_reduction; // 9031 NOISE REDUCTION
  u8 unknown_9032;    // 9032
  u8 unknown_9033;    // 9033
  u8 fm_interrupt;    // 9034
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
  u8 code[6];         //      6-character DTMF PTT-IDs
  u8 unused[10];
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
ALMODE_LIST = ["On Site", "Send Sound", "Send Code"]
AUTOLK_LIST = ["Off"] + ABR_LIST[1:4]
DTMFSPEED_LIST = ["50 ms", "100 ms", "200 ms", "300 ms", "500 ms"]
DTMFST_LIST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
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
        ("unknown Mode 2", 0x28),
    ]
    POWER_LEVELS = [
        chirp_common.PowerLevel("High", watts=8.00),
        chirp_common.PowerLevel("Middle", watts=4.00),
        chirp_common.PowerLevel("Low", watts=1.00),
    ]

    SKEY_LIST = ["Radio",
                 "TX Power",
                 "Scan",
                 "Search",
                 "NOAA",
                 "SOS",
                 "Switch AM/FM",
                 "Bluetooth",]
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
        (0xD000, 0xD040),  # Radio mode hidden setting
     ]

    _calibration = (0xF000, 0xF250)  # Calibration data
    _memsize = 0xF250  # Including calibration data

    _has_bt_denoise = True
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = True
    _has_zone_or_channel = False
    _has_zone_names = False
    _has_sp0 = True  # spkey addresses are shifted -1
    _has_hf = False

    _valid_chars = chirp_common.CHARSET_ALPHANUMERIC + \
        "`~!@#$%^&*()-=_+[]\\{}|;':\",./<>?"

    _steps = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0, 8.33]
    _step_map = [("2.5 K", 0), ("5.0 K", 1), ("6.25 K", 2), ("8.33 K", 8),
                 ("10.0 K", 3), ("12.5 K", 4), ("20.0 K", 5), ("25.0 K", 6),
                 ("50.0 K", 7),]
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
        finally:
            _exit_programming_mode(self)

        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        finally:
            _exit_programming_mode(self)

    def get_settings(self):
        _dtmf = self._memobj.dtmf
        _settings = self._memobj.settings
        _radio_mode = self._memobj.opmode.radio_mode
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Menu 12: TOT
        rs = RadioSettingValueList(TOT_LIST, current_index=_settings.tot)
        rset = MemSetting("settings.tot", "Time Out Timer", rs)
        rset.set_doc("Set the Time Out Timer for transmit (Seconds).")
        basic.append(rset)

        # Menu 00: SQL
        rs = RadioSettingValueInteger(0, 9, _settings.sql)
        rset = MemSetting("settings.sql", "Squelch Level", rs)
        rset.set_doc("Set the receive squelch level. Setting to zero will "
                     "disable the squlech.")
        basic.append(rset)

        # Menu 13: VOX
        rs = RadioSettingValueList(OFF1TO9_LIST, current_index=_settings.vox)
        rset = MemSetting("settings.vox", "VOX", rs)
        rset.set_doc("Set the VOX sensitivity level.")
        basic.append(rset)

        # Menu 39: VOX DELAY
        rs = RadioSettingValueList(VOXD_LIST, current_index=_settings.voxd)
        rset = MemSetting("settings.voxd", "VOX Delay", rs)
        rset.set_doc("Set the VOX delay time (Seconds).")
        basic.append(rset)

        # Menu 15: VOICE
        rs = RadioSettingValueBoolean(_settings.voice)
        rset = MemSetting("settings.voice", "Voice Prompts", rs)
        rset.set_doc("Set the radio voice prompts.")
        basic.append(rset)

        # Menu 17: LANGUAGE
        rs = RadioSettingValueList(LANGUAGE_LIST,
                                   current_index=_settings.language)
        rset = MemSetting("settings.language", "Language", rs)
        rset.set_doc("Set the radio menu and voice promopts language.")
        basic.append(rset)

        # Menu 23: ABR
        rs = RadioSettingValueList(ABR_LIST, current_index=_settings.abr)
        rset = MemSetting("settings.abr", "Auto BackLight", rs)
        rset.set_doc("Set the radio Backlight auto switch off time (Seconds).")
        basic.append(rset)

        # Menu 19: SC-REV
        rs = RadioSettingValueList(SCREV_LIST, current_index=_settings.screv)
        rset = MemSetting("settings.screv", "Scan Resume Method", rs)
        rset.set_doc("Set the Scan Resume method: TO (time scanning), "
                     "CO (carrier detect), SE (search scanning).")
        basic.append(rset)

        # Menu 10: SAVE
        rs = RadioSettingValueList(SAVE_LIST,
                                   current_index=_settings.save)
        rset = MemSetting("settings.save", "Battery Save Mode", rs)
        rset.set_doc("Set the Battery power save mode.")
        basic.append(rset)

        # Menu 42: MDF-A
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfa)
        rset = MemSetting("settings.mdfa", "Memory Display Format A", rs)
        rset.set_doc("Set A band display mode.")
        basic.append(rset)

        # Menu 43: MDF-B
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfb)
        rset = MemSetting("settings.mdfb", "Memory Display Format B", rs)
        rset.set_doc("Set B band display mode.")
        basic.append(rset)

        # Menu 33: DTMFST (DTMF ST)
        rs = RadioSettingValueList(DTMFST_LIST, current_index=_settings.dtmfst)
        rset = MemSetting("settings.dtmfst", "DTMF Side Tone", rs)
        rset.set_doc("Set how DTMF tones are heard when a PTT ID DTMF Code "
                     "is sent.")
        basic.append(rset)

        # Menu 37: PTT-LT
        rs = RadioSettingValueList(PTTLT_LIST, current_index=_settings.pttlt)
        rset = MemSetting("settings.pttlt", "PTT Delay", rs)
        rset.set_doc("Set the PTT delay time.")
        basic.append(rset)

        # Menu 36: TONE
        rs = RadioSettingValueList(TONE_LIST, current_index=_settings.tone)
        rset = MemSetting("settings.tone", "Tone-burst Frequency", rs)
        rset.set_doc("Set the Tone-burst Frequency.")
        basic.append(rset)

        # Mneu 29: POWER ON MSG
        rs = RadioSettingValueList(PONMSG_LIST, current_index=_settings.ponmsg)
        rset = MemSetting("settings.ponmsg", "Power On Message", rs)
        rset.set_doc("Set the Power On Message.")
        basic.append(rset)

        # Menu 46: STE
        rs = RadioSettingValueBoolean(_settings.ste)
        rset = MemSetting("settings.ste",
                          "Squelch Tail Eliminate (HT to HT)", rs)
        rset.set_doc("Set the Squelch Tail Eliminate for HT to HT "
                     "communication.")
        basic.append(rset)

        # Menu 40: RP-STE
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rpste)
        rset = MemSetting("settings.rpste",
                          "Squelch Tail Eliminate (repeater)", rs)
        rset.set_doc("Set the Squelch Tail Eliminate time for repeater "
                     "communication.")
        basic.append(rset)

        # Menu 41: RPT-RL
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rptrl)
        rset = MemSetting("settings.rptrl", "STE Repeater Delay", rs)
        rset.set_doc("Set the delay time for Squelch Tail Eliminate "
                     "when using a repeater.")
        basic.append(rset)

        # Menu 38: MENU EXIT TIME
        rs = RadioSettingValueList(MENUQUIT_LIST,
                                   current_index=_settings.menuquit)
        rset = MemSetting("settings.menuquit", "Menu Auto Quit", rs)
        rset.set_doc("Set the time for the radio to automatically exit the "
                     "menu system.")
        basic.append(rset)

        # Menu 34: AUTOLOCK
        rs = RadioSettingValueList(AUTOLK_LIST, current_index=_settings.autolk)
        rset = MemSetting("settings.autolk", "Key Auto Lock", rs)
        rset.set_doc("Set the time for the radio to automatically lock "
                     "the keypad.")
        basic.append(rset)

        # Menu 28: CTCSS SAVE MODE
        rs = RadioSettingValueList(QTSAVE_LIST, current_index=_settings.qtsave)
        rset = MemSetting("settings.qtsave", "QT Save Type", rs)
        rset.set_doc("Set how the CTCSS/DCS codes are saved to a channel.")
        basic.append(rset)

        # Menu 47: AL-MODE
        rs = RadioSettingValueList(ALMODE_LIST, current_index=_settings.almode)
        rset = MemSetting("settings.almode", "Alarm Mode", rs)
        rset.set_doc("Set how the radio will send an Alarm.")
        basic.append(rset)

        # Menu 11: ROGER
        rs = RadioSettingValueList(ROGER_LIST, current_index=_settings.roger)
        rset = MemSetting("settings.roger", "Roger", rs)
        rset.set_doc("Set the Roger Beep mode for when the PTT is released.")
        basic.append(rset)

        # Menu 44: Alarm ON/OFF
        rs = RadioSettingValueBoolean(_settings.alarmsound)
        rset = MemSetting("settings.alarmsound", "Alarm Sound", rs)
        rset.set_doc("Enable to allow the radio to send an alarm.")
        basic.append(rset)

        if self._has_hf:
            s1 = "FM/AM/SSB Radio"
            s2 = "Allow access to FM/AM/SSB RX channels on radio."
        else:
            s1 = "FM Radio"
            s2 = "Allow access to FM broadcast RX channels on radio."

        rs = RadioSettingValueInvertedBoolean(not _settings.fmradio)
        rset = MemSetting("settings.fmradio", s1, rs)
        rset.set_doc(s2)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.kblock)
        rset = MemSetting("settings.kblock", "KB Lock", rs)
        rset.set_doc("Enable radio keypad locked by default.")
        basic.append(rset)

        # Menu 16: BEEP PROMPT
        rs = RadioSettingValueBoolean(_settings.beep)
        rset = MemSetting("settings.beep", "Beep", rs)
        rset.set_doc("Enable radio keypad Beep when pressing keys.")
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
            rs = RadioSettingValueString(0, 6, _code, False)
            rs.set_charset(DTMF_CHARS)
            rset = RadioSetting("pttid/%i.code" % i,
                                "PTT-ID Code %i" % (i + 1), rs)
            rset.set_apply_callback(apply_code, self._memobj.pttid[i], 6)
            rset.set_doc("Set the PTT-ID % i Code DTMF sequence." % (i + 1))
            dtmf.append(rset)

        rs = RadioSettingValueList(DTMFSPEED_LIST,
                                   current_index=_dtmf.dtmfon)
        rset = MemSetting("dtmf.dtmfon", "DTMF Speed (On)", rs)
        rset.set_doc("Set the duration for how long each DMTF tone is ON.")
        dtmf.append(rset)

        rs = RadioSettingValueList(DTMFSPEED_LIST,
                                   current_index=_dtmf.dtmfoff)
        rset = MemSetting("dtmf.dtmfoff", "DTMF Speed (Off)", rs)
        rset.set_doc("Set the duration for how long the pause is between "
                     "DTMF tones.")
        dtmf.append(rset)

        rs = RadioSettingValueList(
            PTTID_LIST, current_index=_settings.pttid)
        rset = MemSetting("settings.pttid", "PTT ID", rs)
        rset.set_doc("Set when the PTT-ID is to be sent.")
        dtmf.append(rset)

        spec = RadioSettingGroup("spec", self.MODEL + " Specific")
        group.append(spec)

        # secret radio mode setting (no menu). PTT + 8 for Super Mode
        rs = RadioSettingValueMap(self._RADIO_MODE_MAP, _radio_mode)
        rset = MemSetting("opmode.radio_mode", "Radio Operating Mode", rs)
        rset.set_warning(
            'This should only be used to change the operating MODE of your '
            'radio if you understand the legalities and implications of '
            'doing so. The change may enable the radio to transmit on '
            'frequencies it is not Type Accepted to do and may be in '
            'violation of FCC and other governing agency regulations.\n\n'
            'It may make your saved image files incompatible with the radio '
            'and non-usable until you change the radio MODE back to the '
            'MODE in effect when the image file was saved. After the '
            'changed image is uploaded, the radio may have to turned OFF '
            'and back ON to have the MODE changes take full effect.\n'
            'DO NOT attempt to edit any settings until uploading to and '
            'downloading from the radio with the new operating MODE.')
        rset.set_doc("Set the radio's Operating Mode.")
        spec.append(rset)

        if self._has_bt_denoise:
            # Menu 46: Noise reduction
            rs = RadioSettingValueBoolean(_settings.noise_reduction)
            rset = MemSetting("settings.noise_reduction",
                              "Noise reduction", rs)
            rset.set_doc("Set the radio's automatic Noise Reduction feature.")
            spec.append(rset)

            # Menu 47: Bluetooth
            rs = RadioSettingValueBoolean(_settings.bluetooth)
            rset = MemSetting("settings.bluetooth", "Bluetooth", rs)
            rset.set_doc("Enable Bluetooth (BLE). "
                         "Bluetooth can be used to program the radio over a "
                         "BLE connection.")
            spec.append(rset)

        # Menu 23: PF2 Short
        if self._has_sp0:
            skey2_sp = _settings.skey2_sp0
            key = "settings.skey2_sp0"
        else:
            skey2_sp = _settings.skey2_sp1
            key = "settings.skey2_sp1"

        rs = RadioSettingValueList(self.SKEY_SP_LIST,
                                   current_index=skey2_sp)
        rset = MemSetting(key, "PF2 Key (Short Press)", rs)
        rset.set_doc("Set what a Short Press on the PF2 Key will do.")
        spec.append(rset)

        # Menu 24: PF2 Long
        if self._has_sp0:
            skey2_lp = _settings.skey2_sp1
            key = "settings.skey2_sp1"
        else:
            skey2_lp = _settings.skey2_lp
            key = "settings.skey2_lp"

        rs = RadioSettingValueList(
            self.SKEY_LIST, current_index=skey2_lp)
        rset = MemSetting(key, "PF2 Key (Long Press)", rs)
        rset.set_doc("Set what a Long Press on the PF2 Key will do.")
        spec.append(rset)

        # Menu 25: PF3 Short
        if self._has_sp0:
            skey3_sp = _settings.skey2_lp
            key = "settings.skey2_lp"
        else:
            skey3_sp = _settings.skey3_sp
            key = "settings.skey3_sp"

        rs = RadioSettingValueList(
            self.SKEY_LIST, current_index=skey3_sp)
        rset = MemSetting(key, "PF3 Key (Short Press)", rs)
        rset.set_doc("Set what a Short Press on the PF3 Key will do.")
        spec.append(rset)

        if self.MODEL not in ["RT-900_BT", "RT-920"]:
            # Menu 50: AM/FM Mode
            if self._has_am_switch:
                rs = RadioSettingValueBoolean(_settings.am_mode)
                rset = MemSetting("settings.am_mode", "AM Mode", rs)
                rset.set_doc("Enable to set the RX modulation mode to AM.")
                spec.append(rset)

        # Menu 7: TDR - Dual freq standby
        rs = RadioSettingValueBoolean(_settings.tdr)
        rset = MemSetting("settings.tdr", "TDR - Dual frequency standby", rs)
        rset.set_doc("Set Dual Frequency Standby (Dual Watch).")
        spec.append(rset)

        if self._has_single_mode:
            # Menu 51: Single Mode - Single freq channel display
            rs = RadioSettingValueBoolean(_settings.single_mode)
            rset = MemSetting("settings.single_mode", "Single Mode", rs)
            rset.set_doc("Set radio to display a single frequency/channel.")
            spec.append(rset)

        if self.MODEL in ["RT-920"]:
            # Menu 53: FM Interupt
            rs = RadioSettingValueBoolean(_settings.fm_interrupt)
            rset = MemSetting("settings.fm_interrupt", "FM Interrupt", rs)
            rset.set_doc("While using broadcast FM, "
                         "allow incoming RX to interrupt the FM "
                         "broadcast audio.")
            spec.append(rset)

        if self._has_zone_or_channel:
            # Menu 10: Zone or Channel
            rs = RadioSettingValueList(self._zone_or_channel_list,
                                       current_index=_settings.zone_or_channel)
            rset = MemSetting("settings.zone_or_channel",
                              "Zone or Channel", rs)
            rset.set_warning(
                 "Changing this setting requires saving the .IMG file and "
                 "opening it back up to enable/disable the Banks (Zones) "
                 "preview tab.")  # and the Zone Name sub-menu.")
            rset.set_doc(
                "Set Zone Mode (static banks) or Full Channel "
                "(flat) memmory channel mode.")
            spec.append(rset)

        # VFO A/B settings
        abblock = RadioSettingGroup("abblock", "VFO A/B Channel")
        spec.append(abblock)

        vfo = self._memobj.vfo

        # Menu 21: VFO A/B BCL (Busy lock)
        rs = RadioSettingValueBoolean(_settings.busy_lock)
        rset = MemSetting("settings.busy_lock", "BCL", rs)
        rset.set_doc("Set Busy Channel Lockout. When selected, disables PTT "
                     "when the current frequency is busy.")
        abblock.append(rset)

        # Menu 30 VFO DTMF code
        rs = RadioSettingValueList(
            PTTID_LIST,
            current_index=_settings.pttid
        )
        rset = MemSetting("settings.pttid", "DTMF Code", rs)
        rset.set_doc("Set when to send PTT-ID DTMF codes")
        abblock.append(rset)

        # Menu 42: TX-A/B
        rs = RadioSettingValueList(
            DUALTX_LIST, current_index=_settings.dualtx)
        rset = MemSetting("settings.dualtx", "TX-A/B", rs)
        rset.set_doc("Set which Band will be used for TX when PTT is pressed.")
        abblock.append(rset)

        # VFO A channel sub menu
        achannel = RadioSettingSubGroup("achannel", "VFO A Channel")
        abblock.append(achannel)

        # Work Mode A
        rs = RadioSettingValueList(WORKMODE_LIST,
                                   current_index=_settings.vfomra)
        rset = MemSetting("settings.vfomra", "Work Mode", rs)
        rset.set_doc("Set A Band Work Mode.")
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

        rs = RadioSettingValueString(0, 10, bfc.bcd_decode_freq(vfo.a.freq))
        rs.set_validate_callback(freq_validate)
        rset = RadioSetting("vfo.a.freq", "Frequency", rs)
        rset.set_apply_callback(apply_freq, vfo.a)
        rset.set_doc("Set A Band VFO frequency.")
        achannel.append(rset)

        # Menu 01: A Step
        rs = RadioSettingValueMap(self._step_map, vfo.a.step)
        rset = MemSetting("vfo.a.step", "Tuning Step", rs)
        rset.set_doc("Set A Band frequency Tuning Step.")
        achannel.append(rset)

        # Menu 02: TX Power
        rs = RadioSettingValueList([str(x) for x in self.POWER_LEVELS],
                                   current_index=vfo.a.txpower)
        rset = MemSetting("vfo.a.txpower", "TX Power", rs)
        rset.set_doc("Set A Band TX Power.")
        achannel.append(rset)

        # Menu 05: Wide/Narrow Band
        rs = RadioSettingValueList(self._bandwidth_list,
                                   current_index=vfo.a.widenarr)
        rset = MemSetting("vfo.a.widenarr", "Bandwidth", rs)
        rset.set_doc("Set A Band Bandwidth.")
        achannel.append(rset)

        # Menu 12,13: RX ctcss/dtsc
        rs = RadioSettingValueList(self._code_list,
                                   current_index=self._code_list.index
                                   (self.decode(vfo.a.rxtone)))
        rset = RadioSetting("vfo.a.rxtone", "RX CTCSS/DCS", rs)
        rset.set_apply_callback(self.apply_vfo_tone,
                                self._memobj.vfo.a, "rxtone")
        rset.set_doc("Set A Band RX CTCSS or DCS code.")
        achannel.append(rset)

        # Menu 14,15: TX ctcss/dtsc
        rs = RadioSettingValueList(self._code_list,
                                   current_index=self._code_list.index
                                   (self.decode(vfo.a.txtone)))
        rset = RadioSetting("vfo.a.txtone", "TX CTCSS/DCS", rs)
        rset.set_apply_callback(self.apply_vfo_tone,
                                self._memobj.vfo.a, "txtone")
        rset.set_doc("Set A Band TX CTCSS or DCS code.")
        achannel.append(rset)

        # Menu 16: Voice Privacy (encryption)
        rs = RadioSettingValueList(self._voicepri_list,
                                   current_index=vfo.a.voicepri)
        rset = RadioSetting("vfo.a.voicepri",
                            "Voice Privacy - Subtone Encryption", rs)
        rset.set_doc("Set A Band Voice Privacy - subtone voice encryption.")
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

        # Menu 26: Offset
        rs = RadioSettingValueString(0, 10,
                                     convert_bytes_to_offset(vfo.a.offset))
        rset = RadioSetting("vfo.a.offset", "Offset (MHz)", rs)
        rset.set_apply_callback(apply_offset, vfo.a)
        rset.set_doc("Set A Band TX frequency offset value.")
        achannel.append(rset)

        # Menu 27: Offset direction
        rs = RadioSettingValueList(self._offset_list,
                                   current_index=vfo.a.sftd)
        rset = MemSetting("vfo.a.sftd", "Offset Direction", rs)
        rset.set_doc("Set A Band TX frequency offset direction.")
        achannel.append(rset)

        # Menu 29: S-Code DTMF 1-15
        rs = RadioSettingValueList(self._scode_list,
                                   current_index=vfo.a.scode)
        rset = MemSetting("vfo.a.scode", "S-CODE", rs)
        rset.set_doc("Set the A Band DTMF code ID to use for PTT ID.")
        achannel.append(rset)

        # Menu 45: Scramble
        rs = RadioSettingValueMap(self._scramble_map, vfo.a.scramble)
        rset = MemSetting("vfo.a.scramble", "Scramble", rs)
        rset.set_doc("Set A Band voice Scramble.")
        achannel.append(rset)

        # Menu 50: RX Modulation
        if self._has_am_per_channel:
            rs = RadioSettingValueList(self._rx_modulation_list,
                                       current_index=vfo.a.rxmod)
            rset = MemSetting("vfo.a.rxmod", "RX Modulation", rs)
            rset.set_doc("Set A Band RX Modulation.")
            achannel.append(rset)

        # VFO B channel sub menu
        bchannel = RadioSettingSubGroup("bchannel", "VFO B Channel")
        abblock.append(bchannel)

        # Work Mode B
        rs = RadioSettingValueList(WORKMODE_LIST,
                                   current_index=_settings.vfomrb)
        rset = MemSetting("settings.vfomrb", "Work Mode", rs)
        rset.set_doc("Set B Band Work Mode.")
        bchannel.append(rset)

        # VFO B Freq
        rs = RadioSettingValueString(0, 10,
                                     bfc.bcd_decode_freq(vfo.b.freq))
        rs.set_validate_callback(freq_validate)
        rset = RadioSetting("vfo.b.freq", "Frequency", rs)
        rset.set_apply_callback(apply_freq, vfo.b)
        rset.set_doc("Set B Band VFO frequency.")
        bchannel.append(rset)

        # Menu 01: B Step
        rs = RadioSettingValueMap(self._step_map, vfo.b.step)
        rset = MemSetting("vfo.b.step", "Tuning Step", rs)
        rset.set_doc("Set B Band frequency Tuning Step.")
        bchannel.append(rset)

        # Menu 02: TX Power
        rs = RadioSettingValueList([str(x) for x in self.POWER_LEVELS],
                                   current_index=vfo.b.txpower)
        rset = MemSetting("vfo.b.txpower", "TX Power", rs)
        rset.set_doc("Set B Band TX Power.")
        bchannel.append(rset)

        # Menu 05: Wide/Narrow Band
        rs = RadioSettingValueList(self._bandwidth_list,
                                   current_index=vfo.b.widenarr)
        rset = MemSetting("vfo.b.widenarr", "Bandwidth", rs)
        rset.set_doc("Set B Band Bandwidth.")
        bchannel.append(rset)

        # Menu 12,13: RX ctcss/dtsc
        rs = RadioSettingValueList(self._code_list,
                                   current_index=self._code_list.index
                                   (self.decode(vfo.b.rxtone)))
        rset = RadioSetting("vfo.b.rxtone", "RX CTCSS/DCS", rs)
        rset.set_apply_callback(self.apply_vfo_tone,
                                self._memobj.vfo.b, "rxtone")
        rset.set_doc("Set B Band RX CTCSS or DCS code.")
        bchannel.append(rset)

        # Menu 14,15: TX ctcss/dtsc
        rs = RadioSettingValueList(self._code_list,
                                   current_index=self._code_list.index
                                   (self.decode(vfo.b.txtone)))
        rset = RadioSetting("vfo.b.txtone", "TX CTCSS/DCS", rs)
        rset.set_apply_callback(self.apply_vfo_tone,
                                self._memobj.vfo.b, "txtone")
        rset.set_doc("Set B Band TX CTCSS or DCS code.")
        bchannel.append(rset)

        # Menu 16: Voice Privacy (encryption)
        rs = RadioSettingValueList(self._voicepri_list,
                                   current_index=vfo.b.voicepri)
        rset = MemSetting("vfo.b.voicepri",
                          "Voice Privacy - Subtone Encryption", rs)
        rset.set_doc("Set B Band Voice Privacy - subtone voice encryption.")
        bchannel.append(rset)

        # Menu 26: Offset
        rs = RadioSettingValueString(0, 10,
                                     convert_bytes_to_offset(vfo.b.offset))
        rset = RadioSetting("vfo.b.offset", "Offset (MHz)", rs)
        rset.set_apply_callback(apply_offset, vfo.b)
        rset.set_doc("Set B Band TX frequency offset value.")
        bchannel.append(rset)

        # Menu 27: Offset direction
        rs = RadioSettingValueList(self._offset_list, current_index=vfo.b.sftd)
        rset = MemSetting("vfo.b.sftd", "Offset Direction", rs)
        rset.set_doc("Set B Band TX frequency offset direction.")
        bchannel.append(rset)

        # Menu 29: S-Code DTMF 1-15
        rs = RadioSettingValueList(
            self._scode_list, current_index=vfo.b.scode)
        rset = MemSetting("vfo.b.scode", "S-CODE", rs)
        rset.set_doc("Set the B Band DTMF code ID to use for PTT ID.")
        bchannel.append(rset)

        # Menu 45: Scramble
        rs = RadioSettingValueMap(self._scramble_map, vfo.b.scramble)
        rset = MemSetting("vfo.b.scramble", "Scramble", rs)
        rset.set_doc("Set B Band voice Scramble.")
        bchannel.append(rset)

        # Menu 50: RX Modulation
        if self._has_am_per_channel:
            rs = RadioSettingValueList(self._rx_modulation_list,
                                       current_index=vfo.b.rxmod)
            rset = MemSetting("vfo.b.rxmod", "RX Modulation", rs)
            rset.set_doc("Set B Band RX Modulation.")
            bchannel.append(rset)

        # SSB Settings, RT-920, BJ7800 Only
        if self._has_hf:
            ssbblock = RadioSettingGroup("ssbblock", "FM/AM/SSB Modulation")
            spec.append(ssbblock)

            # HF mode submenu
            modes = RadioSettingSubGroup("modes", "Modes")
            ssbblock.append(modes)

            # SSB Work Mode
            ssbwm = self._memobj.ssb_settings
            rs = RadioSettingValueList(
                self._ssb_workmode_list,
                current_index=ssbwm.workmode
            )
            rset = MemSetting("ssb_settings.workmode", "Work Mode", rs)
            rset.set_doc("Set HF Workmode.")
            modes.append(rset)

            # SSB Modulation Mode
            ssb = self._memobj.ssb
            rs = RadioSettingValueList(
                self._ssb_modulation_list,
                current_index=ssb.modulation
            )
            rset = MemSetting("ssb.modulation", "Modulation Mode", rs)
            rset.set_doc("Set HF RX Modulation Mode.")
            modes.append(rset)

            # AM mode submenu
            amsettings = RadioSettingSubGroup("amsettings", "AM Settings")
            ssbblock.append(amsettings)

            # AM Step Freq
            stepfreq = self._memobj.stepfreq
            rs = RadioSettingValueList(
                self._am_step_freq_list,
                current_index=stepfreq.am
            )
            rset = MemSetting("stepfreq.am", "Step Freq", rs)
            rset.set_doc("Set HF AM RX Step Frequency.")
            amsettings.append(rset)

            # AM RX Gain
            rs = RadioSettingValueList(
                self._rx_gain_list,
                current_index=ssb.am_rxgain
            )
            rset = MemSetting("ssb.am_rxgain", "RX Gain", rs)
            rset.set_doc("Set HF AM RX Gain value.")
            amsettings.append(rset)

            # SSB mode submenu
            ssbsettings = RadioSettingSubGroup("ssbsettings", "SSB Settings")
            ssbblock.append(ssbsettings)

            # SSB Step Freq
            rs = RadioSettingValueList(
                self._ssb_step_freq_list,
                current_index=stepfreq.ssb
            )
            rset = MemSetting("stepfreq.ssb", "Step Freq", rs)
            rset.set_doc("Set HF SSB RX Step Frequency.")
            ssbsettings.append(rset)

            # SSB RX Gain
            rs = RadioSettingValueList(
                self._rx_gain_list,
                current_index=stepfreq.ssb_rxgain
            )
            rset = MemSetting("stepfreq.ssb_rxgain", "RX Gain", rs)
            rset.set_doc("Set HF SSB RX Gain value.")
            ssbsettings.append(rset)

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

    def _decode_tone(self, memval):
        """Parse the tone data to decode from memval, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        pol = None
        if memval in [0, 0xFFFF]:
            return "", None, None
        elif memval >= 0x0258:
            a = memval / 10.0
            return "Tone", a, pol
        else:
            if memval > 0x69:
                index = memval - 0x6A
                pol = "R"
            else:
                index = memval - 1
                pol = "N"
            tone = DTCS[index]
            return "DTCS", tone, pol

    def _encode_tone(self, mem, memval, mode, value, pol):
        """Parse the tone data to encode from UI to mem"""
        match mode:
            case "" | None:
                memval.fill_raw(b"\x00")
            case "Tone" | "TSQL":
                memval.set_value(int(value * 10))
            case "DTCS":
                try:
                    index = DTCS.index(value)
                    if pol == "N":
                        index += 1
                    else:
                        index += 0x6A
                    memval.set_value(index)
                except ValueError:
                    msg = "DTCS Code '%d' is not supported" % value
                    LOG.error(msg)
                    raise errors.RadioError(msg)
            case _:
                raise Exception("Internal error: invalid mode '%s'" % mode)

    def decode(self, code):
        """decode radio stored VFO tone code into human readable form"""
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

    def apply_vfo_tone(self, setting, obj, which):
        """encode VFO tone from UI into radio storable tone code
        and apply to mem"""
        mem = getattr(obj, which)
        try:
            tone = self._code_list[int(setting.value)]
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
        except (IndexError, ValueError):
            msg = "Unknown CTCSS/DTC tone: %s" % tone
            LOG.exception(msg)
            raise InvalidValueError(msg)

        mem.set_value(code)

    def get_features(self):
        rf = get_default_features(self)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_modes = ["FM", "NFM", "AM", "NAM"]  # 25kHz, 12.5kHz, AM, NAM
        rf.valid_tuning_steps = self._steps
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number - 1]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if _mem.get_raw()[:1] == b"\xff":
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        if mem.freq == 0:
            mem.empty = True
        # tx freq can be blank
        if _mem.txfreq.get_raw() == b"\xff\xff\xff\xff":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if chirp_common.is_split(self.get_features().valid_bands,
                                         mem.freq, int(_mem.txfreq) * 10):
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

        txtone = rxtone = None
        txtone = self._decode_tone(_mem.txtone)
        rxtone = self._decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

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
        rset.set_doc("Set Busy Channel Lockout. When selected, disables PTT "
                     "when the current channel is busy.")
        mem.extra.append(rset)

        # LearnFHSS (per-channel learn / FHSS flag). The OEM CPS labels
        # this column "LearnFHSS"; the open-source firmware reads the
        # same bit as chFlag3.b0 / fhssFlag (Core/Radio.c).
        rs = RadioSettingValueBoolean(_mem.learning)
        rset = RadioSetting("learning", "Learn FHSS", rs)
        rset.set_doc("Enable to allow automatic FHSS code selection.")
        mem.extra.append(rset)

        # FHSS Code (24-bit little-endian, range 0x000000-0x7FFFFF).
        # Displayed and accepted as a 6-digit uppercase hex string, or
        # blank to clear the code (raw 0xFFFFFF). Validation is hoisted
        # to a module-level function so this RadioSetting stays
        # picklable for clipboard copy.
        rs = RadioSettingValueString(0, 6, _fhss_code_to_text(_mem.code))
        rs.set_validate_callback(_validate_fhss_code)
        rset = RadioSetting("fhss_code", "FHSS Code (hex)", rs)
        rset.set_doc("Enter manual FHSS Code using HEX digits.")
        mem.extra.append(rset)

        # PTT-ID
        rs = RadioSettingValueList(PTTID_LIST, current_index=_mem.pttid)
        rset = RadioSetting("pttid", "PTT ID", rs)
        rset.set_doc("Set when the PTT-ID is to be sent.")
        mem.extra.append(rset)

        # Signal (DTMF Encoder Group #)
        rs = RadioSettingValueList(PTTIDCODE_LIST, current_index=_mem.scode)
        rset = RadioSetting("scode", "PTT ID Code", rs)
        rset.set_doc("Set the DTMF code ID to use for PTT ID.")
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.fill_raw(b"\xff")
            return

        _mem.set_raw("\x00" * 16 + "\xff" * 16)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xff")
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
                _mem.name[i] = "\xff"

        txmode = rxmode = ''
        txval = rxval = 0
        txpol = rxpol = None
        ((txmode, txval, txpol),
         (rxmode, rxval, rxpol)) = chirp_common.split_tone_encode(mem)

        self._encode_tone(mem, _mem.txtone, txmode, txval, txpol)
        self._encode_tone(mem, _mem.rxtone, rxmode, rxval, rxpol)

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
            if setting.get_name() == 'fhss_code':
                # Mirror OEM CPS: blank input clears Code (0xFFFFFF) and
                # restores the adjacent flag byte to 0xFF; any value
                # writes Code and sets the flag byte to 0xA0.
                s = str(setting.value).strip()
                if s == "":
                    _mem.code = FHSS_CODE_NULL
                    _mem.code_flag = FHSS_CODE_FLAG_NULL
                else:
                    _mem.code = int(s, 16)
                    _mem.code_flag = FHSS_CODE_FLAG_ACTIVE
            else:
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
        # apply all Memsettings
        all_other_settings = settings.apply_to(self._memobj)
        for setting in all_other_settings:
            if setting.has_apply_callback():
                # use callbacks on Radiosettings that need postprocessing
                setting.run_apply_callback()

    def process_mmap(self):
        mem_format = MEM_FORMAT % self._mem_params
        self._memobj = bitwise.parse(mem_format, self._mmap)


@directory.register
class RT900(RT900BT):
    # ==========
    # Notice to developers:
    # The RT-900 support in this driver is currently based upon stock
    # factory firmware, V0.14P
    # ==========

    """Radtel RT-900 (without Bluetooth)"""
    VENDOR = "Radtel"
    MODEL = "RT-900"

    _has_bt_denoise = False
    _has_am_per_channel = False
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = False
    _has_hf = False

    _upper = 999  # fw V1.14P expands from 512 to 999 channels

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
            ('This driver is a beta version for the RT-900'
             ' running Firmware V0.14P\n'
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
    # The RT-910 BT support in this driver is currently based upon V0.24P
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
        rf.has_bank = True  # Firmware V0.24P supports 15
        #                     "static zones" of 64 frequencies
        rf.valid_tuning_steps = self._steps
        return rf

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the RT-910 BT'
             ' running Firmware V0.24P\n'
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
    # The RT-910 support in this driver is currently based upon V0.11
    # firmware with 15 banks/zones of 64 channel steps.
    # ==========
    """Radtel RT-910 960 (without Bluetooth)"""
    VENDOR = "Radtel"
    MODEL = "RT-910"

    _upper = 960  # fw V0.11 supports 960 channels

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

    _has_bt_denoise = False
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = True
    _has_hf = False

    def get_bank_model(self):
        return chirp_common.StaticBankModel(self, banks=15)

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the RT-910'
             ' Non-Bluetooth running Firmware V0.11\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp


class RT920Bank(chirp_common.NamedBank):
    """RT-920 Bank"""
    def get_name(self):
        """decode bank name from char array into string"""
        _bank = self._model._radio._memobj.zones[self._index - 1]
        name = str(_bank.name).rstrip(" \n\t\x00\xff")  # remove filler chars

        if len(name) == 0:
            name = "ZONE %i" % self._index

        return name

    def set_name(self, name):
        """encode bank name into \xff filled char array"""
        _bank = self._model._radio._memobj.zones[self._index - 1]
        _bank.name = name[:len(_bank.name)].rstrip()\
            .ljust(len(_bank.name), "\xff")


class RT920BankModel(chirp_common.StaticBankModel):
    """RT-920 Bank Model"""
    def __init__(self, radio, name, banks):
        super(RT920BankModel, self).__init__(radio, name, banks)
        self._num_banks = banks
        self._rf = radio.get_features()
        self._banks = []
        for i in range(self._num_banks):
            self._banks.append(RT920Bank(self, i + 1, "ZONE %i" % (i + 1)))


@directory.register
class RT920(RT900BT):
    # ==========
    # Notice to developers:
    # The RT-920 support in this driver is currently based upon V0.18
    # firmware with 10 banks/zones of 99 channels.
    # ==========
    """Radtel RT-920"""
    VENDOR = "Radtel"
    MODEL = "RT-920"

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
    _zone_or_channel_list = ["Zone Mode", "Full Channel"]
    _ssb_modulation_list = [
        "FM",
        "AM",
        "LSB",
        "USB",
        "CW",
    ]
    _ssb_workmode_list = [
        "VFO Mode",
        "CH Mode",
    ]
    _am_step_freq_list = [
        "1K",
        "5K",
        "9K",
        "10K",
        "100K",
    ]
    _ssb_step_freq_list = [
        "1K",
        "5K",
        "10K",
        "100K",
        "500K",
        "1000K",
    ]
    _rx_gain_list = ["AGC"] + \
        ["%ddB" % x for x in range(0, -36, -1)]

    _upper = 990  # fw V0.18 supports 990 channels
    _mem_params = (_upper,  # number of channels
                   )
    _banks = 10
    _ranges = [
        (0x0000, 0x7BC0),  # 10 zones of 99 frequencies,
                           # equals 990 channels of 32 bytes each
                           # 10 * 99 * 32 = 0x7BC0
        (0x8000, 0x8040),
        (0x9000, 0x9040),
        (0xA000, 0xA140),
        (0xB000, 0xB400),  # FM, AM, HF frequencies
        (0xC000, 0xC400),  # FM, AM, HF names
        (0xC800, 0XC8A0),  # static bank names, 10 banks * 16 bytes ea = 0xA0
        (0xD000, 0xD040),  # Radio mode hidden setting
    ]

    _rt920_specific_fmt = """
    #seekto 0xb000;
    // 2 byte fm vfo freq
    struct {
        ul16 freq;
    } fm_vfo;
    // 15ea 2 byte fm chan freq
    struct {
        ul16 freq;
    } fm_freqs[%d];

    #seekto 0xb021; // SSB settings
    struct {
        u8 workmode; // VFO/Ch
    } ssb_settings;

    #seekto 0xb022;
    // 2 byte am vfo freq
    struct {
        ul16 freq;
    } am_vfo;
    // 15ea 2 byte am chan freq
    struct {
        ul16 freq;
    } am_freqs[%d];

    #seekto 0xb043; // ssb
    struct {
        u8 modulation; // modulation mode
        u8 am_rxgain; // AM RX gain
    } ssb;

    #seekto 0xb045;
    // 5 byte hf vfo chan
    struct {
        ul16 freq;
        u8 bandwidth;
        il16 beatfreq; // can be negitive
    } hf_vfo;
    // 15ea 5 byte hf chans
        struct {
        ul16 freq;
        u8 bandwidth;
        il16 beatfreq; // can be negitive
    } hf_freqs[%d];

    #seekto 0xb096;
    struct {
        u8 ssb;
        u8 am;
        u8 ssb_rxgain;
    } stepfreq;

    #seekto 0xc010; // 15ea 16 byte fm chan names
    struct {
        char name[12];
        u8 unused[4];
    } fm_names[%d];

    #seekto 0xc110; // 15ea 16 byte am chan names (RT-920 fw v 0.xx)
    struct {
        char name[12];
        u8 unused[4];
    } am_names[%d];

    #seekto 0xc210; // 15ea 16 byte ssb chan names (RT-920 fw v 0.xx)
    struct {
        char name[12];
        u8 unused[4];
    } hf_names[%d];

    #seekto 0xC800; // 10ea 16 byte zone names (RT-920 fw V0.17)
    struct {
      char name[10];
      u8 unused[6];
    } zones[%d];
    """

    _has_bt_denoise = True
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = True
    _has_zone_or_channel = True
    _has_zone_names = True
    _has_sp0 = False  # spkey addresses are not shifted
    _has_hf = True

    def get_bank_model(self):
        return RT920BankModel(self, "Zones", self._banks)

    def get_features(self):
        rf = super().get_features()
        # Firmware V0.18 supports 10
        # optional "static zones" of 99 frequencies
        # or 990 flat chanels
        if self._memobj is not None and hasattr(self._memobj, "settings"):
            rf.has_bank = not self._memobj.settings.zone_or_channel
        else:
            rf.has_bank = False  # default to flat mode if settings not init'ed

        rf.has_bank_names = self._has_zone_names
        rf.valid_tuning_steps = self._steps
        rf.has_sub_devices = self._has_hf
        return rf

    def process_mmap(self):
        AUX_CHANS_FM = AUX_CHANS_AM = AUX_CHANS_HF = 15
        mem_format = MEM_FORMAT % self._mem_params + \
            self._rt920_specific_fmt % (
                AUX_CHANS_FM,
                AUX_CHANS_AM,
                AUX_CHANS_HF,
                AUX_CHANS_FM,
                AUX_CHANS_AM,
                AUX_CHANS_HF,
                self._banks,
            )
        self._memobj = bitwise.parse(mem_format, self._mmap)

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the RT-920'
             ' running Firmware V0.18\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp

    def get_sub_devices(self):
        return [RT920VhfUfh(self._mmap),
                RT920FM(self._mmap),
                RT920AM(self._mmap),
                RT920HF(self._mmap),
                ]


class RT920VhfUfh(RT920):
    """Radtel RT-920 VHF/UHF subdevice"""
    VENDOR = "Radtel"
    MODEL = "RT-920"
    VARIANT = "VHF/UHF"


class RT920FM(RT920):
    """Radtel RT-920 FM broadcast subdevice"""
    VENDOR = "Radtel"
    MODEL = "RT-920"
    VARIANT = "FM Broadcast"

    _upper = 15
    _mem_params = (_upper,  # number of channels
                   )
    _valid_bands = [(64000000, 108000000)]  # in Mhz, 64.0-108 MHz
    SPECIAL_CHANNELS = ["VFO"]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_bands = self._valid_bands
        rf.memory_bounds = (1, self._upper)
        rf.can_delete = True
        rf.can_odd_split = False
        rf.has_bank = False
        rf.has_bank_index = False
        rf.has_bank_names = False
        rf.has_comment = False
        rf.has_cross = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_mode = True
        rf.has_offset = False
        rf.has_settings = False
        rf.has_sub_devices = False
        rf.has_tuning_step = False
        rf.valid_characters = RT900._valid_chars
        rf.valid_cross_modes = []
        rf.valid_dtcs_codes = []
        rf.valid_dtcs_pols = []
        rf.valid_duplexes = []
        rf.valid_modes = ["AM", "WFM", "Auto"]
        rf.valid_name_length = 12
        rf.valid_skips = []
        rf.valid_special_chans = self.SPECIAL_CHANNELS
        rf.valid_tuning_steps = [
            1.0, 2.5, 5.0, 6.25, 8.33, 10.0, 12.5, 20.0, 25.0, 50.0,
            ]
        rf.valid_tmodes = []
        rf.valid_tones = []
        return rf

    def get_raw_memory(self, number):
        if isinstance(number, str):
            return repr(self._memobj.fm_vfo)
        else:
            return (repr(self._memobj.fm_freqs[number - 1]) +
                    repr(self._memobj.fm_names[number - 1]))

    def get_memory(self, number):
        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.number = self._upper + self.SPECIAL_CHANNELS.index(number) + 1
            mem.extd_number = number
            _mem = self._memobj.fm_vfo
        else:
            mem.number = number
            _mem = self._memobj.fm_freqs[number - 1]
            _name = self._memobj.fm_names[number - 1]

        freq = int(_mem.freq) * 10000

        if freq == 0:
            mem.empty = True
            return mem

        mem.freq = freq

        if mem.number > self._upper:
            mem.immutable += ["name"]
        else:
            mem.name = str(_name.name).rstrip("\xff ")

        mem.mode = "WFM"

        mem.immutable += ["mode", "ctone", "rtone"]
        return mem

    def set_memory(self, mem):

        if mem.number > self._upper:
            _mem = self._memobj.fm_vfo
        else:
            _mem = self._memobj.fm_freqs[mem.number - 1]
            _name = self._memobj.fm_names[mem.number - 1]

        if mem.empty:
            _mem.freq.fill_raw(b"\x00")
            if mem.number <= self._upper:
                _name.name.fill_raw(b"\xff")
            return

        _mem.freq = int(mem.freq / 10000)

        if mem.number <= self._upper:
            _name.name = mem.name.ljust(12, "\xff")


class RT920AM(RT920FM):
    """Radtel RT-920 AM broadcast subdevice"""
    VENDOR = "Radtel"
    MODEL = "RT-920"
    VARIANT = "AM Broadcast"

    _valid_bands = [(153000, 279000),     # in Mhz, 153-279 KHz
                    (520000, 1710000),    # 520-1710 KHz
                    (2300000, 26100000),  # 2300-26100 KHz
                    ]

    def get_raw_memory(self, number):
        if isinstance(number, str):
            return repr(self._memobj.am_vfo)
        else:
            return (repr(self._memobj.am_freqs[number - 1]) +
                    repr(self._memobj.am_names[number - 1]))

    def get_memory(self, number):
        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.number = self._upper + self.SPECIAL_CHANNELS.index(number) + 1
            mem.extd_number = number
            _mem = self._memobj.am_vfo
        else:
            mem.number = number
            _mem = self._memobj.am_freqs[number - 1]
            _name = self._memobj.am_names[number - 1]

        freq = int(_mem.freq) * 1000

        if freq == 0:
            mem.empty = True
            return mem

        mem.freq = freq

        if mem.number > self._upper:
            mem.immutable += ["name"]
        else:
            mem.name = str(_name.name).rstrip("\xff ")

        mem.mode = "AM"

        mem.immutable += ["mode", "ctone", "rtone"]
        return mem

    def set_memory(self, mem):

        if mem.number > self._upper:
            _mem = self._memobj.am_vfo
        else:
            _mem = self._memobj.am_freqs[mem.number - 1]
            _name = self._memobj.am_names[mem.number - 1]

        if mem.empty:
            _mem.freq.fill_raw(b"\x00")
            if mem.number <= self._upper:
                _name.name.fill_raw(b"\xff")
            return

        _mem.freq = int(mem.freq / 1000)

        if mem.number <= self._upper:
            _name.name = mem.name.ljust(12, "\xff")


class RT920HF(RT920FM):
    """Radtel RT-920 HF LSB, USB, CW subdevice"""
    VENDOR = "Radtel"
    MODEL = "RT-920"
    VARIANT = "HF"

    _valid_bands = [(150000, 30000000)]  # in Mhz, 150-30000 KHz

    _ssb_bandwidth_list = [
        "0.5K", "1.0K", "1.2K", "2.2K", "3.0K", "4.0K",
    ]

    def get_raw_memory(self, number):
        if isinstance(number, str):
            return repr(self._memobj.hf_vfo)
        else:
            return (repr(self._memobj.hf_freqs[number - 1]) +
                    repr(self._memobj.hf_names[number - 1]))

    def get_memory(self, number):
        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.number = self._upper + self.SPECIAL_CHANNELS.index(number) + 1
            mem.extd_number = number
            _mem = self._memobj.hf_vfo
        else:
            mem.number = number
            _mem = self._memobj.hf_freqs[number - 1]
            _name = self._memobj.hf_names[number - 1]

        freq = int(_mem.freq) * 1000

        if freq == 0:
            mem.empty = True
            return mem

        mem.freq = freq

        if mem.number > self._upper:
            mem.immutable += ["name"]
        else:
            mem.name = str(_name.name).rstrip("\xff ")

        mem.mode = "Auto"

        mem.immutable += ["mode", "ctone", "rtone"]

        mem.extra = RadioSettingGroup("Extra", "extra")

        # Bandwidth
        rs = RadioSettingValueList(
            self._ssb_bandwidth_list,
            current_index=int(_mem.bandwidth)
        )
        rset = RadioSetting("bandwidth", "Bandwidth", rs)
        rset.set_doc("SSB Channel Bandwidth (KHz).")
        mem.extra.append(rset)

        # Beat Freq
        rs = RadioSettingValueInteger(-32760, 27240, int(_mem.beatfreq), 1)
        rset = RadioSetting("beatfreq", "Beat Freq Offset (Hz)", rs)
        rset.set_doc("SSB Beat Frequency Offset (Hz).")
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):

        if mem.number > self._upper:
            _mem = self._memobj.hf_vfo
        else:
            _mem = self._memobj.hf_freqs[mem.number - 1]
            _name = self._memobj.hf_names[mem.number - 1]

        if mem.empty:
            _mem.fill_raw(b"\x00")
            if mem.number <= self._upper:
                _name.name.fill_raw(b"\xff")
            return

        _mem.freq = int(mem.freq / 1000)

        if mem.number <= self._upper:
            _name.name = mem.name.ljust(12, "\xff")

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), int(setting.value))


@directory.register
class RadioddityGS10B(RT900BT):
    # ==========
    # Radioddity GS-10B: RT-900 BT variant with 256 channels.
    # Same magic (PROGRAMBT80U), fingerprints, and protocol as the
    # RT-900 BT. Memory layout is identical but with fewer channels.
    # Based on firmware V0.03.
    # ==========
    """Radioddity GS-10B"""
    VENDOR = "Radioddity"
    MODEL = "GS-10B"

    _upper = 256  # 256 channels
    _has_single_mode = False

    _mem_params = (_upper,  # number of channels
                   )

    _ranges = [
        (0x0000, 0x2000),  # 256 channels of 32 bytes each
                           # 256 * 32 = 0x2000
        (0x8000, 0x8040),
        (0x9000, 0x9040),
        (0xA000, 0xA140),
        (0xD000, 0xD040),  # Radio mode hidden setting
    ]

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the Radioddity GS-10B\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp


@directory.register
class BJ7800(RT920):
    # ==========
    # Notice to developers:
    # The BJ7800 support in this driver is currently based upon V0.15P
    # firmware with 15 banks/zones of 64 channels.
    # Should also work with the SHU H28Y Pro
    # ==========
    """Bajeton BJ7800"""
    VENDOR = "Bajeton"
    MODEL = "BJ7800"

    _upper = 960  # fw V0.15P supports 960 channels
    _mem_params = (_upper,  # number of channels
                   )
    _banks = 15
    _ranges = [
        (0x0000, 0x7800),  # 15 zones of 64 frequencies,
                           # equals 960 channels of 32 bytes each
                           # 15 * 64 * 32 = 0X7800
        (0x8000, 0x8040),
        (0x9000, 0x9040),
        (0xB000, 0xB400),  # FM, AM, HF frequencies
        (0xC000, 0xC400),  # FM, AM, HF names
        (0xA000, 0xA140),
        (0xD000, 0xD040),   # Radio mode hidden setting
    ]

    _has_bt_denoise = True
    _has_am_per_channel = True
    _has_am_switch = not _has_am_per_channel
    _has_single_mode = False
    _has_zone_or_channel = False
    _has_zone_names = False  # dosen't have named zones like the RT-920
    _has_hf = True

    def get_bank_model(self):
        return chirp_common.StaticBankModel(self, banks=self._banks)

    def get_features(self):
        rf = super().get_features()
        # Firmware V0.15P supports 15
        # "static zones" of 64 frequencies
        # for 960 channels
        rf.has_bank = True
        rf.has_bank_names = self._has_zone_names
        rf.valid_tuning_steps = self._steps
        rf.has_sub_devices = self._has_hf
        return rf

    @classmethod
    def get_prompts(cls):
        rp = super().get_prompts()
        rp.experimental = \
            ('This driver is a beta version for the BJ7800'
             ' running Firmware V0.15P\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp

    def get_sub_devices(self):
        return [BJ7800VhfUfh(self._mmap),
                RT920FM(self._mmap),
                RT920AM(self._mmap),
                RT920HF(self._mmap),
                ]


class BJ7800VhfUfh(BJ7800):
    """Bajeton BJ7800 VHF/UHF subdevice"""
    VENDOR = "Bajeton"
    MODEL = "BJ7800"
    VARIANT = "VHF/UHF"
