import logging
import random
import time
from unittest import mock

from chirp import chirp_common
from chirp import errors
from chirp.wxui import serialtrace
from tests import base

LOG = logging.getLogger(__name__)


class SerialException(Exception):
    pass


class SerialNone(serialtrace.SerialTrace):
    def flush(self):
        pass

    def inWaiting(self):
        return len(self.read(256))

    def read(self, size=None):
        return b""

    def write(self, data):
        if not isinstance(data, bytes):
            raise TypeError('Radio wrote non-bytes to serial')

    def setBaudrate(self, rate):
        pass

    def setTimeout(self, timeout):
        pass

    def setParity(self, parity):
        pass

    def __str__(self):
        return self.__class__.__name__.replace("Serial", "")


class SerialError(SerialNone):
    def read(self, size=None):
        raise SerialException("Foo")

    def write(self, data):
        raise SerialException("Bar")


class SerialGarbage(SerialNone):
    def read(self, size=None):
        if size is None:
            size = random.randint(0, 128)
        buf = []
        for i in range(0, size):
            buf.append(i % 256)
        return bytes(buf)


class SerialShortGarbage(SerialNone):
    def read(self, size=None):
        if size is None:
            size = random.randint(0, 128)
        return b'\x01' * (size - 1)


class TestCaseClone(base.DriverTest):
    def setUp(self):
        super().setUp()
        self.live = isinstance(self.radio, chirp_common.LiveRadio)
        self.clone = isinstance(self.radio, chirp_common.CloneModeRadio)

        if not self.clone and not self.live:
            self.skipTest('Does not support clone')

        real_time = time.time

        def fake_time():
            return real_time() * 1000

        self.patches = []
        self.use_patch(mock.patch('time.sleep'))
        self.use_patch(mock.patch('time.time',
                                  side_effect=fake_time))

    def _test_with_serial(self, serial):
        # The base case sets us up with a file, so re-init with our serial.
        # The radio must not read (or fail) with unexpected/error serial
        # behavior on init.
        LOG.info('Initializing radio with fake serial; Radio should not fail')
        orig_mmap = self.parent._mmap

        try:
            cls = self.RADIO_CLASS.detect_from_serial(serial)
            if cls and cls != self.RADIO_CLASS:
                self.fail('Radio detection did not return self')
        except NotImplementedError:
            pass
        except errors.RadioError:
            pass
        except SerialException:
            pass

        self.radio = self.RADIO_CLASS(serial)
        self.radio._mmap = orig_mmap
        self.radio.status_fn = lambda s: True

        msg = ('Clone in should have failed and raised an exception '
               'that inherits from RadioError')
        with self.assertRaises(errors.RadioError, msg=msg):
            self.radio.sync_in()

        msg = ('Clone out should have failed and raised an exception '
               'that inherits from RadioError')
        with self.assertRaises(errors.RadioError, msg=msg):
            self.radio.sync_out()

    def test_clone_serial_error(self):
        self._test_with_serial(SerialError())

    def test_clone_serial_none(self):
        self._test_with_serial(SerialNone())

    def test_clone_serial_garbage(self):
        self._test_with_serial(SerialGarbage())

    def test_clone_serial_short_garbage(self):
        self._test_with_serial(SerialShortGarbage())
