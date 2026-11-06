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

"""Wouxun KG-WV50 radio management module

The KG-WV50 is a 4G PoC handheld; its analog section is a KG-UV8E-family
transceiver that identifies itself as ``KG-UV8D-A`` on the clone link, so
this driver builds on the shared KG-UV8 support and overrides only what
differs:

* the frame tag is ``0x78`` (``0x7b`` on the KG-UV8E)
* reads have to be split into 32 byte blocks
* ``CH-001`` lives in slot 0 here, the KG-UV8E starts at slot 1
* channel names are GBK and use all 12 bytes of the field
* bit 0 of the flag byte means "narrow" (the KG-UV8E calls it "wide")
* band limits and output power

Reverse engineered from the vendor software (KG-WV50 Commander 1.01, build
170909) and verified on a real radio: download 32768 bytes, upload the same
image again and read it back - no differences.
"""

import logging

from chirp import chirp_common, directory, errors
from chirp.drivers.kguv8d import MEM_DEFS
from chirp.drivers.kguv8e import KGUV8ERadio
from chirp.settings import RadioSettingGroup, RadioSettings

LOG = logging.getLogger(__name__)

CHANNEL_COUNT = 999
NAME_SIZE = 12
NAME_ENCODING = "gbk"

MEM_FORMAT = MEM_DEFS + """
#seekto 0x0900;
struct channel memory[1000];

struct {
    char    name[12];
} names[1000];

#seekto 0x7670;
u8          valid[1000];
"""


@directory.register
class KGWV50Radio(KGUV8ERadio):
    """Wouxun KG-WV50"""
    VENDOR = "Wouxun"
    MODEL = "KG-WV50"

    _record_start = 0x78
    _channel_index_offset = -1
    # Only the mapped area is written: the radio answers 0xdd for everything
    # above it (reserved / factory data) and the vendor software does not
    # touch those blocks either
    _upload_start = 0x0900
    _upload_end = 0x7A60
    _read_block = 0x20
    _write_block = 0x20
    _MEM_FORMAT = MEM_FORMAT

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.0),
                    chirp_common.PowerLevel("High", watts=2.5)]

    _CJK = "".join(chr(c) for c in range(0x4E00, 0x9FA6))

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "The Wouxun KG-WV50 driver is new. Power, bandwidth and skip "
            "flags were checked against one radio; please report anything "
            "that does not match your unit.")
        return rp

    @classmethod
    def match_model(cls, filedata, filename):
        # Images carry metadata, so do not claim images from other radios
        return False

    def _upload(self):
        try:
            self._identify()
            self._do_upload(self._upload_start, self._upload_end,
                            self._write_block)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)

    def get_features(self):
        rf = super().get_features()
        rf.has_settings = False
        rf.valid_bands = [(136000000, 175000000), (350000000, 480000000)]
        rf.valid_name_length = NAME_SIZE
        rf.valid_characters = chirp_common.CHARSET_ASCII + self._CJK
        rf.memory_bounds = (1, CHANNEL_COUNT)
        return rf

    def get_settings(self):
        # has_settings is False; this exists so nothing reaches the KG-UV8E
        # settings blocks, which do not exist on this radio
        return RadioSettings(RadioSettingGroup("cfg", "Configuration"))

    # ---- differences from the KG-UV8E ----

    def _flush_input(self):
        """Drop anything left over from a failed transfer"""
        try:
            pending = self.pipe.in_waiting
            if pending:
                self.pipe.read(pending)
        except Exception:
            pass

    def _write_record(self, cmd, payload=b""):
        # The radio needs a moment after the port is opened and drops the
        # first frame; a failed transfer can also leave bytes behind
        self._flush_input()
        super()._write_record(cmd, payload)

    def _get_name(self, _nam):
        raw = bytes(_nam.get_raw()).split(b"\x00")[0]
        try:
            return raw.decode(NAME_ENCODING).rstrip()
        except UnicodeDecodeError:
            return raw.decode(NAME_ENCODING, "replace").rstrip()

    def _set_name(self, _nam, name):
        raw = (name or "").encode(NAME_ENCODING, "replace")[:NAME_SIZE]
        _nam.set_raw(raw + b"\x00" * (NAME_SIZE - len(raw)))

    def _get_mode(self, _mem):
        # bit 0 of the flag byte is inverted on this radio
        return "NFM" if _mem.iswide else "FM"

    def _set_mode(self, _mem, mode):
        _mem.iswide = 1 if mode == "NFM" else 0

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if not mem.empty and mem.name:
            try:
                raw = mem.name.encode(NAME_ENCODING)
            except UnicodeEncodeError:
                msgs.append(chirp_common.ValidationError(
                    "Name is not encodable in %s" % NAME_ENCODING))
                raw = b""
            if len(raw) > NAME_SIZE:
                msgs.append(chirp_common.ValidationWarning(
                    "Name is too long for radio (%i > %i bytes), "
                    "it will be truncated" % (len(raw), NAME_SIZE)))
        return msgs
