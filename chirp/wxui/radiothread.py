import logging
import queue
import threading
import uuid

import wx

LOG = logging.getLogger(__name__)
RadioThreadResult, EVT_RADIO_THREAD_RESULT = wx.lib.newevent.NewCommandEvent()
_JOB_COUNTER = 0
_JOB_COUNTER_LOCK = threading.Lock()


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
        return '<RadioJob@%i>%s(%s,%s)=%r' % (
            self.score,
            self.fn,
            ','.join(repr(a) for a in self.args),
            ','.join('%s=%r' % (k, v) for k, v in self.kwargs.items()),
            self.result)

    def dispatch(self, radio):
        try:
            self.result = getattr(radio, self.fn)(*self.args, **self.kwargs)
        except Exception as e:
            self.result = e

        LOG.debug('Radio finished %r' % self)
        wx.PostEvent(self.editor, RadioThreadResult(
            self.editor.GetId(), job=self))


class RadioThread(threading.Thread):
    SENTINEL = RadioJob(None, 'END', [], {})

    def __init__(self, radio):
        super().__init__()
        self._radio = radio
        self._queue = queue.PriorityQueue()
        self._log = logging.getLogger('RadioThread')

    def submit(self, editor, fn, *a, **k):
        job = RadioJob(editor, fn, a, k)
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

    @property
    def pending(self):
        return self._queue.qsize()
