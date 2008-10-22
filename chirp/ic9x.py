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

import time

from chirp import chirp_common, errors, memmap, ic9x_ll

class IC9xRadio(chirp_common.IcomRadio):
    BAUD_RATE = 38400
    vfo = 0
    __last = 0
    mem_upper_limit = 300

    def __init__(self, *args, **kwargs):
        chirp_common.IcomRadio.__init__(self, *args, **kwargs)

        self.__memcache = {}
    
    def get_memory(self, number):
        if number < 0 or number > 999:
            raise errors.InvalidValueError("Number must be between 0 and 999")

        if self.__memcache.has_key(number):
            return self.__memcache[number]

        if (time.time() - self.__last) > 0.5:
            ic9x_ll.send_magic(self.pipe)
        self.__last = time.time()

        mframe = ic9x_ll.get_memory(self.pipe, self.vfo, number)

        m = mframe.get_memory()

        self.__memcache[m.number] = m

        return m

    def erase_memory(self, number):
        eframe = ic9x_ll.IC92MemClearFrame(self.vfo, number)

        ic9x_ll.send_magic(self.pipe)

        result = eframe.send(self.pipe)

        if len(result) == 0:
            raise errors.InvalidDataError("No response from radio")

        if result[0].get_data() != "\xfb":
            raise errors.InvalidDataError("Radio reported error")

        del self.__memcache[number]

    def get_raw_memory(self, number):
        ic9x_ll.send_magic(self.pipe)
        mframe = ic9x_ll.get_memory(self.pipe, self.vfo, number)

        return memmap.MemoryMap(mframe.get_data()[2:])

    def get_memories(self, lo=0, hi=None):
        if hi is None:
            hi = self.mem_upper_limit            

        memories = []

        for i in range(lo, hi+1):
            try:
                print "Getting %i" % i
                mem = self.get_memory(i)
                if mem:
                    memories.append(mem)
                print "Done: %s" % mem
            except errors.InvalidMemoryLocation:
                pass
            except errors.InvalidDataError, e:
                print "Error talking to radio: %s" % e
                break

        return memories
        
    def set_memory(self, memory):
        mframe = ic9x_ll.IC92MemoryFrame()
        ic9x_ll.send_magic(self.pipe)
        mframe.set_memory(memory, self.vfo)
        
        result = mframe.send(self.pipe)

        if len(result) == 0:
            raise errors.InvalidDataError("No response from radio")

        if result[0].get_data() != "\xfb":
            raise errors.InvalidDataError("Radio reported error")

        self.__memcache[memory.number] = memory

class IC9xRadioA(IC9xRadio):
    vfo = 1
    mem_upper_limit = 849

class IC9xRadioB(IC9xRadio, chirp_common.IcomDstarRadio):
    vfo = 2
    mem_upper_limit = 399

    MYCALL_LIMIT = (1, 7)
    URCALL_LIMIT = (1, 61)
    RPTCALL_LIMIT = (1, 61)

    def __init__(self, *args, **kwargs):
        IC9xRadio.__init__(self, *args, **kwargs)

        self.__rcalls = []
        self.__mcalls = []
        self.__ucalls = []

    def __get_call_list(self, cache, cstype, ulimit):
        if cache:
            return cache

        ic9x_ll.send_magic(self.pipe)

        for i in range(ulimit - 1):
            cframe = cstype(i)
            result = cframe.send(self.pipe)

            callf = ic9x_ll.IC92CallsignFrame()
            try:
                callf.from_frame(result[0])
            except IndexError:
                raise errors.RadioError("No response from radio")

            if callf.get_callsign():
                cache.append(callf.get_callsign())

        return cache

    def __set_call_list(self, cache, cstype, ulimit, calls):
        sent_magic = False

        for i in range(ulimit - 1):
            blank = " " * 8

            try:
                acall = cache[i]
            except IndexError:
                acall = blank

            try:
                bcall = calls[i]
            except IndexError:
                bcall = blank
            
            if acall == bcall:
                continue # No change to this one

            if not sent_magic:
                ic9x_ll.send_magic(self.pipe)
                sent_magic = True

            cframe = cstype(i+1, bcall)
            result = cframe.send(self.pipe)

            if result[0].get_data() != "\xfb":
                raise errors.RadioError("Radio reported error")

        return calls

    def get_mycall_list(self):
        self.__mcalls = self.__get_call_list(self.__mcalls,
                                             ic9x_ll.IC92MyCallsignFrame,
                                             self.MYCALL_LIMIT[1])
        return self.__mcalls
        
    def get_urcall_list(self):
        self.__ucalls = self.__get_call_list(self.__ucalls,
                                             ic9x_ll.IC92YourCallsignFrame,
                                             self.URCALL_LIMIT[1])
        return self.__ucalls

    def get_repeater_call_list(self):
        self.__rcalls = self.__get_call_list(self.__rcalls,
                                             ic9x_ll.IC92RepeaterCallsignFrame,
                                             self.RPTCALL_LIMIT[1])
        return self.__rcalls

    def set_mycall_list(self, calls):
        self.__mcalls = self.__set_call_list(self.__mcalls,
                                             ic9x_ll.IC92MyCallsignFrame,
                                             self.MYCALL_LIMIT[1],
                                             calls)

    def set_urcall_list(self, calls):
        self.__ucalls = self.__set_call_list(self.__ucalls,
                                             ic9x_ll.IC92YourCallsignFrame,
                                             self.URCALL_LIMIT[1],
                                             calls)

    def set_repeater_call_list(self, calls):
        self.__rcalls = self.__set_call_list(self.__rcalls,
                                             ic9x_ll.IC92RepeaterCallsignFrame,
                                             self.RPTCALL_LIMIT[1],
                                             calls)

if __name__ == "__main__":
    def test():
        import serial
        import util
        r = IC9xRadioB(serial.Serial(port="/dev/ttyUSB1",
                                     baudrate=38400, timeout=0.1))
        print r.get_urcall_list()
        #r.set_urcall_list(["K7TAY", "FOOBAR"])
        print "-- FOO --"
        r.set_urcall_list(["K7TAY", "FOOBAR", "BAZ"])

    test()
