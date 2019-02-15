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
import logging

from chirp import chirp_common, errors, directory

LOG = logging.getLogger(__name__)


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
        raise OmittedHeaderError("Header %s not provided on this line" %
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
        "Location":      (int,   "number"),
        "Name":          (str,   "name"),
        "Frequency":     (chirp_common.parse_freq, "freq"),
        "Duplex":        (str,   "duplex"),
        "Offset":        (chirp_common.parse_freq, "offset"),
        "Tone":          (str,   "tmode"),
        "rToneFreq":     (float, "rtone"),
        "cToneFreq":     (float, "ctone"),
        "DtcsCode":      (int,   "dtcs"),
        "DtcsPolarity":  (str,   "dtcs_polarity"),
        "Mode":          (str,   "mode"),
        "TStep":         (float, "tuning_step"),
        "Skip":          (str,   "skip"),
        "URCALL":        (str,   "dv_urcall"),
        "RPT1CALL":      (str,   "dv_rpt1call"),
        "RPT2CALL":      (str,   "dv_rpt2call"),
        "Comment":       (str,   "comment"),
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
        self.file_has_rTone = None  # Set in load(), used in _clean_tmode()
        self.file_has_cTone = None

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
        rf.can_odd_split = True

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

    def _clean_tmode(self, headers, line, mem):
        """ If there is exactly one of [rToneFreq, cToneFreq] columns in the
        csv file, use it for both rtone & ctone. Makes TSQL use friendlier."""

        if self.file_has_rTone and not self.file_has_cTone:
            mem.ctone = mem.rtone
        elif self.file_has_cTone and not self.file_has_rTone:
            mem.rtone = mem.ctone

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
            except OmittedHeaderError as e:
                pass
            except Exception as e:
                raise Exception("[%s] %s" % (attr, e))

        return self._clean(headers, line, mem)

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self._blank()

        with open(self._filename, "rU") as f:
            header = f.readline().strip()
            f.seek(0, 0)
            return self._load(f)

    def _load(self, f):
        reader = csv.reader(f, delimiter=chirp_common.SEPCHAR, quotechar='"')

        good = 0
        lineno = 0
        for line in reader:
            lineno += 1
            if lineno == 1:
                header = line
                self.file_has_rTone = "rToneFreq" in header
                self.file_has_cTone = "cToneFreq" in header
                continue

            if len(header) > len(line):
                LOG.error("Line %i has %i columns, expected %i",
                          lineno, len(line), len(header))
                self.errors.append("Column number mismatch on line %i" %
                                   lineno)
                continue

            try:
                mem = self._parse_csv_data_line(header, line)
                if mem.number is None:
                    raise Exception("Invalid Location field" % lineno)
            except Exception as e:
                LOG.error("Line %i: %s", lineno, e)
                self.errors.append("Line %i: %s" % (lineno, e))
                continue

            self._grow(mem.number)
            self.memories[mem.number] = mem
            good += 1

        if not good:
            LOG.error(self.errors)
            raise errors.InvalidDataError("No channels found")

    def save(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to save to")

        if filename:
            self._filename = filename

        with open(self._filename, "w") as f:
            writer = csv.writer(f, delimiter=chirp_common.SEPCHAR)
            writer.writerow(chirp_common.Memory.CSV_FORMAT)

            for mem in self.memories:
                write_memory(writer, mem)

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
    def match_model(cls, filedata, filename):
        """Match files ending in .CSV"""
        try:
            filedata = filedata.decode()
        except UnicodeDecodeError:
            # CSV files are text
            return False
        return filename.lower().endswith("." + cls.FILE_EXTENSION) and \
            (filedata.startswith("Location,") or filedata == "")


@directory.register
class CommanderCSVRadio(CSVRadio):
    """A driver for reading CSV files generated by KG-UV Commander software"""
    VENDOR = "Commander"
    MODEL = "KG-UV"
    FILE_EXTENSION = "csv"

    MODE_MAP = {
        "NARR": "NFM",
        "WIDE": "FM",
    }

    SCAN_MAP = {
        "ON":  "",
        "OFF": "S"
    }

    ATTR_MAP = {
        "#":            (int,   "number"),
        "Name":         (str,   "name"),
        "RX Freq":      (chirp_common.parse_freq, "freq"),
        "Scan":         (lambda v: CommanderCSVRadio.SCAN_MAP.get(v), "skip"),
        "TX Dev":       (lambda v: CommanderCSVRadio.MODE_MAP.get(v), "mode"),
        "Group/Notes":  (str,   "comment"),
    }

    def _clean_number(self, headers, line, mem):
        if mem.number == 0:
            for memory in self.memories:
                if memory.empty:
                    mem.number = memory.number
                    break
        return mem

    def _clean_duplex(self, headers, line, mem):
        try:
            txfreq = chirp_common.parse_freq(
                get_datum_by_header(headers, line, "TX Freq"))
        except ValueError:
            mem.duplex = "off"
            return mem

        if mem.freq == txfreq:
            mem.duplex = ""
        elif txfreq:
            mem.duplex = "split"
            mem.offset = txfreq

        return mem

    def _clean_tmode(self, headers, line, mem):
        rtone = get_datum_by_header(headers, line, "Encode")
        ctone = get_datum_by_header(headers, line, "Decode")
        if rtone == "OFF":
            rtone = None
        else:
            rtone = float(rtone)

        if ctone == "OFF":
            ctone = None
        else:
            ctone = float(ctone)

        if rtone:
            mem.tmode = "Tone"
        if ctone:
            mem.tmode = "TSQL"

        mem.rtone = rtone or 88.5
        mem.ctone = ctone or mem.rtone

        return mem

    @classmethod
    def match_model(cls, filedata, filename):
        """Match files ending in .csv and using Commander column names."""
        return filename.lower().endswith("." + cls.FILE_EXTENSION) and \
            filedata.startswith("Name,RX Freq,TX Freq,Decode,Encode,TX Pwr,"
                                "Scan,TX Dev,Busy Lck,Group/Notes") or \
            filedata.startswith('"#","Name","RX Freq","TX Freq","Decode",'
                                '"Encode","TX Pwr","Scan","TX Dev",'
                                '"Busy Lck","Group/Notes"')


@directory.register
class RTCSVRadio(CSVRadio):
    """A driver for reading CSV files generated by RT Systems software"""
    VENDOR = "RT Systems"
    MODEL = "CSV"
    FILE_EXTENSION = "csv"

    DUPLEX_MAP = {
        "Minus":    "-",
        "Plus":     "+",
        "Simplex":  "",
        "Split":    "split",
    }

    SKIP_MAP = {
        "Off":    "",
        "On":     "S",
        "P Scan": "P",
        "Skip":   "S",
        }

    TMODE_MAP = {
        "None":     "",
        "T Sql":    "TSQL",
    }

    BOOL_MAP = {
        "Off":  False,
        "On":   True,
    }

    ATTR_MAP = {
        "Channel Number":    (int,   "number"),
        "Receive Frequency": (chirp_common.parse_freq, "freq"),
        "Offset Frequency":  (chirp_common.parse_freq, "offset"),
        "Offset Direction":  (lambda v:
                              RTCSVRadio.DUPLEX_MAP.get(v, v), "duplex"),
        "Operating Mode":    (str,   "mode"),
        "Name":              (str,   "name"),
        "Tone Mode":         (lambda v:
                              RTCSVRadio.TMODE_MAP.get(v, v), "tmode"),
        "CTCSS":             (lambda v:
                              float(v.split(" ")[0]), "rtone"),
        "DCS":               (int,   "dtcs"),
        "Skip":              (lambda v:
                              RTCSVRadio.SKIP_MAP.get(v, v), "skip"),
        "Step":              (lambda v:
                              float(v.split(" ")[0]), "tuning_step"),
        "Mask":              (lambda v:
                              RTCSVRadio.BOOL_MAP.get(v, v), "empty",),
        "Comment":           (str,   "comment"),
        }

    def _clean_duplex(self, headers, line, mem):
        if mem.duplex == "split":
            try:
                val = get_datum_by_header(headers, line, "Transmit Frequency")
                val = chirp_common.parse_freq(val)
                mem.offset = val
            except OmittedHeaderError:
                pass

        return mem

    def _clean_mode(self, headers, line, mem):
        if mem.mode == "FM":
            try:
                val = get_datum_by_header(headers, line, "Half Dev")
                if self.BOOL_MAP[val]:
                    mem.mode = "FMN"
            except OmittedHeaderError:
                pass

        return mem

    def _clean_ctone(self, headers, line, mem):
        # RT Systems only stores a single tone value
        mem.ctone = mem.rtone
        return mem

    @classmethod
    def match_model(cls, filedata, filename):
        """Match files ending in .csv and using RT Systems column names."""
        # RT Systems provides a different set of columns for each radio.
        # We attempt to match only the first few columns, hoping they are
        # consistent across radio models.
        try:
            filedata = filedata.decode()
        except UnicodeDecodeError:
            # CSV files are text
            return False
        return filename.lower().endswith("." + cls.FILE_EXTENSION) and \
            filedata.startswith("Channel Number,Receive Frequency,"
                                "Transmit Frequency,Offset Frequency,"
                                "Offset Direction,Operating Mode,"
                                "Name,Tone Mode,CTCSS,DCS")
