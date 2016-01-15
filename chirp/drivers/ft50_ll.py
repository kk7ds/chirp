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

from chirp import chirp_common, util, errors, memmap
import time
import logging

LOG = logging.getLogger(__name__)

ACK = chr(0x06)

MEM_LOC_BASE = 0x00AB
MEM_LOC_SIZE = 16

POS_DUPLEX = 1
POS_TMODE = 2
POS_TONE = 2
POS_DTCS = 3
POS_MODE = 4
POS_FREQ = 5
POS_OFFSET = 9
POS_NAME = 11

POS_USED = 0x079C

CHARSET = [str(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    list(" ()+--*/???|0123456789")


def send(s, data):
    s.write(data)
    r = s.read(len(data))
    if len(r) != len(data):
        raise errors.RadioError("Failed to read echo")


def read_exact(s, count):
    data = ""
    i = 0
    while len(data) < count:
        if i == 3:
            LOG.debug(util.hexprint(data))
            raise errors.RadioError("Failed to read %i (%i) from radio" %
                                    (count, len(data)))
        elif i > 0:
            LOG.info("Retry %i" % i)
        data += s.read(count - len(data))
        i += 1

    return data


def download(radio):
    data = ""

    radio.pipe.timeout = 1

    for block in radio._block_lengths:
        LOG.debug("Doing block %i" % block)
        if block > 112:
            step = 16
        else:
            step = block
        for i in range(0, block, step):
            # data += read_exact(radio.pipe, step)
            chunk = radio.pipe.read(step*2)
            LOG.debug("Length of chunk: %i" % len(chunk))
            data += chunk
            LOG.debug("Reading %i" % i)
            time.sleep(0.1)
            send(radio.pipe, ACK)
            if radio.status_fn:
                status = chirp_common.Status()
                status.max = radio._memsize
                status.cur = len(data)
                status.msg = "Cloning from radio"
                radio.status_fn(status)

    r = radio.pipe.read(100)
    send(radio.pipe, ACK)
    LOG.debug("R: %i" % len(r))
    LOG.debug(util.hexprint(r))

    LOG.debug("Got: %i Expecting %i" % (len(data), radio._memsize))

    return memmap.MemoryMap(data)


def get_mem_offset(number):
    return MEM_LOC_BASE + (number * MEM_LOC_SIZE)


def get_raw_memory(map, number):
    pos = get_mem_offset(number)
    return memmap.MemoryMap(map[pos:pos+MEM_LOC_SIZE])


def get_freq(mmap):
    khz = (int("%02x" % (ord(mmap[POS_FREQ])), 10) * 100000) + \
        (int("%02x" % ord(mmap[POS_FREQ+1]), 10) * 1000) + \
        (int("%02x" % ord(mmap[POS_FREQ+2]), 10) * 10)
    return khz / 10000.0


def set_freq(mmap, freq):
    val = util.bcd_encode(int(freq * 1000), width=6)[:3]
    mmap[POS_FREQ] = val


def get_tmode(mmap):
    val = ord(mmap[POS_TMODE]) & 0xC0

    tmodemap = {
        0x00: "",
        0x40: "Tone",
        0x80: "TSQL",
        0xC0: "DTCS",
        }

    return tmodemap[val]


def set_tmode(mmap, tmode):
    val = ord(mmap[POS_TMODE]) & 0x3F

    tmodemap = {
        "":      0x00,
        "Tone":  0x40,
        "TSQL":  0x80,
        "DTCS":  0xC0,
        }

    val |= tmodemap[tmode]

    mmap[POS_TMODE] = val


def get_tone(mmap):
    val = ord(mmap[POS_TONE]) & 0x3F

    return chirp_common.TONES[val]


def set_tone(mmap, tone):
    val = ord(mmap[POS_TONE]) & 0xC0

    mmap[POS_TONE] = val | chirp_common.TONES.index(tone)


def get_dtcs(mmap):
    val = ord(mmap[POS_DTCS])

    return chirp_common.DTCS_CODES[val]


def set_dtcs(mmap, dtcs):
    mmap[POS_DTCS] = chirp_common.DTCS_CODES.index(dtcs)


def get_offset(mmap):
    khz = (int("%02x" % ord(mmap[POS_OFFSET]), 10) * 10) + \
        (int("%02x" % (ord(mmap[POS_OFFSET+1]) >> 4), 10) * 1)

    return khz / 1000.0


def set_offset(mmap, offset):
    val = util.bcd_encode(int(offset * 1000), width=4)[:3]
    LOG.debug("Offset:\n%s" % util.hexprint(val))
    mmap[POS_OFFSET] = val


def get_duplex(mmap):
    val = ord(mmap[POS_DUPLEX]) & 0x03

    dupmap = {
        0x00: "",
        0x01: "-",
        0x02: "+",
        0x03: "split",
        }

    return dupmap[val]


def set_duplex(mmap, duplex):
    val = ord(mmap[POS_DUPLEX]) & 0xFC

    dupmap = {
        "":       0x00,
        "-":      0x01,
        "+":      0x02,
        "split":  0x03,
        }

    mmap[POS_DUPLEX] = val | dupmap[duplex]


def get_name(mmap):
    name = ""
    for x in mmap[POS_NAME:POS_NAME+4]:
        if ord(x) >= len(CHARSET):
            break
        name += CHARSET[ord(x)]
    return name


def set_name(mmap, name):
    val = ""
    for i in name[:4].ljust(4):
        val += chr(CHARSET.index(i))
    mmap[POS_NAME] = val


def get_mode(mmap):
    val = ord(mmap[POS_MODE]) & 0x03

    modemap = {
        0x00: "FM",
        0x01: "AM",
        0x02: "WFM",
        0x03: "WFM",
        }

    return modemap[val]


def set_mode(mmap, mode):
    val = ord(mmap[POS_MODE]) & 0xCF

    modemap = {
        "FM":   0x00,
        "AM":   0x01,
        "WFM":  0x02,
        }

    mmap[POS_MODE] = val | modemap[mode]


def get_used(mmap, number):
    return ord(mmap[POS_USED + number]) & 0x01


def set_used(mmap, number, used):
    val = ord(mmap[POS_USED + number]) & 0xFC
    if used:
        val |= 0x03
    mmap[POS_USED + number] = val


def get_memory(map, number):
    index = number - 1
    mmap = get_raw_memory(map, index)

    mem = chirp_common.Memory()
    mem.number = number
    if not get_used(map, index):
        mem.empty = True
        return mem

    mem.freq = get_freq(mmap)
    mem.tmode = get_tmode(mmap)
    mem.rtone = mem.ctone = get_tone(mmap)
    mem.dtcs = get_dtcs(mmap)
    mem.offset = get_offset(mmap)
    mem.duplex = get_duplex(mmap)
    mem.name = get_name(mmap)
    mem.mode = get_mode(mmap)

    return mem


def set_memory(_map, mem):
    index = mem.number - 1
    mmap = get_raw_memory(_map, index)

    if not get_used(_map, index):
        mmap[0] = ("\x00" * MEM_LOC_SIZE)

    set_freq(mmap, mem.freq)
    set_tmode(mmap, mem.tmode)
    set_tone(mmap, mem.rtone)
    set_dtcs(mmap, mem.dtcs)
    set_offset(mmap, mem.offset)
    set_duplex(mmap, mem.duplex)
    set_name(mmap, mem.name)
    set_mode(mmap, mem.mode)

    _map[get_mem_offset(index)] = mmap.get_packed()
    set_used(_map, index, True)

    return _map


def erase_memory(map, number):
    set_used(map, number-1, False)
    return map


def update_checksum(map):
    cs = 0
    for i in range(0, 3722):
        cs += ord(map[i])
    cs %= 256
    LOG.debug("Checksum old=%02x new=%02x" % (ord(map[3722]), cs))
    map[3722] = cs
