import gobject

import threading

class Editor(gobject.GObject):
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
        }

    root = None

    def __init__(self):
        gobject.GObject.__init__(self)

gobject.type_register(Editor)

class RadioThread(threading.Thread):
    def __init__(self, radio):
        threading.Thread.__init__(self)
        self.__queue = []
        self.__counter = threading.Semaphore(0)
        self.__enabled = True
        self.__lock = threading.Lock()
        self.radio = radio

    def lock(self):
        self.__lock.acquire()

    def unlock(self):
        self.__lock.release()

    def submit(self, cb, func, *args, **kwargs):
        self.lock()
        self.__queue.append((cb, func, args, kwargs))
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
    
    def __do_job(self, cb, fname, args, kwargs):
        print "Running %s" % fname

        try:
            func = getattr(self.radio, fname)
        except AttributeError, e:
            print "No such radio function `%s'" % fname
            print e
            return

        try:
            result = func(*args, **kwargs)
            print "Finished, returning %s to %s" % (result, cb)
        except Exception, e:
            print "Exception in RadioThread: %s" % e
            result = e

        if cb:
            cb(result)

    def run(self):
        while self.__enabled:
            print "Waiting for a job"
            self.__counter.acquire()
            print "Got a job"

            self.lock()
            cb, func, args, kwargs = self.__queue.pop(0)
            self.unlock()

            self.__do_job(cb, func, args, kwargs)
    
        print "RadioThread exiting"
