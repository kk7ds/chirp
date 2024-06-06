from unittest import mock

from tests.unit import base
from chirp import import_logic
from chirp import chirp_common
from chirp import errors


class FakeRadio(chirp_common.Radio):
    def __init__(self, arg):
        self.POWER_LEVELS = list([chirp_common.PowerLevel('lo', watts=5),
                                  chirp_common.PowerLevel('hi', watts=50)])
        self.TMODES = list(['', 'Tone', 'TSQL'])
        self.HAS_CTONE = True
        self.HAS_RX_DTCS = False
        self.MODES = list(['FM', 'AM', 'DV'])
        self.DUPLEXES = list(['', '-', '+'])

    def filter_name(self, name):
        return 'filtered-name'

    def get_memory(self, number):
        return chirp_common.Memory(number, empty=True)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_bands = [(100000000, 500000000)]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_tmodes = self.TMODES
        rf.valid_modes = self.MODES
        rf.valid_duplexes = self.DUPLEXES
        rf.has_ctone = self.HAS_CTONE
        rf.has_rx_dtcs = self.HAS_RX_DTCS
        return rf


class FakeDstarRadio(FakeRadio, chirp_common.IcomDstarSupport):
    REQUIRES_CALL_LISTS = False

    def get_features(self):
        rf = super().get_features()
        rf.requires_call_lists = self.REQUIRES_CALL_LISTS
        return rf


class DstarTests(base.BaseTest):
    def _test_ensure_has_calls(self, mem,
                               ini_urcalls, ini_rptcalls,
                               exp_urcalls, exp_rptcalls):
        radio = FakeDstarRadio(None)
        with mock.patch.multiple(
                radio,
                get_urcall_list=mock.DEFAULT,
                get_repeater_call_list=mock.DEFAULT) as mocks:
            mocks['get_urcall_list'].return_value = ini_urcalls
            mocks['get_repeater_call_list'].return_value = ini_rptcalls
            import_logic.ensure_has_calls(radio, mem)
            self.assertEqual(sorted(ini_urcalls), sorted(exp_urcalls))
            self.assertEqual(sorted(ini_rptcalls), sorted(exp_rptcalls))

    def test_ensure_has_calls_empty(self):
        mem = chirp_common.DVMemory()
        mem.dv_urcall = 'KK7DS'
        mem.dv_rpt1call = 'KD7RFI B'
        mem.dv_rpt2call = 'KD7RFI G'
        ini_urcalls = ['', '', '', '', '']
        ini_rptcalls = ['', '', '', '', '']
        exp_urcalls = list(ini_urcalls)
        exp_rptcalls = list(ini_rptcalls)
        exp_urcalls[0] = mem.dv_urcall
        exp_rptcalls[0] = mem.dv_rpt1call
        exp_rptcalls[1] = mem.dv_rpt2call
        self._test_ensure_has_calls(mem, ini_urcalls, ini_rptcalls,
                                    exp_urcalls, exp_rptcalls)

    def test_ensure_has_calls_partial(self):
        mem = chirp_common.DVMemory()
        mem.dv_urcall = 'KK7DS'
        mem.dv_rpt1call = 'KD7RFI B'
        mem.dv_rpt2call = 'KD7RFI G'
        ini_urcalls = ['FOO', 'BAR', '', '', '']
        ini_rptcalls = ['FOO', 'BAR', '', '', '']
        exp_urcalls = list(ini_urcalls)
        exp_rptcalls = list(ini_rptcalls)
        exp_urcalls[2] = mem.dv_urcall
        exp_rptcalls[2] = mem.dv_rpt1call
        exp_rptcalls[3] = mem.dv_rpt2call
        self._test_ensure_has_calls(mem, ini_urcalls, ini_rptcalls,
                                    exp_urcalls, exp_rptcalls)

    def test_ensure_has_calls_almost_full(self):
        mem = chirp_common.DVMemory()
        mem.dv_urcall = 'KK7DS'
        mem.dv_rpt1call = 'KD7RFI B'
        mem.dv_rpt2call = 'KD7RFI G'
        ini_urcalls = ['FOO', 'BAR', 'BAZ', 'BAT', '']
        ini_rptcalls = ['FOO', 'BAR', 'BAZ', '', '']
        exp_urcalls = list(ini_urcalls)
        exp_rptcalls = list(ini_rptcalls)
        exp_urcalls[4] = mem.dv_urcall
        exp_rptcalls[3] = mem.dv_rpt1call
        exp_rptcalls[4] = mem.dv_rpt2call
        self._test_ensure_has_calls(mem, ini_urcalls, ini_rptcalls,
                                    exp_urcalls, exp_rptcalls)

    def test_ensure_has_calls_urcall_full(self):
        mem = chirp_common.DVMemory()
        mem.dv_urcall = 'KK7DS'
        mem.dv_rpt1call = 'KD7RFI B'
        mem.dv_rpt2call = 'KD7RFI G'
        ini_urcalls = ['FOO', 'BAR', 'BAZ', 'BAT', 'BOOM']
        ini_rptcalls = ['FOO', 'BAR', 'BAZ', '', '']
        exp_urcalls = list(ini_urcalls)
        exp_rptcalls = list(ini_rptcalls)
        exp_urcalls[4] = mem.dv_urcall
        exp_rptcalls[3] = mem.dv_rpt1call
        exp_rptcalls[4] = mem.dv_rpt2call
        self.assertRaises(errors.RadioError,
                          self._test_ensure_has_calls,
                          mem, ini_urcalls, ini_rptcalls,
                          exp_urcalls, exp_rptcalls)

    def test_ensure_has_calls_rptcall_full1(self):
        mem = chirp_common.DVMemory()
        mem.dv_urcall = 'KK7DS'
        mem.dv_rpt1call = 'KD7RFI B'
        mem.dv_rpt2call = 'KD7RFI G'
        ini_urcalls = ['FOO', 'BAR', 'BAZ', 'BAT', '']
        ini_rptcalls = ['FOO', 'BAR', 'BAZ', 'BAT', '']
        exp_urcalls = list(ini_urcalls)
        exp_rptcalls = list(ini_rptcalls)
        exp_urcalls[4] = mem.dv_urcall
        exp_rptcalls[3] = mem.dv_rpt1call
        exp_rptcalls[4] = mem.dv_rpt2call
        self.assertRaises(errors.RadioError,
                          self._test_ensure_has_calls,
                          mem, ini_urcalls, ini_rptcalls,
                          exp_urcalls, exp_rptcalls)

    def test_ensure_has_calls_rptcall_full2(self):
        mem = chirp_common.DVMemory()
        mem.dv_urcall = 'KK7DS'
        mem.dv_rpt1call = 'KD7RFI B'
        mem.dv_rpt2call = 'KD7RFI G'
        ini_urcalls = ['FOO', 'BAR', 'BAZ', 'BAT', '']
        ini_rptcalls = ['FOO', 'BAR', 'BAZ', 'BAT', 'BOOM']
        exp_urcalls = list(ini_urcalls)
        exp_rptcalls = list(ini_rptcalls)
        exp_urcalls[4] = mem.dv_urcall
        exp_rptcalls[3] = mem.dv_rpt1call
        exp_rptcalls[4] = mem.dv_rpt2call
        self.assertRaises(errors.RadioError,
                          self._test_ensure_has_calls,
                          mem, ini_urcalls, ini_rptcalls,
                          exp_urcalls, exp_rptcalls)


class ImportFieldTests(base.BaseTest):
    def test_import_freq(self):
        mem = chirp_common.Memory()
        mem.freq = 10
        self.assertRaises(import_logic.DestNotCompatible,
                          import_logic._import_freq,
                          FakeRadio(None), None, mem)

    def test_import_name(self):
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.name = 'foo'
        import_logic._import_name(FakeRadio(None), None, mem)
        self.assertEqual(mem.name, 'filtered-name')

    def test_import_power_same(self):
        radio = FakeRadio(None)
        same_rf = radio.get_features()
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.power = same_rf.valid_power_levels[0]
        import_logic._import_power(radio, same_rf, mem)
        self.assertEqual(mem.power, same_rf.valid_power_levels[0])

    def test_import_power_no_src(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.power = None
        import_logic._import_power(radio, src_rf, mem)
        self.assertEqual(mem.power, radio.POWER_LEVELS[1])

    def test_import_power_no_src_variable(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.power = None
        with mock.patch.object(radio, 'get_features') as mock_gf:
            mock_gf.return_value = chirp_common.RadioFeatures()
            mock_gf.return_value.has_variable_power = True
            mock_gf.return_value.valid_power_levels = [
                chirp_common.AutoNamedPowerLevel(1),
                chirp_common.AutoNamedPowerLevel(50),
                chirp_common.AutoNamedPowerLevel(1500)]
            import_logic._import_power(radio, src_rf, mem)
        self.assertEqual('50W', str(mem.power))

    def test_import_power_no_dst(self):
        radio = FakeRadio(None)
        src_rf = radio.get_features()  # Steal a copy before we stub out
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.power = src_rf.valid_power_levels[0]
        with mock.patch.object(radio, 'get_features') as mock_gf:
            mock_gf.return_value = chirp_common.RadioFeatures()
            import_logic._import_power(radio, src_rf, mem)
        self.assertEqual(mem.power, None)

    def test_import_power_closest(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        src_rf.valid_power_levels = [
            chirp_common.PowerLevel('foo', watts=7),
            chirp_common.PowerLevel('bar', watts=51),
            chirp_common.PowerLevel('baz', watts=1),
        ]
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.power = src_rf.valid_power_levels[0]
        import_logic._import_power(radio, src_rf, mem)
        self.assertEqual(mem.power, radio.POWER_LEVELS[0])

    def test_import_power_closest_watts(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        src_rf.valid_power_levels = [
            chirp_common.PowerLevel('foo', watts=20),
            chirp_common.PowerLevel('bar', watts=51),
            chirp_common.PowerLevel('baz', watts=1),
        ]
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.power = src_rf.valid_power_levels[0]
        import_logic._import_power(radio, src_rf, mem)
        self.assertEqual(mem.power, radio.POWER_LEVELS[0])

    def test_import_tone_diffA_tsql(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        src_rf.has_ctone = False
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem.tmode = 'TSQL'
        mem.rtone = 100.0
        import_logic._import_tone(radio, src_rf, mem)
        self.assertEqual(mem.ctone, 100.0)

    def test_import_tone_diffB_tsql(self):
        radio = FakeRadio(None)
        radio.HAS_CTONE = False
        src_rf = chirp_common.RadioFeatures()
        src_rf.has_ctone = True
        mem = chirp_common.Memory()
        mem.tmode = 'TSQL'
        mem.ctone = 100.0
        import_logic._import_tone(radio, src_rf, mem)
        self.assertEqual(mem.rtone, 100.0)

    def test_import_dtcs_diffA_dtcs(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        src_rf.has_rx_dtcs = True
        mem = chirp_common.Memory()
        mem.tmode = 'DTCS'
        mem.rx_dtcs = 32
        import_logic._import_dtcs(radio, src_rf, mem)
        self.assertEqual(mem.dtcs, 32)

    def test_import_dtcs_diffB_dtcs(self):
        radio = FakeRadio(None)
        radio.HAS_RX_DTCS = True
        src_rf = chirp_common.RadioFeatures()
        src_rf.has_rx_dtcs = False
        mem = chirp_common.Memory()
        mem.tmode = 'DTCS'
        mem.dtcs = 32
        import_logic._import_dtcs(radio, src_rf, mem)
        self.assertEqual(mem.rx_dtcs, 32)

    def test_import_mode_valid_fm(self):
        radio = FakeRadio(None)
        mem = chirp_common.Memory()
        mem.mode = 'Auto'
        mem.freq = 146000000
        import_logic._import_mode(radio, None, mem)
        self.assertEqual(mem.mode, 'FM')

    def test_import_mode_valid_am(self):
        radio = FakeRadio(None)
        mem = chirp_common.Memory()
        mem.mode = 'Auto'
        mem.freq = 18000000
        import_logic._import_mode(radio, None, mem)
        self.assertEqual(mem.mode, 'AM')

    def test_import_mode_invalid(self):
        radio = FakeRadio(None)
        radio.MODES.remove('AM')
        mem = chirp_common.Memory()
        mem.mode = 'Auto'
        mem.freq = 1800000
        self.assertRaises(import_logic.DestNotCompatible,
                          import_logic._import_mode, radio, None, mem)

    def test_import_duplex_vhf(self):
        radio = FakeRadio(None)
        mem = chirp_common.Memory()
        mem.freq = 146000000
        mem.offset = 146600000
        mem.duplex = 'split'
        import_logic._import_duplex(radio, None, mem)
        self.assertEqual(mem.duplex, '+')
        self.assertEqual(mem.offset, 600000)

    def test_import_duplex_negative(self):
        radio = FakeRadio(None)
        mem = chirp_common.Memory()
        mem.freq = 146600000
        mem.offset = 146000000
        mem.duplex = 'split'
        import_logic._import_duplex(radio, None, mem)
        self.assertEqual(mem.duplex, '-')
        self.assertEqual(mem.offset, 600000)

    def test_import_duplex_uhf(self):
        radio = FakeRadio(None)
        mem = chirp_common.Memory()
        mem.freq = 431000000
        mem.offset = 441000000
        mem.duplex = 'split'
        import_logic._import_duplex(radio, None, mem)
        self.assertEqual(mem.duplex, '+')
        self.assertEqual(mem.offset, 10000000)

    def test_import_duplex_too_big_vhf(self):
        radio = FakeRadio(None)
        mem = chirp_common.Memory()
        mem.freq = 146000000
        mem.offset = 246000000
        mem.duplex = 'split'
        self.assertRaises(import_logic.DestNotCompatible,
                          import_logic._import_duplex, radio, None, mem)

    def test_import_duplex_off_not_supported(self):
        radio = FakeRadio(None)
        mem = chirp_common.Memory()
        mem.freq = 146000000
        mem.duplex = 'off'
        import_logic._import_duplex(radio, None, mem)
        self.assertEqual('', mem.duplex)

    @mock.patch('chirp.import_logic._import_name')
    @mock.patch('chirp.import_logic._import_power')
    @mock.patch('chirp.import_logic._import_tone')
    @mock.patch('chirp.import_logic._import_dtcs')
    @mock.patch('chirp.import_logic._import_mode')
    @mock.patch('chirp.import_logic._import_duplex')
    def _test_import_mem(self, errors,
                         mock_duplex, mock_mode, mock_dtcs, mock_tone,
                         mock_power, mock_name):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        mem = chirp_common.Memory()
        mem.freq = 146520000

        with mock.patch.object(mem, 'dupe') as mock_dupe:
            mock_dupe.return_value = mem
            with mock.patch.object(radio, 'validate_memory') as mock_val:
                mock_val.return_value = errors
                import_logic.import_mem(radio, src_rf, mem)
                mock_val.assert_called_once_with(mem)
            mock_dupe.assert_called_once_with()

        mock_duplex.assert_called_once_with(radio, src_rf, mem)

    def test_import_mem(self):
        self._test_import_mem([])

    @mock.patch.object(FakeRadio, 'get_memory')
    @mock.patch.object(FakeRadio, 'check_set_memory_immutable_policy')
    def test_import_mem_checks_immutable(self, mock_check, mock_get):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        mem = chirp_common.Memory()
        mem.freq = 146520000
        with mock.patch.object(mem, 'dupe') as mock_dupe:
            mock_dupe.return_value = mem
            import_logic.import_mem(radio, src_rf, mem)
            mock_check.assert_called_once_with(mock_get.return_value, mem)
            mock_get.assert_called_once_with(mem.number)

    def test_import_mem_with_class(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        mem = chirp_common.Memory()
        mem.freq = 146520000
        mem2 = import_logic.import_mem(radio, src_rf, mem,
                                       mem_cls=chirp_common.DVMemory)
        self.assertIsInstance(mem2, chirp_common.DVMemory)

    def test_import_mem_dstar_logic(self):
        radio = FakeRadio(None)
        src_rf = chirp_common.RadioFeatures()
        mem = chirp_common.DVMemory()
        mem.freq = 146520000
        mem.mode = 'DV'

        # non-DSTAR radio exposes only FM, so DV is not compatible
        radio.MODES = ['FM']
        self.assertRaises(import_logic.DestNotCompatible,
                          import_logic.import_mem, radio, src_rf, mem)

        # non-DSTAR radio exposes DV, so it is compatible, but obviously
        # no call list manipulation needed.
        radio.MODES = ['FM', 'DV']
        with mock.patch('chirp.import_logic.ensure_has_calls') as mock_e:
            import_logic.import_mem(radio, src_rf, mem)
            mock_e.assert_not_called()

        # A real D-STAR radio gets the full treatment, depending on the
        # required call lists flag
        radio = FakeDstarRadio(None)
        with mock.patch('chirp.import_logic.ensure_has_calls') as mock_e:
            radio.REQUIRES_CALL_LISTS = False
            import_logic.import_mem(radio, src_rf, mem)
            mock_e.assert_not_called()

            radio.REQUIRES_CALL_LISTS = True
            import_logic.import_mem(radio, src_rf, mem)
            mock_e.assert_called()

    def test_import_mem_with_warnings(self):
        self._test_import_mem([chirp_common.ValidationWarning('Test')])

    def test_import_mem_with_errors(self):
        self.assertRaises(import_logic.DestNotCompatible,
                          self._test_import_mem,
                          [chirp_common.ValidationError('Test')])

    def test_import_bank(self):
        dst_mem = chirp_common.Memory()
        dst_mem.number = 1
        src_mem = chirp_common.Memory()
        src_mem.number = 2
        dst_radio = FakeRadio(None)
        src_radio = FakeRadio(None)
        dst_bm = chirp_common.BankModel(dst_radio)
        src_bm = chirp_common.BankModel(src_radio)

        dst_banks = [chirp_common.Bank(dst_bm, 0, 'A'),
                     chirp_common.Bank(dst_bm, 1, 'B'),
                     chirp_common.Bank(dst_bm, 2, 'C'),
                     ]
        src_banks = [chirp_common.Bank(src_bm, 1, '1'),
                     chirp_common.Bank(src_bm, 2, '2'),
                     chirp_common.Bank(src_bm, 3, '3'),
                     ]

        @mock.patch.object(dst_radio, 'get_mapping_models',
                           return_value=[dst_bm])
        @mock.patch.object(src_radio, 'get_mapping_models',
                           return_value=[src_bm])
        @mock.patch.object(dst_bm, 'get_mappings',
                           return_value=dst_banks)
        @mock.patch.object(src_bm, 'get_mappings',
                           return_value=src_banks)
        @mock.patch.object(src_bm, 'get_memory_mappings',
                           return_value=[src_banks[0]])
        @mock.patch.object(dst_bm, 'get_memory_mappings',
                           return_value=[dst_banks[1]])
        @mock.patch.object(dst_bm, 'remove_memory_from_mapping')
        @mock.patch.object(dst_bm, 'add_memory_to_mapping')
        def _test(mock_add, mock_remove, *rest):
            import_logic.import_bank(dst_radio, src_radio, dst_mem, src_mem)
            mock_remove.assert_called_once_with(dst_mem, dst_banks[1])
            mock_add.assert_called_once_with(dst_mem, dst_banks[0])

        _test()
