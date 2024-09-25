import base64
import copy
import json
import os
import pickle
import tempfile

from unittest import mock

from tests.unit import base
from chirp import CHIRP_VERSION
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import settings


class TestUtilityFunctions(base.BaseTest):
    def test_parse_freq_whole(self):
        self.assertEqual(chirp_common.parse_freq("146.520000"), 146520000)
        self.assertEqual(chirp_common.parse_freq("146.5200"), 146520000)
        self.assertEqual(chirp_common.parse_freq("146.52"), 146520000)
        self.assertEqual(chirp_common.parse_freq("146"), 146000000)
        self.assertEqual(chirp_common.parse_freq("1250"), 1250000000)
        self.assertEqual(chirp_common.parse_freq("123456789"),
                         123456789000000)

    def test_parse_freq_decimal(self):
        self.assertEqual(chirp_common.parse_freq("1.0"), 1000000)
        self.assertEqual(chirp_common.parse_freq("1.000000"), 1000000)
        self.assertEqual(chirp_common.parse_freq("1.1"), 1100000)
        self.assertEqual(chirp_common.parse_freq("1.100"), 1100000)
        self.assertEqual(chirp_common.parse_freq("0.6"), 600000)
        self.assertEqual(chirp_common.parse_freq("0.600"), 600000)
        self.assertEqual(chirp_common.parse_freq("0.060"), 60000)
        self.assertEqual(chirp_common.parse_freq(".6"), 600000)

    def test_parse_freq_whitespace(self):
        self.assertEqual(chirp_common.parse_freq("1  "), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1"), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1  "), 1000000)

        self.assertEqual(chirp_common.parse_freq("1.0  "), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1.0"), 1000000)
        self.assertEqual(chirp_common.parse_freq("   1.0  "), 1000000)
        self.assertEqual(chirp_common.parse_freq(""), 0)
        self.assertEqual(chirp_common.parse_freq(" "), 0)

    def test_parse_freq_bad(self):
        self.assertRaises(ValueError, chirp_common.parse_freq, "a")
        self.assertRaises(ValueError, chirp_common.parse_freq, "1.a")
        self.assertRaises(ValueError, chirp_common.parse_freq, "a.b")
        self.assertRaises(ValueError, chirp_common.parse_freq,
                          "1.0000001")

    def test_format_freq(self):
        self.assertEqual(chirp_common.format_freq(146520000), "146.520000")
        self.assertEqual(chirp_common.format_freq(54000000), "54.000000")
        self.assertEqual(chirp_common.format_freq(1800000), "1.800000")
        self.assertEqual(chirp_common.format_freq(1), "0.000001")
        self.assertEqual(chirp_common.format_freq(1250000000), "1250.000000")

    @mock.patch('chirp.CHIRP_VERSION', new='daily-20151021')
    def test_compare_version_to_current(self):
        self.assertTrue(chirp_common.is_version_newer('daily-20180101'))
        self.assertFalse(chirp_common.is_version_newer('daily-20140101'))
        self.assertFalse(chirp_common.is_version_newer('0.3.0'))
        self.assertFalse(chirp_common.is_version_newer('0.3.0dev'))

    @mock.patch('chirp.CHIRP_VERSION', new='0.3.0dev')
    def test_compare_version_to_current_dev(self):
        self.assertTrue(chirp_common.is_version_newer('daily-20180101'))

    def test_from_Hz(self):
        # FIXME: These are wrong! Adding them here purely to test the
        # python3 conversion, but they should be fixed.
        self.assertEqual(140, chirp_common.from_GHz(14000000001))
        self.assertEqual(140, chirp_common.from_MHz(14000001))
        self.assertEqual(140, chirp_common.from_kHz(14001))

    def test_mem_from_text_rb1(self):
        text = '145.2500 	-0.6 MHz 	97.4 	OPEN'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(145250000, mem.freq)
        self.assertEqual(600000, mem.offset)
        self.assertEqual('-', mem.duplex)
        self.assertEqual('Tone', mem.tmode)
        self.assertEqual(97.4, mem.rtone)

    def test_mem_from_text_rb2(self):
        text = '147.3000 	+0.6 MHz 	156.7 / 156.7 	OPEN'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(147300000, mem.freq)
        self.assertEqual(600000, mem.offset)
        self.assertEqual('+', mem.duplex)
        self.assertEqual('TSQL', mem.tmode)
        self.assertEqual(156.7, mem.ctone)

    def test_mem_from_text_rb3(self):
        text = '441.1000 	+5 MHz 	D125 / D125 	OPEN'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(441100000, mem.freq)
        self.assertEqual(5000000, mem.offset)
        self.assertEqual('+', mem.duplex)
        self.assertEqual('DTCS', mem.tmode)
        self.assertEqual(125, mem.dtcs)

    def test_mem_from_text_rb4(self):
        text = '441.1000 	+5 MHz 	88.5 / D125 	OPEN'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(441100000, mem.freq)
        self.assertEqual(5000000, mem.offset)
        self.assertEqual('+', mem.duplex)
        self.assertEqual('Cross', mem.tmode)
        self.assertEqual(88.5, mem.rtone)
        self.assertEqual(125, mem.rx_dtcs)
        self.assertEqual('Tone->DTCS', mem.cross_mode)

    def test_mem_from_text_random1(self):
        text = 'Glass Butte 147.200 + 162.2'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(147200000, mem.freq)
        # This is a default
        self.assertEqual(600000, mem.offset)
        # Just a random + or - on the line isn't enough to trigger offset
        # pattern
        self.assertEqual('+', mem.duplex)
        self.assertEqual('Tone', mem.tmode)
        self.assertEqual(162.2, mem.rtone)

    def test_mem_from_text_random2(self):
        text = 'Glass - Butte 147.200 + 162.2'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(147200000, mem.freq)
        # This is a default
        self.assertEqual(600000, mem.offset)
        # Just a random + or - on the line isn't enough to trigger offset
        # pattern
        self.assertEqual('+', mem.duplex)
        self.assertEqual('Tone', mem.tmode)
        self.assertEqual(162.2, mem.rtone)

    def test_mem_from_text_random3(self):
        text = 'Glass - Butte 147.200 + 88.5'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(147200000, mem.freq)
        # This is a default
        self.assertEqual(600000, mem.offset)
        # Just a random + or - on the line isn't enough to trigger offset
        # pattern
        self.assertEqual('+', mem.duplex)
        self.assertEqual('Tone', mem.tmode)
        self.assertEqual(88.5, mem.rtone)

    def test_mem_from_text_random4(self):
        text = '146.640 | 146.040 | 136.5'
        mem = chirp_common.mem_from_text(text)
        self.assertIsNotNone(mem)
        self.assertEqual(146640000, mem.freq)
        self.assertEqual(600000, mem.offset)
        self.assertEqual('-', mem.duplex)
        self.assertEqual('Tone', mem.tmode)
        self.assertEqual(136.5, mem.rtone)

    def test_mem_from_text_chirp1(self):
        text = '[400.625000/136.000000]'
        chirp_common.mem_from_text(text)

    def test_mem_from_text_chirp2(self):
        text = '[462.675000/+5.000/136.5/136.5]'
        mem = chirp_common.mem_from_text(text)
        self.assertEqual(462675000, mem.freq)
        self.assertEqual('+', mem.duplex)
        self.assertEqual(5000000, mem.offset)

    def test_mem_from_text_chirp3(self):
        text = '[1.675000/1.685/136.5/136.5]'
        mem = chirp_common.mem_from_text(text)
        self.assertEqual(1675000, mem.freq)
        self.assertEqual('+', mem.duplex)
        self.assertEqual(10000, mem.offset)

    def test_mem_from_text_chirp4(self):
        text = '[450.000000/150.000000]'
        mem = chirp_common.mem_from_text(text)
        self.assertEqual(450000000, mem.freq)
        self.assertEqual(150000000, mem.offset)
        self.assertEqual('split', mem.duplex)

    def test_mem_from_text_chirp5(self):
        text = '[500.000000/-9.900]'
        mem = chirp_common.mem_from_text(text)
        self.assertEqual(500000000, mem.freq)
        self.assertEqual(9900000, mem.offset)
        self.assertEqual('-', mem.duplex)
        self.assertEqual(text, chirp_common.mem_to_text(mem))

    def test_mem_from_text_chirp6(self):
        text = '[450.000000/150.000]'
        mem = chirp_common.mem_from_text(text)
        self.assertEqual(450000000, mem.freq)
        self.assertEqual(150000000, mem.offset)
        self.assertEqual('split', mem.duplex)

    def test_mem_from_text_chirp7(self):
        # Offsets >= 10MHz are not allowed, so this will get
        # parsed as a tx frequency of 15MHz
        text = '[450.000000/+15.000]'
        mem = chirp_common.mem_from_text(text)
        self.assertEqual(450000000, mem.freq)
        self.assertEqual(15000000, mem.offset)
        self.assertEqual('split', mem.duplex)

    def test_mem_from_text_chirp8(self):
        # Offsets >= 10MHz are not allowed, so this will get
        # parsed as a tx frequency of 15MHz
        text = '[450.000000/+150.000]'
        mem = chirp_common.mem_from_text(text)
        self.assertEqual(450000000, mem.freq)
        self.assertEqual(150000000, mem.offset)
        self.assertEqual('split', mem.duplex)

    def test_mem_to_text1(self):
        mem = chirp_common.Memory()
        mem.freq = 146900000
        mem.duplex = '-'
        mem.offset = 600000
        mem.tmode = 'TSQL'
        mem.ctone = 100.0
        txt = chirp_common.mem_to_text(mem)
        self.assertEqual('[146.900000/-0.600/100.0/100.0]', txt)
        chirp_common.mem_from_text(txt)
        self.assertEqual(600000, mem.offset)
        self.assertEqual('-', mem.duplex)

    def test_mem_to_text2(self):
        mem = chirp_common.Memory()
        mem.freq = 146900000
        mem.duplex = 'split'
        mem.offset = 446000000
        mem.tmode = 'Cross'
        mem.cross_mode = 'Tone->DTCS'
        mem.rtone = 100.0
        mem.rx_dtcs = 25
        txt = chirp_common.mem_to_text(mem)
        self.assertEqual('[146.900000/446.000000/100.0/D025]', txt)
        chirp_common.mem_from_text(txt)

    def test_mem_to_text3(self):
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.duplex = ''
        mem.offset = 600000
        mem.tmode = 'DTCS'
        mem.dtcs = 25
        txt = chirp_common.mem_to_text(mem)
        self.assertEqual('[146.520000/D025/D025]', txt)
        chirp_common.mem_from_text(txt)

    def test_parse_power(self):
        valid = [
            ('0.1', 0.1),
            ('0.1W', 0.1),
            ('0.25', 0.2),
            ('0.25W', 0.2),
            ('11.0', 11),
            ('11', 11),
            ('11.0W', 11),
            ('11w', 11),
            ('1500', 1500),
            ('2500', 2500),
            ('2500W', 2500),
            ('2500.0W', 2500)]
        for s, v in valid:
            power = chirp_common.parse_power(s)
            self.assertEqual(v, chirp_common.dBm_to_watts(float(power)))

    def test_parse_power_invalid(self):
        invalid = ['2500d', '2d1', 'aaa', 'a', '']
        for s in invalid:
            self.assertRaises(ValueError, chirp_common.parse_power, s)


class TestSplitTone(base.BaseTest):
    def _test_split_tone_decode(self, tx, rx, **vals):
        mem = chirp_common.Memory()
        chirp_common.split_tone_decode(mem, tx, rx)
        for key, value in list(vals.items()):
            self.assertEqual(getattr(mem, key), value)

    def test_split_tone_decode_none(self):
        self._test_split_tone_decode((None, None, None),
                                     (None, None, None),
                                     tmode='')

    def test_split_tone_decode_tone(self):
        self._test_split_tone_decode(('Tone', 100.0, None),
                                     ('', 0, None),
                                     tmode='Tone',
                                     rtone=100.0)

    def test_split_tone_decode_tsql(self):
        self._test_split_tone_decode(('Tone', 100.0, None),
                                     ('Tone', 100.0, None),
                                     tmode='TSQL',
                                     ctone=100.0)

    def test_split_tone_decode_dtcs(self):
        self._test_split_tone_decode(('DTCS', 23, None),
                                     ('DTCS', 23, None),
                                     tmode='DTCS',
                                     dtcs=23)

    def test_split_tone_decode_cross_tone_tone(self):
        self._test_split_tone_decode(('Tone', 100.0, None),
                                     ('Tone', 123.0, None),
                                     tmode='Cross',
                                     cross_mode='Tone->Tone',
                                     rtone=100.0,
                                     ctone=123.0)

    def test_split_tone_decode_cross_tone_dtcs(self):
        self._test_split_tone_decode(('Tone', 100.0, None),
                                     ('DTCS', 32, 'R'),
                                     tmode='Cross',
                                     cross_mode='Tone->DTCS',
                                     rtone=100.0,
                                     rx_dtcs=32,
                                     dtcs_polarity='NR')

    def test_split_tone_decode_cross_dtcs_tone(self):
        self._test_split_tone_decode(('DTCS', 32, 'R'),
                                     ('Tone', 100.0, None),
                                     tmode='Cross',
                                     cross_mode='DTCS->Tone',
                                     ctone=100.0,
                                     dtcs=32,
                                     dtcs_polarity='RN')

    def test_split_tone_decode_cross_dtcs_dtcs(self):
        self._test_split_tone_decode(('DTCS', 32, 'R'),
                                     ('DTCS', 25, 'R'),
                                     tmode='Cross',
                                     cross_mode='DTCS->DTCS',
                                     dtcs=32,
                                     rx_dtcs=25,
                                     dtcs_polarity='RR')

    def test_split_tone_decode_cross_none_dtcs(self):
        self._test_split_tone_decode((None, None, None),
                                     ('DTCS', 25, 'R'),
                                     tmode='Cross',
                                     cross_mode='->DTCS',
                                     rx_dtcs=25,
                                     dtcs_polarity='NR')

    def test_split_tone_decode_cross_none_tone(self):
        self._test_split_tone_decode((None, None, None),
                                     ('Tone', 100.0, None),
                                     tmode='Cross',
                                     cross_mode='->Tone',
                                     ctone=100.0)

    def _set_mem(self, **vals):
        mem = chirp_common.Memory()
        for key, value in list(vals.items()):
            setattr(mem, key, value)
        return chirp_common.split_tone_encode(mem)

    def split_tone_encode_test_none(self):
        self.assertEqual(self._set_mem(tmode=''),
                         (('', None, None),
                          ('', None, None)))

    def split_tone_encode_test_tone(self):
        self.assertEqual(self._set_mem(tmode='Tone', rtone=100.0),
                         (('Tone', 100.0, None),
                          ('', None, None)))

    def split_tone_encode_test_tsql(self):
        self.assertEqual(self._set_mem(tmode='TSQL', ctone=100.0),
                         (('Tone', 100.0, None),
                          ('Tone', 100.0, None)))

    def split_tone_encode_test_dtcs(self):
        self.assertEqual(self._set_mem(tmode='DTCS', dtcs=23,
                                       dtcs_polarity='RN'),
                         (('DTCS', 23, 'R'),
                          ('DTCS', 23, 'N')))

    def split_tone_encode_test_cross_tone_tone(self):
        self.assertEqual(self._set_mem(tmode='Cross', cross_mode='Tone->Tone',
                                       rtone=100.0, ctone=123.0),
                         (('Tone', 100.0, None),
                          ('Tone', 123.0, None)))

    def split_tone_encode_test_cross_tone_dtcs(self):
        self.assertEqual(self._set_mem(tmode='Cross', cross_mode='Tone->DTCS',
                                       rtone=100.0, rx_dtcs=25),
                         (('Tone', 100.0, None),
                          ('DTCS', 25, 'N')))

    def split_tone_encode_test_cross_dtcs_tone(self):
        self.assertEqual(self._set_mem(tmode='Cross', cross_mode='DTCS->Tone',
                                       ctone=100.0, dtcs=25),
                         (('DTCS', 25, 'N'),
                          ('Tone', 100.0, None)))

    def split_tone_encode_test_cross_none_dtcs(self):
        self.assertEqual(self._set_mem(tmode='Cross', cross_mode='->DTCS',
                                       rx_dtcs=25),
                         (('', None, None),
                          ('DTCS', 25, 'N')))

    def split_tone_encode_test_cross_none_tone(self):
        self.assertEqual(self._set_mem(tmode='Cross', cross_mode='->Tone',
                                       ctone=100.0),
                         (('', None, None),
                          ('Tone', 100.0, None)))


class TestStepFunctions(base.BaseTest):
    _625 = [145856250,
            445856250,
            862731250,
            146118750,
            ]
    _125 = [145862500,
            445862500,
            862737500,
            ]
    _005 = [145005000,
            445005000,
            850005000,
            ]
    _025 = [145002500,
            445002500,
            850002500,
            ]

    def test_is_fractional_step(self):
        for freq in self._125 + self._625:
            print(freq)
            self.assertTrue(chirp_common.is_fractional_step(freq))

    def test_is_6_25(self):
        for freq in self._625:
            self.assertTrue(chirp_common.is_6_25(freq))

    def test_is_12_5(self):
        for freq in self._125:
            self.assertTrue(chirp_common.is_12_5(freq))

    def test_is_5_0(self):
        for freq in self._005:
            self.assertTrue(chirp_common.is_5_0(freq))

    def test_is_2_5(self):
        for freq in self._025:
            self.assertTrue(chirp_common.is_2_5(freq))

    def test_required_step(self):
        steps = {2.5: self._025,
                 5.0: self._005,
                 6.25: self._625,
                 12.5: self._125,
                 }
        for step, freqs in list(steps.items()):
            for freq in freqs:
                self.assertEqual(step, chirp_common.required_step(freq))

    def test_required_step_with_list(self):
        steps = {5.0: self._005,
                 6.25: self._625,
                 12.5: self._125,
                 }
        allowed = [6.25, 12.5]
        for step, freqs in list(steps.items()):
            for freq in freqs:
                # We don't support 5.0, so any of the frequencies in that
                # list should raise an error
                if step == 5.0:
                    self.assertRaises(errors.InvalidDataError,
                                      chirp_common.required_step,
                                      freq, allowed)
                else:
                    self.assertEqual(step, chirp_common.required_step(
                        freq, allowed))

    def test_required_step_finds_suitable(self):
        # If we support 5.0, we should get it as the step for those
        self.assertEqual(5.0, chirp_common.required_step(self._005[0],
                                                         allowed=[2.5, 5.0]))
        # If we support 2.5 and not 5.0, then we should find 2.5 as a suitable
        # alternative
        self.assertEqual(2.5, chirp_common.required_step(self._005[0],
                                                         allowed=[2.5]))

    def test_required_step_finds_radio_specific(self):
        # Make sure we find a radio-specific step, 10Hz in this case
        self.assertEqual(0.01, chirp_common.required_step(
            146000010, allowed=[5.0, 10.0, 0.01, 20.0]))

    def test_required_step_fail(self):
        self.assertRaises(errors.InvalidDataError,
                          chirp_common.required_step,
                          146520500)

    def test_fix_rounded_step_250(self):
        self.assertEqual(146106250,
                         chirp_common.fix_rounded_step(146106000))

    def test_fix_rounded_step_500(self):
        self.assertEqual(146112500,
                         chirp_common.fix_rounded_step(146112000))

    def test_fix_rounded_step_750(self):
        self.assertEqual(146118750,
                         chirp_common.fix_rounded_step(146118000))


class TestImageMetadata(base.BaseTest):
    def test_make_metadata(self):
        class TestRadio(chirp_common.CloneModeRadio):
            VENDOR = 'Dan'
            MODEL = 'Foomaster 9000'
            VARIANT = 'R'

        r = TestRadio(None)
        r._metadata['someextra'] = 'foo'
        # We should always take the base properties from the class, so this
        # should not show up in the result.
        r._metadata['vendor'] = 'oops'
        raw_metadata = r._make_metadata()
        metadata = json.loads(base64.b64decode(raw_metadata).decode())
        expected = {
            'vendor': 'Dan',
            'model': 'Foomaster 9000',
            'variant': 'R',
            'rclass': 'TestRadio',
            'chirp_version': CHIRP_VERSION,
            'someextra': 'foo',
        }
        self.assertEqual(expected, metadata)

    def test_strip_metadata(self):
        class TestRadio(chirp_common.CloneModeRadio):
            VENDOR = 'Dan'
            MODEL = 'Foomaster 9000'
            VARIANT = 'R'

        r = TestRadio(None)
        r._metadata['someextra'] = 'foo'
        raw_metadata = r._make_metadata()
        raw_data = (b'foooooooooooooooooooooo' + TestRadio.MAGIC +
                    raw_metadata)
        data, metadata = chirp_common.CloneModeRadio._strip_metadata(raw_data)
        self.assertEqual(b'foooooooooooooooooooooo', data)
        expected = {
            'vendor': 'Dan',
            'model': 'Foomaster 9000',
            'variant': 'R',
            'rclass': 'TestRadio',
            'someextra': 'foo',
            'chirp_version': CHIRP_VERSION,
        }
        self.assertEqual(expected, metadata)

    def test_load_mmap_no_metadata(self):
        fn = os.path.join(tempfile.gettempdir(), 'testfile')
        with open(fn, 'wb') as f:
            f.write(b'thisisrawdata')
            f.flush()

        with mock.patch('chirp.memmap.MemoryMapBytes.__init__') as mock_mmap:
            mock_mmap.return_value = None
            chirp_common.CloneModeRadio(None).load_mmap(fn)
            mock_mmap.assert_called_once_with(b'thisisrawdata')
        os.remove(fn)

    def test_load_mmap_bad_metadata(self):
        fn = os.path.join(tempfile.gettempdir(), 'testfile')
        with open(fn, 'wb') as f:
            f.write(b'thisisrawdata')
            f.write(chirp_common.CloneModeRadio.MAGIC + b'bad')
            f.flush()

        with mock.patch('chirp.memmap.MemoryMapBytes.__init__') as mock_mmap:
            mock_mmap.return_value = None
            chirp_common.CloneModeRadio(None).load_mmap(fn)
            mock_mmap.assert_called_once_with(b'thisisrawdata')
        os.remove(fn)

    def test_save_mmap_includes_metadata(self):
        # Make sure that a file saved with a .img extension includes
        # the metadata blob
        class TestRadio(chirp_common.CloneModeRadio):
            VENDOR = 'Dan'
            MODEL = 'Foomaster 9000'
            VARIANT = 'R'

        fn = os.path.join(tempfile.gettempdir(), 'test.img')
        r = TestRadio(None)
        r._mmap = mock.Mock()
        r._mmap.get_byte_compatible.return_value.get_packed.return_value = (
            b'thisisrawdata')
        r.save_mmap(fn)
        with open(fn, 'rb') as f:
            filedata = f.read()
        os.remove(fn)
        data, metadata = chirp_common.CloneModeRadio._strip_metadata(filedata)
        self.assertEqual(b'thisisrawdata', data)
        expected = {
            'vendor': 'Dan',
            'model': 'Foomaster 9000',
            'variant': 'R',
            'rclass': 'TestRadio',
            'chirp_version': CHIRP_VERSION,
        }
        self.assertEqual(expected, metadata)

    def test_save_mmap_no_metadata_not_img_file(self):
        # Make sure that if we save without a .img extension we do
        # not include the metadata blob
        class TestRadio(chirp_common.CloneModeRadio):
            VENDOR = 'Dan'
            MODEL = 'Foomaster 9000'
            VARIANT = 'R'

        with tempfile.NamedTemporaryFile(suffix='.txt') as f:
            fn = f.name
        r = TestRadio(None)
        r._mmap = mock.Mock()
        r._mmap.get_byte_compatible.return_value.get_packed.return_value = (
            b'thisisrawdata')
        r.save_mmap(fn)
        with open(fn, 'rb') as f:
            filedata = f.read()
        os.remove(fn)
        data, metadata = chirp_common.CloneModeRadio._strip_metadata(filedata)
        self.assertEqual(b'thisisrawdata', data)
        self.assertEqual({}, metadata)

    def test_load_mmap_saves_metadata_on_radio(self):
        class TestRadio(chirp_common.CloneModeRadio):
            VENDOR = 'Dan'
            MODEL = 'Foomaster 9000'
            VARIANT = 'R'

        with tempfile.NamedTemporaryFile(suffix='.img') as f:
            fn = f.name
        r = TestRadio(None)
        r._mmap = mock.Mock()
        r._mmap.get_byte_compatible.return_value.get_packed.return_value = (
            b'thisisrawdata')
        r.save_mmap(fn)

        newr = TestRadio(None)
        newr.load_mmap(fn)
        expected = {
            'vendor': 'Dan',
            'model': 'Foomaster 9000',
            'variant': 'R',
            'rclass': 'TestRadio',
            'chirp_version': CHIRP_VERSION,
        }
        self.assertEqual(expected, newr.metadata)

    def test_sub_devices_linked_metadata(self):
        class FakeRadio(chirp_common.CloneModeRadio):
            def get_sub_devices(self):
                return [FakeRadioSub('a'), FakeRadioSub('b')]

        class FakeRadioSub(FakeRadio):
            def __init__(self, name):
                self.VARIANT = name

        r = FakeRadio(None)
        subs = r.get_sub_devices()
        r.link_device_metadata(subs)
        subs[1]._metadata['foo'] = 'bar'
        self.assertEqual({'a': {}, 'b': {'foo': 'bar'}}, r._metadata)


class FakeRadio(chirp_common.CloneModeRadio):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mems = {}

    def get_memory(self, number):
        return self._mems[number]

    def set_memory(self, mem):
        # Simulate not storing the comment in our memory
        mem = copy.deepcopy(mem)
        mem.comment = ''
        self._mems[mem.number] = mem


class TestCloneModeExtras(base.BaseTest):
    def test_extra_comment(self):
        r = FakeRadio(None)
        m = chirp_common.Memory()
        m.number = 0
        m.freq = 146520000
        m.comment = 'a comment'
        r.set_memory(m)
        # Make sure our fake driver didn't modify our copy
        self.assertEqual('a comment', m.comment)

        m = r.get_memory(0)
        self.assertEqual(146520000, m.freq)
        # Before we call extra, we have no comment
        self.assertEqual('', m.comment)
        m = r.get_memory_extra(m)
        # We haven't called set_extra, so still nothing
        self.assertEqual('', m.comment)

        # Do a normal set, set_extra
        m.comment = 'a comment'
        r.set_memory(m)
        r.set_memory_extra(m)

        # Do a get, get_extra
        m = r.get_memory(0)
        m = r.get_memory_extra(m)
        self.assertEqual(146520000, m.freq)
        # Now we should have the comment
        self.assertEqual('a comment', m.comment)

        # Make sure it is in the metadata
        self.assertIn('0000_comment', r.metadata['mem_extra'])

        # Erase the memory (only extra) and make sure we get no comment
        r.erase_memory_extra(0)

        # Make sure it's gone from metadata
        self.assertNotIn('0000_comment', r.metadata['mem_extra'])

        # Do a get, get_extra
        m = r.get_memory(0)
        m = r.get_memory_extra(m)
        self.assertEqual(146520000, m.freq)
        # Now we should have no comment because we erased
        self.assertEqual('', m.comment)

        r.set_memory_extra(m)

        # Make sure we don't keep empty comments
        self.assertNotIn('0000_comment', r.metadata['mem_extra'])


class TestOverrideRules(base.BaseTest):
    # You should not need to add your radio to this list. If you think you do,
    # please ask permission first.
    # Immutable fields should really only be used for cases where the value
    # is not changeable based on the *location* of the memory. If something
    # is forced to be a value based on the *content* of the memory (i.e. AM
    # for frequencies in airband), coerce them on set/get, and return a
    # ValidationWarning in validate_memory() so the user is told that the
    # values are being forced.
    IMMUTABLE_WHITELIST = [
        # Uncomment me when the time comes
        'Baofeng_GT-5R',
        'BTECH_GMRS-20V2',
        'BTECH_GMRS-50V2',
        'BTECH_GMRS-50X1',
        'BTECH_GMRS-V2',
        'BTECH_MURS-V2',
        'Radioddity_DB25-G',
        'Retevis_RB17P',
    ]

    def _test_radio_override_immutable_policy(self, rclass):
        self.assertEqual(
            chirp_common.Radio.check_set_memory_immutable_policy,
            rclass.check_set_memory_immutable_policy,
            'Radio %s should not override '
            'check_set_memory_immutable_policy' % (
                directory.radio_class_id(rclass)))

    def _test_radio_override_calls_super(self, rclass):
        r = rclass(None)
        method = r.check_set_memory_immutable_policy

        # Make sure the radio actually overrides it
        self.assertNotEqual(
            chirp_common.Radio.check_set_memory_immutable_policy,
            method,
            ('Radio %s in whitelist does not override '
             'check_set_memory_immutable_policy') % (
                 directory.radio_class_id(rclass)))

        # Make sure super() is called in the child class
        self.assertIn('__class__', method.__code__.co_freevars,
                      '%s.%s must call super() but does not' % (
                          rclass.__name__, method.__name__))

    def test_radio_overrides(self):
        for rclass in directory.DRV_TO_RADIO.values():
            if directory.radio_class_id(rclass) in self.IMMUTABLE_WHITELIST:
                self._test_radio_override_calls_super(rclass)
            else:
                self._test_radio_override_immutable_policy(rclass)


class TestMemory(base.BaseTest):
    def test_pickle_with_extra(self):
        m = chirp_common.Memory()
        m.extra = settings.RadioSettingGroup('extra', 'extra')
        m.extra.append(settings.RadioSetting(
            'test', 'test',
            settings.RadioSettingValueString(1, 32, current='foo')))
        n = pickle.loads(pickle.dumps(m))
        self.assertEqual(str(n.extra['test'].value),
                         str(m.extra['test'].value))

    def test_frozen_from_frozen(self):
        m = chirp_common.FrozenMemory(chirp_common.Memory(123))
        n = chirp_common.FrozenMemory(m)
        self.assertEqual(123, n.number)

    def test_frozen_dupe_unfrozen(self):
        FrozenMemory = chirp_common.FrozenMemory(
            chirp_common.Memory()).__class__
        m = chirp_common.FrozenMemory(chirp_common.Memory(123)).dupe()
        self.assertNotIsInstance(m, FrozenMemory)
        self.assertFalse(hasattr(m, '_frozen'))

    def test_frozen_modifications(self):
        orig = chirp_common.Memory(123)
        orig.extra = [settings.RadioSetting(
            'foo', 'Foo',
            settings.RadioSettingValueBoolean(False))]
        frozen = chirp_common.FrozenMemory(orig)
        with self.assertRaises(ValueError):
            frozen.extra[0].value = True

    def test_tone_validator(self):
        m = chirp_common.Memory()
        # 100.0 is a valid tone
        m.rtone = 100.0
        m.ctone = 100.0

        # 100 is not (must be a float)
        with self.assertRaises(ValueError):
            m.rtone = 100
        with self.assertRaises(ValueError):
            m.ctone = 100

        # 30.0 and 300.0 are out of range
        with self.assertRaises(ValueError):
            m.rtone = 30.0
        with self.assertRaises(ValueError):
            m.rtone = 300.0
        with self.assertRaises(ValueError):
            m.ctone = 30.0
        with self.assertRaises(ValueError):
            m.ctone = 300.0

    def test_repr_dump(self):
        m = chirp_common.Memory()
        self.assertEqual(
            "<Memory 0: freq=0,name='',vfo=0,rtone=88.5,ctone=88.5,dtcs=23,"
            "rx_dtcs=23,tmode='',cross_mode='Tone->Tone',dtcs_polarity='NN',"
            "skip='',power=None,duplex='',offset=600000,mode='FM',"
            "tuning_step=5.0,comment='',empty=False,immutable=[]>", repr(m))

        m.freq = 146520000
        m.rtone = 107.2
        m.tmode = 'Tone'
        self.assertEqual(
            "<Memory 0: freq=146520000,name='',vfo=0,rtone=107.2,ctone=88.5,"
            "dtcs=23,rx_dtcs=23,tmode='Tone',cross_mode='Tone->Tone',"
            "dtcs_polarity='NN',skip='',power=None,duplex='',offset=600000,"
            "mode='FM',tuning_step=5.0,comment='',empty=False,immutable=[]>",
            repr(m))

        m.number = 101
        m.extd_number = 'Call'
        self.assertEqual(
            "<Memory Call(101): freq=146520000,name='',vfo=0,rtone=107.2,"
            "ctone=88.5,dtcs=23,rx_dtcs=23,tmode='Tone',"
            "cross_mode='Tone->Tone',dtcs_polarity='NN',skip='',power=None,"
            "duplex='',offset=600000,mode='FM',tuning_step=5.0,comment='',"
            "empty=False,immutable=[]>", repr(m))

        m.extra = settings.RadioSettingGroup('extra', 'Extra')
        m.extra.append(
            settings.RadioSetting('test1', 'Test Setting 1',
                                  settings.RadioSettingValueBoolean(False)))
        m.extra.append(
            settings.RadioSetting('test2', 'Test Setting 2',
                                  settings.RadioSettingValueList(
                                      ['foo', 'bar'], 'foo')))
        self.assertEqual(
            "<Memory Call(101): freq=146520000,name='',vfo=0,rtone=107.2,"
            "ctone=88.5,dtcs=23,rx_dtcs=23,tmode='Tone',"
            "cross_mode='Tone->Tone',dtcs_polarity='NN',skip='',power=None,"
            "duplex='',offset=600000,mode='FM',tuning_step=5.0,comment='',"
            "empty=False,immutable=[],extra.test1='False',extra.test2='foo'>",
            repr(m))

    def test_debug_diff(self):
        m1 = chirp_common.Memory(1)
        m2 = chirp_common.Memory(1)

        m1.freq = 146520000
        m2.freq = 446000000
        self.assertEqual('freq=146520000>446000000', m1.debug_diff(m2, '>'))

        m2.tmode = 'TSQL'
        self.assertEqual("freq=146520000/446000000,tmode=''/'TSQL'",
                         m1.debug_diff(m2))

        # Make sure ident diffs come first and are noticed
        m2.number = 2
        m2.freq = 146520000
        self.assertEqual("ident=1/2,tmode=''/'TSQL'", m1.debug_diff(m2))

        # Make sure we can diff extras, and amongst heterogeneous formats
        m2.number = 1
        m1.extra = settings.RadioSettingGroup('extra', 'Extra')
        m2.extra = settings.RadioSettingGroup('extra', 'Extra')
        m1.extra.append(
            settings.RadioSetting('test1', 'Test Setting 1',
                                  settings.RadioSettingValueBoolean(False)))
        m2.extra.append(
            settings.RadioSetting('test2', 'Test Setting 2',
                                  settings.RadioSettingValueList(
                                      ['foo', 'bar'], 'foo')))
        self.assertEqual(
            "extra.test1='False'/'<missing>',extra.test2='<missing>'/'foo',"
            "tmode=''/'TSQL'", m1.debug_diff(m2))


class TestRadioFeatures(base.BaseTest):
    def test_valid_tones(self):
        rf = chirp_common.RadioFeatures()
        # These are valid tones
        rf.valid_tones = [100.0, 107.2]

        # These contain invalid tones
        with self.assertRaises(ValueError):
            rf.valid_tones = [100.0, 30.0]
        with self.assertRaises(ValueError):
            rf.valid_tones = [100.0, 300.0]
        with self.assertRaises(ValueError):
            rf.valid_tones = [100, 107.2]
