# Quansheng UV-K5 / UV-K6 driver for Chinese third-party firmware
# with GB2312 channel names (LOSEHU / LTS / UVE expanded builds)
#
# Copyright 2026 赵昕 BG8ADW
#
# Based on the Quansheng UV-K5 driver:
#   Quansheng UV-K5 driver (c) 2023 Jacek Lipkowski <sq5bpf@lipkowski.org>
#   based on template.py Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
# and on the reversed protocol and memory notes of the k5web project (MIT
# licensed): k5web/src/utils/serial.js,
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

"""Quansheng UV-K5/UV-K6 running expanded Chinese third-party firmware.

This covers the builds that store channel names as GB2312 and that need the
split-address EEPROM commands (0x2B read / 0x38 write): the LOSEHU expanded
builds, LTS, and UVE.  Everything else is inherited from ``uvk5.py``.

WHAT CHANGES RELATIVE TO THE BASE DRIVER
----------------------------------------
The channel record, the channel attribute bytes and the name array are at
the same offsets with the same layout as the stock radio - verified against
the firmware's own write path (``settings.c:691-711``) and against k5web's
``readChannel``/``writeChannel`` - so ``MEM_FORMAT`` here is
``uvk5.MEM_DEFS`` plus only the three arrays this driver models.  The deltas
are:

* an alternate EEPROM command pair with a split 32 bit address, and a
  different command geometry (0x40 byte writes, computed header size);
* GB2312 channel names, and the firmware's own editor limit for them;
* a larger EEPROM, sized per profile, and a refusal to touch the
  multi-bootloader region that sits above 0x40000 on these builds.

THE COMMAND TIMESTAMP
---------------------
The firmware remembers the four byte timestamp of the hello command and
silently drops any later command that carries a different one - no reply, no
error, indistinguishable from a dead radio:

    app/uart.c:243   CMD_0514 (hello): Timestamp = pCmd->Timestamp;
    app/uart.c:264   CMD_051B: if (pCmd->Timestamp != Timestamp) return;
    app/uart.c:298   CMD_051D: same
    app/uart.c:584   CMD_052B: same
    app/uart.c:613   CMD_0538: same

``uvk5._sayhello()`` sends ``6a 39 57 64`` (``uvk5.py:436``) and upstream's
own commands send the same bytes (``uvk5.py:464,474``), so this driver sends
exactly those bytes too (``TIMESTAMP`` below) and the unit tests assert that
the hello packet and both command bodies agree.  k5web sends ``FF FF FF FF``
for both its handshake and its commands and is equally self consistent;
mixing the two makes every read and write after the handshake fail silently.

CHANNEL NAMES
-------------
These builds store names as plain GB2312 double byte characters - first byte
>= 0xA1, glyph looked up by classic GB2312 code order
(``ui/helper.c:246-253``) - which the capture confirms on real hardware.
The field is 16 bytes but the radio's own menu only edits
``MAX_EDIT_INDEX`` of them, 13 for these builds (``font.h:28``), so that is
``valid_name_length``.  A name that does not fit the field at all is
rejected; a name that fits the field but is longer than the editor limit is
kept as it is (real radios carry them) and is left byte for byte alone if
the user only edits something else on that channel.

EEPROM SIZE AND WRITE SAFETY
----------------------------
The size comes from, in order: the loaded image, the profile default, and
the user's "EEPROM size" setting.  The default for every profile this driver
claims is 0x40000: a live scan of the reference radio (stride 0x8000 over
0..0x100000) shows user data at 0x00000-0x02FFF including the pinyin area at
0x20000, mostly erased bytes at 0x030000-0x03FFFF, and the multi-bootloader
from 0x040000 ("_BL002" at 0x40008), with the space aliasing with a period
of 0x80000 above that.

The 0x040000-0x07FFFF region is the multi-bootloader that some of these
builds install, and a stray write into it can leave the radio unbootable in
a way CHIRP cannot repair - the one place where the Chinese firmware is
strictly more dangerous than an OEM UV-K5.  So nothing at or above
``DATA_LIMIT`` is ever read or written, an image that extends into it is
refused, and a normal upload only writes ``PROG_SIZE`` (0x1d00) bytes at
all, which means the fonts, the welcome text, the FM broadcast presets, the
pinyin blobs and the bootloader region are preserved by never being written.

VERIFICATION STATUS
-------------------
Verified against a real radio (LOSEHU131HS, 2026-10-13, Prolific PL2303GS
on COM9): the hello handshake and its version string, both EEPROM read
command pairs including 0x2B addressing past 0x10000 where the stock 0x1B
command wraps at 0xFFFF, the channel record fields, the channel attribute
bytes and the GB2312 name encoding (channel 1 of the capture reads
435.5875 MHz simplex with the name "私有频点"), the write command 0x38 at a
low address and at 0x01E1E8 (the 32 bit path), a whole-image write and
read-back that differed in 0 bytes, and determinism across dump sessions.

NOT verified on a real radio: CHIRP's own clone path end to end, and the
region above PROG_SIZE, which this driver never writes.  Other builds in this
family are handled by the follow-up work noted in the pull request rather
than by guessing here; radios this driver does not claim are offered as
read-only images.
"""

import logging
import re
import struct

from chirp import chirp_common, directory, bitwise, errors
from chirp.drivers import uvk5
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

# Only the three arrays this driver models, built on the definitions shared
# with the base driver so that the channel record, the attributes and the
# name array cannot drift apart from it.
MEM_FORMAT = uvk5.MEM_DEFS + """
#seekto 0x0000;
struct memory channel[214];

#seekto 0xd60;
struct channel_attributes channel_attributes[200];

#seekto 0xf50;
struct channelname channelname[200];
"""

# The firmware stores the hello command's timestamp and drops any later
# command that carries a different one (see the module docstring).  These are
# the same four bytes uvk5._sayhello() sends, so the handshake and our
# commands always agree.
TIMESTAMP = b'\x6a\x39\x57\x64'

# Highest EEPROM address this driver will ever read or write.  0x040000 and
# above is the multi-bootloader on these builds (see the module docstring).
DATA_LIMIT = 0x40000

# Size of the channel name field on disk, and how many bytes of it the
# radio's own menu will store (font.h:28, ENABLE_CHINESE_FULL == 4).
NAME_LENGTH = 16
NAME_BYTES = 13

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

# Ordered firmware regular expression -> profile name -> EEPROM size in
# bytes, transcribed from k5web navbar/index.vue:230-254 (which matches with
# RegExp.test(), i.e. an unanchored search, and keeps the first match).
#
# Only the profiles that this driver implements are listed here.  The rest of
# k5web's table - the stock 0x1B/0x1D builds (losehu117, losehu118, lts) and
# the font-mapped builds (losehu117k, ltsk and the LTS sub-font builds) - is
# deliberately left out: they take different code paths that no capture here
# exercises, so they fall through to the read-only fallback below.  See the
# follow-up work noted in the pull request.
#
# The version string comes from the radio's hello reply (command 0x0514,
# reply 0x0515, offset 4, up to 16 ASCII bytes: app/uart.c:76,206-220) and is
# the build's PACKED_FILE_SUFFIX (version.h:27, version.c:22, Makefile:309) -
# NOT the ``*OEFW-<author>`` flash header that fw-pack.py inserts at 0x2000,
# which must never be allowlisted.
#
# Sizes: every profile here is an expanded build, and a live scan of the
# reference radio shows user data ending before 0x40000 with the
# multi-bootloader starting there, so 0x40000 is the sensible default.
CN_PROFILES = (
    (r'L_BL[0-9][0-9][0-9]', 'losehubl', 0x40000),
    (r'LOSEHU.*D', 'losehud', 0x40000),
    (r'UVE.*', 'losehu124h', 0x40000),
    (r'LOSEHU13[0-9].*HS', 'losehu124h', 0x40000),
    (r'LOSEHU13[0-9].*H', 'losehu124h', 0x40000),
    (r'LOSEHU13[0-9].*KS', 'losehu120k', 0x40000),
    (r'LOSEHU13[0-9].*K', 'losehu120k', 0x40000),
    (r'LOSEHU12[4-9].*HS', 'losehu124h', 0x40000),
    (r'LOSEHU12[4-9].*H', 'losehu124h', 0x40000),
    (r'LOSEHU12[0-3].*H', 'losehu118h', 0x40000),
    (r'LOSEHU12[0-9].*KS', 'losehu120k', 0x40000),
    (r'LOSEHU12[0-9].*K', 'losehu120k', 0x40000),
    (r'LOSEHU11[8-9].*H', 'losehu118h', 0x40000),
    (r'LOSEHU11[8-9].*K', 'losehu118k', 0x40000),
    # Any other LOSEHU1xx build: recognised, but not claimed, so it comes up
    # as a read-only image instead of being driven on a guess.
    (r'LOSEHU1[0-9][0-9].*', 'todo', 0x2000),
    # The UV-K1 is a different radio, handled by uvk5.UVK1Radio.
    (r'7\..*', 'k1', 0x2000),
    (r'.*', 'todo', 0x2000),
)

# Tuning steps offered by these firmwares; the channel record stores the
# index into this list in a whole byte.  Transcribed from k5web
# search-table/index.vue (stepOption); 24 entries, which is also
# STEP_N_ELEM in the firmware (frequencies.h:45-73).
CN_STEPS = (2.50, 5.00, 6.25, 10.00, 12.50, 25.00, 8.33, 0.01, 0.05, 0.10,
            0.25, 0.50, 1.00, 1.25, 9.00, 15.00, 20.00, 30.00, 50.00, 100.00,
            125.00, 200.00, 250.00, 500.00)

# Band edges used by k5web to pick the band byte it stores in the channel
# attributes (search-table/index.vue freqRange, and the reduce/indexOf pair
# on write): the index of the highest edge below the RX frequency.  These are
# the firmware's own boundaries (frequencies.c:37-44).
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


def _encode_char(char):
    try:
        return char.encode('gb2312')
    except UnicodeEncodeError:
        return b'?'


def encode_name_prefix(name, limit=NAME_BYTES):
    """Encode as many characters of @name as fit in @limit bytes.

    A two byte character is never cut in half.
    """
    out = bytearray()
    for char in name:
        encoded = _encode_char(char)
        if len(out) + len(encoded) > limit:
            break
        out += encoded
    return bytes(out)


def encode_name(name, limit=NAME_BYTES):
    """Encode @name into exactly NAME_LENGTH bytes, NUL padded."""
    return encode_name_prefix(name, limit).ljust(NAME_LENGTH, b'\x00')


def name_fits(name, limit=NAME_LENGTH):
    """True if every character of @name fits in @limit bytes."""
    return len(b''.join(_encode_char(char) for char in name)) <= limit


def decode_name(raw):
    """Decode a NAME_LENGTH byte GB2312 channel name field.

    Mirrors k5web serial.js uint8ArrayToString() and the firmware's own
    convention (``settings.c:414-417``: NUL terminated, trailing spaces
    trimmed by the caller): the name ends at 0x00 or 0xFF; a byte >= 0x80
    starts a two byte character, and if the field ends in the middle of one -
    or the pair is not valid GB2312 - the rest of the name is still decoded
    instead of being dropped.
    """
    out = []
    index = 0
    raw = bytes(raw)
    while index < len(raw):
        byte = raw[index]
        if byte in (0x00, 0xFF):
            break
        if byte < 0x80:
            out.append(chr(byte))
            index += 1
            continue
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

    Layout from k5web serial.js:1458 and the firmware's CMD_052B
    (``app/uart.c:578-604``), including the timestamp rule above.
    """
    return b'\x2b\x05\x08\x00' + \
        struct.pack('<HBB', (offset >> 16) & 0xffff, length, 0) + \
        TIMESTAMP + \
        struct.pack('<H', offset & 0xffff)


def writemem_command(offset, data):
    """Build the alternate EEPROM write command (0x38) for @offset.

    Layout per the firmware's own CMD_0538 (``app/uart.c:614-649``): ID,
    header size, address bits 16-31, size, bAllowPassword, timestamp, then
    the data whose first two bytes are address bits 0-15.  The header size
    counts everything after the four byte header, so it is 10 + len(data);
    k5web hardcodes 0x1c there (``serial.js:1552``) and the firmware
    tolerates that, but the computed value is what the firmware documents.
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
    # The firmware does not appear to validate the request's size field (the
    # reference radio answers with 0x08 and with 0x0A alike), so the reply's
    # size byte is only reported, never asserted on.
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


@directory.register
@directory.detected_by(uvk5.UVK5Radio)
class UVK5LoseHuRadio(uvk5.UVK5RadioBase):
    """Quansheng UV-K5/K6 with expanded Chinese firmware"""

    VENDOR = "Quansheng"
    MODEL = "UV-K5"
    VARIANT = "losehu"
    BAUD_RATE = 38400

    # Reads use 0x80, the largest reply the firmware's reply structure can
    # carry (``app/uart.c:100-108``).  Writes use 0x40: the firmware's
    # receive buffer would take 0x80 (``app/uart.c:24,172``) but 0x40 is
    # what k5web uses on every write path (``serial.js:1534``) and what has
    # been exercised on hardware.  0x1d00 is a multiple of 0x40, so there is
    # never a short final chunk.
    #
    # PROG_SIZE stops before the calibration area at 0x1E00
    # (settings.c:314,319,323,332,333,352; the AES key is at 0x0F30,
    # settings.c:294-297), which is unique per radio; everything this driver
    # maps lives below 0x1D00 anyway.
    MEM_BLOCK = 0x80
    WRITE_BLOCK = 0x40
    PROG_SIZE = 0x1d00
    DEFAULT_MEM_SIZE = 0x2000

    # Clone geometry that uvk5.do_download()/do_upload() pick up from the
    # radio class instead of the module constants, so the clone loop does not
    # have to be copied here.
    read_block = MEM_BLOCK
    write_block = WRITE_BLOCK
    prog_size = PROG_SIZE

    @property
    def mem_size(self):
        """How much EEPROM the clone loops should cover."""
        return self.eeprom_size

    # Profiles this class answers for.  The rest of k5web's table stays out
    # of this class on purpose (see CN_PROFILES).
    _CN_PROFILES = frozenset((
        'losehubl', 'losehu118h', 'losehu118k', 'losehu120k', 'losehu124h',
        'losehud'))

    _steps = CN_STEPS
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
            'running expanded Chinese third-party firmware (LOSEHU, LTS, '
            'UVE), which store channel names as GB2312 and use the split '
            'address EEPROM commands.\n\n'
            'It has been verified against one such radio, a LOSEHU131HS '
            'build: downloading, uploading and a whole-image read-back were '
            'checked there. Other builds in this family may behave '
            'differently, and a wrong write can harm your radio. Use at your '
            'own risk, and keep the image you download before changing '
            'anything: it can be used to restore the radio.\n\n'
            '- Writing at or above 0x40000 would overwrite the '
            'multi-bootloader that some of these builds install there, so '
            'this driver never writes that high and refuses an image that '
            'extends into it.\n'
            '- The default EEPROM size is derived from the reported firmware '
            'version and is only a guess; check the "EEPROM size" setting '
            'against your radio before uploading.\n'
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
        firmware on the radio decides, and the user can override it with the
        "EEPROM size" setting.
        """
        if self._eeprom_size:
            return self._eeprom_size
        return profile_mem_size(self.metadata.get('uvk5_firmware', ''))

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
        # The stock driver exposes 14 VFO channels above channel 200, modelled
        # as 16 byte records.  These firmwares store them as 32 byte records
        # at 0x0C80 (``settings.c:681-682``), which no capture here
        # exercises, so they are not offered.
        return {}

    def get_features(self):
        rf = super().get_features()
        rf.valid_special_chans = []
        rf.valid_name_length = NAME_BYTES
        rf.valid_characters = gb2312_charset()
        rf.valid_tuning_steps = list(self._steps)
        rf.valid_bands = self._get_valid_bands()
        return rf

    def process_mmap(self):
        self._check_firmware_at_load()
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        # The image tells us how much EEPROM was actually read
        self._eeprom_size = len(self._mmap)

    def _check_download_size(self, size):
        if size > DATA_LIMIT:
            raise errors.RadioError(
                _('The EEPROM size is set to 0x%(size)x bytes, but this '
                  'driver only reads below 0x%(limit)x; 0x%(limit)x and '
                  'above is the multi-bootloader on these firmwares. '
                  'Correct the "EEPROM size" setting.') % {
                    'size': size, 'limit': DATA_LIMIT})

    def _check_upload_image(self, image_size, firmware):
        if self.eeprom_size > DATA_LIMIT:
            raise errors.RadioError(
                _('The EEPROM size is set to 0x%(size)x bytes, but this '
                  'driver only writes below 0x%(limit)x; 0x%(limit)x and '
                  'above is the multi-bootloader on these firmwares. '
                  'Correct the "EEPROM size" setting.') % {
                    'size': self.eeprom_size, 'limit': DATA_LIMIT})
        if image_size > DATA_LIMIT:
            raise errors.RadioError(
                _('Image is %(image)i bytes, but this driver only writes '
                  'below 0x%(limit)x; 0x%(limit)x and above is the '
                  'multi-bootloader on these firmwares and writing there '
                  'can destroy the radio. Use an image that stops before '
                  'it.') % {'image': image_size, 'limit': DATA_LIMIT})
        if image_size != self.eeprom_size:
            image_fw = self.metadata.get('uvk5_firmware', '')
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
                      'size': self.eeprom_size})

    def _read_mem_block(self, serport, offset, length):
        # These builds answer the alternate 0x2B read command, which carries
        # the handshake timestamp, instead of the stock 0x1B one
        return _readmem(serport, offset, length)

    def _write_mem_block(self, serport, data, offset):
        return _writemem(serport, data, offset)

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

    def _decode_name(self, raw):
        # The base class decodes names as latin-1; these builds store GB2312,
        # and the field can also end in the middle of a two byte character, so
        # decode_name() walks it rather than handing it to a plain codec.
        return decode_name(raw).rstrip()

    def _store_name(self, number, name, original):
        """Store @name in the name field of channel @number.

        @original is the field as it was before the base class wrote its
        placeholder.  If the name we can decode is unchanged, those bytes are
        put back exactly as they were, so that a name this driver cannot
        represent - or an unused name slot - is never rewritten just because
        the user changed something else on that channel.
        """
        if original != b'\xff' * NAME_LENGTH and \
                decode_name(original).rstrip() == name.rstrip():
            self._memobj.channelname[number].set_raw(original)
            return
        self._memobj.channelname[number].set_raw(encode_name(name))

    def _already_empty(self, number):
        """True if channel @number is already in an "empty" spelling.

        The radio leaves an untouched channel's record, name and attribute at
        0xFF, while CHIRP writes 0x00/0x0F when it clears one; both mean
        "empty".  Recognising the former lets a round trip leave the bytes
        alone instead of respelling them.
        """
        record = bytes(self._memobj.channel[number].get_raw())
        name = bytes(self._memobj.channelname[number].get_raw())
        if record not in (b'\xff' * NAME_LENGTH, b'\x00' * NAME_LENGTH):
            return False
        if name not in (b'\xff' * NAME_LENGTH, b'\x00' * NAME_LENGTH):
            return False
        return bool(int(self._memobj.channel_attributes[number].is_free))

    def set_memory(self, mem):
        if mem.empty or not isinstance(mem.number, int) or mem.number > 200:
            if mem.empty and isinstance(mem.number, int) and \
                    mem.number <= 200 and self._already_empty(mem.number - 1):
                # Nothing to do: the bytes already say "empty"
                return mem
            return super().set_memory(mem)

        number = mem.number - 1
        original = bytes(self._memobj.channelname[number].get_raw())

        # The base class writes the name through a str, which cannot hold a
        # GB2312 name, so hand it a placeholder and write the real bytes
        # afterwards.
        proxy = mem.dupe()
        proxy.name = ''
        super().set_memory(proxy)
        self._store_name(number, mem.name, original)
        return mem

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        if mem.empty or not isinstance(mem.number, int):
            return msgs

        # A name that does not fit the field cannot be stored at all.  A name
        # that fits the field but is longer than the radio's own editor limit
        # is not reported: real radios carry them and this driver preserves
        # them byte for byte (see _store_name).
        if not name_fits(mem.name, NAME_LENGTH):
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
