# Copyright 2013 Jens Jensen <kd4tjx@yahoo.com>
#     based on modification of Dan Smith's and Rick Farina's original work
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

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
import os
import traceback
import re
import logging

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x7F52;
u8 checksum;

#seekto 0x005A;
u8  banksoff1;
#seekto 0x00DA;
u8  banksoff2;

#seekto 0x0068;
u16 prioritychan1;

#seekto 0x00E8;
u16 prioritychan2;

#seekto 0x110;
struct {
    u8  unk1;
    u8  unk2;
    u8  nfm_sql;
    u8  wfm_sql;
    u8  rfsql;
    u8  vfomode:1,
        cwid_en:1,
        scan_lamp:1,
        unk3:1,
        ars:1,
        beep:1,
        split:1,
        dtmfmode:1;
    u8  busyled:1,
        unk4:2,
        bclo:1,
        edgebeep:1,
        unk5:2,
        txsave:1;
    u8  unk6:2,
        smartsearch:1,
        unk7:1,
        artsinterval:1,
        unk8:1,
        hmrv:1,
        moni_tcall:1;
    u8  unk9:5,
        dcsrev:1,
        unk10:1,
        mwmode:1;
    u8  internet_mode:1,
        internet_key:1,
        wx_alert:1,
        unk11:2,
        att:1,
        unk12:2;
    u8  lamp;
    u8  dimmer;
    u8  rxsave;
    u8  resume;
    u8  chcounter;
    u8  openmsgmode;
    u8  openmsg[6];
    u8  cwid[16];
    u8  unk13[16];
    u8  artsbeep;
    u8  bell;
    u8  apo;
    u8  tot;
    u8  lock;
    u8  mymenu;
    u8  unk14[4];
    u8  emergmode;

} settings;

#seekto 0x0192;
struct {
    u8  digits[16];
}   dtmf[9];

#seekto 0x016A;
struct {
    u16 in_use;
} bank_used[20];

#seekto 0x0396;
struct {
    u8 name[6];
} wxchannels[10];

#seekto 0x05C2;
struct {
  u16 channels[100];
} banks[20];

#seekto 0x1562;
struct {
  u8 even_pskip:1,
     even_skip:1,
     even_valid:1,
     even_masked:1,
     odd_pskip:1,
     odd_skip:1,
     odd_valid:1,
     odd_masked:1;
} flags[500];

struct mem_struct {
  u8   unknown1:2,
       txnarrow:1,
       clk:1,
       unknown2:4;
  u8   mode:2,
       duplex:2,
       tune_step:4;
  bbcd freq[3];
  u8   power:2,
       unknown3:4,
       tmode:2;
  u8   name[6];
  bbcd offset[3];
  u8   unknown4:2,
       tone:6;
  u8   unknown5:1,
       dcs:7;
  u8   unknown6;
};

#seekto 0x17C2;
struct mem_struct memory[1000];
struct {
    struct mem_struct lower;
    struct mem_struct upper;
} pms[50];


#seekto 0x03D2;
struct mem_struct home[12];

#seekto 0x04E2;
struct mem_struct vfo[12];


"""

VX2_DUPLEX = ["", "-", "+", "split"]
# NFM handled specially in radio
VX2_MODES = ["FM", "AM", "WFM", "Auto", "NFM"]
VX2_TMODES = ["", "Tone", "TSQL", "DTCS"]

VX2_STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0, 9.0]

CHARSET = list("0123456789" +
               "ABCDEFGHIJKLMNOPQRSTUVWXYZ " +
               "+-/\x00[](){}\x00\x00_" +
               ("\x00" * 13) + "*" + "\x00\x00,'|\x00\x00\x00\x00" +
               ("\x00" * 64))

DTMFCHARSET = list("0123456789ABCD*#")

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=1.50),
                chirp_common.PowerLevel("Low", watts=0.10)]


class VX2BankModel(chirp_common.BankModel):
    """A VX-2 bank model"""

    def get_num_mappings(self):
        return len(self.get_mappings())

    def get_mappings(self):
        banks = self._radio._memobj.banks
        bank_mappings = []
        for index, _bank in enumerate(banks):
            bank = chirp_common.Bank(self, "%i" % index, "b%i" % (index + 1))
            bank.index = index
            bank_mappings.append(bank)

        return bank_mappings

    def _get_channel_numbers_in_bank(self, bank):
        _bank_used = self._radio._memobj.bank_used[bank.index]
        if _bank_used.in_use == 0xFFFF:
            return set()

        _members = self._radio._memobj.banks[bank.index]
        return set([int(ch) + 1 for ch in _members.channels if ch != 0xFFFF])

    def _update_bank_with_channel_numbers(self, bank, channels_in_bank):
        _members = self._radio._memobj.banks[bank.index]
        if len(channels_in_bank) > len(_members.channels):
            raise Exception("Too many entries in bank %d" % bank.index)

        empty = 0
        for index, channel_number in enumerate(sorted(channels_in_bank)):
            _members.channels[index] = channel_number - 1
            empty = index + 1
        for index in range(empty, len(_members.channels)):
            _members.channels[index] = 0xFFFF

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        channels_in_bank.add(memory.number)
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        _bank_used = self._radio._memobj.bank_used[bank.index]
        _bank_used.in_use = 0x0000

        # also needed for unit to recognize banks?
        self._radio._memobj.banksoff1 = 0x00
        self._radio._memobj.banksoff2 = 0x00
        # todo: turn back off (0xFF) when all banks are empty?

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._get_channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        if not channels_in_bank:
            _bank_used = self._radio._memobj.bank_used[bank.index]
            _bank_used.in_use = 0xFFFF

    def get_mapping_memories(self, bank):
        memories = []
        for channel in self._get_channel_numbers_in_bank(bank):
            memories.append(self._radio.get_memory(channel))

        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._get_channel_numbers_in_bank(bank):
                banks.append(bank)

        return banks


def _wipe_memory(mem):
    mem.set_raw("\x00" * (mem.size() // 8))


@directory.register
class VX2Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-2"""
    MODEL = "VX-2"
    _model = "AH015"
    BAUD_RATE = 19200
    _block_lengths = [10, 8, 32577]
    _memsize = 32595

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = True
        rf.has_settings = True
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(set(VX2_MODES))
        rf.valid_tmodes = list(VX2_TMODES)
        rf.valid_duplexes = list(VX2_DUPLEX)
        rf.valid_tuning_steps = list(VX2_STEPS)
        rf.valid_bands = [(500000, 999000000)]
        rf.valid_skips = ["", "S", "P"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.memory_bounds = (1, 1000)
        rf.can_odd_split = True
        rf.has_ctone = False
        return rf

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, 0x7F51)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number-1]
        _flag = self._memobj.flags[(number-1)/2]

        nibble = ((number-1) % 2) and "even" or "odd"
        used = _flag["%s_masked" % nibble]
        valid = _flag["%s_valid" % nibble]
        pskip = _flag["%s_pskip" % nibble]
        skip = _flag["%s_skip" % nibble]

        mem = chirp_common.Memory()
        mem.number = number

        if not used:
            mem.empty = True
        if not valid:
            mem.empty = True
            mem.power = POWER_LEVELS[0]
            return mem

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        mem.tmode = VX2_TMODES[_mem.tmode]
        mem.duplex = VX2_DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        if _mem.txnarrow and _mem.mode == VX2_MODES.index("FM"):
            # narrow + FM
            mem.mode = "NFM"
        else:
            mem.mode = VX2_MODES[_mem.mode]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = VX2_STEPS[_mem.tune_step]
        mem.skip = pskip and "P" or skip and "S" or ""
        mem.power = POWER_LEVELS[~_mem.power & 0x01]

        for i in _mem.name:
            if i == 0xFF:
                break
            mem.name += CHARSET[i & 0x7F]
        mem.name = mem.name.rstrip()
        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        _flag = self._memobj.flags[(mem.number-1)/2]

        nibble = ((mem.number-1) % 2) and "even" or "odd"

        used = _flag["%s_masked" % nibble]
        valid = _flag["%s_valid" % nibble]

        if not mem.empty and not valid:
            _wipe_memory(_mem)

        if mem.empty and valid and not used:
            _flag["%s_valid" % nibble] = False
            return
        _flag["%s_masked" % nibble] = not mem.empty

        if mem.empty:
            return

        _flag["%s_valid" % nibble] = True

        _mem.freq = mem.freq / 1000
        _mem.offset = mem.offset / 1000
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tmode = VX2_TMODES.index(mem.tmode)
        _mem.duplex = VX2_DUPLEX.index(mem.duplex)
        if mem.mode == "NFM":
            _mem.mode = VX2_MODES.index("FM")
            _mem.txnarrow = True
        else:
            _mem.mode = VX2_MODES.index(mem.mode)
            _mem.txnarrow = False
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = VX2_STEPS.index(mem.tuning_step)
        if mem.power == POWER_LEVELS[1]:  # Low
            _mem.power = 0x00
        else:  # Default to High
            _mem.power = 0x03

        _flag["%s_pskip" % nibble] = mem.skip == "P"
        _flag["%s_skip" % nibble] = mem.skip == "S"

        for i in range(0, 6):
            _mem.name[i] = CHARSET.index(mem.name.ljust(6)[i])
        if mem.name.strip():
            # empty name field, disable name display
            # leftmost bit of name chararr is:
            #   1 = display freq, 0 = display name
            _mem.name[0] |= 0x80

        # for now, clear unknown fields
        for i in range(1, 7):
            setattr(_mem, "unknown%i" % i, 0)

    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)
        return msgs

    def get_bank_model(self):
        return VX2BankModel(self)

    def _decode_chars(self, inarr):
        LOG.debug("@_decode_chars, type: %s" % type(inarr))
        LOG.debug(inarr)
        outstr = ""
        for i in inarr:
            if i == 0xFF:
                break
            outstr += CHARSET[i & 0x7F]
        return outstr.rstrip()

    def _encode_chars(self, instr, length=16):
        LOG.debug("@_encode_chars, type: %s" % type(instr))
        LOG.debug(instr)
        outarr = []
        instr = str(instr)
        for i in range(0, length):
            if i < len(instr):
                outarr.append(CHARSET.index(instr[i]))
            else:
                outarr.append(0xFF)
        return outarr

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        arts = RadioSettingGroup("arts", "ARTS")
        top = RadioSettings(basic, arts, dtmf)

        options = ["off", "30m", "1h", "3h", "5h", "8h"]
        rs = RadioSetting(
                "apo", "APO time (hrs)",
                RadioSettingValueList(options, options[_settings.apo]))
        basic.append(rs)

        rs = RadioSetting(
                "ars", "Auto Repeater Shift",
                RadioSettingValueBoolean(_settings.ars))
        basic.append(rs)

        rs = RadioSetting(
                "att", "Attenuation",
                RadioSettingValueBoolean(_settings.att))
        basic.append(rs)

        rs = RadioSetting(
                "bclo", "Busy Channel Lockout",
                RadioSettingValueBoolean(_settings.bclo))
        basic.append(rs)

        rs = RadioSetting(
                "beep", "Beep",
                RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        options = ["off", "1", "3", "5", "8", "cont"]
        rs = RadioSetting(
                "bell", "Bell",
                RadioSettingValueList(options, options[_settings.bell]))
        basic.append(rs)

        rs = RadioSetting(
                "busyled", "Busy LED",
                RadioSettingValueBoolean(_settings.busyled))
        basic.append(rs)

        options = ["5", "10", "50", "100"]
        rs = RadioSetting(
                "chcounter", "Channel Counter (MHz)",
                RadioSettingValueList(options, options[_settings.chcounter]))
        basic.append(rs)

        rs = RadioSetting(
                "dcsrev", "DCS Reverse",
                RadioSettingValueBoolean(_settings.dcsrev))
        basic.append(rs)

        options = list(map(str, list(range(0, 12+1))))
        rs = RadioSetting(
                "dimmer", "Dimmer",
                RadioSettingValueList(options, options[_settings.dimmer]))
        basic.append(rs)

        rs = RadioSetting(
                "edgebeep", "Edge Beep",
                RadioSettingValueBoolean(_settings.edgebeep))
        basic.append(rs)

        options = ["beep", "strobe", "bp+str", "beam",
                   "bp+beam", "cw", "bp+cw"]
        rs = RadioSetting(
                "emergmode", "Emergency Mode",
                RadioSettingValueList(options, options[_settings.emergmode]))
        basic.append(rs)

        options = ["Home", "Reverse"]
        rs = RadioSetting(
                "hmrv", "HM/RV key",
                RadioSettingValueList(options, options[_settings.hmrv]))
        basic.append(rs)

        options = ["My Menu", "Internet"]
        rs = RadioSetting(
                "internet_key", "Internet key",
                RadioSettingValueList(
                    options, options[_settings.internet_key]))
        basic.append(rs)

        options = ["1 APO", "2 AR BEP", "3 AR INT", "4 ARS", "5 ATT",
                   "6 BCLO", "7 BEEP", "8 BELL", "9 BSYLED", "10 CH CNT",
                   "11 CK SFT", "12 CW ID", "13 DC VLT", "14 DCS CD",
                   "15 DCS RV", "16 DIMMER", "17 DTMF", "18 DTMF S",
                   "19 EDG BP", "20 EMG S", "21 HLFDEV", "22 HM/RV",
                   "23 INT MD", "24 LAMP", "25 LOCK", "26 M/T-CL",
                   "27 MW MD", "28 NAME", "29 NM SET", "30 OPNMSG",
                   "31 RESUME", "32 RF SQL", "33 RPT", "34 RX MD",
                   "35 RXSAVE", "36 S SCH", "37 SCNLMP", "38 SHIFT",
                   "39 SKIP", "40 SPLIT", "41 SQL", "42 SQL TYP",
                   "43 STEP", "44 TN FRQ", "45 TOT", "46 TXSAVE",
                   "47 VFO MD", "48 TR SQL (JAPAN)", "48 WX ALT"]

        rs = RadioSetting(
                "mymenu", "My Menu function",
                RadioSettingValueList(options, options[_settings.mymenu - 9]))
        basic.append(rs)

        options = ["wires", "link"]
        rs = RadioSetting(
                "internet_mode", "Internet mode",
                RadioSettingValueList(
                    options, options[_settings.internet_mode]))
        basic.append(rs)

        options = ["key", "cont", "off"]
        rs = RadioSetting(
                "lamp", "Lamp mode",
                RadioSettingValueList(options, options[_settings.lamp]))
        basic.append(rs)

        options = ["key", "dial", "key+dial", "ptt",
                   "key+ptt", "dial+ptt", "all"]
        rs = RadioSetting(
                "lock", "Lock mode",
                RadioSettingValueList(options, options[_settings.lock]))
        basic.append(rs)

        options = ["monitor", "tone call"]
        rs = RadioSetting(
                "moni_tcall", "MONI key",
                RadioSettingValueList(options, options[_settings.moni_tcall]))
        basic.append(rs)

        options = ["lower", "next"]
        rs = RadioSetting(
                "mwmode", "Memory write mode",
                RadioSettingValueList(options, options[_settings.mwmode]))
        basic.append(rs)

        options = list(map(str, list(range(0, 15+1))))
        rs = RadioSetting(
                "nfm_sql", "NFM Sql",
                RadioSettingValueList(options, options[_settings.nfm_sql]))
        basic.append(rs)

        options = list(map(str, list(range(0, 8+1))))
        rs = RadioSetting(
                "wfm_sql", "WFM Sql",
                RadioSettingValueList(options, options[_settings.wfm_sql]))
        basic.append(rs)

        options = ["off", "dc", "msg"]
        rs = RadioSetting(
                "openmsgmode", "Opening message",
                RadioSettingValueList(options, options[_settings.openmsgmode]))
        basic.append(rs)

        openmsg = RadioSettingValueString(
                0, 6, self._decode_chars(_settings.openmsg.get_value()))
        openmsg.set_charset(CHARSET)
        rs = RadioSetting("openmsg", "Opening Message", openmsg)
        basic.append(rs)

        options = ["3s", "5s", "10s", "busy", "hold"]
        rs = RadioSetting(
                "resume", "Resume",
                RadioSettingValueList(options, options[_settings.resume]))
        basic.append(rs)

        options = ["off"] + list(map(str, list(range(1, 9+1))))
        rs = RadioSetting(
                "rfsql", "RF Sql",
                RadioSettingValueList(options, options[_settings.rfsql]))
        basic.append(rs)

        options = ["off", "200ms", "300ms", "500ms", "1s", "2s"]
        rs = RadioSetting(
                "rxsave", "RX pwr save",
                RadioSettingValueList(options, options[_settings.rxsave]))
        basic.append(rs)

        options = ["single", "cont"]
        rs = RadioSetting(
                "smartsearch", "Smart search",
                RadioSettingValueList(options, options[_settings.smartsearch]))
        basic.append(rs)

        rs = RadioSetting(
                "scan_lamp", "Scan lamp",
                RadioSettingValueBoolean(_settings.scan_lamp))
        basic.append(rs)

        rs = RadioSetting(
                "split", "Split",
                RadioSettingValueBoolean(_settings.split))
        basic.append(rs)

        options = ["off", "1", "3", "5", "10"]
        rs = RadioSetting(
                "tot", "TOT (mins)",
                RadioSettingValueList(options, options[_settings.tot]))
        basic.append(rs)

        rs = RadioSetting(
                "txsave", "TX pwr save",
                RadioSettingValueBoolean(_settings.txsave))
        basic.append(rs)

        options = ["all", "band"]
        rs = RadioSetting(
                "vfomode", "VFO mode",
                RadioSettingValueList(options, options[_settings.vfomode]))
        basic.append(rs)

        rs = RadioSetting(
                "wx_alert", "WX Alert",
                RadioSettingValueBoolean(_settings.wx_alert))
        basic.append(rs)

        # todo: priority channel

        # todo: handle WX ch labels

        # arts settings (ar beep, ar int, cwid en, cwid field)
        options = ["15s", "25s"]
        rs = RadioSetting(
                "artsinterval", "ARTS Interval",
                RadioSettingValueList(
                    options, options[_settings.artsinterval]))
        arts.append(rs)

        options = ["off", "in range", "always"]
        rs = RadioSetting(
                "artsbeep", "ARTS Beep",
                RadioSettingValueList(options, options[_settings.artsbeep]))
        arts.append(rs)

        rs = RadioSetting(
                "cwid_en", "CWID Enable",
                RadioSettingValueBoolean(_settings.cwid_en))
        arts.append(rs)

        cwid = RadioSettingValueString(
                0, 16, self._decode_chars(_settings.cwid.get_value()))
        cwid.set_charset(CHARSET)
        rs = RadioSetting("cwid", "CWID", cwid)
        arts.append(rs)

        # setup dtmf
        options = ["manual", "auto"]
        rs = RadioSetting(
                "dtmfmode", "DTMF mode",
                RadioSettingValueList(options, options[_settings.dtmfmode]))
        dtmf.append(rs)

        for i in range(0, 8+1):
            name = "dtmf" + str(i+1)
            dtmfsetting = self._memobj.dtmf[i]
            # dtmflen = getattr(_settings, objname + "_len")
            dtmfstr = ""
            for c in dtmfsetting.digits:
                if c < len(DTMFCHARSET):
                    dtmfstr += DTMFCHARSET[c]
            LOG.debug(dtmfstr)
            dtmfentry = RadioSettingValueString(0, 16, dtmfstr)
            dtmfentry.set_charset(DTMFCHARSET + list(" "))
            rs = RadioSetting(name, name.upper(), dtmfentry)
            dtmf.append(rs)

        return top

    def set_settings(self, uisettings):
        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                setting = element.get_name()
                _settings = self._memobj.settings
                if re.match('dtmf\d', setting):
                    # set dtmf fields
                    dtmfstr = str(element.value).strip()
                    newval = []
                    for i in range(0, 16):
                        if i < len(dtmfstr):
                            newval.append(DTMFCHARSET.index(dtmfstr[i]))
                        else:
                            newval.append(0xFF)
                    LOG.debug(newval)
                    idx = int(setting[-1:]) - 1
                    _settings = self._memobj.dtmf[idx]
                    _settings.digits = newval
                    continue
                if setting == "prioritychan":
                    # prioritychan is top-level member, fix 0 index
                    element.value -= 1
                    _settings = self._memobj
                if setting == "mymenu":
                    opts = element.value.get_options()
                    optsidx = opts.index(element.value.get_value())
                    idx = optsidx + 9
                    setattr(_settings, "mymenu", idx)
                    continue
                oldval = getattr(_settings, setting)
                newval = element.value
                if setting == "cwid":
                    newval = self._encode_chars(newval)
                if setting == "openmsg":
                    newval = self._encode_chars(newval, 6)
                LOG.debug("Setting %s(%s) <= %s" % (setting, oldval, newval))
                setattr(_settings, setting, newval)
            except Exception as e:
                LOG.debug(element.get_name())
                raise
