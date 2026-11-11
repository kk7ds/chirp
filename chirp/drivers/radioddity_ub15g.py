# Copyright 2026 Rob <95710162+thatSFguy@users.noreply.github.com>
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

import logging
import struct

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.drivers import radioddity_db40g as db40g
from chirp.settings import MemSetting, RadioSetting, RadioSettingGroup, \
    RadioSettings, RadioSettingValueBoolean, RadioSettingValueInteger, \
    RadioSettingValueList

LOG = logging.getLogger(__name__)

NUM_CHANNELS = 88
# Channel records sit at 0x10 * index on the radio. Mainboard firmware V1.1
# answers each read with 16 bytes and V1.2 with 24 (names added), whatever
# length is requested; both say 0x10 in the reply header. The image is the
# channel records in order, followed by the settings page.
ADDR_STEP = 0x10
SETTINGS_ADDR = 0xE000
READ_LEN = 0x18
TIMEOUT = 2
# How long to wait for bytes past the 16th when telling V1.1 from V1.2.
# V1.2 sends the whole reply within a few milliseconds, and leaves
# programming mode after well under a second without a request.
DETECT_TIMEOUT = 0.1

MIN_FREQ = 400000000
MAX_FREQ = 470000000
# Lowest GMRS repeater input. Current firmware won't transmit from here up
# on the programmable channels.
RP_TX_MIN = 467000000
FREQ_UNSET = 0xFFFFFFFF
# Factory channels mark "no tone" with 0xFFFF; channels added on the keypad
# use 0x0000.
TONE_UNSET = (0x0000, 0xFFFF)
NAME_LENGTH = 8

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("High", watts=15)]

# The radio supports only the 38 common CTCSS tones
TONES = (67.0, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
         97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
         131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 162.2, 167.9, 173.8,
         179.9, 186.2, 192.8, 203.5, 210.7, 218.1, 225.7, 233.6, 241.8,
         250.3)
DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

TOT_OPTIONS = ["Off", "60s", "120s", "180s"]

# A record holds 13 bytes of channel data, then (V1.2 only) the name. The
# last three bytes of every page are not channel data: on V1.1 they repeat
# bytes from the settings page. They are kept as read.
MEM_FORMAT = """
struct {
    u32 rxfreq;
    u32 txfreq;
    ul16 rxtone;
    ul16 txtone;
    u8 unknown1:1,
       pri_watch:1,
       busylock:1,
       scan:1,
       unknown2:1,
       wide:1,
       unknown3:1,
       highpower:1;
    %(name)s
    u8 tail[3];
} memory[%(count)d];

#seekto 0x%(settings)04X;
struct {
    u8 nrc:4,
       squelch:4;
    u8 unknown1:3,
       roger:1,
       keybeep:1,
       tot:3;
    // Mostly live state, such as the current channel and its frequency.
    u8 state[%(state)d];
} settings;
"""


def _read_reply(radio, addr, size):
    """Send a read request and return the reply's data bytes.

    The radio echoes the request header (with length 0x10) ahead of the data.
    If size is None, the page size is detected: the radio's reply is taken
    to end when no byte arrives for DETECT_TIMEOUT after the 16th.
    """
    request = struct.pack(">cHB", b"R", addr, READ_LEN)
    try:
        radio.pipe.write(request)
        header = radio.pipe.read(len(request))
        data = radio.pipe.read(16)
        if size is None:
            timeout = radio.pipe.timeout
            radio.pipe.timeout = DETECT_TIMEOUT
            try:
                data += radio.pipe.read(8)
            finally:
                radio.pipe.timeout = timeout
        elif size > 16:
            data += radio.pipe.read(size - 16)
    except Exception:
        LOG.exception("Failed to read 0x%04X", addr)
        raise errors.RadioError(
            "Failed to read from radio at 0x%04X" % addr)

    if len(header) != len(request) or header[:3] != request[:3]:
        raise errors.RadioError("Bad read response at 0x%04X" % addr)
    if size is not None and len(data) != size:
        raise errors.RadioError(
            "Short read at 0x%04X (%d bytes)" % (addr, len(data)))
    return data


def _write_page(radio, addr, data):
    """Write one page. The radio replies with a single ACK."""
    request = struct.pack(">cHB", b"W", addr, len(data))
    try:
        radio.pipe.write(request + data)
        ack = radio.pipe.read(1)
    except Exception:
        LOG.exception("Failed to write 0x%04X", addr)
        raise errors.RadioError(
            "Failed to write to radio at 0x%04X" % addr)
    if ack != db40g.CMD_ACK:
        raise errors.RadioError("No ACK after write at 0x%04X" % addr)


def _check_page_size(radio):
    """Read the settings page, checking the radio uses radio's page size.

    Returns the settings page. Called first in every session, so a V1.1
    image is never written to a V1.2 radio or the other way round.
    """
    data = _read_reply(radio, SETTINGS_ADDR, None)
    if len(data) != radio._page_size:
        raise errors.RadioError(
            "This radio's firmware doesn't match the selected model "
            "(%d-byte records, expected %d). Download a new image from the "
            "radio and use that." % (len(data), radio._page_size))
    return data


def _channel_page_for_write(page):
    """Return a channel page in the byte order the radio expects on write.

    The radio returns the two tone fields little-endian but stores what it
    is sent big-endian, so writing a page exactly as read would swap the
    bytes of every tone. Frequencies are sent unchanged.
    """
    tones = struct.unpack_from("<HH", page, 8)
    return page[:8] + struct.pack(">HH", *tones) + page[12:]


def _new_status(msg):
    status = chirp_common.Status()
    status.msg = msg
    status.cur = 0
    status.max = NUM_CHANNELS + 1
    return status


def do_download(radio):
    status = _new_status("Cloning from radio")
    size = radio._page_size
    data = bytearray(radio._memsize)

    radio.pipe.timeout = TIMEOUT
    db40g._enter_programming(radio)
    try:
        data[NUM_CHANNELS * size:] = _check_page_size(radio)
        status.cur += 1
        radio.status_fn(status)
        for i in range(NUM_CHANNELS):
            data[i * size:(i + 1) * size] = _read_reply(
                radio, i * ADDR_STEP, size)
            status.cur += 1
            radio.status_fn(status)
    finally:
        db40g._exit_programming(radio)

    return memmap.MemoryMapBytes(bytes(data))


def do_upload(radio):
    status = _new_status("Uploading to radio")
    size = radio._page_size
    raw = radio.get_mmap().get_packed()

    radio.pipe.timeout = TIMEOUT
    db40g._enter_programming(radio)
    try:
        _check_page_size(radio)
        _write_page(radio, SETTINGS_ADDR, raw[NUM_CHANNELS * size:])
        status.cur += 1
        radio.status_fn(status)
        for i in range(NUM_CHANNELS):
            page = raw[i * size:(i + 1) * size]
            _write_page(radio, i * ADDR_STEP, _channel_page_for_write(page))
            status.cur += 1
            radio.status_fn(status)
    finally:
        db40g._exit_programming(radio)


def _decode_tone(value):
    if value in TONE_UNSET:
        return '', None, None
    return db40g._decode_tone(value)


def _encode_tone(current, mode, value, polarity):
    """Encode a tone, keeping the radio's own "no tone" marker if unchanged."""
    if mode == '' and current in TONE_UNSET:
        return current
    return db40g._encode_tone(mode, value, polarity)


def _tx_freq(mem):
    """Return a memory's transmit frequency, or 0 if it can't transmit."""
    if mem.duplex == "off":
        return 0
    if mem.duplex == "split":
        return mem.offset
    if mem.duplex == "+":
        return mem.freq + mem.offset
    if mem.duplex == "-":
        return mem.freq - mem.offset
    return mem.freq


def _display_channel(number):
    """Return the channel number the radio shows for a CHIRP memory.

    CHIRP numbers the 88 records consecutively, while the radio labels them:

      Memory 1-14:  CH 1-14
      Memory 15-30: CH 15-22, each followed by its repeater as "RP"
      Memory 31-88: CH 23-80
    """
    if number <= 14:
        return number
    if number <= 30:
        return 15 + (number - 15) // 2
    return number - 8


def _immutable_fields(number, power_above_22):
    """Return the fields the radio's fixed GMRS channel plan locks.

    High power is always available on CH 15-22 and their repeaters, and on
    CH 23-80 only if power_above_22 (firmware V1.2).
    """
    channel = _display_channel(number)
    fields = []
    if number <= 30:
        fields += ["empty", "freq", "duplex", "offset"]
    if channel < 15 or (channel > 22 and not power_above_22):
        fields.append("power")
    if 8 <= channel <= 14:
        fields.append("mode")
    return fields


@directory.register
class RadioddityUB15G(db40g.RadioddityDB40G):
    """Radioddity UB15-G, mainboard firmware V1.1"""
    VENDOR = "Radioddity"
    MODEL = "UB15-G"
    BAUD_RATE = 115200

    _page_size = 16
    _memsize = (NUM_CHANNELS + 1) * 16
    # How this firmware's keypad marks an empty channel's frequencies
    _empty_freq = FREQ_UNSET
    # V1.1's keypad offers high/low power only on CH 15-22
    _power_above_22 = False

    @classmethod
    def detect_from_serial(cls, pipe):
        radio = cls(pipe)
        pipe.timeout = TIMEOUT
        db40g._enter_programming(radio)
        try:
            size = len(_read_reply(radio, SETTINGS_ADDR, None))
        finally:
            db40g._exit_programming(radio)
        for rcls in [RadioddityUB15G] + RadioddityUB15G.detected_models(
                include_self=False):
            if rcls._page_size == size:
                return rcls
        raise errors.RadioError(
            "Unsupported UB15-G firmware (%d-byte records)" % size)

    def get_features(self):
        rf = super().get_features()
        rf.has_name = False
        rf.valid_name_length = 0
        rf.valid_characters = ""
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        # CHIRP band ends are exclusive; the radio accepts 470.000 itself.
        rf.valid_bands = [(MIN_FREQ, MAX_FREQ + 1)]
        rf.valid_tones = TONES
        rf.valid_dtcs_codes = DTCS_CODES
        # The radio has no inverted DCS codes.
        rf.valid_dtcs_pols = ["NN"]
        rf.memory_bounds = (1, NUM_CHANNELS)
        return rf

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        # Firmware bug: mainboard firmware V1.1 and V1.2 refuse to transmit
        # on 467 MHz from the programmable channels (CH 23-80), with an
        # error beep, even when the vendor software programs them. Splits
        # below 467 MHz work. This is a warning, not an error, so these
        # channels can still be programmed for when the firmware is fixed.
        if (not mem.empty and mem.number > 30 and
                _tx_freq(mem) >= RP_TX_MIN):
            msgs.append(chirp_common.ValidationWarning(
                "Firmware V1.1 and V1.2 won't transmit on 467 MHz from "
                "memories 31-88 (CH 23-80). Until that is fixed, use an RP "
                "channel (even memories 16-30) to reach a repeater."))
        # The radio has one tone per channel, taken from the receive tone:
        # with only a transmit tone set (seen on V1.2), it shows and treats
        # the channel as having no tone.
        if not mem.empty:
            (txmode, _, _), (rxmode, _, _) = \
                chirp_common.split_tone_encode(mem)
            if txmode and not rxmode:
                msgs.append(chirp_common.ValidationWarning(
                    "The radio ignores a transmit tone unless a receive "
                    "tone is also set. Use TSQL or DTCS to reach a "
                    "repeater."))
        return msgs

    def _mem_format(self):
        return MEM_FORMAT % {
            "name": "",
            "count": NUM_CHANNELS,
            "settings": NUM_CHANNELS * self._page_size,
            "state": self._page_size - 2,
        }

    def process_mmap(self):
        self._memobj = bitwise.parse(self._mem_format(), self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        rxfreq = int(_mem.rxfreq)
        if not MIN_FREQ <= rxfreq <= MAX_FREQ:
            mem.empty = True
            mem.immutable = _immutable_fields(number, self._power_above_22)
            return mem

        mem.freq = rxfreq
        txfreq = int(_mem.txfreq)
        if not MIN_FREQ <= txfreq <= MAX_FREQ:
            mem.duplex = "off"
        elif txfreq == rxfreq:
            mem.duplex = ""
        else:
            mem.duplex = "+" if txfreq > rxfreq else "-"
            mem.offset = abs(txfreq - rxfreq)

        mem.mode = "FM" if _mem.wide else "NFM"
        mem.power = POWER_LEVELS[int(_mem.highpower)]
        mem.skip = "" if _mem.scan else "S"

        chirp_common.split_tone_decode(
            mem,
            _decode_tone(int(_mem.txtone)),
            _decode_tone(int(_mem.rxtone)))

        self._get_extra(_mem, mem)
        mem.immutable = _immutable_fields(number, self._power_above_22)
        return mem

    def _get_extra(self, _mem, mem):
        """Fill in the fields only some firmware versions have."""

    def _set_extra(self, _mem, mem):
        """Store the fields only some firmware versions have."""

    def _clear(self, _mem):
        _mem.rxfreq = self._empty_freq
        _mem.txfreq = self._empty_freq
        _mem.rxtone = db40g.TONE_OFF
        _mem.txtone = db40g.TONE_OFF
        _mem.scan = _mem.wide = _mem.highpower = 0

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            self._clear(_mem)
            return

        _mem.rxfreq = mem.freq
        if mem.duplex == "off":
            _mem.txfreq = FREQ_UNSET
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset
        elif mem.duplex == "+":
            _mem.txfreq = mem.freq + mem.offset
        elif mem.duplex == "-":
            _mem.txfreq = mem.freq - mem.offset
        else:
            _mem.txfreq = mem.freq

        _mem.wide = mem.mode == "FM"
        _mem.highpower = mem.power == POWER_LEVELS[1]
        _mem.scan = mem.skip != "S"

        ((txmode, txval, txpol),
         (rxmode, rxval, rxpol)) = chirp_common.split_tone_encode(mem)
        _mem.txtone = _encode_tone(int(_mem.txtone), txmode, txval, txpol)
        _mem.rxtone = _encode_tone(int(_mem.rxtone), rxmode, rxval, rxpol)

        self._set_extra(_mem, mem)

    def _basic_settings(self):
        _s = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")

        basic.append(MemSetting(
            "settings.squelch", "Squelch Level",
            RadioSettingValueInteger(0, 9, min(int(_s.squelch), 9))))
        basic.append(MemSetting(
            "settings.tot", "TX Timeout",
            RadioSettingValueList(
                TOT_OPTIONS,
                current_index=min(int(_s.tot), len(TOT_OPTIONS) - 1))))
        basic.append(MemSetting(
            "settings.keybeep", "Key Beep",
            RadioSettingValueBoolean(bool(_s.keybeep))))
        basic.append(MemSetting(
            "settings.roger", "Roger Beep",
            RadioSettingValueBoolean(bool(_s.roger))))
        basic.append(MemSetting(
            "settings.nrc", "RX Noise Reduction",
            RadioSettingValueBoolean(bool(_s.nrc))))
        return basic

    def get_settings(self):
        return RadioSettings(self._basic_settings())

    def set_settings(self, settings):
        for setting in settings.apply_to(self._memobj):
            if setting.has_apply_callback():
                setting.run_apply_callback()


@directory.register
@directory.detected_by(RadioddityUB15G)
class RadioddityUB15GV12(RadioddityUB15G):
    """Radioddity UB15-G, mainboard firmware V1.2: adds channel names"""
    VARIANT = "V1.2"

    _page_size = 24
    _memsize = (NUM_CHANNELS + 1) * 24
    # The vendor software writes empty channels with zero frequencies.
    _empty_freq = 0
    # V1.2's keypad also offers high power on CH 23-80
    _power_above_22 = True

    def get_features(self):
        rf = super().get_features()
        rf.has_name = True
        rf.valid_name_length = NAME_LENGTH
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC
        return rf

    def _mem_format(self):
        return MEM_FORMAT % {
            "name": "char name[%d];" % NAME_LENGTH,
            "count": NUM_CHANNELS,
            "settings": NUM_CHANNELS * self._page_size,
            "state": self._page_size - 2,
        }

    def _get_extra(self, _mem, mem):
        mem.name = str(_mem.name).rstrip("\x00 ")
        mem.extra = RadioSettingGroup("Extra", "extra")
        mem.extra.append(RadioSetting(
            "busylock", "Busy Lock",
            RadioSettingValueBoolean(bool(_mem.busylock))))

    def _set_extra(self, _mem, mem):
        _mem.name = mem.name.ljust(NAME_LENGTH)[:NAME_LENGTH]
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def _clear(self, _mem):
        super()._clear(_mem)
        _mem.name = " " * NAME_LENGTH
        _mem.busylock = _mem.pri_watch = 0

    def get_settings(self):
        basic = self._basic_settings()

        # The radio watches at most one priority channel; the vendor
        # software clears the flag on every other channel when it is set.
        options = ["Off"] + [str(n) for n in range(1, NUM_CHANNELS + 1)]
        current = next((i + 1 for i, m in enumerate(self._memobj.memory)
                        if m.pri_watch), 0)
        setting = RadioSetting(
            "pri_watch_channel", "Priority Watch Memory",
            RadioSettingValueList(options, current_index=current))
        setting.set_apply_callback(self._apply_pri_watch)
        basic.append(setting)
        return RadioSettings(basic)

    def _apply_pri_watch(self, setting):
        chosen = int(setting.value) if str(setting.value) != "Off" else 0
        for i, _mem in enumerate(self._memobj.memory):
            _mem.pri_watch = i + 1 == chosen
