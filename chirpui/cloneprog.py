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
        if "parent" in args:
            parent = args["parent"]
            del args["parent"]
        else:
            parent = None

        if "cancel" in args:
            cancel = args["cancel"]
            del args["cancel"]
        else:
            cancel = None

        gtk.Window.__init__(self, **args)

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
        self.set_position(gtk.WIN_POS_CENTER_ON_PARENT)

        vbox = gtk.VBox(False, 2)
        vbox.show()
        self.add(vbox)

        self.set_title(_("Clone Progress"))
        self.set_resizable(False)

        self.infolabel = gtk.Label(_("Cloning"))
        self.infolabel.show()
        vbox.pack_start(self.infolabel, 1, 1, 1)

        self.progbar = gtk.ProgressBar()
        self.progbar.set_fraction(0.0)
        self.progbar.show()
        vbox.pack_start(self.progbar, 0, 0, 0)

        cancel_b = gtk.Button(_("Cancel"))
        cancel_b.connect("clicked", lambda b: cancel())
        cancel_b.show()
        vbox.pack_start(cancel_b, 0, 0, 0)

    def status(self, _status):
        self.infolabel.set_text(_status.msg)

        if _status.cur > _status.max:
            _status.cur = _status.max
        self.progbar.set_fraction(_status.cur / float(_status.max))
