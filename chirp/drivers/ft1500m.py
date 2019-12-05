# Copyright 2019 Josh Small VK2HFF <chirp@vk2hff.ampr.org>
# - Derived from ./ft1802.py Copyright 2012 Tom Hayward <tom@tomh.us>
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

# FT-1500M Clone Proceedure
# 1. Turn radio off.
# 2. Connect cable to mic jack.
# 3. Press and hold in the [MHz],[LOW] and [D/MR] keys
#    while turning the radio on.
# 4. In Chirp, choose Download from Radio.
# 5. Press the [MHz(SET)] key to send image.
# or
# 4. Press the [D/MR(MW)] key ("--WAIT--" will appear on the LCD).
# 5. In Chirp, choose Upload to Radio.

from chirp.drivers import yaesu_clone
from chirp import chirp_common, bitwise, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettings
from textwrap import dedent

MEM_FORMAT = """
#seekto 0x002a;
struct {
  u8 unknown_f:4,
     pskip:1,
     skip:1,
     visible:1,
     valid:1;
} flags[130];

#seekto 0x00ca;
struct {
  u8 unknown1a:2,
     narrow:1,
     clk_shift:1,
     unknown1b:4;
  u8 unknown2a:3,
     unknown2b:2,
     tune_step:3;
  bbcd freq[3];
  u8 tone;
  u8 name[6];
  u8 unknown3;
  u8 offset;
  u8 unknown4a:1,
     unknown4b:1,
     unknown4c:2,
     unknown4d:4;
  u8 unknown5a:2,
     tmode:2,
     power:2,
     duplex:2;
} memory[130];
"""


MODES = ["FM", "NFM"]
TMODES = ["", "Tone", "TSQL"]
DUPLEX = ["", "-", "+"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
POWER_LEVELS = [chirp_common.PowerLevel("LOW1", watts=5),
                chirp_common.PowerLevel("LOW2", watts=10),
                chirp_common.PowerLevel("LOW3", watts=25),
                chirp_common.PowerLevel("HIGH", watts=50),
                ]
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ +-/?()?_"


@directory.register
class FT1500Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FT-1500M"""
    VENDOR = "Yaesu"
    MODEL = "FT-1500M"
    BAUD_RATE = 9600

    _model = "AH4N0"
    _block_lengths = [10, 16, 3953]
    _memsize = 3979

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
1. Turn radio off.
2. Connect cable to mic jack.
3. Press and hold in the [MHz], [LOW], and [D/MR] keys
   while turning the radio on.
4. <b>After clicking OK</b>, press the [MHz(SET)] key to send image."""))
        rp.pre_upload = _(dedent("""\
1. Turn radio off.
2. Connect cable to mic jack.
3. Press and hold in the [MHz], [LOW], and [D/MR] keys
   while turning the radio on.
4. Press the [D/MR(MW)] key ("--WAIT--" will appear on the LCD)."""))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.memory_bounds = (0, 129)

        rf.can_odd_split = False
        rf.has_ctone = False
        rf.has_tuning_step = True
        rf.has_dtcs_polarity = False
        rf.has_bank = False

        rf.valid_tuning_steps = STEPS
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_bands = [(137000000, 174000000)]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = DUPLEX
        rf.valid_skips = ["", "S", "P"]
        rf.valid_name_length = 6
        rf.valid_characters = CHARSET
        rf.has_cross = False

        return rf

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0, self._memsize-2)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number]) + \
               repr(self._memobj.flags[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]
        visible = _flag["visible"]
        valid = _flag["valid"]
        skip = _flag["skip"]
        pskip = _flag["pskip"]
        mem = chirp_common.Memory()
        mem.number = number

        if not visible:
            mem.empty = True
        if not valid:
            mem.empty = True
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = chirp_common.fix_rounded_step(int(_mem.offset) * 100000)
        mem.duplex = DUPLEX[_mem.duplex]
        mem.tuning_step = STEPS[_mem.tune_step] or STEPS[0]
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.tone]
        for i in _mem.name:
            if i == 0xFF:
                break
            if i & 0x80 == 0x80:
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
        _flag = self._memobj.flags[mem.number]
        valid = _flag["valid"]
        visible = _flag["visible"]

        if not mem.empty and not valid:
            _flag["valid"] = True
            _mem.unknown1a = 0x00
            _mem.clk_shift = 0x00
            _mem.unknown1b = 0x00
            _mem.unknown2a = 0x00
            _mem.unknown2b = 0x00
            _mem.unknown3 = 0x00
            _mem.unknown4a = 0x00
            _mem.unknown4b = 0x00
            _mem.unknown4c = 0x00
            _mem.unknown4d = 0x00
            _mem.unknown5a = 0x00

        if mem.empty and valid and not visible:
            _flag["valid"] = False
            return
        _flag["visible"] = not mem.empty

        if mem.empty:
            return

        _flag["valid"] = True

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 100000
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tune_step = STEPS.index(mem.tuning_step)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)

        _mem.name = [0xFF] * 6
        for i in range(0, len(mem.name)):
            try:
                _mem.name[i] = CHARSET.index(mem.name[i])
            except IndexError:
                raise Exception("Character `%s' not supported")

        _mem.narrow = MODES.index(mem.mode)
        _mem.power = 3 if mem.power is None else POWER_LEVELS.index(mem.power)

        _flag["pskip"] = mem.skip == "P"
        _flag["skip"] = mem.skip == "S"

        for element in mem.extra:
            setattr(_mem, element.get_name(), element.value)
