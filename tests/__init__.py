import glob
import logging
import os
import unittest

import pytest

from chirp import directory

from tests import test_banks
from tests import test_brute_force
from tests import test_clone
from tests import test_copy_all
from tests import test_detect
from tests import test_edges
from tests import test_features
from tests import test_settings

LOG = logging.getLogger('testadapter')


class TestAdapterMeta(type):
    def __new__(cls, name, parents, dct):
        return super(TestAdapterMeta, cls).__new__(cls, name, parents, dct)


def _get_sub_devices(rclass, testimage):
    try:
        radio = rclass(None)
        rf = radio.get_features()
    except Exception as e:
        print('Failed to get features for %s: %s' % (rclass, e))
        # FIXME: If the driver fails to run get_features with no memobj
        # we should not arrest the test load. This appears to happen for
        # the Puxing777 for some reason, and not all the time. Figure that
        # out, but until then, assume crash means "no sub devices".
        return [rclass]
    if rf.has_sub_devices:
        # Radios with sub-devices may need to look at the image to determine
        # what those are. That's slow, so only do it for these.
        radio = rclass(testimage)
        return radio.get_sub_devices()
    else:
        return [rclass]


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

    driver_test_cases = (test_edges.TestCaseEdges,
                         test_edges.TestBitwiseStrict,
                         test_brute_force.TestCaseBruteForce,
                         test_banks.TestCaseBanks,
                         test_detect.TestCaseDetect,
                         test_clone.TestCaseClone,
                         test_settings.TestCaseSettings,
                         test_features.TestCaseFeatures,
                         test_copy_all.TestCaseCopyAll)

    for image, test in tests.items():
        rclass = directory.get_radio(test)
        if hasattr(rclass, '_orig_rclass'):
            rclass = rclass._orig_rclass
        module = rclass.__module__.split('.')[-1]
        subdevs = _get_sub_devices(rclass, image)
        has_subdevs = subdevs != [rclass]
        for index, device in enumerate(subdevs):
            if not isinstance(device, type):
                device = device.__class__
            for case in driver_test_cases:
                tc = TestAdapterMeta(
                    "%s_%s" % (case.__name__,
                               directory.radio_class_id(device)),
                    (case,),
                    {'RADIO_CLASS': rclass,
                     'SUB_DEVICE': index if has_subdevs else None,
                     'TEST_IMAGE': image})

                tc = getattr(pytest.mark, module)(tc)
                suite.addTests(loader.loadTestsFromTestCase(tc))

    return suite


def load_tests(loader, tests, pattern, suite=None):
    try:
        return _load_tests(loader, tests, pattern, suite=suite)
    except Exception as e:
        import traceback
        print('Failed to load: %s' % e)
        print(traceback.format_exc())
        raise
