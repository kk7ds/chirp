import unittest
from unittest import mock

from chirp.wxui import serialtrace


class TestSerialTrace(unittest.TestCase):
    @mock.patch('serial.Serial.open')
    def test_open(self, mock_open):
        trace = serialtrace.SerialTrace()
        self.assertIsNone(trace._SerialTrace__tracef)
        trace.open()
        self.assertIsNotNone(trace._SerialTrace__tracef)
        self.assertTrue(trace._SerialTrace__tracef.name.endswith('.txt'))
        mock_open.assert_called_once()

    @mock.patch('os.remove')
    def test_purge_trace_files(self, mock_remove):
        from chirp.wxui import serialtrace

        for i in range(15):
            serialtrace.TRACEFILES.append('test_trace_%i.txt' % i)
        files = serialtrace.TRACEFILES[:]

        # Purge to 10 files keeps the last 10
        serialtrace.purge_trace_files(10)
        self.assertEqual(len(serialtrace.TRACEFILES), 10)
        self.assertEqual(['test_trace_%i.txt' % (i + 5) for i in range(10)],
                         serialtrace.TRACEFILES)

        # Purge to 20 does not change anything since only 10 stored
        serialtrace.purge_trace_files(20)
        self.assertEqual(10, len(serialtrace.TRACEFILES))

        # Purge to zero removes all files
        serialtrace.purge_trace_files(0)
        self.assertEqual(0, len(serialtrace.TRACEFILES))

        # Make sure we ended up removing all the files
        mock_remove.assert_has_calls([mock.call(fn) for fn in files],
                                     any_order=True)

    @mock.patch('serial.Serial.open')
    @mock.patch('serial.Serial.write')
    @mock.patch('serial.Serial.read')
    def test_log_write(self, mock_read, mock_write, mock_open):
        mock_read.side_effect = [b'123', b'']
        trace = serialtrace.SerialTrace()
        trace.open()
        fn = serialtrace.TRACEFILES[-1]
        trace.write(b'foo')
        trace.read(3)
        trace.read(5)
        trace.close()
        with open(fn, 'r') as f:
            content = f.read()
        self.assertIn('# Serial trace', content)
        self.assertIn('foo...', content)
        self.assertIn('R # timeout', content)

    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('serial.Serial.open')
    @mock.patch('serial.Serial.write')
    @mock.patch('serial.Serial.read')
    def test_log_write_fail(self, mock_read, mock_write, mock_open, mock_tf):
        mock_tf.return_value.writelines.side_effect = [
            None, Exception("Write error")]
        trace = serialtrace.SerialTrace()
        trace.open()
        # This should generate a write failure
        trace.read(3)

        # Make sure we don't interrupt further communication
        trace.write(b'foo')
        trace.read()
        trace.write(b'bar')

        # Before we are closed, the trace file should have been abandoned
        self.assertIsNone(trace._SerialTrace__tracef)
