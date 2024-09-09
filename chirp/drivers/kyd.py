# Copyright 2014 Jim Unroe <rock.unroe@gmail.com>
# Copyright 2014 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rx_tone;
  ul16 tx_tone;
  u8 unknown1:3,
     bcl:2,       // Busy Lock
     unknown2:3;
  u8 unknown3:2,
     highpower:1, // Power Level
     wide:1,      // Bandwidth
     unknown4:4;
  u8 unknown5[2];
} memory[16];

#seekto 0x012F;
struct {
  u8 voice;       // Voice Annunciation
  u8 tot;         // Time-out Timer
  u8 totalert;    // Time-out Timer Pre-alert
  u8 unknown1[2];
  u8 squelch;     // Squelch Level
  u8 save;        // Battery Saver
  u8 beep;        // Beep
  u8 unknown2[3];
  u8 vox;         // VOX Gain
  u8 voxdelay;    // VOX Delay
} settings;

#seekto 0x017E;
u8 skipflags[2];  // SCAN_ADD
"""

CMD_ACK = "\x06"

NC630A_POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=1.00),
                       chirp_common.PowerLevel("High", watts=5.00)]

NC630A_DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

BCL_LIST = ["Off", "Carrier", "QT/DQT"]
TIMEOUTTIMER_LIST = [""] + ["%s seconds" % x for x in range(15, 615, 15)]
TOTALERT_LIST = ["", "Off"] + ["%s seconds" % x for x in range(1, 11)]
VOICE_LIST = ["Off", "Chinese", "English"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 17)]
VOXDELAY_LIST = ["0.3", "0.5", "1.0", "1.5", "2.0", "3.0"]


def _nc630a_enter_programming_mode(radio):
    serial = radio.pipe

    try:
        serial.write("PROGRAM")
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio")
    elif ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write("\x02")
        ident = serial.read(8)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ident.startswith(radio._fileid):
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _nc630a_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _nc630a_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _nc630a_enter_programming_mode(radio)

    data = ""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio._block_size):
        status.cur = addr + radio._block_size
        radio.status_fn(status)

        block = _nc630a_read_block(radio, addr, radio._block_size)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _nc630a_enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio._block_size):
            status.cur = addr + radio._block_size
            radio.status_fn(status)
            _nc630a_write_block(radio, addr, radio._block_size)


class MT700Alias(chirp_common.Alias):
    VENDOR = "Plant-Tours"
    MODEL = "MT-700"


@directory.register
class NC630aRadio(chirp_common.CloneModeRadio):
    """KYD NC-630A"""
    VENDOR = "KYD"
    MODEL = "NC-630A"
    ALIASES = [MT700Alias]
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = True

    _ranges = [
               (0x0000, 0x0330),
              ]
    _memsize = 0x03C8
    _block_size = 0x08
    _fileid = b"P32073"

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = NC630A_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]  # 12.5 kHz, 25 kHz.
        rf.memory_bounds = (1, 16)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = [(400000000, 520000000)]
        rf.valid_dtcs_codes = NC630A_DTCS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

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

        LOG.debug("Got TX %s (%i) RX %s (%i)" %
                  (txmode, _mem.tx_tone, rxmode, _mem.rx_tone))

    def get_memory(self, number):
        bitpos = (1 << ((number - 1) % 8))
        bytepos = ((number - 1) / 8)
        LOG.debug("bitpos %s" % bitpos)
        LOG.debug("bytepos %s" % bytepos)

        _mem = self._memobj.memory[number - 1]
        _skp = self._memobj.skipflags[bytepos]

        mem = chirp_common.Memory()

        mem.number = number
        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.duplex = "off"
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        self._get_tone(_mem, mem)

        mem.power = NC630A_POWER_LEVELS[_mem.highpower]

        mem.skip = "" if (_skp & bitpos) else "S"
        LOG.debug("mem.skip %s" % mem.skip)

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueList(
                              BCL_LIST, current_index=_mem.bcl))
        mem.extra.append(rs)

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0x8000
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
        bitpos = (1 << ((mem.number - 1) % 8))
        bytepos = ((mem.number - 1) / 8)
        LOG.debug("bitpos %s" % bitpos)
        LOG.debug("bytepos %s" % bytepos)

        _mem = self._memobj.memory[mem.number - 1]
        _skp = self._memobj.skipflags[bytepos]

        if mem.empty:
            _mem.fill_raw(b"\xFF")
            return

        _mem.set_raw(b"\x00" * 14 + b"\xFF" * 2)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.wide = mem.mode == "FM"

        self._set_tone(mem, _mem)

        _mem.highpower = mem.power == NC630A_POWER_LEVELS[1]

        if mem.skip != "S":
            _skp |= bitpos
        else:
            _skp &= ~bitpos
        LOG.debug("_skp %s" % _skp)

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        rs = RadioSetting("tot", "Time-out timer",
                          RadioSettingValueList(
                              TIMEOUTTIMER_LIST,
                              current_index=_settings.tot))
        basic.append(rs)

        rs = RadioSetting("totalert", "TOT Pre-alert",
                          RadioSettingValueList(
                              TOTALERT_LIST,
                              current_index=_settings.totalert))
        basic.append(rs)

        rs = RadioSetting("vox", "VOX Gain",
                          RadioSettingValueList(
                              VOX_LIST, current_index=_settings.vox))
        basic.append(rs)

        rs = RadioSetting("voice", "Voice Annumciation",
                          RadioSettingValueList(
                              VOICE_LIST, current_index=_settings.voice))
        basic.append(rs)

        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("voxdelay", "VOX Delay",
                          RadioSettingValueList(
                              VOXDELAY_LIST,
                              current_index=_settings.voxdelay))
        basic.append(rs)

        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueBoolean(_settings.save))
        basic.append(rs)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    LOG.debug("Setting %s = %s" % (setting, element.value))
                    setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = match_model = False

        # testing the file data size
        if len(filedata) in [0x338, 0x3C8]:
            match_size = True

        # testing model fingerprint
        if filedata[0x01B8:0x01BE] == cls._fileid:
            match_model = True

        if match_size and match_model:
            return True
        else:
            return False
