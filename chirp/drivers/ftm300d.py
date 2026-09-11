# Copyright 2026 CHIRP contributors
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

"""Yaesu FTM-300DR experimental driver.

Memory map from ADMS-12 CLNFTM300D.dat dumps (98304 bytes, ident AH071).
Clone-in/out is 38400 8N1, 131-byte frames (BE address + 128 payload +
sum%256), ACK 0x06, address wrap at 0x10000 for names.
"""

import logging
import struct

from chirp.drivers import yaesu_clone
from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.settings import MemSetting
from chirp.settings import RadioSetting
from chirp.settings import RadioSettingGroup
from chirp.settings import RadioSettings
from chirp.settings import RadioSettingValueBoolean
from chirp.settings import RadioSettingValueFloat
from chirp.settings import RadioSettingValueInteger
from chirp.settings import RadioSettingValueList
from chirp.settings import RadioSettingValueMap
from chirp.settings import RadioSettingValueString

LOG = logging.getLogger(__name__)

FRAME_LEN = 131
PAYLOAD_LEN = 128
# 16-bit clone address wraps; pass 2 is file offset + 0x10000 (names).
CLONE_PASS2 = 0x10000
CLONE_VFO_ADDR = 0xFFFD
CLONE_END_ADDR = 0xFFFE
CLONE_VFO_DEST = 0x0080
# Pass 1 skips 0x0080 (sent later as FFFD) and 0x0400 (never cloned).
CLONE_SKIP = (0x0080, 0x0400)
# ADMS-12 PUT (SCU-56): 768 ACKed frames. An extra leading 0x0000 in the
# capture had no ACK (~11.5s later identical retry) — not part of the
# protocol. GET from the radio also starts 0x0000, 0x0100, ...
# Wire time ~34ms/frame at 38400; ACK ~36ms after OUT; next OUT ~11ms
# after ACK. Do not copy FTM-350's 50ms post-ACK sleep. No greeting
# byte before frame 1; PC writes first and waits for 0x06.


def clone_addresses():
    """Return the frozen ADMS-12 clone address list (768 frames).

    Pass 1 0x0000-0xFF80 step 128 skipping 0x0080 and 0x0400, wrap to
    file +0x10000 for names, pass 2 0x0000-0x7F80, trailer FFFD (VFO
    at 0x80) and FFFE (end, 128 zeros, checksum 0xFD).
    """
    addrs = [
        addr for addr in range(0x0000, 0x10000, PAYLOAD_LEN)
        if addr not in CLONE_SKIP]
    addrs.extend(range(0x0000, 0x8000, PAYLOAD_LEN))
    addrs.append(CLONE_VFO_ADDR)
    addrs.append(CLONE_END_ADDR)
    return addrs


def clone_frame(addr, payload):
    """Build one 131-byte clone frame (BE address + 128 payload + sum%256)."""
    if len(payload) != PAYLOAD_LEN:
        raise ValueError("Clone payload must be %d bytes" % PAYLOAD_LEN)
    head = struct.pack(">H", addr) + payload
    return head + bytes([sum(head) % 256])


def image_to_clone_frames(mmap):
    """Serialize a 96 KiB image to the 768-frame clone stream."""
    data = mmap.get_packed() if hasattr(mmap, "get_packed") else mmap
    frames = []
    bank = 0
    prev = None
    for addr in clone_addresses():
        if prev is not None and prev >= 0xFF00 and addr < 0x100:
            bank = CLONE_PASS2
        if addr == CLONE_END_ADDR:
            payload = b"\x00" * PAYLOAD_LEN
        elif addr == CLONE_VFO_ADDR:
            payload = data[CLONE_VFO_DEST:CLONE_VFO_DEST + PAYLOAD_LEN]
        else:
            dest = addr + bank
            payload = data[dest:dest + PAYLOAD_LEN]
        frames.append(clone_frame(addr, payload))
        prev = addr
    return frames


def _read_clone_frame(pipe):
    """Read one 131-byte frame. Empty means nothing has arrived yet."""
    frame = pipe.read(FRAME_LEN)
    if not frame:
        return b""
    while len(frame) < FRAME_LEN:
        more = pipe.read(FRAME_LEN - len(frame))
        if not more:
            raise errors.RadioError("Timed out reading from radio")
        frame += more
    return frame


def _clone_in(radio):
    """Download the radio image over the 131-byte framed clone protocol."""
    pipe = radio.pipe
    if hasattr(pipe, "timeout"):
        pipe.timeout = 1

    data = memmap.MemoryMapBytes(b"\x00" * radio._memsize)
    expected = len(clone_addresses())
    bank = 0
    prev_addr = None
    frames = 0
    attempts = 30
    got_end = False

    while not got_end:
        if frames >= expected + 8:
            raise errors.RadioError("Radio sent too many clone frames")
        frame = _read_clone_frame(pipe)
        if not frame:
            if frames:
                raise errors.RadioError("Timed out reading from radio")
            attempts -= 1
            if attempts <= 0:
                raise errors.RadioNoResponse()
            continue

        addr, = struct.unpack(">H", frame[:2])
        payload = frame[2:130]
        checksum = frame[130]
        calc = sum(frame[:130]) % 256
        if calc != checksum:
            LOG.debug("Calc: %02x Real: %02x addr: %04x",
                      calc, checksum, addr)
            raise errors.RadioError("Block failed checksum")

        # SCU-56 does not echo; do not chew 0x06 into the next frame.
        pipe.write(b"\x06")

        if frames == 0 and addr == 0:
            ident = payload[:len(radio._model)]
            if ident != radio._model:
                raise errors.RadioError(
                    "Incorrect model ident (got %r)" % payload[:6])

        if addr == CLONE_END_ADDR:
            got_end = True
        elif addr == CLONE_VFO_ADDR:
            data[CLONE_VFO_DEST] = payload
        else:
            if (prev_addr is not None and prev_addr >= 0xFF00
                    and addr < 0x100):
                bank = CLONE_PASS2
                LOG.debug("Clone wrap to names at frame %d", frames)
            dest = addr + bank
            try:
                data[dest] = payload
            except IndexError:
                raise errors.RadioError(
                    "Clone address 0x%04X maps past end of image" % addr)

        prev_addr = addr
        frames += 1

        status = chirp_common.Status()
        status.cur = frames
        status.max = expected
        status.msg = "Cloning from radio"
        radio.status_fn(status)

    if frames != expected:
        LOG.warning("Expected %d clone frames, got %d", expected, frames)
    LOG.debug("Clone-in finished after %d frames", frames)
    return data


def _clone_out(radio):
    """Upload the radio image over the 131-byte framed clone protocol."""
    pipe = radio.pipe
    if hasattr(pipe, "timeout"):
        pipe.timeout = 1

    ident = bytes(radio.get_mmap()[0:len(radio._model)])
    if ident != radio._model:
        raise errors.RadioError(
            "Incorrect model ident (got %r)" % ident)

    frames = image_to_clone_frames(radio.get_mmap())
    expected = len(frames)

    for i, frame in enumerate(frames):
        attempts = 30 if i == 0 else 1
        while True:
            # SCU-56 does not echo; wait for a real 0x06 from the radio.
            pipe.write(frame)
            ack = pipe.read(1)
            if ack == b"\x06":
                break
            if ack:
                raise errors.RadioError(
                    "Radio refused block %d (got %r)" % (i, ack))
            attempts -= 1
            if attempts <= 0:
                if i == 0:
                    raise errors.RadioNoResponse()
                raise errors.RadioError(
                    "Timed out waiting for ACK on block %d" % i)
            LOG.debug("No ACK on frame 0, retrying (%d left)", attempts)

        status = chirp_common.Status()
        status.cur = i + 1
        status.max = expected
        status.msg = "Cloning to radio"
        radio.status_fn(status)

    LOG.debug("Clone-out finished after %d frames", expected)


YFREQ_FORMAT = """
struct yfreq {
  u8 fine_5k:1,
     fine_2k5:1,
     fine_1k25:1,
     fine_625:1,
     hun:4;
  u8 bcd[2];
};
"""

MEM_FORMAT = YFREQ_FORMAT + """
#seekto 0x0000;
u8 ident[6];

#seekto 0x0081;
u8 unknown_81_hi:2,
   fm_bandwidth_a:1,
   rx_am_a:1,
   rpt_shift_a:4;

#seekto 0x0085;
u8 vfo_tone_a:4,
   vfo_step_a:4;

#seekto 0x008C;
u16 rpt_shift_freq_a;

#seekto 0x0091;
u8 unknown_91_hi:2,
   fm_bandwidth_b:1,
   rx_am_b:1,
   rpt_shift_b:4;

#seekto 0x0095;
u8 vfo_tone_b:4,
   vfo_step_b:4;

#seekto 0x009C;
u16 rpt_shift_freq_b;

#seekto 0x009A;
u8 clock_type_b:1,
   unknown_9a:7;

#seekto 0x00A1;
u8 unit;

#seekto 0x00A4;
u8 apo;

#seekto 0x00A8;
u8 tz_west:1,
   tz_mag:7;

#seekto 0x00AA;
u8 tot;

#seekto 0x00AD;
u8 display_mode;

#seekto 0x00AF;
u8 gps_datum;

#seekto 0x00B5;
u8 gps_log;
u8 vox;
u8 vox_delay;
u8 recording_band;

#seekto 0x00E3;
u8 unknown_e3_hi:2,
   rx_coverage_a:1,
   rx_auto_a:1,
   step_auto_a:1,
   unknown_e3_2:1,
   rx_auto_menu_a:1,
   unknown_e3_lo:1;
u8 unknown_e4_hi:5,
   rpt_ars_a:1,
   unknown_e4_lo:2;

#seekto 0x00E5;
u8 unknown_e5_hi:2,
   band_scope:1,
   unknown_e5_lo:5;

#seekto 0x00E8;
u8 display_info:1,
   unknown_e8_hi:2,
   standby_beep_off:1,
   unknown_e8_3:1,
   target_location:1,
   digital_vw:1,
   unknown_e8_lo:1;
u8 unknown_e9_hi:6,
   sub_band_mute:2;
u8 unknown_ea_hi:2,
   unknown_ea_5:1,
   unknown_ea_4:1,
   recording_mic:1,
   unknown_ea_lo:3;

#seekto 0x00EB;
u8 location_service:1,
   unknown_eb_6:3,
   beep_on:1,
   unknown_eb_lo:3;

#seekto 0x00EC;
u8 gps_device:1,
   unknown_ec:7;

#seekto 0x00EE;
u8 ams_tx_mode;

#seekto 0x00F3;
u8 unknown_f3_hi:2,
   rx_coverage_b:1,
   rx_auto_b:1,
   step_auto_b:1,
   unknown_f3_2:1,
   rx_auto_menu_b:1,
   unknown_f3_lo:1;
u8 unknown_f4_hi:5,
   rpt_ars_b:1,
   unknown_f4_lo:2;

#seekto 0x00F9;
u8 unknown_f9_hi:2,
   unknown_f9_5:1,
   time_12hr:1,
   unknown_f9_3:1,
   date_fmt:3;

#seekto 0x00FA;
u8 unknown_fa_hi:3,
   beep_high:1,
   unknown_fa_lo:4;

#seekto 0x028F;
u8 lcd_brightness;

#seekto 0x02D6;
u8 compass;

#seekto 0x02DB;
u8 digital_popup;

#seekto 0x02DD;
u8 mic_gain;

#seekto 0x02C8;
u8 callsign[10];

#seekto 0x0508;
u8 aprs_call[6];
u8 aprs_ssid;

#seekto 0x0534;
u8 aprs_modem;

#seekto 0x0800;
struct {
  u8 used:1,
     unknown0:1,
     skip:1,
     unknown1:3,
     uhf:1,
     unknown2:1;
  u8 unused_msb:1,
     ams:1,
     narrow:1,
     am:1,
     duplex:4;
  struct yfreq freq;
  u8 tone_mode:4,
     tune_step:4;
  struct yfreq tx_freq;
  u8 power:2,
     tone:6;
  u8 clock_shift:1,
     dcs:7;
  u8 unknown4:1,
     dn:1,
     unknown5:2,
     occupied:4;
  u8 unknown6;
  u8 offset;
  u8 dgid_rx;
  u8 dgid_tx;
} memory[999];

#seekto 0x4CB0;
u16 nameflags[999];

#seekto 0x10000;
struct {
  u8 text[16];
} names[999];
"""

# Factory-empty slot (144.000 analog) vs ADMS-programmed prototype.
EMPTY_SLOT = bytes.fromhex(
    "01 00 01 44 00 00 00 00 00 00 00 03 00 00 00 00")
USED_PROTOTYPE = bytes.fromhex(
    "81 00 01 46 50 00 00 00 00 0c 00 0f 00 0c 00 00")

POWER_LEVELS = [
    chirp_common.PowerLevel("Hi", watts=50),
    chirp_common.PowerLevel("Mid", watts=25),
    chirp_common.PowerLevel("Low", watts=5),
]

STEPS = [5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
# CONFIG 7 STEP. Nibble at 0x85/0x95 matches STEPS[]. Auto is E3/F3 bit 3
# with nibble 0 (same as 5.0 kHz). Proven: Auto, 5.0, 6.25, 10.0, 100.0.
# 8.33/12.5/15/20/25/50 inferred from STEPS index.
VFO_STEP_LABELS = [
    "AUTO",
    "5.0 kHz",
    "6.25 kHz",
    "8.33 kHz",
    "10.0 kHz",
    "12.5 kHz",
    "15.0 kHz",
    "20.0 kHz",
    "25.0 kHz",
    "50.0 kHz",
    "100.0 kHz",
]


def vfo_step_to_fields(label):
    if label == "AUTO":
        return 1, 0
    return 0, VFO_STEP_LABELS.index(label) - 1


# Duplex nibble from dumps: 0 simplex, 2 minus, 3 plus, 4 split.
DUPLEX_FROM_RADIO = {0: "", 2: "-", 3: "+", 4: "split"}
DUPLEX_TO_RADIO = {v: k for k, v in DUPLEX_FROM_RADIO.items()}

# High nibble of byte 5. 3 is TSQL-R (ADMS REV TONE). 5/6 are PR/Pager
# in dumps; not in CHIRP valid_tmodes yet.
TMODE_FROM_RADIO = {0: "", 1: "Tone", 2: "TSQL", 3: "TSQL-R", 4: "DTCS"}
TMODE_TO_RADIO = {v: k for k, v in TMODE_FROM_RADIO.items()}

# CONFIG 12 UNIT at 0x00A1 (USA default INCH). CONFIG 3 TIME ZONE at
# 0x00A8: sign-magnitude half-hours (bit7 west, low 7 bits 0-28).
# Proven: 0x00 = UTC +/-0:00, 0x01 = +0:30, 0x81 = -0:30.
UNIT_LABELS = ["METRIC", "INCH"]
TZ_HALF_MIN = -28
TZ_HALF_MAX = 28


def timezone_from_fields(west, mag):
    mag = int(mag)
    if int(west):
        return -mag
    return mag


def timezone_to_fields(half_hours):
    half = max(TZ_HALF_MIN, min(TZ_HALF_MAX, int(half_hours)))
    if half < 0:
        return 1, -half
    return 0, half


def timezone_label(half_hours):
    if half_hours == 0:
        return "UTC \u00b10:00"
    sign = "+" if half_hours > 0 else "-"
    h = abs(half_hours)
    return "UTC %s%d:%02d" % (sign, h // 2, (h % 2) * 30)


TIMEZONE_LABELS = [
    timezone_label(h) for h in range(TZ_HALF_MIN, TZ_HALF_MAX + 1)]

# CONFIG 2 DATE&TIME FORMAT at 0x00F9: date in bits 2-0, 12-hour in bit 4.
# Proven: MMM/DD/YYYY=2 (0x22), YYYY/MMM/DD=0 (0x20),
# DD/MMM/YYYY=4 (0x24), YYYY/DD/MMM=1 (0x21).
DATE_FORMAT_MAP = (
    ("YYYY/MMM/DD", 0),
    ("YYYY/DD/MMM", 1),
    ("MMM/DD/YYYY", 2),
    ("DD/MMM/YYYY", 4),
)
TIME_FORMAT_LABELS = ["24 HOUR", "12 HOUR"]
# CONFIG 9 CLOCK TYPE at 0x009A bit 7. Proven A=0, B=1.
CLOCK_TYPE_LABELS = ["A", "B"]

FM_BANDWIDTH_LABELS = ["WIDE", "NARROW"]
# MODE is per band (A=0x0081/0x00E3, B=0x0091/0x00F3). DIGITAL is global.
# FM bandwidth = bit5 of 81/91. RX MODE Auto = bit4 of E3/F3; AM = bit4
# of 81/91; FM = both 0. E3/F3 bit1 is "Auto listed in the radio menu"
# (writes set it).
RX_MODE_LABELS = ["AUTO", "FM", "AM"]
# TX/RX DIGITAL 4 STANDBY BEEP at 0x00E8 bit4 (1=Off).
# DIGITAL VW at 0x00E8 bit1. LOCATION SERVICE at 0x00EB bit7 (1=ON).
STANDBY_BEEP_LABELS = ["ON", "OFF"]
ON_Off_LABELS = ["OFF", "ON"]
# DIGITAL POPUP at 0x02DB. Proven Off=0 .. 60sec=8, Continue=0xFF.
# Default 10sec=5.
DIGITAL_POPUP_MAP = (
    ("OFF", 0),
    ("2 SEC", 1),
    ("4 SEC", 2),
    ("6 SEC", 3),
    ("8 SEC", 4),
    ("10 SEC", 5),
    ("20 SEC", 6),
    ("30 SEC", 7),
    ("60 SEC", 8),
    ("CONTINUE", 0xFF),
)
# TX/RX AUDIO MIC GAIN at 0x02DD. Proven MIN=0 .. Max=4. Default NORMAL=2.
MIC_GAIN_MAP = (
    ("MIN", 0),
    ("LOW", 1),
    ("NORMAL", 2),
    ("HIGH", 3),
    ("MAX", 4),
)
# SUB BAND MUTE at 0x00E9 bits 1-0. Proven ON=0, Off=3 (global).
SUB_BAND_MUTE_MAP = (("ON", 0), ("OFF", 3))
# VOX at 0x00B6. Proven Off=0, LOW=1, HIGH=2.
VOX_LABELS = ["OFF", "LOW", "HIGH"]
# VOX DELAY at 0x00B7. Proven 1.0s=1 .. 3.0s=5. Baseline 0 inferred as 0.5s.
VOX_DELAY_MAP = (
    ("0.5 SEC", 0),
    ("1.0 SEC", 1),
    ("1.5 SEC", 2),
    ("2.0 SEC", 3),
    ("2.5 SEC", 4),
    ("3.0 SEC", 5),
)
# RECORDING BAND at 0x00B8. Proven A=1, B=2, A+B=3.
RECORDING_BAND_MAP = (("A", 1), ("B", 2), ("A+B", 3))

# TX/RX DIGITAL AMS TX MODE at 0x00EE (global).
# Proven: Auto=0, TX FM FIXED=1, TX DN FIXED=2.
AMS_TX_MODE_LABELS = ["AUTO", "TX FM Fixed", "TX DN Fixed"]

# CONFIG 8 BEEP: Off / LOW / HIGH as two flags.
# Proven: enable = 0x00EB bit3, HIGH = 0x00FA bit4. Off leaves volume.
BEEP_LABELS = ["OFF", "LOW", "HIGH"]


def beep_from_fields(beep_on, beep_high):
    if not int(beep_on):
        return "OFF"
    if int(beep_high):
        return "HIGH"
    return "LOW"


def beep_to_fields(label):
    if label == "OFF":
        return 0, None
    if label == "HIGH":
        return 1, 1
    return 1, 0


def rx_mode_from_fields(rx_auto, rx_am):
    if int(rx_auto):
        return "AUTO"
    if int(rx_am):
        return "AM"
    return "FM"


def rx_mode_to_fields(label):
    if label == "AUTO":
        return 1, 0
    if label == "AM":
        return 0, 1
    return 0, 0


# DISPLAY 1 TARGET LOCATION at 0x00E8 bit 2. Proven Compass=0, Numeric=1.
TARGET_LOCATION_LABELS = ["COMPASS", "NUMERIC"]
# DISPLAY 2 COMPASS at 0x02D6. Proven North Up=0, Heading Up=1.
COMPASS_LABELS = ["NORTH UP", "HEADING UP"]
# DISPLAY 3 BAND SCOPE at 0x00E5 bit 5. Proven Wide=0, Narrow=1.
BAND_SCOPE_LABELS = ["WIDE", "NARROW"]
# GPS DATUM at 0x00AF. Proven WGS-84=0x15, Tokyo Mean=0xB2.
GPS_DATUM_MAP = (("WGS-84", 0x15), ("TOKYO MEAN", 0xB2))
# GPS DEVICE at 0x00EC bit 7. Proven Internal=0, External=1.
GPS_DEVICE_LABELS = ["INTERNAL", "EXTERNAL"]
# CONFIG 17 GPS LOG at 0x00B5.
# Proven: Off=0, 1s=1, 2s=2, 5s=3, 10s=4, 30s=5, 60s=6. Default Off.
GPS_LOG_MAP = (
    ("OFF", 0),
    ("1 SEC", 1),
    ("2 SEC", 2),
    ("5 SEC", 3),
    ("10 SEC", 4),
    ("30 SEC", 5),
    ("60 SEC", 6),
)
# CONFIG 11 RX COVERAGE at 0x00E3/0x00F3 bit 5 (per band).
# Proven: NORMAL=0, Wide=1 (factory).
RX_COVERAGE_LABELS = ["NORMAL", "WIDE"]
# CONFIG 14 TOT at 0x00AA. Factory 5 min.
# Proven: Off=0, 5min=1, 10min=2, 15min=3, 20min=4, 30min=5,
# 1min=6, 2min=7, 3min=8.
TOT_MAP = (
    ("OFF", 0),
    ("1 MIN", 6),
    ("2 MIN", 7),
    ("3 MIN", 8),
    ("5 MIN", 1),
    ("10 MIN", 2),
    ("15 MIN", 3),
    ("20 MIN", 4),
    ("30 MIN", 5),
)
# CONFIG 13 APO at 0x00A4, 0.5 hour units. Factory OFF=0.
# Proven: OFF=0, 0.5h=1, 1.0h=2, 1.5h=3, 2.0h=4, 3.0h=6, 4.0h=8,
# 12.0h=24. Other 0.5h steps inferred as n = hours*2.
APO_MAP = (("OFF", 0),) + tuple(
    ("%.1f HOUR" % (n / 2.0), n) for n in range(1, 25))
# CONFIG RPT ARS at 0x00E4/0x00F4 bit 2 (per band). Proven ON=1, Off=0.
# VFO RPT SHIFT is the duplex nibble of 0x81/0x91 (0=Off, 2=-, 3=+).
# VFO SHIFT FREQ at 0x8C/0x9C, u16 BE in 50 kHz units (manual 0.00-99.95).
# Proven: 0.75=0x000F, 1.45=0x001D, 3.10=0x003E, 5.00=0x0064,
# 20.00=0x0190. Factory A=0.60 (0x000C), B=5.00 (0x0064).
RPT_SHIFT_MAP = (("OFF", 0), ("-", 2), ("+", 3))
RPT_SHIFT_FREQ_STEP = 0.05
RPT_SHIFT_FREQ_MAX = 99.95
RPT_SHIFT_FREQ_UNITS_MAX = 1999  # 99.95 / 0.05


def _rpt_shift_freq_to_radio(value):
    units = int(round(float(value) / RPT_SHIFT_FREQ_STEP))
    if units < 0:
        units = 0
    if units > RPT_SHIFT_FREQ_UNITS_MAX:
        units = RPT_SHIFT_FREQ_UNITS_MAX
    return units


# DISPLAY 6 DISPLAY MODE: 0x00E8 bit 7 is the info screen (0=default)
# dual-band display). 0x00AD selects Backtrack=0, Altitude=1,
# Timer/Clock=2, GPS Information=3 when the info screen is on.
DISPLAY_MODE_LABELS = [
    "DEFAULT", "BACKTRACK", "ALTITUDE", "TIMER/CLOCK", "GPS INFORMATION"]


def display_mode_to_fields(label):
    if label == "DEFAULT":
        return 0, None
    return 1, DISPLAY_MODE_LABELS.index(label) - 1


# DISPLAY 4 LCD BRIGHTNESS at 0x028F. Proven MIN=3, MID=5, MAX=6.
BRIGHTNESS_MAP = (("MIN", 3), ("MID", 5), ("MAX", 6))
# F(SETUP) CALLSIGN: 10 chars at 0x02C8, 0xFF pad.
# APRS 21 CALLSIGN: 6 chars at 0x0508, 0xCA pad (empty is all 0xCA).
# SSID at 0x050E. Proven AAAAAA-13 -> 0x0D; empty pad 0xCA (not SSID 0).
# APRS 4 MODEM at 0x0534. Proven Off=0, ON=1.
# Radio CALLSIGN allows A-Z, 0-9, hyphen, and slash.
CALLSIGN_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/"
APRS_CALL_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
CALLSIGN_PAD = 0xFF
APRS_CALL_PAD = 0xCA
APRS_SSID_MAX = 15
# Empty SSID is pad 0xCA, distinct from SSID 0.
APRS_SSID_MAP = (("", APRS_CALL_PAD),) + tuple(
    (str(i), i) for i in range(APRS_SSID_MAX + 1))
APRS_MODEM_LABELS = ["OFF", "ON"]


def _decode_padded(raw, pad):
    buf = bytes(int(x) for x in raw)
    return buf.split(bytes([pad]))[0].split(b"\x00")[0].decode(
        "ascii", "replace").rstrip()


def _encode_padded(text, length, pad, charset):
    cleaned = "".join(c if c in charset else "" for c in text.upper())
    cleaned = cleaned[:length]
    data = cleaned.encode("ascii") + bytes([pad]) * (length - len(cleaned))
    return data


# Fine-step flags in the high nibble of the first freq byte.
# Proven: 0x80 = +5 kHz, 0x20 = +1.25 kHz, together +6.25 kHz (0xA0).
_FREQ_FINE = (
    ("fine_5k", 5000),
    ("fine_2k5", 2500),
    ("fine_1k25", 1250),
    ("fine_625", 625),
)


def decode_freq(freq):
    """Decode a yfreq struct to Hz."""
    digits = "%X%02X%02X" % (
        int(freq.hun), int(freq.bcd[0]), int(freq.bcd[1]))
    hz = int(digits, 10) * 10000
    for name, add in _FREQ_FINE:
        if int(getattr(freq, name)):
            hz += add
    return hz


def encode_freq(freq, hz):
    """Encode Hz into a yfreq struct."""
    rem = hz % 10000
    base = hz - rem
    for name, add in _FREQ_FINE:
        if rem >= add:
            setattr(freq, name, 1)
            rem -= add
        else:
            setattr(freq, name, 0)
    khz10 = base // 10000
    s = "%06d" % khz10
    freq.hun = int(s[1])
    freq.bcd[0] = (int(s[2]) << 4) | int(s[3])
    freq.bcd[1] = (int(s[4]) << 4) | int(s[5])


def parse_freq_bytes(raw):
    """Parse a 3-byte freq encoding (for tests)."""
    mmap = memmap.MemoryMapBytes(bytes(raw))
    freq = bitwise.parse(
        YFREQ_FORMAT + "struct yfreq freq;", mmap).freq
    return mmap, freq


def _set_bytes(element, data):
    for i, value in enumerate(data):
        element[i] = value


@directory.register
class FTM300Radio(yaesu_clone.YaesuCloneModeRadio,
                  chirp_common.ExperimentalRadio):
    """Yaesu FTM-300DR (USA)."""
    VENDOR = "Yaesu"
    MODEL = "FTM-300DR"
    BAUD_RATE = 38400
    NEEDS_COMPAT_SERIAL = False
    FORMATS = [directory.register_format('Yaesu FTM-300DR SD ALL', '*.dat')]

    _model = b"AH071"
    _memsize = 98304
    _tx_bands = [
        (144000000, 148000000),
        (430000000, 450000000),
    ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        # Keep these untranslated so we do not churn locale .po files.
        rp.experimental = (
            "The FTM-300DR driver is experimental. Memories, serial "
            "clone, and some Config/Display/callsign settings work; "
            "Home/PMS, most Set Mode items, and most APRS are not "
            "mapped. "
            "Keep a microSD ALL backup (SD CARD -> BACKUP -> WRITE TO "
            "SD -> ALL) before uploading. The stock USB cable in the box "
            "is not a programming cable.")
        rp.info = (
            "Use an SCU-56 or SCU-20 on the DATA jack at 38400 8N1. Keep "
            "a microSD ALL backup. If clone shows ERROR, restore with "
            "SD CARD -> READ FROM SD -> ALL.")
        rp.pre_download = (
            "1. Connect an SCU-56 or SCU-20 to the DATA jack "
            "(not the stock USB firmware cable).\n"
            "2. Press and hold [F(SETUP)], select CLONE, then "
            "[1 This → Other].\n"
            "3. <b>After clicking OK</b>, on the radio select OK and "
            "press the DIAL knob.\n")
        rp.pre_upload = (
            "Keep a microSD ALL backup first.\n"
            "1. Connect an SCU-56 or SCU-20 to the DATA jack "
            "(not the stock USB firmware cable).\n"
            "2. Press and hold [F(SETUP)], select CLONE, then "
            "[2 Other → This].\n"
            "3. <b>After clicking OK</b>, on the radio select OK and "
            "press the DIAL knob.\n")
        return rp

    def _append_mode(self, parent, suffix, title):
        group = RadioSettingGroup("band_%s" % suffix, title)
        parent.append(group)
        group.append(MemSetting(
            "fm_bandwidth_%s" % suffix, "FM Bandwidth",
            RadioSettingValueList(
                FM_BANDWIDTH_LABELS,
                current_index=int(
                    getattr(self._memobj, "fm_bandwidth_%s" % suffix)))))
        rx = rx_mode_from_fields(
            getattr(self._memobj, "rx_auto_%s" % suffix),
            getattr(self._memobj, "rx_am_%s" % suffix))
        group.append(RadioSetting(
            "rx_mode_%s" % suffix, "RX Mode",
            RadioSettingValueList(
                RX_MODE_LABELS, current_index=RX_MODE_LABELS.index(rx))))

    def _append_repeater_settings(self, parent, suffix, title):
        group = RadioSettingGroup("repeater_%s" % suffix, title)
        parent.append(group)
        group.append(MemSetting(
            "rpt_ars_%s" % suffix, "ARS",
            RadioSettingValueList(
                ON_Off_LABELS,
                current_index=int(
                    getattr(self._memobj, "rpt_ars_%s" % suffix)))))
        group.append(MemSetting(
            "rpt_shift_%s" % suffix, "Shift",
            RadioSettingValueMap(
                RPT_SHIFT_MAP,
                mem_val=int(
                    getattr(self._memobj, "rpt_shift_%s" % suffix)))))
        units = int(getattr(self._memobj, "rpt_shift_freq_%s" % suffix))
        mhz = round(units * RPT_SHIFT_FREQ_STEP, 2)
        group.append(RadioSetting(
            "rpt_shift_freq_%s" % suffix, "Shift Freq",
            RadioSettingValueFloat(
                0.0, RPT_SHIFT_FREQ_MAX, mhz, RPT_SHIFT_FREQ_STEP, 2)))

    def _append_step_settings(self, group, suffix, title):
        if int(getattr(self._memobj, "step_auto_%s" % suffix)):
            idx = 0
        else:
            idx = int(getattr(self._memobj, "vfo_step_%s" % suffix)) + 1
        rs = RadioSetting(
            "vfo_step_%s" % suffix, title,
            RadioSettingValueList(VFO_STEP_LABELS, current_index=idx))
        rs.set_doc(
            "VFO mode only. In Memory mode the radio uses each "
            "channel's Tuning Step.")
        group.append(rs)

    def _append_rx_coverage_settings(self, group, suffix, title):
        group.append(MemSetting(
            "rx_coverage_%s" % suffix, title,
            RadioSettingValueList(
                RX_COVERAGE_LABELS,
                current_index=int(
                    getattr(self._memobj, "rx_coverage_%s" % suffix)))))

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_bank_names = False
        rf.has_settings = True
        rf.has_ctone = False
        rf.has_dtcs = True
        rf.has_dtcs_polarity = False
        rf.has_cross = False
        rf.has_rx_dtcs = False
        rf.has_comment = False
        rf.has_nostep_tuning = False
        rf.can_odd_split = True
        rf.can_delete = True
        rf.memory_bounds = (1, 999)
        rf.valid_modes = ["FM", "NFM", "AM", "DN"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "TSQL-R", "DTCS"]
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 16
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_dtcs_codes = list(chirp_common.DTCS_CODES)
        rf.valid_bands = [
            (108000000, 174000000),
            (174000000, 400000000),
            (400000000, 480000000),
            (480000000, 824000000),
            (849000000, 869000000),
            (894000000, 999990000),
        ]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_settings(self):
        top = RadioSettings()
        config = RadioSettingGroup("config", "Config")
        top.append(config)

        half = timezone_from_fields(
            self._memobj.tz_west, self._memobj.tz_mag)
        tz_idx = half - TZ_HALF_MIN
        if tz_idx < 0 or tz_idx >= len(TIMEZONE_LABELS):
            tz_idx = len(TIMEZONE_LABELS)
        # Two bitfields; applied as leftover in set_settings().
        config.append(RadioSetting(
            "timezone", "Time Zone",
            RadioSettingValueList(
                TIMEZONE_LABELS, current_index=tz_idx)))

        date_time_format = RadioSettingGroup("date_time_format",
                                             "Date & Time Format")
        config.append(date_time_format)
        date_time_format.append(MemSetting(
            "date_fmt", "Date Format",
            RadioSettingValueMap(
                DATE_FORMAT_MAP, mem_val=int(self._memobj.date_fmt))))
        date_time_format.append(MemSetting(
            "time_12hr", "Time Format",
            RadioSettingValueList(
                TIME_FORMAT_LABELS,
                current_index=int(self._memobj.time_12hr))))

        repeater = RadioSettingGroup("repeater", "Repeater")
        config.append(repeater)
        self._append_repeater_settings(repeater, "a", "A Band")
        self._append_repeater_settings(repeater, "b", "B Band")

        vfo_step = RadioSettingGroup("vfo_step", "Step (VFO)")
        vfo_step.set_doc(
            "Tuning step in VFO mode. Auto follows the band plan. "
            "Memory mode uses each channel's Tuning Step in the "
            "memory editor.")
        config.append(vfo_step)
        self._append_step_settings(vfo_step, "a", "A Band")
        self._append_step_settings(vfo_step, "b", "B Band")

        rx_coverage = RadioSettingGroup("rx_coverage", "RX Coverage")
        config.append(rx_coverage)
        self._append_rx_coverage_settings(rx_coverage, "a", "A Band")
        self._append_rx_coverage_settings(rx_coverage, "b", "B Band")

        beep = beep_from_fields(
            self._memobj.beep_on, self._memobj.beep_high)
        config.append(RadioSetting(
            "beep", "Beep",
            RadioSettingValueList(
                BEEP_LABELS, current_index=BEEP_LABELS.index(beep))))

        config.append(MemSetting(
            "clock_type_b", "Clock Type",
            RadioSettingValueList(
                CLOCK_TYPE_LABELS,
                current_index=int(self._memobj.clock_type_b))))

        config.append(MemSetting(
            "unit", "Display Units",
            RadioSettingValueList(
                UNIT_LABELS, current_index=int(self._memobj.unit))))

        config.append(MemSetting(
            "apo", "APO",
            RadioSettingValueMap(APO_MAP, mem_val=int(self._memobj.apo))))

        config.append(MemSetting(
            "tot", "TOT",
            RadioSettingValueMap(TOT_MAP, mem_val=int(self._memobj.tot))))

        config.append(MemSetting(
            "gps_datum", "GPS Datum",
            RadioSettingValueMap(
                GPS_DATUM_MAP, mem_val=int(self._memobj.gps_datum))))
        config.append(MemSetting(
            "gps_device", "GPS Device",
            RadioSettingValueList(
                GPS_DEVICE_LABELS,
                current_index=int(self._memobj.gps_device))))
        config.append(MemSetting(
            "gps_log", "GPS Log",
            RadioSettingValueMap(
                GPS_LOG_MAP, mem_val=int(self._memobj.gps_log))))

        txrx = RadioSettingGroup("txrx", "TX/RX")
        top.append(txrx)

        mode = RadioSettingGroup("mode", "Mode")
        self._append_mode(mode, "a", "A Band")
        self._append_mode(mode, "b", "B Band")
        txrx.append(mode)

        digital = RadioSettingGroup("digital", "Digital")
        txrx.append(digital)
        digital.append(MemSetting(
            "ams_tx_mode", "AMS TX Mode",
            RadioSettingValueList(
                AMS_TX_MODE_LABELS,
                current_index=int(self._memobj.ams_tx_mode))))
        digital.append(MemSetting(
            "digital_popup", "Digital Popup",
            RadioSettingValueMap(
                DIGITAL_POPUP_MAP,
                mem_val=int(self._memobj.digital_popup))))
        digital.append(MemSetting(
            "location_service", "Location Service",
            RadioSettingValueList(
                ON_Off_LABELS,
                current_index=int(self._memobj.location_service))))
        digital.append(MemSetting(
            "standby_beep_off", "Standby Beep",
            RadioSettingValueList(
                STANDBY_BEEP_LABELS,
                current_index=int(self._memobj.standby_beep_off))))
        digital.append(MemSetting(
            "digital_vw", "Digital VW",
            RadioSettingValueList(
                ON_Off_LABELS,
                current_index=int(self._memobj.digital_vw))))

        audio = RadioSettingGroup("audio", "Audio")
        txrx.append(audio)
        audio.append(MemSetting(
            "sub_band_mute", "Sub Band Mute",
            RadioSettingValueMap(
                SUB_BAND_MUTE_MAP,
                mem_val=int(self._memobj.sub_band_mute))))
        audio.append(MemSetting(
            "mic_gain", "Mic Gain",
            RadioSettingValueMap(
                MIC_GAIN_MAP, mem_val=int(self._memobj.mic_gain))))

        vox = RadioSettingGroup("vox", "VOX")
        audio.append(vox)

        vox.append(MemSetting(
            "vox", "VOX",
            RadioSettingValueList(
                VOX_LABELS, current_index=int(self._memobj.vox))))
        vox.append(MemSetting(
            "vox_delay", "VOX Delay",
            RadioSettingValueMap(
                VOX_DELAY_MAP, mem_val=int(self._memobj.vox_delay))))

        recording = RadioSettingGroup("recording", "Recording")
        audio.append(recording)

        recording.append(MemSetting(
            "recording_band", "Recording Band",
            RadioSettingValueMap(
                RECORDING_BAND_MAP,
                mem_val=int(self._memobj.recording_band))))
        recording.append(MemSetting(
            "recording_mic", "Recording Mic",
            RadioSettingValueList(
                ON_Off_LABELS,
                current_index=int(self._memobj.recording_mic))))

        display = RadioSettingGroup("display", "Display")
        top.append(display)
        display.append(MemSetting(
            "target_location", "Target Location",
            RadioSettingValueList(
                TARGET_LOCATION_LABELS,
                current_index=int(self._memobj.target_location))))
        display.append(MemSetting(
            "compass", "COMPASS",
            RadioSettingValueList(
                COMPASS_LABELS, current_index=int(self._memobj.compass))))
        display.append(MemSetting(
            "band_scope", "Band Scope",
            RadioSettingValueList(
                BAND_SCOPE_LABELS,
                current_index=int(self._memobj.band_scope))))
        display.append(MemSetting(
            "lcd_brightness", "LCD Brightness",
            RadioSettingValueMap(
                BRIGHTNESS_MAP,
                mem_val=int(self._memobj.lcd_brightness))))
        if int(self._memobj.display_info):
            dmode_idx = int(self._memobj.display_mode) + 1
        else:
            dmode_idx = 0
        display.append(RadioSetting(
            "display_mode", "Display Mode",
            RadioSettingValueList(
                DISPLAY_MODE_LABELS, current_index=dmode_idx)))

        ident = RadioSettingGroup("callsign", "Callsign")
        top.append(ident)
        ident.append(RadioSetting(
            "callsign", "Radio Callsign",
            RadioSettingValueString(
                0, 10, self._decode_callsign(),
                autopad=False, charset=CALLSIGN_CHARSET)))

        aprs = RadioSettingGroup("aprs", "APRS")
        top.append(aprs)
        aprs.append(RadioSetting(
            "aprs_call", "APRS Callsign",
            RadioSettingValueString(
                0, 6, self._decode_aprs_call(),
                autopad=False, charset=APRS_CALL_CHARSET)))
        aprs.append(MemSetting(
            "aprs_ssid", "APRS SSID",
            RadioSettingValueMap(
                APRS_SSID_MAP, mem_val=int(self._memobj.aprs_ssid))))
        aprs.append(MemSetting(
            "aprs_modem", "APRS Modem",
            RadioSettingValueList(
                APRS_MODEM_LABELS,
                current_index=int(self._memobj.aprs_modem))))
        return top

    def set_settings(self, settings):
        leftover = settings.apply_to(self._memobj)
        for element in leftover:
            name = element.get_name()
            value = str(element.value)
            if name == "timezone":
                half = TIMEZONE_LABELS.index(value) + TZ_HALF_MIN
                west, mag = timezone_to_fields(half)
                self._memobj.tz_west = west
                self._memobj.tz_mag = mag
            elif name == "beep":
                on, high = beep_to_fields(value)
                self._memobj.beep_on = on
                if high is not None:
                    self._memobj.beep_high = high
            elif name == "display_mode":
                info, mode = display_mode_to_fields(value)
                self._memobj.display_info = info
                if mode is not None:
                    self._memobj.display_mode = mode
            elif name == "rpt_shift_freq_a":
                self._memobj.rpt_shift_freq_a = _rpt_shift_freq_to_radio(
                    value)
            elif name == "rpt_shift_freq_b":
                self._memobj.rpt_shift_freq_b = _rpt_shift_freq_to_radio(
                    value)
            elif name == "vfo_step_a":
                auto, nibble = vfo_step_to_fields(value)
                self._memobj.step_auto_a = auto
                self._memobj.vfo_step_a = nibble
            elif name == "vfo_step_b":
                auto, nibble = vfo_step_to_fields(value)
                self._memobj.step_auto_b = auto
                self._memobj.vfo_step_b = nibble
            elif name == "rx_mode_a":
                auto, am = rx_mode_to_fields(value)
                self._memobj.rx_auto_a = auto
                self._memobj.rx_am_a = am
                self._memobj.rx_auto_menu_a = 1
            elif name == "rx_mode_b":
                auto, am = rx_mode_to_fields(value)
                self._memobj.rx_auto_b = auto
                self._memobj.rx_am_b = am
                self._memobj.rx_auto_menu_b = 1
            elif name == "callsign":
                self._encode_callsign(value)
            elif name == "aprs_call":
                self._encode_aprs_call(value)

    def _decode_callsign(self):
        return _decode_padded(self._memobj.callsign, CALLSIGN_PAD)

    def _encode_callsign(self, text):
        data = _encode_padded(text, 10, CALLSIGN_PAD, CALLSIGN_CHARSET)
        _set_bytes(self._memobj.callsign, data)

    def _decode_aprs_call(self):
        return _decode_padded(self._memobj.aprs_call, APRS_CALL_PAD)

    def _encode_aprs_call(self, text):
        data = _encode_padded(text, 6, APRS_CALL_PAD, APRS_CALL_CHARSET)
        _set_bytes(self._memobj.aprs_call, data)

    def sync_in(self):
        try:
            self._mmap = _clone_in(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Failed to read: %s", e)
            raise errors.RadioError(
                "Failed to download from radio (%s)" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            _clone_out(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Failed to write: %s", e)
            raise errors.RadioError(
                "Failed to upload to radio (%s)" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.empty:
            return msgs
        if mem.duplex == "split":
            tx = mem.offset
        elif mem.duplex == "-":
            tx = mem.freq - mem.offset
        elif mem.duplex == "+":
            tx = mem.freq + mem.offset
        else:
            tx = mem.freq
        in_tx = any(lo <= tx < hi for lo, hi in self._tx_bands)
        if not in_tx:
            if mem.duplex in ("-", "+", "split"):
                msgs.append(chirp_common.ValidationError(
                    "TX frequency is outside amateur allocations "
                    "for this model"))
            else:
                msgs.append(chirp_common.ValidationWarning(
                    "RX-only frequency; radio will not transmit here"))
        return msgs

    def _decode_name(self, number):
        raw = bytes(int(x) for x in self._memobj.names[number - 1].text)
        return raw.split(b"\xff")[0].split(b"\x00")[0].decode(
            "ascii", "replace").rstrip()

    def _encode_name(self, name):
        cleaned = "".join(
            c if c in chirp_common.CHARSET_ASCII else " "
            for c in name)[:16]
        padded = cleaned.encode("ascii", "replace")
        return padded + b"\xff" * (16 - len(padded))

    def _get_extra(self, mem, _mem):
        extra = RadioSettingGroup("Extra", "extra")
        extra.append(MemSetting(
            "ams", "AMS mode",
            RadioSettingValueBoolean(bool(int(_mem.ams)))))
        extra.append(MemSetting(
            "dgid_rx", "RX DG-ID",
            RadioSettingValueInteger(0, 99, int(_mem.dgid_rx))))
        extra.append(MemSetting(
            "dgid_tx", "TX DG-ID",
            RadioSettingValueInteger(0, 99, int(_mem.dgid_tx))))
        extra.append(MemSetting(
            "clock_shift", "Clock Shift",
            RadioSettingValueBoolean(bool(int(_mem.clock_shift)))))
        mem.extra = extra

    def _apply_extra(self, mem, _mem):
        for setting in mem.extra:
            setting.apply_to_memobj(_mem)
        # AMS extra maps to _mem.ams; DN-only is the inverse bit.
        # Analog modes must not leave either digital flag set.
        if mem.mode == "DN":
            _mem.dn = 0 if int(_mem.ams) else 1
        else:
            _mem.ams = 0
            _mem.dn = 0

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._memobj.memory[number - 1]
        if not int(_mem.used):
            mem.empty = True
            return mem

        mem.empty = False
        mem.freq = decode_freq(_mem.freq)
        mem.duplex = DUPLEX_FROM_RADIO.get(int(_mem.duplex), "")
        if mem.duplex == "split":
            mem.offset = decode_freq(_mem.tx_freq)
        else:
            mem.offset = int(_mem.offset) * 50000
        mem.name = self._decode_name(number)
        mem.skip = "S" if int(_mem.skip) else ""
        try:
            mem.power = POWER_LEVELS[int(_mem.power)]
        except IndexError:
            mem.power = POWER_LEVELS[0]
        try:
            mem.tuning_step = STEPS[int(_mem.tune_step)]
        except IndexError:
            mem.tuning_step = STEPS[0]
        mem.tmode = TMODE_FROM_RADIO.get(int(_mem.tone_mode), "")
        try:
            mem.rtone = chirp_common.TONES[int(_mem.tone)]
        except IndexError:
            mem.rtone = 88.5
        mem.ctone = mem.rtone
        try:
            mem.dtcs = chirp_common.DTCS_CODES[int(_mem.dcs)]
        except IndexError:
            mem.dtcs = 23

        if int(_mem.am):
            mem.mode = "AM"
        elif int(_mem.narrow):
            mem.mode = "NFM"
        elif int(_mem.ams) or int(_mem.dn):
            mem.mode = "DN"
        else:
            mem.mode = "FM"

        self._get_extra(mem, _mem)
        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        name_idx = mem.number - 1
        if mem.empty:
            _mem.set_raw(EMPTY_SLOT)
            _set_bytes(self._memobj.names[name_idx].text, b"\xff" * 16)
            self._memobj.nameflags[name_idx] = 0xFFFF
            return

        if not int(_mem.used):
            _mem.set_raw(USED_PROTOTYPE)

        _mem.used = 1
        _mem.unknown2 = 1
        _mem.occupied = 0xF
        _mem.uhf = 1 if mem.freq >= 400000000 else 0
        _mem.skip = 1 if mem.skip == "S" else 0
        encode_freq(_mem.freq, mem.freq)
        _mem.duplex = DUPLEX_TO_RADIO.get(mem.duplex, 0)
        if mem.duplex == "split":
            encode_freq(_mem.tx_freq, int(mem.offset))
            _mem.offset = 0
        else:
            encode_freq(_mem.tx_freq, 0)
            _mem.offset = int(round(mem.offset / 50000.0)) if mem.offset else 0

        _mem.am = 1 if mem.mode == "AM" else 0
        _mem.narrow = 1 if mem.mode == "NFM" else 0
        if mem.mode != "DN":
            _mem.ams = 0
            _mem.dn = 0

        try:
            _mem.tune_step = STEPS.index(mem.tuning_step)
        except ValueError:
            _mem.tune_step = 0
        _mem.tone_mode = TMODE_TO_RADIO.get(mem.tmode, 0)
        try:
            _mem.tone = chirp_common.TONES.index(mem.rtone)
        except ValueError:
            _mem.tone = chirp_common.TONES.index(88.5)
        try:
            _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        except ValueError:
            _mem.dcs = 0
        if mem.power in POWER_LEVELS:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        encoded = self._encode_name(mem.name)
        _set_bytes(self._memobj.names[name_idx].text, encoded)
        self._memobj.nameflags[name_idx] = (
            0x0000 if mem.name.strip() else 0xFFFF)

        self._apply_extra(mem, _mem)
        if mem.mode == "DN" and not int(_mem.ams) and not int(_mem.dn):
            _mem.ams = 1
            _mem.dn = 0
