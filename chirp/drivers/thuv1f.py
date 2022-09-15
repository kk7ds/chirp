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
import logging

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings

LOG = logging.getLogger(__name__)


def uvf1_identify(radio):
    """Do identify handshake with TYT TH-UVF1"""
    radio.pipe.write("PROG333")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio did not respond")
    radio.pipe.write("\x02")
    ident = radio.pipe.read(16)
    LOG.info("Ident:\n%s" % util.hexprint(ident))
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

    radio.pipe.write("\x45")

    return memmap.MemoryMap(data)


def uvf1_upload(radio):
    """Upload to TYT TH-UVF1"""
    data = uvf1_identify(radio)

    radio.pipe.timeout = 1

    if data != radio._mmap[:16]:
        raise errors.RadioError("Unable to talk to this model")

    for i in range(0, 0x1000, 0x10):
        addr = i + 0x10
        msg = struct.pack(">BHB", ord("W"), i, 0x10)
        msg += radio._mmap[addr:addr+0x10]

        radio.pipe.write(msg)
        ack = radio.pipe.read(1)
        if ack != "\x06":
            LOG.debug(repr(ack))
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
struct mem memory[128];

#seekto 0x0840;
struct {
  u8 scans:2,
     autolk:1,
     unknown1:5;
  u8 light:2,
     unknown6:2,
     disnm:1,
     voice:1,
     beep:1,
     rxsave:1;
  u8 led:2,
     unknown5:3,
     ani:1,
     roger:1,
     dw:1;
  u8 opnmsg:2,
     unknown4:1,
     dwait:1,
     unknown9:4;
  u8 squelch;
  u8 unknown2:4,
     tot:4;
  u8 unknown3:4,
     vox_level:4;
  u8 pad[10];
  char ponmsg[6];
} settings;

#seekto 0x08D0;
struct name names[128];

"""

LED_LIST = ["Off", "On", "Auto"]
LIGHT_LIST = ["Purple", "Orange", "Blue"]
VOX_LIST = ["1", "2", "3", "4", "5", "6", "7", "8"]
TOT_LIST = ["Off", "30s", "60s", "90s", "120s", "150s", "180s", "210s",
            "240s", "270s"]
SCANS_LIST = ["Time", "Carry", "Seek"]
OPNMSG_LIST = ["Off", "DC", "Message"]

POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5),
                chirp_common.PowerLevel("Low", watts=1),
                ]

PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
BCL_LIST = ["Off", "CSQ", "QT/DQT"]
CODES_LIST = [x for x in range(1, 9)]
STEPS = [5.0, 6.25, 7.5, 10.0, 12.5, 25.0, 37.5, 50.0, 100.0]


@directory.register
class TYTTHUVF1Radio(chirp_common.CloneModeRadio):
    """TYT TH-UVF1"""
    VENDOR = "TYT"
    MODEL = "TH-UVF1"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 128)
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_tuning_step = False
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_settings = True
        rf.can_odd_split = True
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        rf.valid_bands = [(136000000, 174000000),
                          (420000000, 470000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tuning_steps = STEPS
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
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            uvf1_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    @classmethod
    def match_model(cls, filedata, filename):
        # TYT TH-UVF1 original
        if filedata.startswith("\x13\x60\x17\x40\x40\x00\x48\x00" +
                               "\x35\x00\x39\x00\x47\x00\x52\x00"):
            return True
        # TYT TH-UVF1 V2
        elif filedata.startswith("\x14\x40\x14\x80\x43\x00\x45\x00" +
                                 "\x13\x60\x17\x40\x40\x00\x47\x00"):
            return True
        else:
            return False

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

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.tx_freq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number
        if _mem.get_raw().startswith("\xFF\xFF\xFF\xFF"):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        txfreq = int(_mem.tx_freq) * 10
        if self._is_txinh(_mem):
            mem.duplex = "off"
            mem.offset = 0
        elif txfreq == mem.freq:
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

        chirp_common.split_tone_decode(
            mem, (txmode, txval, txpol), (rxmode, rxval, rxpol))

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
                          RadioSettingValueList(
                              CODES_LIST, CODES_LIST[_mem.scramble_code]))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            return

        if _mem.get_raw() == ("\xFF" * 16):
            LOG.debug("Initializing empty memory")
            _mem.set_raw("\x00" * 16)

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.tx_freq[i].set_raw("\xFF")
        elif mem.duplex == "split":
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

    def get_settings(self):
        _settings = self._memobj.settings

        group = RadioSettingGroup("basic", "Basic")
        top = RadioSettings(group)

        group.append(
            RadioSetting("led", "LED Mode",
                         RadioSettingValueList(LED_LIST,
                                               LED_LIST[_settings.led])))
        group.append(
            RadioSetting("light", "Light Color",
                         RadioSettingValueList(LIGHT_LIST,
                                               LIGHT_LIST[_settings.light])))

        group.append(
            RadioSetting("squelch", "Squelch Level",
                         RadioSettingValueInteger(0, 9, _settings.squelch)))

        group.append(
            RadioSetting("vox_level", "VOX Level",
                         RadioSettingValueList(VOX_LIST,
                                               VOX_LIST[_settings.vox_level])))

        group.append(
            RadioSetting("beep", "Beep",
                         RadioSettingValueBoolean(_settings.beep)))

        group.append(
            RadioSetting("ani", "ANI",
                         RadioSettingValueBoolean(_settings.ani)))

        group.append(
            RadioSetting("dwait", "D.WAIT",
                         RadioSettingValueBoolean(_settings.dwait)))

        group.append(
            RadioSetting("tot", "Timeout Timer",
                         RadioSettingValueList(TOT_LIST,
                                               TOT_LIST[_settings.tot])))

        group.append(
            RadioSetting("roger", "Roger Beep",
                         RadioSettingValueBoolean(_settings.roger)))

        group.append(
            RadioSetting("dw", "Dual Watch",
                         RadioSettingValueBoolean(_settings.dw)))

        group.append(
            RadioSetting("rxsave", "RX Save",
                         RadioSettingValueBoolean(_settings.rxsave)))

        group.append(
            RadioSetting("scans", "Scans",
                         RadioSettingValueList(SCANS_LIST,
                                               SCANS_LIST[_settings.scans])))

        group.append(
            RadioSetting("autolk", "Auto Lock",
                         RadioSettingValueBoolean(_settings.autolk)))

        group.append(
            RadioSetting("voice", "Voice",
                         RadioSettingValueBoolean(_settings.voice)))

        group.append(
            RadioSetting("opnmsg", "Opening Message",
                         RadioSettingValueList(OPNMSG_LIST,
                                               OPNMSG_LIST[_settings.opnmsg])))

        group.append(
            RadioSetting("disnm", "Display Name",
                         RadioSettingValueBoolean(_settings.disnm)))

        def _filter(name):
            LOG.debug(repr(str(name)))
            return str(name).rstrip("\xFF").rstrip()

        group.append(
            RadioSetting("ponmsg", "Power-On Message",
                         RadioSettingValueString(0, 6,
                                                 _filter(_settings.ponmsg))))

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            setattr(_settings, element.get_name(), element.value)
