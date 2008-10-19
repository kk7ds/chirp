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


from chirp import chirp_common, icf, ic2200_ll

class IC2200Radio(chirp_common.IcomMmapRadio,
                  chirp_common.IcomDstarRadio):
    _model = "\x26\x98\x00\x01"
    _memsize = 6848
    _endframe = "Icom Inc\x2eD8"

    _memories = []

    _ranges = [(0x0000, 0x1340, 32),
               (0x1340, 0x1360, 16),
               (0x1360, 0x136B,  8),

               (0x1370, 0x1380, 16),
               (0x1380, 0x15E0, 32),
               (0x15E0, 0x1600, 16),
               (0x1600, 0x1640, 32),
               (0x1640, 0x1660, 16),
               (0x1660, 0x1680, 32),

               (0x16E0, 0x1860, 32),

               (0x1880, 0x1AB0, 32),

               (0x1AB8, 0x1AC0,  8),
               ]

    foo = [
               (0x1A80, 0x2B18, 32),
               (0x2B18, 0x2B20,  8),
               (0x2B20, 0x2BE0, 32),
               (0x2BE0, 0x2BF4, 20),
               (0x2BF4, 0x2C00, 12),
               (0x2C00, 0x2DE0, 32),
               (0x2DE0, 0x2DF4, 20),
               (0x2DF4, 0x2E00, 12),
               (0x2E00, 0x2E20, 32),

               (0x2F00, 0x3070, 32),

               (0x30D0, 0x30E0, 16),
               (0x30E0, 0x3160, 32),
               (0x3160, 0x3180, 16),
               (0x3180, 0x32A0, 32),
               (0x31A0, 0x31B0, 16),

               (0x3220, 0x3240, 32),
               (0x3240, 0x3260, 16),
               (0x3260, 0x3560, 32),
               (0x3560, 0x3580, 16),
               (0x3580, 0x3720, 32),
               (0x3720, 0x3780,  8),

               (0x3798, 0x37A0,  8),
               (0x37A0, 0x37B0, 16),
               (0x37B0, 0x37B1,  1),

               (0x37D8, 0x37E0,  8),
               (0x37E0, 0x3898, 32),
               (0x3898, 0x389A,  2),

               (0x38A8, 0x38C0, 16)]

    MYCALL_LIMIT  = (0, 6)
    URCALL_LIMIT  = (0, 6)
    RPTCALL_LIMIT = (0, 6)

    def process_mmap(self):
        self._memories = ic2200_ll.parse_map_for_memory(self._mmap)

    def get_memory(self, number):
        if not self._mmap:
            self.sync_in()

        return ic2200_ll.get_memory(self._mmap, number)

    def erase_memory(self, number):
        ic2200_ll.erase_memory(self._mmap, number)

    def get_memories(self, lo=0, hi=199):
        if not self._mmap:
            self.sync_in()

        return [m for m in self._memories if m.number >= lo and m.number <= hi]

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()

        self._mmap = ic2200_ll.set_memory(self._mmap, memory)

    def sync_in(self):
        self._mmap = icf.clone_from_radio(self)
        self.process_mmap()
    
    def sync_out(self):
        return icf.clone_to_radio(self)

    def get_raw_memory(self, number):
        return ic2200_ll.get_raw_memory(self._mmap, number)

    def get_urcall_list(self):
        calls = []

        for i in range(*self.URCALL_LIMIT):
            call = ic2200_ll.get_urcall(self._mmap, i)
            if call:
                calls.append(call)

        return calls

    def get_repeater_call_list(self):
        calls = []

        for i in range(*self.RPTCALL_LIMIT):
            call = ic2200_ll.get_rptcall(self._mmap, i)
            if call:
                calls.append(call)

        return calls

    def get_mycall_list(self):
        calls = []

        for i in range(*self.MYCALL_LIMIT):
            call = ic2200_ll.get_mycall(self._mmap, i)
            if call:
                calls.append(call)

        return calls

    def set_urcall_list(self, calls):
        for i in range(*self.URCALL_LIMIT):
            try:
                call = calls[i]
            except IndexError:
                call = " " * 8

            ic2200_ll.set_urcall(self._mmap, i, call)

    def set_repeater_call_list(self, calls):
        for i in range(*self.RPTCALL_LIMIT):
            try:
                call = calls[i]
            except IndexError:
                call = " " * 8

            ic2200_ll.set_rptcall(self._mmap, i, call)

    def set_mycall_list(self, calls):
        for i in range(*self.MYCALL_LIMIT):
            try:
                call = calls[i]
            except IndexError:
                call = " " * 8

            ic2200_ll.set_mycall(self._mmap, i, call)
