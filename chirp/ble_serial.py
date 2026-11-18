# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import collections
import functools
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time

import wx

from chirp import serialtrace
from chirp.wxui import common

_ = wx.GetTranslation
LOG = logging.getLogger(__name__)


# Scans for available BLE devices using the ble-scan command.
def scan_ble_device_lists():
    result = subprocess.run(
        [sys.executable, '-m', 'ble_serial.scan'],
        capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            _('ble-scan exited with status %s: %s') %
            (result.returncode, details))
    scan_errors = [
        line for line in result.stdout.splitlines()
        if line.startswith('ERROR:')]
    if scan_errors:
        raise RuntimeError('\n'.join(scan_errors))
    return parse_ble_scan_output(result.stdout)


# Formats the list of devices from ble-scan output, removing RSSI, e.g.:
# 00:11:22:33:44:55: My Device
def parse_ble_scan_output(output):
    scan_line = re.compile(r'^(\S+)\s+\(RSSI=[^)]+\):\s*(.*)$',
                           re.IGNORECASE)
    devices = []
    for line in output.splitlines():
        match = scan_line.match(line.strip())
        if match:
            devices.append((match.group(1), match.group(2).strip()))
    return devices


# Formats the selected BLE device name for display in a menu or dialog,
# falling back to the MAC address if no name is available, e.g.:
# BLE: My Device
def device(address, name):
    if not name or name.casefold() == 'none':
        name = address
    return _('BLE: %s') % name


class BluetoothConnection:
    def __init__(self, address, rclass, open_serial, on_complete):
        self._address = address
        self._rclass = rclass
        self._open_serial = open_serial
        self._on_complete = on_complete
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._pipe = None
        self._process = None
        self._process_lock = threading.Lock()

    @staticmethod
    def _read_output(process, ready, output, ports):
        if process.stdout is None:
            return
        port_line = re.compile(r'Port endpoint created on (.+?) -> .+$')
        for line in process.stdout:
            line = line.rstrip()
            output.append(line)
            LOG.debug('ble-serial: %s', line)
            match = port_line.search(line)
            if match:
                ports.append(match.group(1))
            if 'Running main loop!' in line:
                ready.set()

    def _start_process(self):
        if self._cancelled.is_set():
            raise InterruptedError('Bluetooth connection cancelled')
        process = subprocess.Popen(
            [sys.executable, '-m', 'ble_serial', '-d', self._address],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        with self._process_lock:
            self._process = process
        ready = threading.Event()
        output = collections.deque(maxlen=20)
        ports = []
        try:
            reader = threading.Thread(
                target=self._read_output,
                args=(process, ready, output, ports), daemon=True)
            reader.start()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self._cancelled.is_set():
                    raise InterruptedError('Bluetooth connection cancelled')
                if process.poll() is not None:
                    reader.join(timeout=1)
                    details = '\n'.join(output)
                    raise RuntimeError(
                        _('ble-serial exited before connecting '
                          '(status %s). %s') %
                        (process.returncode, details))
                if ready.wait(0.1):
                    if process.poll() is not None:
                        reader.join(timeout=1)
                        details = '\n'.join(output)
                        raise RuntimeError(
                            _('ble-serial stopped after connecting. %s') %
                            details)
                    if not ports:
                        raise RuntimeError(
                            _('ble-serial did not report a serial port. %s') %
                            '\n'.join(output))
                    port = ports[-1]
                    if not os.path.exists(port):
                        raise RuntimeError(
                            _('ble-serial connected but %s is unavailable') %
                            port)
                    LOG.info('ble-serial connected; using %s', port)
                    return port
            details = '\n'.join(output)
            raise RuntimeError(
                _('Timed out waiting for ble-serial to connect. %s') % details)
        except Exception:
            self.stop()
            raise

    def stop(self):
        with self._process_lock:
            process = self._process
            if process is None:
                return
            if process.poll() is not None:
                self._process = None
                return
            try:
                try:
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            except OSError:
                LOG.exception('Failed to stop ble-serial')
                return
            self._process = None

    def _open_port(self):
        if not self._address:
            raise RuntimeError(_('Select a Bluetooth device first'))
        port = self._start_process()
        LOG.info('Opening Bluetooth device %s on %s', self._address, port)
        try:
            if self._cancelled.is_set():
                raise InterruptedError('Bluetooth connection cancelled')
            serial_factory = functools.partial(
                serialtrace.SerialTrace, on_close=self.stop, is_ble=True)
            return self._open_serial(
                port, self._rclass, serial_factory=serial_factory)
        except Exception:
            self.stop()
            raise

    def start(self):
        threading.Thread(target=self._connect, daemon=True).start()

    def cancel(self):
        with self._lock:
            self._cancelled.set()
            pipe = self._pipe
            self._pipe = None
        if pipe is not None:
            pipe.close()

    def _connect(self):
        try:
            pipe = self._open_port()
        except Exception as e:
            if not self._cancelled.is_set():
                LOG.exception('Failed to connect to Bluetooth radio')
                wx.CallAfter(self._deliver, str(e))
            return

        with self._lock:
            if self._cancelled.is_set():
                cancelled = True
            else:
                self._pipe = pipe
                cancelled = False
        if cancelled:
            pipe.close()
        else:
            wx.CallAfter(self._deliver, None)

    def _deliver(self, error):
        with self._lock:
            if self._cancelled.is_set():
                return
            pipe = self._pipe
            self._pipe = None
        on_complete = self._on_complete
        self._on_complete = None
        if on_complete is not None:
            on_complete(pipe, error)


class BluetoothDeviceDialog(wx.Dialog):
    def __init__(self, parent, selected=None):
        super().__init__(parent, title=_('Bluetooth device'))
        self._devices = []
        self._selected = selected
        self._scan_thread = None
        self._scan_id = 0
        self._alive = True

        self._device = wx.Choice(self, choices=[])
        self._device.SetMinSize((400, -1))
        self._refresh = wx.Button(self, label=_('Refresh'))
        self._status = wx.StaticText(self, label='')

        device_sizer = wx.BoxSizer(wx.HORIZONTAL)
        device_sizer.Add(self._device, proportion=1,
                         flag=wx.EXPAND | wx.RIGHT, border=5)
        device_sizer.Add(self._refresh)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(device_sizer, proportion=0,
                  flag=wx.EXPAND | wx.ALL, border=10)
        sizer.Add(self._status, proportion=0,
                  flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  border=10)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL),
                  flag=wx.ALL, border=10)
        self.SetSizer(sizer)
        self.SetMinSize((500, 120))
        self.Fit()
        self.CenterOnParent()

        self.Bind(wx.EVT_BUTTON, self._refresh_devices, self._refresh)
        self.Bind(wx.EVT_CHOICE, self._selected_device, self._device)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._window_destroyed)
        self._refresh_devices()

    def get_selected_device(self):
        device = self.get_selected_device_info()
        return device[0] if device else None

    def get_selected_device_info(self):
        index = self._device.GetSelection()
        if 0 <= index < len(self._devices):
            return self._devices[index]
        return None

    def _selected_device(self, _event):
        self._selected = self.get_selected_device()
        self._update_ok_button()

    def _update_ok_button(self):
        button = self.FindWindowById(self.GetAffirmativeId())
        button.Enable(bool(self.get_selected_device()))

    def _show_scanning(self):
        self._devices = []
        self._device.SetItems([_('Scanning...')])
        self._device.SetSelection(0)
        self._device.Disable()
        self._status.SetLabel('')
        self._update_ok_button()

    def _refresh_devices(self, _event=None):
        if self._scan_thread and self._scan_thread.is_alive():
            return

        self._refresh.Disable()
        self._show_scanning()
        self._scan_id += 1
        scan_id = self._scan_id
        self._scan_thread = threading.Thread(
            target=self._scan_devices_async,
            args=(scan_id,), daemon=True)
        self._scan_thread.start()

    def _scan_devices_async(self, scan_id):
        try:
            devices = scan_ble_device_lists()
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            LOG.exception('Bluetooth device scan failed')
            wx.CallAfter(self._scan_complete, scan_id, None, str(e))
        else:
            wx.CallAfter(self._scan_complete, scan_id, devices, None)

    def _scan_complete(self, scan_id, devices, error):
        if not self._alive or scan_id != self._scan_id:
            return

        self._scan_thread = None
        self._refresh.Enable()
        self._device.Enable()
        if error:
            self._device.SetItems([])
            self._status.SetLabel(_('Bluetooth scan failed'))
            common.error_proof.show_error(
                error, parent=self, title=_('Bluetooth scan failed'))
            self._update_ok_button()
            return

        previous = self._selected
        self._devices = devices
        labels = [
            '{}: {}'.format(address, name or 'None')
            for address, name in devices]
        self._device.SetItems(labels)
        selection = next(
            (i for i, (address, _) in enumerate(devices)
             if address == previous),
            0 if devices else -1)
        self._device.SetSelection(selection)
        if devices:
            self._status.SetLabel('')
        else:
            self._status.SetLabel(_('No Bluetooth devices found'))
        self._selected = self.get_selected_device()
        self._update_ok_button()

    def _window_destroyed(self, event):
        if event.GetEventObject() is self:
            self._alive = False
        event.Skip()
