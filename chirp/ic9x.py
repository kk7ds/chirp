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

import ic9x_ll

class IC9xRadio(chirp_common.IcomRadio):
    BAUD_RATE = 38400

    def get_memory(self, number, vfo=1):
        if vfo not in [1, 2]:
            raise errors.InvalidValueError("VFO must be 1 or 2")

        if number < 0 or number > 999:
            raise errors.InvalidValueError("Number must be between 0 and 999")

        ic9x_ll.send_magic(self.pipe)


        mframe = ic9x_ll.get_memory(self.pipe, vfo, number)

        mem = chirp_common.Memory()
        mem.freq = mframe._freq
        mem.number = int("%02x" % mframe._number)
        mem.name = mframe._name
        mem.vfo = mframe._vfo
        mem.duplex = mframe._duplex
        mem.mode = mframe._mode
        mem.tone = mframe._tone
        mem.toneEnabled = mframe._toneEnabled

        return mem

    def get_memories(self, vfo=1):
        memories = []

        for i in range(999):
            try:
                print "Getting %i" % i
                m = self.get_memory(i, vfo)
                memories.append(m)
            except errors.InvalidMemoryLocation:
                pass
            except errors.InvalidDataError, e:
                print "Error talking to radio: %s" % e
                break

        return memories
        
    def set_memory(self, memory):
        mframe = ic9x_ll.IC92MemoryFrame()
        mframe.set_memory(memory)
        mframe.make_raw() # FIXME
        
        result = ic9x_ll.send(self.pipe, mframe._rawdata)

        if len(result) == 0:
            raise errors.InvalidDataError("No response from radio")

        if result[0]._data != "\xfb":
            raise errors.InvalidDataError("Radio reported error")
