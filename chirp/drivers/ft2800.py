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

import time
import os
import logging

from chirp import util, memmap, chirp_common, bitwise, directory, errors
from yaesu_clone import YaesuCloneModeRadio

LOG = logging.getLogger(__name__)

CHUNK_SIZE = 16


def _send(s, data):
    for i in range(0, len(data), CHUNK_SIZE):
        chunk = data[i:i+CHUNK_SIZE]
        s.write(chunk)
        echo = s.read(len(chunk))
        if chunk != echo:
            raise Exception("Failed to read echo chunk")

IDBLOCK = "\x0c\x01\x41\x33\x35\x02\x00\xb8"
TRAILER = "\x0c\x02\x41\x33\x35\x00\x00\xb7"
ACK = "\x0C\x06\x00"


def _download(radio):
    data = ""
    for _i in range(0, 10):
        data = radio.pipe.read(8)
        if data == IDBLOCK:
            break

    LOG.debug("Header:\n%s" % util.hexprint(data))

    if len(data) != 8:
        raise Exception("Failed to read header")

    _send(radio.pipe, ACK)

    data = ""

    while len(data) < radio._block_sizes[1]:
        time.sleep(0.1)
        chunk = radio.pipe.read(38)
        LOG.debug("Got: %i:\n%s" % (len(chunk), util.hexprint(chunk)))
        if len(chunk) == 8:
            LOG.debug("END?")
        elif len(chunk) != 38:
            LOG.debug("Should fail?")
            break
            # raise Exception("Failed to get full data block")
        else:
            cs = 0
            for byte in chunk[:-1]:
                cs += ord(byte)
            if ord(chunk[-1]) != (cs & 0xFF):
                raise Exception("Block failed checksum!")

            data += chunk[5:-1]

        _send(radio.pipe, ACK)
        if radio.status_fn:
            status = chirp_common.Status()
            status.max = radio._block_sizes[1]
            status.cur = len(data)
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    LOG.debug("Total: %i" % len(data))

    return memmap.MemoryMap(data)


def _upload(radio):
    for _i in range(0, 10):
        data = radio.pipe.read(256)
        if not data:
            break
        LOG.debug("What is this garbage?\n%s" % util.hexprint(data))

    _send(radio.pipe, IDBLOCK)
    time.sleep(1)
    ack = radio.pipe.read(300)
    LOG.debug("Ack was (%i):\n%s" % (len(ack), util.hexprint(ack)))
    if ack != ACK:
        raise Exception("Radio did not ack ID")

    block = 0
    while block < (radio.get_memsize() / 32):
        data = "\x0C\x03\x00\x00" + chr(block)
        data += radio.get_mmap()[block*32:(block+1)*32]
        cs = 0
        for byte in data:
            cs += ord(byte)
        data += chr(cs & 0xFF)

        LOG.debug("Writing block %i:\n%s" % (block, util.hexprint(data)))

        _send(radio.pipe, data)
        time.sleep(0.1)
        ack = radio.pipe.read(3)
        if ack != ACK:
            raise Exception("Radio did not ack block %i" % block)

        if radio.status_fn:
            status = chirp_common.Status()
            status.max = radio._block_sizes[1]
            status.cur = block * 32
            status.msg = "Cloning to radio"
            radio.status_fn(status)
        block += 1

    _send(radio.pipe, TRAILER)

MEM_FORMAT = """
struct {
  bbcd freq[4];
  u8 unknown1[4];
  bbcd offset[2];
  u8 unknown2[2];
  u8 pskip:1,
     skip:1,
     unknown3:1,
     isnarrow:1,
     power:2,
     duplex:2;
  u8 unknown4:6,
     tmode:2;
  u8 tone;
  u8 dtcs;
} memory[200];

#seekto 0x0E00;
struct {
  char name[6];
} names[200];
"""

MODES = ["FM", "NFM"]
TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", ""]
POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=65),
                chirp_common.PowerLevel("Mid", watts=25),
                chirp_common.PowerLevel("Low2", watts=10),
                chirp_common.PowerLevel("Low1", watts=5),
                ]
CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + "()+-=*/???|_"


@directory.register
class FT2800Radio(YaesuCloneModeRadio):
    """Yaesu FT-2800"""
    VENDOR = "Yaesu"
    MODEL = "FT-2800M"

    _block_sizes = [8, 7680]
    _memsize = 7680

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.memory_bounds = (0, 199)

        rf.has_ctone = False
        rf.has_tuning_step = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False

        rf.valid_tuning_steps = [5.0, 10.0, 12.5, 15.0,
                                 20.0, 25.0, 50.0, 100.0]
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_bands = [(137000000, 174000000)]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = DUPLEX
        rf.valid_skips = ["", "S", "P"]
        rf.valid_name_length = 6
        rf.valid_characters = CHARSET

        return rf

    def sync_in(self):
        self.pipe.parity = "E"
        start = time.time()
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Downloaded in %.2f sec" % (time.time() - start))
        self.process_mmap()

    def sync_out(self):
        self.pipe.timeout = 1
        self.pipe.parity = "E"
        start = time.time()
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Uploaded in %.2f sec" % (time.time() - start))

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]
        mem = chirp_common.Memory()

        mem.number = number

        if _mem.get_raw()[0] == "\xFF":
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 100000
        mem.duplex = DUPLEX[_mem.duplex]
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.name = str(_nam.name).rstrip()
        mem.mode = _mem.isnarrow and "NFM" or "FM"
        mem.skip = _mem.pskip and "P" or _mem.skip and "S" or ""
        mem.power = POWER_LEVELS[_mem.power]

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _nam = self._memobj.names[mem.number]

        if mem.empty:
            _mem.set_raw("\xFF" * (_mem.size() / 8))
            return

        if _mem.get_raw()[0] == "\xFF":
            # Emtpy -> Non-empty, so initialize
            _mem.set_raw("\x00" * (_mem.size() / 8))

        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 100000
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.isnarrow = MODES.index(mem.mode)
        _mem.pskip = mem.skip == "P"
        _mem.skip = mem.skip == "S"
        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        _nam.name = mem.name.ljust(6)[:6]

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize
