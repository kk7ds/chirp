import os
import struct

from tests.unit import base
from chirp.drivers import baofeng_common
from chirp.drivers import bf_t1
from chirp.drivers import uv5r


# These are values that will decode as different values in various modes.
# Without anything preventing us from hitting these collisions based on the
# firmware version or something, we have no way to avoid these.
OVERLAPS = [
    65.1, 90.6,   # BF-T1
    65.3, 76.8,   # UV-5R
    65.4, 102.4,  # UV-5R
    77.2, 102.7,  # UV-5R
    90.9, 76.9,   # UV-5R
    91.0, 102.5,  # UV-5R
    ]


class FMRadioTest(base.BaseTest):
    IMAGE = None
    RADIO_CLASS = None
    MEMOBJ = 'element'
    SETTINGS_INDEX = (0, 'element')
    METHODS = []

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

    def check_fmvfo(self, expected, method):
        """Check FM VFO from settings

        expected should be something like 106.1
        """
        settings = self.radio.get_settings()
        index, name = self.SETTINGS_INDEX
        vfo = float(settings[index][name].value)

        if expected in OVERLAPS and vfo != expected:
            # These are collisions that we can't really do anything about,
            # unfortunately.
            pass
        else:
            self.assertEqual(expected, vfo,
                             'Memory is 0x%04x (method %s)' % (
                                 self.get_fmvfo_raw(), method))

    def set_fmvfo(self, value):
        """Set FM VFO via settings

        value is a float like 106.1
        """
        index, name = self.SETTINGS_INDEX
        settings = self.radio.get_settings()
        vfo = settings[index][name]
        vfo.value = value
        self.radio.set_settings(settings)

    def test_get(self):
        for method in self.METHODS:
            raw = baofeng_common.encode_fmradio(100.0,
                                                method.swap, method.shift)

            # Set the raw value
            self.set_fmvfo_raw(raw)

            # Make sure we get the value we expect
            self.check_fmvfo(100.0, method)

    def test_set(self):
        for method in self.METHODS:
            raw = baofeng_common.encode_fmradio(100.0,
                                                method.swap, method.shift)

            # Set the initial in-memory value
            self.set_fmvfo_raw(raw)

            # Make sure we decode it to the expected value
            self.check_fmvfo(100.0, method)

            # Set another value via settings
            self.set_fmvfo(106.1)

            # Make sure it looks like we expect in memory
            raw = baofeng_common.encode_fmradio(106.1,
                                                method.swap, method.shift)
            self.assertEqual(raw, self.get_fmvfo_raw(),
                             'In-memory value does not match expected after '
                             'setting via settings (method %s)' % str(method))

            # Make sure we get back the same value via settings
            self.check_fmvfo(106.1, method)

    def test_get_out_of_range(self):
        # Set the value to something out of range
        self.set_fmvfo_raw(0xFFFF)

        # Make sure we get no setting exposed
        self.assertRaises(KeyError, self.check_fmvfo, 100, self.METHODS[0])

    def _test_edges(self, swap, shift):
        """Test the edges around the supported range.

        Make sure that we don't confuse old and new values in our valid range.
        """
        errors = []
        for dial in range(650, 1081):
            dial /= 10
            self.set_fmvfo_raw(
                baofeng_common.encode_fmradio(dial, swap, shift))
            try:
                self.check_fmvfo(dial, 'swap=%s shift=%s' % (swap, shift))
            except (AssertionError, KeyError) as e:
                errors.append(str(e))

        self.assertEqual([], errors)

    def test_edges(self):
        for method in self.METHODS:
            self._test_edges(method.swap, method.shift)


class TestBFT1(FMRadioTest):
    IMAGE = 'Baofeng_BF-T1.img'
    RADIO_CLASS = bf_t1.BFT1
    SETTINGS_INDEX = (1, 'fm_vfo')
    MEMOBJ = 'settings.fm_vfo'
    METHODS = [baofeng_common.METHOD2,
               baofeng_common.METHOD4]


class TestUV5R(FMRadioTest):
    IMAGE = 'Baofeng_UV-5R.img'
    RADIO_CLASS = uv5r.BaofengUV5R
    SETTINGS_INDEX = (4, 'fm_presets')
    MEMOBJ = 'fm_presets'
    METHODS = [baofeng_common.METHOD1,
               baofeng_common.METHOD2,
               baofeng_common.METHOD3]
