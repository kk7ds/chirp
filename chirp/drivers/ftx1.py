# Copyright 2026 Richard Steinbrueck
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Yaesu FTX-1.

Two ways to get at the memories of the radio:

  - over its USB port, with the block commands the radio has for this
    (see "USB")
  - with the files the radio saves to its SD card with "MEM LIST SAVE"
    (FTX-1/MemList/*.dat) and reads back with "MEM LIST LOAD" (see "SD
    card file layout"). They open and save like an image.

Both hold the same data, at different offsets:

  info    two channel numbers, then bitmaps of 141 bytes with one bit
          per channel: in use, skipped by the memory scan, in the
          memory group (M-GRP), one reserved, and eleven lists the
          radio shows the channels in (all, HF, 6 m, air band, VHF,
          UHF, four reserved, M-GRP)
  home    the five home channels
  memory  channels of 89 bytes: 999 memories, 100 PMS band edges
          (P-01L, P-01U ... P-50U), 15 for the 5 MHz band, the
          emergency channel and 10 weather channels

Erasing a channel only clears its bits, the radio keeps the record.

SD card file layout:

  0x000  eight lines of 62 spaces and CR LF
  0x200  "MemList  80  <CRC>" padded to a ninth such line
  0x240  the body, lightly obfuscated: a repeating 43 byte key is
         added to every byte, see KEY. <CRC> is the CRC-32 of the body
         as stored, followed by four constant bytes.

The body holds info at 0x0010, home at 0x0857 and memory at 0x0BD4. It
ends within the 5 MHz channels, so the file has the memories and the
PMS channels only. An image made from a file keeps what is in front of
info and behind home next to them, and has zeros where the file ends:
that part is not uploaded.

USB:

The radio answers on its CAT port ("Enhanced COM Port", 38400 baud) to
commands that end in ";" like CAT commands do, but carry binary data:

  A1 <sum> ;                    -> A1 <r> <size:3> <sum> ;
  A2 <sum> ;                    -> A2 <r> <model:6> <pattern:2> <sum> ;
  A0 R <r> <addr:3> <len:2> <sum> ;
                    -> A0 R <r> <addr:3> <len:2> <data:1024> <sum> ;
  A0 W <r> <addr:3> <len:2> <data:1024> <sum> ;
                                -> A0 W <r> <0x06> <sum> ;
  PS9;                          restart, after writing

<r> is a byte the sender picks, it is added to every byte between it
and <sum>. <sum> is the sum of all bytes before it. Numbers are big
endian. A block always carries 1024 data bytes, of which <len> count.
Only info, home and memory are read and written, the image of this
driver holds them at their address in the radio: 0x2079, 0x28C0 and
0x70D6. The rest of the image is not used.

Known gaps:
  - a channel holds a set of filter settings per group of modes, only
    the one of its own mode is shown. Of these the notch and contour
    frequency, the IF width and the IF shift are kept but not shown.
    A new channel gets the values the radio itself uses for a new
    channel.
  - C4FM and WFM show no AGC and filter settings
  - the repeater offset amount is a radio setting, a channel only
    selects the shift direction. The offset the FM settings of a
    channel hold (rpt_freq) is kept but not used.
  - the home, 5 MHz, emergency and weather channels are not shown
  - the USB driver does not search for the baud rate of the radio
"""

import logging
import random
import time
import zlib

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList

LOG = logging.getLogger(__name__)

FILE_SIZE = 101592
HEADER_SIZE = 0x240
# Offset and length of the header line that names the file type
TYPE_LINE = (0x200, 0x40)
FILE_TYPE = b"MemList"

# The radio does not store the body in the clear. Byte i of the body is
# written as (byte + KEY[i % 43]) & 0xFF, and reading subtracts the key
# again. The key is a fixed shuffle of the numbers 1 to 43, the same in
# every file. Stretches of the body that are zero show the key itself
# in the file.
KEY = bytes.fromhex("1e271b12111619172425291c0d0b060403010205070c0e0f181d20"
                    "222a2b08090a101314151a1f21282326")
# Appended to the stored body before its CRC-32 is taken
CRC_TAIL = bytes.fromhex("8f93c635")

# Info, home and memory are at their address in the radio
MEM_FORMAT = """
// Settings a channel holds for a group of modes. Not every group has
// every switch: see GROUP_SWITCHES.
struct mode_group {
  u8 notch:1,
     contour:1,
     apf:1,
     agc:3,
     bk_in:1,
     dnf:1;
  u16 contour_freq;
  u16 notch_freq;
  u16 width;
  i16 shift;
};

struct channel {
  u8 tag:1,
     ipo:2,
     mode:5;
  u8 sdx:1,
     digi_narrow:1,             // C4FM modes
     att:1,
     unknown1:2,
     tuner:1,
     unknown2:1,
     antenna:1;
  u8 shift:2,
     unknown3:2,
     dnr:4;
  u8 ssb_narrow:1,
     cw_narrow:1,
     rtty_narrow:1,
     data_narrow:1,
     split:1,
     sql:3;
  u8 unknown4:4,
     nb:4;
  struct mode_group ssb;
  struct mode_group cw;
  struct mode_group rtty;
  struct mode_group data;       // DATA-L, DATA-U and PSK
  struct {
    u8 notch:1,
       contour:1,
       unknown1:1,
       agc:3,
       bk_in:1,
       dnf:1;
    u16 contour_freq;
    u16 notch_freq;
  } am;
  struct {
    u8 unknown1:3,
       agc:3,
       bk_in:1,
       unknown2:1;
    u32 rpt_freq;
  } fm;                         // FM and DATA-FM
  u8 tone;
  u8 dtcs;
  u16 clarifier;
  u32 freq;
  u16 name[12];
  u32 split_freq;
  u8 rx_dgid;
  u8 tx_dgid;
};

// One bit per channel, channel 1 first
struct bitmap {
  lbit channel[1128];
};

#seekto 0x2079;
struct {
  u16 vfo_channel[2];
  struct bitmap used;
  struct bitmap skip;
  struct bitmap mgrp;
  struct bitmap reserved;
  struct bitmap groups[11];
} info;
struct channel home[5];

#seekto 0x70D6;
struct channel memory[1125];
"""

MEM_SIZE = 89
NAME_LENGTH = 12

MEMORIES = 999
# The PMS channels follow the memories: the lower and the upper edge of
# 50 bands to scan
PMS_NAMES = ["P-%02i%s" % (band, edge)
             for band in range(1, 51) for edge in "LU"]

# info.groups[] index of the list with every channel, of the band group
# a frequency belongs to and of the memory group. Frequencies outside of
# the bands are in no band group. HF is the amateur bands only.
GROUP_ALL = 0
GROUP_HF, GROUP_6M, GROUP_AIR, GROUP_VHF, GROUP_UHF = 1, 2, 3, 4, 5
GROUP_MGRP = 10
BAND_GROUPS = [
    (1800000, 2000000, GROUP_HF),
    (3500000, 4000000, GROUP_HF),
    (5000000, 5500000, GROUP_HF),
    (7000000, 7500000, GROUP_HF),
    (10000000, 10500000, GROUP_HF),
    (14000000, 14500000, GROUP_HF),
    (18000000, 18500000, GROUP_HF),
    (21000000, 21500000, GROUP_HF),
    (24500000, 25000000, GROUP_HF),
    (28000000, 30000000, GROUP_HF),
    (50000000, 54000000, GROUP_6M),
    (118000000, 137000000, GROUP_AIR),
    (137000000, 174000000, GROUP_VHF),
    (400000000, 470000000, GROUP_UHF),
]

# A mode of the radio as CHIRP mode and data flag: the DATA modes of the
# radio are LSB, USB and FM with data, see mem.extra. Several codes can
# share a CHIRP value, *_TO_FILE holds the code that is written for it.
MODE_FROM_FILE = {
    0x00: ("LSB", False), 0x01: ("USB", False),
    0x02: ("CWR", False),       # CW-L
    0x03: ("CW", False),        # CW-U
    0x04: ("AM", False), 0x05: ("NAM", False),
    0x06: ("FM", False), 0x07: ("NFM", False),
    0x08: ("LSB", True),        # DATA-L
    0x09: ("USB", True),        # DATA-U
    0x0A: ("FM", True),         # DATA-FM
    0x0B: ("NFM", True),        # DATA-FM-N
    0x0C: ("RTTY", False),      # RTTY-L
    0x0D: ("RTTYR", False),     # RTTY-U
    0x0E: ("FSK", False),       # PSK
    0x10: ("DN", False),        # C4FM-VD
    0x11: ("DN", False),        # C4FM-DN
    0x12: ("DN", False),        # C4FM-VW
    0x13: ("DN", False),        # C4FM-DW
    0x1D: ("WFM", False),
    0x1E: ("Auto", False),      # AMS, FM or C4FM as received
}
MODE_TO_FILE = {
    ("LSB", False): 0x00, ("USB", False): 0x01, ("CWR", False): 0x02,
    ("CW", False): 0x03, ("AM", False): 0x04, ("NAM", False): 0x05,
    ("FM", False): 0x06, ("NFM", False): 0x07, ("LSB", True): 0x08,
    ("USB", True): 0x09, ("FM", True): 0x0A, ("NFM", True): 0x0B,
    ("RTTY", False): 0x0C, ("RTTYR", False): 0x0D, ("FSK", False): 0x0E,
    ("DN", False): 0x11, ("WFM", False): 0x1D, ("Auto", False): 0x1E,
}
DATA_MODES = [mode for mode, data in MODE_TO_FILE if data]

TMODE_FROM_FILE = {
    0: "", 1: "Tone", 2: "TSQL", 3: "DTCS",
    4: "",          # PR FREQ, no CHIRP equivalent
    5: "TSQL-R",    # REV TONE
}
TMODE_TO_FILE = {"": 0, "Tone": 1, "TSQL": 2, "DTCS": 3, "TSQL-R": 5}

SHIFT_FROM_FILE = {
    0: "-", 1: "", 2: "+",
    3: "",          # ARS, automatic repeater shift
}
SHIFT_TO_FILE = {"-": 0, "": 1, "+": 2}

# What the radio itself puts into the mode groups (ssb ... fm) of a new
# channel
NEW_MODE_SETTINGS = bytes.fromhex(
    "04009600960bb80000" "040096009601f40000" "040096009601f40000"
    "04009600960c800000" "080096009604000000")
# A new channel: the mode groups start at byte 5 of the record
NEW_MEMORY = bytes(5) + NEW_MODE_SETTINGS + bytes(MEM_SIZE - 50)

# The mode group whose settings a mode uses
MODE_GROUP = {
    0x00: "ssb", 0x01: "ssb",
    0x02: "cw", 0x03: "cw",
    0x0C: "rtty", 0x0D: "rtty",
    0x08: "data", 0x09: "data", 0x0E: "data",
    0x04: "am", 0x05: "am",
    0x06: "fm", 0x07: "fm", 0x0A: "fm", 0x0B: "fm",
}
# The switches a mode group has, besides its AGC
GROUP_SWITCHES = {
    "ssb": ("notch", "contour", "dnf", "bk_in"),
    "cw": ("notch", "contour", "dnf", "apf", "bk_in"),
    "rtty": ("notch", "contour", "dnf"),
    "data": ("notch", "contour", "dnf"),
    "am": ("notch", "contour", "dnf", "bk_in"),
    "fm": ("bk_in",),
}
SWITCH_LABELS = [("notch", "Notch"), ("contour", "Contour"),
                 ("dnf", "DNF"), ("apf", "APF"), ("bk_in", "Break-in")]
# The channel field with the narrow filter switch of a mode. AM and FM
# have narrow modes of their own instead.
NARROW_FIELD = {
    0x00: "ssb_narrow", 0x01: "ssb_narrow",
    0x02: "cw_narrow", 0x03: "cw_narrow",
    0x0C: "rtty_narrow", 0x0D: "rtty_narrow",
    0x08: "data_narrow", 0x09: "data_narrow", 0x0E: "data_narrow",
    0x10: "digi_narrow", 0x11: "digi_narrow", 0x12: "digi_narrow",
    0x13: "digi_narrow", 0x1E: "digi_narrow",
}

AGC_MODES = ["Off", "Auto", "Fast", "Mid", "Slow"]
OFF_ON = ["Off", "On"]
IPO_MODES = ["IPO", "AMP1", "AMP2"]
LEVELS = ["Off"] + ["%i" % level for level in range(1, 11)]
DG_IDS = ["%02i" % dg_id for dg_id in range(100)]

# USB: the model the radio reports and the size of its memory
MODEL_CODE = b"AH084M"
MEMORY_SIZE = 129011
BLOCK_SIZE = 1024
ACK = 0x06
# Address in the radio of info, home and memory
INFO_ADDRESS = 0x2079
HOME_ADDRESS = 0x28C0
MEMORY_ADDRESS = 0x70D6
ALL_CHANNELS = 1125
# What is read and written, as address and size: memory, then info and
# home
BLOCK_RANGES = [(MEMORY_ADDRESS, ALL_CHANNELS * MEM_SIZE),
                (INFO_ADDRESS, HOME_ADDRESS - INFO_ADDRESS),
                (HOME_ADDRESS, 5 * MEM_SIZE)]

# SD card files: offset of info and of memory in the body, and where
# the two parts of the body are in the image, as address and size
FILE_INFO = 0x0010
FILE_MEMORY = 0x0BD4
FILE_PARTS = [(INFO_ADDRESS - FILE_INFO, FILE_MEMORY),
              (MEMORY_ADDRESS, FILE_SIZE - HEADER_SIZE - FILE_MEMORY)]
# The format version, and how the body of a file starts: with the same
# version
FILE_VERSION = b"80"
FILE_BODY_START = bytes.fromhex("00000000500000000000000000000000")


def _decode(body):
    return bytes((byte - KEY[i % len(KEY)]) & 0xFF
                 for i, byte in enumerate(body))


def _encode(plain):
    return bytes((byte + KEY[i % len(KEY)]) & 0xFF
                 for i, byte in enumerate(plain))


def _to_file(value, current_code, from_file, to_file):
    """Return the file code for a CHIRP @value.

    Keeps @current_code if it already means @value, so that codes CHIRP
    cannot express (ARS ...) survive an edit of an unrelated field. A
    code that is not known at all reads as "".
    """
    if from_file.get(current_code, "") == value:
        return current_code
    return to_file[value]


def _switch(name, label, options, obj, field):
    """Describe a setting of mem.extra: @field of @obj holds the index
    into @options. @obj is None if the channel has no such setting."""
    return name, label, options, obj, field


# SD card files

def _is_file(data):
    """Tell a memory list file of the radio from an image"""
    start, length = TYPE_LINE
    # File type, format version and CRC
    fields = data[start:start + length].split()
    return (len(data) == FILE_SIZE and len(fields) == 3 and
            fields[0] == FILE_TYPE)


def _image_from_file(data):
    image = bytearray(MEMORY_SIZE)
    body = _decode(data[HEADER_SIZE:])
    offset = 0
    for address, size in FILE_PARTS:
        image[address:address + size] = body[offset:offset + size]
        offset += size
    return bytes(image)


def _file_from_image(image):
    body = bytearray().join(image[address:address + size]
                            for address, size in FILE_PARTS)
    if not any(body[:FILE_INFO]):
        # An image from the radio has nothing in front of info
        body[:FILE_INFO] = FILE_BODY_START
    body = _encode(body)
    crc = b"%08X" % zlib.crc32(body + CRC_TAIL)
    blank = b" " * (TYPE_LINE[1] - 2) + b"\r\n"
    line = b"  ".join([FILE_TYPE, FILE_VERSION, crc])
    return blank * 8 + line.ljust(len(blank) - 2) + b"\r\n" + body


def _has_all_channels(image):
    """A file ends within the 5 MHz channels. An image made from one
    holds zeros from there on, which a radio never does."""
    address, size = FILE_PARTS[-1]
    return any(image[address + size:MEMORY_ADDRESS + ALL_CHANNELS * MEM_SIZE])


# USB

def _checksum(data):
    return sum(data) & 0xFF


def _shift_bytes(data, by):
    """Add @by to every byte: how the radio hides the payload"""
    return bytes((byte + by) & 0xFF for byte in data)


def _command(pipe, command, reply_size):
    """Send @command, return the reply of @reply_size with its checksum
    and terminator checked and removed"""
    pipe.write(command + bytes([_checksum(command)]) + b";")
    reply = pipe.read(reply_size)
    if len(reply) != reply_size:
        raise errors.RadioError(
            "The radio did not answer (%i of %i bytes). Check the port, "
            "it has to be the Enhanced COM Port, and the CAT rate of the "
            "radio, it has to be 38400 bps." % (len(reply), reply_size))
    if reply[-1:] != b";" or reply[:2] != command[:2] or \
            reply[-2] != _checksum(reply[:-2]):
        LOG.debug("Bad reply to %r: %r", command[:3], reply[:16])
        raise errors.RadioError("The radio sent a damaged answer")
    return reply[:-2]


def _identify(pipe):
    """Make sure that the radio is an FTX-1 with the memory this driver
    knows"""
    reply = _command(pipe, b"A1", 8)
    size = int.from_bytes(_shift_bytes(reply[3:6], -reply[2]), "big")
    reply = _command(pipe, b"A2", 13)
    model = _shift_bytes(reply[3:9], -reply[2])
    LOG.info("Radio reports model %r, memory size %i", model, size)
    if model != MODEL_CODE or size != MEMORY_SIZE:
        raise errors.RadioError(
            "This is not an FTX-1 this driver knows (model %r, memory size "
            "%i)" % (model, size))


def _read_block(pipe, address, size):
    key = random.randint(0, 255)
    header = address.to_bytes(3, "big") + size.to_bytes(2, "big")
    reply = _command(pipe, b"A0R" + bytes([key]) + _shift_bytes(header, key),
                     2 + 1 + 1 + 5 + BLOCK_SIZE + 2)
    payload = _shift_bytes(reply[4:], -reply[3])
    if payload[:5] != header:
        raise errors.RadioError(
            "The radio answered with another block than asked for")
    return payload[5:5 + size]


def _write_block(pipe, address, data):
    key = random.randint(0, 255)
    payload = (address.to_bytes(3, "big") + len(data).to_bytes(2, "big") +
               data.ljust(BLOCK_SIZE, b"\x00"))
    reply = _command(pipe, b"A0W" + bytes([key]) + _shift_bytes(payload, key),
                     2 + 1 + 1 + 1 + 2)
    if _shift_bytes(reply[4:5], -reply[3]) != bytes([ACK]):
        raise errors.RadioError(
            "The radio refused block 0x%06X" % address)


def _blocks(ranges):
    """Return address and size of every block to transfer"""
    return [(address, min(BLOCK_SIZE, start + size - address))
            for start, size in ranges
            for address in range(start, start + size, BLOCK_SIZE)]


@directory.register
class FTX1Radio(chirp_common.CloneModeRadio):
    """Yaesu FTX-1"""
    VENDOR = "Yaesu"
    MODEL = "FTX-1"
    BAUD_RATE = 38400
    # The radio can key the transmitter with DTR
    WANTS_DTR = False
    FORMATS = [directory.register_format("Yaesu FTX-1 SD MemList", "*.dat")]

    _memsize = MEMORY_SIZE

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This driver is new and was not yet tested much. Keep a "
            "backup of your memories on the SD card of the radio (MEM "
            "LIST SAVE) before you upload.")
        rp.pre_download = rp.pre_upload = (
            "1. Connect the USB port of the radio to the computer.\n"
            "2. Select the Enhanced COM Port of the radio as port.\n"
            "3. Make sure that the CAT-1 RATE of the radio is 38400 bps.\n"
            "4. Click OK. After an upload the radio restarts.\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_tuning_step = False
        # Channels hold a frequency in Hz, on no step grid
        rf.has_nostep_tuning = True
        rf.has_dtcs_polarity = False
        rf.has_cross = False
        rf.has_settings = False
        rf.can_odd_split = True
        rf.memory_bounds = (1, MEMORIES)
        rf.valid_special_chans = list(PMS_NAMES)
        rf.valid_bands = [(30000, 174000000), (400000000, 470000000)]
        rf.valid_modes = [mode for mode, data in MODE_TO_FILE if not data]
        rf.valid_tmodes = list(TMODE_TO_FILE)
        rf.valid_duplexes = list(SHIFT_TO_FILE) + ["split"]
        rf.valid_skips = ["", "S"]
        rf.valid_name_length = NAME_LENGTH
        rf.valid_characters = chirp_common.CHARSET_ASCII
        return rf

    def _index(self, number):
        """Return the index of a memory or PMS channel in the radio"""
        if isinstance(number, str):
            if number not in PMS_NAMES:
                raise errors.InvalidMemoryLocation(
                    "Unknown channel %s" % number)
            return MEMORIES + PMS_NAMES.index(number)
        if not isinstance(number, int) or \
                not 1 <= number <= MEMORIES + len(PMS_NAMES):
            raise errors.InvalidMemoryLocation(
                "Number must be between 1 and %i" % (
                    MEMORIES + len(PMS_NAMES)))
        return number - 1

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[self._index(number)])

    def _extra_settings(self, _mem, index):
        """Return the settings of a channel beyond what a CHIRP memory has,
        see _switch(). They depend on the mode of the channel."""
        code = int(_mem.mode)
        group_name = MODE_GROUP.get(code)
        # C4FM and WFM have no mode group
        group = getattr(_mem, group_name) if group_name else None
        info = self._memobj.info

        settings = [
            _switch("agc", "AGC", AGC_MODES, group, "agc"),
            _switch("sdx", "S-DX", OFF_ON, _mem, "sdx"),
            _switch("ipo", "IPO", IPO_MODES, _mem, "ipo"),
            _switch("att", "ATT", OFF_ON, _mem, "att"),
            _switch("narrow", "Narrow", OFF_ON,
                    _mem if code in NARROW_FIELD else None,
                    NARROW_FIELD.get(code)),
            _switch("nb", "NB", LEVELS, _mem, "nb"),
            _switch("dnr", "DNR", LEVELS, _mem, "dnr"),
        ]
        for field, label in SWITCH_LABELS:
            has_switch = field in GROUP_SWITCHES.get(group_name, ())
            settings.append(_switch(field, label, OFF_ON,
                                    group if has_switch else None, field))
        settings += [
            _switch("rx_dgid", "RX DG-ID", DG_IDS, _mem, "rx_dgid"),
            _switch("tx_dgid", "TX DG-ID", DG_IDS, _mem, "tx_dgid"),
            _switch("tag", "Show name", OFF_ON, _mem, "tag"),
            _switch("mgrp", "M-GRP", OFF_ON, info.mgrp.channel, index),
        ]
        return settings

    @staticmethod
    def _shown(options, obj, field):
        """Return the index of the option a setting shows. A value the
        radio should not hold shows as the first one."""
        if obj is None:
            return 0
        value = int(obj[field] if isinstance(field, int)
                    else getattr(obj, field))
        return value if value < len(options) else 0

    def get_memory(self, number):
        index = self._index(number)
        mem = chirp_common.Memory()
        mem.number = index + 1
        if index >= MEMORIES:
            mem.extd_number = PMS_NAMES[index - MEMORIES]
        if not self._memobj.info.groups[GROUP_ALL].channel[index]:
            mem.empty = True
            return mem

        _mem = self._memobj.memory[index]
        mem.freq = int(_mem.freq)
        try:
            mem.mode, data = MODE_FROM_FILE[int(_mem.mode)]
        except KeyError:
            raise errors.RadioError(
                "Channel %i uses a mode this driver does not know yet "
                "(code %i)" % (mem.number, _mem.mode))
        # A record the radio never named holds no characters at all
        mem.name = "".join(
            chr(int(char)) if chr(int(char)) in chirp_common.CHARSET_ASCII
            else " " for char in _mem.name).rstrip()
        mem.skip = "S" if self._memobj.info.skip.channel[index] else ""
        mem.tmode = TMODE_FROM_FILE.get(int(_mem.sql), "")
        try:
            mem.rtone = mem.ctone = chirp_common.TONES[int(_mem.tone)]
            mem.dtcs = chirp_common.DTCS_CODES[int(_mem.dtcs)]
        except IndexError:
            raise errors.RadioError(
                "Channel %i holds a tone or DCS code this driver does not "
                "know (%i, %i)" % (mem.number, _mem.tone, _mem.dtcs))
        if _mem.split:
            mem.duplex = "split"
            mem.offset = int(_mem.split_freq)
        else:
            mem.duplex = SHIFT_FROM_FILE[int(_mem.shift)]
            # The radio uses its own repeater shift setting
            mem.offset = 0

        mem.extra = RadioSettingGroup("extra", "Extra")
        for name, label, options, obj, field in \
                self._extra_settings(_mem, index):
            value = RadioSettingValueList(
                options, current_index=self._shown(options, obj, field))
            # A setting the mode does not have is still there, read
            # only, because the UI expects it on every channel
            value.set_mutable(obj is not None)
            mem.extra.append(RadioSetting(name, label, value))
        value = RadioSettingValueList(OFF_ON, current_index=int(data))
        # Only LSB, USB and FM have a DATA mode
        value.set_mutable(mem.mode in DATA_MODES)
        mem.extra.append(RadioSetting("data", "Data", value))
        return mem

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.duplex in ("+", "-") and mem.offset:
            msgs.append(chirp_common.ValidationWarning(
                "The offset amount is not stored, the radio uses its own "
                "repeater shift setting"))
        return msgs

    def _set_used(self, index, used, group=None):
        """Mark a channel as used or erased, and as part of band @group"""
        info = self._memobj.info
        info.used.channel[index] = used
        info.groups[GROUP_ALL].channel[index] = used
        if used and group is not None and info.groups[group].channel[index]:
            # Still in its band group. The radio was seen to list channel
            # 1 in a second group as well, which is kept this way.
            return
        for band_group in sorted(set(g for _low, _high, g in BAND_GROUPS)):
            info.groups[band_group].channel[index] = (
                used and band_group == group)

    def set_memory(self, mem):
        index = self._index(mem.number)
        info = self._memobj.info
        if mem.empty:
            # Like the radio: the record stays, only the bits go
            self._set_used(index, False)
            info.skip.channel[index] = False
            info.mgrp.channel[index] = False
            info.groups[GROUP_MGRP].channel[index] = False
            return

        _mem = self._memobj.memory[index]
        if not info.groups[GROUP_ALL].channel[index]:
            # Do not inherit what an erased channel left behind
            _mem.set_raw(NEW_MEMORY)
            _mem.shift = SHIFT_TO_FILE[""]

        is_split = mem.duplex == "split"
        _mem.freq = mem.freq
        # A setting the mode did not have, when the channel was read, only
        # shows a placeholder. It must not end up in the mode of now.
        extra = {setting.get_name(): str(setting.value)
                 for setting in mem.extra or []
                 if setting.value.get_mutable()}
        data = extra.get("data") == "On" and mem.mode in DATA_MODES
        _mem.mode = _to_file((mem.mode, data), int(_mem.mode),
                             MODE_FROM_FILE, MODE_TO_FILE)
        for i, char in enumerate(mem.name[:NAME_LENGTH].ljust(NAME_LENGTH)):
            _mem.name[i] = ord(char)
        _mem.sql = _to_file(mem.tmode, int(_mem.sql),
                            TMODE_FROM_FILE, TMODE_TO_FILE)
        # A channel holds one tone, used for sending and for the squelch
        tone = mem.ctone if mem.tmode in ("TSQL", "TSQL-R") else mem.rtone
        _mem.tone = chirp_common.TONES.index(tone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        info.skip.channel[index] = mem.skip == "S"
        _mem.split = is_split
        _mem.split_freq = mem.offset if is_split else 0
        if not is_split:
            _mem.shift = _to_file(mem.duplex, int(_mem.shift),
                                  SHIFT_FROM_FILE, SHIFT_TO_FILE)

        # The settings of the mode the channel has now
        for name, _label, options, obj, field in \
                self._extra_settings(_mem, index):
            # What already shows as wanted is left alone, so that a value
            # this driver does not know survives
            if obj is None or name not in extra or \
                    extra[name] == options[self._shown(options, obj, field)]:
                continue
            if isinstance(field, int):
                obj[field] = options.index(extra[name])
            else:
                setattr(obj, field, options.index(extra[name]))
        # The memory group is a list of the radio as well
        info.groups[GROUP_MGRP].channel[index] = bool(
            info.mgrp.channel[index])

        groups = [group for low, high, group in BAND_GROUPS
                  if low <= mem.freq < high]
        self._set_used(index, True, groups[0] if groups else None)

    @classmethod
    def match_model(cls, filedata, filename):
        return _is_file(filedata) or super().match_model(filedata, filename)

    def load_mmap(self, filename):
        with open(filename, "rb") as f:
            data = f.read()
        if not _is_file(data):
            return super().load_mmap(filename)
        self._mmap = memmap.MemoryMapBytes(_image_from_file(data))
        self.process_mmap()

    def save_mmap(self, filename):
        if not filename.lower().endswith(".dat"):
            return super().save_mmap(filename)
        image = self._mmap.get_byte_compatible().get_packed()
        with open(filename, "wb") as f:
            f.write(_file_from_image(image))

    def _transfer(self, block_fn, message, ranges=BLOCK_RANGES):
        """Call block_fn(address, size) for every block of @ranges"""
        self.pipe.timeout = 5
        status = chirp_common.Status()
        status.msg = message
        try:
            # What the radio sent on its own, or after a transfer that
            # was given up, is no answer
            self.pipe.reset_input_buffer()
            _identify(self.pipe)
            blocks = _blocks(ranges)
            status.max = len(blocks)
            for number, (address, size) in enumerate(blocks, 1):
                block_fn(address, size)
                status.cur = number
                self.status_fn(status)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Transfer failed")
            raise errors.RadioError(
                "Failed to communicate with the radio: %s" % e)

    def sync_in(self):
        image = bytearray(MEMORY_SIZE)

        def read(address, size):
            image[address:address + size] = _read_block(
                self.pipe, address, size)

        self._transfer(read, "Reading from the radio")
        self._mmap = memmap.MemoryMapBytes(bytes(image))
        self.process_mmap()

    def sync_out(self):
        image = self._mmap.get_byte_compatible().get_packed()

        started = []

        def write(address, size):
            started.append(address)
            _write_block(self.pipe, address, image[address:address + size])

        ranges = list(BLOCK_RANGES)
        if not _has_all_channels(image):
            # Like the radio does when it loads a file
            ranges[0] = FILE_PARTS[-1]
        try:
            self._transfer(write, "Writing to the radio", ranges)
        except errors.RadioError as e:
            if not started:
                raise
            # The lists of the channels in use are written last
            raise errors.RadioError(
                "%s. The radio holds a part of the upload now, upload "
                "again before you use its memories." % e)
        # The radio takes the new memories over with a restart
        time.sleep(0.1)
        self.pipe.write(b"PS9;")

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
