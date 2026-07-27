import sys
import tempfile
from unittest import mock

from chirp import chirp_common

sys.modules['wx'] = wx = mock.MagicMock()
sys.modules['wx.adv'] = mock.MagicMock()
# wx.Colour is normally a real color object; make it a passthrough so
# tests can assert on the plain '#RRGGBB' strings the controller passes
# in, without needing a real wx runtime.
wx.Colour = lambda v: v

from chirp.memcolors import categories  # noqa
from chirp.memcolors import profile as profile_mod  # noqa
from chirp.memcolors import rules  # noqa
from chirp.wxui import config  # noqa
from chirp.wxui import memcolors  # noqa
from tests.unit import base  # noqa


def _mem(freq, duplex='', offset=600000, mode='FM', name=''):
    m = chirp_common.Memory(1, name=name)
    m.freq = freq
    m.duplex = duplex
    m.offset = offset
    m.mode = mode
    return m


class ColorCodingControllerTest(base.BaseTest):
    def setUp(self):
        super().setUp()
        tmpdir = tempfile.mkdtemp()
        config._CONFIG = config.ChirpConfig(tmpdir)
        self.ctrl = memcolors.ColorCodingController()

    def test_defaults_when_nothing_saved(self):
        self.assertTrue(self.ctrl.profile.enabled)
        self.assertEqual((), self.ctrl.profile.load_warnings)

    def test_save_and_reload_round_trips(self):
        self.ctrl.profile.enabled = False
        self.ctrl.save()

        ctrl2 = memcolors.ColorCodingController()
        self.assertFalse(ctrl2.profile.enabled)

    def test_malformed_saved_profile_falls_back_to_defaults(self):
        conf = config.get(memcolors.CONF_SECTION)
        conf.set(memcolors.CONF_KEY, '{not valid json')
        ctrl2 = memcolors.ColorCodingController()
        self.assertTrue(ctrl2.profile.enabled)  # built-in default

    def test_style_for_disabled_feature_returns_none(self):
        self.ctrl.profile.enabled = False
        m = _mem(146850000, duplex='-')
        self.assertIsNone(self.ctrl.style_for(m, 'freq'))

    def test_style_for_repeater_matches_category_defaults(self):
        m = _mem(146850000, duplex='-')
        style = self.ctrl.style_for(m, 'freq')
        self.assertIsNotNone(style)
        bg, fg, bold = style
        cat = categories.default_category(categories.HAM_REPEATER)
        self.assertEqual(cat.default_bg, bg)
        self.assertEqual(cat.default_fg, fg)

    def test_style_for_disabled_category_returns_none(self):
        state = self.ctrl.profile.category_state(categories.HAM_REPEATER)
        state.enabled = False
        self.ctrl.profile.set_category_state(categories.HAM_REPEATER, state)
        m = _mem(146850000, duplex='-')
        self.assertIsNone(self.ctrl.style_for(m, 'freq'))

    def test_selected_columns_mode_limits_columns(self):
        self.ctrl.profile.apply_mode = profile_mod.APPLY_COLUMNS
        self.ctrl.profile.selected_columns = ('freq',)
        m = _mem(146850000, duplex='-')
        self.assertIsNotNone(self.ctrl.style_for(m, 'freq'))
        self.assertIsNone(self.ctrl.style_for(m, 'comment'))

    def test_rule_override_wins_over_category(self):
        rule = rules.Rule(
            name='Special', enabled=True, priority=0,
            conditions=(rules.Condition(rules.FIELD_FREQ, rules.OP_EQ,
                                        146850000),),
            bg='#123456', fg='#ABCDEF', bold=True)
        self.ctrl.profile.add_rule(rule)
        m = _mem(146850000, duplex='-')
        bg, fg, bold = self.ctrl.style_for(m, 'freq')
        self.assertEqual('#123456', bg)
        self.assertEqual('#ABCDEF', fg)
        self.assertTrue(bold)

    def test_cache_invalidated_on_save(self):
        m = _mem(146850000, duplex='-')
        self.ctrl.classify(m)
        self.assertEqual(1, len(self.ctrl._cache))

        # A profile change must invalidate the cache -- classify() would
        # otherwise keep returning a stale result forever.
        self.ctrl.profile.enabled = False
        self.ctrl.save()
        self.assertEqual(0, len(self.ctrl._cache))
        self.assertIsNone(self.ctrl.classify(m))

    def test_cache_invalidated_on_memory_field_change(self):
        m = _mem(146850000, duplex='-')
        r1 = self.ctrl.classify(m)
        self.assertEqual(categories.HAM_REPEATER, r1.category_id)

        m.duplex = ''
        r2 = self.ctrl.classify(m)
        self.assertEqual(categories.HAM_SIMPLEX, r2.category_id)

    def test_listener_notified_on_save(self):
        calls = []
        self.ctrl.add_listener(lambda: calls.append(1))
        self.ctrl.save()
        self.assertEqual(1, len(calls))

    def test_listener_removed(self):
        calls = []
        cb = lambda: calls.append(1)  # noqa: E731
        self.ctrl.add_listener(cb)
        self.ctrl.remove_listener(cb)
        self.ctrl.save()
        self.assertEqual(0, len(calls))

    def test_discard_changes_reverts_unsaved_edits(self):
        self.ctrl.profile.enabled = False  # never saved
        self.ctrl.discard_changes()
        self.assertTrue(self.ctrl.profile.enabled)

    def test_replace_profile_persists(self):
        new_profile = profile_mod.default_profile()
        new_profile.enabled = False
        self.ctrl.replace_profile(new_profile)

        ctrl2 = memcolors.ColorCodingController()
        self.assertFalse(ctrl2.profile.enabled)

    def test_flag_invalid_skipped_for_receive_only(self):
        self.ctrl.profile.flag_invalid = True
        m = _mem(146850000, duplex='off')

        class FakeFeatures:
            def validate_memory(self, mem):
                return [chirp_common.ValidationError('out of range')]

        class FakeRadio:
            def get_features(self):
                return FakeFeatures()

        # duplex == 'off' short-circuits validation entirely, per
        # classifier.classify()'s documented rationale.
        self.assertIsNone(self.ctrl.validation_errors_for(FakeRadio(), m))

    def test_flag_invalid_applies_for_transmitting_memory(self):
        self.ctrl.profile.flag_invalid = True
        m = _mem(146850000, duplex='-')

        class FakeFeatures:
            def validate_memory(self, mem):
                return [chirp_common.ValidationError('out of range')]

        class FakeRadio:
            def get_features(self):
                return FakeFeatures()

        errors = self.ctrl.validation_errors_for(FakeRadio(), m)
        self.assertEqual(1, len(errors))


if __name__ == '__main__':
    import unittest
    unittest.main()
