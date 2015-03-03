import mox
from tests.unit import base

__builtins__["_"] = lambda s: s

from chirp.ui import memedit


class TestEdits(base.BaseTest):
    def _test_tone_column_change(self, col,
                                 ini_tmode='', ini_cmode='',
                                 exp_tmode=None, exp_cmode=None):
        editor = self.mox.CreateMock(memedit.MemoryEditor)
        editor._config = self.mox.CreateMockAnything()
        editor._config.get_bool("no_smart_tmode").AndReturn(False)
        editor.col = lambda x: x
        editor.store = self.mox.CreateMockAnything()
        editor.store.get_iter('path').AndReturn('iter')
        editor.store.get('iter', 'Tone Mode', 'Cross Mode').AndReturn(
            (ini_tmode, ini_cmode))
        if exp_tmode:
            editor.store.set('iter', 'Tone Mode', exp_tmode)
        if exp_cmode and col != 'Cross Mode':
            editor.store.set('iter', 'Cross Mode', exp_cmode)
        self.mox.ReplayAll()
        memedit.MemoryEditor.ed_tone_field(editor, None, 'path', None, col)

    def _test_auto_tone_mode(self, col, exp_tmode, exp_cmode):
        cross_exp_cmode = (exp_tmode == "Cross" and exp_cmode or None)

        # No tmode -> expected tmode, maybe requires cross mode change
        self._test_tone_column_change(col, exp_tmode=exp_tmode,
                                      exp_cmode=cross_exp_cmode)

        # Expected tmode does not re-set tmode, may change cmode
        self._test_tone_column_change(col, ini_tmode=exp_tmode,
                                      exp_cmode=cross_exp_cmode)

        # Invalid tmode -> expected, may change cmode
        self._test_tone_column_change(col, ini_tmode="foo",
                                      exp_tmode=exp_tmode,
                                      exp_cmode=cross_exp_cmode)

        # Expected cmode does not re-set cmode
        self._test_tone_column_change(col, ini_tmode="Cross",
                                      ini_cmode=exp_cmode)

        # Invalid cmode -> expected
        self._test_tone_column_change(col, ini_tmode="Cross",
                                      ini_cmode="foo", exp_cmode=exp_cmode)

    def test_auto_tone_mode_tone(self):
        self._test_auto_tone_mode('Tone', 'Tone', 'Tone->Tone')

    def test_auto_tone_mode_tsql(self):
        self._test_auto_tone_mode('ToneSql', 'TSQL', 'Tone->Tone')

    def test_auto_tone_mode_dtcs(self):
        self._test_auto_tone_mode('DTCS Code', 'DTCS', 'DTCS->')

    def test_auto_tone_mode_dtcs_rx(self):
        self._test_auto_tone_mode('DTCS Rx Code', 'Cross', '->DTCS')

    def test_auto_tone_mode_dtcs_pol(self):
        self._test_auto_tone_mode('DTCS Pol', 'DTCS', 'DTCS->')

    def test_auto_tone_mode_cross(self):
        self._test_auto_tone_mode('Cross Mode', 'Cross', 'Tone->Tone')
