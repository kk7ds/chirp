# Copyright 2010 Dan Smith <dsmith@danplanet.com>
# Copyright 2017 Wade Simmons <wade@wades.im>
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
from textwrap import dedent

from chirp.drivers import yaesu_clone, ft1d
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSettings

LOG = logging.getLogger(__name__)

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("Mid", watts=30),
                chirp_common.PowerLevel("Hi", watts=65)]

TMODES = ["", "Tone", "TSQL", "DTCS", "TSQL-R", None, None, "Pager", "Cross"]
CROSS_MODES = [None, "DTCS->", "Tone->DTCS", "DTCS->Tone"]

MODES = ["FM", "NFM"]
STEPS = [0, 5, 6.25, 10, 12.5, 15, 20, 25, 50, 100]  # 0 = auto
RFSQUELCH = ["OFF", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]

# Charset is subset of ASCII + some unknown chars \x80-\x86
VALID_CHARS = ["%i" % int(x) for x in range(0, 10)] + \
    list(":>=<?@") + \
    [chr(x) for x in range(ord("A"), ord("Z") + 1)] + \
    list("[\\]_") + \
    [chr(x) for x in range(ord("a"), ord("z") + 1)] + \
    list("%*+,-/=$ ")

MEM_FORMAT = """
#seekto 0xceca;
struct {
  u8 unknown5;
  u8 unknown3;
  u8 unknown4:6,
     dsqtype:2;
  u8 dsqcode;
  u8 unknown1[2];
  char mycall[10];
  u8 unknown2[368];
} settings;

#seekto 0xfec9;
u8 checksum;
"""


@directory.register
class FTM3200Radio(ft1d.FT1Radio):
    """Yaesu FTM-3200D"""
    BAUD_RATE = 38400
    VENDOR = "Yaesu"
    MODEL = "FTM-3200D"
    VARIANT = "R"

    _model = "AH52N"
    _memsize = 65227
    _block_lengths = [10, 65217]
    _has_vibrate = False
    _has_af_dual = False

    _mem_params = (199,            # size of memories array
                   199)            # size of flags array

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to DATA terminal.
            3. Press and hold in the [MHz(SETUP)] key while turning the radio
                 on ("CLONE" will appear on the display).
            4. <b>After clicking OK</b>, press the [REV(DW)] key
                 to send image."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to DATA terminal.
            3. Press and hold in the [MHz(SETUP)] key while turning the radio
                 on ("CLONE" will appear on the display).
            4. Press the [MHz(SETUP)] key
                 ("-WAIT-" will appear on the LCD)."""))
        return rp

    def process_mmap(self):
        mem_format = ft1d.MEM_FORMAT + MEM_FORMAT
        self._memobj = bitwise.parse(mem_format % self._mem_params, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = [x for x in TMODES if x is not None]
        rf.valid_cross_modes = [x for x in CROSS_MODES if x is not None]
        rf.valid_duplexes = list(ft1d.DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(136000000, 174000000)]
        # rf.valid_skips = SKIPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(VALID_CHARS)
        rf.valid_name_length = 8
        rf.memory_bounds = (1, 199)
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_bank = False
        rf.has_bank_names = False
        # disable until implemented
        rf.has_settings = False
        return rf

    def _decode_label(self, mem):
        # TODO preserve the unknown \x80-x86 chars?
        return str(mem.label).rstrip("\xFF").decode('ascii', 'replace')

    def _encode_label(self, mem):
        label = mem.name.rstrip().encode('ascii', 'ignore')
        return self._add_ff_pad(label, 16)

    def _encode_charsetbits(self, mem):
        # TODO this is a setting to decide if the memory should be displayed
        # as a name or frequency. Should we expose this setting to the user
        # instead of autoselecting it (and losing their preference)?
        if mem.name.rstrip() == '':
            return [0x00, 0x00]
        return [0x00, 0x80]

    def _decode_power_level(self, mem):
        return POWER_LEVELS[mem.power - 1]

    def _encode_power_level(self, mem):
        return POWER_LEVELS.index(mem.power) + 1

    def _decode_mode(self, mem):
        return MODES[mem.mode_alt]

    def _encode_mode(self, mem):
        return MODES.index(mem.mode)

    def _get_tmode(self, mem, _mem):
        if _mem.tone_mode > 8:
            tmode = "Cross"
            mem.cross_mode = CROSS_MODES[_mem.tone_mode - 8]
        else:
            tmode = TMODES[_mem.tone_mode]

        if tmode == "Pager":
            # TODO chirp_common does not allow 'Pager'
            #   Expose as a different setting?
            mem.tmode = ""
        else:
            mem.tmode = tmode

    def _set_tmode(self, _mem, mem):
        if mem.tmode == "Cross":
            _mem.tone_mode = 8 + CROSS_MODES.index(mem.cross_mode)
        else:
            _mem.tone_mode = TMODES.index(mem.tmode)

    def _set_mode(self, _mem, mem):
        _mem.mode_alt = self._encode_mode(mem)

    def get_bank_model(self):
        return None

    def _debank(self, mem):
        return

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x064A, 0x06C8),
                yaesu_clone.YaesuChecksum(0x06CA, 0x0748),
                yaesu_clone.YaesuChecksum(0x074A, 0x07C8),
                yaesu_clone.YaesuChecksum(0x07CA, 0x0848),
                yaesu_clone.YaesuChecksum(0x0000, 0xFEC9)]

    def _get_settings(self):
        # TODO
        top = RadioSettings()
        return top

    @classmethod
    def _wipe_memory(cls, mem):
        mem.set_raw("\x00" * (mem.size() / 8))

    def sync_out(self):
        # Need to give enough time for the radio to ACK after writes
        self.pipe.timeout = 1
        return super(FTM3200Radio, self).sync_out()
