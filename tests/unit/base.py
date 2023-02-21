import builtins
import sys
import unittest

from unittest import mock

import warnings
warnings.simplefilter('ignore', Warning)

builtins._ = lambda x: x


class BaseTest(unittest.TestCase):
    def setUp(self):
        __builtins__['_'] = lambda s: s
        self.mocks = []

    def tearDown(self):
        for m in self.mocks:
            m.stop()
