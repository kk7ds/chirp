import copy
import functools
import logging
import os
import unittest

from chirp import chirp_common
from chirp import bandplan_na

LOG = logging.getLogger(__name__)

_NO_CACHE_ENTRY = object()


class RadioTestFixture:
    """Restore a loaded radio to its original image without reparsing it.

    The fixture keeps the parsed parent and any selected subdevices. Restore
    resets their backing maps and mutable instance state while retaining the
    original radio, map, and bitwise-object identities.
    """

    def __init__(self, parent, sub_device=None):
        self.parent = parent
        self.parent_rf = parent.get_features()
        self.sub_devices = []

        if sub_device is not None:
            self.sub_devices = list(parent.get_sub_devices())
            self.radio = self.sub_devices[sub_device]
            self.rf = self.radio.get_features()
        else:
            self.radio = parent
            self.rf = self.parent_rf

        self._snapshot()

    def _snapshot(self):
        radios = []
        for radio in [self.parent] + self.sub_devices:
            if all(radio is not existing for existing in radios):
                radios.append(radio)

        # A map wrapper can share its backing list with another wrapper.
        # Preserve each wrapper's list reference and snapshot each unique list.
        maps = []
        buffers = []
        for radio in radios:
            mmap = getattr(radio, '_mmap', None)
            data = getattr(mmap, '_data', None)
            if not isinstance(data, list):
                self.cacheable = False
                return
            if all(mmap is not existing[0] for existing in maps):
                maps.append((mmap, data))
            if all(data is not existing[0] for existing in buffers):
                buffers.append((data, data[:]))

        # Preserve the objects that parsed fields refer to, and copy any
        # other instance state so driver-specific caches reset between tests.
        preserved = radios + [mmap for mmap, _data in maps]
        preserved += [data for data, _snapshot in buffers]
        for radio in radios:
            for name in ('_mmap', '_memobj'):
                value = getattr(radio, name, None)
                if value is not None and all(
                        value is not existing for existing in preserved):
                    preserved.append(value)

        try:
            memo = {id(value): value for value in preserved}
            states = []
            for radio in radios:
                state = {name: value
                         for name, value in radio.__dict__.items()
                         if name not in ('_mmap', '_memobj')}
                states.append((radio, copy.deepcopy(state, memo),
                               '_mmap' in radio.__dict__,
                               getattr(radio, '_mmap', None),
                               '_memobj' in radio.__dict__,
                               getattr(radio, '_memobj', None)))
            self._parent_rf = copy.deepcopy(self.parent_rf)
            self._radio_rf = (None if self.radio is self.parent else
                              copy.deepcopy(self.rf))
        except Exception as e:
            LOG.debug('Not caching driver test state for %s: %s',
                      self.parent.__class__, e)
            self.cacheable = False
            return

        self._maps = maps
        self._buffers = buffers
        self._states = states
        self._preserved = preserved
        self.cacheable = True

    def restore(self):
        """Restore and return this fixture's parent/radio/features."""
        if not self.cacheable:
            raise RuntimeError('Radio fixture does not support restoration')

        # Restore the map wrappers to their original lists before restoring
        # list contents. This preserves legacy MemoryMap's shared view.
        for mmap, data in self._maps:
            mmap._data = data
        for data, snapshot in self._buffers:
            data[:] = snapshot

        memo = {id(value): value for value in self._preserved}
        for radio, state, has_mmap, mmap, has_memobj, memobj in self._states:
            for name in list(radio.__dict__):
                if name not in state and name not in ('_mmap', '_memobj'):
                    del radio.__dict__[name]
            radio.__dict__.update(copy.deepcopy(state, memo))
            if has_mmap:
                radio._mmap = mmap
            else:
                radio.__dict__.pop('_mmap', None)
            if has_memobj:
                radio._memobj = memobj
            else:
                radio.__dict__.pop('_memobj', None)

        self.parent_rf = copy.deepcopy(self._parent_rf)
        self.rf = (self.parent_rf if self.radio is self.parent else
                   copy.deepcopy(self._radio_rf))
        return self


class DriverTest(unittest.TestCase):
    RADIO_CLASS = None
    SUB_DEVICE = None
    TEST_IMAGE = None
    CACHE_DRIVER_IMAGE = True

    @classmethod
    def tearDownClass(cls):
        # A driver process runs many generated classes. Drop each cached
        # image when its class finishes instead of retaining all parsed
        # memories for the lifetime of the worker.
        if '_driver_test_fixture' in cls.__dict__:
            del cls._driver_test_fixture
        super().tearDownClass()

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

        # Generated test classes represent one radio/image/subdevice. Keep
        # their parsed template class-local so another image cannot reuse its
        # memory snapshot.
        cls = type(self)
        key = (self.RADIO_CLASS,
               os.path.realpath(self.TEST_IMAGE) if self.TEST_IMAGE else None,
               self.SUB_DEVICE)
        fixture = None
        if self.CACHE_DRIVER_IMAGE:
            entry = cls.__dict__.get('_driver_test_fixture', _NO_CACHE_ENTRY)
            if entry is _NO_CACHE_ENTRY:
                # The fixture owns the parsed parent and any subdevices for
                # this image; later setups restore it instead of reparsing.
                parent = self.RADIO_CLASS(self.TEST_IMAGE)
                fixture = RadioTestFixture(parent, self.SUB_DEVICE)
                if not fixture.cacheable:
                    fixture = None
                cls._driver_test_fixture = (key, fixture)
            elif entry[0] != key:
                # A generated class must remain tied to its original image.
                raise RuntimeError(
                    'Driver test fixture key changed for %s: was %r, now %r' %
                    (cls.__name__, entry[0], key))
            else:
                fixture = entry[1]

        if fixture is not None:
            fixture.restore()
            self.parent = fixture.parent
            self.parent_rf = fixture.parent_rf
            self.radio = fixture.radio
            self.rf = fixture.rf
        else:
            self.parent = self.RADIO_CLASS(self.TEST_IMAGE)
            self.parent_rf = self.parent.get_features()
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
            if chirp_common.is_airband(m.freq):
                # Air band requires special step handling.
                # First see if we can pick a 2m frequency to avoid airband
                # details.
                if chirp_common.in_range(146520000, self.rf.valid_bands):
                    m.freq = 146520000
                else:
                    # Nope, so go 25kHz up from the bottom of the band to
                    # avoid 8.33kHz issues
                    m.freq += 25000
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
            elif k == "offset" and (not self.rf.has_offset or not a.duplex):
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


def requires_feature(flag, equal=None):
    def inner(fn):
        @functools.wraps(fn)
        def wraps(self, *a, **k):
            val = getattr(self.rf, flag)
            if (val == equal if equal is not None else val):
                fn(self, *a, **k)
            else:
                self.skipTest('Feature %s not supported' % flag)
        return wraps
    return inner
