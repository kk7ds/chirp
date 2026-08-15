# Copyright 2026 Dan <dannjb@gmail.com>
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

"""Baofeng 5RH Chirp driver"""

import time
import logging
import random

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.settings import (
    RadioSettings, RadioSettingGroup, RadioSetting,
    RadioSettingValueList, RadioSettingValueBoolean, RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

HEADER_SYNC = bytearray(b"PROGRAM\x00")
HEADER_SYNC_PIC = b"Picture\xff"  # boot-image handshake (no seed, no XOR)
HEADER_INFO = b"INFORMATION"
END_INFO = b"END\x00"

# Accepted boot-image dimensions (width, height)
BOOT_IMAGE_SIZES = [(160, 128), (240, 240), (240, 320)]
T_INFO = bytearray(16)
for _i in range(12, 16):
    T_INFO[_i] = 0xFF

DATA_LEN = 49152
CHN_SIZE = 48
CHN_MAX = 640

# Zone layout (DataProtocol.cs ConvertZone/ZoneConvert). The radio navigates
# channels through zones: each zone holds a fixed array of channel IDs, with
# FFFF marking an unused slot (the CPS leaves such gaps in place rather than
# packing the list). A channel only appears on the radio if its ID is in a
# zone, so the zone table must be rebuilt on upload to reflect newly-added
# channels.
ZONE_TOTAL_OFF = 31360
ZONE_BASE = 31376
ZONE_SIZE = 152
ZONE_MAX = 10
ZONE_CHN_MAX = 64       # firmware limit (FormMain.cs:383): 10 * 64 == 640
ZONE_NAME_OFF = 136     # IDs occupy 2..129, 130..135 unused, name 136..151

TONES = chirp_common.TONES
DTCS = chirp_common.ALL_DTCS_CODES

POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=0.5),
    chirp_common.PowerLevel("High", watts=5),
]

DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "NFM", "AM"]

# Channel byte 24 written by the radio itself for an airband memory. flags1
# is identical to a plain FM channel there, so this is what marks AM.
MODULATION_AM = 2

# Receive-only coverage the image header does not list. The radio reports
# only its four main bands, but the hardware also receives the airband
# (verified: a 133.450 memory entered on the radio comes back with
# MODULATION_AM set).
# Upper bound is inclusive for chirp_common.in_range(), so stop just below
# 136 MHz where the first band from the header begins.
AIRBAND = (108000000, 135999999)

# Tuning steps offered by the CPS. Same list as the non-GPS UV-5RM Plus /
# 5RM in baofeng_uv17Pro.py. 6.25 kHz is required for PMR446 (446.006250)
# and other 12.5 kHz-offset grids; without it chirp_common.required_step()
# rejects those frequencies during memory validation.
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]

# Frequency coverage. The radio stores its own ranges in the image header,
# which is what get_features() reports once an image is loaded (see
# _bands_from_image). These values are only the fallback for when no image
# is available yet, and match a UV-5RM Plus GPS / 5RH Pro on firmware
# v2_0_09 (CPS "Device Information"):
#   RX: 136-174, 220-260, 350-390, 400-520 MHz
#   TX: 136-174, 220-260,          400-480 MHz
# The RX ranges are a superset of the TX ranges, so they are used for
# valid_bands. This also permits cross-band memories (UHF RX with VHF TX).
VALID_BANDS = [
    (136000000, 174000000),
    (220000000, 260000000),
    (350000000, 390000000),
    (400000000, 520000000),
]

# Settings option lists (labels mirror the CPS general-settings form).
# For these the stored byte equals the option index.
SQL_LIST = ["OFF"] + [str(i) for i in range(1, 10)]
TOT_LIST = [str(i * 15) for i in range(15)]          # 0..210s
PRETOT_LIST = [str(i) for i in range(11)]            # 0..10s
APO_LIST = ["OFF", "30", "60", "120", "240", "480"]  # minutes
SAVE_LIST = ["OFF", "1:1", "1:2", "1:4"]
DISP_LIST = ["Frequency", "Name", "Number", "Frequency+Name"]
DUAL_LIST = ["Single band single watch", "Dual band dual watch",
             "Dual band single watch"]
MAINBAND_LIST = ["A", "B"]
VOICE_LIST = ["OFF", "Chinese", "English"]
ENDTONE_LIST = ["OFF", "Mode 1", "Mode 2", "Mode 3"]
HZ1750_LIST = ["1000Hz", "1450Hz", "1750Hz", "2100Hz"]
TAIL_LIST = ["OFF", "55Hz", "120deg", "180deg", "240deg"]
BLIGHTLV_LIST = [str(i) for i in range(1, 6)]        # 1..5
# Special transforms (byte != index):
VOXLV_LIST = [str(i) for i in range(1, 10)]          # byte == int(label)
VOXDLY_LIST = ["%.1f" % (1.0 + 0.5 * i) for i in range(19)]  # byte == val*10
# byte < 5 reads as "Always"
BLIGHTTIME_LIST = ["Always"] + [str(i) for i in range(5, 31)]

# key == settings struct field, value == option list (stored byte == index)
_INDEX_SETTINGS = [
    ("sqlv", "Squelch level", SQL_LIST),
    ("tot", "Time-out timer (s)", TOT_LIST),
    ("pre_tot", "TOT pre-alert (s)", PRETOT_LIST),
    ("apo", "Auto power off (min)", APO_LIST),
    ("posave", "Battery save", SAVE_LIST),
    ("dual_mode", "Dual watch mode", DUAL_LIST),
    ("main_band", "Main band", MAINBAND_LIST),
    ("cha_disp", "Display A mode", DISP_LIST),
    ("chb_disp", "Display B mode", DISP_LIST),
    ("voice", "Voice prompt", VOICE_LIST),
    ("endtone", "Roger / end tone", ENDTONE_LIST),
    ("hz1750", "Tone burst", HZ1750_LIST),
    ("tailfreq", "Tail tone", TAIL_LIST),
    ("blight_lv", "Backlight level", BLIGHTLV_LIST),
]

# key == field, label == display name (stored byte == bit, 0/1)
_BOOL_SETTINGS = [
    ("voxsw", "VOX enable"),
    ("busylock", "Busy channel lockout"),
    ("beep", "Key beep"),
    ("keylock", "Key lock"),
    ("autokey", "Auto key lock"),
    ("dispdir", "Display direction"),
    ("enhance", "Enhanced function"),
]


def _freq_bcd_to_hz(raw):
    """Convert BCD-in-hex frequency to Hz.

    The hex digits read as decimal give MHz*100000, i.e. Hz/10. Example:
    0x43781000 -> "43781000" -> 43781000 -> 437.81 MHz -> 437810000 Hz

    Integer math on purpose: going via float("512.00375") * 1e6 truncates
    to 512003749 Hz.
    """
    if raw == 0 or raw == 0xFFFFFFFF:
        return 0
    try:
        return int(f"{raw:08X}") * 10
    except ValueError:
        return 0


def _freq_hz_to_bcd(freq_hz):
    """Convert Hz to BCD-in-hex frequency value.

    Reverse of _freq_bcd_to_hz, matching CPS FreqToData (DataProtocol.cs:1484):
    strip the decimal point and parse the digit string as hex. Done with
    integer math (freq_hz // 10 == MHz*100000) to avoid float rounding.
    """
    if not freq_hz:
        return 0
    dec = freq_hz // 10  # MHz * 100000, e.g. 437810000 -> 43781000
    return int("%08d" % dec, 16)


def _decode_name(raw):
    """Decode a GB2312 name field, which ends at the first 0x00 or 0xFF."""
    nb = bytearray()
    for b in raw:
        if b in (0x00, 0xFF):
            break
        nb.append(b)
    try:
        return nb.decode('gb2312')
    except UnicodeDecodeError:
        return nb.decode('latin-1', errors='replace')


def _encode_name(name, length=16):
    """Encode a name as GB2312, zero-padded like CPS StringSwap2Char."""
    try:
        nb = name.encode('gb2312')
    except UnicodeEncodeError:
        nb = name.encode('ascii', errors='ignore')
    return nb[:length].ljust(length, b'\x00')


def _decode_tone(dath, datl):
    """Decode a 2-byte sub-audio field into a (mode, value, polarity) spec.

    Mirrors CPS SubVoiceConvert (DataProtocol.cs:630). The stored 16-bit value
    is BCD-in-hex: its hex digits read as decimal give the CTCSS freq*10 or the
    DCS code. Returns specs compatible with chirp_common.split_tone_decode:
        (None, None, None)        - off
        ("Tone", 123.0, None)     - CTCSS
        ("DTCS", 23, "N"/"R")     - DCS normal/inverted
    """
    dath = int(dath)
    datl = int(datl)
    if dath & 0x80:
        # DCS
        if dath == 0xFF:
            return (None, None, None)
        pol = "R" if (dath & 0xC0) == 0xC0 else "N"
        val = ((dath & 0x07) << 8) | datl
        code = int("%X" % val)  # hex digits as decimal: 0x023 -> 23
        return ("DTCS", code, pol)
    if dath == 0:
        return (None, None, None)
    val = (dath << 8) | datl
    freq = int("%X" % val)  # hex digits as decimal: 0x1000 -> 1000
    return ("Tone", freq / 10.0, None)


def _encode_tone(spec):
    """Encode a (mode, value, polarity) spec into 2 bytes (datH, datL).

    Reverse of _decode_tone, matching CPS SubAudioToData
    (DataProtocol.cs:1505).
    """
    mode, val, pol = spec
    if mode == "Tone":
        raw = int("%d" % int(round(val * 10)), 16)  # 100.0 -> 1000 -> 0x1000
        return (raw >> 8) & 0xFF, raw & 0xFF
    if mode == "DTCS":
        raw = int("%d" % val, 16)  # 23 -> 0x023
        high = (raw >> 8) & 0x07
        high |= 0xC0 if pol == "R" else 0x80
        return high, raw & 0xFF
    return 0x00, 0x00


def _handshake(radio, is_write=False):
    """Three-stage handshake; every byte after it is XORed with the seed."""
    port = radio.pipe
    seed = random.randint(1, 254)

    # H1: Send T_INFO
    port.write(bytes(T_INFO))

    # H2: Wait for response, potentially switch baud
    got_h2 = False
    for _ in range(25):
        time.sleep(0.2)
        if port.in_waiting <= 0:
            continue
        rb = port.read(1)
        if not rb:
            continue
        rb = rb[0]

        if rb != 0x41:
            # Switch to 115200 - close, reopen, reset buffer
            port.close()
            port.baudrate = 115200
            port.open()
            port.reset_input_buffer()

        # Send PROGRAM with seed
        HEADER_SYNC[7] = seed
        port.write(HEADER_SYNC)
        got_h2 = True
        break

    if not got_h2:
        raise errors.RadioError("H2 timeout")

    # H3: Receive encrypted 0x41
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            buf = port.read(1)[0]
            result = seed ^ buf
            if result != 0x41:
                raise errors.RadioError(
                    f"H3 failed: XOR result 0x{result:02X}")
            break
        time.sleep(0.01)
    else:
        raise errors.RadioError("H3 timeout")

    # H4: Send password (8 bytes of seed XOR 0xFF)
    password = bytes([seed ^ 0xFF] * 8)
    port.write(password)

    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            buf = port.read(1)[0]
            result = seed ^ buf
            if result != 0x41:
                raise errors.RadioError(
                    f"H4 failed: XOR result 0x{result:02X}")
            break
        time.sleep(0.01)
    else:
        raise errors.RadioError("H4 timeout")

    # H5: Send encrypted HEADER_INFO
    info_xor = bytes([seed ^ b for b in HEADER_INFO])
    port.write(info_xor)

    # Read model info
    time.sleep(0.1)
    if port.in_waiting > 0:
        model_data = port.read(min(port.in_waiting, 16))
        model_str = "".join(chr(b ^ seed) if b != 0xFF else ""
                            for b in model_data).strip()
        LOG.info(f"Radio model: {model_str}")

    # Send direction (0x52='R' for read, 0x57='W' for write)
    direction = 0x57 if is_write else 0x52
    port.write(bytes([seed ^ direction]))

    # H6: Receive encrypted 0x41
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            buf = port.read(1)[0]
            result = seed ^ buf
            if result != 0x41:
                raise errors.RadioError(
                    f"H6 failed: XOR result 0x{result:02X}")
            break
        time.sleep(0.01)
    else:
        raise errors.RadioError("H6 timeout")

    return seed


def _read_blocks(radio, seed):
    """Read 12 blocks of 4096 bytes each using XOR'd commands"""
    port = radio.pipe
    full = bytearray(DATA_LEN)
    rx_offset = 0
    block_size = 4096
    num_blocks = DATA_LEN // block_size

    port.timeout = 0.5

    status = chirp_common.Status()
    status.cur = 0
    status.max = num_blocks
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    for block_num in range(num_blocks):
        # Build XOR'd command
        cmd = bytes([
            seed ^ 0x52,
            seed ^ (rx_offset >> 8),
            seed ^ (rx_offset & 0xFF),
            seed
        ])

        port.write(cmd)

        # Read 4100-byte response
        resp = bytearray()
        deadline = time.time() + 6.0
        while len(resp) < 4100 and time.time() < deadline:
            if port.in_waiting > 0:
                chunk = port.read(min(port.in_waiting, 4100 - len(resp)))
                resp.extend(chunk)
            else:
                time.sleep(0.01)

        if len(resp) < 4100:
            raise errors.RadioError(
                f"Block {block_num}: short read {len(resp)}/4100")

        # Copy payload to buffer (skip 4-byte header)
        full[rx_offset:rx_offset + block_size] = resp[4:4100]
        rx_offset += block_size

        status.cur = block_num + 1
        radio.status_fn(status)

    # Send END command
    end_cmd = bytes([seed ^ b for b in END_INFO])
    port.write(end_cmd)

    # Wait for final ACK
    time.sleep(0.2)
    if port.in_waiting > 0:
        port.read(port.in_waiting)

    # XOR decrypt all data
    for i in range(DATA_LEN):
        full[i] ^= seed

    return bytes(full)


def _write_blocks(radio, seed, data):
    """Write 12 blocks of 4096 bytes each using XOR'd format"""
    port = radio.pipe
    block_size = 4096
    num_blocks = DATA_LEN // block_size
    tx_offset = 0

    port.timeout = 0.5

    status = chirp_common.Status()
    status.cur = 0
    status.max = num_blocks
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    for block_num in range(num_blocks):
        # Build XOR'd command
        cmd = bytes([
            seed ^ 0x57,  # 0x57 = 'W' for write
            seed ^ (tx_offset >> 8),
            seed ^ (tx_offset & 0xFF),
            seed
        ])

        # Build 4100-byte payload
        chunk = data[tx_offset:tx_offset + block_size]
        if len(chunk) < block_size:
            chunk = chunk + b'\xff' * (block_size - len(chunk))

        # XOR encrypt the payload
        encrypted = bytes([seed ^ b for b in chunk])
        payload = cmd + encrypted

        port.write(payload)

        # Wait for response
        deadline = time.time() + 6.0
        while time.time() < deadline:
            if port.in_waiting > 0:
                resp = port.read(1)[0]
                if (resp ^ seed) == 0x41:
                    break
            else:
                time.sleep(0.01)
        else:
            raise errors.RadioError(f"Block {block_num}: timeout")

        tx_offset += block_size

        status.cur = block_num + 1
        radio.status_fn(status)

    # Send END command
    end_cmd = bytes([seed ^ b for b in END_INFO])
    port.write(end_cmd)

    # Wait for final ACK
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            port.read(1)
            return
        time.sleep(0.01)


# The boot-picture protocol is a simplified, unencrypted variant of the clone
# protocol: a 3-stage handshake (H2 sends "Picture\xFF") followed by raw
# 4096-byte blocks that the radio ACKs with 0x41. No seed, no XOR. Mirrors the
# CPS writePicInfo path; the radio has no read-back for the boot image.

def _handshake_boot(radio):
    """Three-stage unencrypted handshake for the boot-image upload."""
    port = radio.pipe

    # H1: send T_INFO
    port.write(bytes(T_INFO))

    # H2: wait for a byte, switch to 115200 if it isn't an ACK, then send sync
    got_h2 = False
    for _ in range(25):
        time.sleep(0.2)
        if port.in_waiting <= 0:
            continue
        rb = port.read(1)
        if not rb:
            continue
        if rb[0] != 0x41:
            port.close()
            port.baudrate = 115200
            port.open()
            port.reset_input_buffer()
        port.write(HEADER_SYNC_PIC)
        got_h2 = True
        break

    if not got_h2:
        raise errors.RadioError("Boot handshake H2 timeout")

    # H3: expect a raw 0x41 ACK
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            ack = port.read(1)[0]
            if ack != 0x41:
                raise errors.RadioError(
                    "Boot handshake H3 failed: 0x%02X" % ack)
            return
        time.sleep(0.01)
    raise errors.RadioError("Boot handshake H3 timeout")


def _load_boot_image(path):
    """Load a boot image, converting a 24-bit BMP to big-endian RGB565.

    A non-.bmp file is treated as pre-converted raw RGB565 data. Mirrors CPS
    Convert24To16Bit / ReversalHighLowByte (FormProgressBar.cs:506).
    """
    if not str(path).lower().endswith(".bmp"):
        with open(path, "rb") as f:
            return f.read()

    try:
        from PIL import Image
    except ImportError:
        raise errors.RadioError(
            "Pillow is required for BMP conversion (pip install Pillow)")

    img = Image.open(path)
    w, h = img.size
    if (w, h) not in BOOT_IMAGE_SIZES:
        raise errors.RadioError(
            "Unsupported image size %dx%d (accepted: %s)" %
            (w, h, ", ".join("%dx%d" % s for s in BOOT_IMAGE_SIZES)))

    img = img.convert("RGB")
    data = bytearray()
    for y in range(h):
        for x in range(w):
            r, g, b = img.getpixel((x, y))
            px = (r >> 3) << 11 | (g >> 2) << 5 | (b >> 3)
            data.append(px >> 8)     # big-endian high byte
            data.append(px & 0xFF)   # big-endian low byte
    return bytes(data)


def _write_boot_image(radio, data):
    """Send the boot image as raw, zero-padded 4096-byte blocks."""
    port = radio.pipe
    port.timeout = 0.5
    block_size = 4096
    num_blocks = (len(data) + block_size - 1) // block_size

    status = chirp_common.Status()
    status.cur = 0
    status.max = num_blocks
    status.msg = "Uploading boot image..."
    radio.status_fn(status)

    sent = 0
    for block_num in range(num_blocks):
        chunk = data[sent:sent + block_size]
        block = bytes(chunk) + b"\x00" * (block_size - len(chunk))
        port.write(block)

        deadline = time.time() + 8.0
        while True:
            if port.in_waiting > 0:
                ack = port.read(1)[0]
                if ack != 0x41:
                    raise errors.RadioError(
                        "Boot block %d bad ACK 0x%02X" % (block_num, ack))
                break
            if time.time() > deadline:
                raise errors.RadioError(
                    "Boot block %d timeout" % block_num)
            time.sleep(0.01)

        sent += len(chunk)
        status.cur = block_num + 1
        radio.status_fn(status)

    # END marker (raw)
    port.write(END_INFO)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            port.read(port.in_waiting)
            break
        time.sleep(0.01)


def upload_boot_image(radio, path):
    """Convert and upload a boot image to the radio.

    @path is a 24-bit BMP (160x128, 240x240 or 240x320) or pre-converted
    raw RGB565 data.
    """
    LOG.info("Uploading boot image from %s", path)
    port = radio.pipe
    port.timeout = 0.1
    port.baudrate = 19200

    data = _load_boot_image(path)
    LOG.info("Boot image: %d bytes RGB565", len(data))
    try:
        _handshake_boot(radio)
        _write_boot_image(radio, data)
        LOG.info("Boot image upload complete")
    except Exception as e:
        raise errors.RadioError("Boot image upload failed: %s" % e)


MEM_FORMAT = """
// Frequency ranges the radio reports for itself, in the same BCD-in-hex
// encoding as the channel frequencies. Unused slots are zero.
#seekto 0x0010;
struct {
  ul32 lo;
  ul32 hi;
} rx_bands[4];

#seekto 0x0030;
struct {
  ul32 lo;
  ul32 hi;
} tx_bands[4];

#seekto 0x0080;
struct {
  ul32 rx_freq;    // 0  (little-endian)
  ul32 tx_freq;    // 4  (little-endian)
  u8 rx_tone[2];   // 8-9   (decode / receive sub-audio)
  u8 tx_tone[2];   // 10-11 (encode / transmit sub-audio)
  u8 unknown1[4];  // 12-15
  u8 flags1;       // 16  power[7:6] wideth[5] offsetdir[3:2]
                   //     freqinvert[1] talkaround[0]
  u8 flags2;       // 17    fivetoneptt[7:6] dtmfptt[5:4] sqtype[3:0]
  u8 unknown2;     // 18
  // Byte 19 bit 5 is "Launch banned" (receive only) in the CPS. It is not
  // exposed as duplex "off" because the v2_0_09 firmware ignores it: a
  // channel uploaded with the bit set still transmits, even after a power
  // cycle, and the radio has no matching entry in its channel menu.
  u8 unknown3[5];  // 19-23
  u8 modulation;   // 24    2 == AM, 0 == FM/NFM (see MODULATION_AM)
  u8 unknown4[7];  // 25-31
  char name[16];   // 32-47 GB2312
} memory[640];

#seekto 0x7A20;
u8 valid_flags[80];

// "Scan Add" bitmap, same layout as valid_flags: bit == 0 means scanned.
#seekto 0x81A0;
u8 scan_flags[80];

#seekto 0x7980;
struct {
  u8 cha_mode;                                                  // 0
  u8 chb_mode;                                                  // 1
  u16 cha_num;                                                  // 2
  u16 chb_num;                                                  // 4
  u8 cha_zone;                                                  // 6
  u8 chb_zone;                                                  // 7
  u8 blight_time;                                               // 8
  u8 blight_lv;                                                 // 9
  u8 cha_disp:4, chb_disp:4;                                    // 10
  u8 dual_mode;                                                 // 11
  u8 main_band;                                                 // 12
  u8 sqlv;                                                      // 13
  u8 vox_lv;                                                    // 14
  u8 vox_dly;                                                   // 15
  u8 posave;                                                    // 16
  u8 posave_dly;                                                // 17
  u8 lone_work_tim;                                             // 18
  u8 lone_work_rsp;                                             // 19
  u8 apo;                                                       // 20
  u8 tot;                                                       // 21
  u8 pre_tot;                                                   // 22
  u8 unknown23;                                                 // 23
  u8 gps_zone;                                                  // 24
  u8 unknown25;                                                 // 25
  u8 hz1750;                                                    // 26
  u8 unknown27[3];                                              // 27-29
  u8 noaa_ch;                                                   // 30
  u8 gps_id;                                                    // 31
  u8 voxsw:1, aprssw:1, lonework:1, daodi:1, voice:2, busylock:2; // 32
  u8 keylock:1, autokey:1, unknown33:6;                        // 33
  u8 beep:1, endtone:2, unknown34:5;                           // 34
  u8 flag35;                                                    // 35
  u8 flag36;                                                    // 36
  u8 flag37;                                                    // 37
  u8 tailfreq:3, noaa:1, dispdir:1, fminter:1, noisecancel:1, enhance:1; // 38
  u8 unknown39;                                                 // 39
  u8 bt_hold;                                                   // 40
  u8 bt_rxdly;                                                  // 41
  u8 bt_mic;                                                    // 42
  u8 bt_spk;                                                    // 43
  u8 bt_password[4];                                            // 44-47
  u8 skey1;                                                     // 48
  u8 skey2;                                                     // 49
  u8 lkey1;                                                     // 50
  u8 lkey2;                                                     // 51
  u8 unknown52[12];                                             // 52-63
  u8 pow_password[8];                                           // 64-71
  u8 wr_password[8];                                            // 72-79
  char radio_name[16];                                          // 80-95
  char bluet_name[16];                                          // 96-111
  char pair_name[16];                                           // 112-127
} settings;
"""


def _download(radio):
    """Download from radio"""
    LOG.info("Downloading from Baofeng 5RH")
    port = radio.pipe
    port.timeout = 0.1
    port.baudrate = 19200

    try:
        seed = _handshake(radio, is_write=False)
        LOG.info(f"Handshake complete, seed=0x{seed:02X}")
        data = _read_blocks(radio, seed)
        LOG.info(f"Downloaded {len(data)} bytes")
        return data
    except Exception as e:
        raise errors.RadioError(f"Download failed: {e}")


def _upload(radio, data):
    """Upload to radio"""
    LOG.info("Uploading to Baofeng 5RH")
    port = radio.pipe
    port.timeout = 0.1
    port.baudrate = 19200

    try:
        seed = _handshake(radio, is_write=True)
        LOG.info(f"Handshake complete, seed=0x{seed:02X}")
        _write_blocks(radio, seed, data)
        LOG.info(f"Uploaded {len(data)} bytes")
    except Exception as e:
        raise errors.RadioError(f"Upload failed: {e}")


@directory.register
class BaofengUV5RHRadio(chirp_common.CloneModeRadio):
    """Baofeng 5RH Pro / UV-5RM Plus with GPS, v2 firmware."""
    VENDOR = "Baofeng"
    MODEL = "5RH Pro with GPS (v2)"
    BAUD_RATE = 19200

    def _bands_from_image(self):
        """RX ranges the radio reports in the image header, plus the airband.

        Reading the header beats hardcoding, because the same firmware ships
        on models with different coverage. It lists only the four main bands
        though, so the receive-only airband is added back. Falls back to
        VALID_BANDS when no image is loaded or the header looks unusable.
        """
        if self._memobj is None:
            return [AIRBAND] + VALID_BANDS

        bands = []
        for band in self._memobj.rx_bands:
            lo = _freq_bcd_to_hz(int(band.lo))
            hi = _freq_bcd_to_hz(int(band.hi))
            if lo and hi > lo:
                bands.append((lo, hi))
        if not bands:
            LOG.warning("No usable RX ranges in image header, using defaults")
            bands = list(VALID_BANDS)
        return [AIRBAND] + bands

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        # No per-channel tuning step: neither the channel struct nor the CPS
        # channel editor has such a field. valid_tuning_steps below is still
        # used to validate frequencies.
        rf.has_tuning_step = False
        rf.has_name = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        # RX and TX frequency are stored (and edited in the CPS) as two
        # independent fields, so an arbitrary split is supported.
        rf.can_odd_split = True

        rf.valid_bands = self._bands_from_image()
        rf.valid_modes = MODES
        rf.valid_tuning_steps = STEPS
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        # Both sub-audio fields are stored independently and each can hold a
        # CTCSS tone or a DCS code, so every combination is representable.
        # "DTCS->" is what the CPS produces for a TX-only DCS channel.
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "DTCS->DTCS", "DTCS->", "->Tone", "->DTCS"]
        rf.valid_duplexes = DUPLEX
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tones = TONES
        rf.valid_dtcs_codes = DTCS

        rf.memory_bounds = (1, 640)
        rf.valid_name_length = 16

        return rf

    def validate_memory(self, mem):
        msgs = []
        in_airband = chirp_common.in_range(mem.freq, [AIRBAND])
        if in_airband and mem.mode != "AM":
            msgs.append(chirp_common.ValidationWarning(
                "Frequency in this range requires AM mode"))
        elif not in_airband and mem.mode == "AM":
            msgs.append(chirp_common.ValidationWarning(
                "Frequency in this range must not be AM mode"))
        return msgs + super().validate_memory(mem)

    def sync_in(self):
        self._mmap = memmap.MemoryMapBytes(_download(self))
        self.process_mmap()

    def sync_out(self):
        if self._memobj is None:
            self.process_mmap()
        self._rebuild_zones()
        _upload(self, self._mmap.get_packed())

    def _rebuild_zones(self):
        """Regenerate the zone tables so every in-use channel is reachable.

        A channel is only reachable on the radio if its ID sits in a zone
        (DataProtocol.cs:1828). Chirp has no zone concept, so channels are
        mapped to zones by position: zone z holds channels
        [z*ZONE_CHN_MAX .. (z+1)*ZONE_CHN_MAX). Zone names are preserved; an
        unnamed but populated zone gets a "Zone N" default.
        """
        mm = self._mmap
        zones_used = 0
        for z in range(ZONE_MAX):
            zbase = ZONE_BASE + z * ZONE_SIZE
            count = 0
            for idx in range(ZONE_CHN_MAX):
                ch_index = z * ZONE_CHN_MAX + idx
                off = zbase + 2 + idx * 2
                if (ch_index < CHN_MAX and
                        self._get_flag(self._memobj.valid_flags, ch_index)):
                    mm[off] = (ch_index >> 8) & 0xFF
                    mm[off + 1] = ch_index & 0xFF
                    count += 1
                else:
                    mm[off] = 0xFF
                    mm[off + 1] = 0xFF
            mm[zbase] = count
            mm[zbase + 1] = 0xFF
            if count:
                zones_used += 1
                name_off = zbase + ZONE_NAME_OFF
                if mm[name_off][0] in (0x00, 0xFF):
                    for i, b in enumerate(_encode_name("Zone %d" % (z + 1))):
                        mm[name_off + i] = b
        mm[ZONE_TOTAL_OFF] = zones_used

    def upload_boot_image(self, path):
        upload_boot_image(self, path)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # Both per-channel bitmaps (valid_flags at 0x7A20, scan_flags at 0x81A0)
    # use a clear bit for "on", matching CPS ConvertChnValidFlg
    # (DataProtocol.cs:883).
    @staticmethod
    def _get_flag(bitmap, index):
        return ((int(bitmap[index // 8]) >> (index % 8)) & 1) == 0

    @staticmethod
    def _set_flag(bitmap, index, on):
        flags = int(bitmap[index // 8])
        if on:
            flags &= ~(1 << (index % 8))
        else:
            flags |= 1 << (index % 8)
        bitmap[index // 8] = flags

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        if not self._get_flag(self._memobj.valid_flags, number - 1):
            mem.empty = True
            return mem

        mem.freq = _freq_bcd_to_hz(int(_mem.rx_freq))
        tx_freq = _freq_bcd_to_hz(int(_mem.tx_freq))
        if tx_freq and tx_freq != mem.freq:
            mem.offset = abs(tx_freq - mem.freq)
            mem.duplex = "+" if tx_freq > mem.freq else "-"
        else:
            mem.duplex = ""
            mem.offset = 0

        # tx_tone is the encode (transmit) field, rx_tone the decode one
        chirp_common.split_tone_decode(
            mem,
            _decode_tone(_mem.tx_tone[0], _mem.tx_tone[1]),
            _decode_tone(_mem.rx_tone[0], _mem.rx_tone[1]),
        )

        # power[7:6]: 2 == High, 0 == Low; wideth[5]: set == 25K == FM
        mem.power = POWER_LEVELS[1] if (int(_mem.flags1) >> 6) >= 2 \
            else POWER_LEVELS[0]
        if int(_mem.modulation) == MODULATION_AM:
            mem.mode = "AM"
        else:
            mem.mode = "FM" if (int(_mem.flags1) >> 5) & 1 else "NFM"

        # "Scan Add" in the CPS; chirp inverts the sense via skip
        scanned = self._get_flag(self._memobj.scan_flags, number - 1)
        mem.skip = "" if scanned else "S"

        mem.name = _decode_name(_mem.get_raw(asbytes=True)[32:48]).rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b'\xff' * CHN_SIZE)
            self._set_flag(self._memobj.valid_flags, mem.number - 1, False)
            self._set_flag(self._memobj.scan_flags, mem.number - 1, False)
            return

        # Only a previously unused slot is cleared. An existing channel keeps
        # the bytes this driver does not decode (optional signaling, the DTMF
        # / 2-Tone / 5-Tone / MDC indexes, emergency system, ...), so editing
        # a channel in chirp does not silently reset its CPS settings.
        if not self._get_flag(self._memobj.valid_flags, mem.number - 1):
            _mem.set_raw(b'\x00' * CHN_SIZE)

        self._set_flag(self._memobj.valid_flags, mem.number - 1, True)
        self._set_flag(self._memobj.scan_flags, mem.number - 1,
                       mem.skip != "S")

        _mem.rx_freq = _freq_hz_to_bcd(mem.freq)

        if mem.duplex == "+":
            tx_freq = mem.freq + mem.offset
        elif mem.duplex == "-":
            tx_freq = mem.freq - mem.offset
        elif mem.duplex == "split":
            tx_freq = mem.offset
        else:
            tx_freq = mem.freq

        _mem.tx_freq = _freq_hz_to_bcd(tx_freq)

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _mem.tx_tone[0], _mem.tx_tone[1] = _encode_tone(txtone)
        _mem.rx_tone[0], _mem.rx_tone[1] = _encode_tone(rxtone)

        # flags2 sqtype[3:0]: the CPS sets 1 whenever a receive sub-audio tone
        # is present, so the squelch actually opens on it (0 otherwise). The
        # upper nibble holds the DTMF / 5-Tone PTT ID and is left alone.
        _mem.flags2 = (int(_mem.flags2) & 0xF0) | (1 if rxtone[0] else 0)

        # flags1: power[7:6] (High == 2), wideth[5] (wide == FM),
        # offsetdir[3:2]. Bits 1:0 (freqinvert, talkaround) are kept.
        # AM lives in its own byte; the radio leaves wideth set for it.
        _mem.modulation = MODULATION_AM if mem.mode == "AM" else 0

        flags1 = int(_mem.flags1) & 0x03
        if mem.power == POWER_LEVELS[1]:
            flags1 |= 2 << 6
        if mem.mode != "NFM":
            flags1 |= 0x20
        # offsetdir: 0 == simplex, 1 == TX above RX, 2 == TX below RX
        # (the CPS writes flags1 0xA4 and 0xA8 for those two cases).
        if tx_freq > mem.freq:
            flags1 |= 1 << 2
        elif tx_freq < mem.freq:
            flags1 |= 2 << 2
        _mem.flags1 = flags1

        _mem.name = _encode_name(mem.name or "")

    def get_settings(self):
        _s = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        group = RadioSettings(basic)

        def _list(key, name, options, idx):
            if idx < 0 or idx >= len(options):
                idx = 0
            rs = RadioSetting(
                key, name,
                RadioSettingValueList(options, current_index=idx))
            basic.append(rs)

        for key, name, options in _INDEX_SETTINGS:
            _list(key, name, options, int(getattr(_s, key)))

        # Special transforms
        _list("vox_lv", "VOX level", VOXLV_LIST, int(_s.vox_lv) - 1)

        dly = (int(_s.vox_dly) - 10) // 5
        _list("vox_dly", "VOX delay (s)", VOXDLY_LIST, dly)

        bt = int(_s.blight_time)
        bt_idx = 0 if bt < 5 else min(bt - 4, len(BLIGHTTIME_LIST) - 1)
        _list("blight_time", "Backlight time (s)", BLIGHTTIME_LIST, bt_idx)

        for key, name in _BOOL_SETTINGS:
            rs = RadioSetting(
                key, name,
                RadioSettingValueBoolean(bool(int(getattr(_s, key)))))
            basic.append(rs)

        cur_name = _decode_name(_s.get_raw(asbytes=True)[80:96])
        rs = RadioSetting("radio_name", "Radio name",
                          RadioSettingValueString(0, 16, cur_name))
        basic.append(rs)

        return group

    def set_settings(self, settings):
        _s = self._memobj.settings
        index_map = {k: opts for k, _, opts in _INDEX_SETTINGS}

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            key = element.get_name()
            val = element.value

            if key in index_map:
                setattr(_s, key, index_map[key].index(str(val)))
            elif key == "vox_lv":
                _s.vox_lv = int(str(val))
            elif key == "vox_dly":
                _s.vox_dly = int(round(float(str(val)) * 10))
            elif key == "blight_time":
                s = str(val)
                _s.blight_time = 0 if s == "Always" else int(s)
            elif key == "radio_name":
                _s.radio_name = _encode_name(str(val).rstrip())
            else:
                setattr(_s, key, 1 if bool(val) else 0)
