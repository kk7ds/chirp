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

from chirp.chirp_common import IcomFrame
from chirp import chirp_common, util, errors
from chirp.memmap import MemoryMap

TUNING_STEPS = {
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

TUNING_STEPS_REV = {}
for __idx, __val in TUNING_STEPS.items():
    TUNING_STEPS_REV[__val] = __idx

def bcd_encode(val, bigendian=True, width=None):
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
            raise errors.InvalidDataError("No header")

        if not data.endswith("\xfd"):
            raise errors.InvalidDataError("No trailer")

        self._vfo = ord(data[3])
        self._magic = ord(data[2])

        self._data = data[4:-1]
        self._rawdata = data

        self._post_proc()

    def from_frame(self, frame):
        # pylint: disable-msg=W0212
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

    def get_data(self):
        return self._data

    def _make_raw(self):
        # pylint: disable-msg=R0201
        raise Exception("Not implemented")

    def __str__(self):
        string = "Frame VFO=%i (len = %i)\n" % (self._vfo, len(self._data))
        string += util.hexprint(self._data)
        string += "\n"

        return string

    def send(self, pipe, verbose=False):
        self._make_raw()
        return send(pipe, self._rawdata, verbose)

class IC92BankFrame(IC92Frame):
    def __str__(self):
        return "Bank %s: %s" % (self._data[2], self._data[3:])

class IC92MemClearFrame(IC92Frame):
    def __init__(self, vfo, number):
        IC92Frame.__init__(self)
        self._number = number
        self._vfo = vfo

    def _make_raw(self):
        self._rawdata = struct.pack("BBBB", self._vfo, 0x80, 0x1A, 0x00)
        self._rawdata += struct.pack(">BHB",
                                     0x01,
                                     int("%i" % self._number, 16),
                                     0xFF)

class IC92CallsignFrame(IC92Frame):
    command = 0 # Invalid

    def __init__(self, number=0, callsign=""):
        IC92Frame.__init__(self)
        self._number = number
        if callsign:
            callsign = callsign.ljust(8)
        self.callsign = callsign

    def _make_raw(self):
        self._rawdata = struct.pack("BBBB", 2, 0x80, 0x1D, self.command)
        self._rawdata += struct.pack("B", self._number)
        self._rawdata += self.callsign

    def get_callsign(self):
        return self._data[3:11].rstrip()

class IC92YourCallsignFrame(IC92CallsignFrame):
    command = 6 # Your

class IC92RepeaterCallsignFrame(IC92CallsignFrame):
    command = 7 # Repeater

class IC92MyCallsignFrame(IC92CallsignFrame):
    command = 8 # My

    def __init__(self, number=0, callsign=""):
        if callsign:
            callsign = callsign.ljust(12)

        IC92CallsignFrame.__init__(self, number, callsign)

class IC92MemoryFrame(IC92Frame):
    def __init__(self):
        IC92Frame.__init__(self)

        self.is_dv = False
        self._dtcs_polarity = "NN"
        self._ts = 5.0
        self._rtone = 88.5
        self._ctone = 88.5
        self._dtcs = 23
        self._duplex = ""
        self._urcall = "CQCQCQ"
        self._tmode = ""
        self._mode = "FM"
        self._freq = "146.010"
        self._name = ""
        self._offset = 0
        self._rpt1call = ""
        self._rpt2call = ""
        self._number = -1

    def _post_proc(self):
        if len(self._data) < 36:
            raise errors.InvalidDataError("Frame length %i is too short",
                                          len(self._data))

        self.is_dv = (len(self._data) == 62)

        mmap = MemoryMap(self._data[2:])

        self._name = mmap[26:34].rstrip()
        self._number = struct.unpack(">H", mmap[1:3])

        hun = int("%x" % ord(mmap[7]))
        ten = int("%x" % ord(mmap[6]))
        dec = int("%02x%02x%02x" % (ord(mmap[5]),
                                    ord(mmap[4]),
                                    ord(mmap[3])))        

        self._freq = ((hun * 100) + ten) + (dec / 1000000.0)

        tdup, = struct.unpack("B", mmap[22])
        if (tdup & 0x01) == 0x01:
            self._duplex = "-"
        elif (tdup & 0x02) == 0x02:
            self._duplex = "+"
        else:
            self._duplex = ""

        tval = tdup & 0x1C
        if tval == 0x00:
            self._tmode = ""
        elif tval == 0x04:
            self._tmode = "Tone"
        elif tval == 0x0C:
            self._tmode = "TSQL"
        elif tval == 0x14:
            self._tmode = "DTCS"
        elif tval == 0x18:
            self._tmode = "" # TSQL-R
        elif tval == 0x1C:
            self._tmode = "" # DTCS-R

        polarity_values = {0x00 : "NN",
                           0x04 : "NR",
                           0x08 : "RN",
                           0x0C : "RR" }

        self._dtcs_polarity = polarity_values[ord(mmap[23]) & 0x0C]

        mode = struct.unpack("B", mmap[21])[0] & 0xF0
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

        tone = int("%02x%02x" % (ord(mmap[13]), ord(mmap[14])))
        tone /= 10.0
        if tone in chirp_common.TONES:
            self._rtone = tone
        else:
            raise errors.InvalidDataError("Radio has invalid tone %.1f" % tone)

        tone = int("%02x%02x" % (ord(mmap[15]), ord(mmap[16])))
        tone /= 10.0
        if tone in chirp_common.TONES:
            self._ctone = tone
        else:
            raise errors.InvalidDataError("Radio has invalid tone %.1f" % tone)

        dtcs = int("%02x%02x" % (ord(mmap[17]), ord(mmap[18])))
        if dtcs in chirp_common.DTCS_CODES:
            self._dtcs = dtcs
        else:
            raise errors.InvalidDataError("Radio has invalid DTCS %03i" % dtcs)

        self._offset = float("%x.%02x%02x%02x" % (ord(mmap[11]), ord(mmap[10]),
                                                  ord(mmap[9]),  ord(mmap[8])))

        index = ord(mmap[21]) & 0x0F
        self._ts = TUNING_STEPS[index]               

        if self.is_dv:
            self._rpt2call = mmap[36:43].strip()
            self._rpt1call = mmap[44:51].strip()
            self._urcall = mmap[52:60].strip()

    def _make_raw(self):
        mmap = MemoryMap("\x00" * 60)

        # Setup an empty memory map
        mmap[0] = 0x01
        mmap[10] = "\x60\x00\x00\x08\x85\x08\x85\x00" + \
            "\x23\x22\x00\x06\x00\x00\x00\x00"
        mmap[36] = (" " * 16)
        mmap[52] = "CQCQCQ  "

        mmap[1] = struct.pack(">H", int("%i" % self._number, 16))
        mmap[3] = bcd_encode(int(self._freq * 1000000), bigendian=False)

        mmap[26] = self._name.ljust(8)[:8]

        dup = ord(mmap[22]) & 0xE0
        if self._duplex == "-":
            dup |= 0x01
        elif self._duplex == "+":
            dup |= 0x02

        if self._tmode == "Tone":
            dup |= 0x04
        elif self._tmode == "TSQL":
            dup |= 0x0C
        elif self._tmode == "DTCS":
            dup |= 0x14

        mmap[22] = dup

        mode = ord(mmap[21]) & 0x0F
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

        mmap[21] = mode

        mmap[13] = bcd_encode(int(self._rtone * 10))
        mmap[15] = bcd_encode(int(self._ctone * 10))
        mmap[17] = bcd_encode(int(self._dtcs), width=4)
        
        mmap[8] = bcd_encode(int(self._offset * 1000000),
                           bigendian=False,
                           width=6)

        val = ord(mmap[23]) & 0xF3
        polarity_values = { "NN" : 0x00,
                            "NR" : 0x04,
                            "RN" : 0x08,
                            "RR" : 0x0C }
        val |= polarity_values[self._dtcs_polarity]
        mmap[23] = val

        val = ord(mmap[21]) & 0xF0
        idx = TUNING_STEPS_REV[self._ts]
        val |= idx
        mmap[21] = val

        if self._vfo == 2:
            mmap[36] = self._rpt2call.ljust(8)
            mmap[44] = self._rpt1call.ljust(8)
            mmap[52] = self._urcall.ljust(8)

        self._rawdata = struct.pack("BBBB", self._vfo, 0x80, 0x1A, 0x00)
        if self._vfo == 1:
            self._rawdata += mmap.get_packed()[:34]
        else:
            self._rawdata += mmap.get_packed()

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
        self._dtcs_polarity = memory.dtcs_polarity
        self._tmode = memory.tmode
        self._ts = memory.tuning_step

        if isinstance(memory, chirp_common.DVMemory) and vfo == 2:
            self._urcall = memory.dv_urcall
            self._rpt1call = memory.dv_rpt1call
            self._rpt2call = memory.dv_rpt2call
        else:
            self._urcall = self._rpt1call = self._rpt2call = ""

    def get_memory(self):
        if self.is_dv:
            mem = chirp_common.DVMemory()
            mem.dv_urcall = self._urcall
            mem.dv_rpt1call = self._rpt1call
            mem.dv_rpt2call = self._rpt2call
        else:
            mem = chirp_common.Memory()

        mem.freq = self._freq
        mem.number = int("%02x" % self._number)
        mem.name = self._name
        mem.duplex = self._duplex
        mem.offset = self._offset
        mem.mode = self._mode
        mem.rtone = self._rtone
        mem.ctone = self._ctone
        mem.dtcs = self._dtcs
        mem.dtcs_polarity = self._dtcs_polarity

        mem.tmode = self._tmode
        mem.tuning_step = self._ts
        
        return mem

    def __str__(self):
        return "%i: %.2f (%s) (DV=%s)" % (self._number,
                                          self._freq,
                                          self._name,
                                          self.is_dv)

def parse_frames(buf):
    frames = []

    while "\xfe\xfe" in buf:
        try:
            start = buf.index("\xfe\xfe")
            end = buf[start:].index("\xfd") + start + 1
        except Exception, e:
            print "No trailing bit"
            break

        framedata = buf[start:end]
        buf = buf[end:]

        try:
            frame = IC92Frame()
            frame.from_raw(framedata)
            frames.append(frame)
        except errors.InvalidDataError, e:
            print "Broken frame: %s" % e

        #print "Parsed %i frames" % len(frames)

    return frames

def print_frames(frames):
    count = 0
    for i in frames:
        print "Frame %i:" % count
        print i
        count += 1


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

    return parse_frames(data)

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

    if len(frames[0].get_data()) < 6:
        print "%s" % util.hexprint(frames[0].get_data())
        raise errors.InvalidDataError("Got a short, unknown block from radio")

    if frames[0].get_data()[5] == '\xff':
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
    print util.hexprint(bcd_encode(1072))
    print util.hexprint(bcd_encode(146900000, False))
    print util.hexprint(bcd_encode(25, width=4))
    print util.hexprint(bcd_encode(5000000, False, 6))
    print util.hexprint(bcd_encode(600000, False, 6))
    
