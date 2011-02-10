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

import locale

locale.setlocale(locale.LC_ALL, "")
if locale.localeconv()["decimal_point"] == ".":
    SEPCHAR = ","
else:
    SEPCHAR = ";"
    
#print "Using separation character of '%s'" % SEPCHAR

import threading
import math

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
]

MODES = ["WFM", "FM", "NFM", "AM", "NAM", "DV", "USB", "LSB", "CW", "RTTY"]

STD_2M_OFFSETS = [
    (145.1, 145.5, -0.600),
    (146.0, 146.4, 0.600),
    (146.6, 147.0, -0.600),
    (147.0, 147.4, 0.600),
    (147.6, 148.0, -0.600),
    ]

STD_70CM_OFFSETS = [
    (440.0, 445.0, 5),
    (445.0, 450.0, -5),
    ]

STD_OFFSETS = {
    1 : STD_2M_OFFSETS,
    4 : STD_70CM_OFFSETS,
    }

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
    5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0
]

SKIP_VALUES = [ "", "S", "P" ]

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

class Memory:
    freq = 0.0
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
    offset = 0.600
    mode = "FM"
    tuning_step = 5.0

    bank = None
    bank_index = -1

    empty = False

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
        "bank"          : [x for x in range(0, 256)] + [None],
        "empty"         : [True, False],
        "dv_code"       : [x for x in range(0, 100)],
        }

    immutable = []

    def __repr__(self):
        return "Memory[%i]" % self.number

    def dupe(self):
        m = self.__class__()
        for k, v in self.__dict__.items():
            m.__dict__[k] = v

        return m

    CSV_FORMAT = SEPCHAR.join(["Location", "Name", "Frequency",
                               "Duplex", "Offset", "Tone",
                               "rToneFreq", "cToneFreq", "DtcsCode",
                               "DtcsPolarity", "Mode", "TStep",
                               "Skip", "Bank", "Bank Index",
                               "URCALL", "RPT1CALL", "RPT2CALL"])

    def __setattr__(self, name, val):
        if not hasattr(self, name):
            raise ValueError("No such attribute `%s'" % name)

        if name in self.immutable:
            raise ValueError("Field %s is not mutable on this memory")

        if self._valid_map.has_key(name) and val not in self._valid_map[name]:
            raise ValueError("`%s' is not in valid list: %s" % (\
                    val,
                    self._valid_map[name]))

        self.__dict__[name] = val

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

        if self.bank_index == -1:
            bindex = ""
        else:
            bindex = ":%i" % self.bank_index

        return "Memory %i: %.5f%s%0.3f %s (%s) r%.1f%s c%.1f%s d%03i%s%s [TS=%.2f] %s" % \
            (self.number,
             self.freq,
             dup,
             self.offset,
             self.mode,
             self.name,
             self.rtone,
             tenc,
             self.ctone,
             tsql,
             self.dtcs,
             dtcs,
             self.dtcs_polarity,
             self.tuning_step,
             self.bank and "(%s%s)" % (self.bank, bindex) or "")

    def to_csv(self):
        if self.bank is None:
            bank = ""
        else:
            bank = "%s" % chr(ord("A") + self.bank)

        string = SEPCHAR.join([
                "%i"   % self.number,
                "%s"   % self.name,
                "%.5f" % self.freq,
                "%s"   % self.duplex,
                "%.5f" % self.offset,
                "%s"   % self.tmode,
                "%.1f" % self.rtone,
                "%.1f" % self.ctone,
                "%03i" % self.dtcs,
                "%s"   % self.dtcs_polarity,
                "%s"   % self.mode,
                "%.2f" % self.tuning_step,
                "%s"   % self.skip,
                "%s"   % bank,
                "%i"   % self.bank_index,
                "", "", "", ""])

        return string

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

        try:
            if not vals[13]:
                self.bank = None
            else:
                ind = ord(vals[13][0])
                if ind >= ord("A") and ind <= ord("Z"):
                    self.bank = ind - ord("A")
                elif ind >= ord("a") and ind <= ord("z"):
                    self.bank = ind - ord("a")
                else:
                    raise Exception()
        except:
            raise errors.InvalidDataError("Bank value is not valid")

        try:
            self.bank_index = int(vals[14])
        except:
            raise errors.InvalidDataError("Bank Index value is not valid")

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
        if self.bank is None:
            bank = ""
        else:
            bank = "%s" % chr(ord("A") + self.bank)

        string = SEPCHAR.join([
                "%i"   % self.number,
                "%s"   % self.name,
                "%.5f" % self.freq,
                "%s"   % self.duplex,
                "%.5f" % self.offset,
                "%s"   % self.tmode,
                "%.1f" % self.rtone,
                "%.1f" % self.ctone,
                "%03i" % self.dtcs,
                "%s"   % self.dtcs_polarity,
                "%s"   % self.mode,
                "%.2f" % self.tuning_step,
                "%s"   % self.skip,
                "%s"   % bank,
                "%i"   % self.bank_index,
                "%s"   % self.dv_urcall,
                "%s"   % self.dv_rpt1call,
                "%s"   % self.dv_rpt2call,
                "%i"   % self.dv_code])

        return string

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
    def __init__(self, name):
        self.__dict__["name"] = name

    def __str__(self):
        return self.name

class ImmutableBank(Bank):
    def __setattr__(self, name, val):
        if not hasattr(self, name):
            raise ValueError("No such attribute `%s'" % name)
        else:
            raise ValueError("Property is immutable")    

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
        "has_tuning_step"     : BOOLEAN,
        "has_name"            : BOOLEAN,
        "has_ctone"           : BOOLEAN,
        "has_cross"           : BOOLEAN,

        # Attributes
        "valid_modes"         : [],
        "valid_tmodes"        : [],
        "valid_duplexes"      : [],
        "valid_tuning_steps"  : [],
        "valid_bands"         : [],
        "valid_skips"         : [],
        "valid_power_levels"  : [],

        "has_sub_devices"     : BOOLEAN,
        "memory_bounds"       : (0, 0),
        "can_odd_split"       : BOOLEAN,

        # D-STAR
        "requires_call_lists" : BOOLEAN,
        "has_implicit_calls"  : BOOLEAN,
        }

    def __setattr__(self, name, val):
        if not name in self._valid_map.keys():
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
        elif val not in self._valid_map[name]:
            # Value not in the list of valid values
            raise ValueError("Invalid value `%s' for attribute `%s'" % (val,
                                                                        name))
        self.__dict__[name] = val

    def __init__(self):
        self.has_bank_index = False
        self.has_dtcs = True
        self.has_dtcs_polarity = True
        self.has_mode = True
        self.has_offset = True
        self.has_name = True
        self.has_bank = True
        self.has_tuning_step = True
        self.has_ctone = True
        self.has_cross = False

        self.valid_modes = list(MODES)
        self.valid_tmodes = []
        self.valid_duplexes = ["", "+", "-"]
        self.valid_tuning_steps = list(TUNING_STEPS)
        self.valid_bands = []
        self.valid_skips = ["", "S"]
        self.valid_power_levels = []

        self.has_sub_devices = False
        self.memory_bounds = (0, 1)
        self.can_odd_split = False

        self.requires_call_lists = True
        self.has_implicit_calls = False

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
    VENDOR = "Unknown"
    MODEL = "Unknown"
    VARIANT = ""

    status_fn = lambda x, y: console_status(y)

    def __init__(self, pipe):
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

    def get_banks(self):
        return []

    def set_banks(self, banks):
        raise errors.InvalidDataError("This model does not support bank naming")

    def get_raw_memory(self, number):
        pass

    def get_special_locations(self):
        return []

    def filter_name(self, name):
        return name6(name)

    def get_sub_devices(self):
        return []

    def validate_memory(self, mem):
        msgs = []
        rf = self.get_features()

        lo, hi = rf.memory_bounds
        if mem.number < lo or mem.number > hi:
            msg = ValidationWarning("Location %i is out of range" % mem.number)
            msgs.append(msg)

        if rf.valid_modes and mem.mode not in rf.valid_modes:
            msg = ValidationError("Mode %s not supported" % mem.mode)
            msgs.append(msg)

        if rf.valid_tmodes and mem.tmode not in rf.valid_tmodes:
            msg = ValidationError("Tone mode %s not supported" % mem.tmode)
            msgs.append(msg)

        if rf.valid_duplexes and mem.duplex not in rf.valid_duplexes:
            msg = ValidationError("Duplex %s not supported" % mem.duplex)
            msgs.append(msg)

        ts = mem.tuning_step
        if rf.valid_tuning_steps and ts not in rf.valid_tuning_steps:
            msg = ValidationError("Tuning step %.2f not supported" % ts)
            msgs.append(msg)

        if rf.valid_bands:
            valid = False
            for lo, hi in rf.valid_bands:
                if mem.freq > lo and mem.freq < hi:
                    valid = True
                    break
            if not valid:
                msg = ValidationError("Frequency %.5f is out of range" % mem.freq)
                msgs.append(msg)

        if rf.valid_power_levels and mem.power not in rf.valid_power_levels:
            msg = ValidationWarning("Power level %s not supported" % mem.power)
            msgs.append(msg)

        return msgs

class CloneModeRadio(Radio):
    """A clone-mode radio does a full memory dump in and out and we store
    an image of the radio into an image file"""

    _memsize = 0

    def __init__(self, pipe):

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
    dhz = freq * 1000
    return int(dhz) != dhz

def is_12_5(freq):
    return ((freq * 1000) - int(freq * 1000)) == 0.5

def is_6_25(freq):
    return ((freq * 1000) - int(freq * 1000)) == 0.25

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
