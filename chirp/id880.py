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


class ID880Radio(chirp_common.IcomMmapRadio,
                 chirp_common.IcomDstarRadio):
    _model = "\x31\x67\x00\x01"
    _memsize = 62976
    _endframe = "Icom Inc\x2eCB"

    feature_hash_implicit_calls = True

    def sync_in(self):
        self._mmap = icf.clone_from_radio(self)

    def sync_out(self):
        return icf.clone_to_radio(self)

    def get_raw_memory(self, number):
        return id880_ll.get_raw_memory(self._mmap, number)

    def get_memory(self, number):
        return id880_ll.get_memory(self._mmap, number)
