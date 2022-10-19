import logging
import queue
import threading
import uuid

import wx

LOG = logging.getLogger(__name__)
RadioThreadResult, EVT_RADIO_THREAD_RESULT = wx.lib.newevent.NewCommandEvent()


class RadioJob:
    def __init__(self, editor, fn, args, kwargs):
        self.editor = editor
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.result = None
        self.id = str(uuid.uuid4())

    def __repr__(self):
        return '<RadioJob>%s(%s,%s)=%r' % (
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
    SENTINEL = object()

    def __init__(self, radio):
        super().__init__()
        self._radio = radio
        self._queue = queue.Queue()
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

