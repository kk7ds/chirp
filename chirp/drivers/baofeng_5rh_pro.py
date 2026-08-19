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

import logging

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import kenwood_tone
from chirp import memmap
from chirp.settings import (
    RadioSettings, RadioSettingGroup, RadioSetting,
    RadioSettingValueList, RadioSettingValueBoolean, RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

# The radio XORs the whole session after the sync header with the key it is
# given in the last byte of that header. It accepts any key, so use zero:
# that keeps serial traces readable instead of obfuscating them for no gain.
XOR_KEY = 0x00

HEADER_SYNC = b"PROGRAM" + bytes([XOR_KEY])
HEADER_SYNC_PIC = b"Picture\xff"  # boot-image handshake (no seed, no XOR)
HEADER_INFO = b"INFORMATION"
END_INFO = b"END\x00"

# Accepted boot-image dimensions (width, height)
BOOT_IMAGE_SIZES = [(160, 128), (240, 240), (240, 320)]
T_INFO = bytearray(16)
for _i in range(12, 16):
    T_INFO[_i] = 0xFF

DATA_LEN = 49152
BLOCK_SIZE = 4096
CHN_SIZE = 48
CHN_MAX = 640

# Zone layout. The radio navigates channels through zones: each zone holds a
# fixed array of channel IDs, with FFFF marking an unused slot (the CPS
# leaves such gaps in place rather than packing the list). A channel only
# appears on the radio if its ID is in a zone, so the zone table must be
# rebuilt on upload to reflect newly-added channels.
ZONE_TOTAL_OFF = 31360
ZONE_BASE = 31376
ZONE_SIZE = 152
ZONE_MAX = 10
ZONE_CHN_MAX = 64       # firmware limit: 10 * 64 == 640
ZONE_NAME_OFF = 136     # IDs occupy 2..129, 130..135 unused, name 136..151

TONES = chirp_common.TONES
DTCS = chirp_common.ALL_DTCS_CODES

POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=0.5),
    chirp_common.PowerLevel("High", watts=5),
]

DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "NFM", "AM"]

# Same set as the non-GPS sibling (UV17Pro in baofeng_uv17Pro.py). Names are
# stored as GB2312, which covers ASCII, and the factory radio name
# "welcome" shows the display handles lower case.
VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + "!@#$%^&*()+-=[]:\";'<>?,./"

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


def _announce(radio):
    """Send the initial announce and get the radio onto a rate we agree on.

    The radio replies with a plain "A" at the rate it wants to be talked to.
    A reply that is not "A" only means the port is at the wrong rate: an "A"
    sent at 115200 and sampled at 19200 decodes as 0xFF or 0xFE depending on
    line timing, never as anything meaningful. So rather than reading the
    byte as a protocol element, just retry at the other rate.

    Two of the three radios seen so far answer at 115200 and one at 19200,
    with no relation to the name on the badge, so this is most likely a
    firmware difference. Try the common case first and fall back.
    """
    port = radio.pipe
    timeout = port.timeout

    try:
        # The reply takes about 110ms, so a short timeout here keeps the
        # retry cheap for the radios that need the other rate.
        port.timeout = 1
        for baudrate in (115200, 19200):
            port.baudrate = baudrate
            port.reset_input_buffer()
            port.write(bytes(T_INFO))
            resp = port.read(1)
            if resp == b'A':
                LOG.info('Radio answered the announce at %i baud', baudrate)
                return
            LOG.info('No announce reply at %i baud (got %s)', baudrate,
                     resp and '0x%02X' % resp[0] or 'nothing')
    finally:
        port.timeout = timeout

    raise errors.RadioNoResponse('Radio did not respond')


def _handshake(radio, is_write=False):
    """Put the radio into clone mode.

    Everything after the sync header is XORed with the key the CPS puts in
    the last byte of HEADER_SYNC. The radio accepts any key, so XOR_KEY is
    zero, which makes the whole session readable in a serial trace.
    """
    port = radio.pipe

    _announce(radio)

    # The last byte of the sync header is the XOR key for the rest of the
    # session, and HEADER_SYNC already ends in XOR_KEY.
    port.write(HEADER_SYNC)
    if port.read(1) != bytes([XOR_KEY ^ 0x41]):
        raise errors.RadioError('Radio did not agree to program mode')

    port.write(bytes([XOR_KEY ^ 0xFF] * 8))
    if port.read(1) != bytes([XOR_KEY ^ 0x41]):
        raise errors.RadioError('Radio did not ACK the password')

    port.write(bytes([XOR_KEY ^ b for b in HEADER_INFO]))
    model = port.read(16)
    if len(model) != 16:
        raise errors.RadioError('Radio did not report its model')
    LOG.info('Radio model: %s', _decode_name(
        bytes(b ^ XOR_KEY for b in model)))

    # 0x52 == 'R' to read from the radio, 0x57 == 'W' to write to it
    port.write(bytes([XOR_KEY ^ (0x57 if is_write else 0x52)]))
    if port.read(1) != bytes([XOR_KEY ^ 0x41]):
        raise errors.RadioError('Radio refused the clone direction')


def _read_blocks(radio):
    """Read the image as 12 blocks of 4096 bytes."""
    port = radio.pipe
    full = bytearray(DATA_LEN)
    offset = 0

    status = chirp_common.Status()
    status.cur = 0
    status.max = DATA_LEN // BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    for block_num in range(DATA_LEN // BLOCK_SIZE):
        port.write(bytes([XOR_KEY ^ 0x52,
                          XOR_KEY ^ (offset >> 8),
                          XOR_KEY ^ (offset & 0xFF),
                          XOR_KEY]))

        # The radio echoes the 4-byte command back ahead of the payload
        resp = port.read(4 + BLOCK_SIZE)
        if len(resp) != 4 + BLOCK_SIZE:
            raise errors.RadioError(
                'Block %i: short read (%i of %i bytes)' % (
                    block_num, len(resp), 4 + BLOCK_SIZE))

        full[offset:offset + BLOCK_SIZE] = bytes(
            b ^ XOR_KEY for b in resp[4:])
        offset += BLOCK_SIZE

        status.cur = block_num + 1
        radio.status_fn(status)

    port.write(bytes([XOR_KEY ^ b for b in END_INFO]))
    port.read(1)

    return bytes(full)


def _write_blocks(radio, data):
    """Write the image as 12 blocks of 4096 bytes."""
    port = radio.pipe
    offset = 0

    status = chirp_common.Status()
    status.cur = 0
    status.max = DATA_LEN // BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    for block_num in range(DATA_LEN // BLOCK_SIZE):
        chunk = data[offset:offset + BLOCK_SIZE]
        chunk = chunk.ljust(BLOCK_SIZE, b'\xff')

        port.write(bytes([XOR_KEY ^ 0x57,
                          XOR_KEY ^ (offset >> 8),
                          XOR_KEY ^ (offset & 0xFF),
                          XOR_KEY]) +
                   bytes([XOR_KEY ^ b for b in chunk]))

        if port.read(1) != bytes([XOR_KEY ^ 0x41]):
            raise errors.RadioError(
                'Block %i: radio did not ACK the write' % block_num)

        offset += BLOCK_SIZE
        status.cur = block_num + 1
        radio.status_fn(status)

    port.write(bytes([XOR_KEY ^ b for b in END_INFO]))
    port.read(1)


# The boot-picture protocol is a simplified, unencrypted variant of the clone
# protocol: a 3-stage handshake (H2 sends "Picture\xFF") followed by raw
# 4096-byte blocks that the radio ACKs with 0x41. No seed, no XOR. Mirrors the
# CPS writePicInfo path; the radio has no read-back for the boot image.

def _handshake_boot(radio):
    """Unencrypted handshake for the boot-image upload."""
    port = radio.pipe

    _announce(radio)

    port.write(HEADER_SYNC_PIC)
    if port.read(1) != b'A':
        raise errors.RadioError('Radio did not agree to boot-image mode')


def _load_boot_image(path):
    """Load a boot image, converting a 24-bit BMP to big-endian RGB565.

    A non-.bmp file is treated as pre-converted raw RGB565 data. Mirrors CPS
    The radio expects big-endian RGB565.
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
    num_blocks = (len(data) + BLOCK_SIZE - 1) // BLOCK_SIZE

    status = chirp_common.Status()
    status.cur = 0
    status.max = num_blocks
    status.msg = "Uploading boot image..."
    radio.status_fn(status)

    for block_num in range(num_blocks):
        chunk = data[block_num * BLOCK_SIZE:(block_num + 1) * BLOCK_SIZE]
        port.write(bytes(chunk).ljust(BLOCK_SIZE, b'\x00'))

        if port.read(1) != b'A':
            raise errors.RadioError(
                'Boot block %i: radio did not ACK the write' % block_num)

        status.cur = block_num + 1
        radio.status_fn(status)

    port.write(END_INFO)
    port.read(1)


def upload_boot_image(radio, path):
    """Convert and upload a boot image to the radio.

    @path is a 24-bit BMP (160x128, 240x240 or 240x320) or pre-converted
    raw RGB565 data.
    """
    LOG.info("Uploading boot image from %s", path)
    radio.pipe.timeout = 6

    data = _load_boot_image(path)
    LOG.info("Boot image: %d bytes RGB565", len(data))
    try:
        _handshake_boot(radio)
        _write_boot_image(radio, data)
        LOG.info("Boot image upload complete")
    except Exception as e:
        raise errors.RadioError("Boot image upload failed: %s" % e)


MEM_FORMAT = """
// Frequency ranges the radio reports for itself, in the same BCD encoding
// as the channel frequencies (units of 10 Hz). Unused slots are zero.
#seekto 0x0010;
struct {
  lbcd lo[4];
  lbcd hi[4];
} rx_bands[4];

#seekto 0x0030;
struct {
  lbcd lo[4];
  lbcd hi[4];
} tx_bands[4];

// 0x0050: version strings, terminated with 0xFF. The firmware version is
// what the CPS shows under "Device Information".
char fw_version[8];
char hw_version[8];
char prog_date[16];

#seekto 0x0080;
struct {
  lbcd rx_freq[4]; // 0-3   BCD, units of 10 Hz
  lbcd tx_freq[4]; // 4-7
  u16 rxtone;      // 8-9   (decode / receive sub-audio)
  u16 txtone;      // 10-11 (encode / transmit sub-audio)
  u8 unknown1[4];  // 12-15
  u8 power:2,      // 16  2 == High, 0 == Low
     wideth:1,     //     set == 25K == FM
     unknown_f1:1,
     offsetdir:2,  //     0 == simplex, 1 == TX above RX, 2 == TX below
     freqinvert:1,
     talkaround:1;
  u8 fivetoneptt:2, // 17
     dtmfptt:2,
     sqtype:4;     //     1 whenever a receive sub-audio tone is present
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

// One bit per channel, and note the inverted sense: a *clear* bit means
// the channel is in use, and likewise that it is included in the scan.
#seekto 0x7A20;
lbit chn_unused[640];

#seekto 0x81A0;
lbit chn_unscanned[640];

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
    # A full 4100-byte block takes 2.1s at 19200 and 0.4s at 115200, so this
    # leaves plenty of headroom either way.
    radio.pipe.timeout = 6

    _handshake(radio, is_write=False)
    data = _read_blocks(radio)
    LOG.info("Downloaded %i bytes", len(data))
    return data


def _upload(radio, data):
    """Upload to radio"""
    LOG.info("Uploading to Baofeng 5RH")
    radio.pipe.timeout = 6

    _handshake(radio, is_write=True)
    _write_blocks(radio, data)
    LOG.info("Uploaded %i bytes", len(data))


class Baofeng5RHPro(chirp_common.CloneModeRadio):
    """Baofeng 5RH Pro family running v2 firmware.

    The same hardware is badged several ways: a unit labelled "UV-5RM Plus"
    carries FCC ID 2AJGM-5RHPRO, and units labelled "UV-5RH Plus", "5RH Pro"
    and "UV-5RM Plus" all speak this clone protocol. The subclasses below
    exist only so owners can find their radio under the name printed on it.

    What distinguishes this driver from the "UV-5RM Plus" one in
    baofeng_uv17Pro.py is the firmware generation, not the badge: v2
    firmware replaced the older clone protocol entirely.
    """
    VENDOR = "Baofeng"
    BAUD_RATE = 115200

    # CTCSS and DCS are stored BCD-style with 0x8000 flagging DCS and 0x4000
    # inverted polarity, which is the widely copied Kenwood scheme.
    _tone_model = kenwood_tone.KenwoodToneModel(
        dcs_base=0x8000, pol_mask=0x4000, tone_init=0x0000, tone_flag=0x0000,
        dcs_enc_base=16, tone_enc_base=16)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            'This driver is new and has only been tested on radios running '
            'v2 firmware (software version v2_0_09). Older firmware uses a '
            'different clone protocol and is not supported.\n'
            '\n'
            'Please save an unedited copy of your first successful download '
            'to a CHIRP Radio Images (*.img) file before making changes.')
        rp.pre_download = (
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = (
            "Follow these instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

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
            lo = int(band.lo) * 10
            hi = int(band.hi) * 10
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
        rf.valid_characters = VALID_CHARS

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
        try:
            data = _download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self._mmap = memmap.MemoryMapBytes(data)
        self.process_mmap()

    def sync_out(self):
        if self._memobj is None:
            self.process_mmap()
        self._rebuild_zones()
        try:
            _upload(self, self._mmap.get_packed())
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to upload to radio: %s" % e)

    def _rebuild_zones(self):
        """Regenerate the zone tables so every in-use channel is reachable.

        A channel is only reachable on the radio if its ID sits in a zone.
        Chirp has no zone concept, so channels are mapped to zones by
        position: zone z holds channels
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
                        not self._memobj.chn_unused[ch_index]):
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
        LOG.info('Radio firmware %s, hardware %s, programmed %s',
                 _decode_name(self._memobj.fw_version.get_raw(asbytes=True)),
                 _decode_name(self._memobj.hw_version.get_raw(asbytes=True)),
                 _decode_name(self._memobj.prog_date.get_raw(asbytes=True)))

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        if self._memobj.chn_unused[number - 1]:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        tx_freq = int(_mem.tx_freq) * 10
        if tx_freq and tx_freq != mem.freq:
            mem.offset = abs(tx_freq - mem.freq)
            mem.duplex = "+" if tx_freq > mem.freq else "-"
        else:
            mem.duplex = ""
            mem.offset = 0

        self._tone_model.get_tone(_mem, mem)

        mem.power = POWER_LEVELS[1] if _mem.power >= 2 else POWER_LEVELS[0]
        if int(_mem.modulation) == MODULATION_AM:
            mem.mode = "AM"
        else:
            mem.mode = "FM" if _mem.wideth else "NFM"

        # "Scan Add" in the CPS; chirp inverts the sense via skip
        mem.skip = "S" if self._memobj.chn_unscanned[number - 1] else ""

        mem.name = _decode_name(_mem.get_raw(asbytes=True)[32:48]).rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.fill_raw(b'\xff')
            self._memobj.chn_unused[mem.number - 1] = 1
            self._memobj.chn_unscanned[mem.number - 1] = 1
            return

        # Only a previously unused slot is cleared. An existing channel keeps
        # the bytes this driver does not decode (optional signaling, the DTMF
        # / 2-Tone / 5-Tone / MDC indexes, emergency system, ...), so editing
        # a channel in chirp does not silently reset its CPS settings.
        if self._memobj.chn_unused[mem.number - 1]:
            _mem.fill_raw(b'\x00')

        self._memobj.chn_unused[mem.number - 1] = 0
        self._memobj.chn_unscanned[mem.number - 1] = mem.skip == "S"

        _mem.rx_freq = mem.freq // 10

        if mem.duplex == "+":
            tx_freq = mem.freq + mem.offset
        elif mem.duplex == "-":
            tx_freq = mem.freq - mem.offset
        elif mem.duplex == "split":
            tx_freq = mem.offset
        else:
            tx_freq = mem.freq

        _mem.tx_freq = tx_freq // 10

        self._tone_model.set_tone(mem, _mem)

        # The CPS sets sqtype whenever a receive sub-audio tone is present, so
        # that the squelch actually opens on it.
        _mem.sqtype = 1 if int(_mem.rxtone) else 0

        # AM lives in its own byte; the radio leaves wideth set for it.
        _mem.modulation = MODULATION_AM if mem.mode == "AM" else 0

        _mem.power = 2 if mem.power == POWER_LEVELS[1] else 0
        _mem.wideth = mem.mode != "NFM"
        if tx_freq > mem.freq:
            _mem.offsetdir = 1
        elif tx_freq < mem.freq:
            _mem.offsetdir = 2
        else:
            _mem.offsetdir = 0

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


# One entry per name the hardware is sold under, so owners can find their
# radio by what is printed on it. See Baofeng5RHPro for why these are all
# the same device.

@directory.register
class Baofeng5RHProRadio(Baofeng5RHPro):
    MODEL = "5RH Pro"


@directory.register
class BaofengUV5RHPlus(Baofeng5RHPro):
    MODEL = "UV-5RH Plus"


@directory.register
class BaofengUV5RMPlusV2(Baofeng5RHPro):
    # baofeng_uv17Pro.py already registers "UV-5RM Plus" for the older
    # firmware, so the generation goes in VARIANT to keep the two apart.
    MODEL = "UV-5RM Plus"
    VARIANT = "v2"
