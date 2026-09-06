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
from chirp.settings import RadioSettingValueInteger
from chirp.settings import RadioSettingValueList
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

#seekto 0x00A1;
u8 unit;

#seekto 0x00A8;
u8 tz_west:1,
   tz_mag:7;

#seekto 0x028F;
u8 lcd_brightness;

#seekto 0x02C8;
u8 callsign[10];

#seekto 0x0508;
u8 aprs_call[6];

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
    if mag > TZ_HALF_MAX:
        mag = TZ_HALF_MAX
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

# DISPLAY 4 LCD BRIGHTNESS at 0x028F. Proven MIN=3, MID=5, MAX=6.
BRIGHTNESS_FROM_RADIO = {3: "MIN", 5: "MID", 6: "MAX"}
BRIGHTNESS_TO_RADIO = {v: k for k, v in BRIGHTNESS_FROM_RADIO.items()}
BRIGHTNESS_LABELS = ["MIN", "MID", "MAX"]

# F(SETUP) CALLSIGN: 10 chars at 0x02C8, 0xFF pad.
# APRS 21 CALLSIGN: 6 chars at 0x0508, 0xCA pad (empty is all 0xCA).
# Radio CALLSIGN allows A-Z, 0-9, hyphen, and slash.
CALLSIGN_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/"
APRS_CALL_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
CALLSIGN_PAD = 0xFF
APRS_CALL_PAD = 0xCA


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

        unit = int(self._memobj.unit)
        if unit not in (0, 1):
            unit = 1
        config.append(RadioSetting(
            "unit", "Display Units",
            RadioSettingValueList(UNIT_LABELS, current_index=unit)))

        half = timezone_from_fields(
            self._memobj.tz_west, self._memobj.tz_mag)
        label = timezone_label(half)
        try:
            idx = TIMEZONE_LABELS.index(label)
        except ValueError:
            idx = TIMEZONE_LABELS.index(timezone_label(0))
        config.append(RadioSetting(
            "timezone", "Time Zone",
            RadioSettingValueList(TIMEZONE_LABELS, current_index=idx)))

        display = RadioSettingGroup("display", "Display")
        top.append(display)
        bright = BRIGHTNESS_FROM_RADIO.get(
            int(self._memobj.lcd_brightness), "MID")
        display.append(RadioSetting(
            "lcd_brightness", "LCD Brightness",
            RadioSettingValueList(
                BRIGHTNESS_LABELS,
                current_index=BRIGHTNESS_LABELS.index(bright))))

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
        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            name = element.get_name()
            value = str(element.value)
            if name == "unit":
                self._memobj.unit = UNIT_LABELS.index(value)
            elif name == "timezone":
                half = TIMEZONE_LABELS.index(value) + TZ_HALF_MIN
                west, mag = timezone_to_fields(half)
                self._memobj.tz_west = west
                self._memobj.tz_mag = mag
            elif name == "lcd_brightness":
                self._memobj.lcd_brightness = BRIGHTNESS_TO_RADIO[value]
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
