# Copyright 2014 Tom Hayward <tom@tomh.us>
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

from chirp import bitwise, chirp_common, directory

TH9800_MEM_FORMAT = """
struct mem {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  lbcd ctcss[2];
  lbcd dtcs[2];
  u8 power:2,
     unknown0a:4,
     scan:2;
  u8 fmdev:2,
     unknown1a:2,
     unknown1b:4;
  u8 unknown2;
  u8 dtcs_pol:2,
     unknown3:4,
     tmode:2;
  u8 unknown4[4];
  u8 unknown5a:3,
     am:1,
     unknown5b:4;
  u8 unknown6[3];
  char name[6];
  u8 empty[2];
};

#seekto 0x1100;
struct mem memory[800];
"""


BLANK_MEMORY = "\xFF" * 8 + "\x00\x10\x23\x00\xC0\x08\x06\x00" \
               "\x00\x00\x76\x00\x00\x00" + "\xFF" * 10
DTCS_POLARITY = ["NN", "RN", "NR", "RR"]
SCAN_MODES = ["", "S", "P"]
MODES = ["FM", "FM", "NFM"]
TMODES = ["", "Tone", "TSQL", "DTCS"]


@directory.register
class TYTTH9800File(chirp_common.FileBackedRadio):
    """TYT TH-9800 .dat file"""
    VENDOR = "TYT"
    MODEL = "TH-9800"
    FILE_EXTENSION = "dat"

    _memsize = 69632

    def __init__(self, pipe):
        self.errors = []
        self._mmap = None

        if isinstance(pipe, str):
            self.pipe = None
            self.load_mmap(pipe)
        else:
            chirp_common.FileBackedRadio.__init__(self, pipe)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 800)
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_tmodes = TMODES
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "#*-+"
        rf.valid_bands = [( 26000000,  33000000),
                          ( 47000000,  54000000),
                          (108000000, 180000000),
                          (350000000, 399000000),
                          (430000000, 512000000),
                          (750000000, 947000000)]
        rf.valid_skips = SCAN_MODES
        rf.valid_modes = MODES + ["AM"]
        rf.valid_name_length = 6

        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and filename.endswith('.dat')

    def process_mmap(self):
        self._memobj = bitwise.parse(TH9800_MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number
        if _mem.get_raw().startswith("\xFF\xFF\xFF\xFF"):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        txfreq = int(_mem.tx_freq) * 10
        if txfreq == mem.freq:
            mem.duplex = ""
        elif abs(txfreq - mem.freq) > 70000000:
            mem.duplex = "split"
            mem.offset = txfreq
        elif txfreq < mem.freq:
            mem.duplex = "-"
            mem.offset = mem.freq - txfreq
        elif txfreq > mem.freq:
            mem.duplex = "+"
            mem.offset = txfreq - mem.freq

        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_pol]

        mem.tmode = TMODES[int(_mem.tmode)]
        mem.ctone = mem.rtone = int(_mem.ctcss) / 10.0
        mem.dtcs = int(_mem.dtcs)

        mem.name = str(_mem.name)
        mem.name = mem.name.replace("\xFF", " ").rstrip()

        mem.skip = SCAN_MODES[int(_mem.scan)]
        mem.mode = _mem.am and "AM" or MODES[int(_mem.fmdev)]

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        if mem.empty:
            _mem.set_raw(BLANK_MEMORY)
            return

        if _mem.get_raw() == BLANK_MEMORY:
            print "Initializing empty memory"
            _mem.set_raw(BLANK_MEMORY)

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "split":
            _mem.tx_freq = mem.offset / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        _mem.tmode = TMODES.index(mem.tmode)
        _mem.ctcss = mem.rtone * 10
        _mem.dtcs = mem.dtcs
        _mem.dtcs_pol = DTCS_POLARITY.index(mem.dtcs_polarity)

        _mem.name = mem.name.ljust(6, "\xFF")

        _mem.scan = SCAN_MODES.index(mem.skip)

        if mem.mode == "AM":
            _mem.am = True
            _mem.fmdev = 0
        else:
            _mem.am = False
            _mem.fmdev = MODES.index(mem.mode)
