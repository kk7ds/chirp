import unittest
import mox

import warnings
warnings.simplefilter('ignore', Warning)


class BaseTest(unittest.TestCase):
    def setUp(self):
        __builtins__['_'] = lambda s: s
        self.mox = mox.Mox()

    def tearDown(self):
        self.mox.UnsetStubs()
        self.mox.VerifyAll()
