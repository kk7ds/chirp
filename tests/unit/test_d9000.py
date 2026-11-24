# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os
import unittest
from unittest import mock

from chirp import chirp_common, directory
from chirp.drivers import d9000  # noqa: F401  (registers the driver)


IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "Zastone_ZT-D9000.img")

# 512 records of 32 bytes starting here; channel 91 is the one that holds
# 121.745MHz, the frequency the driver deliberately moves onto a real
# airband channel when it writes.
RECORD_BASE = 0x2000
RECORD_LEN = 32


class TestZT_D9000(unittest.TestCase):
    def setUp(self):
        klass = directory.get_radio("Zastone_ZT-D9000")
        self.radio = klass(IMAGE)
        self.radio.load(IMAGE)

    def test_preserves_unknown_flags(self):
        # [13] carries 0x10 on two channels of the vendor codeplug and [17] is
        # the scan list membership flag (0x01 on the eight channels the vendor
        # puts in a scan list, with [25] = 0x03).  Writing a channel must not
        # clear them: if the radio sees [17] = 0 it drops the channel out of
        # the scan list and clears [25] as well, so the membership is lost.
        _mem = self.radio._memobj.memory[0]
        _mem.unknown13 = 0x10
        _mem.unknown17 = 0x01
        _mem.unknown18[7] = 0x03

        self.radio.set_memory(self.radio.get_memory(1))

        self.assertEqual(0x10, int(_mem.unknown13))
        self.assertEqual(0x01, int(_mem.unknown17))
        self.assertEqual(0x03, int(_mem.unknown18[7]))

    def test_cleared_channel_is_all_zero(self):
        mem = chirp_common.Memory()
        mem.number = 1
        mem.empty = True
        self.radio.set_memory(mem)

        self.assertEqual(b"\x00" * RECORD_LEN, bytes(
            self.radio._memobj.memory[0].get_raw(asbytes=True)))
        self.assertTrue(self.radio.get_memory(1).empty)

    def test_tone_word_layout(self):
        # The 16 bit tone word is a 4 bit kind/flag nibble (1 = CTCSS receive,
        # 5 = CTCSS transmit) and a 12 bit value in units of 100 mHz, so
        # 88.5Hz is 0x1375 on the receive side and 0x5375 on the transmit one.
        mem = chirp_common.Memory()
        mem.number = 5
        mem.freq = 439000000
        mem.duplex = ""
        mem.tmode = "TSQL"
        mem.ctone = 88.5
        mem.rtone = 88.5
        mem.mode = "FM"
        self.radio.set_memory(mem)

        raw = bytes(self.radio._memobj.memory[4].get_raw(asbytes=True))
        self.assertEqual(0x1375, int.from_bytes(raw[7:9], "big"))
        self.assertEqual(0x5375, int.from_bytes(raw[9:11], "big"))
        # 5 kHz units for 439.000MHz, and the "channel in use" marker
        self.assertEqual(0x01, raw[16])

    def test_write_keeps_the_bytes_it_does_not_own(self):
        # CHIRP only edits the frequency, offset, tone, band and name fields.
        # The rest of the record belongs to the radio: [13] and [17] are flags
        # (see above), [18:26] holds the scan/zone code and [26:32] is the
        # "------" padding the vendor software fills in.  None of it may
        # change when a channel is written back.
        # The airband channels go through chirp_common.fix_rounded_step(),
        # which raises a translated message, so give it a no-op gettext.
        first, last = self.radio.get_features().memory_bounds
        with mock.patch("builtins._", lambda text: text, create=True):
            for number in range(first, last + 1):
                record = self.radio._memobj.memory[number - 1]
                before = bytes(record.get_raw(asbytes=True))
                self.radio.set_memory(self.radio.get_memory(number))
                after = bytes(record.get_raw(asbytes=True))

                self.assertEqual(before[13], after[13],
                                 "channel %i" % number)
                self.assertEqual(before[17], after[17],
                                 "channel %i" % number)
                self.assertEqual(before[18:26], after[18:26],
                                 "channel %i" % number)
                self.assertEqual(before[26:32], after[26:32],
                                 "channel %i" % number)
