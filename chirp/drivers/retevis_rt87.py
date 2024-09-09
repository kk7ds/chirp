# Copyright 2021 Jim Unroe <rock.unroe@gmail.com>
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

"""Retevis RT87 radio management module"""

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
struct memory {
  bbcd rx_freq[4];
  bbcd tx_freq[4];
  lbcd rx_tone[2];
  lbcd tx_tone[2];
  u8 unknown10:2,
     pttid:2,
     unknown11:1,
     highpower:1,
     option:2;
  u8 optsigtype:3,
     unknown20:1,
     narrow:1,
     vox:1,
     bcl:2;
  u8 unknown31:1,
     scanadd:1,
     unknown32:3,
     scrambler:3;
  u8 unknown4;
};

struct name {
  char name[10];
};

#seekto 0x0010;
struct memory channels[128];

#seekto 0x0830;
struct {
  u8 scanmode:2,        // Scan Modes (Time, Carrier, Seek)                [17]
     autolock:1,        // Auto Keypad Lock (Off, On)                      [18]
     unknown_0830:2,
     manager:1,         // Manager (Off, On)
     unknown_08301:2;
  u8 batterydis:1,      // Battery Display (Voltage, Icon)                 [20]
     unknown_0831:1,
     sidetone:1,        // Side Tone (Off, On)
     unknown_08311:1,
     chnameshow:1,      // Display Channel Names (Off, On)                 [25]
     voice:1,           // Voice Prompt (Off, On)                          [19]
     beep:1,            // Beep (Off, On)                                  [09]
     batterysave:1;     // Battery Save aka Receiver Saver (Off, On)       [16]
  u8 unknown_0832:3,
     manual:1,          // Manual (Disabled, Enabled)
     cancelcodesql:1,   // Cancel Code Squelch When Press PTT (Disabled,
                        //                                     Enabled)
     ani:1,             // Automatic Number Identity (Off, On)             [10]
     roger:1,           // Roger Time (Off, On)                            [14]
     dwatch:1;          // Inhibit Receiver When Radio Working (Disabled,  [15]
                        // aka Dual Watch/Monitor               Enabled)
  u8 unknown_0833:2,
     txsel:1,           // Priority Transmit (Edit, Busy)                  [02]
     dwait:1,           // Dual Wait/Standby (Off, On)                     [06]
     unknown_08331:1,
     dtmfsig:1,         // DTMF Signaling (Code Squelch, Selective Call)
     msgmode:2;         // Message Mode (Off, DC, MSG, Image)              [23]
  u8 unk_0834:4,
     squelch:4;         // Squelch Level (0 - 9)                           [05]
  u8 unk_0835:4,
     tot:4;             // Time-out Timer (Off, 30sec, 60sec, 90sec,       [11]
                        //                 120sec, 150sec, 180sec,
                        //                 210sec, 240sec, 270sec)
  u8 unknown_0836:2,
     voxdelaytime:2,    // VOX Delay Time (1sec, 2sec, 3sec, 4sec)
     voxgainlevel:4;    // VOX Gain Level (1 - 8)                          [03]
  u8 unknown_0837;
  u8 unknown_0838;
  u8 unknown_0839;
  u8 lamp:5,            // Lamp            00000    Off                    [07]
                        //                 00001    On
                        //                 00010    5s
                        //                 00100    10s (default)
                        //                 01000    20s
                        //                 10000    30s
     brightness:3;      // Brightness           000 Off                    [08]
                        //                      001 1
                        //                      010 2
                        //                      011 3
                        //                      100 4
                        //                      101 5
                        //                      110 6  (default)
                        //                      111 7
  u8 unknown_083B:1,
     pf1:3,             // PF1 (Off, Reverse, Opt Call, 1750 Hz, A/B)      [21]
     unknown_083B1:1,
     pf2:3;             // PF2 (Off, Reverse, Opt Call, 1750 Hz, A/B)      [22]
  u8 unknown_083c;      // factory = 05, reset = FF
  u8 unknown_083d;      // factory = 12, reset = FF
  u8 unknown_083e;      // factory = 50, reset = FF
  u8 stunmode;          // Stun Mode (Stun Rx/Tx, Stun Tx, Normal)
} settings;

#seekto 0x08C0;
struct {
  char line1[16];       // PowerOn Message Line 1 (16 characters)
  char line2[16];       // PowerOn Message Line 2 (16 characters)
  char line3[16];       // PowerOn Message Line 3 (16 characters)
  char line4[16];       // PowerOn Message Line 4 (16 characters)
} poweron_msg;

#seekto 0x0D20;
struct {
  u8 unknown_0d20:4,
     autoresettimer:4;  // Auto Reset Timer[s]
  u8 delay;             // Digit Delay
  u8 unknown_0d22:4,
     dtmflen:4;         // DTMF Code Length
  u8 unknown_0d23;
  u8 unknown_0d24:4,
     intcode:4;         // Intermediate Code
  u8 unknown_0d25:4,
     groupcode:4;       // Group Code
} optsig;

#seekto 0x0D30;
struct {
  u8 mskid[2];          // MSK ID Code
} msk;

#seekto 0x0D38;
struct {
  u8 mskcall[2];        // MSK CallList
  u8 unused[2];
} msklist[10];

#seekto 0x0D90;
struct {
  u8 bot[7];            // PTT-ID BOT (Beginning of Transmission)
  u8 unused_0d97;
  u8 eot[7];            // PTT-ID EOT (End of Transmission) "0123456789ABCD#* "
  u8 unused_0d9f;
} pttid;

#seekto 0x0DA8;
struct {
  char code[7];         // Local Name
} msk_name;

#seekto 0x0DB0;
struct {
  u8 code[16];          // MSK CallList
} dtmfenc[10];

#seekto 0x0E50;
struct {
  u8 stunid[4];         // Stun/Wake-Up ID Code
} stun;

#seekto 0x1900;
struct name names[128];
"""


# Radio supports UPPER/lower case and symbols
CHARSET_ASCII_PLUS = chirp_common.CHARSET_ALPHANUMERIC + \
                     "!\"#$%&'()*+,-./:;<=>?@[\\]^_`"

POWER_LEVELS = [chirp_common.PowerLevel('Low', watts=1),
                chirp_common.PowerLevel('High', watts=4)]

VALID_BANDS = [(136000000, 174000000),
               (400000000, 480000000)]

RT87_DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

NUMERIC_CHARSET = list("0123456789")
DTMF_CHARSET = NUMERIC_CHARSET + list("ABCD*#")

LIST_BATTERY = ["Volt", "Icon"]
LIST_BCL = ["Off", "Carrier", "QT/DQT"]
LIST_BRIGHTNESS = ["Off"] + ["%s" % x for x in range(1, 8)]
LIST_DTMFLEN = ["%s" % x for x in range(30, 160, 10)]
LIST_DTMFSIG = ["Code Squelch", "Selective Call"]
LIST_INTCODE = list(DTMF_CHARSET)
LIST_OPTION = ["Off", "Compand", "Scramble"]
LIST_POWERON = ["Off", "Voltage", "Message", "Picture"]
LIST_PTTID = ["Off", "BOT", "EOT", "Both"]
LIST_RESET = ["Off", "1 second"] + ["%s seconds" % x for x in range(2, 16)]
LIST_SCNREV = ["Time Operated", "Carrier Operated", "Seek"]
LIST_SIDEKEY = ["Off", "Reverse", "Opt Call", "1750 Hz", "A/B"]
LIST_TOT = ["Off"] + ["%s seconds" % x for x in range(30, 300, 30)]
LIST_TXSEL = ["Edit", "Busy"]
LIST_VFOMR = ["Frequency (VFO)", "Channel (MR)"]
LIST_VOXDELAYTIME = ["1 second", "2 seconds", "3 seconds", "4 seconds"]

LED_CHOICES = ["Off", "On", "5 seconds", "10 seconds", "20 seconds",
               "30 seconcds"]
LED_VALUES = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10]

DELAY_CHOICES = ["%s ms" % x for x in range(300, 1250, 50)]
DELAY_VALUES = [x for x in range(0, 95, 5)]

STUN_CHOICES = ["Stun Rx/Tx", "Stun Tx", "Normal"]
STUN_VALUES = [0x55, 0xAA, 0xFF]

GROUP_CHOICES = ["Off", "A", "B", "C", "D", "*", "#"]
GROUP_VALUES = [0x00, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F]


def _identify(radio):
    try:
        magic = radio._MAGIC
        radio.pipe.write(magic)
        echo = radio.pipe.read(len(magic))  # Chew the echoed response

        if magic != echo:
            LOG.debug("expecting echo\n%s\n", util.hexprint(magic))
            LOG.debug("got echo\n%s\n", util.hexprint(echo))
            raise Exception("Got false echo. Expected: '{}', got: '{}'."
                            .format(magic, echo))

        ack = radio.pipe.read(2)
        if ack != b"\x06\x30":
            raise errors.RadioError("Radio did not ACK first command: %r" %
                                    ack)
    except:
        LOG.exception('')
        raise errors.RadioError("Unable to communicate with the radio")


def _download(radio):
    _identify(radio)
    data = bytes([])
    for i in range(0, 0x2000, 0x40):
        msg = struct.pack('>cHb', b'R', i, 0x40)
        radio.pipe.write(msg)
        echo = radio.pipe.read(len(msg))  # Chew the echoed response

        if msg != echo:
            LOG.debug("expecting echo\n%s\n", util.hexprint(msg))
            LOG.debug("got echo\n%s\n", util.hexprint(echo))
            raise Exception("Got false echo. Expected: '{}', got: '{}'."
                            .format(msg, echo))

        block = radio.pipe.read(0x40 + 4)
        if len(block) != (0x40 + 4):
            raise errors.RadioError("Radio sent a short block (%02x/%02x)" % (
                len(block), 0x44))
        data += block[4:]

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i
            status.max = 0x2000
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    radio.pipe.write(b"E")

    return memmap.MemoryMapBytes(data)


def _upload(radio):
    _identify(radio)

    for start_addr, end_addr, block_size in radio._ranges:
        for addr in range(start_addr, end_addr, block_size):
            msg = struct.pack('>cHb', b'W', addr, block_size)
            msg += radio._mmap[addr:(addr + block_size)]
            radio.pipe.write(msg)
            radio.pipe.read(block_size + 4)
            ack = radio.pipe.read(1)
            if ack != b'\x06':
                raise errors.RadioError('Radio did not ACK block %i (0x%04x)'
                                        % (addr, addr))

            if radio.status_fn:
                status = chirp_common.Status()
                status.cur = addr
                status.max = 0x2000
                status.msg = "Cloning to radio"
                radio.status_fn(status)

    radio.pipe.write(b"E")


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return True


class Rt87BaseRadio(chirp_common.CloneModeRadio):
    VENDOR = "Retevis"
    MODEL = "RT87 Base"
    BAUD_RATE = 9600
    _MAGIC = b"PGM2017"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        # General
        rf.has_bank = False
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_settings = True
        # Attributes
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_tuning_steps = [0.5, 2.5, 5, 6.25, 10, 12.5, 25, 37.5, 50,
                                 100]
        rf.valid_bands = VALID_BANDS
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = CHARSET_ASCII_PLUS
        rf.valid_name_length = 10
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]

        rf.memory_bounds = (1, 128)
        rf.can_odd_split = True
        return rf

    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
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
            _upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return (repr(self._memobj.channels[number - 1]) +
                repr(self._memobj.names[number - 1]))

    def _get_memobjs(self, number):
        return (self._memobj.channels[number - 1],
                self._memobj.names[number - 1])

    def _decode_tone(self, toneval):
        pol = "N"
        rawval = (toneval[1].get_bits(0xFF) << 8) | toneval[0].get_bits(0xFF)

        if toneval[0].get_bits(0xFF) == 0xFF:
            mode = ""
            val = 0
        elif toneval[1].get_bits(0xC0) == 0xC0:
            mode = "DTCS"
            val = int("%x" % (rawval & 0x3FFF))
            pol = "R"
        elif toneval[1].get_bits(0x80):
            mode = "DTCS"
            val = int("%x" % (rawval & 0x3FFF))
        else:
            mode = "Tone"
            val = int(toneval) / 10.0

        return mode, val, pol

    def _encode_tone(self, _toneval, mode, val, pol):
        toneval = 0
        if mode == "Tone":
            toneval = int("%i" % (val * 10), 16)
        elif mode == "DTCS":
            toneval = int("%i" % val, 16)
            toneval |= 0x8000
            if pol == "R":
                toneval |= 0x4000
        else:
            toneval = 0xFFFF

        _toneval[0].set_raw(toneval & 0xFF)
        _toneval[1].set_raw((toneval >> 8) & 0xFF)

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.tx_freq[i].get_raw(asbytes=False)
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def _bbcd2num(self, bcdarr, strlen=8):
        # doing bbcd
        LOG.debug(bcdarr.get_value())
        string = ''.join("%02X" % b for b in bcdarr)
        LOG.debug("@_bbcd2num, received: %s" % string)
        if strlen <= 8:
            string = string[:strlen]
        return string

    def _num2bbcd(self, value, strlen=8):
        numstr = value.get_value()
        numstr = str.ljust(numstr.strip(), strlen, "F")
        bcdarr = list(bytearray.fromhex(numstr))
        LOG.debug("@_num2bbcd, sending: %s" % bcdarr)
        return bcdarr

    def get_memory(self, number):
        _mem, _name = self._get_memobjs(number)

        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.number = SPECIALS[number]
            mem.extd_number = number
        else:
            mem.number = number

        if _mem.get_raw(asbytes=False).startswith("\xFF\xFF\xFF\xFF"):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        if self._is_txinh(_mem):
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        else:
            # TX freq set
            offset = (int(_mem.tx_freq) * 10) - mem.freq
            if offset != 0:
                if _split(self.get_features(), mem.freq, int(
                          _mem.tx_freq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.tx_freq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        txmode, txval, txpol = self._decode_tone(_mem.tx_tone)
        rxmode, rxval, rxpol = self._decode_tone(_mem.rx_tone)

        chirp_common.split_tone_decode(mem,
                                       (txmode, txval, txpol),
                                       (rxmode, rxval, rxpol))

        mem.mode = 'NFM' if _mem.narrow else 'FM'
        mem.skip = '' if _mem.scanadd else 'S'
        mem.power = POWER_LEVELS[int(_mem.highpower)]
        mem.name = str(_name.name).rstrip('\xFF ')

        # Extra
        mem.extra = RadioSettingGroup("extra", "Extra")

        rs = RadioSettingValueList(LIST_BCL, current_index=_mem.bcl)
        rset = RadioSetting("bcl", "BCL", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueList(LIST_PTTID, current_index=_mem.pttid)
        rset = RadioSetting("pttid", "PTT-ID", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(bool(_mem.vox))
        rset = RadioSetting("vox", "VOX", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueList(LIST_OPTION, current_index=_mem.option)
        rset = RadioSetting("option", "Option", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueInteger(1, 8, _mem.scrambler + 1)
        rset = RadioSetting("scrambler", "Compander/Scrambler", rs)
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        _mem, _name = self._get_memobjs(mem.number)
        if mem.empty:
            _mem.set_raw('\xFF' * 16)
            _name.set_raw('\xFF' * 10)
            return
        _mem.set_raw('\x00' * 16)

        _mem.rx_freq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.tx_freq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.tx_freq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)

        self._encode_tone(_mem.tx_tone, txmode, txval, txpol)
        self._encode_tone(_mem.rx_tone, rxmode, rxval, rxpol)

        _mem.narrow = mem.mode == 'NFM'
        _mem.scanadd = mem.skip != 'S'
        _mem.highpower = POWER_LEVELS.index(mem.power) if mem.power else 1
        _name.name = mem.name.rstrip(' ').ljust(10, '\xFF')

        # extra settings
        for setting in mem.extra:
            if setting == "scrambler":
                setattr(_mem, setting.get_name(), element.value - 1)
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def _get_settings(self):
        _msg = self._memobj.poweron_msg
        _optsig = self._memobj.optsig
        _settings = self._memobj.settings
        _stun = self._memobj.stun
        _msk = self._memobj.msk
        _mskname = self._memobj.msk_name

        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Menu 01: SCAN

        # Menu 02: TX.SEL aka PRI
        rs = RadioSettingValueList(LIST_TXSEL,
                                   current_index=_settings.txsel)
        rset = RadioSetting("txsel", "Priority Transmit", rs)
        basic.append(rset)

        # Menu 03: VOX (VOX Gain Level)
        rs = RadioSettingValueInteger(1, 8, _settings.voxgainlevel + 1)
        rset = RadioSetting("voxgainlevel", "VOX Gain Level", rs)
        basic.append(rset)

        # Function Setting: VOX Delay Time
        rs = RadioSettingValueList(LIST_VOXDELAYTIME,
                                   current_index=_settings.voxdelaytime)
        rset = RadioSetting("voxdelaytime", "VOX Delay Time", rs)
        basic.append(rset)

        # Menu 04: TX POW (TX Power)

        # Menu 05: SQL (Squelch Level)
        rs = RadioSettingValueInteger(0, 9, _settings.squelch)
        rset = RadioSetting("squelch", "Squelch Level", rs)
        basic.append(rset)

        # Menu 06: D.WAIT aka DW (Dual Wait/Standby)
        rs = RadioSettingValueBoolean(bool(_settings.dwait))
        rset = RadioSetting("dwait", "Dual Wait/Standby", rs)
        basic.append(rset)

        # Menu 07: LED (Backlight Time)
        def apply_lamp_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) +
                      " from list")
            val = str(setting.value)
            index = LED_CHOICES.index(val)
            val = LED_VALUES[index]
            obj.set_value(val)

        if _settings.lamp in LED_VALUES:
            idx = LED_VALUES.index(_settings.lamp)
        else:
            idx = LED_VALUES.index(0x04)
        rs = RadioSettingValueList(LED_CHOICES, current_index=idx)
        rset = RadioSetting("settings.lamp", "Backlight Time", rs)
        rset.set_apply_callback(apply_lamp_listvalue, _settings.lamp)
        basic.append(rset)

        # Menu 08: BRIGHT (Backlight Brightness)
        rs = RadioSettingValueList(LIST_BRIGHTNESS,
                                   current_index=_settings.brightness)
        rset = RadioSetting("brightness", "Backlight Brightness", rs)
        basic.append(rset)

        # Menu 09: BEEP (Key Beep)
        rs = RadioSettingValueBoolean(bool(_settings.beep))
        rset = RadioSetting("beep", "Key Beep", rs)
        basic.append(rset)

        # Menu 10: ANI (Automatic Number Identification)
        rs = RadioSettingValueBoolean(bool(_settings.ani))
        rset = RadioSetting("ani", "ANI", rs)
        basic.append(rset)

        # Menu 11: TOT (Transmitter Time-out Timer)
        rs = RadioSettingValueList(LIST_TOT,
                                   current_index=_settings.tot)
        rset = RadioSetting("tot", "Time-Out Timer", rs)
        basic.append(rset)

        # Menu 12: BUSY LOCK
        # Menu 13: VOX SW

        # Menu 14: ROGER (Transmit Ended Beep)
        rs = RadioSettingValueBoolean(bool(_settings.roger))
        rset = RadioSetting("roger", "Roger Beep", rs)
        basic.append(rset)

        # Menu 15: DW (Dual Watch/Monitor)
        rs = RadioSettingValueBoolean(bool(_settings.dwatch))
        rset = RadioSetting("dwatch", "Dual Watch/Monitor", rs)
        basic.append(rset)

        # Menu 16: RX SAVE (Battery Save)
        rs = RadioSettingValueBoolean(bool(_settings.batterysave))
        rset = RadioSetting("batterysave", "Battery Save", rs)
        basic.append(rset)

        # Menu 17: SCN-REV (Scan Mode)
        rs = RadioSettingValueList(LIST_SCNREV,
                                   current_index=_settings.scanmode)
        rset = RadioSetting("scanmode", "Scan Mode", rs)
        basic.append(rset)

        # Menu 18: AUTOLK (Auto Keypad Lock)
        rs = RadioSettingValueBoolean(bool(_settings.autolock))
        rset = RadioSetting("autolock", "Auto Keypad Lock", rs)
        basic.append(rset)

        # Menu 19: VOICE (Voice Prompt)
        rs = RadioSettingValueBoolean(bool(_settings.voice))
        rset = RadioSetting("voice", "Voice Prompt", rs)
        basic.append(rset)

        # Menu 20: BATT SHOW (Battery Display Method)
        rs = RadioSettingValueList(LIST_BATTERY,
                                   current_index=_settings.batterydis)
        rset = RadioSetting("batterydis", "Battery Display Method", rs)
        basic.append(rset)

        # Menu 21: PF1 (Side-Key 1)
        rs = RadioSettingValueList(LIST_SIDEKEY,
                                   current_index=_settings.pf1)
        rset = RadioSetting("pf1", "Side Key Function 1", rs)
        basic.append(rset)

        # Menu 22: PF2 (Side-Key 2)
        rs = RadioSettingValueList(LIST_SIDEKEY,
                                   current_index=_settings.pf2)
        rset = RadioSetting("pf2", "Side Key Function 2", rs)
        basic.append(rset)

        # Menu 23: OPN.SET (Power-On Display)
        rs = RadioSettingValueList(LIST_POWERON,
                                   current_index=_settings.msgmode)
        rset = RadioSetting("msgmode", "Power-On Display Method", rs)
        basic.append(rset)

        # Menu 24: PON.MSG (Power-On Message Editing)
        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in CHARSET_ASCII_PLUS:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        rs = RadioSettingValueString(0, 16, _filter(_msg.line1))
        rset = RadioSetting("poweron_msg.line1", "Power-On Message 1", rs)
        basic.append(rset)

        rs = RadioSettingValueString(0, 16, _filter(_msg.line2))
        rset = RadioSetting("poweron_msg.line2", "Power-On Message 2", rs)
        basic.append(rset)

        rs = RadioSettingValueString(0, 16, _filter(_msg.line3))
        rset = RadioSetting("poweron_msg.line3", "Power-On Message 3", rs)
        basic.append(rset)

        rs = RadioSettingValueString(0, 16, _filter(_msg.line4))
        rset = RadioSetting("poweron_msg.line4", "Power-On Message 4", rs)
        basic.append(rset)

        # Menu 25: CHNAME SHOW (Channel Name Show)
        rs = RadioSettingValueBoolean(bool(_settings.chnameshow))
        rset = RadioSetting("chnameshow", "Display Channel Names", rs)
        basic.append(rset)

        # Menu 26: CH.NAME (Channel Name Editing)
        # Menu 27: OFFSET (Repeater Shift)
        # Menu 28: C-CDC (TX/RX Tone Coder)
        # Menu 29: R-CDC (RX Tone Coder)
        # Menu 30: T-CDC (TX Tone Coder)
        # Menu 31: SFT-D (Shift Direction)
        # Menu 32: STEP (STEP)
        # Menu 33: N/W (Channel Spacing Select)
        # Menu 34: CTCSS SCAN (CTCSS Scan)
        # Menu 35: DCS SSCAN (DCS Scan)
        # Menu 36: SCR.NO (Scrambler)
        # Menu 37: APRO (Voice Compander/Scrambler)

        pttid = RadioSettingGroup("pttid", "PTT ID Settings")
        group.append(pttid)

        # PTT ID Setting: BOT
        _codeobj = self._memobj.pttid.bot
        _code = "".join([DTMF_CHARSET[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 7, _code, False)
        val.set_charset(DTMF_CHARSET)
        rs = RadioSetting("pttid.bot", "PTT ID BOT Code", val)

        def apply_bot_code(setting, obj):
            value = []
            for j in range(0, 7):
                try:
                    value.append(DTMF_CHARSET.index(str(setting.value)[j]))
                except IndexError:
                    value.append(0xFF)
            obj.bot = value
        rs.set_apply_callback(apply_bot_code, self._memobj.pttid)
        pttid.append(rs)

        # PTT ID Setting: EOT
        _codeobj = self._memobj.pttid.eot
        _code = "".join([DTMF_CHARSET[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 7, _code, False)
        val.set_charset(DTMF_CHARSET)
        rs = RadioSetting("pttid.eot", "PTT ID EOT Code", val)

        def apply_eot_code(setting, obj):
            value = []
            for j in range(0, 7):
                try:
                    value.append(DTMF_CHARSET.index(str(setting.value)[j]))
                except IndexError:
                    value.append(0xFF)
            obj.eot = value
        rs.set_apply_callback(apply_eot_code, self._memobj.pttid)
        pttid.append(rs)

        # Optional Signal
        optsig = RadioSettingGroup("optsig", "Option Signal")
        group.append(optsig)

        # Common Set
        common = RadioSettingGroup("common", "Common Set")
        optsig.append(common)

        # Common Set: Digit Delay[ms] (broken in OEM software)
        def apply_delay_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) +
                      " from list")
            val = str(setting.value)
            index = DELAY_CHOICES.index(val)
            val = DELAY_VALUES[index]
            obj.set_value(val)

        if _optsig.delay in DELAY_VALUES:
            idx = DELAY_VALUES.index(_optsig.delay)
        else:
            idx = DELAY_VALUES.index(30)
        rs = RadioSettingValueList(DELAY_CHOICES, current_index=idx)
        rset = RadioSetting("optsig.delay", "Digit Delay", rs)
        rset.set_apply_callback(apply_delay_listvalue, _optsig.delay)
        common.append(rset)

        # Common Set: Auto Reset Timer[s]
        rs = RadioSettingValueList(LIST_RESET,
                                   current_index=_optsig.autoresettimer)
        rset = RadioSetting("optsig.autoresettimer", "Auto Reset Timer", rs)
        common.append(rset)

        # Common Set: Side Tone
        rs = RadioSettingValueBoolean(bool(_settings.sidetone))
        rset = RadioSetting("sidetone", "Side Tone", rs)
        common.append(rset)

        # Common Set: Stun Mode
        def apply_stun_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) +
                      " from list")
            val = str(setting.value)
            index = STUN_CHOICES.index(val)
            val = STUN_VALUES[index]
            obj.set_value(val)

        if _settings.stunmode in STUN_VALUES:
            idx = STUN_VALUES.index(_settings.stunmode)
        else:
            idx = STUN_VALUES.index(0xFF)
        rs = RadioSettingValueList(STUN_CHOICES, current_index=idx)
        rset = RadioSetting("settings.stunmode", "Stun Mode", rs)
        rset.set_apply_callback(apply_stun_listvalue, _settings.stunmode)
        common.append(rset)

        # Common Set: Stun/Wake-Up ID

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in NUMERIC_CHARSET:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        codesetting = getattr(_stun, "stunid")
        codestr = self._bbcd2num(codesetting, 8)
        code = RadioSettingValueString(0, 8, _filter(codestr))
        code.set_charset(NUMERIC_CHARSET + list(" "))
        rs = RadioSetting("stun.stunid", "Stun ID Code", code)
        common.append(rs)

        # Common Set: Manager
        rs = RadioSettingValueBoolean(bool(_settings.manager))
        rset = RadioSetting("manager", "Manager", rs)
        common.append(rset)

        # MSK
        msk = RadioSettingGroup("msk", "MSK")
        optsig.append(msk)

        # MSK: ID Code
        codesetting = getattr(_msk, "mskid")
        codestr = self._bbcd2num(codesetting, 4)
        code = RadioSettingValueString(0, 4, _filter(codestr))
        code.set_charset(NUMERIC_CHARSET + list(" "))
        rs = RadioSetting("msk.mskid", "MSK ID Code", code)
        msk.append(rs)

        # MSK: Local Name
        rs = RadioSettingValueString(0, 7, _filter(_mskname.code))
        rset = RadioSetting("msk_name.code", "Local Name", rs)
        msk.append(rset)

        # MSK: CallList
        for i in range(0, 10):
            codesetting = getattr(self._memobj.msklist[i], "mskcall")
            codestr = self._bbcd2num(codesetting, 4)
            code = RadioSettingValueString(0, 4, _filter(codestr))
            code.set_charset(NUMERIC_CHARSET + list(" "))
            code.set_mutable(False)
            rs = RadioSetting("msklist/%i.mskcall" % i, "CallList %i" % i,
                              code)
            msk.append(rs)

        # DTMF
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        optsig.append(dtmf)

        # DTMF: Encode

        for i in range(0, 10):
            _codeobj = self._memobj.dtmfenc[i].code
            _code = "".join([DTMF_CHARSET[x] for x in _codeobj if
                            int(x) < 0x1F])
            val = RadioSettingValueString(0, 16, _code, False)
            val.set_charset(DTMF_CHARSET)
            rs = RadioSetting("dtmfenc/%i.code" % i,
                              "Encode %i" % i, val)

            def apply_code(setting, obj):
                code = []
                for j in range(0, 16):
                    try:
                        code.append(DTMF_CHARSET.index(str(setting.value)[j]))
                    except IndexError:
                        code.append(0xFF)
                obj.code = code
            rs.set_apply_callback(apply_code, self._memobj.dtmfenc[i])
            dtmf.append(rs)

        # DTMF: DTMF Signaling
        rs = RadioSettingValueList(LIST_DTMFSIG,
                                   current_index=_settings.dtmfsig)
        rset = RadioSetting("dtmfsig", "DTMF Signaling", rs)
        dtmf.append(rset)

        # DTMF: Intermediate Code
        rs = RadioSettingValueList(LIST_INTCODE,
                                   current_index=_optsig.intcode)
        rset = RadioSetting("optsig.intcode", "Intermediate Code", rs)
        dtmf.append(rset)

        # DTMF: Group Code
        def apply_group_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) +
                      " from list")
            val = str(setting.value)
            index = GROUP_CHOICES.index(val)
            val = GROUP_VALUES[index]
            obj.set_value(val)

        if _optsig.groupcode in GROUP_VALUES:
            idx = GROUP_VALUES.index(_optsig.groupcode)
        else:
            idx = GROUP_VALUES.index(0x00)
        rs = RadioSettingValueList(GROUP_CHOICES, current_index=idx)
        rset = RadioSetting("optsig.groupcode", "Group Code", rs)
        rset.set_apply_callback(apply_group_listvalue, _optsig.groupcode)
        dtmf.append(rset)

        # DTMF: DTMF Code Length
        rs = RadioSettingValueList(LIST_DTMFLEN,
                                   current_index=_optsig.dtmflen - 3)
        rset = RadioSetting("optsig.dtmflen", "DTMF Code Length", rs)
        dtmf.append(rset)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("failed to parse settings")
            traceback.print_exc()
            return None

    def set_settings(self, settings):
        _mem = self._memobj
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
                        LOG.debug("using apply callback")
                        element.run_apply_callback()
                    elif setting == "voxgainlevel":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "stunid":
                        numstr = self._num2bbcd(element.value, 8)
                        setattr(_mem.stun, setting, numstr)
                    elif setting == "mskid":
                        numstr = self._num2bbcd(element.value, 4)
                        setattr(_mem.msk, setting, numstr)
                    elif setting == "dtmflen":
                        setattr(obj, setting, int(element.value) + 3)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise


@directory.register
class RT87(Rt87BaseRadio):
    VENDOR = "Retevis"
    MODEL = "RT87"

    _ranges = [
               (0x0000, 0x0A00, 0x40),
               (0x0BC0, 0x0C00, 0x08),
               (0x0C00, 0x0F00, 0x40),
               (0x1000, 0x2000, 0x40),
              ]
