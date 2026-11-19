# Copyright 2026 jsjacob
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

"""Samcom FPCN30A, as programmed by "SAMCOM_Radio_FreqTool" V1.2.

The protocol was reverse engineered from the vendor programming tool
(PocTools.exe, SAMCOM_Radio_FreqTools_V1.2-20231212) and checked against
real FPCN30A radios (model ID "ZW_U5W"). The full protocol description is
in docs/samcom_fpcn30a_protocol.md. In short:

- Channel frames are stored with RX in bytes 9-12 and TX in 13-16, the
  same order the radio reports them. (The vendor tool writes them the
  other way round, which swaps RX and TX on split channels.)
- Power, companding and scrambler (bytes 23-25) are stored per channel.
- The radio acknowledges the settings frame but does not apply its values,
  so settings are shown read-only. The frame is still required: without
  it the radio ignores the TX frequency in channel frames. It must not
  contain 0xFF values.
- For a while after it has been read (more than 1 s, less than 20 s), the
  radio acknowledges channel writes but ignores tone changes. The driver
  therefore waits READ_SETTLE_TIME after its own last read before writing.
- Every write session sets the serial number in the radio's working copy
  of its settings to 0xFF, and a write session that changes channels also
  sets VOX and squelch there to 0xFF (the radio then displays garbage for
  them). Turning the radio off and on restores all of them from storage.

Wire format (9600 8N1, DTR off). Data frames, in both directions:

    [0]    0x35 start
    [1]    command (1 = read, 2 = write; radio accepts 1..3)
    [2]    data type (2 = local settings, 3 = channel; radio accepts 2..7)
    [3:5]  big-endian value <= 1024 (sequence number on channel writes)
    [5]    checksum: low byte of the sum of every other byte in the frame
    [6]    payload length L
    [7:7+L] payload
    [7+L]  0x10 terminator

Control frames are three bytes: 36 06 10 (ACK), 36 05 10 (resend),
36 07 10 (complete).

The radio does not send a memory dump, so this driver keeps its own
small image: the settings payload followed by one record per channel.
Uploads send a vendor-style settings frame, the channel frames, then
COMPLETE, as the vendor tool does.
"""

import logging
import time

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.settings import RadioSetting
from chirp.settings import RadioSettingGroup
from chirp.settings import RadioSettings
from chirp.settings import RadioSettingValueString

LOG = logging.getLogger(__name__)

# Seconds to wait after reading the radio before writing to it; tone
# changes were ignored when written ~1 s after a read and applied after 20 s.
READ_SETTLE_TIME = 30

# time.monotonic() when this driver last finished talking to a radio
# during a read, or None
_last_read = None

MAGIC = b"SAMCOMFT"
NUM_CHANNELS = 22
SETTINGS_LEN = 41
CHANNEL_PAYLOAD_LEN = 27

START_DATA = 0x35
START_CTRL = 0x36
TERMINATOR = 0x10

CTRL_ACK = bytes([START_CTRL, 0x06, TERMINATOR])
CTRL_REPEAT = bytes([START_CTRL, 0x05, TERMINATOR])
CTRL_COMPLETE = bytes([START_CTRL, 0x07, TERMINATOR])

# PttWRP.CreateReadLocalInfo_Cmd in the vendor tool
CMD_READ_LOCAL_INFO = bytes([0x35, 0x01, 0x02, 0x01, 0x00, 0x49, 0x00, 0x10])

# Values the radio reported for power, companding and scrambler on every
# channel before any third-party write; used for newly created channels.
DEFAULT_CHANNEL_EXTRAS = (0x01, 0x00, 0x00)

TIMEOUT_READ = 2.0    # seconds; vendor uses 2000 ms when reading
TIMEOUT_WRITE = 1.0   # seconds; vendor uses 1000 ms when writing
RETRIES = 3           # vendor retries each request 3 times

MEM_FORMAT = """
char magic[8];

struct {
  char model[6];
  char unknown1[6];
  char serial[10];
  u8 freq_range;
  u8 tot;
  u8 vox;
  char userid[6];
  u8 group;
  u8 squelch;
  u8 voice_language;
  u8 scrambler;
  u8 companding;
  u8 power_mode;
  u8 unknown2[4];
} settings;

#seekto 0x0040;
struct {
  u8 used;
  bbcd rxfreq[4];
  bbcd txfreq[4];
  u8 rxtone;
  u8 txtone;
  u8 band;
  u8 power;
  u8 companding;
  u8 scrambler;
  u8 unknown;
} channels[22];
"""

MEMSIZE = 0x40 + NUM_CHANNELS * 16

# Tone index table used by the radio: 0 = off, then the standard 50
# CTCSS tones, then the standard 104 DCS codes (normal polarity only).
TONE_OFF = 0
CTCSS_BASE = 1
DCS_BASE = CTCSS_BASE + len(chirp_common.TONES)
TONE_MAX = DCS_BASE + len(chirp_common.DTCS_CODES) - 1

FREQ_RANGES = {0: "134-176 MHz", 1: "406.1-470 MHz"}
BANDS = {0: (134000000, 176000001), 1: (406100000, 470000001)}
MODES = ["FM", "NFM"]   # band byte: 0 = 25.0K, 1 = 12.5K (vendor UI order)
VOICE_LANGUAGES = {0: "English", 1: "Chinese"}


def checksum(frame):
    """Low byte of the sum of every byte except the checksum at [5]."""
    return sum(b for i, b in enumerate(frame) if i != 5) & 0xFF


def make_frame(cmd, dtype, value, payload):
    frame = bytearray([START_DATA, cmd, dtype,
                       (value >> 8) & 0xFF, value & 0xFF,
                       0, len(payload)])
    frame += payload
    frame.append(TERMINATOR)
    frame[5] = checksum(frame)
    return bytes(frame)


def check_frame(frame):
    """Mirror of Form_PocTool.Receive_PacketCheck in the vendor tool."""
    if len(frame) < 8 or frame[0] != START_DATA:
        return False
    length = frame[6]
    if len(frame) < length + 8 or frame[length + 7] != TERMINATOR:
        return False
    if not (1 <= frame[1] <= 3 and 2 <= frame[2] <= 7):
        return False
    if ((frame[3] << 8) | frame[4]) > 1024:
        return False
    return checksum(frame[:length + 8]) == frame[5]


class _Link:
    """Frame-level I/O over the radio pipe."""

    def __init__(self, radio):
        self.pipe = radio.pipe

    def _read_exact(self, count, deadline):
        data = b""
        while len(data) < count:
            if time.time() > deadline:
                return None
            chunk = self.pipe.read(count - len(data))
            if chunk:
                data += chunk
        return data

    def read_frame(self, timeout):
        """Return the next control or valid data frame, or None."""
        deadline = time.time() + timeout
        while True:
            start = self._read_exact(1, deadline)
            if start is None:
                return None
            if start[0] == START_CTRL:
                rest = self._read_exact(2, deadline)
                if rest is None:
                    return None
                frame = start + rest
                if frame[2] == TERMINATOR:
                    return frame
                LOG.debug("Ignoring malformed control frame %r", frame)
                continue
            if start[0] != START_DATA:
                LOG.debug("Skipping stray byte %02x", start[0])
                continue
            header = self._read_exact(6, deadline)
            if header is None:
                return None
            frame = start + header
            rest = self._read_exact(frame[6] + 1, deadline)
            if rest is None:
                return None
            frame += rest
            if check_frame(frame):
                return frame
            LOG.warning("Discarding invalid frame %s", frame.hex(" "))

    def transact(self, request, timeout, want_data):
        """Send request; return the reply following the vendor's rules.

        want_data=True waits for a data frame (or COMPLETE), as when
        reading. want_data=False waits for ACK, as when writing.
        A RESEND request or a timeout resends, up to RETRIES times.
        """
        for attempt in range(RETRIES + 1):
            self.pipe.write(request)
            while True:
                reply = self.read_frame(timeout)
                if reply is None or reply == CTRL_REPEAT:
                    LOG.debug("Resending (attempt %i): %s", attempt + 1,
                              "timeout" if reply is None else "radio asked")
                    break
                if reply == CTRL_COMPLETE:
                    return reply
                if want_data and reply[0] == START_DATA:
                    return reply
                if not want_data and reply == CTRL_ACK:
                    return reply
                LOG.debug("Ignoring unexpected reply %s", reply.hex(" "))
        raise errors.RadioError("Radio did not respond to %s" %
                                request[:8].hex(" "))


def _status(radio, cur, total, msg):
    if radio.status_fn:
        status = chirp_common.Status()
        status.cur = cur
        status.max = total
        status.msg = msg
        radio.status_fn(status)


def _prepare_pipe(radio):
    # The vendor tool opens the port with DTR disabled. CHIRP already opens
    # it that way (WANTS_DTR); this covers other callers.
    try:
        radio.pipe.dtr = False
    except Exception:
        LOG.debug("Pipe does not support DTR control")


def do_download(radio):
    global _last_read
    _prepare_pipe(radio)
    try:
        return _download(radio)
    finally:
        _last_read = time.monotonic()


def _wait_after_read(radio):
    """Wait until READ_SETTLE_TIME has passed since the last read."""
    if _last_read is None:
        return
    remaining = READ_SETTLE_TIME - (time.monotonic() - _last_read)
    while remaining > 0:
        _status(radio, int(READ_SETTLE_TIME - remaining), READ_SETTLE_TIME,
                "Waiting for the radio after reading (%i s)" %
                int(remaining + 0.999))
        time.sleep(min(1.0, remaining))
        remaining = READ_SETTLE_TIME - (time.monotonic() - _last_read)


def _download(radio):
    link = _Link(radio)
    image = bytearray(MEMSIZE)
    image[0:8] = MAGIC

    _status(radio, 0, NUM_CHANNELS + 1, "Reading settings")
    reply = link.transact(CMD_READ_LOCAL_INFO, TIMEOUT_READ, want_data=True)
    if reply == CTRL_COMPLETE:
        raise errors.RadioError("Radio ended the session before settings")
    payload = reply[7:7 + reply[6]]
    if len(payload) < 37:
        raise errors.RadioError("Settings reply too short (%i bytes)" %
                                len(payload))
    payload = payload[:SETTINGS_LEN].ljust(SETTINGS_LEN, b"\x00")
    image[0x08:0x08 + SETTINGS_LEN] = payload
    LOG.info("Radio model %r serial %r", payload[0:6], payload[12:22])

    # The vendor tool sends ACK and gets one channel per reply until the
    # radio sends COMPLETE, giving up after 30 exchanges.
    for _ in range(30):
        reply = link.transact(CTRL_ACK, TIMEOUT_READ, want_data=True)
        if reply == CTRL_COMPLETE:
            break
        if not (reply[1] == 1 or reply[2] == 3):
            raise errors.RadioError("Unexpected frame from radio: %s" %
                                    reply.hex(" "))
        number = reply[7]
        if not 1 <= number <= NUM_CHANNELS:
            LOG.warning("Ignoring channel %i from radio", number)
            continue
        base = 0x40 + (number - 1) * 16
        image[base] = 1
        image[base + 1:base + 5] = reply[9:13]    # RX
        image[base + 5:base + 9] = reply[13:17]   # TX
        image[base + 9] = reply[20]               # RX tone
        image[base + 10] = reply[21]              # TX tone
        image[base + 11] = reply[22]              # bandwidth
        image[base + 12:base + 15] = reply[23:26]  # power, companding,
        #                                            scrambler
        _status(radio, number, NUM_CHANNELS + 1, "Reading channels")
    else:
        raise errors.RadioError("Radio never signalled the end of the "
                                "channel list")

    return memmap.MemoryMapBytes(bytes(image))


# Offset of the user ID within the 41-byte settings payload
OFF_USERID = 25


def session_settings_frame(settings_raw):
    """Settings frame that opens a write session, built as the vendor tool
    builds it after reading a radio (Form_PocTool.CreateLocalPara):
    ASCII zeros over model and serial, the radio's own values where they
    are valid and the vendor tool's defaults otherwise.

    The radio does not apply these values, but it only accepts TX
    frequencies in channel frames that follow a settings frame. The frame
    never contains 0xFF: echoing a radio's 0xFF values back once blanked
    its settings block.
    """
    s = bytearray(settings_raw[:SETTINGS_LEN])
    s[0:22] = b"0" * 22
    s[22] = 0 if s[22] == 0 else 1                  # frequency range
    if not (s[23] % 10 == 0 and 30 <= s[23] <= 180):
        s[23] = 60                                  # time-out timer
    if s[24] > 5:
        s[24] = 0                                   # VOX
    if not all(b == 0 or 0x30 <= b <= 0x39 for b in s[25:31]):
        s[25:31] = b"\x00" * 6                      # user ID
    if not 1 <= s[31] <= NUM_CHANNELS:
        s[31] = 2                                   # group channel
    if not 1 <= s[32] <= 9:
        s[32] = 3                                   # squelch
    for offset, default, limit in ((33, 0, 2),      # voice language
                                   (34, 0, 2),      # scrambler
                                   (35, 0, 2),      # companding
                                   (36, 1, 3)):     # power mode
        if s[offset] >= limit:
            s[offset] = default
    s[37:41] = b"\x00" * 4
    return make_frame(0x02, 0x02, 0x0001, bytes(s))


def build_channel_frame(index, seq, chan):
    """Channel frame laid out as Form_PocTool.CreateChannelParaData does,
    except that RX goes first, which is the order the radio stores."""
    band = int(chan.band)
    payload = bytearray(CHANNEL_PAYLOAD_LEN)
    payload[0] = index + 1
    payload[2:6] = bytes(chan.rxfreq.get_raw())
    payload[6:10] = bytes(chan.txfreq.get_raw())
    payload[12] = band
    payload[13] = int(chan.rxtone)
    payload[14] = int(chan.txtone)
    payload[15] = band
    payload[16] = int(chan.power)
    payload[17] = int(chan.companding)
    payload[18] = int(chan.scrambler)
    return make_frame(0x02, 0x03, seq & 0xFF, bytes(payload))


def do_upload(radio):
    _prepare_pipe(radio)
    mem = radio._memobj
    used = [i for i in range(NUM_CHANNELS) if mem.channels[i].used]

    # Do not read the radio here: shortly after a read it ignores tone
    # changes. Wait out a read this driver did recently instead.
    _wait_after_read(radio)
    link = _Link(radio)

    # The settings frame opens the session; without it the radio ignores
    # TX frequencies. Its values are not applied by the radio.
    _status(radio, 0, len(used) + 1, "Starting write")
    reply = link.transact(session_settings_frame(mem.settings.get_raw()),
                          TIMEOUT_WRITE, want_data=False)
    if reply != CTRL_ACK:
        raise errors.RadioError("Radio refused the write session")

    # Sequence numbers start at 2, as in the vendor tool
    seq = 2
    for count, index in enumerate(used, 1):
        frame = build_channel_frame(index, seq, mem.channels[index])
        seq += 1
        reply = link.transact(frame, TIMEOUT_WRITE, want_data=False)
        if reply != CTRL_ACK:
            raise errors.RadioError("Radio refused channel %i" % (index + 1))
        _status(radio, count + 1, len(used) + 1, "Writing channels")

    # The vendor tool sends COMPLETE and ignores the answer.
    link.pipe.write(CTRL_COMPLETE)
    link.read_frame(TIMEOUT_WRITE)


def _decode_tone(index):
    index = int(index)
    if CTCSS_BASE <= index < DCS_BASE:
        return "Tone", chirp_common.TONES[index - CTCSS_BASE], None
    if DCS_BASE <= index <= TONE_MAX:
        return "DTCS", chirp_common.DTCS_CODES[index - DCS_BASE], "N"
    return "", None, None


def _encode_tone(mode, value, polarity):
    if mode == "Tone":
        return CTCSS_BASE + chirp_common.TONES.index(value)
    if mode == "DTCS":
        return DCS_BASE + chirp_common.DTCS_CODES.index(value)
    return TONE_OFF


@directory.register
class SamcomFPCN30A(chirp_common.CloneModeRadio):
    """Samcom FPCN30A"""
    VENDOR = "Samcom"
    MODEL = "FPCN30A"
    BAUD_RATE = 9600
    # Open the port with DTR and RTS off, as the vendor tool does.
    WANTS_DTR = False
    WANTS_RTS = False
    _memsize = MEMSIZE

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver was reverse engineered from the vendor programming "
            "software and has only been partially tested with real radios. "
            "It writes channels only; radio settings are shown read-only "
            "because the radio does not apply them over the cable. Save a "
            "backup with the vendor tool before uploading.")
        rp.pre_upload = (
            "The radio ignores tone changes written shortly after it has "
            "been read. If you read it with another program in the last "
            "half minute, wait before uploading (CHIRP waits by itself "
            "after its own download).\n\n"
            "After the upload, turn the radio off and on again. Until then "
            "it shows VOX and squelch wrongly.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, NUM_CHANNELS)
        rf.has_bank = False
        rf.has_name = False
        rf.has_tuning_step = False
        rf.has_dtcs_polarity = False
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_settings = True
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        # "Tone->" is omitted: CHIRP reports TX-tone-only as plain "Tone"
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "DTCS->DTCS", "->Tone", "->DTCS", "DTCS->"]
        rf.valid_dtcs_codes = chirp_common.DTCS_CODES
        rf.valid_modes = MODES
        rf.valid_skips = []
        rf.valid_bands = list(BANDS.values())
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata[:len(MAGIC)] == MAGIC

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Download failed")
            raise errors.RadioError("Failed to read from radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Upload failed")
            raise errors.RadioError("Failed to write to radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.channels[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.channels[number - 1]
        mem = chirp_common.Memory()
        mem.number = number
        if not _mem.used:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10
        chirp_common.split_to_offset(mem, mem.freq, int(_mem.txfreq) * 10)
        chirp_common.split_tone_decode(mem, _decode_tone(_mem.txtone),
                                       _decode_tone(_mem.rxtone))
        mem.mode = MODES[1] if int(_mem.band) == 1 else MODES[0]
        return mem

    def set_memory(self, mem):
        _mem = self._memobj.channels[mem.number - 1]
        if mem.empty:
            _mem.set_raw(b"\x00" * 16)
            return

        if not _mem.used:
            # New channel: use the per-channel values real radios report
            _mem.set_raw(b"\x00" * 16)
            (_mem.power, _mem.companding,
             _mem.scrambler) = DEFAULT_CHANNEL_EXTRAS
        _mem.used = 1
        _mem.rxfreq = mem.freq // 10
        _mem.txfreq = self._tx_freq(mem) // 10

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)
        _mem.txtone = _encode_tone(txmode, txval, txpol)
        _mem.rxtone = _encode_tone(rxmode, rxval, rxpol)
        _mem.band = MODES.index(mem.mode) if mem.mode in MODES else 0

    @staticmethod
    def _tx_freq(mem):
        if mem.duplex == "split":
            return mem.offset
        if mem.duplex == "+":
            return mem.freq + mem.offset
        if mem.duplex == "-":
            return mem.freq - mem.offset
        return mem.freq

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        freq_range = int(self._memobj.settings.freq_range)
        if freq_range not in BANDS or mem.empty:
            return msgs
        lo, hi = BANDS[freq_range]
        for freq in (mem.freq, self._tx_freq(mem)):
            if not lo <= freq < hi:
                msgs.append(chirp_common.ValidationWarning(
                    "Frequency %s is outside this radio's band (%s)" % (
                        chirp_common.format_freq(freq),
                        FREQ_RANGES[freq_range])))
                break
        return msgs

    def get_settings(self):
        """All settings are read-only: the radio does not apply the values
        in a settings frame (see session_settings_frame)."""
        _set = self._memobj.settings
        raw = bytes(_set.get_raw())
        info = RadioSettingGroup("info", "Radio Settings (read-only)")
        top = RadioSettings(info)

        def text(data):
            return "".join(chr(b) if 32 <= b < 127 else " "
                           for b in data).rstrip()

        def not_set(value):
            return "Not set (0x%02X)" % value

        def describe(name, value):
            if name == "freq_range":
                return FREQ_RANGES.get(value, not_set(value))
            if name == "tot":
                return ("%is" % value if value % 10 == 0 and
                        30 <= value <= 180 else not_set(value))
            if name == "vox":
                return ("Off" if value == 0 else "%i" % value
                        if value <= 5 else not_set(value))
            if name == "squelch":
                return "%i" % value if 1 <= value <= 9 else not_set(value)
            if name == "group":
                if value == 20:
                    # The radio's display shows channel 20 as "CH0"
                    return "CH20 (shown as CH0 on the radio)"
                return ("CH%i" % value if 1 <= value <= NUM_CHANNELS
                        else not_set(value))
            if name == "voice_language":
                return VOICE_LANGUAGES.get(value, not_set(value))
            return "%i" % value if value != 0xFF else not_set(value)

        rows = [("model", "Model", text(raw[0:6])),
                ("serial", "Serial number", text(raw[12:22]))]
        for name, label in (("freq_range", "Frequency range"),
                            ("tot", "Time-out timer"),
                            ("vox", "VOX level"),
                            ("squelch", "Squelch level"),
                            ("group", "Group channel"),
                            ("voice_language", "Voice prompt language"),
                            ("power_mode", "Power mode"),
                            ("companding", "Companding"),
                            ("scrambler", "Scrambler")):
            rows.append((name, label, describe(name, int(getattr(_set,
                                                                 name)))))
        userid = raw[OFF_USERID:OFF_USERID + 6]
        rows.append(("userid", "User ID",
                     not_set(0xFF) if set(userid) == {0xFF} else text(userid)))

        for name, label, value in rows:
            setting_value = RadioSettingValueString(0, 32, value,
                                                    autopad=False)
            setting_value.set_mutable(False)
            info.append(RadioSetting(name, label, setting_value))
        return top

    def set_settings(self, settings):
        # Settings are read-only; see get_settings.
        pass
