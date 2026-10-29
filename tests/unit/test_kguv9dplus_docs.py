import os

from tests.unit import base  # noqa
from chirp.drivers import kguv9dplus


def test_kguv9_models_all_settings_have_docs():
    images = os.path.join(os.path.dirname(__file__), "..", "images")
    models = (
        (kguv9dplus.KGUV9DPlusRadio, "Wouxun_KG-UV9D_Plus.img"),
        (kguv9dplus.KGUV9PXRadio, "Wouxun_KG-UV9PX.img"),
        (kguv9dplus.KGUV9GXRadio, "Wouxun_KG-UV9GX.img"),
        (kguv9dplus.KGUV9KRadio, "Wouxun_KG-UV9K.img"),
        (kguv9dplus.KGUV9GProRadio, "Wouxun_KG-UV9G_Pro.img"),
    )

    for radio_cls, image in models:
        radio = radio_cls(os.path.join(images, image))
        radio.get_features()
        settings = list(radio.get_settings().walk())
        # The driver has no per-memory Extra tab yet, so this is empty
        settings.extend(radio.get_memory(1).extra)

        missing = [setting.get_name() for setting in settings
                   if not setting.__doc__]
        s_tone = next(setting for setting in settings
                      if setting.get_name() == "s_tone")

        assert not missing, radio_cls.MODEL
        # Menu 36 is Single Tone, the repeater tone burst
        assert "tone-burst" in s_tone.__doc__
