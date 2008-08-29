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


import chirp_common
import errors
import util
import icf

import id800_ll

class ID800v2Radio(chirp_common.IcomMmapRadio,
                   chirp_common.IcomDstarRadio):
    _model = "\x27\x88\x02\x00"
    _memsize = 14528
    _endframe = "Icom Inc\x2eCB"

    _memories = []

    _ranges = [(0x0020, 0x2B18, 32),
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
               (0x3180, 0x31A0, 32),
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

               (0x38A8, 0x38C0, 16),]

    MYCALL_LIMIT  = (1, 7)
    URCALL_LIMIT  = (1, 99)
    RPTCALL_LIMIT = (1, 59)

    def process_mmap(self):
        self._memories = id800_ll.parse_map_for_memory(self._mmap)

    def get_memory(self, number, vfo=None):
        if not self._mmap:
            self.sync_in()
        
        return id800_ll.get_memory(self._mmap, number)

    def get_memories(self, lo=0, hi=499):
        if not self._mmap:
            self.sync_in()

        return [m for m in self._memories if m.number >= lo and m.number <= hi]

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()

        self._mmap = id800_ll.set_memory(self._mmap, memory)

    def sync_in(self):
        self._mmap = icf.clone_from_radio(self)
        self.process_mmap()

    def sync_out(self):
        return icf.clone_to_radio(self)

    def get_raw_memory(self, number):
        return id800_ll.get_raw_memory(self._mmap, number)

    def get_urcall_list(self):
        calls = []

        for i in range(*self.URCALL_LIMIT):
            call = id800_ll.get_urcall(self._mmap, i)
            if call:
                calls.append(call)

        return calls

    def get_repeater_call_list(self):
        calls = []

        for i in range(*self.RPTCALL_LIMIT):
            call = id800_ll.get_rptcall(self._mmap, i)
            if call:
                calls.append(call)

        return calls

if __name__ == "__main__":
    import serial

    s = serial.Serial(port="/dev/ttyUSB1",
                      baudrate=9600,
                      timeout=1)

    r = ID800v2Radio(s)
    r.get_memories()

    f = file("id800.mmap", "wb")
    f.write(r._mmap)
    f.close()
