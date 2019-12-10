# Copyright 2018 Rhett Robinson <rrhett@gmail.com>
# Added Settings support, 6/2019 Rick DeWitt <aa0rd@yahoo.com>
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
import logging
from chirp.drivers import icf
from chirp import chirp_common, util, directory, bitwise, memmap
from chirp import errors
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, InvalidValueError
from textwrap import dedent

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  u24  freq_flags:6
       freq:18;
  u16  offset;
  u8   tune_step:4,
       unknown5:2,
       mode:2;
  u8   unknown6:2,
       rtone:6;
  u8   unknown7:2,
       ctone:6;
  u8   unknown8;
  u8   dtcs;
  u8   tmode:4,
       duplex:2,
       dtcs_polarity:2;
  char name[6];
} memory[1002];

#seekto 0x42c0;
u8 used_flags[125];

#seekto 0x433e;
u8 skip_flags[125];
u8 pskip_flags[125];

#seekto 0x4440;
struct {
u8 bank;
u8 index;
} bank_info[1000];

#seekto 0x4c40;
struct {
char com[16];
} comment;

#seekto 0x4c50;
struct {
char name[6];
} bank_names[10];

#seekto 0x4cc8;
struct{
u8 codes[24];
} dtmfcode[16];

#seekto 0x4c8c;
struct {
char nam[6];
} pslnam[10];

#seekto 0x4e80;
struct {
u24  loflags:6
     lofreq:18;
u24  hiflags:6
     hifreq:18;
u8  flag:4
    mode:4;
u8  tstp;
char name[6];
} pgmscanedge[25];

#seekto 0x5000;
struct {
u8  aprichn;
u8  bprichn;
u8  autopwr;
u8  unk5003;
u8  autorptr;
u8  rmtmic;    // 0x05005
u8  pttlock;
u8  bcl;
u8  tot;
u8  actband;
u8  unk500a;
u8  dialspdup;
u8  toneburst;
u8  micgain;
u8  unk500e;
u8  civaddr;
u8  civbaud;
u8  civtcvr;
u8  sqlatt;
u8  sqldly;
u8  unk5014a:4
    fanspeed:4;
u8  unk5015;
u8  bthvox;
u8  bthvoxlvl;
u8  bthvoxdly;
u8  bthvoxtot;  // 0x05019
u8  btoothon;
u8  btoothauto;
u8  bthdset;
u8  bthhdpsav;
u8  bth1ptt;    // 0x0501e
u8  bthpttbeep;
u8  bthcustbeep;    // 0x05020
u8  ascanpause;
u8  bscanpause;
u8  ascanresume;
u8  bscanresume;
u8  dtmfspd;
u8  unk5026;
u8  awxalert;
u8  bwxalert;
u8  aprgskpscn;
u8  bprgskpscn;
u8  memname;
u8  contrast;
u8  autodimtot;
u8  autodim;
u8  unk502f;
u8  backlight;
u8  unk5031;
u8  unk5032;
u8  openmsg;
u8  beeplvl;    // 0x05034
u8  keybeep;
u8  scanstpbeep;
u8  bandedgbeep;
u8  subandmute;
u8  atmpskiptym;
u8  btmpskiptym;
u32 vfohome;
u8  vfohomeset;
u16 homech;
u8  mickyrxf1;
u8  mickyrxf2;
u8  mickyrxup;
u8  mickyrxdn;  // 0x05045
u8  bthplaykey;
u8  bthfwdkey;
u8  bthrwdkey;
u8  mickytxf1;
u8  mickytxf2;
u8  mickytxup;
u8  mickytxdn;
u8  unk504d;
u8  unk504e;
u8  unk504f;
u8  homebeep;
u8  bthfctn;
u8  unk5052;
u8  unk5053;
u8  ifxchg;
u8  airbandch;
u8  vhfpower;
u8  uhfpower;
u8  unk5058;
u8  unk5059;
u8  unk505a;
u8  unk505b;
u8  unk505c;
u8  unk505d;
u8  unk505e:6
    rpthangup:1
    unk505e2:1;
u8  unk505f;
} settings;

#seekto 0x5220;
struct {
u16  left_memory;
u16  right_memory;
} initmem;

#seekto 0x523e;
struct {
u8  awxchan;
u8  bwxchan;
} abwx;

#seekto 0x5250;
struct {
u8  alnk[2];
u16 unk5252;
u8  blnk[2];
} banklink;

#seekto 0x5258;
struct {
u8  msk[4];
} pslgrps[25];

#seekto 0x5280;
u16  mem_writes_count;
"""

# Guessing some of these intermediate values are with the Pocket Beep function,
# but I haven't reliably reproduced these.
TMODES = ["", "Tone", "??0", "TSQL", "??1", "DTCS", "TSQL-R", "DTCS-R",
          "DTC.OFF", "TON.DTC", "DTC.TSQ", "TON.TSQ"]
DUPLEX = ["", "-", "+"]
MODES = ["FM", "NFM", "AM", "NAM"]
DTCSP = ["NN", "NR", "RN", "RR"]
DTMF_CHARS = list("0123456789ABCD*#")
BANKLINK_CHARS = list("ABCDEFGHIJ")
AUTOREPEATER = ["OFF", "DUP", "DUP.TON"]
MICKEYOPTS = ["Off", "Up", "Down", "Vol Up", "Vol Down", "SQL Up",
              "SQL Down", "Monitor", "Call", "MR (Ch 0)", "MR (Ch 1)",
              "VFO/MR", "Home Chan", "Band/Bank", "Scan", "Temp Skip",
              "Main", "Mode", "Low", "Dup", "Priority", "Tone", "MW", "Mute",
              "T-Call", "DTMF Direct"]


class IC2730Bank(icf.IcomNamedBank):
    """An IC2730 bank"""
    def get_name(self):
        _banks = self._model._radio._memobj.bank_names
        return str(_banks[self.index].name).rstrip()

    def set_name(self, name):
        _banks = self._model._radio._memobj.bank_names
        _banks[self.index].name = str(name).ljust(6)[:6]


def _get_special():
    special = {"C0": -2, "C1": -1}
    return special


def _resolve_memory_number(number):
    if isinstance(number, str):
        return _get_special()[number]
    else:
        return number


def _wipe_memory(mem, char):
    mem.set_raw(char * (mem.size() // 8))


@directory.register
class IC2730Radio(icf.IcomRawCloneModeRadio):
    """Icom IC-2730A"""
    VENDOR = "Icom"
    MODEL = "IC-2730A"

    _model = "\x35\x98\x00\x01"
    _memsize = 21312  # 0x5340
    _endframe = "Icom Inc\x2e4E"

    _ranges = [(0x0000, 0x5300, 64),
               (0x5300, 0x5310, 16),
               (0x5310, 0x5340, 48)]

    _num_banks = 10
    _bank_class = IC2730Bank
    _can_hispeed = True

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = ('Click the Special Channels tab on the main screen to '
                   'access the C0 and C1 frequencies.\n')

        rp.pre_download = _(dedent("""\
            Follow these instructions to download your config:

            1 - Turn off your radio
            2 - Connect your interface cable to the Speaker-2 jack
            3 - Turn on your radio
            4 - Radio > Download from radio
            5 - Disconnect the interface cable! Otherwise there will be
                no right-side audio!
            """))
        rp.pre_upload = _(dedent("""\
            Follow these instructions to upload your config:

            1 - Turn off your radio
            2 - Connect your interface cable to the Speaker-2 jack
            3 - Turn on your radio
            4 - Radio > Upload to radio
            5 - Disconnect the interface cable, otherwise there will be
                no right-side audio!
            6 - Cycle power on the radio to exit clone mode
            """))
        return rp

    def _get_bank(self, loc):
        _bank = self._memobj.bank_info[loc]
        _bank.bank = _bank.bank & 0x1F      # Bad index filter, fix issue #7031
        if _bank.bank == 0x1F:
            return None
        else:
            return _bank.bank

    def _set_bank(self, loc, bank):
        _bank = self._memobj.bank_info[loc]
        if bank is None:
            _bank.bank = 0x1F
        else:
            _bank.bank = bank

    def _get_bank_index(self, loc):
        _bank = self._memobj.bank_info[loc]
        return _bank.index

    def _set_bank_index(self, loc, index):
        _bank = self._memobj.bank_info[loc]
        _bank.index = index

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank_index = True
        rf.has_bank_names = True
        rf.requires_call_lists = False
        rf.memory_bounds = (0, 999)
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(set(DUPLEX))
        rf.valid_tuning_steps = list(chirp_common.TUNING_STEPS[0:9])
        rf.valid_bands = [(118000000, 174000000),
                          (375000000, 550000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 6
        rf.valid_special_chans = sorted(_get_special().keys())

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = _resolve_memory_number(number)
        if mem.number >= 0:
            _mem = self._memobj.memory[mem.number]
            bitpos = (1 << (number % 8))
            bytepos = number / 8
            _used = self._memobj.used_flags[bytepos]
            is_used = ((_used & bitpos) == 0)

            _skip = self._memobj.skip_flags[bytepos]
            _pskip = self._memobj.pskip_flags[bytepos]
            if _skip & bitpos:
                mem.skip = "S"
            elif _pskip & bitpos:
                mem.skip = "P"
            if not is_used:
                mem.empty = True
                return mem
        else:   # C0, C1 specials
            _mem = self._memobj.memory[1002 + mem.number]

        # _mem.freq is stored as a multiple of a tuning step
        frequency_flags = int(_mem.freq_flags)
        frequency_multiplier = 5000
        offset_multiplier = 5000
        if frequency_flags & 0x08:
            frequency_multiplier = 6250
        if frequency_flags & 0x01:
            offset_multiplier = 6250
        if frequency_flags & 0x10:
            frequency_multiplier = 8333
        if frequency_flags & 0x02:
            offset_multiplier = 8333

        if frequency_flags & 0x10:  # fix underflow
            val = int(_mem.freq) * frequency_multiplier
            mem.freq = round(val)
        else:
            mem.freq = int(_mem.freq) * frequency_multiplier
        if frequency_flags & 0x02:
            val = int(_mem.offset) * offset_multiplier
            mem.offset = round(val)
        else:
            mem.offset = int(_mem.offset) * offset_multiplier
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.ctone = chirp_common.TONES[_mem.ctone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.dtcs_polarity = DTCSP[_mem.dtcs_polarity]
        if _mem.tune_step > 8:
            mem.tuning_step = 5.0  # Sometimes TS is garbage?
        else:
            mem.tuning_step = chirp_common.TUNING_STEPS[_mem.tune_step]
        mem.name = str(_mem.name).rstrip()
        if mem.number == -2:
            mem.name = "C0"
            mem.extd_number = "C0"
        if mem.number == -1:
            mem.name = "C1"
            mem.extd_number = "C1"

        return mem

    def set_memory(self, mem):
        if mem.number >= 0:       # Normal
            bitpos = (1 << (mem.number % 8))
            bytepos = mem.number / 8

            _mem = self._memobj.memory[mem.number]
            _used = self._memobj.used_flags[bytepos]

            was_empty = _used & bitpos

            skip = self._memobj.skip_flags[bytepos]
            pskip = self._memobj.pskip_flags[bytepos]
            if mem.skip == "S":
                skip |= bitpos
            else:
                skip &= ~bitpos
            if mem.skip == "P":
                pskip |= bitpos
            else:
                pskip &= ~bitpos

            if mem.empty:
                _used |= bitpos
                _wipe_memory(_mem, "\xFF")
                self._set_bank(mem.number, None)
                return

            _used &= ~bitpos
            if was_empty:
                _wipe_memory(_mem, "\x00")
            _mem.name = mem.name.ljust(6)
        else:       # Specials: -2 and -1
            _mem = self._memobj.memory[1002 + mem.number]

        # Common to both types
        frequency_flags = 0x00
        frequency_multiplier = 5000
        offset_multiplier = 5000
        if mem.freq % 5000 != 0 and mem.freq % 6250 == 0:
            frequency_flags |= 0x08
            frequency_multiplier = 6250
        elif mem.freq % 8333 == 0:
            frequency_flags |= 0x10
            frequency_multiplier = 8333
        if mem.offset % 5000 != 0 and mem.offset % 6250 == 0:
            frequency_flags |= 0x01
            offset_multiplier = 6250
        elif mem.offset % 8333 == 0:
            frequency_flags |= 0x02
            offset_multiplier = 8333
        _mem.freq = mem.freq / frequency_multiplier
        _mem.offset = mem.offset / offset_multiplier
        _mem.freq_flags = frequency_flags
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.mode = MODES.index(mem.mode)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCSP.index(mem.dtcs_polarity)
        _mem.tune_step = chirp_common.TUNING_STEPS.index(mem.tuning_step)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_settings(self):
        """Translate the MEM_FORMAT structs into settings in the UI"""
        # Define mem struct write-back shortcuts
        _sets = self._memobj.settings
        _cmnt = self._memobj.comment
        _wxch = self._memobj.abwx
        _dtm = self._memobj.dtmfcode
        _pses = self._memobj.pgmscanedge
        _bklk = self._memobj.banklink

        basic = RadioSettingGroup("basic", "Basic Settings")
        mickey = RadioSettingGroup("mickey", "Microphone Keys")
        bluet = RadioSettingGroup("bluet", "Bluetooth")
        disp = RadioSettingGroup("disp", "Display")
        sound = RadioSettingGroup("sound", "Sounds")
        dtmf = RadioSettingGroup("dtmf", "DTMF Codes")
        abset = RadioSettingGroup("abset", "A/B Band Settings")
        edges = RadioSettingGroup("edges", "Program Scan Edges")
        pslnk = RadioSettingGroup("pslnk", "Program Scan Links")
        other = RadioSettingGroup("other", "Other Settings")

        group = RadioSettings(basic, disp, sound, mickey, dtmf,
                              abset, bluet, edges, pslnk, other)

        def mic_keys(setting, obj, atrb):
            """ Callback to set subset of mic key options """
            stx = str(setting.value)
            value = MICKEYOPTS.index(stx)
            setattr(obj, atrb, value)
            return

        def hex_val(setting, obj, atrb):
            """ Callback to store string as hex values """
            value = int(str(setting.value), 16)
            setattr(obj, atrb, value)
            return

        def unpack_str(codestr):
            """Convert u8 DTMF array to a string: NOT a callback."""
            stx = ""
            for i in range(0, 24):    # unpack up to ff
                if codestr[i] != 0xff:
                    if codestr[i] == 0x0E:
                        stx += "#"
                    elif codestr[i] == 0x0F:
                        stx += "*"
                    else:
                        stx += format(int(codestr[i]), '0X')
            return stx

        def pack_chars(setting, obj, atrb, ndx):
            """Callback to build 0-9,A-D,*# nibble array from string"""
            # String will be f padded to 24 bytes
            # Chars are stored as hex values
            ary = []
            stx = str(setting.value).upper()
            stx = stx.strip()       # trim spaces
            # Remove illegal characters first
            sty = ""
            for j in range(0, len(stx)):
                if stx[j] in DTMF_CHARS:
                    sty += stx[j]
            for j in range(0, 24):
                if j < len(sty):
                    if sty[j] == "#":
                        chrv = 0xE
                    elif sty[j] == "*":
                        chrv = 0xF
                    else:
                        chrv = int(sty[j], 16)
                else:   # pad to 24 bytes
                    chrv = 0xFF
                ary.append(chrv)    # append byte
            setattr(obj[ndx], atrb, ary)
            return

        def myset_comment(setting, obj, atrb, knt):
            """ Callback to create space-padded char array"""
            stx = str(setting.value)
            for i in range(0, knt):
                if i > len(stx):
                    str.append(0x20)
            setattr(obj, atrb, stx)
            return

        def myset_psnam(setting, obj, ndx, atrb, knt):
            """ Callback to generate space-padded, uppercase char array """
            # This sub also is specific to object arrays
            stx = str(setting.value).upper()
            for i in range(0, knt):
                if i > len(stx):
                    str.append(0x20)
            setattr(obj[ndx], atrb, stx)
            return

        def myset_frqflgs(setting, obj, ndx, flg, frq):
            """ Callback to gen flag/freq pairs """
            vfrq = float(str(setting.value))
            vfrq = int(vfrq * 1000000)
            vflg = 0x10
            if vfrq % 6250 == 0:
                vflg = 0x08
                vfrq = int(vfrq / 6250)
            elif vfrq % 5000 == 0:
                vflg = 0
                vfrq = int(vfrq / 5000)
            else:
                vfrq = int(vfrq / 8333)
            setattr(obj[ndx], flg, vflg)
            setattr(obj[ndx], frq, vfrq)
            return

        def banklink(ary):
            """ Sub to generate A-J string from 2-byte bit pattern """
            stx = ""
            for kx in range(0, 10):
                if kx < 8:
                    val = ary[0]
                    msk = 1 << kx
                else:
                    val = ary[1]
                    msk = 1 << (kx - 8)
                if val & msk:
                    stx += chr(kx + 65)
                else:
                    stx += "_"
            return stx

        def myset_banklink(setting, obj, atrb):
            """Callback to create 10-bit, u8[2] array from 10 char string"""
            stx = str(setting.value).upper()
            ary = [0, 0]
            for kx in range(0, 10):
                if stx[kx] == chr(kx + 65):
                    if kx < 8:
                        ary[0] = ary[0] + (1 << kx)
                    else:
                        ary[1] = ary[1] + (1 << (kx - 8))
            setattr(obj, atrb, ary)
            return

        def myset_tsopt(setting, obj, ndx, atrb, bx):
            """ Callback to set scan Edge tstep """
            stx = str(setting.value)
            flg = 0
            if stx == "-":
                val = 0xff
            else:
                if bx == 1:  # Air band
                    if stx == "Auto":
                        val = 0xe
                    elif stx == "25k":
                        val = 8
                    elif stx == "8.33k":
                        val = 2
                else:       # VHF or UHF
                    optx = ["-", "5k", "6.25k", "10k", "12.5k", "15k",
                            "20k", "25k", "30k", "50k"]
                    val = optx.index(stx) + 1
            setattr(obj[ndx], atrb, val)
            # and set flag
            setattr(obj[ndx], "flag", flg)
            return

        def myset_mdopt(setting, obj, ndx, atrb, bx):
            """ Callback to set Scan Edge mode """
            stx = str(setting.value)
            if stx == "-":
                val = 0xf
            elif stx == "FM":
                val = 0
            else:
                val = 1
            setattr(obj[ndx], atrb, val)
            return

        def myset_bitmask(setting, obj, ndx, atrb, knt):
            """ Callback to gnerate byte-array bitmask from string"""
            # knt is BIT count to process
            lsx = str(setting.value).strip().split(",")
            for kx in range(0, len(lsx)):
                try:
                    lsx[kx] = int(lsx[kx])
                except Exception:
                    lsx[kx] = -99   # will nop
            ary = [0, 0, 0, 0xfe]
            for kx in range(0, knt):
                if kx < 8:
                    if kx in lsx:
                        ary[0] += 1 << kx
                elif kx >= 8 and kx < 16:
                    if kx in lsx:
                        ary[1] += 1 << (kx - 8)
                elif kx >= 16 and kx < 24:
                    if kx in lsx:
                        ary[2] += 1 << (kx - 16)
                else:
                    if kx in lsx:   # only bit 25
                        ary[3] += 1
            setattr(obj[ndx], atrb, ary)
            return

        # --- Basic
        options = ["Off", "S-Meter Squelch", "ATT"]
        rx = RadioSettingValueList(options, options[_sets.sqlatt])
        rset = RadioSetting("settings.sqlatt", "Squelch/ATT", rx)
        basic.append(rset)

        options = ["Short", "Long"]
        rx = RadioSettingValueList(options, options[_sets.sqldly])
        rset = RadioSetting("settings.sqldly", "Squelch Delay", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.pttlock))
        rset = RadioSetting("settings.pttlock", "PTT Lockout", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bcl))
        rset = RadioSetting("settings.bcl", "Busy Channel Lockout", rx)
        basic.append(rset)

        options = ["Off", "1m", "3m", "5m", "10m", "15m", "30m"]
        rx = RadioSettingValueList(options, options[_sets.tot])
        rset = RadioSetting("settings.tot", "Tx Timeout", rx)
        basic.append(rset)

        val = int(_sets.vfohome)
        if val == 0xffff:
            val = 0
        val = val / 1000000.0
        rx = RadioSettingValueFloat(0.0, 550.0, val, 0.005, 4)
        rx.set_mutable(False)
        rset = RadioSetting("settings.vfohome", "Home VFO (Read-Only)", rx)
        basic.append(rset)

        val = _sets.homech
        if val == 0xffff:
            val = -1
        rx = RadioSettingValueInteger(-1, 999, val)
        rx.set_mutable(False)
        rset = RadioSetting("settings.homech",
                            "Home Channel (Read-Only)", rx)
        basic.append(rset)

        options = ["1", "2", "3", "4"]
        rx = RadioSettingValueList(options, options[_sets.micgain])
        rset = RadioSetting("settings.micgain", "Microphone Gain", rx)
        basic.append(rset)

        _bmem = self._memobj.initmem
        rx = RadioSettingValueInteger(0, 999, _bmem.left_memory)
        rset = RadioSetting("initmem.left_memory",
                            "Left Bank Initial Mem Chan", rx)
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 999, _bmem.right_memory)
        rset = RadioSetting("initmem.right_memory",
                            "Right Bank Initial Mem Chan", rx)
        basic.append(rset)

        stx = ""
        for i in range(0, 16):
            stx += chr(_cmnt.com[i])
        stx = stx.rstrip()
        rx = RadioSettingValueString(0, 16, stx)
        rset = RadioSetting("comment.com", "Comment (16 chars)", rx)
        rset.set_apply_callback(myset_comment, _cmnt, "com", 16)
        basic.append(rset)

        # --- Other
        rset = RadioSetting("drv_clone_speed", "Use Hi-Speed Clone",
                            RadioSettingValueBoolean(self._can_hispeed))
        other.append(rset)

        options = ["Single", "All", "Ham"]
        rx = RadioSettingValueList(options, options[_sets.actband])
        rset = RadioSetting("settings.actband", "Active Band", rx)
        other.append(rset)

        options = ["Slow", "Mid", "Fast", "Auto"]
        rx = RadioSettingValueList(options, options[_sets.fanspeed])
        rset = RadioSetting("settings.fanspeed", "Fan Speed", rx)
        other.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.dialspdup))
        rset = RadioSetting("settings.dialspdup", "Dial Speed-Up", rx)
        other.append(rset)

        options = ["Off", "On(Dup)", "On(Dup+Tone)"]
        rx = RadioSettingValueList(options, options[_sets.autorptr])
        rset = RadioSetting("settings.autorptr", "Auto Repeater", rx)
        other.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.rmtmic))
        rset = RadioSetting("settings.rmtmic",
                            "One-Touch PTT (Remote Mic)", rx)
        other.append(rset)

        options = ["Low", "Mid", "High"]
        rx = RadioSettingValueList(options, options[_sets.vhfpower])
        rset = RadioSetting("settings.vhfpower", "VHF Power Default", rx)
        other.append(rset)

        rx = RadioSettingValueList(options, options[_sets.uhfpower])
        rset = RadioSetting("settings.uhfpower", "UHF Power Default", rx)
        other.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.toneburst))
        rset = RadioSetting("settings.toneburst", "1750 Htz Tone Burst", rx)
        other.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.ifxchg))
        rset = RadioSetting("settings.ifxchg", "IF Exchange", rx)
        other.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.rpthangup))
        rset = RadioSetting("settings.rpthangup",
                            "Repeater Hang up Timeout", rx)
        other.append(rset)

        stx = str(_sets.civaddr)[2:]    # Hex value
        rx = RadioSettingValueString(1, 2, stx)
        rset = RadioSetting("settings.civaddr", "CI-V Address (90)", rx)
        rset.set_apply_callback(hex_val, _sets, "civaddr")
        other.append(rset)

        options = ["1200", "2400", "4800", "9600", "19200", "Auto"]
        rx = RadioSettingValueList(options, options[_sets.civbaud])
        rset = RadioSetting("settings.civbaud", "CI-V Baud Rate (bps)", rx)
        other.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.civtcvr))
        rset = RadioSetting("settings.civtcvr", "CI-V Transceive", rx)
        other.append(rset)

        # A/B Band Settings
        options = ["Off", "On", "Bell"]
        rx = RadioSettingValueList(options, options[_sets.aprichn])
        rset = RadioSetting("settings.aprichn",
                            "A Band: VFO Priority Watch Mode", rx)
        abset.append(rset)

        options = ["2", "4", "6", "8", "10", "12", "14",
                   "16", "18", "20", "Hold"]
        rx = RadioSettingValueList(options, options[_sets.ascanpause])
        rset = RadioSetting("settings.ascanpause",
                            "-- A Band: Scan Pause Time (Secs)", rx)
        abset.append(rset)

        options = ["0", "1", "2", "3", "4", "5", "Hold"]
        rx = RadioSettingValueList(options, options[_sets.ascanresume])
        rset = RadioSetting("settings.ascanresume",
                            "-- A Band: Scan Resume Time (Secs)", rx)
        abset.append(rset)

        options = ["5", "10", "15"]
        rx = RadioSettingValueList(options, options[_sets.atmpskiptym])
        rset = RadioSetting("settings.atmpskiptym",
                            "-- A Band: Temp Skip Time (Secs)", rx)
        abset.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.aprgskpscn))
        rset = RadioSetting("settings.aprgskpscn",
                            "-- A Band: Program Skip Scan", rx)
        abset.append(rset)

        rx = RadioSettingValueString(10, 10, banklink(_bklk.alnk))
        rset = RadioSetting("banklink.alnk",
                            "-- A Band Banklink (use _ to skip)", rx)
        rset.set_apply_callback(myset_banklink, _bklk, "alnk")
        abset.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.awxalert))
        rset = RadioSetting("settings.awxalert",
                            "-- A Band: Weather Alert", rx)
        abset.append(rset)

        # Use list for Wx chans since chan 1 = index 0
        options = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
        rx = RadioSettingValueList(options, options[_wxch.awxchan])
        rset = RadioSetting("abwx.awxchan", "-- A Band: Weather Channel", rx)
        abset.append(rset)

        options = ["Off", "On", "Bell"]
        rx = RadioSettingValueList(options, options[_sets.bprichn])
        rset = RadioSetting("settings.bprichn",
                            "B Band: VFO Priority Watch Mode", rx)
        abset.append(rset)

        options = ["2", "4", "6", "8", "10", "12", "14",
                   "16", "18", "20", "Hold"]
        rx = RadioSettingValueList(options, options[_sets.bscanpause])
        rset = RadioSetting("settings.bscanpause",
                            "-- B Band: Scan Pause Time (Secs)", rx)
        abset.append(rset)

        options = ["0", "1", "2", "3", "4", "5", "Hold"]
        rx = RadioSettingValueList(options, options[_sets.bscanresume])
        rset = RadioSetting("settings.bscanresume",
                            "-- B Band: Scan Resume Time (Secs)", rx)
        abset.append(rset)

        options = ["5", "10", "15"]
        rx = RadioSettingValueList(options, options[_sets.btmpskiptym])
        rset = RadioSetting("settings.btmpskiptym",
                            "-- B Band: Temp Skip Time (Secs)", rx)
        abset.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bprgskpscn))
        rset = RadioSetting("settings.bprgskpscn",
                            "-- B Band: Program Skip Scan", rx)
        abset.append(rset)

        rx = RadioSettingValueString(10, 10, banklink(_bklk.blnk))
        rset = RadioSetting("banklink.blnk",
                            "-- B Band Banklink (use _ to skip)", rx)
        rset.set_apply_callback(myset_banklink, _bklk, "blnk")
        abset.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bwxalert))
        rset = RadioSetting("settings.bwxalert",
                            "-- B Band: Weather Alert", rx)
        abset.append(rset)

        options = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
        rx = RadioSettingValueList(options, options[_wxch.bwxchan])
        rset = RadioSetting("abwx.bwxchan", "-- B Band: Weather Channel", rx)
        abset.append(rset)

        # --- Microphone Keys
        # The Mic keys get wierd: stored values are indecis to the full
        # options list, but only a subset is valid...
        shortopts = ["Off", "Monitor", "MR (Ch 0)", "MR (Ch 1)", "Band/Bank",
                     "Scan", "Temp Skip", "Mode", "Low", "Dup", "Priority",
                     "Tone", "MW", "Mute", "DTMF Direct", "T-Call"]
        ptr = shortopts.index(MICKEYOPTS[_sets.mickyrxf1])
        rx = RadioSettingValueList(shortopts, shortopts[ptr])
        rset = RadioSetting("settings.mickyrxf1",
                            "During Rx/Standby [F-1]", rx)
        rset.set_apply_callback(mic_keys, _sets, "mickyrxf1")
        mickey.append(rset)

        ptr = shortopts.index(MICKEYOPTS[_sets.mickyrxf2])
        rx = RadioSettingValueList(shortopts, shortopts[ptr])
        rset = RadioSetting("settings.mickyrxf2",
                            "During Rx/Standby [F-2]", rx)
        rset.set_apply_callback(mic_keys, _sets, "mickyrxf2")
        mickey.append(rset)

        options = ["Off", "Low", "T-Call"]      # NOT a subset of MICKEYOPTS
        rx = RadioSettingValueList(options, options[_sets.mickytxf1])
        rset = RadioSetting("settings.mickytxf1", "During Tx [F-1]", rx)
        mickey.append(rset)

        rx = RadioSettingValueList(options, options[_sets.mickytxf2])
        rset = RadioSetting("settings.mickytxf2", "During Tx [F-2]", rx)
        mickey.append(rset)

        # These next two get the full options list
        rx = RadioSettingValueList(MICKEYOPTS, MICKEYOPTS[_sets.mickyrxup])
        rset = RadioSetting("settings.mickyrxup",
                            "During Rx/Standby [Up]", rx)
        mickey.append(rset)

        rx = RadioSettingValueList(MICKEYOPTS, MICKEYOPTS[_sets.mickyrxdn])
        rset = RadioSetting("settings.mickyrxdn",
                            "During Rx/Standby [Down]", rx)
        mickey.append(rset)

        options = ["Off", "Low", "T-Call"]
        rx = RadioSettingValueList(options, options[_sets.mickytxup])
        rset = RadioSetting("settings.mickytxup", "During Tx [Up]", rx)
        mickey.append(rset)

        rx = RadioSettingValueList(options, options[_sets.mickytxdn])
        rset = RadioSetting("settings.mickytxdn", "During Tx [Down]", rx)
        mickey.append(rset)

        # --- Bluetooth
        rx = RadioSettingValueBoolean(bool(_sets.btoothon))
        rset = RadioSetting("settings.btoothon", "Bluetooth", rx)
        bluet.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.btoothauto))
        rset = RadioSetting("settings.btoothauto", "Auto Connect", rx)
        bluet.append(rset)

        options = ["Headset Only", "Headset & Speaker"]
        rx = RadioSettingValueList(options, options[_sets.bthdset])
        rset = RadioSetting("settings.bthdset", "Headset Audio", rx)
        bluet.append(rset)

        options = ["Normal", "Microphone", "PTT (Audio:Main)",
                   "PTT(Audio:Controller)"]
        rx = RadioSettingValueList(options, options[_sets.bthfctn])
        rset = RadioSetting("settings.bthfctn", "Headset Function", rx)
        bluet.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bthvox))
        rset = RadioSetting("settings.bthvox", "Vox", rx)
        bluet.append(rset)

        options = ["Off", "1.0", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
        rx = RadioSettingValueList(options, options[_sets.bthvoxlvl])
        rset = RadioSetting("settings.bthvoxlvl", "Vox Level", rx)
        bluet.append(rset)

        options = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
        rx = RadioSettingValueList(options, options[_sets.bthvoxdly])
        rset = RadioSetting("settings.bthvoxdly", "Vox Delay (Secs)", rx)
        bluet.append(rset)

        options = ["Off", "1", "2", "3", "4", "5", "10", "15"]
        rx = RadioSettingValueList(options, options[_sets.bthvoxtot])
        rset = RadioSetting("settings.bthvoxtot", "Vox Time-Out (Mins)", rx)
        bluet.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bthhdpsav))
        rset = RadioSetting("settings.bthhdpsav",
                            "ICOM Headset Power-Save", rx)
        bluet.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bth1ptt))
        rset = RadioSetting("settings.bth1ptt",
                            "ICOM Headset One-Touch PTT", rx)
        bluet.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bthpttbeep))
        rset = RadioSetting("settings.bthpttbeep",
                            "ICOM Headset PTT Beep", rx)
        bluet.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bthcustbeep))
        rset = RadioSetting("settings.bthcustbeep",
                            "ICOM Headset Custom Key Beep", rx)
        bluet.append(rset)

        rx = RadioSettingValueList(MICKEYOPTS, MICKEYOPTS[_sets.bthplaykey])
        rset = RadioSetting("settings.bthplaykey",
                            "ICOM Headset Custom Key [Play]", rx)
        bluet.append(rset)

        rx = RadioSettingValueList(MICKEYOPTS, MICKEYOPTS[_sets.bthfwdkey])
        rset = RadioSetting("settings.bthfwdkey",
                            "ICOM Headset Custom Key [Fwd]", rx)
        bluet.append(rset)

        rx = RadioSettingValueList(MICKEYOPTS, MICKEYOPTS[_sets.bthrwdkey])
        rset = RadioSetting("settings.bthrwdkey",
                            "ICOM Headset Custom Key [Rwd]", rx)
        bluet.append(rset)

        # ---- Display
        options = ["1: Dark", "2", "3", "4: Bright"]
        rx = RadioSettingValueList(options, options[_sets.backlight])
        rset = RadioSetting("settings.backlight", "Backlight Level", rx)
        disp.append(rset)

        options = ["Off", "Auto-Off", "Auto-1", "Auto-2", "Auto-3"]
        rx = RadioSettingValueList(options, options[_sets.autodim])
        rset = RadioSetting("settings.autodim", "Auto Dimmer", rx)
        disp.append(rset)

        options = ["5", "10"]
        rx = RadioSettingValueList(options, options[_sets.autodimtot])
        rset = RadioSetting("settings.autodimtot",
                            "Auto-Dimmer Timeout (Secs)", rx)
        disp.append(rset)

        options = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
        rx = RadioSettingValueList(options, options[_sets.contrast])
        rset = RadioSetting("settings.contrast", "LCD Contrast", rx)
        disp.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.openmsg))
        rset = RadioSetting("settings.openmsg", "Opening Message", rx)
        disp.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.memname))
        rset = RadioSetting("settings.memname", "Memory Names", rx)
        disp.append(rset)

        options = ["CH ID", "Frequency"]
        rx = RadioSettingValueList(options, options[_sets.airbandch])
        rset = RadioSetting("settings.airbandch", "Air Band Display", rx)
        disp.append(rset)

        # -- Sounds
        rx = RadioSettingValueInteger(0, 9, _sets.beeplvl)
        rset = RadioSetting("settings.beeplvl", "Beep Level", rx)
        sound.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.homebeep))
        rset = RadioSetting("settings.homebeep", "Home Chan Beep", rx)
        sound.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.keybeep))
        rset = RadioSetting("settings.keybeep", "Key Touch Beep", rx)
        sound.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.bandedgbeep))
        rset = RadioSetting("settings.bandedgbeep", "Band Edge Beep", rx)
        sound.append(rset)

        rx = RadioSettingValueBoolean(bool(_sets.scanstpbeep))
        rset = RadioSetting("settings.scanstpbeep", "Scan Stop Beep", rx)
        sound.append(rset)

        options = ["Off", "Mute", "Beep", "Mute & Beep"]
        rx = RadioSettingValueList(options, options[_sets.subandmute])
        rset = RadioSetting("settings.subandmute", "Sub Band Mute", rx)
        sound.append(rset)

        # --- DTMF Codes
        options = ["100", "200", "300", "500"]
        rx = RadioSettingValueList(options, options[_sets.dtmfspd])
        rset = RadioSetting("settings.dtmfspd", "DTMF Speed (mSecs)", rx)
        dtmf.append(rset)

        for kx in range(0, 16):
            stx = unpack_str(_dtm[kx].codes)
            rx = RadioSettingValueString(0, 24, stx)
            # NOTE the / to indicate indexed array
            rset = RadioSetting("dtmfcode/%d.codes" % kx,
                                "DTMF Code %X" % kx, rx)
            rset.set_apply_callback(pack_chars, _dtm, "codes", kx)
            dtmf.append(rset)

        # --- Program Scan Edges
        for kx in range(0, 25):
            stx = ""
            for i in range(0, 6):
                stx += chr(_pses[kx].name[i])
            stx = stx.rstrip()
            rx = RadioSettingValueString(0, 6, stx)
            rset = RadioSetting("pgmscanedge/%d.name" % kx,
                                "Program Scan %d Name" % kx, rx)
            rset.set_apply_callback(myset_psnam, _pses, kx, "name", 6)
            edges.append(rset)

            # Freq's use the multiplier flags
            fmult = 5000.0
            if _pses[kx].loflags == 0x10:
                fmult = 8333
            if _pses[kx].loflags == 0x08:
                fmult = 6250.0
            flow = (int(_pses[kx].lofreq) * fmult) / 1000000.0
            flow = round(flow, 4)

            fmult = 5000.0
            if _pses[kx].hiflags == 0x10:
                fmult = 8333
            if _pses[kx].hiflags == 0x08:
                fmult = 6250.0
            fhigh = (int(_pses[kx].hifreq) * fmult) / 1000000.0
            fhigh = round(fhigh, 4)
            if (flow > 0) and (flow >= fhigh):   # reverse em
                val = flow
                flow = fhigh
                fhigh = val
            rx = RadioSettingValueFloat(0, 550.0, flow, 0.010, 3)
            rset = RadioSetting("pgmscanedge/%d.lofreq" % kx,
                                "-- Scan %d Low Limit" % kx, rx)
            rset.set_apply_callback(myset_frqflgs, _pses, kx, "loflags",
                                    "lofreq")
            edges.append(rset)

            rx = RadioSettingValueFloat(0, 550.0, fhigh, 0.010, 3)
            rset = RadioSetting("pgmscanedge/%d.hifreq" % kx,
                                "-- Scan %d High Limit" % kx, rx)
            rset.set_apply_callback(myset_frqflgs, _pses, kx, "hiflags",
                                    "hifreq")
            edges.append(rset)

            # Tstep and Mode depend on the bands
            ndxt = 0
            ndxm = 0
            bxnd = 0
            tsopt = ["-", "5k", "6.25k", "10k", "12.5k", "15k",
                     "20k", "25k", "30k", "50k"]
            mdopt = ["-", "FM", "FM-N"]
            if fhigh > 0:
                if fhigh < 135.0:  # Air band
                    bxnd = 1
                    tsopt = ["-", "8.33k", "25k", "Auto"]
                    ndxt = _pses[kx].tstp
                    if ndxt == 0xe:     # Auto
                        ndxt = 3
                    elif ndxt == 8:     # 25k
                        ndxt = 2
                    elif ndxt == 2:     # 8.33k
                        ndxt = 1
                    else:
                        ndxt = 0
                    mdopt = ["-"]
                elif (flow >= 137.0) and (fhigh <= 174.0):   # VHF
                    ndxt = _pses[kx].tstp - 1
                    ndxm = _pses[kx].mode + 1
                    bxnd = 2
                elif (flow >= 375.0) and (fhigh <= 550.0):  # UHF
                    ndxt = _pses[kx].tstp - 1
                    ndxm = _pses[kx].mode + 1
                    bxnd = 3
                else:   # Mixed, ndx's = 0 default
                    tsopt = ["-"]
                    mdopt = ["-"]
                    bxnd = 4
                if (ndxt > 9) or (ndxt < 0):
                    ndxt = 0   # trap ff
                if ndxm > 2:
                    ndxm = 0
            # end if fhigh > 0
            rx = RadioSettingValueList(tsopt, tsopt[ndxt])
            rset = RadioSetting("pgmscanedge/%d.tstp" % kx,
                                "-- Scan %d Freq Step" % kx, rx)
            rset.set_apply_callback(myset_tsopt, _pses, kx, "tstp", bxnd)
            edges.append(rset)

            rx = RadioSettingValueList(mdopt, mdopt[ndxm])
            rset = RadioSetting("pgmscanedge/%d.mode" % kx,
                                "-- Scan %d Mode" % kx, rx)
            rset.set_apply_callback(myset_mdopt, _pses, kx, "mode", bxnd)
            edges.append(rset)
        # End for kx

        # --- Program Scan Links
        _psln = self._memobj.pslnam
        _pslg = self._memobj.pslgrps
        for kx in range(0, 10):
            stx = ""
            for i in range(0, 6):
                stx += chr(_psln[kx].nam[i])
            stx = stx.rstrip()
            rx = RadioSettingValueString(0, 6, stx)
            rset = RadioSetting("pslnam/%d.nam" % kx,
                                "Program Scan Link %d Name" % kx, rx)
            rset.set_apply_callback(myset_psnam, _psln, kx, "nam", 6)
            pslnk.append(rset)

            for px in range(0, 25):
                # Generate string numeric representation of 4-byte bitmask
                stx = ""
                for nx in range(0, 25):
                    if nx < 8:
                        if (_pslg[kx].msk[0] & (1 << nx)):
                            stx += "%0d, " % nx
                    elif (nx >= 8) and (nx < 16):
                        if (_pslg[kx].msk[1] & (1 << (nx - 8))):
                            sstx += "%0d, " % nx
                    elif (nx >= 16) and (nx < 24):
                        if (_pslg[kx].msk[2] & (1 << (nx - 16))):
                            stx += "%0d, " % nx
                    elif (nx >= 24):
                        if (_pslg[kx].msk[3] & (1 << (nx - 24))):
                            stx += "%0d, " % nx
            rx = RadioSettingValueString(0, 80, stx)
            rset = RadioSetting("pslgrps/%d.msk" % kx,
                                "--- Scan Link %d Scans" % kx, rx)
            rset.set_apply_callback(myset_bitmask, _pslg,
                                    kx, "msk", 25)
            pslnk.append(rset)
            # end for px
        # End for kx
        return group       # END get_settings()

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif element.get_name() == "drv_clone_speed":
                        val = element.value.get_value()
                        self.__class__._can_hispeed = val
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise
