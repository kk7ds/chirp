# Copyright 2012 Tom Hayward <tom@tomh.us>
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

# FT-1802 Clone Procedure
# 1. Turn radio off.
# 2. Connect cable to mic jack.
# 3. Press and hold in the [LOW(A/N)] key while turning the radio on.
# 4. In Chirp, choose Download from Radio.
# 5. Press the [MHz(SET)] key to send image.
# or
# 4. Press the [D/MR(MW)] key ("--WAIT--" will appear on the LCD).
# 5. In Chirp, choose Upload to Radio.

from chirp.drivers import yaesu_clone
from chirp import chirp_common, bitwise, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean

MEM_FORMAT = """
#seekto 0x06ea;
struct {
  u8 odd_pskip:1,
     odd_skip:1,
     odd_visible:1,
     odd_valid:1,
     even_pskip:1,
     even_skip:1,
     even_visible:1,
     even_valid:1;
} flags[100];

#seekto 0x076a;
struct {
  u8 unknown1a:1,
     step_changed:1,
     narrow:1,
     clk_shift:1,
     unknown1b:4;
  u8 unknown2a:2,
     duplex:2,
     unknown2b:1,
     tune_step:3;
  bbcd freq[3];
  u8 power:2,
     unknown3:3,
     tmode:3;
  u8 name[6];
  bbcd offset[3];
  u8 tone;
  u8 dtcs;
  u8 unknown4;
} memory[200];
"""


MODES = ["FM", "NFM"]
TMODES = ["", "Tone", "TSQL", "DTCS", "TSQL-R", "Cross"]
CROSS_MODES = ["DTCS->", "Tone->DTCS", "DTCS->Tone"]
DUPLEX = ["", "-", "+", "split"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
POWER_LEVELS = [chirp_common.PowerLevel("LOW1", watts=5),
                chirp_common.PowerLevel("LOW2", watts=10),
                chirp_common.PowerLevel("LOW3", watts=25),
                chirp_common.PowerLevel("HIGH", watts=50),
                ]
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ +-/?()?_"


@directory.register
class FT1802Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FT-1802"""
    VENDOR = "Yaesu"
    MODEL = "FT-1802M"
    BAUD_RATE = 19200

    _model = b"AH023"
    _block_lengths = [10, 8001]
    _memsize = 8011

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to mic jack.\n"
            "3. Press and hold in the [LOW(A/N)] key while turning the radio"
            " on.\n"
            "4. <b>After clicking OK</b>, press the [MHz(SET)] key to send"
            " image.\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect cable to mic jack.\n"
            "3. Press and hold in the [LOW(A/N)] key while turning the radio"
            " on.\n"
            "4. Press the [D/MR(MW)] key (\"--WAIT--\" will appear on the"
            " LCD).\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.memory_bounds = (0, 199)

        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_tuning_step = True
        rf.has_dtcs_polarity = False  # in radio settings, not per memory
        rf.has_bank = False  # has banks, but not implemented

        rf.valid_tuning_steps = STEPS
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_bands = [(137000000, 174000000)]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = DUPLEX
        rf.valid_skips = ["", "S", "P"]
        rf.valid_name_length = 6
        rf.valid_characters = CHARSET
        rf.has_cross = True
        rf.valid_cross_modes = list(CROSS_MODES)

        return rf

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0, self._memsize-2)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number]) + \
               repr(self._memobj.flags[number/2])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number/2]

        nibble = (number % 2) and "odd" or "even"
        visible = _flag["%s_visible" % nibble]
        valid = _flag["%s_valid" % nibble]
        pskip = _flag["%s_pskip" % nibble]
        skip = _flag["%s_skip" % nibble]

        mem = chirp_common.Memory()
        mem.number = number

        if not visible:
            mem.empty = True
        if not valid:
            mem.empty = True
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = chirp_common.fix_rounded_step(int(_mem.offset) * 1000)
        mem.duplex = DUPLEX[_mem.duplex]
        mem.tuning_step = _mem.step_changed and \
            STEPS[_mem.tune_step] or STEPS[0]
        if _mem.tmode < TMODES.index("Cross"):
            mem.tmode = TMODES[_mem.tmode]
            mem.cross_mode = CROSS_MODES[0]
        else:
            mem.tmode = "Cross"
            mem.cross_mode = CROSS_MODES[_mem.tmode - TMODES.index("Cross")]
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        for i in _mem.name:
            if i == 0xFF:
                break
            if i & 0x80 == 0x80:
                # first bit in name is "show name"
                mem.name += CHARSET[0x80 ^ int(i)]
            else:
                mem.name += CHARSET[i]
        mem.name = mem.name.rstrip()
        mem.mode = _mem.narrow and "NFM" or "FM"
        mem.skip = pskip and "P" or skip and "S" or ""
        mem.power = POWER_LEVELS[_mem.power]

        mem.extra = RadioSettingGroup("extra", "Extra Settings")
        rs = RadioSetting("clk_shift", "Clock Shift",
                          RadioSettingValueBoolean(_mem.clk_shift))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flag = self._memobj.flags[mem.number/2]

        nibble = (mem.number % 2) and "odd" or "even"

        valid = _flag["%s_valid" % nibble]
        visible = _flag["%s_visible" % nibble]

        if not mem.empty and not valid:
            _flag["%s_valid" % nibble] = True
            _mem.unknown1a = 0x00
            _mem.clk_shift = 0x00
            _mem.unknown1b = 0x00
            _mem.unknown2a = 0x00
            _mem.unknown2b = 0x00
            _mem.unknown3 = 0x00
            _mem.unknown4 = 0x00

        if mem.empty and valid and not visible:
            _flag["%s_valid" % nibble] = False
            return
        _flag["%s_visible" % nibble] = not mem.empty

        if mem.empty:
            return

        _flag["%s_valid" % nibble] = True

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        _mem.step_changed = mem.tuning_step != STEPS[0]
        if mem.tmode != "Cross":
            _mem.tmode = TMODES.index(mem.tmode)
        else:
            _mem.tmode = TMODES.index("Cross") + \
                         CROSS_MODES.index(mem.cross_mode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)

        _mem.name = [0xFF] * 6
        for i in range(0, len(mem.name)):
            try:
                _mem.name[i] = CHARSET.index(mem.name[i])
            except IndexError:
                raise Exception("Character `%s' not supported")
        if _mem.name[0] != 0xFF:
            _mem.name[0] += 0x80  # show name instead of frequency

        _mem.narrow = MODES.index(mem.mode)
        _mem.power = 3 if mem.power is None else POWER_LEVELS.index(mem.power)

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        for element in mem.extra:
            setattr(_mem, element.get_name(), element.value)
