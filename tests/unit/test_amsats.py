import unittest
from unittest import mock
from chirp.sources import amsats
from chirp import chirp_common

class TestAmsatsSatNOGS(unittest.TestCase):
    def setUp(self):
        self.satnogs = amsats.SatNOGS()

    def test_item_to_memory_mode_mapping(self):
        test_cases = [
            ('FMN', 'NFM'),
            ('DSB', 'AM'),
            ('AM', 'AM'),
            ('CW', 'CW'),
            ('USB', 'USB'),
            ('LSB', 'LSB'),
            ('GMSK', 'DIG'),
            ('GFSK', 'DIG'),
            ('MSK', 'DIG'),
            ('BPSK', 'DIG'),
            ('DVB-S2', 'DIG'),
            ('AHRPT', 'DIG'),
            ('LoRa', 'DIG'),
            ('SSTV', 'DIG'),
        ]
        
        for orig_mode, expected_mode in test_cases:
            item = {
                'downlink_low': 435000000,
                'mode': orig_mode,
                'type': 'Transmitter',
                '_satellite': {'name': 'TestSat', 'norad_cat_id': '12345'}
            }
            mem = self.satnogs.item_to_memory(item)
            self.assertEqual(mem.mode, expected_mode, f"Failed mapping {orig_mode}")
            
            # Check comment for non-native modes
            if expected_mode in ['DIG', 'AM'] and orig_mode != expected_mode:
                self.assertIn(f"Mode:{orig_mode}", mem.comment)
            
            # Check for fixed URL
            self.assertIn("https://db.satnogs.org/satellite/12345", mem.comment)
            # Check for removed NORAD: prefix
            self.assertFalse(mem.comment.startswith("NORAD:"))

    def test_item_to_memory_native_mode_redundancy(self):
        # Native modes shouldn't have "Mode:XXX" in comment
        item = {
            'downlink_low': 145000000,
            'mode': 'FM',
            'type': 'Transmitter',
            '_satellite': {'name': 'TestSat', 'norad_cat_id': '54321'}
        }
        mem = self.satnogs.item_to_memory(item)
        self.assertEqual(mem.mode, 'FM')
        self.assertNotIn("Mode:FM", mem.comment)

    @mock.patch('chirp.sources.amsats.SatNOGS._fetch_all')
    def test_do_fetch_filtering(self, mock_fetch):
        # Setup mocks
        mock_fetch.side_effect = [
            [{'sat_id': 'SAT1', 'name': 'Sat 1', 'norad_cat_id': '1'}], # Satellites
            [
                {'sat_id': 'SAT1', 'mode': 'FM', 'downlink_low': 100},
                {'sat_id': 'SAT1', 'mode': 'GMSK', 'downlink_low': 200},
                {'sat_id': 'SAT1', 'mode': None, 'downlink_low': 300},
            ], # Transmitters
            [{'sat_id': 'SAT1', 'name': 'Sat 1', 'norad_cat_id': '1'}], # Satellites second call
            [
                {'sat_id': 'SAT1', 'mode': 'FM', 'downlink_low': 100},
                {'sat_id': 'SAT1', 'mode': 'GMSK', 'downlink_low': 200},
                {'sat_id': 'SAT1', 'mode': None, 'downlink_low': 300},
            ] # Transmitters second call
        ]
    
        # Test FM filter
        status = mock.MagicMock()
        self.satnogs.do_fetch(status, {'modes': ['FM']})
        self.assertEqual(len(self.satnogs._memories), 1)
        self.assertEqual(self.satnogs._memories[0].mode, 'FM')
    
        # Reset and test GMSK filter
        self.satnogs._memories = []
        self.satnogs.do_fetch(status, {'modes': ['GMSK']})
        self.assertEqual(len(self.satnogs._memories), 1)
        self.assertEqual(self.satnogs._memories[0].mode, 'DIG')

class TestAmsatsRadioAmateur(unittest.TestCase):
    def test_item_to_memory_restyling(self):
        ra_sat = amsats.RadioAmateurSatellites()
        item = {
            'name': 'Sat1',
            'norad_id': '123',
            'satnogs_id': '123',
            'downlink': '145.800',
            'mode': 'FM',
        }
        mem = ra_sat.item_to_memory(item)
        self.assertEqual(mem.mode, 'FM')
        self.assertIn("https://db.satnogs.org/satellite/123", mem.comment)
        self.assertFalse(mem.comment.startswith("NORAD:"))
        self.assertIn("Mode:FM", mem.comment) # RadioAmateurSatellites still has Mode: in comment as per my implementation

if __name__ == '__main__':
    unittest.main()
