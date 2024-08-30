import functools
import logging
import os
import unittest

from chirp import chirp_common
from chirp import bandplan_na

LOG = logging.getLogger(__name__)


class DriverTest(unittest.TestCase):
    RADIO_CLASS = None
    SUB_DEVICE = None
    TEST_IMAGE = None

    def setUp(self):
        super().setUp()
        self.patches = []

        if ('CHIRP_TEST_BITWISE_STRICT_BYTES' in os.environ and
                not self.RADIO_CLASS.NEEDS_COMPAT_SERIAL):
            self.use_patch(unittest.mock.patch(
                'chirp.bitwise.DataElement._compat_bytes',
                side_effect=self._strict_bytes))
            self.use_patch(unittest.mock.patch(
                'chirp.bitwise.string_straight_encode',
                side_effect=AssertionError(
                    'string_straight_encode not allowed in strict mode')))

        self.parent = self.RADIO_CLASS(self.TEST_IMAGE)
        self.parent_rf = self.parent.get_features()
        # If SUB_DEVICE is set to an index, then the actual radio we are
        # to test is get_sub_devices()[SUB_DEVICE]. Otherwise, it's the
        # actual class we were handed.
        if self.SUB_DEVICE is not None:
            self.radio = self.parent.get_sub_devices()[self.SUB_DEVICE]
            self.rf = self.radio.get_features()
        else:
            self.radio = self.parent
            self.rf = self.parent_rf

    def use_patch(self, patch):
        self.patches.append(patch)
        patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def _strict_bytes(self, bs, asbytes):
        """Enforce strict get_raw() behavior returning bytes()"""
        assert asbytes, 'asbytes must be True in strict mode'
        assert isinstance(bs, bytes), 'Type should be bytes here'
        return bs

    def get_mem(self):
        """Attempt to build a suitable memory for testing"""
        # Check to see if memory #1 has immutable fields, and if so,
        # use that as our template instead of constructing a memory ourselves
        try:
            m = self.radio.get_memory(1)
            # Pre-filter the name so it will match what we expect back
            if 'name' not in m.immutable:
                m.name = self.radio.filter_name(m.name)
            # Disable duplex in case it's set because this will cause some
            # weirdness if we much with other values, like offset.
            if 'duplex' not in m.immutable:
                m.duplex = ''
            if m.immutable:
                return m
        except Exception:
            pass

        m = chirp_common.Memory()

        # Some of the exposed bands may not be transmit-enabled, so
        # iterate them all
        attempt = 0
        for band_lo, band_hi in self.rf.valid_bands:
            m.freq = band_lo
            if self.rf.valid_tuning_steps:
                # If we have valid tuning steps, go one step above the
                # bottom of the band. Select a different tuning_step each
                # time, as some radios have various requirements for which
                # steps work in each band, mode, etc.
                steps = [x for x in self.rf.valid_tuning_steps
                         if x > 1]
                step_index = attempt % len(steps)
                m.tuning_step = steps[step_index]
                m.freq += int(m.tuning_step * 1000)
            elif m.freq + 1000000 < band_hi:
                # Otherwise just pick 1MHz above the bottom, which has been
                # our test basis for a long time, unless that extends past
                # the end of the band.
                m.freq += 1000000

            if m.freq < 30000000 and "AM" in self.rf.valid_modes:
                m.mode = "AM"
            else:
                try:
                    m.mode = self.rf.valid_modes[0]
                except IndexError:
                    pass

            for i in range(*self.rf.memory_bounds)[:10]:
                m.number = i
                msgs = self.radio.validate_memory(m)
                warnings, errors = chirp_common.split_validation_msgs(msgs)
                if warnings and not errors:
                    # If we got some warnings and no errors, then we know the
                    # memory is almost good enough. Set it and pull it back
                    # to let the radio squash whatever was "almost correct"
                    # and then use that.
                    self.radio.set_memory(m)
                    m = self.radio.get_memory(m.number)
                    try:
                        del m.extra
                    except AttributeError:
                        pass
                    return m
                # If we got no warnings, or we have only one band, then
                # no errors means we found our candidate.
                elif not errors:
                    return m

                attempt += 1

        self.fail("No mutable memory locations found - unable to run this "
                  "test because I don't have a memory to test with")

    def assertEqualMem(self, a, b, ignore=None):
        if a.tmode == "Cross":
            tx_mode, rx_mode = a.cross_mode.split("->")
        if ignore is None:
            ignore = []

        if a.duplex == b.duplex == 'off':
            # If we're asking for duplex=off, we should not obsess over the
            # driver keeping track of our offset, as it may use the offset
            # field to manage the TX behavior
            ignore.append('offset')

        a_vals = {}
        b_vals = {}

        for k, v in list(a.__dict__.items()):
            if ignore and k in ignore:
                continue
            if k == "power":
                continue  # FIXME
            elif k == "extra":
                continue
            elif k == "immutable":
                continue
            elif k == "name":
                if not self.rf.has_name:
                    continue  # Don't complain about name, if not supported
                else:
                    # Name mismatch fair if filter_name() is right
                    v = self.radio.filter_name(v).rstrip()
            elif k == "tuning_step" and not self.rf.has_tuning_step:
                continue
            elif k == "rtone" and not (
                a.tmode == "Tone" or
                (a.tmode == "TSQL" and not self.rf.has_ctone) or
                (a.tmode == "Cross" and tx_mode == "Tone") or
                (a.tmode == "Cross" and rx_mode == "Tone" and
                 not self.rf.has_ctone)
            ):
                continue
            elif k == "ctone" and (not self.rf.has_ctone or
                                   not (a.tmode == "TSQL" or
                                        (a.tmode == "Cross" and
                                         rx_mode == "Tone"))):
                continue
            elif k == "dtcs" and (a.tmode != 'DTCS' or
                                  (a.tmode == 'Cross' and tx_mode != 'DTCS')):
                # If we are not in a tmode where a transmit DTCS code is
                # required, we do not care if the code is persisted.
                continue
            elif k == "rx_dtcs" and (not self.rf.has_rx_dtcs or
                                     not (a.tmode == "Cross" and
                                          rx_mode == "DTCS")):
                # If we are not in a tmode where a receive DTCS code is
                # required, we do not care if the code is persisted.
                continue
            elif k == "offset" and not a.duplex:
                continue
            elif k == "cross_mode" and a.tmode != "Cross":
                continue

            if (a.freq in bandplan_na.ALL_GMRS_FREQS and
                    k in a.immutable or k in b.immutable):
                # If the radio returned a field in immutable, it probably
                # means that it's a mandatory setting (i.e. power or duplex
                # in GMRS)
                continue

            a_vals[k] = v
            b_vals[k] = b.__dict__[k]

        self.assertEqual(a_vals, b_vals,
                         'Memories have unexpected differences')

        # Consider mem.extra as matching if the structure remains the same.
        # Since we don't know anything about model-specific things here we
        # can't really assert any more than that, but we can ensure that the
        # structure doesn't change due to the contents of the rest of the
        # memory.
        if a.extra and b.extra:
            self.assertEqual([x.get_name() for x in a.extra],
                             [x.get_name() for x in b.extra],
                             'Memories have different mem.extra keys')


def requires_feature(flag):
    def inner(fn):
        @functools.wraps(fn)
        def wraps(self, *a, **k):
            if getattr(self.rf, flag):
                fn(self, *a, **k)
            else:
                self.skipTest('Feature %s not supported' % flag)
        return wraps
    return inner
