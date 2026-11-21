from pathlib import Path

from chirp.drivers import baofeng_dm32uv


def test_rename_zone_replaces_characters_outside_latin1():
    images = Path(__file__).resolve().parents[1] / 'images'
    radio = baofeng_dm32uv.DM32UV(str(images / 'Baofeng_DM-32UV.img'))
    zone = radio.get_bank_model().get_mappings()[0]

    zone.set_name('Çeşme')

    assert zone.get_name() == 'Çe?me'
