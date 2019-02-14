import sys
import unittest

from chirp import directory
from tests import load_tests


class TestSuiteAdapter(object):
    """Adapter for pytest since it doesn't support the loadTests() protocol"""

    def __init__(self, locals):
        self.locals = locals

    def loadTestsFromTestCase(self, test_cls):
        self.locals[test_cls.__name__] = test_cls

    @staticmethod
    def addTests(tests):
        pass


directory.safe_import_drivers()
adapter = TestSuiteAdapter(locals())
load_tests(adapter, None, None, suite=adapter)
