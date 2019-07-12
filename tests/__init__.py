import glob
import os
import shutil
import sys
import tempfile
import unittest

from chirp import directory

import run_tests


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
        self.testimage = tempfile.mktemp('.img')
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
        return tw.do("get_sub_devices")
    else:
        return [rclass]


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()

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
