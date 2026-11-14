import unittest
from unittest import mock

from chirp.cli import main as climain


class _Radio(object):
    BAUD_RATE = 9600

    def __init__(self, pipe):
        self.pipe = pipe

    def get_settings(self):
        return 'ok'


class TestChirpcWriteTimeout(unittest.TestCase):
    def test_device_port_sets_write_timeout(self):
        serial_obj = mock.Mock()
        with mock.patch('sys.argv', ['chirpc', '-s', '/dev/ttyTEST']), \
                mock.patch('chirp.cli.main.directory.get_radio',
                           return_value=_Radio), \
                mock.patch('chirp.cli.main.serialtrace.SerialTrace',
                           return_value=serial_obj) as ser, \
                mock.patch('builtins.print'):
            with self.assertRaises(SystemExit) as cm:
                climain.main(['-r', 'Dummy', '-s', '/dev/ttyTEST',
                              '--list-settings'])
        self.assertEqual(cm.exception.code, 0)
        ser.assert_called_once_with(port='/dev/ttyTEST', timeout=0.5,
                                    write_timeout=2)

    def test_url_port_sets_write_timeout_before_open(self):
        events = []

        class UrlPipe(object):
            def __init__(self):
                self.timeout = None
                self.write_timeout = None

            def open(self):
                events.append((self.write_timeout, self.timeout))

        pipe = UrlPipe()
        with mock.patch('sys.argv', ['chirpc', '-s', 'loop://']), \
                mock.patch('chirp.cli.main.directory.get_radio',
                           return_value=_Radio), \
                mock.patch('chirp.cli.main.serial.serial_for_url',
                           return_value=pipe) as for_url, \
                mock.patch('chirp.cli.main.serialtrace.SerialTrace') as ser, \
                mock.patch('builtins.print'):
            with self.assertRaises(SystemExit) as cm:
                climain.main(['-r', 'Dummy', '-s', 'loop://',
                              '--list-settings'])
        self.assertEqual(cm.exception.code, 0)
        for_url.assert_called_once_with('loop://', do_not_open=True)
        ser.assert_not_called()
        self.assertEqual(events, [(2, 0.5)])
        self.assertEqual(pipe.write_timeout, 2)
        self.assertEqual(pipe.timeout, 0.5)

    def test_loop_url_really_opens_with_write_timeout(self):
        # pyserial's in-process loop:// handler, not a radio port.
        seen = []

        class Recording(_Radio):
            def __init__(self, pipe):
                super().__init__(pipe)
                seen.append(pipe)

        with mock.patch('sys.argv', ['chirpc', '-s', 'loop://']), \
                mock.patch('chirp.cli.main.directory.get_radio',
                           return_value=Recording), \
                mock.patch('builtins.print'):
            with self.assertRaises(SystemExit) as cm:
                climain.main(['-r', 'Dummy', '-s', 'loop://',
                              '--list-settings'])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(len(seen), 1)
        pipe = seen[0]
        try:
            self.assertTrue(pipe.is_open)
            self.assertEqual(pipe.write_timeout, 2)
            self.assertEqual(pipe.timeout, 0.5)
        finally:
            pipe.close()
