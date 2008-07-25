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

import errors

TONES = [ 67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5,
          85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5,
          107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
          131.8, 136.5, 141.3, 146.2, 151.4, 156.7,
          159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
          177.3, 179.9, 183.5, 186.2, 189.9, 192.8,
          196.6, 199.5, 203.5, 206.5, 210.7, 218.1,
          225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
          ]          

MODES = ["FM", "NFM", "AM", "NAM", "DV"]

class IcomFrame:
    pass

class Memory:
    freq = 0.0
    number = 0
    name = ""
    vfo = 0
    tone = 88.5
    toneEnabled = False
    duplex = ""
    mode = "FM"
    tuningStep = 5.0

    CSV_FORMAT = "Location,Name,Frequency,ToneFreq,ToneEnabled,Duplex,Mode,"

    def __str__(self):
        if self.toneEnabled:
            te = "*"
        else:
            te = " "

        return "Memory %i: %.5f%s %s (%s) %.1f%s [TS=%.2f]" % (self.number,
                                                              self.freq,
                                                              self.duplex,
                                                              self.mode,
                                                              self.name,
                                                              self.tone,
                                                              te,
                                                              self.tuningStep)

    def to_csv(self):
        if self.toneEnabled:
            te = "X"
        else:
            te = ""
        s = "%i,%s,%.5f,%.1f,%s,%s,%s," % (self.number,
                                           self.name,
                                           self.freq,
                                           self.tone,
                                           te,
                                           self.duplex,
                                           self.mode)

        return s

    def from_csv(self, line):
        vals = line.split(",")
        if len(vals) != 7 and len(vals) != 8:
            raise errors.InvalidDataError("CSV format error")

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

        try:
            self.tone = float(vals[3])
        except:
            raise errors.InvalidDataError("Tone is not a valid number")
        if self.tone not in TONES:
            raise errors.InvalidDataError("Tone is not valid")

        if vals[4] == "X":
            self.toneEnabled = True
        elif vals[4].strip() == "":
            self.toneEnabled = False
        else:
            raise errors.InvalidDataError("ToneEnabled is not a valid boolean")

        if vals[5].strip() in ["+", "-", ""]:
            self.duplex = vals[5].strip()
        else:
            raise errors.InvalidDataError("Duplex is not +,-, or empty")

        if vals[6] in MODES:
            self.mode = vals[6]
        else:
            raise errors.InvalidDataError("Mode is not valid")           

        return True

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

    def get_memory(self, number, vfo=None):
        pass

    def get_memories(self, vfo=None):
        pass

    def set_memory(self, memory):
        pass

    def set_memories(self, memories):
        pass

    def get_banks(self, vfo=None):
        pass

    def set_banks(self, vfo=None):
        pass

    
class IcomMmapRadio(IcomRadio):
    BAUDRATE = 9600

    _model = "\x00\x00\x00\x00"
    _memsize = 0
    _mmap = None

    def __init__(self, pipe):

        if isinstance(pipe, str):
            self.pipe = None
            self.load_mmap(pipe)
        else:
            IcomRadio.__init__(self, pipe)

    def load_mmap(self, filename):
        f = file(filename, "rb")
        self._mmap = f.read()
        f.close()

        self.process_mmap()

    def save_mmap(self, filename):
        f = file(filename, "wb")
        f.write(self._mmap)
        f.close()

    def sync_in(self):
        pass

    def sync_out(self):
        pass

    def process_mmap(self):
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
