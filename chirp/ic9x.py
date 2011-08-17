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
import threading

from chirp import chirp_common, errors, memmap, ic9x_ll, util, icf

IC9xA_SPECIAL = {}
IC9xA_SPECIAL_REV = {}
IC9xB_SPECIAL = {}
IC9xB_SPECIAL_REV = {}

for i in range(0, 25):
    idA = "%iA" % i
    idB = "%iB" % i
    Anum = 800 + i * 2
    Bnum = 400 + i * 2

    IC9xA_SPECIAL[idA] = Anum
    IC9xA_SPECIAL[idB] = Bnum
    IC9xA_SPECIAL_REV[Anum] = idA
    IC9xA_SPECIAL_REV[Bnum] = idB

    IC9xB_SPECIAL[idA] = Bnum
    IC9xB_SPECIAL[idB] = Bnum + 1
    IC9xB_SPECIAL_REV[Bnum] = idA
    IC9xB_SPECIAL_REV[Bnum+1] = idB

IC9xA_SPECIAL["C0"] = IC9xB_SPECIAL["C0"] = -1
IC9xA_SPECIAL["C1"] = IC9xB_SPECIAL["C1"] = -2

IC9xA_SPECIAL_REV[-1] = IC9xB_SPECIAL_REV[-1] = "C0"
IC9xA_SPECIAL_REV[-2] = IC9xB_SPECIAL_REV[-2] = "C1"

IC9x_SPECIAL = {
    1 : IC9xA_SPECIAL,
    2 : IC9xB_SPECIAL,
}

IC9x_SPECIAL_REV = {
    1 : IC9xA_SPECIAL_REV,
    2 : IC9xB_SPECIAL_REV,
}

LOCK = threading.Lock()

class IC9xRadio(icf.IcomLiveRadio):
    MODEL = "IC-91/92AD"

    _model = "ic9x" # Fake model info for detect.py
    vfo = 0
    __last = 0
    _upper = 300

    def __init__(self, *args, **kwargs):
        chirp_common.LiveRadio.__init__(self, *args, **kwargs)

        if self.pipe:
            self.pipe.setTimeout(0.1)

        self.__memcache = {}
        self.__bankcache = {}

        global LOCK
        self._lock = LOCK

    def _maybe_send_magic(self):
        if (time.time() - self.__last) > 1:
            print "Sending magic"
            ic9x_ll.send_magic(self.pipe)
        self.__last = time.time()

    def get_available_bank_index(self, bank):
        indexes = []
        for mem in self.__memcache.values():
            if mem.bank == bank and mem.bank_index >= 0:
                indexes.append(mem.bank_index)

        print "Index list for %i: %s" % (bank, indexes)

        for i in range(0, 99):
            if i not in indexes:
                return i

        raise errors.RadioError("Out of slots in this bank")

    def get_special_locations(self):
        return sorted(IC9x_SPECIAL[self.vfo].keys())
    
    def get_memory(self, number):
        if isinstance(number, str):
            try:
                number = IC9x_SPECIAL[self.vfo][number]
            except KeyError:
                raise InvalidMemoryLocation("Unknown channel %s" % number)

        if number < -2 or number > 999:
            raise errors.InvalidValueError("Number must be between 0 and 999")

        if self.__memcache.has_key(number):
                return self.__memcache[number]

        self._lock.acquire()
        try:
            self._maybe_send_magic()
            mem = ic9x_ll.get_memory(self.pipe, self.vfo, number)
        except errors.InvalidMemoryLocation:
            mem = chirp_common.Memory()
            mem.number = number
            if number < self._upper:
                mem.empty = True
        except:
            self._lock.release()
            raise

        self._lock.release()

        if number > self._upper or number < 0:
            mem.extd_number = IC9x_SPECIAL_REV[self.vfo][number]
            mem.immutable = ["number", "skip", "bank", "bank_index",
                             "extd_number"]

        self.__memcache[mem.number] = mem

        return mem

    def get_raw_memory(self, number):
        self._lock.acquire()
        try:
            ic9x_ll.send_magic(self.pipe)
            mframe = ic9x_ll.get_memory_frame(self.pipe, self.vfo, number)
        except:
            self._lock.release()
            raise

        self._lock.release()

        return memmap.MemoryMap(mframe.get_payload())

    def get_memories(self, lo=0, hi=None):
        if hi is None:
            hi = self._upper            

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
        self._lock.acquire()
        self._maybe_send_magic()
        try:
           if memory.empty:
               ic9x_ll.erase_memory(self.pipe, self.vfo, memory.number)
           else:
               ic9x_ll.set_memory(self.pipe, self.vfo, memory)
        except:
            self._lock.release()
            raise

        self._lock.release()

        self.__memcache[memory.number] = memory

    def get_banks(self):
        if len(self.__bankcache.keys()) == 26:
            return [self.__bankcache[k] for k in sorted(self.__bankcache.keys())]

        self._lock.acquire()
        try:
            self._maybe_send_magic()
            banks = ic9x_ll.get_banks(self.pipe, self.vfo)
        except:
            self._lock.release()
            raise

        self._lock.release()

        i = 0
        for bank in banks:
            self.__bankcache[i] = bank
            i += 1

        return banks
        
    def set_banks(self, banks):

        if len(banks) != len(self.__bankcache.keys()):
            raise errors.InvalidDataError("Invalid bank list length (%i:%i)" %\
                                              (len(banks),
                                               len(self.__bankcache.keys())))

        cached_names = [str(self.__bankcache[x]) \
                            for x in sorted(self.__bankcache.keys())]

        need_update = False
        for i in range(0, 26):
            if banks[i] != cached_names[i]:
                need_update = True
                self.__bankcache[i] = banks[i]
                print "Updating %s: %s -> %s" % (chr(i + ord("A")),
                                                 cached_names[i],
                                                 banks[i])

        if need_update:
            self._lock.acquire()
            try:
                self._maybe_send_magic()
                ic9x_ll.set_banks(self.pipe, self.vfo, banks)
            except:
                self._lock.release()
                raise

            self._lock.release()

    def get_sub_devices(self):
        return [IC9xRadioA(self.pipe), IC9xRadioB(self.pipe)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_sub_devices = True
        return rf

class IC9xRadioA(IC9xRadio):
    VARIANT = "Band A"
    vfo = 1
    _upper = 849

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank_index = True
        rf.memory_bounds = (0, self._upper)
        rf.valid_modes = ["FM", "WFM", "AM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(500000, 9990000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 8
        return rf

class IC9xRadioB(IC9xRadio, chirp_common.IcomDstarSupport):
    VARIANT = "Band B"
    vfo = 2
    _upper = 399

    MYCALL_LIMIT = (1, 7)
    URCALL_LIMIT = (1, 61)
    RPTCALL_LIMIT = (1, 61)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank_index = True
        rf.requires_call_lists = False
        rf.memory_bounds = (0, self._upper)
        rf.valid_modes = ["FM", "NFM", "AM", "DV"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(118000000, 174000000), (350000000, 470000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 8
        return rf

    def __init__(self, *args, **kwargs):
        IC9xRadio.__init__(self, *args, **kwargs)

        self.__rcalls = []
        self.__mcalls = []
        self.__ucalls = []

    def __get_call_list(self, cache, cstype, ulimit):
        if cache:
            return cache

        calls = []

        self._maybe_send_magic()
        for i in range(ulimit-1):
            call = ic9x_ll.get_call(self.pipe, cstype, i+1)
            calls.append(call)

        return calls

    def __set_call_list(self, cache, cstype, ulimit, calls):
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

            self._maybe_send_magic()
            ic9x_ll.set_call(self.pipe, cstype, i+1, calls[i])

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
