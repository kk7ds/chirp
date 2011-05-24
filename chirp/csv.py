#!/usr/bin/python
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import os

from chirp import chirp_common, errors

class OmittedHeaderError(Exception):
    pass

class CSVRadio(chirp_common.CloneModeRadio, chirp_common.IcomDstarSupport):
    VENDOR = "CSV"
    MODEL = "Generic"

    ATTR_MAP = {
        "Location"     : (int,   "number"),
        "Name"         : (str,   "name"),
        "Frequency"    : (float, "freq"),
        "Duplex"       : (str,   "duplex"),
        "Offset"       : (float, "offset"),
        "Tone"         : (str,   "tmode"),
        "rToneFreq"    : (float, "rtone"),
        "cToneFreq"    : (float, "ctone"),
        "DtcsCode"     : (int,   "dtcs"),
        "DtcsPolarity" : (str,   "dtcs_polarity"),
        "Mode"         : (str,   "mode"),
        "TStep"        : (float, "tuning_step"),
        "Skip"         : (str,   "skip"),
        "Bank"         : (int,   "bank"),
        "Bank Index"   : (int,   "bank_index"),
        "URCALL"       : (str,   "dv_urcall"),
        "RPT1CALL"     : (str,   "dv_rpt1call"),
        "RPT2CALL"     : (str,   "dv_rpt2call"),
        }

    def _blank(self):
        self.errors = []
        self.memories = []
        for i in range(0, 1000):
            m = chirp_common.Memory()
            m.number = i
            m.empty = True
            self.memories.append(m)

    def __init__(self, pipe):
        chirp_common.CloneModeRadio.__init__(self, None)

        self._filename = pipe
        if self._filename and os.path.exists(self._filename):
            self.load()
        else:
            self._blank()

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank_index = True
        rf.requires_call_lists = False
        rf.has_implicit_calls = False
        rf.memory_bounds = (0, len(self.memories))
        rf.has_infinite_number = True

        rf.valid_modes = list(chirp_common.MODES)
        rf.valid_tmodes = list(chirp_common.TONE_MODES)
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(0.01, 10000.0)]
        rf.valid_skips = ["", "S"]
        
        return rf

    def _parse_quoted_line(self, line):
        line = line.replace("\n", "")
        line = line.replace("\r", "")
        line = line.replace('"', "")

        return line.split(",")

    def _get_datum_by_header(self, headers, data, header):
        if header not in headers:
            raise OmittedHeaderError("Header %s not provided" % header)

        try:
            return data[headers.index(header)]
        except IndexError:
            raise OmittedHeaderError("Header %s not provided on this line" %\
                                     header)

    def _parse_csv_data_line(self, headers, line):

        data = self._parse_quoted_line(line)

        mem = chirp_common.Memory()
        try:
            if self._get_datum_by_header(headers, data, "Mode") == "DV":
                mem = chirp_common.DVMemory()
        except OmittedHeaderError:
            pass

        for header, (typ, attr) in self.ATTR_MAP.items():
            try:
                val = self._get_datum_by_header(headers, data, header)
                if not val and typ == int:
                    val = None
                else:
                    val = typ(val)
                if hasattr(mem, attr):
                    setattr(mem, attr, val)
            except OmittedHeaderError, e:
                pass

        return mem

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self._blank()
        f = file(self._filename, "rU")
        
        header = f.readline().strip()
        headers = self._parse_quoted_line(header)
        lines = f.readlines()
        f.close()

        i = 1
        good = 0
        for line in lines:
            i += 1
            try:
                mem = self._parse_csv_data_line(headers, line)
                if mem.number is None:
                    raise Exception("Location field must not be empty")
                self.__grow(mem.number)
                self.memories[mem.number] = mem
                good += 1
            except Exception, e:
                print "CSV Line %i: %s" % (i, e)
                self.errors.append("Line %i: %s" % (i, e))

        if not good:
            raise errors.InvalidDataError("No channels found")

    def save(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to save to")

        if filename:
            self._filename = filename

        f = file(self._filename, "w")

        f.write(chirp_common.Memory.CSV_FORMAT + "\n")

        for mem in self.memories:
            if not mem.empty:
                f.write(mem.to_csv() + "\n")

        f.close()

    # MMAP compatibility
    def save_mmap(self, filename):
        return self.save(filename)

    def load_mmap(self, filename):
        return self.load(filename)

    def get_memories(self, lo=0, hi=999):
        return [x for x in self.memories if x.number >= lo and x.number <= hi]

    def get_memory(self, number):
        try:
            return self.memories[number]
        except:
            raise errors.InvalidMemoryLocation("No such memory %s" % number)

    def __grow(self, target):
        delta = target - len(self.memories)
        if delta < 0:
            return

        delta += 1
        
        for i in range(len(self.memories), len(self.memories) + delta + 1):
            m = chirp_common.Memory()
            m.empty = True
            m.number = i
            self.memories.append(m)

    def set_memory(self, newmem):
        self.__grow(newmem.number)
        self.memories[newmem.number] = newmem

    def erase_memory(self, number):
        m = chirp_common.Memory()
        m.number = number
        m.empty = True
        self.memories[number] = m
        
    def filter_name(self, name):
        return name
