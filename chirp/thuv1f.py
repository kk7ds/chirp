# Copyright 2012 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise

from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueList, RadioSettingValueBoolean, \
    RadioSettingValueString

def uvf1_identify(radio):
    """Do identify handshake with TYT TH-UVF1"""
    radio.pipe.write("PROG333")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio did not respond")
    radio.pipe.write("\x02")
    ident = radio.pipe.read(16)
    print "Ident:\n%s" % util.hexprint(ident)
    radio.pipe.write("\x06")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio did not ack identification")
    return ident

def uvf1_download(radio):
    """Download from TYT TH-UVF1"""
    data = uvf1_identify(radio)

    for i in range(0, 0x1000, 0x10):
        msg = struct.pack(">BHB", ord("R"), i, 0x10)
        radio.pipe.write(msg)
        block = radio.pipe.read(0x10 + 4)
        if len(block) != (0x10 + 4):
            raise errors.RadioError("Radio sent a short block")
        radio.pipe.write("\x06")
        ack = radio.pipe.read(1)
        if ack != "\x06":
            raise errors.RadioError("Radio NAKed block")
        data += block[4:]

        status = chirp_common.Status()
        status.cur = i
        status.max = 0x1000
        status.msg = "Cloning from radio"
        radio.status_fn(status)
    return memmap.MemoryMap(data)

def uvf1_upload(radio):
    """Upload to TYT TH-UVF1"""
    data = uvf1_identify(radio)

    radio.pipe.setTimeout(1)

    if data != radio._mmap[:16]:
        raise errors.RadioError("Unable to talk to this model")

    for i in range(0, 0x1000, 0x10):
        addr = i + 0x10
        msg = struct.pack(">BHB", ord("W"), i, 0x10)
        msg += radio._mmap[addr:addr+0x10]

        radio.pipe.write(msg)
        ack = radio.pipe.read(1)
        if ack != "\x06":
            print repr(ack)
            raise errors.RadioError("Radio did not ack block %i" % i)
        status = chirp_common.Status()
        status.cur = i
        status.max = 0x1000
        status.msg = "Cloning to radio"
        radio.status_fn(status)

    # End of clone?
    radio.pipe.write("\x45")

THUV1F_MEM_FORMAT = """
struct mem {
  bbcd rx_freq[4];
  bbcd tx_freq[4];
  lbcd rx_tone[2];
  lbcd tx_tone[2];
  u8 unknown1:1,
     pttid:2, 
     unknown2:2,
     ishighpower:1,
     unknown3:2;
  u8 unknown4:4,
     isnarrow:1,
     vox:1,
     bcl:2;
  u8 unknown5:1,
     scan:1,
     unknown6:3,
     scramble_code:3;
  u8 unknown7;
};

struct name {
  char name[7];
};

#seekto 0x0020;
struct mem memory[20];

#seekto 0x08D0;
struct name names[20];

"""

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5),
                chirp_common.PowerLevel("Low", watts=1),
                ]

PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
BCL_LIST = ["Off", "CSQ", "QT/DQT"]
CODES_LIST = [x for x in range(1, 9)]

@directory.register
class TYTTHUVF1Radio(chirp_common.CloneModeRadio):
    """TYT TH-UVF1"""
    VENDOR = "TYT"
    MODEL = "TH-UVF1"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 20)
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_tuning_step = False
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        rf.valid_bands = [(136000000, 174000000),
                          (420000000, 470000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_name_length = 7
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->DTCS",
                                "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->"]
                                
        return rf

    def sync_in(self):
        try:
            self._mmap = uvf1_download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            uvf1_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata.startswith("\x13\x60\x17\x40\x40\x00\x48\x00" +
                                   "\x35\x00\x39\x00\x47\x00\x52\x00")

    def process_mmap(self):
        self._memobj = bitwise.parse(THUV1F_MEM_FORMAT, self._mmap)

    def _decode_tone(self, toneval):
        pol = "N"
        rawval = (toneval[1].get_bits(0xFF) << 8) | toneval[0].get_bits(0xFF)
                              
        if toneval[0].get_bits(0xFF) == 0xFF:
            mode = ""
            val = 0
        elif toneval[1].get_bits(0xC0) == 0xC0:
            mode = "DTCS"
            val = int("%x" % (rawval & 0x3FFF))
            pol = "R"
        elif toneval[1].get_bits(0x80):
            mode = "DTCS"
            val = int("%x" % (rawval & 0x3FFF))
        else:
            mode = "Tone"
            val = int(toneval) / 10.0

        return mode, val, pol

    def _encode_tone(self, _toneval, mode, val, pol):
        toneval = 0
        if mode == "Tone":
            toneval = int("%i" % (val * 10), 16)
        elif mode == "DTCS":
            toneval = int("%i" % val, 16)
            toneval |= 0x8000
            if pol == "R":
                toneval |= 0x4000
        else:
            toneval = 0xFFFF

        _toneval[0].set_raw(toneval & 0xFF)
        _toneval[1].set_raw((toneval >> 8) & 0xFF)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number
        if _mem.get_raw().startswith("\xFF\xFF\xFF\xFF"):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        txfreq = int(_mem.tx_freq) * 10
        if txfreq == mem.freq:
            mem.duplex = ""
        elif abs(txfreq - mem.freq) > 70000000:
            mem.duplex = "split"
            mem.offset = txfreq
        elif txfreq < mem.freq:
            mem.duplex = "-"
            mem.offset = mem.freq - txfreq
        elif txfreq > mem.freq:
            mem.duplex = "+"
            mem.offset = txfreq - mem.freq

        txmode, txval, txpol = self._decode_tone(_mem.tx_tone)
        rxmode, rxval, rxpol = self._decode_tone(_mem.rx_tone)

        chirp_common.split_tone_decode(mem,
                                      (txmode, txval, txpol),
                                      (rxmode, rxval, rxpol))

        mem.name = str(self._memobj.names[number - 1].name)
        mem.name = mem.name.replace("\xFF", " ").rstrip()

        mem.skip = not _mem.scan and "S" or ""
        mem.mode = _mem.isnarrow and "NFM" or "FM"
        mem.power = POWER_LEVELS[1 - _mem.ishighpower]

        mem.extra = RadioSettingGroup("extra", "Extra Settings")

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[_mem.pttid]))
        mem.extra.append(rs)

        rs = RadioSetting("vox", "VOX",
                          RadioSettingValueBoolean(_mem.vox))
        mem.extra.append(rs)

        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueList(BCL_LIST,
                                                BCL_LIST[_mem.bcl]))
        mem.extra.append(rs)

        rs = RadioSetting("scramble_code", "Scramble Code",
                          RadioSettingValueList(CODES_LIST,
                                                CODES_LIST[_mem.scramble_code]))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            return

        if _mem.get_raw() == ("\xFF" * 16):
            print "Initializing empty memory"
            _mem.set_raw("\x00" * 16)

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "split":
            _mem.tx_freq = mem.offset / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        (txmode, txval, txpol), (rxmode, rxval, rxpol) = \
            chirp_common.split_tone_encode(mem)

        self._encode_tone(_mem.tx_tone, txmode, txval, txpol)
        self._encode_tone(_mem.rx_tone, rxmode, rxval, rxpol)

        self._memobj.names[mem.number - 1].name = mem.name.ljust(7, "\xFF")

        _mem.scan = mem.skip == ""
        _mem.isnarrow = mem.mode == "NFM"
        _mem.ishighpower = mem.power == POWER_LEVELS[0]

        for element in mem.extra:
            setattr(_mem, element.get_name(), element.value)
