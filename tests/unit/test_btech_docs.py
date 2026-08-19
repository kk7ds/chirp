import os

from chirp.drivers import btech


def test_kt8900_models_all_detailed_settings_have_docs():
    image = os.path.join(os.path.dirname(__file__),
                         "..", "images", "QYT_KT8900D.img")
    models = (
        (btech.KT9800, "pre-alert"),
        (btech.KT8900D, "powers the radio off"),
    )

    for radio_cls, apo_text in models:
        radio = radio_cls(image)
        radio.get_features()
        settings = list(radio.get_settings().walk())
        settings.extend(radio.get_memory(0).extra.walk())

        missing = [setting.get_name() for setting in settings
                   if not setting.__doc__]
        apo = next(setting for setting in settings
                   if setting.get_name() == "settings.apo")

        assert not missing, radio_cls.MODEL
        assert apo_text in apo.__doc__
