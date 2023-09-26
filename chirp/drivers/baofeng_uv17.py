# Copyright 2023:
# * Sander van der Wel, <svdwel@icloud.com>
# this software is a modified version of the boafeng driver by:
# * Jim Unroe KC9HI, <rock.unroe@gmail.com>
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

from chirp import chirp_common, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, \
    InvalidValueError
import time
import struct
import logging
from chirp import errors, util

LOG = logging.getLogger(__name__)

DTMF_CHARS = "0123456789 *#ABCD"
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]

LIST_AB = ["A", "B"]
LIST_ALMOD = ["Site", "Tone", "Code"]
LIST_BANDWIDTH = ["Wide", "Narrow"]
LIST_COLOR = ["Off", "Blue", "Orange", "Purple"]
LIST_DTMFSPEED = ["%s ms" % x for x in range(50, 2010, 10)]
LIST_DTMFST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
LIST_MODE = ["Channel", "Name", "Frequency"]
LIST_OFF1TO9 = ["Off"] + list("123456789")
LIST_OFF1TO10 = LIST_OFF1TO9 + ["10"]
LIST_OFFAB = ["Off"] + LIST_AB
LIST_RESUME = ["TO", "CO", "SE"]
LIST_PONMSG = ["Full", "Message"]
LIST_PTTID = ["Off", "BOT", "EOT", "Both"]
LIST_SCODE = ["%s" % x for x in range(1, 16)]
LIST_RPSTE = ["Off"] + ["%s" % x for x in range(1, 11)]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SHIFTD = ["Off", "+", "-"]
LIST_STEDELAY = ["Off"] + ["%s ms" % x for x in range(100, 1100, 100)]
LIST_STEP = [str(x) for x in STEPS]
LIST_TIMEOUT = ["Off"] + ["%s sec" % x for x in range(15, 615, 15)]
LIST_TXPOWER = ["High", "Mid", "Low"]
LIST_VOICE = ["Chinese", "English"]
LIST_WORKMODE = ["Frequency", "Channel"]

TXP_CHOICES = ["High", "Low"]
TXP_VALUES = [0x00, 0x02]

def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if data[0:2] == b"\x0A\x0D":
        return True
    else:
        return False
    
STIMEOUT = 1.5

def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except:
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if len(data) != amount:
        msg = "Error reading data from radio: not the amount of data we want."
        raise errors.RadioError(msg)

    return data


def _rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        #print(data)
        #print(radio)
        radio.pipe.write(data)
    except:
        raise errors.RadioError("Error sending data to radio")

def _make_read_frame(addr, length):
    """Pack the info in the header format"""
    frame = _make_frame(b'\x52', addr, length)
    # Return the data
    return frame

def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the header format"""
    frame = cmd + struct.pack("i",addr)[:-1]+struct.pack("b", length)
    # add the data if set
    if len(data) != 0:
        frame += data
    # return the data
    return frame


def _recv(radio, addr, length):
    """Get data from the radio """
    # read 4 bytes of header
    hdr = _rawrecv(radio, 4)

    # read data
    data = _rawrecv(radio, length)

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(hdr + data))

    c, a, l = struct.unpack(">BHB", hdr)
    if a != addr or l != length or c != ord("X"):
        LOG.error("Invalid answer for block 0x%04x:" % addr)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Unknown response from the radio")

    return data

def _sendmagic(radio, magic, response):
    _rawsend(radio, magic)
    ack = _rawrecv(radio, len(response))
    if ack != response:
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to enter read mode")
    
def _do_ident(radio):
    """Put the radio in PROGRAM mode & identify it"""
    radio.pipe.baudrate = radio.BAUDRATE
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # Flush input buffer
    _clean_buffer(radio)

    # Ident radio
    magic = radio._magic0
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 8)

    if not ack.startswith(radio._fingerprint):
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond as expected (A)")

    return True

def _getMemoryMap(radio):
    # Get memory map
    memory_map = []
    for addr in range(0x1FFF, 0x10FFF, 0x1000):
        frame = _make_frame(b"R", addr, 1)
        _rawsend(radio, frame)
        blocknr = ord(_rawrecv(radio, 6)[5:])
        blocknr = (blocknr>>4&0xf)*10 + (blocknr&0xf)
        memory_map += [blocknr]
        _sendmagic(radio, b"\x06", b"\x06")
    return memory_map

def _download(radio):
    """Get the memory map"""

    # Put radio in program mode and identify it
    _do_ident(radio)
    
    data = b""
    # Enter read mode
    _sendmagic(radio, radio._magic2, b"\x50\x00\x00")
    _sendmagic(radio, radio._magic3, b"\x06")

    # Start data with some unknown stuff to be compatible with the official CPS app
    _rawsend(radio, b"\x56\x00\x00\x0A\x0D")
    d = _rawrecv(radio, 13)
    data += d[3:] + 6 * b"\x00"
    _sendmagic(radio, b"\x06", b"\x06")
    _rawsend(radio, b"\x56\x00\x10\x0A\x0D")
    d = _rawrecv(radio, 13)
    data += d[3:] + 6 * b"\x00"
    _sendmagic(radio, b"\x06", b"\x06")
    _rawsend(radio, b"\x56\x00\x20\x0A\x0D")
    d = _rawrecv(radio, 13)
    data += d[3:] + 6 * b"\x00"
    _sendmagic(radio, b"\x06", b"\x06")
    data += (0x2000 - 0x30) * b"\x00"

    _sendmagic(radio, b"\x56\x00\x00\x00\x0A", b"\x56\x0A\x08\x00\x10\x00\x00\xFF\xFF\x00\x00")
    _sendmagic(radio, b"\x06", b"\x06")
    _sendmagic(radio, radio._magic4, b"\x06")
    _sendmagic(radio, b"\02", b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF")
    _sendmagic(radio, b"\x06", b"\x06")

    # Get memory map
    memory_map = _getMemoryMap(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    for block_number in radio.BLOCK_ORDER:
        block_index = memory_map.index(block_number) + 1
        start_addr = block_index * 0x1000
        for addr in range(start_addr, start_addr + 0x1000, radio.BLOCK_SIZE):
            frame = _make_read_frame(addr, radio.BLOCK_SIZE)
            # DEBUG
            LOG.debug("Frame=" + util.hexprint(frame))

            # Sending the read request
            _rawsend(radio, frame)

            # Now we read data
            d = _rawrecv(radio, radio.BLOCK_SIZE + 5)

            LOG.debug("Response Data= " + util.hexprint(d))

            # Aggregate the data
            data += d[5:]

            # UI Update
            status.cur = len(data) // radio.BLOCK_SIZE
            status.msg = "Cloning from radio..."
            radio.status_fn(status)

            # ACK ACK
            _sendmagic(radio, b"\x06", b"\x06")

    return data

def _upload(radio):
    """Upload procedure"""
    # Put radio in program mode and identify it
    _do_ident(radio)
    
    # Enter read mode
    _sendmagic(radio, radio._magic2, b"\x50\x00\x00")
    _sendmagic(radio, radio._magic3, b"\x06")

    # Start data with some unknown stuff to be compatible with the official CPS app
    _rawsend(radio, b"\x56\x00\x00\x0A\x0D")
    d = _rawrecv(radio, 13)
    _sendmagic(radio, b"\x06", b"\x06")
    _rawsend(radio, b"\x56\x00\x10\x0A\x0D")
    d = _rawrecv(radio, 13)
    _sendmagic(radio, b"\x06", b"\x06")
    _rawsend(radio, b"\x56\x00\x20\x0A\x0D")
    d = _rawrecv(radio, 13)
    _sendmagic(radio, b"\x06", b"\x06")

    _sendmagic(radio, b"\x56\x00\x00\x00\x0A", b"\x56\x0A\x08\x00\x10\x00\x00\xFF\xFF\x00\x00")
    _sendmagic(radio, b"\x06", b"\x06")
    _sendmagic(radio, radio._magic4, b"\x06")
    _sendmagic(radio, b"\02", b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF")
    _sendmagic(radio, b"\x06", b"\x06")

    # Get memory map
    memory_map = _getMemoryMap(radio)
 
    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.WRITE_MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the fun start here
    data_addr = 0x3000
    for block_number in radio.WRITE_BLOCK_ORDER:
        block_index = memory_map.index(block_number) + 1
        start_addr = block_index * 0x1000
        data_start_addr = radio.BLOCK_LOCATIONS[radio.BLOCK_ORDER.index(block_number)]
        for addr in range(start_addr, start_addr + 0x1000, radio.BLOCK_SIZE):
            # sending the data
            data_addr = data_start_addr + addr - start_addr
            data = radio.get_mmap()[data_addr:data_addr + radio.BLOCK_SIZE]

            frame = _make_frame(b"W", addr, radio.BLOCK_SIZE, data)
            #print()
            #print(hex(data_addr))
            #print(util.hexprint(frame))
            _rawsend(radio, frame)
            #time.sleep(0.05)

            # receiving the response
            ack = _rawrecv(radio, 1)
            #ack = b"\x06"
            if ack != b"\x06":
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            # UI Update
            status.cur = (data_addr - 0x3000) // radio.BLOCK_SIZE
            status.msg = "Cloning to radio..."
            radio.status_fn(status)


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return True


@directory.register

class UV17(chirp_common.CloneModeRadio, 
           chirp_common.ExperimentalRadio):
    """Baofeng UV-17"""
    VENDOR = "Baofeng"
    MODEL = "UV-17"
    NEEDS_COMPAT_SERIAL = False

    BLOCK_ORDER = [2, 16, 17, 18, 19,  24, 25, 26, 4, 6]
    BLOCK_LOCATIONS = [0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x7000, 0x8000, 0x9000, 0xA000, 0xB000]
    WRITE_BLOCK_ORDER = [16, 17, 18, 19, 24, 25, 26, 4, 6]

    MEM_TOTAL = 0xC000
    WRITE_MEM_TOTAL = 0x9000
    BLOCK_SIZE = 0x40
    STIMEOUT = 2
    BAUDRATE = 57600

    _gmrs = False
    _bw_shift = False

    _magic0 = b"PSEARCH"
    _magic2 = b"PASSSTA"
    _magic3 = b"SYSINFO"
    _magic4 = b"\xFF\xFF\xFF\xFF\x0C\x55\x56\x31\x35\x39\x39\x39"
    _fingerprint = b"\x06" + b"UV15999"

    _tri_band = False

    MODES = ["NFM", "FM"]
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "!@#$%^&*()+-=[]:\";'<>?,./"
    LENGTH_NAME = 11
    SKIP_VALUES = ["", "S"]
    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=1.00),
                    chirp_common.PowerLevel("High", watts=5.00)]
    _vhf_range = (130000000, 180000000)
    _vhf2_range = (200000000, 260000000)
    _uhf_range = (400000000, 521000000)
    VALID_BANDS = [_vhf_range,
                   _uhf_range]
    PTTID_LIST = LIST_PTTID
    SCODE_LIST = LIST_SCODE

    MEM_FORMAT = """
    #seekto 0x3030;
    struct {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      u8 unused1:8;
      ul16 rxtone;
      ul16 txtone;
      u8 unknown1:1,
         bcl:1,
         pttid:2,
         unknown2:1,
         wide:1,
         lowpower:1,
         unknown:1;
      u8 scode:4,
         unknown3:3,
         scan:1;
      u8 unknown4:8;
    } memory[1002];

    #seekto 0xA040;
    struct {
      u8 timeout;
      u8 squelch;
      u8 vox;
      u8 unknown:6,
         voice: 1
         voicealert: 1;
      u8 unknown1:8;
      u8 unknown2:8;
    } settings;

    struct vfo {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      u8 unused1:8;
      ul16 rxtone;
      ul16 txtone;
      u8 unknown1:1,
         bcl:1,
         pttid:2,
         unknown2:1,
         wide:1,
         lowpower:1,
         unknown:1;
      u8 scode:4,
         unknown3:3,
         scan:1;
      u8 unknown4:8;
    };

    #seekto 0x3010;
    struct {
      struct vfo a;
      struct vfo b;
    } vfo;

    #seekto 0x7000;
    struct {
      char name[11];
    } names[999];
    """

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        other = RadioSettingGroup("other", "Other Settings")
        work = RadioSettingGroup("work", "Work Mode Settings")
        fm_preset = RadioSettingGroup("fm_preset", "FM Preset")
        dtmfe = RadioSettingGroup("dtmfe", "DTMF Encode Settings")
        service = RadioSettingGroup("service", "Service Settings")
        top = RadioSettings(basic, advanced, other, work, fm_preset, dtmfe,
                            service)
        print(_mem.settings)

        # Basic settings
        if _mem.settings.squelch > 0x09:
            val = 0x00
        else:
            val = _mem.settings.squelch
        rs = RadioSetting("settings.squelch", "Squelch",
                          RadioSettingValueList(
                              LIST_OFF1TO9, LIST_OFF1TO9[val]))
        basic.append(rs)

        if _mem.settings.timeout > 0x27:
            val = 0x03
        else:
            val = _mem.settings.timeout
        rs = RadioSetting("settings.timeout", "Timeout Timer",
                          RadioSettingValueList(
                              LIST_TIMEOUT, LIST_TIMEOUT[val]))
        basic.append(rs)

        if _mem.settings.voice > 0x02:
            val = 0x01
        else:
            val = _mem.settings.voice
        rs = RadioSetting("settings.voice", "Voice Prompt",
                          RadioSettingValueList(
                              LIST_VOICE, LIST_VOICE[val]))
        basic.append(rs)

        rs = RadioSetting("settings.voicealert", "Voice Alert",
                          RadioSettingValueBoolean(_mem.settings.voicealert))
        basic.append(rs)


        return top

    
    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = memmap.MemoryMapBytes(data)
        self.process_mmap()
        print(self._memobj.settings)

    def sync_out(self):
        """Upload to radio"""
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_features(self):
        """Get the radio's features"""

        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_name_length = self.LENGTH_NAME
        if self._gmrs:
            rf.valid_duplexes = ["", "+", "off"]
        else:
            rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_skips = self.SKIP_VALUES
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (0, 998)
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = STEPS

        return rf

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"
    
    def get_memory(self, number):
        offset = 0
        #skip 16 bytes at memory block boundary
        if number >= 252:
            offset += 1
        if number >= 507:
            offset += 1
        if number >= 762:
            offset += 1

        _mem = self._memobj.memory[number + offset]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if _split(self.get_features(), mem.freq, int(
                          _mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        for char in _nam.name:
            if (str(char) == "\xFF") | (str(char) == "\x00"):
                char = " "  # The OEM software may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]
        txtone = int(_mem.txtone)
        rxtone = int(_mem.rxtone)
        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif (_mem.txtone & 0x8000) > 0:
            txmode = "DTCS"
            mem.dtcs = (_mem.txtone&0x0f) + (_mem.txtone>>4&0xf)*10 + (_mem.txtone>>8&0xf)*100
            if (_mem.txtone & 0xC000) == 0xC000:
                dtcs_pol[0] = "R"
        else:
            txmode = "Tone"
            mem.rtone = int((_mem.txtone&0x0f) + (_mem.txtone>>4&0xf)*10 + (_mem.txtone>>8&0xf)*100 + (_mem.txtone>>12&0xf)*1000) / 10.0

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif (_mem.rxtone & 0x8000) > 0:
            rxmode = "DTCS"
            mem.rx_dtcs = (_mem.rxtone&0x0f) + (_mem.rxtone>>4&0xf)*10 + (_mem.rxtone>>8&0xf)*100
            if (_mem.rxtone & 0xC000) == 0xC000:
                dtcs_pol[1] = "R"
        else:
            rxmode = "Tone"
            mem.ctone = int((_mem.rxtone&0x0f) + (_mem.rxtone>>4&0xf)*10 + (_mem.rxtone>>8&0xf)*100 + (_mem.txtone>>12&0xf)*1000) / 10.0

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        levels = self.POWER_LEVELS
        try:
            mem.power = levels[_mem.lowpower]
        except IndexError:
            LOG.error("Radio reported invalid power level %s (in %s)" %
                        (_mem.power, levels))
            mem.power = levels[0]

        mem.mode = _mem.wide and "FM" or "NFM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(self.PTTID_LIST,
                                                self.PTTID_LIST[_mem.pttid]))
        mem.extra.append(rs)

        rs = RadioSetting("scode", "S-CODE",
                          RadioSettingValueList(self.SCODE_LIST,
                                                self.SCODE_LIST[_mem.scode - 1]))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        offset = 0
        #skip 16 bytes at memory block boundary
        if mem.number >= 252:
            offset += 1
        if mem.number >= 507:
            offset += 1
        if mem.number >= 762:
            offset += 1
        _mem = self._memobj.memory[mem.number + offset]
        _nam = self._memobj.names[mem.number]

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

        _mem.set_raw("\x00" * 16)
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

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            tone = str(int(mem.rtone * 10)).rjust(4, '0')
            _mem.txtone = (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            tone = str(int(mem.ctone * 10)).rjust(4, '0')
            _mem.txtone = (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
            _mem.rxtone = (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            tone = str(int(mem.dtcs)).rjust(4, '0')
            _mem.txtone = 0x8000 + (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
            _mem.rxtone = 0x8000 + (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                tone = str(int(mem.rtone * 10)).rjust(4, '0')
                _mem.txtone = (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
            elif txmode == "DTCS":
                tone = str(int(mem.dtcs)).rjust(4, '0')
                _mem.txtone = 0x8000 + (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                tone = str(int(mem.ctone * 10)).rjust(4, '0')
                _mem.rxtone = (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
            elif rxmode == "DTCS":
                tone = str(int(mem.rx_dtcs)).rjust(4, '0')
                _mem.rxtone = 0x8000 + (int(tone[0])<<12) + (int(tone[1])<<8) + (int(tone[2])<<4) + int(tone[3])
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x4000
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x4000

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "FM"

        if mem.power:
            _mem.lowpower = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.lowpower = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                if setting.get_name() == "scode":
                    setattr(_mem, setting.get_name(), str(int(setting.value) + 1))
                else:
                    setattr(_mem, setting.get_name(), setting.value)
        else:
            # there are no extra settings, load defaults
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.scode = 0


    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() == "fm_preset":
                    self._set_fm_preset(element)
                else:
                    self.set_settings(element)
                    continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _set_fm_preset(self, settings):
        for element in settings:
            try:
                val = element.value
                if self._memobj.fm_presets <= 108.0 * 10 - 650:
                    value = int(val.get_value() * 10 - 650)
                else:
                    value = int(val.get_value() * 10)
                LOG.debug("Setting fm_presets = %s" % (value))
                if self._bw_shift:
                    value = ((value & 0x00FF) << 8) | ((value & 0xFF00) >> 8)
                self._memobj.fm_presets = value
            except Exception:
                LOG.debug(element.get_name())
                raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) in [0xC000]:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False





