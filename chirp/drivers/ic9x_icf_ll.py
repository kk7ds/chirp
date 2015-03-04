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

import struct
from chirp import chirp_common
from chirp.memmap import MemoryMap

MEM_LOC_SIZE_A = 20
MEM_LOC_SIZE_B = MEM_LOC_SIZE_A + 1 + (3 * 8)

POS_FREQ = 0
POS_OFFSET = 3
POS_TONE = 5
POS_MODE = 6
POS_DTCS = 7
POS_TS = 8
POS_DTCSPOL = 11
POS_DUPLEX = 11
POS_NAME = 12


def get_mem_offset(number):
    """Get the offset into the memory map for memory @number"""
    if number < 850:
        return MEM_LOC_SIZE_A * number
    else:
        return (MEM_LOC_SIZE_A * 850) + (MEM_LOC_SIZE_B * (number - 850))


def get_raw_memory(mmap, number):
    """Return a raw representation of memory @number"""
    offset = get_mem_offset(number)
    if number >= 850:
        size = MEM_LOC_SIZE_B
    else:
        size = MEM_LOC_SIZE_A
    return MemoryMap(mmap[offset:offset+size])


def get_freq(mmap):
    """Return the memory frequency"""
    if ord(mmap[10]) & 0x10:
        mult = 6250
    else:
        mult = 5000
    val, = struct.unpack(">I", "\x00" + mmap[POS_FREQ:POS_FREQ+3])
    return val * mult


def get_offset(mmap):
    """Return the memory offset"""
    val, = struct.unpack(">H", mmap[POS_OFFSET:POS_OFFSET+2])
    return val * 5000


def get_rtone(mmap):
    """Return the memory rtone"""
    val = (ord(mmap[POS_TONE]) & 0xFC) >> 2
    return chirp_common.TONES[val]


def get_ctone(mmap):
    """Return the memory ctone"""
    val = (ord(mmap[POS_TONE]) & 0x03) | ((ord(mmap[POS_TONE+1]) & 0xF0) >> 4)
    return chirp_common.TONES[val]


def get_dtcs(mmap):
    """Return the memory dtcs value"""
    val = ord(mmap[POS_DTCS]) >> 1
    return chirp_common.DTCS_CODES[val]


def get_mode(mmap):
    """Return the memory mode"""
    val = ord(mmap[POS_MODE]) & 0x07

    modemap = ["FM", "NFM", "WFM", "AM", "DV", "FM"]

    return modemap[val]


def get_ts(mmap):
    """Return the memory tuning step"""
    val = (ord(mmap[POS_TS]) & 0xF0) >> 4
    if val == 14:
        return 5.0  # Coerce "Auto" to 5.0

    icf_ts = list(chirp_common.TUNING_STEPS)
    icf_ts.insert(2, 8.33)
    icf_ts.insert(3, 9.00)
    icf_ts.append(100.0)
    icf_ts.append(125.0)
    icf_ts.append(200.0)

    return icf_ts[val]


def get_dtcs_polarity(mmap):
    """Return the memory dtcs polarity"""
    val = (ord(mmap[POS_DTCSPOL]) & 0x03)

    pols = ["NN", "NR", "RN", "RR"]

    return pols[val]


def get_duplex(mmap):
    """Return the memory duplex"""
    val = (ord(mmap[POS_DUPLEX]) & 0x0C) >> 2

    dup = ["", "-", "+", ""]

    return dup[val]


def get_name(mmap):
    """Return the memory name"""
    return mmap[POS_NAME:POS_NAME+8]


def get_memory(_mmap, number):
    """Get memory @number from global memory map @_mmap"""
    mmap = get_raw_memory(_mmap, number)
    mem = chirp_common.Memory()
    mem.number = number
    mem.freq = get_freq(mmap)
    mem.offset = get_offset(mmap)
    mem.rtone = get_rtone(mmap)
    mem.ctone = get_ctone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.mode = get_mode(mmap)
    mem.tuning_step = get_ts(mmap)
    mem.dtcs_polarity = get_dtcs_polarity(mmap)
    mem.duplex = get_duplex(mmap)
    mem.name = get_name(mmap)

    mem.empty = mem.freq == 0

    return mem
