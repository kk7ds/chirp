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

from chirp import chirp_common, errors
from chirp.memmap import MemoryMap

IC2820_MODES = {
    0x0040 : "NFM",
    0x0000 : "FM",
    0x0100 : "DV",
    0x0080 : "AM",
    0x00C0 : "NAM",
    }

IC2820_MODES_REV = {}
for __val, __mode in IC2820_MODES.items():
    IC2820_MODES_REV[__mode] = __val

# Value offsets
# NB: The _END variants are python slice ends, which means they are one
#     higher than the actual end value
POS_FREQ_START =  0
POS_FREQ_END   =  4
POS_NAME_START = -8
POS_TONE_START = 34
POS_TONE_END   = 36
POS_DUPX_TONE  = 33
POS_DOFF_START =  4
POS_DOFF_END   =  8
POS_MODE_START = 36
POS_MODE_END   = 38
POS_DTCS_POL   = 39
POS_DTCS       = 36
POS_USED_START = 0x61E0

MEM_LOC_SIZE   = 0x30

def is_used(mmap, number):
    byte = int(number / 8) + POS_USED_START
    mask = 1 << (number % 8)
    
    return (ord(mmap[byte]) & mask) == 0

def set_used(mmap, number, used):
    byte = int(number / 8) + POS_USED_START
    mask = 1 << (number % 8)

    val = ord(mmap[byte]) & (~mask & 0xFF)

    if not used:
        val |= mask

    mmap[byte] = val

    return mmap

def get_freq(mmap):
    return struct.unpack(">I", mmap[POS_FREQ_START:POS_FREQ_END])[0] / 1000000.0

def get_name(mmap):
    return mmap[POS_NAME_START:].strip()

def get_rtone(mmap):
    mask = 0x03F0
    val = struct.unpack(">H", mmap[POS_TONE_START:POS_TONE_END])[0] & mask
    idx = (val >> 4)

    return chirp_common.TONES[idx]

def get_ctone(mmap):
    mask = 0xFC00
    val = struct.unpack(">H", mmap[POS_TONE_START:POS_TONE_END])[0] & mask
    idx = (val >> 10)

    return chirp_common.TONES[idx]    

def get_dtcs(mmap):
    mask = 0xFE
    val = struct.unpack("B", mmap[POS_DTCS])[0] & mask
    idx = (val >> 1)
    
    return chirp_common.DTCS_CODES[idx]

def get_dtcs_polarity(mmap):
    val = struct.unpack("B", mmap[POS_DTCS_POL])[0] & 0x30
    polarity_values = { 0x00 : "NN",
                        0x10 : "NR",
                        0x20 : "RN",
                        0x30 : "RR" }

    return polarity_values[val]

def get_duplex(mmap):
    val = struct.unpack("B", mmap[POS_DUPX_TONE])[0] & 0x60
    if val & 0x40:
        return "+"
    elif val & 0x20:
        return "-"
    else:
        return ""

def get_dup_off(mmap):
    return struct.unpack(">I", mmap[POS_DOFF_START:POS_DOFF_END])[0] / 1000000.0

def get_tone_enabled(mmap):
    val = struct.unpack("B", mmap[POS_DUPX_TONE])[0] & 0x3C
    
    enc = sql = dtcs = False

    if (val & 0x0C) == 0x0C:
        sql = True
    elif (val & 0x38) == 0x38:
        dtcs = True
    elif (val & 0x04) == 0x04:
        enc = True

    return enc, sql, dtcs

def get_mode(mmap):
    val = struct.unpack(">H", mmap[POS_MODE_START:POS_MODE_END])[0] & 0x01C0
    try:
        return IC2820_MODES[val]
    except KeyError:
        raise errors.InvalidDataError("Radio has unknown mode 0x%04x" % val)

def get_raw_memory(mmap, number):
    offset = number * MEM_LOC_SIZE
    return MemoryMap(mmap[offset : offset + MEM_LOC_SIZE])

def set_raw_memory(dst, src, number):
    offset = number * MEM_LOC_SIZE
    dst[offset] = src.get_packed()

def get_memory(_map, number):
    if not is_used(_map, number):
        raise errors.InvalidMemoryLocation("Location %i is empty" % number)

    mmap = get_raw_memory(_map, number)
    mem = chirp_common.Memory()
    mem.number = number

    mem.freq = get_freq(mmap)
    mem.name = get_name(mmap)

    mem.rtone = get_rtone(mmap)
    mem.ctone = get_ctone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.tencEnabled, mem.tsqlEnabled, mem.dtcsEnabled = get_tone_enabled(mmap)
    mem.dtcsPolarity = get_dtcs_polarity(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_dup_off(mmap)
    mem.mode = get_mode(mmap)

    return mem

def erase_memory(mmap, number):
    set_used(mmap, number, False)

def set_freq(mmap, freq):
    mmap[POS_FREQ_START] = struct.pack(">I", int(freq * 1000000))

def set_name(mmap, name):
    mmap[POS_NAME_START] = name.ljust(8)[:8]

def set_duplex(mmap, duplex):
    val = ord(mmap[POS_DUPX_TONE]) & 0x9F # ~01100000
    if duplex == "+":
        val |= 0x40
    elif duplex == "-":
        val |= 0x20
    mmap[POS_DUPX_TONE] = val

def set_dup_offset(mmap, offset):
    mmap[POS_DOFF_START] = struct.pack(">I", int(offset * 1000000))

def set_tone_enabled(mmap, enc, sql, dtcs):
    mask = 0xC3
    val = ord(mmap[POS_DUPX_TONE]) & mask

    if enc:
        val |= 0x04
    elif sql:
        val |= 0x2C
    elif dtcs:
        val |= 0x38

    mmap[POS_DUPX_TONE] = val

def set_rtone(mmap, tone):
    mask = 0xFC0F # ~00001111 11110000
    val = struct.unpack(">H", mmap[POS_TONE_START:POS_TONE_END])[0] & mask
    index = chirp_common.TONES.index(tone)
    val |= (index << 4) & 0x03F0

    mmap[POS_TONE_START] = struct.pack(">H", val)

def set_ctone(mmap, tone):
    mask = 0x03FF # ~11111100 00000000
    val = struct.unpack(">H", mmap[POS_TONE_START:POS_TONE_END])[0] & mask
    index = chirp_common.TONES.index(tone)
    val |= (index << 10) & 0xFC00

    mmap[POS_TONE_START] = struct.pack(">H", val)    

def set_dtcs(mmap, code):
    mask = 0x01 # ~11111110
    val = struct.unpack("B", mmap[POS_DTCS])[0] & mask
    val |= (chirp_common.DTCS_CODES.index(code) << 1)
    
    mmap[POS_DTCS] = struct.pack("B", val)

def set_dtcs_polarity(mmap, polarity):
    mask = 0xCF # ~00110000
    val = struct.unpack("B", mmap[POS_DTCS_POL])[0] & mask

    polarity_values = { "NN" : 0x00,
                        "NR" : 0x10,
                        "RN" : 0x20,
                        "RR" : 0x30 }

    val |= polarity_values[polarity]

    mmap[POS_DTCS_POL] = val

def set_mode(mmap, mode):
    mask = 0xFE3F # ~ 00000001 11000000
    val = struct.unpack(">H", mmap[POS_MODE_START:POS_MODE_END])[0] & mask

    try:
        val |= IC2820_MODES_REV[mode]
    except KeyError:
        print "Valid modes: %s" % IC2820_MODES_REV
        raise errors.InvalidDataError("Unsupported mode `%s'" % mode)

    mmap[POS_MODE_START] = struct.pack(">H", val)

def set_memory(_map, mem):
    mmap = get_raw_memory(_map, mem.number)

    set_freq(mmap, mem.freq)
    set_name(mmap, mem.name)
    set_duplex(mmap, mem.duplex)
    set_dup_offset(mmap, mem.offset)
    set_rtone(mmap, mem.rtone)
    set_ctone(mmap, mem.ctone)
    set_dtcs(mmap, mem.dtcs)
    set_dtcs_polarity(mmap, mem.dtcsPolarity)
    set_tone_enabled(mmap, mem.tencEnabled, mem.tsqlEnabled, mem.dtcsEnabled)
    set_mode(mmap, mem.mode)

    set_raw_memory(_map, mmap, mem.number)

    set_used(_map, mem.number, True)

    return _map

def parse_map_for_memory(mmap):
    memories = []

    for i in range(500):
        try:
            mem = get_memory(mmap, i)
        except errors.InvalidMemoryLocation:
            mem = None

        if mem:
            memories.append(mem)

    return memories

