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
import time
import logging

from chirp import memmap, chirp_common, errors

LOG = logging.getLogger(__name__)

POS_MODE = 5
POS_DUP = 6
POS_TMODE = 6
POS_RTONE = 7
POS_CTONE = 8
POS_DTCS = 9
POS_OFFSET = 10

MEM_LOC_BASE = 0x1700
MEM_LOC_SIZE = 16
MEM_TAG_BASE = 0x5800
MEM_FLG_BASE = 0x0E00

V71_SPECIAL = {}

for i in range(0, 10):
    V71_SPECIAL["L%i" % i] = 1000 + (i * 2)
    V71_SPECIAL["U%i" % i] = 1000 + (i * 2) + 1
for i in range(0, 10):
    V71_SPECIAL["WX%i" % (i + 1)] = 1020 + i
V71_SPECIAL["C VHF"] = 1030
V71_SPECIAL["C UHF"] = 1031

V71_SPECIAL_REV = {}
for k, v in V71_SPECIAL.items():
    V71_SPECIAL_REV[v] = k


def command(s, cmd, timeout=0.5):
    start = time.time()

    data = ""
    LOG.debug("PC->V71: %s" % cmd)
    s.write(cmd + "\r")
    while not data.endswith("\r") and (time.time() - start) < timeout:
        data += s.read(1)
    LOG.debug("V71->PC: %s" % data.strip())
    return data.strip()


def get_id(s):
    r = command(s, "ID")
    if r.startswith("ID "):
        return r.split(" ")[1]
    else:
        raise errors.RadioError("No response to ID command")


EXCH_R = "R\x00\x00\x00"
EXCH_W = "W\x00\x00\x00"


def read_block(s, block, count=256):
    s.write(struct.pack("<cHB", "R", block, 0))
    r = s.read(4)
    if len(r) != 4:
        raise Exception("Did not receive block response")

    cmd, _block, zero = struct.unpack("<cHB", r)
    if cmd != "W" or _block != block:
        raise Exception("Invalid response: %s %i" % (cmd, _block))

    data = ""
    while len(data) < count:
        data += s.read(count - len(data))

    s.write(chr(0x06))
    if s.read(1) != chr(0x06):
        raise Exception("Did not receive post-block ACK!")

    return data


def write_block(s, block, map):
    s.write(struct.pack("<cHB", "W", block, 0))
    base = block * 256
    s.write(map[base:base+256])

    ack = s.read(1)

    return ack == chr(0x06)


def download(radio):
    if command(radio.pipe, "0M PROGRAM") != "0M":
        raise errors.RadioError("No response from radio")

    data = ""
    for i in range(0, 0x7F):
        data += read_block(radio.pipe, i)
        if radio.status_fn:
            s = chirp_common.Status()
            s.msg = "Cloning from radio"
            s.max = 256 * 0x7E
            s.cur = len(data)
            radio.status_fn(s)

    radio.pipe.write("E")

    return memmap.MemoryMap(data)


def upload(radio):
    if command(radio.pipe, "0M PROGRAM") != "0M":
        raise errors.RadioError("No response from radio")

    for i in range(0, 0x7F):
        r = write_block(radio.pipe, i, radio._mmap)
        if not r:
            raise errors.RadioError("Radio NAK'd block %i" % i)
        if radio.status_fn:
            s = chirp_common.Status()
            s.msg = "Cloning to radio"
            s.max = 256 * 0x7E
            s.cur = 256 * i
            radio.status_fn(s)

    radio.pipe.write("E")


def get_mem_offset(number):
    return MEM_LOC_BASE + (MEM_LOC_SIZE * number)


def get_raw_mem(map, number):
    base = get_mem_offset(number)
    # LOG.debug("Offset for %i is %04x" % (number, base))
    return map[base:base+MEM_LOC_SIZE]


def get_used(map, number):
    pos = MEM_FLG_BASE + (number * 2)
    flag = ord(map[pos])
    LOG.debug("Flag byte is %02x" % flag)
    return not (flag & 0x80)


def set_used(map, number, freq):
    pos = MEM_FLG_BASE + (number * 2)
    if freq == 0:
        # Erase
        map[pos] = "\xff\xff"
    elif int(freq / 100) == 1:
        map[pos] = "\x05\x00"
    elif int(freq / 100) == 4:
        map[pos] = "\x08\x00"


def get_skip(map, number):
    pos = MEM_FLG_BASE + (number * 2)
    flag = ord(map[pos+1])
    if flag & 0x01:
        return "S"
    else:
        return ""


def set_skip(map, number, skip):
    pos = MEM_FLG_BASE + (number * 2)
    flag = ord(map[pos+1])
    if skip:
        flag |= 0x01
    else:
        flag &= ~0x01
    map[pos+1] = flag


def get_freq(mmap):
    freq, = struct.unpack("<I", mmap[0:4])
    return freq / 1000000.0


def set_freq(mmap, freq):
    mmap[0] = struct.pack("<I", int(freq * 1000000))


def get_name(map, number):
    base = MEM_TAG_BASE + (8 * number)
    return map[base:base+6].replace("\xff", "")


def set_name(mmap, number, name):
    base = MEM_TAG_BASE + (8 * number)
    mmap[base] = name.ljust(6)[:6].upper()


def get_tmode(mmap):
    val = ord(mmap[POS_TMODE]) & 0x70

    tmodemap = {
        0x00: "",
        0x40: "Tone",
        0x20: "TSQL",
        0x10: "DTCS",
        }

    return tmodemap[val]


def set_tmode(mmap, tmode):
    val = ord(mmap[POS_TMODE]) & 0x8F

    tmodemap = {
        "":     0x00,
        "Tone": 0x40,
        "TSQL": 0x20,
        "DTCS": 0x10,
        }

    mmap[POS_TMODE] = val | tmodemap[tmode]


def get_tone(mmap, offset):
    val = ord(mmap[offset])

    return chirp_common.TONES[val]


def set_tone(mmap, tone, offset):
    LOG.debug(tone)
    mmap[offset] = chirp_common.TONES.index(tone)


def get_dtcs(mmap):
    val = ord(mmap[POS_DTCS])

    return chirp_common.DTCS_CODES[val]


def set_dtcs(mmap, dtcs):
    mmap[POS_DTCS] = chirp_common.DTCS_CODES.index(dtcs)


def get_duplex(mmap):
    val = ord(mmap[POS_DUP]) & 0x03

    dupmap = {
        0x00: "",
        0x01: "+",
        0x02: "-",
        }

    return dupmap[val]


def set_duplex(mmap, duplex):
    val = ord(mmap[POS_DUP]) & 0xFC

    dupmap = {
        "":  0x00,
        "+": 0x01,
        "-": 0x02,
        }

    mmap[POS_DUP] = val | dupmap[duplex]


def get_offset(mmap):
    val, = struct.unpack("<I", mmap[POS_OFFSET:POS_OFFSET+4])
    return val / 1000000.0


def set_offset(mmap, offset):
    mmap[POS_OFFSET] = struct.pack("<I", int(offset * 1000000))


def get_mode(mmap):
    val = ord(mmap[POS_MODE]) & 0x03
    modemap = {
        0x00: "FM",
        0x01: "NFM",
        0x02: "AM",
        }

    return modemap[val]


def set_mode(mmap, mode):
    val = ord(mmap[POS_MODE]) & 0xFC
    modemap = {
        "FM":  0x00,
        "NFM": 0x01,
        "AM":  0x02,
        }

    mmap[POS_MODE] = val | modemap[mode]


def get_memory(map, number):
    if number < 0 or number > (max(V71_SPECIAL.values()) + 1):
        raise errors.InvalidMemoryLocation("Number must be between 0 and 999")

    mem = chirp_common.Memory()
    mem.number = number

    if number > 999:
        mem.extd_number = V71_SPECIAL_REV[number]
    if not get_used(map, number):
        mem.empty = True
        return mem

    mmap = get_raw_mem(map, number)

    mem.freq = get_freq(mmap)
    mem.name = get_name(map, number)
    mem.tmode = get_tmode(mmap)
    mem.rtone = get_tone(mmap, POS_RTONE)
    mem.ctone = get_tone(mmap, POS_CTONE)
    mem.dtcs = get_dtcs(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_offset(mmap)
    mem.mode = get_mode(mmap)

    if number < 999:
        mem.skip = get_skip(map, number)

    if number > 999:
        mem.immutable = ["number", "bank", "extd_number", "name"]
    if number > 1020 and number < 1030:
        mem.immutable += ["freq"]  # FIXME: ALL

    return mem


def initialize(mmap):
    mmap[0] = \
        "\x80\xc8\xb3\x08\x00\x01\x00\x08" + \
        "\x08\x00\xc0\x27\x09\x00\x00\xff"


def set_memory(map, mem):
    if mem.number < 0 or mem.number > (max(V71_SPECIAL.values()) + 1):
        raise errors.InvalidMemoryLocation("Number must be between 0 and 999")

    mmap = memmap.MemoryMap(get_raw_mem(map, mem.number))

    if not get_used(map, mem.number):
        initialize(mmap)

    set_freq(mmap, mem.freq)
    if mem.number < 999:
        set_name(map, mem.number, mem.name)
    set_tmode(mmap, mem.tmode)
    set_tone(mmap, mem.rtone, POS_RTONE)
    set_tone(mmap, mem.ctone, POS_CTONE)
    set_dtcs(mmap, mem.dtcs)
    set_duplex(mmap, mem.duplex)
    set_offset(mmap, mem.offset)
    set_mode(mmap, mem.mode)

    base = get_mem_offset(mem.number)
    map[base] = mmap.get_packed()

    set_used(map, mem.number, mem.freq)
    if mem.number < 999:
        set_skip(map, mem.number, mem.skip)

    return map


if __name__ == "__main__":
    import sys
    import serial
    s = serial.Serial(port=sys.argv[1], baudrate=9600, dsrdtr=True,
                      timeout=0.25)
    # s.write("\r\r")
    # print get_id(s)
    data = download(s)
    open(sys.argv[2], "wb").write(data)
