#!/usr/bin/python

import struct

import icf
import util
import chirp_common
import errors

def get_memory(map, number):
    chunk = map[number*0x30:(number+1)*0x30]

    _freq, = struct.unpack(">I", chunk[0:4])

    mem = chirp_common.Memory()
    mem.number = number
    mem.name = chunk[-8:].strip()
    mem.freq = _freq / 1000000.0

    if mem.name[0] == "\x00":
        return None
    elif mem.name[0] == "\xFF":
        return None

    _tone, = struct.unpack(">H", chunk[34:36])
    _tonei = (_tone >> 4) & 0xFF

    _tdup, = struct.unpack("B", chunk[33])
    mem.toneEnabled = ((_tdup & 0x04) != 0)
    if ((_tdup & 0x40) != 0):
        mem.duplex = "+"
    elif ((_tdup & 0x20) != 0):
        mem.duplex = "-"
    else:
        mem.duplex = ""

    try:
        mem.tone = chirp_common.TONES[_tonei]
    except:
        raise errors.InvalidDataError("Radio has unknown tone 0x%02X" % _tonei)

    return mem

def set_memory(map, memory):
    _fa = (memory.number * 0x30)
    _na = (memory.number * 0x30) + 0x28
    
    freq = struct.pack(">I", int(memory.freq * 1000000))
    name = memory.name.ljust(8)

    tdup = 0
    if memory.toneEnabled:
        tdup |= 0x04
    if memory.duplex == "+":
        tdup |= 0x40
    elif memory.duplex == "-":
        tdup |= 0x20

    tdup = chr(tdup)
        
    _tone = chirp_common.TONES.index(memory.tone)
    tone, = struct.unpack(">H", map[_fa+34:_fa+36])
    tone &= 0xF00F
    tone |= ((_tone << 4) & 0x0FF0)
    tone = chr((tone & 0xFF00) >> 8) + chr(tone & 0xFF)

    map = util.write_in_place(map, _fa, freq)
    map = util.write_in_place(map, _na, name[:8])
    map = util.write_in_place(map, _fa+33, tdup)
    map = util.write_in_place(map, _fa+34, tone)

    return map

def parse_map_for_memory(map):
    memories = []

    for i in range(500):
        m = get_memory(map, i)
        if m:
            memories.append(m)

    return memories

if __name__ == "__main__":
    import serial
    
    s = serial.Serial(port="/dev/ttyUSB1",
                      baudrate=9600,
                      timeout=0.5)
    
    md = icf.get_model_data(s)
    
    print "Model:\n%s" % util.hexprint(md)
    #
    map = icf.clone_from_radio(s, md[0:4], chirp_common.console_status)
    #f = file("2820.map", "wb")
    #f.write(map)
    #f.close()

    #f = file("2820.map", "rb")
    #map = f.read()
    #f.close()

    #print get_memory(map, 3)
