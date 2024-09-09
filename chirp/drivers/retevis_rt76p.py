# Copyright 2021-2022 Jim Unroe <rock.unroe@gmail.com>
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

import logging
import struct

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];     // 0-3
  lbcd txfreq[4];     // 4-7
  ul16 rxtone;        // 8-9
  ul16 txtone;        // A-B
  u8 unknown1:4,      // C
     scode:4;         //     Signal
  u8 unknown2:6,      // D
     pttid:2;         //     PTT-ID
  u8 unknown3:7,      // E
     lowpower:1;      //     Power Level 0 = High, 1 = Low
  u8 ani:1,           // F   ANI
     narrow:1,        //     Bandwidth  0 = Wide, 1 = Narrow
     unknown4:2,
     bcl:1,           //     BCL
     scan:1,          //     Scan  0 = Skip, 1 = Scan
     unknown5:1,
     compand:1;       //     Compand
} memory[128];

#seekto 0x0C00;
struct {
  char name[10];      // 10-character Alpha Tag
  u8 unused[6];
} names[128];

#seekto 0x1A00;
struct {
  u8 unknown:4,       // 1A00
     squelch:4;       //      Squelch Level
  u8 unknown_1a01:7,  // 1A01
     save:1;          //      Save Mode
  u8 unknown_1a02:4,  // 1A04
     vox:4;           // 1A02 VOX Level
  u8 unknown_1a03:4,  // 1A03
     abr:4;           //      Auto Backlight Time-out
  u8 unknown_1a04:7,  // 1A04
     tdr:1;           //      Dual Standby
  u8 tot;             // 1A05 Time-out Timer
  u8 unknown_1a06:7,  // 1A06
     beep:1;          //      Beep
  u8 unknown_1a07:7,  // 1A07
     voice:1;         //      Voice Switch
  u8 unknown_1a08:7,  // 1A08
     language:1;      //      Language
  u8 unknown_1a09:6,  // 1A09
     dtmfst:2;        //      DTMF ST
  u8 unknown_101a:6,  // 1A0A
     scmode:2;        //      Scan Mode
  u8 unknown_1a0a;    // 1A0B
  u8 pttlt;           // 1A0C PTT Delay
  u8 unknown_1a0d:6,  // 1A0D
     mdfa:2;          //      Channel A Display
  u8 unknown_1a0e:6,  // 1A0E
     mdfb:2;          //      Channel B Display
  u8 unknown_1a0f:7,  // 1A0F
     bcl:1;           //      BCL
  u8 unknown_1a10:7,  // 1A10
     autolock:1;      //      AutoLock
  u8 unknown_1a11:6,  // 1A11
     almod:2;         //      Alarm Mode
  u8 unknown_1a12:7,  // 1A12
     alarm:1;         //      Alarm Sound
  u8 unknown_1a13:6,  // 1A13
     tdrab:2;         //      Tx Under TDR Start
  u8 unknown_1a14:7,  // 1A14
     ste:1;           //      Tail Noise Clear
  u8 unknown_1a15:4,  // 1A15
     rpste:4;         //      Pass Repeat Noise
  u8 unknown_1a16:4,  // 1A16
     rptrl:4;         //      Pass Repeat Noise
  u8 unknown_1a17:7,  // 1A17
     roger:1;         //      Roger
  u8 unknown_1a18;    // 1A18
  u8 unknown_1a19:7,  // 1A19
     fmradio:1;       //      FM Radio (inverted)
  u8 unknown_1a1a:7,  // 1A1A
     workmode:1;      //      Work Mode
  u8 unknown_1a1b:7,  // 1A1B
     kblock:1;        //      KB_Lock
  u8 unknown_1a1c:6,  // 1A1C
     pwronmsg:2;      //      Pwr On Msg
  u8 unknown_1a1d;    // 1A1D
  u8 unknown_1a1e:6,  // 1A1E
     tone:2;          //      Tone
  u8 unknown_1a1f;    // 1A1F
  u8 unknown_1a20[7]; // 1A20-1A26
  u8 unknown_1a27:6,  // 1A27
     wtled:2;         //      Wait Backlight Color
  u8 unknown_1a28:6,  // 1A28
     rxled:2;         //      Rx Backlight Color
  u8 unknown_1a29:6,  // 1A29
     txled:2;         //      Tx Backlight Color
} settings;

#seekto 0x1A80;
struct {
  u8 shortp;          // 1A80 Skey Short
  u8 longp;           // 1A81 Skey Long
} skey;

#seekto 0x1B00;
struct {
  u8 code[6];         // 6-character PTT-ID Code
  u8 unused[10];
} pttid[15];

#seekto 0x1BF0;
struct {
  u8 code[6];         // ANI Code
  u8 unknown111;
  u8 dtmfon;          // DTMF Speed (on time)
  u8 dtmfoff;         // DTMR Speed (off time)
  u8 unused222[7];
  u8 killword[6];     // Kill Word
  u8 unused333[2];
  u8 revive[6];       // Revive
  u8 unused444[2];
} dtmf;

#seekto 0x1FE0;
struct {
  char line1[16];     // Power-on Message Line 1
  char line2[16];     // Power-on Message Line 2
} poweron_msg;
"""


CMD_ACK = b"\x06"

RT76P_DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

DTMF_CHARS = "0123456789 *#ABCD"

ALMOD_LIST = ["On Site", "Send Sound", "Send Code"]
BACKLIGHT_LIST = ["Off", "Blue", "Orange", "Purple"]
DTMFSPEED_LIST = ["%s ms" % x for x in range(50, 2010, 10)]
DTMFST_LIST = ["Off", "KeyBboard Side Tone", "ANI Side Tone", "KB ST + ANI ST"]
LANGUAGE_LIST = ["English", "China"]
MDF_LIST = ["Name", "Frequency", "Number"]
OFF1TO10_LIST = ["Off"] + ["%s" % x for x in range(1, 11)]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 16)]
PWRONMSG_LIST = ["Picture", "Message", "Voltage"]
RPSTE_LIST = ["Off"] + ["%s" % x for x in range(100, 1100, 100)]
SCMODE_LIST = ["Time (TO)", "Carrier (CO)", "Search (SE)"]
TDRAB_LIST = ["Off", "A Band", "B Band"]
TIMEOUTTIMER_LIST = ["%s seconds" % x for x in range(15, 615, 15)]
TONE_LIST = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
VOICE_LIST = ["Off", "On"]
WORKMODE_LIST = ["VFO Mode", "Channel Mode"]

SKEY_CHOICES = ["FM", "Tx Power", "Moni", "Scan", "Offline", "Weather"]
SKEY_VALUES = [0x07, 0x0A, 0x05, 0x1C, 0x0B, 0x0C]

GMRS_FREQS1 = [462562500, 462587500, 462612500, 462637500, 462662500,
               462687500, 462712500]
GMRS_FREQS2 = [467562500, 467587500, 467612500, 467637500, 467662500,
               467687500, 467712500]
GMRS_FREQS3 = [462550000, 462575000, 462600000, 462625000, 462650000,
               462675000, 462700000, 462725000]
GMRS_FREQS = GMRS_FREQS1 + GMRS_FREQS2 + GMRS_FREQS3 * 2


def _rt76p_enter_programming_mode(radio):
    serial = radio.pipe

    exito = False
    for i in range(0, 5):
        serial.write(radio._magic)
        ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    try:
        serial.write(b"F")
        ident = serial.read(8)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ident == radio._fingerprint:
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")


def _rt76p_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _rt76p_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"R" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _rt76p_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    serial = radio.pipe
    LOG.debug("download")
    _rt76p_enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _rt76p_read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _rt76p_exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _rt76p_enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            _rt76p_write_block(radio, addr, radio.BLOCK_SIZE_UP)

    _rt76p_exit_programming_mode(radio)


@directory.register
class RT76PRadio(chirp_common.CloneModeRadio):
    """RETEVIS RT76P"""
    VENDOR = "Retevis"
    MODEL = "RT76P"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x20

    RT76P_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                          chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PROGROMCD2U"
    _fingerprint = b"\x01\x36\x01\x74\x04\x00\x05\x20"

    _ranges = [
               (0x0000, 0x0820),
               (0x0C00, 0x1400),
               (0x1A00, 0x1C20),
              ]
    _memsize = 0x2000
    _valid_chars = chirp_common.CHARSET_ALPHANUMERIC + \
        "`~!@#$%^&*()-=_+[]\\{}|;':\",./<>?"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.valid_name_length = 10
        rf.valid_characters = self._valid_chars
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.RT76P_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
        rf.valid_dtcs_codes = RT76P_DTCS
        rf.memory_bounds = (1, 128)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 20., 25., 50.]
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 480000000)]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw(asbytes=False)
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw(asbytes=False)[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if offset > 0:
                    mem.duplex = "+"
                    mem.offset = 5000000
            else:
                mem.duplex = ""
                mem.offset = 0

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "  # may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = RT76P_DTCS[index]
        else:
            LOG.warn("Bug: txtone is %04x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.rx_dtcs = RT76P_DTCS[index]
        else:
            LOG.warn("Bug: rxtone is %04x" % _mem.rxtone)

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        mem.power = self.RT76P_POWER_LEVELS[_mem.lowpower]

        mem.mode = _mem.narrow and "NFM" or "FM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        # BCL (Busy Channel Lockout)
        rs = RadioSettingValueBoolean(_mem.bcl)
        rset = RadioSetting("bcl", "BCL", rs)
        mem.extra.append(rset)

        # PTT-ID
        rs = RadioSettingValueList(PTTID_LIST, current_index=_mem.pttid)
        rset = RadioSetting("pttid", "PTT ID", rs)
        mem.extra.append(rset)

        # Signal (DTMF Encoder Group #)
        rs = RadioSettingValueList(PTTIDCODE_LIST, current_index=_mem.scode)
        rset = RadioSetting("scode", "PTT ID Code", rs)
        mem.extra.append(rset)

        # Compand
        rs = RadioSettingValueBoolean(_mem.compand)
        rset = RadioSetting("compand", "Compand", rs)
        mem.extra.append(rset)

        # ANI
        rs = RadioSettingValueBoolean(_mem.ani)
        rset = RadioSetting("ani", "ANI", rs)
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

        _mem.set_raw("\x00" * 16)

        if mem.freq in GMRS_FREQS1:
            mem.duplex == ''
            mem.offset = 0
        elif mem.freq in GMRS_FREQS2:
            mem.duplex == ''
            mem.offset = 0
            mem.mode = "NFM"
            mem.power = self.RT76P_POWER_LEVELS[1]
        elif mem.freq in GMRS_FREQS3:
            if mem.duplex == '+':
                mem.offset = 5000000
            else:
                mem.duplex == ''
                mem.offset = 0
        else:
            mem.duplex = 'off'
            mem.offset = 0

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = RT76P_DTCS.index(mem.dtcs) + 1
            _mem.rxtone = RT76P_DTCS.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = RT76P_DTCS.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = RT76P_DTCS.index(mem.rx_dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.narrow = mem.mode == "NFM"

        _mem.lowpower = mem.power == self.RT76P_POWER_LEVELS[1]

        for setting in mem.extra:
            if setting.get_name() == "scramble_type":
                setattr(_mem, setting.get_name(), int(setting.value) + 8)
                setattr(_mem, "scramble_type2", int(setting.value) + 8)
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _dtmf = self._memobj.dtmf
        _settings = self._memobj.settings
        _skey = self._memobj.skey
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Menu 00: Squelch (Squelch Level)
        rs = RadioSettingValueInteger(0, 9, _settings.squelch)
        rset = RadioSetting("squelch", "Squelch Level", rs)
        basic.append(rset)

        # Menu 01: Step (VFO setting)
        # Menu 02: Tx Power (VFO setting - not available)

        # Menu 03: Power save (Save Mode)
        rs = RadioSettingValueBoolean(_settings.save)
        rset = RadioSetting("save", "Power Save", rs)
        basic.append(rset)

        # Menu 04: Vox Level (VOX)
        rs = RadioSettingValueList(OFF1TO10_LIST, current_index=_settings.vox)
        rset = RadioSetting("vox", "VOX Level", rs)
        basic.append(rset)

        # Menu 05: Bandwidth

        # Menu 06: Backlight (Auto Backlight)
        rs = RadioSettingValueList(OFF1TO10_LIST,
                                   current_index=_settings.abr)
        rset = RadioSetting("abr", "Backlight Time-out", rs)
        basic.append(rset)

        # Menu 07: Dual Standby (TDR)
        rs = RadioSettingValueBoolean(_settings.tdr)
        rset = RadioSetting("tdr", "Dual Standby", rs)
        basic.append(rset)

        # Menu 08: Beep Prompt
        rs = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("beep", "Beep Prompt", rs)
        basic.append(rset)

        # Menu 09: Voice (Voice Switch)
        rs = RadioSettingValueBoolean(_settings.voice)
        rset = RadioSetting("voice", "Voice Prompts", rs)
        basic.append(rset)

        # Menu 10: Tx over time (Time Out)
        rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                   current_index=_settings.tot - 1)
        rset = RadioSetting("tot", "Time-out Timer", rs)
        basic.append(rset)

        # Menu 11: Rx DCS
        # Menu 12: Rx CTCSS
        # Menu 13: Tx DCS
        # Menu 14: Tx CTCSS
        # Menu 15: Voice Compand

        # Menu 16: DTMFST (DTMF ST)
        rs = RadioSettingValueList(DTMFST_LIST, current_index=_settings.dtmfst)
        rset = RadioSetting("dtmfst", "DTMF Side Tone", rs)
        basic.append(rset)

        # Mneu 17: R-TONE (Tone)
        rs = RadioSettingValueList(TONE_LIST, current_index=_settings.tone)
        rset = RadioSetting("tone", "Tone-burst Frequency", rs)
        basic.append(rset)

        # Menu 18: S-CODE

        # Menu 19: Scan Mode
        rs = RadioSettingValueList(SCMODE_LIST, current_index=_settings.scmode)
        rset = RadioSetting("scmode", "Scan Resume Method", rs)
        basic.append(rset)

        # Menu 20: ANI Match
        # Menu 21: PTT-ID

        # Menu 22: MDF-A (Channle_A Display)
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfa)
        rset = RadioSetting("mdfa", "Memory Display Format A", rs)
        basic.append(rset)

        # Menu 23: MDF-B (Channle_B Display)
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfb)
        rset = RadioSetting("mdfb", "Memory Display Format B", rs)
        basic.append(rset)

        # Menu 24: Busy Lockout

        # Menu 25: Key Auto Lock (AutoLock)
        rs = RadioSettingValueBoolean(_settings.autolock)
        rset = RadioSetting("autolock", "Keypad Auto Lock", rs)
        basic.append(rset)

        # Menu 26: WT-LED (Wait Backlight)
        rs = RadioSettingValueList(BACKLIGHT_LIST,
                                   current_index=_settings.wtled)
        rset = RadioSetting("wtled", "Wait Backlight Color", rs)
        basic.append(rset)

        # Menu 27: RX-LED (Rx Backlight)
        rs = RadioSettingValueList(BACKLIGHT_LIST,
                                   current_index=_settings.rxled)
        rset = RadioSetting("rxled", "RX Backlight Color", rs)
        basic.append(rset)

        # Menu 28: TX-LED (Tx Backlight)
        rs = RadioSettingValueList(BACKLIGHT_LIST,
                                   current_index=_settings.txled)
        rset = RadioSetting("txled", "TX Backlight Color", rs)
        basic.append(rset)

        # Menu 29: Alarm Mode
        rs = RadioSettingValueList(ALMOD_LIST, current_index=_settings.almod)
        rset = RadioSetting("almod", "Alarm Mode", rs)
        basic.append(rset)

        # Menu 30: TAIL (Tail Noise Clear)
        rs = RadioSettingValueBoolean(_settings.ste)
        rset = RadioSetting("ste", "Squelch Tail Eliminate", rs)
        basic.append(rset)

        # Menu 31: PROGRE (Roger)
        rs = RadioSettingValueBoolean(_settings.roger)
        rset = RadioSetting("roger", "Roger Beep", rs)
        basic.append(rset)

        # Menu 32: Language
        rs = RadioSettingValueList(LANGUAGE_LIST,
                                   current_index=_settings.language)
        rset = RadioSetting("language", "Language", rs)
        basic.append(rset)

        # Menu 33: OPENMGS (Pwr On Msg)
        rs = RadioSettingValueList(PWRONMSG_LIST,
                                   current_index=_settings.pwronmsg)
        rset = RadioSetting("pwronmsg", "Power On Message", rs)
        basic.append(rset)

        dtmfchars = "0123456789ABCD*#"

        # Menu 34: ANI ID (display only)
        _codeobj = self._memobj.dtmf.code
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 6, _code, False)
        val.set_charset(dtmfchars)
        val.set_mutable(False)
        rs = RadioSetting("dtmf.code", "Query ANI ID", val)
        basic.append(rs)

        # Menu 35: Reset

        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        group.append(advanced)

        # Work Mode
        rs = RadioSettingValueList(WORKMODE_LIST,
                                   current_index=_settings.workmode)
        rset = RadioSetting("workmode", "Work Mode", rs)
        advanced.append(rset)

        # PTT Delay
        rs = RadioSettingValueInteger(0, 30, _settings.pttlt)
        rset = RadioSetting("pttlt", "PTT ID Delay", rs)
        advanced.append(rset)

        def apply_skey_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) + " from list")
            val = str(setting.value)
            index = SKEY_CHOICES.index(val)
            val = SKEY_VALUES[index]
            obj.set_value(val)

        # Skey Short
        if _skey.shortp in SKEY_VALUES:
            idx = SKEY_VALUES.index(_skey.shortp)
        else:
            idx = SKEY_VALUES.index(0x0C)
        rs = RadioSettingValueList(SKEY_CHOICES, current_index=idx)
        rset = RadioSetting("skey.shortp", "Side Key (Short Press)", rs)
        rset.set_apply_callback(apply_skey_listvalue, _skey.shortp)
        advanced.append(rset)

        # Skey Long
        if _skey.longp in SKEY_VALUES:
            idx = SKEY_VALUES.index(_skey.longp)
        else:
            idx = SKEY_VALUES.index(0x0C)
        rs = RadioSettingValueList(SKEY_CHOICES, current_index=idx)
        rset = RadioSetting("skey.longp", "Side Key (Long Press)", rs)
        rset.set_apply_callback(apply_skey_listvalue, _skey.longp)
        advanced.append(rset)

        # Pass Repeat Noise
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rpste)
        rset = RadioSetting("rpste", "Squelch Tail Eliminate (repeater)", rs)
        advanced.append(rset)

        # Pass Repeat Noise
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rptrl)
        rset = RadioSetting("rptrl", "STE Repeater Delay", rs)
        advanced.append(rset)

        # KB_Lock
        rs = RadioSettingValueBoolean(_settings.kblock)
        rset = RadioSetting("kblock", "Keypad Lock", rs)
        advanced.append(rset)

        # FM Radio Enable
        rs = RadioSettingValueBoolean(not _settings.fmradio)
        rset = RadioSetting("fmradio", "Broadcast FM Radio", rs)
        advanced.append(rset)

        # Alarm Sound
        rs = RadioSettingValueBoolean(_settings.alarm)
        rset = RadioSetting("alarm", "Alarm Sound", rs)
        advanced.append(rset)

        # Tx Under TDR Start
        rs = RadioSettingValueList(TDRAB_LIST, current_index=_settings.tdrab)
        rset = RadioSetting("tdrab", "Dual Standby TX Priority", rs)
        advanced.append(rset)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        _msg = self._memobj.poweron_msg
        rs = RadioSetting("poweron_msg.line1", "Power-On Message 1",
                          RadioSettingValueString(
                              0, 16, _filter(_msg.line1)))
        advanced.append(rs)
        rs = RadioSetting("poweron_msg.line2", "Power-On Message 2",
                          RadioSettingValueString(
                              0, 16, _filter(_msg.line2)))
        advanced.append(rs)

        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        group.append(dtmf)

        def apply_code(setting, obj, length):
            code = []
            for j in range(0, length):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code

        for i in range(0, 15):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 6, _code, False)
            val.set_charset(DTMF_CHARS)
            pttid = RadioSetting("pttid/%i.code" % i,
                                 "Signal Code %i" % (i + 1), val)
            pttid.set_apply_callback(apply_code, self._memobj.pttid[i], 6)
            dtmf.append(pttid)

        _codeobj = self._memobj.dtmf.killword
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 6, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("dtmf.killword", "Kill Word", val)
        rs.set_apply_callback(apply_code, self._memobj.dtmf, 6)
        dtmf.append(rs)

        _codeobj = self._memobj.dtmf.revive
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 6, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("dtmf.revive", "Revive Word", val)
        rs.set_apply_callback(apply_code, self._memobj.dtmf, 6)
        dtmf.append(rs)

        _codeobj = self._memobj.dtmf.code
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 6, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("dtmf.code", "ANI Code", val)
        rs.set_apply_callback(apply_code, self._memobj.dtmf, 6)
        dtmf.append(rs)

        if _dtmf.dtmfon > 0xC3:
            val = 0x00
        else:
            val = _dtmf.dtmfon
        rs = RadioSetting("dtmf.dtmfon", "DTMF Speed (on)",
                          RadioSettingValueList(DTMFSPEED_LIST,
                                                current_index=val))
        dtmf.append(rs)

        if _dtmf.dtmfoff > 0xC3:
            val = 0x00
        else:
            val = _dtmf.dtmfoff
        rs = RadioSetting("dtmf.dtmfoff", "DTMF Speed (off)",
                          RadioSettingValueList(DTMFSPEED_LIST,
                                                current_index=val))
        dtmf.append(rs)

        return group

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
                    elif setting == "fmradio":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "tot":
                        setattr(obj, setting, int(element.value) + 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False
