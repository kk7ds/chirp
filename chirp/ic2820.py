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

from chirp import chirp_common, icf, ic2820_ll, errors

class IC2820Radio(chirp_common.IcomMmapRadio,
                  chirp_common.IcomDstarRadio):
    _model = "\x29\x70\x00\x01"
    _memsize = 44224
    _endframe = "Icom Inc\x2e68"

    _ranges = [(0x0000, 0x6960, 32),
               (0x6960, 0x6980, 16),
               (0x6980, 0x7160, 32),
               (0x7160, 0x7180, 16),
               (0x7180, 0xACC0, 32),]

    MYCALL_LIMIT = (1, 7)
    URCALL_LIMIT = (1, 61)
    RPTCALL_LIMIT = (1, 61)

    feature_bankindex = True
    feature_req_call_lists = False

    _memories = {}

    def get_memory_upper(self):
        return 499
    
    def get_available_bank_index(self, bank):
        indexes = []
        for mem in self._memories.values():
            if mem.bank == bank and mem.bank_index >= 0:
                indexes.append(mem.bank_index)

        for i in range(0, 256):
            if i not in indexes:
                return i

        raise errors.RadioError("Out of slots in this bank")

    def get_special_locations(self):
        return sorted(ic2820_ll.IC2820_SPECIAL.keys())

    def process_mmap(self):
        self._memories = {}
        count = 500 + len(ic2820_ll.IC2820_SPECIAL.keys())
        for i in range(0, count):
            try:
                mem = ic2820_ll.get_memory(self._mmap, i)
            except errors.InvalidMemoryLocation:
                continue

            self._memories[mem.number] = mem

    def get_memory(self, number):
        if not self._mmap:
            self.sync_in()

        if isinstance(number, str):
            try:
                number = ic2820_ll.IC2820_SPECIAL[number]
            except KeyError:
                raise errors.InvalidMemoryLocation("Unknown channel %s" % \
                                                       number)
        
        try:
            return self._memories[number]
        except KeyError:
            raise errors.InvalidMemoryLocation("Location %s is empty" % number)

    def erase_memory(self, number):
        ic2820_ll.erase_memory(self._mmap, number)
        self.process_mmap()

    def get_memories(self, lo=0, hi=499):
        if not self._mmap:
            self.sync_in()

        return [m for m in self._memories.values() if m.number >= lo and m.number <= hi]

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()

        self._mmap = ic2820_ll.set_memory(self._mmap, memory)
        self._memories[memory.number] = memory

    def sync_in(self):
        self._mmap = icf.clone_from_radio(self)
        self.process_mmap()

    def sync_out(self):
        return icf.clone_to_radio(self)

    def get_raw_memory(self, number):
        return ic2820_ll.get_raw_memory(self._mmap, number)
    
    def get_banks(self):
        return ic2820_ll.get_bank_names(self._mmap)

    def set_banks(self, banks):
        return ic2820_ll.set_bank_names(self._mmap, banks)

    def get_urcall_list(self):
        calls = []

        for i in range(*self.URCALL_LIMIT):
            call = ic2820_ll.get_urcall(self._mmap, i)
            calls.append(call)

        return calls

    def get_repeater_call_list(self):
        calls = []

        for i in range(*self.RPTCALL_LIMIT):
            call = ic2820_ll.get_rptcall(self._mmap, i)
            calls.append(call)

        return calls

    def get_mycall_list(self):
        calls = []
        
        for i in range(*self.MYCALL_LIMIT):
            call = ic2820_ll.get_mycall(self._mmap, i)
            calls.append(call)

        return calls

    def set_urcall_list(self, calls):
        for i in range(*self.URCALL_LIMIT):
            try:
                call = calls[i-1]
            except IndexError:
                print "No call for %i" % i
                call = " " * 8

            ic2820_ll.set_urcall(self._mmap, i, call)


    def set_repeater_call_list(self, calls):
        for i in range(*self.RPTCALL_LIMIT):
            try:
                call = calls[i-1]
            except IndexError:
                call = " " * 8

            ic2820_ll.set_rptcall(self._mmap, i, call)

    def set_mycall_list(self, calls):
        for i in range(*self.MYCALL_LIMIT):
            try:
                call = calls[i-1]
            except IndexError:
                call = " " * 8

            ic2820_ll.set_mycall(self._mmap, i, call)
