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
from chirp import chirp_common, directory, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettingValue, InvalidValueError


def encode_base100(v):
    return (v / 100 << 8) + (v % 100)


def decode_base100(u16):
    return 100 * (u16 >> 8 & 0xff) + (u16 & 0xff)


def encode_smartbeacon(d):
    return struct.pack(
        ">7H",
        encode_base100(d['lowspeed']),
        encode_base100(d['slowrate']),
        encode_base100(d['highspeed']),
        encode_base100(d['fastrate']),
        encode_base100(d['turnslope']),
        encode_base100(d['turnangle']),
        encode_base100(d['turntime']),
    )


def decode_smartbeacon(smartbeacon):
    return dict(zip((
        'lowspeed',
        'slowrate',
        'highspeed',
        'fastrate',
        'turnslope',
        'turnangle',
        'turntime',
    ), map(decode_base100, struct.unpack(">7H", smartbeacon))))


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
        pipe.write("@SETUP")
        s = pipe.read(64)
        if s and "SETUP" in s:
            return True
    raise errors.RadioError('Radio did not respond.')


def download(radio):
    status = chirp_common.Status()
    drain(radio.pipe)

    status.msg = " Power on AP510 now, waiting "
    radio.status_fn(status)
    enter_setup(radio.pipe)

    status.cur = 1
    status.max = 5
    status.msg = "Downloading"
    radio.status_fn(status)
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

    print "%04i P<R: %s" % (
        len(buf), util.hexprint(buf).replace("\n", "\n          "))
    return buf


def upload(radio):
    status = chirp_common.Status()
    drain(radio.pipe)

    status.msg = " Power on AP510 now, waiting "
    radio.status_fn(status)
    enter_setup(radio.pipe)

    status.msg = "Uploading"
    status.cur = 1
    status.max = len(radio._mmap._memobj.items())
    for k, v in radio._mmap._memobj.items():
        if k == '00':
            continue
        if k in ('09', '10', '15'):
            radio.pipe.write("@" + k + v + "\x00\r\n")
        else:
            radio.pipe.write("@" + k + v)
        # Piece of crap acks every command except 15 with OK.
        if radio.pipe.read(2) != "OK" and k != '15':
            raise errors.RadioError("Radio did not acknowledge upload: %s" % k)
        status.cur += 1
        radio.status_fn(status)


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
        print self.version

    def __getattr__(self, name):
        return self._memobj[self.ATTR_MAP[name]]

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super(AP510Memory, self).__setattr__(name, value)
            return
        self._memobj[self.ATTR_MAP[name]] = str(value)


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

RP_IMMUTABLE = ["number", "skip", "bank", "extd_number", "name", "rtone",
                "ctone", "dtcs", "tmode", "dtcs_polarity", "skip", "duplex",
                "offset", "mode", "tuning_step", "bank_index"]


@directory.register
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
        # _mmap isn't a Chirp MemoryMap, but since AP510Memory implements
        # get_packed(), the standard Chirp save feature works.
        try:
            self._mmap = AP510Memory(download(self))
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._mmap.process_data()

    def sync_out(self):
        try:
            upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def load_mmap(self, filename):
        """Load the radio's memory map from @filename"""
        mapfile = file(filename, "rb")
        self._mmap = AP510Memory(mapfile.read())
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
        mem.immutable = RP_IMMUTABLE

        return mem

    def set_memory(self, mem):
        if mem.number != 0:
            raise errors.InvalidMemoryLocation("AP510 has only one slot")

        self._mmap.freq = "%8.4f" % (mem.freq / 1000000.0)

    def get_settings(self):
        china = RadioSettingGroup("china", "China Map Fix")
        smartbeacon = RadioSettingGroup("smartbeacon", "Smartbeacon")

        aprs = RadioSettingGroup("aprs", "APRS", china, smartbeacon)
        digipeat = RadioSettingGroup("digipeat", "Digipeat")
        system = RadioSettingGroup("system", "System")
        settings = RadioSettingGroup("all", "Settings", aprs, digipeat, system)

        # The RadioSetting syntax is really verbose, iterate it.
        fields = [
            ("callsign", "Callsign",
                RadioSettingValueString(0, 6, self._mmap.callsign[:6])),
            ("ssid", "SSID", RadioSettingValueInteger(
                0, 15, ord(self._mmap.callsign[6]) - 0x30)),
            ("pttdelay", "PTT Delay",
                RadioSettingValueList(
                    PTT_DELAY, PTT_DELAY[int(self._mmap.pttdelay) - 1])),
            ("output", "Output",
                RadioSettingValueList(
                    OUTPUT, OUTPUT[int(self._mmap.output) - 1])),
            ("mice", "Mic-E",
                RadioSettingValueBoolean(strbool(self._mmap.mice))),
            ("path", "Path",
                RadioSettingValueList(PATH, PATH[int(self._mmap.path)])),
            ("table", "Table or Overlay",
                RadioSettingValueList(TABLE, self._mmap.symbol[1])),
            ("symbol", "Symbol",
                RadioSettingValueList(SYMBOL, self._mmap.symbol[0])),
            ("beacon", "Beacon Mode",
                RadioSettingValueList(
                    BEACON, BEACON[int(self._mmap.beacon) - 1])),
            ("rate", "Beacon Rate (seconds)",
                RadioSettingValueInteger(10, 9999, self._mmap.rate)),
            ("comment", "Comment", RadioSettingValueString(
                0, 34, self._mmap.comment, autopad=False, charset=CHARSET)),
            ("status", "Status", RadioSettingValueString(
                0, 34, self._mmap.status, autopad=False, charset=CHARSET)),
        ]
        for field in fields:
            aprs.append(RadioSetting(*field))

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

        sb = decode_smartbeacon(self._mmap.smartbeacon)
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

        fields = [
            ("version", "Version (read-only)",
                RadioSettingValueString(0, 14, self._mmap.version)),
            ("autooff", "Auto off (after 90 minutes)",
                RadioSettingValueBoolean(strbool(self._mmap.autooff))),
            ("beep", "Beep on transmit",
                RadioSettingValueBoolean(strbool(self._mmap.beep))),
            ("highaltitude", "High Altitude",
                RadioSettingValueBoolean(strbool(self._mmap.highaltitude))),
            ("busywait", "Wait for clear channel before transmit",
                RadioSettingValueBoolean(strbool(self._mmap.busywait))),
        ]
        for field in fields:
            system.append(RadioSetting(*field))

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
                              'busywait'):
                    setattr(self._mmap, name, boolstr(setting.value))
                elif name == "path":
                    self._mmap.path = PATH.index(str(setting.value))
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
                elif name == "status":
                    self._mmap.status = str(setting.value)
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
            except Exception, e:
                print setting.get_name()
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
        sb = decode_smartbeacon(self._mmap.smartbeacon)
        sb.update(kwargs)
        if sb['lowspeed'] > sb['highspeed']:
            raise InvalidValueError("Low speed must be less than high speed")
        if sb['slowrate'] < sb['fastrate']:
            raise InvalidValueError("Slow rate must be greater than fast rate")
        self._mmap.smartbeacon = encode_smartbeacon(sb)

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata.startswith('\r\n00=' + cls._model)
