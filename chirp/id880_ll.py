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
POS_TUNE_STEP  =  8
POS_CODE       = 19

POS_USED_START = 0xAA80
POS_SKIP_FLAGS = 0xAAFE
POS_PSKP_FLAGS = 0xAB82

POS_BANKS      = 0xAD00

POS_MYCALL     = 0xDE56
POS_URCALL     = 0xDE9E
POS_RPTCALL    = 0xF408

MEM_LOC_SIZE = 41

def bank_name(index):
    char = chr(ord("A") + index)
    return "BANK-%s" % char

def get_mem_offset(number):
    return (number * MEM_LOC_SIZE)

def get_raw_memory(mmap, number):
    offset = get_mem_offset(number)
    return MemoryMap(mmap[offset:offset + MEM_LOC_SIZE])

def get_freq(mmap):
    val = struct.unpack(">i", "\x00" + mmap[:3])[0]
    if val & 0x00200000:
        mult = 6.25
    else:
        mult = 5.0
    val &= 0x0003FFFF
    
    return (val * mult) / 1000.0

def set_freq(mmap, freq):
    if chirp_common.is_fractional_step(freq):
        mult = 6.25
        flag = 0x20
    else:
        mult = 5
        flag = 0x00

    mmap[POS_FREQ_START] = struct.pack(">i", int((freq * 1000) / mult))[1:]
    mmap[POS_FREQ_START] = ord(mmap[POS_FREQ_START]) | flag

def get_ts(mmap):
    tsidx = ord(mmap[POS_TUNE_STEP]) >> 4

    return chirp_common.TUNING_STEPS[tsidx]

def set_ts(mmap, ts):
    tsidx = chirp_common.TUNING_STEPS.index(ts)

    val = mmap[POS_TUNE_STEP] & 0x0F
    mmap[POS_TUNE_STEP] = val | (tsidx << 4)

def get_name(mmap):
    return mmap[POS_NAME_START:POS_NAME_END].strip()

def set_name(mmap, name):
    mmap[POS_NAME_START] = name.rstrip()[:8].ljust(8)

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
    elif val == 7:
        return ""

    try:
        return ID880_TMODES[val]
    except IndexError:
        raise errors.InvalidDataError("Unknown tone mode 0x%02x" % val)

def set_tmode(mmap, tmode):
    if tmode not in ID880_TMODES:
        raise errors.InvalidDataError("Tone Mode %s not supported" % tmode)

    val = struct.unpack("b", mmap[POS_TMODE])[0] & 0x8F
    val |= (ID880_TMODES.index(tmode) << 4)
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

def decode_call(sevenbytes):
    if len(sevenbytes) != 7:
        raise Exception("%i (!=7) bytes to decode_call" % len(sevenbytes))

    i = 0
    rem = 0
    str = ""
    for byte in [ord(x) for x in sevenbytes]:
        i += 1

        mask = (1 << i) - 1           # Mask is 0x01, 0x03, 0x07, etc

        code = (byte >> i) | rem      # Code gets the upper bits of remainder
                                      # plus all but the i lower bits of this
                                      # byte
        str += chr(code)

        rem = (byte & mask) << 7 - i  # Remainder for next time are the masked
                                      # bits, moved to the high places for the
                                      # next round

    # After seven trips gathering overflow bits, we chould have seven
    # left, which is the final character
    str += chr(rem)

    return str.rstrip()

def encode_call(call):
    call = call.ljust(8)
    val = 0
    
    buf = []
    
    for i in range(0, 8):
        byte = ord(call[i])
        if i > 0:
            last = buf[i-1]
            himask = ~((1 << (7-i)) - 1) & 0x7F
            last |= (byte & himask) >> (7-i)
            buf[i-1] = last
        else:
            himask = 0

        buf.append((byte & ~himask) << (i+1))

    return "".join([chr(x) for x in buf[:7]])

def get_mem_urcall(mmap):
    return decode_call(mmap[20:20+7])

def get_mem_rpt1call(mmap):
    return decode_call(mmap[27:27+7])

def get_mem_rpt2call(mmap):
    return decode_call(mmap[34:34+7])

def get_bank(mmap, number):
    pos = POS_BANKS + (number * 2)
    bnk, idx = struct.unpack("BB", mmap[pos:pos+2])

    if bnk == 0xFF:
        return None, -1

    return bnk, idx

def get_digital_code(mmap):
    return ord(mmap[POS_CODE]) & 0x7F

def _get_memory(mmap, number):
    if get_mode(mmap) == "DV":
        mem = chirp_common.DVMemory()
        mem.dv_urcall = get_mem_urcall(mmap)
        mem.dv_rpt1call = get_mem_rpt1call(mmap)
        mem.dv_rpt2call = get_mem_rpt2call(mmap)
        mem.dv_code = get_digital_code(mmap)
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
    mem.tuning_step = get_ts(mmap)

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

    mem.bank, mem.bank_index = get_bank(_map, number)

    return mem

def set_urcall(mmap, call):
    mmap[20] = encode_call(call)

def set_rpt1call(mmap, call):
    mmap[27] = encode_call(call)

def set_rpt2call(mmap, call):
    mmap[34] = encode_call(call)

def set_bank(mmap, number, bank, idx):
    if bank is None:
        bank = idx = 0xFF
    elif bank > 26 or idx > 99:
        raise errors.InvalidDataError("Invalid bank/index")

    pos = POS_BANKS + (number * 2)
    mmap[pos] = struct.pack("BB", bank, idx)

def set_digital_code(mmap, code):
    if code < 0 or code > 99:
        raise errors.InvalidDataError("Digital code %i out of range" % code)

    mmap[POS_CODE] = code

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
    set_ts(mmap, mem.tuning_step)

    if isinstance(mem, chirp_common.DVMemory):
        set_urcall(mmap, mem.dv_urcall)
        set_rpt1call(mmap, mem.dv_rpt1call)
        set_rpt2call(mmap, mem.dv_rpt2call)
        set_digital_code(mmap, mem.dv_code)

    _map[get_mem_offset(mem.number)] = mmap.get_packed()

    set_skip(_map, mem.number, mem.skip)
    set_bank(_map, mem.number, mem.bank, mem.bank_index)
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
