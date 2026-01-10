import os
import unittest

from chirp import memmap
from chirp.drivers import retevis_ra25


class TestRA25SqlMode(unittest.TestCase):
    """Test sql_mode (Signal/Squelch Mode) feature for RA25/779UV"""

    def setUp(self):
        test_image = os.path.join(os.path.dirname(__file__),
                                  '..', 'images', 'Retevis_RA25.img')
        self.radio = retevis_ra25.RA25UVRadio(None)
        with open(test_image, 'rb') as f:
            self.radio._mmap = memmap.MemoryMapBytes(f.read())
        self.radio.process_mmap()

    def test_sql_mode_not_in_memory_extra(self):
        """sql_mode setting should NOT be present in mem.extra"""
        mem = self.radio.get_memory(1)
        setting_names = [s.get_name() for s in mem.extra]
        self.assertNotIn('sql_mode', setting_names)

    def test_sql_mode_raw_values(self):
        """sql_mode raw values should be 0 (SQ) or 1 (CT/DCS)"""
        _mem = self.radio._memobj.memory[0]

        # Test setting to 0 (SQ)
        _mem.sql_mode = 0
        self.assertEqual(int(_mem.sql_mode), 0)

        # Test setting to 1 (CT/DCS)
        _mem.sql_mode = 1
        self.assertEqual(int(_mem.sql_mode), 1)

    def test_sql_mode_adjacent_fields_intact(self):
        """Modifying sql_mode should not corrupt adjacent fields"""
        _mem = self.radio._memobj.memory[0]

        # Store original values
        orig_tone_id = int(_mem.tone_id)
        orig_bcl = int(_mem.busychannellockout)

        # Modify sql_mode
        _mem.sql_mode = 1
        _mem.sql_mode = 0

        # Verify adjacent fields unchanged
        self.assertEqual(int(_mem.tone_id), orig_tone_id)
        self.assertEqual(int(_mem.busychannellockout), orig_bcl)

    def test_sql_mode_in_vfo(self):
        """VFO struct should also have sql_mode field"""
        for i in [0, 1]:
            _vfo = self.radio._memobj.vfo[i]
            # Should be accessible without error
            _ = int(_vfo.sql_mode)

    def test_sql_mode_set_from_tmode_empty(self):
        """sql_mode should be 0 (SQ) when tmode is empty"""
        mem = self.radio.get_memory(1)
        mem.tmode = ""
        self.radio.set_memory(mem)

        _mem = self.radio._memobj.memory[0]
        self.assertEqual(int(_mem.sql_mode), 0)

    def test_sql_mode_set_from_tmode_tone(self):
        """sql_mode should be 0 (SQ) when tmode is Tone (TX only)"""
        mem = self.radio.get_memory(1)
        mem.tmode = "Tone"
        mem.rtone = 88.5
        self.radio.set_memory(mem)

        _mem = self.radio._memobj.memory[0]
        self.assertEqual(int(_mem.sql_mode), 0)

    def test_sql_mode_set_from_tmode_tsql(self):
        """sql_mode should be 1 (CT/DCS) when tmode is TSQL"""
        mem = self.radio.get_memory(1)
        mem.tmode = "TSQL"
        mem.ctone = 88.5
        self.radio.set_memory(mem)

        _mem = self.radio._memobj.memory[0]
        self.assertEqual(int(_mem.sql_mode), 1)

    def test_sql_mode_set_from_tmode_dtcs(self):
        """sql_mode should be 1 (CT/DCS) when tmode is DTCS"""
        mem = self.radio.get_memory(1)
        mem.tmode = "DTCS"
        mem.dtcs = 23
        self.radio.set_memory(mem)

        _mem = self.radio._memobj.memory[0]
        self.assertEqual(int(_mem.sql_mode), 1)

    def test_sql_mode_set_from_cross_with_rx_tone(self):
        """sql_mode should be 1 (CT/DCS) when Cross mode has RX tone"""
        mem = self.radio.get_memory(1)
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 88.5
        mem.ctone = 100.0
        self.radio.set_memory(mem)

        _mem = self.radio._memobj.memory[0]
        self.assertEqual(int(_mem.sql_mode), 1)

    def test_sql_mode_set_from_cross_with_rx_dtcs(self):
        """sql_mode should be 1 (CT/DCS) when Cross mode has RX DTCS"""
        mem = self.radio.get_memory(1)
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->DTCS"
        mem.rtone = 88.5
        mem.rx_dtcs = 23
        self.radio.set_memory(mem)

        _mem = self.radio._memobj.memory[0]
        self.assertEqual(int(_mem.sql_mode), 1)

    def test_sql_mode_set_from_cross_without_rx_tone(self):
        """sql_mode should be 0 (SQ) when Cross mode has no RX tone"""
        mem = self.radio.get_memory(1)
        mem.tmode = "Cross"
        mem.cross_mode = "DTCS->"
        mem.dtcs = 23
        self.radio.set_memory(mem)

        _mem = self.radio._memobj.memory[0]
        self.assertEqual(int(_mem.sql_mode), 0)
