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
import tempfile
import unittest

from chirp import directory
from chirp.drivers import ic2820, icf, id31


class TestICF(unittest.TestCase):
    def test_read_icf_data_modern(self):
        with tempfile.NamedTemporaryFile(suffix='.icf', mode='w') as f:
            f.write('12345678\r\n#Foo=somefoovalue\r\n#Bar=123\r\n')
            f.write('0000000020015C70000020800000E4002020202020'
                    '20202020202020202020200040810204\r\n')
            f.write('000000202008102040810204081020408102040810'
                    '20015B9903E821700000E4284C614772\r\n')
            f.write('#CD=fakehash\r\n')
            f.flush()

            icfdata, mmap = icf.read_file(f.name)

            self.assertEqual({'model': b'\x12\x34\x56\x78',
                              'Foo': 'somefoovalue',
                              'Bar': 123,
                              'recordsize': 32,
                              'CD': 'fakehash'}, icfdata)

            try:
                directory.icf_to_radio(f.name)
            except Exception as e:
                self.assertIn('12345678', str(e))
            else:
                self.fail('Directory failed to reject unknown model')

    def test_read_icf_data_old(self):
        with tempfile.NamedTemporaryFile(suffix='.icf', mode='w') as f:
            f.write('29700001\r\n#\r\n')
            f.write('00001008BBB7C0000927C04351435143512020\r\n')
            f.write('00101020202020202020202020202020202020\r\n')
            f.flush()

            icfdata, mmap = icf.read_file(f.name)

            self.assertEqual({'model': b'\x29\x70\x00\x01',
                              'recordsize': 16}, icfdata)

    def test_read_write_icf(self):
        with tempfile.NamedTemporaryFile(suffix='.icf', mode='w') as f:
            # These are different values than the default, so make
            # sure we persist them to the output ICF file.
            f.write('33220001\r\n#MapRev=2\r\n#EtcData=000006\r\n')
            f.write('0000000020015C70000020800000E4002020202020'
                    '20202020202020202020200040810204\r\n')
            f.write('000000202008102040810204081020408102040810'
                    '20015B9903E821700000E4284C614772\r\n')
            f.write('#CD=fakehash\r\n')
            f.flush()

            r = id31.ID31Radio(f.name)

        with tempfile.NamedTemporaryFile(suffix='.icf', mode='w') as f:
            r.save(f.name)
            icfdata, mmap = icf.read_file(f.name)
            self.assertEqual({'MapRev': 2,
                              'EtcData': 6,
                              'Comment': '',
                              'model': r.get_model(),
                              'recordsize': 32}, icfdata)

    def test_read_img_write_icf_modern(self):
        img_file = os.path.join(os.path.dirname(__file__),
                                '..', 'images', 'Icom_ID-31A.img')

        r = id31.ID31Radio(img_file)
        with tempfile.NamedTemporaryFile(suffix='.icf', mode='w') as f:
            r.save(f.name)

            icfdata, mmap = icf.read_file(f.name)
            # If we sourced from an image, we use our defaults in
            # generating the ICF metdata
            self.assertEqual({'MapRev': 1,
                              'EtcData': 5,
                              'Comment': '',
                              'model': r.get_model(),
                              'recordsize': 32}, icfdata)

            self.assertEqual(id31.ID31Radio,
                             directory.icf_to_radio(f.name))


    def test_read_img_write_icf_old(self):
        img_file = os.path.join(os.path.dirname(__file__),
                                '..', 'images', 'Icom_IC-2820H.img')

        r = ic2820.IC2820Radio(img_file)
        with tempfile.NamedTemporaryFile(suffix='.icf', mode='w') as f:
            r.save(f.name)

            icfdata, mmap = icf.read_file(f.name)
            self.assertEqual({'MapRev': 1,
                              'EtcData': 0,
                              'Comment': '',
                              'model': r.get_model(),
                              'recordsize': 16}, icfdata)

            self.assertEqual(ic2820.IC2820Radio,
                             directory.icf_to_radio(f.name))
