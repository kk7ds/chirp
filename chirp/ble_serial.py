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

import asyncio
import logging
import os
import threading

from chirp import serialtrace

LOG = logging.getLogger(__name__)


def scan_ble_devices():
    from ble_serial.scan.main import scan

    async def run_scan():
        return await asyncio.wait_for(scan('hci0', 5.0, None), timeout=30)

    try:
        devices = asyncio.run(run_scan())
    except asyncio.TimeoutError as e:
        raise TimeoutError('Bluetooth scan timed out') from e
    return [(dev.address, dev.name.strip() if dev.name is not None else 'None')
            for dev, _adv in devices.values()]


class BluetoothBridge(serialtrace.SerialTrace):
    def __init__(self, address, mtu=None, verbosity=None, rclass=None):
        self._address = address
        self._mtu, self._mtu_source = self._resolve_mtu(mtu, rclass)
        self._verbosity = self._resolve_verbosity(verbosity)
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._endpoint_path = None
        self._error = None
        self._stopped = threading.Event()
        self._thread = None
        self._loop = None
        self._task = None
        super().__init__()

    @staticmethod
    def _resolve_mtu(mtu, rclass):
        # Use `BLE_MTU` key from a driver radio class.
        # Overridden by `ble_mtu` key in chirp.config [bluetooth] section.
        mtu_source = (
            'chirp.config' if mtu not in (None, '') else 'radio driver')
        if mtu is None or mtu == '':
            mtu = getattr(rclass, 'BLE_MTU', None)
        mtu = int(mtu) if mtu is not None else None
        if mtu is not None and mtu <= 0:
            raise ValueError('BLE serial MTU must be a positive integer')
        return mtu, mtu_source

    @staticmethod
    def _resolve_verbosity(verbosity):
        # Read `verbosity` level (1=INFO, 2=DEBUG) from
        # chirp.config [bluetooth] section.
        verbosity = int(verbosity) if verbosity else 0
        if verbosity < 0:
            raise ValueError('BLE serial verbosity must be non-negative')
        return verbosity

    def _configure_logging(self):
        if self._verbosity:
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)
            for handler in root_logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    handler.setLevel(logging.DEBUG)
            logging.getLogger('bleak').setLevel(
                logging.DEBUG if self._verbosity > 1 else logging.INFO)

    async def _run_bridge(self):
        import tty

        from ble_serial import DEFAULT_PORT
        from ble_serial.bluetooth.ble_client import BLE_client

        self._configure_logging()
        if self._mtu is None:
            LOG.info('No custom BLE MTU configured; '
                     'will use BLE_client default = 20')
        else:
            LOG.info('Using custom BLE MTU %d from %s',
                     self._mtu, self._mtu_source)
        loop = asyncio.get_running_loop()
        # Keep the slave open until shutdown, including while BLE connects.
        controller, endpoint = os.openpty()
        client = None
        tasks = []
        failure = loop.create_future()
        reader_added = False
        link_info = None
        try:
            with self._lock:
                if self._stopped.is_set():
                    raise InterruptedError('Bluetooth connection cancelled')
                self._loop = loop
                self._task = asyncio.current_task()
            endpoint_path = os.ttyname(endpoint)
            os.symlink(endpoint_path, DEFAULT_PORT)
            link_info = os.lstat(DEFAULT_PORT)
            tty.setraw(controller)
            os.set_blocking(controller, False)
            client = BLE_client('hci0', None)
            outgoing = asyncio.Queue()

            def receive_serial():
                try:
                    data = os.read(controller, self._mtu)
                    if not data:
                        raise RuntimeError('Bluetooth serial port closed')
                    client.queue_send(data)
                except BlockingIOError:
                    return
                except Exception as e:
                    loop.remove_reader(controller)
                    if not failure.done():
                        failure.set_exception(e)

            def receive_bluetooth(data):
                outgoing.put_nowait(data)

            async def write_serial():
                while True:
                    data = await outgoing.get()
                    while data:
                        try:
                            written = os.write(controller, data)
                        except BlockingIOError:
                            writable = loop.create_future()

                            def serial_writable(writable=writable):
                                if not writable.done():
                                    writable.set_result(None)

                            loop.add_writer(controller, serial_writable)
                            try:
                                await writable
                            finally:
                                loop.remove_writer(controller)
                            continue
                        if not written:
                            raise OSError('Bluetooth serial write failed')
                        data = data[written:]

            client.set_receiver(receive_bluetooth)
            loop.add_reader(controller, receive_serial)
            reader_added = True
            await client.connect(self._address, 'public', None, 5.0)
            await client.setup_chars(None, None, 'rw', False)
            if self._mtu is None:
                self._mtu = client.write_char.max_write_without_response_size
                if self._mtu <= 0:
                    raise ValueError('BLE client returned an invalid MTU')
            tasks = [asyncio.create_task(client.send_loop()),
                     asyncio.create_task(client.check_loop()),
                     asyncio.create_task(write_serial())]
            self._endpoint_path = DEFAULT_PORT
            self._ready.set()
            done, _ = await asyncio.wait(
                [*tasks, failure], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if not self._stopped.is_set():
                raise RuntimeError('Bluetooth connection closed')
        finally:
            with self._lock:
                self._loop = None
                self._task = None
            if reader_added:
                loop.remove_reader(controller)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if not failure.done():
                failure.cancel()
            elif not failure.cancelled():
                failure.exception()
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    LOG.exception('Failed to disconnect Bluetooth')
            try:
                if link_info is not None:
                    try:
                        current_link = os.lstat(DEFAULT_PORT)
                    except FileNotFoundError:
                        LOG.warning('Bluetooth serial link was removed: %s',
                                    DEFAULT_PORT)
                    else:
                        if (current_link.st_dev, current_link.st_ino) == (
                                link_info.st_dev, link_info.st_ino):
                            os.unlink(DEFAULT_PORT)
                        else:
                            LOG.warning('Bluetooth serial link was replaced: '
                                        '%s', DEFAULT_PORT)
            finally:
                try:
                    os.close(controller)
                finally:
                    os.close(endpoint)

    def _run_thread(self):
        try:
            asyncio.run(self._run_bridge())
        except asyncio.CancelledError:
            if not self._ready.is_set():
                self._error = InterruptedError(
                    'Bluetooth connection cancelled')
        except Exception as e:
            LOG.exception('Bluetooth bridge failed')
            if not self._ready.is_set():
                self._error = e
        finally:
            if not self._ready.is_set():
                if self._error is None:
                    self._error = RuntimeError(
                        'Bluetooth connection closed')
                self._ready.set()

    def start(self):
        with self._lock:
            if self._stopped.is_set():
                raise InterruptedError('Bluetooth connection cancelled')
            self._thread = threading.Thread(
                target=self._run_thread, daemon=True)
            self._thread.start()
        if not self._ready.wait(timeout=30):
            self.stop()
            raise RuntimeError(
                'Timed out waiting for Bluetooth connection')
        if self._error is not None:
            raise self._error
        if self._stopped.is_set():
            raise InterruptedError('Bluetooth connection cancelled')
        return self._endpoint_path

    def stop(self):
        with self._lock:
            stopping = self._stopped.is_set()
            self._stopped.set()
            loop = self._loop
            task = self._task
            if not stopping and loop is not None and task is not None:
                loop.call_soon_threadsafe(task.cancel)

    def close(self):
        try:
            super().close()
        finally:
            self.stop()
