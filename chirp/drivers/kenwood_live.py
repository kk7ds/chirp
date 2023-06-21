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
    RadioSettingValueString, RadioSettingValueList, \
    RadioSettingValueMap, RadioSettings

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


def _command(ser, cmd, *args):
    """Send @cmd to radio via @ser"""
    global LOCK, LAST_DELIMITER, COMMAND_RESP_BUFSIZE

    start = time.time()

    # TODO: This global use of LAST_DELIMITER breaks reentrancy
    # and needs to be fixed.
    if args:
        cmd += LAST_DELIMITER[1] + LAST_DELIMITER[1].join(args)
    cmd += LAST_DELIMITER[0]

    LOG.debug("PC->RADIO: %s" % cmd.strip())
    ser.write(cmd.encode('cp1252'))

    result = ""
    while not result.endswith(LAST_DELIMITER[0]):
        result += ser.read(COMMAND_RESP_BUFSIZE).decode('cp1252')
        if (time.time() - start) > 0.5:
            LOG.error("Timeout waiting for data")
            break

    if result.endswith(LAST_DELIMITER[0]):
        LOG.debug("RADIO->PC: %r" % result.strip())
        result = result[:-1]
    else:
        LOG.error("Giving up")

    return result.strip()


def command(ser, cmd, *args):
    with LOCK:
        return _command(ser, cmd, *args)


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
            try:
                resp = command(ser, "ID")
            except UnicodeDecodeError:
                # If we got binary here, we are using the wrong rate
                # or not talking to a kenwood live radio.
                continue

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


# NOTE: There's actually a set_validate_callback() thing, but that
#       callback doesn't get the object, so it would need to be
#       a lambda or something to get the min/max values... this seemed
#       more obvious.
class KenwoodSettingProgrammableVFO(RadioSettingValueString):

    """A string setting"""

    def __init__(self, minval, maxval, current):
        minlen = len("%d" % minval)
        maxlen = len("%d" % maxval)
        start, end = current.split(',', 1)
        current = "%d-%d" % (int(start), int(end))
        LOG.debug("Current = '%s'" % current)
        RadioSettingValueString.__init__(self, minlen * 2 + 1,
                                         maxlen * 2 + 1, current,
                                         False, "0123456789-")
        self._minval = minval
        self._maxval = maxval
        self.set_value(current)

    def validate(self):
        value = self.get_value()
        LOG.debug("Validating... %s" % value)
        try:
            start, end = value.split("-", 1)
            start = int(start)
            end = int(end)
            if start > end:  # TODO: Set current value back on error...
                raise errors.RadioError("Start must be less than or equal "
                                        "to end")
            if (start < self._minval):
                raise errors.RadioError("Start must be greater than or equal "
                                        "to %d" % self._minval)
            if (start > self._maxval):
                raise errors.RadioError("Start must be less than or equal "
                                        "to %d" % self._maxval)
            if (end < self._minval):
                raise errors.RadioError("End must be greater than or equal "
                                        "to %d" % self._minval)
            if (end > self._maxval):
                raise errors.RadioError("End must be less than or equal to " +
                                        "%d" % self._maxval)
        except errors.RadioError:
            raise
        except:
            raise errors.RadioError("Programmable VFO must be Start-End " +
                                    "format (ie: 144-147)")
        return "%05d,%05d" % (start, end)


class KenwoodLiveRadio(chirp_common.LiveRadio):
    """Base class for all live-mode kenwood radios"""
    BAUD_RATE = 9600
    VENDOR = "Kenwood"
    MODEL = ""
    NEEDS_COMPAT_SERIAL = False
    # Lots of Kenwood radios actually require RTS, even some of the ones with
    # USB integrated
    HARDWARE_FLOW = True

    _vfo = 0
    _upper = 200
    _kenwood_split = False
    _kenwood_valid_tones = list(chirp_common.TONES)
    _has_name = True

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

    def _cmd_get_memory(self, number, cmd="MR"):
        if isinstance(number, str):
            return cmd, "%i,0,%s" % (self._vfo, number)
        return cmd, "%i,0,%03i" % (self._vfo, number)

    def _cmd_get_memory_name(self, number):
        return "MNA", "%i,%03i" % (self._vfo, number)

    def _cmd_get_split(self, number, cmd="MR"):
        if isinstance(number, str):
            return cmd, "%i,1,%s" % (self._vfo, number)
        return cmd, "%i,1,%03i" % (self._vfo, number)

    def _cmd_set_memory(self, number, spec, cmd="MW"):
        if spec:
            spec = "," + spec
        if isinstance(number, str):
            return cmd, "%i,0,%s%s" % (self._vfo, number, spec)
        return cmd, "%i,0,%03i%s" % (self._vfo, number, spec)

    def _cmd_set_memory_name(self, number, name):
        return "MNA", "%i,%03i,%s" % (self._vfo, number, name)

    def _cmd_set_split(self, number, spec, cmd="MW"):
        return cmd, "%i,1,%03i,%s" % (self._vfo, number, spec)

    def get_raw_memory(self, number):
        return command(self.pipe, *self._cmd_get_memory(number))

    def _get_special_memory(self, number, write):
        name = None
        cmd = write and "MW" or "MR"
        if self._program_scan_lower is not None \
                and self._program_scan_upper is not None \
                and number >= self._program_scan_lower \
                and number <= self._program_scan_upper:
            number -= self._program_scan_lower
            if (number % 2) == (self._program_scan_lower % 2):
                number = "L%d" % int(number / 2)
            else:
                number = "U%d" % int(number / 2)
            name = number
        elif self._callmem_lower is not None \
                and self._callmem_upper is not None \
                and number >= self._callmem_lower \
                and number <= self._callmem_upper:
            cmd = write and "CW" or "CR"
            number -= self._callmem_lower
            name = "Call %d" % (number)
        elif number < 0 or number > self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % self._upper)
        return (name, number, cmd)


    def get_memory(self, number):
        name, cmdnum, read_cmd = self._get_special_memory(number, False)
        if number in self._memcache and not NOCACHE:
            return self._memcache[number]

        result = command(self.pipe, *self._cmd_get_memory(cmdnum, read_cmd))
        if result == "N" or result == "E":
            mem = chirp_common.Memory()
            if self._has_name:
                if name is not None:
                    if mem.immutable == []:
                        mem.name = name
                        mem.immutable = ['name', 'skip']
            mem.number = number
            if name is None:
                mem.empty = True
            self._memcache[mem.number] = mem
            return mem
        elif " " not in result:
            LOG.error("Not sure what to do with this: `%s'" % result)
            raise errors.RadioError("Unexpected result returned from radio")

        value = result.split(" ")[1]
        spec = value.split(",")

        mem = self._parse_mem_spec(spec, read_cmd)
        self._memcache[mem.number] = mem

        if self._has_name:
            if name is not None:
                if mem.immutable == []:
                    mem.name = name
                    mem.immutable = ['name', 'skip']
            else:
                result = command(self.pipe, *self._cmd_get_memory_name(cmdnum))
                if " " in result:
                    value = result.split(" ", 1)[1]
                    if value.count(",") == 2:
                        _zero, _loc, mem.name = value.split(",")
                    else:
                        _loc, mem.name = value.split(",")

        if mem.duplex == "" and self._kenwood_split:
            result = command(self.pipe, *self._cmd_get_split(cmdnum, read_cmd))
            if " " in result:
                value = result.split(" ", 1)[1]
                self._parse_split_spec(mem, value.split(","), read_cmd)

        return mem

    def _make_mem_spec(self, mem, cmd="MW"):
        pass

    def _parse_mem_spec(self, spec, read_cmd="MR"):
        pass

    def _parse_split_spec(self, mem, spec, cmd="MR"):
        mem.duplex = "split"
        mem.offset = int(spec[2])

    def _make_split_spec(self, mem, cmd="MW"):
        return ("%011i" % mem.offset, "0")

    def set_memory(self, memory):
        name, cmdnum, read_cmd = self._get_special_memory(number, True)
        spec = self._make_mem_spec(memory, write_cmd)
        spec = ",".join(spec)
        r1 = command(self.pipe, *self._cmd_set_memory(cmdnum, spec, write_cmd))
        if not iserr(r1) and name is None and self._has_name:
            time.sleep(0.5)
            r2 = command(self.pipe, *self._cmd_set_memory_name(cmdnum,
                                                               memory.name))
            if not iserr(r2):
                memory.name = memory.name.rstrip()
                self._memcache[memory.number] = memory
            else:
                raise errors.InvalidDataError("Radio refused name %i: %s" %
                                              (memory.number,
                                               repr(memory.name)))
        elif self._has_name and name is None:
            raise errors.InvalidDataError("Radio refused %i" % memory.number)
        elif self._has_name and name is not None:
            self._memcache[memory.number] = memory

        if memory.duplex == "split" and self._kenwood_split:
            spec = ",".join(self._make_split_spec(memory, write_cmd))
            result = command(self.pipe, *self._cmd_set_split(cmdnum,
                                                             spec, write_cmd))
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
            elif isinstance(element.value, KenwoodSettingProgrammableVFO):
                self._kenwood_set(element.get_name(), element.value.validate())
            elif isinstance(element.value, RadioSettingValueMap):
                self._kenwood_set(element.get_name(),
                                  element.value.get_mem_val())
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
            # TODO: Is there a way to keep it from re-sending everything
            #       on every change?


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
    HARDWARE_FLOW = False

    _kenwood_split = True
    _upper = 199
    _program_scan_lower = 200
    _program_scan_upper = 219
    _callmem_lower = 220
    _callmem_upper = 221

    DTMF_CHARSET = "ABCD#*0123456789 "
    SSTV_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !?-/"

    _BEP_OPTIONS = ["Off", "Key", "Key+Data", "All"]
    _POSC_OPTIONS = ["Off Duty", "Enroute", "In Service", "Returning",
                     "Committed", "Special", "Priority", "Emergency"]

    SQUELCH_LEVELS = [("Open", "00"), ("1", "01"), ("2", "02"),
                      ("3", "03"), ("4", "04"), ("5", "05")]

    _SETTINGS_MAPS = {
        "ARL": [("Off", "0000"), ("10", "0010"), ("20", "0020"),
                ("30", "0030"), ("40", "0040"), ("50", "0050"),
                ("60", "0060"), ("70", "0070"), ("80", "0080"),
                ("90", "0090"), ("100", "0100"), ("110", "0110"),
                ("120", "0120"), ("130", "0130"), ("140", "0140"),
                ("150", "0150"), ("160", "0160"), ("170", "0170"),
                ("180", "0180"), ("190", "0190"), ("200", "0200"),
                ("210", "0210"), ("220", "0220"), ("230", "0230"),
                ("240", "0240"), ("250", "0250"), ("260", "0260"),
                ("270", "0270"), ("280", "0280"), ("290", "0290"),
                ("300", "0300"), ("310", "0310"), ("320", "0320"),
                ("330", "0330"), ("340", "0340"), ("350", "0350"),
                ("360", "0360"), ("370", "0370"), ("380", "0380"),
                ("390", "0390"), ("400", "0400"), ("410", "0410"),
                ("420", "0420"), ("430", "0430"), ("440", "0440"),
                ("450", "0450"), ("460", "0460"), ("470", "0470"),
                ("480", "0480"), ("490", "0490"), ("500", "0500"),
                ("510", "0510"), ("520", "0520"), ("530", "0530"),
                ("540", "0540"), ("550", "0550"), ("560", "0560"),
                ("570", "0570"), ("580", "0580"), ("590", "0590"),
                ("600", "0600"), ("610", "0610"), ("620", "0620"),
                ("630", "0630"), ("640", "0640"), ("650", "0650"),
                ("660", "0660"), ("670", "0670"), ("680", "0680"),
                ("690", "0690"), ("700", "0700"), ("710", "0710"),
                ("720", "0720"), ("730", "0730"), ("740", "0740"),
                ("750", "0750"), ("760", "0760"), ("770", "0770"),
                ("780", "0780"), ("790", "0790"), ("800", "0800"),
                ("810", "0810"), ("820", "0820"), ("830", "0830"),
                ("840", "0840"), ("850", "0850"), ("860", "0860"),
                ("870", "0870"), ("880", "0880"), ("890", "0890"),
                ("900", "0900"), ("910", "0910"), ("920", "0920"),
                ("930", "0930"), ("940", "0940"), ("950", "0950"),
                ("960", "0960"), ("970", "0970"), ("980", "0980"),
                ("990", "0990"), ("1000", "1000"), ("1010", "1010"),
                ("1020", "1020"), ("1030", "1030"), ("1040", "1040"),
                ("1050", "1050"), ("1060", "1060"), ("1070", "1070"),
                ("1080", "1080"), ("1090", "1090"), ("1100", "1100"),
                ("1110", "1110"), ("1120", "1120"), ("1130", "1130"),
                ("1140", "1140"), ("1150", "1150"), ("1160", "1160"),
                ("1170", "1170"), ("1180", "1180"), ("1190", "1190"),
                ("1200", "1200"), ("1210", "1210"), ("1220", "1220"),
                ("1230", "1230"), ("1240", "1240"), ("1250", "1250"),
                ("1260", "1260"), ("1270", "1270"), ("1280", "1280"),
                ("1290", "1290"), ("1300", "1300"), ("1310", "1310"),
                ("1320", "1320"), ("1330", "1330"), ("1340", "1340"),
                ("1350", "1350"), ("1360", "1360"), ("1370", "1370"),
                ("1380", "1380"), ("1390", "1390"), ("1400", "1400"),
                ("1410", "1410"), ("1420", "1420"), ("1430", "1430"),
                ("1440", "1440"), ("1450", "1450"), ("1460", "1460"),
                ("1470", "1470"), ("1480", "1480"), ("1490", "1490"),
                ("1500", "1500"), ("1510", "1510"), ("1520", "1520"),
                ("1530", "1530"), ("1540", "1540"), ("1550", "1550"),
                ("1560", "1560"), ("1570", "1570"), ("1580", "1580"),
                ("1590", "1590"), ("1600", "1600"), ("1610", "1610"),
                ("1620", "1620"), ("1630", "1630"), ("1640", "1640"),
                ("1650", "1650"), ("1660", "1660"), ("1670", "1670"),
                ("1680", "1680"), ("1690", "1690"), ("1700", "1700"),
                ("1710", "1710"), ("1720", "1720"), ("1730", "1730"),
                ("1740", "1740"), ("1750", "1750"), ("1760", "1760"),
                ("1770", "1770"), ("1780", "1780"), ("1790", "1790"),
                ("1800", "1800"), ("1810", "1810"), ("1820", "1820"),
                ("1830", "1830"), ("1840", "1840"), ("1850", "1850"),
                ("1860", "1860"), ("1870", "1870"), ("1880", "1880"),
                ("1890", "1890"), ("1900", "1900"), ("1910", "1910"),
                ("1920", "1920"), ("1930", "1930"), ("1940", "1940"),
                ("1950", "1950"), ("1960", "1960"), ("1970", "1970"),
                ("1980", "1980"), ("1990", "1990"), ("2000", "2000"),
                ("2010", "2010"), ("2020", "2020"), ("2030", "2030"),
                ("2040", "2040"), ("2050", "2050"), ("2060", "2060"),
                ("2070", "2070"), ("2080", "2080"), ("2090", "2090"),
                ("2100", "2100"), ("2110", "2110"), ("2120", "2120"),
                ("2130", "2130"), ("2140", "2140"), ("2150", "2150"),
                ("2160", "2160"), ("2170", "2170"), ("2180", "2180"),
                ("2190", "2190"), ("2200", "2200"), ("2210", "2210"),
                ("2220", "2220"), ("2230", "2230"), ("2240", "2240"),
                ("2250", "2250"), ("2260", "2260"), ("2270", "2270"),
                ("2280", "2280"), ("2290", "2290"), ("2300", "2300"),
                ("2310", "2310"), ("2320", "2320"), ("2330", "2330"),
                ("2340", "2340"), ("2350", "2350"), ("2360", "2360"),
                ("2370", "2370"), ("2380", "2380"), ("2390", "2390"),
                ("2400", "2400"), ("2410", "2410"), ("2420", "2420"),
                ("2430", "2430"), ("2440", "2440"), ("2450", "2450"),
                ("2460", "2460"), ("2470", "2470"), ("2480", "2480"),
                ("2490", "2490"), ("2500", "2500")],
        "ASC 0": [("Off", "0"), ("On", "1,0")],
        "ASC 1": [("Off", "0"), ("On", "1,0")],
        "BEL 0": [("Off", "0"), ("On", "1,0")],
        "BEL 1": [("Off", "0"), ("On", "1,0")],
        "SKTN": [("67.0", "01"), ("71.9", "03"), ("74.4", "04"),
                 ("77.0", "05"), ("79.7", "06"), ("82.5", "07"),
                 ("85.4", "08"), ("88.5", "09"), ("91.5", "10"),
                 ("94.8", "11"), ("97.4", "12"), ("100.0", "13"),
                 ("103.5", "14"), ("107.2", "15"), ("110.9", "16"),
                 ("114.8", "17"), ("118.8", "18"), ("123.0", "19"),
                 ("127.3", "20"), ("131.8", "21"), ("136.5", "22"),
                 ("141.3", "23"), ("146.2", "24"), ("151.4", "25"),
                 ("156.7", "26"), ("162.2", "27"), ("167.9", "28"),
                 ("173.8", "29"), ("179.9", "30"), ("186.2", "31"),
                 ("192.8", "32"), ("203.5", "33"), ("210.7", "34"),
                 ("218.1", "35"), ("225.7", "36"), ("233.6", "37"),
                 ("241.8", "38"), ("250.3", "39")],
        "ICO": [('Kenwood', '0,0'),
                ('Runner', '0,1'),
                ('House ', '0,2'),
                ('Tent', '0,3'),
                ('Boat', '0,4'),
                ('SSTV', '0,5'),
                ('Plane', '0,6'),
                ('Speedboat', '0,7'),
                ('Car', '0,8'),
                ('Bicycle', '0,9')],
        "SQ 0": SQUELCH_LEVELS,
        "SQ 1": SQUELCH_LEVELS,
    }

    SSTV_COLOURS = ["Black", "Blue", "Red", "Magenta", "Green", "Cyan",
                    "Yellow", "White"]
    POWER_LEVELS = ["High", "Low", "Economic Low"]

    _SETTINGS_OPTIONS = {
        "APO": ["Off", "30min", "60min"],
        "BAL": ["4:0", "3:1", "2:2", "1:3", "0:4"],
        "BC": ["A", "B"],
        "BEP": None,
        "BEPT": ["Off", "Mine", "All New"],  # D700 has fourth "All"
        "DS": ["Data Band", "Both Bands"],
        "DTB": ["A", "B"],
        "DTBA": ["A", "B", "A:TX/B:RX"],  # D700 has fourth A:RX/B:TX
        "DTX": ["Manual", "PTT", "Auto"],
        "GU": ["Not Used", "NMEA"],
        "MAC": SSTV_COLOURS,
        "MNF": ["Name", "Frequency"],  # Can only be set in Memory mode...
        "PC 0": POWER_LEVELS,
        "PC 1": POWER_LEVELS,
        "PKSA": ["1200", "9600"],
        "POSC": None,
        "PT": ["100ms", "200ms", "500ms", "750ms",
               "1000ms", "1500ms", "2000ms"],
        "RSC": SSTV_COLOURS,
        "SCR": ["Time", "Carrier", "Seek"],
        "SMC": SSTV_COLOURS,
        "SV": ["Off", "0.2s", "0.4s", "0.6s", "0.8s", "1.0s",
               "2s", "3s", "4s", "5s"],
        "TEMP": ["Mile and °F", "Kilometer and °C"],
        "TXI": ["30sec", "1min", "2min", "3min", "4min", "5min",
                "10min", "20min", "30min"],
        "UNIT": ["English", "Metric"],
        "WAY": ["Off", "6 digit NMEA", "7 digit NMEA", "8 digit NMEA",
                "9 digit NMEA", "6 digit Magellan", "DGPS"],
    }

    _PROGRAMMABLE_VFOS = [
        ("Band A, 118MHz Sub-Band", 1, 118, 135),
        ("Band A, VHF Sub-Band", 2, 136, 173),
        ("Band B, VHF Sub-Band", 3, 144, 147),
        ("Band B, UHF Sub-Band", 6, 400, 479),
    ]

    def __init__(self, *args, **kwargs):
        if self.MODEL == "TH-D7" or self.MODEL == "TH-D7G":
            chirp_common.LiveRadio.__init__(self, *args, **kwargs)

            self._memcache = {}

            if self.pipe:
                self.pipe.timeout = 0.1
                global LAST_BAUD
                LAST_BAUD = 9600
                global LAST_DELIMITER
                LAST_DELIMITER = ("\r", " ")
                LOG.info("Trying ID at baud %d with delimiter \"%s\"" %
                         (LAST_BAUD, repr(LAST_DELIMITER)))
                self.pipe.baudrate = LAST_BAUD
                self.pipe.write(LAST_DELIMITER[0].encode())
                self.pipe.read(25)
                radio_id = None
                for i in range(3):
                    try:
                        resp = command(self.pipe, "ID")
                    except UnicodeDecodeError:
                        # If we got binary here, we are using the wrong rate
                        # or not talking to a kenwood live radio.
                        raise errors.RadioError("Garbage response from radio")

                    # most kenwood radios
                    if " " in resp:
                        radio_id = resp.split(" ")[1]
                        break

                if radio_id is None:
                    raise errors.RadioError("Invalid response from radio")

                if radio_id != self.MODEL.split(" ")[0]:
                    raise Exception("Radio reports %s (not %s)" % (radio_id,
                                                                   self.MODEL))

                command(self.pipe, "BCN", "0")  # TODO: Save/restore?
                command(self.pipe, "TNC", "0")
                command(self.pipe, "AI", "0")
                self.pipe.read(25)
        else:
            KenwoodLiveRadio.__init__(self, *args, **kwargs)

    def degsub(self, minuend, subtrahend):
        m = list(minuend)
        s = list(subtrahend)
        res = [None] * 3
        for i in (2, 1):
            res[i] = m[i] - s[i]
            if res[i] < 0:
                res[i] += 60
                m[i-1] -= 1
        res[0] = m[0] - s[0]
        return tuple(res)

    def _kenwood_pos_to_maidenhead(self, posstr):
        lat = (int(posstr[0:2]), int(posstr[2:4]),
               int(int(posstr[4:6]) * 60 / 100))
        lon = (int(posstr[8:11]), int(posstr[11:13]),
               int(int(posstr[13:15]) * 60 / 100))
        if posstr[6:8] == '01':
            lat = self.degsub((90, 0, 0), lat)
        else:
            lat = (lat[0] + 90, lat[1], lat[2])
        if posstr[15:17] == '01':
            lon = self.degsub((180, 0, 0), lon)
        else:
            lon = (lon[0] + 180, lat[1], lat[2])
        ret = ''
        ret += chr(65 + int(lon[0] / 20))
        ret += chr(65 + int(lat[0] / 10))
        ret += chr(48 + int((lon[0] % 20) / 2))
        ret += chr(48 + int(lat[0] % 10))
        ret += chr(97 + int(lon[1] / 5) + ((lon[0] % 2) * 12))
        ret += chr(97 + int((lat[1] * 2) / 5))
        ret += chr(48 + int(lon[2] / 30) + ((lon[1] % 5) * 2))
        ret += chr(48 + int((lat[2] + (((lat[1] * 2) % 5)*30)) / 15))
        ret += chr(97 + int((lon[2] % 30) * 24 / 30))
        ret += chr(97 + int((lat[2] % 15) * 24 / 15))
        return ret

    def _kenwood_maidenhead_to_pos(self, m):
        latd = 0
        lond = 0
        latm = 0
        lonm = 0
        if len(m) >= 2:
            lond += (ord(m[0:1].upper()) - 65) * 20
            latd += (ord(m[1:2].upper()) - 65) * 10
        else:
            lond += 180
            latd += 90

        if len(m) >= 4:
            lond += (ord(m[2:3]) - 48) * 2
            latd += (ord(m[3:4]) - 48)
        else:
            lond += 1
            latm += 3000

        if len(m) >= 6:
            lonm += (ord(m[4:5].upper()) - 65) * 500
            if lonm >= 6000:
                lond += 1
                lonm -= 6000
            latm += (ord(m[5:6].upper()) - 65) * 250
        else:
            lond += 1
            latm += 30

        if len(m) >= 8:
            lonm += (ord(m[6:7]) - 48) * 50
            latm += (ord(m[7:8]) - 48) * 25
        else:
            lonm += 250
            latm += 125

        if len(m) >= 10:
            lonm += (ord(m[8:9].upper()) - 65) * (50 / 24)
            latm += (ord(m[9:10].upper()) - 65) * (25 / 24)
        else:
            lonm += (25 / 24)
            latm += (25 / 48)

        lond = lond - 180
        latd = latd - 90
        if latd < 0:
            latdir = 1
            latd = abs(latd)
            latm = 6000 - latm
            if latm == 6000:
                latm = 0
            else:
                latd -= 1
        else:
            latdir = 0
        if lond < 0:
            londir = 1
            lond = abs(lond)
            lonm = 6000 - lonm
            if lonm == 6000:
                lonm = 0
            else:
                lond -= 1
        else:
            londir = 0
        return "%02u%04u%02u%03u%04u%02u" % (latd, latm, latdir,
                                             lond, lonm, londir)

    def _kenwood_get(self, cmd):
        if " " in cmd:
            suffix = cmd.split(" ", 1)[1]
            resp = super()._kenwood_get(cmd)
            if resp[1][0:len(suffix)+1] == suffix + ',':
                resp = (cmd, resp[1][len(suffix)+1:])
                if cmd[0:3] == 'DM ':
                    clean = resp[1].replace("E", "*").replace("F", "#")
                    resp = (resp[0], clean)
                if cmd[0:3] == 'MP ':
                    resp = (resp[0], self._kenwood_pos_to_maidenhead(resp[1]))
                return resp
            raise errors.RadioError("Command %s response value '%s' unusable"
                                    % (cmd, resp[1]))
        else:
            return super()._kenwood_get(cmd)

    def _kenwood_set(self, cmd, value):
        if " " in cmd:
            if cmd[0:3] == 'DM ':
                value = value.replace("*", "E").replace("#", "F")
            elif cmd[0:3] == 'MP ':
                value = self._kenwood_maidenhead_to_pos(value)
            resp = command(self.pipe, cmd + "," + value)
            cmd = cmd.split(" ", 1)[0]
        else:
            resp = command(self.pipe, cmd, value)
        if resp[:len(cmd)] == cmd:
            return
        raise errors.RadioError("Radio refused to set %s" % cmd)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = True
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_modes = list(MODES.values())
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_characters = \
            chirp_common.CHARSET_ALPHANUMERIC + "/.-+*)('&%$#! ~}|{"
        rf.valid_name_length = 7
        rf.valid_tuning_steps = STEPS
        upper = self._upper
        if self._callmem_lower is not None and self._callmem_upper is not None:
            upper += self._callmem_upper - self._callmem_lower + 1
        if self._program_scan_lower is not None \
                and self._program_scan_upper is not None:
            upper += self._program_scan_upper - self._program_scan_lower + 1
        rf.memory_bounds = (0, upper)
        return rf

    def _cmd_get_memory(self, number, cmd="MR"):
        if cmd == "CR":
            return cmd, "%i,0" % (number)
        return super()._cmd_get_memory(number, cmd)

    def _cmd_get_split(self, number, cmd="MR"):
        if cmd == "CR":
            return cmd, "%i,1" % (number)
        return super()._cmd_get_split(number, cmd)

    def _cmd_set_memory(self, number, spec, cmd="MW"):
        if cmd == "CW":
            if spec:
                spec = "," + spec
            return cmd, "%i,0%s" % (number, spec)
        return super()._cmd_set_memory(number, spec, cmd)

    def _cmd_set_split(self, number, spec, cmd="MW"):
        if cmd == "CW":
            return cmd, "%i,0%s" % (number, spec)
        return super()._cmd_set_split(number, spec, cmd)

    def _make_mem_spec(self, mem, cmd="MW"):
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
            "%i" % util.get_dict_rev(MODES, mem.mode))
        if cmd == "MW":
            spec.append("%i" % ((mem.skip == "S") and 1 or 0))

        return spec

    def _parse_split_spec(self, mem, spec, cmd="MR"):
        if cmd == "CR":
            spec.insert(0, 0)
        mem.duplex = "split"
        mem.offset = int(spec[2])

    def _parse_mem_spec(self, spec, read_cmd):
        mem = chirp_common.Memory()

        if read_cmd == "CR":
            spec.insert(1, 0)
            mem.number = self._callmem_lower + int(spec[0])
        elif spec[2][0:1] == 'L':
            mem.number = int(spec[2][1:]) * 2 + self._program_scan_lower
        elif spec[2][0:1] == 'U':
            mem.number = int(spec[2][1:]) * 2 + self._program_scan_lower + 1
        else:
            mem.number = int(spec[2])
        mem.freq = int(spec[3], 10)
        mem.tuning_step = STEPS[int(spec[4], 16)]
        mem.duplex = DUPLEX[int(spec[5])]
        mem.tmode = get_tmode(spec[7], spec[8], spec[9])
        mem.rtone = self._kenwood_valid_tones[int(spec[10]) - 1]
        mem.ctone = self._kenwood_valid_tones[int(spec[12]) - 1]
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11][:-1]) - 1]
        elif spec[11] == '':
            pass
        else:
            LOG.warn("Unknown or invalid DCS: %s" % spec[11])
        if spec[13]:
            mem.offset = int(spec[13])
        else:
            mem.offset = 0
        mem.mode = MODES[int(spec[14])]
        if len(spec) > 15 and spec[15]:
            mem.skip = int(spec[15]) and "S" or ""
        else:
            mem.skip = ""
        return mem

    EXTRA_BOOL_SETTINGS = {
        'aux': [("ELK", "Enable Tune When Locked"),
                ("TXS", "Transmit Inhibit")],
        'dtmf': [("TXH", "TX Hold")],
        'main': [("LMP", "Lamp")],
    }
    EXTRA_LIST_SETTINGS = {
        'main': [("BAL", "Balance"),
                 #("MNF", "Memory Display Mode")  Only available in MR mode, not VFO mode
                ],
        'save': [("SV", "Battery Save")],
        'aprs': [("TEMP", "APRS Units")],
    }
    EXTRA_INT_SETTINGS = {
    }
    MAIDENHEAD_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWX" + \
                         "abcdefghijklmnopqrstuvwx"
    EXTRA_STRING_SETTINGS = {
        'aprs': [("MP 1", "My Position 1", 10, MAIDENHEAD_CHARSET),
                 ("MP 2", "My Position 2", 10, MAIDENHEAD_CHARSET),
                 ("MP 3", "My Position 3", 10, MAIDENHEAD_CHARSET)],
    }
    EXTRA_MAP_SETTINGS = {
        'main': [("BEL 0", "Tone Alert Band A"),
                 ("BEL 1", "Tone Alert Band B"),
                 ("SQ 0", "Band A Squelch"),
                 ("SQ 1", "Band B Squelch")],
    }

    def _get_setting_options(self, setting):
        try:
            opts = getattr(self, '_%s_OPTIONS' % setting)
        except AttributeError:
            opts = self._SETTINGS_OPTIONS[setting]
        return opts

    def _get_setting_map(self, setting):
        try:
            LOG.debug("Getting map for _%s_MAP" % setting)
            vmap = getattr(self, '_%s_MAP' % setting)
        except AttributeError:
            LOG.debug("Failed, using settings map")
            vmap = self._SETTINGS_MAPS[setting]
        return vmap

    def get_settings(self):
        main = RadioSettingGroup("main", "Main")
        aux = RadioSettingGroup("aux", "Aux")
        tnc = RadioSettingGroup("tnc", "TNC")
        save = RadioSettingGroup("save", "Save")
        display = RadioSettingGroup("display", "Display")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        radio = RadioSettingGroup("radio", "Radio",
                                  aux, tnc, save, display, dtmf)
        sstv = RadioSettingGroup("sstv", "SSTV")
        sky = RadioSettingGroup("sky", "SkyCommand")
        aprs = RadioSettingGroup("aprs", "APRS")

        top = RadioSettings(main, radio, aprs, sstv, sky)

        bools = [("AMR", aprs, "APRS Message Auto-Reply"),
                 ("AIP", aux, "Advanced Intercept Point"),
                 ("ARO", aux, "Automatic Repeater Offset"),
                 ("BCN", aprs, "Beacon"),
                 ("CH", main, "Channel Mode Display"),
                 ("DL", main, "Dual"),
                 ("LK", main, "Lock"),
                 ("TNC", main, "Packet Mode"),
                 ("TSP", dtmf, "DTMF Fast Transmission"),
                 ("VCS", sstv, "VC Shutter"),
                 ]

        for setting, group, name in bools:
            value = self._kenwood_get_bool(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueBoolean(value))
            group.append(rs)

        for group_name, settings in self.EXTRA_BOOL_SETTINGS.items():
            group = locals()[group_name]
            for setting, name in settings:
                value = self._kenwood_get_bool(setting)
                rs = RadioSetting(setting, name,
                                  RadioSettingValueBoolean(value))
                group.append(rs)

        lists = [("APO", save, "Automatic Power Off"),
                 ("BC", main, "Band"),
                 ("BEP", aux, "Beep"),
                 ("BEPT", aprs, "APRS Beep"),
                 ("DS", tnc, "Data Sense"),
                 ("DTB", tnc, "Data Band"),
                 ("DTBA", aprs, "APRS Data Band"),
                 ("DTX", aprs, "APRS Data TX"),
                 ("GU", aprs, "GPS Unit"),
                 ("MAC", sstv, "Callsign Colour"),
                 ("PKSA", aprs, "APRS Packet Speed"),
                 ("POSC", aprs, "APRS Position Comment"),
                 ("PT", dtmf, "DTMF Pause Duration"),
                 ("RSC", sstv, "RSV Colour"),
                 ("SCR", aux, "Scan Resume"),
                 ("SMC", sstv, "Message Colour"),
                 ("TXI", aprs, "APRS Transmit Interval"),
                 ("WAY", aprs, "Waypoint Mode"),
                 ]

        for setting, group, name in lists:
            value = self._kenwood_get_int(setting)
            options = self._get_setting_options(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueList(options,
                                                    options[value]))
            group.append(rs)

        for group_name, settings in self.EXTRA_LIST_SETTINGS.items():
            group = locals()[group_name]
            for setting, name in settings:
                value = self._kenwood_get_int(setting)
                options = self._get_setting_options(setting)
                rs = RadioSetting(setting, name,
                                  RadioSettingValueList(options,
                                                        options[value]))
                group.append(rs)

        ints = [("CNT", display, "Contrast", 1, 16),
                ]

        for setting, group, name, minv, maxv in ints:
            value = self._kenwood_get_int(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueInteger(minv, maxv, value))
            group.append(rs)

        for group_name, settings in self.EXTRA_INT_SETTINGS.items():
            group = locals()[group_name]
            for setting, name, minv, maxv in settings:
                value = self._kenwood_get_int(setting)
                rs = RadioSetting(setting, name,
                                  RadioSettingValueInteger(minv, maxv, value))
                group.append(rs)

        strings = [("DMN 00", dtmf, "DTMF Memory 0 Name", 8),
                   ("DM 00", dtmf, "DTMF Memory 0", 16, self.DTMF_CHARSET),
                   ("DMN 01", dtmf, "DTMF Memory 1 Name", 8),
                   ("DM 01", dtmf, "DTMF Memory 1", 16, self.DTMF_CHARSET),
                   ("DMN 02", dtmf, "DTMF Memory 2 Name", 8),
                   ("DM 02", dtmf, "DTMF Memory 2", 16, self.DTMF_CHARSET),
                   ("DMN 03", dtmf, "DTMF Memory 3 Name", 8),
                   ("DM 03", dtmf, "DTMF Memory 3", 16, self.DTMF_CHARSET),
                   ("DMN 04", dtmf, "DTMF Memory 4 Name", 8),
                   ("DM 04", dtmf, "DTMF Memory 4", 16, self.DTMF_CHARSET),
                   ("DMN 05", dtmf, "DTMF Memory 5 Name", 8),
                   ("DM 05", dtmf, "DTMF Memory 5", 16, self.DTMF_CHARSET),
                   ("DMN 06", dtmf, "DTMF Memory 6 Name", 8),
                   ("DM 06", dtmf, "DTMF Memory 6", 16, self.DTMF_CHARSET),
                   ("DMN 07", dtmf, "DTMF Memory 7 Name", 8),
                   ("DM 07", dtmf, "DTMF Memory 7", 16, self.DTMF_CHARSET),
                   ("DMN 08", dtmf, "DTMF Memory 8 Name", 8),
                   ("DM 08", dtmf, "DTMF Memory 8", 16, self.DTMF_CHARSET),
                   ("DMN 09", dtmf, "DTMF Memory 9 Name", 8),
                   ("DM 09", dtmf, "DTMF Memory 9", 16, self.DTMF_CHARSET),
                   ("MES", display, "Power-on Message", 8),
                   ("MYC", aprs, "APRS Callsign", 9),
                   ("PP", aprs, "APRS Path", 32),
                   ("RSV", sstv, "SSTV RSV", 10, self.SSTV_CHARSET),
                   ("SCC", sky, "SkyCommand Commander Callsign", 8),
                   ("SCT", sky, "SkyCommand Transporter Callsign", 8),
                   ("SMY", sstv, "SSTV Callsign", 8, self.SSTV_CHARSET),
                   ("SMSG", sstv, "SSTV Message", 9, self.SSTV_CHARSET),
                   ("STAT 1", aprs, "Status Text #1", 32),
                   ("STAT 2", aprs, "Status Text #2", 32),
                   ("STAT 3", aprs, "Status Text #3", 32),
                   ("UPR", aprs, "Group Code", 9,
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ-0123456789")]

        for setting, group, name, length, *charset in strings:
            _cmd, value = self._kenwood_get(setting)
            if charset == []:
                rs = RadioSetting(setting, name,
                                  RadioSettingValueString(0, length,
                                                          value, False))
            else:
                rsvs = RadioSettingValueString(0, length, value, False,
                                               charset=charset[0])
                rs = RadioSetting(setting, name, rsvs)
            group.append(rs)

        for group_name, settings in self.EXTRA_STRING_SETTINGS.items():
            group = locals()[group_name]
            for setting, name, length, *charset in settings:
                _cmd, value = self._kenwood_get(setting)
                if charset == []:
                    rs = RadioSetting(setting, name,
                                      RadioSettingValueString(0, length,
                                                              value, False))
                else:
                    rsvs = RadioSettingValueString(0, length,
                                                   value, False,
                                                   charset=charset[0])
                    rs = RadioSetting(setting, name, rsvs)
                group.append(rs)

        maps = [("ARL", aprs, "Reception Restriction Distance"),
                ("ASC 0", main, "Automatic Simplex Check Band A"),
                ("ASC 1", main, "Automatic Simplex Check Band B"),
                ("ICO", aprs, "Icon"),
                ("SKTN", sky, "Tone Frequency"),
                ]

        for setting, group, name in maps:
            value = self._kenwood_get(setting)[1]
            vmap = self._get_setting_map(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueMap(vmap,
                                                   value))
            group.append(rs)

        for group_name, settings in self.EXTRA_MAP_SETTINGS.items():
            group = locals()[group_name]
            for setting, name in settings:
                value = self._kenwood_get(setting)[1]
                vmap = self._get_setting_map(setting)
                rs = RadioSetting(setting, name,
                                  RadioSettingValueMap(vmap,
                                                       value))
                group.append(rs)

        for pvfo in self._PROGRAMMABLE_VFOS:
            cmd = "PV %d" % pvfo[1]
            value = self._kenwood_get(cmd)[1]
            rs = RadioSetting("PV %d" % pvfo[1], pvfo[0],
                              KenwoodSettingProgrammableVFO(pvfo[2],
                                                            pvfo[3],
                                                            value))
            main.append(rs)

        return top


@directory.register
class THD7GRadio(THD7Radio):
    """Kenwood TH-D7G"""
    MODEL = "TH-D7G"

    _upper = 199
    _program_scan_lower = _upper + 1
    _program_scan_upper = _program_scan_lower + 19
    _callmem_lower = _program_scan_upper + 1
    _callmem_upper = _callmem_lower + 1

    _ICO_MAP = [('Kenwood', '0,0'),
                ('Runner', '0,1'),
                ('House ', '0,2'),
                ('Tent', '0,3'),
                ('Boat', '0,4'),
                ('SSTV', '0,5'),
                ('Plane', '0,6'),
                ('Speedboat', '0,7'),
                ('Car', '0,8'),
                ('Bicycle', '0,9'),
                ('TRIANGLE(DF station)', '0,A'),
                ('Jeep', '0,B'),
                ('Recreational Vehicle', '0,C'),
                ('Truck ', '0,D'),
                ('Van', '0,E'),
                ('WEATHER Station (blue)', '1,/#'),
                ('House QTH (VHF)', '1,/-'),
                ('Boy Scouts', '1,/,'),
                ('Campground (Portable ops)', '1,/;'),
                ('FIRE', '1,/:'),
                ('Police, Sheriff', '1,/!'),
                ('SERVER for Files', '1,/?'),
                ('X', '1,/.'),
                ('Small AIRCRAFT (SSID-11)', "1,/'"),
                ('reserved  (was rain)', '1,/"'),
                ('Mobile Satellite Station', '1,/('),
                ('Wheelchair (handicapped)', '1,/)'),
                ('Human/Person   (SSID-7)', '1,/['),
                ('MAIL/PostOffice(was PBBS)', '1,/]'),
                ('/{ (J1)', '1,/{'),
                ('/} (J3)', '1,/}'),
                ('HC FUTURE predict (dot)', '1,/@'),
                ('SnowMobile', '1,/*'),
                ('Red Dot', '1,//'),
                ('TRIANGLE(DF station)', '1,/\\'),
                ('HF GATEway', '1,/&'),
                ('DIGI (white center)', '1,/#'),
                ('DX CLUSTER', '1,/%'),
                ('Dish Antenna', '1,/`'),
                ('LARGE AIRCRAFT', '1,/^'),
                ('Red Cross', '1,/+'),
                ('Motorcycle     (SSID-10)', '1,/<'),
                ('RAILROAD ENGINE', '1,/='),
                ('CAR            (SSID-9)', '1,/>'),
                ('TNC Stream Switch', '1,/|'),
                ('TNC Stream Switch', '1,/~'),
                ('PHONE', '1,/$'),
                ('# circle (obsolete)', '1,/0'),
                ('TBD (these were numbered)', '1,/1'),
                ('TBD (circles like pool)', '1,/2'),
                ('TBD (balls.  But with)', '1,/3'),
                ('TBD (overlays, we can)', '1,/4'),
                ("TBD (put all #'s on one)", '1,/5'),
                ('TBD (So 1-9 are available)', '1,/6'),
                ('TBD (for new uses?)', '1,/7'),
                ('TBD (They are often used)', '1,/8'),
                ('TBD (as mobiles at events)', '1,/9'),
                ('Aid Station', '1,/A'),
                ('AMBULANCE     (SSID-1)', '1,/a'),
                ('BBS or PBBS', '1,/B'),
                ('BIKE          (SSID-4)', '1,/b'),
                ('Canoe', '1,/C'),
                ('Incident Command Post', '1,/c'),
                ('/D (PD)', '1,/D'),
                ('Fire dept', '1,/d'),
                ('EYEBALL (Events, etc!)', '1,/E'),
                ('HORSE (equestrian)', '1,/e'),
                ('Farm Vehicle (tractor)', '1,/F'),
                ('FIRE TRUCK    (SSID-3)', '1,/f'),
                ('Grid Square (6 digit)', '1,/G'),
                ('Glider', '1,/g'),
                ('HOTEL (blue bed symbol)', '1,/H'),
                ('HOSPITAL', '1,/h'),
                ('TcpIp on air network stn', '1,/I'),
                ('IOTA (islands on the air)', '1,/i'),
                ('/J (PJ)', '1,/J'),
                ('JEEP          (SSID-12)', '1,/j'),
                ('School', '1,/K'),
                ('TRUCK         (SSID-14)', '1,/k'),
                ('PC user (Jan 03)', '1,/L'),
                ('Laptop (Jan 03)  (Feb 07)', '1,/l'),
                ('MacAPRS', '1,/M'),
                ('Mic-E Repeater', '1,/m'),
                ('NTS Station', '1,/N'),
                ('Node (black bulls-eye)', '1,/n'),
                ('BALLOON        (SSID-11)', '1,/O'),
                ('EOC', '1,/o'),
                ('Police', '1,/P'),
                ('ROVER (puppy, or dog)', '1,/p'),
                ('TBD', '1,/Q'),
                ('GRID SQ shown above 128 m', '1,/q'),
                ('REC. VEHICLE   (SSID-13)', '1,/R'),
                ('Repeater         (Feb 07)', '1,/r'),
                ('SHUTTLE', '1,/S'),
                ('SHIP (pwr boat)  (SSID-8)', '1,/s'),
                ('SSTV', '1,/T'),
                ('TRUCK STOP', '1,/t'),
                ('BUS            (SSID-2)', '1,/U'),
                ('TRUCK (18 wheeler)', '1,/u'),
                ('ATV', '1,/V'),
                ('VAN           (SSID-15)', '1,/v'),
                ('National WX Service Site', '1,/W'),
                ('WATER station', '1,/w'),
                ('HELO           (SSID-6)', '1,/X'),
                ('xAPRS (Unix)', '1,/x'),
                ('YACHT (sail)   (SSID-5)', '1,/Y'),
                ('YAGI @ QTH', '1,/y'),
                ('WinAPRS', '1,/Z'),
                ('TBD', '1,/z'),
                ('# WX site (green digi)', '1,\\_'),
                ('# WX site (green digi) with Zero overlaid', '1,0_'),
                ('# WX site (green digi) with One overlaid', '1,1_'),
                ('# WX site (green digi) with Two overlaid', '1,2_'),
                ('# WX site (green digi) with Three overlaid', '1,3_'),
                ('# WX site (green digi) with Four overlaid', '1,4_'),
                ('# WX site (green digi) with Five overlaid', '1,5_'),
                ('# WX site (green digi) with Six overlaid', '1,6_'),
                ('# WX site (green digi) with Seven overlaid', '1,7_'),
                ('# WX site (green digi) with Eight overlaid', '1,8_'),
                ('# WX site (green digi) with Nine overlaid', '1,9_'),
                ('# WX site (green digi) with Letter A overlaid', '1,A_'),
                ('# WX site (green digi) with Letter B overlaid', '1,B_'),
                ('# WX site (green digi) with Letter C overlaid', '1,C_'),
                ('# WX site (green digi) with Letter D overlaid', '1,D_'),
                ('# WX site (green digi) with Letter E overlaid', '1,E_'),
                ('# WX site (green digi) with Letter F overlaid', '1,F_'),
                ('# WX site (green digi) with Letter G overlaid', '1,G_'),
                ('# WX site (green digi) with Letter H overlaid', '1,H_'),
                ('# WX site (green digi) with Letter I overlaid', '1,I_'),
                ('# WX site (green digi) with Letter J overlaid', '1,J_'),
                ('# WX site (green digi) with Letter K overlaid', '1,K_'),
                ('# WX site (green digi) with Letter L overlaid', '1,L_'),
                ('# WX site (green digi) with Letter M overlaid', '1,M_'),
                ('# WX site (green digi) with Letter N overlaid', '1,N_'),
                ('# WX site (green digi) with Letter O overlaid', '1,O_'),
                ('# WX site (green digi) with Letter P overlaid', '1,P_'),
                ('# WX site (green digi) with Letter Q overlaid', '1,Q_'),
                ('# WX site (green digi) with Letter R overlaid', '1,R_'),
                ('# WX site (green digi) with Letter S overlaid', '1,S_'),
                ('# WX site (green digi) with Letter T overlaid', '1,T_'),
                ('# WX site (green digi) with Letter U overlaid', '1,U_'),
                ('# WX site (green digi) with Letter V overlaid', '1,V_'),
                ('# WX site (green digi) with Letter W overlaid', '1,W_'),
                ('# WX site (green digi) with Letter X overlaid', '1,X_'),
                ('# WX site (green digi) with Letter Y overlaid', '1,Y_'),
                ('# WX site (green digi) with Letter Z overlaid', '1,Z_'),
                ('House (H=HF) (O = Op Present)', '1,\\-'),
                ('Girl Scouts', '1,\\,'),
                ('Park/Picnic + overlay events', '1,\\;'),
                ('AVAIL (Hail ==> ` ovly H)', '1,\\:'),
                ('EMERGENCY (and overlays)', '1,\\!'),
                ('INFO Kiosk  (Blue box with ?)', '1,\\?'),
                ('Ambiguous (Big Question mark)', '1,\\.'),
                ('Crash (& now Incident sites)', "1,\\'"),
                ('reserved', '1,\\"'),
                ('CLOUDY (other clouds w ovrly)', '1,\\('),
                ('Firenet MEO, MODIS Earth Obs.', '1,\\)'),
                ('W.Cloud (& humans w Ovrly)', '1,\\['),
                ('AVAIL', '1,\\]'),
                ('AVAIL? (Fog ==> E ovly F)', '1,\\{'),
                ('AVAIL? (maybe)', '1,\\}'),
                ('HURICANE/Trop-Storm', '1,\\@'),
                ('AVAIL (SNOW moved to ` ovly S)', '1,\\*'),
                ('Waypoint Destination See APRSdos MOBILE.txt', '1,\\/'),
                ('New overlayable GPS symbol', '1,\\\\'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX', '1,\\&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Zero overlaid', '1,0&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with One overlaid', '1,1&'),
                ('TX igate with path set to 2 hops', '1,2&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Three overlaid', '1,3&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Four overlaid', '1,4&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Five overlaid', '1,5&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Six overlaid', '1,6&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Seven overlaid', '1,7&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Eight overlaid', '1,8&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Nine overlaid', '1,9&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter A overlaid',
                 '1,A&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter B overlaid',
                 '1,B&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter C overlaid',
                 '1,C&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter D overlaid',
                 '1,D&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter E overlaid',
                 '1,E&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter F overlaid',
                 '1,F&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter G overlaid',
                 '1,G&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter H overlaid',
                 '1,H&'),
                ('Igate Generic', '1,I&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter J overlaid',
                 '1,J&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter K overlaid',
                 '1,K&'),
                ('Lora Igate', '1,L&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter M overlaid',
                 '1,M&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter N overlaid',
                 '1,N&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter O overlaid',
                 '1,O&'),
                ('PSKmail node', '1,P&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter Q overlaid',
                 '1,Q&'),
                ('Receive only Igate', '1,R&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter S overlaid',
                 '1,S&'),
                ('TX igate with path set to 1 hop only', '1,T&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter U overlaid',
                 '1,U&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter V overlaid',
                 '1,V&'),
                ('WIRES-X', '1,W&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter X overlaid',
                 '1,X&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter Y overlaid',
                 '1,Y&'),
                ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter Z overlaid',
                 '1,Z&'),
                ('OVERLAY DIGI (green star)', '1,\\#'),
                ('OVERLAY DIGI (green star) with Zero overlaid', '1,0#'),
                ('OVERLAY DIGI (green star) with One overlaid', '1,1#'),
                ('OVERLAY DIGI (green star) with Two overlaid', '1,2#'),
                ('OVERLAY DIGI (green star) with Three overlaid', '1,3#'),
                ('OVERLAY DIGI (green star) with Four overlaid', '1,4#'),
                ('OVERLAY DIGI (green star) with Five overlaid', '1,5#'),
                ('OVERLAY DIGI (green star) with Six overlaid', '1,6#'),
                ('OVERLAY DIGI (green star) with Seven overlaid', '1,7#'),
                ('OVERLAY DIGI (green star) with Eight overlaid', '1,8#'),
                ('OVERLAY DIGI (green star) with Nine overlaid', '1,9#'),
                ('OVERLAY DIGI (green star) with Letter A overlaid', '1,A#'),
                ('OVERLAY DIGI (green star) with Letter B overlaid', '1,B#'),
                ('OVERLAY DIGI (green star) with Letter C overlaid', '1,C#'),
                ('OVERLAY DIGI (green star) with Letter D overlaid', '1,D#'),
                ('OVERLAY DIGI (green star) with Letter E overlaid', '1,E#'),
                ('OVERLAY DIGI (green star) with Letter F overlaid', '1,F#'),
                ('OVERLAY DIGI (green star) with Letter G overlaid', '1,G#'),
                ('OVERLAY DIGI (green star) with Letter H overlaid', '1,H#'),
                ('OVERLAY DIGI (green star) with Letter I overlaid', '1,I#'),
                ('OVERLAY DIGI (green star) with Letter J overlaid', '1,J#'),
                ('OVERLAY DIGI (green star) with Letter K overlaid', '1,K#'),
                ('OVERLAY DIGI (green star) with Letter L overlaid', '1,L#'),
                ('OVERLAY DIGI (green star) with Letter M overlaid', '1,M#'),
                ('OVERLAY DIGI (green star) with Letter N overlaid', '1,N#'),
                ('OVERLAY DIGI (green star) with Letter O overlaid', '1,O#'),
                ('OVERLAY DIGI (green star) with Letter P overlaid', '1,P#'),
                ('OVERLAY DIGI (green star) with Letter Q overlaid', '1,Q#'),
                ('OVERLAY DIGI (green star) with Letter R overlaid', '1,R#'),
                ('OVERLAY DIGI (green star) with Letter S overlaid', '1,S#'),
                ('OVERLAY DIGI (green star) with Letter T overlaid', '1,T#'),
                ('OVERLAY DIGI (green star) with Letter U overlaid', '1,U#'),
                ('OVERLAY DIGI (green star) with Letter V overlaid', '1,V#'),
                ('OVERLAY DIGI (green star) with Letter W overlaid', '1,W#'),
                ('OVERLAY DIGI (green star) with Letter X overlaid', '1,X#'),
                ('OVERLAY DIGI (green star) with Letter Y overlaid', '1,Y#'),
                ('OVERLAY DIGI (green star) with Letter Z overlaid', '1,Z#'),
                ('Power Plant with overlay', '1,\\%'),
                ('Rain (all types w ovrly)', '1,\\`'),
                ('other Aircraft ovrlys (2014)', '1,\\^'),
                ('other Aircraft ovrlys (2014) with Zero overlaid', '1,0^'),
                ('other Aircraft ovrlys (2014) with One overlaid', '1,1^'),
                ('other Aircraft ovrlys (2014) with Two overlaid', '1,2^'),
                ('other Aircraft ovrlys (2014) with Three overlaid', '1,3^'),
                ('other Aircraft ovrlys (2014) with Four overlaid', '1,4^'),
                ('other Aircraft ovrlys (2014) with Five overlaid', '1,5^'),
                ('other Aircraft ovrlys (2014) with Six overlaid', '1,6^'),
                ('other Aircraft ovrlys (2014) with Seven overlaid', '1,7^'),
                ('other Aircraft ovrlys (2014) with Eight overlaid', '1,8^'),
                ('other Aircraft ovrlys (2014) with Nine overlaid', '1,9^'),
                ('Autonomous', '1,A^'),
                ('other Aircraft ovrlys (2014) with Letter B overlaid',
                 '1,B^'),
                ('other Aircraft ovrlys (2014) with Letter C overlaid',
                 '1,C^'),
                ('Drone', '1,D^'),
                ('Electric aircraft', '1,E^'),
                ('other Aircraft ovrlys (2014) with Letter F overlaid',
                 '1,F^'),
                ('other Aircraft ovrlys (2014) with Letter G overlaid',
                 '1,G^'),
                ('Hovercraft', '1,H^'),
                ('other Aircraft ovrlys (2014) with Letter I overlaid',
                 '1,I^'),
                ('JET', '1,J^'),
                ('other Aircraft ovrlys (2014) with Letter K overlaid',
                 '1,K^'),
                ('other Aircraft ovrlys (2014) with Letter L overlaid',
                 '1,L^'),
                ('Missle', '1,M^'),
                ('other Aircraft ovrlys (2014) with Letter N overlaid',
                 '1,N^'),
                ('other Aircraft ovrlys (2014) with Letter O overlaid',
                 '1,O^'),
                ('Prop', '1,P^'),
                ('other Aircraft ovrlys (2014) with Letter Q overlaid',
                 '1,Q^'),
                ('Remotely Piloted', '1,R^'),
                ('Solar Powered', '1,S^'),
                ('other Aircraft ovrlys (2014) with Letter T overlaid',
                 '1,T^'),
                ('other Aircraft ovrlys (2014) with Letter U overlaid',
                 '1,U^'),
                ('Vertical takeoff', '1,V^'),
                ('other Aircraft ovrlys (2014) with Letter W overlaid',
                 '1,W^'),
                ('Experimental', '1,X^'),
                ('other Aircraft ovrlys (2014) with Letter Y overlaid',
                 '1,Y^'),
                ('other Aircraft ovrlys (2014) with Letter Z overlaid',
                 '1,Z^'),
                ('Church', '1,\\+'),
                ('ADVISORY (one WX flag)', '1,\\<'),
                ('avail. symbol overlay group', '1,\\='),
                ('OVERLAYED CARs & Vehicles', '1,\\>'),
                ('OVERLAYED CARs & Vehicles with Zero overlaid', '1,0>'),
                ('OVERLAYED CARs & Vehicles with One overlaid', '1,1>'),
                ('OVERLAYED CARs & Vehicles with Two overlaid', '1,2>'),
                ('Model 3 (Tesla)', '1,3>'),
                ('OVERLAYED CARs & Vehicles with Four overlaid', '1,4>'),
                ('OVERLAYED CARs & Vehicles with Five overlaid', '1,5>'),
                ('OVERLAYED CARs & Vehicles with Six overlaid', '1,6>'),
                ('OVERLAYED CARs & Vehicles with Seven overlaid', '1,7>'),
                ('OVERLAYED CARs & Vehicles with Eight overlaid', '1,8>'),
                ('OVERLAYED CARs & Vehicles with Nine overlaid', '1,9>'),
                ('OVERLAYED CARs & Vehicles with Letter A overlaid', '1,A>'),
                ('BEV - Battery EV', '1,B>'),
                ('OVERLAYED CARs & Vehicles with Letter C overlaid', '1,C>'),
                ('DIY - Do it yourself ', '1,D>'),
                ('Ethanol (was electric)', '1,E>'),
                ('Fuelcell or hydrogen', '1,F>'),
                ('OVERLAYED CARs & Vehicles with Letter G overlaid', '1,G>'),
                ('Hybrid', '1,H>'),
                ('OVERLAYED CARs & Vehicles with Letter I overlaid', '1,I>'),
                ('OVERLAYED CARs & Vehicles with Letter J overlaid', '1,J>'),
                ('OVERLAYED CARs & Vehicles with Letter K overlaid', '1,K>'),
                ('Leaf', '1,L>'),
                ('OVERLAYED CARs & Vehicles with Letter M overlaid', '1,M>'),
                ('OVERLAYED CARs & Vehicles with Letter N overlaid', '1,N>'),
                ('OVERLAYED CARs & Vehicles with Letter O overlaid', '1,O>'),
                ('PHEV - Plugin-hybrid', '1,P>'),
                ('OVERLAYED CARs & Vehicles with Letter Q overlaid', '1,Q>'),
                ('OVERLAYED CARs & Vehicles with Letter R overlaid', '1,R>'),
                ('Solar powered', '1,S>'),
                ('Tesla  (temporary)', '1,T>'),
                ('OVERLAYED CARs & Vehicles with Letter U overlaid', '1,U>'),
                ('Volt (temporary)', '1,V>'),
                ('OVERLAYED CARs & Vehicles with Letter W overlaid', '1,W>'),
                ('Model X', '1,X>'),
                ('OVERLAYED CARs & Vehicles with Letter Y overlaid', '1,Y>'),
                ('OVERLAYED CARs & Vehicles with Letter Z overlaid', '1,Z>'),
                ('TNC Stream Switch', '1,\\|'),
                ('TNC Stream Switch', '1,\\~'),
                ('Bank or ATM  (green box)', '1,\\$'),
                ('CIRCLE (IRLP/Echolink/WIRES)', '1,\\0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Zero overlaid', '1,00'),
                ('CIRCLE (IRLP/Echolink/WIRES) with One overlaid', '1,10'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Two overlaid', '1,20'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Three overlaid', '1,30'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Four overlaid', '1,40'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Five overlaid', '1,50'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Six overlaid', '1,60'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Seven overlaid', '1,70'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Eight overlaid', '1,80'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Nine overlaid', '1,90'),
                ('Allstar Node', '1,A0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter B overlaid',
                 '1,B0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter C overlaid',
                 '1,C0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter D overlaid',
                 '1,D0'),
                ('Echolink Node', '1,E0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter F overlaid',
                 '1,F0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter G overlaid',
                 '1,G0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter H overlaid',
                 '1,H0'),
                ('IRLP repeater', '1,I0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter J overlaid',
                 '1,J0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter K overlaid',
                 '1,K0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter L overlaid',
                 '1,L0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter M overlaid',
                 '1,M0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter N overlaid',
                 '1,N0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter O overlaid',
                 '1,O0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter P overlaid',
                 '1,P0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter Q overlaid',
                 '1,Q0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter R overlaid',
                 '1,R0'),
                ('Staging Area', '1,S0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter T overlaid',
                 '1,T0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter U overlaid',
                 '1,U0'),
                ('Echolink and IRLP', '1,V0'),
                ('WIRES (Yaesu VOIP)', '1,W0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter X overlaid',
                 '1,X0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter Y overlaid',
                 '1,Y0'),
                ('CIRCLE (IRLP/Echolink/WIRES) with Letter Z overlaid',
                 '1,Z0'),
                ('AVAIL', '1,\\1'),
                ('AVAIL', '1,\\2'),
                ('AVAIL', '1,\\3'),
                ('AVAIL', '1,\\4'),
                ('AVAIL', '1,\\5'),
                ('AVAIL', '1,\\6'),
                ('AVAIL', '1,\\7'),
                ('802.11 or other network node', '1,\\8'),
                ('Gas Station (blue pump)', '1,\\9'),
                ('overlayBOX DTMF & RFID & XO', '1,\\A'),
                ('overlayBOX DTMF & RFID & XO with Zero overlaid', '1,0A'),
                ('overlayBOX DTMF & RFID & XO with One overlaid', '1,1A'),
                ('overlayBOX DTMF & RFID & XO with Two overlaid', '1,2A'),
                ('overlayBOX DTMF & RFID & XO with Three overlaid', '1,3A'),
                ('overlayBOX DTMF & RFID & XO with Four overlaid', '1,4A'),
                ('overlayBOX DTMF & RFID & XO with Five overlaid', '1,5A'),
                ('overlayBOX DTMF & RFID & XO with Six overlaid', '1,6A'),
                ('HT DTMF user', '1,7A'),
                ('overlayBOX DTMF & RFID & XO with Eight overlaid', '1,8A'),
                ('Mobile DTMF user', '1,9A'),
                ('AllStar DTMF report', '1,AA'),
                ('overlayBOX DTMF & RFID & XO with Letter B overlaid', '1,BA'),
                ('overlayBOX DTMF & RFID & XO with Letter C overlaid', '1,CA'),
                ('D-Star report', '1,DA'),
                ('Echolink DTMF report', '1,EA'),
                ('overlayBOX DTMF & RFID & XO with Letter F overlaid', '1,FA'),
                ('overlayBOX DTMF & RFID & XO with Letter G overlaid', '1,GA'),
                ('House DTMF user', '1,HA'),
                ('IRLP DTMF report', '1,IA'),
                ('overlayBOX DTMF & RFID & XO with Letter J overlaid', '1,JA'),
                ('overlayBOX DTMF & RFID & XO with Letter K overlaid', '1,KA'),
                ('overlayBOX DTMF & RFID & XO with Letter L overlaid', '1,LA'),
                ('overlayBOX DTMF & RFID & XO with Letter M overlaid', '1,MA'),
                ('overlayBOX DTMF & RFID & XO with Letter N overlaid', '1,NA'),
                ('overlayBOX DTMF & RFID & XO with Letter O overlaid', '1,OA'),
                ('overlayBOX DTMF & RFID & XO with Letter P overlaid', '1,PA'),
                ('overlayBOX DTMF & RFID & XO with Letter Q overlaid', '1,QA'),
                ('RFID report', '1,RA'),
                ('overlayBOX DTMF & RFID & XO with Letter S overlaid', '1,SA'),
                ('overlayBOX DTMF & RFID & XO with Letter T overlaid', '1,TA'),
                ('overlayBOX DTMF & RFID & XO with Letter U overlaid', '1,UA'),
                ('overlayBOX DTMF & RFID & XO with Letter V overlaid', '1,VA'),
                ('overlayBOX DTMF & RFID & XO with Letter W overlaid', '1,WA'),
                ('OLPC Laptop XO', '1,XA'),
                ('overlayBOX DTMF & RFID & XO with Letter Y overlaid', '1,YA'),
                ('overlayBOX DTMF & RFID & XO with Letter Z overlaid', '1,ZA'),
                (' ARRL,ARES,WinLINK,Dstar, etc', '1,\\a'),
                ('AVAIL (BlwngSnow ==> E ovly B', '1,\\B'),
                ('AVAIL(Blwng Dst/Snd => E ovly)', '1,\\b'),
                ('Coast Guard', '1,\\C'),
                (' CD triangle RACES/SATERN/etc', '1,\\c'),
                ('DX spot by callsign', '1,\\d'),
                ("DEPOTS (Drizzle ==> ' ovly D)", '1,\\D A'),
                ('Smoke (& other vis codes)', '1,\\E'),
                ('Sleet (& future ovrly codes)', '1,\\e'),
                ('AVAIL (FrzngRain ==> `F)', '1,\\F'),
                ('Funnel Cloud', '1,\\f'),
                ('AVAIL (Snow Shwr ==> I ovly S)', '1,\\G'),
                ('Gale Flags', '1,\\g'),
                ('\\Haze (& Overlay Hazards)', '1,\\H'),
                ('Store. or HAMFST Hh=HAM store', '1,\\h'),
                ('Rain Shower', '1,\\I'),
                ('BOX or points of Interest', '1,\\i'),
                ('AVAIL (Lightening ==> I ovly L)', '1,\\J'),
                ('WorkZone (Steam Shovel)', '1,\\j'),
                ('Kenwood HT (W)', '1,\\K'),
                ('Special Vehicle SUV,ATV,4x4', '1,\\k'),
                ('Lighthouse', '1,\\L'),
                ('Areas      (box,circles,etc)', '1,\\l'),
                ('MARS (A=Army,N=Navy,F=AF)', '1,\\M'),
                ('Value Sign (3 digit display)', '1,\\m'),
                ('Navigation Buoy', '1,\\N'),
                ('OVERLAY TRIANGLE', '1,\\n'),
                ('OVERLAY TRIANGLE with Zero overlaid', '1,0n'),
                ('OVERLAY TRIANGLE with One overlaid', '1,1n'),
                ('OVERLAY TRIANGLE with Two overlaid', '1,2n'),
                ('OVERLAY TRIANGLE with Three overlaid', '1,3n'),
                ('OVERLAY TRIANGLE with Four overlaid', '1,4n'),
                ('OVERLAY TRIANGLE with Five overlaid', '1,5n'),
                ('OVERLAY TRIANGLE with Six overlaid', '1,6n'),
                ('OVERLAY TRIANGLE with Seven overlaid', '1,7n'),
                ('OVERLAY TRIANGLE with Eight overlaid', '1,8n'),
                ('OVERLAY TRIANGLE with Nine overlaid', '1,9n'),
                ('OVERLAY TRIANGLE with Letter A overlaid', '1,An'),
                ('OVERLAY TRIANGLE with Letter B overlaid', '1,Bn'),
                ('OVERLAY TRIANGLE with Letter C overlaid', '1,Cn'),
                ('OVERLAY TRIANGLE with Letter D overlaid', '1,Dn'),
                ('OVERLAY TRIANGLE with Letter E overlaid', '1,En'),
                ('OVERLAY TRIANGLE with Letter F overlaid', '1,Fn'),
                ('OVERLAY TRIANGLE with Letter G overlaid', '1,Gn'),
                ('OVERLAY TRIANGLE with Letter H overlaid', '1,Hn'),
                ('OVERLAY TRIANGLE with Letter I overlaid', '1,In'),
                ('OVERLAY TRIANGLE with Letter J overlaid', '1,Jn'),
                ('OVERLAY TRIANGLE with Letter K overlaid', '1,Kn'),
                ('OVERLAY TRIANGLE with Letter L overlaid', '1,Ln'),
                ('OVERLAY TRIANGLE with Letter M overlaid', '1,Mn'),
                ('OVERLAY TRIANGLE with Letter N overlaid', '1,Nn'),
                ('OVERLAY TRIANGLE with Letter O overlaid', '1,On'),
                ('OVERLAY TRIANGLE with Letter P overlaid', '1,Pn'),
                ('OVERLAY TRIANGLE with Letter Q overlaid', '1,Qn'),
                ('OVERLAY TRIANGLE with Letter R overlaid', '1,Rn'),
                ('OVERLAY TRIANGLE with Letter S overlaid', '1,Sn'),
                ('OVERLAY TRIANGLE with Letter T overlaid', '1,Tn'),
                ('OVERLAY TRIANGLE with Letter U overlaid', '1,Un'),
                ('OVERLAY TRIANGLE with Letter V overlaid', '1,Vn'),
                ('OVERLAY TRIANGLE with Letter W overlaid', '1,Wn'),
                ('OVERLAY TRIANGLE with Letter X overlaid', '1,Xn'),
                ('OVERLAY TRIANGLE with Letter Y overlaid', '1,Yn'),
                ('OVERLAY TRIANGLE with Letter Z overlaid', '1,Zn'),
                ('Overlay Balloon (Rocket = \\O)', '1,\\O'),
                ('small circle', '1,\\o'),
                ('Parking', '1,\\P'),
                ('AVAIL (PrtlyCldy => ( ovly P', '1,\\p'),
                ('QUAKE', '1,\\Q'),
                ('AVAIL', '1,\\q'),
                ('Restaurant', '1,\\R'),
                ('Restrooms', '1,\\r'),
                ('Satellite/Pacsat', '1,\\S'),
                ('OVERLAY SHIP/boats', '1,\\s'),
                ('OVERLAY SHIP/boats with Zero overlaid', '1,0s'),
                ('OVERLAY SHIP/boats with One overlaid', '1,1s'),
                ('OVERLAY SHIP/boats with Two overlaid', '1,2s'),
                ('OVERLAY SHIP/boats with Three overlaid', '1,3s'),
                ('OVERLAY SHIP/boats with Four overlaid', '1,4s'),
                ('OVERLAY SHIP/boats with Five overlaid', '1,5s'),
                ('Shipwreck ("deep6")', '1,6s'),
                ('OVERLAY SHIP/boats with Seven overlaid', '1,7s'),
                ('OVERLAY SHIP/boats with Eight overlaid', '1,8s'),
                ('OVERLAY SHIP/boats with Nine overlaid', '1,9s'),
                ('OVERLAY SHIP/boats with Letter A overlaid', '1,As'),
                ('Pleasure Boat', '1,Bs'),
                ('Cargo', '1,Cs'),
                ('Diving', '1,Ds'),
                ('Emergency or Medical transport', '1,Es'),
                ('Fishing', '1,Fs'),
                ('OVERLAY SHIP/boats with Letter G overlaid', '1,Gs'),
                ('High-speed Craft', '1,Hs'),
                ('OVERLAY SHIP/boats with Letter I overlaid', '1,Is'),
                ('Jet Ski', '1,Js'),
                ('OVERLAY SHIP/boats with Letter K overlaid', '1,Ks'),
                ('Law enforcement', '1,Ls'),
                ('Miltary', '1,Ms'),
                ('OVERLAY SHIP/boats with Letter N overlaid', '1,Ns'),
                ('Oil Rig', '1,Os'),
                ('Pilot Boat', '1,Ps'),
                ('Torpedo', '1,Qs'),
                ('OVERLAY SHIP/boats with Letter R overlaid', '1,Rs'),
                ('Search and Rescue', '1,Ss'),
                ('Tug', '1,Ts'),
                ('Underwater ops or submarine', '1,Us'),
                ('OVERLAY SHIP/boats with Letter V overlaid', '1,Vs'),
                ('Wing-in-Ground effect (or Hovercraft)', '1,Ws'),
                ('Passenger (paX)(ferry)', '1,Xs'),
                ('Sailing (large ship)', '1,Ys'),
                ('OVERLAY SHIP/boats with Letter Z overlaid', '1,Zs'),
                ('Thunderstorm', '1,\\T'),
                ('Tornado', '1,\\t'),
                ('SUNNY', '1,\\U'),
                ('OVERLAYED TRUCK', '1,\\u'),
                ('OVERLAYED TRUCK with Zero overlaid', '1,0u'),
                ('OVERLAYED TRUCK with One overlaid', '1,1u'),
                ('OVERLAYED TRUCK with Two overlaid', '1,2u'),
                ('OVERLAYED TRUCK with Three overlaid', '1,3u'),
                ('OVERLAYED TRUCK with Four overlaid', '1,4u'),
                ('OVERLAYED TRUCK with Five overlaid', '1,5u'),
                ('OVERLAYED TRUCK with Six overlaid', '1,6u'),
                ('OVERLAYED TRUCK with Seven overlaid', '1,7u'),
                ('OVERLAYED TRUCK with Eight overlaid', '1,8u'),
                ('OVERLAYED TRUCK with Nine overlaid', '1,9u'),
                ('OVERLAYED TRUCK with Letter A overlaid', '1,Au'),
                ('Buldozer/construction/Backhoe', '1,Bu'),
                ('Chlorine Tanker', '1,Cu'),
                ('OVERLAYED TRUCK with Letter D overlaid', '1,Du'),
                ('OVERLAYED TRUCK with Letter E overlaid', '1,Eu'),
                ('OVERLAYED TRUCK with Letter F overlaid', '1,Fu'),
                ('Gas', '1,Gu'),
                ('Hazardous', '1,Hu'),
                ('OVERLAYED TRUCK with Letter I overlaid', '1,Iu'),
                ('OVERLAYED TRUCK with Letter J overlaid', '1,Ju'),
                ('OVERLAYED TRUCK with Letter K overlaid', '1,Ku'),
                ('OVERLAYED TRUCK with Letter L overlaid', '1,Lu'),
                ('OVERLAYED TRUCK with Letter M overlaid', '1,Mu'),
                ('OVERLAYED TRUCK with Letter N overlaid', '1,Nu'),
                ('OVERLAYED TRUCK with Letter O overlaid', '1,Ou'),
                ('Plow or SnowPlow', '1,Pu'),
                ('OVERLAYED TRUCK with Letter Q overlaid', '1,Qu'),
                ('OVERLAYED TRUCK with Letter R overlaid', '1,Ru'),
                ('OVERLAYED TRUCK with Letter S overlaid', '1,Su'),
                ('Tanker', '1,Tu'),
                ('OVERLAYED TRUCK with Letter U overlaid', '1,Uu'),
                ('OVERLAYED TRUCK with Letter V overlaid', '1,Vu'),
                ('OVERLAYED TRUCK with Letter W overlaid', '1,Wu'),
                ('OVERLAYED TRUCK with Letter X overlaid', '1,Xu'),
                ('OVERLAYED TRUCK with Letter Y overlaid', '1,Yu'),
                ('OVERLAYED TRUCK with Letter Z overlaid', '1,Zu'),
                ('VORTAC Nav Aid', '1,\\V'),
                ('OVERLAYED Van', '1,\\v'),
                ('OVERLAYED Van with Zero overlaid', '1,0v'),
                ('OVERLAYED Van with One overlaid', '1,1v'),
                ('OVERLAYED Van with Two overlaid', '1,2v'),
                ('OVERLAYED Van with Three overlaid', '1,3v'),
                ('OVERLAYED Van with Four overlaid', '1,4v'),
                ('OVERLAYED Van with Five overlaid', '1,5v'),
                ('OVERLAYED Van with Six overlaid', '1,6v'),
                ('OVERLAYED Van with Seven overlaid', '1,7v'),
                ('OVERLAYED Van with Eight overlaid', '1,8v'),
                ('OVERLAYED Van with Nine overlaid', '1,9v'),
                ('OVERLAYED Van with Letter A overlaid', '1,Av'),
                ('OVERLAYED Van with Letter B overlaid', '1,Bv'),
                ('OVERLAYED Van with Letter C overlaid', '1,Cv'),
                ('OVERLAYED Van with Letter D overlaid', '1,Dv'),
                ('OVERLAYED Van with Letter E overlaid', '1,Ev'),
                ('OVERLAYED Van with Letter F overlaid', '1,Fv'),
                ('OVERLAYED Van with Letter G overlaid', '1,Gv'),
                ('OVERLAYED Van with Letter H overlaid', '1,Hv'),
                ('OVERLAYED Van with Letter I overlaid', '1,Iv'),
                ('OVERLAYED Van with Letter J overlaid', '1,Jv'),
                ('OVERLAYED Van with Letter K overlaid', '1,Kv'),
                ('OVERLAYED Van with Letter L overlaid', '1,Lv'),
                ('OVERLAYED Van with Letter M overlaid', '1,Mv'),
                ('OVERLAYED Van with Letter N overlaid', '1,Nv'),
                ('OVERLAYED Van with Letter O overlaid', '1,Ov'),
                ('OVERLAYED Van with Letter P overlaid', '1,Pv'),
                ('OVERLAYED Van with Letter Q overlaid', '1,Qv'),
                ('OVERLAYED Van with Letter R overlaid', '1,Rv'),
                ('OVERLAYED Van with Letter S overlaid', '1,Sv'),
                ('OVERLAYED Van with Letter T overlaid', '1,Tv'),
                ('OVERLAYED Van with Letter U overlaid', '1,Uv'),
                ('OVERLAYED Van with Letter V overlaid', '1,Vv'),
                ('OVERLAYED Van with Letter W overlaid', '1,Wv'),
                ('OVERLAYED Van with Letter X overlaid', '1,Xv'),
                ('OVERLAYED Van with Letter Y overlaid', '1,Yv'),
                ('OVERLAYED Van with Letter Z overlaid', '1,Zv'),
                ('# NWS site (NWS options)', '1,\\W'),
                ('# NWS site (NWS options) with Zero overlaid', '1,0W'),
                ('# NWS site (NWS options) with One overlaid', '1,1W'),
                ('# NWS site (NWS options) with Two overlaid', '1,2W'),
                ('# NWS site (NWS options) with Three overlaid', '1,3W'),
                ('# NWS site (NWS options) with Four overlaid', '1,4W'),
                ('# NWS site (NWS options) with Five overlaid', '1,5W'),
                ('# NWS site (NWS options) with Six overlaid', '1,6W'),
                ('# NWS site (NWS options) with Seven overlaid', '1,7W'),
                ('# NWS site (NWS options) with Eight overlaid', '1,8W'),
                ('# NWS site (NWS options) with Nine overlaid', '1,9W'),
                ('# NWS site (NWS options) with Letter A overlaid', '1,AW'),
                ('# NWS site (NWS options) with Letter B overlaid', '1,BW'),
                ('# NWS site (NWS options) with Letter C overlaid', '1,CW'),
                ('# NWS site (NWS options) with Letter D overlaid', '1,DW'),
                ('# NWS site (NWS options) with Letter E overlaid', '1,EW'),
                ('# NWS site (NWS options) with Letter F overlaid', '1,FW'),
                ('# NWS site (NWS options) with Letter G overlaid', '1,GW'),
                ('# NWS site (NWS options) with Letter H overlaid', '1,HW'),
                ('# NWS site (NWS options) with Letter I overlaid', '1,IW'),
                ('# NWS site (NWS options) with Letter J overlaid', '1,JW'),
                ('# NWS site (NWS options) with Letter K overlaid', '1,KW'),
                ('# NWS site (NWS options) with Letter L overlaid', '1,LW'),
                ('# NWS site (NWS options) with Letter M overlaid', '1,MW'),
                ('# NWS site (NWS options) with Letter N overlaid', '1,NW'),
                ('# NWS site (NWS options) with Letter O overlaid', '1,OW'),
                ('# NWS site (NWS options) with Letter P overlaid', '1,PW'),
                ('# NWS site (NWS options) with Letter Q overlaid', '1,QW'),
                ('# NWS site (NWS options) with Letter R overlaid', '1,RW'),
                ('# NWS site (NWS options) with Letter S overlaid', '1,SW'),
                ('# NWS site (NWS options) with Letter T overlaid', '1,TW'),
                ('# NWS site (NWS options) with Letter U overlaid', '1,UW'),
                ('# NWS site (NWS options) with Letter V overlaid', '1,VW'),
                ('# NWS site (NWS options) with Letter W overlaid', '1,WW'),
                ('# NWS site (NWS options) with Letter X overlaid', '1,XW'),
                ('# NWS site (NWS options) with Letter Y overlaid', '1,YW'),
                ('# NWS site (NWS options) with Letter Z overlaid', '1,ZW'),
                ('Flooding (Avalanches/Slides)', '1,\\w'),
                ('Pharmacy Rx (Apothicary)', '1,\\X'),
                ('Wreck or Obstruction ->X<-', '1,\\x'),
                ('Radios and devices', '1,\\Y'),
                ('Skywarn', '1,\\y'),
                ('AVAIL', '1,\\Z'),
                ('OVERLAYED Shelter', '1,\\z')]
    _TXD_MAP = [("100ms", "1"), ("200ms", "2"), ("300ms", "3"),
                ("400ms", "4"), ("500ms", "5"), ("750ms", "6"),
                ("1000ms", "7")]

    _BEPT_OPTIONS = ["Off", "Mine", "All New", "All"]  # Added "All"
    _CKEY_OPTIONS = ["Call", "1750Hz"]
    _DS_OPTIONS = ["Data Band", "Both Bands", "Ignore DCD"]
    _DSPA_OPTIONS = ["Entire Display", "One Line"]
    _DTB_OPTIONS = ["A", "B", "A:TX/B:RX", "A:RX/B:TX"]
    _DTBA_OPTIONS = ["A", "B", "A:TX/B:RX", "A:RX/B:TX"]
    _GU_OPTIONS = ["Not Used", "NMEA", "NMEA96"]
    _KILO_OPTIONS = ["Miles", "Kilometers"]
    _PAMB_OPTIONS = ["Off", "1 Digit", "2 Digits", "3 Digits", "4 Digits"]
    _STXR_OPTIONS = ["Off", "1/1", "1/2", "1/3", "1/4", "1/5", "1/6",
                     "1/7", "1/8"]
    _POSC_OPTIONS = ["Off Duty", "Enroute", "In Service", "Returning",
                     "Committed", "Special", "Priority", "CUSTOM 0",
                     "CUSTOM 1", "CUSTOM 2", "CUSTOM 4", "CUSTOM 5",
                     "CUSTOM 6", "Emergency"]
    _TEMP_OPTIONS = ["°F", "°C"]
    _TZ_OPTIONS = ["UTC - 12:00", "UTC - 11:30", "UTC - 11:00",
                   "UTC - 10:30", "UTC - 10:00", "UTC - 9:30",
                   "UTC - 9:00", "UTC - 8:30", "UTC - 8:00",
                   "UTC - 7:30", "UTC - 7:00", "UTC - 6:30",
                   "UTC - 6:00", "UTC - 5:30", "UTC - 5:00",
                   "UTC - 4:30", "UTC - 4:00", "UTC - 3:30",
                   "UTC - 3:00", "UTC - 2:30", "UTC - 2:00",
                   "UTC - 1:30", "UTC - 1:00", "UTC - 0:30",
                   "UTC", "UTC + 0:30", "UTC + 1:00", "UTC + 1:30",
                   "UTC + 2:00", "UTC + 2:30", "UTC + 3:00",
                   "UTC + 3:30", "UTC + 4:00", "UTC + 4:30",
                   "UTC + 5:00", "UTC + 5:30", "UTC + 6:00",
                   "UTC + 6:30", "UTC + 7:00", "UTC + 7:30",
                   "UTC + 8:00", "UTC + 8:30", "UTC + 9:00",
                   "UTC + 9:30", "UTC + 10:00", "UTC + 10:30",
                   "UTC + 11:00", "UTC + 11:30", "UTC + 12:00"]

    EXTRA_BOOL_SETTINGS = {
        'aux': [("ELK", "Enable Tune When Locked"),
                ("TH", "Tx Hold for 1750"),
                ("TXS", "Transmit Inhibit")],
        'dtmf': [("TXH", "TX Hold")],
        'main': [("LMP", "Lamp")],
    }
    EXTRA_LIST_SETTINGS = {
        'aprs': [("DSPA", "Display Area"),
                 ("KILO", "Mile/Kilometer"),
                 ("PAMB", "Position Ambiguity"),
                 ("STXR", "Status Transmit Rate"),
                 ("TEMP", "APRS Units"),
                 ("TZ", "Timezone")],
        'aux': [("CKEY", "CALL Key Set Up")],
        'main': [("BAL", "Balance"),
                 #("MNF", "Memory Display Mode")],  Only available in MR mode, not VFO mode
                ],
        'save': [("SV", "Battery Save")],
    }

    MAIDENHEAD_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWX" + \
                         "abcdefghijklmnopqrstuvwx"
    EXTRA_STRING_SETTINGS = {
        'aprs': [("ARLM", "Auto Reply Message", 45),
                 ("AMGG", "Message Groups", 45, "ABCDEFGHIJKLMNOPQRSTUVWXYZ" +
                                                "*,-0123456789"),
                 ("MP 1", "My Position 1", 10, MAIDENHEAD_CHARSET),
                 ("MP 2", "My Position 2", 10, MAIDENHEAD_CHARSET),
                 ("MP 3", "My Position 3", 10, MAIDENHEAD_CHARSET)],
    }

    EXTRA_MAP_SETTINGS = {
        'main': [("BEL 0", "Tone Alert Band A"),
                 ("BEL 1", "Tone Alert Band B"),
                 ("SQ 0", "Band A Squelch"),
                 ("SQ 1", "Band B Squelch")],
        'aprs': [("TXD", "Transmit Delay")],
    }

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
    EXTRA_LIST_SETTINGS = {
        'aprs': [("TEMP", "APRS Units")],
    }
    _PROGRAMMABLE_VFOS = None

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
    HARDWARE_FLOW = False

    _charset = chirp_common.CHARSET_ASCII
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
        rf.valid_characters = self._charset
        rf.valid_name_length = 8
        rf.memory_bounds = (0, self._upper)
        rf.has_settings = True
        return rf

    def _cmd_set_memory(self, number, spec, cmd="MW"):
        if spec:
            spec = "," + spec
        return cmd, "0,%03i%s" % (number, spec)

    def _cmd_get_memory(self, number, cmd="MR"):
        return cmd, "0,%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MNA", "%03i" % number

    def _cmd_set_memory_name(self, number, name):
        return "MNA", "%03i,%s" % (number, name)

    def _cmd_get_split(self, number, cmd="MR"):
        return cmd, "1,%03i" % number

    def _cmd_set_split(self, number, spec, cmd="MW"):
        return cmd, "1,%03i,%s" % (number, spec)

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
    _charset = chirp_common.CHARSET_1252


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

    def _cmd_get_memory(self, number, cmd="ME"):
        return cmd, "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec, cmd="ME"):
        return cmd, "%03i,%s" % (number, spec)

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
class THD74Radio(TMD710Radio):
    """Kenwood TH_D74"""
    MODEL = "TH-D74 (live mode)"
    HARDWARE_FLOW = sys.platform == "darwin"

    STEPS = [5.0, 6.25, 8.33, 9.0, 10.0, 12.5, 15.0, 20.0,
             25.0, 30.0, 50.0, 100.0]
    MODES = ['FM', 'DV', 'AM', 'LSB', 'USB', 'CW', 'NFM', 'DR',
             'WFM', 'R-CW']
    CROSS_MODES = ['DTCS->', 'Tone->DTCS', 'DTCS->Tone', 'Tone->Tone']
    DUPLEX = ['', '+', '-', 'split']
    _has_name = False

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This driver is incomplete as the D74 lacks "
                           "the full serial command set of older radios. "
                           "As such, this should be considered permanently "
                           "experimental.")
        return rp

    def _cmd_get_memory_name(self, number):
        return ''

    def get_features(self):
        rf = super(THD74Radio, self).get_features()
        rf.valid_tuning_steps = self.STEPS
        rf.valid_modes = self.MODES
        rf.valid_cross_modes = self.CROSS_MODES
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.has_name = False  # Radio has it, but no command to retrieve
        rf.has_cross = True
        return rf

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()
        mem.number = int(spec[0])
        mem.freq = int(spec[1])
        mem.offset = int(spec[2])
        mem.tuning_step = self.STEPS[int(spec[3])]
        mem.mode = self.MODES[int(spec[5])]
        if int(spec[11]):
            mem.tmode = "Cross"
            mem.cross_mode = self.CROSS_MODES[int(spec[18])]
        elif int(spec[8]):
            mem.tmode = "Tone"
        elif int(spec[9]):
            mem.tmode = "TSQL"
        elif int(spec[10]):
            mem.tmode = "DTCS"

        mem.duplex = self.DUPLEX[int(spec[14])]
        mem.rtone = chirp_common.TONES[int(spec[15])]
        mem.ctone = chirp_common.TONES[int(spec[16])]
        mem.dtcs = chirp_common.DTCS_CODES[int(spec[17])]
        mem.skip = int(spec[22]) and 'S' or ''

        return mem

    def _make_mem_spec(self, mem):
        spec = (
            "%010i" % mem.freq,
            "%010i" % mem.offset,
            "%X" % self.STEPS.index(mem.tuning_step),
            "%X" % self.STEPS.index(mem.tuning_step),
            "%i" % self.MODES.index(mem.mode),
            "0",  # Fine mode
            "0",  # Fine step
            "%i" % (mem.tmode == "Tone" and 1 or 0),
            "%i" % (mem.tmode == "TSQL" and 1 or 0),
            "%i" % (mem.tmode == "DTCS" and 1 or 0),
            "%i" % (mem.tmode == 'Cross'),
            "0",  # Reverse
            "0",  # Odd split channel
            "%i" % self.DUPLEX.index(mem.duplex),
            "%02i" % (chirp_common.TONES.index(mem.rtone)),
            "%02i" % (chirp_common.TONES.index(mem.ctone)),
            "%03i" % (chirp_common.DTCS_CODES.index(mem.dtcs)),
            "%i" % self.CROSS_MODES.index(mem.cross_mode),
            "CQCQCQ",  # URCALL
            "0",   # D-STAR squelch type
            "00",  # D-STAR squelch code
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

    def _cmd_get_memory(self, number, cmd="ME"):
        return cmd, "%02i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%02i" % number

    def _cmd_set_memory(self, number, spec, cmd="ME"):
        return cmd, "%02i,%s" % (number, spec)

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

    def _cmd_get_memory(self, number, cmd="ME"):
        return cmd, "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec, cmd="ME"):
        return cmd, "%03i,%s" % (number, spec)

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

    def _cmd_get_memory(self, number, cmd="ME"):
        return cmd, "%03i" % number

    def _cmd_get_memory_name(self, number):
        return "MN", "%03i" % number

    def _cmd_set_memory(self, number, spec, cmd="ME"):
        return cmd, "%03i,%s" % (number, spec)

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
        # Add 1 to string idecis if referring to CAT manual
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
