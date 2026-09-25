# Copyright 2016 Jim Unroe <rock.unroe@gmail.com>
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
  lbcd rxtone[2];
  lbcd txtone[2];
  u8 speccode:1,    // SpecCode
     compander:1,   // Compander
     scramble:1,    // Scramble
     skip:1,        // Scan Add
     highpower:1,   // Power Level
     wide:1,        // Bandwidth
     encrypt:1,     // Encryption? -> Doesnt seem to have impact except of OEM Software showing encrypted and 470MHz 
     bcl:1;         // Busy Lock
  u8 unknown2[3];
} memory[32];

#seekto 0x03c0;
struct {
  u8 voxc:1,        // VOX Control
     scanmode:1,    // Scan Carrier/Time
     codesw:1,      // Code Switch --> RemoveCT/DCS
     bank:1,        // Selected memory Bank AKA PMR and Freenet
     unknown1:2,
     save:1,        // Battery Save
     unknown2:1;
  u8 squelch;       // Squelch
  u8 k1shortp;      // Key 1 Short Press
  u8 tot;           // Time Out Timer
  u8 unknown3:4,
     voxg:4;        // VOX Gain
  u8 unknown4;
  u8 unknown5;
  u8 voxd:4,        // VOX Delay
     unknown6:4;  
  u8 unknown7:7,
     specmode:1;    // Spec Code 1 or 2
} settings;

"""

CMD_ACK = b"\x06"

RB669_POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=0.50),
                    chirp_common.PowerLevel("High", watts=1.00)]

RB669_DTCS = tuple(sorted(chirp_common.DTCS_CODES))

LIST_SCANMODE = ["Carrier", "Time"]
#LIST_SHORT_PRESS = ["Off", "Monitor On/Off", "VOX On/Off", "Alarm", "2/3", "BEEPs", "Unknown", "PIEPs", "FUNCTION0", "FUNCTION1", "FUNCTION2", "FUNCTION3", "FUNCTION4", "FUNCTION5", "FUNCTION6", "FUNCTION07"]
LIST_SHORT_PRESS = ["Off", "Monitor On/Off", "VOX On/Off", "Alarm"]
LIST_VOXDELAY = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
LIST_TIMEOUTTIMER = ["Off"] + ["%s" % x for x in range(30, 330, 30)]
LIST_SAVE = ["Off", "On"]
LIST_SPECMODE = ["Spec Code 1", "Spec Code 2"]
LIST_BANK = ["PMR", "Freenet"]


def _enter_programming_mode(radio):
    serial = radio.pipe

    magic = [b"H32GRAM"]
    for i in range(0, 1):

        try:
            LOG.debug("sending " + magic[i].decode())
            serial.write(magic[i])
            ack = serial.read(1)
        except:
            _exit_programming_mode(radio)
            raise errors.RadioError("Error communicating with radio")

        if not ack:
            _exit_programming_mode(radio)
            raise errors.RadioNoResponse()
        elif ack != CMD_ACK:
            LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
            _exit_programming_mode(radio)
            raise errors.RadioError("Radio refused to enter programming mode")

    try:
        LOG.debug("sending " + util.hexprint("\x02"))
        serial.write(b"\x02")
        ident = serial.read(20)
    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if not ident.startswith(b"SMP558"):
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ident))
        _exit_programming_mode(radio)
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        LOG.debug("sending " + util.hexprint(CMD_ACK))
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
        _exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")

    # DEBUG
    LOG.info("Positive ident, this is a %s %s" % (radio.VENDOR, radio.MODEL))


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"b\x0D\x0A")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)

        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            _exit_programming_mode(radio)
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe
    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        _exit_programming_mode(radio)
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio._block_size):
        status.cur = addr + radio._block_size
        radio.status_fn(status)

        block = _read_block(radio, addr, radio._block_size)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr, block_size in radio._ranges:
        for addr in range(start_addr, end_addr, block_size):
            status.cur = addr + block_size
            radio.status_fn(status)
            _write_block(radio, addr, block_size)

    _exit_programming_mode(radio)

@directory.register
class RB669Radio(chirp_common.CloneModeRadio):
    """Retevis RB669"""
    VENDOR = "Retevis"
    MODEL = "RB669"
    BAUD_RATE = 9600

    _memsize = 0x03f8
    _block_size = 0x08
    _ranges = [
               (0x0000, _memsize, _block_size),
              ]
    # these ranges are just so narrow as thats whats allowed but I am confident a wider use of band is Possible
    _vhf_range = (149000000, 149115000)
    _uhf_range = (446000000, 466200000)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False #or does it?
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = ["S", ""]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = RB669_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]  # 12.5 kHz, 25 kHz.
        rf.valid_dtcs_codes = RB669_DTCS
        rf.memory_bounds = (1, 32)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = [self._vhf_range, self._uhf_range]

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

    def decode_tone(self, val):
        val = int(val)
        if val == 16665:
            return '', None, None
        elif val >= 12000:
            return 'DTCS', val - 12000, 'R'
        elif val >= 8000:
            return 'DTCS', val - 8000, 'N'
        else:
            return 'Tone', val / 10.0, None

    def encode_tone(self, memval, mode, value, pol):
        """Parse the tone data to encode from UI to mem"""
        if mode == '':
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            flag = 0x80 if pol == 'N' else 0xC0
            memval.set_value(value)
            memval[1].set_bits(flag)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

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

        mem.mode = _mem.wide and "NFM" or "FM"

        rxtone = txtone = None
        txtone = self.decode_tone(_mem.txtone)
        rxtone = self.decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.power = RB669_POWER_LEVELS[_mem.highpower]

        if _mem.skip:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "Busy Lock",
                          RadioSettingValueBoolean(not _mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(not _mem.compander))
        mem.extra.append(rs)

        rs = RadioSetting("scramble", "Scramble",
                          RadioSettingValueBoolean(not _mem.scramble))
        mem.extra.append(rs)

        rs = RadioSetting("speccode", "Spec Code",
                          RadioSettingValueBoolean(not _mem.speccode))
        mem.extra.append(rs)

        rs = RadioSetting("encrypt", "Encrypt",
                          RadioSettingValueBoolean(not _mem.encrypt))
        rs.set_doc("This does not seem to change anything to the devices behaviour, but the OEM software only shows encrypted when your read this out")
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xFF" * (_mem.size() // 8))
            return

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

        _mem.wide = mem.mode == "NFM"

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.txtone, txmode, txtone, txpol)
        self.encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        _mem.highpower = mem.power == RB669_POWER_LEVELS[1]

        _mem.skip = mem.skip == "S"

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), not int(setting.value))

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        if _settings.k1shortp > 4:
            val = 1
        else:
            val = _settings.k1shortp
        rs = RadioSetting("k1shortp", "Key Short Press",
                          RadioSettingValueList(
                              LIST_SHORT_PRESS,
                              current_index=val))
        rs.set_doc("Function of side key. Note: 'Alarm' is not offical and once enable can only be disabled by powering down the devcice")
        basic.append(rs)

        rs = RadioSetting("voxc", "VOX Control",
                          RadioSettingValueBoolean(_settings.voxc))
        basic.append(rs)

        if _settings.voxg > 9:
            val = 4
        else:
            val = _settings.voxg
        rs = RadioSetting("voxg", "VOX Gain",
                          RadioSettingValueInteger(0, 9, val))
        basic.append(rs)

        rs = RadioSetting("voxd", "VOX Delay Time",
                          RadioSettingValueList(
                              LIST_VOXDELAY,
                              current_index=_settings.voxd))
        basic.append(rs)

        if _settings.squelch > 8:
            val = 4
        else:
            val = _settings.squelch
        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, val))
        basic.append(rs)

        if _settings.tot > 10:
            val = 6
        else:
            val = _settings.tot
        rs = RadioSetting("tot", "Time-out Timer[s]",
                          RadioSettingValueList(
                              LIST_TIMEOUTTIMER,
                              current_index=val))
        basic.append(rs)

        rs = RadioSetting("scanmode", "Scan Mode",
                          RadioSettingValueList(
                              LIST_SCANMODE,
                              current_index=_settings.scanmode))
        rs.set_doc("To Enable Scan Mode you need to select Channel 16 (not 32!)\n- Carrier will change to the first RX Channel and stays there\n- Time will change the first channel with RX and rescan every 5sec")
        basic.append(rs)

        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueBoolean(_settings.save))
        basic.append(rs)

        rs = RadioSetting("codesw", "Code Switch",
                          RadioSettingValueBoolean(_settings.codesw))
        basic.append(rs)

        rs = RadioSetting("specmode", "Spec Mode",
                          RadioSettingValueList(
                              LIST_SPECMODE,
                              current_index=_settings.specmode))
        basic.append(rs)

        rs = RadioSetting("bank", "Memory Bank",
                          RadioSettingValueList(
                              LIST_BANK,
                              current_index=_settings.bank))
        rs.set_doc("Selected memory Bank\n- PMR = Channels 01-16\n- Freenet = Channels 17-32\nCan be changed by long press the side button")
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

                    if element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise
