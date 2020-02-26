# Copyright August 2018 Klaus Ruebsam <dg5eau@ruebsam.eu>
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

import time
import os
import struct
import logging

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettings, \
    RadioSettingValueString

LOG = logging.getLogger(__name__)

# memory map
# 0000 copy of channel 16: 0100 - 010F
# 0010 Channel 1
# 0020 Channel 2
# 0030 Channel 3
# 0040 Channel 4
# 0050 Channel 5
# 0060 Channel 6
# 0070 Channel 7
# 0080 Channel 8
# 0090 Channel 9
# 00A0 Channel 10
# 00B0 Channel 11
# 00C0 Channel 12
# 00D0 Channel 13
# 00E0 Channel 14
# 00F0 Channel 15
# 0100 Channel 16
# 03C0 various settings

# the last three bytes of every channel are identical
# to the first three bytes of the next channel in row.
# However it will automatically be filled by the radio itself

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  lbcd rx_tone[2];
  lbcd tx_tone[2];
  u8 unknown1:1,
    compand:1,
    scramb:1,
    scanadd:1,
    power:1,
    mode:1,
    unknown2:1,
    bclo:1;
  u8 unknown3[3];
} memory[16];

#seekto 0x03C0;
struct {
  u8 unknown3c08:1,
      scanmode:1,
      unknown3c06:1,
      unknown3c05:1,
      voice:2,
      save:1,
      beep:1;
  u8 squelch;
  u8 unknown3c2;
  u8 timeout;
  u8 voxgain;
  u8 specialcode;
  u8 unknown3c6;
  u8 voxdelay;
} settings;

"""

CMD_ACK = "\x06"
CMD_ALT_ACK = "\x53"
CMD_STX = "\x02"
CMD_ENQ = "\x05"

POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=0.50),
                chirp_common.PowerLevel("High", watts=3.00)]
TIMEOUT_LIST = ["Off"] + ["%s seconds" % x for x in range(30, 330, 30)]
SCANMODE_LIST = ["Carrier", "Timer"]
VOICE_LIST = ["Off", "Chinese", "English"]
VOX_LIST = ["Off"] + ["%s" % x for x in range(1, 9)]
VOXDELAY_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
MODE_LIST = ["WFM", "NFM"]

TONES = chirp_common.TONES
DTCS_CODES = chirp_common.DTCS_CODES

SETTING_LISTS = {
    "tot": TIMEOUT_LIST,
    "scanmode": SCANMODE_LIST,
    "voice": VOICE_LIST,
    "vox": VOX_LIST,
    "voxdelay": VOXDELAY_LIST,
    "mode": MODE_LIST,
    }

VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
    "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"


def _r2_enter_programming_mode(radio):
    serial = radio.pipe

    magic = "TYOGRAM"
    exito = False
    serial.write(CMD_STX)
    for i in range(0, 5):
        for j in range(0, len(magic)):
            serial.write(magic[j])
        ack = serial.read(1)
        if ack == CMD_ACK:
            exito = True
            break

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check your interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    try:
        serial.write(CMD_STX)
        ident = serial.read(8)
    except:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    # No idea yet what the next 7 bytes stand for
    # as long as they start with ACK (or ALT_ACK on some devices) we are fine
    if not ident.startswith(CMD_ACK) and not ident.startswith(CMD_ALT_ACK):
        _r2_exit_programming_mode(radio)
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")

    # the next 6 bytes represent the 6 digit password
    # they are somehow coded where '1' becomes x01 and 'a' becomes x25
    try:
        serial.write(CMD_ENQ)
        ack = serial.read(6)
    except:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    # we will only read if no password is set
    if ack != "\xFF\xFF\xFF\xFF\xFF\xFF":
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Radio is password protected")
    try:
        serial.write(CMD_ACK)
        ack = serial.read(6)

    except:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio 2")

    if ack != CMD_ACK:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode 2")


def _r2_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(CMD_ACK)
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _r2_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        for j in range(0, len(cmd)):
            serial.write(cmd[j])

        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            _r2_exit_programming_mode(radio)
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        _r2_exit_programming_mode(radio)
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _r2_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing block %04x..." % (block_addr))
    LOG.debug(util.hexprint(cmd + data))

    try:
        for j in range(0, len(cmd)):
            serial.write(cmd[j])
        for j in range(0, len(data)):
            serial.write(data[j])
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        _r2_exit_programming_mode(radio)
        raise errors.RadioError("Failed to send block "
                                "%04x to radio" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _r2_enter_programming_mode(radio)

    data = ""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio._block_size):
        status.cur = addr + radio._block_size
        radio.status_fn(status)

        block = _r2_read_block(radio, addr, radio._block_size)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    data += radio.MODEL.ljust(8)

    _r2_exit_programming_mode(radio)

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _r2_enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr, block_size in radio._ranges:
        for addr in range(start_addr, end_addr, block_size):
            status.cur = addr + block_size
            radio.status_fn(status)
            _r2_write_block(radio, addr, block_size)

    _r2_exit_programming_mode(radio)


class RadioddityR2(chirp_common.CloneModeRadio):
    """Radioddity R2"""
    VENDOR = "Radioddity"
    MODEL = "R2"
    BAUD_RATE = 9600

    # definitions on how to read StartAddr EndAddr BlockZize
    _ranges = [
               (0x0000, 0x01F8, 0x08),
               (0x01F8, 0x03F0, 0x08)
              ]
    _memsize = 0x03F0
    # never read more than 8 bytes at once
    _block_size = 0x08
    # frequency range is 400-470MHz
    _range = [400000000, 470000000]
    # maximum 16 channels
    _upper = 16

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = False
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.can_odd_split = False
        # FIXME: Is this right? The get_memory() has no checking for
        # deleted memories, but set_memory() used to reference a missing
        # variable likely copied from another driver
        rf.can_delete = False
        rf.valid_modes = MODE_LIST
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "Tone->Tone",
            "->DTCS",
            "DTCS->",
            "DTCS->DTCS"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = []
        rf.valid_bands = [self._range]
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
        return rf

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        # to set the vars on the class to the correct ones

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        if val.get_raw() == "\xFF\xFF":
            return '', None, None

        val = int(val)

        if val >= 12000:
            a = val - 12000
            return 'DTCS', a, 'R'

        elif val >= 8000:
            a = val - 8000
            return 'DTCS', a, 'N'

        else:
            a = val / 10.0
            return 'Tone', a, None

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
        bitpos = (1 << ((number - 1) % 8))
        bytepos = ((number - 1) / 8)
        LOG.debug("bitpos %s" % bitpos)
        LOG.debug("bytepos %s" % bytepos)

        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()

        mem.number = number

        mem.freq = int(_mem.rx_freq) * 10

        txfreq = int(_mem.tx_freq) * 10
        if txfreq == mem.freq:
            mem.duplex = ""
        elif txfreq == 0:
            mem.duplex = "off"
            mem.offset = 0
        # 166666665*10 is the equivalent for FF FF FF FF
        # stored in the TX field
        elif txfreq == 1666666650:
            mem.duplex = "off"
            mem.offset = 0
        elif txfreq < mem.freq:
            mem.duplex = "-"
            mem.offset = mem.freq - txfreq
        elif txfreq > mem.freq:
            mem.duplex = "+"
            mem.offset = txfreq - mem.freq

        # get bandwith FM or NFM
        mem.mode = MODE_LIST[_mem.mode]

        # tone data
        txtone = self.decode_tone(_mem.tx_tone)
        rxtone = self.decode_tone(_mem.rx_tone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.power = POWER_LEVELS[_mem.power]

        # add extra channel settings to the OTHER tab of the properties
        # extra settings are unfortunately inverted
        mem.extra = RadioSettingGroup("extra", "Extra")

        scanadd = RadioSetting("scanadd", "Scan Add",
                               RadioSettingValueBoolean(
                                   not bool(_mem.scanadd)))
        scanadd.set_doc("Add channel for scanning")
        mem.extra.append(scanadd)

        bclo = RadioSetting("bclo", "Busy Lockout",
                            RadioSettingValueBoolean(not bool(_mem.bclo)))
        bclo.set_doc("Busy Lockout")
        mem.extra.append(bclo)

        scramb = RadioSetting("scramb", "Scramble",
                              RadioSettingValueBoolean(not bool(_mem.scramb)))
        scramb.set_doc("Scramble Audio Signal")
        mem.extra.append(scramb)

        compand = RadioSetting("compand", "Compander",
                               RadioSettingValueBoolean(
                                   not bool(_mem.compand)))
        compand.set_doc("Compress Audio for TX")
        mem.extra.append(compand)

        return mem

    def set_memory(self, mem):
        bitpos = (1 << ((mem.number - 1) % 8))
        bytepos = ((mem.number - 1) / 8)
        LOG.debug("bitpos %s" % bitpos)
        LOG.debug("bytepos %s" % bytepos)

        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]

        LOG.warning('This driver may be broken for deleted memories')
        if mem.empty:
            return

        _mem.rx_freq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.tx_freq[i].set_raw("\xFF")
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        # power, default power is low
        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0     # low

        # tone data
        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.tx_tone, txmode, txtone, txpol)
        self.encode_tone(_mem.rx_tone, rxmode, rxtone, rxpol)

        _mem.mode = MODE_LIST.index(mem.mode)

        # extra settings are unfortunately inverted
        for setting in mem.extra:
            LOG.debug("@set_mem:", setting.get_name(), setting.value)
            setattr(_mem, setting.get_name(), not setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        rs = RadioSetting("settings.squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("settings.timeout", "Timeout Timer",
                          RadioSettingValueList(
                              TIMEOUT_LIST, TIMEOUT_LIST[_settings.timeout]))

        basic.append(rs)

        rs = RadioSetting("settings.scanmode", "Scan Mode",
                          RadioSettingValueList(
                              SCANMODE_LIST,
                              SCANMODE_LIST[_settings.scanmode]))
        basic.append(rs)

        rs = RadioSetting("settings.voice", "Voice Prompts",
                          RadioSettingValueList(
                              VOICE_LIST, VOICE_LIST[_settings.voice]))
        basic.append(rs)

        rs = RadioSetting("settings.voxgain", "VOX Level",
                          RadioSettingValueList(
                              VOX_LIST, VOX_LIST[_settings.voxgain]))
        basic.append(rs)

        rs = RadioSetting("settings.voxdelay", "VOX Delay Time",
                          RadioSettingValueList(
                              VOXDELAY_LIST,
                              VOXDELAY_LIST[_settings.voxdelay]))
        basic.append(rs)

        rs = RadioSetting("settings.save", "Battery Save",
                          RadioSettingValueBoolean(_settings.save))
        basic.append(rs)

        rs = RadioSetting("settings.beep", "Beep Tone",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in VALID_CHARS:
                    filtered += char
                else:
                    filtered += " "
            return filtered

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
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


class RT24Alias(chirp_common.Alias):
    VENDOR = "Retevis"
    MODEL = "RT24"


@directory.register
class RadioddityR2Generic(RadioddityR2):
    ALIASES = [RT24Alias]
