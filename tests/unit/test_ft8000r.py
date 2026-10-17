from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from chirp import chirp_common, directory, errors, memmap
from chirp.drivers import ft8000r


FIXTURE = Path(__file__).parents[1] / 'images' / 'Yaesu_FT-8000R.img'


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Port:
    def __init__(self, clock, data=b'', echo=True, short=False, corrupt=False):
        self.clock = clock
        self.pending = bytearray(data)
        self.echo = echo
        self.short = short
        self.corrupt = corrupt
        self.writes = []

    @property
    def in_waiting(self):
        return len(self.pending)

    def read(self, count):
        if not self.pending:
            self.clock.sleep(0.1)
        # Force fragmented reads, including a header split across reads.
        count = min(count, 3)
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def write(self, data):
        self.writes.append(data)
        if self.short:
            return 0
        if self.echo:
            self.pending.extend(bytes([data[0] ^ 1]) if self.corrupt else data)
        return len(data)

    def flush(self):
        pass


class TestFT8000R(unittest.TestCase):
    def setUp(self):
        self.radio = ft8000r.FT8000RRadio(str(FIXTURE))
        self.data = self.radio.get_mmap().get_packed()
        self.left, self.right = self.radio.get_sub_devices()
        self.clock = Clock()
        self.time = mock.patch.object(ft8000r, 'time', SimpleNamespace(
            monotonic=self.clock.monotonic, sleep=self.clock.sleep))
        self.time.start()
        self.addCleanup(self.time.stop)
        self.status = []
        self.radio.status_fn = self.status.append

    def test_hardware_fixture_and_subdevices(self):
        self.assertEqual(self.data[-1], 0x88)
        self.assertTrue(self.radio.get_features().has_sub_devices)
        self.assertFalse(self.left.get_features().has_sub_devices)
        self.assertEqual(self.left.get_features().memory_bounds, (1, 50))
        self.assertEqual(self.left.get_memory(1).freq, 146440000)
        self.assertEqual(self.right.get_memory(1).freq, 439800000)
        self.assertEqual(self.left.get_memory(13).mode, 'AM')
        self.assertEqual(self.left.get_memory(4).duplex, '+')
        self.assertEqual(self.left.get_memory(4).offset, 600000)
        self.assertEqual(self.right.get_memory(1).duplex, '-')
        self.assertEqual(self.right.get_memory(1).offset, 5000000)
        self.assertEqual(sum(not self.left.get_memory(i).empty
                             for i in range(1, 51)), 13)
        self.assertEqual(sum(not self.right.get_memory(i).empty
                             for i in range(1, 51)), 3)

    def test_noop_roundtrip_is_byte_identical(self):
        for child in (self.left, self.right):
            for number in range(1, 51):
                memory = child.get_memory(number)
                if not memory.empty:
                    child.set_memory(memory)
        self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_two_frequency_edits_and_working_records_share_parent_map(self):
        shared = self.radio.get_mmap()
        for child, freq in [(self.left, 146420000), (self.right, 439780000)]:
            memory = child.get_memory(1)
            memory.freq = freq
            child.set_memory(memory)
        changed = shared.get_packed()
        self.assertIs(self.left.get_mmap(), shared)
        self.assertIs(self.right.get_mmap(), shared)
        self.assertEqual(changed[0x409:0x412], bytes.fromhex(
            '00 08 16 57 88 00 17 70 00'))
        self.assertEqual(changed[0x21F:0x228], bytes.fromhex(
            '20 4c 43 1a e8 00 c3 50 00'))
        self.assertEqual(changed[0x121:0x12A], changed[0x409:0x412])
        self.assertEqual(changed[0x21:0x2A], changed[0x21F:0x228])
        allowed = {0x21, 0x24, 0x25, 0x124, 0x125, 0x21F, 0x222,
                   0x223, 0x40C, 0x40D, 0x743}
        self.assertEqual({i for i, (a, b) in enumerate(zip(self.data, changed))
                          if a != b}, allowed)
        ft8000r.validate_image(changed)

    def test_other_working_record_preserved(self):
        data = bytearray(self.data)
        data[0x122] ^= 1
        data[-1] = ft8000r.checksum(data)
        self.radio = ft8000r.FT8000RRadio(memmap.MemoryMapBytes(bytes(data)))
        left = self.radio.get_sub_devices()[0]
        memory = left.get_memory(1)
        memory.freq = 146420000
        left.set_memory(memory)
        self.assertEqual(left.get_mmap()[0x121:0x12A],
                         bytes(data[0x121:0x12A]))

    def test_ambiguous_working_copy_rejected_without_mutation(self):
        data = bytearray(self.data)
        data[0x412:0x41B] = data[0x409:0x412]
        data[-1] = ft8000r.checksum(data)
        left = ft8000r.FT8000RLeftRadio(memmap.MemoryMapBytes(bytes(data)))
        memory = left.get_memory(1)
        memory.freq = 146420000
        with self.assertRaisesRegex(errors.InvalidValueError, 'ambiguous'):
            left.set_memory(memory)
        self.assertEqual(left.get_mmap().get_packed(), bytes(data))

    def test_unsupported_edits_do_not_mutate_image(self):
        memory = self.left.get_memory(1)
        memory.immutable = []
        memory.tmode = 'DTCS'
        with self.assertRaises(errors.InvalidValueError):
            self.left.set_memory(memory)
        for freq in (439800000, 146441001, 146441000):
            memory = self.left.get_memory(1)
            memory.freq = freq
            with self.assertRaises(errors.InvalidValueError):
                self.left.set_memory(memory)
        self.assertEqual(self.radio.get_mmap().get_packed(), self.data)

    def test_tone_power_and_skip_from_vendor_record(self):
        memory = self.right.get_memory(1)
        self.assertEqual(memory.tmode, 'Tone')
        self.assertEqual(memory.rtone, 100.0)
        self.assertEqual(str(memory.power), 'High')
        self.assertEqual(memory.skip, '')
        self.assertFalse(self.right.get_features().has_dtcs)
        self.assertEqual(len(self.right.get_features().valid_tones), 39)

    def test_validation_rejects_unsupported_grid_before_import(self):
        memory = self.right.get_memory(1)
        memory.freq = 433006000
        messages = self.right.validate_memory(memory)
        self.assertTrue(any(isinstance(m, chirp_common.ValidationError)
                            for m in messages))
        self.assertEqual(self.right.filter_name('Unsupported name'), '')

    def test_uhf_five_khz_ending_matches_vendor_grid_code(self):
        memory = self.right.get_memory('HOME')
        memory.freq = 433005000
        self.right.set_memory(memory)
        raw = self.right.get_mmap()[0x33:0x3C]
        self.assertEqual(raw[0] & 3, 1)
        self.assertEqual(raw[2:5], (4330050).to_bytes(3, 'big'))
        self.assertEqual(self.right.get_memory('HOME').freq, 433005000)

    def test_factory_home_duplicate_does_not_block_regular_memory_edit(self):
        data = bytearray(self.data)
        data[0x133:0x13C] = data[0x409:0x412]
        data[-1] = ft8000r.checksum(data)
        left = ft8000r.FT8000RLeftRadio(memmap.MemoryMapBytes(bytes(data)))
        memory = left.get_memory(1)
        memory.freq = 146460000
        left.set_memory(memory)
        self.assertEqual(left.get_memory(1).freq, 146460000)
        self.assertEqual(left.get_memory('VFO').freq, 146460000)
        self.assertEqual(left.get_memory('HOME').freq, 146440000)

    def test_new_memory_all_fields_literal_vendor_encoding(self):
        memory = self.left.get_memory(50)
        memory.empty = False
        memory.freq = 146520000
        memory.duplex = '-'
        memory.offset = 600000
        memory.tmode = 'TSQL'
        memory.rtone = 123.0
        memory.mode = 'AM'
        memory.skip = 'S'
        memory.power = self.left.get_features().valid_power_levels[2]
        old = self.radio.get_mmap().get_packed()
        self.left.set_memory(memory)
        offset = 0x409 + 49 * 9
        raw = self.radio.get_mmap()[offset:offset + 9]
        self.assertEqual(raw, bytes.fromhex('60 d2 16 5b 70 00 17 70 82'))
        actual = self.left.get_memory(50)
        for field in ('freq', 'duplex', 'offset', 'tmode', 'rtone',
                      'mode', 'skip', 'power', 'empty'):
            self.assertEqual(getattr(actual, field), getattr(memory, field))
        self.assertEqual(self.radio.get_mmap()[0x121:0x12A], old[0x121:0x12A])
        self.left.set_memory(actual)
        ft8000r.validate_image(self.radio.get_mmap().get_packed())
        actual.empty = True
        self.left.set_memory(actual)
        self.assertTrue(self.left.get_memory(50).empty)
        ft8000r.validate_image(self.radio.get_mmap().get_packed())

    def test_offset_split_and_working_copy_sync(self):
        memory = self.right.get_memory(1)
        memory.duplex = 'split'
        memory.offset = 434812500
        self.right.set_memory(memory)
        data = self.radio.get_mmap().get_packed()
        self.assertEqual(data[0x21F] & 0x3F, 0x35)
        self.assertEqual(ft8000r.decode_frequency(data[0x224:0x227]),
                         434812500)
        self.assertEqual(data[0x21:0x2A], data[0x21F:0x228])
        self.assertEqual(self.right.get_memory(1).offset, 434812500)

    def test_unrelated_edits_preserve_reserved_tone_and_power_bits(self):
        data = bytearray(self.data)
        # Unknown tone index/mode, bell/unknown flags and reserved power code.
        data[0x40A] = 0xBF
        data[0x411] = 0xFD
        data[-1] = ft8000r.checksum(data)
        left = ft8000r.FT8000RLeftRadio(memmap.MemoryMapBytes(bytes(data)))
        memory = left.get_memory(1)
        left.set_memory(memory)
        self.assertEqual(left.get_mmap().get_packed(), bytes(data))
        memory.skip = 'S'
        left.set_memory(memory)
        self.assertEqual(left.get_mmap()[0x40A], b'\xbf')
        self.assertEqual(left.get_mmap()[0x411], b'\xfd')
        self.assertEqual(left.get_mmap()[0x409], bytes([data[0x409] | 0x40]))

    def test_deleting_active_memory_preserves_live_vfo(self):
        memory = self.left.get_memory(1)
        memory.empty = True
        self.left.set_memory(memory)
        self.assertTrue(self.left.get_memory(1).empty)
        self.assertEqual(self.radio.get_mmap()[0x121:0x12A],
                         self.data[0x121:0x12A])

    def test_special_memories_addresses_and_noop(self):
        for child, addresses in [
                (self.left, [0x5CB, 0x5D4, 0x5DD, 0x5E6, 0x133, 0x121]),
                (self.right, [0x3E1, 0x3EA, 0x3F3, 0x3FC, 0x33, 0x21])]:
            locations = zip(ft8000r.SPECIALS, addresses)
            for i, (name, address) in enumerate(locations):
                self.assertEqual(child._record_offset(name), address)
                memory = child.get_memory(name)
                self.assertEqual(memory.number, 51 + i)
                self.assertEqual(memory.extd_number, name)
                child.set_memory(memory)
        self.assertEqual(self.radio.get_mmap().get_packed(), self.data)
        vfo = self.left.get_memory('VFO')
        vfo.freq = 146460000
        self.left.set_memory(vfo)
        self.assertEqual(self.left.get_memory('VFO').freq, 146460000)
        self.assertEqual(self.left.get_memory(1).freq, 146440000)

    def test_bell_and_mask_only_change_known_bits(self):
        memory = self.right.get_memory(1)
        memory.tmode = 'TSQL'
        memory.extra['bell'].value = True
        memory.extra['masked'].value = True
        self.right.set_memory(memory)
        raw = self.radio.get_mmap().get_packed()[0x21F:0x228]
        self.assertEqual(raw, bytes.fromhex('a5 cc 43 1b b0 00 c3 50 04'))
        actual = self.right.get_memory(1)
        self.assertFalse(actual.empty)
        self.assertTrue(bool(actual.extra['bell'].value))
        self.assertTrue(bool(actual.extra['masked'].value))
        actual.tmode = 'Tone'
        self.right.set_memory(actual)
        self.assertFalse(bool(self.right.get_memory(1).extra['bell'].value))

    def test_all_tones_and_power_choices(self):
        for child in (self.left, self.right):
            for mode in ft8000r.TMODES:
                for tone in ft8000r.TONES:
                    memory = child.get_memory(2)
                    memory.tmode = mode
                    memory.rtone = tone
                    child.set_memory(memory)
                    actual = child.get_memory(2)
                    self.assertEqual((actual.tmode, actual.rtone),
                                     (mode, tone))
            for power in child.get_features().valid_power_levels:
                memory = child.get_memory(2)
                memory.power = power
                child.set_memory(memory)
                self.assertEqual(child.get_memory(2).power, power)

    def test_settings_noop_preserves_unknown_and_noncanonical_values(self):
        for original in (self.data, bytes([0xFF]) * 1860):
            data = bytearray(original)
            data[:5] = ft8000r.HEADER
            data[-1] = ft8000r.checksum(data)
            radio = ft8000r.FT8000RRadio(memmap.MemoryMapBytes(bytes(data)))
            settings = radio.get_settings()
            radio.set_settings(settings)
            self.assertEqual(radio.get_mmap().get_packed(), bytes(data))

    def test_settings_change_exact_bits_and_dtmf_encoding(self):
        settings = self.radio.get_settings()
        common, dtmf = settings
        common['key_beep'].value = False
        common['tot'].value = '5 minute(s)'
        common['right_rf_sql'].value = 'Full scale'
        common['right_scan'].value = '5 seconds'
        common['volts_offset'].value = '-0.066 V'
        dtmf['left_dtmf'].value = '12ABCD*#P0'
        self.radio.set_settings(settings)
        data = self.radio.get_mmap().get_packed()
        self.assertEqual(data[0xB], self.data[0xB] | 0x40)
        self.assertEqual(data[0xD:0xF], b'\x01\x2c')
        self.assertEqual(data[0x75], 11)
        self.assertEqual(data[0x1D], self.data[0x1D] | 0x10)
        self.assertEqual(data[0x13], 0xFF)
        self.assertEqual(data[0x143:0x154], bytes.fromhex(
            '0a 01 02 0a 0b 0c 0d 0e 0f 10 00 10 10 10 10 10 10'))
        after = self.radio.get_settings()
        self.assertEqual(str(after[1]['left_dtmf'].value), '12ABCD*#P0')
        self.assertEqual(str(after[0]['tot'].value), '5 minute(s)')
        allowed = {0xB, 0xD, 0xE, 0x13, 0x75, 0x1D, 0x743}
        allowed.update(range(0x143, 0x154))
        self.assertTrue({i for i, (a, b) in enumerate(zip(self.data, data))
                         if a != b} <= allowed)
        ft8000r.validate_image(data)

    def test_subband_operation_does_not_change_receive_mode(self):
        for index in (1, 2, 0):
            settings = self.radio.get_settings()
            settings[0]['sub_operation'].value = index
            self.radio.set_settings(settings)
            data = self.radio.get_mmap().get_packed()
            self.assertEqual(data[0xB] & ~2, self.data[0xB] & ~2)
            self.assertEqual(data[0xC] & ~2, self.data[0xC] & ~2)
            self.assertEqual(int(self.radio.get_settings()[0][
                'sub_operation'].value), index)

    def test_save_and_reopen_with_chirp_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'radio.img')
            self.radio.save(path)
            loaded = directory.get_radio_by_image(path)
            self.assertIsInstance(loaded, ft8000r.FT8000RRadio)
            self.assertEqual(loaded.MODEL, 'FT-8000R')
            self.assertEqual(loaded.get_mmap().get_packed(), self.data)
        # No loose raw-image autodetection by checksum/size alone.
        self.assertFalse(ft8000r.FT8000RRadio.match_model(
            self.data, 'unknown.img'))

    def test_early_development_image_model_name_still_loads(self):
        class EarlyFT8000(ft8000r.FT8000RRadio):
            MODEL = 'FT-8000'

        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'legacy.img')
            radio = EarlyFT8000(memmap.MemoryMapBytes(self.data))
            radio.save(path)
            loaded = directory.get_radio_by_image(path)
            self.assertIsInstance(loaded, ft8000r.FT8000RRadio)
            self.assertEqual(loaded.MODEL, 'FT-8000')
            self.assertTrue(all(device.MODEL == 'FT-8000'
                                for device in loaded.get_sub_devices()))
            self.assertEqual(loaded.get_mmap().get_packed(), self.data)

    def test_download_passive_fragmented_with_retained_prefix_metadata(self):
        port = Port(self.clock, data=b'\x00\xfc' + self.data)
        radio = ft8000r.FT8000RRadio(port)
        radio.status_fn = self.status.append
        radio.sync_in()
        self.assertEqual(radio.get_mmap().get_packed(), self.data)
        self.assertEqual(radio.metadata['ft8000_download_prefix'], '00fc')
        self.assertEqual(port.writes, [])
        self.assertEqual((port.stopbits, port.dtr, port.rts), (2, False, True))
        self.assertEqual(self.status[-1].cur, 1860)

    def test_corrupt_or_partial_download_not_installed(self):
        corrupt = bytearray(self.data)
        corrupt[-1] ^= 1
        for data in (bytes(corrupt), self.data[:100], b'', b'X' * 100):
            with self.subTest(size=len(data)):
                port = Port(self.clock, data=data)
                radio = ft8000r.FT8000RRadio(port)
                radio.status_fn = self.status.append
                with self.assertRaises(errors.RadioError):
                    radio.sync_in()
                self.assertIsNone(radio.get_mmap())
                self.assertEqual(port.writes, [])

    def test_upload_exact_one_byte_writes_echo_and_completion(self):
        port = Port(self.clock)
        self.radio.set_pipe(port)
        self.radio.sync_out()
        self.assertEqual(b''.join(port.writes), self.data + b'\x06')
        self.assertTrue(all(len(chunk) == 1 for chunk in port.writes))
        self.assertGreaterEqual(self.clock.now, 18.8)
        self.assertEqual(port.in_waiting, 0)
        self.assertEqual((port.stopbits, port.dtr, port.rts), (2, False, True))

    def test_upload_bad_echo_or_short_write_stops_at_first_byte(self):
        for options in ({'echo': False}, {'corrupt': True}, {'short': True}):
            with self.subTest(options=options):
                port = Port(self.clock, **options)
                self.radio.set_pipe(port)
                with self.assertRaises(errors.RadioError):
                    self.radio.sync_out()
                self.assertEqual(port.writes, [self.data[:1]])

    def test_chirp_serialtrace_style_missing_write_count_requires_echo(self):
        class TracePort(Port):
            def write(self, data):
                super().write(data)
                # Same return behavior as wxui.serialtrace.SerialTrace.
                return None
        for echo in (True, False):
            port = TracePort(self.clock, echo=echo)
            self.radio.set_pipe(port)
            if echo:
                self.radio.sync_out()
                self.assertEqual(b''.join(port.writes), self.data + b'\x06')
            else:
                with self.assertRaises(errors.RadioError):
                    self.radio.sync_out()
                self.assertEqual(port.writes, [self.data[:1]])

    def test_invalid_image_or_unexpected_preflight_rx_never_sends(self):
        port = Port(self.clock, data=b'\x06')
        self.radio.set_pipe(port)
        with self.assertRaises(errors.RadioError):
            self.radio.sync_out()
        self.assertEqual(port.writes, [])
        self.radio.get_mmap()[1859] = self.data[-1] ^ 1
        self.radio.pipe = None
        with self.assertRaisesRegex(errors.RadioError, 'checksum'):
            self.radio.sync_out()
