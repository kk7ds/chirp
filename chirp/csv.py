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

class CSVRadio(chirp_common.IcomFileBackedRadio):
    feature_longnames = True

    def __init__(self, pipe):
        chirp_common.IcomFileBackedRadio.__init__(self, None)

        self.memories = []

        self._filename = pipe
        if self._filename and os.path.exists(self._filename):
            self.load()

    def get_memory_upper(self):
        return 999
            
    def _parse_csv_line(self, line):
        line = line.replace("\n", "")
        line = line.replace("\r", "")

        mem = chirp_common.Memory.from_csv(line)
        if mem:
            self.memories.append(mem)

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self.memories = []
        f = file(self._filename, "rU")
        
        header = f.readline().strip()

        if header != chirp_common.Memory.CSV_FORMAT:
            print "Got:      %s" % header
            print "Expected: %s" % chirp_common.Memory.CSV_FORMAT
            raise errors.InvalidDataError("CSV format mismatch")

        lines = f.readlines()
        f.close()

        i = 0
        for line in lines:
            i += 1
            try:
                self._parse_csv_line(line)
            except errors.InvalidMemoryLocation:
                print "Invalid memory location on line %i" % i
            except errors.InvalidDataError, e:
                raise errors.InvalidDataError("%s on line %i" % (e, i))

    def save(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to save to")

        if filename:
            self._filename = filename

        f = file(self._filename, "w")

        f.write(chirp_common.Memory.CSV_FORMAT + "\n")

        for mem in self.memories:
            f.write(mem.to_csv() + "\n")

        f.close()

    def get_memories(self, lo=0, hi=999):
        return [x for x in self.memories if x.number >= lo and x.number <= hi]

    def get_memory(self, number):
        for mem in self.memories:
            if mem.number == number:
                return mem

        raise errors.InvalidMemoryLocation("No such memory %s" % number)

    def set_memory(self, newmem):
        self.erase_memory(newmem.number)
        self.memories.append(newmem)

    def erase_memory(self, number):
        newlist = []
        for mem in self.memories:
            if mem.number != number:
                newlist.append(mem)
        self.memories = newlist
        
    def get_banks(self):
        banks = []
        for i in range(0, 26):
            banks.append("BANK%s" % (chr(ord("A") + i)))

        return banks

    def filter_name(self, name):
        return name
