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

from chirp import chirp_common, util, errors
from chirp.memmap import MemoryMap

POS_FREQ_START =  0
POS_FREQ_END   =  2
POS_NAME_START =  4
POS_NAME_END   = 10
POS_MODE       = 23
POS_DUPX       = 20
POS_DOFF       =  2
POS_RTONE      = 10
POS_CTONE      = 11
POS_DTCS       = 12
POS_DTCS_POL   = 21
POS_TENB       = 19
POS_USED_START = 0x1370

MEM_LOC_SIZE = 24

def is_used(map, number):
    return (ord(map[POS_USED_START + number]) & 0x20) == 0

def set_used(map, number, isUsed=True):
    val = ord(map[POS_USED_START + number]) & 0x0F

    if not isUsed:
        val |= 0x20

    map[POS_USED_START + number] = val

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

def get_dup_offset(map):
    val = struct.unpack("B", map[POS_DOFF])[0]

    return float(val * 5.0) / 1000.0

def get_rtone(map):
    idx = struct.unpack("B", map[POS_RTONE])[0]

    return chirp_common.TONES[idx]

def get_ctone(map):
    idx = struct.unpack("B", map[POS_CTONE])[0]

    return chirp_common.TONES[idx]

def get_dtcs(map):
    idx = struct.unpack("B", map[POS_DTCS])[0]

    return chirp_common.DTCS_CODES[idx]

def get_tone_enabled(map):
    val = struct.unpack("B", map[POS_TENB])[0] & 0x03

    dtcs = tenc = tsql = False

    if val == 3:
        dtcs = True
    else:
        tenc = (val & 0x01) != 0
        tsql = (val & 0x02) != 0

    return tenc, tsql, dtcs

def get_dtcs_polarity(map):
    val = struct.unpack("B", map[POS_DTCS_POL])[0] & 0xC0

    pol_values = { 0x00 : "NN",
                   0x40 : "NR",
                   0x80 : "RN",
                   0xC0 : "RR" }

    return pol_values[val]

def get_mem_offset(number):
    return number * MEM_LOC_SIZE

def get_raw_memory(map, number):
    offset = get_mem_offset(number)
    return MemoryMap(map[offset:offset + MEM_LOC_SIZE])

def get_memory(_map, number):
    map = get_raw_memory(_map, number)

    if not is_used(_map, number):
        raise errors.InvalidMemoryLocation("Location %i is empty" % number)

    m = chirp_common.Memory()
    m.freq = get_freq(map)
    m.name = get_name(map)
    m.number = number
    m.mode = get_mode(map)
    m.duplex = get_duplex(map)
    m.offset = get_dup_offset(map)
    m.rtone = get_rtone(map)
    m.ctone = get_ctone(map)
    m.dtcs = get_dtcs(map)
    m.tencEnabled, m.tsqlEnabled, m.dtcsEnabled = get_tone_enabled(map)
    m.dtcsPolarity = get_dtcs_polarity(map)
    
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

def set_dup_offset(map, offset):
    val = struct.pack("B", int((offset * 1000) / 5))

    map[POS_DOFF] = val

def set_tone_enabled(map, enc, sql, dtcs):
    mask = 0xFC # ~00000001
    val = struct.unpack("B", map[POS_TENB])[0] & mask

    if dtcs:
        val |= 0x03
    else:
        if enc:
            val |= 0x01
        if sql:
            val |= 0x02

    map[POS_TENB] = val

def set_rtone(map, tone):
    map[POS_RTONE] = struct.pack("B", chirp_common.TONES.index(tone))    

def set_ctone(map, tone):
    map[POS_CTONE] = struct.pack("B", chirp_common.TONES.index(tone))

def set_dtcs(map, code):
    map[POS_DTCS] = struct.pack("B", chirp_common.DTCS_CODES.index(code))

def set_dtcs_polarity(map, polarity):
    val = struct.unpack("B", map[POS_DTCS_POL])[0] & 0x3F
    pol_values = { "NN" : 0x00,
                   "NR" : 0x40,
                   "RN" : 0x80,
                   "RR" : 0xC0 }

    val |= pol_values[polarity]

    map[POS_DTCS_POL] = val

def set_memory(_map, memory):
    map = get_raw_memory(_map, memory.number)

    if not is_used(_map, memory.number):
        # Assume this is empty now, so initialize bits
        map[2] = "\x78\x00"
        map[10] = "\x08x08" + ("\x00" * 10)

    set_used(_map, memory.number, True)
    set_freq(map, memory.freq)
    set_name(map, memory.name)
    set_duplex(map, memory.duplex)
    set_dup_offset(map, memory.offset)
    set_mode(map, memory.mode)
    set_rtone(map, memory.rtone)
    set_ctone(map, memory.ctone)
    set_dtcs(map, memory.dtcs)
    set_tone_enabled(map,
                     memory.tencEnabled,
                     memory.tsqlEnabled,
                     memory.dtcsEnabled)
    set_dtcs_polarity(map, memory.dtcsPolarity)

    _map[get_mem_offset(memory.number)] = map.get_packed()
    return _map

def erase_memory(map, number):
    set_used(map, number, False)

def parse_map_for_memory(map):
    memories = []

    for i in range(197):
        try:
            m = get_memory(map, i)
        except errors.InvalidMemoryLocation:
            m = None
        if m:
            memories.append(m)

    return memories
