# Copyright 2024 Paul Decker <kg7hf1@gmail.com>
#      Derives from template.py
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

import logging
from chirp import chirp_common, directory
from chirp import bitwise
from chirp.drivers import icf

LOG = logging.getLogger(__name__)

BAUDS = [4800]
POWER_LEVELS = []
DUPLEX_MODES = ['', 'split', 'off']
# do not reorder this list
# MODULATION_MODES = ["USB", "R3E", "AM", "LSB", "AFS", "FSK", "CW"]
MODULATION_MODES = ["USB", "USB", "AM", "LSB", "DIG", "FSK", "CW"]
TUNING_STEPS = [0.5]

MEM_FORMAT = """

#seekto 0xE020;
struct {
  bbcd rx_freq[4];
  u8 mode;
  char name[7];
  bbcd tx_freq[4];
}memory[232];

"""


@directory.register
class IcomM710Radio(icf.IcomCloneModeRadio):
    """ICOM IC-M710"""
    VENDOR = "Icom"
    MODEL = "IC-M710"
    BAUD_RATE = 4800

    _model = "\x162\x00\x01"  # 4-byte mode string
    _endframe = ''
    _ignore_clone_ok = True

    _memsize = 0xEFC0
    _ranges = [(0xE000, 0xEFC0, 32)]
    _can_hispeed = False
    _double_ident = False

    _raw_frames = False
    _highbit_flip = False

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank_index = False
        rf.has_dtcs = False
        rf.has_rx_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_mode = True
        rf.has_offset = False
        rf.has_name = True
        rf.has_bank = False
        rf.has_bank_names = False
        rf.has_tuning_step = False
        rf.has_ctone = False
        rf.has_cross = False
        rf.has_infinite_number = False
        rf.has_nostep_tuning = True
        rf.has_comment = False
        rf.has_settings = False  # TODO radio does have settings
        rf.has_variable_power = False

        rf.memory_bounds = (0, 231)
        rf.valid_bands = [(1000000, 29999999)]

        rf.valid_duplexes = DUPLEX_MODES
        rf.can_odd_split = True
        rf.valid_modes = MODULATION_MODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tones = []
        rf.valid_tmodes = []
        rf.valid_skips = []
        return rf

    # Convert the raw byte array into a memory object structure
    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # Return a raw representation of the memory object, which
    # is very helpful for development
    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def sync_out(self):
        self.pipe.baudrate = 4800
        icf.clone_to_radio(self)

    # Extract a high-level memory object from the
    # low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number):

        # this just gets the 160 common
        # the 72 ITU channels are probably working
        # there may be some strange behavior with
        # the SITOR FSK "hidden" channels
        # best be careful about trying to set a fixed
        # simplex channel with a duplex frequency
        # TODO test, test, test, all the combinations.

        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[int(number)]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        mem.number = number
        # Convert your low-level frequency to Hertz.
        mem.freq = int(_mem.rx_freq)
        mem.name = str(_mem.name).rstrip()  # Set the alpha tag

        mem.mode = MODULATION_MODES[0]
        if (_mem.mode > -1) and (_mem.mode < 7):
            mem.mode = MODULATION_MODES[int(_mem.mode)]

        # if the frequency is above 30MHz
        # (166666665 or FF,FF,FF,FF), it's simplex
        if (int(_mem.tx_freq) > 29999999):
            mem.duplex = 'off'
        elif (int(_mem.rx_freq) == int(_mem.tx_freq)):
            mem.duplex = ''
        else:
            mem.duplex = 'split'
            mem.offset = int(_mem.tx_freq)

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if (mem.freq < 1000000) or (mem.freq > 29999999):
            mem.empty = True

        return mem

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[int(mem.number)]

        _mem.name = mem.name.ljust(7)[:7]

        if mem.empty:
            _mem.rx_freq.set_raw(b'\xFF' * 4)
            _mem.mode.set_raw(b'\x00')
            _mem.tx_freq.set_raw(b'\xFF' * 4)
        else:
            _mem.rx_freq = mem.freq
            _mem.mode = MODULATION_MODES.index(mem.mode)
            if mem.duplex == 'off':
                _mem.tx_freq.set_raw(b'\xFF' * 4)
            elif mem.duplex == '':
                _mem.tx_freq = _mem.rx_freq
            else:
                _mem.tx_freq = mem.offset
