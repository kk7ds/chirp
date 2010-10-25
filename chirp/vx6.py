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

from chirp import chirp_common, yaesu_clone, vx6_ll

class VX6Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 19200
    VENDOR = "Yaesu"
    MODEL = "VX-6"

    _memsize = 32587
    _block_lengths = [10, 32578]
    _block_size = 16

    def _update_checksum(self):
        vx6_ll.update_checksum(self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.valid_modes = ["FM", "WFM", "AM"]
        rf.memory_bounds = (1, 900)
        rf.can_odd_split = True
        return rf

    def get_raw_memory(self, number):
        return vx6_ll.get_raw_memory(self._mmap, number)

    def get_memory(self, number):
        return vx6_ll.get_memory(self._mmap, number)

    def set_memory(self, mem):
        return vx6_ll.set_memory(self._mmap, mem)

    def erase_memory(self, number):
        return vx6_ll.erase_memory(self._mmap, number)
