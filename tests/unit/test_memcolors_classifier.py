import unittest

from chirp import chirp_common
from chirp.memcolors import categories
from chirp.memcolors import classifier
from chirp.memcolors import rules


def _mem(freq, duplex='', offset=600000, mode='FM', tmode='', name='',
         comment='', skip='', empty=False):
    m = chirp_common.Memory(1, empty=empty, name=name)
    m.freq = freq
    m.duplex = duplex
    m.offset = offset
    m.mode = mode
    m.tmode = tmode
    m.comment = comment
    m.skip = skip
    return m


class ClassifierPrecedenceTest(unittest.TestCase):
    def test_ham_repeater_minus(self):
        m = _mem(146850000, duplex='-', offset=600000)
        self.assertEqual(categories.HAM_REPEATER,
                         classifier.classify(m).category_id)

    def test_ham_repeater_plus(self):
        m = _mem(146850000, duplex='+', offset=600000)
        self.assertEqual(categories.HAM_REPEATER,
                         classifier.classify(m).category_id)

    def test_ham_repeater_no_tone_still_repeater(self):
        # Repeater semantics come from duplex/offset, never tone alone.
        m = _mem(146850000, duplex='-', offset=600000, tmode='')
        self.assertEqual(categories.HAM_REPEATER,
                         classifier.classify(m).category_id)

    def test_ham_repeater_split(self):
        m = _mem(146850000, duplex='split', offset=147450000)
        self.assertEqual(categories.HAM_REPEATER,
                         classifier.classify(m).category_id)

    def test_ham_simplex(self):
        m = _mem(146555000, duplex='')
        self.assertEqual(categories.HAM_SIMPLEX,
                         classifier.classify(m).category_id)

    def test_ham_simplex_requires_no_offset(self):
        # "split" with tx == rx is not a real cross-frequency operation.
        m = _mem(146555000, duplex='split', offset=146555000)
        self.assertNotEqual(categories.HAM_REPEATER,
                            classifier.classify(m).category_id)

    def test_ham_calling_overrides_simplex(self):
        m = _mem(146520000, duplex='')
        self.assertEqual(categories.HAM_CALLING,
                         classifier.classify(m).category_id)

    def test_ham_calling_70cm(self):
        m = _mem(446000000, duplex='')
        self.assertEqual(categories.HAM_CALLING,
                         classifier.classify(m).category_id)

    def test_ham_satellite(self):
        m = _mem(145900000, duplex='')
        self.assertEqual(categories.HAM_SATELLITE,
                         classifier.classify(m).category_id)

    def test_ham_aprs(self):
        m = _mem(144390000, duplex='', mode='FM')
        self.assertEqual(categories.HAM_APRS_DATA,
                         classifier.classify(m).category_id)

    def test_ham_digital_voice_by_mode(self):
        m = _mem(146900000, duplex='-', offset=600000, mode='DMR')
        # Digital voice mode outranks repeater-shape in the specialized
        # tier ordering (both are tier 5, but mode-based digital voice
        # is checked first since it's unambiguous).
        self.assertEqual(categories.HAM_DIGITAL_VOICE,
                         classifier.classify(m).category_id)

    def test_ham_beacon(self):
        m = _mem(28285000, duplex='')
        self.assertEqual(categories.HAM_BEACON_SPECIALTY,
                         classifier.classify(m).category_id)

    def test_ham_receive_only(self):
        m = _mem(146555000, duplex='off')
        self.assertEqual(categories.HAM_RECEIVE_ONLY,
                         classifier.classify(m).category_id)

    def test_ham_receive_only_does_not_override_satellite(self):
        # A satellite downlink-only entry stays "satellite", not
        # generic "receive-only" -- specialized (tier 5) outranks the
        # receive-only modifier (tier 7).
        m = _mem(145900000, duplex='off')
        self.assertEqual(categories.HAM_SATELLITE,
                         classifier.classify(m).category_id)

    def test_ham_general_fallback(self):
        m = _mem(146555000, duplex='+', offset=0)
        self.assertEqual(categories.HAM_GENERAL,
                         classifier.classify(m).category_id)

    def test_disabled_overrides_repeater(self):
        m = _mem(146850000, duplex='-', offset=600000, empty=True)
        self.assertEqual(categories.DISABLED,
                         classifier.classify(m).category_id)

    def test_skipped_is_disabled(self):
        m = _mem(146850000, duplex='-', offset=600000, skip='S')
        self.assertEqual(categories.DISABLED,
                         classifier.classify(m).category_id)

    def test_pilot_skip_is_disabled(self):
        m = _mem(146850000, skip='P')
        self.assertEqual(categories.DISABLED,
                         classifier.classify(m).category_id)

    def test_invalid_override(self):
        m = _mem(146850000, duplex='-', offset=600000)
        result = classifier.classify(m, validation_errors=['bad'])
        self.assertEqual(categories.INVALID, result.category_id)

    def test_invalid_beats_disabled(self):
        m = _mem(146850000, empty=True)
        result = classifier.classify(m, validation_errors=['bad'])
        self.assertEqual(categories.INVALID, result.category_id)

    def test_gmrs(self):
        m = _mem(462562500, duplex='')
        self.assertEqual(categories.FRS, classifier.classify(m).category_id)

    def test_gmrs_repeater_output(self):
        m = _mem(462550000, duplex='')
        self.assertEqual(categories.GMRS, classifier.classify(m).category_id)

    def test_gmrs_stays_gmrs_regardless_of_duplex(self):
        # No GMRS-specific repeater subclass is implemented -- GMRS
        # channels stay categorized as GMRS regardless of duplex shape.
        m = _mem(462550000, duplex='+', offset=5000000)
        self.assertEqual(categories.GMRS, classifier.classify(m).category_id)

    def test_murs(self):
        m = _mem(151820000, duplex='')
        self.assertEqual(categories.MURS, classifier.classify(m).category_id)

    def test_marine_emergency(self):
        m = _mem(156800000, duplex='')
        self.assertEqual(categories.EMERGENCY,
                         classifier.classify(m).category_id)

    def test_marine_plain(self):
        m = _mem(156450000, duplex='')
        self.assertEqual(categories.MARINE,
                         classifier.classify(m).category_id)

    def test_aviation(self):
        m = _mem(122800000, duplex='', mode='AM')
        self.assertEqual(categories.AVIATION,
                         classifier.classify(m).category_id)

    def test_aviation_emergency(self):
        m = _mem(121500000, duplex='', mode='AM')
        self.assertEqual(categories.AVIATION_EMERGENCY,
                         classifier.classify(m).category_id)

    def test_aviation_receive_only_not_invalid(self):
        # An RX-only memory outside a radio's TX range should not be
        # misreported as "invalid" merely because it can't transmit --
        # callers are expected to omit validation_errors for such
        # memories (see chirp.wxui.memcolors.validation_errors_for), and
        # classify() itself just honors whatever it's given.
        m = _mem(122800000, duplex='off', mode='AM')
        result = classifier.classify(m, validation_errors=None)
        self.assertNotEqual(categories.INVALID, result.category_id)
        self.assertEqual(categories.RECEIVE_ONLY, result.category_id)

    def test_weather(self):
        m = _mem(162400000, duplex='')
        self.assertEqual(categories.WEATHER,
                         classifier.classify(m).category_id)

    def test_railroad(self):
        m = _mem(160800000, duplex='')
        self.assertEqual(categories.RAILROAD,
                         classifier.classify(m).category_id)

    def test_unknown_fallback(self):
        m = _mem(88500000, duplex='')  # FM broadcast band
        self.assertEqual(categories.UNKNOWN,
                         classifier.classify(m).category_id)

    def test_receive_only_outranks_unknown(self):
        m = _mem(88500000, duplex='off')
        self.assertEqual(categories.RECEIVE_ONLY,
                         classifier.classify(m).category_id)


class UserRuleTest(unittest.TestCase):
    def test_user_rule_overrides_builtin(self):
        rule = rules.Rule(
            name='My Rule', enabled=True, priority=0,
            conditions=(rules.Condition(rules.FIELD_NAME, rules.OP_CONTAINS,
                                        'skywarn'),),
            bg='#FFEB3B', fg='#000000')
        m = _mem(146850000, duplex='-', offset=600000, name='SKYWARN net')
        result = classifier.classify(m, rules=(rule,))
        self.assertTrue(result.is_rule_override)
        self.assertEqual(rule, result.rule)
        # candidate category is preserved for reference even when a
        # rule overrides the color.
        self.assertEqual(categories.HAM_REPEATER, result.category_id)

    def test_user_rule_priority_order_lowest_wins(self):
        low = rules.Rule(
            name='Low', enabled=True, priority=0,
            conditions=(rules.Condition(rules.FIELD_FREQ, rules.OP_EQ,
                                        146520000),),
            bg='#111111', fg='#FFFFFF')
        high = rules.Rule(
            name='High', enabled=True, priority=5,
            conditions=(rules.Condition(rules.FIELD_FREQ, rules.OP_EQ,
                                        146520000),),
            bg='#222222', fg='#FFFFFF')
        m = _mem(146520000, duplex='')
        result = classifier.classify(m, rules=(high, low))
        self.assertEqual('Low', result.rule.name)

    def test_disabled_still_beats_user_rule(self):
        rule = rules.Rule(
            name='Always', enabled=True, priority=0,
            conditions=(rules.Condition(rules.FIELD_FREQ, rules.OP_RANGE,
                                        [0, 999999999999]),),
            bg='#111111', fg='#FFFFFF')
        m = _mem(146520000, empty=True)
        result = classifier.classify(m, rules=(rule,))
        self.assertFalse(result.is_rule_override)
        self.assertEqual(categories.DISABLED, result.category_id)

    def test_disabled_rule_not_matched(self):
        rule = rules.Rule(
            name='Off', enabled=False, priority=0,
            conditions=(rules.Condition(rules.FIELD_FREQ, rules.OP_EQ,
                                        146520000),),
            bg='#111111', fg='#FFFFFF')
        m = _mem(146520000, duplex='')
        result = classifier.classify(m, rules=(rule,))
        self.assertFalse(result.is_rule_override)

    def test_rule_can_match_on_builtin_classification(self):
        rule = rules.Rule(
            name='Repeaters get bold', enabled=True, priority=0,
            conditions=(rules.Condition(rules.FIELD_CLASSIFICATION,
                                        rules.OP_EQ,
                                        categories.HAM_REPEATER),),
            bg='#333333', fg='#FFFFFF', bold=True)
        m = _mem(146850000, duplex='-', offset=600000)
        result = classifier.classify(m, rules=(rule,))
        self.assertTrue(result.is_rule_override)


if __name__ == '__main__':
    unittest.main()
