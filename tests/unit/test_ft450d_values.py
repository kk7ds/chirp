from chirp.drivers import ft450d  # noqa: F401
from tests.unit import base


class _FT450Values:
    def test_cw_500hz_filter_can_be_stored(self):
        mem = self.radio.get_memory(1)
        mem.mode = "CW"
        mem.extra["bpfilter"].value = "500 Hz"

        self.assertFalse(self.radio.validate_memory(mem))
        self.radio.set_memory(mem)

        self.assertEqual(1, self.radio._memobj.memory[0].cw_width)
        self.assertEqual("500 Hz",
                         str(self.radio.get_memory(1).extra[
                             "bpfilter"].value))

    def test_setting_ranges_match_manual(self):
        settings = {setting.get_name(): setting.value
                    for setting in self.radio.get_settings().walk()}
        self.assertEqual("10ms", settings["cat_tot"].get_options()[0])
        self.assertEqual(-3000, settings["d_disp"].get_min())
        self.assertEqual(3000, settings["d_disp"].get_max())
        self.assertEqual(1, settings["vox_gain"].get_min())
        self.assertEqual(100, settings["vox_gain"].get_max())

    def test_set_initializes_blank_but_valid_memory(self):
        number = 11
        index = number - 1
        channel = self.radio._memobj.memory[index]
        channel.set_raw("\xFF" * (channel.size() // 8))
        self.radio._memobj.visible[index // 8] &= ~(1 << (index % 8))
        self.radio._memobj.filled[index // 8] |= 1 << (index % 8)

        mem = self.radio.get_memory(number)
        self.assertTrue(mem.empty)
        mem.empty = False
        mem.freq = 2255000

        self.radio.set_memory(mem)

        updated = self.radio.get_memory(number)
        self.assertEqual(updated.freq, 2255000)
        self.assertEqual(str(updated.extra["bpfilter"].value), "2.5 kHz")


class TestFT450DValues(_FT450Values, base.RadioTest):
    VENDOR_MODEL = "Yaesu_FT-450D"


class TestFT450Values(_FT450Values, base.RadioTest):
    VENDOR_MODEL = "Yaesu_FT-450"
