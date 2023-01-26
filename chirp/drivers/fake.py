import logging
import time

from chirp import chirp_common
from chirp import directory
from chirp import errors
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
        # We don't even implement this interface, but the point of this
        # is to make sure the GUI doesn't choke on live radios.
        rf.has_bank = True
        rf.valid_name_length = 8
        rf.valid_characters = chirp_common.CHARSET_ASCII
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


class FakeLiveRadioWithErrors(FakeLiveRadio):
    VARIANT = 'Errors'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.memories[2] = errors.RadioError
        self.memories[3] = Exception

    def get_memory(self, number):
        m = super().get_memory(number)
        if isinstance(m, type):
            raise m('Error')
        else:
            return m

    def set_memory(self, mem):
        if mem.freq < 145000000:
            raise errors.RadioError('Out of range')
        else:
            return super().set_memory(mem)


class FakeCloneFail(chirp_common.CloneModeRadio):
    VENDOR = 'CHIRP'
    MODEL = 'Fake Clone Radio'
    VARIANT = 'Errors'

    def sync_in(self):
        s = chirp_common.Status()
        s.max = 100
        s.cur = 10
        s.msg = 'Gonna fail...'
        self.status_fn(s)
        raise errors.RadioError('This always fails')


class FakeKenwoodSerial:
    def __init__(self, *a, **k):
        self._rbuf = b''

    def write(self, buffer):
        LOG.debug('Write: %r' % buffer)
        if buffer.startswith(b'ID'):
            self._rbuf += b'ID TH-F7\r'
        elif buffer.startswith(b'MR 0,001'):
            self._rbuf += b'MR 0,001,00146520000,0,0,0,0,0,0,00,00,000,000000000,0,0\r'
        elif buffer.startswith(b'MNA 001\r'):
            self._rbuf += b'MNA 001,Foo\r'
        elif buffer.startswith(b'MNA 0'):
            self._rbuf += buffer
        elif buffer.startswith(b'MW 0'):
            self._rbuf += b'MW\r'
        else:
            self._rbuf += b'N\r'

    def read(self, n):
        ret = self._rbuf[:n]
        self._rbuf = self._rbuf[n:]
        return ret


def register_fakes():
    directory.register(FakeLiveRadio)
    directory.register(FakeLiveSlowRadio)
    directory.register(FakeLiveRadioWithErrors)
    directory.register(FakeCloneFail)
