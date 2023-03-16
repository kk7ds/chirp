import os
import struct

import pytest

from tests.unit import base
from chirp.drivers import bf_t1
from chirp.drivers import uv5r
from chirp import settings


class FMRadioTest(base.BaseTest):
    IMAGE = None
    RADIO_CLASS = None
    MEMOBJ = 'element'
    SETTINGS_INDEX = (0, 'element')

    def setUp(self):
        if self.IMAGE is None:
            self.skipTest('Base test')

        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', self.IMAGE)
        self.radio = self.RADIO_CLASS(img)

        return super().setUp()

    def set_fmvfo_raw(self, value):
        """Set FM VFO as integer directly in memory"""
        val_bytes = struct.pack('>H', value)
        obj = self.radio._memobj
        for element in self.MEMOBJ.split('.'):
            obj = getattr(obj, element)
        obj.set_raw(val_bytes)

    def get_fmvfo_raw(self):
        """Get FM VFO as integer directly from memory"""
        obj = self.radio._memobj
        for element in self.MEMOBJ.split('.'):
            obj = getattr(obj, element)
        return int(obj)

    def check_fmvfo(self, expected):
        """Check FM VFO from settings

        expected should be something like 106.1
        """
        settings = self.radio.get_settings()
        index, name = self.SETTINGS_INDEX
        vfo = settings[index][name]
        self.assertEqual(expected, float(vfo.value))

    def set_fmvfo(self, value):
        """Set FM VFO via settings

        value is a float like 106.1
        """
        index, name = self.SETTINGS_INDEX
        settings = self.radio.get_settings()
        vfo = settings[index][name]
        vfo.value = value
        self.radio.set_settings(settings)

    def test_get_original(self):
        # 100.0 in original form would be:
        # 100.0 - 65 = 35.0 * 10 = 350 = 0x015E

        # Set it directly in our memory in old format
        self.set_fmvfo_raw(0x015E)

        # Make sure we get the expected value from settings
        self.check_fmvfo(100.0)

    def test_set_original(self):
        # Set it via settings
        self.set_fmvfo(106.1)

        # Make sure it's the expected value in memory, old format, since our
        # test image was in old format
        self.assertEqual(0x019B, self.get_fmvfo_raw())

        # Make sure we still get it back from settings as expected
        self.check_fmvfo(106.1)

    def test_get_2022(self):
        # 100.0 in original form would be:
        # 100.0 - 65 = 35.0 * 10 = 350 = 0x015E
        # New form is byte-swapped: 0x5E01

        # Set it directly in our memory in new format
        self.set_fmvfo_raw(0x5E01)

        # Make sure we get the expected value from settings
        self.check_fmvfo(100.0)

    def test_set_2022(self):
        # First set it in new format directly to 100.0
        self.set_fmvfo_raw(0x5E01)

        # Make sure we see it via settings as expected
        self.check_fmvfo(100.0)

        # Now set it via settings to a new value
        self.set_fmvfo(106.1)

        # Make sure it is in new form in the memory
        self.assertEqual(0x9B01, self.get_fmvfo_raw())

        # Make sure it is returned properly in settings
        self.check_fmvfo(106.1)

    def _test_edges(self, new=True):
        """Test the edges around the supported range.

        Make sure that we don't confuse old and new values on either side of
        the supported range as the wrong format.
        """
        if new:
            default = 0x5E01
        else:
            default = 0x015E
        for dial in range(50, 500, 10):
            if 65 <= dial <= 108:
                self.set_fmvfo(dial)
                self.check_fmvfo(dial)
            else:
                # Set this to a good default value so that we can set via
                # settings below.
                self.set_fmvfo_raw(default)

                # We should not be able to set this out-of-range value
                self.assertRaises(settings.InvalidValueError,
                                  self.set_fmvfo, dial)

                # Can't physically set this in memory
                if dial <= 65:
                    continue

                # Set it anyway in memory directly
                self.set_fmvfo_raw(int((dial - 65) * 10))

                # Make sure we do not interpret it incorrectly
                self.assertRaises(KeyError,
                                  self.check_fmvfo, dial)

    def test_edges_original(self):
        self._test_edges(False)

    def test_edges_2022(self):
        self._test_edges(True)


class TestBFT1(FMRadioTest):
    IMAGE = 'Baofeng_BF-T1.img'
    RADIO_CLASS = bf_t1.BFT1
    SETTINGS_INDEX = (1, 'fm_vfo')
    MEMOBJ = 'settings.fm_vfo'


@pytest.mark.skip('This radio needs fixing')
class TestUV5R(FMRadioTest):
    IMAGE = 'Baofeng_UV-5R.img'
    RADIO_CLASS = uv5r.BaofengUV5R
    SETTINGS_INDEX = (3, 'fm_presets')
    MEMOBJ = 'fm_presets'
