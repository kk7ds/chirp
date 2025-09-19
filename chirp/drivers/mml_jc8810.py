# Copyright 2023 Jim Unroe <rock.unroe@gmail.com>
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
    RadioSettingValueMap,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  lbcd rxfreq[4];     // 0-3
  lbcd txfreq[4];     // 4-7
  ul16 rxtone;        // 8-9
  ul16 txtone;        // A-B
  u8 unknown1:4,      // C
     scode:4;         //     Signaling
  u8 unknown2:6,      // D
     pttid:2;         //     PTT-ID
  u8 scramble:6,      //     Scramble
     txpower:2;       //     Power Level  0 = H, 1 = L, 2 = M
  u8 unknown4:1,      // F
     narrow:1,        //     Bandwidth  0 = Wide, 1 = Narrow
     encrypt:2,       //     Encrypt
     bcl:1,           //     BCL
     scan:1,          //     Scan  0 = Skip, 1 = Scan
     unknown5:1,      //
     learning:1;      //     Learning
  lbcd code[3];       // 0-2 Code
  u8 unknown6;        // 3
  char name[12];      // 4-F 12-character Alpha Tag
} memory[%d];

#seekto 0x9000;
struct {
  u8 unused:4,        // 9000
     sql:4;           //      Squelch Level
  u8 unused_9001:6,   // 9001
     save:2;          //      Battery Save
  u8 unused_9002:4,   // 9002
     vox:4;           //      VOX Level
  u8 unused_9003:4,   // 9003
     abr:4;           //      Auto BackLight
  u8 unused_9004:7,   // 9004
     tdr:1;           //      TDR
  u8 unused_9005:5,   // 9005
     tot:3;           //      Time-out Timer
  u8 unused_9006:7,   // 9006
     beep:1;          //      Beep
  u8 unused_9007:7,   // 9007
     voice:1;         //      Voice Prompt
  u8 unused_9008:7,   // 9008
     language:1;      //      Language
  u8 unused_9009:6,   // 9009
     dtmfst:2;        //      DTMF ST
  u8 unused_900a:6,   // 900A
     screv:2;         //      Scan Mode
  u8 unused_900B:4,   // 900B
     pttid:4;         //      PTT-ID
  u8 unused_900c:5,   // 900C
     pttlt:3;         //      PTT Delay
  u8 unused_900d:6,   // 900D
     mdfa:2;          //      Channel_A Display
  u8 unused_900e:6,   // 900E
     mdfb:2;          //      Channel_B Display
  u8 unknown_900f;    // 900F
  u8 unused_9010:4,   // 9010
     autolk:4;        //      Key Auto Lock
  u8 unused_9011:6,   // 9011
     almode:2;        //      Alarm Mode
  u8 unused_9012:7,   // 9012
     alarmsound:1;    //      Alarm Sound
  u8 unused_9013:6,   // 9013
     dualtx:2;        //      Dual TX
  u8 unused_9014:7,   // 9014
     ste:1;           //      Tail Noise Clear
  u8 unused_9015:4,   // 9015
     rpste:4;         //      RPT Noise Clear
  u8 unused_9016:4,   // 9016
     rptrl:4;         //      RPT Noise Delay
  u8 unused_9017:6,   // 9017
     roger:2;         //      Roger
  u8 unknown_9018;    // 9018
  u8 unused_9019:7,   // 9019
     fmradio:1;       //      FM Radio
  u8 unused_901a1:3,  // 901A
     vfomrb:1,        //      WorkMode B
     unused_901a2:3,  //
     vfomra:1;        //      WorkMode A
  u8 unused_901b:7,   // 901B
     kblock:1;        //      KB Lock
  u8 unused_901c:7,   // 901C
     ponmsg:1;        //      Power On Msg
  u8 unknown_901d;    // 901D
  u8 unused_901e:6,   // 901E
     tone:2;          //      Pilot
  u8 unknown_901f;    // 901F
  u8 unused_9020:4,   // 9020
     voxd:4;          //      VOX Delay
  u8 unused_9021:4,   // 9021
     menuquit:4;      //      Menu Auto Quit
  u8 unused_9022:7,   // 9022
     tailcode:1;      //      Tail Code (RT-470L)
  u8 unknown_9023;    // 9023
  u8 unlock_sw_ch;    // 9024 UNLOCK SW CH (A36plus 8w)
  u8 unknown_9025;    // 9025
  u8 unknown_9026;    // 9026
  u8 unknown_9027;    // 9027
  u8 unknown_9028;    // 9028
  u8 unused_9029:6,   // 9029
     qtsave:2;        //      QT Save Type
  u8 ani;             // 902A ANI
  u8 skey2_sp;        // 902B Skey2 Short
  u8 skey2_lp;        // 902C Skey2 Long
  u8 skey3_sp;        // 902D Skey3 Short
  u8 topkey_sp;       // 902E Top Key (RT-470L)
  u8 unused_902f:6,   // 902F
     rxendtail:2;     //      RX END TAIL (RT-470)
                      //      TAIL PHASE (A36plus)
  u8 skey3_lp;        // 9030 Skey3 Long (RT-470L)
                      //      RX END TAIL (A36plus)
  u8 unknown_9031;    // 9031
  u8 unknown_9032;    // 9032
  u8 unknown_9033;    // 9033
  u8 unknown_9034;    // 9034
  u8 unknown_9035;    // 9035
  u8 unknown_9036;    // 9036
  u8 unknown_9037;    // 9037
  u8 unknown_9038;    // 9038
  u8 unknown_9039;    // 9039
  u8 unknown_903a;    // 903a
  u8 single_mode;     // 903b SINGLE MODE (A36plus 8w)
  u8 dis_s_table;     // 903b DIS S TABLE (A36plus 8w)
} settings;

#seekto 0xA006;
struct {
  u8 unknown_A006;    // A006
  u8 unused_a007:5,   // A007
     dtmfon:3;        //      DTMF Speed (on time)
  u8 unused_a008:5,   // A008
     dtmfoff:3;       //      DTMF Speed (off time)
} dtmf;

#seekto 0xA020;
struct {
  u8 code[5];         //      5-character DTMF Encoder Groups
  u8 unused[11];
} pttid[15];

#seekto 0xB000;
struct {
  u8 code[3];         //      3-character ANI Code Groups
} anicodes[60];

#seekto 0xB0C0;
struct {
  char name[10];      //      10-character ANI Code Group Names
  u8 unused[6];
} aninames[%d];

"""

MEM_FORMAT_A36PLUS = """
#seekto 0xB200;
struct {
  char name[10];      //      10-character Custom CH Names (Talkpod A36plus)
  u8 unused[6];
} customnames[30];

"""


CMD_ACK = b"\x06"

DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

DTMF_CHARS = "0123456789 *#ABCD"

TXPOWER_HIGH = 0x00
TXPOWER_LOW = 0x01
TXPOWER_MID = 0x02

ABR_LIST = ["On", "5 seconds", "10 seconds", "15 seconds", "20 seconds",
            "30 seconds", "1 minute", "2 minutes", "3 minutes"]
ALMODE_LIST = ["Site", "Tone", "Code"]
AUTOLK_LIST = ["Off"] + ABR_LIST[1:4]
DTMFSPEED_LIST = ["50 ms", "100 ms", "200 ms", "300 ms", "500 ms"]
DTMFST_LIST = ["Off", "KeyBoard Side Tone", "ANI Side Tone", "KB ST + ANI ST"]
DUALTX_LIST = ["Off", "A", "B"]
ENCRYPT_LIST = ["Off", "DCP1", "DCP2", "DCP3"]
LANGUAGE_LIST = ["English", "Chinese"]
MDF_LIST = ["Name", "Frequency", "Channel"]
MENUQUIT_LIST = ["%s seconds" % x for x in range(5, 55, 5)] + ["60 seconds"]
OFF1TO9_LIST = ["Off"] + ["%s" % x for x in range(1, 10)]
PONMSG_LIST = ["Logo", "Voltage"]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 16)]
PTTLT_LIST = ["None", "100 ms"] + \
             ["%s ms" % x for x in range(200, 1200, 200)]
QTSAVE_LIST = ["All", "RX", "TX"]
ROGER_LIST = ["OFF", "BEEP", "TONE1200"]
RPSTE_LIST = ["Off"] + ["%s ms" % x for x in range(100, 1100, 100)]
SAVE_LIST = ["Off", "Normal", "Super", "Deep"]
SCREV_LIST = ["Time (TO)", "Carrier (CO)", "Search (SE)"]
TAILCODE_LIST = ["55 Hz", "62.5 Hz"]
TAILPHASE_LIST = ["None", "120 Shift", "180 Shift", "240 Shift"]
TONERXEND_LIST = ["Off", "MDC-1200"]
TONE_LIST = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
TOT_LIST = ["Off", "30 seconds", "60 seconds", "120 seconds", "240 seconds",
            "480 seconds"]
VOXD_LIST = ["%s seconds" % str(x / 10) for x in range(5, 21)]
WORKMODE_LIST = ["VFO Mode", "Channel Mode"]

ALL_SKEY_CHOICES = ["OFF",
                    "FM Radio",
                    "TX Power Level",
                    "Scan",
                    "Search",
                    "Flashlight",
                    "NOAA Weather",
                    "Monitor",
                    "PTT B",
                    "SOS",
                    "DTMF",
                    "REVERSE",
                    "REMOTE Scan"]

ALL_SKEY_VALUES = [0xFF,
                   0x07,
                   0x0A,
                   0x1C,
                   0x1D,
                   0x08,
                   0x0C,
                   0x05,
                   0x01,
                   0x03,
                   0x2A,
                   0x2D,
                   0x23]

SCRAMBLE_VALUEMAP = [("Off", 0x00), ("SCRAM1", 0x04), ("SCRAM2", 0x08)]


def _enter_programming_mode(radio):
    serial = radio.pipe

    exito = False
    for i in range(0, 5):
        serial.write(radio._magic)
        ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except Exception:
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
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if ident not in radio._fingerprint:
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    if radio.MODEL == "RT-470X":
        if ident in radio._fingerprint_pcb1:
            LOG.info("Radtel RT-470X - original pcb")
            radio.RT470X_ORIG = True
        elif ident in radio._fingerprint_pcb2:
            LOG.info("Radtel RT-470X - pcb2")
            radio.RT470X_ORIG = False


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
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
    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except Exception:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)

    _exit_programming_mode(radio)


class JC8810base(chirp_common.CloneModeRadio):
    """MML JC-8810"""
    VENDOR = "MML"
    MODEL = "JC-8810base"
    BAUD_RATE = 57600
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x40

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=10.00),
                    chirp_common.PowerLevel("M", watts=8.00),
                    chirp_common.PowerLevel("L", watts=4.00)]

    VALID_BANDS = [(108000000, 136000000),
                   (136000000, 180000000),
                   (200000000, 260000000),
                   (330000000, 400000000),
                   (400000000, 520000000)]

    _magic = b"PROGRAMJC81U"
    _fingerprint = [b"\x00\x00\x00\x26\x00\x20\xD8\x04",
                    b"\x00\x00\x00\x42\x00\x20\xF0\x04",
                    b"\x00\x00\x00\x4A\x00\x20\xF8\x04"]

    _ranges = [
               (0x0000, 0x2000),
               (0x8000, 0x8040),
               (0x9000, 0x9040),
               (0xA000, 0xA140),
               (0xB000, 0xB300)
              ]
    _memsize = 0xB300
    _upper = 256
    _aninames = 30
    _mem_params = (_upper,  # number of channels
                   _aninames,  # number of aninames
                   )
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
        rf.valid_name_length = 12
        rf.valid_characters = self._valid_chars
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
        rf.valid_dtcs_codes = DTCS
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 8.33, 10., 12.5, 20., 25., 50.]
        rf.valid_bands = self.VALID_BANDS
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
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
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number - 1]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if _mem.get_raw()[:1] == b"\xFF":
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if chirp_common.is_split(self.get_features().valid_bands,
                                         mem.freq, int(_mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        for char in _mem.name:
            if str(char) == "\xFF":
                char = " "  # may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip().replace('\x00', '')

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
            mem.dtcs = DTCS[index]
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
            mem.rx_dtcs = DTCS[index]
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

        _levels = self.POWER_LEVELS
        if self.MODEL in ["A36plus", "A36plus_8w", "UV-A37", "AR-730"]:
            if _mem.txpower == TXPOWER_HIGH:
                mem.power = _levels[0]
            elif _mem.txpower == TXPOWER_LOW:
                mem.power = _levels[1]
            else:
                LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                          (mem.name, _mem.txpower))
        else:
            if _mem.txpower == TXPOWER_HIGH:
                mem.power = _levels[0]
            elif _mem.txpower == TXPOWER_MID:
                mem.power = _levels[1]
            elif _mem.txpower == TXPOWER_LOW:
                mem.power = _levels[2]
            else:
                LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                          (mem.name, _mem.txpower))

        mem.mode = _mem.narrow and "NFM" or "FM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        # Encryption
        rs = RadioSettingValueList(ENCRYPT_LIST, current_index=_mem.encrypt)
        rset = RadioSetting("encrypt", "Encryption", rs)
        mem.extra.append(rset)

        # Scramble
        rs = RadioSettingValueMap(SCRAMBLE_VALUEMAP, _mem.scramble)
        rset = RadioSetting("scramble", "Scramble", rs)
        mem.extra.append(rset)

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

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xff" * 32)
            return

        _mem.set_raw("\x00" * 16 + "\xFF" * 16)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xFF")
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
                _mem.name[i] = mem.name[i]
            except IndexError:
                _mem.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = DTCS.index(mem.dtcs) + 1
            _mem.rxtone = DTCS.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = DTCS.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = DTCS.index(mem.rx_dtcs) + 1
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

        _levels = self.POWER_LEVELS
        if self.MODEL in ["A36plus", "A36plus_8w", "UV-A37", "AR-730"]:
            if mem.power is None:
                _mem.txpower = TXPOWER_HIGH
            elif mem.power == _levels[0]:
                _mem.txpower = TXPOWER_HIGH
            elif mem.power == _levels[1]:
                _mem.txpower = TXPOWER_LOW
            else:
                LOG.error('%s: set_mem: unhandled power level: %s' %
                          (mem.name, mem.power))
        else:
            if mem.power is None:
                _mem.txpower = TXPOWER_HIGH
            elif mem.power == _levels[0]:
                _mem.txpower = TXPOWER_HIGH
            elif mem.power == _levels[1]:
                _mem.txpower = TXPOWER_MID
            elif mem.power == _levels[2]:
                _mem.txpower = TXPOWER_LOW
            else:
                LOG.error('%s: set_mem: unhandled power level: %s' %
                          (mem.name, mem.power))

        for setting in mem.extra:
            if setting.get_name() == "scramble_type":
                setattr(_mem, setting.get_name(), int(setting.value) + 8)
                setattr(_mem, "scramble_type2", int(setting.value) + 8)
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _dtmf = self._memobj.dtmf
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Menu 12: TOT
        rs = RadioSettingValueList(TOT_LIST, current_index=_settings.tot)
        rset = RadioSetting("tot", "Time Out Timer", rs)
        basic.append(rset)

        # Menu 00: SQL
        rs = RadioSettingValueInteger(0, 9, _settings.sql)
        rset = RadioSetting("sql", "Squelch Level", rs)
        basic.append(rset)

        # Menu 13: VOX
        rs = RadioSettingValueList(OFF1TO9_LIST, current_index=_settings.vox)
        rset = RadioSetting("vox", "VOX", rs)
        basic.append(rset)

        # Menu 39: VOX DELAY
        rs = RadioSettingValueList(VOXD_LIST, current_index=_settings.voxd)
        rset = RadioSetting("voxd", "VOX Delay", rs)
        basic.append(rset)

        # Menu 15: VOICE
        rs = RadioSettingValueBoolean(_settings.voice)
        rset = RadioSetting("voice", "Voice Prompts", rs)
        basic.append(rset)

        if self.MODEL not in ["A36plus", "A36plus_8w", "UV-A37", "AR-730"]:
            # Menu 17: LANGUAGE
            rs = RadioSettingValueList(LANGUAGE_LIST,
                                       current_index=_settings.language)
            rset = RadioSetting("language", "Voice", rs)
            basic.append(rset)

        # Menu 23: ABR
        rs = RadioSettingValueList(ABR_LIST, current_index=_settings.abr)
        rset = RadioSetting("abr", "Auto BackLight", rs)
        basic.append(rset)

        # Work Mode A
        rs = RadioSettingValueList(WORKMODE_LIST,
                                   current_index=_settings.vfomra)
        rset = RadioSetting("vfomra", "Work Mode A", rs)
        basic.append(rset)

        # Work Mode B
        rs = RadioSettingValueList(WORKMODE_LIST,
                                   current_index=_settings.vfomrb)
        rset = RadioSetting("vfomrb", "Work Mode B", rs)
        basic.append(rset)

        # Menu 19: SC-REV
        rs = RadioSettingValueList(SCREV_LIST, current_index=_settings.screv)
        rset = RadioSetting("screv", "Scan Resume Method", rs)
        basic.append(rset)

        # Menu 10: SAVE
        rs = RadioSettingValueList(SAVE_LIST,
                                   current_index=_settings.save)
        rset = RadioSetting("save", "Battery Save Mode", rs)
        basic.append(rset)

        # Menu 42: MDF-A
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfa)
        rset = RadioSetting("mdfa", "Memory Display Format A", rs)
        basic.append(rset)

        # Menu 43: MDF-B
        rs = RadioSettingValueList(MDF_LIST, current_index=_settings.mdfb)
        rset = RadioSetting("mdfb", "Memory Display Format B", rs)
        basic.append(rset)

        # Menu 33: DTMFST (DTMF ST)
        rs = RadioSettingValueList(DTMFST_LIST, current_index=_settings.dtmfst)
        rset = RadioSetting("dtmfst", "DTMF Side Tone", rs)
        basic.append(rset)

        # Menu 37: PTT-LT
        rs = RadioSettingValueList(PTTLT_LIST, current_index=_settings.pttlt)
        rset = RadioSetting("pttlt", "PTT Delay", rs)
        basic.append(rset)

        rs = RadioSettingValueInteger(1, 60, _settings.ani + 1)
        rset = RadioSetting("ani", "ANI", rs)
        basic.append(rset)

        # Menu 20: PF2
        def apply_skey2s_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) + " from list")
            val = str(setting.value)
            index = SKEY2S_CHOICES.index(val)
            val = SKEY2S_VALUES[index]
            obj.set_value(val)

        if self.MODEL in ["HI-8811", "RT-470L", "RT-470X", "RT-470X_BT",
                          "RT-470"]:
            unwanted = [9, 10, 11, 12]
        elif self.MODEL in ["UV-A37", "AR-730"]:
            unwanted = [0, 5, 7, 9, 10, 11, 12]
        elif self.MODEL in ["A36plus", "A36plus_8w"]:
            unwanted = [0, 5, 7, 9, 10, 11]
        elif self.MODEL in ["RT-630", "RT-495"]:
            unwanted = [5, 9, 10, 11, 12]
        else:
            unwanted = []
        SKEY2S_CHOICES = ALL_SKEY_CHOICES.copy()
        SKEY2S_VALUES = ALL_SKEY_VALUES.copy()
        for ele in sorted(unwanted, reverse=True):
            del SKEY2S_CHOICES[ele]
            del SKEY2S_VALUES[ele]

        if _settings.skey2_sp in SKEY2S_VALUES:
            idx = SKEY2S_VALUES.index(_settings.skey2_sp)
        else:
            idx = SKEY2S_VALUES.index(0x07)  # default FM
        rs = RadioSettingValueList(SKEY2S_CHOICES, current_index=idx)
        rset = RadioSetting("skey2_sp", "PF2 Key (Short Press)", rs)
        rset.set_apply_callback(apply_skey2s_listvalue, _settings.skey2_sp)
        basic.append(rset)

        # Menu 21: PF2 LONG PRESS
        def apply_skey2l_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) + " from list")
            val = str(setting.value)
            index = SKEY2L_CHOICES.index(val)
            val = SKEY2L_VALUES[index]
            obj.set_value(val)

        if self.MODEL in ["HI-8811", "RT-470L", "RT-470X", "RT-470X_BT",
                          "RT-470"]:
            unwanted = [8, 9, 10, 11, 12]
        elif self.MODEL in ["UV-A37", "AR-730"]:
            unwanted = [0, 5, 7, 8, 10, 11, 12]
        elif self.MODEL in ["A36plus", "A36plus_8w"]:
            unwanted = [0, 5, 7, 8, 11, 12]
        elif self.MODEL in ["RT-630", "RT-495"]:
            unwanted = [5, 9, 10, 11, 12]
        else:
            unwanted = []
        SKEY2L_CHOICES = ALL_SKEY_CHOICES.copy()
        SKEY2L_VALUES = ALL_SKEY_VALUES.copy()
        for ele in sorted(unwanted, reverse=True):
            del SKEY2L_CHOICES[ele]
            del SKEY2L_VALUES[ele]

        if _settings.skey2_lp in SKEY2L_VALUES:
            idx = SKEY2L_VALUES.index(_settings.skey2_lp)
        else:
            idx = SKEY2L_VALUES.index(0x1D)  # default Search
        rs = RadioSettingValueList(SKEY2L_CHOICES, current_index=idx)
        rset = RadioSetting("skey2_lp", "PF2 Key (Long Press)", rs)
        rset.set_apply_callback(apply_skey2l_listvalue, _settings.skey2_lp)
        basic.append(rset)

        # Menu 22: PF3
        def apply_skey3s_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) + " from list")
            val = str(setting.value)
            index = SKEY3S_CHOICES.index(val)
            val = SKEY3S_VALUES[index]
            obj.set_value(val)

        if self.MODEL in ["HI-8811", "RT-470L", "RT-470X", "RT-470X_BT",
                          "RT-470"]:
            unwanted = [8, 9, 10, 11, 12]
        elif self.MODEL in ["UV-A37", "AR-730"]:
            unwanted = [0, 5, 7, 8, 9, 10, 11, 12]
        elif self.MODEL in ["A36plus", "A36plus_8w"]:
            unwanted = [0, 5, 7, 8, 11]
        elif self.MODEL in ["RT-630", "RT-495"]:
            unwanted = [5, 9, 10, 11, 12]
        else:
            unwanted = []
        SKEY3S_CHOICES = ALL_SKEY_CHOICES.copy()
        SKEY3S_VALUES = ALL_SKEY_VALUES.copy()
        for ele in sorted(unwanted, reverse=True):
            del SKEY3S_CHOICES[ele]
            del SKEY3S_VALUES[ele]

        if _settings.skey3_sp in SKEY3S_VALUES:
            idx = SKEY3S_VALUES.index(_settings.skey3_sp)
        else:
            idx = SKEY3S_VALUES.index(0x0C)  # default NOAA
        rs = RadioSettingValueList(SKEY3S_CHOICES, current_index=idx)
        rset = RadioSetting("skey3_sp", "PF3 Key (Short Press)", rs)
        rset.set_apply_callback(apply_skey3s_listvalue, _settings.skey3_sp)
        basic.append(rset)

        if self.MODEL in ["HI-8811", "RT-470L", "RT-470X", "RT-470X_BT",
                          "RT-470", "RT-630", "RT-495"]:
            # Menu 24: PF3 LONG PRESS (RT-470L)
            def apply_skey3l_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = SKEY3L_CHOICES.index(val)
                val = SKEY2L_VALUES[index]
                obj.set_value(val)

            if self.MODEL in ["HI-8811", "RT-470L", "RT-470X", "RT-470X_BT",
                              "RT-470"]:
                unwanted = [8, 9, 10, 11, 12]
            elif self.MODEL in ["RT-630", "RT-495"]:
                unwanted = [5, 9, 10, 11, 12]
            else:
                unwanted = []
            SKEY3L_CHOICES = ALL_SKEY_CHOICES.copy()
            SKEY3L_VALUES = ALL_SKEY_VALUES.copy()
            for ele in sorted(unwanted, reverse=True):
                del SKEY3L_CHOICES[ele]
                del SKEY3L_VALUES[ele]

            if _settings.skey3_lp in SKEY3L_VALUES:
                idx = SKEY3L_VALUES.index(_settings.skey3_lp)
            else:
                idx = SKEY3L_VALUES.index(0x1D)  # default SEARCH
            rs = RadioSettingValueList(SKEY3L_CHOICES, current_index=idx)
            rset = RadioSetting("skey3_lp", "PF3 Key (Long Press)", rs)
            rset.set_apply_callback(apply_skey3l_listvalue,
                                    _settings.skey3_lp)
            basic.append(rset)

        # Menu 25: TOP KEY (RT-470L)
        def apply_skeytop_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) +
                      " from list")
            val = str(setting.value)
            index = SKEYTOP_CHOICES.index(val)
            val = SKEYTOP_VALUES[index]
            obj.set_value(val)

        if self.MODEL in ["HI-8811", "RT-470L", "RT-470X", "RT-470X_BT",
                          "RT-470"]:
            unwanted = [8, 9, 10, 11, 12]
        elif self.MODEL in ["UV-A37", "AR-730"]:
            unwanted = [0, 5, 7, 8, 9, 10, 11, 12]
        elif self.MODEL in ["A36plus", "A36plus_8w"]:
            unwanted = [0, 5, 7, 8, 11]
        else:
            unwanted = []
        SKEYTOP_CHOICES = ALL_SKEY_CHOICES.copy()
        SKEYTOP_VALUES = ALL_SKEY_VALUES.copy()
        for ele in sorted(unwanted, reverse=True):
            del SKEYTOP_CHOICES[ele]
            del SKEYTOP_VALUES[ele]

        if _settings.topkey_sp in SKEYTOP_VALUES:
            idx = SKEYTOP_VALUES.index(_settings.topkey_sp)
        else:
            idx = SKEYTOP_VALUES.index(0x1D)  # default SEARCH
        rs = RadioSettingValueList(SKEYTOP_CHOICES, current_index=idx)
        rset = RadioSetting("topkey_sp", "Top Key (Short Press)", rs)
        rset.set_apply_callback(apply_skeytop_listvalue,
                                _settings.topkey_sp)
        basic.append(rset)

        # Mneu 36: TONE
        rs = RadioSettingValueList(TONE_LIST, current_index=_settings.tone)
        rset = RadioSetting("tone", "Tone-burst Frequency", rs)
        basic.append(rset)

        # Mneu 29: POWER ON MSG
        rs = RadioSettingValueList(PONMSG_LIST, current_index=_settings.ponmsg)
        rset = RadioSetting("ponmsg", "Power On Message", rs)
        basic.append(rset)

        if self.MODEL in ["HI-8811", "RT-470L", "RT-470X", "RT-470X_BT",
                          "RT-630", "RT-495"]:
            rs = RadioSettingValueList(TAILCODE_LIST,
                                       current_index=_settings.tailcode)
            rset = RadioSetting("tailcode", "Tail Code", rs)
            basic.append(rset)

        # Menu 46: STE
        rs = RadioSettingValueBoolean(_settings.ste)
        rset = RadioSetting("ste", "Squelch Tail Eliminate (HT to HT)", rs)
        basic.append(rset)

        # Menu 40: RP-STE
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rpste)
        rset = RadioSetting("rpste", "Squelch Tail Eliminate (repeater)", rs)
        basic.append(rset)

        # Menu 41: RPT-RL
        rs = RadioSettingValueList(RPSTE_LIST, current_index=_settings.rptrl)
        rset = RadioSetting("rptrl", "STE Repeater Delay", rs)
        basic.append(rset)

        # Menu 38: MENU EXIT TIME
        rs = RadioSettingValueList(MENUQUIT_LIST,
                                   current_index=_settings.menuquit)
        rset = RadioSetting("menuquit", "Menu Auto Quit", rs)
        basic.append(rset)

        # Menu 34: AUTOLOCK
        rs = RadioSettingValueList(AUTOLK_LIST, current_index=_settings.autolk)
        rset = RadioSetting("autolk", "Key Auto Lock", rs)
        basic.append(rset)

        # Menu 28: CDCSS SAVE MODE
        rs = RadioSettingValueList(QTSAVE_LIST, current_index=_settings.qtsave)
        rset = RadioSetting("qtsave", "QT Save Type", rs)
        basic.append(rset)

        # Menu 45: TX-A/B
        rs = RadioSettingValueList(DUALTX_LIST, current_index=_settings.dualtx)
        rset = RadioSetting("dualtx", "Dual TX", rs)
        basic.append(rset)

        # Menu 47: AL-MODE
        rs = RadioSettingValueList(ALMODE_LIST, current_index=_settings.almode)
        rset = RadioSetting("almode", "Alarm Mode", rs)
        basic.append(rset)

        # Menu 11: ROGER
        # ==========
        # Notice to developers:
        # The RT-470 v1.22 firmware expanded the ROGER menu with an additional
        # choice, 'TONE1200'. RT-470 radios with a firmware version prior to
        #  v1.22 will not honor the ROGER menu's 'TONE1200' choice in CHIRP.
        # ==========
        rs = RadioSettingValueList(ROGER_LIST, current_index=_settings.roger)
        rset = RadioSetting("roger", "Roger", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.alarmsound)
        rset = RadioSetting("alarmsound", "Alarm Sound", rs)
        basic.append(rset)

        # Menu 44: TDR
        rs = RadioSettingValueBoolean(_settings.tdr)
        rset = RadioSetting("tdr", "TDR", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(not _settings.fmradio)
        rset = RadioSetting("fmradio", "FM Radio", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.kblock)
        rset = RadioSetting("kblock", "KB Lock", rs)
        basic.append(rset)

        # Menu 16: BEEP PROMPT
        rs = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("beep", "Beep", rs)
        basic.append(rset)

        if self.MODEL not in ["A36plus", "A36plus_8w", "UV-A37", "AR-730"]:
            # Menu 48: RX END TAIL
            rs = RadioSettingValueList(TONERXEND_LIST,
                                       current_index=_settings.rxendtail)
            rset = RadioSetting("rxendtail", "Tone RX End", rs)
            basic.append(rset)

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
            rs = RadioSettingValueString(0, 5, _code, False)
            rs.set_charset(DTMF_CHARS)
            rset = RadioSetting("pttid/%i.code" % i,
                                "PTT-ID Code %i" % (i + 1), rs)
            rset.set_apply_callback(apply_code, self._memobj.pttid[i], 5)
            dtmf.append(rset)

        rs = RadioSettingValueList(DTMFSPEED_LIST,
                                   current_index=_dtmf.dtmfon)
        rset = RadioSetting("dtmf.dtmfon", "DTMF Speed (on)", rs)
        dtmf.append(rset)

        rs = RadioSettingValueList(DTMFSPEED_LIST,
                                   current_index=_dtmf.dtmfoff)
        rset = RadioSetting("dtmf.dtmfoff", "DTMF Speed (off)", rs)
        dtmf.append(rset)

        # RT470X Plus Bluetooth does not seem to have correct PTTID setting
        if self.MODEL not in ["RT-470X_BT"]:
            rs = RadioSettingValueList(
                PTTID_LIST, current_index=_settings.pttid)
            rset = RadioSetting("pttid", "PTT ID", rs)
            dtmf.append(rset)

        ani = RadioSettingGroup("ani", "ANI Code List Settings")
        group.append(ani)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in self._valid_chars:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        end = 60 - self._aninames  # end of immutable ANI names
        for i in range(0, end):
            _codeobj = self._memobj.anicodes[i].code
            _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            rs = RadioSettingValueString(0, 3, _code, False)
            rs.set_charset(DTMF_CHARS)
            rset = RadioSetting("anicodes/%i.code" % i,
                                "ANI Code %i (NUM.%i)" % (i + 1, i + 1), rs)
            rset.set_apply_callback(apply_code, self._memobj.anicodes[i], 3)
            ani.append(rset)

        for i in range(end, 60):
            _codeobj = self._memobj.anicodes[i].code
            _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            rs = RadioSettingValueString(0, 3, _code, False)
            rs.set_charset(DTMF_CHARS)
            rset = RadioSetting("anicodes/%i.code" % (i),
                                "ANI Code %i" % (i + 1), rs)
            rset.set_apply_callback(apply_code,
                                    self._memobj.anicodes[i], 3)
            ani.append(rset)

            _nameobj = self._memobj.aninames[i - end].name
            rs = RadioSettingValueString(0, 10, _filter(_nameobj))
            rset = RadioSetting("aninames/%i.name" % (i - end),
                                "ANI Code %i Name" % (i + 1), rs)
            ani.append(rset)

        if self.MODEL in ["A36plus", "A36plus_8w"]:
            custom = RadioSettingGroup("custom", "Custom Channel Names")
            group.append(custom)

            for i in range(0, 30):
                _nameobj = self._memobj.customnames[i].name
                rs = RadioSettingValueString(0, 10, _filter(_nameobj))
                rset = RadioSetting("customnames/%i.name" % i,
                                    "Custom Name %i" % (i + 1), rs)
                custom.append(rset)

        if self.MODEL in ["A36plus", "A36plus_8w"]:
            # Menu 21: RX END TAIL
            rs = RadioSettingValueList(TONERXEND_LIST,
                                       current_index=_settings.skey3_lp)
            rset = RadioSetting("skey3_lp", "RX End Tail", rs)
            basic.append(rset)

            # Menu 23: TAIL PHASE
            rs = RadioSettingValueList(TAILPHASE_LIST,
                                       current_index=_settings.rxendtail)
            rset = RadioSetting("rxendtail", "Tail Phase", rs)
            basic.append(rset)

            # Menu 20: SINGLE MODE
            rs = RadioSettingValueBoolean(_settings.single_mode)
            rset = RadioSetting("single_mode", "Single Display Mode", rs)
            basic.append(rset)

            # Menu 48: UNLOCK SW CH
            rs = RadioSettingValueBoolean(_settings.unlock_sw_ch)
            rset = RadioSetting("unlock_sw_ch",
                                "Override KB Lock for Channel Keys", rs)
            basic.append(rset)

            # Menu 49: DIS S TABLE
            rs = RadioSettingValueBoolean(_settings.dis_s_table)
            rset = RadioSetting("dis_s_table", "Display S Meter", rs)
            basic.append(rset)

        return group

    def set_settings(self, settings):
        _settings = self._memobj.settings
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
                    elif setting == "ani":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "fmradio":
                        setattr(obj, setting, not int(element.value))
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name(), e)
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RT470Radio(JC8810base):
    """Radtel RT-470"""
    VENDOR = "Radtel"
    MODEL = "RT-470"

    # ==========
    # Notice to developers:
    # The RT-470 support in this driver is currently based upon...
    # - v1.25a firmware (original pcb)
    # - v2.11a firmware (pcb2)
    # ==========

    # original pcb
    _fingerprint_pcb1 = [b"\x00\x00\x00\x26\x00\x20\xD8\x04",
                         b"\x00\x00\x00\x42\x00\x20\xF0\x04",
                         b"\x00\x00\x00\x4A\x00\x20\xF8\x04",
                         b"\x00\x00\x00\x3A\x00\x20\xE8\x04",  # fw 1.25A
                         b"\x00\x00\x00\x42\x00\x20\xec\x04",  # fw 1.27A
                         ]

    # pcb 2
    _fingerprint_pcb2 = [b"\x00\x00\x00\x28\x00\x20\xD4\x04",  # fw v2.00
                         b"\x00\x00\x00\x2C\x00\x20\xD8\x04",  # fw v2.11A
                         b"\x00\x00\x00\x36\x00\x20\xDC\x04",  # fw v2.13A
                         ]

    _fingerprint = _fingerprint_pcb1 + _fingerprint_pcb2

    VALID_BANDS = [(16000000, 100000000),
                   (100000000, 136000000),
                   (136000000, 200000000),
                   (200000000, 300000000),
                   (300000000, 400000000),
                   (400000000, 560000000),
                   (740000000, 1000000000),
                   ]


@directory.register
class RT470LRadio(JC8810base):
    """Radtel RT-470L"""
    VENDOR = "Radtel"
    MODEL = "RT-470L"

    # ==========
    # Notice to developers:
    # The RT-470 support in this driver is currently based upon v1.17 firmware.
    # ==========

    _fingerprint = [b"\x00\x00\x00\xfe\x00\x20\xAC\x04",
                    b"\x00\x00\x00\x20\x00\x20\xCC\x04",
                    b"\x00\x00\x00\x20\x00\x20\x07\x00"]

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=5.00),
                    chirp_common.PowerLevel("M", watts=4.00),
                    chirp_common.PowerLevel("L", watts=2.00)]

    VALID_BANDS = [(108000000, 136000000),
                   (136000000, 179000000),
                   (220000000, 260000000),
                   (330000000, 400000000),
                   (400000000, 520000000)]


@directory.register
class RT470XRadio(RT470LRadio):
    """Radtel RT-470X"""
    VENDOR = "Radtel"
    MODEL = "RT-470X"

    # ==========
    # Notice to developers:
    # The RT-470X support in this driver is currently based upon...
    # - v1.18a firmware (original pcb)
    # - v2.13a firmware (pcb2)
    # ==========

    # original pcb
    _fingerprint_pcb1 = [b"\x00\x00\x00\x20\x00\x20\xCC\x04",
                         ]

    # pcb 2
    _fingerprint_pcb2 = [b"\x00\x00\x00\x2C\x00\x20\xD8\x04",  # fw v2.10A
                         b"\x00\x00\x00\x36\x00\x20\xDC\x04",  # fw v2.13A
                         ]

    _fingerprint = _fingerprint_pcb1 + _fingerprint_pcb2
    RT470X_ORIG = False
    VALID_BANDS = [(100000000, 136000000),
                   (136000000, 200000000),
                   (200000000, 300000000),
                   (300000000, 400000000),
                   (400000000, 560000000)]
    _AIRBAND = (118000000, 136000000)

    def get_features(self):
        rf = super().get_features()
        rf.valid_modes.append('AM')
        rf.valid_modes.append('NAM')
        rf.valid_bands = [(18000000, 1000000000)]
        return rf

    def validate_memory(self, mem):
        msgs = []
        in_range = chirp_common.in_range
        AM_mode = mem.mode == 'AM' or mem.mode == "NAM"
        if in_range(mem.freq, [self._AIRBAND]) and not AM_mode:
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range requires AM mode')))
        if not in_range(mem.freq, [self._AIRBAND]) and AM_mode:
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range must not be AM mode')))
        return msgs + super().validate_memory(mem)

    def get_memory(self, number):
        mem = super().get_memory(number)
        _mem = self._memobj.memory[mem.number - 1]
        if chirp_common.in_range(mem.freq, [self._AIRBAND]):
            mem.mode = _mem.narrow and "NAM" or "AM"
        return mem


@directory.register
class RT470XPlusRadio(RT470XRadio):
    """Radtel RT-470X Plus BT"""
    VENDOR = "Radtel"
    MODEL = "RT-470X_BT"
    RT470X_ORIG = False  # BT fingerprint will fall automatically here

    # BT version
    _fingerprint_bt = [b"\x01\x36\x01\x80\x04\x00\x05\x20"  # fw v0.15
                       ]
    _fingerprint = _fingerprint_bt


@directory.register
class HI8811Radio(RT470LRadio):
    """Hiroyasu HI-8811"""
    VENDOR = "Hiroyasu"
    MODEL = "HI-8811"

    # ==========
    # Notice to developers:
    # The HI-8811 support in this driver is currently based upon...
    # - v1.17 firmware (original pcb)
    # - v2.00 firmware (pcb2)
    # ==========

    # original pcb
    _fingerprint_pcb1 = [b"\x00\x00\x00\xfe\x00\x20\xAC\x04",
                         b"\x00\x00\x00\x20\x00\x20\xCC\x04",  # fw v1.17
                         b"\x00\x00\x00\x20\x00\x20\x07\x00",
                         ]

    # pcb 2
    _fingerprint_pcb2 = [b"\x00\x00\x00\x28\x00\x20\xD4\x04",  # fw v2.00
                         b"\x00\x00\x00\x28\x00\x20\x07\x00",  # fw v2.00
                         ]

    _fingerprint = _fingerprint_pcb1 + _fingerprint_pcb2


@directory.register
class UVA37Radio(JC8810base):
    """Anysecu UV-A37"""
    VENDOR = "Anysecu"
    MODEL = "UV-A37"

    # ==========
    # Notice to developers:
    # The UV-A37 support in this driver is currently based upon v1.24
    # firmware.
    # ==========

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=5.00),
                    chirp_common.PowerLevel("L", watts=1.00)]

    VALID_BANDS = [(108000000, 136000000),
                   (136000000, 174000000),
                   (200000000, 260000000),
                   (350000000, 390000000),
                   (400000000, 520000000)]

    _magic = b"PROGRAMJC37U"
    _fingerprint = [b"\x00\x00\x00\xE4\x00\x20\x94\x04",
                    b"\x00\x00\x00\xE8\x00\x20\x98\x04"]

    _ranges = [
               (0x0000, 0x2000),
               (0x8000, 0x8040),
               (0x9000, 0x9040),
               (0xA000, 0xA140),
               (0xB000, 0xB440)
              ]
    _memsize = 0xB440


@directory.register
class A36plusRadio(JC8810base):
    """Talkpod A36plus"""
    VENDOR = "Talkpod"
    MODEL = "A36plus"

    # ==========
    # Notice to developers:
    # The A36plus support in this driver is currently based upon v1.26
    # firmware.
    # ==========

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=5.00),
                    chirp_common.PowerLevel("L", watts=1.00)]

    VALID_BANDS = [(108000000, 136000000),
                   (136000000, 180000000),
                   (200000000, 260000000),
                   (350000000, 400000000),
                   (400000000, 520000000),
                   ]

    _magic = b"PROGRAMJC37U"
    _fingerprint = [b"\x00\x00\x00\x42\x00\x20\xF0\x04",
                    b"\x00\x00\x00\x5A\x00\x20\x08\x05",  # fw 1.18
                    b"\x00\x00\x00\x9E\x00\x20\x0C\x05",  # fw 1.22
                    b"\x00\x00\x00\xFA\x00\x20\x40\x05",  # fw 1.4
                    b"\x00\x00\x00\x9C\x00\x20\x04\x05",  # fw 1.26
                    ]

    _ranges = [
               (0x0000, 0x4000),
               (0x8000, 0x8040),
               (0x9000, 0x9040),
               (0xA000, 0xA140),
               (0xB000, 0xB440)
              ]
    _memsize = 0xB440
    _upper = 512  # fw 1.22 expands from 256 to 512 channels
    _aninames = 10
    _mem_params = (_upper,  # number of channels
                   _aninames,  # number of aninames
                   )

    def process_mmap(self):
        mem_format = MEM_FORMAT % self._mem_params + MEM_FORMAT_A36PLUS
        self._memobj = bitwise.parse(mem_format, self._mmap)


@directory.register
class A36plus8wRadio(A36plusRadio):
    """Talkpod A36plus8w"""
    VENDOR = "Talkpod"
    MODEL = "A36plus_8w"

    # ==========
    # Notice to developers:
    # The A36plus 8w support in this driver is currently based upon v1.6
    # firmware.
    # ==========

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=8.00),
                    chirp_common.PowerLevel("L", watts=1.00)]

    _fingerprint = [b"\x00\x00\x00\xFA\x00\x20\x40\x05",  # fw 1.4
                    b"\x00\x00\x00\xD8\x00\x20\x58\x05",  # fw 1.6
                    ]


@directory.register
class AR730Radio(UVA37Radio):
    """Abbree AR730"""
    VENDOR = "Abbree"
    MODEL = "AR-730"

    # ==========
    # Notice to developers:
    # The AR-730 support in this driver is currently based upon v1.24
    # firmware.
    # ==========

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=5.00),
                    chirp_common.PowerLevel("L", watts=1.00)]

    VALID_BANDS = [(108000000, 136000000),
                   (136000000, 180000000),
                   (200000000, 260000000),
                   (350000000, 390000000),
                   (400000000, 520000000)]


@directory.register
class RT630Radio(JC8810base):
    """Radtel RT-630"""
    VENDOR = "Radtel"
    MODEL = "RT-630"

    # ==========
    # Notice to developers:
    # The RT-630 support in this driver is currently based upon v0.07 firmware.
    # ==========

    _fingerprint = [b"\x00\x00\x00\x32\x00\x20\xD8\x04",  # fw 0.07
                    b"\x00\x00\x00\x36\x00\x20\xDC\x04",  # fw V0.09 20250703
                    ]

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=5.00),
                    chirp_common.PowerLevel("M", watts=4.00),
                    chirp_common.PowerLevel("L", watts=2.00)]

    VALID_BANDS = [(18000000, 108000000),
                   (108000000, 136000000),
                   (136000000, 300000000),
                   (300000000, 660000000),
                   (840000000, 1000000000)]

    _ranges = [
               (0x0000, 0x2000),
               (0x8000, 0x8040),
               (0x9000, 0x9040),
               (0xA000, 0xA140),
               (0xB000, 0xB2C0),
               (0xB500, 0xB740)
               ]
    _memsize = 0xB740


@directory.register
class RT495Radio(RT630Radio):
    """Radtel RT-495"""
    VENDOR = "Radtel"
    MODEL = "RT-495"

    # ==========
    # Notice to developers:
    # The RT-495 support in this driver is currently based upon v0.07 firmware.
    # ==========

    _fingerprint = [b"\x00\x00\x00\x24\x00\x20\xD0\x04",  # fw 0.06
                    b"\x00\x00\x00\x32\x00\x20\xD8\x04",  # fw 0.07
                    ]
