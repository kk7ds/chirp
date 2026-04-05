# Copyright 2026 Tony Gies <tgies@tgies.net>
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

"""Retevis C2 GMRS radio driver.

The C2 uses a DLE-stuffed STX/ETX serial protocol at 115200 baud.
"""

import logging
import time


from chirp import bandplan_na, bitwise, chirp_common, directory
from chirp import errors, memmap
from chirp.settings import (
    MemSetting,
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueMap,
    RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
u8 ident_data[28];        // 0x0000  firmware/hardware ident (read-only)
ul32 local_id;            // 0x001C
ul32 settings_0020;       // 0x0020  bit0=voice prompt
ul32 unknown_0024;        // 0x0024
ul32 power_save;          // 0x0028
ul32 unknown_002c;        // 0x002C
ul32 unknown_0030;        // 0x0030
ul32 unknown_0034;        // 0x0034
ul32 vox_packed;          // 0x0038  vox_level*4 + (1=on, 2=off)
ul32 unknown_003c;        // 0x003C
ul32 sk_short;            // 0x0040  key assignment
ul32 sk_long;             // 0x0044  key assignment (0xFFFFFFFF=None)
ul32 pf1_short;           // 0x0048  key assignment
ul32 pf1_long;            // 0x004C  key assignment
ul32 pf2_short;           // 0x0050  key assignment
ul32 pf2_long;            // 0x0054  key assignment

#seekto 0x0080;
ul32 tot;                 // 0x0080  seconds (0=Off)
ul32 unknown_0084;        // 0x0084
ul32 freq_step;           // 0x0088  Hz

#seekto 0x0090;
ul32 scan_mode;           // 0x0090  0=Search, 1=Carrier, 2=Time
ul32 keytone;             // 0x0094  0=Off, 1=On

#seekto 0x0118;
ul32 vox_delay;           // 0x0118  ms

#seekto 0x019C;
ul32 unknown_019c[4];     // 0x019C

#seekto 0x01BC;
ul32 recorder;            // 0x01BC  0=Off, 1=On
ul32 work_mode;           // 0x01C0  0=Channel, 1=Memory
ul32 unknown_01c4;        // 0x01C4
ul32 squelch;             // 0x01C8  1-9 (Sq Level)
ul32 unknown_01cc;        // 0x01CC
ul32 unknown_01d0;        // 0x01D0
ul32 ai_denoise_packed;   // 0x01D4  bits 0:1 = AI denoise enable
ul32 unknown_01d8;        // 0x01D8
ul32 ctcss_tail_tone;     // 0x01DC  CTCSS tail freq (freq*40+2)
ul32 cdcss_tail_tone;     // 0x01E0  CDCSS tail freq (freq*40+2)
ul32 no_ctcss_tail_freq;  // 0x01E4  NO CTCSS tail freq (Hz*10)
u8 unknown_01e8[6];       // 0x01E8
il16 micgain_analog;      // 0x01EE  -3 to 3

#seekto 0x0330;
char dtmf_local_id[8];    // 0x0330
u8 unknown_0338;          // 0x0338
u8 unknown_0339;          // 0x0339
char dtmf_sep_code;       // 0x033A
char dtmf_group_code;     // 0x033B
ul16 unknown_033c;        // 0x033C
ul16 dtmf_first_time;    // 0x033E  0.5ms units (e.g. 400=200ms)

#seekto 0x0347;
u8 tot_warning;           // 0x0347  value << 4 (0=Off, 1-10)

#seekto 0x035C;
ul32 settings_035c;     // 0x035C  byte0=tx_start_beep, bytes1-3=pri_ch

#seekto 0x0360;
struct {
    u8 cfg_unk0:1,        // +00 bit 7
       highpower:1,       //     bit 6
       cfg_unk1:1,        //     bit 5
       busylock:1,        //     bit 4
       talkaround:1,      //     bit 3
       cfg_unk2:3;        //     bits 2-0 (default 0b101)
    ul16 bandwidth;       // +01  25000=Wide, 12500=Narrow
    u8 pad0;              // +03
    ul32 rxfreq;          // +04  Hz
    ul32 rxtone;          // +08  custom encoding
    ul32 txfreq;          // +0C  Hz
    ul32 txtone;          // +10  custom encoding
    u8 unknown1[20];      // +14
    char name[12];        // +28
    ul16 unk15:1,         //     bit 15
         compand:1,       //     bit 14
         unk13_12:2,      //     bits 13-12
         unk11:1,         //     bit 11 (default 1)
         unk10:1,         //     bit 10
         dtmf_group:4,    //     bits 9-6 (0-indexed)
         ani:1,           //     bit 5
         scanadd:1,       //     bit 4
         unk3:1,          //     bit 3
         pttid:3;         //     bits 2-0 (1=Off,2=Start,3=End,4=Both)
    ul16 scramble;        // +36  Hz (0xFFFF=Off)
} memory[256];

#seekto 0x3C64;
ul32 dwatch;              // 0x3C64  1=Off, 2=On

#seekto 0x3C80;
ul32 group_call_ch;       // 0x3C80  0-indexed channel number
ul32 noaa_ch;             // 0x3C84  0-indexed (0=WX1 .. 6=WX7)

#seekto 0x3D34;
ul32 noaa_freq;           // 0x3D34  NOAA freq in Hz (auto from noaa_ch)

#seekto 0x3D74;
ul32 key_lock;            // 0x3D74  ms (0=Off)
ul32 settings_3d78;      // 0x3D78  bits0:1=fm_auto
                         //   (1=On,2=Off), bit2=allow_tx_beep
ul32 unknown_3d7c;        // 0x3D7C
ul32 unknown_3d80[7];     // 0x3D80
ul32 lcd_brightness;      // 0x3D9C  1-5
ul32 auto_bl_time;        // 0x3DA0  ms
ul32 apo_time;            // 0x3DA4  ms (0=Off)
ul32 password;            // 0x3DA8  pwd*4 + flag (1=on, 0=off)
ul32 chnameshow;          // 0x3DAC  0=Off, 1=On
ul32 tone_burst;          // 0x3DB0  Hz (1750, 2100, etc.)
ul32 abswitch;            // 0x3DB4  0=Auto, 1=On, 2=Off
ul32 css_packed;          // 0x3DB8  bit0=css_vague, bit4=cancel_all_ctdt
ul32 unknown_3dbc;        // 0x3DBC
ul32 unknown_3dc0;        // 0x3DC0
ul32 show_bat;            // 0x3DC4  0=Off, 1=On
ul32 dtmf_show;           // 0x3DC8  0=Off, 1=On
ul32 unknown_3dcc;        // 0x3DCC
ul32 group_switch;        // 0x3DD0  0=Off, 1=On
ul32 unknown_3dd4;        // 0x3DD4
ul32 noaa_warning;        // 0x3DD8  0=Off, 0x40000=On
"""

# Protocol constants
STX = 0x02
ETX = 0x03
DLE = 0x10

# Bytes that must be DLE-escaped in the protocol
ESCAPE_MAP = {0x00: 0x13, 0x02: 0x01, 0x03: 0x11, 0x10: 0x12, 0xFF: 0x14}
UNESCAPE_MAP = {v: k for k, v in ESCAPE_MAP.items()}

# Protocol commands (byte 1 of request/response frames)
CMD_IDENT = 0x01
CMD_READ = 0x02
CMD_WRITE = 0x03
CMD_VERIFY = 0x04
CMD_FINALIZE = 0x05

# Table IDs (byte 2 — selects which data table to access)
TBL_SYSCONFIG = 0x01
TBL_RFCAL = 0x02
TBL_SETTINGS = 0x03
TBL_CHANNELS = 0x04
TBL_EXTRA = 0x05
TBL_FINAL = 0x07

# Memory layout — user data region (uploaded back to radio)
IDENT_SIZE = 28
SETTINGS_OFFSET = 0x001C
SETTINGS_SIZE = 836
CHANNELS_OFFSET = 0x0360
CHANNEL_SIZE = 56
NUM_CHANNELS = 256
EXTRA_OFFSET = 0x3B60
EXTRA_COUNT = 8
EXTRA_SIZE = 32
FINAL_OFFSET = 0x3C60
FINAL_SIZE = 480
# Calibration region (downloaded but not uploaded)
SYSCONFIG_OFFSET = 0x3E40
SYSCONFIG_SIZE = 1100
RFCAL_OFFSET = 0x428C
RFCAL_COUNT = 10
RFCAL_SIZE = 36
MEMSIZE = 17396

IMAGE_VERSION = 1

POWER_LEVELS = [
    chirp_common.PowerLevel("High", watts=5.00),
    chirp_common.PowerLevel("Low", watts=0.50),
]

# NOAA WX frequencies
NOAA_FREQS = [
    162550000,  # WX1: 162.550 MHz
    162400000,  # WX2: 162.400 MHz
    162475000,  # WX3: 162.475 MHz
    162425000,  # WX4: 162.425 MHz
    162450000,  # WX5: 162.450 MHz
    162500000,  # WX6: 162.500 MHz
    162525000,  # WX7: 162.525 MHz
]

# Valid GMRS TX frequencies (main channels + repeater outputs)
GMRS_TX_FREQS = (
    set(bandplan_na.ALL_GMRS_FREQS) |
    {f + 5000000 for f in bandplan_na.GMRS_HIRPT}
)

# Tail elimination frequency options (50.0-260.0 Hz in 0.1 Hz steps)
TAIL_TONES = [round(50.0 + i * 0.1, 1) for i in range(2101)]

# CTCSS/CDCSS tail freq encoding: freq_hz * 40 + 2
TAIL_TONE_MAP = [("%.1f" % t, int(round(t * 40)) + 2)
                 for t in TAIL_TONES]

# NO CTCSS tail freq encoding: freq_hz * 10
NO_CTCSS_TAIL_MAP = [("%.1f" % t, int(round(t * 10)))
                     for t in TAIL_TONES]

# Per-channel setting maps
PTTID_MAP = [("Off", 1), ("Start", 2), ("End", 3), ("Both", 4)]
SCRAMBLE_MAP = ([("Off", 0xFFFF)] +
                [("%d Hz" % f, f) for f in range(2700, 3500, 100)])

# Lists used in get_settings / get_memory
LIST_NOAA = ["WX%d" % (i + 1) for i in range(7)]
LIST_PRIORITY_SCAN = ["Off"] + ["CH%03d" % (i + 1) for i in range(256)]

# Valid DTMF symbol charset
DTMF_CHARS = "0123456789ABCD*#"


# --- DCS tone encoding/decoding ---

def _reverse_bits(val, nbits):
    """Reverse the bit order of an integer."""
    result = 0
    for i in range(nbits):
        if val & (1 << i):
            result |= (1 << (nbits - 1 - i))
    return result


def _golay_remainder(data_12):
    """Compute Golay(23,12) check bits using DCS polynomial 0xAE3."""
    msg = data_12 << 11
    for i in range(11, -1, -1):
        if msg & (1 << (i + 11)):
            msg ^= (0xAE3 << i)
    return msg & 0x7FF


def _dcs_encode(code_oct, pol='N'):
    """Encode a DCS code and polarity to the C2's 32-bit tone value.

    The radio stores these in a format similar to the DCS wire format.

    The encoding uses a Golay(23,12) codeword with the 9-bit DCS code
    stored at bits [10:2] of the tone value. The codeword is bit-reversed
    relative to the standard Golay encoding. Bit 25 indicates inverted
    polarity. CTCSS and DCS values are distinguished by bit 1 (DCS=1).
    """
    code_dec = int(str(code_oct), 8)

    if pol == 'R':
        # Inverted: compute Golay for the complemented code
        code_9bit = (~code_dec) & 0x1FF
        low3 = 0x06
    else:
        code_9bit = code_dec
        low3 = 0x01

    data_12 = (_reverse_bits(code_9bit, 9) << 3) | low3
    rem = _golay_remainder(data_12)
    cw23 = (data_12 << 11) | rem
    cw23_rev = _reverse_bits(cw23, 23)
    tone = (cw23_rev << 2) | 0x02

    if pol == 'R':
        # Set inversion flag (bit 25 = bit 1 of byte 3)
        tone = tone | (0x02 << 24)

    return tone


def _dcs_decode(tone_val):
    """Decode a 32-bit DCS tone value to (code_oct, polarity)."""
    raw9 = (tone_val >> 2) & 0x1FF
    inv_flag = (tone_val >> 25) & 1
    if inv_flag:
        code = (~raw9) & 0x1FF
        return int('%o' % code), 'R'
    else:
        return int('%o' % raw9), 'N'


def _decode_tone(val):
    """Decode a 32-bit tone value to (mode, value, polarity).

    Returns ('', 0, 'N') for no tone, ('Tone', freq_hz, 'N') for CTCSS,
    or ('DTCS', code, pol) for DCS.
    """
    if val == 0:
        return '', 0, 'N'
    if not (val & 0x02):
        # CTCSS: bit 1 clear, value = tone_hz * 40 + 1
        tone_hz = (val - 1) / 40.0
        return 'Tone', tone_hz, 'N'
    # DCS: bit 1 set
    code, pol = _dcs_decode(val)
    return 'DTCS', code, pol


def _encode_tone(mode, value, pol):
    """Encode tone parameters to a 32-bit value."""
    if mode in ('Tone', 'TSQL'):
        return int(round(value * 40)) + 1
    elif mode == 'DTCS':
        return _dcs_encode(value, pol)
    return 0


# --- Protocol framing ---

def _dle_escape(data):
    """Apply DLE byte-stuffing to raw data."""
    result = bytearray()
    for b in data:
        if b in ESCAPE_MAP:
            result.append(DLE)
            result.append(ESCAPE_MAP[b])
        else:
            result.append(b)
    return bytes(result)


def _dle_unescape(data):
    """Remove DLE byte-stuffing from escaped data."""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == DLE and i + 1 < len(data):
            escaped = data[i + 1]
            if escaped in UNESCAPE_MAP:
                result.append(UNESCAPE_MAP[escaped])
            else:
                result.append(escaped)
            i += 2
        else:
            result.append(data[i])
            i += 1
    return bytes(result)


def _make_frame(payload):
    """Build a complete STX/ETX frame with checksum and DLE escaping."""
    chk = sum(payload) & 0xFF
    raw = payload + bytes([chk])
    return bytes([STX]) + _dle_escape(raw) + bytes([ETX])


def _parse_frame(frame_data):
    """Extract and verify payload from a received frame.

    Returns the payload (without checksum) or raises RadioError.
    """
    if not frame_data or frame_data[0] != STX or frame_data[-1] != ETX:
        raise errors.RadioError("Invalid frame")
    inner = _dle_unescape(frame_data[1:-1])
    if len(inner) < 2:
        raise errors.RadioError("Frame too short")
    payload = inner[:-1]
    chk = inner[-1]
    expected = sum(payload) & 0xFF
    if chk != expected:
        raise errors.RadioError(
            "Checksum mismatch: got 0x%02x, expected 0x%02x" %
            (chk, expected))
    return payload


# --- Serial communication ---

def _read_frame(pipe, timeout=5.0):
    """Read a complete STX...ETX frame from the serial port.

    Uses byte-at-a-time blocking reads to track DLE byte-stuffing
    and correctly identify the real ETX terminator.
    """
    data = bytearray()
    in_escape = False
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            b = pipe.read(1)
        except Exception as e:
            raise errors.RadioError(
                "Error reading from radio: %s" % e)
        if not b:
            continue
        data.append(b[0])
        if len(data) == 1:
            if b[0] != STX:
                data = bytearray()
            continue
        if in_escape:
            in_escape = False
            continue
        if b[0] == DLE:
            in_escape = True
            continue
        if b[0] == ETX:
            return bytes(data)
    if data:
        LOG.debug("Incomplete frame (%d bytes): %s",
                  len(data), data[:20].hex())
    return b''


def _send_recv(radio, payload):
    """Send a command and receive the response.

    Retries up to 3 times on timeout to handle occasional
    timing-related failures on some USB serial adapters.
    Returns the response payload (header + data, no checksum).
    """
    frame = _make_frame(payload)
    pipe = radio.pipe

    for attempt in range(3):
        try:
            pipe.write(frame)
            pipe.flush()
        except Exception as e:
            raise errors.RadioError(
                "Error communicating with radio: %s" % e)

        resp_frame = _read_frame(pipe)
        if resp_frame:
            return _parse_frame(resp_frame)

        LOG.warning("No response on attempt %d", attempt + 1)
        # Drain any garbage data before retrying
        try:
            avail = pipe.in_waiting
            if avail:
                pipe.read(avail)
        except Exception:
            pass

    raise errors.RadioError(
        "No response from radio after 3 attempts (cmd=%s)" %
        ' '.join('%02x' % b for b in payload))


def _read_block(radio, cmd, table, index):
    """Read a data block from the radio.

    Returns just the data portion (no header bytes).
    """
    payload = bytes([0x01, cmd, table, index])
    resp = _send_recv(radio, payload)
    # Response format: [resp_type, cmd, table, index, ...data...]
    if len(resp) < 4 or resp[1:4] != payload[1:4]:
        raise errors.RadioError(
            "Unexpected response header: got %s, expected cmd=%02x "
            "tbl=%02x idx=%02x" % (resp[:4].hex(), cmd, table, index))
    return resp[4:]


def _write_block(radio, cmd, table, index, data):
    """Write a data block to the radio."""
    payload = bytes([0x01, cmd, table, index]) + data
    frame = _make_frame(payload)

    pipe = radio.pipe
    try:
        pipe.write(frame)
        pipe.flush()
    except Exception as e:
        raise errors.RadioError("Error communicating with radio: %s" % e)

    resp_frame = _read_frame(pipe)
    if not resp_frame:
        avail = pipe.in_waiting
        if avail:
            raw = pipe.read(avail)
            LOG.error("Got non-frame data: %s", raw.hex())
        raise errors.RadioError(
            "No response to write (cmd=%02x tbl=%02x idx=%02x, %d bytes)" %
            (cmd, table, index, len(data)))

    resp = _parse_frame(resp_frame)
    if len(resp) < 4 or resp[1:4] != payload[1:4]:
        raise errors.RadioError(
            "Unexpected write response: got %s, expected cmd=%02x "
            "tbl=%02x idx=%02x" % (resp[:4].hex(), cmd, table, index))
    return resp


# --- Download / Upload ---

def do_download(radio):
    """Download memory image from the radio."""
    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.cur = 0
    status.max = MEMSIZE

    mmap_data = bytearray(MEMSIZE)
    offset = 0

    # 1. Read ident
    data = _read_block(radio, CMD_IDENT, 0x00, 0x00)
    mmap_data[offset:offset + len(data)] = data
    offset += len(data)
    status.cur = offset
    radio.status_fn(status)

    # 2. Read settings
    data = _read_block(radio, CMD_READ, TBL_SETTINGS, 0x00)
    mmap_data[offset:offset + len(data)] = data
    offset += len(data)
    status.cur = offset
    radio.status_fn(status)

    # 3. Read channels (256)
    for i in range(NUM_CHANNELS):
        data = _read_block(radio, CMD_READ, TBL_CHANNELS, i)
        mmap_data[offset:offset + len(data)] = data
        offset += len(data)
        status.cur = offset
        if i % 16 == 0:
            radio.status_fn(status)

    # 4. Read extra blocks
    for i in range(EXTRA_COUNT):
        data = _read_block(radio, CMD_READ, TBL_EXTRA, i)
        mmap_data[offset:offset + len(data)] = data
        offset += len(data)

    # 5. Read final block
    data = _read_block(radio, CMD_READ, TBL_FINAL, 0x00)
    mmap_data[offset:offset + len(data)] = data
    offset += len(data)

    # 6. Read calibration data (downloaded but not uploaded)
    data = _read_block(radio, CMD_READ, TBL_SYSCONFIG, 0x00)
    mmap_data[offset:offset + len(data)] = data
    offset += len(data)

    for i in range(RFCAL_COUNT):
        data = _read_block(radio, CMD_READ, TBL_RFCAL, i)
        mmap_data[offset:offset + len(data)] = data
        offset += len(data)

    status.cur = MEMSIZE
    radio.status_fn(status)

    LOG.debug("Downloaded %d bytes", offset)

    radio._metadata['image_version'] = IMAGE_VERSION

    return memmap.MemoryMapBytes(bytes(mmap_data[:offset]))


def do_upload(radio):
    """Upload memory image to the radio."""
    status = chirp_common.Status()
    status.msg = "Uploading to radio"
    status.cur = 0
    status.max = MEMSIZE

    mmap = radio.get_mmap()

    # 1. Read ident (handshake)
    _read_block(radio, CMD_IDENT, 0x00, 0x00)

    # 2. Read current settings (verify communication)
    _read_block(radio, CMD_READ, TBL_SETTINGS, 0x00)

    # 3. Write settings
    settings_data = mmap[SETTINGS_OFFSET:SETTINGS_OFFSET + SETTINGS_SIZE]
    _write_block(radio, CMD_WRITE, TBL_SETTINGS, 0x00, settings_data)
    _read_block(radio, CMD_VERIFY, TBL_SETTINGS, 0x00)
    status.cur = SETTINGS_OFFSET + SETTINGS_SIZE
    radio.status_fn(status)

    # 4. Write channels
    for i in range(NUM_CHANNELS):
        ch_offset = CHANNELS_OFFSET + i * CHANNEL_SIZE
        ch_data = mmap[ch_offset:ch_offset + CHANNEL_SIZE]
        _write_block(radio, CMD_WRITE, TBL_CHANNELS, i, ch_data)
        _read_block(radio, CMD_VERIFY, TBL_CHANNELS, i)
        status.cur = ch_offset + CHANNEL_SIZE
        if i % 16 == 0:
            radio.status_fn(status)

    # 5. Write extra blocks
    for i in range(EXTRA_COUNT):
        blk_start = EXTRA_OFFSET + i * EXTRA_SIZE
        blk_data = mmap[blk_start:blk_start + EXTRA_SIZE]
        _write_block(radio, CMD_WRITE, TBL_EXTRA, i, blk_data)
        _read_block(radio, CMD_VERIFY, TBL_EXTRA, i)

    # 6. Write final block (448 of 480 bytes, matching CPS protocol)
    final_data = mmap[FINAL_OFFSET:FINAL_OFFSET + 448]
    _write_block(radio, CMD_WRITE, TBL_FINAL, 0x00, final_data)
    _read_block(radio, CMD_VERIFY, TBL_FINAL, 0x00)

    # 7. Finalize
    _read_block(radio, CMD_FINALIZE, 0x00, 0x00)

    status.cur = MEMSIZE
    radio.status_fn(status)


# --- Main radio class ---

@directory.register
class RetevisC2(chirp_common.CloneModeRadio):
    """Retevis C2"""
    VENDOR = "Retevis"
    MODEL = "C2"
    BAUD_RATE = 115200
    WANTS_RTS = False

    _memsize = MEMSIZE

    POWER_LEVELS = POWER_LEVELS

    VALID_BANDS = [(100000000, 520000000)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_name = True
        rf.valid_name_length = 12
        rf.valid_characters = (chirp_common.CHARSET_ALPHANUMERIC +
                               " !@#$%&*()-+=")
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_skips = ["", "S"]
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
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = chirp_common.TUNING_STEPS
        rf.valid_dtcs_codes = chirp_common.DTCS_CODES
        rf.can_odd_split = True
        rf.memory_bounds = (1, NUM_CHANNELS)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        if int(_mem.rxfreq) == 0:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq)

        # TX freq / duplex
        txfreq = int(_mem.txfreq)
        if txfreq == 0 or txfreq == 0xFFFFFFFF:
            mem.duplex = "off"
            mem.offset = 0
        else:
            offset = txfreq - mem.freq
            if offset == 0:
                mem.duplex = ""
                mem.offset = 0
            elif offset > 0:
                if chirp_common.is_split(
                        self.get_features().valid_bands,
                        mem.freq, txfreq):
                    mem.duplex = "split"
                    mem.offset = txfreq
                else:
                    mem.duplex = "+"
                    mem.offset = offset
            elif offset < 0:
                mem.duplex = "-"
                mem.offset = abs(offset)

        # Mode (bandwidth)
        bw = int(_mem.bandwidth)
        mem.mode = "FM" if bw == 25000 else "NFM"

        # Power
        if _mem.highpower:
            mem.power = self.POWER_LEVELS[0]  # High
        else:
            mem.power = self.POWER_LEVELS[1]  # Low

        # Tones
        txtone = _decode_tone(int(_mem.txtone))
        rxtone = _decode_tone(int(_mem.rxtone))
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # Name
        name = str(_mem.name).rstrip('\x00').rstrip()
        mem.name = name

        # Skip (scanadd: 1=add, 0=skip)
        if not _mem.scanadd:
            mem.skip = "S"

        # Per-channel extras
        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("_compand", "Compand",
                          RadioSettingValueBoolean(
                              bool(_mem.compand)))
        mem.extra.append(rs)

        rs = RadioSetting("_talkaround", "Talk Around",
                          RadioSettingValueBoolean(
                              bool(_mem.talkaround)))
        mem.extra.append(rs)

        rs = RadioSetting("_busylock", "Busy Lock",
                          RadioSettingValueBoolean(
                              bool(_mem.busylock)))
        mem.extra.append(rs)

        rs = RadioSetting("_ani", "ANI",
                          RadioSettingValueBoolean(
                              bool(_mem.ani)))
        mem.extra.append(rs)

        rs = RadioSetting("_pttid", "PTT ID",
                          RadioSettingValueMap(
                              PTTID_MAP, int(_mem.pttid)))
        mem.extra.append(rs)

        dtmf_grp = int(_mem.dtmf_group)
        rs = RadioSetting("_dtmf_group", "DTMF Group",
                          RadioSettingValueInteger(
                              1, 16, dtmf_grp + 1))
        mem.extra.append(rs)

        rs = RadioSetting("_scramble", "Scramble",
                          RadioSettingValueMap(
                              SCRAMBLE_MAP, int(_mem.scramble)))
        mem.extra.append(rs)

        # GMRS implied modes
        mem.mode, mem.power = self._apply_gmrs_limits(mem)

        return mem

    def _compute_tx_freq(self, mem):
        """Compute TX frequency from memory duplex settings.

        Returns None if TX is disabled (duplex='off').
        """
        if mem.duplex == "off":
            return None
        elif mem.duplex == "split":
            return mem.offset
        elif mem.duplex == "+":
            return mem.freq + mem.offset
        elif mem.duplex == "-":
            return mem.freq - mem.offset
        return mem.freq

    def _apply_gmrs_limits(self, mem):
        """Compute GMRS frequency-based restrictions (implied modes).

        Returns (mode, power) tuple. Interstitial channels
        (467.5625-467.7125 MHz) are forced to NFM and low power.
        """
        tx_freq = self._compute_tx_freq(mem)
        if tx_freq is not None and tx_freq in bandplan_na.GMRS_HHONLY:
            return "NFM", self.POWER_LEVELS[1]
        return mem.mode, mem.power

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b'\x00' * 56)
            _mem.bandwidth = 25000
            _mem.highpower = 1
            _mem.cfg_unk2 = 5       # CPS default (bits 2,0 set)
            _mem.scanadd = 1
            _mem.pttid = 1          # Off
            _mem.unk11 = 1          # CPS default (bit 11)
            _mem.scramble = 0xFFFF
            return

        _mem.rxfreq = mem.freq

        # TX freq
        if mem.duplex == "off":
            _mem.txfreq = 0
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset
        elif mem.duplex == "+":
            _mem.txfreq = mem.freq + mem.offset
        elif mem.duplex == "-":
            _mem.txfreq = mem.freq - mem.offset
        else:
            _mem.txfreq = mem.freq

        # Enforce GMRS HH-only limits on write
        tx_freq = self._compute_tx_freq(mem)
        is_hhonly = tx_freq is not None and tx_freq in bandplan_na.GMRS_HHONLY

        # Mode
        if is_hhonly:
            _mem.bandwidth = 12500
        else:
            _mem.bandwidth = 25000 if mem.mode == "FM" else 12500

        # Power
        _mem.highpower = (not is_hhonly and
                          mem.power == self.POWER_LEVELS[0])

        # Tones
        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        _mem.txtone = _encode_tone(txmode, txtone, txpol)
        _mem.rxtone = _encode_tone(rxmode, rxtone, rxpol)

        # Name
        name = mem.name.ljust(12, '\x00')[:12]
        _mem.name = name

        # Skip (scanadd: 1=add, 0=skip)
        _mem.scanadd = mem.skip != "S"

        _mem.pad0 = 0

        # Per-channel extras - reset to defaults if not provided
        # (e.g. CSV import or copy where extras are absent)
        if not mem.extra:
            _mem.busylock = 0
            _mem.talkaround = 0
            _mem.compand = 0
            _mem.dtmf_group = 0
            _mem.ani = 0
            _mem.pttid = 1          # Off
            _mem.scramble = 0xFFFF
            return

        for setting in mem.extra:
            name = setting.get_name()
            if name == "_compand":
                _mem.compand = int(bool(setting.value))
            elif name == "_talkaround":
                _mem.talkaround = int(bool(setting.value))
            elif name == "_busylock":
                _mem.busylock = int(bool(setting.value))
            elif name == "_ani":
                _mem.ani = int(bool(setting.value))
            elif name == "_pttid":
                _mem.pttid = int(setting.value)
            elif name == "_dtmf_group":
                _mem.dtmf_group = int(setting.value) - 1
            elif name == "_scramble":
                _mem.scramble = int(setting.value)

    def get_settings(self):
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        vox = RadioSettingGroup("vox", "VOX Settings")
        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        top = RadioSettings(basic, vox, dtmf)

        ABSWITCH_MAP = [("Auto", 0), ("On", 1), ("Off", 2)]
        STEP_MAP = [("2.5K", 2500), ("5.0K", 5000), ("6.25K", 6250),
                    ("10.0K", 10000), ("12.5K", 12500), ("20.0K", 20000),
                    ("25.0K", 25000), ("50.0K", 50000)]
        TOT_MAP = [("Off", 0)] + [("%d" % x, x) for x in range(15, 615, 15)]
        VOXDELAY_MAP = [("0.5", 500), ("1.0", 1000), ("1.5", 1500),
                        ("2.0", 2000), ("2.5", 2500), ("3.0", 3000)]

        basic.append(MemSetting("tot", "TOT (seconds)",
                                RadioSettingValueMap(
                                    TOT_MAP, int(_mem.tot))))
        TOTWARN_MAP = [("Off", 0)] + [
            ("%d" % x, x << 4) for x in range(1, 11)]
        basic.append(MemSetting("tot_warning", "TOT Warning Time",
                                RadioSettingValueMap(
                                    TOTWARN_MAP,
                                    int(_mem.tot_warning))))
        basic.append(MemSetting("freq_step", "Frequency Step",
                                RadioSettingValueMap(
                                    STEP_MAP, int(_mem.freq_step))))
        basic.append(MemSetting("abswitch", "A/B Switch",
                                RadioSettingValueMap(
                                    ABSWITCH_MAP,
                                    int(_mem.abswitch))))
        KEY_MAP = [
            ("Off", 0xFFFFFFFF),
            ("Monitor", 1),
            ("TX Power", 4),
            ("Scan", 5),
            ("Flashlight", 6),
            ("Denoise", 12),
            ("Frequency Detect", 15),
            ("VOX", 17),
            ("Local Alarm", 20),
            ("Remote Alarm", 21),
            ("Weather", 22),
            ("Talk Around", 23),
            ("Reverse Frequency", 24),
        ]
        SKEY_MAP = KEY_MAP + [("SUB-PTT", 25), ("Group PTT", 26)]
        for field, label, kmap in [
                ("pf1_short", "P1 Short Press", KEY_MAP),
                ("pf1_long", "P1 Long Press", KEY_MAP),
                ("pf2_short", "P2 Short Press", KEY_MAP),
                ("pf2_long", "P2 Long Press", KEY_MAP),
                ("sk_short", "Side Key Short", SKEY_MAP),
                ("sk_long", "Side Key Long", KEY_MAP)]:
            basic.append(MemSetting(
                field, label,
                RadioSettingValueMap(
                    kmap, int(getattr(_mem, field)))))
        rs = RadioSettingValueInteger(1, 256, int(_mem.group_call_ch) + 1)
        basic.append(RadioSetting(
            "_group_call_ch", "Group Call Channel", rs))
        basic.append(MemSetting(
            "squelch", "Squelch Level",
            RadioSettingValueInteger(0, 9, min(int(_mem.squelch), 9))))

        basic.append(MemSetting("chnameshow",
                                "Display Channel Names",
                                RadioSettingValueBoolean(
                                    bool(int(_mem.chnameshow)))))
        basic.append(MemSetting("keytone", "Key Tone",
                                RadioSettingValueBoolean(
                                    bool(int(_mem.keytone)))))
        rs = RadioSettingValueBoolean(int(_mem.dwatch) == 2)
        basic.append(RadioSetting("_dwatch", "Dual Watch", rs))
        basic.append(MemSetting("group_switch", "Group Call",
                                RadioSettingValueBoolean(
                                    bool(int(_mem.group_switch)))))

        noaa_idx = int(_mem.noaa_ch)
        if noaa_idx >= 7:
            noaa_idx = 0
        rs = RadioSettingValueList(LIST_NOAA, current_index=noaa_idx)
        basic.append(RadioSetting(
            "_noaa_ch", "NOAA Weather Channel", rs))
        rs = RadioSettingValueBoolean(int(_mem.noaa_warning) != 0)
        basic.append(RadioSetting(
            "_noaa_warning", "NOAA Weather Warning", rs))
        fm_raw = int(_mem.settings_3d78)
        rs = RadioSettingValueBoolean((fm_raw & 0x03) == 1)
        basic.append(RadioSetting("_fm_auto", "FM Radio", rs))
        rs = RadioSettingValueBoolean(bool(fm_raw & 0x04))
        basic.append(RadioSetting(
            "_allow_tx_beep", "Allow TX Beep", rs))
        # AI Denoise: ul32 = level*96 + 4 + (3 if on else 0)
        ai_raw = int(_mem.ai_denoise_packed)
        ai_enabled = (ai_raw & 0x03) == 0x03
        ai_level = ((ai_raw & ~3) - 4) // 96
        if ai_level < 1:
            ai_level = 1
        if ai_level > 10:
            ai_level = 10
        rs = RadioSettingValueBoolean(ai_enabled)
        basic.append(RadioSetting("_ai_denoise", "AI Denoise", rs))
        rs = RadioSettingValueInteger(1, 10, ai_level)
        basic.append(RadioSetting(
            "_ai_denoise_level", "AI Denoise Level", rs))

        basic.append(MemSetting("recorder", "Recording Playback",
                                RadioSettingValueBoolean(
                                    bool(int(_mem.recorder)))))
        basic.append(MemSetting("show_bat", "Show Battery Voltage",
                                RadioSettingValueBoolean(
                                    bool(int(_mem.show_bat)))))
        basic.append(MemSetting("dtmf_show", "DTMF Show",
                                RadioSettingValueBoolean(
                                    bool(int(_mem.dtmf_show)))))
        rs = RadioSettingValueBoolean(bool(int(_mem.css_packed) & 0x01))
        basic.append(RadioSetting("_css_vague", "CSS Vague", rs))
        rs = RadioSettingValueBoolean(bool(int(_mem.css_packed) & 0x10))
        basic.append(RadioSetting(
            "_cancel_all_ctdt", "Cancel All CTCSS/DCS", rs))

        basic.append(MemSetting("ctcss_tail_tone",
                                "CTCSS Tail Freq (Hz)",
                                RadioSettingValueMap(
                                    TAIL_TONE_MAP,
                                    int(_mem.ctcss_tail_tone))))
        basic.append(MemSetting("cdcss_tail_tone",
                                "CDCSS Tail Freq (Hz)",
                                RadioSettingValueMap(
                                    TAIL_TONE_MAP,
                                    int(_mem.cdcss_tail_tone))))
        basic.append(MemSetting("no_ctcss_tail_freq",
                                "NO CTCSS Tail Freq (Hz)",
                                RadioSettingValueMap(
                                    NO_CTCSS_TAIL_MAP,
                                    int(_mem.no_ctcss_tail_freq))))

        rs = RadioSettingValueBoolean(bool(int(_mem.settings_0020) & 1))
        basic.append(RadioSetting("_voice", "Voice Prompt", rs))

        POWERSAVE_MAP = [("Off", 0), ("1", 1), ("2", 4),
                         ("3", 6), ("4", 9)]
        basic.append(MemSetting("power_save", "Battery Save",
                                RadioSettingValueMap(
                                    POWERSAVE_MAP,
                                    int(_mem.power_save))))

        WORKMODE_MAP = [("Channel", 0), ("Memory", 1)]
        basic.append(MemSetting("work_mode", "Work Mode",
                                RadioSettingValueMap(
                                    WORKMODE_MAP,
                                    int(_mem.work_mode))))

        basic.append(MemSetting(
            "micgain_analog", "Mic Gain (Analog)",
            RadioSettingValueInteger(
                -3, 3, max(-3, min(3, int(_mem.micgain_analog))))))

        pri_raw = int(_mem.settings_035c)
        rs = RadioSettingValueBoolean(bool(pri_raw & 0x01))
        basic.append(RadioSetting(
            "_tx_start_beep", "TX Start Beep", rs))
        rs = RadioSettingValueBoolean(bool(pri_raw & 0x04))
        basic.append(RadioSetting(
            "_tx_stop_beep", "TX Stop Beep", rs))

        pri_ch = pri_raw >> 8
        if pri_ch == 0xFFFFFF:
            pri_idx = 0
        else:
            pri_idx = pri_ch + 1
            if pri_idx < 1 or pri_idx > 256:
                pri_idx = 0
        rs = RadioSettingValueList(
            LIST_PRIORITY_SCAN, current_index=pri_idx)
        basic.append(RadioSetting(
            "_priority_scan", "Priority Scan Channel", rs))

        SCANMODE_MAP = [("Search", 0), ("Carrier", 1), ("Time", 2)]
        basic.append(MemSetting("scan_mode", "Scan Mode",
                                RadioSettingValueMap(
                                    SCANMODE_MAP,
                                    int(_mem.scan_mode))))

        basic.append(MemSetting(
            "lcd_brightness", "LCD Brightness",
            RadioSettingValueInteger(
                1, 5, min(max(int(_mem.lcd_brightness), 1), 5))))

        KEYLOCK_MAP = [("Off", 0), ("5s", 5000), ("10s", 10000),
                       ("15s", 15000), ("20s", 20000), ("25s", 25000),
                       ("30s", 30000)]
        basic.append(MemSetting("key_lock", "Key Lock",
                                RadioSettingValueMap(
                                    KEYLOCK_MAP, int(_mem.key_lock))))

        ABLTIME_MAP = [("Always", 0), ("5s", 5000), ("10s", 10000),
                       ("15s", 15000), ("20s", 20000)]
        basic.append(MemSetting("auto_bl_time", "Auto Backlight Time",
                                RadioSettingValueMap(
                                    ABLTIME_MAP, int(_mem.auto_bl_time))))

        APO_MAP = [("Off", 0), ("10min", 600000), ("30min", 1800000)] + \
                  [("%dhr" % h, h * 3600000) for h in range(1, 13)]
        basic.append(MemSetting("apo_time", "Auto Power Off",
                                RadioSettingValueMap(
                                    APO_MAP, int(_mem.apo_time))))

        # Password: packed as pwd_int * 4 + flag (1=on, 0=off)
        pwd_raw = int(_mem.password)
        pwd_enabled = (pwd_raw % 4) == 1
        pwd_num = pwd_raw // 4
        pwd_str = "%06d" % pwd_num
        rs = RadioSettingValueBoolean(pwd_enabled)
        basic.append(RadioSetting(
            "_pwd_enable", "Password Enable", rs))
        rs = RadioSettingValueString(6, 6, pwd_str)
        rs.set_charset("0123456789")
        basic.append(RadioSetting("_pwd_code", "Password", rs))

        TONE_MAP = [("1000", 1000), ("1450", 1450),
                    ("1750", 1750), ("2100", 2100)]
        basic.append(MemSetting("tone_burst", "Tone Burst (Hz)",
                                RadioSettingValueMap(
                                    TONE_MAP, int(_mem.tone_burst))))
        # VOX is packed: vox_level*4 + (1=on, 2=off)
        vox_packed = int(_mem.vox_packed)
        vox_on = (vox_packed % 4) == 1
        vox_level = vox_packed // 4
        if vox_level < 1:
            vox_level = 1
        if vox_level > 9:
            vox_level = 5

        rs = RadioSettingValueBoolean(vox_on)
        vox.append(RadioSetting("_vox_enabled", "VOX Function", rs))

        vox.append(RadioSetting(
            "_vox_level", "VOX Level",
            RadioSettingValueInteger(1, 9, vox_level)))

        vox.append(MemSetting("vox_delay", "VOX Delay Time",
                              RadioSettingValueMap(
                                  VOXDELAY_MAP, int(_mem.vox_delay))))

        # DTMF settings
        dtmf_id = str(_mem.dtmf_local_id).rstrip('\x00')
        rs = RadioSettingValueString(0, 8, dtmf_id,
                                     mem_pad_char='\x00')
        rs.set_charset(DTMF_CHARS)
        dtmf.append(MemSetting("dtmf_local_id", "DTMF Local ID", rs))

        DTMF_FIRST_MAP = [("%dms" % ms, ms * 2)
                          for ms in range(150, 1010, 10)]
        dtmf.append(MemSetting("dtmf_first_time",
                               "DTMF First Code Time",
                               RadioSettingValueMap(
                                   DTMF_FIRST_MAP,
                                   int(_mem.dtmf_first_time))))

        LIST_SEP = ['*', '#', 'A', 'B', 'C', 'D']
        sep = str(_mem.dtmf_sep_code)
        sep_idx = LIST_SEP.index(sep) if sep in LIST_SEP else 0
        rs = RadioSettingValueList(LIST_SEP, current_index=sep_idx)
        dtmf.append(RadioSetting(
            "dtmf_sep_code", "Separate Code", rs))

        LIST_GRP = ['A', 'B', 'C', 'D', '*', '#']
        grp = str(_mem.dtmf_group_code)
        grp_idx = LIST_GRP.index(grp) if grp in LIST_GRP else 0
        rs = RadioSettingValueList(LIST_GRP, current_index=grp_idx)
        dtmf.append(RadioSetting(
            "dtmf_group_code", "Group Code", rs))

        return top

    def set_settings(self, settings):
        _mem = self._memobj
        for element in settings:
            if isinstance(element, MemSetting):
                element.apply_to_memobj(_mem)
            elif isinstance(element, RadioSetting):
                # Packed/composite settings need manual encoding
                name = element.get_name()
                if name == '_group_call_ch':
                    _mem.group_call_ch = int(element.value) - 1
                elif name == '_fm_auto':
                    cur = int(_mem.settings_3d78) & ~0x03
                    _mem.settings_3d78 = \
                        cur | (1 if bool(element.value) else 2)
                elif name == '_allow_tx_beep':
                    cur = int(_mem.settings_3d78)
                    if bool(element.value):
                        _mem.settings_3d78 = cur | 0x04
                    else:
                        _mem.settings_3d78 = cur & ~0x04
                elif name == '_dwatch':
                    _mem.dwatch = 2 if bool(element.value) else 1
                elif name == '_voice':
                    cur = int(_mem.settings_0020)
                    if bool(element.value):
                        _mem.settings_0020 = cur | 1
                    else:
                        _mem.settings_0020 = cur & ~1
                elif name == '_vox_enabled':
                    # Repack VOX: vox_level*4 + (1=on, 2=off)
                    cur = int(_mem.vox_packed)
                    level = cur // 4
                    flag = 1 if bool(element.value) else 2
                    _mem.vox_packed = level * 4 + flag
                elif name == '_vox_level':
                    cur = int(_mem.vox_packed)
                    flag = cur % 4
                    _mem.vox_packed = int(element.value) * 4 + flag
                elif name == '_pwd_enable':
                    cur = int(_mem.password)
                    pwd = cur // 4
                    if bool(element.value):
                        _mem.password = pwd * 4 + 1
                    else:
                        _mem.password = pwd * 4
                elif name == '_pwd_code':
                    cur = int(_mem.password)
                    flag = cur % 4
                    _mem.password = \
                        int(str(element.value)) * 4 + flag
                elif name == '_ai_denoise':
                    cur = int(_mem.ai_denoise_packed)
                    if bool(element.value):
                        _mem.ai_denoise_packed = (cur & ~3) | 3
                    else:
                        _mem.ai_denoise_packed = cur & ~3
                elif name == '_ai_denoise_level':
                    cur = int(_mem.ai_denoise_packed)
                    enable = cur & 3
                    _mem.ai_denoise_packed = \
                        int(element.value) * 96 + 4 + enable
                elif name == '_tx_start_beep':
                    cur = int(_mem.settings_035c)
                    if bool(element.value):
                        _mem.settings_035c = cur | 0x01
                    else:
                        _mem.settings_035c = cur & ~0x01
                elif name == '_tx_stop_beep':
                    cur = int(_mem.settings_035c)
                    if bool(element.value):
                        _mem.settings_035c = cur | 0x04
                    else:
                        _mem.settings_035c = cur & ~0x04
                elif name == '_priority_scan':
                    cur = int(_mem.settings_035c) & 0xFF
                    idx = int(element.value)
                    if idx == 0:
                        _mem.settings_035c = \
                            (0xFFFFFF << 8) | cur
                    else:
                        _mem.settings_035c = \
                            ((idx - 1) << 8) | cur
                elif name == '_css_vague':
                    cur = int(_mem.css_packed)
                    if bool(element.value):
                        _mem.css_packed = cur | 0x01
                    else:
                        _mem.css_packed = cur & ~0x01
                elif name == '_cancel_all_ctdt':
                    cur = int(_mem.css_packed)
                    if bool(element.value):
                        _mem.css_packed = cur | 0x10
                    else:
                        _mem.css_packed = cur & ~0x10
                elif name == '_noaa_ch':
                    idx = int(element.value)
                    _mem.noaa_ch = idx
                    _mem.noaa_freq = NOAA_FREQS[idx]
                elif name == '_noaa_warning':
                    cur = int(_mem.noaa_warning)
                    if bool(element.value):
                        _mem.noaa_warning = cur | 0x40000
                    else:
                        _mem.noaa_warning = cur & ~0x40000
                elif name in ('dtmf_sep_code', 'dtmf_group_code'):
                    setattr(_mem, name, str(element.value))
                else:
                    LOG.warning("Unhandled setting: %s", name)
            else:
                self.set_settings(element)

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.empty:
            return msgs

        tx_freq = self._compute_tx_freq(mem)

        if tx_freq is not None:
            if tx_freq not in GMRS_TX_FREQS:
                msgs.append(chirp_common.ValidationWarning(
                    "TX frequency %s is not a GMRS frequency"
                    % chirp_common.format_freq(tx_freq)))
            if tx_freq in bandplan_na.GMRS_HHONLY:
                if mem.mode != "NFM":
                    msgs.append(chirp_common.ValidationWarning(
                        "GMRS 467 MHz channels require NFM"))
                if mem.power and mem.power != self.POWER_LEVELS[1]:
                    msgs.append(chirp_common.ValidationWarning(
                        "GMRS 467 MHz channels require low power"))

        return msgs
