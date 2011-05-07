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

from chirp import chirp_common, icf, id800_ll

class ID800v2Radio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    VENDOR = "Icom"
    MODEL = "ID-800H"
    VARIANT = "v2"

    _model = "\x27\x88\x02\x00"
    _memsize = 14528
    _endframe = "Icom Inc\x2eCB"

    _memories = []

    _ranges = [(0x0020, 0x2B18, 32),
               (0x2B18, 0x2B20,  8),
               (0x2B20, 0x2BE0, 32),
               (0x2BE0, 0x2BF4, 20),
               (0x2BF4, 0x2C00, 12),
               (0x2C00, 0x2DE0, 32),
               (0x2DE0, 0x2DF4, 20),
               (0x2DF4, 0x2E00, 12),
               (0x2E00, 0x2E20, 32),

               (0x2F00, 0x3070, 32),

               (0x30D0, 0x30E0, 16),
               (0x30E0, 0x3160, 32),
               (0x3160, 0x3180, 16),
               (0x3180, 0x31A0, 32),
               (0x31A0, 0x31B0, 16),

               (0x3220, 0x3240, 32),
               (0x3240, 0x3260, 16),
               (0x3260, 0x3560, 32),
               (0x3560, 0x3580, 16),
               (0x3580, 0x3720, 32),
               (0x3720, 0x3780,  8),

               (0x3798, 0x37A0,  8),
               (0x37A0, 0x37B0, 16),
               (0x37B0, 0x37B1,  1),

               (0x37D8, 0x37E0,  8),
               (0x37E0, 0x3898, 32),
               (0x3898, 0x389A,  2),

               (0x38A8, 0x38C0, 16),]

    MYCALL_LIMIT  = (1, 7)
    URCALL_LIMIT  = (1, 99)
    RPTCALL_LIMIT = (1, 59)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_implicit_calls = True
        rf.valid_modes = id800_ll.ID800_MODES.values()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(118000000, 173995000), (230000000, 549995000),
                          (810000000, 999990000)]
        rf.valid_skips = ["", "S", "P"]
        rf.memory_bounds = (1, 499)
        return rf

    def process_mmap(self):
        self._memories = id800_ll.parse_map_for_memory(self._mmap)

    def get_special_locations(self):
        return sorted(id800_ll.ID800_SPECIAL.keys())

    def get_memory(self, number):
        if not self._mmap:
            self.sync_in()
        
        if isinstance(number, str):
            try:
                number = id800_ll.ID800_SPECIAL[number]
            except KeyError:
                raise errors.InvalidMemoryLocation("Unknown channel %s" % \
                                                       number)

        return id800_ll.get_memory(self._mmap, number)

    def get_memories(self, lo=0, hi=499):
        if not self._mmap:
            self.sync_in()

        return [m for m in self._memories if m.number >= lo and m.number <= hi]

    def set_memory(self, memory):
        if not self._mmap:
            self.sync_in()


        if memory.empty:
            self._mmap = id800_ll.erase_memory(self._mmap, memory.number)
        else:
            self._mmap = id800_ll.set_memory(self._mmap, memory)

    def sync_in(self):
        icf.IcomCloneModeRadio.sync_in(self)
        self.process_mmap()

    def get_raw_memory(self, number):
        return id800_ll.get_raw_memory(self._mmap, number)

    def get_banks(self):
        banks = []

        for i in range(0, 10):
            banks.append(chirp_common.ImmutableBank(id800_ll.bank_name(i)))

        return banks

    def set_banks(self, banks):
        raise errors.InvalidDataError("Bank naming not supported on this model")

    def get_urcall_list(self):
        calls = ["CQCQCQ"]

        for i in range(*self.URCALL_LIMIT):
            call = id800_ll.get_urcall(self._mmap, i)
            calls.append(call)

        return calls

    def get_repeater_call_list(self):
        calls = ["*NOTUSE*"]

        for i in range(*self.RPTCALL_LIMIT):
            call = id800_ll.get_rptcall(self._mmap, i)
            calls.append(call)

        return calls

    def get_mycall_list(self):
        calls = []

        for i in range(*self.MYCALL_LIMIT):
            call = id800_ll.get_mycall(self._mmap, i)
            calls.append(call)

        return calls
    
    def set_urcall_list(self, calls):
        for i in range(*self.URCALL_LIMIT):
            try:
                call = calls[i] # Skip the implicit CQCQCQ
            except IndexError:
                call = " " * 8

            id800_ll.set_urcall(self._mmap, i, call)


    def set_repeater_call_list(self, calls):
        for i in range(*self.RPTCALL_LIMIT):
            try:
                call = calls[i] # Skip the implicit blank
            except IndexError:
                call = " " * 8

            id800_ll.set_rptcall(self._mmap, i, call)
        
    def set_mycall_list(self, calls):
        for i in range(*self.MYCALL_LIMIT):
            try:
                call = calls[i-1]
            except IndexError:
                call = " " * 8

            id800_ll.set_mycall(self._mmap, i, call)
