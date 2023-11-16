from chirp import chirp_common
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

    def test_memory_extra_frozen(self):
        # Find the first non-empty memory and try to set it back as a
        # FrozenMemory to make sure the driver does not try to modify
        # any of the settings.
        for i in range(*self.rf.memory_bounds):
            m = self.radio.get_memory(i)
            if not m.empty:
                self.radio.set_memory(chirp_common.FrozenMemory(m))
                break

    def test_memory_extra_flat(self):
        for i in range(*self.rf.memory_bounds):
            m = self.radio.get_memory(i)
            if not m.empty:
                self.assertIsInstance(
                    m.extra,
                    (list, settings.RadioSettingGroup),
                    'mem.extra must be a list or RadioSettingGroup')
                for e in m.extra:
                    self.assertIsInstance(
                        e, settings.RadioSetting,
                        'mem.extra items must be RadioSetting objects')
