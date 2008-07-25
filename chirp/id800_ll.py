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

import chirp_common
import errors
import util
import icf

def pack_name(_name, enabled=True):
    name = _name.ljust(8)
    nibbles = []

    def val_of(char):
        if char == " ":
            return 0
        elif char.isdigit():
            return (int(char) & 0x3F) | 0x10
        else:
            return ((ord(char) - ord("A") + 1) & 0x3F) | 0x20

    for i in range(0, len(name), 2):
        c1 = name[i]
        c2 = name[i+1]

        v1 = val_of(c1)
        v2 = val_of(c2)

        nibbles.append((v1 & 0x3F) >> 2)
        nibbles.append(((v1 & 0x03) << 2) | ((v2 & 0x30) >> 4))
        nibbles.append((v2 & 0x0F))

    if enabled:
        nibbles.insert(0, 2)
    else:
        nibbles.insert(0, 0)

    nibbles.append(0)

    val = ""

    for i in range(0, len(nibbles), 2):
        val += struct.pack("B", ((nibbles[i] << 4)| nibbles[i+1]))

    return val

def unpack_name(mem):
    nibbles = []

    for i in mem:
        nibbles.append((ord(i) & 0xF0) >> 4)
        nibbles.append(ord(i) & 0x0F)

    ln = None
    i = 1
    name = ""

    while i < len(nibbles) - 1:
        this = nibbles[i]

        if ln is None:
            i += 1
            ln = nibbles[i]
            this = (this << 2)  | ((ln >> 2) & 0x3)
        else:
            this = ((ln & 0x3) << 4) | this
            ln = None

        if this == 0:
            name += " "
        elif (this & 0x20) == 0:
            name += chr(ord("1") + (this & 0x0F) - 1)
        else:
            name += chr(ord("A") + (this & 0x1F) - 1)

        i += 1

    return name.rstrip()

def pack_frequency(freq):
    return struct.pack(">i", int((freq * 1000) / 5))[1:]

def unpack_frequency(_mem, _ts):
    mem = '\x00' + _mem

    if _ts == 0xA0 or _ts == 0x20:
        mult = 6.25
    else:
        mult = 5.0

    return ((struct.unpack(">i", mem)[0] * mult) / 1000.0)

def get_memory(map, i):
    addr = (i * 22) + 0x0020
    chunk = map[addr:addr+23]

    _freq = chunk[0:3]
    _name = chunk[11:11+8]
    _ts = ord(chunk[8]) & 0xF0

    if len(_freq) != 3:
        raise Exception("freq != 3 for %i" % i)
        
    mem = chirp_common.Memory()
    mem.number = i
    mem.name = unpack_name(_name)
    mem.freq = unpack_frequency(_freq, _ts)

    dup = struct.unpack("B", chunk[6])[0] & 0xF0
    if (dup & 0xC0) == 0xC0:
        mem.duplex = "+"
    elif (dup & 0x80) == 0x80:
        mem.duplex = "-"
    else:
        mem.duplex = ""

    mode = struct.unpack("B", chunk[-2])[0] & 0xF0
    if mode == 0x00:
        mem.mode = "FM"
    elif mode == 0x10:
        mem.mode = "NFM"
    elif mode == 0x20:
        mem.mode = "AM"
    elif mode == 0x30:
        mem.mode = "NAM"
    elif mode == 0x40:
        mem.mode = "DV"
    else:
        raise errors.InvalidDataError("Radio has invalid mode %02x" % mode)

    tone, = struct.unpack("B", chunk[5])
    mem.tone = chirp_common.TONES[tone]

    tenb, = struct.unpack("B", chunk[10])
    mem.toneEnabled = ((tenb & 0x01) != 0)

    return mem

def parse_map_for_memory(map):
    """Returns a list of memories, given a valid memory map"""

    memories = []
    
    for i in range(500):        
        mem = get_memory(map, i)
        if mem:
            memories.append(mem)

    return memories

def set_memory(map, memory):
    _fa = (memory.number * 22) + 0x0020
    _na = (memory.number * 22) + 0x0020 + 11

    freq = pack_frequency(memory.freq)
    name = pack_name(memory.name[:6])

    map = util.write_in_place(map, _fa, freq)
    map = util.write_in_place(map, _na, name)

    _dup, = struct.unpack("B", map[_fa+6])
    _dup &= 0x3F
    if memory.duplex == "-":
        _dup |= 0x80
    elif memory.duplex == "+":
        _dup |= 0xC0

    map = util.write_in_place(map, _fa+6, chr(_dup))

    _mode = memory.mode
    mode = 0
    if _mode[0] == "N":
        _mode = _mode[1:]
        mode = 0x10

    if _mode == "FM":
        mode |= 0x00
    elif _mode == "AM":
        mode |= 0x20
    elif _mode == "DV":
        mode = 0x40
    else:
        raise errors.InvalidDataError("Unsupported mode `%s'" % _mode)

    map = util.write_in_place(map, _fa+21, chr(mode))

    _tone = chirp_common.TONES.index(memory.tone)
    tone = struct.pack("B", _tone)

    map = util.write_in_place(map, _fa+5, tone)

    tenb, = struct.unpack("B", map[_fa+10])
    tenb &= 0xFE
    if memory.toneEnabled:
        tenb |= 0x01

    map = util.write_in_place(map, _fa+10, chr(tenb))

    return map

def test_basic():
    v = pack_name("DAN")
    #V = "\x28\xe8\x86\xe4\x80\x00\x00"
    V = "\x29\x21\xb8\x00\x00\x00\x00"

    if v == V:
        print "Pack name: OK"
    else:
        print "Pack name: FAIL"
        print "%s\nnot equal to\n%s" % (util.hexprint(v), util.hexprint(V))

    name = unpack_name(v)

    if name == "DAN":
        print "Unpack name: OK"
    else:
        print "Unpack name: FAIL"

    v = pack_frequency(146.520)
    V = "\x00\x72\x78"

    if v != V:
        print "Pack frequency: FAIL"
        print "%s != %s" % (list(v), list(V))
    else:
        print "Pack frequency: OK"

    freq = unpack_frequency(v)

    if freq != 146.520:
        print "Unpack frequency: FAIL"
        print "%s != %s" % (freq, 146.520)
    else:
        print "Unpack frequency: OK"


if __name__ == "__main__":

    import sys
    import serial
    import os

    test_basic()

    sys.exit(0)

    if len(sys.argv) > 2:
        mm = file(sys.argv[1], "rb")
        map = mm.read()

        #parse_map_for_memory(map)

        pipe = serial.Serial(port=sys.argv[2],
                             baudrate=9600)

        model = "\x27\x88\x02\x00"

        outlog = file("outlog", "wb", 0)

        clone_to_radio(pipe, model, map)
