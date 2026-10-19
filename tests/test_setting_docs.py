import os

import yaml

from chirp import directory
from chirp import settings
from tests import base

with open(os.path.join(os.path.dirname(__file__),
                       'driver_setting_docs.yaml')) as f:
    DOCUMENTED = yaml.load(f, Loader=yaml.SafeLoader) or []


class TestCaseSettingDocs(base.DriverTest):
    def setUp(self):
        # Most radios are not listed, so skip them before loading the image
        if (self.SUB_DEVICE is None and
                directory.radio_class_id(self.RADIO_CLASS) not in DOCUMENTED):
            self.skipTest('Not listed in driver_setting_docs.yaml')
        super().setUp()

    def test_settings_have_docs(self):
        if directory.radio_class_id(self.radio.__class__) not in DOCUMENTED:
            self.skipTest('Not listed in driver_setting_docs.yaml')

        all_settings = []
        if self.rf.has_settings:
            all_settings.extend(self.radio.get_settings().walk())
        for i in range(*self.rf.memory_bounds):
            mem = self.radio.get_memory(i)
            if not mem.empty:
                extra = mem.extra
                if isinstance(extra, settings.RadioSettingGroup):
                    extra = extra.walk()
                all_settings.extend(extra)
                break

        missing = [setting.get_name() for setting in all_settings
                   if not setting.__doc__]
        self.assertEqual([], missing,
                         'Settings without a description')
