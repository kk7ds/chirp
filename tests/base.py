import functools
import logging
import unittest

from chirp import chirp_common

LOG = logging.getLogger(__name__)


class DriverTest(unittest.TestCase):
    RADIO_CLASS = None
    TEST_IMAGE = None

    def setUp(self):
        super().setUp()
        self.radio = self.RADIO_CLASS(self.TEST_IMAGE)
        self.rf = self.radio.get_features()
        self.patches = []

    def use_patch(self, patch):
        self.patches.append(patch)
        patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def get_mem(self):
        """Attempt to build a suitable memory for testing"""
        # If we have a memory in spot 1, use that
        try:
            m = self.radio.get_memory(1)
            # Don't return extra because it will never match properly
            del m.extra
            # Pre-filter the name so it will match what we expect back
            if 'name' not in m.immutable:
                m.name = self.radio.filter_name(m.name)
            # Disable duplex in case it's set because this will cause some
            # weirdness if we much with other values, like offset.
            if 'duplex' not in m.immutable:
                m.duplex = ''
            return m
        except Exception:
            pass

        m = chirp_common.Memory()
        m.freq = self.rf.valid_bands[0][0] + 1000000
        if m.freq < 30000000 and "AM" in self.rf.valid_modes:
            m.mode = "AM"
        else:
            try:
                m.mode = self.rf.valid_modes[0]
            except IndexError:
                pass

        for i in range(*self.rf.memory_bounds):
            m.number = i
            if not self.radio.validate_memory(m):
                return m

        self.fail("No mutable memory locations found")

    def assertEqualMem(self, a, b, ignore=None):
        if a.tmode == "Cross":
            tx_mode, rx_mode = a.cross_mode.split("->")

        a_vals = {}
        b_vals = {}

        for k, v in list(a.__dict__.items()):
            if ignore and k in ignore:
                continue
            if k == "power":
                continue  # FIXME
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
            elif k == "dtcs" and not (
                    (a.tmode == "DTCS" and not self.rf.has_rx_dtcs) or
                    (a.tmode == "Cross" and tx_mode == "DTCS") or
                    (a.tmode == "Cross" and rx_mode == "DTCS" and
                     not self.rf.has_rx_dtcs)):
                continue
            elif k == "rx_dtcs" and (not self.rf.has_rx_dtcs or
                                     not (a.tmode == "Cross" and
                                          rx_mode == "DTCS")):
                continue
            elif k == "offset" and not a.duplex:
                continue
            elif k == "cross_mode" and a.tmode != "Cross":
                continue

            a_vals[k] = v
            b_vals[k] = b.__dict__[k]

        self.assertEqual(a_vals, b_vals,
                         'Memories have unexpected differences')


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