import os

from tests.unit import base  # noqa
from chirp.drivers import radtel_rt880g


def test_rt880g_power_tuning_docs_follow_manual_range():
    image = os.path.join(os.path.dirname(__file__), "..", "images",
                         "Radtel_RT-880G.img")
    radio = radtel_rt880g.RT880G(image)
    radio.get_features()
    powers = [setting for setting in radio.get_settings().walk()
              if setting.get_name().startswith("tt_power_")
              and setting.get_name() != "tt_power_test"]

    assert len(powers) == 15
    for setting in powers:
        assert "from 0 to 254" in setting.__doc__, setting.get_name()
