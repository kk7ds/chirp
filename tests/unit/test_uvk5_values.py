import os

from chirp.drivers import uvk5
from tests.unit import base  # noqa

IMAGES = os.path.join(os.path.dirname(__file__), "..", "images")
MODELS = (
    (uvk5.UVK5Radio, "Quansheng_UV-K5.img"),
    (uvk5.RA79Radio, "Retevis_RA79.img"),
)


def _load(radio_cls, image):
    radio = radio_cls(os.path.join(IMAGES, image))
    radio.get_features()
    return radio


def _settings(radio):
    return {setting.get_name(): setting
            for setting in radio.get_settings().walk()}


def test_dtmf_auto_reset_time_is_stored_in_seconds():
    for radio_cls, image in MODELS:
        radio = _load(radio_cls, image)
        setting = _settings(radio)["dtmf_auto_reset_time"]
        setting.value = 30
        radio.set_settings([setting])

        stored = radio._memobj.dtmf_settings.auto_reset_time
        assert stored == 30, radio_cls.MODEL
        shown = _settings(radio)["dtmf_auto_reset_time"].value
        assert int(shown) == 30, radio_cls.MODEL


def test_setting_labels_match_manual():
    for radio_cls, image in MODELS:
        radio = _load(radio_cls, image)
        settings = _settings(radio)

        assert settings["keypad_tone"].get_shortname() == "Voice prompt"
        response = settings["dtmf_decode_response"].value.get_options()
        assert response[0] == "NULL"
        for name in ("dualwatch", "crossband"):
            options = settings[name].value.get_options()
            assert options == ["Off", "CHAN_A", "CHAN_B"], name
