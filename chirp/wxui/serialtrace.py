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
import logging
import os
import serial
import tempfile
import time

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


class SerialTrace(serial.Serial):
    def __init__(self, *a, **k):
        self.__tracef = None
        super().__init__(*a, **k)

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
        super().write(data)
        if self.__tracef:
            try:
                self.__tracef.writelines(get_trace_entry('W',
                                                         self.__trace_start,
                                                         data))
            except Exception as e:
                LOG.error('Failed to write to serial trace file: %s' % e)
                self.__tracef = None

    def read(self, size=1):
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
