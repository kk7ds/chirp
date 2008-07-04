import struct

from repidr_common import IcomFrame
import util
import errors

class IC92Frame(IcomFrame):
    def from_raw(self, data):
        if not data.startswith("\xfe\xfe"):
            raise InvalidDataError("No header");

        if not data.endswith("\xfd"):
            raise InvalidDataError("No trailer");

        self._vfo = ord(data[3])
        self._magic = ord(data[2])

        self._data = data[4:-1]
        self._rawdata = data

        self._post_proc()

    def from_frame(self, frame):
        self._vfo = frame._vfo
        self._magic = frame._magic
        self._data = frame._data
        self._rawdata = frame._rawdata

        self._post_proc()

    def _post_proc(self):
        pass

    def __init__(self):
        self._vfo = 1
        self._magic = 80
        self._data = None
        self._rawdata = None

    def _make_raw(self):
        raise Exception("Not implemented")

    def __str__(self):
        s = "Frame VFO=%i (len = %i)\n" % (self._vfo, len(self._data))
        s += hexprint(self._data)
        s += "\n"

        return s

class IC92BankFrame(IC92Frame):
    def __str__(self):
        return "Bank %s: %s" % (self._data[2], self._data[3:])

class IC92MemoryFrame(IC92Frame):
    def _post_proc(self):
        if len(self._data) < 36:
            raise errors.InvalidDataError("Frame length %i is too short",
                                          len(self._data))

        self.isDV = (len(self._data) == 62)

        self._name = self._data[28:36]
        self._number, = struct.unpack(">H", self._data[3:5])

        h = int("%x" % ord(self._data[9]))
        t = int("%x" % ord(self._data[8]))
        d = int("%x" % ord(self._data[7]))

        self._freq = ((h * 100) + t) + (d / 100.0)

    def make_raw(self):
        self._rawdata = struct.pack(">BBBBBH",
                                    self._vfo,
                                    0x80,
                                    0x1A,
                                    0x00,
                                    0x01,
                                    self._number)
        self._rawdata += "\x00\x00"


        d = int("%i" % (int((self._freq - int(self._freq)) * 100)), 16)
        t = int("%i" % (int(self._freq) % 100), 16)
        h = int("%i" % (int(self._freq) / 100), 16)

        self._rawdata += struct.pack(">BBB",
                                     d,
                                     t,
                                     h)

        self._rawdata += "\x00" * 2
        self._rawdata += "\x60\x00\x00\x08\x85\x08\x85\x00"
        self._rawdata += "\x23\x22\x80\x06\x00\x00\x00\x00"
        self._rawdata += self._name
        self._rawdata += "\x00\x00" + ("\x20" * 16)
        self._rawdata += "CQCQCQ  "
                                    
        print "Raw memory frame:\n%s\n" % util.hexprint(self._rawdata)

    def set_memory(self, memory):
        self._name = memory.name.ljust(8)[0:8]
        self._number = memory.number
        self._freq = memory.freq
        self._vfo = memory.vfo

    def __str__(self):
        return "%i: %.2f (%s) (DV=%s)" % (self._number,
                                          self._freq,
                                          self._name,
                                          self.isDV)

def send(pipe, buf, verbose=False):
    realbuf = "\xfe\xfe" + buf + "\xfd"

    if verbose:
        print "Sending:\n%s" % hexprint(realbuf)

    pipe.write(realbuf)
    pipe.flush()

    data = ""
    while True:
        buf = pipe.read(4096)
        if not buf:
            break

        data += buf

    return util.parse_frames(data)

def send_magic(pipe, verbose=False):
    magic = ("\xfe" * 400) + "\x01\x80\x19"

    send(pipe, magic, verbose)

def print_banks(pipe):
    frames = send(pipe, "\x01\x80\x1a\x09") # Banks

    print "A Banks:"
    for i in range(180, 180+26):
        bf = IC92BankFrame()
        bf.from_frame(frames[i])
        print str(bf)

    print "B Banks:"
    for i in range(237, 237+26):
        bf = IC92BankFrame()
        bf.from_frame(frames[i])
        print str(bf)

def get_memory(pipe, vfo, number):
    seq = chr(vfo) + "\x80\x1a\x00\x01" + struct.pack(">H", number)
    frames = send(pipe, seq)

    if len(frames) == 0:
        raise errors.InvalidDataError("No response from radio")

    if len(frames[0]._data) < 6:
        raise errors.InvalidDataError("Got a short, unknown block from radio")

    if frames[0]._data[5] == '\xff':
        raise errors.InvalidMemoryLocation("Radio says location is empty")

    print "Memory result:\n%s" % util.hexprint(frames[0]._data)

    mf = IC92MemoryFrame()
    mf.from_frame(frames[0])

    return mf

def print_memory(pipe, vfo, number):
    if vfo not in [1, 2]:
        raise errors.InvalidValueError("VFO must be 1 or 2")

    if number < 0 or number > 999:
        raise errors.InvalidValueError("Number must be between 0 and 999")

    mf = get_memory(pipe, vfo, number)

    print "Memory %i from VFO %i: %s" % (number, vfo, str(mf))
