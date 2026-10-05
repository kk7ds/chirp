# Copyright 2026 CHIRP contributors
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

"""Yaesu FTM-150E experimental CHIRP driver.

Memory map from ADMS-17 CLNFTM150nn.dat dumps (98304 bytes, ident AH086).

Downloading from and uploading to the radio over a cable both work.
Also, only the full backup (CLNFTM150nn.dat) is supported -
setup (SYSFTM150nn.dat) and memory (MEMFTM150nn.dat) files are not supported.
Not every feature of FTM-150/ADMS-17 is currently supported by this driver.
"""

import logging

from chirp.drivers import ftm300d
from chirp.drivers import yaesu_clone
from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp.settings import RadioSetting
from chirp.settings import RadioSettingGroup
from chirp.settings import RadioSettings
from chirp.settings import RadioSettingValueBoolean
from chirp.settings import RadioSettingValueList
from chirp.settings import RadioSettingValueString

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Clone protocol, 38400 8N1 on the DATA jack. Captured from a real
# [58 This -> Other] transfer: the FTM-150 speaks exactly what ftm300d.py
# already implements for the FTM-300DR, down to the skipped blocks, the
# wrap to the name tables and the two trailer frames, so the clone code is
# reused from there. The image has the layout of the radio's own SD backup
# (CLNFTM150nn.dat). The radio never transmits block 0x0400, so it stays
# zero in a cable-read image; it is zero in every SD backup seen so far,
# too, and no known setting lives there.
# ---------------------------------------------------------------------------

# The .dat format keeps a checksum over everything before this offset, but
# the radio transmits 0x00 there -- the clone stream carries its own
# per-frame checksum instead. ADMS-17 fills the byte in when it writes a
# file from a cable read and sends 0x00 again when it uploads, so do the
# same: without it, saving a downloaded image yields a .dat whose checksum
# does not match its contents. Nothing this driver exposes for editing
# lives below the offset, so computing it once after the download is
# enough.
FILE_CHECKSUM_AT = 0x007F


# ---------------------------------------------------------------------------
# Frequency encoding, the same as on the FTM-300D: the 100 MHz digit and
# the BCD digits down to 10 kHz, plus a 4-bit count of 625 Hz steps on
# top. ftm300d.py and ftm350.py treat the latter as single 5k/2.5k/1.25k
# (/625) flags, but together they are just binary 8/4/2/1 x 625 Hz.
# ---------------------------------------------------------------------------

YFREQ_FORMAT = """
struct yfreq {
  u8 fine:4,
     hun:4;
  bbcd khz10[2];
};
"""


def decode_freq(freq):
    """Decode a yfreq struct to Hz."""
    return ((int(freq.hun) * 10000 + int(freq.khz10)) * 10000
            + int(freq.fine) * 625)


def encode_freq(freq, hz):
    """Encode Hz into a yfreq struct."""
    khz10, rest = divmod(hz, 10000)
    freq.hun = khz10 // 10000 % 10
    freq.khz10 = khz10 % 10000
    freq.fine = rest // 625


# ---------------------------------------------------------------------------
# Memory map.
#
# `chanrecord` is the 16-byte per-channel layout shared, byte-for-byte, by
# regular memory channels, PMS entries, and VFO/HOME band records.
#
# `namerecord` is the 16-byte, 0xFF-padded ASCII name shared by all of
# those tables too.
#
# The FTM-300D shares this layout, but some of its fields do not apply to
# the analog-only FTM-150 and are named unknown here on purpose:
# - unknown3 (byte 1, 0x40) is ftm300d's "ams". The FTM-150 has no AMS,
#   yet the radio sets the bit on some records (also at 0x0091 and
#   0x00E2), while ADMS-17 clears it everywhere when writing a .dat.
#   Meaning unknown; the driver never touches it.
# - unknown5 (byte 11, 0x40) is ftm300d's "dn", unknown8 and unknown9
#   (bytes 14 and 15) are its "dgid_rx" and "dgid_tx". All C4FM; never
#   seen set on an FTM-150.
# ---------------------------------------------------------------------------

MEM_FORMAT = YFREQ_FORMAT + """
struct chanrecord {
  u8 used:1,
     unknown0:1,
     skip:1,
     memref:1,
     unknown1:2,
     band:2;
  u8 unused_msb:1,
     unknown3:1,
     narrow:1,
     am:1,
     duplex:4;
  struct yfreq freq;
  u8 tone_mode:4,
     tune_step:4;
  struct yfreq tx_freq;
  u8 power:2,
     tone:6;
  u8 clock_shift:1,
     dcs:7;
  u8 unknown4:1,
     unknown5:1,
     unknown6:1,
     pr_freq:5;
  u8 unknown7;
  u8 offset;
  u8 unknown8;
  u8 unknown9;
};

struct namerecord {
  u8 text[16];
};

struct dtmfrecord {
  u8 digits[16];
};

// 0x0000
u8 ident[6];

#seekto 0x00A1;
u8 unit;

#seekto 0x00A8;
u8 tz_west:1,
   tz_mag:7;

#seekto 0x00CF;
u8 pmg_selected;

#seekto 0x00DF;
u8 vfo_a_active;

#seekto 0x00FB;
u8 pmg_active;

#seekto 0x0100;
struct chanrecord vfo_a[4];

#seekto 0x0150;
struct chanrecord vfo_b[4];

#seekto 0x01A0;
struct chanrecord home_a[4];

#seekto 0x01F0;
struct chanrecord home_b[4];

#seekto 0x028F;
u8 lcd_brightness;

#seekto 0x02C8;
u8 callsign[10];

// 0x02D2
u8 pager_rx[2];
u8 pager_tx[2];

#seekto 0x0300;
struct dtmfrecord dtmf[9];

#seekto 0x03B0;
struct namerecord home_b_names[4];

#seekto 0x0480;
struct namerecord home_a_names[4];

#seekto 0x0800;
struct chanrecord memory[999];

// 0x4670
struct chanrecord pms[100];

// 0x4CB0
u16 nameflags[999];

#seekto 0x5600;
struct chanrecord pmg[5];

#seekto 0x6800;
struct namerecord wx_names[10];

// 0x68A0
u16 wx_nameflags[10];

#seekto 0x10000;
struct namerecord names[999];

// 0x13E70
struct namerecord pms_names[100];
"""

# This is the real radio-generated (not ADMS-17-resaved) empty slot backup.
# ADMS-17 itself writes a *different* pattern for empty channels on resave.
EMPTY_SLOT = bytes.fromhex(
    "01 00 01 44 00 04 00 00 00 0c 00 0f 00 0c 00 00")
USED_PROTOTYPE = bytes.fromhex(
    "81 00 01 46 50 00 00 00 00 0c 00 0f 00 0c 00 00")

POWER_LEVELS = [
    chirp_common.PowerLevel("Hi", watts=50),
    chirp_common.PowerLevel("Mid", watts=25),
    chirp_common.PowerLevel("Low", watts=5),
]

STEPS = ftm300d.STEPS

# Duplex nibble: 0 simplex, 2 minus, 3 plus, 4 split.
DUPLEX_FROM_RADIO = ftm300d.DUPLEX_FROM_RADIO
DUPLEX_TO_RADIO = ftm300d.DUPLEX_TO_RADIO

# High nibble of byte 5, in ADMS-17 terms: 0 OFF, 1 TONE, 2 TONE SQL,
# 3 REV TONE, 4 DCS, 5 PR FREQ, 6 PAGER. CHIRP has no tmode for PR FREQ
# (reverse tone on the User CTCSS frequency, see pr_freq) or PAGER (EPCS
# selective call), so like ft4.py they go into the "sql_override" channel
# extra and the grid shows tmode "" for them. The override wins over tmode
# on write.
TMODE_FROM_RADIO = ftm300d.TMODE_FROM_RADIO
TMODE_TO_RADIO = ftm300d.TMODE_TO_RADIO
EDITABLE_TMODES = ["", "Tone", "TSQL", "TSQL-R", "DTCS"]
SQL_OVERRIDE_NONE = "(None)"
SQL_OVERRIDE_FROM_RADIO = {5: "PR FREQ", 6: "PAGER"}
SQL_OVERRIDE_TO_RADIO = {v: k for k, v in SQL_OVERRIDE_FROM_RADIO.items()}
SQL_OVERRIDES = [SQL_OVERRIDE_NONE] + list(SQL_OVERRIDE_FROM_RADIO.values())

# ADMS-17 "User CTCSS", 300-3000 Hz in 100 Hz steps, stored as Hz / 100 in
# the low 5 bits of byte 11 (confirmed by controlled diff: 300 -> 3,
# 1100 -> 11, 3000 -> 30). Every channel has it, whatever its tone mode;
# the factory value is 1500 Hz. Bit 5 has never been seen set.
PR_FREQS = ["%d Hz" % hz for hz in range(300, 3001, 100)]
PR_FREQ_MIN = 3

# ADMS-17 Signaling -> Pager Code: RX and TX each take two EPCS codes,
# 1-50, stored as code - 1 (confirmed by controlled diff; factory 05/47).
PAGER_CODES = ["%02d" % code for code in range(1, 51)]

# DTMF digit encoding confirmed by controlled diff.
DTMF_CHARSET = "0123456789*#"
DTMF_CHAR_TO_CODE = {str(d): d for d in range(10)}
DTMF_CHAR_TO_CODE.update({"*": 0x0E, "#": 0x0F})
DTMF_CODE_TO_CHAR = {v: k for k, v in DTMF_CHAR_TO_CODE.items()}
DTMF_PAD = 0xFF

# WX is the ten-channel NOAA weather broadcast bank. Only the user-assignable
# name and its flag are stored in the backup (0x6800 / 0x68A0); the
# frequencies themselves live in firmware, which is why they are hardcoded
# here just to label the name fields.
#
# UNTESTED on real hardware: the name storage is confirmed by controlled
# diff, but only against a European FTM-150E, where the WX bank cannot
# normally be reached -- the [P4] key ships assigned to T-CALL there, while
# the USA FTM-150R ships with WX on P4. Nobody has yet checked that a name
# written here shows up on a radio that can actually display the bank.
WX_FREQS = ("162.550", "162.400", "162.475", "162.425", "162.450",
            "162.500", "162.525", "161.650", "161.775", "163.275")


def _decode_name(raw):
    return ftm300d._decode_padded(raw, 0xFF)


def _encode_name(text, length=16):
    cleaned = "".join(
        c if c in chirp_common.CHARSET_ASCII else " " for c in text
    )[:length]
    padded = cleaned.encode("ascii", "replace")
    return padded + b"\xff" * (length - len(padded))


def _decode_dtmf(raw):
    buf = [int(x) for x in raw]
    chars = []
    for b in buf:
        if b == DTMF_PAD:
            break
        chars.append(DTMF_CODE_TO_CHAR.get(b, "?"))
    return "".join(chars)


def _encode_dtmf(text, length=16):
    codes = [DTMF_CHAR_TO_CODE[c] for c in text if c in DTMF_CHAR_TO_CODE]
    codes = codes[:length]
    return bytes(codes) + bytes([DTMF_PAD]) * (length - len(codes))


# ---------------------------------------------------------------------------
# Special channels: VFO A/B (4 bands each), HOME CH A/B (4 bands each, with
# names), and PMS (50 L/U pairs). All share the exact same 16-byte
# chanrecord layout as regular memory channels
# ---------------------------------------------------------------------------

# Order of the four records inside vfo_a/vfo_b/home_a/home_b, ascending by
# frequency. Byte 0 of each record carries its own index, which is how this
# order was confirmed; "OTHER" covers everything between 2 m and 70 cm.
SPECIAL_BANDS = ("AIR", "144", "OTHER", "430")


def _band_index(hz):
    """Index into SPECIAL_BANDS that the radio stores for a frequency.

    Edges confirmed by controlled diff on memory channels and VFO/HOME
    records set on the radio: 136.9875 is AIR, 137.9875 and 174.0 are
    144, 174.1 and 399.9875 are OTHER, 400.0 and 480.0 are 430. The radio
    does not accept exactly 137.0. (ADMS-17 disagrees on 174.0 for
    VFO/HOME and puts it in OTHER.)
    """
    if hz < 137000000:
        return 0
    if hz <= 174000000:
        return 1
    if hz < 400000000:
        return 2
    return 3


def _build_special_memories():
    mapping = {}
    idx = -1
    for prefix in ("VFO_A", "VFO_B", "Home_A", "Home_B"):
        for band in SPECIAL_BANDS:
            mapping["%s_%s" % (prefix, band)] = idx
            idx -= 1
    for n in range(1, 51):
        mapping["PMS_L_%02d" % n] = idx
        idx -= 1
        mapping["PMS_U_%02d" % n] = idx
        idx -= 1
    return mapping


# ---------------------------------------------------------------------------
# PMG (Primary Memory Group): five chanrecords at 0x5600, packed from slot 1
# without gaps -- the radio moves the later slots up when one is deleted.
# A slot either holds a frequency of its own, as a full record like a VFO,
# or, with memref set, points at a memory channel: then byte 1 is 0xFF,
# bytes 2-3 are the channel number - 1, big endian, and the band in byte 0
# is that of the channel. Deleting a slot clears only byte 0. pmg_selected
# is the slot selected on the radio, 0-based. All confirmed by controlled
# diff.
# ---------------------------------------------------------------------------

PMG_EMPTY = "(Empty)"


def _pmg_channel(raw):
    """Memory channel number a raw PMG slot points at, or None."""
    if not raw[0] & 0x80 or not raw[0] & 0x10:
        return None
    return (raw[2] << 8 | raw[3]) + 1


def _pmg_ref(number, band):
    """Raw PMG slot pointing at memory channel number."""
    return bytes([0x90 | band, 0xFF, (number - 1) >> 8,
                  (number - 1) & 0xFF]) + b"\xff" * 12


SPECIAL_MEMORIES = _build_special_memories()
SPECIAL_MEMORIES_REV = {v: k for k, v in SPECIAL_MEMORIES.items()}


def _special_memory_sort_key(name):
    if name.startswith(("VFO_", "Home_")):
        family, side, band = name.split("_")
        family_order = 0 if family == "VFO" else 1
        side_order = 0 if side == "A" else 1
        return family_order, side_order, SPECIAL_BANDS.index(band), 0

    band, number = name[4:].split("_")
    side_order = 0 if band == "L" else 1
    return 2, int(number), side_order, 0


@directory.register
class FTM150Radio(yaesu_clone.YaesuCloneModeRadio,
                  chirp_common.ExperimentalRadio):
    """Yaesu FTM-150E.

    Only the European FTM-150E has been tested. The USA FTM-150R probably
    uses the same image, but that is unconfirmed, so it is not offered.
    """
    VENDOR = "Yaesu"
    MODEL = "FTM-150E"
    BAUD_RATE = 38400  # confirmed against the radio
    NEEDS_COMPAT_SERIAL = False
    FORMATS = [directory.register_format('Yaesu FTM-150E SD ALL', '*.dat')]

    _model = b"AH086"
    _memsize = 98304
    # IARU Region 1 limits of the FTM-150E. Many radios are frequency-
    # expanded (the test radio is), so validate_memory() only warns.
    _tx_bands = [
        (144000000, 146000000),
        (430000000, 440000000),
    ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This FTM-150E driver is experimental. Downloading from and\n"
            "uploading to the radio over a cable work, as does opening and\n"
            "saving the SD card 'ALL' backup file\n"
            "(FTM150/BACKUP/CLNFTM150nn.dat).\n"
            "\n"
            "Keep an SD card 'ALL' backup before uploading.")
        rp.pre_download = (
            "1. Connect the cable to the DATA jack on the back of the\n"
            "    radio.\n"
            "2. Press and hold the [F(SETUP)] key, turn the right DIAL\n"
            "    knob to select [58 This -> Other], then press the DIAL\n"
            "    knob.\n"
            "3. <b>After clicking OK here</b>, turn the DIAL knob on the\n"
            "    radio to select [OK] and press it to start the transfer.\n")
        rp.pre_upload = (
            "Keep an SD card 'ALL' backup first.\n"
            "\n"
            "1. Connect the cable to the DATA jack on the back of the\n"
            "    radio.\n"
            "2. Press and hold the [F(SETUP)] key, turn the right DIAL\n"
            "    knob to select [59 Other -> This], then press the DIAL\n"
            "    knob.\n"
            "3. Turn the DIAL knob to select [OK] and press it, so the\n"
            "    radio waits for data.\n"
            "4. Click OK here within 30 seconds.\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_bank_names = False
        rf.has_settings = True
        rf.has_ctone = False
        rf.has_dtcs = True
        rf.has_dtcs_polarity = False
        rf.has_cross = False
        rf.has_rx_dtcs = False
        rf.has_comment = False
        rf.has_nostep_tuning = False
        rf.can_odd_split = True
        rf.can_delete = True
        rf.memory_bounds = (1, 999)
        rf.valid_special_chans = sorted(
            SPECIAL_MEMORIES, key=_special_memory_sort_key)
        # No "DN" -- the FTM-150 is analog only.
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_tmodes = list(EDITABLE_TMODES)
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 16
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_dtcs_codes = list(chirp_common.DTCS_CODES)
        rf.valid_bands = [
            (108000000, 174000000),
            (174000000, 400000000),
            # The radio accepts 480.0 itself, but nothing above it.
            (400000000, 480000001),
        ]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, FILE_CHECKSUM_AT - 1)]

    def sync_in(self):
        try:
            self._mmap = ftm300d._clone_in(self)
            self.update_checksums()
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Failed to download from radio")
            raise errors.RadioError(
                "Failed to download from radio (%s)" % e)
        self.process_mmap()

    def sync_out(self):
        # Send 0x00 in place of the file checksum, like the radio and
        # ADMS-17 do, but leave the image itself intact.
        checksum = self._mmap[FILE_CHECKSUM_AT]
        self._mmap[FILE_CHECKSUM_AT] = b"\x00"
        try:
            ftm300d._clone_out(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Failed to upload to radio")
            raise errors.RadioError(
                "Failed to upload to radio (%s)" % e)
        finally:
            self._mmap[FILE_CHECKSUM_AT] = checksum

    # -- settings: the small Set Mode tables so far. VFO A/B, HOME CH A/B
    # and PMS are not here -- they are exposed as special channels in the
    # Memories grid instead, see the "special channels" section above.
    def get_settings(self):
        top = RadioSettings()

        top.append(self._get_status())

        config = RadioSettingGroup("config", "Config")
        top.append(config)
        unit = int(self._memobj.unit)
        config.append(RadioSetting(
            "unit", "Display Units",
            RadioSettingValueList(
                ftm300d.UNIT_LABELS, current_index=unit if unit in (0, 1)
                else 0)))
        brightness = int(self._memobj.lcd_brightness)
        config.append(RadioSetting(
            "lcd_brightness", "LCD Brightness (raw value)",
            RadioSettingValueString(0, 2, str(brightness))))

        dtmf = RadioSettingGroup("dtmf", "DTMF Memory")
        top.append(dtmf)
        for i in range(9):
            code = _decode_dtmf(self._memobj.dtmf[i].digits)
            dtmf.append(RadioSetting(
                "dtmf%d" % i, "Channel %d" % (i + 1),
                RadioSettingValueString(
                    0, 16, code, autopad=False, charset=DTMF_CHARSET)))

        signaling = RadioSettingGroup("signaling", "Signaling")
        top.append(signaling)
        for direction in ("rx", "tx"):
            codes = getattr(self._memobj, "pager_" + direction)
            for i in range(2):
                code = int(codes[i])
                if code >= len(PAGER_CODES):
                    # Out of range values are left alone rather than shown
                    # wrong.
                    continue
                rs = RadioSetting(
                    "pager_%s%d" % (direction, i),
                    "Pager %s Code %d" % (direction.upper(), i + 1),
                    RadioSettingValueList(PAGER_CODES, current_index=code))
                rs.set_doc(
                    "Used by channels whose Squelch override is PAGER.")
                signaling.append(rs)

        wx = RadioSettingGroup("wx", "WX Channel Names")
        top.append(wx)
        for i in range(10):
            rs = RadioSetting(
                "wx%d" % i, "WX-CH%02d (%s MHz)" % (i + 1, WX_FREQS[i]),
                RadioSettingValueString(
                    0, 16, _decode_name(self._memobj.wx_names[i].text),
                    autopad=False))
            rs.set_doc(
                "Name only -- the frequency is fixed in firmware. The WX "
                "bank is reachable only via a programmable key, assigned "
                "to [P4] on the USA FTM-150R but to T-CALL on the "
                "European FTM-150E.")
            wx.append(rs)

        top.append(self._get_pmg())

        return top

    # Operating state from block 0x0080, which the radio sends last and an
    # upload restores. Read only: switching it means changing several
    # bytes that depend on the active VFO. Confirmed by controlled diff:
    # 0x00FB is 0x0A with PMG on and 0x00 with it off, on either VFO, and
    # 0x00DF is 1 on VFO A (left on the display) and 0 on VFO B (right).
    # With PMG on, the radio also sets 0x80 in byte 3 of the active VFO's
    # block (0x00E0 A, 0x00F0 B), 0x01 in byte 4 of the other one, and
    # clears 0x00D0 (A) or 0x00C0 (B).
    def _get_status(self):
        status = RadioSettingGroup("status", "Current Status")
        pmg_active = int(self._memobj.pmg_active)
        if pmg_active in (0x00, 0x0A):
            rs = RadioSetting(
                "pmg_active", "PMG active",
                RadioSettingValueBoolean(pmg_active == 0x0A))
            rs.value.set_mutable(False)
            rs.set_doc("Uploading restores the state saved in this "
                       "image, whatever the radio was set to since.")
            status.append(rs)
        vfo_a = int(self._memobj.vfo_a_active)
        if vfo_a in (0, 1):
            rs = RadioSetting(
                "vfo_a_active", "Active VFO",
                RadioSettingValueList(
                    ["B (right)", "A (left)"], current_index=vfo_a))
            rs.value.set_mutable(False)
            rs.set_doc("Uploading restores the state saved in this "
                       "image, whatever the radio was set to since.")
            status.append(rs)
        return status

    def _channel_label(self, number):
        if int(self._memobj.memory[number - 1].used):
            name = _decode_name(self._memobj.names[number - 1].text)
        else:
            name = "(empty)"
        return ("%d %s" % (number, name)).strip()

    # PMG slots are settings, as the radio treats PMG as a list of five
    # entries. A slot holding a frequency of its own is a full channel
    # (offset, tone, power, ...) that a settings field cannot edit fully,
    # so it is shown and kept but cannot be created or changed here. The
    # intended way to add that is special channels PMG_1..PMG_5 in the
    # memory grid, like VFO and HOME, with these settings still showing
    # what each slot holds.
    def _get_pmg(self):
        pmg = RadioSettingGroup("pmg", "PMG")
        channels = [self._channel_label(i + 1)
                    for i, rec in enumerate(self._memobj.memory)
                    if int(rec.used)]
        for i, rec in enumerate(self._memobj.pmg):
            options = [PMG_EMPTY] + channels
            current = PMG_EMPTY
            number = _pmg_channel(rec.get_raw())
            if number is not None:
                current = self._channel_label(number)
                if current not in options:
                    # Points at a channel deleted since; kept as is.
                    options.append(current)
            elif int(rec.used):
                current = "Frequency %s MHz" % chirp_common.format_freq(
                    decode_freq(rec.freq))
                options.insert(1, current)
            rs = RadioSetting(
                "pmg%d" % i, "Slot %d" % (i + 1),
                RadioSettingValueList(
                    options, current_index=options.index(current)))
            rs.set_doc(
                "A memory channel, or a frequency stored in the slot "
                "itself. Frequencies can only be stored on the radio. "
                "Emptied slots are filled by the slots after them, as on "
                "the radio.")
            pmg.append(rs)
        selected = int(self._memobj.pmg_selected)
        slots = ["Slot %d" % (i + 1) for i in range(len(self._memobj.pmg))]
        rs = RadioSetting(
            "pmg_selected", "Selected slot",
            RadioSettingValueList(
                slots, current_index=selected if selected < len(slots)
                else 0))
        rs.set_doc("The slot whose name the radio shows. Follows its "
                   "entry when that moves up; falls back to slot 1 when "
                   "the selected slot is emptied.")
        pmg.append(rs)
        return pmg

    def _set_pmg(self, pmg):
        old = [rec.get_raw() for rec in self._memobj.pmg]
        slots = []
        moved_to = {}
        selected = 0
        for element in pmg:
            name = element.get_name()
            value = str(element.value)
            if name == "pmg_selected":
                selected = int(value.split()[1]) - 1
                continue
            if value == PMG_EMPTY:
                continue
            idx = int(name[len("pmg"):])
            moved_to[idx] = len(slots)
            raw = old[idx]
            if value.startswith("Frequency "):
                slots.append(raw)
                continue
            number = int(value.split()[0])
            if _pmg_channel(raw) != number:
                raw = _pmg_ref(
                    number, int(self._memobj.memory[number - 1].band))
            slots.append(raw)
        for i, rec in enumerate(self._memobj.pmg):
            if i < len(slots):
                rec.set_raw(slots[i])
            elif old[i][0] & 0x80:
                rec.set_raw(b"\x00" + old[i][1:])
        # The selection follows its slot when that moves up.
        self._memobj.pmg_selected = moved_to.get(selected, 0)

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() == "pmg":
                    self._set_pmg(element)
                else:
                    self.set_settings(element)
                continue
            name = element.get_name()
            value = str(element.value)
            if name == "unit":
                self._memobj.unit = ftm300d.UNIT_LABELS.index(value)
            elif name == "lcd_brightness":
                try:
                    self._memobj.lcd_brightness = int(value)
                except ValueError:
                    pass
            elif name.startswith("dtmf"):
                idx = int(name[len("dtmf"):])
                ftm300d._set_bytes(self._memobj.dtmf[idx].digits,
                                   _encode_dtmf(value))
            elif name.startswith(("pager_rx", "pager_tx")):
                codes = getattr(self._memobj, name[:-1])
                codes[int(name[-1])] = PAGER_CODES.index(value)
            elif name.startswith("wx"):
                idx = int(name[len("wx"):])
                text = value.strip()
                ftm300d._set_bytes(self._memobj.wx_names[idx].text,
                                   _encode_name(text))
                self._memobj.wx_nameflags[idx] = 0x0000 if text else 0xFFFF

    # -- memory channels (1-999): logic ported from ftm300d.py
    def get_raw_memory(self, number):
        if isinstance(number, str):
            arr, _names_arr, idx, _kind = self._special_target(number)
            return repr(getattr(self._memobj, arr)[idx])
        if number < 0:
            return self.get_raw_memory(SPECIAL_MEMORIES_REV[number])
        return repr(self._memobj.memory[number - 1])

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if mem.empty:
            return msgs
        if mem.number in SPECIAL_MEMORIES_REV:
            name = SPECIAL_MEMORIES_REV[mem.number]
            _arr, _names_arr, idx, kind = self._special_target(name)
            if kind != "pms" and _band_index(mem.freq) != idx:
                msgs.append(chirp_common.ValidationError(
                    "%s only holds %s band frequencies" % (
                        name, SPECIAL_BANDS[idx])))
        if mem.duplex == "split":
            tx = mem.offset
        elif mem.duplex == "-":
            tx = mem.freq - mem.offset
        elif mem.duplex == "+":
            tx = mem.freq + mem.offset
        else:
            tx = mem.freq
        in_tx = any(lo <= tx < hi for lo, hi in self._tx_bands)
        if not in_tx:
            if mem.duplex in ("-", "+", "split"):
                # Only a warning: an expanded radio transmits here, and a
                # stock one refuses to on its own.
                msgs.append(chirp_common.ValidationWarning(
                    "TX frequency is outside amateur allocations "
                    "for this model"))
            else:
                msgs.append(chirp_common.ValidationWarning(
                    "RX-only frequency; radio will not transmit here"))
        return msgs

    # Shared record decode/encode, used by both regular channels and
    # every special channel (VFO/HOME/PMS) below, since they're all the
    # same 16-byte chanrecord layout
    def _decode_chanrecord(self, mem, _mem):
        mem.freq = decode_freq(_mem.freq)
        mem.duplex = DUPLEX_FROM_RADIO.get(int(_mem.duplex), "")
        if mem.duplex == "split":
            mem.offset = decode_freq(_mem.tx_freq)
        else:
            mem.offset = int(_mem.offset) * 50000
        mem.skip = "S" if int(_mem.skip) else ""
        try:
            mem.power = POWER_LEVELS[int(_mem.power)]
        except IndexError:
            mem.power = POWER_LEVELS[0]
        try:
            mem.tuning_step = STEPS[int(_mem.tune_step)]
        except IndexError:
            mem.tuning_step = STEPS[0]
        tone_mode = int(_mem.tone_mode)
        mem.tmode = TMODE_FROM_RADIO.get(tone_mode, "")
        mem.extra = RadioSettingGroup("extra", "Extra")
        rs = RadioSetting(
            "sql_override", "Squelch override",
            RadioSettingValueList(
                SQL_OVERRIDES,
                SQL_OVERRIDE_FROM_RADIO.get(tone_mode, SQL_OVERRIDE_NONE)))
        rs.set_doc(
            "PR FREQ and PAGER have no CHIRP tone mode. When one is "
            "selected here, the channel uses it on the radio regardless "
            "of Tone Mode. PR FREQ uses the User CTCSS frequency, PAGER "
            "the pager codes under Settings -> Signaling.")
        mem.extra.append(rs)
        pr_freq = int(_mem.pr_freq) - PR_FREQ_MIN
        if 0 <= pr_freq < len(PR_FREQS):
            # Out of range values are left alone rather than shown wrong.
            rs = RadioSetting(
                "pr_freq", "User CTCSS",
                RadioSettingValueList(PR_FREQS, current_index=pr_freq))
            rs.set_doc(
                "Select the idle line frequency to remove signals such "
                "as idle line signals used by private railways and "
                "control signals of MCA radio systems. Only used when "
                "Squelch override is PR FREQ.")
            mem.extra.append(rs)
        rs = RadioSetting(
            "clock_shift", "Clock Shift",
            RadioSettingValueBoolean(bool(int(_mem.clock_shift))))
        rs.set_doc(
            "Shift the CPU clock frequency on this channel, to move an "
            "internal spurious signal (\"birdie\") away from it.")
        mem.extra.append(rs)
        try:
            mem.rtone = chirp_common.TONES[int(_mem.tone)]
        except IndexError:
            mem.rtone = 88.5
        mem.ctone = mem.rtone
        try:
            mem.dtcs = chirp_common.DTCS_CODES[int(_mem.dcs)]
        except IndexError:
            mem.dtcs = 23

        if int(_mem.am):
            mem.mode = "AM"
        elif int(_mem.narrow):
            mem.mode = "NFM"
        else:
            mem.mode = "FM"

    def _encode_chanrecord(self, _mem, mem):
        _mem.used = 1
        _mem.band = _band_index(mem.freq)
        _mem.skip = 1 if mem.skip == "S" else 0
        encode_freq(_mem.freq, mem.freq)
        _mem.duplex = DUPLEX_TO_RADIO.get(mem.duplex, 0)
        if mem.duplex == "split":
            encode_freq(_mem.tx_freq, int(mem.offset))
            _mem.offset = 0
        else:
            encode_freq(_mem.tx_freq, 0)
            _mem.offset = (
                int(round(mem.offset / 50000.0)) if mem.offset else 0)

        _mem.am = 1 if mem.mode == "AM" else 0
        _mem.narrow = 1 if mem.mode == "NFM" else 0

        try:
            _mem.tune_step = STEPS.index(mem.tuning_step)
        except ValueError:
            _mem.tune_step = 0
        _mem.tone_mode = TMODE_TO_RADIO.get(mem.tmode, 0)
        for setting in mem.extra:
            if setting.get_name() == "sql_override":
                override = str(setting.value)
                if override in SQL_OVERRIDE_TO_RADIO:
                    _mem.tone_mode = SQL_OVERRIDE_TO_RADIO[override]
            elif setting.get_name() == "pr_freq":
                _mem.pr_freq = (
                    PR_FREQS.index(str(setting.value)) + PR_FREQ_MIN)
            elif setting.get_name() == "clock_shift":
                _mem.clock_shift = 1 if setting.value else 0
        try:
            _mem.tone = chirp_common.TONES.index(mem.rtone)
        except ValueError:
            _mem.tone = chirp_common.TONES.index(88.5)
        try:
            _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        except ValueError:
            _mem.dcs = 0
        if mem.power in POWER_LEVELS:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

    # dispatch the regular numbered channels (1-999) vs. the special
    # channels (string name, or the negative int CHIRP stores internally)
    def get_memory(self, number):
        if isinstance(number, str):
            return self._get_special(number)
        if number < 0:
            return self._get_special(SPECIAL_MEMORIES_REV[number])
        return self._get_normal(number)

    def set_memory(self, mem):
        if mem.number < 0:
            return self._set_special(mem)
        return self._set_normal(mem)

    def _get_normal(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._memobj.memory[number - 1]
        if not int(_mem.used):
            mem.empty = True
            return mem

        mem.empty = False
        self._decode_chanrecord(mem, _mem)
        mem.name = _decode_name(self._memobj.names[number - 1].text)
        return mem

    def _set_normal(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        name_idx = mem.number - 1
        if mem.empty:
            _mem.set_raw(EMPTY_SLOT)
            ftm300d._set_bytes(self._memobj.names[name_idx].text, b"\xff" * 16)
            self._memobj.nameflags[name_idx] = 0xFFFF
            return

        if not int(_mem.used):
            _mem.set_raw(USED_PROTOTYPE)

        self._encode_chanrecord(_mem, mem)

        encoded = _encode_name(mem.name)
        ftm300d._set_bytes(self._memobj.names[name_idx].text, encoded)
        self._memobj.nameflags[name_idx] = (
            0x0000 if mem.name.strip() else 0xFFFF)

    def _special_target(self, name):
        """Return (chanrecord array attr, names array attr or None, index,
        kind) for a special channel name. kind is 'vfo', 'home' or 'pms'."""
        for prefix, arr, names_arr, kind in (
                ("VFO_A", "vfo_a", None, "vfo"),
                ("VFO_B", "vfo_b", None, "vfo"),
                ("Home_A", "home_a", "home_a_names", "home"),
                ("Home_B", "home_b", "home_b_names", "home")):
            if name.startswith(prefix + "_"):
                band = name[len(prefix) + 1:]
                return arr, names_arr, SPECIAL_BANDS.index(band), kind
        if name.startswith(("PMS_L_", "PMS_U_")):
            prefix, number = name.rsplit("_", 1)
            n = int(number) if number.isdigit() else 0
            if 1 <= n <= 50:
                slot = (n - 1) * 2 + (0 if prefix == "PMS_L" else 1)
                return "pms", "pms_names", slot, "pms"
        raise errors.InvalidMemoryLocation(
            "Unknown FTM-150 special channel %r" % name)

    def _get_special(self, name):
        arr, names_arr, idx, kind = self._special_target(name)
        _mem = getattr(self._memobj, arr)[idx]
        _name_obj = (getattr(self._memobj, names_arr)[idx]
                     if names_arr else None)

        mem = chirp_common.Memory()
        mem.number = SPECIAL_MEMORIES[name]
        mem.extd_number = name

        if kind == "pms" and not int(_mem.used):
            mem.empty = True
            mem.immutable = ["number", "extd_number"]
            return mem

        mem.empty = False
        self._decode_chanrecord(mem, _mem)
        if _name_obj is not None:
            mem.name = _decode_name(_name_obj.text)

        immutable = ["number", "extd_number"]
        if _name_obj is None:
            # VFO A/B have no name storage at all.
            immutable.append("name")
        mem.immutable = immutable
        return mem

    def _set_special(self, mem):
        name = SPECIAL_MEMORIES_REV[mem.number]
        arr, names_arr, idx, kind = self._special_target(name)
        _mem = getattr(self._memobj, arr)[idx]
        _name_obj = (getattr(self._memobj, names_arr)[idx]
                     if names_arr else None)

        if mem.empty:
            if kind != "pms":
                raise errors.RadioError(
                    "%s cannot be deleted -- VFO/HOME bands always exist "
                    "on the radio; only PMS entries can be cleared" % name)
            _mem.set_raw(EMPTY_SLOT)
            if _name_obj is not None:
                ftm300d._set_bytes(_name_obj.text, b"\xff" * 16)
            return

        if kind == "pms" and not int(_mem.used):
            _mem.set_raw(USED_PROTOTYPE)

        self._encode_chanrecord(_mem, mem)
        if _name_obj is not None:
            ftm300d._set_bytes(_name_obj.text, _encode_name(mem.name))
