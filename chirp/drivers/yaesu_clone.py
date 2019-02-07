# Copyright 2010 Dan Smith <dsmith@danplanet.com>
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
from textwrap import dedent

from chirp import chirp_common, util, memmap, errors

LOG = logging.getLogger(__name__)

CMD_ACK = 0x06


def _safe_read(pipe, count):
    buf = ""
    first = True
    for _i in range(0, 60):
        buf += pipe.read(count - len(buf))
        # LOG.debug("safe_read: %i/%i\n" % (len(buf), count))
        if buf:
            if first and buf[0] == chr(CMD_ACK):
                # LOG.debug("Chewed an ack")
                buf = buf[1:]  # Chew an echo'd ack if using a 2-pin cable
            first = False
        if len(buf) == count:
            break
    LOG.debug(util.hexprint(buf))
    return buf


def _chunk_read(pipe, count, status_fn):
    timer = time.time()
    block = 32
    data = ""
    while len(data) < count:
        # Don't read past the end of our block if we're not on a 32-byte
        # boundary
        chunk_size = min(block, count - len(data))
        chunk = pipe.read(chunk_size)
        if chunk:
            timer = time.time()
            data += chunk
            if data[0] == chr(CMD_ACK):
                data = data[1:]  # Chew an echo'd ack if using a 2-pin cable
        # LOG.debug("Chewed an ack")
        if time.time() - timer > 2:
            # It's been two seconds since we last saw data from the radio,
            # so it's time to give up.
            raise errors.RadioError("Timed out reading from radio")
        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        status.max = count
        status.cur = len(data)
        status_fn(status)
        LOG.debug("Read %i/%i" % (len(data), count))
    return data


def __clone_in(radio):
    pipe = radio.pipe

    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.max = radio.get_memsize()

    start = time.time()

    data = ""
    blocks = 0
    for block in radio._block_lengths:
        blocks += 1
        if blocks == len(radio._block_lengths):
            chunk = _chunk_read(pipe, block, radio.status_fn)
        else:
            chunk = _safe_read(pipe, block)
            pipe.write(chr(CMD_ACK))
        if not chunk:
            raise errors.RadioError("No response from radio")
        if radio.status_fn:
            status.cur = len(data)
            radio.status_fn(status)
        data += chunk

    if len(data) != radio.get_memsize():
        raise errors.RadioError("Received incomplete image from radio")

    LOG.debug("Clone completed in %i seconds" % (time.time() - start))

    return memmap.MemoryMap(data)


def _clone_in(radio):
    try:
        return __clone_in(radio)
    except Exception as e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


def _chunk_write(pipe, data, status_fn, block):
    delay = 0.03
    count = 0
    for i in range(0, len(data), block):
        chunk = data[i:i+block]
        pipe.write(chunk)
        count += len(chunk)
        LOG.debug("@_chunk_write, count: %i, blocksize: %i" % (count, block))
        time.sleep(delay)

        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        status.max = len(data)
        status.cur = count
        status_fn(status)


def __clone_out(radio):
    pipe = radio.pipe
    block_lengths = radio._block_lengths
    total_written = 0

    def _status():
        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        status.max = block_lengths[0] + block_lengths[1] + block_lengths[2]
        status.cur = total_written
        radio.status_fn(status)

    start = time.time()

    blocks = 0
    pos = 0
    for block in radio._block_lengths:
        blocks += 1
        if blocks != len(radio._block_lengths):
            LOG.debug("Sending %i-%i" % (pos, pos+block))
            pipe.write(radio.get_mmap()[pos:pos+block])
            buf = pipe.read(1)
            if buf and buf[0] != chr(CMD_ACK):
                buf = pipe.read(block)
            if not buf or buf[-1] != chr(CMD_ACK):
                raise Exception("Radio did not ack block %i" % blocks)
        else:
            _chunk_write(pipe, radio.get_mmap()[pos:],
                         radio.status_fn, radio._block_size)
        pos += block

    pipe.read(pos)  # Chew the echo if using a 2-pin cable

    LOG.debug("Clone completed in %i seconds" % (time.time() - start))


def _clone_out(radio):
    try:
        return __clone_out(radio)
    except Exception as e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


class YaesuChecksum:
    """A Yaesu Checksum Object"""
    def __init__(self, start, stop, address=None):
        self._start = start
        self._stop = stop
        if address:
            self._address = address
        else:
            self._address = stop + 1

    def get_existing(self, mmap):
        """Return the existing checksum in mmap"""
        return ord(mmap[self._address])

    def get_calculated(self, mmap):
        """Return the calculated value of the checksum"""
        cs = 0
        for i in range(self._start, self._stop+1):
            cs += ord(mmap[i])
        return cs % 256

    def update(self, mmap):
        """Update the checksum with the data in @mmap"""
        mmap[self._address] = self.get_calculated(mmap)

    def __str__(self):
        return "%04X-%04X (@%04X)" % (self._start,
                                      self._stop,
                                      self._address)


class YaesuCloneModeRadio(chirp_common.CloneModeRadio):
    """Base class for all Yaesu clone-mode radios"""
    _block_lengths = [8, 65536]
    _block_size = 8

    VENDOR = "Yaesu"
    _model = "ABCDE"

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect data cable.
            3. Prepare radio for clone.
            4. <b>After clicking OK</b>, press the key to send image."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect data cable.
            3. Prepare radio for clone.
            4. Press the key to receive the image."""))
        return rp

    def _checksums(self):
        """Return a list of checksum objects that need to be calculated"""
        return []

    def update_checksums(self):
        """Update the radio's checksums from the current memory map"""
        for checksum in self._checksums():
            checksum.update(self._mmap)

    def check_checksums(self):
        """Validate the checksums stored in the memory map"""
        for checksum in self._checksums():
            if checksum.get_existing(self._mmap) != \
                    checksum.get_calculated(self._mmap):
                raise errors.RadioError("Checksum Failed [%s]" % checksum)
            LOG.debug("Checksum %s: OK" % checksum)

    def sync_in(self):
        self._mmap = _clone_in(self)
        self.check_checksums()
        self.process_mmap()

    def sync_out(self):
        self.update_checksums()
        _clone_out(self)

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata[:5] == cls._model and len(filedata) == cls._memsize

    def _wipe_memory_banks(self, mem):
        """Remove @mem from all the banks it is currently in"""
        bm = self.get_bank_model()
        for bank in bm.get_memory_mappings(mem):
            bm.remove_memory_from_mapping(mem, bank)
