# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import serial
import logging

from chirp import chirp_common, errors, util

LOG = logging.getLogger(__name__)


def parse_frames(buf):
    """Parse frames from the radio"""
    frames = []

    while b"\xfe\xfe" in buf:
        try:
            start = buf.index(b"\xfe\xfe")
            end = buf[start:].index(b"\xfd") + start + 1
        except Exception:
            LOG.error("Unable to parse frames (buffer %i)", len(buf))
            break

        frames.append(buf[start:end])
        buf = buf[end:]

    return frames


def send(pipe, buf):
    """Send data in @buf to @pipe"""
    pipe.write(b"\xfe\xfe%s\xfd" % buf)
    pipe.flush()

    data = b""
    while True:
        buf = pipe.read(4096)
        if not buf:
            break

        data += buf
        LOG.debug("Got: \n%s" % util.hexprint(buf))

    LOG.debug('Sent %i bytes, received %i', len(buf), len(data))
    return parse_frames(data)


def send_magic(pipe):
    """Send the magic wakeup call to @pipe"""
    LOG.debug('Sending magic wakeup')
    send(pipe, (b"\xfe" * 15) + b"\x01\x7f\x19")


def drain(pipe):
    """Chew up any data waiting on @pipe"""
    while True:
        buf = pipe.read(4096)
        if not buf:
            break


def set_freq(pipe, freq):
    """Set the frequency of the radio on @pipe to @freq"""
    freqbcd = util.bcd_encode(freq, bigendian=False, width=9)
    buf = b"\x01\x7f\x05" + freqbcd

    drain(pipe)
    send_magic(pipe)
    resp = send(pipe, buf)
    for frame in resp:
        if len(frame) == 6:
            if frame[4] == 251:
                return True

    raise errors.InvalidDataError("Repeater reported error")


def get_freq(pipe):
    """Get the frequency of the radio attached to @pipe"""
    buf = b"\x01\x7f\x1a\x09"

    drain(pipe)
    send_magic(pipe)
    resp = send(pipe, buf)

    for frame in resp:
        if frame[4] == 3:
            els = frame[5:10]

            freq = int("%02x%02x%02x%02x%02x" % (els[4],
                                                 els[3],
                                                 els[2],
                                                 els[1],
                                                 els[0]))
            LOG.debug("Freq: %f" % freq)
            return freq
        else:
            LOG.debug('Unhandled frame type %i', frame[4])

    raise errors.InvalidDataError("No frequency frame received")


RP_IMMUTABLE = ["number", "skip", "bank", "extd_number", "name", "rtone",
                "ctone", "dtcs", "tmode", "dtcs_polarity", "skip", "duplex",
                "offset", "mode", "tuning_step", "bank_index"]


class IDRPx000V(chirp_common.LiveRadio):
    """Icom IDRP-*"""
    BAUD_RATE = 19200
    VENDOR = "Icom"
    MODEL = "ID-2000V/4000V/2D/2V"

    _model = "0000"  # Unknown
    mem_upper_limit = 0

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_modes = ["DV"]
        rf.valid_tmodes = []
        rf.valid_characters = ""
        rf.valid_duplexes = [""]
        rf.valid_name_length = 0
        rf.valid_skips = []
        rf.valid_tuning_steps = []
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_mode = False
        rf.has_name = False
        rf.has_offset = False
        rf.has_tuning_step = False
        rf.memory_bounds = (0, 0)
        return rf

    def get_memory(self, number):
        if number != 0:
            raise errors.InvalidMemoryLocation("Repeaters have only one slot")

        mem = chirp_common.Memory()
        mem.number = 0
        mem.freq = get_freq(self.pipe)
        mem.name = "TX/RX"
        mem.mode = "DV"
        mem.offset = 0.0
        mem.immutable = RP_IMMUTABLE

        return mem

    def set_memory(self, mem):
        if mem.number != 0:
            raise errors.InvalidMemoryLocation("Repeaters have only one slot")

        set_freq(self.pipe, mem.freq)


def do_test():
    """Get the frequency of /dev/icom"""
    ser = serial.Serial(port="/dev/icom", baudrate=19200, timeout=0.5)
    # set_freq(pipe, 439.920)
    get_freq(ser)


if __name__ == "__main__":
    do_test()
