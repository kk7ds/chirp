#!/usr/bin/python
#
# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

# README:
#
# I know that collecting data is not very popular.  I don't like it
# either.  However, it's hard to tell what drivers people are using
# and I think it would be helpful if I had that information.  This is
# completely optional, so you can turn it off if you want.  It doesn't
# report anything other than version and model usage information.  The
# code below is very conservative, and will disable itself if reporting
# fails even once or takes too long to perform.  It's run in a thread
# so that the user shouldn't even notice it's happening.
#

import threading
import os
import time

from chirp import CHIRP_VERSION, platform

REPORT_URL = "http://chirp.danplanet.com/report/report.php?do_report"
ENABLED = True
DEBUG = os.getenv("CHIRP_DEBUG") == "y"
THREAD_SEM = threading.Semaphore(10) # Maximum number of outstanding threads
LAST = 0

try:
    # Don't let failure to import any of these modules cause trouble
    from chirpui import config
    import xmlrpclib
except:
    ENABLED = False

def debug(string):
    if DEBUG:
        print string

def should_report():
    if not ENABLED:
        debug("Not reporting due to recent failure")
        return False

    conf = config.get()
    if conf.get_bool("no_report"):
        debug("Reporting disabled")
        return False

    return True

def _report_model_usage(model, direction, success):
    global ENABLED
    if direction not in ["live", "download", "upload", "import", "export"]:
        print "Invalid direction `%s'" % direction
        return True # This is a bug, but not fatal

    model = "%s_%s" % (model.VENDOR, model.MODEL)
    data = "%s,%s,%s" % (model, direction, success)

    debug("Reporting model usage: %s" % data)

    proxy = xmlrpclib.ServerProxy(REPORT_URL)
    id = proxy.report_stats(CHIRP_VERSION,
                            platform.get_platform().os_version_string(),
                            "model_use",
                            data)

    # If the server returns zero, it wants us to shut up
    return id != 0

def _report_exception(stack):
    global ENABLED

    debug("Reporting exception")

    proxy = xmlrpclib.ServerProxy(REPORT_URL)
    id = proxy.report_exception(CHIRP_VERSION,
                                platform.get_platform().os_version_string(),
                                "exception",
                                stack)

    # If the server returns zero, it wants us to shut up
    return id != 0

class ReportThread(threading.Thread):
    def __init__(self, func, *args):
        threading.Thread.__init__(self)
        self.__func = func
        self.__args = args

    def _run(self):
        try:
            return self.__func(*self.__args)
        except Exception, e:
            debug("Failed to report: %s" % e)
            return False
        
    def run(self):
        start = time.time()
        result = self._run()
        if not result:
            # Reporting failed
            ENABLED = False
        elif (time.time() - start) > 15:
            # Reporting took too long
            debug("Time to report was %.2f sec -- Disabling" % \
                      (time.time()-start))
            ENABLED = False

        THREAD_SEM.release()

def dispatch_thread(func, *args):
    global LAST

    # If reporting is disabled or failing, bail
    if not should_report():
        debug("Reporting is disabled")
        return

    # If the time between now and the last report is less than 5 seconds, bail
    delta = time.time() - LAST
    LAST = time.time()
    if delta < 5:
        debug("Throttling...")
        return

    # If there are already too many threads running, bail
    if not THREAD_SEM.acquire(False):
        debug("Too many threads already running")
        return

    t = ReportThread(func, *args)
    t.start()

def report_model_usage(model, direction, success):
    dispatch_thread(_report_model_usage, model, direction, success)

def report_exception(stack):
    dispatch_thread(_report_exception, stack)
