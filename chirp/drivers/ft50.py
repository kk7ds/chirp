# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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
import time
import logging
import re

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, errors, bitwise, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
from textwrap import dedent

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct flag_struct {
  u8 unknown1f:5,
     skip:1,
     mask:1,
     used:1;
};

struct mem_struct {
  u8 showname:1,
     unknown1:3,
     unknown2:2,
     unknown3:2;
  u8 ishighpower:1,
     power:2,
     unknown4:1,
     tuning_step:4;
  u8 codememno:4,
     codeorpage:2,
     duplex:2;
  u8 tmode:2,
     tone:6;
  u8 unknown5:1,
     dtcs:7;
  u8 unknown6:6,
     mode:2;
  bbcd freq[3];
  bbcd offset[3];
  u8 name[4];
};

#seekto 0x000C;
struct {
  u8 extendedrx_flg;    // Seems to be set to 03 when extended rx is enabled
  u8 extendedrx;        // Seems to be set to 01 when extended rx is enabled
} extendedrx_struct;    // UNFINISHED!!

#seekto 0x001A;
struct flag_struct flag[100];

#seekto 0x079C;
struct flag_struct flag_repeat[100];

#seekto 0x00AA;
struct mem_struct memory[100];
struct mem_struct special[11];

#seekto 0x08C7;
struct {
  u8 sub_display;
  u8 unknown1s;
  u8 apo;
  u8 timeout;
  u8 lock;
  u8 rxsave;
  u8 lamp;
  u8 bell;
  u8 cwid[16];
  u8 unknown2s;
  u8 artsmode;
  u8 artsbeep;
  u8 unknown3s;
  u8 unknown4s;
  struct {
    u8 header[3];
    u8 mem_num;
    u8 digits[16];
  } autodial[8];
  struct {
    u8 header[3];
    u8 mem_num;
    u8 digits[32];
  } autodial9_ro;
  bbcd pagingcodec_ro[2];
  bbcd pagingcodep[2];
  struct {
    bbcd digits[2];
  } pagingcode[6];
  u8 code_dec_c_en:1,
     code_dec_p_en:1,
     code_dec_1_en:1,
     code_dec_2_en:1,
     code_dec_3_en:1,
     code_dec_4_en:1,
     code_dec_5_en:1,
     code_dec_6_en:1;
  u8 pagingspeed;
  u8 pagingdelay;
  u8 pagingbell;
  u8 paginganswer;

  #seekto 0x0E30;
  u8 squelch;       // squelch
  u8 unknown0c;
  u8 rptl:1,        // repeater input tracking
     amod:1,        // auto mode
     scnl:1,        // scan lamp
     resm:1,        // scan resume mode 0=5sec, 1=carr
     ars:1,         // automatic repeater shift
     keybeep:1,     // keypad beep
     lck:1,         // lock
     unknown1c:1;
  u8 lgt:1,
     pageamsg:1,
     unknown2c:1,
     bclo:1,        // Busy channel lock out
     unknown3c:2,
     cwid_en:1,     // CWID off/on
     tsav:1;        // TX save
  u8 unknown4c:4,
     artssped:1,    // ARTS/SPED: 0=15s, 1=25s
     unknown5c:1,
     rvhm:1,        // RVHM: 0=home, 1=rev
     mon:1;         // MON: 0=mon, 1=tcal
} settings;

#seekto 0x080E;
struct mem_struct vfo_mem[10];


"""

# 10 VFO memories: A145, A220, A380, A430, A800,
#                  B145, B220, B380, B430, B800

DUPLEX = ["", "-", "+"]
MODES = ["FM", "AM", "WFM"]
SKIP_VALUES = ["", "S"]
TMODES = ["", "Tone", "TSQL", "DTCS"]
TUNING_STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
TONES = list(chirp_common.OLD_TONES)

# CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ()+-=*/???|0123456789"
# the = displays as an underscored dash on radio
# the first ? is an uppercase delta - \xA7
# the second ? is an uppercase gamma - \xD1
# the thrid ? is an uppercase sigma - \xCF
NUMERIC_CHARSET = list("0123456789")
CHARSET = [str(x) for x in range(0, 10)] + \
    [chr(x) for x in range(ord("A"), ord("Z")+1)] + \
    list(" ()+-=*/" + ("\x00" * 3) + "|") + NUMERIC_CHARSET
DTMFCHARSET = NUMERIC_CHARSET + list("ABCD*#")

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.0),
                chirp_common.PowerLevel("L3", watts=2.5),
                chirp_common.PowerLevel("L2", watts=1.0),
                chirp_common.PowerLevel("L1", watts=0.1)]
SPECIALS = ["L1", "U1", "L2", "U2", "L3", "U3", "L4", "U4", "L5", "U5", "UNK"]


@directory.register
class FT50Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FT-50"""
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "FT-50"

    _model = ""
    _memsize = 3723
    _block_lengths = [10, 16, 112, 16, 16, 1776, 1776, 1]
    # _block_delay = 0.15
    _block_size = 8

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
1. Turn radio off.
2. Connect cable to MIC/SP jack.
3. Press and hold [PTT] &amp; Knob while turning the
     radio on.
4. <b>After clicking OK</b>, press the [PTT] switch to send image."""))
        rp.pre_upload = _(dedent("""\
1. Turn radio off.
2. Connect cable to MIC/SP jack.
3. Press and hold [PTT] &amp; Knob while turning the
     radio on.
4. Press the [MONI] switch ("WAIT" will appear on the LCD).
5. Press OK."""))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 100)
        rf.valid_duplexes = DUPLEX
        rf.valid_tmodes = TMODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 4
        rf.valid_modes = MODES
        # Specials not yet implementd
        # rf.valid_special_chans = SPECIALS
        rf.valid_bands = [(76000000, 200000000),
                          (300000000, 540000000),
                          (590000000, 999000000)]
        # rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_bank = False
        rf.has_settings = True
        rf.has_dtcs_polarity = False

        return rf

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, 0xE89)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        mem = chirp_common.Memory()
        _mem = self._memobj.memory[number-1]
        _flg = self._memobj.flag[number-1]
        mem.number = number

        # if not _flg.visible:
        #    mem.empty = True
        if not _flg.used:
            mem.empty = True
            return mem

        for i in _mem.name:
            mem.name += CHARSET[i & 0x7F]
        mem.name = mem.name.rstrip()

        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.duplex = DUPLEX[_mem.duplex]
        mem.offset = chirp_common.fix_rounded_step(int(_mem.offset) * 1000)
        mem.rtone = mem.ctone = TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tmode]
        mem.mode = MODES[_mem.mode]
        mem.tuning_step = TUNING_STEPS[_mem.tuning_step]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        # Power is stored as 2 bits to describe the 3 low power levels
        # High power is determined by a different bit.
        if not _mem.ishighpower:
            mem.power = POWER_LEVELS[3 - _mem.power]
        else:
            mem.power = POWER_LEVELS[0]
        mem.skip = SKIP_VALUES[_flg.skip]

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number-1]
        _flg = self._memobj.flag[mem.number-1]
        _flg_repeat = self._memobj.flag_repeat[mem.number-1]

        if mem.empty:
            _flg.used = False
            return

        if (len(mem.name) == 0):
            _mem.name = [0x24] * 4
            _mem.showname = 0
        else:
            _mem.showname = 1
            for i in range(0, 4):
                _mem.name[i] = CHARSET.index(mem.name.ljust(4)[i])

        _mem.freq = int(mem.freq / 1000)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.offset = int(mem.offset / 1000)
        _mem.mode = MODES.index(mem.mode)
        _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
        if mem.power:
            if (mem.power == POWER_LEVELS[0]):
                # low power level is not changed when high power is selected
                _mem.ishighpower = 0x01
                if (_mem.power == 3):
                    # Set low power to L3 (0x02) if it is
                    # set to 3 (new object default)
                    LOG.debug("SETTING DEFAULT?")
                    _mem.power = 0x02
            else:
                _mem.ishighpower = 0x00
                _mem.power = 3 - POWER_LEVELS.index(mem.power)
        else:
            _mem.ishighpower = 0x01
            _mem.power = 0x02
        _mem.tmode = TMODES.index(mem.tmode)
        try:
            _mem.tone = TONES.index(mem.rtone)
        except ValueError:
            raise errors.UnsupportedToneError(
                ("This radio does not support tone %s" % mem.rtone))
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)

        _flg.skip = SKIP_VALUES.index(mem.skip)

        # initialize new channel to safe defaults
        if not mem.empty and not _flg.used:
            _flg.used = True
            _flg.mask = True        # Mask = True to be visible on radio
            _mem.unknown1 = 0x00
            _mem.unknown2 = 0x00
            _mem.unknown3 = 0x00
            _mem.unknown4 = 0x00
            _mem.unknown5 = 0x00
            _mem.unknown6 = 0x00
            _mem.codememno = 0x02   # Not implemented in chirp
            _mem.codeorpage = 0x00  # Not implemented in chirp

        # Duplicate flags to repeated part in memory
        _flg_repeat.skip = _flg.skip
        _flg_repeat.mask = _flg.mask
        _flg_repeat.used = _flg.used

    def _decode_cwid(self, inarr):
        LOG.debug("@_decode_chars, type: %s" % type(inarr))
        LOG.debug(inarr)
        outstr = ""
        for i in inarr:
            if i == 0xFF:
                break
            outstr += CHARSET[i & 0x7F]
        LOG.debug(outstr)
        return outstr.rstrip()

    def _encode_cwid(self, instr, length=16):
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
        dtmf = RadioSettingGroup("dtmf", "DTMF Code & Paging")
        arts = RadioSettingGroup("arts", "ARTS")
        autodial = RadioSettingGroup("autodial", "AutoDial")
        top = RadioSettings(basic, autodial, arts, dtmf)

        rs = RadioSetting(
                "squelch", "Squelch",
                RadioSettingValueInteger(0, 15, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting(
                "keybeep", "Keypad Beep",
                RadioSettingValueBoolean(_settings.keybeep))
        basic.append(rs)

        rs = RadioSetting(
                "scnl", "Scan Lamp",
                RadioSettingValueBoolean(_settings.scnl))
        basic.append(rs)

        options = ["off", "30m", "1h", "3h", "5h", "8h"]
        rs = RadioSetting(
                "apo", "APO time (hrs)",
                RadioSettingValueList(options, options[_settings.apo]))
        basic.append(rs)

        options = ["off", "1m", "2.5m", "5m", "10m"]
        rs = RadioSetting(
                "timeout", "Time Out Timer",
                RadioSettingValueList(options, options[_settings.timeout]))
        basic.append(rs)

        options = ["key", "dial", "key+dial", "ptt",
                   "key+ptt", "dial+ptt", "all"]
        rs = RadioSetting(
                "lock", "Lock mode",
                RadioSettingValueList(options, options[_settings.lock]))
        basic.append(rs)

        options = ["off", "0.2", "0.3", "0.5", "1.0", "2.0"]
        rs = RadioSetting(
                "rxsave", "RX Save (sec)",
                RadioSettingValueList(options, options[_settings.rxsave]))
        basic.append(rs)

        options = ["5sec", "key", "tgl"]
        rs = RadioSetting(
                "lamp", "Lamp mode",
                RadioSettingValueList(options, options[_settings.lamp]))
        basic.append(rs)

        options = ["off", "1", "3", "5", "8", "rpt"]
        rs = RadioSetting(
                "bell", "Bell Repetitions",
                RadioSettingValueList(options, options[_settings.bell]))
        basic.append(rs)

        rs = RadioSetting(
                "cwid_en", "CWID Enable",
                RadioSettingValueBoolean(_settings.cwid_en))
        arts.append(rs)

        cwid = RadioSettingValueString(
                0, 16, self._decode_cwid(_settings.cwid.get_value()))
        cwid.set_charset(CHARSET)
        rs = RadioSetting("cwid", "CWID", cwid)
        arts.append(rs)

        options = ["off", "rx", "tx", "trx"]
        rs = RadioSetting(
                "artsmode", "ARTS Mode",
                RadioSettingValueList(
                    options, options[_settings.artsmode]))
        arts.append(rs)

        options = ["off", "in range", "always"]
        rs = RadioSetting(
                "artsbeep", "ARTS Beep",
                RadioSettingValueList(options, options[_settings.artsbeep]))
        arts.append(rs)

        for i in range(0, 8):
            dialsettings = _settings.autodial[i]
            dialstr = ""
            for c in dialsettings.digits:
                if c < len(DTMFCHARSET):
                    dialstr += DTMFCHARSET[c]
            dialentry = RadioSettingValueString(0, 16, dialstr)
            dialentry.set_charset(DTMFCHARSET + list(" "))
            rs = RadioSetting("autodial" + str(i+1),
                              "AutoDial " + str(i+1), dialentry)
            autodial.append(rs)

        dialstr = ""
        for c in _settings.autodial9_ro.digits:
            if c < len(DTMFCHARSET):
                dialstr += DTMFCHARSET[c]
        dialentry = RadioSettingValueString(0, 32, dialstr)
        dialentry.set_mutable(False)
        rs = RadioSetting("autodial9_ro", "AutoDial 9 (read only)", dialentry)
        autodial.append(rs)

        options = ["50ms", "100ms"]
        rs = RadioSetting(
                "pagingspeed", "Paging Speed",
                RadioSettingValueList(options, options[_settings.pagingspeed]))
        dtmf.append(rs)

        options = ["250ms", "450ms", "750ms", "1000ms"]
        rs = RadioSetting(
                "pagingdelay", "Paging Delay",
                RadioSettingValueList(options, options[_settings.pagingdelay]))
        dtmf.append(rs)

        options = ["off", "1", "3", "5", "8", "rpt"]
        rs = RadioSetting(
                "pagingbell", "Paging Bell Repetitions",
                RadioSettingValueList(options, options[_settings.pagingbell]))
        dtmf.append(rs)

        options = ["off", "ans", "for"]
        rs = RadioSetting(
                "paginganswer", "Paging Answerback",
                RadioSettingValueList(options,
                                      options[_settings.paginganswer]))
        dtmf.append(rs)

        rs = RadioSetting(
                "code_dec_c_en", "Paging Code C Decode Enable",
                RadioSettingValueBoolean(_settings.code_dec_c_en))
        dtmf.append(rs)

        _str = str(bitwise.bcd_to_int(_settings.pagingcodec_ro))
        code = RadioSettingValueString(0, 3, _str)
        code.set_charset(NUMERIC_CHARSET + list(" "))
        code.set_mutable(False)
        rs = RadioSetting("pagingcodec_ro", "Paging Code C (read only)", code)
        dtmf.append(rs)

        rs = RadioSetting(
                "code_dec_p_en", "Paging Code P Decode Enable",
                RadioSettingValueBoolean(_settings.code_dec_p_en))
        dtmf.append(rs)

        _str = str(bitwise.bcd_to_int(_settings.pagingcodep))
        code = RadioSettingValueString(0, 3, _str)
        code.set_charset(NUMERIC_CHARSET + list(" "))
        rs = RadioSetting("pagingcodep", "Paging Code P", code)
        dtmf.append(rs)

        for i in range(0, 6):
            num = str(i+1)
            name = "code_dec_" + num + "_en"
            rs = RadioSetting(
                    name, "Paging Code " + num + " Decode Enable",
                    RadioSettingValueBoolean(getattr(_settings, name)))
            dtmf.append(rs)

            _str = str(bitwise.bcd_to_int(_settings.pagingcode[i].digits))
            code = RadioSettingValueString(0, 3, _str)
            code.set_charset(NUMERIC_CHARSET + list(" "))
            rs = RadioSetting("pagingcode" + num, "Paging Code " + num, code)
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
                if re.match('autodial\d', setting):
                    # set autodial fields
                    dtmfstr = str(element.value).strip()
                    newval = []
                    for i in range(0, 16):
                        if i < len(dtmfstr):
                            newval.append(DTMFCHARSET.index(dtmfstr[i]))
                        else:
                            newval.append(0xFF)
                    LOG.debug(newval)
                    idx = int(setting[-1:]) - 1
                    _settings = self._memobj.settings.autodial[idx]
                    _settings.digits = newval
                    continue
                if (setting == "pagingcodep"):
                    bitwise.int_to_bcd(_settings.pagingcodep,
                                       int(element.value))
                    continue
                if re.match('pagingcode\d', setting):
                    idx = int(setting[-1:]) - 1
                    bitwise.int_to_bcd(_settings.pagingcode[idx].digits,
                                       int(element.value))
                    continue
                newval = element.value
                oldval = getattr(_settings, setting)
                if setting == "cwid":
                    newval = self._encode_cwid(newval)
                LOG.debug("Setting %s(%s) <= %s" % (setting, oldval, newval))
                setattr(_settings, setting, newval)
            except Exception:
                LOG.debug(element.get_name())
                raise

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    def sync_out(self):
        self.update_checksums()
        return _clone_out(self)


def _clone_out(radio):
    try:
        return __clone_out(radio)
    except Exception, e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


def __clone_out(radio):
    pipe = radio.pipe
    block_lengths = radio._block_lengths
    total_written = 0

    def _status():
        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        status.max = sum(block_lengths)
        status.cur = total_written
        radio.status_fn(status)

    start = time.time()

    blocks = 0
    pos = 0
    for block in radio._block_lengths:
        blocks += 1
        data = radio.get_mmap()[pos:pos + block]
        # LOG.debug(util.hexprint(data))

        recvd = ""
        # Radio echos every block received
        for byte in data:
            time.sleep(0.01)
            pipe.write(byte)
            # flush & sleep so don't loose ack
            pipe.flush()
            time.sleep(0.015)
            recvd += pipe.read(1)  # chew the echo
        # LOG.debug(util.hexprint(recvd))
        LOG.debug("Bytes sent: %i" % len(data))

        # Radio does not ack last block
        if (blocks < 8):
            buf = pipe.read(block)
            LOG.debug("ACK attempt: " + util.hexprint(buf))
            if buf and buf[0] != chr(yaesu_clone.CMD_ACK):
                buf = pipe.read(block)
            if not buf or buf[-1] != chr(yaesu_clone.CMD_ACK):
                raise errors.RadioError("Radio did not ack block %i" % blocks)

        total_written += len(data)
        _status()
        pos += block

    pipe.read(pos)  # Chew the echo if using a 2-pin cable

    LOG.debug("Clone completed in %i seconds" % (time.time() - start))
