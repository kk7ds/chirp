
import struct
import logging
from chirp.drivers import icf
from chirp import chirp_common, util, errors, bitwise, directory
from chirp.memmap import MemoryMap
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList, RadioSettingValueBoolean

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
bbcd number[2];
u8   unknown:3
     split:1,
     unknown_0:4;
lbcd freq[5];
u8   unknown2:5,
     mode:3;
u8   filter;
u8   unknown_1:3,
     dig:1,
     unknown_2:4;
"""


# http://www.vk4adc.com/
#     web/index.php/reference-information/49-general-ref-info/182-civ7400
MEM_IC7000_FORMAT = """
u8   bank;
bbcd number[2];
u8   spl:4,
     skip:4;
lbcd freq[5];
u8   mode;
u8   filter;
u8   duplex:4,
     tmode:4;
bbcd rtone[3];
bbcd ctone[3];
u8   dtcs_polarity;
bbcd dtcs[2];
lbcd freq_tx[5];
u8   mode_tx;
u8   filter_tx;
u8   duplex_tx:4,
     tmode_tx:4;
bbcd rtone_tx[3];
bbcd ctone_tx[3];
u8   dtcs_polarity_tx;
bbcd dtcs_tx[2];
char name[9];
"""

MEM_IC7100_FORMAT = """
u8   bank;                 // 1 bank number
bbcd number[2];            // 2,3
u8   splitSelect;          // 4 split and select memory settings
lbcd freq[5];              // 5-9 operating freq
u8   mode;                 // 10 operating mode
u8   filter;               // 11 filter
u8   dataMode;             // 12 data mode setting (on or off)
u8   duplex:4,             // 13 duplex on/-/+
     tmode:4;              // 13 tone
u8   dsql:4,               // 14 digital squelch
     unknown1:4;           // 14 zero
bbcd rtone[3];             // 15-17 repeater tone freq
bbcd ctone[3];             // 18-20 tone squelch setting
u8   dtcsPolarity;         // 21 DTCS polarity
u8   unknown2:4,           // 22 zero
     firstDtcs:4;          // 22 first digit of DTCS code
u8   secondDtcs:4,         // 23 second digit DTCS
     thirdDtcs:4;          // 23 third digit DTCS
u8   digitalSquelch;       // 24 Digital code squelch setting
u8   duplexOffset[3];      // 25-27 duplex offset freq
char destCall[8];          // 28-35 destination call sign
char accessRepeaterCall[8];// 36-43 access repeater call sign
char linkRepeaterCall[8];  // 44-51 gateway/link repeater call sign
bbcd duplexSettings[47];   // repeat of 5-51 for duplex
char name[16];             // 52-60 Name of station
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
u8   dtcs_polarity;
bbcd dtcs[2];
u8   unknown[11];
char name[9];
"""

SPLIT = ["", "spl"]


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

        LOG.debug("%02x -> %02x (%i):\n%s" %
                  (src, dst, len(raw), util.hexprint(raw)))

        serial.write(raw)
        if willecho:
            echo = serial.read(len(raw))
            if echo != raw and echo:
                LOG.debug("Echo differed (%i/%i)" % (len(raw), len(echo)))
                LOG.debug(util.hexprint(raw))
                LOG.debug(util.hexprint(echo))

    def read(self, serial):
        """Read the frame from @serial"""
        data = ""
        while not data.endswith(chr(0xFD)):
            char = serial.read(1)
            if not char:
                LOG.debug("Read %i bytes total" % len(data))
                raise errors.RadioError("Timeout")
            data += char

        if data == chr(0xFD):
            raise errors.RadioError("Radio reported error")

        src, dst = struct.unpack("BB", data[2:4])
        LOG.debug("%02x <- %02x:\n%s" % (dst, src, util.hexprint(data)))

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
        self._data = MemoryMap(str(self._data))  # Make sure we're assignable
        return bitwise.parse(MEM_FORMAT, self._data)

    def initialize(self):
        """Initialize to sane values"""
        self._data = MemoryMap("".join(["\x00"] * (self.get_obj().size() / 8)))


class BankMemFrame(MemFrame):
    """A memory frame for radios with multiple banks"""
    FORMAT = MEM_IC7000_FORMAT
    _bnk = 0

    def set_location(self, loc, bank=1):
        self._loc = loc
        self._bnk = bank
        self._data = struct.pack(
            ">BH", int("%02i" % bank, 16), int("%04i" % loc, 16))

    def make_empty(self):
        """Mark as empty so the radio will erase the memory"""
        self._data = struct.pack(
            ">BHB", int("%02i" % self._bnk, 16),
            int("%04i" % self._loc, 16), 0xFF)

    def get_obj(self):
        self._data = MemoryMap(str(self._data))  # Make sure we're assignable
        return bitwise.parse(self.FORMAT, self._data)


class IC7100MemFrame(BankMemFrame):
    FORMAT = MEM_IC7100_FORMAT


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

    # complete list of modes from CI-V documentation
    # each radio supports a subset
    # WARNING: "S-AM" and "PSK" are not valid (yet) for chirp
    _MODES = [
        "LSB", "USB", "AM", "CW", "RTTY", "FM", "WFM", "CWR"
        "RTTYR", "S-AM", "PSK", None, None, None, None, None,
        None, None, None, None, None, None, None, None,
        "DV",
    ]

    def mem_to_ch_bnk(self, mem):
        l, h = self._bank_index_bounds
        bank_no = (mem // (h - l + 1)) + l
        channel = mem % (h - l + 1) + l
        return (channel, bank_no)

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
        LOG.debug("Echo:\n%s" % util.hexprint(resp))
        return resp == echo_test

    def __init__(self, *args, **kwargs):
        icf.IcomLiveRadio.__init__(self, *args, **kwargs)

        self._classes = {
            "mem": MemFrame,
            }

        if self.pipe:
            self._willecho = self._detect_echo()
            LOG.debug("Interface echo: %s" % self._willecho)
            self.pipe.timeout = 1

        # f = Frame()
        # f.set_command(0x19, 0x00)
        # self._send_frame(f)
        #
        # res = f.read(self.pipe)
        # if res:
        #    LOG.debug("Result: %x->%x (%i)" %
        #              (res[0], res[1], len(f.get_data())))
        #    LOG.debug(util.hexprint(f.get_data()))
        #
        # self._id = f.get_data()[0]
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
        if self._rf.has_bank:
            ch, bnk = self.mem_to_ch_bnk(number)
            f.set_location(ch, bnk)
            loc = "bank %i, channel %02i" % (bnk, ch)
        else:
            f.set_location(number)
            loc = "number %i" % number
        self._send_frame(f)
        f.read(self.pipe)
        if f.get_data() and f.get_data()[-1] == "\xFF":
            return "Memory " + loc + " empty."
        else:
            return repr(f.get_obj())

# We have a simple mapping between the memory location in the frequency
# editor and (bank, channel) of the radio.  The mapping doesn't
# change so we use a little math to calculate what bank a location
# is in.  We can't change the bank a location is in so we just pass.
    def _get_bank(self, loc):
        l, h = self._bank_index_bounds
        return loc // (h - l + 1)

    def _set_bank(self, loc, bank):
        pass

    def get_memory(self, number):
        LOG.debug("Getting %i" % number)
        f = self._classes["mem"]()
        if self._rf.has_bank:
            ch, bnk = self.mem_to_ch_bnk(number)
            f.set_location(ch, bnk)
            LOG.debug("Bank %i, Channel %02i" % (bnk, ch))
        else:
            f.set_location(number)
        self._send_frame(f)

        mem = chirp_common.Memory()
        mem.number = number
        mem.immutable = []

        f = self._recv_frame(f)
        if len(f.get_data()) == 0:
            raise errors.RadioError("Radio reported error")
        if f.get_data() and f.get_data()[-1] == "\xFF":
            mem.empty = True
            LOG.debug("Found %i empty" % mem.number)
            return mem

        memobj = f.get_obj()
        LOG.debug(repr(memobj))

        try:
            if memobj.skip == 1:
                mem.skip = ""
            else:
                mem.skip = "S"
        except AttributeError:
            pass

        mem.freq = int(memobj.freq)
        try:
            mem.mode = self._MODES[memobj.mode]

            # We do not know what a variety of the positions between
            # PSK and DV mean, so let's behave as if those values
            # are not set to maintain consistency between known-unknown
            # values and unknown-unknown ones.
            if mem.mode is None:
                raise IndexError(memobj.mode)
        except IndexError:
            LOG.error(
                "Bank %s location %s is set for mode %s, but no known "
                "mode matches that value.",
                int(memobj.bank),
                int(memobj.number),
                repr(memobj.mode),
            )
            raise

        if self._rf.has_name:
            mem.name = str(memobj.name).rstrip()

        if self._rf.valid_tmodes:
            mem.tmode = self._rf.valid_tmodes[memobj.tmode]

        if self._rf.has_dtcs_polarity:
            if memobj.dtcs_polarity == 0x11:
                mem.dtcs_polarity = "RR"
            elif memobj.dtcs_polarity == 0x10:
                mem.dtcs_polarity = "RN"
            elif memobj.dtcs_polarity == 0x01:
                mem.dtcs_polarity = "NR"
            else:
                mem.dtcs_polarity = "NN"

        if self._rf.has_dtcs:
            mem.dtcs = bitwise.bcd_to_int(memobj.dtcs)

        if "Tone" in self._rf.valid_tmodes:
            mem.rtone = int(memobj.rtone) / 10.0

        if "TSQL" in self._rf.valid_tmodes and self._rf.has_ctone:
            mem.ctone = int(memobj.ctone) / 10.0

        if self._rf.valid_duplexes:
            mem.duplex = self._rf.valid_duplexes[memobj.duplex]

        if self._rf.can_odd_split and memobj.spl:
            mem.duplex = "split"
            mem.offset = int(memobj.freq_tx)
            mem.immutable = []
        else:
            mem.immutable = ["offset"]

        mem.extra = RadioSettingGroup("extra", "Extra")
        try:
            dig = RadioSetting("dig", "Digital",
                               RadioSettingValueBoolean(bool(memobj.dig)))
        except AttributeError:
            pass
        else:
            dig.set_doc("Enable digital mode")
            mem.extra.append(dig)

        options = ["Wide", "Mid", "Narrow"]
        try:
            fil = RadioSetting(
                "filter", "Filter",
                RadioSettingValueList(options,
                                      options[memobj.filter - 1]))
        except AttributeError:
            pass
        else:
            fil.set_doc("Filter settings")
            mem.extra.append(fil)

        return mem

    def set_memory(self, mem):
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
        if self._rf.has_bank:
            ch, bnk = self.mem_to_ch_bnk(mem.number)
            LOG.debug("Bank %i, Channel %02i" % (bnk, ch))
        f = self._get_template_memory()
        if mem.empty:
            if self._rf.has_bank:
                f.set_location(ch, bnk)
            else:
                f.set_location(mem.number)
            LOG.debug("Making %i empty" % mem.number)
            f.make_empty()
            self._send_frame(f)

# The next two lines accept the radio's status after setting the memory
# and reports the results to the debug log.  This is needed for the
# IC-7000.  No testing was done to see if it breaks memory delete on the
# IC-746 or IC-7200.
            f = self._recv_frame()
            LOG.debug("Result:\n%s" % util.hexprint(f.get_data()))
            return

        # f.set_data(MemoryMap(self.get_raw_memory(mem.number)))
        # f.initialize()

        memobj = f.get_obj()
        if self._rf.has_bank:
            memobj.bank = bnk
            memobj.number = ch
        else:
            memobj.number = mem.number
        if mem.skip == "S":
            memobj.skip = 0
        else:
            try:
                memobj.skip = 1
            except KeyError:
                pass
        memobj.freq = int(mem.freq)
        memobj.mode = self._MODES.index(mem.mode)
        if self._rf.has_name:
            name_length = len(memobj.name.get_value())
            memobj.name = mem.name.ljust(name_length)[:name_length]

        if self._rf.valid_tmodes:
            memobj.tmode = self._rf.valid_tmodes.index(mem.tmode)

        if self._rf.has_ctone:
            memobj.ctone = int(mem.ctone * 10)
            memobj.rtone = int(mem.rtone * 10)

        if self._rf.has_dtcs_polarity:
            if mem.dtcs_polarity == "RR":
                memobj.dtcs_polarity = 0x11
            elif mem.dtcs_polarity == "RN":
                memobj.dtcs_polarity = 0x10
            elif mem.dtcs_polarity == "NR":
                memobj.dtcs_polarity = 0x01
            else:
                memobj.dtcs_polarity = 0x00

        if self._rf.has_dtcs:
            bitwise.int_to_bcd(memobj.dtcs, mem.dtcs)

        if self._rf.can_odd_split and mem.duplex == "split":
            memobj.spl = 1
            memobj.duplex = 0
            memobj.freq_tx = int(mem.offset)
            memobj.tmode_tx = memobj.tmode
            memobj.ctone_tx = memobj.ctone
            memobj.rtone_tx = memobj.rtone
            memobj.dtcs_polarity_tx = memobj.dtcs_polarity
            memobj.dtcs_tx = memobj.dtcs
        elif self._rf.valid_duplexes:
            memobj.duplex = self._rf.valid_duplexes.index(mem.duplex)

        for setting in mem.extra:
            if setting.get_name() == "filter":
                setattr(memobj, setting.get_name(), int(setting.value) + 1)
            else:
                setattr(memobj, setting.get_name(), setting.value)

        LOG.debug(repr(memobj))
        self._send_frame(f)

        f = self._recv_frame()
        LOG.debug("Result:\n%s" % util.hexprint(f.get_data()))


@directory.register
class Icom7200Radio(IcomCIVRadio):
    """Icom IC-7200"""
    MODEL = "7200"
    _model = "\x76"
    _template = 201

    _num_banks = 1		# Banks not supported

    def _initialize(self):
        self._rf.has_bank = False
        self._rf.has_dtcs_polarity = False
        self._rf.has_dtcs = False
        self._rf.has_ctone = False
        self._rf.has_offset = False
        self._rf.has_name = False
        self._rf.has_tuning_step = False
        self._rf.valid_modes = ["LSB", "USB", "AM", "CW", "RTTY",
                                "CWR", "RTTYR"]
        self._rf.valid_tmodes = []
        self._rf.valid_duplexes = []
        self._rf.valid_bands = [(30000, 60000000)]
        self._rf.valid_skips = []
        self._rf.memory_bounds = (1, 201)


@directory.register
class Icom7000Radio(IcomCIVRadio):
    """Icom IC-7000"""
    MODEL = "IC-7000"
    _model = "\x70"
    _template = 102

    _num_banks = 5		# Banks A-E
    _bank_index_bounds = (1, 99)
    _bank_class = icf.IcomBank

    def _initialize(self):
        self._classes["mem"] = BankMemFrame
        self._rf.has_bank = True
        self._rf.has_dtcs_polarity = True
        self._rf.has_dtcs = True
        self._rf.has_ctone = True
        self._rf.has_offset = True
        self._rf.has_name = True
        self._rf.has_tuning_step = False
        self._rf.valid_modes = ["LSB", "USB", "AM", "CW", "RTTY", "FM", "WFM"]
        self._rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        self._rf.valid_duplexes = ["", "-", "+", "split"]
        self._rf.valid_bands = [(30000, 199999999), (400000000, 470000000)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = ["S", ""]
        self._rf.valid_name_length = 9
        self._rf.valid_characters = chirp_common.CHARSET_ASCII
        self._rf.memory_bounds = (0, 99 * self._num_banks - 1)
        self._rf.can_odd_split = True


@directory.register
class Icom7100Radio(IcomCIVRadio):
    """Icom IC-7100"""
    MODEL = "IC-7100"
    _model = "\x88"
    _template = 102

    _num_banks = 5
    _bank_index_bounds = (1, 99)
    _bank_class = icf.IcomBank

    def _initialize(self):
        self._classes["mem"] = IC7100MemFrame
        self._rf.has_bank = True
        self._rf.has_bank_index = False
        self._rf.has_bank_names = False
        self._rf.has_dtcs_polarity = False
        self._rf.has_dtcs = False
        self._rf.has_ctone = True
        self._rf.has_offset = False
        self._rf.has_name = True
        self._rf.has_tuning_step = False
        self._rf.valid_modes = [
            "LSB", "USB", "AM", "CW", "RTTY", "FM", "WFM", "CWR", "RTTYR", "DV"
        ]
        self._rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        self._rf.valid_duplexes = ["", "-", "+"]
        self._rf.valid_bands = [(30000, 199999999), (400000000, 470000000)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = []
        self._rf.valid_name_length = 16
        self._rf.valid_characters = chirp_common.CHARSET_ASCII
        self._rf.memory_bounds = (0, 99 * self._num_banks - 1)


@directory.register
class Icom746Radio(IcomCIVRadio):
    """Icom IC-746"""
    MODEL = "746"
    BAUD_RATE = 9600
    _model = "\x56"
    _template = 102

    _num_banks = 1		# Banks not supported

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
    (0x76, 0xE0): Icom7200Radio,
    (0x88, 0xE0): Icom7100Radio,
    (0x70, 0xE0): Icom7000Radio,
    (0x46, 0xE0): Icom746Radio,
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
            LOG.debug("Got data, but not 1 byte:")
            LOG.debug(util.hexprint(f.get_data()))
            raise errors.RadioError("Unknown response")

    raise errors.RadioError("Unsupported model")
