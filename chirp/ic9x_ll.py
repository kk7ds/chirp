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

import struct

from chirp_common import IcomFrame
import chirp_common
import util
import errors
from memmap import MemoryMap

tuning_steps = {
    0 : 5.0,
    1 : 6.25,
    2 : 8.33,
    3 : 9.0,
    4 : 10.0,
    5 : 12.5,
    6 : 15,
    7 : 20,
    8 : 25,
    9 : 30,
    10: 50,
    11: 100,
    12: 125,
    13: 200
    }

tuning_steps_rev = {}
for idx, val in tuning_steps.items():
    tuning_steps_rev[val] = idx

def BCDencode(val, bigendian=True, width=None):
    digits = []
    while val != 0:
        digits.append(val % 10)
        val /= 10

    result = ""

    if len(digits) % 2 != 0:
        digits.append(0)

    while width and width > len(digits):
        digits.append(0)

    for i in range(0, len(digits), 2):
        newval = struct.pack("B", (digits[i+1] << 4) | digits[i])
        if bigendian:
            result =  newval + result
        else:
            result = result + newval
    
    return result

class IC92Frame(IcomFrame):
    def from_raw(self, data):
        if not data.startswith("\xfe\xfe"):
            raise InvalidDataError("No header");

        if not data.endswith("\xfd"):
            raise InvalidDataError("No trailer");

        self._vfo = ord(data[3])
        self._magic = ord(data[2])

        self._data = data[4:-1]
        self._rawdata = data

        self._post_proc()

    def from_frame(self, frame):
        self._vfo = frame._vfo
        self._magic = frame._magic
        self._data = frame._data
        self._rawdata = frame._rawdata

        self._post_proc()

    def _post_proc(self):
        pass

    def __init__(self):
        self._vfo = 1
        self._magic = 80
        self._data = None
        self._rawdata = None

    def _make_raw(self):
        raise Exception("Not implemented")

    def __str__(self):
        s = "Frame VFO=%i (len = %i)\n" % (self._vfo, len(self._data))
        s += hexprint(self._data)
        s += "\n"

        return s

class IC92BankFrame(IC92Frame):
    def __str__(self):
        return "Bank %s: %s" % (self._data[2], self._data[3:])

class IC92MemoryFrame(IC92Frame):
    def _post_proc(self):
        if len(self._data) < 36:
            raise errors.InvalidDataError("Frame length %i is too short",
                                          len(self._data))

        self.isDV = (len(self._data) == 62)

        map = MemoryMap(self._data[2:])

        self._name = map[26:34].rstrip()
        self._number = struct.unpack(">H", map[1:3])

        h = int("%x" % ord(map[7]))
        t = int("%x" % ord(map[6]))
        d = int("%02x%02x%02x" % (ord(map[5]),
                                  ord(map[4]),
                                  ord(map[3])))        

        self._freq = ((h * 100) + t) + (d / 1000000.0)

        tdup, = struct.unpack("B", map[22])
        if (tdup & 0x01) == 0x01:
            self._duplex = "-"
        elif (tdup & 0x02) == 0x02:
            self._duplex = "+"
        else:
            self._duplex = ""

        self._tencEnabled = self._tsqlEnabled = self._dtcsEnabled = False
            
        tval = tdup & 0x1D
        if tval == 0x00:
            pass # No tone
        elif tval == 0x04:
            self._tencEnabled = True
        elif tval == 0x0C:
            self._tsqlEnabled = True
        elif tval == 0x14:
            self._dtcsEnabled = True
        elif tval == 0x18:
            pass # TSQL-R
        elif tval == 0x1C:
            pass # DTCS-R

        polarity_values = {0x00 : "NN",
                           0x04 : "NR",
                           0x08 : "RN",
                           0x0C : "RR" }

        self._dtcsPolarity = polarity_values[ord(map[23]) & 0x0C]

        mode = struct.unpack("B", map[21])[0] & 0xF0
        if mode == 0:
            self._mode = "FM"
        elif mode == 0x10:
            self._mode = "NFM"
        elif mode == 0x30:
            self._mode = "AM"
        elif mode == 0x40:
            self._mode = "DV"
        elif mode == 0x20:
            self._mode = "WFM"
        else:
            raise errors.InvalidDataError("Radio has invalid mode %02x" % mode)

        tone = int("%02x%02x" % (ord(map[13]), ord(map[14])))
        tone /= 10.0
        if tone in chirp_common.TONES:
            self._rtone = tone
        else:
            raise errors.InvalidDataError("Radio has invalid tone %.1f" % tone)

        tone = int("%02x%02x" % (ord(map[15]), ord(map[16])))
        tone /= 10.0
        if tone in chirp_common.TONES:
            self._ctone = tone
        else:
            raise errors.InvalidDataError("Radio has invalid tone %.1f" % tone)

        dtcs = int("%02x%02x" % (ord(map[17]), ord(map[18])))
        if dtcs in chirp_common.DTCS_CODES:
            self._dtcs = dtcs
        else:
            raise errors.InvalidDataError("Radio has invalid DTCS %03i" % dtcs)

        self._offset = float("%x.%02x%02x%02x" % (ord(map[11]), ord(map[10]),
                                                  ord(map[9]),  ord(map[8])))

        index = ord(map[21]) & 0x0F
        self._ts = tuning_steps[index]               

    def make_raw(self):
        map = MemoryMap("\x00" * 60)

        # Setup an empty memory map
        map[0] = 0x01
        map[10] = "\x60\x00\x00\x08\x85\x08\x85\x00" + \
            "\x23\x22\x00\x06\x00\x00\x00\x00"
        map[36] = (" " * 16)
        map[52] = "CQCQCQ  "

        map[1] = struct.pack(">H", int("%i" % self._number, 16))
        map[3] = BCDencode(int(self._freq * 1000000), bigendian=False)

        map[26] = self._name.ljust(8)[:8]

        dup = ord(map[22]) & 0xE0
        if self._duplex == "-":
            dup |= 0x01
        elif self._duplex == "+":
            dup |= 0x02

        if self._tencEnabled:
            dup |= 0x04
        if self._tsqlEnabled:
            dup |= 0x0C
        if self._dtcsEnabled:
            dup |= 0x14

        map[22] = dup

        mode = ord(map[21]) & 0x0F
        if self._mode == "FM":
            mode |= 0
        elif self._mode == "NFM":
            mode |= 0x10
        elif self._mode == "AM":
            mode |= 0x30
        elif self._mode == "DV":
            mode |= 0x40
        elif self._mode == "WFM":
            mode |= 0x20
        else:
            raise errors.InvalidDataError("Unsupported mode `%s'" % self._mode)

        map[21] = mode

        map[13] = BCDencode(int(self._rtone * 10))
        map[15] = BCDencode(int(self._ctone * 10))
        map[17] = BCDencode(int(self._dtcs), width=4)
        
        map[8] = BCDencode(int(self._offset * 1000000),
                           bigendian=False,
                           width=6)

        val = ord(map[23]) & 0xF3
        polarity_values = { "NN" : 0x00,
                            "NR" : 0x04,
                            "RN" : 0x08,
                            "RR" : 0x0C }
        val |= polarity_values[self._dtcsPolarity]
        map[23] = val

        val = ord(map[21]) & 0xF0
        idx = tuning_steps_rev[self._ts]
        val |= idx
        map[21] = val

        self._rawdata = struct.pack("BBBB", self._vfo, 0x80, 0x1A, 0x00)
        if self._vfo == 1:
            self._rawdata += map.get_packed()[:34]
        else:
            self._rawdata += map.get_packed()

        print "Raw memory frame (%i):\n%s\n" % (\
            len(self._rawdata) - 4,
            util.hexprint(self._rawdata[4:]))

    def set_memory(self, memory, vfo):
        # This is really dumb... FIXME
        self._name = memory.name.ljust(8)[0:8]
        self._number = memory.number
        self._freq = memory.freq
        self._vfo = vfo
        self._duplex = memory.duplex
        self._offset = memory.offset
        self._mode = memory.mode
        self._rtone = memory.rtone
        self._ctone = memory.ctone
        self._dtcs = memory.dtcs
        self._dtcsPolarity = memory.dtcsPolarity
        self._tencEnabled = memory.tencEnabled
        self._tsqlEnabled = memory.tsqlEnabled
        self._dtcsEnabled = memory.dtcsEnabled
        self._ts = memory.tuningStep

    def __str__(self):
        return "%i: %.2f (%s) (DV=%s)" % (self._number,
                                          self._freq,
                                          self._name,
                                          self.isDV)

def send(pipe, buf, verbose=False):
    realbuf = "\xfe\xfe" + buf + "\xfd"

    if verbose:
        print "Sending:\n%s" % util.hexprint(realbuf)

    pipe.write(realbuf)
    pipe.flush()

    data = ""
    while True:
        buf = pipe.read(4096)
        if not buf:
            break

        data += buf

    return util.parse_frames(data)

def send_magic(pipe, verbose=False):
    magic = ("\xfe" * 400) + "\x01\x80\x19"

    send(pipe, magic, verbose)

def print_banks(pipe):
    frames = send(pipe, "\x01\x80\x1a\x09") # Banks

    print "A Banks:"
    for i in range(180, 180+26):
        bf = IC92BankFrame()
        bf.from_frame(frames[i])
        print str(bf)

    print "B Banks:"
    for i in range(237, 237+26):
        bf = IC92BankFrame()
        bf.from_frame(frames[i])
        print str(bf)

def get_memory(pipe, vfo, number):
    seq = chr(vfo) + "\x80\x1a\x00\x01" + struct.pack(">H",
                                                      int("%i" % number, 16))
    frames = send(pipe, seq)

    if len(frames) == 0:
        raise errors.InvalidDataError("No response from radio")

    if len(frames[0]._data) < 6:
        print "%s" % util.hexprint(frames[0]._data)
        raise errors.InvalidDataError("Got a short, unknown block from radio")

    if frames[0]._data[5] == '\xff':
        raise errors.InvalidMemoryLocation("Radio says location is empty")

    mf = IC92MemoryFrame()
    mf.from_frame(frames[0])

    return mf

def print_memory(pipe, vfo, number):
    if vfo not in [1, 2]:
        raise errors.InvalidValueError("VFO must be 1 or 2")

    if number < 0 or number > 399:
        raise errors.InvalidValueError("Number must be between 0 and 399")

    mf = get_memory(pipe, vfo, number)

    print "Memory %i from VFO %i: %s" % (number, vfo, str(mf))

if __name__ == "__main__":
    print util.hexprint(BCDencode(1072))
    print util.hexprint(BCDencode(146900000, False))
    print util.hexprint(BCDencode(25, width=4))
    print util.hexprint(BCDencode(5000000, False, 6))
    print util.hexprint(BCDencode(600000, False, 6))
    
