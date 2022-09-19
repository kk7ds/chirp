import functools
import glob
import logging
import os
import re
import shutil
import sys
import tempfile
import unittest

import pytest
import six

from chirp import directory

from tests import run_tests


LOG = logging.getLogger('testadapter')
PY3_XFAIL = []


def if_enabled(fn):
    name = fn.__name__.replace('test_', '')
    if 'CHIRP_TESTS' in os.environ:
        tests_enabled = os.environ['CHIRP_TESTS'].split(',')
        enabled = name in tests_enabled
    else:
        enabled = True

    def wrapper(*a, **k):
        if enabled:
            return fn(*a, **k)
        else:
            raise unittest.SkipTest('%s not enabled' % name)

    return wrapper


class TestAdapterMeta(type):
    def __new__(cls, name, parents, dct):
        return super(TestAdapterMeta, cls).__new__(cls, name, parents, dct)


class TestAdapter(unittest.TestCase):
    RADIO_CLASS = None
    SOURCE_IMAGE = None
    RADIO_INST = None
    testwrapper = None
    XFAIL = False

    def shortDescription(self):
        test = self.id().split('.')[-1].replace('test_', '').replace('_', ' ')
        return 'Testing %s %s' % (self.RADIO_CLASS.get_name(), test)

    @classmethod
    def setUpClass(cls):
        if not cls.testwrapper:
            # Initialize the radio once per class invocation to save
            # bitwise parse time
            # Do this for things like Generic_CSV, that demand it
            _base, ext = os.path.splitext(cls.SOURCE_IMAGE)
            cls.testimage = tempfile.mktemp(ext)
            shutil.copy(cls.SOURCE_IMAGE, cls.testimage)
            cls.testwrapper = run_tests.TestWrapper(cls.RADIO_CLASS,
                                                    cls.testimage)

    @classmethod
    def tearDownClass(cls):
        os.remove(cls.testimage)

    def setUp(self):
        self._out = run_tests.TestOutputANSI()
        rid = "%s_%s_" % (self.RADIO_CLASS.VENDOR, self.RADIO_CLASS.MODEL)
        rid = rid.replace("/", "_")
        basefn, ext = os.path.splitext(self.testimage)
        self.testimage = tempfile.mktemp('.%s' % ext, rid)
        shutil.copy(self.SOURCE_IMAGE, self.testimage)

    def tearDown(self):
        os.remove(self.testimage)

    def _runtest(self, test):
        tw = run_tests.TestWrapper(self.RADIO_CLASS,
                                   self.testimage,
                                   dst=self.RADIO_INST)
        testcase = test(tw)
        testcase.prepare()
        try:
            failures = testcase.run()
            if failures:
                raise failures[0]
        except run_tests.TestCrashError as e:
            raise e.get_original_exception()
        except run_tests.TestSkippedError as e:
            raise unittest.SkipTest(str(e))
        finally:
            testcase.cleanup()

    @if_enabled
    def test_copy_all(self):
        self._runtest(run_tests.TestCaseCopyAll)

    @if_enabled
    def test_brute_force(self):
        self._runtest(run_tests.TestCaseBruteForce)

    @if_enabled
    def test_edges(self):
        self._runtest(run_tests.TestCaseEdges)

    @if_enabled
    def test_settings(self):
        self._runtest(run_tests.TestCaseSettings)

    @if_enabled
    def test_banks(self):
        self._runtest(run_tests.TestCaseBanks)

    @if_enabled
    def test_detect(self):
        self._runtest(run_tests.TestCaseDetect)

    @if_enabled
    def test_clone(self):
        self._runtest(run_tests.TestCaseClone)

    def test_py3_expected(self):
        assert self.SOURCE_IMAGE not in PY3_XFAIL


def _get_sub_devices(rclass, testimage):
    try:
        tw = run_tests.TestWrapper(rclass, None)
    except Exception as e:
        tw = run_tests.TestWrapper(rclass, testimage)

    try:
        rf = tw.do("get_features")
    except Exception as e:
        print('Failed to get features for %s: %s' % (rclass, e))
        # FIXME: If the driver fails to run get_features with no memobj
        # we should not arrest the test load. This appears to happen for
        # the Puxing777 for some reason, and not all the time. Figure that
        # out, but until then, assume crash means "no sub devices".
        return [rclass]
    if rf.has_sub_devices:
        return tw.do("get_sub_devices")
    else:
        return [rclass]


class TestAdapterXFAIL(TestAdapter):
    @pytest.mark.xfail(reason=('Driver not expected to run in python3. '
                               'Remove from py3_remaining.txt'), strict=True)
    def test_py3_expected(self):
        pass


class RadioSkipper(unittest.TestCase):
    def test_is_supported_by_environment(self):
        raise unittest.SkipTest('Running in py3 and driver is not supported')


def _load_tests(loader, tests, pattern, suite=None):
    if not suite:
        suite = unittest.TestSuite()

    if 'CHIRP_TESTIMG' in os.environ:
        images = os.environ['CHIRP_TESTIMG'].split()
    else:
        images = glob.glob("tests/images/*.img")
    tests = [os.path.splitext(os.path.basename(img))[0] for img in images]

    base = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(base, 'images')
    images = glob.glob(os.path.join(base, "*"))
    tests = {img: os.path.splitext(os.path.basename(img))[0] for img in images}

    if pattern == 'test*.py':
        # This default is meaningless for us
        pattern = None

    py3_remaining = [x.strip() for x in open(os.path.join(
        base, '..', 'py3_remaining.txt')).readlines()
                     if not x.startswith('#')]

    for image, test in tests.items():
        try:
            rclass = directory.get_radio(test)
            if os.path.basename(image) in py3_remaining:
                PY3_XFAIL.append(image)

        except Exception:
            if not six.PY3:
                raise

            if 'CHIRP_DEBUG' in os.environ:
                LOG.error('Failed to load %s' % test)

            if os.path.basename(image) in py3_remaining:
                # We expect this to fail to import in py3, so do not
                # abort the test run.
                continue
            print('%s not in py3 exclusion list %s...' % (
                os.path.basename(image), ','.join(py3_remaining)))
            raise
        for device in _get_sub_devices(rclass, image):
            class_name = 'TestCase_%s' % (
                ''.join(filter(lambda c: c.isalnum(),
                               device.get_name())))
            if isinstance(device, type):
                dst = None
            else:
                dst = device
                device = device.__class__

            if image in PY3_XFAIL:
                cls = TestAdapterXFAIL
            else:
                cls = TestAdapter

            tc = TestAdapterMeta(
                class_name, (cls,), dict(RADIO_CLASS=device,
                                         SOURCE_IMAGE=image,
                                         RADIO_INST=dst))
            tests = loader.loadTestsFromTestCase(tc)

            if pattern:
                tests = [t for t in tests
                         if re.search(pattern, '%s.%s' % (class_name,
                                                          t._testMethodName))]

            suite.addTests(tests)

    return suite


def load_tests(loader, tests, pattern, suite=None):
    try:
        return _load_tests(loader, tests, pattern, suite=suite)
    except Exception as e:
        import traceback
        print('Failed to load: %s' % e)
        print(traceback.format_exc())
        raise
