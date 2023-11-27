# Version 1.0 for TYT-TH8600
# Initial radio protocol decode, channels and memory layout, basic settings
# by Andy Knitt <andyknitt@gmail.com>, Summer 2023
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
# along with this program.

import struct
import logging
import math
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct chns {
  ul32 rxfreq;
  ul32 txfreq;
  ul16 rxtone;
  ul16 txtone;

  u8 power:2,          // High=00,Mid=01,Low=10
     mode:2,          //  WFM=00, FM=01, NFM=10
     b_lock:2,         // off=00, sub=01, carrier=10
     REV:1,
     TxInh:1;
  u8 sqlmode:3,         // SQ=000, CT=001, Tone=010,
                       //CT or Tone=011, CTC and Tone=100
     signal:2,          // off=00, dtmf=01, 2-tone=10, 5-tone=11
     display: 1,
     talkoff: 1,
     TBD: 1;
  u8 fivetonepttid: 2,  //off=00, begin=01,end=10,both=11
     dtmfpttid: 2,      //off=00, begin=01,end=10,both=11
     tuning_step: 4;   //
  u8 name[6];
};

struct chname {
  u8  extra_name[10];
};

#seekto 0x0000;
struct chns chan_mem[200];
struct chns scanlimits[4];
struct chns vfos[6];

#seekto 0x1960;
struct chname chan_name[200];

#seekto 0x1160;
struct {
  u8 introScreen1[12];    // 0x1160 *Intro Screen Line 1(truncated to 12 alpha
                          //         text characters)
  u8 unk_bit9 : 1,        // 0x116C
     subDisplay : 2,      //   0b00 = OFF; 0b01 = frequency; 0b10 = voltage
     unk_bit8 : 1,        //
     sqlLevel : 4;        //        *OFF, 1-9
  u8 beep : 1,            // 0x116D *OFF, On
     burstFreq : 2,       //        1750,2100,1000,1450 Hz tone burst frequency
     unkstr4: 4,          //
     txChSelect : 1;      //        *Last CH, Main CH
  u8 unk_bit7 : 1,        // 0x116E
     autoPowOff : 2,      //        OFF, 30Min, 1HR, 2HR
     tot : 5;             //        OFF, time in minutes (1 to 30)
  u8 pttRelease: 2,       // 0x116F  OFF, Begin, After, Both
     unk_bit6: 2,         //
     sqlTailElim: 2,      //        OFF, Frequency, No Frequency
     disableReset:1,      //        NO, YES
     menuOperation:1;     //        NO, YES
  u8 scanResumeTime : 2,  // 0x1170 2S, 5S, 10S, 15S
     disMode : 2,         //        Frequency, Channel, Name
     scanType: 2,         //        Time operated, Carrier operated, Se
     ledMode: 2;          //        On, 5 second, 10 second
  u8 unky;                // 0x1171
  u8 usePowerOnPw : 1,    // 0x1172 NO, YES
     elimTailNoTone: 1,   //        NO, YES
     unk6 : 6;            //
  u8 unk;                 // 0x1173
  u8 unk_bit5 : 1,        // 0x1174
     mzKeyFunc : 3,      //   A/B, Low, Monitor, Scan, Tone, M/V, MHz, Mute
     unk_bit4 : 1,        //
     lowKeyFunc : 3;      //   A/B, Low, Monitor, Scan, Tone, M/V, MHz, Mute
  u8 unk_bit3 : 1,        // 0x1175
     vmKeyFunc : 3,       //   A/B, Low, Monitor, Scan, Tone, M/V, MHz, Mute
     unk_bit2 : 1,        //
     ctKeyFunc : 3;       //   A/B, Low, Monitor,
                          //   Scan, Tone, M/V, MHz, Mute
  u8 abKeyFunc : 3,       // 0x1176  A/B, Low, Monitor,
                          //         Scan, Tone, M/V, MHz, Mute
     unk_bit1 : 1,        //
     volume : 4;          //         0 to 15
  u8 unk3 : 3,            // 0x1177
     introScreen : 2,     //      OFF, Picture, Character String
     unk_bits : 3;        //
  u8 unk4;                // 0x1178
  u8 unk5;                // 0x1179
  u8 powerOnPw[6];        // 0x117A  6 ASCII characters
} basicsettings;

#seekto 0x1180;
struct {
  u8 bitmap[26];    // one bit for each channel marked in use
} chan_avail;

#seekto 0x11A0;
struct {
  u8 bitmap[26];    // one bit for each channel; 0 = skip; 1 = dont skip
} chan_skip;

#seekto 0x1680;
ul32 rx_freq_limit_low_vhf;
ul32 rx_freq_limit_high_vhf;
ul32 tx_freq_limit_low_vhf;
ul32 tx_freq_limit_high_vhf;
ul32 rx_freq_limit_low_220;   //not supported by radio - always 0xFFFFFFFF
ul32 rx_freq_limit_high_220;  //not supported by radio - always 0xFFFFFFFF
ul32 tx_freq_limit_low_220;   //not supported by radio - always 0xFFFFFFFF
ul32 tx_freq_limit_high_220;  //not supported by radio - always 0xFFFFFFFF
ul32 rx_freq_limit_low_uhf;
ul32 rx_freq_limit_high_uhf;
ul32 tx_freq_limit_low_uhf;
ul32 tx_freq_limit_high_uhf;

#seekto 0x1940;
struct {
  u8 introLine1[16];    // 16 ASCII characters
  u8 introLine2[16];    // 16 ASCII characters
} intro_lines;
"""

MEM_SIZE = 0x2400
BLOCK_SIZE = 0x20
STIMEOUT = 2
BAUDRATE = 9600

# Channel power: 3 levels
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=25.00),
                chirp_common.PowerLevel("Mid", watts=10.00),
                chirp_common.PowerLevel("Low", watts=5.00)]
B_LOCK_LIST = ["OFF", "Sub", "Carrier"]
OPTSIG_LIST = ["OFF", "DTMF", "2TONE", "5TONE"]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
STEPS = [2.5, 5.0, 6.25, 7.5, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0]
LIST_STEPS = [str(x) for x in STEPS]
# In the context of SQL_MODES, 'Tone' refers to 2tone, 5tone, or DTMF
# signalling while "CT" refers to CTCSS and DTCS
SQL_MODES = ["SQ", "CT", "Tone", "CT or Tone", "CT and Tone"]
SPECIAL_CHANS = ("L1", "U1",
                 "L2", "U2",
                 "VFOA_VHF", "VFOA_UHF",
                 "VFOB_VHF", "VFOB_UHF")


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
    except Exception:
        _exit_program_mode(radio)
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if len(data) != amount:
        _exit_program_mode(radio)
        msg = "Error reading from radio: not the amount of data we want."
        raise errors.RadioError(msg)

    return data


def _rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        radio.pipe.write(data)
    except Exception:
        raise errors.RadioError("Error sending data to radio")


def _make_read_frame(addr, length):
    frame = b"\xFE\xFE\xEE\xEF\xEB"
    """Pack the info in the header format"""
    frame += bytes(f'{addr:X}'.zfill(4), 'utf-8')
    frame += bytes(f'{length:X}'.zfill(2), 'utf-8')
    frame += b"\xFD"
    # Return the data
    return frame


def _make_write_frame(addr, length, data=""):
    frame = b"\xFE\xFE\xEE\xEF\xE4"
    """Pack the info in the header format"""
    output = struct.pack(">HB", addr, length)
    # Add the data if set
    if len(data) != 0:
        output += data
    # Convert to ASCII
    converted_data = b''
    for b in output:
        converted_data += bytes(f'{b:X}'.zfill(2), 'utf-8')
    frame += converted_data
    """Unlike other TYT models, the frame header is
       not included in the checksum calc"""
    cs_byte = _calculate_checksum(data)
    # convert checksum to ASCII
    converted_checksum = bytes(f'{cs_byte[0]:X}'.zfill(2), 'utf-8')
    frame += converted_checksum
    frame += b"\xFD"
    # Return the data
    return frame


def _calculate_checksum(data):
    num = 0
    for x in range(0, len(data)):
        num = (num + data[x]) % 256

    if num == 0:
        return bytes([0])

    return bytes([256 - num])


def _recv(radio, addr, length):
    """Get data from the radio """

    data = _rawrecv(radio, length)

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(data))

    return data


def _do_ident(radio):
    """Put the radio in PROGRAM mode & identify it"""
    radio.pipe.baudrate = BAUDRATE
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # Flush input buffer
    _clean_buffer(radio)

    # Ident radio
    magic = radio._magic0
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 36)
    if not ack.startswith(radio._fingerprint) or not ack.endswith(b"\xFD"):
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond as expected (A)")

    return True


def _exit_program_mode(radio):
    # This may be the last part of a read
    magic = radio._magic5
    _rawsend(radio, magic)
    _clean_buffer(radio)


def _download(radio):
    """Get the memory map"""

    # Put radio in program mode and identify it
    _do_ident(radio)

    # Enter read mode
    magic = radio._magic2
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 7)
    if ack != b"\xFE\xFE\xEF\xEE\xE6\x00\xFD":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to enter read mode")

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = b""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        frame = _make_read_frame(addr, BLOCK_SIZE)
        # DEBUG
        LOG.debug("Frame=" + util.hexprint(frame))

        # Sending the read request
        _rawsend(radio, frame)

        # Now we read data
        d = _recv(radio, addr, BLOCK_SIZE*2 + 14)

        LOG.debug("Response Data= " + util.hexprint(d))

        if not d.startswith(b"\xFE\xFE\xEF\xEE\xE4"):
            LOG.warning("Incorrect start")
        if not d.endswith(b"\xFD"):
            LOG.warning("Incorrect end")
        # validate the block data with checksum
        # HEADER IS NOT INCLUDED IN CHECKSUM CALC, UNLIKE OTHER TYT MODELS
        protected_data = d[5:-3]
        received_checksum = d[-3:-1]
        # unlike some other TYT models, the data protected by checksum
        # is sent over the wire in ASCII format.  Need to convert ASCII
        # to integers to perform the checksum calculation, which uses
        # the same algorithm as other TYT models.
        converted_data = b''
        for i in range(0, len(protected_data), 2):
            int_data = int(protected_data[i:i+2].decode('utf-8'), 16)
            converted_data += int_data.to_bytes(1, 'big')
        cs_byte = _calculate_checksum(converted_data)
        # checksum is sent over the wire as ASCII characters, so convert
        # the calculated value before checking against what was received
        converted_checksum = bytes(f'{cs_byte[0]:X}'.zfill(2), 'utf-8')
        if received_checksum != converted_checksum:
            LOG.warning("Incorrect checksum received")
        # Strip out header, addr, length, checksum,
        # eof and then aggregate the remaining data
        ascii_data = d[11:-3]
        if len(ascii_data) % 2 != 0:
            LOG.error("Invalid data length")
        converted_data = b''
        for i in range(0, len(ascii_data), 2):
            # LOG.debug(ascii_data[i] + ascii_data[i+1])
            int_data = int(ascii_data[i:i+2].decode('utf-8'), 16)
            converted_data += int_data.to_bytes(1, 'big')
        data += converted_data

        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)

    return data


def _upload(radio):
    """Upload procedure"""
    # Put radio in program mode and identify it
    _do_ident(radio)

    magic = radio._magic3
    _rawsend(radio, magic)
    ack = _rawrecv(radio, 7)
    if ack != b"\xFE\xFE\xEF\xEE\xE6\x00\xFD":
        _exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to enter write mode")

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # The fun starts here
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # Official programmer skips writing these memory locations
        if addr >= 0x1680 and addr < 0x1940:
            continue

        # Sending the data
        data = radio.get_mmap()[addr:addr + BLOCK_SIZE]

        frame = _make_write_frame(addr, BLOCK_SIZE, data)
        LOG.warning("Frame:%s:" % util.hexprint(frame))
        _rawsend(radio, frame)

        ack = _rawrecv(radio, 7)
        LOG.debug("Response Data= " + util.hexprint(ack))

        if not ack.startswith(b"\xFE\xFE\xEF\xEE\xE6\x00\xFD"):
            LOG.warning("Unexpected response")
            _exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

    _exit_program_mode(radio)


def _do_map(chn, sclr, mary):
    """Set or Clear the chn (0-199) bit in mary[] word array map"""
    # chn is 1-based channel, sclr:1 = set, 0= = clear, 2= return state
    # mary[] is u8 array, but the map is by nibbles
    ndx = int(math.floor((chn) / 8))
    bv = (chn) % 8
    msk = 1 << bv
    mapbit = sclr
    if sclr == 1:    # Set the bit
        mary[ndx] = mary[ndx] | msk
    elif sclr == 0:  # clear
        mary[ndx] = mary[ndx] & (~ msk)     # ~ is complement
    else:       # return current bit state
        mapbit = 0
        if (mary[ndx] & msk) > 0:
            mapbit = 1
    return mapbit


@directory.register
class TH8600Radio(chirp_common.CloneModeRadio):
    """TYT TH8600 Radio"""

    VENDOR = "TYT"
    MODEL = "TH-8600"
    NEEDS_COMPAT_SERIAL = False
    MODES = ['WFM', 'FM', 'NFM']
    sql_modeS = ("", "Tone", "TSQL", "DTCS", "Cross")
    TONES = chirp_common.TONES
    DTCS_CODES = chirp_common.DTCS_CODES
    NAME_LENGTH = 6
    DTMF_CHARS = list("0123456789ABCD*#")
    # 136-174, 400-480
    VALID_BANDS = [(136000000, 174000001), (400000000, 480000001)]
    # Valid chars on the LCD
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "`!\"#$%&'()*+,-./:;<=>?@[]^_"

    _magic0 = b"\xFE\xFE\xEE\xEF\xE0\x26\x98\x00\x00\xFD"
    _magic2 = b"\xFE\xFE\xEE\xEF\xE2\x26\x98\x00\x00\xFD"
    _magic3 = b"\xFE\xFE\xEE\xEF\xE3\x26\x98\x00\x00\xFD"
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5\x26\x98\x00\x00\xFD"
    _fingerprint = b"\xFE\xFE\xEF\xEE\xE1\x26\x98\x00\x00\x31\x31\x31\x31" \
                   b"\x31\x31\x31\x31\x31\x31\x31\x31\x31\x31\x31\x31\x31" \
                   b"\x31\x31\x31\x34\x33\x34\x45"

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = \
            (cls.VENDOR + ' ' + cls.MODEL + '\n')

        rp.pre_download = _(
            "This is an early stage beta driver\n")
        rp.pre_upload = _(
            "This is an early stage beta driver - upload at your own risk\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_bank_index = False
        rf.has_bank_names = False
        rf.has_comment = False
        rf.has_tuning_step = True
        rf.valid_tuning_steps = STEPS
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_sub_devices = False
        rf.has_infinite_number = False
        rf.has_nostep_tuning = False
        rf.has_variable_power = False
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->", "->DTCS",
                                "Tone->DTCS", "DTCS->Tone", "->Tone",
                                "DTCS->DTCS"]
        rf.valid_skips = []
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_dtcs_codes = chirp_common.DTCS_CODES
        rf.valid_bands = self.VALID_BANDS
        rf.valid_special_chans = SPECIAL_CHANS
        rf.memory_bounds = (0, 199)
        rf.valid_skips = ["", "S"]
        return rf

    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
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
        except Exception:
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

    def set_memory(self, memory):
        """A value in a UI column for chan 'number' has been modified."""
        # update all raw channel memory values (_mem) from UI (mem)
        if memory.number >= 200 and memory.number < 204:
            _mem = self._memobj.scanlimits[memory.number-200]
            _name = None
        elif memory.number >= 204:
            _mem = self._memobj.vfos[memory.number-204]
            _name = None
        else:
            _mem = self._memobj.chan_mem[memory.number]
            _name = self._memobj.chan_name[memory.number]
            _mem.set_raw("\x00" * 21)
            if memory.empty:
                _do_map(memory.number, 0, self._memobj.chan_avail.bitmap)
                return
            else:
                _do_map(memory.number, 1, self._memobj.chan_avail.bitmap)

            if memory.skip == "":
                _do_map(memory.number, 1, self._memobj.chan_skip.bitmap)
            else:
                _do_map(memory.number, 0, self._memobj.chan_skip.bitmap)

        return self._set_memory(memory, _mem, _name)

    def get_memory(self, number):

        mem = chirp_common.Memory()
        mem.number = number
        # Get a low-level memory object mapped to the image
        if isinstance(number, str) or number >= 200:
            # mem.number = -10 + SPECIAL_CHANS.index(number)
            if number == 'L1' or number == 200:
                _mem = self._memobj.scanlimits[0]
                _name = None
                mem.number = 200
                mem.extd_number = 'L1'
            elif number == 'U1' or number == 201:
                _mem = self._memobj.scanlimits[1]
                _name = None
                mem.number = 201
                mem.extd_number = 'U1'
            elif number == 'L2' or number == 202:
                _mem = self._memobj.scanlimits[2]
                _name = None
                mem.number = 202
                mem.extd_number = 'L2'
            elif number == 'U2' or number == 203:
                _mem = self._memobj.scanlimits[3]
                _name = None
                mem.number = 203
                mem.extd_number = 'U2'
            elif number == 'VFOA_VHF' or number == 204:
                _mem = self._memobj.vfos[0]
                mem.number = 204
                mem.extd_number = 'VFOA_VHF'
                _name = None
            elif number == 'VFOA_220' or number == 205:
                _mem = self._memobj.vfos[1]
                _name = None
                mem.number = 205
            elif number == 'VFOA_UHF' or number == 206:
                _mem = self._memobj.vfos[2]
                mem.number = 206
                mem.extd_number = 'VFOA_UHF'
                _name = None
            elif number == 'VFOB_VHF' or number == 207:
                _mem = self._memobj.vfos[3]
                mem.number = 207
                mem.extd_number = 'VFOB_VHF'
                _name = None
                mem.extd_number = 'VFOA_220'
            elif number == 'VFOB_220' or number == 208:
                _mem = self._memobj.vfos[4]
                _name = None
                mem.number = 208
                mem.extd_number = 'VFOB_220'
            elif number == 'VFOB_UHF' or number == 209:
                _mem = self._memobj.vfos[5]
                mem.number = 209
                mem.extd_number = 'VFOB_UHF'
                _name = None
        else:
            mem.number = number  # Set the memory number
            _mem = self._memobj.chan_mem[number]
            _name = self._memobj.chan_name[number]
            # Determine if channel is empty

            if _do_map(mem.number, 2, self._memobj.chan_avail.bitmap) == 0:
                mem.empty = True
                return mem

            if _do_map(mem.number, 2, self._memobj.chan_skip.bitmap) == 1:
                mem.skip = ""
            else:
                mem.skip = "S"

        return self._get_memory(mem, _mem, _name)

    def _get_memory(self, mem, _mem, _name):
        """Convert raw channel memory data into UI columns"""
        mem.extra = RadioSettingGroup("Extra", "extra")

        mem.empty = False
        # This function process both 'normal' and Freq up/down' entries
        mem.freq = int(_mem.rxfreq) * 10

        if _mem.txfreq == 0xFFFFFFFF:
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 25000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) \
                and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.name = ""
        for i in range(6):   # 0 - 6
            mem.name += chr(_mem.name[i])
        if _name and mem.number < 200:
            for i in range(10):
                mem.name += chr(_name.extra_name[i])

        mem.name = mem.name.rstrip()    # remove trailing spaces

        mem.tuning_step = STEPS[_mem.tuning_step]

        # ########## TONE ##########
        dtcs_polarity = ['N', 'N']
        if _mem.txtone == 0xFFF:
            # All off
            txmode = ""
        elif _mem.txtone >= 0x8000:
            # DTSC inverted when high bit is set - signed int
            txmode = "DTCS"
            mem.dtcs = int(format(int(_mem.txtone & 0x7FFF), 'o'))
            dtcs_polarity[0] = "R"
        elif _mem.txtone > 500:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            # DTCS
            txmode = "DTCS"
            mem.dtcs = int(format(int(_mem.txtone), 'o'))
            dtcs_polarity[0] = "N"
        if _mem.rxtone == 0xFFF:
            rxmode = ""
        elif _mem.rxtone >= 0x8000:
            # DTSC inverted when high bit is set
            rxmode = "DTCS"
            mem.rx_dtcs = int(format(int(_mem.rxtone & 0x7FFF), 'o'))
            dtcs_polarity[1] = "R"
        elif _mem.rxtone > 500:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            rxmode = "DTCS"
            mem.rx_dtcs = int(format(int(_mem.rxtone), 'o'))
            dtcs_polarity[1] = "N"
        mem.dtcs_polarity = "".join(dtcs_polarity)

        mem.tmode = ""
        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
            mem.rx_dtcs = mem.dtcs
            dtcs_polarity[1] = dtcs_polarity[0]
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)
        # ########## TONE ##########

        mem.mode = self.MODES[_mem.mode]
        mem.power = POWER_LEVELS[int(_mem.power)]

        rs = RadioSettingValueList(B_LOCK_LIST,
                                   B_LOCK_LIST[min(_mem.b_lock, 0x02)])
        b_lock = RadioSetting("b_lock", "B_Lock", rs)
        mem.extra.append(b_lock)

        optsig = RadioSetting("signal", "Optional signaling",
                              RadioSettingValueList(
                                  OPTSIG_LIST,
                                  OPTSIG_LIST[_mem.signal]))
        mem.extra.append(optsig)

        vlist = RadioSettingValueList(PTTID_LIST, PTTID_LIST[_mem.dtmfpttid])
        dtmfpttid = RadioSetting("dtmfpttid", "DTMF PTT ID", vlist)
        mem.extra.append(dtmfpttid)

        vlist2 = RadioSettingValueList(PTTID_LIST,
                                       PTTID_LIST[_mem.fivetonepttid])
        fivetonepttid = RadioSetting("fivetonepttid", "5 Tone PTT ID", vlist2)
        mem.extra.append(fivetonepttid)

        return mem

    def _set_memory(self, mem, _mem, _name):
        # """Convert UI column data (mem) into MEM_FORMAT memory (_mem)."""

        _mem.rxfreq = mem.freq / 10
        _mem.tuning_step = STEPS.index(mem.tuning_step)
        if mem.duplex == "off":
            _mem.txfreq = 0xFFFFFFFF
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = _mem.rxfreq

        out_name = mem.name.ljust(16)

        for i in range(6):   # 0 - 6
            _mem.name[i] = ord(out_name[i])
        if mem.number < 200:
            for i in range(10):
                _name.extra_name[i] = ord(out_name[i+6])

        # autoset display to name if filled, else show frequency
        if mem.name != "":
            _mem.display = True
        else:
            _mem.display = False
        rxmode = ""
        txmode = ""
        sql_mode = "SQ"
        if mem.tmode == "":
            sql_mode = "SQ"
            _mem.rxtone = 0xFFF
            _mem.txtone = 0xFFF
        elif mem.tmode == "Tone":
            txmode = "Tone"
            sql_mode = "SQ"
            _mem.txtone = int(float(mem.rtone) * 10)
            _mem.rxtone = 0xFFF
        elif mem.tmode == "TSQL":
            rxmode = "Tone"
            txmode = "TSQL"
            sql_mode = "CT"
            _mem.rxtone = int(float(mem.ctone) * 10)
            _mem.txtone = int(float(mem.ctone) * 10)
        elif mem.tmode == "DTCS":
            rxmode = "DTCS"
            txmode = "DTCS"
            sql_mode = "CT"
            if mem.dtcs_polarity[0] == "N":
                _mem.txtone = int(str(mem.dtcs), 8)
            else:
                _mem.txtone = int(str(mem.dtcs), 8) | 0x8000
            if mem.dtcs_polarity[1] == "N":
                _mem.rxtone = int(str(mem.dtcs), 8)
            else:
                _mem.rxtone = int(str(mem.dtcs), 8) | 0x8000
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if rxmode == "":
                _mem.rxtone = 0xFFF
                sql_mode = "SQ"
            elif rxmode == "Tone":
                sql_mode = "CT"
                _mem.rxtone = int(float(mem.ctone) * 10)
            elif rxmode == "DTCS":
                sql_mode = "CT"
                if mem.dtcs_polarity[0] == "N":
                    _mem.rxtone = int(str(mem.rx_dtcs), 8)
                else:
                    _mem.rxtone = int(str(mem.rx_dtcs), 8) | 0x8000
            if txmode == "":
                _mem.txtone = 0xFFF
            elif txmode == "Tone":
                _mem.txtone = int(float(mem.rtone) * 10)
            elif txmode == "TSQL":
                _mem.txtone = int(float(mem.rtone) * 10)
            elif txmode == "DTCS":
                if mem.dtcs_polarity[1] == "N":
                    _mem.txtone = int(str(mem.dtcs), 8)
                else:
                    _mem.txtone = int(str(mem.dtcs), 8) | 0x8000
        _mem.sqlmode = SQL_MODES.index(sql_mode)
        _mem.mode = self.MODES.index(mem.mode)
        _mem.power = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        for element in mem.extra:
            setattr(_mem, element.get_name(), element.value)

        return

    def get_settings(self):
        """Translate the MEM_FORMAT structs into setstuf in the UI"""
        _settings = self._memobj.basicsettings
        # _settings2 = self._memobj.settings2
        # _workmode = self._memobj.workmodesettings

        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Display Mode
        options = ['Frequency', 'Channel #', 'Name']
        rx = RadioSettingValueList(options, options[_settings.disMode])
        rset = RadioSetting("basicsettings.disMode", "Display Mode", rx)
        basic.append(rset)

        # Subscreen Mode
        options = ['Off', 'Frequency', 'Voltage']
        rx = RadioSettingValueList(options, options[_settings.subDisplay])
        rset = RadioSetting("basicsettings.subDisplay", "Subscreen Mode", rx)
        basic.append(rset)

        # Squelch Level
        options = ["OFF"] + ["%s" % x for x in range(1, 10)]
        rx = RadioSettingValueList(options, options[_settings.sqlLevel])
        rset = RadioSetting("basicsettings.sqlLevel", "Squelch Level", rx)
        basic.append(rset)

        # Tone Burst Frequency
        options = ['1750', '2100', '1000', '1450']
        rx = RadioSettingValueList(options, options[_settings.burstFreq])
        rset = RadioSetting("basicsettings.burstFreq",
                            "Tone Burst Frequency (Hz)", rx)
        basic.append(rset)

        # PTT Release
        options = ['Off', 'Begin', 'End', 'Both']
        rx = RadioSettingValueList(options, options[_settings.pttRelease])
        rset = RadioSetting("basicsettings.pttRelease", "PTT Release", rx)
        basic.append(rset)

        # TX Channel Select
        options = ["Last Channel", "Main Channel"]
        rx = RadioSettingValueList(options, options[_settings.txChSelect])
        rset = RadioSetting("basicsettings.txChSelect",
                            "Priority Transmit", rx)
        basic.append(rset)

        # LED Mode
        options = ["On", "5 Second", "10 Second"]
        rx = RadioSettingValueList(options, options[_settings.ledMode])
        rset = RadioSetting("basicsettings.ledMode", "LED Display Mode", rx)
        basic.append(rset)

        # Scan Type
        options = ["TO", "CO", "SE"]
        rx = RadioSettingValueList(options, options[_settings.scanType])
        rset = RadioSetting("basicsettings.scanType", "Scan Type", rx)
        basic.append(rset)

        # Resume Time
        options = ["2 seconds", "5 seconds", "10 seconds", "15 seconds"]
        rx = RadioSettingValueList(options, options[_settings.scanResumeTime])
        rset = RadioSetting("basicsettings.scanResumeTime",
                            "Scan Resume Time", rx)
        basic.append(rset)

        # Tail Elim
        options = ["Off", "Frequency", "No Frequency"]
        rx = RadioSettingValueList(options, options[_settings.sqlTailElim])
        rset = RadioSetting("basicsettings.sqlTailElim", "Sql Tail Elim", rx)
        basic.append(rset)

        # Auto Power Off
        options = ["Off", "30 minute", "60 minute", "120 minute"]
        rx = RadioSettingValueList(options, options[_settings.autoPowOff])
        rset = RadioSetting("basicsettings.autoPowOff", "Auto Power Off", rx)
        basic.append(rset)

        # TOT
        options = ["Off"] + ["%s minutes" % x for x in range(1, 31, 1)]
        rx = RadioSettingValueList(options, options[_settings.tot])
        rset = RadioSetting("basicsettings.tot",
                            "Transmission Time-out Timer", rx)
        basic.append(rset)

        # Beep
        rx = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("basicsettings.beep", "Keypad Beep", rx)
        basic.append(rset)

        # Volume
        options = ["%s" % x for x in range(0, 16)]
        rx = RadioSettingValueList(options, options[_settings.volume])
        rset = RadioSetting("basicsettings.volume",
                            "Volume", rx)
        basic.append(rset)

        # Require Power On Password
        rx = RadioSettingValueBoolean(_settings.usePowerOnPw)
        rset = RadioSetting("basicsettings.usePowerOnPw",
                            "Require Power On Password", rx)
        basic.append(rset)

        # Power On Password Value
        pwdigits = ""
        for i in range(6):  # 0 - 6
            char = chr(_settings.powerOnPw[i])
            pwdigits += char
        rx = RadioSettingValueString(0, 6, pwdigits)
        rset = RadioSetting("basicsettings.powerOnPw", "Power On Password", rx)
        basic.append(rset)

        # Intro Screen
        '''
        #disabling since the memory map for this is still a bit ambigiuous
        options = ["Off", "Image", "Character String"]
        rx = RadioSettingValueList(options, options[_settings.introScreen])
        rset = RadioSetting("basicsettings.introScreen", "Intro Screen", rx)
        basic.append(rset)
        '''

        key_options = ["A/B", "Low", "Monitor", "Scan",
                       "Tone", "M/V", "MHz", "Mute"]
        # LO key function
        options = key_options
        rx = RadioSettingValueList(options, options[_settings.lowKeyFunc])
        rset = RadioSetting("basicsettings.lowKeyFunc", "LO Key Function", rx)
        basic.append(rset)

        # Mz key function
        options = key_options
        rx = RadioSettingValueList(options, options[_settings.mzKeyFunc])
        rset = RadioSetting("basicsettings.mzKeyFunc", "Mz Key Function", rx)
        basic.append(rset)

        # CT key function
        options = key_options
        rx = RadioSettingValueList(options, options[_settings.ctKeyFunc])
        rset = RadioSetting("basicsettings.ctKeyFunc", "CT Key Function", rx)
        basic.append(rset)

        # V/M key function
        options = key_options
        rx = RadioSettingValueList(options, options[_settings.vmKeyFunc])
        rset = RadioSetting("basicsettings.vmKeyFunc", "V/M Key Function", rx)
        basic.append(rset)

        # A/B key function
        options = key_options
        rx = RadioSettingValueList(options, options[_settings.abKeyFunc])
        rset = RadioSetting("basicsettings.abKeyFunc", "A/B Key Function", rx)
        basic.append(rset)

        # Menu Operation
        rx = RadioSettingValueBoolean(_settings.menuOperation)
        rset = RadioSetting("basicsettings.menuOperation",
                            "Menu Operation", rx)
        basic.append(rset)

        # SQ tail elim with no tone option
        rx = RadioSettingValueBoolean(_settings.elimTailNoTone)
        rset = RadioSetting("basicsettings.elimTailNoTone",
                            "Eliminate Squelch Tail When No CT/DCS Signalling",
                            rx)
        basic.append(rset)

        # Disable Reset Option
        rx = RadioSettingValueBoolean(_settings.disableReset)
        rset = RadioSetting("basicsettings.disableReset", "Disable Reset", rx)
        basic.append(rset)
        '''
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        group.append(advanced)

        # software only
        options = ['Off', 'Frequency']
        rx = RadioSettingValueList(options, options[_settings.endToneElim])
        rset = RadioSetting("basicsettings.endToneElim", "End Tone Elim", rx)
        advanced.append(rset)

        # software only
        name = ""
        for i in range(15):  # 0 - 15
            char = chr(int(self._memobj.openradioname.name1[i]))
            if char == "\x00":
                char = " "  # Other software may have 0x00 mid-name
            name += char
        name = name.rstrip()  # remove trailing spaces

        rx = RadioSettingValueString(0, 15, name)
        rset = RadioSetting("openradioname.name1", "Intro Line 1", rx)
        advanced.append(rset)

        # software only
        name = ""
        for i in range(15):  # 0 - 15
            char = chr(int(self._memobj.openradioname.name2[i]))
            if char == "\x00":
                char = " "  # Other software may have 0x00 mid-name
            name += char
        name = name.rstrip()  # remove trailing spaces

        rx = RadioSettingValueString(0, 15, name)
        rset = RadioSetting("openradioname.name2", "Intro Line 2", rx)
        advanced.append(rset)
        '''

        def myset_mask(setting, obj, atrb, nx):
            if bool(setting.value):     # Enabled = 1
                vx = 1
            else:
                vx = 0
            _do_map(nx + 1, vx, self._memobj.fmmap.fmset)
            return

        def myset_freq(setting, obj, atrb, mult):
            """ Callback to set frequency by applying multiplier"""
            value = int(float(str(setting.value)) * mult)
            setattr(obj, atrb, value)
            return

        return group       # END get_settings()

    def set_settings(self, settings):
        _settings = self._memobj.basicsettings
        # _mem = self._memobj
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
                    elif setting == "powerOnPw":
                        temp = []
                        for c in element.value:
                            temp.append(ord(c))
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, temp)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise
