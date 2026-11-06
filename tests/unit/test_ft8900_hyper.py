from pathlib import Path
import tempfile
import unittest
from unittest import mock

from chirp import chirp_common, directory, errors, memmap
from chirp.drivers.ft7800 import FT8900Radio
from chirp.settings import (RadioSetting, RadioSettingGroup, RadioSettings,
                            RadioSettingValueString)


FIXTURE = Path(__file__).parents[1] / 'images' / 'Yaesu_FT-8900.img'
# Independent clone captures established these 6 bases and the LE words
# for channels 001, 010, 100, 200, 400 and 600. The public fixture supplies
# ordinary channels; no private radio image is required for these tests.
BASES = (0x288, 0x348, 0x408, 0x4C8, 0x588, 0x648)
WORDS = (b'\x00\x00', b'\x09\x00', b'\x63\x00',
         b'\xC7\x00', b'\x8F\x01', b'\x57\x02')
CHANNELS = (1, 10, 100, 200, 400, 600)


def choose_memory(settings, slot, channel):
    value = settings[f'hyper{slot}'][f'hyper{slot}_memory'].value
    value.set_value(next(option for option in value.get_options()
                         if option.startswith(f'{channel:03d} ')))


def forged_setting(name, value):
    field = RadioSetting(name, name, RadioSettingValueString(0, 80, 'initial'))
    field.value = value
    group = RadioSettingGroup('forged', 'Forged')
    group.append(field)
    return group


class TestFT8900Hyper(unittest.TestCase):
    def setUp(self):
        serial = mock.patch('serial.Serial',
                            side_effect=AssertionError('Unexpected radio I/O'))
        self.serial = serial.start()
        self.addCleanup(serial.stop)
        self.addCleanup(self.serial.assert_not_called)
        self.stock = FT8900Radio(str(FIXTURE))
        self.stock_data = self.stock.get_mmap().get_packed()
        for channel in CHANNELS + (3, 299, 700):
            memory = chirp_common.Memory()
            memory.number = channel
            memory.freq = 430250000
            memory.name = 'TEST'
            self.stock.set_memory(memory)
        payload = bytearray(self.stock.get_mmap().get_packed())
        for base, word in zip(BASES, WORDS):
            payload[base + 0x90:base + 0x98] = (
                b'\x02\x00\x00\x00' + word + b'\x00\x00')
            payload[base + 0x9B] = 0xB1  # Preserve unmodelled low bits.
            payload[base + 0x9D] = 0x08
        payload[-1] = sum(payload[:-1]) % 256
        self.data = bytes(payload)
        self.radio = FT8900Radio(memmap.MemoryMapBytes(self.data))

    def assert_checksum(self, data):
        self.assertEqual(sum(data[:-1]) % 256, data[-1])

    def test_existing_vfo_fixture_is_readonly_and_byte_identical(self):
        radio = FT8900Radio(str(FIXTURE))
        settings = radio.get_settings()
        self.assertTrue(radio.get_features().has_settings)
        self.assertEqual(len(settings), 6)
        self.assertFalse(any(s.value.get_mutable() for s in settings.walk()))
        radio.set_settings(settings)
        self.assertEqual(radio.get_mmap().get_packed(), self.stock_data)

    def test_supported_profiles_and_noop(self):
        settings = self.radio.get_settings()
        self.assertEqual(sum(s.value.get_mutable()
                             for s in settings.walk()), 18)
        for slot, channel in enumerate(CHANNELS, 1):
            group = settings[f'hyper{slot}']
            self.assertTrue(str(group[f'hyper{slot}_memory'].value).startswith(
                f'{channel:03d} '))
            self.assertEqual(str(group[f'hyper{slot}_main'].value), 'Left')
            self.assertEqual(str(group[f'hyper{slot}_scan'].value), 'MEM')
            self.assertTrue(all(s.__doc__ for s in group.walk()))
        self.radio.set_settings(settings)
        self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_all_six_channel_edits_are_isolated_and_reversible(self):
        # Hardware channel700 encoded as BB02; check both bytes and carry.
        for slot, (base, channel) in enumerate(zip(BASES, CHANNELS), 1):
            with self.subTest(slot=slot):
                settings = self.radio.get_settings()
                choose_memory(settings, slot, 700)
                self.radio.set_settings(settings)
                changed = self.radio.get_mmap().get_packed()
                self.assertEqual(changed[base + 0x94:base + 0x96], b'\xBB\x02')
                allowed = {base + 0x94, base + 0x95, 0x39C8}
                self.assertTrue(all(i in allowed for i in range(len(changed))
                                    if changed[i] != self.data[i]))
                self.assert_checksum(changed)
                settings = self.radio.get_settings()
                choose_memory(settings, slot, channel)
                self.radio.set_settings(settings)
                self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_main_and_scan_preserve_other_bits_and_reverse(self):
        for slot, base in enumerate(BASES, 1):
            for field, value, offset, expected in (
                    ('main', 'Right', base + 0x9B, 0x31),
                    ('scan', 'MSM', base + 0x9D, 0x0A)):
                with self.subTest(slot=slot, field=field):
                    settings = self.radio.get_settings()
                    field_setting = settings[f'hyper{slot}'][
                        f'hyper{slot}_{field}']
                    field_setting.value = value
                    self.radio.set_settings(settings)
                    changed = self.radio.get_mmap().get_packed()
                    self.assertEqual(changed[offset], expected)
                    self.assertEqual(
                        {i for i in range(len(changed))
                         if changed[i] != self.data[i]}, {offset, 0x39C8})
                    self.assert_checksum(changed)
                    settings = self.radio.get_settings()
                    settings[f'hyper{slot}'][f'hyper{slot}_{field}'].value = (
                        'Left' if field == 'main' else 'MEM')
                    self.radio.set_settings(settings)
                    self.assertEqual(self.radio.get_mmap().get_packed(),
                                     self.data)

    def test_memory_edit_in_msm_keeps_scan_mode(self):
        settings = self.radio.get_settings()
        settings['hyper2']['hyper2_scan'].value = 'MSM'
        self.radio.set_settings(settings)
        settings = self.radio.get_settings()
        choose_memory(settings, 2, 700)
        self.radio.set_settings(settings)
        self.assertEqual(self.radio.get_mmap()[0x3E5], b'\x0A')
        self.assertEqual(str(self.radio.get_settings()['hyper2'][
            'hyper2_scan'].value), 'MSM')

    def test_unsupported_patterns_are_readonly_and_reject_forged_writes(self):
        for base in BASES:
            for offset, value in ((0x90, 0), (0x91, 1), (0x96, 1),
                                  (0x9D, 0), (0x9D, 2), (0x9D, 9),
                                  (0x9D, 11), (0x9D, 0xFF)):
                with self.subTest(base=base, offset=offset, value=value):
                    payload = bytearray(self.data)
                    payload[base + offset] = value
                    radio = FT8900Radio(memmap.MemoryMapBytes(bytes(payload)))
                    slot = BASES.index(base) + 1
                    self.assertFalse(any(s.value.get_mutable() for s in
                                         radio.get_settings()[
                                             f'hyper{slot}'].walk()))
                    settings = RadioSettings(forged_setting(
                        f'hyper{slot}_main', 'Right'))
                    with self.assertRaises(errors.RadioError):
                        radio.set_settings(settings)
                    self.assertEqual(radio.get_mmap().get_packed(),
                                     bytes(payload))

    def test_invalid_and_empty_current_channels_are_readonly(self):
        for word in (b'\x1F\x03', b'\xFF\xFF'):
            payload = bytearray(self.data)
            payload[0x31C:0x31E] = word
            radio = FT8900Radio(memmap.MemoryMapBytes(bytes(payload)))
            self.assertFalse(any(s.value.get_mutable() for s in
                                 radio.get_settings()['hyper1'].walk()))
        memory = self.radio.get_memory(1)
        memory.empty = True
        self.radio.set_memory(memory)
        self.assertFalse(any(s.value.get_mutable() for s in
                             self.radio.get_settings()['hyper1'].walk()))

    def test_invalid_later_setting_does_not_partially_commit(self):
        for name, value in (('hyper7_main', 'Right'),
                            ('hyper2_main', 'invalid'),
                            ('hyper2_scan', 'invalid'),
                            ('hyper2_memory', '001 missing'),
                            ('hyper1_memory', 'duplicate'),
                            ('hyper1_mode', 'VFO')):
            with self.subTest(name=name):
                settings = self.radio.get_settings()
                choose_memory(settings, 1, 700)
                settings.append(forged_setting(name, value))
                with self.assertRaises(errors.RadioError):
                    self.radio.set_settings(settings)
                self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_deleted_target_is_rejected_using_current_channels(self):
        settings = self.radio.get_settings()
        choose_memory(settings, 2, 700)
        memory = self.radio.get_memory(700)
        memory.empty = True
        self.radio.set_memory(memory)
        before = self.radio.get_mmap().get_packed()
        with self.assertRaises(errors.RadioError):
            self.radio.set_settings(settings)
        self.assertEqual(self.radio.get_mmap().get_packed(), before)

    def test_renamed_or_retuned_target_keeps_its_channel_number(self):
        settings = self.radio.get_settings()
        choose_memory(settings, 2, 700)
        memory = self.radio.get_memory(700)
        memory.name = 'NEW'
        memory.freq = 430275000
        self.radio.set_memory(memory)
        before = self.radio.get_mmap().get_packed()
        self.radio.set_settings(settings)
        changed = self.radio.get_mmap().get_packed()
        self.assertEqual(changed[0x3DC:0x3DE], b'\xBB\x02')
        self.assertEqual(changed[0x708:0x38F8], before[0x708:0x38F8])
        self.assertEqual(self.radio.get_memory(700).name, 'NEW')
        self.assertEqual(self.radio.get_memory(700).freq, 430275000)

    def test_ordinary_edits_and_pending_checksums_still_work(self):
        memory_map = self.radio.get_mmap()
        memory = self.radio.get_memory(1)
        self.assertFalse(memory.immutable)
        memory.freq = 430275000
        self.radio.set_memory(memory)
        before = memory_map.get_packed()
        settings = self.radio.get_settings()
        self.radio.set_settings(settings)
        self.assertEqual(memory_map.get_packed(), before)
        settings = self.radio.get_settings()
        settings['hyper2']['hyper2_scan'].value = 'MSM'
        self.radio.set_settings(settings)
        self.assertIs(self.radio.get_mmap(), memory_map)
        self.assertEqual(self.radio.get_memory(1).freq, 430275000)
        self.assertEqual(memory_map[0x708:0x38F8], before[0x708:0x38F8])
        self.assert_checksum(memory_map.get_packed())
        memory.freq = 430300000
        self.radio.set_memory(memory)
        self.assertEqual(self.radio.get_memory(1).freq, 430300000)
        self.assertEqual(memory_map[0x3E5], b'\x0A')

    def test_saved_images_keep_standard_model_and_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'hyper.img'
            self.radio.save(str(path))
            payload, metadata = chirp_common.CloneModeRadio._strip_metadata(
                path.read_bytes())
            self.assertEqual(metadata['model'], 'FT-8900')
            self.assertNotIn('ft8900_hyper_schema', metadata)
            self.assertEqual(payload, self.data)
            reopened = directory.get_radio_by_image(str(path))
            self.assertIsInstance(reopened, FT8900Radio)
            self.assertEqual(reopened.get_mmap().get_packed(), self.data)
