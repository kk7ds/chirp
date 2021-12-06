import glob
import os
import shutil
import sys
import tempfile
import unittest

from chirp import directory

import run_tests


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

    def shortDescription(self):
        test = self.id().split('.')[-1].replace('test_', '').replace('_', ' ')
        return 'Testing %s %s' % (self.RADIO_CLASS.get_name(), test)

    def setUp(self):
        self._out = run_tests.TestOutputANSI()
        rid = "%s_%s_" % (self.RADIO_CLASS.VENDOR, self.RADIO_CLASS.MODEL)
        rid = rid.replace("/", "_")
        self.testimage = tempfile.mktemp('.img', rid)
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


def _get_sub_devices(rclass, testimage):
    try:
        tw = run_tests.TestWrapper(rclass, '/etc/localtime')
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


def _load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()

    if 'CHIRP_TESTIMG' in os.environ:
        images = os.environ['CHIRP_TESTIMG'].split()
    else:
        images = glob.glob("tests/images/*.img")
    tests = [os.path.splitext(os.path.basename(img))[0] for img in images]

    for test in tests:
        image = os.path.join('tests', 'images', '%s.img' % test)
        rclass = directory.get_radio(test)
        for device in _get_sub_devices(rclass, image):
            class_name = 'TestCase_%s' % (
                filter(lambda c: c.isalnum(),
                       device.get_name()))
            if isinstance(device, type):
                dst = None
            else:
                dst = device
                device = device.__class__
            tc = TestAdapterMeta(
                class_name, (TestAdapter,), dict(RADIO_CLASS=device,
                                                 SOURCE_IMAGE=image,
                                                 RADIO_INST=dst))
        suite.addTests(loader.loadTestsFromTestCase(tc))

    return suite


def load_tests(loader, tests, pattern):
    try:
        return _load_tests(loader, tests, pattern)
    except Exception as e:
        import traceback
        print('Failed to load: %s' % e)
        print(traceback.format_exc())
        raise
