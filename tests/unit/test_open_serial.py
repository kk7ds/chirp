import sys
import unittest
from unittest import mock

# clone.py imports wx at module level. Stub it the same way as
# test_wxui_radiothread so this test does not need wxPython installed.
sys.modules['wx'] = wx = mock.MagicMock()
sys.modules['wx.lib'] = mock.MagicMock()
sys.modules['wx.lib.scrolledpanel'] = mock.MagicMock()
sys.modules['wx.lib.sized_controls'] = mock.MagicMock()
sys.modules['wx.richtext'] = mock.MagicMock()
wx.lib.newevent.NewCommandEvent.return_value = None, None
sys.modules['chirp.wxui.developer'] = mock.MagicMock()

from chirp.drivers import fake  # noqa: E402
from chirp.wxui import clone  # noqa: E402
from chirp import serialtrace  # noqa: E402


class _Radio(object):
    BAUD_RATE = 19200
    HARDWARE_FLOW = True
    WANTS_RTS = False
    WANTS_DTR = True


class TestOpenSerialWriteTimeout(unittest.TestCase):
    def test_url_port_sets_write_timeout_before_open(self):
        events = []

        class UrlPipe(object):
            def __init__(self):
                self.timeout = None
                self.write_timeout = None
                self.rtscts = None
                self.rts = None
                self.dtr = None
                self.baudrate = None

            def open(self):
                events.append((self.write_timeout, self.timeout,
                               self.baudrate))

        pipe = UrlPipe()
        with mock.patch('serial.serial_for_url', return_value=pipe) as for_url:
            opened = clone.open_serial('loop://', _Radio)
        for_url.assert_called_once_with('loop://', do_not_open=True)
        self.assertIs(opened, pipe)
        # Bound is in place before open(); baud is still applied after.
        self.assertEqual(events, [(2, 0.25, None)])
        self.assertEqual(pipe.write_timeout, 2)
        self.assertEqual(pipe.timeout, 0.25)
        self.assertEqual(pipe.baudrate, 19200)
        self.assertIs(pipe.rtscts, True)
        self.assertIs(pipe.rts, False)
        self.assertIs(pipe.dtr, True)

    def test_loop_url_really_opens_with_write_timeout(self):
        # pyserial's in-process loop:// handler, not a radio port.
        pipe = clone.open_serial('loop://', _Radio)
        try:
            self.assertTrue(pipe.is_open)
            self.assertEqual(pipe.write_timeout, 2)
            self.assertEqual(pipe.timeout, 0.25)
            self.assertEqual(pipe.baudrate, 19200)
            self.assertIs(pipe.rtscts, True)
            pipe.write(b'abc')
            self.assertEqual(pipe.read(3), b'abc')
        finally:
            pipe.close()

    def test_device_port_passes_write_timeout_to_serialtrace(self):
        seen = {}

        def fake_open(self):
            seen['write_timeout'] = self.write_timeout
            seen['timeout'] = self.timeout
            seen['port'] = self.port
            seen['baudrate'] = self.baudrate
            seen['rtscts'] = self.rtscts
            seen['rts'] = self.rts
            seen['dtr'] = self.dtr

        with mock.patch('chirp.serialtrace.SerialTrace.open', fake_open):
            pipe = clone.open_serial('/dev/ttyTEST', _Radio)
        self.assertIsInstance(pipe, serialtrace.SerialTrace)
        self.assertEqual(seen['write_timeout'], 2)
        self.assertEqual(seen['timeout'], 0.25)
        self.assertEqual(seen['port'], '/dev/ttyTEST')
        self.assertEqual(seen['baudrate'], 19200)
        self.assertIs(seen['rtscts'], True)
        self.assertIs(seen['rts'], False)
        self.assertIs(seen['dtr'], True)
        # Constructor default stays None so existing SerialTrace doubles,
        # which never go through open_serial, keep blocking writes.
        direct = serialtrace.SerialTrace()
        self.assertIsNone(direct.write_timeout)

    def test_duck_typed_fake_is_not_given_write_timeout(self):
        pipe = clone.open_serial('Fake F7E', _Radio)
        self.assertIsInstance(pipe, fake.FakeKenwoodSerial)
        self.assertFalse(hasattr(pipe, 'write_timeout'))
        self.assertFalse(hasattr(pipe, 'timeout'))
