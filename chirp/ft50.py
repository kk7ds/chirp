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

from chirp import chirp_common, yaesu_clone, ft50_ll, directory

# Not working, don't register
#@directory.register
class FT50Radio(yaesu_clone.YaesuCloneModeRadio):
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "FT-50"

    _memsize = 3723
    _block_lengths = [10, 16, 112, 16, 16, 1776, 1776, 1]
    _block_delay = 0.15

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 100)
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.valid_modes = [ "FM", "WFM", "AM" ]
        return rf

    def _update_checksum(self):
        ft50_ll.update_checksum(self._mmap)

    def get_raw_memory(self, number):
        return ft50_ll.get_raw_memory(self._mmap, number)

    def get_memory(self, number):
        return ft50_ll.get_memory(self._mmap, number)

    def set_memory(self, number):
        return ft50_ll.set_memory(self._mmap, number)

    def erase_memory(self, number):
        return ft50_ll.erase_memory(self._mmap, number)

    def filter_name(self, name):
        return name[:4].upper()
