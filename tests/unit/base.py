import builtins
import os
import unittest
import warnings

from chirp import directory
from tests.base import RadioTestFixture

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


class RadioTest(BaseTest):
    """Base for unit tests that exercise one radio's saved test image."""

    VENDOR_MODEL = None

    def setUp(self):
        super().setUp()
        cls = type(self)

        if '_radio_test_fixture' not in cls.__dict__:
            model = cls.VENDOR_MODEL
            if model is None:
                raise NotImplementedError(
                    '%s must set VENDOR_MODEL' % cls.__name__)
            image = os.path.abspath(os.path.join(
                os.path.dirname(__file__), '..', 'images', model + '.img'))
            radio_class = directory.get_radio(model)
            fixture = RadioTestFixture(radio_class(image))
            cls._radio_test_image = image
            cls._radio_test_class = radio_class
            cls._radio_test_fixture = fixture if fixture.cacheable else None

        fixture = cls._radio_test_fixture
        if fixture is None:
            self.parent = cls._radio_test_class(cls._radio_test_image)
            self.parent_rf = self.parent.get_features()
            self.radio = self.parent
            self.rf = self.parent_rf
        else:
            fixture.restore()
            self.parent = fixture.parent
            self.parent_rf = fixture.parent_rf
            self.radio = fixture.radio
            self.rf = fixture.rf

    @classmethod
    def tearDownClass(cls):
        for name in ('_radio_test_fixture', '_radio_test_image',
                     '_radio_test_class'):
            if name in cls.__dict__:
                delattr(cls, name)
        super().tearDownClass()
