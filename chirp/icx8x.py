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

from chirp import chirp_common, icf, icx8x_ll

class ICx8xRadio(chirp_common.IcomMmapRadio):
    _model = "\x28\x26\x00\x01"
    _memsize = 6464
    _endframe = ""

    _memories = []

    def sync_in(self):
        self._mmap = icf.clone_from_radio(self)
        
    def sync_out(self):
        return icf.clone_to_radio(self)

    def get_memory(self, number):
        if not self._mmap:
            self.sync_in()

        return icx8x_ll.get_memory(self._mmap, number)

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()

        self._mmap = icx8x_ll.set_memory(self._mmap, memory)

    def get_raw_memory(self, number):
        return icx8x_ll.get_raw_memory(self._mmap, number)
