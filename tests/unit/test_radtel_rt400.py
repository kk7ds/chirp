# Copyright 2026 SV1TSD
# Licensed under the GNU General Public License, version 3 or later.
"""RT-400 typed memory and cross-radio import regression coverage."""
from pathlib import Path
import unittest

from chirp import bitwise, chirp_common, errors, import_logic
from chirp.drivers import radtel_rt400 as driver


IMAGE = Path(__file__).resolve().parents[1] / 'images' / 'Radtel_RT-400.img'


def setting(tree, name):
    return next(item for item in tree.walk() if item.get_name() == name)


class RT400Test(unittest.TestCase):
    def setUp(self):
        self.radio = driver.RadtelRT400Radio(str(IMAGE))

    def test_typed_map_matches_recorded_addresses(self):
        data = self.radio._memobj
        self.assertIsInstance(data.memory[0].rx_freq[0],
                              bitwise.lbcdDataElement)
        self.assertIsInstance(data.memory[0].rx_tone,
                              bitwise.ul16DataElement)
        self.assertIsInstance(data.memory[0].fhss_code,
                              bitwise.ul24DataElement)
        for field, offset, size in (
                (data.memory[0], 0, 32),
                (data.memory[255], 255 * 32, 32),
                (data.vfo[0], 0x8000, 32),
                (data.vfo[1], 0x8020, 32),
                (data.settings, 0x9000, 64),
                (data.dtmf, 0xA000, 320),
                (data.contacts, 0xB000, 768),
                (data.contacts.ids[59].code, 0xB0B1, 3),
                (data.contacts.names[29].name, 0xB290, 16)):
            with self.subTest(offset=offset):
                self.assertEqual(field.get_offset(), offset)
                self.assertEqual(field.size() // 8, size)

    def test_full_image_no_edit_roundtrip_preserves_all_bytes(self):
        before = self.radio.get_mmap().get_packed()
        self.radio.set_settings(self.radio.get_settings())
        for number in range(1, 257):
            self.radio.set_memory(self.radio.get_memory(number))
        self.assertEqual(self.radio.get_mmap().get_packed(), before)

    def test_channel_uses_little_endian_bcd(self):
        memory = self.radio.get_memory(1)
        memory.freq = 146520000
        memory.duplex = 'off'
        self.radio.set_memory(memory)
        stored = self.radio._memobj.memory[0]
        self.assertEqual(stored.rx_freq.get_raw(), b'\x00\x20\x65\x14')
        self.assertEqual(int(stored.rx_freq), 14652000)
        self.assertEqual(self.radio.get_memory(1).freq, 146520000)
        self.assertEqual(stored.tx_freq.get_raw(), b'\xff' * 4)

    def test_standard_dcs_list_plus_645(self):
        self.assertEqual(set(driver.DCS_CODES) - set(chirp_common.DTCS_CODES),
                         {645})
        self.assertEqual(len(driver.DCS_CODES), 105)
        memory = self.radio.get_memory(1)
        memory.tmode = 'DTCS'
        memory.dtcs = 645
        memory.rx_dtcs = 645
        memory.dtcs_polarity = 'RR'
        self.radio.set_memory(memory)
        expected = driver.DCS_CODES.index(645) + 1 + 105
        self.assertEqual(int(self.radio._memobj.memory[0].tx_tone), expected)
        self.assertEqual(self.radio.get_memory(1).dtcs, 645)
        self.assertEqual(self.radio.get_memory(1).dtcs_polarity, 'RR')

    def test_power_import_matches_wattages_and_stores_device_index(self):
        for watts, label, code in ((0.5, 'Low', 1), (3, 'Medium', 2),
                                   (5, 'High', 0)):
            with self.subTest(watts=watts):
                memory = self.radio.get_memory(1)
                memory.power = chirp_common.PowerLevel('Source', watts=watts)
                import_logic._import_power(self.radio, None, memory)
                self.assertEqual(str(memory.power), label)
                self.assertIs(type(memory.power), chirp_common.PowerLevel)
                self.radio.set_memory(memory)
                self.assertEqual(int(self.radio._memobj.memory[0].power), code)

    def test_import_power_from_existing_uv5r_and_bft8_drivers(self):
        from chirp.drivers import bf_t8, uv5r

        sources = ((uv5r.UV5R_POWER_LEVELS, ['High', 'Low']),
                   (bf_t8.BFT8Radio.POWER_LEVELS, ['Medium', 'Low']))
        for levels, expected in sources:
            for power, label in zip(levels, expected):
                with self.subTest(source=str(power), target=label):
                    memory = self.radio.get_memory(1)
                    memory.power = power
                    import_logic._import_power(self.radio, None, memory)
                    self.assertEqual(str(memory.power), label)

    def test_power_edit_preserves_scrambler_and_other_record_bytes(self):
        stored = self.radio._memobj.memory[0]
        stored.scrambler = 15
        stored.reserved_flag7 = 1
        stored.reserved_flag1 = 1
        before = self.radio.get_mmap().get_packed()
        memory = self.radio.get_memory(1)
        memory.power = driver.POWER_LEVELS[1]
        self.radio.set_memory(memory)
        expected = bytearray(before)
        expected[14] = (expected[14] & 0xF0) | 1
        self.assertEqual(self.radio.get_mmap().get_packed(), bytes(expected))

    def test_fhss_24_bit_code_keeps_high_bit(self):
        memory = self.radio.get_memory(1)
        setting(memory.extra, 'fhss_code').value.set_value('ABCDEF')
        self.radio.set_memory(memory)
        stored = self.radio._memobj.memory[0]
        self.assertEqual(int(stored.fhss_code), 0xABCDEF)
        self.assertEqual(stored.fhss_code.get_raw(), b'\xef\xcd\xab')
        self.assertEqual(int(stored.fhss_marker), 0xA0)
        self.assertEqual(str(setting(self.radio.get_memory(1).extra,
                                     'fhss_code').value), 'ABCDEF')

    def test_bad_channel_edit_restores_typed_record(self):
        before = self.radio.get_mmap().get_packed()
        memory = self.radio.get_memory(1)
        memory.freq = 146520000
        memory.name = 'NAME_TOO_LONG'
        with self.assertRaises(errors.InvalidValueError):
            self.radio.set_memory(memory)
        self.assertEqual(self.radio.get_mmap().get_packed(), before)
        stored = self.radio._memobj.memory[0].rx_freq
        self.assertEqual(self.radio.get_memory(1).freq,
                         driver._frequency(stored))

    def test_settings_rollback_keeps_ui_callbacks_attached(self):
        before = self.radio.get_mmap().get_packed()
        original_map = self.radio.get_mmap()
        tree = self.radio.get_settings()
        setting(tree, 'sql').value.set_value('9')
        setting(tree, 'vfo_a_frequency').value.set_value('...')
        with self.assertRaises(errors.InvalidValueError):
            self.radio.set_settings(tree)
        self.assertIs(self.radio.get_mmap(), original_map)
        self.assertEqual(self.radio.get_mmap().get_packed(), before)
        setting(tree, 'vfo_a_frequency').value.set_value('145.50000')
        self.radio.set_settings(tree)
        self.assertEqual(int(self.radio._memobj.settings.sql), 9)
        digits = self.radio._memobj.vfo[0].frequency
        self.assertEqual(driver._digits(digits, 10), 145500000)
        before = self.radio.get_mmap().get_packed()
        tree = self.radio.get_settings()
        setting(tree, 'sql').value.set_value('8')
        self.radio.set_settings(tree)
        expected = bytearray(before)
        expected[0x9000] = (expected[0x9000] & 0xF0) | 8
        self.assertEqual(self.radio.get_mmap().get_packed(), bytes(expected))
        self.assertEqual(int(self.radio._memobj.settings.sql), 8)

    def test_tot_and_spectrum_keep_explicit_device_codes(self):
        tree = self.radio.get_settings()
        self.assertEqual(setting(tree, 'tot').value.get_options(),
                         ['Off', '30 s', '60 s', '120 s', '240 s', '480 s'])
        setting(tree, 'tot').value.set_value('480 s')
        setting(tree, 'side_short').value.set_value('Spectrum')
        self.radio.set_settings(tree)
        self.assertEqual(int(self.radio._memobj.settings.tot), 5)
        self.assertEqual(int(self.radio._memobj.settings.side_short), 0x24)
        self.assertEqual(self.radio._memobj.settings.side_short.get_offset(),
                         0x902B)
        self.assertNotIn('PTT B',
                         setting(tree, 'side_long').value.get_options())
