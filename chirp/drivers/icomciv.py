# Latest update: April, 2021 Add hasattr test at line 564
import struct
import logging
from chirp.drivers import icf
from chirp import chirp_common, util, errors, bitwise, directory
from chirp.memmap import MemoryMapBytes
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
lbcd duplexOffset[3];      // 25-27 duplex offset freq
char destCall[8];          // 28-35 destination call sign
char accessRepeaterCall[8];// 36-43 access repeater call sign
char linkRepeaterCall[8];  // 44-51 gateway/link repeater call sign
bbcd duplexSettings[47];   // repeat of 5-51 for duplex
char name[16];             // 52-60 Name of station
"""

MEM_IC910_FORMAT = """
u8   bank;                 // 1 bank number
bbcd number[2];            // 2,3
lbcd freq[5];              // 4-8 operating freq
u8   mode;                 // 9 operating mode
u8   filter;               // 10 filter
u8   tmode:4,              // 11 tone
     duplex:4;             // 11 duplex off/-/+
bbcd rtone[3];             // 12-14 repeater tone freq
bbcd ctone[3];             // 15-17 tone squelch setting
lbcd duplexOffset[3];      // 18-20 duplex offset freq
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

MEM_IC7300_FORMAT = """
bbcd number[2];            // 1,2
u8   spl:4,                // 3 split and select memory settings
     select:4;
lbcd freq[5];              // 4-8 receive freq
u8   mode;                 // 9 operating mode
u8   filter;               // 10 filter 1-3 (undocumented)
u8   dataMode:4,           // 11 data mode setting (on or off)
     tmode:4;              // 11 tone type
char pad1;
bbcd rtone[2];             // 12-14 tx tone freq
char pad2;
bbcd ctone[2];             // 15-17 tone rx squelch setting
// This is duplicated from 4-17 above, even duplicated by number in the
// manual!
lbcd freq_tx[5];              // 4-8 receive freq
u8   mode_tx;                 // 9 operating mode
u8   filter_tx;               // 10 filter 1-3 (undocumented)
u8   dataMode_tx:4,           // 11 data mode setting (on or off)
     tmode_tx:4;              // 11 tone type
char pad1_tx;
bbcd rtone_tx[2];             // 12-14 tx tone freq
char pad2_tx;
bbcd ctone_tx[2];             // 15-17 tone rx squelch setting
// End TX duplicate block
char name[10];             // 18-27 Callsign
"""

MEM_IC9700_FORMAT = """
u8 bank;
bbcd number[2];
u8 select_memory;
lbcd freq[5];
bbcd mode;
u8 filter;
bbcd data_mode;
u8 duplex:4,
   tmode:4;
u8 dig_sql:4,
   unused1:4;
bbcd rtone[3];
bbcd ctone[3];
u8 dtcs_polarity;
bbcd dtcs[2];
u8 dig_code;
lbcd duplexOffset[3];
char urcall[8];
char rpt1call[8];
char rpt2call[8];
char name[16];
"""

MEM_IC9700_SAT_FORMAT = """
bbcd number[2];
lbcd freq[5];
bbcd mode;
u8 filter;
bbcd data_mode;
u8 unused1:4,
   tmode:4;
u8 unused2:4,
   dig_sql:4;
bbcd rtone[3];
bbcd ctone[3];
u8 dtcs_polarity;
bbcd dtcs[2];
u8 dig_code;
char urcall[8];
char rpt1call[8];
char rpt2call[8];
struct {
  lbcd freq[5];
  bbcd mode;
  u8 filter;
  bbcd data_mode;
  u8 unused1:4,
     tmode:4;
  u8 unused2:4,
     dig_sql:4;
     bbcd rtone[3];
     bbcd ctone[3];
     u8 dtcs_polarity;
     bbcd dtcs[2];
     u8 dig_code;
     char urcall[8];
     char rpt1call[8];
     char rpt2call[8];
  } tx;
char name[16];
"""

MEM_IC7400_FORMAT = """
bbcd number[2];
u8   unknown1;
lbcd freq[5];
u8   mode;
u8   filter;
u8   unknown2:7,
     dig:1;
u8   unknown3:2,
     duplex:2,
     unknown4:1,
     tmode:3;
bbcd rtone[3];
bbcd ctone[3];
u8   dtcs_polarity;
bbcd dtcs[2];
// As with IC-7300 it seems the following are duplicated parameters save for
// `dig` which seem to be zeroed in unknown5
lbcd freq_tx[5];
u8   mode_tx;
u8   filter_tx;
u8 unknown5;
u8   unknown6:2,
     duplex_tx:2,
     unknown7:1,
     tmode_tx:3;
bbcd rtone_tx[3];
bbcd ctone_tx[3];
u8   dtcs_polarity_tx;
bbcd dtcs_tx[2];
// End TX duplicate block
char name[8];
"""

MEM_IC7610_FORMAT = """
bbcd number[2];            // 1,2
u8   spl:4,                // 3 split and select memory settings
     select:4;
lbcd freq[5];              // 4-8 receive freq
u8   mode;                 // 9 operating mode
u8   filter;               // 10 filter 1-3 (undocumented)
u8   dataMode:4,           // 11 data mode setting (on or off)
     tmode:4;              // 11 tone type
char pad1;
bbcd rtone[2];             // 12-14 tx tone freq
char pad2;
bbcd ctone[2];             // 15-17 tone rx squelch setting
char name[10];             // 18-27 Callsign
"""

SPLIT = ["", "spl"]


class Frame:
    """Base class for an ICF frame"""
    _cmd = 0x00
    _sub: int | None = 0x00

    def __init__(self):
        self._data = b""

    def set_command(self, cmd, sub=None):
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
        hdr = struct.pack("BBBBB", 0xFE, 0xFE, src, dst, self._cmd)
        # Some commands have no subcommand
        if self._sub is not None:
            hdr += bytes([self._sub])
        raw = bytearray(hdr)
        if isinstance(self._data, MemoryMapBytes):
            data = self._data.get_packed()
        else:
            data = self._data
        raw.extend(data)
        raw.append(0xFD)

        LOG.debug("%02x -> %02x (%i):\n%s" %
                  (src, dst, len(raw), util.hexprint(bytes(raw))))

        serial.write(raw)
        if willecho:
            echo = serial.read(len(raw))
            if echo != raw and echo:
                LOG.debug("Echo differed (%i/%i)" % (len(raw), len(echo)))
                LOG.debug(util.hexprint(bytes(raw)))
                LOG.debug(util.hexprint(bytes(echo)))

    def read(self, serial):
        """Read the frame from @serial"""
        data = bytearray()
        while not (data and data[-1] == 0xFD):
            char = serial.read(1)
            if not char:
                LOG.debug("Read %i bytes total" % len(data))
                raise errors.RadioError("Timeout")
            data.extend(char)

        if data[0] == 0xFD:
            raise errors.RadioError("Radio reported error")

        src, dst = struct.unpack("BB", data[2:4])
        LOG.debug("%02x <- %02x:\n%s" % (dst, src, util.hexprint(bytes(data))))

        self._cmd = data[4]
        # If we've been set with a None subcommand, assume we don't expect
        # it from the radio
        if self._sub is None:
            dataidx = 5
        else:
            self._sub = data[5]
            dataidx = 6
        self._data = data[dataidx:-1]

        return src, dst

    def get_obj(self):
        raise errors.RadioError("Generic frame has no structure")


class MemFrame(Frame):
    """A memory frame"""
    _cmd = 0x1A
    _sub = 0x00
    _loc = 0
    FORMAT = MEM_FORMAT

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
        # Make sure we're assignable
        self._data = MemoryMapBytes(bytes(self._data))
        return bitwise.parse(self.FORMAT, self._data)

    def initialize(self):
        """Initialize to sane values"""
        self._data = bytes(b'\x00' * (self.get_obj().size() // 8))


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
        # Make sure we're assignable
        self._data = MemoryMapBytes(bytes(self._data))
        return bitwise.parse(self.FORMAT, self._data)


class IC7100MemFrame(BankMemFrame):
    FORMAT = MEM_IC7100_FORMAT


class IC910MemFrame(BankMemFrame):
    FORMAT = MEM_IC910_FORMAT


class DupToneMemFrame(MemFrame):
    def get_obj(self):
        self._data = MemoryMapBytes(bytes(self._data))
        return bitwise.parse(mem_duptone_format, self._data)


class IC7400MemFrame(MemFrame):
    def get_obj(self):
        self._data = MemoryMapBytes(bytes(self._data))
        return bitwise.parse(MEM_IC7400_FORMAT, self._data)


class IC7300MemFrame(MemFrame):
    FORMAT = MEM_IC7300_FORMAT


class IC7610MemFrame(MemFrame):
    FORMAT = MEM_IC7610_FORMAT


class IC9700MemFrame(BankMemFrame):
    FORMAT = MEM_IC9700_FORMAT


class IC9700SatMemFrame(MemFrame):
    _sub = 0x07
    FORMAT = MEM_IC9700_SAT_FORMAT


class SpecialChannel(object):
    """Info for special (named) channels"""

    def __init__(self):
        self.name = None
        self.location = None
        self.channel = None

    def __repr__(self):
        s = "SpecialChannel(name=%r, location=%r, channel=%r)"
        return s % (self.name, self.location, self.channel)


class BankSpecialChannel(SpecialChannel):
    """Info for special (named) channels for radios with multiple banks"""

    def __init__(self):
        super(BankSpecialChannel, self).__init__()
        self.bank = None

    def __repr__(self):
        s = "BankSpecialChannel(name=%r, location=%r, bank=%r, channel=%r)"
        return s % (self.name, self.location, self.bank, self.channel)


class IcomCIVRadio(icf.IcomLiveRadio):
    """Base class for ICOM CIV-based radios"""
    BAUD_RATE = 19200
    MODEL = "CIV Radio"
    # RTS is interpreted as "transmit now" on some interface boxes for these
    WANTS_RTS = False
    _model = "\x00"
    _template = 0

    # complete list of modes from CI-V documentation
    # each radio supports a subset
    # WARNING: "S-AM" and "PSK" are not valid (yet) for chirp
    _MODES = [
        "LSB", "USB", "AM", "CW", "RTTY", "FM", "WFM", "CWR",
        "RTTYR", "S-AM", "PSK", None, None, None, None, None,
        None, None, None, None, None, None, None, None,
        "DV",
    ]

    # Unified modes where mode and filter are combined. See note at
    # _unified_modes.
    _UNIFIED_MODES = {
        'FM': 'NFM',
        'CW': 'NCW'
    }

    def mem_to_ch_bnk(self, mem):
        if self._adjust_bank_loc_start:
            mem -= 1
        l, h = self._bank_index_bounds
        bank_no = (mem // (h - l + 1)) + l
        channel = mem % (h - l + 1) + l
        return (channel, bank_no)

    def _is_special(self, number):
        return False

    def _get_special_info(self, number):
        raise errors.RadioError("Radio does not support special channels")

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
        echo_test = b"\xfe\xfe\xe0\xe0\xfa\xfd"
        self.pipe.write(echo_test)
        resp = self.pipe.read(6)
        LOG.debug("Echo:\n%s" % util.hexprint(bytes(resp)))
        return resp == echo_test

    def _detect_baudrate(self):
        if self._baud_detected:
            return

        # Don't ever try to run this twice, even if we fail
        self._baud_detected = True

        bauds = [9600, 19200, 38400, 57600, 115200, 4800]
        bauds.remove(self.BAUD_RATE)
        bauds.insert(0, self.BAUD_RATE)
        self.pipe.timeout = 0.25
        for baud in bauds:
            LOG.debug('Trying %i baud' % baud)
            self.pipe.baudrate = baud
            self._willecho = self._detect_echo()
            LOG.debug("Interface echo: %s" % self._willecho)
            try:
                self._get_template_memory()
                LOG.info('Detected %i baud' % baud)
                break
            except errors.RadioError:
                pass
        else:
            LOG.warning('Unable to detect baudrate, using default of %i' % (
                self.BAUD_RATE))
            self.pipe.baudrate = self.BAUD_RATE

        # Restore the historical default of 1s timeout for this driver
        self.pipe.timeout = 1

    def __init__(self, *args, **kwargs):
        icf.IcomLiveRadio.__init__(self, *args, **kwargs)

        self._classes = {
            "mem": MemFrame,
            }

        if self.pipe:
            self._willecho = self._detect_echo()
            LOG.debug("Interface echo: %s" % self._willecho)
            self.pipe.timeout = 1
        else:
            self._willecho = False

        self._baud_detected = False

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

        # On some radios, the filter field is used to signify normal versus
        # narrow modes, rather than being a distinct passband feature. As
        # such, mode + filter comprises a "unified mode" value that can be
        # mapped into a Chirp mode.
        self._unified_modes = False

        # Icom live radios with bank support present their memories to the
        # user starting from 1. For some reason, IC-7000 and IC-7100 were
        # implemented with the Chirp location starting from 0, so that the
        # user must mentally adjust. While adding IC-910 support, allowance
        # was made to provide a 1-based start, using the following setting.
        # This is not currently applied to the IC-7000 or IC-7100 due to the
        # inability to test, and also since changing it may cause issues if
        # location limit keys have been saved in the user's config file.
        self._adjust_bank_loc_start = False

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
        self._detect_baudrate()
        LOG.debug("Getting %s (raw)" % number)
        f = self._classes["mem"]()
        if self._is_special(number):
            info = self._get_special_info(number)
            LOG.debug("Special info: %s" % info)
            ch = info.channel
            if self._rf.has_bank:
                bnk = info.bank
        elif self._rf.has_bank:
            ch, bnk = self.mem_to_ch_bnk(number)
        else:
            ch = number
        if self._rf.has_bank:
            f.set_location(ch, bnk)
            loc = "bank %i, channel %02i" % (bnk, ch)
        else:
            f.set_location(ch)
            loc = "number %i" % ch
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
        if self._adjust_bank_loc_start:
            loc -= 1
        l, h = self._bank_index_bounds
        return loc // (h - l + 1)

    def _set_bank(self, loc, bank):
        pass

    def get_memory(self, number):
        self._detect_baudrate()
        LOG.debug("Getting %s" % number)
        f = self._classes["mem"]()
        mem = chirp_common.Memory()
        if self._is_special(number):
            info = self._get_special_info(number)
            LOG.debug("Special info: %s" % info)
            if self._rf.has_bank:
                f.set_location(info.channel, info.bank)
            else:
                f.set_location(info.channel)
            mem.number = info.location
            mem.extd_number = info.name
            mem.immutable = ["number", "extd_number"]
        else:
            if self._rf.has_bank:
                ch, bnk = self.mem_to_ch_bnk(number)
                f.set_location(ch, bnk)
                LOG.debug("Bank %i, Channel %02i" % (bnk, ch))
            else:
                f.set_location(number)
            mem.number = number
        self._send_frame(f)

        f = self._recv_frame(f)
        if len(f.get_data()) == 0:
            raise errors.RadioError("Radio reported error")
        if f.get_data() and f.get_data()[-1] == 0xFF:
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
            # Note that memobj.mode could be a bcd on some radios, so we must
            # coerce it to an int for the index operation.
            mem.mode = self._MODES[int(memobj.mode)]

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
        if self._unified_modes and memobj.filter == 2:
            try:
                # Adjust mode to its narrow variant
                mem.mode = self._UNIFIED_MODES[mem.mode]
            except KeyError:
                LOG.error(
                    "Bank %s location %s is set for mode %s with filter %s, "
                    "but no known mode matches that combination.",
                    int(memobj.bank),
                    int(memobj.number),
                    repr(memobj.mode),
                    int(memobj.filter),
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
            if hasattr(memobj, "duplex"):
                mem.duplex = "split"
            mem.offset = int(memobj.freq_tx)
            mem.immutable = []
        elif hasattr(memobj, "duplexOffset"):
            mem.offset = int(memobj.duplexOffset) * 100
        else:
            mem.immutable = ["offset"]

        try:
            dig = RadioSetting("dig", "Digital",
                               RadioSettingValueBoolean(bool(memobj.dig)))
        except AttributeError:
            pass
        else:
            dig.set_doc("Enable digital mode")
            if not mem.extra:
                mem.extra = RadioSettingGroup("extra", "Extra")
            mem.extra.append(dig)

        if not self._unified_modes:
            options = ["Wide", "Mid", "Narrow"]
            try:
                fil = RadioSetting(
                    "filter", "Filter",
                    RadioSettingValueList(options,
                                          current_index=memobj.filter - 1))
            except AttributeError:
                pass
            else:
                fil.set_doc("Filter settings")
                if not mem.extra:
                    mem.extra = RadioSettingGroup("extra", "Extra")
                mem.extra.append(fil)

        return mem

    def set_memory(self, mem):
        self._detect_baudrate()
        LOG.debug("Setting %s(%s)" % (mem.number, mem.extd_number))
        f = self._get_template_memory()
        if self._is_special(mem.number):
            info = self._get_special_info(mem.number)
            LOG.debug("Special info: %s" % info)
            ch = info.channel
            if self._rf.has_bank:
                bnk = info.bank
        elif self._rf.has_bank:
            ch, bnk = self.mem_to_ch_bnk(mem.number)
            LOG.debug("Bank %i, Channel %02i" % (bnk, ch))
        else:
            ch = mem.number
        if mem.empty:
            if self._rf.has_bank:
                f.set_location(ch, bnk)
            else:
                f.set_location(ch)
            LOG.debug("Making %i empty" % mem.number)
            f.make_empty()
            self._send_frame(f)

# The next two lines accept the radio's status after setting the memory
# and reports the results to the debug log.  This is needed for the
# IC-7000.  No testing was done to see if it breaks memory delete on the
# IC-746 or IC-7200.
            f = self._recv_frame()
            LOG.debug("Result:\n%s" % util.hexprint(bytes(f.get_data())))
            return

        # f.set_data(MemoryMap(self.get_raw_memory(mem.number)))
        # f.initialize()

        memobj = f.get_obj()
        if self._rf.has_bank:
            memobj.bank = bnk
            memobj.number = ch
        else:
            memobj.number = ch
        if mem.skip == "S":
            memobj.skip = 0
        else:
            try:
                memobj.skip = 1
            except KeyError:
                pass
        memobj.freq = int(mem.freq)
        mode = mem.mode
        if self._unified_modes:
            lookup = [
                k for k, v in self._UNIFIED_MODES.items() if v == mode]
            if lookup:
                mode = lookup[0]
                memobj.filter = 2
            else:
                memobj.filter = 1
        memobj.mode = self._MODES.index(mode)
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
            if hasattr(memobj, "duplex"):
                memobj.duplex = 0
            memobj.freq_tx = int(mem.offset)
            memobj.tmode_tx = memobj.tmode
            memobj.ctone_tx = memobj.ctone
            memobj.rtone_tx = memobj.rtone
            if self._rf.has_dtcs:
                memobj.dtcs_polarity_tx = memobj.dtcs_polarity
                memobj.dtcs_tx = memobj.dtcs
        elif self._rf.valid_duplexes:
            memobj.duplex = self._rf.valid_duplexes.index(mem.duplex)
            if hasattr(memobj, "duplexOffset"):
                memobj.duplexOffset = int(mem.offset) // 100

        for setting in mem.extra:
            if setting.get_name() == "filter":
                setattr(memobj, setting.get_name(), int(setting.value) + 1)
            else:
                setattr(memobj, setting.get_name(), setting.value)

        LOG.debug(repr(memobj))
        self._send_frame(f)

        f = self._recv_frame()
        LOG.debug("Result:\n%s" % util.hexprint(bytes(f.get_data())))


@directory.register
class Icom7200Radio(IcomCIVRadio):
    """Icom IC-7200"""
    MODEL = "IC-7200"
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
    MODEL = "IC-746"
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


@directory.register
class Icom7400Radio(IcomCIVRadio):
    """Icom IC-7400"""
    MODEL = "IC-7400"
    BAUD_RATE = 9600
    _model = "\x66"
    _template = 102

    _num_banks = 1		# Banks not supported

    def _initialize(self):
        self._classes["mem"] = IC7400MemFrame
        self._rf.has_bank = False
        self._rf.has_dtcs_polarity = True
        self._rf.has_dtcs = True
        self._rf.has_ctone = True
        self._rf.has_offset = False
        self._rf.has_name = True
        self._rf.has_tuning_step = False
        self._rf.valid_modes = [
            "LSB", "USB", "AM", "CW", "RTTY", "FM", "USB", "CWR", "RTTYR"
        ]
        self._rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        self._rf.valid_duplexes = ["", "-", "+"]
        self._rf.valid_bands = [(30000, 174000000)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = []
        self._rf.valid_name_length = 8
        self._rf.valid_characters = " !#$%&'()*+,-./" \
            "0123456789" \
            ":;<=>?" \
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ" \
            "[\\]^_" \
            "abcdefghijklmnopqrstuvwxyz" \
            "{|}~"
        self._rf.memory_bounds = (1, 99)


@directory.register
class Icom910Radio(IcomCIVRadio):
    """Icom IC-910"""
    MODEL = "IC-910"
    BAUD_RATE = 19200
    _model = "\x60"
    _template = 100

    _num_banks = 3		# Banks for 2m, 70cm, 23cm
    _bank_index_bounds = (1, 99)
    _bank_class = icf.IcomBank

    _SPECIAL_CHANNELS = {
        "1A": 100,
        "1b": 101,
        "2A": 102,
        "2b": 103,
        "3A": 104,
        "3b": 105,
        "C":  106,
    }
    _SPECIAL_CHANNELS_REV = {v: k for k, v in _SPECIAL_CHANNELS.items()}

    _SPECIAL_BANKS = {
        "2m":   1,
        "70cm": 2,
        "23cm": 3,
    }
    _SPECIAL_BANKS_REV = {v: k for k, v in _SPECIAL_BANKS.items()}

    def _get_special_names(self, band):
        return sorted([band + "-" + key
                       for key in self._SPECIAL_CHANNELS.keys()])

    def _is_special(self, number):
        return isinstance(number, str) or number >= 1000

    def _get_special_info(self, number):
        info = BankSpecialChannel()
        if isinstance(number, str):
            info.name = number
            (band_name, chan_name) = number.split("-")
            info.bank = self._SPECIAL_BANKS[band_name]
            info.channel = self._SPECIAL_CHANNELS[chan_name]
            info.location = info.bank * 1000 + info.channel
        else:
            info.location = number
            (info.bank, info.channel) = divmod(number, 1000)
            band_name = self._SPECIAL_BANKS_REV[info.bank]
            chan_name = self._SPECIAL_CHANNELS_REV[info.channel]
            info.name = band_name + "-" + chan_name
        return info

    # The IC-910 has a bank of memories for each band. The 23cm band is only
    # available when the optional UX-910 unit is installed, but there is no
    # direct means of detecting its presence. Instead, attempt to access the
    # first memory in the 23cm bank. If that's successful, the unit is there,
    # and we can present all 3 banks to the user. Otherwise, the unit is not
    # installed, so we present 2 banks to the user, for 2m and 70cm.
    def _detect_23cm_unit(self):
        if not self.pipe:
            return True
        self._detect_baudrate()
        f = IC910MemFrame()
        f.set_location(1, 3)  # First memory in 23cm bank
        self._send_frame(f)
        f.read(self.pipe)
        if f._cmd == 0xFA:  # Error code lands in command field
            self._num_banks = 2
        LOG.debug("UX-910 unit is %sinstalled" %
                  ("not " if self._num_banks == 2 else ""))
        return self._num_banks == 3

    def _initialize(self):
        self._classes["mem"] = IC910MemFrame
        self._has_23cm_unit = self._detect_23cm_unit()
        self._rf.has_bank = True
        self._rf.has_dtcs_polarity = False
        self._rf.has_dtcs = False
        self._rf.has_ctone = True
        self._rf.has_offset = True
        self._rf.has_name = False
        self._rf.has_tuning_step = False
        self._rf.valid_modes = ["LSB", "USB", "CW", "NCW", "FM", "NFM"]
        self._rf.valid_tmodes = ["", "Tone", "TSQL"]
        self._rf.valid_duplexes = ["", "-", "+"]
        self._rf.valid_bands = [(136000000, 174000000),
                                (420000000, 480000000)]
        self._rf.valid_tuning_steps = []
        self._rf.valid_skips = []
        self._rf.valid_special_chans = (self._get_special_names("2m") +
                                        self._get_special_names("70cm"))
        self._rf.memory_bounds = (1, 99 * self._num_banks)

        if self._has_23cm_unit:
            self._rf.valid_bands.append((1240000000, 1320000000))
            self._rf.valid_special_chans += self._get_special_names("23cm")

        # Combine mode and filter into unified mode
        self._unified_modes = True

        # Use Chirp locations starting with 1
        self._adjust_bank_loc_start = True


@directory.register
class Icom7300Radio(IcomCIVRadio):      # Added March, 2021 by Rick DeWitt
    """Icom IC-7300"""
    MODEL = "IC-7300"
    BAUD_RATE = 115200
    _model = "\x94"
    _template = 100              # Use P1 as blank template

    _SPECIAL_CHANNELS = {
        "P1": 100,
        "P2": 101,
    }
    _SPECIAL_CHANNELS_REV = dict(zip(_SPECIAL_CHANNELS.values(),
                                     _SPECIAL_CHANNELS.keys()))

    def _is_special(self, number):
        return isinstance(number, str) or number > 99

    def _get_special_info(self, number):
        info = SpecialChannel()
        if isinstance(number, str):
            info.name = number
            info.channel = self._SPECIAL_CHANNELS[number]
            info.location = info.channel
        else:
            info.location = number
            info.name = self._SPECIAL_CHANNELS_REV[number]
            info.channel = info.location
        return info

    def _initialize(self):
        self._classes["mem"] = IC7300MemFrame
        self._rf.has_name = True
        self._rf.has_dtcs = False
        self._rf.has_dtcs_polarity = False
        self._rf.has_bank = False
        self._rf.has_tuning_step = False
        self._rf.has_nostep_tuning = True
        self._rf.can_odd_split = True
        self._rf.memory_bounds = (1, 99)
        self._rf.valid_modes = [
            "LSB", "USB", "AM", "CW", "RTTY", "FM", "CWR", "RTTYR",
            "Data+LSB", "Data+USB", "Data+AM", "N/A", "N/A", "Data+FM"
        ]
        self._rf.valid_tmodes = ["", "Tone", "TSQL"]
        # self._rf.valid_duplexes = ["", "-", "+", "split"]
        self._rf.valid_duplexes = []     # To prevent using memobj.duplex
        self._rf.valid_bands = [(30000, 74800000)]
        self._rf.valid_skips = []
        self._rf.valid_name_length = 10
        self._rf.valid_characters = chirp_common.CHARSET_ASCII
        self._rf.valid_special_chans = sorted(self._SPECIAL_CHANNELS.keys())


@directory.register
class Icom7610Radio(Icom7300Radio):
    MODEL = "IC-7610"
    _model = '\x98'

    def _initialize(self):
        super()._initialize()
        self._classes['mem'] = IC7610MemFrame


@directory.register
class Icom9700Radio(IcomCIVRadio):
    MODEL = 'IC-9700'
    _model = '\xA2'
    _template = 100
    BANDS = {
        1: (144, 148),
        2: (430, 450),
        3: (1240, 1300),
    }
    _MODES = [
        "LSB", "USB", "AM", "CW", "RTTY", "FM", "CWR",
        "RTTY-R", None, None, None, None, None, None, None, None, None,
        "DV", None, None, None, None, "DD", None, None, None, None, None,
    ]

    def get_sub_devices(self):
        return [Icom9700RadioBand(self, 1),
                Icom9700RadioBand(self, 2),
                Icom9700RadioBand(self, 3),
                Icom9700SatelliteBand(self)]

    def _initialize(self):
        super()._initialize()
        self._rf.has_sub_devices = True
        self._rf.memory_bounds = (1, 99)
        self._classes['mem'] = IC9700MemFrame


class Icom9700RadioBand(Icom9700Radio):
    _SPECIAL_CHANNELS = {
        "1A": 100,
        "1B": 101,
        "2A": 102,
        "2B": 103,
        "3A": 104,
        "4B": 105,
        "C1": 106,
        "C2": 107,
    }
    _SPECIAL_CHANNELS_REV = dict(zip(_SPECIAL_CHANNELS.values(),
                                     _SPECIAL_CHANNELS.keys()))

    def _detect_echo(self):
        self._parent._willecho

    def _is_special(self, number):
        return isinstance(number, str) or number > 99

    def _get_special_info(self, number):
        info = BankSpecialChannel()
        info.bank = self._band
        if isinstance(number, str):
            info.name = number
            info.channel = self._SPECIAL_CHANNELS[number]
            info.location = info.channel
        else:
            info.location = number
            info.name = self._SPECIAL_CHANNELS_REV[number]
            info.channel = info.location
        return info

    def __init__(self, parent, band):
        self._parent = parent
        self._band = band
        self.VARIANT = '%i band' % (self.BANDS[band][0])
        super().__init__(parent.pipe)

    def mem_to_ch_bnk(self, mem):
        return mem, self._band

    def _initialize(self):
        super()._initialize()
        self._rf.has_name = True
        self._rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS']
        self._rf.has_dtcs = True
        self._rf.has_dtcs_polarity = True
        self._rf.has_bank = True
        self._rf.has_tuning_step = False
        self._rf.has_nostep_tuning = True
        self._rf.can_odd_split = False
        self._rf.memory_bounds = (1, 99)
        self._rf.valid_bands = [(x * 1000000, y * 1000000) for x, y in
                                [self.BANDS[self._band]]]
        self._rf.valid_name_length = 16
        self._rf.valid_characters = (chirp_common.CHARSET_ALPHANUMERIC +
                                     '!#$%&\\?"\'`^+-*/.,:=<>()[]{}|_~@')
        self._rf.valid_special_chans = sorted(self._SPECIAL_CHANNELS.keys())
        # Last item is RPS for DD mode
        self._rf.valid_duplexes = ['', '-', '+']
        self._rf.valid_modes = [x for x in self._MODES if x]
        if self._band != 3:
            self._rf.valid_modes.remove('DD')
        self._classes['mem'] = IC9700MemFrame


class Icom9700SatelliteBand(Icom9700Radio):
    VARIANT = 'Satellite'

    def __init__(self, parent):
        self._parent = parent
        super().__init__(parent.pipe)

    def _detect_echo(self):
        self._parent._willecho

    def _initialize(self):
        super()._initialize()
        self._rf.has_name = True
        self._rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS']
        self._rf.has_dtcs = True
        self._rf.has_dtcs_polarity = True
        self._rf.has_bank = False
        self._rf.has_tuning_step = False
        self._rf.has_nostep_tuning = True
        self._rf.can_odd_split = True
        self._rf.memory_bounds = (1, 99)
        self._rf.valid_bands = [(x * 1000000, y * 1000000) for x, y in
                                self.BANDS.values()]
        self._rf.valid_name_length = 16
        self._rf.valid_characters = (chirp_common.CHARSET_ALPHANUMERIC +
                                     '!#$%&\\?"\'`^+-*/.,:=<>()[]{}|_~@')
        # Last item is RPS for DD mode
        self._rf.valid_duplexes = ['split']
        self._rf.valid_modes = [x for x in self._MODES if x]
        self._rf.valid_modes.remove('DD')
        self._classes['mem'] = IC9700SatMemFrame

    def _get_template_memory(self):
        f = self._classes["mem"]()
        f.initialize()
        return f

    def get_memory(self, number):
        self._detect_baudrate()
        LOG.debug("Getting %s" % number)
        f = self._classes["mem"]()
        mem = chirp_common.Memory()
        f.set_location(number)
        mem.number = number
        self._send_frame(f)

        f = self._recv_frame(f)
        if len(f.get_data()) == 0:
            raise errors.RadioError("Radio reported error")
        if f.get_data() and f.get_data()[-1] == 0xFF:
            mem.empty = True
            mem.duplex = 'split'
            LOG.debug("Found %i empty" % mem.number)
            return mem

        memobj = f.get_obj()
        LOG.debug(repr(memobj))

        mem.freq = int(memobj.freq)
        mem.mode = self._MODES[int(memobj.mode)]
        mem.name = str(memobj.name).rstrip()
        mem.tmode = self._rf.valid_tmodes[memobj.tmode]

        if memobj.dtcs_polarity == 0x11:
            mem.dtcs_polarity = "RR"
        elif memobj.dtcs_polarity == 0x10:
            mem.dtcs_polarity = "RN"
        elif memobj.dtcs_polarity == 0x01:
            mem.dtcs_polarity = "NR"
        else:
            mem.dtcs_polarity = "NN"

        mem.dtcs = bitwise.bcd_to_int(memobj.dtcs)
        mem.rtone = int(memobj.rtone) / 10.0
        mem.ctone = int(memobj.ctone) / 10.0
        mem.duplex = 'split'
        mem.offset = int(memobj.tx.freq)
        mem.immutable = ["duplex"]

        try:
            dig = RadioSetting("dig", "Digital",
                               RadioSettingValueBoolean(bool(memobj.dig)))
        except AttributeError:
            pass
        else:
            dig.set_doc("Enable digital mode")
            if not mem.extra:
                mem.extra = RadioSettingGroup("extra", "Extra")
            mem.extra.append(dig)

        options = ["Wide", "Mid", "Narrow"]
        fil = RadioSetting(
            "filter", "Filter",
            RadioSettingValueList(options,
                                  current_index=memobj.filter - 1))
        fil.set_doc("Filter settings")
        if not mem.extra:
            mem.extra = RadioSettingGroup("extra", "Extra")
        mem.extra.append(fil)

        return mem

    def set_memory(self, mem):
        self._detect_baudrate()
        LOG.debug("Setting %s(%s)" % (mem.number, mem.extd_number))
        f = self._get_template_memory()
        ch = mem.number
        if mem.empty:
            LOG.debug("Making %i empty" % mem.number)
            f.set_location(ch)
            f.make_empty()
            self._send_frame(f)
            f = self._recv_frame()
            LOG.debug("Result (%r):\n%s",
                      f._cmd, util.hexprint(bytes(f.get_data())))
            return

        memobj = f.get_obj()
        memobj.number = ch
        memobj.freq = int(mem.freq)
        mode = mem.mode
        memobj.mode = self._MODES.index(mode)
        name_length = len(memobj.name.get_value())
        memobj.name = mem.name.ljust(name_length)[:name_length]
        memobj.tmode = self._rf.valid_tmodes.index(mem.tmode)
        memobj.ctone = int(mem.ctone * 10)
        memobj.rtone = int(mem.rtone * 10)

        if mem.dtcs_polarity == "RR":
            memobj.dtcs_polarity = 0x11
        elif mem.dtcs_polarity == "RN":
            memobj.dtcs_polarity = 0x10
        elif mem.dtcs_polarity == "NR":
            memobj.dtcs_polarity = 0x01
        else:
            memobj.dtcs_polarity = 0x00

        bitwise.int_to_bcd(memobj.dtcs, mem.dtcs)

        memobj.tx.freq = int(mem.offset)
        memobj.tx.tmode = memobj.tmode
        memobj.tx.ctone = memobj.ctone
        memobj.tx.rtone = memobj.rtone
        memobj.tx.dtcs_polarity = memobj.dtcs_polarity
        memobj.tx.dtcs = memobj.dtcs

        memobj.urcall = memobj.rpt1call = memobj.rpt2call = ' ' * 8
        memobj.tx.urcall = memobj.tx.rpt1call = memobj.tx.rpt2call = ' ' * 8
        memobj.filter = memobj.tx.filter = 1

        for setting in mem.extra:
            if setting.get_name() == "filter":
                setattr(memobj, setting.get_name(), int(setting.value) + 1)
            else:
                setattr(memobj, setting.get_name(), setting.value)

        LOG.debug(repr(memobj))
        self._send_frame(f)

        f = self._recv_frame()
        LOG.debug("Result (%r):\n%s",
                  f._cmd, util.hexprint(bytes(f.get_data())))
        if f._cmd == 0xFA:
            LOG.error('Radio refused memory')


def probe_model(ser):
    """Probe the radio attached to @ser for its model"""
    f = Frame()
    f.set_command(0x19, 0x00)

    models = {}
    for rclass in directory.DRV_TO_RADIO.values():
        if issubclass(rclass, IcomCIVRadio):
            models[rclass.MODEL] = rclass

    for rclass in models.values():
        model = ord(rclass._model)
        f.send(model, 0xE0, ser)
        try:
            f.read(ser)
        except errors.RadioError:
            continue

        if len(f.get_data()) == 1:
            md = f.get_data()[0]
            if (md == model):
                return rclass

        if f.get_data():
            LOG.debug("Got data, but not 1 byte:")
            LOG.debug(util.hexprint(bytes(f.get_data())))
            raise errors.RadioError("Unknown response")

    raise errors.RadioError("Unsupported model")
