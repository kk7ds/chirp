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
import inspect
import logging
import math
import re
import sys

from chirp import errors, memmap, CHIRP_VERSION

LOG = logging.getLogger(__name__)

SEPCHAR = ","

# 50 Tones
TONES = (
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5,
    85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5,
    107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
    131.8, 136.5, 141.3, 146.2, 151.4, 156.7,
    159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
    177.3, 179.9, 183.5, 186.2, 189.9, 192.8,
    196.6, 199.5, 203.5, 206.5, 210.7, 218.1,
    225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
)

OLD_TONES = tuple(x for x in sorted(
    set(TONES) - set([159.8, 165.5, 171.3, 177.3, 183.5, 189.9,
                      196.6, 199.5, 206.5, 229.1, 254.1])))


def VALIDTONE(v):
    return isinstance(v, float) and 50 < v < 300


# 104 DTCS Codes
DTCS_CODES = (
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
)

# 512 Possible DTCS Codes
ALL_DTCS_CODES = tuple([((a * 100) + (b * 10) + c)
                        for a in range(0, 8)
                        for b in range(0, 8)
                        for c in range(0, 8)])

CROSS_MODES = (
    "Tone->Tone",
    "DTCS->",
    "->DTCS",
    "Tone->DTCS",
    "DTCS->Tone",
    "->Tone",
    "DTCS->DTCS",
    "Tone->"
)

# This is the "master" list of modes, and in general things should not be
# added here without significant consideration. These must remain stable and
# universal to allow importing memories between different radio vendors and
# models.
MODES = ("WFM", "FM", "NFM", "AM", "NAM", "DV", "USB", "LSB", "CW", "RTTY",
         "DIG", "PKT", "NCW", "NCWR", "CWR", "P25", "Auto", "RTTYR",
         "FSK", "FSKR", "DMR", "DN")

TONE_MODES = (
    "",
    "Tone",
    "TSQL",
    "DTCS",
    "DTCS-R",
    "TSQL-R",
    "Cross",
)

TUNING_STEPS = (
    5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0,
    125.0, 200.0,
    # Need to fix drivers using this list as an index!
    9.0, 1.0, 2.5,
)

# These are the default for RadioFeatures.valid_tuning_steps
COMMON_TUNING_STEPS = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0)

SKIP_VALUES = ("", "S", "P")

CHARSET_UPPER_NUMERIC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ 1234567890"
CHARSET_ALPHANUMERIC = \
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz 1234567890"
CHARSET_ASCII = "".join([chr(x) for x in range(ord(" "), ord("~") + 1)])
CHARSET_1252 = bytes(
    [x for x in range(0x20, 0x100)
     if x not in [0x7F, 0x81, 0x8D, 0x8F, 0x90, 0x9D, 0xA0, 0xAD]]
).decode('cp1252')

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
    return 10 * math.log10(watts) + 30


def dBm_to_watts(dBm):
    """Converts @dBm from dBm to watts"""
    return round(math.pow(10, dBm / 10) / 1000, 1)


class PowerLevel:
    """Represents a power level supported by a radio"""

    def __init__(self, label, watts=0, dBm=0):
        if watts:
            dBm = watts_to_dBm(watts)
        self._power = float(dBm)
        self._label = label

    def __str__(self):
        return str(self._label)

    def __int__(self):
        return int(self._power)

    def __float__(self):
        return self._power

    def __sub__(self, val):
        return float(self) - float(val)

    def __add__(self, val):
        return float(self) + float(val)

    def __eq__(self, val):
        if val is not None:
            return float(self) == float(val)
        return False

    def __lt__(self, val):
        return float(self) < float(val)

    def __gt__(self, val):
        return float(self) > float(val)

    def __bool__(self):
        return int(self) != 0

    def __repr__(self):
        return "%s (%i dBm)" % (self._label, self._power)


class AutoNamedPowerLevel(PowerLevel):
    """A power level that is simply named by its value in watts"""

    def __init__(self, watts):
        fmt = ('%iW' if watts >= 10 else '%.1fW')
        super().__init__(fmt % watts, watts=watts)


def parse_power(powerstr):
    if powerstr.isdigit():
        # All digits means watts
        watts = int(powerstr)
    else:
        match = re.match(r'^\s*([0-9.]+)\s*([Ww]?)\s*$', powerstr)
        if not match:
            raise ValueError('Invalid power specification: %r' % powerstr)
        if match.group(2).lower() in ('', 'w'):
            watts = float(match.group(1))
        else:
            raise ValueError('Unknown power units in %r' % powerstr)

    return AutoNamedPowerLevel(watts)


def parse_freq(freqstr: str) -> int:
    """Parse a frequency string and return the value in integral Hz"""
    freqstr = freqstr.strip()
    if freqstr == "":
        return 0
    elif freqstr.endswith(" MHz"):
        return parse_freq(freqstr.split(" ")[0])
    elif freqstr.endswith(" kHz"):
        return int(freqstr.split(" ")[0]) * 1000

    if "." in freqstr:
        _mhz, _khz = freqstr.split(".")
        if _mhz == "":
            _mhz = "0"
        _khz = _khz.ljust(6, "0")
        if len(_khz) > 6:
            raise ValueError("Invalid kHz value: %s", _khz)
        mhz = int(_mhz) * 1000000
        khz = int(_khz)
    else:
        mhz = int(freqstr) * 1000000
        khz = 0

    return mhz + khz


def format_freq(freq: int) -> str:
    """Format a frequency given in Hz as a string"""

    return "%i.%06i" % (freq / 1000000, freq % 1000000)


class ImmutableValueError(ValueError):
    pass


class Memory:
    """Base class for a single radio memory"""
    freq: int = 0
    number: int = 0
    extd_number: str = ""
    name: str = ""
    vfo: int = 0
    rtone: float = 88.5
    ctone: float = 88.5
    dtcs: int = 23
    rx_dtcs: int = 23
    tmode: str = ""
    cross_mode: str = "Tone->Tone"
    dtcs_polarity: str = "NN"
    skip: str = ""
    power: PowerLevel | None = None
    duplex: str = ""
    offset: int = 600000
    mode: str = "FM"
    tuning_step: float = 5.0

    comment: str = ""

    empty: bool = False

    immutable: list[str] = []

    # A RadioSettingGroup of additional settings supported by the radio,
    # or an empty list if none
    extra = []

    def __init__(self, number=0, empty=False, name=""):
        self.freq = 0
        self.number = number
        self.extd_number = ""
        self.name = name
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

        self.empty = empty

        self.immutable = []

    _valid_map = {
        "rtone":          VALIDTONE,
        "ctone":          VALIDTONE,
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
        ident, vals = self.debug_dump()
        return '<Memory %s: %s>' % (
            ident, ','.join('%s=%r' % item for item in vals))

    def debug_diff(self, other, delim='/'):
        my_ident, my_vals = self.debug_dump()
        my_vals = dict(my_vals)

        om_ident, om_vals = other.debug_dump()
        om_vals = dict(om_vals)

        diffs = []
        if my_ident != om_ident:
            diffs.append('ident=%s%s%s' % (my_ident, delim, om_ident))
        for k in sorted(my_vals.keys() | om_vals.keys()):
            myval = my_vals.get(k, '<missing>')
            omval = om_vals.get(k, '<missing>')
            if myval != omval:
                diffs.append('%s=%r%s%r' % (k, myval, delim, omval))
        return ','.join(diffs)

    def debug_dump(self):
        vals = [(k, v) for k, v in self.__dict__.items()
                if k not in ('extra', 'number', 'extd_number')]
        for extra in self.extra:
            vals.append(('extra.%s' % extra.get_name(), str(extra.value)))
        if self.extd_number:
            ident = '%s(%i)' % (self.extd_number, self.number)
        else:
            ident = str(self.number)
        return ident, vals

    def dupe(self):
        """Return a deep copy of @self"""
        mem = self.__class__()
        for k, v in list(self.__dict__.items()):
            mem.__dict__[k] = v

        return mem

    def clone(self, source):
        """Absorb all of the properties of @source"""
        for k, v in list(source.__dict__.items()):
            self.__dict__[k] = v

    CSV_FORMAT = ["Location", "Name", "Frequency",
                  "Duplex", "Offset", "Tone",
                  "rToneFreq", "cToneFreq", "DtcsCode",
                  "DtcsPolarity", "RxDtcsCode",
                  "CrossMode",
                  "Mode", "TStep",
                  "Skip", "Power", "Comment",
                  "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE"]

    def __setattr__(self, name, val):
        if not hasattr(self, name):
            raise ValueError("No such attribute `%s'" % name)

        if name in self.immutable:
            raise ImmutableValueError("Field %s is not " % name +
                                      "mutable on this memory")

        if name in self._valid_map:
            valid = self._valid_map[name]
            if callable(valid):
                if not valid(val):
                    raise ValueError("`%s' is not a valid value for `%s'" % (
                        val, name))
            elif val not in self._valid_map[name]:
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
            "%03i" % self.rx_dtcs,
            "%s" % self.cross_mode,
            "%s" % self.mode,
            "%.2f" % self.tuning_step,
            "%s" % self.skip,
            "%s" % self.power,
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
        except Exception:
            raise errors.InvalidDataError(
                "Location '%s' is not a valid integer" % vals[0])

        self.name = vals[1]

        try:
            self.freq = to_MHz(float(vals[2]))
        except Exception:
            raise errors.InvalidDataError("Frequency is not a valid number")

        if vals[3].strip() in ["+", "-", ""]:
            self.duplex = vals[3].strip()
        else:
            raise errors.InvalidDataError("Duplex is not +,-, or empty")

        try:
            self.offset = to_MHz(float(vals[4]))
        except Exception:
            raise errors.InvalidDataError("Offset is not a valid number")

        self.tmode = vals[5]
        if self.tmode not in TONE_MODES:
            raise errors.InvalidDataError("Invalid tone mode `%s'" %
                                          self.tmode)

        try:
            self.rtone = float(vals[6])
        except Exception:
            raise errors.InvalidDataError("rTone is not a valid number")
        if self.rtone not in TONES:
            raise errors.InvalidDataError("rTone is not valid")

        try:
            self.ctone = float(vals[7])
        except Exception:
            raise errors.InvalidDataError("cTone is not a valid number")
        if self.ctone not in TONES:
            raise errors.InvalidDataError("cTone is not valid")

        try:
            self.dtcs = int(vals[8], 10)
        except Exception:
            raise errors.InvalidDataError("DTCS code is not a valid number")
        if self.dtcs not in DTCS_CODES:
            raise errors.InvalidDataError("DTCS code is not valid")

        if vals[9] in ["NN", "NR", "RN", "RR"]:
            self.dtcs_polarity = vals[9]
        else:
            raise errors.InvalidDataError("DtcsPolarity is not valid")

        try:
            self.rx_dtcs = int(vals[10], 10)
        except Exception:
            raise errors.InvalidDataError("DTCS Rx code is not a valid number")
        if self.rx_dtcs not in DTCS_CODES:
            raise errors.InvalidDataError("DTCS Rx code is not valid")

        self.cross_mode = vals[11]

        if vals[12] in MODES:
            self.mode = vals[12]
        else:
            raise errors.InvalidDataError("Mode %r is not valid" % vals[10])

        try:
            self.tuning_step = float(vals[13])
        except Exception:
            raise errors.InvalidDataError("Tuning step is invalid")

        try:
            self.skip = vals[14]
        except Exception:
            raise errors.InvalidDataError("Skip value is not valid")

        return True


class DVMemory(Memory):
    """A Memory with D-STAR attributes"""
    dv_urcall: str = "CQCQCQ"
    dv_rpt1call: str = ""
    dv_rpt2call: str = ""
    dv_code: int = 0

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


def FrozenMemory(source):
    class _FrozenMemory(source.__class__):
        def __init__(self, source):
            self.__dict__['_frozen'] = False
            for k, v in source.__dict__.items():
                if k == '_frozen':
                    continue
                setattr(self, k, v)

            self.__dict__['_frozen'] = True
            for i in self.extra:
                i.set_frozen()

        def __setattr__(self, k, v):
            if self._frozen:
                # This should really be an error, but we have a number of
                # drivers that make modifications during set_memory(). So this
                # just has to be a warning for now. Later it could turn into
                # a TypeError.
                caller = inspect.getframeinfo(inspect.stack()[1][0])
                LOG.warning(
                    '%s@%i: Illegal set on attribute %s - Fix this driver!' % (
                        caller.filename, caller.lineno, k))
            super().__setattr__(k, v)

        def dupe(self):
            m = Memory()
            m.clone(self)
            delattr(m, '_frozen')
            return m

    return _FrozenMemory(source)


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


class StaticBank(Bank):
    pass


class StaticBankModel(BankModel):
    MSG = 'This radio has fixed banks and does not allow reassignment'
    channelAlwaysHasBank = True

    """A BankModel that shows a static mapping but does not allow changes."""

    def __init__(self, radio, name='Banks', banks=10):
        super().__init__(radio, name=name)
        self._num_banks = banks
        self._rf = radio.get_features()
        self._banks = []
        for i in range(self._num_banks):
            self._banks.append(StaticBank(self, i + 1, 'Bank'))

    def get_num_mappings(self):
        return self._num_banks

    def get_mappings(self):
        return self._banks

    def get_mapping_memories(self, bank):
        lo, hi = self._rf.memory_bounds
        count = (hi - lo + 1) / self._num_banks
        offset = lo + ((bank.get_index() - 1) * count)
        return [self._radio.get_memory(offset + i) for i in range(count)]

    def get_memory_mappings(self, memory):
        lo, hi = self._rf.memory_bounds
        mems = hi - lo + 1
        count = mems // self._num_banks
        return [self._banks[(memory.number - lo) // count]]

    def remove_memory_from_mapping(self, memory, mapping):
        raise errors.RadioFixedBanks()

    def add_memory_to_mapping(self, memory, mapping):
        raise errors.RadioFixedBanks()


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


def BOOLEAN(v):
    assert v in (True, False)


def LIST(v):
    assert hasattr(v, '__iter__')


def LIST_NONZERO_INT(v):
    assert all(x > 0 for x in v)


def INT(min=0, max=None):
    def checkint(v):
        assert isinstance(v, int)
        assert v >= min
        if max is not None:
            assert v <= max

    return checkint


def STRING(v):
    assert isinstance(v, str)


def NTUPLE(size):
    def checktuple(v):
        assert len(v) == size

    return checktuple


def TONELIST(v):
    assert all(VALIDTONE(x) for x in v)


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
        "has_variable_power":   BOOLEAN,
        "has_dynamic_subdevices": BOOLEAN,

        # Attributes
        "valid_modes":          LIST,
        "valid_tmodes":         LIST,
        "valid_duplexes":       LIST,
        "valid_tuning_steps":   LIST_NONZERO_INT,
        "valid_bands":          LIST,
        "valid_skips":          LIST,
        "valid_power_levels":   LIST,
        "valid_characters":     STRING,
        "valid_name_length":    INT(),
        "valid_cross_modes":    LIST,
        "valid_tones":          TONELIST,
        "valid_dtcs_pols":      LIST,
        "valid_dtcs_codes":     LIST,
        "valid_special_chans":  LIST,

        "has_sub_devices":      BOOLEAN,
        "memory_bounds":        NTUPLE(2),
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
        elif name not in list(self._valid_map.keys()):
            raise ValueError("No such attribute `%s'" % name)

        try:
            self._valid_map[name](val)
        except AssertionError:
            raise ValueError('Invalid value %r for attribute %r' % (
                val, name))

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
        self.init("has_variable_power", False,
                  "Indicates the radio supports any power level between the "
                  "min and max in valid_power_levels")
        self.init("has_dynamic_subdevices", False,
                  "Indicates the radio has a non-static list of subdevices")

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
        self.init("valid_tones", list(TONES),
                  "Support Tones")
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
        return name in list(self._valid_map.keys())

    def __getitem__(self, name):
        return self.__dict__[name]

    def validate_memory(self, mem):
        """Return a list of warnings and errors that will be encountered
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
                'mode' not in mem.immutable and
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

        if self.valid_tones and mem.rtone not in self.valid_tones:
            msg = ValidationError("Tone %.1f not supported" % mem.rtone)
            msgs.append(msg)
        if self.valid_tones and mem.ctone not in self.valid_tones:
            msg = ValidationError("Tone %.1f not supported" % mem.ctone)
            msgs.append(msg)

        if self.has_dtcs_polarity and \
                mem.dtcs_polarity not in self.valid_dtcs_pols:
            msg = ValidationError("DTCS Polarity %s not supported" %
                                  mem.dtcs_polarity)
            msgs.append(msg)

        if self.valid_dtcs_codes and \
                mem.dtcs not in self.valid_dtcs_codes:
            msg = ValidationError("DTCS Code %03i not supported" % mem.dtcs)
            msgs.append(msg)
        if self.valid_dtcs_codes and \
                mem.rx_dtcs not in self.valid_dtcs_codes:
            msg = ValidationError("DTCS Code %03i not supported" % mem.rx_dtcs)
            msgs.append(msg)

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

        if mem.power and self.valid_power_levels:
            if self.has_variable_power:
                if (mem.power < min(self.valid_power_levels) or
                        mem.power > max(self.valid_power_levels)):
                    msg = ValidationWarning(
                        "Power level %s is out of radio's range" % mem.power)
                    msgs.append(msg)
            else:
                if mem.power not in self.valid_power_levels:
                    msg = ValidationWarning(
                        "Power level %s not supported" % mem.power)
                    msgs.append(msg)

        if self.valid_tuning_steps and not self.has_nostep_tuning:
            try:
                required_step(mem.freq, self.valid_tuning_steps)
            except errors.InvalidDataError as e:
                msgs.append(ValidationError(e))

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


def split_validation_msgs(msgs):
    """Split a list of msgs into warnings,errors"""
    return ([x for x in msgs if isinstance(x, ValidationWarning)],
            [x for x in msgs if isinstance(x, ValidationError)])


class Alias(object):
    VENDOR = "Unknown"
    MODEL = "Unknown"
    VARIANT = ""


class Radio(Alias):
    """Base class for all Radio drivers"""
    BAUD_RATE = 9600
    # Whether or not we should use RTS/CTS flow control
    HARDWARE_FLOW = False
    # Whether or not we should assert DTR when opening the serial port
    WANTS_DTR = True
    # Whether or not we should assert RTS when opening the serial port
    WANTS_RTS = True
    ALIASES = []
    NEEDS_COMPAT_SERIAL = False
    FORMATS: list[str] = []

    def status_fn(self, status):
        """Deliver @status to the UI"""
        console_status(status)

    def __init__(self, pipe):
        self.errors = []
        self.pipe = pipe

    def get_features(self) -> RadioFeatures:
        """Return a RadioFeatures object for this radio"""
        return RadioFeatures()

    @classmethod
    def get_name(cls) -> str:
        """Return a printable name for this radio"""
        return "%s %s" % (cls.VENDOR, cls.MODEL)

    @classmethod
    def get_prompts(cls) -> RadioPrompts:
        """Return a set of strings for use in prompts"""
        return RadioPrompts()

    def set_pipe(self, pipe) -> None:
        """Set the serial object to be used for communications"""
        self.pipe = pipe

    def get_memory(self, number: int | str) -> Memory:
        """Return a Memory object for the memory at location @number

        Constructs and returns a generic Memory object for the given location
        in the radio's memory. The memory should accurately represent what is
        actually stored in the radio as closely as possible. If the radio
        does not support changing some attributes of the location in question,
        the Memory.immutable list should be set appropriately.

        NB: No changes to the radio's memory should occur as a result of
        calling get_memory().
        """
        raise NotImplementedError()

    def erase_memory(self, number: int | str) -> None:
        """Erase memory at location @number"""
        mem = Memory()
        if isinstance(number, str):
            mem.extd_number = number
        else:
            mem.number = number
        mem.empty = True
        self.set_memory(mem)

    def get_memories(self, lo=None, hi=None):
        """Get all the memories between @lo and @hi"""
        pass

    def set_memory(self, memory: Memory) -> None:
        """Set the memory object @memory

        This method should copy generic attributes from @memory to the
        radio's memory. It should not modify @memory and it should reproduce
        the generic attributes on @memory in the radio's memory as faithfully
        as the radio allows. Attributes that can't be copied exactly should
        be warned in validate_memory() with ValidationWarnings if a
        substitution will be made, or ValidationError if truly incompatible.
        In the latter case, set_memory() will not be called.
        """
        raise NotImplementedError()

    def get_mapping_models(self):
        """Returns a list of MappingModel objects (or an empty list)"""
        if hasattr(self, "get_bank_model"):
            # FIXME: Backwards compatibility for old bank models
            bank_model = self.get_bank_model()
            if bank_model:
                return [bank_model]
        return []

    def get_raw_memory(self, number: int | str) -> str:
        """Return a raw string describing the memory at @number"""
        return 'Memory<%r>' % number

    def filter_name(self, name: str) -> str:
        """Filter @name to just the length and characters supported"""
        rf = self.get_features()
        if rf.valid_characters == rf.valid_characters.upper():
            # Radio only supports uppercase, so help out here
            name = name.upper()
        return "".join([x for x in name[:rf.valid_name_length]
                        if x in rf.valid_characters])

    def get_sub_devices(self) -> list[Alias]:
        """Return a list of sub-device Radio objects, if
        RadioFeatures.has_sub_devices is True"""
        return []

    def validate_memory(self, mem: Memory) -> list[ValidationMessage]:
        """Return a list of warnings and errors that will be encountered
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

    @classmethod
    def supports_format(cls, fmt: str) -> bool:
        """Returns true if file format @fmt is supported by this radio.

        This really should not be overridden by implementations
        without a good reason (like excluding one).
        """
        return fmt in cls.FORMATS

    def check_set_memory_immutable_policy(self, existing: Memory, new: Memory):
        """Checks whether or not a new memory will violate policy.

        Some radios have complex requirements for which fields of which
        memories can be modified at any given point. For the most part, radios
        require certain physical memory slots to have immutable fields
        (such as labels on call channels), and this default implementation
        checks that policy. However, other radios have more fine-grained
        rules in order to comply with FCC type acceptance, which requires
        overriding this behavior.

        ** This should almost never be overridden in your driver.

        ** This must not communicate with the radio, if implemented on a live-
           mode driver.
        """
        for field in existing.immutable:
            if getattr(existing, field) != getattr(new, field):
                raise ImmutableValueError(
                    'Field %s is not mutable on this memory' % field)


class ExternalMemoryProperties:
    """A mixin class that provides external memory property support.

    This is for use by drivers that have some way of storing additional
    memory properties externally (i.e. in metadata or a separate region)
    that cannot be loaded/updated during get_memory()/set_memory().
    Implementing this is much less ideal than supporting those properties
    directly, so this should only be used when absolutely necessary.
    """

    def get_memory_extra(self, memory):
        """Update @memory with extra fields.

        This is called after get_memory() and is passed the result
        for augmentation from external storage.
        """
        return memory

    def set_memory_extra(self, memory):
        """Update external storage of properties from @memory.

        This is called after set_memory() with the same memory object
        to record additional properties in external storage.
        """
        pass

    def erase_memory_extra(self, number):
        """Erase external storage for @memory.

        This is called after erase_memory() to clear external storage
        for memory @number.
        """
        pass

    def link_device_metadata(self, devices):
        """Link sub-device metadata with parent.

        This is called after get_sub_devices() to make sure that the
        sub-device instances use a reference into the main radio's
        metadata. In most cases, this does not need to be overridden.
        """
        # Link metadata of the sub-devices into the main by variant name
        # so that they are both included in a later save of the parent.
        for sub in devices:
            self._metadata.setdefault(sub.VARIANT, {})
            sub._metadata = self._metadata[sub.VARIANT]


class FileBackedRadio(Radio):
    """A file-backed radio stores its data in a file"""
    FILE_EXTENSION = 'dat'

    def save(self, filename):
        """Save the radio's memory map to @filename"""
        pass

    def load(self, filename):
        """Load the radio's memory map object from @filename"""
        pass


def class_detected_models_attribute(cls):
    return 'DETECTED_MODELS_%s' % cls.__name__


class DetectableInterface:
    @classmethod
    def detect_from_serial(cls, pipe):
        """Communicate with the radio via serial to determine proper class

        Returns an in implementation of CloneModeRadio if detected, or raises
        RadioError if not. If NotImplemented is raised, we assume that no
        detection is possible or necessary.
        """
        detected = getattr(cls, class_detected_models_attribute(cls), None)
        assert detected is None, (
            'Class has detected models but no detect_from_serial() '
            'implementation')
        raise NotImplementedError()

    @classmethod
    def detected_models(cls, include_self=True):
        detected = getattr(cls, class_detected_models_attribute(cls), [])
        # Only include this class if it is registered
        if include_self and hasattr(cls, '_DETECTED_BY'):
            extra = [cls]
        else:
            extra = []
        return extra + list(detected)

    @classmethod
    def detect_model(cls, detected_cls):
        detected_attr = class_detected_models_attribute(cls)
        if getattr(cls, detected_attr, None) is None:
            setattr(cls, detected_attr, [])
        getattr(cls, detected_attr).append(detected_cls)


class CloneModeRadio(FileBackedRadio, ExternalMemoryProperties,
                     DetectableInterface):
    """A clone-mode radio does a full memory dump in and out and we store
    an image of the radio into an image file"""
    FILE_EXTENSION = "img"
    MAGIC = b'\x00\xffchirp\xeeimg\x00\x01'

    _memsize = 0

    def __init__(self, pipe):
        self.errors = []
        self._mmap = None
        self._memobj = None
        self._metadata = {}

        if isinstance(pipe, str):
            self.pipe = None
            self.load_mmap(pipe)
        elif isinstance(pipe, memmap.MemoryMapBytes):
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
        return cls._memsize and len(filedata) == cls._memsize

    def sync_in(self):
        """Initiate a radio-to-PC clone operation"""
        pass

    def sync_out(self):
        """Initiate a PC-to-radio clone operation"""
        pass

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
            metadata = json.loads(base64.b64decode(raw_metadata).decode())
        except ValueError as e:
            LOG.error('Failed to parse decoded metadata blob: %s' % e)
        except TypeError as e:
            LOG.error('Failed to decode metadata blob: %s' % e)

        if metadata:
            LOG.debug('Loaded metadata: %s' % metadata)

        return raw_data[:idx], metadata

    def _make_metadata(self):
        # Always generate these directly from our in-memory state
        base = {
            'rclass': self.__class__.__name__,
            'vendor': self.VENDOR,
            'model': self.MODEL,
            'variant': self.VARIANT,
            'chirp_version': CHIRP_VERSION,
        }

        # Any other properties take a back seat to the above
        extra = {k: v for k, v in self._metadata.items() if k not in base}
        extra.update(base)

        return base64.b64encode(json.dumps(extra).encode())

    def load_mmap(self, filename):
        """Load the radio's memory map from @filename"""
        mapfile = open(filename, "rb")
        data = mapfile.read()
        if self.MAGIC in data:
            data, self._metadata = self._strip_metadata(data)
            if ('chirp_version' in self._metadata and
                    is_version_newer(self._metadata.get('chirp_version'))):
                LOG.warning('Image is from version %s but we are %s' % (
                    self._metadata.get('chirp_version'), CHIRP_VERSION))
        if self.NEEDS_COMPAT_SERIAL:
            self._mmap = memmap.MemoryMap(data)
        else:
            self._mmap = memmap.MemoryMapBytes(bytes(data))
        mapfile.close()
        self.process_mmap()

    def save_mmap(self, filename):
        """
        try to open a file and write to it
        If IOError raise a File Access Error Exception
        """
        try:
            mapfile = open(filename, "wb")
            mapfile.write(self._mmap.get_byte_compatible().get_packed())
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
    def metadata(self, values):
        self._metadata.update(values)

    def get_memory_extra(self, memory):
        rf = self.get_features()
        if not rf.has_comment and isinstance(memory.number, int):
            self._metadata.setdefault('mem_extra', {})
            try:
                memory.comment = self._metadata['mem_extra'].get(
                    '%04i_comment' % memory.number, '')
            except ImmutableValueError:
                pass
        return memory

    def set_memory_extra(self, memory):
        rf = self.get_features()
        if not rf.has_comment and isinstance(memory.number, int):
            self._metadata.setdefault('mem_extra', {})
            key = '%04i_comment' % memory.number
            if not memory.comment:
                self._metadata['mem_extra'].pop(key, None)
            else:
                self._metadata['mem_extra'][key] = memory.comment

    def erase_memory_extra(self, number):
        rf = self.get_features()
        if not rf.has_comment and isinstance(number, int):
            self._metadata.setdefault('mem_extra', {})
            self._metadata['mem_extra'].pop('%04i_comment' % number, None)


class LiveRadio(Radio, DetectableInterface):
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
            nticks = int(pct) // 10
            ticks = "=" * nticks
        except ValueError:
            pct = 0.0
            ticks = "?" * 10

        return "|%-10s| %2.1f%% %s" % (ticks, pct, self.msg)


def is_fractional_step(freq):
    """Returns True if @freq requires a 12.5 kHz or 6.25 kHz step"""
    return not is_5_0(freq) and (is_12_5(freq) or is_6_25(freq))


def is_5_0(freq):
    """Returns True if @freq is reachable by a 5 kHz step"""
    return (freq % 5000) == 0


def is_10_0(freq):
    """Returns True if @freq is reachable by a 10 kHz step"""
    return (freq % 10000) == 0


def is_12_5(freq):
    """Returns True if @freq is reachable by a 12.5 kHz step"""
    return (freq % 12500) == 0


def is_6_25(freq):
    """Returns True if @freq is reachable by a 6.25 kHz step"""
    return (freq % 6250) == 0


def is_2_5(freq):
    """Returns True if @freq is reachable by a 2.5 kHz step"""
    return (freq % 2500) == 0


def is_8_33(freq):
    """Returns True if @freq is reachable by a 8.33 kHz step"""
    return (freq % 25000) in [0, 8330, 16660]


def is_1_0(freq):
    """Returns True if @freq is reachable by a 1.0 kHz step"""
    return (freq % 1000) == 0


def is_0_5(freq):
    """Returns True if @freq is reachable by a 0.5 kHz step"""
    return (freq % 500) == 0


def make_is(stephz):
    def validator(freq):
        return freq % stephz == 0
    return validator


def required_step(freq, allowed=None):
    """Returns the simplest tuning step that is required to reach @freq"""
    if allowed is None:
        allowed = [5.0, 10.0, 12.5, 6.25, 2.5, 1.0, 0.5, 8.33, 0.25]

    special = {8.33: is_8_33}
    for step in allowed:
        if step in special:
            validate = special[step]
        else:
            validate = make_is(int(step * 1000))
        if validate(freq):
            LOG.debug('Chose step %s for %s' % (step, format_freq(freq)))
            return step

    raise errors.InvalidDataError("Unable to find a supported " +
                                  "tuning step for %s" % format_freq(freq))


def fix_rounded_step(freq):
    """Some radios imply the last bit of 12.5 kHz and 6.25 kHz step
    frequencies. Take the base @freq and return the corrected one"""
    allowed = [12.5, 6.25]

    try:
        required_step(freq + 500, allowed=allowed)
        return freq + 500
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 250, allowed=allowed)
        return freq + 250
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 750, allowed=allowed)
        return float(freq + 750)
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 330, allowed=allowed)
        return float(freq + 330)
    except errors.InvalidDataError:
        pass

    try:
        required_step(freq + 660, allowed=allowed)
        return float(freq + 660)
    except errors.InvalidDataError:
        pass

    # These radios can all resolve 5kHz, so make sure what we are left with
    # is 5kHz-aligned, else we refuse below.
    try:
        required_step(freq, allowed=[5.0])
        return freq
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
    return val // 100000000


def from_MHz(val):
    """Convert @val in Hz to MHz"""
    return val // 100000


def from_kHz(val):
    """Convert @val in Hz to kHz"""
    return val // 100


def split_to_offset(mem, rxfreq, txfreq):
    """Set the freq, offset, and duplex fields of a memory based on
    a separate rx/tx frequency.
    """
    mem.freq = rxfreq

    if abs(txfreq - rxfreq) > to_MHz(70):
        mem.offset = txfreq
        mem.duplex = 'split'
    else:
        offset = txfreq - rxfreq
        if offset < 0:
            mem.duplex = '-'
        elif offset > 0:
            mem.duplex = '+'
        mem.offset = abs(offset)


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
            for x in range(256)
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


def urlretrieve(url, fn):
    """Grab an URL and save it in a specified file"""

    import urllib.request
    import urllib.error

    headers = {
        'User-Agent': http_user_agent(),
    }
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req)
    with open(fn, 'wb') as f:
        f.write(resp.read())


def mem_from_tsv(tsv_text):
    fields = tsv_text.split('\t')
    if len(fields) < 13:
        raise ValueError('Not enough fields to be a memory')
    mem = Memory()
    mem.really_from_csv(fields)
    print('Parsed %s from tsv' % mem)
    return mem


def mem_from_text(text):
    if text.count('\t') > 10:
        # Seems like plausible TSV, return if it parses
        try:
            return mem_from_tsv(text)
        except Exception:
            pass
    m = Memory()
    freqs = re.findall(r'\b(\d{1,3}\.\d{2,6})\b', text)
    if not freqs:
        raise ValueError('Unable to find a frequency')
    m.freq = parse_freq(freqs[0])
    offset = re.search(r'([+-])\s*(\d\.\d{1,3}|\d)\b', text)
    duplex = re.search(r'\W([+-])\W', text[text.index(freqs[0]):])
    if len(freqs) > 1 and not offset:
        split_to_offset(m, m.freq, parse_freq(freqs[1]))
    else:
        if offset:
            m.duplex = offset.group(1)
            m.offset = parse_freq(offset.group(2))
        # Only look for the first +/- after the frequency, which would be
        # by far the most common arrangement
        if offset is None and duplex:
            m.duplex = duplex.group(1)
    tones = re.findall(r'\b(\d{2,3}\.\d|D\d{3})\b', text)
    if tones and len(tones) <= 2:
        txrx = []
        for val in tones:
            if '.' in val:
                mode = 'Tone'
                tone = float(val)
            elif 'D' in val:
                mode = 'DTCS'
                tone = int(val[1:])
            else:
                continue
            txrx.append((mode, tone, 'N'))
        if len(txrx) == 1:
            txrx.append(('', 88.5, 'N'))
        split_tone_decode(m, txrx[0], txrx[1])

    return m


def mem_to_text(mem):
    pieces = [format_freq(mem.freq)]
    if mem.duplex == 'split':
        pieces.append(format_freq(mem.offset))
    elif mem.duplex in ('-', '+'):
        pieces.append('%s%i.%3.3s' % (mem.duplex,
                                      mem.offset / 1000000,
                                      '%03i' % (mem.offset % 1000000)))
    txrx = split_tone_encode(mem)
    for mode, tone, pol in txrx:
        if mode == 'Tone':
            pieces.append('%.1f' % tone)
        elif mode == 'DTCS':
            pieces.append('D%03i' % tone)
    return '[%s]' % '/'.join(pieces)


def in_range(freq, ranges):
    """Check if freq is in any of the provided ranges"""
    for lo, hi in ranges:
        if lo <= freq <= hi:
            return True
    return False


def is_split(bands, freq1, freq2):
    """Check if two freqs are in the same band from a list of bands
    Returns False if the two freqs are in the same band (not split)
    or True if they are in separate bands (split)"""

    # determine if the two freqs are in the same band
    for low, high in bands:
        if freq1 >= low and freq1 <= high and \
                freq2 >= low and freq2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return True
