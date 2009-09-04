#!/usr/bin/python
#
# Copyright 2009 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common, errors
from chirp.memmap import MemoryMap

POS_FREQ_START = 0
POS_NAME_START = 11
POS_NAME_END   = POS_NAME_START+8
POS_DUP        = 10
POS_OFFSET     =  3
POS_MODE       =  6
POS_RTONE      =  5
POS_CTONE      =  5
POS_DTCS       =  7
POS_TMODE      = 10
POS_DTCS_POL   = 10
POS_TUNE_FLAG  =  8

POS_USED_START = 0xAA80

POS_MYCALL     = 0xDE56
POS_URCALL     = 0xDE9E
POS_RPTCALL    = 0xF408

MEM_LOC_SIZE = 41


def get_mem_offset(number):
    return (number * MEM_LOC_SIZE)

def get_raw_memory(mmap, number):
    offset = get_mem_offset(number)
    return MemoryMap(mmap[offset:offset + MEM_LOC_SIZE])

def get_freq(mmap):
    val = struct.unpack("b", mmap[POS_TUNE_FLAG])[0] & 0x10
    if val:
        mult = 6.25
    else:
        mult = 5.0

    val = struct.unpack(">i", "\x00" + mmap[:3])[0]
    val &= 0x000FFFFF

    return (val * mult) / 1000.0

def get_name(mmap):
    return mmap[POS_NAME_START:POS_NAME_END].strip()

def get_offset(mmap):
    val = struct.unpack(">h", mmap[POS_OFFSET:POS_OFFSET+2])[0] & 0x0FFF
    return (val * 5) / 1000.0

def get_duplex(mmap):
    val = struct.unpack("b", mmap[POS_DUP])[0]

    if (val & 0x0C) == 0x04:
        return "-"
    elif (val & 0x0C) == 0x08:
        return "+"
    else:
        return ""    

def get_rtone(mmap):
    val = struct.unpack("b", mmap[POS_RTONE])[0] & 0xFC
    val >>= 2

    return chirp_common.TONES[val]

def get_ctone(mmap):
    val = struct.unpack("!H", mmap[POS_CTONE:POS_CTONE+2])[0]
    val = (val & 0x03F0) >> 4
    
    return chirp_common.TONES[val]

def get_dtcs(mmap):
    val = struct.unpack("b", mmap[POS_DTCS])[0]
    return chirp_common.DTCS_CODES[val]

def get_mode(mmap):
    val = struct.unpack("b", mmap[POS_MODE])[0] & 0x07

    if val == 0:
        return "FM"
    elif val == 1:
        return "NFM"
    elif val == 3:
        return "AM"
    elif val == 4:
        return "NAM"
    elif val == 5:
        return "DV"
    else:    
        raise errors.InvalidDataError("Unknown mode 0x%02x" % val)

def get_tmode(mmap):
    val = (struct.unpack("b", mmap[POS_TMODE])[0] >> 4) & 0x07

    if val == 0:
        return ""
    elif val == 1:
        return "Tone"
    elif val == 3:
        return "TSQL"
    elif val == 5:
        return "DTCS"
    elif val == 6:
        return "TSQL-R"
    elif val == 7:
        return "DTCS-R"
    else:
        raise errors.InvalidDataError("Unknown tone mode 0x%02x" % val)

def get_dtcs_polarity(mmap):
    val = struct.unpack("b", mmap[POS_DTCS_POL])[0] & 0x03

    if val == 0:
        return "NN"
    elif val == 1:
        return "NR"
    elif val == 2:
        return "RN"
    elif val == 3:
        return "RR"

def is_used(mmap, number):
    byte = int(number / 8)
    bit = number % 8

    val = struct.unpack("b", mmap[POS_USED_START + byte])[0]
    val &= (1 << bit)

    return not bool(val)

def _get_memory(mmap, number):
    if get_mode(mmap) == "DV":
        mem = chirp_common.DVMemory()
    else:
        mem = chirp_common.Memory()

    mem.freq = get_freq(mmap)
    mem.name = get_name(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_offset(mmap)
    mem.mode = get_mode(mmap)
    mem.rtone = get_rtone(mmap)
    mem.ctone = get_ctone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.tmode = get_tmode(mmap)
    mem.dtcs_polarity = get_dtcs_polarity(mmap)

    return mem

def get_memory(_map, number):
    if not is_used(_map, number):
        mem = chirp_common.Memory()
        mem.number = number
        mem.empty = True # FIXME for static scan edge, etc
        return mem

    mmap = get_raw_memory(_map, number)
    mem = _get_memory(mmap, number)
    mem.number = number

    return mem

def call_location(base, index):
    return base + (8 * (index - 1))

def get_call(mmap, index, base, limit, implied_first=False):
    if index > limit:
        raise errors.InvalidDataError("Call index must be <= %i" % limit)
    elif index == 0 and implied_first:
        return "CQCQCQ"

    start = call_location(base, index)
    print "start for %i is %x" % (index, start)
    return mmap[start:start+8].rstrip()

def get_mycall(mmap, index):
    return get_call(mmap, index, POS_MYCALL, 6)

def get_urcall(mmap, index):
    return get_call(mmap, index, POS_URCALL, 60, True)

def get_rptcall(mmap, index):
    return get_call(mmap, index, POS_RPTCALL, 99) # FIXME: repeater limit
