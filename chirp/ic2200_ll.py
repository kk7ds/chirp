import struct

import chirp_common
import util

def get_memory(map, number):
    chunk = map[number * 24:(number+1) * 24]

    _freq = (struct.unpack("<H", chunk[0:2])[0] * 5) / 1000.0
    _name = chunk[4:10]

    if map[0x1370 + number] == "\x7A":
        # Location is not used
        return None

    m = chirp_common.Memory()
    m.freq = _freq
    m.name = _name.replace("\x0e", "").strip()
    m.number = number

    return m

def set_memory(map, memory):
    _fa = (memory.number * 24)
    _na = (memory.number * 24) + 4

    if map[_fa + 2] == "\xFF":
        # Assume this is empty now, so initialize bits
        map = util.write_in_place(map, _fa + 2, "\x78\x00")
        map = util.write_in_place(map, _fa + 10, "\x08\x08" + ("\x00" * 12))

    freq = struct.pack("<H", int(memory.freq * 1000) / 5)
    name = memory.name.ljust(6)[:6]

    map = util.write_in_place(map, _fa, freq)
    map = util.write_in_place(map, _na, name)

    # Mark as used
    map = util.write_in_place(map, 0x1370 + memory.number, "\x4A")

    if name == (" " * 6):
        map = util.write_in_place(map, _fa+22, "\x00")
    else:
        map = util.write_in_place(map, _fa+22, "\x10")

    return map

def parse_map_for_memory(map):
    memories = []

    for i in range(197):
        m = get_memory(map, i)
        if m:
            memories.append(m)

    return memories
