# Copyright 2016:
# * Jim Unroe KC9HI, <rock.unroe@gmail.com>
# * Pavel Milanes CO7WT <pavelmc@gmail.com>
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
import struct
import logging
import re

LOG = logging.getLogger(__name__)

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings
from textwrap import dedent

MEM_FORMAT = """
struct mem {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  lbcd rxtone[2];
  lbcd txtone[2];
  u8 unknown0:2,
     txp:2,
     wn:2,
     unknown1:1,
     bcl:1;
  u8 unknown2:2,
     revert:1,
     dname:1,
     unknown3:4;
  u8 unknown4[2];
};

struct nam {
  char name[6];
  u8 unknown1[2];
};

#seekto 0x0000;
struct mem left_memory[500];

#seekto 0x2000;
struct mem right_memory[500];

#seekto 0x4000;
struct nam left_names[500];

#seekto 0x5000;
struct nam right_names[500];

#seekto 0x6000;
u8 left_usedflags[64];

#seekto 0x6040;
u8 left_scanflags[64];

#seekto 0x6080;
u8 right_usedflags[64];

#seekto 0x60C0;
u8 right_scanflags[64];

#seekto 0x6160;
struct {
  char line32[32];
} embedded_msg;

#seekto 0x6180;
struct {
  u8  sbmute:2,        // sub band mute
      unknown1:1,
      workmodb:1,      // work mode (right side)
      dw:1,            // dual watch
      audio:1,         // audio output mode (stereo/mono)
      unknown2:1,
      workmoda:1;      // work mode (left side)
  u8  scansb:1,        // scan stop beep
      aftone:3,        // af tone control
      scand:1,         // scan directon
      scanr:3;         // scan resume
  u8  rxexp:1,         // rx expansion
      ptt:1,           // ptt mode
      display:1,       // display select (frequency/clock)
      omode:1,         // operaton mode
      beep:2,          // beep volume
      spkr:2;          // speaker
  u8  cpuclk:1,        // operating mode(cpu clock)
      fkey:3,          // fkey function
      mrscan:1,        // memory scan type
      color:3;         // lcd backlight color
  u8  vox:2,           // vox
      voxs:3,          // vox sensitivity
      mgain:3;         // mic gain
  u8  wbandb:4,        // work band (right side)
      wbanda:4;        // work band (left side)
  u8  sqlb:4,          // squelch level (right side)
      sqla:4;          // squelch level (left side)
  u8  apo:4,           // auto power off
      ars:1,           // automatic repeater shift
      tot:3;           // time out timer
  u8  stepb:4,         // auto step (right side)
      stepa:4;         // auto step (left side)
  u8  rxcoverm:1,      // rx coverage-memory
      lcdc:3,          // lcd contrast
      rxcoverv:1,      // rx coverage-vfo
      lcdb:3;          // lcd brightness
  u8  smode:1,         // smart function mode
      timefmt:1,       // time format
      datefmt:2,       // date format
      timesig:1,       // time signal
      keyb:3;          // key/led brightness
  u8  dwstop:1,        // dual watch stop
      unknown3:1,
      sqlexp:1,        // sql expansion
      decbandsel:1,    // decoding band select
      dtmfmodenc:1,    // dtmf mode encode
      bell:3;          // bell ringer
  u8  unknown4:2,
      btime:6;         // lcd backlight time
  u8  unknown5:2,
      tz:6;            // time zone
  u8  unknown618E;
  u8  unknown618F;
  ul16  offseta;       // work offset (left side)
  ul16  offsetb;       // work offset (right side)
  ul16  mrcha;         // selected memory channel (left)
  ul16  mrchb;         // selected memory channel (right)
  ul16  wpricha;       // work priority channel (left)
  ul16  wprichb;       // work priority channel (right)
  u8  unknown6:3,
      datasql:2,       // data squelch
      dataspd:1,       // data speed
      databnd:2;       // data band select
  u8  unknown7:1,
      pfkey2:3,        // mic p2 key
      unknown8:1,
      pfkey1:3;        // mic p1 key
  u8  unknown9:1,
      pfkey4:3,        // mic p4 key
      unknowna:1,
      pfkey3:3;        // mic p3 key
  u8  unknownb:7,
      dtmfmoddec:1;    // dtmf mode decode
} settings;

#seekto 0x61B0;
struct {
  char line16[16];
} poweron_msg;

#seekto 0x6300;
struct {
  u8  unknown1:3,
      ttdgt:5;         // dtmf digit time
  u8  unknown2:3,
      ttint:5;         // dtmf interval time
  u8  unknown3:3,
      tt1stdgt:5;      // dtmf 1st digit time
  u8  unknown4:3,
      tt1stdly:5;      // dtmf 1st digit delay
  u8  unknown5:3,
      ttdlyqt:5;       // dtmf delay when use qt
  u8  unknown6:3,
      ttdkey:5;        // dtmf d key function
  u8  unknown7;
  u8  unknown8:4,
      ttautod:4;       // dtmf auto dial group
} dtmf;

#seekto 0x6330;
struct {
  u8  unknown1:7,
      ttsig:1;         // dtmf signal
  u8  unknown2:4,
      ttintcode:4;     // dtmf interval code
  u8  unknown3:5,
      ttgrpcode:3;     // dtmf group code
  u8  unknown4:4,
      ttautorst:4;     // dtmf auto reset time
  u8  unknown5:5,
      ttalert:3;       // dtmf alert tone/transpond
} dtmf2;

#seekto 0x6360;
struct {
  u8 code1[8];         // dtmf code
  u8 code1_len;        // dtmf code length
  u8 unknown1[7];
  u8 code2[8];         // dtmf code
  u8 code2_len;        // dtmf code length
  u8 unknown2[7];
  u8 code3[8];         // dtmf code
  u8 code3_len;        // dtmf code length
  u8 unknown3[7];
  u8 code4[8];         // dtmf code
  u8 code4_len;        // dtmf code length
  u8 unknown4[7];
  u8 code5[8];         // dtmf code
  u8 code5_len;        // dtmf code length
  u8 unknown5[7];
  u8 code6[8];         // dtmf code
  u8 code6_len;        // dtmf code length
  u8 unknown6[7];
  u8 code7[8];         // dtmf code
  u8 code7_len;        // dtmf code length
  u8 unknown7[7];
  u8 code8[8];         // dtmf code
  u8 code8_len;        // dtmf code length
  u8 unknown8[7];
  u8 code9[8];         // dtmf code
  u8 code9_len;        // dtmf code length
  u8 unknown9[7];
} dtmfcode;

"""

MEM_SIZE = 0x8000
BLOCK_SIZE = 0x40
MODES = ["FM", "Auto", "NFM", "AM"]
SKIP_VALUES = ["", "S"]
TONES = chirp_common.TONES
DTCS_CODES = chirp_common.DTCS_CODES
NAME_LENGTH = 6
DTMF_CHARS = list("0123456789ABCD*#")
STIMEOUT = 1

# valid chars on the LCD
VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
    "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"

# Power Levels
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("Mid", watts=20),
                chirp_common.PowerLevel("High", watts=50)]

# B-TECH UV-50X3 id string
UV50X3_id  = "VGC6600MD"


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        Log.debug("Got %i bytes of junk before starting" % len(junk))


def _check_for_double_ack(radio):
    radio.pipe.timeout = 0.005
    c = radio.pipe.read(1)
    radio.pipe.timeout = STIMEOUT
    if c and c != '\x06':
        _exit_program_mode(radio)
        raise errors.RadioError('Expected nothing or ACK, got %r' % c)


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except:
        _exit_program_mode(radio)
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if len(data) != amount:
        _exit_program_mode(radio)
        msg = "Error reading data from radio: not the amount of data we want."
        raise errors.RadioError(msg)

    return data


def _rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        radio.pipe.write(data)
    except:
        raise errors.RadioError("Error sending data to radio")


def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the headder format"""
    frame = struct.pack(">BHB", ord(cmd), addr, length)
    # add the data if set
    if len(data) != 0:
        frame += data
    # return the data
    return frame


def _recv(radio, addr, length=BLOCK_SIZE):
    """Get data from the radio """
    # read 4 bytes of header
    hdr = _rawrecv(radio, 4)

    # check for unexpected extra command byte
    c, a, l = struct.unpack(">BHB", hdr)
    if hdr[0:2] == "WW" and a != addr:
        # extra command byte detected
        # throw away the 1st byte and add the next byte in the buffer
        hdr = hdr[1:] + _rawrecv(radio, 1)

    # read 64 bytes (0x40) of data
    data = _rawrecv(radio, (BLOCK_SIZE))

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(hdr + data))

    c, a, l = struct.unpack(">BHB", hdr)
    if a != addr or l != length or c != ord("W"):
        _exit_program_mode(radio)
        LOG.error("Invalid answer for block 0x%04x:" % addr)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Unknown response from the radio")

    return data


def _do_ident(radio):
    """Put the radio in PROGRAM mode & identify it"""
    #  set the serial discipline
    radio.pipe.baudrate = 115200
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # flush input buffer
    _clean_buffer(radio)

    magic = "V66LINK"

    _rawsend(radio, magic)

    # Ok, get the ident string
    ident = _rawrecv(radio, 9)

    # check if ident is OK
    if ident != radio.IDENT:
        # bad ident
        msg = "Incorrect model ID, got this:"
        msg +=  util.hexprint(ident)
        LOG.debug(msg)
        raise errors.RadioError("Radio identification failed.")

    # DEBUG
    LOG.info("Positive ident, got this:")
    LOG.debug(util.hexprint(ident))

    return True


def _exit_program_mode(radio):
    endframe = "\x45"
    _rawsend(radio, endframe)


def _download(radio):
    """Get the memory map"""

    # put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = ""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        frame = _make_frame("R", addr, BLOCK_SIZE)
        # DEBUG
        LOG.info("Request sent:")
        LOG.debug(util.hexprint(frame))

        # sending the read request
        _rawsend(radio, frame)

        # now we read
        d = _recv(radio, addr)

        # aggregate the data
        data += d

        # UI Update
        status.cur = addr / BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)

    return data


def _upload(radio):
    """Upload procedure"""

    MEM_SIZE = 0x7000

    # put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the fun start here
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # sending the data
        data = radio.get_mmap()[addr:addr + BLOCK_SIZE]

        frame = _make_frame("W", addr, BLOCK_SIZE, data)

        _rawsend(radio, frame)

        # receiving the response
        ack = _rawrecv(radio, 1)
        if ack != "\x06":
            _exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        _check_for_double_ack(radio)

        # UI Update
        status.cur = addr / BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x6140:0x6148]

    #if rid in cls._fileid:
    if rid in cls.IDENT:
        return True

    return False


class VGCStyleRadio(chirp_common.CloneModeRadio,
                    chirp_common.ExperimentalRadio):
    """BTECH's UV-50X3"""
    VENDOR = "BTECH"
    _air_range = (108000000, 136000000)
    _vhf_range = (136000000, 174000000)
    _vhf2_range = (174000000, 250000000)
    _220_range = (222000000, 225000000)
    _gen1_range = (300000000, 400000000)
    _uhf_range = (400000000, 480000000)
    _gen2_range = (480000000, 520000000)
    _upper = 499
    MODEL = ""
    IDENT = ""

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('The UV-50X3 driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(dedent("""\
            Follow this instructions to download your info:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio
            4 - Do the download of your radio data
            """))
        rp.pre_upload = _(dedent("""\
            Follow this instructions to upload your info:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio
            4 - Do the upload of your radio data
            """))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = False
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
        rf.has_sub_devices = self.VARIANT == ""
        rf.valid_modes = MODES
        rf.valid_characters = VALID_CHARS
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
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = SKIP_VALUES
        rf.valid_name_length = NAME_LENGTH
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_bands = [self._air_range,
                          self._vhf_range,
                          self._vhf2_range,
                          self._220_range,
                          self._gen1_range,
                          self._uhf_range,
                          self._gen2_range]
        rf.memory_bounds = (0, self._upper)
        return rf

    def get_sub_devices(self):
        return [UV50X3Left(self._mmap), UV50X3Right(self._mmap)]

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
        self._mmap = memmap.MemoryMap(data)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            _upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

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

    def _memory_obj(self, suffix=""):
        return getattr(self._memobj, "%s_memory%s" % (self._vfo, suffix))

    def _name_obj(self, suffix=""):
        return getattr(self._memobj, "%s_names%s" % (self._vfo, suffix))

    def _scan_obj(self, suffix=""):
        return getattr(self._memobj, "%s_scanflags%s" % (self._vfo, suffix))

    def _used_obj(self, suffix=""):
        return getattr(self._memobj, "%s_usedflags%s" % (self._vfo, suffix))

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        bitpos = (1 << (number % 8))
        bytepos = (number / 8)

        _mem = self._memory_obj()[number]
        _names = self._name_obj()[number]
        _scn = self._scan_obj()[bytepos]
        _usd = self._used_obj()[bytepos]

        isused = bitpos & int(_usd)
        isscan = bitpos & int(_scn)

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if not isused:
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if _mem.get_raw()[4] == "\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX feq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset < 0:
                mem.offset = abs(offset)
                mem.duplex = "-"
            elif offset > 0:
                mem.offset = offset
                mem.duplex = "+"
            else:
                mem.offset = 0

        # skip
        if not isscan:
            mem.skip = "S"

        # name TAG of the channel
        mem.name = str(_names.name).strip("\xFF")

        # power
        mem.power = POWER_LEVELS[int(_mem.txp)]

        # wide/narrow
        mem.mode = MODES[int(_mem.wn)]

        # tone data
        rxtone = txtone = None
        txtone = self.decode_tone(_mem.txtone)
        rxtone = self.decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # Extra
        mem.extra = RadioSettingGroup("extra", "Extra")

        bcl = RadioSetting("bcl", "Busy channel lockout",
                              RadioSettingValueBoolean(bool(_mem.bcl)))
        mem.extra.append(bcl)

        revert = RadioSetting("revert", "Revert",
                              RadioSettingValueBoolean(bool(_mem.revert)))
        mem.extra.append(revert)

        dname = RadioSetting("dname", "Display name",
                             RadioSettingValueBoolean(bool(_mem.dname)))
        mem.extra.append(dname)

        return mem

    def set_memory(self, mem):
        """Set the memory data in the eeprom img from the UI"""
        bitpos = (1 << (mem.number % 8))
        bytepos = (mem.number / 8)

        _mem = self._memory_obj()[mem.number]
        _names = self._name_obj()[mem.number]
        _scn = self._scan_obj()[bytepos]
        _usd = self._used_obj()[bytepos]

        if mem.empty:
            _usd &= ~bitpos
            _scn &= ~bitpos
            _mem.set_raw("\xFF" * 16)
            _names.name = ("\xFF" * 6)
            return
        else:
            _usd |= bitpos

        # frequency
        _mem.rxfreq = mem.freq / 10

        # duplex
        if mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "off":
            for i in _mem.txfreq:
                i.set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        else:
            _mem.txfreq = mem.freq / 10

        # tone data
        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.txtone, txmode, txtone, txpol)
        self.encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        # name TAG of the channel
        _names.name = mem.name.ljust(6, "\xFF")

        # power level, # default power level is low
        _mem.txp = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        # wide/narrow
        _mem.wn = MODES.index(mem.mode)

        if mem.skip == "S":
            _scn &= ~bitpos
        else:
            _scn |= bitpos

        # autoset display to display name if filled
        if mem.extra:
            # mem.extra only seems to be populated when called from edit panel
            dname = mem.extra["dname"]
        else:
            dname = None
        if mem.name:
            _mem.dname = True
            if dname and not dname.changed():
                dname.value = True
        else:
            _mem.dname = False
            if dname and not dname.changed():
                dname.value = False

        # reseting unknowns, this has to be set by hand
        _mem.unknown0 = 0
        _mem.unknown1 = 0
        _mem.unknown2 = 0
        _mem.unknown3 = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                setattr(_mem, setting.get_name(), setting.value)
        else:
            # there are no extra settings, load defaults
            _mem.bcl = 0
            _mem.revert = 0
            _mem.dname = 1


    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) == MEM_SIZE:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False


@directory.register
class UV50X3(VGCStyleRadio):
    """BTech UV-50X3"""
    MODEL = "UV-50X3"
    IDENT = UV50X3_id


class UV50X3Left(UV50X3):
    VARIANT = "Left"
    _vfo = "left"


class UV50X3Right(UV50X3):
    VARIANT = "Right"
    _vfo = "right"
