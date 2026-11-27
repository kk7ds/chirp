from chirp.drivers import ft450d  # noqa: F401
from tests.unit import base


class _FT450Docs:
    def test_ft450_models_all_settings_have_docs(self):
        radio = self.radio
        radio.get_features()
        settings = list(radio.get_settings().walk())
        settings.extend(radio.get_memory(1).extra.walk())

        missing = [setting.get_name() for setting in settings
                   if not setting.__doc__]
        att = next(setting for setting in settings
                   if setting.get_name() == "att")

        self.assertFalse(missing, radio.MODEL)
        self.assertIn("20 dB", att.__doc__)


class TestFT450DDocs(_FT450Docs, base.RadioTest):
    VENDOR_MODEL = "Yaesu_FT-450D"


class TestFT450Docs(_FT450Docs, base.RadioTest):
    VENDOR_MODEL = "Yaesu_FT-450"
