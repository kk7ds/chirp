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

class IcomFrame:
    pass

class Memory:
    freq = 0.0
    number = 0
    name = ""
    vfo = 0
    rtone = 88.5
    ctone = 88.5
    dtcs = 23
    tencEnabled = False
    tsqlEnabled = False
    dtcsEnabled = False
    dtcsPolarity = "NN"

    # FIXME: Decorator for valid value?
    duplex = ""
    offset = 0.600
    mode = "FM"
    tuningStep = 5.0

    CSV_FORMAT = "Location,Name,Frequency,Duplex,Offset," + \
        "rToneFreq,rToneOn,cToneFreq,cToneOn,DtcsCode,DtcsOn,DtcsPolarity," + \
        "Mode," 

    def __str__(self):
        if self.tencEnabled:
            tenc = "*"
        else:
            tenc = " "

        if self.tsqlEnabled:
            tsql = "*"
        else:
            tsql = " "

        if self.dtcsEnabled:
            dtcs = "*"
        else:
            dtcs = " "

        if self.duplex == "":
            dup = "/"
        else:
            dup = self.duplex

        return "Memory %i: %.5f%s%0.3f %s (%s) r%.1f%s c%.1f%s d%03i%s%s [TS=%.2f]" % \
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
             self.dtcsPolarity,
             self.tuningStep)

    def to_csv(self):
        rte = self.tencEnabled and "X" or ""
        cte = self.tsqlEnabled and "X" or ""
        dte = self.dtcsEnabled and "X" or ""

        s = "%i,%s,%.5f,%s,%.5f,%.1f,%s,%.1f,%s,%03i,%s,%s,%s," % ( \
            self.number,
            self.name,
            self.freq,
            self.duplex,
            self.offset,
            self.rtone,
            rte,
            self.ctone,
            cte,
            self.dtcs,
            dte,
            self.dtcsPolarity,
            self.mode)

        return s

    def from_csv(self, _line):
        line = _line.strip()

        if line.startswith("Location"):
            raise errors.InvalidMemoryLocation("Non-CSV line")

        vals = line.split(",")
        if len(vals) < 13:
            raise errors.InvalidDataError("CSV format error (13 columns expected)")

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
        
        try:
            self.rtone = float(vals[5])
        except:
            raise errors.InvalidDataError("rTone is not a valid number")
        if self.rtone not in TONES:
            raise errors.InvalidDataError("rTone is not valid")

        if vals[6] == "X":
            self.tencEnabled = True
        elif vals[6].strip() == "":
            self.tencEnabled = False
        else:
            raise errors.InvalidDataError("TencEnabled is not a valid boolean")

        try:
            self.ctone = float(vals[7])
        except:
            raise errors.InvalidDataError("cTone is not a valid number")
        if self.ctone not in TONES:
            raise errors.InvalidDataError("cTone is not valid")

        if vals[8] == "X":
            self.tsqlEnabled = True
        elif vals[8].strip() == "":
            self.tsqlEnabled = False
        else:
            raise errors.InvalidDataError("TsqlEnabled is not a valid boolean")

        try:
            self.dtcs = int(vals[9], 10)
        except:
            raise errors.InvalidDataError("DTCS code is not a valid number")
        if self.dtcs not in DTCS_CODES:
            raise errors.InvalidDataError("DTCS code is not valid")

        if vals[10] == "X":
            self.dtcsEnabled = True
        elif vals[10].strip() == "":
            self.dtcsEnabled = False
        else:
            raise errors.InvalidDataError("DtcsEnabled is not a valid boolean")

        if vals[11] in ["NN", "NR", "RN", "RR"]:
            self.dtcsPolarity = vals[11]
        else:
            raise errors.InvalidDataError("DtcsPolarity is not valid")

        if vals[12] in MODES:
            self.mode = vals[12]
        else:
            raise errors.InvalidDataError("Mode is not valid")           

        return True

class DVMemory(Memory):
    UrCall = "CQCQCQ"
    Rpt1Call = ""
    Rpt2Call = ""

    def __str__(self):
        s = Memory.__str__(self)

        s += " <%s,%s,%s>" % (self.UrCall, self.Rpt1Call, self.Rpt2Call)

        return s

class Bank:
    name = "BANK"
    vfo = 0

def console_status(status):
    import sys

    sys.stderr.write("\r%s" % status)
    

class IcomRadio:
    BAUD_RATE = 9600

    status_fn = lambda x,y: console_status(y)

    def __init__(self, pipe):
        self.pipe = pipe

    def set_pipe(self, pipe):
        self.pipe = pipe

    def get_memory(self, number):
        pass

    def erase_memory(self, number):
        pass

    def get_memories(self, lo=None, hi=None):
        pass

    def set_memory(self, memory):
        pass

    def set_memories(self, memories):
        pass

    def get_banks(self):
        pass

    def set_banks(self):
        pass

    def get_raw_memory(self, number):
        pass
    
class IcomMmapRadio(IcomRadio):
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
        f = file(filename, "rb")
        self._mmap = memmap.MemoryMap(f.read())
        f.close()

        self.process_mmap()

    def save_mmap(self, filename):
        f = file(filename, "wb")
        f.write(self._mmap.get_packed())
        f.close()

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
    
    def get_urcall_list(self):
        pass

    def get_repeater_call_list(self):
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

if __name__ == "__main__":
    s = Status()
    s.msg = "Cloning"
    s.max = 1234
    s.cur = 172

    print s
