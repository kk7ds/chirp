import unittest
from unittest import mock

from chirp import chirp_common
from chirp.sources import base
from chirp.sources import dmrmarc

# Hopefully this will provide a sentinel and forcing function for
# network sources when APIs stop working. Unfortunately, live queries
# are more likely to add spurious failures into the tests, but time
# will tell if it's worth it.


class TestDMRMARC(unittest.TestCase):
    def test_marc_works(self):
        r = dmrmarc.DMRMARCRadio()
        r.do_fetch(mock.MagicMock(), {'city': 'portland',
                                      'state': 'oregon',
                                      'country': ''})
        f = r.get_features()

        # Assert that we found some repeaters. If they all go away in
        # Portland, this will break and we will need another target
        self.assertGreater(f.memory_bounds[1], 2)

        for i in range(*f.memory_bounds):
            m = r.get_memory(i)
            self.assertEqual('DMR', m.mode)
            # Assume all DMR repeaters are above 100MHz
            self.assertGreater(m.freq, 100000000)


class TestNetworkResultRadio(unittest.TestCase):
    def _radio_with(self, n):
        r = base.NetworkResultRadio()
        r._memories = []
        for i in range(n):
            m = chirp_common.Memory(number=i)
            m.freq = 146520000 + i * 10000
            r._memories.append(m)
        return r

    def test_set_memory_edits_in_place(self):
        r = self._radio_with(3)
        mem = r.get_memory(1).dupe()
        mem.name = 'Changed'
        r.set_memory(mem)

        self.assertEqual('Changed', r.get_memory(1).name)
        # Others untouched
        self.assertEqual('', r.get_memory(0).name)
        self.assertEqual('', r.get_memory(2).name)

    def test_erase_memory(self):
        r = self._radio_with(3)
        r.erase_memory(1)

        self.assertTrue(r.get_memory(1).empty)
        self.assertFalse(r.get_memory(0).empty)

    def test_validate_memory_allows_anything(self):
        r = self._radio_with(1)
        self.assertEqual([], r.validate_memory(r.get_memory(0)))


class TestRadioReferenceRadio(unittest.TestCase):
    def _make_radio(self):
        with mock.patch('chirp.sources.radioreference.Client'):
            from chirp.sources import radioreference
            return radioreference.RadioReferenceRadio()

    def test_set_memory_overrides_reconstruction(self):
        r = self._make_radio()
        # Simulate having fetched some raw frequency records, which
        # get_memory() would normally reconstruct a Memory from on every
        # call.
        r._freqs = [mock.MagicMock(), mock.MagicMock()]

        mem = chirp_common.Memory(number=0, name='Edited')
        mem.freq = 146520000
        r.set_memory(mem)

        got = r.get_memory(0)
        self.assertEqual('Edited', got.name)
        self.assertEqual(146520000, got.freq)

    def test_erase_memory_overrides_reconstruction(self):
        r = self._make_radio()
        r._freqs = [mock.MagicMock()]
        r.erase_memory(0)
        self.assertTrue(r.get_memory(0).empty)
