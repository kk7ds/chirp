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
POS_TUNE_STEP  = 35
POS_USED_START = 0x61E0
POS_URCALL     = 0x69B8
POS_RPTCALL    = 0x6B98
POS_MYCALL     = 0x6970
POS_SKIP_START = 0x6222
POS_PSKIP_START= 0x6263
POS_BNAME_START= 0x66C0
POS_BANK_START = 0x62A8

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

def get_tune_step(mmap):
    tsidx = ord(mmap[POS_TUNE_STEP]) & 0x0F
    if tsidx > 8:
        # This seems to sometimes contain garbage
        print "Taking default TS of 5kHz"
        tsidx = chirp_common.TUNING_STEPS.index(5.0)
    try:
        return chirp_common.TUNING_STEPS[tsidx]
    except IndexError:
        raise errors.InvalidDataError("Radio has unknown TS index %i" % tsidx)

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
    val = struct.unpack("B", mmap[POS_DUPX_TONE])[0] & 0x1C
    
    if (val & 0x0C) == 0x0C:
        return "TSQL"
    elif (val & 0x18) == 0x18:
        return "DTCS"
    elif (val & 0x04) == 0x04:
        return "Tone"
    else:
        return ""

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

def get_skip(mmap, number):
    byte = number / 8
    bit = 1 << (number % 8)

    if ord(mmap[POS_SKIP_START + byte]) & bit:
        return "S"
    elif ord(mmap[POS_PSKIP_START + byte]) & bit:
        return "P"
    else:
        return ""

def get_bank_names(mmap):
    names = []
    for i in range(0, 26):
        pos = POS_BNAME_START + (i * 8)
        label = mmap[pos:pos+8].rstrip()
        name = "%s - %s" % (chr(i + ord("A")), label)
        names.append(name)
    
    return names

def get_bank_info(mmap, number):
    bank = ord(mmap[POS_BANK_START + (number * 2)])
    bidx = ord(mmap[POS_BANK_START + (number * 2) + 1])

    return bank, bidx

def get_memory(_map, number):
    if not is_used(_map, number):
        raise errors.InvalidMemoryLocation("Location %i is empty" % number)

    mmap = get_raw_memory(_map, number)
    
    if get_mode(mmap) == "DV":
        mem = chirp_common.DVMemory()
        mem.dv_urcall = mmap[8:16].strip()
        mem.dv_rpt1call = mmap[16:24].strip()
        mem.dv_rpt2call = mmap[24:32].strip()
    else:
        mem = chirp_common.Memory()

    mem.number = number

    mem.freq = get_freq(mmap)
    mem.name = get_name(mmap)

    mem.rtone = get_rtone(mmap)
    mem.ctone = get_ctone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.tmode = get_tone_enabled(mmap)
    mem.dtcs_polarity = get_dtcs_polarity(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_dup_off(mmap)
    mem.mode = get_mode(mmap)
    mem.tuning_step = get_tune_step(mmap)
    mem.skip = get_skip(_map, number)

    # FIXME: Potential for optimization here
    banks = get_bank_names(_map)
    b, i = get_bank_info(_map, number)
    if b == 0xFF:
        mem.bank = None
        mem.bank_index = -1
    else:
        mem.bank = banks[b]
        mem.bank_index = i

    return mem

def erase_memory(mmap, number):
    set_used(mmap, number, False)

def set_freq(mmap, freq):
    mmap[POS_FREQ_START] = struct.pack(">I", int(freq * 1000000))

def set_tune_step(mmap, ts):
    val = ord(mmap[POS_TUNE_STEP]) & 0xF0
    tsidx = chirp_common.TUNING_STEPS.index(ts)
    val |= (tsidx & 0x0F)
    mmap[POS_TUNE_STEP] = val

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

def set_tone_enabled(mmap, mode):
    # mask = 0xC3
    # The bottom two bits seem to indicate MSK/packet mode, and seem to
    # want to get set sometimes.  Explicitly ignore those so they are zeroed
    # for now.  Worst case is we unset MSK mode if set, somehow.
    mask = 0xE0
    val = ord(mmap[POS_DUPX_TONE]) & mask

    if mode == "Tone":
        val |= 0x04
    elif mode == "TSQL":
        val |= 0x2C
    elif mode == "DTCS":
        val |= 0x18

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

def set_skip(mmap, number, skip):
    if skip not in ["", "P", "S"]:
        raise errors.InvalidDataError("Skip mode not supported by this model")

    byte = number / 8
    bit = 1 << (number % 8)

    if skip:
        orval = bit
    else:
        orval = 0

    pval = ord(mmap[POS_PSKIP_START + byte]) & ~bit
    if skip == "P":
        pval |= bit

    sval = ord(mmap[POS_SKIP_START + byte]) & ~bit
    if skip == "S":
        sval |= bit
    
    mmap[POS_PSKIP_START + byte] = pval
    mmap[POS_SKIP_START + byte] = sval

def parse_bank_name(bname):
    chr = bname[0]
    idx = ord(bname[0]) - ord("A")

    if idx < 0 or idx > 25:
        raise errors.InvalidDataError("Invalid bank number %i" % idx)

    return idx

def set_bank_info(mmap, number, bank, index):
    if bank >= 25:
        raise errors.InvalidDataError("Invalid bank number %i" % bank)

    mmap[POS_BANK_START + (number * 2)] = bank
    mmap[POS_BANK_START + (number * 2) + 1] = index

def set_memory(_map, mem):
    mmap = get_raw_memory(_map, mem.number)

    if isinstance(mem, chirp_common.DVMemory):
        mmap[8] = mem.dv_urcall.ljust(8)
        mmap[16] = mem.dv_rpt1call.ljust(8)
        mmap[24] = mem.dv_rpt2call.ljust(8)

    set_freq(mmap, mem.freq)
    set_name(mmap, mem.name)
    set_duplex(mmap, mem.duplex)
    set_dup_offset(mmap, mem.offset)
    set_rtone(mmap, mem.rtone)
    set_ctone(mmap, mem.ctone)
    set_dtcs(mmap, mem.dtcs)
    set_dtcs_polarity(mmap, mem.dtcs_polarity)
    set_tone_enabled(mmap, mem.tmode)
    set_mode(mmap, mem.mode)
    set_tune_step(mmap, mem.tuning_step)

    set_raw_memory(_map, mmap, mem.number)

    set_used(_map, mem.number, True)
    set_skip(_map, mem.number, mem.skip)

    set_bank_info(_map, mem.number, parse_bank_name(mem.bank), mem.bank_index)

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

def call_location(base, index):
    return base + (8 * (index - 1))

def get_urcall(mmap, number):
    if number > 60:
        raise errors.InvalidDataError("URCALL index must be <= 60")

    start = call_location(POS_URCALL, number)
    return mmap[start:start+8].rstrip()

def get_rptcall(mmap, number):
    if number > 60:
        raise errors.InvalidDataError("RPTCALL index must be <= 60")

    start = call_location(POS_RPTCALL, number)
    return mmap[start:start+8].rstrip()

def get_mycall(mmap, number):
    if number > 6:
        raise errors.InvalidDataError("MYCALL index must be <= 6")

    start = POS_MYCALL + (12 * (number -1 ))
    return mmap[start:start+8].rstrip()

def set_urcall(mmap, number, call):
    if number > 60:
        raise errors.InvalidDataError("URCALL index must be <= 60")

    start = call_location(POS_URCALL, number)
    mmap[start] = call.ljust(8)

def set_rptcall(mmap, number, call):
    if number > 60:
        raise errors.InvalidDataError("RPTCALL index must be <= 60")

    start = call_location(POS_RPTCALL, number)
    mmap[start] = call.ljust(8)

def set_mycall(mmap, number, call):
    if number > 6:
        raise errors.InvalidDataError("MYCALL index must be <= 6")

    start = POS_MYCALL + (12 * (number - 1))
    mmap[start] = call.ljust(8)
