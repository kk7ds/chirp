import pytest
from unittest import mock

from chirp import bitwise
from chirp import chirp_common
from chirp import errors
from tests import base


class TestCaseEdges(base.DriverTest):
    def test_longname(self):
        m = self.get_mem()
        m.name = ("X" * 256)  # Should be longer than any radio can handle
        m.name = self.radio.filter_name(m.name)

        self.radio.set_memory(m)
        n = self.radio.get_memory(m.number)

        self.assertEqualMem(m, n)

    def test_badname(self):
        m = self.get_mem()

        ascii = "".join([chr(x) for x in range(ord(" "), ord("~")+1)])
        for i in range(0, len(ascii), 4):
            m.name = self.radio.filter_name(ascii[i:i+4])
            self.radio.set_memory(m)
            n = self.radio.get_memory(m.number)
            self.assertEqualMem(m, n)

    def test_bandedges(self):
        m = self.get_mem()
        min_step = min(self.rf.has_tuning_step and
                       self.rf.valid_tuning_steps or [10])

        for low, high in self.rf.valid_bands:
            for freq in (low, high - int(min_step * 1000)):
                try:
                    m.freq = freq
                except chirp_common.ImmutableValueError:
                    self.skipTest('Test memory has immutable freq')
                if self.radio.validate_memory(m):
                    # Radio doesn't like it, so skip
                    continue

                self.radio.set_memory(m)
                n = self.radio.get_memory(m.number)
                self.assertEqualMem(m, n)

    def test_oddsteps(self):
        odd_steps = {
            145000000: [145856250, 145862500],
            445000000: [445856250, 445862500],
            862000000: [862731250, 862737500],
        }

        m = self.get_mem()

        for low, high in self.rf.valid_bands:
            for band, totest in list(odd_steps.items()):
                if band < low or band > high:
                    continue
                for testfreq in totest:
                    step = chirp_common.required_step(testfreq)
                    if step not in self.rf.valid_tuning_steps:
                        continue

                    try:
                        m.freq = testfreq
                    except chirp_common.ImmutableValueError:
                        self.skipTest('Test channel has immutable freq')
                    m.tuning_step = step
                    self.radio.set_memory(m)
                    n = self.radio.get_memory(m.number)
                    # Some radios have per-band required modes, which we
                    # don't care about testing here
                    self.assertEqualMem(m, n, ignore=['tuning_step',
                                                      'mode'])

    def test_empty_to_not(self):
        firstband = self.rf.valid_bands[0]
        testfreq = firstband[0]
        for loc in range(*self.rf.memory_bounds):
            m = self.radio.get_memory(loc)
            if m.empty:
                m.empty = False
                m.freq = testfreq
                self.radio.set_memory(m)
                m = self.radio.get_memory(loc)
                self.assertEqual(testfreq, m.freq,
                                 'Radio returned an unexpected frequency when'
                                 'setting previously-empty location %i' % loc)
                break

    def test_delete_memory(self):
        for loc in range(*self.rf.memory_bounds):
            m = self.radio.get_memory(loc)
            if 'empty' in m.immutable:
                # This memory is not deletable
                continue
            if not m.empty:
                m.empty = True
                self.radio.set_memory(m)
                m = self.radio.get_memory(loc)
                self.assertTrue(m.empty,
                                'Radio returned non-empty memory when asked '
                                'to delete location %i' % loc)
                break

    def test_get_set_specials(self):
        if not self.rf.valid_special_chans:
            self.skipTest('Radio has no specials')
        lo, hi = self.rf.memory_bounds
        for name in self.rf.valid_special_chans:
            m1 = self.radio.get_memory(name)
            # Flip to non-empty, but only touch it if it's false because some
            # radios have empty in the immutable set.
            if m1.empty:
                m1.empty = False
            try:
                del m1.extra
            except AttributeError:
                pass
            if m1.freq > 130000000 and m1.freq < 500000000:
                m1.freq += 5000
            elif m1.freq == 0:
                # If the memory was empty before, we likely need to pick
                # a valid frequency. Use the bottom of the first supported
                # band.
                m1.freq = self.rf.valid_bands[0][0]
            try:
                self.radio.set_memory(m1)
            except errors.RadioError:
                # If the radio raises RadioError, assume we're editing a
                # special channel that is not editable
                continue
            m2 = self.radio.get_memory(name)
            self.assertEqualMem(m1, m2, ignore=['name'])

            self.assertFalse(
                lo < m1.number < hi,
                'Special memory %s maps into memory bounds at %i' % (
                    name, m1.number))

    def test_check_regular_not_special(self):
        lo, hi = self.rf.memory_bounds
        for i in range(lo, hi + 1):
            m = self.radio.get_memory(i)
            self.assertEqual('', m.extd_number,
                             'Non-special memory %i should not have '
                             'extd_number set to %r' % (i, m.extd_number))

    def test_get_memory_name_trailing_whitespace(self):
        if self.radio.MODEL == 'KG-UV8E':
            self.skipTest('The UV8E driver is so broken it does not even '
                          'parse its own test image cleanly')
        for i in range(*self.rf.memory_bounds):
            m = self.radio.get_memory(i)
            self.assertEqual(m.name.rstrip(), m.name,
                             'Radio returned a memory with trailing '
                             'whitespace in the name')

    def test_memory_name_stripped(self):
        if ' ' not in self.rf.valid_characters:
            self.skipTest('Radio does not support space characters')
        m1 = self.get_mem()
        m1.name = 'FOO '
        self.radio.set_memory(m1)
        m2 = self.radio.get_memory(m1.number)
        self.assertEqual(m2.name.rstrip(), m2.name,
                         'Radio set and returned a memory with trailing '
                         'whitespace in the name')


class TestBitwiseStrict(base.DriverTest):
    def setUp(self):
        pass

    def _raise(self, message):
        raise SyntaxError(message)

    @pytest.mark.xfail(strict=False)
    @mock.patch.object(bitwise.Processor, 'assert_negative_seek',
                       side_effect=_raise)
    def test_bitwise_negative_seek(self, mock_assert):
        super().setUp()

    @pytest.mark.xfail(strict=False)
    @mock.patch.object(bitwise.Processor, 'assert_unnecessary_seek',
                       side_effect=_raise)
    def test_bitwise_unnecessary_seek(self, mock_assert):
        super().setUp()

    @mock.patch.object(bitwise.LOG, 'error')
    def test_bitwise_errors(self, mock_log):
        super().setUp()
        self.assertFalse(mock_log.called,
                         [x[0][0] for x in mock_log.call_args_list])
