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

import logging
import struct

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueList
from chirp.settings import RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

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
     scan:1,
     unknown2:4;
  u8 unknown3[2];
} memory[8];

#seekto 0x0250;
struct {
  u8 unknown0;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  // 0x04 Emergency, 0x05 keylock, 0x06 Monitor 0x09 temp delete, 0x0A none
  u8 speakerkey;
  u8 circlekey;
} settings;

#seekto 0x0270;
struct {
  u8 scanresume; // 0=selected 1=selected+talkback
  u8 dropoutdelay; // 0.5s*value, 0.5-5.0
  u8 txdwell; // same as above
  u8 offhookscan; // 0=off 1=on
} settings2;

#seekto 0x0310;
struct {
  char line1[32];
  char line2[32];
} messages;

"""

# These are 4+index
KEYS = [
    'Emergency',
    'Key Lock',
    'Monitor',
    'Scan On/Off',
    'Talk Around',
    'Temporary Delete',
    'None',
]
SCAN_RESUME = ['Selected', 'Selected+Talkback']
SCAN_TIME = ['%.1f' % (v * 0.5) for v in range(11)]
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("High", watts=50)]
MODES = ["NFM", "FM"]
PTTID = ["", "BOT", "EOT", "Both"]
SIGNAL = ["", "DTMF"]


def make_frame(cmd, addr, length, data=b""):
    return struct.pack(">BHB", ord(cmd), addr, length) + bytes(data)


def send(radio, frame):
    # LOG.debug("%04i P>R: %s" % (len(frame), util.hexprint(frame)))
    radio.pipe.write(frame)


def recv(radio, readdata=True):
    hdr = radio.pipe.read(4)
    cmd, addr, length = struct.unpack(">BHB", hdr)
    if readdata:
        data = radio.pipe.read(length)
        # LOG.debug("     P<R: %s" % util.hexprint(hdr + data))
        if len(data) != length:
            raise errors.RadioError("Radio sent %i bytes (expected %i)" % (
                    len(data), length))
    else:
        data = bytes(b"")
    radio.pipe.write(b"\x06")
    return addr, data


def do_ident(radio):
    send(radio, b"PROGRAM")
    ack = radio.pipe.read(1)
    if ack != bytes(b"\x06"):
        LOG.debug('Response was %r, expected 0x06' % ack)
        raise errors.RadioError("Radio refused program mode")
    radio.pipe.write(b"\x02")
    ident = radio.pipe.read(8)
    try:
        modelstr = ident[1:5].decode()
    except UnicodeDecodeError:
        LOG.debug('Model string was %r' % ident)
        modelstr = '?'
    if modelstr != radio.MODEL.split("-")[1]:
        raise errors.RadioError("Incorrect model: TK-%s, expected %s" % (
                modelstr, radio.MODEL))
    LOG.info("Model: %s" % util.hexprint(ident))
    radio.pipe.write(b"\x06")
    ack = radio.pipe.read(1)


def do_download(radio):
    radio.pipe.parity = "E"
    radio.pipe.timeout = 1
    try:
        do_ident(radio)
    except errors.RadioError:
        do_ident(radio)

    data = bytes(b"")
    for addr in range(0, 0x0400, 8):
        send(radio, make_frame(bytes(b"R"), addr, 8))
        _addr, _data = recv(radio)
        if _addr != addr:
            raise errors.RadioError("Radio sent unexpected address")
        data += _data
        radio.pipe.write(b"\x06")
        ack = radio.pipe.read(1)
        if ack != bytes(b"\x06"):
            raise errors.RadioError("Radio refused block at %04x" % addr)

        status = chirp_common.Status()
        status.cur = addr
        status.max = 0x0400
        status.msg = "Cloning from radio"
        radio.status_fn(status)

    radio.pipe.write(b"\x45")

    data = (b"\x45\x58\x33\x34\x30\x32\xff\xff" + (b"\xff" * 8) +
            data)
    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    radio.pipe.parity = "E"
    radio.pipe.timeout = 1
    try:
        do_ident(radio)
    except errors.RadioError:
        do_ident(radio)

    mmap = radio._mmap.get_byte_compatible()
    for addr in range(0, 0x0400, 8):
        eaddr = addr + 16
        send(radio, make_frame(b"W", addr, 8, mmap[eaddr:eaddr + 8]))
        ack = radio.pipe.read(1)
        if ack != bytes(b"\x06"):
            raise errors.RadioError("Radio refused block at %04x" % addr)
        radio.pipe.write(b"\x06")

        status = chirp_common.Status()
        status.cur = addr
        status.max = 0x0400
        status.msg = "Cloning to radio"
        radio.status_fn(status)

    radio.pipe.write(b"\x45")


class KenwoodTKx102Radio(chirp_common.CloneModeRadio):
    """Kenwood TK-x102"""
    VENDOR = "Kenwood"
    MODEL = "TK-x102"
    BAUD_RATE = 9600

    _memsize = 0x410

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = False
        rf.has_rx_dtcs = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_modes = MODES
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = ["", "S"]
        rf.valid_bands = [self._range]
        rf.memory_bounds = (1, self._upper)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            self.pipe.write(b"\x45")
            raise
        except Exception as e:
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            self.pipe.write(b"\x45")
            raise
        except Exception as e:
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

        if _mem.get_raw(asbytes=False)[:4] == "\xFF\xFF\xFF\xFF":
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
                                                   current_index=_mem.pttid))
        mem.extra.append(pttid)

        signal = RadioSetting(
            "signaling", "Signaling",
            RadioSettingValueList(
                SIGNAL, current_index=_mem.signaling & 0x01))
        mem.extra.append(signal)

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0xA000
            return val

        rx_mode = tx_mode = None
        rx_tone = tx_tone = 0xFFFF

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            tx_tone = int(mem.rtone * 10)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rx_tone = tx_tone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                tx_tone = int(mem.rtone * 10)
            if rx_mode == "DTCS":
                rx_tone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rx_tone = int(mem.ctone * 10)

        _mem.rx_tone = rx_tone
        _mem.tx_tone = tx_tone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.tx_tone, rx_mode, _mem.rx_tone))

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
            if setting.get_name == "signaling":
                if setting.value == "DTMF":
                    _mem.signaling = 0x03
                else:
                    _mem.signaling = 0x00
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic")
        scan = RadioSettingGroup("scan", "Scan")
        top = RadioSettings(basic, scan)

        def _f(val):
            string = ""
            for char in str(val):
                if char == "\xFF":
                    break
                string += char
            return string

        line1 = RadioSetting("messages.line1", "Message Line 1",
                             RadioSettingValueString(0, 32,
                                                     _f(_mem.messages.line1),
                                                     autopad=False))
        basic.append(line1)

        line2 = RadioSetting("messages.line2", "Message Line 2",
                             RadioSettingValueString(0, 32,
                                                     _f(_mem.messages.line2),
                                                     autopad=False))
        basic.append(line2)

        skey = RadioSetting(
            "settings.speakerkey", "Speaker Key",
            RadioSettingValueList(
                KEYS, current_index=int(_mem.settings.speakerkey) - 4))
        basic.append(skey)

        ckey = RadioSetting(
            "settings.circlekey", "Circle Key",
            RadioSettingValueList(
                KEYS, current_index=int(_mem.settings.circlekey) - 4))
        basic.append(ckey)

        scanresume = RadioSetting(
            "settings2.scanresume", "Scan Resume",
            RadioSettingValueList(SCAN_RESUME,
                                  current_index=_mem.settings2.scanresume))
        scan.append(scanresume)

        offhookscan = RadioSetting(
            "settings2.offhookscan", "Off-Hook Scan",
            RadioSettingValueBoolean(bool(_mem.settings2.offhookscan)))
        scan.append(offhookscan)

        dropout = RadioSetting(
            "settings2.dropoutdelay", "Drop-out Delay Time",
            RadioSettingValueList(
                SCAN_TIME, current_index=int(_mem.settings2.dropoutdelay)))

        scan.append(dropout)

        txdwell = RadioSetting(
            "settings2.txdwell", "TX Dwell Time",
            RadioSettingValueList(
                SCAN_TIME, current_index=int(_mem.settings2.txdwell)))
        scan.append(txdwell)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if "." in element.get_name():
                bits = element.get_name().split(".")
                obj = self._memobj
                for bit in bits[:-1]:
                    obj = getattr(obj, bit)
                setting = bits[-1]
            else:
                obj = self._memobj.settings
                setting = element.get_name()

            if "line" in setting:
                value = str(element.value).ljust(32, "\xFF")
            elif 'key' in setting:
                value = int(element.value) + 4
            else:
                value = element.value
            setattr(obj, setting, value)

    @classmethod
    def match_model(cls, filedata, filename):
        model = filedata[0x03D1:0x03D5]
        return model == cls.MODEL.encode().split(b"-")[1]


@directory.register
class KenwoodTK7102Radio(KenwoodTKx102Radio):
    MODEL = "TK-7102"
    _range = (136000000, 174000000)
    _upper = 4


@directory.register
class KenwoodTK8102Radio(KenwoodTKx102Radio):
    MODEL = "TK-8102"
    _range = (400000000, 500000000)
    _upper = 4


@directory.register
class KenwoodTK7108Radio(KenwoodTKx102Radio):
    MODEL = "TK-7108"
    _range = (136000000, 174000000)
    _upper = 8


@directory.register
class KenwoodTK8108Radio(KenwoodTKx102Radio):
    MODEL = "TK-8108"
    _range = (400000000, 500000000)
    _upper = 8
