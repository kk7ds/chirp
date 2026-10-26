from pathlib import Path
import unittest

from chirp import memmap
from chirp.drivers import vx8


FIXTURE = Path(__file__).parents[1] / 'images' / 'Yaesu_VX-8GE.img'

FLAG_BASE = 0x2C4A
MEMORY_BASE = 0x328A
MEMORY_SIZE = 32

# Values observed in a real-world VX-8GE image for channels programmed
# from the radio's keypad, which CHIRP could not previously load: the
# radio's "AUTO" RX mode is stored as mode bits == 3, which is out of
# range for the driver's MODES list, and a keypad-entered split
# transmit frequency is rounded to the 1kHz resolution of the offset
# field, leaving it unaligned to any tuning step.
FLAG_USED_VALID = 0x03
MODE_AUTO = 0xC0        # mode (3) | duplex (0) | tune step (0)
MODE_AUTO_SPLIT = 0xF0  # mode (3) | duplex (3, split) | tune step (0)
FREQ_4625625 = b'\x46\x25\x62'  # 462.5625 MHz, as stored by the radio
OFFSET_5000K = b'\x00\x50\x00'   # 5 MHz
OFFSET_159007 = b'\x15\x90\x07'  # 159.007 MHz, not aligned to any step
NAME_KEYPAD = b'\x14\x0e\x22\x19\x0a\x0d'  # "KEYPAD" in the VX-8 charset


class TestVX8(unittest.TestCase):
    def setUp(self):
        self.radio = vx8.VX8GERadio(str(FIXTURE))
        self.data = self.radio.get_mmap().get_packed()
        self.number = self.radio.get_features().memory_bounds[1]

    def _radio_with_keypad_memory(self, mode_byte, offset_bytes):
        data = bytearray(self.data)
        number = self.number
        data[FLAG_BASE + number - 1] = FLAG_USED_VALID
        base = MEMORY_BASE + (number - 1) * MEMORY_SIZE
        data[base] = 0x00
        data[base + 1] = mode_byte
        data[base + 2:base + 5] = FREQ_4625625
        data[base + 5] = 0xC0  # power | tone mode
        data[base + 6:base + 8] = b'\x00\x00'  # charset bits
        data[base + 8:base + 24] = NAME_KEYPAD + b'\xFF' * 10
        data[base + 24:base + 27] = offset_bytes
        data[base + 27:base + 32] = b'\x00\x00\x00\x00\x00'
        return vx8.VX8GERadio(memmap.MemoryMapBytes(bytes(data)))

    def test_all_memories_load(self):
        for number in range(*self.radio.get_features().memory_bounds):
            self.radio.get_memory(number)

    def test_auto_mode_coerced_to_fm(self):
        radio = self._radio_with_keypad_memory(MODE_AUTO, OFFSET_5000K)
        mem = radio.get_memory(self.number)
        self.assertFalse(mem.empty)
        self.assertEqual(mem.mode, 'FM')
        self.assertEqual(mem.freq, 462562500)
        self.assertEqual(mem.name, 'KEYPAD')

    def test_uncorrectable_split_offset_loads(self):
        radio = self._radio_with_keypad_memory(MODE_AUTO_SPLIT,
                                               OFFSET_159007)
        mem = radio.get_memory(self.number)
        self.assertFalse(mem.empty)
        self.assertEqual(mem.mode, 'FM')
        self.assertEqual(mem.duplex, 'split')
        self.assertEqual(mem.offset, 159007000)
