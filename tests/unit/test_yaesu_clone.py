from builtins import bytes
import os
import shutil
import subprocess
import tempfile
import unittest

from chirp import directory
from chirp import errors
from chirp.drivers import ft60
from chirp.drivers import ft4
from chirp.drivers import ftm300d
from chirp.drivers import yaesu_clone
from chirp import memmap
from chirp.settings import RadioSetting


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


class TestFTM300Freq(unittest.TestCase):
    def test_roundtrip_calling(self):
        mmap, freq = ftm300d.parse_freq_bytes(b"\x00" * 3)
        ftm300d.encode_freq(freq, 146520000)
        self.assertEqual(bytes.fromhex("01 46 52"), mmap.get_packed())
        self.assertEqual(146520000, ftm300d.decode_freq(freq))

    def test_6_25_extra_from_dump(self):
        raw = bytes.fromhex("a4 46 00")
        mmap, freq = ftm300d.parse_freq_bytes(raw)
        self.assertEqual(446006250, ftm300d.decode_freq(freq))
        ftm300d.encode_freq(freq, 446006250)
        self.assertEqual(raw, mmap.get_packed())

    def test_tsql_r_from_adms_rev_tone(self):
        # Dump 31: Tone Mode=REV TONE, byte 5 high nibble 3.
        raw = bytes.fromhex("81 40 01 46 52 30 00 00 00 08 00 0f 00 0c 00 00")
        self.assertEqual(3, raw[5] >> 4)
        self.assertEqual("TSQL-R", ftm300d.TMODE_FROM_RADIO[3])
        self.assertEqual(3, ftm300d.TMODE_TO_RADIO["TSQL-R"])

    def test_timezone_sign_magnitude(self):
        self.assertEqual(0, ftm300d.timezone_from_fields(0, 0))
        self.assertEqual(1, ftm300d.timezone_from_fields(0, 1))
        self.assertEqual(-1, ftm300d.timezone_from_fields(1, 1))
        self.assertEqual((0, 0), ftm300d.timezone_to_fields(0))
        self.assertEqual((0, 1), ftm300d.timezone_to_fields(1))
        self.assertEqual((1, 1), ftm300d.timezone_to_fields(-1))
        self.assertEqual((1, 16), ftm300d.timezone_to_fields(-16))
        self.assertEqual("UTC \u00b10:00", ftm300d.timezone_label(0))
        self.assertEqual("UTC +0:30", ftm300d.timezone_label(1))
        self.assertEqual("UTC -0:30", ftm300d.timezone_label(-1))
        self.assertEqual("UTC -8:00", ftm300d.timezone_label(-16))
        self.assertEqual(57, len(ftm300d.TIMEZONE_LABELS))


def _setting_map(settings):
    found = {}
    for element in settings:
        if isinstance(element, RadioSetting):
            found[element.get_name()] = str(element.value)
        else:
            found.update(_setting_map(element))
    return found


class FakeFTM300:
    """SCU-56 style pipe: no echo of the host frame into the read stream.

    acks: None (no reply), a 1-byte bytes (always that reply on a 131-byte
    write), or a list of 1-byte replies popped per 131-byte write.
    """

    def __init__(self, readbuf=b"", chunk=None, acks=None):
        self.readbuf = readbuf
        self.writebuf = b""
        self.timeout = 0.25
        self.chunk = chunk
        self.acks = acks

    def write(self, data):
        assert isinstance(data, bytes)
        self.writebuf += data
        if len(data) != ftm300d.FRAME_LEN or self.acks is None:
            return
        if isinstance(self.acks, list):
            if self.acks:
                self.readbuf += self.acks.pop(0)
        else:
            self.readbuf += self.acks

    def read(self, n):
        take = n if self.chunk is None else min(n, self.chunk)
        buf = self.readbuf[:take]
        self.readbuf = self.readbuf[take:]
        return buf


class TestFTM300Clone(unittest.TestCase):
    def _golden(self):
        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', 'Yaesu_FTM-300DR.img')
        return ftm300d.FTM300Radio(img)

    def test_clone_address_list(self):
        addrs = ftm300d.clone_addresses()
        self.assertEqual(768, len(addrs))
        self.assertEqual([0x0000, 0x0100, 0x0180], addrs[:3])
        self.assertEqual(0xFF80, addrs[509])
        self.assertNotIn(0x0080, addrs[:510])
        self.assertNotIn(0x0400, addrs[:510])
        self.assertEqual(0x0000, addrs[510])
        self.assertEqual(0x0080, addrs[511])
        self.assertEqual([0x7F80, 0xFFFD, 0xFFFE], addrs[-3:])

    def test_emitter_trailer_and_checksums(self):
        src = self._golden()
        mmap = src.get_mmap().get_packed()
        frames = ftm300d.image_to_clone_frames(mmap)
        self.assertEqual(768, len(frames))
        for frame in frames:
            self.assertEqual(ftm300d.FRAME_LEN, len(frame))
            self.assertEqual(sum(frame[:130]) % 256, frame[130])
        vfo = frames[-2]
        self.assertEqual(b"\xff\xfd", vfo[:2])
        self.assertEqual(mmap[0x80:0x100], vfo[2:130])
        end = frames[-1]
        self.assertEqual(b"\xff\xfe" + b"\x00" * 128 + b"\xfd", end)

    def test_emitter_inverts_download(self):
        src = self._golden()
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        dst = ftm300d.FTM300Radio(FakeFTM300(b"".join(frames)))
        dst.sync_in()
        self.assertEqual(frames, ftm300d.image_to_clone_frames(dst.get_mmap()))

    def test_download(self):
        src = self._golden()
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        self.assertEqual(768, len(frames))
        self.assertEqual(ftm300d.FRAME_LEN, len(frames[0]))

        fake = FakeFTM300(b"".join(frames))
        dst = ftm300d.FTM300Radio(fake)
        dst.sync_in()

        self.assertEqual(b"\x06" * 768, fake.writebuf)
        self.assertEqual(38400, ftm300d.FTM300Radio.BAUD_RATE)

        srcb = src.get_mmap().get_packed()
        got = dst.get_mmap().get_packed()
        self.assertEqual(src._memsize, len(got))
        self.assertEqual(srcb[:0x400], got[:0x400])
        self.assertEqual(b"\x00" * 0x80, got[0x400:0x480])
        self.assertEqual(srcb[0x480:], got[0x480:])

        mem = dst.get_memory(1)
        self.assertEqual(src.get_memory(1).freq, mem.freq)
        self.assertEqual(src.get_memory(1).name, mem.name)

    def test_download_byte_at_a_time(self):
        src = self._golden()
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        dst = ftm300d.FTM300Radio(
            FakeFTM300(b"".join(frames), chunk=1))
        dst.sync_in()
        self.assertEqual(src.get_memory(1).freq, dst.get_memory(1).freq)
        self.assertEqual(b"\x06" * 768, dst.pipe.writebuf)

    def test_download_no_response(self):
        dst = ftm300d.FTM300Radio(FakeFTM300(b""))
        with self.assertRaises(errors.RadioNoResponse):
            dst.sync_in()

    def test_download_bad_ident(self):
        src = self._golden()
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        payload = bytearray(frames[0][2:130])
        payload[:5] = b"XXXXX"
        frames[0] = ftm300d.clone_frame(0, bytes(payload))
        dst = ftm300d.FTM300Radio(FakeFTM300(b"".join(frames)))
        with self.assertRaisesRegex(errors.RadioError, "ident"):
            dst.sync_in()

    def test_download_bad_checksum(self):
        src = self._golden()
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        bad = bytearray(frames[0])
        bad[-1] ^= 0xFF
        dst = ftm300d.FTM300Radio(FakeFTM300(bytes(bad)))
        with self.assertRaisesRegex(errors.RadioError, "checksum"):
            dst.sync_in()

    def test_upload(self):
        src = self._golden()
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        fake = FakeFTM300(acks=b"\x06")
        src.set_pipe(fake)
        src.sync_out()
        self.assertEqual(b"".join(frames), fake.writebuf)
        self.assertEqual(b"", fake.readbuf)

    def test_clone_out_writes_acked_stream(self):
        src = self._golden()
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        fake = FakeFTM300(acks=b"\x06")
        src.set_pipe(fake)
        ftm300d._clone_out(src)
        self.assertEqual(b"".join(frames), fake.writebuf)
        self.assertEqual(b"", fake.readbuf)

    def test_clone_out_no_ack(self):
        src = self._golden()
        fake = FakeFTM300()
        src.set_pipe(fake)
        with self.assertRaises(errors.RadioNoResponse):
            ftm300d._clone_out(src)
        # First frame retried; later frames not sent.
        first = ftm300d.image_to_clone_frames(src.get_mmap())[0]
        self.assertEqual(first * 30, fake.writebuf)

    def test_clone_out_refused(self):
        src = self._golden()
        fake = FakeFTM300(acks=b"\x00")
        src.set_pipe(fake)
        with self.assertRaisesRegex(errors.RadioError, "refused"):
            ftm300d._clone_out(src)
        first = ftm300d.image_to_clone_frames(src.get_mmap())[0]
        self.assertEqual(first, fake.writebuf)

    def test_clone_out_timeout_after_first(self):
        src = self._golden()
        fake = FakeFTM300(acks=[b"\x06"])
        src.set_pipe(fake)
        with self.assertRaisesRegex(errors.RadioError, "ACK"):
            ftm300d._clone_out(src)
        frames = ftm300d.image_to_clone_frames(src.get_mmap())
        self.assertEqual(frames[0] + frames[1], fake.writebuf)

    def test_emitter_matches_adms_put_capture(self):
        # Local capture only; CI does not ship the pcap.
        pcap = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'ignored', 'yaesu', 'ftm-300dr', 'clone-sniff',
            'adms-put.pcapng')
        if not os.path.exists(pcap) or not shutil.which('tshark'):
            self.skipTest('ADMS PUT capture or tshark not available')
        out = subprocess.check_output(
            ['tshark', '-r', pcap, '-Y', 'usb.data_len == 131',
             '-T', 'fields', '-e', 'usb.capdata'],
            stderr=subprocess.DEVNULL)
        captured = [bytes.fromhex(line.strip())
                    for line in out.decode().splitlines() if line.strip()]
        self.assertEqual(769, len(captured))
        # First URB had no ACK; identical retry starts the 768-frame clone.
        self.assertEqual(captured[0], captured[1])
        acked = captured[1:]
        self.assertEqual(
            ftm300d.clone_addresses(),
            [int.from_bytes(frame[:2], 'big') for frame in acked])
        radio = ftm300d.FTM300Radio(FakeFTM300(b"".join(acked)))
        radio.sync_in()
        self.assertEqual(
            acked, ftm300d.image_to_clone_frames(radio.get_mmap()))

    def test_settings_defaults_and_roundtrip(self):
        src = self._golden()
        values = _setting_map(src.get_settings())
        self.assertEqual("INCH", values["unit"])
        self.assertEqual("UTC \u00b10:00", values["timezone"])

        settings = src.get_settings()
        src.set_settings(settings)
        for group in settings:
            if isinstance(group, RadioSetting):
                continue
            for setting in group:
                if setting.get_name() == "unit":
                    setting.value = "METRIC"
                elif setting.get_name() == "timezone":
                    setting.value = "UTC -8:00"
        src.set_settings(settings)

        packed = src.get_mmap().get_packed()
        self.assertEqual(0x00, packed[0xA1])
        self.assertEqual(0x90, packed[0xA8])
        values = _setting_map(src.get_settings())
        self.assertEqual("METRIC", values["unit"])
        self.assertEqual("UTC -8:00", values["timezone"])

        settings = src.get_settings()
        for group in settings:
            if isinstance(group, RadioSetting):
                continue
            for setting in group:
                if setting.get_name() == "lcd_brightness":
                    setting.value = "MIN"
                elif setting.get_name() == "callsign":
                    setting.value = "N0CALL/A"
                elif setting.get_name() == "aprs_call":
                    setting.value = "N0CALL"
        src.set_settings(settings)
        packed = src.get_mmap().get_packed()
        self.assertEqual(0x03, packed[0x28F])
        self.assertEqual(
            b"N0CALL/A" + b"\xff" * 2, packed[0x2C8:0x2D2])
        self.assertEqual(b"N0CALL", packed[0x508:0x50E])
        values = _setting_map(src.get_settings())
        self.assertEqual("MIN", values["lcd_brightness"])
        self.assertEqual("N0CALL/A", values["callsign"])
        self.assertEqual("N0CALL", values["aprs_call"])

    def test_settings_from_live_dumps(self):
        dump_dir = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'ignored', 'yaesu', 'ftm-300dr', 'chirp-dumps')
        cases = [
            ('Yaesu_FTM-300DR_20260906.img',
             'INCH', 'UTC \u00b10:00'),
            ('Yaesu_FTM-300DR_20260906_timezone=UTC+0:30.img',
             'INCH', 'UTC +0:30'),
            ('Yaesu_FTM-300DR_20260906_timezone=UTC-0:30.img',
             'INCH', 'UTC -0:30'),
            ('Yaesu_FTM-300DR_20260906_unit=metric.img',
             'METRIC', 'UTC \u00b10:00'),
        ]
        missing = [name for name, _, _ in cases
                   if not os.path.exists(os.path.join(dump_dir, name))]
        if missing:
            self.skipTest('live dumps not present: %s' % missing[0])
        for name, unit, tz in cases:
            radio = ftm300d.FTM300Radio(os.path.join(dump_dir, name))
            values = _setting_map(radio.get_settings())
            self.assertEqual(unit, values['unit'], name)
            self.assertEqual(tz, values['timezone'], name)

        extra = [
            ('Yaesu_FTM-300DR_20260906.img',
             {'lcd_brightness': 'MAX', 'callsign': 'A', 'aprs_call': ''}),
            ('Yaesu_FTM-300DR_20260906_display-brightness=min.img',
             {'lcd_brightness': 'MIN'}),
            ('Yaesu_FTM-300DR_20260906_display-brightness=mid.img',
             {'lcd_brightness': 'MID'}),
            ('Yaesu_FTM-300DR_20260906_callsign=B.img',
             {'callsign': 'B'}),
            ('Yaesu_FTM-300DR_20260906_callsign-aprs=B.img',
             {'aprs_call': 'A'}),
        ]
        for name, expect in extra:
            path = os.path.join(dump_dir, name)
            if not os.path.exists(path):
                self.skipTest('live dumps not present: %s' % name)
            radio = ftm300d.FTM300Radio(path)
            values = _setting_map(radio.get_settings())
            for key, want in expect.items():
                self.assertEqual(want, values[key], '%s %s' % (name, key))
