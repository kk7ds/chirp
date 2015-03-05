#
# Copyright 2012 Filippi Marco <iz3gme.marco@gmail.com>
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

"""vcommon function for wouxun (or similar) radios"""

import struct
import os
import logging
from chirp import util, chirp_common, memmap

LOG = logging.getLogger(__name__)


def wipe_memory(_mem, byte):
    """Cleanup a memory"""
    _mem.set_raw(byte * (_mem.size() / 8))


def do_download(radio, start, end, blocksize):
    """Initiate a download of @radio between @start and @end"""
    image = ""
    for i in range(start, end, blocksize):
        cmd = struct.pack(">cHb", "R", i, blocksize)
        LOG.debug(util.hexprint(cmd))
        radio.pipe.write(cmd)
        length = len(cmd) + blocksize
        resp = radio.pipe.read(length)
        if len(resp) != (len(cmd) + blocksize):
            LOG.debug(util.hexprint(resp))
            raise Exception("Failed to read full block (%i!=%i)" %
                            (len(resp), len(cmd) + blocksize))

        radio.pipe.write("\x06")
        radio.pipe.read(1)
        image += resp[4:]

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i
            status.max = end
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    return memmap.MemoryMap(image)


def do_upload(radio, start, end, blocksize):
    """Initiate an upload of @radio between @start and @end"""
    ptr = start
    for i in range(start, end, blocksize):
        cmd = struct.pack(">cHb", "W", i, blocksize)
        chunk = radio.get_mmap()[ptr:ptr+blocksize]
        ptr += blocksize
        radio.pipe.write(cmd + chunk)
        LOG.debug(util.hexprint(cmd + chunk))

        ack = radio.pipe.read(1)
        if not ack == "\x06":
            raise Exception("Radio did not ack block %i" % ptr)
        # radio.pipe.write(ack)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i
            status.max = end
            status.msg = "Cloning to radio"
            radio.status_fn(status)
