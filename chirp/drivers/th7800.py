# Copyright 2014 Tom Hayward <tom@tomh.us>
# Copyright 2014 Jens Jensen <af5mi@yahoo.com>
# Copyright 2014 James Lee N1DDK <jml@jmlzone.com>
# Copyright 2016 Nathan Crapo <nathan_crapo@yahoo.com>  (TH-7800 only)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from chirp import bitwise, chirp_common, directory, errors, util, memmap
import struct
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueBoolean, \
    RadioSettingValueString, RadioSettings, \
    RadioSettingValueMap, zero_indexed_seq_map
from chirp.chirp_common import format_freq
import logging
from datetime import date

LOG = logging.getLogger(__name__)

TH7800_MEM_FORMAT = """
struct mem {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  lbcd ctcss[2];
  lbcd dtcs[2];
  u8 power:2,
     clk_sft:1,
     unknown0a:2,
     display:1,     // freq=0, name=1
     scan:2;
  u8 fmdev:2,       // wide=00, mid=01, narrow=10
     scramb:1,
     compand:1,
     emphasis:1,
     unknown1a:2,
     sqlmode:1;     // carrier, tone
  u8 rptmod:2,      // off, -, +
     reverse:1,
     talkaround:1,
     step:4;
  u8 dtcs_pol:2,
     unknown3:4,
     tmode:2;
  lbcd offset[4];
  u8 hsdtype:2,     // off, 2-tone, 5-tone, dtmf
     unknown5a:1,
     am:1,
     unknown5b:4;
  u8 unknown6[3];
  char name[6];
  u8 empty[2];
};

#seekto 0x%04X;
struct mem memory[800];

#seekto 0x%04X;
struct {
  struct mem lower;
  struct mem upper;
} scanlimits[5];

#seekto 0x%04X;
struct {
    u8  unk0xdc20:5,
        left_sql:3;
    u8  apo;
    u8  unk0xdc22:5,
        backlight:3;
    u8  unk0xdc23;
    u8  beep:1,
        keylock:1,
        pttlock:2,
        unk0xdc24_32:2,
        hyper_chan:1,
        right_func_key:1;
    u8  tbst_freq:2,
        unk0xdc25_4:2,
        mute_mode:2,
        unk0xdc25_10:2;
    u8  ars:1,
        unk0xdc26_54:3,
        auto_am:1,
        unk0xdc26_210:3;
    u8  unk0xdc27_76543:5,
        scan_mode:1,
        unk0xdc27_1:1,
        scan_resume:1;
    u16 scramb_freq;
    u16 scramb_freq1;
    u8  unk0xdc2c;
    u8  unk0xdc2d;
    u8  unk0xdc2e:5,
        right_sql:3;
    u8  unk0xdc2f:8;
    u8  tot;
    u8  unk0xdc30;
    u8  unk0xdc31;
    u8  unk0xdc32;
    u8  unk0xdc34;
    u8  unk0xdc35;
    u8  unk0xdc36;
    u8  unk0xdc37;
    u8  p1;
    u8  p2;
    u8  p3;
    u8  p4;
} settings;

#seekto 0x%04X;
u8  chan_active[128];
u8  scan_enable[128];
u8  priority[128];

#seekto 0x%04X;
struct {
    char sn[8];
    char model[8];
    char code[16];
    u8 empty[8];
    lbcd prog_yr[2];
    lbcd prog_mon;
    lbcd prog_day;
    u8 empty_10f2c[4];
} info;

struct {
  lbcd lorx[4];
  lbcd hirx[4];
  lbcd lotx[4];
  lbcd hitx[4];
} bandlimits[9];

"""


BLANK_MEMORY = "\xFF" * 8 + "\x00\x10\x23\x00\xC0\x08\x06\x00" \
               "\x00\x00\x76\x00\x00\x00" + "\xFF" * 10
DTCS_POLARITY = ["NN", "RN", "NR", "RR"]
SCAN_MODES = ["", "S", "P"]
MODES = ["WFM", "FM", "NFM"]
TMODES = ["", "Tone", "TSQL", "DTCS"]
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                chirp_common.PowerLevel("Mid2", watts=10.00),
                chirp_common.PowerLevel("Mid1", watts=20.00),
                chirp_common.PowerLevel("High", watts=50.00)]
BUSY_LOCK = ["off", "Carrier", "2 tone"]
MICKEYFUNC = ["None", "SCAN", "SQL.OFF", "TCALL", "PPTR", "PRI", "LOW", "TONE",
              "MHz", "REV", "HOME", "BAND", "VFO/MR"]
SQLPRESET = ["Off", "2", "5", "9", "Full"]
BANDS = ["30 MHz", "50 MHz", "60 MHz", "108 MHz", "150 MHz", "250 MHz", "350 MHz",
         "450 MHz", "850 MHz"]
STEPS = [2.5, 5.0, 6.25, 7.5, 8.33, 10.0, 12.5,
         15.0, 20.0, 25.0, 30.0, 50.0, 100.0]


def add_radio_setting(radio_setting_group, mem_field, ui_name, option_map,
                      current, doc=None):
    setting = RadioSetting(mem_field, ui_name,
                           RadioSettingValueMap(option_map, current))
    if doc is not None:
        setting.set_doc(doc)
    radio_setting_group.append(setting)


def add_radio_bool(radio_setting_group, mem_field, ui_name, current, doc=None):
    setting = RadioSetting(mem_field, ui_name,
                           RadioSettingValueBoolean(bool(current)))
    radio_setting_group.append(setting)


class TYTTH7800Base(chirp_common.Radio):
    """Base class for TYT TH-7800"""
    VENDOR = "TYT"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 800)
        rf.has_bank = False
        rf.has_tuning_step = True
        rf.valid_tuning_steps = STEPS
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = TMODES
        rf.has_ctone = False
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "#*-+"
        rf.valid_bands = [(108000000, 180000000),
                          (350000000, 399995000),
                          (400000000, 512000000)]
        rf.valid_skips = SCAN_MODES
        rf.valid_modes = MODES + ["AM"]
        rf.valid_name_length = 6
        rf.has_settings = True
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(
            TH7800_MEM_FORMAT %
            (self._mmap_offset, self._scanlimits_offset, self._settings_offset,
             self._chan_active_offset, self._info_offset), self._mmap)

    def get_active(self, banktype, num):
        """get active flag for channel active,
        scan enable, or priority banks"""
        bank = getattr(self._memobj, banktype)
        index = (num - 1) // 8
        bitpos = (num - 1) % 8
        mask = 2**bitpos
        enabled = bank[index] & mask
        if enabled:
            return True
        else:
            return False

    def set_active(self, banktype, num, enable=True):
        """set active flag for channel active,
        scan enable, or priority banks"""
        bank = getattr(self._memobj, banktype)
        index = (num - 1) // 8
        bitpos = (num - 1) % 8
        mask = 2**bitpos
        if enable:
            bank[index] |= mask
        else:
            bank[index] &= ~mask

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        mem.empty = not self.get_active("chan_active", number)
        if mem.empty:
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        txfreq = int(_mem.tx_freq) * 10
        if txfreq == mem.freq:
            mem.duplex = ""
        elif txfreq == 0:
            mem.duplex = "off"
            mem.offset = 0
        elif abs(txfreq - mem.freq) > 70000000:
            mem.duplex = "split"
            mem.offset = txfreq
        elif txfreq < mem.freq:
            mem.duplex = "-"
            mem.offset = mem.freq - txfreq
        elif txfreq > mem.freq:
            mem.duplex = "+"
            mem.offset = txfreq - mem.freq

        mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_pol]

        mem.tmode = TMODES[int(_mem.tmode)]
        mem.ctone = mem.rtone = int(_mem.ctcss) / 10.0
        mem.dtcs = int(_mem.dtcs)

        mem.name = str(_mem.name)
        mem.name = mem.name.replace("\xFF", " ").rstrip()

        if not self.get_active("scan_enable", number):
            mem.skip = "S"
        elif self.get_active("priority", number):
            mem.skip = "P"
        else:
            mem.skip = ""

        mem.mode = _mem.am and "AM" or MODES[int(_mem.fmdev)]

        mem.power = POWER_LEVELS[_mem.power]
        mem.tuning_step = STEPS[_mem.step]

        mem.extra = RadioSettingGroup("extra", "Extra")

        add_radio_setting(mem.extra, "display", "Display",
                          zero_indexed_seq_map(["Frequency", "Name"]),
                          _mem.display)
        add_radio_setting(mem.extra, "hsdtype", "HSD TYPE",
                          zero_indexed_seq_map(["OFF", "2TON", "5TON",
                                                "DTMF"]),
                          _mem.hsdtype)
        add_radio_bool(mem.extra, "clk_sft", "CLK-SFT", _mem.clk_sft)
        add_radio_bool(mem.extra, "compand", "Compand", _mem.compand,
                       doc="Compress Audio")
        add_radio_bool(mem.extra, "talkaround", "Talk Around", _mem.talkaround,
                       doc="Simplex mode when out of range of repeater")

        add_radio_bool(mem.extra, "scramb", "Scramble", _mem.scramb,
                       doc="Frequency inversion Scramble")
        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        _prev_active = self.get_active("chan_active", mem.number)
        self.set_active("chan_active", mem.number, not mem.empty)
        if mem.empty or not _prev_active:
            LOG.debug("initializing memory channel %d" % mem.number)
            _mem.set_raw(BLANK_MEMORY)

        if mem.empty:
            return

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "split":
            _mem.tx_freq = mem.offset / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "off":
            _mem.tx_freq = 0
            _mem.offset = 0
        else:
            _mem.tx_freq = mem.freq / 10

        _mem.tmode = TMODES.index(mem.tmode)
        if mem.tmode == "TSQL" or mem.tmode == "DTCS":
            _mem.sqlmode = 1
        else:
            _mem.sqlmode = 0
        _mem.ctcss = mem.rtone * 10
        _mem.dtcs = mem.dtcs
        _mem.dtcs_pol = DTCS_POLARITY.index(mem.dtcs_polarity)

        _mem.name = mem.name.ljust(6, "\xFF")

        # autoset display to name if filled, else show frequency
        if mem.extra:
            # mem.extra only seems to be populated when called from edit panel
            display = mem.extra["display"]
        else:
            display = None
        if mem.name:
            _mem.display = True
        else:
            _mem.display = False

        _mem.scan = SCAN_MODES.index(mem.skip)
        if mem.skip == "P":
            self.set_active("priority", mem.number, True)
            self.set_active("scan_enable", mem.number, True)
        elif mem.skip == "S":
            self.set_active("priority", mem.number, False)
            self.set_active("scan_enable", mem.number, False)
        elif mem.skip == "":
            self.set_active("priority", mem.number, False)
            self.set_active("scan_enable", mem.number, True)

        if mem.mode == "AM":
            _mem.am = True
            _mem.fmdev = 0
        else:
            _mem.am = False
            _mem.fmdev = MODES.index(mem.mode)

        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0    # low
        _mem.step = STEPS.index(mem.tuning_step)

        for setting in mem.extra:
            LOG.debug("@set_mem: %s %s", setting.get_name(), setting.value)
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        _info = self._memobj.info
        _bandlimits = self._memobj.bandlimits
        basic = RadioSettingGroup("basic", "Basic")
        info = RadioSettingGroup("info", "Model Info")
        top = RadioSettings(basic, info)
        add_radio_bool(basic, "beep", "Beep", _settings.beep)
        add_radio_bool(basic, "ars", "Auto Repeater Shift", _settings.ars)
        add_radio_setting(basic, "keylock", "Key Lock",
                          zero_indexed_seq_map(["Manual", "Auto"]),
                          _settings.keylock)
        add_radio_bool(basic, "auto_am", "Auto AM", _settings.auto_am)
        add_radio_setting(basic, "left_sql", "Left Squelch",
                          zero_indexed_seq_map(SQLPRESET),
                          _settings.left_sql)
        add_radio_setting(basic, "right_sql", "Right Squelch",
                          zero_indexed_seq_map(SQLPRESET),
                          _settings.right_sql)
        add_radio_setting(basic, "apo", "Auto Power off (Hours)",
                          [("Off", 0), ("0.5", 5), ("1.0", 10), ("1.5", 15),
                           ("2.0", 20)],
                          _settings.apo)
        add_radio_setting(basic, "backlight", "Display Backlight",
                          zero_indexed_seq_map(["Off", "1", "2", "3", "Full"]),
                          _settings.backlight)
        add_radio_setting(basic, "pttlock", "PTT Lock",
                          zero_indexed_seq_map(["Off", "Right", "Left",
                                                "Both"]),
                          _settings.pttlock)
        add_radio_setting(basic, "hyper_chan", "Hyper Channel",
                          zero_indexed_seq_map(["Manual", "Auto"]),
                          _settings.hyper_chan)
        add_radio_setting(basic, "right_func_key", "Right Function Key",
                          zero_indexed_seq_map(["Key 1", "Key 2"]),
                          _settings.right_func_key)
        add_radio_setting(basic, "mute_mode", "Mute Mode",
                          zero_indexed_seq_map(["Off", "TX", "RX", "TX RX"]),
                          _settings.mute_mode)
        add_radio_setting(basic, "scan_mode", "Scan Mode",
                          zero_indexed_seq_map(["MEM", "MSM"]),
                          _settings.scan_mode,
                          doc="MEM = Normal scan, bypass channels marked "
                          "skip. MSM = Scan only channels marked priority.")
        add_radio_setting(basic, "scan_resume", "Scan Resume",
                          zero_indexed_seq_map(["Time", "Busy"]),
                          _settings.scan_resume)
        basic.append(RadioSetting(
                "tot", "Time Out Timer (minutes)",
                RadioSettingValueInteger(0, 30, _settings.tot)))
        add_radio_setting(basic, "p1", "P1 Function",
                          zero_indexed_seq_map(MICKEYFUNC),
                          _settings.p1)
        add_radio_setting(basic, "p2", "P2 Function",
                          zero_indexed_seq_map(MICKEYFUNC),
                          _settings.p2)
        add_radio_setting(basic, "p3", "P3 Function",
                          zero_indexed_seq_map(MICKEYFUNC),
                          _settings.p3)
        add_radio_setting(basic, "p4", "P4 Function",
                          zero_indexed_seq_map(MICKEYFUNC),
                          _settings.p4)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        rsvs = RadioSettingValueString(0, 8, _filter(_info.sn))
        rsvs.set_mutable(False)
        rs = RadioSetting("sn", "Serial Number", rsvs)
        info.append(rs)

        rsvs = RadioSettingValueString(0, 8, _filter(_info.model))
        rsvs.set_mutable(False)
        rs = RadioSetting("model", "Model Name", rsvs)
        info.append(rs)

        rsvs = RadioSettingValueString(0, 16, _filter(_info.code))
        rsvs.set_mutable(False)
        rs = RadioSetting("code", "Model Code", rsvs)
        info.append(rs)

        progdate = "%d/%d/%d" % (_info.prog_mon, _info.prog_day,
                                 _info.prog_yr)
        rsvs = RadioSettingValueString(0, 10, progdate)
        rsvs.set_mutable(False)
        rs = RadioSetting("progdate", "Last Program Date", rsvs)
        info.append(rs)

        # Band Limits
        for i in range(0, len(BANDS)):
            rx_start = int(_bandlimits[i].lorx) * 10
            if not rx_start == 0:
                objname = BANDS[i] + "lorx"
                objnamepp = BANDS[i] + " Rx Start"
                rsv = RadioSettingValueString(0, 10, format_freq(rx_start))
                rsv.set_mutable(False)
                rs = RadioSetting(objname, objnamepp, rsv)
                info.append(rs)

                rx_end = int(_bandlimits[i].hirx) * 10
                objname = BANDS[i] + "hirx"
                objnamepp = BANDS[i] + " Rx end"
                rsv = RadioSettingValueString(0, 10, format_freq(rx_end))
                rsv.set_mutable(False)
                rs = RadioSetting(objname, objnamepp, rsv)
                info.append(rs)

            tx_start = int(_bandlimits[i].lotx) * 10
            if not tx_start == 0:
                objname = BANDS[i] + "lotx"
                objnamepp = BANDS[i] + " Tx Start"
                rsv = RadioSettingValueString(0, 10, format_freq(tx_start))
                rsv.set_mutable(False)
                rs = RadioSetting(objname, objnamepp, rsv)
                info.append(rs)

                tx_end = int(_bandlimits[i].hitx) * 10
                objname = BANDS[i] + "hitx"
                objnamepp = BANDS[i] + " Tx end"
                rsv = RadioSettingValueString(0, 10, format_freq(tx_end))
                rsv.set_mutable(False)
                rs = RadioSetting(objname, objnamepp, rsv)
                info.append(rs)
        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _info = self._memobj.info
        _bandlimits = self._memobj.bandlimits
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                setting = element.get_name()
                oldval = getattr(_settings, setting)
                newval = element.value

                LOG.debug("Setting %s(%s) <= %s" % (setting, oldval, newval))
                setattr(_settings, setting, newval)
            except Exception:
                LOG.debug(element.get_name())
                raise


@directory.register
class TYTTH7800File(TYTTH7800Base, chirp_common.FileBackedRadio):
    """TYT TH-7800 .dat file"""
    MODEL = "TH-7800 File"
    NEEDS_COMPAT_SERIAL = True
    FILE_EXTENSION = "dat"

    _memsize = 69632
    _mmap_offset = 0x1100
    _scanlimits_offset = 0xC800 + _mmap_offset
    _settings_offset = 0xCB20 + _mmap_offset
    _chan_active_offset = 0xCB80 + _mmap_offset
    _info_offset = 0xfe00 + _mmap_offset

    def __init__(self, pipe):
        self.errors = []
        self._mmap = None

        if isinstance(pipe, str):
            self.pipe = None
            self.load_mmap(pipe)
        else:
            chirp_common.FileBackedRadio.__init__(self, pipe)

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and filename.endswith('.dat')


def _identify(radio):
    """Do identify handshake with TYT"""
    try:
        radio.pipe.write(b"\x02SPECPR")
        ack = radio.pipe.read(1)
        if ack != b"A":
            util.hexprint(ack)
            raise errors.RadioError("Radio did not ACK first command: %r"
                                    % ack)
    except:
        raise errors.RadioError("Unable to communicate with the radio")

    radio.pipe.write(b"G\x02")
    ident = radio.pipe.read(16)
    radio.pipe.write(b"A")
    r = radio.pipe.read(2)
    if r != b"A":
        raise errors.RadioError("Ack failed")
    return ident


def _download(radio, memsize=0x10000, blocksize=0x80):
    """Download from TYT TH-7800"""
    data = _identify(radio)
    LOG.info("ident:", util.hexprint(data))
    offset = 0x100
    for addr in range(offset, memsize, blocksize):
        msg = struct.pack(">cHB", b"R", addr, blocksize)
        radio.pipe.write(msg)
        block = radio.pipe.read(blocksize + 4)
        if len(block) != (blocksize + 4):
            LOG.debug(util.hexprint(block))
            raise errors.RadioError("Radio sent a short block")
        radio.pipe.write(b"A")
        ack = radio.pipe.read(1)
        if ack != b"A":
            LOG.debug(util.hexprint(ack))
            raise errors.RadioError("Radio NAKed block")
        data += block[4:]

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = addr
            status.max = memsize
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    radio.pipe.write(b"ENDR")

    return memmap.MemoryMapBytes(data)


def _upload(radio, memsize=0xF400, blocksize=0x80):
    """Upload to TYT TH-7800"""
    data = _identify(radio)

    radio.pipe.timeout = 1

    if data != radio._mmap[0:radio._mmap_offset]:
        raise errors.RadioError(
            "Model mismatch: \n%s\n%s" %
            (util.hexprint(data),
             util.hexprint(radio._mmap[:radio._mmap_offset])))
    # in the factory software they update the last program date when
    # they upload, So let's do the same
    today = date.today()
    y = today.year
    m = today.month
    d = today.day
    _info = radio._memobj.info

    ly = _info.prog_yr
    lm = _info.prog_mon
    ld = _info.prog_day
    LOG.debug("Updating last program date:%d/%d/%d" % (lm, ld, ly))
    LOG.debug("                  to today:%d/%d/%d" % (m, d, y))

    _info.prog_yr = y
    _info.prog_mon = m
    _info.prog_day = d

    offset = 0x0100
    for addr in range(offset, memsize, blocksize):
        mapaddr = addr + radio._mmap_offset - offset
        LOG.debug("addr: 0x%04X, mmapaddr: 0x%04X" % (addr, mapaddr))
        msg = struct.pack(">cHB", b"W", addr, blocksize)
        msg += radio._mmap[mapaddr:(mapaddr + blocksize)]
        LOG.debug(util.hexprint(msg))
        radio.pipe.write(msg)
        ack = radio.pipe.read(1)
        if ack != b"A":
            LOG.debug(util.hexprint(ack))
            raise errors.RadioError("Radio did not ack block 0x%04X" % addr)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = addr
            status.max = memsize
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    # End of clone
    radio.pipe.write(b"ENDW")

    # Checksum?
    final_data = radio.pipe.read(3)
    LOG.debug("final:", util.hexprint(final_data))


@directory.register
class TYTTH7800Radio(TYTTH7800Base, chirp_common.CloneModeRadio,
                     chirp_common.ExperimentalRadio):
    VENDOR = "TYT"
    MODEL = "TH-7800"
    BAUD_RATE = 38400

    _memsize = 65296
    _mmap_offset = 0x0010
    _scanlimits_offset = 0xC800 + _mmap_offset
    _settings_offset = 0xCB20 + _mmap_offset
    _chan_active_offset = 0xCB80 + _mmap_offset
    _info_offset = 0xfe00 + _mmap_offset

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) != cls._memsize:
            return False
        # TYT used TH9800 as model for TH-7800 _AND_ TH-9800.  Check
        # for TH7800 in case they fix it or if users update the model
        # in their own radio.
        if not (filedata[0xfe18:0xfe1e] == b"TH9800" or
                filedata[0xfe18:0xfe1e] == b"TH7800"):
            return False
        # TH-7800 bandlimits differ from TH-9800.  First band Invalid
        # (zero).
        first_bandlimit = struct.unpack("BBBBBBBBBBBBBBBB",
                                        filedata[0xfe40:0xfe50])
        if not all(v == 0 for v in first_bandlimit):
            return False
        return True

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
         'This is experimental support for TH-7800 '
         'which is still under development.\n'
         'Please ensure you have a good backup with OEM software.\n'
         'Also please send in bug and enhancement requests!\n'
         'You have been warned. Proceed at your own risk!')
        return rp

    def sync_in(self):
        try:
            self._mmap = _download(self)
        except Exception as e:
            raise errors.RadioError(
                    "Failed to communicate with the radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            _upload(self)
        except Exception as e:
            raise errors.RadioError(
                    "Failed to communicate with the radio: %s" % e)
