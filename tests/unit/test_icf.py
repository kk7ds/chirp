# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
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

import os
import shutil
import tempfile
import unittest

from chirp import directory
from chirp.drivers import ic2820, icf, id31


class TestFileICF(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def cleanUp(self):
        shutil.rmtree(self.tempdir)

    def test_read_icf_data_modern(self):
        fn = os.path.join(self.tempdir, 'test.icf')
        with open(fn, 'w', newline='\r\n') as f:
            f.write('12345678\n#Foo=somefoovalue\n#Bar=123\n')
            f.write('0000000020015C70000020800000E4002020202020'
                    '20202020202020202020200040810204\n')
            f.write('000000202008102040810204081020408102040810'
                    '20015B9903E821700000E4284C614772\n')
            f.write('#CD=fakehash\n')
            f.flush()

        icfdata, mmap = icf.read_file(fn)

        self.assertEqual({'model': b'\x12\x34\x56\x78',
                          'Foo': 'somefoovalue',
                          'Bar': 123,
                          'recordsize': 32,
                          'CD': 'fakehash'}, icfdata)

        try:
            directory.get_radio_by_image(fn)
        except Exception as e:
            self.assertIn('Unknown file format', str(e))
        else:
            self.fail('Directory failed to reject unknown model')

    def test_read_icf_data_old(self):
        fn = os.path.join(self.tempdir, 'test.icf')
        with open(fn, 'w', newline='\r\n') as f:
            f.write('29700001\n#\n')
            f.write('00001008BBB7C0000927C04351435143512020\n')
            f.write('00101020202020202020202020202020202020\n')
            f.flush()

        icfdata, mmap = icf.read_file(fn)

        self.assertEqual({'model': b'\x29\x70\x00\x01',
                          'recordsize': 16}, icfdata)

    def test_read_write_icf(self):
        fn1 = os.path.join(self.tempdir, 'test1.icf')
        with open(fn1, 'w', newline='\r\n') as f:
            # These are different values than the default, so make
            # sure we persist them to the output ICF file.
            f.write('33220001\n#MapRev=2\n#EtcData=000006\n')
            f.write('0000000020015C70000020800000E4002020202020'
                    '20202020202020202020200040810204\n')
            f.write('000000202008102040810204081020408102040810'
                    '20015B9903E821700000E4284C614772\n')
            f.write('#CD=fakehash\n')
            f.flush()

        r = id31.ID31Radio(fn1)

        fn2 = os.path.join(self.tempdir, 'test2.icf')
        with open(fn2, 'w', newline='\r\n') as f:
            r.save(fn2)
            icfdata, mmap = icf.read_file(fn2)
            self.assertEqual({'MapRev': 2,
                              'EtcData': 6,
                              'Comment': '',
                              'model': r.get_model(),
                              'CD': '9674E1C86BA17D36DB9D3D8A144F1081',
                              'recordsize': 32}, icfdata)

    def test_read_img_write_icf_modern(self):
        img_file = os.path.join(os.path.dirname(__file__),
                                '..', 'images', 'Icom_ID-31A.img')

        r = id31.ID31Radio(img_file)
        fn = os.path.join(self.tempdir, 'test.icf')
        with open(fn, 'w', newline='\r\n'):
            r.save(fn)

            icfdata, mmap = icf.read_file(fn)
            # If we sourced from an image, we use our defaults in
            # generating the ICF metadata
            self.assertEqual({'MapRev': 1,
                              'EtcData': 5,
                              'Comment': '',
                              'model': r.get_model(),
                              'CD': '9F240F598EF20683726ED252278C61D0',
                              'recordsize': 32}, icfdata)

            self.assertIsInstance(directory.get_radio_by_image(fn),
                                  id31.ID31Radio)

    def test_read_img_write_icf_old(self):
        img_file = os.path.join(os.path.dirname(__file__),
                                '..', 'images', 'Icom_IC-2820H.img')

        r = ic2820.IC2820Radio(img_file)
        fn = os.path.join(self.tempdir, 'test.icf')
        with open(fn, 'w', newline='\r\n'):
            r.save(fn)

            icfdata, mmap = icf.read_file(fn)
            self.assertEqual({'MapRev': 1,
                              'EtcData': 0,
                              'Comment': '',
                              'model': r.get_model(),
                              'recordsize': 16}, icfdata)

            self.assertIsInstance(directory.get_radio_by_image(fn),
                                  ic2820.IC2820Radio)


class TestCloneICF(unittest.TestCase):
    def test_frame_parse(self):
        f = icf.IcfFrame.parse(b'\xfe\xfe\xee\xef\xe0\x00\01\xfd')
        self.assertEqual(0xEE, f.src)
        self.assertEqual(0xEF, f.dst)
        self.assertEqual(0xE0, f.cmd)
        self.assertEqual(b'\x00\x01', f.payload)

    def test_frame_parse_no_end(self):
        f = icf.IcfFrame.parse(b'\xfe\xfe\xee\xef\xe0\x00\01')
        self.assertIsNone(f)

    def test_frame_parse_trailing_garbage(self):
        f = icf.IcfFrame.parse(b'\xfe\xfe\xee\xef\xe0\x00\01\xfd\x01')
        self.assertEqual(0xEE, f.src)
        self.assertEqual(0xEF, f.dst)
        self.assertEqual(0xE0, f.cmd)
        self.assertEqual(b'\x00\x01', f.payload)

    def test_pack(self):
        f = icf.IcfFrame(icf.ADDR_PC, icf.ADDR_RADIO, icf.CMD_CLONE_ID)
        f.payload = b'\x01\x02'
        self.assertEqual(b'\xfe\xfe\xee\xef\xe0\x01\x02\xfd', f.pack())


class TestICFUtil(unittest.TestCase):
    def test_warp_byte_size(self):
        # 4-bit chars to 8-bit bytes
        input = bytes([0x12, 0x34])
        output = bytes(icf.warp_byte_size(input, obw=4))
        self.assertEqual(b'\x01\x02\x03\x04', output)

    def test_warp_byte_size_skip(self):
        # 4-bit chars to 8-bit bytes with 4 bits of padding ignored
        input = bytes([0x12, 0x34])
        output = bytes(icf.warp_byte_size(input, obw=4, iskip=4))
        self.assertEqual(b'\x02\x03\x04', output)

    def test_warp_byte_size_pad(self):
        # 8-bit bytes to 4-bit chars, with 4 bits of padding added
        input = bytes([2, 3, 4])
        output = bytes(icf.warp_byte_size(input, ibw=4, opad=4))
        self.assertEqual(b'\x02\x34', output)

    def test_warp_byte_size_symmetric_padded(self):
        # Make sure we can go from 8->4-> with padding and get back what we
        # put in
        ref = bytes([1, 2, 3, 4, 5, 6])
        stored = bytes(icf.warp_byte_size(bytes(ref), ibw=6, opad=4))
        self.assertEqual(5, len(bytes(stored)))
        self.assertEqual(ref,
                         bytes(icf.warp_byte_size(stored, obw=6, iskip=4)))
