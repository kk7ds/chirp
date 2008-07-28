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
import traceback
import sys

import icf
import util
import chirp_common
import errors
from memmap import MemoryMap

IC2820_MODES = {
    0x0040 : "NFM",
    0x0000 : "FM",
    0x0100 : "DV",
    0x0080 : "AM",
    0x00C0 : "NAM",
    }

IC2820_MODES_REV = {}
for val, mode in IC2820_MODES.items():
    IC2820_MODES_REV[mode] = val

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

MEM_LOC_SIZE   = 0x30

def get_freq(map):
    return struct.unpack(">I", map[POS_FREQ_START:POS_FREQ_END])[0] / 1000000.0

def get_name(map):
    return map[POS_NAME_START:].strip()

def get_rtone(map):
    mask = 0x03F0
    val = struct.unpack(">H", map[POS_TONE_START:POS_TONE_END])[0] & mask
    idx = (val >> 4)

    return chirp_common.TONES[idx]

def get_ctone(map):
    mask = 0xFC00
    val = struct.unpack(">H", map[POS_TONE_START:POS_TONE_END])[0] & mask
    idx = (val >> 10)

    return chirp_common.TONES[idx]    

def get_dtcs(map):
    mask = 0xFE
    val = struct.unpack("B", map[POS_DTCS])[0] & mask
    idx = (val >> 1)
    
    return chirp_common.DTCS_CODES[idx]

def get_dtcs_polarity(map):
    val = struct.unpack("B", map[POS_DTCS_POL])[0] & 0x30
    polarity_values = { 0x00 : "NN",
                        0x10 : "NR",
                        0x20 : "RN",
                        0x30 : "RR" }

    return polarity_values[val]

def get_duplex(map):
    val = struct.unpack("B", map[POS_DUPX_TONE])[0] & 0x60
    if val & 0x40:
        return "+"
    elif val & 0x20:
        return "-"
    else:
        return ""

def get_dup_off(map):
    return struct.unpack(">I", map[POS_DOFF_START:POS_DOFF_END])[0] / 1000000.0

def get_tone_enabled(map):
    val = struct.unpack("B", map[POS_DUPX_TONE])[0] & 0x3C
    
    enc = sql = dtcs = False

    if val == 0x04:
        enc = True
    elif val == 0x2C:
        sql = True
    elif val == 0x38:
        dtcs = True

    return enc, sql, dtcs

def get_mode(map):
    val = struct.unpack(">H", map[POS_MODE_START:POS_MODE_END])[0] & 0x01C0
    try:
        return IC2820_MODES[val]
    except KeyError:
        raise errors.InvalidDataError("Radio has unknown mode 0x%04x" % val)

def get_memory(_map, number):
    offset = number * MEM_LOC_SIZE
    map = MemoryMap(_map[offset : offset + MEM_LOC_SIZE])
    mem = chirp_common.Memory()
    mem.number = number

    mem.freq = get_freq(map)
    mem.name = get_name(map)

    # Really need to figure out how to determine which locations are used
    if len(mem.name) == 0:
        return None
    if mem.name[0] == "\x00":
        return None
    elif mem.name[0] == "\xFF":
        return None

    mem.rtone = get_rtone(map)
    mem.ctone = get_ctone(map)
    mem.dtcs = get_dtcs(map)
    mem.tencEnabled, mem.tsqlEnabled, mem.dtcsEnabled = get_tone_enabled(map)
    mem.dtcsPolarity = get_dtcs_polarity(map)
    mem.duplex = get_duplex(map)
    mem.offset = get_dup_off(map)
    mem.mode = get_mode(map)

    return mem

def set_freq(map, freq):
    map[POS_FREQ_START] = struct.pack(">I", int(freq * 1000000))

def set_name(map, name):
    map[POS_NAME_START] = name.ljust(8)[:8]

def set_duplex(map, duplex):
    val = ord(map[POS_DUPX_TONE]) & 0x9F # ~01100000
    if duplex == "+":
        val |= 0x40
    elif duplex == "-":
        val |= 0x20
    map[POS_DUPX_TONE] = val

def set_dup_offset(map, offset):
    map[POS_DOFF_START] = struct.pack(">I", int(offset * 1000000))

def set_tone_enabled(map, enc, sql, dtcs):
    mask = 0xC3
    val = ord(map[POS_DUPX_TONE]) & mask

    if enc:
        val |= 0x04
    elif sql:
        val |= 0x2C
    elif dtcs:
        val |= 0x38

    map[POS_DUPX_TONE] = val

def set_rtone(map, tone):
    mask = 0xFC0F # ~00001111 11110000
    val = struct.unpack(">H", map[POS_TONE_START:POS_TONE_END])[0] & mask
    index = chirp_common.TONES.index(tone)
    val |= (index << 4) & 0x03F0

    map[POS_TONE_START] = struct.pack(">H", val)

def set_ctone(map, tone):
    mask = 0x03FF # ~11111100 00000000
    val = struct.unpack(">H", map[POS_TONE_START:POS_TONE_END])[0] & mask
    index = chirp_common.TONES.index(tone)
    val |= (index << 10) & 0xFC00

    map[POS_TONE_START] = struct.pack(">H", val)    

def set_dtcs(map, code):
    mask = 0x01 # ~11111110
    val = struct.unpack("B", map[POS_DTCS])[0] & mask
    val |= (chirp_common.DTCS_CODES.index(code) << 1)
    
    map[POS_DTCS] = struct.pack("B", val)

def set_dtcs_polarity(map, polarity):
    mask = 0xCF # ~00110000
    val = struct.unpack("B", map[POS_DTCS_POL])[0] & mask

    polarity_values = { "NN" : 0x00,
                        "NR" : 0x10,
                        "RN" : 0x20,
                        "RR" : 0x30 }

    val |= polarity_values[polarity]

    map[POS_DTCS_POL] = val

def set_mode(map, mode):
    mask = 0xFE3F # ~ 00000001 11000000
    val = struct.unpack(">H", map[POS_MODE_START:POS_MODE_END])[0] & mask

    try:
        val |= IC2820_MODES_REV[mode]
    except KeyError:
        print "Valid modes: %s" % IC2820_MODES_REV
        raise errors.InvalidDataError("Unsupported mode `%s'" % mode)

    map[POS_MODE_START] = struct.pack(">H", val)

def set_memory(_map, mem):
    offset = mem.number * MEM_LOC_SIZE
    map = MemoryMap(_map[offset:offset + MEM_LOC_SIZE])

    set_freq(map, mem.freq)
    set_name(map, mem.name)
    set_duplex(map, mem.duplex)
    set_dup_offset(map, mem.offset)
    set_rtone(map, mem.rtone)
    set_ctone(map, mem.ctone)
    set_dtcs(map, mem.dtcs)
    set_dtcs_polarity(map, mem.dtcsPolarity)
    set_tone_enabled(map, mem.tencEnabled, mem.tsqlEnabled, mem.dtcsEnabled)
    set_mode(map, mem.mode)

    _map[offset] = map.get_packed()

    return _map

def parse_map_for_memory(map):
    memories = []

    for i in range(500):
        # FIXME: Remove this after debugging
        try:
            m = get_memory(map, i)
            if m:
                memories.append(m)
        except Exception,e:
            traceback.print_exc(file=sys.stdout)
            print "Failed to parse location %i: %s" % (i, e)

    return memories

if __name__ == "__main__":
    import serial
    
    s = serial.Serial(port="/dev/ttyUSB1",
                      baudrate=9600,
                      timeout=0.5)
    
    md = icf.get_model_data(s)
    
    print "Model:\n%s" % util.hexprint(md)
    #
    map = icf.clone_from_radio(s, md[0:4], chirp_common.console_status)
    #f = file("2820.map", "wb")
    #f.write(map)
    #f.close()

    #f = file("2820.map", "rb")
    #map = f.read()
    #f.close()

    #print get_memory(map, 3)
