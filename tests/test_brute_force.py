import logging

from chirp import chirp_common
from chirp import errors
from tests import base

LOG = logging.getLogger(__name__)


class TestCaseBruteForce(base.DriverTest):
    def set_and_compare(self, m, **kwargs):
        msgs = self.radio.validate_memory(m)
        if msgs:
            # If the radio correctly refuses memories it can't
            # store, don't fail
            return

        self.radio.set_memory(chirp_common.FrozenMemory(m))
        ret_m = self.radio.get_memory(m.number)

        # Damned Baofeng radios don't seem to properly store
        # shift and direction, so be gracious here
        if m.duplex == "split" and ret_m.duplex in ["-", "+"]:
            ret_m.offset = ret_m.freq + \
                (ret_m.offset * int(ret_m.duplex + "1"))
            ret_m.duplex = "split"

        self.assertEqualMem(m, ret_m, **kwargs)

    def test_tone(self):
        m = self.get_mem()
        for tone in chirp_common.TONES:
            for tmode in self.rf.valid_tmodes:
                if tmode not in chirp_common.TONE_MODES:
                    continue
                elif tmode in ["DTCS", "DTCS-R", "Cross"]:
                    continue  # We'll test DCS and Cross tones separately

                m.tmode = tmode
                if tmode == "":
                    pass
                elif tmode == "Tone":
                    m.rtone = tone
                elif tmode in ["TSQL", "TSQL-R"]:
                    if self.rf.has_ctone:
                        m.ctone = tone
                    else:
                        m.rtone = tone
                else:
                    self.fail("Unknown tone mode `%s'" % tmode)

                try:
                    self.set_and_compare(m)
                except errors.UnsupportedToneError:
                    # If a radio doesn't support a particular tone value,
                    # don't punish it
                    pass

    @base.requires_feature('has_dtcs')
    def test_dtcs(self):
        m = self.get_mem()
        m.tmode = "DTCS"
        for code in self.rf.valid_dtcs_codes:
            m.dtcs = code
            self.set_and_compare(m)

        if not self.rf.has_dtcs_polarity:
            return

        for pol in self.rf.valid_dtcs_pols:
            m.dtcs_polarity = pol
            self.set_and_compare(m)

    @base.requires_feature('has_cross')
    def test_cross(self):
        m = self.get_mem()
        m.tmode = "Cross"
        # No fair asking a radio to detect two identical tones as Cross instead
        # of TSQL
        m.rtone = 100.0
        m.ctone = 107.2
        m.dtcs = 506
        m.rx_dtcs = 516
        for cross_mode in self.rf.valid_cross_modes:
            m.cross_mode = cross_mode
            self.set_and_compare(m)

    @base.requires_feature('valid_duplexes')
    def test_duplex(self):
        m = self.get_mem()
        if 'duplex' in m.immutable:
            self.skipTest('Test memory has immutable duplex')
        for duplex in self.rf.valid_duplexes:
            assert duplex in ["", "-", "+", "split", "off"]
            if duplex == 'split':
                self.assertTrue(self.rf.can_odd_split,
                                'Radio supports split but does not set '
                                'can_odd_split=True in features')
                m.offset = self.rf.valid_bands[0][1] - 100000
            else:
                m.offset = chirp_common.to_kHz(int(m.tuning_step) * 2)
            m.duplex = duplex
            # Ignore the offset because we do some fudging on this and we
            # don't necessarily know the best step to use. What we care about
            # is duplex here.
            self.set_and_compare(m, ignore=['offset'])

        if self.rf.can_odd_split:
            self.assertIn('split', self.rf.valid_duplexes,
                          'Radio claims can_odd_split but split not in '
                          'valid_duplexes')

    @base.requires_feature('valid_skips')
    def test_skip(self):
        mem = self.get_mem()
        lo, hi = self.rf.memory_bounds
        # Walk through several memories, specifically across 8 and 16,
        # as many radio use bitfields for skip flags.
        for i in range(max(5, lo), min(25, hi)):
            # Walk through the skip flags twice each, to make sure we can
            # toggle them on..off..on
            for skip in self.rf.valid_skips * 2:
                m = mem.dupe()
                if 'empty' not in m.immutable:
                    m.empty = False
                m.number = i
                m.skip = skip
                self.set_and_compare(m)
                # Delete the memory each time because some radios are
                # dynamically allocated and will run out of space here.
                self.radio.erase_memory(m.number)

    @base.requires_feature('valid_modes')
    def test_mode(self):
        m = self.get_mem()
        if 'mode' in m.immutable:
            self.skipTest('Test memory has immutable duplex')

        def ensure_urcall(call):
            lst = self.radio.get_urcall_list()
            lst[0] = call
            self.radio.set_urcall_list(lst)

        def ensure_rptcall(call):
            lst = self.radio.get_repeater_call_list()
            lst[0] = call
            self.radio.set_repeater_call_list(lst)

        def freq_is_ok(freq):
            for lo, hi in self.rf.valid_bands:
                if freq > lo and freq < hi:
                    return True
            return False

        successes = 0
        for mode in self.rf.valid_modes:
            self.assertIn(mode, chirp_common.MODES,
                          'Radio exposes non-standard mode')
            tmp = m.dupe()
            if mode == "DV" and \
                isinstance(self.radio,
                           chirp_common.IcomDstarSupport):
                tmp = chirp_common.DVMemory()
                try:
                    ensure_urcall(tmp.dv_urcall)
                    ensure_rptcall(tmp.dv_rpt1call)
                    ensure_rptcall(tmp.dv_rpt2call)
                except IndexError:
                    if self.rf.requires_call_lists:
                        raise
                    else:
                        # This radio may not do call lists at all,
                        # so let it slide
                        pass
            if mode == "FM" and freq_is_ok(tmp.freq + 100000000):
                # Some radios don't support FM below approximately 30MHz,
                # so jump up by 100MHz, if they support that
                tmp.freq += 100000000

            tmp.mode = mode

            if self.rf.validate_memory(tmp):
                # A result (of error messages) from validate means the radio
                # thinks this is invalid, so don't fail the test
                LOG.warning('Failed to validate %s: %s' % (
                    tmp, self.rf.validate_memory(tmp)))
                continue

            # Ignore tuning_step because changing modes may cause step changes
            # in some radios
            self.set_and_compare(tmp, ignore=['tuning_step'])
            successes += 1
