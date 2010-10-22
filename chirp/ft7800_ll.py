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

import time
from chirp import chirp_common, util, errors
from chirp import memmap

ACK = chr(0x06)

MEM_LOC_BASE = 0x04C8
MEM_LOC_SIZE = 16
MEM_TAG_BASE = 0x4988
MEM_FLG_BASE = 0x7648

POS_USED   = 0
POS_DUP    = 0
POS_MODE   = 0
POS_FREQ   = 1
POS_TMODE  = 4
POS_STEP   = 4
POS_TONE   = 8
POS_DTCS   = 9
POS_OFFSET = 12

STEPS = list(chirp_common.TUNING_STEPS)
STEPS.remove(6.25)
STEPS.remove(30.0)
STEPS.append(100.0)
STEPS.append(9.0)

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    list(" " * 10) + \
    list("*+,- /|      [ ] _") + \
    list("?" * 100)

def send(s, data):
    print "Sending %i:\n%s" % (len(data), util.hexprint(data))
    s.write(data)
    s.read(len(data))

def download(radio):
    data = ""

    chunk = ""
    for i in range(0, 30):
        chunk += radio.pipe.read(radio._block_lengths[0])
        if chunk:
            break

    if len(chunk) != radio._block_lengths[0]:
        raise Exception("Failed to read header")
    data += chunk

    send(radio.pipe, ACK)

    for i in range(0, radio._block_lengths[1], 64):
        chunk = radio.pipe.read(64)
        data += chunk
        if len(chunk) != 64:
            break
            raise Exception("No block at %i" % i)
        send(radio.pipe, ACK)
        if radio.status_fn:
            status = chirp_common.Status()
            status.max = radio._block_lengths[1]
            status.cur = i+len(chunk)
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    data += radio.pipe.read(1)
    send(radio.pipe, ACK)

    return memmap.MemoryMap(data)

def upload(radio):
    cur = 0
    for block in radio._block_lengths:
        for i in range(0, block, 64):
            length = min(64, block)
            print "i=%i length=%i range: %i-%i" % (i, length,
                                                   cur, cur+length)
            send(radio.pipe, radio._mmap[cur:cur+length])
            if radio.pipe.read(1) != ACK:
                raise errors.RadioError("Radio did not ack block at %i" % cur)
            cur += length
            #time.sleep(0.1)

            if radio.status_fn:
                s = chirp_common.Status()
                s.cur = cur
                s.max = radio._memsize
                s.msg = "Cloning to radio"
                radio.status_fn(s)

def get_mem_offset(number):
    return MEM_LOC_BASE + (number * MEM_LOC_SIZE)

def get_raw_memory(map, number):
    offset = get_mem_offset(number)

    return memmap.MemoryMap(map[offset:offset+MEM_LOC_SIZE])

def get_freq(mmap):
    khz = (int("%02x" % (ord(mmap[POS_FREQ]) & 0x0F), 10) * 100000) + \
        (int("%02x" % ord(mmap[POS_FREQ+1]), 10) * 1000) + \
        (int("%02x" % ord(mmap[POS_FREQ+2]), 10) * 10)
    return khz / 1000.0

def set_freq(mmap, freq):
    val = util.bcd_encode(int(freq * 10000), width=6)[:4]

    mmap[POS_FREQ] = (ord(mmap[POS_FREQ]) & 0xF0) | ord(val[0])
    mmap[POS_FREQ+1] = val[1:]

def get_tmode(mmap):
    val = ord(mmap[POS_TMODE]) & 0x07
    
    tmodemap = {
        0x00 : "",
        0x01 : "Tone",
        0x02 : "TSQL",
        0x03 : "", # UNSUPPORTED: REV TN
        0x04 : "DTCS",
        }

    return tmodemap[val]

def set_tmode(mmap, tmode):
    val = ord(mmap[POS_TMODE]) & 0xF8

    tmodemap = {
        ""     : 0x00,
        "Tone" : 0x01,
        "TSQL" : 0x02,
        "DTCS" : 0x04,
        }

    mmap[POS_TMODE] = val | tmodemap[tmode]

def get_duplex(mmap):
    val = ord(mmap[POS_DUP]) & 0x03

    dupmap = {
        0x00 : "",
        0x01 : "split", #this will almost certainly fail is a spectacular way
        0x02 : "-",
        0x03 : "+",
        }

    return dupmap[val]

def set_duplex(mmap, duplex):
    val = ord(mmap[POS_DUP]) & 0xFC

    dupmap = {
        ""      : 0x00,
        "split" : 0x01, #this is even more likely to fail in a spectacular way
        "-"     : 0x02,
        "+"     : 0x03,
        }

    mmap[POS_DUP] = val | dupmap[duplex]

def get_offset(mmap):
    val = ord(mmap[POS_OFFSET])

    return (val * 5) / 100.0

def set_offset(mmap, offset):
    val = int(offset * 100) / 5

    mmap[POS_OFFSET] = val

def get_tone(mmap):
    val = ord(mmap[POS_TONE]) & 0x3F
    return chirp_common.TONES[val]

def set_tone(mmap, tone):
    val = ord(mmap[POS_TONE]) & 0xC0

    mmap[POS_TONE] = val | chirp_common.TONES.index(tone)

def get_dtcs(mmap):
    val = ord(mmap[POS_DTCS]) & 0x7F

    return chirp_common.DTCS_CODES[val]

def set_dtcs(mmap, dtcs):
    mmap[POS_DTCS] = chirp_common.DTCS_CODES.index(dtcs)

def get_ts(mmap):
    val = ord(mmap[POS_STEP]) & 0x70

    return STEPS[val >> 4]

def set_ts(mmap, ts):
    if ts not in STEPS:
        raise errors.InvalidDataError("Tuning step %.1f not supported" % ts)

    val = ord(mmap[POS_STEP]) & 0x8F

    mmap[POS_STEP] = val | (STEPS.index(ts) << 4)

def get_mode(mmap):
    val = ord(mmap[POS_MODE]) & 0x10

    if val:
        return "AM"
    else:
        return "FM"

def set_mode(mmap, mode):
    val = ord(mmap[POS_MODE]) & 0xEF
    if mode == "FM":
        pass
    elif mode == "AM":
        val |= 0x10
    else:
        raise errors.InvalidDataError("Unsupported mode %s" % mode)

    mmap[POS_MODE] = val

def get_name(map, number):
    pos = MEM_TAG_BASE + (number * 8)
    tag = map[pos:pos+6]

    print "Pos for %i: %04x" % (number, pos)

    if not (ord(map[pos+6]) & 0x80):
        return ""

    name = ""
    for i in tag:
        if ord(i) == 0:
            break
        print "%i: %i" % (len(name), ord(i))
        name += CHARSET[ord(i)]

    return name

def set_name(map, number, name):
    name = name.ljust(6)[:6].upper()
    pos = MEM_TAG_BASE + (number * 8)

    i = 0
    for char in name:
        if not char in CHARSET:
            char = " "
        map[pos+i] = CHARSET.index(char)
        i += 1

    if name:
        map[pos+7] = ord(map[pos+7]) | 0x80
    else:
        map[pos+7] = ord(map[pos+7]) & 0x7F

def get_used(mmap):
    return ord(mmap[POS_USED]) & 0x80

def set_used(mmap, used):
    val = ord(mmap[POS_USED]) & 0x7F

    if used:
        val |= 0x80

    mmap[POS_USED] = val

def get_skip(map, number):
    byte = number / 4
    halfnib  = number % 4

    val = ord(map[MEM_FLG_BASE+byte])
    val >>= (6 - (2 * halfnib))
    val &= 0x03

    if val == 0x02:
        return "P"
    elif val == 0x01:
        return "S"
    else:
        return ""

def set_skip(map, number, skip):
    byte = number / 4
    halfnib = number % 4

    if skip == "S":
        bits = 0x01
    elif skip == "P":
        bits = 0x02
    else:
        bits = 0x00

    print "Bits: %02x" % bits

    shift = 6 - (2 * halfnib)
    bits <<= shift

    print "Shfd: %02x" % bits

    val = ord(map[MEM_FLG_BASE+byte]) & ~(0x03 << shift)
    
    print "Val:  %02x" % val

    map[MEM_FLG_BASE+byte] = (val | bits) & 0xFF

def get_memory(map, number):
    mmap = get_raw_memory(map, number)

    mem = chirp_common.Memory()
    mem.number = number
    if not get_used(mmap):
        mem.empty = True
        return mem

    mem.freq = get_freq(mmap)
    mem.tmode = get_tmode(mmap)
    mem.duplex = get_duplex(mmap)
    mem.offset = get_offset(mmap)
    mem.rtone = mem.ctone = get_tone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.tuning_step = get_ts(mmap)
    mem.mode = get_mode(mmap)
    mem.name = get_name(map, number)
    mem.skip = get_skip(map, number)

    return mem

def set_memory(map, mem):
    mmap = get_raw_memory(map, mem.number)

    if not get_used(mmap):
        pass # FIXME

    set_freq(mmap, mem.freq)
    set_duplex(mmap, mem.duplex)
    set_mode(mmap, mem.mode)
    set_ts(mmap, mem.tuning_step)
    set_tone(mmap, mem.ctone)
    set_dtcs(mmap, mem.dtcs)
    set_tmode(mmap, mem.tmode)
    set_offset(mmap, mem.offset)

    set_used(mmap, True)

    map[get_mem_offset(mem.number)] = mmap.get_packed()

    set_name(map, mem.number, mem.name)
    set_skip(map, mem.number, mem.skip)

def erase_memory(map, number):
    mmap = get_raw_memory(_map, mem.number)
    set_used(mmap, mem.number, False)
    map[get_mem_offset(mem.number)] = mmap.get_packed()
    
def update_checksum(map):
    cs = 0
    for i in range(0, 0x7B48):
        cs += ord(map[i])
    cs %= 256
    print "Checksum old=%02x new=%02x" % (ord(map[0x7B48]), cs)
    map[0x7B48] = cs

if __name__ == "__main__":
    import serial, sys

    def status(status):
        print status.msg

    s = serial.Serial(port=sys.argv[1], baudrate=9600, timeout=3)
    data = download(s, 31552, status)

    file("output", "wb").write(data)
