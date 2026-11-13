# Copyright 2026 赵昕 BG8ADW
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os

import pytest

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


@pytest.fixture()
def radio():
    r = directory.get_radio("Weierwei_VEV-V8_Plus")(IMAGE)
    return r


def test_handshake_frame():
    frame = v8plus.WAKE_PAYLOAD
    assert frame == b"\x46\x4c\x74\x06\x45\x04"
    packet = b"\x02" + bytes([len(frame)]) + frame
    checksum = 0
    for byte in packet:
        checksum ^= byte
    assert checksum == 0x3D
    # the reply the radio gives is the ident string, same framing
    assert ident_reply() == b"\x06\x06" + v8plus.IDENT + b"\x3e"


def test_frames_match_the_leixen_protocol():
    # read and write frames are the ones the clone protocol defines
    assert leixen.make_frame(b"R", 0x0310, b"\x10") == \
        b"\x52\x03\x03\x10\x10\x52"
    assert leixen.make_frame(b"W", 0x0310, b"\x00" * 16) == \
        b"\x57\x12\x03\x10" + b"\x00" * 16 + b"\x56"


def test_transport_is_shared_with_the_leixen_driver():
    """The clone layer is not reimplemented here."""
    assert issubclass(v8plus.VEVV8PlusRadio, leixen.LeixenVV898Radio)
    for name in ("make_frame", "send", "recv", "do_ident", "do_download",
                 "do_upload", "finish"):
        assert not hasattr(v8plus, name), name
    assert v8plus.WAKE_PAYLOAD != leixen.LeixenVV898Radio._wake_payload
    assert v8plus.IDENT != leixen.LeixenVV898Radio._ident
    assert v8plus.VEVV8PlusRadio._memsize == 0x2000
    assert v8plus.VEVV8PlusRadio._upload_ranges == [(0x0000, 0x2000)]


def test_detection_is_not_automatic():
    # leixen's detector reads an image ident this radio does not have
    with pytest.raises(NotImplementedError):
        v8plus.VEVV8PlusRadio.detect_from_serial(object())


def test_handshake_sets_the_timeout_and_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(v8plus.time, "sleep", sleeps.append)
    pipe = FakeSerial([b"\x00" * 9,            # a frame that is not an ident
                       ident_reply(),
                       b"\x06\x00\x06"])
    radio = v8plus.VEVV8PlusRadio(None)
    radio.pipe = pipe
    radio._handshake()

    assert pipe.timeout == v8plus.VEVV8PlusRadio.IDENT_TIMEOUT
    # one retry delay, and nothing else
    assert sleeps == [v8plus.VEVV8PlusRadio.IDENT_RETRY_DELAY]
    # two handshake frames, and the input is cleared once for the retry
    assert len([w for w in pipe.written if w[0] == 0x02]) == 2
    assert pipe.resets == 1
    assert pipe.written[-1] == b"\x06\x00\x06"


def test_handshake_gives_up(monkeypatch):
    monkeypatch.setattr(v8plus.time, "sleep", lambda seconds: None)
    radio = v8plus.VEVV8PlusRadio(None)
    radio.pipe = FakeSerial([])
    with pytest.raises(errors.RadioError):
        radio._handshake()


def test_sync_in_uses_the_leixen_downloader(monkeypatch):
    class FakeRadio(v8plus.VEVV8PlusRadio):
        def _handshake(self):
            pass

    payload = bytes(0x2000)
    calls = []

    def fake_download(radio):
        calls.append(radio)
        return memmap.MemoryMapBytes(payload)

    monkeypatch.setattr(leixen, "do_download", fake_download)
    radio = FakeRadio(None)
    radio.sync_in()
    assert calls == [radio]
    assert radio._memobj is not None


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


def test_tone_table_is_the_vendor_software_list():
    assert v8plus.TONES == CPS_TONES
    assert len(v8plus.TONES) == 47
    # the list starts at 63.0 and stops at 229.1
    assert v8plus.TONES[0] == 63.0
    assert v8plus.TONES[-1] == 229.1
    for tone in (233.6, 241.8, 250.3, 254.1):
        assert tone not in v8plus.TONES


def test_stored_tone_index_is_the_list_position_plus_one(radio):
    for tone, index in CPS_TONE_INDEX:
        assert v8plus.TONES.index(tone) + 1 == index, tone
        assert radio._decode_tone(index, v8plus.TX_TONE_FLAG,
                                  v8plus.TX_TONE_FLAG) == tone
    # 63.0 is the first entry of the list, so it is stored as 1
    assert v8plus.TONES.index(63.0) + 1 == 1


def test_no_tone_is_stored_as_ff(radio):
    # 0xff is what the radio itself writes into an unused tone slot, and the
    # vendor software writes 0; both mean "no tone", and the flag byte agrees
    assert radio._decode_tone(v8plus.NO_TONE, v8plus.TX_TONE_FLAG,
                              v8plus.TX_TONE_FLAG) is None
    assert radio._decode_tone(0, v8plus.TX_TONE_FLAG,
                              v8plus.TX_TONE_FLAG) is None
    assert radio._decode_tone(10, 0x00, v8plus.TX_TONE_FLAG) is None
    assert radio._decode_tone(200, v8plus.TX_TONE_FLAG,
                              v8plus.TX_TONE_FLAG) is None


def test_valid_tones_are_only_the_supported_ones(radio):
    assert radio.get_features().valid_tones == v8plus.TONES


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
    assert mem.ctone == 88.5

    mem = radio.get_memory(6)
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
    mem.power = radio.get_features().valid_power_levels[1]
    mem.mode = "NFM"
    mem.tmode = "Tone"
    mem.rtone = 88.5
    radio.set_memory(mem)

    raw = radio._memobj.memory[149]
    assert raw.rx_freq.get_raw() == b"\x43\x50\x00\x00"
    assert raw.tx_freq.get_raw() == b"\x44\x00\x00\x00"
    assert raw.tx_tone == 10
    assert raw.tx_tone_flag == v8plus.TX_TONE_FLAG
    assert raw.rx_tone == v8plus.NO_TONE
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
    mem.power = radio.get_features().valid_power_levels[0]
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


def test_set_memory_low_tone(radio):
    # 63.0 Hz is the first entry of the radio's tone list
    mem = chirp_common.Memory()
    mem.number = 153
    mem.freq = 433500000
    mem.duplex = ""
    mem.offset = 0
    mem.power = radio.get_features().valid_power_levels[1]
    mem.mode = "FM"
    mem.tmode = "Tone"
    mem.rtone = 63.0
    radio.set_memory(mem)

    assert radio._memobj.memory[152].tx_tone == 1
    assert radio.get_memory(153).rtone == 63.0


def test_unsupported_tone_is_not_written(radio):
    """A tone outside the table must not be stored as some other tone."""
    mem = chirp_common.Memory()
    mem.number = 154
    mem.freq = 433600000
    mem.duplex = ""
    mem.offset = 0
    mem.power = radio.get_features().valid_power_levels[1]
    mem.mode = "FM"
    mem.tmode = "Tone"
    mem.rtone = 250.3                      # not in the radio's list
    radio.set_memory(mem)

    raw = radio._memobj.memory[153]
    assert raw.tx_tone == v8plus.NO_TONE
    assert raw.tx_tone_flag == 0x00
    assert radio.get_memory(154).tmode == ""


def test_erase_memory(radio):
    mem = radio.get_memory(1)
    mem.empty = True
    radio.set_memory(mem)
    assert radio._memobj.memory[0].get_raw() == b"\xff" * 16
    assert radio.get_memory(1).empty


def test_round_trip_byte_identical(radio):
    before = radio.get_mmap().get_packed()
    for number in range(1, 200):
        radio.set_memory(radio.get_memory(number))
    after = radio.get_mmap().get_packed()
    assert before == after


def test_power_and_bandwidth_are_independent(radio):
    mem = radio.get_memory(1)
    mem.power = radio.get_features().valid_power_levels[0]
    mem.mode = "NFM"
    radio.set_memory(mem)
    raw = radio._memobj.memory[0]
    assert raw.flags & v8plus.POWER_HIGH
    assert not raw.flags & v8plus.BANDWIDTH_WIDE
    assert radio.validate_memory(radio.get_memory(1)) == []


def test_cross_rx_only_tone(radio):
    mem = chirp_common.Memory()
    mem.number = 152
    mem.freq = 433000000
    mem.duplex = ""
    mem.offset = 0
    mem.power = radio.get_features().valid_power_levels[0]
    mem.mode = "FM"
    mem.tmode = "Cross"
    mem.cross_mode = "->Tone"
    mem.ctone = 88.5
    radio.set_memory(mem)
    raw = radio._memobj.memory[151]
    assert raw.tx_tone_flag == 0x00
    assert raw.rx_tone_flag == v8plus.RX_TONE_FLAG
    assert raw.rx_tone == 10
    back = radio.get_memory(152)
    assert back.tmode == "Cross"
    assert back.cross_mode == "->Tone"
    assert back.ctone == 88.5
