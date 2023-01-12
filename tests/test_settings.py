from chirp import settings
from tests import base


class TestCaseSettings(base.DriverTest):
    def test_has_settings(self):
        return
        settings = self.radio.get_settings()
        if settings:
            self.assertFalse(self.rf.has_settings,
                             'Radio returned settings but has_settings=False')
        else:
            self.assertTrue(self.rf.has_settings,
                            'Radio returned no settings but has_settings=True')

    @base.requires_feature('has_settings')
    def test_get_settings(self):
        lst = self.radio.get_settings()
        self.assertIsInstance(lst, list)

    @base.requires_feature('has_settings')
    def test_same_settings(self):
        o = self.radio.get_settings()
        self.radio.set_settings(o)
        n = self.radio.get_settings()
        list(map(self.compare_settings, o, n))

    def compare_settings(self, a, b):
        try:
            if isinstance(a, settings.RadioSettingValue):
                raise StopIteration
            list(map(self.compare_settings, a, b))
        except StopIteration:
            self.assertEqual(a.get_value(), b.get_value(),
                             'Setting value changed from %r to %r' % (
                                 a.get_value(), b.get_value()))
