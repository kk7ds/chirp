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

import os
import struct
import time

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueList, RadioSettingValueString

_mem_format = """
#seekto 0x0100;
struct {
  u8 even_unknown:2,
     even_pskip:1,
     even_skip:1,
     odd_unknown:2,
     odd_pskip:1,
     odd_skip:1;
} flags[379];
"""

mem_format = _mem_format + """
struct memory {
  bbcd freq[4];
  bbcd offset[4];
  u8 unknownA:4,
     tune_step:4;
  u8 rxdcsextra:1,
     txdcsextra:1,
     rxinv:1,
     txinv:1,
     channel_width:2,
     unknownB:2;
  u8 unknown8:3,
     is_am:1,
     power:2,
     duplex:2;
  u8 unknown4:4,
     rxtmode:2,
     txtmode:2;
  u8 unknown5:2,
     txtone:6;
  u8 unknown6:2,
     rxtone:6;
  u8 txcode;
  u8 rxcode;
  u8 unknown7[2];
  u8 unknown2[5];
  char name[7];
  u8 unknownZ[2];
};

#seekto 0x0030;
struct {
	char serial[16];
} serial_no;

#seekto 0x0050;
struct {
	char date[16];
} version;

#seekto 0x0280;
struct {
  u8 unknown1:6,
     display:2;
  u8 unknown[351];
  char welcome[8];
} settings;

#seekto 0x0540;
struct memory memblk1[12];

#seekto 0x2000;
struct memory memory[758];

#seekto 0x7ec0;
struct memory memblk2[10];
"""

class FlagObj(object):
    def __init__(self, flagobj, which):
        self._flagobj = flagobj
        self._which = which

    def _get(self, flag):
        return getattr(self._flagobj, "%s_%s" % (self._which, flag))

    def _set(self, flag, value):
        return setattr(self._flagobj, "%s_%s" % (self._which, flag), value)

    def get_skip(self):
        return self._get("skip")

    def set_skip(self, value):
        self._set("skip", value)

    skip = property(get_skip, set_skip)

    def get_pskip(self):
        return self._get("pskip")

    def set_pskip(self, value):
        self._set("pskip", value)

    pskip = property(get_pskip, set_pskip)

    def set(self):
        self._set("unknown", 3)
        self._set("skip", 1)
        self._set("pskip", 1)

    def clear(self):
        self._set("unknown", 0)
        self._set("skip", 0)
        self._set("pskip", 0)

    def get(self):
        return (self._get("unknown") << 2 |
                self._get("skip") << 1 |
                self._get("pskip"))

    def __repr__(self):
        return repr(self._flagobj)

def _is_loc_used(memobj, loc):
    return memobj.flags[loc / 2].get_raw() != "\xFF"

def _addr_to_loc(addr):
    return (addr - 0x2000) / 32

def _should_send_addr(memobj, addr):
    if addr < 0x2000 or addr >= 0x7EC0:
        return True
    else:
        return _is_loc_used(memobj, _addr_to_loc(addr))

def _debug(string):
    if "CHIRP_DEBUG" in os.environ or True:
        print string

def _echo_write(radio, data):
    try:
        radio.pipe.write(data)
        radio.pipe.read(len(data))
    except Exception, e:
        print "Error writing to radio: %s" % e
        raise errors.RadioError("Unable to write to radio")

def _read(radio, length):
    try:
        data = radio.pipe.read(length)
    except Exception, e:
        print "Error reading from radio: %s" % e
        raise errors.RadioError("Unable to read from radio")

    if len(data) != length:
        print "Short read from radio (%i, expected %i)" % (len(data),
                                                           length)
        print util.hexprint(data)
        raise errors.RadioError("Short read from radio")
    return data

valid_model = ['QX588UV', 'HR-2040']

def _ident(radio):
    radio.pipe.setTimeout(1)
    _echo_write(radio, "PROGRAM")
    response = radio.pipe.read(3)
    if response != "QX\x06":
        print "Response was:\n%s" % util.hexprint(response)
        raise errors.RadioError("Unsupported model")
    _echo_write(radio, "\x02")
    response = radio.pipe.read(16)
    _debug(util.hexprint(response))
    if response[1:8] not in valid_model:
        print "Response was:\n%s" % util.hexprint(response)
        raise errors.RadioError("Unsupported model")

def _finish(radio):
    endframe = "\x45\x4E\x44"
    _echo_write(radio, endframe)
    result = radio.pipe.read(1)
    if result != "\x06":
        print "Got:\n%s" % util.hexprint(result)
        raise errors.RadioError("Radio did not finish cleanly")

def _checksum(data):
    cs = 0
    for byte in data:
        cs += ord(byte)
    return cs % 256

def _send(radio, cmd, addr, length, data=None):
    frame = struct.pack(">cHb", cmd, addr, length)
    if data:
        frame += data
        frame += chr(_checksum(frame[1:]))
        frame += "\x06"
    _echo_write(radio, frame)
    _debug("Sent:\n%s" % util.hexprint(frame))
    if data:
        result = radio.pipe.read(1)
        if result != "\x06":
            print "Ack was: %s" % repr(result)
            raise errors.RadioError("Radio did not accept block at %04x" % addr)
        return
    result = _read(radio, length + 6)
    _debug("Got:\n%s" % util.hexprint(result))
    header = result[0:4]
    data = result[4:-2]
    ack = result[-1]
    if ack != "\x06":
        print "Ack was: %s" % repr(ack)
        raise errors.RadioError("Radio NAK'd block at %04x" % addr)
    _cmd, _addr, _length = struct.unpack(">cHb", header)
    if _addr != addr or _length != _length:
        print "Expected/Received:"
        print " Length: %02x/%02x" % (length, _length)
        print " Addr: %04x/%04x" % (addr, _addr)
        raise errors.RadioError("Radio send unexpected block")
    cs = _checksum(result[1:-2])
    if cs != ord(result[-2]):
        print "Calculated: %02x" % cs
        print "Actual:     %02x" % ord(result[-2])
        raise errors.RadioError("Block at 0x%04x failed checksum" % addr)
    return data

def _download(radio):
    _ident(radio)

    memobj = None

    data = ""
    for start, end in radio._ranges:
        for addr in range(start, end, 0x10):
            if memobj is not None and not _should_send_addr(memobj, addr):
                block = "\xFF" * 0x10
            else:
                block = _send(radio, 'R', addr, 0x10)
            data += block

            status = chirp_common.Status()
            status.cur = len(data)
            status.max = end
            status.msg = "Cloning from radio"
            radio.status_fn(status)

            if addr == 0x19F0:
                memobj = bitwise.parse(_mem_format, data)

    _finish(radio)

    return memmap.MemoryMap(data)

def _upload(radio):
    _ident(radio)

    for start, end in radio._ranges:
        for addr in range(start, end, 0x10):
            if addr < 0x0100:
                continue
            if not _should_send_addr(radio._memobj, addr):
                continue
            block = radio._mmap[addr:addr + 0x10]
            _send(radio, 'W', addr, len(block), block)

            status = chirp_common.Status()
            status.cur = addr
            status.max = end
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    _finish(radio)

TONES = [62.5] + list(chirp_common.TONES)
TMODES = ['', 'Tone', 'DTCS']
DUPLEXES = ['', '-', '+']
MODES = ["FM", "FM", "NFM"]
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=50),
                chirp_common.PowerLevel("Mid1", watts=25),
                chirp_common.PowerLevel("Mid2", watts=10),
                chirp_common.PowerLevel("Low", watts=5)]


@directory.register
class AnyTone5888UVRadio(chirp_common.CloneModeRadio,
                         chirp_common.ExperimentalRadio):
    """AnyTone 5888UV"""
    VENDOR = "AnyTone"
    MODEL = "5888UV"
    BAUD_RATE = 9600

    # May try to mirror the OEM behavior later
    _ranges = [
        (0x0000, 0x8000),
        ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("The Anytone driver is currently experimental. "
                           "There are no known issues with it, but you should "
                           "proceed with caution.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_rx_dtcs = True
        rf.valid_skips = ["", "S", "P"]
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->DTCS', 'DTCS->Tone',
                                '->Tone', '->DTCS', 'Tone->Tone']
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES
        rf.valid_bands = [(108000000, 500000000)]
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        rf.valid_name_length = 7
        rf.valid_power_levels = POWER_LEVELS
        rf.memory_bounds = (1, 758)
        return rf

    def sync_in(self):
        self._mmap = _download(self)
        self.process_mmap()

    def sync_out(self):
        _upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def _get_memobjs(self, number):
        number -= 1
        _mem = self._memobj.memory[number]
        _flg = FlagObj(self._memobj.flags[number / 2],
                       number % 2 and "even" or "odd")
        return _mem, _flg

    def _get_dcs_index(self, _mem, which):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        return (int(extra) << 8) | int(base)

    def _set_dcs_index(self, _mem, which, index):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        base.set_value(index & 0xFF)
        extra.set_value(index >> 8)

    def get_raw_memory(self, number):
        _mem, _flg = self._get_memobjs(number)
        return repr(_mem) + repr(_flg)

    def get_memory(self, number):
        _mem, _flg = self._get_memobjs(number)
        mem = chirp_common.Memory()
        mem.number = number

        if _flg.get() == 0x0F:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 100
        mem.offset = int(_mem.offset) * 100
        mem.name = str(_mem.name).rstrip()
        mem.duplex = DUPLEXES[_mem.duplex]
        mem.mode = _mem.is_am and "AM" or MODES[_mem.channel_width]

        rxtone = txtone = None
        rxmode = TMODES[_mem.rxtmode]
        txmode = TMODES[_mem.txtmode]
        if txmode == "Tone":
            txtone = TONES[_mem.txtone]
        elif txmode == "DTCS":
            txtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'tx')]
        if rxmode == "Tone":
            rxtone = TONES[_mem.rxtone]
        elif rxmode == "DTCS":
            rxtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'rx')]

        rxpol = _mem.rxinv and "R" or "N"
        txpol = _mem.txinv and "R" or "N"

        chirp_common.split_tone_decode(mem,
                                       (txmode, txtone, txpol),
                                       (rxmode, rxtone, rxpol))

        mem.skip = _flg.get_skip() and "S" or _flg.get_pskip() and "P" or ""
        mem.power = POWER_LEVELS[_mem.power]

        return mem

    def set_memory(self, mem):
        _mem, _flg = self._get_memobjs(mem.number)
        if mem.empty:
            _flg.set()
            return
        _flg.clear()
        _mem.set_raw("\x00" * 32)

        _mem.freq = mem.freq / 100
        _mem.offset = mem.offset / 100
        _mem.name = mem.name.ljust(7)
        _mem.is_am = mem.mode == "AM"
        _mem.duplex = DUPLEXES.index(mem.duplex)

        try:
            _mem.channel_width = MODES.index(mem.mode)
        except ValueError:
            _mem.channel_width = 0

        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.txtmode = TMODES.index(txmode)
        _mem.rxtmode = TMODES.index(rxmode)
        if txmode == "Tone":
            _mem.txtone = TONES.index(txtone)
        elif txmode == "DTCS":
            self._set_dcs_index(_mem, 'tx',
                                chirp_common.ALL_DTCS_CODES.index(txtone))
        if rxmode == "Tone":
            _mem.rxtone = TONES.index(rxtone)
        elif rxmode == "DTCS":
            self._set_dcs_index(_mem, 'rx',
                                chirp_common.ALL_DTCS_CODES.index(rxtone))

        _mem.txinv = txpol == "R"
        _mem.rxinv = rxpol == "R"

        _flg.set_skip(mem.skip == "S")
        _flg.set_pskip(mem.skip == "P")

        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

    def get_settings(self):
        _settings = self._memobj.settings
        settings = RadioSettingGroup('all', 'All Settings')

        display = ["Frequency", "Channel", "Name"]
        rs = RadioSetting("display", "Display",
                          RadioSettingValueList(display,
                                                display[_settings.display]))
        settings.append(rs)

        def filter(s):
            s_ = ""
            for i in range(0, 8):
                c = str(s[i])
                s_ += (c if c in chirp_common.CHARSET_ASCII else "")
            return s_

        rs = RadioSetting("welcome", "Welcome Message",
                          RadioSettingValueString(0, 8,
                                                  filter(_settings.welcome)))
        settings.append(rs)

        return settings

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            name = element.get_name()
            setattr(_settings, name, element.value)

# since both the AnyTone 5888UV and the Intek HR-2040 place the same ident
# (QX588UV) in the image, we need to check which of them it actually is.
# The Intek has HR-2040-XXXXXXXX (Serial No.) at offset 0x30:0x3f,
# so this may be the best method of determining the actual model.
    @classmethod
    def match_model(cls, filedata, filename):
		if filedata[0x30:0x37] == "HR-2040":
			return False
		return filedata[0x21:0x28] == "QX588UV"

@directory.register
class IntekHR2040Radio(AnyTone5888UVRadio):
    """Intek HR-2040"""
    VENDOR = "Intek"
    MODEL = "HR-2040"

    @classmethod
    def get_experimental_warning(cls):
        return "Experimental - Based on the AnyTone 5888UV code"

# Use the first part of the radio serial No. for Ident (HR-2040-XXXXXXXX) at offset 0x30:0x37
    @classmethod
    def match_model(cls, filedata, filename):
       return filedata[0x30:0x37] == "HR-2040"
