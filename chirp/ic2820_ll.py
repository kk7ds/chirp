#!/usr/bin/python

import struct

import icf
import util
import chirp_common

def get_memory(map, number):
    chunk = map[number*0x30:(number+1)*0x30]

    _freq, = struct.unpack(">I", chunk[0:4])

    mem = chirp_common.Memory()
    mem.number = number
    mem.name = chunk[-8:]
    mem.freq = _freq / 1000000.0

    return mem

def parse_map_for_memory(map):
    memories = []

    for i in range(500):
        memories.append(get_memory(map, i))

    return memories

def get_memory_map(pipe, status):
    md = icf.get_model_data(pipe)

    return icf.clone_from_radio(pipe, md[0:4], status)

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
