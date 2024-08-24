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

import logging
import math
import os
import threading

from chirp import chirp_common, directory, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueBoolean, \
    RadioSettingValueString, RadioSettingValueList, RadioSettingValueMap, \
    RadioSettings, RadioSettingValueFloat

LOG = logging.getLogger(__name__)


class KenwoodD7Position(RadioSettingGroup):
    def __init__(self, name, shortname, radio, *args, **kwargs):
        super().__init__(name, shortname, *args, **kwargs)
        self._radio = radio
        if ' ' in name:
            index = name.split(" ", 1)[1]
        else:
            index = ''
        rs = RadioSetting("latd%s" % index, "Latitude degrees",
                          RadioSettingValueInteger(0, 90, 0))
        self.append(rs)
        rs = RadioSetting("latm%s" % index, "Latitude minutes",
                          RadioSettingValueFloat(0, 59.99, 0,
                                                 resolution=0.01,
                                                 precision=2))
        self.append(rs)
        rs = RadioSetting("south%s" % index, "South",
                          RadioSettingValueBoolean(False))
        self.append(rs)
        rs = RadioSetting("longd%s" % index, "Longitude degrees",
                          RadioSettingValueInteger(0, 180, 0))
        self.append(rs)
        rs = RadioSetting("longm%s" % index, "Longitude minutes",
                          RadioSettingValueFloat(0, 59.99, 0,
                                                 resolution=0.01, precision=2))
        self.append(rs)
        rs = RadioSetting("west%s" % index, "West",
                          RadioSettingValueBoolean(False))
        self.append(rs)

    def kenwood_d7_read_value(self):
        index = self._get_index()
        name = self.get_name()
        rawval = self._radio._kenwood_get(name)[1]
        curr_value = int(rawval[0:2])
        self["latd%s" % index].value.set_value(curr_value)
        curr_value = int(rawval[2:6]) / 100
        self["latm%s" % index].value.set_value(curr_value)
        curr_value = int(rawval[6:8])
        self["south%s" % index].value.set_value(curr_value)
        curr_value = int(rawval[8:11])
        self["longd%s" % index].value.set_value(curr_value)
        curr_value = int(rawval[11:15]) / 100
        self["longm%s" % index].value.set_value(curr_value)
        curr_value = int(rawval[15:17])
        self["west%s" % index].value.set_value(curr_value)
        self['latd%s' % index].value._has_changed = False
        self['latm%s' % index].value._has_changed = False
        self['south%s' % index].value._has_changed = False
        self['longd%s' % index].value._has_changed = False
        self['longm%s' % index].value._has_changed = False
        self['west%s' % index].value._has_changed = False

    def _get_index(self):
        name = self.get_name()
        if ' ' in name:
            return name.split(" ", 1)[1]
        return ''

    def changed(self):
        index = self._get_index()
        if self['latd%s' % index].changed():
            return True
        if self['latm%s' % index].changed():
            return True
        if self['south%s' % index].changed():
            return True
        if self['longd%s' % index].changed():
            return True
        if self['longm%s' % index].changed():
            return True
        if self['west%s' % index].changed():
            return True
        return False

    def kenwood_d7_set_value(self):
        index = self._get_index()
        latd = self['latd%s' % index].value.get_value()
        latm = self['latm%s' % index].value.get_value()
        latmd = int(round(math.modf(latm)[0] * 100))
        latm = int(round(latm))
        south = int(self['south%s' % index].value.get_value())
        longd = self['longd%s' % index].value.get_value()
        longm = self['longm%s' % index].value.get_value()
        longmd = int(round(math.modf(longm)[0] * 100))
        longm = int(round(longm))
        west = int(self['west%s' % index].value.get_value())
        args = '%s%02d%02d%02d%02d%03d%02d%02d%02d' % (index,
                                                       latd, latm, latmd,
                                                       south,
                                                       longd, longm, longmd,
                                                       west)
        if index != '':
            index = ' ' + index
        self._radio._kenwood_set('MP%s' % index, args)
        # TODO: Hacking up _has_changed is bad... but we don't want
        #       to re-send all the set commands each time either.
        self['latd%s' % index].value._has_changed = False
        self['latm%s' % index].value._has_changed = False
        self['south%s' % index].value._has_changed = False
        self['longd%s' % index].value._has_changed = False
        self['longm%s' % index].value._has_changed = False
        self['west%s' % index].value._has_changed = False


class KenwoodD7DTMFMemory(RadioSettingGroup):
    DTMF_CHARSET = "ABCD#*0123456789 "

    def __init__(self, name, shortname, radio, *args, **kwargs):
        super().__init__(name, shortname, *args, **kwargs)
        self._radio = radio
        self._name = name
        index = self._get_index()
        rs = RadioSetting("DMN %s" % index, "Memory Name",
                          RadioSettingValueString(0, 8, '', False))
        self.append(rs)
        rs = RadioSetting("DM %s" % index, "Memory Value",
                          RadioSettingValueString(0, 16, '', False,
                                                  self.DTMF_CHARSET))
        self.append(rs)

    def _get_index(self):
        return "%02d" % int(self._name.split(" ", 1)[1])

    def kenwood_d7_read_value(self):
        index = self._get_index()
        value = self._radio._kenwood_get("DM %s" % index)[1]
        value = value.replace("E", "*").replace("F", "#")
        vname = self._radio._kenwood_get("DMN %s" % index)[1]
        self["DMN %s" % index].value.set_value(vname)
        self["DMN %s" % index].value._has_changed = False
        self["DM %s" % index].value.set_value(value)
        self["DM %s" % index].value._has_changed = False

    def changed(self):
        for element in self:
            if element.changed():
                return True
        return False

    def kenwood_d7_set_value(self):
        for element in self:
            if not element.changed():
                continue
            newval = element.value.get_value()
            newval = newval.replace("*", "E").replace("#", "F")
            self._radio._kenwood_set(element.get_name(),
                                     newval)
            element.value._has_changed = False


class KenwoodD7ProgrammableVFOs(RadioSettingGroup):
    def __init__(self, name, shortname, radio, *args, **kwargs):
        self._radio = radio
        super().__init__(name, shortname, *args, **kwargs)
        for optname, index, minimum, maximum in self._radio._PROGRAMMABLE_VFOS:
            group = RadioSettingGroup("PV %d" % index, optname)
            self.append(group)
            rs = RadioSetting("PV %dL" % index, "Lower Limit",
                              RadioSettingValueInteger(minimum, maximum,
                                                       minimum))
            group.append(rs)
            rs = RadioSetting("PV %dU" % index, "Upper Limit",
                              RadioSettingValueInteger(minimum, maximum,
                                                       maximum))
            group.append(rs)

    def _get_index(self, element):
        name = element.get_name()
        return int(name.split(" ", 1)[1])

    def kenwood_d7_read_value(self):
        for element in self:
            index = self._get_index(element)
            rv = self._radio._kenwood_get("PV %d" % index)[1]
            lower, upper = rv.split(',', 1)
            lower = int(lower)
            upper = int(upper)
            pvdl = "PV %dL" % index
            pvdu = "PV %dU" % index
            element[pvdl].value.set_value(lower)
            element[pvdl].value._has_changed = False
            element[pvdu].value.set_value(upper)
            element[pvdu].value._has_changed = False

    def changed(self):
        for element in self:
            for bound in element:
                if bound.changed():
                    return True
        return False

    # TODO: Custom validator things...

    def kenwood_d7_set_value(self):
        for element in self:
            index = self._get_index(element)
            pvdl = "PV %dL" % index
            pvdu = "PV %dU" % index
            if element[pvdl].changed() or element[pvdu].changed():
                lower = element[pvdl].value.get_value()
                upper = element[pvdu].value.get_value()
                args = "%05d,%05d" % (lower, upper)
                self._radio._kenwood_set(element.get_name(), args)
                element[pvdl].value._has_changed = False
                element[pvdu].value._has_changed = False


class KenwoodD7Family(chirp_common.LiveRadio):
    VENDOR = "Kenwood"
    MODEL = ""
    HARDWARE_FLOW = False

    _ARG_DELIMITER = " "
    _BAUDS = [9600]
    _CMD_DELIMITER = "\r"
    _DISABLE_AI_CMD = ('AI', '0')
    _DUPLEX = {0: "", 1: "+", 2: "-"}
    _HAS_NAME = True
    _LOCK = threading.Lock()
    _MODES = {0: "FM", 1: "AM"}
    _NOCACHE = "CHIRP_NOCACHE" in os.environ
    _SPLIT = True
    _STEPS = (5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0)
    _TONES = chirp_common.OLD_TONES
    _LOWER = 0
    _UPPER = 199
    _BANDS = []

    _CALL_CHANS = ("VHF Call", "UHF Call")
    _SPECIAL_CHANS = ("L0", "U0",
                      "L1", "U1",
                      "L2", "U2",
                      "L3", "U3",
                      "L4", "U4",
                      "L5", "U5",
                      "L6", "U6",
                      "L7", "U7",
                      "L8", "U8",
                      "L9", "U9",
                      *_CALL_CHANS)

    # These are used more than once in _COMMON_SETTINGS
    _BOOL = {'type': 'bool'}
    _DATA_BAND = {'type': 'list',
                  'values': ("A", "B", "A:TX/B:RX", "A:RX/B:TX")}
    _DTMF_MEMORY = {'type': KenwoodD7DTMFMemory}
    _ON_OFF_DUAL_MAP = {'type': 'map',
                        'map': (("Off", "0"), ("On", "1,0")),
                        'set_requires': (('DL', True),),
                        'get_requires': (('DL', True),)}
    _POSITION = {'type': KenwoodD7Position}
    _SSTV_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !?-/"
    _SSTV_COLOURS = {'type': 'list',
                     'values': ("Black", "Blue", "Red", "Magenta", "Green",
                                "Cyan", "Yellow", "White")}
    _STATUS_TEXT = {'type': 'string', 'max_len': 32}
    _SQUELCH = {'type': 'list', 'digits': 2,
                'values': ("Open", "1", "2", "3", "4", "5")}
    # Settings that are shared by at least two radios.
    # If a third radio does not have the setting at all, the presence
    # here won't matter.  If it has it but with different parameters,
    # it can be overridden in the subclass _SETTINGS dict.
    _COMMON_SETTINGS = {
        "AIP": _BOOL,
        "ARL": {'type': 'map',
                'map': (('Off', '0000'),) + tuple(
                    [('%i' % x, '%04i' % x)
                     for x in range(10, 2510, 10)])},
        "ARLM": {'type': 'string', 'max_len': 45},
        "AMGG": {'type': 'string', 'max_len': 45,
                 'charset': "ABCDEFGHIJKLMNOPQRSTUVWXYZ*,-0123456789"},
        "AMR": _BOOL,
        "APO": {'type': 'list',
                'values': ("Off", "30min", "60min")},
        "ARO": _BOOL,
        # ASC x requires that the specified VFO is enabled on TH-D7G
        # (ie: dual is on or VFO is current) for both fetch and set
        # Easiest to just enable DL before set/read
        "ASC 0": _ON_OFF_DUAL_MAP,
        "ASC 1": _ON_OFF_DUAL_MAP,
        "BAL": {'type': 'list',
                'values': ("4:0", "3:1", "2:2", "1:3", "0:4")},
        "BC": {'type': 'list',
               'values': ("A", "B")},
        "BCN": _BOOL,
        # BEL x requires that the specified VFO is enabled on TH-D7G
        # (ie: dual is on or VFO is current) for both fetch and set
        # Easiest to just enable DL before set/read
        "BEL 0": _ON_OFF_DUAL_MAP,
        "BEL 1": _ON_OFF_DUAL_MAP,
        "BEP": {'type': 'list',
                'values': ("Off", "Key", "Key+Data", "All")},
        "BEPT": {'type': 'list',
                 'values': ("Off", "Mine", "All New", "All")},
        "CH": _BOOL,
        "CKEY": {'type': 'list',
                 'values': ("Call", "1750 Hz")},
        "CNT": {'type': 'integer', 'min': 1, 'max': 16},
        "DL": _BOOL,
        "DS": {'type': 'list',
               'values': ("Data Band", "Both Bands")},
        "DTB": _DATA_BAND,
        "DTBA": _DATA_BAND,
        "dtmfmem 00": _DTMF_MEMORY,
        "dtmfmem 01": _DTMF_MEMORY,
        "dtmfmem 02": _DTMF_MEMORY,
        "dtmfmem 03": _DTMF_MEMORY,
        "dtmfmem 04": _DTMF_MEMORY,
        "dtmfmem 05": _DTMF_MEMORY,
        "dtmfmem 06": _DTMF_MEMORY,
        "dtmfmem 07": _DTMF_MEMORY,
        "dtmfmem 08": _DTMF_MEMORY,
        "dtmfmem 09": _DTMF_MEMORY,
        "DTX": {'type': 'list',
                'values': ("Manual", "PTT", "Auto")},
        "ELK": {'type': 'bool'},
        "GU": {'type': 'list',
               'values': ("Not Used", "NMEA", "NMEA96")},
        # This isn't exactly shared, but each radio adds to this list
        "ICO": {'type': 'map',
                'map': (('Kenwood', '0,0'),
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
                        ('Van', '0,E'))},
        "KILO": {'type': 'list',
                 'values': ("Miles", "Kilometers")},
        "LK": _BOOL,
        "LMP": _BOOL,
        "MAC": _SSTV_COLOURS,
        "MES": {'type': 'string', 'max_len': 8},
        # NOTE: Requires memory mode to be active
        "MNF": {'type': 'list',
                'values': ("Name", "Frequency")},
        "MP 1": _POSITION,
        "MP 2": _POSITION,
        "MP 3": _POSITION,
        "MYC": {'type': 'string', 'max_len': 9},
        "PAMB": {'type': 'list',
                 'values': ("Off", "1 Digit", "2 Digits", "3 Digits",
                            "4 Digits")},
        "PKSA": {'type': 'list',
                 'values': ("1200", "9600")},
        "POSC": {'type': 'list',
                 'values': ("Off Duty", "Enroute", "In Service", "Returning",
                            "Committed", "Special", "Priority", "CUSTOM 0",
                            "CUSTOM 1", "CUSTOM 2", "CUSTOM 4", "CUSTOM 5",
                            "CUSTOM 6", "Emergency")},
        "PP": {'type': 'string', 'max_len': 32},
        "PT": {'type': 'list',
               'values': ("100ms", "200ms", "500ms", "750ms",
                          "1000ms", "1500ms", "2000ms")},
        "PV": {'type': KenwoodD7ProgrammableVFOs},
        "RSC": _SSTV_COLOURS,
        "RSV": {'type': 'string', 'max_len': 10, 'charset': _SSTV_CHARSET},
        "SCC": {'type': 'string', 'max_len': 8},
        "SCR": {'type': 'list',
                'values': ("Time", "Carrier", "Seek")},
        "SCT": {'type': 'string', 'max_len': 8},
        "SKTN": {'type': 'map',
                 'map': tuple([(str(x), "%02d" % (ind + 1))
                               for ind, x in enumerate(_TONES) if x != 69.3])},
        "SMC": _SSTV_COLOURS,
        "SMSG": {'type': 'string', 'max_len': 9, 'charset': _SSTV_CHARSET},
        "SMY": {'type': 'string', 'max_len': 8, 'charset': _SSTV_CHARSET},
        "SQ 0": _SQUELCH,
        "SQ 1": _SQUELCH,
        "STAT 1": _STATUS_TEXT,
        "STAT 2": _STATUS_TEXT,
        "STAT 3": _STATUS_TEXT,
        "STXR": {'type': 'list',
                 'values': ("Off", "1/1", "1/2", "1/3", "1/4", "1/5", "1/6",
                            "1/7", "1/8")},
        "SV": {'type': 'list',
               'values': ("Off", "0.2s", "0.4s", "0.6s", "0.8s", "1.0s",
                          "2s", "3s", "4s", "5s")},
        "TEMP": {'type': 'list',
                 'values': ("°F", "°C")},
        "TH": _BOOL,
        "TNC": _BOOL,
        "TSP": _BOOL,
        "TXD": {'type': 'map',
                'map': (("100ms", "1"), ("200ms", "2"), ("300ms", "3"),
                        ("400ms", "4"), ("500ms", "5"), ("750ms", "6"),
                        ("1000ms", "7"))},
        "TXH": _BOOL,
        "TXI": {'type': 'list',
                'values': ("30sec", "1min", "2min", "3min", "4min", "5min",
                           "10min", "20min", "30min")},
        "TXS": _BOOL,
        "TZ": {'type': 'list',
               'values': ("UTC - 12:00", "UTC - 11:30", "UTC - 11:00",
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
                          "UTC + 11:00", "UTC + 11:30", "UTC + 12:00")},
        "UPR": {'type': 'string', 'max_len': 9,
                'charset': "ABCDEFGHIJKLMNOPQRSTUVWXYZ-0123456789"},
        "VCS": _BOOL,
        "WAY": {'type': 'list',
                'values': ("Off", "6 digit NMEA", "7 digit NMEA",
                           "8 digit NMEA", "9 digit NMEA", "6 digit Magellan",
                           "DGPS")}}

    _PROGRAMMABLE_VFOS = (
        ("Band A, 118 MHz Sub-Band", 1, 118, 135),
        ("Band A, VHF Sub-Band", 2, 136, 173),
        ("Band B, VHF Sub-Band", 3, 144, 147),
        ("Band B, UHF Sub-Band", 6, 400, 479))

    def __init__(self, *args, **kwargs):
        chirp_common.LiveRadio.__init__(self, *args, **kwargs)

        # Clear the caches
        self._memcache = {}
        self._setcache = {}
        self._baud = 9600
        self._cur_setting = 0
        self._setting_count = 0
        self._vfo = 0
        if self.pipe:
            self.pipe.timeout = 0.5
            radio_id = self._get_id()
            if hasattr(self, '_ID_STRING'):
                id_str = self._ID_STRING
            else:
                id_str = self.MODEL.split(" ")[0]
            if radio_id != id_str:
                raise Exception("Radio reports %s (not %s)" % (radio_id,
                                                               id_str))

            self._command(*self._DISABLE_AI_CMD)

    # This returns the index value for CR/CW commands, not the index
    # in the memory list grid
    def _call_index(self, memid_or_index):
        if isinstance(memid_or_index, int):
            memid = self._index_to_memid(memid_or_index)
        else:
            memid = memid_or_index
        return self._CALL_CHANS.index(memid)

    # This returns the memid from the index value in CR/CW commands, not
    # the index in the memory list grid
    def _call_index_to_memid(self, index):
        return self._CALL_CHANS[index]

    def _cmd_get_memory_name(self, memid):
        return "MNA", "%i,%s" % (self._vfo, memid)

    def _cmd_get_memory_or_split(self, memid, split):
        sd = split and 1 or 0
        if self._is_call(memid):
            return "CR", "%d,%d" % (self._call_index(memid), split)
        return "MR", "%i,%d,%s" % (self._vfo, sd, memid)

    def _cmd_set_memory_name(self, memid, name):
        if self._is_call(memid):
            return None
        return "MNA", "%i,%s,%s" % (self._vfo, memid, name)

    def _cmd_set_memory_or_split(self, memid, memory, split):
        if not memory.empty:
            spec = "," + ",".join(self._make_mem_spec(memid, memory))
        else:
            spec = ''
        sd = split and 1 or 0
        if (self._is_call(memid)):
            return "CW", "%d,%d%s" % (self._call_index(memid), sd, spec)
        return "MW", "%i,%d,%s%s" % (self._vfo, sd, memid, spec)

    def _count_settings(self, entries):
        for entry in entries:
            if (type(entry[1]) is tuple):
                self._count_settings(entry[1])
            else:
                self._setting_count += 1

    def _create_group(self, entries, grp=None):
        if grp is None:
            grp = RadioSettings()
        for entry in entries:
            if (type(entry[1]) is tuple):
                subgrp = RadioSettingGroup(entry[0].lower(), entry[0])
                grp.append(self._create_group(entry[1], subgrp))
            else:
                setting = self._get_setting_data(entry[0])
                if setting['type'] == 'undefined':
                    continue
                if setting['type'] == 'list':
                    rsvl = RadioSettingValueList(setting['values'])
                    rs = RadioSetting(entry[0], entry[1], rsvl)
                elif setting['type'] == 'bool':
                    rs = RadioSetting(entry[0], entry[1],
                                      RadioSettingValueBoolean(False))
                elif setting['type'] == 'string':
                    params = {}
                    if 'charset' in setting:
                        params['charset'] = setting['charset']
                    else:
                        params['charset'] = chirp_common.CHARSET_ASCII
                    minlen = 'min_len' in setting and setting['min_len'] or 0
                    dummy = params['charset'][0] * minlen
                    rsvs = RadioSettingValueString(minlen,
                                                   setting['max_len'],
                                                   dummy,
                                                   False, **params)
                    rs = RadioSetting(entry[0], entry[1], rsvs)
                elif setting['type'] == 'integer':
                    rs = RadioSetting(entry[0], entry[1],
                                      RadioSettingValueInteger(setting['min'],
                                                               setting['max'],
                                                               setting['min']))
                elif setting['type'] == 'map':
                    rsvs = RadioSettingValueMap(setting['map'],
                                                setting['map'][0][1])
                    rs = RadioSetting(entry[0], entry[1], rsvs)
                else:
                    rs = setting['type'](entry[0], entry[1], self)
                rs.kenwood_d7_loaded = False
                grp.append(rs)
                self._setcache[entry[0]] = rs
        return grp

    def _do_prerequisite(self, cmd, get, do):
        if get:
            arg = 'get_requires'
        else:
            arg = 'set_requires'
        setting = self._get_setting_data(cmd)
        if arg not in setting:
            return
        # Undo prerequisites in the reverse order they were applied
        if not do:
            it = reversed(setting[arg])
        else:
            it = iter(setting[arg])
        for prereq, value in it:
            entry = self._setcache[prereq]
            if not entry.kenwood_d7_loaded:
                self._refresh_setting(entry)
            if do:
                entry.kenwood_d7_old_value = entry.value.get_value()
                entry.value.set_value(value)
            else:
                entry.value.set_value(entry.kenwood_d7_old_value)
            sdata = self._get_setting_data(prereq)
            self._set_setting(prereq, sdata, entry)

    def _drain_input(self):
        oldto = self.pipe.timeout
        self.pipe.timeout = 0
        # Read until a timeout
        while len(self.pipe.read(1)):
            pass
        self.pipe.timeout = oldto

    def _empty_memory(self, memid):
        mem = chirp_common.Memory()
        if self._is_special(memid):
            mem.extd_number = memid
        mem.number = self._memid_to_index(memid)
        mem.empty = True
        mem.immutable = self._get_immutable(memid)
        return mem

    def _get_id(self):
        """Get the ID of the radio attached to @ser"""

        for i in self._BAUDS:
            LOG.info("Trying ID at baud %i" % i)
            self.pipe.baudrate = i
            # Try to force an error
            self.pipe.write(self._CMD_DELIMITER.encode('cp1252'))
            # Wait for it to be sent
            self.pipe.flush()
            self._drain_input()
            try:
                resp = self._command("ID")
            except UnicodeDecodeError:
                # If we got binary here, we are using the wrong rate
                # or not talking to a kenwood live radio.
                continue

            ret = self._parse_id_response(resp)
            if ret is not None:
                self._baud = i
                return ret

            # Radio responded in the right baud rate,
            # but threw an error because of all the crap
            # we have been hurling at it. Retry the ID at this
            # baud rate, which will almost definitely work.
            if "?" in resp:
                resp = self._command("ID")
                ret = self._parse_id_response(resp)
                if ret is not None:
                    self._baud = i
                    return ret
        raise errors.RadioError("No response from radio")

    def _get_immutable(self, memid_or_index):
        if self._is_call(memid_or_index):
            return ['name', 'skip']
        if self._is_pscan(memid_or_index):
            return ['skip']
        return []

    def _get_setting_data(self, setting):
        if setting in self._SETTINGS:
            return self._SETTINGS[setting]
        if setting in self._COMMON_SETTINGS:
            return self._COMMON_SETTINGS[setting]
        if (setting.upper() == setting):
            LOG.debug("Undefined setting: %s" % setting)
        return {'type': 'undefined'}

    def _get_setting_digits(self, setting_data):
        if 'digits' in setting_data:
            return setting_data['digits']
        if setting_data['type'] == 'integer':
            return len(str(setting_data['max']))
        if setting_data['type'] == 'list':
            return len(str(len(setting_data['values'])))
        raise TypeError('Setting data should not have digits')

    def _get_tmode(self, tone, ctcss, dcs):
        """Get the tone mode based on the values of the tone, ctcss, dcs"""
        if dcs and int(dcs) == 1:
            return "DTCS"
        elif int(ctcss):
            return "TSQL"
        elif int(tone):
            return "Tone"
        else:
            return ""

    def _index_to_memid(self, index):
        if not isinstance(index, int):
            raise errors.RadioError("%s passed as memory index"
                                    % str(type(index)))
        if index <= self._UPPER:
            return "%03d" % index
        index -= self._UPPER
        index -= 1
        return self._SPECIAL_CHANS[index]

    def _is_call(self, memid_or_index):
        if isinstance(memid_or_index, int):
            memid = self._index_to_memid(memid_or_index)
        else:
            memid = memid_or_index
        return memid in self._CALL_CHANS

    def _is_pscan(self, memid_or_index):
        if isinstance(memid_or_index, int):
            memid = self._index_to_memid(memid_or_index)
        else:
            memid = memid_or_index
        if memid[0] == 'L' or memid[0] == 'U':
            if memid[1:].isdigit():
                return True
        return False

    def _is_special(self, memid_or_index):
        if isinstance(memid_or_index, str):
            index = self._memid_to_index(memid_or_index)
        else:
            index = memid_or_index
        return index > self._UPPER

    def _iserr(self, result):
        """Returns True if the @result from a radio is an error"""
        return result in ["N", "?"]

    def _keep_reading(self, result):
        return False

    def _kenwood_get(self, cmd):
        self._do_prerequisite(cmd, True, True)
        ret = None
        if " " in cmd:
            suffix = cmd.split(" ", 1)[1]
            resp = self._kenwood_simple_get(cmd)
            if resp[1][0:len(suffix)+1] == suffix + ',':
                resp = (cmd, resp[1][len(suffix)+1:])
                ret = resp
            else:
                raise errors.RadioError("Command %s response value '%s' "
                                        "unusable" % (cmd, resp[1]))
        else:
            ret = self._kenwood_simple_get(cmd)
        self._do_prerequisite(cmd, True, False)
        return ret

    def _kenwood_get_bool(self, cmd):
        _cmd, result = self._kenwood_get(cmd)
        return result == "1"

    def _kenwood_get_int(self, cmd):
        _cmd, result = self._kenwood_get(cmd)
        return int(result)

    def _kenwood_set_success(self, cmd, modcmd, value, response):
        if response[:len(modcmd)] == modcmd:
            return True
        return False

    def _kenwood_set(self, cmd, value):
        self._do_prerequisite(cmd, False, True)
        if " " in cmd:
            resp = self._command(cmd + "," + value)
            modcmd = cmd.split(" ", 1)[0]
        else:
            resp = self._command(cmd, value)
            modcmd = cmd
        self._do_prerequisite(cmd, False, False)
        if self._kenwood_set_success(cmd, modcmd, value, resp):
            return
        raise errors.RadioError("Radio refused to set %s" % cmd)

    def _kenwood_set_bool(self, cmd, value):
        return self._kenwood_set(cmd, str(int(value)))

    def _kenwood_set_int(self, cmd, value, digits=1):
        return self._kenwood_set(cmd, ("%%0%ii" % digits) % value)

    def _kenwood_simple_get(self, cmd):
        resp = self._command(cmd)
        if " " in resp:
            return resp.split(" ", 1)
        else:
            if resp == cmd:
                return [resp, ""]
            else:
                raise errors.RadioError("Radio refused to return %s" % cmd)

    def _mem_spec_fixup(self, spec, memid, mem):
        pass

    def _make_mem_spec(self, memid, mem):
        if mem.duplex in " -+":
            duplex = util.get_dict_rev(self._DUPLEX, mem.duplex)
            offset = mem.offset
        else:
            duplex = 0
            offset = 0

        spec = [
            "%011i" % mem.freq,
            "%X" % self._STEPS.index(mem.tuning_step),
            "%i" % duplex,
            "0",
            "%i" % (mem.tmode == "Tone"),
            "%i" % (mem.tmode == "TSQL"),
            "",  # DCS Flag
            "%02i" % (self._TONES.index(mem.rtone) + 1),
            "",  # DCS Code
            "%02i" % (self._TONES.index(mem.ctone) + 1),
            "%09i" % offset,
            "%i" % util.get_dict_rev(self._MODES, mem.mode)]
        if not self._is_call(memid):
            spec.append("%i" % ((mem.skip == "S") and 1 or 0))
        self._mem_spec_fixup(spec, memid, mem)

        return tuple(spec)

    def _make_split_spec(self, mem):
        return ("%011i" % mem.offset, "0")

    def _memid_to_index(self, memid):
        if not isinstance(memid, str):
            raise errors.RadioError("%s passed as memory id"
                                    % str(type(memid)))
        if memid in self._SPECIAL_CHANS:
            return self._SPECIAL_CHANS.index(memid) + self._UPPER + 1
        return int(memid)

    def _parse_id_response(self, resp):
        # most kenwood VHF+ radios
        if " " in resp:
            return resp.split(" ")[1]
        return None

    def _parse_mem_fixup(self, mem, spec):
        pass

    def _parse_mem(self, result):
        mem = chirp_common.Memory()

        value = result.split(" ")[1]
        spec = value.split(",")
        if len(spec) == 14:  # This is a Call memory
            spec.insert(1, 0)   # Add "bank"
            spec.insert(15, 0)  # Add "skip"
            memid = self._call_index_to_memid(int(spec[0]))
            mem.extd_number = memid
            mem.number = self._memid_to_index(mem.extd_number)
        elif spec[2].isdigit():  # Normal memory
            mem.number = int(spec[2])
            memid = self._index_to_memid(mem.number)
        else:  # Program Scan memory
            memid = spec[2]
            mem.extd_number = memid
            mem.number = self._memid_to_index(mem.extd_number)
        mem.immutable = self._get_immutable(memid)
        mem.freq = int(spec[3], 10)
        mem.tuning_step = self._STEPS[int(spec[4], 16)]
        mem.duplex = self._DUPLEX[int(spec[5])]
        mem.tmode = self._get_tmode(spec[7], spec[8], spec[9])
        mem.rtone = self._TONES[int(spec[10]) - 1]
        mem.ctone = self._TONES[int(spec[12]) - 1]
        if spec[13]:
            mem.offset = int(spec[13])
        else:
            mem.offset = 0
        mem.mode = self._MODES[int(spec[14])]
        if 'skip' not in mem.immutable:
            mem.skip = int(spec[15]) and "S" or ""
        self._parse_mem_fixup(mem, spec)
        return mem

    def _parse_split(self, mem, result):
        value = result.split(" ")[1]
        spec = value.split(",")
        mem.duplex = "split"
        # TODO: There's another parameter here... not sure what it is
        if len(spec) == 14:  # Call memory
            mem.offset = int(spec[2])
        else:
            mem.offset = int(spec[3])

    def _refresh_setting(self, entry):
        name = entry.get_name()
        setting = self._get_setting_data(name)
        # TODO: It would be nice to bump_wait_dialog here...
        #       Also, this is really only useful for the cli. :(
        if self.status_fn:
            status = chirp_common.Status()
            status.cur = self._cur_setting
            status.max = self._setting_count
            status.msg = "Fetching %-30s" % entry.get_shortname()
            # self.bump_wait_dialog(int(status.cur * 100 / status.max),
            #                       "Fetching %s" % entry[1])
            self.status_fn(status)
        self._cur_setting += 1
        if setting['type'] == 'list':
            value = self._kenwood_get_int(name)
            entry.value.set_index(value)
        elif setting['type'] == 'bool':
            value = self._kenwood_get_bool(name)
            entry.value.set_value(value)
        elif setting['type'] == 'string':
            value = self._kenwood_get(name)[1]
            entry.value.set_value(value)
        elif setting['type'] == 'integer':
            value = self._kenwood_get_int(name)
            entry.value.set_value(value)
        elif setting['type'] == 'map':
            value = self._kenwood_get(name)[1]
            entry.value.set_mem_val(value)
        else:
            entry.kenwood_d7_read_value()
        if hasattr(entry, 'value'):
            if hasattr(entry.value, '_has_changed'):
                entry.value._has_changed = False
        entry.kenwood_d7_loaded = True

    def _refresh_settings(self):
        for entry in self._setcache.values():
            if not entry.kenwood_d7_loaded:
                self._refresh_setting(entry)

    def _validate_memid(self, memid_or_index):
        if isinstance(memid_or_index, int):
            index = memid_or_index
            memid = self._index_to_memid(memid_or_index)
        else:
            memid = memid_or_index
            index = self._memid_to_index(memid_or_index)
        if memid in self._SPECIAL_CHANS:
            pass
        elif index < self._LOWER or index > self._UPPER:
            raise errors.InvalidMemoryLocation(
                "Number must be between %i and %i" % (self._LOWER,
                                                      self._UPPER))
        return index, memid

    def _validate_memory(self, memory):
        if memory.number is None:
            return self._validate_memid(memory.extd_number)
        return self._validate_memid(memory.number)

    def _set_setting(self, name, sdata, element):
        if sdata['type'] == 'bool':
            value = element.value.get_value()
            self._kenwood_set_bool(name, value)
            element.value._has_changed = False
        elif sdata['type'] == 'integer':
            value = element.value.get_value()
            digits = self._get_setting_digits(sdata)
            self._kenwood_set_int(name, value, digits)
            element.value._has_changed = False
        elif sdata['type'] == 'string':
            value = element.value.get_value()
            self._kenwood_set(name, value)
            element.value._has_changed = False
        elif sdata['type'] == 'list':
            value = element.value.get_value()
            digits = self._get_setting_digits(sdata)
            self._kenwood_set_int(name, sdata['values'].index(value),
                                  digits)
            element.value._has_changed = False
        elif sdata['type'] == 'map':
            self._kenwood_set(name, element.value.get_mem_val())
            element.value._has_changed = False
        # TODO: I would like to have tried this first then fetched
        # value, but we can't use hasattr() on settings due to the
        # Magic foo.value attribute in chirp/settings.py.  Instead,
        # I need to get_value() each time. :(
        elif hasattr(element, 'kenwood_d7_set_value'):
            element.kenwood_d7_set_value()
        else:
            raise TypeError('No way to set %s value' % name)

    def _command(self, cmd, *args):
        """Send @cmd to radio via @ser"""

        # This lock is needed to allow clicking the settings tab while
        # the memories are still loading.  Most important with the TH-D7A
        # and TH-D7A(G) with the 9600bps maximum.
        with self._LOCK:
            if args:
                cmd += self._ARG_DELIMITER + self._ARG_DELIMITER.join(args)
            cmd += self._CMD_DELIMITER
            self._drain_input()

            LOG.debug("PC->RADIO: %s" % cmd.strip())
            self.pipe.write(cmd.encode('cp1252'))
            cd = self._CMD_DELIMITER.encode('cp1252')
            keep_reading = True
            while keep_reading:
                result = self.pipe.read_until(cd).decode('cp1252')
                if result.endswith(self._CMD_DELIMITER):
                    keep_reading = self._keep_reading(result)
                    LOG.debug("RADIO->PC: %r" % result.strip())
                    result = result[:-1]
                else:
                    keep_reading = False
                    LOG.error("Timeout waiting for data")

        return result.strip()

    def erase_memory(self, memid_or_index):
        index, memid = self._validate_memid(memid_or_index)
        if memid not in self._memcache:
            return
        # TODO: Can't disable the menu item?
        if self._is_call(memid):
            # Raising an error just makes the memory errored
            return
        cmd = self._cmd_set_memory_or_split(memid, self._empty_memory(memid),
                                            False)
        resp = self._command(*cmd)
        if self._iserr(resp):
            raise errors.RadioError("Radio refused delete of %s" % memid)
        del self._memcache[memid]

    def get_features(self, *args, **kwargs):
        rf = chirp_common.RadioFeatures(*args, **kwargs)
        rf.valid_tones = tuple([x for x in self._TONES if x != 69.3])
        rf.has_settings = True
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_mode = True
        rf.has_tuning_step = True
        rf.can_odd_split = True
        rf.valid_name_length = 8
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_modes = list(self._MODES.values())
        rf.valid_tmodes = ["", "Tone", "TSQL"]
        rf.valid_characters = \
            chirp_common.CHARSET_ALPHANUMERIC + "/.-+*)('&%$#! ~}|{"
        rf.valid_tuning_steps = self._STEPS
        rf.memory_bounds = (self._LOWER, self._UPPER)
        rf.valid_special_chans = self._SPECIAL_CHANS
        rf.valid_bands = self._BANDS
        return rf

    def get_memory(self, memid_or_index):
        index, memid = self._validate_memid(memid_or_index)
        if memid in self._memcache and not self._NOCACHE:
            return self._memcache[memid]

        result = self._command(*self._cmd_get_memory_or_split(memid,
                                                              False))
        if result == "N":
            mem = self._empty_memory(memid)
            self._memcache[memid] = mem
            return mem
        elif self._ARG_DELIMITER not in result:
            LOG.error("Not sure what to do with this: `%s'" % result)
            raise errors.RadioError("Unexpected result returned from radio")

        mem = self._parse_mem(result)
        self._memcache[memid] = mem

        if self._HAS_NAME:
            cmd = self._cmd_get_memory_name(memid)
            if cmd is not None:
                result = self._command(*cmd)
                if " " in result:
                    value = result.split(" ", 1)[1]
                    mem.name = value.split(",", 2)[2]
        if mem.duplex == "" and self._SPLIT:
            cmd = self._cmd_get_memory_or_split(memid, True)
            if cmd is not None:
                result = self._command(*cmd)
                if " " in result:
                    self._parse_split(mem, result)

        return mem

    def get_settings(self):
        if self._setting_count == 0:
            self._count_settings(self._SETTINGS_MENUS)
        ret = self._create_group(self._SETTINGS_MENUS)
        self._cur_setting = 0
        self._refresh_settings()
        status = chirp_common.Status()
        status.cur = self._setting_count
        status.max = self._setting_count
        status.msg = "%-40s" % "Done"
        self.status_fn(status)
        return ret

    def set_memory(self, memory):
        index, memid = self._validate_memory(memory)
        if memory.empty:
            self.erase_memory(memid)
            LOG.debug("set_memory passed an empty memory, perhaps "
                      "you wanted erase_memory()?")
            return
        r1 = self._command(*self._cmd_set_memory_or_split(memid, memory,
                                                          False))
        if self._iserr(r1):
            raise errors.InvalidDataError("Radio refused %s" % memid)
        self._memcache[memid] = memory.dupe()
        if self._HAS_NAME:
            r2cmd = self._cmd_set_memory_name(memid, memory.name)
            if r2cmd is not None:
                r2 = self._command(*r2cmd)
                if self._iserr(r2):
                    raise errors.InvalidDataError("Radio refused name %s: %s" %
                                                  (memid, repr(memory.name)))
        if memory.duplex == "split" and self._SPLIT:
            result = self._command(*self._cmd_set_memory_or_split(memid,
                                                                  memory,
                                                                  True))
            if self._iserr(result):
                raise errors.InvalidDataError("Radio refused %s" %
                                              memid)

    def set_settings(self, settings):
        for element in settings:
            name = element.get_name()
            sdata = self._get_setting_data(name)
            if sdata['type'] == 'undefined':
                if isinstance(element, RadioSettingGroup):
                    self.set_settings(element)
                continue
            if not element.changed():
                continue
            self._set_setting(name, sdata, element)


@directory.register
class THD7Radio(KenwoodD7Family):
    """Kenwood TH-D7"""
    MODEL = "TH-D7"

    _BANDS = [(118000000, 174000000), (400000000, 470000000)]
    _SETTINGS = {
        "BEPT": {'type': 'list',
                 'values': ("Off", "Mine", "All New")},
        "DTB": {'type': 'list',
                'values': ("A", "B")},
        "DTBA": {'type': 'list',
                 'values': ("A", "B", "A:TX/B:RX", "A:RX/B:TX")},
        "GU": {'type': 'list',
               'values': ("Not Used", "NMEA")},
        "MP": {'type': 'position'},
        "STAT": {'type': 'string', 'max_len': 20},
        "TEMP": {'type': 'list',
                 'values': ("Miles / °F", "Kilometers / °C")}}

    _SETTINGS_MENUS = (
        ('Main',
            (("ASC 0", "Automatic Simplex Check Band A"),
             ("ASC 1", "Automatic Simplex Check Band B"),
             ("BAL", "Balance"),
             ("BC", "Band"),
             ("BEL 0", "Tone Alert Band A"),
             ("BEL 1", "Tone Alert Band B"),
             ("CH", "Channel Mode Display"),
             ("DL", "Dual"),
             ("LMP", "Lamp"),
             ("LK", "Lock"),
             # MNF requires that the *current* VFO be in MR mode
             # Also, it has a direct key
             # ("MNF", "Memory Display Mode"),
             ("SQ 0", "Band A Squelch"),
             ("SQ 1", "Band B Squelch"),
             # We likely don't want to enable this from Chirp...
             # ("TNC", "Packet Mode"))),
             )),
        ('Radio',
            (('Display',
                (("MES", "Power-ON Message"),
                 ("CNT", "Contrast"))),
             ('Save',
                (("SV", "Battery Saver Interval"),
                 ("APO", "Automatic Power Off (APO)"))),
             ('DTMF',
                (("dtmfmem 00", "Number Store #0"),
                 ("dtmfmem 01", "Number Store #1"),
                 ("dtmfmem 02", "Number Store #2"),
                 ("dtmfmem 03", "Number Store #3"),
                 ("dtmfmem 04", "Number Store #4"),
                 ("dtmfmem 05", "Number Store #5"),
                 ("dtmfmem 06", "Number Store #6"),
                 ("dtmfmem 07", "Number Store #7"),
                 ("dtmfmem 08", "Number Store #8"),
                 ("dtmfmem 09", "Number Store #9"),
                 ("TSP", "TX Speed"),
                 ("TXH", "TX Hold"),
                 ("PT", "Pause"))),
             ('TNC',
                (("DTB", "Data band select"),
                 ("DS", "DCD sense"))),
             ('AUX',
                (("ARO", "Automatic Repeater Offset"),
                 ("SCR", "Scan Resume"),
                 ("BEP", "Key Beep"),
                 ("ELK", "Tuning Enable"),
                 ("TXS", "TX Inhibit"),
                 ("AIP", "Advanced Intercept Point"),
                 ("TH", "TX Hold, 1750 Hz"),
                 ("XXX", "VHF band narrow TX deviation"))))),
        ('APRS',
            (("MYC", "My call sign"),
             ("GU", "GPS receiver"),
             # Untested... D7G and D700 take an index, but since D7A only has
             # one position and is older, it may not.
             # ("MP", "Latitude / longitude data"),
             ("POSC", "Position comment"),
             ("ICO", "Station icon"),
             ("STAT", "Status text"),
             ("TXI", "Beacon transmit interval"),
             ("PP", "Packet path"),
             ("DTX", "Beacon transmit method"),
             ("UPR", "Group code"),
             ("ARL", "Reception restriction distance"),
             ("TEMP", "Unit for temperature"))),
        ('SSTV',
            (("SMY", "My call sign"),
             ("MAC", "Color for call sign"),
             ("SMSG", "Message"),
             ("SMC", "Color for message"),
             ("RSV", "RSV report"),
             ("RSC", "Color for RSV report"),
             ("VCS", "VC-H1 Control"))),
        ('SkyCommand',
            (("SCC", "Commander call sign"),
             ("SCT", "Transporter call sign"),
             ("SKTN", "Tone frequency select"))))


@directory.register
class THD7GRadio(KenwoodD7Family):
    """Kenwood TH-D7G"""
    MODEL = "TH-D7G"

    _BANDS = [(118000000, 174000000), (400000000, 470000000)]
    _APRS_EXTRA = (('WEATHER Station (blue)', '1,/#'),
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
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Zero overlaid',
                    '1,0&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with One overlaid', '1,1&'),
                   ('TX igate with path set to 2 hops', '1,2&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Three overlaid',
                    '1,3&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Four overlaid',
                    '1,4&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Five overlaid',
                    '1,5&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Six overlaid', '1,6&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Seven overlaid',
                    '1,7&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Eight overlaid',
                    '1,8&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Nine overlaid',
                    '1,9&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX with Letter A overlaid',
                    '1,A&'),
                   ('I=Igte R=RX T=1hopTX 2=2hopTX  with Letter B overlaid',
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
                   ('OVERLAY DIGI (green star) with Letter A overlaid',
                    '1,A#'),
                   ('OVERLAY DIGI (green star) with Letter B overlaid',
                    '1,B#'),
                   ('OVERLAY DIGI (green star) with Letter C overlaid',
                    '1,C#'),
                   ('OVERLAY DIGI (green star) with Letter D overlaid',
                    '1,D#'),
                   ('OVERLAY DIGI (green star) with Letter E overlaid',
                    '1,E#'),
                   ('OVERLAY DIGI (green star) with Letter F overlaid',
                    '1,F#'),
                   ('OVERLAY DIGI (green star) with Letter G overlaid',
                    '1,G#'),
                   ('OVERLAY DIGI (green star) with Letter H overlaid',
                    '1,H#'),
                   ('OVERLAY DIGI (green star) with Letter I overlaid',
                    '1,I#'),
                   ('OVERLAY DIGI (green star) with Letter J overlaid',
                    '1,J#'),
                   ('OVERLAY DIGI (green star) with Letter K overlaid',
                    '1,K#'),
                   ('OVERLAY DIGI (green star) with Letter L overlaid',
                    '1,L#'),
                   ('OVERLAY DIGI (green star) with Letter M overlaid',
                    '1,M#'),
                   ('OVERLAY DIGI (green star) with Letter N overlaid',
                    '1,N#'),
                   ('OVERLAY DIGI (green star) with Letter O overlaid',
                    '1,O#'),
                   ('OVERLAY DIGI (green star) with Letter P overlaid',
                    '1,P#'),
                   ('OVERLAY DIGI (green star) with Letter Q overlaid',
                    '1,Q#'),
                   ('OVERLAY DIGI (green star) with Letter R overlaid',
                    '1,R#'),
                   ('OVERLAY DIGI (green star) with Letter S overlaid',
                    '1,S#'),
                   ('OVERLAY DIGI (green star) with Letter T overlaid',
                    '1,T#'),
                   ('OVERLAY DIGI (green star) with Letter U overlaid',
                    '1,U#'),
                   ('OVERLAY DIGI (green star) with Letter V overlaid',
                    '1,V#'),
                   ('OVERLAY DIGI (green star) with Letter W overlaid',
                    '1,W#'),
                   ('OVERLAY DIGI (green star) with Letter X overlaid',
                    '1,X#'),
                   ('OVERLAY DIGI (green star) with Letter Y overlaid',
                    '1,Y#'),
                   ('OVERLAY DIGI (green star) with Letter Z overlaid',
                    '1,Z#'),
                   ('Power Plant with overlay', '1,\\%'),
                   ('Rain (all types w ovrly)', '1,\\`'),
                   ('other Aircraft ovrlys (2014)', '1,\\^'),
                   ('other Aircraft ovrlys (2014) with Zero overlaid', '1,0^'),
                   ('other Aircraft ovrlys (2014) with One overlaid', '1,1^'),
                   ('other Aircraft ovrlys (2014) with Two overlaid', '1,2^'),
                   ('other Aircraft ovrlys (2014) with Three overlaid',
                    '1,3^'),
                   ('other Aircraft ovrlys (2014) with Four overlaid', '1,4^'),
                   ('other Aircraft ovrlys (2014) with Five overlaid', '1,5^'),
                   ('other Aircraft ovrlys (2014) with Six overlaid', '1,6^'),
                   ('other Aircraft ovrlys (2014) with Seven overlaid',
                    '1,7^'),
                   ('other Aircraft ovrlys (2014) with Eight overlaid',
                    '1,8^'),
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
                   ('OVERLAYED CARs & Vehicles with Letter A overlaid',
                    '1,A>'),
                   ('BEV - Battery EV', '1,B>'),
                   ('OVERLAYED CARs & Vehicles with Letter C overlaid',
                    '1,C>'),
                   ('DIY - Do it yourself ', '1,D>'),
                   ('Ethanol (was electric)', '1,E>'),
                   ('Fuelcell or hydrogen', '1,F>'),
                   ('OVERLAYED CARs & Vehicles with Letter G overlaid',
                    '1,G>'),
                   ('Hybrid', '1,H>'),
                   ('OVERLAYED CARs & Vehicles with Letter I overlaid',
                    '1,I>'),
                   ('OVERLAYED CARs & Vehicles with Letter J overlaid',
                    '1,J>'),
                   ('OVERLAYED CARs & Vehicles with Letter K overlaid',
                    '1,K>'),
                   ('Leaf', '1,L>'),
                   ('OVERLAYED CARs & Vehicles with Letter M overlaid',
                    '1,M>'),
                   ('OVERLAYED CARs & Vehicles with Letter N overlaid',
                    '1,N>'),
                   ('OVERLAYED CARs & Vehicles with Letter O overlaid',
                    '1,O>'),
                   ('PHEV - Plugin-hybrid', '1,P>'),
                   ('OVERLAYED CARs & Vehicles with Letter Q overlaid',
                    '1,Q>'),
                   ('OVERLAYED CARs & Vehicles with Letter R overlaid',
                    '1,R>'),
                   ('Solar powered', '1,S>'),
                   ('Tesla  (temporary)', '1,T>'),
                   ('OVERLAYED CARs & Vehicles with Letter U overlaid',
                    '1,U>'),
                   ('Volt (temporary)', '1,V>'),
                   ('OVERLAYED CARs & Vehicles with Letter W overlaid',
                    '1,W>'),
                   ('Model X', '1,X>'),
                   ('OVERLAYED CARs & Vehicles with Letter Y overlaid',
                    '1,Y>'),
                   ('OVERLAYED CARs & Vehicles with Letter Z overlaid',
                    '1,Z>'),
                   ('TNC Stream Switch', '1,\\|'),
                   ('TNC Stream Switch', '1,\\~'),
                   ('Bank or ATM  (green box)', '1,\\$'),
                   ('CIRCLE (IRLP/Echolink/WIRES)', '1,\\0'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Zero overlaid', '1,00'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with One overlaid', '1,10'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Two overlaid', '1,20'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Three overlaid',
                    '1,30'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Four overlaid', '1,40'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Five overlaid', '1,50'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Six overlaid', '1,60'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Seven overlaid',
                    '1,70'),
                   ('CIRCLE (IRLP/Echolink/WIRES) with Eight overlaid',
                    '1,80'),
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
                   ('overlayBOX DTMF & RFID & XO with Letter B overlaid',
                    '1,BA'),
                   ('overlayBOX DTMF & RFID & XO with Letter C overlaid',
                    '1,CA'),
                   ('D-Star report', '1,DA'),
                   ('Echolink DTMF report', '1,EA'),
                   ('overlayBOX DTMF & RFID & XO with Letter F overlaid',
                    '1,FA'),
                   ('overlayBOX DTMF & RFID & XO with Letter G overlaid',
                    '1,GA'),
                   ('House DTMF user', '1,HA'),
                   ('IRLP DTMF report', '1,IA'),
                   ('overlayBOX DTMF & RFID & XO with Letter J overlaid',
                    '1,JA'),
                   ('overlayBOX DTMF & RFID & XO with Letter K overlaid',
                    '1,KA'),
                   ('overlayBOX DTMF & RFID & XO with Letter L overlaid',
                    '1,LA'),
                   ('overlayBOX DTMF & RFID & XO with Letter M overlaid',
                    '1,MA'),
                   ('overlayBOX DTMF & RFID & XO with Letter N overlaid',
                    '1,NA'),
                   ('overlayBOX DTMF & RFID & XO with Letter O overlaid',
                    '1,OA'),
                   ('overlayBOX DTMF & RFID & XO with Letter P overlaid',
                    '1,PA'),
                   ('overlayBOX DTMF & RFID & XO with Letter Q overlaid',
                    '1,QA'),
                   ('RFID report', '1,RA'),
                   ('overlayBOX DTMF & RFID & XO with Letter S overlaid',
                    '1,SA'),
                   ('overlayBOX DTMF & RFID & XO with Letter T overlaid',
                    '1,TA'),
                   ('overlayBOX DTMF & RFID & XO with Letter U overlaid',
                    '1,UA'),
                   ('overlayBOX DTMF & RFID & XO with Letter V overlaid',
                    '1,VA'),
                   ('overlayBOX DTMF & RFID & XO with Letter W overlaid',
                    '1,WA'),
                   ('OLPC Laptop XO', '1,XA'),
                   ('overlayBOX DTMF & RFID & XO with Letter Y overlaid',
                    '1,YA'),
                   ('overlayBOX DTMF & RFID & XO with Letter Z overlaid',
                    '1,ZA'),
                   ('ARRL,ARES,WinLINK,Dstar, etc', '1,\\a'),
                   ('AVAIL (BlwngSnow ==> E ovly B', '1,\\B'),
                   ('AVAIL (Blwng Dst/Snd => E ovly)', '1,\\b'),
                   ('Coast Guard', '1,\\C'),
                   ('CD triangle RACES/SATERN/etc', '1,\\c'),
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
                   ('AVAIL (Lightning ==> I ovly L)', '1,\\J'),
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
                   ('Pharmacy Rx (Apothecary)', '1,\\X'),
                   ('Wreck or Obstruction ->X<-', '1,\\x'),
                   ('Radios and devices', '1,\\Y'),
                   ('Skywarn', '1,\\y'),
                   ('AVAIL', '1,\\Z'),
                   ('OVERLAYED Shelter', '1,\\z'))
    _SETTINGS = {
        "DS": {'type': 'list',
               'values': ("Data Band", "Both Bands", "Ignore DCD")},
        "DSPA": {'type': 'list',
                 'values': ("Entire Display", "One Line")},
        "ICO": {'type': 'map',
                'map': (
                    KenwoodD7Family.
                        _COMMON_SETTINGS["ICO"]["map"] +  # type: ignore
                        _APRS_EXTRA)}}

    _SETTINGS_MENUS = (
        ('Main',
            (("ASC 0", "Automatic Simplex Check Band A"),
             ("ASC 1", "Automatic Simplex Check Band B"),
             ("BAL", "Balance"),
             ("BC", "Band"),
             ("BEL 0", "Tone Alert Band A"),
             ("BEL 1", "Tone Alert Band B"),
             ("CH", "Channel Mode Display"),
             ("DL", "Dual"),
             ("LK", "Lock"),
             ("LMP", "Lamp"),
             # MNF requires that the *current* VFO be in MR mode
             # Also, it has a direct key
             # ("MNF", "Memory Display Mode"),
             ("PV", "Programmable VFOs"),
             ("SQ 0", "Band A Squelch"),
             ("SQ 1", "Band B Squelch"),
             # We likely don't want to enable this from Chirp...
             # ("TNC", "Packet Mode"))),
             )),
        ('Radio',
            (('Display',
                (("MES", "Power-ON Message"),
                 ("CNT", "Contrast"))),
             ('Save',
                (("SV", "Battery Saver Interval"),
                 ("APO", "Automatic Power Off (APO)"))),
             ('DTMF',
                (("dtmfmem 00", "Number Store #0"),
                 ("dtmfmem 01", "Number Store #1"),
                 ("dtmfmem 02", "Number Store #2"),
                 ("dtmfmem 03", "Number Store #3"),
                 ("dtmfmem 04", "Number Store #4"),
                 ("dtmfmem 05", "Number Store #5"),
                 ("dtmfmem 06", "Number Store #6"),
                 ("dtmfmem 07", "Number Store #7"),
                 ("dtmfmem 08", "Number Store #8"),
                 ("dtmfmem 09", "Number Store #9"),
                 ("TSP", "TX Speed"),
                 ("TXH", "TX Hold"),
                 ("PT", "Pause"))),
             ('TNC',
                (("DTB", "Data band select"),
                 ("DS", "DCD sense"))),
             ('AUX',
                (("ARO", "Automatic Repeater Offset"),
                 ("SCR", "Scan Resume"),
                 ("BEP", "Key Beep"),
                 ("ELK", "Tuning Enable"),
                 ("TXS", "TX Inhibit"),
                 ("AIP", "Advanced Intercept Point"),
                 ("CKEY", "Call Key function"),
                 ("TH", "TX Hold, 1750 Hz"))))),
        ('APRS',
            (("MYC", "My call sign"),
             ("GU", "GPS receiver"),
             ("WAY", "Waypoint"),
             ("MP 1", "My position #1"),
             ("MP 2", "My position #2"),
             ("MP 3", "My position #3"),
             ("PAMB", "Position Ambiguity"),
             ("POSC", "Position comment"),
             ("ARL", "Reception restriction distance"),
             ("ICO", "Station icon"),
             ("STAT 1", "Status text #1"),
             ("STAT 2", "Status text #2"),
             ("STAT 3", "Status text #3"),
             ("STXR", "Status text transmit rate"),
             ("PP", "Packet path"),
             ("DTX", "Packet transmit method"),
             ("TXI", "Packet transmit interval"),
             ("UPR", "Group code"),
             ("BEPT", "Beep"),
             ("DSPA", "Display area"),
             ("KILO", "Unit for distance"),
             ("TEMP", "Unit for temperature"),
             ("AMR", "Auto Answer Reply"),
             ("ARLM", "Reply message"),
             ("AMGG", "Message group"),
             ("DTBA", "Data band"),
             ("PKSA", "Packet transfer rate"),
             ("TZ", "Time Zone"),
             ("TXD", "Packet transmit delay"))),
        ('SSTV',
            (("SMY", "My call sign"),
             ("MAC", "Color for call sign"),
             ("SMSG", "Message"),
             ("SMC", "Color for message"),
             ("RSV", "RSV report"),
             ("RSC", "Color for RSV report"),
             ("VCS", "VC-H1 Control"))),
        ('SkyCommand',
            (("SCC", "Commander call sign"),
             ("SCT", "Transporter call sign"),
             ("SKTN", "Tone frequency select"))))


@directory.register
class TMD700Radio(KenwoodD7Family):
    """Kenwood TH-D700"""
    MODEL = "TM-D700"
    HARDWARE_FLOW = True

    # Details taken from https://www.qsl.net/k7jar/pages/D700Cmds.html
    # And https://www.qsl.net/k/kb9rku/aprs/ (continued on next line)
    # PC%20Command%20Specifications%20for%20TM-D700_Rev1.pdf
    _BAUDS = [57600, 38400, 19200, 9600]
    _LOWER = 1
    _UPPER = 200
    _BANDS = [(118000000, 524000000), (800000000, 1300000000)]

    _BOOL = {'type': 'bool'}
    _PKEY_FUNCTION = {'type': 'list',
                      'values': ('Power', 'A/B', 'Monitor', 'Enter', 'Voice',
                                 '1750', 'PM', 'Menu', 'VFO', 'MR', 'CALL',
                                 'MHz', 'Tone', 'Rev', 'Low', 'Mute', 'Ctrl',
                                 'PM.In', 'A.B.C', 'M>V', 'M.In', 'C.In',
                                 'Lock', 'T.Sel', 'Shift', 'Step', 'Visual',
                                 'Dim', 'Sub-Band Select', 'DX', 'TNC', 'List',
                                 'P.Mon', 'BCon', 'Msg', 'Pos')}
    _VOLUME = {'type': 'list',
               'values': ('Off', '1', '2', '3', '4', '5', '6', 'Maximum')}
    _SETTINGS = {
        "ABLG": {'type': 'string', 'max_len': 29},
        "AD": _BOOL,
        "BEP": {'type': 'list',
                'values': ("Off", "Key")},
        "BVOL": _VOLUME,
        "CP": {'type': 'list',
               'values': ('9600bps', '19200bps', '38400bps', '57600bps')},
        "DATP": {'type': 'list',
                 'values': ('1200bps', '9600bps')},
        "DIG": _BOOL,
        "DTM": _BOOL,
        "FUNC": {'type': 'map',
                 'map': (("Mode 1", "1"), ("Mode 2", "2"), ("Mode 3", "3"))},
        "ICO": {'type': 'map',
                'map': (KenwoodD7Family.
                        _COMMON_SETTINGS["ICO"]["map"] +  # type: ignore
                        (('Digipeater', '0,F'),) +
                        THD7GRadio._APRS_EXTRA)},
        "MCL 0": _BOOL,
        "MCL 1": _BOOL,
        "MCNT": _BOOL,
        "MD": {'type': 'list', 'values': ('FM', 'AM')},
        "NP": _BOOL,
        "OS": {'type': 'integer', 'min': -99999999, 'max': 999999999,
               'digits': 9},
        "PF 1": _PKEY_FUNCTION,
        "PF 2": _PKEY_FUNCTION,
        "PF 3": _PKEY_FUNCTION,
        "PF 4": _PKEY_FUNCTION,
        "PMM": _BOOL,
        "RCA": _BOOL,
        "RC": _BOOL,
        "RCC": {'type': 'integer', 'min': 0, 'max': 999},
        "REP": {'type': 'list',
                'values': ('Off', 'Locked-Band', 'Cross-Band')},
        "REPL": _BOOL,
        "SHT": {'type': 'list',
                'values': ('Off', '125ms', '250ms', '500ms')},
        "SSEL": {'type': 'map',
                 'map': (("MODE1", "1"), ("MODE2", "2"))},
        "SSQ 0": _BOOL,
        "SSQ 1": _BOOL,
        "TOT": {'type': 'list',
                'values': ('3 minutes', '5 minutes', '10 minutes')},
        "UDIG": {'type': 'string', 'max_len': 39, 'charset': '0123456789'
                 'ABCDEFGHIJKLMNOPQRSTUVWXYZ,-'},
        "VOM": {'type': 'list',
                'values': ('Off', 'English', 'APRS only', 'Japanese')},
        "VS3": _VOLUME,
        "VSM": {'type': 'map',
                'map': (('31 Channels', '1'), ('61 Channels', '2'),
                        ('91 Channels', '3'), ('181 Channels', '4'))}}

    _PROGRAMMABLE_VFOS = (
        ("Band A 118 MHz Sub-Band", 1, 118, 135),
        ("Band A VHF Sub-Band", 2, 136, 199),
        ("Band B VHF Sub-Band", 3, 136, 174),
        ("Band A 220 MHz Sub-Band", 4, 200, 299),
        ("Band B 300 MHz Sub-Band", 5, 300, 399),
        ("Band A 300 MHz Sub-Band", 6, 300, 399),
        ("Band B UHF Sub-Band", 7, 400, 523),
        ("Band A UHF Sub-Band", 8, 400, 469),
        ("Band B 1.2 GHz Sub-Band", 9, 800, 1299))

    _SETTINGS_MENUS = (
        ('Main',
            (("ASC 0", "Automatic Simplex Check Band A"),
             ("ASC 1", "Automatic Simplex Check Band B"),
             ("DL", "Dual"),
             ("LK", "Lock"),
             # MNF requires that the *current* VFO be in MR mode
             # ("MNF", "Memory Display Mode"),
             # We likely don't want to enable this from Chirp...
             # ("TNC", "Packet Mode"))),
             )),
        ('Radio',
            (('Display',
                (("MES", "Power-ON Message"),
                 ("CNT", "Contrast"),
                 ("NP", "Reverse mode"),
                 ("AD", "Auto Dimmer Change"),
                 ("FUNC", "Multi-function button"))),
             ('Audio',
                (("BVOL", "Beep volume"),
                 ("BEP", "Key Beep"),
                 ("SSEL", "Speaker configuration"),
                 ("VOM", "Voice Synthesizer"),
                 ("VS3", "Voice volume"))),
             ('TX/RX',
                (("PV", "Programmable VFO"),
                 ("SSQ 0", "Band A S-meter Squelch"),
                 ("SSQ 1", "Band B S-meter Squelch"),
                 ("SHT", "Squelch hang time"),
                 ("MD", "FM / AM mode"),
                 ("AIP", "Advanced Intercept Point"),
                 ("XXX", "TX/ RX deviation"))),
             ('Memory',
                (("PMM", "Auto PM Channel Store"),
                 ("CH", "Channel Display"),
                 ("MCL 0", "Band A Memory Channel Lockout"),
                 ("MCL 1", "Band B Memory Channel Lockout"),
                 ("XXX", "Memory channel name"))),
             ('DTMF',
                (("dtmfmem 00", "Number Store #0"),
                 ("dtmfmem 01", "Number Store #1"),
                 ("dtmfmem 02", "Number Store #2"),
                 ("dtmfmem 03", "Number Store #3"),
                 ("dtmfmem 04", "Number Store #4"),
                 ("dtmfmem 05", "Number Store #5"),
                 ("dtmfmem 06", "Number Store #6"),
                 ("dtmfmem 07", "Number Store #7"),
                 ("dtmfmem 08", "Number Store #8"),
                 ("dtmfmem 09", "Number Store #9"),
                 ("TSP", "TX Speed"),
                 ("PT", "Pause"))),
             ('TNC',
                (("DTB", "Data band"),
                 ("DS", "DCD sense"),
                 ("XXX", "Time"),
                 ("XXX", "Date"),
                 ("TZ", "Time zone"))),
             ('Repeater',
                (("OS", "Offset frequency"),
                 ("ARO", "Automatic Repeater Offset"),
                 ("CKEY", "Call Button Function"),
                 ("TH", "TX Hold"),
                 ("REPH", "Repeater Hold"),
                 ("REP", "Repeater function"))),
             ('Mic',
                (("PF 1", "Mic PF Key"),
                 ("PF 2", "Mic MR Key"),
                 ("PF 3", "Mic VFO Key"),
                 ("PF 4", "Mic CALL Key"),
                 ("MCNT", "Microphone Control"),
                 ("DTM", "DTMF Monitor"))),
             ('Aux',
                (("SCR", "Scan Resume"),
                 ("VSM", "Number of Channels for Visual Scan"),
                 ("APO", "Automatic Power Off (APO)"),
                 ("TOT", "Time-Out Timer (TOT)"),
                 ("CP", "COM port"),
                 ("DATP", "Data port"))),
             ('Remote Control',
                (("RCC", "Secret code"),
                 ("RCA", "Acknowledgement"),
                 ("RC", "Remote Control"))))),
        ('SSTV',
            (("SMY", "My call sign"),
             ("MAC", "Color for call sign"),
             ("SMSG", "Message"),
             ("SMC", "Color for message"),
             ("RSV", "RSV report"),
             ("RSC", "Color for RSV report"),
             ("VCS", "VC-H1 Control"))),
        ('APRS',
            (("MYC", "My call sign"),
             ("GU", "GPS receiver"),
             ("WAY", "Waypoint"),
             ("MP 1", "My position #1"),
             ("MP 2", "My position #2"),
             ("MP 3", "My position #3"),
             ("PAMB", "Position Ambiguity"),
             ("POSC", "Position comment"),
             ("ARL", "Reception restriction distance"),
             ("ICO", "Station icon"),
             ("STAT 1", "Status text #1"),
             ("STAT 2", "Status text #2"),
             ("STAT 3", "Status text #3"),
             ("STXR", "Status text transmit rate"),
             ("PP", "Packet path"),
             ("DTX", "Packet transmit method"),
             ("TXI", "Packet transmit interval"),
             ("UPR", "Group code"),
             ("BEPT", "Beep"),
             ("KILO", "Unit for distance"),
             ("TEMP", "Unit for temperature"),
             ("DTBA", "Data band"),
             ("PKSA", "Packet transfer rate"),
             ("DIG", "Digipeater"),
             ("UDIG", "Digipeating path"),
             ("AMR", "Auto Answer Reply"),
             ("ARLM", "Reply message"),
             ("ABLG", "Bulletin group"))),
        ('SkyCommand',
            (("SCC", "Commander call sign"),
             ("SCT", "Transporter call sign"),
             ("SKTN", "Tone frequency select"))))

    # Apparently, when sent "CH 1", the radio will return "SM 0,00"
    # which is the current value of the Band A S-Meter.  We'll ignore that
    # and read the next line (which is hopefully "CH 1")
    def _keep_reading(self, result):
        if result[0:3] == 'SM ':
            return True
        return False

    # It also seems that "CH 1" can return "N" when the current memory
    # is invalid (but still enters CH mode)
    def _kenwood_set_success(self, cmd, modcmd, value, response):
        if cmd == 'CH' and value == "1":
            if response == 'N':
                return True
        return super()._kenwood_set_success(cmd, modcmd, value, response)

    def _mem_spec_fixup(self, spec, memid, mem):
        spec[6] = "%i" % (mem.tmode == "DTCS")
        spec[8] = "%03i0" % (chirp_common.DTCS_CODES.index(mem.dtcs) + 1)

    def _parse_mem_fixup(self, mem, spec):
        if spec[11] and spec[11].isdigit():
            mem.dtcs = chirp_common.DTCS_CODES[int(spec[11][:-1]) - 1]
        else:
            LOG.warn("Unknown or invalid DCS: %s" % spec[11])

    def get_features(self, *args, **kwargs):
        rf = super().get_features(*args, **kwargs)
        rf.has_dtcs = True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        return rf
