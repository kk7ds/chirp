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

import time
import struct
import os
import logging

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, errors, util, bitwise, memmap
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings
from chirp.settings import RadioSettingValueInteger, RadioSettingValueString

LOG = logging.getLogger(__name__)

mem_format = """
struct mem {
  u8 used:1,
     skip:2,
     unknown1:5;
  u8 unknown2:1,
     mode:3,
     unknown8:1,
     oddsplit:1,
     duplex:2;
  bbcd freq[3];
  u8 unknownA:1,
     tmode:3,
     unknownB:4;
  bbcd split[3];
  u8 power:2,
     tone:6;
  u8 unknownC:1,
     dtcs:7;
  u8 showalpha:1,
     unknown5:7;
  u8 unknown6;
  u8 offset;
  u8 unknown7[2];
};

struct lab {
  u8 string[8];
};

#seekto 0x0508;
struct {
  char call[6];
  u8 ssid;
} aprs_my_callsign;

#seekto 0x0480;
struct mem left_memory_zero;
#seekto 0x04A0;
struct lab left_label_zero;
#seekto 0x04C0;
struct mem right_memory_zero;
#seekto 0x04E0;
struct lab right_label_zero;

#seekto 0x0800;
struct mem left_memory[500];

#seekto 0x2860;
struct mem right_memory[500];

#seekto 0x48C0;
struct lab left_label[518];
struct lab right_label[518];
"""

_TMODES = ["", "Tone", "TSQL", "-RVT", "DTCS", "-PR", "-PAG"]
TMODES = ["", "Tone", "TSQL", "", "DTCS", "", ""]
MODES = ["FM", "AM", "NFM", "", "WFM"]
DUPLEXES = ["", "", "-", "+", "split"]
# TODO: add japaneese characters (viewable in special menu, scroll backwards)
CHARSET = \
    ('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!"' +
     '#$%&`()*+,-./:;<=>?@[\\]^_`{|}~?????? ' + '?' * 91)

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=50),
                chirp_common.PowerLevel("Mid", watts=20),
                chirp_common.PowerLevel("Low", watts=5)]

SKIPS = ["", "S", "P"]


def aprs_call_to_str(_call):
    call = ""
    for i in str(_call):
        if i == "\xca":
            break
        call += i
    return call


def _safe_read(radio, length):
    data = ""
    while len(data) < length:
        data += radio.pipe.read(length - len(data))
    return data


def _clone_in(radio):
    data = ""

    radio.pipe.timeout = 1
    attempts = 30

    data = memmap.MemoryMap("\x00" * (radio._memsize + 128))
    length = 0
    last_addr = 0
    while length < radio._memsize:
        frame = radio.pipe.read(131)
        if length and not frame:
            raise errors.RadioError("Radio not responding")

        if not frame:
            attempts -= 1
            if attempts <= 0:
                raise errors.RadioError("Radio not responding")

        if frame:
            addr, = struct.unpack(">H", frame[0:2])
            checksum = ord(frame[130])
            block = frame[2:130]

            cs = 0
            for i in frame[:-1]:
                cs = (cs + ord(i)) % 256
            if cs != checksum:
                LOG.debug("Calc: %02x Real: %02x Len: %i" %
                          (cs, checksum, len(block)))
                raise errors.RadioError("Block failed checksum")

            radio.pipe.write("\x06")
            time.sleep(0.05)

            if (last_addr + 128) != addr:
                LOG.debug("Gap, expecting %04x, got %04x" %
                          (last_addr+128, addr))
            last_addr = addr
            data[addr] = block
            length += len(block)

        status = chirp_common.Status()
        status.cur = length
        status.max = radio._memsize
        status.msg = "Cloning from radio"
        radio.status_fn(status)

    return data


def _clone_out(radio):
    radio.pipe.timeout = 1

    # Seriously, WTF Yaesu?
    ranges = [
        (0x0000, 0x0000),
        (0x0100, 0x0380),
        (0x0480, 0xFF80),
        (0x0080, 0x0080),
        (0xFFFE, 0xFFFE),
        ]

    for start, end in ranges:
        for i in range(start, end+1, 128):
            block = radio._mmap[i:i + 128]
            frame = struct.pack(">H", i) + block
            cs = 0
            for byte in frame:
                cs += ord(byte)
            frame += chr(cs % 256)
            radio.pipe.write(frame)
            ack = radio.pipe.read(1)
            if ack != "\x06":
                raise errors.RadioError("Radio refused block %i" % (i / 128))
            time.sleep(0.05)

            status = chirp_common.Status()
            status.cur = i + 128
            status.max = radio._memsize
            status.msg = "Cloning to radio"
            radio.status_fn(status)


def get_freq(rawfreq):
    """Decode a frequency that may include a fractional step flag"""
    # Ugh.  The 0x80 and 0x40 indicate values to add to get the
    # real frequency.  Gross.
    if rawfreq > 8000000000:
        rawfreq = (rawfreq - 8000000000) + 5000

    if rawfreq > 4000000000:
        rawfreq = (rawfreq - 4000000000) + 2500

    if rawfreq > 2000000000:
        rawfreq = (rawfreq - 2000000000) + 1250

    return rawfreq


def set_freq(freq, obj, field):
    """Encode a frequency with any necessary fractional step flags"""
    obj[field] = freq / 10000
    frac = freq % 10000

    if frac >= 5000:
        frac -= 5000
        obj[field][0].set_bits(0x80)

    if frac >= 2500:
        frac -= 2500
        obj[field][0].set_bits(0x40)

    if frac >= 1250:
        frac -= 1250
        obj[field][0].set_bits(0x20)

    return freq


@directory.register
class FTM350Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FTM-350"""
    BAUD_RATE = 48000
    VENDOR = "Yaesu"
    MODEL = "FTM-350"

    _model = ""
    _memsize = 65536
    _vfo = ""

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_settings = self._vfo == "left"
        rf.has_tuning_step = False
        rf.has_dtcs_polarity = False
        rf.has_sub_devices = self.VARIANT == ""
        rf.valid_skips = []  # FIXME: Finish this
        rf.valid_tmodes = [""] + [x for x in TMODES if x]
        rf.valid_modes = [x for x in MODES if x]
        rf.valid_duplexes = DUPLEXES
        rf.valid_skips = SKIPS
        rf.valid_name_length = 8
        rf.valid_characters = CHARSET
        rf.memory_bounds = (0, 500)
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_bands = [(500000,   1800000),
                          (76000000, 250000000),
                          (30000000, 1000000000)]
        rf.can_odd_split = True
        rf.valid_tuning_steps = [5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0,
                                 25.0, 50.0, 100.0, 200.0]

        return rf

    def get_sub_devices(self):
        return [FTM350RadioLeft(self._mmap), FTM350RadioRight(self._mmap)]

    def sync_in(self):
        try:
            self._mmap = _clone_in(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to download from radio (%s)" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            _clone_out(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to upload to radio (%s)" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):

        def identity(o):
            return o

        def indexed(o):
            return o[number - 1]

        if number == 0:
            suffix = "_zero"
            fn = identity
        else:
            suffix = ""
            fn = indexed
        return (repr(fn(self._memory_obj(suffix))) +
                repr(fn(self._label_obj(suffix))))

    def _memory_obj(self, suffix=""):
        return getattr(self._memobj, "%s_memory%s" % (self._vfo, suffix))

    def _label_obj(self, suffix=""):
        return getattr(self._memobj, "%s_label%s" % (self._vfo, suffix))

    def get_memory(self, number):
        if number == 0:
            _mem = self._memory_obj("_zero")
            _lab = self._label_obj("_zero")
        else:
            _mem = self._memory_obj()[number - 1]
            _lab = self._label_obj()[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        if not _mem.used:
            mem.empty = True
            return mem

        mem.freq = get_freq(int(_mem.freq) * 10000)
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tmode]

        if _mem.oddsplit:
            mem.duplex = "split"
            mem.offset = get_freq(int(_mem.split) * 10000)
        else:
            mem.duplex = DUPLEXES[_mem.duplex]
            mem.offset = int(_mem.offset) * 50000

        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.mode = MODES[_mem.mode]
        mem.skip = SKIPS[_mem.skip]
        mem.power = POWER_LEVELS[_mem.power]

        for char in _lab.string:
            if char == 0xCA:
                break
            try:
                mem.name += CHARSET[char]
            except IndexError:
                mem.name += "?"
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        if mem.number == 0:
            _mem = self._memory_obj("_zero")
            _lab = self._label_obj("_zero")
        else:
            _mem = self._memory_obj()[mem.number - 1]
            _lab = self._label_obj()[mem.number - 1]
        _mem.used = not mem.empty
        if mem.empty:
            return

        set_freq(mem.freq, _mem, 'freq')
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.mode = MODES.index(mem.mode)
        _mem.skip = SKIPS.index(mem.skip)

        _mem.oddsplit = 0
        _mem.duplex = 0
        if mem.duplex == "split":
            set_freq(mem.offset, _mem, 'split')
            _mem.oddsplit = 1
        else:
            _mem.offset = mem.offset / 50000
            _mem.duplex = DUPLEXES.index(mem.duplex)

        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        for i in range(0, 8):
            try:
                char = CHARSET.index(mem.name[i])
            except IndexError:
                char = 0xCA
            _lab.string[i] = char
        _mem.showalpha = mem.name.strip() != ""

    @classmethod
    def match_model(self, filedata, filename):
        return filedata.startswith("AH033$")

    def get_settings(self):
        top = RadioSettings()

        aprs = RadioSettingGroup("aprs", "APRS")
        top.append(aprs)

        myc = self._memobj.aprs_my_callsign
        rs = RadioSetting("aprs_my_callsign.call", "APRS My Callsign",
                          RadioSettingValueString(0, 6,
                                                  aprs_call_to_str(myc.call)))
        aprs.append(rs)

        rs = RadioSetting("aprs_my_callsign.ssid", "APRS My SSID",
                          RadioSettingValueInteger(0, 15, myc.ssid))
        aprs.append(rs)

        return top

    def set_settings(self, settings):
        for setting in settings:
            if not isinstance(setting, RadioSetting):
                self.set_settings(setting)
                continue

            # Quick hack to make these work
            if setting.get_name() == "aprs_my_callsign.call":
                self._memobj.aprs_my_callsign.call = \
                    setting.value.get_value().upper().replace(" ", "\xCA")
            elif setting.get_name() == "aprs_my_callsign.ssid":
                self._memobj.aprs_my_callsign.ssid = setting.value


class FTM350RadioLeft(FTM350Radio):
    VARIANT = "Left"
    _vfo = "left"


class FTM350RadioRight(FTM350Radio):
    VARIANT = "Right"
    _vfo = "right"
