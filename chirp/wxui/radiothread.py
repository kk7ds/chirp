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

import logging
import queue
import threading
import uuid

LOG = logging.getLogger(__name__)
_JOB_COUNTER = 0
_JOB_COUNTER_LOCK = threading.Lock()
_JOB_LOCK = threading.Lock()


def jobnumber():
    global _JOB_COUNTER

    # This shouldn't be called outside the main thread, so this should
    # not be necessary. But, be careful anyway in case that changes in
    # the future.
    with _JOB_COUNTER_LOCK:
        num = _JOB_COUNTER
        _JOB_COUNTER += 1
    return num


class RadioJob:
    def __init__(self, editor, fn, args, kwargs):
        self.editor = editor
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.result = None
        self.id = str(uuid.uuid4())
        self.jobnumber = jobnumber()

    @property
    def score(self):
        if self.fn == 'get_memory':
            return 20
        elif self.fn.startswith('get'):
            return 10
        else:
            return 0

    def __lt__(self, job):
        # Prioritize jobs with lower scores and jobs submitted before us
        return self.score < job.score or self.jobnumber < job.jobnumber

    def __repr__(self):
        return '<%s@%i>%s(%s,%s)=%r' % (
            self.__class__.__name__,
            self.score,
            self.fn,
            ','.join(repr(a) for a in self.args),
            ','.join('%s=%r' % (k, v) for k, v in self.kwargs.items()),
            self.result)

    def dispatch(self, radio):
        try:
            with _JOB_LOCK:
                self.result = getattr(radio, self.fn)(*self.args,
                                                      **self.kwargs)
        except Exception as e:
            LOG.exception('Failed to run %r' % self)
            self.result = e

        LOG.debug('Radio finished %r' % self)


class BackgroundRadioJob(RadioJob):
    @property
    def score(self):
        return 100


class RadioThread(threading.Thread):
    SENTINEL = RadioJob(None, 'END', [], {})

    def __init__(self, radio):
        super().__init__()
        self._radio = radio
        self._queue = queue.PriorityQueue()
        self._log = logging.getLogger('RadioThread')
        self._waiting = []

    def submit(self, editor, fn, *a, **k):
        job = RadioJob(editor, fn, a, k)
        self._queue.put(job)
        return job.id

    def background(self, editor, fn, *a, **k):
        job = BackgroundRadioJob(editor, fn, a, k)
        self._queue.put(job)
        return job.id

    def end(self):
        self._queue.put(self.SENTINEL)

    def run(self):
        while True:
            job = self._queue.get()
            if job is self.SENTINEL:
                self._log.info('Exiting on request')
                return
            job.dispatch(self._radio)
            self._waiting.append(job)

            for job in list(self._waiting):
                delivered = job.editor.radio_thread_event(
                    job, block=not self.pending)
                if delivered:
                    self._waiting.remove(job)

    @property
    def pending(self):
        return self._queue.qsize()
