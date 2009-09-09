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
POS_SKIP_FLAGS = 0xAAFE
POS_PSKP_FLAGS = 0xAB82

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

def set_freq(mmap, freq):
    val = struct.unpack("b", mmap[POS_TUNE_FLAG])[0] & 0xEF
    if chirp_common.is_fractional_step(freq):
        mult = 6.25
        val |= 0x10
    else:
        mult = 5

    mmap[POS_TUNE_FLAG] = val
    mmap[POS_FREQ_START] = struct.pack(">i", int((freq * 1000) / mult))[1:]

def get_name(mmap):
    return mmap[POS_NAME_START:POS_NAME_END].strip()

def set_name(mmap, name):
    mmap[POS_NAME_START] = name.rstrip()[:8]

def get_offset(mmap):
    val = struct.unpack(">h", mmap[POS_OFFSET:POS_OFFSET+2])[0] & 0x0FFF
    return (val * 5) / 1000.0

def set_offset(mmap, offset):
    val = struct.unpack(">h", mmap[POS_OFFSET:POS_OFFSET+2])[0] & 0xF000
    val |= (int(offset * 1000) / 5)
    mmap[POS_OFFSET] = struct.pack(">h", val)

def get_duplex(mmap):
    val = struct.unpack("b", mmap[POS_DUP])[0]

    if (val & 0x0C) == 0x04:
        return "-"
    elif (val & 0x0C) == 0x08:
        return "+"
    else:
        return ""    

def set_duplex(mmap, duplex):
    val = struct.unpack("b", mmap[POS_DUP])[0] & 0xF3
    if duplex == "-":
        val |= 0x04
    elif duplex == "+":
        val |= 0x08
    mmap[POS_DUP] = val

def get_rtone(mmap):
    val = struct.unpack("b", mmap[POS_RTONE])[0] & 0xFC
    val >>= 2

    return chirp_common.TONES[val]

def set_rtone(mmap, tone):
    val = struct.unpack("b", mmap[POS_RTONE])[0] & 0x03
    val |= chirp_common.TONES.index(tone) << 2
    mmap[POS_RTONE] = val

def get_ctone(mmap):
    val = struct.unpack(">h", mmap[POS_CTONE:POS_CTONE+2])[0]
    val = (val & 0x03F0) >> 4
    
    return chirp_common.TONES[val]

def set_ctone(mmap, tone):
    val = struct.unpack(">h", mmap[POS_CTONE:POS_CTONE+2])[0] & 0xFC0F
    val |= chirp_common.TONES.index(tone) << 4
    mmap[POS_CTONE] = struct.pack(">h", val)

def get_dtcs(mmap):
    val = struct.unpack("b", mmap[POS_DTCS])[0]
    return chirp_common.DTCS_CODES[val]

def set_dtcs(mmap, code):
    mmap[POS_DTCS] = chirp_common.DTCS_CODES.index(code)

ID880_MODES = ["FM", "NFM", None, "AM", "NAM", "DV"]

def get_mode(mmap):
    val = struct.unpack("b", mmap[POS_MODE])[0] & 0x07

    if val == 2:
        raise errors.InvalidDataError("Mode 0x02 is not valid for this radio")

    try:
        return ID880_MODES[val]
    except IndexError:
        raise errors.InvalidDataError("Unknown mode 0x%02x" % val)

def set_mode(mmap, mode):
    if mode not in ID880_MODES:
        raise errors.InvalidDataError("Mode %s not supported" % mode)

    val = struct.unpack("b", mmap[POS_MODE])[0] & 0xF8
    val |= ID880_MODES.index(mode)
    mmap[POS_MODE] = val

ID880_TMODES = ["", "Tone", None, "TSQL", "DTCS", "TSQL-R", "DTCS-R"]

def get_tmode(mmap):
    val = (struct.unpack("b", mmap[POS_TMODE])[0] >> 4) & 0x07

    if val == 2:
        raise errors.InvalidDataError("TMode 0x02 is not valid for this radio")

    try:
        return ID880_TMODES[val]
    except IndexError:
        raise errors.InvalidDataError("Unknown tone mode 0x%02x" % val)

def set_tmode(mmap, tmode):
    if tmode not in ID880_TMODES:
        raise errors.InvalidDataError("Tone Mode %s not supported" % tmode)

    val = struct.unpack("b", mmap[POS_TMODE])[0] & 0xF8
    val |= ID880_TMODES.index(tmode)
    mmap[POS_TMODE] = val

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

def set_dtcs_polarity(mmap, polarity):
    val = struct.unpack("b", mmap[POS_DTCS_POL])[0] & 0xFC

    if polarity == "NN":
        pass
    elif polarity == "NR":
        val |= 1
    elif polarity == "RN":
        val |= 2
    elif polarity == "RR":
        val |= 3
    else:
        raise errors.InvalidDataError("Unknown DTCS polarity %s" % polarity)

def is_used(mmap, number):
    byte = int(number / 8)
    bit = number % 8

    val = struct.unpack("b", mmap[POS_USED_START + byte])[0]
    val &= (1 << bit)

    return not bool(val)

def set_is_used(mmap, number, used):
    byte = int(number / 8)
    mask = ~(1 << (number % 8))

    val = struct.unpack("b", mmap[POS_USED_START + byte])[0] & mask
    if not used:
        val |= (1 << (number % 8))
    mmap[POS_USED_START + byte] = (val & 0xFF)

def get_skip(mmap, number):
    sval = struct.unpack("b", mmap[POS_SKIP_FLAGS + number])[0]
    pval = struct.unpack("b", mmap[POS_PSKP_FLAGS + number])[0]

    if not (sval & 0x40):
        return ""
    elif pval & 0x40:
        return "P"
    else:
        return "S"

def set_skip(mmap, number, skip):
    sval = struct.unpack("b", mmap[POS_SKIP_FLAGS + number])[0] & 0xBF
    pval = struct.unpack("b", mmap[POS_PSKP_FLAGS + number])[0] & 0xBF

    if skip:
        sval |= 0x40
    if skip == "P":
        pval |= 0x40

    mmap[POS_SKIP_FLAGS] = sval
    mmap[POS_PSKP_FLAGS] = pval

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
    mem.skip = get_skip(_map, number)

    return mem

def set_memory(_map, mem):
    mmap = get_raw_memory(_map, mem.number)

    set_freq(mmap, mem.freq)
    set_name(mmap, mem.name)
    set_duplex(mmap, mem.duplex)
    set_offset(mmap, mem.offset)
    set_mode(mmap, mem.mode)
    set_rtone(mmap, mem.rtone)
    set_ctone(mmap, mem.ctone)
    set_dtcs(mmap, mem.dtcs)
    set_tmode(mmap, mem.tmode)
    set_dtcs_polarity(mmap, mem.dtcs_polarity)

    _map[get_mem_offset(mem.number)] = mmap.get_packed()

    set_skip(_map, mem.number, mem.skip)
    set_is_used(_map, mem.number, True)

    return _map

def erase_memory(map, number):
    set_is_used(map, number, False)
    return map    

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
