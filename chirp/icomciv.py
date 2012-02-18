
import struct
from chirp import chirp_common, icf, util, errors, bitwise, ic9x_ll, directory
from chirp.memmap import MemoryMap

DEBUG = True

mem_format = """
bbcd number[2];
u8   unknown1;
lbcd freq[5];
u8   unknown2:5,
     mode:3;
"""

class Frame:
    _cmd = 0x00
    _sub = 0x00

    def __init__(self):
        self._data = ""

    def set_command(self, cmd, sub):
        self._cmd = cmd
        self._sub = sub

    def get_data(self):
        return self._data

    def set_data(self, data):
        self._data = data

    def send(self, src, dst, serial):
        raw = struct.pack("BBBBBB", 0xFE, 0xFE, src, dst, self._cmd, self._sub)
        raw += self._data + chr(0xFD)

        if DEBUG:
            print "%02x -> %02x:\n%s" % (src, dst, util.hexprint(raw))

        serial.write(raw)
        echo = serial.read(len(raw))
        if echo != raw and echo:
            print "Echo differed"
            print util.hexprint(raw)
            print util.hexprint(echo)

    def read(self, serial):
        data = ""
        while not data.endswith(chr(0xFD)):
            c = serial.read(1)
            if not c:
                print "In buffer:\n%s" % util.hexprint(data)
                raise errors.RadioError("Timeout")
            data += c

        if data == chr(0xFD):
            raise errors.RadioError("Radio reported error")

        src, dst = struct.unpack("BB", data[2:4])
        if DEBUG:
            print "%02x <- %02x:\n%s" % (src, dst, util.hexprint(data))

        self._cmd = ord(data[4])
        self._sub = ord(data[5])
        self._data = data[6:-1]

        return src, dst

class MemFrame(Frame):
    _cmd = 0x1A
    _sub = 0x00
    _loc = 0

    def set_location(self, loc):
        self._loc = loc
        self._data = struct.pack(">H", int("%04i" % loc, 16))

    def make_empty(self):
        self._data = struct.pack(">HB", int("%04i" % self._loc, 16), 0xFF)

class IcomCIVRadio(icf.IcomLiveRadio):
    BAUD_RATE = 19200
    MODEL = "CIV Radio"

    def _send_frame(self, frame):
        return frame.send(0x76, 0xE0, self.pipe)

    def _recv_frame(self, frame=None):
        if not frame:
            frame = Frame()
        frame.read(self.pipe)
        return frame

    def _initialize(self):
        pass

    def __init__(self, *args, **kwargs):
        icf.IcomLiveRadio.__init__(self, *args, **kwargs)

        self.pipe.setTimeout(1)

        f = Frame()
        f.set_command(0x19, 0x00)
        self._send_frame(f)

        res = f.read(self.pipe)
        if res:
            print "Result: %x->%x (%i)" % (res[0], res[1], len(f.get_data()))
            print util.hexprint(f.get_data())

        self._id = f.get_data()[0]
        self._rf = chirp_common.RadioFeatures()

        self._initialize()

    def get_features(self):
        return self._rf

    def get_raw_memory(self, number):
        f = MemFrame()
        f.set_location(number)
        self._send_frame(f)
        f.read(self.pipe)
        return f.get_data()

    def get_memory(self, number):
        print "Getting %i" % number
        f = MemFrame()
        f.set_location(number)
        self._send_frame(f)

        mem = chirp_common.Memory()
        mem.number = number

        f = self._recv_frame(f)
        if f.get_data() and f.get_data()[2] == "\xFF":
            mem.empty = True
            return mem

        memobj = bitwise.parse(mem_format, f.get_data())

        mem.freq = int(memobj.freq) / 1000000.0
        mem.mode = self._rf.valid_modes[memobj.mode]

        return mem

    def set_memory(self, mem):
        f = MemFrame()
        if mem.empty:
            f.set_location(mem.number)
            f.make_empty()
            self._send_frame(f)
            return

        data = MemoryMap(self.get_raw_memory(mem.number))

        memobj = bitwise.parse(mem_format, data)
        memobj.number = mem.number
        memobj.freq = int(mem.freq * 1000000)

        f.set_data(data.get_packed())
        self._send_frame(f)

        f = self._recv_frame()
        print "Result:\n%s" % util.hexprint(f.get_data())

@directory.register
class Icom7200Radio(IcomCIVRadio):
    MODEL = "7200"
    _model = "\x76"

    def _initialize(self):
        self._rf.has_bank = False
        self._rf.has_dtcs_polarity = False
        self._rf.has_dtcs = False
        self._rf.has_ctone = False
        self._rf.has_offset = False
        self._rf.has_name = False
        self._rf.valid_modes = ["LSB", "USB", "AM", "CW", "RTTY"]
        self._rf.valid_tmodes = []
        self._rf.valid_duplexes = []
        self._rf.valid_bands = [(1.8, 59.0)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = []
        self._rf.memory_bounds = (1, 200)

CIV_MODELS = {
    (0x76, 0xE0) : Icom7200Radio,
}

def probe_model(s):
    f = Frame()
    f.set_command(0x19, 0x00)

    for model, controller in CIV_MODELS.keys():
        f.send(model, controller, s)
        try:
            f.read(s)
        except errors.RadioError:
            continue

        if len(f.get_data()) == 1:
            model = ord(f.get_data()[0])
            return CIV_MODELS[(model, controller)]

        if f.get_data():
            print "Got data, but not 1 byte:"
            print util.hexprint(f.get_data())
            raise errors.RadioError("Unknown response")

    raise errors.RadioError("Unsupported model")
