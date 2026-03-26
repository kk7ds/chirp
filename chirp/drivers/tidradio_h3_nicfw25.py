# Copyright 2025 TIDRADIO TD-H3 nicFW V2.5 CHIRP Adapter
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# EEPROM layout and protocol: https://github.com/nicsure/nicfw2docs
# V2.5X codeplugs use BIG-Endian for all multi-byte values.

import logging
import re
import struct

from chirp import chirp_common, directory, bitwise, memmap, errors
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettingValueBoolean,
    RadioSettingValueList,
    RadioSettingValueInteger,
    RadioSettingValueString,
    RadioSettingValueFloat,
    RadioSettings,
)

LOG = logging.getLogger(__name__)

# V2.5 EEPROM layout (big-endian). See nicfw2docs eeprom.md,
# channelInfo.md, settingsBlock.md.
MEM_FORMAT = """
// V2.5X: multi-byte values are BIG-endian (u16, u32)
// 0x0000 vfoA, 0x0020 vfoB, 0x0040 memoryChannels[198]
#seekto 0x0000;
struct {
    u32 rxFreq;      // 10 Hz units
    u32 txFreq;
    u16 rxSubTone;   // CTCSS 0.1 Hz, or DCS bit15 [+ bit14 invert]
    u16 txSubTone;
    u8 txPower;
    u16 groups;      // g0:4, g1:4, g2:4, g3:4
    // CHIRP bitwise: first-declared bitfield is MSB (bit 7).
    // nicFW wire: bit0=bandwidth, bit7=busyLock, bits1-2=modulation,
    // bit3=position, bits4-5=pttID, bit6=reversed. Declare MSB to LSB.
    u8 busyLock:1,
       reversed:1,
       pttID:2,
       position:1,
       modulation:2,
       bandwidth:1;
    u8 skip;
    char reserved[3];
    char name[12];
} vfoA;

#seekto 0x0020;
struct {
    u32 rxFreq;
    u32 txFreq;
    u16 rxSubTone;
    u16 txSubTone;
    u8 txPower;
    u16 groups;
    u8 busyLock:1,
       reversed:1,
       pttID:2,
       position:1,
       modulation:2,
       bandwidth:1;
    u8 skip;
    char reserved[3];
    char name[12];
} vfoB;

#seekto 0x0040;
struct {
    u32 rxFreq;
    u32 txFreq;
    u16 rxSubTone;
    u16 txSubTone;
    u8 txPower;
    u16 groups;
    u8 busyLock:1,
       reversed:1,
       pttID:2,
       position:1,
       modulation:2,
       bandwidth:1;
    u8 skip;
    char reserved[3];
    char name[12];
} memory[198];

// 0x1900 settings block (V2.5 magic 0xD82F)
#seekto 0x1900;
struct {
    u16 magic;           // 0xD82F
    u8 squelch;
    u8 dualWatch;
    u8 autoFloor;
    u8 activeVfo;
    u16 step;
    u16 rxSplit;
    u16 txSplit;
    u8 pttMode;
    u8 txModMeter;
    u8 micGain;
    u8 txDeviation;
    // V2.5: unused here; live XTAL at 0x1DFB (eeprom.md)
    i8 xtal671_DEFUNCT;
    u8 battStyle;
    u16 scanRange;
    u16 scanPersist;
    u8 scanResume;
    u8 ultraScan;
    u8 toneMonitor;
    u8 lcdBrightness;
    u8 lcdTimeout;
    u8 breathe;
    u8 dtmfDev;
    u8 gamma;
    u16 repeaterTone;
    u8 vfoState_group0;
    u8 vfoState_lastGroup0;
    u8 vfoState_groupModeChannels0[16];
    u8 vfoState_mode0;
    u8 vfoState_group1;
    u8 vfoState_lastGroup1;
    u8 vfoState_groupModeChannels1[16];
    u8 vfoState_mode1;
    u8 keyLock;
    u8 bluetooth;
    u8 powerSave;
    u8 keyTones;
    u8 ste;
    u8 rfGain;
    u8 sBarStyle;
    u8 sqNoiseLev;
    u32 lastFmtFreq;
    u8 vox;
    u16 voxTail;
    u8 txTimeout;
    u8 dimmer;
    u8 dtmfSpeed;
    u8 noiseGate;
    u8 scanUpdate;
    u8 asl;
    u8 disableFmt;
    u16 pin;
    u8 pinAction;
    u8 lcdInverted;
    u8 afFilters;
    u8 ifFreq;
    u8 sBarAlwaysOn;
    u8 lockedVfo;
    u8 vfoLockActive;
    u8 dualWatchDelay;
    u8 subToneDeviation;
    // 0x1967-0x1973: showXmitCurrent, AGC 0-3, RFi Comp, etc.
    u8 filler1967[13];
    u8 amAgcFix;         // 0x1974  AM AGC Fix (0=Off, 1=On)  ✓ confirmed
    u8 filler1975[11];   // 0x1975-0x197F
} settings;

// 0x1A00 bandplan magic 0xA46D, then bandPlans[20]
#seekto 0x1A00;
u16 bandplanMagic;
#seekto 0x1A02;
struct {
    u32 startFreq;
    u32 endFreq;
    u8 maxPower;
    // CHIRP bitwise: first declared = MSB.
    // Radio: bit0=txAllowed, bit1=wrap, bits2-4=modulation, bits5-7=bandwidth.
    // Reverse declaration order maps last field to bit 0.
    u8 bandwidth:3,
       modulation:3,
       wrap:1,
       txAllowed:1;
} bandPlans[20];

// 0x1B00 scanPresets[20]
#seekto 0x1B00;
struct {
    u32 startFreq;
    u16 range;
    u16 step;
    u8 resume;
    u8 persist;
    // CHIRP bitwise: first declared = MSB.
    // Radio: bits[1:0]=modulation (FM/AM/USB/Auto), bits[4:2]=ultrascan.
    // ultrascan is 6 bits covering bits[7:2] (incl. unused upper bits).
    // Reverse declaration maps modulation to bits[1:0].
    u8 ultrascan:6,
       modulation:2;
    char label[9];
} scanPresets[20];

// 0x1C90 group labels: 15 groups A-O; idx 0-14 used, 15 unused.
// Six chars per label plus a null terminator.
#seekto 0x1C90;
struct {
    char label[6];
} groupLabels[16];

// 0x1DFB calibration (per-radio; clone from another radio copies these)
#seekto 0x1DFB;
struct {
    // Crystal calibration (V2.5; Advanced Menu)
    i8 xtal671;
    u8 maxPowerWattsUHF;      // 0.1W units
    u8 maxPowerSettingUHF;
    u8 maxPowerWattsVHF;      // 0.1W units
    u8 maxPowerSettingVHF;
} calibration;
"""

# Protocol (programmer_radio_protocol.md)
CMD_DISABLE_RADIO = 0x45
CMD_ENABLE_RADIO = 0x46
CMD_READ_EEPROM = 0x30
CMD_WRITE_EEPROM = 0x31
CMD_REBOOT_RADIO = 0x49

MAGIC_SETTINGS_V25 = 0xD82F
MAGIC_BANDPLAN_V25 = 0xA46D

BLOCK_SIZE = 32
EEPROM_SIZE = 8192  # 8 KB
NUM_BLOCKS = EEPROM_SIZE // BLOCK_SIZE  # 256

# Channel/settings constants
MODULATION_LIST = ["Auto", "FM", "AM", "USB"]
# chirp_common.MODES-style labels for FM/AM + narrow (EEPROM still stores
# modulation + bandwidth bit).
NFM = "NFM"
NAM = "NAM"
# Memory editor / validate_memory: includes NFM/NAM alongside EEPROM
# modulation names.
VALID_MODES = ["Auto", "FM", NFM, "AM", NAM, "USB"]
BANDWIDTH_LIST = ["Wide", "Narrow"]


def _extra_bandwidth_value_str(mem):
    """Return Bandwidth extra value as a string, or None if unset/missing."""
    extra = getattr(mem, "extra", None)
    if not extra:
        return None
    try:
        for e in extra:
            try:
                if e.get_name() != "bandwidth":
                    continue
                val = e.value
                if hasattr(val, "get_value"):
                    return str(val.get_value())
                return str(val)
            except Exception:
                continue
    except Exception:
        pass
    return None


def _extra_bandwidth_is_narrow(mem):
    """True if Memory.extra lists bandwidth Narrow (legacy saves / UI)."""
    extra = getattr(mem, "extra", None)
    if not extra:
        return False
    try:
        for e in extra:
            try:
                if e.get_name() != "bandwidth":
                    continue
                val = e.value
                if hasattr(val, "get_value"):
                    cur = val.get_value()
                    if "Narrow" in str(cur):
                        return True
                elif "Narrow" in str(val):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _fw_channel_mode_to_chirp(mod_idx, is_narrow):
    """Map EEPROM modulation index + narrow bit to chirp_common.Memory.mode."""
    mod_idx = int(mod_idx)
    if mod_idx >= len(MODULATION_LIST):
        mod_idx = 1
    mod_str = MODULATION_LIST[mod_idx]
    if mod_str == "FM" and is_narrow:
        return NFM
    if mod_str == "AM" and is_narrow:
        return NAM
    return mod_str


def _chirp_mode_to_fw_channel(mem):
    """Return (modulation_index, narrow_bool) for channel EEPROM flags."""
    if mem.mode == NFM:
        return MODULATION_LIST.index("FM"), True
    if mem.mode == NAM:
        return MODULATION_LIST.index("AM"), True
    if mem.mode in MODULATION_LIST:
        return MODULATION_LIST.index(mem.mode), _extra_bandwidth_is_narrow(mem)
    return 0, _extra_bandwidth_is_narrow(mem)


def _channel_memory_wants_narrow(mem):
    """True if mem should encode narrow bandwidth (set_memory / mmap)."""
    return _chirp_mode_to_fw_channel(mem)[1]


def _apply_channel_bandwidth_bit0_to_mmap(mmap, index, want_narrow):
    """Set byte 15 bit0 for narrow (0=Wide, 1=Narrow); keep other bits."""
    if mmap is None or index < 0:
        return
    off = 0x40 + index * 32 + 15
    if off + 1 > len(mmap):
        return
    cur = mmap[off]
    cur_b = cur[0] if isinstance(cur, (bytes, bytearray)) else int(cur)
    mmap[off] = (cur_b & 0xFE) | (1 if want_narrow else 0)


GROUPS_LIST = [
    "None",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O"]
# txPower: 0 = N/T; 1..255 = level; max from cal maxPowerSetting* /
# maxPowerWatts* (0.1 W steps) at 0x1DFB — same idea as group label
# strings in UI.
TXPower_NT = 0  # 0 = No Transmit
DEFAULT_MAX_POWER_WATTS_TENTHS = 50  # 5.0 W when EEPROM cal is blank
DEFAULT_MAX_POWER_SETTING = 130
# Distinct negative dBm so import_logic int(mem.power) works for N/T.
NT_TX_DBM = -127
# Tiny per-raw bias so saturated max-power steps stay distinguishable
# (__eq__ / import).
_RAW_DBM_EPSILON = 1.0e-6


def _calibration_power_params(memobj):
    """Return VHF/UHF (max watts tenths, max raw setting) from calibration."""
    d = (DEFAULT_MAX_POWER_WATTS_TENTHS, DEFAULT_MAX_POWER_SETTING,
         DEFAULT_MAX_POWER_WATTS_TENTHS, DEFAULT_MAX_POWER_SETTING)
    if memobj is None:
        return d
    try:
        cal = memobj.calibration
        mv = int(cal.maxPowerWattsVHF) & 0xFF
        sv = int(cal.maxPowerSettingVHF) & 0xFF
        mu = int(cal.maxPowerWattsUHF) & 0xFF
        su = int(cal.maxPowerSettingUHF) & 0xFF
    except Exception:
        return d
    if mv <= 0 and mu <= 0:
        return d
    if sv <= 0:
        sv = DEFAULT_MAX_POWER_SETTING
    if su <= 0:
        su = DEFAULT_MAX_POWER_SETTING
    return (mv, sv, mu, su)


def _watts_for_raw_scaled(raw, max_w_tenths, max_set):
    """Approximate TX watts for firmware power 1..255 from one band's cal."""
    if raw <= 0 or max_w_tenths <= 0:
        return 0.0
    max_w = max_w_tenths / 10.0
    if max_set <= 0:
        max_set = DEFAULT_MAX_POWER_SETTING
    return min(max_w, (raw / float(max_set)) * max_w)


def power_levels_for_memobj(memobj):
    """PowerLevel list for CHIRP import_logic (see PowerLevel.__int__)."""
    mv, sv, mu, su = _calibration_power_params(memobj)
    levels = [chirp_common.PowerLevel("N/T", dBm=NT_TX_DBM)]
    for raw in range(1, 256):
        wv = _watts_for_raw_scaled(raw, mv, sv)
        wu = _watts_for_raw_scaled(raw, mu, su)
        if mv > 0 and mu > 0:
            w_nom = (wv + wu) / 2.0
        elif mv > 0:
            w_nom = wv
        else:
            w_nom = wu
        label = "%d (%.1f W)" % (raw, w_nom)
        w_use = max(w_nom, 1e-9)
        pl_dbm = chirp_common.watts_to_dBm(w_use) + raw * _RAW_DBM_EPSILON
        levels.append(chirp_common.PowerLevel(label, dBm=pl_dbm))
    return levels


def _tx_power_u8_from_memory(memobj, mem_power):
    """Map Memory.power (PowerLevel, str, None) to firmware txPower byte."""
    levels = power_levels_for_memobj(memobj)
    if mem_power is None:
        return 1 if len(levels) > 1 else TXPower_NT
    if isinstance(mem_power, chirp_common.PowerLevel):
        for i, pl in enumerate(levels):
            if pl == mem_power:
                return i
        return 1
    s = str(mem_power).strip()
    if not s or s == "N/T" or s.startswith("N/T"):
        return TXPower_NT
    if s.isdigit():
        v = int(s)
        return v if 0 <= v <= 255 else 1
    m = re.match(r"^(\d+)\s", s)
    if m:
        v = int(m.group(1))
        return v if 0 <= v <= 255 else 1
    return 1


# Settings block option lists (per settingsBlock.md and nicFW behaviour)
SQUELCH_LIST = [str(x) for x in range(10)]  # 0-9
ACTIVEVFO_LIST = ["VFO-A", "VFO-B"]
# nicFW step: 2.5, 5, 6.25, 12.5, 25, 50 kHz. Stored in radio as Hz. CHIRP
# dropdown shows Hz (2500=2.5 kHz).
STEP_LIST = ["2.5 kHz", "5.0 kHz", "6.25 kHz", "12.5 kHz", "25 kHz", "50 kHz"]
# Hz, for settings block u16 step
STEP_VALUES = [2500, 5000, 6250, 12500, 25000, 50000]
# Per-memory tuning step: free entry in CHIRP (empty list); default when
# not on a supported step grid
DEFAULT_TUNING_STEP_HZ = 12500  # 12.5 kHz
# Hz; used only for inferring step from freq
VALID_TUNING_STEPS_HZ = [2500, 5000, 6250, 12500, 25000, 50000]
BATTSTYLE_LIST = ["Off", "Icon", "Percentage", "Voltage"]
SCANRESUME_LIST = ["Time", "Hold", "Seek"]  # typical
TONEMONITOR_LIST = ["Off", "On", "Clone"]
LCDTIMEOUT_LIST = ["Off"] + [str(x) for x in range(1, 201)]
AF_FILTERS_LIST = [
    "All",
    "Band Pass Only",
    "De-Emphasis + High Pass",
    "High Pass Only",
    "De-Emphasis + Low Pass",
    "Low Pass Only",
    "De-Emphasis Only",
    "None"]
RFGAIN_LIST = ["AGC"] + [str(x) for x in range(1, 43)]
VOX_LIST = ["Off"] + [str(x) for x in range(1, 16)]
PIN_ACTION_LIST = ["Off", "Lock", "Unlock"]  # typical; extend if doc specifies
# vfoState.mode 0 = VFO, 1 = Channel/Group
OP_MODE_LIST = ["VFO", "Channel/Group"]
# Band plan (nicFW Programmer; EEPROM verified Mar 2026).
# Modulation: 3 bits. Raw value = list index.
# EEPROM: raw 0=Ignore, 1=FM, 2=AM; raw 3-7 = best-effort labels.
MODULATION_BP_LIST = [
    "Ignore",
    "FM",
    "AM",
    "USB",
    "Auto",
    "Enforce FM",
    "Enforce AM",
    "Enforce USB",
]
# Bandwidth: 3 bits. Raw value = list index.
# EEPROM: raw 0=Ignore, 1=Wide, 2=Narrow, 5=FM Tuner; 3/4/6/7 = placeholders.
BANDWIDTH_BP_LIST = [
    "Ignore",
    "Wide",
    "Narrow",
    "BW(3)",
    "BW(4)",
    "FM Tuner",
    "BW(6)",
    "BW(7)",
]
MAXPOWER_BP_LIST = ["Ignore"] + [str(x) for x in range(1, 256)]
# Scan preset 0x1B00: modulation bits[1:0] (ordering differs from channels).
# Verified live EEPROM Mar 2026.
MODULATION_SP_LIST = ["FM", "AM", "USB", "Auto"]
# Ultrascan: 3 bits at bits[4:2]; displayed 0-7.
ULTRASCAN_SP_LIST = [str(x) for x in range(8)]
# 15 groups A-O in programmer UI
GROUP_LETTERS = [
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O",
]


def _do_status(radio, block_num, total=NUM_BLOCKS):
    if radio.status_fn:
        status = chirp_common.Status()
        status.msg = "Cloning"
        status.cur = block_num
        status.max = total
        radio.status_fn(status)


def _checksum(data):
    return sum(data) % 256


def _enter_programming_mode(radio):
    """Disable radio before EEPROM read/write (per protocol doc)."""
    serial = radio.pipe
    serial.timeout = 0.5
    serial.write(bytes([CMD_DISABLE_RADIO]))
    ack = serial.read(1)
    if ack != bytes([CMD_DISABLE_RADIO]):
        raise errors.RadioError("Radio did not acknowledge disable command")


def _exit_programming_mode(radio):
    """Re-enable radio after EEPROM read/write."""
    serial = radio.pipe
    serial.write(bytes([CMD_ENABLE_RADIO]))
    ack = serial.read(1)
    if ack != bytes([CMD_ENABLE_RADIO]):
        raise errors.RadioError("Radio did not acknowledge enable command")


def _read_block(radio, block_num):
    serial = radio.pipe
    serial.write(bytes([CMD_READ_EEPROM, block_num]))
    packet_id = serial.read(1)
    if packet_id != bytes([CMD_READ_EEPROM]):
        raise errors.RadioError("Invalid read response (packet ID)")
    data = serial.read(BLOCK_SIZE)
    if len(data) != BLOCK_SIZE:
        raise errors.RadioError("Short read: got %d bytes" % len(data))
    checksum_r = serial.read(1)
    if len(checksum_r) != 1:
        raise errors.RadioError("No checksum byte")
    if _checksum(data) != checksum_r[0]:
        LOG.debug("Checksum mismatch block %d", block_num)
    return data


def _write_block(radio, block_num, data):
    if len(data) != BLOCK_SIZE:
        raise errors.RadioError("Block must be %d bytes" % BLOCK_SIZE)
    serial = radio.pipe
    serial.write(bytes([CMD_WRITE_EEPROM, block_num]))
    serial.write(data)
    serial.write(bytes([_checksum(data)]))
    ack = serial.read(1)
    if ack != bytes([CMD_WRITE_EEPROM]):
        raise errors.RadioError(
            "Radio did not acknowledge write block %d" %
            block_num)


def _reboot_radio(radio):
    radio.pipe.write(bytes([CMD_REBOOT_RADIO]))


def do_download(radio):
    """Download full 8 KB EEPROM from radio."""
    _enter_programming_mode(radio)
    data = bytearray()
    try:
        for block_num in range(NUM_BLOCKS):
            data.extend(_read_block(radio, block_num))
            _do_status(radio, block_num + 1)
    finally:
        _exit_programming_mode(radio)
    return memmap.MemoryMapBytes(bytes(data))


def do_upload(radio):
    """Upload full 8 KB EEPROM to radio."""
    mmap = radio.get_mmap()
    if len(mmap) < EEPROM_SIZE:
        raise errors.RadioError("Image too small")
    _enter_programming_mode(radio)
    try:
        for block_num in range(NUM_BLOCKS):
            start = block_num * BLOCK_SIZE
            block_data = bytes(mmap[start:start + BLOCK_SIZE])
            _write_block(radio, block_num, block_data)
            _do_status(radio, block_num + 1)
    finally:
        _exit_programming_mode(radio)
    _reboot_radio(radio)


def _decode_tone(tone_word):
    """Decode rxSubTone/txSubTone to (mode, value, polarity)."""
    tone_word = int(tone_word) & 0xFFFF
    if 0 < tone_word <= 3000:
        return "Tone", tone_word / 10.0, None
    if tone_word & 0x8000:
        dcs_code = tone_word & 0x01FF
        polarity = "R" if (tone_word & 0x4000) else "N"
        # 9-bit payload indexes ALL_DTCS_CODES (0..511), not the CHIRP code
        # integer (e.g. index 21 -> DCS 025 -> Memory value 25). Allow 0..511.
        if 0 <= dcs_code <= 511:
            return "DTCS", dcs_code, polarity
    return None, None, None


def _chirp_dtcs_from_firmware_raw(dcs_code):
    """
    Map 9-bit firmware sub-tone payload to chirp_common.Memory.dtcs / rx_dtcs.

    nicFW 2.5 stores a linear index 0..511 into ALL_DTCS_CODES (same pattern as
    e.g. icf520 / many Kenwood-style drivers), not the CHIRP code integer.

    A raw value like 21 is both a valid index (DCS 025 -> 25) and a valid CHIRP
    code (021 -> 21). The radio uses the index interpretation; treating 21 as
    a literal code mis-shows 021 instead of 025.
    """
    if dcs_code is None:
        return None
    raw = int(dcs_code)
    codes = chirp_common.ALL_DTCS_CODES
    if 0 <= raw < len(codes):
        return codes[raw]
    return min(codes, key=lambda c: abs(c - raw))


def _dtcs_chirp_value_to_firmware_index(value):
    """Map CHIRP dtcs/rx_dtcs integer to EEPROM index for _encode_tone."""
    if value is None:
        return 0
    codes = chirp_common.ALL_DTCS_CODES
    v = int(value)
    try:
        return codes.index(v)
    except ValueError:
        nearest = min(codes, key=lambda c: abs(c - v))
        return codes.index(nearest)


def _encode_tone(mode, value, polarity=None):
    """Build 16-bit tone word; bitwise stores it big-endian."""
    if mode == "Tone" and value is not None:
        tone_word = int(round(value * 10.0))
        if 0 <= tone_word <= 3000:
            return tone_word
    if mode == "DTCS" and value is not None:
        idx = _dtcs_chirp_value_to_firmware_index(value) & 0x1FF
        tone_word = 0x8000 | idx
        if polarity == "R" or polarity == "I":
            tone_word |= 0x4000
        return tone_word
    return 0


def _get_channel_info(memobj, index):
    """Return vfoA (-2), vfoB (-1), or memory[0..197] Bitwise struct."""
    if index == -2:
        return memobj.vfoA
    if index == -1:
        return memobj.vfoB
    if 0 <= index <= 197:
        return memobj.memory[index]
    raise errors.InvalidValueError("Channel index out of range")


def _build_groups_display(memobj):
    """Build group-slot spinner labels from EEPROM group names.

    Slot 0 is "None". Slots 1-15 use GROUP_LETTERS; custom labels show as
    "L: name". Order matches the numeric value stored in EEPROM.
    """
    display = ["None"]
    for i, letter in enumerate(GROUP_LETTERS):
        try:
            gl = memobj.groupLabels[i]
            raw = gl.get_raw()
            lbl = raw.decode("ascii", "replace").rstrip(
                "\x00 \xff").strip() if raw and len(raw) >= 6 else ""
        except Exception:
            lbl = ""
        display.append("%s: %s" % (letter, lbl) if lbl else letter)
    return display


def _channel_to_memory(memobj, number, mem):
    """Populate chirp_common.Memory from channelInfo (V2.5 big-endian)."""
    _mem = _get_channel_info(memobj, number)
    mem.number = number
    rxf = int(_mem.rxFreq)
    txf = int(_mem.txFreq)
    # Frequencies in 10 Hz units
    mem.freq = rxf * 10
    if rxf == 0 and txf == 0:
        mem.empty = True
        return mem
    mem.empty = False
    if txf == 0:
        mem.duplex = "off"
        mem.offset = 0
    elif rxf == txf:
        mem.duplex = ""
        mem.offset = 0
    else:
        mem.duplex = "+" if txf > rxf else "-"
        mem.offset = abs(rxf - txf) * 10
    mem.skip = "S" if int(_mem.skip) else ""
    _tx = int(_mem.txPower)
    _pwr_lv = power_levels_for_memobj(memobj)
    if _tx == TXPower_NT or _tx < 0 or _tx >= len(_pwr_lv):
        mem.power = _pwr_lv[0]
    else:
        mem.power = _pwr_lv[_tx]
    # Decode name from raw channel bytes (name is last 12 bytes of 32-byte
    # channelInfo)
    raw = _mem.get_raw()
    if raw and len(raw) >= 32:
        name_bytes = bytes(raw[20:32])
        mem.name = name_bytes.decode(
            "ascii", "replace").rstrip("\x00 \xff").strip() or ""
    else:
        name_parts = []
        for b in _mem.name:
            if isinstance(b, int):
                name_parts.append(chr(b) if 32 <= b < 127 else "")
            elif isinstance(b, str) and len(b) == 1:
                name_parts.append(b if 32 <= ord(b) < 127 else "")
            else:
                name_parts.append("")
        mem.name = "".join(name_parts).rstrip() or ""
    mod_idx = int(
        _mem.modulation) if int(
        _mem.modulation) < len(MODULATION_LIST) else 1
    is_narrow = bool(int(_mem.bandwidth))
    mem.mode = _fw_channel_mode_to_chirp(mod_idx, is_narrow)
    txmode, txval, txpol = _decode_tone(_mem.txSubTone)
    rxmode, rxval, rxpol = _decode_tone(_mem.rxSubTone)
    if txmode == "DTCS" and txval is not None:
        txval = _chirp_dtcs_from_firmware_raw(txval)
    if rxmode == "DTCS" and rxval is not None:
        rxval = _chirp_dtcs_from_firmware_raw(rxval)
    chirp_common.split_tone_decode(
        mem, (txmode, txval, txpol), (rxmode, rxval, rxpol))
    # Beyond chirp_common.Memory (freq, name, mode, duplex, offset, power,
    # tones, tuning_step, skip, comment, empty, ...) use mem.extra only:
    # group slots, bandwidth (firmware bit), and busyLock (BCL).
    # See chirp/chirp_common.py (class Memory).
    mem.extra = RadioSettingGroup("extra", "Extra")
    g = int(_mem.groups)
    g0, g1, g2, g3 = (g >> 0) & 0xF, (g >> 4) & 0xF, (g >>
                                                      8) & 0xF, (g >> 12) & 0xF
    mem.comment = ""
    groups_display = _build_groups_display(memobj)
    for slot, val in [("group1", g0), ("group2", g1),
                      ("group3", g2), ("group4", g3)]:
        rs = RadioSetting(slot,
                          "Groups slot %s (letter)" % slot[-1],
                          RadioSettingValueList(groups_display,
                                                groups_display[val]))
        mem.extra.append(rs)
    # Bandwidth is bit 0 of flags byte. 0=Wide, 1=Narrow — extra mirrors
    # mem.mode (NFM/NAM ↔ Narrow).
    bw = "Narrow" if is_narrow else "Wide"
    mem.extra.append(
        RadioSetting(
            "bandwidth",
            "Bandwidth",
            RadioSettingValueList(
                BANDWIDTH_LIST,
                bw)))
    # Busy Lock is bit 7 of flags byte (matches MEM_FORMAT after MSB→LSB field
    # order).
    busy_lock = bool(int(_mem.busyLock))
    mem.extra.append(
        RadioSetting(
            "busyLock",
            "Busy Lock",
            RadioSettingValueBoolean(busy_lock)))
    # Step is global in the radio (Settings only). Memory.tuning_step is kHz
    # (chirp_common); pick a grid step from nicFW Hz list or default 12.5 kHz.
    _step_hz = next(
        (s for s in VALID_TUNING_STEPS_HZ if mem.freq % s == 0),
        DEFAULT_TUNING_STEP_HZ,
    )
    mem.tuning_step = _step_hz / 1000.0
    return mem


def _memory_to_channel(memobj, number, mem):
    """Write chirp_common.Memory into channelInfo (V2.5 big-endian)."""
    _mem = _get_channel_info(memobj, number)
    if mem.empty:
        _mem.rxFreq = 0
        _mem.txFreq = 0
        _mem.txPower = 0
        _mem.rxSubTone = 0
        _mem.txSubTone = 0
        _mem.groups = 0
        for i in range(12):
            _mem.name[i] = 0xFF
        _mem.skip = 0
        return
    _mem.rxFreq = mem.freq // 10
    if mem.duplex == "off":
        _mem.txFreq = 0
    elif mem.duplex == "split":
        _mem.txFreq = mem.offset // 10
    elif mem.duplex == "+":
        _mem.txFreq = (mem.freq + mem.offset) // 10
    elif mem.duplex == "-":
        _mem.txFreq = (mem.freq - mem.offset) // 10
    else:
        _mem.txFreq = mem.freq // 10
    _mem.txPower = _tx_power_u8_from_memory(memobj, mem.power)
    name = (mem.name or "")[:12].ljust(12)
    for i, c in enumerate(name):
        o = ord(c)
        _mem.name[i] = o if 32 <= o < 127 else 0x20
    if mem.mode == NFM:
        _mem.modulation = MODULATION_LIST.index("FM")
        _mem.bandwidth = 1
    elif mem.mode == NAM:
        _mem.modulation = MODULATION_LIST.index("AM")
        _mem.bandwidth = 1
    elif mem.mode in MODULATION_LIST:
        _mem.modulation = MODULATION_LIST.index(mem.mode)
        _mem.bandwidth = 1 if _extra_bandwidth_is_narrow(mem) else 0
    else:
        _mem.modulation = 0
        _mem.bandwidth = 1 if _extra_bandwidth_is_narrow(mem) else 0
    # Busy Lock is incompatible with repeater/split operation (radio rule).
    _busy_requested = bool(
        mem.extra and any(
            e.get_name() == "busyLock" and bool(
                e.value) for e in mem.extra))
    _mem.busyLock = 1 if (
        _busy_requested and mem.duplex not in (
            "+", "-", "split")) else 0
    (txmode, txval, txpol), (rxmode, rxval,
                             rxpol) = chirp_common.split_tone_encode(mem)
    _mem.txSubTone = _encode_tone(txmode, txval, txpol)
    _mem.rxSubTone = _encode_tone(rxmode, rxval, rxpol)
    if mem.extra:
        g0 = g1 = g2 = g3 = 0
        groups_display = _build_groups_display(memobj)
        for e in mem.extra:
            n = e.get_name()
            v = (
                e.value.get_value()
                if hasattr(e.value, "get_value")
                else str(e.value)
            )
            if v in groups_display:
                idx = groups_display.index(v)
            elif v in GROUPS_LIST:
                # fallback: bare letter from old image
                idx = GROUPS_LIST.index(v)
            else:
                idx = 0
            if n == "group1":
                g0 = idx
            elif n == "group2":
                g1 = idx
            elif n == "group3":
                g2 = idx
            elif n == "group4":
                g3 = idx
        _mem.groups = g0 | (g1 << 4) | (g2 << 8) | (g3 << 12)
    elif getattr(mem, "comment", None) and isinstance(mem.comment, str):
        # Parse Comment column (e.g. "AG") into group slots when edited in main
        # table
        letters = [c.upper() for c in mem.comment.strip()
                   if c.upper() in GROUP_LETTERS][:4]
        g0 = g1 = g2 = g3 = 0
        for i, letter in enumerate(letters):
            idx = GROUP_LETTERS.index(letter) + 1  # A=1, B=2, ... O=15
            if i == 0:
                g0 = idx
            elif i == 1:
                g1 = idx
            elif i == 2:
                g2 = idx
            else:
                g3 = idx
        _mem.groups = g0 | (g1 << 4) | (g2 << 8) | (g3 << 12)
    _mem.skip = 1 if mem.skip == "S" else 0


@directory.register
class TH3NicFw25(chirp_common.CloneModeRadio):
    """TIDRADIO TD-H3 with nicFW V2.5 firmware."""
    VENDOR = "TIDRADIO"
    MODEL = "TD-H3 nicFW 2.5"
    BAUD_RATE = 38400
    # nicFW V2.5 settings block magic at 0x1900 (big-endian); 8192-byte EEPROM.
    _memsize = 8192

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) != cls._memsize:
            return False
        magic = struct.unpack_from(">H", filedata, 0x1900)[0]
        return magic == 0xD82F

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "->DTCS",
            "DTCS->",
            "DTCS->DTCS"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        # RX span per nicFW Programmer / band plan; TX still follows firmware.
        # CHIRP uses lo <= freq < hi; hi = 600_000_001 Hz so 600.0 MHz is
        # included.
        rf.valid_bands = [
            (50_000_000, 600_000_001),
        ]
        # Finer RX sub-ranges (reference only; single band above unless split):
        #   (50_000_000, 76_000_000),      # Low VHF / FM
        #   (108_000_000, 136_000_000),    # AM airband; 8.33 kHz; AM demod
        #   (174_000_000, 350_000_000),    # Extended VHF
        #   (350_000_000, 400_000_000),    # UHF / emergency / military
        #   (470_000_000, 600_000_001),    # Extended UHF
        rf.valid_modes = list(VALID_MODES)
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_skips = ["", "S"]
        rf.valid_name_length = 12
        rf.valid_power_levels = power_levels_for_memobj(
            getattr(self, "_memobj", None))
        # Radio shows "Channel Bank 1".."198"; CHIRP 1-198 = memory[0]..[197]
        rf.memory_bounds = (1, 198)
        rf.has_comment = True
        # nicFW steps in kHz; required for chirp_common.required_step (e.g. CI
        # test_validate_all_steps at 462.5625 MHz on 6.25 kHz grid).
        rf.has_tuning_step = True
        rf.valid_tuning_steps = [hz / 1000.0 for hz in VALID_TUNING_STEPS_HZ]
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except Exception as e:
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to upload to radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        magic = int(self._memobj.settings.magic)
        if magic != MAGIC_SETTINGS_V25:
            LOG.warning(
                "Settings magic 0x%04X is not V2.5 0xD82F; "
                "image may be wrong firmware",
                magic)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        index = number - 1  # CHIRP 1-198 -> radio memory[0]..[197]
        _mem = _get_channel_info(self._memobj, index)
        raw = _mem.get_raw()
        if raw and len(raw) >= 4 and raw[0:4] == b"\xff\xff\xff\xff":
            mem.empty = True
            return mem
        mem = _channel_to_memory(self._memobj, index, mem)
        mem.number = number  # keep 1-based for display
        return mem

    def set_memory(self, mem):
        index = mem.number - 1  # CHIRP 1-198 -> radio memory[0]..[197]
        _memory_to_channel(self._memobj, index, mem)
        if not mem.empty and hasattr(self, "_mmap") and self._mmap is not None:
            _apply_channel_bandwidth_bit0_to_mmap(
                self._mmap, index, _channel_memory_wants_narrow(mem))

    def validate_memory(self, mem):
        """Check NFM/NAM vs Memory.extra bandwidth (RadioDroid mmap)."""
        msgs = super().validate_memory(mem)
        if getattr(mem, "empty", True):
            return msgs
        if mem.mode in (NFM, NAM):
            bw = _extra_bandwidth_value_str(mem)
            if bw is not None and "Narrow" not in bw:
                msgs.append(
                    chirp_common.ValidationError(
                        "Mode %s needs narrow bandwidth under Radio Specific; "
                        "set Bandwidth to Narrow or use FM/AM wideband." %
                        mem.mode))
        return msgs

    def get_settings(self):
        s = self._memobj.settings
        top = RadioSettingGroup("root", "Settings")

        # Basic
        basic = RadioSettingGroup("basic", "Basic Settings")
        basic.append(
            RadioSetting(
                "squelch", "Squelch", RadioSettingValueInteger(
                    0, 9, int(
                        s.squelch))))
        basic.append(
            RadioSetting(
                "dualWatch",
                "Dual Watch",
                RadioSettingValueBoolean(
                    bool(
                        s.dualWatch))))
        basic.append(
            RadioSetting(
                "activeVfo",
                "Active VFO",
                RadioSettingValueList(
                    ACTIVEVFO_LIST,
                    ACTIVEVFO_LIST[min(int(s.activeVfo), 1)],
                ),
            )
        )
        step_val = int(s.step)
        step_idx = STEP_VALUES.index(
            step_val) if step_val in STEP_VALUES else 0
        basic.append(
            RadioSetting(
                "step",
                "Tuning Step (10 Hz)",
                RadioSettingValueList(
                    STEP_LIST,
                    STEP_LIST[step_idx])))
        basic.append(
            RadioSetting(
                "rxSplit", "RX Split (10 Hz)", RadioSettingValueInteger(
                    0, 65535, int(
                        s.rxSplit))))
        basic.append(
            RadioSetting(
                "txSplit", "TX Split (10 Hz)", RadioSettingValueInteger(
                    0, 65535, int(
                        s.txSplit))))
        basic.append(
            RadioSetting(
                "pttMode", "PTT Mode", RadioSettingValueInteger(
                    0, 255, int(
                        s.pttMode))))
        basic.append(
            RadioSetting(
                "txModMeter",
                "TX Modulation Meter",
                RadioSettingValueBoolean(
                    bool(
                        s.txModMeter))))
        basic.append(
            RadioSetting(
                "micGain", "Mic Gain", RadioSettingValueInteger(
                    0, 31, int(
                        s.micGain))))
        basic.append(
            RadioSetting(
                "txDeviation", "TX Deviation", RadioSettingValueInteger(
                    0, 255, int(
                        s.txDeviation))))
        basic.append(
            RadioSetting(
                "battStyle",
                "Battery Style",
                RadioSettingValueList(
                    BATTSTYLE_LIST,
                    BATTSTYLE_LIST[min(int(s.battStyle), 3)],
                ),
            )
        )
        top.append(basic)

        # Scan
        scan = RadioSettingGroup("scan", "Scan")
        scan.append(
            RadioSetting(
                "scanRange", "Scan Range (10 Hz)", RadioSettingValueInteger(
                    0, 65535, int(
                        s.scanRange))))
        scan.append(
            RadioSetting(
                "scanPersist", "Scan Persist", RadioSettingValueInteger(
                    0, 65535, int(
                        s.scanPersist))))
        scan.append(
            RadioSetting(
                "scanResume", "Scan Resume", RadioSettingValueInteger(
                    0, 255, int(
                        s.scanResume))))
        scan.append(
            RadioSetting(
                "ultraScan", "Ultra Scan", RadioSettingValueInteger(
                    0, 255, int(
                        s.ultraScan))))
        scan.append(
            RadioSetting(
                "scanUpdate", "Scan Update", RadioSettingValueInteger(
                    0, 255, int(
                        s.scanUpdate))))
        top.append(scan)

        # Display / Audio
        disp = RadioSettingGroup("display", "Display & Audio")
        disp.append(
            RadioSetting(
                "toneMonitor",
                "Tone Monitor",
                RadioSettingValueList(
                    TONEMONITOR_LIST,
                    TONEMONITOR_LIST[min(int(s.toneMonitor), 2)],
                ),
            )
        )
        disp.append(
            RadioSetting(
                "lcdBrightness", "LCD Brightness", RadioSettingValueInteger(
                    0, 28, int(
                        s.lcdBrightness))))
        disp.append(
            RadioSetting(
                "lcdTimeout", "LCD Timeout", RadioSettingValueInteger(
                    0, 200, int(
                        s.lcdTimeout))))
        disp.append(
            RadioSetting(
                "breathe", "Breathe", RadioSettingValueInteger(
                    0, 255, int(
                        s.breathe))))
        disp.append(
            RadioSetting(
                "dimmer", "Dimmer", RadioSettingValueInteger(
                    0, 255, int(
                        s.dimmer))))
        disp.append(
            RadioSetting(
                "lcdInverted",
                "LCD Inverted",
                RadioSettingValueBoolean(
                    bool(
                        s.lcdInverted))))
        disp.append(
            RadioSetting(
                "repeaterTone", "Repeater Tone (Hz)", RadioSettingValueInteger(
                    0, 65535, int(
                        s.repeaterTone))))
        disp.append(
            RadioSetting(
                "dtmfDev", "DTMF Deviation", RadioSettingValueInteger(
                    0, 255, int(
                        s.dtmfDev))))
        disp.append(
            RadioSetting(
                "gamma", "Gamma", RadioSettingValueInteger(
                    0, 255, int(
                        s.gamma))))
        disp.append(
            RadioSetting(
                "sBarStyle", "Signal Bar Style", RadioSettingValueInteger(
                    0, 255, int(
                        s.sBarStyle))))
        disp.append(
            RadioSetting(
                "sqNoiseLev", "Squelch Noise Level", RadioSettingValueInteger(
                    0, 255, int(
                        s.sqNoiseLev))))
        disp.append(
            RadioSetting(
                "sBarAlwaysOn",
                "Signal Bar Always On",
                RadioSettingValueBoolean(
                    bool(
                        s.sBarAlwaysOn))))
        disp.append(
            RadioSetting(
                "afFilters",
                "AF Filters",
                RadioSettingValueList(
                    AF_FILTERS_LIST,
                    AF_FILTERS_LIST[
                        min(int(s.afFilters), len(AF_FILTERS_LIST) - 1)
                    ],
                ),
            )
        )
        disp.append(
            RadioSetting(
                "ifFreq", "IF Freq", RadioSettingValueInteger(
                    0, 255, int(
                        s.ifFreq))))
        top.append(disp)

        # VFO State A
        vfo_a = RadioSettingGroup("vfoStateA", "VFO A State")
        vfo_a.append(
            RadioSetting(
                "vfoState_group0",
                "Group (0=channel mode)",
                RadioSettingValueInteger(
                    0, 15, int(s.vfoState_group0))))
        vfo_a.append(
            RadioSetting(
                "vfoState_lastGroup0", "Last Group", RadioSettingValueInteger(
                    0, 15, int(
                        s.vfoState_lastGroup0))))
        for i in range(16):
            # clamp so UI always shows a value (0-197)
            v = min(max(int(s.vfoState_groupModeChannels0[i]), 0), 197)
            vfo_a.append(
                RadioSetting(
                    "vfoState_groupModeChannels0_%d" %
                    i,
                    "Group Channel %d" %
                    i,
                    RadioSettingValueInteger(
                        0,
                        197,
                        v)))
        _m0 = min(int(s.vfoState_mode0), 1)
        vfo_a.append(
            RadioSetting(
                "vfoState_mode0",
                "Mode (0=VFO, 1=Channel/Group)",
                RadioSettingValueList(OP_MODE_LIST, OP_MODE_LIST[_m0]),
            )
        )
        top.append(vfo_a)

        # VFO State B
        vfo_b = RadioSettingGroup("vfoStateB", "VFO B State")
        vfo_b.append(
            RadioSetting(
                "vfoState_group1",
                "Group (0=channel mode)",
                RadioSettingValueInteger(
                    0, 15, int(s.vfoState_group1))))
        vfo_b.append(
            RadioSetting(
                "vfoState_lastGroup1", "Last Group", RadioSettingValueInteger(
                    0, 15, int(
                        s.vfoState_lastGroup1))))
        for i in range(16):
            # clamp so UI always shows a value (0-197)
            v = min(max(int(s.vfoState_groupModeChannels1[i]), 0), 197)
            vfo_b.append(
                RadioSetting(
                    "vfoState_groupModeChannels1_%d" %
                    i,
                    "Group Channel %d" %
                    i,
                    RadioSettingValueInteger(
                        0,
                        197,
                        v)))
        _m1 = min(int(s.vfoState_mode1), 1)
        vfo_b.append(
            RadioSetting(
                "vfoState_mode1",
                "Mode (0=VFO, 1=Channel/Group)",
                RadioSettingValueList(OP_MODE_LIST, OP_MODE_LIST[_m1]),
            )
        )
        top.append(vfo_b)

        # Misc
        misc = RadioSettingGroup("misc", "Misc")
        misc.append(
            RadioSetting(
                "keyLock",
                "Key Lock",
                RadioSettingValueBoolean(
                    bool(
                        s.keyLock))))
        misc.append(
            RadioSetting(
                "bluetooth",
                "Bluetooth",
                RadioSettingValueBoolean(
                    bool(
                        s.bluetooth))))
        misc.append(
            RadioSetting(
                "powerSave",
                "Power Save",
                RadioSettingValueBoolean(
                    bool(
                        s.powerSave))))
        misc.append(
            RadioSetting(
                "keyTones",
                "Key Tones",
                RadioSettingValueBoolean(
                    bool(
                        s.keyTones))))
        misc.append(
            RadioSetting(
                "ste", "STE (Squelch Tail Elim)", RadioSettingValueInteger(
                    0, 255, int(
                        s.ste))))
        _rfg = min(int(s.rfGain), len(RFGAIN_LIST) - 1)
        misc.append(
            RadioSetting(
                "rfGain",
                "RF Gain",
                RadioSettingValueList(RFGAIN_LIST, RFGAIN_LIST[_rfg]),
            )
        )
        misc.append(
            RadioSetting(
                "lastFmtFreq", "Last FM Tuner Freq", RadioSettingValueInteger(
                    0, 0xFFFFFFFF, int(
                        s.lastFmtFreq))))
        misc.append(RadioSetting("vox", "VOX", RadioSettingValueList(
            VOX_LIST, VOX_LIST[min(int(s.vox), len(VOX_LIST) - 1)])))
        misc.append(
            RadioSetting(
                "voxTail", "VOX Tail", RadioSettingValueInteger(
                    0, 65535, int(
                        s.voxTail))))
        misc.append(
            RadioSetting(
                "txTimeout", "TX Timeout (s)", RadioSettingValueInteger(
                    0, 255, int(
                        s.txTimeout))))
        misc.append(
            RadioSetting(
                "dtmfSpeed", "DTMF Speed", RadioSettingValueInteger(
                    0, 255, int(
                        s.dtmfSpeed))))
        misc.append(
            RadioSetting(
                "noiseGate", "Noise Gate", RadioSettingValueInteger(
                    0, 255, int(
                        s.noiseGate))))
        misc.append(
            RadioSetting(
                "asl", "ASL", RadioSettingValueInteger(
                    0, 255, int(
                        s.asl))))
        misc.append(
            RadioSetting(
                "disableFmt",
                "Disable FM Tuner",
                RadioSettingValueBoolean(
                    bool(
                        s.disableFmt))))
        misc.append(
            RadioSetting(
                "dualWatchDelay", "Dual Watch Delay", RadioSettingValueInteger(
                    0, 255, int(
                        s.dualWatchDelay))))
        misc.append(
            RadioSetting(
                "subToneDeviation",
                "Sub Tone Deviation",
                RadioSettingValueInteger(
                    0, 127, int(s.subToneDeviation))))
        misc.append(
            RadioSetting(
                "amAgcFix",
                "AM AGC Fix",
                RadioSettingValueBoolean(
                    bool(
                        s.amAgcFix))))
        top.append(misc)

        # Security
        sec = RadioSettingGroup("security", "Security")
        sec.append(
            RadioSetting(
                "pin", "PIN", RadioSettingValueInteger(
                    0, 65535, int(
                        s.pin))))
        sec.append(
            RadioSetting(
                "pinAction", "PIN Action", RadioSettingValueInteger(
                    0, 255, int(
                        s.pinAction))))
        sec.append(
            RadioSetting(
                "lockedVfo", "Locked VFO", RadioSettingValueInteger(
                    0, 255, int(
                        s.lockedVfo))))
        sec.append(
            RadioSetting(
                "vfoLockActive",
                "VFO Lock Active",
                RadioSettingValueBoolean(
                    bool(
                        s.vfoLockActive))))
        top.append(sec)

        # Band Plan (20 plans at 0x1A02; match nicFW Programmer: freq in 10 Hz,
        # display MHz)
        bandplan_grp = RadioSettingGroup("bandplan", "Band Plan")
        for i in range(20):
            bp = self._memobj.bandPlans[i]
            start_mhz = int(bp.startFreq) * 10 / 1e6
            end_mhz = int(bp.endFreq) * 10 / 1e6
            # txAllowed bit=1 means TX is allowed; wrap bit=1 means scan wrap
            # is enabled.
            _tx_allow = bool(bp.txAllowed)
            _wrap = bool(bp.wrap)
            # Raw value IS the list index for both modulation and bandwidth (no
            # remapping).
            _mod_raw = int(bp.modulation) & 7
            _mod_idx = min(_mod_raw, len(MODULATION_BP_LIST) - 1)
            _bw_raw = int(bp.bandwidth) & 7
            _bw_idx = min(_bw_raw, len(BANDWIDTH_BP_LIST) - 1)
            plan = RadioSettingGroup("bandPlan_%d" % i, "Plan %d" % (i + 1))
            plan.append(
                RadioSetting(
                    "bandPlan_%d_startFreq" %
                    i,
                    "Start (MHz)",
                    RadioSettingValueFloat(
                        0,
                        1500,
                        start_mhz,
                        0.00001)))
            plan.append(
                RadioSetting(
                    "bandPlan_%d_endFreq" %
                    i,
                    "End (MHz)",
                    RadioSettingValueFloat(
                        0,
                        1500,
                        end_mhz,
                        0.00001)))
            _mp = min(int(bp.maxPower), len(MAXPOWER_BP_LIST) - 1)
            plan.append(
                RadioSetting(
                    "bandPlan_%d_maxPower" % i,
                    "Max Power",
                    RadioSettingValueList(
                        MAXPOWER_BP_LIST, MAXPOWER_BP_LIST[_mp],
                    ),
                )
            )
            plan.append(
                RadioSetting(
                    "bandPlan_%d_txAllowed" %
                    i,
                    "TX Allowed",
                    RadioSettingValueBoolean(_tx_allow)))
            plan.append(
                RadioSetting(
                    "bandPlan_%d_wrap" %
                    i,
                    "Wrap",
                    RadioSettingValueBoolean(_wrap)))
            plan.append(
                RadioSetting(
                    "bandPlan_%d_modulation" %
                    i,
                    "Modulation",
                    RadioSettingValueList(
                        MODULATION_BP_LIST,
                        MODULATION_BP_LIST[_mod_idx])))
            plan.append(
                RadioSetting(
                    "bandPlan_%d_bandwidth" %
                    i,
                    "Bandwidth",
                    RadioSettingValueList(
                        BANDWIDTH_BP_LIST,
                        BANDWIDTH_BP_LIST[_bw_idx])))
            bandplan_grp.append(plan)
        top.append(bandplan_grp)

        # Scan Presets: 20 @ 0x1B00; no magic; empty when startFreq==0.
        # Modulation: 0=FM, 1=AM, 2=USB, 3=Auto (EEPROM dump verify Mar 2026).
        # Ultrascan: 3 bits at bits[4:2] of flags byte; range 0-7.
        # Range is 10 kHz units; End Freq = Start Freq + Range.
        # Step stored as 10 Hz units; displayed in kHz.
        # Label: 8 ASCII chars (+ null terminator byte) at struct offset 11.
        scanpreset_grp = RadioSettingGroup("scanPresets", "Scan Presets")
        for i in range(20):
            sp = self._memobj.scanPresets[i]
            start_raw = int(sp.startFreq)
            start_hz = start_raw * 10                          # Hz
            start_mhz = start_hz / 1e6
            # Empty: startFreq==0; Programmer hides end/step even if
            # EEPROM holds non-zero defaults.
            if start_raw == 0:
                end_mhz = 0.0
                step_khz = 0.0
            else:
                range_raw = int(sp.range)
                end_hz = start_hz + range_raw * 10000          # Hz
                end_mhz = end_hz / 1e6
                step_raw = int(sp.step)
                # 10 Hz units -> kHz
                step_khz = step_raw * 10 / 1000.0
            _resume = int(sp.resume)
            _persist = int(sp.persist)
            # ultrascan is a 6-bit struct field covering bits[7:2]; only lower
            # 3 bits (0-7) are used
            _ultrascan = int(sp.ultrascan) & 0x07
            _mod_raw = int(sp.modulation) & 0x03
            try:
                raw = sp.get_raw()
                # label starts at struct offset 11; 8 content bytes (offset 19
                # is null terminator)
                label_bytes = bytes(raw[11:19]) if raw and len(
                    raw) >= 19 else b""
                label_str = label_bytes.decode(
                    "ascii", "replace").rstrip("\x00 \xff").strip()
            except Exception:
                label_str = ""
            preset = RadioSettingGroup(
                "scanPreset_%d" %
                i, "Preset %d" %
                (i + 1))
            preset.append(RadioSetting(
                "scanPreset_%d_startFreq" % i, "Start (MHz)",
                RadioSettingValueFloat(0, 1500, start_mhz, 0.00001)))
            preset.append(RadioSetting(
                "scanPreset_%d_endFreq" % i, "End (MHz)",
                RadioSettingValueFloat(0, 1500, end_mhz, 0.00001)))
            preset.append(RadioSetting(
                "scanPreset_%d_step" % i, "Step (kHz)",
                RadioSettingValueFloat(0, 1000, step_khz, 0.01)))
            preset.append(RadioSetting(
                "scanPreset_%d_resume" % i, "Scan Resume",
                RadioSettingValueInteger(0, 255, _resume)))
            preset.append(RadioSetting(
                "scanPreset_%d_persist" % i, "Scan Persist",
                RadioSettingValueInteger(0, 255, _persist)))
            preset.append(
                RadioSetting(
                    "scanPreset_%d_modulation" %
                    i,
                    "Modulation",
                    RadioSettingValueList(
                        MODULATION_SP_LIST,
                        MODULATION_SP_LIST[_mod_raw])))
            preset.append(
                RadioSetting(
                    "scanPreset_%d_ultrascan" %
                    i,
                    "Ultrascan (0-7)",
                    RadioSettingValueList(
                        ULTRASCAN_SP_LIST,
                        ULTRASCAN_SP_LIST[_ultrascan])))
            preset.append(RadioSetting(
                "scanPreset_%d_label" % i, "Label (8 chars)",
                RadioSettingValueString(0, 8, label_str)))
            scanpreset_grp.append(preset)
        top.append(scanpreset_grp)

        # Group Labels (0x1C90; Group A-O = 15 labels, 6 chars each; match
        # nicFW Programmer Group Labels tab)
        gl_grp = RadioSettingGroup("groupLabels", "Group Labels")
        for i in range(15):
            gl = self._memobj.groupLabels[i]
            try:
                raw = gl.get_raw()
                label_str = raw.decode("ascii", "replace").rstrip(
                    "\x00 \xff").strip() if raw and len(raw) >= 6 else ""
            except Exception:

                def _group_label_chr(c):
                    if (
                        isinstance(c, str)
                        and len(c) == 1
                        and 32 <= ord(c) < 127
                    ):
                        return chr(ord(c))
                    if isinstance(c, int) and 32 <= c < 127:
                        return chr(c)
                    return ""

                label_str = "".join(
                    _group_label_chr(c) for c in gl.label
                ).rstrip()
            gl_grp.append(
                RadioSetting(
                    "groupLabel_%d" %
                    i,
                    "Group %s" %
                    GROUP_LETTERS[i],
                    RadioSettingValueString(
                        0,
                        6,
                        label_str)))
        top.append(gl_grp)

        # Calibration (per-radio; at 0x1DFB. Cloning from another radio copies
        # these.)
        cal = self._memobj.calibration
        adv = RadioSettingGroup("calibration", "Calibration (per-radio)")
        adv.append(RadioSetting("xtal671", "XTAL (Crystal) calibration",
                   RadioSettingValueInteger(-128, 127, int(cal.xtal671))))
        adv.append(
            RadioSetting(
                "maxPowerWattsUHF",
                "Max Power Watts UHF (0.1W)",
                RadioSettingValueInteger(
                    0, 255, int(cal.maxPowerWattsUHF))))
        adv.append(
            RadioSetting(
                "maxPowerSettingUHF",
                "Max Power Setting UHF",
                RadioSettingValueInteger(
                    0, 255, int(cal.maxPowerSettingUHF))))
        adv.append(
            RadioSetting(
                "maxPowerWattsVHF",
                "Max Power Watts VHF (0.1W)",
                RadioSettingValueInteger(
                    0, 255, int(cal.maxPowerWattsVHF))))
        adv.append(
            RadioSetting(
                "maxPowerSettingVHF",
                "Max Power Setting VHF",
                RadioSettingValueInteger(
                    0, 255, int(cal.maxPowerSettingVHF))))
        top.append(adv)

        return RadioSettings(top)

    def set_settings(self, ui):
        def apply_el(element):
            if isinstance(element, RadioSettingGroup):
                for child in element:
                    apply_el(child)
                return
            if not isinstance(element, RadioSetting):
                return
            name = element.get_name()
            val = element.value.get_value() if hasattr(
                element.value, "get_value") else element.value
            self._apply_one_setting(name, val)

        for el in ui:
            apply_el(el)

    def _apply_one_setting(self, name, val):
        """Apply a single (name, value) to memory struct.

        Used by set_settings and by apply_setting_to_settings.
        """
        s = self._memobj.settings
        if name == "squelch":
            s.squelch = int(val) & 0xFF
        elif name == "dualWatch":
            s.dualWatch = 1 if val else 0
        elif name == "activeVfo":
            if val in ACTIVEVFO_LIST:
                s.activeVfo = ACTIVEVFO_LIST.index(val)
            else:
                s.activeVfo = 0
        elif name == "step":
            idx = STEP_LIST.index(val) if val in STEP_LIST else 0
            s.step = STEP_VALUES[idx]
        elif name == "rxSplit":
            s.rxSplit = int(val) & 0xFFFF
        elif name == "txSplit":
            s.txSplit = int(val) & 0xFFFF
        elif name == "pttMode":
            s.pttMode = int(val) & 0xFF
        elif name == "txModMeter":
            s.txModMeter = 1 if val else 0
        elif name == "micGain":
            s.micGain = int(val) & 0xFF
        elif name == "txDeviation":
            s.txDeviation = int(val) & 0xFF
        elif name == "battStyle":
            if val in BATTSTYLE_LIST:
                s.battStyle = BATTSTYLE_LIST.index(val)
            else:
                s.battStyle = 0
        elif name == "scanRange":
            s.scanRange = int(val) & 0xFFFF
        elif name == "scanPersist":
            s.scanPersist = int(val) & 0xFFFF
        elif name == "scanResume":
            s.scanResume = int(val) & 0xFF
        elif name == "ultraScan":
            s.ultraScan = int(val) & 0xFF
        elif name == "scanUpdate":
            s.scanUpdate = int(val) & 0xFF
        elif name == "toneMonitor":
            if val in TONEMONITOR_LIST:
                s.toneMonitor = TONEMONITOR_LIST.index(val)
            else:
                s.toneMonitor = 0
        elif name == "lcdBrightness":
            s.lcdBrightness = int(val) & 0xFF
        elif name == "lcdTimeout":
            s.lcdTimeout = int(val) & 0xFF
        elif name == "breathe":
            s.breathe = int(val) & 0xFF
        elif name == "dimmer":
            s.dimmer = int(val) & 0xFF
        elif name == "lcdInverted":
            s.lcdInverted = 1 if val else 0
        elif name == "repeaterTone":
            s.repeaterTone = int(val) & 0xFFFF
        elif name == "dtmfDev":
            s.dtmfDev = int(val) & 0xFF
        elif name == "gamma":
            s.gamma = int(val) & 0xFF
        elif name == "sBarStyle":
            s.sBarStyle = int(val) & 0xFF
        elif name == "sqNoiseLev":
            s.sqNoiseLev = int(val) & 0xFF
        elif name == "sBarAlwaysOn":
            s.sBarAlwaysOn = 1 if val else 0
        elif name == "afFilters":
            if val in AF_FILTERS_LIST:
                s.afFilters = min(AF_FILTERS_LIST.index(val), 255)
            else:
                s.afFilters = 0
        elif name == "ifFreq":
            s.ifFreq = int(val) & 0xFF
        elif name == "vfoState_group0":
            s.vfoState_group0 = int(val) & 0x0F
        elif name == "vfoState_lastGroup0":
            s.vfoState_lastGroup0 = int(val) & 0x0F
        elif name == "vfoState_mode0":
            if val in OP_MODE_LIST:
                s.vfoState_mode0 = OP_MODE_LIST.index(val)
            else:
                s.vfoState_mode0 = 0
        elif name and name.startswith("vfoState_groupModeChannels0_"):
            try:
                i = int(name.split("_")[-1])
                if 0 <= i < 16:
                    s.vfoState_groupModeChannels0[i] = min(
                        max(int(val), 0), 197)
            except (ValueError, IndexError):
                pass
        elif name == "vfoState_group1":
            s.vfoState_group1 = int(val) & 0x0F
        elif name == "vfoState_lastGroup1":
            s.vfoState_lastGroup1 = int(val) & 0x0F
        elif name == "vfoState_mode1":
            if val in OP_MODE_LIST:
                s.vfoState_mode1 = OP_MODE_LIST.index(val)
            else:
                s.vfoState_mode1 = 0
        elif name and name.startswith("vfoState_groupModeChannels1_"):
            try:
                i = int(name.split("_")[-1])
                if 0 <= i < 16:
                    s.vfoState_groupModeChannels1[i] = min(
                        max(int(val), 0),
                        197,
                    )
            except (ValueError, IndexError):
                pass
        elif name == "keyLock":
            s.keyLock = 1 if val else 0
        elif name == "bluetooth":
            s.bluetooth = 1 if val else 0
        elif name == "powerSave":
            s.powerSave = 1 if val else 0
        elif name == "keyTones":
            s.keyTones = 1 if val else 0
        elif name == "ste":
            s.ste = int(val) & 0xFF
        elif name == "rfGain":
            s.rfGain = RFGAIN_LIST.index(val) if val in RFGAIN_LIST else 0
        elif name == "lastFmtFreq":
            s.lastFmtFreq = int(val) & 0xFFFFFFFF
        elif name == "vox":
            s.vox = VOX_LIST.index(val) if val in VOX_LIST else 0
        elif name == "voxTail":
            s.voxTail = int(val) & 0xFFFF
        elif name == "txTimeout":
            s.txTimeout = int(val) & 0xFF
        elif name == "dtmfSpeed":
            s.dtmfSpeed = int(val) & 0xFF
        elif name == "noiseGate":
            s.noiseGate = int(val) & 0xFF
        elif name == "asl":
            s.asl = int(val) & 0xFF
        elif name == "disableFmt":
            s.disableFmt = 1 if val else 0
        elif name == "dualWatchDelay":
            s.dualWatchDelay = int(val) & 0xFF
        elif name == "subToneDeviation":
            s.subToneDeviation = int(val) & 0xFF
        elif name == "pin":
            s.pin = int(val) & 0xFFFF
        elif name == "pinAction":
            s.pinAction = int(val) & 0xFF
        elif name == "lockedVfo":
            s.lockedVfo = int(val) & 0xFF
        elif name == "vfoLockActive":
            s.vfoLockActive = 1 if val else 0
        elif name == "amAgcFix":
            s.amAgcFix = 1 if val else 0
        elif name and name.startswith("bandPlan_") and "_" in name[9:]:
            parts = name.split("_")
            if len(parts) >= 3:
                try:
                    idx = int(parts[1])
                    field = "_".join(parts[2:])
                    if 0 <= idx < 20:
                        bp = self._memobj.bandPlans[idx]
                        if field == "startFreq":
                            bp.startFreq = int(round(float(val) * 100000))
                        elif field == "endFreq":
                            bp.endFreq = int(round(float(val) * 100000))
                        elif field == "maxPower":
                            if val in MAXPOWER_BP_LIST:
                                bp.maxPower = MAXPOWER_BP_LIST.index(val)
                            else:
                                bp.maxPower = 0
                        elif field == "txAllowed":
                            bp.txAllowed = 1 if val else 0
                        elif field == "wrap":
                            bp.wrap = 1 if val else 0
                        elif field == "modulation":
                            if val in MODULATION_BP_LIST:
                                bp.modulation = MODULATION_BP_LIST.index(val)
                            else:
                                bp.modulation = 0
                        elif field == "bandwidth":
                            if val in BANDWIDTH_BP_LIST:
                                bp.bandwidth = BANDWIDTH_BP_LIST.index(val)
                            else:
                                bp.bandwidth = 0
                except (ValueError, IndexError, TypeError):
                    pass
        elif name and name.startswith("scanPreset_") and "_" in name[11:]:
            parts = name.split("_")
            if len(parts) >= 3:
                try:
                    idx = int(parts[1])
                    field = "_".join(parts[2:])
                    if 0 <= idx < 20:
                        sp = self._memobj.scanPresets[idx]
                        if field == "startFreq":
                            sp.startFreq = int(round(float(val) * 100000))
                        elif field == "endFreq":
                            start_hz = int(sp.startFreq) * 10
                            end_hz = int(round(float(val) * 1e6))
                            range_raw = max(0, (end_hz - start_hz) // 10000)
                            sp.range = min(range_raw, 65535)
                        elif field == "step":
                            sp.step = int(round(float(val) * 100)) & 0xFFFF
                        elif field == "resume":
                            sp.resume = int(val) & 0xFF
                        elif field == "persist":
                            sp.persist = int(val) & 0xFF
                        elif field == "modulation":
                            if val in MODULATION_SP_LIST:
                                sp.modulation = MODULATION_SP_LIST.index(val)
                            else:
                                sp.modulation = 0
                        elif field == "ultrascan":
                            sp.ultrascan = int(val) & 0x07
                        elif field == "label":
                            label_str = (str(val) or "")[:8].ljust(8)
                            for j, c in enumerate(label_str):
                                sp.label[j] = ord(c) if ord(c) < 256 else 0x20
                            sp.label[8] = 0
                except (ValueError, IndexError, TypeError):
                    pass
        elif name and name.startswith("groupLabel_"):
            try:
                idx = int(name.split("_")[1])
                if 0 <= idx < 15:
                    label_str = (str(val) or "")[:6].ljust(6)
                    gl = self._memobj.groupLabels[idx]
                    for j, c in enumerate(label_str):
                        gl.label[j] = ord(c) if ord(c) < 256 else 0x20
            except (ValueError, IndexError):
                pass
        else:
            cal = self._memobj.calibration
            if name == "xtal671":
                v = int(val)
                cal.xtal671 = max(-128, min(127, v))
            elif name == "maxPowerWattsUHF":
                cal.maxPowerWattsUHF = int(val) & 0xFF
            elif name == "maxPowerSettingUHF":
                cal.maxPowerSettingUHF = int(val) & 0xFF
            elif name == "maxPowerWattsVHF":
                cal.maxPowerWattsVHF = int(val) & 0xFF
            elif name == "maxPowerSettingVHF":
                cal.maxPowerSettingVHF = int(val) & 0xFF

    def apply_setting(self, name, val):
        """Apply a single (name, value) to the memory struct.

        Used when tree->struct does not persist (e.g. Android).
        """
        self._apply_one_setting(name, val)

    def apply_setting_to_settings(self, name, val):
        """Legacy alias for apply_setting.

        Prefer `apply_setting` for new code.
        """
        self.apply_setting(name, val)
