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
import logging

from chirp.ui import common, miscwidgets

LOG = logging.getLogger(__name__)

WIDGETW = 80
WIDGETH = 30


class CallsignEditor(gtk.HBox):
    __gsignals__ = {
        "changed": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
        }

    def _cs_changed(self, listw, callid):
        if callid == 0 and self.first_fixed:
            return False

        self.emit("changed")

        return True

    def make_list(self, width):
        cols = [(gobject.TYPE_INT, ""),
                (gobject.TYPE_INT, ""),
                (gobject.TYPE_STRING, _("Callsign")),
                ]

        self.listw = miscwidgets.KeyedListWidget(cols)
        self.listw.show()

        self.listw.set_editable(1, True)
        self.listw.connect("item-set", self._cs_changed)

        rend = self.listw.get_renderer(1)
        rend.set_property("family", "Monospace")
        rend.set_property("width-chars", width)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(self.listw)
        sw.show()

        return sw

    def __init__(self, first_fixed=False, width=8):
        gtk.HBox.__init__(self, False, 2)

        self.first_fixed = first_fixed

        self.listw = None

        self.pack_start(self.make_list(width), 1, 1, 1)

    def set_callsigns(self, calls):
        if self.first_fixed:
            st = 1
        else:
            st = 0

        values = []
        i = 1
        for call in calls[st:]:
            self.listw.set_item(i, i, call)
            i += 1

    def get_callsigns(self):
        calls = []
        keys = self.listw.get_keys()
        for key in keys:
            id, idx, call = self.listw.get_item(key)
            calls.append(call)

        if self.first_fixed:
            calls.insert(0, "")

        return calls


class DStarEditor(common.Editor):
    def __cs_changed(self, cse):
        job = None

        LOG.debug("Callsigns: %s" % cse.get_callsigns())
        if cse == self.editor_ucall:
            job = common.RadioJob(None,
                                  "set_urcall_list",
                                  cse.get_callsigns())
            LOG.debug("Set urcall")
        elif cse == self.editor_rcall:
            job = common.RadioJob(None,
                                  "set_repeater_call_list",
                                  cse.get_callsigns())
            LOG.debug("Set rcall")
        elif cse == self.editor_mcall:
            job = common.RadioJob(None,
                                  "set_mycall_list",
                                  cse.get_callsigns())

        if job:
            LOG.debug("Submitting job to update call lists")
            self.rthread.submit(job)

        self.emit("changed")

    def make_callsigns(self):
        box = gtk.HBox(True, 2)

        fixed = self.rthread.radio.get_features().has_implicit_calls

        frame = gtk.Frame(_("Your callsign"))
        self.editor_ucall = CallsignEditor(first_fixed=fixed)
        self.editor_ucall.set_size_request(-1, 200)
        self.editor_ucall.show()
        frame.add(self.editor_ucall)
        frame.show()
        box.pack_start(frame, 1, 1, 0)

        frame = gtk.Frame(_("Repeater callsign"))
        self.editor_rcall = CallsignEditor(first_fixed=fixed)
        self.editor_rcall.set_size_request(-1, 200)
        self.editor_rcall.show()
        frame.add(self.editor_rcall)
        frame.show()
        box.pack_start(frame, 1, 1, 0)

        frame = gtk.Frame(_("My callsign"))
        self.editor_mcall = CallsignEditor()
        self.editor_mcall.set_size_request(-1, 200)
        self.editor_mcall.show()
        frame.add(self.editor_mcall)
        frame.show()
        box.pack_start(frame, 1, 1, 0)

        box.show()
        return box

    def focus(self):
        if self.loaded:
            return
        self.loaded = True
        LOG.debug("Loading callsigns...")

        def set_ucall(calls):
            self.editor_ucall.set_callsigns(calls)
            self.editor_ucall.connect("changed", self.__cs_changed)

        def set_rcall(calls):
            self.editor_rcall.set_callsigns(calls)
            self.editor_rcall.connect("changed", self.__cs_changed)

        def set_mcall(calls):
            self.editor_mcall.set_callsigns(calls)
            self.editor_mcall.connect("changed", self.__cs_changed)

        job = common.RadioJob(set_ucall, "get_urcall_list")
        job.set_desc(_("Downloading URCALL list"))
        self.rthread.submit(job)

        job = common.RadioJob(set_rcall, "get_repeater_call_list")
        job.set_desc(_("Downloading RPTCALL list"))
        self.rthread.submit(job)

        job = common.RadioJob(set_mcall, "get_mycall_list")
        job.set_desc(_("Downloading MYCALL list"))
        self.rthread.submit(job)

    def __init__(self, rthread):
        super(DStarEditor, self).__init__(rthread)

        self.loaded = False

        self.editor_ucall = self.editor_rcall = None

        vbox = gtk.VBox(False, 2)
        vbox.pack_start(self.make_callsigns(), 0, 0, 0)

        tmp = gtk.Label("")
        tmp.show()
        vbox.pack_start(tmp, 1, 1, 1)

        self.root = vbox
