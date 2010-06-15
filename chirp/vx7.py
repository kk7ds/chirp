#!/usr/bin/python
#
# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common, yaesu_clone, vx7_ll

class VX7Radio(chirp_common.IcomFileBackedRadio):
    BAUD_RATE = 19200
    VENDOR = "Yaesu"
    MODEL = "VX-7"

    _memsize = 16211
    feature_bankindex = False
    feature_longnames = True

    _block_lengths = [ 10, 8, 16193 ]
    _block_size = 8

    def get_raw_memory(self, number):
        return vx7_ll.get_raw_memory(self._mmap, number)

    def sync_in(self):
        print "Cloning in..."
        self._mmap = yaesu_clone.clone_in(self)

    def sync_out(self):
        print "Cloning out..."
        vx7_ll.update_checksum(self._mmap)
        yaesu_clone.clone_out(self)

    def get_memory(self, number):
        return vx7_ll.get_memory(self._mmap, number)

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()

        if memory.empty:
            self._mmap = vx7_ll.erase_memory(self._mmap, memory.number)
        else:
            self._mmap = vx7_ll.set_memory(self._mmap, memory)

    def get_banks(self):
        return []

    def get_memory_upper(self):
        return 450
