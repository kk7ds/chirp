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

import re
from chirp import chirp_common, directory, util, errors
from chirp.drivers import kenwood_live
from chirp.drivers.kenwood_live import KenwoodLiveRadio, \
    command, iserr, NOCACHE

TS2000_SSB_STEPS = [1.0, 2.5, 5.0, 10.0]
TS2000_FM_STEPS = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]
TS2000_DUPLEX = dict(kenwood_live.DUPLEX)
TS2000_DUPLEX[3] = "="
TS2000_DUPLEX[4] = "split"
TS2000_MODES = ["?", "LSB", "USB", "CW", "FM", "AM",
                "FSK", "CWR", "?", "FSKR"]
TS2000_TMODES = ["", "Tone", "TSQL", "DTCS"]
TS2000_TONES = list(chirp_common.OLD_TONES)
TS2000_TONES.remove(69.3)


@directory.register
class TS2000Radio(KenwoodLiveRadio):
    """Kenwood TS-2000"""
    MODEL = "TS-2000"

    _upper = 289
    _kenwood_split = True
    _kenwood_valid_tones = list(TS2000_TONES)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_modes = ["LSB", "USB", "CW", "FM", "AM"]
        rf.valid_tmodes = list(TS2000_TMODES)
        rf.valid_tuning_steps = list(TS2000_SSB_STEPS + TS2000_FM_STEPS)
        rf.valid_bands = [(1000, 1300000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_duplexes = list(TS2000_DUPLEX.values())

        # TS-2000 uses ";" as a message separator even though it seems to
        # allow you to to use all printable ASCII characters at the manual
        # controls.  The radio doesn't send the name after the ";" if you
        # input one from the manual controls.
        rf.valid_characters = chirp_common.CHARSET_ASCII.replace(';', '')
        rf.valid_name_length = 7    # 7 character channel names
        rf.memory_bounds = (0, self._upper)
        return rf

    def _cmd_set_memory(self, number, spec):
        return "MW0%03i%s" % (number, spec)

    def _cmd_set_split(self, number, spec):
        return "MW1%03i%s" % (number, spec)

    def _cmd_get_memory(self, number):
        return "MR0%03i" % number

    def _cmd_get_split(self, number):
        return "MR1%03i" % number

    def _cmd_recall_memory(self, number):
        return "MC%03i" % (number)

    def _cmd_cur_memory(self, number):
        return "MC"

    def _cmd_erase_memory(self, number):
        # write a memory channel that's effectively zeroed except
        # for the channel number
        return "MW%04i%035i" % (number, 0)

    def erase_memory(self, number):
        if number not in self._memcache:
            return

        resp = command(self.pipe, *self._cmd_erase_memory(number))
        if iserr(resp):
            raise errors.RadioError("Radio refused delete of %i" % number)
        del self._memcache[number]

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
        if mem.duplex == "" and self._kenwood_split:
            result = command(self.pipe, *self._cmd_get_split(number))
            self._parse_split_spec(mem, result)

        return mem

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        # pad string so indexes match Kenwood docs
        spec = " " + spec

        # use the same variable names as the Kenwood docs
        # _p1 = spec[3]
        _p2 = spec[4]
        _p3 = spec[5:7]
        _p4 = spec[7:18]
        _p5 = spec[18]
        _p6 = spec[19]
        _p7 = spec[20]
        _p8 = spec[21:23]
        _p9 = spec[23:25]
        _p10 = spec[25:28]
        # _p11 = spec[28]
        _p12 = spec[29]
        _p13 = spec[30:39]
        _p14 = spec[39:41]
        # _p15 = spec[41]
        _p16 = spec[42:49]

        mem.number = int(_p2 + _p3)     # concat bank num and chan num

        if _p5 == '0':
            # NOTE(danms): Apparently some TS2000s will return unset
            # memory records with all zeroes for the fields instead of
            # NAKing the command with an N response. If that happens here,
            # return an empty memory.
            mem.empty = True
            return mem

        mem.freq = int(_p4)
        mem.mode = TS2000_MODES[int(_p5)]
        mem.skip = ["", "S"][int(_p6)]
        mem.tmode = TS2000_TMODES[int(_p7)]
        # PL and T-SQL are 1 indexed, DTCS is 0 indexed
        mem.rtone = self._kenwood_valid_tones[int(_p8) - 1]
        mem.ctone = self._kenwood_valid_tones[int(_p9) - 1]
        mem.dtcs = chirp_common.DTCS_CODES[int(_p10)]
        mem.duplex = TS2000_DUPLEX[int(_p12)]
        mem.offset = int(_p13)      # 9-digit
        if mem.mode in ["AM", "FM"]:
            mem.tuning_step = TS2000_FM_STEPS[int(_p14)]
        else:
            mem.tuning_step = TS2000_SSB_STEPS[int(_p14)]
        mem.name = _p16

        return mem

    def _parse_split_spec(self, mem, spec):

        # pad string so indexes match Kenwood docs
        spec = " " + spec

        # use the same variable names as the Kenwood docs
        split_freq = int(spec[7:18])
        if mem.freq != split_freq:
            mem.duplex = "split"
            mem.offset = split_freq

        return mem

    def set_memory(self, memory):
        if memory.number < 0 or memory.number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % self._upper)

        spec = self._make_mem_spec(memory)
        spec = "".join(spec)
        r1 = command(self.pipe, *self._cmd_set_memory(memory.number, spec))
        if not iserr(r1):
            memory.name = memory.name.rstrip()
            self._memcache[memory.number] = memory

            # if we're tuned to the channel, reload it
            r1 = command(self.pipe, *self._cmd_cur_memory(memory.number))
            if not iserr(r1):
                pattern = re.compile("MC([0-9]{3})")
                match = pattern.search(r1)
                if match is not None:
                    cur_mem = int(match.group(1))
                    if cur_mem == memory.number:
                        cur_mem = \
                            command(self.pipe,
                                    *self._cmd_recall_memory(memory.number))
        else:
            raise errors.InvalidDataError("Radio refused %i" % memory.number)

        # FIXME
        if memory.duplex == "split" and self._kenwood_split:
            spec = "".join(self._make_split_spec(memory))
            result = command(self.pipe, *self._cmd_set_split(memory.number,
                                                             spec))
            if iserr(result):
                raise errors.InvalidDataError("Radio refused %i" %
                                              memory.number)

    def _make_mem_spec(self, mem):
        if mem.duplex in " +-":
            duplex = util.get_dict_rev(TS2000_DUPLEX, mem.duplex)
            offset = mem.offset
        elif mem.duplex == "split":
            duplex = 0
            offset = 0
        else:
            print("Bug: unsupported duplex `%s'" % mem.duplex)
        if mem.mode in ["AM", "FM"]:
            step = TS2000_FM_STEPS.index(mem.tuning_step)
        else:
            step = TS2000_SSB_STEPS.index(mem.tuning_step)

        # TS-2000 won't accept channels with tone mode off if they have
        # tone values
        if mem.tmode == "":
            rtone = 0
            ctone = 0
            dtcs = 0
        else:
            # PL and T-SQL are 1 indexed, DTCS is 0 indexed
            rtone = (self._kenwood_valid_tones.index(mem.rtone) + 1)
            ctone = (self._kenwood_valid_tones.index(mem.ctone) + 1)
            dtcs = (chirp_common.DTCS_CODES.index(mem.dtcs))

        spec = (
            "%011i" % mem.freq,
            "%i" % (TS2000_MODES.index(mem.mode)),
            "%i" % (mem.skip == "S"),
            "%i" % TS2000_TMODES.index(mem.tmode),
            "%02i" % (rtone),
            "%02i" % (ctone),
            "%03i" % (dtcs),
            "0",    # REVERSE status
            "%i" % duplex,
            "%09i" % offset,
            "%02i" % step,
            "0",    # Memory Group number (0-9)
            "%s" % mem.name,
        )

        return spec

    def _make_split_spec(self, mem):
        if mem.duplex in " +-":
            duplex = util.get_dict_rev(TS2000_DUPLEX, mem.duplex)
        elif mem.duplex == "split":
            duplex = 0
        else:
            print("Bug: unsupported duplex `%s'" % mem.duplex)
        if mem.mode in ["AM", "FM"]:
            step = TS2000_FM_STEPS.index(mem.tuning_step)
        else:
            step = TS2000_SSB_STEPS.index(mem.tuning_step)

        # TS-2000 won't accept channels with tone mode off if they have
        # tone values
        if mem.tmode == "":
            rtone = 0
            ctone = 0
            dtcs = 0
        else:
            # PL and T-SQL are 1 indexed, DTCS is 0 indexed
            rtone = (self._kenwood_valid_tones.index(mem.rtone) + 1)
            ctone = (self._kenwood_valid_tones.index(mem.ctone) + 1)
            dtcs = (chirp_common.DTCS_CODES.index(mem.dtcs))

        spec = (
            "%011i" % mem.offset,
            "%i" % (TS2000_MODES.index(mem.mode)),
            "%i" % (mem.skip == "S"),
            "%i" % TS2000_TMODES.index(mem.tmode),
            "%02i" % (rtone),
            "%02i" % (ctone),
            "%03i" % (dtcs),
            "0",    # REVERSE status
            "%i" % duplex,
            "%09i" % 0,
            "%02i" % step,
            "0",    # Memory Group number (0-9)
            "%s" % mem.name,
        )

        return spec
