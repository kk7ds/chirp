# Copyright 2026 Justin Overfelt
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os
import unittest
from unittest import mock

from chirp import chirp_common, errors, memmap
from chirp.drivers import bridgecom_bcm

IMAGE = os.path.join(os.path.dirname(__file__), "..", "images",
                     "BridgeCom_BCM-220.img")


class FakeRadio:
    """Simulates the BCM-220 side of the clone protocol"""

    def __init__(self, data, answer_mode=True, corrupt=None):
        self.data = bytearray(data)
        self.answer_mode = answer_mode
        self.corrupt = corrupt
        self.rx = bytearray()
        self.tx = bytearray()
        self.mode = None
        self.block = None
        self.reset = False
        self.timeouts = []

    @property
    def timeout(self):
        return self.timeouts[-1] if self.timeouts else None

    @timeout.setter
    def timeout(self, value):
        self.timeouts.append(value)

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
                checksum = sum(chunk) & 0xFF
                if self.corrupt == 'checksum':
                    checksum ^= 0xFF
                self.tx += chunk + bytes([checksum])
                if self.corrupt == 'short':
                    del self.tx[-10:]
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


def _without_radio_state(data):
    data = bytearray(data)
    data[0x5d] = 0
    # The last channel has no padding, it ends the clone area
    for i in range(249):
        start = 0x100 + i * 40 + 28
        data[start:start + 12] = b'\x00' * 12
    return bytes(data)


class TestBCM220(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.radio = bridgecom_bcm.BCM220Radio(IMAGE)
        self.radio.status_fn = lambda s: None

    def test_image(self):
        self.assertEqual(0x2800, len(self.radio.get_mmap().get_packed()))
        used = [n for n in range(1, 251)
                if not self.radio.get_memory(n).empty]
        self.assertEqual(list(range(1, 17)), used)

    def test_download(self):
        data = self.radio.get_mmap().get_packed()
        fake = FakeRadio(data)
        self.radio.pipe = fake
        self.radio.sync_in()
        self.assertEqual(data, self.radio.get_mmap().get_packed())
        self.assertTrue(fake.reset)

    def _image_with_model(self, model):
        data = bytearray(self.radio.get_mmap().get_packed())
        data[bridgecom_bcm.MODEL_OFFSET] = model
        return bytes(data)

    def test_download_model_byte(self):
        # The test image comes from a BCM-220, which reports model 0
        self.assertEqual(
            0, self.radio.get_mmap().get_packed()[bridgecom_bcm.MODEL_OFFSET])

    def test_download_rejects_other_models(self):
        for model, name in ((1, 'BCM-144'), (2, 'BCM-440')):
            with self.subTest(model=name):
                fake = FakeRadio(self._image_with_model(model))
                self.radio.pipe = fake
                with self.assertRaises(errors.RadioError) as cm:
                    self.radio.sync_in()
                self.assertIn(name, str(cm.exception))
                self.assertIn('BCM-220', str(cm.exception))
                # The radio must still be told to reset
                self.assertTrue(fake.reset)

    def test_download_allows_unknown_model_byte(self):
        # Only the models the vendor software defines are refused
        data = self._image_with_model(0xFF)
        self.radio.pipe = FakeRadio(data)
        self.radio.sync_in()
        self.assertEqual(data, self.radio.get_mmap().get_packed())

    def test_upload(self):
        data = self.radio.get_mmap().get_packed()
        fake = FakeRadio(b'\x00' * 0x2800)
        self.radio.pipe = fake
        self.radio.sync_out()
        self.assertEqual(_without_radio_state(data),
                         bytes(fake.data))
        self.assertTrue(fake.reset)

    def test_upload_clears_radio_state(self):
        # The radio keeps its own state in 0x5d and in channel padding (e.g.
        # 0x7ff).  Writing stale values back made it drop channel 3 from the
        # in-use bitmap at power on, so uploads must zero them like the
        # vendor software does.
        image = bytearray(self.radio.get_mmap().get_packed())
        image[0x5d] = 0xd0
        image[0x7ff] = 0x06
        image[0x11e:0x120] = b'\xa0\xa8'
        radio = bridgecom_bcm.BCM220Radio(
            memmap.MemoryMapBytes(bytes(image)))
        radio.status_fn = lambda s: None
        fake = FakeRadio(b'\xff' * 0x2800)
        radio.pipe = fake
        radio.sync_out()
        self.assertEqual(0, fake.data[0x5d])
        self.assertEqual(0, fake.data[0x7ff])
        self.assertEqual(b'\x00\x00', fake.data[0x11e:0x120])
        self.assertEqual(_without_radio_state(image),
                         bytes(fake.data))

    def test_no_answer(self):
        fake = FakeRadio(b'\x00' * 0x2800, answer_mode=False)
        self.radio.pipe = fake
        self.assertRaises(errors.RadioError, self.radio.sync_in)
        # Never got into the mode, so there is nothing to reset
        self.assertFalse(fake.reset)

    def test_short_block(self):
        fake = FakeRadio(self.radio.get_mmap().get_packed(), corrupt='short')
        self.radio.pipe = fake
        self.assertRaises(errors.RadioError, self.radio.sync_in)
        self.assertTrue(fake.reset)

    def test_bad_checksum(self):
        fake = FakeRadio(self.radio.get_mmap().get_packed(),
                         corrupt='checksum')
        self.radio.pipe = fake
        self.assertRaises(errors.RadioError, self.radio.sync_in)
        self.assertTrue(fake.reset)

    def test_timeout_set_once(self):
        data = self.radio.get_mmap().get_packed()
        fake = FakeRadio(data)
        self.radio.pipe = fake
        self.radio.sync_in()
        self.assertEqual([bridgecom_bcm.TIMEOUT], fake.timeouts)
        self.assertEqual(b'', bytes(fake.tx))
        fake = FakeRadio(b'\x00' * 0x2800)
        self.radio.pipe = fake
        self.radio.sync_out()
        self.assertEqual([bridgecom_bcm.TIMEOUT], fake.timeouts)
        self.assertEqual(b'', bytes(fake.tx))

    def test_tones(self):
        m = self.radio.get_memory(16)
        self.assertEqual(('DTCS', 754, 'RR'),
                         (m.tmode, m.dtcs, m.dtcs_polarity))
        self.assertEqual(204, int(self.radio._memobj.memory[15].txtone))
        m = self.radio.get_memory(12)
        self.assertEqual(('TSQL', 100.0, 'NFM'),
                         (m.tmode, m.ctone, m.mode))

    def test_data_band_forces_data(self):
        m = chirp_common.Memory(100)
        m.freq = 219500000
        self.radio.set_memory(m)
        m = self.radio.get_memory(100)
        self.assertTrue(m.extra['data'].value)
        m.extra['data'].value = False
        self.radio.set_memory(m)
        self.assertTrue(self.radio.get_memory(100).extra['data'].value)

    def test_data_optional_in_voice_band(self):
        m = chirp_common.Memory(100)
        m.freq = 223500000
        self.radio.set_memory(m)
        self.assertFalse(self.radio.get_memory(100).extra['data'].value)

    def test_band_mismatch(self):
        m = chirp_common.Memory(100)
        m.freq = 219500000
        m.duplex = 'split'
        m.offset = 223500000
        msgs = self.radio.validate_memory(m)
        self.assertTrue(any(isinstance(x, chirp_common.ValidationError)
                            for x in msgs))

    def test_bitmaps(self):
        m = chirp_common.Memory(100)
        m.freq = 223500000
        self.radio.set_memory(m)
        _set = self.radio._memobj.settings
        self.assertTrue(_set.used[99])
        self.assertTrue(_set.scanlist[99])
        m.empty = True
        self.radio.set_memory(m)
        self.assertFalse(_set.used[99])
        self.assertFalse(_set.scanlist[99])

    def test_last_channel_name(self):
        m = chirp_common.Memory(250)
        m.freq = 223500000
        m.name = 'ABCDEFGHIJKLMNOP'
        self.radio.set_memory(m)
        self.assertEqual('ABCDEFGHIJKL', self.radio.get_memory(250).name)

    def test_unchanged_roundtrip(self):
        before = self.radio.get_mmap().get_packed()
        for n in range(1, 251):
            self.radio.set_memory(self.radio.get_memory(n))
        self.radio.set_settings(self.radio.get_settings())
        self.assertEqual(before, self.radio.get_mmap().get_packed())

    def _settings(self):
        settings = self.radio.get_settings()
        return settings, {s.get_name(): s for s in settings.walk()}

    def test_settings(self):
        settings, by_name = self._settings()
        self.assertEqual({'settings_squelch', 'settings_beeps',
                          'settings_tot', 'settings_apo',
                          'settings_cos_decode', 'settings_password',
                          'settings_scan_unmute_carrier',
                          'settings_scan_speed', 'settings_scan_hang',
                          'settings_scan_wait'}, set(by_name))

        by_name['settings_squelch'].value.set_value(5)
        by_name['settings_beeps'].value.set_value(True)
        by_name['settings_tot'].value.set_value(300)
        by_name['settings_apo'].value.set_value('12 Hours')
        by_name['settings_cos_decode'].value.set_value('DECODE')
        by_name['settings_scan_unmute_carrier'].value.set_value('CARRIER')
        by_name['settings_password'].value.set_value('abc123')
        self.radio.set_settings(settings)

        _set = self.radio._memobj.settings
        self.assertEqual(5, int(_set.squelch))
        self.assertEqual(1, int(_set.beeps))
        self.assertEqual(300, int(_set.tot))
        self.assertEqual(11, int(_set.apo))
        self.assertEqual(1, int(_set.cos_decode))
        self.assertEqual(1, int(_set.scan_unmute_carrier))
        self.assertEqual(b'abc123\x00\x00\x00\x00',
                         _set.password.get_raw())

        # and they come back the same
        _, by_name = self._settings()
        self.assertEqual(5, int(by_name['settings_squelch'].value))
        self.assertEqual('12 Hours', str(by_name['settings_apo'].value))
        self.assertEqual('CARRIER',
                         str(by_name['settings_scan_unmute_carrier'].value))
        self.assertEqual('DECODE',
                         str(by_name['settings_cos_decode'].value))
        self.assertEqual('abc123',
                         str(by_name['settings_password'].value).rstrip())

    def test_set_settings_leaves_vfo_alone(self):
        before = self.radio.get_mmap().get_packed()
        settings, by_name = self._settings()
        by_name['settings_squelch'].value.set_value(9)
        self.radio.set_settings(settings)
        after = self.radio.get_mmap().get_packed()
        changed = [i for i in range(len(before)) if before[i] != after[i]]
        self.assertEqual([0x0d], changed)

    def test_memmap_type(self):
        r = bridgecom_bcm.BCM220Radio(
            memmap.MemoryMapBytes(b'\x00' * 0x2800))
        self.assertTrue(r.get_memory(1).empty)
