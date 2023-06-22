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

from chirp.drivers.kenwood_live import KenwoodOldLiveRadio, MODES, STEPS, \
    DUPLEX, LOG, get_tmode
from chirp import chirp_common, directory, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueBoolean, \
    RadioSettingValueString, RadioSettingValueList, RadioSettings


@directory.register
class THD7Radio(KenwoodOldLiveRadio):
    """Kenwood TH-D7"""
    MODEL = "TH-D7"
    HARDWARE_FLOW = False

    _kenwood_split = True
    _upper = 199

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
        rf.memory_bounds = (0, self._upper)
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
        elif spec[11] == '':
            pass
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
                   ("MYC", aprs, "APRS Callsign", 9),
                   ("PP", aprs, "APRS Path", 32),
                   ("SCC", sky, "SkyCommand Callsign", 8),
                   ("SCT", sky, "SkyCommand To Callsign", 8),
                   # ("STAT", aprs, "APRS Status Text", 32),
                   ]
        for setting, group, name, length in strings:
            _cmd, value = self._kenwood_get(setting)
            rs = RadioSetting(setting, name,
                              RadioSettingValueString(0, length, value, False))
            group.append(rs)

        return top


@directory.register
class THD7GRadio(THD7Radio):
    """Kenwood TH-D7G"""
    MODEL = "TH-D7G"

    _SETTINGS_OPTIONS = {
        "BEPT": ["Off", "Mine", "All New", "All"],  # Added "All"
    }

    def _get_setting_options(self, setting):
        if setting in self._SETTINGS_OPTIONS:
            opts = self._SETTINGS_OPTIONS[setting]
        else:
            opts = super()._SETTINGS_OPTIONS[setting]
            if opts is None:
                opts = getattr(self, '_%s_OPTIONS' % setting)
        return opts

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
