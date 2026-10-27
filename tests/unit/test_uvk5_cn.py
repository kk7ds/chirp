# Copyright 2026 赵昕 BG8ADW
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

"""Unit tests for the Chinese firmware UV-K5 driver (chirp.drivers.uvk5_cn).

These tests need no radio and no serial port.  The image in
tests/images/Quansheng_UV-K5_losehu.img is a REAL 256 KiB capture from a
UV-K5 running a LOSEHU131HS build (2026-10-13, Prolific PL2303GS on COM9);
only the CHIRP metadata trailer was added to it.

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

IMAGES = os.path.join(os.path.dirname(__file__), '..', 'images')
IMAGE = os.path.join(IMAGES, 'Quansheng_UV-K5_losehu.img')
OEM_IMAGE = os.path.join(IMAGES, 'Quansheng_UV-K5.img')

# The real radio this image came from
FIRMWARE = 'LOSEHU131HS'
EEPROM_SIZE = 0x40000
# First unused channel in the capture (its record and name slot are all 0xFF)
FIRST_EMPTY = 98
# Channel 1 of the capture: GB2312 "private frequency", 435.5875 MHz simplex
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
    """Recompose the channel attribute byte for @index."""
    attr = radio._memobj.channel_attributes[index]
    return ((int(attr.is_scanlist1) << 7) |
            (int(attr.is_scanlist2) << 6) |
            (int(attr.compander) << 4) |
            (int(attr.is_free) << 3) |
            int(attr.band))


def split_msgs(msgs):
    return chirp_common.split_validation_msgs(msgs)


def image_payload(path):
    with open(path, 'rb') as image_file:
        data = image_file.read()
    payload, metadata = chirp_common.CloneModeRadio._strip_metadata(data)
    return payload, metadata


class TestMemFormat(unittest.TestCase):
    """MEM_FORMAT must be built from the shared definitions, not a copy."""

    def test_built_from_the_base_definitions(self):
        self.assertTrue(uvk5_cn.MEM_FORMAT.startswith(uvk5.MEM_DEFS))
        self.assertTrue(uvk5.MEM_FORMAT.startswith(uvk5.MEM_DEFS))
        # The struct bodies live in exactly one place
        self.assertEqual(1, uvk5.MEM_DEFS.count('struct memory {'))
        layout = uvk5_cn.MEM_FORMAT[len(uvk5.MEM_DEFS):]
        self.assertNotIn('ul32 freq', layout)
        self.assertIn('struct memory channel[214];', layout)
        self.assertIn('struct channel_attributes channel_attributes[200];',
                      layout)
        self.assertIn('struct channelname channelname[200];', layout)

    def test_parses_the_real_image_identically_to_the_base(self):
        """Our subset must place everything exactly where uvk5 does."""
        payload, _metadata = image_payload(IMAGE)
        ours = bitwise.parse(uvk5_cn.MEM_FORMAT,
                             memmap.MemoryMapBytes(payload))
        base = bitwise.parse(uvk5.MEM_FORMAT,
                             memmap.MemoryMapBytes(payload))
        for number in range(200):
            self.assertEqual(bytes(base.channel[number].get_raw()),
                             bytes(ours.channel[number].get_raw()),
                             'channel record %i' % (number + 1))
            self.assertEqual(bytes(base.channelname[number].get_raw()),
                             bytes(ours.channelname[number].get_raw()),
                             'channel name %i' % (number + 1))
            self.assertEqual(
                bytes(base.channel_attributes[number].get_raw()),
                bytes(ours.channel_attributes[number].get_raw()),
                'channel attributes %i' % (number + 1))


class TestTimestamp(unittest.TestCase):
    """Every command must carry the hello packet's timestamp.

    The firmware stores the four byte timestamp of the hello command and
    silently drops any later command that carries a different one - no
    reply, no error, indistinguishable from a dead radio:
    ``app/uart.c:243`` stores it, ``app/uart.c:264`` (CMD_051B), ``:298``
    (CMD_051D), ``:584`` (CMD_052B) and ``:613`` (CMD_0538) all return
    early on a mismatch.
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

    def test_base_commands_use_the_same_timestamp(self):
        """The commands inherited from uvk5 must agree as well."""
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
    """Byte exact checks of the command bodies.

    The expected bytes are written out by hand from k5web
    src/utils/serial.js eeprom_read (line 1458) and eeprom_write (line 1552)
    and from the firmware's own CMD_0538 (app/uart.c:614-649), so that a
    change in the driver cannot silently change the protocol.
    """

    def test_read_command_low_address(self):
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
        cls = uvk5_cn.UVK5LoseHuRadio
        self.assertEqual(0x80, cls.MEM_BLOCK)        # reply structure limit
        self.assertEqual(0x40, cls.WRITE_BLOCK)      # k5web verified size
        self.assertEqual(0, cls.WRITE_BLOCK % 8)     # firmware write unit
        self.assertEqual(0, cls.PROG_SIZE % cls.WRITE_BLOCK)
        self.assertEqual(0x1d00, cls.PROG_SIZE)

    def test_writemem_sends_exactly_that_frame(self):
        data = bytes(range(0x40))
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


class TestNameCodec(unittest.TestCase):

    def test_ascii_round_trip(self):
        self.assertEqual(padded(b'CALL'), uvk5_cn.encode_name('CALL'))
        self.assertEqual('CALL', uvk5_cn.decode_name(padded(b'CALL')))

    def test_real_radio_gb2312_name(self):
        """The name of channel 1 of the real capture."""
        raw = b'\xcb\xbd\xd3\xd0\xc6\xb5\xb5\xe3' + b'\x00' * 8
        self.assertEqual(CH1_NAME, uvk5_cn.decode_name(raw))
        self.assertEqual(raw, uvk5_cn.encode_name(CH1_NAME))
        self.assertTrue(uvk5_cn.name_fits(CH1_NAME, uvk5_cn.NAME_BYTES))

    def test_gb2312_round_trip(self):
        name = '\u4e2d\u7ee7'                      # "repeater"
        self.assertEqual(padded(b'\xd6\xd0\xbc\xcc'),
                         uvk5_cn.encode_name(name))
        self.assertEqual(name, uvk5_cn.decode_name(
            uvk5_cn.encode_name(name)))

    def test_empty_name_all_ff(self):
        self.assertEqual('', uvk5_cn.decode_name(b'\xff' * 16))

    def test_empty_name_all_nul(self):
        self.assertEqual('', uvk5_cn.decode_name(b'\x00' * 16))
        self.assertEqual(padded(b''), uvk5_cn.encode_name(''))

    def test_name_stops_at_ff(self):
        self.assertEqual('AB', uvk5_cn.decode_name(b'AB' + b'\xff' * 14))

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
        raw = b'A\x80\x40B' + b'\x00' * 12       # 0x80 is not a GB2312 lead
        self.assertEqual('A?B', uvk5_cn.decode_name(raw))

    def test_name_longer_than_field_is_truncated_on_char_boundary(self):
        name = '\u4e2d' * 9                        # 18 bytes
        self.assertFalse(uvk5_cn.name_fits(name))
        encoded = uvk5_cn.encode_name(name, uvk5_cn.NAME_LENGTH)
        self.assertEqual(16, len(encoded))
        self.assertEqual('\u4e2d' * 8, uvk5_cn.decode_name(encoded))

    def test_name_is_encoded_within_the_editor_limit(self):
        # The default limit is the firmware's 13 bytes (font.h:28)
        self.assertEqual(13, uvk5_cn.NAME_BYTES)
        self.assertEqual(b'X' * 13 + b'\x00' * 3,
                         uvk5_cn.encode_name('X' * 16))
        self.assertTrue(uvk5_cn.name_fits('X' * 13, 13))
        self.assertFalse(uvk5_cn.name_fits('X' * 14, 13))
        # Five two byte characters fit in 10 bytes, six do not
        self.assertTrue(uvk5_cn.name_fits('\u4e2d' * 5, 10))
        self.assertFalse(uvk5_cn.name_fits('\u4e2d' * 6, 10))

    def test_unencodable_character_becomes_question_mark(self):
        self.assertEqual(padded(b'?'), uvk5_cn.encode_name('\u20ac'))

    def test_gb2312_charset_is_usable(self):
        charset = uvk5_cn.gb2312_charset()
        self.assertIn('A', charset)
        self.assertIn('\u4e2d', charset)
        self.assertNotIn('\x00', charset)


class TestFirmwareProfiles(unittest.TestCase):
    """The profile table must follow k5web navbar/index.vue:230-254."""

    def test_retained_profiles(self):
        cases = {
            'LOSEHU131HS': 'losehu124h',     # the reference radio
            'LOSEHU133HS': 'losehu124h',
            'LOSEHU133H': 'losehu124h',
            'LOSEHU133K': 'losehu120k',
            'LOSEHU126K': 'losehu120k',
            'LOSEHU126H': 'losehu124h',
            'LOSEHU122H': 'losehu118h',
            'LOSEHU118K': 'losehu118k',
            'LOSEHU118H': 'losehu118h',
            'L_BL001': 'losehubl',
            'LOSEHUD': 'losehud',
            'UVE5-1.2.3': 'losehu124h',
        }
        for firmware, profile in cases.items():
            self.assertEqual(profile, uvk5_cn.cn_profile(firmware), firmware)
            self.assertTrue(
                uvk5_cn.UVK5LoseHuRadio.k5_approve_firmware(firmware),
                firmware)

    def test_deferred_builds_are_not_claimed(self):
        """The other code paths are deliberately left to the follow-up PR.

        The stock-command builds (losehu117/118/lts), the font-mapped ones
        (losehu117k/ltsk) and the LTS sub-font builds each take a path that
        no capture here exercises, so they must come up as the read-only
        fallback rather than be driven on a guess.
        """
        for firmware in ('LOSEHU116', 'LOSEHU117P6', 'LOSEHU118',
                         'LOSEHU133', 'LOSEHU116K', 'LOSEHU117K',
                         'LOSEHU117P6K', 'LOSEHU13PK', 'font1', 'font2',
                         'font3', 'LOSEHU140'):
            self.assertEqual('todo', uvk5_cn.cn_profile(firmware), firmware)
            self.assertFalse(
                uvk5_cn.UVK5LoseHuRadio.k5_approve_firmware(firmware),
                firmware)

    def test_oem_and_foreign_firmware_are_not_claimed(self):
        for firmware in ('k5_2.01.26', 'app_2.01.17', 'EGZUMER v1',
                         '7.03.01', '1o11', '*OEFW-LOSEHU', 'OSFW-bd90ca3'):
            self.assertFalse(
                uvk5_cn.UVK5LoseHuRadio.k5_approve_firmware(firmware),
                firmware)

    def test_oefw_flash_header_is_never_approved(self):
        """0x2000 holds '*OEFW-<author>' (fw-pack.py:28); it is not the
        version string and must never be allowlisted."""
        for firmware in ('*OEFW-LOSEHU', '*OEFW-'):
            self.assertFalse(uvk5.UVK5Radio.k5_approve_firmware(firmware))
            self.assertEqual('todo', uvk5_cn.cn_profile(firmware))

    def test_k1_goes_to_the_upstream_uvk1_driver(self):
        self.assertEqual('k1', uvk5_cn.cn_profile('7.03.01'))
        self.assertTrue(uvk5.UVK1Radio.k5_approve_firmware('7.03.01'))

    def test_eeprom_size_from_profile(self):
        # A live scan of the reference radio shows user data ending before
        # 0x40000 with the multi-bootloader starting there, so every claimed
        # profile defaults to 0x40000.
        for firmware in (FIRMWARE, 'LOSEHU133HS', 'LOSEHU126K', 'LOSEHU118H',
                         'LOSEHU118K', 'LOSEHUD', 'L_BL001', 'UVE5'):
            self.assertEqual(0x40000, uvk5_cn.profile_mem_size(firmware),
                             firmware)
        # Anything not claimed keeps the smallest image
        self.assertEqual(0x2000, uvk5_cn.profile_mem_size('LOSEHU116'))
        self.assertEqual(0x2000, uvk5_cn.profile_mem_size('unknown'))

    def test_data_limit_is_the_bootloader_boundary(self):
        self.assertEqual(0x40000, uvk5_cn.DATA_LIMIT)
        self.assertLess(uvk5_cn.UVK5LoseHuRadio.PROG_SIZE,
                        uvk5_cn.DATA_LIMIT)


class TestDetection(unittest.TestCase):
    """Serial detection must pick the right class, and fall back safely."""

    def _detect(self, firmware):
        with mock.patch.object(uvk5, '_sayhello', return_value=firmware):
            return uvk5.UVK5Radio.detect_from_serial(object())

    def test_claimed_firmware_uses_our_class(self):
        for firmware in ('LOSEHU131HS', 'LOSEHU133K', 'LOSEHU126H',
                         'LOSEHU118K', 'LOSEHUD', 'L_BL001', 'UVE5'):
            self.assertIs(uvk5_cn.UVK5LoseHuRadio, self._detect(firmware),
                          firmware)

    def test_deferred_and_unknown_firmware_is_read_only(self):
        for firmware in ('LOSEHU116', 'LOSEHU117P6K', 'LOSEHU133',
                         'some new firmware'):
            self.assertIs(uvk5.UVK5RestrictedRadio, self._detect(firmware),
                          firmware)

    def test_oem_firmware_still_uses_the_stock_driver(self):
        with mock.patch.object(uvk5, '_sayhello',
                               return_value='k5_2.01.23'):
            self.assertIs(uvk5.UVK5Radio,
                          uvk5.UVK5Radio.detect_from_serial(object()))

    def test_registry_lookup(self):
        self.assertIs(uvk5_cn.UVK5LoseHuRadio,
                      directory.get_radio('Quansheng_UV-K5_losehu'))
        self.assertIs(uvk5.UVK5Radio,
                      directory.get_radio('Quansheng_UV-K5'))

    def test_class_does_not_own_detected_models(self):
        """tests/test_clone.py requires detect_from_serial() to be usable."""
        cls = uvk5_cn.UVK5LoseHuRadio
        self.assertFalse(hasattr(cls, 'DETECTED_MODELS_%s' % cls.__name__))
        with self.assertRaises(NotImplementedError):
            cls.detect_from_serial(object())


class TestPrompts(unittest.TestCase):

    def test_prompts(self):
        prompts = uvk5_cn.UVK5LoseHuRadio.get_prompts()
        for name in ('experimental', 'pre_download', 'pre_upload'):
            self.assertIsInstance(getattr(prompts, name), str)
        text = prompts.experimental
        # The verification status and the dangerous region must be stated
        self.assertIn('LOSEHU131HS', text)
        self.assertIn('verified', text)
        self.assertIn('0x40000', text)
        self.assertIn('multi-bootloader', text)
        # ... and it must not claim to be untested
        self.assertNotIn('not been tested', text)

    def test_prompts_available_on_the_class_and_an_instance(self):
        self.assertIsInstance(uvk5_cn.UVK5LoseHuRadio.get_prompts(),
                              chirp_common.RadioPrompts)
        radio = uvk5_cn.UVK5LoseHuRadio(None)
        self.assertIsInstance(radio.get_prompts(),
                              chirp_common.RadioPrompts)


class TestRealImage(unittest.TestCase):
    """Exercise the driver against the real LOSEHU131HS capture."""

    def setUp(self):
        self.radio = directory.get_radio_by_image(IMAGE)
        self.radio.status_fn = lambda status: True

    def test_detected_as_losehu_variant(self):
        self.assertIsInstance(self.radio, uvk5_cn.UVK5LoseHuRadio)
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
        self.assertEqual(EEPROM_SIZE, uvk5_cn.profile_mem_size(FIRMWARE))
        self.assertEqual(0x40000, len(self.radio._mmap))

    def test_channel_one_is_the_regression_anchor(self):
        mem = self.radio.get_memory(1)
        self.assertFalse(mem.empty)
        self.assertEqual(CH1_FREQ, mem.freq)
        self.assertEqual(CH1_NAME, mem.name)
        self.assertEqual('', mem.duplex)          # simplex
        self.assertEqual(0, mem.offset)
        self.assertEqual('FM', mem.mode)
        self.assertEqual('High', str(mem.power))
        self.assertEqual(2.5, mem.tuning_step)

    def test_other_real_channels(self):
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
        # Unused channels are marked 0xFF on disk
        self.assertEqual(0xff, attr_byte(self.radio, FIRST_EMPTY - 1))

    def test_non_empty_and_empty_channels(self):
        nonempty = [n for n in range(1, 201)
                    if not self.radio.get_memory(n).empty]
        self.assertEqual(list(range(1, FIRST_EMPTY)), nonempty)
        self.assertEqual(97, len(nonempty))
        for number in (FIRST_EMPTY, 150, 200):
            mem = self.radio.get_memory(number)
            self.assertTrue(mem.empty, number)
            self.assertEqual('', mem.name)
            self.assertEqual(6, len(mem.extra))

    def test_special_channels_are_not_offered(self):
        rf = self.radio.get_features()
        self.assertEqual([], rf.valid_special_chans)
        self.assertEqual((1, 200), rf.memory_bounds)
        self.assertEqual({}, self.radio._get_specials())

    def test_features(self):
        rf = self.radio.get_features()
        self.assertTrue(rf.has_settings)
        self.assertEqual(13, rf.valid_name_length)
        self.assertIn('\u4e2d', rf.valid_characters)
        self.assertEqual(24, len(rf.valid_tuning_steps))
        self.assertIn(8.33, rf.valid_tuning_steps)
        self.assertEqual((1, 200), rf.memory_bounds)
        self.assertEqual(18000000, rf.valid_bands[0][0])
        self.assertEqual(1300000000, rf.valid_bands[-1][1])

    def test_round_trip_of_every_channel_is_byte_identical(self):
        """Reading and writing every channel must not change one byte.

        This is the strongest cheap proof that the driver's delta over the
        base class is a no-op for real data: the channel records, the
        attributes (including the 0xFF "empty" spelling) and the names.
        """
        payload, _metadata = image_payload(IMAGE)
        self.assertEqual(payload, bytes(self.radio._mmap.get_packed()))

        for number in range(1, 201):
            self.radio.set_memory(self.radio.get_memory(number))

        self.assertEqual(payload, bytes(self.radio._mmap.get_packed()))

    def test_long_name_round_trips_without_being_shortened(self):
        mem = self.radio.get_memory(19)
        self.assertEqual('\u5e94\u6025\u901a\u4fe1\u7fbd\u6797\u5927\u961f',
                         mem.name)
        self.radio.set_memory(mem)
        self.assertEqual(mem.name, self.radio.get_memory(19).name)
        raw = bytes(self.radio._memobj.channelname[18].get_raw())
        self.assertEqual(16, len(raw.rstrip(b'\x00')))

    def test_unrepresentable_name_bytes_are_preserved(self):
        """Name bytes we cannot reproduce must not be rewritten."""
        field = self.radio._memobj.channelname[0]      # real channel 1
        raw = b'A\x80\x40B' + b'\x00' * 12
        field.set_raw(raw)

        mem = self.radio.get_memory(1)
        self.assertFalse(mem.empty)
        self.assertEqual('A?B', mem.name)
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

    def test_set_memory_round_trip_gb2312(self):
        number = FIRST_EMPTY
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 439000000
        mem.name = '\u4e2d\u7ee7\u53f0'
        self.radio.set_memory(mem)
        new = self.radio.get_memory(number)
        self.assertFalse(new.empty)
        self.assertEqual(439000000, new.freq)
        self.assertEqual('\u4e2d\u7ee7\u53f0', new.name)
        raw = self.radio._memobj.channelname[number - 1].get_raw()
        self.assertEqual('\u4e2d\u7ee7\u53f0'.encode('gb2312'),
                         bytes(raw[:6]))
        self.assertEqual(b'\x00' * 10, bytes(raw[6:]))

    def test_set_memory_round_trip_ascii(self):
        number = FIRST_EMPTY + 1
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 435000000
        mem.name = 'TEST'
        self.radio.set_memory(mem)
        new = self.radio.get_memory(number)
        self.assertEqual(435000000, new.freq)
        self.assertEqual('TEST', new.name)

    def test_delete_and_rewrite(self):
        number = FIRST_EMPTY + 2
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 145500000
        mem.name = 'GONE'
        self.radio.set_memory(mem)
        self.assertFalse(self.radio.get_memory(number).empty)

        mem.empty = True
        self.radio.set_memory(mem)
        self.assertTrue(self.radio.get_memory(number).empty)
        self.assertEqual(b'\xff' * 16,
                         bytes(self.radio._memobj.channel[number - 1]
                               .get_raw()))

    def test_already_empty_channel_is_left_alone(self):
        """An untouched empty channel keeps its 0xFF spelling."""
        index = FIRST_EMPTY - 1
        before = bytes(self.radio._memobj.channel_attributes[index].get_raw())
        self.radio.set_memory(self.radio.get_memory(FIRST_EMPTY))
        self.assertEqual(
            before,
            bytes(self.radio._memobj.channel_attributes[index].get_raw()))

    def test_tuning_step_round_trip_for_every_offered_step(self):
        number = FIRST_EMPTY + 3
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
        self.assertEqual(CH1_NAME, self.radio.get_memory(1).name)

    def test_get_memory_has_no_trailing_whitespace(self):
        number = FIRST_EMPTY + 4
        mem = self.radio.get_memory(number)
        mem.empty = False
        mem.freq = 145000000
        mem.name = 'PAD '
        self.radio.set_memory(mem)
        self.assertEqual('PAD', self.radio.get_memory(number).name)

    def test_validate_memory_accepts_every_real_channel(self):
        """No channel of the capture may produce a warning.

        CHIRP's generated sample image test asserts that validate_memory()
        returns no warnings for any channel of the image
        (tests/test_brute_force.py:202 unpacks split_validation_msgs() the
        other way round, so its "errs" holds the warnings).  The single
        error is CHIRP's core airband policy on channel 91 (121.745 MHz, a
        gap in the 8.33 kHz channel scheme), which this driver does not
        override.
        """
        warnings = 0
        errors_seen = []
        for number in range(1, 201):
            mem = self.radio.get_memory(number)
            if mem.empty:
                continue
            warns, errs = split_msgs(self.radio.validate_memory(mem))
            warnings += len(warns)
            if errs:
                errors_seen.append((number, str(errs[0])))

        self.assertEqual(0, warnings)
        self.assertEqual([91], [number for number, _ in errors_seen])
        self.assertIn('Aircraft frequencies', errors_seen[0][1])

    def test_validate_memory_rejects_name_wider_than_the_field(self):
        mem = self.radio.get_memory(1)
        mem.name = '\u4e2d' * 9                  # 18 bytes > 16
        warns, errs = split_msgs(self.radio.validate_memory(mem))
        self.assertEqual(1, len(errs))
        self.assertIn('16 bytes', str(errs[0]))

    def test_validate_memory_is_silent_about_the_editor_limit(self):
        """A name past the radio's editor limit but inside the field is
        accepted without a message: the field holds it and this driver keeps
        it byte for byte."""
        mem = self.radio.get_memory(1)
        mem.name = '\u4e2d' * 7                  # 14 bytes: field ok
        self.assertFalse(uvk5_cn.name_fits(mem.name, uvk5_cn.NAME_BYTES))
        self.assertTrue(uvk5_cn.name_fits(mem.name, uvk5_cn.NAME_LENGTH))
        warns, errs = split_msgs(self.radio.validate_memory(mem))
        self.assertEqual([], warns)
        self.assertEqual([], errs)

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
        self.assertEqual(0x40000, self.radio.eeprom_size)
        settings = self.radio.get_settings()
        for group in settings:
            for setting in group:
                if setting.get_name() == 'eeprom_size':
                    setting.value.set_value('0x10000 (64 KiB)')
        self.radio.set_settings(settings)
        self.assertEqual(0x10000, self.radio.eeprom_size)

    def test_bitwise_parses_the_image_without_errors(self):
        with mock.patch.object(bitwise.LOG, 'error') as mock_error:
            self.radio.process_mmap()
            self.assertFalse(mock_error.called,
                             [x[0][0] for x in mock_error.call_args_list])

    def test_a_corrupt_tone_nibble_does_not_crash_get_memory(self):
        """uvk5's _get_tone indexes TMODES with the raw nibble.

        Radios only write tone types 0..3 (dcs.h:22-30), but a partially
        written record can hold 0xFF there, which would raise IndexError
        while loading an image.
        """
        image = bytearray(b'\xFF' * 0x2000)
        image[0x00:0x04] = struct.pack('<L', 435587500 // 10)
        image[0x0d60] = 0x05
        radio = uvk5_cn.UVK5LoseHuRadio(None)
        radio.metadata = {'uvk5_firmware': FIRMWARE}
        radio._mmap = memmap.MemoryMapBytes(bytes(image))
        radio._eeprom_size = 0x2000
        radio.process_mmap()
        mem = radio.get_memory(1)               # must not raise
        self.assertFalse(mem.empty)
        self.assertEqual('', mem.tmode)
        self.assertEqual(435587500, mem.freq)


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
        self.assertEqual([], serport.written)

    def test_writemem_refuses_a_block_that_crosses_the_limit(self):
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])))
        with self.assertRaises(errors.RadioError):
            uvk5_cn._writemem(serport, b'\x00' * 0x40, 0x3ffd0)
        self.assertEqual([], serport.written)

    def test_writemem_allows_the_last_block_below_the_limit(self):
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])))
        self.assertTrue(uvk5_cn._writemem(serport, b'\x00' * 0x40, 0x3ffc0))

    def test_readmem_refuses_the_bootloader_region(self):
        serport = FakeSerial()
        with self.assertRaises(errors.RadioError):
            uvk5_cn._readmem(serport, 0x40000, 0x80)
        self.assertEqual([], serport.written)

    def test_upload_refuses_an_image_that_reaches_the_bootloader(self):
        radio = uvk5_cn.UVK5LoseHuRadio(None)
        radio.status_fn = lambda status: True
        radio.pipe = FakeSerial()
        radio._mmap = memmap.MemoryMapBytes(bytes(0x80000))
        radio._eeprom_size = 0x2000     # so the *image* length trips the guard
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5.do_upload(radio)
        message = str(caught.exception)
        self.assertIn('524288', message)
        self.assertIn('0x40000', message)
        self.assertIn('multi-bootloader', message)

    def test_upload_refuses_a_size_past_the_limit(self):
        radio = uvk5_cn.UVK5LoseHuRadio(None)
        radio.status_fn = lambda status: True
        radio.pipe = FakeSerial()
        radio._mmap = memmap.MemoryMapBytes(bytes(0x2000))
        radio._eeprom_size = 0x80000
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5.do_upload(radio)
        self.assertIn('0x40000', str(caught.exception))

    def test_download_refuses_a_size_past_the_limit(self):
        radio = uvk5_cn.UVK5LoseHuRadio(None)
        radio.status_fn = lambda status: True
        radio.pipe = FakeSerial()
        radio._eeprom_size = 0x80000
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5.do_download(radio)
        self.assertIn('0x40000', str(caught.exception))

    def test_real_image_is_inside_the_limit(self):
        payload, metadata = image_payload(IMAGE)
        self.assertEqual(0x40000, len(payload))
        self.assertLessEqual(len(payload), uvk5_cn.DATA_LIMIT)
        self.assertEqual(FIRMWARE, metadata['uvk5_firmware'])


class TestOemNamePath(unittest.TestCase):
    """The byte-native name handling in the base class must not change the
    bytes the OEM driver writes."""

    def test_oem_image_name_round_trip_is_byte_identical(self):
        radio = directory.get_radio_by_image(OEM_IMAGE)
        before = bytes(radio._mmap.get_packed())
        names = {}
        for number in range(1, 201):
            mem = radio.get_memory(number)
            if mem.empty:
                continue
            names[number] = bytes(radio._memobj.channelname[number - 1]
                                  .get_raw())
            radio.set_memory(mem)
        after = bytes(radio._mmap.get_packed())
        for number, raw in names.items():
            self.assertEqual(raw, bytes(radio._memobj.channelname[number - 1]
                                        .get_raw()), 'name %i' % number)
        diffs = [i for i in range(len(before)) if before[i] != after[i]]
        self.assertEqual([], diffs)

    def test_oem_name_read_stops_at_nul_and_ff(self):
        radio = directory.get_radio_by_image(OEM_IMAGE)
        field = radio._memobj.channelname[0]
        field.set_raw(b'AB' + b'\x00' * 14)
        self.assertEqual('AB', radio.get_memory(1).name)
        field.set_raw(b'CD' + b'\xff' * 14)
        self.assertEqual('CD', radio.get_memory(1).name)

    def test_oem_name_write_is_space_padded(self):
        radio = directory.get_radio_by_image(OEM_IMAGE)
        mem = radio.get_memory(1)
        mem.name = 'XYZ'
        radio.set_memory(mem)
        self.assertEqual(b'XYZ' + b' ' * 7 + b'\x00' * 6,
                         bytes(radio._memobj.channelname[0].get_raw()))


@unittest.skipIf(not os.path.exists(IMAGE), 'test image missing')
class TestCloneWithFakeSerial(unittest.TestCase):
    """Download and upload over a fake serial port."""

    READ_DATA = bytes(range(0x80))

    def setUp(self):
        self.radio = uvk5_cn.UVK5LoseHuRadio(None)
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
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            mmap = uvk5.do_download(self.radio)
        return serport, mmap

    def test_download_reads_the_requested_size(self):
        size = 0x2000
        response = self._read_reply(self.READ_DATA) * (size // 0x80)
        serport, mmap = self._download(response, size=size)
        self.assertEqual(size, len(mmap.get_packed()))
        self.assertEqual(size // 0x80, len(serport.written))
        for index, frame in enumerate(serport.written):
            payload = unframe(frame)
            self.assertEqual(0x2b, payload[0])
            self.assertEqual(uvk5_cn.TIMESTAMP, payload[8:12])
            self.assertEqual(struct.pack('<H', (index * 0x80) & 0xffff),
                             payload[12:14])
        self.assertEqual(FIRMWARE, self.radio.metadata['uvk5_firmware'])
        self.assertEqual(self.READ_DATA * (size // 0x80), mmap.get_packed())

    def test_download_raises_when_profile_over_estimates(self):
        # A profile that over-estimates the EEPROM must fail loudly rather
        # than hand the user a short image that they might upload back
        response = self._read_reply(self.READ_DATA) * 64    # exactly 0x2000
        with self.assertRaises(errors.RadioError):
            self._download(response)

    def test_download_fails_if_no_usable_image(self):
        with self.assertRaises(errors.RadioError):
            self._download(b'', fail_after=0, size=0x2000)

    def test_download_rejects_unsupported_firmware(self):
        self.radio.pipe = FakeSerial()
        with mock.patch.object(uvk5, '_sayhello', return_value='BOGUS'):
            with self.assertRaises(errors.RadioError):
                uvk5.do_download(self.radio)

    def test_upload_writes_prog_size_and_resets(self):
        self.radio._mmap = memmap.MemoryMapBytes(bytes(range(0x100)) * 0x20)
        self.radio._eeprom_size = 0x2000
        nwrites = 0x1d00 // 0x40
        serport = FakeSerial(make_reply(bytes([0x1e, 0x05])) * nwrites)
        self.radio.pipe = serport
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            self.assertTrue(uvk5.do_upload(self.radio))
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
        with mock.patch.object(uvk5, '_sayhello', return_value=FIRMWARE):
            with self.assertRaises(errors.RadioError) as caught:
                uvk5.do_upload(self.radio)
        message = str(caught.exception)
        self.assertIn('8192', message)          # loaded image length
        self.assertIn('todo', message)          # its profile
        self.assertIn('losehu124h', message)    # radio profile
        self.assertIn('262144', message)        # profile default
        self.assertIn('EEPROM size', message)

    def test_upload_rejects_unsupported_firmware(self):
        self.radio._mmap = memmap.MemoryMapBytes(bytes(0x2000))
        self.radio.pipe = FakeSerial()
        with mock.patch.object(uvk5, '_sayhello', return_value='BOGUS'):
            with self.assertRaises(errors.RadioError):
                uvk5.do_upload(self.radio)

    def test_sync_in_with_silent_serial_raises_radio_error(self):
        self.radio.pipe = FakeSerial()
        with self.assertRaises(errors.RadioError):
            self.radio.sync_in()


if __name__ == '__main__':
    unittest.main()
