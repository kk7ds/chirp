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


def register_fakes():
    directory.register(FakeLiveRadio)
    directory.register(FakeLiveSlowRadio)
    directory.register(FakeLiveRadioWithErrors)
    directory.register(FakeCloneFail)


def encode_uvpro_rf_ch(idx, rx_hz, tx_hz, name='', byte13=0xC0):
    """25-byte RfCh: FM, byte13 default 0xC0 = scan + High."""
    bits = 0
    for width, val in [(8, idx), (2, 0), (30, tx_hz), (2, 0), (30, rx_hz),
                       (16, 0), (16, 0)]:
        bits = (bits << width) | (val & ((1 << width) - 1))
    head = bits.to_bytes(13, 'big')
    return (head + bytes([byte13, 0]) +
            name.encode('ascii')[:10].ljust(10, b'\x00'))


class FakeUVProSerial:
    """Enough GAIA for BTECH UV-PRO live download/upload in the GUI."""

    def __init__(self, *a, **k):
        self._rbuf = b''
        self.sent = []
        self._channels = {}
        for i, (hz, nm) in enumerate([
                (146520000, 'CALL'),
                (146940000, 'RPT1'),
                (147000000, 'RPT2'),
                (446000000, 'UHF1')]):
            self._channels[i] = encode_uvpro_rf_ch(i, hz, hz, nm)
        self.soft_ver = 147
        self.region_count = 6
        self.curr_region = 1
        self.region_name = b'Monmouth'
        self.timeout = 0.25
        self.write_timeout = 2

    def _reply(self, cmd, body):
        payload = struct.pack('>HH', 2, 0x8000 | cmd) + body
        return bytes([0xFF, 0x01, 0x00, len(payload) - 4]) + payload

    def write(self, buffer):
        self.sent.append(bytes(buffer))
        if not buffer.startswith(b'\xff\x01'):
            return
        grp, cmd = struct.unpack('>HH', buffer[4:8])
        if cmd == 4:  # GET_DEV_INFO
            d6 = (self.region_count >> 4) & 0x03
            d7 = ((self.region_count & 0x0F) << 4)
            info = (bytes([6]) + (260).to_bytes(2, 'big') + bytes([1]) +
                    self.soft_ver.to_bytes(2, 'big') +
                    bytes([d6, d7, 30, 0]))
            self._rbuf += self._reply(4, b'\x00' + info)
        elif cmd == 13:  # READ_RF_CH
            ch = buffer[8]
            if ch >= 30:
                self._rbuf += self._reply(13, b'\x05')
            elif ch in self._channels:
                self._rbuf += self._reply(13, b'\x00' + self._channels[ch])
            else:
                self._rbuf += self._reply(
                    13, b'\x00' + encode_uvpro_rf_ch(ch, 0, 0))
        elif cmd == 14:  # WRITE_RF_CH
            rec = bytes(buffer[8:33])
            self._channels[rec[0]] = rec
            self._rbuf += self._reply(14, bytes([0, rec[0]]))
        elif cmd == 20:  # GET_HT_STATUS
            s2 = (self.curr_region >> 2) & 0x0F
            s3 = ((self.curr_region & 0x03) << 6)
            self._rbuf += self._reply(20, b'\x00' + bytes([0x80, 0, s2, s3]))
        elif cmd == 73:  # READ_REGION_NAME
            idx = buffer[8] if len(buffer) > 8 else 0
            name = self.region_name if idx == self.curr_region else b''
            self._rbuf += self._reply(
                73, b'\x00' + bytes([idx]) + name.ljust(10, b'\x00'))
        else:
            self._rbuf += self._reply(cmd, b'\x05')

    def read(self, n):
        ret = self._rbuf[:n]
        self._rbuf = self._rbuf[n:]
        return ret

    def close(self):
        pass

    def log(self, msg):
        pass
