# Copyright 2012 Dan Smith <dsmith@danplanet.com>
# Copyright 2025 Thibaut Berg <thibaut.berg@hotmail.com>
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
import ctypes
import enum
import logging
import struct
import time
import secrets

from chirp import bitwise
from chirp import chirp_common, memmap, directory, errors
from chirp.bitwise import arrayDataElement
from chirp.chirp_common import CloneModeRadio
from chirp.settings import (RadioSetting, RadioSettingGroup,
                            RadioSettings, RadioSettingValueList,
                            RadioSettingValueString, RadioSettingValueBoolean,
                            RadioSettingValueInteger, RadioSettingValueFloat,
                            RadioSettingSubGroup)

LOG = logging.getLogger(__name__)

DEBUG = True
DEBUG_SERIAL = True

MEM_FORMAT = """
struct {
    u8 flag;
} channels_usage[999];
#printoffset "After channels usage";

struct {
    ul32 rx_freq;
    ul32 freq_diff;
    u8 tx_non_standard_1;
    u8 tx_non_standard_2;
    u8 rx_qt_type;
    u8 tx_qt_type;
    u8 freq_dir;
    u8 band;
    u8 step;
    u8 encrypt;
    u8 power;
    u8 busy;
    u8 reverse;
    u8 dtmf_decode_flag;
    u8 ptt_id;
    u8 mode;
    u8 scan_list;
    u8 sq;
    char name[16];
    u32 rx_qt;
    u32 tx_qt;
    u8 unknown[8];
    ul32 tx_qt2;
    u8 signal;
    u8 unknown_2[3];
} channels[999];
#printoffset "After Channels";

struct {
    u8 channel_ab;
    u8 noaa_sq;
    u8 tx_tot;
    u8 noaa_scan;
    u8 keylock;
    u8 vox_sw;
    u8 vox_lvl;
    u8 mic;
    u8 freq_mode;
    u8 channel_display_mode;
    u8 mw_sw_agc;
    u8 power_save;
    u8 dual_watch;
    u8 backlight;
    ul16 call_ch;
    u8 beep;
    u8 key_short1;
    u8 key_long1;
    u8 key_short2;
    u8 key_long2;
    u8 scan_mode;
    u8 auto_lock;
    u8 power_on_screen_mode;
    u8 alarm_mode;
    u8 roger_tone;
    u8 repeater_tail;
    u8 tail_tone;
    u8 denoise_sw;
    u8 denoise_lvl;
    u8 transpositional_sw;
    u8 transpositional_lvl;
    u8 chn_A_volume;
    u8 chn_B_volume;
    u8 key_tone_flag;
    u8 language;
    u8 noaa_same_decode;
    u8 noaa_same_event;
    u8 noaa_same_address;
    u8 unknown;
    u8 sbar;
    u8 brightness;
    u8 kill_code;
    u8 dtmf_side_tone;
    u8 dtmf_decode_rspn;
    u8 match_tot;
    u8 match_qt_mode;
    u8 match_dcs_bit;
    u8 match_threshold;
    u8 unknown_2;
    ul16 cw_pitch_freq;
    u8 unknown_3[4];
    ul16 dtmf_separator;
    ul16 dtmf_group_code;
    u8 dtmf_reset_time;
    u8 dtmf_resv4;
    ul16 dtmf_carry_time;
    ul16 dtmf_first_code_time;
    ul16 dtmf_d_code_time;
    ul16 dtmf_continue_time;
    ul16 dtmf_interval_time;
    u8 dtmf_id[8];
    u8 dtmf_up_code[16];
    u8 dtmf_down_code[16];
    u8 unknown_4[16];
    ul16 tone5_separator;
    ul16 tone5_group_code;
    u8 tone5_reset_time;
    u8 tone5_resv4;
    ul16 tone5_carry_time;
    ul16 tone5_first_code_time;
    u8 tone5_protocol;
    u8 tone5_resv1;
    ul16 tone5_single_continue_time;
    ul16 tone5_single_interval_time;
    u8 tone5_id[8];
    u8 tone5_up_code[16];
    u8 tone5_down_code[16];
    ul16 tone5_user_freq[15];
    u8 tone5_revs5[2];
    char logo_string1[16];
    char logo_string2[16];

    // General 2 collapsed to general
    u8 unknown_5[48];
    u8 dtmf_kill[8];
    u8 dtmf_wakeup[8];
    u8 tone5_kill[8];
    u8 tone5_wakeup[8];
    u8 unknown_6[16];
    u8 device_name[16];
} general;
#printoffset "After general";

struct {
    ul16 a_id;
    ul16 b_id;
    ul16 freq_a_id;
    ul16 freq_b_id;
    ul16 channel_a_id;
    ul16 channel_b_id;
    ul16 noaa_a_id;
    ul16 noaa_b_id;
} channels_idx;
#printoffset "After channels_idx";

struct {
    ul16 vfo_frequency;
    u8 channel_id;
    u8 memory_vfo_flag;
    u8 unknown[4];
    ul16 frequencies[32];
} fm;
#printoffset "After fm";

struct {
    u8 name[16];
    u8 code_id[8];
} dtmf_contacts[16];
#printoffset "After dtmf_contacts";

struct {
    u8 name[16];
    ul16 prio_1;
    ul16 prio_2;
    u8 unknown[4];
    ul16 channels[48];
    u8 unknown_2[8];
} scan_list[32];
#printoffset "After scan_list";

struct {
    u8 name[16];
    u8 code_id[8];
} tone5_contacts[16];
#printoffset "After 5TONE contacts";

struct {
    u8 address[8];
    u8 info[32];
} noaa_decode_addresses[16];
#printoffset "After NOAA Decode";

struct {
    u8 value;
} noaa_same_events_control[128];
#printoffset "After NOAA SAME event control";
"""

MAX_CHUNK_SIZE = 0x200

MAGIC_CODE = secrets.randbits(32)
START_MESSAGE_FLAG = (0xAB, 0xCD)
END_MESSAGE_FLAG = (0xDC, 0xBA)

CHANNELS_COUNT = 999
NAME_LENGTH = 0x10

POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=1),
    chirp_common.PowerLevel("Middle", watts=5),
    chirp_common.PowerLevel("High", watts=10),
]

TONE_MODES = ['', "Tone", "TSQL", "DTCS", "Cross"]
VALID_CROSS_MODES = [
    'Tone->DTCS', 'DTCS->Tone', 'DTCS->DTCS', 'Tone->Tone'
]

TX_FREQUENCIES = [
    [150000, 1800000],  # 0.15 MHz – 1.8 MHz
    [1800000, 18000000],  # 1.8 MHz – 18 MHz
    [18000000, 32000000],  # 18 MHz – 32 MHz
    [32000000, 76000000],  # 32 MHz – 76 MHz
    [108000000, 136000000],  # 108 MHz – 136 MHz
    [136000000, 174000000],  # 136 MHz – 174 MHz
    [174000000, 350000000],  # 174 MHz – 350 MHz
    [350000000, 400000000],  # 350 MHz – 400 MHz
    [400000000, 470000000],  # 400 MHz – 470 MHz
    [470000000, 580000000],  # 470 MHz – 580 MHz
    [580000000, 760000000],  # 580 MHz – 760 MHz
    [760000000, 1000000000],  # 760 MHz – 1000 MHz
    [1000000000, 1160000000],  # 1000 MHz – 1160 MHz
]

DTMF_TIMES = [str(i) for i in range(30, 1001, 10)]
DTMF_GROUP_CODES = ["A", "B", "C", "D", "*", "#"]
DTMF_SEPARATE_CODES = ["Null", "A", "B", "C", "D", "*", "#"]

_5TONE_TIMES = [str(i) for i in range(30, 1001, 10)]
_5TONE_SINGLE_INTERVAL_TIMES = [str(i) for i in range(0, 1001, 10)]
_5TONE_PROTOCOLS = ["EIA", "EEA", "CCIR", "ZVEI1", "ZVEI2", "User"]
_5TONE_GROUP_CODES = ["A", "B", "C", "D", "E"]
_5TONE_SEPARATE_CODES = ["A", "B", "C", "D", "E"]

NUMERIC_CHARSET = "0123456789"

VALID_TONES = [63.0] + list(chirp_common.TONES)

AVAILABLE_SCAN_LIST = ["None"] + ([str(i) for i in range(1, 33)] +
                                  ["Scan all channels"])
ENCRYPT_LIST = ["Off"] + [str(i) for i in range(1, 11)]
SQUELCH_LIST = list(range(0, 9))
MSW_LIST = ['2K', '2.5K', '3K', '3.5K', '4K', '4.5K', '5K']

TOT_LIST = ["Off"] + [str(i) for i in range(1, 11)]
VOX_MODE = ["Off"] + [str(i) for i in range(1, 11)]
MIC_MODE = [str(i) for i in range(1, 7)]
POWER_ON_MODE = ["Off"] + [f"1:{i}" for i in range(1, 5)]
BACKLIGHT = [
    "Off", "1", "2", "3", "4", "5", "10", "15", "20", "25", "30", "Always ON"
]
SCAN_MODE = ["TO", "CO", "SE"]
ALARM_MODE = ["Local alarm", "Remote alarm"]
RESPOND_MODE = ["OFF", "Remind", "Reply", "Remind & reply"]
BRIGHTNESS_MODE = [str(i) for i in range(8, 201)]

CHANNELS = ["A", "B"]
VOLUME = ["0%", "33%", "66%", "100%"]
CHANNEL_DISPLAY_MODE = ["Frequency", "ID", "Name"]
REPEATER_TAIL_TONE = ["OFF"] + [str(i) for i in range(100, 1100, 100)]
REMIND_END_OF_TALK = \
    ["OFF", "Beep tone", "MDC"] + [f"User{i}" for i in range(1, 6)]
DENOISE = ["OFF"] + [str(i) for i in range(1, 7)]
TRANSPOSITIONAL = ["OFF"] + [str(i) for i in range(1, 6)]

CH_AB_DISPLAY = [f"CH-{i:02d}" for i in range(1, 1000)]

A_DISPLAY_SPECIAL_COUNT = 11
A_DISPLAY = (
    [f"A-F{i:02d}" for i in range(1, A_DISPLAY_SPECIAL_COUNT + 1)] +
    CH_AB_DISPLAY
)

B_DISPLAY_SPECIAL_COUNT = 11
B_DISPLAY = (
    [f"B-F{i:02d}" for i in range(1, B_DISPLAY_SPECIAL_COUNT + 1)] +
    CH_AB_DISPLAY
)

PTT_ID_MODES = ['OFF', 'Start', 'End', 'Start & end']
SIGNAL_MODE = ["DTMF", "5TONE"]
SIDE_KEY_ACTION = [
    'None', 'Flashlight', 'Power selection', 'Monitor', 'Scan', 'VOX', 'Alarm',
    'FM radio', '1750 MHZ'
]
KEY_LOCK_MODE = ["Unlocked", "Locked"]
BOOT_SCREEN_MODE = [
    "Fullscreen", "Welcome", "Battery voltage", "Picture", "None"
]

FREQUENCY_METER_MODES = ["Normal", "Expert mode", "Auto learning mode"]
DCS_MODES = ["23bit", "24bit"]

FREQUENCIES = [
    [150000, 1160000000],  # 0.15 MHz – 1160 MHz
]

CHARSET = "".join([chr(x) for x in range(ord(" "), ord("~") + 1)])

FM_RANGE = (76, 108)

NOAA_SAME_EVENTS = [
    ("ADR", "Administrative Message"),
    ("AVA", "Avalanche Watch"),
    ("AVW", "Avalanche Warning"),
    ("BLU", "Blue Alert"),
    ("BWW", "Boil Water Warning"),
    ("BZW", "Blizzard Warning"),
    ("CAE", "Child Abduction Emergency"),
    ("CDW", "Civil Danger Warning"),
    ("CEM", "Civil Emergency Message"),
    ("CFA", "Coastal Flood Watch"),
    ("CFW", "Coastal Flood Warning"),
    ("DBA", "DAM Watch"),
    ("DMO", "Practice/Demo Warning"),
    ("DSW", "Dust Storm Warning"),
    ("EAN", "Emergency Action Notification"),
    ("EQW", "Civil Earthquake Warning"),
    ("EVA", "Evacuation Watch"),
    ("EVI", "Evacuation Immediate"),
    ("EWW", "Extreme Wind Warning"),
    ("FFA", "Flash Flood Watch"),
    ("FFS", "Flash Flood Statement"),
    ("FFW", "Flash Flood Warning"),
    ("FLA", "Flood Watch"),
    ("FLS", "Flood Statement"),
    ("FLW", "Flood Warning"),
    ("FRW", "Fire Warning"),
    ("FSW", "Flash Freeze Warning"),
    ("FZW", "Freeze Warning"),
    ("HLS", "Hurricane Statement"),
    ("HMW", "Hazardous Materials Warning"),
    ("HUA", "Hurricane Watch"),
    ("HUW", "Hurricane Warning"),
    ("HWA", "High Wind Watch"),
    ("HWW", "High Wind Warning"),
    ("IBW", "Iceberg Warning"),
    ("LAE", "Local Area Emergency"),
    ("LEW", "Law Enforcement Warning"),
    ("NAT", "National Audible Test"),
    ("NIC", "National Information Center"),
    ("NMN", "Network Message Notification"),
    ("NPT", "National Periodic Test"),
    ("NST", "National Silent Test"),
    ("NUW", "Nuclear Power Plant Warning"),
    ("POS", "Power Outage Advisory"),
    ("RHW", "Radiological Hazard Warning"),
    ("RMT", "Required Monthly Test"),
    ("RWT", "Required Weekly Test"),
    ("SMW", "Special Marine Warning"),
    ("SPS", "Special Weather Statement"),
    ("SPW", "Shelter In Place Warning"),
    ("SQW", "Snow Squall Warning"),
    ("SSA", "Storm Surge Watch"),
    ("SSW", "Storm Surge Warning"),
    ("SVA", "Severe Thunderstorm Watch"),
    ("SVR", "Severe Thunderstorm Warning"),
    ("SVS", "Severe Weather Statement"),
    ("TOA", "Tornado Watch"),
    ("TOE", "911 Telephone Outage Emergency"),
    ("TOW", "Tornado Warning"),
    ("TRA", "Tropical Storm Watch"),
    ("TRW", "Tropical Storm Warning"),
    ("TSA", "Tsunami Watch"),
    ("TSW", "Tsunami Warning"),
    ("TXB", "Transmitter Backup On"),
    ("TXF", "Transmitter Carrier Off"),
    ("TXO", "Transmitter Carrier On"),
    ("TXP", "Transmitter Primary On"),
    ("VOW", "Volcano Warning"),
    ("WFA", "Wild Fire Watch"),
    ("WFW", "Wild Fire Warning"),
    ("WSA", "Winter Storm Watch"),
    ("WSW", "Winter Storm Warning"),
    ("", "Unrecognized Warning"),
    ("", "Unrecognized Watch"),
    ("", "Unrecognized Emergency"),
    ("", "Unrecognized Statement"),
    ("", "Unrecognized Message"),
]


class FrequencyDirection(enum.Enum):
    """Frequency direction enum"""
    EQUAL = 0
    ADD = 1
    REMOVE = 2

    @property
    def label(self):
        """Get label for enum value"""
        return {
            FrequencyDirection.EQUAL: "",
            FrequencyDirection.ADD: '+',
            FrequencyDirection.REMOVE: '-'
        }[self]

    @staticmethod
    def from_str(value: str):
        """Convert FrequencyDirection string value to enum"""
        return {
            FrequencyDirection.EQUAL.label: FrequencyDirection.EQUAL,
            FrequencyDirection.ADD.label: FrequencyDirection.ADD,
            FrequencyDirection.REMOVE.label: FrequencyDirection.REMOVE
        }[value]


class Mode(enum.Enum):
    """Modulation enum"""
    NFM = 5
    FM = 0
    AM = 1
    LSB = 2
    USB = 3
    CW = 4


class QTType(enum.Enum):
    """QT Code type enum"""
    NONE = 0
    CTCSS = 1
    NDCS = 2
    IDCS = 3


class Power(enum.Enum):
    """Power enum"""
    LOW = 0
    MIDDLE = 1
    HIGH = 2

    @property
    def level(self):
        """Get power level"""
        return {
            Power.LOW: POWER_LEVELS[0],
            Power.MIDDLE: POWER_LEVELS[1],
            Power.HIGH: POWER_LEVELS[2]
        }[self]


class MemoryAddress:
    """Memory address"""
    CHANNELS_USAGE = 0x11000
    FM = 0x12000
    GENERAL_SETTINGS = 0x13000
    GENERAL_2_SETTINGS = 0x14000
    CHANNELS_IDX = 0x15000
    DTMF_CONTACTS = 0x1A000
    SCAN_LIST = 0x16000
    TONE5 = 0x1A800
    NOAA_DECODE_ADDRESSES = 0x22000
    NOAA_SAME_EVENT_CONTROL = 0x22280


class ChunkSize:
    """Chunk size"""
    SETTINGS = 0xF8
    SETTINGS_2 = 0x70
    CHANNELS_IDX = 0x10
    FM = 0x48
    DTMF_CONTACTS = 0x180
    SCAN_LIST = 0x80
    TONE5_CONTACTS = 0x180
    NOAA_DECODE_ADDRESSES = 0x28
    NOAA_SAME_EVENTS_CONTROL = 0x80


class MessageType(enum.Enum):
    """Message type enum"""
    CONNECT_REQUEST = 0x01F4
    CONNECT_RESPONSE = 0x01F5
    MEMORY_READ_REQUEST = 0x01FB
    MEMORY_READ_RESPONSE = 0x01FC
    MEMORY_WRITE_REQUEST = 0x1FD
    MEMORY_WRITE_RESPONSE = 0x1FE
    REBOOT_REQUEST = 0x5DD


class ConnectionResponse:
    """ConnectionResponse"""

    def __init__(self, message_type: int, message_length: int, version: str):
        self.message_type = message_type
        self.message_length = message_length
        self.version = version

    def __str__(self):
        """Convert representation to string"""
        return (
            f"ConnectionResponse | "
            f"message type : {str(self.message_type)} "
            f"({self.message_length} bytes) - "
            f"{self.version}"
        )

    @staticmethod
    def from_bytes(bytes_array):
        """Convert bytes to ConnectionResponse"""
        if len(bytes_array) < 20:
            raise errors.InvalidDataError("Connect response invalid format")

        unpacked = struct.unpack('<HH16s', bytes_array[:20])

        return ConnectionResponse(
            unpacked[0],
            unpacked[1],
            unpacked[2].split(b'\x00')[0].decode('ascii', errors='ignore')
        )


class ConnectionRequest:
    """ConnectionRequest"""
    MESSAGE_LENGTH = 0x4

    @staticmethod
    def to_bytes():
        """Convert request to bytes"""
        return struct.pack(
            '<HHI',
            MessageType.CONNECT_REQUEST.value,
            ConnectionRequest.MESSAGE_LENGTH,
            MAGIC_CODE
        )


class MessageHeader(ctypes.Structure):
    """MessageHeader structure"""
    _pack_ = 1
    _fields_ = [
        ("message_type", ctypes.c_uint16),
        ("message_length", ctypes.c_uint16),
    ]


class WriteRequest(ctypes.Structure):
    """WriteRequest structure"""
    _pack_ = 1
    _fields_ = [
        ("header", MessageHeader),
        ("address", ctypes.c_uint32),
        ("data_length", ctypes.c_uint16),
        ("advance_flag", ctypes.c_uint8),
        ("rsv", ctypes.c_uint8),
        ("magic_code", ctypes.c_uint32),
    ]


class RebootRequest(ctypes.Structure):
    """RebootRequest structure"""
    _pack_ = 1
    _fields_ = [
        ("header", MessageHeader)
    ]


def parse_str_from_tk11(data: arrayDataElement, default_str: str = "") -> str:
    """Parse string from TK11 format to chirp format as str.
    Remove empty characters."""
    raw = data.get_raw()

    if not raw or raw[0] == 0xFF:
        return default_str

    try:
        return raw.rstrip(b' \x00').decode("ascii")
    except UnicodeDecodeError:
        return default_str


def parse_str_to_tk11(data: str, length: int = 16) -> list[int]:
    """Parse string from chirp format to TK11 format.
    Add empty character until a specific length"""
    return list(data.ljust(length, "\x00").encode("ascii"))


def get_response_code(response) -> int | None:
    """Get response code or None of response length is < 2"""
    if len(response) < 2:
        return None

    return response[0] | response[1] << 8


def crc16_xmodem(content: bytes) -> int:
    """crc16 xmodem"""
    num_array = [
        0, 4129, 8258, 12387, 16516, 20645, 24774, 28903, 33032, 37161, 41290,
        45419, 49548, 53677, 57806, 61935, 4657, 528, 12915, 8786, 21173,
        17044, 29431, 25302, 37689, 33560, 45947, 41818, 54205, 50076, 62463,
        58334, 9314, 13379, 1056, 5121, 25830, 29895, 17572, 21637, 42346,
        46411, 34088, 38153, 58862, 62927, 50604, 54669, 13907, 9842, 5649,
        1584, 30423, 26358, 22165, 18100, 46939, 42874, 38681, 34616, 63455,
        59390, 55197, 51132, 18628, 22757, 26758, 30887, 2112, 6241, 10242,
        14371, 51660, 55789, 59790, 63919, 35144, 39273, 43274, 47403, 23285,
        19156, 31415, 27286, 6769, 2640, 14899, 10770, 56317, 52188, 64447,
        60318, 39801, 35672, 47931, 43802, 27814, 31879, 19684, 23749, 11298,
        15363, 3168, 7233, 60846, 64911, 52716, 56781, 44330, 48395, 36200,
        40265, 32407, 28342, 24277, 20212, 15891, 11826, 7761, 3696, 65439,
        61374, 57309, 53244, 48923, 44858, 40793, 36728, 37256, 33193, 45514,
        41451, 53516, 49453, 61774, 57711, 4224, 161, 12482, 8419, 20484,
        16421, 28742, 24679, 33721, 37784, 41979, 46042, 49981, 54044, 58239,
        62302, 689, 4752, 8947, 13010, 16949, 21012, 25207, 29270, 46570,
        42443, 38312, 34185, 62830, 58703, 54572, 50445, 13538, 9411, 5280,
        1153, 29798, 25671, 21540, 17413, 42971, 47098, 34713, 38840, 59231,
        63358, 50973, 55100, 9939, 14066, 1681, 5808, 26199, 30326, 17941,
        22068, 55628, 51565, 63758, 59695, 39368, 35305, 47498, 43435, 22596,
        18533, 30726, 26663, 6336, 2273, 14466, 10403, 52093, 56156, 60223,
        64286, 35833, 39896, 43963, 48026, 19061, 23124, 27191, 31254, 2801,
        6864, 10931, 14994, 64814, 60687, 56684, 52557, 48554, 44427, 40424,
        36297, 31782, 27655, 23652, 19525, 15522, 11395, 7392, 3265, 61215,
        65342, 53085, 57212, 44955, 49082, 36825, 40952, 28183, 32310, 20053,
        24180, 11923, 16050, 3793, 7920
    ]

    crc = 0
    for value in content:
        index = ((crc >> 8) ^ value) & 0xFF
        crc = ((crc << 8) ^ num_array[index]) & 0xFFFF

    return crc


def content_nor_or(content: bytearray) -> None:
    """content nor or"""
    num_array = bytearray([
        22, 108, 20, 230, 46, 145, 13, 64, 33, 53, 213, 64, 19, 3, 233, 128
    ])

    for i, byte in enumerate(content):
        content[i] = byte ^ num_array[i % 16]


def byte_nor_or(data: bytes, start_index: int, nor_or_len: int) -> bytes:
    """byte nor or"""
    content = bytearray(data[start_index:start_index + nor_or_len])

    content_nor_or(content)

    result = bytearray(data)
    result[start_index:start_index + nor_or_len] = content

    return bytes(result)


def encapsulate_message(buf: bytes) -> bytes:
    """Encapsulate a message with start and end message flags"""
    length = len(buf)
    header_bytes = struct.pack(
        "<BBH",
        START_MESSAGE_FLAG[0],
        START_MESSAGE_FLAG[1],
        length
    )

    crc = crc16_xmodem(buf)
    ender_bytes = struct.pack(
        "<HBB",
        crc,
        END_MESSAGE_FLAG[0],
        END_MESSAGE_FLAG[1]
    )

    data = bytearray()
    data.extend(header_bytes)
    data.extend(buf)
    data.extend(ender_bytes)

    return byte_nor_or(data, 4, length + 2)


def create_parameter_read_request(start_address: int, length: int):
    """Create a parameter read request"""
    address = 0x080000 + start_address

    message_length = 0xC
    rsv = (0, 0)

    fmt = '<HHI H BB I'

    return struct.pack(
        fmt,
        MessageType.MEMORY_READ_REQUEST.value,
        message_length,
        address,
        length,
        rsv[0],
        rsv[1],
        MAGIC_CODE
    )


def parse_data(serial_response) -> bytes | None:
    """Parse data from serial response as bytes
    None is returned if serial is empty or not valid"""
    if serial_response is None or len(serial_response) < 4:
        return None

    length = serial_response[2] | (serial_response[3] << 8)
    num_array1 = bytearray(length)
    index = 4 + length + 2

    if index > len(serial_response):
        return None

    if (serial_response[0] == 0xAB and
            serial_response[1] == 0xCD and
            serial_response[index] == 0xDC and
            serial_response[index + 1] == 0xBA):
        num_array1[:] = serial_response[4:4 + length]
        return byte_nor_or(num_array1, 0, length)

    return None


def read_serial(serial, timeout_ms=2000) -> bytes | None:
    """Read serial as bytes or None"""
    try:
        serial_data = bytearray()

        elapsed = 0
        while elapsed < timeout_ms:
            time.sleep(0.01)
            elapsed += 1

            bytes_available = serial.in_waiting

            if bytes_available > 0:
                data = serial.read(bytes_available)
                serial_data.extend(data)

                if is_serial_message_complete(serial_data):
                    break

        return parse_data(bytes(serial_data))
    except Exception as e:
        raise errors.RadioError("Failed to read data from serial") from e


def is_serial_message_complete(message: bytearray) -> bool:
    """Check if a message is complete or not"""
    return (
            message[0] == START_MESSAGE_FLAG[0] and
            message[1] == START_MESSAGE_FLAG[1] and
            message[-2] == END_MESSAGE_FLAG[0] and
            message[-1] == END_MESSAGE_FLAG[1]
    )


def read_memory(serial, start_address, length):
    """Read TK11 radio memory"""
    request = create_parameter_read_request(start_address, length)
    message = encapsulate_message(request)

    try:
        serial.flush()

        bytes_written = serial.write(message)
        if bytes_written == 0:
            raise errors.RadioError(
                "Failed to send read memory message to radio")

        serial_response = read_serial(serial)
        resp_code = get_response_code(serial_response)
        is_response_code_valid = (
                resp_code == MessageType.MEMORY_READ_RESPONSE.value
        )

        if serial_response is None or not is_response_code_valid:
            LOG.error("Failed to read read memory response from radio")
            raise errors.RadioError(
                "Failed to read read memory response from radio"
            )

        data = serial_response[12:]
    except Exception as se:
        raise errors.RadioError(
            "Error with serial, failed to read memory"
        ) from se

    return data


def dtcs_to_chirp(dtcs: int):
    """Convert DTCS to chirp format"""
    val = ((dtcs >> 24) & 0xFF) | ((dtcs >> 8) & 0x700)
    return int(f"{val:o}")


def dtcs_to_tk11(dtcs):
    """Convert DTCS to tk11 format"""
    val = int(str(dtcs), 8)

    return ((val & 0xFF) << 24) | ((val & 0x700) << 8)


def convert_tone(tone: int) -> int:
    """Convert tone"""
    return int.from_bytes(
        int(tone).to_bytes(4, 'little'),
        'big'
    )


def nullable_float_fm_freq_validate(value):
    """Validate nullable float"""
    if value is None or value == "":
        return ""

    try:
        float_val = float(value)
    except ValueError as ve:
        raise ValueError("Value is not float or empty") from ve

    if float_val < FM_RANGE[0] or float_val > FM_RANGE[1]:
        raise ValueError(f"Value is not in range {FM_RANGE}")

    return str(float_val)


def do_download(radio):
    """This is your download function"""
    # Get the serial port connection
    serial = radio.pipe

    status = chirp_common.Status()
    status.cur = 0
    status.msg = "Connecting to radio"
    radio.status_fn(status)

    connection_request_message = encapsulate_message(
        ConnectionRequest.to_bytes()
    )

    try:
        serial.write(connection_request_message)
    except Exception as se:
        raise errors.RadioError(
            "Error with serial, failed to write connection request message"
        ) from se

    connection_serial_response = read_serial(serial, 1000)

    if connection_serial_response is None:
        LOG.error("Invalid radio model, connection response not received")
        raise errors.RadioError(
            "Invalid radio model, connection response not received"
        )

    connection_response = ConnectionResponse.from_bytes(
        connection_serial_response
    )

    if connection_response.message_type != MessageType.CONNECT_RESPONSE.value:
        LOG.error("Invalid radio connection response")
        raise errors.RadioError("Invalid radio connection response")

    LOG.info(
        "Connected to radio - firmware version : %s",
        connection_response.version
    )

    radio.firmware_version = connection_response.version

    status.msg = "Reading channels usage from radio"
    radio.status_fn(status)

    memory = bytearray()

    # channels
    channels_usage = bytearray()
    for index in range(2):
        channels_usage.extend(
            read_memory(
                serial,
                MemoryAddress.CHANNELS_USAGE + (index * MAX_CHUNK_SIZE),
                MAX_CHUNK_SIZE
            )
        )

    channels_usage = channels_usage[:CHANNELS_COUNT]

    status.msg = "Reading channels from radio"
    radio.status_fn(status)

    radio.edited_channels = []

    channel_struct_size = 64
    channels = bytearray()
    for i_channel in range(CHANNELS_COUNT):
        if channels_usage[i_channel] != 0xFF:
            status.msg = f"Reading channel #{i_channel + 1} from radio"
            radio.status_fn(status)
            channel_response = read_memory(
                serial,
                i_channel * channel_struct_size,
                channel_struct_size
            )
            channels.extend(channel_response)
            radio.edited_channels.append(i_channel)

    channels.extend(
        [0] * (
            (CHANNELS_COUNT - int(len(channels) / channel_struct_size))
            * channel_struct_size
        )
    )

    status.msg = "Reading general settings from radio"
    radio.status_fn(status)

    # General settings
    general_settings = read_memory(
        serial, MemoryAddress.GENERAL_SETTINGS, ChunkSize.SETTINGS
    )

    status.msg = "Reading general settings 2 from radio"
    radio.status_fn(status)

    # General settings 2
    general_settings_2 = read_memory(
        serial, MemoryAddress.GENERAL_2_SETTINGS, ChunkSize.SETTINGS_2
    )

    status.msg = "Reading channel settings from radio"
    radio.status_fn(status)

    # Channels idx
    channels_idx = read_memory(
        serial, MemoryAddress.CHANNELS_IDX, ChunkSize.CHANNELS_IDX
    )

    # FM
    status.msg = "Reading FM settings from radio"
    radio.status_fn(status)

    fm = read_memory(serial, MemoryAddress.FM, ChunkSize.FM)

    # DTMF contacts
    status.msg = "Reading DTMF contacts from radio"
    radio.status_fn(status)

    dtmf_contacts = read_memory(
        serial, MemoryAddress.DTMF_CONTACTS, ChunkSize.DTMF_CONTACTS
    )

    # Scan list
    scan_list = bytearray()
    for i in range(0, 32):
        status.msg = f"Reading scan list #{i + 1} from radio"
        radio.status_fn(status)

        scan_list.extend(
            read_memory(
                serial,
                MemoryAddress.SCAN_LIST + (i * ChunkSize.SCAN_LIST),
                ChunkSize.SCAN_LIST
            )
        )

    status.msg = "Reading 5Tone contacts from radio"
    radio.status_fn(status)
    tone5_contacts = read_memory(
        serial, MemoryAddress.TONE5, ChunkSize.TONE5_CONTACTS
    )

    status.msg = "Reading NOAA decode channels from radio"
    radio.status_fn(status)

    noaa_decode_addresses = bytearray()
    for i in range(0, 16):
        status.msg = f"Reading NOAA decode channel #{i + 1} from radio"
        radio.status_fn(status)

        offset = i * ChunkSize.NOAA_DECODE_ADDRESSES

        noaa_decode_addresses.extend(
            read_memory(
                serial,
                MemoryAddress.NOAA_DECODE_ADDRESSES + offset,
                ChunkSize.NOAA_DECODE_ADDRESSES
            )
        )

    # NOAA SAME events control
    status.msg = "Reading NOAA SAME events control from radio"
    radio.status_fn(status)

    noaa_same_events = read_memory(
        serial,
        MemoryAddress.NOAA_SAME_EVENT_CONTROL,
        ChunkSize.NOAA_SAME_EVENTS_CONTROL
    )

    memory.extend(channels_usage)
    memory.extend(channels)
    memory.extend(general_settings)
    memory.extend(general_settings_2)
    memory.extend(channels_idx)
    memory.extend(fm)
    memory.extend(dtmf_contacts)
    memory.extend(scan_list)
    memory.extend(tone5_contacts)
    memory.extend(noaa_decode_addresses)
    memory.extend(noaa_same_events)

    return memmap.MemoryMapBytes(bytes(memory))


def memory_write(serial, address: int, data: bytearray | bytes) -> bool:
    """Write data to TK11 memory"""
    request = WriteRequest()
    request.header = MessageHeader(
        message_type=MessageType.MEMORY_WRITE_REQUEST.value,
        message_length=0xC
    )
    request.address = 0x080000 + address
    request.data_length = len(data)
    request.magic_code = MAGIC_CODE

    message_data = bytearray()
    message_data.extend(bytes(request))
    message_data.extend(data)

    message = encapsulate_message(message_data)

    try:
        bytes_written = serial.write(message)
        if bytes_written == 0:
            LOG.error("Failed to send memory write message to radio")
            raise errors.RadioError(
                "Failed to send memory write message to radio"
            )
    except Exception as se:
        raise errors.RadioError(
            "Error with serial, failed to write memory write message"
        ) from se

    serial_response = read_serial(serial)

    if serial_response is None:
        LOG.error("Failed to read memory write response from radio")
        raise errors.RadioError(
            "Failed to read memory write response from radio"
        )

    response_code = get_response_code(serial_response)
    memory_response = MessageType.MEMORY_WRITE_RESPONSE.value
    return response_code == memory_response


def reboot(serial):
    """Send request to reboot radio"""
    request = RebootRequest()
    request.header = MessageHeader(
        message_type=MessageType.REBOOT_REQUEST.value,
        message_length=0
    )

    try:
        message = encapsulate_message(bytes(request))
        serial.write(message)
    except Exception as se:
        raise errors.RadioError(
            "Error with serial, failed to write reboot message"
        ) from se


def do_upload(radio):
    """This is your upload function"""
    status = chirp_common.Status()
    status.msg = f"Uploading data to {radio.VENDOR} {radio.MODEL}"
    radio.status_fn(status)

    # Get the serial port connection
    serial = radio.pipe
    memory = radio.get_mmap()

    # Channels usage
    channels_usage_length = 1024
    channels_usage = bytearray(memory[0:CHANNELS_COUNT])
    channels_usage.extend([0xFF] * (channels_usage_length - CHANNELS_COUNT))

    iter_count = int(channels_usage_length / MAX_CHUNK_SIZE)
    for i in range(0, iter_count):
        status.msg = f"Writing channels usage {i + 1}/{iter_count} to radio"
        radio.status_fn(status)

        start = i * MAX_CHUNK_SIZE
        end = start + MAX_CHUNK_SIZE

        data = memory[start:end]
        memory_write(serial, MemoryAddress.CHANNELS_USAGE + start, data)

    # Channel
    channel_struct_size = 64
    for i in sorted(set(radio.edited_channels)):
        status.msg = f"Writing channel #{i + 1} to radio"
        radio.status_fn(status)

        channel_start = (i * channel_struct_size)
        start = CHANNELS_COUNT + channel_start
        end = start + channel_struct_size

        channel = memory[start:end]
        memory_write(serial, channel_start, channel)

    radio.edited_channels = []

    # General settings
    status.msg = "Writing general settings to radio"
    radio.status_fn(status)

    start = 0xFDA7
    end = start + ChunkSize.SETTINGS

    general_settings = memory[start:end]
    memory_write(
        serial, MemoryAddress.GENERAL_SETTINGS, general_settings
    )

    # General settings 2
    status.msg = "Writing general settings 2 to radio"
    radio.status_fn(status)

    start = end
    end = end + ChunkSize.SETTINGS_2

    general_2_settings = memory[start:end]
    memory_write(
        serial, MemoryAddress.GENERAL_2_SETTINGS, general_2_settings
    )

    # Channels IDX
    status.msg = "Writing channels settings to radio"
    radio.status_fn(status)

    start = end
    end = end + ChunkSize.CHANNELS_IDX

    channels_idx = memory[start:end]
    memory_write(serial, MemoryAddress.CHANNELS_IDX, channels_idx)

    # FM
    status.msg = "Writing FM settings to radio"
    radio.status_fn(status)

    start = end
    end = end + ChunkSize.FM

    fm = memory[start:end]
    memory_write(serial, MemoryAddress.FM, fm)

    # DTMF contacts
    status.msg = "Writing DTMF contacts to radio"
    radio.status_fn(status)

    start = end
    end = end + ChunkSize.DTMF_CONTACTS

    dtmf_contacts = memory[start:end]
    memory_write(serial, MemoryAddress.DTMF_CONTACTS, dtmf_contacts)

    # Scan list
    for i in range(0, 32):
        status.msg = f"Writing scan list #{i + 1} to radio"
        radio.status_fn(status)

        start = end
        end = end + ChunkSize.SCAN_LIST

        scan_list = memory[start:end]
        memory_write(
            serial,
            MemoryAddress.SCAN_LIST + (i * ChunkSize.SCAN_LIST),
            scan_list
        )

    # 5TONE contacts
    status.msg = "Writing 5Tone contacts to radio"
    radio.status_fn(status)

    start = end
    end = end + ChunkSize.TONE5_CONTACTS

    tone5_contacts = memory[start:end]
    memory_write(serial, MemoryAddress.TONE5, tone5_contacts)

    # NOAA settings
    for i in range(0, 16):
        status.msg = f"Writing NOAA decode channel #{i + 1} to radio"
        radio.status_fn(status)

        start = end
        end = end + ChunkSize.NOAA_DECODE_ADDRESSES

        scan_list = memory[start:end]

        offset = i * ChunkSize.NOAA_DECODE_ADDRESSES
        memory_write(
            serial,
            MemoryAddress.NOAA_DECODE_ADDRESSES + offset,
            scan_list
        )

    # NOAA
    status.msg = "Writing NOAA SAME events control to radio"
    radio.status_fn(status)

    start = end
    end = end + ChunkSize.NOAA_SAME_EVENTS_CONTROL

    scan_list = memory[start:end]
    memory_write(serial, MemoryAddress.NOAA_SAME_EVENT_CONTROL, scan_list)

    reboot(serial)


def get_channel_frequency_range(frequency: int) -> int | None:
    """Get channel frequency range"""
    channel_frequency_rang = 0

    for f_min, f_max in TX_FREQUENCIES:
        if f_min > frequency or frequency > f_max:
            channel_frequency_rang += 1
        else:
            break

    return channel_frequency_rang


def is_tone_valid(tone):
    """Return true if tone is valid, false otherwise"""
    return tone in VALID_TONES


def parse_scan_channel_to_tk11(channels, name):
    if name == "Current channel":
        return 0x5A5A

    if name == "None":
        return CHANNELS_COUNT

    channels = [
        parse_str_from_tk11(c.name) if c.rx_freq != 0 else ""
        for c in channels
    ]

    try:
        return channels.index(name)
    except ValueError:
        return CHANNELS_COUNT


def parse_scan_channel_from_tk11(memory_channels, value, prio_channels):
    if value == 0x5A5A:
        return 0

    try:
        parsed = parse_str_from_tk11(memory_channels[value].name)
        return prio_channels.index(parsed)
    except (ValueError, IndexError):
        return 1


def index_to_char(i):
    if 1 <= i <= 9:
        return str(i)

    return chr(ord('A') + (i - 10))


@directory.register
class TK11(CloneModeRadio):
    """Quansheng TK 11"""
    VENDOR = "Quansheng"
    MODEL = "TK11"
    BAUD_RATE = 38400

    firmware_version = "unknown"

    edited_channels = []  # store edited channels

    # All new drivers should be "Byte Clean" so leave this in place.

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        """Get radio features"""
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_settings = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True

        rf.memory_bounds = (1, CHANNELS_COUNT)

        rf.valid_bands = FREQUENCIES

        rf.valid_power_levels = POWER_LEVELS
        rf.valid_modes = [mode.name for mode in Mode]

        rf.valid_name_length = NAME_LENGTH

        rf.valid_duplexes = [
            direction.label for direction in FrequencyDirection
        ]

        rf.valid_characters = CHARSET

        rf.valid_tmodes = TONE_MODES
        rf.valid_cross_modes = VALID_CROSS_MODES
        rf.valid_tones = VALID_TONES
        rf.valid_skips = []

        return rf

    def set_settings(self, settings):
        """Set settings"""
        memory = self._memobj

        settings_root = settings["settings"]

        # Startup
        startup = settings_root["startup"]

        memory.general.device_name = parse_str_to_tk11(
            str(startup["device_name"].value)
        )

        memory.general.power_on_screen_mode = int(startup["boot_screen"].value)

        memory.general.logo_string1 = parse_str_to_tk11(
            str(startup["start_string_1"].value)
        )
        memory.general.logo_string2 = parse_str_to_tk11(
            str(startup["start_string_2"].value)
        )

        a_display = int(startup["a_display"].value)
        if a_display < A_DISPLAY_SPECIAL_COUNT:
            memory.channels_idx.a_id = CHANNELS_COUNT + a_display
        else:
            memory.channels_idx.a_id = a_display - A_DISPLAY_SPECIAL_COUNT

        b_display = int(startup["b_display"].value)
        if b_display < B_DISPLAY_SPECIAL_COUNT:
            memory.channels_idx.b_id = CHANNELS_COUNT + b_display
        else:
            memory.channels_idx.b_id = b_display - B_DISPLAY_SPECIAL_COUNT

        # Buttons
        buttons = settings_root["buttons"]
        memory.general.key_short1 = int(
            buttons["side_key_1_short_press"].value
        )
        memory.general.key_long1 = int(buttons["side_key_1_long_press"].value)
        memory.general.key_short2 = int(
            buttons["side_key_2_short_press"].value
        )
        memory.general.key_long2 = int(buttons["side_key_2_long_press"].value)

        memory.general.keylock = int(buttons["key_lock"].value)
        memory.general.auto_lock = bool(buttons["auto_lock"].value)

        # General settings
        general = settings_root["general"]
        memory.general.tx_tot = int(general["tot"].value)

        vox = int(general["vox"].value)
        if vox == 0:
            memory.general.vox_sw = 0
            memory.general.vox_lvl = 0
        else:
            memory.general.vox_sw = 1
            memory.general.vox_lvl = vox - 1

        memory.general.mic = int(general["microphone"].value)
        memory.general.beep = bool(general["beep_tone"].value)
        memory.general.power_save = int(general["power_on_mode"].value)
        memory.general.backlight = int(general["backlight"].value)
        memory.general.scan_mode = int(general["scan_mode"].value)
        memory.general.alarm_mode = int(general["alarm"].value)
        memory.general.kill_code = bool(general["kill_code"].value)
        memory.general.dtmf_side_tone = bool(general["side_tone"].value)
        memory.general.dtmf_decode_rspn = int(general["respond"].value)
        memory.general.sbar = bool(general["s_bar"].value)
        memory.general.key_tone_flag = bool(general["voice"].value)
        memory.general.mw_sw_agc = bool(general["mw_sw_agc"].value)
        memory.general.brightness = int(general["brightness"].value)
        memory.general.cw_pitch_freq = int(general["cw_pitch_freq"].value)

        # Channel settings
        channel = settings_root["channel"]

        memory.general.channel_ab = int(channel["main_channel"].value)
        memory.general.chn_A_volume = int(channel["a_rx_volume_balance"].value)
        memory.general.chn_B_volume = int(channel["b_rx_volume_balance"].value)
        memory.general.freq_mode = bool(channel["vfo_mode"].value)
        memory.general.channel_display_mode = int(
            channel["channel_display_mode"].value
        )
        memory.general.repeater_tail = int(channel["repeater_tail_tone"].value)
        memory.general.call_ch = int(channel["call_channel"].value)
        memory.general.tail_tone = int(channel["tail_tone"].value)
        memory.general.dual_watch = int(channel["dual_receive"].value)
        memory.general.roger_tone = int(channel["remind_eot"].value)

        denoise = int(channel["denoise"].value)
        if denoise == 0:
            memory.general.denoise_sw = 0
            memory.general.denoise_lvl = 0
        else:
            memory.general.denoise_sw = 1
            memory.general.denoise_lvl = denoise - 1

        transpositional = int(channel["transpositional"].value)
        if transpositional == 0:
            memory.general.transpositional_sw = 0
            memory.general.transpositional_lvl = 0
        else:
            memory.general.transpositional_sw = 1
            memory.general.transpositional_lvl = transpositional - 1

        # Match frequency
        match_frequency = settings_root["match_frequency"]

        memory.general.match_tot = int(
            match_frequency["frequency_meter_tot"].value
        )
        memory.general.match_qt_mode = int(
            match_frequency["frequency_meter_mode"].value
        )
        memory.general.match_dcs_bit = int(
            match_frequency["dcs"].value
        )
        memory.general.match_threshold = int(
            match_frequency["match_threshold"].value
        )

        # FM
        fm = settings_root["fm"]

        memory.fm.vfo_frequency = int(fm["vfo"].value * 10)
        memory.fm.memory_vfo_flag = int(fm["mode"].value)
        memory.fm.channel_id = int(fm["channel"].value)

        for i, setting in enumerate(settings["fm_frequencies"]):
            memory.fm.frequencies[i] = 0xFFFF \
                if setting.value == "" else int(float(setting.value) * 10)

        # NOAA settings
        noaa = settings_root["noaa"]

        memory.general.noaa_same_decode = int(
            noaa["noaa_same_decode"].value
        )
        memory.general.noaa_same_event = int(
            noaa["noaa_same_event"].value
        )
        memory.general.noaa_same_address = int(
            noaa["noaa_same_address"].value
        )
        memory.general.noaa_sq = noaa["noaa_sq"].value.get_value()
        memory.general.noaa_scan = int(
            noaa["noaa_scan"].value
        )

        items = noaa["noaa_same_event_control"].items()
        for i, (name, ev) in enumerate(items):
            memory.noaa_same_events_control[i].value = int(
                ev[name + "_checked"].value
            )

        # DTMF settings
        self.set_dtmf_settings(memory, settings["dtmf_settings"])
        self.set_dtmf_contacts(
            memory,
            settings["dtmf_settings"]["dtmf_contacts"]
        )

        # Scan list
        scan_list = settings["scan_list"]

        for group_name, scan_group in scan_list.items():
            i = int(group_name.split("_")[-1])

            name = str(scan_group[f"{group_name}_name"].value)
            prio_1_name = str(scan_group[f"{group_name}_prio_channel_1"].value)
            prio_2_name = str(scan_group[f"{group_name}_prio_channel_2"].value)

            memory.scan_list[i].name = parse_str_to_tk11(name)
            memory.scan_list[i].prio_1 = parse_scan_channel_to_tk11(
                memory.channels, prio_1_name
            )
            memory.scan_list[i].prio_2 = parse_scan_channel_to_tk11(
                memory.channels, prio_2_name
            )

        # 5TONE settings
        tone5_settings = settings["tone5_settings"]
        self.set_tone5_settings(memory, tone5_settings)
        self.set_tone5_contacts(
            memory,
            tone5_settings["tone5_contacts"]
        )

        # NOAA Decode Addresses
        noaa_decode_addresses = settings["noaa_decode_addresses"]
        for i, (name, group) in enumerate(noaa_decode_addresses.items()):
            memory.noaa_decode_addresses[i].address = parse_str_to_tk11(
                str(group[name + "_address"].value), 8
            )
            memory.noaa_decode_addresses[i].info = parse_str_to_tk11(
                str(group[name + "_information"].value), 32
            )

    @staticmethod
    def set_dtmf_settings(memory, dtmf_settings):
        """Set DTMF settings"""
        memory.general.dtmf_id = parse_str_to_tk11(
            str(dtmf_settings["local_code"].value), 8
        )
        memory.general.dtmf_kill = parse_str_to_tk11(
            str(dtmf_settings["kill_code"].value), 8
        )
        memory.general.dtmf_wakeup = parse_str_to_tk11(
            str(dtmf_settings["revive_code"].value), 8
        )
        memory.general.dtmf_separator = ord(
            str(dtmf_settings["separate_code"].value)
        )
        memory.general.dtmf_group_code = ord(
            str(dtmf_settings["group_code"].value)
        )
        memory.general.dtmf_reset_time = int(
            dtmf_settings["auto_reset_time"].value
        )
        memory.general.dtmf_up_code = parse_str_to_tk11(
            str(dtmf_settings["up_code"].value)
        )
        memory.general.dtmf_down_code = parse_str_to_tk11(
            str(dtmf_settings["down_code"].value)
        )
        memory.general.dtmf_carry_time = (
            dtmf_settings["pre_load_time"].value.get_value()
        )
        memory.general.dtmf_first_code_time = (
            dtmf_settings["first_code_persist"].value.get_value()
        )
        memory.general.dtmf_d_code_time = (
            dtmf_settings["code_persist_time"].value.get_value()
        )
        memory.general.dtmf_continue_time = (
            dtmf_settings["code_continue_time"].value.get_value()
        )
        memory.general.dtmf_interval_time = (
            dtmf_settings["code_interval_time"].value.get_value()
        )

    @staticmethod
    def set_dtmf_contacts(memory, dtmf_contacts):
        """Set DTMF contacts"""
        for i, contact in enumerate(memory.dtmf_contacts):
            group = dtmf_contacts[f"dtmf-contact-{i}"]

            contact.name = parse_str_to_tk11(
                str(group[f"contact_{i}_name"].value)
            )

            contact.code_id = parse_str_to_tk11(
                str(group[f"contact_{i}_id_code"].value), 8
            )

    @staticmethod
    def set_tone5_settings(memory, tone5_settings):
        """Set DTMF settings"""
        memory.general.tone5_id = parse_str_to_tk11(
            str(tone5_settings["local_code"].value), 8
        )
        memory.general.tone5_kill = parse_str_to_tk11(
            str(tone5_settings["kill_code"].value), 8
        )
        memory.general.tone5_wakeup = parse_str_to_tk11(
            str(tone5_settings["revive_code"].value), 8
        )
        memory.general.tone5_separator = ord(
            str(tone5_settings["separate_code"].value)
        )
        memory.general.tone5_group_code = ord(
            str(tone5_settings["group_code"].value)
        )
        memory.general.tone5_reset_time = int(
            tone5_settings["auto_reset_time"].value
        )
        memory.general.tone5_up_code = parse_str_to_tk11(
            str(tone5_settings["up_code"].value)
        )
        memory.general.tone5_down_code = parse_str_to_tk11(
            str(tone5_settings["down_code"].value)
        )
        memory.general.tone5_carry_time = (
            tone5_settings["pre_load_time"].value.get_value()
        )
        memory.general.tone5_first_code_time = (
            tone5_settings["first_code_persist"].value.get_value()
        )
        memory.general.tone5_first_code_time = (
            tone5_settings["code_persist_time"].value.get_value()
        )
        memory.general.tone5_single_continue_time = (
            tone5_settings["code_continue_time"].value.get_value()
        )
        memory.general.tone5_single_interval_time = (
            tone5_settings["code_interval_time"].value.get_value()
        )
        memory.general.tone5_protocol = int(
            tone5_settings["protocol"].value
        )

        # User frequencies
        frequencies = tone5_settings["tone5_user_frequencies"]
        for i, user_frequency in enumerate(frequencies):
            memory.general.tone5_user_freq[i] = int(user_frequency.value)

    @staticmethod
    def set_tone5_contacts(memory, tone5_contacts):
        """Set DTMF contacts"""
        for i, contact in enumerate(memory.tone5_contacts):
            group = tone5_contacts[f"tone5-contact-{i}"]

            contact.name = parse_str_to_tk11(
                str(group[f"contact_{i}_name"].value)
            )

            contact.code_id = parse_str_to_tk11(
                str(group[f"contact_{i}_id_code"].value), 8
            )

    def get_settings(self):
        """Get settings"""
        memory = self._memobj

        firmware = self.get_firmware_settings_group()
        settings = self.get_settings_group(memory)
        dtmf = self.get_dtmf_group(memory)
        tone5 = self.get_tone5_group(memory)
        scan_list = self.get_scan_list_group(memory)
        fm_frequencies = self.get_fm_frequencies_group(memory)
        noaa_decode_addresses = self.get_noaa_decode_addresses_group(memory)

        return RadioSettings(
            firmware, settings, scan_list, dtmf, tone5, fm_frequencies,
            noaa_decode_addresses
        )

    def get_firmware_settings_group(self):
        """Get firmware settings"""
        firmware = RadioSettingGroup("firmware", "Firmware")
        firmware_value_str = RadioSettingValueString(
            0,
            7,
            str(self.firmware_version)
        )

        firmware_value_str.set_mutable(False)

        firmware_version = RadioSetting(
            "firmware_version",
            "Version",
            firmware_value_str
        )

        firmware.append(firmware_version)
        return firmware

    @staticmethod
    def get_scan_list_group(memory):
        """Get a scan list settings group"""
        scan_list = RadioSettingGroup("scan_list", "Scan list")

        for i, scan in enumerate(memory.scan_list):
            sub_group = RadioSettingSubGroup(
                f"scan_list_{i}", f"Scan list {i + 1}"
            )

            name = RadioSetting(
                f"scan_list_{i}_name",
                "Name",
                RadioSettingValueString(
                    0,
                    10,
                    parse_str_from_tk11(scan.name, f"ScanList{i + 1}"),
                    autopad=False
                )
            )
            sub_group.append(name)

            prio_channels = ["Current channel", "None"] + [
                parse_str_from_tk11(memory.channels[i].name)
                for i in scan.channels if i != 0xFFFF
            ]

            prio_channel_1 = RadioSetting(
                f"scan_list_{i}_prio_channel_1",
                "Prio channel 1",
                RadioSettingValueList(
                    prio_channels,
                    current_index=parse_scan_channel_from_tk11(
                        memory.channels, int(scan.prio_1), prio_channels
                    )
                )
            )
            sub_group.append(prio_channel_1)

            prio_channel_2 = RadioSetting(
                f"scan_list_{i}_prio_channel_2",
                "Prio channel 2",
                RadioSettingValueList(
                    prio_channels,
                    current_index=parse_scan_channel_from_tk11(
                        memory.channels, int(scan.prio_2), prio_channels
                    )
                )
            )
            sub_group.append(prio_channel_2)

            scan_list.append(sub_group)

        return scan_list

    @staticmethod
    def get_fm_frequencies_group(memory):
        """Get fm frequencies settings group"""
        fm_frequencies = RadioSettingGroup(
            "fm_frequencies", "FM"
        )

        for i, frequency in enumerate(memory.fm.frequencies):
            setting = RadioSettingValueString(
                0,
                6,
                str(frequency / 10) if frequency != 0xFFFF else "",
                charset=NUMERIC_CHARSET + '.',
                autopad=False
            )
            setting.set_validate_callback(nullable_float_fm_freq_validate)

            name = RadioSetting(
                f"fm_frequency_{i}",
                f"Frequency {i + 1}",
                setting
            )
            fm_frequencies.append(name)

        return fm_frequencies

    @staticmethod
    def get_noaa_decode_addresses_group(memory):
        """Get NOAA decode addresses group"""
        noaa_decode_addresses = RadioSettingGroup(
            "noaa_decode_addresses", "NOAA decode addresses"
        )

        for i, noaa_decode_address in enumerate(memory.noaa_decode_addresses):
            group = RadioSettingSubGroup(
                f"noaa_decode_address_{i}",
                f"NOAA decode address {i + 1}"
            )

            group.append(RadioSetting(
                f"noaa_decode_address_{i}_address",
                "NOAA address",
                RadioSettingValueString(
                    0,
                    6,
                    parse_str_from_tk11(noaa_decode_address.address),
                    autopad=False
                )
            ))

            group.append(RadioSetting(
                f"noaa_decode_address_{i}_information",
                "Information",
                RadioSettingValueString(
                    0,
                    32,
                    parse_str_from_tk11(noaa_decode_address.info),
                    autopad=False
                )
            ))

            noaa_decode_addresses.append(group)

        return noaa_decode_addresses

    def get_settings_group(self, memory):
        settings = RadioSettingGroup("settings", "Settings")

        general = self.general_settings(memory)
        settings.append(general)

        startup = self.startup_settings(memory)
        settings.append(startup)

        buttons = self.buttons_settings(memory)
        settings.append(buttons)

        channel = self.channel_settings(self, memory)
        settings.append(channel)

        match_frequency = self.match_frequency_settings(memory)
        settings.append(match_frequency)

        fm = self.fm_settings(memory)
        settings.append(fm)

        noaa = self.noaa_settings(memory)
        settings.append(noaa)

        return settings

    def get_dtmf_group(self, memory):
        dtmf_settings = RadioSettingGroup(
            "dtmf_settings", "DTMF"
        )

        local_code = RadioSetting(
            "local_code",
            "Local code",
            RadioSettingValueString(
                0,
                3,
                parse_str_from_tk11(memory.general.dtmf_id),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        dtmf_settings.append(local_code)

        kill_code = RadioSetting(
            "kill_code",
            "Kill code",
            RadioSettingValueString(
                0,
                5,
                parse_str_from_tk11(memory.general.dtmf_kill),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        dtmf_settings.append(kill_code)

        revive_code = RadioSetting(
            "revive_code",
            "Revive code",
            RadioSettingValueString(
                0,
                5,
                parse_str_from_tk11(memory.general.dtmf_wakeup),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        dtmf_settings.append(revive_code)

        separate_code = RadioSetting(
            "separate_code",
            "Separate code",
            RadioSettingValueList(
                DTMF_SEPARATE_CODES,
                current_index=DTMF_SEPARATE_CODES.index(
                    parse_str_from_tk11(memory.general.dtmf_separator)
                )
            )
        )
        dtmf_settings.append(separate_code)

        group_code = RadioSetting(
            "group_code",
            "Group code",
            RadioSettingValueList(
                DTMF_GROUP_CODES,
                current_index=DTMF_GROUP_CODES.index(
                    parse_str_from_tk11(memory.general.dtmf_group_code)
                )
            )
        )
        dtmf_settings.append(group_code)

        auto_reset_time = RadioSetting(
            "auto_reset_time",
            "Auto reset time",
            RadioSettingValueInteger(
                5,
                60,
                int(memory.general.dtmf_reset_time)
            )
        )
        dtmf_settings.append(auto_reset_time)

        up_code = RadioSetting(
            "up_code",
            "Up code",
            RadioSettingValueString(
                0,
                14,
                parse_str_from_tk11(memory.general.dtmf_up_code),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        dtmf_settings.append(up_code)

        down_code = RadioSetting(
            "down_code",
            "Down code",
            RadioSettingValueString(
                0,
                14,
                parse_str_from_tk11(memory.general.dtmf_down_code),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        dtmf_settings.append(down_code)

        pre_load_time = RadioSetting(
            "pre_load_time",
            "Pre load time (ms)",
            RadioSettingValueList(
                DTMF_TIMES,
                current_index=DTMF_TIMES.index(
                    str(int(memory.general.dtmf_carry_time))
                )
            )
        )
        dtmf_settings.append(pre_load_time)

        first_code_persist = RadioSetting(
            "first_code_persist",
            "First code persist time (ms)",
            RadioSettingValueList(
                DTMF_TIMES,
                current_index=DTMF_TIMES.index(
                    str(int(memory.general.dtmf_first_code_time))
                )
            )
        )
        dtmf_settings.append(first_code_persist)

        code_persist_time = RadioSetting(
            "code_persist_time",
            "Code persist time (ms)",
            RadioSettingValueList(
                DTMF_TIMES,
                current_index=DTMF_TIMES.index(
                    str(int(memory.general.dtmf_d_code_time))
                )
            )
        )
        dtmf_settings.append(code_persist_time)

        code_continue_time = RadioSetting(
            "code_continue_time",
            "Code continue time (ms)",
            RadioSettingValueList(
                DTMF_TIMES,
                current_index=DTMF_TIMES.index(
                    str(int(memory.general.dtmf_continue_time))
                )
            )
        )
        dtmf_settings.append(code_continue_time)

        code_interval_time = RadioSetting(
            "code_interval_time",
            "Code interval time (ms)",
            RadioSettingValueList(
                DTMF_TIMES,
                current_index=DTMF_TIMES.index(
                    str(int(memory.general.dtmf_interval_time))
                )
            )
        )
        dtmf_settings.append(code_interval_time)

        dtmf_contacts = self.get_dtmf_contacts_group(memory)
        dtmf_settings.append(dtmf_contacts)

        return dtmf_settings

    @staticmethod
    def get_dtmf_contacts_group(memory):
        dtmf_contacts = RadioSettingGroup(
            "dtmf_contacts", "Contacts"
        )

        for i, contact in enumerate(memory.dtmf_contacts):
            sub_group = RadioSettingSubGroup(
                f"dtmf-contact-{i}",
                f"Contact {i + 1}"
            )

            name = RadioSetting(
                f"contact_{i}_name",
                "Name",
                RadioSettingValueString(
                    0,
                    8,
                    parse_str_from_tk11(contact.name),
                    autopad=False
                )
            )
            sub_group.append(name)

            id_code = RadioSetting(
                f"contact_{i}_id_code",
                "Id code",
                RadioSettingValueString(
                    0,
                    3,
                    parse_str_from_tk11(contact.code_id),
                    charset=NUMERIC_CHARSET,
                    autopad=False
                )
            )
            sub_group.append(id_code)

            dtmf_contacts.append(sub_group)

        return dtmf_contacts

    def get_tone5_group(self, memory):
        tone5_settings = RadioSettingGroup(
            "tone5_settings", "5Tone"
        )

        local_code = RadioSetting(
            "local_code",
            "Local code",
            RadioSettingValueString(
                0,
                3,
                parse_str_from_tk11(memory.general.tone5_id),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        tone5_settings.append(local_code)

        kill_code = RadioSetting(
            "kill_code",
            "Kill code",
            RadioSettingValueString(
                0,
                5,
                parse_str_from_tk11(memory.general.tone5_kill),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        tone5_settings.append(kill_code)

        revive_code = RadioSetting(
            "revive_code",
            "Revive code",
            RadioSettingValueString(
                0,
                5,
                parse_str_from_tk11(memory.general.tone5_wakeup),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        tone5_settings.append(revive_code)

        separate_code = RadioSetting(
            "separate_code",
            "Separate code",
            RadioSettingValueList(
                _5TONE_SEPARATE_CODES,
                current_index=_5TONE_SEPARATE_CODES.index(
                    parse_str_from_tk11(memory.general.tone5_separator)
                )
            )
        )
        tone5_settings.append(separate_code)

        group_code = RadioSetting(
            "group_code",
            "Group code",
            RadioSettingValueList(
                _5TONE_GROUP_CODES,
                current_index=_5TONE_GROUP_CODES.index(
                    parse_str_from_tk11(memory.general.tone5_group_code)
                )
            )
        )
        tone5_settings.append(group_code)

        auto_reset_time = RadioSetting(
            "auto_reset_time",
            "Auto reset time",
            RadioSettingValueInteger(
                5,
                60,
                int(memory.general.tone5_reset_time)
            )
        )
        tone5_settings.append(auto_reset_time)

        up_code = RadioSetting(
            "up_code",
            "Up code",
            RadioSettingValueString(
                0,
                14,
                parse_str_from_tk11(memory.general.tone5_up_code),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        tone5_settings.append(up_code)

        down_code = RadioSetting(
            "down_code",
            "Down code",
            RadioSettingValueString(
                0,
                14,
                parse_str_from_tk11(memory.general.tone5_down_code),
                charset=NUMERIC_CHARSET,
                autopad=False
            )
        )
        tone5_settings.append(down_code)

        pre_load_time = RadioSetting(
            "pre_load_time",
            "Pre load time (ms)",
            RadioSettingValueList(
                _5TONE_TIMES,
                current_index=_5TONE_TIMES.index(
                    str(int(memory.general.tone5_carry_time))
                )
            )
        )
        tone5_settings.append(pre_load_time)

        first_code_persist = RadioSetting(
            "first_code_persist",
            "First code persist time (ms)",
            RadioSettingValueList(
                _5TONE_TIMES,
                current_index=_5TONE_TIMES.index(
                    str(int(memory.general.tone5_first_code_time))
                )
            )
        )
        tone5_settings.append(first_code_persist)

        code_persist_time = RadioSetting(
            "code_persist_time",
            "Code persist time (ms)",
            RadioSettingValueList(
                _5TONE_TIMES,
                current_index=_5TONE_TIMES.index(
                    str(int(memory.general.tone5_first_code_time))
                )
            )
        )
        tone5_settings.append(code_persist_time)

        code_continue_time = RadioSetting(
            "code_continue_time",
            "Code continue time (ms)",
            RadioSettingValueList(
                _5TONE_TIMES,
                current_index=_5TONE_TIMES.index(
                    str(int(memory.general.tone5_single_continue_time))
                )
            )
        )
        tone5_settings.append(code_continue_time)

        code_interval_time = RadioSetting(
            "code_interval_time",
            "Code interval time (ms)",
            RadioSettingValueList(
                _5TONE_SINGLE_INTERVAL_TIMES,
                current_index=_5TONE_SINGLE_INTERVAL_TIMES.index(
                    str(int(memory.general.tone5_single_interval_time))
                )
            )
        )
        tone5_settings.append(code_interval_time)

        protocol = RadioSetting(
            "protocol",
            "Protocol",
            RadioSettingValueList(
                _5TONE_PROTOCOLS,
                current_index=int(memory.general.tone5_protocol)
            )
        )
        tone5_settings.append(protocol)

        _5tone_freq_sub_group = self.get_5tone_frequencies_sub_group(memory)
        tone5_settings.append(_5tone_freq_sub_group)

        _5tone_contacts = self.get_5tone_contacts_group(memory)
        tone5_settings.append(_5tone_contacts)

        return tone5_settings

    @staticmethod
    def get_5tone_frequencies_sub_group(memory):
        _5tone_user_frequencies = RadioSettingSubGroup(
            "tone5_user_frequencies", "Frequencies"
        )

        for i in range(len(memory.general.tone5_user_freq) - 1):
            name = RadioSetting(
                f"user_{i}_freq",
                f"User {index_to_char(i + 1)}",
                RadioSettingValueInteger(
                    350,
                    3500,
                    int(memory.general.tone5_user_freq[i])
                )
            )
            _5tone_user_frequencies.append(name)

        return _5tone_user_frequencies

    @staticmethod
    def get_5tone_contacts_group(memory):
        _5tone_contacts = RadioSettingGroup(
            "tone5_contacts", "Contacts"
        )

        for i, contact in enumerate(memory.tone5_contacts):
            sub_group = RadioSettingSubGroup(
                f"tone5-contact-{i}",
                f"Contact {i + 1}"
            )

            name = RadioSetting(
                f"contact_{i}_name",
                "Name",
                RadioSettingValueString(
                    0,
                    8,
                    parse_str_from_tk11(contact.name),
                    autopad=False
                )
            )
            sub_group.append(name)

            id_code = RadioSetting(
                f"contact_{i}_id_code",
                "Id code",
                RadioSettingValueString(
                    0,
                    3,
                    parse_str_from_tk11(contact.code_id),
                    charset=NUMERIC_CHARSET,
                    autopad=False
                )
            )
            sub_group.append(id_code)

            _5tone_contacts.append(sub_group)

        return _5tone_contacts

    def get_channels_name(self):
        """Get a list of valid channels name"""
        return [
            parse_str_from_tk11(c.name)
            for c in self.get_memory_object().channels
            if c.rx_freq is not None and c.rx_freq != 0
        ]

    @staticmethod
    def general_settings(memory):
        """Get general settings"""
        general = RadioSettingGroup("general", "General")

        tot = RadioSetting(
            "tot",
            "TOT (minute)",
            RadioSettingValueList(
                TOT_LIST,
                current_index=int(memory.general.tx_tot)
            )
        )
        general.append(tot)

        vox_level = int(memory.general.vox_lvl)
        vox_sw = int(memory.general.vox_sw)
        vox = RadioSetting(
            "vox",
            "VOX",
            RadioSettingValueList(
                VOX_MODE,
                current_index=vox_level + 1 if vox_sw != 0 else 0
            )
        )
        general.append(vox)

        microphone = RadioSetting(
            "microphone",
            "Microphone",
            RadioSettingValueList(
                MIC_MODE,
                current_index=int(memory.general.mic)
            )
        )
        general.append(microphone)

        beep_tone = RadioSetting(
            "beep_tone",
            "Beep tone",
            RadioSettingValueBoolean(
                bool(memory.general.beep)
            )
        )
        general.append(beep_tone)

        power_on_mode = RadioSetting(
            "power_on_mode",
            "Power ON mode",
            RadioSettingValueList(
                POWER_ON_MODE,
                current_index=int(memory.general.power_save)
            )
        )
        general.append(power_on_mode)

        backlight = RadioSetting(
            "backlight",
            "Backlight",
            RadioSettingValueList(
                BACKLIGHT,
                current_index=int(memory.general.backlight)
            )
        )
        general.append(backlight)

        scan_mode = RadioSetting(
            "scan_mode",
            "Scan mode",
            RadioSettingValueList(
                SCAN_MODE,
                current_index=int(memory.general.scan_mode)
            )
        )
        general.append(scan_mode)

        alarm = RadioSetting(
            "alarm",
            "Alarm",
            RadioSettingValueList(
                ALARM_MODE,
                current_index=int(memory.general.alarm_mode)
            )
        )
        general.append(alarm)

        kill_code = RadioSetting(
            "kill_code",
            "Kill code",
            RadioSettingValueBoolean(
                bool(memory.general.kill_code)
            )
        )
        general.append(kill_code)

        side_tone = RadioSetting(
            "side_tone",
            "Side tone",
            RadioSettingValueBoolean(
                bool(memory.general.dtmf_side_tone)
            )
        )
        general.append(side_tone)

        respond = RadioSetting(
            "respond",
            "Respond",
            RadioSettingValueList(
                RESPOND_MODE,
                current_index=int(memory.general.dtmf_decode_rspn)
            )
        )
        general.append(respond)

        s_bar = RadioSetting(
            "s_bar",
            "SBar",
            RadioSettingValueBoolean(
                bool(memory.general.sbar)
            )
        )
        general.append(s_bar)

        voice = RadioSetting(
            "voice",
            "Voice",
            RadioSettingValueBoolean(bool(memory.general.key_tone_flag))
        )
        general.append(voice)

        mw_sw_agc = RadioSetting(
            "mw_sw_agc",
            "MwSw AGC",
            RadioSettingValueBoolean(bool(memory.general.mw_sw_agc))
        )
        general.append(mw_sw_agc)

        brightness = RadioSetting(
            "brightness",
            "Brightness",
            RadioSettingValueInteger(
                8, 200, int(memory.general.brightness)
            )
        )
        general.append(brightness)

        cw_pitch_freq = RadioSetting(
            "cw_pitch_freq",
            "CW pitch frequency",
            RadioSettingValueInteger(
                400,
                1500,
                int(memory.general.cw_pitch_freq),
                10
            )
        )
        general.append(cw_pitch_freq)

        return general

    @staticmethod
    def buttons_settings(memory):
        """Get buttons settings"""
        buttons = RadioSettingGroup("buttons", "Buttons")

        side_key_1_short_press = RadioSetting(
            "side_key_1_short_press",
            "Side key 1 short press",
            RadioSettingValueList(
                SIDE_KEY_ACTION,
                current_index=int(memory.general.key_short1)
            )
        )
        buttons.append(side_key_1_short_press)

        side_key_1_long_press = RadioSetting(
            "side_key_1_long_press",
            "Side key 1 long press",
            RadioSettingValueList(
                SIDE_KEY_ACTION,
                current_index=int(memory.general.key_long1)
            )
        )
        buttons.append(side_key_1_long_press)

        side_key_2_short_press = RadioSetting(
            "side_key_2_short_press",
            "Side key 2 short press",
            RadioSettingValueList(
                SIDE_KEY_ACTION,
                current_index=int(memory.general.key_short2)
            )
        )
        buttons.append(side_key_2_short_press)

        side_key_2_long_press = RadioSetting(
            "side_key_2_long_press",
            "Side key 2 long press",
            RadioSettingValueList(
                SIDE_KEY_ACTION,
                current_index=int(memory.general.key_long2)
            )
        )
        buttons.append(side_key_2_long_press)

        key_lock = RadioSetting(
            "key_lock",
            "Key lock",
            RadioSettingValueList(
                KEY_LOCK_MODE,
                current_index=int(memory.general.keylock)
            )
        )
        buttons.append(key_lock)

        auto_lock = RadioSetting(
            "auto_lock",
            "Auto lock",
            RadioSettingValueBoolean(memory.general.auto_lock)
        )
        buttons.append(auto_lock)

        return buttons

    @staticmethod
    def startup_settings(memory):
        """Get startup settings"""
        startup = RadioSettingGroup("startup", "Start up")
        device_name = RadioSetting(
            "device_name", "Device name",
            RadioSettingValueString(
                0, 12,
                parse_str_from_tk11(memory.general.device_name),
                autopad=False
            )
        )
        startup.append(device_name)

        start_string_1 = RadioSetting(
            "start_string_1",
            "Start string 1",
            RadioSettingValueString(
                0,
                16,
                parse_str_from_tk11(memory.general.logo_string1),
                autopad=False
            )
        )
        startup.append(start_string_1)

        start_string_2 = RadioSetting(
            "start_string_2",
            "Start string 2",
            RadioSettingValueString(
                0,
                16,
                parse_str_from_tk11(memory.general.logo_string2),
                autopad=False
            )
        )
        startup.append(start_string_2)

        boot_screen = RadioSetting(
            "boot_screen",
            "Boot screen",
            RadioSettingValueList(
                BOOT_SCREEN_MODE,
                current_index=int(memory.general.power_on_screen_mode)
            )
        )
        startup.append(boot_screen)

        a_display_index = int(memory.channels_idx.a_id)
        if a_display_index < CHANNELS_COUNT:
            a_display_index = A_DISPLAY_SPECIAL_COUNT + a_display_index
        else:
            a_display_index = a_display_index - CHANNELS_COUNT

        b_display_index = int(memory.channels_idx.b_id)
        if b_display_index < CHANNELS_COUNT:
            b_display_index = B_DISPLAY_SPECIAL_COUNT + b_display_index
        else:
            b_display_index = b_display_index - CHANNELS_COUNT

        a_display = RadioSetting(
            "a_display",
            "A display",
            RadioSettingValueList(A_DISPLAY, current_index=a_display_index)
        )
        startup.append(a_display)

        b_display = RadioSetting(
            "b_display",
            "B display",
            RadioSettingValueList(B_DISPLAY, current_index=b_display_index)
        )
        startup.append(b_display)

        return startup

    @staticmethod
    def channel_settings(radio, memory):
        """Get channel settings"""
        channel = RadioSettingGroup("channel", "Channel")

        main_channel = RadioSetting(
            "main_channel",
            "Main channel",
            RadioSettingValueList(
                CHANNELS,
                current_index=int(memory.general.channel_ab)
            )
        )
        channel.append(main_channel)

        a_rx_volume_balance = RadioSetting(
            "a_rx_volume_balance",
            "Volume RX balance A",
            RadioSettingValueList(
                VOLUME,
                current_index=int(memory.general.chn_A_volume)
            )
        )
        channel.append(a_rx_volume_balance)

        b_rx_volume_balance = RadioSetting(
            "b_rx_volume_balance",
            "Volume RX balance B",
            RadioSettingValueList(
                VOLUME,
                current_index=int(memory.general.chn_B_volume)
            )
        )
        channel.append(b_rx_volume_balance)

        vfo_mode = RadioSetting(
            "vfo_mode",
            "VFO Mode",
            RadioSettingValueBoolean(memory.general.freq_mode)
        )
        channel.append(vfo_mode)

        channel_display_mode = RadioSetting(
            "channel_display_mode",
            "Channel display mode",
            RadioSettingValueList(
                CHANNEL_DISPLAY_MODE,
                current_index=int(memory.general.channel_display_mode)
            )
        )
        channel.append(channel_display_mode)

        repeater_tail_tone = RadioSetting(
            "repeater_tail_tone",
            "Repeater tail tone",
            RadioSettingValueList(
                REPEATER_TAIL_TONE,
                current_index=int(memory.general.repeater_tail)
            )
        )
        channel.append(repeater_tail_tone)

        call_ch = int(memory.general.call_ch)
        call_channel = RadioSetting(
            "call_channel",
            "Call channel",
            RadioSettingValueList(
                ["Null"] + radio.get_channels_name(),
                current_index=0
                if memory.channels_usage[call_ch].flag > len(TX_FREQUENCIES)
                else call_ch
            )
        )
        channel.append(call_channel)

        tail_tone = RadioSetting(
            "tail_tone",
            "Tail tone",
            RadioSettingValueBoolean(memory.general.tail_tone))
        channel.append(tail_tone)

        dual_receive = RadioSetting(
            "dual_receive",
            "Dual receive",
            RadioSettingValueBoolean(memory.general.dual_watch))
        channel.append(dual_receive)

        remind_eot = RadioSetting(
            "remind_eot",
            "Remind end of talk",
            RadioSettingValueList(
                REMIND_END_OF_TALK,
                current_index=int(memory.general.roger_tone)
            )
        )
        channel.append(remind_eot)

        denoise = RadioSetting(
            "denoise",
            "Denoise",
            RadioSettingValueList(
                DENOISE,
                current_index=int(memory.general.denoise_lvl) + 1
            )
        )
        channel.append(denoise)

        transpositional = RadioSetting(
            "transpositional",
            "Transpositional",
            RadioSettingValueList(
                TRANSPOSITIONAL,
                current_index=int(memory.general.transpositional_lvl) + 1)
        )
        channel.append(transpositional)

        return channel

    @staticmethod
    def match_frequency_settings(memory):
        """Get match frequency settings"""
        match_frequency = RadioSettingGroup(
            "match_frequency", "Match frequency"
        )

        frequency_meter_tot = RadioSetting(
            "frequency_meter_tot",
            "Frequency meter tot[s]",
            RadioSettingValueInteger(
                8,
                32,
                int(memory.general.match_tot)
            )
        )
        match_frequency.append(frequency_meter_tot)

        frequency_meter_mode = RadioSetting(
            "frequency_meter_mode",
            "Frequency meter mode",
            RadioSettingValueList(
                FREQUENCY_METER_MODES,
                current_index=int(memory.general.match_qt_mode)
            )
        )
        match_frequency.append(frequency_meter_mode)

        dcs = RadioSetting(
            "dcs",
            "DCS",
            RadioSettingValueList(
                DCS_MODES,
                current_index=int(memory.general.match_dcs_bit)
            )
        )
        match_frequency.append(dcs)

        match_threshold = RadioSetting(
            "match_threshold",
            "QT threshold",
            RadioSettingValueInteger(
                10,
                200,
                int(memory.general.match_threshold)
            )
        )
        match_frequency.append(match_threshold)

        return match_frequency

    @staticmethod
    def fm_settings(memory):
        """Get FM settings"""
        fm = RadioSettingGroup("fm", "FM")

        vfo_freq_val = int(memory.fm.vfo_frequency) / 10
        vfo_frequency = vfo_freq_val if (76 <= vfo_freq_val <= 108) else 76

        vfo = RadioSetting(
            "vfo",
            "VFO",
            RadioSettingValueFloat(
                76,
                108,
                vfo_frequency, precision=1
            )
        )
        fm.append(vfo)

        mode = RadioSetting(
            "mode",
            "Mode",
            RadioSettingValueList(
                ["VFO mode", "MR mode"],
                current_index=int(memory.fm.memory_vfo_flag)
            )
        )
        fm.append(mode)

        channel = RadioSetting(
            "channel",
            "Channel",
            RadioSettingValueList(
                [str(i) for i in range(1, 33)],
                current_index=int(memory.fm.channel_id)
            )
        )
        fm.append(channel)

        return fm

    @staticmethod
    def noaa_settings(memory):
        """Get NOAA settings"""
        noaa = RadioSettingGroup("noaa", "NOAA")

        noaa_same_decode = RadioSetting(
            "noaa_same_decode",
            "NOAA SAME decode",
            RadioSettingValueList(
                ["Null", "1050Hz", "SAME decode"],
                current_index=int(memory.general.noaa_same_decode)
            )
        )
        noaa.append(noaa_same_decode)

        noaa_same_event = RadioSetting(
            "noaa_same_event",
            "NOAA SAME event",
            RadioSettingValueList(
                ["Default", "All open", "All off", "User"],
                current_index=int(memory.general.noaa_same_event)
            )
        )
        noaa.append(noaa_same_event)

        noaa_same_address = RadioSetting(
            "noaa_same_address",
            "NOAA SAME address",
            RadioSettingValueList(
                ["Single address", "Multiple address", "Any address"],
                current_index=int(memory.general.noaa_same_address)
            )
        )
        noaa.append(noaa_same_address)

        noaa_sq = RadioSetting(
            "noaa_sq",
            "NOAA SAME address",
            RadioSettingValueInteger(
                0,
                9,
                int(memory.general.noaa_sq)
            )
        )
        noaa.append(noaa_sq)

        noaa_scan = RadioSetting(
            "noaa_scan",
            "NOAA search",
            RadioSettingValueList(
                ["Manual", "Auto"],
                current_index=int(memory.general.noaa_scan)
            )
        )
        noaa.append(noaa_scan)

        noaa_same_event_control = RadioSettingSubGroup(
            "noaa_same_event_control",
            "NOAA SAME event control"
        )

        for i, (code, label) in enumerate(NOAA_SAME_EVENTS):
            group = RadioSettingSubGroup(
                f"noaa_same_event_control{i}",
                f"NOAA message {i}"
            )

            code_value = RadioSettingValueString(
                0,
                3,
                code
            )
            code_value.set_mutable(False)

            group.append(RadioSetting(
                f"noaa_same_event_control{i}_code",
                "Code",
                code_value
            ))

            label_value = RadioSettingValueString(
                0,
                100,
                label
            )
            label_value.set_mutable(False)

            group.append(RadioSetting(
                f"noaa_same_event_control{i}_label",
                "Label",
                label_value
            ))

            group.append(RadioSetting(
                f"noaa_same_event_control{i}_checked",
                "",
                RadioSettingValueBoolean(
                    bool(memory.noaa_same_events_control[i].value)
                )
            ))

            noaa_same_event_control.append(group)

        noaa.append(noaa_same_event_control)

        return noaa

    def get_memory_object(self):
        """Get memory object"""
        return self._memobj

    def sync_in(self):
        """Download radio data"""
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        """Upload radio data"""
        do_upload(self)

    def process_mmap(self):
        """Convert the raw byte array into a memory object structure"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        """Return a raw representation of the memory object"""
        return repr(self._memobj.channels[number - 1])

    def get_memory(self, number):
        """Extract a high-level memory object from the low-level memory map"""
        channel = self._memobj.channels[number - 1]

        memory = chirp_common.Memory()
        memory.number = number

        if channel.rx_freq is None or channel.rx_freq == 0:
            memory.empty = True
            return memory

        try:
            memory.power = Power(channel.power).level
        except ValueError:
            memory.power = Power.HIGH.level

        memory.freq = int(channel.rx_freq) * 10
        memory.offset = int(channel.freq_diff) * 10
        memory.name = parse_str_from_tk11(channel.name)

        if channel.mode == Mode.FM.value:
            if channel.band & 15 == 0:
                memory.mode = Mode.FM.name
            elif channel.band & 15 == 1:
                memory.mode = Mode.NFM.name
        else:
            memory.mode = Mode(channel.mode).name

        if memory.offset == 0:
            memory.duplex = FrequencyDirection.EQUAL.label
        else:
            try:
                duplex = FrequencyDirection(int(channel.freq_dir)).label
                memory.duplex = duplex

                if duplex == FrequencyDirection.EQUAL.label:
                    memory.offset = 0
            except ValueError:
                memory.offset = 0
                memory.duplex = FrequencyDirection.EQUAL.label
                LOG.error(
                    "Unknown frequency direction %s",
                    channel.freq_dir
                )

        if channel.tx_qt_type == QTType.NONE.value == channel.rx_qt_type:
            memory.tmode = ""
        elif (channel.tx_qt_type == QTType.CTCSS.value and
              channel.rx_qt_type == QTType.NONE.value):
            memory.tmode = "Tone"

            tx_tone = convert_tone(int(channel.tx_qt)) / 10
            if not is_tone_valid(tx_tone):
                tx_tone = VALID_TONES[0]

            memory.rtone = tx_tone
        elif (channel.tx_qt_type == QTType.CTCSS.value and
              channel.rx_qt_type == QTType.CTCSS.value and
              channel.tx_qt == channel.rx_qt):
            memory.tmode = "TSQL"

            tx_tone = convert_tone(int(channel.tx_qt)) / 10
            if not is_tone_valid(tx_tone):
                tx_tone = VALID_TONES[0]

            memory.ctone = tx_tone
            memory.rtone = tx_tone
        elif (channel.tx_qt_type in (QTType.NDCS.value, QTType.IDCS.value) and
              channel.rx_qt_type in (QTType.NDCS.value, QTType.IDCS.value) and
              channel.tx_qt == channel.rx_qt):
            tx_dtcs = int(dtcs_to_chirp(int(channel.tx_qt)))

            tx_polarity = "N" \
                if channel.tx_qt_type == QTType.NDCS.value else "R"
            rx_polarity = "N" \
                if channel.rx_qt_type == QTType.NDCS.value else "R"
            memory.dtcs_polarity = tx_polarity + rx_polarity

            memory.tmode = "DTCS"
            memory.dtcs = tx_dtcs
        else:
            tx_mode = ""
            rx_mode = ""

            tx_polarity = "N"
            rx_polarity = "N"

            if channel.tx_qt_type == QTType.CTCSS.value:
                tx_mode = "Tone"

                tx_tone = convert_tone(int(channel.tx_qt)) / 10
                if not is_tone_valid(tx_tone):
                    tx_tone = VALID_TONES[0]

                memory.rtone = tx_tone
            elif channel.tx_qt_type in (QTType.NDCS.value, QTType.IDCS.value):
                tx_mode = "DTCS"
                tx_polarity = "N" \
                    if channel.tx_qt_type == QTType.NDCS.value else "R"
                memory.dtcs = int(dtcs_to_chirp(int(channel.tx_qt)))

            if channel.rx_qt_type == QTType.CTCSS.value:
                rx_mode = "Tone"

                rx_tone = convert_tone(int(channel.rx_qt)) / 10
                if not is_tone_valid(rx_tone):
                    rx_tone = VALID_TONES[0]

                memory.ctone = rx_tone
            elif channel.rx_qt_type in (QTType.NDCS.value, QTType.IDCS.value):
                rx_mode = "DTCS"
                rx_polarity = "N" \
                    if channel.rx_qt_type == QTType.NDCS.value else "R"
                memory.rx_dtcs = int(dtcs_to_chirp(int(channel.rx_qt)))

            memory.tmode = "Cross"

            memory.cross_mode = f"{tx_mode}->{rx_mode}"
            memory.dtcs_polarity = tx_polarity + rx_polarity

        memory.extra = RadioSettingGroup("Extra", "extra")

        msw = RadioSetting(
            "msw",
            "MSW",
            RadioSettingValueList(
                MSW_LIST,
                current_index=int(channel.band >> 4)
            )
        )
        memory.extra.append(msw)

        squelch = RadioSetting(
            "squelch",
            "Squelch",
            RadioSettingValueList(
                SQUELCH_LIST,
                current_index=int(channel.sq)
            )
        )
        memory.extra.append(squelch)

        scan_list = RadioSetting(
            "scan_list",
            "Scan List",
            RadioSettingValueList(
                AVAILABLE_SCAN_LIST,
                current_index=int(channel.scan_list) + 1
                if channel.scan_list != 0xFF else 0
            )
        )
        memory.extra.append(scan_list)

        encrypt = RadioSetting(
            "encrypt",
            "Encrypt",
            RadioSettingValueList(
                ENCRYPT_LIST,
                current_index=int(channel.encrypt)
            )
        )
        memory.extra.append(encrypt)

        busy_lock = RadioSetting(
            "busy_lock",
            "Busy lock",
            RadioSettingValueBoolean(bool(channel.busy)))
        memory.extra.append(busy_lock)

        signaling_decode = RadioSetting(
            "signaling_decode",
            "Signaling decode",
            RadioSettingValueBoolean(bool(channel.dtmf_decode_flag)))
        memory.extra.append(signaling_decode)

        signal = RadioSetting(
            "signal",
            "Signal",
            RadioSettingValueList(
                SIGNAL_MODE,
                current_index=int(channel.signal)
            )
        )
        memory.extra.append(signal)

        rs = RadioSetting(
            "ptt_id",
            "PTT ID",
            RadioSettingValueList(
                PTT_ID_MODES,
                current_index=int(channel.ptt_id)
            )
        )
        memory.extra.append(rs)

        return memory

    def set_memory(self, memory):
        """Store details about a high-level memory to the memory map"""
        chan_index = memory.number - 1

        frequency_range = get_channel_frequency_range(
            int(memory.freq)
        )
        self._memobj.channels_usage[chan_index].flag = frequency_range

        channel = self._memobj.channels[chan_index]

        if memory.empty:
            channel.set_raw(b"\x00" * 64)
            return

        channel.rx_freq = int(memory.freq / 10)

        is_mode_nfm = memory.mode == Mode.NFM.name

        # 0 = 25K
        # 1 = 12.5K
        band_index = 1 if is_mode_nfm else 0
        msw_index = int(
            self.get_extra_or_default(memory, "msw", 0)
        )

        channel.mode = Mode.FM.value \
            if is_mode_nfm else Mode[memory.mode].value

        channel.band = band_index | (msw_index << 4)

        if memory.power is None:
            channel.power = Power.LOW.level
        else:
            channel.power = Power[str(memory.power).upper()].value

        if memory.name is not None:
            channel.name = parse_str_to_tk11(memory.name, 16)

        match memory.duplex:
            case FrequencyDirection.EQUAL.label:
                channel.freq_dir = FrequencyDirection.EQUAL.value
                channel.freq_diff = 0
            case FrequencyDirection.ADD.label:
                channel.freq_dir = FrequencyDirection.ADD.value
                channel.freq_diff = int(memory.offset / 10)
            case FrequencyDirection.REMOVE.label:
                channel.freq_dir = FrequencyDirection.REMOVE.value
                channel.freq_diff = int(memory.offset / 10)

        scan_list = int(
            self.get_extra_or_default(memory, "scan_list", "0")
        )

        channel.scan_list = 0xFF if scan_list == 0 else scan_list - 1

        channel.encrypt = int(
            self.get_extra_or_default(memory, "encrypt", 0)
        )

        channel.sq = int(
            self.get_extra_or_default(memory, "squelch", 4)
        )

        channel.busy = int(
            self.get_extra_or_default(memory, "busy_lock", 0)
        )

        channel.dtmf_decode_flag = int(
            self.get_extra_or_default(memory, "signaling_decode", 0)
        )

        channel.signal = int(
            self.get_extra_or_default(memory, "signal", 0)
        )

        channel.ptt_id = int(
            self.get_extra_or_default(memory, "ptt_id", 0)
        )

        match memory.tmode:
            case "":
                channel.tx_qt_type = QTType.NONE.value
                channel.tx_qt = 0

                channel.rx_qt_type = QTType.NONE.value
                channel.rx_qt = 0
            case "Tone":
                channel.tx_qt_type = QTType.CTCSS.value
                channel.tx_qt = convert_tone(int(memory.rtone * 10))

                channel.rx_qt_type = QTType.NONE.value
                channel.rx_qt = 0
            case "TSQL":
                tone = convert_tone(int(memory.ctone * 10))

                channel.tx_qt_type = QTType.CTCSS.value
                channel.tx_qt = tone

                channel.rx_qt_type = QTType.CTCSS.value
                channel.rx_qt = tone
            case "DTCS":
                tx_polarity = memory.dtcs_polarity[0].upper()
                rx_polarity = memory.dtcs_polarity[1].upper()

                channel.tx_qt_type = QTType.NDCS.value \
                    if tx_polarity == "N" else QTType.IDCS.value
                channel.rx_qt_type = QTType.NDCS.value \
                    if rx_polarity == "N" else QTType.IDCS.value

                channel.tx_qt = dtcs_to_tk11(memory.dtcs)
                channel.rx_qt = dtcs_to_tk11(memory.dtcs)
            case "Cross":
                tx_mode, rx_mode = memory.cross_mode.split("->", 1)

                if tx_mode == "Tone":
                    channel.tx_qt_type = QTType.CTCSS.value
                    channel.tx_qt = convert_tone(int(memory.rtone * 10))
                elif tx_mode == "DTCS":
                    tx_polarity = memory.dtcs_polarity[0].upper()
                    channel.tx_qt_type = QTType.NDCS.value \
                        if tx_polarity == "N" else QTType.IDCS.value
                    channel.tx_qt = dtcs_to_tk11(memory.dtcs)

                if rx_mode == "Tone":
                    channel.rx_qt_type = QTType.CTCSS.value
                    channel.rx_qt = convert_tone(int(memory.ctone * 10))
                elif rx_mode == "DTCS":
                    rx_polarity = memory.dtcs_polarity[1].upper()
                    channel.rx_qt_type = QTType.NDCS.value \
                        if rx_polarity == "N" else QTType.IDCS.value
                    channel.rx_qt = dtcs_to_tk11(memory.rx_dtcs)

        self.edited_channels.append(memory.number - 1)

    @staticmethod
    def get_extra_or_default(memory, key, default):
        """Get extra value or default value"""
        if key in memory.extra and memory.extra[key] is not None:
            return memory.extra[key].value

        return default
