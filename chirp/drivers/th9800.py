# Copyright 2014 Tom Hayward <tom@tomh.us>
# Copyright 2014 Jens Jensen <af5mi@yahoo.com>
# Copyright 2014 James Lee N1DDK <jml@jmlzone.com>
# Copyright 2025 Jim Unroe KC9HI <rock.unroe@gmail.com> add Retevis MA1 support
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
    RadioSettings
from chirp.chirp_common import format_freq
import logging
from datetime import date

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x%04X;
struct mem memory[%d];

#seekto 0x%04X;
struct {
  struct mem lower;
  struct mem upper;
} scanlimits[5];

#seekto 0x%04X;
struct {
    u8  unk0xdb07_7:1,
        vox:3,
        unk0xdb07_1:3,
        txanc:1;
    u8  unk0xdb08[8];
    u8  unk0xdb10[16];
    u8  unk0xdc20:5,
        left_sql:3;
    u8  apo;
    u8  unk0xdc22:4,
        backlight:4;
    u8  mdf:1,              //bit 7 is mdf 0=freq, 1=name
        unk0xdc23_5:2,
        dtmf_keylock:1,
        auto_brightness:1,
        repeater_mode:2,
        unk0xdc23_0:1;
    u8  beep:1,
        keylock:1,
        pttlock:2,
        unk0xdc24_32:2,
        hyper_chan:1,
        right_func_key:1;
    u8  tbst_freq:2,
        ani_display:1,
        non_subvoice_tail:1,
        mute_mode:2,
        unk0xdc25_10:2;
    u8  auto_xfer:1,
        auto_contact:1,
        unk0xdc26_54:2,
        auto_am:1,
        unk0xdc26_210:3;
    u8  unk0xdc27_76543:5,
        scan_mode:1,
        scan_resume:2;
    u16 scramb_freq;
    u16 scramb_freq1;
    u8  exit_delay;
    u8  mic_gain;
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
    u8  pnl_band;
    u8  pnl_ctrl;
    u8  pnl_m;
    u8  unk0xdcef;
    char  screen_text[6];
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


DTCS_POLARITY = ["NN", "RN", "NR", "RR"]
SQLPRESET = ["Off", "2", "5", "9", "Full"]
BANDS = ["30 MHz", "50 MHz", "60 MHz", "108 MHz", "150 MHz", "250 MHz",
         "350 MHz", "450 MHz", "850 MHz"]
STEPS = [2.5, 5.0, 6.25, 7.5, 8.33, 10.0, 12.5,
         15.0, 20.0, 25.0, 30.0, 50.0, 100.0]
HSDTYPE = ["Off", "2 Tone", "5 Tone", "DTMF"]
PTTIDMODE = ["Off", "PTTID1", "PTTID2", "PTTID3", "PTTID4", "5 Tone"]


def isValidDate(month, day, year):
    today = date.today()

    monthlist1 = [1, 3, 5, 7, 8, 10, 12]  # monthlist for months with 31 days.
    monthlist2 = [4, 6, 9, 11]  # monthlist for months with 30 days.
    monthlist3 = [2, ]  # monthlist for month with 28 days.

    if month in monthlist1:
        max1 = 31
    elif month in monthlist2:
        max1 = 30
    elif month in monthlist3:
        if ((year % 4) == 0 and (year % 100) != 0 or (year % 400) == 0):
            max1 = 29
        else:
            max1 = 28
    if (month < 1 or month > 12):
        LOG.debug("Invalid 'Last Program Date: Month'")
        return False
    elif (day < 1 or day > max1):
        LOG.debug("Invalid 'Last Program Date: Day'")
        return False
    elif (year < 2014 or year > today.year):
        LOG.debug("Invalid 'Last Program Date: Year'")
        return False
    return True


class TYTTH9800Base(chirp_common.Radio):
    """Base class for TYT TH-9800"""
    VENDOR = "TYT"

    _upper = 800

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
         emphasis:1,
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
    """

    BLANK_MEMORY = "\xFF" * 8 + "\x00\x10\x23\x00\xC0\x08\x06\x00" \
                   "\x00\x00\x76\x00\x00\x00" + "\xFF" * 10
    SCAN_MODES = ["", "S", "P"]
    MODES = ["WFM", "FM", "NFM"]
    TMODES = ["", "Tone", "TSQL", "DTCS"]
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                    chirp_common.PowerLevel("Mid2", watts=10.00),
                    chirp_common.PowerLevel("Mid1", watts=20.00),
                    chirp_common.PowerLevel("High", watts=50.00)]
    BUSY_LOCK = ["off", "Carrier", "2 tone"]
    MICKEYFUNC = ["None", "SCAN", "SQL.OFF", "TCALL", "PPTR", "PRI", "LOW",
                  "TONE", "MHz", "REV", "HOME", "BAND", "VFO/MR"]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 800)
        rf.has_bank = False
        rf.has_tuning_step = True
        rf.valid_tuning_steps = STEPS
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = self.TMODES
        rf.has_ctone = False
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "#*-+"
        rf.valid_bands = [(26000000,  33000000),
                          (47000000,  54000000),
                          (108000000, 180000000),
                          (220000000, 260000000),
                          (350000000, 399995000),
                          (400000000, 512000000),
                          (750000000, 950000000)]
        rf.valid_skips = self.SCAN_MODES
        rf.valid_modes = self.MODES + ["AM"]
        rf.valid_name_length = 6
        rf.has_settings = True
        return rf

    def process_mmap(self):
        LOG.debug('Ident info from image:\n%s',
                  util.hexprint(self._mmap[0:self._mmap_offset]))

        fmt = (self.TH9800_MEM_FORMAT + MEM_FORMAT)
        self._memobj = bitwise.parse(
            fmt % (self._mmap_offset,
                   self._upper,
                   self._scanlimits_offset,
                   self._settings_offset,
                   self._chan_active_offset,
                   self._info_offset
                   ), self._mmap)

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

    def decode_tone(self, val, tmode):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        if tmode == 0x00:
            return '', None, None

        val = int(val)
        if tmode == 0x03:
            a = val
            return 'DTCS', a, 'R'
        elif tmode == 0x02:
            a = val
            return 'DTCS', a, 'N'
        else:
            a = val / 10.0
            return 'Tone', a, None

    def encode_tone(self, memval, mode, value, pol, tmodeval):
        """Parse the tone data to encode from UI to mem"""
        if mode == '':
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
            tmodeval.set_value(0x00)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
            tmodeval.set_value(0x01)
        elif mode == 'DTCS':
            tmodev = 0x02 if pol == 'N' else 0x03
            memval.set_value(value)
            tmodeval.set_value(tmodev)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

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

        if self.MODEL == "MA1":
            rxtone = txtone = None
            txtone = self.decode_tone(_mem.tx_tone, _mem.tx_tmode)
            rxtone = self.decode_tone(_mem.rx_tone, _mem.rx_tmode)
            chirp_common.split_tone_decode(mem, txtone, rxtone)
        else:
            mem.dtcs_polarity = DTCS_POLARITY[_mem.dtcs_pol]

            mem.tmode = self.TMODES[int(_mem.tmode)]
            mem.ctone = mem.rtone = int(_mem.ctcss) / 10.0
            mem.dtcs = int(_mem.dtcs)

        mem.name = self.filter_name(str(_mem.name).rstrip('\x00\x20\xFF'))

        if not self.get_active("scan_enable", number):
            mem.skip = "S"
        elif self.get_active("priority", number):
            mem.skip = "P"
        else:
            mem.skip = ""

        if self.MODEL == "MA1":
            if _mem.am:
                mem.mode = 'AM'
            elif _mem.fmdev == self.CHANNEL_WIDTH_25kHz:
                mem.mode = 'FM'
            elif _mem.fmdev == self.CHANNEL_WIDTH_20kHz:
                LOG.info(
                    '%s: get_mem: promoting 20 kHz channel width to 25 kHz' %
                    mem.name)
                mem.mode = 'FM'
            elif _mem.fmdev == self.CHANNEL_WIDTH_12d5kHz:
                mem.mode = 'NFM'
            else:
                LOG.error('%s: get_mem: unhandled channel width: 0x%02x' %
                          (mem.name, _mem.fmdev))
        else:
            mem.mode = _mem.am and "AM" or self.MODES[int(_mem.fmdev)]

        if self.MODEL == "MA1":
            if _mem.power == self.TXPOWER_LOW:
                mem.power = self.POWER_LEVELS[0]
            elif _mem.power == self.TXPOWER_MED:
                mem.power = self.POWER_LEVELS[1]
            elif _mem.power == self.TXPOWER_HIGH:
                mem.power = self.POWER_LEVELS[2]
            else:
                LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                          (mem.name, _mem.power))
        else:
            mem.power = self.POWER_LEVELS[_mem.power]
        mem.tuning_step = STEPS[_mem.step]

        mem.extra = RadioSettingGroup("extra", "Extra")

        if not self.MODEL == "MA1":
            opts = ["Frequency", "Name"]
            display = RadioSetting(
                    "display", "Display",
                    RadioSettingValueList(opts, current_index=_mem.display))
            mem.extra.append(display)

        bclo = RadioSetting(
                "bclo", "Busy Lockout",
                RadioSettingValueList(self.BUSY_LOCK, current_index=_mem.bclo))
        bclo.set_doc("Busy Lockout")
        mem.extra.append(bclo)

        if not self.MODEL == "MA1":
            emphasis = RadioSetting(
                    "emphasis", "Emphasis",
                    RadioSettingValueBoolean(bool(_mem.emphasis)))
            emphasis.set_doc("Boosts 300 Hz to 2500 Hz mic response")
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

        if self.MODEL == "MA1":
            hsdtype = RadioSetting(
                "hsdtype", "Option Signaling",
                RadioSettingValueList(
                    HSDTYPE, current_index=_mem.hsdtype))
            hsdtype.set_doc("Option Signaling")
            mem.extra.append(hsdtype)

            pttid_mode = RadioSetting(
                "pttid_mode", "PTTID Mode",
                RadioSettingValueList(
                    PTTIDMODE, current_index=_mem.pttid_mode))
            pttid_mode.set_doc("PTTID Mode")
            mem.extra.append(pttid_mode)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        _prev_active = self.get_active("chan_active", mem.number)
        self.set_active("chan_active", mem.number, not mem.empty)
        if mem.empty or not _prev_active:
            LOG.debug("initializing memory channel %d" % mem.number)
            _mem.set_raw(self.BLANK_MEMORY)

        if mem.empty:
            return

        if self.MODEL == "MA1":
            _mem.set_raw(self.INIT_MEMORY)

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "split":
            _mem.tx_freq = mem.offset / 10
            _mem.offset = abs(mem.offset - mem.freq) / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
            _mem.offset = (mem.offset) / 10
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
            _mem.offset = (mem.offset) / 10
        elif mem.duplex == "off":
            _mem.tx_freq = 0
            _mem.offset = 0
        else:
            _mem.tx_freq = mem.freq / 10

        if self.MODEL == "MA1":
            ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
                chirp_common.split_tone_encode(mem)
            self.encode_tone(_mem.tx_tone, txmode, txtone, txpol,
                             _mem.tx_tmode)
            self.encode_tone(_mem.rx_tone, rxmode, rxtone, rxpol,
                             _mem.rx_tmode)
        else:
            _mem.tmode = self.TMODES.index(mem.tmode)
            if mem.tmode == "TSQL" or mem.tmode == "DTCS":
                _mem.sqlmode = 1
            else:
                _mem.sqlmode = 0
            _mem.ctcss = mem.rtone * 10
            _mem.dtcs = mem.dtcs
            _mem.dtcs_pol = DTCS_POLARITY.index(mem.dtcs_polarity)

        pad_char = "\x00" if self.MODEL == "MA1" else "\xFF"
        _mem.name = mem.name.ljust(6, pad_char)

        if not self.MODEL == "MA1":
            # autoset display to name if filled, else show frequency
            if mem.extra:
                # mem.extra only seems to be populated when called from edit
                # panel
                display = mem.extra["display"]
            else:
                display = None
            if mem.name:
                _mem.display = True
            else:
                _mem.display = False

        _mem.scan = self.SCAN_MODES.index(mem.skip)
        if mem.skip == "P":
            self.set_active("priority", mem.number, True)
            self.set_active("scan_enable", mem.number, True)
        elif mem.skip == "S":
            self.set_active("priority", mem.number, False)
            self.set_active("scan_enable", mem.number, False)
        elif mem.skip == "":
            self.set_active("priority", mem.number, False)
            self.set_active("scan_enable", mem.number, True)

        if self.MODEL == "MA1":
            # Set the channel width - remember we promote 20 kHz channels to FM
            # on import
            # , so don't handle them here
            if mem.mode == "AM":
                _mem.am = True
                _mem.fmdev = 0
            elif mem.mode in ["FM", "NFM"]:
                _mem.am = False
                if mem.mode == 'FM':
                    _mem.fmdev = self.CHANNEL_WIDTH_25kHz
                elif mem.mode == 'NFM':
                    _mem.fmdev = self.CHANNEL_WIDTH_12d5kHz
            else:
                LOG.error('%s: set_mem: unhandled mode: %s' % (
                    mem.name, mem.mode))
        else:
            if mem.mode == "AM":
                _mem.am = True
                _mem.fmdev = 0
            else:
                _mem.am = False
                _mem.fmdev = self.MODES.index(mem.mode)

        if self.MODEL == "MA1":
            if mem.power == self.POWER_LEVELS[0]:
                _mem.power = self.TXPOWER_LOW
            elif mem.power == self.POWER_LEVELS[1]:
                _mem.power = self.TXPOWER_MED
            elif mem.power == self.POWER_LEVELS[2]:
                _mem.power = self.TXPOWER_HIGH
            else:
                LOG.error('%s: set_mem: unhandled power level: %s' %
                          (mem.name, mem.power))
        else:
            if mem.power:
                _mem.power = self.POWER_LEVELS.index(mem.power)
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
        basic.append(RadioSetting(
                "beep", "Beep",
                RadioSettingValueBoolean(_settings.beep)))
        basic.append(RadioSetting(
                "beep_vol", "Beep Volume",
                RadioSettingValueInteger(0, 15, _settings.beep_vol)))
        if not self.MODEL == "MA1":
            basic.append(RadioSetting(
                    "keylock", "Key Lock",
                    RadioSettingValueBoolean(_settings.keylock)))
        basic.append(RadioSetting(
                "ani_display", "ANI Display",
                RadioSettingValueBoolean(_settings.ani_display)))
        basic.append(RadioSetting(
                "auto_xfer", "Auto Transfer",
                RadioSettingValueBoolean(_settings.auto_xfer)))
        if not self.MODEL == "MA1":
            basic.append(RadioSetting(
                    "auto_contact", "Auto Contact Always Remind",
                    RadioSettingValueBoolean(_settings.auto_contact)))
        basic.append(RadioSetting(
                "auto_am", "Auto AM",
                RadioSettingValueBoolean(_settings.auto_am)))
        if not self.MODEL == "MA1":
            basic.append(RadioSetting(
                    "left_sql", "Left Squelch",
                    RadioSettingValueList(
                        SQLPRESET, current_index=_settings.left_sql)))
            basic.append(RadioSetting(
                    "right_sql", "Right Squelch",
                    RadioSettingValueList(
                        SQLPRESET, current_index=_settings.right_sql)))
#      basic.append(RadioSetting("apo", "Auto Power off (0.1h)",
#              RadioSettingValueInteger(0, 20, _settings.apo)))
        if self.MODEL == "MA1":
            opts = ["Off"] + ["%0.1f" % (t / 10.0) for t in range(5, 35, 5)]
        else:
            opts = ["Off"] + ["%0.1f" % (t / 10.0) for t in range(1, 21, 1)]
        basic.append(RadioSetting(
                "apo", "Auto Power off (Hours)",
                RadioSettingValueList(opts, current_index=_settings.apo)))
        if self.MODEL == "MA1":
            opts = ["Off"] + list("12345678")
        else:
            opts = ["Off", "1", "2", "3", "Full"]
        basic.append(
            RadioSetting(
                "backlight", "Display Backlight",
                RadioSettingValueList(
                    opts, current_index=_settings.backlight)))
        if not self.MODEL == "MA1":
            opts = ["Off", "Right", "Left", "Both"]
            basic.append(RadioSetting(
                    "pttlock", "PTT Lock",
                    RadioSettingValueList(
                        opts, current_index=_settings.pttlock)))
            opts = ["Manual", "Auto"]
            basic.append(
                RadioSetting(
                    "hyper_chan", "Hyper Channel",
                    RadioSettingValueList(
                        opts, current_index=_settings.hyper_chan)))
            opts = ["Key 1", "Key 2"]
            basic.append(
                RadioSetting(
                    "right_func_key", "Right Function Key",
                    RadioSettingValueList(
                        opts, current_index=_settings.right_func_key)))
            opts = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
            basic.append(
                RadioSetting(
                    "tbst_freq", "Tone Burst Frequency",
                    RadioSettingValueList(
                        opts, current_index=_settings.tbst_freq)))
            opts = ["Off", "TX", "RX", "TX RX"]
            basic.append(
                RadioSetting(
                    "mute_mode", "Mute Mode",
                    RadioSettingValueList(
                        opts, current_index=_settings.mute_mode)))
            opts = ["MEM", "MSM"]
            scanmode = RadioSetting(
                    "scan_mode", "Scan Mode",
                    RadioSettingValueList(
                        opts, current_index=_settings.scan_mode))
            scanmode.set_doc("MEM = Normal scan, bypass channels marked skip. "
                             " MSM = Scan only channels marked priority.")
            basic.append(scanmode)
        if self.MODEL == "MA1":
            opts = ["TO", "CO", "Seek"]
        else:
            opts = ["TO", "CO"]
        basic.append(
            RadioSetting(
                "scan_resume", "Scan Resume",
                RadioSettingValueList(
                    opts, current_index=_settings.scan_resume)))
        if self.MODEL == "MA1":
            opts_choices = ["%0.1f" % (t / 10.0) for t in range(0, 51, 10)]
            opts_values = [0x00, 0x0A, 0x14, 0x1E, 0x28, 0x32]

            def apply_exit_delay_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = opts_choices.index(val)
                val = opts_values[index]
                obj.set_value(val)

            if _settings.exit_delay in opts_values:
                idx = opts_values.index(_settings.exit_delay)
            else:
                idx = opts_values.index(0x00)
            rs = RadioSettingValueList(opts_choices, current_index=idx)
            rset = RadioSetting("exit_delay",
                                "Span Transit Exit Delay", rs)
            rset.set_apply_callback(apply_exit_delay_listvalue,
                                    _settings.exit_delay)
            basic.append(rset)
        else:
            opts = ["%0.1f" % (t / 10.0) for t in range(0, 51, 1)]
            basic.append(
                RadioSetting(
                    "exit_delay", "Span Transit Exit Delay",
                    RadioSettingValueList(
                        opts, current_index=_settings.exit_delay)))
        basic.append(RadioSetting(
                "tot", "Time Out Timer (minutes)",
                RadioSettingValueInteger(0, 30, _settings.tot)))
        if not self.MODEL == "MA1":
            basic.append(RadioSetting(
                    "tot_alert", "Time Out Timer Pre Alert(seconds)",
                    RadioSettingValueInteger(0, 15, _settings.tot_alert)))
        basic.append(RadioSetting(
                "tot_rekey", "Time Out Rekey (seconds)",
                RadioSettingValueInteger(0, 30, _settings.tot_rekey)))
        if not self.MODEL == "MA1":
            basic.append(RadioSetting(
                    "tot_reset", "Time Out Reset(seconds)",
                    RadioSettingValueInteger(0, 15, _settings.tot_reset)))
        basic.append(RadioSetting(
                "p1", "P1 Function",
                RadioSettingValueList(self.MICKEYFUNC,
                                      current_index=_settings.p1)))
        basic.append(RadioSetting(
                "p2", "P2 Function",
                RadioSettingValueList(self.MICKEYFUNC,
                                      current_index=_settings.p2)))
        basic.append(RadioSetting(
                "p3", "P3 Function",
                RadioSettingValueList(self.MICKEYFUNC,
                                      current_index=_settings.p3)))
        basic.append(RadioSetting(
                "p4", "P4 Function",
                RadioSettingValueList(self.MICKEYFUNC,
                                      current_index=_settings.p4)))
        if self.MODEL == "MA1":
            def apply_pnl_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = self.PNLKEY_CHOICES.index(val)
                val = self.PNLKEY_VALUES[index]
                obj.set_value(val)

            if _settings.pnl_band in self.PNLKEY_VALUES:
                idx = self.PNLKEY_VALUES.index(_settings.pnl_band)
            else:
                idx = self.PNLKEY_VALUES.index(0x00)
            rs = RadioSettingValueList(self.PNLKEY_CHOICES, current_index=idx)
            rset = RadioSetting("pnl_band", "Panel BAND Function", rs)
            rset.set_apply_callback(apply_pnl_listvalue, _settings.pnl_band)
            basic.append(rset)
            if _settings.pnl_ctrl in self.PNLKEY_VALUES:
                idx = self.PNLKEY_VALUES.index(_settings.pnl_ctrl)
            else:
                idx = self.PNLKEY_VALUES.index(0x01)
            rs = RadioSettingValueList(self.PNLKEY_CHOICES, current_index=idx)
            rset = RadioSetting("pnl_ctrl", "Panel CTRL Function", rs)
            rset.set_apply_callback(apply_pnl_listvalue, _settings.pnl_ctrl)
            basic.append(rset)
            if _settings.pnl_m in self.PNLKEY_VALUES:
                idx = self.PNLKEY_VALUES.index(_settings.pnl_m)
            else:
                idx = self.PNLKEY_VALUES.index(0x02)
            rs = RadioSettingValueList(self.PNLKEY_CHOICES, current_index=idx)
            rset = RadioSetting("pnl_m", "Panel M Function", rs)
            rset.set_apply_callback(apply_pnl_listvalue, _settings.pnl_m)
            basic.append(rset)
        # opts = ["0", "1"]
        # basic.append(RadioSetting("x", "Desc",
        #       RadioSettingValueList(opts, opts[_settings.x])))
        if self.MODEL == "MA1":
            opts = ["Cross Band", "A TX/B RX", "A RX/B TX"]
            basic.append(RadioSetting(
                    "repeater_mode", "Repeater Mode",
                    RadioSettingValueList(
                        opts, current_index=_settings.repeater_mode)))
            basic.append(RadioSetting(
                    "dtmf_keylock", "DTMF Key Lock",
                    RadioSettingValueBoolean(
                        _settings.dtmf_keylock)))
            autobright = RadioSetting(
                    "auto_brightness", "Auto Brightness",
                    RadioSettingValueBoolean(
                        _settings.auto_brightness))
            autobright.set_doc("Auto Brightness. Requires 'Display Backlight' "
                               "set to 1, 2 or 3 to enable.")
            basic.append(autobright)
            basic.append(RadioSetting(
                    "non_subvoice_tail", "Non Subvoice Tail",
                    RadioSettingValueBoolean(
                        _settings.non_subvoice_tail)))
            opts = ["Auto"] + list("1234567")
            if _settings.mic_gain >= len(opts):
                val = 0x00
            else:
                val = _settings.mic_gain
            basic.append(RadioSetting(
                    "mic_gain", "Mic Gain",
                    RadioSettingValueList(
                        opts, current_index=val)))
            txanc = RadioSetting(
                    "txanc", "TX ANC",
                    RadioSettingValueBoolean(
                        _settings.txanc))
            txanc.set_doc("Transmit/uplink Noise Cancellation.")
            basic.append(txanc)
            opts = ["Off"] + list("1234")
            if _settings.vox >= len(opts):
                val = 0x00
            else:
                val = _settings.vox
            basic.append(RadioSetting(
                    "vox", "VOX",
                    RadioSettingValueList(
                        opts, current_index=val)))

            MA1_CHARSET = chirp_common.CHARSET_ALPHANUMERIC + \
                "!\"#$%&'()*+,-./:;<=>?@"

            # Clean/validate for the UI: uppercase,
            #                            replace invalid chars with space,
            #                            truncate
            def _cleanScreenText(value):
                return "".join(c if c in MA1_CHARSET else " "
                               for c in str(value).upper())[:6]

            # Apply: pad to device width when actually storing
            def apply_screentext(setting):
                _settings.screen_text = _cleanScreenText(setting.value
                                                         ).ljust(6, '\x00')

            # Initialize safely
            _text = str(_settings.screen_text).rstrip('\x00\x20\xFF')
            initial = _cleanScreenText(_text)

            rsvs = RadioSettingValueString(0, 6, initial, False, MA1_CHARSET)
            rsvs.set_validate_callback(_cleanScreenText)

            rs = RadioSetting("screen_text", "Screen Text", rsvs)
            rs.set_apply_callback(apply_screentext)
            basic.append(rs)

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

        mm = int(_info.prog_mon)
        dd = int(_info.prog_day)
        yy = int(_info.prog_yr)

        Valid_Date = isValidDate(mm, dd, yy)

        if Valid_Date:
            progdate = "%d/%d/%d" % (mm, dd, yy)
        else:
            progdate = "Invalid"
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

                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    element.run_apply_callback()
                else:
                    LOG.debug(
                        "Setting %s(%s) <= %s" % (setting, oldval, newval)
                    )
                    setattr(_settings, setting, newval)
            except Exception:
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
    _settings_offset = 0xCB07 + _mmap_offset
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
        radio.pipe.write(b"\x02PROGRA")
        ack = radio.pipe.read(1)
        if ack != b"A":
            util.hexprint(ack)
            raise errors.RadioError("Radio did not ACK first command: %x"
                                    % ord(ack))
    except:
        LOG.debug(util.hexprint(ack))
        raise errors.RadioError("Unable to communicate with the radio")

    radio.pipe.write(b"M\x02")
    ident = radio.pipe.read(16)
    if len(ident) == 15:
        # Newer (?) firmware doesn't send the last byte of the model string,
        # but it's always a 0x00, so add it back for consistency.
        ident += b'\x00'
        LOG.debug('Radio sent 15 byte model string; padding for consistency')
    radio.pipe.write(b"A")
    r = radio.pipe.read(1)
    if r != b"A":
        raise errors.RadioError("Ack failed")
    return ident


def _download(radio, memsize=0x10000, blocksize=0x80):
    """Download from TYT TH-9800"""
    data = _identify(radio)
    LOG.info("ident:\n%s", util.hexprint(data))
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
    """Upload to TYT TH-9800"""
    data = _identify(radio)

    radio.pipe.timeout = 1

    if data != radio._mmap[0:radio._mmap_offset]:
        raise errors.RadioError(
            "Model mismatch: \n%s\n%s" %
            (util.hexprint(data),
             util.hexprint(radio._mmap[0:radio._mmap_offset])))
    # in the factory software they update the last program date when
    # they upload, So let's do the same
    today = date.today()
    y = today.year
    m = today.month
    d = today.day
    _info = radio._memobj.info

    ly = int(_info.prog_yr)
    lm = int(_info.prog_mon)
    ld = int(_info.prog_day)

    Valid_Date = isValidDate(lm, ld, ly)

    if Valid_Date:
        LOG.debug("Updating last program date:%d/%d/%d" % (lm, ld, ly))
    else:
        LOG.debug("Updating last program date: Invalid")
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
    LOG.debug("final:\n%s" % util.hexprint(final_data))


@directory.register
class TYTTH9800Radio(TYTTH9800Base, chirp_common.CloneModeRadio,
                     chirp_common.ExperimentalRadio):
    VENDOR = "TYT"
    MODEL = "TH-9800"
    BAUD_RATE = 38400

    _memsize = 65296
    _mmap_offset = 0x0010
    _scanlimits_offset = 0xC800 + _mmap_offset
    _settings_offset = 0xCB07 + _mmap_offset
    _chan_active_offset = 0xCB80 + _mmap_offset
    _info_offset = 0xfe00 + _mmap_offset

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) != cls._memsize:
            return False
        # TYT set this model for TH-7800 _AND_ TH-9800
        if not filedata[0xfe18:0xfe1e] == b"TH9800":
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


@directory.register
class RetevisMA1Radio(TYTTH9800Base, chirp_common.CloneModeRadio,
                      chirp_common.ExperimentalRadio):
    VENDOR = "Retevis"
    MODEL = "MA1"
    BAUD_RATE = 38400

    _memsize = 65296
    _mmap_offset = 0x0010
    _scanlimits_offset = 0xC800 + _mmap_offset
    _settings_offset = 0xCB07 + _mmap_offset
    _chan_active_offset = 0xCB80 + _mmap_offset
    _info_offset = 0xfe00 + _mmap_offset

    _upper = 999

    MA1_MEM_FORMAT = """
    struct mem {
      lbcd rx_freq[4];
      lbcd tx_freq[4];
      lbcd rx_tone[2];
      lbcd tx_tone[2];
      u8 power:2,
         BeatShift:1,
         unknown0a:4,
         scan:1;
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
      u8 tx_tmode:2,
         bclo:2,
         rx_tmode:2,
         unknown2a:2;
      lbcd offset[4];
      u8 hsdtype:2,     // off, 2-tone, 5-tone, dtmf
         unknown5a:1,
         am:1,
         unknown5b:4;
      u8 unknown6a:5,
         pttid_mode:3;
      u8 unknown6[2];
      char name[6];
      u8 empty[2];
    };
    """

    BLANK_MEMORY = "\xFF" * 32
    INIT_MEMORY = "\xFF" * 12 + "\xC0\x08\x00\x00" + \
                  "\x00" * 6 + "\xFF\xFF" + "\x00" * 6 + "\xFF\xFF"
    SCAN_MODES = ["", "S"]
    MODES = ["FM", "NFM"]
    TMODES = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']

    TXPOWER_LOW = 0x00
    TXPOWER_MED = 0x01
    TXPOWER_HIGH = 0x03

    CHANNEL_WIDTH_25kHz = 0x00
    CHANNEL_WIDTH_20kHz = 0x01
    CHANNEL_WIDTH_12d5kHz = 0x02

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                    chirp_common.PowerLevel("Mid", watts=20.00),
                    chirp_common.PowerLevel("High", watts=50.00)]
    BUSY_LOCK = ["Off", "Carrier", "CTCSS/DCS"]
    MICKEYFUNC = ["FR.BAND", "CTRL", "MONI", "MENU", "MUTE", "SHIFT", "DUAL",
                  "M>V", "VFO", "MR", "CALL", "MHZ", "TONE", "REV", "LOW",
                  "LOCK", "A/B", "Enter", "1750"]
    PNLKEY_CHOICES = MICKEYFUNC[:8] + MICKEYFUNC[18:]
    PNLKEY_VALUES = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x12]

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
         'This is experimental support for MA1 '
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

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, self._upper)
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.valid_tuning_steps = STEPS
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = self.TMODES
        rf.valid_cross_modes = ['Tone->Tone',
                                'Tone->DTCS',
                                'DTCS->Tone',
                                'DTCS->DTCS',
                                'DTCS->',
                                '->DTCS',
                                '->Tone']
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "#*-+"
        rf.valid_bands = [(108000000, 134000000),
                          (134000000, 180000000),
                          (400000000, 512000000)]
        rf.valid_skips = self.SCAN_MODES
        rf.valid_modes = self.MODES + ["AM"]
        rf.valid_name_length = 6
        rf.has_settings = True
        return rf

    def process_mmap(self):
        fmt = (self.MA1_MEM_FORMAT + MEM_FORMAT)
        self._memobj = bitwise.parse(
            fmt % (self._mmap_offset,
                   self._upper,
                   self._scanlimits_offset,
                   self._settings_offset,
                   self._chan_active_offset,
                   self._info_offset
                   ), self._mmap)
