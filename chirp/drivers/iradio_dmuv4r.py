# Copyright 2026
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

import csv
import io
import logging
import os

from chirp import chirp_common, directory, errors, memmap
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettingValueBoolean,
    RadioSettingValueFloat,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
    RadioSettingSubGroup,
    RadioSettings,
)
from chirp.drivers.iradio_common import enter_programming_mode, \
    exit_programming_mode


LOG = logging.getLogger(__name__)

BLOCK_SIZE = 1024
# Firmware command 0x34 sub-command 0x10 enters the "PC Programing" screen;
# sub-command 0xEE exits it. Block reads and writes use separate 0x52/0x90+
# frames after this handshake.
READ_MAGIC = b"\x34\x52\x05\x10\x9B"
END_MAGIC = b"\x34\x52\x05\xEE\x79"
ACK = b"\x06"

NAME_LEN = 16
CHANNEL_COUNT = 1024
CHANNEL_RECORD_SIZE = 48
CONTACT_COUNT = 10000
CONTACT_RECORD_SIZE = 21
GROUP_COUNT = 250
GROUP_RECORD_SIZE = 80
GROUP_MEMBERS = 32
ENCRYPTION_COUNT = 256
ENCRYPTION_SELECTOR_COUNT = ENCRYPTION_COUNT + 1
ENCRYPTION_RECORD_SIZE = 48
ENCRYPTION_TYPES = ["ARC", "AES-128", "AES-256"]
ENCRYPTION_KEY_LENGTHS = [5, 16, 32]
ZONE_COUNT = 250
ZONE_MEMBERS = 250
ZONE_TABLE_OFFSET = 0
LEGACY_ZONE_TABLE_OFFSET = 8 * BLOCK_SIZE
ZONE_RECORD_SIZE = 520
# Newer OEM CPS DM550_NOLCD writes zones with opcode 0x93 after the VFO/CFG2
# block. Earlier 0x92 probes targeted the wrong section.
ZONE_WRITES_ENABLED = True
SMS_PRESET_COUNT = 16
SMS_RECORD_SIZE = 256
SMS_TEXT_LEN = 160
FM_COUNT = 80
FM_RECORD_SIZE = 48
FM_ALIAS_OFFSET = 30
FM_ALIAS_LENGTH = 16
FM_RANGE_CHOICES = ["64-108 MHz", "2-30 MHz", "520-1710 KHz", "153-279 KHz"]
FM_DEMOD_CHOICES = ["AM", "LSB", "USB", "CW"]
FM_STEP_CHOICES = ["1K", "5K", "9K", "10K"]
FM_BW_CHOICES = ["0.5 K", "1.0 K", "1.2 K", "2.2 K", "3.0 K", "4.0 K"]
FM_AGC_CHOICES = ["AGC", "0"] + ["-%d" % value for value in range(1, 38)]
APO_SECONDS_MIN = 30
APO_SECONDS_MAX = (9999 * 3600) + (59 * 60) + 59
STARTUP_IMAGE_PAYLOAD_SIZE = 4096
STARTUP_IMAGE_HEX_MAX_LEN = STARTUP_IMAGE_PAYLOAD_SIZE * 2
GLOBAL_CONTACT_CSV_PATH_LEN = 512
LOCAL_CONTACT_CSV_PATH_LEN = 512
GLOBAL_CONTACT_MAX_PAYLOAD = 29360124
FM_LIST_FIELDS = {
    "fm_range": (0, FM_RANGE_CHOICES),
    "fm_sw_demod": (3, FM_DEMOD_CHOICES),
    "fm_sw_step": (4, FM_STEP_CHOICES),
    "fm_sw_bw": (5, FM_BW_CHOICES),
    "fm_sw_agc": (6, FM_AGC_CHOICES),
    "fm_mw_demod": (12, FM_DEMOD_CHOICES),
    "fm_mw_step": (13, FM_STEP_CHOICES),
    "fm_mw_bw": (14, FM_BW_CHOICES),
    "fm_mw_agc": (15, FM_AGC_CHOICES),
    "fm_lw_demod": (21, FM_DEMOD_CHOICES),
    "fm_lw_step": (22, FM_STEP_CHOICES),
    "fm_lw_bw": (23, FM_BW_CHOICES),
    "fm_lw_agc": (24, FM_AGC_CHOICES),
}
FM_FREQ_FIELDS = {
    "fm_freq": (1, 10),
    "fm_sw_freq": (9, 1000),
    "fm_mw_freq": (18, 1),
    "fm_lw_freq": (27, 1),
}
FM_BFO_FIELDS = {
    "fm_sw_bfo": 7,
    "fm_mw_bfo": 16,
    "fm_lw_bfo": 25,
}
FM_UI_FIELDS = (
    ("list", "fm_range", "Range"),
    ("broadcast_freq", "fm_freq", "Frequency"),
    ("alias", "fm_alias", "Alias"),
    ("list", "fm_sw_demod", "SW Demod"),
    ("freq", "fm_sw_freq", "SW Frequency MHz", 3, 8),
    ("list", "fm_sw_step", "SW Step"),
    ("list", "fm_sw_bw", "SW Bandwidth"),
    ("list", "fm_sw_agc", "SW AGC"),
    ("bfo", "fm_sw_bfo", "SW BFO"),
    ("list", "fm_mw_demod", "MW Demod"),
    ("freq", "fm_mw_freq", "MW Frequency kHz", 0, 6),
    ("list", "fm_mw_step", "MW Step"),
    ("list", "fm_mw_bw", "MW Bandwidth"),
    ("list", "fm_mw_agc", "MW AGC"),
    ("bfo", "fm_mw_bfo", "MW BFO"),
    ("list", "fm_lw_demod", "LW Demod"),
    ("freq", "fm_lw_freq", "LW Frequency kHz", 0, 6),
    ("list", "fm_lw_step", "LW Step"),
    ("list", "fm_lw_bw", "LW Bandwidth"),
    ("list", "fm_lw_agc", "LW AGC"),
    ("bfo", "fm_lw_bfo", "LW BFO"),
)
CONTACT_TYPES = ["Disabled", "Private", "Group", "All Call"]
LOCAL_CONTACT_IMPORT_MODES = ["Disabled", "Replace", "Append"]
LOCAL_CONTACT_TYPE_ALIASES = {
    "private": 0,
    "individual": 0,
    "individual call": 0,
    "single": 0,
    "single call": 0,
    "group": 1,
    "group call": 1,
    "all": 2,
    "all call": 2,
}
CONTACT_UI_MIN_SLOTS = 256
CSV_CHARSET = "0123456789, "
HEX_CHARSET = "0123456789ABCDEFabcdef"
SIGNALING_ID_MASK = 0x00FFFFFF
CFG2_OFFSET = 96
CHANNEL_RXTX_CHOICES = ["RX+TX", "Only RX", "Only TX"]
CHANNEL_ID_SELECT_CHOICES = ["Radio ID", "Channel ID"]
CHANNEL_DMR_MODE_CHOICES = ["Dual Slot Off", "Dual Slot On"]
CHANNEL_CALL_PRIORITY_CHOICES = ["Allow TX", "Channel Free", "Color Code Idle"]
CHANNEL_TX_PRIORITY_CHOICES = ["Allow TX", "Channel Free", "CTC/DCS Idle"]
CHANNEL_CTDCS_SELECT_CHOICES = [
    "Standard", "Encrypt 1", "Encrypt 2", "Encrypt 3", "Mute Code",
]
CHANNEL_AMFM_CHOICES = ["FM", "AM", "SSB"]
CHANNEL_TAIL_TONE_CHOICES = [
    "Off", "55Hz No Shift", "120 Shift", "180 Shift", "240 Shift",
]
CHANNEL_BAND_CHOICES = ["Wide", "Narrow"]
CHANNEL_SCRAMBLE_CHOICES = ["Off"] + [str(value) for value in range(1, 9)]
SPECIAL_MEMORIES = {
    "VFO-A": -2,
    "VFO-B": -1,
}
SPECIAL_MEMORIES_REV = {value: key for key, value in SPECIAL_MEMORIES.items()}

OFFSET_CFG = 0
OFFSET_VFO = OFFSET_CFG + BLOCK_SIZE
OFFSET_ALL = OFFSET_CFG + 4096
OFFSET_ZONE = OFFSET_ALL + (CHANNEL_COUNT * CHANNEL_RECORD_SIZE)
OFFSET_CONTACT = OFFSET_ZONE + 131072
OFFSET_GROUP = OFFSET_CONTACT + 212992
OFFSET_ENCRYPT = OFFSET_GROUP + 20480
OFFSET_SMS = OFFSET_ENCRYPT + 12288
OFFSET_FM = OFFSET_SMS + 102400
OFFSET_STARTUP_IMAGE = OFFSET_FM + 4096
OFFSET_GLOBAL_CONTACTS = OFFSET_STARTUP_IMAGE + 1 + STARTUP_IMAGE_PAYLOAD_SIZE
MEM_SIZE = OFFSET_GLOBAL_CONTACTS + 1 + GLOBAL_CONTACT_CSV_PATH_LEN
COMPACT_MEM_SIZE = OFFSET_STARTUP_IMAGE
LEGACY_COMPACT_MEM_SIZE = 508928
MATCH_MODEL_SIZES = (LEGACY_COMPACT_MEM_SIZE, COMPACT_MEM_SIZE, MEM_SIZE)

SEGMENTS = {
    "cfg": (OFFSET_CFG, 4096),
    # The newer OEM stores VFO A/B plus CFG_2 in flash block 112. Keep it in
    # unused cfg padding to avoid changing the existing compact image size.
    "vfo": (OFFSET_VFO, 1024),
    "all": (OFFSET_ALL, CHANNEL_COUNT * CHANNEL_RECORD_SIZE),
    "zone": (OFFSET_ZONE, 131072),
    "contact": (OFFSET_CONTACT, 212992),
    "group": (OFFSET_GROUP, 20480),
    "encrypt": (OFFSET_ENCRYPT, 12288),
    "sms": (OFFSET_SMS, 102400),
    "fm": (OFFSET_FM, 4096),
    # Not part of the normal read plan. This stores an optional OEM 0x9A
    # power-on image payload plus a one-byte enable flag for image files.
    "startup_image": (OFFSET_STARTUP_IMAGE, 1 + STARTUP_IMAGE_PAYLOAD_SIZE),
    # Separate OEM 0xA4 global-contact database writer. The database can be
    # tens of MiB, so the image stores only an upload flag and source CSV path.
    "global_contacts": (
        OFFSET_GLOBAL_CONTACTS, 1 + GLOBAL_CONTACT_CSV_PATH_LEN),
}

READ_PLAN = (
    (0x0008, "cfg", 1),
    (0x0010, "all", 48),
    (0x0070, "vfo", 1),
    (0x0078, "zone", 128),
    (0x0178, "contact", 208),
    (0x0318, "group", 20),
    (0x0340, "encrypt", 12),
    (0x0358, "sms", 100),
    (0x03C0, "fm", 4),
)

# Upload opcodes are relative writers. The second tuple item records the
# firmware's first 4 KiB flash sector for maintainers; the wire frame address
# still starts at zero for each opcode.
UPLOAD_PLAN = (
    (0x90, 0x002, "cfg", 1),
    (0x91, 0x004, "all", 48),
    (0x92, 0x01C, "vfo", 1),
    (0x93, 0x01E, "zone", 128),
    (0x94, 0x05E, "contact", 208),
    (0x95, 0x0C6, "group", 20),
    (0x96, 0x0D0, "encrypt", 12),
    # Firmware opcode 0x97 erases/writes only sector 0x0D6, so only the
    # 16 editable preset SMS records are uploaded, not the 100-block
    # SMS/history area read from the radio.
    (0x97, 0x0D6, "sms", 4),
    (0x98, 0x0F0, "fm", 4),
)

SAFE_UPLOAD_PLAN = UPLOAD_PLAN

POWER_LEVELS = [
    # The OEM CPS exposes only Low/High. Absolute RF watts vary by band/model
    # and are not encoded in the channel record.
    chirp_common.PowerLevel("Low"),
    chirp_common.PowerLevel("High"),
]

VALID_BANDS = [
    (136000000, 174000000),
    (400000000, 480000000),
]

LIST_ON_OFF = ["Off", "On"]
LIST_YES_NO = ["No", "Yes"]
LIST_GPS_BAUD = [
    "4800", "9600", "14400", "19200", "38400",
    "56000", "57600", "115200", "128000", "256000",
]
LIST_GPS_MODE = ["Off", "On", "Auto"]
LIST_GPS_RECORD_MODE = ["Off", "Auto", "Manual"]
TIMER_CHOICES = [
    "Off", "5", "10", "15", "30", "45", "60", "75", "90", "105",
    "120", "135", "150", "165", "180", "195", "210", "225", "240",
    "255", "270", "285", "300", "315", "330", "345", "360", "375",
    "390", "405", "420", "435", "450", "465", "480", "495", "510",
    "525", "540", "555", "570", "585", "600",
]
MS100_CHOICES = ["0"] + ["%dms" % value for value in range(100, 2100, 100)]
MS30_CHOICES = ["%dms" % value for value in range(30, 210, 10)]
SCAN_COUNT_CHOICES = [str(value) for value in range(31)]
LOCK_RANGE_CHOICES = ["Unlock", "RX Only", "Lock"]
TALKAROUND_CHOICES = ["Off", "Talkaround", "Reverse Freq"]
MAIN_PTT_CHOICES = ["Area A", "Main Area"]
ALARM_TYPE_CHOICES = ["Local", "Remote", "Local+Remote"]
TX_PRIORITY_CHOICES = ["Edit", "Busy"]
SCAN_MODE_CHOICES = ["CO", "TO", "SE"]
SCAN_RETURN_CHOICES = ["Original CH", "Current CH"]
ROGER_CHOICES = ["Off", "Roger 1", "Roger 2", "MDC1200"]
CALL_END_BEEP_CHOICES = ["Off", "Roger 1", "Roger 2"]
DETECT_RANGE_CHOICES = [
    "18-64MHz", "64-136MHz", "136-174MHz", "174-240MHz",
    "240-320MHz", "320-400MHz", "400-480MHz", "480-560MHz",
    "560-620MHz", "840-920MHz", "920-1000MHz",
]
SMS_FORMAT_CHOICES = ["Hytera", "Motorola"]
SMS_FONT_CHOICES = ["Unicode", "GBK"]
GROUP_DISPLAY_CHOICES = ["Show Caller Info", "Show Called Info"]
DTMF_MODE_CHOICES = ["Off", "TX Begin", "TX End", "Begin And End"]
DTMF_SELECT_CHOICES = ["DTMF-%02d" % value for value in range(1, 17)]
LIST_BOOL_FIELDS = {
    16: "startup_picture",
    19: "startup_beep",
    20: "startup_label",
    27: "startup_password_enabled",
    105: "auto_power_off",
}
CONFIG_LIST_FIELDS = {
    92: ("voice_prompt", LIST_ON_OFF),
    93: ("key_beep", LIST_ON_OFF),
    95: ("lock_timer", TIMER_CHOICES),
    96: ("led_enabled", LIST_ON_OFF),
    97: ("lcd_brightness", [str(x) for x in range(5)]),
    98: ("led_timer", TIMER_CHOICES),
    99: ("save_mode", ["Off", "1:1", "1:2", "1:3"]),
    101: ("menu_timer", TIMER_CHOICES),
    103: ("talkaround", TALKAROUND_CHOICES),
    104: ("alarm_type", ALARM_TYPE_CHOICES),
    126: ("tx_priority", TX_PRIORITY_CHOICES),
    127: ("main_ptt", MAIN_PTT_CHOICES),
    142: ("lock_type_1", LOCK_RANGE_CHOICES),
    147: ("lock_type_2", LOCK_RANGE_CHOICES),
    152: ("lock_type_3", LOCK_RANGE_CHOICES),
    157: ("lock_type_4", LOCK_RANGE_CHOICES),
    163: ("scan_mode", SCAN_MODE_CHOICES),
    164: ("scan_return", SCAN_RETURN_CHOICES),
    165: ("scan_dwell", SCAN_COUNT_CHOICES),
    166: ("scan_interval", SCAN_COUNT_CHOICES),
    169: ("refresh_delay", MS100_CHOICES),
    234: ("display_id_digits", ["6 digits", "8 digits"]),
    267: ("tx_start_beep", LIST_ON_OFF),
    268: ("roger_beep", ROGER_CHOICES),
    269: ("analog_vox", LIST_ON_OFF),
    272: ("detect_range", DETECT_RANGE_CHOICES),
    273: ("relay_delay", MS100_CHOICES),
    275: ("noaa_1050_alarm", LIST_ON_OFF),
    278: ("short_tail", LIST_ON_OFF),
    388: ("dmr_remote", LIST_ON_OFF),
    397: ("call_start_beep", LIST_ON_OFF),
    398: ("call_end_beep", CALL_END_BEEP_CHOICES),
    404: ("dmr_group_display", GROUP_DISPLAY_CHOICES),
    405: ("dmr_send_dtmf", LIST_ON_OFF),
    406: ("sms_format", SMS_FORMAT_CHOICES),
    407: ("sms_font", SMS_FONT_CHOICES),
    512: ("dtmf_send_delay", MS100_CHOICES),
    513: ("dtmf_send_duration", MS30_CHOICES),
    514: ("dtmf_send_interval", MS30_CHOICES),
    515: ("dtmf_send_mode", DTMF_MODE_CHOICES),
    516: ("dtmf_send_select", DTMF_SELECT_CHOICES),
    517: ("dtmf_decode_display", LIST_ON_OFF),
    520: ("dtmf_remote", LIST_ON_OFF),
    842: ("channel_direction", LIST_ON_OFF),
    843: ("sms_tone", LIST_ON_OFF),
    852: ("carrier_led", LIST_ON_OFF),
}

CONFIG_INT_FIELDS = {
    "save_start": (100, "Power Save Start Time (s)", 0, 200, "u8"),
    "clock_seconds": (
        106, "APO Time (seconds)", APO_SECONDS_MIN, APO_SECONDS_MAX, "u32"),
    "lock_range_1_start": (143, "Lock Range 1 Start MHz", 18, 1000, "u16"),
    "lock_range_1_end": (145, "Lock Range 1 End MHz", 18, 1000, "u16"),
    "lock_range_2_start": (148, "Lock Range 2 Start MHz", 18, 1000, "u16"),
    "lock_range_2_end": (150, "Lock Range 2 End MHz", 18, 1000, "u16"),
    "lock_range_3_start": (153, "Lock Range 3 Start MHz", 18, 1000, "u16"),
    "lock_range_3_end": (155, "Lock Range 3 End MHz", 18, 1000, "u16"),
    "lock_range_4_start": (158, "Lock Range 4 Start MHz", 18, 1000, "u16"),
    "lock_range_4_end": (160, "Lock Range 4 End MHz", 18, 1000, "u16"),
    "lcd_contrast": (233, "Screen Contrast", 0, 10, "u8"),
    "single_tone_hz": (256, "Single Tone Frequency Hz", 0, 20000, "u16"),
    "squelch_level": (258, "Squelch Level", 0, 10, "u8"),
    "tx_mic_gain": (261, "Analog MIC Gain", 0, 31, "u8"),
    "rx_speaker_gain": (262, "Analog SPK Gain", 0, 63, "u8"),
    "analog_vox_threshold": (270, "VOX Threshold", 0, 245, "u8"),
    "analog_vox_delay": (271, "VOX Delay", 0, 5, "u8"),
    "glitch_filter": (276, "Adjacent-Channel Threshold", 0, 10, "u8"),
    "single_tone_timer": (277, "Single Tone Send Timer (s)", 0, 120, "u8"),
    "dmr_radio_id": (384, "Personal ID", 1, 16776415, "bcd32"),
    "dmr_tx_denoise": (389, "DMR TX Denoise", 0, 4, "u8"),
    "dmr_rx_denoise": (390, "DMR RX Denoise", 0, 4, "u8"),
    "dmr_call_mic_gain": (391, "DMR MIC Gain", 0, 24, "u8"),
    "dmr_called_speaker_gain": (392, "DMR SPK Gain", 0, 24, "u8"),
    "dmr_group_call_time": (
        399, "DMR Group Call Hold Time (ms)", 0, 9999, "u16"),
    "dmr_private_call_time": (
        401, "DMR Private Call Hold Time (ms)", 0, 9999, "u16"),
    "dmr_squelch_level": (403, "DMR Squelch Level", 0, 16, "u8"),
    "dmr_called_keep": (408, "Called Screen Keep Time (s)", 0, 60, "u8"),
    "dtmf_gain": (518, "DTMF Send Gain", 0, 127, "u8"),
    "dtmf_decode_threshold": (519, "DTMF Decode Threshold", 0, 63, "u8"),
}

CONFIG_INT_DEFAULTS = {
    "clock_seconds": APO_SECONDS_MIN,
    "lcd_contrast": 5,
}

LOCK_RANGE_NUMBERS = range(1, 5)

PTT_MIC_SETTING_NAMES = (
    "main_ptt",
    "cfg2_second_ptt",
    "tx_priority",
    "tx_mic_gain",
    "dmr_call_mic_gain",
    "dmr_tx_denoise",
    "tx_start_beep",
    "roger_beep",
    "call_start_beep",
    "call_end_beep",
)

DTMF_SETTING_NAMES = (
    "dtmf_send_delay",
    "dtmf_send_duration",
    "dtmf_send_interval",
    "dtmf_send_mode",
    "dtmf_send_select",
    "dtmf_gain",
    "dtmf_decode_threshold",
    "dtmf_remote",
)

POWER_MANAGEMENT_SETTING_NAMES = (
    "auto_power_off",
    "clock_seconds",
    "save_mode",
    "save_start",
)

SCREEN_DISPLAY_SETTING_NAMES = (
    "led_enabled",
    "lcd_brightness",
    "led_timer",
    "lcd_contrast",
    "carrier_led",
    "cfg2_dual_display",
    "cfg2_display_mode_a",
    "cfg2_display_mode_b",
    "dmr_group_display",
    "dmr_called_keep",
    "dtmf_decode_display",
)

SCAN_RECEIVE_SETTING_NAMES = (
    "scan_mode",
    "scan_return",
    "scan_dwell",
    "scan_interval",
    "refresh_delay",
    "detect_range",
    "glitch_filter",
    "scan_start_mhz",
    "scan_end_mhz",
    "noaa_1050_alarm",
    "squelch_level",
    "cfg2_scan_direction",
)

CONFIG_FLOAT_FIELDS = {
    "scan_start_mhz": (
        844, "Scan Start Frequency MHz", 18.0, 999.99999, 400.125),
    "scan_end_mhz": (
        848, "Scan End Frequency MHz", 18.0, 999.99999, 439.975),
}

CFG2_STEP_CHOICES = [
    "0.01K", "0.02K", "0.03K", "0.05K", "0.10K", "0.25K", "0.50K",
    "1.25K", "2.50K", "5.00K", "6.25K", "8.33K", "10.0K", "12.5K",
    "20.0K", "25.0K", "50.0K", "100K", "500K ", "1M", "5M",
]
VALID_TUNING_STEPS = [
    0.01, 0.02, 0.03, 0.05, 0.10, 0.25, 0.50, 1.25, 2.50, 5.00,
    6.25, 8.33, 10.0, 12.5, 20.0, 25.0, 50.0, 100.0, 500.0,
    1000.0, 5000.0,
]
CFG2_WORK_MODES = ["Freq Mode", "CH Mode", "Zone Mode"]
CFG2_DISPLAY_MODES = ["Channel", "Freq", "Alias"]
CFG2_KEY_FUNCTIONS = [
    "None", "Monitor(Analog)", "H/L Power", "Dual Standby",
    "TX Priority", "Scanning", "Backlight On-off", "Roger Beep",
    "FM Radio", "Talkaround", "Alarm", "Freq Detect",
    "CTC/DCS Scan", "Send Single Tone", "Status Query", "Remote Monitor",
    "Remote Stun", "Remote Kill", "Remote Wake Up", "Online Check",
    "Called Show", "RX AM/FM Switch", "Analog Spectrum", "SQ",
    "Freq Step", "DA Switch", "NOAA Mode", "Save CH", "New SMS",
    "Jump To SMS Menu", "Brightness", "Analog CH VOX", "Zone Select",
    "Promiscuous Mode", "Dual Slot On-off", "Time Slot Switch",
    "Color Code SW", "DMR Encrypt Off", "Jump To RX List",
    "Jump To Contact", "Jump To DTMF Sel",
]
CFG2_LIST_FIELDS = {
    0: ("cfg2_key_lock", "Key Lock", ["Unlock", "Lock"]),
    1: ("cfg2_main_range", "Current Band", ["A", "B"]),
    2: ("cfg2_dual_watch", "Dual Standby", LIST_ON_OFF),
    3: ("cfg2_dual_display", "Dual-Frequency Display", ["Dual", "Single"]),
    4: ("cfg2_scan_direction", "Scan Direction", ["Up", "Down"]),
    5: ("cfg2_step", "Frequency Step", CFG2_STEP_CHOICES),
    19: ("cfg2_fm_standby", "Standby RF RX", LIST_ON_OFF),
    20: ("cfg2_work_mode_a", "A Channel Work Mode", CFG2_WORK_MODES),
    21: ("cfg2_work_mode_b", "B Channel Work Mode", CFG2_WORK_MODES),
    22: ("cfg2_display_mode_a", "A Channel Display Mode",
         CFG2_DISPLAY_MODES),
    23: ("cfg2_display_mode_b", "B Channel Display Mode",
         CFG2_DISPLAY_MODES),
    30: ("cfg2_second_ptt", "Sub PTT Active", LIST_ON_OFF),
}
CFG2_KEY_FIELDS = {
    31: ("cfg2_fs1_short", "FS1 Short Key"),
    32: ("cfg2_fs1_long", "FS1 Long Key"),
    33: ("cfg2_fs2_short", "FS2 Short Key"),
    34: ("cfg2_fs2_long", "FS2 Long Key"),
    35: ("cfg2_alarm_short", "Alarm Short Key"),
    36: ("cfg2_alarm_long", "Alarm Long Key"),
    37: ("cfg2_key_0", "Key 0"),
    38: ("cfg2_key_1", "Key 1"),
    39: ("cfg2_key_2", "Key 2"),
    40: ("cfg2_key_3", "Key 3"),
    41: ("cfg2_key_4", "Key 4"),
    42: ("cfg2_key_5", "Key 5"),
    43: ("cfg2_key_6", "Key 6"),
    44: ("cfg2_key_7", "Key 7"),
    45: ("cfg2_key_8", "Key 8"),
    46: ("cfg2_key_9", "Key 9"),
}

LIST_BOOL_OFFSETS_BY_NAME = {
    value: offset for offset, value in LIST_BOOL_FIELDS.items()
}
CONFIG_LIST_FIELDS_BY_NAME = {
    field: (offset, choices)
    for offset, (field, choices) in CONFIG_LIST_FIELDS.items()
}
CFG2_LIST_FIELDS_BY_NAME = {
    field: (offset, label, choices)
    for offset, (field, label, choices) in CFG2_LIST_FIELDS.items()
}
CFG2_KEY_FIELDS_BY_NAME = {
    field: (offset, label)
    for offset, (field, label) in CFG2_KEY_FIELDS.items()
}
LOCK_RANGE_SETTING_NAMES = tuple(
    "lock_type_%d" % number for number in LOCK_RANGE_NUMBERS)
LOCK_RANGE_SETTING_NAMES += tuple(
    "lock_range_%d_%s" % (number, suffix)
    for number in LOCK_RANGE_NUMBERS
    for suffix in ("start", "end"))
EXPLICIT_SETTING_NAMES = frozenset(
    ("startup_password_enabled", "dmr_radio_id") +
    PTT_MIC_SETTING_NAMES +
    DTMF_SETTING_NAMES +
    POWER_MANAGEMENT_SETTING_NAMES +
    SCREEN_DISPLAY_SETTING_NAMES +
    SCAN_RECEIVE_SETTING_NAMES +
    LOCK_RANGE_SETTING_NAMES)

SETTING_LABELS = {
    "startup_picture": "Startup Logo",
    "startup_label": "Startup Text",
    "auto_power_off": "APO Enabled",
    "voice_prompt": "Voice Prompt",
    "lock_timer": "Timed Key Lock",
    "led_enabled": "Backlight",
    "lcd_brightness": "Screen Brightness",
    "led_timer": "Timed Screen Off",
    "save_mode": "Power Save Mode",
    "menu_timer": "Menu Timeout",
    "talkaround": "Talkaround / Reverse Frequency",
    "alarm_type": "Alarm Type",
    "tx_priority": "Priority TX",
    "main_ptt": "Main PTT TX Band",
    "lock_type_1": "Lock Range 1 Status",
    "lock_type_2": "Lock Range 2 Status",
    "lock_type_3": "Lock Range 3 Status",
    "lock_type_4": "Lock Range 4 Status",
    "scan_return": "Scan Return",
    "scan_dwell": "Scan Dwell Time",
    "scan_interval": "Scan Interval Time",
    "refresh_delay": "RSSI Refresh Time",
    "display_id_digits": "Frequency Input Digits",
    "roger_beep": "End TX Beep",
    "detect_range": "Frequency Detect Range",
    "relay_delay": "Repeater Callback Delay",
    "analog_vox": "Analog VOX",
    "analog_vox_threshold": "VOX Threshold",
    "analog_vox_delay": "VOX Delay",
    "short_tail": "Short Tail",
    "noaa_1050_alarm": "NOAA 1050 Alarm",
    "dmr_remote": "DMR Remote Control RX",
    "dmr_group_display": "Called Info Display",
    "dmr_send_dtmf": "Send DTMF",
    "sms_font": "SMS Encoding",
    "sms_tone": "SMS Prompt",
    "dtmf_send_delay": "DTMF Send Delay",
    "dtmf_send_duration": "DTMF Send Duration",
    "dtmf_send_interval": "DTMF Send Interval",
    "dtmf_send_mode": "DTMF Send Mode",
    "dtmf_send_select": "DTMF Send Selection",
    "dtmf_decode_display": "DTMF Decode Display",
    "dtmf_remote": "DTMF Remote Control",
    "channel_direction": "Channel Switch Reverse",
    "carrier_led": "Carrier Indicator LED",
}


def _checksum(data):
    return sum(data) & 0xFF


def _u16le(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def _set_u16le(data, offset, value):
    data[offset] = value & 0xFF
    data[offset + 1] = (value >> 8) & 0xFF


def _u32le(data, offset):
    return (
        data[offset] |
        (data[offset + 1] << 8) |
        (data[offset + 2] << 16) |
        (data[offset + 3] << 24)
    )


def _set_u32le(data, offset, value):
    data[offset] = value & 0xFF
    data[offset + 1] = (value >> 8) & 0xFF
    data[offset + 2] = (value >> 16) & 0xFF
    data[offset + 3] = (value >> 24) & 0xFF


def _decode_string(raw):
    raw = raw.split(b"\xFF", 1)[0].split(b"\x00", 1)[0]
    if not raw:
        return ""
    try:
        return raw.decode("gbk", errors="ignore").rstrip()
    except LookupError:
        return raw.decode(errors="ignore").rstrip()


def _encode_string(value, length):
    encoded = value.encode("gbk", errors="ignore")[:length]
    return encoded + (b"\xFF" * (length - len(encoded)))


def _filter_ascii(value, length):
    return "".join(
        ch for ch in value if ch in chirp_common.CHARSET_ASCII)[
        :length]


def _filter_path(value, length):
    return "".join(
        ch for ch in value if ch in chirp_common.CHARSET_ASCII)[
        :length]


def _is_blank(raw):
    return all(b in (0x00, 0xFF) for b in raw)


def _bcd_to_int(value):
    out = 0
    for shift in range(7, -1, -1):
        out *= 10
        out += (value >> (shift * 4)) & 0x0F
    return out


def _int_to_bcd(value):
    value = max(0, min(99999999, int(value)))
    return int("".join("%d" % int(d) for d in f"{value:08d}"), 16)


def _decode_tone(raw):
    if raw in (0x0000, 0xFFFF):
        return ("", None, "N")
    prefix = raw & 0xF000
    payload = raw & 0x0FFF
    if prefix == 0x1000:
        return ("Tone", payload / 10.0, "N")
    if prefix in (0x2000, 0x3000):
        code = int(format(payload, "o"))
        return ("DTCS", code, "R" if prefix == 0x3000 else "N")
    return ("", None, "N")


def _encode_tone(mode, value, polarity):
    if mode == "Tone":
        return 0x1000 | int(round(float(value) * 10))
    if mode == "DTCS":
        payload = int(str(int(value)), 8)
        return (0x3000 if polarity == "R" else 0x2000) | payload
    return 0xFFFF


def _fm_raw_to_freq(value):
    if value in (0x0000, 0xFFFF):
        return 0.0
    return value / 10.0


def _freq_to_fm_raw(value):
    if not value:
        return 0xFFFF
    return int(round(float(value) * 10))


def _fm_freq_text(raw, divisor, precision):
    if raw in (0x0000, 0xFFFF):
        return ""
    return ("%.*f" % (precision, raw / float(divisor)))


def _fm_freq_raw(text, multiplier):
    text = str(text).strip()
    if not text:
        return 0xFFFF
    return int(round(float(text) * multiplier))


def _setting_label(name):
    return SETTING_LABELS.get(name, name.replace("_", " ").title())


def _fm_bfo(data, offset, blank=False):
    if blank:
        return 0
    return _u16le(data, offset) - 32768


def _set_fm_bfo(data, offset, value):
    value = max(-32768, min(32767, int(value))) + 32768
    _set_u16le(data, offset, value)


def _get_config_int(cfg, offset, kind):
    if kind == "u8":
        return cfg[offset]
    if kind == "u16":
        return _u16le(cfg, offset)
    if kind == "u32":
        return _u32le(cfg, offset)
    if kind == "bcd32":
        return _bcd_to_int(_u32le(cfg, offset))
    raise errors.RadioError("Unknown config integer type %s" % kind)


def _set_config_int(cfg, offset, kind, value):
    value = int(value)
    if kind == "u8":
        cfg[offset] = value & 0xFF
    elif kind == "u16":
        _set_u16le(cfg, offset, value)
    elif kind == "u32":
        _set_u32le(cfg, offset, value)
    elif kind == "bcd32":
        _set_u32le(cfg, offset, _int_to_bcd(value))
    else:
        raise errors.RadioError("Unknown config integer type %s" % kind)


def _safe_choice_index(choices, value, default=0):
    text = str(value)
    return choices.index(text) if text in choices else default


def _is_high_power(power):
    return str(power) == str(POWER_LEVELS[1])


def _segment_blocks(data):
    return [bytes(data[offset:offset + BLOCK_SIZE])
            for offset in range(0, len(data), BLOCK_SIZE)]


class DMUV4RZoneBank(chirp_common.NamedBank):
    """Editable CHIRP bank backed by one DM-UV4R zone record."""

    def set_name(self, name):
        name = self._model._radio.filter_name(name).rstrip()
        self._model._radio._set_zone_name(self.get_index(), name)
        self._model._zones[self.get_index()]["name"] = name
        super().set_name(name)


class DMUV4RZoneBankModel(chirp_common.MTOBankModel):
    """Editable view of decoded DM-UV4R zones."""

    channelAlwaysHasBank = False

    def __init__(self, radio, name="Zones"):
        chirp_common.BankModel.__init__(self, radio, name)
        self._zones = self._radio._parse_zones()
        self._member_lists = [
            list(zone["members"]) for zone in self._zones
        ]
        self._member_sets = [
            set(members) for members in self._member_lists
        ]
        self._member_to_zone_indexes = {}
        self._rebuild_member_index()
        self._banks = []
        for index, zone in enumerate(self._zones):
            default_name = "Zone-%03d" % (index + 1)
            name = zone["name"] or default_name
            self._banks.append(DMUV4RZoneBank(self, index, name))

    def _rebuild_member_index(self):
        self._member_to_zone_indexes = {}
        for zone_index, members in enumerate(self._member_lists):
            for member in members:
                self._member_to_zone_indexes.setdefault(
                    member, []).append(zone_index)

    def _add_member_index(self, zone_index, member):
        zones = self._member_to_zone_indexes.setdefault(member, [])
        if zone_index not in zones:
            zones.append(zone_index)

    def _remove_member_index(self, zone_index, member):
        zones = self._member_to_zone_indexes.get(member, [])
        if zone_index in zones:
            zones.remove(zone_index)
        if not zones and member in self._member_to_zone_indexes:
            del self._member_to_zone_indexes[member]

    def get_num_mappings(self):
        return len(self._banks)

    def get_mappings(self):
        return self._banks

    def add_memory_to_mapping(self, memory, mapping):
        member = memory.number - 1
        zone_index = mapping.get_index()
        members = self._member_lists[zone_index]
        if member in self._member_sets[zone_index]:
            return
        if len(members) >= ZONE_MEMBERS:
            raise errors.RadioError("Zone is full")
        members.append(member)
        self._member_sets[zone_index].add(member)
        self._add_member_index(zone_index, member)
        self._radio._set_zone_members(zone_index, members)
        self._zones[zone_index]["members"] = list(members)

    def remove_memory_from_mapping(self, memory, mapping):
        member = memory.number - 1
        zone_index = mapping.get_index()
        members = self._member_lists[zone_index]
        if member not in self._member_sets[zone_index]:
            raise errors.RadioError("Memory is not in this zone")
        members.remove(member)
        self._member_sets[zone_index].remove(member)
        self._remove_member_index(zone_index, member)
        self._radio._set_zone_members(zone_index, members)
        self._zones[zone_index]["members"] = list(members)

    def get_mapping_memories(self, mapping):
        try:
            members = self._member_lists[mapping.get_index()]
        except IndexError:
            return []
        memories = []
        for member in members:
            try:
                mem = self._radio.get_memory(member + 1)
            except errors.InvalidMemoryLocation:
                continue
            if not mem.empty:
                memories.append(mem)
        return memories

    def get_memory_mappings(self, memory):
        member = memory.number - 1
        return [
            self._banks[index]
            for index in self._member_to_zone_indexes.get(member, [])
        ]


@directory.register
class IradioDMUV4RRadio(chirp_common.CloneModeRadio,
                        chirp_common.ExperimentalRadio):
    VENDOR = "Iradio"
    MODEL = "DM-UV4R"
    BAUD_RATE = 115200
    NEEDS_COMPAT_SERIAL = False
    _memsize = MEM_SIZE

    def __init__(self, pipe):
        self._password_bytes = None
        super().__init__(pipe)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver is experimental. Clone a backup before editing. "
            "Password-protected radios may require the OEM CPS to clear or "
            "preserve the programming password first. Uploads use the newer "
            "OEM cfg/channel/VFO/zone/contact/TG/encryption/SMS/FM sequence."
        )
        rp.pre_download = (
            "1. Power the radio off.\n"
            "2. Connect the programming cable.\n"
            "3. Power the radio on.\n"
            "4. Start the clone.\n"
        )
        rp.pre_upload = (
            "1. Power the radio off.\n"
            "2. Connect the programming cable.\n"
            "3. Power the radio on.\n"
            "4. Start the upload.\n"
        )
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = True
        rf.has_bank_names = True
        rf.has_name = True
        rf.has_tuning_step = False
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.can_odd_split = True
        rf.valid_bands = VALID_BANDS
        rf.valid_tuning_steps = VALID_TUNING_STEPS
        rf.valid_duplexes = ["", "+", "-", "split"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->DTCS",
            "DTCS->DTCS",
        ]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_modes = ["FM", "NFM", "DMR"]
        rf.valid_name_length = NAME_LEN
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.memory_bounds = (1, CHANNEL_COUNT)
        rf.valid_special_chans = sorted(SPECIAL_MEMORIES)
        rf.valid_skips = ["", "S"]
        return rf

    def get_bank_model(self):
        return DMUV4RZoneBankModel(self)

    @classmethod
    def _strip_trailing_metadata(cls, filedata):
        if len(filedata) in MATCH_MODEL_SIZES:
            return filedata
        for size in MATCH_MODEL_SIZES:
            if filedata[size:size + len(cls.MAGIC)] == cls.MAGIC:
                return filedata[:size]
        return filedata

    @classmethod
    def match_model(cls, filedata, filename):
        data = cls._strip_trailing_metadata(filedata)
        return len(data) in MATCH_MODEL_SIZES

    def load_mmap(self, filename):
        with open(filename, "rb") as mapfile:
            data = self._strip_trailing_metadata(mapfile.read())
        self._mmap = memmap.MemoryMapBytes(bytes(data))
        self.process_mmap()

    def process_mmap(self):
        if len(self._mmap) < MEM_SIZE:
            data = self._mmap.get(0, -1).ljust(MEM_SIZE, b"\xFF")
            self._mmap = memmap.MemoryMapBytes(data)
        self._password_bytes = bytes(self._get_segment("cfg")[:12])

    def get_raw_memory(self, number):
        if isinstance(number, str) or number < 0:
            raw = self._vfo_record(number)
        else:
            raw = self._channel_data(number)
        return raw.hex()

    def _get_segment(self, name):
        offset, size = SEGMENTS[name]
        return bytearray(self._mmap.get(offset, size).ljust(size, b"\xFF"))

    def _set_segment(self, name, data):
        offset, _size = SEGMENTS[name]
        self._mmap.set(offset, bytes(data))

    def _channel_offset(self, number):
        return OFFSET_ALL + ((number - 1) * CHANNEL_RECORD_SIZE)

    def _channel_data(self, number):
        return bytearray(
            self._mmap.get(self._channel_offset(number), CHANNEL_RECORD_SIZE))

    def _write_channel(self, number, data):
        self._mmap.set(self._channel_offset(number), bytes(data))

    def _special_name(self, number):
        if isinstance(number, str):
            if number not in SPECIAL_MEMORIES:
                raise errors.InvalidMemoryLocation(
                    "Unknown special %s" % number)
            return number
        if number in SPECIAL_MEMORIES_REV:
            return SPECIAL_MEMORIES_REV[number]
        raise errors.InvalidMemoryLocation("Unknown special %s" % number)

    def _vfo_index(self, number):
        return 0 if self._special_name(number) == "VFO-A" else 1

    def _vfo_record(self, number):
        vfo = self._get_segment("vfo")
        base = self._vfo_index(number) * CHANNEL_RECORD_SIZE
        return bytearray(vfo[base:base + CHANNEL_RECORD_SIZE])

    def _write_vfo_record(self, number, data):
        vfo = self._get_segment("vfo")
        base = self._vfo_index(number) * CHANNEL_RECORD_SIZE
        vfo[base:base +
            CHANNEL_RECORD_SIZE] = bytes(data[:CHANNEL_RECORD_SIZE])
        self._set_segment("vfo", vfo)

    def _read_frame(self, addr):
        cmd = bytes([0x52, (addr >> 8) & 0xFF, addr & 0xFF])
        frame = cmd + bytes([_checksum(cmd)])
        self.pipe.write(frame)
        reply = self.pipe.read(1028)
        if len(reply) != 1028:
            raise errors.RadioError("Short read from radio")
        if reply[0] != 0x52 or reply[1] != frame[1] or reply[2] != frame[2]:
            raise errors.RadioError("Unexpected block reply from radio")
        if reply[-1] != _checksum(reply[:-1]):
            raise errors.RadioError("Block checksum error")
        return reply[3:-1]

    def _write_frame(self, opcode, addr, payload):
        frame = bytes([opcode, (addr >> 8) & 0xFF, addr & 0xFF]) + payload
        frame += bytes([_checksum(frame)])
        self.pipe.write(frame)
        old_timeout = getattr(self.pipe, "timeout", None)
        try:
            if isinstance(old_timeout, (int, float)) and old_timeout < 5:
                self.pipe.timeout = 5
            ack = self.pipe.read(1)
        finally:
            if isinstance(old_timeout, (int, float)):
                self.pipe.timeout = old_timeout
        if ack != ACK:
            if opcode == 0xA4 and ack == b"\xA4":
                raise errors.RadioError("Global contacts flash IC mismatch")
            if opcode == 0xA4 and ack == b"\x4A":
                raise errors.RadioError(
                    "Global contacts reached flash capacity limit")
            raise errors.RadioError(
                "Radio did not ACK upload block opcode=0x%02X addr=%d" %
                (opcode, addr))

    def _enter(self):
        enter_programming_mode(self.pipe, READ_MAGIC, timeout=0.25)

    def _exit(self):
        exit_programming_mode(self.pipe, END_MAGIC)

    def _download_image(self):
        image = memmap.MemoryMapBytes(b"\xFF" * MEM_SIZE)
        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        status.cur = 0
        status.max = sum(blocks for _addr, _name, blocks in READ_PLAN)
        done = 0

        for addr, segment, blocks in READ_PLAN:
            seg_off, _seg_size = SEGMENTS[segment]
            for block in range(blocks):
                payload = self._read_frame(addr + block)
                image.set(seg_off + (block * BLOCK_SIZE), payload)
                done += 1
                status.cur = done
                self.status_fn(status)

        return image

    def _build_upload_cfg0(self, radio_cfg0):
        cfg = self._get_segment("cfg")
        cfg0 = bytearray(cfg[:BLOCK_SIZE])
        cfg0[960:1024] = radio_cfg0[960:1024]
        cfg0[12:14] = b"\xCD\xAB"
        cfg0[14:16] = b"\xFF\xFF"
        return cfg0

    def _parse_zones(self):
        zone = self._get_segment("zone")
        zones = []
        count = self._zone_record_count()
        for index in range(count):
            raw = self._zone_record(index, zone)
            name = _filter_ascii(_decode_string(bytes(raw[4:20])), 16)
            zones.append({
                "name": name,
                "channel_a": _u16le(raw, 0),
                "channel_b": _u16le(raw, 2),
                "members": self._zone_record_members(raw),
                "raw": bytes(raw),
            })
        return zones

    def _zone_record_count(self):
        return ZONE_COUNT

    def _zone_table_score(self, zone, offset):
        score = 0
        for index in range(min(16, ZONE_COUNT)):
            base = offset + (index * ZONE_RECORD_SIZE)
            if base + ZONE_RECORD_SIZE > len(zone):
                break
            raw = zone[base:base + ZONE_RECORD_SIZE]
            name = _filter_ascii(_decode_string(bytes(raw[4:20])), 16)
            if name:
                score += 2
            for member in range(min(8, ZONE_MEMBERS)):
                if _u16le(raw, 20 + (member * 2)) < CHANNEL_COUNT:
                    score += 1
                    break
        return score

    def _zone_table_offset(self, zone=None):
        if zone is None:
            zone = self._get_segment("zone")
        legacy_fits = LEGACY_ZONE_TABLE_OFFSET + ZONE_RECORD_SIZE <= len(zone)
        if legacy_fits:
            score = self._zone_table_score(zone, ZONE_TABLE_OFFSET)
            legacy_score = self._zone_table_score(
                zone, LEGACY_ZONE_TABLE_OFFSET)
            if legacy_score > score + 2:
                return LEGACY_ZONE_TABLE_OFFSET
        return ZONE_TABLE_OFFSET

    def _zone_offset(self, index, zone=None):
        return self._zone_table_offset(zone) + (index * ZONE_RECORD_SIZE)

    def _blank_zone_record(self):
        return bytearray(b"\xFF" * ZONE_RECORD_SIZE)

    def _zone_record(self, index, zone=None):
        if zone is None:
            zone = self._get_segment("zone")
        base = self._zone_offset(index, zone)
        if base + ZONE_RECORD_SIZE > len(zone):
            return self._blank_zone_record()
        return bytearray(zone[base:base + ZONE_RECORD_SIZE])

    def _write_zone_record(self, index, record):
        zone = self._get_segment("zone")
        base = self._zone_offset(index, zone)
        if base + ZONE_RECORD_SIZE > len(zone):
            zone = self._build_zone_upload()
            base = index * ZONE_RECORD_SIZE
        if base + ZONE_RECORD_SIZE > len(zone):
            raise errors.RadioError("Zone record does not fit in image")
        zone[base:base + ZONE_RECORD_SIZE] = bytes(record[:ZONE_RECORD_SIZE])
        self._set_segment("zone", zone)

    def _zone_record_members(self, raw):
        members = []
        for member in range(ZONE_MEMBERS):
            value = _u16le(raw, 20 + (member * 2))
            if value < CHANNEL_COUNT:
                members.append(value)
        return members

    def _zone_members(self, index):
        return self._zone_record_members(self._zone_record(index))

    def _set_zone_members(self, index, members):
        record = self._zone_record(index)
        record[20:20 + (ZONE_MEMBERS * 2)] = b"\xFF" * (ZONE_MEMBERS * 2)
        for member_index, member in enumerate(members[:ZONE_MEMBERS]):
            if 0 <= member < CHANNEL_COUNT:
                _set_u16le(record, 20 + (member_index * 2), member)
        if members:
            default_a = _u16le(record, 0)
            default_b = _u16le(record, 2)
            if default_a not in members:
                default_a = members[0]
            if default_b not in members:
                default_b = members[1] if len(members) > 1 else members[0]
            _set_u16le(record, 0, default_a)
            _set_u16le(record, 2, default_b)
        else:
            _set_u16le(record, 0, 0xFFFF)
            _set_u16le(record, 2, 0xFFFF)
        self._write_zone_record(index, record)

    def _set_zone_name(self, index, name):
        record = self._zone_record(index)
        record[4:20] = _encode_string(name, 16)
        self._write_zone_record(index, record)

    def _zone_default_channel_number(self, value):
        if 0 <= value < CHANNEL_COUNT:
            return value + 1
        return 1

    def _zone_has_default_settings(self, index, zone):
        if zone["members"]:
            return True
        default_name = "Zone-%03d" % (index + 1)
        placeholder_name = not zone["name"] or zone["name"] == default_name
        placeholder_defaults = (
            zone["channel_a"] in (0, 0xFFFF) and
            zone["channel_b"] in (0, 0xFFFF))
        if placeholder_name and placeholder_defaults:
            return False
        return (
            bool(zone["name"]) or
            zone["channel_a"] < CHANNEL_COUNT or
            zone["channel_b"] < CHANNEL_COUNT)

    def _append_zone_default_settings(self, group):
        group.set_doc(
            "OEM zone records store separate default channel A/B fields. "
            "Values are shown as CHIRP's 1-based channel numbers; the radio "
            "stores them zero-based. The OEM UI normally limits these to "
            "channels already present in the zone. Zone names are edited in "
            "the Zones/Banks tab. Blank zones are omitted from this settings "
            "page to keep the settings UI responsive; use the Zones editor "
            "to add channel membership first.")
        for index, zone in enumerate(self._parse_zones()):
            if not self._zone_has_default_settings(index, zone):
                continue
            zone_name = zone["name"] or "Zone-%03d" % (index + 1)
            self._append_int_setting(
                group, "zone_default_a_%03d" % index,
                "Zone %03d A Channel (%s)" % (index + 1, zone_name),
                self._zone_default_channel_number(zone["channel_a"]),
                1, CHANNEL_COUNT)
            self._append_int_setting(
                group, "zone_default_b_%03d" % index,
                "Zone %03d B Channel (%s)" % (index + 1, zone_name),
                self._zone_default_channel_number(zone["channel_b"]),
                1, CHANNEL_COUNT)

    def _apply_zone_default_setting(self, zone, name, value):
        index = int(name.rsplit("_", 1)[1])
        slot = name[len("zone_default_")]
        base = ZONE_TABLE_OFFSET + (index * ZONE_RECORD_SIZE)
        if base + 4 > len(zone):
            raise errors.RadioError(
                "Zone default channel does not fit in image")
        offset = 0 if slot == "a" else 2
        channel = max(1, min(CHANNEL_COUNT, int(value))) - 1
        _set_u16le(zone, base + offset, channel)

    def _build_zone_upload(self):
        zone = self._get_segment("zone")
        offset = self._zone_table_offset(zone)
        if offset == 0:
            return zone
        data = bytearray(b"\xFF" * SEGMENTS["zone"][1])
        available = min(len(zone) - offset, len(data))
        data[:available] = zone[offset:offset + available]
        return data

    def _parse_contacts(self):
        contact = self._get_segment("contact")
        contacts = []
        for index in range(CONTACT_COUNT):
            base = index * CONTACT_RECORD_SIZE
            if base + CONTACT_RECORD_SIZE > len(contact):
                break
            contact_type = contact[base]
            if contact_type > 2:
                continue
            name = _filter_ascii(
                _decode_string(bytes(contact[base + 5:base + 21])), 16)
            if index == 0:
                contact_id = 16777215
                if not name:
                    name = "All Call"
            else:
                contact_id = _bcd_to_int(_u32le(contact, base + 1))
                if contact_id > 99999999:
                    continue
            contacts.append({
                "slot": index,
                "type": contact_type,
                "name": name,
                "id": contact_id,
            })
        return contacts

    def _build_contact_upload(self):
        data = bytearray(b"\xFF" * SEGMENTS["contact"][1])
        valid_contacts = {
            contact["slot"]: contact for contact in self._parse_contacts()}
        if 0 not in valid_contacts:
            valid_contacts[0] = {
                "slot": 0,
                "type": 2,
                "name": "All Call",
                "id": 16777215,
            }
        for index in range(CONTACT_COUNT):
            base = index * CONTACT_RECORD_SIZE
            contact = valid_contacts.get(index)
            if not contact:
                continue
            data[base] = contact["type"] & 0xFF
            if index == 0:
                data[base + 1:base + 5] = b"\xAA\xAA\xAA\xAA"
            else:
                _set_u32le(data, base + 1, _int_to_bcd(contact["id"]))
            data[base + 5:base + 21] = _encode_string(contact["name"], 16)
        return data

    def _write_contact_entry(
            self,
            contact,
            slot,
            contact_type,
            contact_id,
            name):
        if slot < 0 or slot >= CONTACT_COUNT:
            raise errors.RadioError("Contact slot out of range")
        base = slot * CONTACT_RECORD_SIZE
        contact[base:base + CONTACT_RECORD_SIZE] = b"\xFF" * \
            CONTACT_RECORD_SIZE
        contact[base] = contact_type & 0xFF
        if slot == 0:
            contact[base + 1:base + 5] = b"\xAA\xAA\xAA\xAA"
        else:
            _set_u32le(contact, base + 1, _int_to_bcd(contact_id))
        contact[base + 5:base + 21] = _encode_string(name, 16)

    def _decode_local_contacts_csv(self, path):
        csv_path = os.path.expanduser(path)
        if not os.path.exists(csv_path):
            raise errors.RadioError(
                "DMR contacts CSV does not exist: %s" % csv_path)
        if not os.path.isfile(csv_path):
            raise errors.RadioError(
                "DMR contacts CSV is not a file: %s" % csv_path)
        try:
            with open(csv_path, "rb") as csv_file:
                raw = csv_file.read()
        except OSError as exc:
            raise errors.RadioError(
                "DMR contacts CSV cannot be read: %s" % exc) from exc

        for encoding in ("utf-8-sig", "gbk"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                text = None
        if text is None:
            text = raw.decode("gbk", errors="replace")
        return list(csv.reader(io.StringIO(text)))

    def _csv_contact_type(self, value):
        text = str(value).strip().lower()
        if not text or text == "disabled":
            return None
        if text in LOCAL_CONTACT_TYPE_ALIASES:
            return LOCAL_CONTACT_TYPE_ALIASES[text]
        raise errors.RadioError("Unknown DMR contact type %r" % value)

    def _csv_contact_id(self, value):
        text = str(value).strip()
        if not text:
            return 0
        try:
            contact_id = int(text)
        except ValueError as exc:
            raise errors.RadioError(
                "Invalid DMR contact ID %r" % value) from exc
        if contact_id < 0 or contact_id > 99999999:
            raise errors.RadioError(
                "DMR contact ID out of range: %d" % contact_id)
        return contact_id

    def _csv_contact_rows(self, path):
        rows = self._decode_local_contacts_csv(path)
        contacts = []
        positional_slot = 1
        for row_index, row in enumerate(rows):
            row = [cell.strip() for cell in row]
            if not any(row):
                continue
            row += [""] * (4 - len(row))
            number, contact_type, name, contact_id = row[:4]
            if row_index == 0 and not number.isdigit():
                continue

            ctype = self._csv_contact_type(contact_type)
            if ctype is None and not name and not contact_id:
                if number == "1":
                    continue
                contacts.append(
                    (self._csv_contact_slot(
                        number, positional_slot), None, 0, ""))
                positional_slot += 1
                continue
            if ctype is None:
                raise errors.RadioError(
                    "DMR contact row %d has no contact type" % (row_index + 1))

            slot = self._csv_contact_slot(number, positional_slot)
            contacts.append(
                (slot, ctype, self._csv_contact_id(contact_id), name))
            positional_slot = max(positional_slot + 1, slot + 1)
        return contacts

    def _csv_contact_slot(self, number, fallback):
        if str(number).strip().isdigit():
            slot = int(str(number).strip()) - 1
        else:
            slot = fallback
        if slot < 0 or slot >= CONTACT_COUNT:
            raise errors.RadioError("DMR contact CSV slot out of range")
        return slot

    def _first_blank_contact_slot(self, contact):
        for slot in range(1, CONTACT_COUNT):
            base = slot * CONTACT_RECORD_SIZE
            if contact[base] > 2:
                return slot
        raise errors.RadioError("No blank DMR contact slots available")

    def _apply_local_contacts_csv(self, contact, path, mode):
        rows = self._csv_contact_rows(path)
        if mode == "Replace":
            contact = bytearray(b"\xFF" * SEGMENTS["contact"][1])
            self._write_contact_entry(contact, 0, 2, 16777215, "All Call")
            for slot, ctype, contact_id, name in rows:
                if slot == 0:
                    continue
                if ctype is None:
                    base = slot * CONTACT_RECORD_SIZE
                    contact[base:base + CONTACT_RECORD_SIZE] = (
                        b"\xFF" * CONTACT_RECORD_SIZE)
                else:
                    self._write_contact_entry(
                        contact, slot, ctype, contact_id, name)
            return contact

        if mode == "Append":
            contact = bytearray(contact)
            slot = self._first_blank_contact_slot(contact)
            for csv_slot, ctype, contact_id, name in rows:
                if csv_slot == 0:
                    continue
                if ctype is None:
                    continue
                self._write_contact_entry(
                    contact, slot, ctype, contact_id, name)
                slot += 1
                if slot >= CONTACT_COUNT:
                    raise errors.RadioError(
                        "No blank DMR contact slots available")
            return contact

        return contact

    def _contact_setting_slots(self, contacts):
        slots = set(range(CONTACT_UI_MIN_SLOTS))
        slots.update(contact["slot"] for contact in contacts)
        return sorted(slot for slot in slots if slot < CONTACT_COUNT)

    def _append_contact_settings(self, parent):
        contacts = {
            contact["slot"]: contact
            for contact in self._parse_contacts()
        }
        for slot in self._contact_setting_slots(contacts.values()):
            contact = contacts.get(slot, {})
            contact_type = contact.get("type", 0xFF)
            current_type = contact_type + 1 if contact_type <= 2 else 0
            group = RadioSettingSubGroup(
                "contact_%05d" % slot, "Contact %05d" % (slot + 1))
            group.append(
                RadioSetting(
                    "contact_%05d_type" % slot,
                    "Type",
                    RadioSettingValueList(
                        CONTACT_TYPES,
                        current_index=current_type)))
            group.append(RadioSetting(
                "contact_%05d_id" % slot, "DMR ID",
                RadioSettingValueInteger(0, 99999999, contact.get("id", 0))))
            group.append(RadioSetting(
                "contact_%05d_name" % slot, "Name",
                RadioSettingValueString(
                    0, 16, contact.get("name", ""), autopad=False)))
            parent.append(group)

    def _apply_contact_settings(self, contact, group):
        slot = int(group.get_name().split("_", 1)[1])
        prefix = "contact_%05d_" % slot
        base = slot * CONTACT_RECORD_SIZE
        ctype = str(group[prefix + "type"].value)
        if ctype == "Disabled":
            contact[base:base + CONTACT_RECORD_SIZE] = b"\xFF" * \
                CONTACT_RECORD_SIZE
            return

        contact[base:base + CONTACT_RECORD_SIZE] = b"\xFF" * \
            CONTACT_RECORD_SIZE
        contact[base] = CONTACT_TYPES.index(ctype) - 1
        if slot == 0:
            contact[base + 1:base + 5] = b"\xAA\xAA\xAA\xAA"
        else:
            _set_u32le(contact, base + 1,
                       _int_to_bcd(int(group[prefix + "id"].value)))
        contact[base + 5:base + 21] = _encode_string(
            str(group[prefix + "name"].value).rstrip(), 16)

    def _parse_groups(self):
        group = self._get_segment("group")
        groups = []
        for index in range(GROUP_COUNT):
            base = index * GROUP_RECORD_SIZE
            name = _filter_ascii(_decode_string(
                bytes(group[base:base + 16])), 16)
            members = []
            for member in range(GROUP_MEMBERS):
                value = _u16le(group, base + 16 + (member * 2))
                if value < CONTACT_COUNT:
                    members.append(value)
            enabled = bool(name) or bool(members)
            groups.append({
                "slot": index,
                "enabled": enabled,
                "name": name,
                "members": members,
            })
        return groups

    def _build_group_upload(self):
        data = bytearray(b"\xFF" * SEGMENTS["group"][1])
        for group in self._parse_groups():
            if not group["enabled"]:
                continue
            base = group["slot"] * GROUP_RECORD_SIZE
            data[base:base + 16] = _encode_string(group["name"], 16)
            for member_index in range(GROUP_MEMBERS):
                value = 0xFFFF
                if member_index < len(group["members"]):
                    value = group["members"][member_index]
                _set_u16le(data, base + 16 + (member_index * 2), value)
        return data

    def _members_to_csv(self, members):
        return ",".join(str(member) for member in members)

    def _members_from_csv(self, text):
        members = []
        text = str(text).strip()
        if not text:
            return members
        for raw in text.split(","):
            raw = raw.strip()
            if not raw:
                continue
            value = int(raw)
            if value < 0 or value >= CONTACT_COUNT:
                raise errors.RadioError("TG list contact index out of range")
            members.append(value)
        return members[:GROUP_MEMBERS]

    def _append_group_settings(self, parent):
        groups = self._parse_groups()
        for group_info in groups:
            group = RadioSettingSubGroup(
                "tg_%03d" % group_info["slot"],
                "TG List %03d" % (group_info["slot"] + 1))
            group.append(RadioSetting(
                "tg_%03d_name" % group_info["slot"], "Name",
                RadioSettingValueString(
                    0, 16, group_info["name"], autopad=False)))
            group.append(RadioSetting(
                "tg_%03d_members" % group_info["slot"], "Raw Contact Indexes",
                RadioSettingValueString(
                    0, GROUP_MEMBERS * 6,
                    self._members_to_csv(group_info["members"]),
                    autopad=False, charset=CSV_CHARSET)))
            parent.append(group)

    def _apply_group_settings(self, group_data, group):
        slot = int(group.get_name().split("_", 1)[1])
        prefix = "tg_%03d_" % slot
        base = slot * GROUP_RECORD_SIZE
        name = str(group[prefix + "name"].value).rstrip()
        members = self._members_from_csv(group[prefix + "members"].value)
        if not name and not members:
            group_data[base:base + GROUP_RECORD_SIZE] = b"\xFF" * \
                GROUP_RECORD_SIZE
            return
        group_data[base:base + GROUP_RECORD_SIZE] = b"\xFF" * GROUP_RECORD_SIZE
        group_data[base:base + 16] = _encode_string(name, 16)
        for member_index, member in enumerate(members):
            _set_u16le(group_data, base + 16 + (member_index * 2), member)

    def _parse_encryptions(self):
        encrypt = self._get_segment("encrypt")
        entries = []
        for index in range(ENCRYPTION_COUNT):
            base = index * ENCRYPTION_RECORD_SIZE
            enc_type = encrypt[base + 1]
            name = _filter_ascii(_decode_string(
                bytes(encrypt[base + 2:base + 16])), 14)
            key = bytes(encrypt[base + 16:base + 48])
            enabled = enc_type <= 2 and (bool(name) or not _is_blank(key))
            entries.append({
                "slot": index,
                "enabled": enabled,
                "type": 0 if enc_type > 2 else enc_type,
                "name": name,
                "key": key,
            })
        return entries

    def _build_encrypt_upload(self):
        data = bytearray(b"\xFF" * SEGMENTS["encrypt"][1])
        for entry in self._parse_encryptions():
            if not entry["enabled"]:
                continue
            base = entry["slot"] * ENCRYPTION_RECORD_SIZE
            data[base] = (entry["slot"] + 1) & 0xFF
            data[base + 1] = entry["type"] & 0xFF
            data[base + 2:base + 16] = _encode_string(entry["name"], 14)
            key_len = ENCRYPTION_KEY_LENGTHS[entry["type"]]
            data[base + 16:base + 48] = (
                entry["key"][:key_len].ljust(32, b"\xFF"))
        return data

    def _encryption_key_hex(self, entry):
        if not entry["enabled"]:
            return ""
        key_len = ENCRYPTION_KEY_LENGTHS[entry["type"]]
        return entry["key"][:key_len].hex().upper()

    def _append_encryption_settings(self, parent):
        for entry in self._parse_encryptions():
            group = RadioSettingSubGroup(
                "encrypt_%03d" % entry["slot"],
                "Encryption %03d" % (entry["slot"] + 1))
            group.append(RadioSetting(
                "encrypt_%03d_enabled" % entry["slot"], "Enabled",
                RadioSettingValueBoolean(entry["enabled"])))
            group.append(RadioSetting(
                "encrypt_%03d_type" % entry["slot"], "Type",
                RadioSettingValueList(ENCRYPTION_TYPES,
                                      current_index=entry["type"])))
            group.append(RadioSetting(
                "encrypt_%03d_name" % entry["slot"], "Name",
                RadioSettingValueString(
                    0, 14, entry["name"], autopad=False)))
            group.append(RadioSetting(
                "encrypt_%03d_key_hex" % entry["slot"], "Key Hex",
                RadioSettingValueString(
                    0, 64, self._encryption_key_hex(entry), autopad=False,
                    charset=HEX_CHARSET)))
            parent.append(group)

    def _apply_encryption_settings(self, encrypt, group):
        slot = int(group.get_name().split("_", 1)[1])
        prefix = "encrypt_%03d_" % slot
        base = slot * ENCRYPTION_RECORD_SIZE
        if not bool(group[prefix + "enabled"].value):
            encrypt[base:base + ENCRYPTION_RECORD_SIZE] = (
                b"\xFF" * ENCRYPTION_RECORD_SIZE)
            return
        enc_type = ENCRYPTION_TYPES.index(str(group[prefix + "type"].value))
        key_hex = str(group[prefix + "key_hex"].value).strip()
        if len(key_hex) % 2:
            key_hex += "F"
        try:
            key = bytes.fromhex(key_hex)
        except ValueError as exc:
            raise errors.RadioError("Invalid encryption key hex: %s" % exc)
        encrypt[base:base + ENCRYPTION_RECORD_SIZE] = b"\xFF" * \
            ENCRYPTION_RECORD_SIZE
        encrypt[base] = (slot + 1) & 0xFF
        encrypt[base + 1] = enc_type
        encrypt[base + 2:base + 16] = _encode_string(
            str(group[prefix + "name"].value).rstrip(), 14)
        key_len = ENCRYPTION_KEY_LENGTHS[enc_type]
        encrypt[base + 16:base + 48] = key[:key_len].ljust(32, b"\xFF")

    def _build_sms_upload(self):
        sms = self._get_segment("sms")
        data = bytearray(b"\xFF" * (SMS_PRESET_COUNT * SMS_RECORD_SIZE))
        for index in range(SMS_PRESET_COUNT):
            src = sms[index * SMS_RECORD_SIZE:(index + 1) * SMS_RECORD_SIZE]
            base = index * SMS_RECORD_SIZE
            if src[0] != 0x00:
                continue
            text = _decode_string(bytes(src[56:56 + SMS_TEXT_LEN]))
            if text:
                data[base] = 0x00
                data[base + 1:base + 56] = b"\xFF" * 55
                data[base + 56:base + 56 + SMS_TEXT_LEN] = (
                    _encode_string(text, SMS_TEXT_LEN))
        return data

    def _build_fm_upload(self):
        return self._get_segment("fm")

    def _startup_image_payload_hex(self):
        data = self._get_segment("startup_image")
        payload = bytes(data[1:1 + STARTUP_IMAGE_PAYLOAD_SIZE])
        if data[0] != 0x01 and payload == b"\xFF" * STARTUP_IMAGE_PAYLOAD_SIZE:
            return ""
        if payload[1024:] == b"\x00" * (STARTUP_IMAGE_PAYLOAD_SIZE - 1024):
            payload = payload[:1024]
        return payload.hex().upper()

    def _set_startup_image_payload_hex(self, value):
        text = str(value).strip()
        data = self._get_segment("startup_image")
        if not text:
            data[0] = 0xFF
            data[1:] = b"\xFF" * STARTUP_IMAGE_PAYLOAD_SIZE
            self._set_segment("startup_image", data)
            return

        try:
            payload = bytes.fromhex(text)
        except ValueError as exc:
            raise errors.RadioError("Invalid power-on image hex: %s" % exc)
        if len(payload) not in (1024, STARTUP_IMAGE_PAYLOAD_SIZE):
            raise errors.RadioError(
                "Power-on image must be 1024 or 4096 bytes, got %d" %
                len(payload))

        data[1:] = b"\x00" * STARTUP_IMAGE_PAYLOAD_SIZE
        data[1:1 + len(payload)] = payload
        self._set_segment("startup_image", data)

    def _build_startup_image_upload(self):
        data = self._get_segment("startup_image")
        if data[0] != 0x01:
            return []
        payload = bytes(data[1:1 + STARTUP_IMAGE_PAYLOAD_SIZE])
        return _segment_blocks(payload)

    def _build_startup_image_follow_upload(self):
        blocks = self._build_startup_image_upload()
        return blocks[:1]

    def _global_contacts_path(self):
        data = self._get_segment("global_contacts")
        return _filter_path(_decode_string(bytes(data[1:])),
                            GLOBAL_CONTACT_CSV_PATH_LEN)

    def _set_global_contacts_path(self, value):
        data = self._get_segment("global_contacts")
        data[1:] = _encode_string(
            _filter_path(str(value).rstrip(), GLOBAL_CONTACT_CSV_PATH_LEN),
            GLOBAL_CONTACT_CSV_PATH_LEN)
        self._set_segment("global_contacts", data)

    def _global_contacts_payload_from_csv(self, path):
        path = os.path.expanduser(str(path).strip())
        if not path:
            return []
        if not os.path.exists(path):
            raise errors.RadioError(
                "Global contacts CSV does not exist: %s" % path)
        if not os.path.isfile(path):
            raise errors.RadioError(
                "Global contacts CSV is not a file: %s" % path)

        rows = []
        try:
            with open(path, "r", encoding="utf-8-sig",
                      errors="replace") as csv_file:
                for line_no, line in enumerate(csv_file):
                    if line_no == 0:
                        continue
                    columns = line.rstrip("\r\n").split(",")
                    # OEM importer appends text only after seeing the sixth
                    # comma.
                    if len(columns) < 7:
                        continue
                    rows.append(",".join(columns[:6]))
        except OSError as exc:
            raise errors.RadioError(
                "Global contacts CSV cannot be read: %s" % exc) from exc

        payload = "\n".join(rows)
        if payload:
            payload += "\n"
        payload = payload.encode("gbk", errors="ignore")[
            :GLOBAL_CONTACT_MAX_PAYLOAD]
        total_len = len(payload) + 4
        data = bytearray([
            (total_len >> 24) & 0xFF,
            (total_len >> 16) & 0xFF,
            (total_len >> 8) & 0xFF,
            total_len & 0xFF,
        ])
        data.extend(payload)
        while len(data) % BLOCK_SIZE:
            data.append(0xFF)
        return _segment_blocks(data)

    def _build_global_contacts_upload(self):
        data = self._get_segment("global_contacts")
        if data[0] != 0x01:
            return []
        path = self._global_contacts_path()
        if not path:
            raise errors.RadioError(
                "Global contacts upload enabled but no CSV path is configured")
        return self._global_contacts_payload_from_csv(path)

    def _build_upload_segments(self, radio_cfg0):
        cfg = self._get_segment("cfg")
        return {
            "cfg": [self._build_upload_cfg0(radio_cfg0)] +
            _segment_blocks(cfg[BLOCK_SIZE:]),
            "all": _segment_blocks(self._get_segment("all")),
            "vfo": _segment_blocks(self._get_segment("vfo")),
            "zone": _segment_blocks(self._build_zone_upload()),
            "contact": _segment_blocks(self._build_contact_upload()),
            "group": _segment_blocks(self._build_group_upload()),
            "encrypt": _segment_blocks(self._build_encrypt_upload()),
            "sms": _segment_blocks(self._build_sms_upload()),
            "fm": _segment_blocks(self._build_fm_upload()),
        }

    def sync_in(self):
        try:
            self._enter()
            self._mmap = self._download_image()
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as exc:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % exc)
        finally:
            try:
                self._exit()
            except Exception:
                pass

    def sync_out(self):
        entered = False
        try:
            startup_image_blocks = self._build_startup_image_follow_upload()
            global_contact_blocks = self._build_global_contacts_upload()
            self._enter()
            entered = True
            probe = self._read_frame(0x0000)
            if len(probe) != BLOCK_SIZE:
                raise errors.RadioError("Probe block failed")
            radio_cfg0 = self._read_frame(0x0008)
            image_password = bytes(self._get_segment("cfg")[:12])
            radio_password = bytes(radio_cfg0[:12])
            if image_password not in (b"\xFF" * 12, radio_password):
                raise errors.RadioError(
                    "Programming password mismatch. Use the OEM CPS to "
                    "clear or clone the correct password first."
                )

            status = chirp_common.Status()
            status.msg = "Uploading to radio"
            status.cur = 0
            normal_blocks = sum(
                blocks
                for _opcode, _base, _name, blocks in SAFE_UPLOAD_PLAN)
            status.max = (normal_blocks + len(startup_image_blocks) +
                          len(global_contact_blocks))

            written = 0
            cfg = self._get_segment("cfg")
            upload_segments = self._build_upload_segments(radio_cfg0)
            for opcode, _flash_sector, segment, blocks in SAFE_UPLOAD_PLAN:
                for block in range(blocks):
                    payload = upload_segments[segment][block]
                    self._write_frame(opcode, block, bytes(payload))
                    written += 1
                    status.cur = written
                    self.status_fn(status)
            for block, payload in enumerate(startup_image_blocks):
                self._write_frame(0x9A, block, bytes(payload))
                written += 1
                status.cur = written
                self.status_fn(status)
            if global_contact_blocks:
                # The OEM global-contact writer uses a separate flgComState=6
                # session, not an extension of the full codeplug writer.
                self._exit()
                entered = False
                self._enter()
                entered = True
            for block, payload in enumerate(global_contact_blocks):
                self._write_frame(0xA4, block, bytes(payload))
                written += 1
                status.cur = written
                self.status_fn(status)
            self._password_bytes = bytes(cfg[:12])
        except errors.RadioError:
            raise
        except Exception as exc:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % exc)
        finally:
            if entered:
                try:
                    self._exit()
                except Exception:
                    pass

    def _sync_out_utility_blocks(self, opcode, blocks, status_msg):
        if not blocks:
            raise errors.RadioError(
                "No payload configured for %s" % status_msg)
        entered = False
        try:
            self._enter()
            entered = True
            status = chirp_common.Status()
            status.msg = status_msg
            status.cur = 0
            status.max = len(blocks)
            for block, payload in enumerate(blocks):
                self._write_frame(opcode, block, bytes(payload))
                status.cur = block + 1
                self.status_fn(status)
        except errors.RadioError:
            raise
        except Exception as exc:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % exc)
        finally:
            if entered:
                try:
                    self._exit()
                except Exception:
                    pass

    def sync_out_startup_image(self):
        self._sync_out_utility_blocks(
            0x9A, self._build_startup_image_upload(),
            "Uploading power-on image")

    def sync_out_global_contacts(self):
        self._sync_out_utility_blocks(
            0xA4, self._build_global_contacts_upload(),
            "Uploading global contacts")

    def filter_name(self, name):
        return _filter_ascii(name, NAME_LEN)

    def _get_analog_memory(self, mem, raw):
        rx = _decode_tone(_u16le(raw, 13))
        tx = _decode_tone(_u16le(raw, 15))
        chirp_common.split_tone_decode(mem, tx, rx)
        band = (raw[4] >> 6) & 0x03 if raw[4] != 0xFF else 0
        if band == 1:
            mem.mode = "NFM"
        elif band == 0:
            mem.mode = "FM"
        else:
            mem.mode = "NFM" if mem.freq >= 400000000 else "FM"

    def _set_analog_memory(self, mem, raw):
        tx, rx = chirp_common.split_tone_encode(mem)
        rx_blank = _u16le(raw, 13)
        tx_blank = _u16le(raw, 15)
        if rx_blank not in (0x0000, 0xFFFF):
            rx_blank = 0x0000
        if tx_blank not in (0x0000, 0xFFFF):
            tx_blank = 0x0000
        _set_u16le(raw, 13, _encode_tone(*rx)
                   if rx[0] else rx_blank)
        _set_u16le(raw, 15, _encode_tone(*tx)
                   if tx[0] else tx_blank)
        raw[4] = (raw[4] & 0x3F) | ((1 if mem.mode == "NFM" else 0) << 6)

    def _apply_duplex(self, mem, rx_raw, tx_raw):
        mem.freq = rx_raw * 10
        tx = tx_raw * 10
        offset = tx - mem.freq
        if offset == 0:
            mem.duplex = ""
            mem.offset = 0
        elif abs(offset) < 100000000:
            mem.duplex = "+" if offset > 0 else "-"
            mem.offset = abs(offset)
        else:
            mem.duplex = "split"
            mem.offset = tx

    def _decode_memory_record(self, number, raw, extd_number=None):
        mem = chirp_common.Memory()
        mem.number = number
        if extd_number:
            mem.extd_number = extd_number
        mem.empty = _is_blank(raw[5:13])
        channel_type = (raw[0] >> 6) & 0x03
        is_digital = channel_type == 0
        mem.extra = self._build_extra(raw, is_digital)

        if mem.empty:
            return mem

        rx_raw = _u32le(raw, 5)
        tx_raw = _u32le(raw, 9)
        self._apply_duplex(mem, rx_raw, tx_raw)

        mem.name = self.filter_name(_decode_string(bytes(raw[32:48])))
        mem.power = POWER_LEVELS[1 if (raw[2] & 0x40) else 0]
        mem.skip = "" if (raw[3] & 0x80) else "S"

        if is_digital:
            mem.mode = "DMR"
            mem.tmode = ""
        else:
            self._get_analog_memory(mem, raw)

        return mem

    def get_memory(self, number):
        if isinstance(number, str) or number < 0:
            name = self._special_name(number)
            return self._decode_memory_record(
                SPECIAL_MEMORIES[name],
                self._vfo_record(name),
                extd_number=name)
        return self._decode_memory_record(number, self._channel_data(number))

    def _build_extra(self, raw, is_digital):
        extra = RadioSettingGroup("extra", "Extra")
        contact_index = _u16le(raw, 17)
        if contact_index >= CONTACT_COUNT:
            contact_index = 0
        rx_group_index = raw[19] if raw[19] != 0xFF else 0
        if rx_group_index > GROUP_COUNT:
            rx_group_index = 0
        encryption_index = _u16le(raw, 20)
        if encryption_index >= ENCRYPTION_SELECTOR_COUNT:
            encryption_index = 0
        channel_id = _bcd_to_int(_u32le(raw, 22))
        if channel_id > 99999999:
            channel_id = 0
        rx_tx = (raw[0] >> 4) & 0x03
        if rx_tx >= len(CHANNEL_RXTX_CHOICES):
            rx_tx = 0
        id_select = (raw[0] >> 3) & 0x01
        dmr_mode = (raw[0] >> 2) & 0x01
        time_slot = (raw[0] >> 1) & 0x01
        digital_monitor = raw[0] & 0x01
        color_code = (raw[1] >> 4) & 0x0F
        if raw[1] == 0xFF:
            color_code = 1
        tot = raw[2] & 0x3F if raw[2] != 0xFF else 0
        call_priority = (raw[3] >> 5) & 0x03
        if call_priority >= len(CHANNEL_CALL_PRIORITY_CHOICES):
            call_priority = 0
        tx_priority = (raw[3] >> 3) & 0x03
        if tx_priority >= len(CHANNEL_TX_PRIORITY_CHOICES):
            tx_priority = 0
        tail_tone = raw[3] & 0x07
        if tail_tone >= len(CHANNEL_TAIL_TONE_CHOICES):
            tail_tone = 0
        ctdcs_select = (raw[4] >> 1) & 0x07
        if ctdcs_select >= len(CHANNEL_CTDCS_SELECT_CHOICES):
            ctdcs_select = 0
        amfm = (raw[4] >> 4) & 0x03
        if amfm >= len(CHANNEL_AMFM_CHOICES):
            amfm = 0
        band = (raw[4] >> 6) & 0x03
        if band >= len(CHANNEL_BAND_CHOICES):
            band = 0
        analog_scramble = raw[1] & 0x0F if raw[1] != 0xFF else 0
        if analog_scramble >= len(CHANNEL_SCRAMBLE_CHOICES):
            analog_scramble = 0
        signaling_id = _u32le(raw, 26) & SIGNALING_ID_MASK
        extras = [
            RadioSetting(
                "raw_mode", "Raw Channel Type",
                RadioSettingValueList(
                    ["DMR", "Analog"],
                    current_index=0 if is_digital else 1)),
            RadioSetting("rx_tx", "RX/TX Permission",
                         RadioSettingValueList(CHANNEL_RXTX_CHOICES,
                                               current_index=rx_tx)),
            RadioSetting("scan_add", "Scan Add",
                         RadioSettingValueBoolean(bool(raw[3] & 0x80))),
            RadioSetting("dmr_id_select", "DMR ID Select",
                         RadioSettingValueList(CHANNEL_ID_SELECT_CHOICES,
                                               current_index=id_select)),
            RadioSetting("dmr_mode", "DMR Mode",
                         RadioSettingValueList(CHANNEL_DMR_MODE_CHOICES,
                                               current_index=dmr_mode)),
            RadioSetting("time_slot", "Time Slot",
                         RadioSettingValueList(["1", "2"],
                                               current_index=time_slot)),
            RadioSetting("color_code", "Color Code",
                         RadioSettingValueInteger(0, 15, color_code)),
            RadioSetting("digital_monitor", "Digital Monitor",
                         RadioSettingValueBoolean(bool(digital_monitor))),
            RadioSetting("call_priority", "Call Priority",
                         RadioSettingValueList(CHANNEL_CALL_PRIORITY_CHOICES,
                                               current_index=call_priority)),
            RadioSetting("tot_index", "TOT Index",
                         RadioSettingValueInteger(0, 42, tot)),
            RadioSetting("contact_index", "Contact Selector Index",
                         RadioSettingValueInteger(0, CONTACT_COUNT - 1,
                                                  contact_index)),
            RadioSetting("rx_group_index", "RX Group Index",
                         RadioSettingValueInteger(0, GROUP_COUNT,
                                                  rx_group_index)),
            RadioSetting(
                "encryption_index", "Encryption Index",
                RadioSettingValueInteger(
                    0, ENCRYPTION_SELECTOR_COUNT - 1,
                    encryption_index)),
            RadioSetting("channel_id", "Channel ID",
                         RadioSettingValueInteger(0, 99999999,
                                                  channel_id)),
            RadioSetting("ctdcs_select", "CTC/DCS Mode",
                         RadioSettingValueList(CHANNEL_CTDCS_SELECT_CHOICES,
                                               current_index=ctdcs_select)),
            RadioSetting("signaling_id_hex", "Signaling ID Hex",
                         RadioSettingValueString(
                             8, 8, "%08X" % signaling_id, autopad=False,
                             charset=HEX_CHARSET)),
            RadioSetting("analog_bcl", "Analog TX Priority",
                         RadioSettingValueList(CHANNEL_TX_PRIORITY_CHOICES,
                                               current_index=tx_priority)),
            RadioSetting("amfm", "Analog Modulation",
                         RadioSettingValueList(CHANNEL_AMFM_CHOICES,
                                               current_index=amfm)),
            RadioSetting("tail_tone", "Tail Tone",
                         RadioSettingValueList(CHANNEL_TAIL_TONE_CHOICES,
                                               current_index=tail_tone)),
            RadioSetting("analog_scramble", "Analog Scramble",
                         RadioSettingValueList(CHANNEL_SCRAMBLE_CHOICES,
                                               current_index=analog_scramble)),
            RadioSetting("bandwidth", "Bandwidth",
                         RadioSettingValueList(CHANNEL_BAND_CHOICES,
                                               current_index=band)),
        ]
        for setting in extras:
            extra.append(setting)
        return extra

    def _base_memory_record(self, mem):
        if isinstance(mem.number, str) or mem.number < 0:
            try:
                raw = self._vfo_record(mem.number)
            except errors.InvalidMemoryLocation:
                raw = None
        elif 1 <= mem.number <= CHANNEL_COUNT:
            raw = self._channel_data(mem.number)
        else:
            raw = None

        if raw is not None and not _is_blank(raw[5:13]):
            return bytearray(raw)
        return bytearray(b"\x00" * CHANNEL_RECORD_SIZE)

    def _encode_memory_record(self, mem):
        if mem.empty:
            return bytearray(b"\xFF" * CHANNEL_RECORD_SIZE)

        is_digital = mem.mode == "DMR"
        raw = self._base_memory_record(mem)
        _set_u32le(raw, 5, mem.freq // 10)
        if mem.duplex == "":
            txfreq = mem.freq
        elif mem.duplex == "-":
            txfreq = mem.freq - mem.offset
        elif mem.duplex == "+":
            txfreq = mem.freq + mem.offset
        elif mem.duplex == "split":
            txfreq = mem.offset
        else:
            raise errors.RadioError("Unsupported duplex mode %r" % mem.duplex)
        _set_u32le(raw, 9, txfreq // 10)
        raw[0] = (raw[0] & 0x3F) | (0x00 if is_digital else 0x40)
        raw[1] = 0x10 if raw[1] == 0xFF else raw[1]
        raw[2] = (
            (0x00 if raw[2] == 0xFF else raw[2]) & 0x3F) | (
                0x40 if _is_high_power(mem.power) else 0x00)
        raw[3] = (
            (0x00 if raw[3] == 0xFF else raw[3]) & 0x7F) | (
                0x80 if mem.skip != "S" else 0x00)
        raw[4] = 0x00 if raw[4] == 0xFF else raw[4]
        raw[32:48] = _encode_string(self.filter_name(mem.name), 16)

        is_digital = mem.mode == "DMR"
        if not is_digital:
            self._set_analog_memory(mem, raw)

        if mem.extra:
            for setting in mem.extra:
                name = setting.get_name()
                value = setting.value
                if name == "raw_mode":
                    is_digital = str(value) == "DMR"
                    raw[0] = (raw[0] & 0x3F) | ((0 if is_digital else 1) << 6)
                elif name == "rx_tx":
                    raw[0] = (
                        (raw[0] & 0xCF) |
                        (_safe_choice_index(CHANNEL_RXTX_CHOICES, value) << 4))
                elif name == "scan_add":
                    raw[3] = (raw[3] & 0x7F) | (0x80 if value else 0x00)
                elif name == "dmr_id_select":
                    if is_digital:
                        raw[0] = (
                            (raw[0] & 0xF7) | (
                                _safe_choice_index(
                                    CHANNEL_ID_SELECT_CHOICES,
                                    value) << 3))
                elif name == "dmr_mode":
                    if is_digital:
                        raw[0] = (
                            (raw[0] & 0xFB) | (
                                _safe_choice_index(
                                    CHANNEL_DMR_MODE_CHOICES,
                                    value) << 2))
                elif name == "time_slot":
                    if is_digital:
                        raw[0] = (
                            (raw[0] & 0xFD) |
                            ((0 if str(value) == "1" else 1) << 1))
                elif name == "color_code":
                    if is_digital:
                        raw[1] = (raw[1] & 0x0F) | ((int(value) & 0x0F) << 4)
                elif name == "digital_monitor":
                    if is_digital:
                        raw[0] = (raw[0] & 0xFE) | (0x01 if value else 0x00)
                elif name == "call_priority":
                    if is_digital:
                        raw[3] = (
                            (raw[3] & 0x9F) |
                            (_safe_choice_index(CHANNEL_CALL_PRIORITY_CHOICES,
                                                value) << 5))
                elif name == "admit_criteria":
                    if is_digital:
                        raw[3] = (raw[3] & 0x9F) | ((int(value) & 0x03) << 5)
                elif name == "tot_index":
                    raw[2] = (raw[2] & 0xC0) | (int(value) & 0x3F)
                elif name == "contact_index":
                    if is_digital:
                        _set_u16le(raw, 17, int(value))
                elif name == "rx_group_index":
                    if is_digital:
                        raw[19] = int(value) & 0xFF
                elif name == "encryption_index":
                    if is_digital:
                        _set_u16le(raw, 20, int(value))
                elif name == "channel_id":
                    if is_digital:
                        _set_u32le(raw, 22, _int_to_bcd(int(value)))
                elif name == "ctdcs_select":
                    raw[4] = (
                        (raw[4] & 0xF1) |
                        (_safe_choice_index(CHANNEL_CTDCS_SELECT_CHOICES,
                                            value) << 1))
                elif name == "signaling_id_hex":
                    _set_u32le(raw, 26, int(str(value), 16)
                               & SIGNALING_ID_MASK)
                elif name == "analog_bcl":
                    if not is_digital:
                        raw[3] = (
                            (raw[3] & 0xE7) |
                            (_safe_choice_index(CHANNEL_TX_PRIORITY_CHOICES,
                                                value) << 3))
                elif name == "amfm":
                    if not is_digital:
                        raw[4] = (
                            (raw[4] & 0xCF) | (
                                _safe_choice_index(
                                    CHANNEL_AMFM_CHOICES,
                                    value) << 4))
                elif name == "tail_tone":
                    if not is_digital:
                        raw[3] = (
                            (raw[3] & 0xF8) | _safe_choice_index(
                                CHANNEL_TAIL_TONE_CHOICES, value))
                elif name == "analog_scramble":
                    if not is_digital:
                        raw[1] = (
                            (raw[1] & 0xF0) | _safe_choice_index(
                                CHANNEL_SCRAMBLE_CHOICES, value))
                elif name == "bandwidth":
                    if not is_digital:
                        raw[4] = (
                            (raw[4] & 0x3F) | (
                                _safe_choice_index(
                                    CHANNEL_BAND_CHOICES,
                                    value) << 6))

        if is_digital:
            raw[0] &= 0x3F
            raw[1] = raw[1] & 0xF0
        else:
            raw[0] = (raw[0] & 0x3F) | 0x40
            if mem.mode not in ("FM", "NFM"):
                mem.mode = "FM"
            self._set_analog_memory(mem, raw)

        return raw

    def set_memory(self, mem):
        raw = self._encode_memory_record(mem)
        if isinstance(mem.number, str) or mem.number < 0:
            self._write_vfo_record(mem.number, raw)
        else:
            self._write_channel(mem.number, raw)

    def _append_bool_setting(self, group, name, label, current):
        group.append(RadioSetting(
            name, label, RadioSettingValueBoolean(bool(current))))

    def _append_int_setting(
            self,
            group,
            name,
            label,
            current,
            minimum,
            maximum,
            default=None):
        if current < minimum or current > maximum:
            current = minimum if default is None else default
        group.append(
            RadioSetting(
                name,
                label,
                RadioSettingValueInteger(
                    minimum,
                    maximum,
                    current)))

    def _append_float_setting(
            self,
            group,
            name,
            label,
            current,
            minimum,
            maximum,
            default=None):
        if current < minimum or current > maximum:
            current = minimum if default is None else default
        group.append(RadioSetting(
            name, label,
            RadioSettingValueFloat(minimum, maximum, current,
                                   resolution=0.00001, precision=5)))

    def _append_list_setting(self, group, name, label, choices, current):
        current = current if 0 <= current < len(choices) else 0
        group.append(
            RadioSetting(
                name,
                label,
                RadioSettingValueList(
                    choices,
                    current_index=current)))

    def _append_named_setting(self, group, cfg, name):
        if name in LIST_BOOL_OFFSETS_BY_NAME:
            offset = LIST_BOOL_OFFSETS_BY_NAME[name]
            self._append_bool_setting(group, name, _setting_label(name),
                                      cfg[offset])
        elif name in CONFIG_LIST_FIELDS_BY_NAME:
            offset, choices = CONFIG_LIST_FIELDS_BY_NAME[name]
            self._append_list_setting(group, name, _setting_label(name),
                                      choices, cfg[offset])
        elif name in CFG2_LIST_FIELDS_BY_NAME:
            vfo = self._get_segment("vfo")
            base = CFG2_OFFSET
            offset, label, choices = CFG2_LIST_FIELDS_BY_NAME[name]
            self._append_list_setting(group, name, label, choices,
                                      vfo[base + offset])
        elif name in CONFIG_INT_FIELDS:
            offset, label, minimum, maximum, kind = CONFIG_INT_FIELDS[name]
            self._append_int_setting(group, name, label,
                                     _get_config_int(cfg, offset, kind),
                                     minimum, maximum,
                                     default=CONFIG_INT_DEFAULTS.get(name))
        elif name in CONFIG_FLOAT_FIELDS:
            offset, label, minimum, maximum, default = (
                CONFIG_FLOAT_FIELDS[name])
            self._append_float_setting(
                group, name, label, _u32le(cfg, offset) / 100000.0,
                minimum, maximum, default=default)
        else:
            raise errors.RadioError("Unknown setting %s" % name)

    def _append_named_settings(self, group, cfg, names):
        for name in names:
            self._append_named_setting(group, cfg, name)

    def _append_frequency_limit_settings(self, group, cfg):
        for number in LOCK_RANGE_NUMBERS:
            status_name = "lock_type_%d" % number
            offset, choices = CONFIG_LIST_FIELDS_BY_NAME[status_name]
            self._append_list_setting(group, status_name,
                                      _setting_label(status_name),
                                      choices, cfg[offset])

            for suffix in ("start", "end"):
                name = "lock_range_%d_%s" % (number, suffix)
                offset, label, minimum, maximum, kind = CONFIG_INT_FIELDS[name]
                self._append_int_setting(group, name, label,
                                         _get_config_int(cfg, offset, kind),
                                         minimum, maximum)

    def _append_cfg2_settings(self, group):
        vfo = self._get_segment("vfo")
        base = CFG2_OFFSET
        for offset, (name, label, choices) in sorted(CFG2_LIST_FIELDS.items()):
            if name in EXPLICIT_SETTING_NAMES:
                continue
            self._append_list_setting(group, name, label, choices,
                                      vfo[base + offset])

        self._append_float_setting(
            group, "cfg2_special_freq", "Spectrum Center Frequency MHz",
            _u32le(vfo, base + 8) / 100000.0, 18.0, 999.99999,
            default=435.125)
        self._append_float_setting(
            group, "cfg2_special_step", "Spectrum Step MHz",
            _u32le(vfo, base + 12) / 100000.0, 0.00001, 5.0,
            default=0.001)
        self._append_int_setting(group, "cfg2_special_rssi",
                                 "Spectrum RSSI Threshold", vfo[base + 16],
                                 0, 255, default=80)
        self._append_int_setting(group, "cfg2_zone_a",
                                 "A Channel Zone", vfo[base + 24] + 1, 1,
                                 ZONE_COUNT)
        self._append_int_setting(group, "cfg2_zone_b",
                                 "B Channel Zone", vfo[base + 25] + 1, 1,
                                 ZONE_COUNT)
        self._append_int_setting(group, "cfg2_channel_a", "A Channel Number",
                                 _u16le(vfo, base + 26) + 1, 1,
                                 CHANNEL_COUNT)
        self._append_int_setting(group, "cfg2_channel_b", "B Channel Number",
                                 _u16le(vfo, base + 28) + 1, 1,
                                 CHANNEL_COUNT)

    def _append_fm_radio_channel_setting(self, group):
        vfo = self._get_segment("vfo")
        base = CFG2_OFFSET
        self._append_int_setting(group, "cfg2_fm_channel",
                                 "FM Radio Channel", vfo[base + 18] + 1, 1,
                                 FM_COUNT)

    def _append_programmable_key_settings(self, group):
        vfo = self._get_segment("vfo")
        base = CFG2_OFFSET
        for offset, (name, label) in sorted(CFG2_KEY_FIELDS.items()):
            self._append_list_setting(group, name, label, CFG2_KEY_FUNCTIONS,
                                      vfo[base + offset])

    def _append_ptt_mic_settings(self, group, cfg):
        self._append_named_settings(group, cfg, PTT_MIC_SETTING_NAMES)

    def _append_dtmf_settings(self, group, cfg):
        self._append_named_settings(group, cfg, DTMF_SETTING_NAMES)

        for index in range(20):
            base = 522 + (index * 16)
            length = cfg[base + 15]
            if length > 14:
                length = 14
            text = _filter_ascii(_decode_string(
                bytes(cfg[base:base + length])), 14)
            group.append(RadioSetting(
                "dtmf_code_%02d" % index,
                "DTMF Code %02d" % (index + 1),
                RadioSettingValueString(0, 14, text, autopad=False),
            ))

    def _append_power_management_settings(self, group, cfg):
        self._append_named_settings(group, cfg, POWER_MANAGEMENT_SETTING_NAMES)

    def _append_screen_display_settings(self, group, cfg):
        self._append_named_settings(group, cfg, SCREEN_DISPLAY_SETTING_NAMES)

    def _append_scan_receive_settings(self, group, cfg):
        self._append_named_settings(group, cfg, SCAN_RECEIVE_SETTING_NAMES)

    def _apply_cfg2_setting(self, vfo, name, value):
        base = CFG2_OFFSET
        if name in CFG2_LIST_FIELDS_BY_NAME:
            offset, _label, choices = CFG2_LIST_FIELDS_BY_NAME[name]
            vfo[base + offset] = (
                choices.index(str(value)) if str(value) in choices else 0)
            return True
        if name in CFG2_KEY_FIELDS_BY_NAME:
            offset, _label = CFG2_KEY_FIELDS_BY_NAME[name]
            vfo[base + offset] = (
                CFG2_KEY_FUNCTIONS.index(str(value))
                if str(value) in CFG2_KEY_FUNCTIONS else 0)
            return True

        if name == "cfg2_special_freq":
            _set_u32le(vfo, base + 8, int(round(float(value) * 100000)))
        elif name == "cfg2_special_step":
            _set_u32le(vfo, base + 12, int(round(float(value) * 100000)))
        elif name == "cfg2_special_rssi":
            vfo[base + 16] = int(value) & 0xFF
        elif name == "cfg2_fm_channel":
            vfo[base + 18] = max(1, min(FM_COUNT, int(value))) - 1
        elif name == "cfg2_zone_a":
            vfo[base + 24] = max(1, min(ZONE_COUNT, int(value))) - 1
        elif name == "cfg2_zone_b":
            vfo[base + 25] = max(1, min(ZONE_COUNT, int(value))) - 1
        elif name == "cfg2_channel_a":
            _set_u16le(vfo, base + 26,
                       max(1, min(CHANNEL_COUNT, int(value))) - 1)
        elif name == "cfg2_channel_b":
            _set_u16le(vfo, base + 28,
                       max(1, min(CHANNEL_COUNT, int(value))) - 1)
        else:
            return False
        return True

    def _fm_needs_defaults(self, fm, base):
        record = fm[base:base + FM_RECORD_SIZE]
        return all(byte == 0xFF
                   for offset, byte in enumerate(record)
                   if offset != 0)

    def _init_fm_record(self, fm, base):
        current_range = fm[base] if 0 <= fm[base] < len(
            FM_RANGE_CHOICES) else 0
        fm[base:base + FM_RECORD_SIZE] = b"\x00" * FM_RECORD_SIZE
        fm[base] = current_range
        _set_u16le(fm, base + 9, 7000)
        _set_fm_bfo(fm, base + 7, 0)
        _set_u16le(fm, base + 18, 520)
        _set_fm_bfo(fm, base + 16, 0)
        _set_u16le(fm, base + 27, 279)
        _set_fm_bfo(fm, base + 25, 0)
        alias_start = base + FM_ALIAS_OFFSET
        alias_end = alias_start + FM_ALIAS_LENGTH
        fm[alias_start:alias_end] = b"\xFF" * FM_ALIAS_LENGTH

    def _apply_fm_setting(self, fm, name, value):
        field, idx_text = name.rsplit("_", 1)
        idx = int(idx_text)
        base = idx * FM_RECORD_SIZE
        if field == "fm_freq" and not str(value).strip():
            fm[base:base + FM_RECORD_SIZE] = b"\xFF" * FM_RECORD_SIZE
            return
        if field != "fm_freq" and field != "fm_range" and _is_blank(
                fm[base:base + FM_RECORD_SIZE]):
            return

        if field in FM_LIST_FIELDS:
            offset, choices = FM_LIST_FIELDS[field]
            fm[base + offset] = _safe_choice_index(choices, value)
        elif field in FM_FREQ_FIELDS:
            offset, multiplier = FM_FREQ_FIELDS[field]
            if self._fm_needs_defaults(fm, base):
                self._init_fm_record(fm, base)
            _set_u16le(fm, base + offset, _fm_freq_raw(value, multiplier))
        elif field in FM_BFO_FIELDS:
            _set_fm_bfo(fm, base + FM_BFO_FIELDS[field], int(value))
        elif field == "fm_alias":
            alias_start = base + FM_ALIAS_OFFSET
            alias_end = alias_start + FM_ALIAS_LENGTH
            fm[alias_start:alias_end] = _encode_string(
                str(value).rstrip(), FM_ALIAS_LENGTH)

    def _append_password_settings(self, group, cfg):
        group.append(RadioSetting(
            "program_password_hex",
            "Program Password (hex, 6 chars max)",
            RadioSettingValueString(0, 24, cfg[:12].hex().upper(),
                                    autopad=False,
                                    charset="0123456789ABCDEF"),
        ))
        self._append_bool_setting(group, "startup_password_enabled",
                                  _setting_label("startup_password_enabled"),
                                  cfg[27])
        group.append(RadioSetting(
            "startup_password",
            "Startup Password (max 16 chars)",
            RadioSettingValueString(0, 16,
                                    _filter_ascii(_decode_string(
                                        bytes(cfg[28:44])), 16),
                                    autopad=False),
        ))

    def _append_identity_settings(self, group, cfg):
        group.append(RadioSetting(
            "radio_name",
            "Radio Name (max 16 chars)",
            RadioSettingValueString(
                0, 16, _filter_ascii(_decode_string(bytes(cfg[76:92])), 16),
                autopad=False),
        ))
        offset, label, minimum, maximum, kind = CONFIG_INT_FIELDS[
            "dmr_radio_id"]
        self._append_int_setting(group, "dmr_radio_id", label,
                                 _get_config_int(cfg, offset, kind),
                                 minimum, maximum)
        group.append(RadioSetting(
            "startup_text",
            "Welcome Message (max 32 chars)",
            RadioSettingValueString(
                0, 32, _filter_ascii(_decode_string(bytes(cfg[44:76])), 32),
                autopad=False),
        ))

    def _append_standard_config_settings(self, general, startup, digital, cfg):
        self._append_int_setting(startup, "startup_line", "Startup Line",
                                 _u16le(cfg, 23), 0, 7)
        self._append_int_setting(startup, "startup_column", "Startup Column",
                                 _u16le(cfg, 25), 0, 127)
        for offset, name in sorted(LIST_BOOL_FIELDS.items()):
            if name in EXPLICIT_SETTING_NAMES:
                continue
            target = startup if offset < 64 else general
            self._append_bool_setting(target, name, _setting_label(name),
                                      cfg[offset])
        for offset, (name, choices) in sorted(CONFIG_LIST_FIELDS.items()):
            if name in EXPLICIT_SETTING_NAMES:
                continue
            if name.startswith(("dmr_", "sms_")):
                target = digital
            else:
                target = general
            self._append_list_setting(target, name, _setting_label(name),
                                      choices, cfg[offset])

        for name, (offset, label, minimum, maximum, kind) in sorted(
                CONFIG_INT_FIELDS.items()):
            if name in EXPLICIT_SETTING_NAMES:
                continue
            if name.startswith("dmr_"):
                target = digital
            else:
                target = general
            self._append_int_setting(target, name, label,
                                     _get_config_int(cfg, offset, kind),
                                     minimum, maximum,
                                     default=CONFIG_INT_DEFAULTS.get(name))

        for name, (offset, label, minimum, maximum, default) in sorted(
                CONFIG_FLOAT_FIELDS.items()):
            if name in EXPLICIT_SETTING_NAMES:
                continue
            self._append_float_setting(
                general, name, label, _u32le(cfg, offset) / 100000.0,
                minimum, maximum, default=default)

    def _append_contact_import_settings(self, group):
        group.set_doc(
            "Edits contact slots 1-%d plus any populated higher slots. "
            "Use the CSV import action to replace or append up to all %d "
            "normal DMR contact slots without rendering every blank slot. "
            "The CSV format is compatible with the OEM four-column local "
            "contacts export: No., Call Type, Contact Alias, Call ID. "
            "Channel Contact Selector Index values are the raw OEM "
            "combo-box indexes stored in channel bytes +17..+18. With "
            "packed contacts these match contact slots, but gaps in the "
            "contact table can make the selector index differ from the "
            "contact slot." %
            (CONTACT_UI_MIN_SLOTS, CONTACT_COUNT))
        group.append(
            RadioSetting(
                "local_contacts_csv_import_mode",
                "Local Contacts CSV Import Mode",
                RadioSettingValueList(
                    LOCAL_CONTACT_IMPORT_MODES,
                    current_index=0)))
        group.append(RadioSetting(
            "local_contacts_csv_import_path",
            "Local Contacts CSV Import Path",
            RadioSettingValueString(
                0, LOCAL_CONTACT_CSV_PATH_LEN, "", autopad=False,
                charset=chirp_common.CHARSET_ASCII)))

    def _append_poweron_image_settings(self, group):
        startup_image = self._get_segment("startup_image")
        group.set_doc(
            "Advanced OEM power-on image writer. Payload is raw monochrome "
            "hex for the OEM 0x9A command: either the first 1024 image bytes "
            "or all 4096 bytes. Normal codeplug upload follows the OEM "
            "checkbox path and writes only block 0; the isolated utility "
            "writer sends all four blocks. Upload is disabled unless "
            "explicitly enabled.")
        group.append(RadioSetting(
            "startup_image_upload",
            "Upload Power-On Image",
            RadioSettingValueBoolean(startup_image[0] == 0x01)))
        group.append(RadioSetting(
            "startup_image_payload_hex",
            "Power-On Image Payload Hex",
            RadioSettingValueString(
                0, STARTUP_IMAGE_HEX_MAX_LEN,
                self._startup_image_payload_hex(), autopad=False,
                charset=HEX_CHARSET)))

    def _append_global_contact_settings(self, group):
        global_contacts = self._get_segment("global_contacts")
        group.set_doc(
            "Advanced OEM 0xA4 global contact database writer. The source CSV "
            "path is local to this computer and is read only during upload. "
            "Rows must have at least seven comma-separated columns; the OEM "
            "format stores the first six fields. CSV rows must be sorted by "
            "DMR ID, matching the OEM CPS warning.")
        group.append(RadioSetting(
            "global_contacts_upload",
            "Upload Global Contacts",
            RadioSettingValueBoolean(global_contacts[0] == 0x01)))
        group.append(RadioSetting(
            "global_contacts_csv_path",
            "Global Contacts CSV Path",
            RadioSettingValueString(
                0, GLOBAL_CONTACT_CSV_PATH_LEN,
                self._global_contacts_path(), autopad=False,
                charset=chirp_common.CHARSET_ASCII)))

    def _append_fm_record_field(self, group, fm, index, blank, field):
        base = index * FM_RECORD_SIZE
        kind = field[0]
        field_name = field[1]
        name = "%s_%02d" % (field_name, index)
        label = "FM %02d %s" % (index + 1, field[2])

        if kind == "list":
            offset, choices = FM_LIST_FIELDS[field_name]
            self._append_list_setting(group, name, label, choices,
                                      fm[base + offset])
        elif kind == "broadcast_freq":
            offset, _multiplier = FM_FREQ_FIELDS[field_name]
            freq = _fm_raw_to_freq(_u16le(fm, base + offset))
            group.append(RadioSetting(
                name, label,
                RadioSettingValueString(
                    0, 8, ("" if not freq else "%.1f" % freq),
                    autopad=False, charset="0123456789.")))
        elif kind == "freq":
            offset, divisor = FM_FREQ_FIELDS[field_name]
            precision, length = field[3:]
            group.append(RadioSetting(
                name, label,
                RadioSettingValueString(
                    0, length,
                    _fm_freq_text(_u16le(fm, base + offset),
                                  divisor, precision),
                    autopad=False, charset="0123456789.")))
        elif kind == "alias":
            offset = FM_ALIAS_OFFSET
            group.append(RadioSetting(
                name, label,
                RadioSettingValueString(
                    0, FM_ALIAS_LENGTH,
                    _filter_ascii(_decode_string(
                        bytes(fm[base + offset:base + offset +
                                 FM_ALIAS_LENGTH])), FM_ALIAS_LENGTH),
                    autopad=False)))
        elif kind == "bfo":
            offset = FM_BFO_FIELDS[field_name]
            self._append_int_setting(group, name, label,
                                     _fm_bfo(fm, base + offset, blank),
                                     -32768, 32767)

    def _append_fm_record_settings(self, group, fm, index):
        base = index * FM_RECORD_SIZE
        blank = _is_blank(fm[base:base + FM_RECORD_SIZE])
        for field in FM_UI_FIELDS:
            self._append_fm_record_field(group, fm, index, blank, field)

    def _append_fm_settings(self, group, fm):
        self._append_fm_radio_channel_setting(group)
        for index in range(FM_COUNT):
            self._append_fm_record_settings(group, fm, index)

    def _append_sms_preset_settings(self, group, sms):
        for index in range(SMS_PRESET_COUNT):
            base = index * SMS_RECORD_SIZE
            if sms[base] not in (0x00, 0xFF):
                continue
            text = _filter_ascii(
                _decode_string(bytes(sms[base + 56:base + 56 + SMS_TEXT_LEN])),
                SMS_TEXT_LEN)
            group.append(RadioSetting(
                "sms_preset_%02d" % index,
                "Preset SMS %02d" % (index + 1),
                RadioSettingValueString(0, SMS_TEXT_LEN, text, autopad=False),
            ))

    def get_settings(self):
        cfg = self._get_segment("cfg")
        fm = self._get_segment("fm")
        sms = self._get_segment("sms")

        identity = RadioSettingGroup("radio_identity", "Radio Identity")
        passwords = RadioSettingGroup("passwords", "Passwords")
        general = RadioSettingGroup("general", "General")
        power_group = RadioSettingGroup("power_management",
                                        "Power Management")
        screen_group = RadioSettingGroup("screen_display",
                                         "Screen & Display")
        ptt_mic = RadioSettingGroup("ptt_mic", "PTT & Mic Setting")
        scan_group = RadioSettingGroup("scan_receive", "Scan & Receive")
        startup = RadioSettingGroup("startup", "Startup")
        frequency_limits = RadioSettingGroup(
            "frequency_range_limits", "Frequency Range Limits")
        digital = RadioSettingGroup("digital", "DMR / SMS")
        dtmf_group = RadioSettingGroup("dtmf", "DTMF")
        contacts_group = RadioSettingGroup("dmr_contacts", "DMR Contacts")
        tg_group = RadioSettingGroup("dmr_tg_lists", "DMR TG Lists")
        encrypt_group = RadioSettingGroup("dmr_encryption", "DMR Encryption")
        cfg2_group = RadioSettingGroup("cfg2", "VFO / CFG2")
        keys_group = RadioSettingGroup(
            "programmable_keys", "Programmable Keys")
        zone_defaults = RadioSettingGroup(
            "zone_defaults", "Zone Default Channels")
        fm_group = RadioSettingGroup("fm", "FM Broadcast")
        poweron_group = RadioSettingGroup("poweron_image", "Power-On Image")
        global_group = RadioSettingGroup("global_contacts", "Global Contacts")
        sms_group = RadioSettingGroup("sms", "Preset SMS")

        self._append_password_settings(passwords, cfg)
        self._append_identity_settings(identity, cfg)
        self._append_standard_config_settings(general, startup, digital, cfg)
        self._append_power_management_settings(power_group, cfg)
        self._append_screen_display_settings(screen_group, cfg)
        self._append_scan_receive_settings(scan_group, cfg)
        self._append_frequency_limit_settings(frequency_limits, cfg)
        self._append_ptt_mic_settings(ptt_mic, cfg)
        self._append_dtmf_settings(dtmf_group, cfg)
        self._append_cfg2_settings(cfg2_group)
        self._append_programmable_key_settings(keys_group)
        self._append_zone_default_settings(zone_defaults)
        self._append_contact_import_settings(contacts_group)
        self._append_contact_settings(contacts_group)
        self._append_group_settings(tg_group)
        self._append_encryption_settings(encrypt_group)
        self._append_poweron_image_settings(poweron_group)
        self._append_global_contact_settings(global_group)
        self._append_fm_settings(fm_group, fm)
        self._append_sms_preset_settings(sms_group, sms)

        return RadioSettings(
            identity,
            general,
            power_group,
            screen_group,
            ptt_mic,
            scan_group,
            startup,
            frequency_limits,
            cfg2_group,
            keys_group,
            digital,
            dtmf_group,
            zone_defaults,
            contacts_group,
            tg_group,
            encrypt_group,
            fm_group,
            poweron_group,
            global_group,
            sms_group,
            passwords)

    def set_settings(self, settings):
        cfg = self._get_segment("cfg")
        zone = self._get_segment("zone")
        if self._zone_table_offset(zone) != ZONE_TABLE_OFFSET:
            zone = self._build_zone_upload()
        contact = self._get_segment("contact")
        group_data = self._get_segment("group")
        encrypt = self._get_segment("encrypt")
        vfo = self._get_segment("vfo")
        fm = self._get_segment("fm")
        sms = self._get_segment("sms")
        startup_image = self._get_segment("startup_image")
        global_contacts = self._get_segment("global_contacts")
        local_contacts_csv_import_mode = "Disabled"
        local_contacts_csv_import_path = ""

        def apply_group(group):
            nonlocal startup_image, global_contacts
            nonlocal local_contacts_csv_import_mode
            nonlocal local_contacts_csv_import_path
            for item in group:
                if isinstance(item, RadioSetting):
                    name = item.get_name()
                    value = item.value
                    if name == "program_password_hex":
                        raw = bytes.fromhex(str(value).strip()[
                                            :24].ljust(24, "F"))
                        cfg[:12] = raw[:12]
                    elif name == "startup_password":
                        cfg[28:44] = _encode_string(str(value).rstrip(), 16)
                    elif name == "startup_text":
                        cfg[44:76] = _encode_string(str(value).rstrip(), 32)
                    elif name == "radio_name":
                        cfg[76:92] = _encode_string(str(value).rstrip(), 16)
                    elif name == "local_contacts_csv_import_mode":
                        local_contacts_csv_import_mode = str(value)
                    elif name == "local_contacts_csv_import_path":
                        local_contacts_csv_import_path = str(value).strip()
                    elif name == "startup_line":
                        _set_u16le(cfg, 23, int(value))
                    elif name == "startup_column":
                        _set_u16le(cfg, 25, int(value))
                    elif name in LIST_BOOL_OFFSETS_BY_NAME:
                        offset = LIST_BOOL_OFFSETS_BY_NAME[name]
                        cfg[offset] = 1 if bool(value) else 0
                    elif name in CONFIG_LIST_FIELDS_BY_NAME:
                        offset, choices = CONFIG_LIST_FIELDS_BY_NAME[name]
                        cfg[offset] = choices.index(
                            str(value)) if str(value) in choices else 0
                    elif name == "zone_a":
                        cfg[134] = int(value) & 0xFF
                    elif name == "channel_a":
                        _set_u16le(cfg, 135, int(value))
                    elif name == "zone_b":
                        cfg[139] = int(value) & 0xFF
                    elif name == "channel_b":
                        _set_u16le(cfg, 140, int(value))
                    elif name == "gps_record_count":
                        _set_u16le(cfg, 191, int(value))
                    elif name in CONFIG_INT_FIELDS:
                        offset, _label, _minimum, _maximum, kind = (
                            CONFIG_INT_FIELDS[name])
                        _set_config_int(cfg, offset, kind, int(value))
                    elif name in CONFIG_FLOAT_FIELDS:
                        offset, _label, _minimum, _maximum, _default = (
                            CONFIG_FLOAT_FIELDS[name])
                        _set_u32le(cfg, offset, int(
                            round(float(value) * 100000)))
                    elif name.startswith("cfg2_"):
                        self._apply_cfg2_setting(vfo, name, value)
                    elif name.startswith("zone_default_"):
                        self._apply_zone_default_setting(zone, name, value)
                    elif name.startswith("dtmf_code_"):
                        idx = int(name.rsplit("_", 1)[1])
                        base = 522 + (idx * 16)
                        encoded = str(value).rstrip().encode(
                            "gbk", errors="ignore")[:14]
                        cfg[base:base + 16] = b"\xFF" * 16
                        cfg[base:base + len(encoded)] = encoded
                        cfg[base + 15] = len(encoded)
                    elif name.startswith("fm_"):
                        self._apply_fm_setting(fm, name, value)
                    elif name == "startup_image_upload":
                        startup_image[0] = 0x01 if bool(value) else 0xFF
                    elif name == "startup_image_payload_hex":
                        self._set_segment("startup_image", startup_image)
                        self._set_startup_image_payload_hex(value)
                        startup_image = self._get_segment("startup_image")
                    elif name == "global_contacts_upload":
                        global_contacts[0] = 0x01 if bool(value) else 0xFF
                    elif name == "global_contacts_csv_path":
                        self._set_segment("global_contacts", global_contacts)
                        self._set_global_contacts_path(value)
                        global_contacts = self._get_segment("global_contacts")
                    elif name.startswith("sms_preset_"):
                        idx = int(name.rsplit("_", 1)[1])
                        base = idx * SMS_RECORD_SIZE
                        text = str(value).rstrip()
                        if text:
                            sms[base] = 0x00
                            sms[base + 1:base + 56] = b"\xFF" * 55
                            sms[base + 56:base + 56 + SMS_TEXT_LEN] = (
                                _encode_string(text, SMS_TEXT_LEN))
                            sms[base +
                                56 +
                                SMS_TEXT_LEN:base +
                                SMS_RECORD_SIZE] = (b"\xFF" *
                                                    (SMS_RECORD_SIZE -
                                                     56 -
                                                     SMS_TEXT_LEN))
                        else:
                            sms[base:base + SMS_RECORD_SIZE] = b"\xFF" * \
                                SMS_RECORD_SIZE
                else:
                    name = item.get_name()
                    if name.startswith("contact_"):
                        self._apply_contact_settings(contact, item)
                    elif name.startswith("tg_"):
                        self._apply_group_settings(group_data, item)
                    elif name.startswith("encrypt_"):
                        self._apply_encryption_settings(encrypt, item)
                    else:
                        apply_group(item)

        apply_group(settings)
        if (local_contacts_csv_import_path and
                local_contacts_csv_import_mode != "Disabled"):
            contact = self._apply_local_contacts_csv(
                contact, local_contacts_csv_import_path,
                local_contacts_csv_import_mode)
        self._set_segment("cfg", cfg)
        self._set_segment("zone", zone)
        self._set_segment("contact", contact)
        self._set_segment("group", group_data)
        self._set_segment("encrypt", encrypt)
        self._set_segment("vfo", vfo)
        self._set_segment("fm", fm)
        self._set_segment("sms", sms)
        self._set_segment("startup_image", startup_image)
        self._set_segment("global_contacts", global_contacts)
        self._password_bytes = bytes(cfg[:12])
