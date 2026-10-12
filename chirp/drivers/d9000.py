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

"""Zastone ZT-D9000 / 即时通 (Jishitong) D9000.

The radio identifies itself as "HRK-2820H" and presents a 32 KiB clone image
over a 19200 8N1 serial link.

Memory map (reverse-engineered from the vendor programming tool, and verified
byte-for-byte against images read from the radio):

    0x0000 - 0x1FFF   radio settings / band table (not modelled here)
    0x2000 - 0x5FFF   512 channel records, 32 bytes each
    0x6000 - 0x7FFF   512 channel names, 16 bytes each (GBK)

Channel record:
    [0:3]   rx frequency, 3-byte big-endian, units of `fu` kHz
    [3]     0x00
    [4:6]   tx offset magnitude, signed 16-bit big-endian, units of `ou` kHz
    [6]     0x06 on every valid channel
    [7:9]   rx tone 0x1000 + hz*10, else 0x0000
    [9:11]  tx tone 0x5000 + hz*10, else 0x0000
    [11]    fu selector: 1 = 6.25 kHz units, 0 = 5 kHz units
    [12]    ou selector: 1 = 6.25 kHz units, 0 = 5 kHz units
    [13]    unknown (0x10 seen on two factory channels)
    [14]    offset direction: 0x00 simplex, 0x04 minus, 0x08 plus
    [15]    0x04 for every >= 300 MHz channel, 0x00 for VHF - exposed as FM/NFM
    [16]    0x01 = channel slot in use
    [17]    scan list membership; [25] scan/zone code
    [26:32] "------"

Name field: GBK (truncated on a character boundary to 12 bytes) padded with
0x20 up to 12 bytes and then four 0xFF bytes; an unused slot is 16 x 0xFF.

The frequency and offset fields each choose 5 kHz or 6.25 kHz units per
channel - the vendor tool picks whichever represents the value exactly.
"""

import logging

from chirp import chirp_common, directory, bitwise, errors, memmap

LOG = logging.getLogger(__name__)

# --------------------------------------------------------------- wire protocol
STX = 0x02
ETX = 0x03
TX_CONNECT = bytes([0x02, 0x23, 0xE0, 0xFB, 0x03])
TX_GETBAND = bytes([0x02, 0x23, 0xE1, 0xFA, 0x03])
TX_FINISH = bytes([0x02, 0x23, 0xE7, 0xF4, 0x03])
RX_ACK = bytes([0x02, 0x41, 0x43, 0x4B, 0x03])
RX_NAK = bytes([0x02, 0x4E, 0x41, 0x4B, 0x03])
RX_BAND = bytes([0x02, 0x23, 0xE2, 0xF9])
RD_CMD = bytes([0x02, 0x23, 0xE5, 0xF6])
WR_CMD = bytes([0x02, 0x23, 0xE6, 0xF5])

IMAGE_SIZE = 32768
BLOCK_LEN = 64
READ_BLOCKS = [(a, BLOCK_LEN) for a in range(0, IMAGE_SIZE, BLOCK_LEN)]
WRITE_BLOCKS = ([(12, 2)] +
                [(a, BLOCK_LEN) for a in range(1024, IMAGE_SIZE, BLOCK_LEN)])

PARAM_BASE = 0x2000
PARAM_LEN = 32
NAME_BASE = 0x6000
NAME_LEN = 16
NAME_BYTES = 12

MAGIC = b"HRK-2820H"

MEM_FORMAT = """
#seekto 0x2000;
struct {
  u24 freq;
  u8  unknown3;
  u16 offset;
  u8  unknown6;
  u16 rxtone;
  u16 txtone;
  u8  freq_unit;
  u8  offset_unit;
  u8  unknown13;
  u8  offset_dir;
  u8  band;
  u8  valid;
  u8  unknown17;
  u8  unknown18[8];
  u8  tail[6];
} memory[512];
"""


def _crc(parts):
    return (sum(parts) - 25) & 0xFF


def _read_frame(addr, length):
    return RD_CMD + bytes([(addr >> 8) & 0xFF, addr & 0xFF, length, ETX])


def _write_frame(addr, payload):
    body = [(addr >> 8) & 0xFF, addr & 0xFF, len(payload)] + list(payload)
    return WR_CMD + bytes(body) + bytes([_crc(body), ETX])


def _ctcss_rx(hz):
    return 0x1000 + int(round(hz * 10))


def _ctcss_tx(hz):
    return 0x5000 + int(round(hz * 10))


def _rx_tone_hz(word):
    """Return the CTCSS tone in Hz, or None if the word is not an rx CTCSS."""
    word = int(word)
    if 0x1000 < word < 0x2000:
        return (word - 0x1000) / 10.0
    return None


def _tx_tone_hz(word):
    word = int(word)
    if 0x5000 < word < 0x6000:
        return (word - 0x5000) / 10.0
    return None


@directory.register
class D9000Radio(chirp_common.CloneModeRadio):
    """Zastone ZT-D9000 / 即时通 (Jishitong) D9000"""

    VENDOR = "Zastone"
    MODEL = "ZT-D9000"
    BAUD_RATE = 19200
    NEEDS_COMPAT_SERIAL = False

    # CJK Unified Ideographs, since channel names are stored as GBK
    _CJK = "".join(chr(c) for c in range(0x4E00, 0x9FA6))

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver was written from the vendor programming software and "
            "verified against images read from a real radio.\n"
            "The radio reboots after a successful upload, so it will not "
            "answer for about ten seconds afterwards.\n"
            "Back up your radio (Radio -> Download) before uploading.")
        return rp

    @classmethod
    def match_model(cls, filedata, filename):
        return (len(filedata) == IMAGE_SIZE and
                filedata.startswith(MAGIC))

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = False
        rf.has_bank = False
        rf.has_ctone = True          # separate TX/RX tone fields
        rf.has_dtcs = False          # the DCS encoding was not identified
        rf.has_dtcs_polarity = False
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_tuning_step = False   # the format stores no per-channel step
        rf.has_cross = True
        rf.memory_bounds = (1, 512)
        rf.valid_bands = [(108000000, 174000000), (400000000, 520000000)]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "->Tone"]
        # "" only: no skip flag was identified in the channel record
        rf.valid_skips = [""]
        rf.valid_duplexes = ["", "+", "-"]
        rf.valid_tuning_steps = [5.0, 6.25]
        rf.valid_characters = chirp_common.CHARSET_ASCII + self._CJK
        rf.valid_name_length = NAME_BYTES
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # ------------------------------------------------------------ serial layer
    def _setup_pipe(self):
        for attr in ("dtr", "rts"):
            try:
                setattr(self.pipe, attr, True)
            except Exception:
                pass

    def _expect(self, want):
        got = self.pipe.read(len(want))
        if got == want:
            return True
        LOG.debug("Expected %s, got %s", want.hex(" "),
                  got.hex(" ") if got else "<timeout>")
        return False

    def _connect(self):
        self._setup_pipe()
        for _ in range(60):
            self.pipe.reset_input_buffer()
            self.pipe.write(TX_CONNECT)
            if self._expect(RX_ACK):
                return
        raise errors.RadioError(
            "Radio did not respond. Check the cable, and make sure no other "
            "programming software is holding the serial port.")

    def _get_band(self):
        self.pipe.write(TX_GETBAND)
        msg = self.pipe.read(21)
        if len(msg) < 4 or not msg.startswith(RX_BAND):
            raise errors.RadioError(
                "Unexpected response to the band query (%s)"
                % (msg.hex(" ") if msg else "<timeout>"))
        return msg

    def _finish(self):
        self.pipe.write(TX_FINISH)
        self._expect(RX_ACK)

    def _read_image(self, status=None):
        self._connect()
        self._get_band()
        img = bytearray(IMAGE_SIZE)
        for i, (addr, length) in enumerate(READ_BLOCKS):
            frame = _read_frame(addr, length)
            for _ in range(4):
                self.pipe.write(frame)
                got = self.pipe.read(length + 9)
                if len(got) != length + 9:
                    continue
                # The reply header is 02 23 E6 F5 (the same command byte as
                # the write frame), not an echo of the E5 F6 request; the
                # vendor tool checks only the length, the ETX and the CRC.
                if (got[0] != STX or got[1] != 0x23 or
                        got[6] != length or got[length + 8] != ETX):
                    continue
                body = list(got[4:7 + length])
                if got[7 + length] != _crc(body):
                    continue
                img[addr:addr + length] = got[7:7 + length]
                break
            else:
                raise errors.RadioError(
                    "Failed to read block at 0x%04X" % addr)
            if status and i % 32 == 0:
                status("Reading", i * 100 // len(READ_BLOCKS))
        self._finish()
        return bytes(img)

    def _write_image(self, img, status=None):
        self._connect()
        self._get_band()
        for i, (addr, length) in enumerate(WRITE_BLOCKS):
            frame = _write_frame(addr, img[addr:addr + length])
            for _ in range(6):
                self.pipe.write(frame)
                got = self.pipe.read(5)
                if got == RX_ACK:
                    break
                if got == RX_NAK:
                    LOG.debug("NAK at 0x%04X, resending", addr)
            else:
                raise errors.RadioError(
                    "Failed to write block at 0x%04X" % addr)
            if status and i % 32 == 0:
                status("Writing", i * 100 // len(WRITE_BLOCKS))
        self._finish()

    def sync_in(self):
        try:
            self._mmap = memmap.MemoryMapBytes(self._read_image())
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            self._write_image(self._mmap.get_packed())
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    # ------------------------------------------------------------------ names
    def _name_offset(self, number):
        return NAME_BASE + NAME_LEN * (number - 1)

    def _get_name(self, number):
        raw = self._mmap.get(self._name_offset(number), NAME_LEN)
        return raw.split(b"\xff")[0].rstrip(b"\x20").decode("gbk", "replace")

    def _set_name(self, number, name):
        # Truncate on a character boundary so a GBK double byte is never split
        out = ""
        for char in name:
            if len((out + char).encode("gbk", "replace")) > NAME_BYTES:
                break
            out += char
        raw = out.encode("gbk", "replace")
        raw += b"\x20" * (NAME_BYTES - len(raw))
        raw += b"\xff" * (NAME_LEN - NAME_BYTES)
        self._mmap.set(self._name_offset(number), raw)

    # --------------------------------------------------------------- memories
    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._memobj.memory[number - 1]
        if int(_mem.valid) != 0x01 or int(_mem.unknown6) != 0x06:
            mem.empty = True
            return mem

        freq_unit = 6.25 if int(_mem.freq_unit) else 5.0
        mem.freq = int(round(int(_mem.freq) * freq_unit * 1000))

        off_unit = 6.25 if int(_mem.offset_unit) else 5.0
        offset = int(_mem.offset)
        if offset >= 0x8000:
            offset -= 0x10000
        mem.duplex = {0x04: "-", 0x08: "+"}.get(int(_mem.offset_dir), "")
        if mem.duplex:
            mem.offset = int(round(abs(offset) * off_unit * 1000))
        else:
            mem.offset = 0

        # This byte is 0x04 for every >=300MHz channel and 0x00 for VHF in both
        # the radio's own codeplug and the vendor's factory image
        mem.mode = "FM" if int(_mem.band) else "NFM"

        rx_hz = _rx_tone_hz(_mem.rxtone)
        tx_hz = _tx_tone_hz(_mem.txtone)
        if rx_hz and tx_hz and rx_hz != tx_hz:
            mem.tmode = "Cross"
            mem.cross_mode = "Tone->Tone"
            mem.rtone = tx_hz
            mem.ctone = rx_hz
        elif rx_hz and tx_hz:
            mem.tmode = "TSQL"
            mem.rtone = tx_hz
            mem.ctone = rx_hz
        elif tx_hz:
            mem.tmode = "Tone"
            mem.rtone = tx_hz
        elif rx_hz:
            mem.tmode = "Cross"
            mem.cross_mode = "->Tone"
            mem.ctone = rx_hz
        else:
            mem.tmode = ""
        mem.dtcs = 23
        mem.rx_dtcs = 23
        mem.dtcs_polarity = "NN"
        mem.skip = ""
        mem.name = self._get_name(number)
        return mem

    def _set_ctcss(self, _mem, rx_hz, tx_hz):
        """Write the tone pair, keeping any value we do not understand."""
        if rx_hz is None:
            # Don't destroy an unrecognised (e.g. DCS) word on edit
            if not int(_mem.rxtone) or _rx_tone_hz(_mem.rxtone):
                _mem.rxtone = 0
        else:
            _mem.rxtone = _ctcss_rx(rx_hz)
        if tx_hz is None:
            if not int(_mem.txtone) or _tx_tone_hz(_mem.txtone):
                _mem.txtone = 0
        else:
            _mem.txtone = _ctcss_tx(tx_hz)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        if mem.empty:
            self._mmap.set(PARAM_BASE + PARAM_LEN * (mem.number - 1),
                           b"\x00" * PARAM_LEN)
            self._mmap.set(self._name_offset(mem.number), b"\xff" * NAME_LEN)
            return

        freq_khz = mem.freq // 1000
        if freq_khz % 5:
            freq_unit, freq_flag = 6.25, 1
        else:
            freq_unit, freq_flag = 5.0, 0
        _mem.freq = int(round(freq_khz / freq_unit))
        _mem.freq_unit = freq_flag
        _mem.unknown3 = 0x00
        _mem.unknown6 = 0x06
        _mem.unknown13 = 0x00
        _mem.unknown17 = 0x00
        _mem.valid = 0x01
        _mem.band = 0x04 if mem.mode == "FM" else 0x00

        if mem.duplex in ("-", "+") and mem.offset:
            off_khz = mem.offset // 1000
            if off_khz % 5:
                off_unit, off_flag = 6.25, 1
            else:
                off_unit, off_flag = 5.0, 0
            _mem.offset = int(round(off_khz / off_unit))
            _mem.offset_unit = off_flag
            _mem.offset_dir = 0x04 if mem.duplex == "-" else 0x08
        else:
            _mem.offset = 1000
            _mem.offset_unit = 0
            _mem.offset_dir = 0x00

        # CHIRP's tone semantics: rtone is the transmit tone, and in TSQL the
        # value used for both directions is ctone when the radio has_ctone.
        if mem.tmode == "Tone":
            self._set_ctcss(_mem, None, mem.rtone)
        elif mem.tmode == "TSQL":
            tone = mem.ctone if self.get_features().has_ctone else mem.rtone
            self._set_ctcss(_mem, tone, tone)
        elif mem.tmode == "Cross" and mem.cross_mode == "Tone->Tone":
            self._set_ctcss(_mem, mem.ctone, mem.rtone)
        elif mem.tmode == "Cross" and mem.cross_mode == "->Tone":
            self._set_ctcss(_mem, mem.ctone, None)
        else:
            self._set_ctcss(_mem, None, None)

        self._set_name(mem.number, mem.name)

    def get_raw_memory(self, number):
        return (repr(self._memobj.memory[number - 1]) +
                "\nname: %s\n" % self._mmap.get(self._name_offset(number),
                                                NAME_LEN).hex(" "))

    def validate_memory(self, mem):
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)
        if not mem.empty:
            used = len(mem.name.encode("gbk", "replace"))
            if used > NAME_BYTES:
                msgs.append(chirp_common.ValidationWarning(
                    "Channel name is %i GBK bytes; only %i fit and it will be "
                    "truncated" % (used, NAME_BYTES)))
        return msgs
