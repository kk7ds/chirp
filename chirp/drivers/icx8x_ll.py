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
from chirp.chirp_common import to_MHz
from chirp.util import StringStruct as struct

POS_FREQ_START = 0
POS_FREQ_END = 2
POS_OFFSET = 2
POS_NAME_START = 4
POS_NAME_END = 9
POS_RTONE = 9
POS_CTONE = 10
POS_DTCS = 11
POS_TUNE_STEP = 17
POS_TMODE = 21
POS_MODE = 21
POS_MULT_FLAG = 21
POS_DTCS_POL = 22
POS_DUPLEX = 22
POS_DIG = 23
POS_TXI = 23

POS_FLAGS_START = 0x1370
POS_MYCALL = 0x15E0
POS_URCALL = 0x1640
POS_RPCALL = 0x16A0
POS_RP2CALL = 0x1700

MEM_LOC_SIZE = 24

ICx8x_SPECIAL = {"C": 206}
ICx8x_SPECIAL_REV = {206: "C"}

for i in range(0, 3):
    idA = "%iA" % i
    idB = "%iB" % i
    num = 200 + i * 2
    ICx8x_SPECIAL[idA] = num
    ICx8x_SPECIAL[idB] = num + 1
    ICx8x_SPECIAL_REV[num] = idA
    ICx8x_SPECIAL_REV[num+1] = idB


def bank_name(index):
    char = chr(ord("A") + index)
    return "BANK-%s" % char


def get_freq(mmap, base):
    if (ord(mmap[POS_MULT_FLAG]) & 0x80) == 0x80:
        mult = 6250
    else:
        mult = 5000

    val = struct.unpack("<H", mmap[POS_FREQ_START:POS_FREQ_END])[0]

    return (val * mult) + to_MHz(base)


def set_freq(mmap, freq, base):
    tflag = ord(mmap[POS_MULT_FLAG]) & 0x7F

    if chirp_common.is_fractional_step(freq):
        mult = 6250
        tflag |= 0x80
    else:
        mult = 5000

    value = (freq - to_MHz(base)) // mult

    mmap[POS_MULT_FLAG] = tflag
    mmap[POS_FREQ_START] = struct.pack("<H", value)


def get_name(mmap):
    return mmap[POS_NAME_START:POS_NAME_END].strip()


def set_name(mmap, name):
    mmap[POS_NAME_START] = name.ljust(5)[:5]


def get_rtone(mmap):
    idx, = struct.unpack("B", mmap[POS_RTONE])

    return chirp_common.TONES[idx]


def set_rtone(mmap, tone):
    mmap[POS_RTONE] = chirp_common.TONES.index(tone)


def get_ctone(mmap):
    idx, = struct.unpack("B", mmap[POS_CTONE])

    return chirp_common.TONES[idx]


def set_ctone(mmap, tone):
    mmap[POS_CTONE] = chirp_common.TONES.index(tone)


def get_dtcs(mmap):
    idx, = struct.unpack("B", mmap[POS_DTCS])

    return chirp_common.DTCS_CODES[idx]


def set_dtcs(mmap, code):
    mmap[POS_DTCS] = chirp_common.DTCS_CODES.index(code)


def get_dtcs_polarity(mmap):
    val = struct.unpack("B", mmap[POS_DTCS_POL])[0] & 0xC0

    pol_values = {
        0x00: "NN",
        0x40: "NR",
        0x80: "RN",
        0xC0: "RR"}

    return pol_values[val]


def set_dtcs_polarity(mmap, polarity):
    val = struct.unpack("B", mmap[POS_DTCS_POL])[0] & 0x3F
    pol_values = {"NN": 0x00,
                  "NR": 0x40,
                  "RN": 0x80,
                  "RR": 0xC0}
    val |= pol_values[polarity]

    mmap[POS_DTCS_POL] = val


def get_dup_offset(mmap):
    val = struct.unpack("<H", mmap[POS_OFFSET:POS_OFFSET+2])[0]
    return val * 5000


def set_dup_offset(mmap, offset):
    val = struct.pack("<H", offset // 5000)
    mmap[POS_OFFSET] = val


def get_duplex(mmap):
    val = struct.unpack("B", mmap[POS_DUPLEX])[0] & 0x30

    if val == 0x10:
        return "-"
    elif val == 0x20:
        return "+"
    else:
        return ""


def set_duplex(mmap, duplex):
    val = struct.unpack("B", mmap[POS_DUPLEX])[0] & 0xCF

    if duplex == "-":
        val |= 0x10
    elif duplex == "+":
        val |= 0x20

    mmap[POS_DUPLEX] = val


def get_tone_enabled(mmap):
    val = struct.unpack("B", mmap[POS_TMODE])[0] & 0x03

    if val == 0x01:
        return "Tone"
    elif val == 0x02:
        return "TSQL"
    elif val == 0x03:
        return "DTCS"
    else:
        return ""


def set_tone_enabled(mmap, tmode):
    val = struct.unpack("B", mmap[POS_TMODE])[0] & 0xFC

    if tmode == "Tone":
        val |= 0x01
    elif tmode == "TSQL":
        val |= 0x02
    elif tmode == "DTCS":
        val |= 0x03

    mmap[POS_TMODE] = val


def get_tune_step(mmap):
    tsidx = struct.unpack("B", mmap[POS_TUNE_STEP])[0] & 0xF0
    tsidx >>= 4
    icx8x_ts = list(chirp_common.TUNING_STEPS)
    del icx8x_ts[1]

    try:
        return icx8x_ts[tsidx]
    except IndexError:
        raise errors.InvalidDataError("TS index %i out of range (%i)" %
                                      (tsidx, len(icx8x_ts)))


def set_tune_step(mmap, tstep):
    val = struct.unpack("B", mmap[POS_TUNE_STEP])[0] & 0x0F
    icx8x_ts = list(chirp_common.TUNING_STEPS)
    del icx8x_ts[1]

    tsidx = icx8x_ts.index(tstep)
    val |= (tsidx << 4)

    mmap[POS_TUNE_STEP] = val


def get_mode(mmap):
    val = struct.unpack("B", mmap[POS_DIG])[0] & 0x08

    if val == 0x08:
        return "DV"

    val = struct.unpack("B", mmap[POS_MODE])[0] & 0x20

    if val == 0x20:
        return "NFM"
    else:
        return "FM"


def set_mode(mmap, mode):
    dig = struct.unpack("B", mmap[POS_DIG])[0] & 0xF7

    val = struct.unpack("B", mmap[POS_MODE])[0] & 0xDF

    if mode == "FM":
        pass
    elif mode == "NFM":
        val |= 0x20
    elif mode == "DV":
        dig |= 0x08
    else:
        raise errors.InvalidDataError("%s mode not supported" % mode)

    mmap[POS_DIG] = dig
    mmap[POS_MODE] = val


def is_used(mmap, number):
    if number == ICx8x_SPECIAL["C"]:
        return True

    return (ord(mmap[POS_FLAGS_START + number]) & 0x20) == 0


def set_used(mmap, number, used=True):
    if number == ICx8x_SPECIAL["C"]:
        return

    val = struct.unpack("B", mmap[POS_FLAGS_START + number])[0] & 0xDF

    if not used:
        val |= 0x20

    mmap[POS_FLAGS_START + number] = val


def get_skip(mmap, number):
    val = struct.unpack("B", mmap[POS_FLAGS_START + number])[0] & 0x10

    if val != 0:
        return "S"
    else:
        return ""


def set_skip(mmap, number, skip):
    if skip == "P":
        raise errors.InvalidDataError("PSKIP not supported by this model")

    val = struct.unpack("B", mmap[POS_FLAGS_START + number])[0] & 0xEF

    if skip == "S":
        val |= 0x10

    mmap[POS_FLAGS_START + number] = val


def get_call_indices(mmap):
    return ord(mmap[18]) & 0x0F, \
        (ord(mmap[19]) & 0xF0) >> 4, \
        ord(mmap[19]) & 0x0F


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

    mmap[18] = (ord(mmap[18]) & 0xF0) | uindex
    mmap[19] = (r1index << 4) | r2index

# --


def get_mem_offset(number):
    return number * MEM_LOC_SIZE


def get_raw_memory(mmap, number):
    offset = get_mem_offset(number)
    return MemoryMap(mmap[offset:offset + MEM_LOC_SIZE])


def get_bank(mmap, number):
    val = ord(mmap[POS_FLAGS_START + number]) & 0x0F

    if val >= 10:
        return None
    else:
        return val


def set_bank(mmap, number, bank):
    if bank is not None and bank > 9:
        raise errors.InvalidDataError("Invalid bank number %i" % bank)

    if bank is None:
        index = 0x0A
    else:
        index = bank

    val = ord(mmap[POS_FLAGS_START + number]) & 0xF0
    val |= index
    mmap[POS_FLAGS_START + number] = val


def _get_memory(_map, mmap, base):
    if get_mode(mmap) == "DV":
        mem = chirp_common.DVMemory()
        i_ucall, i_r1call, i_r2call = get_call_indices(mmap)
        mem.dv_urcall = get_urcall(_map, i_ucall)
        mem.dv_rpt1call = get_rptcall(_map, i_r1call)
        mem.dv_rpt2call = get_rptcall(_map, i_r2call)
    else:
        mem = chirp_common.Memory()

    mem.freq = get_freq(mmap, base)
    mem.name = get_name(mmap)
    mem.rtone = get_rtone(mmap)
    mem.ctone = get_ctone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.dtcs_polarity = get_dtcs_polarity(mmap)
    mem.offset = get_dup_offset(mmap)
    mem.duplex = get_duplex(mmap)
    mem.tmode = get_tone_enabled(mmap)
    mem.tuning_step = get_tune_step(mmap)
    mem.mode = get_mode(mmap)

    return mem


def get_memory(_map, number, base):
    if not is_used(_map, number):
        mem = chirp_common.Memory()
        if number < 200:
            mem.number = number
            mem.empty = True
            return mem
    else:
        mmap = get_raw_memory(_map, number)
        mem = _get_memory(_map, mmap, base)

    mem.number = number

    if number < 200:
        mem.skip = get_skip(_map, number)
    else:
        mem.extd_number = ICx8x_SPECIAL_REV[number]
        mem.immutable = ["number", "skip", "bank", "bank_index", "extd_number"]

    return mem


def clear_tx_inhibit(mmap):
    txi = struct.unpack("B", mmap[POS_TXI])[0]
    txi |= 0x40
    mmap[POS_TXI] = txi


def set_memory(_map, memory, base):
    mmap = get_raw_memory(_map, memory.number)

    set_freq(mmap, memory.freq, base)
    set_name(mmap, memory.name)
    set_rtone(mmap, memory.rtone)
    set_ctone(mmap, memory.ctone)
    set_dtcs(mmap, memory.dtcs)
    set_dtcs_polarity(mmap, memory.dtcs_polarity)
    set_dup_offset(mmap, memory.offset)
    set_duplex(mmap, memory.duplex)
    set_tone_enabled(mmap, memory.tmode)
    set_tune_step(mmap, memory.tuning_step)
    set_mode(mmap, memory.mode)
    if memory.number < 200:
        set_skip(_map, memory.number, memory.skip)

    if isinstance(memory, chirp_common.DVMemory):
        set_call_indices(_map,
                         mmap,
                         memory.dv_urcall,
                         memory.dv_rpt1call,
                         memory.dv_rpt2call)

    if not is_used(_map, memory.number):
        clear_tx_inhibit(mmap)

    _map[get_mem_offset(memory.number)] = mmap.get_packed()
    set_used(_map, memory.number)

    return _map


def erase_memory(_map, number):
    set_used(_map, number, False)

    return _map


def call_location(base, index):
    return base + (16 * index)


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

    return mmap[start:start+8].rstrip()


def set_urcall(mmap, index, call):
    if index > 5:
        raise errors.InvalidDataError("URCALL index %i must be <= 5" % index)

    start = call_location(POS_URCALL, index)

    mmap[start] = call.ljust(12)

    return mmap


def set_rptcall(mmap, index, call):
    if index > 5:
        raise errors.InvalidDataError("RPTCALL index %i must be <= 5" % index)

    start = call_location(POS_RPCALL, index)
    mmap[start] = call.ljust(12)

    start = call_location(POS_RP2CALL, index)
    mmap[start] = call.ljust(12)

    return mmap


def set_mycall(mmap, index, call):
    if index > 5:
        raise errors.InvalidDataError("MYCALL index %i must be <= 5" % index)

    start = call_location(POS_MYCALL, index)

    mmap[start] = call.ljust(12)

    return mmap
