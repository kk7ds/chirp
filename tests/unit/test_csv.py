import os
import tempfile
import unittest

import ddt

from chirp import chirp_common
from chirp import directory
from chirp.drivers import generic_csv

CHIRP_CSV_LEGACY = (
    """Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL
1,FRS 1,462.562500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,
2,FRS 2,462.587500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,
""")
CHIRP_CSV_MINIMAL = (
    """Location,Frequency
1,146.520
2,446.000
""")
CHIRP_CSV_MODERN = (
    """Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE
0,Nat Simplex,146.520000,,0.600000,TSQL,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,This is the national calling frequency on 2m,,,,
1,National Simp,446.000000,-,5.000000,DTCS,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,5.0W,This is NOT the UHF calling frequency,,,,
""")  # noqa
CHIRP_CSV_MODERN_QUOTED_HEADER = (
    """"Location","Name","Frequency","Duplex","Offset","Tone","rToneFreq","cToneFreq","DtcsCode","DtcsPolarity","RxDtcsCode","CrossMode","Mode","TStep","Skip","Power","Comment","URCALL","RPT1CALL","RPT2CALL","DVCODE"
0,Nat Simplex,146.520000,,0.600000,TSQL,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,This is the national calling frequency on 2m,,,,
1,"National Simp",446.000000,-,5.000000,DTCS,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,5.0W,This is NOT the UHF calling frequency,,,,
""")  # noqa


class TestCSV(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.testfn = tempfile.mktemp('.csv', 'chirp-test')

    def tearDown(self):
        super().tearDown()
        try:
            os.remove(self.testfn)
        except FileNotFoundError:
            pass

    def test_parse_legacy(self):
        with open(self.testfn, 'w', encoding='utf-8') as f:
            f.write(CHIRP_CSV_LEGACY)
        csv = generic_csv.CSVRadio(self.testfn)
        mem = csv.get_memory(1)
        self.assertEqual(1, mem.number)
        self.assertEqual('FRS 1', mem.name)
        self.assertEqual(462562500, mem.freq)
        self.assertEqual('', mem.duplex)
        self.assertEqual(5000000, mem.offset)
        self.assertEqual('', mem.tmode)
        self.assertEqual(88.5, mem.rtone)
        self.assertEqual(88.5, mem.ctone)
        self.assertEqual(23, mem.dtcs)
        self.assertEqual('NN', mem.dtcs_polarity)
        self.assertEqual('NFM', mem.mode)
        self.assertEqual(12.5, mem.tuning_step)

    def test_parse_modern(self, output_encoding='utf-8', data=None):
        with open(self.testfn, 'w', encoding=output_encoding) as f:
            f.write(data or CHIRP_CSV_MODERN)
        # Make sure we detect the file
        with open(self.testfn, 'rb') as f:
            self.assertTrue(generic_csv.CSVRadio.match_model(
                f.read(), self.testfn))
        csv = generic_csv.CSVRadio(self.testfn)
        mem = csv.get_memory(1)
        self.assertEqual(1, mem.number)
        self.assertEqual('National Simp', mem.name)
        self.assertEqual(446000000, mem.freq)
        self.assertEqual('-', mem.duplex)
        self.assertEqual(5000000, mem.offset)
        self.assertEqual('DTCS', mem.tmode)
        self.assertEqual(88.5, mem.rtone)
        self.assertEqual(88.5, mem.ctone)
        self.assertEqual(23, mem.dtcs)
        self.assertEqual('NN', mem.dtcs_polarity)
        self.assertEqual('FM', mem.mode)
        self.assertEqual(5.0, mem.tuning_step)
        self.assertEqual('5.0W', str(mem.power))
        self.assertIn('UHF calling', mem.comment)

    def _test_csv_with_comments(self, data, output_encoding='utf-8'):
        lines = list(data.strip().split('\n'))
        lines.insert(0, '# This is a comment')
        lines.insert(0, '# Test file with comments')
        lines.insert(4, '# Test comment in the middle')
        lines.append('# Comment at the end')
        with open(self.testfn, 'w', newline='', encoding=output_encoding) as f:
            f.write('\r\n'.join(lines))
        # Make sure we detect the file
        with open(self.testfn, 'rb') as f:
            self.assertTrue(generic_csv.CSVRadio.match_model(
                f.read(), self.testfn))
        csv = generic_csv.CSVRadio(self.testfn)
        mem = csv.get_memory(0)
        self.assertEqual(146520000, mem.freq)
        mem = csv.get_memory(1)
        self.assertEqual(446000000, mem.freq)
        csv.save(self.testfn)
        with open(self.testfn, 'r') as f:
            read_lines = [x.strip() for x in f.readlines()]
        # Ignore quotes
        self.assertEqual([x.replace('"', '') for x in lines], read_lines)

    def test_csv_with_comments(self):
        self._test_csv_with_comments(CHIRP_CSV_MODERN)

    def test_csv_with_comments_quoted_header(self):
        self._test_csv_with_comments(CHIRP_CSV_MODERN_QUOTED_HEADER)

    def test_parse_modern_quoted_header(self):
        self.test_parse_modern(data=CHIRP_CSV_MODERN_QUOTED_HEADER)

    def test_parse_modern_quoted_header_bom(self):
        self.test_parse_modern(output_encoding='utf-8-sig',
                               data=CHIRP_CSV_MODERN_QUOTED_HEADER)

    def test_parse_modern_bom(self):
        self.test_parse_modern(output_encoding='utf-8-sig')

    def test_parse_modern_bom_with_comments(self):
        self.test_parse_modern(output_encoding='utf-8-sig')

    def test_parse_minimal(self):
        with open(self.testfn, 'w', encoding='utf-8') as f:
            f.write(CHIRP_CSV_MINIMAL)
        csv = generic_csv.CSVRadio(self.testfn)
        mem = csv.get_memory(1)
        self.assertEqual(1, mem.number)
        self.assertEqual(146520000, mem.freq)

    def test_parse_unknown_field(self):
        with open(self.testfn, 'w', encoding='utf-8') as f:
            f.write('Location,Frequency,Color\n')
            f.write('1,146.520,Red\n')
        csv = generic_csv.CSVRadio(self.testfn)
        mem = csv.get_memory(1)
        self.assertEqual(1, mem.number)
        self.assertEqual(146520000, mem.freq)

    def test_parse_unknown_power(self):
        with open(self.testfn, 'w', encoding='utf-8') as f:
            f.write('Location,Frequency,Power\n')
            f.write('0,146.520,L1\n')
            f.write('1,146.520,5W\n')
        csv = generic_csv.CSVRadio(self.testfn)
        mem = csv.get_memory(1)
        self.assertEqual(1, mem.number)
        self.assertEqual(146520000, mem.freq)

    def test_foreign_power(self):
        csv = generic_csv.CSVRadio(None)
        m = chirp_common.Memory()
        m.number = 1
        m.freq = 146520000
        m.power = chirp_common.PowerLevel('Low', watts=17)
        csv.set_memory(m)
        m = csv.get_memory(1)
        self.assertEqual('17W', str(m.power))
        self.assertEqual(int(chirp_common.watts_to_dBm(17)), int(m.power))

    def test_default_power(self):
        m = chirp_common.Memory()
        m.number = 1
        m.freq = 146520000
        r = generic_csv.CSVRadio(None)
        r.set_memory(m)
        m2 = r.get_memory(1)
        self.assertEqual(generic_csv.DEFAULT_POWER_LEVEL, m2.power)

    def _write_and_read(self, mem):
        radio = generic_csv.CSVRadio(None)
        radio.set_memory(mem)
        radio.save(self.testfn)
        radio = generic_csv.CSVRadio(self.testfn)
        return radio.get_memory(mem.number)

    def test_escaped_string_chars(self):
        m = chirp_common.Memory()
        m.number = 1
        m.name = 'This is "The one"'
        m.comment = 'Wow, a \nMulti-line comment!'
        m2 = self._write_and_read(m)
        self.assertEqual(m.name, m2.name)
        self.assertEqual(m.comment, m2.comment)

    def test_unicode_comment_chars(self):
        m = chirp_common.Memory()
        m.number = 1
        m.name = 'This is "The one"'
        m.comment = b'This is b\xc9\x90d news'.decode()
        m2 = self._write_and_read(m)
        self.assertEqual(m.name, m2.name)
        self.assertEqual(m.comment, m2.comment)

    def test_cross_dtcs(self):
        m = chirp_common.Memory()
        m.number = 1
        m.tmode = 'Cross'
        m.cross_mode = 'DTCS->DTCS'
        m.dtcs = 25
        m.rx_dtcs = 73
        m2 = self._write_and_read(m)
        self.assertEqual('Cross', m2.tmode)
        self.assertEqual('DTCS->DTCS', m2.cross_mode)
        self.assertEqual(25, m2.dtcs)
        self.assertEqual(73, m2.rx_dtcs)

    def test_csv_memories_are_private(self):
        m = chirp_common.Memory(name='foo')
        radio = generic_csv.CSVRadio(None)
        radio.set_memory(m)
        # If CSVRadio maintains a reference to m, then this will modify
        # its internal state and the following assertion will fail.
        m.name = 'bar'
        self.assertEqual('foo', radio.get_memory(0).name)


@ddt.ddt
class RTCSV(unittest.TestCase):
    def _test_open(self, sample):
        sample_fn = os.path.join(os.path.dirname(__file__), sample)
        radio = directory.get_radio_by_image(sample_fn)
        self.assertIsInstance(radio, generic_csv.RTCSVRadio)

    @ddt.data('ft3d', 'ftm400', 'ftm500')
    def test_sample_file(self, arg):
        self._test_open('rtcsv_%s.csv' % arg)
