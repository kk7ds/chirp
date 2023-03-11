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

from chirp.drivers import yaesu_clone
from chirp import chirp_common, bitwise

# This driver is unfinished and therefore does not register itself with Chirp.
#
# Downloads should work consistently but an upload has not been attempted.
#
# There is a stray byte at 0xC in the radio download that is not present in the
# save file from the CE-21 software. This puts the first few bytes of channel 1
# in the wrong location. A quick hack to fix the subsequent channels was to
# insert the #seekto dynamically, but this does nothing to fix reading of
# channel 1 (memory[0]).
MEM_FORMAT = """
u8 unknown1[6];
u8 prioritych;

#seekto %d;
struct {
  u8 empty:1,
     txinhibit:1,
     tot:1,
     low_power:1,
     bclo:1,
     btlo:1,
     skip:1,
     pwrsave:1;
  u8 unknown2:5,
     narrow:1,
     unknown2b:2;
  u24 name;
  u8 ctone;
  u8 rtone;
  u8 unknown3;
  bbcd freq_rx[3];
  bbcd freq_tx[3];
} memory[32];

char imgname[10];
"""

STEPS = [5.0, 6.25]
CHARSET = "".join([chr(x) for x in range(ord("0"), ord("9")+1)] +
                  [chr(x) for x in range(ord("A"), ord("Z")+1)]) + \
                      r"<=>*+-\/_ "
TONES = list(chirp_common.TONES)
TONES.remove(165.5)
TONES.remove(171.3)
TONES.remove(177.3)
POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("Low", watts=1.0)]


# @directory.register
class VX510Radio(yaesu_clone.YaesuCloneModeRadio):
    """Vertex VX-510V"""
    BAUD_RATE = 9600
    VENDOR = "Vertex Standard"
    MODEL = "VX-510V"

    _model = ""
    _memsize = 470
    _block_lengths = [10, 460]
    _block_size = 8

    def _checksums(self):
        return []
        # These checksums don't pass, so the alg might be different than Yaesu.
        # return [yaesu_clone.YaesuChecksum(0, self._memsize - 2)]
        # return [yaesu_clone.YaesuChecksum(0, 10),
        #         yaesu_clone.YaesuChecksum(12, self._memsize - 1)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.memory_bounds = (1, 32)
        rf.valid_bands = [(13600000, 174000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 4
        rf.valid_characters = CHARSET
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % 0xA, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number-1])

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number

        _mem = self._memobj.memory[number-1]

        mem.empty = _mem.empty
        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq_rx) * 1000)

        for i in range(0, 4):
            index = (_mem.name >> (i*6)) & 0x3F
            mem.name += CHARSET[index]

        freq_tx = chirp_common.fix_rounded_step(int(_mem.freq_tx) * 1000)
        if _mem.txinhibit:
            mem.duplex = "off"
        elif mem.freq == freq_tx:
            mem.duplex = ""
            mem.offset = 0
        elif 144000000 <= mem.freq < 148000000:
            mem.duplex = "+" if freq_tx > mem.freq else "-"
            mem.offset = abs(mem.freq - freq_tx)
        else:
            mem.duplex = "split"
            mem.offset = freq_tx

        mem.mode = _mem.narrow and "NFM" or "FM"
        mem.power = POWER_LEVELS[_mem.low_power]

        rtone = int(_mem.rtone)
        ctone = int(_mem.ctone)
        tmode_tx = tmode_rx = ""

        if rtone & 0x80:
            tmode_tx = "DTCS"
            mem.dtcs = chirp_common.DTCS_CODES[int(rtone) - 0x80]
        elif rtone:
            tmode_tx = "Tone"
            mem.rtone = TONES[rtone - 1]
            if not ctone:
                # not used, but this is a better default than 88.5
                mem.ctone = TONES[rtone - 1]

        if ctone & 0x80:
            tmode_rx = "DTCS"
            mem.rx_dtcs = chirp_common.DTCS_CODES[int(ctone) - 0x80]
        elif ctone:
            tmode_rx = "Tone"
            mem.ctone = TONES[ctone - 1]

        if tmode_tx == "Tone" and not tmode_rx:
            mem.tmode = "Tone"
        elif tmode_tx == tmode_rx and tmode_tx == "Tone" and \
                mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif tmode_tx == tmode_rx and tmode_tx == "DTCS" and \
                mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif tmode_rx or tmode_tx:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (tmode_tx, tmode_rx)

        mem.skip = _mem.skip and "S" or ""

        return mem

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize


# @directory.register
class VX510File(VX510Radio, chirp_common.FileBackedRadio):
    """Vertex CE-21 File"""
    VENDOR = "Vertex Standard"
    MODEL = "CE-21 File"

    _model = ""
    _memsize = 664

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0, self._memsize - 1)]

    def process_mmap(self):
        # CE-21 file is missing the 0xC byte, probably a checksum.
        # It's not a YaesuChecksum.
        self._memobj = bitwise.parse(MEM_FORMAT % 0x9, self._mmap)

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize
