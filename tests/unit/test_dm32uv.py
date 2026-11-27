from chirp.drivers import baofeng_dm32uv  # noqa: F401
from tests.unit import base


class TestDM32UV(base.RadioTest):
    VENDOR_MODEL = 'Baofeng_DM-32UV'

    def test_rename_zone_replaces_characters_outside_latin1(self):
        zone = self.radio.get_bank_model().get_mappings()[0]

        zone.set_name('Çeşme')

        self.assertEqual('Çe?me', zone.get_name())
