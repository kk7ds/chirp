#!/usr/bin/python
#
# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common
from chirp import util
from chirp.memmap import MemoryMap

POS_STEP   = 1
POS_DUP    = 1
POS_FREQ   = 2
POS_MODE   = 1
POS_TMODE  = 5
POS_NAME   = 6
POS_OFFSET = 12
POS_TONE   = 15
POS_DTCS   = 16

MEM_FLG_BASE = 0x1ECA
MEM_LOC_BASE = 0x21CA
MEM_LOC_SIZE = 18

STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(6.25)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.append(9.0)

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    list(" +-/?[]__?????????$%%?**.|=\\?@") + \
    list("?" * 100)

def get_mem_offset(number):
    return MEM_LOC_BASE + (number * MEM_LOC_SIZE)

def get_raw_memory(mmap, number):
    offset = get_mem_offset(number)
    return MemoryMap(mmap[offset:offset+MEM_LOC_SIZE])

def get_used(mmap, number):
    byte = int(number / 2)
    nibble = number % 2

    val = ord(mmap[MEM_FLG_BASE + byte])

    if nibble:
        return (val & 0x30) == 0x30
    else:
        return (val & 0x03) == 0x03

def set_used(mmap, number, used):
    byte = int(number / 2)
    nibble = number % 2

    val = ord(mmap[MEM_FLG_BASE + byte])

    bits = 0x03

    if nibble:
        bits = 0x30
        mask = 0x0F
    else:
        bits = 0x03
        mask = 0xF0

    val &= mask
    if used:
        val |= bits

    mmap[MEM_FLG_BASE + byte] = val

def _get_freq_at(mmap, index):
    khz = (int("%02x" % ord(mmap[index]), 10) * 10000) + \
        (int("%02x" % ord(mmap[index+1]), 10) * 100) + \
        (int("%02x" % ord(mmap[index+2]), 10))
    return khz / 1000.0

def _set_freq_at(mmap, index, freq):
    val = util.bcd_encode(freq, width=6)[:3]
    mmap[index] = val

def get_freq(mmap):
    return _get_freq_at(mmap, POS_FREQ)

def set_freq(mmap, freq):
    return _set_freq_at(mmap, POS_FREQ, int(freq * 1000))

def get_duplex(mmap):
    val = ord(mmap[POS_DUP]) & 0x30

    dupmap = {
        0x00 : "",
        0x10 : "-",
        0x20 : "+",
        0x30 : "split",
        }

    return dupmap[val]

def set_duplex(mmap, duplex):
    val = ord(mmap[POS_DUP]) & 0xCF

    dupmap = {
        ""      : 0x00,
        "-"     : 0x10,
        "+"     : 0x20,
        "split" : 0x30,
        }

    mmap[POS_DUP] = val | dupmap[duplex]

def get_tmode(mmap):
    val = ord(mmap[POS_TMODE]) & 0x03

    tmodemap = {
        0x00 : "",
        0x01 : "Tone",
        0x02 : "TSQL",
        0x03 : "DTCS",
        }

    return tmodemap[val]

def set_tmode(mmap, tmode):
    tmodemap = {
        ""     : 0x00,
        "Tone" : 0x01,
        "TSQL" : 0x02,
        "DTCS" : 0x03,
        }

    if not tmodemap.has_key(tmode):
        raise errors.InvalidDataError("Tone mode %s not supported" % tmode)

    val = ord(mmap[POS_TMODE]) & 0xF0
    val |= tmodemap[tmode]
    mmap[POS_TMODE] = val

def get_tone(mmap):
    val = ord(mmap[POS_TONE]) & 0x3F

    return chirp_common.TONES[val]

def set_tone(mmap, tone):
    val = ord(mmap[POS_TONE]) & 0xC0

    if tone not in chirp_common.TONES:
        raise errors.InvalidDataError("Tone %.1f not supported" % tone)

    val |= chirp_common.TONES.index(tone)
    mmap[POS_TONE] = val

def get_dtcs(mmap):
    val = ord(mmap[POS_DTCS]) & 0x3F

    return chirp_common.DTCS_CODES[val]

def set_dtcs(mmap, dtcs):
    val = ord(mmap[POS_DTCS]) & 0xC0

    if dtcs not in chirp_common.DTCS_CODES:
        raise errors.InvalidDataError("DTCS code %03i not supported" % dtcs)

    val |= chirp_common.DTCS_CODES.index(dtcs)
    mmap[POS_DTCS] = val

def get_offset(mmap):
    return _get_freq_at(mmap, POS_OFFSET)

def set_offset(mmap, offset):
    _set_freq_at(mmap, POS_OFFSET, int(offset * 1000))

def get_ts(mmap):
    val = ord(mmap[POS_STEP]) & 0x0F
    return STEPS[val]

def set_ts(mmap, ts):
    if not ts in STEPS:
        raise errors.InvalidDataError("Unsupported tune step %.1f" % ts)

    val = ord(mmap[POS_STEP]) & 0xF0
    val |= STEPS.index(ts)
    mmap[POS_STEP] = val

def get_name(mmap):
    name = ""
    for i in mmap[POS_NAME:POS_NAME+6]:
        if ord(i) == 0xFF:
            break
        name += CHARSET[ord(i) & 0x7F]
    return name.rstrip()

def set_name(mmap, name):
    i = 0
    for char in name.ljust(6)[:6]:
        if not char in CHARSET:
            char = " "
        mmap[POS_NAME+i] = CHARSET.index(char)
        i += i

def get_mode(mmap):
    val = ord(mmap[POS_MODE]) & 0xC0

    modemap = {
        0x00 : "FM",
        0x80 : "WFM",
        0x40 : "AM",
        }

    return modemap[val]

def set_mode(mmap, mode):
    val = ord(mmap[POS_MODE]) & 0x3F

    modemap = {
        "FM"  : 0x00,
        "WFM" : 0x80,
        "AM"  : 0x40,
        }

    mmap[POS_MODE] = val | modemap[mode]

def get_skip(map, number):
    byte = int(number / 2)
    nibble = number % 2

    val = ord(map[MEM_FLG_BASE + byte])

    if nibble:
        val = (val & 0xC0) >> 4
    else:
        val = val & 0x0C

    if val == 0x08:
        return "P"
    elif val == 0x04:
        return "S"
    else:
        return ""
    
def set_skip(map, number, skip):
    byte = int(number / 2)
    nibble = number % 2

    val = ord(map[MEM_FLG_BASE + byte])

    if skip == "P":
        bits = 0x08
    elif skip == "S":
        bits = 0x04
    else:
        bits = 0x00

    if nibble:
        bits <<= 4
        mask = 0x3F
    else:
        mask = 0xF3

    map[MEM_FLG_BASE + byte] = (val & mask) | bits

def get_memory(map, number):
    mmap = get_raw_memory(map, number - 1)

    mem = chirp_common.Memory()
    mem.number = number
    if not get_used(map, number - 1):
        mem.empty = True
        return mem

    mem.freq = get_freq(mmap)
    mem.duplex = get_duplex(mmap)
    mem.tmode = get_tmode(mmap)
    mem.rtone = get_tone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.offset = get_offset(mmap)
    mem.tuning_step = get_ts(mmap)
    mem.name = get_name(mmap)
    mem.mode = get_mode(mmap)
    mem.skip = get_skip(map, number - 1)

    return mem

def set_unknowns(mmap):
    mmap[0] = \
        "\x00\x00\x14\x40\x00\xC0\xff\xff" + \
        "\xff\xff\xff\xff\x00\x06\x00\x08" + \
        "\x00\x0d"
    
def set_memory(_map, mem):
    number = mem.number - 1
    mmap = get_raw_memory(_map, number)

    if not get_used(_map, number):
        set_unknowns(mmap)

    set_freq(mmap, mem.freq)
    set_duplex(mmap, mem.duplex)
    set_mode(mmap, mem.mode)
    set_name(mmap, mem.name)
    set_ts(mmap, mem.tuning_step)
    set_tone(mmap, mem.rtone)
    set_dtcs(mmap, mem.dtcs)
    set_tmode(mmap, mem.tmode)
    set_offset(mmap, mem.offset)

    _map[get_mem_offset(number)] = mmap.get_packed()
    set_used(_map, number, True)
    set_skip(_map, number, mem.skip)

    return _map

def erase_memory(map, number):
    set_used(map, number - 1, False)
