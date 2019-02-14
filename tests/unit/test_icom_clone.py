# Copyright 2019 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from builtins import bytes

import glob
import os
import logging
import unittest

from chirp import directory
directory.safe_import_drivers()
from chirp.drivers import icf
from chirp import memmap
from tests import icom_clone_simulator


class BaseIcomCloneTest():
    def setUp(self):
        self.radio = directory.get_radio(self.RADIO_IDENT)(None)
        self.simulator = icom_clone_simulator.FakeIcomRadio(self.radio)
        self.radio.set_pipe(self.simulator)

    def image_filename(self, filename):
        tests_base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(tests_base, 'images', filename)

    def load_from_test_image(self, filename):
        self.simulator.load_from_file(self.image_filename(filename))

    def image_version(self, filename):
        end = self.radio.get_memsize()

        with open(self.image_filename(filename), 'rb') as f:
            data = f.read()
        if data[-8:-6] == b'%02x' % self.radio.get_model()[0]:
            return 2
        elif data[end-16:end] == b'IcomCloneFormat3':
            return 3


    def test_sync_in(self):
        test_file = self.IMAGE_FILE
        self.load_from_test_image(test_file)
        self.radio.sync_in()

        img_ver = self.image_version(test_file)
        if img_ver == 2:
            endstring = b''.join(b'%02x' % ord(c)
                                 for c in self.radio._model[:2])
            self.assertEqual(endstring + b'0001', self.radio._mmap[-8:])
        elif img_ver == 3:
            self.assertEqual(b'IcomCloneFormat3', self.radio._mmap[-16:])
        elif img_ver is None:
            self.assertEqual(self.radio.get_memsize(), len(self.radio._mmap))

    def test_sync_out(self):
        self.radio._mmap = memmap.MemoryMapBytes(
            bytes(b'\x00') * self.radio.get_memsize())
        self.radio._mmap[50] = bytes(b'abcdefgh')
        self.radio.sync_out()
        self.assertEqual(b'abcdefgh', self.simulator._memory[50:58])


class TestRawRadioData(unittest.TestCase):
    def test_get_payload(self):
        radio = directory.get_radio('Icom_IC-2730A')(None)
        payload = radio.get_payload(bytes(b'\x00\x10\xFE\x00'), True, True)
        self.assertEqual(b'\x00\x10\xFF\x0E\x00\xF2', payload)

        payload = radio.get_payload(bytes(b'\x00\x10\xFE\x00'), True, False)
        self.assertEqual(b'\x00\x10\xFF\x0E\x00', payload)

    def test_process_frame_payload(self):
        radio = directory.get_radio('Icom_IC-2730A')(None)
        data = radio.process_frame_payload(bytes(b'\x00\x10\xFF\x0E\x00'))
        self.assertEqual(b'\x00\x10\xFE\x00', data)


class TestAdapterMeta(type):
    def __new__(cls, name, parents, dct):
        return super(TestAdapterMeta, cls).__new__(cls, name, parents, dct)


test_file_glob = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'images',
                              'Icom_*.img')
import sys
for image_file in glob.glob(test_file_glob):
    base, _ext = os.path.splitext(os.path.basename(image_file))

    try:
        radio = directory.get_radio(base)
    except Exception:
        continue

    if issubclass(radio, icf.IcomRawCloneModeRadio):
        # The simulator does not behave like a raw radio
        continue

    class_name = 'Test_%s' % base
    sys.modules[__name__].__dict__[class_name] = \
        TestAdapterMeta(class_name,
                        (BaseIcomCloneTest, unittest.TestCase),
                        dict(RADIO_IDENT=base, IMAGE_FILE=image_file))
