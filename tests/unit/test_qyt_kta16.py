import os
import tempfile
import unittest

from chirp import chirp_common
from chirp.drivers import qyt_kta16


IMAGE = os.path.join(
    os.path.dirname(__file__), "..", "images", "QYT_KT-A16.img")


class QYTKTA16ImageTest(unittest.TestCase):
    def setUp(self):
        self.radio = qyt_kta16.QYTKTA16Radio(IMAGE)

    def test_decode(self):
        channel = self.radio.get_memory(0)
        self.assertEqual(121500000, channel.freq)
        self.assertEqual("AM", channel.mode)

        weather = self.radio.get_memory(190)
        self.assertEqual(162550000, weather.freq)
        self.assertEqual("WX01", weather.name)
        self.assertEqual("FM", weather.mode)

    def test_memory_round_trip(self):
        channel = chirp_common.Memory(7)
        channel.freq = 119208330
        channel.name = "TEST-1"
        channel.skip = "S"
        self.radio.set_memory(channel)

        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "round-trip.img")
            self.radio.save(image)
            decoded = qyt_kta16.QYTKTA16Radio(image).get_memory(7)

        self.assertEqual(119208330, decoded.freq)
        self.assertEqual("TEST-1", decoded.name)
        self.assertEqual("S", decoded.skip)
        self.assertEqual("", decoded.duplex)
        self.assertEqual(0, decoded.offset)
        self.assertEqual("AM", decoded.mode)

    def test_frequency_validation(self):
        channel = chirp_common.Memory(7)
        channel.freq = 119210000
        channel.mode = "AM"
        messages = self.radio.validate_memory(channel)
        self.assertEqual(1, len(messages))
        self.assertIn("actual carrier frequency", str(messages[0]))

        channel.freq = 119208330
        self.assertEqual([], self.radio.validate_memory(channel))


if __name__ == "__main__":
    unittest.main()
