# Copyright 2026 Rich Dunajewski <rich@mygmrs.com>
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

"""Wouxun KG-989G radio management module.

The protocol and memory layout were worked out from serial captures
between the radio and the OEM "KG-916" programming software, and from
observing that software. No OEM code was copied. Confirmed on a real
radio.

Session (9600 baud): the PC sends 0x02 "RWITF" (read) or "WRITF" (write)
plus two 0xFF bytes, then 16 key bytes of its choice. After two short
handshake replies, memory moves in 16-byte blocks:

    PC:    0x57 + enc(00 HI LO 10 [16 data bytes when writing])
    radio: 0x57 + enc(xx HI LO 10 16 data bytes)  (read)  or  0x06 (write)

"enc" is a single running key byte K, shared by both directions for the
whole session and seeded from the key bytes: K = key[1] ^ key[3]. Each
byte is sent as c = p ^ K, and then K += c. The session ends with "T".

The radio answers reads for 0x0000-0x3FFF, and the driver downloads all of
it. The OEM software reads and writes only 0x0000-0x27CF (the rest is blank
apart from the band limits at 0x3E00), so uploads stop there too.
"""

import logging
import random
import time

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp.settings import (
    MemSetting, RadioSettingGroup, RadioSettings,
    RadioSettingValueBoolean, RadioSettingValueList)

LOG = logging.getLogger(__name__)

MEM_SIZE = 0x4000  # the radio answers reads up to 0x3FFF
WRITE_END = 0x27D0  # the OEM software only reads and writes below this
BLOCK = 0x10
CHAN_LO = 0x0100   # the OEM software skips empty blocks in this range
CHAN_HI = 0x1A00   # when uploading
NUM_CHANNELS = 400

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-=+*_ "
NAME_LEN = 6

MEM_FORMAT = """
#seekto 0x0020;
struct {
  u8 squelch;
  u8 unknown21[2];
  u8 beep;
} settings;

#seekto 0x0100;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  u8 rxtone_type;
  u8 rxtone;
  u8 txtone_type;
  u8 txtone;
  u8 power;
  u8 unknown13:7,
     bcl:1;
  u8 wide;
  u8 scan;
} memory[401];

#seekto 0x1B00;
struct {
  u8 chars[6];
} names[401];

#seekto 0x2500;
u8 used[51];

#seekto 0x2600;
u8 scan_bits[51];
"""

# Tone type byte: index into chirp_common.TONES / DTCS_CODES follows (1-based)
TONE_NONE, TONE_CTCSS, TONE_DCS_N, TONE_DCS_I = range(4)


def _bit(arr, n):
    return bool(arr[n // 8] & (1 << (n % 8)))


def _set_bit(arr, n, value):
    if value:
        arr[n // 8] = arr[n // 8] | (1 << (n % 8))
    else:
        arr[n // 8] = arr[n // 8] & ~(1 << (n % 8))


class _Cipher:
    """The single-byte running key used by the KG-916 protocol."""
    def __init__(self, key):
        self.k = (key[1] ^ key[3]) & 0xFF

    def encrypt(self, data):
        out = bytearray()
        for b in data:
            c = b ^ self.k
            self.k = (self.k + c) & 0xFF
            out.append(c)
        return bytes(out)

    def decrypt(self, data):
        out = bytearray()
        for c in data:
            out.append(c ^ self.k)
            self.k = (self.k + c) & 0xFF
        return bytes(out)


@directory.register
class KG989GRadio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):
    """Wouxun KG-989G"""
    VENDOR = "Wouxun"
    MODEL = "KG-989G"
    BAUD_RATE = 9600

    # The OEM software only offers High/Low; wattages are estimates
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.0),
                    chirp_common.PowerLevel("High", watts=5.0)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver is experimental. Save a backup image from your "
            "radio with CHIRP (and the Wouxun software if you have it) "
            "before uploading any changes.")
        return rp

    # ------------------------------------------------------------------
    # Serial protocol

    def _read(self, length, what):
        data = self.pipe.read(length)
        if len(data) != length:
            LOG.debug("Wanted %i bytes for %s, got %r", length, what, data)
            if not data:
                raise errors.RadioNoResponse()
            raise errors.RadioError("Short reply from radio (%s)" % what)
        return data

    def _expect_ack(self, what):
        ack = self._read(1, what)
        if ack != b"\x06":
            raise errors.RadioError("Radio refused %s (%r)" % (what, ack))

    def _start(self, write):
        magic = b"\x02WRITF\xff\xff" if write else b"\x02RWITF\xff\xff"
        # For about 4 seconds after a session ends the radio ignores a new
        # one, so keep asking for a while before giving up.
        deadline = time.time() + 8
        while True:
            self.pipe.write(magic)
            ack = self.pipe.read(1)
            if ack == b"\x06":
                break
            if ack:
                raise errors.RadioError("Radio refused program mode (%r)" %
                                        ack)
            if time.time() > deadline:
                raise errors.RadioNoResponse()
            LOG.debug("No answer to program mode, retrying")
        key = bytes(random.randint(0, 255) for _ in range(16))
        self._cipher = _Cipher(key)
        self.pipe.write(key)
        reply = self._read(12, "key exchange")
        if reply[0:1] != b"P":
            raise errors.RadioError("Unexpected reply to key exchange")
        self.pipe.write(b"\x06")
        self._read(18, "radio info")
        self.pipe.write(b"\x06")
        self._expect_ack("start of transfer")

    def _finish(self):
        try:
            self.pipe.write(b"T")
        except Exception:
            LOG.exception("Failed to end the session")

    def _status(self, addr, msg, end=MEM_SIZE):
        status = chirp_common.Status()
        status.cur = addr
        status.max = end
        status.msg = msg
        self.status_fn(status)

    def _read_block(self, addr):
        request = bytes([0x00, addr >> 8, addr & 0xFF, BLOCK])
        self.pipe.write(b"\x57" + self._cipher.encrypt(request))
        reply = self._read(5 + BLOCK, "block %04X" % addr)
        if reply[0] != 0x57:
            raise errors.RadioError("Bad reply at %04X" % addr)
        plain = self._cipher.decrypt(reply[1:])
        if plain[1:4] != request[1:4]:
            raise errors.RadioError("Radio sent the wrong block at %04X" %
                                    addr)
        return plain[4:]

    def _write_block(self, addr, data):
        frame = bytes([0x00, addr >> 8, addr & 0xFF, BLOCK]) + data
        self.pipe.write(b"\x57" + self._cipher.encrypt(frame))
        self._expect_ack("block %04X" % addr)

    def sync_in(self):
        data = b""
        try:
            self._start(write=False)
            for addr in range(0, MEM_SIZE, BLOCK):
                data += self._read_block(addr)
                self._status(addr + BLOCK, "Cloning from radio")
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Download failed")
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        finally:
            self._finish()
        self._mmap = memmap.MemoryMapBytes(data)
        self.process_mmap()

    def sync_out(self):
        image = self._mmap.get_packed()
        try:
            self._start(write=True)
            # Like the OEM software, write only up to WRITE_END and skip
            # channel blocks with no frequency in them
            for addr in range(0, WRITE_END, BLOCK):
                block = image[addr:addr + BLOCK]
                if CHAN_LO <= addr <= CHAN_HI and block[3] > 0x99:
                    continue
                self._write_block(addr, block)
                self._status(addr + BLOCK, "Cloning to radio", WRITE_END)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Upload failed")
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        finally:
            self._finish()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # ------------------------------------------------------------------
    # Memories

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
        rf.can_odd_split = True
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "DTCS->", "->Tone", "->DTCS", "DTCS->DTCS"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = CHARSET
        rf.valid_name_length = NAME_LEN
        rf.valid_dtcs_codes = chirp_common.DTCS_CODES
        rf.valid_tones = chirp_common.TONES
        # Band limits reported by the radio during the handshake
        rf.valid_bands = [(400000000, 480000000)]
        rf.memory_bounds = (1, NUM_CHANNELS)
        return rf

    def get_raw_memory(self, number):
        return (repr(self._memobj.memory[number]) +
                repr(self._memobj.names[number]))

    @staticmethod
    def _decode_tone(ttype, index):
        if ttype == TONE_CTCSS and 1 <= index <= len(chirp_common.TONES):
            return "Tone", chirp_common.TONES[index - 1], None
        if (ttype in (TONE_DCS_N, TONE_DCS_I) and
                1 <= index <= len(chirp_common.DTCS_CODES)):
            return ("DTCS", chirp_common.DTCS_CODES[index - 1],
                    "R" if ttype == TONE_DCS_I else "N")
        return "", None, None

    @staticmethod
    def _encode_tone(mode, value, pol):
        if mode == "Tone":
            return TONE_CTCSS, chirp_common.TONES.index(value) + 1
        if mode == "DTCS":
            return (TONE_DCS_I if pol == "R" else TONE_DCS_N,
                    chirp_common.DTCS_CODES.index(value) + 1)
        return TONE_NONE, 0

    def _get_name(self, number):
        name = ""
        for c in self._memobj.names[number].chars:
            if int(c) >= len(CHARSET):
                break
            name += CHARSET[int(c)]
        return name.rstrip()

    def _set_name(self, number, name):
        name = name.upper().ljust(NAME_LEN)[:NAME_LEN]
        chars = self._memobj.names[number].chars
        for i, ch in enumerate(name):
            chars[i] = CHARSET.index(ch) if ch in CHARSET else \
                CHARSET.index(" ")

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        mem = chirp_common.Memory(number)

        if (not _bit(self._memobj.used, number) or
                _mem.get_raw()[0:4] == b"\xff\xff\xff\xff"):
            mem.empty = True
            return mem

        rx = int(_mem.rxfreq) * 10
        if _mem.get_raw()[4:8] == b"\xff\xff\xff\xff":
            mem.freq = rx
            mem.duplex = "off"
        else:
            chirp_common.split_to_offset(mem, rx, int(_mem.txfreq) * 10)

        mem.name = self._get_name(number)
        chirp_common.split_tone_decode(
            mem,
            self._decode_tone(int(_mem.txtone_type), int(_mem.txtone)),
            self._decode_tone(int(_mem.rxtone_type), int(_mem.rxtone)))
        mem.power = self.POWER_LEVELS[1 if _mem.power else 0]
        mem.mode = "FM" if _mem.wide else "NFM"
        mem.skip = "" if _mem.scan else "S"

        mem.extra = RadioSettingGroup("extra", "Extra")
        rs = MemSetting("bcl", "Busy lockout",
                        RadioSettingValueBoolean(bool(_mem.bcl)))
        rs.set_doc("Don't transmit while the channel is busy")
        mem.extra.append(rs)
        return mem

    def set_memory(self, mem):
        number = mem.number
        _mem = self._memobj.memory[number]

        if mem.empty:
            # Slots the radio already treats as unused may hold stale
            # data; leave it alone, as the OEM software does
            if _bit(self._memobj.used, number):
                _mem.fill_raw(b"\xff")
                self._memobj.names[number].fill_raw(b"\xff")
            _set_bit(self._memobj.used, number, False)
            _set_bit(self._memobj.scan_bits, number, False)
            return

        if not _bit(self._memobj.used, number):
            # Defaults the OEM software uses for a new channel
            _mem.fill_raw(b"\x00")
            _mem.unknown13 = 0x04
        _set_bit(self._memobj.used, number, True)

        _mem.rxfreq = mem.freq // 10
        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xff")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) // 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) // 10
        else:
            _mem.txfreq = mem.freq // 10

        if mem.name.rstrip() != self._get_name(number):
            self._set_name(number, mem.name)

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _mem.txtone_type, _mem.txtone = self._encode_tone(*txtone)
        _mem.rxtone_type, _mem.rxtone = self._encode_tone(*rxtone)

        _mem.power = int(mem.power == self.POWER_LEVELS[1]
                         if mem.power else 1)
        _mem.wide = int(mem.mode == "FM")
        _mem.scan = int(mem.skip != "S")
        _set_bit(self._memobj.scan_bits, number, mem.skip != "S")

        RadioSettings(*mem.extra).apply_to(_mem)

    # ------------------------------------------------------------------
    # Settings

    def get_settings(self):
        _set = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")

        sql = int(_set.squelch)
        rs = MemSetting("settings.squelch", "Squelch",
                        RadioSettingValueList(
                            ["%i" % i for i in range(10)],
                            current_index=sql if sql < 10 else 0))
        rs.set_doc("Squelch level (0 is open)")
        basic.append(rs)

        rs = MemSetting("settings.beep", "Key beep",
                        RadioSettingValueBoolean(bool(_set.beep)))
        rs.set_doc("Beep when a key is pressed")
        basic.append(rs)

        return RadioSettings(basic)

    def set_settings(self, settings):
        settings.apply_to(self._memobj)
