import time
import unittest
from unittest import mock

from chirp import chirp_common
from chirp import errors
from chirp import memmap
from chirp.drivers import samcom_fpcn30a as sf

# Exact packet extracted from the vendor tool's static data
# (PttWRP.CreateWritePara_Cmd); used here to check the checksum rule.
VENDOR_WRITE_PARA = bytes.fromhex(
    "35 02 02 01 00 6a 29 5a 4e 4e 30 31 31 30 30 30 30 30 30 53 43 46 46"
    "46 46 46 46 46 46 01 3c 00 31 32 33 34 35 36 14 03 00 00 00 00 00 00"
    "00 00 10")

# Settings block reported by a real FPCN30A (model ZW_U5W).
FPCN30A_SETTINGS = bytes.fromhex(
    "5a575f553557 303030303030 53430000000000000000"
    "ff ff 00 ffffffffffff 14 03 ff ff ff ff ffffffff".replace(" ", ""))

# Settings block of the same radio after its settings were blanked.
FPCN30A_BLANKED = bytes.fromhex(
    "5a575f553557 303030303030 5343ffffffffffffffff"
    "ff ff 00 ffffffffffff 01 03 ff ff ff ff ffffffff".replace(" ", ""))

# The session settings frame that, sent to that blanked radio, made it
# accept a TX frequency change (and changed none of its settings).
TESTED_SESSION_FRAME = bytes.fromhex(
    "35 02 02 00 01 d5 29 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30"
    "30 30 30 30 30 30 01 3c 00 00 00 00 00 00 00 01 03 00 00 00 01 00 00"
    "00 00 10")

# Channel 9 payload exactly as a real FPCN30A reported it: RX 462.625,
# TX 467.625, tone index 13 both ways, 12.5K, power/companding/scrambler
# 01/00/00.
FPCN30A_CH9 = bytes.fromhex(
    "09 00 46262500 46762500 0000 01 0d 0d 01 01 00 00"
    "0000000000000000".replace(" ", ""))


def channel_reply(payload):
    """A channel frame as the radio sends it."""
    return sf.make_frame(0x01, 0x03, 0x0001, payload)


def channel_payload(number, rx_bcd, tx_bcd, rxtone, txtone, band,
                    extras=(1, 0, 0)):
    payload = bytearray(27)
    payload[0] = number
    payload[2:6] = rx_bcd
    payload[6:10] = tx_bcd
    payload[12] = band
    payload[13] = rxtone
    payload[14] = txtone
    payload[15] = band
    payload[16:19] = bytes(extras)
    return bytes(payload)


class FakeRadio:
    """Serial pipe emulating the radio side of the protocol."""

    def __init__(self, channels=(), repeat_first=False):
        self.channels = list(channels)
        self.repeat_first = repeat_first
        self.written = []
        self.outbox = b""

    def write(self, data):
        self.written.append(bytes(data))
        if self.repeat_first:
            self.repeat_first = False
            self.outbox += sf.CTRL_REPEAT
            return
        if data == sf.CMD_READ_LOCAL_INFO:
            self.outbox += sf.make_frame(0x01, 0x02, 0x0000,
                                         FPCN30A_SETTINGS)
        elif data == sf.CTRL_ACK:
            self.outbox += (self.channels.pop(0) if self.channels
                            else sf.CTRL_COMPLETE)
        elif data[0] == sf.START_DATA:
            self.outbox += sf.CTRL_ACK
        elif data == sf.CTRL_COMPLETE:
            self.outbox += sf.CTRL_ACK

    def read(self, size):
        data, self.outbox = self.outbox[:size], self.outbox[size:]
        return data


def make_radio(pipe=None):
    radio = sf.SamcomFPCN30A(None)
    image = bytearray(sf.MEMSIZE)
    image[0:8] = sf.MAGIC
    image[8:8 + 41] = FPCN30A_SETTINGS
    radio._mmap = memmap.MemoryMapBytes(bytes(image))
    radio.process_mmap()
    radio.pipe = pipe
    return radio


def write_frames(pipe):
    """Frames written by an upload, which must not read the radio."""
    frames = list(pipe.written)
    assert sf.CMD_READ_LOCAL_INFO not in frames
    return frames


class FakeClock:
    """Stands in for the driver's time module."""

    def __init__(self, now=1000.0):
        self.now = now
        self.slept = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.slept += seconds

    # Frame timeouts use wall-clock time
    time = staticmethod(time.time)


def settings_values(radio):
    return {s.get_name(): str(s.value)
            for group in radio.get_settings() for s in group}


@mock.patch.object(sf, "TIMEOUT_READ", 0.05)
@mock.patch.object(sf, "TIMEOUT_WRITE", 0.05)
@mock.patch.object(sf, "READ_SETTLE_TIME", 0)
class TestSamcomFPCN30A(unittest.TestCase):
    def setUp(self):
        self._last_read = sf._last_read
        sf._last_read = None

    def tearDown(self):
        sf._last_read = self._last_read

    def test_vendor_packets_pass_frame_check(self):
        self.assertTrue(sf.check_frame(sf.CMD_READ_LOCAL_INFO))
        self.assertTrue(sf.check_frame(VENDOR_WRITE_PARA))
        self.assertEqual(sf.CTRL_ACK, bytes.fromhex("360610"))
        self.assertEqual(sf.CTRL_REPEAT, bytes.fromhex("360510"))
        self.assertEqual(sf.CTRL_COMPLETE, bytes.fromhex("360710"))

    def test_port_opened_with_dtr_and_rts_off(self):
        # CHIRP applies these before opening the port
        self.assertFalse(sf.SamcomFPCN30A.WANTS_DTR)
        self.assertFalse(sf.SamcomFPCN30A.WANTS_RTS)

    def test_frame_check_rejects_bad_checksum(self):
        bad = bytearray(VENDOR_WRITE_PARA)
        bad[5] ^= 0xFF
        self.assertFalse(sf.check_frame(bytes(bad)))

    def test_download(self):
        pipe = FakeRadio([
            channel_reply(channel_payload(1, bytes.fromhex("43812500"),
                                          bytes.fromhex("43812500"),
                                          0, 0, 0)),
            channel_reply(channel_payload(3, bytes.fromhex("44600625"),
                                          bytes.fromhex("44110625"),
                                          9, 51, 1)),
        ])
        radio = make_radio(pipe)
        radio.sync_in()

        mem = radio.get_memory(1)
        self.assertEqual(438125000, mem.freq)
        self.assertEqual("", mem.duplex)
        self.assertEqual("", mem.tmode)
        self.assertEqual("FM", mem.mode)

        self.assertTrue(radio.get_memory(2).empty)

        mem = radio.get_memory(3)
        self.assertEqual(446006250, mem.freq)
        self.assertEqual("-", mem.duplex)
        self.assertEqual(4900000, mem.offset)
        self.assertEqual("NFM", mem.mode)
        self.assertEqual("Cross", mem.tmode)
        self.assertEqual("DTCS->Tone", mem.cross_mode)
        self.assertEqual(88.5, mem.ctone)          # index 9
        self.assertEqual(23, mem.dtcs)             # index 51 = D023N

        self.assertEqual(sf.CMD_READ_LOCAL_INFO, pipe.written[0])
        self.assertEqual([sf.CTRL_ACK] * 3, pipe.written[1:])

    def test_download_resends_on_repeat(self):
        pipe = FakeRadio(repeat_first=True)
        radio = make_radio(pipe)
        radio.sync_in()
        self.assertEqual([sf.CMD_READ_LOCAL_INFO] * 2, pipe.written[:2])

    def test_download_without_radio_fails(self):
        radio = make_radio(mock.Mock(read=lambda n: b"", write=lambda d: 0))
        with self.assertRaises(errors.RadioError):
            radio.sync_in()

    def test_real_channel_round_trips_byte_for_byte(self):
        # A split channel read from a real radio must be written back with
        # the identical payload (RX first, per-channel extras preserved).
        radio = make_radio(FakeRadio([channel_reply(FPCN30A_CH9)]))
        radio.sync_in()
        mem = radio.get_memory(9)
        self.assertEqual(462625000, mem.freq)
        self.assertEqual("+", mem.duplex)
        self.assertEqual(5000000, mem.offset)

        pipe = FakeRadio()
        radio.pipe = pipe
        radio.sync_out()
        _settings, channel_frame, complete = write_frames(pipe)
        self.assertTrue(sf.check_frame(channel_frame))
        self.assertEqual(bytes.fromhex("3502030002"), channel_frame[:5])
        self.assertEqual(FPCN30A_CH9, channel_frame[7:7 + 27])
        self.assertEqual(sf.CTRL_COMPLETE, complete)

    def test_upload_session_order(self):
        pipe = FakeRadio()
        radio = make_radio(pipe)
        for number in (2, 5):
            mem = chirp_common.Memory(number)
            mem.freq = 446006250
            radio.set_memory(mem)
        radio.sync_out()

        frames = write_frames(pipe)
        self.assertEqual(4, len(frames))
        self.assertEqual(bytes.fromhex("3502020001"), frames[0][:5])
        self.assertTrue(all(f[2] == 0x03 for f in frames[1:3]))  # channels
        self.assertEqual([2, 5], [f[7] for f in frames[1:3]])
        self.assertEqual([2, 3], [f[4] for f in frames[1:3]])    # sequence
        self.assertEqual(sf.CTRL_COMPLETE, frames[3])

    def test_upload_does_not_read_radio(self):
        # Shortly after a read the radio ignores tone changes, so an upload
        # must open with the session frame, built from the loaded image.
        pipe = FakeRadio()
        radio = make_radio(pipe)
        mem = chirp_common.Memory(1)
        mem.freq = 446006250
        radio.set_memory(mem)
        radio.sync_out()
        self.assertEqual(sf.session_settings_frame(
            radio._memobj.settings.get_raw()), write_frames(pipe)[0])

    def test_download_records_read_time(self):
        clock = FakeClock(now=500.0)
        with mock.patch.object(sf, "time", clock):
            make_radio(FakeRadio()).sync_in()
        self.assertEqual(500.0, sf._last_read)

    def test_upload_waits_after_recent_read(self):
        clock = FakeClock(now=1000.0)
        sf._last_read = 995.0                      # read 5 s ago
        pipe = FakeRadio()
        radio = make_radio(pipe)
        with mock.patch.object(sf, "READ_SETTLE_TIME", 30), \
                mock.patch.object(sf, "time", clock):
            radio.sync_out()
        self.assertAlmostEqual(25.0, clock.slept)
        self.assertTrue(pipe.written)

    def test_upload_does_not_wait_after_old_read(self):
        clock = FakeClock(now=1000.0)
        sf._last_read = 900.0                      # read 100 s ago
        with mock.patch.object(sf, "READ_SETTLE_TIME", 30), \
                mock.patch.object(sf, "time", clock):
            make_radio(FakeRadio()).sync_out()
        self.assertEqual(0.0, clock.slept)

    def test_session_frame_matches_frame_tested_on_radio(self):
        self.assertEqual(TESTED_SESSION_FRAME,
                         sf.session_settings_frame(FPCN30A_BLANKED))

    def test_session_frame_never_contains_ff(self):
        for settings in (FPCN30A_SETTINGS, FPCN30A_BLANKED, b"\xff" * 41):
            frame = sf.session_settings_frame(settings)
            self.assertTrue(sf.check_frame(frame))
            self.assertNotIn(0xFF, frame[7:48])
            self.assertEqual(b"0" * 22, frame[7:29])

    def test_session_frame_keeps_valid_radio_values(self):
        payload = sf.session_settings_frame(FPCN30A_SETTINGS)[7:48]
        self.assertEqual(0, payload[24])           # VOX
        self.assertEqual(20, payload[31])          # group channel
        self.assertEqual(3, payload[32])           # squelch
        self.assertEqual((1, 60, 0), (payload[22], payload[23],
                                      payload[33]))  # vendor defaults

    def test_upload_layout_rx_first(self):
        pipe = FakeRadio()
        radio = make_radio(pipe)
        mem = chirp_common.Memory(2)
        mem.freq = 446006250
        mem.duplex = "-"
        mem.offset = 4900000
        mem.tmode = "TSQL"
        mem.ctone = 100.0
        mem.mode = "NFM"
        radio.set_memory(mem)
        radio.sync_out()

        channel_frame = write_frames(pipe)[1]
        self.assertTrue(sf.check_frame(channel_frame))
        self.assertEqual(35, len(channel_frame))
        self.assertEqual(27, channel_frame[6])
        self.assertEqual(2, channel_frame[7])                # channel 2
        self.assertEqual(bytes.fromhex("44600625"), channel_frame[9:13])
        self.assertEqual(bytes.fromhex("44110625"), channel_frame[13:17])
        self.assertEqual(1, channel_frame[19])               # band
        self.assertEqual(13, channel_frame[20])              # 100.0 Hz
        self.assertEqual(13, channel_frame[21])
        self.assertEqual(1, channel_frame[22])               # band
        # New channel gets the per-channel values real radios report
        self.assertEqual(bytes([1, 0, 0]), channel_frame[23:26])
        self.assertEqual(sf.TERMINATOR, channel_frame[34])

    def test_editing_keeps_per_channel_extras(self):
        radio = make_radio(FakeRadio([channel_reply(channel_payload(
            4, bytes.fromhex("46256250"), bytes.fromhex("46256250"),
            0, 0, 1, extras=(2, 1, 1)))]))
        radio.sync_in()
        mem = radio.get_memory(4)
        mem.freq = 462587500
        radio.set_memory(mem)
        chan = radio._memobj.channels[3]
        self.assertEqual((2, 1, 1), (int(chan.power), int(chan.companding),
                                     int(chan.scrambler)))

    def test_upload_without_radio_fails(self):
        radio = make_radio(mock.Mock(read=lambda n: b"", write=lambda d: 0))
        mem = chirp_common.Memory(1)
        mem.freq = 446006250
        radio.set_memory(mem)
        with self.assertRaises(errors.RadioError):
            radio.sync_out()

    def test_exact_bcd_frequency(self):
        # The vendor tool truncates floats; the driver must not lose 10 Hz.
        radio = make_radio()
        mem = chirp_common.Memory(1)
        mem.freq = 438125000
        radio.set_memory(mem)
        self.assertEqual(bytes.fromhex("43812500"),
                         bytes(radio._memobj.channels[0].rxfreq.get_raw()))

    def test_settings_are_read_only(self):
        radio = make_radio()
        values = settings_values(radio)
        self.assertEqual("ZW_U5W", values["model"])
        self.assertEqual("SC", values["serial"])
        self.assertEqual("Not set (0xFF)", values["freq_range"])
        self.assertEqual("Not set (0xFF)", values["tot"])
        self.assertEqual("Off", values["vox"])
        self.assertEqual("3", values["squelch"])
        self.assertEqual("CH20", values["group"])
        self.assertEqual("Not set (0xFF)", values["userid"])
        self.assertEqual("Not set (0xFF)", values["power_mode"])

        settings = radio.get_settings()
        for group in settings:
            for setting in group:
                self.assertFalse(setting.value.get_mutable())
        before = bytes(radio._memobj.settings.get_raw())
        radio.set_settings(settings)
        self.assertEqual(before, bytes(radio._memobj.settings.get_raw()))
