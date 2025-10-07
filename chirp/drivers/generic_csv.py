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

import io
import os
import csv
import logging

from chirp import chirp_common, errors, directory

LOG = logging.getLogger(__name__)
DEFAULT_POWER_LEVEL = chirp_common.AutoNamedPowerLevel(50)


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


def parse_cross_mode(value):
    if value not in chirp_common.CROSS_MODES:
        raise ValueError('Invalid cross mode %r' % value)
    return value


@directory.register
class CSVRadio(chirp_common.FileBackedRadio):
    """A driver for Generic CSV files"""
    VENDOR = "Generic"
    MODEL = "CSV"
    NEEDS_COMPAT_SERIAL = True
    FILE_EXTENSION = "csv"
    FORMATS = [directory.register_format('CSV', '*.csv')]
    SEPCHAR = ','

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
        "RxDtcsCode":    (int,   "rx_dtcs"),
        "CrossMode":     (parse_cross_mode, "cross_mode"),
        "Mode":          (str,   "mode"),
        "TStep":         (float, "tuning_step"),
        "Skip":          (str,   "skip"),
        "Power":         (chirp_common.parse_power, "power"),
        "Comment":       (str,   "comment"),
        }

    def _blank(self, setDefault=False, max_memory=999):
        self.errors = []
        self.memories = [chirp_common.Memory(i, True)
                         for i in range(0, max_memory + 1)]
        if (setDefault):
            self.memories[0].empty = False
            self.memories[0].freq = 146010000
            # Default to 50W
            self.memories[0].power = DEFAULT_POWER_LEVEL

    def clear(self):
        self.memories = []

    def __init__(self, pipe, max_memory=999):
        chirp_common.FileBackedRadio.__init__(self, None)
        self.memories = []
        self.file_has_rTone = None  # Set in load(), used in _clean_tmode()
        self.file_has_cTone = None

        # Persistence for comment lines
        # List of tuples of (previous_memory, comment)
        self._comments = []
        self._filename = pipe
        if self._filename and os.path.exists(self._filename):
            self.load()
        else:
            self._blank(True, max_memory=max_memory)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.requires_call_lists = False
        rf.has_implicit_calls = False
        rf.memory_bounds = (0, len(self.memories)-1)
        rf.has_infinite_number = True
        rf.has_nostep_tuning = True
        rf.has_comment = True
        rf.has_rx_dtcs = True
        rf.has_variable_power = True
        rf.can_odd_split = True

        rf.valid_modes = list(chirp_common.MODES)
        rf.valid_tmodes = list(chirp_common.TONE_MODES)
        rf.valid_cross_modes = list(chirp_common.CROSS_MODES)
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS)
        rf.valid_bands = [(1, 10000000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_characters = chirp_common.CHARSET_1252
        rf.valid_name_length = 999
        rf.valid_power_levels = [chirp_common.AutoNamedPowerLevel(0.1),
                                 DEFAULT_POWER_LEVEL,
                                 chirp_common.AutoNamedPowerLevel(1500)]

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
            except OmittedHeaderError:
                pass
            except Exception as e:
                raise Exception("[%s] %s" % (attr, e))

        if not mem.power:
            # Default power level to something if not set
            mem.power = DEFAULT_POWER_LEVEL

        return self._clean(headers, line, mem)

    def load_from(self, string):
        self._load(io.StringIO(string, newline=''))

    def load(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to load from")

        if filename:
            self._filename = filename

        self._blank()

        with open(self._filename, newline='', encoding='utf-8-sig') as f:
            return self._load(f)

    def _load(self, f):
        reader = csv.reader(f, delimiter=self.SEPCHAR, quotechar='"')

        self._comments = []
        good = 0
        lineno = 0
        last_number = -1
        for line in reader:
            # Skip (but stash) comment lines that start with #
            if line and line[0].startswith('#'):
                self._comments.append((last_number, ' '.join(line)))
                continue
            lineno += 1
            if lineno == 1:
                header = line
                for field in header:
                    # Log unknown header names for the UI to capture and expose
                    if field not in chirp_common.Memory.CSV_FORMAT:
                        LOG.error('Header line has unknown field %r' % field)
                self.file_has_rTone = "rToneFreq" in header
                self.file_has_cTone = "cToneFreq" in header
                continue

            # Spreadsheets like to omit trailing empty columns in TSV
            if len(header) > len(line) and not self.SEPCHAR.isspace():
                LOG.error("Line %i has %i columns, expected %i",
                          lineno, len(line), len(header))
                self.errors.append("Column number mismatch on line %i" %
                                   lineno)
                continue

            try:
                mem = self._parse_csv_data_line(header, line)
                if mem is None or mem.freq == 0:
                    LOG.debug('Line %i did not contain a valid memory',
                              lineno)
                    continue
                if mem.number is None:
                    raise Exception("Invalid Location field" % lineno)
            except Exception as e:
                LOG.error("Line %i: %s", lineno, e)
                self.errors.append("Line %i: %s" % (lineno, e))
                continue

            last_number = mem.number
            self._grow(mem.number)
            self.memories[mem.number] = mem
            good += 1

        if not good:
            raise errors.InvalidDataError("No channels found")

    def save(self, filename=None):
        if filename is None and self._filename is None:
            raise errors.RadioError("Need a location to save to")

        if filename:
            self._filename = filename

        with open(self._filename, "w", newline='', encoding='utf-8') as f:
            self._write_to(f)

    def _write_to(self, f):
        comments = list(self._comments)
        writer = csv.writer(f, delimiter=self.SEPCHAR)

        for index, comment in comments[:]:
            if index >= 0:
                break
            writer.writerow([comment])
            comments.pop(0)

        writer.writerow(chirp_common.Memory.CSV_FORMAT)

        for mem in self.memories:
            for index, comment in comments[:]:
                if index >= mem.number:
                    break
                writer.writerow([comment])
                comments.pop(0)
            write_memory(writer, mem)

    def as_string(self):
        string = io.StringIO(newline='')
        self._write_to(string)
        return string.getvalue()

    # MMAP compatibility
    def save_mmap(self, filename):
        return self.save(filename)

    def load_mmap(self, filename):
        return self.load(filename)

    def get_memories(self, lo=0, hi=999):
        return [x for x in self.memories if x.number >= lo and x.number <= hi]

    def get_memory(self, number):
        try:
            return self.memories[number].dupe()
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
        newmem = newmem.dupe()
        if newmem.power is None:
            newmem.power = DEFAULT_POWER_LEVEL
        else:
            # Accept any power level because we are CSV, but convert it to
            # the class that will str() into our desired format.
            newmem.power = chirp_common.AutoNamedPowerLevel(
                chirp_common.dBm_to_watts(float(newmem.power)))
        self._grow(newmem.number)
        self.memories[newmem.number] = newmem
        self.memories[newmem.number].name = newmem.name.rstrip()

    def erase_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        mem.empty = True
        self.memories[number] = mem

    def get_raw_memory(self, number):
        return ",".join(chirp_common.Memory.CSV_FORMAT) + \
            os.linesep + \
            self.SEPCHAR.join(self.memories[number].to_csv())

    @classmethod
    def match_model(cls, filedata, filename):
        """Match files ending in .CSV"""
        try:
            filedata = filedata.decode()
        except UnicodeDecodeError:
            # CSV files are text
            return False
        return filename.lower().endswith("." + cls.FILE_EXTENSION) and \
            (find_csv_header(filedata) or filedata == "")


def find_csv_header(filedata):
    if filedata.startswith('\ufeff') or filedata.startswith('\ufffe'):
        # Skip BOM
        filedata = filedata[1:]
    while filedata.startswith('#'):
        filedata = filedata[filedata.find('\n') + 1:]
    delims = ['', '"', "'"]
    return any([filedata.startswith('%sLocation%s,' % (d, d))
                for d in delims])


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
            filedata.startswith(b"Name,RX Freq,TX Freq,Decode,Encode,TX Pwr,"
                                b"Scan,TX Dev,Busy Lck,Group/Notes") or \
            filedata.startswith(b'"#","Name","RX Freq","TX Freq","Decode",'
                                b'"Encode","TX Pwr","Scan","TX Dev",'
                                b'"Busy Lck","Group/Notes"')


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
        "Scan":   "",
        }

    TMODE_MAP = {
        "None":     "",
        "T Sql":    "TSQL",
    }

    BOOL_MAP = {
        "Off":  False,
        "On":   True,
    }

    MODE_MAP = {
        'FM Narrow': 'NFM',
    }

    ATTR_MAP = {
        "Channel Number":    (int,   "number"),
        "Receive Frequency": (chirp_common.parse_freq, "freq"),
        "Offset Frequency":  (chirp_common.parse_freq, "offset"),
        "Offset Direction":  (lambda v:
                              RTCSVRadio.DUPLEX_MAP.get(v, v), "duplex"),
        "Operating Mode":    (lambda v: RTCSVRadio.MODE_MAP.get(v, v), 'mode'),
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

    def __init__(self, pipe):
        self._last_loaded = 0
        super().__init__(pipe)

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

    def _clean_number(self, headers, line, mem):
        if 'Channel Number' not in headers and self.memories:
            # Some RTSystems software generates this with an empty header name?
            self._last_loaded += 1
            mem.number = self._last_loaded
            LOG.debug('No location column, calculated %i from %r',
                      mem.number, self.memories[-1])
        return mem

    def _parse_csv_data_line(self, headers, line):
        val = get_datum_by_header(headers, line, "Receive Frequency")
        if not val.strip():
            return
        return super()._parse_csv_data_line(headers, line)

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

        try:
            firstline, rest = filedata.split('\n', 1)
            firstline_fields = firstline.split(',')
        except Exception as e:
            LOG.warning('Failed to detect file as RTCSV: %s', e)
            return False

        return filename.lower().endswith("." + cls.FILE_EXTENSION) and \
            'Receive Frequency' in firstline_fields


class TSVRadio(CSVRadio):
    SEPCHAR = '\t'
