import os
import unittest

from chirp.drivers import th9800


class Fake9800:
    ident = (b'\x54\x48\x39\x38\x30\x30\xff\xff'
             b'\x56\x31\x34\x78\xff\xff\xff\xff')

    def __init__(self):
        self.writebuf = b''
        # Pre-load the identify dance
        self.readbuf = b'A' + self.ident

    def write(self, data):
        assert isinstance(data, bytes)
        self.writebuf += data
        if data.startswith(b'R'):
            self.readbuf += b'W\x00\x00\x00' + (b'\x00' * 0x80)
        elif data.startswith(b'W'):
            self.writebuf += data
            self.readbuf += b'A'
        elif data == b'A':
            assert len(self.readbuf) == 0
            self.readbuf += b'A'
        elif data == b'ENDW':
            self.readbuf += b'123'

    def read(self, n):
        buf = self.readbuf[:n]
        self.readbuf = self.readbuf[n:]
        return buf


class TestTH9800(unittest.TestCase):
    def test_identify(self):
        f = Fake9800()
        r = th9800.TYTTH9800Radio(f)
        ident = th9800._identify(r)
        self.assertEqual(f.ident, ident)
        self.assertEqual(b'\x02PROGRAM\x02A', f.writebuf)

    def test_download(self):
        f = Fake9800()
        r = th9800.TYTTH9800Radio(f)
        r.sync_in()

    def test_upload(self):
        f = Fake9800()
        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', 'TYT_TH-9800.img')
        r = th9800.TYTTH9800Radio(img)
        r.set_pipe(f)
        r.sync_out()
