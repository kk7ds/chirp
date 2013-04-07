# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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
from chirp import chirp_common, directory, bitwise, memmap, errors, util

mem_format = """
struct memory {
  lbcd freq[4];
  lbcd offset[4];
  u8 unknown1:2,
     txpol:1,
     rxpol:1,
     unknown2:4;
  u8 rxtone;
  u8 txtone;
  u8 unknown3:1,
     scanadd:1,
     isnarrow:1,
     unknown4:3,
     duplex:2;
  u8 unknown[4];
};

#seekto 0x0000;
char ident[32];
u8 blank[16];
struct memory vfo1;
struct memory channels[128];
#seekto 0x0850;
struct memory vfo2;

#seekto 0x0A30;
struct {
  u8 name[5];
} names[128];
"""

def do_ident(radio):
    radio.pipe.setTimeout(3)
    radio.pipe.write("PROGRAM")
    ack = radio.pipe.read(1)
    if ack != '\x06':
        raise errors.RadioError("Radio did not ack programming mode")
    radio.pipe.write("\x02")
    ident = radio.pipe.read(8)
    print util.hexprint(ident)
    if ident != "HKT511\x00\x04":
        raise errors.RadioError("Unsupported model")
    radio.pipe.write("\x06")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio did not ack ident")

def do_status(radio, direction, addr):
    status = chirp_common.Status()
    status.msg = "Cloning %s radio" % direction
    status.cur = addr
    status.max = 0x1000
    radio.status_fn(status)

def do_download(radio):
    do_ident(radio)
    data = "KT511 Radio Program data v1.08\x00\x00"
    data += ("\x00" * 16)

    for i in range(0, 0x1000, 16):
        frame = struct.pack(">cHB", "R", i, 16)
        radio.pipe.write(frame)
        result = radio.pipe.read(20)
        if frame[1:4] != result[1:4]:
            print util.hexprint(result)
            raise errors.RadioError("Invalid response for address 0x%04x" % i)
        radio.pipe.write("\x06")
        ecks = radio.pipe.read(1)
        if ecks != "x":
            raise errors.RadioError("Unexpected response")
        data += result[4:]
        do_status(radio, "from", i)

    return memmap.MemoryMap(data)

def do_upload(radio):
    do_ident(radio)
    data = radio._mmap[0x0030:]

    for i in range(0, 0x1000, 16):
        frame = struct.pack(">cHB", "W", i, 16)
        frame += data[i:i + 16]
        radio.pipe.write(frame)
        ack = radio.pipe.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio NAK'd block at address 0x%04x" % i)
        do_status(radio, "to", i)

DUPLEX = ["", "-", "+"]
CHARSET = "0123456789- ABCDEFGHIJKLMNOPQRSTUVWXYZ_+*"
SPECIALS = {
    "VFO1": -2,
    "VFO2": -1,
    }

@directory.register
class BaofengUVB5(chirp_common.CloneModeRadio):
    """Baofeng UV-B5"""
    VENDOR = "Baofeng"
    MODEL = "UV-B5"
    BAUD_RATE = 9600

    _memsize = 0x1000

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_duplexes = DUPLEX
        rf.valid_skips = ["", "S"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 5
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 520000000)]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_special_chans = SPECIALS.keys()
        rf.has_ctone = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.memory_bounds = (1, 128)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.channels[number - 1])

    def _decode_tone(self, value, flag):
        if value > 50:
            mode = 'DTCS'
            val = chirp_common.DTCS_CODES[value - 51]
            pol = flag and 'R' or 'N'
        elif value:
            mode = 'Tone'
            val = chirp_common.TONES[value - 1]
            pol = None
        else:
            mode = val = pol = None

        return mode, val, pol

    def _encode_tone(self, _mem, which, mode, val, pol):
        def _set(field, value):
            setattr(_mem, "%s%s" % (which, field), value)

        _set("pol", 0)
        if mode == "Tone":
            _set("tone", chirp_common.TONES.index(val) + 1)
        elif mode == "DTCS":
            _set("tone", chirp_common.DTCS_CODES.index(val) + 51)
            _set("pol", pol == "R")
        else:
            _set("tone", 0)

    def _get_memobjs(self, number):
        if isinstance(number, str):
            return (getattr(self._memobj, number.lower()), None)
        elif number < 0:
            for k, v in SPECIALS.items():
                if number == v:
                    return (getattr(self._memobj, k.lower()), None)
        else:
            return (self._memobj.channels[number - 1],
                    self._memobj.names[number - 1].name)

    def get_memory(self, number):
        _mem, _nam = self._get_memobjs(number)
        mem = chirp_common.Memory()
        if isinstance(number, str):
            mem.number = SPECIALS[number]
            mem.extd_number = number
        else:
            mem.number = number

        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 10

        chirp_common.split_tone_decode(
            mem,
            self._decode_tone(_mem.txtone, _mem.txpol),
            self._decode_tone(_mem.rxtone, _mem.rxpol))

        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = _mem.isnarrow and "NFM" or "FM"
        mem.skip = "" if _mem.scanadd else "S"

        if _nam:
            for char in _nam:
                try:
                    mem.name += CHARSET[char]
                except IndexError:
                    break
            mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem, _nam = self._get_memobjs(mem.number)

        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 10

        tx, rx = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem, 'tx', *tx)
        self._encode_tone(_mem, 'rx', *rx)

        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.isnarrow = mem.mode == "NFM"
        _mem.scanadd = mem.skip == ""

        if _nam:
            for i in range(0, 5):
                try:
                    _nam[i] = CHARSET.index(mem.name[i])
                except IndexError:
                    _nam[i] = 0xFF

    @classmethod
    def match_model(cls, filedata, filename):
        return (filedata.startswith("KT511 Radio Program data") and
                len(filedata) == (cls._memsize + 0x30))
