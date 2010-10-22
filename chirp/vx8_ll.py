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

from chirp import chirp_common, util, errors
from chirp.memmap import MemoryMap

POS_DUP    = 1
POS_MODE   = 1
POS_STEP   = 1
POS_FREQ   = 2
POS_TMODE  = 5
POS_NAME   = 8
POS_OFFSET = 25
POS_TONE   = 27
POS_DTCS   = 28

MEM_FLG_BASE = 0x2C4A
MEM_LOC_BASE = 0x328A
MEM_LOC_SIZE = 32

STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.insert(2, 0.0) # There is a skipped tuning step ad index 2 (?)

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    [" ",] + \
    [chr(x) for x in range(ord("a"), ord("z")+1)] + \
    list(".,:;*#_-/&()@!?^ ") + list("?" * 100)

def get_mem_offset(number):
    return MEM_LOC_BASE + (number * MEM_LOC_SIZE)

def get_raw_memory(mmap, number):
    offset = get_mem_offset(number)
    return MemoryMap(mmap[offset:offset + MEM_LOC_SIZE])

def _get_freq_at(mmap, index):
    khz = (int("%02x" % ord(mmap[index]), 10) * 10000) + \
        (int("%02x" % ord(mmap[index+1]), 10) * 100) + \
        (int("%02x" % ord(mmap[index+2]), 10))

    mult1250 = (khz+0.5) / 12.5
    mult0625 = (khz+0.25) / 6.25
    
    if mult1250 == int(mult1250):
        khz += 0.5
    elif mult0625 == int(mult0625):
        khz += 0.25

    return khz / 1000.0

def _set_freq_at(mmap, index, freq):
    val = util.bcd_encode(freq, width=6)[:3]
    mmap[index] = val

def get_freq(mmap):
    return _get_freq_at(mmap, POS_FREQ)

def set_freq(mmap, freq):
    return _set_freq_at(mmap, POS_FREQ, int(freq * 1000))

def get_duplex(mmap):
    val = (ord(mmap[POS_DUP]) & 0x30) >> 4

    dupmap = {
        0x00 : "",
        0x01 : "-",
        0x02 : "+",
        0x03 : "split", # non-standard repeater shift
        }

    return dupmap[val]

def set_duplex(mmap, duplex):
    val = (ord(mmap[POS_DUP]) & 0xCF)

    if duplex == "-":
        val |= 0x10
    elif duplex == "+":
        val |= 0x20
    elif duplex == "split":
        val |= 0x30

    mmap[POS_DUP] = val

def get_offset(mmap):
    khz = (int("%02x" % ord(mmap[POS_OFFSET]), 10) * 100) + \
        (int("%02x" % ord(mmap[POS_OFFSET+1]), 10))

    return khz / 1000.0

def set_offset(mmap, offset):
    val = util.bcd_encode(int(offset * 1000), width=4)[:3]
    mmap[POS_OFFSET] = val

def get_mode(mmap):
    # [31]&0x80 is "AUTO" mode flag
    val = ord(mmap[POS_MODE]) & 0xC0

    modemap = {
        0x00 : "FM",
        0x40 : "AM",
        0x80 : "WFM",
        }

    return modemap[val]

def set_mode(mmap, mode):
    val = ord(mmap[POS_MODE]) & 0x3F

    modemap = {
        "FM" : 0x00,
        "AM" : 0x40,
        "WFM": 0x80,
        }

    if not modemap.has_key(mode):
        raise errors.InvalidDataError("Mode %s not supported" % mode)

    val |= modemap[mode]
    mmap[POS_MODE] = val

def get_name(mmap):
    name = ""
    for i in mmap[POS_NAME:POS_NAME+16]:
        if i == chr(0xFF):
            break
        name += CHARSET[ord(i)]

    return name

def set_name(mmap, name):
    i = 0
    for char in name.ljust(16)[:16]:
        if not char in CHARSET:
            char = " "
        mmap[POS_NAME+i] = CHARSET.index(char)
        i += 1        

def get_ts(mmap):
    # [31]&0x10 is "AUTO" tuning step flag
    val = ord(mmap[POS_STEP]) & 0x0F
    return STEPS[val]

def set_ts(mmap, ts):
    if not ts in STEPS:
        raise errors.InvalidDataError("Unsupported tune step %.1f" % ts)

    val = ord(mmap[POS_STEP]) & 0xF0
    val |= STEPS.index(ts)
    mmap[POS_STEP] = val

def get_tmode(mmap):
    val = ord(mmap[POS_TMODE]) & 0x0F

    tmodemap = {
        0x00 : "",
        0x01 : "Tone",
        0x02 : "TSQL",
        0x03 : "DTCS",
        # Advanced modes not supported yet
        }

    return tmodemap.get(val, "")
        
def set_tmode(mmap, tmode):
    tmodemap = {
        ""     : 0x00,
        "Tone" : 0x01,
        "TSQL" : 0x02,
        "DTCS" : 0x03,
        }
    if tmode not in tmodemap.keys():
        raise errors.InvalidDataError("Tone mode %s not supported" % tmode)

    val = ord(mmap[POS_TMODE]) & 0xF0
    val |= tmodemap[tmode]
    mmap[POS_TMODE] = val

def get_tone(mmap):
    val = ord(mmap[POS_TONE]) & 0x3F
    return chirp_common.TONES[val]

def set_tone(mmap, tone):
    if tone not in chirp_common.TONES:
        raise errors.InvalidDataError("Unsupported tone %.1f" % tone)

    val = ord(mmap[POS_TONE]) & 0xC0
    val |= chirp_common.TONES.index(tone)
    mmap[POS_TONE] = val

def get_dtcs(mmap):
    val = ord(mmap[POS_DTCS]) & 0x7F
    if val > 0x67:
        raise errors.InvalidDataError("Unknown DTCS code 0x%02x" % val)
    return chirp_common.DTCS_CODES[val]

def set_dtcs(mmap, dtcs):
    val = ord(mmap[POS_DTCS]) & 0x80
    if dtcs not in chirp_common.DTCS_CODES:
        raise errors.InvalidDataError("Unsupported DTCS code 0x%02x" % dtcs)
    mmap[POS_DTCS] = val | chirp_common.DTCS_CODES.index(dtcs)

def is_used(mmap, number):
    val = ord(mmap[MEM_FLG_BASE + number])

    if val & 0x03:
        return True
    else:
        return False

def set_is_used(mmap, number, used):
    if used:
        mmap[MEM_FLG_BASE + number] = 0x03
    else:
        mmap[MEM_FLG_BASE + number] = 0x00

def get_skip(mmap, number):
    val = ord(mmap[MEM_FLG_BASE + number])

    if val & 0x08:
        return "P"
    elif val & 0x04:
        return "S"
    else:
        return ""

def set_skip(mmap, number, skip):
    val = ord(mmap[MEM_FLG_BASE + number]) & 0x03

    if skip == "P":
        val |= 0x08
    elif skip == "S":
        val |= 0x04

    mmap[MEM_FLG_BASE + number] = val

def get_memory(_map, number):
    index = number - 1
    mem = chirp_common.Memory()
    mem.number = number
    if not is_used(_map, index):
        mem.empty = True
        return mem

    mmap = get_raw_memory(_map, index)
    mem.freq = get_freq(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_offset(mmap)
    mem.mode = get_mode(mmap)
    mem.name = get_name(mmap)
    mem.tuning_step = get_ts(mmap)
    mem.tmode = get_tmode(mmap)
    mem.rtone = mem.ctone = get_tone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.skip = get_skip(_map, index)
    
    return mem

def initialize(mmap):
    mmap[0] = "\x00\x00\x14\x65\x20\xc0\x00\x00"
    mmap[8] = "\xff" * 16
    mmap[24] = "\x00\x10\x00\x08\x00\x0d\x00\x18"

def set_memory(_map, mem):
    index = mem.number - 1
    mmap = get_raw_memory(_map, index)

    if not is_used(_map, index):
        initialize(mmap)

    set_freq(mmap, mem.freq)
    set_duplex(mmap, mem.duplex)
    set_offset(mmap, mem.offset)
    set_mode(mmap, mem.mode)
    set_name(mmap, mem.name)
    set_ts(mmap, mem.tuning_step)
    set_tmode(mmap, mem.tmode)
    set_tone(mmap, mem.rtone)
    set_dtcs(mmap, mem.dtcs)

    _map[get_mem_offset(index)] = mmap.get_packed()
    set_is_used(_map, index, True)
    set_skip(_map, index, mem.skip)

    return _map

def erase_memory(map, number):
    set_is_used(map, number-1, False)
    return map

def update_checksum(mmap):
    cs = 0
    for i in range(0x0000, 0xFECA):
        cs += ord(mmap[i])
    cs %= 256
    print "Checksum old=%02x new=%02x" % (ord(mmap[0xFECA]), cs)
    mmap[0xFECA] = cs
