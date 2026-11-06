from pathlib import Path
import unittest
from unittest import mock

from chirp import chirp_common, errors
from chirp.drivers.ft7800 import FT8900Radio


FIXTURE = Path(__file__).parents[1] / 'images' / 'Yaesu_FT-8900.img'
BANDS = ('L29', 'L50', 'L144', 'L350', 'L430', 'L850', 'R144', 'R430')
# The 223 MHz left record is reserved; right-side records follow all seven
# left records. Hardware captures independently located right UHF at +0x80.
RECORDS = (0, 1, 2, 4, 5, 6, 7, 8)
FREQUENCIES = (29025000, 50025000, 144025000, 350025000,
               430025000, 850025000, 144025000, 430025000)


class TestFT8900VFOs(unittest.TestCase):
    def setUp(self):
        serial = mock.patch('serial.Serial',
                            side_effect=AssertionError('Unexpected radio I/O'))
        self.serial = serial.start()
        self.addCleanup(serial.stop)
        self.addCleanup(self.serial.assert_not_called)
        self.radio = FT8900Radio(str(FIXTURE))
        self.data = self.radio.get_mmap().get_packed()

    def test_all_profiles_expose_eight_per_band_vfos(self):
        features = self.radio.get_features()
        self.assertEqual(len(features.valid_special_chans), 64)
        for slot in range(1, 7):
            for index, band in enumerate(BANDS):
                memory = self.radio.get_memory(f'H{slot} {band}')
                self.assertFalse(memory.empty)
                self.assertEqual(memory.number, 816 + (slot - 1) * 8 + index)
                self.assertEqual(memory.extd_number, f'H{slot} {band}')
                self.assertEqual(vars(memory), vars(self.radio.get_memory(
                    memory.number)))
                self.assertIn('empty', memory.immutable)
                self.assertNotIn('freq', memory.immutable)

    def test_noop_preserves_all_records_and_pending_checksum(self):
        # No-op must not normalize dormant VFO settings or other state.
        for slot in range(1, 7):
            for band in BANDS:
                self.radio.set_memory(self.radio.get_memory(f'H{slot} {band}'))
        self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_right_uhf_frequency_matches_physical_capture_encoding(self):
        memory = self.radio.get_memory('H2 R430')
        memory.freq = 430025000
        self.radio.set_memory(memory)
        changed = self.radio.get_mmap().get_packed()
        self.assertEqual(changed[0x3C9:0x3CC], b'\x84\x30\x02')
        self.assertEqual({i for i in range(len(changed))
                          if changed[i] != self.data[i]},
                         {0x3C9, 0x3CB, 0x39C8})

    def test_all_vfo_frequency_writes_preserve_other_bands_and_profiles(self):
        for slot in range(1, 7):
            for band, index, freq in zip(BANDS, RECORDS, FREQUENCIES):
                with self.subTest(slot=slot, band=band):
                    radio = FT8900Radio(str(FIXTURE))
                    memory = radio.get_memory(f'H{slot} {band}')
                    memory.freq = freq
                    radio.set_memory(memory)
                    changed = radio.get_mmap().get_packed()
                    offset = 0x288 + (slot - 1) * 0xC0 + index * 16
                    allowed = {offset + 1, offset + 2, offset + 3, 0x39C8}
                    self.assertTrue(all(i in allowed for i in
                                        range(len(changed))
                                        if changed[i] != self.data[i]))
                    self.assertEqual(radio.get_memory(memory.number).freq,
                                     freq)
                    self.assertEqual(sum(changed[:-1]) % 256, changed[-1])

    def test_two_profiles_retain_different_vhf_and_uhf_settings(self):
        plans = [('H1 L144', 145525000, '', 0, '', 88.5),
                 ('H1 L430', 432525000, '', 0, '', 88.5),
                 ('H2 L144', 145750000, '-', 600000, 'Tone', 77.0),
                 ('H2 L430', 438650000, '-', 7600000, 'Tone', 131.8)]
        for label, freq, duplex, offset, tmode, tone in plans:
            memory = self.radio.get_memory(label)
            memory.freq, memory.duplex, memory.offset = freq, duplex, offset
            memory.tmode, memory.rtone = tmode, tone
            memory.mode = 'FM'
            memory.power = self.radio.POWER_LEVELS_VHF[2]
            self.radio.set_memory(memory)
        for label, freq, duplex, offset, tmode, tone in plans:
            memory = self.radio.get_memory(label)
            self.assertEqual((memory.freq, memory.duplex, memory.offset,
                              memory.tmode, memory.rtone, str(memory.power)),
                             (freq, duplex, offset, tmode, tone, 'Mid2'))
        after = self.radio.get_mmap().get_packed()
        self.assertEqual(after[0x408:0x708], self.data[0x408:0x708])
        self.assertEqual(after[0x708:0x39C8], self.data[0x708:0x39C8])
        for base in (0x288, 0x348):
            self.assertEqual(after[base + 0x30:base + 0x40],
                             self.data[base + 0x30:base + 0x40])

    def test_shift_uses_bcd_field_and_preserves_vfo_control_bytes(self):
        memory = self.radio.get_memory('H1 L430')
        # Factory name/control bytes encode 5 MHz for ordinary channels,
        # while this VFO's BCD shift field is zero.
        self.assertEqual(memory.offset, 0)
        for offset, encoded in ((1600000, b'\x00\x01\x60'),
                                (99950000, b'\x00\x99\x95')):
            memory.offset = offset
            self.radio.set_memory(memory)
            after = self.radio.get_mmap().get_packed()
            self.assertEqual(after[0x2DD:0x2E0], encoded)
            self.assertEqual(after[0x2E2:0x2E8], self.data[0x2E2:0x2E8])
            self.assertEqual(self.radio.get_memory('H1 L430').offset, offset)

    def test_tone_power_and_mode_encoding_preserves_unused_bits(self):
        memory = self.radio.get_memory('H1 L144')
        memory.mode = 'NFM'
        memory.duplex = '-'
        memory.tmode = 'Tone'
        memory.rtone = 88.5
        memory.power = self.radio.POWER_LEVELS_VHF[2]
        self.radio.set_memory(memory)
        after = self.radio.get_mmap().get_packed()
        self.assertEqual(after[0x2A8], 2)
        self.assertEqual(after[0x2AC], 0x49)
        self.assertEqual(after[0x2B0], 8)
        self.assertEqual(after[0x2B2:0x2B8], self.data[0x2B2:0x2B8])

    def test_vfo_mode_and_band_selection_preserves_other_state(self):
        settings = self.radio.get_settings()
        settings['hyper1']['hyper1_left_band'].value = '430 MHz'
        settings['hyper1']['hyper1_right_band'].value = '144 MHz'
        self.radio.set_settings(settings)
        after = self.radio.get_mmap().get_packed()
        self.assertEqual(after[0x320:0x322], b'\x05\x02')
        self.assertEqual({i for i in range(len(after))
                          if after[i] != self.data[i]},
                         {0x320, 0x321})
        self.assertEqual(sum(after[:-1]) % 256, after[-1])

    def test_memory_mode_requires_an_existing_channel(self):
        # Remove ordinary channels to make the stored MR pointer unavailable.
        for number in range(1, 800):
            memory = self.radio.get_memory(number)
            if not memory.empty:
                memory.empty = True
                self.radio.set_memory(memory)
        before = self.radio.get_mmap().get_packed()
        settings = self.radio.get_settings()
        settings['hyper1']['hyper1_mode'].value = 'Memory'
        with self.assertRaises(errors.RadioError):
            self.radio.set_settings(settings)
        self.assertEqual(self.radio.get_mmap().get_packed(), before)

    def test_mr_vfo_switch_preserves_channel_and_other_mode_bits(self):
        memory = chirp_common.Memory(number=1)
        memory.freq = 145525000
        self.radio.set_memory(memory)
        self.radio.update_checksums()
        before = self.radio.get_mmap().get_packed()
        settings = self.radio.get_settings()
        settings['hyper1']['hyper1_mode'].value = 'Memory'
        self.radio.set_settings(settings)
        after = self.radio.get_mmap().get_packed()
        self.assertEqual((after[0x318], after[0x325]), (2, 8))
        settings = self.radio.get_settings()
        settings['hyper1']['hyper1_scan'].value = 'MSM'
        settings['hyper1']['hyper1_mode'].value = 'VFO'
        self.radio.set_settings(settings)
        after = self.radio.get_mmap().get_packed()
        self.assertEqual((after[0x318], after[0x325]), (0, 2))
        self.assertEqual(after[0x31C:0x31E], before[0x31C:0x31E])
        self.assertEqual(str(self.radio.get_settings()['hyper1'][
            'hyper1_scan'].value), 'MSM')

    def test_invalid_vfo_values_rejected_before_any_write(self):
        for field, value in (
                ('freq', 430025000), ('freq', 145856250),
                ('empty', True), ('name', 'TEST'), ('skip', 'S'),
                ('duplex', 'split'), ('offset', 625000),
                ('power', chirp_common.PowerLevel('Bad', watts=17)),
                ('rtone', 99.0), ('mode', 'USB')):
            with self.subTest(field=field):
                memory = self.radio.get_memory('H1 L144')
                memory.immutable = []
                memory.freq = 145525000
                setattr(memory, field, value)
                with self.assertRaises(errors.RadioError):
                    self.radio.set_memory(memory)
                self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_uhf_high_accepts_shared_ui_power_level(self):
        for label in ('H1 L430', 'H1 R430', 'HOME 430'):
            with self.subTest(label=label):
                memory = self.radio.get_memory(label)
                memory.power = self.radio.get_features().valid_power_levels[2]
                self.radio.set_memory(memory)
                memory = self.radio.get_memory(label)
                # The shared editor offers VHF Hi (50 W). UHF uses the same
                # encoding for Hi, whose actual rating is 35 W.
                memory.power = self.radio.get_features().valid_power_levels[0]
                self.radio.set_memory(memory)
                self.assertEqual(self.radio.get_memory(label).power,
                                 self.radio.POWER_LEVELS_UHF[0])
