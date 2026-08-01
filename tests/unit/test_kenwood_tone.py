from tests.unit import base
from chirp import chirp_common
from chirp import kenwood_tone


class MockMemory:
    def __init__(self):
        self.rxtone = 0x0000
        self.txtone = 0x0000


class TestKenwoodToneModelInit(base.BaseTest):
    def test_init_valid_params(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000)
        self.assertEqual(model.dcs_base, 0x4000)
        self.assertEqual(model.pol_mask, 0x2000)
        self.assertEqual(model.tone_init, 0x0000)
        self.assertEqual(model.tone_flag, 0x8000)
        self.assertEqual(model.dcs_enc_base, 8)
        self.assertEqual(model.tone_enc_base, 10)

    def test_init_custom_params(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x2800, pol_mask=0x8000,
            tone_init=0xFFFF, tone_flag=0x0000,
            dcs_enc_base=10, tone_enc_base=16)
        self.assertEqual(model.dcs_base, 0x2800)
        self.assertEqual(model.pol_mask, 0x8000)
        self.assertEqual(model.tone_init, 0xFFFF)
        self.assertEqual(model.tone_flag, 0x0000)
        self.assertEqual(model.dcs_enc_base, 10)
        self.assertEqual(model.tone_enc_base, 16)

    def test_init_invalid_dcs_enc_base(self):
        with self.assertRaises(AssertionError):
            kenwood_tone.KenwoodToneModel(
                dcs_base=0x4000, pol_mask=0x2000, dcs_enc_base=15)

    def test_init_invalid_tone_enc_base(self):
        with self.assertRaises(AssertionError):
            kenwood_tone.KenwoodToneModel(
                dcs_base=0x4000, pol_mask=0x2000, tone_enc_base=15)


class TestGetToneVal(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.model_8_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000)
        self.model_10_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10)
        self.model_16_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16)
        self.model_8_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            tone_enc_base=16)
        self.model_10_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10, tone_enc_base=16)
        self.model_16_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16, tone_enc_base=16)

    def test_get_tone_val_zero_8_10(self):
        code, pol = self.model_8_10._get_tone_val(0x0000)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_zero_10_10(self):
        code, pol = self.model_10_10._get_tone_val(0x0000)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_zero_16_10(self):
        code, pol = self.model_16_10._get_tone_val(0x0000)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_zero_8_16(self):
        code, pol = self.model_8_16._get_tone_val(0x0000)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_zero_10_16(self):
        code, pol = self.model_10_16._get_tone_val(0x0000)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_zero_16_16(self):
        code, pol = self.model_16_16._get_tone_val(0x0000)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_ffff_8_10(self):
        code, pol = self.model_8_10._get_tone_val(0xFFFF)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_ffff_10_10(self):
        code, pol = self.model_10_10._get_tone_val(0xFFFF)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_ffff_16_10(self):
        code, pol = self.model_16_10._get_tone_val(0xFFFF)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_ffff_8_16(self):
        code, pol = self.model_8_16._get_tone_val(0xFFFF)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_ffff_10_16(self):
        code, pol = self.model_10_16._get_tone_val(0xFFFF)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_ffff_16_16(self):
        code, pol = self.model_16_16._get_tone_val(0xFFFF)
        self.assertIsNone(code)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_8_10(self):
        code, pol = self.model_8_10._get_tone_val(885 + 0x8000)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_10_10(self):
        code, pol = self.model_10_10._get_tone_val(885 + 0x8000)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_16_10(self):
        code, pol = self.model_16_10._get_tone_val(885 + 0x8000)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_8_16(self):
        code, pol = self.model_8_16._get_tone_val(0x0885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_10_16(self):
        code, pol = self.model_10_16._get_tone_val(0x0885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_16_16(self):
        code, pol = self.model_16_16._get_tone_val(0x0885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_no_flag_8_10(self):
        code, pol = self.model_8_10._get_tone_val(885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_no_flag_10_10(self):
        code, pol = self.model_10_10._get_tone_val(885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_no_flag_16_10(self):
        code, pol = self.model_16_10._get_tone_val(885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_no_flag_8_16(self):
        code, pol = self.model_8_16._get_tone_val(0x0885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_no_flag_10_16(self):
        code, pol = self.model_10_16._get_tone_val(0x0885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_ctcss_no_flag_16_16(self):
        code, pol = self.model_16_16._get_tone_val(0x0885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_get_tone_val_dcs_normal_polarity_8_10(self):
        code, pol = self.model_8_10._get_tone_val(0x4000 + 0o023)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_normal_polarity_10_10(self):
        code, pol = self.model_10_10._get_tone_val(0x4000 + 23)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_normal_polarity_16_10(self):
        code, pol = self.model_16_10._get_tone_val(0x4000 + 0x023)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_normal_polarity_8_16(self):
        code, pol = self.model_8_16._get_tone_val(0x4000 + 0o023)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_normal_polarity_10_16(self):
        code, pol = self.model_10_16._get_tone_val(0x4000 + 23)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_normal_polarity_16_16(self):
        code, pol = self.model_16_16._get_tone_val(0x4000 + 0x023)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_reverse_polarity_8_10(self):
        code, pol = self.model_8_10._get_tone_val(0x4000 + 0o023 + 0x2000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_get_tone_val_dcs_reverse_polarity_10_10(self):
        code, pol = self.model_10_10._get_tone_val(0x4000 + 23 + 0x2000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_get_tone_val_dcs_reverse_polarity_16_10(self):
        code, pol = self.model_16_10._get_tone_val(0x4000 + 0x023 + 0x2000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_get_tone_val_dcs_reverse_polarity_8_16(self):
        code, pol = self.model_8_16._get_tone_val(0x4000 + 0o023 + 0x2000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_get_tone_val_dcs_reverse_polarity_10_16(self):
        code, pol = self.model_10_16._get_tone_val(0x4000 + 23 + 0x2000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_get_tone_val_dcs_reverse_polarity_16_16(self):
        code, pol = self.model_16_16._get_tone_val(0x4000 + 0x023 + 0x2000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_get_tone_val_dcs_octal_encoding_large_code_8_10(self):
        code, pol = self.model_8_10._get_tone_val(0x4000 + 0o754)
        self.assertEqual(code, 754)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_octal_encoding_large_code_10_10(self):
        code, pol = self.model_10_10._get_tone_val(0x4000 + 754)
        self.assertEqual(code, 754)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_octal_encoding_large_code_16_10(self):
        code, pol = self.model_16_10._get_tone_val(0x4000 + 0x754)
        self.assertEqual(code, 754)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_octal_encoding_large_code_8_16(self):
        code, pol = self.model_8_16._get_tone_val(0x4000 + 0o754)
        self.assertEqual(code, 754)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_octal_encoding_large_code_10_16(self):
        code, pol = self.model_10_16._get_tone_val(0x4000 + 754)
        self.assertEqual(code, 754)
        self.assertEqual(pol, "N")

    def test_get_tone_val_dcs_octal_encoding_large_code_16_16(self):
        code, pol = self.model_16_16._get_tone_val(0x4000 + 0x754)
        self.assertEqual(code, 754)
        self.assertEqual(pol, "N")


class TestSetToneVal(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.model_8_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000)
        self.model_10_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10)
        self.model_16_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16)
        self.model_8_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            tone_enc_base=16)
        self.model_10_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10, tone_enc_base=16)
        self.model_16_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16, tone_enc_base=16)

    def test_set_tone_val_none_8_10(self):
        val = self.model_8_10._set_tone_val(None, None)
        self.assertEqual(val, 0x0000)

    def test_set_tone_val_none_10_10(self):
        val = self.model_10_10._set_tone_val(None, None)
        self.assertEqual(val, 0x0000)

    def test_set_tone_val_none_16_10(self):
        val = self.model_16_10._set_tone_val(None, None)
        self.assertEqual(val, 0x0000)

    def test_set_tone_val_none_8_16(self):
        val = self.model_8_16._set_tone_val(None, None)
        self.assertEqual(val, 0x0000)

    def test_set_tone_val_none_10_16(self):
        val = self.model_10_16._set_tone_val(None, None)
        self.assertEqual(val, 0x0000)

    def test_set_tone_val_none_16_16(self):
        val = self.model_16_16._set_tone_val(None, None)
        self.assertEqual(val, 0x0000)

    def test_set_tone_val_ctcss_8_10(self):
        val = self.model_8_10._set_tone_val(88.5, None)
        self.assertEqual(val, 885 + 0x8000)

    def test_set_tone_val_ctcss_10_10(self):
        val = self.model_10_10._set_tone_val(88.5, None)
        self.assertEqual(val, 885 + 0x8000)

    def test_set_tone_val_ctcss_16_10(self):
        val = self.model_16_10._set_tone_val(88.5, None)
        self.assertEqual(val, 885 + 0x8000)

    def test_set_tone_val_ctcss_8_16(self):
        val = self.model_8_16._set_tone_val(88.5, None)
        self.assertEqual(val, 0x8885)

    def test_set_tone_val_ctcss_10_16(self):
        val = self.model_10_16._set_tone_val(88.5, None)
        self.assertEqual(val, 0x8885)

    def test_set_tone_val_ctcss_16_16(self):
        val = self.model_16_16._set_tone_val(88.5, None)
        self.assertEqual(val, 0x8885)

    def test_set_tone_val_ctcss_no_flag_8_10(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_flag=0x0000)
        val = model._set_tone_val(88.5, None)
        self.assertEqual(val, 885)

    def test_set_tone_val_ctcss_no_flag_10_10(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_flag=0x0000,
            dcs_enc_base=10)
        val = model._set_tone_val(88.5, None)
        self.assertEqual(val, 885)

    def test_set_tone_val_ctcss_no_flag_16_10(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_flag=0x0000,
            dcs_enc_base=16)
        val = model._set_tone_val(88.5, None)
        self.assertEqual(val, 885)

    def test_set_tone_val_ctcss_no_flag_8_16(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_flag=0x0000,
            tone_enc_base=16)
        val = model._set_tone_val(88.5, None)
        self.assertEqual(val, 0x0885)

    def test_set_tone_val_ctcss_no_flag_10_16(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_flag=0x0000,
            dcs_enc_base=10, tone_enc_base=16)
        val = model._set_tone_val(88.5, None)
        self.assertEqual(val, 0x0885)

    def test_set_tone_val_ctcss_no_flag_16_16(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_flag=0x0000,
            dcs_enc_base=16, tone_enc_base=16)
        val = model._set_tone_val(88.5, None)
        self.assertEqual(val, 0x0885)

    def test_set_tone_val_dcs_normal_8_10(self):
        val = self.model_8_10._set_tone_val(23, "N")
        self.assertEqual(val, 0x4000 + 0o023)

    def test_set_tone_val_dcs_normal_10_10(self):
        val = self.model_10_10._set_tone_val(23, "N")
        self.assertEqual(val, 0x4000 + 23)

    def test_set_tone_val_dcs_normal_16_10(self):
        val = self.model_16_10._set_tone_val(23, "N")
        self.assertEqual(val, 0x4000 + 0x023)

    def test_set_tone_val_dcs_normal_8_16(self):
        val = self.model_8_16._set_tone_val(23, "N")
        self.assertEqual(val, 0x4000 + 0o023)

    def test_set_tone_val_dcs_normal_10_16(self):
        val = self.model_10_16._set_tone_val(23, "N")
        self.assertEqual(val, 0x4000 + 23)

    def test_set_tone_val_dcs_normal_16_16(self):
        val = self.model_16_16._set_tone_val(23, "N")
        self.assertEqual(val, 0x4000 + 0x023)

    def test_set_tone_val_dcs_reverse_8_10(self):
        val = self.model_8_10._set_tone_val(23, "R")
        self.assertEqual(val, 0x4000 + 0o023 + 0x2000)

    def test_set_tone_val_dcs_reverse_10_10(self):
        val = self.model_10_10._set_tone_val(23, "R")
        self.assertEqual(val, 0x4000 + 23 + 0x2000)

    def test_set_tone_val_dcs_reverse_16_10(self):
        val = self.model_16_10._set_tone_val(23, "R")
        self.assertEqual(val, 0x4000 + 0x023 + 0x2000)

    def test_set_tone_val_dcs_reverse_8_16(self):
        val = self.model_8_16._set_tone_val(23, "R")
        self.assertEqual(val, 0x4000 + 0o023 + 0x2000)

    def test_set_tone_val_dcs_reverse_10_16(self):
        val = self.model_10_16._set_tone_val(23, "R")
        self.assertEqual(val, 0x4000 + 23 + 0x2000)

    def test_set_tone_val_dcs_reverse_16_16(self):
        val = self.model_16_16._set_tone_val(23, "R")
        self.assertEqual(val, 0x4000 + 0x023 + 0x2000)


class TestSetTone(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.model_8_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000)
        self.model_10_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10)
        self.model_16_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16)
        self.model_8_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            tone_enc_base=16)
        self.model_10_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10, tone_enc_base=16)
        self.model_16_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16, tone_enc_base=16)

    def _make_mem(self, **kwargs):
        mem = chirp_common.Memory()
        for key, value in kwargs.items():
            setattr(mem, key, value)
        return mem

    def test_set_tone_empty_8_10(self):
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0x0000)
        self.assertEqual(_mem.txtone, 0x0000)

    def test_set_tone_empty_10_10(self):
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0x0000)
        self.assertEqual(_mem.txtone, 0x0000)

    def test_set_tone_empty_16_10(self):
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0x0000)
        self.assertEqual(_mem.txtone, 0x0000)

    def test_set_tone_empty_8_16(self):
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0x0000)
        self.assertEqual(_mem.txtone, 0x0000)

    def test_set_tone_empty_10_16(self):
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0x0000)
        self.assertEqual(_mem.txtone, 0x0000)

    def test_set_tone_empty_16_16(self):
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0x0000)
        self.assertEqual(_mem.txtone, 0x0000)

    def test_set_tone_tone_mode_8_10(self):
        mem = self._make_mem(tmode="Tone", rtone=100.0)
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, 0x0000)

    def test_set_tone_tone_mode_10_10(self):
        mem = self._make_mem(tmode="Tone", rtone=100.0)
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, 0x0000)

    def test_set_tone_tone_mode_16_10(self):
        mem = self._make_mem(tmode="Tone", rtone=100.0)
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, 0x0000)

    def test_set_tone_tone_mode_8_16(self):
        mem = self._make_mem(tmode="Tone", rtone=100.0)
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x0000)

    def test_set_tone_tone_mode_10_16(self):
        mem = self._make_mem(tmode="Tone", rtone=100.0)
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x0000)

    def test_set_tone_tone_mode_16_16(self):
        mem = self._make_mem(tmode="Tone", rtone=100.0)
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x0000)

    def test_set_tone_tsql_mode_8_10(self):
        mem = self._make_mem(tmode="TSQL", ctone=107.2)
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(107.2 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_tsql_mode_10_10(self):
        mem = self._make_mem(tmode="TSQL", ctone=107.2)
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(107.2 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_tsql_mode_16_10(self):
        mem = self._make_mem(tmode="TSQL", ctone=107.2)
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(107.2 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_tsql_mode_8_16(self):
        mem = self._make_mem(tmode="TSQL", ctone=107.2)
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9072)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_tsql_mode_10_16(self):
        mem = self._make_mem(tmode="TSQL", ctone=107.2)
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9072)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_tsql_mode_16_16(self):
        mem = self._make_mem(tmode="TSQL", ctone=107.2)
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9072)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_dtcs_mode_8_10(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NR")
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o023 + 0x2000)

    def test_set_tone_dtcs_mode_10_10(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NR")
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23)
        self.assertEqual(_mem.rxtone, 0x4000 + 23 + 0x2000)

    def test_set_tone_dtcs_mode_16_10(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NR")
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x023 + 0x2000)

    def test_set_tone_dtcs_mode_8_16(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NR")
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o023 + 0x2000)

    def test_set_tone_dtcs_mode_10_16(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NR")
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23)
        self.assertEqual(_mem.rxtone, 0x4000 + 23 + 0x2000)

    def test_set_tone_dtcs_mode_16_16(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NR")
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x023 + 0x2000)

    def test_set_tone_dtcs_mode_nn_8_10(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o023)

    def test_set_tone_dtcs_mode_nn_10_10(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23)
        self.assertEqual(_mem.rxtone, 0x4000 + 23)

    def test_set_tone_dtcs_mode_nn_16_10(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x023)

    def test_set_tone_dtcs_mode_nn_8_16(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o023)

    def test_set_tone_dtcs_mode_nn_10_16(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23)
        self.assertEqual(_mem.rxtone, 0x4000 + 23)

    def test_set_tone_dtcs_mode_nn_16_16(self):
        mem = self._make_mem(tmode="DTCS", dtcs=23, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x023)

    def test_set_tone_cross_tone_tone_8_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->Tone",
                             rtone=100.0, ctone=107.2)
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_tone_tone_10_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->Tone",
                             rtone=100.0, ctone=107.2)
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_tone_tone_16_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->Tone",
                             rtone=100.0, ctone=107.2)
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_tone_tone_8_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->Tone",
                             rtone=100.0, ctone=107.2)
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_tone_tone_10_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->Tone",
                             rtone=100.0, ctone=107.2)
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_tone_tone_16_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->Tone",
                             rtone=100.0, ctone=107.2)
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_tone_dtcs_8_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->DTCS",
                             rtone=100.0, rx_dtcs=25,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o025)

    def test_set_tone_cross_tone_dtcs_10_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->DTCS",
                             rtone=100.0, rx_dtcs=25,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, 0x4000 + 25)

    def test_set_tone_cross_tone_dtcs_16_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->DTCS",
                             rtone=100.0, rx_dtcs=25,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, int(100.0 * 10) + 0x8000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x025)

    def test_set_tone_cross_tone_dtcs_8_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->DTCS",
                             rtone=100.0, rx_dtcs=25,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o025)

    def test_set_tone_cross_tone_dtcs_10_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->DTCS",
                             rtone=100.0, rx_dtcs=25,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x4000 + 25)

    def test_set_tone_cross_tone_dtcs_16_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="Tone->DTCS",
                             rtone=100.0, rx_dtcs=25,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x9000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x025)

    def test_set_tone_cross_dtcs_tone_8_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->Tone",
                             dtcs=23, ctone=107.2,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_dtcs_tone_10_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->Tone",
                             dtcs=23, ctone=107.2,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_dtcs_tone_16_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->Tone",
                             dtcs=23, ctone=107.2,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_dtcs_tone_8_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->Tone",
                             dtcs=23, ctone=107.2,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_dtcs_tone_10_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->Tone",
                             dtcs=23, ctone=107.2,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_dtcs_tone_16_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->Tone",
                             dtcs=23, ctone=107.2,
                             dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_dtcs_dtcs_8_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->DTCS",
                             dtcs=23, rx_dtcs=25,
                             dtcs_polarity="RN")
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023 + 0x2000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o025)

    def test_set_tone_cross_dtcs_dtcs_10_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->DTCS",
                             dtcs=23, rx_dtcs=25,
                             dtcs_polarity="RN")
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23 + 0x2000)
        self.assertEqual(_mem.rxtone, 0x4000 + 25)

    def test_set_tone_cross_dtcs_dtcs_16_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->DTCS",
                             dtcs=23, rx_dtcs=25,
                             dtcs_polarity="RN")
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023 + 0x2000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x025)

    # Show that the tone_bcd flag doesn't interfere with DCS parsing.
    def test_set_tone_cross_dtcs_dtcs_8_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->DTCS",
                             dtcs=23, rx_dtcs=25,
                             dtcs_polarity="RN")
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0o023 + 0x2000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o025)

    def test_set_tone_cross_dtcs_dtcs_10_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->DTCS",
                             dtcs=23, rx_dtcs=25,
                             dtcs_polarity="RN")
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 23 + 0x2000)
        self.assertEqual(_mem.rxtone, 0x4000 + 25)

    def test_set_tone_cross_dtcs_dtcs_16_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="DTCS->DTCS",
                             dtcs=23, rx_dtcs=25,
                             dtcs_polarity="RN")
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x4000 + 0x023 + 0x2000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x025)

    def test_set_tone_cross_none_tone_8_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->Tone",
                             ctone=107.2)
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_none_tone_10_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->Tone",
                             ctone=107.2)
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_none_tone_16_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->Tone",
                             ctone=107.2)
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, int(107.2 * 10) + 0x8000)

    def test_set_tone_cross_none_tone_8_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->Tone",
                             ctone=107.2)
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_none_tone_10_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->Tone",
                             ctone=107.2)
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_none_tone_16_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->Tone",
                             ctone=107.2)
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x9072)

    def test_set_tone_cross_none_dtcs_8_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->DTCS",
                             rx_dtcs=25, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o025)

    def test_set_tone_cross_none_dtcs_10_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->DTCS",
                             rx_dtcs=25, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x4000 + 25)

    def test_set_tone_cross_none_dtcs_16_10(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->DTCS",
                             rx_dtcs=25, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x025)

    def test_set_tone_cross_none_dtcs_8_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->DTCS",
                             rx_dtcs=25, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0o025)

    def test_set_tone_cross_none_dtcs_10_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->DTCS",
                             rx_dtcs=25, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x4000 + 25)

    def test_set_tone_cross_none_dtcs_16_16(self):
        mem = self._make_mem(tmode="Cross", cross_mode="->DTCS",
                             rx_dtcs=25, dtcs_polarity="NN")
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        self.assertEqual(_mem.txtone, 0x0000)
        self.assertEqual(_mem.rxtone, 0x4000 + 0x025)

    def test_set_tone_with_tone_init_ffff_8_10(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_init=0xFFFF)
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        model.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0xFFFF)
        self.assertEqual(_mem.txtone, 0xFFFF)

    def test_set_tone_with_tone_init_ffff_10_10(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_init=0xFFFF,
            dcs_enc_base=10)
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        model.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0xFFFF)
        self.assertEqual(_mem.txtone, 0xFFFF)

    def test_set_tone_with_tone_init_ffff_16_10(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_init=0xFFFF,
            dcs_enc_base=16)
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        model.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0xFFFF)
        self.assertEqual(_mem.txtone, 0xFFFF)

    def test_set_tone_with_tone_init_ffff_8_16(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_init=0xFFFF,
            tone_enc_base=16)
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        model.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0xFFFF)
        self.assertEqual(_mem.txtone, 0xFFFF)

    def test_set_tone_with_tone_init_ffff_10_16(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_init=0xFFFF,
            dcs_enc_base=10, tone_enc_base=16)
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        model.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0xFFFF)
        self.assertEqual(_mem.txtone, 0xFFFF)

    def test_set_tone_with_tone_init_ffff_16_16(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_init=0xFFFF,
            dcs_enc_base=16, tone_enc_base=16)
        mem = self._make_mem(tmode="")
        _mem = MockMemory()
        model.set_tone(mem, _mem)
        self.assertEqual(_mem.rxtone, 0xFFFF)
        self.assertEqual(_mem.txtone, 0xFFFF)


class TestGetTone(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.model_8_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000)
        self.model_10_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10)
        self.model_16_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16)
        self.model_8_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            tone_enc_base=16)
        self.model_10_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10, tone_enc_base=16)
        self.model_16_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16, tone_enc_base=16)

    def test_get_tone_empty_8_10(self):
        _mem = MockMemory()
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "")

    def test_get_tone_empty_10_10(self):
        _mem = MockMemory()
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "")

    def test_get_tone_empty_16_10(self):
        _mem = MockMemory()
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "")

    def test_get_tone_empty_8_16(self):
        _mem = MockMemory()
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "")

    def test_get_tone_empty_10_16(self):
        _mem = MockMemory()
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "")

    def test_get_tone_empty_16_16(self):
        _mem = MockMemory()
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "")

    def test_get_tone_tone_mode_8_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = 0x0000
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Tone")
        self.assertEqual(mem.rtone, 100.0)

    def test_get_tone_tone_mode_10_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = 0x0000
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Tone")
        self.assertEqual(mem.rtone, 100.0)

    def test_get_tone_tone_mode_16_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = 0x0000
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Tone")
        self.assertEqual(mem.rtone, 100.0)

    def test_get_tone_tone_mode_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x0000
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Tone")
        self.assertEqual(mem.rtone, 100.0)

    def test_get_tone_tone_mode_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x0000
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Tone")
        self.assertEqual(mem.rtone, 100.0)

    def test_get_tone_tone_mode_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x0000
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Tone")
        self.assertEqual(mem.rtone, 100.0)

    def test_get_tone_tsql_mode_8_10(self):
        _mem = MockMemory()
        _mem.txtone = int(107.2 * 10) + 0x8000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "TSQL")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_tsql_mode_10_10(self):
        _mem = MockMemory()
        _mem.txtone = int(107.2 * 10) + 0x8000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "TSQL")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_tsql_mode_16_10(self):
        _mem = MockMemory()
        _mem.txtone = int(107.2 * 10) + 0x8000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "TSQL")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_tsql_mode_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9072
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "TSQL")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_tsql_mode_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9072
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "TSQL")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_tsql_mode_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9072
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "TSQL")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_dtcs_mode_8_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0o023
        _mem.rxtone = 0x4000 + 0o023
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.dtcs_polarity, "NN")

    def test_get_tone_dtcs_mode_10_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 23
        _mem.rxtone = 0x4000 + 23
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.dtcs_polarity, "NN")

    def test_get_tone_dtcs_mode_16_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0x023
        _mem.rxtone = 0x4000 + 0x023
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.dtcs_polarity, "NN")

    def test_get_tone_dtcs_mode_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0o023
        _mem.rxtone = 0x4000 + 0o023
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.dtcs_polarity, "NN")

    def test_get_tone_dtcs_mode_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 23
        _mem.rxtone = 0x4000 + 23
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.dtcs_polarity, "NN")

    def test_get_tone_dtcs_mode_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0x023
        _mem.rxtone = 0x4000 + 0x023
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.dtcs_polarity, "NN")

    def test_get_tone_dtcs_with_polarity_8_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0o023 + 0x2000
        _mem.rxtone = 0x4000 + 0o023
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs_polarity, "RN")

    def test_get_tone_dtcs_with_polarity_10_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 23 + 0x2000
        _mem.rxtone = 0x4000 + 23
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs_polarity, "RN")

    def test_get_tone_dtcs_with_polarity_16_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0x023 + 0x2000
        _mem.rxtone = 0x4000 + 0x023
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs_polarity, "RN")

    def test_get_tone_dtcs_with_polarity_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0o023 + 0x2000
        _mem.rxtone = 0x4000 + 0o023
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs_polarity, "RN")

    def test_get_tone_dtcs_with_polarity_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 23 + 0x2000
        _mem.rxtone = 0x4000 + 23
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs_polarity, "RN")

    def test_get_tone_dtcs_with_polarity_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0x023 + 0x2000
        _mem.rxtone = 0x4000 + 0x023
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "DTCS")
        self.assertEqual(mem.dtcs_polarity, "RN")

    def test_get_tone_cross_tone_tone_8_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->Tone")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_tone_tone_10_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->Tone")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_tone_tone_16_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->Tone")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_tone_tone_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->Tone")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_tone_tone_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->Tone")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_tone_tone_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->Tone")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_tone_dtcs_8_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = 0x4000 + 0o025
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->DTCS")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_tone_dtcs_10_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = 0x4000 + 25
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->DTCS")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_tone_dtcs_16_10(self):
        _mem = MockMemory()
        _mem.txtone = int(100.0 * 10) + 0x8000
        _mem.rxtone = 0x4000 + 0x025
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->DTCS")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_tone_dtcs_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x4000 + 0o025
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->DTCS")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_tone_dtcs_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x4000 + 25
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->DTCS")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_tone_dtcs_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x9000
        _mem.rxtone = 0x4000 + 0x025
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "Tone->DTCS")
        self.assertEqual(mem.rtone, 100.0)
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_dtcs_tone_8_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0o023
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "DTCS->Tone")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_dtcs_tone_10_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 23
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "DTCS->Tone")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_dtcs_tone_16_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0x023
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "DTCS->Tone")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_dtcs_tone_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0o023
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "DTCS->Tone")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_dtcs_tone_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 23
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "DTCS->Tone")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_dtcs_tone_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x4000 + 0x023
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "DTCS->Tone")
        self.assertEqual(mem.dtcs, 23)
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_none_tone_8_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->Tone")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_none_tone_10_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->Tone")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_none_tone_16_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = int(107.2 * 10) + 0x8000
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->Tone")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_none_tone_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->Tone")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_none_tone_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->Tone")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_none_tone_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x9072
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->Tone")
        self.assertEqual(mem.ctone, 107.2)

    def test_get_tone_cross_none_dtcs_8_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x4000 + 0o025
        mem = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->DTCS")
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_none_dtcs_10_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x4000 + 25
        mem = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->DTCS")
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_none_dtcs_16_10(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x4000 + 0x025
        mem = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->DTCS")
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_none_dtcs_8_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x4000 + 0o025
        mem = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->DTCS")
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_none_dtcs_10_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x4000 + 25
        mem = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->DTCS")
        self.assertEqual(mem.rx_dtcs, 25)

    def test_get_tone_cross_none_dtcs_16_16(self):
        _mem = MockMemory()
        _mem.txtone = 0x0000
        _mem.rxtone = 0x4000 + 0x025
        mem = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, mem)
        self.assertEqual(mem.tmode, "Cross")
        self.assertEqual(mem.cross_mode, "->DTCS")
        self.assertEqual(mem.rx_dtcs, 25)


class TestRoundTrip(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.model_8_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000)
        self.model_10_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10)
        self.model_16_10 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16)
        self.model_8_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            tone_enc_base=16)
        self.model_10_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=10, tone_enc_base=16)
        self.model_16_16 = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000,
            dcs_enc_base=16, tone_enc_base=16)

    def _round_trip_8_10(self, mem):
        _mem = MockMemory()
        self.model_8_10.set_tone(mem, _mem)
        result = chirp_common.Memory()
        self.model_8_10.get_tone(_mem, result)
        return result

    def _round_trip_10_10(self, mem):
        _mem = MockMemory()
        self.model_10_10.set_tone(mem, _mem)
        result = chirp_common.Memory()
        self.model_10_10.get_tone(_mem, result)
        return result

    def _round_trip_16_10(self, mem):
        _mem = MockMemory()
        self.model_16_10.set_tone(mem, _mem)
        result = chirp_common.Memory()
        self.model_16_10.get_tone(_mem, result)
        return result

    def _round_trip_8_16(self, mem):
        _mem = MockMemory()
        self.model_8_16.set_tone(mem, _mem)
        result = chirp_common.Memory()
        self.model_8_16.get_tone(_mem, result)
        return result

    def _round_trip_10_16(self, mem):
        _mem = MockMemory()
        self.model_10_16.set_tone(mem, _mem)
        result = chirp_common.Memory()
        self.model_10_16.get_tone(_mem, result)
        return result

    def _round_trip_16_16(self, mem):
        _mem = MockMemory()
        self.model_16_16.set_tone(mem, _mem)
        result = chirp_common.Memory()
        self.model_16_16.get_tone(_mem, result)
        return result

    def test_round_trip_empty_8_10(self):
        mem = chirp_common.Memory()
        mem.tmode = ""
        result = self._round_trip_8_10(mem)
        self.assertEqual(result.tmode, "")

    def test_round_trip_empty_10_10(self):
        mem = chirp_common.Memory()
        mem.tmode = ""
        result = self._round_trip_10_10(mem)
        self.assertEqual(result.tmode, "")

    def test_round_trip_empty_16_10(self):
        mem = chirp_common.Memory()
        mem.tmode = ""
        result = self._round_trip_16_10(mem)
        self.assertEqual(result.tmode, "")

    def test_round_trip_empty_8_16(self):
        mem = chirp_common.Memory()
        mem.tmode = ""
        result = self._round_trip_8_16(mem)
        self.assertEqual(result.tmode, "")

    def test_round_trip_empty_10_16(self):
        mem = chirp_common.Memory()
        mem.tmode = ""
        result = self._round_trip_10_16(mem)
        self.assertEqual(result.tmode, "")

    def test_round_trip_empty_16_16(self):
        mem = chirp_common.Memory()
        mem.tmode = ""
        result = self._round_trip_16_16(mem)
        self.assertEqual(result.tmode, "")

    def test_round_trip_tone_8_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Tone"
        mem.rtone = 100.0
        result = self._round_trip_8_10(mem)
        self.assertEqual(result.tmode, "Tone")
        self.assertEqual(result.rtone, 100.0)

    def test_round_trip_tone_10_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Tone"
        mem.rtone = 100.0
        result = self._round_trip_10_10(mem)
        self.assertEqual(result.tmode, "Tone")
        self.assertEqual(result.rtone, 100.0)

    def test_round_trip_tone_16_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Tone"
        mem.rtone = 100.0
        result = self._round_trip_16_10(mem)
        self.assertEqual(result.tmode, "Tone")
        self.assertEqual(result.rtone, 100.0)

    def test_round_trip_tone_8_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Tone"
        mem.rtone = 100.0
        result = self._round_trip_8_16(mem)
        self.assertEqual(result.tmode, "Tone")
        self.assertEqual(result.rtone, 100.0)

    def test_round_trip_tone_10_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Tone"
        mem.rtone = 100.0
        result = self._round_trip_10_16(mem)
        self.assertEqual(result.tmode, "Tone")
        self.assertEqual(result.rtone, 100.0)

    def test_round_trip_tone_16_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Tone"
        mem.rtone = 100.0
        result = self._round_trip_16_16(mem)
        self.assertEqual(result.tmode, "Tone")
        self.assertEqual(result.rtone, 100.0)

    def test_round_trip_tsql_8_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "TSQL"
        mem.ctone = 107.2
        result = self._round_trip_8_10(mem)
        self.assertEqual(result.tmode, "TSQL")
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_tsql_10_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "TSQL"
        mem.ctone = 107.2
        result = self._round_trip_10_10(mem)
        self.assertEqual(result.tmode, "TSQL")
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_tsql_16_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "TSQL"
        mem.ctone = 107.2
        result = self._round_trip_16_10(mem)
        self.assertEqual(result.tmode, "TSQL")
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_tsql_8_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "TSQL"
        mem.ctone = 107.2
        result = self._round_trip_8_16(mem)
        self.assertEqual(result.tmode, "TSQL")
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_tsql_10_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "TSQL"
        mem.ctone = 107.2
        result = self._round_trip_10_16(mem)
        self.assertEqual(result.tmode, "TSQL")
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_tsql_16_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "TSQL"
        mem.ctone = 107.2
        result = self._round_trip_16_16(mem)
        self.assertEqual(result.tmode, "TSQL")
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_dtcs_8_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "DTCS"
        mem.dtcs = 23
        mem.dtcs_polarity = "NR"
        result = self._round_trip_8_10(mem)
        self.assertEqual(result.tmode, "DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.dtcs_polarity, "NR")

    def test_round_trip_dtcs_10_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "DTCS"
        mem.dtcs = 23
        mem.dtcs_polarity = "NR"
        result = self._round_trip_10_10(mem)
        self.assertEqual(result.tmode, "DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.dtcs_polarity, "NR")

    def test_round_trip_dtcs_16_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "DTCS"
        mem.dtcs = 23
        mem.dtcs_polarity = "NR"
        result = self._round_trip_16_10(mem)
        self.assertEqual(result.tmode, "DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.dtcs_polarity, "NR")

    def test_round_trip_dtcs_8_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "DTCS"
        mem.dtcs = 23
        mem.dtcs_polarity = "NR"
        result = self._round_trip_8_16(mem)
        self.assertEqual(result.tmode, "DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.dtcs_polarity, "NR")

    def test_round_trip_dtcs_10_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "DTCS"
        mem.dtcs = 23
        mem.dtcs_polarity = "NR"
        result = self._round_trip_10_16(mem)
        self.assertEqual(result.tmode, "DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.dtcs_polarity, "NR")

    def test_round_trip_dtcs_16_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "DTCS"
        mem.dtcs = 23
        mem.dtcs_polarity = "NR"
        result = self._round_trip_16_16(mem)
        self.assertEqual(result.tmode, "DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.dtcs_polarity, "NR")

    def test_round_trip_cross_tone_tone_8_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 100.0
        mem.ctone = 107.2
        result = self._round_trip_8_10(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "Tone->Tone")
        self.assertEqual(result.rtone, 100.0)
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_cross_tone_tone_10_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 100.0
        mem.ctone = 107.2
        result = self._round_trip_10_10(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "Tone->Tone")
        self.assertEqual(result.rtone, 100.0)
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_cross_tone_tone_16_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 100.0
        mem.ctone = 107.2
        result = self._round_trip_16_10(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "Tone->Tone")
        self.assertEqual(result.rtone, 100.0)
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_cross_tone_tone_8_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 100.0
        mem.ctone = 107.2
        result = self._round_trip_8_16(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "Tone->Tone")
        self.assertEqual(result.rtone, 100.0)
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_cross_tone_tone_10_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 100.0
        mem.ctone = 107.2
        result = self._round_trip_10_16(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "Tone->Tone")
        self.assertEqual(result.rtone, 100.0)
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_cross_tone_tone_16_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->Tone"
        mem.rtone = 100.0
        mem.ctone = 107.2
        result = self._round_trip_16_16(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "Tone->Tone")
        self.assertEqual(result.rtone, 100.0)
        self.assertEqual(result.ctone, 107.2)

    def test_round_trip_cross_dtcs_dtcs_8_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "DTCS->DTCS"
        mem.dtcs = 23
        mem.rx_dtcs = 25
        mem.dtcs_polarity = "RN"
        result = self._round_trip_8_10(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "DTCS->DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.rx_dtcs, 25)
        self.assertEqual(result.dtcs_polarity, "RN")

    def test_round_trip_cross_dtcs_dtcs_10_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "DTCS->DTCS"
        mem.dtcs = 23
        mem.rx_dtcs = 25
        mem.dtcs_polarity = "RN"
        result = self._round_trip_10_10(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "DTCS->DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.rx_dtcs, 25)
        self.assertEqual(result.dtcs_polarity, "RN")

    def test_round_trip_cross_dtcs_dtcs_16_10(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "DTCS->DTCS"
        mem.dtcs = 23
        mem.rx_dtcs = 25
        mem.dtcs_polarity = "RN"
        result = self._round_trip_16_10(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "DTCS->DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.rx_dtcs, 25)
        self.assertEqual(result.dtcs_polarity, "RN")

    def test_round_trip_cross_dtcs_dtcs_8_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "DTCS->DTCS"
        mem.dtcs = 23
        mem.rx_dtcs = 25
        mem.dtcs_polarity = "RN"
        result = self._round_trip_8_16(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "DTCS->DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.rx_dtcs, 25)
        self.assertEqual(result.dtcs_polarity, "RN")

    def test_round_trip_cross_dtcs_dtcs_10_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "DTCS->DTCS"
        mem.dtcs = 23
        mem.rx_dtcs = 25
        mem.dtcs_polarity = "RN"
        result = self._round_trip_10_16(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "DTCS->DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.rx_dtcs, 25)
        self.assertEqual(result.dtcs_polarity, "RN")

    def test_round_trip_cross_dtcs_dtcs_16_16(self):
        mem = chirp_common.Memory()
        mem.tmode = "Cross"
        mem.cross_mode = "DTCS->DTCS"
        mem.dtcs = 23
        mem.rx_dtcs = 25
        mem.dtcs_polarity = "RN"
        result = self._round_trip_16_16(mem)
        self.assertEqual(result.tmode, "Cross")
        self.assertEqual(result.cross_mode, "DTCS->DTCS")
        self.assertEqual(result.dtcs, 23)
        self.assertEqual(result.rx_dtcs, 25)
        self.assertEqual(result.dtcs_polarity, "RN")


class TestParseQtdqt(base.BaseTest):
    def test_parse_empty_string(self):
        mode, val, pol = kenwood_tone.parse_qtdqt("")
        self.assertEqual(mode, "")
        self.assertIsNone(val)
        self.assertIsNone(pol)

    def test_parse_none(self):
        mode, val, pol = kenwood_tone.parse_qtdqt(None)
        self.assertEqual(mode, "")
        self.assertIsNone(val)
        self.assertIsNone(pol)

    def test_parse_tone(self):
        mode, val, pol = kenwood_tone.parse_qtdqt("103.5")
        self.assertEqual(mode, "Tone")
        self.assertEqual(val, 103.5)
        self.assertEqual(pol, "")

    def test_parse_tone_whitespace(self):
        mode, val, pol = kenwood_tone.parse_qtdqt(" 103.5 ")
        self.assertEqual(mode, "Tone")
        self.assertEqual(val, 103.5)
        self.assertEqual(pol, "")

    def test_parse_dcs_normal(self):
        mode, val, pol = kenwood_tone.parse_qtdqt("D023N")
        self.assertEqual(mode, "DTCS")
        self.assertEqual(val, 23)
        self.assertEqual(pol, "N")

    def test_parse_dcs_reverse(self):
        mode, val, pol = kenwood_tone.parse_qtdqt("D032R")
        self.assertEqual(mode, "DTCS")
        self.assertEqual(val, 32)
        self.assertEqual(pol, "R")

    def test_parse_dcs_lowercase(self):
        mode, val, pol = kenwood_tone.parse_qtdqt("d023n")
        self.assertEqual(mode, "DTCS")
        self.assertEqual(val, 23)
        self.assertEqual(pol, "N")

    def test_parse_dcs_invalid_format(self):
        with self.assertRaises(ValueError) as ctx:
            kenwood_tone.parse_qtdqt("D23N")
        self.assertIn("D023N", str(ctx.exception))

    def test_parse_dcs_invalid_code(self):
        with self.assertRaises(ValueError) as ctx:
            kenwood_tone.parse_qtdqt("DABCN")
        self.assertIn("D023N", str(ctx.exception))

    def test_parse_tone_invalid(self):
        with self.assertRaises(ValueError) as ctx:
            kenwood_tone.parse_qtdqt("abc")
        self.assertIn("103.5", str(ctx.exception))


class TestFormatQtdqt(base.BaseTest):
    def test_format_dcs(self):
        result = kenwood_tone.format_qtdqt("DTCS", 23, "N")
        self.assertEqual(result, "D023N")

    def test_format_dcs_reverse(self):
        result = kenwood_tone.format_qtdqt("DTCS", 32, "R")
        self.assertEqual(result, "D032R")

    def test_format_tone(self):
        result = kenwood_tone.format_qtdqt("Tone", 103.5, "")
        self.assertEqual(result, "103.5")

    def test_format_empty(self):
        result = kenwood_tone.format_qtdqt("", None, "")
        self.assertEqual(result, "")


class TestDifferentParameterSets(base.BaseTest):
    def test_dcs_base_0x2800(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x2800, pol_mask=0x8000)
        code, pol = model._get_tone_val(0x2800 + 0o023)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

        code, pol = model._get_tone_val(0x2800 + 0o023 + 0x8000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_dcs_base_0x8000(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x8000, pol_mask=0x4000)
        code, pol = model._get_tone_val(0x8000 + 0o023)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "N")

        code, pol = model._get_tone_val(0x8000 + 0o023 + 0x4000)
        self.assertEqual(code, 23)
        self.assertEqual(pol, "R")

    def test_tone_flag_0x0000(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, tone_flag=0x0000)
        val = model._set_tone_val(88.5, None)
        self.assertEqual(val, 885)

        code, pol = model._get_tone_val(885)
        self.assertEqual(code, 88.5)
        self.assertIsNone(pol)

    def test_decimal_dcs_encoding(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, dcs_enc_base=10)
        val = model._set_tone_val(123, "N")
        self.assertEqual(val, 0x4000 + 123)

        code, pol = model._get_tone_val(0x4000 + 123)
        self.assertEqual(code, 123)
        self.assertEqual(pol, "N")

        code, pol = model._get_tone_val(0x4000 + 123 + 0x2000)
        self.assertEqual(code, 123)
        self.assertEqual(pol, "R")

    def test_bcd_dcs_encoding(self):
        model = kenwood_tone.KenwoodToneModel(
            dcs_base=0x4000, pol_mask=0x2000, dcs_enc_base=16)
        val = model._set_tone_val(123, "N")
        self.assertEqual(val, 0x4123)

        code, pol = model._get_tone_val(0x4123)
        self.assertEqual(code, 123)
        self.assertEqual(pol, "N")

        code, pol = model._get_tone_val(0x4123 + 0x2000)
        self.assertEqual(code, 123)
        self.assertEqual(pol, "R")
