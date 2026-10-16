# Copyright 2026
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

import logging
import struct

from chirp import bitwise, chirp_common, directory, errors, memmap, util
from chirp import kenwood_tone
from chirp.settings import RadioSetting, RadioSettingGroup, RadioSettings, \
    RadioSettingValueBoolean, RadioSettingValueInteger, RadioSettingValueList

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown1:3,
     bcl:2,
     unknown2:3;
  u8 unknown3:2,
     highpower:1,
     wide:1,
     unknown4:4;
  u8 unknown5[2];
} memory[16];

#seekto 0x012F;
struct {
  u8 voice;
  u8 tot;
  u8 totalert;
  u8 unknown1[2];
  u8 squelch;
  u8 save;
  u8 beep;
  u8 unknown2[2];
  u8 vox;
  u8 voxgain;
  u8 voxdelay;
} settings;

#seekto 0x017E;
u8 skipflags[2];
"""

BLOCK_SIZE = 0x08
MEM_SIZE = 0x0400
WRITE_END = 0x0330
ACK = b"\x06"
FILEID = b"P32073"

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                chirp_common.PowerLevel("High", watts=5.00)]
DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
BCL_LIST = ["Off", "Carrier", "QT/DQT"]
TIMEOUTTIMER_LIST = ["Off"] + ["%s seconds" % x for x in range(15, 615, 15)]
TOTALERT_LIST = ["Off"] + ["%s seconds" % x for x in range(1, 11)]
VOICE_LIST = ["Off", "Chinese", "English"]
VOX_LIST = ["Off"] + ["%s" % x for x in range(1, 17)]
VOXDELAY_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
TONE_MODEL = kenwood_tone.KenwoodToneModel(
    dcs_base=0x2800, pol_mask=0x8000, tone_init=0xFFFF, tone_flag=0x0000)
EMPTY_CHANNEL = b"\x00" * 8 + b"\xFF\xFF\xFF\xFF" + b"\x00\xBF\xA0\xF8"


def _enter_programming_mode(radio):
    serial = radio.pipe
    serial.timeout = 1
    try:
        serial.parity = "N"
        serial.flush()
    except Exception:
        pass

    ack = b""
    for _attempt in range(5):
        serial.write(b"PROGRAM")
        ack = serial.read(1)
        if ack == ACK:
            break
    if not ack:
        raise errors.RadioNoResponse()
    if ack != ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    serial.write(b"\x02")
    ident = serial.read(8)
    if len(ident) != 8 or not ident.startswith(FILEID):
        LOG.debug("Incorrect model ID, got %s", util.hexprint(ident))
        raise errors.RadioError(
            "Incorrect model ID, got %r, it does not contain %s" %
            (ident, FILEID.decode()))

    serial.write(ACK)
    ack = serial.read(1)
    if ack != ACK:
        raise errors.RadioError("Radio refused to enter programming mode")
    LOG.debug("Radio ident is %r", ident)
    return ident


def _exit_programming_mode(radio):
    try:
        radio.pipe.write(b"E")
    except Exception:
        LOG.debug("Radio did not leave programming mode")


def _read_block(radio, addr):
    cmd = struct.pack(">cHb", b"R", addr, BLOCK_SIZE)
    expected = b"W" + cmd[1:]
    radio.pipe.write(cmd)
    response = radio.pipe.read(4 + BLOCK_SIZE)
    if len(response) != 4 + BLOCK_SIZE or response[:4] != expected:
        LOG.debug("Bad block %04x: %s", addr, util.hexprint(response))
        raise errors.RadioError("Failed to read block at %04x" % addr)
    radio.pipe.write(ACK)
    if radio.pipe.read(1) != ACK:
        raise errors.RadioError("No ACK reading block at %04x" % addr)
    return response[4:]


def _write_block(radio, addr):
    data = radio.get_mmap()[addr:addr + BLOCK_SIZE]
    cmd = struct.pack(">cHb", b"W", addr, BLOCK_SIZE) + data
    radio.pipe.write(cmd)
    if radio.pipe.read(1) != ACK:
        raise errors.RadioError("No ACK writing block at %04x" % addr)


def _do_download(radio):
    _enter_programming_mode(radio)
    try:
        data = b""
        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        status.max = MEM_SIZE
        for addr in range(0, MEM_SIZE, BLOCK_SIZE):
            status.cur = addr + BLOCK_SIZE
            radio.status_fn(status)
            data += _read_block(radio, addr)
        return memmap.MemoryMapBytes(data)
    finally:
        _exit_programming_mode(radio)


def _do_upload(radio):
    _enter_programming_mode(radio)
    try:
        status = chirp_common.Status()
        status.msg = "Uploading to radio"
        status.max = WRITE_END
        for addr in range(0, WRITE_END, BLOCK_SIZE):
            status.cur = addr + BLOCK_SIZE
            radio.status_fn(status)
            _write_block(radio, addr)
    finally:
        _exit_programming_mode(radio)


def _clamp(value, limit):
    value = int(value)
    if value < 0 or value >= limit:
        return 0
    return value


class TK3207Alias(chirp_common.Alias):
    VENDOR = "Kenwood"
    MODEL = "TK-3207"


@directory.register
class HYTF3Radio(chirp_common.CloneModeRadio,
                 chirp_common.ExperimentalRadio):
    """HYT F3, a P32073 clone of the Kenwood TK-3207"""
    VENDOR = "HYT"
    MODEL = "F3"
    BAUD_RATE = 9600
    ALIASES = [TK3207Alias]
    NEEDS_COMPAT_SERIAL = False

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = _(
            "This driver was written for the HYT F3, which identifies "
            "itself as P32073 and is a clone of the Kenwood TK-3207. "
            "It does not program a genuine TK-3207.")
        rp.pre_download = _(
            "1. Turn off the radio\n"
            "2. Connect the interface cable\n"
            "3. Turn the radio on\n"
            "4. Download from the radio\n")
        rp.pre_upload = _(
            "1. Turn off the radio\n"
            "2. Connect the interface cable\n"
            "3. Turn the radio on\n"
            "4. Upload to the radio\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]
        rf.valid_dtcs_codes = DTCS_CODES
        rf.memory_bounds = (1, 16)
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
        rf.valid_bands = [(400000000, 520000000)]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = _do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Unexpected error during download: %s", e)
            raise errors.RadioError("Error downloading data from radio")
        self.process_mmap()

    def sync_out(self):
        try:
            _do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Unexpected error during upload: %s", e)
            raise errors.RadioError("Error uploading data to radio")

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _skip_flags(self, number):
        bitpos = 1 << ((number - 1) % 8)
        bytepos = (number - 1) // 8
        return bitpos, self._memobj.skipflags[bytepos]

    def _channel_template(self):
        for i in range(16):
            raw = self._memobj.memory[i].get_raw()
            if raw[:4] not in (b"\xFF\xFF\xFF\xFF", b"\x00\x00\x00\x00"):
                return raw
        return EMPTY_CHANNEL

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        bitpos, _skp = self._skip_flags(number)
        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = int(_mem.rxfreq) * 10

        if mem.freq == 0 or _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            mem.skip = "S"
            return mem

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.duplex = "off"
            mem.offset = 0
        else:
            mem.duplex = "-" if int(_mem.rxfreq) > int(_mem.txfreq) else "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = "FM" if _mem.wide else "NFM"
        TONE_MODEL.get_tone(_mem, mem)
        mem.power = POWER_LEVELS[int(_mem.highpower)]
        mem.skip = "" if (_skp & bitpos) else "S"

        mem.extra = RadioSettingGroup("Extra", "extra")
        bcl = _clamp(_mem.bcl, len(BCL_LIST))
        mem.extra.append(RadioSetting(
            "bcl", "Busy Channel Lockout",
            RadioSettingValueList(BCL_LIST, current_index=bcl)))
        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        bitpos, _skp = self._skip_flags(mem.number)

        if mem.empty:
            _mem.set_raw(b"\xFF" * 16)
            _skp &= ~bitpos
            return

        if _mem.rxfreq.get_raw() in (b"\xFF\xFF\xFF\xFF", b"\x00\x00\x00\x00"):
            _mem.set_raw(self._channel_template())

        _mem.rxfreq = mem.freq // 10
        if mem.duplex == "off":
            _mem.txfreq.set_raw(b"\xFF\xFF\xFF\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) // 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) // 10
        else:
            _mem.txfreq = mem.freq // 10

        _mem.wide = mem.mode == "FM"
        TONE_MODEL.set_tone(mem, _mem)
        try:
            _mem.highpower = POWER_LEVELS.index(mem.power)
        except ValueError:
            _mem.highpower = 1

        if mem.skip != "S":
            _skp |= bitpos
        else:
            _skp &= ~bitpos

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), int(setting.value))

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        basic.append(RadioSetting(
            "squelch", "Squelch Level",
            RadioSettingValueInteger(0, 9, _clamp(_settings.squelch, 10))))
        basic.append(RadioSetting(
            "tot", "Time-out timer",
            RadioSettingValueList(
                TIMEOUTTIMER_LIST,
                current_index=_clamp(_settings.tot, len(TIMEOUTTIMER_LIST)))))
        basic.append(RadioSetting(
            "totalert", "TOT Pre-alert",
            RadioSettingValueList(
                TOTALERT_LIST,
                current_index=_clamp(_settings.totalert,
                                     len(TOTALERT_LIST)))))
        basic.append(RadioSetting(
            "voice", "Voice Prompts",
            RadioSettingValueList(
                VOICE_LIST,
                current_index=_clamp(_settings.voice, len(VOICE_LIST)))))
        basic.append(RadioSetting(
            "beep", "Beep",
            RadioSettingValueBoolean(bool(_settings.beep))))
        basic.append(RadioSetting(
            "save", "Battery Save",
            RadioSettingValueBoolean(bool(_settings.save))))
        basic.append(RadioSetting(
            "vox", "VOX",
            RadioSettingValueBoolean(bool(_settings.vox))))
        basic.append(RadioSetting(
            "voxgain", "VOX Gain",
            RadioSettingValueList(
                VOX_LIST,
                current_index=_clamp(_settings.voxgain, len(VOX_LIST)))))
        basic.append(RadioSetting(
            "voxdelay", "VOX Delay",
            RadioSettingValueList(
                VOXDELAY_LIST,
                current_index=_clamp(_settings.voxdelay,
                                     len(VOXDELAY_LIST)))))
        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if "." in element.get_name():
                bits = element.get_name().split(".")
                obj = self._memobj
                for bit in bits[:-1]:
                    obj = getattr(obj, bit)
                setting = bits[-1]
            else:
                obj = self._memobj.settings
                setting = element.get_name()
            setattr(obj, setting, int(element.value))

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) != MEM_SIZE:
            return False
        return filedata[0x01B8:0x01C0].startswith(FILEID)
