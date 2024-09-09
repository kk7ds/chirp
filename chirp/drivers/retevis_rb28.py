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

import struct
import logging

from chirp import (
    bandplan_iaru_r1,
    bandplan_na,
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
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  u8 rxtone;           // PL/DPL Decode          8
  u8 unused_9;         //                        9
  u8 txtone;           // PL/DPL Encode          A
  u8 unused_b;         //                        B
  u8 compander:1,      // Compander              C
     unused_1:1,       //
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     unused_2:4;       //
  u8 reserved[3];      // Reserved               D-F
} memory[%d];

#seekto 0x002D;
struct {
  u8 unknown_2d_7:1,   //                        002D
     unknown_2d_6:1,   //
     unknown_2d_5:1,   //
     savem:1,          // Battery Save Set
     save:1,           // Battery Save
     beep:1,           // Beep
     voice:1,          // Voice Prompts
     unused_2d_0:1;    //
  u8 squelch;          // Squelch                002E
  u8 tot;              // Time-out Timer         002F
  u8 channel_4[13];    //                        0030-003C
  u8 unused_3d;        //                        003D
  u8 voxl;             // Vox Level              003E
  u8 voxd;             // Vox Delay              003F
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_3[3];     //                        004D-004F
  u8 channel_6[13];    //                        0050-005C
  u8 unknown_4[3];     //                        005D-005F
  u8 channel_7[13];    //                        0060-006C
  u8 volume;           // Volume                 006D
  u8 tone;             // Tone                   006E
  u8 chnumber;         // Channel                006F
  u8 channel_8[13];    //                        0070-007C
  u8 unknown_7d;       //                        007D
  u8 scan;             // Scan                   007E
  u8 backlight;        // Back Light             007F
  u8 channel_9[13];    //                        0080-008C
  u8 wxchnumber;       // Weather Channel        008D
  u8 wxwarn;           // Weather Warn           008E
  u8 roger;            // End Tone               008F
  u8 channel_10[13];   //                        0090-009C
  u8 unknown_9d;       //                        009D
  u8 keylock;          // Key Lock               009E
  u8 unknown_9f;       //                        009F
  u8 channel_11[13];   //                        00A0-00AC
  u8 unknown_ad;       //                        00AD
  u8 unknown_ae;       //                        00AE
  u8 unknown_af;       //                        00AF
  u8 channel_12[13];   //                        00B0-00BC
  u8 autokeylock;      // Key Lock               00BD
  u8 pfkey_lt;         // Key Set < Long         00BE
  u8 pfkey_gt;         // Key Set > Long         00BB
} settings;

#seekto 0x00AD;
struct {
u8 chnl_8:1,      // Busy Channel Lockout  8     00AD
   chnl_7:1,      // Busy Channel Lockout  7
   chnl_6:1,      // Busy Channel Lockout  6
   chnl_5:1,      // Busy Channel Lockout  5
   chnl_4:1,      // Busy Channel Lockout  4
   chnl_3:1,      // Busy Channel Lockout  3
   chnl_2:1,      // Busy Channel Lockout  2
   chnl_1:1;      // Busy Channel Lockout  1
u8 chnl_16:1,     // Busy Channel Lockout 16     00AE
   chnl_15:1,     // Busy Channel Lockout 15
   chnl_14:1,     // Busy Channel Lockout 14
   chnl_13:1,     // Busy Channel Lockout 13
   chnl_12:1,     // Busy Channel Lockout 12
   chnl_11:1,     // Busy Channel Lockout 11
   chnl_10:1,     // Busy Channel Lockout 10
   chnl_9:1;      // Busy Channel Lockout 09
u8 unused_af_7:1, //                             00AF
   unused_af_6:1, //
   chnl_22:1,     // Busy Channel Lockout 22
   chnl_21:1,     // Busy Channel Lockout 21
   chnl_20:1,     // Busy Channel Lockout 20
   chnl_19:1,     // Busy Channel Lockout 19
   chnl_18:1,     // Busy Channel Lockout 18
   chnl_17:1;     // Busy Channel Lockout 17
} bclo;
"""

CMD_ACK = b"\x06"

BACKLIGHT_LIST = ["Off", "ON", "5S", "10S", "15S", "30S"]
PFKEY_US_LIST = ["None", "Weather", "Warn", "Call", "Monitor"]
PFKEY_EU_LIST = ["None", "Warn", "Call", "Monitor"]
SAVE_LIST = ["Normal", "Super"]
TIMEOUTTIMER_LIST = ["%s seconds" % x for x in range(15, 195, 15)]
VOICE_LIST = ["Off", "English"]
VOXD_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
VOXL_LIST = ["OFF"] + ["%s" % x for x in range(1, 10)]

PMR_TONES = tuple(
    set(chirp_common.TONES) - set([69.3, 159.8, 165.5, 171.3, 177.3,
                                   183.5, 189.9, 196.6, 199.5, 206.5,
                                   229.1, 254.1]))

PMR_DTCS_CODES = tuple(
    set(chirp_common.DTCS_CODES) - set([36,  53, 122, 145, 212,
                                        225, 246, 252, 255, 266,
                                        274, 325, 332, 356, 446,
                                        452, 454, 455, 462, 523,
                                        526]))


def _enter_programming_mode(radio):
    serial = radio.pipe

    _magic = radio._magic

    try:
        serial.write(_magic)
        for i in range(1, 5):
            ack = serial.read(1)
            if ack == CMD_ACK:
                break
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio")
    elif ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write(b"\x02")
        ident = serial.read(8)
    except:
        raise errors.RadioError("Error communicating with radio")

    # check if ident is OK
    for fp in radio._fingerprint:
        if fp in ident:
            break
    else:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        if block_addr != 0 or radio._ack_1st_block:
            serial.write(CMD_ACK)
            ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if block_addr != 0 or radio._ack_1st_block:
        if ack != CMD_ACK:
            raise Exception("No ACK reading block %04x." % (block_addr))

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
    except:
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


@directory.register
class RB28Radio(chirp_common.CloneModeRadio):
    """RETEVIS RB28"""
    VENDOR = "Retevis"
    MODEL = "RB28"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    TONES = PMR_TONES
    DTCS_CODES = PMR_DTCS_CODES
    PFKEY_LIST = PFKEY_US_LIST
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.50),
                    chirp_common.PowerLevel("Low", watts=0.50)]
    VALID_BANDS = [(400000000, 480000000)]

    _magic = b"PHOGR\x0B\x28"
    _fingerprint = [b"P32073" + b"\x02\xFF",
                    b"P32073" + b"\x00\xFF",
                    ]
    _upper = 22
    _mem_params = (_upper,  # number of channels
                   )
    _ack_1st_block = False
    _reserved = True
    _frs = True

    _ranges = [
               (0x0000, 0x0160),
              ]
    _memsize = 0x0160

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = []
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "off"]
        rf.valid_modes = ["FM", "NFM"]  # 25 kHz, 12.5 kHz.
        rf.valid_tones = self.TONES
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = self.VALID_BANDS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params,
                                     self._mmap)

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

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):

        mem = chirp_common.Memory()

        mem.number = number

        _mem = self._memobj.memory[number - 1]

        if self._reserved:
            _rsvd = _mem.reserved.get_raw(asbytes=False)

        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw(asbytes=False) == "\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        if _mem.txtone in [0, 0xFF]:
            txmode = ""
        elif _mem.txtone < 0x27:
            mem.rtone = PMR_TONES[_mem.txtone - 1]
            txmode = "Tone"
        elif _mem.txtone >= 0x27:
            tcode = PMR_DTCS_CODES[_mem.txtone - 0x27]
            mem.dtcs = tcode
            txmode = "DTCS"
        else:
            LOG.warn("Bug: tx_mode is %02x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFF]:
            rxmode = ""
        elif _mem.rxtone < 0x27:
            mem.ctone = PMR_TONES[_mem.rxtone - 1]
            rxmode = "Tone"
        elif _mem.rxtone >= 0x27:
            rcode = PMR_DTCS_CODES[_mem.rxtone - 0x27]
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        else:
            LOG.warn("Bug: rx_mode is %02x" % _mem.rxtone)

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.power = self.POWER_LEVELS[1 - _mem.highpower]

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSettingValueBoolean(_mem.compander)
        rset = RadioSetting("compander", "Compander", rs)
        mem.extra.append(rset)

        _obj = self._memobj.bclo
        key = "chnl_%i" % (mem.number)
        rs = RadioSettingValueBoolean(getattr(_obj, "chnl_%i" % (mem.number)))
        rset = RadioSetting(key, "Busy Channel Lockout", rs)
        mem.extra.append(rset)

        immutable = []

        if self._frs:
            if mem.number >= 1 and mem.number <= 22:
                # 22 FRS fixed channels
                FRS_FREQ = bandplan_na.ALL_GMRS_FREQS[mem.number - 1]
                mem.freq = FRS_FREQ
                mem.duplex == ''
                mem.offset = 0
                mem.mode = "NFM"
                immutable = ["empty", "freq", "duplex", "offset", "mode"]
                if mem.number >= 8 and mem.number <= 14:
                    mem.power = self.POWER_LEVELS[1]
                    immutable += ["power"]
        elif self._pmr:
            if mem.number >= 1 and mem.number <= 16:
                # 16 PMR fixed channels
                PMR_FREQ = bandplan_iaru_r1.PMR446_FREQS[mem.number - 1]
                mem.freq = PMR_FREQ
                mem.duplex = ''
                mem.offset = 0
                mem.mode = "NFM"
                mem.power = self.POWER_LEVELS[1]
                immutable = ["empty", "freq", "duplex", "offset", "mode",
                             "power"]

        mem.immutable = immutable

        return mem

    def _set_tone(self, _mem, which, value, mode):
        if mode == "Tone":
            val = PMR_TONES.index(value) + 1
        elif mode == "DTCS":
            val = PMR_DTCS_CODES.index(value) + 0x27
        elif mode == "":
            val = 0
        else:
            raise errors.RadioError("Internal error: tmode %s" % mode)

        setattr(_mem, which, val)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if self._reserved:
            _rsvd = _mem.reserved.get_raw(asbytes=False)

        if mem.empty:
            if self._reserved:
                _mem.set_raw("\xFF" * 13 + _rsvd)
            else:
                _mem.set_raw("\xFF" * (_mem.size() // 8))

            return

        if self._reserved:
            _mem.set_raw("\x00" * 13 + _rsvd)
        else:
            _mem.set_raw("\x00" * 13 + "\xFF\xFF\xFF")

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

        _mem.wide = mem.mode == "FM"

        rxtone = txtone = 0
        rxmode = txmode = ""

        if mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            rxtone = txtone = mem.dtcs
        elif mem.tmode and mem.tmode != "Cross":
            rxtone = txtone = mem.tmode == "Tone" and mem.rtone or mem.ctone
            txmode = "Tone"
            rxmode = mem.tmode == "TSQL" and "Tone" or ""
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)

            if txmode == "DTCS":
                txtone = mem.dtcs
            elif txmode == "Tone":
                txtone = mem.rtone

            if rxmode == "DTCS":
                rxtone = mem.rx_dtcs
            elif rxmode == "Tone":
                rxtone = mem.ctone

        self._set_tone(_mem, "txtone", txtone, txmode)
        self._set_tone(_mem, "rxtone", rxtone, rxmode)

        _mem.highpower = mem.power == self.POWER_LEVELS[0]

        for setting in mem.extra:
            if setting.get_name().startswith("chnl_"):
                setattr(self._memobj.bclo, setting.get_name(), setting.value)
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        rs = RadioSettingValueInteger(0, 9, _settings.squelch)
        rset = RadioSetting("squelch", "Squelch Level", rs)
        basic.append(rset)

        rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                   current_index=_settings.tot - 1)
        rset = RadioSetting("tot", "Time-out timer", rs)
        basic.append(rset)

        rs = RadioSettingValueList(VOICE_LIST,
                                   current_index=_settings.voice)
        rset = RadioSetting("voice", "Voice Prompts", rs)
        basic.append(rset)

        rs = RadioSettingValueList(SAVE_LIST,
                                   current_index=_settings.savem)
        rset = RadioSetting("savem", "Battery Save Mode", rs)
        basic.append(rset)

        rs = RadioSettingValueList(BACKLIGHT_LIST,
                                   current_index=_settings.backlight)
        rset = RadioSetting("backlight", "Back Light", rs)
        basic.append(rset)

        rs = RadioSettingValueInteger(0, 9, _settings.volume)
        rset = RadioSetting("volume", "Volume", rs)
        basic.append(rset)

        rs = RadioSettingValueInteger(0, 10, _settings.tone)
        rset = RadioSetting("tone", "Tone", rs)
        basic.append(rset)

        rs = RadioSettingValueInteger(1, 22, _settings.chnumber + 1)
        rset = RadioSetting("chnumber", "Channel Number", rs)
        basic.append(rset)

        if self.MODEL == "RB28":
            rs = RadioSettingValueInteger(1, 11, _settings.wxchnumber + 1)
            rset = RadioSetting("wxchnumber", "Weather Channel Number", rs)
            basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.autokeylock)
        rset = RadioSetting("autokeylock", "Auto Key Lock", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.save)
        rset = RadioSetting("save", "Battery Save", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.roger)
        rset = RadioSetting("roger", "End Tone", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("beep", "Beep", rs)
        basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.scan)
        rset = RadioSetting("scan", "Scan", rs)
        basic.append(rset)

        if self.MODEL == "RB28":
            rs = RadioSettingValueBoolean(_settings.wxwarn)
            rset = RadioSetting("wxwarn", "Weather Warn", rs)
            basic.append(rset)

        rs = RadioSettingValueBoolean(_settings.keylock)
        rset = RadioSetting("keylock", "Key Lock", rs)
        basic.append(rset)

        rs = RadioSettingValueList(VOXL_LIST,
                                   current_index=_settings.voxl)
        rset = RadioSetting("voxl", "Vox Level", rs)
        basic.append(rset)

        rs = RadioSettingValueList(VOXD_LIST,
                                   current_index=_settings.voxd)
        rset = RadioSetting("voxd", "Vox Delay", rs)
        basic.append(rset)

        rs = RadioSettingValueList(self.PFKEY_LIST,
                                   current_index=_settings.pfkey_lt)
        rset = RadioSetting("pfkey_lt", "Key Set < Long", rs)
        basic.append(rset)

        rs = RadioSettingValueList(self.PFKEY_LIST,
                                   current_index=_settings.pfkey_gt)
        rset = RadioSetting("pfkey_gt", "Key Set > Long", rs)
        basic.append(rset)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "chnumber":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "tot":
                        setattr(obj, setting, int(element.value) + 1)
                    elif setting == "wxchnumber":
                        setattr(obj, setting, int(element.value) - 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # Radios that have always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RB628Radio(RB28Radio):
    """RETEVIS RB628"""
    VENDOR = "Retevis"
    MODEL = "RB628"

    PFKEY_LIST = PFKEY_EU_LIST
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=0.50),
                    chirp_common.PowerLevel("Low", watts=0.50)]

    _magic = b"PHOGR\x28\x0B"
    _fingerprint = [b"P32073" + b"\x00\xFF", ]
    _upper = 16
    _mem_params = (_upper,  # number of channels
                   )
    _frs = False
    _pmr = True
