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

from chirp import chirp_common, yaesu_clone, directory, errors, util
from chirp import ft7800
from chirp import bitwise, memmap
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueInteger, RadioSettingValueString

mem_format = """
struct mem {
  u8 used:1,
     skip:2,
     unknown1:5;
  u8 unknown2:1,
     mode:3,
     unknown8:2,
     duplex:2;
  bbcd freq[3];
  u8 unknownA:1,
     tmode:3,
     unknownB:4;
  u8 unknown3[3];
  u8 unknown4:2,
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
DUPLEXES = ["", "-", "+"]
CHARSET = ('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!"' +
           '                                                                ')
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

    radio.pipe.setTimeout(1)
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
                print "Calc: %02x Real: %02x Len: %i" % (cs, checksum,
                                                         len(block))
                raise errors.RadioError("Block failed checksum")

            radio.pipe.write("\x06")
            time.sleep(0.05)

            if os.getenv("CHIRP_DEBUG") and (last_addr + 128) != addr:
                print "Gap, expecting %04x, got %04x" % (last_addr+128, addr)
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
    radio.pipe.setTimeout(1)

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
        rf.valid_skips = [] # FIXME: Finish this
        rf.valid_tmodes = [""] + [x for x in TMODES if x]
        rf.valid_modes = [x for x in MODES if x]
        rf.valid_duplexes = DUPLEXES
        rf.valid_skips = SKIPS
        rf.memory_bounds = (1, 500)
        rf.valid_bands = [(  500000,    1800000),
                          (76000000,  250000000),
                          (30000000, 1000000000)]
        return rf

    def get_sub_devices(self):
        return [FTM350RadioLeft(self._mmap), FTM350RadioRight(self._mmap)]

    def sync_in(self):
        try:
            self._mmap = _clone_in(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to download from radio (%s)" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            _clone_out(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to upload to radio (%s)" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return (repr(self._memory_obj()[number - 1]) + 
                repr(self._label_obj()[number - 1]))

    def _memory_obj(self):
        return getattr(self._memobj, "%s_memory" % self._vfo)

    def _label_obj(self):
        return getattr(self._memobj, "%s_label" % self._vfo)

    def get_memory(self, number):
        _mem = self._memory_obj()[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        if not _mem.used:
            mem.empty = True
            return mem

        mem.freq = ft7800.get_freq(int(_mem.freq) * 10000)
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tmode]
        mem.duplex = DUPLEXES[_mem.duplex - 1]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.offset = int(_mem.offset) * 50000
        mem.mode = MODES[_mem.mode]
        mem.skip = SKIPS[_mem.skip]

        for char in self._label_obj()[number - 1].string:
            if char == 0xCA:
                break
            try:
                mem.name += CHARSET[char]
            except IndexError:
                mem.name += "?"
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memory_obj()[mem.number - 1]
        _mem.used = not mem.empty
        if mem.empty:
            return

        ft7800.set_freq(mem.freq, _mem, 'freq')
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEXES.index(mem.duplex) + 1
        _mem.offset = mem.offset / 50000
        _mem.mode = MODES.index(mem.mode)
        _mem.skip = SKIPS.index(mem.skip)

        for i in range(0, 8):
            try:
                char = CHARSET.index(mem.name[i])
            except IndexError:
                char = 0xCA
            self._label_obj()[mem.number - 1].string[i] = char
        _mem.showalpha = mem.name.strip() != ""

    @classmethod
    def match_model(self, filedata, filename):
        return filedata.startswith("AH033$")

    def get_settings(self):
        top = RadioSettingGroup("all", "All Settings")

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
