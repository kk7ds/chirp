from builtins import bytes
import os
import random
import shutil
import struct
import subprocess
import tempfile
import unittest

from chirp import bitwise
from chirp import directory
from chirp import errors
from chirp.drivers import ft60
from chirp.drivers import ft4
from chirp.drivers import ftm150
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


def _iter_settings(settings):
    for element in settings:
        if isinstance(element, RadioSetting):
            yield element
        else:
            yield from _iter_settings(element)


def _setting_map(settings):
    found = {}
    for s in _iter_settings(settings):
        val = s.value
        if hasattr(val, "format"):
            found[s.get_name()] = val.format()
        else:
            found[s.get_name()] = str(val)
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
        for setting in _iter_settings(settings):
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
        for setting in _iter_settings(settings):
            name = setting.get_name()
            if name == "lcd_brightness":
                setting.value = "MIN"
            elif name == "callsign":
                setting.value = "N0CALL/A"
            elif name == "aprs_call":
                setting.value = "N0CALL"
            elif name == "aprs_ssid":
                setting.value = "13"
            elif name == "aprs_modem":
                setting.value = "ON"
            elif name == "beep":
                setting.value = "HIGH"
            elif name == "ams_tx_mode":
                setting.value = "TX DN Fixed"
            elif name == "fm_bandwidth_a":
                setting.value = "NARROW"
            elif name == "date_fmt":
                setting.value = "YYYY/MMM/DD"
            elif name == "time_12hr":
                setting.value = "12 HOUR"
            elif name == "clock_type_b":
                setting.value = "B"
            elif name == "rx_mode_a":
                setting.value = "AM"
            elif name == "rx_mode_b":
                setting.value = "FM"
            elif name == "standby_beep_off":
                setting.value = "OFF"
            elif name == "digital_vw":
                setting.value = "ON"
            elif name == "location_service":
                setting.value = "OFF"
            elif name == "digital_popup":
                setting.value = "CONTINUE"
            elif name == "mic_gain":
                setting.value = "MAX"
            elif name == "target_location":
                setting.value = "NUMERIC"
            elif name == "compass":
                setting.value = "NORTH UP"
            elif name == "band_scope":
                setting.value = "NARROW"
            elif name == "display_mode":
                setting.value = "GPS INFORMATION"
            elif name == "sub_band_mute":
                setting.value = "OFF"
            elif name == "vox":
                setting.value = "HIGH"
            elif name == "vox_delay":
                setting.value = "3.0 SEC"
            elif name == "recording_band":
                setting.value = "B"
            elif name == "recording_mic":
                setting.value = "ON"
            elif name == "gps_datum":
                setting.value = "TOKYO MEAN"
            elif name == "gps_device":
                setting.value = "EXTERNAL"
            elif name == "rpt_ars_a":
                setting.value = "OFF"
            elif name == "rpt_shift_freq_a":
                setting.value = 1.45
            elif name == "rpt_shift_freq_b":
                setting.value = 3.10
            elif name == "vfo_step_a":
                setting.value = "10.0 kHz"
            elif name == "rx_coverage_a":
                setting.value = "NORMAL"
            elif name == "tot":
                setting.value = "30 MIN"
            elif name == "gps_log":
                setting.value = "60 SEC"
            elif name == "apo":
                setting.value = "12.0 HOUR"
        src.set_settings(settings)
        packed = src.get_mmap().get_packed()
        self.assertEqual(0x08, packed[0xEB])
        self.assertEqual(0x10, packed[0xFA])
        self.assertEqual(0x02, packed[0xEE])
        self.assertEqual(0x20, packed[0x81] & 0x20)
        self.assertEqual(0x00, packed[0x91] & 0x20)
        self.assertEqual(0x80, packed[0x9A])
        self.assertEqual(0x00, packed[0xE3] & 0x10)
        self.assertEqual(0x02, packed[0xE3] & 0x02)
        self.assertEqual(0x10, packed[0x81] & 0x10)
        self.assertEqual(0x00, packed[0xF3] & 0x10)
        self.assertEqual(0x02, packed[0xF3] & 0x02)
        self.assertEqual(0x00, packed[0x91] & 0x10)
        self.assertEqual(0x96, packed[0xE8])
        self.assertEqual(0x00, packed[0x2D6])
        self.assertEqual(0x20, packed[0xE5] & 0x20)
        self.assertEqual(0x03, packed[0xAD])
        self.assertEqual(0xFF, packed[0x2DB])
        self.assertEqual(0x04, packed[0x2DD])
        self.assertEqual(0x03, packed[0xE9] & 0x03)
        self.assertEqual(0x02, packed[0xB6])
        self.assertEqual(0x05, packed[0xB7])
        self.assertEqual(0x02, packed[0xB8])
        self.assertEqual(0x08, packed[0xEA] & 0x08)
        self.assertEqual(0xB2, packed[0xAF])
        self.assertEqual(0x80, packed[0xEC] & 0x80)
        self.assertEqual(0x00, packed[0xE4] & 0x04)
        self.assertEqual(0x04, packed[0xF4] & 0x04)
        self.assertEqual(0x1D, packed[0x8D])
        self.assertEqual(0x3E, packed[0x9D])
        self.assertEqual(0x03, packed[0x85] & 0x0F)
        self.assertEqual(0x00, packed[0xE3] & 0x08)
        self.assertEqual(0x00, packed[0xE3] & 0x20)
        self.assertEqual(0x20, packed[0xF3] & 0x20)
        self.assertEqual(0x05, packed[0xAA])
        self.assertEqual(0x06, packed[0xB5])
        self.assertEqual(0x18, packed[0xA4])
        self.assertEqual(0x10, packed[0xF9] & 0x10)
        self.assertEqual(0x00, packed[0xF9] & 0x07)
        self.assertEqual(0x03, packed[0x28F])
        self.assertEqual(
            b"N0CALL/A" + b"\xff" * 2, packed[0x2C8:0x2D2])
        self.assertEqual(b"N0CALL", packed[0x508:0x50E])
        self.assertEqual(0x0D, packed[0x50E])
        self.assertEqual(0x01, packed[0x534])
        values = _setting_map(src.get_settings())
        self.assertEqual("MIN", values["lcd_brightness"])
        self.assertEqual("N0CALL/A", values["callsign"])
        self.assertEqual("N0CALL", values["aprs_call"])
        self.assertEqual("13", values["aprs_ssid"])
        self.assertEqual("ON", values["aprs_modem"])
        self.assertEqual("HIGH", values["beep"])
        self.assertEqual("TX DN Fixed", values["ams_tx_mode"])
        self.assertEqual("NARROW", values["fm_bandwidth_a"])
        self.assertEqual("WIDE", values["fm_bandwidth_b"])
        self.assertEqual("YYYY/MMM/DD", values["date_fmt"])
        self.assertEqual("12 HOUR", values["time_12hr"])
        self.assertEqual("B", values["clock_type_b"])
        self.assertEqual("AM", values["rx_mode_a"])
        self.assertEqual("FM", values["rx_mode_b"])
        self.assertEqual("OFF", values["standby_beep_off"])
        self.assertEqual("ON", values["digital_vw"])
        self.assertEqual("OFF", values["location_service"])
        self.assertEqual("CONTINUE", values["digital_popup"])
        self.assertEqual("MAX", values["mic_gain"])
        self.assertEqual("NUMERIC", values["target_location"])
        self.assertEqual("NORTH UP", values["compass"])
        self.assertEqual("NARROW", values["band_scope"])
        self.assertEqual("GPS INFORMATION", values["display_mode"])
        self.assertEqual("OFF", values["sub_band_mute"])
        self.assertEqual("HIGH", values["vox"])
        self.assertEqual("3.0 SEC", values["vox_delay"])
        self.assertEqual("B", values["recording_band"])
        self.assertEqual("ON", values["recording_mic"])
        self.assertEqual("TOKYO MEAN", values["gps_datum"])
        self.assertEqual("EXTERNAL", values["gps_device"])
        self.assertEqual("OFF", values["rpt_ars_a"])
        self.assertEqual("ON", values["rpt_ars_b"])
        self.assertEqual("1.45", values["rpt_shift_freq_a"])
        self.assertEqual("3.10", values["rpt_shift_freq_b"])
        self.assertEqual("10.0 kHz", values["vfo_step_a"])
        self.assertEqual("NORMAL", values["rx_coverage_a"])
        self.assertEqual("WIDE", values["rx_coverage_b"])
        self.assertEqual("30 MIN", values["tot"])
        self.assertEqual("60 SEC", values["gps_log"])
        self.assertEqual("12.0 HOUR", values["apo"])

        settings = src.get_settings()
        for setting in _iter_settings(settings):
            if setting.get_name() == "aprs_ssid":
                setting.value = ""
        src.set_settings(settings)
        packed = src.get_mmap().get_packed()
        self.assertEqual(0xCA, packed[0x50E])
        values = _setting_map(src.get_settings())
        self.assertEqual("", values["aprs_ssid"])


def _ftm150_synthetic_image():
    rnd = random.Random(150)
    data = bytearray(rnd.randbytes(ftm150.FTM150Radio._memsize))
    data[0:5] = ftm150.FTM150Radio._model
    return data


class FakeFTM150Receiver:
    """Collects uploaded frames and ACKs each one, like [59 Other -> This]."""
    timeout = None

    def __init__(self, ack=b"\x06"):
        self.frames = []
        self._ack = ack

    def write(self, data):
        self.frames.append(bytes(data))

    def read(self, count):
        return self._ack


class FakeFTM150Sender:
    """Plays a canned clone stream, like [58 This -> Other]."""
    timeout = None

    def __init__(self, frames):
        self._buf = b"".join(frames)
        self.acks = b""

    def write(self, data):
        self.acks += data

    def read(self, count):
        out, self._buf = self._buf[:count], self._buf[count:]
        return out


class TestFTM150Clone(unittest.TestCase):
    def _radio(self, pipe, data=None):
        radio = ftm150.FTM150Radio(pipe)
        if data is not None:
            radio._mmap = memmap.MemoryMapBytes(bytes(data))
            radio.process_mmap()
        return radio

    def test_upload_stream(self):
        data = _ftm150_synthetic_image()
        pipe = FakeFTM150Receiver()
        data[ftm150.FILE_CHECKSUM_AT] = 0x5A
        radio = self._radio(pipe, data)
        radio.sync_out()

        addrs = [struct.unpack(">H", f[:2])[0] for f in pipe.frames]
        self.assertEqual(ftm300d.clone_addresses(), addrs)
        for frame in pipe.frames:
            self.assertEqual(ftm300d.FRAME_LEN, len(frame))
            self.assertEqual(sum(frame[:-1]) % 256, frame[-1])

        # The file checksum goes out as 0x00, like the radio sends it, but
        # only in pass 1: pass 2's block 0x0000 is name table data.
        self.assertEqual(0, pipe.frames[0][2 + ftm150.FILE_CHECKSUM_AT])
        # ... while the image keeps it.
        self.assertEqual(
            b"\x5A", radio.get_mmap()[ftm150.FILE_CHECKSUM_AT])
        pass2 = addrs.index(0, 1)
        self.assertEqual(
            data[0x10000:0x10080], pipe.frames[pass2][2:2 + 128])

    def test_upload_download_roundtrip(self):
        data = _ftm150_synthetic_image()
        up = FakeFTM150Receiver()
        self._radio(up, data).sync_out()

        down = FakeFTM150Sender(up.frames)
        radio = self._radio(down)
        radio.sync_in()
        result = radio.get_mmap().get_packed()

        self.assertEqual(b"\x06" * len(ftm300d.clone_addresses()),
                         down.acks)
        # Block 0x0400 is never transmitted; the checksum is recomputed.
        expected = bytearray(data)
        expected[0x0400:0x0480] = b"\x00" * 128
        expected[ftm150.FILE_CHECKSUM_AT] = (
            sum(expected[:ftm150.FILE_CHECKSUM_AT]) % 256)
        self.assertEqual(bytes(expected), result)

    def test_upload_refused(self):
        pipe = FakeFTM150Receiver(ack=b"\x15")
        with self.assertRaises(errors.RadioError):
            self._radio(pipe, _ftm150_synthetic_image()).sync_out()
        self.assertEqual(1, len(pipe.frames))

    def test_upload_no_response(self):
        pipe = FakeFTM150Receiver(ack=b"")
        with self.assertRaises(errors.RadioNoResponse):
            self._radio(pipe, _ftm150_synthetic_image()).sync_out()
        self.assertEqual(30, len(pipe.frames))

    def test_upload_wrong_image(self):
        data = _ftm150_synthetic_image()
        data[0:5] = b"AH071"
        pipe = FakeFTM150Receiver()
        with self.assertRaises(errors.RadioError):
            self._radio(pipe, data).sync_out()
        self.assertEqual([], pipe.frames)


def _ftm150_freq(raw):
    mmap = memmap.MemoryMapBytes(bytes(raw))
    freq = bitwise.parse(
        ftm150.YFREQ_FORMAT + "struct yfreq freq;", mmap).freq
    return mmap, freq


class TestFTM150Freq(unittest.TestCase):
    def test_roundtrip_calling(self):
        mmap, freq = _ftm150_freq(b"\x00" * 3)
        ftm150.encode_freq(freq, 145500000)
        self.assertEqual(bytes.fromhex("01 45 50"), mmap.get_packed())
        self.assertEqual(145500000, ftm150.decode_freq(freq))

    def test_6_25_from_dump(self):
        # 5 kHz + 1.25 kHz, i.e. fine = 0b1010 = 10 x 625 Hz.
        raw = bytes.fromhex("a4 46 00")
        mmap, freq = _ftm150_freq(raw)
        self.assertEqual(10, int(freq.fine))
        self.assertEqual(446006250, ftm150.decode_freq(freq))
        ftm150.encode_freq(freq, 446006250)
        self.assertEqual(raw, mmap.get_packed())

    def test_every_625_step(self):
        mmap, freq = _ftm150_freq(b"\x00" * 3)
        for fine in range(16):
            hz = 433000000 + fine * 625
            ftm150.encode_freq(freq, hz)
            self.assertEqual(hz, ftm150.decode_freq(freq))
            self.assertEqual(bytes([fine << 4 | 4, 0x33, 0x00]),
                             mmap.get_packed())

    def test_8_33_rounds_down_to_625_step(self):
        # Airband 8.33 kHz channels do not fit; same as ftm300d does.
        mmap, freq = _ftm150_freq(b"\x00" * 3)
        ftm150.encode_freq(freq, 118008333)
        self.assertEqual(118008125, ftm150.decode_freq(freq))


class TestFTM150SqlOverride(unittest.TestCase):
    def setUp(self):
        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', 'Yaesu_FTM-150E.img')
        self.radio = ftm150.FTM150Radio(img)
        self._mem = self.radio._memobj.memory[0]
        self.assertTrue(int(self._mem.used))

    def _override(self, mem):
        return str(mem.extra["sql_override"].value)

    def test_pr_freq_and_pager_survive_write(self):
        for raw, name in ((5, "PR FREQ"), (6, "PAGER")):
            self._mem.tone_mode = raw
            mem = self.radio.get_memory(1)
            self.assertEqual("", mem.tmode)
            self.assertEqual(name, self._override(mem))
            self.radio.set_memory(mem)
            self.assertEqual(raw, int(self._mem.tone_mode))

    def test_override_wins_over_tmode(self):
        self._mem.tone_mode = 1
        mem = self.radio.get_memory(1)
        self.assertEqual("(None)", self._override(mem))
        mem.extra["sql_override"].value = "PAGER"
        self.radio.set_memory(mem)
        self.assertEqual(6, int(self._mem.tone_mode))

    def test_clearing_override_uses_tmode(self):
        self._mem.tone_mode = 6
        mem = self.radio.get_memory(1)
        mem.tmode = "TSQL"
        mem.extra["sql_override"].value = "(None)"
        self.radio.set_memory(mem)
        self.assertEqual(2, int(self._mem.tone_mode))

    def test_records_from_adms(self):
        # Channel 1 as ADMS-17 wrote it: (record, mode, CTCSS, User CTCSS)
        for raw, override, rtone, pr_freq in (
                ("81 04 01 44 00 54 01 44 00 00 00 03 00 00 00 00",
                 "PR FREQ", 67.0, "300 Hz"),
                ("81 04 01 44 00 64 01 44 00 0d 00 0b 00 00 00 00",
                 "PAGER", 103.5, "1100 Hz"),
                ("81 04 01 44 00 64 01 44 00 0d 00 1e 00 00 00 00",
                 "PAGER", 103.5, "3000 Hz")):
            record = bytes.fromhex(raw)
            self._mem.set_raw(record)
            mem = self.radio.get_memory(1)
            self.assertEqual(override, self._override(mem))
            self.assertEqual(rtone, mem.rtone)
            self.assertEqual(pr_freq, str(mem.extra["pr_freq"].value))
            self.radio.set_memory(mem)
            self.assertEqual(record, self._mem.get_raw())

    def test_pr_freq_write(self):
        mem = self.radio.get_memory(1)
        self.assertEqual("1500 Hz", str(mem.extra["pr_freq"].value))
        mem.extra["pr_freq"].value = "3000 Hz"
        self.radio.set_memory(mem)
        self.assertEqual(30, int(self._mem.pr_freq))

    def test_pager_codes(self):
        values = _setting_map(self.radio.get_settings())
        self.assertEqual(
            ["05", "47", "05", "47"],
            [values[n] for n in ("pager_rx0", "pager_rx1",
                                 "pager_tx0", "pager_tx1")])
        # RX 40/01 and TX 01/15, as ADMS-17 wrote them
        new = {"pager_rx0": "40", "pager_rx1": "01",
               "pager_tx0": "01", "pager_tx1": "15"}
        settings = self.radio.get_settings()
        for setting in _iter_settings(settings):
            if setting.get_name() in new:
                setting.value = new[setting.get_name()]
        self.radio.set_settings(settings)
        self.assertEqual(bytes.fromhex("27 00 00 0e"),
                         self.radio.get_mmap().get_packed()[0x2D2:0x2D6])

    def test_pr_freq_out_of_range_untouched(self):
        self._mem.pr_freq = 0
        mem = self.radio.get_memory(1)
        self.assertNotIn("pr_freq", [s.get_name() for s in mem.extra])
        self.radio.set_memory(mem)
        self.assertEqual(0, int(self._mem.pr_freq))


class TestFTM150PMG(unittest.TestCase):
    # Slot records as the radio wrote them; FREQ is a VFO frequency
    # (145.6125 MHz, -600 kHz) stored in the slot itself.
    FREQ = bytes.fromhex("81 02 41 45 61 04 00 00 00 8c 00 8f 00 0c 00 00")

    def setUp(self):
        img = os.path.join(os.path.dirname(__file__),
                           '..', 'images', 'Yaesu_FTM-150E.img')
        self.radio = ftm150.FTM150Radio(img)
        pmg = self.radio._memobj.pmg
        pmg[0].set_raw(ftm150._pmg_ref(10, 3))
        pmg[1].set_raw(ftm150._pmg_ref(1, 1))
        pmg[2].set_raw(self.FREQ)
        pmg[3].set_raw(ftm150._pmg_ref(999, 1))
        pmg[4].set_raw(b"\x00" + b"\xff" * 15)
        self.radio._memobj.pmg_selected = 3

    def _raw(self):
        return [rec.get_raw() for rec in self.radio._memobj.pmg]

    def _set(self, new):
        settings = self.radio.get_settings()
        for setting in _iter_settings(settings):
            if setting.get_name() in new:
                setting.value = new[setting.get_name()]
        self.radio.set_settings(settings)

    def test_ref_format(self):
        # Channel 300 as the radio stored it
        self.assertEqual(bytes.fromhex("91 ff 01 2b") + b"\xff" * 12,
                         ftm150._pmg_ref(300, 1))
        self.assertEqual(300, ftm150._pmg_channel(ftm150._pmg_ref(300, 1)))
        self.assertIsNone(ftm150._pmg_channel(self.FREQ))
        self.assertIsNone(ftm150._pmg_channel(
            bytes.fromhex("00 ff 01 2b") + b"\xff" * 12))

    def test_read(self):
        values = _setting_map(self.radio.get_settings())
        self.assertTrue(values["pmg0"].startswith("10"))
        self.assertTrue(values["pmg1"].startswith("1"))
        self.assertEqual("Frequency 145.612500 MHz", values["pmg2"])
        self.assertTrue(values["pmg3"].startswith("999"))
        self.assertEqual("(Empty)", values["pmg4"])
        self.assertEqual("Slot 4", values["pmg_selected"])

    def test_unchanged_roundtrip(self):
        before = self.radio.get_mmap().get_packed()
        self._set({})
        self.assertEqual(before, self.radio.get_mmap().get_packed())

    def test_empty_slot_moves_later_slots_up(self):
        old = self._raw()
        self._set({"pmg1": "(Empty)"})
        # Like the radio: later slots move up, the last one only loses
        # its used bit.
        self.assertEqual(old[0], self._raw()[0])
        self.assertEqual([self.FREQ, old[3]], self._raw()[1:3])
        self.assertEqual(b"\x00" + old[3][1:], self._raw()[3])
        self.assertEqual(old[4], self._raw()[4])
        # The selected channel 999 moved from slot 4 to slot 3.
        self.assertEqual(2, int(self.radio._memobj.pmg_selected))

    def test_selected_falls_back_to_slot_1(self):
        self._set({"pmg3": "(Empty)"})
        self.assertEqual(0, int(self.radio._memobj.pmg_selected))

    def test_new_ref_uses_channel_band(self):
        label = self.radio._channel_label(14)
        self._set({"pmg4": label})
        self.assertEqual(ftm150._pmg_ref(14, 3), self._raw()[4])
