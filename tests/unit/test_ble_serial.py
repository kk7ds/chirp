import asyncio
import importlib.util
import logging
import os
import sys
import tempfile
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
    chirp_path = Path(__file__).resolve().parents[2] / 'chirp'
    spec = importlib.util.spec_from_file_location(
        'chirp.wxui._clone_ble_test', chirp_path / 'wxui' / 'clone.py')
    clone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clone)

from chirp import ble_serial as backend  # noqa: E402
from chirp import errors, platform  # noqa: E402
from chirp.drivers import baofeng_uv17Pro  # noqa: E402


class _Radio(object):
    BAUD_RATE = 19200
    HARDWARE_FLOW = True
    WANTS_RTS = False
    WANTS_DTR = True


class TestBleSerial(unittest.TestCase):
    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.ble_port = os.path.join(tempdir.name, 'ttyBLE')
        port_patch = mock.patch('ble_serial.DEFAULT_PORT', self.ble_port)
        port_patch.start()
        self.addCleanup(port_patch.stop)

    def test_scan_ble_devices(self):
        first = mock.Mock(address='20:91:48:4C:4C:54')
        first.name = 'UV Radio'
        second = mock.Mock(address='55AEB150-5AF1-4318-A02E-19A46223F572')
        second.name = None
        devices = {
            'first': (first, mock.Mock()),
            'second': (second, mock.Mock()),
        }
        with mock.patch('ble_serial.scan.main.BleakScanner.discover',
                        new_callable=mock.AsyncMock,
                        return_value=devices) as discover, \
                mock.patch.object(backend.BluetoothBridge,
                                  '_configure_logging') as configure:
            self.assertEqual(backend.scan_ble_devices(verbosity='1'), [
                ('20:91:48:4C:4C:54', 'UV Radio'),
                ('55AEB150-5AF1-4318-A02E-19A46223F572', 'None'),
            ])
        discover.assert_awaited_once_with(
            adapter='hci0', timeout=5.0, return_adv=True)
        configure.assert_called_once_with(1)

    def test_scan_runs_on_worker_thread(self):
        dialog = mock.Mock()
        dialog._scanning = False
        dialog._scan_devices_async.side_effect = (
            lambda: clone.BluetoothDeviceDialog._scan_devices_async(dialog))
        started = threading.Event()
        release = threading.Event()
        scheduled = threading.Event()
        worker_threads = []
        devices = [('address', 'Radio')]

        def scan(verbosity=None):
            worker_threads.append(threading.current_thread())
            started.set()
            if not release.wait(2):
                raise TimeoutError('test did not release BLE scan')
            return devices

        def call_after(*args):
            scheduled.set()

        with mock.patch.object(backend, 'scan_ble_devices',
                               side_effect=scan) as scan_devices, \
                mock.patch.object(clone.CONF, 'get', return_value='1'), \
                mock.patch.object(wx, 'CallAfter',
                                  side_effect=call_after) as call_after_mock:
            try:
                clone.BluetoothDeviceDialog._refresh_devices(dialog)
                self.assertTrue(started.wait(1))
                self.assertIsNot(worker_threads[0], threading.current_thread())
                release.set()
                self.assertTrue(scheduled.wait(2))
                worker_threads[0].join(2)
            finally:
                release.set()
        call_after_mock.assert_called_once_with(
            dialog._scan_complete, devices, None)
        scan_devices.assert_called_once_with(verbosity='1')

    def test_scan_stays_active_until_callback_is_processed(self):
        dialog = mock.Mock()
        dialog._scanning = False
        dialog._alive = True
        dialog._selected = None
        dialog.get_selected_device.return_value = None
        with mock.patch.object(clone.threading, 'Thread') as thread:
            clone.BluetoothDeviceDialog._refresh_devices(dialog)
            clone.BluetoothDeviceDialog._refresh_devices(dialog)
        thread.assert_called_once()
        self.assertTrue(dialog._scanning)
        dialog._refresh.Disable.assert_called_once_with()

        clone.BluetoothDeviceDialog._scan_complete(dialog, [], None)
        self.assertFalse(dialog._scanning)
        dialog._refresh.Enable.assert_called_once_with()

    def test_scan_callback_after_dialog_destroy_is_ignored(self):
        dialog = mock.Mock()
        dialog._alive = False
        clone.BluetoothDeviceDialog._scan_complete(dialog, [], None)
        dialog._refresh.Enable.assert_not_called()

    def test_scan_disables_ok_until_completion(self):
        dialog = mock.Mock()
        dialog.get_selected_device.return_value = 'address'
        button = dialog.FindWindow.return_value
        parent_button = dialog.FindWindowById.return_value
        dialog._scanning = True

        clone.BluetoothDeviceDialog._update_ok_button(dialog)
        button.Enable.assert_called_with(False)

        dialog._scanning = False
        clone.BluetoothDeviceDialog._update_ok_button(dialog)
        button.Enable.assert_called_with(True)

        dialog.get_selected_device.return_value = None
        clone.BluetoothDeviceDialog._update_ok_button(dialog)
        button.Enable.assert_called_with(False)
        parent_button.Enable.assert_not_called()

    def test_scan_timeout_is_reported(self):
        with mock.patch('ble_serial.scan.main.scan',
                        new_callable=mock.AsyncMock,
                        side_effect=asyncio.TimeoutError), \
                self.assertRaisesRegex(TimeoutError,
                                       'Bluetooth scan timed out'):
            backend.scan_ble_devices()

    def test_scan_failure_is_reported_by_worker(self):
        dialog = mock.Mock()
        for error, message in ((ValueError('Bluetooth unavailable'),
                                'Bluetooth unavailable'),
                               (ValueError(), 'ValueError')):
            with self.subTest(error=message), \
                    mock.patch.object(backend, 'scan_ble_devices',
                                      side_effect=error), \
                    mock.patch.object(wx, 'CallAfter') as call_after:
                clone.BluetoothDeviceDialog._scan_devices_async(dialog)
            call_after.assert_called_once_with(
                dialog._scan_complete, None, message)

    def test_scan_timeout_is_translated_by_worker(self):
        dialog = mock.Mock()
        with mock.patch.object(backend, 'scan_ble_devices',
                               side_effect=TimeoutError), \
                mock.patch.object(clone, '_',
                                  return_value='translated timeout'), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            clone.BluetoothDeviceDialog._scan_devices_async(dialog)
        call_after.assert_called_once_with(
            dialog._scan_complete, None, 'translated timeout')

    def test_scanned_device_labels_and_selected_address(self):
        dialog = mock.Mock()
        dialog._alive = True
        dialog.get_selected_device.return_value = None
        dialog._selected = 'address-2'
        devices = [('address-1', 'Radio'), ('address-2', ''),
                   ('address-3', 'None')]

        clone.BluetoothDeviceDialog._scan_complete(dialog, devices, None)
        dialog._device.SetItems.assert_called_once_with([
            'address-1: Radio', 'address-2: None', 'address-3: None'])
        dialog._device.SetSelection.assert_called_once_with(1)

    def test_ble_device_prefers_name_and_falls_back_to_address(self):
        address = '20:91:48:4C:4C:54'
        self.assertEqual(
            clone.get_ble_device_label(address, 'walkie-talkie'),
            'BLE: walkie-talkie')
        self.assertEqual(
            clone.get_ble_device_label(address, 'None'),
            'BLE: {}'.format(address))

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires a pseudo-terminal')
    def test_bridge_connects_and_transfers_serial_data(self):
        client = mock.Mock()
        client.connect = mock.AsyncMock()
        client.setup_chars = mock.AsyncMock()
        client.write_char = mock.Mock(max_write_without_response_size=3)
        client.disconnect = mock.AsyncMock()

        async def wait_for_stop():
            await asyncio.Event().wait()

        client.send_loop = mock.AsyncMock(side_effect=wait_for_stop)
        client.check_loop = mock.AsyncMock(side_effect=wait_for_stop)
        received = threading.Event()
        sent = []

        def queue_send(data):
            sent.append(data)
            if sum(map(len, sent)) >= len(b'hello'):
                received.set()

        client.queue_send.side_effect = queue_send
        connection = clone.BluetoothConnection(
            '20:91:48:4C:4C:54', _Radio, clone.open_serial, mock.Mock())
        with tempfile.TemporaryDirectory() as trace_dir, \
                mock.patch.object(backend.serialtrace.SerialTrace, 'trace_dir',
                                  new_callable=mock.PropertyMock,
                                  return_value=trace_dir), \
                mock.patch.object(backend.serialtrace, 'TRACEFILES', []), \
                mock.patch('ble_serial.bluetooth.ble_client.BLE_client',
                           return_value=client) as factory:
            try:
                with self.assertLogs(backend.LOG, level='INFO') as logs:
                    pipe = connection._open_port()
                self.assertTrue(any(
                    'No custom BLE MTU configured' in message
                    for message in logs.output))
                try:
                    self.assertEqual(pipe.port, self.ble_port)
                    self.assertTrue(os.path.islink(self.ble_port))
                    pipe.write(b'hello')
                    self.assertTrue(received.wait(2))
                    self.assertEqual(b''.join(sent), b'hello')
                    self.assertTrue(all(len(data) <= 3 for data in sent))
                    receive = client.set_receiver.call_args.args[0]
                    connection._serial._loop.call_soon_threadsafe(
                        receive, b'world')
                    self.assertEqual(pipe.read(5), b'world')
                finally:
                    pipe.close()
            finally:
                connection._serial.stop()
                connection._serial._thread.join(2)
        factory.assert_called_once_with('hci0', None)
        client.connect.assert_awaited_once_with(
            '20:91:48:4C:4C:54', 'public', None, 5.0)
        client.setup_chars.assert_awaited_once_with(None, None, 'rw', False)
        client.disconnect.assert_awaited_once()
        self.assertFalse(connection._serial._thread.is_alive())
        self.assertFalse(os.path.lexists(self.ble_port))

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires a pseudo-terminal')
    def test_existing_ble_port_is_not_replaced_or_removed(self):
        with open(self.ble_port, 'w') as existing:
            existing.write('existing port')
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())

        with self.assertRaises(FileExistsError):
            connection._serial.start()
        connection._serial._thread.join(2)
        with open(self.ble_port) as existing:
            self.assertEqual(existing.read(), 'existing port')

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

        with mock.patch.object(clone.BluetoothConnection, '_open_port',
                               side_effect=open_ble), \
                mock.patch.object(wx, 'CallAfter', side_effect=call_after), \
                mock.patch.object(clone.config._CONFIG, 'save') as save:
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
        dialog._persist_choices.assert_called_once_with()
        dialog._remember_port_for_selected.assert_called_once_with()
        save.assert_called_once_with()

    def test_bluetooth_selection_requires_device(self):
        connection = clone.BluetoothConnection(
            None, _Radio, clone.open_serial, mock.Mock())
        with mock.patch.object(connection._serial, 'start') as start, \
                self.assertRaisesRegex(RuntimeError, 'Select a Bluetooth'):
            connection._open_port()
        start.assert_not_called()

    def test_ble_port_opens_with_managed_serial_trace(self):
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        pipe = connection._serial
        with mock.patch.object(connection._serial, 'start',
                               return_value='/tmp/ttyBLE'), \
                mock.patch.object(pipe, 'open') as serial_open:
            result = connection._open_port()

        self.assertIs(result, pipe)
        self.assertEqual(pipe.baudrate, _Radio.BAUD_RATE)
        self.assertEqual(pipe.rtscts, _Radio.HARDWARE_FLOW)
        self.assertEqual(pipe.timeout, 0.25)
        self.assertEqual(pipe.write_timeout, 2)
        self.assertEqual(pipe.port, '/tmp/ttyBLE')
        serial_open.assert_called_once_with()

    def test_bridge_uses_driver_mtu_unless_configured(self):
        class DriverWithMtu:
            BLE_MTU = 48

        cases = (
            (None, None, None, 0),
            (DriverWithMtu, None, 48, 0),
            (DriverWithMtu, '64', 64, 3),
        )
        for rclass, configured_mtu, expected_mtu, verbosity in cases:
            with self.subTest(configured_mtu=configured_mtu):
                bridge = backend.BluetoothBridge(
                    'address', mtu=configured_mtu,
                    verbosity=str(verbosity), rclass=rclass)
                self.assertEqual(bridge._mtu, expected_mtu)
                self.assertEqual(bridge._verbosity, verbosity)

    def test_selected_ble_options_use_driver_and_config_values(self):
        class DriverWithMtu:
            BLE_MTU = 48

        dialog = mock.Mock()
        dialog._ble_device_address = 'address'
        continuation = mock.Mock()
        cases = (
            (_Radio, {}, None, None),
            (DriverWithMtu, {}, None, None),
            (DriverWithMtu,
             {'ble_mtu': '64', 'verbosity': '3'},
             '64', '3'),
        )

        for rclass, settings, expected_mtu, expected_verbosity in cases:
            with self.subTest(settings=settings), \
                    mock.patch.object(
                        clone.CONF, 'get',
                        side_effect=lambda key, section=None:
                            settings.get(key)) as config_get, \
                    mock.patch.object(clone, 'BluetoothConnection') as \
                    connection:
                clone.ChirpCloneDialog._open_selected_port(
                    dialog, clone.BLUETOOTH, rclass, continuation)

            self.assertEqual(config_get.call_args_list, [
                mock.call('ble_mtu', 'bluetooth'),
                mock.call('verbosity', 'bluetooth'),
            ])
            self.assertEqual(
                connection.call_args.kwargs['mtu'], expected_mtu)
            self.assertEqual(
                connection.call_args.kwargs['verbosity'],
                expected_verbosity)

    def test_non_bluetooth_selection_opens_serial_port(self):
        dialog = mock.Mock()
        continuation = mock.Mock()
        with mock.patch.object(clone, 'open_serial') as open_serial, \
                mock.patch.object(clone, 'BluetoothConnection') as open_ble:
            clone.ChirpCloneDialog._open_selected_port(
                dialog, '/dev/ttyUSB0', _Radio, continuation)
        continuation.assert_called_once_with(open_serial.return_value)
        open_serial.assert_called_once_with('/dev/ttyUSB0', _Radio)
        open_ble.assert_not_called()
        dialog._start_ble_activity.assert_not_called()

    def test_ble_port_open_failure_stops_bridge(self):
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        with mock.patch.object(connection._serial, 'start',
                               return_value='/tmp/ttyBLE'), \
                mock.patch.object(connection._serial, 'stop') as stop, \
                mock.patch.object(connection._serial, 'open',
                                  side_effect=OSError('port unavailable')), \
                self.assertRaisesRegex(OSError, 'port unavailable'):
            connection._open_port()
        stop.assert_called_once_with()

    def test_cancelled_connection_does_not_start_bridge(self):
        connection = clone.BluetoothConnection(
            'device', _Radio, clone.open_serial, mock.Mock())
        connection.cancel()
        with mock.patch.object(backend.threading, 'Thread') as thread, \
                self.assertRaises(InterruptedError):
            connection._serial.start()
        thread.assert_not_called()

    def test_cancel_before_connection_callback_closes_pipe(self):
        dialog = mock.Mock()
        continuation = mock.Mock()
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, continuation)
        pipe = mock.Mock()
        connection._pipe = pipe
        dialog._ble_connection = connection

        clone.ChirpCloneDialog._cancel_ble_connection(dialog)
        connection._deliver(None)

        pipe.close.assert_called_once_with()
        continuation.assert_not_called()
        self.assertIsNone(connection._on_complete)
        dialog._stop_ble_activity.assert_not_called()

    def test_delivery_without_callback_closes_pipe(self):
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, None)
        pipe = mock.Mock()
        connection._pipe = pipe
        connection._deliver(None)
        pipe.close.assert_called_once_with()

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

        with mock.patch.object(clone.BluetoothConnection, '_open_port',
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

    def test_bluetooth_connection_timeout_stops_bridge_and_reports_error(self):
        on_complete = mock.Mock()
        connection = clone.BluetoothConnection(
            'device', _Radio, clone.open_serial, on_complete)
        with mock.patch.object(backend.threading, 'Thread'), \
                mock.patch.object(connection._serial._ready, 'wait',
                                  return_value=False), \
                mock.patch.object(connection._serial, 'stop') as stop, \
                mock.patch.object(wx, 'CallAfter') as call_after:
            connection.run()
            callback, *args = call_after.call_args.args
            callback(*args)

        pipe, error = on_complete.call_args.args
        self.assertIsNone(pipe)
        self.assertIn('Timed out waiting for Bluetooth connection', error)
        stop.assert_called_once_with()

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires a pseudo-terminal')
    def test_ble_connect_timeout_preserves_error(self):
        client = mock.Mock()
        client.connect = mock.AsyncMock(
            side_effect=TimeoutError('BLE connection timed out'))
        client.disconnect = mock.AsyncMock()
        connection = clone.BluetoothConnection(
            'device', _Radio, clone.open_serial, mock.Mock())
        with mock.patch('ble_serial.bluetooth.ble_client.BLE_client',
                        return_value=client), \
                self.assertRaisesRegex(TimeoutError,
                                       'BLE connection timed out'):
            connection._serial.start()
        connection._serial._thread.join(2)
        client.disconnect.assert_awaited_once()

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires a pseudo-terminal')
    def test_non_radio_ble_connection_failure_is_reported(self):
        client = mock.Mock()
        client.connect = mock.AsyncMock()
        client.setup_chars = mock.AsyncMock(
            side_effect=AssertionError('No matching characteristic'))
        client.disconnect = mock.AsyncMock()
        dialog = mock.Mock()
        continuation = mock.Mock()
        dialog._ble_connection_complete.side_effect = (
            lambda *args: clone.ChirpCloneDialog._ble_connection_complete(
                dialog, *args))
        connection = clone.BluetoothConnection(
            'non-radio', _Radio, clone.open_serial,
            lambda pipe, error: dialog._ble_connection_complete(
                continuation, pipe, error))
        with mock.patch('ble_serial.bluetooth.ble_client.BLE_client',
                        return_value=client), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            connection.run()
            callback, *args = call_after.call_args.args
            callback(*args)

        self.assertIn('No matching characteristic',
                      dialog.fail.call_args.args[0])
        client.disconnect.assert_awaited_once()
        dialog._stop_ble_activity.assert_called_once_with()
        continuation.assert_not_called()

    def test_non_radio_silent_serial_reports_no_response_and_stops_ble(self):
        connection = clone.BluetoothConnection(
            'non-radio', _Radio, clone.open_serial, mock.Mock())
        pipe = connection._serial
        pipe.port = '/tmp/ttyBLE'
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
        self.assertTrue(connection._serial._stopped.is_set())

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

        with mock.patch.object(clone.BluetoothConnection, '_open_port',
                               side_effect=OSError('connection failed')), \
                mock.patch.object(wx, 'CallAfter', side_effect=call_after):
            clone.ChirpCloneDialog._open_selected_port(
                dialog, clone.BLUETOOTH, _Radio, mock.Mock())
            self.assertTrue(scheduled.wait(2))
            callback, *args = callbacks[0]
            callback(*args)

        dialog._stop_ble_activity.assert_called_once_with()
        dialog.fail.assert_called_once_with('connection failed')

    def test_managed_ble_pipe_is_detected(self):
        pipe = backend.BluetoothBridge('address')
        pipe.port = '/tmp/ttyBLE'
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
        pipe.port = '/dev/ttyUSB0'
        self.assertFalse(platform.UnixPlatform.is_ble_serial(None, pipe))

    def test_ble_serial_verbosity_configures_logging(self):
        root_logger = logging.getLogger()
        bleak_logger = logging.getLogger('bleak')
        cases = (
            (0, logging.WARNING),
            (1, logging.INFO),
            (2, logging.DEBUG)
        )
        handler = logging.StreamHandler()
        with mock.patch.object(root_logger, 'handlers', [handler]), \
                mock.patch.object(root_logger, 'level', logging.DEBUG), \
                mock.patch.object(bleak_logger, 'level', logging.NOTSET):
            for verbosity, bleak_level in cases:
                with self.subTest(verbosity=verbosity):
                    backend.BluetoothBridge._configure_logging(verbosity)
                    self.assertEqual(bleak_logger.getEffectiveLevel(),
                                     bleak_level)

    def test_select_ble_device_updates_selection_and_closes_dialog(self):
        parent = mock.Mock()
        parent._ble_device_address = 'old-address'
        chooser = mock.Mock()
        chooser.ShowModal.return_value = clone.wx.ID_OK
        chooser.get_selected_device_info.return_value = ('address', 'Radio')

        with mock.patch.object(clone, 'BluetoothDeviceDialog',
                               return_value=chooser) as create_dialog:
            self.assertTrue(clone.ChirpCloneDialog._select_ble_device(parent))

        create_dialog.assert_called_once_with(parent, selected='old-address')
        self.assertEqual(parent._ble_device_address, 'address')
        self.assertEqual(parent._ble_device_name, 'Radio')
        parent._clear_ble_error.assert_called_once_with()
        parent.set_ports.assert_called_once_with(select='address')
        self.assertFalse(chooser._alive)
        chooser.Destroy.assert_called_once_with()

    def test_cancel_ble_device_preserves_selection_and_closes_dialog(self):
        parent = mock.Mock()
        parent._ble_device_address = 'old-address'
        parent._ble_device_name = 'Old Radio'
        chooser = mock.Mock()
        chooser.ShowModal.return_value = clone.wx.ID_CANCEL

        with mock.patch.object(clone, 'BluetoothDeviceDialog',
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
        dialog._remember_port_for_selected.assert_not_called()
        dialog.FindWindowById.return_value.Enable.assert_called_once_with(
            True)

    def test_selected_ble_device_maps_back_to_address(self):
        dialog = mock.Mock()
        dialog._ble_supported = True
        dialog._ble_device_address = '20:91:48:4C:4C:54'
        dialog._ble_device_name = 'UV Radio'
        dialog._port.GetStringSelection.return_value = 'BLE: UV Radio'

        with mock.patch.object(
                clone.CONF, 'get', return_value='20:91:48:4C:4C:54'), \
                mock.patch.object(clone.list_ports, 'comports',
                                  return_value=[]), \
                mock.patch.object(clone, 'CUSTOM_PORTS', []):
            clone.ChirpCloneDialog.set_ports(
                dialog, select='20:91:48:4C:4C:54')

        self.assertIn(
            ('20:91:48:4C:4C:54', 'BLE: UV Radio'), dialog.ports)
        self.assertNotIn(('20:91:48:4C:4C:54', '20:91:48:4C:4C:54'),
                         dialog.ports)
        dialog._port.SetStringSelection.assert_called_once_with(
            'BLE: UV Radio')
        self.assertEqual(
            clone.ChirpCloneDialog.get_selected_port(dialog),
            '20:91:48:4C:4C:54')

    def test_last_ble_address_restores_without_scanning(self):
        addresses = (
            '20:91:48:4C:4C:54',
            '55AEB150-5AF1-4318-A02E-19A46223F572',
        )
        for address in addresses:
            with self.subTest(address=address):
                dialog = mock.Mock()
                dialog._ble_supported = True
                dialog._ble_device_address = None
                dialog._ble_device_name = None
                label = 'BLE: {}'.format(address)
                dialog._port.GetStringSelection.return_value = label

                def get_config(key, section=None):
                    return address if key == 'last_port' else ''

                with mock.patch.object(
                        clone.CONF, 'get', side_effect=get_config), \
                        mock.patch.object(clone.list_ports, 'comports',
                                          return_value=[]), \
                        mock.patch.object(clone, 'CUSTOM_PORTS', []):
                    clone.ChirpCloneDialog.set_ports(dialog)

                self.assertEqual(dialog._ble_device_address, address)
                self.assertIsNone(dialog._ble_device_name)
                dialog._port.SetStringSelection.assert_called_once_with(
                    label)
                self.assertEqual(
                    clone.ChirpCloneDialog.get_selected_port(dialog),
                    address)

    def test_radio_ble_address_is_restored_without_saving(self):
        address = '9C60DFB9-00B4-1F95-FEC5-73F8483B1618'
        dialog = mock.Mock()
        dialog._vendor.GetStringSelection.return_value = 'Vendor'
        dialog._model.GetStringSelection.return_value = 'Model'
        dialog.get_selected_rclass.return_value = _Radio
        dialog._ble_supported = True
        dialog._ble_device_address = None
        dialog._ble_device_name = None
        dialog.get_selected_port.return_value = address
        dialog.ports = [(clone.BLUETOOTH, clone.BLUETOOTH)]
        dialog.set_ports = mock.Mock()
        dialog.set_selected_port = lambda port: (
            clone.ChirpCloneDialog.set_selected_port(dialog, port))

        rconfig = mock.Mock()
        rconfig.get.side_effect = lambda key: {
            'last_port': address,
            'last_ble_device_name': 'walkie-talkie',
        }.get(key)

        with mock.patch.object(
                clone.config, 'get_for_radio', return_value=rconfig), \
                mock.patch.object(clone.CONF, 'set') as config_set, \
                mock.patch.object(clone.config._CONFIG, 'save') as save:
            clone.ChirpCloneDialog._select_port_for_model(dialog)

        self.assertEqual(dialog._ble_device_name, 'walkie-talkie')
        dialog.set_ports.assert_called_once_with(
            select=address)
        config_set.assert_not_called()
        rconfig.set.assert_not_called()
        save.assert_not_called()

    def test_selected_bluetooth_port_uses_saved_ble_address(self):
        dialog = mock.Mock()
        dialog._ble_device_address = '20:91:48:4C:4C:54'
        dialog._port.GetStringSelection.return_value = clone.BLUETOOTH
        dialog.ports = [(clone.BLUETOOTH, clone.BLUETOOTH)]

        self.assertEqual(
            clone.ChirpCloneDialog.get_selected_port(dialog),
            '20:91:48:4C:4C:54')

    def test_last_ble_address_opens_as_bluetooth(self):
        address = '20:91:48:4C:4C:54'
        dialog = mock.Mock()
        dialog._ble_device_address = address
        continuation = mock.Mock()

        with mock.patch.object(clone, 'BluetoothConnection') as connection:
            clone.ChirpCloneDialog._open_selected_port(
                dialog, address, _Radio, continuation)

        self.assertEqual(connection.call_args.args[0], address)
        connection.return_value.start.assert_called_once_with()

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

    def test_cancel_bluetooth_selection_restores_previous_choice(self):
        for previous in ('/dev/ttyUSB0', 'BLE: Old Radio'):
            with self.subTest(previous=previous):
                dialog = mock.Mock()
                dialog._current_port_selection = previous
                dialog._ble_device_address = 'old-address'
                dialog._port.GetStringSelection.side_effect = [
                    clone.BLUETOOTH, previous]
                dialog.get_selected_port.return_value = clone.BLUETOOTH
                dialog._select_ble_device.return_value = False

                clone.ChirpCloneDialog._selected_port(dialog, None)

                dialog._select_ble_device.assert_called_once_with()
                dialog._port.SetStringSelection.assert_called_once_with(
                    previous)
                self.assertEqual(dialog._ble_device_address, 'old-address')
                dialog._persist_choices.assert_not_called()

    def test_ble_close_stops_bridge_even_if_serial_close_fails(self):
        pipe = backend.BluetoothBridge('address')
        with mock.patch('serial.Serial.close',
                        side_effect=OSError('close failed')), \
                mock.patch.object(pipe, 'stop') as stop, \
                self.assertRaisesRegex(OSError, 'close failed'):
            pipe.close()
        stop.assert_called_once_with()

    def test_delivered_pipe_stops_its_connection(self):
        callback = mock.Mock()
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, callback)
        with mock.patch.object(connection._serial, 'start',
                               return_value='/tmp/ttyBLE'), \
                mock.patch.object(clone.serialtrace.SerialTrace, 'open'), \
                mock.patch.object(clone.serialtrace.serial.Serial, 'close'), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            connection.run()
            deliver, *args = call_after.call_args.args
            deliver(*args)
            pipe, error = callback.call_args.args
            self.assertIsNone(error)
            pipe.close()

        self.assertTrue(connection._serial._stopped.is_set())

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires a pseudo-terminal')
    def test_cancel_during_ble_connect_disconnects_and_stops_bridge(self):
        started = threading.Event()
        client = mock.Mock()

        async def connect(*args):
            started.set()
            await asyncio.Event().wait()

        client.connect = mock.AsyncMock(side_effect=connect)
        client.disconnect = mock.AsyncMock()
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        with mock.patch('ble_serial.bluetooth.ble_client.BLE_client',
                        return_value=client), \
                mock.patch.object(wx, 'CallAfter') as call_after:
            connection.start()
            try:
                self.assertTrue(started.wait(2))
                connection.cancel()
                connection.join(2)
                connection._serial._thread.join(2)
                self.assertFalse(connection.is_alive())
                self.assertFalse(connection._serial._thread.is_alive())
                client.disconnect.assert_awaited_once()
                call_after.assert_not_called()
            finally:
                connection.cancel()
                connection.join(2)
                connection._serial._thread.join(2)

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires a pseudo-terminal')
    def test_full_serial_buffer_does_not_block_bridge_shutdown(self):
        client = mock.Mock()
        client.connect = mock.AsyncMock()
        client.setup_chars = mock.AsyncMock()
        client.write_char = mock.Mock(max_write_without_response_size=20)
        client.disconnect = mock.AsyncMock()

        async def wait_for_stop():
            await asyncio.Event().wait()

        client.send_loop = mock.AsyncMock(side_effect=wait_for_stop)
        client.check_loop = mock.AsyncMock(side_effect=wait_for_stop)
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        with mock.patch('ble_serial.bluetooth.ble_client.BLE_client',
                        return_value=client):
            try:
                connection._serial.start()
                receive = client.set_receiver.call_args.args[0]
                responsive = threading.Event()

                def queue_data():
                    receive(b'x' * (1024 * 1024))
                    connection._serial._loop.call_later(0.1, responsive.set)

                connection._serial._loop.call_soon_threadsafe(queue_data)
                self.assertTrue(responsive.wait(2))
            finally:
                connection._serial.stop()
                connection._serial._thread.join(2)
        self.assertFalse(connection._serial._thread.is_alive())
        client.disconnect.assert_awaited_once()

    @unittest.skipUnless(hasattr(os, 'openpty'), 'requires a pseudo-terminal')
    def test_repeated_stop_does_not_interrupt_bridge_cleanup(self):
        disconnecting = threading.Event()
        release = threading.Event()
        client = mock.Mock()
        client.connect = mock.AsyncMock()
        client.setup_chars = mock.AsyncMock()
        client.write_char = mock.Mock(max_write_without_response_size=20)

        async def wait_for_stop():
            await asyncio.Event().wait()

        async def disconnect():
            disconnecting.set()
            await asyncio.to_thread(release.wait, 2)

        client.send_loop = mock.AsyncMock(side_effect=wait_for_stop)
        client.check_loop = mock.AsyncMock(side_effect=wait_for_stop)
        client.disconnect = mock.AsyncMock(side_effect=disconnect)
        connection = clone.BluetoothConnection(
            'address', _Radio, clone.open_serial, mock.Mock())
        with mock.patch('ble_serial.bluetooth.ble_client.BLE_client',
                        return_value=client):
            connection._serial.start()
            first = threading.Thread(target=connection._serial.stop)
            second = threading.Thread(target=connection._serial.stop)
            try:
                first.start()
                self.assertTrue(disconnecting.wait(2))
                second.start()
                first.join(0.5)
                second.join(0.5)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertTrue(connection._serial._thread.is_alive())
                release.set()
                connection._serial._thread.join(2)
                self.assertFalse(connection._serial._thread.is_alive())
                client.disconnect.assert_awaited_once()
            finally:
                release.set()
                connection._serial.stop()
                connection._serial._thread.join(2)
