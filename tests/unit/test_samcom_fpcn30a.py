import unittest
from unittest import mock

from chirp import chirp_common
from chirp import errors
from chirp import memmap
from chirp.drivers import samcom_fpcn30a as sf

# Exact packets extracted from the vendor tool's static data
# (PttWRP.CreateWritePara_Cmd and the ACK/RESEND/COMPLETE commands).
VENDOR_WRITE_PARA = bytes.fromhex(
    "35 02 02 01 00 6a 29 5a 4e 4e 30 31 31 30 30 30 30 30 30 53 43 46 46"
    "46 46 46 46 46 46 01 3c 00 31 32 33 34 35 36 14 03 00 00 00 00 00 00"
    "00 00 10")
SETTINGS_PAYLOAD = VENDOR_WRITE_PARA[7:7 + 41]


def channel_reply(number, rx_bcd, tx_bcd, rxtone, txtone, band):
    """A channel frame as the vendor tool expects to read it."""
    payload = bytearray(27)
    payload[0] = number
    payload[2:6] = rx_bcd
    payload[6:10] = tx_bcd
    payload[13] = rxtone
    payload[14] = txtone
    payload[15] = band
    return sf.make_frame(0x01, 0x03, 0, bytes(payload))


class FakeRadio:
    """Serial pipe emulating the radio side of the vendor protocol."""

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
            self.outbox += sf.make_frame(0x01, 0x02, 0x0100,
                                         SETTINGS_PAYLOAD)
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
    image[8:8 + 41] = SETTINGS_PAYLOAD
    radio._mmap = memmap.MemoryMapBytes(bytes(image))
    radio.process_mmap()
    radio.pipe = pipe
    return radio


@mock.patch.object(sf, "TIMEOUT_READ", 0.05)
@mock.patch.object(sf, "TIMEOUT_WRITE", 0.05)
class TestSamcomFreqTool(unittest.TestCase):
    def test_vendor_packets_pass_frame_check(self):
        self.assertTrue(sf.check_frame(sf.CMD_READ_LOCAL_INFO))
        self.assertTrue(sf.check_frame(VENDOR_WRITE_PARA))
        self.assertEqual(sf.CTRL_ACK, bytes.fromhex("360610"))
        self.assertEqual(sf.CTRL_REPEAT, bytes.fromhex("360510"))
        self.assertEqual(sf.CTRL_COMPLETE, bytes.fromhex("360710"))

    def test_frame_check_rejects_bad_checksum(self):
        bad = bytearray(VENDOR_WRITE_PARA)
        bad[5] ^= 0xFF
        self.assertFalse(sf.check_frame(bytes(bad)))

    def test_download(self):
        pipe = FakeRadio([
            channel_reply(1, bytes.fromhex("43812500"),
                          bytes.fromhex("43812500"), 0, 0, 0),
            channel_reply(3, bytes.fromhex("44600625"),
                          bytes.fromhex("44110625"), 9, 51, 1),
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

    def test_upload_matches_vendor_layout(self):
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

        settings_frame, channel_frame, complete = pipe.written
        self.assertTrue(sf.check_frame(settings_frame))
        self.assertEqual(bytes.fromhex("3502020001"), settings_frame[:5])
        self.assertEqual(41, settings_frame[6])
        self.assertEqual(b"0" * 22, settings_frame[7:29])   # vendor zeros
        self.assertEqual(SETTINGS_PAYLOAD[22:37], settings_frame[29:44])
        self.assertEqual(b"\x00" * 4, settings_frame[44:48])

        self.assertTrue(sf.check_frame(channel_frame))
        self.assertEqual(35, len(channel_frame))
        self.assertEqual(bytes.fromhex("3502030002"), channel_frame[:5])
        self.assertEqual(27, channel_frame[6])
        self.assertEqual(2, channel_frame[7])                # channel 2
        # Vendor write order: TX in 9-12, RX in 13-16
        self.assertEqual(bytes.fromhex("44110625"), channel_frame[9:13])
        self.assertEqual(bytes.fromhex("44600625"), channel_frame[13:17])
        self.assertEqual(1, channel_frame[19])               # band
        self.assertEqual(13, channel_frame[20])              # 100.0 Hz
        self.assertEqual(13, channel_frame[21])
        self.assertEqual(1, channel_frame[22])               # band
        self.assertEqual(sf.TERMINATOR, channel_frame[34])

        self.assertEqual(sf.CTRL_COMPLETE, complete)

    def test_upload_without_radio_fails(self):
        radio = make_radio(mock.Mock(read=lambda n: b"", write=lambda d: 0))
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

    def test_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()
        values = {s.get_name(): str(s.value)
                  for group in settings for s in group}
        self.assertEqual("ZNN011", values["model"])
        self.assertEqual("SCFFFFFFFF", values["serial"])
        self.assertEqual("406.1-470 MHz", values["freq_range"])
        self.assertEqual("60s", values["tot"])
        self.assertEqual("123456", values["userid"])
        self.assertEqual("3", values["squelch"])
        self.assertEqual("20", values["group"])

        for group in settings:
            for setting in group:
                if setting.get_name() == "tot":
                    setting.value = "120s"
                elif setting.get_name() == "squelch":
                    setting.value = "5"
        radio.set_settings(settings)
        self.assertEqual(120, int(radio._memobj.settings.tot))
        self.assertEqual(5, int(radio._memobj.settings.squelch))
