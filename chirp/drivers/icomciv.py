
import struct, logging
from chirp.drivers import icf
from chirp import chirp_common, util, errors, bitwise, directory
from chirp.memmap import MemoryMap

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
bbcd number[2];
u8   unknown1;
lbcd freq[5];
u8   unknown2:5,
     mode:3;
"""
MEM_VFO_FORMAT = """
u8   vfo;
bbcd number[2];
u8   unknown1;
lbcd freq[5];
u8   unknown2:5,
     mode:3;
u8   unknown1;
u8   unknown2:2,
     duplex:2,
     unknown3:1,
     tmode:3;
u8   unknown4;
bbcd rtone[2];
u8   unknown5;
bbcd ctone[2];
u8   unknown6[2];
bbcd dtcs;
u8   unknown[17];
char name[9];
"""
mem_duptone_format = """
bbcd number[2];
u8   unknown1;
lbcd freq[5];
u8   unknown2:5,
     mode:3;
u8   unknown1;
u8   unknown2:2,
     duplex:2,
     unknown3:1,
     tmode:3;
u8   unknown4;
bbcd rtone[2];
u8   unknown5;
bbcd ctone[2];
u8   unknown6[2];
bbcd dtcs;
u8   unknown[11];
char name[9];
"""

class Frame:
    """Base class for an ICF frame"""
    _cmd = 0x00
    _sub = 0x00

    def __init__(self):
        self._data = ""

    def set_command(self, cmd, sub):
        """Set the command number (and optional subcommand)"""
        self._cmd = cmd
        self._sub = sub

    def get_data(self):
        """Return the data payload"""
        return self._data

    def set_data(self, data):
        """Set the data payload"""
        self._data = data

    def send(self, src, dst, serial, willecho=True):
        """Send the frame over @serial, using @src and @dst addresses"""
        raw = struct.pack("BBBBBB", 0xFE, 0xFE, src, dst, self._cmd, self._sub)
        raw += str(self._data) + chr(0xFD)

        LOG.debug("%02x -> %02x (%i):\n%s" % (src, dst,
                                          len(raw), util.hexprint(raw)))

        serial.write(raw)
        if willecho:
            echo = serial.read(len(raw))
            if echo != raw and echo:
                print "Echo differed (%i/%i)" % (len(raw), len(echo))
                print util.hexprint(raw)
                print util.hexprint(echo)

    def read(self, serial):
        """Read the frame from @serial"""
        data = ""
        while not data.endswith(chr(0xFD)):
            char = serial.read(1)
            if not char:
                print "Read %i bytes total" % len(data)
                raise errors.RadioError("Timeout")
            data += char

        if data == chr(0xFD):
            raise errors.RadioError("Radio reported error")

        src, dst = struct.unpack("BB", data[2:4])
        LOG.debug("%02x <- %02x:\n%s" % (src, dst, util.hexprint(data)))

        self._cmd = ord(data[4])
        self._sub = ord(data[5])
        self._data = data[6:-1]

        return src, dst

    def get_obj(self):
        raise errors.RadioError("Generic frame has no structure")

class MemFrame(Frame):
    """A memory frame"""
    _cmd = 0x1A
    _sub = 0x00
    _loc = 0

    def set_location(self, loc):
        """Set the memory location number"""
        self._loc = loc
        self._data = struct.pack(">H", int("%04i" % loc, 16))

    def make_empty(self):
        """Mark as empty so the radio will erase the memory"""
        self._data = struct.pack(">HB", int("%04i" % self._loc, 16), 0xFF)

    def is_empty(self):
        """Return True if memory is marked as empty"""
        return len(self._data) < 5

    def get_obj(self):
        """Return a bitwise parsed object"""
        self._data = MemoryMap(str(self._data)) # Make sure we're assignable
        return bitwise.parse(MEM_FORMAT, self._data)

    def initialize(self):
        """Initialize to sane values"""
        self._data = MemoryMap("".join(["\x00"] * (self.get_obj().size() / 8)))

class MultiVFOMemFrame(MemFrame):
    """A memory frame for radios with multiple VFOs"""
    def set_location(self, loc, vfo=1):
        self._loc = loc
        self._data = struct.pack(">BH", vfo, int("%04i" % loc, 16))

    def get_obj(self):
        self._data = MemoryMap(str(self._data)) # Make sure we're assignable
        return bitwise.parse(MEM_VFO_FORMAT, self._data)

class DupToneMemFrame(MemFrame):
    def get_obj(self):
        self._data = MemoryMap(str(self._data))
        return bitwise.parse(mem_duptone_format, self._data)

class IcomCIVRadio(icf.IcomLiveRadio):
    """Base class for ICOM CIV-based radios"""
    BAUD_RATE = 19200
    MODEL = "CIV Radio"
    _model = "\x00"
    _template = 0

    def _send_frame(self, frame):
        return frame.send(ord(self._model), 0xE0, self.pipe,
                          willecho=self._willecho)

    def _recv_frame(self, frame=None):
        if not frame:
            frame = Frame()
        frame.read(self.pipe)
        return frame

    def _initialize(self):
        pass

    def _detect_echo(self):
        echo_test = "\xfe\xfe\xe0\xe0\xfa\xfd"
        self.pipe.write(echo_test)
        resp = self.pipe.read(6)
        print "Echo:\n%s" % util.hexprint(resp)
        return resp == echo_test

    def __init__(self, *args, **kwargs):
        icf.IcomLiveRadio.__init__(self, *args, **kwargs)

        self._classes = {
            "mem" : MemFrame,
            }

        if self.pipe:
            self._willecho = self._detect_echo()
            print "Interface echo: %s" % self._willecho
            self.pipe.setTimeout(1)

        #f = Frame()
        #f.set_command(0x19, 0x00)
        #self._send_frame(f)
        #
        #res = f.read(self.pipe)
        #if res:
        #    print "Result: %x->%x (%i)" % (res[0], res[1], len(f.get_data()))
        #    print util.hexprint(f.get_data())
        #
        #self._id = f.get_data()[0]
        self._rf = chirp_common.RadioFeatures()

        self._initialize()

    def get_features(self):
        return self._rf

    def _get_template_memory(self):
        f = self._classes["mem"]()
        f.set_location(self._template)
        self._send_frame(f)
        f.read(self.pipe)
        return f

    def get_raw_memory(self, number):
        f = self._classes["mem"]()
        f.set_location(number)
        self._send_frame(f)
        f.read(self.pipe)
        return repr(f.get_obj())

    def get_memory(self, number):
        print "Getting %i" % number
        f = self._classes["mem"]()
        f.set_location(number)
        self._send_frame(f)

        mem = chirp_common.Memory()
        mem.number = number

        f = self._recv_frame(f)
        if len(f.get_data()) == 0:
            raise errors.RadioError("Radio reported error")
        if f.get_data() and f.get_data()[-1] == "\xFF":
            mem.empty = True
            return mem

        memobj = f.get_obj()
        print repr(memobj)

        mem.freq = int(memobj.freq)
        mem.mode = self._rf.valid_modes[memobj.mode]

        if self._rf.has_name:
            mem.name = str(memobj.name).rstrip()

        if self._rf.valid_tmodes:
            mem.tmode = self._rf.valid_tmodes[memobj.tmode]

        if self._rf.has_dtcs:
            # FIXME
            mem.dtcs = bitwise.bcd_to_int([memobj.dtcs])

        if "Tone" in self._rf.valid_tmodes:
            mem.rtone = int(memobj.rtone) / 10.0

        if "TSQL" in self._rf.valid_tmodes and self._rf.has_ctone:
            mem.ctone = int(memobj.ctone) / 10.0

        if self._rf.valid_duplexes:
            mem.duplex = self._rf.valid_duplexes[memobj.duplex]

        return mem

    def set_memory(self, mem):
        f = self._get_template_memory()
        if mem.empty:
            f.set_location(mem.number)
            f.make_empty()
            self._send_frame(f)
            return

        #f.set_data(MemoryMap(self.get_raw_memory(mem.number)))
        #f.initialize()

        memobj = f.get_obj()
        memobj.number = mem.number
        memobj.freq = int(mem.freq)
        memobj.mode = self._rf.valid_modes.index(mem.mode)
        if self._rf.has_name:
            memobj.name = mem.name.ljust(9)[:9]

        if self._rf.valid_tmodes:
            memobj.tmode = self._rf.valid_tmodes.index(mem.tmode)

        if self._rf.valid_duplexes:
            memobj.duplex = self._rf.valid_duplexes.index(mem.duplex)

        if self._rf.has_ctone:
            memobj.ctone = int(mem.ctone * 10)
            memobj.rtone = int(mem.rtone * 10)

        print repr(memobj)
        self._send_frame(f)

        f = self._recv_frame()
        print "Result:\n%s" % util.hexprint(f.get_data())

@directory.register
class Icom7200Radio(IcomCIVRadio):
    """Icom IC-7200"""
    MODEL = "7200"
    _model = "\x76"
    _template = 201

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
        self._rf.valid_bands = [(1800000, 59000000)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = []
        self._rf.memory_bounds = (1, 200)

@directory.register
class Icom7000Radio(IcomCIVRadio):
    """Icom IC-7000"""
    MODEL = "7000"
    _model = "\x70"
    _template = 102

    def _initialize(self):
        self._classes["mem"] = MultiVFOMemFrame
        self._rf.has_bank = False
        self._rf.has_dtcs_polarity = True
        self._rf.has_dtcs = True
        self._rf.has_ctone = True
        self._rf.has_offset = False
        self._rf.has_name = True
        self._rf.has_tuning_step = False
        self._rf.valid_modes = ["LSB", "USB", "AM", "CW", "RTTY", "FM"]
        self._rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        self._rf.valid_duplexes = ["", "-", "+"]
        self._rf.valid_bands = [(30000, 199999999), (400000000, 470000000)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = []
        self._rf.valid_name_length = 9
        self._rf.valid_characters = chirp_common.CHARSET_ASCII
        self._rf.memory_bounds = (1, 99)

@directory.register
class Icom746Radio(IcomCIVRadio):
    """Icom IC-746"""
    MODEL = "746"
    BAUD_RATE = 9600
    _model = "\x56"
    _template = 102

    def _initialize(self):
        self._classes["mem"] = DupToneMemFrame
        self._rf.has_bank = False
        self._rf.has_dtcs_polarity = False
        self._rf.has_dtcs = False
        self._rf.has_ctone = True
        self._rf.has_offset = False
        self._rf.has_name = True
        self._rf.has_tuning_step = False
        self._rf.valid_modes = ["LSB", "USB", "AM", "CW", "RTTY", "FM"]
        self._rf.valid_tmodes = ["", "Tone", "TSQL"]
        self._rf.valid_duplexes = ["", "-", "+"]
        self._rf.valid_bands = [(30000, 199999999)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = []
        self._rf.valid_name_length = 9
        self._rf.valid_characters = chirp_common.CHARSET_ASCII
        self._rf.memory_bounds = (1, 99)

CIV_MODELS = {
    (0x76, 0xE0) : Icom7200Radio,
    (0x70, 0xE0) : Icom7000Radio,
    (0x46, 0xE0) : Icom746Radio,
}

def probe_model(ser):
    """Probe the radio attatched to @ser for its model"""
    f = Frame()
    f.set_command(0x19, 0x00)

    for model, controller in CIV_MODELS.keys():
        f.send(model, controller, ser)
        try:
            f.read(ser)
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
