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

import struct
import logging
import re

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings

LOG = logging.getLogger(__name__)

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
      scand:1,         // scan direction
      scanr:3;         // scan resume
  u8  rxexp:1,         // rx expansion
      ptt:1,           // ptt mode
      display:1,       // display select (frequency/clock)
      omode:1,         // operation mode
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

# Basic settings lists
LIST_AFTONE = ["Low-3", "Low-2", "Low-1", "Normal", "High-1", "High-2"]
LIST_SPKR = ["Off", "Front", "Rear", "Front + Rear"]
LIST_AUDIO = ["Monaural", "Stereo"]
LIST_SBMUTE = ["Off", "TX", "RX", "Both"]
LIST_MLNHM = ["Min", "Low", "Normal", "High", "Max"]
LIST_PTT = ["Momentary", "Toggle"]
LIST_RXEXP = ["General", "Wide coverage"]
LIST_VOX = ["Off", "Internal mic", "Front hand-mic", "Rear hand-mic"]
LIST_DISPLAY = ["Frequency", "Timer/Clock"]
LIST_MINMAX = ["Min"] + ["%s" % x for x in range(2, 8)] + ["Max"]
LIST_COLOR = ["White-Blue", "Sky-Blue", "Marine-Blue", "Green",
              "Yellow-Green", "Orange", "Amber", "White"]
LIST_BTIME = ["Continuous"] + ["%s" % x for x in range(1, 61)]
LIST_MRSCAN = ["All", "Selected"]
LIST_DWSTOP = ["Auto", "Hold"]
LIST_SCAND = ["Down", "Up"]
LIST_SCANR = ["Busy", "Hold", "1 sec", "3 sec", "5 sec"]
LIST_APO = ["Off", ".5", "1", "1.5"] + ["%s" % x for x in range(2, 13)]
LIST_BEEP = ["Off", "Low", "High"]
LIST_FKEY = ["MHz/AD-F", "AF Dual 1(line-in)", "AF Dual 2(AM)",
             "AF Dual 3(FM)", "PA", "SQL off", "T-call", "WX"]
LIST_PFKEY = ["Off", "SQL off", "TX power", "Scan", "RPT shift", "Reverse",
              "T-Call"]
LIST_AB = ["A", "B"]
LIST_COVERAGE = ["In band", "All"]
LIST_TOT = ["Off"] + ["%s" % x for x in range(5, 25, 5)] + ["30"]
LIST_DATEFMT = ["yyyy/mm/dd", "yyyy/dd/mm", "mm/dd/yyyy", "dd/mm/yyyy"]
LIST_TIMEFMT = ["24H", "12H"]
LIST_TZ = ["-12 INT DL W",
           "-11 MIDWAY",
           "-10 HAST",
           "-9 AKST",
           "-8 PST",
           "-7 MST",
           "-6 CST",
           "-5 EST",
           "-4:30 CARACAS",
           "-4 AST",
           "-3:30 NST",
           "-3 BRASILIA",
           "-2 MATLANTIC",
           "-1 AZORES",
           "-0 LONDON",
           "+0 LONDON",
           "+1 ROME",
           "+2 ATHENS",
           "+3 MOSCOW",
           "+3:30 REHRW",
           "+4 ABUDNABI",
           "+4:30 KABUL",
           "+5 ISLMABAD",
           "+5:30 NEWDELHI",
           "+6 DHAKA",
           "+6:30 YANGON",
           "+7 BANKOK",
           "+8 BEIJING",
           "+9 TOKYO",
           "+10 ADELAIDE",
           "+10 SYDNET",
           "+11 NWCLDNIA",
           "+12 FIJI",
           "+13 NUKALOFA"
           ]
LIST_BELL = ["Off", "1 time", "3 times", "5 times", "8 times", "Continuous"]
LIST_DATABND = ["Main band", "Sub band", "Left band-fixed", "Right band-fixed"]
LIST_DATASPD = ["1200 bps", "9600 bps"]
LIST_DATASQL = ["Busy/TX", "Busy", "TX"]

# Other settings lists
LIST_CPUCLK = ["Clock frequency 1", "Clock frequency 2"]

# Work mode settings lists
LIST_WORK = ["VFO", "Memory System"]
LIST_WBANDB = ["Air", "H-V", "GR1-V", "GR1-U", "H-U", "GR2"]
LIST_WBANDA = ["Line-in", "AM", "FM"] + LIST_WBANDB
LIST_SQL = ["Open"] + ["%s" % x for x in range(1, 10)]
_STEP_LIST = [2.5, 5., 6.25, 8.33, 9., 10., 12.5, 15., 20., 25., 50., 100.,
              200.]
LIST_STEP = ["Auto"] + ["{0:.2f} kHz".format(x) for x in _STEP_LIST]
LIST_SMODE = ["F-1", "F-2"]

# DTMF settings lists
LIST_TTDKEY = ["D code"] + ["Send delay %s s" % x for x in range(1, 17)]
LIST_TT200 = ["%s ms" % x for x in range(50, 210, 10)]
LIST_TT1000 = ["%s ms" % x for x in range(100, 1050, 50)]
LIST_TTSIG = ["Code squelch", "Select call"]
LIST_TTAUTORST = ["Off"] + ["%s s" % x for x in range(1, 16)]
LIST_TTGRPCODE = ["Off"] + list("ABCD*#")
LIST_TTINTCODE = DTMF_CHARS
LIST_TTALERT = ["Off", "Alert tone", "Transpond", "Transpond-ID code",
                "Transpond-transpond code"]
LIST_TTAUTOD = ["%s" % x for x in range(1, 10)]

# valid chars on the LCD
VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
    "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"

# Power Levels
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("Mid", watts=20),
                chirp_common.PowerLevel("High", watts=50)]

# B-TECH UV-50X3 id string
UV50X3_id = b"VGC6600MD"


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _check_for_double_ack(radio):
    radio.pipe.timeout = 0.005
    c = radio.pipe.read(1)
    radio.pipe.timeout = STIMEOUT
    if c and c != b'\x06':
        _exit_program_mode(radio)
        raise errors.RadioError('Expected nothing or ACK, got %r' % c)


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = b""
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
    """Pack the info in the header format"""
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
    if hdr[0:2] == b"WW" and a != addr:
        # extra command byte detected
        # throw away the 1st byte and add the next byte in the buffer
        hdr = hdr[1:] + _rawrecv(radio, 1)

    # read 64 bytes (0x40) of data
    data = _rawrecv(radio, (BLOCK_SIZE))

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(hdr + data))

    c, a, l = struct.unpack(">BHB", hdr)
    if a != addr or l != length or c != ord(b"W"):
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

    magic = b"V66LINK"

    _rawsend(radio, magic)

    # Ok, get the ident string
    ident = _rawrecv(radio, 9)

    # check if ident is OK
    if ident != radio.IDENT:
        # bad ident
        msg = "Incorrect model ID, got this:"
        msg += util.hexprint(ident)
        LOG.debug(msg)
        raise errors.RadioError("Radio identification failed.")

    # DEBUG
    LOG.info("Positive ident, got this:")
    LOG.debug(util.hexprint(ident))

    return True


def _exit_program_mode(radio):
    endframe = b"\x45"
    _rawsend(radio, endframe)


def _download(radio):
    """Get the memory map"""

    # put radio in program mode and identify it
    _do_ident(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = b""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        frame = _make_frame(b"R", addr, BLOCK_SIZE)
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
        status.cur = addr // BLOCK_SIZE
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
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the fun start here
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # sending the data
        data = radio.get_mmap()[addr:addr + BLOCK_SIZE]

        frame = _make_frame(b"W", addr, BLOCK_SIZE, data)

        _rawsend(radio, frame)

        # receiving the response
        ack = _rawrecv(radio, 1)
        if ack != b"\x06":
            _exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        _check_for_double_ack(radio)

        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x6140:0x6148]

    if rid in cls.IDENT:
        return True

    return False


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
        rp.pre_download = _(
            "Follow this instructions to download your info:\n"
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

    def get_features(self):
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
        rf.valid_tuning_steps = _STEP_LIST
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
        self._mmap = memmap.MemoryMapBytes(data)
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
        if val.get_raw(asbytes=False) == "\xFF\xFF":
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
        if _mem.get_raw(asbytes=False)[4] == "\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX feq set
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
        _names.name = mem.name.rstrip().ljust(6, "\xFF")

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

        # resetting unknowns, this has to be set by hand
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

    def _bbcd2dtmf(self, bcdarr, strlen=16):
        # doing bbcd, but with support for ABCD*#
        LOG.debug(bcdarr.get_value())
        string = ''.join("%02X" % b for b in bcdarr)
        LOG.debug("@_bbcd2dtmf, received: %s" % string)
        string = string.replace('E', '*').replace('F', '#')
        if strlen <= 16:
            string = string[:strlen]
        return string

    def _dtmf2bbcd(self, value):
        dtmfstr = value.get_value()
        dtmfstr = dtmfstr.replace('*', 'E').replace('#', 'F')
        dtmfstr = str.ljust(dtmfstr.strip(), 16, "F")
        bcdarr = list(bytearray.fromhex(dtmfstr))
        LOG.debug("@_dtmf2bbcd, sending: %s" % bcdarr)
        return bcdarr

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        other = RadioSettingGroup("other", "Other Settings")
        work = RadioSettingGroup("work", "Work Mode Settings")
        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        top = RadioSettings(basic, other, work, dtmf)

        # Basic

        # Audio: A01-A04

        aftone = RadioSetting(
            "settings.aftone", "AF tone control",
            RadioSettingValueList(
                LIST_AFTONE, current_index=_mem.settings.aftone))
        basic.append(aftone)

        spkr = RadioSetting(
            "settings.spkr", "Speaker",
            RadioSettingValueList(
                LIST_SPKR, current_index=_mem.settings.spkr))
        basic.append(spkr)

        audio = RadioSetting(
            "settings.audio", "Stereo/Mono",
            RadioSettingValueList(
                LIST_AUDIO, current_index=_mem.settings.audio))
        basic.append(audio)

        sbmute = RadioSetting(
            "settings.sbmute", "Sub band mute",
            RadioSettingValueList(
                LIST_SBMUTE, current_index=_mem.settings.sbmute))
        basic.append(sbmute)

        # TX/RX: B01-B08

        mgain = RadioSetting(
            "settings.mgain", "Mic gain",
            RadioSettingValueList(
                LIST_MLNHM, current_index=_mem.settings.mgain))
        basic.append(mgain)

        ptt = RadioSetting(
            "settings.ptt", "PTT mode",
            RadioSettingValueList(
                LIST_PTT, current_index=_mem.settings.ptt))
        basic.append(ptt)

        # B03 (per channel)
        # B04 (per channel)

        rxexp = RadioSetting(
            "settings.rxexp", "RX expansion",
            RadioSettingValueList(
                LIST_RXEXP, current_index=_mem.settings.rxexp))
        basic.append(rxexp)

        vox = RadioSetting(
            "settings.vox", "Vox",
            RadioSettingValueList(
                LIST_VOX, current_index=_mem.settings.vox))
        basic.append(vox)

        voxs = RadioSetting(
            "settings.voxs", "Vox sensitivity",
            RadioSettingValueList(
                LIST_MLNHM, current_index=_mem.settings.voxs))
        basic.append(voxs)

        # B08 (per channel)

        # Display: C01-C06

        display = RadioSetting(
            "settings.display", "Display select",
            RadioSettingValueList(
                LIST_DISPLAY, current_index=_mem.settings.display))
        basic.append(display)

        lcdb = RadioSetting(
            "settings.lcdb", "LCD brightness",
            RadioSettingValueList(
                LIST_MINMAX, current_index=_mem.settings.lcdb))
        basic.append(lcdb)

        color = RadioSetting(
            "settings.color", "LCD color",
            RadioSettingValueList(
                LIST_COLOR, current_index=_mem.settings.color))
        basic.append(color)

        lcdc = RadioSetting(
            "settings.lcdc", "LCD contrast",
            RadioSettingValueList(
                LIST_MINMAX, current_index=_mem.settings.lcdc))
        basic.append(lcdc)

        btime = RadioSetting(
            "settings.btime", "LCD backlight time",
            RadioSettingValueList(
                LIST_BTIME, current_index=_mem.settings.btime))
        basic.append(btime)

        keyb = RadioSetting(
            "settings.keyb", "Key brightness",
            RadioSettingValueList(
                LIST_MINMAX, current_index=_mem.settings.keyb))
        basic.append(keyb)

        # Memory: D01-D04

        # D01 (per channel)
        # D02 (per channel)

        mrscan = RadioSetting(
            "settings.mrscan", "Memory scan type",
            RadioSettingValueList(
                LIST_MRSCAN, current_index=_mem.settings.mrscan))
        basic.append(mrscan)

        # D04 (per channel)

        # Scan: E01-E04

        dwstop = RadioSetting(
            "settings.dwstop", "Dual watch stop",
            RadioSettingValueList(
                LIST_DWSTOP, current_index=_mem.settings.dwstop))
        basic.append(dwstop)

        scand = RadioSetting(
            "settings.scand", "Scan direction",
            RadioSettingValueList(
                LIST_SCAND, current_index=_mem.settings.scand))
        basic.append(scand)

        scanr = RadioSetting(
            "settings.scanr", "Scan resume",
            RadioSettingValueList(
                LIST_SCANR, current_index=_mem.settings.scanr))
        basic.append(scanr)

        scansb = RadioSetting("settings.scansb", "Scan stop beep",
                              RadioSettingValueBoolean(_mem.settings.scansb))
        basic.append(scansb)

        # System: F01-F09

        apo = RadioSetting(
            "settings.apo", "Automatic power off [hours]",
            RadioSettingValueList(
                LIST_APO, current_index=_mem.settings.apo))
        basic.append(apo)

        ars = RadioSetting("settings.ars", "Automatic repeater shift",
                           RadioSettingValueBoolean(_mem.settings.ars))
        basic.append(ars)

        beep = RadioSetting(
            "settings.beep", "Beep volume",
            RadioSettingValueList(
                LIST_BEEP, current_index=_mem.settings.beep))
        basic.append(beep)

        fkey = RadioSetting(
            "settings.fkey", "F key",
            RadioSettingValueList(
                LIST_FKEY, current_index=_mem.settings.fkey))
        basic.append(fkey)

        pfkey1 = RadioSetting(
            "settings.pfkey1", "Mic P1 key",
            RadioSettingValueList(
                LIST_PFKEY, current_index=_mem.settings.pfkey1))
        basic.append(pfkey1)

        pfkey2 = RadioSetting(
            "settings.pfkey2", "Mic P2 key",
            RadioSettingValueList(
                LIST_PFKEY, current_index=_mem.settings.pfkey2))
        basic.append(pfkey2)

        pfkey3 = RadioSetting(
            "settings.pfkey3", "Mic P3 key",
            RadioSettingValueList(
                LIST_PFKEY, current_index=_mem.settings.pfkey3))
        basic.append(pfkey3)

        pfkey4 = RadioSetting(
            "settings.pfkey4", "Mic P4 key",
            RadioSettingValueList(
                LIST_PFKEY, current_index=_mem.settings.pfkey4))
        basic.append(pfkey4)

        omode = RadioSetting(
            "settings.omode", "Operation mode",
            RadioSettingValueList(
                LIST_AB, current_index=_mem.settings.omode))
        basic.append(omode)

        rxcoverm = RadioSetting(
            "settings.rxcoverm", "RX coverage - memory",
            RadioSettingValueList(
                LIST_COVERAGE, current_index=_mem.settings.rxcoverm))
        basic.append(rxcoverm)

        rxcoverv = RadioSetting(
            "settings.rxcoverv", "RX coverage - VFO",
            RadioSettingValueList(
                LIST_COVERAGE, current_index=_mem.settings.rxcoverv))
        basic.append(rxcoverv)

        tot = RadioSetting(
            "settings.tot", "Time out timer [min]",
            RadioSettingValueList(
                LIST_TOT, current_index=_mem.settings.tot))
        basic.append(tot)

        # Timer/Clock: G01-G04

        # G01
        datefmt = RadioSetting(
            "settings.datefmt", "Date format",
            RadioSettingValueList(
                LIST_DATEFMT, current_index=_mem.settings.datefmt))
        basic.append(datefmt)

        timefmt = RadioSetting(
            "settings.timefmt", "Time format",
            RadioSettingValueList(
                LIST_TIMEFMT, current_index=_mem.settings.timefmt))
        basic.append(timefmt)

        timesig = RadioSetting("settings.timesig", "Time signal",
                               RadioSettingValueBoolean(_mem.settings.timesig))
        basic.append(timesig)

        tz = RadioSetting("settings.tz", "Time zone",
                          RadioSettingValueList(
                              LIST_TZ, current_index=_mem.settings.tz))
        basic.append(tz)

        # Signaling: H01-H06

        bell = RadioSetting(
            "settings.bell", "Bell ringer",
            RadioSettingValueList(
                LIST_BELL, current_index=_mem.settings.bell))
        basic.append(bell)

        # H02 (per channel)

        dtmfmodenc = RadioSetting("settings.dtmfmodenc", "DTMF mode encode",
                                  RadioSettingValueBoolean(
                                      _mem.settings.dtmfmodenc))
        basic.append(dtmfmodenc)

        dtmfmoddec = RadioSetting("settings.dtmfmoddec", "DTMF mode decode",
                                  RadioSettingValueBoolean(
                                      _mem.settings.dtmfmoddec))
        basic.append(dtmfmoddec)

        # H04 (per channel)

        decbandsel = RadioSetting(
            "settings.decbandsel", "DTMF band select",
            RadioSettingValueList(
                LIST_AB, current_index=_mem.settings.decbandsel))
        basic.append(decbandsel)

        sqlexp = RadioSetting("settings.sqlexp", "SQL expansion",
                              RadioSettingValueBoolean(_mem.settings.sqlexp))
        basic.append(sqlexp)

        # Pkt: I01-I03

        databnd = RadioSetting(
            "settings.databnd", "Packet data band",
            RadioSettingValueList(
                LIST_DATABND, current_index=_mem.settings.databnd))
        basic.append(databnd)

        dataspd = RadioSetting(
            "settings.dataspd", "Packet data speed",
            RadioSettingValueList(
                LIST_DATASPD, current_index=_mem.settings.dataspd))
        basic.append(dataspd)

        datasql = RadioSetting(
            "settings.datasql", "Packet data squelch",
            RadioSettingValueList(
                LIST_DATASQL, current_index=_mem.settings.datasql))
        basic.append(datasql)

        # Other

        dw = RadioSetting("settings.dw", "Dual watch",
                          RadioSettingValueBoolean(_mem.settings.dw))
        other.append(dw)

        cpuclk = RadioSetting(
            "settings.cpuclk", "CPU clock frequency",
            RadioSettingValueList(
                LIST_CPUCLK, current_index=_mem.settings.cpuclk))
        other.append(cpuclk)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in VALID_CHARS:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        line16 = RadioSetting("poweron_msg.line16", "Power-on message",
                              RadioSettingValueString(0, 16, _filter(
                                  _mem.poweron_msg.line16)))
        other.append(line16)

        line32 = RadioSetting("embedded_msg.line32", "Embedded message",
                              RadioSettingValueString(0, 32, _filter(
                                  _mem.embedded_msg.line32)))
        other.append(line32)

        # Work

        workmoda = RadioSetting(
            "settings.workmoda", "Work mode A",
            RadioSettingValueList(
                LIST_WORK, current_index=_mem.settings.workmoda))
        work.append(workmoda)

        workmodb = RadioSetting(
            "settings.workmodb", "Work mode B",
            RadioSettingValueList(
                LIST_WORK, current_index=_mem.settings.workmodb))
        work.append(workmodb)

        wbanda = RadioSetting(
            "settings.wbanda", "Work band A",
            RadioSettingValueList(
                LIST_WBANDA, current_index=(_mem.settings.wbanda) - 1))
        work.append(wbanda)

        wbandb = RadioSetting(
            "settings.wbandb", "Work band B",
            RadioSettingValueList(
                LIST_WBANDB, current_index=(_mem.settings.wbandb) - 4))
        work.append(wbandb)

        sqla = RadioSetting(
            "settings.sqla", "Squelch A",
            RadioSettingValueList(
                LIST_SQL, current_index=_mem.settings.sqla))
        work.append(sqla)

        sqlb = RadioSetting(
            "settings.sqlb", "Squelch B",
            RadioSettingValueList(
                LIST_SQL, current_index=_mem.settings.sqlb))
        work.append(sqlb)

        stepa = RadioSetting(
            "settings.stepa", "Auto step A",
            RadioSettingValueList(
                LIST_STEP, current_index=_mem.settings.stepa))
        work.append(stepa)

        stepb = RadioSetting(
            "settings.stepb", "Auto step B",
            RadioSettingValueList(
                LIST_STEP, current_index=_mem.settings.stepb))
        work.append(stepb)

        mrcha = RadioSetting("settings.mrcha", "Current channel A",
                             RadioSettingValueInteger(0, 499,
                                                      _mem.settings.mrcha))
        work.append(mrcha)

        mrchb = RadioSetting("settings.mrchb", "Current channel B",
                             RadioSettingValueInteger(0, 499,
                                                      _mem.settings.mrchb))
        work.append(mrchb)

        val = _mem.settings.offseta / 100.00
        offseta = RadioSetting("settings.offseta", "Offset A (0-37.95)",
                               RadioSettingValueFloat(0, 38.00, val, 0.05, 2))
        work.append(offseta)

        val = _mem.settings.offsetb / 100.00
        offsetb = RadioSetting("settings.offsetb", "Offset B (0-79.95)",
                               RadioSettingValueFloat(0, 80.00, val, 0.05, 2))
        work.append(offsetb)

        wpricha = RadioSetting("settings.wpricha", "Priority channel A",
                               RadioSettingValueInteger(0, 499,
                                                        _mem.settings.wpricha))
        work.append(wpricha)

        wprichb = RadioSetting("settings.wprichb", "Priority channel B",
                               RadioSettingValueInteger(0, 499,
                                                        _mem.settings.wprichb))
        work.append(wprichb)

        smode = RadioSetting(
            "settings.smode", "Smart function mode",
            RadioSettingValueList(
                LIST_SMODE, current_index=_mem.settings.smode))
        work.append(smode)

        # dtmf

        ttdkey = RadioSetting(
            "dtmf.ttdkey", "D key function",
            RadioSettingValueList(
                LIST_TTDKEY, current_index=_mem.dtmf.ttdkey))
        dtmf.append(ttdkey)

        ttdgt = RadioSetting(
            "dtmf.ttdgt", "Digit time",
            RadioSettingValueList(
                LIST_TT200, current_index=(_mem.dtmf.ttdgt) - 5))
        dtmf.append(ttdgt)

        ttint = RadioSetting(
            "dtmf.ttint", "Interval time",
            RadioSettingValueList(
                LIST_TT200, current_index=(_mem.dtmf.ttint) - 5))
        dtmf.append(ttint)

        tt1stdgt = RadioSetting(
            "dtmf.tt1stdgt", "1st digit time",
            RadioSettingValueList(
                LIST_TT200, current_index=(_mem.dtmf.tt1stdgt) - 5))
        dtmf.append(tt1stdgt)

        tt1stdly = RadioSetting(
            "dtmf.tt1stdly", "1st digit delay time",
            RadioSettingValueList(
                LIST_TT1000, current_index=(_mem.dtmf.tt1stdly) - 2))
        dtmf.append(tt1stdly)

        ttdlyqt = RadioSetting(
            "dtmf.ttdlyqt", "Digit delay when use qt",
            RadioSettingValueList(
                LIST_TT1000, current_index=(_mem.dtmf.ttdlyqt) - 2))
        dtmf.append(ttdlyqt)

        ttsig = RadioSetting(
            "dtmf2.ttsig", "Signal",
            RadioSettingValueList(
                LIST_TTSIG, current_index=_mem.dtmf2.ttsig))
        dtmf.append(ttsig)

        ttautorst = RadioSetting(
            "dtmf2.ttautorst", "Auto reset time",
            RadioSettingValueList(
                LIST_TTAUTORST, current_index=_mem.dtmf2.ttautorst))
        dtmf.append(ttautorst)

        if _mem.dtmf2.ttgrpcode > 0x06:
            val = 0x00
        else:
            val = _mem.dtmf2.ttgrpcode
        ttgrpcode = RadioSetting("dtmf2.ttgrpcode", "Group code",
                                 RadioSettingValueList(LIST_TTGRPCODE,
                                                       current_index=val))
        dtmf.append(ttgrpcode)

        ttintcode = RadioSetting(
            "dtmf2.ttintcode", "Interval code",
            RadioSettingValueList(
                LIST_TTINTCODE, current_index=_mem.dtmf2.ttintcode))
        dtmf.append(ttintcode)

        if _mem.dtmf2.ttalert > 0x04:
            val = 0x00
        else:
            val = _mem.dtmf2.ttalert
        ttalert = RadioSetting("dtmf2.ttalert", "Alert tone/transpond",
                               RadioSettingValueList(LIST_TTALERT,
                                                     current_index=val))
        dtmf.append(ttalert)

        ttautod = RadioSetting(
            "dtmf.ttautod", "Auto dial group",
            RadioSettingValueList(
                LIST_TTAUTOD, current_index=_mem.dtmf.ttautod))
        dtmf.append(ttautod)

        # setup 9 dtmf autodial entries
        for i in map(str, list(range(1, 10))):
            objname = "code" + i
            strname = "Code " + str(i)
            dtmfsetting = getattr(_mem.dtmfcode, objname)
            dtmflen = getattr(_mem.dtmfcode, objname + "_len")
            dtmfstr = self._bbcd2dtmf(dtmfsetting, dtmflen)
            code = RadioSettingValueString(0, 16, dtmfstr)
            code.set_charset(DTMF_CHARS + list(" "))
            rs = RadioSetting("dtmfcode." + objname, strname, code)
            dtmf.append(rs)
        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
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
                    elif setting == "line16":
                        setattr(obj, setting, str(element.value).rstrip(
                            " ").ljust(16, "\xFF"))
                    elif setting == "line32":
                        setattr(obj, setting, str(element.value).rstrip(
                            " ").ljust(32, "\xFF"))
                    elif setting == "wbanda":
                        setattr(obj, setting, int(element.value) + 1)
                    elif setting == "wbandb":
                        setattr(obj, setting, int(element.value) + 4)
                    elif setting in ["offseta", "offsetb"]:
                        val = element.value
                        value = int(val.get_value() * 100)
                        setattr(obj, setting, value)
                    elif setting in ["ttdgt", "ttint", "tt1stdgt"]:
                        setattr(obj, setting, int(element.value) + 5)
                    elif setting in ["tt1stdly", "ttdlyqt"]:
                        setattr(obj, setting, int(element.value) + 2)
                    elif re.match(r'code\d', setting):
                        # set dtmf length field and then get bcd dtmf
                        dtmfstrlen = len(str(element.value).strip())
                        setattr(_mem.dtmfcode, setting + "_len", dtmfstrlen)
                        dtmfstr = self._dtmf2bbcd(element.value)
                        setattr(_mem.dtmfcode, setting, dtmfstr)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

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
