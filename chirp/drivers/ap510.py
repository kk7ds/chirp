# Copyright 2014 Tom Hayward <tom@tomh.us>
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

import struct
from time import sleep
import logging

from chirp import chirp_common, directory, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    InvalidValueError, RadioSettings

LOG = logging.getLogger(__name__)


def chunks(s, t):
    """ Yield chunks of s in sizes defined in t."""
    i = 0
    for n in t:
        yield s[i:i+n]
        i += n


def encode_base100(v):
    return (v / 100 << 8) + (v % 100)


def decode_base100(u16):
    return 100 * (u16 >> 8 & 0xff) + (u16 & 0xff)


def drain(pipe):
    """Chew up any data waiting on @pipe"""
    for x in xrange(3):
        buf = pipe.read(4096)
        if not buf:
            return
    raise errors.RadioError('Your pipes are clogged.')


def enter_setup(pipe):
    """Put AP510 in configuration mode."""
    for x in xrange(30):
        if x % 2:
            pipe.write("@SETUP")
        else:
            pipe.write("\r\nSETUP\r\n")
        s = pipe.read(64)
        if s and "\r\nSETUP" in s:
            return True
        elif s and "SETUP" in s:
            return False
    raise errors.RadioError('Radio did not respond.')


def download(radio):
    status = chirp_common.Status()
    drain(radio.pipe)

    status.msg = " Power on AP510 now, waiting "
    radio.status_fn(status)
    new = enter_setup(radio.pipe)

    status.cur = 1
    status.max = 5
    status.msg = "Downloading"
    radio.status_fn(status)
    if new:
        radio.pipe.write("\r\nDISP\r\n")
    else:
        radio.pipe.write("@DISP")
    buf = ""

    for status.cur in xrange(status.cur, status.max):
        buf += radio.pipe.read(1024)
        if buf.endswith("\r\n"):
            status.cur = status.max
            radio.status_fn(status)
            break
        radio.status_fn(status)
    else:
        raise errors.RadioError("Incomplete data received.")

    LOG.debug("%04i P<R: %s" %
              (len(buf), util.hexprint(buf).replace("\n", "\n          ")))
    return buf


def upload(radio):
    status = chirp_common.Status()
    drain(radio.pipe)

    status.msg = " Power on AP510 now, waiting "
    radio.status_fn(status)
    new = enter_setup(radio.pipe)

    status.msg = "Uploading"
    status.cur = 1
    status.max = len(radio._mmap._memobj.items())
    for k, v in radio._mmap._memobj.items():
        if k == '00':
            continue
        if new:
            radio.pipe.write("%s=%s\r\n" % (k, v))
            sleep(0.05)
        elif k in ('09', '10', '15'):
            radio.pipe.write("@" + k + v + "\x00\r\n")
        else:
            radio.pipe.write("@" + k + v)
        # Older firmware acks every command except 15 with OK.
        if not new and radio.pipe.read(2) != "OK" and k != '15':
            raise errors.RadioError("Radio did not acknowledge upload: %s" % k)
        status.cur += 1
        radio.status_fn(status)
    if new and radio.pipe.read(6) != "\r\n\r\nOK":
        raise errors.RadioError("Radio did not acknowledge upload.")


def strbool(s):
    return s == '1'


def boolstr(b):
    return b and '1' or '0'


class AP510Memory(object):
    """Parses and generates AP510 key/value format

    The AP510 sends it's configuration as a set of keys and values. There
    is one key/value pair per line. Line separators are \r\n. Keys are
    deliminated from values with the = symbol.

    Sample:
    00=AVRT5 20140829
    01=KD7LXL7
    02=3
    03=1

    This base class is compatible with firmware 20141008 (rx free).
    """

    ATTR_MAP = {
        'version':  '00',
        'callsign': '01',
        'pttdelay': '02',
        'output':   '03',
        'mice':     '04',
        'path':     '05',
        'symbol':   '06',
        'beacon':   '07',
        'rate':     '08',
        'status':   '09',
        'comment':  '10',
        'digipeat': '12',
        'autooff':  '13',
        'chinamapfix': '14',
        'virtualgps': '15',
        'freq':     '16',
        'beep':     '17',
        'smartbeacon': '18',
        'highaltitude': '19',
        'busywait': '20',
    }

    def __init__(self, data):
        self._data = data
        self.process_data()

    def get_packed(self):
        self._data = "\r\n"
        for v in sorted(self.ATTR_MAP.values()):
            self._data += "%s=%s\r\n" % (v, self._memobj[v])
        return self._data

    def process_data(self):
        data = []
        for line in self._data.split('\r\n'):
            if '=' in line:
                data.append(line.split('=', 1))
        self._memobj = dict(data)
        LOG.debug(self.version)

    def __getattr__(self, name):
        if hasattr(self, 'get_%s' % name):
            return getattr(self, 'get_%s' % name)()
        try:
            return self._memobj[self.ATTR_MAP[name]]
        except KeyError as e:
            raise NotImplementedError(e)

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super(AP510Memory, self).__setattr__(name, value)
            return
        if hasattr(self, 'set_%s' % name):
            return getattr(self, 'set_%s' % name)(value)
        try:
            self._memobj[self.ATTR_MAP[name]] = str(value)
        except KeyError as e:
            raise NotImplementedError(e)

    def get_smartbeacon(self):
        return dict(zip((
            'lowspeed',
            'slowrate',
            'highspeed',
            'fastrate',
            'turnslope',
            'turnangle',
            'turntime',
        ), map(
            decode_base100,
            struct.unpack(">7H", self._memobj[self.ATTR_MAP['smartbeacon']]))
        ))

    def set_smartbeacon(self, d):
        self._memobj[self.ATTR_MAP['smartbeacon']] = \
            struct.pack(">7H",
                        encode_base100(d['lowspeed']),
                        encode_base100(d['slowrate']),
                        encode_base100(d['highspeed']),
                        encode_base100(d['fastrate']),
                        encode_base100(d['turnslope']),
                        encode_base100(d['turnangle']),
                        encode_base100(d['turntime']),
                        )


class AP510Memory20141215(AP510Memory):
    """Compatible with firmware version 20141215"""
    ATTR_MAP = dict(AP510Memory.ATTR_MAP.items() + {
        'tx_volume': '21',  # 1-6
        'rx_volume': '22',  # 1-9
        'tx_power': '23',  # 1: 1 watt,  0: 0.5 watt
        'tx_serial_ui_out': '24',
        'path1': '25',
        'path2': '26',
        'path3': '27',  # like "WIDE1 1" else "0"
        'multiple': '28',
        'auto_on': '29',
    }.items())

    def get_multiple(self):
        return dict(zip(
           (
            'mice_message',     # conveniently matches APRS spec Mic-E messages
            'voltage',          # voltage in comment
            'temperature',      # temperature in comment
            'tfx',              # not sure what the TF/X toggle does
            'squelch',          # squelch level 0-8 (0 = disabled)
            'blueled',          # 0: squelch LED on GPS lock
                                # 1: light LED on GPS lock
            'telemetry',        # 1: enable
            'telemetry_every',  # two-digit int
            'timeslot_enable',  # 1: enable   Is this implemented in firmware?
            'timeslot',         # int 00-59
            'dcd',              # 0: Blue LED displays squelch,
                                # 1: Blue LED displays software DCD
            'tf_card'           # 0: KML,  1: WPL
            ), map(int, chunks(self._memobj[self.ATTR_MAP['multiple']],
                               (1, 1, 1, 1, 1, 1, 1, 2, 1, 2, 1, 1)))
        ))

    def set_multiple(self, d):
        self._memobj[self.ATTR_MAP['multiple']] = "%(mice_message)1d" \
                                                  "%(voltage)1d" \
                                                  "%(temperature)1d" \
                                                  "%(tfx)1d" \
                                                  "%(squelch)1d" \
                                                  "%(blueled)1d" \
                                                  "%(telemetry)1d" \
                                                  "%(telemetry_every)02d" \
                                                  "%(timeslot_enable)1d" \
                                                  "%(timeslot)02d" \
                                                  "%(dcd)1d" \
                                                  "%(tf_card)1d" % d

    def get_smartbeacon(self):
        # raw:    18=0100300060010240028005
        # chunks: 18=010 0300 060 010 240 028 005
        return dict(zip((
            'lowspeed',
            'slowrate',
            'highspeed',
            'fastrate',
            'turnslope',
            'turnangle',
            'turntime',
        ), map(int, chunks(
            self._memobj[self.ATTR_MAP['smartbeacon']],
            (3, 4, 3, 3, 3, 3, 3)))
        ))

    def set_smartbeacon(self, d):
        self._memobj[self.ATTR_MAP['smartbeacon']] = "%(lowspeed)03d" \
                                                     "%(slowrate)04d" \
                                                     "%(highspeed)03d" \
                                                     "%(fastrate)03d" \
                                                     "%(turnslope)03d" \
                                                     "%(turnangle)03d" \
                                                     "%(turntime)03d" % d


PTT_DELAY = ['60 ms', '120 ms', '180 ms', '300 ms', '480 ms',
             '600 ms', '1000 ms']
OUTPUT = ['KISS', 'Waypoint out', 'UI out']
PATH = [
    '(None)',
    'WIDE1-1',
    'WIDE1-1,WIDE2-1',
    'WIDE1-1,WIDE2-2',
    'TEMP1-1',
    'TEMP1-1,WIDE 2-1',
    'WIDE2-1',
]
TABLE = "/\#&0>AW^_acnsuvz"
SYMBOL = "".join(map(chr, range(ord("!"), ord("~")+1)))
BEACON = ['manual', 'auto', 'auto + manual', 'smart', 'smart + manual']
ALIAS = ['WIDE1-N', 'WIDE2-N', 'WIDE1-N + WIDE2-N']
CHARSET = "".join(map(chr, range(0, 256)))
MICE_MESSAGE = ['Emergency', 'Priority', 'Special', 'Committed', 'Returning',
                'In Service', 'En Route', 'Off Duty']
TF_CARD = ['WPL', 'KML']
POWER_LEVELS = [chirp_common.PowerLevel("0.5 watt", watts=0.50),
                chirp_common.PowerLevel("1 watt", watts=1.00)]

RP_IMMUTABLE = ["number", "skip", "bank", "extd_number", "name", "rtone",
                "ctone", "dtcs", "tmode", "dtcs_polarity", "skip", "duplex",
                "offset", "mode", "tuning_step", "bank_index"]


class AP510Radio(chirp_common.CloneModeRadio):
    """Sainsonic AP510"""
    BAUD_RATE = 9600
    VENDOR = "Sainsonic"
    MODEL = "AP510"

    _model = "AVRT5"
    mem_upper_limit = 0

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.valid_modes = ["FM"]
        rf.valid_tmodes = [""]
        rf.valid_characters = ""
        rf.valid_duplexes = [""]
        rf.valid_name_length = 0
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = []
        rf.valid_tuning_steps = []
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_mode = False
        rf.has_name = False
        rf.has_offset = False
        rf.has_tuning_step = False
        rf.valid_bands = [(136000000, 174000000)]
        rf.memory_bounds = (0, 0)
        return rf

    def sync_in(self):
        try:
            data = download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

        # _mmap isn't a Chirp MemoryMap, but since AP510Memory implements
        # get_packed(), the standard Chirp save feature works.
        if data.startswith('\r\n00=%s 20141215' % self._model):
            self._mmap = AP510Memory20141215(data)
        else:
            self._mmap = AP510Memory(data)

    def process_mmap(self):
        self._mmap.process_data()

    def sync_out(self):
        try:
            upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def load_mmap(self, filename):
        """Load the radio's memory map from @filename"""
        mapfile = file(filename, "rb")
        data = mapfile.read()
        if data.startswith('\r\n00=%s 20141215' % self._model):
            self._mmap = AP510Memory20141215(data)
        else:
            self._mmap = AP510Memory(data)
        mapfile.close()

    def get_raw_memory(self, number):
        return self._mmap.get_packed()

    def get_memory(self, number):
        if number != 0:
            raise errors.InvalidMemoryLocation("AP510 has only one slot")

        mem = chirp_common.Memory()
        mem.number = 0
        mem.freq = float(self._mmap.freq) * 1000000
        mem.name = "TX/RX"
        mem.mode = "FM"
        mem.offset = 0.0
        try:
            mem.power = POWER_LEVELS[int(self._mmap.tx_power)]
        except NotImplementedError:
            mem.power = POWER_LEVELS[1]
        mem.immutable = RP_IMMUTABLE

        return mem

    def set_memory(self, mem):
        if mem.number != 0:
            raise errors.InvalidMemoryLocation("AP510 has only one slot")

        self._mmap.freq = "%8.4f" % (mem.freq / 1000000.0)
        if mem.power:
            try:
                self._mmap.tx_power = str(POWER_LEVELS.index(mem.power))
            except NotImplementedError:
                pass

    def get_settings(self):
        china = RadioSettingGroup("china", "China Map Fix")
        smartbeacon = RadioSettingGroup("smartbeacon", "Smartbeacon")

        aprs = RadioSettingGroup("aprs", "APRS", china, smartbeacon)
        digipeat = RadioSettingGroup("digipeat", "Digipeat")
        system = RadioSettingGroup("system", "System")
        settings = RadioSettings(aprs, digipeat, system)

        aprs.append(RadioSetting("callsign", "Callsign",
                    RadioSettingValueString(0, 6, self._mmap.callsign[:6])))
        aprs.append(RadioSetting("ssid", "SSID", RadioSettingValueInteger(
                    0, 15, ord(self._mmap.callsign[6]) - 0x30)))
        pttdelay = PTT_DELAY[int(self._mmap.pttdelay) - 1]
        aprs.append(RadioSetting("pttdelay", "PTT Delay",
                    RadioSettingValueList(PTT_DELAY, pttdelay)))
        output = OUTPUT[int(self._mmap.output) - 1]
        aprs.append(RadioSetting("output", "Output",
                    RadioSettingValueList(OUTPUT, output)))
        aprs.append(RadioSetting("mice", "Mic-E",
                    RadioSettingValueBoolean(strbool(self._mmap.mice))))
        try:
            mice_msg = MICE_MESSAGE[int(self._mmap.multiple['mice_message'])]
            aprs.append(RadioSetting("mice_message", "Mic-E Message",
                        RadioSettingValueList(MICE_MESSAGE, mice_msg)))
        except NotImplementedError:
            pass
        try:
            aprs.append(RadioSetting("path1", "Path 1",
                        RadioSettingValueString(0, 6, self._mmap.path1[:6],
                                                autopad=True,
                                                charset=CHARSET)))
            ssid1 = ord(self._mmap.path1[6]) - 0x30
            aprs.append(RadioSetting("ssid1", "SSID 1",
                        RadioSettingValueInteger(0, 7, ssid1)))
            aprs.append(RadioSetting("path2", "Path 2",
                        RadioSettingValueString(0, 6, self._mmap.path2[:6],
                                                autopad=True,
                                                charset=CHARSET)))
            ssid2 = ord(self._mmap.path2[6]) - 0x30
            aprs.append(RadioSetting("ssid2", "SSID 2",
                        RadioSettingValueInteger(0, 7, ssid2)))
            aprs.append(RadioSetting("path3", "Path 3",
                        RadioSettingValueString(0, 6, self._mmap.path3[:6],
                                                autopad=True,
                                                charset=CHARSET)))
            ssid3 = ord(self._mmap.path3[6]) - 0x30
            aprs.append(RadioSetting("ssid3", "SSID 3",
                        RadioSettingValueInteger(0, 7, ssid3)))
        except NotImplementedError:
            aprs.append(RadioSetting("path", "Path",
                        RadioSettingValueList(PATH,
                                              PATH[int(self._mmap.path)])))
        aprs.append(RadioSetting("table", "Table or Overlay",
                    RadioSettingValueList(TABLE, self._mmap.symbol[1])))
        aprs.append(RadioSetting("symbol", "Symbol",
                    RadioSettingValueList(SYMBOL, self._mmap.symbol[0])))
        aprs.append(RadioSetting("beacon", "Beacon Mode",
                    RadioSettingValueList(BEACON,
                                          BEACON[int(self._mmap.beacon) - 1])))
        aprs.append(RadioSetting("rate", "Beacon Rate (seconds)",
                    RadioSettingValueInteger(10, 9999, self._mmap.rate)))
        aprs.append(RadioSetting("comment", "Comment",
                    RadioSettingValueString(0, 34, self._mmap.comment,
                                            autopad=False, charset=CHARSET)))
        try:
            voltage = self._mmap.multiple['voltage']
            aprs.append(RadioSetting("voltage", "Voltage in comment",
                        RadioSettingValueBoolean(voltage)))
            temperature = self._mmap.multiple['temperature']
            aprs.append(RadioSetting("temperature", "Temperature in comment",
                        RadioSettingValueBoolean(temperature)))
        except NotImplementedError:
            pass
        aprs.append(RadioSetting("status", "Status", RadioSettingValueString(
            0, 34, self._mmap.status, autopad=False, charset=CHARSET)))
        try:
            telemetry = self._mmap.multiple['telemetry']
            aprs.append(RadioSetting("telemetry", "Telemetry",
                        RadioSettingValueBoolean(telemetry)))
            telemetry_every = self._mmap.multiple['telemetry_every']
            aprs.append(RadioSetting("telemetry_every", "Telemetry every",
                        RadioSettingValueInteger(1, 99, telemetry_every)))
            timeslot_enable = self._mmap.multiple['telemetry']
            aprs.append(RadioSetting("timeslot_enable", "Timeslot",
                        RadioSettingValueBoolean(timeslot_enable)))
            timeslot = self._mmap.multiple['timeslot']
            aprs.append(RadioSetting("timeslot", "Timeslot (second of minute)",
                        RadioSettingValueInteger(0, 59, timeslot)))
        except NotImplementedError:
            pass

        fields = [
            ("chinamapfix", "China map fix",
                RadioSettingValueBoolean(strbool(self._mmap.chinamapfix[0]))),
            ("chinalat", "Lat",
                RadioSettingValueInteger(
                    -45, 45, ord(self._mmap.chinamapfix[2]) - 80)),
            ("chinalon", "Lon",
                RadioSettingValueInteger(
                    -45, 45, ord(self._mmap.chinamapfix[1]) - 80)),
        ]
        for field in fields:
            china.append(RadioSetting(*field))

        try:
            # Sometimes when digipeat is disabled, alias is 0xFF
            alias = ALIAS[int(self._mmap.digipeat[1]) - 1]
        except ValueError:
            alias = ALIAS[0]
        fields = [
            ("digipeat", "Digipeat",
                RadioSettingValueBoolean(strbool(self._mmap.digipeat[0]))),
            ("alias", "Digipeat Alias",
                RadioSettingValueList(
                    ALIAS, alias)),
            ("virtualgps", "Static Position",
                RadioSettingValueBoolean(strbool(self._mmap.virtualgps[0]))),
            ("btext", "Static Position BTEXT", RadioSettingValueString(
                0, 27, self._mmap.virtualgps[1:], autopad=False,
                charset=CHARSET)),
        ]
        for field in fields:
            digipeat.append(RadioSetting(*field))

        sb = self._mmap.smartbeacon
        fields = [
            ("lowspeed", "Low Speed"),
            ("highspeed", "High Speed"),
            ("slowrate", "Slow Rate (seconds)"),
            ("fastrate", "Fast Rate (seconds)"),
            ("turnslope", "Turn Slope"),
            ("turnangle", "Turn Angle"),
            ("turntime", "Turn Time (seconds)"),
        ]
        for field in fields:
            smartbeacon.append(RadioSetting(
                field[0], field[1],
                RadioSettingValueInteger(0, 9999, sb[field[0]])
            ))

        system.append(RadioSetting("version", "Version (read-only)",
                      RadioSettingValueString(0, 14, self._mmap.version)))
        system.append(RadioSetting("autooff", "Auto off (after 90 minutes)",
                      RadioSettingValueBoolean(strbool(self._mmap.autooff))))
        system.append(RadioSetting("beep", "Beep on transmit",
                      RadioSettingValueBoolean(strbool(self._mmap.beep))))
        system.append(RadioSetting("highaltitude", "High Altitude",
                      RadioSettingValueBoolean(
                          strbool(self._mmap.highaltitude))))
        system.append(RadioSetting("busywait",
                                   "Wait for clear channel before transmit",
                                   RadioSettingValueBoolean(
                                       strbool(self._mmap.busywait))))
        try:
            system.append(RadioSetting("tx_volume", "Transmit volume",
                          RadioSettingValueList(
                              map(str, range(1, 7)), self._mmap.tx_volume)))
            system.append(RadioSetting("rx_volume", "Receive volume",
                          RadioSettingValueList(
                              map(str, range(1, 10)), self._mmap.rx_volume)))
            system.append(RadioSetting("squelch", "Squelch",
                          RadioSettingValueList(
                              map(str, range(0, 9)),
                              str(self._mmap.multiple['squelch']))))
            system.append(RadioSetting("tx_serial_ui_out", "Tx serial UI out",
                          RadioSettingValueBoolean(
                              strbool(self._mmap.tx_serial_ui_out))))
            system.append(RadioSetting("auto_on", "Auto-on with 5V input",
                          RadioSettingValueBoolean(
                              strbool(self._mmap.auto_on[0]))))
            system.append(RadioSetting(
                              "auto_on_delay",
                              "Auto-off delay after 5V lost (seconds)",
                              RadioSettingValueInteger(
                                  0, 9999, int(self._mmap.auto_on[1:]))
            ))
            system.append(RadioSetting("tfx", "TF/X",
                          RadioSettingValueBoolean(
                              self._mmap.multiple['tfx'])))
            system.append(RadioSetting("blueled", "Light blue LED on GPS lock",
                          RadioSettingValueBoolean(
                              self._mmap.multiple['blueled'])))
            system.append(RadioSetting("dcd", "Blue LED shows software DCD",
                          RadioSettingValueBoolean(
                              self._mmap.multiple['dcd'])))
            system.append(RadioSetting("tf_card", "TF card format",
                          RadioSettingValueList(
                              TF_CARD,
                              TF_CARD[int(self._mmap.multiple['tf_card'])])))
        except NotImplementedError:
            pass

        return settings

    def set_settings(self, settings):
        for setting in settings:
            if not isinstance(setting, RadioSetting):
                self.set_settings(setting)
                continue
            if not setting.changed():
                continue
            try:
                name = setting.get_name()
                if name == "callsign":
                    self.set_callsign(callsign=setting.value)
                elif name == "ssid":
                    self.set_callsign(ssid=int(setting.value))
                elif name == "pttdelay":
                    self._mmap.pttdelay = PTT_DELAY.index(
                        str(setting.value)) + 1
                elif name == "output":
                    self._mmap.output = OUTPUT.index(str(setting.value)) + 1
                elif name in ('mice', 'autooff', 'beep', 'highaltitude',
                              'busywait', 'tx_serial_ui_out'):
                    setattr(self._mmap, name, boolstr(setting.value))
                elif name == "mice_message":
                    multiple = self._mmap.multiple
                    multiple['mice_message'] = MICE_MESSAGE.index(
                        str(setting.value))
                    self._mmap.multiple = multiple
                elif name == "path":
                    self._mmap.path = PATH.index(str(setting.value))
                elif name == "path1":
                    self._mmap.path1 = "%s%s" % (
                        setting.value, self._mmap.path1[6])
                elif name == "ssid1":
                    self._mmap.path1 = "%s%s" % (
                        self._mmap.path1[:6], setting.value)
                elif name == "path2":
                    self._mmap.path2 = "%s%s" % (
                        setting.value, self._mmap.path2[6])
                elif name == "ssid2":
                    self._mmap.path2 = "%s%s" % (
                        self._mmap.path2[:6], setting.value)
                elif name == "path3":
                    self._mmap.path3 = "%s%s" % (
                        setting.value, self._mmap.path3[6])
                elif name == "ssid3":
                    self._mmap.path3 = "%s%s" % (
                        self._mmap.path3[:6], setting.value)
                elif name == "table":
                    self.set_symbol(table=setting.value)
                elif name == "symbol":
                    self.set_symbol(symbol=setting.value)
                elif name == "beacon":
                    self._mmap.beacon = BEACON.index(str(setting.value)) + 1
                elif name == "rate":
                    self._mmap.rate = "%04d" % setting.value
                elif name == "comment":
                    self._mmap.comment = str(setting.value)
                elif name == "voltage":
                    multiple = self._mmap.multiple
                    multiple['voltage'] = int(setting.value)
                    self._mmap.multiple = multiple
                elif name == "temperature":
                    multiple = self._mmap.multiple
                    multiple['temperature'] = int(setting.value)
                    self._mmap.multiple = multiple
                elif name == "status":
                    self._mmap.status = str(setting.value)
                elif name in ("telemetry", "telemetry_every",
                              "timeslot_enable", "timeslot",
                              "tfx", "blueled", "dcd"):
                    multiple = self._mmap.multiple
                    multiple[name] = int(setting.value)
                    self._mmap.multiple = multiple
                elif name == "chinamapfix":
                    self.set_chinamapfix(enable=setting.value)
                elif name == "chinalat":
                    self.set_chinamapfix(lat=int(setting.value))
                elif name == "chinalon":
                    self.set_chinamapfix(lon=int(setting.value))
                elif name == "digipeat":
                    self.set_digipeat(enable=setting.value)
                elif name == "alias":
                    self.set_digipeat(
                        alias=str(ALIAS.index(str(setting.value)) + 1))
                elif name == "virtualgps":
                    self.set_virtualgps(enable=setting.value)
                elif name == "btext":
                    self.set_virtualgps(btext=str(setting.value))
                elif name == "lowspeed":
                    self.set_smartbeacon(lowspeed=int(setting.value))
                elif name == "highspeed":
                    self.set_smartbeacon(highspeed=int(setting.value))
                elif name == "slowrate":
                    self.set_smartbeacon(slowrate=int(setting.value))
                elif name == "fastrate":
                    self.set_smartbeacon(fastrate=int(setting.value))
                elif name == "turnslope":
                    self.set_smartbeacon(turnslope=int(setting.value))
                elif name == "turnangle":
                    self.set_smartbeacon(turnangle=int(setting.value))
                elif name == "turntime":
                    self.set_smartbeacon(turntime=int(setting.value))
                elif name in ("tx_volume", "rx_volume", "squelch"):
                    setattr(self._mmap, name, "%1d" % setting.value)
                elif name == "auto_on":
                    self._mmap.auto_on = "%s%05d" % (
                        bool(setting.value) and '1' or 'i',
                        int(self._mmap.auto_on[1:]))
                elif name == "auto_on_delay":
                    self._mmap.auto_on = "%s%05d" % (
                        self._mmap.auto_on[0], setting.value)
                elif name == "tf_card":
                    multiple = self._mmap.multiple
                    multiple['tf_card'] = TF_CARD.index(str(setting.value))
                    self._mmap.multiple = multiple
            except:
                LOG.debug(setting.get_name())
                raise

    def set_callsign(self, callsign=None, ssid=None):
        if callsign is None:
            callsign = self._mmap.callsign[:6]
        if ssid is None:
            ssid = ord(self._mmap.callsign[6]) - 0x30
        self._mmap.callsign = str(callsign) + chr(ssid + 0x30)

    def set_symbol(self, table=None, symbol=None):
        if table is None:
            table = self._mmap.symbol[1]
        if symbol is None:
            symbol = self._mmap.symbol[0]
        self._mmap.symbol = str(symbol) + str(table)

    def set_chinamapfix(self, enable=None, lat=None, lon=None):
        if enable is None:
            enable = strbool(self._mmap.chinamapfix[0])
        if lat is None:
            lat = ord(self._mmap.chinamapfix[2]) - 80
        if lon is None:
            lon = ord(self._mmap.chinamapfix[1]) - 80
        self._mmapchinamapfix = boolstr(enable) + chr(lon + 80) + chr(lat + 80)

    def set_digipeat(self, enable=None, alias=None):
        if enable is None:
            enable = strbool(self._mmap.digipeat[0])
        if alias is None:
            alias = self._mmap.digipeat[1]
        self._mmap.digipeat = boolstr(enable) + alias

    def set_virtualgps(self, enable=None, btext=None):
        if enable is None:
            enable = strbool(self._mmap.virtualgps[0])
        if btext is None:
            btext = self._mmap.virtualgps[1:]
        self._mmap.virtualgps = boolstr(enable) + btext

    def set_smartbeacon(self, **kwargs):
        sb = self._mmap.smartbeacon
        sb.update(kwargs)
        if sb['lowspeed'] > sb['highspeed']:
            raise InvalidValueError("Low speed must be less than high speed")
        if sb['slowrate'] < sb['fastrate']:
            raise InvalidValueError("Slow rate must be greater than fast rate")
        self._mmap.smartbeacon = sb

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata.startswith('\r\n00=' + cls._model)
