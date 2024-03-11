import builtins
import unittest

import warnings
warnings.simplefilter('ignore', Warning)

builtins._ = lambda x: x


class BaseTest(unittest.TestCase):
    def setUp(self):
        __builtins__['_'] = lambda s: s
        self.mocks = []

    def use(self, m):
        self.mocks.append(m)
        m.start()

    def tearDown(self):
        for m in self.mocks:
            m.stop()
