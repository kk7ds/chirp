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
import pango

import threading
import time
import os
import traceback

from chirp import errors
from chirpui import reporting

class Editor(gobject.GObject):
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
        'usermsg' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                     (gobject.TYPE_STRING,)),
        }

    root = None

    def __init__(self):
        gobject.GObject.__init__(self)
        self._focused = False

    def is_focused(self):
        return self._focused

    def focus(self):
        self._focused = True

    def unfocus(self):
        self._focused = False

    def copy_selection(self, cut=False):
        pass

    def paste_selection(self):
        pass

    def hotkey(self, action):
        pass

gobject.type_register(Editor)

def DBG(*args):
    if False:
        print " ".join(args)

VERBOSE = False

class RadioJob:
    def __init__(self, cb, func, *args, **kwargs):
        self.cb = cb
        self.cb_args = ()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.desc = "Working"
        self.target = None
        self.tb = traceback.format_stack()

    def __str__(self):
        return "RadioJob(%s,%s,%s)" % (self.func, self.args, self.kwargs)

    def set_desc(self, desc):
        self.desc = desc

    def set_cb_args(self, *args):
        self.cb_args = args

    def set_target(self, target):
        self.target = target

    def _execute(self, target, func):
        try:
            DBG("Running %s (%s %s)" % (self.func,
                                        str(self.args),
                                        str(self.kwargs)))
            if VERBOSE:
                print self.desc
            result = func(*self.args, **self.kwargs)
        except errors.InvalidMemoryLocation, e:
            result = e
        except Exception, e:
            print "Exception running RadioJob: %s" % e
            log_exception()
            print "Job Args:   %s" % str(self.args)
            print "Job KWArgs: %s" % str(self.kwargs)
            print "Job Called from:%s%s" % (os.linesep, "".join(self.tb[:-1]))
            result = e

        if self.cb:
            gobject.idle_add(self.cb, result, *self.cb_args)

    def execute(self, radio):
        if not self.target:
            self.target = radio

        try:
            func = getattr(self.target, self.func)
        except AttributeError, e:
            print "No such radio function `%s' in %s" % (self.func,
                                                         self.target)
            return

        self._execute(self.target, func)

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
                self.status(_("Completed") + " " + last_job_desc + \
                                " (" + _("idle") + ")")
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

        reporting.report_exception(traceback.format_exc(limit=30))

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

def show_error_text(msg, text, parent=None):
    d = gtk.MessageDialog(buttons=gtk.BUTTONS_OK, parent=parent,
                          type=gtk.MESSAGE_ERROR)
    d.set_property("text", msg)

    v = gtk.TextView()
    v.get_buffer().set_text(text)
    v.show()
    sw = gtk.ScrolledWindow()
    sw.add(v)
    sw.show()
    d.vbox.pack_start(sw, 1,1,1)

    if not parent:
        d.set_position(gtk.WIN_POS_CENTER_ALWAYS)

    d.set_size_request(600, 400)
    d.run()
    d.destroy()

def simple_diff(a, b):
    lines_a = a.split(os.linesep)
    lines_b = b.split(os.linesep)

    diff = ""
    for i in range(0, len(lines_a)):
        if lines_a[i] != lines_b[i]:
            diff += "-%s%s" % (lines_a[i], os.linesep)
            diff += "+%s%s" % (lines_b[i], os.linesep)
        else:
            diff += " %s%s" % (lines_a[i], os.linesep)
    return diff

# A quick hacked up tool to show a blob of text in a dialog window
# using fixed-width fonts. It also highlights lines that start with
# a '-' in red bold font and '+' with blue bold font.
def show_diff_blob(title, result):
    d = gtk.Dialog(title=title,
                   buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK))
    b = gtk.TextBuffer()

    tags = b.get_tag_table()
    for color in ["red", "blue", "green", "grey"]:
        tag = gtk.TextTag(color)
        tag.set_property("foreground", color)
        tags.add(tag)
    tag = gtk.TextTag("bold")
    tag.set_property("weight", pango.WEIGHT_BOLD)
    tags.add(tag)

    lines = result.split(os.linesep)
    for line in lines:
        if line.startswith("-"):
            tags = ("red", "bold")
        elif line.startswith("+"):
            tags = ("blue", "bold")
        else:
            tags = ()
        b.insert_with_tags_by_name(b.get_end_iter(), line + os.linesep, *tags)
    v = gtk.TextView(b)
    fontdesc = pango.FontDescription("Courier 11")
    v.modify_font(fontdesc)
    v.set_editable(False)
    v.show()
    s = gtk.ScrolledWindow()
    s.add(v)
    s.show()
    d.vbox.pack_start(s, 1, 1, 1)
    d.set_size_request(600, 400)
    d.run()
    d.destroy()

