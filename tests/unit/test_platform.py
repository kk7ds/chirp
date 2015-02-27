# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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

import unittest
import mox
import os

from tests.unit import base
from chirp import platform


class Win32PlatformTest(base.BaseTest):
    def _test_init(self):
        self.mox.StubOutWithMock(platform, 'comports')
        self.mox.StubOutWithMock(os, 'mkdir')
        self.mox.StubOutWithMock(os, 'getenv')
        os.mkdir(mox.IgnoreArg())
        os.getenv("APPDATA").AndReturn("foo")
        os.getenv("USERPROFILE").AndReturn("foo")

    def test_init(self):
        self._test_init()
        self.mox.ReplayAll()
        platform.Win32Platform()

    def test_serial_ports_sorted(self):
        self._test_init()

        fake_comports = []
        numbers = [1, 11, 2, 12, 7, 3, 123]
        for i in numbers:
            fake_comports.append(("COM%i" % i, None, None))

        platform.comports().AndReturn(fake_comports)
        self.mox.ReplayAll()
        ports = platform.Win32Platform().list_serial_ports()

        correct_order = ["COM%i" % i for i in sorted(numbers)]
        self.assertEqual(ports, correct_order)

    def test_serial_ports_bad_portnames(self):
        self._test_init()

        platform.comports().AndReturn([('foo', None, None)])
        self.mox.ReplayAll()
        ports = platform.Win32Platform().list_serial_ports()
        self.assertEqual(ports, ['foo'])
