# Copyright 2026 赵昕 BG8ADW
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

"""Weierwei VEV-V8 Plus radio management module

The VEV-V8 Plus is programmed by the Linton LT-6100E software (MCP6100, VB6
and MSComm32) at 9600 8N1, and it speaks the Leixen clone protocol: the same
frames, the same read and write commands, the same end of session.  Only the
handshake payload, the ident string and the memory layout differ, so this
driver calls the transport functions of :mod:`chirp.drivers.leixen`
(``do_ident``/``do_download``/``do_upload``/``make_frame``) instead of
carrying its own copy of them.  What is left here is the memory map, the
frequency, tone and power encoding, and the handshake retry this radio needs.

    0x0000  settings, not decoded and preserved as is
    0x0310  199 channels of 16 bytes (0x0310 + 199 * 16 = 0x0f80)

Channel record:

    +0   receive frequency, 6 digit BCD in kHz, three bytes
    +3   bit 3 (0x08) adds 500 Hz
    +4   transmit frequency, same encoding
    +8   receive CTCSS index, 0xff when there is no receive tone
    +9   0x82 when a receive tone is set, 0x00 otherwise
    +10  transmit CTCSS index, 0xff when there is no transmit tone
    +11  0x81 when a transmit tone is set, 0x00 otherwise
    +12  always 0xff, unknown
    +13  always 0xff, unknown
    +14  bit 7 high power, bit 6 wide bandwidth, bits 0-5 unknown
    +15  unknown, 0x70 in most channels written by the vendor software
         (0x52/0x71/0x72 also occur); preserved, and defaulted to 0x70 when
         a channel is created in a slot that was erased

THE TONE TABLE
--------------
The vendor software's tone combo box is initialised with these 47 strings
(``LT6100E.exe``, the ``Items.Strings`` property of the tone control):

    63.0, 67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
    97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8,
    136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3,
    173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5,
    206.5, 210.7, 218.1, 225.7, 229.1

i.e. 63.0 followed by the standard CTCSS table up to 229.1 - there is nothing
below 63.0 and no 233.6/241.8/250.3.  The radio stores the list position plus
one, and 0x00 and 0xff both mean "no tone" (the vendor software's own channel
data writes index 0 there).  Nine pairs taken from the channel data of the
reference radio pin the offset down, e.g. 71.9 -> 4, 82.5 -> 8, 88.5 -> 10,
100.0 -> 14, 110.9 -> 17, 118.8 -> 19, 131.8 -> 22, which is the CTCSS table
index plus two everywhere.  No captured channel uses 63.0 Hz, so that single
entry is placed by the list order (position 1) rather than measured.

BYTE 14, POWER AND BANDWIDTH
----------------------------
Writing a value to +14 and reading the channel back in the vendor software
gives: 0xff high/wide, 0x7f low/wide, 0x3f low/narrow, 0xbf high/**wide**,
0x00 low/narrow.  So with the high power bit set the vendor software ignores
the narrow bit - it shows, and therefore stores, wide.  That is a display
rule of the CPS on one sample, so this driver does not warn about it: both
bits are written as CHIRP asks and read back as they are stored.

NOT DECODED
-----------
The vendor software has a per channel alias column; its storage has not been
located (0x0f80 onwards is 0xff), so channels have no names in CHIRP.  DCS is
not implemented - no sample was seen.

Verified on a real radio: 8192 bytes downloaded, uploaded again and read back
with no differences, and a new channel written and read back unchanged.
"""

import logging
import time

from chirp import bitwise, chirp_common, directory, errors
from chirp.drivers import leixen

LOG = logging.getLogger(__name__)

MEM_SIZE = 0x2000
BLOCK_SIZE = 16
CHANNEL_COUNT = 199

# Handshake payload of this radio and the ident string it answers with; the
# rest of the protocol is leixen's, see the module docstring.
WAKE_PAYLOAD = bytes([0x46, 0x4C, 0x74, 0x06, 0x45, 0x04])
IDENT = b"Linton"

# The tone list of the vendor software, in its own order; the radio stores
# the position plus one.  See the module docstring for the evidence.
TONES = (63.0,) + tuple(tone for tone in chirp_common.TONES if tone <= 229.1)

RX_TONE_FLAG = 0x82
TX_TONE_FLAG = 0x81
NO_TONE = 0xFF

FREQ_HALF_KHZ = 0x08
UNKNOWN15_DEFAULT = 0x70

MEM_FORMAT = """
#seekto 0x0310;
struct {
  u8 rx_freq[4];
  u8 tx_freq[4];
  u8 rx_tone;
  u8 rx_tone_flag;
  u8 tx_tone;
  u8 tx_tone_flag;
  u8 unknown12;
  u8 unknown13;
  u8 highpower:1,
     wide:1,
     unknown14:6;
  u8 unknown15;
} memory[199];
"""


def _bcd_to_int(data):
    value = 0
    for byte in data:
        high = byte >> 4
        low = byte & 0x0F
        if high > 9 or low > 9:
            return None
        value = value * 100 + high * 10 + low
    return value


def _int_to_bcd(value, length):
    data = bytearray(length)
    for index in range(length - 1, -1, -1):
        value, low = divmod(value, 10)
        value, high = divmod(value, 10)
        data[index] = (high << 4) | low
    return bytes(data)


def _decode_freq(raw):
    """Decode 3 BCD kilohertz plus the 500 Hz bit, or None if erased."""
    khz = _bcd_to_int(raw[0:3])
    if khz is None:
        return None
    hz = khz * 1000
    if raw[3] & FREQ_HALF_KHZ:
        hz += 500
    return hz


def _encode_freq(hz):
    """Encode a frequency as BCD kilohertz plus a 500 Hz bit.

    The radio stores kilohertz and a half kilohertz flag, so anything below
    500 Hz resolution is rounded to the nearest 500 Hz.
    """
    khz, rem = divmod(int(hz), 1000)
    if rem >= 750:
        khz += 1
        extra = 0
    elif rem >= 250:
        extra = FREQ_HALF_KHZ
    else:
        extra = 0
    return _int_to_bcd(khz, 3) + bytes([extra])


@directory.register
class VEVV8PlusRadio(chirp_common.CloneModeRadio,
                     chirp_common.ExperimentalRadio):
    """Weierwei VEV-V8 Plus"""

    VENDOR = "Weierwei"
    MODEL = "VEV-V8 Plus"
    BAUD_RATE = 9600

    _memsize = MEM_SIZE
    _wake_payload = WAKE_PAYLOAD
    _ident = IDENT
    # The vendor software writes back every block it has read
    _upload_ranges = [(0x0000, MEM_SIZE)]

    _power_levels = [chirp_common.PowerLevel("High", watts=5.0),
                     chirp_common.PowerLevel("Low", watts=1.0)]

    # Measured: the radio answers a frame in about 70 ms, and it ignores the
    # host for about three seconds after the port is opened, which is why the
    # wake frame is retried instead of sent once - the vendor software resends
    # it too.  The timeout is set explicitly so that a silent port makes
    # read() return short rather than block, and the retry delay paces the
    # attempts (both were measured on the radio).
    IDENT_TIMEOUT = 0.25
    IDENT_RETRY_DELAY = 0.5
    IDENT_ATTEMPTS = 12

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver was reverse engineered from the LT-6100E "
            "programming software and tested on a VEV-V8 Plus.  Channel "
            "names are not decoded (the vendor software has an alias column "
            "whose storage has not been located) and DCS is not implemented.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = False
        rf.has_offset = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "->Tone"]
        # 400-470MHz means a receive and transmit frequency can never be
        # more than 70MHz apart, so the radio cannot express a split
        rf.valid_duplexes = ["", "+", "-", "off"]
        rf.valid_tuning_steps = [5.0, 10.0, 12.5, 25.0]
        rf.valid_tones = TONES
        rf.valid_power_levels = self._power_levels
        rf.valid_bands = [(400000000, 470000000)]
        rf.valid_skips = [""]
        rf.memory_bounds = (1, CHANNEL_COUNT)
        return rf

    # ---- transport ----
    def _handshake(self):
        """Wake the radio up and enter the read/write session."""
        self.pipe.timeout = self.IDENT_TIMEOUT
        for attempt in range(self.IDENT_ATTEMPTS):
            if attempt:
                # Measured on the radio: it is deaf for about three seconds
                # after the port is opened, so the first attempts time out and
                # the wake frame has to be resent (the vendor software does the
                # same).  Wait, then drop whatever arrived in the meantime, so
                # that a late answer to the previous attempt is not read as the
                # answer to this one.
                time.sleep(self.IDENT_RETRY_DELAY)
                self.pipe.reset_input_buffer()
            try:
                leixen.do_ident(self)
                return
            except errors.RadioError as exc:
                LOG.debug("Handshake attempt %i failed: %s", attempt + 1, exc)
        raise errors.RadioError("Radio did not answer the handshake")

    def sync_in(self):
        self._handshake()
        try:
            self._mmap = leixen.do_download(self)
        except errors.RadioError:
            leixen.finish(self)
            raise
        self.process_mmap()

    def sync_out(self):
        self._handshake()
        try:
            # The handshake already put the radio into the session
            leixen.do_upload(self, ident=False, ranges=self._upload_ranges)
        except errors.RadioError:
            leixen.finish(self)
            raise

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_settings(self):
        # The settings area is not decoded, so there is nothing to offer
        return None

    # ---- channel conversion ----
    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        rx = _decode_freq(_mem.rx_freq)
        if not rx:
            mem.empty = True
            return mem
        mem.freq = rx

        tx = _decode_freq(_mem.tx_freq)
        if not tx:
            # the transmit frequency is erased, so the radio is told not to
            # transmit on this channel at all
            mem.duplex = "off"
            mem.offset = 0
        else:
            chirp_common.split_to_offset(mem, rx, tx)

        mem.power = self._power_levels[0] if _mem.highpower \
            else self._power_levels[1]
        mem.mode = "FM" if _mem.wide else "NFM"

        tx_tone = self._decode_tone(_mem.tx_tone, _mem.tx_tone_flag,
                                    TX_TONE_FLAG)
        rx_tone = self._decode_tone(_mem.rx_tone, _mem.rx_tone_flag,
                                    RX_TONE_FLAG)
        chirp_common.split_tone_decode(
            mem,
            ("Tone", tx_tone, None) if tx_tone else ("", None, None),
            ("Tone", rx_tone, None) if rx_tone else ("", None, None))
        return mem

    @staticmethod
    def _decode_tone(index, flag, expected):
        """Return the tone at @index, or None if there is no tone there."""
        if flag != expected or int(index) == NO_TONE:
            return None
        position = int(index) - 1
        if not 0 <= position < len(TONES):
            LOG.warning("Channel holds out of range tone index 0x%2.2x",
                        int(index))
            return None
        return TONES[position]

    @staticmethod
    def _encode_tone(tone, flag):
        """Return the index and flag bytes for @tone.

        @flag is the flag that marks a tone as present; without a tone both
        bytes are cleared, which is what the vendor software writes.
        """
        if tone is None:
            return NO_TONE, 0x00
        try:
            return TONES.index(tone) + 1, flag
        except ValueError:
            LOG.warning("Tone %s is not in the radio's table", tone)
            return NO_TONE, 0x00

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        if mem.empty:
            _mem.set_raw(b"\xff" * BLOCK_SIZE)
            return

        rx = mem.freq
        if mem.duplex == "+":
            tx = rx + mem.offset
        elif mem.duplex == "-":
            tx = rx - mem.offset
        elif mem.duplex == "split":
            tx = mem.offset
        else:
            tx = rx

        _mem.rx_freq = _encode_freq(rx)
        if mem.duplex == "off":
            _mem.tx_freq = b"\xff" * 4
        else:
            _mem.tx_freq = _encode_freq(tx)

        (txmode, txtone, _txpol), (rxmode, rxtone, _rxpol) = \
            chirp_common.split_tone_encode(mem)
        _mem.tx_tone, _mem.tx_tone_flag = self._encode_tone(
            txtone if txmode == "Tone" else None, TX_TONE_FLAG)
        _mem.rx_tone, _mem.rx_tone_flag = self._encode_tone(
            rxtone if rxmode == "Tone" else None, RX_TONE_FLAG)

        _mem.highpower = (mem.power is None or
                          mem.power == self._power_levels[0])
        _mem.wide = mem.mode == "FM"

        if _mem.unknown15 in (0x00, 0xFF):
            _mem.unknown15 = UNKNOWN15_DEFAULT
