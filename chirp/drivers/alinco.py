# Copyright 2011 Dan Smith <dsmith@danplanet.com>
#           2016 Matt Weyland <lt-betrieb@hb9uf.ch>
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

from chirp import chirp_common, bitwise, memmap, errors, directory, util
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettings

from textwrap import dedent

import time
import logging

LOG = logging.getLogger(__name__)


DRX35_MEM_FORMAT = """
#seekto 0x0120;
u8 used_flags[25];

#seekto 0x0200;
struct {
  u8 new_used:1,
     unknown1:1,
     isnarrow:1,
     isdigital:1,
     ishigh:1,
     unknown2:3;
  u8 unknown3:6,
     duplex:2;
  u8 unknown4:4,
     tmode:4;
  u8 unknown5:4,
     step:4;
  bbcd freq[4];
  u8 unknown6[1];
  bbcd offset[3];
  u8 rtone;
  u8 ctone;
  u8 dtcs_tx;
  u8 dtcs_rx;
  u8 name[7];
  u8 unknown8[2];
  u8 unknown9:6,
     power:2;
  u8 unknownA[6];
} memory[100];

#seekto 0x0130;
u8 skips[25];
"""

# 0000 0111
# 0000 0010

# Response length is:
# 1. \r\n
# 2. Four-digit address, followed by a colon
# 3. 16 bytes in hex (32 characters)
# 4. \r\n
RLENGTH = 2 + 5 + 32 + 2

STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0]


def isascii(data):
    for byte in data:
        if (ord(byte) < ord(" ") or ord(byte) > ord("~")) and \
                byte not in "\r\n":
            return False
    return True


def tohex(data):
    if isascii(data):
        return repr(data)
    string = ""
    for byte in data:
        string += "%02X" % ord(byte)
    return string


class AlincoStyleRadio(chirp_common.CloneModeRadio):
    """Base class for all known Alinco radios"""
    _memsize = 0
    _model = "NONE"

    def _send(self, data):
        LOG.debug("PC->R: (%2i) %s" % (len(data), tohex(data)))
        self.pipe.write(data)
        self.pipe.read(len(data))

    def _read(self, length):
        data = self.pipe.read(length)
        LOG.debug("R->PC: (%2i) %s" % (len(data), tohex(data)))
        return data

    def _download_chunk(self, addr):
        if addr % 16:
            raise Exception("Addr 0x%04x not on 16-byte boundary" % addr)

        cmd = "AL~F%04XR\r\n" % addr
        self._send(cmd)

        resp = self._read(RLENGTH).strip()
        if len(resp) == 0:
            raise errors.RadioError("No response from radio")
        if ":" not in resp:
            raise errors.RadioError("Unexpected response from radio")
        addr, _data = resp.split(":", 1)
        data = ""
        for i in range(0, len(_data), 2):
            data += chr(int(_data[i:i+2], 16))

        if len(data) != 16:
            LOG.debug("Response was:")
            LOG.debug("|%s|")
            LOG.debug("Which I converted to:")
            LOG.debug(util.hexprint(data))
            raise Exception("Radio returned less than 16 bytes")

        return data

    def _download(self, limit):
        self._identify()

        data = ""
        for addr in range(0, limit, 16):
            data += self._download_chunk(addr)
            time.sleep(0.1)

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr + 16
                status.max = self._memsize
                status.msg = "Downloading from radio"
                self.status_fn(status)

        self._send("AL~E\r\n")
        self._read(20)

        return memmap.MemoryMap(data)

    def _identify(self):
        for _i in range(0, 3):
            self._send("%s\r\n" % self._model)
            resp = self._read(6)
            if resp.strip() == "OK":
                return True
            time.sleep(1)

        return False

    def _upload_chunk(self, addr):
        if addr % 16:
            raise Exception("Addr 0x%04x not on 16-byte boundary" % addr)

        _data = self._mmap[addr:addr+16]
        data = "".join(["%02X" % ord(x) for x in _data])

        cmd = "AL~F%04XW%s\r\n" % (addr, data)
        self._send(cmd)

    def _upload(self, limit):
        if not self._identify():
            raise Exception("I can't talk to this model")

        for addr in range(0x100, limit, 16):
            self._upload_chunk(addr)
            time.sleep(0.1)

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr + 16
                status.max = self._memsize
                status.msg = "Uploading to radio"
                self.status_fn(status)

        self._send("AL~E\r\n")
        self.pipe._read(20)

    def process_mmap(self):
        self._memobj = bitwise.parse(DRX35_MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = self._download(self._memsize)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            self._upload(self._memsize)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])


DUPLEX = ["", "-", "+"]
TMODES = ["", "Tone", "", "TSQL"] + [""] * 12
TMODES[12] = "DTCS"
DCS_CODES = {
    "Alinco": chirp_common.DTCS_CODES,
    "Jetstream": [17] + chirp_common.DTCS_CODES,
}

CHARSET = (["\x00"] * 0x30) + \
    [chr(x + ord("0")) for x in range(0, 10)] + \
    [chr(x + ord("A")) for x in range(0, 26)] + [" "] + \
    list("\x00" * 128)


def _get_name(_mem):
    name = ""
    for i in _mem.name:
        if i in [0x00, 0xFF]:
            break
        name += CHARSET[i]
    return name


def _set_name(mem, _mem):
    name = [0x00] * 7
    j = 0
    for i in range(0, 7):
        try:
            name[j] = CHARSET.index(mem.name[i])
            j += 1
        except IndexError:
            pass
        except ValueError:
            pass
    return name

ALINCO_TONES = list(chirp_common.TONES)
ALINCO_TONES.remove(159.8)
ALINCO_TONES.remove(165.5)
ALINCO_TONES.remove(171.3)
ALINCO_TONES.remove(177.3)
ALINCO_TONES.remove(183.5)
ALINCO_TONES.remove(189.9)
ALINCO_TONES.remove(196.6)
ALINCO_TONES.remove(199.5)
ALINCO_TONES.remove(206.5)
ALINCO_TONES.remove(229.1)
ALINCO_TONES.remove(254.1)


class DRx35Radio(AlincoStyleRadio):
    """Base class for the DR-x35 radios"""
    _range = [(118000000, 155000000)]
    _power_levels = []
    _valid_tones = ALINCO_TONES

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_skips = ["", "S"]
        rf.valid_bands = self._range
        rf.memory_bounds = (0, 99)
        rf.has_ctone = True
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.can_delete = False
        rf.valid_tuning_steps = STEPS
        rf.valid_name_length = 7
        rf.valid_power_levels = self._power_levels
        return rf

    def _get_used(self, number):
        _usd = self._memobj.used_flags[number / 8]
        bit = (0x80 >> (number % 8))
        return _usd & bit

    def _set_used(self, number, is_used):
        _usd = self._memobj.used_flags[number / 8]
        bit = (0x80 >> (number % 8))
        if is_used:
            _usd |= bit
        else:
            _usd &= ~bit

    def _get_power(self, _mem):
        if self._power_levels:
            return self._power_levels[_mem.ishigh]
        return None

    def _set_power(self, _mem, mem):
        if self._power_levels:
            _mem.ishigh = mem.power is None or \
                mem.power == self._power_levels[1]

    def _get_extra(self, _mem, mem):
        mem.extra = RadioSettingGroup("extra", "Extra")
        dig = RadioSetting("isdigital", "Digital",
                           RadioSettingValueBoolean(bool(_mem.isdigital)))
        dig.set_doc("Digital/Packet mode enabled")
        mem.extra.append(dig)

    def _set_extra(self, _mem, mem):
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _skp = self._memobj.skips[number / 8]
        _usd = self._memobj.used_flags[number / 8]
        bit = (0x80 >> (number % 8))

        mem = chirp_common.Memory()
        mem.number = number
        if not self._get_used(number) and self.MODEL != "JT220M":
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 100
        mem.rtone = self._valid_tones[_mem.rtone]
        mem.ctone = self._valid_tones[_mem.ctone]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.offset = int(_mem.offset) * 100
        mem.tmode = TMODES[_mem.tmode]
        mem.dtcs = DCS_CODES[self.VENDOR][_mem.dtcs_tx]
        mem.tuning_step = STEPS[_mem.step]

        if _mem.isnarrow:
            mem.mode = "NFM"

        mem.power = self._get_power(_mem)

        if _skp & bit:
            mem.skip = "S"

        mem.name = _get_name(_mem).rstrip()

        self._get_extra(_mem, mem)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _skp = self._memobj.skips[mem.number / 8]
        _usd = self._memobj.used_flags[mem.number / 8]
        bit = (0x80 >> (mem.number % 8))

        if self._get_used(mem.number) and not mem.empty:
            # Initialize the memory
            _mem.set_raw("\x00" * 32)

        self._set_used(mem.number, not mem.empty)
        if mem.empty:
            return

        _mem.freq = mem.freq / 100

        try:
            _tone = mem.rtone
            _mem.rtone = self._valid_tones.index(mem.rtone)
            _tone = mem.ctone
            _mem.ctone = self._valid_tones.index(mem.ctone)
        except ValueError:
            raise errors.UnsupportedToneError("This radio does not support " +
                                              "tone %.1fHz" % _tone)

        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.offset = mem.offset / 100
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.dtcs_tx = DCS_CODES[self.VENDOR].index(mem.dtcs)
        _mem.dtcs_rx = DCS_CODES[self.VENDOR].index(mem.dtcs)
        _mem.step = STEPS.index(mem.tuning_step)

        _mem.isnarrow = mem.mode == "NFM"
        self._set_power(_mem, mem)

        if mem.skip:
            _skp |= bit
        else:
            _skp &= ~bit

        _mem.name = _set_name(mem, _mem)

        self._set_extra(_mem, mem)


@directory.register
class DR03Radio(DRx35Radio):
    """Alinco DR03"""
    VENDOR = "Alinco"
    MODEL = "DR03T"

    _model = "DR135"
    _memsize = 4096
    _range = [(28000000, 29695000)]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x00) and filedata[0x65] == chr(0x28)


@directory.register
class DR06Radio(DRx35Radio):
    """Alinco DR06"""
    VENDOR = "Alinco"
    MODEL = "DR06T"

    _model = "DR435"
    _memsize = 4096
    _range = [(50000000, 53995000)]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x00) and filedata[0x65] == chr(0x50)


@directory.register
class DR135Radio(DRx35Radio):
    """Alinco DR135"""
    VENDOR = "Alinco"
    MODEL = "DR135T"

    _model = "DR135"
    _memsize = 4096
    _range = [(118000000, 173000000)]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x01) and filedata[0x65] == chr(0x44)


@directory.register
class DR235Radio(DRx35Radio):
    """Alinco DR235"""
    VENDOR = "Alinco"
    MODEL = "DR235T"

    _model = "DR235"
    _memsize = 4096
    _range = [(216000000, 280000000)]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x02) and filedata[0x65] == chr(0x22)


@directory.register
class DR435Radio(DRx35Radio):
    """Alinco DR435"""
    VENDOR = "Alinco"
    MODEL = "DR435T"

    _model = "DR435"
    _memsize = 4096
    _range = [(350000000, 511000000)]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x04) and filedata[0x65] == chr(0x00)


@directory.register
class DJ596Radio(DRx35Radio):
    """Alinco DJ596"""
    VENDOR = "Alinco"
    MODEL = "DJ596"

    _model = "DJ596"
    _memsize = 4096
    _range = [(136000000, 174000000), (400000000, 511000000)]
    _power_levels = [chirp_common.PowerLevel("Low", watts=1.00),
                     chirp_common.PowerLevel("High", watts=5.00)]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0x64] == chr(0x45) and filedata[0x65] == chr(0x01)


@directory.register
class JT220MRadio(DRx35Radio):
    """Jetstream JT220"""
    VENDOR = "Jetstream"
    MODEL = "JT220M"

    _model = "DR136"
    _memsize = 8192
    _range = [(216000000, 280000000)]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0x60:0x64] == "2009"


@directory.register
class DJ175Radio(DRx35Radio):
    """Alinco DJ175"""
    VENDOR = "Alinco"
    MODEL = "DJ175"

    _model = "DJ175"
    _memsize = 6896
    _range = [(136000000, 174000000), (400000000, 511000000)]
    _power_levels = [
        chirp_common.PowerLevel("Low", watts=0.50),
        chirp_common.PowerLevel("Mid", watts=2.00),
        chirp_common.PowerLevel("High", watts=5.00),
        ]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    def _get_used(self, number):
        return self._memobj.memory[number].new_used

    def _set_used(self, number, is_used):
        self._memobj.memory[number].new_used = is_used

    def _get_power(self, _mem):
        return self._power_levels[_mem.power]

    def _set_power(self, _mem, mem):
        if mem.power in self._power_levels:
            _mem.power = self._power_levels.index(mem.power)

    def _download_chunk(self, addr):
        if addr % 16:
            raise Exception("Addr 0x%04x not on 16-byte boundary" % addr)

        cmd = "AL~F%04XR\r\n" % addr
        self._send(cmd)

        _data = self._read(34).strip()
        if len(_data) == 0:
            raise errors.RadioError("No response from radio")

        data = ""
        for i in range(0, len(_data), 2):
            data += chr(int(_data[i:i+2], 16))

        if len(data) != 16:
            LOG.debug("Response was:")
            LOG.debug("|%s|")
            LOG.debug("Which I converted to:")
            LOG.debug(util.hexprint(data))
            raise Exception("Radio returned less than 16 bytes")

        return data


DJG7EG_MEM_FORMAT = """
#seekto 0x200;
ul16 bank[50];
ul16 special_bank[7];
#seekto 0x1200;
struct {
    u8   empty;
    ul32 freq;
    u8   mode;
    u8   step;
    ul32 offset;
    u8   duplex;
    u8   squelch_type;
    u8   tx_tone;
    u8   rx_tone;
    u8   dcs;
    ul24 unknown1;
    u8   skip;
    ul32 unknown2;
    ul32 unknown3;
    ul32 unknown4;
    char name[32];
} memory[1000];
"""


@directory.register
class AlincoDJG7EG(AlincoStyleRadio):
    """Alinco DJ-G7EG"""
    VENDOR = "Alinco"
    MODEL = "DJ-G7EG"
    BAUD_RATE = 57600

    # Those are different from the other Alinco radios.
    STEPS = [5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0,
             100.0, 125.0, 150.0, 200.0, 500.0, 1000.0]
    DUPLEX = ["", "+", "-"]
    MODES = ["NFM", "FM", "AM", "WFM"]
    TMODES = ["", "??1", "Tone", "TSQL", "TSQL-R", "DTCS"]

    # This is a bit of a hack to avoid overwriting _identify()
    _model = "AL~DJ-G7EG"
    _memsize = 0x1a7c0
    _range = [(500000, 1300000000)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Ensure your firmware version is 4_10 or higher
            2. Turn radio off
            3. Connect your interface cable
            4. Turn radio on
            5. Press and release PTT 3 times while holding MONI key
            6. Supported baud rates: 57600 (default) and 19200
               (rotate dial while holding MONI to change)
            7. Click OK
            """))
        rp.pre_upload = _(dedent("""\
            1. Ensure your firmware version is 4_10 or higher
            2. Turn radio off
            3. Connect your interface cable
            4. Turn radio on
            5. Press and release PTT 3 times while holding MONI key
            6. Supported baud rates: 57600 (default) and 19200
               (rotate dial while holding MONI to change)
            7. Click OK
            """))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_settings = False

        rf.valid_modes = self.MODES
        rf.valid_tmodes = ["", "Tone", "TSQL", "Cross", "TSQL-R", "DTCS"]
        rf.valid_tuning_steps = self.STEPS
        rf.valid_bands = self._range
        rf.valid_skips = ["", "S"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 16
        rf.memory_bounds = (0, 999)

        return rf

    def _download_chunk(self, addr):
        if addr % 0x40:
            raise Exception("Addr 0x%04x not on 64-byte boundary" % addr)

        cmd = "AL~F%05XR\r" % addr
        self._send(cmd)

        # Response: "\r\n[ ... data ... ]\r\n
        # data is encoded in hex, hence we read two chars per byte
        _data = self._read(2+2*64+2).strip()
        if len(_data) == 0:
            raise errors.RadioError("No response from radio")

        data = ""
        for i in range(0, len(_data), 2):
            data += chr(int(_data[i:i+2], 16))

        if len(data) != 64:
            LOG.debug("Response was:")
            LOG.debug("|%s|")
            LOG.debug("Which I converted to:")
            LOG.debug(util.hexprint(data))
            raise Exception("Chunk from radio has wrong size")

        return data

    def _detect_baudrate_and_identify(self):
        if self._identify():
            return True
        else:
            # Apparenly Alinco support suggests to try again at a lower baud
            # rate if their cable fails with the default rate. See #4355.
            LOG.info("Could not talk to radio. Trying again at 19200 baud")
            self.pipe.baudrate = 19200
            return self._identify()

    def _download(self, limit):
        self._detect_baudrate_and_identify()

        data = "\x00"*0x200

        for addr in range(0x200, limit, 0x40):
            data += self._download_chunk(addr)
            # Other Alinco drivers delay here, but doesn't seem to be necessary
            # for this model.

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr
                status.max = limit
                status.msg = "Downloading from radio"
                self.status_fn(status)
        return memmap.MemoryMap(data)

    def _upload_chunk(self, addr):
        if addr % 0x40:
            raise Exception("Addr 0x%04x not on 64-byte boundary" % addr)

        _data = self._mmap[addr:addr+0x40]
        data = "".join(["%02X" % ord(x) for x in _data])

        cmd = "AL~F%05XW%s\r" % (addr, data)
        self._send(cmd)

        resp = self._read(6)
        if resp.strip() != "OK":
            raise Exception("Unexpected response from radio: %s" % resp)

    def _upload(self, limit):
        if not self._detect_baudrate_and_identify():
            raise Exception("I can't talk to this model")

        for addr in range(0x200, self._memsize, 0x40):
            self._upload_chunk(addr)
            # Other Alinco drivers delay here, but doesn't seem to be necessary
            # for this model.

            if self.status_fn:
                status = chirp_common.Status()
                status.cur = addr
                status.max = self._memsize
                status.msg = "Uploading to radio"
                self.status_fn(status)

    def _get_empty_flag(self, freq, mode):
        # Returns flag used to hide a channel from the main band. This occurs
        # when the mode is anything but NFM or FM (main band can only do those)
        # or when the frequency is outside of the range supported by the main
        # band.
        if mode not in ("NFM", "FM"):
            return 0x01
        if (freq >= 136000000 and freq < 174000000) or \
           (freq >= 400000000 and freq < 470000000) or \
           (freq >= 1240000000 and freq < 1300000000):
            return 0x02
        else:
            return 0x01

    def _check_channel_consistency(self, number):
        _mem = self._memobj.memory[number]
        if _mem.empty != 0x00:
            if _mem.unknown1 == 0xffffff:
                # Previous versions of this code have skipped the unknown
                # fields. They contain bytes of value if the channel is empty
                # and thus those bytes remain 0xff when the channel is put to
                # use. The radio is totally fine with this but the Alinco
                # programming software is not (see #5275). Here, we check for
                # this and report if it is encountered.
                LOG.warning("Channel %d is inconsistent: Found 0xff in "
                            "non-empty channel. Touch channel to fix."
                            % number)

            if _mem.empty != self._get_empty_flag(_mem.freq,
                                                  self.MODES[_mem.mode]):
                LOG.warning("Channel %d is inconsistent: Found out of band "
                            "frequency. Touch channel to fix." % number)

    def process_mmap(self):
        self._memobj = bitwise.parse(DJG7EG_MEM_FORMAT, self._mmap)
        # We check all channels for corruption (see bug #5275) but we don't fix
        # it automatically because it would be unpolite to modify something on
        # a read operation. A log message is emitted though for the user to
        # take actions.
        for number in range(len(self._memobj.memory)):
            self._check_channel_consistency(number)

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        mem = chirp_common.Memory()
        mem.number = number
        if _mem.empty == 0:
            mem.empty = True
        else:
            mem.freq = int(_mem.freq)
            mem.mode = self.MODES[_mem.mode]
            mem.tuning_step = self.STEPS[_mem.step]
            mem.offset = int(_mem.offset)
            mem.duplex = self.DUPLEX[_mem.duplex]
            if self.TMODES[_mem.squelch_type] == "TSQL" and \
                    _mem.tx_tone != _mem.rx_tone:
                mem.tmode = "Cross"
                mem.cross_mode = "Tone->Tone"
            else:
                mem.tmode = self.TMODES[_mem.squelch_type]
            mem.rtone = ALINCO_TONES[_mem.tx_tone-1]
            mem.ctone = ALINCO_TONES[_mem.rx_tone-1]
            mem.dtcs = DCS_CODES[self.VENDOR][_mem.dcs]
            if _mem.skip:
                mem.skip = "S"
            # FIXME find out what every other byte is used for. Japanese?
            mem.name = str(_mem.name.get_raw()[::2]).rstrip('\0')
        return mem

    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number]
        if mem.empty:
            _mem.set_raw("\xff" * (_mem.size()/8))
            _mem.empty = 0x00
        else:
            _mem.empty = self._get_empty_flag(mem.freq, mem.mode)
            _mem.freq = mem.freq
            _mem.mode = self.MODES.index(mem.mode)
            _mem.step = self.STEPS.index(mem.tuning_step)
            _mem.offset = mem.offset
            _mem.duplex = self.DUPLEX.index(mem.duplex)
            if mem.tmode == "Cross":
                _mem.squelch_type = self.TMODES.index("TSQL")
                try:
                    _mem.tx_tone = ALINCO_TONES.index(mem.rtone)+1
                except ValueError:
                    raise errors.UnsupportedToneError(
                        "This radio does not support tone %.1fHz" % mem.rtone)
                try:
                    _mem.rx_tone = ALINCO_TONES.index(mem.ctone)+1
                except ValueError:
                    raise errors.UnsupportedToneError(
                        "This radio does not support tone %.1fHz" % mem.ctone)
            elif mem.tmode == "TSQL":
                _mem.squelch_type = self.TMODES.index("TSQL")
                # Note how the same TSQL tone is copied to both memory
                # locaations
                try:
                    _mem.tx_tone = ALINCO_TONES.index(mem.ctone)+1
                    _mem.rx_tone = ALINCO_TONES.index(mem.ctone)+1
                except ValueError:
                    raise errors.UnsupportedToneError(
                        "This radio does not support tone %.1fHz" % mem.ctone)
            else:
                _mem.squelch_type = self.TMODES.index(mem.tmode)
                try:
                    _mem.tx_tone = ALINCO_TONES.index(mem.rtone)+1
                except ValueError:
                    raise errors.UnsupportedToneError(
                        "This radio does not support tone %.1fHz" % mem.rtone)
                try:
                    _mem.rx_tone = ALINCO_TONES.index(mem.ctone)+1
                except ValueError:
                    raise errors.UnsupportedToneError(
                        "This radio does not support tone %.1fHz" % mem.ctone)
            _mem.dcs = DCS_CODES[self.VENDOR].index(mem.dtcs)
            _mem.skip = (mem.skip == "S")
            _mem.name = "\x00".join(mem.name).ljust(32, "\x00")
            _mem.unknown1 = 0x3e001c
            _mem.unknown2 = 0x0000000a
            _mem.unknown3 = 0x00000000
            _mem.unknown4 = 0x00000000
