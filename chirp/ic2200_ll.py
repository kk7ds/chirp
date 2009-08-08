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

POS_FREQ_START =  0
POS_FREQ_END   =  2
POS_NAME_START =  4
POS_NAME_END   = 10
POS_MODE       = 23
POS_FLAG       = 20
POS_DUPX       = 21
POS_DOFF_START =  2
POS_DOFF_END   =  4
POS_RTONE      = 10
POS_CTONE      = 11
POS_DTCS       = 12
POS_DTCS_POL   = 21
POS_TENB       = 20
POS_TUNE_STEP  = 13
POS_FLAGS_START= 0x1370
POS_MYURCALL   = 17
POS_RPTCALL    = 18

POS_URCALL     = 0x1620
POS_RPCALL     = 0x1650
POS_MYCALL     = 0x15F0

MEM_LOC_SIZE = 24

TUNING_STEPS = list(chirp_common.TUNING_STEPS)
TUNING_STEPS.remove(6.25)

IC2200_SPECIAL = { "C" : 206 }
IC2200_SPECIAL_REV = { 206 : "C" }

for i in range(0, 3):
    idA = "%iA" % i
    idB = "%iB" % i
    num = 200 + i * 2
    IC2200_SPECIAL[idA] = num
    IC2200_SPECIAL[idB] = num + 1
    IC2200_SPECIAL_REV[num] = idA
    IC2200_SPECIAL_REV[num+1] = idB

def bank_name(index):
    char = chr(ord("A") + index)
    return "BANK-%s" % char

def is_used(mmap, number):
    if number == IC2200_SPECIAL["C"]:
        return True

    return (ord(mmap[POS_FLAGS_START + number]) & 0x20) == 0

def set_used(mmap, number, used=True):
    if number == IC2200_SPECIAL["C"]:
        return

    val = ord(mmap[POS_FLAGS_START + number]) & 0xDF

    if not used:
        val |= 0x20

    mmap[POS_FLAGS_START + number] = val

def get_freq(mmap):
    val = struct.unpack("<H", mmap[POS_FREQ_START:POS_FREQ_END])[0]

    if ord(mmap[POS_FLAG]) & 0x80:
        mult = 6.25
    else:
        mult = 5.0

    return (val * mult) / 1000.0

def get_name(mmap):
    return mmap[POS_NAME_START:POS_NAME_END].replace("\x0E", "").strip()

def get_tune_step(mmap):
    tsidx = ord(mmap[POS_TUNE_STEP]) &0x0F
    try:
        return TUNING_STEPS[tsidx]
    except IndexError:
        raise errors.InvalidDataError("Radio has unknown TS index %i" % tsidx)

def get_mode(mmap):
    val = struct.unpack("B", mmap[POS_MODE])[0] & 0x80
    flg = struct.unpack("B", mmap[POS_FLAG])[0] & 0x30

    if val == 0x80:
        return "DV"
    elif val == 0x00:
        mode = "FM"
        if flg & 0x20:
            mode = "AM"
        
        if flg & 0x10:
            mode = "N" + mode
    else:
        raise errors.InvalidDataError("Radio has unknown mode %02x" % val)

    return mode

def get_duplex(mmap):
    val = struct.unpack("B", mmap[POS_DUPX])[0] & 0x30
    if val & 0x10:
        return "-"
    elif val & 0x20:
        return "+"
    else:
        return ""

def get_dup_offset(mmap):
    val = struct.unpack("<H", mmap[POS_DOFF_START:POS_DOFF_END])[0]

    return float(val * 5.0) / 1000.0

def get_rtone(mmap):
    idx = struct.unpack("B", mmap[POS_RTONE])[0]

    return chirp_common.TONES[idx]

def get_ctone(mmap):
    idx = struct.unpack("B", mmap[POS_CTONE])[0]

    return chirp_common.TONES[idx]

def get_dtcs(mmap):
    idx = struct.unpack("B", mmap[POS_DTCS])[0]

    return chirp_common.DTCS_CODES[idx]

def get_tone_enabled(mmap):
    val = struct.unpack("B", mmap[POS_TENB])[0] & 0x03

    if val == 3:
        return "DTCS"
    else:
        if (val & 0x01) != 0:
            return "Tone"
        elif (val & 0x02) != 0:
            return "TSQL"
    
    return ""

def get_dtcs_polarity(mmap):
    val = struct.unpack("B", mmap[POS_DTCS_POL])[0] & 0xC0

    pol_values = { 0x00 : "NN",
                   0x40 : "NR",
                   0x80 : "RN",
                   0xC0 : "RR" }

    return pol_values[val]

def get_mem_offset(number):
    return number * MEM_LOC_SIZE

def get_raw_memory(mmap, number):
    offset = get_mem_offset(number)
    return MemoryMap(mmap[offset:offset + MEM_LOC_SIZE])

def get_call_indices(mmap):
    return ord(mmap[17]) & 0x0F, \
        (ord(mmap[18]) & 0xF0) >> 4, \
        ord(mmap[18]) & 0x0F
               
def get_skip(mmap, number):
    val = ord(mmap[POS_FLAGS_START + number]) & 0x10

    if val != 0:
        return "S"
    else:
        return ""

def get_bank(mmap, number):
    val = ord(mmap[POS_FLAGS_START + number]) & 0x0F

    if val == 0x0A:
        return None
    else:
        return val

def _get_memory(_map, mmap):
    if get_mode(mmap) == "DV":
        print "Doing DV"
        mem = chirp_common.DVMemory()
        i_ucall, i_r1call, i_r2call = get_call_indices(mmap)
        mem.dv_urcall = get_urcall(_map, i_ucall)
        mem.dv_rpt1call = get_rptcall(_map, i_r1call)
        mem.dv_rpt2call = get_rptcall(_map, i_r2call)
        print "Calls: %s %s %s" % (mem.dv_urcall, mem.dv_rpt1call, mem.dv_rpt2call)
        print "Indexes: %i %i %i" % (i_ucall, i_r1call, i_r2call)
    else:
        print "Non-DV"
        mem = chirp_common.Memory()

    mem.freq = get_freq(mmap)
    mem.name = get_name(mmap)
    mem.mode = get_mode(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_dup_offset(mmap)
    mem.rtone = get_rtone(mmap)
    mem.ctone = get_ctone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.tmode = get_tone_enabled(mmap)
    mem.dtcs_polarity = get_dtcs_polarity(mmap)
    mem.tuning_step = get_tune_step(mmap)

    return mem

def get_memory(_map, number):
    if not is_used(_map, number):
        mem = chirp_common.Memory()
        if number < 200:
            mem.number = number
            mem.empty = True
            return mem
    else:
        mmap = get_raw_memory(_map, number)
        mem = _get_memory(_map, mmap)

    mem.number = number

    if number < 200:
        mem.skip = get_skip(_map, number)
        mem.bank = get_bank(_map, number)
    else:
        mem.extd_number = IC2200_SPECIAL_REV[number]
        mem.immutable = ["number", "skip", "bank", "bank_index", "extd_number"]
    
    return mem

def set_freq(mmap, freq, ts):
    if ts == 12.5:
        mult = 6.25
    else:
        mult = 5.0

    mmap[POS_FREQ_START] = struct.pack("<H", int((freq * 1000) / mult))

def set_tune_step(mmap, ts):
    val = ord(mmap[POS_TUNE_STEP]) & 0xF0
    try:
        tsidx = TUNING_STEPS.index(ts)
    except ValueError:
        raise errors.InvalidDataError("IC2200H does not support tuning step of %.2f" % ts)
    val |= (tsidx & 0x0F)
    mmap[POS_TUNE_STEP] = val

def set_name(mmap, name):
    mmap[POS_NAME_START] = name.ljust(6)[:6]

    if name == (" " * 6):
        mmap[22] = 0
    else:
        mmap[22] = 0x10

def set_mode(mmap, mode):
    val = ord(mmap[POS_FLAG]) & 0xCF

    if mode == "FM":
        mmap[POS_MODE] = 0
    elif mode == "NFM":
        mmap[POS_MODE] = 0
        val |= 0x10
    elif mode == "DV":
        mmap[POS_MODE] = 0x80
    elif mode == "AM":
        mmap[POS_MODE] = 0
        val |= 0x20
    elif mode == "NAM":
        mmap[POS_MODE] = 0
        val |= 0x30
    else:
        raise errors.InvalidDataError("Unsupported mode `%s'" % mode)

    mmap[POS_FLAG] = val

def set_duplex(mmap, duplex):
    mask = 0xCF # ~ 00110000
    val = struct.unpack("B", mmap[POS_DUPX])[0] & mask

    if duplex == "-":
        val |= 0x10
    elif duplex == "+":
        val |= 0x20

    mmap[POS_DUPX] = val

def set_dup_offset(mmap, offset):
    val = struct.pack("<H", int((offset * 1000) / 5))

    mmap[POS_DOFF_START] = val

def set_tone_enabled(mmap, mode):
    mask = 0xFC # ~00000001
    val = struct.unpack("B", mmap[POS_TENB])[0] & mask

    if mode == "DTCS":
        val |= 0x03
    else:
        if mode == "Tone":
            val |= 0x01
        elif mode == "TSQL":
            val |= 0x02

    mmap[POS_TENB] = val

def set_rtone(mmap, tone):
    mmap[POS_RTONE] = struct.pack("B", chirp_common.TONES.index(tone))    

def set_ctone(mmap, tone):
    mmap[POS_CTONE] = struct.pack("B", chirp_common.TONES.index(tone))

def set_dtcs(mmap, code):
    mmap[POS_DTCS] = struct.pack("B", chirp_common.DTCS_CODES.index(code))

def set_dtcs_polarity(mmap, polarity):
    val = struct.unpack("B", mmap[POS_DTCS_POL])[0] & 0x3F
    pol_values = { "NN" : 0x00,
                   "NR" : 0x40,
                   "RN" : 0x80,
                   "RR" : 0xC0 }

    val |= pol_values[polarity]

    mmap[POS_DTCS_POL] = val

def set_call_indices(_map, mmap, urcall, r1call, r2call):
    ulist = []
    for i in range(0, 6):
        ulist.append(get_urcall(_map, i))

    rlist = []
    for i in range(0, 6):
        rlist.append(get_rptcall(_map, i))

    try:
        if not urcall:
            uindex = 0
        else:
            uindex = ulist.index(urcall)
    except ValueError:
        raise errors.InvalidDataError("Call `%s' not in URCALL list" % urcall)

    try:
        if not r1call:
            r1index = 0
        else:
            r1index = rlist.index(r1call)
    except ValueError:
        raise errors.InvalidDataError("Call `%s' not in RCALL list" % r1call)

    try:
        if not r2call:
            r2index = 0
        else:
            r2index = rlist.index(r2call)
    except ValueError:
        raise errors.InvalidDataError("Call `%s' not in RCALL list" % r2call)

    print "Setting calls: %i %i %i" % (uindex, r1index, r2index)

    mmap[17] = (ord(mmap[17]) & 0xF0) | uindex
    mmap[18] = (r1index << 4) | r2index

def set_skip(mmap, number, skip):
    if skip == "P":
        raise errors.InvalidDataError("PSKIP not supported by this model")

    val = ord(mmap[POS_FLAGS_START + number]) & 0xEF

    if skip == "S":
        val |= 0x10

    mmap[POS_FLAGS_START + number] = val

def set_bank(mmap, number, bank):
    if bank > 9:
        raise errors.InvalidDataError("Invalid bank number %i" % bank)

    if bank is None:
        index = 0x0A
    else:
        index = bank

    val = ord(mmap[POS_FLAGS_START + number]) & 0xF0
    val |= index
    mmap[POS_FLAGS_START + number] = val    

def set_memory (_map, memory):
    mmap = get_raw_memory(_map, memory.number)

    if not is_used(_map, memory.number):
        # Assume this is empty now, so initialize bits
        mmap[2] = "\x78\x00"
        mmap[10] = "\x08x08" + ("\x00" * 10)

    set_used(_map, memory.number, True)
    set_freq(mmap, memory.freq, memory.tuning_step)
    set_name(mmap, memory.name)
    set_duplex(mmap, memory.duplex)
    set_dup_offset(mmap, memory.offset)
    set_mode(mmap, memory.mode)
    set_rtone(mmap, memory.rtone)
    set_ctone(mmap, memory.ctone)
    set_dtcs(mmap, memory.dtcs)
    set_tone_enabled(mmap, memory.tmode)
    set_dtcs_polarity(mmap, memory.dtcs_polarity)
    set_tune_step(mmap, memory.tuning_step)
    if memory.number < 200:
        set_skip(_map, memory.number, memory.skip)
        set_bank(_map, memory.number, memory.bank)

    if isinstance(memory, chirp_common.DVMemory):
        set_call_indices(_map,
                         mmap,
                         memory.dv_urcall,
                         memory.dv_rpt1call,
                         memory.dv_rpt2call)

    _map[get_mem_offset(memory.number)] = mmap.get_packed()
    return _map

def erase_memory(mmap, number):
    set_used(mmap, number, False)
    return mmap

def call_location(base, index):
    return base + (8 * index)

def get_urcall(mmap, index):
    if index > 5:
        raise errors.InvalidDataError("URCALL index %i must be <= 5" % index)

    start = call_location(POS_URCALL, index)

    return mmap[start:start+8].rstrip()

def get_rptcall(mmap, index):
    if index > 5:
        raise errors.InvalidDataError("RPTCALL index %i must be <= 5" % index)

    start = call_location(POS_RPCALL, index)

    return mmap[start:start+8].rstrip()

def get_mycall(mmap, index):
    if index > 5:
        raise errors.InvalidDataError("MYCALL index %i must be <= 5" % index)

    start = call_location(POS_MYCALL, index)
    print "Start for %i is %04x" % (index, start)

    return mmap[start:start+8].rstrip()

def set_urcall(mmap, index, call):
    if index > 5:
        raise errors.InvalidDataError("URCALL index %i must be <= 5" % index)

    start = call_location(POS_URCALL, index)

    mmap[start] = call.ljust(8)

    return mmap

def set_rptcall(mmap, index, call):
    if index > 5:
        raise errors.InvalidDataError("RPTCALL index %i must be <= 5" % index)

    start = call_location(POS_RPCALL, index)

    mmap[start] = call.ljust(8)

    return mmap

def set_mycall(mmap, index, call):
    if index > 5:
        raise errors.InvalidDataError("MYCALL index %i must be <= 5" % index)

    start = call_location(POS_MYCALL, index)

    mmap[start] = call.ljust(8)

    return mmap

def parse_map_for_memory(mmap):
    memories = []

    for i in range(197):
        try:
            mem = get_memory(mmap, i)
        except errors.InvalidMemoryLocation:
            mem = None
        if mem:
            memories.append(mem)

    return memories
