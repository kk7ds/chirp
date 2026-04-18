# Wouxun KG Encrypted Protocol Common Base
#
# Copyright 2026 Chris Betz AF7PT
#
# Shared base class for Wouxun radios using the newer encrypted serial
# protocol (KG-Q10H, KG-935G, and future models in this family).
# This is separate from wouxun_common.py which covers the older
# unencrypted protocol (KG-UV6, etc.).
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

"""Shared base class for Wouxun radios with encrypted serial protocol."""

import struct
import time
import logging

from chirp import chirp_common, memmap, util

LOG = logging.getLogger(__name__)

# Command codes shared by the encrypted protocol family
CMD_RD = 0x82

# TODO: KG935GRadio should eventually inherit from WouxunKGBase.
# That migration will be a separate PR to avoid risk to the established
# driver. The 935G will need:
#   _cryptbyte = 0x57  (currently hardcoded in kg935g.py encrypt/decrypt)
#   _download_delay = 0
#   Its encrypt, decrypt, _checksum, _get_tone, _set_tone, and
#   _do_download methods match the base class implementations here.
#   The 935G _do_upload uses a 3-tuple config_map format
#   (map_address, write_size, write_count) which differs from Q10H's
#   4-tuple format, so _do_upload stays in the subclass.


def strxor(xora, xorb):
    """XOR two byte values and return as a single-byte bytes object."""
    return bytes([xora ^ xorb])


class WouxunKGBase(chirp_common.CloneModeRadio,
                   chirp_common.ExperimentalRadio):
    """Base class for Wouxun radios using the encrypted serial protocol.

    Subclasses MUST set:
        _cryptbyte   - the encryption key byte (e.g. 0x54 for Q10H)
    Subclasses MAY override:
        _record_start   - record header byte (default 0x7C)
        _download_delay - sleep between download blocks (default 0)
    """

    _cryptbyte = 0x00
    _record_start = 0x7C
    _download_delay = 0

    # --- Encryption ---

    def encrypt(self, data):
        """Encrypt data using chained XOR with _cryptbyte as the seed.

        Each output byte is XORed with the previous output byte,
        creating a chain where every byte depends on all prior bytes.
        """
        result = strxor(self._cryptbyte, data[0])
        for i in range(1, len(data)):
            result += strxor(result[i - 1], data[i])
        return result

    def decrypt(self, data):
        """Decrypt data by reversing the chained XOR."""
        result = b''
        for i in range(len(data) - 1, 0, -1):
            result += strxor(data[i], data[i - 1])
        result += strxor(data[0], self._cryptbyte)
        return result[::-1]

    # --- Checksum ---

    def _checksum(self, data):
        """Simple checksum: sum of bytes mod 256."""
        cs = 0
        for byte in data:
            cs += byte
        return cs % 256

    # --- Download ---

    def _do_download(self, start, end, blocksize):
        """Download a contiguous region of radio memory.

        Reads blocksize-byte chunks from start to end, calling
        _write_record / _read_record / _finish (which subclasses must
        provide) and returning the assembled memory image.
        """
        image = b""
        for i in range(start, end, blocksize):
            if self._download_delay:
                time.sleep(self._download_delay)
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

        LOG.debug("Set TX tone %04x RX tone %04x (mode %s)" %
                  (_mem.txtone, _mem.rxtone, mem.tmode))

    # --- Memory field helpers ---

    def _decode_duplex_offset(self, mem, _mem):
        """Decode duplex and offset from radio memory.

        Uses the 70 MHz threshold to distinguish +/- duplex from split.
        """
        if _mem.txfreq == 0xFFFFFFFF:
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        # > 70 MHz difference = too large for standard duplex offset
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

    def _decode_name(self, mem, _nam):
        """Decode channel name from radio memory."""
        for char in _nam.name:
            if char != 0:
                mem.name += chr(char)
        mem.name = mem.name.rstrip()
