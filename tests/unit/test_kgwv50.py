# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os
import unittest

from chirp import chirp_common, directory
from chirp.drivers import kguv8d, kgwv50


IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "Wouxun_KG-WV50.img")


class TestKGWV50(unittest.TestCase):
    def setUp(self):
        klass = directory.get_radio("Wouxun_KG-WV50")
        self.radio = klass(IMAGE)
        self.radio.load(IMAGE)

    def test_driver_identity(self):
        self.assertEqual(0x78, kgwv50.KGWV50Radio._record_start)
        self.assertEqual("Wouxun", kgwv50.KGWV50Radio.VENDOR)
        self.assertEqual("KG-WV50", kgwv50.KGWV50Radio.MODEL)
        self.assertTrue(issubclass(
            kgwv50.KGWV50Radio, directory.get_radio("Wouxun_KG-UV8E")))

    def test_image_size_and_layout(self):
        self.assertEqual(0x8000,
                         len(self.radio.get_mmap().get_packed()))
        self.assertEqual((1, kgwv50.CHANNEL_COUNT),
                         self.radio.get_features().memory_bounds)

    def test_channel_index_offset(self):
        # CH-001 is the first channel slot, slot 0 is unused
        self.assertEqual(1, self.radio._mem_index(1))
        self.assertEqual(999, self.radio._mem_index(999))

    def test_image_channels(self):
        used = [n for n in range(1, kgwv50.CHANNEL_COUNT + 1)
                if not self.radio.get_memory(n).empty]
        self.assertEqual(1, used[0])
        self.assertEqual(77, len(used))
        first = self.radio.get_memory(1)
        self.assertEqual(435587500, first.freq)
        self.assertEqual("私有频道", first.name)
        self.assertEqual("", first.duplex)
        self.assertEqual("NFM", first.mode)
        self.assertEqual(self.radio.POWER_LEVELS[1], first.power)

    def test_read_only_image_has_no_warnings(self):
        for n in range(1, kgwv50.CHANNEL_COUNT + 1):
            mem = self.radio.get_memory(n)
            if mem.empty:
                continue
            self.assertEqual([], self.radio.validate_memory(mem),
                             "channel %i" % n)

    def test_set_memory_round_trip(self):
        mem = chirp_common.Memory()
        mem.number = 500
        mem.freq = 439000000
        mem.duplex = "-"
        mem.offset = 5000000
        mem.tmode = "Tone"
        mem.rtone = 88.5
        mem.name = "测试中继"
        mem.mode = "FM"
        mem.power = self.radio.POWER_LEVELS[0]
        mem.skip = "S"
        self.radio.set_memory(mem)

        ret = self.radio.get_memory(500)
        self.assertEqual(439000000, ret.freq)
        self.assertEqual("-", ret.duplex)
        self.assertEqual(5000000, ret.offset)
        self.assertEqual("Tone", ret.tmode)
        self.assertEqual(88.5, ret.rtone)
        self.assertEqual("测试中继", ret.name)
        self.assertEqual("FM", ret.mode)
        self.assertEqual(self.radio.POWER_LEVELS[0], ret.power)
        self.assertEqual("S", ret.skip)

    def test_set_memory_duplex_off(self):
        mem = chirp_common.Memory()
        mem.number = 501
        mem.freq = 433000000
        mem.duplex = "off"
        mem.tmode = ""
        self.radio.set_memory(mem)
        ret = self.radio.get_memory(501)
        self.assertEqual("off", ret.duplex)
        self.assertEqual(0, ret.offset)

    def test_set_memory_odd_split(self):
        mem = chirp_common.Memory()
        mem.number = 502
        mem.freq = 433000000
        mem.duplex = "split"
        # the radio only distinguishes a "split" when the two frequencies
        # are more than 70 MHz apart (same rule as the KG-UV8E)
        mem.offset = 145000000
        mem.tmode = ""
        self.radio.set_memory(mem)
        ret = self.radio.get_memory(502)
        self.assertEqual("split", ret.duplex)
        self.assertEqual(145000000, ret.offset)

    def test_set_memory_dcs(self):
        mem = chirp_common.Memory()
        mem.number = 503
        mem.freq = 433500000
        mem.duplex = ""
        mem.tmode = "DTCS"
        mem.dtcs = 23
        self.radio.set_memory(mem)
        ret = self.radio.get_memory(503)
        self.assertEqual("DTCS", ret.tmode)
        self.assertEqual(23, ret.dtcs)

    def test_clear_sets_valid_flag(self):
        mem = chirp_common.Memory()
        mem.number = 504
        mem.freq = 433500000
        mem.duplex = ""
        mem.tmode = ""
        self.radio.set_memory(mem)
        self.assertEqual(kguv8d.MEM_VALID,
                         int(self.radio._memobj.valid[504]))

        empty = chirp_common.Memory()
        empty.number = 504
        empty.empty = True
        self.radio.set_memory(empty)
        self.assertTrue(self.radio.get_memory(504).empty)
        self.assertEqual(0, int(self.radio._memobj.valid[504]))

    def test_name_truncation_warning(self):
        mem = self.radio.get_memory(3)
        mem.name = "一二三四五六七"
        msgs = self.radio.validate_memory(mem)
        self.assertTrue(any("too long" in str(m) for m in msgs), msgs)

    def test_upload_only_covers_the_mapped_area(self):
        # The radio answers 0xdd for the reserved area, so it is never written
        self.assertEqual(0x0900, self.radio._upload_start)
        self.assertEqual(0x7A60, self.radio._upload_end)

    def test_codec_round_trip(self):
        # The record codec is inherited from the KG-UV8E
        radio = kgwv50.KGWV50Radio(None)
        for payload in (b"\x01", bytes(range(32))):
            self.assertEqual(payload, radio.decrypt(radio.encrypt(payload)))

    def test_serial_error_is_radio_error(self):
        class BrokenPipe(object):
            def read(self, count):
                raise IOError("boom")

            def write(self, data):
                raise IOError("boom")

            def flush(self):
                pass

            @property
            def in_waiting(self):
                return 0

        self.radio.pipe = BrokenPipe()
        with self.assertRaises(Exception):
            self.radio._identify()

    def test_full_image_round_trips_unchanged(self):
        # Reading a whole codeplug and writing it back unedited has to be a
        # no-op.  This pins the encoding to the vendor's: the image is the
        # radio's own and it has 0xff in the 922 channels that are not in use,
        # so an encoder that invents a default (a tone flag, a different fill
        # for the empty slots) shows up here as a diff instead of hiding
        # behind our own decoder.
        before = bytes(self.radio.get_mmap().get_packed())
        for number in range(1, kgwv50.CHANNEL_COUNT + 1):
            self.radio.set_memory(self.radio.get_memory(number))
        self.assertEqual(before, bytes(self.radio.get_mmap().get_packed()))

    def test_clear_channel_matches_vendor_fill(self):
        # The vendor codeplug leaves unused channel records as 0xff and the
        # unused names as 0x00, so a cleared channel should look the same.
        mem = chirp_common.Memory()
        mem.number = 5
        mem.empty = True
        self.radio.set_memory(mem)

        # CH-001 is slot 1 on this radio, so channel 5 lives in memory[5]
        self.assertEqual(b'\xff' * 16, bytes(
            self.radio._memobj.memory[5].get_raw(asbytes=True)))
        self.assertEqual(0, int(self.radio._memobj.valid[5]))
        self.assertEqual(b'\x00' * 12, bytes(
            self.radio._memobj.names[5].get_raw(asbytes=True)))
        self.assertTrue(self.radio.get_memory(5).empty)
