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
POS_FREQ_END   =  3
POS_TSTEP      =  8
POS_NAME_START = 11
POS_NAME_END   = 19
POS_DUPX       =  6
POS_MODE       = 21
POS_TENB       = 10
POS_RTONE      =  5
POS_CTONE      =  6
POS_DTCS       =  7
POS_DTCS_POL   = 11
POS_DOFF_START =  3
POS_DOFF_END   =  5
POS_TUNE_FLAG  = 10
POS_CODE       = 16
POS_MYCALL     = 0x3220
POS_URCALL     = 0x3250
POS_RPTCALL    = 0x3570
POS_FLAGS      = 0x2bf4

MEM_LOC_SIZE  = 22
MEM_LOC_START = 0x20

ID800_TS = [5.0, 10.0, 12.5, 15, 20.0, 25.0, 30.0, 50.0, 100.0, 200.0, 6.25]

ID800_MODES = {
    0x00 : "FM",
    0x10 : "NFM",
    0x20 : "AM",
    0x30 : "NAM",
    0x40 : "DV",
}

ID800_MODES_REV = {}
for __val, __mode in ID800_MODES.items():
    ID800_MODES_REV[__mode] = __val

ID800_SPECIAL = {
    "C2" : 510,
    "C1" : 511,
    }
ID800_SPECIAL_REV = {
    510 : "C2",
    511 : "C1",
    }

for i in range(0, 5):
    idA = "%iA" % (i + 1)
    idB = "%iB" % (i + 1)
    num = 500 + i * 2
    ID800_SPECIAL[idA] = num
    ID800_SPECIAL[idB] = num + 1
    ID800_SPECIAL_REV[num] = idA
    ID800_SPECIAL_REV[num+1] = idB

def bank_name(index):
    char = chr(ord("A") + index)
    return "BANK-%s" % char

def is_used(mmap, number):
    if number == 510 or number == 511:
        return True
    return not ((ord(mmap[POS_FLAGS + number]) & 0x70) == 0x70)

def set_used(mmap, number, used):
    if number == 510 or number == 511:
        return

    val = ord(mmap[POS_FLAGS + number]) & 0x3F

    if not used:
        val |= 0x70

    mmap[POS_FLAGS + number] = val

ALPHA_CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"
NUMERIC_CHARSET = "0123456789+-=*/()|"

def get_name(mmap):
    nibbles = []

    for i in mmap[POS_NAME_START:POS_NAME_END]:
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
        elif this & 0x20:
            name += ALPHA_CHARSET[this & 0x1F]
        else:
            name += NUMERIC_CHARSET[this & 0x0F]

        i += 1

    return name.rstrip()

def get_freq_ts(mmap):
    fval = '\x00' + mmap[POS_FREQ_START:POS_FREQ_END]
    tsval = (ord(mmap[POS_TSTEP]) >> 4) & 0x0F

    if (ord(mmap[POS_TUNE_FLAG]) & 0x80) == 0x80:
        mult = 6250
    else:
        mult = 5000

    freq = (struct.unpack(">i", fval)[0] * mult)

    return freq, ID800_TS[tsval]

def get_duplex(mmap):
    val = struct.unpack("B", mmap[POS_DUPX])[0] & 0xC0
    if val == 0xC0:
        return "+"
    elif val == 0x80:
        return "-"
    else:
        return ""

def get_mode(mmap):
    val = struct.unpack("B", mmap[POS_MODE])[0] & 0x70
    try:
        return ID800_MODES[val]
    except KeyError:
        raise errors.InvalidDataError("Radio has invalid mode %02x" % val)

def get_rtone(mmap):
    idx = struct.unpack("B", mmap[POS_RTONE])[0]
    
    try:
        return chirp_common.TONES[idx]
    except IndexError:
        #print "Unknown rtone of %i, assuming default" % idx
        return chirp_common.TONES[8]

def get_ctone(mmap):
    idx = struct.unpack("B", mmap[POS_CTONE])[0] & 0x3F

    try:
        return chirp_common.TONES[idx]
    except IndexError:
        print "Unknown ctone of %i, assuming default" % idx
        return chirp_common.TONES[8]

def get_dtcs(mmap):
    idx = struct.unpack("B", mmap[POS_DTCS])[0]

    try:
        return chirp_common.DTCS_CODES[idx]
    except IndexError:
        print "Unknown DTCS index %i, assuming default" % idx
        return chirp_common.DTCS_CODES[0]

def get_tone_enabled(mmap):
    val = struct.unpack("B", mmap[POS_TENB])[0] & 0x03

    dtcs = tenc = tsql = False

    if val == 3:
        dtcs = True
    else:
        tenc = (val & 0x01) != 0
        tsql = (val & 0x02) != 0

    if tenc:
        return "Tone"
    elif tsql:
        return "TSQL"
    elif dtcs:
        return "DTCS"
    else:
        return ""

def get_dtcs_polarity(mmap):
    val = struct.unpack("B", mmap[POS_DTCS_POL])[0] & 0xC0

    pol_values = { 0x00 : "NN",
                   0x40 : "NR",
                   0x80 : "RN",
                   0xC0 : "RR" }

    return pol_values[val]        

def get_dup_offset(mmap):
    val = struct.unpack(">H", mmap[POS_DOFF_START:POS_DOFF_END])[0] & 0xEFFF

    return val * 5000

def get_mem_offset(number):
    if number < 510:
        return (number * MEM_LOC_SIZE) + MEM_LOC_START
    elif number == 511:
        return 0x2df4
    elif number == 510:
        return 0x2df4 + MEM_LOC_SIZE

def get_raw_memory(mmap, number):
    offset = get_mem_offset(number)
    #print "Offset for %i is %04x" % (number, offset)
    return MemoryMap(mmap[offset:offset + MEM_LOC_SIZE])

def get_call_indices(mmap):
    return ord(mmap[18]), ord(mmap[19]), ord(mmap[20])

def get_skip(mmap, number):
    val = ord(mmap[POS_FLAGS + number]) & 0x30

    if val == 0x20:
        return "P"
    elif val == 0x10:
        return "S"
    else:
        return ""

def get_bank(mmap, number):
    val = ord(mmap[POS_FLAGS + number]) & 0x0F

    if val == 0x0A:
        return None
    else:
        return val

def get_digital_code(mmap):
    return ord(mmap[POS_CODE]) & 0x7F

def _get_memory(_map, mmap):
    if get_mode(mmap) == "DV":
        mem = chirp_common.DVMemory()
        i_ucall, i_r1call, i_r2call = get_call_indices(mmap)
        mem.dv_urcall = get_urcall(_map, i_ucall)
        mem.dv_rpt1call = get_rptcall(_map, i_r1call)
        mem.dv_rpt2call = get_rptcall(_map, i_r2call)
        mem.dv_code = get_digital_code(mmap)
    else:
        mem = chirp_common.Memory()

    mem.freq, mem.tuning_step = get_freq_ts(mmap)
    mem.name = get_name(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_dup_offset(mmap)
    mem.mode = get_mode(mmap)
    mem.rtone = get_rtone(mmap)
    mem.ctone = get_ctone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.tmode = get_tone_enabled(mmap)
    mem.dtcs_polarity = get_dtcs_polarity(mmap)

    return mem

def get_memory(_map, number):
    index = number - 1
    if not is_used(_map, index):
        mem = chirp_common.Memory()
        mem.number = number
        if index < 500:
            mem.empty = True
            return mem
    else:
        mmap = get_raw_memory(_map, index)
        mem = _get_memory(_map, mmap)

    mem.number = number

    if index < 500:
        mem.skip = get_skip(_map, index)
        mem.bank = get_bank(_map, index)
    else:
        mem.extd_number = ID800_SPECIAL_REV[index]
        mem.immutable = ["number", "skip", "bank", "bank_index", "extd_number"]

    return mem

def call_location(base, index):
    return base + (8 * (index - 1))

def get_mycall(mmap, index):
    if index > 7:
        raise errors.InvalidDataError("MYCALL index must be <= 7")

    start = call_location(POS_MYCALL, index)

    return mmap[start:start+8].strip()

def get_urcall(mmap, index):
    if index > 99:
        raise errors.InvalidDataError("URCALL index must be <= 99")
    elif index == 0:
        return "CQCQCQ"

    start = call_location(POS_URCALL, index)

    return mmap[start:start+8].rstrip()

def get_rptcall(mmap, index):
    if index > 59:
        raise errors.InvalidDataError("RPTCALL index must be <= 59")
    elif index == 0:
        return ""

    start = call_location(POS_RPTCALL, index)

    return mmap[start:start+8].rstrip()

def parse_map_for_memory(mmap):
    """Returns a list of memories, given a valid memory map"""

    memories = []
    
    for i in range(500):        
        try:
            mem = get_memory(mmap, i)
        except errors.InvalidMemoryLocation:
            mem = None

        if mem:
            memories.append(mem)

    return memories

def set_freq_ts(mmap, freq, ts):
    tflag = ord(mmap[POS_TUNE_FLAG]) & 0x7F

    if chirp_common.is_fractional_step(freq):
        mult = 6250
        tflag |= 0x80
    else:
        mult = 5000

    mmap[POS_TUNE_FLAG] = tflag
    mmap[POS_FREQ_START] = struct.pack(">i", freq / mult)[1:]
    mmap[POS_TSTEP] = (ord(mmap[POS_TSTEP]) & 0x0F) | (ID800_TS.index(ts) << 4)

def set_name(mmap, _name, enabled=True):
    name = _name.ljust(6)[:6].upper()
    nibbles = []

    def val_of(char):
        if char == " ":
            return 0
        elif char.isalpha():
            return ALPHA_CHARSET.index(char) | 0x20
        else:
            return NUMERIC_CHARSET.index(char) | 0x10

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

    # Hmm, all of the sudden I have to disable this or it breaks?!
    # nibbles.append(0)

    val = ""

    for i in range(0, len(nibbles), 2):
        val += struct.pack("B", ((nibbles[i] << 4)| nibbles[i+1]))

    mmap[POS_NAME_START] = val

def set_duplex(mmap, duplex):
    mask = 0x3F # ~11000000
    val = struct.unpack("B", mmap[POS_DUPX])[0] & mask

    if duplex == "-":
        val |= 0x80
    elif duplex == "+":
        val |= 0xC0

    mmap[POS_DUPX] = val

def set_dup_offset(mmap, offset):
    val = struct.pack(">H", offset / 5000)

    mmap[POS_DOFF_START] = val

def set_mode(mmap, mode):
    mask = 0x8F # ~01110000
    val = struct.unpack("B", mmap[POS_MODE])[0] & mask

    try:
        val |= ID800_MODES_REV[mode]
    except Exception:
        raise errors.InvalidDataError("Unsupported mode `%s'" % mode)

    mmap[POS_MODE] = val

def set_rtone(mmap, tone):
    mmap[POS_RTONE] = struct.pack("B", chirp_common.TONES.index(tone))

def set_ctone(mmap, tone):
    val = struct.unpack("B", mmap[POS_CTONE])[0] & 0xC0
    mmap[POS_CTONE] = struct.pack("B", chirp_common.TONES.index(tone) | val)

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

def set_tone_enabled(mmap, mode):
    mask = 0xFC # ~00000011
    val = struct.unpack("B", mmap[POS_TENB])[0] & mask

    if mode == "DTCS":
        val |= 0x3
    else:
        if mode == "Tone":
            val |= 0x1
        if mode == "TSQL":
            val |= 0x2

    mmap[POS_TENB] = val

def set_call_indices(_map, mmap, urcall, r1call, r2call):
    ulist = ["CQCQCQ"]
    for i in range(1, 100):
        call = get_urcall(_map, i).rstrip()
        ulist.append(call)

    rlist = ["*NOTUSE*"]
    for i in range(1, 60):
        call = get_rptcall(_map, i).rstrip()
        rlist.append(call)

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
        raise errors.InvalidDataError("Call `%s' not in Repeater list" % r1call)

    try:
        if not r2call:
            r2index = 0
        else:
            r2index = rlist.index(r2call)
    except ValueError:
        raise errors.InvalidDataError("Call `%s' not in Repeater list" % r2call)

    mmap[18] = uindex
    mmap[19] = r1index
    mmap[20] = r2index

def set_skip(mmap, number, skip):
    val = ord(mmap[POS_FLAGS + number]) & 0xCF

    if skip == "P":
        val |= 0x20
    elif skip == "S":
        val |= 0x10
    elif skip == "":
        pass
    else:
        raise errors.InvalidDataError("Skip mode not supported by this model")

    mmap[POS_FLAGS + number] = val    

def set_bank(mmap, number, bank):
    if bank > 9:
        raise errors.InvalidDataError("Invalid bank number %i" % bank)

    if bank is None:
        index = 0x0A
    else:
        index = bank

    val = ord(mmap[POS_FLAGS + number]) & 0xF0
    val |= index
    mmap[POS_FLAGS + number] = val    

def set_digital_code(mmap, code):
    if code < 0 or code > 99:
        raise errors.InvalidDataError("Digital code %i out of range" % code)

    mmap[POS_CODE] = code

def set_memory(_map, mem):
    index = mem.number - 1
    mmap = get_raw_memory(_map, index)

    set_freq_ts(mmap, mem.freq, mem.tuning_step)
    set_name(mmap, mem.name)
    set_duplex(mmap, mem.duplex)
    set_dup_offset(mmap, mem.offset)
    set_mode(mmap, mem.mode)
    set_rtone(mmap, mem.rtone)
    set_ctone(mmap, mem.ctone)
    set_dtcs(mmap, mem.dtcs)
    set_tone_enabled(mmap, mem.tmode)
    set_dtcs_polarity(mmap, mem.dtcs_polarity)
    set_skip(_map, index, mem.skip)
    set_bank(_map, index, mem.bank)

    if isinstance(mem, chirp_common.DVMemory):
        set_call_indices(_map, mmap,
                         mem.dv_urcall, mem.dv_rpt1call, mem.dv_rpt2call)
        set_digital_code(mmap, mem.dv_code)

    _map[get_mem_offset(index)] = mmap.get_packed()

    set_used(_map, index, True)

    return _map

def erase_memory(mmap, number):
    set_used(mmap, number-1, False)

    return mmap

def set_mycall(mmap, index, call):
    if index > 7:
        raise errors.InvalidDataError("MYCALL index must be <= 7")

    start = call_location(POS_MYCALL, index)
    
    mmap[start] = call.ljust(8)

    return mmap

def set_urcall(mmap, index, call):
    if index > 99:
        raise errors.InvalidDataError("URCALL index must be <= 99")

    start = call_location(POS_URCALL, index)

    mmap[start] = call.ljust(8)

    return mmap

def set_rptcall(mmap, index, call):
    if index > 59:
        raise errors.InvalidDataError("RPTCALL index must be <= 59")

    start = call_location(POS_RPTCALL, index)

    mmap[start] = call.ljust(8)

    return mmap
