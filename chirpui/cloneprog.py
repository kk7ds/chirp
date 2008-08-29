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

class CloneProg(gtk.Window):
    def __init__(self, **args):
        if args.has_key("parent"):
            parent = args["parent"]
            del args["parent"]
        else:
            parent = None

        gtk.Window.__init__(self, **args)

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)

        vbox = gtk.VBox(False, 2)
        vbox.show()
        self.add(vbox)

        self.set_title("Clone Progress")
        self.set_resizable(False)

        self.infolabel = gtk.Label("Cloning")
        self.infolabel.show()
        vbox.pack_start(self.infolabel, 1,1,1)

        self.progbar = gtk.ProgressBar()
        self.progbar.set_fraction(0.0)
        self.progbar.show()
        vbox.pack_start(self.progbar, 0,0,0)

    def status(self, s):
        self.infolabel.set_text(s.msg)

        if s.cur > s.max:
            s.cur = s.max
        self.progbar.set_fraction(s.cur / float(s.max))

if __name__ == "__main__":
    w = CloneProg()
    w.show()

    gtk.main()
