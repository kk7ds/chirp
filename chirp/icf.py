#!/usr/bin/python

import struct

import errors
import chirp_common
import util

CMD_CLONE_OUT = 0xE2
CMD_CLONE_IN  = 0xE3
CMD_CLONE_DAT = 0xE4
CMD_CLONE_END = 0xE5

def get_model_data(pipe, model="\x00\x00\x00\x00"):
    send_clone_frame(pipe, 0xe0, model, raw=True)

    model_data = ""

    while not model_data.endswith("\xfd"):
        model_data += pipe.read(1)

    hdr = "\xfe\xfe\xef\xee\xe1"

    if not model_data.startswith(hdr):
        print "Radio said:\n%s" % util.hexprint(model_data)
        raise errors.InvalidDataError("Unable to read radio model data");

    model_data = model_data[len(hdr):]
    model_data = model_data[:-1]

    return model_data

def get_clone_resp(pipe, length=None):
    def exit_criteria(buf, length):
        if length is None:
            return buf.endswith("\xfd")
        else:
            return len(buf) == length

    resp = ""
    while not exit_criteria(resp, length):
        resp += pipe.read(1)

    return resp

def send_clone_frame(pipe, cmd, data, raw=False, checksum=False):

    if raw:
        hed = data
    else:
        hed = ""
        for byte in data:
            hed += "%02X" % ord(byte)

    if checksum:
        cs = 0
        for i in data:
            cs += ord(i)

        cs = ((cs ^ 0xFFFF) + 1) & 0xFF
        cs = "%02X" % cs
    else:
        cs =""

    frame = "\xfe\xfe\xee\xef%s%s%s\xfd" % (chr(cmd), hed, cs)

    #print "Sending:\n%s" % util.hexprint(frame)
    
    pipe.write(frame)

    resp = get_clone_resp(pipe)
    if resp != frame:
        print "Bad response:\n%sSent:\n%s" % (util.hexprint(resp),
                                              util.hexprint(frame))
        raise errors.RadioError("Radio did not echo frame")

    return frame

def process_payload_frame(mem, data, last_eaddr=0):
    if len(data) < 8:
        # data is too short to be a frame
        return mem, last_eaddr, 0

    saddr = int(data[0:4], 16)
    bytes = int(data[4:6], 16)
    eaddr = saddr + bytes
    fdata = data[6:6+(bytes * 2)]

    try:
        checksum = data[8+(bytes * 2)]
        eof = data[8+(bytes * 2)]
    except IndexError:
        # Not quite enough
        return mem, last_eaddr, 0

    if eof != "\xfd":
        raise errors.InvalidDataError("Invalid frame trailer 0x%02X" % ord(eof))

    if len(fdata) != (bytes * 2):
        # data is too short to house entire frame, wait for more
        return mem, last_eaddr, 0

    if saddr != last_eaddr:
        count = saddr - eaddr
        mem += ("\x00" * count)

    i = 0
    while i < range(len(fdata)) and i+1 < len(fdata):
        try:
            val = int("%s%s" % (fdata[i], fdata[i+1]), 16)
            i += 2
            memdata = struct.pack("B", val)
            mem += memdata
        except Exception, e:
            print "Failed to parse byte: %s" % e
            break

    return mem, eaddr, (bytes * 2) + 8

def process_data_frames(data, map):
    data_hdr = "\xfe\xfe\xef\xee\xe4"

    end = 0
    while data.startswith(data_hdr):
        map, end, size = process_payload_frame(map, data[5:], end)
        if size == 0:
            break
        else:
            data = data[size + 6:]
            #print "Processed frame for %04x (%i bytes)" % (end, size)

    return data, map

def clone_from_radio(radio):
    send_clone_frame(radio.pipe, CMD_CLONE_OUT, radio._model, raw=True)

    data = ""
    map = ""
    while True:
        _d = radio.pipe.read(64)
        if not _d:
            break

        data += _d

        if not data.startswith("\xfe\xfe"):
            raise errors.InvalidDataError("Received broken frame from radio")

        if "\xfd" in data:
            data, map = process_data_frames(data, map)

        if radio.status_fn:
            s = chirp_common.Status()
            s.msg = "Cloning from radio"
            s.max = radio._memsize
            s.cur = len(map)
            radio.status_fn(s)

    return map

def send_mem_chunk(radio, start, stop, bs=32):
    for i in range(start, stop, bs):
        if i + bs < stop:
            size = bs
        else:
            size = stop - i

        chunk = struct.pack(">HB", i, size) + radio._mmap[i:i+size]

        frame = send_clone_frame(radio.pipe,
                                 CMD_CLONE_DAT,
                                 chunk,
                                 checksum=True)

        if radio.status_fn:
            s = chirp_common.Status()
            s.msg = "Cloning to radio"
            s.max = radio._memsize
            s.cur = i+bs
            
            radio.status_fn(s)

    return True

def clone_to_radio(radio):
    md = get_model_data(radio.pipe)

    if md[0:4] != radio._model:
        raise errors.RadioError("I can't talk to this model")

    send_clone_frame(radio.pipe, CMD_CLONE_IN, radio._model, raw=True)

    for start, stop, bs in radio._ranges:
        if not send_mem_chunk(radio, start, stop, bs):
            break

    send_clone_frame(radio.pipe, CMD_CLONE_END, radio._endframe, raw=True)

    termresp = get_clone_resp(radio.pipe)

    return termresp[5] == "\x00"
