# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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

import threading
import os
import sys
import time
import logging

from chirp import chirp_common, errors, directory, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueBoolean, \
    RadioSettingValueString, RadioSettingValueList, RadioSettings

LOG = logging.getLogger(__name__)

NOCACHE = "CHIRP_NOCACHE" in os.environ

DUPLEX = {0: "", 1: "+", 2: "-"}
MODES = {0: "FM", 1: "AM"}
STEPS = list(chirp_common.TUNING_STEPS)
STEPS.append(100.0)

KENWOOD_TONES = list(chirp_common.TONES)
KENWOOD_TONES.remove(159.8)
KENWOOD_TONES.remove(165.5)
KENWOOD_TONES.remove(171.3)
KENWOOD_TONES.remove(177.3)
KENWOOD_TONES.remove(183.5)
KENWOOD_TONES.remove(189.9)
KENWOOD_TONES.remove(196.6)
KENWOOD_TONES.remove(199.5)

THF6_MODES = ["FM", "WFM", "AM", "LSB", "USB", "CW"]


RADIO_IDS = {
    "ID019": "TS-2000",
    "ID009": "TS-850",
    "ID020": "TS-480_LiveMode",
    "ID021": "TS-590S/SG_LiveMode",         # S-model uses same class
    "ID023": "TS-590S/SG_LiveMode"          # as SG
}

LOCK = threading.Lock()
COMMAND_RESP_BUFSIZE = 8
LAST_BAUD = 4800
LAST_DELIMITER = ("\r", " ")

# The Kenwood TS-2000, TS-480, TS-590 & TS-850 use ";"
# as a CAT command message delimiter, and all others use "\n".
# Also, TS-2000 and TS-590 don't space delimite the command
# fields, but others do.


def command(ser, cmd, *args):
    """Send @cmd to radio via @ser"""
    global LOCK, LAST_DELIMITER, COMMAND_RESP_BUFSIZE

    start = time.time()

    LOCK.acquire()

    # TODO: This global use of LAST_DELIMITER breaks reentrancy
    # and needs to be fixed.
    if args:
        cmd += LAST_DELIMITER[1] + LAST_DELIMITER[1].join(args)
    cmd += LAST_DELIMITER[0]

    LOG.debug("PC->RADIO: %s" % cmd.strip())
    ser.write(cmd.encode())

    result = ""
    while not result.endswith(LAST_DELIMITER[0]):
        result += ser.read(COMMAND_RESP_BUFSIZE).decode()
        if (time.time() - start) > 0.5:
            LOG.error("Timeout waiting for data")
            break

    if result.endswith(LAST_DELIMITER[0]):
        LOG.debug("RADIO->PC: %r" % result.strip())
        result = result[:-1]
    else:
        LOG.error("Giving up")

    LOCK.release()

    return result.strip()


def get_id(ser):
    """Get the ID of the radio attached to @ser"""
    global LAST_BAUD
    bauds = [4800, 9600, 19200, 38400, 57600, 115200]
    bauds.remove(LAST_BAUD)
    # Make sure LAST_BAUD is last so that it is tried first below
    bauds.append(LAST_BAUD)

    global LAST_DELIMITER
    command_delimiters = [("\r", " "), (";", "")]

    for delimiter in command_delimiters:
        # Process the baud options in reverse order so that we try the
        # last one first, and then start with the high-speed ones next
        for i in reversed(bauds):
            LAST_DELIMITER = delimiter
            LOG.info("Trying ID at baud %i with delimiter \"%s\"" %
                     (i, repr(delimiter)))
            ser.baudrate = i
            ser.write(LAST_DELIMITER[0].encode())
            ser.read(25)
            resp = command(ser, "ID")

            # most kenwood radios
            if " " in resp:
                LAST_BAUD = i
                return resp.split(" ")[1]

            # Radio responded in the right baud rate,
            # but threw an error because of all the crap
            # we have been hurling at it. Retry the ID at this
            # baud rate, which will almost definitely work.
            if "?" in resp:
                resp = command(ser, "ID")
                LAST_BAUD = i
                if " " in resp:
                    return resp.split(" ")[1]

            # Kenwood radios that return ID numbers
            if resp in list(RADIO_IDS.keys()):
                return RADIO_IDS[resp]

    raise errors.RadioError("No response from radio")


def get_tmode(tone, ctcss, dcs):
    """Get the tone mode based on the values of the tone, ctcss, dcs"""
    if dcs and int(dcs) == 1:
        return "DTCS"
    elif int(ctcss):
        return "TSQL"
    elif int(tone):
        return "Tone"
    else:
        return ""


def iserr(result):
    """Returns True if the @result from a radio is an error"""
    return result in ["N", "?"]


class KenwoodLiveRadio(chirp_common.LiveRadio):
    """Base class for all live-mode kenwood radios"""
    BAUD_RATE = 9600
    VENDOR = "Kenwood"
    MODEL = ""
    NEEDS_COMPAT_SERIAL = False

    _vfo = 0
    _upper = 200
    _kenwood_split = False
    _kenwood_valid_tones = list(chirp_common.TONES)

    def __init__(self, *args, **kwargs):
        chirp_common.LiveRadio.__init__(self, *args, **kwargs)

        self._memcache = {}

        if self.pipe:
            self.pipe.timeout = 0.1
            radio_id = get_id(self.pipe)
            if radio_id != self.MODEL.split(" ")[0]:
                raise Exception("Radio reports %s (not %s)" % (radio_id,
                                                               self.MODEL))

            command(self.pipe, "AI", "0")

    def _cmd_get_memory(self, number):
        return "MR", "%i,0,%03i" % (self._vfo, number)

    def _cmd_get_memory_name(self, number):
        return "MNA", "%i,%03i" % (self._vfo, number)

    def _cmd_get_split(self, number):
        return "MR", "%i,1,%03i" % (self._vfo, number)

    def _cmd_set_memory(self, number, spec):
        if spec:
            spec = "," + spec
        return "MW", "%i,0,%03i%s" % (self._vfo, number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MNA", "%i,%03i,%s" % (self._vfo, number, name)

    def _cmd_set_split(self, number, spec):
        return "MW", "%i,1,%03i,%s" % (self._vfo, number, spec)

    def get_raw_memory(self, number):
        return command(self.pipe, *self._cmd_get_memory(number))

    def get_memory(self, number):
        if number < 0 or number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % self._upper)
        if number in self._memcache and not NOCACHE:
            return self._memcache[number]

        result = command(self.pipe, *self._cmd_get_memory(number))
        if result == "N" or result == "E":
            mem = chirp_common.Memory()
            mem.number = number
            mem.empty = True
            self._memcache[mem.number] = mem
            return mem
        elif " " not in result:
            LOG.error("Not sure what to do with this: `%s'" % result)
            raise errors.RadioError("Unexpected result returned from radio")

        value = result.split(" ")[1]
        spec = value.split(",")

        mem = self._parse_mem_spec(spec)
        self._memcache[mem.number] = mem

        result = command(self.pipe, *self._cmd_get_memory_name(number))
        if " " in result:
            value = result.split(" ", 1)[1]
            if value.count(",") == 2:
                _zero, _loc, mem.name = value.split(",")
            else:
                _loc, mem.name = value.split(",")

        if mem.duplex == "" and self._kenwood_split:
            result = command(self.pipe, *self._cmd_get_split(number))
            if " " in result:
                value = result.split(" ", 1)[1]
                self._parse_split_spec(mem, value.split(","))

        return mem

    def _make_mem_spec(self, mem):
        pass

    def _parse_mem_spec(self, spec):
        pass

    def _parse_split_spec(self, mem, spec):
        mem.duplex = "split"
        mem.offset = int(spec[2])

    def _make_split_spec(self, mem):
        return ("%011i" % mem.offset, "0")

    def set_memory(self, memory):
        if memory.number < 0 or memory.number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % self._upper)

        spec = self._make_mem_spec(memory)
        spec = ",".join(spec)
        r1 = command(self.pipe, *self._cmd_set_memory(memory.number, spec))
        if not iserr(r1):
            time.sleep(0.5)
            r2 = command(self.pipe, *self._cmd_set_memory_name(memory.number,
                                                               memory.name))
            if not iserr(r2):
                memory.name = memory.name.rstrip()
                self._memcache[memory.number] = memory
            else:
                raise errors.InvalidDataError("Radio refused name %i: %s" %
                                              (memory.number,
                                               repr(memory.name)))
        else:
            raise errors.InvalidDataError("Radio refused %i" % memory.number)

        if memory.duplex == "split" and self._kenwood_split:
            spec = ",".join(self._make_split_spec(memory))
            result = command(self.pipe, *self._cmd_set_split(memory.number,
                                                             spec))
            if iserr(result):
                raise errors.InvalidDataError("Radio refused %i" %
                                              memory.number)

    def erase_memory(self, number):
        if number not in self._memcache:
            return

        resp = command(self.pipe, *self._cmd_set_memory(number, ""))
        if iserr(resp):
            raise errors.RadioError("Radio refused delete of %i" % number)
        del self._memcache[number]

    def _kenwood_get(self, cmd):
        resp = command(self.pipe, cmd)
        if " " in resp:
            return resp.split(" ", 1)
        else:
            if resp == cmd:
                return [resp, ""]
            else:
                raise errors.RadioError("Radio refused to return %s" % cmd)

    def _kenwood_set(self, cmd, value):
        resp = command(self.pipe, cmd, value)
        if resp[:len(cmd)] == cmd:
            return
        raise errors.RadioError("Radio refused to set %s" % cmd)

    def _kenwood_get_bool(self, cmd):
        _cmd, result = self._kenwood_get(cmd)
        return result == "1"

    def _kenwood_set_bool(self, cmd, value):
        return self._kenwood_set(cmd, str(int(value)))

    def _kenwood_get_int(self, cmd):
        _cmd, result = self._kenwood_get(cmd)
        return int(result)

    def _kenwood_set_int(self, cmd, value, digits=1):
        return self._kenwood_set(cmd, ("%%0%ii" % digits) % value)

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            if isinstance(element.value, RadioSettingValueBoolean):
                self._kenwood_set_bool(element.get_name(), element.value)
            elif isinstance(element.value, RadioSettingValueList):
                options = self._get_setting_options(element.get_name())
                if len(options) > 9:
                    digits = 2
                else:
                    digits = 1
                self._kenwood_set_int(element.get_name(),
                                      options.index(str(element.value)),
                                      digits)
            elif isinstance(element.value, RadioSettingValueInteger):
                if element.value.get_max() > 9:
                    digits = 2
                else:
                    digits = 1
                self._kenwood_set_int(element.get_name(),
                                      element.value, digits)
            elif isinstance(element.value, RadioSettingValueString):
                self._kenwood_set(element.get_name(), str(element.value))
            else:
                LOG.error("Unknown type %s" % element.value)


class KenwoodOldLiveRadio(KenwoodLiveRadio):
    _kenwood_valid_tones = list(chirp_common.OLD_TONES)

    def set_memory(self, memory):
        supported_tones = list(chirp_common.OLD_TONES)
        supported_tones.remove(69.3)
        if memory.rtone not in supported_tones:
            raise errors.UnsupportedToneError("This radio does not support " +
                                              "tone %.1fHz" % memory.rtone)
        if memory.ctone not in supported_tones:
            raise errors.UnsupportedToneError("This radio does not support " +
                                              "tone %.1fHz" % memory.ctone)

        return KenwoodLiveRadio.set_memory(self, memory)


@directory.register
class THD7Radio(KenwoodOldLiveRadio):
    """Kenwood TH-D7"""
    MODEL = "TH-D7"

    _kenwood_split = True

    _BEP_OPTIONS = ["Off", "Key", "Key+Data", "All"]
    _POSC_OPTIONS = ["Off Duty", "Enroute", "In Service", "Returning",
                     "Committed", "Special", "Priority", "Emergency"]

    _SETTINGS_OPTIONS = {
        "BAL": ["4:0", "3:1", "2:2", "1:3", "0:4"],
        "BEP": None,
        "BEPT": ["Off", "Mine", "All New"],  # D700 has fourth "All"
        "DS": ["Data Band", "Both Bands"],
        "DTB": ["A", "B"],
        "DTBA": ["A", "B", "A:TX/B:RX"],  # D700 has fourth A:RX/B:TX
        "DTX": ["Manual", "PTT", "Auto"],
        "ICO": ["Kenwood", "Runner", "House", "Tent", "Boat", "SSTV",
                "Plane", "Speedboat", "Car", "Bicycle"],
        "MNF": ["Name", "Frequency"],
        "PKSA": ["1200", "9600"],
        "POSC": None,
        "PT": ["100ms", "200ms", "500ms", "750ms",
               "1000ms", "1500ms", "2000ms"],
        "SCR": ["Time", "Carrier", "Seek"],
        "SV": ["Off", "0.2s", "0.4s", "0.6s", "0.8s", "1.0s",
               "2s", "3s", "4s", "5s"],
        "TEMP": ["F", "C"],
        "TXI": ["30sec", "1min", "2min", "3min", "4min", "5min",
                "10min", "20min", "30min"],
        "UNIT": ["English", "Metric"],
        "WAY": ["Off", "6 digit NMEA", "7 digit NMEA", "8 digit NMEA",
                "9 digit NMEA", "6 digit Magellan", "DGPS"],
    }

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_modes = list(MODES.values())
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_characters = \
            chirp_common.CHARSET_ALPHANUMERIC + "/.-+*)('&%$#! ~}|{"
        rf.valid_name_length = 7
        rf.valid_tuning_steps = STEPS
        rf.memory_bounds = (1, self._upper)
        return rf

    def _make_mem_spec(self, mem):
        if mem.duplex in " -+":
            duplex = util.get_dict_rev(DUPLEX, mem.duplex)
            offset = mem.offset
        else:
            duplex = 0
            offset = 0

        spec = (
            "%011i" % mem.freq,
            "%X" % STEPS.index(mem.tuning_step),
            "%i" % duplex,
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "",  # DCS Flag
            "%02i" % (self._kenwood_valid_tones.index(mem.rtone) + 1),
            "",  # DCS Code
            "%02i" % (self._kenwood_valid_tones.index(mem.ctone) + 1),
            "%09i" % offset,
            "%i" % util.get_dict_rev(MODES, mem.mode),
            "%i" % ((mem.skip == "S") and 1 or 0))

        return spec

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[2])
        mem.freq = int(spec[3], 10)
        mem.tuning_step = STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        mem.tmode = get_tmode(spec[7], spec[8], spec[9])
        mem.rtone = self._kenwood_valid_tones[int(spec[10]) - 1]
        mem.ctone = self._kenwood_valid_tones[int(spec[12]) - 1]
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11][:-1]) - 1]
        else:
            LOG.warn("Unknown or invalid DCS: %s" % spec[11])
        if spec[13]:
            mem.offset = int(spec[13])
        else:
            mem.offset = 0
        mem.mode = MODES[int(spec[14])]
        mem.skip = int(spec[15]) and "S" or ""

        return mem

    EXTRA_BOOL_SETTINGS = {
        'main': [("LMP", "Lamp")],
        'dtmf': [("TXH", "TX Hold")],
    }
    EXTRA_LIST_SETTINGS = {
        'main': [("BAL", "Balance"),
                 ("MNF", "Memory Display Mode")],
        'save': [("SV", "Battery Save")],
    }

    def _get_setting_options(self, setting):
        opts = self._SETTINGS_OPTIONS[setting]
        if opts is None:
            opts = getattr(self, '_%s_OPTIONS' % setting)
        return opts

    def get_settings(self):
        main = RadioSettingGroup("main", "Main")
        aux = RadioSettingGroup("aux", "Aux")
        tnc = RadioSettingGroup("tnc", "TNC")
        save = RadioSettingGroup("save", "Save")
        display = RadioSettingGroup("display", "Display")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        radio = RadioSettingGroup("radio", "Radio",
                                  aux, tnc, save, display, dtmf)
        sky = RadioSettingGroup("sky", "SkyCommand")
        aprs = RadioSettingGroup("aprs", "APRS")

        top = RadioSettings(main, radio, aprs, sky)

        bools = [("AMR", aprs, "APRS Message Auto-Reply"),
                 ("AIP", aux, "Advanced Intercept Point"),
                 ("ARO", aux, "Automatic Repeater Offset"),
                 ("BCN", aprs, "Beacon"),
                 ("CH", radio, "Channel Mode Display"),
                 # ("DIG", aprs, "APRS Digipeater"),
                 ("DL", main, "Dual"),
                 ("LK", main, "Lock"),
                 ("TSP", dtmf, "DTMF Fast Transmission"),
                 ]

        for setting, group, name in bools:
            value = self._kenwood_get_bool(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueBoolean(value))
            group.append(rs)

        lists = [("BEP", aux, "Beep"),
                 ("BEPT", aprs, "APRS Beep"),
                 ("DS", tnc, "Data Sense"),
                 ("DTB", tnc, "Data Band"),
                 ("DTBA", aprs, "APRS Data Band"),
                 ("DTX", aprs, "APRS Data TX"),
                 # ("ICO", aprs, "APRS Icon"),
                 ("PKSA", aprs, "APRS Packet Speed"),
                 ("POSC", aprs, "APRS Position Comment"),
                 ("PT", dtmf, "DTMF Speed"),
                 ("TEMP", aprs, "APRS Temperature Units"),
                 ("TXI", aprs, "APRS Transmit Interval"),
                 # ("UNIT", aprs, "APRS Display Units"),
                 ("WAY", aprs, "Waypoint Mode"),
                 ]

        for setting, group, name in lists:
            value = self._kenwood_get_int(setting)
            options = self._get_setting_options(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueList(options,
                                                    options[value]))
            group.append(rs)

        for group_name, settings in self.EXTRA_BOOL_SETTINGS.items():
            group = locals()[group_name]
            for setting, name in settings:
                value = self._kenwood_get_bool(setting)
                rs = RadioSetting(setting, name,
                                  RadioSettingValueBoolean(value))
                group.append(rs)

        for group_name, settings in self.EXTRA_LIST_SETTINGS.items():
            group = locals()[group_name]
            for setting, name in settings:
                value = self._kenwood_get_int(setting)
                options = self._get_setting_options(setting)
                rs = RadioSetting(setting, name,
                                  RadioSettingValueBoolean(value))
                group.append(rs)

        ints = [("CNT", display, "Contrast", 1, 16),
                ]
        for setting, group, name, minv, maxv in ints:
            value = self._kenwood_get_int(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueInteger(minv, maxv, value))
            group.append(rs)

        strings = [("MES", display, "Power-on Message", 8),
                   ("MYC", aprs, "APRS Callsign", 8),
                   ("PP", aprs, "APRS Path", 32),
                   ("SCC", sky, "SkyCommand Callsign", 8),
                   ("SCT", sky, "SkyCommand To Callsign", 8),
                   # ("STAT", aprs, "APRS Status Text", 32),
                   ]
        for setting, group, name, length in strings:
            _cmd, value = self._kenwood_get(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueString(0, length, value))
            group.append(rs)

        return top


@directory.register
class THD7GRadio(THD7Radio):
    """Kenwood TH-D7G"""
    MODEL = "TH-D7G"

    def get_features(self):
        rf = super(THD7GRadio, self).get_features()
        rf.valid_name_length = 8
        return rf


@directory.register
class TMD700Radio(THD7Radio):
    """Kenwood TH-D700"""
    MODEL = "TM-D700"

    _kenwood_split = True

    _BEP_OPTIONS = ["Off", "Key"]
    _POSC_OPTIONS = ["Off Duty", "Enroute", "In Service", "Returning",
                     "Committed", "Special", "Priority", "CUSTOM 0",
                     "CUSTOM 1", "CUSTOM 2", "CUSTOM 4", "CUSTOM 5",
                     "CUSTOM 6", "Emergency"]
    EXTRA_BOOL_SETTINGS = {}
    EXTRA_LIST_SETTINGS = {}

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_dtcs = True
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_modes = ["FM", "AM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 8
        rf.valid_tuning_steps = STEPS
        rf.memory_bounds = (1, self._upper)
        return rf

    def _make_mem_spec(self, mem):
        if mem.duplex in " -+":
            duplex = util.get_dict_rev(DUPLEX, mem.duplex)
        else:
            duplex = 0
        spec = (
            "%011i" % mem.freq,
            "%X" % STEPS.index(mem.tuning_step),
            "%i" % duplex,
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "%i" % (mem.tmode == "DTCS"),
            "%02i" % (self._kenwood_valid_tones.index(mem.rtone) + 1),
            "%03i0" % (chirp_common.DTCS_CODES.index(mem.dtcs) + 1),
            "%02i" % (self._kenwood_valid_tones.index(mem.ctone) + 1),
            "%09i" % mem.offset,
            "%i" % util.get_dict_rev(MODES, mem.mode),
            "%i" % ((mem.skip == "S") and 1 or 0))

        return spec

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[2])
        mem.freq = int(spec[3])
        mem.tuning_step = STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        mem.tmode = get_tmode(spec[7], spec[8], spec[9])
        mem.rtone = self._kenwood_valid_tones[int(spec[10]) - 1]
        mem.ctone = self._kenwood_valid_tones[int(spec[12]) - 1]
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11][:-1]) - 1]
        else:
            LOG.warn("Unknown or invalid DCS: %s" % spec[11])
        if spec[13]:
            mem.offset = int(spec[13])
        else:
            mem.offset = 0
        mem.mode = MODES[int(spec[14])]
        mem.skip = int(spec[15]) and "S" or ""

        return mem


@directory.register
class TMV7Radio(KenwoodOldLiveRadio):
    """Kenwood TM-V7"""
    MODEL = "TM-V7"

    mem_upper_limit = 200  # Will be updated

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = False
        rf.has_tuning_step = False
        rf.valid_modes = ["FM"]
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_name_length = 7
        rf.valid_tuning_steps = STEPS
        rf.has_sub_devices = True
        rf.memory_bounds = (1, self._upper)
        return rf

    def _make_mem_spec(self, mem):
        spec = (
            "%011i" % mem.freq,
            "%X" % STEPS.index(mem.tuning_step),
            "%i" % util.get_dict_rev(DUPLEX, mem.duplex),
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "0",
            "%02i" % (self._kenwood_valid_tones.index(mem.rtone) + 1),
            "000",
            "%02i" % (self._kenwood_valid_tones.index(mem.ctone) + 1),
            "",
            "0")

        return spec

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()
        mem.number = int(spec[2])
        mem.freq = int(spec[3])
        mem.tuning_step = STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        if int(spec[7]):
            mem.tmode = "Tone"
        elif int(spec[8]):
            mem.tmode = "TSQL"
        mem.rtone = self._kenwood_valid_tones[int(spec[10]) - 1]
        mem.ctone = self._kenwood_valid_tones[int(spec[12]) - 1]

        return mem

    def get_sub_devices(self):
        return [TMV7RadioVHF(self.pipe), TMV7RadioUHF(self.pipe)]

    def __test_location(self, loc):
        mem = self.get_memory(loc)
        if not mem.empty:
            # Memory was not empty, must be valid
            return True

        # Mem was empty (or invalid), try to set it
        if self._vfo == 0:
            mem.freq = 144000000
        else:
            mem.freq = 440000000
        mem.empty = False
        try:
            self.set_memory(mem)
        except Exception:
            # Failed, so we're past the limit
            return False

        # Erase what we did
        try:
            self.erase_memory(loc)
        except Exception:
            pass  # V7A Can't delete just yet

        return True

    def _detect_split(self):
        return 50


class TMV7RadioSub(TMV7Radio):
    """Base class for the TM-V7 sub devices"""
    def __init__(self, pipe):
        TMV7Radio.__init__(self, pipe)
        self._detect_split()


class TMV7RadioVHF(TMV7RadioSub):
    """TM-V7 VHF subdevice"""
    VARIANT = "VHF"
    _vfo = 0


class TMV7RadioUHF(TMV7RadioSub):
    """TM-V7 UHF subdevice"""
    VARIANT = "UHF"
    _vfo = 1


@directory.register
class TMG707Radio(TMV7Radio):
    """Kenwood TM-G707"""
    MODEL = "TM-G707"

    def get_features(self):
        rf = TMV7Radio.get_features(self)
        rf.has_sub_devices = False
        rf.memory_bounds = (1, 180)
        rf.valid_bands = [(118000000, 174000000),
                          (300000000, 520000000),
                          (800000000, 999000000)]
        return rf


THG71_STEPS = [5, 6.25, 10, 12.5, 15, 20, 25, 30, 50, 100]


@directory.register
class THG71Radio(TMV7Radio):
    """Kenwood TH-G71"""
    MODEL = "TH-G71"

    def get_features(self):
        rf = TMV7Radio.get_features(self)
        rf.has_tuning_step = True
        rf.valid_tuning_steps = list(THG71_STEPS)
        rf.valid_name_length = 6
        rf.has_sub_devices = False
        rf.valid_bands = [(118000000, 174000000),
                          (320000000, 470000000),
                          (800000000, 945000000)]
        return rf

    def _make_mem_spec(self, mem):
        spec = (
            "%011i" % mem.freq,
            "%X" % THG71_STEPS.index(mem.tuning_step),
            "%i" % util.get_dict_rev(DUPLEX, mem.duplex),
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "0",
            "%02i" % (self._kenwood_valid_tones.index(mem.rtone) + 1),
            "000",
            "%02i" % (self._kenwood_valid_tones.index(mem.ctone) + 1),
            "%09i" % mem.offset,
            "%i" % ((mem.skip == "S") and 1 or 0))
        return spec

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()
        mem.number = int(spec[2])
        mem.freq = int(spec[3])
        mem.tuning_step = THG71_STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        if int(spec[7]):
            mem.tmode = "Tone"
        elif int(spec[8]):
            mem.tmode = "TSQL"
        mem.rtone = self._kenwood_valid_tones[int(spec[10]) - 1]
        mem.ctone = self._kenwood_valid_tones[int(spec[12]) - 1]
        if spec[13]:
            mem.offset = int(spec[13])
        else:
            mem.offset = 0
        return mem


THF6A_STEPS = [5.0, 6.25, 8.33, 9.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0,
               100.0]

THF6A_DUPLEX = dict(DUPLEX)
THF6A_DUPLEX[3] = "split"


@directory.register
class THF6ARadio(KenwoodLiveRadio):
    """Kenwood TH-F6"""
    MODEL = "TH-F6"

    _upper = 399
    _kenwood_split = True
    _kenwood_valid_tones = list(KENWOOD_TONES)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_modes = list(THF6_MODES)
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_tuning_steps = list(THF6A_STEPS)
        rf.valid_bands = [(1000, 1300000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_duplexes = list(THF6A_DUPLEX.values())
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 8
        rf.memory_bounds = (0, self._upper)
        rf.has_settings = True
        return rf

    def _cmd_set_memory(self, number, spec):
        if spec:
            spec = "," + spec
        return "MW", "0,%03i%s" % (number, spec)

    def _cmd_get_memory(self, number):
        return "MR", "0,%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MNA", "%03i" % number

    def _cmd_set_memory_name(self, number, name):
        return "MNA", "%03i,%s" % (number, name)

    def _cmd_get_split(self, number):
        return "MR", "1,%03i" % number

    def _cmd_set_split(self, number, spec):
        return "MW", "1,%03i,%s" % (number, spec)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[1])
        mem.freq = int(spec[2])
        mem.tuning_step = THF6A_STEPS[int(spec[3], 16)]
        mem.duplex = THF6A_DUPLEX[int(spec[4])]
        mem.tmode = get_tmode(spec[6], spec[7], spec[8])
        mem.rtone = self._kenwood_valid_tones[int(spec[9])]
        mem.ctone = self._kenwood_valid_tones[int(spec[10])]
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11])]
        else:
            LOG.warn("Unknown or invalid DCS: %s" % spec[11])
        if spec[12]:
            mem.offset = int(spec[12])
        else:
            mem.offset = 0
        mem.mode = THF6_MODES[int(spec[13])]
        if spec[14] == "1":
            mem.skip = "S"

        return mem

    def _make_mem_spec(self, mem):
        if mem.duplex in " +-":
            duplex = util.get_dict_rev(THF6A_DUPLEX, mem.duplex)
            offset = mem.offset
        elif mem.duplex == "split":
            duplex = 0
            offset = 0
        else:
            LOG.warn("Bug: unsupported duplex `%s'" % mem.duplex)
        spec = (
            "%011i" % mem.freq,
            "%X" % THF6A_STEPS.index(mem.tuning_step),
            "%i" % duplex,
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "%i" % (mem.tmode == "DTCS"),
            "%02i" % (self._kenwood_valid_tones.index(mem.rtone)),
            "%02i" % (self._kenwood_valid_tones.index(mem.ctone)),
            "%03i" % (chirp_common.DTCS_CODES.index(mem.dtcs)),
            "%09i" % offset,
            "%i" % (THF6_MODES.index(mem.mode)),
            "%i" % (mem.skip == "S"))

        return spec

    _SETTINGS_OPTIONS = {
        "APO": ["Off", "30min", "60min"],
        "BAL": ["100%:0%", "75%:25%", "50%:50%", "25%:75%", "%0:100%"],
        "BAT": ["Lithium", "Alkaline"],
        "CKEY": ["Call", "1750Hz"],
        "DATP": ["1200bps", "9600bps"],
        "LAN": ["English", "Japanese"],
        "MNF": ["Name", "Frequency"],
        "MRM": ["All Band", "Current Band"],
        "PT": ["100ms", "250ms", "500ms", "750ms",
               "1000ms", "1500ms", "2000ms"],
        "SCR": ["Time", "Carrier", "Seek"],
        "SV": ["Off", "0.2s", "0.4s", "0.6s", "0.8s", "1.0s",
               "2s", "3s", "4s", "5s"],
        "VXD": ["250ms", "500ms", "750ms", "1s", "1.5s", "2s", "3s"],
    }

    def get_settings(self):
        main = RadioSettingGroup("main", "Main")
        aux = RadioSettingGroup("aux", "Aux")
        save = RadioSettingGroup("save", "Save")
        display = RadioSettingGroup("display", "Display")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        top = RadioSettings(main, aux, save, display, dtmf)

        lists = [("APO", save, "Automatic Power Off"),
                 ("BAL", main, "Balance"),
                 ("BAT", save, "Battery Type"),
                 ("CKEY", aux, "CALL Key Set Up"),
                 ("DATP", aux, "Data Packet Speed"),
                 ("LAN", display, "Language"),
                 ("MNF", main, "Memory Display Mode"),
                 ("MRM", main, "Memory Recall Method"),
                 ("PT", dtmf, "DTMF Speed"),
                 ("SCR", main, "Scan Resume"),
                 ("SV", save, "Battery Save"),
                 ("VXD", aux, "VOX Drop Delay"),
                 ]

        bools = [("ANT", aux, "Bar Antenna"),
                 ("ATT", main, "Attenuator Enabled"),
                 ("ARO", main, "Automatic Repeater Offset"),
                 ("BEP", aux, "Beep for keypad"),
                 ("DL", main, "Dual"),
                 ("DLK", dtmf, "DTMF Lockout On Transmit"),
                 ("ELK", aux, "Enable Locked Tuning"),
                 ("LK", main, "Lock"),
                 ("LMP", display, "Lamp"),
                 ("NSFT", aux, "Noise Shift"),
                 ("TH", aux, "Tx Hold for 1750"),
                 ("TSP", dtmf, "DTMF Fast Transmission"),
                 ("TXH", dtmf, "TX Hold DTMF"),
                 ("TXS", main, "Transmit Inhibit"),
                 ("VOX", aux, "VOX Enable"),
                 ("VXB", aux, "VOX On Busy"),
                 ]

        ints = [("CNT", display, "Contrast", 1, 16),
                ("VXG", aux, "VOX Gain", 0, 9),
                ]

        strings = [("MES", display, "Power-on Message", 8),
                   ]

        for setting, group, name in bools:
            value = self._kenwood_get_bool(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueBoolean(value))
            group.append(rs)

        for setting, group, name in lists:
            value = self._kenwood_get_int(setting)
            options = self._SETTINGS_OPTIONS[setting]
            rs = RadioSetting(setting, name,
                              RadioSettingValueList(options,
                                                    options[value]))
            group.append(rs)

        for setting, group, name, minv, maxv in ints:
            value = self._kenwood_get_int(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueInteger(minv, maxv, value))
            group.append(rs)

        for setting, group, name, length in strings:
            _cmd, value = self._kenwood_get(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueString(0, length, value))
            group.append(rs)

        return top


@directory.register
class THF7ERadio(THF6ARadio):
    """Kenwood TH-F7"""
    MODEL = "TH-F7"


D710_DUPLEX = ["", "+", "-", "split"]
D710_MODES = ["FM", "NFM", "AM"]
D710_SKIP = ["", "S"]
D710_STEPS = [5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]


@directory.register
class TMD710Radio(KenwoodLiveRadio):
    """Kenwood TM-D710"""
    MODEL = "TM-D710"

    _upper = 999
    _kenwood_valid_tones = list(KENWOOD_TONES)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = True
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = D710_MODES
        rf.valid_duplexes = D710_DUPLEX
        rf.valid_tuning_steps = D710_STEPS
        rf.valid_characters = chirp_common.CHARSET_ASCII.replace(',', '')
        rf.valid_name_length = 8
        rf.valid_skips = D710_SKIP
        rf.memory_bounds = (0, 999)
        return rf

    def _cmd_get_memory(self, number):
        return "ME", "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec):
        return "ME", "%03i,%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MN", "%03i,%s" % (number, name)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[0])
        mem.freq = int(spec[1])
        mem.tuning_step = D710_STEPS[int(spec[2], 16)]
        mem.duplex = D710_DUPLEX[int(spec[3])]
        # Reverse
        if int(spec[5]):
            mem.tmode = "Tone"
        elif int(spec[6]):
            mem.tmode = "TSQL"
        elif int(spec[7]):
            mem.tmode = "DTCS"
        mem.rtone = self._kenwood_valid_tones[int(spec[8])]
        mem.ctone = self._kenwood_valid_tones[int(spec[9])]
        mem.dtcs = chirp_common.DTCS_CODES[int(spec[10])]
        mem.offset = int(spec[11])
        mem.mode = D710_MODES[int(spec[12])]
        # TX Frequency
        if int(spec[13]):
            mem.duplex = "split"
            mem.offset = int(spec[13])
        # Unknown
        mem.skip = D710_SKIP[int(spec[15])]  # Memory Lockout

        return mem

    def _make_mem_spec(self, mem):
        spec = (
            "%010i" % mem.freq,
            "%X" % D710_STEPS.index(mem.tuning_step),
            "%i" % (0 if mem.duplex == "split"
                    else D710_DUPLEX.index(mem.duplex)),
            "0",  # Reverse
            "%i" % (mem.tmode == "Tone" and 1 or 0),
            "%i" % (mem.tmode == "TSQL" and 1 or 0),
            "%i" % (mem.tmode == "DTCS" and 1 or 0),
            "%02i" % (self._kenwood_valid_tones.index(mem.rtone)),
            "%02i" % (self._kenwood_valid_tones.index(mem.ctone)),
            "%03i" % (chirp_common.DTCS_CODES.index(mem.dtcs)),
            "%08i" % (0 if mem.duplex == "split" else mem.offset),  # Offset
            "%i" % D710_MODES.index(mem.mode),
            "%010i" % (mem.offset if mem.duplex == "split" else 0),  # TX Freq
            "0",  # Unknown
            "%i" % D710_SKIP.index(mem.skip),  # Memory Lockout
            )

        return spec


@directory.register
class THD72Radio(TMD710Radio):
    """Kenwood TH-D72"""
    MODEL = "TH-D72 (live mode)"
    HARDWARE_FLOW = sys.platform == "darwin"  # only OS X driver needs hw flow

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[0])
        mem.freq = int(spec[1])
        mem.tuning_step = D710_STEPS[int(spec[2], 16)]
        mem.duplex = D710_DUPLEX[int(spec[3])]
        # Reverse
        if int(spec[5]):
            mem.tmode = "Tone"
        elif int(spec[6]):
            mem.tmode = "TSQL"
        elif int(spec[7]):
            mem.tmode = "DTCS"
        mem.rtone = self._kenwood_valid_tones[int(spec[9])]
        mem.ctone = self._kenwood_valid_tones[int(spec[10])]
        mem.dtcs = chirp_common.DTCS_CODES[int(spec[11])]
        mem.offset = int(spec[13])
        mem.mode = D710_MODES[int(spec[14])]
        # TX Frequency
        if int(spec[15]):
            mem.duplex = "split"
            mem.offset = int(spec[15])
        # Lockout
        mem.skip = D710_SKIP[int(spec[17])]  # Memory Lockout

        return mem

    def _make_mem_spec(self, mem):
        spec = (
            "%010i" % mem.freq,
            "%X" % D710_STEPS.index(mem.tuning_step),
            "%i" % (0 if mem.duplex == "split"
                    else D710_DUPLEX.index(mem.duplex)),
            "0",  # Reverse
            "%i" % (mem.tmode == "Tone" and 1 or 0),
            "%i" % (mem.tmode == "TSQL" and 1 or 0),
            "%i" % (mem.tmode == "DTCS" and 1 or 0),
            "0",
            "%02i" % (self._kenwood_valid_tones.index(mem.rtone)),
            "%02i" % (self._kenwood_valid_tones.index(mem.ctone)),
            "%03i" % (chirp_common.DTCS_CODES.index(mem.dtcs)),
            "0",
            "%08i" % (0 if mem.duplex == "split" else mem.offset),  # Offset
            "%i" % D710_MODES.index(mem.mode),
            "%010i" % (mem.offset if mem.duplex == "split" else 0),  # TX Freq
            "0",  # Unknown
            "%i" % D710_SKIP.index(mem.skip),  # Memory Lockout
            )

        return spec


@directory.register
class TMV71Radio(TMD710Radio):
    """Kenwood TM-V71"""
    MODEL = "TM-V71"


@directory.register
class TMD710GRadio(TMD710Radio):
    """Kenwood TM-D710G"""
    MODEL = "TM-D710G"

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is currently under development, "
                           "and supports the same features as the TM-D710A/E. "
                           "There are no known issues with it, but you should "
                           "proceed with caution.")
        return rp


THK2_DUPLEX = ["", "+", "-"]
THK2_MODES = ["FM", "NFM"]

THK2_CHARS = chirp_common.CHARSET_UPPER_NUMERIC + "-/"


@directory.register
class THK2Radio(KenwoodLiveRadio):
    """Kenwood TH-K2"""
    MODEL = "TH-K2"

    _kenwood_valid_tones = list(KENWOOD_TONES)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = THK2_MODES
        rf.valid_duplexes = THK2_DUPLEX
        rf.valid_characters = THK2_CHARS
        rf.valid_name_length = 6
        rf.valid_bands = [(136000000, 173990000)]
        rf.valid_skips = ["", "S"]
        rf.valid_tuning_steps = [5.0]
        rf.memory_bounds = (0, 49)
        return rf

    def _cmd_get_memory(self, number):
        return "ME", "%02i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%02i" % number

    def _cmd_set_memory(self, number, spec):
        return "ME", "%02i,%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MN", "%02i,%s" % (number, name)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        mem.number = int(spec[0])
        mem.freq = int(spec[1])
        # mem.tuning_step =
        mem.duplex = THK2_DUPLEX[int(spec[3])]
        if int(spec[5]):
            mem.tmode = "Tone"
        elif int(spec[6]):
            mem.tmode = "TSQL"
        elif int(spec[7]):
            mem.tmode = "DTCS"
        mem.rtone = self._kenwood_valid_tones[int(spec[8])]
        mem.ctone = self._kenwood_valid_tones[int(spec[9])]
        mem.dtcs = chirp_common.DTCS_CODES[int(spec[10])]
        mem.offset = int(spec[11])
        mem.mode = THK2_MODES[int(spec[12])]
        mem.skip = int(spec[16]) and "S" or ""
        return mem

    def _make_mem_spec(self, mem):
        try:
            rti = self._kenwood_valid_tones.index(mem.rtone)
            cti = self._kenwood_valid_tones.index(mem.ctone)
        except ValueError:
            raise errors.UnsupportedToneError()

        spec = (
            "%010i" % mem.freq,
            "0",
            "%i" % THK2_DUPLEX.index(mem.duplex),
            "0",
            "%i" % int(mem.tmode == "Tone"),
            "%i" % int(mem.tmode == "TSQL"),
            "%i" % int(mem.tmode == "DTCS"),
            "%02i" % rti,
            "%02i" % cti,
            "%03i" % chirp_common.DTCS_CODES.index(mem.dtcs),
            "%08i" % mem.offset,
            "%i" % THK2_MODES.index(mem.mode),
            "0",
            "%010i" % 0,
            "0",
            "%i" % int(mem.skip == "S")
            )
        return spec


TM271_STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0]


@directory.register
class TM271Radio(THK2Radio):
    """Kenwood TM-271"""
    MODEL = "TM-271"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = THK2_MODES
        rf.valid_duplexes = THK2_DUPLEX
        rf.valid_characters = THK2_CHARS
        rf.valid_name_length = 6
        rf.valid_bands = [(137000000, 173990000)]
        rf.valid_skips = ["", "S"]
        rf.valid_tuning_steps = list(TM271_STEPS)
        rf.memory_bounds = (0, 99)
        return rf

    def _cmd_get_memory(self, number):
        return "ME", "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec):
        return "ME", "%03i,%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MN", "%03i,%s" % (number, name)


@directory.register
class TM281Radio(TM271Radio):
    """Kenwood TM-281"""
    MODEL = "TM-281"
    # seems that this is a perfect clone of TM271 with just a different model


@directory.register
class TM471Radio(THK2Radio):
    """Kenwood TM-471"""
    MODEL = "TM-471"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = THK2_MODES
        rf.valid_duplexes = THK2_DUPLEX
        rf.valid_characters = THK2_CHARS
        rf.valid_name_length = 6
        rf.valid_bands = [(444000000, 479990000)]
        rf.valid_skips = ["", "S"]
        rf.valid_tuning_steps = [5.0]
        rf.memory_bounds = (0, 99)
        return rf

    def _cmd_get_memory(self, number):
        return "ME", "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec):
        return "ME", "%03i,%s" % (number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MN", "%03i,%s" % (number, name)


@directory.register
class TS590Radio(KenwoodLiveRadio):
    """Kenwood TS-590S/SG"""
    MODEL = "TS-590S/SG_LiveMode"

    _kenwood_valid_tones = list(KENWOOD_TONES)
    _kenwood_valid_tones.append(1750)

    _upper = 99
    _duplex = ["", "-", "+"]
    _skip = ["", "S"]
    _modes = ["LSB", "USB", "CW", "FM", "AM", "FSK", "CW-R",
              "FSK-R", "Data+LSB", "Data+USB", "Data+FM"]
    _bands = [(1800000, 2000000),    # 160M Band
              (3500000, 4000000),    # 80M Band
              (5167500, 5450000),    # 60M Band
              (7000000, 7300000),    # 40M Band
              (10100000, 10150000),  # 30M Band
              (14000000, 14350000),  # 20M Band
              (18068000, 18168000),  # 17M Band
              (21000000, 21450000),  # 15M Band
              (24890000, 24990000),  # 12M Band
              (28000000, 29700000),  # 10M Band
              (50000000, 54000000)]   # 6M Band

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.can_odd_split = False
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_name = True
        rf.has_settings = False
        rf.has_offset = True
        rf.has_mode = True
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.has_cross = True
        rf.has_comment = False

        rf.memory_bounds = (0, self._upper)

        rf.valid_bands = self._bands
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "*+-/"
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_modes = self._modes
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "->Tone"]
        rf.valid_name_length = 8    # 8 character channel names

        return rf

    def _my_val_list(setting, opts, obj, atrb):
        """Callback:from ValueList. Set the integer index."""
        value = opts.index(str(setting.value))
        setattr(obj, atrb, value)
        return

    def get_memory(self, number):
        """Convert ascii channel data spec into UI columns (mem)"""
        mem = chirp_common.Memory()
        mem.extra = RadioSettingGroup("extra", "Extra")
        # Read the base and split MR strings
        mem.number = number
        spec0 = command(self.pipe, "MR0 %02i" % mem.number)
        spec1 = command(self.pipe, "MR1 %02i" % mem.number)
        mem.name = spec0[41:49]  # Max 8-Char Name if assigned
        mem.name = mem.name.strip()
        mem.name = mem.name.upper()
        _p4 = int(spec0[6:17])    # Rx Frequency
        _p4s = int(spec1[6:17])   # Offset freq (Tx)
        _p5 = int(spec0[17])      # Mode
        _p6 = int(spec0[18])      # Data Mode
        _p7 = int(spec0[19])      # Tone Mode
        _p8 = int(spec0[20:22])   # Tone Frequency Index
        _p9 = int(spec0[22:24])   # CTCSS Frequency Index
        _p11 = int(spec0[27])     # Filter A/B
        _p14 = int(spec0[38:40])  # FM Mode
        _p15 = int(spec0[40])     # Chan Lockout (Skip)
        if _p4 == 0:
            mem.empty = True
            return mem
        mem.empty = False
        mem.freq = _p4
        mem.duplex = self._duplex[0]    # None by default
        mem.offset = 0
        if _p4 < _p4s:   # + shift
            mem.duplex = self._duplex[2]
            mem.offset = _p4s - _p4
        if _p4 > _p4s:   # - shift
            mem.duplex = self._duplex[1]
            mem.offset = _p4 - _p4s
        mx = _p5 - 1     # CAT modes start at 1
        if _p5 == 9:     # except CAT FSK-R is 9, there is no 8
            mx = 7
        if _p6:       # LSB+Data= 8, USB+Data= 9, FM+Data= 10
            if _p5 == 1:     # CAT LSB
                mx = 8
            elif _p5 == 2:   # CAT USB
                mx = 9
            elif _p5 == 4:   # CAT FM
                mx = 10
        mem.mode = self._modes[mx]
        mem.tmode = ""
        mem.cross_mode = "Tone->Tone"
        mem.ctone = self._kenwood_valid_tones[_p9]
        mem.rtone = self._kenwood_valid_tones[_p8]
        if _p7 == 1:
            mem.tmode = "Tone"
        elif _p7 == 2:
            mem.tmode = "TSQL"
        elif _p7 == 3:
            mem.tmode = "Cross"
        mem.skip = self._skip[_p15]

        rx = RadioSettingValueBoolean(bool(_p14))
        rset = RadioSetting("fmnrw", "FM Narrow mode (off = Wide)", rx)
        mem.extra.append(rset)
        return mem

    def erase_memory(self, number):
        """ Send the blank string to MW0 """
        mem = chirp_common.Memory()
        mem.empty = True
        mem.freq = 0
        mem.offset = 0
        spx = "MW0%03i00000000000000000000000000000000000" % number
        rx = command(self.pipe, spx)      # Send MW0
        return mem

    def set_memory(self, mem):
        """Send UI column data (mem) to radio"""
        pfx = "MW0%03i" % mem.number
        xmode = 0
        xtmode = 0
        xrtone = 8
        xctone = 8
        xdata = 0
        xfltr = 0
        xfm = 0
        xskip = 0
        xfreq = mem.freq
        if xfreq > 0:       # if empty; use those defaults
            ix = self._modes.index(mem.mode)
            xmode = ix + 1     # stored as CAT values, LSB= 1
            if ix == 7:        # FSK-R
                xmode = 9     # There is no CAT 8
            if ix > 7:         # a Data mode
                xdata = 1
                if ix == 8:
                    xmode = 1      # LSB
                elif ix == 9:
                    xmode = 2      # USB
                elif ix == 10:
                    xmode = 4      # FM
            if mem.tmode == "Tone":
                xtmode = 1
                xrtone = self._kenwood_valid_tones.index(mem.rtone)
            if mem.tmode == "TSQL" or mem.tmode == "Cross":
                xtmode = 2
                if mem.tmode == "Cross":
                    xtmode = 3
                xctone = self._kenwood_valid_tones.index(mem.ctone)
            for setting in mem.extra:
                if setting.get_name() == "fmnrw":
                    xfm = setting.value
            if mem.skip == "S":
                xskip = 1
        spx = "%011i%1i%1i%1i%02i%02i000%1i0000000000%02i%1i%s" \
            % (xfreq, xmode, xdata, xtmode, xrtone,
                xctone, xfltr, xfm, xskip, mem.name)
        rx = command(self.pipe, pfx, spx)      # Send MW0
        if mem.offset != 0:
            pfx = "MW1%03i" % mem.number
            xfreq = mem.freq - mem.offset
            if mem.duplex == "+":
                xfreq = mem.freq + mem.offset
            spx = "%011i%1i%1i%1i%02i%02i000%1i0000000000%02i%1i%s" \
                % (xfreq, xmode, xdata, xtmode, xrtone,
                   xctone, xfltr, xfm, xskip, mem.name)
            rx = command(self.pipe, pfx, spx)      # Send MW1


@directory.register
class TS480Radio(KenwoodLiveRadio):
    """Kenwood TS-480"""
    MODEL = "TS-480_LiveMode"

    _kenwood_valid_tones = list(KENWOOD_TONES)
    _kenwood_valid_tones.append(1750)

    _upper = 99
    _duplex = ["", "-", "+"]
    _skip = ["", "S"]
    _modes = ["LSB", "USB", "CW", "FM", "AM", "FSK", "CW-R", "N/A",
              "FSK-R"]
    _bands = [(1800000, 2000000),    # 160M Band
              (3500000, 4000000),    # 80M Band
              (5167500, 5450000),    # 60M Band
              (7000000, 7300000),    # 40M Band
              (10100000, 10150000),  # 30M Band
              (14000000, 14350000),  # 20M Band
              (18068000, 18168000),  # 17M Band
              (21000000, 21450000),  # 15M Band
              (24890000, 24990000),  # 12M Band
              (28000000, 29700000),  # 10M Band
              (50000000, 54000000)]   # 6M Band

    _tsteps = [0.5, 1.0, 2.5, 5.0, 6.25, 10.0, 12.5,
               15.0, 20.0, 25.0, 30.0, 50.0, 100.0]

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.can_odd_split = False
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_name = True
        rf.has_settings = False
        rf.has_offset = True
        rf.has_mode = True
        rf.has_tuning_step = True
        rf.has_nostep_tuning = True
        rf.has_cross = True
        rf.has_comment = False

        rf.memory_bounds = (0, self._upper)

        rf.valid_bands = self._bands
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "*+-/"
        rf.valid_duplexes = ["", "-", "+"]
        rf.valid_modes = self._modes
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "->Tone"]
        rf.valid_name_length = 8    # 8 character channel names
        rf.valid_tuning_steps = self._tsteps

        return rf

    def _my_val_list(setting, opts, obj, atrb):
        """Callback:from ValueList. Set the integer index."""
        value = opts.index(str(setting.value))
        setattr(obj, atrb, value)
        return

    def get_memory(self, number):
        """Convert ascii channel data spec into UI columns (mem)"""
        mem = chirp_common.Memory()
        # Read the base and split MR strings
        mem.number = number
        spec0 = command(self.pipe, "MR0%03i" % mem.number)
        spec1 = command(self.pipe, "MR1%03i" % mem.number)
        # Add 1 to string idecis if refering to CAT manual
        mem.name = spec0[41:49]  # Max 8-Char Name if assigned
        mem.name = mem.name.strip()
        mem.name = mem.name.upper()
        _p4 = int(spec0[6:17])    # Rx Frequency
        _p4s = int(spec1[6:17])   # Offset freq (Tx)
        _p5 = int(spec0[17])      # Mode
        _p6 = int(spec0[18])      # Chan Lockout (Skip)
        _p7 = int(spec0[19])      # Tone Mode
        _p8 = int(spec0[20:22])   # Tone Frequency Index
        _p9 = int(spec0[22:24])   # CTCSS Frequency Index
        _p14 = int(spec0[38:40])  # Tune Step
        if _p4 == 0:
            mem.empty = True
            return mem
        mem.empty = False
        mem.freq = _p4
        mem.duplex = self._duplex[0]    # None by default
        mem.offset = 0
        if _p4 < _p4s:   # + shift
            mem.duplex = self._duplex[2]
            mem.offset = _p4s - _p4
        if _p4 > _p4s:   # - shift
            mem.duplex = self._duplex[1]
            mem.offset = _p4 - _p4s
        mx = _p5 - 1     # CAT modes start at 1
        mem.mode = self._modes[mx]
        mem.tmode = ""
        mem.cross_mode = "Tone->Tone"
        mem.ctone = self._kenwood_valid_tones[_p9]
        mem.rtone = self._kenwood_valid_tones[_p8]
        if _p7 == 1:
            mem.tmode = "Tone"
        elif _p7 == 2:
            mem.tmode = "TSQL"
        elif _p7 == 3:
            mem.tmode = "Cross"
        mem.skip = self._skip[_p6]
        # Tuning step depends on mode
        options = [0.5, 1.0, 2.5, 5.0, 10.0]    # SSB/CS/FSK
        if _p14 == 4 or _p14 == 5:   # AM/FM
            options = self._tsteps[3:]
        mem.tuning_step = options[_p14]

        return mem

    def erase_memory(self, number):
        mem = chirp_common.Memory()
        mem.empty = True
        mem.freq = 0
        mem.offset = 0
        spx = "MW0%03i00000000000000000000000000000000000" % number
        rx = command(self.pipe, spx)      # Send MW0
        return mem

    def set_memory(self, mem):
        """Send UI column data (mem) to radio"""
        pfx = "MW0%03i" % mem.number
        xtmode = 0
        xdata = 0
        xrtone = 8
        xctone = 8
        xskip = 0
        xstep = 0
        xfreq = mem.freq
        if xfreq > 0:       # if empty, use those defaults
            ix = self._modes.index(mem.mode)
            xmode = ix + 1     # stored as CAT values, LSB= 1
            if ix == 7:        # FSK-R
                xmode = 9     # There is no CAT 8
            if mem.tmode == "Tone":
                xtmode = 1
                xrtone = self._kenwood_valid_tones.index(mem.rtone)
            if mem.tmode == "TSQL" or mem.tmode == "Cross":
                xtmode = 2
                if mem.tmode == "Cross":
                    xtmode = 3
                xctone = self._kenwood_valid_tones.index(mem.ctone)
            if mem.skip == "S":
                xskip = 1
            options = [0.5, 1.0, 2.5, 5.0, 10.0]    # SSB/CS/FSK
            if xmode == 4 or xmode == 5:
                options = self._tsteps[3:]
            xstep = options.index(mem.tuning_step)
        spx = "%011i%1i%1i%1i%02i%02i00000000000000%02i%s" \
            % (xfreq, xmode, xskip, xtmode, xrtone,
                xctone, xstep, mem.name)
        rx = command(self.pipe, pfx, spx)      # Send MW0
        if mem.offset != 0:             # Don't send MW1 if empty
            pfx = "MW1%03i" % mem.number
            xfreq = mem.freq - mem.offset
            if mem.duplex == "+":
                xfreq = mem.freq + mem.offset
            spx = "%011i%1i%1i%1i%02i%02i00000000000000%02i%s" \
                  % (xfreq, xmode, xskip, xtmode, xrtone,
                     xctone, xstep, mem.name)
            rx = command(self.pipe, pfx, spx)      # Send MW1
