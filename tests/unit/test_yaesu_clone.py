from builtins import bytes
import os
import tempfile
import unittest

from chirp import directory
from chirp.drivers import ft60
from chirp.drivers import ft4
from chirp.drivers import yaesu_clone
from chirp import memmap


class TestYaesuChecksum(unittest.TestCase):
    def _test_checksum(self, mmap):
        cs = yaesu_clone.YaesuChecksum(0, 2, 3)

        self.assertEqual(42, cs.get_existing(mmap))
        self.assertEqual(0x8A, cs.get_calculated(mmap))
        try:
            mmap = mmap.get_byte_compatible()
            mmap[0] = 3
        except AttributeError:
            # str or bytes
            try:
                # str
                mmap = memmap.MemoryMap('\x03' + mmap[1:])
            except TypeError:
                # bytes
                mmap = memmap.MemoryMapBytes(b'\x03' + mmap[1:])

        cs.update(mmap)
        self.assertEqual(95, cs.get_calculated(mmap))

    def test_with_MemoryMap(self):
        mmap = memmap.MemoryMap('...\x2A')
        self._test_checksum(mmap)

    def test_with_MemoryMapBytes(self):
        mmap = memmap.MemoryMapBytes(bytes(b'...\x2A'))
        self._test_checksum(mmap)

    def test_with_bytes(self):
        self._test_checksum(b'...\x2A')

    def test_with_str(self):
        self._test_checksum('...\x2A')


class FakeFT60:
    def __init__(self):
        self.readbuf = b''
        self.writebuf = b''

    def start_download(self):
        self.readbuf += b'\x00' * 8
        for i in range(448):
            self.readbuf += b'\x00' * 64

    def write(self, data):
        assert isinstance(data, bytes)
        # Prepend echo so it is read first next
        self.readbuf = data + self.readbuf

        self.writebuf += data
        if len(data) == 1:
            # If we're doing an upload, we need to ack this
            # last short block
            if self.writebuf.startswith(b'AH017'):
                self.readbuf += b'\x06'
        elif len(data) in (8, 64):
            self.readbuf += b'\x06'
        else:
            raise Exception('Unhandled')

    def read(self, n):
        buf = self.readbuf[:n]
        self.readbuf = self.readbuf[n:]
        return buf


class TestFT60(unittest.TestCase):
    def test_download(self):
        f = FakeFT60()
        f.start_download()
        r = ft60.FT60Radio(f)
        r.sync_in()
        # Make sure the ACKs are there
        self.assertEqual(449, len(f.writebuf))
        self.assertEqual(f.writebuf, b'\x06' * 449)

    def test_upload(self):
        f = FakeFT60()
        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', 'Yaesu_FT-60.img')
        r = ft60.FT60Radio(img)
        r.set_pipe(f)
        r.sync_out()


class FakeFTX4:
    ID = ft4.YaesuFT4XERadio.id_str

    def __init__(self):
        self.readbuf = b''
        self.writebuf = b''

    def write(self, buf):
        assert isinstance(buf, bytes)
        # Echo
        self.readbuf = buf + self.readbuf
        if buf.startswith(b'PROGRAM'):
            self.readbuf += b'QX'
        elif buf == b'\x02':
            # Ident
            self.readbuf += self.ID
        elif buf.startswith(b'R'):
            resp = b'W' + buf[1:] + b'\x00' * 16
            self.readbuf += resp + bytes([ft4.checkSum8(resp[1:])])
        elif buf.startswith(b'W'):
            pass
        elif buf == b'END':
            pass
        else:
            raise Exception('Unhandled %r' % buf)
        self.readbuf += b'\x06'

    def read(self, n):
        buf = self.readbuf[:n]
        self.readbuf = self.readbuf[n:]
        return buf


class FakeFT25R(FakeFTX4):
    ID = ft4.YaesuFT25RRadio.id_str


class FakeFT25R_Asian(FakeFTX4):
    ID = ft4.YaesuFT25RRadio.id_str[:-1] + b'\x03'


class TestFTX4(unittest.TestCase):
    RCLASS = ft4.YaesuFT4XERadio
    FAKE = FakeFTX4

    def test_download(self):
        f = self.FAKE()
        r = self.RCLASS(f)
        r.sync_in()
        self.assertEqual(f.ID[-1], r.subtype)

    def test_upload(self):
        f = self.FAKE()
        fn = directory.radio_class_id(self.RCLASS)
        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', '%s.img' % fn)
        r = self.RCLASS(img)
        r.set_pipe(f)
        r.sync_out()

    def test_download_open(self):
        f = self.FAKE()
        r = self.RCLASS(f)
        r.sync_in()
        # Make sure we got subtype set as expected after download
        self.assertEqual(f.ID[-1], r.subtype)

        # Save it out to a file
        fn = tempfile.mktemp('.img', 'ft4')
        r.save(fn)

        # Make sure if we re-load our image, we keep the same subtype
        r = self.RCLASS(fn)
        self.assertEqual(f.ID[-1], r.subtype)


class TestFT25(TestFTX4):
    RCLASS = ft4.YaesuFT25RRadio
    FAKE = FakeFT25R


class TestFT25_Asian(TestFT25):
    FAKE = FakeFT25R_Asian
