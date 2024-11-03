import importlib
import logging
import os
import struct
import time

from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import settings
from chirp import util

LOG = logging.getLogger(__name__)


class FakeLiveRadio(chirp_common.LiveRadio):
    VENDOR = 'CHIRP'
    MODEL = 'Fake Live Radio'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.settings = {'knob': 5}
        self.memories = []
        for i in range(1, 12):
            m = chirp_common.Memory(i, empty=i > 5, name='channel %i' % i)
            m.freq = 146520000
            self.memories.append(m)
        self.memories[-1].extd_number = 'Special'

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 10)
        rf.has_settings = True
        # We don't even implement this interface, but the point of this
        # is to make sure the GUI doesn't choke on live radios.
        rf.has_bank = True
        rf.valid_name_length = 8
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_special_chans = ['Special']
        return rf

    def get_memory(self, number):
        if number == 'Special':
            number = len(self.memories)
        m = self.memories[number - 1]
        if isinstance(m, chirp_common.Memory) and m.number != number:
            LOG.error('fake driver found %i instead of %i',
                      m.number, number)
        return m

    def set_memory(self, mem):
        LOG.info('Set memory %s' % mem)
        self.memories[mem.number - 1] = mem.dupe()

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
            raise m('Error getting %i' % number)
        else:
            return m

    def set_memory(self, mem):
        if not mem.empty and mem.freq < 145000000:
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
            self._rbuf += \
                b'MR 0,001,00146520000,0,0,0,0,0,0,00,00,000,000000000,0,0\r'
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


# NOTE: This is not complete, it's just enough to do the ident dance with
# these radios
class FakeUV17Serial:
    def get_radio(self):
        baofeng_uv17 = importlib.import_module('chirp.drivers.baofeng_uv17')
        self.rclass = baofeng_uv17.UV17

    def __init__(self, *a, **k):
        self._sbuf = b''
        self.get_radio()
        imgfn = os.path.join(os.path.dirname(__file__), '..', '..',
                             'tests', 'images',
                             '%s_%s.img' % (self.rclass.VENDOR,
                                            self.rclass.MODEL))
        LOG.debug('Opening %s' % imgfn)
        try:
            with open(imgfn, 'rb') as f:
                self._img = f.read()
            LOG.debug('Loaded image size 0x%x', len(self._img))
        except FileNotFoundError:
            LOG.error('Unable to open image, fixture will not work')
            self._img = b''

    def write(self, buffer):
        baofeng_uv17Pro = importlib.import_module(
            'chirp.drivers.baofeng_uv17Pro')
        if buffer == self.rclass._magic:
            LOG.debug('Sent first magic')
            self._sbuf += self.rclass._fingerprint
        elif buffer.startswith(b'R'):
            LOG.debug('Got: %s' % util.hexprint(buffer))
            cmd, addr, blen = struct.unpack('>cHb', buffer)
            resp = struct.pack('>cHb', b'W', addr, blen)
            block = self._img[addr:addr + blen] or (b'\x00' * blen)
            LOG.debug('Sending block length 0x%x', len(block))
            self._sbuf += resp + baofeng_uv17Pro._crypt(1, block)
        else:
            for magic, rlen in self.rclass._magics:
                if buffer == magic:
                    LOG.debug('Sent magic %r' % magic)
                    self._sbuf += b' ' * rlen
                    return
            LOG.debug('Unrecognized ident string %r' % buffer)
            self._sbuf += b'\x15' * 32

    def read(self, length):
        chunk = self._sbuf[:length]
        self._sbuf = self._sbuf[length:]
        return chunk

    def close(self):
        pass


class FakeUV17ProSerial(FakeUV17Serial):
    def get_radio(self):
        baofeng_uv17Pro = importlib.import_module(
            'chirp.drivers.baofeng_uv17Pro')
        self.rclass = baofeng_uv17Pro.UV17Pro


class FakeBankModel(chirp_common.BankModel,
                    chirp_common.SpecialBankModelInterface):
    def __init__(self, radio, name='Banks'):
        super().__init__(radio, name)
        self._banks = {i: set() for i in range(5)}

    def get_bankable_specials(self):
        return self._radio.get_features().valid_special_chans[:-1]

    def get_num_mappings(self):
        return len(self._banks)

    def get_mappings(self):
        return [chirp_common.Bank(self, i, 'Bank %i' % i) for i in range(5)]

    def get_memory_mappings(self, memory):
        banks = self.get_mappings()
        in_banks = [i for i in range(5) if memory.number in self._banks[i]]
        return [bank for bank in banks if bank.get_index() in in_banks]

    def add_memory_to_mapping(self, memory, mapping):
        self._banks[mapping.get_index()].add(memory.number)

    def remove_memory_from_mapping(self, memory, mapping):
        self._banks[mapping.get_index()].remove(memory.number)


class FakeClone(chirp_common.CloneModeRadio):
    VENDOR = 'CHIRP'
    MODEL = 'Fake Clone'

    def __init__(self, pipe):
        super().__init__(pipe)
        self._memories = [chirp_common.Memory(i) for i in range(10)]
        # Make sure these are not contiguous with main memory so that there
        # are no edge cases
        self._specials = [chirp_common.Memory(100 + i) for i in range(3)]
        for i, mem in enumerate(self._memories + self._specials):
            mem.freq = 146000000 + (i * 100000)
            mem.empty = i < 5
            if mem in self._specials:
                mem.extd_number = 'Special %i' % mem.number
        self._special_names = [x.extd_number for x in self._specials]

    def get_features(self) -> chirp_common.RadioFeatures:
        rf = chirp_common.RadioFeatures()
        rf.valid_special_chans = self._special_names
        rf.valid_bands = [(144000000, 148000000)]
        rf.memory_bounds = (0, 9)
        rf.has_bank = True
        return rf

    def get_bank_model(self):
        return FakeBankModel(self)

    def get_memory(self, number):
        if isinstance(number, str):
            return self._specials[self._special_names.index(number)]
        else:
            try:
                return self._memories[number]
            except IndexError:
                return self._specials[number - 100]

    def set_memory(self, memory):
        if memory.extd_number:
            self._specials[self._special_names.index(memory.extd_number)] = (
                memory)
        else:
            self._memories[memory.number] = memory


def register_fakes():
    directory.register(FakeLiveRadio)
    directory.register(FakeLiveSlowRadio)
    directory.register(FakeLiveRadioWithErrors)
    directory.register(FakeCloneFail)
    directory.register(FakeClone)
