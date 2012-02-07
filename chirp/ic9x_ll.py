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

from chirp import chirp_common, util, errors
from chirp.memmap import MemoryMap

TUNING_STEPS = {
    0 : 5.0,
    1 : 6.25,
    2 : 8.33,
    3 : 9.0,
    4 : 10.0,
    5 : 12.5,
    6 : 15,
    7 : 20,
    8 : 25,
    9 : 30,
    10: 50,
    11: 100,
    12: 125,
    13: 200
    }

TUNING_STEPS_REV = {}
for __idx, __val in TUNING_STEPS.items():
    TUNING_STEPS_REV[__val] = __idx

MEM_LEN = 34
DV_MEM_LEN = 60

def _ic9x_parse_frames(buf):
    frames = []

    while "\xfe\xfe" in buf:
        try:
            start = buf.index("\xfe\xfe")
            end = buf[start:].index("\xfd") + start + 1
        except Exception, e:
            print "No trailing bit"
            break

        framedata = buf[start:end]
        buf = buf[end:]

        try:
            frame = IC92Frame()
            frame.from_raw(framedata[2:-1])
            frames.append(frame)
        except errors.InvalidDataError, e:
            print "Broken frame: %s" % e

        #print "Parsed %i frames" % len(frames)

    return frames

def ic9x_send(pipe, buf):
    """Send @buf to @pipe, wrapped in a header and trailer.  Attempt to read
    any response frames, which are returned as a list"""

    # Add header and trailer
    realbuf = "\xfe\xfe" + buf + "\xfd"

    #print "Sending:\n%s" % util.hexprint(realbuf)

    pipe.write(realbuf)
    pipe.flush()

    data = ""
    while True:
        buf = pipe.read(4096)
        if not buf:
            break

        data += buf

    return _ic9x_parse_frames(data)

class IcomFrame:
    pass

class IC92Frame(IcomFrame):
    def get_vfo(self):
        return ord(self._map[0])

    def set_vfo(self, vfo):
        self._map[0] = chr(vfo)

    def from_raw(self, data):
        self._map = MemoryMap(data)

        #self._map.printable()

    def from_frame(self, frame):
        self._map = frame._map

    def __init__(self, subcmd=0, flen=0, cmd=0x1A):
        self._map = MemoryMap("\x00" * (4 + flen))
        self._map[0] = "\x01\x80" + chr(cmd) + chr(subcmd)

    def get_payload(self):
        return self._map[4:]

    def get_raw(self):
        return self._map.get_packed()

    def __str__(self):
        string = "Frame VFO=%i (len = %i)\n" % (self.get_vfo(),
                                                len(self.get_payload()))
        string += util.hexprint(self.get_payload())
        string += "\n"

        return string

    def send(self, pipe, verbose=False):
        if verbose:
            print "Sending:\n%s" % util.hexprint(self.get_raw())

        response = ic9x_send(pipe, self.get_raw())

        if len(response) == 0:
            raise errors.InvalidDataError("No response from radio")

        return response[0]

    def __setitem__(self, start, value):
        self._map[start+4] = value

    def __getitem__(self, index):
        return self._map[index+4]

    def __getslice__(self, start, end):
        return self._map[start+4:end+4]
    
class IC92GetBankFrame(IC92Frame):
    def __init__(self):
        IC92Frame.__init__(self, 0x09)

    def send(self, pipe):
        rframes = ic9x_send(pipe, self.get_raw())

        if len(rframes) == 0:
            raise errors.InvalidDataError("No response from radio")

        return rframes

class IC92BankFrame(IC92Frame):
    def __init__(self):
        # 1 byte for identifier
        # 8 bytes for name
        IC92Frame.__init__(self, 0x0B, 9)

    def __str__(self):
        return "Bank %s: %s" % (self._data[2], self._data[3:])

    def get_name(self):
        return self[1:]

    def get_identifier(self):
        return self[0]

    def set_name(self, name):
        self[1] = name[:8].ljust(8)

    def set_identifier(self, ident):
        self[0] = ident[0]

class IC92MemClearFrame(IC92Frame):
    def __init__(self, loc):
        # 2 bytes for location
        # 1 byte for 0xFF
        IC92Frame.__init__(self, 0x00, 4)

        self[0] = struct.pack(">BHB", 1, int("%i" % loc, 16), 0xFF)

class IC92MemGetFrame(IC92Frame):
    def __init__(self, loc, call=False):
        # 2 bytes for location
        IC92Frame.__init__(self, 0x00, 3)

        if call:
            c = 2
        else:
            c = 1

        self[0] = struct.pack(">BH", c, int("%i" % loc, 16))

class IC92GetCallsignFrame(IC92Frame):
    def __init__(self, type, number):
        IC92Frame.__init__(self, type, 1, 0x1D)

        self[0] = chr(number)

class IC92CallsignFrame(IC92Frame):
    command = 0 # Invalid
    width = 8

    def __init__(self, number=0, callsign=""):
        # 1 byte for index
        # $width bytes for callsign
        IC92Frame.__init__(self, self.command, self.width+1, 0x1D)

        self[0] = chr(number) + callsign[:self.width].ljust(self.width)

    def get_callsign(self):
        return self[1:self.width+1].rstrip()

class IC92YourCallsignFrame(IC92CallsignFrame):
    command = 6 # Your

class IC92RepeaterCallsignFrame(IC92CallsignFrame):
    command = 7 # Repeater

class IC92MyCallsignFrame(IC92CallsignFrame):
    command = 8 # My
    width = 12 # 4 bytes for /STID

class IC92MemoryFrame(IC92Frame):
    def __init__(self):
        IC92Frame.__init__(self, 0, DV_MEM_LEN)

        # For good measure, here is a whole, valid memory block
        # at 146.010 FM.  Since the 9x will complain if any bits
        # are invalid, it's easiest to start with a known-good one
        # since we don't set everything.
        self[0] = \
            "\x01\x00\x03\x00\x00\x01\x46\x01" + \
            "\x00\x00\x60\x00\x00\x08\x85\x08" + \
            "\x85\x00\x23\x22\x80\x06\x00\x00" + \
            "\x00\x00\x20\x20\x20\x20\x20\x20" + \
            "\x20\x20\x00\x00\x20\x20\x20\x20" + \
            "\x20\x20\x20\x20\x4b\x44\x37\x52" + \
            "\x45\x58\x20\x43\x43\x51\x43\x51" + \
            "\x43\x51\x20\x20"

    def set_vfo(self, vfo):
        IC92Frame.set_vfo(self, vfo)
        if vfo == 1:
            self._map.truncate(MEM_LEN + 4)

    def set_iscall(self, iscall):
        if iscall:
            self[0] = 2
        else:
            self[0] = 1

    def get_iscall(self):
        return ord(self[0]) == 2

    def _encode_duptone(self, mem):
        duptone = ord(self[22]) & 0xE0

        if mem.duplex == "-":
            duptone |= duptone | 0x01
        elif mem.duplex == "+":
            duptone |= duptone | 0x02

        if mem.tmode == "Tone":
            duptone |= 0x04
        elif mem.tmode == "TSQL":
            duptone |= 0x0C
        elif mem.tmode == "DTCS":
            duptone |= 0x14

        self[22] = duptone

    def _decode_duptone(self):
        duptone = ord(self[22])

        if duptone & 0x01:
            duplex = "-"
        elif duptone & 0x02:
            duplex = "+"
        else:
            duplex = ""

        if (duptone & 0x0C) == 0x0C:
            tmode = "TSQL"
        elif (duptone & 0x14) == 0x14:
            tmode = "DTCS"
        elif (duptone & 0x04) == 0x04:
            tmode = "Tone"
        else:
            tmode = ""

        return duplex, tmode

    def _encode_mode(self, mem):
        mode = ord(self[21]) & 0x0F

        if mem.mode == "FM":
            pass
        elif mem.mode == "NFM":
            mode |= 0x10
        elif mem.mode == "WFM":
            mode |= 0x20
        elif mem.mode == "AM":
            mode |= 0x30
        elif mem.mode == "DV":
            mode |= 0x40
        else:
            raise errors.InvalidDataError("Unsupported mode %s" % mem.mode)

        self[21] = mode

    def _decode_mode(self):
        mode = ord(self[21])

        if (mode & 0x30) == 0x30:
            return "AM"
        elif (mode & 0x10) == 0x10:
            return "NFM"
        elif (mode & 0x20) == 0x20:
            return "WFM"
        elif (mode & 0x40) == 0x40:
            return "DV"
        else:
            return "FM"

    def _encode_dtcs_polarity(self, mem):
        pol = ord(self[23]) & 0xF3
        if mem.dtcs_polarity[0] == "R":
            pol |= 0x80
        if mem.dtcs_polarity[1] == "R":
            pol |= 0x40
        self[23] = pol

    def _decode_dtcs_polarity(self):
        pol = ord(self[23])

        pstr = ""
        if pol & 0x80:
            pstr += "R"
        else:
            pstr += "N"
        if pol & 0x40:
            pstr += "R"
        else:
            pstr += "N"

        return pstr

    def _encode_tuning_step(self, mem):
        ts = ord(self[21]) & 0xF0
        ts |= TUNING_STEPS_REV[mem.tuning_step]
        self[21] = ts

    def _decode_tuning_step(self):
        ts = ord(self[21]) & 0x0F
        return TUNING_STEPS[ts]

    def _encode_skip(self, mem):
        skip = ord(self[23]) & 0xFC
        if mem.skip == "S":
            skip |= 0x01
        elif mem.skip == "P":
            skip |= 0x02
        self[23] = skip

    def _decode_skip(self):
        skip = ord(self[23])

        if skip & 0x01:
            return "S"
        elif skip & 0x02:
            return "P"
        else:
            return ""

    def _encode_bank(self, mem):
        if mem.bank is None:
            self[24] = 0
        else:
            self[24] = chr(mem.bank + ord("A"))

        if mem.bank_index == -1:
            self[25] = util.bcd_encode(0)
        else:
            self[25] = util.bcd_encode(mem.bank_index)

    def _decode_bank(self):
        if ord(self[24]) == 0 or self.get_iscall():
            bank = None
            index = -1
        else:
            bank = ord(self[24]) - ord("A")
            index = int("%02x" % ord(self[25]))

        return bank, index

    def _encode_calls(self, mem):
        if isinstance(mem, chirp_common.DVMemory):
            uc = mem.dv_urcall
            r1 = mem.dv_rpt1call
            r2 = mem.dv_rpt2call
        else:
            uc = r1 = r2 = (" " * 8)

        self[36] = r2.ljust(8)
        self[44] = r1.ljust(8)
        self[52] = uc.ljust(8)

    def _decode_calls(self):
        return self[52:60].rstrip(), self[44:52].rstrip(),self[36:44].rstrip()

    def _decode_digital_code(self):
        return int("%02x" % ord(self[35]))

    def _encode_digital_code(self, mem):
        self[35] = util.bcd_encode(mem.dv_code)

    def _decode_freq(self):
        return int("%02x%02x%02x%02x%02x" % (ord(self[7]),
                                             ord(self[6]),
                                             ord(self[5]),
                                             ord(self[4]),
                                             ord(self[3])))

    def set_memory(self, mem):
        if mem.number < 0:
            self.set_iscall(True)
            mem.number = abs(mem.number) - 1
            print "Memory is %i (call %s)" % (mem.number, self.get_iscall())

        self[1] = struct.pack(">H", int("%i" % mem.number, 16))

        self[3] = util.bcd_encode(mem.freq,
                                  bigendian=False,
                                  width=10)
        self[8] = util.bcd_encode(mem.offset,
                                  bigendian=False,
                                  width=6)
        self[13] = util.bcd_encode(int(mem.rtone * 10))
        self[15] = util.bcd_encode(int(mem.ctone * 10))
        self[17] = util.bcd_encode(int(mem.dtcs), width=4)
        self._encode_mode(mem)
        self._encode_tuning_step(mem)
        self._encode_duptone(mem)
        self._encode_dtcs_polarity(mem)
        self._encode_skip(mem)
        self._encode_bank(mem)
        if mem.mode == "DV":
            self._encode_calls(mem)
            self._encode_digital_code(mem)

        self[26] = mem.name[:8].ljust(8)

    def get_memory(self):
        if self._decode_mode() == "DV":
            mem = chirp_common.DVMemory()
        else:
            mem = chirp_common.Memory()

        mem.number = int("%02x" % struct.unpack(">H", self[1:3])[0])

        if self.get_iscall():
            mem.number = -1 - mem.number

        mem.freq = self._decode_freq()
        mem.offset = float("%02x%02x%02x%02x" % (ord(self[11]), ord(self[10]),
                                                 ord(self[9]),  ord(self[8])))
        mem.rtone = int("%02x%02x" % (ord(self[13]), ord(self[14]))) / 10.0
        mem.ctone = int("%02x%02x" % (ord(self[15]), ord(self[16]))) / 10.0
        mem.dtcs = int("%02x%02x"  % (ord(self[17]), ord(self[18])))
        mem.mode = self._decode_mode()
        mem.tuning_step = self._decode_tuning_step()
        mem.duplex, mem.tmode = self._decode_duptone()
        mem.dtcs_polarity = self._decode_dtcs_polarity()
        mem.skip = self._decode_skip()
        mem.bank, mem.bank_index = self._decode_bank()

        if mem.mode == "DV":
            mem.dv_urcall, mem.dv_rpt1call, mem.dv_rpt2call = \
                self._decode_calls()
            mem.dv_code = self._decode_digital_code()

        mem.name = self[26:34].rstrip()

        return mem

def print_frames(frames):
    count = 0
    for i in frames:
        print "Frame %i:" % count
        print i
        count += 1

def _send_magic_4800(pipe):
    cmd = "\x01\x80\x19"
    magic = ("\xFE" * 25) + cmd
    for i in [0,1]:
        r = ic9x_send(pipe, magic)
        if r:
            return r[0].get_raw()[0] == "\x80"
    return r and r[0].get_raw()[:3] == rsp

def _send_magic_38400(pipe):
    cmd = "\x01\x80\x19"
    rsp = "\x80\x01\x19"
    magic = ("\xFE" * 400) + cmd
    for i in [0,1]:
        r = ic9x_send(pipe, magic)
        if r:
            return r[0].get_raw()[0] == "\x80"
    return False

def send_magic(pipe):
    if pipe.getBaudrate() == 38400:
        r = _send_magic_38400(pipe)
        if r:
            return
        print "Switching from 38400 to 4800"
        pipe.setBaudrate(4800)
        r = _send_magic_4800(pipe)
        pipe.setBaudrate(38400)
        if r:
            return
        raise errors.RadioError("Radio not responding")
    elif pipe.getBaudrate() == 4800:
        r = _send_magic_4800(pipe)
        if r:
            return
        print "Switching from 4800 to 38400"
        pipe.setBaudrate(38400)
        r = _send_magic_38400(pipe)
        if r:
            return
        pipe.setBaudrate(4800)
        raise errors.RadioError("Radio not responding")
    else:
        raise errors.InvalidDataError("Radio in unknown state (%i)" % r.getBaudrate())    

def print_banks(pipe):
    frames = send(pipe, "\x01\x80\x1a\x09") # Banks

    print "A Banks:"
    for i in range(180, 180+26):
        bf = IC92BankFrame()
        bf.from_frame(frames[i])
        print str(bf)

    print "B Banks:"
    for i in range(237, 237+26):
        bf = IC92BankFrame()
        bf.from_frame(frames[i])
        print str(bf)

def get_memory_frame(pipe, vfo, number):
    if number < 0:
        number = abs(number + 1)
        call = True
    else:
        call = False

    frame = IC92MemGetFrame(number, call)
    frame.set_vfo(vfo)

    return frame.send(pipe)

def get_memory(pipe, vfo, number):
    rframe = get_memory_frame(pipe, vfo, number)

    if len(rframe.get_payload()) < 1:
        raise errors.InvalidMemoryLocation("No response from radio")

    if rframe.get_payload()[3] == '\xff':
        raise errors.InvalidMemoryLocation("Radio says location is empty")

    mf = IC92MemoryFrame()
    mf.from_frame(rframe)

    return mf.get_memory()

def set_memory(pipe, vfo, memory):
    frame = IC92MemoryFrame()
    frame.set_memory(memory)
    frame.set_vfo(vfo)

    #print "Sending (%i):" % (len(frame.get_raw()))
    #print util.hexprint(frame.get_raw())

    rframe = frame.send(pipe)

    if rframe.get_raw()[2] != "\xfb":
        raise errors.InvalidDataError("Radio reported error:\n%s" %\
                                          util.hexprint(rframe.get_payload()))

def erase_memory(pipe, vfo, number):
    frame = IC92MemClearFrame(number)
    frame.set_vfo(vfo)

    rframe = frame.send(pipe)
    if rframe.get_raw()[2] != "\xfb":
        raise errors.InvalidDataError("Radio reported error")

def get_banks(pipe, vfo):
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

        bank = chirp_common.Bank(bframe.get_name())
        banks.append(bank)
    
    return banks

def set_banks(pipe, vfo, banks):
    for i in range(0, 26):
        bframe = IC92BankFrame()
        bframe.set_vfo(vfo)
        bframe.set_identifier(chr(i + ord("A")))
        bframe.set_name(banks[i])

        rframe = bframe.send(pipe)
        if rframe.get_payload() != "\xfb":
            raise errors.InvalidDataError("Radio reported error")

def get_call(pipe, cstype, number):
    cframe = IC92GetCallsignFrame(cstype.command, number)
    cframe.set_vfo(2)
    rframe = cframe.send(pipe)

    cframe = IC92CallsignFrame()
    cframe.from_frame(rframe)

    return cframe.get_callsign()

def set_call(pipe, cstype, number, call):
    cframe = cstype(number, call)
    cframe.set_vfo(2)
    rframe = cframe.send(pipe)

    if rframe.get_payload() != "\xfb":
        raise errors.RadioError("Radio reported error")

def print_memory(pipe, vfo, number):
    if vfo not in [1, 2]:
        raise errors.InvalidValueError("VFO must be 1 or 2")

    if number < 0 or number > 399:
        raise errors.InvalidValueError("Number must be between 0 and 399")

    mf = get_memory(pipe, vfo, number)

    print "Memory %i from VFO %i: %s" % (number, vfo, str(mf))

if __name__ == "__main__":
    print util.hexprint(util.bcd_encode(1072))
    print util.hexprint(util.bcd_encode(146900000, False))
    print util.hexprint(util.bcd_encode(25, width=4))
    print util.hexprint(util.bcd_encode(5000000, False, 6))
    print util.hexprint(util.bcd_encode(600000, False, 6))
    
