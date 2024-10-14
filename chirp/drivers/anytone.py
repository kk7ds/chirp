# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings, \
    RadioSettingValueList, RadioSettingValueString, RadioSettingValueBoolean


LOG = logging.getLogger(__name__)

BLOCK_SIZE = 0x10
NUMBER_OF_MEMORY_LOCATIONS = 758
MEMORY_LOCATION_SIZE = 32
ADDR_FIRST_WRITABLE_BYTE = 0x0100
ADDR_LAST_BLOCK_BEFORE_MEMORIES = 0x19F0
ADDR_FIRST_MEMORY_LOCATION = 0x2000


# This _mem_format structure is defined separately from the rest because it
# needs to be parsed twice -- once in the middle of downloading data from the
# radio, and then again (along with everything else) once the download is
# complete.
_mem_format = """
#seekto 0x0100;
struct {
  u8 even_unknown:2,
     even_pskip:1,
     even_skip:1,
     odd_unknown:2,
     odd_pskip:1,
     odd_skip:1;
} flags[379];
"""

mem_format = _mem_format + """
struct memory {
  bbcd freq[4];
  bbcd offset[4];
  u8 unknownA:4,
     tune_step:4;
  u8 rxdcsextra:1,
     txdcsextra:1,
     rxinv:1,
     txinv:1,
     channel_width:2,
     rev:1,
     txoff:1;
  u8 talkaround:1,
     compander:1,
     unknown8:1,
     is_am:1,
     power:2,
     duplex:2;
  u8 dtmfSlotNum:4,
     rxtmode:2,
     txtmode:2;
  u8 unknown5:2,
     txtone:6;
  u8 unknown6:2,
     rxtone:6;
  u8 txcode;
  u8 rxcode;
  u8 unknown10:2,
     pttid:2,
     unknown11:2,
     bclo:2;
  u8 unknown7;
  u8 unknown9:5,
     sqlMode:3;         // [Carrier, CTCSS/DCS Tones,
                        // Opt Sig Only, Tones & Opt Sig,
                        // Tones or Opt Sig]
  u8 unknown21:6,
     optsig:2;
  u8 unknown22:3,
     twotone:5;
  u8 unknown23:1,
     fivetone:7;
  u8 unknown24:4,
     scramble:4;
  char name[7];
  ul16 custtone;
};

#seekto 0x0030;
struct {
  char serial[16];
} serial_no;

#seekto 0x0050;
struct {
  char date[16];
} version;

#seekto 0x0280;
struct {
  u8 unknown1:6,
     display:2;
  u8 unknown2[11];
  // TODO Backlight brightness is in here (RGB)
  u8 unknown3:3,
     apo:5;
  u8 unknown4a[2];
  u8 unknown4b:6,
     mute:2;
  // TODO Keypad locked is in here (0=unlocked, 1=locked)
  u8 unknown4;
  u8 unknown5:5,
     beep:1,
     unknown6:2;
  u8 unknown[334];
  // TODO Programmable keys A-D are here
  char welcome[8];
} settings;

#seekto 0x0540;
struct memory memblk1[12];

#seekto 0x2000;
struct memory memory[758];  // FIXME It's actually only 750

// TODO VFO scan limits are here (after the 750th memory; seekto 0x7DC0)

#seekto 0x7ec0;
struct memory memblk2[10];
"""


class FlagObj(object):
    def __init__(self, flagobj, which):
        self._flagobj = flagobj
        self._which = which

    def _get(self, flag):
        return getattr(self._flagobj, "%s_%s" % (self._which, flag))

    def _set(self, flag, value):
        return setattr(self._flagobj, "%s_%s" % (self._which, flag), value)

    def get_skip(self):
        return self._get("skip")

    def set_skip(self, value):
        self._set("skip", value)

    skip = property(get_skip, set_skip)

    def get_pskip(self):
        return self._get("pskip")

    def set_pskip(self, value):
        self._set("pskip", value)

    pskip = property(get_pskip, set_pskip)

    def set(self):
        self._set("unknown", 3)
        self._set("skip", 1)
        self._set("pskip", 1)

    def clear(self):
        self._set("unknown", 0)
        self._set("skip", 0)
        self._set("pskip", 0)

    def get(self):
        return (self._get("unknown") << 2 |
                self._get("skip") << 1 |
                self._get("pskip"))

    def __repr__(self):
        return repr(self._flagobj)


def _is_loc_used(memobj, loc):
    return memobj.flags[loc / 2].get_raw(asbytes=False) != "\xFF"


def _addr_to_loc(addr):
    return (addr - ADDR_FIRST_MEMORY_LOCATION) / MEMORY_LOCATION_SIZE


def _should_send_addr(memobj, addr):
    if addr < ADDR_FIRST_MEMORY_LOCATION or addr >= 0x7EC0:
        return True
    else:
        return _is_loc_used(memobj, _addr_to_loc(addr))


def _echo_write(radio, data):
    try:
        radio.pipe.write(data)
        radio.pipe.read(len(data))
    except Exception as e:
        LOG.error("Error writing to radio: %s" % e)
        raise errors.RadioError("Unable to write to radio")


def _read(radio, length):
    try:
        data = radio.pipe.read(length)
    except Exception as e:
        LOG.error("Error reading from radio: %s" % e)
        raise errors.RadioError("Unable to read from radio")

    if len(data) != length:
        LOG.error("Short read from radio (%i, expected %i)" %
                  (len(data), length))
        LOG.debug(util.hexprint(data))
        raise errors.RadioError("Short read from radio")
    return data


valid_model = [b'QX588UV', b'HR-2040', b'DB-50M\x00', b'DB-750X']


def _ident(radio):
    # Chew garbage
    try:
        radio.pipe.read(32)
    except Exception:
        raise errors.RadioError("Unable to flush serial connection")
    radio.pipe.timeout = 1
    _echo_write(radio, b"PROGRAM")
    response = radio.pipe.read(3)
    if response != b"QX\x06":
        LOG.debug("Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Unsupported model or bad connection")
    _echo_write(radio, b"\x02")
    response = radio.pipe.read(16)
    LOG.debug(util.hexprint(response))
    if response[1:8] not in valid_model:
        LOG.debug("Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Unsupported model")


def _finish(radio):
    endframe = b"\x45\x4E\x44"
    _echo_write(radio, endframe)
    result = radio.pipe.read(1)
    if result != b"\x06":
        LOG.debug("Got:\n%s" % util.hexprint(result))
        raise errors.RadioError("Radio did not finish cleanly")


def _checksum(data):
    cs = 0
    for byte in data:
        cs += byte
    return cs % 256


def _send(radio, cmd, addr, length, data=None):
    frame = struct.pack(">cHb", cmd, addr, length)
    if data:
        frame += data
        frame += struct.pack('BB', _checksum(frame[1:]), 0x06)
    _echo_write(radio, frame)
    LOG.debug("Sent:\n%s" % util.hexprint(frame))
    if data:
        result = radio.pipe.read(1)
        if result != b'\x06':
            LOG.debug("Ack was: %s" % repr(result))
            raise errors.RadioError(
                "Radio did not accept block at %04x" % addr)
        return
    result = _read(radio, length + 6)
    LOG.debug("Got:\n%s" % util.hexprint(result))
    header = result[0:4]
    data = result[4:-2]
    ack = result[-1]
    if ack != 0x06:
        LOG.debug("Ack was: %s" % repr(ack))
        raise errors.RadioError("Radio NAK'd block at %04x" % addr)
    _cmd, _addr, _length = struct.unpack(">cHb", header)
    if _addr != addr or _length != _length:
        LOG.debug("Expected/Received:")
        LOG.debug(" Length: %02x/%02x" % (length, _length))
        LOG.debug(" Addr: %04x/%04x" % (addr, _addr))
        raise errors.RadioError("Radio send unexpected block")
    cs = _checksum(result[1:-2])
    if cs != result[-2]:
        LOG.debug("Calculated: %02x" % cs)
        LOG.debug("Actual:     %02x" % result[-2])
        raise errors.RadioError("Block at 0x%04x failed checksum" % addr)
    return data


def _download(radio):
    _ident(radio)

    memobj = None

    data = b""
    for start, end in radio._ranges:
        for addr in range(start, end, BLOCK_SIZE):
            if memobj is not None and not _should_send_addr(memobj, addr):
                block = b"\xFF" * BLOCK_SIZE
            else:
                block = _send(radio, b'R', addr, BLOCK_SIZE)
            data += block

            status = chirp_common.Status()
            status.cur = len(data)
            status.max = end
            status.msg = "Cloning from radio"
            radio.status_fn(status)

            if addr == ADDR_LAST_BLOCK_BEFORE_MEMORIES:
                memobj = bitwise.parse(_mem_format, data)

    _finish(radio)

    return memmap.MemoryMapBytes(data)


def _upload(radio):
    _ident(radio)

    for start, end in radio._ranges:
        for addr in range(start, end, BLOCK_SIZE):
            if addr < ADDR_FIRST_WRITABLE_BYTE:
                continue
            if not _should_send_addr(radio._memobj, addr):
                continue
            block = radio._mmap[addr:addr + BLOCK_SIZE]
            _send(radio, b'W', addr, len(block), block)

            status = chirp_common.Status()
            status.cur = addr
            status.max = end
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    _finish(radio)


TONES = tuple(sorted([62.5] + list(chirp_common.TONES)))
TMODES = ['', 'Tone', 'DTCS', '']
DUPLEXES = ['', '-', '+', 'off']
MODES = ["FM", "FM", "NFM"]
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=50),
                chirp_common.PowerLevel("Mid1", watts=25),
                chirp_common.PowerLevel("Mid2", watts=10),
                chirp_common.PowerLevel("Low", watts=5)]
BCLO = ['Off', 'Repeater', 'Busy']
DTMF_SLOTS = ['M%d' % x for x in range(1, 17)]
# Chose not to expose SCRAMBLE_CODES = ['Off'] +
# ['%d' % x for x in range(1, 10)] + ['Define 1', 'Define 2']
TONE2_SLOTS = ['%d' % x for x in range(0, 24)]
TONE5_SLOTS = ['%d' % x for x in range(0, 100)]
SQL_MODES = ["Carrier", "CTCSS/DCS", "Opt Sig Only", "Tones AND Sig",
             "Tones OR Sig"]
OPT_SIG_SQL = ["Off"] + SQL_MODES[2:]
OPT_SIGS = ['Off', 'DTMF', '2Tone', '5Tone']
PTT_IDS = ['Off', 'Begin', 'End', 'Begin & End']
TUNING_STEPS = [2.5, 5, 6.25, 10, 12.5, 15, 20, 25, 30, 50]
# FIXME (1) Not sure if 15 is a valid step, (2) 100 might be a valid step


@directory.register
class AnyTone5888UVRadio(chirp_common.CloneModeRadio,
                         chirp_common.ExperimentalRadio):
    """AnyTone 5888UV"""
    VENDOR = "AnyTone"
    MODEL = "5888UV"
    BAUD_RATE = 9600
    _file_ident = [b"QX588UV", b"588UVN"]

    # May try to mirror the OEM behavior later
    _ranges = [
        (0x0000, 0x8000),
        ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("The Anytone driver is currently experimental. "
                           "There are no known issues with it, but you should "
                           "proceed with caution.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.valid_duplexes = DUPLEXES
        rf.valid_tuning_steps = TUNING_STEPS
        rf.has_rx_dtcs = True
        rf.valid_skips = ["", "S", "P"]
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->DTCS', 'DTCS->Tone',
                                'DTCS->DTCS',
                                '->Tone', '->DTCS', 'Tone->Tone']
        rf.valid_tones = TONES
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES
        rf.valid_bands = [(108000000, 500000000)]
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        rf.valid_name_length = 7
        rf.valid_power_levels = POWER_LEVELS
        rf.memory_bounds = (1, NUMBER_OF_MEMORY_LOCATIONS)
        return rf

    def sync_in(self):
        self._mmap = _download(self)
        self.process_mmap()

    def sync_out(self):
        _upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def _get_memobjs(self, number):
        number -= 1
        _mem = self._memobj.memory[number]
        _flg = FlagObj(self._memobj.flags[number / 2],
                       number % 2 and "even" or "odd")
        return _mem, _flg

    def _get_dcs_index(self, _mem, which):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        return (int(extra) << 8) | int(base)

    def _set_dcs_index(self, _mem, which, index):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        base.set_value(index & 0xFF)
        extra.set_value(index >> 8)

    def get_raw_memory(self, number):
        _mem, _flg = self._get_memobjs(number)
        return repr(_mem) + repr(_flg)

    def get_memory(self, number):
        _mem, _flg = self._get_memobjs(number)
        mem = chirp_common.Memory()
        mem.number = number

        if _flg.get() == 0x0F:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 100

        # compensate for 6.25 and 12.5 kHz tuning steps, add 500 Hz if needed
        lastdigit = int(_mem.freq) % 10
        if (lastdigit == 2 or lastdigit == 7):
            mem.freq += 50

        mem.offset = int(_mem.offset) * 100
        mem.name = str(_mem.name).rstrip()
        mem.duplex = DUPLEXES[_mem.duplex]
        mem.mode = _mem.is_am and "AM" or MODES[_mem.channel_width]
        mem.tuning_step = TUNING_STEPS[_mem.tune_step]

        if _mem.txoff:
            mem.duplex = DUPLEXES[3]

        rxtone = txtone = None
        rxmode = TMODES[_mem.rxtmode]
        if (_mem.sqlMode == SQL_MODES.index("Carrier") or
                _mem.sqlMode == SQL_MODES.index("Opt Sig Only")):
            rxmode = TMODES.index('')
        txmode = TMODES[_mem.txtmode]
        if txmode == "Tone":
            # If custom tone is being used, show as 88.5 (and set
            # checkbox in extras) Future: Improve chirp_common, so I
            # can add "CUSTOM" into TONES
            if _mem.txtone == len(TONES):
                txtone = 88.5
            else:
                txtone = TONES[_mem.txtone]
        elif txmode == "DTCS":
            txtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'tx')]
        if rxmode == "Tone":
            # If custom tone is being used, show as 88.5 (and set
            # checkbox in extras) Future: Improve chirp_common, so I
            # can add "CUSTOM" into TONES
            if _mem.rxtone == len(TONES):
                rxtone = 88.5
            else:
                rxtone = TONES[_mem.rxtone]
        elif rxmode == "DTCS":
            rxtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'rx')]

        rxpol = _mem.rxinv and "R" or "N"
        txpol = _mem.txinv and "R" or "N"

        chirp_common.split_tone_decode(mem,
                                       (txmode, txtone, txpol),
                                       (rxmode, rxtone, rxpol))

        mem.skip = _flg.get_skip() and "S" or _flg.get_pskip() and "P" or ""
        mem.power = POWER_LEVELS[_mem.power]

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("rev", "Reverse", RadioSettingValueBoolean(_mem.rev))
        mem.extra.append(rs)

        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(_mem.compander))
        mem.extra.append(rs)

        rs = RadioSetting("talkaround", "Talkaround",
                          RadioSettingValueBoolean(_mem.talkaround))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(
                              PTT_IDS, current_index=_mem.pttid))
        mem.extra.append(rs)

        rs = RadioSetting("bclo", "Busy Channel Lockout",
                          RadioSettingValueList(BCLO, current_index=_mem.bclo))
        mem.extra.append(rs)

        rs = RadioSetting("optsig", "Optional Signaling",
                          RadioSettingValueList(OPT_SIGS,
                                                current_index=_mem.optsig))
        mem.extra.append(rs)

        rs = RadioSetting("OPTSIGSQL", "Squelch w/Opt Signaling",
                          RadioSettingValueList(
                              OPT_SIG_SQL, SQL_MODES[_mem.sqlMode]
                              if SQL_MODES[_mem.sqlMode] in OPT_SIG_SQL
                              else "Off"))
        mem.extra.append(rs)

        rs = RadioSetting(
            "dtmfSlotNum", "DTMF",
            RadioSettingValueList(
                DTMF_SLOTS, current_index=_mem.dtmfSlotNum))
        mem.extra.append(rs)

        rs = RadioSetting("twotone", "2-Tone",
                          RadioSettingValueList(TONE2_SLOTS,
                                                current_index=_mem.twotone))
        mem.extra.append(rs)

        rs = RadioSetting("fivetone", "5-Tone",
                          RadioSettingValueList(TONE5_SLOTS,
                                                current_index=_mem.fivetone))
        mem.extra.append(rs)

        # Chose not to expose scramble rs = RadioSetting("scramble",
        # "Scrambler Switch", RadioSettingValueList(SCRAMBLE_CODES,
        # SCRAMBLE_CODES[_mem.scramble])) mem.extra.append(rs)

        # Memory properties dialog is only capable of Boolean and List
        # RadioSettingValue classes, so cannot configure it rs =
        # RadioSetting("custtone", "Custom CTCSS",
        # RadioSettingValueFloat(min(TONES), max(TONES), _mem.custtone
        # and _mem.custtone / 10 or 151.1, 0.1, 1))
        # mem.extra.append(rs)
        custToneStr = chirp_common.format_freq(_mem.custtone)

        rs = RadioSetting("CUSTTONETX",
                          "Use Custom CTCSS (%s) for Tx" % custToneStr,
                          RadioSettingValueBoolean(_mem.txtone == len(TONES)))
        mem.extra.append(rs)

        rs = RadioSetting("CUSTTONERX",
                          "Use Custom CTCSS (%s) for Rx" % custToneStr,
                          RadioSettingValueBoolean(_mem.rxtone == len(TONES)))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem, _flg = self._get_memobjs(mem.number)
        if mem.empty:
            _flg.set()
            return
        _flg.clear()
        _mem.set_raw("\x00" * MEMORY_LOCATION_SIZE)

        _mem.freq = mem.freq / 100
        _mem.offset = mem.offset / 100
        _mem.name = mem.name.ljust(7)
        _mem.is_am = mem.mode == "AM"
        _mem.tune_step = TUNING_STEPS.index(mem.tuning_step)
        if mem.duplex == "off":
            _mem.duplex = DUPLEXES.index("")
            _mem.txoff = 1
        else:
            _mem.duplex = DUPLEXES.index(mem.duplex)
            _mem.txoff = 0

        try:
            _mem.channel_width = MODES.index(mem.mode)
        except ValueError:
            _mem.channel_width = 0

        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.txtmode = TMODES.index(txmode)
        _mem.rxtmode = TMODES.index(rxmode)
        if rxmode != '':
            _mem.sqlMode = SQL_MODES.index("CTCSS/DCS")
        else:
            _mem.sqlMode = SQL_MODES.index("Carrier")
        if txmode == "Tone":
            _mem.txtone = TONES.index(txtone)
        elif txmode == "DTCS":
            self._set_dcs_index(_mem, 'tx',
                                chirp_common.ALL_DTCS_CODES.index(txtone))
        if rxmode == "Tone":
            _mem.rxtone = TONES.index(rxtone)
        elif rxmode == "DTCS":
            self._set_dcs_index(_mem, 'rx',
                                chirp_common.ALL_DTCS_CODES.index(rxtone))

        _mem.txinv = txpol == "R"
        _mem.rxinv = rxpol == "R"

        _flg.set_skip(mem.skip == "S")
        _flg.set_pskip(mem.skip == "P")

        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        for setting in mem.extra:
            if setting.get_name() == "ignore":
                LOG.debug("*** ignore: %s" % str(setting.value))
            # Future: elif setting.get_name() == "custtone": Future:
            # setattr(_mem, "custtone", setting.value.get_value() *
            # 10)
            elif setting.get_name() == "OPTSIGSQL":
                if str(setting.value) != "Off":
                    _mem.sqlMode = SQL_MODES.index(str(setting.value))
            elif setting.get_name() == "CUSTTONETX":
                if setting.value:
                    _mem.txtone = len(TONES)
            elif setting.get_name() == "CUSTTONERX":
                if setting.value:
                    _mem.rxtone = len(TONES)
            else:
                setattr(_mem, setting.get_name(), setting.value)

        return mem

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        settings = RadioSettings(basic)

        display = ["Frequency", "Channel", "Name"]
        rs = RadioSetting("display", "Display", RadioSettingValueList(
            display, current_index=_settings.display))
        basic.append(rs)

        apo = ["Off"] + ['%.1f hour(s)' % (0.5 * x) for x in range(1, 25)]
        rs = RadioSetting("apo", "Automatic Power Off",
                          RadioSettingValueList(apo,
                                                current_index=_settings.apo))
        basic.append(rs)

        def filter(s):
            s_ = ""
            for i in range(0, 8):
                c = str(s[i])
                s_ += (c if c in chirp_common.CHARSET_ASCII else "")
            return s_

        welcome_msg = ''.join(filter(_settings.welcome))
        rs = RadioSetting("welcome", "Welcome Message",
                          RadioSettingValueString(0, 8, welcome_msg))

        basic.append(rs)

        rs = RadioSetting("beep", "Beep Enabled",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        MUTE_CHOICES = ["Off", "TX", "RX", "TX/RX"]
        rs = RadioSetting("mute", "Sub Band Mute",
                          RadioSettingValueList(MUTE_CHOICES,
                                                current_index=_settings.mute))
        basic.append(rs)

        return settings

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            name = element.get_name()
            setattr(_settings, name, element.value)

    @classmethod
    def match_model(cls, filedata, filename):
        for _ident in cls._file_ident:
            if _ident in filedata[0x20:0x40]:
                return True
        return False


@directory.register
class IntekHR2040Radio(AnyTone5888UVRadio):
    """Intek HR-2040"""
    VENDOR = "Intek"
    MODEL = "HR-2040"
    _file_ident = [b"HR-2040"]


@directory.register
class PolmarDB50MRadio(AnyTone5888UVRadio):
    """Polmar DB-50M"""
    VENDOR = "Polmar"
    MODEL = "DB-50M"
    _file_ident = [b"DB-50M"]


@directory.register
class PowerwerxDB750XRadio(AnyTone5888UVRadio):
    """Powerwerx DB-750X"""
    VENDOR = "Powerwerx"
    MODEL = "DB-750X"
    _file_ident = [b"DB-750X"]

    def get_settings(self):
        return {}
