import unittest

from chirp.memcolors import rules


class ConditionValidationTest(unittest.TestCase):
    def test_valid_freq_range(self):
        c = rules.Condition(rules.FIELD_FREQ, rules.OP_RANGE,
                            [144000000, 148000000])
        c.validate()  # does not raise

    def test_freq_range_wrong_order_rejected(self):
        c = rules.Condition(rules.FIELD_FREQ, rules.OP_RANGE,
                            [148000000, 144000000])
        with self.assertRaises(rules.RuleValidationError):
            c.validate()

    def test_freq_requires_int(self):
        c = rules.Condition(rules.FIELD_FREQ, rules.OP_EQ, 'not an int')
        with self.assertRaises(rules.RuleValidationError):
            c.validate()

    def test_unknown_field_rejected(self):
        c = rules.Condition('made_up_field', rules.OP_EQ, 1)
        with self.assertRaises(rules.RuleValidationError):
            c.validate()

    def test_op_not_valid_for_field_rejected(self):
        # "contains" only makes sense for text fields.
        c = rules.Condition(rules.FIELD_FREQ, rules.OP_CONTAINS, '146')
        with self.assertRaises(rules.RuleValidationError):
            c.validate()

    def test_receive_only_requires_bool(self):
        c = rules.Condition(rules.FIELD_RECEIVE_ONLY, rules.OP_EQ, 'yes')
        with self.assertRaises(rules.RuleValidationError):
            c.validate()
        c2 = rules.Condition(rules.FIELD_RECEIVE_ONLY, rules.OP_EQ, True)
        c2.validate()

    def test_text_field_requires_string(self):
        c = rules.Condition(rules.FIELD_NAME, rules.OP_EQ, 123)
        with self.assertRaises(rules.RuleValidationError):
            c.validate()

    def test_matches_missing_field_in_context_is_false(self):
        c = rules.Condition(rules.FIELD_FREQ, rules.OP_EQ, 100)
        self.assertFalse(c.matches({}))

    def test_matches_contains_case_insensitive(self):
        c = rules.Condition(rules.FIELD_NAME, rules.OP_CONTAINS, 'Net')
        self.assertTrue(c.matches({rules.FIELD_NAME: 'SKYWARN net control'}))
        self.assertFalse(c.matches({rules.FIELD_NAME: 'simplex'}))

    def test_from_dict_round_trip(self):
        c = rules.Condition(rules.FIELD_MODE, rules.OP_IN, ['FM', 'NFM'])
        c2 = rules.Condition.from_dict(c.to_dict())
        self.assertEqual(c.field, c2.field)
        self.assertEqual(c.op, c2.op)
        self.assertEqual(c.value, c2.value)

    def test_from_dict_missing_key_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.Condition.from_dict({'field': rules.FIELD_FREQ})

    def test_from_dict_non_dict_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.Condition.from_dict('not a dict')


class RuleValidationTest(unittest.TestCase):
    def _cond(self):
        return rules.Condition(rules.FIELD_FREQ, rules.OP_EQ, 146520000)

    def test_valid_rule(self):
        r = rules.Rule(name='Test', enabled=True, priority=0,
                       conditions=(self._cond(),), bg='#FFFFFF',
                       fg='#000000')
        r.validate()  # does not raise

    def test_empty_name_rejected(self):
        r = rules.Rule(name='', enabled=True, priority=0,
                       conditions=(self._cond(),), bg='#FFFFFF',
                       fg='#000000')
        with self.assertRaises(rules.RuleValidationError):
            r.validate()

    def test_no_conditions_rejected(self):
        r = rules.Rule(name='Test', enabled=True, priority=0,
                       conditions=(), bg='#FFFFFF', fg='#000000')
        with self.assertRaises(rules.RuleValidationError):
            r.validate()

    def test_invalid_color_rejected(self):
        r = rules.Rule(name='Test', enabled=True, priority=0,
                       conditions=(self._cond(),), bg='not-a-color',
                       fg='#000000')
        with self.assertRaises(rules.RuleValidationError):
            r.validate()

    def test_invalid_condition_propagates(self):
        bad_cond = rules.Condition('nonsense', rules.OP_EQ, 1)
        r = rules.Rule(name='Test', enabled=True, priority=0,
                       conditions=(bad_cond,), bg='#FFFFFF', fg='#000000')
        with self.assertRaises(rules.RuleValidationError):
            r.validate()

    def test_matches_ands_all_conditions(self):
        r = rules.Rule(
            name='Test', enabled=True, priority=0,
            conditions=(
                rules.Condition(rules.FIELD_FREQ, rules.OP_EQ, 146520000),
                rules.Condition(rules.FIELD_MODE, rules.OP_EQ, 'FM'),
            ), bg='#FFFFFF', fg='#000000')
        self.assertTrue(r.matches({rules.FIELD_FREQ: 146520000,
                                   rules.FIELD_MODE: 'FM'}))
        self.assertFalse(r.matches({rules.FIELD_FREQ: 146520000,
                                    rules.FIELD_MODE: 'AM'}))

    def test_from_dict_round_trip(self):
        r = rules.Rule(name='Test', enabled=False, priority=3,
                       conditions=(self._cond(),), bg='#FFFFFF',
                       fg='#000000', bold=True, description='desc')
        r2 = rules.Rule.from_dict(r.to_dict())
        self.assertEqual(r.name, r2.name)
        self.assertEqual(r.enabled, r2.enabled)
        self.assertEqual(r.priority, r2.priority)
        self.assertEqual(r.bold, r2.bold)
        self.assertEqual(len(r.conditions), len(r2.conditions))

    def test_from_dict_malformed_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.Rule.from_dict({'name': 'Test'})  # missing everything else

    def test_from_dict_no_eval_no_code_execution(self):
        # Values are plain JSON-safe types only -- confirm a
        # code-injection-shaped value is rejected, not executed.
        malicious = {
            'name': 'evil', 'priority': 0, 'bg': '#FFFFFF', 'fg': '#000000',
            'conditions': [{'field': rules.FIELD_NAME, 'op': rules.OP_EQ,
                           'value': '__import__("os").system("true")'}],
        }
        # This should just be treated as a literal string match, never
        # executed.
        r = rules.Rule.from_dict(malicious)
        self.assertFalse(r.matches({rules.FIELD_NAME: 'harmless'}))


class MatchContextTest(unittest.TestCase):
    def test_find_matching_rule_respects_enabled(self):
        r1 = rules.Rule(name='A', enabled=False, priority=0,
                        conditions=(rules.Condition(
                            rules.FIELD_FREQ, rules.OP_EQ, 1),),
                        bg='#FFFFFF', fg='#000000')
        r2 = rules.Rule(name='B', enabled=True, priority=1,
                        conditions=(rules.Condition(
                            rules.FIELD_FREQ, rules.OP_EQ, 1),),
                        bg='#FFFFFF', fg='#000000')
        found = rules.find_matching_rule([r1, r2], {rules.FIELD_FREQ: 1})
        self.assertEqual('B', found.name)

    def test_find_matching_rule_none(self):
        found = rules.find_matching_rule([], {rules.FIELD_FREQ: 1})
        self.assertIsNone(found)


if __name__ == '__main__':
    unittest.main()
