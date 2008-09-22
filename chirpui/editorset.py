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

from chirp import ic2820, ic2200, id800, ic9x, chirp_common
from chirpui import memedit, dstaredit, common

def radio_class_from_file(filename):
    size = os.stat(filename).st_size

    for cls in [ic2820.IC2820Radio, ic2200.IC2200Radio, id800.ID800v2Radio]:
        # pylint: disable-msg=W0212
        if cls._memsize == size:
            return cls

    raise Exception("Unknown file format")

class EditorSet(gtk.VBox):
    __gsignals__ = {
        "want-close" : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
        "status" : (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE,
                    (gobject.TYPE_STRING,))
        }

    def __init__(self, source):
        gtk.VBox.__init__(self, True, 0)

        if isinstance(source, str):
            self.filename = source
            rclass = radio_class_from_file(self.filename)
            self.radio = rclass(self.filename)
        elif isinstance(source, chirp_common.IcomRadio):
            self.radio = source
            self.filename = "IC9x (live)"
        else:
            raise Exception("Unknown source type")

        self.rthread = common.RadioThread(self.radio)
        self.rthread.start()

        self.rthread.connect("status", lambda e, m: self.emit("status", m))

        self.tabs = gtk.Notebook()
        self.tabs.set_tab_pos(gtk.POS_LEFT)

        if isinstance(self.radio, chirp_common.IcomDstarRadio):
            self.memedit = memedit.DstarMemoryEditor(self.rthread)
            self.dstared = dstaredit.DStarEditor(self.rthread)
        else:
            print "Starting memedit"
            self.memedit = memedit.MemoryEditor(self.rthread)
            print "Started"
            self.dstared = None

        lab = gtk.Label("Memories")
        self.tabs.append_page(self.memedit.root, lab)
        self.memedit.root.show()

        if self.dstared:
            lab = gtk.Label("D-STAR")
            self.tabs.append_page(self.dstared.root, lab)
            self.dstared.root.show()

        self.pack_start(self.tabs)
        self.tabs.show()

        # pylint: disable-msg=E1101
        self.memedit.connect("changed", self.editor_changed)

        self.label = self.text_label = None
        self.make_label()
        self.modified = False
        self.update_tab()

    def make_label(self):
        self.label = gtk.HBox(False, 0)

        self.text_label = gtk.Label("")
        self.text_label.show()
        self.label.pack_start(self.text_label, 1, 1, 1)

        button = gtk.Button("X")
        button.set_relief(gtk.RELIEF_NONE)
        button.connect("clicked", lambda x: self.emit("want-close"))
        button.show()
        self.label.pack_start(button, 0, 0, 0)

        self.label.show()

    def update_tab(self):
        fn = os.path.basename(self.filename)
        if self.modified:
            text = "%s*" % fn
        else:
            text = fn

        self.text_label.set_text(text)

    def save(self, fname=None):
        if not fname:
            fname = self.filename
        else:
            self.filename = fname

        self.rthread.lock()
        self.radio.save_mmap(fname)
        self.rthread.unlock()

        self.modified = False
        self.update_tab()

    def editor_changed(self, *args):
        if not isinstance(self.radio, ic9x.IC9xRadio):
            self.modified = True
            self.update_tab()

    def get_tab_label(self):
        return self.label

    def is_modified(self):
        return self.modified

