import logging
import time

from chirp import chirp_common
from chirp import settings

LOG = logging.getLogger(__name__)


class FakeLiveRadio(chirp_common.LiveRadio):
    VENDOR = 'CHIRP'
    MODEL = 'Fake Live Radio'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.settings = {'knob': 5}
        self.memories = []
        for i in range (1, 11):
            m = chirp_common.Memory(i, empty=i > 5, name='channel %i' % i)
            m.freq = 146520000
            self.memories.append(m)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 10)
        rf.has_settings = True
        return rf

    def get_memory(self, number):
        return self.memories[number - 1]

    def set_memory(self, mem):
        LOG.info('Set memory %s' % mem)
        self.memories[mem.number - 1] = mem

    def get_settings(self):
        g = settings.RadioSettingGroup('top', 'Some Settings')
        g.append(
            settings.RadioSetting(
                'knob', 'A knob',
                settings.RadioSettingValueInteger(0, 10,
                                                  self.settings['knob'])))
        return settings.RadioSettings(g)

    def set_settings(self, rs):
        for e in rs:
            if isinstance(e, settings.RadioSetting):
                self.settings[e.name] = e.value
            else:
                self.set_settings(e)


class FakeLiveSlowRadio(FakeLiveRadio):
    VARIANT = 'Slow'

    def get_memory(self, number):
        time.sleep(0.5)
        return super().get_memory(number)

    def set_memory(self, mem):
        time.sleep(5)
        return super().set_memory(mem)

    def get_settings(self):
        time.sleep(1)
        return super().get_settings()

    def set_settings(self, settings):
        time.sleep(2)
        return super().set_settings(settings)
