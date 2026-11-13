# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os

import pytest

from chirp import chirp_common, directory
from chirp.drivers import v6

IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "Weierwei_VEV-V6.img")


@pytest.fixture(autouse=True)
def _gettext(monkeypatch):
    # chirp_common leans on the gettext builtin that only the GUI installs
    monkeypatch.setattr("builtins._", lambda text: text, raising=False)


@pytest.fixture()
def radio():
    klass = directory.get_radio("Weierwei_VEV-V6")
    r = klass(IMAGE)
    r.load(IMAGE)
    return r


def test_image_size(radio):
    assert v6.MEM_SIZE == 0x800
    assert len(v6.PAGE_ADDRS) == 8
    assert v6.PAGE_ADDRS[0] == 0xA000
    assert v6.PAGE_ADDRS[-1] == 0xAE00
    assert len(radio._mmap.get_packed()) == v6.MEM_SIZE


def test_frequency_encoding():
    # 435.5875 has a remainder of 87.5 kHz, which only fits 6.25 kHz steps
    assert v6.encode_frequencies(435587500, 435587500)[:2] == (4355, 14)
    assert v6.encode_frequencies(435587500, 435587500)[4] is False
    # 438.125 fits 5 kHz steps
    assert v6.encode_frequencies(438125000, 438125000)[:2] == (4381, 5)
    assert v6.encode_frequencies(438125000, 438125000)[4] is True
    # 400.000 MHz is all zeroes
    assert v6.encode_frequencies(400000000, 400000000)[:2] == (4000, 0)

    assert v6.decode_frequency(4355, 14, 0x48) == 435587500
    assert v6.decode_frequency(4381, 5, 0x68) == 438125000
    assert v6.decode_frequency(4303, 0, 0x48) == 430300000

    for hz in (400000000, 430300000, 435587500, 438125000, 469993750):
        coarse, fine, _c, _f, step5 = v6.encode_frequencies(hz, hz)
        flags9 = 0x20 if step5 else 0x00
        assert v6.decode_frequency(coarse, fine, flags9) == hz


def test_offset_encoding():
    result = v6.encode_frequencies(435587500, 435587500)
    assert result[2:] == (0x0A, 0xE0, False)
    # 8 MHz down: coarse 80, fine 0
    _r, _rf, coarse, flags, step5 = v6.encode_frequencies(439587500,
                                                          431587500)
    assert (coarse, flags) == (80, 0xA0)
    # 439.5875 needs the 6.25 kHz step, so the offset does too
    assert step5 is False
    assert v6.decode_offset(439587500, coarse, flags, 0x48) == 431587500
    # 8.1875 MHz down only fits the 6.25 kHz step: 81 + 14 * 6.25 kHz
    _r, _rf, coarse, flags, step5 = v6.encode_frequencies(439700000,
                                                          431512500)
    assert step5 is False
    assert (coarse, flags) == (81, 0xA0 + 14)
    assert v6.decode_offset(439700000, coarse, flags, 0x48) == 431512500
    # 5.0375 MHz up: 50 + 6 * 6.25 kHz
    _r, _rf, coarse, flags, step5 = v6.encode_frequencies(430300000,
                                                          435337500)
    assert flags & 0x40
    assert step5 is False
    assert v6.decode_offset(430300000, coarse, flags, 0x48) == 435337500


def test_tone_mapping():
    assert v6.index_to_tone(8) == 88.5
    assert v6.index_to_tone(12) == 100.0
    assert v6.index_to_tone(21) == 136.5
    for tone in v6.TONE_TABLE:
        assert v6.index_to_tone(v6.tone_to_index(tone)) == tone
    # 67.0 Hz is index 0, which is only usable because the flags byte says
    # whether a tone is present at all
    assert v6.index_to_tone(0) == 67.0
    assert 67.0 in v6.TONE_TABLE


def test_features(radio):
    rf = radio.get_features()
    assert rf.has_name is False
    assert rf.has_dtcs is False
    assert rf.valid_bands == [(400000000, 470000000)]
    assert rf.memory_bounds == (1, 128)
    assert rf.valid_modes == ["FM", "NFM"]


def test_channel_decode(radio):
    mem = radio.get_memory(1)
    assert mem.freq == 435587500
    assert mem.duplex == ""
    assert mem.tmode == ""
    assert mem.mode == "FM"
    assert str(mem.power) == "High"

    mem = radio.get_memory(3)
    assert mem.freq == 439587500
    assert mem.duplex == "-"
    assert mem.offset == 8000000
    assert mem.tmode == "TSQL"
    assert mem.rtone == 88.5
    assert mem.ctone == 88.5

    mem = radio.get_memory(5)
    assert mem.freq == 438125000
    assert mem.mode == "NFM"

    # 438.9375 / -7.45 MHz: the offset fine part is stored in 6.25 kHz steps
    mem = radio.get_memory(48)
    assert mem.freq == 438937500
    assert mem.offset == 7450000
    assert mem.tmode == "TSQL"
    assert mem.rtone == 79.7


def test_empty_channel(radio):
    assert radio.get_memory(101).empty
    radio.set_memory(radio.get_memory(101))
    assert radio.get_memory(101).empty


def test_round_trip_all_channels(radio):
    # every record must be reproduced byte for byte when the decoded values
    # are written back
    for number in range(1, v6.CHANNEL_COUNT + 1):
        page, index = v6._record_index(number)
        before = bytes(radio._memobj.page[page].ch[index].get_raw())
        mem = radio.get_memory(number)
        radio.set_memory(mem)
        after = bytes(radio._memobj.page[page].ch[index].get_raw())
        assert before == after, "channel %i changed" % number


def test_set_memory_new_channel(radio):
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
    radio.set_memory(mem)

    page, index = v6._record_index(120)
    raw = bytes(radio._memobj.page[page].ch[index].get_raw())
    assert raw == bytes([0x10, 0xEF, 0xA0, 0x00, 0x32, 0xA0, 0x08, 0x08,
                         0xFC, 0x69, 0xFF, 0xFF, 0xFF, 0xFF])

    back = radio.get_memory(120)
    assert back.freq == 433500000
    assert back.offset == 5000000
    assert back.tmode == "TSQL"
    assert back.rtone == 88.5
    assert back.mode == "NFM"
    assert str(back.power) == "Low"


def test_tone_67(radio):
    mem = chirp_common.Memory()
    mem.number = 121
    mem.freq = 433500000
    mem.tmode = "Tone"
    mem.rtone = 67.0
    mem.power = v6.POWER_LEVELS[0]
    radio.set_memory(mem)

    page, index = v6._record_index(121)
    raw = bytes(radio._memobj.page[page].ch[index].get_raw())
    assert raw[7] == 0
    assert not raw[9] & v6.NO_TX_TONE
    assert radio.get_memory(121).rtone == 67.0


def test_validate_memory(radio):
    mem = chirp_common.Memory()
    mem.number = 120
    mem.freq = 433500000
    mem.tmode = "Tone"
    mem.rtone = 88.5
    assert not radio.validate_memory(mem)

    mem.freq = 433503000
    msgs = radio.validate_memory(mem)
    assert any("kHz steps" in str(msg) for msg in msgs)
