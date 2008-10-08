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

from chirpui import common, miscwidgets

WIDGETW = 80
WIDGETH = 30

class CallsignEditor(gtk.HBox):
    __gsignals__ = {
        "changed" : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
        }

    def __add_cb(self, button, entry):
        call = entry.get_text().upper()
        if call:
            self.listw.add_item(call)
            entry.set_text("")
            self.emit("changed")

    def __del_cb(self, button):
        self.listw.remove_selected()
        self.emit("changed")

    def __mov_cb(self, button, delta):
        self.listw.move_selected(delta)
        self.emit("changed")

    def make_controls(self):
        vbox = gtk.VBox(False, 2)

        entry = gtk.Entry(8)
        entry.set_size_request(WIDGETW, WIDGETH)
        entry.show()
        vbox.pack_start(entry, 0, 0, 0)

        addbtn = gtk.Button(stock=gtk.STOCK_ADD)
        addbtn.connect("clicked", self.__add_cb, entry)
        addbtn.set_size_request(WIDGETW, WIDGETH)
        addbtn.show()
        vbox.pack_start(addbtn, 0, 0, 0)

        delbtn = gtk.Button(stock=gtk.STOCK_REMOVE)
        delbtn.connect("clicked", self.__del_cb)
        delbtn.set_size_request(WIDGETW, WIDGETH)
        delbtn.show()
        vbox.pack_start(delbtn, 0, 0, 0)
        
        mupbtn = gtk.Button("Move up")
        mupbtn.connect("clicked", self.__mov_cb, 1)
        mupbtn.set_size_request(WIDGETW, WIDGETH)
        mupbtn.show()
        vbox.pack_start(mupbtn, 0, 0, 0)

        mdnbtn = gtk.Button("Move down")
        mdnbtn.connect("clicked", self.__mov_cb, -1)
        mdnbtn.set_size_request(WIDGETW, WIDGETH)
        mdnbtn.show()
        vbox.pack_start(mdnbtn, 0, 0, 0)

        vbox.show()

        return vbox

    def make_list(self):
        cols = [ (gobject.TYPE_STRING, "Callsign") ]

        self.listw = miscwidgets.ListWidget(cols)
        self.listw.show()

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(self.listw)
        sw.show()
        
        return sw

    def __init__(self):
        gtk.HBox.__init__(self, False, 2)

        self.listw = None

        self.pack_start(self.make_list(), 1, 1, 1)
        self.pack_start(self.make_controls(), 0, 0, 0)

    def set_callsigns(self, calls):
        values = [(x,) for x in calls]
        self.listw.set_values(values)

    def get_callsigns(self):
        values = self.listw.get_values()
        return [x for x, in values]

class DStarEditor(common.Editor):
    def __cs_changed(self, cse):
        job = None

        print "Callsigns: %s" % cse.get_callsigns()
        if cse == self.editor_ucall:
            job = common.RadioJob(None,
                                  "set_urcall_list",
                                  cse.get_callsigns())
            print "Set urcall"
        elif cse == self.editor_rcall:
            job = common.RadioJob(None,
                                  "set_repeater_call_list",
                                  cse.get_callsigns())
            print "Set rcall"

        if job:
            print "Submitting job to update call lists"
            self.rthread.submit(job)

        self.emit("changed")

    def make_callsigns(self):
        box = gtk.HBox(True, 2)

        frame = gtk.Frame("Your callsign")
        self.editor_ucall = CallsignEditor()
        self.editor_ucall.set_size_request(-1, 200)
        self.editor_ucall.show()
        frame.add(self.editor_ucall)
        frame.show()
        box.pack_start(frame, 1, 1, 0)

        job = common.RadioJob(self.editor_ucall.set_callsigns,
                              "get_urcall_list")
        job.set_desc("Downloading URCALL list")
        self.rthread.submit(job)

        self.editor_ucall.connect("changed", self.__cs_changed)

        frame = gtk.Frame("Repeater callsign")
        self.editor_rcall = CallsignEditor()
        self.editor_rcall.set_size_request(-1, 200)
        self.editor_rcall.show()
        frame.add(self.editor_rcall)
        frame.show()
        box.pack_start(frame, 1, 1, 0)

        job = common.RadioJob(self.editor_rcall.set_callsigns,
                              "get_repeater_call_list")
        job.set_desc("Downloading RPTCALL list")
        self.rthread.submit(job)

        self.editor_rcall.connect("changed", self.__cs_changed)

        box.show()
        return box

    def __init__(self, rthread):
        common.Editor.__init__(self)
        self.rthread = rthread

        self.editor_ucall = self.editor_rcall = None

        vbox = gtk.VBox(False, 2)
        vbox.pack_start(self.make_callsigns(), 0, 0, 0)        

        tmp = gtk.Label("")
        tmp.show()
        vbox.pack_start(tmp, 1, 1, 1)

        self.root = vbox
