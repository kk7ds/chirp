# Copyright 2026
#
# EXPERIMENTAL / reverse-engineered driver for the Retevis RT18.
#
# The clone protocol and 16-channel memory layout were derived from
# passive USB capture analysis (Wireshark + USBPcap) of the vendor's
# Windows CPS talking to a real RT18 over its programming cable. Treat
# with caution:
#
#   * Channel memory (frequency, tones, power, narrow/wide, scan add,
#     busy lock, scramble, compander, spec code) is expected to read
#     correctly -- the block-read protocol and the 16-channel/16-byte
#     layout at 0x0010-0x0110 were directly confirmed against captured
#     traffic. Reprogramming squelch tone/DCS code, wide/narrowband,
#     and squelch level was tested end-to-end on a real unit (CHIRP
#     write, then read back with the vendor CPS) and matched.
#   * The rest of the "Other"/settings screen (timeout timer, VOX,
#     beep, scan mode, battery save, etc.) is INHERITED UNCHANGED from
#     the Radtel T18 base class and has NOT been individually tested
#     on a real RT18 yet -- the exact offsets may differ. Don't trust
#     those specific values until confirmed.
#   * The 6-digit programming password (separate "Password" settings
#     group below) IS confirmed against a real "set password" capture
#     (rt18_write_password_to_radio.pcapng) and was also tested
#     end-to-end on a real unit (CHIRP write, then read back with the
#     vendor CPS) -- see _PASSWORD_ADDR.
#   * ALWAYS do a "read from radio" and save the image before ever
#     attempting a write, so there is a known-good backup.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import time

from chirp import chirp_common, directory, errors
from chirp.drivers import radtel_t18 as t18
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueString

# Offset/length of the 6-digit programming password inside the memory
# image, confirmed against rt18_write_password_to_radio.pcapng: writing
# a full image with the password set to "123456" sends a block-write of
# `01 02 03 04 05 06 00 ff` at address 0x03B0 -- one raw byte per digit
# (not ASCII), followed by 2 bytes that stay `00 ff` whether or not a
# password is set (unknown/reserved). All-0xFF digits means "no
# password", matching what the extra 0x05 handshake step reads back.
_PASSWORD_ADDR = 0x03B0
_PASSWORD_LEN = 6
_PASSWORD_BLANK = b"\xff" * _PASSWORD_LEN


@directory.register
class RT18Radio(t18.T18Radio):
    """Retevis RT18"""

    VENDOR = "Retevis"
    MODEL = "RT18"

    BLOCK_SIZE = 0x08
    CMD_EXIT = b"b"
    # Confirmed by capture: no per-block ACK after a block *read*
    # (unlike most other T18 siblings, which do ACK_BLOCK = True).
    ACK_BLOCK = False

    # Handshake magic, captured verbatim from a real "Read from radio"
    # session: b"\x02" + this string.
    _magic = b"JSOGRAP"

    # NOTE: unlike most T18 siblings (which check for a text string like
    # b"SMP558..."), the 8-byte ident this radio returns does not look
    # like a text fingerprint. Originally captured as:
    #   06 03 e8 08 ff ff ff ff
    # ...but a real unit (see git history) responded instead with
    #   06 00 00 00 00 00 00 00
    # confirming this is NOT a fixed brand string -- only the leading
    # 0x06 (which is just CMD_ACK, echoed as the first byte of the
    # ident reply) is consistent; the remaining bytes vary with radio
    # state (e.g. programmed vs. blank). So only match on that.
    _fingerprint = [b"\x06"]

    _upper = 16
    _mem_params = _upper
    _frs = _frs16 = _murs = _pmr = _gmrs = False
    _echo = False
    _reserved = False

    _ranges = [
        (0x0000, 0x03F0),
    ]
    _memsize = 0x03F0

    VALID_BANDS = [(400000000, 470000000)]

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=2.00)]

    # 6 raw digit bytes read via the extra 0x05 step during handshake,
    # or b"\xff\xff\xff\xff\xff\xff" when no password is set. This is
    # also mirrored at 0x03B0 inside the main memory image -- writing
    # a full image back (as do_upload always does) rewrites it too.
    _password = b""

    def _enter_programming_mode(self):
        """Identical handshake to the Radtel T18 family (magic + ident
        + ack), plus one extra step this RT18 firmware does before the
        normal block read/write loop: a single 0x05 command that
        returns a 6-byte "password" block (raw digit bytes, or 0xFF x6
        when no password is set), acknowledged the same way as a
        channel block."""
        # Both captures (read and write sessions) show the vendor CPS
        # asserting DTR then RTS on the cable, then waiting ~120-130ms
        # before writing the magic string -- CHIRP's generic serial-open
        # asserts both lines but writes the magic immediately, which can
        # race the radio's cable/UART chip if the port was very recently
        # opened/closed (observed as an intermittent "No response from
        # radio" on repeated clone attempts). Mirror the vendor's delay.
        time.sleep(0.15)
        t18.T18Radio._enter_programming_mode(self)

        serial = self.pipe
        try:
            self.pipe.log("RT18 password step")
            serial.write(b"\x05")
            if self._echo:
                serial.read(1)  # Chew the echo
            self._password = serial.read(6)
            serial.write(t18.CMD_ACK)
            if self._echo:
                serial.read(1)  # Chew the echo
            ack = serial.read(1)
        except Exception:
            raise errors.RadioError(
                "Error communicating with radio (password step)")

        if ack != t18.CMD_ACK:
            raise errors.RadioError("Bad ACK after password step")

    def _rt18_get_password(self):
        raw = self._mmap.get(_PASSWORD_ADDR, _PASSWORD_LEN)
        if raw == _PASSWORD_BLANK:
            return ""
        return "".join(str(b) for b in raw if b != 0xFF)

    def _rt18_apply_password(self, setting):
        digits = [int(c) for c in str(setting.value).strip()]
        raw = bytes(digits) + _PASSWORD_BLANK[len(digits):]
        self._mmap.set(_PASSWORD_ADDR, raw)

    def get_settings(self):
        top = t18.T18Radio.get_settings(self)

        # The vendor CPS for the RT18 has no "Voice prompts" control --
        # unlike its T18 siblings, this radio doesn't seem to have voice
        # prompts at all. Drop the setting the base class adds
        # unconditionally so we don't expose a non-existent feature.
        basic = top[0]
        if "voiceprompt" in basic:
            del basic[basic["voiceprompt"]]

        password = RadioSettingGroup("password", "Password")
        top.append(password)

        rs = RadioSetting(
            "rt18_password", "Programming password (blank = disabled)",
            RadioSettingValueString(0, _PASSWORD_LEN,
                                    self._rt18_get_password(),
                                    autopad=False,
                                    charset="0123456789"))
        rs.set_doc(
            "Password required (on the radio's vendor CPS) to "
            "enter programming mode. 1-6 digits, or blank to disable "
            "password protection. Change this field and upload to set a "
            "new password, or clear it and upload to remove password "
            "protection entirely. Confirmed via passive USB capture of a "
            "real 'set password' session; not confirmed to actually gate "
            "anything on the radio side beyond what was observed.")
        rs.set_apply_callback(self._rt18_apply_password)
        password.append(rs)

        return top
