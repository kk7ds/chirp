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

LOG = logging.getLogger(__name__)

CMD_ID = 128    # 0x80
CMD_END = 129   # 0x81
CMD_RD = 130    # 0x82
CMD_WR = 131    # 0x83

MEM_VALID = 158

POWER_LEVELS = [
    chirp_common.PowerLevel("L", watts=0.5),
    chirp_common.PowerLevel("M", watts=4.5),
    chirp_common.PowerLevel("H", watts=5.5),
    chirp_common.PowerLevel("U", watts=6.0),
]

STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]

AIRBAND = (108000000, 136000000)

# Upload map: (radio_start, chirp_start, block_size, count)
#
# Each entry writes block_size * count bytes from CHIRP linear memory
# (at chirp_start) to the radio (at radio_start). Every group of 4
# entries covers one 0x400-byte region with blocks in reversed order
# (the rearrangement pattern).
#
# Radio addresses are in rearranged (radio) space; chirp addresses
# are in linear (CHIRP) space.
#
# CHIRP linear memory map (all offsets in rearranged/linear space):
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

config_map_Q10H = (
    # --- 0x0000-0x0400: Unknown | Freq limits | OEM info ---
    (0x0300, 0x0000, 64, 4),
    (0x0200, 0x0100, 64, 4),
    (0x0100, 0x0200, 64, 4),
    (0x0000, 0x0300, 64, 4),

    # --- 0x0400-0x0800: OEM info (tail) | Settings | VFO A/B | Ch memory ---
    (0x0700, 0x0400, 64, 4),
    (0x0600, 0x0500, 64, 4),
    (0x0500, 0x0600, 64, 4),
    (0x0400, 0x0700, 64, 4),

    # --- 0x0800-0x4400: Channel memory (continued) ---
    # 1000 channels x 16 bytes = 0x3E80 bytes, from 0x05E0 to 0x4460
    (0x0b00, 0x0800, 64, 4),
    (0x0a00, 0x0900, 64, 4),
    (0x0900, 0x0a00, 64, 4),
    (0x0800, 0x0b00, 64, 4),

    (0x0f00, 0x0c00, 64, 4),
    (0x0e00, 0x0d00, 64, 4),
    (0x0d00, 0x0e00, 64, 4),
    (0x0c00, 0x0f00, 64, 4),

    (0x1300, 0x1000, 64, 4),
    (0x1200, 0x1100, 64, 4),
    (0x1100, 0x1200, 64, 4),
    (0x1000, 0x1300, 64, 4),

    (0x1700, 0x1400, 64, 4),
    (0x1600, 0x1500, 64, 4),
    (0x1500, 0x1600, 64, 4),
    (0x1400, 0x1700, 64, 4),

    (0x1b00, 0x1800, 64, 4),
    (0x1a00, 0x1900, 64, 4),
    (0x1900, 0x1a00, 64, 4),
    (0x1800, 0x1b00, 64, 4),

    (0x1f00, 0x1c00, 64, 4),
    (0x1e00, 0x1d00, 64, 4),
    (0x1d00, 0x1e00, 64, 4),
    (0x1c00, 0x1f00, 64, 4),

    (0x2300, 0x2000, 64, 4),
    (0x2200, 0x2100, 64, 4),
    (0x2100, 0x2200, 64, 4),
    (0x2000, 0x2300, 64, 4),

    (0x2700, 0x2400, 64, 4),
    (0x2600, 0x2500, 64, 4),
    (0x2500, 0x2600, 64, 4),
    (0x2400, 0x2700, 64, 4),

    (0x2b00, 0x2800, 64, 4),
    (0x2a00, 0x2900, 64, 4),
    (0x2900, 0x2a00, 64, 4),
    (0x2800, 0x2b00, 64, 4),

    (0x2f00, 0x2c00, 64, 4),
    (0x2e00, 0x2d00, 64, 4),
    (0x2d00, 0x2e00, 64, 4),
    (0x2c00, 0x2f00, 64, 4),

    (0x3300, 0x3000, 64, 4),
    (0x3200, 0x3100, 64, 4),
    (0x3100, 0x3200, 64, 4),
    (0x3000, 0x3300, 64, 4),

    (0x3700, 0x3400, 64, 4),
    (0x3600, 0x3500, 64, 4),
    (0x3500, 0x3600, 64, 4),
    (0x3400, 0x3700, 64, 4),

    (0x3b00, 0x3800, 64, 4),
    (0x3a00, 0x3900, 64, 4),
    (0x3900, 0x3a00, 64, 4),
    (0x3800, 0x3b00, 64, 4),

    (0x3f00, 0x3c00, 64, 4),
    (0x3e00, 0x3d00, 64, 4),
    (0x3d00, 0x3e00, 64, 4),
    (0x3c00, 0x3f00, 64, 4),

    (0x4300, 0x4000, 64, 4),
    (0x4200, 0x4100, 64, 4),
    (0x4100, 0x4200, 64, 4),
    (0x4000, 0x4300, 64, 4),

    # --- 0x4400-0x4800: Ch memory (tail, ends at 0x4460) | Ch names ---
    (0x4700, 0x4400, 64, 4),
    (0x4600, 0x4500, 64, 4),
    (0x4500, 0x4600, 64, 4),
    (0x4400, 0x4700, 64, 4),

    # --- 0x4800-0x7000: Channel names (continued) ---
    # 1000 names x 12 bytes = 0x2EE0 bytes, from 0x4460 to 0x7340
    (0x4b00, 0x4800, 64, 4),
    (0x4a00, 0x4900, 64, 4),
    (0x4900, 0x4a00, 64, 4),
    (0x4800, 0x4b00, 64, 4),

    (0x4f00, 0x4c00, 64, 4),
    (0x4e00, 0x4d00, 64, 4),
    (0x4d00, 0x4e00, 64, 4),
    (0x4c00, 0x4f00, 64, 4),

    (0x5300, 0x5000, 64, 4),
    (0x5200, 0x5100, 64, 4),
    (0x5100, 0x5200, 64, 4),
    (0x5000, 0x5300, 64, 4),

    (0x5700, 0x5400, 64, 4),
    (0x5600, 0x5500, 64, 4),
    (0x5500, 0x5600, 64, 4),
    (0x5400, 0x5700, 64, 4),

    (0x5b00, 0x5800, 64, 4),
    (0x5a00, 0x5900, 64, 4),
    (0x5900, 0x5a00, 64, 4),
    (0x5800, 0x5b00, 64, 4),

    (0x5f00, 0x5c00, 64, 4),
    (0x5e00, 0x5d00, 64, 4),
    (0x5d00, 0x5e00, 64, 4),
    (0x5c00, 0x5f00, 64, 4),

    (0x6300, 0x6000, 64, 4),
    (0x6200, 0x6100, 64, 4),
    (0x6100, 0x6200, 64, 4),
    (0x6000, 0x6300, 64, 4),

    (0x6700, 0x6400, 64, 4),
    (0x6600, 0x6500, 64, 4),
    (0x6500, 0x6600, 64, 4),
    (0x6400, 0x6700, 64, 4),

    (0x6b00, 0x6800, 64, 4),
    (0x6a00, 0x6900, 64, 4),
    (0x6900, 0x6a00, 64, 4),
    (0x6800, 0x6b00, 64, 4),

    (0x6f00, 0x6c00, 64, 4),
    (0x6e00, 0x6d00, 64, 4),
    (0x6d00, 0x6e00, 64, 4),
    (0x6c00, 0x6f00, 64, 4),

    # --- 0x7000-0x7400: Ch names (tail, ends at 0x7340) | Valid flags ---
    (0x7300, 0x7000, 64, 4),
    (0x7200, 0x7100, 64, 4),
    (0x7100, 0x7200, 64, 4),
    (0x7000, 0x7300, 64, 4),

    # --- 0x7400-0x7800: Valid flags (tail) | Unknown | Scan groups |
    #     VFO scan ranges | Unknown ---
    (0x7700, 0x7400, 64, 4),
    (0x7600, 0x7500, 64, 4),
    (0x7500, 0x7600, 64, 4),
    (0x7400, 0x7700, 64, 4),

    # --- 0x7800-0x7C00: Unknown | FM presets | Call IDs | Call names ---
    (0x7b00, 0x7800, 64, 4),
    (0x7a00, 0x7900, 64, 4),
    (0x7900, 0x7a00, 64, 4),
    (0x7800, 0x7b00, 64, 4),

    # --- 0x7C00-0x8000: Call names (continued to end of memory) ---
    (0x7f00, 0x7c00, 64, 4),
    (0x7e00, 0x7d00, 64, 4),
    (0x7d00, 0x7e00, 64, 4),
    (0x7c00, 0x7f00, 64, 4),
)

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
class KGQ10HRadio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):

    """Wouxun KG-Q10H"""
    VENDOR = "Wouxun"
    MODEL = "KG-Q10H"
    BAUD_RATE = 115200
    POWER_LEVELS = POWER_LEVELS
    _record_start = 0x7C
    _model = b"KG-Q10H"
    _cryptbyte = 0x54
    config_map = config_map_Q10H

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

    def _do_download(self, start, end, blocksize):
        image = b""
        for i in range(start, end, blocksize):
            time.sleep(0.005)
            req = struct.pack('>HB', i, blocksize)
            self._write_record(CMD_RD, req)
            cs_error, resp = self._read_record()
            if cs_error:
                LOG.debug(util.hexprint(resp))
                raise Exception("Checksum error on read")
            image += resp[2:]
            if self.status_fn:
                status = chirp_common.Status()
                status.cur = i
                status.max = end
                status.msg = "Cloning from radio"
                self.status_fn(status)
        self._finish()
        return memmap.MemoryMapBytes(image)

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
        cfgmap = self.config_map

        for radio_start, chirp_start, blocksize, count in cfgmap:
            end = chirp_start + (blocksize * count)
            radio_addr = radio_start

            for addr in range(chirp_start, end, blocksize):
                req = struct.pack('>H', radio_addr)
                chunk = self.get_mmap()[addr:addr + blocksize]
                self._write_record(CMD_WR, req + chunk)
                cserr, ack = self._read_record()
                j = struct.unpack('>H', ack)[0]
                if cserr or j != radio_addr:
                    raise Exception(
                        "Radio did not ack block %i" % radio_addr)
                radio_addr += blocksize
                if self.status_fn:
                    status = chirp_common.Status()
                    status.cur = addr
                    status.max = 0x8000
                    status.msg = "Cloning to radio"
                    self.status_fn(status)

        self._finish()

    # --- Serial protocol ---

    def strxor(self, xora, xorb):
        return bytes([xora ^ xorb])

    def encrypt(self, data):
        result = self.strxor(self._cryptbyte, data[0])
        for i in range(1, len(data)):
            result += self.strxor(result[i - 1], data[i])
        return result

    def decrypt(self, data):
        result = b''
        for i in range(len(data) - 1, 0, -1):
            result += self.strxor(data[i], data[i - 1])
        result += self.strxor(data[0], self._cryptbyte)
        return result[::-1]

    def _checksum(self, data):
        """Simple checksum: sum of bytes mod 256."""
        cs = 0
        for byte in data:
            cs += byte
        return cs % 256

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
        _rcs = self.strxor(self.pipe.read(1)[0], _rcs_xor)[0]
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
        # Encrypted finish/reboot command
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

    # --- Tone handling ---

    def _get_tone(self, _mem, mem):
        """Decode TX/RX tones from radio memory into CHIRP memory.

        Wouxun radios store separate TX/RX tones in every channel.
        We detect simple modes (Tone, TSQL, DTCS) and only fall
        back to Cross when the configuration doesn't fit.

        Tone encoding:
          0xFFFF or 0x0000 = no tone
          0x8000 flag = CTCSS tone (value / 10.0 Hz)
          0x4000 flag = DCS code (octal in lower bits)
          0x2000 flag = inverted DCS polarity
        """
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x2000) and "R" or "N"
            return code, pol

        # Decode TX tone
        tpol = False
        if _mem.txtone != 0xFFFF and (_mem.txtone & 0x4000) == 0x4000:
            tcode, tpol = _get_dcs(_mem.txtone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.txtone != 0xFFFF and _mem.txtone != 0x0:
            mem.rtone = (_mem.txtone & 0x7FFF) / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        # Decode RX tone
        rpol = False
        if _mem.rxtone != 0xFFFF and (_mem.rxtone & 0x4000) == 0x4000:
            rcode, rpol = _get_dcs(_mem.rxtone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rxtone != 0xFFFF and _mem.rxtone != 0x0:
            mem.ctone = (_mem.rxtone & 0x7FFF) / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        # Detect simple modes before falling back to Cross
        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif (txmode == rxmode == "Tone" and mem.rtone == mem.ctone):
            mem.tmode = "TSQL"
        elif (txmode == rxmode == "DTCS"
              and mem.dtcs == mem.rx_dtcs):
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "%s%s" % (tpol or "N", rpol or "N")

    def _set_tone(self, mem, _mem):
        """Encode CHIRP tone settings into radio memory format."""
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) | 0x4000
            if pol == "R":
                val |= 0x2000
            return val

        rxtone = txtone = 0x0000

        if mem.tmode == "Tone":
            txtone = int(mem.rtone * 10) | 0x8000
        elif mem.tmode == "TSQL":
            rxtone = txtone = int(mem.ctone * 10) | 0x8000
        elif mem.tmode == "DTCS":
            txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rxtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                txtone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                txtone = int(mem.rtone * 10) | 0x8000
            if rx_mode == "DTCS":
                rxtone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rxtone = int(mem.ctone * 10) | 0x8000

        _mem.rxtone = rxtone
        _mem.txtone = txtone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (mem.tmode, _mem.txtone, mem.tmode, _mem.rxtone))

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
        if _mem.txfreq == 0xFFFFFFFF:
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        # name (12 chars)
        for char in _nam.name:
            if char != 0:
                mem.name += chr(char)
        mem.name = mem.name.rstrip()

        # tones
        self._get_tone(_mem, mem)

        # skip
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

        # skip
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

        # defaults for extras (Phase 2 will handle these properly)
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
