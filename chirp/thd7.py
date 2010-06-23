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

from chirp import chirp_common, errors

DEBUG = True

DUPLEX = { 0 : "", 1 : "+", 2 : "-" }
MODES = { 0 : "FM", 1 : "AM" }
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.append(100.0)

def rev(hash, value):
    reverse = {}
    for k, v in hash.items():
        reverse[v] = k

    return reverse[value]

def command(s, command, *args):
    cmd = command
    if args:
        cmd += " " + " ".join(args)
    if DEBUG:
        print "PC->D7: %s" % cmd
    s.write(cmd + "\r")

    result = ""
    while not result.endswith("\r"):
        result += s.read(8)

    if DEBUG:
        print "D7->PC: %s" % result.strip()

    return result.strip()

def get_id(s):
    return command(s, "ID")

def get_tmode(tone, ctcss, dcs):
    if dcs and int(dcs) == 1:
        return "DTCS"
    elif int(ctcss):
        return "TSQL"
    elif int(tone):
        return "Tone"
    else:
        return ""

def get_memory(s, number):
    mem = chirp_common.Memory()
    mem.number = number

    result = command(s, "MR", "0,0,%03i" % (number + 1))
    if result == "N":
        mem.empty = True
        return mem

    print result

    value = result.split(" ")[1]

    zero, split, loc, freq, step, duplex, reverse, tone_on, ctcss_on, dcs_on,\
        tone, dcs, ctcss, offset, mode, scan_locked = value.split(",")

    if True:
        print "Memory location %i:" % number
        print "    split: %s" % split
        print "    loc: %s" % loc
        print "    freq: %s" % freq
        print "    step: %s" % step
        print "    duplex: %s" % duplex
        print "    reverse: %s" % reverse
        print "    tone_on: %s" % tone_on
        print "    ctcss_on: %s" % ctcss_on
        print "    dcs_on: %s" % dcs_on
        print "    tone: %s" % tone
        print "    dcs: %s" % dcs
        print "    ctcss: %s" % ctcss
        print "    offset: %s" % offset
        print "    mode: %s" % mode
        print "    scan_locked: %s" % scan_locked

    mem.freq = int(freq) / 1000000.0
    mem.tuning_step = STEPS[int(step)]
    mem.duplex = DUPLEX[int(duplex)]
    mem.tmode = get_tmode(tone_on, ctcss_on, dcs_on)
    mem.rtone = chirp_common.TONES[int(tone) - 1]
    mem.ctone = chirp_common.TONES[int(ctcss) - 1]
    if dcs and dcs.isdigit():
        mem.dtcs = chirp_common.DTCS_CODES[int(dcs[:-1]) - 1]
    else:
        print "Unknown or invalid DCS: %s" % dcs
    if offset:
        mem.offset = int(offset) / 1000000.0
    else:
        mem.offset = 0.0
    mem.mode = MODES[int(mode)]

    result = command(s, "MNA", "0,%03i" % (number + 1))
    if " " in result:
        value = result.split(" ")[1]
        zero, loc, mem.name = value.split(",")

    return mem

def set_memory(s, mem, do_dcs):
    if mem.empty:
        raise errors.InvalidDataError("Unable to delete right now")

    if do_dcs:
        dtcs_on = int(mem.tmode == "DTCS")
        dtcs = "%03i0" % (chirp_common.DTCS_CODES.index(mem.dtcs) + 1)
    else:
        dtcs_on = dtcs = ""

    spec = "0,0,%03i,%011i,%i,%i,%i,%i,%i,%s,%02i,%s,%02i,%09i,%i,%i" % (\
        mem.number + 1,
        mem.freq * 1000000,
        STEPS.index(mem.tuning_step),
        rev(DUPLEX, mem.duplex),
        0,
        mem.tmode == "Tone",
        mem.tmode == "TSQL",
        dtcs_on,
        chirp_common.TONES.index(mem.rtone) + 1,
        dtcs,
        chirp_common.TONES.index(mem.ctone) + 1,
        mem.offset * 1000000,
        rev(MODES, mem.mode),
        0)

    result = command(s, "MW", spec)
    if result == "N":
        print "Failed to set %s" % spec
        return False

    result = command(s, "MNA", "0,%03i,%s" % (mem.number + 1, mem.name))
    return result != "N"    

class THD7xRadio(chirp_common.IcomRadio):
    BAUD_RATE = 9600
    VENDOR = "Kenwood"
    MODEL = ""

    mem_upper_limit = 200

    def __init__(self, *args, **kwargs):
        chirp_common.IcomRadio.__init__(self, *args, **kwargs)

        self.__memcache = {}

        self.__id = get_id(self.pipe)
        if " " in self.__id:
            self.__id = self.__id.split(" ")[1]
        print "Talking to a %s" % self.__id

    def get_memory(self, number):
        if number < 0 or number >= 200:
            raise errors.InvalidMemoryLocation("Number must be between 0 and 200")
        if self.__memcache.has_key(number):
            return self.__memcache[number]

        mem = get_memory(self.pipe, number)
        self.__memcache[mem.number] = mem

        return mem

    def set_memory(self, memory):
        if memory.number < 0 or memory.number >= 200:
            raise errors.InvalidMemoryLocation("Number must be between 0 and 200")
        if set_memory(self.pipe, memory, self.__id == "TM-D700"):
            self.__memcache[memory.number] = memory

    def get_memory_upper(self):
        return self.mem_upper_limit - 1

    def filter_name(self, name):
        return chirp_common.name8(name)

class THD7Radio(THD7xRadio):
    MODEL = "TH-D7(a)(g)"

if __name__ == "__main__":
    import serial
    import sys

    s = serial.Serial(port=sys.argv[1], baudrate=9600, xonxoff=True, timeout=1)

    print get_id(s)
    print get_memory(s, int(sys.argv[2]))

