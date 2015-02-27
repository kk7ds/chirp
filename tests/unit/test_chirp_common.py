from tests.unit import base
from chirp import chirp_common
from chirp import errors


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


class TestSplitTone(base.BaseTest):
    def _test_split_tone_decode(self, tx, rx, **vals):
        mem = chirp_common.Memory()
        chirp_common.split_tone_decode(mem, tx, rx)
        for key, value in vals.items():
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
        for key, value in vals.items():
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
            print freq
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
        for step, freqs in steps.items():
            for freq in freqs:
                self.assertEqual(step, chirp_common.required_step(freq))

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
