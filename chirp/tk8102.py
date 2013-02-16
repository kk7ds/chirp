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
import os

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueList

MEM_FORMAT = """
#seekto 0x0030;
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  ul16 rx_tone;
  ul16 tx_tone;
  u8 signaling:2,
     unknown1:3,
     bcl:1,
     wide:1,
     beatshift:1;
  u8 pttid:2,
     highpower:1,
     scan:1
     unknown2:4;
  u8 unknown3[2];
} memory[4];
"""

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("High", watts=50)]
MODES = ["NFM", "FM"]
PTTID = ["", "BOT", "EOT", "Both"]
SIGNAL = ["", "DTMF"]

def make_frame(cmd, addr, length, data=""):
    return struct.pack(">BHB", ord(cmd), addr, length) + data

def send(radio, frame):
    print "%04i P>R: %s" % (len(frame), util.hexprint(frame))
    radio.pipe.write(frame)

def recv(radio, readdata=True):
    hdr = radio.pipe.read(4)
    cmd, addr, length = struct.unpack(">BHB", hdr)
    if readdata:
        data = radio.pipe.read(length)
        print "     P<R: %s" % util.hexprint(hdr + data)
        if len(data) != length:
            raise errors.RadioError("Radio sent %i bytes (expected %i)" % (
                    len(data), length))
    else:
        data = ""
    radio.pipe.write("\x06")
    return addr, data

def do_ident(radio):
    send(radio, "PROGRAM")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio refused program mode")
    radio.pipe.write("\x02")
    ident = radio.pipe.read(8)
    print "Radio ident:"
    print util.hexprint(ident)
    radio.pipe.write("\x06")
    ack = radio.pipe.read(1)

def do_download(radio):
    radio.pipe.setParity("E")
    radio.pipe.setTimeout(1)
    do_ident(radio)

    data = ""
    for addr in range(0, 0x0400, 8):
        send(radio, make_frame("R", addr, 8))
        _addr, _data = recv(radio)
        if _addr != addr:
            raise errors.RadioError("Radio sent unexpected address")
        data += _data
        radio.pipe.write("\x06")
        ack = radio.pipe.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio refused block at %04x" % addr)

        status = chirp_common.Status()
        status.cur = addr
        status.max = 0x0400
        status.msg = "Cloning to radio"
        radio.status_fn(status)

    radio.pipe.write("\x45")

    data = ("\x45\x58\x33\x34\x30\x32\xff\xff" + ("\xff" * 8) +
            data)
    return memmap.MemoryMap(data)

def do_upload(radio):
    radio.pipe.setParity("E")
    radio.pipe.setTimeout(1)
    do_ident(radio)

    for addr in range(0, 0x0400, 8):
        eaddr = addr + 16
        send(radio, make_frame("W", addr, 8, radio._mmap[eaddr:eaddr + 8]))
        ack = radio.pipe.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio refused block at %04x" % addr)
        radio.pipe.write("\x06")

        status = chirp_common.Status()
        status.cur = addr
        status.max = 0x0400
        status.msg = "Cloning to radio"
        radio.status_fn(status)

    radio.pipe.write("\x45")

@directory.register
class KenwoodTK8102(chirp_common.CloneModeRadio):
    """Kenwood TK-8102"""
    VENDOR = "Kenwood"
    MODEL = "TK-8102"
    BAUD_RATE = 9600

    _memsize = 0x410

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_cross = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = False
        rf.has_rx_dtcs = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_modes = MODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = ["", "S"]
        rf.valid_bands = [(400000000, 500000000)]
        rf.memory_bounds = (1, 4)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to upload to radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol
            
        if _mem.tx_tone != 0xFFFF and _mem.tx_tone > 0x2800:
            tcode, tpol = _get_dcs(_mem.tx_tone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.tx_tone != 0xFFFF:
            mem.rtone = _mem.tx_tone / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        if _mem.rx_tone != 0xFFFF and _mem.rx_tone > 0x2800:
            rcode, rpol = _get_dcs(_mem.rx_tone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rx_tone != 0xFFFF:
            mem.ctone = _mem.rx_tone / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        if mem.tmode == "DTCS":
            mem.dtcs_polarity = "%s%s" % (tpol, rpol)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:4] == "\xFF\xFF\xFF\xFF":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        offset = (int(_mem.tx_freq) * 10) - mem.freq
        if offset < 0:
            mem.offset = abs(offset)
            mem.duplex = "-"
        elif offset > 0:
            mem.offset = offset
            mem.duplex = "+"
        else:
            mem.offset = 0

        self._get_tone(_mem, mem)
        mem.power = POWER_LEVELS[_mem.highpower]
        mem.mode = MODES[_mem.wide]
        mem.skip = not _mem.scan and "S" or ""

        mem.extra = RadioSettingGroup("all", "All Settings")

        bcl = RadioSetting("bcl", "Busy Channel Lockout",
                           RadioSettingValueBoolean(bool(_mem.bcl)))
        mem.extra.append(bcl)

        beat = RadioSetting("beatshift", "Beat Shift",
                            RadioSettingValueBoolean(bool(_mem.beatshift)))
        mem.extra.append(beat)

        pttid = RadioSetting("pttid", "PTT ID",
                             RadioSettingValueList(PTTID,
                                                   PTTID[_mem.pttid]))
        mem.extra.append(pttid)

        signal = RadioSetting("signaling", "Signaling",
                              RadioSettingValueList(SIGNAL,
                                                    SIGNAL[
                                                      _mem.signaling & 0x01]))
        mem.extra.append(signal)

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0xA000
            return val

        if mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
        elif mem.tmode == "Tone":
            tx_mode = mem.tmode
            rx_mode = None
        else:
            tx_mode = rx_mode = mem.tmode

        if tx_mode == "DTCS":
            _mem.tx_tone = mem.tmode != "DTCS" and \
                _set_dcs(mem.dtcs, mem.dtcs_polarity[0]) or \
                _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[0])
        elif tx_mode:
            _mem.tx_tone = tx_mode == "Tone" and \
                int(mem.rtone * 10) or int(mem.ctone * 10)
        else:
            _mem.tx_tone = 0xFFFF

        if rx_mode == "DTCS":
            _mem.rx_tone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
        elif rx_mode:
            _mem.rx_tone = int(mem.ctone * 10)
        else:
            _mem.rx_tone = 0xFFFF

        if os.getenv("CHIRP_DEBUG"):
            print "Set TX %s (%i) RX %s (%i)" % (tx_mode, _mem.tx_tone,
                                                 rx_mode, _mem.rx_tone)
    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            return

        _mem.unknown3[0] = 0x07
        _mem.unknown3[1] = 0x22
        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        self._set_tone(mem, _mem)
        

        _mem.highpower = mem.power == POWER_LEVELS[1]
        _mem.wide = mem.mode == "FM"
        _mem.scan = mem.skip != "S"

        for setting in mem.extra:
            print "Setting %s=%s" % (setting.get_name(), setting.value)
            if setting.get_name == "signaling":
                if setting.value == "DTMF":
                    _mem.signaling = 0x03
                else:
                    _mem.signaling = 0x00
            else:
                setattr(_mem, setting.get_name(), setting.value)
