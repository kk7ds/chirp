# Copyright 2015 Eric Allen <eric@hackerengineer.net>
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

"""TYT uv3r (2.5 kHz) radio management module"""

from chirp import chirp_common, bitwise, directory
from chirp.drivers.wouxun import do_download, do_upload

from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList, RadioSettingValueBoolean

from chirp.drivers.th_uv3r import TYTUV3RRadio, tyt_uv3r_prep, THUV3R_CHARSET


def tyt_uv3r_download(radio):
    tyt_uv3r_prep(radio)
    return do_download(radio, 0x0000, 0x0B30, 0x0010)


def tyt_uv3r_upload(radio):
    tyt_uv3r_prep(radio)
    return do_upload(radio, 0x0000, 0x0B30, 0x0010)


mem_format = """
// 20 bytes per memory
struct memory {
  ul32 rx_freq; // 4 bytes
  ul32 tx_freq; // 8 bytes

  ul16 rx_tone; // 10 bytes
  ul16 tx_tone; // 12 bytes

  u8 unknown1a:1,
     iswide:1,
     bclo_n:1,
     vox_n:1,
     tail:1,
     power_high:1,
     voice_mode:2;
  u8 name[6]; // 19 bytes
  u8 unknown2; // 20 bytes
};

#seekto 0x0010;
struct memory memory[128];

#seekto 0x0A80;
u8 emptyflags[16];
u8 skipflags[16];
"""

VOICE_MODE_LIST = ["Compander", "Scrambler", "None"]


@directory.register
class TYTUV3R25Radio(TYTUV3RRadio):
    MODEL = "TH-UV3R-25"
    _memsize = 2864

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low", watts=0.80)]

    def get_features(self):
        rf = super(TYTUV3R25Radio, self).get_features()

        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 37.50,
                                 50.0, 100.0]
        rf.valid_power_levels = self.POWER_LEVELS
        return rf

    def sync_in(self):
        self.pipe.timeout = 2
        self._mmap = tyt_uv3r_download(self)
        self.process_mmap()

    def sync_out(self):
        tyt_uv3r_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        bit = 1 << ((number - 1) % 8)
        byte = (number - 1) / 8

        if self._memobj.emptyflags[byte] & bit:
            mem.empty = True
            return mem

        mem.freq = _mem.rx_freq * 10
        mem.offset = abs(_mem.rx_freq - _mem.tx_freq) * 10
        if _mem.tx_freq == _mem.rx_freq:
            mem.duplex = ""
        elif _mem.tx_freq < _mem.rx_freq:
            mem.duplex = "-"
        elif _mem.tx_freq > _mem.rx_freq:
            mem.duplex = "+"

        mem.mode = _mem.iswide and "FM" or "NFM"
        self._decode_tone(mem, _mem)
        mem.skip = (self._memobj.skipflags[byte] & bit) and "S" or ""

        for char in _mem.name:
            try:
                c = THUV3R_CHARSET[char]
            except:
                c = ""
            mem.name += c
        mem.name = mem.name.rstrip()

        mem.power = self.POWER_LEVELS[not _mem.power_high]

        mem.extra = RadioSettingGroup("extra", "Extra Settings")

        rs = RadioSetting("bclo_n", "Busy Channel Lockout",
                          RadioSettingValueBoolean(not _mem.bclo_n))
        mem.extra.append(rs)

        rs = RadioSetting("vox_n", "VOX",
                          RadioSettingValueBoolean(not _mem.vox_n))
        mem.extra.append(rs)

        rs = RadioSetting("tail", "Squelch Tail Elimination",
                          RadioSettingValueBoolean(_mem.tail))
        mem.extra.append(rs)

        rs = RadioSetting("voice_mode", "Voice Mode",
                          RadioSettingValueList(
                              VOICE_MODE_LIST,
                              current_index=_mem.voice_mode-1))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        bit = 1 << ((mem.number - 1) % 8)
        byte = (mem.number - 1) // 8

        if mem.empty:
            self._memobj.emptyflags[byte] |= bit
            _mem.set_raw("\xFF" * 20)
            return

        self._memobj.emptyflags[byte] &= ~bit

        _mem.rx_freq = mem.freq / 10

        if mem.duplex == "":
            _mem.tx_freq = _mem.rx_freq
        elif mem.duplex == "-":
            _mem.tx_freq = _mem.rx_freq - mem.offset / 10.0
        elif mem.duplex == "+":
            _mem.tx_freq = _mem.rx_freq + mem.offset / 10.0

        _mem.iswide = mem.mode == "FM"

        self._encode_tone(mem, _mem)

        if mem.skip:
            self._memobj.skipflags[byte] |= bit
        else:
            self._memobj.skipflags[byte] &= ~bit

        name = []
        for char in mem.name.ljust(6):
            try:
                c = THUV3R_CHARSET.index(char)
            except:
                c = THUV3R_CHARSET.index(" ")
            name.append(c)
        _mem.name = name

        if mem.power == self.POWER_LEVELS[0]:
            _mem.power_high = 1
        else:
            _mem.power_high = 0

        for element in mem.extra:
            if element.get_name() == 'voice_mode':
                setattr(_mem, element.get_name(), int(element.value) + 1)
            elif element.get_name().endswith('_n'):
                setattr(_mem, element.get_name(), 1 - int(element.value))
            else:
                setattr(_mem, element.get_name(), element.value)

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize
