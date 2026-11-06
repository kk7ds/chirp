# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os

import pytest

from chirp import chirp_common, directory
from chirp.drivers import v8plus

IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "Weierwei_VEV-V8_Plus.img")


@pytest.fixture()
def radio():
    klass = directory.get_radio("Weierwei_VEV-V8_Plus")
    r = klass(IMAGE)
    r.load(IMAGE)
    return r


def test_frame_checksum():
    frame = v8plus.HANDSHAKE
    checksum = 0
    for byte in frame[:-1]:
        checksum ^= byte
    assert checksum == frame[-1]
    assert v8plus.PROBE == bytes([0x06, 0x00, 0x06])


def test_frequency_encoding():
    assert v8plus._encode_freq(435587500) == b"\x43\x55\x87\x08"
    assert v8plus._encode_freq(438500000) == b"\x43\x85\x00\x00"
    assert v8plus._encode_freq(438125000) == b"\x43\x81\x25\x00"
    assert v8plus._decode_freq(b"\x43\x55\x87\x08") == 435587500
    assert v8plus._decode_freq(b"\x43\x85\x00\x00") == 438500000
    # every frequency in the image must survive a round trip
    for hz in (400000000, 430512500, 446006000, 469993500):
        assert v8plus._decode_freq(v8plus._encode_freq(hz)) == hz


def test_bcd_helpers():
    assert v8plus._int_to_bcd(435587, 3) == b"\x43\x55\x87"
    assert v8plus._bcd_to_int(b"\x43\x55\x87") == 435587
    assert v8plus._bcd_to_int(b"\xff\xff\xff") is None


def test_tone_mapping():
    assert v8plus._index_to_tone(6) == 77.0
    assert v8plus._index_to_tone(10) == 88.5
    assert v8plus._index_to_tone(14) == 100.0
    for tone in chirp_common.TONES:
        index = v8plus._tone_to_index(tone)
        assert v8plus._index_to_tone(index) == tone


def test_get_memory(radio):
    assert radio.get_memory(1).freq == 435587500
    assert radio.get_memory(1).duplex == ""
    assert str(radio.get_memory(1).power) == "High"
    assert radio.get_memory(1).mode == "FM"

    mem = radio.get_memory(3)
    assert mem.freq == 439587500
    assert mem.duplex == "-"
    assert mem.offset == 8000000
    assert mem.tmode == "TSQL"
    assert mem.rtone == 88.5

    mem = radio.get_memory(18)
    assert mem.tmode == "Tone"
    assert mem.rtone == 88.5

    assert radio.get_memory(199).empty


def test_get_memory_all_in_band(radio):
    for number in range(1, radio.get_features().memory_bounds[1] + 1):
        mem = radio.get_memory(number)
        if mem.empty:
            continue
        assert 400000000 <= mem.freq <= 470000000
        assert mem.mode in ("FM", "NFM")
        assert str(mem.power) in ("High", "Low")


def test_set_memory_new_channel(radio):
    mem = chirp_common.Memory()
    mem.number = 150
    mem.freq = 435000000
    mem.duplex = "+"
    mem.offset = 5000000
    mem.power = v8plus.POWER_LEVELS[1]
    mem.mode = "NFM"
    mem.tmode = "Tone"
    mem.rtone = 88.5
    radio.set_memory(mem)

    raw = radio._memobj.memory[149]
    assert raw.rx_freq.get_raw() == b"\x43\x50\x00\x00"
    assert raw.tx_freq.get_raw() == b"\x44\x00\x00\x00"
    assert raw.tx_tone == 10
    assert raw.tx_tone_flag == v8plus.TX_TONE_FLAG
    assert raw.rx_tone_flag == 0x00
    assert not raw.flags & v8plus.POWER_HIGH
    assert not raw.flags & v8plus.BANDWIDTH_WIDE

    reread = radio.get_memory(150)
    assert reread.freq == 435000000
    assert reread.offset == 5000000
    assert str(reread.power) == "Low"
    assert reread.mode == "NFM"
    assert reread.tmode == "Tone"
    assert reread.rtone == 88.5


def test_set_memory_cross_and_half_khz(radio):
    mem = chirp_common.Memory()
    mem.number = 151
    mem.freq = 439512500
    mem.duplex = ""
    mem.offset = 0
    mem.power = v8plus.POWER_LEVELS[0]
    mem.mode = "FM"
    mem.tmode = "Cross"
    mem.cross_mode = "Tone->Tone"
    mem.rtone = 100.0
    mem.ctone = 77.0
    radio.set_memory(mem)

    raw = radio._memobj.memory[150]
    assert raw.rx_freq.get_raw() == b"\x43\x95\x12\x08"
    assert raw.tx_tone == 14
    assert raw.rx_tone == 6
    assert raw.tx_tone_flag == v8plus.TX_TONE_FLAG
    assert raw.rx_tone_flag == v8plus.RX_TONE_FLAG

    reread = radio.get_memory(151)
    assert reread.freq == 439512500
    assert reread.tmode == "Cross"
    assert reread.cross_mode == "Tone->Tone"
    assert reread.rtone == 100.0
    assert reread.ctone == 77.0


def test_erase_memory(radio):
    mem = radio.get_memory(1)
    mem.empty = True
    radio.set_memory(mem)
    assert radio._memobj.memory[0].get_raw() == b"\xff" * 16
    assert radio.get_memory(1).empty


def test_round_trip_byte_identical(radio):
    before = radio.get_mmap().get_packed()
    for number in range(1, 200):
        mem = radio.get_memory(number)
        radio.set_memory(mem)
    after = radio.get_mmap().get_packed()
    assert before == after


def test_validate_high_power_narrow(radio):
    mem = radio.get_memory(1)
    mem.mode = "NFM"
    mem.power = v8plus.POWER_LEVELS[0]
    msgs = radio.validate_memory(mem)
    assert any("wide bandwidth" in str(m) for m in msgs)


def test_cross_rx_only_tone(radio):
    mem = chirp_common.Memory()
    mem.number = 152
    mem.freq = 433000000
    mem.duplex = ""
    mem.offset = 0
    mem.power = v8plus.POWER_LEVELS[0]
    mem.mode = "FM"
    mem.tmode = "Cross"
    mem.cross_mode = "->Tone"
    mem.ctone = 88.5
    radio.set_memory(mem)
    raw = radio._memobj.memory[151]
    assert raw.tx_tone_flag == 0x00
    assert raw.rx_tone_flag == v8plus.RX_TONE_FLAG
    back = radio.get_memory(152)
    assert back.tmode == "Cross"
    assert back.cross_mode == "->Tone"
    assert back.ctone == 88.5
