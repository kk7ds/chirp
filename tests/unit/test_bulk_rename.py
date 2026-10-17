# Copyright 2026 Tony Gies <tgies@tgies.net>
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

from tests.unit import base
from chirp import chirp_common
from chirp import settings
from chirp.wxui.bulk_rename import (CaseInsensitiveDict, parse_seq_token,
                                    build_format_dict, apply_template,
                                    resolve_arithmetic,
                                    resolve_conditionals)


class TestCaseInsensitiveDict(base.BaseTest):
    def test_lowercase_lookup(self):
        d = CaseInsensitiveDict({'freq': 462.5625, 'name': 'TEST'})
        self.assertEqual(462.5625, d['freq'])

    def test_uppercase_lookup(self):
        d = CaseInsensitiveDict({'freq': 462.5625})
        self.assertEqual(462.5625, d['FREQ'])

    def test_mixed_case_lookup(self):
        d = CaseInsensitiveDict({'freq': 462.5625})
        self.assertEqual(462.5625, d['Freq'])

    def test_missing_key_raises(self):
        d = CaseInsensitiveDict({'freq': 462.5625})
        with self.assertRaises(KeyError):
            d['nonexistent']

    def test_contains(self):
        d = CaseInsensitiveDict({'freq': 462.5625})
        self.assertIn('FREQ', d)
        self.assertIn('freq', d)
        self.assertNotIn('missing', d)


class TestParseSeqToken(base.BaseTest):
    def test_no_seq(self):
        template, start, step = parse_seq_token('CH {num}')
        self.assertEqual('CH {num}', template)
        self.assertEqual(1, start)
        self.assertEqual(1, step)

    def test_plain_seq(self):
        template, start, step = parse_seq_token('{seq}')
        self.assertEqual('{seq}', template)
        self.assertEqual(1, start)
        self.assertEqual(1, step)

    def test_seq_positive_offset(self):
        template, start, step = parse_seq_token('{seq+10}')
        self.assertEqual('{seq}', template)
        self.assertEqual(10, start)
        self.assertEqual(1, step)

    def test_seq_negative_offset(self):
        template, start, step = parse_seq_token('{seq-5}')
        self.assertEqual('{seq}', template)
        self.assertEqual(-5, start)
        self.assertEqual(1, step)

    def test_seq_offset_and_step(self):
        template, start, step = parse_seq_token('{seq+10/2}')
        self.assertEqual('{seq}', template)
        self.assertEqual(10, start)
        self.assertEqual(2, step)

    def test_seq_with_format_spec(self):
        template, start, step = parse_seq_token('{seq+10:03d}')
        self.assertEqual('{seq:03d}', template)
        self.assertEqual(10, start)
        self.assertEqual(1, step)

    def test_seq_full_syntax(self):
        template, start, step = parse_seq_token('{seq+10/2:03d}')
        self.assertEqual('{seq:03d}', template)
        self.assertEqual(10, start)
        self.assertEqual(2, step)

    def test_seq_preserves_surrounding_text(self):
        template, start, step = parse_seq_token('CH {seq+5} x')
        self.assertEqual('CH {seq} x', template)
        self.assertEqual(5, start)
        self.assertEqual(1, step)

    def test_seq_case_insensitive(self):
        template, start, step = parse_seq_token('{SEQ+10}')
        self.assertEqual('{seq}', template)
        self.assertEqual(10, start)
        self.assertEqual(1, step)

    def test_seq_step_without_offset(self):
        template, start, step = parse_seq_token('{seq/2}')
        self.assertEqual('{seq}', template)
        self.assertEqual(1, start)
        self.assertEqual(2, step)

    def test_repeated_seq_tokens(self):
        template, start, step = parse_seq_token(
            '{seq+10}-{seq+10}')
        self.assertEqual('{seq}-{seq}', template)
        self.assertEqual(10, start)
        self.assertEqual(1, step)

    def test_conflicting_seq_modifiers_raises(self):
        with self.assertRaises(ValueError):
            parse_seq_token('{seq+10}-{seq+20}')


class TestBuildFormatDict(base.BaseTest):
    def _make_memory(self, **kwargs):
        mem = chirp_common.Memory()
        mem.freq = 462562500
        mem.number = 5
        mem.name = 'GMRS 5'
        mem.offset = 5000000
        mem.duplex = '+'
        mem.tmode = 'TSQL'
        mem.rtone = 141.3
        mem.ctone = 141.3
        mem.dtcs = 23
        mem.mode = 'FM'
        mem.tuning_step = 12.5
        mem.skip = ''
        mem.comment = 'test'
        for k, v in kwargs.items():
            setattr(mem, k, v)
        return mem

    def test_freq_converted_to_mhz(self):
        mem = self._make_memory(freq=462562500)
        d = build_format_dict(mem, 1)
        self.assertAlmostEqual(462.5625, d['freq'], places=4)

    def test_offset_converted_to_mhz(self):
        mem = self._make_memory(offset=5000000)
        d = build_format_dict(mem, 1)
        self.assertAlmostEqual(5.0, d['offset'], places=4)

    def test_num_alias(self):
        mem = self._make_memory(number=42)
        d = build_format_dict(mem, 1)
        self.assertEqual(42, d['num'])
        self.assertEqual(42, d['number'])

    def test_seq_injected(self):
        mem = self._make_memory()
        d = build_format_dict(mem, 7)
        self.assertEqual(7, d['seq'])

    def test_power_none_becomes_empty_string(self):
        mem = self._make_memory(power=None)
        d = build_format_dict(mem, 1)
        self.assertEqual('', d['power'])

    def test_extra_settings_exposed(self):
        mem = self._make_memory()
        rs = settings.RadioSetting(
            'scramble', 'Scramble',
            settings.RadioSettingValueList(
                ['Off', 'SCR1', 'SCR2'],
                current_index=1))
        mem.extra = settings.RadioSettingGroup(
            'extra', 'Extra')
        mem.extra.append(rs)
        d = build_format_dict(mem, 1)
        self.assertEqual('SCR1', d['scramble'])

    def test_cross_mode_exposed(self):
        mem = self._make_memory()
        d = build_format_dict(mem, 1)
        self.assertEqual('Tone->Tone', d['cross_mode'])

    def test_power_stringified(self):
        pl = chirp_common.PowerLevel('High', watts=5)
        mem = self._make_memory(power=pl)
        d = build_format_dict(mem, 1)
        self.assertEqual('High', d['power'])

    def test_case_insensitive(self):
        mem = self._make_memory()
        d = build_format_dict(mem, 1)
        self.assertEqual(d['freq'], d['FREQ'])
        self.assertEqual(d['name'], d['Name'])

    def test_tmode_exposed(self):
        mem = self._make_memory(tmode='TSQL')
        d = build_format_dict(mem, 1)
        self.assertEqual('TSQL', d['tmode'])

    def test_all_memory_fields_present(self):
        mem = self._make_memory()
        d = build_format_dict(mem, 1)
        for field in ('number', 'name', 'freq', 'offset', 'duplex',
                      'tmode', 'rtone', 'ctone', 'dtcs', 'mode',
                      'tuning_step', 'skip', 'comment', 'cross_mode',
                      'dtcs_polarity', 'rx_dtcs'):
            self.assertIn(field, d, 'Missing token: %s' % field)


class TestApplyTemplate(base.BaseTest):
    def _make_memory(self, **kwargs):
        mem = chirp_common.Memory()
        mem.freq = 462562500
        mem.number = 5
        mem.name = 'GMRS 5'
        mem.offset = 5000000
        mem.duplex = '+'
        mem.tmode = ''
        mem.rtone = 88.5
        mem.ctone = 88.5
        mem.dtcs = 23
        mem.mode = 'FM'
        mem.tuning_step = 12.5
        mem.skip = ''
        mem.comment = ''
        for k, v in kwargs.items():
            setattr(mem, k, v)
        return mem

    def test_literal_only(self):
        mem = self._make_memory()
        result = apply_template('HELLO', mem, 0)
        self.assertTrue(result.ok)
        self.assertEqual('HELLO', result.value)

    def test_freq_format(self):
        mem = self._make_memory(freq=462562500)
        result = apply_template('{freq:.1f}', mem, 0)
        self.assertEqual('462.6', result.value)

    def test_freq_full_precision(self):
        mem = self._make_memory(freq=462562500)
        result = apply_template('{freq:.4f}', mem, 0)
        self.assertEqual('462.5625', result.value)

    def test_num_token(self):
        mem = self._make_memory(number=5)
        result = apply_template('CH {num}', mem, 0)
        self.assertEqual('CH 5', result.value)

    def test_seq_default(self):
        mem = self._make_memory()
        result = apply_template('CH {seq}', mem, 0)
        self.assertEqual('CH 1', result.value)

    def test_seq_second_row(self):
        mem = self._make_memory()
        result = apply_template('CH {seq}', mem, 2)
        self.assertEqual('CH 3', result.value)

    def test_seq_with_offset(self):
        mem = self._make_memory()
        result = apply_template('CH {seq+10}', mem, 0)
        self.assertEqual('CH 10', result.value)

    def test_seq_with_offset_and_step(self):
        mem = self._make_memory()
        result = apply_template('CH {seq+10/2}', mem, 2)
        self.assertEqual('CH 14', result.value)

    def test_seq_zero_padded(self):
        mem = self._make_memory()
        result = apply_template('G{seq:02d}', mem, 0)
        self.assertEqual('G01', result.value)

    def test_seq_offset_zero_padded(self):
        mem = self._make_memory()
        result = apply_template('G{seq+10:03d}', mem, 0)
        self.assertEqual('G010', result.value)

    def test_multiple_tokens(self):
        mem = self._make_memory(freq=462562500, mode='FM')
        result = apply_template('{freq:.1f} {mode}', mem, 0)
        self.assertEqual('462.6 FM', result.value)

    def test_case_insensitive_tokens(self):
        mem = self._make_memory(freq=462562500)
        result = apply_template('{FREQ:.1f}', mem, 0)
        self.assertEqual('462.6', result.value)

    def test_empty_template(self):
        mem = self._make_memory()
        result = apply_template('', mem, 0)
        self.assertEqual('', result.value)

    def test_unknown_token_returns_error(self):
        mem = self._make_memory()
        result = apply_template('{bogus}', mem, 0)
        self.assertIn('bogus', result.error)
        self.assertFalse(result.ok)

    def test_bad_format_spec_returns_error(self):
        mem = self._make_memory()
        result = apply_template('{freq:zz}', mem, 0)
        self.assertFalse(result.ok)

    def test_existing_name_token(self):
        mem = self._make_memory(name='OLD')
        result = apply_template('{name} {seq}', mem, 0)
        self.assertEqual('OLD 1', result.value)

    def test_bracket_in_output_is_not_error(self):
        mem = self._make_memory(name='[TEST]')
        result = apply_template('{name}', mem, 0)
        self.assertTrue(result.ok)
        self.assertEqual('[TEST]', result.value)

    def test_conditional_match(self):
        mem = self._make_memory(duplex='+')
        result = apply_template('{duplex?+=RPTR|GMRS}', mem, 0)
        self.assertEqual('RPTR', result.value)

    def test_conditional_fallback(self):
        mem = self._make_memory(duplex='')
        result = apply_template('{duplex?+=RPTR|GMRS}', mem, 0)
        self.assertEqual('GMRS', result.value)

    def test_conditional_no_fallback_passthrough(self):
        mem = self._make_memory(mode='AM')
        result = apply_template('{mode?FM=F|NFM=N}', mem, 0)
        self.assertEqual('AM', result.value)

    def test_conditional_multi_match(self):
        mem = self._make_memory(mode='NFM')
        result = apply_template(
            '{mode?FM=F|NFM=N|AM=A|?}', mem, 0)
        self.assertEqual('N', result.value)

    def test_conditional_with_other_tokens(self):
        mem = self._make_memory(duplex='+')
        result = apply_template(
            '{duplex?+=RPT|SX} {seq:02d}', mem, 0)
        self.assertEqual('RPT 01', result.value)

    def test_conditional_case_insensitive_field(self):
        mem = self._make_memory(duplex='+')
        result = apply_template(
            '{DUPLEX?+=RPTR|GMRS}', mem, 0)
        self.assertEqual('RPTR', result.value)

    def test_conditional_with_nested_token(self):
        mem = self._make_memory(
            freq=462562500, duplex='+')
        result = apply_template(
            '{duplex?+={freq:.1f}|SIMPLEX}', mem, 0)
        self.assertTrue(result.ok)
        self.assertEqual('462.6', result.value)

    def test_conditional_with_nested_token_fallback(self):
        mem = self._make_memory(
            freq=462562500, duplex='')
        result = apply_template(
            '{duplex?+={freq:.1f}|SIMPLEX}', mem, 0)
        self.assertTrue(result.ok)
        self.assertEqual('SIMPLEX', result.value)

    def test_conditional_unknown_field_error(self):
        mem = self._make_memory()
        result = apply_template(
            '{bogus?a=b|c}', mem, 0)
        self.assertFalse(result.ok)
        self.assertIn('bogus', result.error)


class TestResolveConditionals(base.BaseTest):
    def test_simple_match(self):
        d = CaseInsensitiveDict({'duplex': '+'})
        result = resolve_conditionals(
            '{duplex?+=RPTR|GMRS}', d)
        self.assertEqual('RPTR', result)

    def test_fallback(self):
        d = CaseInsensitiveDict({'duplex': ''})
        result = resolve_conditionals(
            '{duplex?+=RPTR|GMRS}', d)
        self.assertEqual('GMRS', result)

    def test_no_fallback_passthrough(self):
        d = CaseInsensitiveDict({'mode': 'AM'})
        result = resolve_conditionals(
            '{mode?FM=F|NFM=N}', d)
        self.assertEqual('AM', result)

    def test_multi_value_map(self):
        d = CaseInsensitiveDict({'mode': 'NFM'})
        result = resolve_conditionals(
            '{mode?FM=F|NFM=N|AM=A|?}', d)
        self.assertEqual('N', result)

    def test_negated_match(self):
        d = CaseInsensitiveDict({'duplex': ''})
        result = resolve_conditionals(
            '{duplex?!+=SPLX|RPT}', d)
        self.assertEqual('SPLX', result)

    def test_negated_no_match(self):
        d = CaseInsensitiveDict({'duplex': '+'})
        result = resolve_conditionals(
            '{duplex?!+=SPLX|RPT}', d)
        self.assertEqual('RPT', result)

    def test_negated_empty(self):
        d = CaseInsensitiveDict({'duplex': '+'})
        result = resolve_conditionals(
            '{duplex?!=HAS|NONE}', d)
        self.assertEqual('HAS', result)

    def test_negated_empty_matches(self):
        d = CaseInsensitiveDict({'duplex': ''})
        result = resolve_conditionals(
            '{duplex?!=HAS|NONE}', d)
        self.assertEqual('NONE', result)

    def test_preserves_other_tokens(self):
        d = CaseInsensitiveDict(
            {'duplex': '+', 'seq': 1})
        result = resolve_conditionals(
            '{duplex?+=RPT|SX} {seq}', d)
        self.assertEqual('RPT {seq}', result)

    def test_unknown_field_raises(self):
        d = CaseInsensitiveDict({'duplex': '+'})
        with self.assertRaises(KeyError):
            resolve_conditionals('{bogus?a=b}', d)

    def test_replacement_with_equals(self):
        d = CaseInsensitiveDict({'mode': 'FM'})
        result = resolve_conditionals(
            '{mode?FM=x=y|other}', d)
        self.assertEqual('x=y', result)

    def test_empty_replacement(self):
        d = CaseInsensitiveDict({'duplex': '+'})
        result = resolve_conditionals(
            '{duplex?+=|GMRS}', d)
        self.assertEqual('', result)

    def test_case_insensitive_field(self):
        d = CaseInsensitiveDict({'duplex': '+'})
        result = resolve_conditionals(
            '{DUPLEX?+=RPTR|GMRS}', d)
        self.assertEqual('RPTR', result)


class TestResolveArithmetic(base.BaseTest):
    def test_addition(self):
        d = CaseInsensitiveDict({'num': 5})
        result = resolve_arithmetic('{num+1}', d)
        self.assertEqual(6, d[result.strip('{}')])

    def test_subtraction(self):
        d = CaseInsensitiveDict({'num': 5})
        result = resolve_arithmetic('{num-1}', d)
        self.assertEqual(4, d[result.strip('{}')])

    def test_multiplication(self):
        d = CaseInsensitiveDict({'num': 5})
        result = resolve_arithmetic('{num*2}', d)
        self.assertEqual(10, d[result.strip('{}')])

    def test_modulo(self):
        d = CaseInsensitiveDict({'freq_khz': 462562})
        result = resolve_arithmetic(
            '{freq_khz%1000}', d)
        self.assertEqual(
            562, d[result.strip('{}')])

    def test_integer_division(self):
        d = CaseInsensitiveDict({'freq_khz': 462562})
        result = resolve_arithmetic(
            '{freq_khz//1000}', d)
        self.assertEqual(
            462, d[result.strip('{}')])

    def test_preserves_format_spec(self):
        d = CaseInsensitiveDict({'freq_khz': 462600})
        result = resolve_arithmetic(
            '{freq_khz%1000:03d}', d)
        self.assertIn(':03d', result)

    def test_preserves_other_tokens(self):
        d = CaseInsensitiveDict(
            {'num': 5, 'name': 'TEST'})
        result = resolve_arithmetic(
            '{num+1} {name}', d)
        self.assertIn('{name}', result)

    def test_unknown_field_raises(self):
        d = CaseInsensitiveDict({'num': 5})
        with self.assertRaises(KeyError):
            resolve_arithmetic('{bogus+1}', d)

    def test_non_numeric_raises(self):
        d = CaseInsensitiveDict({'name': 'TEST'})
        with self.assertRaises(ValueError):
            resolve_arithmetic('{name+1}', d)

    def test_division_by_zero_raises(self):
        d = CaseInsensitiveDict({'num': 5})
        with self.assertRaises(ValueError):
            resolve_arithmetic('{num%0}', d)

    def test_float_result_becomes_int(self):
        d = CaseInsensitiveDict({'freq': 462.5})
        result = resolve_arithmetic(
            '{freq*1000}', d)
        key = result.strip('{}')
        # 462.5 * 1000 = 462500.0, converted to int
        self.assertEqual(462500, d[key])

    def test_case_insensitive_field(self):
        d = CaseInsensitiveDict({'num': 5})
        result = resolve_arithmetic('{NUM+1}', d)
        self.assertEqual(6, d[result.strip('{}')])


class TestApplyTemplateArithmetic(base.BaseTest):
    def _make_memory(self, **kwargs):
        mem = chirp_common.Memory()
        mem.freq = 462562500
        mem.number = 5
        mem.name = 'GMRS 5'
        mem.offset = 5000000
        mem.duplex = '+'
        mem.tmode = ''
        mem.rtone = 88.5
        mem.ctone = 88.5
        mem.dtcs = 23
        mem.mode = 'FM'
        mem.tuning_step = 12.5
        mem.skip = ''
        mem.comment = ''
        for k, v in kwargs.items():
            setattr(mem, k, v)
        return mem

    def test_freq_khz_token(self):
        mem = self._make_memory(freq=462562500)
        result = apply_template('{freq_khz}', mem, 0)
        self.assertEqual('462562', result.value)

    def test_freq_khz_modulo(self):
        mem = self._make_memory(freq=462600000)
        result = apply_template(
            '{freq_khz%1000:03d}', mem, 0)
        self.assertEqual('600', result.value)

    def test_freq_khz_modulo_625(self):
        mem = self._make_memory(freq=462625000)
        result = apply_template(
            '{freq_khz%1000:03d}', mem, 0)
        self.assertEqual('625', result.value)

    def test_arithmetic_with_conditional(self):
        mem = self._make_memory(
            freq=462600000, duplex='+')
        result = apply_template(
            '{duplex?+=R|G}{freq_khz%1000:03d}',
            mem, 0)
        self.assertEqual('R600', result.value)

    def test_num_plus_one(self):
        mem = self._make_memory(number=5)
        result = apply_template(
            'CH{num+1:03d}', mem, 0)
        self.assertEqual('CH006', result.value)
