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

import struct
import logging

from chirp import chirp_common, util, errors, bitwise
from chirp.memmap import MemoryMapBytes

LOG = logging.getLogger(__name__)

TUNING_STEPS = [
    5.0, 6.25, 8.33,  9.0, 10.0, 12.5, 15, 20, 25, 30, 50, 100, 125, 200
    ]

MODES = ["FM", "NFM", "WFM", "AM", "DV"]
DUPLEX = ["", "-", "+"]
TMODES = ["", "Tone", "TSQL", "TSQL", "DTCS", "DTCS"]
DTCS_POL = ["NN", "NR", "RN", "RR"]

MEM_LEN = 34
DV_MEM_LEN = 60


# Dirty hack until I clean up this IC9x mess
class IC9xMemory(chirp_common.Memory):
    """A dirty hack to stash bank information in a memory"""
    _bank = None
    _bank_index = 0

    def __init__(self):
        chirp_common.Memory.__init__(self)


class IC9xDVMemory(chirp_common.DVMemory):
    """See above dirty hack"""
    _bank = None
    _bank_index = 0

    def __init__(self):
        chirp_common.DVMemory.__init__(self)


def _ic9x_parse_frames(buf):
    frames = []

    while b"\xfe\xfe" in buf:
        try:
            start = buf.index(b"\xfe\xfe")
            end = buf[start:].index(b"\xfd") + start + 1
        except Exception:
            LOG.error("No trailing bit")
            break

        framedata = buf[start:end]
        buf = buf[end:]

        try:
            frame = IC92Frame()
            frame.from_raw(framedata[2:-1])
            frames.append(frame)
        except errors.InvalidDataError as e:
            LOG.error("Broken frame: %s" % e)

        # LOG.debug("Parsed %i frames" % len(frames))

    return frames


def ic9x_recv(pipe):
    data = b""
    while b'\xfd' not in data:
        buf = pipe.read(1)
        if not buf:
            break

        data += buf

    return _ic9x_parse_frames(data)


def ic9x_send(pipe, buf):
    """Send @buf to @pipe, wrapped in a header and trailer.  Attempt to read
    any response frames, which are returned as a list"""

    # Add header and trailer
    realbuf = b"\xfe\xfe" + buf + b"\xfd"

    # LOG.debug("Sending:\n%s" % util.hexprint(realbuf))

    pipe.write(realbuf)
    pipe.flush()
    return ic9x_recv(pipe)


class IC92Frame:
    """IC9x frame base class"""
    def get_vfo(self):
        """Return the vfo number"""
        return ord(self._map[0])

    def set_vfo(self, vfo):
        """Set the vfo number"""
        self._map[0] = vfo

    def from_raw(self, data):
        """Construct the frame from raw data"""
        self._map = MemoryMapBytes(data)

    def from_frame(self, frame):
        """Construct the frame by copying another frame"""
        self._map = MemoryMapBytes(frame.get_raw())

    def __init__(self, subcmd=0, flen=0, cmd=0x1A):
        self._map = MemoryMapBytes(b"\x00" * (4 + flen))
        self._map[0] = b"\x01\x80" + bytes([cmd, subcmd])

    def get_payload(self):
        """Return the entire payload (sans header)"""
        return MemoryMapBytes(self._map[4:])

    def get_raw(self):
        """Return the raw version of the frame"""
        return self._map.get_byte_compatible().get_packed()

    def __str__(self):
        string = "Frame VFO=%i (len = %i)\n" % (self.get_vfo(),
                                                len(self.get_payload()))
        string += util.hexprint(self.get_payload())
        string += "\n"

        return string

    def send(self, pipe, verbose=False):
        """Send the frame to the radio via @pipe"""
        if verbose:
            LOG.debug("Sending:\n%s" % util.hexprint(self.get_raw()))

        response = ic9x_send(pipe, self.get_raw())
        while (response and len(response[0].get_raw()) > 4 and
               response[0].get_raw()[4] != self.get_raw()[4]):
            LOG.warning('Skipping unexpected frame:\n%s',
                        util.hexprint(response[0].get_raw()))
            response = ic9x_recv(pipe)

        if not response:
            raise errors.InvalidDataError("No response from radio")

        return response[0]

    def __setitem__(self, start, value):
        self._map[start+4] = value

    def __getitem__(self, index):
        return self.get_payload()[index]

    def __getslice__(self, start, end):
        return self._map[start+4:end+4]


class IC92GetBankFrame(IC92Frame):
    """A frame for requesting bank information"""
    def __init__(self):
        IC92Frame.__init__(self, 0x09)

    def send(self, pipe, verbose=False):
        rframes = ic9x_send(pipe, self.get_raw())

        if len(rframes) == 0:
            raise errors.InvalidDataError("No response from radio")

        return rframes


class IC92BankFrame(IC92Frame):
    """A frame for bank information"""
    def __init__(self):
        # 1 byte for identifier
        # 8 bytes for name
        IC92Frame.__init__(self, 0x0B, 9)

    def get_name(self):
        """Return the bank name"""
        return self[1:]

    def get_identifier(self):
        """Return the letter for the bank (A-Z)"""
        return self[0]

    def set_name(self, name):
        """Set the bank name"""
        self[1] = name[:8].ljust(8)

    def set_identifier(self, ident):
        """Set the letter for the bank (A-Z)"""
        self[0] = ident[0]


class IC92MemClearFrame(IC92Frame):
    """A frame for clearing (erasing) a memory"""
    def __init__(self, loc):
        # 2 bytes for location
        # 1 byte for 0xFF
        IC92Frame.__init__(self, 0x00, 4)

        self[0] = struct.pack(">BHB", 1, int("%i" % loc, 16), 0xFF)


class IC92MemGetFrame(IC92Frame):
    """A frame for requesting a memory"""
    def __init__(self, loc, iscall=False):
        # 2 bytes for location
        IC92Frame.__init__(self, 0x00, 3)

        if iscall:
            call = 2
        else:
            call = 1

        self[0] = struct.pack(">BH", call, int("%i" % loc, 16))


class IC92GetCallsignFrame(IC92Frame):
    """A frame for getting callsign information"""
    def __init__(self, calltype, number):
        IC92Frame.__init__(self, calltype, 1, 0x1D)

        self[0] = chr(number)


class IC92CallsignFrame(IC92Frame):
    """A frame to communicate callsign information"""
    command = 0  # Invalid
    width = 8

    def __init__(self, number=0, callsign=""):
        # 1 byte for index
        # $width bytes for callsign
        IC92Frame.__init__(self, self.command, self.width+1, 0x1D)

        self[0] = chr(number) + callsign[:self.width].ljust(self.width)

    def get_callsign(self):
        """Return the actual callsign"""
        return self[1:self.width+1].rstrip()


class IC92YourCallsignFrame(IC92CallsignFrame):
    """URCALL frame"""
    command = 6  # Your


class IC92RepeaterCallsignFrame(IC92CallsignFrame):
    """RPTCALL frame"""
    command = 7  # Repeater


class IC92MyCallsignFrame(IC92CallsignFrame):
    """MYCALL frame"""
    command = 8  # My
    width = 12  # 4 bytes for /STID


MEMORY_FRAME_FORMAT = """
struct {
  u8 vfo;
  bbcd number[2];
  lbcd freq[5];
  lbcd offset[4];
  u8 unknown8;
  bbcd rtone[2];
  bbcd ctone[2];
  bbcd dtcs[2];
  u8 unknown9[2];
  u8 unknown2:1,
     mode:3,
     tuning_step:4;
  u8 unknown1:3,
     tmode: 3,
     duplex: 2;
  u8 unknown5:4,
     dtcs_polarity:2,
     pskip:1,
     skip:1;
  char bank;
  bbcd bank_index[1];
  char name[8];
  u8 unknown10;
  u8 digital_code;
  char rpt2call[8];
  char rpt1call[8];
  char urcall[8];
} mem[1];
"""


class IC92MemoryFrame(IC92Frame):
    """A frame for communicating memory information"""
    def __init__(self):
        IC92Frame.__init__(self, 0, DV_MEM_LEN)

        # For good measure, here is a whole, valid memory block
        # at 146.010 FM.  Since the 9x will complain if any bits
        # are invalid, it's easiest to start with a known-good one
        # since we don't set everything.
        self[0] = \
            b"\x01\x00\x03\x00\x00\x01\x46\x01" + \
            b"\x00\x00\x60\x00\x00\x08\x85\x08" + \
            b"\x85\x00\x23\x22\x80\x06\x00\x00" + \
            b"\x00\x00\x20\x20\x20\x20\x20\x20" + \
            b"\x20\x20\x00\x00\x20\x20\x20\x20" + \
            b"\x20\x20\x20\x20\x4b\x44\x37\x52" + \
            b"\x45\x58\x20\x43\x43\x51\x43\x51" + \
            b"\x43\x51\x20\x20"

    def set_vfo(self, vfo):
        IC92Frame.set_vfo(self, vfo)
        if vfo == 1:
            self._map.truncate(MEM_LEN + 4)

    def set_iscall(self, iscall):
        """This frame refers to a call channel if @iscall is True"""
        if iscall:
            self[0] = 2
        else:
            self[0] = 1

    def get_iscall(self):
        """Return True if this frame refers to a call channel"""
        return ord(self[0]) == 2

    def set_memory(self, mem):
        """Take Memory object @mem and configure the frame accordingly"""
        if mem.number < 0:
            self.set_iscall(True)
            mem.number = abs(mem.number) - 1
            LOG.debug("Memory is %i (call %s)" %
                      (mem.number, self.get_iscall()))

        _mem = bitwise.parse(MEMORY_FRAME_FORMAT, self).mem

        _mem.number = mem.number

        _mem.freq = mem.freq
        _mem.offset = mem.offset
        _mem.rtone = int(mem.rtone * 10)
        _mem.ctone = int(mem.ctone * 10)
        _mem.dtcs = int(mem.dtcs)
        _mem.mode = MODES.index(mem.mode)
        _mem.tuning_step = TUNING_STEPS.index(mem.tuning_step)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.dtcs_polarity = DTCS_POL.index(mem.dtcs_polarity)

        if mem._bank is not None:
            _mem.bank = chr(ord("A") + mem._bank)
            _mem.bank_index = mem._bank_index

        _mem.skip = mem.skip == "S"
        _mem.pskip = mem.skip == "P"

        _mem.name = mem.name.ljust(8)[:8]

        if mem.mode == "DV":
            _mem.urcall = mem.dv_urcall.upper().ljust(8)[:8]
            _mem.rpt1call = mem.dv_rpt1call.upper().ljust(8)[:8]
            _mem.rpt2call = mem.dv_rpt2call.upper().ljust(8)[:8]
            _mem.digital_code = mem.dv_code

    def get_memory(self):
        """Return a Memory object based on the contents of the frame"""
        _mem = bitwise.parse(MEMORY_FRAME_FORMAT, self.get_payload()).mem

        if MODES[_mem.mode] == "DV":
            mem = IC9xDVMemory()
        else:
            mem = IC9xMemory()

        mem.number = int(_mem.number)
        if self.get_iscall():
            mem.number = -1 - mem.number

        mem.freq = int(_mem.freq)
        mem.offset = int(_mem.offset)
        mem.rtone = int(_mem.rtone) / 10.0
        mem.ctone = int(_mem.ctone) / 10.0
        mem.dtcs = int(_mem.dtcs)
        mem.mode = MODES[int(_mem.mode)]
        mem.tuning_step = TUNING_STEPS[int(_mem.tuning_step)]
        mem.duplex = DUPLEX[int(_mem.duplex)]
        mem.tmode = TMODES[int(_mem.tmode)]
        mem.dtcs_polarity = DTCS_POL[int(_mem.dtcs_polarity)]

        if int(_mem.bank) != 0:
            mem._bank = ord(str(_mem.bank)) - ord("A")
            mem._bank_index = int(_mem.bank_index)

        if _mem.skip:
            mem.skip = "S"
        elif _mem.pskip:
            mem.skip = "P"
        else:
            mem.skip = ""

        mem.name = str(_mem.name).rstrip()

        if mem.mode == "DV":
            mem.dv_urcall = str(_mem.urcall).rstrip()
            mem.dv_rpt1call = str(_mem.rpt1call).rstrip()
            mem.dv_rpt2call = str(_mem.rpt2call).rstrip()
            mem.dv_code = int(_mem.digital_code)

        return mem


def get_memory_frame(pipe, vfo, number):
    """Get the memory frame for @vfo and @number via @pipe"""
    if number < 0:
        number = abs(number + 1)
        call = True
    else:
        call = False

    frame = IC92MemGetFrame(number, call)
    frame.set_vfo(vfo)

    return frame.send(pipe)


def get_memory(pipe, vfo, number):
    """Get a memory object for @vfo and @number via @pipe"""
    rframe = get_memory_frame(pipe, vfo, number)

    if len(rframe.get_payload()) < 1:
        raise errors.InvalidMemoryLocation("No response from radio")

    if rframe.get_payload()[3] == b'\xff':
        raise errors.InvalidMemoryLocation("Radio says location is empty")

    mf = IC92MemoryFrame()
    mf.from_frame(rframe)
    if mf.get_memory().number != number:
        raise errors.RadioError('get_memory() wanted %i got %i' % (
            number, mf.get_memory().number))

    return mf.get_memory()


def set_memory(pipe, vfo, memory):
    """Set memory @memory on @vfo via @pipe"""
    frame = IC92MemoryFrame()
    frame.set_memory(memory)
    frame.set_vfo(vfo)

    # LOG.debug("Sending (%i):" % (len(frame.get_raw())))
    # LOG.debug(util.hexprint(frame.get_raw()))

    rframe = frame.send(pipe)

    if rframe.get_raw()[2] != 0xfb:
        raise errors.InvalidDataError("Radio reported error:\n%s" %
                                      util.hexprint(rframe.get_payload()))


def erase_memory(pipe, vfo, number):
    """Erase memory @number on @vfo via @pipe"""
    frame = IC92MemClearFrame(number)
    frame.set_vfo(vfo)

    rframe = frame.send(pipe)
    if rframe.get_raw()[2] != 0xfb:
        raise errors.InvalidDataError("Radio reported error")


def get_banks(pipe, vfo):
    """Get banks for @vfo via @pipe"""
    frame = IC92GetBankFrame()
    frame.set_vfo(vfo)

    rframes = frame.send(pipe)

    if vfo == 1:
        base = 180
    else:
        base = 237

    banks = []

    for i in range(base, base+26):
        bframe = IC92BankFrame()
        bframe.from_frame(rframes[i])

        banks.append(bframe.get_name().rstrip())

    return banks


def set_banks(pipe, vfo, banks):
    """Set banks for @vfo via @pipe"""
    for i in range(0, 26):
        bframe = IC92BankFrame()
        bframe.set_vfo(vfo)
        bframe.set_identifier(chr(i + ord("A")))
        bframe.set_name(banks[i])

        rframe = bframe.send(pipe)
        if rframe.get_payload() != "\xfb":
            raise errors.InvalidDataError("Radio reported error")


def get_call(pipe, cstype, number):
    """Get @cstype callsign @number via @pipe"""
    cframe = IC92GetCallsignFrame(cstype.command, number)
    cframe.set_vfo(2)
    rframe = cframe.send(pipe)

    cframe = IC92CallsignFrame()
    cframe.from_frame(rframe)

    return cframe.get_callsign()


def set_call(pipe, cstype, number, call):
    """Set @cstype @call at position @number via @pipe"""
    cframe = cstype(number, call)
    cframe.set_vfo(2)
    rframe = cframe.send(pipe)

    if rframe.get_payload() != "\xfb":
        raise errors.RadioError("Radio reported error")
