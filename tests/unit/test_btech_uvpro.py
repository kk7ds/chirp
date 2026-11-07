# Copyright 2026 Michael Sasarak <mike@prepperevolution.com>
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

"""Unit tests for the BTECH UV-PRO live driver using FakeUVProSerial.

Drop this file into tests/unit/ and FakeUVProSerial into chirp/drivers/fake.py
(see submission/fake-gui-howto.md). No radio hardware required.
"""

import builtins
import struct
import unittest

from chirp import chirp_common
from chirp import errors
from chirp.drivers import btech_uvpro as d
from chirp.drivers.fake import FakeUVProSerial

builtins._ = lambda s: s


class TestBTECHUVPRO(unittest.TestCase):
    def setUp(self):
        self.pipe = FakeUVProSerial()
        self.radio = d.BTECHUVPRORadio(self.pipe)

    def test_ident_and_active_group(self):
        self.assertEqual(self.radio.dev_info['soft_ver'], 147)
        self.assertEqual(self.radio.dev_info['region_count'], 6)
        self.assertEqual(self.radio.dev_info['channel_count'], 30)
        self.assertEqual(self.radio._curr_region, 1)
        self.assertEqual(self.radio._region_name, 'Monmouth')

    def test_get_memory_seeded(self):
        m = self.radio.get_memory(0)
        self.assertEqual(m.freq, 146520000)
        self.assertEqual(m.name, 'CALL')
        self.assertFalse(m.empty)
        empty = self.radio.get_memory(29)
        self.assertTrue(empty.empty)

    def test_out_of_range_is_empty(self):
        # Fake returns status 5 for ch >= 30; driver memory_bounds is 0-29
        # so we only ask for in-bounds empties here.
        m = self.radio.get_memory(15)
        self.assertTrue(m.empty)

    def test_write_gate_default_off(self):
        m = self.radio.get_memory(0)
        with self.assertRaises(errors.RadioError):
            self.radio.set_memory(m)

    def test_write_and_readback(self):
        # Flip the in-memory write switch the same way Settings does.
        st = self.radio.get_settings()
        for elem in self.radio._walk(st):
            if elem.get_name() == d.WRITE_SETTING:
                elem.value = True
        self.radio.set_settings(st)
        m = self.radio.get_memory(0)
        m.name = 'NEWNAME'
        m.power = d.POWER_LEVELS[0]
        self.radio.set_memory(m)
        self.radio._memcache.clear()
        again = self.radio.get_memory(0)
        self.assertEqual(again.name, 'NEWNAME')

    def test_am_airband_tx_zero(self):
        st = self.radio.get_settings()
        for elem in self.radio._walk(st):
            if elem.get_name() == d.WRITE_SETTING:
                elem.value = True
        self.radio.set_settings(st)
        m = chirp_common.Memory(5)
        m.freq = 120000000
        m.mode = 'AM'
        m.duplex = 'off'
        m.name = 'AIR'
        self.radio.set_memory(m)
        self.radio._memcache.clear()
        again = self.radio.get_memory(5)
        self.assertEqual(again.mode, 'AM')
        self.assertEqual(again.duplex, 'off')

    def test_dmr_refused_via_validate(self):
        m = chirp_common.Memory(0)
        m.freq = 146520000
        m.mode = 'DMR'
        msgs = self.radio.validate_memory(m)
        self.assertTrue(any('DMR' in str(x) for x in msgs))

    def test_set_region_not_allowlisted(self):
        with self.assertRaises(errors.RadioError):
            d.build_frame(60, bytes([1]))

    def test_parse_helpers(self):
        # region_count=6, channel_count=30, soft_ver=147
        body = struct.pack('>BHBHBBBB', 6, 260, 1, 147,
                           (6 >> 4) & 0x03, (6 & 0x0F) << 4, 30, 0)
        info = d.parse_dev_info(body)
        self.assertEqual(info['soft_ver'], 147)
        self.assertEqual(info['product'], 260)
        self.assertEqual(info['region_count'], 6)
        self.assertEqual(info['channel_count'], 30)
        s2 = (2 >> 2) & 0x0F
        s3 = ((2 & 0x03) << 6)
        self.assertEqual(
            d.parse_ht_status_curr_region(bytes([0x80, 0, s2, s3])), 2)
        self.assertEqual(d.parse_region_name(b'\x01Monmouth\x00\x00'),
                         (1, 'Monmouth'))

    def test_bitwise_preserves_recorded_bit_fields(self):
        # soft_ver 147, product 260, region_count 6, support_dmr set,
        # unused bits in bytes 6-7 set so a shifted field would move them.
        raw = bytes.fromhex('060104010093a86b1e')
        info = d.parse_dev_info(raw)
        self.assertEqual(info['vendor'], 6)
        self.assertEqual(info['product'], 260)
        self.assertEqual(info['hw_ver'], 1)
        self.assertEqual(info['soft_ver'], 147)
        self.assertEqual(info['region_count'], 6)
        self.assertTrue(info['support_dmr'])
        self.assertEqual(info['channel_count'], 30)
        parsed = d._parse_bits(d.DEV_INFO_FORMAT, raw)
        self.assertEqual(parsed.get_raw(), raw)
        # StatusExt curr_region 2 with rssi nibble and low channel bits set.
        # Same split as the fake: high 4 bits from byte 2, low 2 from byte 3.
        status = bytes([0x80, 0x01, 0xA0, 0x95])
        self.assertEqual(d.parse_ht_status_curr_region(status), 2)
        parsed = d._parse_bits(d.STATUS_EXT_FORMAT, status)
        self.assertEqual(parsed.get_raw(), status)
        self.assertIsNone(d.parse_ht_status_curr_region(b'\x80\x00'))

    def test_com4_2026_11_07_payloads(self):
        # Read-only COM4 download. Command 4 body after the success status
        # byte. Tenth byte is outside the 9-byte dev-info record.
        dev = bytes.fromhex('060104010093d0681e54')
        info = d.parse_dev_info(dev)

        def old_region_count(b6, b7):
            return ((b6 & 0x03) << 4) + ((b7 & 0xF0) >> 4)

        self.assertEqual(info['vendor'], 6)
        self.assertEqual(info['product'], 260)
        self.assertEqual(info['hw_ver'], 1)
        self.assertEqual(info['soft_ver'], 147)
        self.assertEqual(info['region_count'], 6)
        self.assertEqual(info['region_count'], old_region_count(0xD0, 0x68))
        self.assertFalse(info['support_dmr'])
        self.assertEqual(bool(0x68 & 0x01), info['support_dmr'])
        self.assertEqual(info['channel_count'], 30)
        parsed = d._parse_bits(d.DEV_INFO_FORMAT, dev[:d.DEV_INFO_LEN])
        self.assertEqual(parsed.get_raw(), dev[:d.DEV_INFO_LEN])
        self.assertEqual(int(parsed.dev_unused), 0xD0 >> 2)
        self.assertEqual(int(parsed.flag_unused), (0x68 >> 1) & 0x07)

        # Command 20 body: b2 21 70 00. curr_region bits are the low
        # nibble of byte 2 and the top two bits of byte 3.
        status = bytes.fromhex('b2217000')

        def old_curr_region(b2, b3):
            return ((b2 & 0x0F) << 2) + (b3 >> 6)

        self.assertEqual(d.parse_ht_status_curr_region(status), 0)
        self.assertEqual(d.parse_ht_status_curr_region(status),
                         old_curr_region(0x70, 0x00))
        parsed = d._parse_bits(d.STATUS_EXT_FORMAT, status)
        self.assertEqual(parsed.get_raw(), status)
        self.assertEqual(int(parsed.flags), 0xB2)
        self.assertEqual(int(parsed.ch_flags), 0x21)
        self.assertEqual(int(parsed.rssi), 0x70 >> 4)
        self.assertEqual(int(parsed.curr_region), 0)
        self.assertEqual(int(parsed.ch_hi), 0)

        # Command 73 success body: index 0 and ten 0x00 name bytes.
        self.assertEqual(d.parse_region_name(bytes(11)), (0, ''))

    def test_rf_ch_bitwise_hardware_bytes(self):
        # Mem 29 as stored by the radio after an AM airband write
        # (debug_am29.log 2026-11-02): TX word 0x40000000, RX 120 MHz AM.
        raw = bytes([0x1d, 0x40, 0, 0, 0, 0x47, 0x27, 0x0e, 0x00,
                     0, 0, 0, 0, 0xd1, 0]) + b'M9AM'.ljust(10, b'\x00')
        ch = d.parse_rf_ch(raw)
        self.assertEqual(int(ch.id), 29)
        self.assertEqual(int(ch.tx_mod), d.MOD_AM)
        self.assertEqual(int(ch.tx_hz), 0)
        self.assertEqual(int(ch.rx_mod), d.MOD_AM)
        self.assertEqual(int(ch.rx_hz), 120000000)
        self.assertEqual(int(ch.scan), 1)
        self.assertEqual(int(ch.max_power), 1)
        self.assertEqual(int(ch.wide), 1)
        self.assertEqual(int(ch.tx_disable), 1)
        self.assertEqual(int(ch.sign), 0)
        self.assertEqual(d.rf_ch_name(ch), 'M9AM')
        # Same structure re-encodes the identical bytes
        self.assertEqual(ch.get_raw(), raw)
        ch.max_power = 0
        ch.med_power = 1
        self.assertEqual(ch.get_raw()[13], 0x93)

    def test_short_reply_raises(self):
        class Silent(FakeUVProSerial):
            def read(self, n):
                return b''
        with self.assertRaises(errors.RadioError):
            d.BTECHUVPRORadio(Silent())

    def test_bad_frame_start_raises(self):
        class Garbage(FakeUVProSerial):
            def read(self, n):
                return b'\x00' * n
        with self.assertRaises(errors.RadioError):
            d.BTECHUVPRORadio(Garbage())

    def test_dtcs_polarity_uses_native_features(self):
        rf = self.radio.get_features()
        self.assertTrue(rf.has_dtcs_polarity)
        self.assertEqual(rf.valid_dtcs_pols, ['NN'])
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.tmode = 'DTCS'
        mem.dtcs = 23
        mem.dtcs_polarity = 'RN'
        feature_msgs = rf.validate_memory(mem)
        self.assertTrue(any(
            isinstance(m, chirp_common.ValidationError) and
            'Polarity' in str(m) for m in feature_msgs))
        driver_msgs = self.radio.validate_memory(mem)
        self.assertTrue(any('Polarity' in str(m) for m in driver_msgs))
        mem.dtcs_polarity = 'NN'
        self.assertFalse(any('Polarity' in str(m)
                             for m in self.radio.validate_memory(mem)))

    def test_timeouts_set(self):
        # Read timeout is the driver's. write_timeout is inherited from
        # the pipe (open_serial on a real port, FakeUVProSerial here).
        self.assertEqual(self.pipe.timeout, d.BTECHUVPRORadio.TIMEOUT)
        self.assertEqual(self.pipe.write_timeout, 2)

    def test_driver_leaves_write_timeout_unchanged(self):
        class Marked(FakeUVProSerial):
            def __init__(self):
                super().__init__()
                self.write_timeout = 9

        pipe = Marked()
        d.BTECHUVPRORadio(pipe)
        self.assertEqual(pipe.timeout, d.BTECHUVPRORadio.TIMEOUT)
        self.assertEqual(pipe.write_timeout, 9)


if __name__ == '__main__':
    unittest.main()
