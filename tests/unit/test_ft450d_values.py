import os

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


def test_cw_500hz_filter_can_be_stored():
    for radio_cls, image in MODELS:
        radio = _load(radio_cls, image)
        mem = radio.get_memory(1)
        mem.mode = "CW"
        mem.extra["bpfilter"].value = "500 Hz"

        assert not radio.validate_memory(mem), radio_cls.MODEL
        radio.set_memory(mem)

        assert radio._memobj.memory[0].cw_width == 1, radio_cls.MODEL
        assert str(radio.get_memory(1).extra["bpfilter"].value) == "500 Hz"


def test_setting_ranges_match_manual():
    for radio_cls, image in MODELS:
        radio = _load(radio_cls, image)
        settings = {setting.get_name(): setting.value
                    for setting in radio.get_settings().walk()}

        assert settings["cat_tot"].get_options()[0] == "10ms"
        assert settings["d_disp"].get_min() == -3000
        assert settings["d_disp"].get_max() == 3000
        assert settings["vox_gain"].get_min() == 1
        assert settings["vox_gain"].get_max() == 100
