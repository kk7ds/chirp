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

from chirp import errors
from chirpui import common

class ImportDialog(gtk.Dialog):

    def _toggle(self, rend, path, col):
        self.__store[path][col] = not self.__store[path][col]

    def _edited(self, rend, path, new, col):
        iter = self.__store.get_iter(path)
        nloc, = self.__store.get(iter, self.col_nloc)

        try:
            val = int(new)
        except ValueError:
            common.show_error("Invalid value.  Must be an integer.")
            return

        try:
            self.dst_radio.get_memory(val)

            d = gtk.MessageDialog(parent=self,
                                  buttons=gtk.BUTTONS_YES_NO)
            d.set_property("text", "Overwrite location %i?" % val)
            resp = d.run()
            d.destroy()
            if resp == gtk.RESPONSE_NO:
                return
        except errors.InvalidMemoryLocation:
            print "No location %i to overwrite" % val

        self.__store.set(iter, col, val)

    def get_import_list(self):
        import_list = []
        iter = self.__store.get_iter_first()
        while iter:
            old, new, enb = self.__store.get(iter,
                                             self.col_oloc,
                                             self.col_nloc,
                                             self.col_import)
            if enb:
                import_list.append((old, new))
            iter = self.__store.iter_next(iter)

        return import_list

    def do_import(self):
        i = 0

        for old, new in self.get_import_list():
            print "Importing %i -> %i" % (old, new)
            mem = self.src_radio.get_memory(old)
            mem.number = new
            self.dst_radio.set_memory(mem)
            i += 1

        return i

    def make_view(self):
        editable = [self.col_nloc]

        self.__store = gtk.ListStore(gobject.TYPE_BOOLEAN,
                                     gobject.TYPE_INT,
                                     gobject.TYPE_INT,
                                     gobject.TYPE_STRING,
                                     gobject.TYPE_DOUBLE)
        self.__view = gtk.TreeView(self.__store)
        self.__view.show()

        for k in self.caps.keys():
            t = self.types[k]

            if t == gobject.TYPE_BOOLEAN:
                rend = gtk.CellRendererToggle()
                rend.connect("toggled", self._toggle, k)
                column = gtk.TreeViewColumn(self.caps[k], rend, active=k)
            else:
                rend = gtk.CellRendererText()
                if k in editable:
                    rend.set_property("editable", True)
                    rend.connect("edited", self._edited, k)
                column = gtk.TreeViewColumn(self.caps[k], rend, text=k)

            column.set_sort_column_id(k)
            self.__view.append_column(column)
        
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.__view)
        sw.show()

        return sw
        
    def build_ui(self):
        self.vbox.pack_start(self.make_view(), 1, 1, 1)

    def populate_list(self, radio):
        for mem in radio.get_memories():
            self.__store.append(row=(True,
                                     mem.number,
                                     mem.number,
                                     mem.name,
                                     mem.freq))

    TITLE = "Import From File"

    def __init__(self, src_radio, dst_radio):
        self.col_import = 0
        self.col_nloc = 1
        self.col_oloc = 2
        self.col_name = 3
        self.col_freq = 4

        self.caps = {
            self.col_import : "Import",
            self.col_nloc   : "New location",
            self.col_oloc   : "Location",
            self.col_name   : "Name",
            self.col_freq   : "Frequency",
            }

        self.types = {
            self.col_import : gobject.TYPE_BOOLEAN,
            self.col_oloc   : gobject.TYPE_INT,
            self.col_nloc   : gobject.TYPE_INT,
            self.col_name   : gobject.TYPE_STRING,
            self.col_freq   : gobject.TYPE_DOUBLE,
            }

        gtk.Dialog.__init__(self,
                            buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK,
                                     gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL),
                            title=self.TITLE)

        self.build_ui()
        self.set_default_size(400,300)
        self.populate_list(src_radio)
        self.src_radio = src_radio
        self.dst_radio = dst_radio

if __name__ == "__main__":
    from chirpui import editorset
    import sys

    f = sys.argv[1]
    rc = editorset.radio_class_from_file(f)
    radio = rc(f)

    d = ImportDialog(radio)
    d.run()

    print d.get_import_list()
