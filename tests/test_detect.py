from chirp import directory
from tests import base


class TestCaseDetect(base.DriverTest):
    def test_detect(self):
        radio = directory.get_radio_by_image(self.TEST_IMAGE)
        if isinstance(self.radio, radio.__class__):
            # If we are a sub-device of the detected class then that's fine.
            # There's no good way for us to know that other than checking, so
            # the below assertion is just for show.
            self.assertIsInstance(self.radio, radio.__class__)
        else:
            self.assertIsInstance(radio, self.RADIO_CLASS,
                                  "Image %s detected as %s but expected %s" % (
                                      self.TEST_IMAGE,
                                      radio._orig_rclass, self.RADIO_CLASS))
