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

"""TYT uv3r radio management module"""

import os
import logging
from chirp import chirp_common, bitwise, errors, directory
from chirp.drivers.wouxun import do_download, do_upload

LOG = logging.getLogger(__name__)


def tyt_uv3r_prep(radio):
    try:
        radio.pipe.write("PROGRAMa")
        ack = radio.pipe.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio did not ACK first command")
    except:
        raise errors.RadioError("Unable to communicate with the radio")


def tyt_uv3r_download(radio):
    tyt_uv3r_prep(radio)
    return do_download(radio, 0x0000, 0x0910, 0x0010)


def tyt_uv3r_upload(radio):
    tyt_uv3r_prep(radio)
    return do_upload(radio, 0x0000, 0x0910, 0x0010)

mem_format = """
struct memory {
  ul24 duplex:2,
       bit:1,
       iswide:1,
       bits:2,
       is625:1,
       freq:17;
  ul16 offset;
  ul16 rx_tone;
  ul16 tx_tone;
  u8 unknown;
  u8 name[6];
};

#seekto 0x0010;
struct memory memory[128];

#seekto 0x0870;
u8 emptyflags[16];
u8 skipflags[16];
"""

THUV3R_DUPLEX = ["", "+", "-"]
THUV3R_CHARSET = "".join([chr(ord("0") + x) for x in range(0, 10)] +
                         [" -*+"] +
                         [chr(ord("A") + x) for x in range(0, 26)] +
                         ["_/"])


@directory.register
class TYTUV3RRadio(chirp_common.CloneModeRadio):
    VENDOR = "TYT"
    MODEL = "TH-UV3R"
    BAUD_RATE = 2400
    _memsize = 2320

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_cross = True
        rf.memory_bounds = (1, 128)
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone",
                                "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS"]
        rf.valid_skips = []
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_name_length = 6
        rf.valid_characters = THUV3R_CHARSET
        rf.valid_bands = [(136000000, 520000000)]
        rf.valid_tuning_steps = [5.0, 6.25, 10.0, 12.5, 25.0, 37.50,
                                 50.0, 100.0]
        rf.valid_skips = ["", "S"]
        return rf

    def sync_in(self):
        self.pipe.timeout = 2
        self._mmap = tyt_uv3r_download(self)
        self.process_mmap()

    def sync_out(self):
        tyt_uv3r_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _decode_tone_value(self, value):
        if value == 0xFFFF:
            return "", "N", 0
        elif value & 0x8000:
            # FIXME: rev pol
            pol = value & 0x4000 and "R" or "N"
            return "DTCS", pol, int("%x" % (value & 0x0FFF))
        else:
            return "Tone", "N", int("%x" % value) / 10.0

    def _decode_tone(self, mem, _mem):
        tx_mode, tpol, tx_tone = self._decode_tone_value(_mem.tx_tone)
        rx_mode, rpol, rx_tone = self._decode_tone_value(_mem.rx_tone)

        if rx_mode == tx_mode == "":
            return

        mem.dtcs_polarity = "%s%s" % (tpol, rpol)

        if rx_mode == tx_mode == "DTCS":
            # Break this for now until we can support this in chirp
            tx_tone = rx_tone

        if rx_mode in ["", tx_mode] and rx_tone in [0, tx_tone]:
            mem.tmode = rx_mode == "Tone" and "TSQL" or tx_mode
            if mem.tmode == "DTCS":
                mem.dtcs = tx_tone
            elif mem.tmode == "TSQL":
                mem.ctone = tx_tone
            else:
                mem.rtone = tx_tone
            return

        mem.cross_mode = "%s->%s" % (tx_mode, rx_mode)
        mem.tmode = "Cross"
        if tx_mode == "Tone":
            mem.rtone = tx_tone
        elif tx_mode == "DTCS":
            mem.dtcs = tx_tone
        if rx_mode == "Tone":
            mem.ctone = rx_tone
        elif rx_mode == "DTCS":
            mem.dtcs = rx_tone  # No support for different codes yet

    def _encode_tone(self, mem, _mem):
        if mem.tmode == "":
            _mem.tx_tone = _mem.rx_tone = 0xFFFF
            return

        def _tone(val):
            return int("%i" % (val * 10), 16)

        def _dcs(val, pol):
            polmask = pol == "R" and 0xC000 or 0x8000
            return int("%i" % (val), 16) | polmask

        rx_tone = tx_tone = 0xFFFF

        if mem.tmode == "Tone":
            rx_mode = ""
            tx_mode = "Tone"
            tx_tone = _tone(mem.rtone)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rx_tone = tx_tone = _tone(mem.ctone)
        elif mem.tmode == "DTCS":
            rx_mode = tx_mode = "DTCS"
            tx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[0])
            rx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->", 1)
            if tx_mode == "DTCS":
                tx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                tx_tone = _tone(mem.rtone)
            if rx_mode == "DTCS":
                rx_tone = _dcs(mem.dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rx_tone = _tone(mem.ctone)

        _mem.rx_tone = rx_tone
        _mem.tx_tone = tx_tone

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        bit = 1 << ((number - 1) % 8)
        byte = (number - 1) / 8

        if self._memobj.emptyflags[byte] & bit:
            mem.empty = True
            return mem

        mult = _mem.is625 and 6250 or 5000
        mem.freq = _mem.freq * mult
        mem.offset = _mem.offset * 5000
        mem.duplex = THUV3R_DUPLEX[_mem.duplex]
        mem.mode = _mem.iswide and "FM" or "NFM"
        self._decode_tone(mem, _mem)
        mem.skip = (self._memobj.skipflags[byte] & bit) and "S" or ""

        for char in _mem.name:
            try:
                c = THUV3R_CHARSET[char]
            except:
                c = ""
            mem.name += c
        mem.name = mem.name.rstrip()

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        bit = 1 << ((mem.number - 1) % 8)
        byte = (mem.number - 1) / 8

        if mem.empty:
            self._memobj.emptyflags[byte] |= bit
            _mem.set_raw("\xFF" * 16)
            return

        self._memobj.emptyflags[byte] &= ~bit

        if chirp_common.is_fractional_step(mem.freq):
            mult = 6250
            _mem.is625 = True
        else:
            mult = 5000
            _mem.is625 = False
        _mem.freq = mem.freq / mult
        _mem.offset = mem.offset / 5000
        _mem.duplex = THUV3R_DUPLEX.index(mem.duplex)
        _mem.iswide = mem.mode == "FM"
        self._encode_tone(mem, _mem)

        if mem.skip:
            self._memobj.skipflags[byte] |= bit
        else:
            self._memobj.skipflags[byte] &= ~bit

        name = []
        for char in mem.name.ljust(6):
            try:
                c = THUV3R_CHARSET.index(char)
            except:
                c = THUV3R_CHARSET.index(" ")
            name.append(c)
        _mem.name = name
        LOG.debug(repr(_mem))

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == 2320
