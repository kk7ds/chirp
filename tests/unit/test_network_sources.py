import unittest
from unittest import mock

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
