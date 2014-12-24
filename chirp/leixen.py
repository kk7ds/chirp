# Copyright 2014 Tom Hayward <tom@tomh.us>
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

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise

MEM_FORMAT = """
struct channel {
  bbcd rx_freq[4];
  bbcd tx_freq[4];
  u8 rx_tone;
  u8 rx_tmode;
  u8 tx_tone;
  u8 tx_tmode;
  u8 unknown5;
  u8 pttidoff:1,
     dtmfoff:1,
     unknown6:1,
     tailcut:1,
     aliasop:1,
     talkaroundoff:1,
     voxoff:1,
     skip:1;
  u8 power:1,
     mode:1
     reverseoff:1,
     blckoff:1,
     unknown7:4;
  u8 unknown8;    
};

struct name {
    char name[7];
    u8 pad;
};

#seekto 0x0d00;
struct channel default[3];
struct channel memory[199];

#seekto 0x19b0;
struct name defaultname[3];
struct name name[199];
"""


POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=4),
                chirp_common.PowerLevel("High", watts=10)]
MODES = ["NFM", "FM"]
WTFTONES = map(float, xrange(56, 64))
TONES = WTFTONES + chirp_common.TONES
DTCS_CODES = [17, 50, 645] + chirp_common.DTCS_CODES
DTCS_CODES.sort()
TMODES = ["", "Tone", "DTCS", "DTCS"]


def checksum(frame):
    x = 0
    for b in frame:
        x ^= ord(b)
    return chr(x)

def make_frame(cmd, addr, data=""):
    payload = struct.pack(">H", addr) + data
    header = struct.pack(">BB", ord(cmd), len(payload))
    frame = header + payload
    return frame + checksum(frame)

def send(radio, frame):
    # print "%04i P>R: %s" % (len(frame), util.hexprint(frame).replace("\n", "\n          "))
    try:
        radio.pipe.write(frame)
    except Exception, e:
        raise errors.RadioError("Failed to communicate with radio: %s" % e)

def recv(radio, readdata=True):
    hdr = radio.pipe.read(4)
    # print "%04i P<R: %s" % (len(hdr), util.hexprint(hdr).replace("\n", "\n          "))
    if hdr == "\x09\x00\x09":
        raise errors.RadioError("Radio rejected command.")
    cmd, length, addr = struct.unpack(">BBH", hdr)
    length -= 2
    if readdata:
        data = radio.pipe.read(length)
        # print "     P<R: %s" % util.hexprint(hdr + data).replace("\n", "\n          ")
        if len(data) != length:
            raise errors.RadioError("Radio sent %i bytes (expected %i)" % (
                    len(data), length))
        chk = radio.pipe.read(1)
    else:
        data = ""
    return addr, data

def do_ident(radio):
    send(radio, "\x02\x06LEIXEN\x17")
    ident = radio.pipe.read(9)
    print "     P<R: %s" % util.hexprint(ident).replace("\n", "\n          ")
    if ident != "\x06\x06leixen\x13":
        raise errors.RadioError("Radio refused program mode")
    radio.pipe.write("\x06\x00\x06")
    ack = radio.pipe.read(3)
    if ack != "\x06\x00\x06":
        raise errors.RadioError("Radio did not ack.")

def do_download(radio):
    do_ident(radio)

    data = ""
    data += "\xFF" * (0 - len(data))
    for addr in range(0, radio._memsize, 0x10):
        send(radio, make_frame("R", addr, chr(0x10)))
        _addr, _data = recv(radio)
        if _addr != addr:
            raise errors.RadioError("Radio sent unexpected address")
        data += _data

        status = chirp_common.Status()
        status.cur = addr
        status.max = radio._memsize
        status.msg = "Cloning from radio"
        radio.status_fn(status)

    finish(radio)

    return memmap.MemoryMap(data)

def do_upload(radio):
    do_ident(radio)

    for start, end in radio._ranges:
        for addr in range(start, end, 0x10):
            frame = make_frame("W", addr, radio._mmap[addr:addr + 0x10])
            send(radio, frame)
            # print "     P<R: %s" % util.hexprint(frame).replace("\n", "\n          ")
            radio.pipe.write("\x06\x00\x06")
            ack = radio.pipe.read(3)
            if ack != "\x06\x00\x06":
                raise errors.RadioError("Radio refused block at %04x" % addr)

            status = chirp_common.Status()
            status.cur = addr
            status.max = radio._memsize
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    finish(radio)

def finish(radio):
    send(radio, "\x64\x01\x6F\x0A")
    ack = radio.pipe.read(8)


@directory.register
class LeixenVV898Radio(chirp_common.CloneModeRadio):
    """Leixen VV-898"""
    VENDOR = "Leixen"
    MODEL = "VV-898"
    BAUD_RATE = 9600

    _file_ident = "LX-\x89\x85\x63"
    _memsize = 0x2000
    _ranges = [
        (0x0000, 0x013f),
        (0x0148, 0x016f),
        (0x0184, 0x018f),
        (0x0190, 0x01cf),
        (0x0900, 0x090f),
        (0x0920, 0x0927),
        (0x0d00, 0x2000),
    ]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_rx_dtcs = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_modes = MODES
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 7
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_skips = ["", "S"]
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 470000000)]
        rf.memory_bounds = (1, 199)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except Exception, e:
            finish(self)
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            finish(self)
            raise
        except Exception, e:
            raise errors.RadioError("Failed to upload to radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.name[number - 1]) + \
               repr(self._memobj.memory[number - 1])

    def _get_tone(self, mem, _mem):
        rx_tone = tx_tone = None

        tx_tmode = TMODES[_mem.tx_tmode]
        rx_tmode = TMODES[_mem.rx_tmode]
        
        if tx_tmode == "Tone":
            tx_tone = TONES[_mem.tx_tone - 1]
        elif tx_tmode == "DTCS":
            tx_tone = DTCS_CODES[_mem.tx_tone - 1]

        if rx_tmode == "Tone":
            rx_tone = TONES[_mem.rx_tone - 1]
        elif rx_tmode == "DTCS":
            rx_tone = DTCS_CODES[_mem.rx_tone - 1]

        tx_pol = _mem.tx_tmode == 0x03 and "R" or "N"
        rx_pol = _mem.rx_tmode == 0x03 and "R" or "N"

        chirp_common.split_tone_decode(mem, (tx_tmode, tx_tone, tx_pol),
                                            (rx_tmode, rx_tone, rx_pol))

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.tx_freq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _name = self._memobj.name[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:4] == "\xFF\xFF\xFF\xFF":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        if self._is_txinh(_mem):
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rx_freq) == int(_mem.tx_freq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rx_freq) * 10 - int(_mem.tx_freq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.tx_freq) * 10
        else:
            mem.duplex = int(_mem.rx_freq) > int(_mem.tx_freq) and "-" or "+"
            mem.offset = abs(int(_mem.rx_freq) - int(_mem.tx_freq)) * 10

        mem.name = str(_name.name).rstrip()

        self._get_tone(mem, _mem)
        mem.mode = MODES[_mem.mode]
        mem.power = POWER_LEVELS[_mem.power]
        mem.skip = _mem.skip and "S" or ""

        return mem

    def _set_tone(self, mem, _mem):
        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.tx_tmode = TMODES.index(txmode)
        _mem.rx_tmode = TMODES.index(rxmode)
        if txmode == "Tone":
            _mem.tx_tone = TONES.index(txtone) + 1
        elif txmode == "DTCS":
            _mem.tx_tmode = txpol == "R" and 0x03 or 0x02
            _mem.tx_tone = DTCS_CODES.index(txtone) + 1
        if rxmode == "Tone":
            _mem.rx_tone = TONES.index(rxtone) + 1
        elif rxmode == "DTCS":
            _mem.rx_tmode = rxpol == "R" and 0x03 or 0x02
            _mem.rx_tone = DTCS_CODES.index(rxtone) + 1

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _name = self._memobj.name[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            return
        elif _mem.get_raw() == ("\xFF" * 16):
            _mem.set_raw("\xFF" * 8 + "\xFF\x00\xFF\x00\xFF\xFE\xF0\xFC")

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

        self._set_tone(mem, _mem)

        _mem.power = mem.power and POWER_LEVELS.index(mem.power) or 0
        _mem.mode = MODES.index(mem.mode)
        _mem.skip = mem.skip == "S"
        _name.name = mem.name.ljust(7)

    @classmethod
    def match_model(cls, filedata, filename):
        if filedata[0x170:0x176] == cls._file_ident:
            return True
        elif filedata[0x900:0x906] == cls.MODEL:
            return True
        return False


@directory.register
class JetstreamJT270MRadio(LeixenVV898Radio):
    """Jetstream JT270M"""
    VENDOR = "Jetstream"
    MODEL = "JT270M"

    _file_ident = "LX-\x89\x85\x53"
