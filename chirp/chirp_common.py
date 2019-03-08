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

import base64
import json
import logging
import math
import sys
from chirp import errors, memmap, CHIRP_VERSION

LOG = logging.getLogger(__name__)

SEPCHAR = ","

# 50 Tones
TONES = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5,
         85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5,
         107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
         131.8, 136.5, 141.3, 146.2, 151.4, 156.7,
         159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
         177.3, 179.9, 183.5, 186.2, 189.9, 192.8,
         196.6, 199.5, 203.5, 206.5, 210.7, 218.1,
         225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
         ]

TONES_EXTRA = [56.0, 57.0, 58.0, 59.0, 60.0, 61.0, 62.0,
               62.5, 63.0, 64.0]

OLD_TONES = list(TONES)
[OLD_TONES.remove(x) for x in [159.8, 165.5, 171.3, 177.3, 183.5, 189.9,
                               196.6, 199.5, 206.5, 229.1, 254.1]]

# 104 DTCS Codes
DTCS_CODES = [
    23,  25,  26,  31,  32,  36,  43,  47,  51,  53,  54,
    65,  71,  72,  73,  74,  114, 115, 116, 122, 125, 131,
    132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174,
    205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
    255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325,
    331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412,
    413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464,
    465, 466, 503, 506, 516, 523, 526, 532, 546, 565, 606,
    612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723,
    731, 732, 734, 743, 754,
]

# 512 Possible DTCS Codes
ALL_DTCS_CODES = []
for a in range(0, 8):
    for b in range(0, 8):
        for c in range(0, 8):
            ALL_DTCS_CODES.append((a * 100) + (b * 10) + c)

CROSS_MODES = [
    "Tone->Tone",
    "DTCS->",
    "->DTCS",
    "Tone->DTCS",
    "DTCS->Tone",
    "->Tone",
    "DTCS->DTCS",
    "Tone->"
]

MODES = ["WFM", "FM", "NFM", "AM", "NAM", "DV", "USB", "LSB", "CW", "RTTY",
         "DIG", "PKT", "NCW", "NCWR", "CWR", "P25", "Auto", "RTTYR",
         "FSK", "FSKR", "DMR"]

TONE_MODES = [
    "",
    "Tone",
    "TSQL",
    "DTCS",
    "DTCS-R",
    "TSQL-R",
    "Cross",
]

TUNING_STEPS = [
    5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0,
    125.0, 200.0,
    # Need to fix drivers using this list as an index!
    9.0, 1.0, 2.5,
]
# These are the default for RadioFeatures.valid_tuning_steps
COMMON_TUNING_STEPS = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]


SKIP_VALUES = ["", "S", "P"]

CHARSET_UPPER_NUMERIC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ 1234567890"
CHARSET_ALPHANUMERIC = \
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz 1234567890"
CHARSET_ASCII = "".join([chr(x) for x in range(ord(" "), ord("~") + 1)])

# http://aprs.org/aprs11/SSIDs.txt
APRS_SSID = (
    "0 Your primary station usually fixed and message capable",
    "1 generic additional station, digi, mobile, wx, etc",
    "2 generic additional station, digi, mobile, wx, etc",
    "3 generic additional station, digi, mobile, wx, etc",
    "4 generic additional station, digi, mobile, wx, etc",
    "5 Other networks (Dstar, Iphones, Androids, Blackberry's etc)",
    "6 Special activity, Satellite ops, camping or 6 meters, etc",
    "7 walkie talkies, HT's or other human portable",
    "8 boats, sailboats, RV's or second main mobile",
    "9 Primary Mobile (usually message capable)",
    "10 internet, Igates, echolink, winlink, AVRS, APRN, etc",
    "11 balloons, aircraft, spacecraft, etc",
    "12 APRStt, DTMF, RFID, devices, one-way trackers*, etc",
    "13 Weather stations",
    "14 Truckers or generally full time drivers",
    "15 generic additional station, digi, mobile, wx, etc")
APRS_POSITION_COMMENT = (
    "off duty", "en route", "in service", "returning", "committed",
    "special", "priority", "custom 0", "custom 1", "custom 2", "custom 3",
    "custom 4", "custom 5", "custom 6", "EMERGENCY")
# http://aprs.org/symbols/symbolsX.txt
APRS_SYMBOLS = (
    "Police/Sheriff", "[reserved]", "Digi", "Phone", "DX Cluster",
    "HF Gateway", "Small Aircraft", "Mobile Satellite Groundstation",
    "Wheelchair", "Snowmobile", "Red Cross", "Boy Scouts", "House QTH (VHF)",
    "X", "Red Dot", "0 in Circle", "1 in Circle", "2 in Circle",
    "3 in Circle", "4 in Circle", "5 in Circle", "6 in Circle", "7 in Circle",
    "8 in Circle", "9 in Circle", "Fire", "Campground", "Motorcycle",
    "Railroad Engine", "Car", "File Server", "Hurricane Future Prediction",
    "Aid Station", "BBS or PBBS", "Canoe", "[reserved]", "Eyeball",
    "Tractor/Farm Vehicle", "Grid Square", "Hotel", "TCP/IP", "[reserved]",
    "School", "PC User", "MacAPRS", "NTS Station", "Balloon", "Police", "TBD",
    "Recreational Vehicle", "Space Shuttle", "SSTV", "Bus", "ATV",
    "National WX Service Site", "Helicopter", "Yacht/Sail Boat", "WinAPRS",
    "Human/Person", "Triangle", "Mail/Postoffice", "Large Aircraft",
    "WX Station", "Dish Antenna", "Ambulance", "Bicycle",
    "Incident Command Post", "Dual Garage/Fire Dept", "Horse/Equestrian",
    "Fire Truck", "Glider", "Hospital", "IOTA", "Jeep", "Truck", "Laptop",
    "Mic-Repeater", "Node", "Emergency Operations Center", "Rover (dog)",
    "Grid Square above 128m", "Repeater", "Ship/Power Boat", "Truck Stop",
    "Truck (18 wheeler)", "Van", "Water Station", "X-APRS", "Yagi at QTH",
    "TDB", "[reserved]"
)


def watts_to_dBm(watts):
    """Converts @watts in watts to dBm"""
    return int(10 * math.log10(int(watts * 1000)))


def dBm_to_watts(dBm):
    """Converts @dBm from dBm to watts"""
    return int(math.pow(10, (dBm - 30) / 10))


class PowerLevel:
    """Represents a power level supported by a radio"""

    def __init__(self, label, watts=0, dBm=0):
        if watts:
            dBm = watts_to_dBm(watts)
        self._power = int(dBm)
        self._label = label

    def __str__(self):
        return str(self._label)

    def __int__(self):
        return self._power

    def __sub__(self, val):
        return int(self) - int(val)

    def __add__(self, val):
        return int(self) + int(val)

    def __eq__(self, val):
        if val is not None:
            return int(self) == int(val)
        return False

    def __lt__(self, val):
        return int(self) < int(val)

    def __gt__(self, val):
        return int(self) > int(val)

    def __nonzero__(self):
        return int(self) != 0

    def __repr__(self):
        return "%s (%i dBm)" % (self._label, self._power)


def parse_freq(freqstr):
    """Parse a frequency string and return the value in integral Hz"""
    freqstr = freqstr.strip()
    if freqstr == "":
        return 0
    elif freqstr.endswith(" MHz"):
        return parse_freq(freqstr.split(" ")[0])
    elif freqstr.endswith(" kHz"):
        return int(freqstr.split(" ")[0]) * 1000

    if "." in freqstr:
        mhz, khz = freqstr.split(".")
        if mhz == "":
            mhz = 0
        khz = khz.ljust(6, "0")
        if len(khz) > 6:
            raise ValueError("Invalid kHz value: %s", khz)
        mhz = int(mhz) * 1000000
        khz = int(khz)
    else:
        mhz = int(freqstr) * 1000000
        khz = 0

    return mhz + khz


def format_freq(freq):
    """Format a frequency given in Hz as a string"""

    return "%i.%06i" % (freq / 1000000, freq % 1000000)


class ImmutableValueError(ValueError):
    pass


class Memory:
    """Base class for a single radio memory"""
    freq = 0
    number = 0
    extd_number = ""
    name = ""
    vfo = 0
    rtone = 88.5
    ctone = 88.5
    dtcs = 23
    rx_dtcs = 23
    tmode = ""
    cross_mode = "Tone->Tone"
    dtcs_polarity = "NN"
    skip = ""
    power = None
    duplex = ""
    offset = 600000
    mode = "FM"
    tuning_step = 5.0

    comment = ""

    empty = False

    immutable = []

    # A RadioSettingGroup of additional settings supported by the radio,
    # or an empty list if none
    extra = []

    def __init__(self):
        self.freq = 0
        self.number = 0
        self.extd_number = ""
        self.name = ""
        self.vfo = 0
        self.rtone = 88.5
        self.ctone = 88.5
        self.dtcs = 23
        self.rx_dtcs = 23
        self.tmode = ""
        self.cross_mode = "Tone->Tone"
        self.dtcs_polarity = "NN"
        self.skip = ""
        self.power = None
        self.duplex = ""
        self.offset = 600000
        self.mode = "FM"
        self.tuning_step = 5.0

        self.comment = ""

        self.empty = False

        self.immutable = []

    _valid_map = {
        "rtone":          TONES + TONES_EXTRA,
        "ctone":          TONES + TONES_EXTRA,
        "dtcs":           ALL_DTCS_CODES,
        "rx_dtcs":        ALL_DTCS_CODES,
        "tmode":          TONE_MODES,
        "dtcs_polarity":  ["NN", "NR", "RN", "RR"],
        "cross_mode":     CROSS_MODES,
        "mode":           MODES,
        "duplex":         ["", "+", "-", "split", "off"],
        "skip":           SKIP_VALUES,
        "empty":          [True, False],
        "dv_code":        [x for x in range(0, 100)],
    }

    def __repr__(self):
        return "Memory[%i]" % self.number

    def dupe(self):
        """Return a deep copy of @self"""
        mem = self.__class__()
        for k, v in self.__dict__.items():
            mem.__dict__[k] = v

        return mem

    def clone(self, source):
        """Absorb all of the properties of @source"""
        for k, v in source.__dict__.items():
            self.__dict__[k] = v

    CSV_FORMAT = ["Location", "Name", "Frequency",
                  "Duplex", "Offset", "Tone",
                  "rToneFreq", "cToneFreq", "DtcsCode",
                  "DtcsPolarity", "Mode", "TStep",
                  "Skip", "Comment",
                  "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE"]

    def __setattr__(self, name, val):
        if not hasattr(self, name):
            raise ValueError("No such attribute `%s'" % name)

        if name in self.immutable:
            raise ImmutableValueError("Field %s is not " % name +
                                      "mutable on this memory")

        if name in self._valid_map and val not in self._valid_map[name]:
            raise ValueError("`%s' is not in valid list: %s" %
                             (val, self._valid_map[name]))

        self.__dict__[name] = val

    def format_freq(self):
        """Return a properly-formatted string of this memory's frequency"""
        return format_freq(self.freq)

    def parse_freq(self, freqstr):
        """Set the frequency from a string"""
        self.freq = parse_freq(freqstr)
        return self.freq

    def __str__(self):
        if self.tmode == "Tone":
            tenc = "*"
        else:
            tenc = " "

        if self.tmode == "TSQL":
            tsql = "*"
        else:
            tsql = " "

        if self.tmode == "DTCS":
            dtcs = "*"
        else:
            dtcs = " "

        if self.duplex == "":
            dup = "/"
        else:
            dup = self.duplex

        return \
            "Memory %s: %s%s%s %s (%s) r%.1f%s c%.1f%s d%03i%s%s [%.2f]" % \
            (self.number if self.extd_number == "" else self.extd_number,
             format_freq(self.freq),
             dup,
             format_freq(self.offset),
             self.mode,
             self.name,
             self.rtone,
             tenc,
             self.ctone,
             tsql,
             self.dtcs,
             dtcs,
             self.dtcs_polarity,
             self.tuning_step)

    def to_csv(self):
        """Return a CSV representation of this memory"""
        return [
            "%i" % self.number,
            "%s" % self.name,
            format_freq(self.freq),
            "%s" % self.duplex,
            format_freq(self.offset),
            "%s" % self.tmode,
            "%.1f" % self.rtone,
            "%.1f" % self.ctone,
            "%03i" % self.dtcs,
            "%s" % self.dtcs_polarity,
            "%s" % self.mode,
            "%.2f" % self.tuning_step,
            "%s" % self.skip,
            "%s" % self.comment,
            "", "", "", ""]

    @classmethod
    def _from_csv(cls, _line):
        line = _line.strip()
        if line.startswith("Location"):
            raise errors.InvalidMemoryLocation("Non-CSV line")

        vals = line.split(SEPCHAR)
        if len(vals) < 11:
            raise errors.InvalidDataError("CSV format error " +
                                          "(14 columns expected)")

        if vals[10] == "DV":
            mem = DVMemory()
        else:
            mem = Memory()

        mem.really_from_csv(vals)
        return mem

    def really_from_csv(self, vals):
        """Careful parsing of split-out @vals"""
        try:
            self.number = int(vals[0])
        except:
            raise errors.InvalidDataError(
                "Location '%s' is not a valid integer" % vals[0])

        self.name = vals[1]

        try:
            self.freq = float(vals[2])
        except:
            raise errors.InvalidDataError("Frequency is not a valid number")

        if vals[3].strip() in ["+", "-", ""]:
            self.duplex = vals[3].strip()
        else:
            raise errors.InvalidDataError("Duplex is not +,-, or empty")

        try:
            self.offset = float(vals[4])
        except:
            raise errors.InvalidDataError("Offset is not a valid number")

        self.tmode = vals[5]
        if self.tmode not in TONE_MODES:
            raise errors.InvalidDataError("Invalid tone mode `%s'" %
                                          self.tmode)

        try:
            self.rtone = float(vals[6])
        except:
            raise errors.InvalidDataError("rTone is not a valid number")
        if self.rtone not in TONES:
            raise errors.InvalidDataError("rTone is not valid")

        try:
            self.ctone = float(vals[7])
        except:
            raise errors.InvalidDataError("cTone is not a valid number")
        if self.ctone not in TONES:
            raise errors.InvalidDataError("cTone is not valid")

        try:
            self.dtcs = int(vals[8], 10)
        except:
            raise errors.InvalidDataError("DTCS code is not a valid number")
        if self.dtcs not in DTCS_CODES:
            raise errors.InvalidDataError("DTCS code is not valid")

        try:
            self.rx_dtcs = int(vals[8], 10)
        except:
            raise errors.InvalidDataError("DTCS Rx code is not a valid number")
        if self.rx_dtcs not in DTCS_CODES:
            raise errors.InvalidDataError("DTCS Rx code is not valid")

        if vals[9] in ["NN", "NR", "RN", "RR"]:
            self.dtcs_polarity = vals[9]
        else:
            raise errors.InvalidDataError("DtcsPolarity is not valid")

        if vals[10] in MODES:
            self.mode = vals[10]
        else:
            raise errors.InvalidDataError("Mode is not valid")

        try:
            self.tuning_step = float(vals[11])
        except:
            raise errors.InvalidDataError("Tuning step is invalid")

        try:
            self.skip = vals[12]
        except:
            raise errors.InvalidDataError("Skip value is not valid")

        return True


class DVMemory(Memory):
    """A Memory with D-STAR attributes"""
    dv_urcall = "CQCQCQ"
    dv_rpt1call = ""
    dv_rpt2call = ""
    dv_code = 0

    def __str__(self):
        string = Memory.__str__(self)

        string += " <%s,%s,%s>" % (self.dv_urcall,
                                   self.dv_rpt1call,
                                   self.dv_rpt2call)

        return string

    def to_csv(self):
        return [
            "%i" % self.number,
            "%s" % self.name,
            format_freq(self.freq),
            "%s" % self.duplex,
            format_freq(self.offset),
            "%s" % self.tmode,
            "%.1f" % self.rtone,
            "%.1f" % self.ctone,
            "%03i" % self.dtcs,
            "%s" % self.dtcs_polarity,
            "%s" % self.mode,
            "%.2f" % self.tuning_step,
            "%s" % self.skip,
            "%s" % self.comment,
            "%s" % self.dv_urcall,
            "%s" % self.dv_rpt1call,
            "%s" % self.dv_rpt2call,
            "%i" % self.dv_code]

    def really_from_csv(self, vals):
        Memory.really_from_csv(self, vals)

        self.dv_urcall = vals[15].rstrip()[:8]
        self.dv_rpt1call = vals[16].rstrip()[:8]
        self.dv_rpt2call = vals[17].rstrip()[:8]
        try:
            self.dv_code = int(vals[18].strip())
        except Exception:
            self.dv_code = 0


class MemoryMapping(object):
    """Base class for a memory mapping"""

    def __init__(self, model, index, name):
        self._model = model
        self._index = index
        self._name = name

    def __str__(self):
        return self.get_name()

    def __repr__(self):
        return "%s-%s" % (self.__class__.__name__, self._index)

    def get_name(self):
        """Returns the mapping name"""
        return self._name

    def get_index(self):
        """Returns the immutable index (string or int)"""
        return self._index

    def __eq__(self, other):
        return self.get_index() == other.get_index()


class MappingModel(object):
    """Base class for a memory mapping model"""

    def __init__(self, radio, name):
        self._radio = radio
        self._name = name

    def get_name(self):
        return self._name

    def get_num_mappings(self):
        """Returns the number of mappings in the model (should be
        callable without consulting the radio"""
        raise NotImplementedError()

    def get_mappings(self):
        """Return a list of mappings"""
        raise NotImplementedError()

    def add_memory_to_mapping(self, memory, mapping):
        """Add @memory to @mapping."""
        raise NotImplementedError()

    def remove_memory_from_mapping(self, memory, mapping):
        """Remove @memory from @mapping.
        Shall raise exception if @memory is not in @bank"""
        raise NotImplementedError()

    def get_mapping_memories(self, mapping):
        """Return a list of memories in @mapping"""
        raise NotImplementedError()

    def get_memory_mappings(self, memory):
        """Return a list of mappings that @memory is in"""
        raise NotImplementedError()


class Bank(MemoryMapping):
    """Base class for a radio's Bank"""


class NamedBank(Bank):
    """A bank that can have a name"""

    def set_name(self, name):
        """Changes the user-adjustable bank name"""
        self._name = name


class BankModel(MappingModel):
    """A bank model where one memory is in zero or one banks at any point"""

    def __init__(self, radio, name='Banks'):
        super(BankModel, self).__init__(radio, name)


class MappingModelIndexInterface:
    """Interface for mappings with index capabilities"""

    def get_index_bounds(self):
        """Returns a tuple (lo,hi) of the min and max mapping indices"""
        raise NotImplementedError()

    def get_memory_index(self, memory, mapping):
        """Returns the index of @memory in @mapping"""
        raise NotImplementedError()

    def set_memory_index(self, memory, mapping, index):
        """Sets the index of @memory in @mapping to @index"""
        raise NotImplementedError()

    def get_next_mapping_index(self, mapping):
        """Returns the next available mapping index in @mapping, or raises
        Exception if full"""
        raise NotImplementedError()


class MTOBankModel(BankModel):
    """A bank model where one memory can be in multiple banks at once """
    pass


def console_status(status):
    """Write a status object to the console"""
    import logging
    from chirp import logger
    if not logger.is_visible(logging.WARN):
        return
    import sys
    import os
    sys.stdout.write("\r%s" % status)
    if status.cur == status.max:
        sys.stdout.write(os.linesep)


class RadioPrompts:
    """Radio prompt strings"""
    info = None
    experimental = None
    pre_download = None
    pre_upload = None
    display_pre_upload_prompt_before_opening_port = True


BOOLEAN = [True, False]


class RadioFeatures:
    """Radio Feature Flags"""
    _valid_map = {
        # General
        "has_bank_index":       BOOLEAN,
        "has_dtcs":             BOOLEAN,
        "has_rx_dtcs":          BOOLEAN,
        "has_dtcs_polarity":    BOOLEAN,
        "has_mode":             BOOLEAN,
        "has_offset":           BOOLEAN,
        "has_name":             BOOLEAN,
        "has_bank":             BOOLEAN,
        "has_bank_names":       BOOLEAN,
        "has_tuning_step":      BOOLEAN,
        "has_ctone":            BOOLEAN,
        "has_cross":            BOOLEAN,
        "has_infinite_number":  BOOLEAN,
        "has_nostep_tuning":    BOOLEAN,
        "has_comment":          BOOLEAN,
        "has_settings":         BOOLEAN,

        # Attributes
        "valid_modes":          [],
        "valid_tmodes":         [],
        "valid_duplexes":       [],
        "valid_tuning_steps":   [],
        "valid_bands":          [],
        "valid_skips":          [],
        "valid_power_levels":   [],
        "valid_characters":     "",
        "valid_name_length":    0,
        "valid_cross_modes":    [],
        "valid_dtcs_pols":      [],
        "valid_dtcs_codes":     [],
        "valid_special_chans":  [],

        "has_sub_devices":      BOOLEAN,
        "memory_bounds":        (0, 0),
        "can_odd_split":        BOOLEAN,
        "can_delete":           BOOLEAN,

        # D-STAR
        "requires_call_lists":  BOOLEAN,
        "has_implicit_calls":   BOOLEAN,
    }

    def __setattr__(self, name, val):
        if name.startswith("_"):
            self.__dict__[name] = val
            return
        elif name not in self._valid_map.keys():
            raise ValueError("No such attribute `%s'" % name)

        if type(self._valid_map[name]) == tuple:
            # Tuple, cardinality must match
            if type(val) != tuple or len(val) != len(self._valid_map[name]):
                raise ValueError("Invalid value `%s' for attribute `%s'" %
                                 (val, name))
        elif type(self._valid_map[name]) == list and not self._valid_map[name]:
            # Empty list, must be another list
            if type(val) != list:
                raise ValueError("Invalid value `%s' for attribute `%s'" %
                                 (val, name))
        elif type(self._valid_map[name]) == str:
            if type(val) != str:
                raise ValueError("Invalid value `%s' for attribute `%s'" %
                                 (val, name))
        elif type(self._valid_map[name]) == int:
            if type(val) != int:
                raise ValueError("Invalid value `%s' for attribute `%s'" %
                                 (val, name))
        elif val not in self._valid_map[name]:
            # Value not in the list of valid values
            raise ValueError("Invalid value `%s' for attribute `%s'" % (val,
                                                                        name))
        self.__dict__[name] = val

    def __getattr__(self, name):
        raise AttributeError("pylint is confused by RadioFeatures")

    def init(self, attribute, default, doc=None):
        """Initialize a feature flag @attribute with default value @default,
        and documentation string @doc"""
        self.__setattr__(attribute, default)
        self.__docs[attribute] = doc

    def get_doc(self, attribute):
        """Return the description of @attribute"""
        return self.__docs[attribute]

    def __init__(self):
        self.__docs = {}
        self.init("has_bank_index", False,
                  "Indicates that memories in a bank can be stored in " +
                  "an order other than in main memory")
        self.init("has_dtcs", True,
                  "Indicates that DTCS tone mode is available")
        self.init("has_rx_dtcs", False,
                  "Indicates that radio can use two different " +
                  "DTCS codes for rx and tx")
        self.init("has_dtcs_polarity", True,
                  "Indicates that the DTCS polarity can be changed")
        self.init("has_mode", True,
                  "Indicates that multiple emission modes are supported")
        self.init("has_offset", True,
                  "Indicates that the TX offset memory property is supported")
        self.init("has_name", True,
                  "Indicates that an alphanumeric memory name is supported")
        self.init("has_bank", True,
                  "Indicates that memories may be placed into banks")
        self.init("has_bank_names", False,
                  "Indicates that banks may be named")
        self.init("has_tuning_step", True,
                  "Indicates that memories store their tuning step")
        self.init("has_ctone", True,
                  "Indicates that the radio keeps separate tone frequencies " +
                  "for repeater and CTCSS operation")
        self.init("has_cross", False,
                  "Indicates that the radios supports different tone modes " +
                  "on transmit and receive")
        self.init("has_infinite_number", False,
                  "Indicates that the radio is not constrained in the " +
                  "number of memories that it can store")
        self.init("has_nostep_tuning", False,
                  "Indicates that the radio does not require a valid " +
                  "tuning step to store a frequency")
        self.init("has_comment", False,
                  "Indicates that the radio supports storing a comment " +
                  "with each memory")
        self.init("has_settings", False,
                  "Indicates that the radio supports general settings")

        self.init("valid_modes", list(MODES),
                  "Supported emission (or receive) modes")
        self.init("valid_tmodes", [],
                  "Supported tone squelch modes")
        self.init("valid_duplexes", ["", "+", "-"],
                  "Supported duplex modes")
        self.init("valid_tuning_steps", list(COMMON_TUNING_STEPS),
                  "Supported tuning steps")
        self.init("valid_bands", [],
                  "Supported frequency ranges")
        self.init("valid_skips", ["", "S"],
                  "Supported memory scan skip settings")
        self.init("valid_power_levels", [],
                  "Supported power levels")
        self.init("valid_characters", CHARSET_UPPER_NUMERIC,
                  "Supported characters for a memory's alphanumeric tag")
        self.init("valid_name_length", 6,
                  "The maximum number of characters in a memory's " +
                  "alphanumeric tag")
        self.init("valid_cross_modes", list(CROSS_MODES),
                  "Supported tone cross modes")
        self.init("valid_dtcs_pols", ["NN", "RN", "NR", "RR"],
                  "Supported DTCS polarities")
        self.init("valid_dtcs_codes", list(DTCS_CODES),
                  "Supported DTCS codes")
        self.init("valid_special_chans", [],
                  "Supported special channel names")

        self.init("has_sub_devices", False,
                  "Indicates that the radio behaves as two semi-independent " +
                  "devices")
        self.init("memory_bounds", (0, 1),
                  "The minimum and maximum channel numbers")
        self.init("can_odd_split", False,
                  "Indicates that the radio can store an independent " +
                  "transmit frequency")
        self.init("can_delete", True,
                  "Indicates that the radio can delete memories")
        self.init("requires_call_lists", True,
                  "[D-STAR] Indicates that the radio requires all callsigns " +
                  "to be in the master list and cannot be stored " +
                  "arbitrarily in each memory channel")
        self.init("has_implicit_calls", False,
                  "[D-STAR] Indicates that the radio has an implied " +
                  "callsign at the beginning of the master URCALL list")

    def is_a_feature(self, name):
        """Returns True if @name is a valid feature flag name"""
        return name in self._valid_map.keys()

    def __getitem__(self, name):
        return self.__dict__[name]

    def validate_memory(self, mem):
        """Return a list of warnings and errors that will be encoundered
        if trying to set @mem on the current radio"""
        msgs = []

        lo, hi = self.memory_bounds
        if not self.has_infinite_number and \
                (mem.number < lo or mem.number > hi) and \
                mem.extd_number not in self.valid_special_chans:
            msg = ValidationWarning("Location %i is out of range" % mem.number)
            msgs.append(msg)

        if (self.valid_modes and
                mem.mode not in self.valid_modes and
                mem.mode != "Auto"):
            msg = ValidationError("Mode %s not supported" % mem.mode)
            msgs.append(msg)

        if self.valid_tmodes and mem.tmode not in self.valid_tmodes:
            msg = ValidationError("Tone mode %s not supported" % mem.tmode)
            msgs.append(msg)
        else:
            if mem.tmode == "Cross":
                if self.valid_cross_modes and \
                        mem.cross_mode not in self.valid_cross_modes:
                    msg = ValidationError("Cross tone mode %s not supported" %
                                          mem.cross_mode)
                    msgs.append(msg)

        if self.has_dtcs_polarity and \
                mem.dtcs_polarity not in self.valid_dtcs_pols:
            msg = ValidationError("DTCS Polarity %s not supported" %
                                  mem.dtcs_polarity)
            msgs.append(msg)

        if self.valid_dtcs_codes and \
                mem.dtcs not in self.valid_dtcs_codes:
            msg = ValidationError("DTCS Code %03i not supported" % mem.dtcs)
        if self.valid_dtcs_codes and \
                mem.rx_dtcs not in self.valid_dtcs_codes:
            msg = ValidationError("DTCS Code %03i not supported" % mem.rx_dtcs)

        if self.valid_duplexes and mem.duplex not in self.valid_duplexes:
            msg = ValidationError("Duplex %s not supported" % mem.duplex)
            msgs.append(msg)

        ts = mem.tuning_step
        if self.valid_tuning_steps and ts not in self.valid_tuning_steps and \
                not self.has_nostep_tuning:
            msg = ValidationError("Tuning step %.2f not supported" % ts)
            msgs.append(msg)

        if self.valid_bands:
            valid = False
            for lo, hi in self.valid_bands:
                if lo <= mem.freq < hi:
                    valid = True
                    break
            if not valid:
                msg = ValidationError(
                    ("Frequency {freq} is out "
                     "of supported range").format(freq=format_freq(mem.freq)))
                msgs.append(msg)

        if self.valid_bands and \
                self.valid_duplexes and \
                mem.duplex in ["split", "-", "+"]:
            if mem.duplex == "split":
                freq = mem.offset
            elif mem.duplex == "-":
                freq = mem.freq - mem.offset
            elif mem.duplex == "+":
                freq = mem.freq + mem.offset
            valid = False
            for lo, hi in self.valid_bands:
                if lo <= freq < hi:
                    valid = True
                    break
            if not valid:
                msg = ValidationError(
                    ("Tx freq {freq} is out "
                     "of supported range").format(freq=format_freq(freq)))
                msgs.append(msg)

        if mem.power and \
                self.valid_power_levels and \
                mem.power not in self.valid_power_levels:
            msg = ValidationWarning("Power level %s not supported" % mem.power)
            msgs.append(msg)

        if self.valid_tuning_steps and not self.has_nostep_tuning:
            try:
                step = required_step(mem.freq)
                if step not in self.valid_tuning_steps:
                    msg = ValidationError("Frequency requires %.2fkHz step" %
                                          required_step(mem.freq))
                    msgs.append(msg)
            except errors.InvalidDataError, e:
                msgs.append(str(e))

        if self.valid_characters:
            for char in mem.name:
                if char not in self.valid_characters:
                    msgs.append(ValidationWarning("Name character " +
                                                  "`%s'" % char +
                                                  " not supported"))
                    break

        return msgs


class ValidationMessage(str):
    """Base class for Validation Errors and Warnings"""
    pass


class ValidationWarning(ValidationMessage):
    """A non-fatal warning during memory validation"""
    pass


class ValidationError(ValidationMessage):
    """A fatal error during memory validation"""
    pass


class Alias(object):
    VENDOR = "Unknown"
    MODEL = "Unknown"
    VARIANT = ""


class Radio(Alias):
    """Base class for all Radio drivers"""
    BAUD_RATE = 9600
    HARDWARE_FLOW = False
    ALIASES = []

    def status_fn(self, status):
        """Deliver @status to the UI"""
        console_status(status)

    def __init__(self, pipe):
        self.errors = []
        self.pipe = pipe

    def get_features(self):
        """Return a RadioFeatures object for this radio"""
        return RadioFeatures()

    @classmethod
    def get_name(cls):
        """Return a printable name for this radio"""
        return "%s %s" % (cls.VENDOR, cls.MODEL)

    @classmethod
    def get_prompts(cls):
        """Return a set of strings for use in prompts"""
        return RadioPrompts()

    def set_pipe(self, pipe):
        """Set the serial object to be used for communications"""
        self.pipe = pipe

    def get_memory(self, number):
        """Return a Memory object for the memory at location @number"""
        pass

    def erase_memory(self, number):
        """Erase memory at location @number"""
        mem = Memory()
        mem.number = number
        mem.empty = True
        self.set_memory(mem)

    def get_memories(self, lo=None, hi=None):
        """Get all the memories between @lo and @hi"""
        pass

    def set_memory(self, memory):
        """Set the memory object @memory"""
        pass

    def get_mapping_models(self):
        """Returns a list of MappingModel objects (or an empty list)"""
        if hasattr(self, "get_bank_model"):
            # FIXME: Backwards compatibility for old bank models
            bank_model = self.get_bank_model()
            if bank_model:
                return [bank_model]
        return []

    def get_raw_memory(self, number):
        """Return a raw string describing the memory at @number"""
        pass

    def filter_name(self, name):
        """Filter @name to just the length and characters supported"""
        rf = self.get_features()
        if rf.valid_characters == rf.valid_characters.upper():
            # Radio only supports uppercase, so help out here
            name = name.upper()
        return "".join([x for x in name[:rf.valid_name_length]
                        if x in rf.valid_characters])

    def get_sub_devices(self):
        """Return a list of sub-device Radio objects, if
        RadioFeatures.has_sub_devices is True"""
        return []

    def validate_memory(self, mem):
        """Return a list of warnings and errors that will be encoundered
        if trying to set @mem on the current radio"""
        rf = self.get_features()
        return rf.validate_memory(mem)

    def get_settings(self):
        """Returns a RadioSettings list containing one or more
        RadioSettingGroup or RadioSetting objects. These represent general
        setting knobs and dials that can be adjusted on the radio. If this
        function is implemented, the has_settings RadioFeatures flag should
        be True and set_settings() must be implemented as well."""
        pass

    def set_settings(self, settings):
        """Accepts the top-level RadioSettingGroup returned from get_settings()
        and adjusts the values in the radio accordingly. This function expects
        the entire RadioSettingGroup hierarchy returned from get_settings().
        If this function is implemented, the has_settings RadioFeatures flag
        should be True and get_settings() must be implemented as well."""
        pass


class FileBackedRadio(Radio):
    """A file-backed radio stores its data in a file"""
    FILE_EXTENSION = "img"
    MAGIC = '\x00\xffchirp\xeeimg\x00\x01'

    def __init__(self, *args, **kwargs):
        Radio.__init__(self, *args, **kwargs)
        self._memobj = None
        self._metadata = {}

    def save(self, filename):
        """Save the radio's memory map to @filename"""
        self.save_mmap(filename)

    def load(self, filename):
        """Load the radio's memory map object from @filename"""
        self.load_mmap(filename)

    def process_mmap(self):
        """Process a newly-loaded or downloaded memory map"""
        pass

    @classmethod
    def _strip_metadata(cls, raw_data):
        try:
            idx = raw_data.index(cls.MAGIC)
        except ValueError:
            LOG.debug('Image data has no metadata blob')
            return raw_data, {}

        # Find the beginning of the base64 blob
        raw_metadata = raw_data[idx + len(cls.MAGIC):]
        metadata = {}
        try:
            metadata = json.loads(base64.b64decode(raw_metadata))
        except ValueError as e:
            LOG.error('Failed to parse decoded metadata blob: %s' % e)
        except TypeError as e:
            LOG.error('Failed to decode metadata blob: %s' % e)

        if metadata:
            LOG.debug('Loaded metadata: %s' % metadata)

        return raw_data[:idx], metadata

    @classmethod
    def _make_metadata(cls):
        return base64.b64encode(json.dumps(
            {'rclass': cls.__name__,
             'vendor': cls.VENDOR,
             'model': cls.MODEL,
             'variant': cls.VARIANT,
             'chirp_version': CHIRP_VERSION,
             }))

    def load_mmap(self, filename):
        """Load the radio's memory map from @filename"""
        mapfile = file(filename, "rb")
        data = mapfile.read()
        if self.MAGIC in data:
            data, self._metadata = self._strip_metadata(data)
            if ('chirp_version' in self._metadata and
                    is_version_newer(self._metadata.get('chirp_version'))):
                LOG.warning('Image is from version %s but we are %s' % (
                    self._metadata.get('chirp_version'), CHIRP_VERSION))
        self._mmap = memmap.MemoryMap(data)
        mapfile.close()
        self.process_mmap()

    def save_mmap(self, filename):
        """
        try to open a file and write to it
        If IOError raise a File Access Error Exception
        """
        try:
            mapfile = file(filename, "wb")
            mapfile.write(self._mmap.get_packed())
            if filename.lower().endswith(".img"):
                mapfile.write(self.MAGIC)
                mapfile.write(self._make_metadata())
            mapfile.close()
        except IOError:
            raise Exception("File Access Error")

    def get_mmap(self):
        """Return the radio's memory map object"""
        return self._mmap

    @property
    def metadata(self):
        return dict(self._metadata)

    @metadata.setter
    def metadata(self, value):
        self._metadata.update(values)


class CloneModeRadio(FileBackedRadio):
    """A clone-mode radio does a full memory dump in and out and we store
    an image of the radio into an image file"""

    _memsize = 0

    def __init__(self, pipe):
        self.errors = []
        self._mmap = None

        if isinstance(pipe, str):
            self.pipe = None
            self.load_mmap(pipe)
        elif isinstance(pipe, memmap.MemoryMap):
            self.pipe = None
            self._mmap = pipe
            self.process_mmap()
        else:
            FileBackedRadio.__init__(self, pipe)

    def get_memsize(self):
        """Return the radio's memory size"""
        return self._memsize

    @classmethod
    def match_model(cls, filedata, filename):
        """Given contents of a stored file (@filedata), return True if
        this radio driver handles the represented model"""

        # Unless the radio driver does something smarter, claim
        # support if the data is the same size as our memory.
        # Ideally, each radio would perform an intelligent analysis to
        # make this determination to avoid model conflicts with
        # memories of the same size.
        return len(filedata) == cls._memsize

    def sync_in(self):
        "Initiate a radio-to-PC clone operation"
        pass

    def sync_out(self):
        "Initiate a PC-to-radio clone operation"
        pass


class LiveRadio(Radio):
    """Base class for all Live-Mode radios"""
    pass


class NetworkSourceRadio(Radio):
    """Base class for all radios based on a network source"""

    def do_fetch(self):
        """Fetch the source data from the network"""
        pass


class IcomDstarSupport:
    """Base interface for radios supporting Icom's D-STAR technology"""
    MYCALL_LIMIT = (1, 1)
    URCALL_LIMIT = (1, 1)
    RPTCALL_LIMIT = (1, 1)

    def get_urcall_list(self):
        """Return a list of URCALL callsigns"""
        return []

    def get_repeater_call_list(self):
        """Return a list of RPTCALL callsigns"""
        return []

    def get_mycall_list(self):
        """Return a list of MYCALL callsigns"""
        return []

    def set_urcall_list(self, calls):
        """Set the URCALL callsign list"""
        pass

    def set_repeater_call_list(self, calls):
        """Set the RPTCALL callsign list"""
        pass

    def set_mycall_list(self, calls):
        """Set the MYCALL callsign list"""
        pass


class ExperimentalRadio:
    """Interface for experimental radios"""
    @classmethod
    def get_experimental_warning(cls):
        return ("This radio's driver is marked as experimental and may " +
                "be unstable or unsafe to use.")


class Status:
    """Clone status object for conveying clone progress to the UI"""
    name = "Job"
    msg = "Unknown"
    max = 100
    cur = 0

    def __str__(self):
        try:
            pct = (self.cur / float(self.max)) * 100
            nticks = int(pct) / 10
            ticks = "=" * nticks
        except ValueError:
            pct = 0.0
            ticks = "?" * 10

        return "|%-10s| %2.1f%% %s" % (ticks, pct, self.msg)


def is_fractional_step(freq):
    """Returns True if @freq requires a 12.5kHz or 6.25kHz step"""
    return not is_5_0(freq) and (is_12_5(freq) or is_6_25(freq))


def is_5_0(freq):
    """Returns True if @freq is reachable by a 5kHz step"""
    return (freq % 5000) == 0


def is_12_5(freq):
    """Returns True if @freq is reachable by a 12.5kHz step"""
    return (freq % 12500) == 0


def is_6_25(freq):
    """Returns True if @freq is reachable by a 6.25kHz step"""
    return (freq % 6250) == 0


def is_2_5(freq):
    """Returns True if @freq is reachable by a 2.5kHz step"""
    return (freq % 2500) == 0


def is_8_33(freq):
    """Returns True if @freq is reachable by a 8.33kHz step"""
    return (freq % 25000) in [0, 8330, 16660]


def required_step(freq):
    """Returns the simplest tuning step that is required to reach @freq"""
    if is_5_0(freq):
        return 5.0
    elif is_12_5(freq):
        return 12.5
    elif is_6_25(freq):
        return 6.25
    elif is_2_5(freq):
        return 2.5
    elif is_8_33(freq):
        return 8.33
    else:
        raise errors.InvalidDataError("Unable to calculate the required " +
                                      "tuning step for %i.%5i" %
                                      (freq / 1000000, freq % 1000000))


def fix_rounded_step(freq):
    """Some radios imply the last bit of 12.5kHz and 6.25kHz step
    frequencies. Take the base @freq and return the corrected one"""
    try:
        required_step(freq)
        return freq
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 500)
        return freq + 500
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 250)
        return freq + 250
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 750)
        return float(freq + 750)
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 330)
        return float(freq + 330)
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 660)
        return float(freq + 660)
    except errors.InvalidDataError:
        pass

    raise errors.InvalidDataError("Unable to correct rounded frequency " +
                                  format_freq(freq))


def _name(name, len, just_upper):
    """Justify @name to @len, optionally converting to all uppercase"""
    if just_upper:
        name = name.upper()
    return name.ljust(len)[:len]


def name6(name, just_upper=True):
    """6-char name"""
    return _name(name, 6, just_upper)


def name8(name, just_upper=False):
    """8-char name"""
    return _name(name, 8, just_upper)


def name16(name, just_upper=False):
    """16-char name"""
    return _name(name, 16, just_upper)


def to_GHz(val):
    """Convert @val in GHz to Hz"""
    return val * 1000000000


def to_MHz(val):
    """Convert @val in MHz to Hz"""
    return val * 1000000


def to_kHz(val):
    """Convert @val in kHz to Hz"""
    return val * 1000


def from_GHz(val):
    """Convert @val in Hz to GHz"""
    return val / 100000000


def from_MHz(val):
    """Convert @val in Hz to MHz"""
    return val / 100000


def from_kHz(val):
    """Convert @val in Hz to kHz"""
    return val / 100


def split_tone_decode(mem, txtone, rxtone):
    """
    Set tone mode and values on @mem based on txtone and rxtone specs like:
    None, None, None
    "Tone", 123.0, None
    "DTCS", 23, "N"
    """
    txmode, txval, txpol = txtone
    rxmode, rxval, rxpol = rxtone

    mem.dtcs_polarity = "%s%s" % (txpol or "N", rxpol or "N")

    if not txmode and not rxmode:
        # No tone
        return

    if txmode == "Tone" and not rxmode:
        mem.tmode = "Tone"
        mem.rtone = txval
        return

    if txmode == rxmode == "Tone" and txval == rxval:
        # TX and RX same tone -> TSQL
        mem.tmode = "TSQL"
        mem.ctone = txval
        return

    if txmode == rxmode == "DTCS" and txval == rxval:
        mem.tmode = "DTCS"
        mem.dtcs = txval
        return

    mem.tmode = "Cross"
    mem.cross_mode = "%s->%s" % (txmode or "", rxmode or "")

    if txmode == "Tone":
        mem.rtone = txval
    elif txmode == "DTCS":
        mem.dtcs = txval

    if rxmode == "Tone":
        mem.ctone = rxval
    elif rxmode == "DTCS":
        mem.rx_dtcs = rxval


def split_tone_encode(mem):
    """
    Returns TX, RX tone specs based on @mem like:
    None, None, None
    "Tone", 123.0, None
    "DTCS", 23, "N"
    """

    txmode = ''
    rxmode = ''
    txval = None
    rxval = None

    if mem.tmode == "Tone":
        txmode = "Tone"
        txval = mem.rtone
    elif mem.tmode == "TSQL":
        txmode = rxmode = "Tone"
        txval = rxval = mem.ctone
    elif mem.tmode == "DTCS":
        txmode = rxmode = "DTCS"
        txval = rxval = mem.dtcs
    elif mem.tmode == "Cross":
        txmode, rxmode = mem.cross_mode.split("->", 1)
        if txmode == "Tone":
            txval = mem.rtone
        elif txmode == "DTCS":
            txval = mem.dtcs
        if rxmode == "Tone":
            rxval = mem.ctone
        elif rxmode == "DTCS":
            rxval = mem.rx_dtcs

    if txmode == "DTCS":
        txpol = mem.dtcs_polarity[0]
    else:
        txpol = None
    if rxmode == "DTCS":
        rxpol = mem.dtcs_polarity[1]
    else:
        rxpol = None

    return ((txmode, txval, txpol),
            (rxmode, rxval, rxpol))


def sanitize_string(astring, validcharset=CHARSET_ASCII, replacechar='*'):
    myfilter = ''.join(
        [
            [replacechar, chr(x)][chr(x) in validcharset]
            for x in xrange(256)
        ])
    return astring.translate(myfilter)


def is_version_newer(version):
    """Return True if version is newer than ours"""

    def get_version(v):
        if v.startswith('daily-'):
            _, stamp = v.split('-', 1)
            ver = (int(stamp),)
        elif '.' in v:
            ver = tuple(int(p) for p in v.split('.'))
        else:
            ver = (0,)
        LOG.debug('Parsed version %r to %r' % (v, ver))
        return ver

    from chirp import CHIRP_VERSION

    try:
        version = get_version(version)
    except ValueError as e:
        LOG.error('Failed to parse version %r: %s' % (version, e))
        version = (0,)
    try:
        my_version = get_version(CHIRP_VERSION)
    except ValueError as e:
        LOG.error('Failed to parse my version %r: %s' % (CHIRP_VERSION, e))
        my_version = (0,)

    return version > my_version


def http_user_agent():
    ver = sys.version_info
    return 'chirp/%s (Python %i.%i.%i on %s)' % (
        CHIRP_VERSION,
        ver.major, ver.minor, ver.micro,
        sys.platform)
