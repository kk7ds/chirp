# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os

import pytest

from chirp import chirp_common, directory
from chirp.drivers import kguv8d, kgwv50


IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "Wouxun_KG-WV50.img")


@pytest.fixture()
def radio():
    klass = directory.get_radio("Wouxun_KG-WV50")
    r = klass(IMAGE)
    r.load(IMAGE)
    return r


def test_driver_identity(radio):
    assert kgwv50.KGWV50Radio._record_start == 0x78
    assert kgwv50.KGWV50Radio.VENDOR == "Wouxun"
    assert kgwv50.KGWV50Radio.MODEL == "KG-WV50"
    assert issubclass(kgwv50.KGWV50Radio,
                      directory.get_radio("Wouxun_KG-UV8E"))


def test_image_size_and_layout(radio):
    assert len(radio.get_mmap().get_packed()) == 0x8000
    assert radio.get_features().memory_bounds == (1, kgwv50.CHANNEL_COUNT)


def test_channel_index_offset(radio):
    # CH-001 is slot 0 on this radio
    assert radio._mem_index(1) == 0
    assert radio._mem_index(999) == 998


def test_image_channels(radio):
    used = [n for n in range(1, kgwv50.CHANNEL_COUNT + 1)
            if not radio.get_memory(n).empty]
    assert used[0] == 2
    assert len(used) == 77
    first = radio.get_memory(2)
    assert first.freq == 435587500
    assert first.name == "私有频道"
    assert first.duplex == ""
    assert first.mode == "NFM"
    assert first.power == radio.POWER_LEVELS[1]


def test_read_only_image_has_no_warnings(radio):
    for n in range(1, kgwv50.CHANNEL_COUNT + 1):
        mem = radio.get_memory(n)
        if mem.empty:
            continue
        assert radio.validate_memory(mem) == [], "channel %i" % n


def test_set_memory_round_trip(radio):
    mem = chirp_common.Memory()
    mem.number = 500
    mem.freq = 439000000
    mem.duplex = "-"
    mem.offset = 5000000
    mem.tmode = "Tone"
    mem.rtone = 88.5
    mem.name = "测试中继"
    mem.mode = "FM"
    mem.power = radio.POWER_LEVELS[0]
    mem.skip = "S"
    radio.set_memory(mem)

    ret = radio.get_memory(500)
    assert ret.freq == 439000000
    assert ret.duplex == "-"
    assert ret.offset == 5000000
    assert ret.tmode == "Tone"
    assert ret.rtone == 88.5
    assert ret.name == "测试中继"
    assert ret.mode == "FM"
    assert ret.power == radio.POWER_LEVELS[0]
    assert ret.skip == "S"


def test_set_memory_duplex_off(radio):
    mem = chirp_common.Memory()
    mem.number = 501
    mem.freq = 433000000
    mem.duplex = "off"
    mem.tmode = ""
    radio.set_memory(mem)
    ret = radio.get_memory(501)
    assert ret.duplex == "off"
    assert ret.offset == 0


def test_set_memory_odd_split(radio):
    mem = chirp_common.Memory()
    mem.number = 502
    mem.freq = 433000000
    mem.duplex = "split"
    # the radio only distinguishes a "split" when the two frequencies are
    # more than 70 MHz apart (same rule as the KG-UV8E)
    mem.offset = 145000000
    mem.tmode = ""
    radio.set_memory(mem)
    ret = radio.get_memory(502)
    assert ret.duplex == "split"
    assert ret.offset == 145000000


def test_set_memory_dcs(radio):
    mem = chirp_common.Memory()
    mem.number = 503
    mem.freq = 433500000
    mem.duplex = ""
    mem.tmode = "DTCS"
    mem.dtcs = 23
    radio.set_memory(mem)
    ret = radio.get_memory(503)
    assert ret.tmode == "DTCS"
    assert ret.dtcs == 23


def test_clear_sets_valid_flag(radio):
    mem = chirp_common.Memory()
    mem.number = 504
    mem.freq = 433500000
    mem.duplex = ""
    mem.tmode = ""
    radio.set_memory(mem)
    assert int(radio._memobj.valid[503]) == kguv8d.MEM_VALID

    empty = chirp_common.Memory()
    empty.number = 504
    empty.empty = True
    radio.set_memory(empty)
    assert radio.get_memory(504).empty
    assert int(radio._memobj.valid[503]) == 0


def test_name_truncation_warning(radio):
    mem = radio.get_memory(3)
    mem.name = "一二三四五六七"
    msgs = radio.validate_memory(mem)
    assert any("too long" in str(m) for m in msgs), msgs


def test_upload_only_covers_the_mapped_area(radio):
    # The radio answers 0xdd for the reserved area, so it is never written
    assert radio._upload_start == 0x0900
    assert radio._upload_end == 0x7A60


def test_codec_round_trip():
    # The record codec is inherited from the KG-UV8E
    radio = kgwv50.KGWV50Radio(None)
    for payload in (b"\x01", bytes(range(32))):
        assert radio.decrypt(radio.encrypt(payload)) == payload


def test_serial_error_is_radio_error(radio):
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

    radio.pipe = BrokenPipe()
    with pytest.raises(Exception):
        radio._identify()
