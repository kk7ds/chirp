#!/usr/bin/python
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import gtk
import gobject

import threading
import time

from chirp import errors

class Editor(gobject.GObject):
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
        }

    root = None

    def __init__(self):
        gobject.GObject.__init__(self)

    def focus(self):
        pass

gobject.type_register(Editor)

def DBG(*args):
    if False:
        print args.join(" ")

class RadioJob:
    def __init__(self, cb, func, *args, **kwargs):
        self.cb = cb
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.desc = "Working"

    def __str__(self):
        return "RadioJob(%s,%s,%s)" % (self.func, self.args, self.kwargs)

    def set_desc(self, desc):
        self.desc = desc

    def execute(self, radio):
        try:
            func = getattr(radio, self.func)
        except AttributeError, e:
            print "No such radio function `%s'" % self.func
            return

        try:
            DBG("Running %s (%s %s)" % (self.func,
                                        str(self.args),
                                        str(self.kwargs)))
            result = func(*self.args, **self.kwargs)
        except errors.InvalidMemoryLocation, e:
            result = e
        except Exception, e:
            print "Exception running RadioJob: %s" % e
            log_exception()
            print "Job Args:   %s" % str(self.args)
            print "Job KWArgs: %s" % str(self.kwargs)
            result = e

        if self.cb:
            gobject.idle_add(self.cb, result)

class RadioThread(threading.Thread, gobject.GObject):
    __gsignals__ = {
        "status" : (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE,
                    (gobject.TYPE_STRING,)),
        }

    def __init__(self, radio):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.__queue = {}
        self.__counter = threading.Semaphore(0)
        self.__enabled = True
        self.__lock = threading.Lock()
        self.__runlock = threading.Lock()
        self.radio = radio

    def _qlock(self):
        self.__lock.acquire()

    def _qunlock(self):
        self.__lock.release()

    def _qsubmit(self, job, priority):
        if not self.__queue.has_key(priority):
            self.__queue[priority] = []

        self.__queue[priority].append(job)
        self.__counter.release()

    def _queue_clear_below(self, priority):
        for i in range(0, priority):
            if self.__queue.has_key(i) and len(self.__queue[i]) != 0:
                return False

        return True

    def _qlock_when_idle(self, priority=10):
        while True:
            DBG("Attempting queue lock (%i)" % len(self.__queue))
            self._qlock()
            if self._queue_clear_below(priority):
                return
            self._qunlock()
            time.sleep(0.1)

    # This is the external lock, which stops any threads from running
    # so that the radio can be operated synchronously
    def lock(self):
        self.__runlock.acquire()

    def unlock(self):
        self.__runlock.release()

    def submit(self, job, priority=0):
        self._qlock()
        self._qsubmit(job, priority)
        self._qunlock()

    def flush(self, priority=None):
        self._qlock()

        if priority is None:
            for i in self.__queue.keys():
                self.__queue[i] = []
        else:
            self.__queue[priority] = []

        self._qunlock()

    def stop(self):
        self.flush()
        self.__counter.release()
        self.__enabled = False
    
    def status(self, msg):
        jobs = 0
        for i in dict(self.__queue):
                jobs += len(self.__queue[i])
        gobject.idle_add(self.emit, "status", "[%i] %s" % (jobs, msg))
            
    def _queue_pop(self, priority):
        try:
            return self.__queue[priority].pop(0)
        except IndexError:
            return None

    def run(self):
        last_job_desc = "idle"
        while self.__enabled:
            DBG("Waiting for a job")
            if last_job_desc:
                self.status("Completed " + last_job_desc + " (idle)")
            self.__counter.acquire()

            self._qlock()
            for i in sorted(self.__queue.keys()):
                job = self._queue_pop(i)
                if job:
                    DBG("Running job at priority %i" % i)
                    break
            self._qunlock()
            
            if job:
                self.lock()
                self.status(job.desc)
                job.execute(self.radio)
                last_job_desc = job.desc
                self.unlock()
   
        print "RadioThread exiting"

def log_exception():
	import traceback
	import sys

	print "-- Exception: --"
	traceback.print_exc(limit=30, file=sys.stdout)
	print "------"

def show_error(msg, parent=None):
    d = gtk.MessageDialog(buttons=gtk.BUTTONS_OK, parent=parent,
                          type=gtk.MESSAGE_ERROR)
    d.set_property("text", msg)

    if not parent:
        d.set_position(gtk.WIN_POS_CENTER_ALWAYS)

    d.run()
    d.destroy()

def ask_yesno_question(msg, parent=None):
    d = gtk.MessageDialog(buttons=gtk.BUTTONS_YES_NO, parent=parent,
                          type=gtk.MESSAGE_QUESTION)
    d.set_property("text", msg)

    if not parent:
        d.set_position(gtk.WIN_POS_CENTER_ALWAYS)

    r = d.run()
    d.destroy()

    return r == gtk.RESPONSE_YES

def combo_select(box, value):
    store = box.get_model()
    iter = store.get_iter_first()
    while iter:
        if store.get(iter, 0)[0] == value:
            box.set_active_iter(iter)
            return True
        iter = store.iter_next(iter)

    return False
