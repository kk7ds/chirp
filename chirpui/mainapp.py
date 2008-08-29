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

import os

import gtk
import gobject
gobject.threads_init()

import serial

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

from chirp import platform, chirp_common, id800, ic2820, ic2200, ic9x
import editorset
import clone

RADIOS = {
    "ic2820" : ic2820.IC2820Radio,
    "ic2200" : ic2200.IC2200Radio,
    "ic9x:A" : ic9x.IC9xRadioA,
    "ic9x:B" : ic9x.IC9xRadioB,
    "id800"  : id800.ID800v2Radio,
}

RTYPES = {}
for k,v in RADIOS.items():
    RTYPES[v] = k

class ChirpMain(gtk.Window):
    def get_current_editorset(self):
        try:
            return self.tabs.get_nth_page(self.tabs.get_current_page())
        except Exception, e:
            return None

    def ev_tab_switched(self):
        def set_action_sensitive(action, sensitive):
            self.menu_ag.get_action(action).set_sensitive(sensitive)

        w = self.get_current_editorset()

        if not w or isinstance(w.radio, ic9x.IC9xRadio):
            s = False
        else:
            s = True

        for i in ["save", "saveas", "close", "cloneout"]:
            set_action_sensitive(i, s)
        
    def do_open(self, fname=None):
        if not fname:
            fname = platform.get_platform().gui_open_file()
            if not fname:
                return

        try:
            e = editorset.EditorSet(fname)
        except Exception, e:
            print e
            return # FIXME

        tab = self.tabs.append_page(e, e.get_tab_label())
        e.show()

    def do_save(self):
        w = self.get_current_editorset()
        w.save()

    def cb_clonein(self, radio, fn):
        radio.pipe.close()
        self.do_open(fn)

    def cb_cloneout(self, radio, fn):
        radio.pipe.close()

    def do_clonein(self):
        d = clone.CloneSettingsDialog()
        r = d.run()
        port, rtype, fn = d.get_values()
        d.destroy()

        if r != gtk.RESPONSE_OK:
            return

        rc = RADIOS[rtype]
        s = serial.Serial(port=port, baudrate=rc.BAUD_RATE, timeout=0.25)
        radio = rc(s)

        ct = clone.CloneThread(radio, fn, cb=self.cb_clonein, parent=self)
        ct.start()

    def do_cloneout(self):
        w = self.get_current_editorset()
        radio = w.radio

        d = clone.CloneSettingsDialog(False,
                                      w.filename,
                                      RTYPES[radio.__class__])
        r = d.run()
        port, rtype, fn = d.get_values()
        d.destroy()

        if r != gtk.RESPONSE_OK:
            return

        rc = RADIOS[rtype]
        s = serial.Serial(port=port, baudrate=rc.BAUD_RATE, timeout=0.25)
        radio.set_pipe(s)

        ct = clone.CloneThread(radio, cb=self.cb_cloneout, parent=self)
        ct.start()

    def do_close(self):
        self.tabs.remove_page(self.tabs.get_current_page())

    def mh(self, _action):
        action = _action.get_name()

        if action == "quit":
            gtk.main_quit()
        elif action == "open":
            self.do_open()
        elif action == "save":
            self.do_save()
        elif action == "clonein":
            self.do_clonein()
        elif action == "cloneout":
            self.do_cloneout()
        elif action == "close":
            self.do_close()

    def make_menubar(self):
        menu_xml = """
<ui>
  <menubar name="MenuBar">
    <menu action="file">
      <menuitem action="open"/>
      <menuitem action="save"/>
      <menuitem action="saveas"/>
      <menuitem action="close"/>
      <menuitem action="quit"/>
    </menu>
    <menu action="radio">
      <menuitem action="clonein"/>
      <menuitem action="cloneout"/>
    </menu>
  </menubar>
</ui>
"""
        actions = [('file', None, "_File", None, None, self.mh),
                   ('open', None, "_Open", None, None, self.mh),
                   ('save', None, "_Save", None, None, self.mh),
                   ('saveas', None, "Save _As", None, None, self.mh),
                   ('close', None, "_Close", None, None, self.mh),
                   ('quit', None, "_Quit", None, None, self.mh),
                   ('radio', None, "_Radio", None, None, self.mh),
                   ('clonein', None, "Clone _In", None, None, self.mh),
                   ('cloneout', None, "Clone _Out", None, None, self.mh),
                   ]

        uim = gtk.UIManager()
        self.menu_ag = gtk.ActionGroup("MenuBar")
        self.menu_ag.add_actions(actions)

        uim.insert_action_group(self.menu_ag, 0)
        uim.add_ui_from_string(menu_xml)

        return uim.get_widget("/MenuBar")

    def make_tabs(self):
        self.tabs = gtk.Notebook()

        return self.tabs        

    def __init__(self, *args, **kwargs):
        gtk.Window.__init__(self, *args, **kwargs)

        vbox = gtk.VBox(False, 2)

        mbar = self.make_menubar()
        mbar.show()
        vbox.pack_start(mbar, 0,0,0)

        tabs = self.make_tabs()
        tabs.connect("switch-page", lambda n,_,p: self.ev_tab_switched())
        tabs.show()
        self.ev_tab_switched()

        vbox.pack_start(tabs, 1,1,1)

        vbox.show()

        self.add(vbox)

        self.set_default_size(640, 480)
        self.set_title("CHIRP")

        self.connect("delete_event", lambda w,e: gtk.main_quit())
        self.connect("destroy", lambda w: gtk.main_quit())

if __name__ == "__main__":
    w = ChirpMain()
    w.show()

    gtk.main()
