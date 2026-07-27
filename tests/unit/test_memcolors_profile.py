import unittest

from chirp.memcolors import categories
from chirp.memcolors import contrast
from chirp.memcolors import profile as profile_mod
from chirp.memcolors import rules


class ContrastTest(unittest.TestCase):
    def test_black_on_white_max_contrast(self):
        self.assertAlmostEqual(21.0,
                               contrast.contrast_ratio('#000000', '#FFFFFF'),
                               places=1)

    def test_same_color_min_contrast(self):
        self.assertAlmostEqual(1.0,
                               contrast.contrast_ratio('#808080', '#808080'),
                               places=1)

    def test_order_independent(self):
        a = contrast.contrast_ratio('#123456', '#FEDCBA')
        b = contrast.contrast_ratio('#FEDCBA', '#123456')
        self.assertAlmostEqual(a, b, places=6)

    def test_invalid_hex_rejected(self):
        with self.assertRaises(ValueError):
            contrast.parse_hex_color('not-a-color')
        with self.assertRaises(ValueError):
            contrast.parse_hex_color('#FFF')  # 3-digit shorthand unsupported
        with self.assertRaises(ValueError):
            contrast.parse_hex_color('#FFFFFF00')  # alpha unsupported

    def test_is_valid_hex_color(self):
        self.assertTrue(contrast.is_valid_hex_color('#AABBCC'))
        self.assertFalse(contrast.is_valid_hex_color('AABBCC'))
        self.assertFalse(contrast.is_valid_hex_color(123))

    def test_all_default_categories_meet_aa(self):
        for cat in categories.DEFAULT_CATEGORIES:
            ratio = contrast.contrast_ratio(cat.default_fg, cat.default_bg)
            self.assertGreaterEqual(
                ratio, 4.5,
                'Category %r only has %.2f:1 contrast (needs >= 4.5:1)' % (
                    cat.id, ratio))


class DefaultProfileTest(unittest.TestCase):
    def test_default_profile_loads(self):
        p = profile_mod.default_profile()
        self.assertTrue(p.enabled)
        self.assertEqual(profile_mod.APPLY_ROW, p.apply_mode)
        self.assertEqual((), p.load_warnings)

    def test_category_state_falls_back_to_builtin(self):
        p = profile_mod.default_profile()
        state = p.category_state(categories.HAM_REPEATER)
        cat = categories.default_category(categories.HAM_REPEATER)
        self.assertEqual(cat.default_bg, state.bg)
        self.assertEqual(cat.default_fg, state.fg)

    def test_unknown_category_raises(self):
        p = profile_mod.default_profile()
        with self.assertRaises(KeyError):
            p.category_state('not_a_real_category')

    def test_set_and_reset_category(self):
        p = profile_mod.default_profile()
        new_state = profile_mod.CategoryState(
            bg='#000000', fg='#FFFFFF', enabled=True, bold=True, priority=0)
        p.set_category_state(categories.HAM_REPEATER, new_state)
        self.assertEqual('#000000', p.category_state(
            categories.HAM_REPEATER).bg)

        p.reset_category(categories.HAM_REPEATER)
        cat = categories.default_category(categories.HAM_REPEATER)
        self.assertEqual(cat.default_bg,
                         p.category_state(categories.HAM_REPEATER).bg)

    def test_reset_all_categories_does_not_touch_rules(self):
        p = profile_mod.default_profile()
        rule = rules.Rule(
            name='Test', enabled=True, priority=0,
            conditions=(rules.Condition(rules.FIELD_FREQ, rules.OP_EQ,
                                        146520000),),
            bg='#FFFFFF', fg='#000000')
        p.add_rule(rule)
        p.set_category_state(categories.HAM_REPEATER,
                             profile_mod.CategoryState(
                                 bg='#000000', fg='#FFFFFF', enabled=True,
                                 bold=False, priority=0))
        p.reset_all_categories()
        cat = categories.default_category(categories.HAM_REPEATER)
        self.assertEqual(cat.default_bg,
                         p.category_state(categories.HAM_REPEATER).bg)
        self.assertEqual(1, len(p.custom_rules))

    def test_enabled_categories_excludes_disabled(self):
        p = profile_mod.default_profile()
        state = p.category_state(categories.HAM_SIMPLEX)
        state.enabled = False
        p.set_category_state(categories.HAM_SIMPLEX, state)
        ids = [c for c, _s in p.enabled_categories()]
        self.assertNotIn(categories.HAM_SIMPLEX, ids)
        self.assertIn(categories.HAM_REPEATER, ids)

    def test_invalid_category_state_rejected(self):
        p = profile_mod.default_profile()
        bad = profile_mod.CategoryState(
            bg='not-a-color', fg='#FFFFFF', enabled=True, bold=False,
            priority=0)
        with self.assertRaises(profile_mod.ProfileValidationError):
            p.set_category_state(categories.HAM_REPEATER, bad)


class RuleOrderingTest(unittest.TestCase):
    def _rule(self, name, priority):
        return rules.Rule(
            name=name, enabled=True, priority=priority,
            conditions=(rules.Condition(rules.FIELD_FREQ, rules.OP_EQ,
                                        146520000),),
            bg='#FFFFFF', fg='#000000')

    def test_move_rule_up(self):
        p = profile_mod.default_profile()
        p.add_rule(self._rule('A', 0))
        p.add_rule(self._rule('B', 1))
        p.move_rule('B', -1)
        ordered = sorted(p.custom_rules, key=lambda r: r.priority)
        self.assertEqual('B', ordered[0].name)

    def test_move_rule_up_at_top_is_noop(self):
        p = profile_mod.default_profile()
        p.add_rule(self._rule('A', 0))
        p.add_rule(self._rule('B', 1))
        p.move_rule('A', -1)
        ordered = sorted(p.custom_rules, key=lambda r: r.priority)
        self.assertEqual('A', ordered[0].name)

    def test_remove_rule(self):
        p = profile_mod.default_profile()
        p.add_rule(self._rule('A', 0))
        p.remove_rule('A')
        self.assertEqual(0, len(p.custom_rules))


class SerializationTest(unittest.TestCase):
    def test_round_trip_default(self):
        p = profile_mod.default_profile()
        p2 = profile_mod.ColorProfile.from_json(p.to_json())
        self.assertEqual((), p2.load_warnings)
        self.assertEqual(p.enabled, p2.enabled)
        self.assertEqual(p.apply_mode, p2.apply_mode)
        self.assertEqual(p.selected_columns, p2.selected_columns)

    def test_round_trip_with_overrides_and_rules(self):
        p = profile_mod.default_profile()
        p.set_category_state(categories.HAM_REPEATER,
                             profile_mod.CategoryState(
                                 bg='#010203', fg='#FFFFFF', enabled=False,
                                 bold=True, priority=9))
        p.add_rule(rules.Rule(
            name='Net', enabled=True, priority=0,
            conditions=(rules.Condition(rules.FIELD_NAME, rules.OP_CONTAINS,
                                        'net'),),
            bg='#ABCDEF', fg='#000000', bold=True))
        p.apply_mode = profile_mod.APPLY_COLUMNS
        p.selected_columns = ('freq', 'name')

        p2 = profile_mod.ColorProfile.from_json(p.to_json())
        self.assertEqual((), p2.load_warnings)
        state = p2.category_state(categories.HAM_REPEATER)
        self.assertEqual('#010203', state.bg)
        self.assertFalse(state.enabled)
        self.assertEqual(1, len(p2.custom_rules))
        self.assertEqual('Net', p2.custom_rules[0].name)
        self.assertEqual(profile_mod.APPLY_COLUMNS, p2.apply_mode)
        self.assertEqual(('freq', 'name'), p2.selected_columns)

    def test_malformed_json_raises(self):
        with self.assertRaises(profile_mod.ProfileValidationError):
            profile_mod.ColorProfile.from_json('{not valid json')

    def test_non_dict_json_raises(self):
        with self.assertRaises(profile_mod.ProfileValidationError):
            profile_mod.ColorProfile.from_json('[1, 2, 3]')

    def test_missing_schema_version_raises(self):
        with self.assertRaises(profile_mod.ProfileValidationError):
            profile_mod.ColorProfile.from_dict({'profile_name': 'x'})

    def test_future_schema_version_raises(self):
        with self.assertRaises(profile_mod.ProfileValidationError):
            profile_mod.ColorProfile.from_dict(
                {'schema_version': 999999})

    def test_malformed_category_override_recovers_with_warning(self):
        data = profile_mod.default_profile().to_dict()
        data['category_overrides'] = {
            categories.HAM_REPEATER: {'bg': 'garbage', 'fg': '#FFFFFF',
                                      'priority': 0},
        }
        p = profile_mod.ColorProfile.from_dict(data)
        self.assertTrue(p.load_warnings)
        # Falls back to the built-in default for the broken category.
        cat = categories.default_category(categories.HAM_REPEATER)
        self.assertEqual(cat.default_bg,
                         p.category_state(categories.HAM_REPEATER).bg)

    def test_unknown_category_id_skipped_not_fatal(self):
        data = profile_mod.default_profile().to_dict()
        data['category_overrides'] = {
            'some_future_category': {'bg': '#000000', 'fg': '#FFFFFF',
                                     'priority': 0},
        }
        p = profile_mod.ColorProfile.from_dict(data)
        self.assertEqual((), p.load_warnings)

    def test_malformed_rule_dropped_with_warning(self):
        data = profile_mod.default_profile().to_dict()
        data['custom_rules'] = [{'name': 'bad'}]  # missing required fields
        p = profile_mod.ColorProfile.from_dict(data)
        self.assertTrue(p.load_warnings)
        self.assertEqual((), p.custom_rules)

    def test_invalid_apply_mode_recovers(self):
        data = profile_mod.default_profile().to_dict()
        data['apply_mode'] = 'sideways'
        p = profile_mod.ColorProfile.from_dict(data)
        self.assertTrue(p.load_warnings)
        self.assertEqual(profile_mod.APPLY_ROW, p.apply_mode)

    def test_unknown_region_recovers(self):
        data = profile_mod.default_profile().to_dict()
        data['region'] = 'MARS'
        p = profile_mod.ColorProfile.from_dict(data)
        self.assertTrue(p.load_warnings)
        self.assertEqual('US', p.region)


if __name__ == '__main__':
    unittest.main()
