# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os
import unittest
from unittest import mock

from chirp import chirp_common, directory, errors, memmap
from chirp.drivers import leixen, v8plus

IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "Weierwei_VEV-V8_Plus.img")

# (tone, index stored in the record), taken from the channel data of the
# reference radio: the vendor software's own file lists the tone as text and
# the index it stored next to it.
CPS_TONE_INDEX = (
    (71.9, 4),
    (77.0, 6),
    (79.7, 7),
    (82.5, 8),
    (88.5, 10),
    (100.0, 14),
    (110.9, 17),
    (118.8, 19),
    (131.8, 22),
)

# The tone list of the vendor software (Items.Strings of its tone control)
CPS_TONES = (
    63.0, 67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
    97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8,
    136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3,
    173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5,
    206.5, 210.7, 218.1, 225.7, 229.1,
)

_gettext = None


def setUpModule():
    # chirp_common leans on the gettext builtin that only the GUI installs
    global _gettext
    _gettext = mock.patch("builtins._", lambda text: text, create=True)
    _gettext.start()


def tearDownModule():
    _gettext.stop()


class FakeSerial:
    """Just enough of a serial port for the handshake to run."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.written = []
        self.timeout = None
        self.resets = 0

    def reset_input_buffer(self):
        self.resets += 1

    def write(self, data):
        assert isinstance(data, bytes), data
        self.written.append(data)

    def read(self, size=None):
        if not self.replies:
            return b""
        return self.replies.pop(0)[:size]


def ident_reply():
    frame = b"\x06" + bytes([len(v8plus.IDENT)]) + v8plus.IDENT
    checksum = 0
    for byte in frame:
        checksum ^= byte
    return frame + bytes([checksum])


class TestVEVV8Plus(unittest.TestCase):
    def setUp(self):
        klass = directory.get_radio("Weierwei_VEV-V8_Plus")
        self.radio = klass(IMAGE)
        self.radio.load(IMAGE)

    def record(self, number):
        return self.radio._memobj.memory[number - 1]

    def power(self, level):
        return self.radio.get_features().valid_power_levels[level]

    def make_memory(self, number, freq, power=1, mode="FM", tmode="",
                    duplex="", offset=0):
        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = freq
        mem.duplex = duplex
        mem.offset = offset
        mem.power = self.power(power)
        mem.mode = mode
        mem.tmode = tmode
        return mem

    def test_handshake_frame(self):
        frame = v8plus.WAKE_PAYLOAD
        self.assertEqual(b"\x46\x4c\x74\x06\x45\x04", frame)
        packet = b"\x02" + bytes([len(frame)]) + frame
        checksum = 0
        for byte in packet:
            checksum ^= byte
        self.assertEqual(0x3D, checksum)
        # the reply the radio gives is the ident string, same framing
        self.assertEqual(b"\x06\x06" + v8plus.IDENT + b"\x3e", ident_reply())

    def test_frames_match_the_leixen_protocol(self):
        # read and write frames are the ones the clone protocol defines
        self.assertEqual(b"\x52\x03\x03\x10\x10\x52",
                         leixen.make_frame(b"R", 0x0310, b"\x10"))
        self.assertEqual(b"\x57\x12\x03\x10" + b"\x00" * 16 + b"\x56",
                         leixen.make_frame(b"W", 0x0310, b"\x00" * 16))

    def test_transport_is_shared_with_the_leixen_driver(self):
        """The clone layer is not reimplemented here, nor overridden."""
        self.assertFalse(issubclass(v8plus.VEVV8PlusRadio,
                                    leixen.LeixenVV898Radio))
        for name in ("make_frame", "send", "recv", "do_ident", "do_download",
                     "do_upload", "finish"):
            self.assertFalse(hasattr(v8plus, name), name)
        self.assertNotEqual(leixen.LeixenVV898Radio._wake_payload,
                            v8plus.WAKE_PAYLOAD)
        self.assertNotEqual(leixen.LeixenVV898Radio._ident, v8plus.IDENT)
        self.assertEqual(0x2000, v8plus.VEVV8PlusRadio._memsize)
        self.assertEqual([(0x0000, 0x2000)],
                         v8plus.VEVV8PlusRadio._upload_ranges)

    def test_detection_is_not_automatic(self):
        # leixen's detector reads an image ident this radio does not have
        with self.assertRaises(NotImplementedError):
            v8plus.VEVV8PlusRadio.detect_from_serial(object())

    def test_handshake_sets_the_timeout_and_retries(self):
        sleeps = []
        pipe = FakeSerial([b"\x00" * 9,        # a frame that is not an ident
                           ident_reply(),
                           b"\x06\x00\x06"])
        radio = v8plus.VEVV8PlusRadio(None)
        radio.pipe = pipe
        with mock.patch.object(v8plus.time, "sleep", sleeps.append):
            radio._handshake()

        self.assertEqual(v8plus.VEVV8PlusRadio.IDENT_TIMEOUT,
                         pipe.timeout)
        # one retry delay, and nothing else
        self.assertEqual([v8plus.VEVV8PlusRadio.IDENT_RETRY_DELAY], sleeps)
        # two handshake frames, and the input is cleared once for the retry
        self.assertEqual(2, len([w for w in pipe.written if w[0] == 0x02]))
        self.assertEqual(1, pipe.resets)
        self.assertEqual(b"\x06\x00\x06", pipe.written[-1])

    def test_handshake_gives_up(self):
        radio = v8plus.VEVV8PlusRadio(None)
        radio.pipe = FakeSerial([])
        with mock.patch.object(v8plus.time, "sleep", lambda seconds: None):
            with self.assertRaises(errors.RadioError):
                radio._handshake()

    def test_sync_in_uses_the_leixen_downloader(self):
        class FakeRadio(v8plus.VEVV8PlusRadio):
            def _handshake(self):
                pass

        payload = bytes(0x2000)
        calls = []

        def fake_download(radio):
            calls.append(radio)
            return memmap.MemoryMapBytes(payload)

        radio = FakeRadio(None)
        with mock.patch.object(leixen, "do_download", fake_download):
            radio.sync_in()
        self.assertEqual([radio], calls)
        self.assertIsNotNone(radio._memobj)

    def test_frequency_encoding(self):
        self.assertEqual(b"\x43\x55\x87\x08",
                         v8plus._encode_freq(435587500))
        self.assertEqual(b"\x43\x85\x00\x00",
                         v8plus._encode_freq(438500000))
        self.assertEqual(b"\x43\x81\x25\x00",
                         v8plus._encode_freq(438125000))
        self.assertEqual(435587500,
                         v8plus._decode_freq(b"\x43\x55\x87\x08"))
        self.assertEqual(438500000,
                         v8plus._decode_freq(b"\x43\x85\x00\x00"))
        # every frequency in the image must survive a round trip
        for hz in (400000000, 430512500, 446006000, 469993500):
            self.assertEqual(hz,
                             v8plus._decode_freq(v8plus._encode_freq(hz)))

    def test_bcd_helpers(self):
        self.assertEqual(b"\x43\x55\x87", v8plus._int_to_bcd(435587, 3))
        self.assertEqual(435587, v8plus._bcd_to_int(b"\x43\x55\x87"))
        self.assertIsNone(v8plus._bcd_to_int(b"\xff\xff\xff"))

    def test_tone_table_is_the_vendor_software_list(self):
        self.assertEqual(CPS_TONES, v8plus.TONES)
        self.assertEqual(47, len(v8plus.TONES))
        # the list starts at 63.0 and stops at 229.1
        self.assertEqual(63.0, v8plus.TONES[0])
        self.assertEqual(229.1, v8plus.TONES[-1])
        for tone in (233.6, 241.8, 250.3, 254.1):
            self.assertNotIn(tone, v8plus.TONES)

    def test_stored_tone_index_is_the_list_position_plus_one(self):
        for tone, index in CPS_TONE_INDEX:
            self.assertEqual(index, v8plus.TONES.index(tone) + 1, tone)
            self.assertEqual(
                tone,
                self.radio._decode_tone(index, v8plus.TX_TONE_FLAG,
                                        v8plus.TX_TONE_FLAG))
        # 63.0 is the first entry of the list, so it is stored as 1
        self.assertEqual(1, v8plus.TONES.index(63.0) + 1)

    def test_no_tone_is_stored_as_ff(self):
        # 0xff is what the radio itself writes into an unused tone slot, and
        # the vendor software writes 0; both mean "no tone", and the flag
        # byte agrees
        self.assertIsNone(
            self.radio._decode_tone(v8plus.NO_TONE, v8plus.TX_TONE_FLAG,
                                    v8plus.TX_TONE_FLAG))
        self.assertIsNone(
            self.radio._decode_tone(0, v8plus.TX_TONE_FLAG,
                                    v8plus.TX_TONE_FLAG))
        self.assertIsNone(
            self.radio._decode_tone(10, 0x00, v8plus.TX_TONE_FLAG))
        self.assertIsNone(
            self.radio._decode_tone(200, v8plus.TX_TONE_FLAG,
                                    v8plus.TX_TONE_FLAG))

    def test_valid_tones_are_only_the_supported_ones(self):
        self.assertEqual(v8plus.TONES, self.radio.get_features().valid_tones)

    def test_get_memory(self):
        mem = self.radio.get_memory(1)
        self.assertEqual(435587500, mem.freq)
        self.assertEqual("", mem.duplex)
        self.assertEqual("High", str(mem.power))
        self.assertEqual("FM", mem.mode)

        mem = self.radio.get_memory(3)
        self.assertEqual(439587500, mem.freq)
        self.assertEqual("-", mem.duplex)
        self.assertEqual(8000000, mem.offset)
        self.assertEqual("TSQL", mem.tmode)
        self.assertEqual(88.5, mem.ctone)

        mem = self.radio.get_memory(6)
        self.assertEqual("Tone", mem.tmode)
        self.assertEqual(88.5, mem.rtone)

        self.assertTrue(self.radio.get_memory(199).empty)

    def test_get_memory_all_in_band(self):
        for number in range(1,
                            self.radio.get_features().memory_bounds[1] + 1):
            mem = self.radio.get_memory(number)
            if mem.empty:
                continue
            self.assertTrue(400000000 <= mem.freq <= 470000000, number)
            self.assertIn(mem.mode, ("FM", "NFM"))
            self.assertIn(str(mem.power), ("High", "Low"))

    def test_set_memory_new_channel(self):
        mem = self.make_memory(150, 435000000, power=1, mode="NFM",
                               tmode="Tone", duplex="+", offset=5000000)
        mem.rtone = 88.5
        self.radio.set_memory(mem)

        raw = self.record(150)
        self.assertEqual(b"\x43\x50\x00\x00", raw.rx_freq.get_raw())
        self.assertEqual(b"\x44\x00\x00\x00", raw.tx_freq.get_raw())
        self.assertEqual(10, raw.tx_tone)
        self.assertEqual(v8plus.TX_TONE_FLAG, raw.tx_tone_flag)
        self.assertEqual(v8plus.NO_TONE, raw.rx_tone)
        self.assertEqual(0x00, raw.rx_tone_flag)
        self.assertFalse(raw.highpower)
        self.assertFalse(raw.wide)

        reread = self.radio.get_memory(150)
        self.assertEqual(435000000, reread.freq)
        self.assertEqual(5000000, reread.offset)
        self.assertEqual("Low", str(reread.power))
        self.assertEqual("NFM", reread.mode)
        self.assertEqual("Tone", reread.tmode)
        self.assertEqual(88.5, reread.rtone)

    def test_set_memory_cross_and_half_khz(self):
        mem = self.make_memory(151, 439512500, power=0, mode="FM",
                               tmode="Cross")
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 100.0
        mem.ctone = 77.0
        self.radio.set_memory(mem)

        raw = self.record(151)
        self.assertEqual(b"\x43\x95\x12\x08", raw.rx_freq.get_raw())
        self.assertEqual(14, raw.tx_tone)
        self.assertEqual(6, raw.rx_tone)
        self.assertEqual(v8plus.TX_TONE_FLAG, raw.tx_tone_flag)
        self.assertEqual(v8plus.RX_TONE_FLAG, raw.rx_tone_flag)

        reread = self.radio.get_memory(151)
        self.assertEqual(439512500, reread.freq)
        self.assertEqual("Cross", reread.tmode)
        self.assertEqual("Tone->Tone", reread.cross_mode)
        self.assertEqual(100.0, reread.rtone)
        self.assertEqual(77.0, reread.ctone)

    def test_set_memory_low_tone(self):
        # 63.0 Hz is the first entry of the radio's tone list
        mem = self.make_memory(153, 433500000, power=1, mode="FM",
                               tmode="Tone")
        mem.rtone = 63.0
        self.radio.set_memory(mem)

        self.assertEqual(1, self.record(153).tx_tone)
        self.assertEqual(63.0, self.radio.get_memory(153).rtone)

    def test_unsupported_tone_is_not_written(self):
        """A tone outside the table must not be stored as some other tone."""
        mem = self.make_memory(154, 433600000, power=1, mode="FM",
                               tmode="Tone")
        mem.rtone = 250.3                   # not in the radio's list
        self.radio.set_memory(mem)

        raw = self.record(154)
        self.assertEqual(v8plus.NO_TONE, raw.tx_tone)
        self.assertEqual(0x00, raw.tx_tone_flag)
        self.assertEqual("", self.radio.get_memory(154).tmode)

    def test_erase_memory(self):
        mem = self.radio.get_memory(1)
        mem.empty = True
        self.radio.set_memory(mem)
        self.assertEqual(b"\xff" * 16, self.record(1).get_raw())
        self.assertTrue(self.radio.get_memory(1).empty)

    def test_round_trip_byte_identical(self):
        before = self.radio.get_mmap().get_packed()
        for number in range(1, 200):
            self.radio.set_memory(self.radio.get_memory(number))
        self.assertEqual(before, self.radio.get_mmap().get_packed())

    def test_power_and_bandwidth_are_independent(self):
        mem = self.radio.get_memory(1)
        mem.power = self.power(0)
        mem.mode = "NFM"
        self.radio.set_memory(mem)
        raw = self.record(1)
        self.assertTrue(raw.highpower)
        self.assertFalse(raw.wide)

    def test_cross_rx_only_tone(self):
        mem = self.make_memory(152, 433000000, power=0, mode="FM",
                               tmode="Cross")
        mem.cross_mode = "->Tone"
        mem.ctone = 88.5
        self.radio.set_memory(mem)

        raw = self.record(152)
        self.assertEqual(0x00, raw.tx_tone_flag)
        self.assertEqual(v8plus.RX_TONE_FLAG, raw.rx_tone_flag)
        self.assertEqual(10, raw.rx_tone)

        back = self.radio.get_memory(152)
        self.assertEqual("Cross", back.tmode)
        self.assertEqual("->Tone", back.cross_mode)
        self.assertEqual(88.5, back.ctone)

    def test_duplex_off_is_an_erased_transmit_frequency(self):
        mem = self.radio.get_memory(1)
        mem.duplex = "off"
        mem.offset = 0
        self.radio.set_memory(mem)
        self.assertEqual(b"\xff" * 4, self.record(1).tx_freq.get_raw())
        self.assertEqual("off", self.radio.get_memory(1).duplex)
