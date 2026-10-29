import os

import pytest

from tests.unit import base  # noqa
from chirp.drivers import kguv9dplus
from chirp.settings import InvalidValueError

IMAGES = os.path.join(os.path.dirname(__file__), "..", "images")
MODELS = (
    (kguv9dplus.KGUV9DPlusRadio, "Wouxun_KG-UV9D_Plus.img"),
    (kguv9dplus.KGUV9PXRadio, "Wouxun_KG-UV9PX.img"),
    (kguv9dplus.KGUV9GXRadio, "Wouxun_KG-UV9GX.img"),
    (kguv9dplus.KGUV9KRadio, "Wouxun_KG-UV9K.img"),
    (kguv9dplus.KGUV9GProRadio, "Wouxun_KG-UV9G_Pro.img"),
)


def _load(radio_cls, image):
    radio = radio_cls(os.path.join(IMAGES, image))
    radio.get_features()
    settings = {setting.get_name(): setting
                for setting in radio.get_settings().walk()}
    return radio, settings


@pytest.mark.parametrize("radio_cls, image", MODELS)
def test_kguv9_names_follow_manual(radio_cls, image):
    radio, settings = _load(radio_cls, image)

    # Menu 36 is Single Tone (S-TONE), the repeater tone burst
    assert settings["s_tone"].get_shortname() == "Single Tone (Menu 36)"
    # Menu 4 is Bandwidth (W/N)
    assert (settings["vfo_a.band_150.fm_dev"].get_shortname() ==
            "Bandwidth (Menu 4)")


@pytest.mark.parametrize("radio_cls, image", MODELS)
def test_kguv9_options_follow_manual(radio_cls, image):
    radio, settings = _load(radio_cls, image)

    assert (settings["roger"].value.get_options() ==
            ["Off", "BOT", "EOT", "Both"])
    assert (settings["ptt_id"].value.get_options() ==
            ["Off", "BOT", "EOT", "Both"])
    assert (settings["vfo_b.band_450.shift"].value.get_options() ==
            ["Off", "+", "-"])
    assert settings["vox_dly"].value.get_options()[1:] == [
        "1s", "2s", "3s", "4s", "5s"]
    # Relabeling keeps the stored values: every test image has no shift
    # and Off for the roger beep and PTT ID
    assert str(settings["vfo_b.band_450.shift"].value) == "Off"
    assert str(settings["roger"].value) == "Off"
    assert str(settings["ptt_id"].value) == "Off"


@pytest.mark.parametrize("radio_cls, image", MODELS)
def test_kguv9_offset_accepts_manual_range(radio_cls, image):
    radio, settings = _load(radio_cls, image)
    offset = settings["vfo_a.band_450.offset"]

    offset.value = "10.000000"
    offset.run_apply_callback()
    assert int(radio._memobj.vfo_a.band_450.offset) == 1000000

    offset.value = "999.995000"
    offset.run_apply_callback()
    assert int(radio._memobj.vfo_a.band_450.offset) == 99999500

    offset.value = "1000.000000"
    with pytest.raises(InvalidValueError):
        offset.run_apply_callback()


@pytest.mark.parametrize("radio_cls, image", MODELS)
def test_kguv9_tones_include_d645(radio_cls, image):
    radio, settings = _load(radio_cls, image)
    encqt = settings["vfo_a.band_150.encqt"]

    assert "D645N" in encqt.value.get_options()
    assert "D645I" in encqt.value.get_options()
    encqt.value = "D645N"
    encqt.run_apply_callback()
    stored = int(radio._memobj.vfo_a.band_150.encqt)
    assert stored == 0x8000 | 0o645
    assert kguv9dplus.short2tone(stored) == "D645N"
