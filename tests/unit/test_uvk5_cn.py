# Copyright 2026 赵昕 BG8ADW
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

"""Unit tests for the Chinese firmware UV-K5 driver (chirp.drivers.uvk5_cn).

These tests need no radio and no serial port.  The image in
tests/images/Quansheng_UV-K5_losehu.img is a REAL 256 KiB (0x40000) capture
from a UV-K5 running a LOSEHU131HS build (2026-10-13, Prolific PL2303GS on
COM9); only the CHIRP metadata trailer was added to it.

The driver uses the gettext builtin ``_``, which the GUI installs and the
driver test suite sets up in tests/test_drivers.py; do the same here.
"""

import os
import struct
import unittest
from unittest import mock

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.drivers import uvk5, uvk5_cn

__builtins__['_'] = lambda s: s

IMAGE = os.path.join(os.path.dirname(__file__), '..', 'images',
                     'Quansheng_UV-K5_losehu.img')

# The real radio this image came from
FIRMWARE = 'LOSEHU131HS'
EEPROM_SIZE = 0x40000
# First unused channel in the capture (its record and name slot are all 0xFF)
FIRST_EMPTY = 98
# Name of channel 1 in the capture, GB2312 "private frequency"
CH1_NAME = '\u79c1\u6709\u9891\u70b9'
CH1_FREQ = 435587500


class FakeSerial:
    """Minimal clone of the serial object the framing layer needs."""

    def __init__(self, response=b'', fail_after=None):
        self.written = []
        self.buffer = bytearray(response)
        self.timeout = None
        self.fail_after = fail_after
        self.reads = 0

    def log(self, message):
        pass

    def write(self, data):
        if not isinstance(data, bytes):
            raise TypeError('driver wrote non-bytes to the serial port')
        self.written.append(data)

    def read(self, size=None):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise errors.RadioError('fake serial stopped answering')
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data


def make_reply(payload):
    """Wrap @payload in the radio's reply frame."""
    # _receive_reply() does not verify the CRC that follows the payload
    return (b'\xab\xcd' + struct.pack('>BB', len(payload), 0) +
            uvk5.xorarr(payload + b'\x12\x34') + b'\xdc\xba')


def unframe(frame):
    """Undo the framing of a command the driver sent and return its payload."""
    assert frame[:2] == b'\xab\xcd', 'bad magic'
    assert frame[-2:] == b'\xdc\xba', 'bad footer'
    length = frame[2]
    body = frame[4:-2]
    assert len(body) == length + 2, 'bad obfuscated length'
    return uvk5.xorarr(body)[:length]


def padded(data):
    return bytes(data).ljust(uvk5_cn.NAME_LENGTH, b'\x00')


def attr_byte(radio, index):
    """Recompose the channel attribute byte for @index.

    bit7 = scanlist I, bit6 = scanlist II, bits4-5 = compander,
    bit3 = is_free, bits0-2 = band.
    """
    attr = radio._memobj.channel_attributes[index]
    return ((int(attr.is_scanlist1) << 7) |
            (int(attr.is_scanlist2) << 6) |
            (int(attr.compander) << 4) |
            (int(attr.is_free) << 3) |
            int(attr.band))


def split_msgs(msgs):
    return chirp_common.split_validation_msgs(msgs)


class TestTimestamp(unittest.TestCase):
    """Every command must carry the hello packet's timestamp.

    The firmware stores the four byte timestamp of the hello command and
    silently drops any later command that carries a different one - no
    reply, no error, indistinguishable from a dead radio:
    ``app/uart.c:243`` stores it, ``app/uart.c:264`` (CMD_051B), ``:298``
    (CMD_051D), ``:584`` (CMD_052B) and ``:613`` (CMD_0538) all return
    early on a mismatch.  A driver that handshakes with one value and then
    sends another reads nothing at all.
    """

    def hello_timestamp(self):
        """Run the real uvk5._sayhello() and decode what it sent."""
        payload = bytes([0x15, 0x05, 0x24, 0x00]) + \
            b'k5_2.01.23\x00' + b'\x00' * 14
        serport = FakeSerial(make_reply(payload))
        self.assertEqual('k5_2.01.23', uvk5._sayhello(serport))
        hello = unframe(serport.written[0])
        self.assertEqual(b'\x14\x05\x04\x00', hello[:4])
        return hello[4:8]

    def test_hello_timestamp_matches_our_commands(self):
        timestamp = self.hello_timestamp()
        self.assertEqual(timestamp, uvk5_cn.TIMESTAMP)
        self.assertEqual(timestamp,
                         uvk5_cn.readmem_command(0x2024, 0x80)[8:12])
        self.assertEqual(timestamp,
                         uvk5_cn.writemem_command(0x2000, b'\x00' * 8)[8:12])

    def test_stock_commands_use_the_same_timestamp(self):
        """The non extended class delegates to uvk5's own commands, which
        must therefore agree with the same hello packet."""
        timestamp = self.hello_timestamp()
        data = bytes(range(8))
        reply = make_reply(bytes([0x1c, 0x05, 0x0a, 0x00, 0x00, 0x00,
                                  0x08, 0x00]) + data)
        serport = FakeSerial(reply)
        self.assertEqual(data, uvk5._readmem(serport, 0x0000, 0x08))
        self.assertEqual(timestamp, unframe(serport.written[0])[8:12])

        serport = FakeSerial(make_reply(bytes([0x1e, 0x05, 0x00, 0x00,
                                               0x00, 0x00])))
        self.assertTrue(uvk5._writemem(serport, data, 0x0000))
        self.assertEqual(timestamp, unframe(serport.written[0])[8:12])


class TestCommandSyntax(unittest.TestCase):
    """Byte exact checks of the EEPROM command bodies.

    The expected bytes are written out by hand from k5web
    src/utils/serial.js eeprom_read (line 1458) and eeprom_write (line 1552)
    and from the firmware's own CMD_0538 (app/uart.c:614-649), so that a
    change in the driver cannot silently change the protocol.
    """

    def test_read_command_low_address(self):
        # [0x2b, 0x05, 0x08, 0x00, addr>>16 LE, size, 0x00,
        #  timestamp x4, addr&0xffff LE]
        expected = bytes([
            0x2b, 0x05, 0x08, 0x00,
            0x00, 0x00,              # address bits 16..31
            0x80,                    # size
            0x00,
        ]) + uvk5_cn.TIMESTAMP + bytes([
            0x24, 0x20,              # address bits 0..15 = 0x2024
        ])
        self.assertEqual(expected, uvk5_cn.readmem_command(0x2024, 0x80))

    def test_read_command_high_address(self):
        expected = bytes([
            0x2b, 0x05, 0x08, 0x00,
            0x01, 0x00,              # address bits 16..31 = 0x0001
            0x80,
            0x00,
        ]) + uvk5_cn.TIMESTAMP + bytes([
            0xf8, 0xff,              # address bits 0..15 = 0xFFF8
        ])
        self.assertEqual(expected,
                         uvk5_cn.readmem_command(0x01fff8, 0x80))

    def test_write_command(self):
        data = bytes(range(0x10))
        expected = bytes([
            0x38, 0x05,
            0x1a, 0x00,              # header size = 10 + len(data) = 0x1a
            0x00, 0x00,              # address bits 16..31
            0x10 + 2,                # size + the two address bytes
            0x00,
        ]) + uvk5_cn.TIMESTAMP + bytes([
            0x00, 0x20,              # address bits 0..15 = 0x2000
        ]) + data
        self.assertEqual(expected, uvk5_cn.writemem_command(0x2000, data))

    def test_write_command_high_address(self):
        data = b'\xaa' * 4
        expected = bytes([
            0x38, 0x05,
            0x0e, 0x00,              # header size = 10 + 4
            0x01, 0x00,              # address bits 16..31 = 0x0001
            0x04 + 2,
            0x00,
        ]) + uvk5_cn.TIMESTAMP + bytes([
            0x00, 0x00,
        ]) + data
        self.assertEqual(expected,
                         uvk5_cn.writemem_command(0x010000, data))

    def test_write_header_size_matches_the_firmware_formula(self):
        # app/uart.c:614-649 counts everything after the four byte header:
        # two high address bytes, size, bAllowPassword, four timestamp
        # bytes, two low address bytes and the payload
        for length in (8, 0x10, 0x40, 0x80):
            command = uvk5_cn.writemem_command(0x1234, b'\x00' * length)
            self.assertEqual(10 + length,
                             struct.unpack('<H', command[2:4])[0], length)
            self.assertEqual(length + 2, command[6], length)
            # payload must be a whole number of the firmware's write units
            self.assertEqual(0, length % 8, length)

    def test_write_geometry(self):
        cls = uvk5_cn.UVK5CNLoseHuRadio
        self.assertEqual(0x80, cls.MEM_BLOCK)        # reply structure limit
        self.assertEqual(0x40, cls.WRITE_BLOCK)      # k5web verified size
        self.assertEqual(0, cls.WRITE_BLOCK % 8)     # firmware write unit
        self.assertEqual(0, cls.PROG_SIZE % cls.WRITE_BLOCK)
        self.assertEqual(0x1d00, cls.PROG_SIZE)

    def test_writemem_sends_exactly_that_frame(self):
        data = bytes(range(0x80))
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])))
        self.assertTrue(uvk5_cn._writemem(serport, data, 0x2000))
        self.assertEqual(1, len(serport.written))
        self.assertEqual(uvk5_cn.writemem_command(0x2000, data),
                         unframe(serport.written[0]))

    def test_readmem_sends_exactly_that_frame(self):
        data = bytes(range(0x80))
        payload = bytes([0x1c, 0x05, 0x0a, 0x00, 0x24, 0x20, 0x80, 0x00])
        serport = FakeSerial(make_reply(payload + data))
        self.assertEqual(data, uvk5_cn._readmem(serport, 0x2024, 0x80))
        self.assertEqual(1, len(serport.written))
        # Decode what actually went out on the wire and compare to the
        # command built by hand above
        self.assertEqual(uvk5_cn.readmem_command(0x2024, 0x80),
                         unframe(serport.written[0]))

    def test_writemem_rejects_bad_reply(self):
        serport = FakeSerial(make_reply(bytes([0x00, 0x05])))
        with self.assertRaises(errors.RadioError):
            uvk5_cn._writemem(serport, b'\x00' * 8, 0x0000)

    def test_readmem_rejects_short_reply(self):
        serport = FakeSerial(make_reply(bytes([0x1c, 0x05, 0x0a, 0x00])))
        with self.assertRaises(errors.RadioError):
            uvk5_cn._readmem(serport, 0x0000, 0x80)

    def test_stock_command_used_for_ascii_variant(self):
        """The 117/118/LTS builds keep the stock 0x1b/0x1d commands."""
        self.assertFalse(uvk5_cn.UVK5CNRadio.USE_EXTENDED_EEPROM)
        self.assertTrue(uvk5_cn.UVK5CNLoseHuRadio.USE_EXTENDED_EEPROM)
        # 0x10000 for the 16 bit pair; for the split address pair the ceiling
        # is the chip's aliasing period: the reference radio reads 0x080000
        # as a byte-identical copy of 0x000000, i.e. a 19 bit effective
        # address on a 4 Mibit part.
        self.assertEqual(0x10000, uvk5_cn.UVK5CNRadio.MAX_ADDRESSABLE)
        self.assertEqual(0x80000,
                         uvk5_cn.UVK5CNLoseHuRadio.MAX_ADDRESSABLE)
        payload = bytes([0x1c, 0x05, 0x0a, 0x00, 0x00, 0x00, 0x08, 0x00])
        data = bytes(range(8))
        serport = FakeSerial(make_reply(payload + data))
        self.assertEqual(data, uvk5._readmem(serport, 0x0000, 0x08))


class TestNameCodec(unittest.TestCase):

    def test_ascii_round_trip(self):
        self.assertEqual(padded(b'CALL'), uvk5_cn.encode_name('CALL'))
        self.assertEqual('CALL', uvk5_cn.decode_name(padded(b'CALL')))

    def test_real_radio_gb2312_name(self):
        """The name of channel 1 of the real capture."""
        name = '\u79c1\u6709\u9891\u70b9'          # "private frequency"
        raw = b'\xcb\xbd\xd3\xd0\xc6\xb5\xb5\xe3' + b'\x00' * 8
        self.assertEqual(name, uvk5_cn.decode_name(raw))
        self.assertEqual(raw, uvk5_cn.encode_name(name))
        self.assertTrue(uvk5_cn.name_fits(name, 13))

    def test_full_width_name(self):
        name = 'ABCDEFGHIJKLMNOP'
        self.assertEqual(16, len(name))
        self.assertTrue(uvk5_cn.name_fits(name))
        self.assertEqual(name.encode('ascii'), uvk5_cn.encode_name(name))
        self.assertEqual(name, uvk5_cn.decode_name(
            uvk5_cn.encode_name(name)))

    def test_gb2312_round_trip(self):
        name = '\u4e2d\u7ee7'                      # "repeater"
        self.assertEqual(padded(b'\xd6\xd0\xbc\xcc'),
                         uvk5_cn.encode_name(name))
        self.assertEqual(name, uvk5_cn.decode_name(
            uvk5_cn.encode_name(name)))
        self.assertTrue(uvk5_cn.name_fits(name))

    def test_empty_name_all_ff(self):
        self.assertEqual('', uvk5_cn.decode_name(b'\xff' * 16))

    def test_empty_name_all_nul(self):
        self.assertEqual('', uvk5_cn.decode_name(b'\x00' * 16))
        self.assertEqual(padded(b''), uvk5_cn.encode_name(''))

    def test_name_stops_at_ff(self):
        raw = b'AB' + b'\xff' * 14
        self.assertEqual('AB', uvk5_cn.decode_name(raw))

    def test_field_ends_mid_character(self):
        """The whole name must not be lost when the field is cut short."""
        raw = b'AB\xd6\xd0\xb9' + b'\x00' * 11
        self.assertEqual('AB\u4e2d', uvk5_cn.decode_name(raw))

    def test_field_ends_on_dangling_lead_byte(self):
        raw = b'A' * 15 + b'\xd6'
        self.assertEqual('A' * 15, uvk5_cn.decode_name(raw))

    def test_dangling_lead_byte_then_ff(self):
        raw = b'AB\xd6\xff' + b'\x00' * 12
        self.assertEqual('AB', uvk5_cn.decode_name(raw))

    def test_invalid_gb2312_pair(self):
        # 0x80 is not a valid GB2312 lead byte
        raw = b'A\x80\x40B' + b'\x00' * 12
        self.assertEqual('A?B', uvk5_cn.decode_name(raw))

    def test_official_charset_stops_at_high_byte(self):
        raw = b'AB\xd6\xd0' + b'\x00' * 12
        self.assertEqual('AB', uvk5_cn.decode_name(raw, 'official'))
        self.assertEqual('AB\u4e2d',
                         uvk5_cn.decode_name(raw, 'gb2312'))

    def test_name_longer_than_field_is_truncated_on_char_boundary(self):
        name = '\u4e2d' * 9                        # 18 bytes
        self.assertFalse(uvk5_cn.name_fits(name))
        encoded = uvk5_cn.encode_name(name)
        self.assertEqual(16, len(encoded))
        # 16 bytes / 2 bytes per character, and never a half character
        self.assertEqual('\u4e2d' * 8, uvk5_cn.decode_name(encoded))

    def test_ascii_name_longer_than_field(self):
        name = 'X' * 17
        self.assertFalse(uvk5_cn.name_fits(name))
        self.assertEqual(padded(b'X' * 16), uvk5_cn.encode_name(name))

    def test_mixed_name_never_splits_character(self):
        # 14 ASCII bytes leaves room for one 2 byte character, not two
        name = 'A' * 15 + '\u4e2d'
        self.assertFalse(uvk5_cn.name_fits(name))
        encoded = uvk5_cn.encode_name(name)
        self.assertEqual(16, len(encoded))
        self.assertEqual('A' * 15, uvk5_cn.decode_name(encoded))

    def test_unencodable_character_becomes_question_mark(self):
        raw = uvk5_cn.encode_name('\u20ac')        # not in GB2312
        self.assertEqual(padded(b'?'), raw)

    def test_gb2312_charset_is_usable(self):
        charset = uvk5_cn.gb2312_charset()
        self.assertIn('A', charset)
        self.assertIn('\u4e2d', charset)
        self.assertNotIn('\x00', charset)
        # every character offered must actually encode
        for char in ('A', 'z', '0', '\u4e2d', '\u7ee7'):
            self.assertIn(char, charset)

    def test_encode_honours_the_firmware_limit(self):
        # 10 bytes is what a build without the Chinese font will store
        # (font.h:30)
        self.assertEqual(b'X' * 10 + b'\x00' * 6,
                         uvk5_cn.encode_name('X' * 16, 10))
        self.assertTrue(uvk5_cn.name_fits('X' * 10, 10))
        self.assertFalse(uvk5_cn.name_fits('X' * 11, 10))
        # 13 bytes for ENABLE_CHINESE_FULL == 4 builds (font.h:28)
        self.assertEqual(b'X' * 13 + b'\x00' * 3,
                         uvk5_cn.encode_name('X' * 16, 13))
        self.assertTrue(uvk5_cn.name_fits('X' * 13, 13))
        self.assertFalse(uvk5_cn.name_fits('X' * 14, 13))
        # Five two byte characters fit in 10 bytes, six do not
        self.assertTrue(uvk5_cn.name_fits('\u4e2d' * 5, 10))
        self.assertFalse(uvk5_cn.name_fits('\u4e2d' * 6, 10))
        # ... and the character is never split at the limit
        self.assertEqual('\u4e2d' * 5,
                         uvk5_cn.decode_name(
                             uvk5_cn.encode_name('\u4e2d' * 9, 10)))


class TestFirmwareProfiles(unittest.TestCase):
    """The profile table must mirror k5web navbar/index.vue:230-254."""

    def test_first_match_wins(self):
        # LOSEHU118H must not fall through to the plain 118 profile
        self.assertEqual('losehu118h', uvk5_cn.cn_profile('LOSEHU118H'))
        self.assertEqual('losehu118', uvk5_cn.cn_profile('LOSEHU118'))
        # k5web maps 124K onto the 120k profile: there is no 124K entry
        self.assertEqual('losehu120k', uvk5_cn.cn_profile('LOSEHU124K'))
        self.assertEqual('losehu124h', uvk5_cn.cn_profile('LOSEHU124HS'))
        self.assertEqual('losehu118h', uvk5_cn.cn_profile('LOSEHU120H'))
        self.assertEqual('losehu117k', uvk5_cn.cn_profile('LOSEHU117K'))
        self.assertEqual('losehu117', uvk5_cn.cn_profile('LOSEHU115'))
        self.assertEqual('losehubl', uvk5_cn.cn_profile('L_BL001'))
        self.assertEqual('losehud', uvk5_cn.cn_profile('LOSEHUD'))
        self.assertEqual('lts', uvk5_cn.cn_profile('LOSEHU13P'))
        self.assertEqual('ltsk', uvk5_cn.cn_profile('LOSEHU13PK'))
        self.assertEqual('losehu124h', uvk5_cn.cn_profile('UVE5'))
        self.assertEqual('k1', uvk5_cn.cn_profile('7.03.01'))
        self.assertEqual('todo', uvk5_cn.cn_profile('k5_2.01.23'))

    def test_profile_is_unanchored_like_javascript(self):
        # RegExp.test() searches anywhere in the string
        self.assertEqual('losehu118h', uvk5_cn.cn_profile('xxLOSEHU118Hxx'))

    def test_evidence_backed_version_strings(self):
        """PACKED_FILE_SUFFIX values the firmware can actually report.

        See firmware_structs.md: version.h:27 / version.c:22 / Makefile:309
        for the LTS tree and Makefile:76-115 for the LOSEHU tree.  k5web
        selects its profile from the same strings (navbar/index.vue:303-309).
        The last one is the version the reference radio actually reports.
        """
        cases = {
            'LOSEHU116': 'losehu117',        # LH tree, non-K
            'LOSEHU116K': 'losehu117k',      # LH tree, K
            'LOSEHU117P6': 'lts',            # LTS default, non-K
            'LOSEHU117P6K': 'ltsk',          # LTS default, K
            'LOSEHU126K': 'losehu120k',
            'LOSEHU133': 'losehu118',        # LH default, non-K
            'LOSEHU133K': 'losehu120k',      # LH default, K
            'LOSEHU133H': 'losehu124h',      # LH, pinyin build
            'LOSEHU133EK': 'losehu120k',
            'LOSEHU131HS': 'losehu124h',     # the reference radio
        }
        for firmware, profile in cases.items():
            self.assertEqual(profile, uvk5_cn.cn_profile(firmware), firmware)

    def test_unlisted_losehu_build_is_read_only(self):
        """Unknown LOSEHU1xx builds must not be made writable on a guess."""
        for firmware in ('LOSEHU140', 'LOSEHU140K', 'LOSEHU105'):
            self.assertEqual('todo', uvk5_cn.cn_profile(firmware), firmware)
            self.assertFalse(
                uvk5_cn.UVK5CNRadio.k5_approve_firmware(firmware))
            self.assertFalse(
                uvk5_cn.UVK5CNLoseHuRadio.k5_approve_firmware(firmware))

    def test_lts_font_bank_builds_are_read_only(self):
        """ENABLE_CHINESE_FULL 1/2/3 builds report no LOSEHU prefix."""
        for firmware in ('font1', 'font2', 'font3'):
            self.assertEqual('todo', uvk5_cn.cn_profile(firmware), firmware)
            self.assertFalse(
                uvk5_cn.UVK5CNLoseHuRadio.k5_approve_firmware(firmware))

    def test_oefw_flash_header_is_never_approved(self):
        """0x2000 holds '*OEFW-<author>' (fw-pack.py:28); it is not the
        version string and must never be allowlisted."""
        for firmware in ('*OEFW-LOSEHU', '*OEFW-'):
            self.assertEqual('todo', uvk5_cn.cn_profile(firmware), firmware)
            for cls in (uvk5_cn.UVK5CNRadio, uvk5_cn.UVK5CNLoseHuRadio):
                self.assertFalse(cls.k5_approve_firmware(firmware))
            self.assertFalse(uvk5.UVK5Radio.k5_approve_firmware(firmware))

    def test_k1_goes_to_the_upstream_uvk1_driver(self):
        self.assertEqual('k1', uvk5_cn.cn_profile('7.03.01'))
        self.assertFalse(
            uvk5_cn.UVK5CNLoseHuRadio.k5_approve_firmware('7.03.01'))
        self.assertFalse(
            uvk5_cn.UVK5CNRadio.k5_approve_firmware('7.03.01'))
        self.assertTrue(uvk5.UVK1Radio.k5_approve_firmware('7.03.01'))

    def test_approved_profiles(self):
        approve = uvk5_cn.UVK5CNLoseHuRadio.k5_approve_firmware
        for firmware in ('LOSEHU118H', 'LOSEHU118K', 'LOSEHU120K',
                         'LOSEHU124K', 'LOSEHU124H', FIRMWARE,
                         'L_BL001', 'LOSEHUD'):
            self.assertTrue(approve(firmware), firmware)

    def test_oem_firmware_is_not_approved(self):
        for firmware in ('k5_2.01.23', 'app_2.01.17', 'EGZUMER v1',
                         '7.03.01', '1o11'):
            self.assertFalse(
                uvk5_cn.UVK5CNLoseHuRadio.k5_approve_firmware(firmware))
            self.assertFalse(
                uvk5_cn.UVK5CNRadio.k5_approve_firmware(firmware))

    def test_font_mapped_profiles_are_claimed_by_the_font_class(self):
        """A radio whose names are font indices must not be written off.

        UVK5RestrictedRadio parses an image with the stock model, so an
        LTS-K radio would show wrong channels and no upload; claiming the
        profiles gives the user frequencies and tones even though the names
        cannot be interpreted.
        """
        self.assertIn('losehu117k', uvk5_cn.FONT_MAPPED_PROFILES)
        self.assertIn('ltsk', uvk5_cn.FONT_MAPPED_PROFILES)
        self.assertEqual(uvk5_cn.FONT_MAPPED_PROFILES,
                         uvk5_cn.UVK5CNFontRadio._CN_PROFILES)
        cases = {'LOSEHU117K': 'losehu117k',
                 'LOSEHU116K': 'losehu117k',
                 'LOSEHU13PK': 'ltsk',
                 'LOSEHU117P6K': 'ltsk'}
        for firmware, profile in cases.items():
            self.assertEqual(profile, uvk5_cn.cn_profile(firmware), firmware)
            self.assertTrue(
                uvk5_cn.UVK5CNFontRadio.k5_approve_firmware(firmware),
                firmware)
            # ... and not by the GB2312 class, which would mangle them
            self.assertFalse(
                uvk5_cn.UVK5CNLoseHuRadio.k5_approve_firmware(firmware))
            self.assertFalse(
                uvk5_cn.UVK5CNRadio.k5_approve_firmware(firmware))

    def test_eeprom_size_from_profile(self):
        # A live scan of the reference LOSEHU131HS radio shows real data at
        # 0x00000-0x02FFF (including the pinyin area at 0x20000), erased
        # bytes at 0x030000-0x03FFFF and the multi-bootloader from 0x040000
        # ("_BL002" at 0x40008), with the space aliasing above 0x80000.  So
        # every expanded profile defaults to 0x40000.
        for firmware in (FIRMWARE, 'LOSEHU117P6', 'LOSEHU117P6K',
                         'LOSEHU118H', 'LOSEHU124HS', 'LOSEHU124K',
                         'LOSEHU116K', 'UVE5', 'LOSEHUD', 'L_BL001'):
            self.assertEqual(0x40000, uvk5_cn.profile_mem_size(firmware),
                             firmware)
        # OEM sized builds and the catch-all
        for firmware in ('LOSEHU116', 'LOSEHU118', 'LOSEHU133', 'unknown',
                         'LOSEHU140'):
            self.assertEqual(0x2000, uvk5_cn.profile_mem_size(firmware),
                             firmware)

    def test_data_limit_is_the_bootloader_boundary(self):
        self.assertEqual(0x40000, uvk5_cn.DATA_LIMIT)
        # The driver only writes the channel region, far below it
        self.assertLess(uvk5_cn.UVK5CNLoseHuRadio.PROG_SIZE,
                        uvk5_cn.DATA_LIMIT)
        self.assertEqual(0x80000, uvk5_cn.UVK5CNLoseHuRadio.MAX_ADDRESSABLE)
        self.assertEqual(0x10000, uvk5_cn.UVK5CNRadio.MAX_ADDRESSABLE)

    def test_name_max_bytes_per_build(self):
        # font.h:28,30: MAX_EDIT_INDEX is 13 bytes for the builds with
        # ENABLE_CHINESE_FULL == 4 and 10 bytes otherwise
        for firmware in ('LOSEHU117K', 'LOSEHU116K', 'LOSEHU124K',
                         'LOSEHU117P6K', 'LOSEHU133H', FIRMWARE):
            self.assertEqual(13, uvk5_cn.name_max_bytes(firmware), firmware)
        for firmware in ('LOSEHU116', 'LOSEHU118', 'LOSEHU133',
                         'LOSEHU117P6', 'unknown', 'LOSEHU140'):
            self.assertEqual(10, uvk5_cn.name_max_bytes(firmware), firmware)


class TestDetection(unittest.TestCase):
    """Serial detection must pick the right class, and fall back safely."""

    def _detect(self, firmware):
        with mock.patch.object(uvk5, '_sayhello', return_value=firmware):
            return uvk5.UVK5Radio.detect_from_serial(object())

    def test_expanded_firmware(self):
        for firmware in ('LOSEHU118H', 'LOSEHU124K', 'LOSEHUD', 'L_BL001',
                         FIRMWARE):
            self.assertIs(uvk5_cn.UVK5CNLoseHuRadio,
                          self._detect(firmware))

    def test_ascii_firmware(self):
        for firmware in ('LOSEHU117', 'LOSEHU118', 'LOSEHU13P'):
            self.assertIs(uvk5_cn.UVK5CNRadio, self._detect(firmware))

    def test_unknown_firmware_is_read_only(self):
        # Anything we do not recognise must land on the restricted class
        for firmware in ('some new firmware', 'font1', 'font2', 'font3'):
            self.assertIs(uvk5.UVK5RestrictedRadio, self._detect(firmware))

    def test_font_mapped_firmware_uses_the_font_class(self):
        for firmware in ('LOSEHU117K', 'LOSEHU116K', 'LOSEHU117P6K',
                         'LOSEHU13PK'):
            self.assertIs(uvk5_cn.UVK5CNFontRadio, self._detect(firmware))

    def test_oem_firmware_still_uses_the_stock_driver(self):
        with mock.patch.object(uvk5, '_sayhello',
                               return_value='k5_2.01.23'):
            self.assertIs(uvk5.UVK5Radio,
                          uvk5.UVK5Radio.detect_from_serial(object()))

    def test_registry_lookup(self):
        self.assertIs(uvk5_cn.UVK5CNRadio,
                      directory.get_radio('Quansheng_UV-K5_cn'))
        self.assertIs(uvk5_cn.UVK5CNLoseHuRadio,
                      directory.get_radio('Quansheng_UV-K5_losehu'))
        self.assertIs(uvk5_cn.UVK5CNFontRadio,
                      directory.get_radio('Quansheng_UV-K5_font'))
        # the stock driver keeps its own slot
        self.assertIs(uvk5.UVK5Radio,
                      directory.get_radio('Quansheng_UV-K5'))

    def test_cn_classes_do_not_own_detected_models(self):
        """tests/test_clone.py requires detect_from_serial() to be usable."""
        for cls in (uvk5_cn.UVK5CNRadio, uvk5_cn.UVK5CNLoseHuRadio,
                    uvk5_cn.UVK5CNFontRadio):
            self.assertFalse(
                hasattr(cls, 'DETECTED_MODELS_%s' % cls.__name__))
            with self.assertRaises(NotImplementedError):
                cls.detect_from_serial(object())


class TestPrompts(unittest.TestCase):
    """The experimental warning must explain the read-only builds."""

    def test_prompts(self):
        prompts = uvk5_cn.UVK5CNLoseHuRadio.get_prompts()
        for name in ('experimental', 'pre_download', 'pre_upload'):
            self.assertIsInstance(getattr(prompts, name), str)
        text = prompts.experimental
        # The reason the font mapped builds cannot have their names edited
        # has to be visible to the user, not just in the source
        self.assertIn('LOSEHU117K', text)
        self.assertIn('cannot be edited', text)
        self.assertIn('font indices', text)
        self.assertIn('EEPROM size', text)
        self.assertIn('0x40000', text)
        self.assertIn('experimental', text)

    def test_prompts_available_on_the_class_and_an_instance(self):
        self.assertIsInstance(uvk5_cn.UVK5CNRadio.get_prompts(),
                              chirp_common.RadioPrompts)
        radio = uvk5_cn.UVK5CNRadio(None)
        self.assertIsInstance(radio.get_prompts(),
                              chirp_common.RadioPrompts)


class TestRealImage(unittest.TestCase):
    """Exercise the driver against the real LOSEHU131HS capture."""

    def setUp(self):
        self.radio = directory.get_radio_by_image(IMAGE)
        self.radio.status_fn = lambda status: True

    def test_detected_as_losehu_variant(self):
        self.assertIsInstance(self.radio, uvk5_cn.UVK5CNLoseHuRadio)
        self.assertEqual('losehu', self.radio.VARIANT)

    def test_image_metadata(self):
        metadata = self.radio.metadata
        self.assertEqual(FIRMWARE, metadata['uvk5_firmware'])
        self.assertIn('REAL capture', metadata['image_note'])
        self.assertEqual('Quansheng', metadata['vendor'])
        self.assertEqual('UV-K5', metadata['model'])
        self.assertEqual('losehu', metadata['variant'])

    def test_eeprom_size_comes_from_the_image(self):
        self.assertEqual(EEPROM_SIZE, self.radio.eeprom_size)
        # ... and agrees with what the profile suggests, so a fresh download
        # from the same radio would read the same amount
        self.assertEqual(EEPROM_SIZE,
                         uvk5_cn.profile_mem_size(FIRMWARE))

    def test_download_would_stop_at_the_bootloader(self):
        """0x40000 is the whole capture and also the profile default."""
        self.assertEqual(0x40000, self.radio.eeprom_size)
        self.assertEqual(0x40000, uvk5_cn.DATA_LIMIT)
        self.assertEqual(0x40000, uvk5_cn.profile_mem_size(FIRMWARE))
        self.assertEqual(0x40000, len(self.radio._mmap))

    def test_name_limit_is_the_chinese_full_build(self):
        self.assertEqual(13, self.radio._name_max_bytes())
        self.assertEqual(13, self.radio.get_features().valid_name_length)

    def test_channels(self):
        mem = self.radio.get_memory(1)
        self.assertFalse(mem.empty)
        self.assertEqual(CH1_FREQ, mem.freq)
        self.assertEqual(CH1_NAME, mem.name)
        self.assertEqual('FM', mem.mode)
        self.assertEqual('High', str(mem.power))
        self.assertEqual(2.5, mem.tuning_step)
        self.assertEqual('', mem.duplex)          # simplex
        self.assertEqual(0, mem.offset)
        self.assertEqual('None', str(mem.extra['scanlists'].value))

        mem = self.radio.get_memory(3)
        self.assertEqual(439587500, mem.freq)
        self.assertEqual('-', mem.duplex)
        self.assertEqual(8000000, mem.offset)
        self.assertEqual('TSQL', mem.tmode)

        mem = self.radio.get_memory(50)
        self.assertEqual(439925000, mem.freq)
        self.assertEqual(8012500, mem.offset)
        self.assertEqual('Tone', mem.tmode)
        self.assertEqual(71.9, mem.rtone)

        mem = self.radio.get_memory(97)
        self.assertEqual(132600000, mem.freq)
        self.assertEqual('Low', str(mem.power))
        self.assertEqual('\u822a\u7a7a\u9891\u70b9', mem.name)

    def test_band_bytes_match_the_real_image(self):
        # The capture's attribute area starts 05 05 05 05 05 05 05 02 01
        for index in range(7):
            self.assertEqual(0x05, attr_byte(self.radio, index),
                             'channel %i' % (index + 1))
        self.assertEqual(0x02, attr_byte(self.radio, 7))
        self.assertEqual(0x01, attr_byte(self.radio, 8))
        # Unused channels are marked 0xFF on disk, which decodes as is_free
        # plus band 7.  0x0F is the byte the firmware writes when it clears
        # a channel and the byte this driver writes; both mean "empty" and
        # are accepted (k5web accepts both too).
        self.assertEqual(0xff, attr_byte(self.radio, FIRST_EMPTY - 1))
        self.assertEqual(0xff, attr_byte(self.radio, 199))

    def test_non_empty_and_empty_channels(self):
        nonempty = [n for n in range(1, 201)
                    if not self.radio.get_memory(n).empty]
        self.assertEqual(list(range(1, FIRST_EMPTY)), nonempty)
        self.assertEqual(97, len(nonempty))
        for number in (FIRST_EMPTY, 150, 200):
            mem = self.radio.get_memory(number)
            self.assertTrue(mem.empty, number)
            self.assertEqual('', mem.name)
            # mem.extra must still be populated for empty channels
            self.assertEqual(6, len(mem.extra))

    def test_special_channels_are_not_offered(self):
        rf = self.radio.get_features()
        self.assertEqual([], rf.valid_special_chans)
        self.assertEqual((1, 200), rf.memory_bounds)
        self.assertEqual({}, self.radio._get_specials())

    def test_features(self):
        rf = self.radio.get_features()
        self.assertTrue(rf.has_settings)
        self.assertIn('\u4e2d', rf.valid_characters)
        self.assertEqual(24, len(rf.valid_tuning_steps))
        self.assertIn(8.33, rf.valid_tuning_steps)
        self.assertEqual((1, 200), rf.memory_bounds)
        self.assertEqual(18000000, rf.valid_bands[0][0])
        self.assertEqual(1300000000, rf.valid_bands[-1][1])

    def test_validate_memory_accepts_every_real_channel(self):
        """No channel of the capture may produce a warning.

        CHIRP's generated sample image test asserts that
        validate_memory() returns no warnings for any channel of the image
        (tests/test_brute_force.py:202 unpacks split_validation_msgs() the
        other way round, so its "errs" holds the warnings and its "warns"
        holds the errors).  Upstream deals with images that cannot satisfy
        that with entries in tests/driver_xfails.yaml; this driver must not
        need one.

        The single error is CHIRP's core airband policy on channel 91
        (121.745 MHz, a gap in the 8.33 kHz channel scheme); the driver does
        not override core policy.
        """
        warnings = 0
        errors = []
        for number in range(1, 201):
            mem = self.radio.get_memory(number)
            if mem.empty:
                continue
            warns, errs = split_msgs(self.radio.validate_memory(mem))
            warnings += len(warns)
            if errs:
                errors.append((number, str(errs[0])))

        self.assertEqual(0, warnings)
        self.assertEqual([91], [number for number, _ in errors])
        self.assertIn('Aircraft frequencies', errors[0][1])

    def test_long_name_round_trips_without_being_shortened(self):
        mem = self.radio.get_memory(19)
        self.assertEqual('\u5e94\u6025\u901a\u4fe1\u7fbd\u6797\u5927\u961f',
                         mem.name)
        self.radio.set_memory(mem)
        self.assertEqual(mem.name, self.radio.get_memory(19).name)
        raw = bytes(self.radio._memobj.channelname[18].get_raw())
        self.assertEqual(16, len(raw.rstrip(b'\x00')))

    def test_airband_gap_channel_follows_core_policy(self):
        """Channel 91 of the capture is 121.745 MHz.

        chirp_common.fix_rounded_step() refuses that as a gap in the
        8.33 kHz airband channel scheme (chirp_common.py:1878-1884).  The
        driver does not override core policy, so it comes back as exactly
        one error and no warning.
        """
        mem = self.radio.get_memory(91)
        self.assertEqual(121745000, mem.freq)
        warns, errs = split_msgs(self.radio.validate_memory(mem))
        self.assertEqual([], warns)
        self.assertEqual(1, len(errs))
        self.assertIn('Aircraft frequencies', str(errs[0]))
        self.assertTrue(chirp_common.is_airband(121745000))

    def test_validate_memory_rejects_name_wider_than_the_field(self):
        mem = self.radio.get_memory(1)
        mem.name = '\u4e2d' * 9                  # 18 bytes > 16
        warns, errs = split_msgs(self.radio.validate_memory(mem))
        self.assertEqual(1, len(errs))
        self.assertIn('16 bytes', str(errs[0]))

    def test_validate_memory_is_silent_about_the_editor_limit(self):
        """A name past the radio's editor limit but inside the field is
        accepted without a message: the field holds it, this driver keeps it
        byte for byte, and warning about it would flag ten channels of the
        real capture (and fail the sample image test, see above)."""
        mem = self.radio.get_memory(1)
        self.assertEqual(13, self.radio._name_max_bytes())
        mem.name = '\u4e2d' * 7                  # 14 bytes: field ok
        self.assertFalse(uvk5_cn.name_fits(mem.name,
                                           self.radio._name_max_bytes()))
        self.assertTrue(uvk5_cn.name_fits(mem.name, uvk5_cn.NAME_LENGTH))
        warns, errs = split_msgs(self.radio.validate_memory(mem))
        self.assertEqual([], warns)
        self.assertEqual([], errs)

    def test_validate_memory_accepts_name_at_the_editor_limit(self):
        mem = self.radio.get_memory(1)
        mem.name = '\u4e2d' * 6                  # 12 bytes, still <= 13
        warns, errs = split_msgs(self.radio.validate_memory(mem))
        self.assertEqual([], warns)
        self.assertEqual([], errs)

    def test_validate_memory_rejects_out_of_band(self):
        mem = self.radio.get_memory(1)
        mem.freq = 2000000000
        warns, errs = split_msgs(self.radio.validate_memory(mem))
        self.assertTrue(errs)

    def test_set_memory_round_trip_ascii(self):
        number = FIRST_EMPTY
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 435000000
        mem.name = 'TEST'
        self.radio.set_memory(mem)
        new = self.radio.get_memory(number)
        self.assertFalse(new.empty)
        self.assertEqual(435000000, new.freq)
        self.assertEqual('TEST', new.name)

    def test_set_memory_round_trip_gb2312(self):
        number = FIRST_EMPTY + 1
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 439000000
        mem.name = '\u4e2d\u7ee7\u53f0'
        self.radio.set_memory(mem)
        new = self.radio.get_memory(number)
        self.assertEqual('\u4e2d\u7ee7\u53f0', new.name)
        # ... and the field really holds GB2312 bytes
        raw = self.radio._memobj.channelname[number - 1].get_raw()
        self.assertEqual('\u4e2d\u7ee7\u53f0'.encode('gb2312'),
                         bytes(raw[:6]))
        self.assertEqual(b'\x00' * 10, bytes(raw[6:]))

    def test_losehu_byte12_bits_survive_set_memory(self):
        """Byte 12 bit5/bit6 and byte 11 bit3 must survive a round trip.

        The LOSEHU tree sets bit5 of byte 12 unconditionally and mirrors
        FrequencyReverse into bit6
        (uv-k5-firmware-custom/settings.c:679-685) while LTS does not
        (settings.c:699-703); neither is modelled, so both must be preserved
        by the SAVE_MASK path (uvk5.py:232-237).  The firmware reads back
        only bits 0-4 (radio.c:305-309).
        """
        number = FIRST_EMPTY + 2
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 145000000
        mem.name = 'UNK'
        self.radio.set_memory(mem)

        raw = bytearray(self.radio._memobj.channel[number - 1].get_raw())
        raw[0x0b] |= 0b00001000          # flags1_unknown3  (byte 11 bit3)
        raw[0x0c] |= 0b01100000          # byte 12 bit5 and bit6
        self.radio._memobj.channel[number - 1].set_raw(bytes(raw))

        changed = self.radio.get_memory(number)
        changed.name = 'UNK2'            # force the non-empty write path
        self.radio.set_memory(changed)

        after = bytes(self.radio._memobj.channel[number - 1].get_raw())
        self.assertEqual(0b00001000, after[0x0b] & 0b00001000,
                         'byte 11 unknown bit was cleared')
        self.assertEqual(0b01100000, after[0x0c] & 0b01100000,
                         'byte 12 bit5/bit6 were cleared')
        self.assertEqual('UNK2', self.radio.get_memory(number).name)

    def test_unknown_bits_of_bytes_0b_to_0d_and_0f_survive(self):
        number = FIRST_EMPTY + 3
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 145000000
        mem.name = 'MASK'
        self.radio.set_memory(mem)

        masks = {0x0b: uvk5.SAVE_MASK_0B, 0x0c: uvk5.SAVE_MASK_0C,
                 0x0d: uvk5.SAVE_MASK_0D, 0x0f: uvk5.SAVE_MASK_0F}
        raw = bytearray(self.radio._memobj.channel[number - 1].get_raw())
        for offset, mask in masks.items():
            raw[offset] |= mask
        self.radio._memobj.channel[number - 1].set_raw(bytes(raw))

        changed = self.radio.get_memory(number)
        changed.name = 'MASK2'
        self.radio.set_memory(changed)

        after = bytes(self.radio._memobj.channel[number - 1].get_raw())
        for offset, mask in masks.items():
            self.assertEqual(mask, after[offset] & mask,
                             'byte 0x%02x masked bits changed' % offset)

    def test_unrepresentable_name_bytes_are_preserved(self):
        """Name bytes we cannot reproduce must not be rewritten.

        The field can hold bytes after the terminator, and an undecodable
        two byte pair decodes to '?'; re-encoding either would destroy them.
        As long as the visible name is unchanged, the raw bytes are left
        alone.
        """
        field = self.radio._memobj.channelname[0]      # real channel 1
        raw = b'A\x80\x40B' + b'\x00' * 12
        field.set_raw(raw)

        mem = self.radio.get_memory(1)
        self.assertFalse(mem.empty)
        self.assertEqual('A?B', mem.name)
        self.assertEqual(435587500, mem.freq)
        mem.freq = 145500000               # change something else entirely
        self.radio.set_memory(mem)
        self.assertEqual(raw, bytes(field.get_raw()))

        # Bytes after the terminator are just as protected
        trailing = b'AB' + b'\x00' + b'\xd6\xd0' + b'\x00' * 11
        field.set_raw(trailing)
        mem = self.radio.get_memory(1)
        self.assertEqual('AB', mem.name)
        mem.freq = 145500000
        self.radio.set_memory(mem)
        self.assertEqual(trailing, bytes(field.get_raw()))

        # But when the user really changes the name, it is written
        mem.name = 'NEW'
        self.radio.set_memory(mem)
        self.assertEqual(uvk5_cn.encode_name('NEW'), bytes(field.get_raw()))

    def test_empty_memory_markers(self):
        number = FIRST_EMPTY + 5
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 145500000
        mem.name = 'GONE'
        self.radio.set_memory(mem)
        self.assertFalse(self.radio.get_memory(number).empty)

        mem.empty = True
        self.radio.set_memory(mem)
        self.assertEqual(b'\xff' * 16,
                         bytes(self.radio._memobj.channel[number - 1]
                               .get_raw()))
        self.assertEqual(b'\xff' * 16,
                         bytes(self.radio._memobj.channelname[number - 1]
                               .get_raw()))
        self.assertEqual(0x0f, attr_byte(self.radio, number - 1))
        self.assertTrue(self.radio.get_memory(number).empty)

    def test_tuning_step_round_trip_for_every_offered_step(self):
        number = FIRST_EMPTY + 6
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 145000000
        for step in self.radio.get_features().valid_tuning_steps:
            mem.tuning_step = step
            self.radio.set_memory(mem)
            self.assertEqual(step, self.radio.get_memory(number).tuning_step)

    def test_set_memory_does_not_modify_input(self):
        mem = chirp_common.FrozenMemory(self.radio.get_memory(1))
        self.radio.set_memory(mem)               # must not raise
        self.assertEqual('\u79c1\u6709\u9891\u70b9',
                         self.radio.get_memory(1).name)

    def test_get_memory_has_no_trailing_whitespace(self):
        number = FIRST_EMPTY + 7
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 145000000
        mem.name = 'PAD '
        self.radio.set_memory(mem)
        self.assertEqual('PAD', self.radio.get_memory(number).name)

    def test_settings_round_trip(self):
        settings = self.radio.get_settings()
        before = {}
        for group in settings:
            for setting in group:
                before[setting.get_name()] = setting.value.get_value()
        self.assertEqual(FIRMWARE, before['fw_ver'])
        self.assertEqual('0x40000 (256 KiB)', before['eeprom_size'])
        self.assertTrue(before['nolimits'])

        self.radio.set_settings(settings)

        after = {}
        for group in self.radio.get_settings():
            for setting in group:
                after[setting.get_name()] = setting.value.get_value()
        self.assertEqual(before, after)

    def test_eeprom_size_setting(self):
        # The image is 0x40000; reduce the setting and check it takes effect
        self.assertEqual(0x40000, self.radio.eeprom_size)
        settings = self.radio.get_settings()
        for group in settings:
            for setting in group:
                if setting.get_name() == 'eeprom_size':
                    setting.value.set_value('0x10000 (64 KiB)')
        self.radio.set_settings(settings)
        self.assertEqual(0x10000, self.radio.eeprom_size)

    def test_no_deprecation_warnings_from_memory(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            mem = self.radio.get_memory(1)
            self.radio.set_memory(mem)

    def test_bitwise_parses_the_image_without_errors(self):
        with mock.patch.object(bitwise.LOG, 'error') as mock_error:
            self.radio.process_mmap()
            self.assertFalse(mock_error.called,
                             [x[0][0] for x in mock_error.call_args_list])


class TestWriteSafety(unittest.TestCase):
    """Nothing at or above DATA_LIMIT may ever be written.

    0x040000-0x07FFFF holds the multi-bootloader on these builds ("_BL002"
    at 0x40008); a stray write there can leave the radio unbootable in a way
    CHIRP cannot repair.
    """

    def test_writemem_refuses_the_bootloader_region(self):
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])))
        with self.assertRaises(errors.RadioError) as caught:
            uvk5_cn._writemem(serport, b'\x00' * 16, 0x40000)
        message = str(caught.exception)
        self.assertIn('0x40000', message)
        self.assertIn('multi-bootloader', message)
        # Nothing was sent to the radio
        self.assertEqual([], serport.written)

    def test_writemem_refuses_a_block_that_crosses_the_limit(self):
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])))
        with self.assertRaises(errors.RadioError):
            uvk5_cn._writemem(serport, b'\x00' * 0x40, 0x3ffd0)
        self.assertEqual([], serport.written)

    def test_writemem_allows_the_last_block_below_the_limit(self):
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])))
        self.assertTrue(uvk5_cn._writemem(serport, b'\x00' * 0x40, 0x3ffc0))
        self.assertEqual(1, len(serport.written))

    def test_readmem_refuses_the_bootloader_region(self):
        serport = FakeSerial()
        with self.assertRaises(errors.RadioError):
            uvk5_cn._readmem(serport, 0x40000, 0x80)
        self.assertEqual([], serport.written)

    def test_upload_refuses_an_image_that_reaches_the_bootloader(self):
        radio = uvk5_cn.UVK5CNLoseHuRadio(None)
        radio.status_fn = lambda status: True
        radio.pipe = FakeSerial()
        radio._mmap = memmap.MemoryMapBytes(bytes(0x80000))
        # A size setting inside the limit, so that the *image* length is what
        # trips the guard
        radio._eeprom_size = 0x2000
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5_cn.do_upload(radio)
        message = str(caught.exception)
        self.assertIn('524288', message)        # the image length
        self.assertIn('0x40000', message)       # the limit
        self.assertIn('multi-bootloader', message)

    def test_upload_refuses_a_size_past_the_limit(self):
        radio = uvk5_cn.UVK5CNLoseHuRadio(None)
        radio.status_fn = lambda status: True
        radio.pipe = FakeSerial()
        radio._mmap = memmap.MemoryMapBytes(bytes(0x2000))
        radio._eeprom_size = 0x80000
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5_cn.do_upload(radio)
        message = str(caught.exception)
        self.assertIn('0x80000', message)
        self.assertIn('0x40000', message)
        self.assertIn('multi-bootloader', message)

    def test_download_refuses_a_size_past_the_limit(self):
        radio = uvk5_cn.UVK5CNLoseHuRadio(None)
        radio.status_fn = lambda status: True
        radio.pipe = FakeSerial()
        radio._eeprom_size = 0x80000
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5_cn.do_download(radio)
        self.assertIn('0x40000', str(caught.exception))

    def test_real_image_is_inside_the_limit(self):
        """The shipped capture must be loadable and uploadable as is."""
        with open(IMAGE, 'rb') as image_file:
            data = image_file.read()
        payload, metadata = chirp_common.CloneModeRadio._strip_metadata(data)
        self.assertEqual(0x40000, len(payload))
        self.assertLessEqual(len(payload), uvk5_cn.DATA_LIMIT)
        self.assertEqual(FIRMWARE, metadata['uvk5_firmware'])


class TestFontMappedNames(unittest.TestCase):
    """UVK5CNFontRadio must never lose or mangle a font mapped name.

    These builds store remapped glyph indices rather than GB2312
    (ui/helper.c:192-201), so there is no text to decode; the driver keeps
    one character per byte, marks the name immutable and lets everything
    else be edited.
    """

    FIRMWARE = 'LOSEHU117P6K'
    # Two font index pairs, the second with a non-printable trail byte
    # (0x02), which is legal for the firmware and would be destroyed by any
    # text re-encoding.
    NAME = b'\x85\x41\x87\x02' + b'\x90\xff' + b'\x00' * 10

    def setUp(self):
        image = bytearray(0x2000)
        # Empty channels: record and name 0xFF, attribute 0x0F
        for index in range(200):
            image[index * 16:(index + 1) * 16] = b'\xFF' * 16
            image[0x0d60 + index] = 0x0F
        image[0x00:0x10] = b'\x00' * 16         # a written channel record
        image[0xf50:0xf60] = self.NAME
        image[0x0d60] = 0x05                    # channel 1 in use
        image[0x00:0x04] = struct.pack('<L', 435587500 // 10)
        image[0x0c] = 0x08                      # high power

        self.radio = uvk5_cn.UVK5CNFontRadio(None)
        self.radio.status_fn = lambda status: True
        self.radio.metadata = {'uvk5_firmware': self.FIRMWARE}
        self.radio._mmap = memmap.MemoryMapBytes(bytes(image))
        self.radio._eeprom_size = 0x2000
        self.radio.process_mmap()

    def test_profile_and_features(self):
        # LOSEHU117P6K is the LTS default build, so k5web maps it to ltsk
        # (the LOSEHU.*P.* table row comes first)
        self.assertEqual('ltsk', uvk5_cn.cn_profile(self.FIRMWARE))
        self.assertTrue(
            uvk5_cn.UVK5CNFontRadio.k5_approve_firmware(self.FIRMWARE))
        self.assertEqual(13, self.radio._name_max_bytes())
        self.assertEqual('latin1', self.radio.NAME_CHARSET)
        self.assertFalse(self.radio.NAMES_ARE_TEXT)

    def test_name_is_decoded_losslessly(self):
        mem = self.radio.get_memory(1)
        self.assertFalse(mem.empty)
        self.assertEqual(435587500, mem.freq)
        # One character per byte, including the non-printable trail byte
        self.assertEqual(self.NAME[:6].decode('latin-1'), mem.name)

    def test_name_is_immutable(self):
        mem = self.radio.get_memory(1)
        self.assertEqual(['name'], mem.immutable)
        with self.assertRaises(chirp_common.ImmutableValueError):
            mem.name = 'text'

    def test_other_fields_are_editable(self):
        mem = self.radio.get_memory(1)
        mem.freq = 439000000
        mem.tmode = 'Tone'
        mem.rtone = 88.5
        self.radio.set_memory(mem)
        new = self.radio.get_memory(1)
        self.assertEqual(439000000, new.freq)
        self.assertEqual('Tone', new.tmode)
        self.assertEqual(88.5, new.rtone)

    def test_untouched_name_round_trips_byte_for_byte(self):
        mem = self.radio.get_memory(1)
        mem.freq = 145500000                    # edit something else
        self.radio.set_memory(mem)
        self.assertEqual(
            self.NAME,
            bytes(self.radio._memobj.channelname[0].get_raw()))
        # ... and a later read still shows the same characters
        self.assertEqual(self.NAME[:6].decode('latin-1'),
                         self.radio.get_memory(1).name)

    def test_encode_is_a_bijection(self):
        for raw in (b'\x85\x41\x87\x02' + b'\x00' * 12,
                    b'\xc0\xfe\x9b\x01' + b'\x00' * 12,
                    b'AB\xd6\xd0' + b'\x00' * 12):
            text = uvk5_cn.decode_name(raw, 'latin1')
            self.assertEqual(raw, uvk5_cn.encode_name(text, 16, 'latin1'))

    def test_all_ff_name_field_is_empty(self):
        self.assertEqual('', uvk5_cn.decode_name(b'\xff' * 16, 'latin1'))
        self.assertEqual('', uvk5_cn.decode_name(b'\x00' * 16, 'latin1'))

    def test_latin1_charset_covers_every_byte_but_nul(self):
        charset = uvk5_cn.latin1_charset()
        for byte in (0x01, 0x20, 0x41, 0x7f, 0x80, 0x9b, 0xfe, 0xff):
            self.assertIn(chr(byte), charset)
        self.assertNotIn('\x00', charset)

    def test_a_corrupt_tone_nibble_does_not_crash_get_memory(self):
        """uvk5's _get_tone indexes TMODES with the raw nibble.

        Radios only write tone types 0..3 (dcs.h:22-30), but a partially
        written record (or a hand-made image) can hold 0xFF there, which
        would raise IndexError while loading an image.  The driver must
        survive it and simply report no tone.
        """
        image = bytearray(b'\xFF' * 0x2000)
        image[0x00:0x04] = struct.pack('<L', 435587500 // 10)
        image[0x0d60] = 0x05
        radio = uvk5_cn.UVK5CNLoseHuRadio(None)
        radio.metadata = {'uvk5_firmware': FIRMWARE}
        radio._mmap = memmap.MemoryMapBytes(bytes(image))
        radio._eeprom_size = 0x2000
        radio.process_mmap()
        mem = radio.get_memory(1)               # must not raise
        self.assertFalse(mem.empty)
        self.assertEqual('', mem.tmode)
        self.assertEqual(435587500, mem.freq)


@unittest.skipIf(not os.path.exists(IMAGE), 'test image missing')
class TestCloneWithFakeSerial(unittest.TestCase):
    """Download and upload over a fake serial port."""

    READ_DATA = bytes(range(0x80))

    def setUp(self):
        self.radio = uvk5_cn.UVK5CNLoseHuRadio(None)
        self.radio.status_fn = lambda status: True

    def _read_reply(self, data):
        payload = bytes([0x1c, 0x05, 0x0a, 0x00, 0x00, 0x00,
                         len(data), 0x00]) + data
        return make_reply(payload)

    def _download(self, response=b'', fail_after=None, size=None):
        serport = FakeSerial(response, fail_after=fail_after)
        self.radio.pipe = serport
        if size is not None:
            self.radio._eeprom_size = size
        with mock.patch.object(uvk5, '_sayhello',
                               return_value=FIRMWARE):
            mmap = uvk5_cn.do_download(self.radio)
        return serport, mmap

    def test_download_reads_the_requested_size(self):
        size = 0x2000
        response = self._read_reply(self.READ_DATA) * (size // 0x80)
        serport, mmap = self._download(response, size=size)
        self.assertEqual(size, len(mmap.get_packed()))
        self.assertEqual(size // 0x80, len(serport.written))
        # every read command must be a 0x2b command at a 0x80 offset
        for index, frame in enumerate(serport.written):
            payload = unframe(frame)
            self.assertEqual(0x2b, payload[0])
            self.assertEqual(
                uvk5_cn.TIMESTAMP, payload[8:12])
            self.assertEqual(struct.pack('<H', (index * 0x80) & 0xffff),
                             payload[12:14])
        self.assertEqual(FIRMWARE, self.radio.metadata['uvk5_firmware'])
        self.assertEqual(self.READ_DATA * (size // 0x80), mmap.get_packed())

    def test_download_falls_back_when_profile_over_estimates(self):
        """A profile guess may be too big; keep the usable part."""
        response = self._read_reply(self.READ_DATA) * 64    # exactly 0x2000
        with self.assertLogs(uvk5_cn.LOG, level='WARNING') as log:
            serport, mmap = self._download(response)
        self.assertEqual(0x2000, len(mmap.get_packed()))
        self.assertTrue(any('keeping' in line for line in log.output))

    def test_download_fails_if_no_usable_image(self):
        with self.assertRaises(errors.RadioError):
            self._download(b'', fail_after=0, size=0x2000)

    def test_download_rejects_unsupported_firmware(self):
        self.radio.pipe = FakeSerial()
        with mock.patch.object(uvk5, '_sayhello', return_value='BOGUS'):
            with self.assertRaises(errors.RadioError):
                uvk5_cn.do_download(self.radio)

    def test_upload_writes_prog_size_and_resets(self):
        self.radio._mmap = memmap.MemoryMapBytes(bytes(range(0x100)) * 0x20)
        self.radio._eeprom_size = 0x2000
        nwrites = 0x1d00 // 0x40
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])) * nwrites)
        self.radio.pipe = serport
        with mock.patch.object(uvk5, '_sayhello',
                               return_value=FIRMWARE):
            self.assertTrue(uvk5_cn.do_upload(self.radio))
        # 0x1d00 / 0x40 writes in 0x40 byte blocks plus the reset packet
        self.assertEqual(nwrites + 1, len(serport.written))
        for index, frame in enumerate(serport.written[:-1]):
            payload = unframe(frame)
            self.assertEqual(0x38, payload[0])
            self.assertEqual(10 + 0x40,
                             struct.unpack('<H', payload[2:4])[0])
            self.assertEqual(0x40 + 2, payload[6])
            self.assertEqual(uvk5_cn.TIMESTAMP, payload[8:12])
            self.assertEqual(struct.pack('<H', (index * 0x40) & 0xffff),
                             payload[12:14])
            self.assertEqual(0x40, len(payload) - 14)
        self.assertEqual(b'\xdd\x05\x00\x00',
                         unframe(serport.written[-1]))

    def test_upload_refuses_mismatched_image(self):
        self.radio._mmap = memmap.MemoryMapBytes(bytes(0x2000))
        self.radio._eeprom_size = 0x40000
        self.radio.pipe = FakeSerial(make_reply(bytes([0x1e, 0x05])))
        with mock.patch.object(uvk5, '_sayhello',
                               return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5_cn.do_upload(self.radio)
        message = str(caught.exception)
        # The error must name the image length, the profile default and the
        # setting, never truncate or pad silently
        self.assertIn('8192', message)          # loaded image length
        self.assertIn('todo', message)          # its profile
        self.assertIn('losehu124h', message)    # radio profile
        self.assertIn('262144', message)        # profile default (0x40000)
        self.assertIn('EEPROM size', message)

    def test_upload_rejects_unsupported_firmware(self):
        self.radio._mmap = memmap.MemoryMapBytes(bytes(0x2000))
        self.radio.pipe = FakeSerial()
        with mock.patch.object(uvk5, '_sayhello', return_value='BOGUS'):
            with self.assertRaises(errors.RadioError):
                uvk5_cn.do_upload(self.radio)

    def test_sixteen_bit_class_refuses_unaddressable_size(self):
        """The stock 0x1B/0x1D pair cannot address past 0xFFFF.

        On the reference radio reading 0x10000 with it returns the bytes
        from 0x0000, so a size above 0x10000 must be refused rather than
        silently producing a wrong image.
        """
        radio = uvk5_cn.UVK5CNRadio(None)
        radio.status_fn = lambda status: True
        radio.pipe = FakeSerial()
        radio._eeprom_size = 0x20000
        with mock.patch.object(uvk5, '_sayhello',
                               return_value='LOSEHU118'):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5_cn.do_download(radio)
        self.assertIn('0x10000', str(caught.exception))
        with self.assertRaises(errors.RadioError) as caught:
            uvk5_cn.do_upload(radio)
        self.assertIn('0x10000', str(caught.exception))

    def test_sync_in_with_silent_serial_raises_radio_error(self):
        self.radio.pipe = FakeSerial()
        with self.assertRaises(errors.RadioError):
            self.radio.sync_in()


if __name__ == '__main__':
    unittest.main()
