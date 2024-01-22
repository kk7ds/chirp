import logging
import sys
from unittest import mock

import pytest

from chirp import directory
from chirp import logger
from tests import base


class TestCaseDetect(base.DriverTest):
    def test_detect(self):
        with logger.log_history(logging.WARNING, 'chirp.drivers') as history:
            radio = directory.get_radio_by_image(self.TEST_IMAGE)
            self.assertEqual([], history.get_history(),
                             'Drivers should not log warnings/errors for '
                             'good images')
        if hasattr(radio, '_orig_rclass'):
            radio = radio._orig_rclass(self.TEST_IMAGE)
        if isinstance(self.radio, radio.__class__):
            # If we are a sub-device of the detected class then that's fine.
            # There's no good way for us to know that other than checking, so
            # the below assertion is just for show.
            self.assertIsInstance(self.radio, radio.__class__)
        else:
            self.assertIsInstance(radio, self.RADIO_CLASS,
                                  "Image %s detected as %s but expected %s" % (
                                      self.TEST_IMAGE,
                                      radio.__class__, self.RADIO_CLASS))

    @pytest.mark.skipif(sys.version_info < (3, 10),
                        reason="requires python3.10 or higher")
    @mock.patch('builtins.print')
    def test_match_model_is_quiet_no_match(self, mock_print):
        with self.assertNoLogs(level=logging.DEBUG):
            self.radio.match_model(b'', 'foo.img')
        mock_print.assert_not_called()

    @pytest.mark.skipif(sys.version_info < (3, 10),
                        reason="requires python3.10 or higher")
    @mock.patch('builtins.print')
    def test_match_model_is_quiet_with_match(self, mock_print):
        with self.assertNoLogs(level=logging.DEBUG):
            with open(self.TEST_IMAGE, 'rb') as f:
                self.radio.match_model(f.read(), self.TEST_IMAGE)
        mock_print.assert_not_called()
