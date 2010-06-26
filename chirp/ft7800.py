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

from chirp import chirp_common, yaesu_clone, ft7800_ll

class FT7800Radio(chirp_common.IcomFileBackedRadio):
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "FT-7800"

    _memsize = 31561
    _block_lengths = [8, 31552, 1]
    _block_size = 64

    def sync_in(self):
        self._mmap = ft7800_ll.download(self)

    def sync_out(self):
        ft7800_ll.update_checksum(self._mmap)
        ft7800_ll.upload(self)

    def get_raw_memory(self, number):
        return ft7800_ll.get_raw_memory(self._mmap, number)

    def get_memory(self, number):
        return ft7800_ll.get_memory(self._mmap, number)

    def set_memory(self, number):
        return ft7800_ll.set_memory(self._mmap, number)

    def erase_memory(self, number):
        return ft7800_ll.erase_memory(self._mmap, number)
