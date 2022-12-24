import os
import struct
import unittest

from chirp.drivers import kguv8d


class FakeUV8D:
    def __init__(self):
        self.writebuf = b''
        self.readbuf = b''

    def write(self, data):
        assert isinstance(data, bytes)
        cmd = data[1]
        response = b''
        if cmd == kguv8d.CMD_ID:
            response = kguv8d.KGUV8DRadio._model + b'\x00' * 10
        elif cmd == kguv8d.CMD_RD:
            response = b'\x00' * 64
        elif cmd == kguv8d.CMD_WR:
            response = data[4:6]
        elif cmd == kguv8d.CMD_END:
            return
        else:
            raise Exception('Unhandled command')
        packet = struct.pack('xxxB', len(response)) + response
        cs = sum(x for x in packet)
        self.readbuf += packet + struct.pack('B', cs % 256)

    def read(self, n):
        buf = self.readbuf[:n]
        self.readbuf = self.readbuf[n:]
        return buf

class TestKGUV8D(unittest.TestCase):
    def test_identify(self):
        f = FakeUV8D()
        r = kguv8d.KGUV8DRadio(f)
        r._identify()

    def test_download(self):
        f = FakeUV8D()
        r = kguv8d.KGUV8DRadio(f)
        r.sync_in()

    def test_upload(self):
        f = FakeUV8D()
        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', 'Wouxun_KG-UV8D.img')
        r = kguv8d.KGUV8DRadio(img)
        r.set_pipe(f)
        r.sync_out()