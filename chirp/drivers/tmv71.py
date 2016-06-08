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

from chirp import chirp_common, errors, util
from chirp.drivers import tmv71_ll
import logging

LOG = logging.getLogger(__name__)


class TMV71ARadio(chirp_common.CloneModeRadio):
    BAUD_RATE = 9600
    VENDOR = "Kenwood"
    MODEL = "TM-V71A"

    mem_upper_limit = 1022
    _memsize = 32512
    _model = ""  # FIXME: REMOVE

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 999)
        return rf

    def _detect_baud(self):
        for baud in [9600, 19200, 38400, 57600]:
            self.pipe.baudrate = baud
            self.pipe.write("\r\r")
            self.pipe.read(32)
            try:
                id = tmv71_ll.get_id(self.pipe)
                LOG.info("Radio %s at %i baud" % (id, baud))
                return True
            except errors.RadioError:
                pass

        raise errors.RadioError("No response from radio")

    def get_raw_memory(self, number):
        return util.hexprint(tmv71_ll.get_raw_mem(self._mmap, number))

    def get_special_locations(self):
        return sorted(tmv71_ll.V71_SPECIAL.keys())

    def get_memory(self, number):
        if isinstance(number, str):
            try:
                number = tmv71_ll.V71_SPECIAL[number]
            except KeyError:
                raise errors.InvalidMemoryLocation("Unknown channel %s" %
                                                   number)

        return tmv71_ll.get_memory(self._mmap, number)

    def set_memory(self, mem):
        return tmv71_ll.set_memory(self._mmap, mem)

    def erase_memory(self, number):
        tmv71_ll.set_used(self._mmap, number, 0)

    def sync_in(self):
        self._detect_baud()
        self._mmap = tmv71_ll.download(self)

    def sync_out(self):
        self._detect_baud()
        tmv71_ll.upload(self)
