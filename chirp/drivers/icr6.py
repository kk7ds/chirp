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


# TODO:
# Channel: Frequency setting
# Channel: TSQL freq or DTCS code with polarity
# Channel: Skip scan settings
# Channel: Comment (not sure if supported in ICF)
# Banks - channel assignment and name editing
# Validate TS by freq/band (e.g. 9k TS is only for AM brdcast. Airband?)
#   CS-R6 shows red X if setting invalid, use that to verify Chirp-output ICF
# Scan edges per manual
# Radio settings - lamp, delays, keytones, ...

# Notes:
#
# USA models have WX alert and block certain frequencies (see manual).

from chirp.drivers import icf
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings
#    RadioSettingValueInteger, \

mem_format = """
// Channel memories: 1300x 16-byte blocks
// 0x000 to 0x513F inclusive
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
  u8 name0;
  u8 name1;
  u8 name2;
  u8 name3;
  u8 name4;
} memory[1300];

// Unknown: 0x5140 to 0x5F7F inclusive
struct {
  u8 unknown0;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5;
  u8 unknown6;
  u8 unknown7;
  u8 unknown8;
  u8 unknown9;
  u8 unknown10;
  u8 unknown11;
  u8 unknown12;
  u8 unknown13;
  u8 unknown14;
  u8 unknown15;
} mystery1[200];

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

// Unknown
struct {
  u8 unknown0;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5;
  u8 unknown6;
  u8 unknown7;
  u8 unknown8;
  u8 unknown9;
  u8 unknown10;
  u8 unknown11;
  u8 unknown12;
  u8 unknown13;
  u8 unknown14;
  u8 unknown15;
} mystery1b[3];

// Channel control flags: 0x5F80 to 0x69A7 inclusive
struct {
  u8 hide_channel:1,  // Channel enable/disable aka show/hide
     skip:2,          // Scan skip: 0=No, 1 = "Skip", 3 = mem&vfo ("P")
     unknown0d:1,
     unknown0e:1,
     unknown0f:1,
     unknown0g:1,
     unknown0h:1;
  u8 unknown1;
} flags[1300];

// Eight bytes of Padding,  everything seems to work on 16-byte boundaries:
struct {
  u8 unknown0; // Start: 0x69A8
  u8 unknown1; // End:   0x69AF
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5;
  u8 unknown6;
  u8 unknown7;
} padding;

// Unknown: Coded as 34 blocks of 16-bytes. 0x69B0 to 0x6BCF
struct {
  u8 unknown0;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5;
  u8 unknown6;
  u8 unknown7;
  u8 unknown8;
  u8 unknown9;
  u8 unknown10;
  u8 unknown11;
  u8 unknown12;
  u8 unknown13;
  u8 unknown14;
  u8 unknown15;
} mystery2[34];

// Device Settings: 0x6bd0 to 0x6c0f
struct {
  u8 unknown00;  // 6bd0
  u8 unknown01;  // 6bd1
  u8 unknown02;  // 6bd2
  u8 unknown03;  // 6bd3
  u8 unknown04;  // 6bd4
  u8 unknown05;  // 6bd5
  u8 unknown06;  // 6bd6
  u8 unknown07;  // 6bd7
  u8 unknown08;  // 6bd8
  u8 unknown09;  // 6bd9
  u8 unknown10;  // 6bda
  u8 unknown11;  // 6bdb
  u8 unknown12;  // 6bdc
  u8 unknown13_6bdd:6,
     func_dial_step:2;    // 00=100kHz, 01=1MHz, 02=10MHz
  u8 unknown14;  // 6bde
  u8 unknown15_6bdf:7,
     key_beep:1;          // 0=Off, 1=On
  u8 unknown16_6be0:2,
     beep_level:6;        // 0x00=Volume, 0x01=00, 0x02=01, ..., 0x28=39
  u8 unknown17_6be1:6,
     back_light:2;        // 00=Off, 01=On, 02=Auto1, 03=Auto2
  u8 unknown18_6be2:7,
     power_save:1;        // 0=Off, 1=On
  u8 unknown17_6be3:7,
     am_ant:1;           // 0=Ext, 1=Bar
  u8 unknown20_6be4:7,
     fm_ant:1;           // 0=Ext, 1=Ear (headset lead)
  u8 unknown21;  // 6be5
  u8 unknown22;  // 6be6
  u8 unknown23;  // 6be7
  u8 unknown24;  // 6be8
  u8 unknown25;  // 6be9
  u8 unknown26;  // 6bea
  u8 unknown27;  // 6beb
  u8 unknown28;  // 6bec
  u8 unknown29;  // 6bed
  u8 unknown30;  // 6bee
  u8 unknown31;  // 6bef
  u8 unknown32;  // 6bf0
  u8 unknown33;  // 6bf1
  u8 civ_address;         // 6bf2: CI-V address, full byte
  u8 unknown35_6bf3:5,
     civ_baud_rate:3;     // 6bf3: Index to CIV_BAUD_RATES, range 0-5
  u8 unknown35_6bf4:7,
    civ_transceive:1;    // 6bf4: Report frequency and mode changes
  u8 unknown37;  // 6bf5
  u8 unknown38;  // 6bf6
  u8 unknown39;  // 6bf7
  u8 unknown40;  // 6bf8
  u8 unknown41;  // 6bf9
  u8 unknown42;  // 6bfa
  u8 unknown43;  // 6bfb
  u8 unknown44;  // 6bfc
  u8 unknown45;  // 6bfd
  u8 unknown46;  // 6bfe
  u8 unknown47;  // 6bff
  u8 unknown48;  // 6c00
  u8 unknown49;  // 6c01
  u8 unknown50;  // c602
  u8 unknown51;  // c603
  u8 unknown52h_6c04:3,   // Fixed 001 seen during tests
     dial_function:1,     // 0=Tuning Dial, 1=Audio Volume
     unknown52m_6c04:2,   // Fixed 10 seen during tests
     mem_display_type:2;  // 00=Freq, 01=BankName, 02=MemName, 03=ChNum
  u8 unknown54;  // 6c05
  u8 unknown55;  // 6c06
  u8 unknown56;  // 6c07
  u8 unknown57;  // 6c08
  u8 unknown58;  // 6c09
  u8 unknown59;  // 6c0a
  u8 unknown60;  // 6c0b
  u8 unknown61;  // 6c0c
  u8 unknown62;  // 6c0d
  u8 unknown63;  // 6c0e
  u8 unknown53;  // 6c0f
} settings;


// Unknown. Coded as 15 blocks of 16-bytes. 0x6C10 to 0x6CFF
struct {
  u8 unknown0;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5;
  u8 unknown6;
  u8 unknown7;
  u8 unknown8;
  u8 unknown9;
  u8 unknown10;
  u8 unknown11;
  u8 unknown12;
  u8 unknown13;
  u8 unknown14;
  u8 unknown15;
} mystery4[15];

// Device comment string. Grab it from the ICF?
struct { // Start: 6D00, End: 6D0F
  char comment[16];
} device_comment;

// 22x ASCII-coded bank names
// 0x6D10 to 0x6DBF inclusive
struct {
  char name[6];
  u8 unknown0; // Padding?
  u8 unknown1; // Padding?
} bank_names[22];

// ASCII-coded scan link names x10: 0x6DC0 to 0x6E0F
struct {
  char name[6];
  u8 unknown0;
  u8 unknown1;
} prog_scan_link_names[10];

// Unknown: Tail end of memory? 6E10 onwards
struct {  // Start: 6E10
  u8 unknown0;
} mystery5[64];

struct {
  // The string "IcomCloneFormat3" at end of block
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
TONES = (67.0,  69.3,  71.9,  74.4,  77.0,  79.7,  82.5,  85.4,
         88.5,  91.5,  94.8,  97.4, 100.0, 103.5, 107.2, 110.9,
         114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
         151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
         177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
         203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8,
         250.3, 254.1)

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
#  DTCS Codes:
#    023, 025, 026, 031, 032, 036, 043, 047,
#    051, 053, 054, 065, 071, 072, 073, 074,
#    114, 115, 116, 122, 125, 131, 132, 134,
#    143, 145, 152, 155, 156, 162, 165, 172, 174,
#    205, 212, 223, 225, 226, 243, 244, 245, 246,
#    251, 252, 255, 261, 263, 265, 266, 271, 274,
#    306, 311, 315, 325, 331, 332, 343, 346,
#    351, 356, 364, 365, 371,
#    411, 412, 413, 423, 431, 432, 445, 446,
#    452, 454, 455, 462, 464, 465, 466,
#    503, 506, 516, 523, 526, 532, 546, 565,
#    606, 612, 624, 627, 631, 632, 654, 662, 664,
#    703, 712, 723, 731, 732, 734, 743, 754
#  DTCS Polarity:

# The IC-R6 manual has | and , but these aren't recognised by CS-R6 and
# the front panel shows : and . instead so we're going with them.
# CS-R6 also accepts : and . (and will show same when reading from radio).
ICR6_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789()*+-./:= "

# Radio-coded alphabet. "^" is ivalid in IC-R6 so used here as a placeholder.
CODED_CHRS = " ^^^^^^^()*+^-./0123456789:^^=^^^ABCDEFGHIJKLMNOPQRSTUVWXYZ^^^^^"
NAME_LENGTH = 6

# Valid Rx Frequencies:
#   USA: 0.1–821.995, 851–866.995, 896–1309.995  MHz
#   France: 0.1–29.995, 50.2–51.2, 87–107.995, 144–146, 430–440, 1240–1300 MHz
#   Rest of World: 0.100–1309.995  MHz continuous

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

        # Bank names are ASCII-coded (unlike the channel names)
        # but restricted to certain characters. Validate:
        for c in name:
            if c not in ICR6_CHARSET:
                return

        _bank = self._model._radio._memobj.bank_names[self.index]
        _bank.name = name.rstrip()


@directory.register
class ICR6Radio(icf.IcomCloneModeRadio):
    """Icom IC-R6 Receiver - UK model"""
    VENDOR = "Icom"
    MODEL = "IC-R6"
    _model = "\x32\x50\x00\x01"
    _memsize = 0x6e5f
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
            print(f"Unknown freq multiplier: {_mem.freq_flags}")
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
        mem.name = CODED_CHRS[((_mem.name0 & 0x0F) << 2)
                              | ((_mem.name1 & 0xC0) >> 6)] + \
            CODED_CHRS[_mem.name1 & 0x3F] + \
            CODED_CHRS[(_mem.name2 & 0xFC) >> 2] + \
            CODED_CHRS[((_mem.name2 & 0x03) << 4)
                       | ((_mem.name3 & 0xF0) >> 4)] + \
            CODED_CHRS[((_mem.name3 & 0x0F) << 2)
                       | ((_mem.name4 & 0xC0) >> 6)] + \
            CODED_CHRS[(_mem.name4 & 0x3F)]
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

            print(f"EDGE: {flow} -> {fhigh}")
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

            # Tuning Step
            # p_ts = ["-", 5, 6.25, 8.33, 9, 10, 12.5, 15, 20,
            #        25, 30, 50, 100, 125, 200]

            # Attenuation
            # ndxt = 0
            # ndxm = 0
            # bxnd = 0
            # tsopt = ["-", "5k", "6.25k", "10k", "12.5k", "15k",
            #         "20k", "25k", "30k", "50k"]
            # mdopt = ["-", "FM", "FM-N"]
            # if fhigh > 0:
            #    if fhigh < 135.0:  # Air band
            #       bxnd = 1
            #       tsopt = ["-", "8.33k", "25k", "Auto"]
            #        ndxt = _pses[kx].tstp
            #        if ndxt == 0xe:     # Auto
            #            ndxt = 3
            #        elif ndxt == 8:     # 25k
            #            ndxt = 2
            #        elif ndxt == 2:     # 8.33k
            #            ndxt = 1
            #        else:
            #            ndxt = 0
            #        mdopt = ["-"]
            #    elif (flow >= 137.0) and (fhigh <= 174.0):   # VHF
            #        ndxt = _pses[kx].tstp - 1
            #        ndxm = _pses[kx].mode + 1
            #        bxnd = 2
            #    elif (flow >= 375.0) and (fhigh <= 550.0):  # UHF
            #        ndxt = _pses[kx].tstp - 1
            #        ndxm = _pses[kx].mode + 1
            #        bxnd = 3
            #    else:   # Mixed, ndx's = 0 default
            #        tsopt = ["-"]
            #        mdopt = ["-"]
            #        bxnd = 4
            #    if (ndxt > 9) or (ndxt < 0):
            #        ndxt = 0   # trap ff
            #    if ndxm > 2:
            #        ndxm = 0
            # # end if fhigh > 0
            # rx = RadioSettingValueList(tsopt, tsopt[ndxt])
            # rset = RadioSetting("pgmscanedge/%d.tstp" % kx,
            #                    "-- Scan %d Freq Step" % kx, rx)
            # rset.set_apply_callback(myset_tsopt, _pses, kx, "tstp", bxnd)
            # edges.append(rset)

            # rx = RadioSettingValueList(mdopt, mdopt[ndxm])
            # rset = RadioSetting("pgmscanedge/%d.mode" % kx,
            #                    "-- Scan %d Mode" % kx, rx)
            # rset.set_apply_callback(myset_mdopt, _pses, kx, "mode", bxnd)
            # edges.append(rset)
        # End for kx (Edges)

        # -------------------
        #   COMMON SETTINGS
        # -------------------

        # Set Mode - Func + Up/Down
        # Set Mode - Power Save
        # Set Mode - Dial Function
        # Sounds - Key Beep
        # Sounds - Beep level
        # Display - Backlight
        # Display - Memory Display Name

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

        # Scan - Program Skip Scan
        # Scan - Bank Link A-H
        # Scan - Bank Link I-P
        # Scan - Bank Link Q-Y
        # Scan - Pause Timer
        # Scan - Resume Timer
        # Scan - Stop Beep

        return group

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _flag = self._memobj.flags[mem.number]

        if mem.empty:
            _flag.hide_channel = 1
            return
        _flag.hide_channel = 0

        # Channel Names - 6x chars each coded via lookup and bitmapped...
        name_str = mem.name.strip("'").ljust(6)
        _mem.name0 = (CODED_CHRS.index(name_str[0]) & 0x3C) >> 2
        _mem.name1 = ((CODED_CHRS.index(name_str[0]) & 0x03) << 6) | \
                     (CODED_CHRS.index(name_str[1]) & 0x3F)
        _mem.name2 = (CODED_CHRS.index(name_str[2]) << 2) | \
                     ((CODED_CHRS.index(name_str[3]) & 0x30) >> 4)
        _mem.name3 = ((CODED_CHRS.index(name_str[3]) & 0x0F) << 4) | \
                     ((CODED_CHRS.index(name_str[4]) & 0x3C) >> 2)
        _mem.name4 = ((CODED_CHRS.index(name_str[4]) & 0x03) << 6) | \
                     (CODED_CHRS.index(name_str[5]) & 0x3F)

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
        #  - Logic needs more mapping for the common cases
        #  - 10/15/20/... k are stored as multiples of 5k
        #  - These are independent of TS
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
                # Can't be 9k, must be 5k
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
            print(f"Unknown freq multiplier: {_mem.freq_flags}")
            mem.freq = 1234567890
            mem.offset_l = mem.offset_h = 0

        # Memory scan skip
        if mem.skip == "":
            _flag.skip = 0
        elif mem.skip == "S":
            _flag.skip = 1     # memscan skip (aka "Skip")
        elif mem.skip == "P":
            _flag.skip = 3     # mem&vfo ("Pskip")
