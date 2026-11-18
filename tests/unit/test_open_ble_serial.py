import io
import importlib.util
import signal
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

wx = mock.MagicMock()
wx.lib.newevent.NewCommandEvent.return_value = None, None
wx.Dialog = type('Dialog', (), {})
wx.GetTranslation.side_effect = lambda text: text
modules = {
    'wx': wx,
    'wx.lib': mock.MagicMock(),
    'wx.lib.scrolledpanel': mock.MagicMock(),
    'wx.lib.sized_controls': mock.MagicMock(),
    'wx.richtext': mock.MagicMock(),
    'chirp.wxui.developer': mock.MagicMock(),
}
with mock.patch.dict(sys.modules, modules):
    import chirp

    chirp_path = Path(__file__).resolve().parents[2] / 'chirp'
    ble_spec = importlib.util.spec_from_file_location(
        'chirp._ble_serial_test', chirp_path / 'ble_serial.py')
    ble = importlib.util.module_from_spec(ble_spec)
    ble_spec.loader.exec_module(ble)
    with mock.patch.object(chirp, 'ble_serial', ble, create=True):
        spec = importlib.util.spec_from_file_location(
            'chirp.wxui._clone_ble_test', chirp_path / 'wxui' / 'clone.py')
        clone = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(clone)

from chirp import chirp_common, errors, platform  # noqa: E402
from chirp.drivers import baofeng_uv17Pro  # noqa: E402


class _Radio(object):
    BAUD_RATE = 19200
    HARDWARE_FLOW = True
    WANTS_RTS = False
    WANTS_DTR = True


class TestBleSerial(unittest.TestCase):
    def test_parse_ble_scan_output(self):
        output = (
            'Started BLE scan\n'
            '20:91:48:4C:4C:54 (rssi=-56): UV Radio\n'
            '55AEB150-5AF1-4318-A02E-19A46223F572 (RSSI=-70):\n'
            'Finished BLE scan\n')
        self.assertEqual(ble.parse_ble_scan_output(output), [
            ('20:91:48:4C:4C:54', 'UV Radio'),
            ('55AEB150-5AF1-4318-A02E-19A46223F572', ''),
        ])

    def test_scanned_device_labels_and_selected_address(self):
        dialog = mock.Mock()
        dialog._alive = True
        dialog._scan_id = 1
        dialog.get_selected_device.return_value = None
        dialog._selected = 'address-2'
        devices = [('address-1', 'Radio'), ('address-2', ''),
                   ('address-3', 'None')]

        ble.BluetoothDeviceDialog._scan_complete(dialog, 1, devices, None)
        dialog._device.SetItems.assert_called_once_with([
            'address-1: Radio', 'address-2: None', 'address-3: None'])
        dialog._device.SetSelection.assert_called_once_with(1)

    def test_ble_device_prefers_name_and_falls_back_to_address(self):
        address = '20:91:48:4C:4C:54'
        self.assertEqual(
            ble.device(address, 'walkie-talkie'),
            'BLE: walkie-talkie')
        self.assertEqual(
            ble.device(address, 'None'),
            'BLE: {}'.format(address))

    def test_start_ble_serial_uses_selected_device(self):
        connection = ble.BluetoothConnection(
            '20:91:48:4C:4C:54', _Radio, clone.open_serial, mock.Mock())
        process = mock.Mock()
        process.poll.return_value = None
        process.stdout = io.StringIO(
            'INFO | linux_pty.py: Port endpoint created on '
            '/tmp/ttyBLE -> /dev/ttys012\n'
            'INFO | main.py: Running main loop!\n')
        with mock.patch.object(ble.subprocess, 'Popen',
                               return_value=process) as popen, \
                mock.patch.object(ble.os.path, 'exists',
                                  return_value=True) as exists, \
                mock.patch.object(ble.time, 'monotonic', return_value=0):
            self.assertEqual(connection._start_process(), '/tmp/ttyBLE')
        exists.assert_called_once_with('/tmp/ttyBLE')
        popen.assert_called_once_with(
            [sys.executable, '-m', 'ble_serial', '-d',
             '20:91:48:4C:4C:54'],
            stdout=ble.subprocess.PIPE,
            stderr=ble.subprocess.STDOUT,
            text=True, bufsize=1)

    def test_bluetooth_connection_runs_in_background(self):
        pipe = mock.Mock()
        dialog = mock.Mock()
        dialog._ble_device_address = 'address'
        dialog._ble_connection = None
        dialog._ble_connection_complete.side_effect = (
            lambda *args: clone.ChirpCloneDialog._ble_connection_complete(
                dialog, *args))
        continuation = mock.Mock()
        started = threading.Event()
        release = threading.Event()
        scheduled = threading.Event()
        callbacks = []

        def open_ble(*args, **kwargs):
            started.set()
            if not release.wait(2):
                raise TimeoutError('test did not release BLE connection')
            return pipe

        def call_after(*args):
            callbacks.append(args)
            scheduled.set()

        with mock.patch.object(ble.BluetoothConnection, '_open_port',
                               side_effect=open_ble), \
                mock.patch.object(wx, 'CallAfter', side_effect=call_after):
            try:
                clone.ChirpCloneDialog._open_selected_port(
                    dialog, clone.BLUETOOTH, _Radio, continuation)
                self.assertTrue(started.wait(1))
                continuation.assert_not_called()
                release.set()
                self.assertTrue(scheduled.wait(2))
                callback, *args = callbacks[0]
                callback(*args)
            finally:
                release.set()

        continuation.assert_called_once_with(pipe)
        dialog._start_ble_activity.assert_called_once()
        dialog._stop_ble_activity.assert_called_once()

    def test_bluetooth_selection_requires_device(self):
        connection = ble.BluetoothConnection(
            None, _Radio, clone.open_serial, mock.Mock())
        with mock.patch.object(connection, '_start_process') as start, \
                self.assertRaisesRegex(RuntimeError, 'Select a Bluetooth'):
            connection._open_port()
        start.assert_not_called()

    def test_ble_port_opens_with_managed_serial_trace(self):
        process = mock.Mock()
        pipe = mock.Mock()
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        connection._process = process
        with mock.patch.object(connection, '_start_process',
                               return_value='/tmp/ttyBLE'), \
                mock.patch.object(ble.serialtrace, 'SerialTrace',
                                  return_value=pipe) as factory:
            result = connection._open_port()

        self.assertIs(result, pipe)
        factory.assert_called_once_with(
            on_close=connection.stop, is_ble=True, baudrate=_Radio.BAUD_RATE,
            rtscts=_Radio.HARDWARE_FLOW, timeout=0.25, write_timeout=2)
        self.assertEqual(pipe.port, '/tmp/ttyBLE')
        pipe.open.assert_called_once_with()

    def test_non_bluetooth_selection_opens_serial_port(self):
        dialog = mock.Mock()
        continuation = mock.Mock()
        with mock.patch.object(clone, 'open_serial') as open_serial, \
                mock.patch.object(ble, 'BluetoothConnection') as open_ble:
            clone.ChirpCloneDialog._open_selected_port(
                dialog, '/dev/ttyUSB0', _Radio, continuation)
        continuation.assert_called_once_with(open_serial.return_value)
        open_serial.assert_called_once_with('/dev/ttyUSB0', _Radio)
        open_ble.assert_not_called()
        dialog._start_ble_activity.assert_not_called()

    def test_ble_port_open_failure_stops_process(self):
        process = mock.Mock()
        pipe = mock.Mock()
        pipe.open.side_effect = OSError('port unavailable')
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        connection._process = process
        with mock.patch.object(connection, '_start_process',
                               return_value='/tmp/ttyBLE'), \
                mock.patch.object(connection, 'stop') as stop, \
                mock.patch.object(clone.serialtrace, 'SerialTrace',
                                  return_value=pipe), \
                self.assertRaisesRegex(OSError, 'port unavailable'):
            connection._open_port()
        stop.assert_called_once_with()

    def test_missing_ble_serial_port_fails_and_stops_process(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.stdout = io.StringIO('Running main loop!\n')
        connection = ble.BluetoothConnection(
            'device', _Radio, clone.open_serial, mock.Mock())
        with mock.patch.object(ble.subprocess, 'Popen',
                               return_value=process), \
                mock.patch.object(connection, 'stop') as stop, \
                self.assertRaisesRegex(RuntimeError, 'did not report'):
            connection._start_process()
        stop.assert_called_once_with()

    def test_cancelled_start_stops_ble_process(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.stdout = io.StringIO('')
        connection = ble.BluetoothConnection(
            'device', _Radio, clone.open_serial, mock.Mock())

        def start_process(*args, **kwargs):
            connection._cancelled.set()
            return process

        with mock.patch.object(ble.subprocess, 'Popen',
                               side_effect=start_process), \
                mock.patch.object(connection, 'stop') as stop, \
                self.assertRaises(InterruptedError):
            connection._start_process()
        stop.assert_called_once_with()

    def test_cancelled_connection_does_not_start_process(self):
        connection = ble.BluetoothConnection(
            'device', _Radio, clone.open_serial, mock.Mock())
        connection.cancel()
        with mock.patch.object(ble.subprocess, 'Popen') as popen, \
                self.assertRaises(InterruptedError):
            connection._start_process()
        popen.assert_not_called()

    def test_cancel_before_connection_callback_closes_pipe(self):
        dialog = mock.Mock()
        continuation = mock.Mock()
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, continuation)
        pipe = mock.Mock()
        connection._pipe = pipe
        dialog._ble_connection = connection

        clone.ChirpCloneDialog._cancel_ble_connection(dialog)
        connection._deliver(None)

        pipe.close.assert_called_once_with()
        continuation.assert_not_called()
        dialog._stop_ble_activity.assert_not_called()

    def test_cancel_during_connection_closes_late_pipe(self):
        dialog = mock.Mock()
        dialog._ble_device_address = 'address'
        dialog._ble_connection = None
        pipe = mock.Mock()
        started = threading.Event()
        release = threading.Event()
        closed = threading.Event()
        pipe.close.side_effect = closed.set

        def open_ble(*args, **kwargs):
            started.set()
            if not release.wait(2):
                raise TimeoutError('test did not release BLE connection')
            return pipe

        with mock.patch.object(ble.BluetoothConnection, '_open_port',
                               side_effect=open_ble), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            try:
                clone.ChirpCloneDialog._open_selected_port(
                    dialog, clone.BLUETOOTH, _Radio, mock.Mock())
                self.assertTrue(started.wait(1))
                clone.ChirpCloneDialog._cancel_ble_connection(dialog)
                release.set()
                self.assertTrue(closed.wait(2))
                call_after.assert_not_called()
            finally:
                release.set()

    def test_connection_error_stops_activity_and_reports_failure(self):
        dialog = mock.Mock()
        dialog._ble_connection = mock.Mock()
        continuation = mock.Mock()

        clone.ChirpCloneDialog._ble_connection_complete(
            dialog, continuation, None, 'failed')

        dialog._stop_ble_activity.assert_called_once_with()
        dialog.fail.assert_called_once_with('failed')
        continuation.assert_not_called()

    def test_bluetooth_failure_is_shown_in_dialog_without_popup(self):
        dialog = mock.Mock(spec=clone.ChirpDownloadDialog)
        dialog.status_msg = mock.Mock()
        dialog._ble_error_button = mock.Mock()
        dialog._ble_error_panel = mock.Mock()
        dialog.Fit = mock.Mock()
        dialog.Layout = mock.Mock()
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        error = 'Connection timed out. Check the radio.\nTechnical details'
        with mock.patch.object(wx, 'CallAfter',
                               side_effect=lambda callback: callback()), \
                mock.patch.object(clone.common.error_proof,
                                  'show_error') as show_error:
            clone.ChirpCloneDialog.fail(dialog, error)

        dialog.status_msg.Hide.assert_called_once_with()
        self.assertEqual(dialog._ble_error, error)
        dialog._ble_error_button.Show.assert_called_once_with(True)
        dialog._ble_error_panel.Show.assert_called_once_with()
        dialog.Fit.assert_called_once_with()
        dialog.Layout.assert_called_once_with()
        dialog.enable_model_select.assert_called_once_with()
        dialog.enable_running.assert_called_once_with()
        show_error.assert_not_called()

    def test_empty_bluetooth_error_hides_information_button(self):
        dialog = mock.Mock()
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        with mock.patch.object(wx, 'CallAfter',
                               side_effect=lambda callback: callback()):
            clone.ChirpCloneDialog.fail(dialog, '')
        dialog.status_msg.Hide.assert_called_once_with()
        dialog._ble_error_panel.Show.assert_called_once_with()
        dialog._ble_error_button.Show.assert_called_once_with(False)

    def test_bluetooth_error_button_shows_full_error(self):
        dialog = mock.Mock()
        error = errors.RadioError('Connection failed. Details\nMore details')
        dialog._ble_error = error
        with mock.patch.object(clone.common.error_proof,
                               'show_error') as show_error:
            clone.ChirpCloneDialog._show_ble_error(dialog, None)
        show_error.assert_called_once_with(
            error, parent=dialog, title='Error communicating with radio')

    def test_bluetooth_retry_replaces_error_with_connection_progress(self):
        dialog = mock.Mock()
        clone.ChirpCloneDialog._start_ble_activity(
            dialog, 'Connecting to Bluetooth radio...')
        dialog._clear_ble_error.assert_called_once_with()
        dialog.status_msg.SetLabel.assert_called_once_with(
            'Connecting to Bluetooth radio...')
        dialog._ble_activity_timer.Start.assert_called_once_with(100)

    def test_clearing_bluetooth_error_hides_details(self):
        dialog = mock.Mock()
        dialog._ble_error = 'Old error'
        dialog._ble_error_panel.IsShown.return_value = True
        clone.ChirpCloneDialog._clear_ble_error(dialog)
        dialog.status_msg.SetLabel.assert_called_once_with('')
        self.assertIsNone(dialog._ble_error)
        dialog._ble_error_panel.Hide.assert_called_once_with()
        dialog.status_msg.Show.assert_called_once_with()
        dialog.Fit.assert_called_once_with()
        dialog.Layout.assert_called_once_with()

    def test_non_bluetooth_failure_still_opens_error_popup(self):
        dialog = mock.Mock()
        dialog.get_selected_port.return_value = '/dev/ttyUSB0'
        with mock.patch.object(wx, 'CallAfter',
                               side_effect=lambda callback: callback()), \
                mock.patch.object(clone.common.error_proof,
                                  'show_error') as show_error:
            clone.ChirpCloneDialog.fail(dialog, 'Serial port failed')
        show_error.assert_called_once()
        dialog.enable_running.assert_called_once_with()

    def test_bluetooth_connection_timeout_stops_process_and_reports_error(
            self):
        process = mock.Mock()
        process.poll.return_value = None
        process.stdout = io.StringIO('')
        on_complete = mock.Mock()
        connection = ble.BluetoothConnection(
            'device', _Radio, clone.open_serial, on_complete)
        with mock.patch.object(ble.subprocess, 'Popen',
                               return_value=process), \
                mock.patch.object(ble.time, 'monotonic',
                                  side_effect=[0, 31]), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            connection._connect()
            callback, *args = call_after.call_args.args
            callback(*args)

        pipe, error = on_complete.call_args.args
        self.assertIsNone(pipe)
        self.assertIn('Timed out waiting for ble-serial to connect', error)
        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.wait.assert_called_once_with(timeout=3)
        self.assertIsNone(connection._process)

    def test_non_radio_ble_process_failure_is_reported(self):
        process = mock.Mock()
        process.poll.return_value = 0
        process.returncode = 0
        process.stdout = io.StringIO(
            'AssertionError: No characteristic in builtin write list found!\n')
        dialog = mock.Mock()
        continuation = mock.Mock()
        dialog._ble_connection_complete.side_effect = (
            lambda *args: clone.ChirpCloneDialog._ble_connection_complete(
                dialog, *args))
        connection = ble.BluetoothConnection(
            'non-radio', _Radio, clone.open_serial,
            lambda pipe, error: dialog._ble_connection_complete(
                continuation, pipe, error))
        with mock.patch.object(ble.subprocess, 'Popen',
                               return_value=process), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            connection._connect()
            callback, *args = call_after.call_args.args
            callback(*args)

        self.assertIn('status 0', dialog.fail.call_args.args[0])
        self.assertIn('No characteristic in builtin write list found',
                      dialog.fail.call_args.args[0])
        self.assertIsNone(connection._process)
        dialog._stop_ble_activity.assert_called_once_with()
        continuation.assert_not_called()

    def test_non_radio_silent_serial_reports_no_response_and_stops_ble(self):
        process = mock.Mock()
        process.poll.return_value = None
        connection = ble.BluetoothConnection(
            'non-radio', _Radio, clone.open_serial, mock.Mock())
        connection._process = process
        pipe = clone.serialtrace.SerialTrace(
            on_close=connection.stop, is_ble=True)
        pipe.port = '/tmp/other-ble-port'
        radio = baofeng_uv17Pro.UV5RMini(pipe)
        dialog = mock.Mock()
        thread = clone.CloneThread(radio, dialog, 'sync_in')
        system = mock.Mock()
        system.is_ble_serial.side_effect = (
            lambda serial: platform.UnixPlatform.is_ble_serial(None, serial))
        with mock.patch.object(clone.serialtrace.serial.Serial, 'read',
                               return_value=b''), \
                mock.patch.object(clone.serialtrace.serial.Serial, 'write'), \
                mock.patch.object(platform, 'get_platform',
                                  return_value=system):
            thread.run()

        error = dialog.fail.call_args.args[0]
        self.assertIsInstance(error, errors.RadioNoResponse)
        self.assertEqual(str(error), 'No response from radio')
        dialog.complete.assert_not_called()
        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.wait.assert_called_once_with(timeout=3)
        self.assertIsNone(connection._process)

    def test_action_is_ignored_while_connection_is_pending(self):
        dialog = mock.Mock()
        dialog._ble_connection = mock.Mock()
        event = mock.Mock()
        event.GetEventObject.return_value.GetId.return_value = clone.wx.ID_OK

        clone.ChirpCloneDialog._action(dialog, event)

        dialog._actual_action.assert_not_called()

    def test_worker_failure_is_reported_on_ui_callback(self):
        dialog = mock.Mock()
        dialog._ble_device_address = 'address'
        dialog._ble_connection = None
        dialog._ble_connection_complete.side_effect = (
            lambda *args: clone.ChirpCloneDialog._ble_connection_complete(
                dialog, *args))
        scheduled = threading.Event()
        callbacks = []

        def call_after(*args):
            callbacks.append(args)
            scheduled.set()

        with mock.patch.object(ble.BluetoothConnection, '_open_port',
                               side_effect=OSError('connection failed')), \
                mock.patch.object(wx, 'CallAfter', side_effect=call_after):
            clone.ChirpCloneDialog._open_selected_port(
                dialog, clone.BLUETOOTH, _Radio, mock.Mock())
            self.assertTrue(scheduled.wait(2))
            callback, *args = callbacks[0]
            callback(*args)

        dialog._stop_ble_activity.assert_called_once_with()
        dialog.fail.assert_called_once_with('connection failed')

    def test_upload_prompt_order_is_preserved(self):
        for before_open in (True, False):
            with self.subTest(before_open=before_open):
                dialog = mock.Mock()
                pipe = mock.Mock()
                events = []
                callbacks = []
                prompts = mock.Mock()
                prompts.info = False
                prompts.pre_upload = True
                prompts.pre_upload_ble = 'Bluetooth upload'
                prompts.display_pre_upload_prompt_before_opening_port = (
                    before_open)
                dialog._radio.get_prompts.return_value = prompts
                dialog._radio.pipe = None
                dialog._radio.BAUD_RATE = 19200
                dialog.get_selected_port.return_value = clone.BLUETOOTH
                dialog._ble_device_address = 'selected-address'
                dialog._upload_before_serial.side_effect = (
                    lambda *args: clone.ChirpUploadDialog
                    ._upload_before_serial(dialog, *args))
                dialog._upload_with_serial.side_effect = (
                    lambda *args: events.append('upload'))

                def open_port(port, radio, continuation):
                    events.append('open')
                    callbacks.append(continuation)

                dialog._open_selected_port.side_effect = open_port
                prompt = mock.Mock()
                prompt.ShowModal.side_effect = (
                    lambda: events.append('prompt') or clone.wx.ID_OK)
                with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                                       return_value=prompt):
                    clone.ChirpUploadDialog._actual_action(dialog, mock.Mock())
                    self.assertEqual(events,
                                     ['prompt', 'open'] if before_open
                                     else ['open'])
                    callbacks[0](pipe)

                self.assertEqual(events, ['prompt', 'open', 'upload']
                                 if before_open else
                                 ['open', 'prompt', 'upload'])

    def test_unselected_bluetooth_upload_prompts_then_selects_then_opens(self):
        dialog = mock.Mock()
        radio = mock.Mock()
        radio.BAUD_RATE = 19200
        radio.pipe = None
        prompts = chirp_common.RadioPrompts()
        prompts.pre_upload_ble = 'Bluetooth upload'
        radio.get_prompts.return_value = prompts
        dialog._radio = radio
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        dialog._ble_device_address = None
        dialog._upload_before_serial.side_effect = (
            lambda *args: clone.ChirpUploadDialog
            ._upload_before_serial(dialog, *args))
        events = []
        dialog._select_ble_device.side_effect = (
            lambda: events.append('picker') or True)
        dialog._open_selected_port.side_effect = (
            lambda *args: events.append('connect'))
        prompt = mock.Mock()
        prompt.ShowModal.side_effect = (
            lambda: events.append('prompt') or clone.wx.ID_OK)
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpUploadDialog._actual_action(dialog, mock.Mock())

        self.assertEqual(events, ['prompt', 'picker', 'connect'])

    def test_unselected_bluetooth_upload_prompts_before_open_when_required(
            self):
        dialog = mock.Mock()
        prompts = chirp_common.RadioPrompts()
        prompts.pre_upload_ble = 'Bluetooth upload'
        prompts.display_pre_upload_prompt_before_opening_port = False
        dialog._radio.get_prompts.return_value = prompts
        dialog._radio.pipe = None
        dialog._ble_device_address = None
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        events = []
        dialog._upload_before_serial.side_effect = (
            lambda *args: clone.ChirpUploadDialog
            ._upload_before_serial(dialog, *args))
        dialog._select_ble_device.side_effect = (
            lambda: events.append('picker') or True)
        dialog._open_selected_port.side_effect = (
            lambda *args: events.append('connect'))
        prompt = mock.Mock()
        prompt.ShowModal.side_effect = (
            lambda: events.append('prompt') or clone.wx.ID_OK)
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpUploadDialog._actual_action(dialog, mock.Mock())
        self.assertEqual(events, ['prompt', 'picker', 'connect'])

    def test_cancelling_upload_device_picker_does_not_connect(self):
        dialog = mock.Mock()
        dialog._ble_device_address = None
        dialog._select_ble_device.return_value = False
        prompts = chirp_common.RadioPrompts()
        prompts.pre_upload_ble = 'Bluetooth upload'
        prompt = mock.Mock()
        prompt.ShowModal.return_value = clone.wx.ID_OK
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpUploadDialog._upload_before_serial(
                dialog, None, clone.BLUETOOTH, prompts)
        dialog.cancel_action.assert_called_once_with()
        dialog._open_selected_port.assert_not_called()

    def test_cancelling_upload_prompt_closes_open_pipe(self):
        dialog = mock.Mock()
        pipe = mock.Mock()
        prompts = mock.Mock()
        prompts.pre_upload = True
        prompts.pre_upload_ble = 'Bluetooth upload'
        prompt = mock.Mock()
        prompt.ShowModal.return_value = clone.wx.ID_CANCEL
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpUploadDialog._upload_before_serial(
                dialog, pipe, clone.BLUETOOTH, prompts)

        pipe.close.assert_called_once_with()
        dialog.cancel_action.assert_called_once_with()
        dialog._open_selected_port.assert_not_called()

    def test_download_prompts_precede_connection(self):
        dialog = mock.Mock()
        radio = mock.Mock()
        prompts = radio.get_prompts.return_value
        prompts.info = True
        prompts.pre_download = True
        prompts.pre_download_ble = None
        dialog.get_selected_rclass.return_value = radio
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        dialog._ble_device_address = 'selected-address'
        event = mock.Mock()
        event.GetEventObject.return_value.GetId.return_value = clone.wx.ID_OK
        order = []
        callbacks = []
        prompt = mock.Mock()
        prompt.ShowModal.side_effect = (
            lambda: order.append('prompt') or clone.wx.ID_OK)

        def open_port(port, rclass, continuation):
            order.append('open')
            callbacks.append(continuation)

        dialog._open_selected_port.side_effect = open_port

        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpDownloadDialog._actual_action(dialog, event)

        self.assertEqual(order, ['prompt', 'prompt', 'open'])
        pipe = mock.Mock()
        callbacks[0](pipe)
        dialog._download_with_serial.assert_called_once_with(pipe, radio)

    def test_driver_bluetooth_prompts_for_all_models(self):
        with mock.patch('builtins._', create=True, side_effect=lambda s: s):
            for radio in (baofeng_uv17Pro.RadioddityGM30Pro,
                          baofeng_uv17Pro.BaofengGM21,
                          baofeng_uv17Pro.UV28Plus,
                          baofeng_uv17Pro.UV5RMini,
                          baofeng_uv17Pro.RadioddityGM30Plus):
                with self.subTest(radio=radio.MODEL):
                    prompts = radio.get_prompts()
                    self.assertIn('interface cable', prompts.pre_download)
                    self.assertIn('interface cable', prompts.pre_upload)
                    self.assertIn('Enable Bluetooth', prompts.pre_download_ble)
                    self.assertIn('Enable Bluetooth', prompts.pre_upload_ble)

    def test_download_prompt_matches_selected_port_and_radio(self):
        for port, has_ble, expected in (
                (clone.BLUETOOTH, True, 'Bluetooth download'),
                ('/dev/ttyUSB0', True, 'Cable download'),
                (clone.BLUETOOTH, False, 'Cable download')):
            with self.subTest(port=port, has_ble=has_ble):
                dialog = mock.Mock()
                radio = mock.Mock()
                prompts = chirp_common.RadioPrompts()
                prompts.pre_download = 'Cable download'
                if has_ble:
                    prompts.pre_download_ble = 'Bluetooth download'
                radio.get_prompts.return_value = prompts
                dialog.get_selected_rclass.return_value = radio
                dialog.get_selected_port.return_value = port
                event = mock.Mock()
                event.GetEventObject.return_value.GetId.return_value = (
                    clone.wx.ID_OK)
                prompt = mock.Mock()
                prompt.ShowModal.return_value = clone.wx.ID_OK
                with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                                       return_value=prompt) as prompt_dialog:
                    clone.ChirpDownloadDialog._actual_action(dialog, event)

                self.assertEqual(prompt_dialog.call_args.kwargs['message'],
                                 expected)
                self.assertEqual(prompt_dialog.call_args.kwargs['prompt'],
                                 'pre_download')
                dialog._open_selected_port.assert_called_once()

    def test_cancelling_bluetooth_download_prompt_does_not_connect(self):
        dialog = mock.Mock()
        radio = mock.Mock()
        prompts = chirp_common.RadioPrompts()
        prompts.pre_download_ble = 'Bluetooth download'
        radio.get_prompts.return_value = prompts
        dialog.get_selected_rclass.return_value = radio
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        event = mock.Mock()
        event.GetEventObject.return_value.GetId.return_value = clone.wx.ID_OK
        prompt = mock.Mock()
        prompt.ShowModal.return_value = clone.wx.ID_CANCEL
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpDownloadDialog._actual_action(dialog, event)
        dialog.cancel_action.assert_called_once_with()
        dialog._select_ble_device.assert_not_called()
        dialog._open_selected_port.assert_not_called()

    def test_cancelled_bluetooth_device_selection_does_not_connect(self):
        dialog = mock.Mock()
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        dialog._ble_device_address = None
        dialog._radio = mock.Mock()
        prompts = chirp_common.RadioPrompts()
        prompts.pre_download_ble = 'Bluetooth download'
        dialog._radio.get_prompts.return_value = prompts
        dialog._select_ble_device.return_value = False
        event = mock.Mock()
        event.GetEventObject.return_value.GetId.return_value = clone.wx.ID_OK
        prompt = mock.Mock()
        prompt.ShowModal.return_value = clone.wx.ID_OK
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpDownloadDialog._actual_action(dialog, event)
        dialog._select_ble_device.assert_called_once_with()
        dialog._open_selected_port.assert_not_called()
        dialog.cancel_action.assert_called_once_with()

    def test_pre_download_prompt_follows_device_selection_on_ok(self):
        dialog = mock.Mock()
        radio = mock.Mock()
        prompts = chirp_common.RadioPrompts()
        prompts.pre_download_ble = 'Bluetooth download'
        radio.get_prompts.return_value = prompts
        dialog.get_selected_rclass.return_value = radio
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        dialog._ble_device_address = 'device-address'
        events = []
        dialog._open_selected_port.side_effect = (
            lambda *args: events.append('open'))
        event = mock.Mock()
        event.GetEventObject.return_value.GetId.return_value = clone.wx.ID_OK
        prompt = mock.Mock()
        prompt.ShowModal.side_effect = (
            lambda: events.append('prompt') or clone.wx.ID_OK)
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpDownloadDialog._actual_action(dialog, event)
        self.assertEqual(events, ['prompt', 'open'])

    def test_pre_download_prompt_then_picker_then_connection_when_unselected(
            self):
        dialog = mock.Mock()
        radio = mock.Mock()
        prompts = chirp_common.RadioPrompts()
        prompts.pre_download_ble = 'Bluetooth download'
        radio.get_prompts.return_value = prompts
        dialog.get_selected_rclass.return_value = radio
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        dialog._ble_device_address = None
        events = []
        dialog._select_ble_device.side_effect = (
            lambda: events.append('picker') or True)
        dialog._open_selected_port.side_effect = (
            lambda *args: events.append('connect'))
        event = mock.Mock()
        event.GetEventObject.return_value.GetId.return_value = clone.wx.ID_OK
        prompt = mock.Mock()
        prompt.ShowModal.side_effect = (
            lambda: events.append('prompt') or clone.wx.ID_OK)
        with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                               return_value=prompt):
            clone.ChirpDownloadDialog._actual_action(dialog, event)
        self.assertEqual(events, ['prompt', 'picker', 'connect'])

    def test_bluetooth_prompt_preserves_instruction_lines(self):
        radio = mock.Mock()
        prompts = chirp_common.RadioPrompts()
        prompts.pre_download = 'Cable\ninstructions\n'
        radio.get_prompts.return_value = prompts
        message = 'Turn on radio\nEnable Bluetooth\n'
        text = mock.Mock()
        with mock.patch.object(clone, 'config'), \
                mock.patch.object(clone.platform, 'system',
                                  return_value='Darwin'), \
                mock.patch.object(wx, 'StaticText', return_value=text), \
                mock.patch.multiple(
                    clone.ChirpRadioPromptDialog, create=True,
                    CreateButtonSizer=mock.DEFAULT, SetSizer=mock.DEFAULT,
                    Layout=mock.DEFAULT, Fit=mock.DEFAULT,
                    Centre=mock.DEFAULT):
            dialog = clone.ChirpRadioPromptDialog(
                radio=radio, prompt='pre_download', message=message)
            self.assertEqual(dialog.message, message)
            text.SetLabelMarkup.assert_called_with(message)
            dialog = clone.ChirpRadioPromptDialog(
                radio=radio, prompt='pre_download')
            self.assertEqual(dialog.message, 'Cable instructions ')

    def test_upload_prompt_matches_selected_port_and_radio(self):
        for port, has_ble, expected in (
                (clone.BLUETOOTH, True, 'Bluetooth upload'),
                ('/dev/ttyUSB0', True, None),
                (clone.BLUETOOTH, False, None)):
            with self.subTest(port=port, has_ble=has_ble):
                dialog = mock.Mock()
                dialog._radio.pipe = None
                prompts = chirp_common.RadioPrompts()
                prompts.pre_upload = 'Cable upload'
                if has_ble:
                    prompts.pre_upload_ble = 'Bluetooth upload'
                pipe = mock.Mock()
                prompt = mock.Mock()
                prompt.ShowModal.return_value = clone.wx.ID_OK
                with mock.patch.object(clone, 'ChirpRadioPromptDialog',
                                       return_value=prompt) as prompt_dialog:
                    clone.ChirpUploadDialog._upload_before_serial(
                        dialog, pipe, port, prompts)

                self.assertEqual(prompt_dialog.call_args.kwargs['message'],
                                 expected)
                self.assertEqual(prompt_dialog.call_args.kwargs['prompt'],
                                 'pre_upload')
                dialog._upload_with_serial.assert_called_once()

    def test_ble_pipe_with_reported_path_is_detected(self):
        pipe = clone.serialtrace.SerialTrace(is_ble=True)
        pipe.port = '/tmp/other-ble-port'
        self.assertTrue(platform.UnixPlatform.is_ble_serial(None, pipe))
        pipe.close()

    def test_manual_ble_device_is_detected(self):
        pipe = clone.serialtrace.SerialTrace()
        for port in ('/tmp/ttyBLE', '/tmp/ttyBLE0'):
            with self.subTest(port=port):
                pipe.port = port
                self.assertTrue(
                    platform.UnixPlatform.is_ble_serial(None, pipe))

    def test_non_ble_port_is_not_detected(self):
        pipe = clone.serialtrace.SerialTrace()
        for port in (None, '/dev/ttyUSB0'):
            with self.subTest(port=port):
                pipe.port = port
                self.assertFalse(
                    platform.UnixPlatform.is_ble_serial(None, pipe))

    def test_ble_device_list_dialog_returns_selected_address(self):
        dialog = mock.Mock()
        dialog._devices = [('20:91:48:4C:4C:54', 'UV Radio')]
        dialog._device.GetSelection.return_value = 0

        self.assertEqual(
            ble.BluetoothDeviceDialog.get_selected_device_info(dialog),
            ('20:91:48:4C:4C:54', 'UV Radio'))

    def test_select_ble_device_updates_selection_and_closes_dialog(self):
        parent = mock.Mock()
        parent._ble_device_address = 'old-address'
        chooser = mock.Mock()
        chooser.ShowModal.return_value = clone.wx.ID_OK
        chooser.get_selected_device_info.return_value = ('address', 'Radio')

        with mock.patch.object(ble, 'BluetoothDeviceDialog',
                               return_value=chooser) as create_dialog:
            self.assertTrue(clone.ChirpCloneDialog._select_ble_device(parent))

        create_dialog.assert_called_once_with(parent, selected='old-address')
        self.assertEqual(parent._ble_device_address, 'address')
        self.assertEqual(parent._ble_device_name, 'Radio')
        parent._clear_ble_error.assert_called_once_with()
        parent.set_ports.assert_called_once_with(select='BLE: Radio')
        self.assertFalse(chooser._alive)
        chooser.Destroy.assert_called_once_with()

    def test_cancel_ble_device_preserves_selection_and_closes_dialog(self):
        parent = mock.Mock()
        parent._ble_device_address = 'old-address'
        parent._ble_device_name = 'Old Radio'
        chooser = mock.Mock()
        chooser.ShowModal.return_value = clone.wx.ID_CANCEL

        with mock.patch.object(ble, 'BluetoothDeviceDialog',
                               return_value=chooser):
            self.assertFalse(clone.ChirpCloneDialog._select_ble_device(parent))

        self.assertEqual(parent._ble_device_address, 'old-address')
        self.assertEqual(parent._ble_device_name, 'Old Radio')
        parent._clear_ble_error.assert_not_called()
        parent.set_ports.assert_not_called()
        self.assertFalse(chooser._alive)
        chooser.Destroy.assert_called_once_with()

    def test_selecting_bluetooth_reopens_picker_for_selected_device(self):
        dialog = mock.Mock()
        dialog._current_port_selection = '/dev/ttyUSB0'
        dialog._ble_device_address = 'old-address'
        dialog._port.GetStringSelection.return_value = clone.BLUETOOTH
        dialog.get_selected_port.return_value = clone.BLUETOOTH

        def select_device():
            dialog._current_port_selection = 'BLE: UV Radio'
            return True

        dialog._select_ble_device.side_effect = select_device

        clone.ChirpCloneDialog._selected_port(dialog, None)

        dialog._select_ble_device.assert_called_once_with()
        self.assertEqual(dialog._current_port_selection, 'BLE: UV Radio')
        dialog._persist_choices.assert_called_once_with()

    def test_first_bluetooth_selection_opens_device_dialog_without_prompt(
            self):
        dialog = mock.Mock()
        dialog._port = mock.Mock()
        dialog.FindWindowById = mock.Mock()
        dialog.GetAffirmativeId = mock.Mock()
        dialog._current_port_selection = '/dev/ttyUSB0'
        dialog._ble_device_address = None
        dialog._port.GetStringSelection.return_value = clone.BLUETOOTH
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        events = []
        dialog._select_ble_device.side_effect = (
            lambda: events.append('select') or True)

        with mock.patch.object(clone, 'ChirpRadioPromptDialog') as prompt:
            clone.ChirpCloneDialog._selected_port(dialog, None)

        self.assertEqual(events, ['select'])
        prompt.assert_not_called()
        dialog._persist_choices.assert_called_once_with()

    def test_selected_ble_device_maps_back_to_bluetooth(self):
        dialog = mock.Mock()
        dialog._ble_supported = True
        dialog._ble_device_address = '20:91:48:4C:4C:54'
        dialog._ble_device_name = 'UV Radio'
        dialog._port.GetStringSelection.return_value = 'BLE: UV Radio'

        with mock.patch.object(clone.CONF, 'get', return_value=''), \
                mock.patch.object(clone.list_ports, 'comports',
                                  return_value=[]), \
                mock.patch.object(clone, 'CUSTOM_PORTS', []):
            clone.ChirpCloneDialog.set_ports(dialog, select='BLE: UV Radio')

        self.assertIn((clone.BLUETOOTH, 'BLE: UV Radio'), dialog.ports)
        dialog._port.SetStringSelection.assert_called_once_with(
            'BLE: UV Radio')
        self.assertEqual(
            clone.ChirpCloneDialog.get_selected_port(dialog),
            clone.BLUETOOTH)

    def test_translated_bluetooth_choice_maps_to_bluetooth(self):
        dialog = mock.Mock()
        dialog._ble_supported = True
        dialog._ble_device_address = None
        dialog._port.GetStringSelection.return_value = 'Bluetooth traduit'

        with mock.patch.object(clone, 'BLUETOOTH', 'Bluetooth traduit'), \
                mock.patch.object(clone.CONF, 'get', return_value=''), \
                mock.patch.object(clone.list_ports, 'comports',
                                  return_value=[]), \
                mock.patch.object(clone, 'CUSTOM_PORTS', []):
            clone.ChirpCloneDialog.set_ports(dialog, select=clone.BLUETOOTH)
            self.assertIn(
                (clone.BLUETOOTH, 'Bluetooth traduit'), dialog.ports)
            self.assertEqual(
                clone.ChirpCloneDialog.get_selected_port(dialog),
                clone.BLUETOOTH)
        dialog._port.SetStringSelection.assert_called_once_with(
            'Bluetooth traduit')

    def test_cancel_bluetooth_selection_restores_previous_port(self):
        dialog = mock.Mock()
        dialog._current_port_selection = '/dev/ttyUSB0'
        dialog._ble_device_address = 'old-address'
        dialog._port.GetStringSelection.side_effect = [
            clone.BLUETOOTH, '/dev/ttyUSB0']
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        dialog._select_ble_device.return_value = False

        clone.ChirpCloneDialog._selected_port(dialog, None)

        dialog._port.SetStringSelection.assert_called_once_with('/dev/ttyUSB0')
        dialog._persist_choices.assert_not_called()

    def test_cancel_reselecting_bluetooth_preserves_previous_device(self):
        dialog = mock.Mock()
        dialog._current_port_selection = 'BLE: Old Radio'
        dialog._ble_device_address = 'old-address'
        dialog._port.GetStringSelection.side_effect = [
            clone.BLUETOOTH, 'BLE: Old Radio']
        dialog.get_selected_port.return_value = clone.BLUETOOTH
        dialog._select_ble_device.return_value = False

        clone.ChirpCloneDialog._selected_port(dialog, None)

        dialog._select_ble_device.assert_called_once_with()
        dialog._port.SetStringSelection.assert_called_once_with(
            'BLE: Old Radio')
        self.assertEqual(dialog._ble_device_address, 'old-address')
        dialog._persist_choices.assert_not_called()

    def test_closing_ble_pipe_stops_process(self):
        process = mock.Mock()
        process.poll.return_value = None
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        connection._process = process
        pipe = clone.serialtrace.SerialTrace(
            on_close=connection.stop, is_ble=True)

        with mock.patch.object(clone.serialtrace.serial.Serial, 'close') as \
                close:
            pipe.close()
            pipe.close()

        self.assertEqual(close.call_count, 2)
        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.wait.assert_called_once_with(timeout=3)

    def test_delivered_pipe_stops_its_connection(self):
        process = mock.Mock()
        process.poll.return_value = None
        callback = mock.Mock()
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, callback)
        connection._process = process
        with mock.patch.object(connection, '_start_process',
                               return_value='/tmp/ttyBLE'), \
                mock.patch.object(clone.serialtrace.SerialTrace, 'open'), \
                mock.patch.object(clone.serialtrace.serial.Serial, 'close'), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            connection._connect()
            deliver, *args = call_after.call_args.args
            deliver(*args)
            pipe, error = callback.call_args.args
            self.assertIsNone(error)
            pipe.close()

        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.wait.assert_called_once_with(timeout=3)

    def test_stop_escalates_and_is_idempotent(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [
            ble.subprocess.TimeoutExpired('ble-serial', 3),
            ble.subprocess.TimeoutExpired('ble-serial', 3),
            None]
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        connection._process = process

        connection.stop()
        connection.stop()

        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 3)

    def test_concurrent_stop_signals_process_once(self):
        process = mock.Mock()
        process.poll.return_value = None
        entered = threading.Event()
        release = threading.Event()

        def send_signal(_signal):
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test did not release process shutdown')

        process.send_signal.side_effect = send_signal
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        connection._process = process
        first = threading.Thread(target=connection.stop)
        second = threading.Thread(target=connection.stop)
        try:
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
        finally:
            release.set()
            first.join(timeout=2)
            if second.ident is not None:
                second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        process.send_signal.assert_called_once_with(signal.SIGINT)

    def test_failed_stop_can_be_retried(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.send_signal.side_effect = [OSError('unavailable'), None]
        connection = ble.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        connection._process = process

        with self.assertLogs(ble.LOG, level='ERROR'):
            connection.stop()
        connection.stop()

        self.assertEqual(process.send_signal.call_count, 2)
        process.wait.assert_called_once_with(timeout=3)
