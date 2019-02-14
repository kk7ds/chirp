import glob
import logging
import os
import re
import shutil
import sys
import tempfile
import unittest

import six

from chirp import directory

from tests import run_tests


LOG = logging.getLogger('testadapter')


class TestAdapterMeta(type):
    def __new__(cls, name, parents, dct):
        return super(TestAdapterMeta, cls).__new__(cls, name, parents, dct)


class TestAdapter(unittest.TestCase):
    RADIO_CLASS = None
    SOURCE_IMAGE = None

    def shortDescription(self):
        test = self.id().split('.')[-1].replace('test_', '').replace('_', ' ')
        return 'Testing %s %s' % (self.RADIO_CLASS.get_name(), test)

    def setUp(self):
        self._out = run_tests.TestOutputANSI()
        self.testimage = tempfile.mktemp('.img')
        shutil.copy(self.SOURCE_IMAGE, self.testimage)

    def tearDown(self):
        os.remove(self.testimage)

    def _runtest(self, test):
        tw = run_tests.TestWrapper(self.RADIO_CLASS,
                                   self.testimage)
        testcase = test(tw)
        testcase.prepare()
        try:
            testcase.run()
        except run_tests.TestSkippedError as e:
            raise unittest.SkipTest(str(e))
        finally:
            testcase.cleanup()

    def test_copy_all(self):
        self._runtest(run_tests.TestCaseCopyAll)

    def test_brute_force(self):
        self._runtest(run_tests.TestCaseBruteForce)

    def test_edges(self):
        self._runtest(run_tests.TestCaseEdges)

    def test_settings(self):
        self._runtest(run_tests.TestCaseSettings)

    def test_banks(self):
        self._runtest(run_tests.TestCaseBanks)

    def test_detect(self):
        self._runtest(run_tests.TestCaseDetect)

    def test_clone(self):
        self._runtest(run_tests.TestCaseClone)


def _get_sub_devices(rclass, testimage):
    try:
        tw = run_tests.TestWrapper(rclass, '/etc/localtime')
    except Exception as e:
        tw = run_tests.TestWrapper(rclass, testimage)

    rf = tw.do("get_features")
    if rf.has_sub_devices:
        return [r.__class__ for r in tw.do("get_sub_devices")]
    else:
        return [rclass]


class RadioSkipper(unittest.TestCase):
    def test_is_supported_by_environment(self):
        raise unittest.SkipTest('Running in py3 and driver is not supported')


def load_tests(loader, tests, pattern, suite=None):
    if not suite:
        suite = unittest.TestSuite()

    base = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(base, 'images')
    images = glob.glob(os.path.join(base, "*.img"))
    tests = [os.path.splitext(os.path.basename(img))[0] for img in images]

    if pattern == 'test*.py':
        # This default is meaningless for us
        pattern = None

    for test in tests:
        image = os.path.join(base, '%s.img' % test)
        try:
            rclass = directory.get_radio(test)
        except Exception:
            if six.PY3 and 'CHIRP_DEBUG' in os.environ:
                LOG.error('Failed to load %s' % test)
                continue
            raise
        for device in _get_sub_devices(rclass, image):
            class_name = 'TestCase_%s' % (
                ''.join(filter(lambda c: c.isalnum(),
                               device.get_name())))
            tc = TestAdapterMeta(
                class_name, (TestAdapter,), dict(RADIO_CLASS=device,
                                                 SOURCE_IMAGE=image))
            tests = loader.loadTestsFromTestCase(tc)

            if pattern:
                tests = [t for t in tests
                         if re.search(pattern, '%s.%s' % (class_name,
                                                          t._testMethodName))]

            suite.addTests(tests)

    return suite
