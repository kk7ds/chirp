import os
import unittest

from chirp.drivers import ft450d
from tests.unit import base  # noqa


class TestFT450Docs(unittest.TestCase):
    def test_ft450_models_all_settings_have_docs(self):
        images = os.path.join(os.path.dirname(__file__), "..", "images")
        models = (
            (ft450d.FT450DRadio, "Yaesu_FT-450D.img"),
            (ft450d.FT450Radio, "Yaesu_FT-450.img"),
        )

        for radio_cls, image in models:
            radio = radio_cls(os.path.join(images, image))
            radio.get_features()
            settings = list(radio.get_settings().walk())
            settings.extend(radio.get_memory(1).extra.walk())

            missing = [setting.get_name() for setting in settings
                       if not setting.__doc__]
            att = next(setting for setting in settings
                       if setting.get_name() == "att")

            self.assertFalse(missing, radio_cls.MODEL)
            self.assertIn("20 dB", att.__doc__)
