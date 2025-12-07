# Copyright 2025 Don Barber <don@dgb3.net>
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

# -*- coding: utf-8 -*-

# This is a CHIRP driver for the Yaesu VX-1r radio, released circa 1997.
# Please refer to the manual for the peculiarities of this radio
# such as the 8 bands and the difference between Configuration Group 1 and 2.

# The channel order in the UI is:
# The 8 band VFOs
# Channel Group 1 (CG1):
#     the 8 band home channels
#     52 channels (allowing duplex and complete tone settings)
#     10 lower and upper scan range memories
# Channel Group 2 (CG2):
#     the 8 band home channels
#     142 channels (simplex)
#     10 lower and upper scan range memories
# BC Band (BC):
#     1 Home channel
#     9 channels
# 31 Smart Search (SS) channels

# If you know what country codes 2, 4, or 7 represent, either contact me or
# submit a pull request.

# The radio is relatively easy to get into a state where it will not
# accept a clone-in and the radio will just return to the clone menu right
# after one starts sending bytes from the computer.
# This seems to happen after trying to turn on countries or features
# such as cellular rx and wide tx on radios that don't support them.
# One can try modifying the 'Match Mode' under settings to match the current
# mode of your radio. Sometimes even this doesn't seem to work though.
# In this event, I suggest doing a factory reset and starting from that image.
# You should be able to first download your old memories and then copy over to
# the new image before uploading the newly created image back to the radio.

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise, errors
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, RadioSettings
import logging

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
u8 match_mode;  // Must match radio's current active mode or default hardware mode for clone to be accepted.
u8 mode_byte;   // This is the radio's current mode (I think). It is how a new mode is set. 
#seekto 0x0002;
u8 band;

#seekto 0x0007;
struct {
  u8 unknown:1,
     bsyled:1,
     bclo:1,
     beep:1,
     scnl:1,
     resume:1,
     atmd:1,
     ars:1;
} config1;

struct {
  u8 lamp:2,
     apo:3,
     rxsave:3;
} config2;

struct {
  u8 lk:1,
     unknown1:2,
     lock:3,
     bell:2;
} config3;

struct {
  u8 artsbp:2,
     smtmd:1,
     tot:3,
     dialm:1,
     montc:1;
} config4;

struct {
  u8 unknown:6,
     grp:1,
     cwid:1;
} config5;

#seekto 0x000e;
struct {
  u8 unknown:4,
     dtmfm:4;
} config6;

#seekto 0x000f;
u8 volume;
u8 squelch;

#seekto 0x02f1;
u8 cwid_text[9];  // 8 chars max + stop byte (0x3d)

#seekto 0x0300;
u8 hardware_default_mode;  // Hardware default mode byte (read-only, for clone compatibility)
u8 requested_mode;  // Requested configuration (duplicate of 0x0001)

#seekto 0x0311;
struct {
  u8 freq[2];
  u8 name[2];
  u8 unknown[4];
} bc_vfo;

#seekto 0x03a1;
u8 priority_channel;

#seekto 0x11f1;
struct {
  u8 freq[2];  // BC band uses different frequency encoding
  u8 name[2];
  u8 unknown[4];
} bc_memory[10];

#seekto 0x1251;
struct {
  u8 dtmf[16];
} autodialer[8];

#seekto 0x0011;
struct {
  lbcd rx_freq[3];
  lbcd offset[3];
  u8 skip:1,
     name_flag:1,  // 0=display frequency, 1=display alpha name
     mode:2,
     shift:2,
     selcal:2;
  u8 unknown:3,
     power:1,
     clk_shift:1,
     step:3;
  u8 unknown2:2,
     ctcss:6;
  u8 dcs;
  u8 name[6];
} current;

#seekto 0x00a0;
u8 checksum1;

#seekto 0x00f1;
struct {
  lbcd rx_freq[3];
  lbcd offset[3];
  u8 skip:1,
     name_flag:1,  // 0=display frequency, 1=display alpha name
     mode:2,
     shift:2,
     selcal:2;
  u8 unknown:3,
     power:1,
     clk_shift:1,
     step:3;
  u8 unknown2:2,
     ctcss:6;
  u8 dcs;
  u8 name[6];
} smart_search[31];

#seekto 0x0321;
struct {
  lbcd rx_freq[3];
  lbcd offset[3];
  u8 skip:1,
     name_flag:1,  // 0=display frequency, 1=display alpha name
     mode:2,
     shift:2,
     selcal:2;
  u8 unknown:3,
     power:1,
     clk_shift:1,
     step:3;
  u8 unknown2:2,
     ctcss:6;
  u8 dcs;
  u8 name[6];
} vfos[8];

#seekto 0x03d1;
struct {
  lbcd rx_freq[3];
  u8 unknown;
  u8 skip:1,
     name_flag:1,  // 0=display frequency, 1=display alpha name
     mode:2,
     shift:2,
     selcal:2;
  u8 unknown2:3,
     power:1,
     clk_shift:1,
     step:3;
  u8 name[6];
} cg2_memory[170];

#seekto 0x0bd1;
struct {
  lbcd rx_freq[3];
  lbcd offset[3];
  u8 skip:1,
     name_flag:1,  // 0=display frequency, 1=display alpha name
     mode:2,
     shift:2,
     selcal:2;
  u8 unknown:3,
     power:1,
     clk_shift:1,
     step:3;
  u8 unknown2:2,
     ctcss:6;
  u8 dcs;
  u8 name[6];
} cg1_memory[80];

#seekto 0x10d1;
u8 cg2_band_mask[256];  // 8 bands × 32 bytes each for CG2

#seekto 0x10e7;
u8 cg1_band_mask[256];  // 8 bands × 32 bytes each for CG1

#seekto 0x12d1;
u8 checksum2;
"""

# Band frequency ranges (in Hz)
BAND_RANGES = [
    (76000000, 108000000, 0),      # FM broadcast
    (108000000, 137000000, 1),     # AIR
    (137000000, 170000000, 2),     # V-HAM
    (170000000, 222000000, 3),     # VHF-TV
    (222000000, 420000000, 4),     # ACT1
    (420000000, 470000000, 5),     # U-HAM
    (470000000, 800000000, 6),     # UHF-TV
    (800000000, 999000000, 7),     # ACT2
]

MODES = ["FM", "WFM", "AM"]  # VX-1R: FM-N=FM (12.5kHz), FM-W=WFM (broadcast), AM
TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
#Power levels stated are when plugged in.
#When not plugged in, these become .5 and .05, respectively.
POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=1),
                chirp_common.PowerLevel("Lo", watts=0.2)]
# Special channels: CG2-1 through CG2-170, CG1-1 through CG1-60, L1-L10/U1-U10, VFOs, Smart Search, BC Band
VFO_NAMES = ["VFO-BCBAND", "VFO-FM", "VFO-AIR", "VFO-V-HAM", "VFO-VHF-TV", "VFO-ACT1", "VFO-U-HAM", "VFO-UHF-TV", "VFO-ACT2"]
SMART_SEARCH_NAMES = ["SS-%d" % (i + 1) for i in range(0, 31)]
BC_NAMES = ["BC-%d" % (i + 1) for i in range(0, 9)]
CG2_HOME_NAMES = ["CG2-H-FM", "CG2-H-AIR", "CG2-H-V-HAM", "CG2-H-VHF-TV", "CG2-H-ACT1", "CG2-H-U-HAM", "CG2-H-UHF-TV", "CG2-H-ACT2"]
CG1_HOME_NAMES = ["CG1-H-FM", "CG1-H-AIR", "CG1-H-V-HAM", "CG1-H-VHF-TV", "CG1-H-ACT1", "CG1-H-U-HAM", "CG1-H-UHF-TV", "CG1-H-ACT2"]
SPECIALS = (VFO_NAMES +
            CG1_HOME_NAMES +
            ["CG1-%d" % (i + 1) for i in range(0, 52)] +
            ["CG1-%s%d" % (c, i + 1) for i in range(0, 10) for c in ('L', 'U')] +
            CG2_HOME_NAMES +
            ["CG2-%d" % (i + 1) for i in range(0, 142)] +
            ["CG2-%s%d" % (c, i + 1) for i in range(0, 10) for c in ('L', 'U')] +
            ["BC-H"] +
            BC_NAMES +
            SMART_SEARCH_NAMES)

# VX-1R character set
VX1_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ()+-=*/ΔΥΣ|-?%&_$¥\\﹨<>█∪⌋▆"

# DTMF character set
DTMF_CHARSET = "0123456789ABCD*#"

def _decode_dtmf(mem):
    """Decode 16-byte DTMF memory to string"""
    dtmf = ""
    for i in range(16):
        byte = mem[i]
        if byte == 0x3d:  # Stop byte
            break
        if byte == 0x28:  # Pause
            dtmf += "-"
        elif byte < len(DTMF_CHARSET):
            dtmf += DTMF_CHARSET[byte]
    return dtmf

def _encode_dtmf(dtmf_str):
    """Encode string to 16-byte DTMF memory"""
    encoded = []
    for i in range(16):
        if i < len(dtmf_str):
            char = dtmf_str[i].upper()
            if char == '-':
                encoded.append(0x28)
            elif char in DTMF_CHARSET:
                encoded.append(DTMF_CHARSET.index(char))
            else:
                encoded.append(0x3d)  # Invalid = stop
                break
        else:
            encoded.append(0x3d)  # Stop byte
    return encoded

def _decode_name(mem):
    """Decode 6-byte VX-1R name to string"""
    name = ""
    for i in range(6):
        if mem[i] == 0x3f:
            break
        if mem[i] < len(VX1_CHARSET):
            name += VX1_CHARSET[mem[i]]
        else:
            name += " "
    return name.rstrip()

def _decode_cwid(mem):
    """Decode 9-byte CW ID to string, stop byte is 0x3d"""
    name = ""
    for i in range(9):
        if mem[i] == 0x3d:  # Stop byte for CW ID
            break
        if mem[i] < len(VX1_CHARSET):
            name += VX1_CHARSET[mem[i]]
        else:
            name += " "
    return name.rstrip()

def _encode_cwid(name):
    """Encode string to 9-byte CW ID, max 8 chars, stop byte is 0x3d"""
    encoded = []
    name = name[:8]  # Limit to 8 characters
    
    # Encode the name characters
    for char in name:
        char = char.upper()
        try:
            encoded.append(VX1_CHARSET.index(char))
        except ValueError:
            encoded.append(VX1_CHARSET.index('_'))  # Unknown = underscore
    
    # Add stop byte
    encoded.append(0x3d)
    
    # Pad to 9 bytes with zeros
    while len(encoded) < 9:
        encoded.append(0x00)
    
    return encoded


def _encode_name(name, length=6):
    """Encode string to VX-1R name (default 6 bytes, or specify length)"""
    encoded = []
    for i in range(length):
        if i < len(name):
            char = name[i].upper()
            try:
                encoded.append(VX1_CHARSET.index(char))
            except ValueError:
                encoded.append(VX1_CHARSET.index('_'))  # Unknown = underscore
        else:
            encoded.append(0x3f)  # Empty/padding
    return encoded


class VX1Checksum(yaesu_clone.YaesuChecksum):
    """VX-1R Checksum at 0x12d1: (0xe0 - sum) & 0xff, +0x03 if high byte >= 0x80"""
    def get_calculated(self, mmap):
        mmap = self._asbytes(mmap)
        cs = 0
        for i in range(self._start, self._stop + 1):
            cs += mmap[i][0]
        result = (0xe0 - cs) & 0xff
        if (cs >> 8) & 0xff >= 0x80:
            result = (result + 0x03) & 0xff
        return result


class VX1Checksum2(yaesu_clone.YaesuChecksum):
    """VX-1R Checksum at 0x00a0: (sum + 0x20) & 0xff, -0x03 if sum1 high byte >= 0x80
    Calculated first with both 0x00a0 and 0x12d1 zeroed."""
    def get_calculated(self, mmap):
        mmap = self._asbytes(mmap)
        # Calculate sum1 with both checksums zeroed to determine adjustment
        sum1 = sum(mmap[i][0] for i in range(0x0000, 0x12d1) if i not in (0x00a0, 0x12d1))
        cs = 0
        for i in range(self._start, self._stop + 1):
            cs += mmap[i][0]
        result = (cs + 0x20) & 0xff
        if (sum1 >> 8) & 0xff >= 0x80:
            result = (result - 0x03) & 0xff
        return result


@directory.register
class VX1Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-1R"""
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "VX-1R"

    _model = b""
    _memsize = 4818
    _block_lengths = [4818]
    _block_size = 32

    def _checksums(self):
        return [VX1Checksum2(0x0000, 0x009f, 0x00a0),
                VX1Checksum(0x0000, 0x12d0, 0x12d1)]
    
    def _get_band_index(self, freq):
        """Determine which band a frequency belongs to"""
        for low, high, band_idx in BAND_RANGES:
            if low <= freq < high:
                return band_idx
        return None
    
    def _get_extra(self, _mem, mem):
        """Get extra settings for memory"""
        # Always create RadioSettingGroup to override default empty list
        mem.extra = RadioSettingGroup("extra", "Extra")
        
        # Skip BC VFO (1) and BC band (260-269) - no extra settings
        if mem.number == 1 or (260 <= mem.number <= 269):
            return
        
        # Display mode (frequency vs alpha name)
        if hasattr(_mem, 'name_flag'):
            rs = RadioSetting("name_flag", "Display Mode",
                             RadioSettingValueList(
                                 ["Frequency", "Alpha Name"],
                                 current_index=_mem.name_flag))
            mem.extra.append(rs)
        
        # Only CG1 and CG2 have clk_shift
        if hasattr(_mem, 'clk_shift'):
            rs = RadioSetting("clk_shift", "Clock Shift",
                             RadioSettingValueBoolean(_mem.clk_shift))
            mem.extra.append(rs)
    
    def _set_extra(self, _mem, mem):
        """Set extra settings for memory"""
        if mem.extra and hasattr(mem.extra, '__iter__'):
            for setting in mem.extra:
                if hasattr(_mem, setting.get_name()):
                    setattr(_mem, setting.get_name(), setting.value)
    
    def _update_band_mask(self, mem_idx, band_idx, value, is_cg2=False):
        """Update band mask bit for a memory
        algorithm: off = (i - 8) / 8, bit = (i - 8) % 8
        where i is the memory index in the array (0-79 for CG1, 0-169 for CG2)
        """
        # Adjust index: subtract 8 for regular channels (skip home channels in calculation)
        adjusted_idx = mem_idx - 8 if mem_idx >= 8 else mem_idx
        byte_offset = adjusted_idx // 8
        bit_offset = adjusted_idx % 8
        mask = 1 << bit_offset
        
        if is_cg2:
            band_masks = self._memobj.cg2_band_mask
        else:
            band_masks = self._memobj.cg1_band_mask
        
        # Update only this memory's bit in all bands
        for b in range(8):
            idx = b * 32 + byte_offset + 1
            if b == band_idx:
                # Set the bit for the correct band
                band_masks[idx] |= mask
            else:
                # Clear the bit for other bands
                band_masks[idx] &= ~mask

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs_polarity = False
        rf.has_settings = True
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_tuning_steps = STEPS
        rf.valid_duplexes = DUPLEX
        rf.memory_bounds = (1, 0)  # No numeric memories, all are special
        rf.valid_bands = [(500000, 999000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 6
        rf.valid_characters = VX1_CHARSET
        rf.valid_special_chans = SPECIALS
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        
        # Handle string input
        if isinstance(number, str):
            # Parse VFO names
            if number in VFO_NAMES:
                vfo_idx = VFO_NAMES.index(number)
                number = 1 + vfo_idx
                mem.extd_number = VFO_NAMES[vfo_idx]
            # Parse CG1 home channels
            elif number in CG1_HOME_NAMES:
                number = 10 + CG1_HOME_NAMES.index(number)
                mem.extd_number = CG1_HOME_NAMES[number - 10]
            # Parse "CG1-1" through "CG1-52"
            elif number.startswith("CG1-") and not number[4] in ['L', 'U', 'H']:
                ch_num = int(number[4:])
                if 1 <= ch_num <= 52:
                    number = 17 + ch_num
                    mem.extd_number = "CG1-%d" % ch_num
                else:
                    raise errors.InvalidMemoryLocation("Invalid CG1 channel: %s" % number)
            # Parse "CG1-L1" through "CG1-L10" or "CG1-U1" through "CG1-U10"
            elif number.startswith("CG1-") and number[4] in ['L', 'U']:
                pair = int(number[5:])
                if 1 <= pair <= 10:
                    is_upper = (number[4] == 'U')
                    number = 69 + (pair - 1) * 2 + (1 if is_upper else 0) + 1
                    mem.extd_number = "CG1-%s%d" % ('U' if is_upper else 'L', pair)
                else:
                    raise errors.InvalidMemoryLocation("Invalid CG1 band limit: %s" % number)
            # Parse CG2 home channels
            elif number in CG2_HOME_NAMES:
                number = 90 + CG2_HOME_NAMES.index(number)
                mem.extd_number = CG2_HOME_NAMES[number - 90]
            # Parse "CG2-1" through "CG2-142"
            elif number.startswith("CG2-") and not number[4] in ['L', 'U', 'H']:
                ch_num = int(number[4:])
                if 1 <= ch_num <= 142:
                    number = 97 + ch_num
                    mem.extd_number = "CG2-%d" % ch_num
                else:
                    raise errors.InvalidMemoryLocation("Invalid CG2 channel: %s" % number)
            # Parse "CG2-L1" through "CG2-L10" or "CG2-U1" through "CG2-U10"
            elif number.startswith("CG2-") and number[4] in ['L', 'U']:
                pair = int(number[5:])
                if 1 <= pair <= 10:
                    is_upper = (number[4] == 'U')
                    number = 239 + (pair - 1) * 2 + (1 if is_upper else 0) + 1
                    mem.extd_number = "CG2-%s%d" % ('U' if is_upper else 'L', pair)
                else:
                    raise errors.InvalidMemoryLocation("Invalid CG2 band limit: %s" % number)
            # Parse BC home
            elif number == "BC-H":
                number = 260
                mem.extd_number = "BC-H"
            # Parse BC band channels
            elif number.startswith("BC-") and number != "BC-H":
                bc_num = int(number[3:])
                if 1 <= bc_num <= 9:
                    number = 260 + bc_num
                    mem.extd_number = "BC-%d" % bc_num
                else:
                    raise errors.InvalidMemoryLocation("Invalid BC band: %s" % number)
            # Parse smart search channels
            elif number.startswith("SS-"):
                ss_num = int(number[3:])
                if 1 <= ss_num <= 31:
                    number = 269 + ss_num
                    mem.extd_number = "SS-%d" % ss_num
                else:
                    raise errors.InvalidMemoryLocation("Invalid smart search: %s" % number)
            else:
                raise errors.InvalidMemoryLocation("Invalid memory: %s" % number)
        
        mem.number = number

        # Memory layout: VFOs, CG1, CG2, BC, SS
        # VFOs: 1-9 (FM, AIR, V-HAM, VHF-TV, ACT1, U-HAM, UHF-TV, ACT2, BCBAND)
        # CG1: 10-17 home, 18-69 regular (52), 70-89 band limits (20)
        # CG2: 90-97 home, 98-239 regular (142), 240-259 band limits (20)
        # BC: 260 home, 261-269 regular (9)
        # SS: 270-300 (SS-1 through SS-31)
        # BC: 260 home, 261-269 regular (9)
        # SS: 270-300 (SS-1 through SS-31)
        if number <= 9:
            # VFOs (BC band VFO first, then regular VFOs)
            vfo_idx = number - 1
            if vfo_idx == 0:
                # BC band VFO
                _mem = self._memobj.bc_vfo
                has_offset = False
            else:
                # Regular VFOs (FM, AIR, etc.) - map to indices 0-7 in vfos array
                _mem = self._memobj.vfos[vfo_idx - 1]
                has_offset = True
            if not hasattr(mem, 'extd_number'):
                mem.extd_number = VFO_NAMES[vfo_idx]
        elif number <= 89:
            # CG1: home (10-17) + regular (18-69) + band limits (70-89)
            cg1_idx = number - 10  # Maps to CG1 memory indices 0-79
            _mem = self._memobj.cg1_memory[cg1_idx]
            has_offset = True
            
            # Set extended number
            if not hasattr(mem, 'extd_number'):
                if number <= 17:
                    mem.extd_number = CG1_HOME_NAMES[number - 10]
                elif number > 69:
                    # CG1 band limits
                    bl_idx = number - 70
                    pair = bl_idx // 2 + 1
                    is_upper = bl_idx % 2 == 1
                    mem.extd_number = "CG1-%s%d" % ('U' if is_upper else 'L', pair)
                else:
                    # Regular CG1 channels
                    mem.extd_number = "CG1-%d" % (number - 17)
        elif number <= 259:
            # CG2: home (90-97) + regular (98-239) + band limits (240-259)
            cg2_idx = number - 90  # Maps to CG2 memory indices 0-169
            _mem = self._memobj.cg2_memory[cg2_idx]
            has_offset = False
            if not hasattr(mem, 'extd_number'):
                if number <= 97:
                    mem.extd_number = CG2_HOME_NAMES[number - 90]
                elif number > 239:
                    # CG2 band limits
                    bl_idx = number - 240
                    pair = bl_idx // 2 + 1
                    is_upper = bl_idx % 2 == 1
                    mem.extd_number = "CG2-%s%d" % ('U' if is_upper else 'L', pair)
                else:
                    mem.extd_number = "CG2-%d" % (number - 97)
        elif number <= 269:
            # BC band: 260 home, 261-269 regular
            bc_idx = number - 260  # Maps to BC memory indices 0-9
            _mem = self._memobj.bc_memory[bc_idx]
            has_offset = False
            if not hasattr(mem, 'extd_number'):
                if bc_idx == 0:
                    mem.extd_number = "BC-H"
                else:
                    mem.extd_number = "BC-%d" % bc_idx
        else:
            # Smart search: 270-300
            ss_idx = number - 270
            _mem = self._memobj.smart_search[ss_idx]
            has_offset = True
            if not hasattr(mem, 'extd_number'):
                mem.extd_number = "SS-%d" % (ss_idx + 1)

        # Check if memory is empty (first byte is 0xff for all memory types)
        if isinstance(_mem.get_raw()[0], int):
            first_byte = _mem.get_raw()[0]
        else:
            first_byte = ord(_mem.get_raw()[0])
        
        if first_byte == 0xff:
            mem.empty = True
            self._get_extra(_mem, mem)
            return mem

        # BC band VFO uses different frequency encoding (2-byte, 500-1710 kHz)
        if number == 1:  # BC band VFO
            freq_mhz = 0.5 + (_mem.freq[0] * (1.2 / 254.0))
            mem.freq = int(freq_mhz * 1000000)
            mem.name = ""
            mem.mode = "AM"
            mem.skip = ""
            mem.power = POWER_LEVELS[0]
            # Second byte is tuning step in BCD (e.g., 0x40 = 4.0 kHz)
            step_bcd = _mem.freq[1]
            mem.tuning_step = float((step_bcd >> 4) * 10 + (step_bcd & 0x0f)) / 10.0
            mem.duplex = ""
            mem.offset = 0
            self._get_extra(_mem, mem)
            return mem

        # BC band memories use same encoding as BC VFO
        if number >= 260 and number <= 269:  # BC band (including home)
            freq_mhz = 0.5 + (_mem.freq[0] * (1.2 / 254.0))
            mem.freq = int(freq_mhz * 1000000)
            mem.name = _decode_name(_mem.name)  # BC band has 2-byte name, _decode_name handles it
            mem.mode = "AM"
            mem.skip = ""
            mem.power = POWER_LEVELS[0]
            # Second byte is tuning step in BCD (e.g., 0x40 = 4.0 kHz)
            step_bcd = _mem.freq[1]
            mem.tuning_step = float((step_bcd >> 4) * 10 + (step_bcd & 0x0f)) / 10.0
            mem.duplex = ""
            mem.offset = 0
            self._get_extra(_mem, mem)
            return mem

        mem.freq = int(_mem.rx_freq) * 1000
        mem.name = _decode_name(_mem.name)
        mem.mode = MODES[_mem.mode]
        mem.skip = "S" if _mem.skip else ""
        mem.power = POWER_LEVELS[1 - _mem.power]
        mem.tuning_step = STEPS[_mem.step]
        
        if has_offset:
            mem.duplex = DUPLEX[_mem.shift]
            # Normal: offset field contains offset amount
            # Odd split: offset field contains TX frequency
            mem.offset = int(_mem.offset) * 1000
            mem.tmode = TMODES[_mem.selcal]
            mem.rtone = mem.ctone = chirp_common.OLD_TONES[_mem.ctcss]
            mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        else:
            mem.duplex = ""
            mem.offset = 0

        self._get_extra(_mem, mem)
        return mem

    def set_memory(self, mem):
        number = mem.number
        
        # String input already converted by get_memory, but handle if called directly
        if isinstance(number, str):
            # Reuse parsing from get_memory - this shouldn't normally happen
            raise errors.InvalidMemoryLocation("set_memory received string: %s" % number)
        
        if number <= 9:
            # VFOs (BC band VFO first, then regular VFOs)
            vfo_idx = number - 1
            if vfo_idx == 0:
                # BC band VFO
                _mem = self._memobj.bc_vfo
                has_offset = False
            else:
                # Regular VFOs - map to indices 0-7 in vfos array
                _mem = self._memobj.vfos[vfo_idx - 1]
                has_offset = True
        elif number <= 89:
            # CG1: home + regular + band limits
            _mem = self._memobj.cg1_memory[number - 10]
            has_offset = True
        elif number <= 259:
            # CG2: home + regular + band limits
            _mem = self._memobj.cg2_memory[number - 90]
            has_offset = False
        elif number <= 269:
            # BC band: 260 home, 261-269 regular
            _mem = self._memobj.bc_memory[number - 260]
            has_offset = False
        else:
            # Smart search: 270-300
            _mem = self._memobj.smart_search[number - 270]
            has_offset = True

        if mem.empty:
            # Set only first byte to 0xff (radio behavior - leaves rest of data intact)
            if number >= 10 and number <= 89:
                # CG1
                offset = 0x0bd1 + (number - 10) * 16
            elif number >= 90 and number <= 259:
                # CG2
                offset = 0x03d1 + (number - 90) * 12
            elif number == 1:
                # BC VFO
                offset = 0x0311
            elif number >= 260 and number <= 269:
                # BC band
                offset = 0x11f1 + (number - 260) * 8
            elif number >= 2 and number <= 9:
                # VFOs
                offset = 0x0321 + (number - 2) * 16
            elif number >= 270 and number <= 300:
                # Smart Search
                offset = 0x00f1 + (number - 270) * 16
            else:
                return  # Home channels can't be erased
            
            self._mmap[offset] = 0xff
            return

        # BC band VFO uses different frequency encoding
        if number == 1:
            freq_khz = mem.freq / 1000
            byte_val = int(((freq_khz - 500) / 1000.0) / (1.2 / 254.0) + 0.5)
            _mem.freq[0] = min(byte_val, 0xfe)
            # Encode tuning step as BCD (e.g., 4.0 kHz = 0x40)
            step_int = int(mem.tuning_step * 10)  # 4.0 -> 40
            _mem.freq[1] = ((step_int // 10) << 4) | (step_int % 10)
            # BC VFO has 2-byte name field
            name_bytes = _encode_name(mem.name[:2] if mem.name else "", length=2)
            _mem.name[0] = name_bytes[0]
            _mem.name[1] = name_bytes[1]
            return

        # BC band memories use same encoding
        if number >= 260 and number <= 269:
            freq_khz = mem.freq / 1000
            byte_val = int(((freq_khz - 500) / 1000.0) / (1.2 / 254.0) + 0.5)
            _mem.freq[0] = min(byte_val, 0xfe)
            # Encode tuning step as BCD (e.g., 4.0 kHz = 0x40)
            step_int = int(mem.tuning_step * 10)  # 4.0 -> 40
            _mem.freq[1] = ((step_int // 10) << 4) | (step_int % 10)
            # Encode name (only 2 bytes for BC band)
            name_bytes = _encode_name(mem.name[:2] if mem.name else "", length=2)
            _mem.name[0] = name_bytes[0]
            _mem.name[1] = name_bytes[1]
            return

        _mem.rx_freq = mem.freq / 1000
        _mem.name = _encode_name(mem.name)
        _mem.mode = MODES.index(mem.mode)
        _mem.skip = 1 if mem.skip == "S" else 0
        _mem.power = 1 - POWER_LEVELS.index(mem.power) if mem.power else 0
        _mem.step = STEPS.index(mem.tuning_step)
        
        # Set extra fields first (may include name_flag override)
        self._set_extra(_mem, mem)
        
        # Set name_flag based on name presence if not overridden by extra
        if not (mem.extra and any(s.get_name() == 'name_flag' for s in mem.extra if hasattr(s, 'get_name'))):
            _mem.name_flag = 1 if mem.name else 0
        else:
            # Extra setting exists, keep whatever was set
            pass

        if has_offset:
            _mem.shift = DUPLEX.index(mem.duplex)
            # For split mode, offset contains TX frequency; otherwise it's an offset
            _mem.offset = mem.offset / 1000
            _mem.selcal = TMODES.index(mem.tmode)
            try:
                _mem.ctcss = chirp_common.OLD_TONES.index(mem.rtone)
            except ValueError:
                _mem.ctcss = 0
            try:
                _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
            except ValueError:
                _mem.dcs = 0

        # Update band mask based on frequency (must be last, after all fields set)
        if number >= 10 and number <= 89:
            # CG1 memory
            mem_idx = number - 10  # 0-79
            band_idx = self._get_band_index(mem.freq)
            if band_idx is not None:
                self._update_band_mask(mem_idx, band_idx, True, is_cg2=False)
        elif number >= 90 and number <= 259:
            # CG2 memory
            mem_idx = number - 90  # 0-169
            band_idx = self._get_band_index(mem.freq)
            if band_idx is not None:
                self._update_band_mask(mem_idx, band_idx, True, is_cg2=True)

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        
        # CG2 memories (90-259) and BC band (1, 260-269) don't support offset
        if mem.number == 1 or (90 <= mem.number <= 269):
            if mem.duplex:
                mem.duplex = ""
                msgs.append(chirp_common.ValidationWarning(
                    "Duplex not supported for this memory type"))
            if mem.offset:
                mem.offset = 0
        
        return msgs

    def erase_memory(self, number):
        # Convert special channel name to number if needed
        if isinstance(number, str):
            # SPECIALS is 0-indexed but memory numbers start at 1
            number = SPECIALS.index(number) + 1
        
        mem = chirp_common.Memory()
        mem.number = number
        mem.empty = True
        self.set_memory(mem)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to MIC/SP jack.\n"
            "3. Press and hold [FW] while turning radio on to put into CLONE mode.\n"
            "4. Press OK on chirp prompt.\n"
            "5. <b>After clicking OK</b>, press the [DWN] button on radio to send image. The radio will say CLN OUT while downloading.\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect cable to MIC/SP jack.\n"
            "3. Press and hold [FW] while turning radio on to put into CLONE mode.\n"
            "4. Press [UP] button on radio. The radio will say CLN IN.\n"
            "5. <b>After radio says CLN IN</b>, press OK on chirp prompt to upload.\n")
        return rp

    def sync_in(self):
        """Download from radio, warn on checksum errors instead of failing"""
        self._mmap = yaesu_clone._clone_in(self)
        try:
            self.check_checksums()
        except errors.RadioError as e:
            LOG.warning("Checksum mismatch (continuing anyway): %s" % e)
        self.process_mmap()

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    def get_settings(self):
        _settings = self._memobj
        
        basic = RadioSettingGroup("basic", "Basic")
        top = RadioSettings(basic)

        # Old mode bytes (for clone compatibility)
        rs = RadioSetting("match_mode", "Match Mode",
                RadioSettingValueString(0, 4, f"{int(_settings.match_mode):02X}", autopad=False))
        rs.set_doc("Must match radio's current active mode for clone to be accepted (hex format)")
        basic.append(rs)
        
        rs = RadioSetting("hardware_default_mode", "Hardware Default Mode",
                RadioSettingValueString(0, 4, f"{int(_settings.hardware_default_mode):02X}", autopad=False))
        rs.set_doc("Read-only: Hardware default mode byte (factory setting)")
        basic.append(rs)

        # Region/TX expansion mode (bits 7-6 always set = 0xC0, bits 2-0 = country)
        country = int(_settings.mode_byte) & 0x07
        country_map = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7}
        country_idx = country_map.get(country, 0)
        rs = RadioSetting("country", "Country",
                RadioSettingValueList(
                    ["FreeBand", "UK", "Unknown (2)", "USA", "Unknown (4)", "Germany", "Europe", "Unknown (7)"],
                    current_index=country_idx))
        basic.append(rs)

        rs = RadioSetting("wide_tx", "Wide TX",
                RadioSettingValueBoolean(bool(int(_settings.mode_byte) & 0x08)))
        basic.append(rs)

        rs = RadioSetting("cellular_rx", "Cellular RX",
                RadioSettingValueBoolean(bool(int(_settings.mode_byte) & 0x10)))
        basic.append(rs)

        rs = RadioSetting("wide_rx", "Wide RX",
                RadioSettingValueBoolean(bool(int(_settings.mode_byte) & 0x20)))
        basic.append(rs)

        rs = RadioSetting("band", "Current Band",
                RadioSettingValueList(
                    ["FM", "AIR", "V-HAM", "U-HAM", "ACT1", "ACT2", "UHF-TV"],
                    current_index=_settings.band))
        basic.append(rs)

        rs = RadioSetting("config2.apo", "Auto Power Off",
                RadioSettingValueList(
                    ["Off", "30min", "1hr", "3hr", "5hr", "8hr"],
                    current_index=_settings.config2.apo))
        basic.append(rs)

        rs = RadioSetting("config1.ars", "Auto Repeater Shift",
                RadioSettingValueBoolean(_settings.config1.ars))
        basic.append(rs)

        rs = RadioSetting("config1.atmd", "Auto Mode",
                RadioSettingValueBoolean(_settings.config1.atmd))
        basic.append(rs)

        rs = RadioSetting("config4.artsbp", "ARTS Beep",
                RadioSettingValueList(
                    ["Off", "In Range", "All"],
                    current_index=_settings.config4.artsbp))
        basic.append(rs)

        rs = RadioSetting("config1.beep", "Beep",
                RadioSettingValueBoolean(_settings.config1.beep))
        basic.append(rs)

        rs = RadioSetting("config1.bclo", "Busy Channel Lockout",
                RadioSettingValueBoolean(_settings.config1.bclo))
        basic.append(rs)

        rs = RadioSetting("config3.bell", "Bell",
                RadioSettingValueList(
                    ["Off", "1", "3", "5"],
                    current_index=_settings.config3.bell))
        basic.append(rs)

        rs = RadioSetting("config1.bsyled", "Busy LED",
                RadioSettingValueBoolean(_settings.config1.bsyled))
        basic.append(rs)

        rs = RadioSetting("config5.cwid", "CW ID",
                RadioSettingValueBoolean(_settings.config5.cwid))
        basic.append(rs)

        # CW ID text (8 characters max, 9th byte is stop byte)
        cwid_str = _decode_cwid(_settings.cwid_text)
        rs = RadioSetting("cwid_text", "CW ID Text",
                RadioSettingValueString(0, 8, cwid_str, autopad=False))
        basic.append(rs)

        rs = RadioSetting("config4.dialm", "Dial Mode",
                RadioSettingValueBoolean(_settings.config4.dialm))
        basic.append(rs)

        rs = RadioSetting("config5.grp", "Channel Group",
                RadioSettingValueList(
                    ["Group 1", "Group 2"],
                    current_index=_settings.config5.grp))
        basic.append(rs)

        rs = RadioSetting("priority_channel", "Priority Channel",
                RadioSettingValueInteger(1, 250, _settings.priority_channel))
        basic.append(rs)

        rs = RadioSetting("config2.lamp", "Lamp",
                RadioSettingValueList(
                    ["Key", "5 sec", "Toggle"],
                    current_index=_settings.config2.lamp))
        basic.append(rs)

        rs = RadioSetting("config3.lk", "Lock",
                RadioSettingValueBoolean(_settings.config3.lk))
        basic.append(rs)

        rs = RadioSetting("config3.lock", "Lock Mode",
                RadioSettingValueList(
                    ["Off", "Key", "Dial", "Key+Dial", "PTT", "Key+PTT", "Dial+PTT", "All"],
                    current_index=_settings.config3.lock))
        basic.append(rs)

        rs = RadioSetting("config4.montc", "Monitor",
                RadioSettingValueBoolean(_settings.config4.montc))
        basic.append(rs)

        rs = RadioSetting("config1.resume", "Scan Resume",
                RadioSettingValueList(
                    ["5 Second Hold", "Carrier Drop"],
                    current_index=_settings.config1.resume))
        basic.append(rs)

        rs = RadioSetting("config2.rxsave", "RX Battery Save",
                RadioSettingValueList(
                    ["Off", "0.2s", "0.3s", "0.5s", "1s", "2s"],
                    current_index=_settings.config2.rxsave))
        basic.append(rs)

        rs = RadioSetting("config1.scnl", "Scan Lamp",
                RadioSettingValueBoolean(_settings.config1.scnl))
        basic.append(rs)

        rs = RadioSetting("config4.smtmd", "Smart Search",
                RadioSettingValueBoolean(_settings.config4.smtmd))
        basic.append(rs)

        rs = RadioSetting("config4.tot", "Time-Out Timer",
                RadioSettingValueList(
                    ["Off", "1min", "2min", "5min", "10min"],
                    current_index=_settings.config4.tot))
        basic.append(rs)

        rs = RadioSetting("config6.dtmfm", "DTMF Memory",
                RadioSettingValueList(
                    ["DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4", "DTMF-5", 
                     "DTMF-6", "DTMF-7", "DTMF-8"],
                    current_index=_settings.config6.dtmfm))
        basic.append(rs)

        rs = RadioSetting("volume", "Volume",
                RadioSettingValueInteger(0, 31, _settings.volume))
        basic.append(rs)

        rs = RadioSetting("squelch", "Squelch",
                RadioSettingValueList(
                    ["Auto", "Open", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
                    current_index=_settings.squelch))
        basic.append(rs)

        # DTMF autodialer memories
        dtmf = RadioSettingGroup("dtmf", "DTMF Autodialer")
        top.append(dtmf)
        
        for i in range(8):
            dtmf_str = _decode_dtmf(_settings.autodialer[i].dtmf)
            rs = RadioSetting("autodialer_%d" % i, "DTMF-%d" % (i + 1),
                    RadioSettingValueString(0, 16, dtmf_str, False, DTMF_CHARSET + "-"))
            dtmf.append(rs)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                if element.get_name() == "hardware_default_mode":
                    # Read-only field, ignore changes
                    continue
                elif element.get_name() == "match_mode":
                    self._memobj.match_mode = int(str(element.value), 16)
                elif element.get_name() == "country":
                    country_values = [0, 1, 2, 3, 4, 5, 6, 7]
                    country = country_values[int(element.value)]
                    # Read current byte to preserve expansion bits
                    current = int(self._memobj.mode_byte)
                    # Clear country bits (0-2), keep expansion bits (3-5) and fixed bits (6-7)
                    mode_byte = (current & 0xF8) | country
                    self._memobj.mode_byte = mode_byte
                elif element.get_name() == "wide_tx":
                    current = int(self._memobj.mode_byte)
                    if element.value:
                        mode_byte = current | 0x08
                    else:
                        mode_byte = current & ~0x08
                    self._memobj.mode_byte = mode_byte
                elif element.get_name() == "cellular_rx":
                    current = int(self._memobj.mode_byte)
                    if element.value:
                        mode_byte = current | 0x10
                    else:
                        mode_byte = current & ~0x10
                    self._memobj.mode_byte = mode_byte
                elif element.get_name() == "wide_rx":
                    current = int(self._memobj.mode_byte)
                    if element.value:
                        mode_byte = current | 0x20
                    else:
                        mode_byte = current & ~0x20
                    self._memobj.mode_byte = mode_byte
                elif element.get_name() == "cwid_text":
                    self._memobj.cwid_text = _encode_cwid(str(element.value))
                elif element.get_name().startswith("autodialer_"):
                    idx = int(element.get_name().split("_")[1])
                    self._memobj.autodialer[idx].dtmf = _encode_dtmf(str(element.value))
                else:
                    # Handle nested attributes like "config2.apo"
                    parts = element.get_name().split(".")
                    obj = self._memobj
                    for part in parts[:-1]:
                        obj = getattr(obj, part)
                    setattr(obj, parts[-1], element.value)
            except Exception as e:
                LOG.debug(element.get_name())
                raise
