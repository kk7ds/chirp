#!/usr/bin/python
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import errors
import chirp_common
import util

CMD_CLONE_OUT = 0xE2
CMD_CLONE_IN  = 0xE3
CMD_CLONE_DAT = 0xE4
CMD_CLONE_END = 0xE5

class IcfFrame:
    src = 0
    dst = 0
    cmd = 0

    payload = ""

    def __str__(self):
        addrs = { 0xEE : "PC",
                  0xEF : "Radio"}
        cmds = {0xE0 : "ID",
                0xE1 : "Model",
                0xE2 : "Clone out",
                0xE3 : "Clone in",
                0xE4 : "Clone data",
                0xE5 : "Clone end",
                0xE6 : "Clone result"}

        return "%s -> %s [%s]:\n%s" % (addrs[self.src], addrs[self.dst],
                                       cmds[self.cmd],
                                       utils.hexprint(self.payload))

def parse_frame_generic(data):
    f = IcfFrame()

    f.src = ord(data[2])
    f.dst = ord(data[3])
    f.cmd = ord(data[4])

    try:
        end = data.index("\xFD")
    except Exception, e:
        return None, data

    f.payload = data[5:end]

    return f, data[end+1:]

class RadioStream:
    def __init__(self, pipe):
        self.pipe = pipe
        self.data = ""

    def _process_frames(self):
        if not self.data.startswith("\xFE\xFE"):
            raise errors.InvalidDataError("Out of sync with radio")
        elif len(self.data) < 5:
            return [] # Not enough data for a full frame

        frames = []

        while self.data:
            try:
                cmd = ord(self.data[4])
            except IndexError:
                break # Out of data

            try:
                frame, rest = parse_frame_generic(self.data)
                if not frame:
                    break
                elif frame.src == 0xEE:
                    # PC echo, ignore
                    pass
                else:
                    frames.append(frame)

                self.data = rest
            except errors.InvalidDataError, e:
                print "Failed to parse frame: %s" % e
                return []

        return frames

    def get_frames(self, nolimit=False):
        while True:
            _data = self.pipe.read(64)
            if not _data:
                break
            else:
                self.data += _data

            if not nolimit and len(self.data) > 128 and "\xFD" in self.data:
                break # Give us a chance to do some status

        if not self.data:
            return []

        return self._process_frames()

def get_model_data(pipe, model="\x00\x00\x00\x00"):
    send_clone_frame(pipe, 0xe0, model, raw=True)

    stream = RadioStream(pipe)
    frames = stream.get_frames()

    if len(frames) != 1:
        raise errors.RadioError("Unexpected response from radio")

    return frames[0].payload

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
    return frame

    resp = get_clone_resp(pipe)
    if resp != frame:
        print "Bad response:\n%sSent:\n%s" % (util.hexprint(resp),
                                              util.hexprint(frame))
        raise errors.RadioError("Radio did not echo frame")

    return frame

def process_data_frame(frame, map):

    data = frame.payload

    saddr = int(data[0:4], 16)
    bytes = int(data[4:6], 16)
    eaddr = saddr + bytes
    fdata = data[6:6+(bytes * 2)]

    try:
        checksum = data[6+(bytes * 2)]
    except IndexError:
        print "%i Frame data:\n%s" % (bytes, util.hexprint(data))
        raise errors.InvalidDataError("Short frame")

    i = 0
    while i < range(len(fdata)) and i+1 < len(fdata):
        try:
            val = int("%s%s" % (fdata[i], fdata[i+1]), 16)
            i += 2
            map += struct.pack("B", val)
        except Exception, e:
            print "Failed to parse byte: %s" % e
            break

    return map

def clone_from_radio(radio):
    md = get_model_data(radio.pipe)

    if md[0:4] != radio._model:
        raise errors.RadioError("I can't talk to this model")

    send_clone_frame(radio.pipe, CMD_CLONE_OUT, radio._model, raw=True)

    stream = RadioStream(radio.pipe)

    data = ""
    map = ""
    while True:
        frames = stream.get_frames()
        if not frames:
            break

        data_frames = []
        for f in frames:
            if f.cmd == CMD_CLONE_DAT:
                map = process_data_frame(f, map)

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

    stream = RadioStream(radio.pipe)

    send_clone_frame(radio.pipe, CMD_CLONE_IN, radio._model, raw=True)

    frames = []

    for start, stop, bs in radio._ranges:
        if not send_mem_chunk(radio, start, stop, bs):
            break
        frames += stream.get_frames()

    send_clone_frame(radio.pipe, CMD_CLONE_END, radio._endframe, raw=True)
    frames += stream.get_frames(True)

    try:
        result = frames[-1]
    except IndexError:
        raise errors.RadioError("Did not get clone result from radio")

    return result.payload[0] == '\x00'
