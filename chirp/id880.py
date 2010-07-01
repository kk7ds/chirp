#!/usr/bin/python
#
# Copyright 2009 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common, icf, id880_ll


class ID880Radio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    VENDOR = "Icom"
    MODEL = "ID-880H"

    _model = "\x31\x67\x00\x01"
    _memsize = 62976
    _endframe = "Icom Inc\x2eB1"

    _ranges = [(0x0000, 0xF5c0, 32),
               (0xF5c0, 0xf5e0, 16),
               (0xf5e0, 0xf600, 32)]

    MYCALL_LIMIT = (1, 7)
    URCALL_LIMIT = (1, 60)
    RPTCALL_LIMIT = (1, 99)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.requires_call_lists = True
        rf.has_bank_index = True
        rf.valid_modes = [x for x in id880_ll.ID880_MODES if x is not None]
        return rf

    def get_available_bank_index(self, bank):
        indexes = []
        for i in range(0, 1000):
            try:
                mem = self.get_memory(i)
            except:
                continue
            if mem.bank == bank and mem.bank_index >= 0:
                indexes.append(mem.bank_index)

        for i in range(0, 99):
            if i not in indexes:
                return i

        raise errors.RadioError("Out of slots in this bank")

    def get_raw_memory(self, number):
        return id880_ll.get_raw_memory(self._mmap, number)

    def get_banks(self):
        return id880_ll.get_bank_names(self._mmap)

    def set_banks(self, banks):
        return id880_ll.set_bank_names(self._mmap, banks)

    def get_memory(self, number):
        return id880_ll.get_memory(self._mmap, number)

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()

        if memory.empty:
            self._mmap = id880_ll.erase_memory(self._mmap, memory.number)
        else:
            self._mmap = id880_ll.set_memory(self._mmap, memory)

    def get_urcall_list(self):
        calls = ["CQCQCQ"]

        for i in range(*self.URCALL_LIMIT):
            call = id880_ll.get_urcall(self._mmap, i)
            calls.append(call)

        return calls

    def get_mycall_list(self):
        calls = []

        for i in range(*self.MYCALL_LIMIT):
            call = id880_ll.get_mycall(self._mmap, i)
            calls.append(call)

        return calls

    def get_repeater_call_list(self):
        calls = ["*NOTUSE*"]

        for i in range(*self.RPTCALL_LIMIT):
            call = id880_ll.get_rptcall(self._mmap, i)
            calls.append(call)

        return calls
        
    def get_memory_upper(self):
        return 999

    def filter_name(self, name):
        return chirp_common.name8(name, just_upper=True)
