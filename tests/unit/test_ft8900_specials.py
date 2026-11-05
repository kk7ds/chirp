from pathlib import Path
import tempfile
import unittest
from unittest import mock

from chirp import chirp_common, directory, errors, memmap
from chirp.drivers import ft7800


FIXTURE = Path(__file__).parents[1] / 'images' / 'Yaesu_FT-8900.img'
# Compact records from physical stores, recalls and independent downloads.
RECORDS = {
    0x0228: '90 81 45 52 08 00 00 60 0c 00 00 00 00 00 c0 00',
    0x0258: '90 84 32 52 08 00 07 60 0c 00 00 00 80 40 80 00',
    0x38F8: '90 01 44 00 08 00 00 60 0c 00 00 05 00 00 c0 00',
    0x3908: '93 01 46 00 08 00 00 60 0c 00 00 05 00 00 c0 00',
    0x3918: '90 04 30 00 08 00 07 60 0c 00 00 05 80 40 80 00',
    0x3928: '90 04 40 00 08 00 07 60 0c 00 00 05 80 40 80 00',
}
PMS_NAMES = ['L1', 'U1', 'L2', 'U2', 'L3', 'U3', 'L4', 'U4', 'L5', 'U5']


class TestFT8900Specials(unittest.TestCase):
    def setUp(self):
        patch = mock.patch('serial.Serial',
                           side_effect=AssertionError('Unexpected radio I/O'))
        self.serial = patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.serial.assert_not_called)
        self.public = ft7800.FT8900Radio(str(FIXTURE))
        payload = bytearray(self.public.get_mmap().get_packed())
        for offset, record in RECORDS.items():
            payload[offset:offset + 16] = bytes.fromhex(record)
        payload[-1] = sum(payload[:-1]) % 256
        self.data = bytes(payload)
        self.radio = self.new_radio()

    def new_radio(self, data=None):
        return ft7800.FT8900Radio(memmap.MemoryMapBytes(
            self.data if data is None else data))

    def assert_only_changed(self, before, after, allowed):
        self.assertTrue(all(i in allowed for i in range(len(before))
                            if before[i] != after[i]))
        self.assertEqual(sum(after[:-1]) % 256, after[-1])

    def test_layout_stays_inside_clone_image(self):
        self.assertEqual(len(self.radio.get_mmap()), 0x39C9)
        self.assertEqual(self.radio._memobj.homes[2].get_offset(), 0x228)
        self.assertEqual(self.radio._memobj.homes[5].get_offset(), 0x258)
        self.assertEqual(self.radio._memobj.pms[0].get_offset(), 0x38F8)
        self.assertEqual(self.radio._memobj.pms[9].get_offset(), 0x3988)
        self.assertEqual(self.radio._memobj.reserved.get_offset(), 0x3998)
        self.assertEqual(self.radio._memobj.checksum.get_offset(), 0x39C8)

    def test_hardware_records_and_numeric_aliases(self):
        expected = [('HOME 144', 812, 145525000),
                    ('HOME 430', 814, 432525000),
                    ('L1', 800, 144000000), ('U1', 801, 146000000),
                    ('L2', 802, 430000000), ('U2', 803, 440000000)]
        for label, number, frequency in expected:
            with self.subTest(label=label):
                memory = self.radio.get_memory(label)
                self.assertFalse(memory.empty)
                self.assertEqual(memory.number, number)
                self.assertEqual(memory.extd_number, label)
                self.assertEqual(memory.freq, frequency)
                self.assertEqual(str(memory.power), 'Mid2')
                self.assertEqual(vars(memory),
                                 vars(self.radio.get_memory(number)))
        self.assertEqual(self.radio.get_memory('U1').duplex, '+')
        self.assertEqual(self.radio.get_memory('U1').offset, 600000)

    def test_factory_home_is_available_without_used_bit(self):
        memory = self.public.get_memory('HOME 144')
        self.assertFalse(memory.empty)
        self.assertEqual(memory.freq, 144000000)
        self.assertIn('empty', memory.immutable)
        self.assertTrue(self.public.get_memory('L1').empty)

    def test_noop_preserves_every_byte_including_unknown_records(self):
        for radio in (self.radio, self.public):
            before = radio.get_mmap().get_packed()
            for label in radio.get_features().valid_special_chans:
                radio.set_memory(radio.get_memory(label))
            self.assertEqual(radio.get_mmap().get_packed(), before)

    def test_home_frequency_edits_are_isolated_and_reversible(self):
        for label, offset, original, target, raw in (
                ('HOME 144', 0x228, 145525000, 144000000, b'\x01\x44\x00'),
                ('HOME 430', 0x258, 432525000, 430000000, b'\x04\x30\x00')):
            with self.subTest(label=label):
                memory = self.radio.get_memory(label)
                memory.freq = target
                self.radio.set_memory(memory)
                changed = self.radio.get_mmap().get_packed()
                self.assertEqual(changed[offset + 1:offset + 4], raw)
                self.assert_only_changed(self.data, changed,
                                         {offset + 1, offset + 2,
                                          offset + 3, 0x39C8})
                memory.freq = original
                self.radio.set_memory(memory)
                self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_home_power_encoding_matches_physical_mid2_store(self):
        payload = bytearray(self.data)
        payload[0x22C] = 0
        payload[-1] = sum(payload[:-1]) % 256
        radio = self.new_radio(bytes(payload))
        memory = radio.get_memory('HOME 144')
        self.assertEqual(str(memory.power), 'Hi')
        memory.power = radio.POWER_LEVELS_VHF[2]
        radio.set_memory(memory)
        self.assertEqual(radio.get_mmap().get_packed(), self.data)

    def test_all_pms_addresses_are_isolated_from_reserved_tail(self):
        for index, label in enumerate(PMS_NAMES):
            radio = self.new_radio()
            memory = radio.get_memory(label)
            memory.empty = False
            memory.freq = 29100000 if label.startswith('L') else 29200000
            memory.power = radio.POWER_LEVELS_VHF[2]
            memory.duplex = ''
            radio.set_memory(memory)
            changed = radio.get_mmap().get_packed()
            offset = 0x38F8 + index * 16
            self.assert_only_changed(
                self.data, changed, {offset, offset + 1, offset + 2,
                                     offset + 3, offset + 4, 0x39C8})
            self.assertEqual(radio.get_memory(label).freq, memory.freq)
            self.assertEqual(changed[0x3998:0x39C8], self.data[0x3998:0x39C8])

    def test_pms_clear_inherited_shift_preserves_offset_bytes(self):
        memory = self.radio.get_memory('U1')
        memory.duplex = ''
        self.radio.set_memory(memory)
        changed = self.radio.get_mmap().get_packed()
        self.assertEqual(changed[0x3908], 0x90)
        self.assertEqual(self.radio.get_memory('U1').duplex, '')
        self.assert_only_changed(self.data, changed, {0x3908, 0x39C8})

    def test_pms_delete_preserves_record_contents(self):
        memory = self.radio.get_memory('L1')
        memory.empty = True
        self.radio.set_memory(memory)
        self.assertTrue(self.radio.get_memory('L1').empty)
        changed = self.radio.get_mmap().get_packed()
        self.assert_only_changed(self.data, changed, {0x38F8, 0x39C8})
        self.assertEqual(changed[0x38F8], self.data[0x38F8] & 0x7F)

    def test_home_deletion_and_readonly_fields_rejected_atomically(self):
        for field, value in [('empty', True), ('name', 'NO'),
                             ('mode', 'AM'), ('duplex', '+'),
                             ('rtone', 88.5), ('offset', 1000000)]:
            with self.subTest(field=field):
                memory = self.radio.get_memory('HOME 144')
                memory.immutable = []
                memory.freq = 145500000
                setattr(memory, field, value)
                with self.assertRaises(errors.RadioError):
                    self.radio.set_memory(memory)
                self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_invalid_frequency_and_power_rejected_atomically(self):
        values = [('freq', 432525000), ('freq', 145856250),
                  ('power', chirp_common.PowerLevel('Bad', watts=17))]
        for field, value in values:
            with self.subTest(field=field):
                memory = self.radio.get_memory('HOME 144')
                setattr(memory, field, value)
                with self.assertRaises(errors.RadioError):
                    self.radio.set_memory(memory)
                self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_home_validation_reports_band_and_grid_errors(self):
        memory = self.radio.get_memory('HOME 144')
        for frequency in (432525000, 145856250):
            memory.freq = frequency
            messages = self.radio.validate_memory(memory)
            self.assertTrue(any(isinstance(m, chirp_common.ValidationError)
                                for m in messages))

    def test_unknown_labels_and_numbers_rejected(self):
        for number in ('L6', 'HOME 223', 0, 816, -1):
            with self.subTest(number=number):
                with self.assertRaises(errors.InvalidMemoryLocation):
                    self.radio.get_memory(number)
                with self.assertRaises(errors.InvalidMemoryLocation):
                    self.radio.get_raw_memory(number)

    def test_bad_pms_pairs_block_upload_before_transport(self):
        for lower, upper in ((146000000, 146000000),
                             (147000000, 146000000),
                             (144000000, 430000000)):
            with self.subTest(lower=lower, upper=upper):
                radio = self.new_radio()
                for label, frequency in [('L1', lower), ('U1', upper)]:
                    memory = radio.get_memory(label)
                    memory.freq = frequency
                    radio.set_memory(memory)
                before = radio.get_mmap().get_packed()
                with mock.patch.object(ft7800, '_upload') as upload:
                    with self.assertRaises(errors.RadioError):
                        radio.sync_out()
                    upload.assert_not_called()
                self.assertEqual(radio.get_mmap().get_packed(), before)

    def test_valid_pairs_reuse_existing_upload(self):
        with mock.patch.object(ft7800, '_upload') as upload:
            self.radio.sync_out()
            upload.assert_called_once_with(self.radio)
        self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_upload_validation_does_not_require_parsed_state(self):
        radio = ft7800.FT8900Radio(None)
        radio._mmap = memmap.MemoryMapBytes(self.data)
        self.assertIsNone(radio._memobj)
        with mock.patch.object(ft7800, '_upload') as upload:
            radio.sync_out()
            upload.assert_called_once_with(radio)
        payload = bytearray(self.data)
        payload[0x3909:0x390C] = b'\x01\x44\x00'
        radio._mmap = memmap.MemoryMapBytes(bytes(payload))
        with mock.patch.object(ft7800, '_upload') as upload:
            with self.assertRaises(errors.RadioError):
                radio.sync_out()
            upload.assert_not_called()

    def test_ordinary_views_survive_special_write(self):
        original_map = self.radio.get_mmap()
        memory = self.radio.get_memory('HOME 144')
        memory.freq = 145500000
        self.radio.set_memory(memory)
        ordinary = self.radio.get_memory(1)
        if ordinary.empty:
            ordinary = chirp_common.Memory()
            ordinary.number = 1
        ordinary.empty = False
        ordinary.freq = 145550000
        self.radio.set_memory(ordinary)
        self.assertIs(self.radio.get_mmap(), original_map)
        self.assertEqual(self.radio.get_memory(1).freq, 145550000)
        self.assertEqual(self.radio.get_memory('HOME 144').freq, 145500000)

    def test_saved_image_keeps_standard_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'specials.img'
            self.radio.save(str(path))
            payload, metadata = chirp_common.CloneModeRadio._strip_metadata(
                path.read_bytes())
            self.assertEqual(metadata['model'], 'FT-8900')
            self.assertEqual(payload, self.data)
            reopened = directory.get_radio_by_image(str(path))
            self.assertEqual(reopened.get_memory('HOME 430').freq, 432525000)
            self.assertEqual(reopened.get_memory('U2').freq, 440000000)
