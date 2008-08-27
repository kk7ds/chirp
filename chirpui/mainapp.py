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

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

from chirp import platform, chirp_common
import editorset

class ChirpMain(gtk.Window):
    def do_open(self):
        fname = platform.get_platform().gui_open_file()
        if not fname:
            return

        try:
            e = editorset.EditorSet(fname)
        except Exception, e:
            print e
            return # FIXME

        tab = self.tabs.append_page(e, gtk.Label(e.get_tab_title()))
        e.show()

    def do_save(self):
        w = self.tabs.get_nth_page(self.tabs.get_current_page())
        w.save()

    def mh(self, _action):
        action = _action.get_name()

        if action == "quit":
            gtk.main_quit()
        elif action == "open":
            self.do_open()
        elif action == "save":
            self.do_save()

    def make_menubar(self):
        menu_xml = """
<ui>
  <menubar name="MenuBar">
    <menu action="file">
      <menuitem action="open"/>
      <menuitem action="save"/>
      <menuitem action="saveas"/>
      <menuitem action="clonein"/>
      <menuitem action="cloneout"/>
      <menuitem action="quit"/>
    </menu>
  </menubar>
</ui>
"""
        actions = [('file', None, "_File", None, None, self.mh),
                   ('open', None, "_Open", None, None, self.mh),
                   ('save', None, "_Save", None, None, self.mh),
                   ('saveas', None, "Save _As", None, None, self.mh),
                   ('clonein', None, "Clone _In", None, None, self.mh),
                   ('cloneout', None, "Clone _Out", None, None, self.mh),
                   ('quit', None, "_Quit", None, None, self.mh),
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
        tabs.show()
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
