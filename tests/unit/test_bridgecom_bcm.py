# Copyright 2026 Justin Overfelt
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os
from unittest import mock

import pytest

from chirp import chirp_common, errors, memmap
from chirp.drivers import bridgecom_bcm

IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "BridgeCom_BCM-220.img")


class FakeRadio:
    """Simulates the BCM-220 side of the clone protocol"""

    def __init__(self, data, answer_mode=True):
        self.data = bytearray(data)
        self.answer_mode = answer_mode
        self.rx = bytearray()
        self.tx = bytearray()
        self.mode = None
        self.block = None
        self.reset = False
        self.timeout = 0.25

    def _process(self):
        while self.rx:
            if self.mode == 'write' and self.block is not None:
                if len(self.rx) < 257:
                    return
                chunk = bytes(self.rx[:257])
                del self.rx[:257]
                assert (sum(chunk[:256]) + chunk[256]) & 0xFF == 0
                self.data[self.block * 256:(self.block + 1) * 256] = \
                    chunk[:256]
                self.block = None
                self.tx += b'\xAA'
                continue
            cmd = self.rx[0]
            if cmd in (0x36, 0x37) and len(self.rx) >= 2:
                del self.rx[:2]
                self.mode = 'write' if cmd == 0x36 else 'read'
                if self.answer_mode:
                    self.tx += b'\x55'
            elif cmd == 0xBB and len(self.rx) >= 3:
                self.block = self.rx[1] | (self.rx[2] << 8)
                del self.rx[:3]
                self.tx += b'\xAA'
            elif cmd == 0xAA and self.mode == 'read' and \
                    self.block is not None:
                del self.rx[:1]
                chunk = bytes(self.data[self.block * 256:
                                        (self.block + 1) * 256])
                self.tx += chunk + bytes([sum(chunk) & 0xFF])
                self.block = None
            elif cmd == 0xAA:
                del self.rx[:1]  # wake-up byte
            elif cmd == 0xEE:
                del self.rx[:1]
                self.reset = True
                self.tx += b'\x00'
            else:
                return

    def write(self, data):
        self.rx += data
        self._process()

    def read(self, length):
        data = bytes(self.tx[:length])
        del self.tx[:length]
        return data


@pytest.fixture()
def radio():
    r = bridgecom_bcm.BCM220Radio(IMAGE)
    r.status_fn = lambda s: None
    return r


@pytest.fixture(autouse=True)
def no_sleep():
    with mock.patch('time.sleep'):
        yield


def test_image(radio):
    assert len(radio.get_mmap().get_packed()) == 0x2810
    used = [n for n in range(1, 251) if not radio.get_memory(n).empty]
    assert used == list(range(1, 17))


def test_download(radio):
    data = radio.get_mmap().get_packed()
    fake = FakeRadio(data[:0x2800])
    radio.pipe = fake
    radio.sync_in()
    assert radio.get_mmap().get_packed() == data[:0x2800] + b'\x00' * 16
    assert fake.reset


def _without_radio_state(data):
    data = bytearray(data)
    data[0x5d] = 0
    for i in range(250):
        start = 0x100 + i * 40 + 28
        data[start:start + 12] = b'\x00' * 12
    return bytes(data)


def test_upload(radio):
    data = radio.get_mmap().get_packed()
    fake = FakeRadio(b'\x00' * 0x2800)
    radio.pipe = fake
    radio.sync_out()
    assert bytes(fake.data) == _without_radio_state(data)[:0x2800]
    assert fake.reset


def test_upload_clears_radio_state(radio):
    # The radio keeps its own state in 0x5d and in channel padding (e.g.
    # 0x7ff).  Writing stale values back made it drop channel 3 from the
    # in-use bitmap at power on, so uploads must zero them like the vendor
    # software does.
    image = bytearray(radio.get_mmap().get_packed())
    image[0x5d] = 0xd0
    image[0x7ff] = 0x06
    image[0x11e:0x120] = b'\xa0\xa8'
    radio = bridgecom_bcm.BCM220Radio(memmap.MemoryMapBytes(bytes(image)))
    radio.status_fn = lambda s: None
    fake = FakeRadio(b'\xff' * 0x2800)
    radio.pipe = fake
    radio.sync_out()
    assert fake.data[0x5d] == 0
    assert fake.data[0x7ff] == 0
    assert fake.data[0x11e:0x120] == b'\x00\x00'
    assert bytes(fake.data) == _without_radio_state(image)[:0x2800]


def test_no_answer(radio):
    radio.pipe = FakeRadio(b'\x00' * 0x2800, answer_mode=False)
    with mock.patch('time.time', side_effect=range(1000)):
        with pytest.raises(errors.RadioError):
            radio.sync_in()


def test_tones(radio):
    m = radio.get_memory(16)
    assert (m.tmode, m.dtcs, m.dtcs_polarity) == ('DTCS', 754, 'RR')
    assert int(radio._memobj.memory[15].txtone) == 204
    m = radio.get_memory(12)
    assert (m.tmode, m.ctone, m.mode) == ('TSQL', 100.0, 'NFM')


def test_data_band_forces_data(radio):
    m = chirp_common.Memory(100)
    m.freq = 219500000
    radio.set_memory(m)
    m = radio.get_memory(100)
    assert m.extra['data'].value
    m.extra['data'].value = False
    radio.set_memory(m)
    assert radio.get_memory(100).extra['data'].value


def test_data_optional_in_voice_band(radio):
    m = chirp_common.Memory(100)
    m.freq = 223500000
    radio.set_memory(m)
    assert not radio.get_memory(100).extra['data'].value


def test_band_mismatch(radio):
    m = chirp_common.Memory(100)
    m.freq = 219500000
    m.duplex = 'split'
    m.offset = 223500000
    msgs = radio.validate_memory(m)
    assert any(isinstance(x, chirp_common.ValidationError) for x in msgs)


def test_bitmaps(radio):
    m = chirp_common.Memory(100)
    m.freq = 223500000
    radio.set_memory(m)
    _set = radio._memobj.settings
    assert int(_set.used[99 // 8]) & (0x80 >> (99 % 8))
    assert int(_set.scanlist[99 // 8]) & (0x80 >> (99 % 8))
    m.empty = True
    radio.set_memory(m)
    assert not int(_set.used[99 // 8]) & (0x80 >> (99 % 8))
    assert not int(_set.scanlist[99 // 8]) & (0x80 >> (99 % 8))


def test_last_channel_name(radio):
    m = chirp_common.Memory(250)
    m.freq = 223500000
    m.name = 'ABCDEFGHIJKLMNOP'
    radio.set_memory(m)
    assert radio.get_memory(250).name == 'ABCDEFGHIJKL'


def test_unchanged_roundtrip(radio):
    before = radio.get_mmap().get_packed()
    for n in range(1, 251):
        radio.set_memory(radio.get_memory(n))
    radio.set_settings(radio.get_settings())
    assert radio.get_mmap().get_packed() == before


def test_memmap_type():
    r = bridgecom_bcm.BCM220Radio(memmap.MemoryMapBytes(b'\x00' * 0x2810))
    assert r.get_memory(1).empty
