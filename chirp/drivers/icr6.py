"""Icom IC-R6 Driver"""
# Copyright 2024 John Bradshaw Mi0SYN <john@johnbradshaw.org>
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


# Notes:
# USA models have WX alert and block certain frequencies (see manual).

import logging

from chirp.drivers import icf
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings

LOG = logging.getLogger(__name__)

mem_format = """
// Channel memories: 1300x 16-byte blocks: 0x0000 to 0x513f inclusive
struct {
  u8 freq0;               // Freq: low byte
  u8 freq1;               // Freq: mid byte
  u8 freq_flags:6,        // Related to multiplier (step size)
     freq2:2;             // Freq: high bits - 18 bits total = step count
  u8 af_filter:1,         // AF Filter: 0=Off, 1=On
     attenuator:1,        // Attenuator: 0=Off, 1=On
     mode:2,              // Modulation: Index to "MODES"
     tuning_step:4;       // Freq tuning steps: Index to "STEPS"
  u8 unknown4ab:2,
     duplex:2,            // 0 = None, 1 = Minus, 2 = Plus
     unknown4e:1,
     tmode:3;             // TSQL/DTCS Setting: Index to "TONE_MODES"
  u8 offset_l;            // Offset - low value byte
  u8 offset_h;            // Offset - high value byte
  u8 unknown7:2,
     ctone:6;             // TSQL Index. Valid range: 0 to 49
  u8 unknown8;
  u8 canceller_freq_h;    // Canceller training freq index - high 8 bits
  u8 canceller_freq_l:1,  //                               - LSB
     unknown10m:4,
     vsc:1,               // Voice Squelch Control: 0=Off, 1=On
     canceller:2;         // USA-only Canceller option: Index to "CANCELLER"
  u8 name[5];             // 6 Chars coded into 5 bytes
} memory[1300];

#seekto 0x5dc0;           // Unknown: 0x5140 to 0x5f7f inclusive

// 25x Scan Edges with names - 0x5dc0 to 0x5f4f inclusive
// Mulitply the 32-bit by 3 to get freq in Hz
struct {
  u8 start0;      // LSB
  u8 start1;
  u8 start2;
  u8 start3;      // MSB
  u8 end0;        // LSB
  u8 end1;
  u8 end2;
  u8 end3;        // MSB
  u8 disabled:1,
     mode:3,      // 0=FM, 1=WFM, 2=AM, 4="-"
     ts:4;        // Same mapping as channel TS
  u8 unknown9a:2,
     attn:2,      // 0=Off, 1=On, 2="-"
     unknown9b:4;
  char name[6];
} pgmscanedge[25];

#seekto 0x5f80;       // Possibly padding

// Channel control flags: 0x5f80 to 0x69a7 inclusive
struct {
  u8 hide_channel:1,  // Channel enable/disable aka show/hide
     skip:2,          // Scan skip: 0=No, 1 = "Skip", 3 = mem&vfo ("P")
     unknown0:5;
  u8 unknown1;
} flags[1300];

#seekto 0x6bd0;           // 8 bytes padding then 34x16 bytes unknown

// Device Settings: 0x6bd0 to 0x6c0f
struct {
  u8 unknown[13];         // Bytes 0-12 inclusive
  u8 unknown13_6bdd:6,
     func_dial_step:2;    // 00=100kHz, 01=1MHz, 02=10MHz
  u8 unknown14;
  u8 unknown15_6bdf:7,
     key_beep:1;          // 0=Off, 1=On
  u8 unknown16_6be0:2,
     beep_level:6;        // 0x00=Volume, 0x01=00, 0x02=01, ..., 0x28=39
  u8 unknown17_6be1:6,
     back_light:2;        // 00=Off, 01=On, 02=Auto1, 03=Auto2
  u8 unknown18_6be2:7,
     power_save:1;        // 0=Off, 1=On
  u8 unknown17_6be3:7,
     am_ant:1;            // 0=Ext, 1=Bar
  u8 unknown20_6be4:7,
     fm_ant:1;            // 0=Ext, 1=Ear (headset lead)
  u8 unknown21[13];       // Bytes 21-33 inclusive
  u8 civ_address;         // 6bf2: CI-V address, full byte
  u8 unknown35_6bf3:5,
     civ_baud_rate:3;     // 6bf3: Index to CIV_BAUD_RATES, range 0-5
  u8 unknown35_6bf4:7,
    civ_transceive:1;     // 6bf4: Report frequency and mode changes
  u8 unknown37[15];       // Bytes 37-51
  u8 unknown52h_6c04:3,   // Fixed 001 seen during tests
     dial_function:1,     // 0=Tuning Dial, 1=Audio Volume
     unknown52m_6c04:2,   // Fixed 10 seen during tests
     mem_display_type:2;  // 00=Freq, 01=BankName, 02=MemName, 03=ChNum
  u8 unknown54[11];       // Bytes 54-63 inclusive
} settings;

#seekto 0x6d00;           // Unknown: 0x6c10 to 0x6cff

// Device comment string. Grab it from the ICF?
struct { // Start: 6d00, End: 6d0f
  char comment[16];
} device_comment;

// 22x ASCII-coded bank names - 0x6d10 to 0x6dbf inclusive
struct {
  char name[6];
  u8 padding[2];
} bank_names[22];

// 10x ASCII-coded scan link names - 0x6dc0 to 0x6e0f
struct {
  char name[6];
  u8 padding[2];
} prog_scan_link_names[10];

#seekto 0x6e50;     // Unknown - 0x6e10 to 0x6e4f

// The string "IcomCloneFormat3" at end of block
struct {
  char footer[16];
} footer;
"""

TONE_MODES = ["", "TSQL", "TSQL-R", "DTCS", "DTCS-R"]
#  Sub-audible tone settings:
#    "TSQL" (with pocket beep), "TSQL" (no beep),
#    "DTCS" (with pocket beep), "DTCS" (no beep),
#    "TQQL-R" (Tone Squelch Reverse),
#    "DTCS-R" (DTCS Reverse)”,
#    "OFF"
TONES = list(chirp_common.TONES)

# USA model have a Canceller function with various options and
# training frequencies. Fields only show in CS-R6 after importing ICF from
# a USA model. Range 300-3000 in steps of 10 (AF Hz?)
CANCELLER = ("Off", "Train1", "Train2", "MSK")
# For the freq: 9 bits split over 2 bytes.
#               Raw value is 30 (300Hz) to 300 (3000Hz)
#               Default on European model: 228 (2280 Hz) which matches CS-R6

DUPLEX_DIRS = ["", "-", "+"]  # Machine order

MODES = ["FM", "WFM", "AM", "Auto"]

STEPS = [5, 6.25, 8.333333, 9, 10, 12.5, 15, 20,
         25, 30, 50, 100, 125, 200, "Auto"]  # Index 15 is valid
# Note: 8.33k only within Air Band, 9k only within AM broadcast band

# Other per-channel settings from CS-R6
# DTCS_CODES = list(chirp_common.DTCS_CODES) - same 104 codes used
#  DTCS Polarity:

# The IC-R6 manual has | and , but these aren't recognised by CS-R6 and
# the front panel shows : and . instead so we'll go those (per radio & CS-R6).
ICR6_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789()*+-./:= "

# Radio-coded alphabet. "^" is ivalid in IC-R6 so used here as a placeholder.
CODED_CHRS = " ^^^^^^^()*+^-./0123456789:^^=^^^ABCDEFGHIJKLMNOPQRSTUVWXYZ^^^^^"
NAME_LENGTH = 6

# Valid Rx Frequencies - for now using Global:
#   USA: 0.1–821.995, 851–866.995, 896–1309.995  MHz
#   France: 0.1–29.995, 50.2–51.2, 87–107.995, 144–146, 430–440, 1240–1300 MHz
#   Global/Rest of World: 0.100–1309.995  MHz continuous

SQUELCH_LEVEL = ["Open", "Auto", "Level 1", "Level 2", "Level 3", "Level 4",
                 "Level 5", "Level 6", "Level 7", "Level 8", "Level 9"]


CIV_BAUD_RATES = ["300", "1200", "4800", "9600", "19200", "Auto"]

SKIPS = ["", "S", "?", "P"]


class ICR6Bank(icf.IcomBank):
    """ICR6 bank"""
    def get_name(self):
        _bank = self._model._radio._memobj.bank_names[self.index]
        return str(_bank.name).rstrip()

    def set_name(self, name):
        if len(name) > 6:
            return

        # ASCII-coded but restricted to certain characters. Validate:
        for c in name:
            if c not in ICR6_CHARSET:
                return

        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = name.rstrip()


@directory.register
class ICR6Radio(icf.IcomCloneModeRadio):
    """Icom IC-R6 Receiver - Global model"""
    VENDOR = "Icom"
    MODEL = "IC-R6"
    _model = "\x32\x50\x00\x01"
    _memsize = 0x6e60
    _ranges = [(0x0000, _memsize, 32)]
    _endframe = "Icom Inc\x2e73"

    _num_banks = 22
    _bank_class = ICR6Bank

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is currently under development, "
                           "and not all the features or functions may work as"
                           "expected. You should proceed with caution.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 1299)
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TONE_MODES)
        rf.valid_duplexes = list(DUPLEX_DIRS)
        rf.valid_bands = [(100000, 1309995000)]
        rf.valid_skips = ["", "S", "P"]  # Not 1:1 mapping
        rf.valid_characters = ICR6_CHARSET
        rf.valid_name_length = NAME_LENGTH
        rf.can_delete = True
        rf.has_ctone = True
        rf.has_dtcs = False           # TODO
        rf.has_dtcs_polarity = False  # TODO
        rf.has_bank = False           # TODO
        rf.has_bank_names = False     # TODO
        rf.has_name = True
        rf.has_settings = True
        rf.has_tuning_step = False  # hide in GUI, manage by code
        # rf.valid_tuning_steps = list(STEPS)
        # Attenuator = True
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _flag = self._memobj.flags[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _flag.hide_channel == 1:
            mem.empty = True
            return mem
        mem.empty = False

        if _mem.freq_flags == 0:
            mem.freq = 5000 * (_mem.freq2 * 256 * 256 +
                               _mem.freq1 * 256 +
                               int(_mem.freq0))
            mem.offset = 5000 * (_mem.offset_h * 256 + _mem.offset_l)
        elif _mem.freq_flags == 20:
            mem.freq = 6250 * (_mem.freq2 * 256 * 256 +
                               _mem.freq1 * 256 +
                               int(_mem.freq0))
            mem.offset = 6250 * ((_mem.offset_h * 256) + _mem.offset_l)
        elif _mem.freq_flags == 40:
            mem.freq = 8333.3333 * (_mem.freq2 * 256 * 256 +
                                    _mem.freq1 * 256 +
                                    int(_mem.freq0))
            mem.offset = 8333.3333 * ((_mem.offset_h * 256) + _mem.offset_l)
        elif _mem.freq_flags == 60:
            mem.freq = 9000 * (_mem.freq2 * 256 * 256 +
                               _mem.freq1 * 256 +
                               int(_mem.freq0))
            mem.offset = 9000 * ((_mem.offset_h * 256) + _mem.offset_l)
        else:
            LOG.exception(f"Unknown freq multiplier: {_mem.freq_flags}")
            mem.freq = 1234567890
            mem.offset = 0

        # mem.tuning_step = STEPS[_mem.tuning_step]
        mem.duplex = DUPLEX_DIRS[_mem.duplex]

        mem.ctone = TONES[_mem.ctone]
        mem.tmode = TONE_MODES[_mem.tmode]

        mem.mode = MODES[_mem.mode]

        # memory scan skip
        if _flag.skip == 0:
            mem.skip = ""      # None
        elif _flag.skip == 1:
            mem.skip = "S"     # memscan skip (aka "Skip")
        elif _flag.skip == 3:
            mem.skip = "P"     # 3 = mem&vfo ("Pskip")

        # Channel names are encoded in 6x 6-bit groups spanning 5 bytes.
        # Mask only the needed bits and then lookup character for each group
        # Mem format: 0000AAAA AABBBBBB CCCCCCDD DDDDEEEE EEFFFFFF
        mem.name = CODED_CHRS[((_mem.name[0] & 0x0f) << 2)
                              | ((_mem.name[1] & 0xc0) >> 6)] + \
            CODED_CHRS[_mem.name[1] & 0x3f] + \
            CODED_CHRS[(_mem.name[2] & 0xfc) >> 2] + \
            CODED_CHRS[((_mem.name[2] & 0x03) << 4)
                       | ((_mem.name[3] & 0xf0) >> 4)] + \
            CODED_CHRS[((_mem.name[3] & 0x0f) << 2)
                       | ((_mem.name[4] & 0xc0) >> 6)] + \
            CODED_CHRS[(_mem.name[4] & 0x3f)]
        mem.name = mem.name.rstrip(" ").strip("^")

        return mem

    def get_settings(self):
        """Translate the MEM_FORMAT structs into UI settings"""
        # Based on the Icom IC-2730 driver
        # Define mem struct write-back shortcuts
        _sets = self._memobj.settings
        _pses = self._memobj.pgmscanedge

        basic = RadioSettingGroup("basic", "Basic Settings")
        edges = RadioSettingGroup("edges", "Program Scan Edges")
        common = RadioSettingGroup("common", "Common Settings")

        group = RadioSettings(basic, edges, common)

        # ----------------------
        #   BASIC SETTINGS
        # ----------------------

        # ----------------------
        #   PROGRAM SCAN EDGES
        # ----------------------
        for kx in range(0, 25):
            stx = ""
            for i in range(0, 6):
                stx += chr(int(_pses[kx].name[i]))
            stx = stx.rstrip()
            rx = RadioSettingValueString(0, 6, stx)
            rset = RadioSetting("pgmscanedge/%d.name" % kx,
                                f"Program Scan {kx} Name", rx)
            # rset.set_apply_callback(myset_psnam, _pses, kx, "name", 6)
            edges.append(rset)

            # Freq (Hz) is 1/3 the raw value (expect this allows N x 8.333kHz)
            flow = 1.0 * (_pses[kx].start3 * 65536 * 256 +
                          _pses[kx].start2 * 65536 +
                          _pses[kx].start1 * 256 +
                          _pses[kx].start0) / 3e6
            fhigh = 1.0 * (_pses[kx].end3 * 65536 * 256 +
                           _pses[kx].end2 * 65536 +
                           _pses[kx].end1 * 256 +
                           _pses[kx].end0) / 3e6

            if (flow > 0) and (flow >= fhigh):
                flow, fhigh = fhigh, flow

            rx = RadioSettingValueFloat(0.1, 1309.995, flow, 0.010, 6)
            rset = RadioSetting("pgmscanedge/%d.lofreq" % kx,
                                f"-- Scan {kx} Low Limit", rx)
            # rset.set_apply_callback(myset_frqflgs, _pses, kx, "loflags",
            #                        "lofreq")
            edges.append(rset)

            rx = RadioSettingValueFloat(0.1, 1309.995, fhigh, 0.010, 6)
            rset = RadioSetting("pgmscanedge/%d.hifreq" % kx,
                                f"-- Scan {kx} High Limit", rx)
            # rset.set_apply_callback(myset_frqflgs, _pses, kx, "hiflags",
            #                        "hifreq")
            edges.append(rset)

        # -------------------------------
        #   COMMON SETTINGS - Incomplete
        # -------------------------------

        # Antenna - AM
        options = ["Ext", "Bar"]
        rx = RadioSettingValueList(options, options[_sets.am_ant])
        rset = RadioSetting("settings.am_ant", "AM Antenna", rx)
        common.append(rset)

        # Antenna - FM
        options = ["Ext", "Ear"]
        rx = RadioSettingValueList(options, options[_sets.fm_ant])
        rset = RadioSetting("settings.fm_ant", "FM Antenna", rx)
        common.append(rset)

        # CIV Address
        stx = str(_sets.civ_address)[2:]    # Hex value
        rx = RadioSettingValueString(1, 2, stx)
        rset = RadioSetting("settings.civ_address", "CI-V Address (7E)", rx)
        # rset.set_apply_callback(hex_val, _sets, "civ_address")
        common.append(rset)

        # CIV Baud:
        rx = RadioSettingValueList(CIV_BAUD_RATES,
                                   CIV_BAUD_RATES[_sets.civ_baud_rate])
        rset = RadioSetting("settings.civ_baud_rate", "CI-V Baud Rate", rx)
        common.append(rset)

        # CIV - Transmit frequency/mode changes
        rx = RadioSettingValueBoolean(bool(_sets.civ_transceive))
        rset = RadioSetting("settings.civ_transceive", "CI-V Transceive", rx)
        common.append(rset)

        return group

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flag = self._memobj.flags[mem.number]

        _flag.hide_channel = mem.empty
        if mem.empty:
            return

        # Channel Names - 6x chars each coded via lookup and bitmapped...
        name_str = mem.name.strip("'").ljust(6)
        _mem.name[0] = (CODED_CHRS.index(name_str[0]) & 0x3c) >> 2
        _mem.name[1] = ((CODED_CHRS.index(name_str[0]) & 0x03) << 6) | \
            (CODED_CHRS.index(name_str[1]) & 0x3f)
        _mem.name[2] = (CODED_CHRS.index(name_str[2]) << 2) | \
            ((CODED_CHRS.index(name_str[3]) & 0x30) >> 4)
        _mem.name[3] = ((CODED_CHRS.index(name_str[3]) & 0x0f) << 4) | \
            ((CODED_CHRS.index(name_str[4]) & 0x3c) >> 2)
        _mem.name[4] = ((CODED_CHRS.index(name_str[4]) & 0x03) << 6) | \
            (CODED_CHRS.index(name_str[5]) & 0x3f)

        if mem.ctone in TONES:
            _mem.ctone = TONES.index(mem.ctone)
        if mem.tmode in TONE_MODES:
            _mem.tmode = TONE_MODES.index(mem.tmode)

        _mem.mode = MODES.index(mem.mode)

        _mem.duplex = DUPLEX_DIRS.index(mem.duplex)

        #  Frequency: step size and count:
        #  - Some common multiples of 5k and 9k (i.e. 45k)
        #    are stored as 9k multiples. However if duplex is
        #    a 5k multiple (normally is) we must set 5k.
        #  - Logic needs more mapping for the common cases.
        #  - 10/15/20/... k are stored as multiples of 5k.
        #  - Step size is independent of TS.
        if mem.freq % 9000 == 0 and mem.freq % 5000 != 0:
            # 9k multiple but not 5k - use 9k
            _mem.freq_flags = 60

            _mem.freq0 = int(mem.freq / 9000) & 0x00ff
            _mem.freq1 = (int(mem.freq / 9000) & 0xff00) >> 8
            _mem.freq2 = (int(mem.freq / 9000) & 0x30000) >> 16

            _mem.offset_l = (int(mem.offset/9000) & 0x00ff)
            _mem.offset_h = (int(mem.offset/9000) & 0xff00) >> 8
        elif mem.freq % 5000 == 0 and mem.freq % 9000 != 0:
            # 5k multiple but not 9k - use 9k
            _mem.freq_flags = 0

            _mem.freq0 = int(mem.freq / 5000) & 0x00ff
            _mem.freq1 = (int(mem.freq / 5000) & 0xff00) >> 8
            _mem.freq2 = (int(mem.freq / 5000) & 0x30000) >> 16

            _mem.offset_l = (int(mem.offset/5000) & 0x00ff)
            _mem.offset_h = (int(mem.offset/5000) & 0xff00) >> 8
        elif mem.freq % 5000 == 0 and mem.freq % 9000 == 0:
            # 45k case
            if mem.offset/9000 != 0:
                # Can't be 9k, must be 5k for duplex/offset
                _mem.freq_flags = 0

                _mem.freq0 = int(mem.freq / 5000) & 0x00ff
                _mem.freq1 = (int(mem.freq / 5000) & 0xff00) >> 8
                _mem.freq2 = (int(mem.freq / 5000) & 0x30000) >> 16

                _mem.offset_l = (int(mem.offset/5000) & 0x00ff)
                _mem.offset_h = (int(mem.offset/5000) & 0xff00) >> 8
            else:
                # Go with 9k for now
                _mem.freq_flags = 60

                _mem.freq0 = int(mem.freq / 9000) & 0x00ff
                _mem.freq1 = (int(mem.freq / 9000) & 0xff00) >> 8
                _mem.freq2 = (int(mem.freq / 9000) & 0x30000) >> 16

                _mem.offset_l = (int(mem.offset/9000) & 0x00ff)
                _mem.offset_h = (int(mem.offset/9000) & 0xff00) >> 8
        elif mem.freq % 6250 == 0:
            _mem.freq_flags = 20

            _mem.freq0 = int(mem.freq / 6250) & 0x00ff
            _mem.freq1 = (int(mem.freq / 6250) & 0xff00) >> 8
            _mem.freq2 = (int(mem.freq / 6250) & 0x30000) >> 16

            _mem.offset_l = (int(mem.offset/6250) & 0x00ff)
            _mem.offset_h = (int(mem.offset/6250) & 0xff00) >> 8
        elif (mem.freq * 3) % 25000 == 0:  # 8333.3333333
            _mem.freq_flags = 40

            _mem.freq0 = int(mem.freq / 8330) & 0x00ff
            _mem.freq1 = (int(mem.freq / 8330) & 0xff00) >> 8
            _mem.freq2 = (int(mem.freq / 8330) & 0x30000) >> 16

            _mem.offset_l = (int(mem.offset/8330) & 0x00ff)
            _mem.offset_h = (int(mem.offset/8330) & 0xff00) >> 8

        else:
            LOG.exception(f"Can't find multiplier for freq {mem.freq} Hz")

        # Memory scan skip
        if mem.skip == "":
            _flag.skip = 0
        elif mem.skip == "S":
            _flag.skip = 1     # memscan skip (aka "Skip")
        elif mem.skip == "P":
            _flag.skip = 3     # mem&vfo ("Pskip")
