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

SEPCHAR = ","
    
#print "Using separation character of '%s'" % SEPCHAR

import threading
import math
from decimal import Decimal

from chirp import errors, memmap

# 50 Tones
TONES = [ 67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5,
          85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5,
          107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
          131.8, 136.5, 141.3, 146.2, 151.4, 156.7,
          159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
          177.3, 179.9, 183.5, 186.2, 189.9, 192.8,
          196.6, 199.5, 203.5, 206.5, 210.7, 218.1,
          225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
          ]          

# 104 DTCS Codes
DTCS_CODES = [
     23,  25,  26,  31,  32,  36,  43,  47,  51,  53,  54,
     65,  71,  72,  73,  74, 114, 115, 116, 122, 125, 131,
    132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174,
    205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
    255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325,
    331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412,
    413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464,
    465, 466, 503, 506, 516, 523, 526, 532, 546, 565, 606,
    612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723,
    731, 732, 734, 743, 754,
     ]

# Some radios have some strange codes
DTCS_EXTRA_CODES = [ 17, ]

CROSS_MODES = [
    "DCS->Off",
    "Tone->DCS",
    "DCS->CTCSS",
    "Tone->CTCSS",
    "Off->Tone",
    "Off->DCS",
]

MODES = ["WFM", "FM", "NFM", "AM", "NAM", "DV", "USB", "LSB", "CW", "RTTY", "DIG", "PKT", "NCW", "NCWR", "CWR"]

STD_6M_OFFSETS = [
    (51620000, 51980000, -500000),
    (52500000, 52980000, -500000),
    (53500000, 53980000, -500000),
    ]

STD_2M_OFFSETS = [
    (145100000, 145500000, -600000),
    (146000000, 146400000,  600000),
    (146600000, 147000000, -600000),
    (147000000, 147400000,  600000),
    (147600000, 148000000, -600000),
    ]

STD_220_OFFSETS = [
    (223850000, 224980000, -1600000),
    ]

STD_70CM_OFFSETS = [
    (440000000, 445000000,  5000000),
    (447000000, 450000000, -5000000),
    ]

STD_23CM_OFFSETS = [
    (1282000000, 1288000000, -12000000),
    ]

# Standard offsets, indexed by band (wavelength in cm)
STD_OFFSETS = {
    600 : STD_6M_OFFSETS,
    200 : STD_2M_OFFSETS,
    125 : STD_220_OFFSETS,
     70 : STD_70CM_OFFSETS,
     23 : STD_23CM_OFFSETS,
    }

BAND_TO_MHZ = {
    600 : (   50000000,   54000000 ),
    200 : (  144000000,  148000000 ),
    125 : (  219000000,  225000000 ),
    70 :  (  420000000,  450000000 ),
    23 :  ( 1240000000, 1300000000 ),
}

# NB: This only works for some bands, throws an Exception otherwise
def freq_to_band(freq):
    for band, (lo, hi) in BAND_TO_MHZ.items():
        if int(freq) > lo and int(freq) < hi:
            return band
    raise Exception("No conversion for frequency %i" % freq)

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

SKIP_VALUES = [ "", "S", "P" ]

CHARSET_UPPER_NUMERIC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ 1234567890"
CHARSET_ALPHANUMERIC = \
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz 1234567890"
CHARSET_ASCII = "".join([chr(x) for x in range(ord(" "), ord("~")+1)])

def watts_to_dBm(watts):
    return int(10 * math.log10(int(watts * 1000)))

def dBm_to_watts(dBm):
    return int(math.pow(10, (dBm - 30) / 10))

class PowerLevel:
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
    if "." in freqstr:
        MHz, kHz = freqstr.split(".")
    else:
        MHz = freqstr
        kHz = 0
    if not MHz.isdigit() and kHz.isdigit():
        raise ValueError("Invalid value")

    # Make kHz exactly six decimal places
    return int(("%s%-6s" % (MHz, kHz)).replace(" ", "0"))

def format_freq(freq):
    return "%i.%06i" % (freq / 1000000, freq % 1000000)

class Memory:
    freq = 0
    number = 0
    extd_number = ""
    name = ""
    vfo = 0
    rtone = 88.5
    ctone = 88.5
    dtcs = 23
    tmode = ""
    cross_mode = "DCS->Off"
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

    def __init__(self):
        self.freq = 0
        self.number = 0                   
        self.extd_number = ""             
        self.name = ""                    
        self.vfo = 0                      
        self.rtone = 88.5                 
        self.ctone = 88.5                 
        self.dtcs = 23                    
        self.tmode = ""                   
        self.cross_mode = "DCS->Off"      
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
        "rtone"         : TONES,
        "ctone"         : TONES,
        "dtcs"          : DTCS_CODES + DTCS_EXTRA_CODES,
        "tmode"         : TONE_MODES,
        "dtcs_polarity" : ["NN", "NR", "RN", "RR"],
        "cross_mode"    : CROSS_MODES,
        "mode"          : MODES,
        "duplex"        : ["", "+", "-", "split"],
        "skip"          : SKIP_VALUES,
        "empty"         : [True, False],
        "dv_code"       : [x for x in range(0, 100)],
        }

    def __repr__(self):
        return "Memory[%i]" % self.number

    def dupe(self):
        m = self.__class__()
        for k, v in self.__dict__.items():
            m.__dict__[k] = v

        return m

    CSV_FORMAT = ["Location", "Name", "Frequency",
                  "Duplex", "Offset", "Tone",
                  "rToneFreq", "cToneFreq", "DtcsCode",
                  "DtcsPolarity", "Mode", "TStep",
                  "Skip", "Comment",
                  "URCALL", "RPT1CALL", "RPT2CALL"]

    def __setattr__(self, name, val):
        if not hasattr(self, name):
            raise ValueError("No such attribute `%s'" % name)

        if name in self.immutable:
            raise ValueError("Field %s is not mutable on this memory" % name)

        if self._valid_map.has_key(name) and val not in self._valid_map[name]:
            raise ValueError("`%s' is not in valid list: %s" % (\
                    val,
                    self._valid_map[name]))

        self.__dict__[name] = val

    def format_freq(self):
        return format_freq(self.freq)

    def parse_freq(self, freqstr):
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

        return "Memory %i: %s%s%s %s (%s) r%.1f%s c%.1f%s d%03i%s%s [TS=%.2f]"% \
            (self.number,
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
        return [
            "%i"   % self.number,
            "%s"   % self.name,
            format_freq(self.freq),
            "%s"   % self.duplex,
            format_freq(self.offset),
            "%s"   % self.tmode,
            "%.1f" % self.rtone,
            "%.1f" % self.ctone,
            "%03i" % self.dtcs,
            "%s"   % self.dtcs_polarity,
            "%s"   % self.mode,
            "%.2f" % self.tuning_step,
            "%s"   % self.skip,
            "%s"   % self.comment,
            "", "", "", ""]

    class Callable:
        def __init__(self, target):
            self.__call__ = target

    def _from_csv(_line):
        line = _line.strip()
        if line.startswith("Location"):
            raise errors.InvalidMemoryLocation("Non-CSV line")

        vals = line.split(SEPCHAR)
        if len(vals) < 11:
            raise errors.InvalidDataError("CSV format error (14 columns expected)")

        if vals[10] == "DV":
            mem = DVMemory()
        else:
            mem = Memory()

        mem.really_from_csv(vals)
        return mem

    from_csv = Callable(_from_csv)

    def really_from_csv(self, vals):
        try:
            self.number = int(vals[0])
        except:
            print "Loc: %s" % vals[0]
            raise errors.InvalidDataError("Location is not a valid integer")

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
            raise errors.InvalidDataError("Invalid tone mode `%s'" % self.tmode)

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
            "%i"   % self.number,
            "%s"   % self.name,
            format_freq(self.freq),
            "%s"   % self.duplex,
            format_freq(self.offset),
            "%s"   % self.tmode,
            "%.1f" % self.rtone,
            "%.1f" % self.ctone,
            "%03i" % self.dtcs,
            "%s"   % self.dtcs_polarity,
            "%s"   % self.mode,
            "%.2f" % self.tuning_step,
            "%s"   % self.skip,
            "%s" % self.comment,
            "%s"   % self.dv_urcall,
            "%s"   % self.dv_rpt1call,
            "%s"   % self.dv_rpt2call,
            "%i"   % self.dv_code]

    def really_from_csv(self, vals):
        Memory.really_from_csv(self, vals)

        self.dv_urcall = vals[15].rstrip()[:8]
        self.dv_rpt1call = vals[16].rstrip()[:8]
        self.dv_rpt2call = vals[17].rstrip()[:8]
        try:
            self.dv_code = int(vals[18].strip())
        except:
            self.dv_code = 0

class Bank:
    def __init__(self, model, index, name):
        self._model = model
        self._index = index
        self._name = name

    def __str__(self):
        return self.get_name()

    def __repr__(self):
        return "Bank-%s" % self._index

    def get_name(self):
        """Returns the static or user-adjustable bank name"""
        return self._name

    def get_index(self):
        """Returns the immutable bank index (string or int)"""
        return self._index

    def __eq__(self, other):
        return self.get_index() == other.get_index()

class NamedBank(Bank):
    def set_name(self, name):
        """Changes the user-adjustable bank name"""
        self._name = name

class BankModel:
    """A bank model where one memory is in zero or one banks at any point"""
    def __init__(self, radio):
        self._radio = radio

    def get_num_banks(self):
        """Returns the number of banks (should be callable without
        consulting the radio"""
        raise Exception("Not implemented")

    def get_banks(self):
        """Return a list of banks"""
        raise Exception("Not implemented")

    def add_memory_to_bank(self, memory, bank):
        """Add @memory to @bank."""
        raise Exception("Not implemented")

    def remove_memory_from_bank(self, memory, bank):
        """Remove @memory from @bank.
        Shall raise exception if @memory is not in @bank."""
        raise Exception("Not implemented")

    def get_bank_memories(self, bank):
        """Return a list of memories in @bank"""
        raise Exception("Not implemented")

    def get_memory_banks(self, memory):
        """Returns a list of the banks that @memory is in"""
        raise Exception("Not implemented")

class BankIndexInterface:
    def get_index_bounds(self):
        """Returns a tuple (lo,hi) of the minimum and maximum bank indices"""
        raise Exception("Not implemented")

    def get_memory_index(self, memory, bank):
        """Returns the index of @memory in @bank"""
        raise Exception("Not implemented")

    def set_memory_index(self, memory, bank, index):
        """Sets the index of @memory in @bank to @index"""
        raise Exception("Not implemented")

    def get_next_bank_index(self, bank):
        """Returns the next available bank index in @bank, or raises
        Exception if full"""
        raise Exception("Not implemented")


class MTOBankModel(BankModel):
    """A bank model where one memory can be in multiple banks at once """
    pass

def console_status(status):
    import sys

    sys.stderr.write("\r%s" % status)
    

class Callable:
    def __init__(self, target):
        self.__call__ = target

BOOLEAN = [True, False]

class RadioFeatures:
    _valid_map = {
        # General
        "has_bank_index"      : BOOLEAN,
        "has_dtcs"            : BOOLEAN,
        "has_dtcs_polarity"   : BOOLEAN,
        "has_mode"            : BOOLEAN,
        "has_offset"          : BOOLEAN,
        "has_name"            : BOOLEAN,
        "has_bank"            : BOOLEAN,
        "has_bank_names"      : BOOLEAN,
        "has_tuning_step"     : BOOLEAN,
        "has_name"            : BOOLEAN,
        "has_ctone"           : BOOLEAN,
        "has_cross"           : BOOLEAN,
        "has_infinite_number" : BOOLEAN,
        "has_nostep_tuning"   : BOOLEAN,
        "has_comment"         : BOOLEAN,

        # Attributes
        "valid_modes"         : [],
        "valid_tmodes"        : [],
        "valid_duplexes"      : [],
        "valid_tuning_steps"  : [],
        "valid_bands"         : [],
        "valid_skips"         : [],
        "valid_power_levels"  : [],
        "valid_characters"    : "",
        "valid_name_length"   : 0,
        "valid_cross_modes"   : [],
        "valid_dtcs_pols"     : [],

        "has_sub_devices"     : BOOLEAN,
        "memory_bounds"       : (0, 0),
        "can_odd_split"       : BOOLEAN,

        # D-STAR
        "requires_call_lists" : BOOLEAN,
        "has_implicit_calls"  : BOOLEAN,
        }

    def __setattr__(self, name, val):
        if name.startswith("_"):
            self.__dict__[name] = val
            return
        elif not name in self._valid_map.keys():
            raise ValueError("No such attribute `%s'" % name)

        if type(self._valid_map[name]) == tuple:
            # Tuple, cardinality must match
            if type(val) != tuple or len(val) != len(self._valid_map[name]):
                raise ValueError("Invalid value `%s' for attribute `%s'" % \
                                     (val, name))
        elif type(self._valid_map[name]) == list and not self._valid_map[name]:
            # Empty list, must be another list
            if type(val) != list:
                raise ValueError("Invalid value `%s' for attribute `%s'" % \
                                     (val, name))
        elif type(self._valid_map[name]) == str:
            if type(val) != str:
                raise ValueError("Invalid value `%s' for attribute `%s'" % \
                                     (val, name))
        elif type(self._valid_map[name]) == int:
            if type(val) != int:
                raise ValueError("Invalid value `%s' for attribute `%s'" % \
                                     (val, name))
        elif val not in self._valid_map[name]:
            # Value not in the list of valid values
            raise ValueError("Invalid value `%s' for attribute `%s'" % (val,
                                                                        name))
        self.__dict__[name] = val

    def init(self, attribute, default, doc=None):
        self.__setattr__(attribute, default)
        self.__docs[attribute] = doc

    def get_doc(self, attribute):
        return self.__docs[attribute]

    def __init__(self):
        self.__docs = {}
        self.init("has_bank_index", False,
                  "Indicates that memories in a bank can be stored in " +
                  "an order other than in main memory")
        self.init("has_dtcs", True,
                  "Indicates that DTCS tone mode is available")
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

        self.init("valid_modes", list(MODES),
                  "Supported emission (or receive) modes")
        self.init("valid_tmodes", [],
                  "Supported tone squelch modes")
        self.init("valid_duplexes", ["", "+", "-"],
                  "Supported duplex modes")
        self.init("valid_tuning_steps", list(TUNING_STEPS),
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

        self.init("has_sub_devices", False,
                  "Indicates that the radio behaves as two semi-independent " +
                  "devices")
        self.init("memory_bounds", (0, 1),
                  "The minimum and maximum channel numbers")
        self.init("can_odd_split", False,
                  "Indicates that the radio can store an independent " +
                  "transmit frequency")

        self.init("requires_call_lists", True,
                  "[D-STAR] Indicates that the radio requires all callsigns " +
                  "to be in the master list and cannot be stored " +
                  "arbitrarily in each memory channel")
        self.init("has_implicit_calls", False,
                  "[D-STAR] Indicates that the radio has an implied " +
                  "callsign at the beginning of the master URCALL list")

    def is_a_feature(self, name):
        return name in self._valid_map.keys()

    def __getitem__(self, name):
        return self.__dict__[name]

class ValidationMessage(str):
    pass

class ValidationWarning(ValidationMessage):
    pass

class ValidationError(ValidationMessage):
    pass

class Radio:
    BAUD_RATE = 9600
    HARDWARE_FLOW = False
    VENDOR = "Unknown"
    MODEL = "Unknown"
    VARIANT = ""

    status_fn = lambda x, y: console_status(y)

    def __init__(self, pipe):
        self.errors = []
        self.pipe = pipe

    def get_features(self):
        return RadioFeatures()

    def _get_name_raw(*args):
        cls = args[-1]
        return "%s %s" % (cls.VENDOR, cls.MODEL)

    def get_name(self):
        return self._get_name_raw(self.__class__)

    _get_name = Callable(_get_name_raw)

    def set_pipe(self, pipe):
        self.pipe = pipe

    def get_memory(self, number):
        pass

    def erase_memory(self, number):
        m = Memory()
        m.number = number
        m.empty = True
        self.set_memory(m)

    def get_memories(self, lo=None, hi=None):
        pass

    def set_memory(self, memory):
        pass

    def set_memories(self, memories):
        pass

    def get_bank_model(self):
        """Returns either a BankModel or None if not supported"""
        return None

    def get_raw_memory(self, number):
        pass

    def get_special_locations(self):
        return []

    def filter_name(self, name):
        rf = self.get_features()
        if rf.valid_characters == rf.valid_characters.upper():
            # Radio only supports uppercase, so help out here
            name = name.upper()
        return "".join([x for x in name[:rf.valid_name_length] if x in rf.valid_characters])

    def get_sub_devices(self):
        return []

    def validate_memory(self, mem):
        msgs = []
        rf = self.get_features()

        lo, hi = rf.memory_bounds
        if not rf.has_infinite_number and \
                (mem.number < lo or mem.number > hi) and \
                mem.extd_number not in self.get_special_locations():
            msg = ValidationWarning("Location %i is out of range" % mem.number)
            msgs.append(msg)

        if rf.valid_modes and mem.mode not in rf.valid_modes:
            msg = ValidationError("Mode %s not supported" % mem.mode)
            msgs.append(msg)

        if rf.valid_tmodes and mem.tmode not in rf.valid_tmodes:
            msg = ValidationError("Tone mode %s not supported" % mem.tmode)
            msgs.append(msg)
        else:
            if mem.tmode == "Cross":
                if rf.valid_cross_modes and mem.cross_mode not in rf.valid_cross_modes:
                    msg = ValidationError("Cross tone mode %s not supported" % mem.cross_mode)
                    msgs.append(msg)

        if rf.has_dtcs_polarity and mem.dtcs_polarity not in rf.valid_dtcs_pols:
            msg = ValidationError("DTCS Polarity %s not supported" % \
                                      mem.dtcs_polarity)
            msgs.append(msg)

        if rf.valid_duplexes and mem.duplex not in rf.valid_duplexes:
            msg = ValidationError("Duplex %s not supported" % mem.duplex)
            msgs.append(msg)

        ts = mem.tuning_step
        if rf.valid_tuning_steps and ts not in rf.valid_tuning_steps and \
                not rf.has_nostep_tuning:
            msg = ValidationError("Tuning step %.2f not supported" % ts)
            msgs.append(msg)

        if rf.valid_bands:
            valid = False
            for lo, hi in rf.valid_bands:
                if lo <= mem.freq < hi:
                    valid = True
                    break
            if not valid:
                msg = ValidationError(
                    ("Frequency {freq} is out "
                     "of supported range").format(freq=format_freq(mem.freq)))
                msgs.append(msg)

        if mem.power and \
                rf.valid_power_levels and \
                mem.power not in rf.valid_power_levels:
            msg = ValidationWarning("Power level %s not supported" % mem.power)
            msgs.append(msg)

        if rf.valid_tuning_steps and not rf.has_nostep_tuning:
            try:
                step = required_step(mem.freq)
                if step not in rf.valid_tuning_steps:
                    msg = ValidationError("Frequency requires %.2fkHz step" %\
                                              required_step(mem.freq))
                    msgs.append(msg)
            except errors.InvalidDataError, e:
                msgs.append(str(e))

        if rf.valid_characters:
            for char in mem.name:
                if char not in rf.valid_characters:
                    msgs.append(ValidationWarning(("Name character `%s'" % char) +
                                                  " not supported"))
                    break

        return msgs

class CloneModeRadio(Radio):
    """A clone-mode radio does a full memory dump in and out and we store
    an image of the radio into an image file"""

    _memsize = 0

    FILE_EXTENSION = "img"

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
            Radio.__init__(self, pipe)

    def save(self, filename):
        self.save_mmap(filename)

    def load(self, filename):
        self.load_mmap(filename)

    def process_mmap(self):
        pass

    def load_mmap(self, filename):
        mapfile = file(filename, "rb")
        self._mmap = memmap.MemoryMap(mapfile.read())
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
            mapfile.close()
        except IOError,e:
            raise Exception("File Access Error")

    def sync_in(self):
        "Initiate a radio-to-PC clone operation"
        pass

    def sync_out(self):
        "Initiate a PC-to-radio clone operation"
        pass

    def get_memsize(self):
        return self._memsize

    def get_mmap(self):
        return self._mmap

    @classmethod
    def match_model(cls, filedata):
        """Given contents of a stored file (@filedata), return True if 
        this radio driver handles the represented model"""

        # Unless the radio driver does something smarter, claim
        # support if the data is the same size as our memory.
        # Ideally, each radio would perform an intelligent analysis to
        # make this determination to avoid model conflicts with
        # memories of the same size.
        return len(filedata) == cls._memsize

class LiveRadio(Radio):
    pass

class IcomDstarSupport:
    MYCALL_LIMIT = (1, 1)
    URCALL_LIMIT = (1, 1)
    RPTCALL_LIMIT = (1, 1)
    
    def get_urcall_list(self):
        return []

    def get_repeater_call_list(self):
        return []

    def get_mycall_list(self):
        return []

    def set_urcall_list(self, calls):
        pass

    def set_repeater_call_list(self, calls):
        pass

    def set_mycall_list(self, calls):
        pass

class Status:
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
    return not is_5_0(freq) and (is_12_5(freq) or is_6_25(freq))

def is_5_0(freq):
    return (freq % 5000) == 0

def is_12_5(freq):
    return (freq % 12500) == 0

def is_6_25(freq):
    return (freq % 6250) == 0

def is_2_5(freq):
    return (freq % 2500) == 0

def required_step(freq):
    if is_5_0(freq):
        return 5.0
    elif is_12_5(freq):
        return 12.5
    elif is_6_25(freq):
        return 6.25
    elif is_2_5(freq):
        return 2.5
    else:
        raise errors.InvalidDataError("Unable to calculate the required " +
                                      "tuning step for %i.%5i" % (freq / 1000000,
                                                                  freq % 1000000))

def fix_rounded_step(freq):
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

    raise errors.InvalidDataError("Unable to correct rounded frequency " + \
                                      format_freq(freq))

def _name(name, len, just_upper):
    if just_upper:
        name = name.upper()
    return name.ljust(len)[:len]

def name6(name, just_upper=True):
    return _name(name, 6, just_upper)

def name8(name, just_upper=False):
    return _name(name, 8, just_upper)

def name16(name, just_upper=False):
    return _name(name, 16, just_upper)

class KillableThread(threading.Thread):
    def __tid(self):
        if not self.isAlive():
            raise threading.ThreadError("Not running")

        for tid, thread in threading._active.items():
            if thread == self:
                return tid

        raise threading.ThreadError("I don't know my own TID")

    def kill(self, exception):
        import ctypes
        import inspect

        if not inspect.isclass(exception):
            raise Exception("Parameter is not an Exception")

        ctype = ctypes.py_object(exception)
        ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(self.__tid(), ctype)
        if ret != 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(self.__tid(), 0)
            raise Exception("Failed to signal thread!")

def to_GHz(val):
    return val * 1000000000

def to_MHz(val):
    return val * 1000000

def to_kHz(val):
    return val * 1000

def from_GHz(val):
    return val / 100000000

def from_MHz(val):
    return val / 100000

def from_kHz(val):
    return val / 100
