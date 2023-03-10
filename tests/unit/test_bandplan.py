import unittest

from chirp import bandplan


class FakeConfig:
    def __init__(self, bandplan):
        self.bandplan = bandplan

    def is_defined(self, opt, sec):
        return True

    def get(self, opt, sec):
        return None

    def get_bool(self, opt, sec):
        return opt == self.bandplan


class BandPlanTest(unittest.TestCase):
    def test_get_repeater_bands(self):
        plans = bandplan.BandPlans(FakeConfig('north_america'))
        expected = ['10 Meter Band',
                    '6 Meter Band',
                    '2 Meter Band',
                    '1.25 Meter Band',
                    '70 Centimeter Band',
                    '33 Centimeter Band',
                    '23 Centimeter Band',
                    '13 Centimeter Band']

        self.assertEqual(expected,
                         [b.name for b in plans.get_repeater_bands()])
