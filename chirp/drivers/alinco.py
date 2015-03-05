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

from chirp import chirp_common, bitwise, memmap, errors, directory, util
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettings

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
