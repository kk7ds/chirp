#!/usr/bin/python

import struct

import repidr_common
import util

def pack_name(_name, enabled=True):
    name = _name.ljust(8)
    nibbles = []

    def val_of(char):
        if char == " ":
            return 0
        elif char.isdigit():
            return (int(char) & 0x3F) | 0x10
        else:
            return ((ord(char) - ord("A") + 1) & 0x3F) | 0x20

    for i in range(0, len(name), 2):
        c1 = name[i]
        c2 = name[i+1]

        v1 = val_of(c1)
        v2 = val_of(c2)

        nibbles.append((v1 & 0x3B) >> 2)
        nibbles.append(((v1 & 0x03) << 2) | ((v2 & 0x30) >> 4))
        nibbles.append((v2 & 0x0F))

    if enabled:
        nibbles.insert(0, 2)
    else:
        nibbles.insert(0, 0)

    nibbles.append(0)

    val = ""

    for i in range(0, len(nibbles), 2):
        val += struct.pack("B", ((nibbles[i] << 4)| nibbles[i+1]))

    return val

def unpack_name(mem):
    nibbles = []

    for i in mem:
        nibbles.append((ord(i) & 0xF0) >> 4)
        nibbles.append(ord(i) & 0x0F)

    ln = None
    i = 1
    name = ""

    while i < len(nibbles) - 1:
        this = nibbles[i]

        if ln is None:
            i += 1
            ln = nibbles[i]
            this = (this << 2)  | ((ln >> 2) & 0x3)
        else:
            this = ((ln & 0x3) << 4) | this
            ln = None

        if this == 0:
            name += " "
        elif (this & 0x20) == 0:
            name += chr(ord("1") + (this & 0x0F) - 1)
        else:
            name += chr(ord("A") + (this & 0x1F) - 1)

        i += 1

    return name.rstrip()

def pack_frequency(freq):
    return struct.pack(">i", int((freq * 1000) / 5))[1:]

def unpack_frequency(_mem):
    mem = '\x00' + _mem

    return ((struct.unpack(">i", mem)[0] * 5) / 1000.0)

def parse_map_for_memory(map):
    """Returns a list of memories, given a valid memory map"""

    memories = []
    
    for i in range(500):        
        addr = (i * 22) + 0x0020

        _freq = map[addr:addr+3]
        _name = map[addr+11:addr+11+8]

        mem = repidr_common.Memory()
        mem.number = i
        mem.name = unpack_name(_name)
        mem.freq = unpack_frequency(_freq)

        memories.append(mem)

    return memories

def send_to_id800(pipe, cmd, data, raw=False):

    if raw:
        hed = data
    else:
        hed = ""
        for byte in data:
            hed += "%02x" % ord(byte)

    frame = "\xfe\xfe\xee\xef%s%s\xfd" % (chr(cmd), hed)

    print "Sending: %s" % ["%02x" % ord(x) for x in frame]

    pipe.write(frame)

def get_model_data(pipe):
    send_to_id800(pipe, 0xe0, "\x27\x88\x00\x00", raw=True)

    model_data = ""

    while not model_data.endswith("\xfd"):
        model_data += pipe.read(1)

    print "Got model data:\n%s" % util.hexprint(model_data)

    return model_data

def clone_from_radio(pipe, model_data):
    send_to_id800(pipe, 0xe2, model_data, raw=True)

    data = ""

    while True:
        _d = pipe.read(64)
        if not _d:
            break
        data += _d

    return data

def process_radio_stream(streamdata):
    mem = ""
    
    while True:
        try:
            start = streamdata.index("\xfe\xfe")
        except ValueError:
            print "End of stream"
            break

        streamdata = streamdata[start:]

        start = 0
        end = streamdata.index("\xfd")

        frame = streamdata[start:end+1]
        streamdata = streamdata[end:]

        (_, _, fr, to, cmd) = struct.unpack("<BBBBB", frame[:5])

        data = frame[5:-3]

        if cmd == 0xE4:
            saddr = int(data[0:4], 16)
            bytes = int(data[4:6], 16)
            eaddr = saddr + bytes
            fdata = data[6:]
        else:
            continue

        i = 0
        while i < range(len(fdata)):
            try:
                val = int("%s%s" % (fdata[i], fdata[i+1]), 16)
                i += 2
                memdata = struct.pack("B", val)
                mem += memdata
            except:
                break

    return mem

def get_memory_map(pipe):
    #get_model_data(pipe)

    streamdata = clone_from_radio(pipe, "\x27\x88\x00\x00")

    return process_radio_stream(streamdata)

def test_basic():
    v = pack_name("CHAN2")
    V = "\x28\xe8\x86\xe4\x80\x00\x00"

    if v == V:
        print "Pack name: OK"
    else:
        print "Pack name: FAIL"
        print "%s not equal to %s" % (list(v), list(V))

    name = unpack_name(v)

    if name == "CHAN2":
        print "Unpack name: OK"
    else:
        print "Unpack name: FAIL"

    v = pack_frequency(146.520)
    V = "\x00\x72\x78"

    if v != V:
        print "Pack frequency: FAIL"
        print "%s != %s" % (list(v), list(V))
    else:
        print "Pack frequency: OK"

    freq = unpack_frequency(v)

    if freq != 146.520:
        print "Unpack frequency: FAIL"
        print "%s != %s" % (freq, 146.520)
    else:
        print "Unpack frequency: OK"


if __name__ == "__main__":

    import sys

    test_basic()

    if len(sys.argv) > 1:
        mm = file(sys.argv[1], "rb")
        map = mm.read()

        parse_map_for_memory(map)
