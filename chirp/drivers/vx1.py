# Copyright 2026 Don Barber <don@dgb3.net>, N3LP
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

# Base Device (VX-1R): Linear layout matching radio memory order
#   - Memory 1-170: All Configuration Group 2 (CG2) memories
#   - Memory 171-250: All Configuration Group 1 (CG1) memories
#   - Memory 251-260: All BC memories
#   - Global radio settings
#
# Sub-Device "CG1" (VX-1R CG1):
#   - Regular memories 1-52: Map to base device 179-230
#   - L/U scan limits 53-72: Map to base device 231-250 (L1/U1 through \
#     L10/U10)
#   - Home channels 73-80: Map to base device 171-178 (H-FM through \
#     H-ACT2)
#
# Sub-Device "CG2" (VX-1R CG2):
#   - Regular memories 1-142: Map to base device 9-150
#   - L/U scan limits 143-162: Map to base device 151-170 (L1/U1 through \
#     L10/U10)
#   - Home channels 163-170: Map to base device 1-8 (H-FM through \
#     H-ACT2)
#
# Sub-Device "BC" (VX-1R BC):
#   - Regular memories 1-10: Map to base device 251-260 (broadcast band \
#     presets)

# The driver uses sub-devices to organize memories into logical groups.
# Regular memories use standard numbering, while scan limits and home
# channels appear as special channels with descriptive names.

# If you find yourself with a radio that is in a state where it will not
# accept a clone-in, try doing a factory reset. Do this by holding [M/V]
# and [AR] as you power on the radio. When "INI? F" appears, press [FW]
# to reset the radio.
# This will reset all your memories; you may want to download your old
# memories first so you can copy them over to the new fresh image.

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise, errors
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, RadioSettings
import logging

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0000;
// Must match radio's current active mode
// for clone in to be accepted.
u8 match_mode;

// Mode byte with bit fields
u8 fixed_bits:2,  // Always 0xC0 (bits 7-6)
   wide_rx:1,     // bit 5
   cellular_rx:1, // bit 4
   wide_tx:1,     // bit 3
   country:3;     // bits 2-0

#seekto 0x0002;
u8 band;

#seekto 0x0007;
u8 ars:1, atmd:1, resume:1, scnl:1, beep:1, bclo:1, bsyled:1, unknown0:1;
u8 rxsave:3, apo:3, lamp:2;
u8 bell:3, unknown1a:1, lock:3, lk:1;
u8 montc:1, dialm:1, tot:3, smtmd:1, artsbp:2;
u8 unknown2a:1, cwid:1, grp:1, unknown2b:5;

#seekto 0x000e;
u8 dtmfm:4, unknown3:4;

#seekto 0x000f;
u8 volume;
u8 squelch;

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

#seekto 0x02f1;
u8 cwid_text[9];  // 8 chars max + stop byte (0x3d)

#seekto 0x0311;
struct {
  u8 freq[2];
  u8 name[6];  // BC VFO has 6-byte name like other memories
} bc_vfo;

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

#seekto 0x03a1;
u8 priority_channel;

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
lbit band_mask[2048];  // Interleaved CG2 and CG1 band masks
                      // (little-endian bits)

#seekto 0x11f1;
struct {
  u8 freq[2];  // BC band uses different frequency encoding
  u8 name[6];  // BC band has 6-byte name like other memories
} bc_memory[10];

#seekto 0x1251;
struct {
  u8 dtmf[16];
} autodialer[8];

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

# VX-1R: FM-N=FM (12.5kHz), FM-W=WFM (broadcast), AM
MODES = ["FM", "WFM", "AM"]
TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
# Power levels stated are when plugged in.
# When not plugged in, these become .5 and .05, respectively.
POWER_LEVELS = [chirp_common.PowerLevel("Lo", watts=0.2),
                chirp_common.PowerLevel("Hi", watts=1)]
# Base device uses linear memory layout with no special channels
SPECIALS = ()

# VX-1R character set
VX1_CHARSET = (
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ()+-=*/ΔΥΣ|-?%&_$¥\\﹨<>█∪⌋▆")

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
                # Unknown = underscore
                encoded.append(VX1_CHARSET.index('_'))
        else:
            encoded.append(0x3f)  # Empty/padding
    return encoded


class VX1Checksum(yaesu_clone.YaesuChecksum):
    """VX-1R Checksum at 0x12d1: (-sum) & 0xff"""

    def get_calculated(self, mmap):
        mmap = self._asbytes(mmap)
        cs = 0
        for i in range(self._start, self._stop + 1):
            cs += mmap[i][0]
        result = (-cs) & 0xff
        return result


class VX1Checksum2(yaesu_clone.YaesuChecksum):
    """VX-1R Checksum at 0x00a0: sum & 0xff"""

    def get_calculated(self, mmap):
        mmap = self._asbytes(mmap)
        cs = 0
        for i in range(self._start, self._stop + 1):
            cs += mmap[i][0]
        result = cs & 0xff
        return result


@directory.register
class VX1Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu VX-1R"""
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "VX-1"
    VARIANT = ""

    _model = b""
    _memsize = 4818
    _block_lengths = [4818]
    _block_size = 32

    # VX-1R uses 0x21 instead of standard 0x06 ACK
    _cmd_ack = 0x21

    def _checksums(self):
        return [VX1Checksum2(0x0001, 0x009f, 0x00a0),
                VX1Checksum(0x0001, 0x12d0, 0x12d1)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to MIC/SP jack.\n"
            "3. Press and hold [FW] while turning radio on to put into "
            "CLONE mode.\n"
            "4. Press OK on chirp prompt.\n"
            "5. <b>After clicking OK</b>, press the [DWN] button on radio "
            "to send image. The radio will say CLN OUT while downloading.\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect cable to MIC/SP jack.\n"
            "3. Press and hold [FW] while turning radio on to put into "
            "CLONE mode.\n"
            "4. Press [UP] button on radio. The radio will say CLN IN.\n"
            "5. <b>After radio says CLN IN</b>, press OK on chirp prompt "
            "to upload.\n")
        return rp

    @classmethod
    def match_model(cls, filedata, filename):
        return (len(filedata) == cls._memsize and
                filedata[0xE6:0xEB] == b"YAESU")

    def sync_out(self):

        # 9600 8N1 baud for 4818 bytes = 5.02 seconds
        self.pipe.timeout = 7
        try:
            return super().sync_out()
        except Exception as e:
            # Some firmware versions of the VX1 seem to put out extra
            # 0x00 bytes before sending the ack byte.
            # I suspect these were processing debug statements left in by
            # accident and removed in later firmwares.
            if "Radio did not ack block" in str(e):
                buf = self.pipe.read(1)
                if buf and buf[0] == self._cmd_ack:
                    status = chirp_common.Status()
                    status.msg = "Cloning to radio"
                    status.max = 100
                    status.cur = 100
                    self.status_fn(status)
                    return
            raise

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

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs_polarity = False
        rf.has_settings = True
        rf.has_sub_devices = self.VARIANT == ""
        rf.valid_modes = MODES
        rf.valid_tmodes = TMODES
        rf.valid_tuning_steps = STEPS
        rf.valid_duplexes = DUPLEX
        rf.valid_tones = list(chirp_common.OLD_TONES)
        rf.memory_bounds = (1, 260)  # Linear: CG1(80) + CG2(170) + BC(10)
        rf.valid_bands = [(500000, 999000000)]
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 6
        rf.valid_characters = VX1_CHARSET
        rf.valid_special_chans = SPECIALS
        rf.can_odd_split = True
        return rf

    def get_sub_devices(self):
        return [VX1RadioCG1(self._mmap), VX1RadioCG2(self._mmap),
                VX1RadioBC(self._mmap)]

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_settings(self):
        _settings = self._memobj

        basic = RadioSettingGroup("basic", "Basic")
        top = RadioSettings(basic)

        # Match mode byte
        # The radio needs this to match the current mode of the radio,
        # which can be seen as bytes 0 and 1 of a clone in.
        val = RadioSettingValueString(
            2, 2, f"{int(_settings.match_mode):02X}", autopad=False,
            charset="0123456789ABCDEFabcdef")
        val.set_mutable(False)
        rs = RadioSetting("match_mode", "Match Mode", val)
        rs.set_doc("The radio will only accept this image if this byte "
                   "matches its current settings. If the radio resets to "
                   "CLONE on first byte received during CLONE IN, then "
                   "instead download a new fresh image from the radio "
                   "and copy the needed memories into that.")
        basic.append(rs)

        # Region/TX expansion mode
        val = RadioSettingValueList(
            ["FreeBand", "UK", "Unknown (2)", "USA", "Unknown (4)",
             "Germany", "Europe", "Unknown (7)"],
            current_index=int(_settings.country))
        val.set_mutable(False)
        rs = RadioSetting("country", "Country", val)
        # If you know what country codes 2, 4, or 7 represent, either
        # contact me or submit a pull request.
        rs.set_doc("This is read only as modifying it can cause the radio "
                   "to reject future clone-ins.")
        basic.append(rs)

        val = RadioSettingValueBoolean(bool(_settings.wide_tx))
        val.set_mutable(False)
        rs = RadioSetting("wide_tx", "Wide TX", val)
        rs.set_doc("This is read only as modifying it can cause the radio "
                   "to reject future clone-ins.")
        basic.append(rs)

        val = RadioSettingValueBoolean(bool(_settings.cellular_rx))
        val.set_mutable(False)
        rs = RadioSetting("cellular_rx", "Cellular RX", val)
        rs.set_doc("This is read only as modifying it can cause the radio "
                   "to reject future clone-ins.")
        basic.append(rs)

        val = RadioSettingValueBoolean(bool(_settings.wide_rx))
        val.set_mutable(False)
        rs = RadioSetting("wide_rx", "Wide RX", val)
        rs.set_doc("This is read only as modifying it can cause the radio "
                   "to reject future clone-ins.")
        basic.append(rs)

        rs = RadioSetting(
            "band", "Current Band",
            RadioSettingValueList(
                ["BCBAND", "FM", "AIR", "VHF-HAM", "VHF-TV", "ACT1",
                 "UHF-HAM", "UHF-TV", "ACT2"],
                current_index=_settings.band))
        basic.append(rs)

        rs = RadioSetting(
            "apo", "Auto Power Off",
            RadioSettingValueList(
                ["Off", "30min", "1hr", "3hr", "5hr", "8hr"],
                current_index=_settings.apo))
        basic.append(rs)

        rs = RadioSetting(
            "ars", "Auto Repeater Shift",
            RadioSettingValueBoolean(_settings.ars))
        basic.append(rs)

        rs = RadioSetting(
            "atmd", "Auto Mode",
            RadioSettingValueBoolean(_settings.atmd))
        basic.append(rs)

        rs = RadioSetting(
            "artsbp", "ARTS Beep",
            RadioSettingValueList(
                ["Off", "In Range", "All"],
                current_index=_settings.artsbp))
        basic.append(rs)

        rs = RadioSetting(
            "beep", "Keypad Beep",
            RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting(
            "bclo", "Busy Channel Lockout",
            RadioSettingValueBoolean(_settings.bclo))
        basic.append(rs)

        rs = RadioSetting(
            "bell", "Bell",
            RadioSettingValueList(
                ["Off", "1 Ring", "3 Ring", "5 Ring", "8 Ring", "Repeat"],
                current_index=_settings.bell))
        basic.append(rs)

        rs = RadioSetting(
            "bsyled", "Busy LED",
            RadioSettingValueBoolean(_settings.bsyled))
        basic.append(rs)

        rs = RadioSetting(
            "cwid", "CW ID",
            RadioSettingValueBoolean(_settings.cwid))
        basic.append(rs)

        # CW ID text (8 characters max, 9th byte is stop byte)
        cwid_str = _decode_cwid(_settings.cwid_text)
        rs = RadioSetting(
            "cwid_text", "CW ID Text",
            RadioSettingValueString(0, 8, cwid_str, autopad=False))
        basic.append(rs)

        rs = RadioSetting(
            "dialm", "Dial Mode",
            RadioSettingValueList(
                ["Frequency", "Volume/Squelch"],
                current_index=_settings.dialm))
        basic.append(rs)

        rs = RadioSetting(
            "grp", "Configuration Group",
            RadioSettingValueList(
                ["Group 1", "Group 2"],
                current_index=_settings.grp))
        basic.append(rs)

        rs = RadioSetting(
            "priority_channel", "Priority Channel",
            RadioSettingValueInteger(1, 250, _settings.priority_channel))
        basic.append(rs)

        rs = RadioSetting(
            "lamp", "Lamp",
            RadioSettingValueList(
                ["Key", "5 sec", "Toggle"],
                current_index=_settings.lamp))
        basic.append(rs)

        rs = RadioSetting(
            "lk", "Lock",
            RadioSettingValueBoolean(_settings.lk))
        basic.append(rs)

        rs = RadioSetting(
            "lock", "Lock Mode",
            RadioSettingValueList(
                ["Off", "Key", "Dial", "Key+Dial", "PTT",
                 "Key+PTT", "Dial+PTT", "All"],
                current_index=_settings.lock))
        basic.append(rs)

        rs = RadioSetting(
            "montc", "Monitor/TCall",
            RadioSettingValueList(
                ["Monitor", "Tone Calling"],
                current_index=_settings.montc))
        basic.append(rs)

        rs = RadioSetting(
            "resume", "Scan Resume",
            RadioSettingValueList(
                ["5 Second Hold", "Carrier Drop"],
                current_index=_settings.resume))
        basic.append(rs)

        rs = RadioSetting(
            "rxsave", "RX Battery Save",
            RadioSettingValueList(
                ["Off", "0.2s", "0.3s", "0.5s", "1s", "2s"],
                current_index=_settings.rxsave))
        basic.append(rs)

        rs = RadioSetting(
            "scnl", "Scan Lamp",
            RadioSettingValueBoolean(_settings.scnl))
        basic.append(rs)

        rs = RadioSetting(
            "smtmd", "Smart Search",
            RadioSettingValueList(
                ["Single", "Continuous"],
                current_index=_settings.smtmd))
        basic.append(rs)

        rs = RadioSetting(
            "tot", "Time-Out Timer",
            RadioSettingValueList(
                ["Off", "1min", "2min", "5min", "10min"],
                current_index=_settings.tot))
        basic.append(rs)

        rs = RadioSetting(
            "dtmfm", "DTMF Memory",
            RadioSettingValueList(
                ["DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4", "DTMF-5",
                 "DTMF-6", "DTMF-7", "DTMF-8"],
                current_index=_settings.dtmfm))
        basic.append(rs)

        rs = RadioSetting(
            "volume", "Volume",
            RadioSettingValueInteger(0, 31, _settings.volume))
        basic.append(rs)

        rs = RadioSetting(
            "squelch", "Squelch",
            RadioSettingValueList(
                ["Auto", "Open", "1", "2", "3", "4", "5", "6", "7", "8",
                 "9", "10"],
                current_index=_settings.squelch))
        basic.append(rs)

        # DTMF autodialer memories
        dtmf = RadioSettingGroup("dtmf", "DTMF Autodialer")
        top.append(dtmf)

        for i in range(8):
            dtmf_str = _decode_dtmf(_settings.autodialer[i].dtmf)
            rs = RadioSetting(
                "autodialer_%d" % i, "DTMF-%d" % (i + 1),
                RadioSettingValueString(0, 16, dtmf_str, False,
                                        DTMF_CHARSET + "-"))
            dtmf.append(rs)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                if element.get_name() == "match_mode":
                    self._memobj.match_mode = \
                        int(element.value.get_value(), 16)
                elif element.get_name() == "cwid_text":
                    self._memobj.cwid_text = _encode_cwid(str(element.value))
                elif element.get_name().startswith("autodialer_"):
                    idx = int(element.get_name().split("_")[1])
                    self._memobj.autodialer[idx].dtmf = \
                        _encode_dtmf(str(element.value))
                else:
                    setattr(self._memobj, element.get_name(), element.value)
            except Exception:
                LOG.debug(element.get_name())
                raise

        # Mirror configuration data from 0x1-0x11 to 0x301-0x310
        for i in range(1, 0x11):  # 16 bytes (0x1 through 0x10)
            self._mmap[0x300 + i] = self._mmap[i]


class VX1RadioCG1(VX1Radio):
    """VX-1R Configuration Group 1"""
    VARIANT = "CG1"

    # Regular memories, then L/U pairs, then home channels
    SPECIAL_MEMORIES = {
        "L1": 53, "U1": 54,
        "L2": 55, "U2": 56,
        "L3": 57, "U3": 58,
        "L4": 59, "U4": 60,
        "L5": 61, "U5": 62,
        "L6": 63, "U6": 64,
        "L7": 65, "U7": 66,
        "L8": 67, "U8": 68,
        "L9": 69, "U9": 70,
        "L10": 71, "U10": 72,
        "H-FM": 73,
        "H-AIR": 74,
        "H-V-HAM": 75,
        "H-VHF-TV": 76,
        "H-ACT1": 77,
        "H-U-HAM": 78,
        "H-UHF-TV": 79,
        "H-ACT2": 80,
    }
    SPECIAL_MEMORIES_REV = dict(
        zip(SPECIAL_MEMORIES.values(), SPECIAL_MEMORIES.keys()))

    def get_features(self):
        rf = super().get_features()
        rf.has_sub_devices = False
        rf.has_settings = False
        # 52 regular memories to make room for 20 L/U
        rf.memory_bounds = (1, 52)
        rf.valid_special_chans = list(self.SPECIAL_MEMORIES.keys())
        rf.valid_bands = [(1700000, 999000000)]  # CG1: 1.7 MHz - 999 MHz
        return rf

    def get_memory(self, number):
        is_string = isinstance(number, str)
        if is_string:
            # Special channel by name - convert to number
            number = self.SPECIAL_MEMORIES[number]

        if number <= 72:
            # Regular and L/U memories: 1-72 map to cg1_idx 8-79
            cg1_idx = number + 7
        else:
            # Home channels: 73-80 map to cg1_idx 0-7
            cg1_idx = number - 73

        # Handle CG1 memory structure directly
        _mem = self._memobj.cg1_memory[cg1_idx]

        mem = chirp_common.Memory()
        mem.number = number
        if is_string or number > 52:
            mem.extd_number = self.SPECIAL_MEMORIES_REV[number]

        # Check if memory is empty
        if isinstance(_mem.get_raw()[0], int):
            first_byte = _mem.get_raw()[0]
        else:
            first_byte = ord(_mem.get_raw()[0])

        if first_byte == 0xff:
            mem.empty = True
            self._get_extra(_mem, mem)
            return mem

        try:
            mem.freq = chirp_common.fix_rounded_step(int(_mem.rx_freq) * 1000)
        except errors.InvalidDataError:
            mem.freq = int(_mem.rx_freq) * 1000
        mem.name = _decode_name(_mem.name)
        mem.mode = MODES[_mem.mode] if _mem.mode < len(MODES) else MODES[0]
        mem.skip = "S" if _mem.skip else ""
        mem.power = POWER_LEVELS[_mem.power]
        mem.tuning_step = STEPS[_mem.step]

        # CG1 has offset/tone fields
        mem.duplex = DUPLEX[_mem.shift]
        mem.offset = int(_mem.offset) * 1000
        mem.tmode = TMODES[_mem.selcal] if _mem.selcal < len(
            TMODES) else ""
        if mem.tmode and mem.tmode != "":
            if _mem.ctcss < len(chirp_common.OLD_TONES):
                mem.rtone = mem.ctone = chirp_common.OLD_TONES[_mem.ctcss]
            if _mem.dcs < len(chirp_common.DTCS_CODES):
                mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]

        self._get_extra(_mem, mem)

        # Default clk_shift to disabled for CG1 memories
        if hasattr(mem, 'extra') and mem.extra:
            for setting in mem.extra:
                if (setting.get_name() == 'clk_shift' and
                        setting.value is not False):
                    setting.value = False  # Force to disabled

        return mem

    def set_memory(self, mem):
        if isinstance(mem.number, str):
            # Convert string to number
            mem.number = self.SPECIAL_MEMORIES[mem.number]

        # Map CG1 subdevice number to cg1_idx
        if mem.number <= 72:
            # Regular and L/U memories: 1-72 map to cg1_idx 8-79
            cg1_idx = mem.number + 7
        else:
            # Home channels: 73-80 map to cg1_idx 0-7
            cg1_idx = mem.number - 73

        # Handle CG1 memory structure directly
        _mem = self._memobj.cg1_memory[cg1_idx]

        if mem.empty:
            # Set only first byte to 0xff for empty memory
            offset = 0x0bd1 + cg1_idx * 16
            self._mmap[offset] = 0xff
            return

        _mem.rx_freq = int(mem.freq / 1000)
        _mem.name = _encode_name(mem.name)
        _mem.mode = MODES.index(mem.mode)
        _mem.skip = 1 if mem.skip == "S" else 0
        _mem.power = POWER_LEVELS.index(mem.power) if mem.power else 1
        _mem.step = STEPS.index(mem.tuning_step)

        # Set defaults
        _mem.clk_shift = 0
        _mem.name_flag = 1 if mem.name else 0

        # Set extra fields (may override defaults)
        self._set_extra(_mem, mem)

        # CG1 has offset/tone fields
        _mem.shift = DUPLEX.index(mem.duplex)
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

        # Update band mask for CG1 memory (skip home channels)
        if cg1_idx >= 8:  # Only update band mask for non-home channels
            band_idx = self._get_band_index(mem.freq)
            if band_idx is not None:
                # CG1 band mask: offset by 176 bits (22 bytes) from CG2,
                # +8 to skip band byte
                base_offset = 176 + 8
                adjusted_idx = cg1_idx - 8
                for b in range(8):
                    bit_idx = base_offset + b * 256 + adjusted_idx
                    if b == band_idx:
                        self._memobj.band_mask[bit_idx] = 1
                    else:
                        self._memobj.band_mask[bit_idx] = 0

    def erase_memory(self, number):
        # Map CG1 subdevice number to cg1_idx
        if number <= 72:
            cg1_idx = number + 7
        else:
            cg1_idx = number - 73

        offset = 0x0bd1 + cg1_idx * 16
        self._mmap[offset] = 0xff

        # Clear band mask for CG1 memory (skip home channels)
        if cg1_idx >= 8:  # Only clear band mask for non-home channels
            base_offset = 176 + 8
            adjusted_idx = cg1_idx - 8
            for b in range(8):
                bit_idx = base_offset + b * 256 + adjusted_idx
                self._memobj.band_mask[bit_idx] = 0


class VX1RadioCG2(VX1Radio):
    """VX-1R Configuration Group 2"""
    VARIANT = "CG2"

    # Regular memories, then L/U pairs, then home channels
    SPECIAL_MEMORIES = {
        "L1": 143, "U1": 144,
        "L2": 145, "U2": 146,
        "L3": 147, "U3": 148,
        "L4": 149, "U4": 150,
        "L5": 151, "U5": 152,
        "L6": 153, "U6": 154,
        "L7": 155, "U7": 156,
        "L8": 157, "U8": 158,
        "L9": 159, "U9": 160,
        "L10": 161, "U10": 162,
        "H-FM": 163,
        "H-AIR": 164,
        "H-V-HAM": 165,
        "H-VHF-TV": 166,
        "H-ACT1": 167,
        "H-U-HAM": 168,
        "H-UHF-TV": 169,
        "H-ACT2": 170,
    }
    SPECIAL_MEMORIES_REV = dict(
        zip(SPECIAL_MEMORIES.values(), SPECIAL_MEMORIES.keys()))

    def get_features(self):
        rf = super().get_features()
        rf.has_sub_devices = False
        rf.has_settings = False
        # 142 regular memories to make room for 20 L/U
        rf.memory_bounds = (1, 142)
        rf.valid_special_chans = list(self.SPECIAL_MEMORIES.keys())
        # CG2 memories support standard repeater shifts but not custom offsets
        rf.has_offset = False  # No custom offset amounts
        rf.valid_duplexes = ["", "-", "+"]  # Standard repeater shifts only
        rf.can_odd_split = False  # No split mode (no offset field)
        rf.valid_bands = [(1700000, 999000000)]  # CG2: 1.7 MHz - 999 MHz
        # CG2 supports tone modes but not custom tone frequencies
        rf.valid_tmodes = TMODES
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.valid_tones = []  # Hide tone frequency columns
        rf.valid_dtcs_codes = []  # Hide DTCS code columns
        return rf

    def get_memory(self, number):
        is_string = isinstance(number, str)
        if is_string:
            # Special channel by name - convert to number
            number = self.SPECIAL_MEMORIES[number]

        if number <= 162:
            # Regular and L/U memories: 1-162 map to cg2_idx 8-169
            cg2_idx = number + 7
        else:
            # Home channels: 163-170 map to cg2_idx 0-7
            cg2_idx = number - 163

        # Handle CG2 memory structure directly
        _mem = self._memobj.cg2_memory[cg2_idx]

        mem = chirp_common.Memory()
        mem.number = number
        if is_string or number > 142:
            mem.extd_number = self.SPECIAL_MEMORIES_REV[number]

        # Check if memory is empty
        if isinstance(_mem.get_raw()[0], int):
            first_byte = _mem.get_raw()[0]
        else:
            first_byte = ord(_mem.get_raw()[0])

        if first_byte == 0xff:
            mem.empty = True
            self._get_extra(_mem, mem)
            return mem

        try:
            mem.freq = chirp_common.fix_rounded_step(int(_mem.rx_freq) * 1000)
        except errors.InvalidDataError:
            mem.freq = int(_mem.rx_freq) * 1000
        mem.name = _decode_name(_mem.name)
        mem.mode = MODES[_mem.mode] if _mem.mode < len(MODES) else MODES[0]
        mem.skip = "S" if _mem.skip else ""
        mem.power = POWER_LEVELS[_mem.power]
        mem.tuning_step = STEPS[_mem.step]

        # CG2 has duplex field but no offset field (uses standard repeater
        # shifts)
        mem.duplex = DUPLEX[_mem.shift] if _mem.shift < len(DUPLEX) else ""
        # Calculate standard repeater offset based on frequency and duplex
        if mem.duplex in ["-", "+"]:
            if mem.freq >= 420000000:  # UHF band
                mem.offset = 5000000  # 5 MHz
            elif mem.freq >= 144000000:  # VHF band
                mem.offset = 600000   # 600 kHz
            else:
                mem.offset = 0
        else:
            mem.offset = 0
        mem.tmode = TMODES[_mem.selcal] if _mem.selcal < len(TMODES) else ""

        self._get_extra(_mem, mem)

        return mem

    def set_memory(self, mem):
        if isinstance(mem.number, str):
            # Convert string to number
            mem.number = self.SPECIAL_MEMORIES[mem.number]

        # Map CG2 subdevice number to cg2_idx
        if mem.number <= 162:
            # Regular and L/U memories: 1-162 map to cg2_idx 8-169
            cg2_idx = mem.number + 7
        else:
            # Home channels: 163-170 map to cg2_idx 0-7
            cg2_idx = mem.number - 163

        # Handle CG2 memory structure directly
        _mem = self._memobj.cg2_memory[cg2_idx]

        if mem.empty:
            # Set only first byte to 0xff for empty memory
            offset = 0x03d1 + cg2_idx * 12
            self._mmap[offset] = 0xff
            return

        _mem.rx_freq = int(mem.freq / 1000)
        _mem.name = _encode_name(mem.name)
        _mem.mode = MODES.index(mem.mode)
        _mem.skip = 1 if mem.skip == "S" else 0
        _mem.power = POWER_LEVELS.index(mem.power) if mem.power else 1
        _mem.step = STEPS.index(mem.tuning_step)

        # Set defaults
        _mem.clk_shift = 0
        _mem.name_flag = 1 if mem.name else 0

        # Set extra fields (may override defaults)
        self._set_extra(_mem, mem)

        # CG2 supports standard repeater shifts
        _mem.shift = DUPLEX.index(mem.duplex) if mem.duplex in DUPLEX else 0
        _mem.selcal = TMODES.index(mem.tmode) if mem.tmode in TMODES else 0

        # Update band mask for CG2 memory (skip home channels)
        if cg2_idx >= 8:  # Only update band mask for non-home channels
            band_idx = self._get_band_index(mem.freq)
            if band_idx is not None:
                # CG2 band mask: base offset +8 to skip band byte
                base_offset = 8
                adjusted_idx = cg2_idx - 8
                for b in range(8):
                    bit_idx = base_offset + b * 256 + adjusted_idx
                    if b == band_idx:
                        self._memobj.band_mask[bit_idx] = 1
                    else:
                        self._memobj.band_mask[bit_idx] = 0

    def erase_memory(self, number):
        # Map CG2 subdevice number to cg2_idx
        if number <= 162:
            cg2_idx = number + 7
        else:
            cg2_idx = number - 163

        offset = 0x03d1 + cg2_idx * 12
        self._mmap[offset] = 0xff

        # Clear band mask for CG2 memory (skip home channels)
        if cg2_idx >= 8:  # Only clear band mask for non-home channels
            base_offset = 8
            adjusted_idx = cg2_idx - 8
            for b in range(8):
                bit_idx = base_offset + b * 256 + adjusted_idx
                self._memobj.band_mask[bit_idx] = 0

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        # CG2 supports tone modes but not custom tone frequencies
        if mem.tmode in ("Tone", "TSQL"):
            if mem.rtone != 88.5:
                mem.rtone = 88.5
                msgs.append(chirp_common.ValidationWarning(
                    "CG2 does not support custom tone frequencies, "
                    "using default"))
            if mem.ctone != 88.5:
                mem.ctone = 88.5
                msgs.append(chirp_common.ValidationWarning(
                    "CG2 does not support custom tone frequencies, "
                    "using default"))

        return msgs


class VX1RadioBC(VX1Radio):
    """VX-1R Broadcast Band"""
    VARIANT = "BC"

    def get_features(self):
        rf = super().get_features()
        rf.has_sub_devices = False
        rf.has_settings = False
        rf.memory_bounds = (1, 10)  # 10 memories (no separate home channel)
        rf.valid_special_chans = []
        # BC band is AM-only with no advanced features
        rf.valid_modes = ["AM"]
        rf.has_offset = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.valid_duplexes = [""]
        rf.valid_tmodes = [""]
        rf.valid_tones = []
        rf.valid_dtcs_codes = []
        rf.valid_skips = [""]
        rf.can_odd_split = False  # BC doesn't support any duplex modes
        rf.valid_bands = [(500000, 1700000)]  # BC band: 0.5-1.7 MHz
        return rf

    def get_memory(self, number):
        # BC sub-device: memory 1-10 maps to base device 251-260
        base_number = number + 250

        # Handle BC memory structure directly
        bc_idx = base_number - 251
        _mem = self._memobj.bc_memory[bc_idx]

        mem = chirp_common.Memory()
        mem.number = number

        # Check if memory is empty
        first_byte = _mem.freq[0]
        if first_byte == 0xff:
            mem.empty = True
            return mem

        # BC band memories use special frequency encoding
        freq_mhz = 0.5 + (_mem.freq[0] * (1.2 / 254.0))
        mem.freq = int(freq_mhz * 1000000 + 0.5)
        mem.name = _decode_name(_mem.name)
        mem.mode = "AM"
        mem.skip = ""
        mem.power = POWER_LEVELS[0]
        # Always display 5.0 kHz step (STEPS[0]) for UI consistency
        mem.tuning_step = 5.0
        mem.duplex = ""
        mem.offset = 0

        return mem

    def set_memory(self, mem):
        # BC sub-device: memory 1-10 maps to base device 251-260
        base_number = mem.number + 250
        bc_idx = base_number - 251
        _mem = self._memobj.bc_memory[bc_idx]

        if mem.empty:
            # Set only first byte to 0xff for empty memory
            _mem.freq[0] = 0xff
            return

        # BC band memories use special frequency encoding
        freq_mhz = mem.freq / 1000000.0
        byte_val = int((freq_mhz - 0.5) / (1.2 / 254.0) + 0.5)
        byte_val = min(max(byte_val, 0), 0xfe)
        _mem.freq[0] = byte_val
        _mem.freq[1] = 0x40  # Set tuning step to 0x40

        _mem.name = _encode_name(mem.name)
        # BC band is always AM mode, no other fields to set

    def erase_memory(self, number):
        # BC sub-device: memory 1-10 maps to base device 251-260
        base_number = number + 250
        bc_idx = base_number - 251
        offset = 0x11f1 + bc_idx * 8
        self._mmap[offset] = 0xff

    def validate_memory(self, mem):
        msgs = []

        # BC band only supports AM mode
        if mem.mode != "AM":
            mem.mode = "AM"
            msgs.append(chirp_common.ValidationWarning(
                "BC band only supports AM mode"))

        # BC band frequency range: 0.5-1.7 MHz with limited precision
        if mem.freq < 500000 or mem.freq > 1700000:
            mem.freq = max(500000, min(1700000, mem.freq))
            msgs.append(chirp_common.ValidationWarning(
                "BC band frequency adjusted to valid range (0.5-1.7 MHz)"))

        # Round frequency to nearest encodable value for BC band
        freq_mhz = mem.freq / 1000000.0
        byte_val = int((freq_mhz - 0.5) / (1.2 / 254.0) + 0.5)
        byte_val = min(max(byte_val, 0), 0xfe)
        # Calculate the actual encodable frequency
        actual_freq_mhz = 0.5 + (byte_val * (1.2 / 254.0))
        actual_freq = int(actual_freq_mhz * 1000000 + 0.5)  # Round to Hz
        if mem.freq != actual_freq:
            mem.freq = actual_freq
            # Note: No warning - frequency rounding is expected in BC band

        # BC band doesn't support duplex
        if mem.duplex:
            mem.duplex = ""
            msgs.append(chirp_common.ValidationWarning(
                "Duplex not supported for BC band"))

        # BC band doesn't support tones
        if mem.tmode and mem.tmode != "":
            mem.tmode = ""
            msgs.append(chirp_common.ValidationWarning(
                "Tone modes not supported for BC band"))

        return msgs
