#!/usr/bin/python

import struct

import icf
import util
import chirp_common
import errors

from id800_ll import send_mem_chunk

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

def get_memory_map(radio):
    md = icf.get_model_data(radio.pipe)

    if md[0:4] != radio._model:
        raise errors.RadioError("I can't talk to this model")

    return icf.clone_from_radio(radio)

def clone_to_radio(radio):
    md = icf.get_model_data(radio.pipe)

    if md[0:4] != radio._model:
        raise errors.RadioError("This module supports IC-2820H only")

    icf.send_clone_frame(radio.pipe, 0xe3, radio._model, raw=True)

    ranges = [(0x0000, 0x6960, 32),
              (0x6960, 0x6980, 16),
              (0x6980, 0x7160, 32),
              (0x7160, 0x7180, 16),
              (0x7180, 0xACC0, 32),]

    for start, stop, bs in ranges:
        if not send_mem_chunk(radio.pipe, radio._mmap, start, stop, bs):
            break

        if radio.status_fn:
            s = chirp_common.Status()
            s.max = 0xACC0
            s.cur = start
            s.msg = "Cloning to radio"

            radio.status_fn(s)

    icf.send_clone_frame(radio.pipe, 0xe5, "Icom Inc\x2e68", raw=True)

    termresp = icf.get_clone_resp(radio.pipe)

    return termresp[5] == "\x00"

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
