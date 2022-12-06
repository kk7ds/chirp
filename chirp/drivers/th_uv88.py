# Version 1.0 for TYT-UV88
# Initial radio protocol decode, channels and memory layout
# by James Berry <james@coppermoth.com>, Summer 2020
# Additional configuration and help, Jim Unroe <rock.unroe@gmail.com>
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

import time
import struct
import logging
import re
import math
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, InvalidValueError
from textwrap import dedent

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct chns {
  ul32 rxfreq;
  ul32 txfreq;
  ul16 scramble:4
       rxtone:12; //decode:12
  ul16 decodeDSCI:1
       encodeDSCI:1
       unk1:1
       unk2:1
       txtone:12; //encode:12
  u8   power:2
       wide:2
       b_lock:2
       unk3:2;
  u8   unk4:3
       signal:2
       displayName:1
       unk5:2;
  u8   unk6:2
       pttid:2
       step:4;               // not required
  u8   name[6];
};

struct vfo {
  ul32 rxfreq;
  ul32 txfreq;  // displayed as an offset
  ul16 scramble:4
       rxtone:12; //decode:12
  ul16 decodeDSCI:1
       encodeDSCI:1
       unk1:1
       unk2:1
       txtone:12; //encode:12
  u8   power:2
       wide:2
       b_lock:2
       unk3:2;
  u8   unk4:3
       signal:2
       displayName:1
       unk5:2;
  u8   unk6:2
       pttid:2
       step:4;
  u8   name[6];
};

struct chname {
  u8  extra_name[10];
};

#seekto 0x0000;
struct chns chan_mem[199];

#seekto 0x1960;
struct chname chan_name[199];

#seekto 0x1180;
struct {
  u8 bitmap[26];    // one bit for each channel marked in use
} chan_avail;

#seekto 0x11A0;
struct {
  u8 bitmap[26];    // one bit for each channel skipped
} chan_skip;

#seekto 0x1140;
struct {
  u8 autoKeylock:1,       // 0x1140 [18] *OFF, On
     unk_bit6_5:1,        //
     vfomrmodeb:1,        //        *VFO B, MR B
     vfomrmode:1,         //        *VFO, MR
     unk_bit3_0:4;        //
  u8 mrAch;               // 0x1141 MR A Channel #
  u8 mrBch;               // 0x1142 MR B Channel #
  u8 unk_bit7_3:5,        //
     ab:1,                //        * A, B
     unk_bit1_0:2;        //
} workmodesettings;

#seekto 0x1160;
struct {
  u8 introScreen1[12];    // 0x1160 *Intro Screen Line 1(truncated to 12 alpha
                          //         text characters)
  u8 offFreqVoltage : 3,  // 0x116C unknown referred to in code but not on
                          //        screen
     unk_bit4 : 1,        //
     sqlLevel : 4;        //        [05] *OFF, 1-9
  u8 beep : 1             // 0x116D [09] *OFF, On
     callKind : 2,        //        code says 1750,2100,1000,1450 as options
                          //        not on screen
     introScreen: 2,      //        [20] *OFF, Voltage, Char String
     unkstr2: 2,          //
     txChSelect : 1;      //        [02] *Last CH, Main CH
  u8 autoPowOff : 3,      // 0x116E not on screen? OFF, 30Min, 1HR, 2HR
     unk : 1,             //
     tot : 4;             //        [11] *OFF, 30 Second, 60 Second, 90 Second,
                          //              ... , 270 Second
  u8 unk_bit7:1,          // 0x116F
     roger:1,             //        [14] *OFF, On
     dailDef:1,           //        Unknown - 'Volume, Frequency'
     language:1,          //        ?Chinese, English (English only FW BQ1.38+)
     unk_bit3:1,          //
     endToneElim:1,       //        *OFF, Frequency
     unkCheckBox1:1,      //
     unkCheckBox2:1;      //
  u8 scanResumeTime : 2,  // 0x1170 2S, 5S, 10S, 15S (not on screen)
     disMode : 2,         //        [33] *Frequency, Channel, Name
     scanType: 2,         //        [17] *To, Co, Se
     ledMode: 2;          //        [07] *Off, On, Auto
  u8 unky;                // 0x1171
  u8 str6;                // 0x1172 Has flags to do with logging - factory
                          // enabled (bits 16,64,128)
  u8 unk;                 // 0x1173
  u8 swAudio : 1,         // 0x1174 [19] *OFF, On
     radioMoni : 1,       //        [34] *OFF, On
     keylock : 1,         //        [18] *OFF, On
     dualWait : 1,        //        [06] *OFF, On
     unk_bit3 : 1,        //
     light : 3;           //        [08] *1, 2, 3, 4, 5, 6, 7
  u8 voxSw : 1,           // 0x1175 [13] *OFF, On
     voxDelay: 4,         //        *0.5S, 1.0S, 1.5S, 2.0S, 2.5S, 3.0S, 3.5S,
                          //         4.0S, 4.5S, 5.0S
     voxLevel : 3;        //        [03] *1, 2, 3, 4, 5, 6, 7
  u8 str9 : 4,            // 0x1176
     saveMode : 2,        //        [16] *OFF, 1:1, 1:2, 1:4
     keyMode : 2;         //        [32] *ALL, PTT, KEY, Key & Side Key
  u8 unk2;                // 0x1177
  u8 unk3;                // 0x1178
  u8 unk4;                // 0x1179
  u8 name2[6];            // 0x117A unused
} basicsettings;

#seekto 0x191E;
struct {
  u8 unknown191e:4,       //
     region:4;            // 0x191E Radio Region (read only)
                          // 0 = Unlocked  TX: 136-174 MHz / 400-480 MHz
                          // 2-3 = Unknown
                          // 3 = EU        TX: 144-146 MHz / 430-440 MHz
                          // 4 = US        TX: 144-148 MHz / 420-450 MHz
                          // 5-15 = Unknown
} settings2;

#seekto 0x1940;
struct {
  char name1[15];         // Intro Screen Line 1 (16 alpha text characters)
  u8 unk1;
  char name2[15];         // Intro Screen Line 2 (16 alpha text characters)
  u8 unk2;
} openradioname;

struct fm_chn {
  ul32 rxfreq;
};

#seekto 0x2180;
struct fm_chn fm_stations[24];

#seekto 0x021E0;
struct {
  u8  fmset[4];
} fmmap;

#seekto 0x21E4;
struct {
  ul32 fmcur;
} fmfrqs;

"""

MEM_SIZE = 0x22A0
BLOCK_SIZE = 0x20
STIMEOUT = 2
BAUDRATE = 57600

# Channel power: 3 levels
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                chirp_common.PowerLevel("Mid", watts=2.50),
                chirp_common.PowerLevel("Low", watts=0.50)]

SCRAMBLE_LIST = ["OFF", "1", "2", "3", "4", "5", "6", "7", "8"]
B_LOCK_LIST = ["OFF", "Sub", "Carrier"]
OPTSIG_LIST = ["OFF", "DTMF", "2TONE", "5TONE"]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 100.0]
LIST_STEPS = [str(x) for x in STEPS]


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
    frame += struct.pack(">ih", addr, length)

    frame += b"\xFD"
    # Return the data
    return frame


def _make_write_frame(addr, length, data=""):
    frame = b"\xFE\xFE\xEE\xEF\xE4"

    """Pack the info in the header format"""
    output = struct.pack(">ih", addr, length)
    # Add the data if set
    if len(data) != 0:
        output += data

    frame += output
    frame += _calculate_checksum(output)

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
        d = _recv(radio, addr, BLOCK_SIZE + 13)

        LOG.debug("Response Data= " + util.hexprint(d))

        if not d.startswith(b"\xFE\xFE\xEF\xEE\xE4"):
            LOG.warning("Incorrect start")
        if not d.endswith(b"\xFD"):
            LOG.warning("Incorrect end")
        # could validate the block data

        # Aggregate the data
        data += d[11:-2]

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
    """Set or Clear the chn (1-128) bit in mary[] word array map"""
    # chn is 1-based channel, sclr:1 = set, 0= = clear, 2= return state
    # mary[] is u8 array, but the map is by nibbles
    ndx = int(math.floor((chn - 1) / 8))
    bv = (chn - 1) % 8
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
class THUV88Radio(chirp_common.CloneModeRadio):
    """TYT UV88 Radio"""
    VENDOR = "TYT"
    MODEL = "TH-UV88"
    NEEDS_COMPAT_SERIAL = False
    MODES = ['WFM', 'FM', 'NFM']
    TONES = chirp_common.TONES
    DTCS_CODES = chirp_common.DTCS_CODES
    NAME_LENGTH = 10
    DTMF_CHARS = list("0123456789ABCD*#")
    # 136-174, 400-480
    VALID_BANDS = [(136000000, 174000000), (400000000, 480000000)]

    # Valid chars on the LCD
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "`!\"#$%&'()*+,-./:;<=>?@[]^_"

    _magic0 = b"\xFE\xFE\xEE\xEF\xE0" + b"UV88" + b"\xFD"
    _magic2 = b"\xFE\xFE\xEE\xEF\xE2" + b"UV88" + b"\xFD"
    _magic3 = b"\xFE\xFE\xEE\xEF\xE3" + b"UV88" + b"\xFD"
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5" + b"UV88" + b"\xFD"
    _fingerprint = b"\xFE\xFE\xEF\xEE\xE1" + b"UV88"

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = \
            (cls.VENDOR + ' ' + cls.MODEL + '\n')

        rp.pre_download = _(dedent("""\
            This is an early stage beta driver
            """))
        rp.pre_upload = _(dedent("""\
            This is an early stage beta driver - upload at your own risk
            """))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_comment = False
        rf.has_tuning_step = False      # Not as chan feature
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
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES  # this is just to
        # get it working, not sure this is right
        rf.valid_bands = self.VALID_BANDS
        rf.memory_bounds = (1, 199)
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
        return repr(self._memobj.memory[number - 1])

    def set_memory(self, memory):
        """A value in a UI column for chan 'number' has been modified."""
        # update all raw channel memory values (_mem) from UI (mem)
        _mem = self._memobj.chan_mem[memory.number - 1]
        _name = self._memobj.chan_name[memory.number - 1]

        if memory.empty:
            _do_map(memory.number, 0, self._memobj.chan_avail.bitmap)
            return

        _do_map(memory.number, 1, self._memobj.chan_avail.bitmap)

        if memory.skip == "":
            _do_map(memory.number, 1, self._memobj.chan_skip.bitmap)
        else:
            _do_map(memory.number, 0, self._memobj.chan_skip.bitmap)

        return self._set_memory(memory, _mem, _name)

    def get_memory(self, number):
        # radio first channel is 1, mem map is base 0
        _mem = self._memobj.chan_mem[number - 1]
        _name = self._memobj.chan_name[number - 1]
        mem = chirp_common.Memory()
        mem.number = number

        # Determine if channel is empty

        if _do_map(number, 2, self._memobj.chan_avail.bitmap) == 0:
            mem.empty = True
            return mem

        if _do_map(mem.number, 2, self._memobj.chan_skip.bitmap) > 0:
            mem.skip = ""
        else:
            mem.skip = "S"

        return self._get_memory(mem, _mem, _name)

    def _get_memory(self, mem, _mem, _name):
        """Convert raw channel memory data into UI columns"""
        mem.extra = RadioSettingGroup("extra", "Extra")

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
        for i in range(10):
            mem.name += chr(_name.extra_name[i])

        mem.name = mem.name.rstrip()    # remove trailing spaces

        # ########## TONE ##########

        if _mem.txtone > 2600:
            # All off
            txmode = ""
        elif _mem.txtone > 511:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            # DTSC
            txmode = "DTCS"
            mem.dtcs = int(format(int(_mem.txtone), 'o'))

        if _mem.rxtone > 2600:
            rxmode = ""
        elif _mem.rxtone > 511:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            rxmode = "DTCS"
            mem.rx_dtcs = int(format(int(_mem.rxtone), 'o'))

        mem.dtcs_polarity = ("N", "R")[_mem.encodeDSCI] + (
                             "N", "R")[_mem.decodeDSCI]

        mem.tmode = ""
        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        # ########## TONE ##########

        mem.mode = self.MODES[_mem.wide]
        mem.power = POWER_LEVELS[int(_mem.power)]

        b_lock = RadioSetting("b_lock", "B_Lock",
                              RadioSettingValueList(B_LOCK_LIST,
                                                    B_LOCK_LIST[_mem.b_lock]))
        mem.extra.append(b_lock)

        b_lock = RadioSetting("step", "Step",
                              RadioSettingValueList(LIST_STEPS,
                                                    LIST_STEPS[_mem.step]))
        mem.extra.append(b_lock)

        scramble_value = _mem.scramble
        if scramble_value >= 8:     # Looks like OFF is 0x0f ** CONFIRM
            scramble_value = 0
        scramble = RadioSetting("scramble", "Scramble",
                                RadioSettingValueList(SCRAMBLE_LIST,
                                                      SCRAMBLE_LIST[
                                                          scramble_value]))
        mem.extra.append(scramble)

        optsig = RadioSetting("signal", "Optional signaling",
                              RadioSettingValueList(
                                  OPTSIG_LIST,
                                  OPTSIG_LIST[_mem.signal]))
        mem.extra.append(optsig)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[_mem.pttid]))
        mem.extra.append(rs)

        return mem

    def _set_memory(self, mem, _mem, _name):
        # """Convert UI column data (mem) into MEM_FORMAT memory (_mem)."""

        _mem.rxfreq = mem.freq / 10
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
        for i in range(10):
            _name.extra_name[i] = ord(out_name[i+6])

        if mem.name != "":
            _mem.displayName = 1    # Name only displayed if this is set on
        else:
            _mem.displayName = 0

        rxmode = ""
        txmode = ""

        if mem.tmode == "Tone":
            txmode = "Tone"
        elif mem.tmode == "TSQL":
            rxmode = "Tone"
            txmode = "TSQL"
        elif mem.tmode == "DTCS":
            rxmode = "DTCSSQL"
            txmode = "DTCS"
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)

        if mem.dtcs_polarity[1] == "N":
            _mem.decodeDSCI = 0
        else:
            _mem.decodeDSCI = 1

        if rxmode == "":
            _mem.rxtone = 0xFFF
        elif rxmode == "Tone":
            _mem.rxtone = int(float(mem.ctone) * 10)
        elif rxmode == "DTCSSQL":
            _mem.rxtone = int(str(mem.dtcs), 8)
        elif rxmode == "DTCS":
            _mem.rxtone = int(str(mem.rx_dtcs), 8)

        if mem.dtcs_polarity[0] == "N":
            _mem.encodeDSCI = 0
        else:
            _mem.encodeDSCI = 1

        if txmode == "":
            _mem.txtone = 0xFFF
        elif txmode == "Tone":
            _mem.txtone = int(float(mem.rtone) * 10)
        elif txmode == "TSQL":
            _mem.txtone = int(float(mem.ctone) * 10)
        elif txmode == "DTCS":
            _mem.txtone = int(str(mem.dtcs), 8)

        _mem.wide = self.MODES.index(mem.mode)
        _mem.power = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        for element in mem.extra:
            setattr(_mem, element.get_name(), element.value)

        return

    def get_settings(self):
        """Translate the MEM_FORMAT structs into setstuf in the UI"""
        _settings = self._memobj.basicsettings
        _settings2 = self._memobj.settings2
        _workmode = self._memobj.workmodesettings

        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        # Menu 02 - TX Channel Select
        options = ["Last Channel", "Main Channel"]
        rx = RadioSettingValueList(options, options[_settings.txChSelect])
        rset = RadioSetting("basicsettings.txChSelect",
                            "Priority Transmit", rx)
        basic.append(rset)

        # Menu 03 - VOX Level
        rx = RadioSettingValueInteger(1, 7, _settings.voxLevel + 1)
        rset = RadioSetting("basicsettings.voxLevel", "Vox Level", rx)
        basic.append(rset)

        # Menu 05 - Squelch Level
        options = ["OFF"] + ["%s" % x for x in range(1, 10)]
        rx = RadioSettingValueList(options, options[_settings.sqlLevel])
        rset = RadioSetting("basicsettings.sqlLevel", "Squelch Level", rx)
        basic.append(rset)

        # Menu 06 - Dual Wait
        rx = RadioSettingValueBoolean(_settings.dualWait)
        rset = RadioSetting("basicsettings.dualWait", "Dual Wait/Standby", rx)
        basic.append(rset)

        # Menu 07 - LED Mode
        options = ["Off", "On", "Auto"]
        rx = RadioSettingValueList(options, options[_settings.ledMode])
        rset = RadioSetting("basicsettings.ledMode", "LED Display Mode", rx)
        basic.append(rset)

        # Menu 08 - Light
        options = ["%s" % x for x in range(1, 8)]
        rx = RadioSettingValueList(options, options[_settings.light])
        rset = RadioSetting("basicsettings.light",
                            "Background Light Color", rx)
        basic.append(rset)

        # Menu 09 - Beep
        rx = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("basicsettings.beep", "Keypad Beep", rx)
        basic.append(rset)

        # Menu 11 - TOT
        options = ["Off"] + ["%s seconds" % x for x in range(30, 300, 30)]
        rx = RadioSettingValueList(options, options[_settings.tot])
        rset = RadioSetting("basicsettings.tot",
                            "Transmission Time-out Timer", rx)
        basic.append(rset)

        # Menu 13 - VOX Switch
        rx = RadioSettingValueBoolean(_settings.voxSw)
        rset = RadioSetting("basicsettings.voxSw", "Vox Switch", rx)
        basic.append(rset)

        # Menu 14 - Roger
        rx = RadioSettingValueBoolean(_settings.roger)
        rset = RadioSetting("basicsettings.roger", "Roger Beep", rx)
        basic.append(rset)

        # Menu 16 - Save Mode
        options = ["Off", "1:1", "1:2", "1:4"]
        rx = RadioSettingValueList(options, options[_settings.saveMode])
        rset = RadioSetting("basicsettings.saveMode", "Battery Save Mode", rx)
        basic.append(rset)

        # Menu 17 - Scan Type
        if self.MODEL == "QRZ-1":
            options = ["Time", "Carrier", "Stop"]
        else:
            options = ["CO", "TO", "SE"]
        rx = RadioSettingValueList(options, options[_settings.scanType])
        rset = RadioSetting("basicsettings.scanType", "Scan Type", rx)
        basic.append(rset)

        # Menu 18 - Key Lock
        rx = RadioSettingValueBoolean(_settings.keylock)
        rset = RadioSetting("basicsettings.keylock", "Auto Key Lock", rx)
        basic.append(rset)

        if self.MODEL != "QRZ-1":
            # Menu 19 - SW Audio
            rx = RadioSettingValueBoolean(_settings.swAudio)
            rset = RadioSetting("basicsettings.swAudio", "Voice Prompts", rx)
            basic.append(rset)

        # Menu 20 - Intro Screen
        options = ["Off", "Voltage", "Character String"]
        rx = RadioSettingValueList(options, options[_settings.introScreen])
        rset = RadioSetting("basicsettings.introScreen", "Intro Screen", rx)
        basic.append(rset)

        # Menu 32 - Key Mode
        options = ["ALL", "PTT", "KEY", "Key & Side Key"]
        rx = RadioSettingValueList(options, options[_settings.keyMode])
        rset = RadioSetting("basicsettings.keyMode", "Key Lock Mode", rx)
        basic.append(rset)

        # Menu 33 - Display Mode
        options = ['Frequency', 'Channel #', 'Name']
        rx = RadioSettingValueList(options, options[_settings.disMode])
        rset = RadioSetting("basicsettings.disMode", "Display Mode", rx)
        basic.append(rset)

        # Menu 34 - FM Dual Wait
        rx = RadioSettingValueBoolean(_settings.radioMoni)
        rset = RadioSetting("basicsettings.radioMoni", "Radio Monitor", rx)
        basic.append(rset)

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

        # software only
        options = ['0.5S', '1.0S', '1.5S', '2.0S', '2.5S', '3.0S', '3.5S',
                   '4.0S', '4.5S', '5.0S']
        rx = RadioSettingValueList(options, options[_settings.voxDelay])
        rset = RadioSetting("basicsettings.voxDelay", "VOX Delay", rx)
        advanced.append(rset)

        options = ['Unlocked', 'Unknown 1', 'Unknown 2', 'EU', 'US']
        # extend option list with unknown description for values 5 - 15.
        for ix in range(len(options), _settings2.region + 1):
            item_to_add = 'Unknown {region_code}'.format(region_code=ix)
            options.append(item_to_add)
        # log unknown region codes greater than 4
        if _settings2.region > 4:
            LOG.debug("Unknown region code: {value}".
                      format(value=_settings2.region))
        rx = RadioSettingValueList(options, options[_settings2.region])
        rx.set_mutable(False)
        rset = RadioSetting("settings2.region", "Region", rx)
        advanced.append(rset)

        workmode = RadioSettingGroup("workmode", "Work Mode Settings")
        group.append(workmode)

        # Toggle with [#] key
        options = ["Frequency", "Channel"]
        rx = RadioSettingValueList(options, options[_workmode.vfomrmode])
        rset = RadioSetting("workmodesettings.vfomrmode", "VFO/MR Mode", rx)
        workmode.append(rset)

        # Toggle with [#] key
        options = ["Frequency", "Channel"]
        rx = RadioSettingValueList(options, options[_workmode.vfomrmodeb])
        rset = RadioSetting("workmodesettings.vfomrmodeb",
                            "VFO/MR Mode B (BQ1.41+)", rx)
        workmode.append(rset)

        # Toggle with [A/B] key
        options = ["B", "A"]
        rx = RadioSettingValueList(options, options[_workmode.ab])
        rset = RadioSetting("workmodesettings.ab", "A/B Select", rx)
        workmode.append(rset)

        rx = RadioSettingValueInteger(1, 199, _workmode.mrAch + 1)
        rset = RadioSetting("workmodesettings.mrAch", "MR A Channel #", rx)
        workmode.append(rset)

        rx = RadioSettingValueInteger(1, 199, _workmode.mrBch + 1)
        rset = RadioSetting("workmodesettings.mrBch", "MR B Channel #", rx)
        workmode.append(rset)

        fmb = RadioSettingGroup("fmradioc", "FM Radio Settings")
        group.append(fmb)

        def myset_mask(setting, obj, atrb, nx):
            if bool(setting.value):     # Enabled = 1
                vx = 1
            else:
                vx = 0
            _do_map(nx + 1, vx, self._memobj.fmmap.fmset)
            return

        def myset_fmfrq(setting, obj, atrb, nx):
            """ Callback to set xx.x FM freq in memory as xx.x * 100000"""
            # in-valid even KHz freqs are allowed; to satisfy run_tests
            vx = float(str(setting.value))
            vx = int(vx * 100000)
            setattr(obj[nx], atrb, vx)
            return

        def myset_freq(setting, obj, atrb, mult):
            """ Callback to set frequency by applying multiplier"""
            value = int(float(str(setting.value)) * mult)
            setattr(obj, atrb, value)
            return

        _fmx = self._memobj.fmfrqs

        # FM Broadcast Manual Settings
        val = _fmx.fmcur
        val = val / 100000.0
        if val < 64.0 or val > 108.0:
            val = 100.7
        rx = RadioSettingValueFloat(64.0, 108.0, val, 0.1, 1)
        rset = RadioSetting("fmfrqs.fmcur", "Manual FM Freq (MHz)", rx)
        rset.set_apply_callback(myset_freq, _fmx, "fmcur", 100000)
        fmb.append(rset)

        _fmfrq = self._memobj.fm_stations
        _fmap = self._memobj.fmmap

        # FM Broadcast Presets Settings
        for j in range(0, 24):
            val = _fmfrq[j].rxfreq
            if val < 6400000 or val > 10800000:
                val = 88.0
                fmset = False
            else:
                val = (float(int(val)) / 100000)
                # get fmmap bit value: 1 = enabled
                ndx = int(math.floor((j) / 8))
                bv = j % 8
                msk = 1 << bv
                vx = _fmap.fmset[ndx]
                fmset = bool(vx & msk)
            rx = RadioSettingValueBoolean(fmset)
            rset = RadioSetting("fmmap.fmset/%d" % j,
                                "FM Preset %02d" % (j + 1), rx)
            rset.set_apply_callback(myset_mask, _fmap, "fmset", j)
            fmb.append(rset)

            rx = RadioSettingValueFloat(64.0, 108.0, val, 0.1, 1)
            rset = RadioSetting("fm_stations/%d.rxfreq" % j,
                                "    Preset %02d Freq" % (j + 1), rx)
            # This callback uses the array index
            rset.set_apply_callback(myset_fmfrq, _fmfrq, "rxfreq", j)
            fmb.append(rset)

        return group       # END get_settings()

    def set_settings(self, settings):
        _settings = self._memobj.basicsettings
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
                    elif setting == "mrAch" or setting == "mrBch":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "voxLevel":
                        setattr(obj, setting, int(element.value) - 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise


@directory.register
class RT85(THUV88Radio):
    VENDOR = "Retevis"
    MODEL = "RT85"


@directory.register
class QRZ1(THUV88Radio):
    VENDOR = "Explorer"
    MODEL = "QRZ-1"

    _magic0 = b"\xFE\xFE\xEE\xEF\xE0" + b"UV78" + b"\xFD"
    _magic2 = b"\xFE\xFE\xEE\xEF\xE2" + b"UV78" + b"\xFD"
    _magic3 = b"\xFE\xFE\xEE\xEF\xE3" + b"UV78" + b"\xFD"
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5" + b"UV78" + b"\xFD"
    _fingerprint = b"\xFE\xFE\xEF\xEE\xE1" + b"UV78"
