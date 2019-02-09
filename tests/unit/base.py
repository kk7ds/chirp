import sys
import unittest

import mock

try:
    import mox
except ImportError:
    from mox3 import mox

import warnings
warnings.simplefilter('ignore', Warning)


class BaseTest(unittest.TestCase):
    def setUp(self):
        __builtins__['_'] = lambda s: s
        self.mox = mox.Mox()

    def tearDown(self):
        self.mox.UnsetStubs()
        self.mox.VerifyAll()


pygtk_mocks = ('gtk', 'pango', 'gobject')
pygtk_base_classes = ('gobject.GObject', 'gtk.HBox', 'gtk.Dialog')


class DummyBase(object):
    def __init__(self, *a, **k):
        # gtk.Dialog
        self.vbox = mock.MagicMock()

    # gtk.Dialog
    def set_position(self, pos):
        pass


def mock_gtk():
    for module in pygtk_mocks:
        sys.modules[module] = mock.MagicMock()

    for path in pygtk_base_classes:
        module, base_class = path.split('.')
        setattr(sys.modules[module], base_class, DummyBase)


def unmock_gtk():
    for module in pygtk_mocks:
        del sys.modules[module]
