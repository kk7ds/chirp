# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import unittest
from unittest import mock

from chirp import chirp_common
from chirp.drivers import v6
from tests.unit import base

_gettext = None


def setUpModule():
    # chirp_common leans on the gettext builtin that only the GUI installs
    global _gettext
    _gettext = mock.patch("builtins._", lambda text: text, create=True)
    _gettext.start()


def tearDownModule():
    _gettext.stop()


class TestVEVV6(base.RadioTest):
    VENDOR_MODEL = "Weierwei_VEV-V6"

    def record(self, number):
        page, index = v6._record_index(number)
        return self.radio._memobj.page[page].ch[index]

    def test_image_size(self):
        self.assertEqual(0x800, v6.MEM_SIZE)
        self.assertEqual(8, len(v6.PAGE_ADDRS))
        self.assertEqual(0xA000, v6.PAGE_ADDRS[0])
        self.assertEqual(0xAE00, v6.PAGE_ADDRS[-1])
        self.assertEqual(v6.MEM_SIZE, len(self.radio.get_mmap().get_packed()))

    def test_frequency_encoding(self):
        # 435.5875 has a remainder of 87.5 kHz, which only fits 6.25 kHz steps
        self.assertEqual((4355, 14, 0x0A, 0, 0, False),
                         v6.encode_frequencies(435587500, 435587500))
        # 438.125 fits 5 kHz steps
        self.assertEqual((4381, 5, 0x0A, 0, 0, True),
                         v6.encode_frequencies(438125000, 438125000))
        # 400.000 is all zeroes
        self.assertEqual((4000, 0, 0x0A, 0, 0, True),
                         v6.encode_frequencies(400000000, 400000000))

        self.assertEqual(435587500, v6.decode_frequency(4355, 14, False))
        self.assertEqual(438125000, v6.decode_frequency(4381, 5, True))
        self.assertEqual(430300000, v6.decode_frequency(4303, 0, False))

        for hz in (400000000, 430300000, 435587500, 438125000, 469993750):
            coarse, fine, _c, _f, _dir, step_5k = \
                v6.encode_frequencies(hz, hz)
            self.assertEqual(hz, v6.decode_frequency(coarse, fine, step_5k))

    def test_fine_part_is_five_bits(self):
        # The fine part is a plain five bit value which the radio multiplies
        # by the step, so 16 units are stored as 16 and not carried into the
        # coarse part.
        self.assertEqual((4335, 16, 0x0A, 0, 0, True),
                         v6.encode_frequencies(433580000, 433580000))
        self.assertEqual(433580000,
                         v6.decode_frequency(4335, 16, True))

    def test_offset_encoding(self):
        # 8 MHz down: coarse 80, fine 0, transmit below receive
        self.assertEqual((4395, 14, 80, 0, -1, False),
                         v6.encode_frequencies(439587500, 431587500))
        # 8.1875 MHz down only fits the 6.25 kHz step: 81 + 14 * 6.25 kHz
        self.assertEqual((4397, 0, 81, 14, -1, False),
                         v6.encode_frequencies(439700000, 431512500))
        # 5.0375 MHz up: 50 + 6 * 6.25 kHz
        self.assertEqual((4303, 0, 50, 6, 1, False),
                         v6.encode_frequencies(430300000, 435337500))

        self.assertEqual(431587500,
                         v6.decode_offset(439587500, 80, 0, False, 0, 1))
        self.assertEqual(431512500,
                         v6.decode_offset(439700000, 81, 14, False, 0, 1))
        self.assertEqual(435337500,
                         v6.decode_offset(430300000, 50, 6, False, 1, 0))
        # both direction bits set means the channel has no offset
        self.assertEqual(439587500,
                         v6.decode_offset(439587500, 0x0A, 0, False, 1, 1))

    def test_tone_mapping(self):
        self.assertEqual(88.5, v6.index_to_tone(8))
        self.assertEqual(100.0, v6.index_to_tone(12))
        self.assertEqual(136.5, v6.index_to_tone(21))
        self.assertIsNone(v6.index_to_tone(len(v6.TONE_TABLE)))
        for tone in v6.TONE_TABLE:
            self.assertEqual(tone, v6.index_to_tone(v6.tone_to_index(tone)))
        # 67.0 Hz is index 0, which is only usable because the flags byte
        # says whether a tone is present at all
        self.assertEqual(67.0, v6.index_to_tone(0))

    def test_features(self):
        rf = self.radio.get_features()
        self.assertFalse(rf.has_name)
        self.assertFalse(rf.has_dtcs)
        self.assertEqual([(400000000, 470000000)], rf.valid_bands)
        self.assertEqual((1, 128), rf.memory_bounds)
        self.assertEqual(["FM", "NFM"], rf.valid_modes)
        self.assertEqual(["Tone->Tone", "->Tone"], rf.valid_cross_modes)

    def test_channel_decode(self):
        mem = self.radio.get_memory(1)
        self.assertEqual(435587500, mem.freq)
        self.assertEqual("", mem.duplex)
        self.assertEqual("", mem.tmode)
        self.assertEqual("FM", mem.mode)
        self.assertEqual("High", str(mem.power))

        mem = self.radio.get_memory(3)
        self.assertEqual(439587500, mem.freq)
        self.assertEqual("-", mem.duplex)
        self.assertEqual(8000000, mem.offset)
        self.assertEqual("TSQL", mem.tmode)
        self.assertEqual(88.5, mem.rtone)
        self.assertEqual(88.5, mem.ctone)

        mem = self.radio.get_memory(5)
        self.assertEqual(438125000, mem.freq)
        self.assertEqual("NFM", mem.mode)

        # 438.9375 / -7.45 MHz: the offset fine part is in 6.25 kHz steps
        mem = self.radio.get_memory(48)
        self.assertEqual(438937500, mem.freq)
        self.assertEqual(7450000, mem.offset)
        self.assertEqual("TSQL", mem.tmode)
        self.assertEqual(79.7, mem.rtone)

    def test_bit_layout(self):
        # The memory map should carry these as named fields rather than as
        # magic masks in the driver
        record = self.record(3)
        self.assertEqual(1, int(record.offset_down))
        self.assertEqual(0, int(record.offset_up))
        self.assertEqual(14, int(record.fine))
        self.assertEqual(1, int(record.wide))
        record = self.record(1)
        self.assertEqual(1, int(record.offset_up))
        self.assertEqual(1, int(record.offset_down))
        self.assertEqual(v6.NO_TX_TONE, int(record.no_tx_tone))
        self.assertEqual(0, int(record.rx_tone))

    def test_empty_channel(self):
        self.assertTrue(self.radio.get_memory(101).empty)
        self.radio.set_memory(self.radio.get_memory(101))
        self.assertTrue(self.radio.get_memory(101).empty)

    def test_round_trip_all_channels(self):
        # every record must be reproduced byte for byte when the decoded
        # values are written back
        for number in range(1, v6.CHANNEL_COUNT + 1):
            record = self.record(number)
            before = bytes(record.get_raw())
            self.radio.set_memory(self.radio.get_memory(number))
            self.assertEqual(before, bytes(record.get_raw()),
                             "channel %i changed" % number)

    def test_set_memory_new_channel(self):
        mem = chirp_common.Memory()
        mem.number = 120
        mem.freq = 433500000
        mem.duplex = "-"
        mem.offset = 5000000
        mem.tmode = "TSQL"
        mem.rtone = 88.5
        mem.ctone = 88.5
        mem.mode = "NFM"
        mem.power = v6.POWER_LEVELS[1]
        self.radio.set_memory(mem)

        self.assertEqual(
            bytes([0x10, 0xEF, 0xA0, 0x00, 0x32, 0xA0, 0x08, 0x08,
                   0xFC, 0x69, 0xFF, 0xFF, 0xFF, 0xFF]),
            bytes(self.record(120).get_raw()))

        back = self.radio.get_memory(120)
        self.assertEqual(433500000, back.freq)
        self.assertEqual(5000000, back.offset)
        self.assertEqual("TSQL", back.tmode)
        self.assertEqual(88.5, back.rtone)
        self.assertEqual("NFM", back.mode)
        self.assertEqual("Low", str(back.power))

    def test_tone_67(self):
        mem = chirp_common.Memory()
        mem.number = 121
        mem.freq = 433500000
        mem.tmode = "Tone"
        mem.rtone = 67.0
        mem.power = v6.POWER_LEVELS[0]
        self.radio.set_memory(mem)

        record = self.record(121)
        self.assertEqual(0, int(record.ttone))
        self.assertEqual(0, int(record.no_tx_tone))
        self.assertEqual(67.0, self.radio.get_memory(121).rtone)

    def test_validate_memory(self):
        mem = chirp_common.Memory()
        mem.number = 120
        mem.freq = 433500000
        mem.tmode = "Tone"
        mem.rtone = 88.5
        self.assertEqual([], self.radio.validate_memory(mem))

        # the offset coarse part is a single byte
        mem.duplex = "-"
        mem.offset = 30000000
        msgs = [str(msg) for msg in self.radio.validate_memory(mem)]
        self.assertTrue(any("25.5 MHz" in msg for msg in msgs), msgs)


if __name__ == "__main__":
    unittest.main()
