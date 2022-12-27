# Copyright 2018 Antony Jordan <me6kxv@gmail.com>
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

from chirp import chirp_common, directory, errors
from chirp.drivers.kenwood_live import KenwoodLiveRadio, \
    command, iserr, NOCACHE

LOG = logging.getLogger(__name__)

TS850_DUPLEX = ["off", "split"]
TS850_TMODES = ["", "Tone"]
TS850_SKIP = ["", "S"]

TS850_MODES = {
    "N/A":   " ",
    "N/A":   "0",
    "LSB":   "1",
    "USB":   "2",
    "CW":    "3",
    "FM":    "4",
    "AM":    "5",
    "FSK":   "6",
    "CW-R":  "7",
    "FSK-R": "9",
}
TS850_MODES_REV = {val: mode for mode, val in TS850_MODES.items()}

TS850_TONES = list(chirp_common.OLD_TONES)
TS850_TONES.remove(69.3)

TS850_BANDS = [
    (1800000, 2000000),    # 160M Band
    (3500000, 4000000),    # 80M Band
    (7000000, 7300000),    # 40M Band
    (10100000, 10150000),  # 30M Band
    (14000000, 14350000),  # 20M Band
    (18068000, 18168000),  # 17M Band
    (21000000, 21450000),  # 15M Band
    (24890000, 24990000),  # 12M Band
    (28000000, 29700000)   # 10M Band
]


@directory.register
class TS850Radio(KenwoodLiveRadio):
    """Kenwood TS-850"""
    MODEL = "TS-850"
    BAUD_RATE = 4800

    _upper = 99
    _kenwood_valid_tones = list(TS850_TONES)

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.can_odd_split = True

        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_name = False
        rf.has_tuning_step = False

        rf.memory_bounds = (0, self._upper)

        rf.valid_bands = TS850_BANDS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC
        rf.valid_duplexes = TS850_DUPLEX
        rf.valid_modes = list(TS850_MODES.keys())
        rf.valid_skips = TS850_SKIP
        rf.valid_tmodes = TS850_TMODES

        return rf

    def get_memory(self, number):
        if number < 0 or number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % self._upper)
        if number in self._memcache and not NOCACHE:
            return self._memcache[number]

        result = command(self.pipe, *self._cmd_get_memory(number))

        if result == "N":
            mem = chirp_common.Memory()
            mem.number = number
            mem.empty = True
            self._memcache[mem.number] = mem
            return mem

        mem = self._parse_mem_spec(result)
        self._memcache[mem.number] = mem

        # check for split frequency operation
        result = command(self.pipe, *self._cmd_get_split(number))
        self._parse_split_spec(mem, result)

        return mem

    def set_memory(self, memory):
        if memory.number < 0 or memory.number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % self._upper)

        if memory.number > 90:
            if memory.duplex == TS850_DUPLEX[0]:
                memory.duplex = TS850_DUPLEX[1]
                memory.offset = memory.freq
            else:
                if memory.freq > memory.offset:
                    temp = memory.freq
                    memory.freq = memory.offset
                    memory.offset = temp

        # Clear out memory contents to prevent errors
        spec = self._make_base_spec(memory, 0)
        spec = "".join(spec)
        result = command(self.pipe, *self._cmd_set_memory(memory.number, spec))

        if iserr(result):
            raise errors.InvalidDataError("Radio refused %i" %
                                          memory.number)

        # If we have a split set the transmit frequency first.
        if memory.duplex == TS850_DUPLEX[1]:
            spec = "".join(self._make_split_spec(memory))
            result = command(self.pipe, *self._cmd_set_split(memory.number,
                                                             spec))
            if iserr(result):
                raise errors.InvalidDataError("Radio refused %i" %
                                              memory.number)

        spec = self._make_mem_spec(memory)
        spec = "".join(spec)
        result = command(self.pipe, *self._cmd_set_memory(memory.number, spec))
        if iserr(result):
            raise errors.InvalidDataError("Radio refused %i" % memory.number)

    def erase_memory(self, number):
        if number not in self._memcache:
            return

        resp = command(self.pipe, *self._cmd_erase_memory(number))
        if iserr(resp):
            raise errors.RadioError("Radio refused delete of %i" % number)

        del self._memcache[number]

    def _cmd_get_memory(self, number):
        return "MR", "0 %02i" % number

    def _cmd_get_split(self, number):
        return "MR", "1 %02i" % number

    def _cmd_get_memory_name(self, number):
        LOG.error("TS-850 does not support memory channel names")
        return ""

    def _cmd_set_memory(self, number, spec):
        return "MW", "0 %02i%s" % (number, spec)

    def _cmd_set_split(self, number, spec):
        return "MW", "1 %02i%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        LOG.error("TS-850 does not support memory channel names")
        return ""

    def _cmd_erase_memory(self, number):
        return "MW0 %02i%014i   " % (number, 0)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        # pad string so indexes match Kenwood docs
        spec = " " + spec   # Param Format Function

        _p1 = spec[3]       # P1    9      Split Specification
        # _p2 = spec[4]     # P2    -      Blank
        _p3 = spec[5:7]     # P3    7      Memory Channel
        _p4 = spec[7:18]    # P4    4      Frequency
        _p5 = spec[18]      # P5    2      Mode
        _p6 = spec[19]      # P6    10     Memory Lockout
        _p7 = spec[20]      # P7    1      Tone On/Off
        _p8 = spec[21:23]   # P8    14     Tone Frequency
        # _p9 = spec[23]    # P9    -      Blank

        mem.duplex = TS850_DUPLEX[int(_p1)]
        mem.number = int(_p3)
        mem.freq = int(_p4)
        mem.mode = TS850_MODES_REV[_p5]
        mem.skip = TS850_SKIP[int(_p6)]
        mem.tmode = TS850_TMODES[int(_p7)]

        if mem.tmode == TS850_TMODES[1]:
            mem.rtone = TS850_TONES[int(_p8)-1]

        return mem

    def _parse_split_spec(self, mem, spec):

        # pad string so indexes match Kenwood docs
        spec = " " + spec

        split_freq = int(spec[7:18])  # P4

        if mem.freq != 0:
            mem.duplex = "split"
            mem.offset = split_freq

        return mem

    def _make_base_spec(self, mem, freq):
        if mem.mode == "FM" \
                and mem.duplex == TS850_DUPLEX[1] \
                and mem.tmode == TS850_TMODES[1]:
            tmode = "1"
            tone = "%02i" % (TS850_TONES.index(mem.rtone)+1)
        else:
            tmode = "0"
            tone = "  "

        spec = (                                 # Param Format Function
            "%011i" % freq,                      # P4    4      Frequency
            TS850_MODES[mem.mode],               # P5    2      Mode
                                                 #              (Except Tune)
            "%i" % (mem.skip == TS850_SKIP[1]),  # P6    10     Memory Lockout
            tmode,                               # P7    1      Tone On/Off
            tone,                                # P8    1      Tone Frequency
            " "                                  # P9    14     Padding
        )

        return spec

    def _make_mem_spec(self, mem):
        return self._make_base_spec(mem, mem.freq)

    def _make_split_spec(self, mem):
        return self._make_base_spec(mem, mem.offset)
