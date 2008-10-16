import gtk
import gobject

import threading

from chirp import errors

class Editor(gobject.GObject):
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
        }

    root = None

    def __init__(self):
        gobject.GObject.__init__(self)

gobject.type_register(Editor)

class RadioJob:
    def __init__(self, cb, func, *args, **kwargs):
        self.cb = cb
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.desc = "Working"

    def set_desc(self, desc):
        self.desc = desc

    def execute(self, radio):
        try:
            func = getattr(radio, self.func)
        except AttributeError, e:
            print "No such radio function `%s'" % self.func
            return

        try:
            print "Running %s (%s %s)" % (self.func,
                                          str(self.args),
                                          str(self.kwargs))
            result = func(*self.args, **self.kwargs)
        except errors.InvalidMemoryLocation, e:
            result = e
        except Exception, e:
            print "Exception running RadioJob: %s" % e
            log_exception()
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
        self.__queue = []
        self.__counter = threading.Semaphore(0)
        self.__enabled = True
        self.__lock = threading.Lock()
        self.radio = radio

    def lock(self):
        self.__lock.acquire()

    def unlock(self):
        self.__lock.release()

    def submit(self, job):
        self.lock()
        self.__queue.append(job)
        self.unlock()
        self.__counter.release()

    def flush(self):
        self.lock()
        self.__queue = []
        self.unlock()

    def stop(self):
        self.flush()
        self.__counter.release()
        self.__enabled = False
    
    def __do_job(self, job):
        try:
            func = getattr(self.radio, job.func)
        except AttributeError, e:
            print "No such radio function `%s'" % job.func
            print e
            return

        try:
            result = func(*job.args, **job.kwargs)
            print "Finished, returning %s to %s" % (result, cb)
        except Exception, e:
            print "Exception in RadioThread: %s" % e
            log_exception()
            result = e

        if cb:
            gobject.idle_add(cb, result)

    def status(self, msg):
        gobject.idle_add(self.emit, "status", msg)
            
    def run(self):
        while self.__enabled:
            print "Waiting for a job"
            self.status("Idle")
            self.__counter.acquire()

            self.lock()
            try:
                job = self.__queue.pop(0)
            except IndexError:
                self.unlock()
                break

            self.unlock()
            
            self.status(job.desc)
            job.execute(self.radio)
    
        print "RadioThread exiting"

def log_exception():
	import traceback
	import sys

	print "-- Exception: --"
	traceback.print_exc(limit=30, file=sys.stdout)
	print "------"

def show_error(msg, title="Error"):
    d = gtk.MessageDialog(buttons=gtk.BUTTONS_OK)
    d.set_property("text", msg)
    d.run()
    d.destroy()
