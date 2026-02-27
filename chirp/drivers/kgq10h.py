# Wouxun KG-Q10H Driver
#
# Copyright 2026 Chris Betz AF7PT
#
# Based on the work of Mel Terechenok (KG-Q10H beta driver),
# Pavel Milanes CO7WT <pavelmc@gmail.com> (KG-935G driver),
# and Krystian Struzik <toner_82@tlen.pl> who figured out the
# encryption used in Wouxun radios.
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

"""Wouxun KG-Q10H radio management module"""

import struct
import time
import logging

from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.drivers.wouxun_kg_common import WouxunKGBase, strxor

LOG = logging.getLogger(__name__)

CMD_ID = 0x80
CMD_END = 0x81
CMD_WR = 0x83

MEM_VALID = 158

POWER_LEVELS = [
    chirp_common.PowerLevel("L", watts=0.5),
    chirp_common.PowerLevel("M", watts=4.5),
    chirp_common.PowerLevel("H", watts=5.5),
    chirp_common.PowerLevel("U", watts=6.0),
]

STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]

AIRBAND = (108000000, 136000000)

# CHIRP linear memory map (all offsets in linear space):
#   0x0000-0x02C2  Unknown / unused
#   0x02C2-0x0340  Frequency limits (RX/TX band edges)
#   0x0340-0x0440  OEM info (model, firmware, date, lock flag)
#   0x0440-0x0540  Settings (squelch, VOX, timeout, keys, display, etc.)
#   0x0540-0x05A0  VFO A (6 sub-bands, 16 bytes each)
#   0x05A0-0x05C0  VFO B (2 sub-bands, 16 bytes each)
#   0x05C0-0x05E0  Unknown
#   0x05E0-0x4460  Channel memory (1000 channels x 16 bytes)
#   0x4460-0x7340  Channel names (1000 channels x 12 bytes)
#   0x7340-0x7728  Channel valid flags (1000 bytes)
#   0x7728-0x7740  Unknown
#   0x7740-0x77E0  Scan groups (10 groups: start/end addrs + 12-char names)
#   0x77E0-0x77E8  VFO scan ranges (A + B start/end freqs)
#   0x77E8-0x78B0  Unknown
#   0x78B0-0x78E0  FM radio presets (20 x 2 bytes)
#   0x78E0-0x7B38  Call IDs (100 x 6 bytes)
#   0x7B38-0x7B40  Unknown
#   0x7B40-0x8000  Call names (100 x 12 bytes)

MEM_FORMAT = """
#seekto 0x05e0;
struct {
    ul32    rxfreq;
    ul32    txfreq;
    ul16    rxtone;
    ul16    txtone;
    u8      scrambler:4,
            am_mode:2,
            power:2;
    u8      unknown3:1,
            send_loc:1,
            scan_add:1,
            favorite:1,
            compander:1,
            mute_mode:2,
            iswide:1;
    u8      call_group;
    u8      unknown6;
} memory[1000];

#seekto 0x4460;
struct {
    u8      name[12];
} names[1000];

#seekto 0x7340;
u8 valid[1000];
"""


def _addr_rearrange(addr):
    """Swap 256-byte block order within each 1024-byte region.

    The KG-Q10H stores data with 256-byte blocks in reverse order
    within each 1024-byte region. For example, radio addresses
    0x0300, 0x0200, 0x0100, 0x0000 map to linear addresses
    0x0000, 0x0100, 0x0200, 0x0300.

    This transform is its own inverse: applying it twice returns
    the original address.
    """
    region_base = addr & 0xFC00
    block_offset = addr & 0x00FF
    block_index = (addr >> 8) & 0x03
    new_block = 3 - block_index
    return region_base | (new_block << 8) | block_offset


@directory.register
class KGQ10HRadio(WouxunKGBase):

    """Wouxun KG-Q10H"""
    VENDOR = "Wouxun"
    MODEL = "KG-Q10H"
    BAUD_RATE = 115200
    POWER_LEVELS = POWER_LEVELS
    _record_start = 0x7C
    _model = b"KG-Q10H"
    _cryptbyte = 0x54
    _download_delay = 0.005

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = self._download()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            self._upload()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)

    def _download(self):
        """Download memory from the radio and rearrange to linear order."""
        try:
            self._identify()
            raw_image = self._do_download(0, 0x8000, 64)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Unknown error during download process')
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)

        # Rearrange from radio block order to linear CHIRP order
        raw_bytes = raw_image.get_packed()
        image = bytearray(len(raw_bytes))
        for addr in range(len(raw_bytes)):
            image[_addr_rearrange(addr)] = raw_bytes[addr]
        return memmap.MemoryMapBytes(bytes(image))

    def _upload(self):
        """Upload memory to the radio with address rearrangement."""
        try:
            self._identify()
            self._do_upload()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)

    def _do_upload(self):
        blocksize = 64
        for addr in range(0, 0x8000, blocksize):
            radio_addr = _addr_rearrange(addr)
            req = struct.pack('>H', radio_addr)
            chunk = self.get_mmap()[addr:addr + blocksize]
            self._write_record(CMD_WR, req + chunk)
            cserr, ack = self._read_record()
            ack_addr = struct.unpack('>H', ack)[0]
            if cserr or ack_addr != radio_addr:
                raise Exception(
                    "Radio did not ack block %i" % radio_addr)
            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr
                status.max = 0x8000
                status.msg = "Cloning to radio"
                self.status_fn(status)

        self._finish()

    # --- Serial protocol ---

    def _checksum_adjust(self, byte_val):
        """Compute the Q10H checksum adjustment.

        The Q10H applies a small offset to the checksum based on the
        4th byte (index 3) of the combined header[1:]+payload data.
        For read/write commands with a 3-byte payload, this is the
        first byte of the payload (the address high byte).
        """
        adj = (byte_val & 0x0F) % 4
        if adj == 0:
            return 3
        elif adj == 1:
            return 1
        elif adj == 2:
            return -1
        else:
            return -3

    def _write_record(self, cmd, payload=b''):
        """Build, encrypt, and send a framed record to the radio."""
        _packet = struct.pack('BBBB', self._record_start, cmd, 0xFF,
                              len(payload))
        # Checksum covers header bytes [1:] + unencrypted payload
        # Adjustment is based on byte [3] of (header[1:] + payload)
        cs_data = _packet[1:] + payload
        cs = self._checksum(cs_data)
        cs += self._checksum_adjust(cs_data[3] if len(cs_data) > 3
                                    else 0)
        checksum = bytes([cs & 0xFF])
        _packet += self.encrypt(payload + checksum)
        LOG.debug("Sent:\n%s" % util.hexprint(_packet))
        self.pipe.write(_packet)

    def _read_record(self):
        """Read and decrypt a record from the radio.

        Returns (checksum_error, decrypted_payload).
        """
        _header = self.pipe.read(4)
        if len(_header) != 4:
            raise errors.RadioError(
                'Radio did not respond')
        _length = struct.unpack('xxxB', _header)[0]
        _packet = self.pipe.read(_length)
        _rcs_xor = _packet[-1]
        _packet = self.decrypt(_packet)
        _cs = self._checksum(_header[1:])
        _cs += self._checksum(_packet)
        _cs += self._checksum_adjust(_packet[0])
        _cs &= 0xFF
        _rcs = strxor(self.pipe.read(1)[0], _rcs_xor)[0]
        return (_rcs != _cs, _packet)

    def _identify(self):
        """Send identification sequence and verify radio model.

        The Q10H CPS sends the same 8-byte read command three times
        to establish communication. The radio may respond to each one.
        We read the first response to validate, then drain any
        remaining data from the buffer. Model string is at bytes
        46-53 of the decrypted payload.
        """
        # Flush any stale data in the serial buffer
        self.pipe.reset_input_buffer()
        time.sleep(0.1)

        # Pre-encrypted read command for address 0x0000, length 3
        ident = struct.pack(
            'BBBBBBBB', 0x7c, 0x82, 0xff, 0x03,
            0x54, 0x14, 0x54, 0x53)
        for _i in range(3):
            self.pipe.write(ident)
            time.sleep(0.05)

        # Read and validate the first response
        _chksum_err, _resp = self._read_record()
        _radio_id = _resp[46:53]
        LOG.debug("Radio identified as %s" % _radio_id)
        if _chksum_err:
            raise errors.RadioError("Checksum error on identify")

        # Drain any remaining ident responses from the buffer
        time.sleep(0.1)
        self.pipe.reset_input_buffer()

        if _radio_id != self._model:
            self._finish()
            raise errors.RadioError(
                "Radio identified as %s, expected %s"
                % (_radio_id.decode('utf-8', errors='replace'),
                   self._model.decode('utf-8')))

    def _finish(self):
        """Send the finish/reboot command to end communication."""
        # Pre-encrypted finish/reboot command
        finish = struct.pack('BBBBB', 0x7c, 0x81, 0xff, 0x00, 0xd7)
        self.pipe.write(finish)

    # --- Radio features ---

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = False
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->Tone",
            "->DTCS",
            "DTCS->DTCS",
        ]
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 12
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_bands = [(50000000, 54997500),
                          (108000000, 174997500),
                          (222000000, 225997500),
                          (320000000, 479997500),
                          (714000000, 999997500)]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.memory_bounds = (1, 999)
        rf.valid_tuning_steps = STEPS
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            'This driver is experimental. USE AT YOUR OWN RISK.\n'
            '\n'
            'Please save a copy of the image from your radio with CHIRP '
            'before modifying any values.\n'
            '\n'
            'Please keep a copy of your memories with the original Wouxun '
            'CPS software if you treasure them, as this driver is new and '
            'may contain bugs.\n'
        )
        return rp

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    @classmethod
    def match_model(cls, filedata, filename):
        return False

    # --- Memory read/write ---

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number

        _valid = self._memobj.valid[number]
        if _valid != MEM_VALID:
            mem.empty = True
            return mem

        mem.empty = False

        # frequency
        mem.freq = int(_mem.rxfreq) * 10

        # duplex and offset
        self._decode_duplex_offset(mem, _mem)

        # name
        self._decode_name(mem, _nam)

        # tones
        self._get_tone(_mem, mem)

        # skip (scan_add=1 means scan enabled, i.e. not skipped)
        mem.skip = "" if bool(_mem.scan_add) else "S"

        # power (4 levels, clamp to valid range)
        pwr = int(_mem.power) & 0x03
        mem.power = self.POWER_LEVELS[pwr]

        # mode
        if _mem.am_mode:
            mem.mode = "AM"
        elif _mem.iswide:
            mem.mode = "FM"
        else:
            mem.mode = "NFM"

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _nam = self._memobj.names[mem.number]

        if mem.empty:
            _mem.set_raw(b"\x00" * (_mem.size() // 8))
            _nam.set_raw(b"\x00" * (_nam.size() // 8))
            self._memobj.valid[mem.number] = 0
            return

        # frequency
        _mem.rxfreq = int(mem.freq / 10)

        # duplex and offset
        if mem.duplex == "off":
            _mem.txfreq = 0xFFFFFFFF
        elif mem.duplex == "split":
            _mem.txfreq = int(mem.offset / 10)
        elif mem.duplex == "+":
            _mem.txfreq = int(mem.freq / 10) + int(mem.offset / 10)
        elif mem.duplex == "-":
            _mem.txfreq = int(mem.freq / 10) - int(mem.offset / 10)
        else:
            _mem.txfreq = int(mem.freq / 10)

        # skip (scan_add=1 means scan enabled, i.e. not skipped)
        _mem.scan_add = int(mem.skip != "S")

        # mode
        if mem.mode == "AM":
            _mem.am_mode = 1
            _mem.iswide = 1
        elif mem.mode == "FM":
            _mem.am_mode = 0
            _mem.iswide = 1
        else:
            _mem.am_mode = 0
            _mem.iswide = 0

        # tones
        self._set_tone(mem, _mem)

        # power
        if mem.power:
            _mem.power = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        # clear optional fields
        _mem.scrambler = 0
        _mem.compander = 0
        _mem.mute_mode = 0

        # name (12 chars, zero-padded)
        for i in range(12):
            if i < len(mem.name) and mem.name[i]:
                _nam.name[i] = ord(mem.name[i])
            else:
                _nam.name[i] = 0x0

        self._memobj.valid[mem.number] = MEM_VALID

    def validate_memory(self, mem):
        msgs = []
        if (chirp_common.in_range(mem.freq, [AIRBAND])
                and mem.mode != 'AM'):
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range requires AM mode')))
        if (not chirp_common.in_range(mem.freq, [AIRBAND])
                and mem.mode == 'AM'):
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range must not be AM mode')))
        return msgs + super().validate_memory(mem)
