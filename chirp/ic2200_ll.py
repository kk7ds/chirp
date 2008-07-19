import struct

import chirp_common
import util

def get_memory(map, number):
    chunk = map[number * 24:(number+1) * 24]

    _freq = (struct.unpack("<H", chunk[0:2])[0] * 5) / 1000.0
    _name = chunk[4:10]

    m = chirp_common.Memory()
    m.freq = _freq
    m.name = _name.replace("\x0e", "").strip()

    return m

def set_memory(map, memory):
    _fa = (memory.number * 24)
    _na = (memory.number * 24) + 4

    freq = struct.pack("<H", int(memory.freq * 1000) / 5)
    name = memory.name.ljust(8)[:8]

    map = util.write_in_place(map, _fa, freq)
    map = util.write_in_place(map, _na, name)

    return map

def parse_map_for_memory(map):
    memories = []

    for i in range(100):
        m = get_memory(map, i)
        if m:
            memories.append(m)

    return memories
