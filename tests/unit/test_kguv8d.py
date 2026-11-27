import struct

from chirp.drivers import kguv8e
from chirp.drivers import kguv8d
from chirp.drivers import kguv8dplus
from chirp.drivers import kg935g
from tests.unit import base


class FakeUV8D:
    def __init__(self, rclass):
        self.writebuf = b''
        self.readbuf = b''
        self.rclass = rclass
        self._model = rclass._model

    def write(self, data):
        assert isinstance(data, bytes)
        cmd = data[1]
        response = b''
        if cmd == kguv8d.CMD_ID:
            response = self._model + b'\x00' * 10
        elif cmd == kguv8d.CMD_RD:
            response = b'\x00' * 64
        elif cmd == kguv8d.CMD_WR:
            response = data[4:6]
            if hasattr(self.rclass, 'decrypt'):
                response = self.rclass(None).decrypt(response)
        elif cmd == kguv8d.CMD_END:
            return
        else:
            raise Exception('Unhandled command')
        packet = struct.pack('xxxB', len(response)) + response
        cs = sum(x for x in packet) % 256
        packet += struct.pack('B', cs)
        if hasattr(self.rclass, 'encrypt'):
            payload = self.rclass(None).encrypt(packet[4:])
            packet = packet[:4] + payload

        self.readbuf += packet

    def read(self, n):
        buf = self.readbuf[:n]
        self.readbuf = self.readbuf[n:]
        return buf


class TestKGUV8D(base.RadioTest):
    RCLASS = kguv8d.KGUV8DRadio
    VENDOR_MODEL = 'Wouxun_KG-UV8D'

    def test_identify(self):
        f = FakeUV8D(self.RCLASS)
        r = self.RCLASS(f)
        r._identify()

    def test_download(self):
        f = FakeUV8D(self.RCLASS)
        r = self.RCLASS(f)
        r.sync_in()

    def test_upload(self):
        f = FakeUV8D(self.RCLASS)
        self.radio.set_pipe(f)
        self.radio.sync_out()


class TestKGUV8DPlus(TestKGUV8D):
    RCLASS = kguv8dplus.KGUV8DPlusRadio
    VENDOR_MODEL = 'Wouxun_KG-UV8D_Plus'


class TestKGUV8ER(TestKGUV8D):
    RCLASS = kguv8e.KGUV8ERadio
    VENDOR_MODEL = 'Wouxun_KG-UV8E'


class TestKG935(TestKGUV8D):
    RCLASS = kg935g.KG935GRadio
    VENDOR_MODEL = 'Wouxun_KG-935G'
