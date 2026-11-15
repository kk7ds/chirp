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

"""Yaesu FTX-1 memory list files from the SD card.

The FTX-1 has no clone mode. It saves its memories to the SD card with
"MEM LIST SAVE" (FTX-1/MemList/*.dat) and reads them back with "MEM LIST
LOAD". This driver edits those files. The CAT commands of the radio
are not used: they can neither erase a channel nor reach the scan skip
setting.

File layout, found by comparing backups with what the radio reports
over CAT:

  0x000  eight lines of 62 spaces and CR LF
  0x200  "MemList  80  <CRC>" padded to a ninth such line
  0x240  the body, lightly obfuscated: a repeating 43 byte key is
         added to every byte, see KEY. <CRC> is the CRC-32 of the body
         as stored, followed by four constant bytes.

The decoded body holds, among data this driver leaves alone:

  0x0014 the channels in use, one bit per channel
  0x00A1 the channels a memory scan skips, one bit per channel
  0x0248 the channels in use again, then one such bitmap per band group
  0x0BD4 999 channels of 89 bytes

Erasing a channel only clears its bits, the radio keeps the record.

Known gaps:
  - a channel holds an AGC setting per group of modes, only the one of
    its own mode is shown. C4FM and WFM have no AGC setting.
  - apart from the AGC, the settings a channel holds per group of
    modes (the unknown bytes of ssb ... fm in the memory format,
    probably filters) are kept but not understood. A new channel gets
    the values the radio itself uses for a new channel.
  - the edges of the band groups are estimates between the frequencies
    that were tried
  - the repeater offset amount is a per-band radio setting, a channel
    only stores the shift direction
"""

import zlib

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList

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

MEM_FORMAT = """
// Settings a channel holds for a group of modes
struct mode_group {
  u8 unknown1:3,
     agc:3,
     unknown2:2;
  u8 unknown3[8];
};

// The bitmaps hold one bit per channel, channel 1 first
#seekto 0x0014;
lbit used_copy[1000];

#seekto 0x00A1;
lbit skip[1000];

#seekto 0x0248;
struct {
  lbit used[1000];
  u8 unknown[16];
} groups[6];

#seekto 0x0BD4;
struct {
  u8 mode;
  u8 sdx:1,
     unknown1:7;
  u8 shift:2,
     unknown2:6;
  u8 unknown3:4,
     split:1,
     sql:3;
  u8 unknown4;
  struct mode_group ssb;
  struct mode_group cw;
  struct mode_group rtty;
  struct mode_group data;       // DATA-L, DATA-U and PSK
  struct {
    u8 unknown1:3,
       agc:3,
       unknown2:2;
    u8 unknown3[4];
  } am;
  struct {
    u8 unknown1:3,
       agc:3,
       unknown2:2;
    u8 unknown3[3];
  } fm;                         // FM and DATA-FM
  u8 unknown5;
  u8 tone;
  u8 dtcs;
  u8 unknown6[2];
  u32 freq;
  u16 name[12];
  u32 split_freq;
  u8 unknown7[2];
} memory[999];
"""

MEM_SIZE = 89
NAME_LENGTH = 12

# groups[] index of the bitmap with every channel, and of the band group
# a frequency belongs to. Frequencies outside of these are in no band
# group.
GROUP_ALL = 0
BAND_GROUPS = [
    (1800000, 30000000, 1),         # HF
    (50000000, 54000000, 2),        # 6 m
    (108000000, 137000000, 3),      # air band
    (137000000, 174000000, 4),      # VHF
    (400000000, 470000000, 5),      # UHF
]

# A mode of the file as CHIRP mode and data flag: the DATA modes of the
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
    0x11: ("DN", False),        # C4FM-DN
    0x12: ("DN", False),        # C4FM-VW
    0x1D: ("WFM", False),
}
MODE_TO_FILE = {
    ("LSB", False): 0x00, ("USB", False): 0x01, ("CWR", False): 0x02,
    ("CW", False): 0x03, ("AM", False): 0x04, ("NAM", False): 0x05,
    ("FM", False): 0x06, ("NFM", False): 0x07, ("LSB", True): 0x08,
    ("USB", True): 0x09, ("FM", True): 0x0A, ("NFM", True): 0x0B,
    ("RTTY", False): 0x0C, ("RTTYR", False): 0x0D, ("FSK", False): 0x0E,
    ("DN", False): 0x11, ("WFM", False): 0x1D,
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
# channel. Only the AGC in there is understood, so the rest is copied
# as the radio writes it.
NEW_MODE_SETTINGS = bytes.fromhex(
    "04009600960bb80000" "040096009601f40000" "040096009601f40000"
    "04009600960c800000" "080096009604000000")
# A new channel: the mode groups start at byte 5 of the record
NEW_MEMORY = bytes(5) + NEW_MODE_SETTINGS + bytes(MEM_SIZE - 50)

# The mode group whose AGC a mode uses
AGC_GROUP = {
    0x00: "ssb", 0x01: "ssb",
    0x02: "cw", 0x03: "cw",
    0x0C: "rtty", 0x0D: "rtty",
    0x08: "data", 0x09: "data", 0x0E: "data",
    0x04: "am", 0x05: "am",
    0x06: "fm", 0x07: "fm", 0x0A: "fm", 0x0B: "fm",
}
AGC_MODES = ["Off", "Auto", "Fast", "Mid", "Slow"]
OFF_ON = ["Off", "On"]


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


@directory.register
class FTX1Radio(chirp_common.FileBackedRadio):
    """Yaesu FTX-1, memory list file from the SD card"""
    VENDOR = "Yaesu"
    MODEL = "FTX-1"
    FILE_EXTENSION = "dat"
    FORMATS = [directory.register_format("Yaesu FTX-1 SD MemList", "*.dat")]

    _upper = 999

    def __init__(self, pipe):
        super().__init__(None)
        self._header = None
        self._mmap = None
        self._memobj = None
        if isinstance(pipe, str):
            self.load(pipe)

    @classmethod
    def match_model(cls, filedata, filename):
        start, length = TYPE_LINE
        # File type, format version and CRC
        fields = filedata[start:start + length].split()
        return (len(filedata) == FILE_SIZE and len(fields) == 3 and
                fields[0] == FILE_TYPE)

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
        rf.memory_bounds = (1, self._upper)
        rf.valid_bands = [(30000, 174000000), (400000000, 470000000)]
        rf.valid_modes = [mode for mode, data in MODE_TO_FILE if not data]
        rf.valid_tmodes = list(TMODE_TO_FILE)
        rf.valid_duplexes = list(SHIFT_TO_FILE) + ["split"]
        rf.valid_skips = ["", "S"]
        rf.valid_name_length = NAME_LENGTH
        rf.valid_characters = chirp_common.CHARSET_ASCII
        return rf

    # File handling

    def load(self, filename):
        with open(filename, "rb") as f:
            data = f.read()
        self._header = data[:HEADER_SIZE]
        self._mmap = memmap.MemoryMapBytes(_decode(data[HEADER_SIZE:]))
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def save(self, filename):
        if self._mmap is None:
            raise errors.RadioError(
                "There is nothing to save, open a memory list file of the "
                "radio first")
        body = _encode(self._mmap.get_byte_compatible().get_packed())
        start, length = TYPE_LINE
        # File type and format version are kept, the CRC is replaced
        file_type, version = self._header[start:start + length].split()[:2]
        crc = b"%08X" % zlib.crc32(body + CRC_TAIL)
        line = b"  ".join([file_type, version, crc]).ljust(length - 2)
        with open(filename, "wb") as f:
            f.write(self._header[:start] + line + b"\r\n" + body)

    # Memories

    def _check_number(self, number):
        if not isinstance(number, int) or not 1 <= number <= self._upper:
            raise errors.InvalidMemoryLocation(
                "Number must be between 1 and %i" % self._upper)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def get_memory(self, number):
        self._check_number(number)
        mem = chirp_common.Memory()
        mem.number = number
        if not self._memobj.groups[GROUP_ALL].used[number - 1]:
            mem.empty = True
            return mem

        _mem = self._memobj.memory[number - 1]
        mem.freq = int(_mem.freq)
        try:
            mem.mode, data = MODE_FROM_FILE[int(_mem.mode)]
        except KeyError:
            raise errors.RadioError(
                "Channel %i uses a mode this driver does not know yet "
                "(code %i)" % (number, _mem.mode))
        mem.name = "".join(chr(int(char)) for char in _mem.name).rstrip()
        mem.skip = "S" if self._memobj.skip[number - 1] else ""
        mem.tmode = TMODE_FROM_FILE.get(int(_mem.sql), "")
        try:
            mem.rtone = mem.ctone = chirp_common.TONES[int(_mem.tone)]
            mem.dtcs = chirp_common.DTCS_CODES[int(_mem.dtcs)]
        except IndexError:
            raise errors.RadioError(
                "Channel %i holds a tone or DCS code this driver does not "
                "know (%i, %i)" % (number, _mem.tone, _mem.dtcs))
        if _mem.split:
            mem.duplex = "split"
            mem.offset = int(_mem.split_freq)
        else:
            mem.duplex = SHIFT_FROM_FILE[int(_mem.shift)]
            # The file holds no offset amount, the radio uses its own
            # repeater shift setting
            mem.offset = 0

        mem.extra = RadioSettingGroup("extra", "Extra")
        agc_group = AGC_GROUP.get(int(_mem.mode))
        if agc_group is not None:
            value = RadioSettingValueList(
                AGC_MODES, current_index=int(getattr(_mem, agc_group).agc))
        else:
            # C4FM and WFM have no AGC setting. The field is still there,
            # read only, because the UI expects it on every channel.
            value = RadioSettingValueList(
                AGC_MODES, current_index=AGC_MODES.index("Auto"))
            value.set_mutable(False)
        mem.extra.append(RadioSetting("agc", "AGC", value))
        mem.extra.append(RadioSetting(
            "sdx", "S-DX",
            RadioSettingValueList(OFF_ON, current_index=int(_mem.sdx))))
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

    def _set_used(self, number, used, group=None):
        """Mark a channel as used or erased, and as part of band @group"""
        index = number - 1
        self._memobj.used_copy[index] = used
        self._memobj.groups[GROUP_ALL].used[index] = used
        if used and group is not None and \
                self._memobj.groups[group].used[index]:
            # Still in its band group. The radio was seen to list channel
            # 1 in a second group as well, which is kept this way.
            return
        for _low, _high, band_group in BAND_GROUPS:
            self._memobj.groups[band_group].used[index] = (
                used and band_group == group)

    def set_memory(self, mem):
        self._check_number(mem.number)
        if mem.empty:
            # Like the radio: the record stays, only the bits go
            self._set_used(mem.number, False)
            self._memobj.skip[mem.number - 1] = False
            return

        _mem = self._memobj.memory[mem.number - 1]
        if not self._memobj.groups[GROUP_ALL].used[mem.number - 1]:
            # Do not inherit what an erased channel left behind
            _mem.set_raw(NEW_MEMORY)
            _mem.shift = SHIFT_TO_FILE[""]

        is_split = mem.duplex == "split"
        _mem.freq = mem.freq
        extra = {setting.get_name(): str(setting.value)
                 for setting in mem.extra or []}
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
        self._memobj.skip[mem.number - 1] = mem.skip == "S"
        _mem.split = is_split
        _mem.split_freq = mem.offset if is_split else 0
        if not is_split:
            _mem.shift = _to_file(mem.duplex, int(_mem.shift),
                                  SHIFT_FROM_FILE, SHIFT_TO_FILE)

        agc_group = AGC_GROUP.get(int(_mem.mode))
        if "sdx" in extra:
            _mem.sdx = OFF_ON.index(extra["sdx"])
        if "agc" in extra and agc_group is not None:
            getattr(_mem, agc_group).agc = AGC_MODES.index(extra["agc"])

        groups = [group for low, high, group in BAND_GROUPS
                  if low <= mem.freq < high]
        self._set_used(mem.number, True, groups[0] if groups else None)
