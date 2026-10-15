# Quansheng UV-K5 / UV-K6 driver for Chinese third-party firmware
# (LOSEHU / LTS / UVE builds)
#
# Copyright 2026 赵昕 BG8ADW
#
# Based on the Quansheng UV-K5 driver:
#   Quansheng UV-K5 driver (c) 2023 Jacek Lipkowski <sq5bpf@lipkowski.org>
#   based on template.py Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
# and on the reversed protocol and memory notes of the k5web project
# (MIT licensed): k5web/src/utils/serial.js,
# k5web/src/components/navbar/index.vue,
# k5web/src/views/list/search-table/index.vue
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Quansheng UV-K5/UV-K6 running Chinese third-party firmware.

The third party firmwares (LOSEHU, LTS, UVE and derivates) keep the stock
channel area but add an alternate EEPROM command pair, a per-build channel
name encoding and, on some builds, a much larger EEPROM.  This driver reuses
the framing layer of ``chirp.drivers.uvk5`` and adds only what is different.

CHANNEL RECORD, ATTRIBUTES AND NAMES (verified)
-----------------------------------------------
* Framing (``ab cd`` / ``dc ba``, length, XOR obfuscation, CRC16-XMODEM) is
  reused verbatim from uvk5.py, which is verified on real hardware.
* The 16 byte channel record at 0x0000 is byte for byte the same as
  uvk5.MEM_FORMAT (``uvk5.py:50-91``), which is confirmed against the
  firmware write path: ``settings.c:691-711`` fills byte 0-3 with the RX
  frequency in 10 Hz units, byte 4-7 with the TX *offset*, byte 8/9 with the
  RX/TX tone code, byte 10 with ``(TX.CodeType << 4) | RX.CodeType``, byte 11
  with ``(Modulation << 4) | offset direction``, byte 12 with
  ``busy<<4 | power<<2 | bandwidth<<1 | reverse``, byte 13 with
  ``pttid<<1 | dtmf``, byte 14 with the step index and byte 15 with the
  scrambler.  That is exactly the uvk5 field order, including the tone
  *type* nibbles in byte 10 (``uvk5.py:58-59``) rather than tone values.
* Channel attributes live at 0x0D60, one byte per channel.  The firmware
  declares ``band:4, compander:2, scanlist2:1, scanlist1:1`` in a union
  (``misc.h:174-183``); on a little endian target that is bit7 = scanlist1,
  bit6 = scanlist2, bits4-5 = compander and bits0-3 = band.  CHIRP's bitwise
  bitfields are MSB first, so uvk5's
  ``is_scanlist1:1, is_scanlist2:1, compander:2, is_free:1, band:3``
  (``uvk5.py:94-100``) lands on bit7/bit6/bits4-5/bits0-2, and its
  ``is_free`` is the firmware's fourth band bit.  The two only differ for
  band values above 6, which the firmware itself only uses as a "no band"
  sentinel: it writes ``band = 0xf`` for a cleared channel
  (``settings.c:287,755-760``), which CHIRP spells as is_free = 1, band = 7,
  i.e. the byte 0x0F - the same byte, and k5web accepts both 0x0F and 0xFF
  as "empty" too (``search-table/index.vue:633``).  This driver therefore
  keeps the upstream declaration and matches the firmware on the wire.
* The attribute array is 207 bytes in the firmware
  (``misc.h:185`` = 200 memory channels + 7 frequency channels) and the
  channel names are 200 x 16 bytes at 0x0F50 (``settings.c:396,741-745``).
  Only the 200 memory channels are modelled here; the trailing 7 attribute
  bytes are left exactly as read, because CHIRP uploads the whole image
  unchanged.  (k5web only reads 0x0D60..0x0E20, i.e. 192 bytes, which is a
  bug in k5web and is deliberately not copied.)
* The channel name field is 16 bytes.  The radio's own menu editor only
  handles ``MAX_EDIT_INDEX`` bytes of it and truncates to that when the
  radio itself saves a channel (``settings.c:742-745``): 13 bytes for
  ``ENABLE_CHINESE_FULL == 4`` builds and 10 bytes otherwise
  (``font.h:28,30``).  Radios in the field nevertheless carry longer names,
  written by other tools (k5web writes up to 16 bytes, ``serial.js:759``;
  the reference capture has ten channels over 13 bytes and one filling all
  16), so this driver reads and writes the whole 16 byte field and never
  shortens an existing name.  Only a name that cannot fit the field at all
  is refused, as an error.
* Airband: CHIRP's core refuses an airband frequency that falls in a gap of
  the 8.33 kHz channel scheme (``chirp_common.py:1878-1884``).  The
  reference capture contains one (121.745 MHz), and this driver does not
  override that policy; it is the same behaviour the stock uvk5 driver
  would show, and overriding it would require a
  ``tests/driver_xfails.yaml`` entry.
* Unknown bits in bytes 0x0A..0x0F of a channel record are preserved with
  the upstream SAVE_MASK values (``uvk5.py:232-237``), which matters for
  LOSEHU builds that set bit5 of byte 12 and mirror the reverse flag into
  bit6 (``uv-k5-firmware-custom/settings.c:679-685``); LTS does not set
  them, so they must survive a round trip untouched.

PROTOCOL (verified on hardware)
-------------------------------
* Both EEPROM command pairs are used, chosen per profile exactly like
  k5web's ``uart`` field: the stock 0x1B/0x1D pair for the ``losehu117``,
  ``losehu118`` and ``lts`` profiles, and the split 32 bit address pair
  0x2B/0x38 for the rest.  The firmware source only lists 0x2B inside
  ``#if ENABLE_CHINESE_FULL==4`` (``app/uart.c:675-681``), but a real
  LOSEHU131HS radio answers both pairs, so the gate is not simply "K builds
  only".  The stock 16 bit command wraps at 0x10000 on that radio (reading
  0x10000 returns the same bytes as 0x0000) while 0x2B returns different
  bytes, which is the real reason the expanded profiles need 0x2B.
* Commands carry the hello timestamp (see TIMESTAMP below); a mismatched
  timestamp is dropped by the firmware without any reply.
* One read is limited to 0x80 bytes by the reply structure
  (``app/uart.c:100-108``), which is this driver's read block.  Writes use
  0x40, the size k5web uses on every write path and the size exercised
  against hardware, even though the firmware's receive buffer
  (``app/uart.c:24,172``) would take 0x80.
* A write is a single 0x38 command whose header size is ``10 + len(data)``
  as the firmware's CMD_0538 computes it (``app/uart.c:614-649``); the
  payload length must be a multiple of the firmware's 8 byte write unit.
  Each write command ends by reloading the radio's own settings
  (``SETTINGS_InitEEPROM()``, ``app/uart.c:646``), so the upload does not
  strictly need the reboot that upstream sends at the end.

CHANNEL NAMES ARE PER-BUILD, THREE DIFFERENT ENCODINGS
------------------------------------------------------
There is no single name encoding.  Which one applies depends on the build:

1. LOSEHU tree with ``ENABLE_CHINESE_FULL != 0``: plain GB2312 double byte,
   first byte >= 0xA1, glyph looked up by classic GB2312 code order
   (``ui/helper.c:246-253``, font blob at EEPROM 0x2E00).  This is the only
   encoding this driver reads and writes, and it is what the profiles
   ``losehu118h``, ``losehu118k``, ``losehu120k``, ``losehu124h``,
   ``losehubl`` and ``losehud`` use.  Confirmed on a real LOSEHU131HS radio,
   whose channel 1 name field holds the GB2312 bytes for the four character
   name "私有频点".
2. LTS tree with ``ENABLE_CHINESE_FULL != 0``: NOT GB2312.  The name holds
   remapped font indices, ``index = (hi - 0x80) * 255 + lo - 1`` with the
   first byte restricted to 0x80..0x9B (``ui/helper.c:192-201``,
   ``settings.c:398-403``, font blob at EEPROM 0x2000).  This is exactly
   k5web's ``charset: "losehu"`` / ``FONT_MAPPING_117``
   (``serial.js:1642-1661``).  Decoding such a name as GB2312 does not
   fail loudly, it silently produces wrong characters whose re-encoding is
   irreversible.  Those profiles (``losehu117k``, ``ltsk``) are handled by
   ``UVK5CNFontRadio``, which keeps every byte as one character, marks the
   name immutable so CHIRP never offers it for editing, and still gives the
   user full control of frequencies, tones, duplex, power, step and scan
   lists.
3. Builds with ``ENABLE_CHINESE_FULL == 0`` use a single byte glyph index
   (1-9, 11-31, 127-233) into a 137 glyph table compiled into flash
   (``ui/helper.c:46-50``, ``font.h:22``).  The ``losehu117``,
   ``losehu118`` and ``lts`` profiles fall here; k5web also reads them as
   plain ASCII, and so does this driver.  A name that contains glyph bytes
   is not representable, so when such a channel is edited without changing
   the visible name this driver leaves the name bytes completely alone
   instead of overwriting them with ASCII (see ``_store_name``).

EEPROM SIZE (per profile default, always overridable)
-----------------------------------------------------
k5web determines the EEPROM size by *writing* test bytes and reading them
back (``serial.js:1571-1638``).  A clone mode driver must never write while
probing, so this driver takes the size from, in order:

1. the length of a loaded image (authoritative - what is in the file is what
   was read from the radio),
2. the per profile default below,
3. the user's "EEPROM size" setting in the driver information group.

The reference radio was scanned at stride 0x8000 over 0..0x100000: real data
at 0x00000-0x02FFF (including the pinyin and font area at 0x20000), mostly
erased bytes at 0x030000-0x03FFFF, the multi-bootloader at 0x040000+ (a slot
count at 0x40000 and the ASCII string "_BL002" at 0x40008), and above
0x80000 the whole space aliases back to 0 (0x080000 reads exactly what
0x000000 reads).  So 0x40000 is the largest image that covers all of the
build's own data and stops precisely where the bootloader begins:

    profile                              default   basis
    ---------                            -------   -----
    every expanded profile (lts, ltsk,
    losehu117k, losehu118h, losehu118k,
    losehu120k, losehu124h, losehubl,
    losehud, UVE.*)                      0x40000   live scan of the
                                                     reference radio
    losehu117, losehu118, todo           0x2000    OEM sized builds

If the default is too large the download stops at the last address the radio
answered for and keeps what it has (never less than 0x2000), so a wrong
guess costs a warning, not an image.  An image whose length does not match
the effective size, or that extends to or past 0x40000, is refused.

WRITE SAFETY
------------
The 0x040000-0x07FFFF region holds the multi-bootloader that some of these
builds install there.  A stray write into it can leave the radio unbootable
in a way CHIRP cannot repair, which is the one place where the Chinese
firmware is strictly more dangerous than an OEM UV-K5.  This driver
therefore never writes at or above 0x40000 (refusing with an error naming
the offset and the limit), refuses an image that extends into that region,
and normally writes only PROG_SIZE = 0x1d00 bytes at all, so the fonts, the
welcome text, the FM broadcast presets and the bootloader region are
preserved simply by never being written.  Uploading also requires the
image's recorded firmware to match the radio's, so an image from a different
build cannot be pushed into a bootloader region it does not belong to.

VERIFICATION STATUS
-------------------
Verified against a real radio (LOSEHU131HS, 2026-10-13, Prolific PL2303GS
on COM9):
* the hello handshake and its version string,
* both EEPROM read command pairs, including 0x2B addressing past 0x10000
  where the stock 0x1B command wraps at 0xFFFF,
* the channel record fields, the channel attribute bytes and the GB2312
  name encoding (channel 1 of the capture reads 435.5875 MHz simplex with
  the name "私有频点"),
* the write command 0x38: a GB2312 name was written to an unused channel's
  name slot, read back byte for byte, restored and re-read, and the same was
  done at 0x01E1E8 to prove the 32 bit address path,
* a whole image write and read-back: 2048 blocks of 0x40 bytes with no
  failures, followed by a full read that differed in 0 bytes,
* determinism: two independent dump sessions agree byte for byte over their
  common 128 KiB, i.e. the write and restore path leaves the radio
  unchanged,
* CHIRP's own clone path end to end: detect_from_serial() picks the losehu
  variant, sync_in() reads the whole 0x40000 image with 0 differences
  against an independent capture, and after sync_out() a fresh session's
  sync_in() again differs in 0 bytes.

NOT verified on a real radio:
* Every build other than LOSEHU131HS.  The font mapped profiles in
  particular have no hardware here, so only their codec, name immutability
  and detection are tested.  The region above PROG_SIZE is never written by
  design, so it is not exercised either.
* The RX/TX band tables used for validation are a permissive guess for
  "limits removed" firmware.  The band byte stored per channel is instead
  derived from k5web's ``freqRange`` table, which matches the firmware's own
  band boundaries (``frequencies.c:37-44``, 50/108/137/174/350/400/470 MHz).
* Settings other than the driver information group are deliberately not
  mapped: programmable keys, DTMF, MDC contacts, scan lists, FM broadcast
  presets, boot logo, satellite data, AES key, the pinyin and font blobs and
  the calibration block.
* LTS builds with ``ENABLE_CHINESE_FULL`` 1/2/3 write up to three font banks
  at EEPROM 0x2000 + 40960*k (``main.c:133-160``) while the drawing code
  only ever reads the bank at 0x2000 (``ui/helper.c:201``); those builds
  report a version string without a LOSEHU prefix and are read only here.
"""

import logging
import re
import struct

from chirp import chirp_common, directory, bitwise, errors, memmap
from chirp.drivers import uvk5
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

# The channel record, attribute and name areas.  Only the parts of
# uvk5.MEM_FORMAT that are cross-checked against the firmware and k5web are
# mapped here; the settings area, the boot logo, the AES key and the
# calibration block are intentionally left unmapped so that this driver
# cannot corrupt what it does not understand.
#
# Offsets follow from the declarations: 214 * 16 = 0xd60 for the attributes
# and 200 x 16 bytes of names at 0xf50.
MEM_FORMAT = """
struct {
  ul32 freq;
  ul32 offset;
  u8 rxcode;
  u8 txcode;

  // byte 10: (TX tone type << 4) | RX tone type (settings.c:697)
  u8 txcodeflag:4,
     rxcodeflag:4;

  // byte 11: (modulation << 4) | offset direction (settings.c:698)
  u8 flags1_unknown7:1,
  flags1_unknown6:1,
  flags1_unknown5:1,
  enable_am:1,
  flags1_unknown3:1,
  is_in_scanlist:1,
  shift:2;

  // byte 12: see SAVE_MASK_0C; LOSEHU also sets bit5 and mirrors the
  // reverse flag into bit6 (settings.c:679-685)
  u8 flags2_unknown7:1,
  flags2_unknown6:1,
  flags2_unknown5:1,
  bclo:1,
  txpower:2,
  bandwidth:1,
  freq_reverse:1;

  // byte 13: (pttid << 1) | dtmf decode (settings.c:704-708)
  u8 dtmf_flags_unknown7:1,
  dtmf_flags_unknown6:1,
  dtmf_flags_unknown5:1,
  dtmf_flags_unknown4:1,
  dtmf_flags_unknown3:1,
  dtmf_pttid:2,
  dtmf_decode:1;

  u8 step;
  u8 scrambler;
} channel[214];

// The firmware array is 207 bytes (misc.h:185, 200 memory channels plus 7
// frequency channels at 0x0C80).  Only the 200 memory channels are
// modelled; the trailing 7 bytes are left as read, because CHIRP uploads
// the whole image.  "is_free" is bit3, which the firmware counts as the
// fourth bit of its 4 bit band field; the two spellings agree on the empty
// markers 0x0F and 0xFF (settings.c:287,755-760).
struct {
u8 is_scanlist1:1,
is_scanlist2:1,
compander:2,
is_free:1,
band:3;
} channel_attributes[200];

#seekto 0xf50;
struct {
char name[16];
} channelname[200];
"""

# The firmware remembers the four byte timestamp of the hello command and
# silently drops any later command that carries a different one: there is no
# reply and no error, so a mismatch looks exactly like a dead radio.
#
#   app/uart.c:243   CMD_0514 (hello): Timestamp = pCmd->Timestamp;
#   app/uart.c:264   CMD_051B: if (pCmd->Timestamp != Timestamp) return;
#   app/uart.c:298   CMD_051D: same
#   app/uart.c:584   CMD_052B: same
#   app/uart.c:613   CMD_0538: same
#
# uvk5._sayhello() sends b"\x14\x05\x04\x00" + TIMESTAMP (uvk5.py:436) and
# upstream's _readmem/_writemem send the same bytes (uvk5.py:464,474), so
# the stock path is self consistent.  k5web sends 0xFF x 4 for both its
# handshake and its commands, which is also self consistent, but mixing the
# two makes every read and write after the handshake fail silently.  This
# driver reuses uvk5._sayhello(), so it must send TIMESTAMP here as well.
# The unit tests assert that the hello packet, the read command and the
# write command all carry the same four bytes.
TIMESTAMP = b'\x6a\x39\x57\x64'

# Highest EEPROM address this driver will ever read or write.
#
# The reference radio was scanned at stride 0x8000 over 0..0x100000: user
# data occupies 0x00000-0x02FFF, 0x030000-0x03FFFF is mostly erased and
# 0x040000-0x07FFFF holds the multi-bootloader - 0x40000 a slot count,
# 0x40008 the ASCII string "_BL002" - after which the space aliases with a
# period of 0x80000 (0x080000 reads back exactly what 0x000000 reads).
# A stray write into the bootloader region can leave the radio unbootable in
# a way CHIRP cannot repair, so nothing at or above 0x40000 is ever written,
# and an image longer than that is refused.  This is the one place where the
# Chinese firmware is strictly more dangerous than an OEM UV-K5.
#
# Everything this driver maps lives far below the limit: PROG_SIZE is 0x1d00.
DATA_LIMIT = 0x40000

# Size of the channel name field on disk, in bytes.
NAME_LENGTH = 16

# How many bytes of the name field the firmware itself will ever write
# (font.h:28,30).  The condition is ENABLE_CHINESE_FULL == 4, which is the
# same set of builds that k5web marks with a gb2312 or losehu charset:
# those allow 13 bytes, everything else allows 10.  Anything longer is
# truncated by the radio on its next save, so the driver must not offer it.
NAME_BYTES_CHINESE_FULL = 13
NAME_BYTES_DEFAULT = 10

# Profiles whose channel names use k5web's font mapping rather than GB2312.
# This driver does not embed that font table, so reading such a name as
# GB2312 would silently produce wrong characters whose re-encoding is
# irreversible (see the module docstring).  Those firmwares are left to
# uvk5.UVK5RestrictedRadio, which is read only.
FONT_MAPPED_PROFILES = frozenset(('losehu117k', 'ltsk'))

# Profiles whose builds run with ENABLE_CHINESE_FULL == 4: they store names
# as two byte font codes and allow 13 byte names (font.h:28).  These are the
# profiles k5web gives a gb2312 or losehu charset, plus the font mapped ones
# that are read only here.
CHINESE_FULL_PROFILES = frozenset((
    'losehu118h', 'losehu118k', 'losehu120k', 'losehu124h',
    'losehubl', 'losehud', 'losehu117k', 'ltsk'))

# Ordered firmware regular expression -> profile name -> EEPROM size in
# bytes, transcribed from k5web navbar/index.vue:230-254.  k5web matches
# with ``new RegExp(pattern).test(version)``, i.e. an unanchored search, and
# stops at the first match, so the order below is significant.
#
# The version string comes from the radio's hello reply (command 0x0514,
# reply 0x0515, offset 4, up to 16 ASCII bytes: app/uart.c:76,206-220) and
# is the build's PACKED_FILE_SUFFIX (version.h:27, version.c:22,
# Makefile:309) - NOT the ``*OEFW-<author>`` flash header that fw-pack.py
# inserts at 0x2000, which must never be allowlisted.
#
# Sizes.  A live probe of the reference LOSEHU131HS radio (2026-10-13,
# PL2303GS on COM9) read real data at 0x00000-0x02FFF - including the pinyin
# and font area at 0x20000 - mostly erased bytes at 0x030000-0x03FFFF, and
# the multi-bootloader at 0x040000+ (0x40008 = "_BL002"); above 0x80000 the
# space aliases back to 0.  So 0x40000 is the largest image that covers the
# build's own data and stops exactly at the bootloader, and that is the
# default for every expanded profile.  The OEM sized profiles keep 0x2000
# (the stock radio's EEPROM), and the LTS builds that their Makefile builds
# as a single 1 Mibit part are covered by the same 0x40000 default, which is
# only ever a default: a loaded image wins and the user can override it.
CN_PROFILES = (
    (r'L_BL[0-9][0-9][0-9]', 'losehubl', 0x40000),
    (r'LOSEHU.*P.*K', 'ltsk', 0x40000),
    (r'LOSEHU.*P.*', 'lts', 0x40000),
    (r'LOSEHU.*D', 'losehud', 0x40000),
    (r'UVE.*', 'losehu124h', 0x40000),
    (r'LOSEHU13[0-9].*HS', 'losehu124h', 0x40000),
    (r'LOSEHU13[0-9].*H', 'losehu124h', 0x40000),
    (r'LOSEHU13[0-9].*KS', 'losehu120k', 0x40000),
    (r'LOSEHU13[0-9].*K', 'losehu120k', 0x40000),
    (r'LOSEHU13[0-9].*', 'losehu118', 0x2000),
    (r'LOSEHU12[4-9].*HS', 'losehu124h', 0x40000),
    (r'LOSEHU12[4-9].*H', 'losehu124h', 0x40000),
    (r'LOSEHU12[0-3].*H', 'losehu118h', 0x40000),
    (r'LOSEHU12[0-9].*KS', 'losehu120k', 0x40000),
    (r'LOSEHU12[0-9].*K', 'losehu120k', 0x40000),
    (r'LOSEHU12[0-9].*', 'losehu118', 0x2000),
    (r'LOSEHU11[8-9].*H', 'losehu118h', 0x40000),
    (r'LOSEHU11[8-9].*K', 'losehu118k', 0x40000),
    (r'LOSEHU11[8-9].*', 'losehu118', 0x2000),
    (r'LOSEHU11[2-7].*K', 'losehu117k', 0x40000),
    (r'LOSEHU11[2-7].*', 'losehu117', 0x2000),
    # Any other LOSEHU1xx build.  k5web has no entry for these either (they
    # land on its "todo" profile); we recognise the family explicitly and
    # refuse to guess a name encoding rather than making it writable.
    (r'LOSEHU1[0-9][0-9].*', 'todo', 0x2000),
    # The UV-K1 is a different radio, handled by uvk5.UVK1Radio.
    (r'7\..*', 'k1', 0x2000),
    (r'.*', 'todo', 0x2000),
)

# EEPROM sizes offered by k5web (serial.js check_eeprom, card/index.vue).
EEPROM_SIZES = (0x2000, 0x10000, 0x20000, 0x40000, 0x80000)
EEPROM_SIZE_LABELS = (
    '0x2000 (8 KiB)',
    '0x10000 (64 KiB)',
    '0x20000 (128 KiB)',
    '0x40000 (256 KiB)',
    '0x80000 (512 KiB)',
)
EEPROM_SIZE_CHOICES = dict(zip(EEPROM_SIZE_LABELS, EEPROM_SIZES))

# Tuning steps offered for these firmwares; the channel record stores the
# index into this list in a whole byte.  Transcribed from k5web
# search-table/index.vue (stepOption); 24 entries, which is also
# STEP_N_ELEM in the firmware (frequencies.h:45-73).
CN_STEPS = (2.50, 5.00, 6.25, 10.00, 12.50, 25.00, 8.33, 0.01, 0.05, 0.10,
            0.25, 0.50, 1.00, 1.25, 9.00, 15.00, 20.00, 30.00, 50.00, 100.00,
            125.00, 200.00, 250.00, 500.00)

# Band edges used by k5web to pick the band byte it stores in the channel
# attributes (search-table/index.vue freqRange, and the reduce/indexOf pair
# on write): the index of the highest edge below the RX frequency.  These
# are the firmware's own boundaries (frequencies.c:37-44).
CN_BAND_EDGES = (50.0, 108.0, 136.0, 174.0, 350.0, 400.0, 470.0)

# Wide coverage of the "limits removed" firmwares, half open [lo, hi) to
# match RadioFeatures.validate_memory().
CN_BANDS = (
    (18000000, 108000000),
    (108000000, 137000000),
    (137000000, 174000000),
    (174000000, 350000000),
    (350000000, 400000000),
    (400000000, 470000000),
    (470000000, 1300000000),
)

_GB2312_CHARSET = None
_LATIN1_CHARSET = None


def gb2312_charset():
    """Return every character a GB2312 channel name field can hold."""
    global _GB2312_CHARSET
    if _GB2312_CHARSET is None:
        chars = set(chirp_common.CHARSET_ASCII)
        for lead in range(0x81, 0xFF):
            for trail in range(0x40, 0xFF):
                try:
                    chars.add(bytes([lead, trail]).decode('gb2312'))
                except UnicodeDecodeError:
                    continue
        _GB2312_CHARSET = ''.join(sorted(chars))
    return _GB2312_CHARSET


def latin1_charset():
    """Return every character a font mapped name field can hold.

    One character per byte, so every byte except the 0x00 terminator is
    listed; refusing any of them would only produce spurious warnings about
    names this driver deliberately does not interpret.
    """
    global _LATIN1_CHARSET
    if _LATIN1_CHARSET is None:
        _LATIN1_CHARSET = ''.join(chr(byte) for byte in range(1, 0x100))
    return _LATIN1_CHARSET


def cn_profile(firmware):
    """Return the k5web profile name for @firmware.

    k5web uses ``new RegExp(pattern).test(version)`` and keeps the first
    match, i.e. an unanchored search over an ordered table.
    """
    for pattern, profile, _size in CN_PROFILES:
        if re.search(pattern, firmware):
            return profile
    return 'todo'


def profile_mem_size(firmware):
    """Return the default EEPROM size for @firmware, in bytes."""
    for pattern, _profile, size in CN_PROFILES:
        if re.search(pattern, firmware):
            return size
    return 0x2000


def name_max_bytes(firmware):
    """Return how many bytes of a channel name @firmware will store."""
    if cn_profile(firmware) in CHINESE_FULL_PROFILES:
        return NAME_BYTES_CHINESE_FULL
    return NAME_BYTES_DEFAULT


def _encode_char(char, charset='gb2312'):
    """Encode a single character for a channel name field."""
    try:
        return char.encode(charset)
    except (UnicodeEncodeError, LookupError):
        return b'?'


def encode_name_prefix(name, limit=NAME_LENGTH, charset='gb2312'):
    """Encode as many characters of @name as fit in @limit bytes.

    A two byte character is never cut in half.
    """
    out = bytearray()
    for char in name:
        encoded = _encode_char(char, charset)
        if len(out) + len(encoded) > limit:
            break
        out += encoded
    return bytes(out)


def encode_name(name, limit=NAME_LENGTH, charset='gb2312'):
    """Encode @name into exactly NAME_LENGTH bytes, NUL padded."""
    return encode_name_prefix(name, limit, charset).ljust(NAME_LENGTH,
                                                          b'\x00')


def name_fits(name, limit=NAME_LENGTH, charset='gb2312'):
    """True if every character of @name fits in @limit bytes."""
    return len(b''.join(_encode_char(char, charset)
                        for char in name)) <= limit


def decode_name(raw, charset='gb2312'):
    """Decode a NAME_LENGTH byte channel name field.

    Mirrors k5web serial.js uint8ArrayToString() and the firmware's own
    convention (``settings.c:414-417``: NUL terminated, trailing spaces
    trimmed by the caller): the name ends at 0x00 or 0xFF; with the GB2312
    charset a byte >= 0x80 starts a two byte character, and if the field
    ends in the middle of one - or the pair is not valid GB2312 - the rest
    of the name is still decoded instead of being dropped.

    The 'latin1' charset is for the builds whose names are font indices
    rather than text (see the module docstring): every byte maps to exactly
    one character and back, so such a name round-trips byte for byte even
    though the driver cannot interpret it.
    """
    raw = bytes(raw)
    if charset == 'latin1':
        end = raw.find(b'\x00')
        if end < 0:
            end = len(raw)
        text = raw[:end].decode('latin-1')
        if set(text) == {'\xff'}:
            # An all 0xFF field is an unused name slot
            return ''
        return text

    out = []
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte in (0x00, 0xFF):
            break
        if byte < 0x80:
            out.append(chr(byte))
            index += 1
            continue
        if charset != 'gb2312':
            # A single byte glyph index build: stop at the first high byte
            break
        if index + 1 >= len(raw) or raw[index + 1] in (0x00, 0xFF):
            # The field ends in the middle of a two byte character
            break
        try:
            out.append(bytes(raw[index:index + 2]).decode('gb2312'))
        except UnicodeDecodeError:
            out.append('?')
        index += 2
    return ''.join(out)


def readmem_command(offset, length):
    """Build the alternate EEPROM read command (0x2B) for @offset.

    Byte for byte from k5web serial.js:1458, except for the timestamp, which
    must match the hello command (see TIMESTAMP).  The firmware lists this
    command inside ``#if ENABLE_CHINESE_FULL==4`` (``app/uart.c:675-681``),
    but a real LOSEHU131HS build, which k5web classes as an ``H`` and not a
    ``K`` profile, answers 0x2B with true 32 bit addressing, so the gate is
    not a build class.
    """
    return b'\x2b\x05\x08\x00' + \
        struct.pack('<HBB', (offset >> 16) & 0xffff, length, 0) + \
        TIMESTAMP + \
        struct.pack('<H', offset & 0xffff)


def writemem_command(offset, data):
    """Build the alternate EEPROM write command (0x38) for @offset.

    Layout per the firmware's own CMD_0538 (``app/uart.c:614-649``):
    ID, header size, address bits 16-31, size, bAllowPassword, timestamp,
    then the data whose first two bytes are address bits 0-15.  The header
    size counts everything after the four byte header - the two high address
    bytes, the size byte, bAllowPassword, the four timestamp bytes, the two
    low address bytes and the payload - so it is 10 + len(data).  k5web
    hardcodes 0x1c here (``serial.js:1552``) and the firmware tolerates
    that, but the computed value is what the firmware documents.
    """
    return b'\x38\x05' + \
        struct.pack('<H', 10 + len(data)) + \
        struct.pack('<HBB', (offset >> 16) & 0xffff, len(data) + 2, 0) + \
        TIMESTAMP + \
        struct.pack('<H', offset & 0xffff) + data


def _readmem(serport, offset, length):
    """Read @length bytes at @offset with the alternate command."""
    if offset < 0 or offset + length > DATA_LIMIT:
        raise errors.RadioError(
            _('Refusing to read 0x%4.4x..0x%4.4x: this driver only reads '
              'below 0x%4.4x') % (offset, offset + length - 1, DATA_LIMIT))
    serport.log('Sending readmem (cn) offset=0x%4.4x len=0x%4.4x' % (
        offset, length))
    uvk5._send_command(serport, readmem_command(offset, length))
    rep = uvk5._receive_reply(serport)
    if len(rep) < 8 + length:
        LOG.warning('Short readmem reply: got %i bytes, wanted %i',
                    len(rep), 8 + length)
        raise errors.RadioError('Short response to readmem')
    # The firmware does not appear to validate the request's size field (a
    # real radio answers a read with 0x08 and with 0x0A alike), so the
    # reply's size byte is only reported, never asserted on.
    if rep[6] != length:
        LOG.debug('readmem reply size is 0x%2.2x, wanted 0x%2.2x',
                  rep[6], length)
    return rep[8:8 + length]


def _writemem(serport, data, offset):
    """Write @data at @offset with the alternate command.

    Anything at or above DATA_LIMIT is the multi-bootloader region and is
    refused outright: a stray write there can leave the radio unbootable.
    """
    if offset < 0 or offset + len(data) > DATA_LIMIT:
        raise errors.RadioError(
            _('Refusing to write 0x%4.4x..0x%4.4x: 0x%4.4x is the start of '
              'the multi-bootloader on this firmware and writing there can '
              'destroy the radio') % (offset, offset + len(data) - 1,
                                      DATA_LIMIT))
    serport.log('Writemem (cn) at offset %04x len %04x' % (offset, len(data)))
    uvk5._send_command(serport, writemem_command(offset, data))
    rep = uvk5._receive_reply(serport)
    if rep and rep[0] == 0x1e:
        return True
    LOG.warning('Bad data from writemem (cn)')
    raise errors.RadioError('Bad response to writemem')


def do_download(radio):
    """Download the EEPROM from a radio running a Chinese firmware."""
    serport = radio.pipe
    serport.timeout = 0.5
    firmware = uvk5._sayhello(serport)
    if not firmware:
        raise errors.RadioError(_('Unable to determine firmware version'))
    if not radio.k5_approve_firmware(firmware):
        raise errors.RadioError(
            _('Firmware version is not supported by this driver'))
    radio.metadata = {'uvk5_firmware': firmware}

    size = radio.eeprom_size
    limit = min(radio.MAX_ADDRESSABLE, DATA_LIMIT)
    if size > limit:
        raise errors.RadioError(
            _('The EEPROM size is set to 0x%(size)x bytes, but this driver '
              'only reads below 0x%(limit)x; 0x%(data)x and above is the '
              'multi-bootloader on these firmwares. Correct the "EEPROM '
              'size" setting.') % {'size': size, 'limit': limit,
                                   'data': DATA_LIMIT})
    LOG.info('Downloading %i bytes from firmware %r', size, firmware)

    status = chirp_common.Status()
    status.cur = 0
    status.max = size
    status.msg = _('Downloading from radio')
    radio.status_fn(status)

    if radio.USE_EXTENDED_EEPROM:
        readmem = _readmem
    else:
        readmem = uvk5._readmem

    eeprom = b''
    addr = 0
    while addr < size:
        try:
            data = readmem(serport, addr, radio.MEM_BLOCK)
            if not data or len(data) != radio.MEM_BLOCK:
                raise errors.RadioError(_('Memory download incomplete'))
        except errors.RadioError:
            # A profile may over-estimate the EEPROM; never leave the user
            # without an image once a usable one has been read.
            if addr < radio.DEFAULT_MEM_SIZE:
                raise
            LOG.warning('Radio stopped answering at 0x%4.4x; keeping the '
                        '%i bytes read so far. If the image is incomplete, '
                        'set the "EEPROM size" to the real size and '
                        'download again.', addr, addr)
            break
        eeprom += data
        addr += radio.MEM_BLOCK
        status.cur = addr
        radio.status_fn(status)

    return memmap.MemoryMapBytes(eeprom)


def do_upload(radio):
    """Upload a channel image to a radio running a Chinese firmware."""
    serport = radio.pipe
    serport.timeout = 0.5

    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.PROG_SIZE
    status.msg = _('Uploading to radio')
    radio.status_fn(status)

    limit = min(radio.MAX_ADDRESSABLE, DATA_LIMIT)
    if radio.eeprom_size > limit:
        raise errors.RadioError(
            _('The EEPROM size is set to 0x%(size)x bytes, but this driver '
              'only writes below 0x%(limit)x; 0x%(data)x and above is the '
              'multi-bootloader on these firmwares. Correct the "EEPROM '
              'size" setting.') % {'size': radio.eeprom_size,
                                   'limit': limit, 'data': DATA_LIMIT})

    firmware = uvk5._sayhello(serport)
    if not firmware:
        raise errors.RadioError(_('Unable to determine firmware version'))
    if not radio.k5_approve_firmware(firmware):
        raise errors.RadioError(
            _('Firmware version is not supported by this driver'))
    LOG.info('Uploading image from firmware %r to radio with %r',
             radio.metadata.get('uvk5_firmware', 'unknown'), firmware)

    image = radio.get_mmap()
    image_size = len(image) if image is not None else 0
    if image_size > limit:
        raise errors.RadioError(
            _('Image is %(image)i bytes, but this driver only writes below '
              '0x%(limit)x; 0x%(data)x and above is the multi-bootloader on '
              'these firmwares and writing there can destroy the radio. '
              'Use an image that stops before it.') % {
                  'image': image_size, 'limit': limit,
                  'data': DATA_LIMIT})
    size = radio.eeprom_size
    if image_size != size:
        image_fw = radio.metadata.get('uvk5_firmware', '')
        raise errors.RadioError(
            _('Image is %(image)i bytes from firmware %(image_fw)r '
              '(profile %(image_profile)s). The radio reports firmware '
              '%(radio_fw)r (profile %(radio_profile)s), which suggests '
              '%(default)i bytes, and the EEPROM size setting is %(size)i '
              'bytes.\nLoad an image of the right size, or set the EEPROM '
              'size to the real size.') % {
                  'image': image_size,
                  'image_fw': image_fw,
                  'image_profile': cn_profile(image_fw),
                  'radio_fw': firmware,
                  'radio_profile': cn_profile(firmware),
                  'default': profile_mem_size(firmware),
                  'size': size})

    if radio.USE_EXTENDED_EEPROM:
        writemem = _writemem
    else:
        writemem = uvk5._writemem

    addr = 0
    while addr < radio.PROG_SIZE:
        dat = image[addr:addr + radio.WRITE_BLOCK]
        if not dat:
            raise errors.RadioError(_('Memory upload incomplete'))
        writemem(serport, dat, addr)
        addr += radio.WRITE_BLOCK
        status.cur = addr
        radio.status_fn(status)

    # Each write command already makes the radio reload its own settings
    # (CMD_0538 ends with SETTINGS_InitEEPROM(), ``app/uart.c:646``), so no
    # reboot is strictly required; the reset is kept because upstream does
    # it and it leaves the radio in a clean state.
    uvk5._resetradio(serport)
    status.msg = _('Uploaded OK')

    return True


def _find_band_cn(hz):
    """Return the band byte k5web stores for @hz, or False if out of range."""
    if not CN_BANDS[0][0] <= hz < CN_BANDS[-1][1]:
        return False
    mhz = hz / 1000000.0
    band = 0
    for index, edge in enumerate(CN_BAND_EDGES):
        if edge < mhz:
            band = index
    return band


class UVK5CNRadioBase(uvk5.UVK5RadioBase):
    """Common behaviour of the Chinese firmware variants."""

    # Class level sizes.  uvk5.MEM_SIZE/PROG_SIZE/MEM_BLOCK are module
    # globals that its do_download()/do_upload() resolve at run time, so a
    # subclass cannot change them; this module has its own download/upload
    # that read these attributes instead (the same idea as _cal_start).
    #
    # Reads use 0x80, the largest reply the firmware's reply structure can
    # carry (``app/uart.c:100-108``).  Writes use 0x40: the firmware's
    # receive buffer is bigger (``app/uart.c:24,172``) and would take 0x80,
    # but 0x40 is what k5web uses for every write path
    # (``serial.js:1534``) and what has been exercised against hardware, so
    # the reference-verified size wins.  0x40 and 0x80 are both multiples of
    # the firmware's 8 byte write unit, and 0x1d00 is a multiple of 0x40, so
    # there is never a short final chunk.
    #
    # PROG_SIZE stops before the calibration area at 0x1E00
    # (settings.c:314,319,323,332,333,352; the AES key is at 0x0F30,
    # settings.c:294-297), which is unique per radio; everything this driver
    # maps (records, attributes, names) lives below 0x1D00 anyway.
    MEM_BLOCK = 0x80
    WRITE_BLOCK = 0x40
    PROG_SIZE = 0x1d00
    DEFAULT_MEM_SIZE = 0x2000

    # Which EEPROM command pair to use and which channel name encoding.
    USE_EXTENDED_EEPROM = False
    NAME_CHARSET = 'official'

    # Largest EEPROM address this command pair can reach.  The stock
    # 0x1B/0x1D pair carries a 16 bit offset only, so on a radio with the
    # split address command reading at 0x10000 with it silently returns the
    # bytes from 0x0000 (measured on the reference radio).  The split
    # address form is 32 bit but the chip is 4 Mibit, so addresses wrap with
    # a period of 0x80000: reading at 0x080000 on the reference radio
    # returns exactly what 0x000000 returns.  Refusing a size we cannot
    # address correctly is the only safe answer.
    MAX_ADDRESSABLE = 0x10000

    # Channel names of this build cannot be represented as text; see
    # UVK5CNFontRadio.
    NAMES_ARE_TEXT = True

    # Profiles this class answers for; filled in by the concrete classes.
    _CN_PROFILES = frozenset()

    _expanded_limits = True

    def __init__(self, pipe):
        # Must be set before super().__init__(), which loads an image and
        # calls process_mmap() when we are constructed from a filename.
        self._eeprom_size = None
        super().__init__(pipe)

    @classmethod
    def k5_approve_firmware(cls, firmware):
        return cn_profile(firmware) in cls._CN_PROFILES

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = _(
            'This is an experimental driver for Quansheng UV-K5/UV-K6 radios '
            'running Chinese third-party firmware (LOSEHU, LTS, UVE). It has '
            'been tested against one such radio (a LOSEHU131HS build): the '
            'download reproduced that radio exactly, an upload of the same '
            'image left it unchanged (0 bytes differ on a fresh read), and a '
            'whole image write and read-back differed in 0 bytes. Other '
            'builds are untested, so keep a backup. It may still harm your '
            'radio, or worse. Use at your own risk.\n\n'
            'Before making any changes, download the memory image from the '
            'radio and keep it: it can be used to restore the original '
            'settings.\n\n'
            'Please note:\n'
            '- The channel name encoding depends on the firmware build. '
            'Builds that store names as font indices rather than GB2312 '
            '(LOSEHU117K, LTS-K and other TSK/KS builds) are shown with the '
            'raw name bytes and their names cannot be edited in CHIRP, '
            'because text would be meaningless to the radio.\n'
            '- The default EEPROM size is derived from the reported firmware '
            'version and is only a guess. Check the "EEPROM size" setting '
            'against your radio and correct it before uploading.\n'
            '- Writing at or above 0x40000 would overwrite the '
            'multi-bootloader that some of these builds install there, so '
            'this driver never writes that high and refuses an image that '
            'extends into it.\n'
            '- Settings (keys, DTMF, MDC, scan lists, boot logo, satellite '
            'data, calibration) are not supported.')
        rp.pre_download = _(
            '1. Turn the radio on.\n'
            '2. Connect the cable to the mic/speaker connector.\n'
            '3. Make sure the connector is firmly seated.\n'
            '4. Click OK to download the image from the device.\n\n'
            'It may not work if you turn the radio on with the cable '
            'already attached.')
        rp.pre_upload = _(
            '1. Turn the radio on.\n'
            '2. Connect the cable to the mic/speaker connector.\n'
            '3. Make sure the connector is firmly seated.\n'
            '4. Click OK to upload the image to the device.\n\n'
            'It may not work if you turn the radio on with the cable '
            'already attached.')
        return rp

    @property
    def eeprom_size(self):
        """Size of the EEPROM image in bytes.

        A loaded image is authoritative.  Otherwise the profile of the
        firmware on the radio decides, and the user can override it with
        the "EEPROM size" setting.
        """
        if self._eeprom_size:
            return self._eeprom_size
        return profile_mem_size(self.metadata.get('uvk5_firmware', ''))

    def _name_max_bytes(self):
        """How many bytes of a channel name this firmware will store."""
        return name_max_bytes(self.metadata.get('uvk5_firmware', ''))

    def _get_charset(self):
        return chirp_common.CHARSET_ASCII

    def _get_valid_bands(self):
        if self._expanded_limits:
            return CN_BANDS
        return tuple((int(lo * 1000000), int(hi * 1000000))
                     for lo, hi in uvk5.BANDS.values())

    def _find_band(self, hz):
        if self._expanded_limits:
            return _find_band_cn(hz)
        return uvk5._find_band(False, hz)

    def _get_specials(self):
        # The stock driver exposes 14 VFO channels above channel 200.  Those
        # live in the tail of the channel array (0x0C80.., 32 bytes each,
        # settings.c:681-682), which k5web never reads or writes, so they are
        # not offered here.
        return {}

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_settings = True
        rf.has_comment = False
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.valid_dtcs_codes = uvk5.DTCS_CODES
        # The firmware's editable name length, in bytes (font.h:28,30).
        # For ASCII this is also the character count; a name using two byte
        # characters is rejected by validate_memory() if it needs more.
        rf.valid_name_length = self._name_max_bytes()
        rf.valid_characters = self._get_charset()
        rf.valid_power_levels = uvk5.UVK5_POWER_LEVELS
        rf.valid_special_chans = []
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_skips = []
        rf.valid_tuning_steps = list(self._steps)
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_modes = ["FM", "NFM", "AM", "NAM"]
        rf.memory_bounds = (1, 200)
        rf.valid_bands = self._get_valid_bands()
        return rf

    def process_mmap(self):
        self._check_firmware_at_load()
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        # The image tells us how much EEPROM was actually read
        self._eeprom_size = len(self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def _get_tone(self, mem, _mem):
        """Read the tone settings, tolerating a partially written record.

        uvk5's _get_tone indexes TMODES with the raw nibble (uvk5.py:770-773)
        and raises IndexError for a tone type between 4 and 15.  Radios only
        ever write 0..3 (``dcs.h:22-30``), but an interrupted write or a
        hand-made image can leave 0xFF there, and crashing while loading an
        image is worse than losing the tone, so the range is checked first.
        """
        if int(_mem.rxcodeflag) > 3 or int(_mem.txcodeflag) > 3:
            mem.tmode = ''
            return
        return super()._get_tone(mem, _mem)

    def get_memory(self, number):
        mem = super().get_memory(number)
        if not mem.empty and isinstance(number, int) and number <= 200:
            raw = self._memobj.channelname[number - 1].get_raw()
            mem.name = decode_name(raw, self.NAME_CHARSET).rstrip()
            if not self.NAMES_ARE_TEXT:
                # The name is a font index, not text: show it (losslessly)
                # but do not let the user edit it, because a name built from
                # text would be meaningless to the radio.
                mem.immutable = ["name"]
        return mem

    def _get_mem_extra(self, mem, _mem):
        """Build the per channel extra settings.

        Same keys as uvk5 so that set_memory() below works the same way, but
        every label is translatable and the lists use current_index, which
        the inherited version still does not.
        """
        tmpscn = uvk5.SCANLIST_LIST[0]

        if mem.number <= 200:
            _mem3 = self._memobj.channel_attributes[mem.number - 1]
            # free memory bit
            if _mem3.is_free > 0:
                mem.empty = True
            # scanlists
            if _mem3.is_scanlist1 > 0 and _mem3.is_scanlist2 > 0:
                tmpscn = uvk5.SCANLIST_LIST[3]  # "1+2"
            elif _mem3.is_scanlist1 > 0:
                tmpscn = uvk5.SCANLIST_LIST[1]  # "1"
            elif _mem3.is_scanlist2 > 0:
                tmpscn = uvk5.SCANLIST_LIST[2]  # "2"

        mem.extra = RadioSettingGroup("Extra", "extra")

        is_bclo = not mem.empty and bool(_mem.bclo > 0)
        rs = RadioSetting("bclo", _("BCLO"),
                          RadioSettingValueBoolean(is_bclo))
        mem.extra.append(rs)

        is_frev = not mem.empty and bool(_mem.freq_reverse > 0)
        rs = RadioSetting("frev", _("FreqRev"),
                          RadioSettingValueBoolean(is_frev))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", _("PTTID"), RadioSettingValueList(
            self._pttid_list, current_index=int(_mem.dtmf_pttid)))
        mem.extra.append(rs)

        is_dtmf = not mem.empty and bool(_mem.dtmf_decode > 0)
        rs = RadioSetting("dtmfdecode", _("DTMF decode"),
                          RadioSettingValueBoolean(is_dtmf))
        mem.extra.append(rs)

        enc = _mem.scrambler & 0x0f
        if enc >= len(uvk5.SCRAMBLER_LIST):
            enc = 0
        rs = RadioSetting("scrambler", _("Scrambler"), RadioSettingValueList(
            uvk5.SCRAMBLER_LIST, current_index=enc))
        mem.extra.append(rs)

        rs = RadioSetting("scanlists", _("Scanlists"), RadioSettingValueList(
            uvk5.SCANLIST_LIST,
            current_index=uvk5.SCANLIST_LIST.index(tmpscn)))
        mem.extra.append(rs)

    def _store_name(self, number, name):
        """Store @name in the name field of channel @number.

        If the name we can decode is unchanged, the raw bytes are left
        exactly as they were.  That keeps glyph index characters (which only
        one of the three name encodings can represent, and which this driver
        does not model) from being overwritten with ASCII just because the
        user changed the frequency of that channel.

        The whole 16 byte field is used, not the firmware's own smaller
        editor limit: radios in the field carry names up to the full field
        width, written by other tools, and a name must never be shortened
        just because it was stored again.  Names wider than the editor limit
        are reported by validate_memory() instead.
        """
        field = self._memobj.channelname[number]
        raw = bytes(field.get_raw())
        if raw != b'\xff' * NAME_LENGTH and \
                decode_name(raw, self.NAME_CHARSET).rstrip() == name.rstrip():
            return
        field.set_raw(encode_name(name, NAME_LENGTH, self.NAME_CHARSET))

    def set_memory(self, mem):
        """Store a memory.

        This is a byte-native reimplementation of uvk5's channel write.
        The stock implementation stores the name as a Python str, which
        would raise in CHIRP's strict bytes test mode, and it cannot hold a
        multi byte name of the length these fields use.
        """
        number = mem.number - 1
        _mem = self._memobj.channel[number]
        _mem4 = self._memobj

        if mem.empty:
            _mem.set_raw(b'\xFF' * NAME_LENGTH)
            if number < 200:
                self._memobj.channelname[number].set_raw(
                    b'\xFF' * NAME_LENGTH)
                _attr = _mem4.channel_attributes[number]
                _attr.is_scanlist1 = 0
                _attr.is_scanlist2 = 0
                _attr.compander = 0
                # The firmware's own "no band" sentinel is band = 0xf
                # (settings.c:287,755-760), which CHIRP spells as
                # is_free = 1, band = 7 - the same byte, 0x0F.
                _attr.is_free = 1
                _attr.band = 0x7
            return mem

        if _mem.get_raw()[0] == 0xff:
            # This was an empty memory
            _mem.set_raw(b'\x00' * NAME_LENGTH)
        else:
            # Keep the bits we do not understand, like the stock driver.
            # Byte 0x0A and byte 0x0E are fully owned by the tone type and
            # step fields, so their masks cannot take effect; bytes 0x0B to
            # 0x0D and 0x0F are what actually survives.
            prev = bytes(_mem.get_raw()[0x0a:0x10])
            _mem.set_raw(b'\x00' * 10 +
                         bytes([prev[0] & uvk5.SAVE_MASK_0A,
                                prev[1] & uvk5.SAVE_MASK_0B,
                                prev[2] & uvk5.SAVE_MASK_0C,
                                prev[3] & uvk5.SAVE_MASK_0D,
                                prev[4] & uvk5.SAVE_MASK_0E,
                                prev[5] & uvk5.SAVE_MASK_0F]))

        if number < 200:
            _attr = _mem4.channel_attributes[number]
            _attr.is_scanlist1 = 0
            _attr.is_scanlist2 = 0
            _attr.compander = 0
            _attr.is_free = 1
            _attr.band = 0x7

        band = self._find_band(mem.freq)

        self._set_mem_mode(_mem, mem.mode)

        _mem.freq = mem.freq // 10
        _mem.offset = mem.offset // 10

        if mem.duplex == "":
            _mem.offset = 0
            _mem.shift = 0
        elif mem.duplex == '-':
            _mem.shift = uvk5.FLAGS1_OFFSET_MINUS
        elif mem.duplex == '+':
            _mem.shift = uvk5.FLAGS1_OFFSET_PLUS
        elif mem.duplex == 'off':
            # Fake tx disable by setting the tx frequency to 0 MHz
            _mem.shift = uvk5.FLAGS1_OFFSET_MINUS
            _mem.offset = _mem.freq

        if number < 200:
            _attr.is_free = 0
            _attr.band = 0 if band is False else band
            self._store_name(number, mem.name)

        self._set_tone(mem, _mem)

        _mem.step = self._steps.index(mem.tuning_step)

        if str(mem.power) == str(uvk5.UVK5_POWER_LEVELS[2]):
            _mem.txpower = uvk5.POWER_HIGH
        elif str(mem.power) == str(uvk5.UVK5_POWER_LEVELS[1]):
            _mem.txpower = uvk5.POWER_MEDIUM
        else:
            _mem.txpower = uvk5.POWER_LOW

        for setting in mem.extra:
            sname = setting.get_name()
            svalue = setting.value.get_value()

            if sname == "bclo":
                _mem.bclo = svalue and 1 or 0

            if sname == "pttid":
                try:
                    _mem.dtmf_pttid = self._pttid_list.index(svalue)
                except ValueError:
                    _mem.dtmf_pttid = 0

            if sname == "frev":
                _mem.freq_reverse = svalue and 1 or 0

            if sname == "dtmfdecode":
                _mem.dtmf_decode = svalue and 1 or 0

            if sname == "scrambler":
                _mem.scrambler = (
                    _mem.scrambler & 0xf0) | uvk5.SCRAMBLER_LIST.index(svalue)

            if number < 200 and sname == "scanlists":
                _attr = _mem4.channel_attributes[number]
                if svalue == "1":
                    _attr.is_scanlist1 = 1
                    _attr.is_scanlist2 = 0
                elif svalue == "2":
                    _attr.is_scanlist1 = 0
                    _attr.is_scanlist2 = 1
                elif svalue == "1+2":
                    _attr.is_scanlist1 = 1
                    _attr.is_scanlist2 = 1
                else:
                    _attr.is_scanlist1 = 0
                    _attr.is_scanlist2 = 0

        return mem

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        if mem.empty or not isinstance(mem.number, int):
            return msgs

        # A name that does not fit the field cannot be stored at all, so it
        # is an error.
        #
        # A name between the radio's own editor limit and the end of the
        # field is deliberately NOT reported: the field holds it, this driver
        # preserves it byte for byte, and radios in the field are full of
        # them (the reference capture has ten).  Warning about them would
        # also make every image from a real radio fail CHIRP's generated
        # sample image test, which asserts that validate_memory() returns no
        # *warnings* for any channel of a sample image
        # (tests/test_brute_force.py:202 unpacks split_validation_msgs() the
        # other way round, so its "errs" holds the warnings).  Upstream
        # handles that with an entry in tests/driver_xfails.yaml; not
        # needing one is better than adding one.
        if not name_fits(mem.name, NAME_LENGTH, self.NAME_CHARSET):
            msgs.append(chirp_common.ValidationError(
                _('The name needs more than the %i bytes this name field '
                  'holds') % NAME_LENGTH))

        return msgs

    def get_settings(self):
        roinfo = RadioSettingGroup('roinfo', _('Driver information'))
        top = RadioSettings(roinfo)

        firmware = self.metadata.get('uvk5_firmware', 'UNKNOWN')
        # Fixed width and no autopad, so that the value shown is exactly the
        # firmware string (uvk5 pads this to 128 characters).
        val = RadioSettingValueString(len(firmware), len(firmware), firmware,
                                      False)
        val.set_mutable(False)
        roinfo.append(RadioSetting('fw_ver', _('Firmware version'), val))

        size = self.eeprom_size
        if size in EEPROM_SIZES:
            index = EEPROM_SIZES.index(size)
        else:
            index = 0
        rs = RadioSetting('eeprom_size', _('EEPROM size'),
                          RadioSettingValueList(EEPROM_SIZE_LABELS,
                                                current_index=index))
        rs.set_doc(_(
            'The profile %(profile)s suggests %(default)i bytes; this is '
            'only a guess and the radio is the authority. A loaded image '
            'sets this automatically, and anything at or above '
            '0x%(limit)x is refused because that is the multi-bootloader '
            'region.') % {
                'profile': cn_profile(
                    self.metadata.get('uvk5_firmware', '')),
                'default': profile_mem_size(
                    self.metadata.get('uvk5_firmware', '')),
                'limit': DATA_LIMIT})
        roinfo.append(rs)

        val = RadioSettingValueBoolean(self._expanded_limits)
        rs = RadioSetting('nolimits',
                          _('Limits disabled for modified firmware'), val)
        rs.set_warning(_(
            'This should only be enabled if you are using modified firmware '
            'that supports wider frequency coverage. Enabling this will '
            'cause CHIRP not to enforce OEM restrictions and may lead to '
            'undefined or unregulated behavior. Use at your own risk!'),
            safe_value=False)
        roinfo.append(rs)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            name = element.get_name()

            if name == 'eeprom_size':
                size = EEPROM_SIZE_CHOICES.get(str(element.value))
                if size:
                    self._eeprom_size = size

            elif name == 'nolimits':
                LOG.warning('User expanded band limits')
                self._expanded_limits = bool(element.value)


@directory.register
@directory.detected_by(uvk5.UVK5Radio)
class UVK5CNRadio(UVK5CNRadioBase):
    """Quansheng UV-K5 with Chinese firmware (stock EEPROM commands)"""

    VENDOR = "Quansheng"
    MODEL = "UV-K5"
    VARIANT = "cn"
    BAUD_RATE = 38400

    # These builds have ENABLE_CHINESE_FULL == 0, so their names are plain
    # ASCII as far as CHIRP and k5web are concerned and the firmware only
    # stores 10 bytes of them (font.h:30).
    _CN_PROFILES = frozenset(('losehu117', 'losehu118', 'lts'))

    _steps = CN_STEPS
    _pttid_list = ["off", "BOT", "EOT", "BOTH"]


@directory.register
@directory.detected_by(uvk5.UVK5Radio)
class UVK5CNLoseHuRadio(UVK5CNRadioBase):
    """Quansheng UV-K5/K6 with expanded (K/H) Chinese firmware"""

    VENDOR = "Quansheng"
    MODEL = "UV-K5"
    VARIANT = "losehu"
    BAUD_RATE = 38400

    # ENABLE_CHINESE_FULL == 4: GB2312 names are stored as is (confirmed on
    # a real LOSEHU131HS radio), the names allow 13 bytes (font.h:28) and
    # the split address commands are the ones that can reach past 0x10000
    # (app/uart.c:578-604).  Do not assume the split address read is
    # restricted to a build class: in the LOSEHU tree the 0x052B handler is
    # commented out entirely (``app/uart.c:586-612``) and the dispatch at
    # ``app/uart.c:670-672`` sends 0x052B to the stock 0x051B handler, yet
    # the reference LOSEHU131HS radio answers 0x2B with true 32 bit
    # addressing while 0x1B wraps at 0xFFFF.  The profile table, which
    # mirrors k5web, is the only reliable selector.
    USE_EXTENDED_EEPROM = True
    NAME_CHARSET = 'gb2312'

    # The split address form is 32 bit but the chip's address space wraps
    # with a period of 0x80000 (see DATA_LIMIT), so that is the addressing
    # ceiling here.
    MAX_ADDRESSABLE = 0x80000

    _CN_PROFILES = frozenset((
        'losehu118h', 'losehu118k', 'losehu120k', 'losehu124h',
        'losehubl', 'losehud'))

    _steps = CN_STEPS
    _pttid_list = ["off", "BOT", "EOT", "BOTH"]

    def _get_charset(self):
        return gb2312_charset()


@directory.register
@directory.detected_by(uvk5.UVK5Radio)
class UVK5CNFontRadio(UVK5CNRadioBase):
    """Quansheng UV-K5 with font mapped (LTS-K / 117K) Chinese firmware

    These builds are the ones k5web gives a ``losehu`` charset: their names
    are not GB2312 but remapped glyph indices,
    ``index = (hi - 0x80) * 255 + lo - 1`` with the first byte in 0x80..0x9B
    (``ui/helper.c:192-201`` with ``settings.c:398-403``, font blob at EEPROM
    0x2000).  Reading such a name as GB2312 would silently produce wrong
    characters and writing it back would be irreversible, so this class does
    not try: it keeps every byte as one character, marks the name immutable
    so CHIRP does not offer it for editing, and gives the user what they
    actually need - frequencies, tones, duplex, power, step and scan lists -
    on radios that would otherwise be treated as completely unsupported.
    """

    VENDOR = "Quansheng"
    MODEL = "UV-K5"
    VARIANT = "font"
    BAUD_RATE = 38400

    USE_EXTENDED_EEPROM = True
    NAME_CHARSET = 'latin1'
    MAX_ADDRESSABLE = 0x80000

    # The name is a font index, not text
    NAMES_ARE_TEXT = False

    _CN_PROFILES = FONT_MAPPED_PROFILES

    _steps = CN_STEPS
    _pttid_list = ["off", "BOT", "EOT", "BOTH"]

    def _get_charset(self):
        return latin1_charset()
