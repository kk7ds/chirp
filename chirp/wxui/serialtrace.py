# Copyright 2025 Dan Smith <chirp@f.danplanet.com>
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

import datetime
import functools
import logging
import os
import serial
import tempfile
import time
import warnings

from chirp import util
from chirp.wxui import config

CONF = config.get()
LOG = logging.getLogger(__name__)
TRACEFILES = []


def get_trace_entry(direction, start_ts, data):
    loglines = util.hexprint(data, block_size=16).split('\n')
    ts = time.monotonic() - start_ts
    loglines = ['%7.3f %s %s%s' % (ts, direction, line, os.linesep)
                for line in loglines if line.strip()]
    if not loglines and direction == 'R' and not data:
        # No data read means timeout, so denote that for clarity
        loglines = ['%7.3f %s # timeout%s' % (ts, direction, os.linesep)]
    return loglines


def purge_trace_files(keep=10):
    global TRACEFILES
    if keep == 0:
        purge = TRACEFILES
        TRACEFILES = []
    else:
        purge = TRACEFILES[:-keep]
        TRACEFILES = TRACEFILES[-10:]
    for fn in purge:
        try:
            os.remove(fn)
            LOG.debug('Removed old trace file %s', fn)
        except FileNotFoundError:
            pass
        except Exception as e:
            LOG.error('Failed to remove old trace file %s: %s', fn, e)


def calculate_baud_time(serial, size):
    """Calculate the time in milliseconds required to transfer size bytes"""
    cps = serial.baudrate / (1 +  # start bit
                             serial.stopbits +
                             serial.bytesize +
                             (serial.parity and 1 or 0))
    return size / cps * 1000


def warn_timeout(f):
    @functools.wraps(f)
    def wrapper(self, *a, **k):
        try:
            size = a[0]
        except IndexError:
            size = k.get('size', 1)
        required_time = calculate_baud_time(self, size)
        write_required_time = write_of = 0
        if self.last_write:
            write_at, write_of = self.last_write
            # The last operation was a write and it should require this much
            # time to complete
            write_required_time = calculate_baud_time(self, write_of)
            # If not enough time has passed to finish the write, calculate
            # remaining
            write_required_time -= max(time.monotonic() - write_at, 0)
            required_time += write_required_time
        if self.timeout is not None and required_time > (self.timeout * 1000):
            warnings.warn(
                ('Read of %i bytes requires %ims at %i baud, '
                 'but timeout is %ims (accounting for %i written bytes '
                 'in %ims)') % (
                    size, required_time, self.baudrate, self.timeout * 1000,
                    write_of, write_required_time))
            self.log('timeout %ims less than required %ims '
                     'for read of %i bytes at %i baud (%ims remaining '
                     'for %i bytes written)' % (
                         self.timeout * 1000,
                         required_time,
                         size,
                         self.baudrate,
                         write_required_time,
                         write_of))
        return f(self, *a, **k)
    return wrapper


class SerialTrace(serial.Serial):
    def __init__(self, *a, **k):
        self.__tracef = None
        self.__last_write = None
        super().__init__(*a, **k)

    @property
    def last_write(self):
        return self.__last_write

    def open(self):
        super().open()
        try:
            self.__trace_start = time.monotonic()
            self.__tracef = tempfile.NamedTemporaryFile(mode='w',
                                                        delete=False,
                                                        prefix='chirp-trace-',
                                                        suffix='.txt')
            TRACEFILES.append(self.__tracef.name)
            purge_trace_files(10)
            now = datetime.datetime.now()
            self.log('Serial trace %s started at %s' % (self, now.isoformat()))
            LOG.info('Serial trace file created: %s' % self.__tracef.name)
        except Exception as e:
            LOG.error('Failed to create serial trace file: %s' % e)
            self.__tracef = None

    def write(self, data):
        self.__last_write = (time.monotonic(), len(data))
        super().write(data)
        if self.__tracef:
            try:
                self.__tracef.writelines(get_trace_entry('W',
                                                         self.__trace_start,
                                                         data))
            except Exception as e:
                LOG.error('Failed to write to serial trace file: %s' % e)
                self.__tracef = None

    @warn_timeout
    def read(self, size=1):
        self.__last_write = None
        data = super().read(size)
        if self.__tracef:
            try:
                self.__tracef.writelines(get_trace_entry('R',
                                                         self.__trace_start,
                                                         data))
            except Exception as e:
                LOG.error('Failed to write to serial trace file: %s' % e)
                self.__tracef = None
        return data

    def close(self):
        super().close()
        if self.__tracef:
            try:
                now = datetime.datetime.now()
                self.log('Trace ended at %s' % now.isoformat())
                self.__tracef.close()
                LOG.info('Serial trace file closed: %s' % self.__tracef.name)
            except Exception as e:
                LOG.error('Failed to close serial trace file: %s' % e)
            finally:
                self.__tracef = None

    def log(self, message):
        """Log a message to the trace file.

        Use this to annotate important events in the trace file, such as
        reading a new block, etc.
        """
        if self.__tracef:
            try:
                self.__tracef.write('# %s\n' % message)
            except Exception as e:
                LOG.error('Failed to write log message to trace file: %s' % e)
                self.__tracef = None
