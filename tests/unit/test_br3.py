# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os

import pytest

from chirp import chirp_common, directory
from chirp.drivers import br3, tdxone_tdq8a

IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "Baolisitong_BR-3.img")


@pytest.fixture()
def radio():
    klass = directory.get_radio("Baolisitong_BR-3")
    r = klass(IMAGE)
    r.load(IMAGE)
    return r


def test_image_size(radio):
    assert len(radio.get_mmap().get_packed()) == 0x2008
    assert radio.get_features().memory_bounds == (1, 128)


def test_bands(radio):
    # 66-88 MHz is broadcast FM receive only, so it is not a channel band
    assert radio.get_features().valid_bands == [(136000000, 174000000),
                                                (400000000, 480000000)]


def test_used_channels(radio):
    used = [n for n in range(1, 129) if not radio.get_memory(n).empty]
    assert len(used) == 112
    assert used[0] == 1
    # 78..93 are empty in this codeplug
    assert 78 not in used
    assert 93 not in used
    assert 94 in used


def test_simplex_channel(radio):
    mem = radio.get_memory(1)
    assert mem.freq == 435587500
    assert mem.duplex == ""
    assert mem.offset == 0
    assert mem.name == ""
    assert mem.mode == "FM"
    assert mem.power == radio.get_features().valid_power_levels[0]
    assert mem.skip == ""
    assert mem.tmode == ""


def test_repeater_channel(radio):
    mem = radio.get_memory(3)
    assert mem.freq == 439587500
    assert mem.duplex == "-"
    assert mem.offset == 8000000
    assert mem.tmode == "TSQL"
    assert mem.ctone == 88.5
    assert mem.rtone == 88.5


def test_dcs_channel(radio):
    # channel 94 carries DI032, channel 98 DN125 in the stock codeplug
    mem = radio.get_memory(94)
    assert mem.tmode == "DTCS"
    assert mem.dtcs == 32
    assert mem.dtcs_polarity == "RR"

    mem = radio.get_memory(98)
    assert mem.tmode == "DTCS"
    assert mem.dtcs == 125
    assert mem.dtcs_polarity == "NN"


def test_bcl_flag(radio):
    # channels 1 and 8 are the only ones with busy channel lockout off
    assert radio.get_memory(1).extra["bcl"].value.get_value() is False
    assert radio.get_memory(8).extra["bcl"].value.get_value() is False
    assert radio.get_memory(2).extra["bcl"].value.get_value() is True
    assert radio.get_memory(2).extra["dtmf"].value.get_value() is True


def test_validate_all(radio):
    for number in range(1, 129):
        mem = radio.get_memory(number)
        if mem.empty:
            continue
        assert radio.validate_memory(mem) == [], "channel %i" % number


def test_set_memory_round_trip(radio):
    mem = chirp_common.Memory()
    mem.number = 120
    mem.freq = 439000000
    mem.duplex = "-"
    mem.offset = 5000000
    mem.tmode = "Tone"
    mem.rtone = 88.5
    mem.name = "BG8ADW"
    mem.mode = "NFM"
    mem.power = radio.get_features().valid_power_levels[1]
    mem.skip = "S"
    radio.set_memory(mem)

    ret = radio.get_memory(120)
    assert ret.freq == 439000000
    assert ret.duplex == "-"
    assert ret.offset == 5000000
    assert ret.tmode == "Tone"
    assert ret.rtone == 88.5
    assert ret.name == "BG8ADW"
    assert ret.mode == "NFM"
    assert ret.power == radio.get_features().valid_power_levels[1]
    assert ret.skip == "S"


def test_set_dcs_memory(radio):
    mem = radio.get_memory(2)
    mem.tmode = "DTCS"
    mem.dtcs = 754
    mem.dtcs_polarity = "NR"
    radio.set_memory(mem)

    raw = radio._memobj.memory[1]
    assert int(raw.txtone) == 0x2800 | int("754", 8)
    assert int(raw.rxtone) == 0xA800 | int("754", 8)

    back = radio.get_memory(2)
    assert back.tmode == "DTCS"
    assert back.dtcs == 754
    assert back.dtcs_polarity == "NR"


def test_clear_channel(radio):
    mem = chirp_common.Memory()
    mem.number = 121
    mem.empty = True
    radio.set_memory(mem)
    assert radio.get_memory(121).empty
    raw = bytes(radio._memobj.memory[120].get_raw(asbytes=True))
    assert raw == b"\xff" * 16


def test_write_preserves_unknown_bits(radio):
    mem = radio.get_memory(3)
    radio.set_memory(mem)
    raw = bytes(radio._memobj.memory[2].get_raw(asbytes=True))
    assert raw[12] == 0xFF
    assert raw[13] == 0xFF


def test_upload_ranges(radio):
    for start, end in radio._ranges:
        assert start % 0x10 == 0
        assert end <= 0x2000


def test_clone_frames():
    # these are the exact frames the vendor CPS builds (see BR3_TD6格式.md)
    assert tdxone_tdq8a.MSTRING_TDQ8A == "\x02PYNCRAM"
    assert tdxone_tdq8a._make_frame("R", 0x0010, 0x40) == b"R\x00\x10\x40"
    assert tdxone_tdq8a._make_frame("W", 0x0F80, 0x10) == b"W\x0F\x80\x10"
    assert br3.BaolisitongBR3._recv_block_size == 0x40
    assert br3.BaolisitongBR3._send_block_size == 0x10
    assert br3.BaolisitongBR3._mem_size == 0x2000
