# -*- coding: utf-8 -*-
# Copyright 2026 Piotr Kochanowski <tar4nis@gmail.com>
#
# CHIRP driver for the Retevis H777D-PMR.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""CHIRP driver for the Retevis H777D-PMR radio.

This radio uses the Baofeng BF480 clone protocol for communication.
It supports 16 PMR446 channels with optional names, various tones,
and a wide range of settings exposed by the OEM software.
"""

import logging
import struct

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueList,
)

LOG = logging.getLogger(__name__)


MEM_FORMAT = """
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    ul16 rxtone;
    ul16 txtone;
    u8 unknown12;
    u8 unknown13;
    u8 power_low:1,
       hop_off:1,
       scramble:1,
       unknown14_3:5;
    u8 pttid:2,
       scan_add:1,
       bcl:1,
       unknown15_4:2,
       wide:1,
       unknown15_7:1;
} memory[16];

#seekto 0x0E20;
struct {
    u8 squelch;
    u8 sidekey1_short;
    u8 sidekey1_long;
    u8 save;
    u8 vox_level;
    u8 vox_switch;
    u8 abr;
    u8 dual_watch;
    u8 beep;
    u8 tot;
    u8 unknown0A;
    u8 unknown0B;
    u8 unknown0C;
    u8 unknown0D;
    u8 voice;
    u8 unknown0F;
} settings226;

struct {
    u8 dtmf_side_tone;
    u8 unknown01;
    u8 scan;
    u8 sidekey2_short;
    u8 sidekey2_long;
    u8 a_channel_display;
    u8 b_channel_display;
    u8 global_bcl;
    u8 autolock;
    u8 unknown09;
    u8 unknown0A;
    u8 unknown0B;
    u8 lcd_contrast;
    u8 wait_backlight;
    u8 rx_backlight;
    u8 tx_backlight;
} settings227;

struct {
    u8 alarm_mode;
    u8 unknown01;
    u8 dual_watch_tx_select;
    u8 noise_reduction;
    u8 repeater_tail_clear;
    u8 repeater_tail_detect;
    u8 noaa_channel;
    u8 roger;
    u8 reset_operation;
    u8 unknown09;
    u8 menu_setting:1,
       unknown0A_1:2,
       alarm_sound:1,
       fm_radio_allowed:1,
       unknown0A_5:3;
    u8 unknown0B;
    u8 unknown0C;
    u8 keypad_lock;
    u8 unknown0E;
    u8 unknown0F;
} settings228;

struct {
    u8 unknown00;
    u8 noaa_switch;
    u8 unknown02[14];
} settings229;

#seekto 0x0F20;
struct {
    u8 unknown00[10];
    u8 sidekey3_short;
    u8 sidekey4_short;
    u8 unknown0C[2];
    u8 sidekey3_long;
    u8 sidekey4_long;
} settings242;

#seekto 0x1000;
struct {
    char name[12];
    u8 unused[4];
} names[16];
"""


CMD_ACK = b"\x06"
TX1 = bytes([0x50, 0xBB, 0xFF, 0x20, 0x12, 0x07, 0x25])

READ_BLOCK_SIZE = 0x40
WRITE_BLOCK_SIZE = 0x10

# The vendor CPS reads only these sparse regions.
DOWNLOAD_RANGES = [
    (0x0000, 0x0100),
    (0x0800, 0x1100),
]

# The vendor CPS writes these sparse regions plus one
# fixed 0xFF byte at 0x1800.
UPLOAD_RANGES = [
    (0x0000, 0x0100),
    (0x0800, 0x0810),
    (0x0A00, 0x0D00),
    (0x0E00, 0x0E90),
    (0x0F00, 0x0F70),
    (0x1000, 0x1110),
]
TAIL_BYTE_ADDR = 0x1800
IMAGE_SIZE = TAIL_BYTE_ADDR + 1

NAME_LENGTH = 12
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
VALID_BANDS = [(400000000, 520000000)]
VENDOR_DTCS_CODES = (
    23, 25, 26, 31, 32, 36, 43, 47, 51, 53,
    54, 65, 71, 72, 73, 74, 114, 115, 116, 122,
    125, 131, 132, 134, 143, 145, 152, 155, 156, 162,
    165, 172, 174, 205, 212, 223, 225, 226, 243, 244,
    245, 246, 251, 252, 255, 261, 263, 265, 266, 271,
    274, 306, 311, 315, 325, 331, 332, 343, 346, 351,
    356, 364, 365, 371, 411, 412, 413, 423, 431, 432,
    445, 446, 452, 454, 455, 462, 464, 465, 466, 503,
    506, 516, 523, 526, 532, 546, 565, 606, 612, 624,
    627, 631, 632, 645, 654, 662, 664, 703, 712, 723,
    731, 732, 734, 743, 754,
)
VENDOR_DTCS_COUNT = len(VENDOR_DTCS_CODES)
CTCSS_TONE_TO_RAW = {
    tone: int(round(tone * 10)) for tone in chirp_common.TONES
}
CTCSS_RAW_TO_TONE = {raw: tone for tone, raw in CTCSS_TONE_TO_RAW.items()}

# Note: Memory structure uses bitfields defined in MEM_FORMAT above.
# The following constants are kept for reference but should not be used
# for manual bitmasking - use the bitfield accessors instead.
POWER_LOW_MASK = 0x01
HOP_OFF_MASK = 0x02
SCRAMBLE_MASK = 0x04

PTTID_MASK = 0x03
SCAN_ADD_MASK = 0x04
BCL_MASK = 0x08
WIDE_MASK = 0x40

SQUELCH_LIST = [str(i) for i in range(10)]
VOX_LEVEL_LIST = [str(i) for i in range(1, 11)]

ABR_LIST = ["Off"] + [f"{i} s" for i in range(1, 11)]
TOT_LIST = [f"{seconds} s" for seconds in range(15, 181, 15)]
VOICE_LIST = ["Off", "English"]

SAVE_LIST = ["Off", "On"]
SCAN_LIST = ["Time", "Carrier", "Search"]
CHANNEL_DISPLAY_LIST = ["Channel", "Channel + Name", "Channel + Frequency"]
DTMF_SIDE_TONE_LIST = [
    "Off (All)",
    "Keypad DTMF Side Tone",
    "Send ANI DTMF Side Tone",
    "Keypad + Send ANI Side Tone",
]
BACKLIGHT_LIST = ["Off", "Blue", "Orange", "Purple"]
ALARM_MODE_LIST = ["Site", "Tone", "Code"]
DUAL_WATCH_TX_LIST = ["Off", "A Band", "B Band"]
LCD_CONTRAST_LIST = [str(i) for i in range(1, 10)]
NOAA_CHANNEL_LIST = [str(i) for i in range(1, 11)]
REPEATER_TAIL_LIST = ["Off"] + [f"{i * 100} ms" for i in range(1, 11)]
SIDEKEY_VALUE_LIST = [
    "Off",
    "Monitor",
    "Scan",
    "VOX",
    "High/Low Power",
    "Flashlight",
    "Unknown 6",
    "Unknown 7",
    "Unknown 8",
    "Unknown 9",
    "Unknown 10",
    "Emergency Alarm",
    "Channel Lock",
]


def _enter_programming_mode(serial):
    serial.timeout = 1
    try:
        serial.rts = True
        serial.dtr = True
    except Exception:
        pass

    last_error = "Bad ACK after TX1: b''"
    for _ in range(4):
        serial.write(TX1)
        ack = serial.read(1)
        if ack != CMD_ACK:
            last_error = f"Bad ACK after TX1: {ack!r}"
            continue

        serial.write(b"\x02")
        ident = serial.read(8)
        if len(ident) != 8:
            last_error = f"Short ident: {len(ident)} bytes"
            continue

        serial.write(CMD_ACK)
        ack = serial.read(1)
        if ack != CMD_ACK:
            last_error = f"Bad ACK after ident ACK: {ack!r}"
            continue

        return ident

    raise errors.RadioError(last_error)


def _exit_programming_mode(serial):
    try:
        serial.write(CMD_ACK)
    except Exception:
        pass


def _iter_blocks(ranges, block_size):
    """Iterate over blocks in given ranges with specified block size."""
    for start, end in ranges:
        yield from range(start, end, block_size)


def _ranges_size(ranges):
    return sum(end - start for start, end in ranges)


def _read_block(radio, addr):
    """Read one 64-byte block using the BF480 sparse-read protocol."""
    ser = radio.pipe
    cmd = struct.pack(">cHB", b"S", addr, READ_BLOCK_SIZE)
    expected_tail = cmd[1:]
    ser.write(cmd)

    resp = ser.read(1 + 4 + READ_BLOCK_SIZE)
    if len(resp) < 4 + READ_BLOCK_SIZE:
        raise errors.RadioError(f"Short read @ {addr:04X}: {len(resp)} bytes")

    if resp[:1] == CMD_ACK and len(resp) >= 1 + 4 + READ_BLOCK_SIZE:
        resp = resp[1:]

    hdr = resp[:4]
    if hdr[:1] not in (b"W", b"X"):
        raise errors.RadioError(f"Bad response header @ {addr:04X}: {hdr!r}")
    if hdr[1:] != expected_tail:
        raise errors.RadioError(f"Bad response header @ {addr:04X}: {hdr!r}")

    data = resp[4:4 + READ_BLOCK_SIZE]
    ser.write(CMD_ACK)
    return data


def _write_block(radio, addr, data):
    """Write one block. The vendor uses 16-byte writes plus one final byte."""
    ser = radio.pipe
    size = len(data)

    cmd = struct.pack(">cHB", b"X", addr, size) + data
    ser.write(cmd)
    ack = b""
    for _ in range(4):
        ack = ser.read(1)
        if ack == CMD_ACK:
            return
        # Some units occasionally emit a stray NUL byte between write ACKs.
        if ack == b"\x00":
            continue
        break
    raise errors.RadioError(f"No ACK after write @ {addr:04X}: {ack!r}")


def do_download(radio):
    """Download memory from radio."""
    _enter_programming_mode(radio.pipe)

    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.cur = 0
    status.max = _ranges_size(DOWNLOAD_RANGES)

    data = bytearray(b"\xFF" * radio._memsize)
    done = 0

    try:
        for addr in _iter_blocks(DOWNLOAD_RANGES, READ_BLOCK_SIZE):
            block = _read_block(radio, addr)
            data[addr:addr + READ_BLOCK_SIZE] = block
            done += READ_BLOCK_SIZE
            status.cur = min(done, status.max)
            radio.status_fn(status)
    finally:
        _exit_programming_mode(radio.pipe)

    return memmap.MemoryMapBytes(bytes(data))


def do_upload(radio):
    """Upload memory to radio."""
    # The vendor CPS always writes a literal 0xFF at 0x1800.
    radio.pipe.timeout = 1
    _enter_programming_mode(radio.pipe)

    status = chirp_common.Status()
    status.msg = "Uploading to radio"
    status.cur = 0
    status.max = _ranges_size(UPLOAD_RANGES) + 1

    image = radio.get_mmap().get_byte_compatible()
    done = 0

    try:
        for addr in _iter_blocks(UPLOAD_RANGES, WRITE_BLOCK_SIZE):
            _write_block(radio, addr, image[addr:addr + WRITE_BLOCK_SIZE])
            done += WRITE_BLOCK_SIZE
            status.cur = min(done, status.max)
            radio.status_fn(status)

        # Write the mandatory tail byte (always 0xFF)
        _write_block(radio, TAIL_BYTE_ADDR, b"\xFF")
        status.cur = status.max
        radio.status_fn(status)
    finally:
        _exit_programming_mode(radio.pipe)


@directory.register
class RetevisH777D(chirp_common.CloneModeRadio):
    """Retevis H777D-PMR (BF480 protocol)

    This radio uses the Baofeng BF480 clone protocol for communication.
    It supports 16 PMR446 channels with optional names, various tones,
    and a wide range of settings exposed by the OEM software.
    """

    VENDOR = "Retevis"
    MODEL = "H777D"
    VARIANT = "PMR"

    BAUD_RATE = 9600
    HARDWARE_FLOW = False
    _memsize = IMAGE_SIZE

    POWER_LEVELS = [
        chirp_common.PowerLevel("Low", dBm=0),
        chirp_common.PowerLevel("High", dBm=1),
    ]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_name = True
        rf.has_bank = False
        rf.has_tuning_step = False

        rf.valid_modes = ["NFM", "FM"]
        rf.valid_skips = ["", "S"]
        # Memory channels are validated against this list even when the
        # radio does not store a per-channel tuning step. PMR446 channels
        # are spaced at 12.5 kHz, but the 446.00625 MHz base requires
        # 6.25 kHz resolution for absolute-frequency validation.
        rf.valid_tuning_steps = [6.25, 12.5]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS",
        ]
        # Explicit RX and TX frequencies, not
        # repeater-style +/- offsets. Use simplex or exact split TX.
        rf.valid_duplexes = ["", "split"]
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.can_odd_split = True

        rf.memory_bounds = (1, 16)
        rf.valid_bands = VALID_BANDS
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_dtcs_codes = list(VENDOR_DTCS_CODES)
        rf.valid_name_length = NAME_LENGTH
        rf.valid_characters = chirp_common.CHARSET_ASCII
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as exc:
            LOG.exception("Unexpected error during download")
            raise errors.RadioError(
                "Unexpected error communicating with radio") from exc
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as exc:
            LOG.exception("Unexpected error during upload")
            raise errors.RadioError(
                "Unexpected error communicating with radio") from exc

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    @staticmethod
    def _setting_index(value, choices):
        value = int(value)
        if value < 0 or value >= len(choices):
            return 0
        return value

    @staticmethod
    def _optional_setting_index(value, choices):
        value = int(value)
        if value < 0 or value >= len(choices):
            return None
        return value

    def _decode_tone(self, memval):
        raw = int(memval)

        if raw in (0, 0xFFFF):
            return "", None, None
        if 1 <= raw <= VENDOR_DTCS_COUNT:
            return "DTCS", VENDOR_DTCS_CODES[raw - 1], "N"
        if VENDOR_DTCS_COUNT < raw <= VENDOR_DTCS_COUNT * 2:
            return "DTCS", VENDOR_DTCS_CODES[raw - VENDOR_DTCS_COUNT - 1], "R"
        if raw in CTCSS_RAW_TO_TONE:
            return "Tone", CTCSS_RAW_TO_TONE[raw], None

        LOG.warning("Unknown tone encoding 0x%04X", raw)
        return "", None, None

    def _encode_tone(self, memval, mode, value, polarity):
        if mode == "":
            raw = 0xFFFF
        elif mode == "Tone":
            raw = int(round(float(value) * 10))
        elif mode == "DTCS":
            index = VENDOR_DTCS_CODES.index(value) + 1
            if polarity == "R":
                raw = index + VENDOR_DTCS_COUNT
            else:
                raw = index
        else:
            raise errors.RadioError(f"Unsupported tone mode: {mode}")

        memval.set_value(raw)

    def _decode_name(self, name_entry):
        name = ""
        for char in name_entry.name:
            value = str(char)
            if value in ("\x00", "\xFF"):
                value = " "
            name += value
        return name.rstrip()

    def _apply_tone_fields(self, mem, txtone, rxtone):
        # Use CHIRP's standard tone presentation: matching TX/RX pairs
        # collapse to TSQL/DTCS, and only mismatched pairs remain Cross.
        chirp_common.split_tone_decode(mem, txtone, rxtone)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _name = self._memobj.names[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        raw_rx = _mem.rxfreq.get_raw()
        if raw_rx in (b"\x00\x00\x00\x00", b"\xFF\xFF\xFF\xFF"):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10
        if not mem.freq:
            mem.empty = True
            return mem

        raw_tx = _mem.txfreq.get_raw()
        if raw_tx in (b"\x00\x00\x00\x00", b"\xFF\xFF\xFF\xFF"):
            mem.duplex = ""
            mem.offset = 0
        else:
            txfreq = int(_mem.txfreq) * 10
            if txfreq == mem.freq:
                mem.duplex = ""
                mem.offset = 0
            else:
                mem.duplex = "split"
                mem.offset = txfreq

        mem.mode = "FM" if _mem.wide else "NFM"
        # The radio does not store a per-channel tuning step, but CHIRP
        # still validates the hidden field on edit. Use the channel-plan
        # spacing so existing rows do not retain the default 5.0 kHz value.
        mem.tuning_step = 12.5
        mem.power = (self.POWER_LEVELS[0]
                     if _mem.power_low
                     else self.POWER_LEVELS[1])
        mem.skip = "" if _mem.scan_add else "S"
        mem.name = self._decode_name(_name)

        txtone = self._decode_tone(_mem.txtone)
        rxtone = self._decode_tone(_mem.rxtone)
        self._apply_tone_fields(mem, txtone, rxtone)

        mem.extra = RadioSettingGroup("extra", "Extra")
        mem.extra.append(
            RadioSetting(
                "pttid",
                "PTT-ID",
                RadioSettingValueList(PTTID_LIST,
                                      current_index=int(_mem.pttid)),
            )
        )
        mem.extra.append(
            RadioSetting(
                "bcl",
                "Busy Channel Lockout",
                RadioSettingValueBoolean(bool(_mem.bcl)),
            )
        )
        mem.extra.append(
            RadioSetting(
                "scramble",
                "Scramble",
                RadioSettingValueBoolean(bool(_mem.scramble)),
            )
        )
        mem.extra.append(
            RadioSetting(
                "hopping",
                "Frequency Hopping",
                RadioSettingValueBoolean(not bool(_mem.hop_off)),
            )
        )

        return mem

    def get_settings(self):
        _s226 = self._memobj.settings226
        _s227 = self._memobj.settings227
        _s228 = self._memobj.settings228
        _s229 = self._memobj.settings229
        _s242 = self._memobj.settings242

        basic = RadioSettingGroup("basic", "Basic Settings")
        display = RadioSettingGroup("display", "Display")
        sidekeys = RadioSettingGroup("sidekeys", "Side Key Functions")
        hidden = RadioSettingGroup("hidden", "Undocumented")

        rs = RadioSetting("squelch", "Squelch",
                          RadioSettingValueList(
                              SQUELCH_LIST,
                              current_index=self._setting_index(
                                  _s226.squelch, SQUELCH_LIST)))
        basic.append(rs)
        rs = RadioSetting("vox_switch", "VOX Switch",
                          RadioSettingValueBoolean(bool(_s226.vox_switch)))
        basic.append(rs)
        rs = RadioSetting("vox_level", "VOX Level",
                          RadioSettingValueList(
                              VOX_LEVEL_LIST,
                              current_index=self._setting_index(
                                  _s226.vox_level, VOX_LEVEL_LIST)))
        basic.append(rs)
        rs = RadioSetting("voice", "Voice Language",
                          RadioSettingValueList(
                              VOICE_LIST,
                              current_index=self._setting_index(_s226.voice,
                                                                VOICE_LIST)))
        basic.append(rs)
        rs = RadioSetting("tot", "Time Out Timer (TOT)",
                          RadioSettingValueList(
                              TOT_LIST,
                              current_index=self._setting_index(_s226.tot,
                                                                TOT_LIST)))
        basic.append(rs)
        rs = RadioSetting("roger", "Roger",
                          RadioSettingValueBoolean(bool(_s228.roger)))
        basic.append(rs)
        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(bool(_s226.beep)))
        basic.append(rs)
        rs = RadioSetting("save", "Save Battery",
                          RadioSettingValueList(
                              SAVE_LIST,
                              current_index=self._setting_index(_s226.save,
                                                                SAVE_LIST)))
        basic.append(rs)
        rs = RadioSetting("scan", "Scan",
                          RadioSettingValueList(
                              SCAN_LIST,
                              current_index=self._setting_index(_s227.scan,
                                                                SCAN_LIST)))
        basic.append(rs)
        rs = RadioSetting("autolock", "Auto Lock",
                          RadioSettingValueBoolean(bool(_s227.autolock)))
        basic.append(rs)
        rs = RadioSetting("alarm_mode", "Alarm Mode",
                          RadioSettingValueList(
                              ALARM_MODE_LIST,
                              current_index=self._setting_index(
                                  _s228.alarm_mode, ALARM_MODE_LIST)))
        basic.append(rs)

        rs = RadioSetting("abr", "Backlight Timeout",
                          RadioSettingValueList(
                              ABR_LIST,
                              current_index=self._setting_index(_s226.abr,
                                                                ABR_LIST)))
        display.append(rs)
        rs = RadioSetting("lcd_contrast", "LCD Contrast",
                          RadioSettingValueList(
                              LCD_CONTRAST_LIST,
                              current_index=self._setting_index(
                                  _s227.lcd_contrast, LCD_CONTRAST_LIST)))
        display.append(rs)
        rs = RadioSetting("wait_backlight", "Wait Backlight",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=self._setting_index(
                                  _s227.wait_backlight, BACKLIGHT_LIST)))
        display.append(rs)
        rs = RadioSetting("rx_backlight", "RX Backlight",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=self._setting_index(
                                  _s227.rx_backlight, BACKLIGHT_LIST)))
        display.append(rs)
        rs = RadioSetting("tx_backlight", "TX Backlight",
                          RadioSettingValueList(
                              BACKLIGHT_LIST,
                              current_index=self._setting_index(
                                  _s227.tx_backlight, BACKLIGHT_LIST)))
        display.append(rs)

        rs = RadioSetting("sidekey1_short", "Side Key 1 Short Press",
                          RadioSettingValueList(
                              SIDEKEY_VALUE_LIST,
                              current_index=self._setting_index(
                                  _s226.sidekey1_short, SIDEKEY_VALUE_LIST)))
        sidekeys.append(rs)
        rs = RadioSetting("sidekey1_long", "Side Key 1 Long Press",
                          RadioSettingValueList(
                              SIDEKEY_VALUE_LIST,
                              current_index=self._setting_index(
                                  _s226.sidekey1_long, SIDEKEY_VALUE_LIST)))
        sidekeys.append(rs)
        rs = RadioSetting("sidekey2_short", "Side Key 2 Short Press",
                          RadioSettingValueList(
                              SIDEKEY_VALUE_LIST,
                              current_index=self._setting_index(
                                  _s227.sidekey2_short, SIDEKEY_VALUE_LIST)))
        sidekeys.append(rs)
        rs = RadioSetting("sidekey2_long", "Side Key 2 Long Press",
                          RadioSettingValueList(
                              SIDEKEY_VALUE_LIST,
                              current_index=self._setting_index(
                                  _s227.sidekey2_long, SIDEKEY_VALUE_LIST)))
        sidekeys.append(rs)

        rs = RadioSetting("menu_setting", "Menu Setting",
                          RadioSettingValueBoolean(bool(_s228.menu_setting)))
        hidden.append(rs)
        rs = RadioSetting("reset_operation", "Reset Operation",
                          RadioSettingValueBoolean(
                              bool(_s228.reset_operation)))
        hidden.append(rs)
        rs = RadioSetting("a_channel_display", "A Channel Display Mode",
                          RadioSettingValueList(
                              CHANNEL_DISPLAY_LIST,
                              current_index=self._setting_index(
                                  _s227.a_channel_display,
                                  CHANNEL_DISPLAY_LIST)))
        hidden.append(rs)
        rs = RadioSetting("b_channel_display", "B Channel Display Mode",
                          RadioSettingValueList(
                              CHANNEL_DISPLAY_LIST,
                              current_index=self._setting_index(
                                  _s227.b_channel_display,
                                  CHANNEL_DISPLAY_LIST)))
        hidden.append(rs)
        rs = RadioSetting("dtmf_side_tone", "DTMF Side Tone",
                          RadioSettingValueList(
                              DTMF_SIDE_TONE_LIST,
                              current_index=self._setting_index(
                                  _s227.dtmf_side_tone,
                                  DTMF_SIDE_TONE_LIST)))
        hidden.append(rs)
        rs = RadioSetting("global_bcl", "Busy Channel Lockout (Global)",
                          RadioSettingValueBoolean(bool(_s227.global_bcl)))
        hidden.append(rs)
        rs = RadioSetting("keypad_lock", "Keypad Lock",
                          RadioSettingValueBoolean(bool(_s228.keypad_lock)))
        hidden.append(rs)
        rs = RadioSetting("noise_reduction", "Noise Reduction",
                          RadioSettingValueBoolean(
                              bool(_s228.noise_reduction)))
        hidden.append(rs)
        rs = RadioSetting("fm_radio_allowed", "FM Radio Allowed",
                          RadioSettingValueBoolean(
                              bool(_s228.fm_radio_allowed)))
        hidden.append(rs)
        rs = RadioSetting("alarm_sound", "Alarm Sound",
                          RadioSettingValueBoolean(bool(_s228.alarm_sound)))
        hidden.append(rs)
        rs = RadioSetting("dual_watch", "Dual Watch",
                          RadioSettingValueBoolean(bool(_s226.dual_watch)))
        hidden.append(rs)
        rs = RadioSetting("dual_watch_tx_select", "Dual Watch TX Select",
                          RadioSettingValueList(
                              DUAL_WATCH_TX_LIST,
                              current_index=self._setting_index(
                                  _s228.dual_watch_tx_select,
                                  DUAL_WATCH_TX_LIST)))
        hidden.append(rs)
        rs = RadioSetting("noaa_channel", "NOAA Channel",
                          RadioSettingValueList(
                              NOAA_CHANNEL_LIST,
                              current_index=self._setting_index(
                                  _s228.noaa_channel, NOAA_CHANNEL_LIST)))
        hidden.append(rs)
        rs = RadioSetting("noaa_switch", "NOAA Switch",
                          RadioSettingValueBoolean(bool(_s229.noaa_switch)))
        hidden.append(rs)
        rs = RadioSetting("repeater_tail_clear", "Repeater Tail Clear",
                          RadioSettingValueList(
                              REPEATER_TAIL_LIST,
                              current_index=self._setting_index(
                                  _s228.repeater_tail_clear,
                                  REPEATER_TAIL_LIST)))
        hidden.append(rs)
        rs = RadioSetting("repeater_tail_detect", "Repeater Tail Detect",
                          RadioSettingValueList(
                              REPEATER_TAIL_LIST,
                              current_index=self._setting_index(
                                  _s228.repeater_tail_detect,
                                  REPEATER_TAIL_LIST)))
        hidden.append(rs)
        sidekey3_short_idx = self._optional_setting_index(
            _s242.sidekey3_short, SIDEKEY_VALUE_LIST)
        if sidekey3_short_idx is not None:
            rs = RadioSetting("sidekey3_short", "Side Key 3 Short Press",
                              RadioSettingValueList(
                                  SIDEKEY_VALUE_LIST,
                                  current_index=sidekey3_short_idx))
            hidden.append(rs)

        sidekey4_short_idx = self._optional_setting_index(
            _s242.sidekey4_short, SIDEKEY_VALUE_LIST)
        if sidekey4_short_idx is not None:
            rs = RadioSetting("sidekey4_short", "Side Key 4 Short Press",
                              RadioSettingValueList(
                                  SIDEKEY_VALUE_LIST,
                                  current_index=sidekey4_short_idx))
            hidden.append(rs)

        sidekey3_long_idx = self._optional_setting_index(
            _s242.sidekey3_long, SIDEKEY_VALUE_LIST)
        if sidekey3_long_idx is not None:
            rs = RadioSetting("sidekey3_long", "Side Key 3 Long Press",
                              RadioSettingValueList(
                                  SIDEKEY_VALUE_LIST,
                                  current_index=sidekey3_long_idx))
            hidden.append(rs)

        sidekey4_long_idx = self._optional_setting_index(
            _s242.sidekey4_long, SIDEKEY_VALUE_LIST)
        if sidekey4_long_idx is not None:
            rs = RadioSetting("sidekey4_long", "Side Key 4 Long Press",
                              RadioSettingValueList(
                                  SIDEKEY_VALUE_LIST,
                                  current_index=sidekey4_long_idx))
            hidden.append(rs)

        return RadioSettings(basic, display, sidekeys, hidden)

    def set_memory(self, memory):
        _mem = self._memobj.memory[memory.number - 1]
        _name = self._memobj.names[memory.number - 1]

        if memory.empty:
            _mem.set_raw(b"\xFF" * (_mem.size() // 8))
            _name.set_raw(b"\xFF" * (_name.size() // 8))
            return

        _mem.set_raw(b"\x00" * (_mem.size() // 8))

        _mem.rxfreq = memory.freq / 10

        if memory.duplex == "off":
            _mem.txfreq.fill_raw(b'\xFF')
        elif memory.duplex == "split":
            _mem.txfreq = memory.offset / 10
        elif memory.duplex == "+":
            _mem.txfreq = (memory.freq + memory.offset) / 10
        elif memory.duplex == "-":
            _mem.txfreq = (memory.freq - memory.offset) / 10
        else:
            _mem.txfreq = memory.freq / 10

        txtone, rxtone = chirp_common.split_tone_encode(memory)
        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)

        _mem.power_low = 0
        _mem.hop_off = 0
        _mem.scramble = 0
        _mem.pttid = 0
        _mem.scan_add = 0
        _mem.bcl = 0
        _mem.wide = 0

        if memory.power == self.POWER_LEVELS[0]:
            _mem.power_low = 1
        if memory.mode == "FM":
            _mem.wide = 1
        if memory.skip != "S":
            _mem.scan_add = 1

        mem_name = (memory.name or "").encode(
            "ascii", errors="ignore")[:NAME_LENGTH]
        for i in range(NAME_LENGTH):
            try:
                _name.name[i] = chr(mem_name[i])
            except IndexError:
                _name.name[i] = "\xFF"

        for setting in memory.extra or []:
            name = setting.get_name()
            if name == "pttid":
                _mem.pttid = PTTID_LIST.index(str(setting.value))
            elif name == "bcl":
                _mem.bcl = 1 if int(setting.value) else 0
            elif name == "scramble":
                _mem.scramble = 1 if int(setting.value) else 0
            elif name == "hopping":
                _mem.hop_off = 0 if int(setting.value) else 1

    def set_settings(self, settings):
        _s226 = self._memobj.settings226
        _s227 = self._memobj.settings227
        _s228 = self._memobj.settings228
        _s229 = self._memobj.settings229
        _s242 = self._memobj.settings242

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            name = element.get_name()

            if name == "squelch":
                _s226.squelch = SQUELCH_LIST.index(str(element.value))
            elif name == "vox_switch":
                _s226.vox_switch = int(element.value)
            elif name == "vox_level":
                _s226.vox_level = VOX_LEVEL_LIST.index(str(element.value))
            elif name == "voice":
                _s226.voice = VOICE_LIST.index(str(element.value))
            elif name == "abr":
                _s226.abr = ABR_LIST.index(str(element.value))
            elif name == "tot":
                _s226.tot = TOT_LIST.index(str(element.value))
            elif name == "roger":
                _s228.roger = int(element.value)
            elif name == "beep":
                _s226.beep = int(element.value)
            elif name == "save":
                _s226.save = SAVE_LIST.index(str(element.value))
            elif name == "scan":
                _s227.scan = SCAN_LIST.index(str(element.value))
            elif name == "autolock":
                _s227.autolock = int(element.value)
            elif name == "alarm_mode":
                _s228.alarm_mode = ALARM_MODE_LIST.index(str(element.value))
            elif name == "lcd_contrast":
                _s227.lcd_contrast = LCD_CONTRAST_LIST.index(
                    str(element.value))
            elif name == "wait_backlight":
                _s227.wait_backlight = BACKLIGHT_LIST.index(str(element.value))
            elif name == "rx_backlight":
                _s227.rx_backlight = BACKLIGHT_LIST.index(str(element.value))
            elif name == "tx_backlight":
                _s227.tx_backlight = BACKLIGHT_LIST.index(str(element.value))
            elif name == "sidekey1_short":
                _s226.sidekey1_short = SIDEKEY_VALUE_LIST.index(
                    str(element.value))
            elif name == "sidekey1_long":
                _s226.sidekey1_long = SIDEKEY_VALUE_LIST.index(
                    str(element.value))
            elif name == "sidekey2_short":
                _s227.sidekey2_short = SIDEKEY_VALUE_LIST.index(
                    str(element.value))
            elif name == "sidekey2_long":
                _s227.sidekey2_long = SIDEKEY_VALUE_LIST.index(
                    str(element.value))
            elif name == "menu_setting":
                _s228.menu_setting = int(bool(element.value))
            elif name == "reset_operation":
                _s228.reset_operation = int(element.value)
            elif name == "a_channel_display":
                _s227.a_channel_display = CHANNEL_DISPLAY_LIST.index(
                    str(element.value))
            elif name == "b_channel_display":
                _s227.b_channel_display = CHANNEL_DISPLAY_LIST.index(
                    str(element.value))
            elif name == "dtmf_side_tone":
                _s227.dtmf_side_tone = DTMF_SIDE_TONE_LIST.index(
                    str(element.value))
            elif name == "global_bcl":
                _s227.global_bcl = int(element.value)
            elif name == "keypad_lock":
                _s228.keypad_lock = int(element.value)
            elif name == "noise_reduction":
                _s228.noise_reduction = int(element.value)
            elif name == "fm_radio_allowed":
                _s228.fm_radio_allowed = int(bool(element.value))
            elif name == "alarm_sound":
                _s228.alarm_sound = int(bool(element.value))
            elif name == "dual_watch":
                _s226.dual_watch = int(element.value)
            elif name == "dual_watch_tx_select":
                _s228.dual_watch_tx_select = DUAL_WATCH_TX_LIST.index(
                    str(element.value))
            elif name == "noaa_channel":
                _s228.noaa_channel = NOAA_CHANNEL_LIST.index(
                    str(element.value))
            elif name == "noaa_switch":
                _s229.noaa_switch = int(element.value)
            elif name == "repeater_tail_clear":
                _s228.repeater_tail_clear = REPEATER_TAIL_LIST.index(
                    str(element.value))
            elif name == "repeater_tail_detect":
                _s228.repeater_tail_detect = REPEATER_TAIL_LIST.index(
                    str(element.value))
            elif name == "sidekey3_short":
                _s242.sidekey3_short = SIDEKEY_VALUE_LIST.index(
                    str(element.value))
            elif name == "sidekey4_short":
                _s242.sidekey4_short = SIDEKEY_VALUE_LIST.index(
                    str(element.value))
            elif name == "sidekey3_long":
                _s242.sidekey3_long = SIDEKEY_VALUE_LIST.index(
                    str(element.value))
            elif name == "sidekey4_long":
                _s242.sidekey4_long = SIDEKEY_VALUE_LIST.index(
                    str(element.value))

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is matched via metadata, not by old-style image probing.
        return False
