import os
import unittest

from chirp.drivers import ft450d
from tests.unit import base  # noqa

IMAGES = os.path.join(os.path.dirname(__file__), "..", "images")
MODELS = (
    (ft450d.FT450DRadio, "Yaesu_FT-450D.img"),
    (ft450d.FT450Radio, "Yaesu_FT-450.img"),
)


def _load(radio_cls, image):
    radio = radio_cls(os.path.join(IMAGES, image))
    radio.get_features()
    return radio


class TestFT450Values(unittest.TestCase):
    def test_cw_500hz_filter_can_be_stored(self):
        for radio_cls, image in MODELS:
            radio = _load(radio_cls, image)
            mem = radio.get_memory(1)
            mem.mode = "CW"
            mem.extra["bpfilter"].value = "500 Hz"

            self.assertFalse(radio.validate_memory(mem), radio_cls.MODEL)
            radio.set_memory(mem)

            self.assertEqual(1, radio._memobj.memory[0].cw_width,
                             radio_cls.MODEL)
            self.assertEqual("500 Hz",
                             str(radio.get_memory(1).extra["bpfilter"].value))

    def test_setting_ranges_match_manual(self):
        for radio_cls, image in MODELS:
            radio = _load(radio_cls, image)
            settings = {setting.get_name(): setting.value
                        for setting in radio.get_settings().walk()}
            self.assertEqual("10ms", settings["cat_tot"].get_options()[0])
            self.assertEqual(-3000, settings["d_disp"].get_min())
            self.assertEqual(3000, settings["d_disp"].get_max())
            self.assertEqual(1, settings["vox_gain"].get_min())
            self.assertEqual(100, settings["vox_gain"].get_max())

    def test_set_initializes_blank_but_valid_memory(self):
        for radio_cls, image in MODELS:
            radio = _load(radio_cls, image)
            number = 11
            index = number - 1
            channel = radio._memobj.memory[index]
            channel.set_raw("\xFF" * (channel.size() // 8))
            radio._memobj.visible[index // 8] &= ~(1 << (index % 8))
            radio._memobj.filled[index // 8] |= 1 << (index % 8)

            mem = radio.get_memory(number)
            self.assertTrue(mem.empty)
            mem.empty = False
            mem.freq = 2255000

            radio.set_memory(mem)

            updated = radio.get_memory(number)
            self.assertEqual(updated.freq, 2255000, radio_cls.MODEL)
            self.assertEqual(str(updated.extra["bpfilter"].value), "2.5 kHz")
