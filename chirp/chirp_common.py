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
    
print "Using separation character of '%s'" % SEPCHAR

from chirp import errors, memmap

TONES = [ 67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5,
          85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5,
          107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
          131.8, 136.5, 141.3, 146.2, 151.4, 156.7,
          159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
          177.3, 179.9, 183.5, 186.2, 189.9, 192.8,
          196.6, 199.5, 203.5, 206.5, 210.7, 218.1,
          225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
          ]          

DTCS_CODES = [
     23,  25,  26,  31,  32,  36,  43,  47,  51,  53,  54,
     65,  71,  72,  73,  74, 114, 115, 116, 122, 125, 131,
    132, 133, 134, 145, 152, 155, 156, 162, 165, 172, 174,
    205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
    255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325,
    331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412,
    413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464,
    465, 466, 503, 506, 516, 523, 526, 532, 546, 565, 606,
    612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723,
    731, 732, 734, 743, 754,
     ]

MODES = ["WFM", "FM", "NFM", "AM", "NAM", "DV"]

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
]

TUNING_STEPS = [
    5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0
]

SKIP_VALUES = [ "", "S", "P" ]

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
    dtcs_polarity = "NN"
    skip = ""

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
        "dtcs"          : DTCS_CODES,
        "tmode"         : TONE_MODES,
        "dtcs_polarity" : ["NN", "NR", "RN", "RR"],
        "mode"          : MODES,
        "duplex"        : ["", "+", "-"],
        "skip"          : SKIP_VALUES,
        "bank"          : [x for x in range(0, 256)] + [None],
        "empty"         : [True, False],
        }

    immutable = []


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
                "", "", ""])

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
                "%s"   % self.dv_rpt2call])

        return string

    def really_from_csv(self, vals):
        Memory.really_from_csv(self, vals)

        self.dv_urcall = vals[15].rstrip()[:8]
        self.dv_rpt1call = vals[16].rstrip()[:8]
        self.dv_rpt2call = vals[17].rstrip()[:8]

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
    

class IcomRadio:
    BAUD_RATE = 9600

    status_fn = lambda x, y: console_status(y)

    feature_bankindex = False

    def __init__(self, pipe):
        self.pipe = pipe

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
        pass

    def set_banks(self, banks):
        raise errors.InvalidDataError("This model does not support bank naming")

    def get_raw_memory(self, number):
        pass

    def get_special_locations(self):
        return []

    def get_memory_upper(self):
        return 0

class IcomFileBackedRadio(IcomRadio):
    def save(self, filename=None):
        pass

    def load(self, filename=None):
        pass

class IcomMmapRadio(IcomFileBackedRadio):
    BAUDRATE = 9600

    _model = "\x00\x00\x00\x00"
    _memsize = 0
    _mmap = None
    _endframe = ""
    _ranges = []

    def __init__(self, pipe):

        if isinstance(pipe, str):
            self.pipe = None
            self.load_mmap(pipe)
        else:
            IcomRadio.__init__(self, pipe)

    def load_mmap(self, filename):
        mapfile = file(filename, "rb")
        self._mmap = memmap.MemoryMap(mapfile.read())
        mapfile.close()

        self.process_mmap()

    def save_mmap(self, filename):
        mapfile = file(filename, "wb")
        mapfile.write(self._mmap.get_packed())
        mapfile.close()

    def save(self, filename):
        self.save_mmap(filename)

    def load(self, filename):
        self.load_mmap(filename)

    def sync_in(self):
        pass

    def sync_out(self):
        pass

    def process_mmap(self):
        pass

    def get_model(self):
        return self._model

    def get_endframe(self):
        return self._endframe

    def get_memsize(self):
        return self._memsize

    def get_mmap(self):
        return self._mmap

    def get_ranges(self):
        return self._ranges

class IcomDstarRadio:
    MYCALL_LIMIT = (1, 1)
    URCALL_LIMIT = (1, 1)
    RPTCALL_LIMIT = (1, 1)
    
    feature_req_call_lists = True
    feature_has_implicit_calls = False

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
