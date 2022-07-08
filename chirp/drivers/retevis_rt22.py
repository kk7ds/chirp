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

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];                
  lbcd txfreq[4];                
  ul16 rx_tone;                  
  ul16 tx_tone;                  
  u8 unknown1;                   
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
  u8 unknown1[3];
  u8 squelch;     // Squelch Level
  u8 save;        // Battery Saver                    
  u8 beep;        // Beep                             
  u8 unknown2[2];
  u8 vox;         // VOX
  u8 voxgain;     // VOX Gain
  u8 voxdelay;    // VOX Delay                        
  u8 unknown3[2];
  u8 pf2key;      // PF2 Key                          
} settings;

#seekto 0x017E;
u8 skipflags[2];  // SCAN_ADD

#seekto 0x0300;
struct {
  char line1[32];
  char line2[32];
} embedded_msg;
"""

CMD_ACK = "\x06"

RT22_POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=2.00),
                     chirp_common.PowerLevel("High", watts=5.00)]

RT22_DTCS = sorted(chirp_common.DTCS_CODES + [645])

PF2KEY_LIST = ["Scan", "Local Alarm", "Remote Alarm"]
TIMEOUTTIMER_LIST = [""] + ["%s seconds" % x for x in range(15, 615, 15)]
VOICE_LIST = ["Off", "Chinese", "English"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 17)]
VOXDELAY_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]

SETTING_LISTS = {
    "pf2key": PF2KEY_LIST,
    "tot": TIMEOUTTIMER_LIST,
    "voice": VOICE_LIST,
    "vox": VOX_LIST,
    "voxdelay": VOXDELAY_LIST,
    }

VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
    "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"


def _rt22_enter_programming_mode(radio):
    serial = radio.pipe

    magic = "PROGRGS"
    exito = False
    for i in range(0, 5):
        for j in range(0, len(magic)):
            time.sleep(0.005)
            serial.write(magic[j])
        ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    try:
        serial.write("\x02")
        ident = serial.read(8)
    except:
        _rt22_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    # check if ident is OK
    itis = False
    for fp in radio._fileid:
        if fp in ident:
            # got it!
            itis = True

            break

    if itis is False:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _rt22_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        _rt22_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write("\x07")
        ack = serial.read(1)
    except:
        _rt22_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != "\x4E":
        _rt22_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")


def _rt22_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write("E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _rt22_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        for j in range(0, len(cmd)):
            time.sleep(0.005)
            serial.write(cmd[j])

        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            _rt22_exit_programming_mode(radio)
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _rt22_exit_programming_mode(radio)
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        _rt22_exit_programming_mode(radio)
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _rt22_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        for j in range(0, len(cmd)):
            time.sleep(0.005)
            serial.write(cmd[j])
        for j in range(0, len(data)):
            time.sleep(0.005)
            serial.write(data[j])
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        _rt22_exit_programming_mode(radio)
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _rt22_enter_programming_mode(radio)

    data = ""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio._block_size):
        status.cur = addr + radio._block_size
        radio.status_fn(status)

        block = _rt22_read_block(radio, addr, radio._block_size)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    data += radio.MODEL.ljust(8)

    _rt22_exit_programming_mode(radio)

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _rt22_enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr, block_size in radio._ranges:
        for addr in range(start_addr, end_addr, block_size):
            status.cur = addr + block_size
            radio.status_fn(status)
            _rt22_write_block(radio, addr, block_size)

    _rt22_exit_programming_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if len(data) == 0x0408:
        rid = data[0x0400:0x0408]
        return rid.startswith(cls.MODEL)
    else:
        return False


@directory.register
class RT22Radio(chirp_common.CloneModeRadio):
    """Retevis RT22"""
    VENDOR = "Retevis"
    MODEL = "RT22"
    BAUD_RATE = 9600

    _ranges = [
               (0x0000, 0x0180, 0x10),
               (0x01B8, 0x01F8, 0x10),
               (0x01F8, 0x0200, 0x08),
               (0x0200, 0x0340, 0x10),
              ]
    _memsize = 0x0400
    _block_size = 0x40
    _fileid = ["P32073", "P3" + "\x00\x00\x00" + "3"]

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
        rf.valid_power_levels = RT22_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]  # 12.5 KHz, 25 kHz.
        rf.memory_bounds = (1, 16)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = [(400000000, 520000000)]

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

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

        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == "\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        self._get_tone(_mem, mem)

        mem.power = RT22_POWER_LEVELS[_mem.highpower]

        mem.skip = "" if (_skp & bitpos) else "S"
        LOG.debug("mem.skip %s" % mem.skip)

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
            _mem.set_raw("\xFF" * (_mem.size() / 8))
            return

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
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

        _mem.highpower = mem.power == RT22_POWER_LEVELS[1]

        if mem.skip != "S":
            _skp |= bitpos
        else:
            _skp &= ~bitpos
        LOG.debug("_skp %s" % _skp)

    def get_settings(self):
        _settings = self._memobj.settings
        _message = self._memobj.embedded_msg
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("tot", "Time-out timer",
                          RadioSettingValueList(
                              TIMEOUTTIMER_LIST,
                              TIMEOUTTIMER_LIST[_settings.tot]))
        basic.append(rs)

        rs = RadioSetting("voice", "Voice Prompts",
                          RadioSettingValueList(
                              VOICE_LIST, VOICE_LIST[_settings.voice]))
        basic.append(rs)

        rs = RadioSetting("pf2key", "PF2 Key",
                          RadioSettingValueList(
                              PF2KEY_LIST, PF2KEY_LIST[_settings.pf2key]))
        basic.append(rs)

        rs = RadioSetting("vox", "Vox",
                          RadioSettingValueBoolean(_settings.vox))
        basic.append(rs)

        rs = RadioSetting("voxgain", "VOX Level",
                          RadioSettingValueList(
                              VOX_LIST, VOX_LIST[_settings.voxgain]))
        basic.append(rs)

        rs = RadioSetting("voxdelay", "VOX Delay Time",
                          RadioSettingValueList(
                              VOXDELAY_LIST,
                              VOXDELAY_LIST[_settings.voxdelay]))
        basic.append(rs)

        rs = RadioSetting("save", "Battery Save",
                          RadioSettingValueBoolean(_settings.save))
        basic.append(rs)

        rs = RadioSetting("beep", "Beep",
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

        rs = RadioSetting("embedded_msg.line1", "Embedded Message 1",
                          RadioSettingValueString(0, 32, _filter(
                              _message.line1)))
        basic.append(rs)

        rs = RadioSetting("embedded_msg.line2", "Embedded Message 2",
                          RadioSettingValueString(0, 32, _filter(
                              _message.line2)))
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
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) in [0x0408, ]:
            match_size = True
        
        # testing the model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False

@directory.register
class KDC1(RT22Radio):
    """WLN KD-C1"""
    VENDOR = "WLN"
    MODEL = "KD-C1"

@directory.register
class ZTX6(RT22Radio):
    """Zastone ZT-X6"""
    VENDOR = "Zastone"
    MODEL = "ZT-X6"

@directory.register
class LT316(RT22Radio):
    """Luiton LT-316"""
    VENDOR = "LUITON"
    MODEL = "LT-316"

@directory.register
class TDM8(RT22Radio):
    VENDOR = "TID"
    MODEL = "TD-M8"
