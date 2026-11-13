from pathlib import Path
import struct
import unittest

from chirp import chirp_common, errors, memmap
from chirp.drivers import retevis_rt21


FIXTURE = Path(__file__).parents[1] / 'images' / 'Retevis_RT97L.img'


class FakeRT97L:
    """Simulated RT97L clone interface backed by a 256-byte image."""

    def __init__(self, data, ident=b'P32073\x01\xFF'):
        self.memory = bytearray(data)
        self.ident = ident
        self.pending = bytearray()
        self.inbuf = bytearray()
        self.last_read = None
        self.reads = []
        self.writes = []

    def read(self, count):
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def write(self, data):
        self.inbuf.extend(data)
        while self.inbuf:
            if not self._handle():
                break

    def _handle(self):
        buf = self.inbuf
        if buf.startswith(b'PHOGR\x92\x25'):
            del buf[:7]
            self.pending.extend(b'\x06')
        elif buf[:1] == b'\x02':
            del buf[:1]
            self.pending.extend(self.ident)
        elif buf[:1] == b'\x06':
            del buf[:1]
            # No ACK is sent after block 0x0000
            assert self.last_read != 0, 'ACK sent after block 0'
            self.pending.extend(b'\x06')
        elif buf[:1] == b'R' and len(buf) >= 4:
            addr, size = struct.unpack('>HB', bytes(buf[1:4]))
            del buf[:4]
            self.reads.append((addr, size))
            self.last_read = addr
            self.pending.extend(b'W' + struct.pack('>HB', addr, size) +
                                self.memory[addr:addr + size])
        elif buf[:1] == b'W' and len(buf) >= 4:
            addr, size = struct.unpack('>HB', bytes(buf[1:4]))
            if len(buf) < 4 + size:
                return False
            self.memory[addr:addr + size] = buf[4:4 + size]
            del buf[:4 + size]
            self.writes.append((addr, size))
            self.pending.extend(b'\x06')
        elif buf[:1] == b'E':
            del buf[:1]
            self.pending.extend(b'\x06')
        else:
            raise AssertionError('Unexpected bytes %r' % bytes(buf))
        return True


class TestRT97L(unittest.TestCase):
    def setUp(self):
        self.radio = retevis_rt21.RT97LRadio(str(FIXTURE))
        self.data = self.radio.get_mmap().get_packed()

    def _byte(self, offset):
        return self.radio.get_mmap().get_packed()[offset]

    def test_download_reads_whole_image(self):
        port = FakeRT97L(self.data)
        radio = retevis_rt21.RT97LRadio(port)
        radio.status_fn = lambda s: None
        radio.sync_in()
        self.assertEqual([(a, 0x20) for a in range(0, 0x100, 0x20)],
                         port.reads)
        self.assertEqual(self.data, radio.get_mmap().get_packed())

    def test_upload_writes_every_block_in_order(self):
        port = FakeRT97L(b'\x00' * 0x100)
        self.radio.set_pipe(port)
        self.radio.status_fn = lambda s: None
        self.radio.sync_out()
        self.assertEqual([(a, 0x10) for a in range(0, 0x100, 0x10)],
                         port.writes)
        self.assertEqual(self.data, bytes(port.memory))

    def test_upload_refuses_short_image(self):
        port = FakeRT97L(b'\x00' * 0x100)
        radio = retevis_rt21.RT97LRadio(
            memmap.MemoryMapBytes(self.data[:0xF0]))
        radio.set_pipe(port)
        radio.status_fn = lambda s: None
        self.assertRaises(errors.RadioError, radio.sync_out)
        self.assertEqual(b'', bytes(port.inbuf))
        self.assertEqual([], port.writes)

    def test_upload_wrong_radio_writes_nothing(self):
        port = FakeRT97L(b'\x00' * 0x100, ident=b'P32073\x02\xFF')
        self.radio.set_pipe(port)
        self.radio.status_fn = lambda s: None
        self.assertRaises(errors.RadioError, self.radio.sync_out)
        self.assertEqual([], port.writes)

    def test_channel_13_power_and_mode_keep_audio_output(self):
        audio = self._byte(0xCC)
        mem = self.radio.get_memory(13)
        self.assertIn('power', mem.immutable)
        self.assertIn('mode', mem.immutable)
        # Imported memories carry no immutable fields
        new = chirp_common.Memory(13)
        new.freq = 467700000
        new.duplex = '-'
        new.offset = 5000000
        new.power = self.radio.POWER_LEVELS[0]
        new.mode = 'FM'
        self.radio.set_memory(new)
        self.assertEqual(audio, self._byte(0xCC))
        self.assertEqual(467700000, self.radio.get_memory(13).freq)

    def test_channel_13_from_empty_warns_and_keeps_audio_output(self):
        audio = self._byte(0xCC)
        mem = self.radio.get_memory(13)
        mem.empty = True
        self.radio.set_memory(mem)
        mem = self.radio.get_memory(13)
        self.assertTrue(mem.empty)
        self.assertIn('power', mem.immutable)
        self.assertIn('mode', mem.immutable)
        new = chirp_common.Memory(13)
        new.freq = 467650000
        new.power = self.radio.POWER_LEVELS[0]
        new.mode = 'FM'
        warnings, errs = chirp_common.split_validation_msgs(
            self.radio.validate_memory(new))
        self.assertEqual([], errs)
        self.assertEqual(1, len(warnings))
        self.radio.set_memory(new)
        self.assertEqual(audio, self._byte(0xCC))
        mem = self.radio.get_memory(13)
        self.assertEqual('Low', str(mem.power))
        self.assertEqual('NFM', mem.mode)

    def test_delete_keeps_settings_bytes(self):
        before = self.radio.get_mmap().get_packed()
        for number in (3, 13):
            mem = self.radio.get_memory(number)
            mem.empty = True
            self.radio.set_memory(mem)
        after = self.radio.get_mmap().get_packed()
        for number in (3, 13):
            base = (number - 1) * 0x10
            self.assertEqual(b'\xFF' * 12, after[base:base + 12])
            self.assertEqual(before[base + 12:base + 16],
                             after[base + 12:base + 16])
        self.assertTrue(self.radio.get_memory(3).empty)

    def test_set_keeps_settings_bytes(self):
        before = self.radio.get_mmap().get_packed()
        for number in (3, 5, 8):
            mem = self.radio.get_memory(number)
            mem.freq = 467700000
            self.radio.set_memory(mem)
        after = self.radio.get_mmap().get_packed()
        for number in (3, 5, 8):
            base = (number - 1) * 0x10
            self.assertEqual(before[base + 13:base + 16],
                             after[base + 13:base + 16])

    def test_skip_is_scan_add_bit(self):
        before = self.radio.get_mmap().get_packed()
        mem = self.radio.get_memory(5)
        mem.skip = ''
        self.radio.set_memory(mem)
        self.assertEqual(0x10, self._byte(0x4E))
        mem.skip = 'S'
        self.radio.set_memory(mem)
        self.assertEqual(before, self.radio.get_mmap().get_packed())

    def test_set_keeps_unmapped_flag_bits(self):
        mem = self.radio.get_memory(1)
        mem.power = self.radio.POWER_LEVELS[1]
        mem.mode = 'NFM'
        self.radio.set_memory(mem)
        # Factory 0x38 with power and wide cleared leaves bit 3
        self.assertEqual(0x08, self._byte(0x0C))

    def test_new_record_starts_from_factory_flags(self):
        mmap = self.radio.get_mmap()
        mmap[0x10] = b'\xFF' * 13
        new = chirp_common.Memory(2)
        new.freq = 467575000
        new.power = self.radio.POWER_LEVELS[0]
        new.mode = 'FM'
        self.radio.set_memory(new)
        self.assertEqual(0x38, self._byte(0x1C))

    def test_tx_off_is_zeros(self):
        mem = self.radio.get_memory(2)
        mem.duplex = 'off'
        self.radio.set_memory(mem)
        self.assertEqual(b'\x00' * 4,
                         self.radio.get_mmap().get_packed()[0x14:0x18])
        self.assertEqual('off', self.radio.get_memory(2).duplex)

    def test_unchanged_settings_change_nothing(self):
        mmap = self.radio.get_mmap()
        mmap[0xCC] = 0x38  # out of range, shown as 5
        before = mmap.get_packed()
        self.radio.set_settings(self.radio.get_settings())
        self.assertEqual(before, self.radio.get_mmap().get_packed())

    def test_settings(self):
        settings = self.radio.get_settings()
        values = {s.get_name(): s for s in settings.walk()}
        self.assertEqual(9, int(values['rt97l_audio.audio'].value))
        self.assertEqual(3, int(values['rt97l_audio.channel'].value))
        values['rt97l_audio.audio'].value = 4
        values['rt97l_audio.channel'].value = 16
        values['rt97l_relay.relay'].value = False
        self.radio.set_settings(settings)
        self.assertEqual(4, self._byte(0xCC))
        self.assertEqual(15, self._byte(0xCE))
        self.assertEqual(0, self._byte(0x7F))

    def test_image_is_256_bytes(self):
        self.assertEqual(0x100, len(self.data))
        self.assertIsInstance(self.radio.get_mmap(), memmap.MemoryMapBytes)
