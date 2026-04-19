#
# Copyright 2026 Dan Smith (chirp@f.danplanet.com)
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


class KenwoodToneModel:
    """
    Common tone handling model for Kenwood (and knock-off) radios.

    This provides generalized handling for a tone/dcs encoding scheme that
    originated on Kenwood radios in the 1990s and has been widely copied by
    other radio manufacturers.

    Typically CTCSS tones are stored as the frequency in Hertz, multiplied by
    10, and sometimes with a flag bit set (tone_flag).

    DCS codes are stored either as octal or decimal (dcs_enc_base), with one
    or more flag bits (dcs_base) set to indicate that it's DCS. Reverse
    polarity is indicated by another flag bit (pol_mask). Finally, a completely
    disabled tone/code field is often indicated by 0x0000 or 0xFFFF
    (tone_init).

    Note that this requires your radio's memory structure to have u16 fields
    named exactly "rxtone" and "txtone".

    :param dcs_base: Base value for DCS tones (e.g., 0x4000, 0x2800, 0x8000)
    :param pol_mask: Bitmask for polarity (e.g., 0x2000, 0x8000, 0x4000)
    :param tone_init: Initial value for uninitialized tones (0x0000, 0xFFFF)
    :param tone_flag: Flag to indicate a CTCSS tone (0x0000 or 0x8000)
    :param dcs_enc_base: Numerical base for DCS encoding (8 or 10)
    """
    def __init__(self, dcs_base, pol_mask, tone_init=0x0000, tone_flag=0x8000,
                 dcs_enc_base=8):
        self.dcs_base = dcs_base
        self.pol_mask = pol_mask
        self.tone_init = tone_init
        self.tone_flag = tone_flag
        assert dcs_enc_base in (8, 10), "DCS encoding base must be 8 or 10"
        self.dcs_enc_base = dcs_enc_base

    def _get_tone_val(self, tone_val):
        """
        Convert a binary tone value to a tuple of (code, polarity).

        :param tone_val: Binary tone value from radio memory
        :return: Tuple of (code, polarity) or (None, None) if no tone
        """
        if tone_val == 0xFFFF or tone_val == 0x0000:
            return None, None

        if (tone_val & self.dcs_base) == self.dcs_base:
            if self.dcs_enc_base == 8:
                code = int("%03o" % (tone_val & 0x07FF))
            elif self.dcs_enc_base == 10:
                code = int("%03i" % (tone_val & 0x07FF))
            pol = (tone_val & self.pol_mask) and "R" or "N"
            return code, pol

        return (tone_val & 0x7fff) / 10.0, None

    def _set_tone_val(self, code, pol):
        """
        Convert a tone code and polarity to a binary value.

        :param code: Tone code (integer for DCS, float for CTCSS)
        :param pol: Polarity string ("N" or "R") or None for CTCSS
        :return: Binary tone value
        """
        if code is None:
            return 0x0000

        if pol is not None:
            val = int("%i" % code, self.dcs_enc_base) | self.dcs_base
            if pol == "R":
                val += self.pol_mask
            return val

        return int(code * 10) + self.tone_flag

    def set_tone(self, mem, _mem):
        """
        Set tone values for a memory channel based on UI settings.

        :param mem: Memory channel object from UI
        :param _mem: Radio memory object
        """
        rx_mode = tx_mode = None
        rxtone = txtone = self.tone_init

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            txtone = self._set_tone_val(mem.rtone, None)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rxtone = txtone = self._set_tone_val(mem.ctone, None)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            txtone = self._set_tone_val(mem.dtcs, mem.dtcs_polarity[0])
            rxtone = self._set_tone_val(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                txtone = self._set_tone_val(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                txtone = self._set_tone_val(mem.rtone, None)
            if rx_mode == "DTCS":
                rxtone = self._set_tone_val(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rxtone = self._set_tone_val(mem.ctone, None)

        _mem.rxtone = rxtone
        _mem.txtone = txtone

    def get_tone(self, _mem, mem):
        """
        Get tone settings from radio memory into UI memory object.

        :param _mem: Radio memory object
        :param mem: Memory channel object for UI
        """
        txtone = _mem.txtone
        tcode, tpol = self._get_tone_val(txtone)
        if tcode is not None:
            if tpol is not None:
                mem.dtcs = tcode
                txmode = "DTCS"
            else:
                mem.rtone = tcode
                txmode = "Tone"
        else:
            txmode = ""

        rxtone = _mem.rxtone
        rcode, rpol = self._get_tone_val(rxtone)
        if rcode is not None:
            if rpol is not None:
                mem.rx_dtcs = rcode
                rxmode = "DTCS"
            else:
                mem.ctone = rcode
                rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)
        else:
            mem.tmode = ""

        mem.dtcs_polarity = "%s%s" % (tpol or "N", rpol or "N")


def parse_qtdqt(selcall):
    """Parse a standard "selcall" mode string.

    This parses strings like 'D023N', 'D032R' and '103.5' into parts for
    use with CHIRP.

    :param selcall: A string like '', '103.5', or 'D023N'
    :returns: (mode, val, pol) where:
     - mode is one of: '', 'Tone', 'DTCS'
     - val is the integer DTCS code or float tone frequency (ex: 023, 103.5)
     - pol is the DTCS polarity ('N' or 'R') or '' for tone/CSQ
    """
    selcall = selcall or ''
    selcall = selcall.upper().strip()
    if selcall.startswith('D'):
        try:
            val = int(selcall[1:4])
            pol = selcall[4]
            return 'DTCS', val, pol
        except (ValueError, IndexError):
            raise ValueError(
                'DCS value must be in the form "D023N"')
    elif selcall:
        try:
            val = float(selcall)
            return 'Tone', val, ''
        except ValueError:
            raise ValueError(
                'Tone value must be in the form "103.5"')
    else:
        return '', None, None


def format_qtdqt(mode, val, pol):
    """Format a CHIRP tone spec into a standard 'selcall' string.

    This takes a standard CHIRP (mode, val, pol) tuple and returns a string
    like is used in several manufacturer's software (i.e. 'D023N', '103.5').

    :param mode: Either '', 'Tone', or 'DTCS'
    :param val: A float one frequency (103.5) or integer DTCS code (023)
    :param pol: A DTCS polarity ('N' or 'R')
    :returns: A selcall string like '103.5' or 'D023N'
    """
    if mode == 'DTCS':
        return 'D%03.3i%s' % (val, pol)
    elif mode == 'Tone':
        return '%3.1f' % val
    else:
        return ''
