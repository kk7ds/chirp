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

import os
import csv

from chirp import chirp_common, errors, directory

class OmittedHeaderError(Exception):
    """Internal exception to signal that a column has been omitted"""
    pass

def get_datum_by_header(headers, data, header):
    """Return the column corresponding to @headers[@header] from @data"""
    if header not in headers:
        raise OmittedHeaderError("Header %s not provided" % header)

    try:
        return data[headers.index(header)]
    except IndexError:
        raise OmittedHeaderError("Header %s not provided on this line" % \
                                     header)

def write_memory(writer, mem):
    """Write @mem using @writer if not empty"""
    if mem.empty:
        return
    writer.writerow(mem.to_csv())

@directory.register
class CSVRadio(chirp_common.FileBackedRadio, chirp_common.IcomDstarSupport):
    """A driver for Generic CSV files"""
    VENDOR = "Generic"
    MODEL = "CSV"
    FILE_EXTENSION = "csv"

    ATTR_MAP = {
        "Location"     : (int,   "number"),
        "Name"         : (str,   "name"),
        "Frequency"    : (chirp_common.parse_freq, "freq"),
        "Duplex"       : (str,   "duplex"),
        "Offset"       : (chirp_common.parse_freq, "offset"),
        "Tone"         : (str,   "tmode"),
        "rToneFreq"    : (float, "rtone"),
        "cToneFreq"    : (float, "ctone"),
        "DtcsCode"     : (int,   "dtcs"),
        "DtcsPolarity" : (str,   "dtcs_polarity"),
        "Mode"         : (str,   "mode"),
        "TStep"        : (float, "tuning_step"),
        "Skip"         : (str,   "skip"),
        "URCALL"       : (str,   "dv_urcall"),
        "RPT1CALL"     : (str,   "dv_rpt1call"),
        "RPT2CALL"     : (str,   "dv_rpt2call"),
        "Comment"      : (str,   "comment"),
        }

    def _blank(self):
        self.errors = []
        self.memories = []
        for i in range(0, 1000):
            mem = chirp_common.Memory()
            mem.number = i
            mem.empty = True
            self.memories.append(mem)

    def __init__(self, pipe):
        chirp_common.FileBackedRadio.__init__(self, None)
        self.memories = []

        self._filename = pipe
        if self._filename and os.path.exists(self._filename):
            self.load()
        else:
            self._blank()

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.requires_call_lists = False
        rf.has_implicit_calls = False
        rf.memory_bounds = (0, len(self.memories))
        rf.has_infinite_number = True
        rf.has_nostep_tuning = True
        rf.has_comment = True

        rf.valid_modes = list(chirp_common.MODES)
        rf.valid_tmodes = list(chirp_common.TONE_MODES)
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(1, 10000000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 999

        return rf

    def _clean(self, headers, line, mem):
        """Runs post-processing functions on new mem objects.

        This is useful for parsing other CSV dialects when multiple columns
        convert to a single Chirp column."""

        for attr in dir(mem):
            fname = "_clean_%s" % attr
            if hasattr(self, fname):
                mem = getattr(self, fname)(headers, line, mem)
        
        return mem

    def _parse_csv_data_line(self, headers, line):
        mem = chirp_common.Memory()
        try:
            if get_datum_by_header(headers, line, "Mode") == "DV":
                mem = chirp_common.DVMemory()
        except OmittedHeaderError:
            pass

        for header in headers:
            try:
                typ, attr = self.ATTR_MAP[header]
            except KeyError:
                continue
            try:
                val = get_datum_by_header(headers, line, header)
                if not val and typ == int:
                    val = None
                else:
                    val = typ(val)
                if hasattr(mem, attr):
                    setattr(mem, attr, val)
            except OmittedHeaderError, e:
                pass
            except Exception, e:
                raise Exception("[%s] %s" % (attr, e))

        return self._clean(headers, line, mem)

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self._blank()

        f = file(self._filename, "rU")
        header = f.readline().strip()

        f.seek(0, 0)
        reader = csv.reader(f, delimiter=chirp_common.SEPCHAR, quotechar='"')

        good = 0
        lineno = 0
        for line in reader:
            lineno += 1
            if lineno == 1:
                header = line
                continue

            if len(header) > len(line):
                print "Line %i has %i columns, expected %i" % (lineno,
                                                               len(line),
                                                               len(header))
                self.errors.append("Column number mismatch on line %i" % lineno)
                continue

            try:
                mem = self._parse_csv_data_line(header, line)
                if mem.number is None:
                    raise Exception("Invalid Location field" % lineno)
            except Exception, e:
                print "Line %i: %s" % (lineno, e)
                self.errors.append("Line %i: %s" % (lineno, e))
                continue

            self._grow(mem.number)
            self.memories[mem.number] = mem
            good += 1

        if not good:
            print self.errors
            raise errors.InvalidDataError("No channels found")

    def save(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to save to")

        if filename:
            self._filename = filename

        f = file(self._filename, "wb")
        writer = csv.writer(f, delimiter=chirp_common.SEPCHAR)
        writer.writerow(chirp_common.Memory.CSV_FORMAT)

        for mem in self.memories:
            write_memory(writer, mem)

        f.close()

    # MMAP compatibility
    def save_mmap(self, filename):
        return self.save(filename)

    def load_mmap(self, filename):
        return self.load(filename)

    def get_memories(self, lo=0, hi=999):
        return [x for x in self.memories if x.number >= lo and x.number <= hi]

    def get_memory(self, number):
        try:
            return self.memories[number]
        except:
            raise errors.InvalidMemoryLocation("No such memory %s" % number)

    def _grow(self, target):
        delta = target - len(self.memories)
        if delta < 0:
            return

        delta += 1
        
        for i in range(len(self.memories), len(self.memories) + delta + 1):
            mem = chirp_common.Memory()
            mem.empty = True
            mem.number = i
            self.memories.append(mem)

    def set_memory(self, newmem):
        self._grow(newmem.number)
        self.memories[newmem.number] = newmem

    def erase_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        mem.empty = True
        self.memories[number] = mem

    def get_raw_memory(self, number):
        return ",".join(chirp_common.Memory.CSV_FORMAT) + \
            os.linesep + \
            ",".join(self.memories[number].to_csv())

    @classmethod
    def match_model(cls, _filedata, filename):
        """Match files ending in .CSV"""
        return filename.lower().endswith("." + cls.FILE_EXTENSION)
