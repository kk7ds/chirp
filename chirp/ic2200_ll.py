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
import util
import errors
from memmap import MemoryMap

POS_FREQ_START =  0
POS_FREQ_END   =  2
POS_NAME_START =  4
POS_NAME_END   = 10
POS_MODE       = 23
POS_DUPX       = 20
POS_TONE       = 10
POS_TENB       = 19
POS_USED_START = 0x1370

MEM_LOC_SIZE = 24

def is_used(map, number):
    return map[POS_USED_START + number] != "\x7A"

def set_used(map, number, isUsed=True):
    if isUsed:
        map[POS_USED_START + number] = 0
    else:
        map[POS_USED_START + number] = 0x4A

def get_freq(map):
    val = struct.unpack("<H", map[POS_FREQ_START:POS_FREQ_END])[0]

    return (val * 5) / 1000.0

def get_name(map):
    return map[POS_NAME_START:POS_NAME_END].replace("\x0E", "").strip()

def get_mode(map):
    val = struct.unpack("B", map[POS_MODE])[0] & 0x80
    if val == 0x80:
        return "DV"
    elif val == 0x00:
        return "FM"
    else:
        raise errors.InvalidDataError("Radio has unknown mode %02x" % val)

def get_duplex(map):
    val = struct.unpack("B", map[POS_DUPX])[0] & 0x30
    if val & 0x10:
        return "-"
    elif val & 0x20:
        return "+"
    else:
        return ""

def get_tone_idx(map):
    return struct.unpack("B", map[POS_TONE])[0]

def get_tone_enabled(map):
    val = struct.unpack("B", map[POS_TENB])[0]

    return (val & 0x01) != 0

def get_memory(_map, number):
    offset = number * MEM_LOC_SIZE
    map = MemoryMap(_map[offset:offset + MEM_LOC_SIZE])

    if not is_used(_map, number):
        return None

    m = chirp_common.Memory()
    m.freq = get_freq(map)
    m.name = get_name(map)
    m.number = number
    m.mode = get_mode(map)
    m.duplex = get_duplex(map)
    m.tone = chirp_common.TONES[get_tone_idx(map)]
    m.toneEnabled = get_tone_enabled(map)

    return m

def set_freq(map, freq):
    map[POS_FREQ_START] = struct.pack("<H", int(freq * 1000) / 5)

def set_name(map, name):
    map[POS_NAME_START] = name.ljust(6)[:6]

    if name == (" " * 6):
        map[22] = 0
    else:
        map[22] = 0x10

def set_mode(map, mode):
    if mode == "FM":
        map[POS_MODE] = 0
    elif mode == "DV":
        map[POS_MODE] = 0x80
    else:
        raise errors.InvalidDataError("Unsupported mode `%s'" % mode)

def set_duplex(map, duplex):
    mask = 0xCF # ~ 00110000
    val = struct.unpack("B", map[POS_DUPX])[0] & mask

    if duplex == "-":
        val |= 0x10
    elif duplex == "+":
        val |= 0x20

    map[POS_DUPX] = val

def set_tone_enabled(map, enabled):
    mask = 0xFE # ~00000001
    val = struct.unpack("B", map[POS_TENB])[0] & mask

    if enabled:
        val |= 0x01

    map[POS_TENB] = val

def set_tone(map, index):
    map[POS_TONE] = struct.pack("B", index)    

def set_memory(_map, memory):
    offset = memory.number * MEM_LOC_SIZE
    map = MemoryMap(_map[offset:offset+MEM_LOC_SIZE])

    if not is_used(_map, memory.number):
        # Assume this is empty now, so initialize bits
        map[2] = "\x78\x00"
        map[10] = "\x08x08" + ("\x00" * 10)

    set_used(_map, memory.number, True)
    set_freq(map, memory.freq)
    set_name(map, memory.name)
    set_duplex(map, memory.duplex)
    set_mode(map, memory.mode)
    set_tone_enabled(map, memory.toneEnabled)
    set_tone(map, chirp_common.TONES.index(memory.tone))

    _map[offset] = map.get_packed()
    return _map

def parse_map_for_memory(map):
    memories = []

    for i in range(197):
        m = get_memory(map, i)
        if m:
            memories.append(m)

    return memories
