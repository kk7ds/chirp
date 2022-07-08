# Copyright 2014 Tom Hayward <tom@tomh.us>
# Copyright 2014 Jens Jensen <af5mi@yahoo.com>
# Copyright 2014 James Lee N1DDK <jml@jmlzone.com>
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
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, InvalidValueError, RadioSettings
from chirp.chirp_common import format_freq
import os
import time
import logging
from datetime import date

LOG = logging.getLogger(__name__)

TH9800_MEM_FORMAT = """
struct mem {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  lbcd ctcss[2];
  lbcd dtcs[2];
  u8 power:2,
     BeatShift:1,
     unknown0a:2,
     display:1,     // freq=0, name=1
     scan:2;
  u8 fmdev:2,       // wide=00, mid=01, narrow=10
     scramb:1,
     compand:1,
     emphasis:1
     unknown1a:2,
     sqlmode:1;     // carrier, tone
  u8 rptmod:2,      // off, -, +
     reverse:1,
     talkaround:1,
     step:4;
  u8 dtcs_pol:2,
     bclo:2,
     unknown3:2,
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
        ani_display:1,
        unk0xdc25_4:1
        mute_mode:2,
        unk0xdc25_10:2;
    u8  auto_xfer:1,
        auto_contact:1,
        unk0xdc26_54:2,
        auto_am:1,
        unk0xdc26_210:3;
    u8  unk0xdc27_76543:5,
        scan_mode:1,
        unk0xdc27_1:1,
        scan_resume:1;
    u16 scramb_freq;
    u16 scramb_freq1;
    u8  exit_delay;
    u8  unk0xdc2d;
    u8  unk0xdc2e:5,
        right_sql:3;
    u8  unk0xdc2f:4,
        beep_vol:4;
    u8  tot;
    u8  tot_alert;
    u8  tot_rekey;
    u8  tot_reset;
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
BANDS = ["30MHz", "50MHz", "60MHz", "108MHz", "150MHz", "250MHz", "350MHz",
         "450MHz", "850MHz"]
STEPS = [2.5, 5.0, 6.25, 7.5, 8.33, 10.0, 12.5,
         15.0, 20.0, 25.0, 30.0, 50.0, 100.0]


class TYTTH9800Base(chirp_common.Radio):
    """Base class for TYT TH-9800"""
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
        rf.valid_bands = [(26000000,  33000000),
                          (47000000,  54000000),
                          (108000000, 180000000),
                          (220000000, 260000000),
                          (350000000, 399995000),
                          (400000000, 512000000),
                          (750000000, 950000000)]
        rf.valid_skips = SCAN_MODES
        rf.valid_modes = MODES + ["AM"]
        rf.valid_name_length = 6
        rf.has_settings = True
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(
            TH9800_MEM_FORMAT %
            (self._mmap_offset, self._scanlimits_offset, self._settings_offset,
             self._chan_active_offset, self._info_offset), self._mmap)

    def get_active(self, banktype, num):
        """get active flag for channel active,
        scan enable, or priority banks"""
        bank = getattr(self._memobj, banktype)
        index = (num - 1) / 8
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
        index = (num - 1) / 8
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

        opts = ["Frequency", "Name"]
        display = RadioSetting(
                "display", "Display",
                RadioSettingValueList(opts, opts[_mem.display]))
        mem.extra.append(display)

        bclo = RadioSetting(
                "bclo", "Busy Lockout",
                RadioSettingValueList(BUSY_LOCK, BUSY_LOCK[_mem.bclo]))
        bclo.set_doc("Busy Lockout")
        mem.extra.append(bclo)

        emphasis = RadioSetting(
                "emphasis", "Emphasis",
                RadioSettingValueBoolean(bool(_mem.emphasis)))
        emphasis.set_doc("Boosts 300Hz to 2500Hz mic response")
        mem.extra.append(emphasis)

        compand = RadioSetting(
                "compand", "Compand",
                RadioSettingValueBoolean(bool(_mem.compand)))
        compand.set_doc("Compress Audio")
        mem.extra.append(compand)

        BeatShift = RadioSetting(
                "BeatShift", "BeatShift",
                RadioSettingValueBoolean(bool(_mem.BeatShift)))
        BeatShift.set_doc("Beat Shift")
        mem.extra.append(BeatShift)

        TalkAround = RadioSetting(
                "talkaround", "Talk Around",
                RadioSettingValueBoolean(bool(_mem.talkaround)))
        TalkAround.set_doc("Simplex mode when out of range of repeater")
        mem.extra.append(TalkAround)

        scramb = RadioSetting(
                "scramb", "Scramble",
                RadioSettingValueBoolean(bool(_mem.scramb)))
        scramb.set_doc("Frequency inversion Scramble")
        mem.extra.append(scramb)

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
            if display and not display.changed():
                display.value = "Name"
        else:
            _mem.display = False
            if display and not display.changed():
                display.value = "Frequency"

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
            LOG.debug("@set_mem:", setting.get_name(), setting.value)
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        _info = self._memobj.info
        _bandlimits = self._memobj.bandlimits
        basic = RadioSettingGroup("basic", "Basic")
        info = RadioSettingGroup("info", "Model Info")
        top = RadioSettings(basic, info)
        basic.append(RadioSetting(
                "beep", "Beep",
                RadioSettingValueBoolean(_settings.beep)))
        basic.append(RadioSetting(
                "beep_vol", "Beep Volume",
                RadioSettingValueInteger(0, 15, _settings.beep_vol)))
        basic.append(RadioSetting(
                "keylock", "Key Lock",
                RadioSettingValueBoolean(_settings.keylock)))
        basic.append(RadioSetting(
                "ani_display", "ANI Display",
                RadioSettingValueBoolean(_settings.ani_display)))
        basic.append(RadioSetting(
                "auto_xfer", "Auto Transfer",
                RadioSettingValueBoolean(_settings.auto_xfer)))
        basic.append(RadioSetting(
                "auto_contact", "Auto Contact Always Remind",
                RadioSettingValueBoolean(_settings.auto_contact)))
        basic.append(RadioSetting(
                "auto_am", "Auto AM",
                RadioSettingValueBoolean(_settings.auto_am)))
        basic.append(RadioSetting(
                "left_sql", "Left Squelch",
                RadioSettingValueList(
                    SQLPRESET, SQLPRESET[_settings.left_sql])))
        basic.append(RadioSetting(
                "right_sql", "Right Squelch",
                RadioSettingValueList(
                    SQLPRESET, SQLPRESET[_settings.right_sql])))
#      basic.append(RadioSetting("apo", "Auto Power off (0.1h)",
#              RadioSettingValueInteger(0, 20, _settings.apo)))
        opts = ["Off"] + ["%0.1f" % (t / 10.0) for t in range(1, 21, 1)]
        basic.append(RadioSetting(
                "apo", "Auto Power off (Hours)",
                RadioSettingValueList(opts, opts[_settings.apo])))
        opts = ["Off", "1", "2", "3", "Full"]
        basic.append(RadioSetting(
                "backlight", "Display Backlight",
                RadioSettingValueList(opts, opts[_settings.backlight])))
        opts = ["Off", "Right", "Left", "Both"]
        basic.append(RadioSetting(
                "pttlock", "PTT Lock",
                RadioSettingValueList(opts, opts[_settings.pttlock])))
        opts = ["Manual", "Auto"]
        basic.append(RadioSetting(
                "hyper_chan", "Hyper Channel",
                RadioSettingValueList(opts, opts[_settings.hyper_chan])))
        opts = ["Key 1", "Key 2"]
        basic.append(RadioSetting(
                "right_func_key", "Right Function Key",
                RadioSettingValueList(opts, opts[_settings.right_func_key])))
        opts = ["1000Hz", "1450Hz", "1750Hz", "2100Hz"]
        basic.append(RadioSetting(
                "tbst_freq", "Tone Burst Frequency",
                RadioSettingValueList(opts, opts[_settings.tbst_freq])))
        opts = ["Off", "TX", "RX", "TX RX"]
        basic.append(RadioSetting(
                "mute_mode", "Mute Mode",
                RadioSettingValueList(opts, opts[_settings.mute_mode])))
        opts = ["MEM", "MSM"]
        scanmode = RadioSetting(
                "scan_mode", "Scan Mode",
                RadioSettingValueList(opts, opts[_settings.scan_mode]))
        scanmode.set_doc("MEM = Normal scan, bypass channels marked skip. "
                         " MSM = Scan only channels marked priority.")
        basic.append(scanmode)
        opts = ["TO", "CO"]
        basic.append(RadioSetting(
                "scan_resume", "Scan Resume",
                RadioSettingValueList(opts, opts[_settings.scan_resume])))
        opts = ["%0.1f" % (t / 10.0) for t in range(0, 51, 1)]
        basic.append(RadioSetting(
                "exit_delay", "Span Transit Exit Delay",
                RadioSettingValueList(opts, opts[_settings.exit_delay])))
        basic.append(RadioSetting(
                "tot", "Time Out Timer (minutes)",
                RadioSettingValueInteger(0, 30, _settings.tot)))
        basic.append(RadioSetting(
                "tot_alert", "Time Out Timer Pre Alert(seconds)",
                RadioSettingValueInteger(0, 15, _settings.tot_alert)))
        basic.append(RadioSetting(
                "tot_rekey", "Time Out Rekey (seconds)",
                RadioSettingValueInteger(0, 15, _settings.tot_rekey)))
        basic.append(RadioSetting(
                "tot_reset", "Time Out Reset(seconds)",
                RadioSettingValueInteger(0, 15, _settings.tot_reset)))
        basic.append(RadioSetting(
                "p1", "P1 Function",
                RadioSettingValueList(MICKEYFUNC, MICKEYFUNC[_settings.p1])))
        basic.append(RadioSetting(
                "p2", "P2 Function",
                RadioSettingValueList(MICKEYFUNC, MICKEYFUNC[_settings.p2])))
        basic.append(RadioSetting(
                "p3", "P3 Function",
                RadioSettingValueList(MICKEYFUNC, MICKEYFUNC[_settings.p3])))
        basic.append(RadioSetting(
                "p4", "P4 Function",
                RadioSettingValueList(MICKEYFUNC, MICKEYFUNC[_settings.p4])))
#      opts = ["0", "1"]
#      basic.append(RadioSetting("x", "Desc",
#            RadioSettingValueList(opts, opts[_settings.x])))

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

        # 9 band limits
        for i in range(0, 9):
            objname = BANDS[i] + "lorx"
            objnamepp = BANDS[i] + " Rx Start"
            # rsv = RadioSettingValueInteger(0, 100000000,
            #              int(_bandlimits[i].lorx))
            rsv = RadioSettingValueString(
                    0, 10, format_freq(int(_bandlimits[i].lorx)*10))
            rsv.set_mutable(False)
            rs = RadioSetting(objname, objnamepp, rsv)
            info.append(rs)
            objname = BANDS[i] + "hirx"
            objnamepp = BANDS[i] + " Rx end"
            rsv = RadioSettingValueString(
                    0, 10, format_freq(int(_bandlimits[i].hirx)*10))
            rsv.set_mutable(False)
            rs = RadioSetting(objname, objnamepp, rsv)
            info.append(rs)
            objname = BANDS[i] + "lotx"
            objnamepp = BANDS[i] + " Tx Start"
            rsv = RadioSettingValueString(
                    0, 10, format_freq(int(_bandlimits[i].lotx)*10))
            rsv.set_mutable(False)
            rs = RadioSetting(objname, objnamepp, rsv)
            info.append(rs)
            objname = BANDS[i] + "hitx"
            objnamepp = BANDS[i] + " Tx end"
            rsv = RadioSettingValueString(
                    0, 10, format_freq(int(_bandlimits[i].hitx)*10))
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
            except Exception as e:
                LOG.debug(element.get_name())
                raise


@directory.register
class TYTTH9800File(TYTTH9800Base, chirp_common.FileBackedRadio):
    """TYT TH-9800 .dat file"""
    MODEL = "TH-9800 File"

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
        radio.pipe.write("\x02PROGRA")
        ack = radio.pipe.read(1)
        if ack != "A":
            util.hexprint(ack)
            raise errors.RadioError("Radio did not ACK first command: %x"
                                    % ord(ack))
    except:
        LOG.debug(util.hexprint(ack))
        raise errors.RadioError("Unable to communicate with the radio")

    radio.pipe.write("M\x02")
    ident = radio.pipe.read(16)
    radio.pipe.write("A")
    r = radio.pipe.read(1)
    if r != "A":
        raise errors.RadioError("Ack failed")
    return ident


def _download(radio, memsize=0x10000, blocksize=0x80):
    """Download from TYT TH-9800"""
    data = _identify(radio)
    LOG.info("ident:", util.hexprint(data))
    offset = 0x100
    for addr in range(offset, memsize, blocksize):
        msg = struct.pack(">cHB", "R", addr, blocksize)
        radio.pipe.write(msg)
        block = radio.pipe.read(blocksize + 4)
        if len(block) != (blocksize + 4):
            LOG.debug(util.hexprint(block))
            raise errors.RadioError("Radio sent a short block")
        radio.pipe.write("A")
        ack = radio.pipe.read(1)
        if ack != "A":
            LOG.debug(util.hexprint(ack))
            raise errors.RadioError("Radio NAKed block")
        data += block[4:]

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = addr
            status.max = memsize
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    radio.pipe.write("ENDR")

    return memmap.MemoryMap(data)


def _upload(radio, memsize=0xF400, blocksize=0x80):
    """Upload to TYT TH-9800"""
    data = _identify(radio)

    radio.pipe.timeout = 1

    if data != radio._mmap[:radio._mmap_offset]:
        raise errors.RadioError(
            "Model mis-match: \n%s\n%s" %
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
        msg = struct.pack(">cHB", "W", addr, blocksize)
        msg += radio._mmap[mapaddr:(mapaddr + blocksize)]
        LOG.debug(util.hexprint(msg))
        radio.pipe.write(msg)
        ack = radio.pipe.read(1)
        if ack != "A":
            LOG.debug(util.hexprint(ack))
            raise errors.RadioError("Radio did not ack block 0x%04X" % addr)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = addr
            status.max = memsize
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    # End of clone
    radio.pipe.write("ENDW")

    # Checksum?
    final_data = radio.pipe.read(3)
    LOG.debug("final:", util.hexprint(final_data))


@directory.register
class TYTTH9800Radio(TYTTH9800Base, chirp_common.CloneModeRadio,
                     chirp_common.ExperimentalRadio):
    VENDOR = "TYT"
    MODEL = "TH-9800"
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
        # TYT set this model for TH-7800 _AND_ TH-9800
        if not filedata[0xfe18:0xfe1e] == "TH9800":
            return False
        # TH-9800 bandlimits differ from TH-7800.  First band is used
        # (non-zero).
        first_bandlimit = struct.unpack("BBBBBBBBBBBBBBBB",
                                        filedata[0xfe40:0xfe50])
        if all(v == 0 for v in first_bandlimit):
            return False
        return True

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
         'This is experimental support for TH-9800 '
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
