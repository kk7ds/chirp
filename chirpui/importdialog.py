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
import pango

from chirp import errors, chirp_common
from chirpui import common

class ImportDialog(gtk.Dialog):

    def _check_for_dupe(self, location):
        iter = self.__store.get_iter_first()
        while iter:
            imp, loc = self.__store.get(iter, self.col_import, self.col_nloc)
            if imp and loc == location:
                return True
            iter = self.__store.iter_next(iter)

        return False

    def _toggle(self, rend, path, col):
        iter = self.__store.get_iter(path)
        imp, nloc = self.__store.get(iter, self.col_import, self.col_nloc)
        if not imp and self._check_for_dupe(nloc):
            d = gtk.MessageDialog(parent=self, buttons=gtk.BUTTONS_OK)
            d.set_property("text",
                           "Location %i is already being imported.  " % nloc + \
                               "Choose another value for 'New Location' " + \
                               "before selecting 'Import'")
            d.run()
            d.destroy()
        else:
            self.__store[path][col] = not imp

    def _render(self, _, rend, model, iter, colnum):
        newloc, imp = model.get(iter, self.col_nloc, self.col_import)

        if newloc in self.used_list and imp:
            rend.set_property("foreground", "red")
            rend.set_property("text", "%i" % newloc)
            rend.set_property("weight", pango.WEIGHT_BOLD)
        else:
            rend.set_property("foreground", "black")
            rend.set_property("weight", pango.WEIGHT_NORMAL)

    def _edited(self, rend, path, new, col):
        iter = self.__store.get_iter(path)
        nloc, = self.__store.get(iter, self.col_nloc)

        try:
            val = int(new)
        except ValueError:
            common.show_error("Invalid value.  Must be an integer.")
            return

        if val == nloc:
            return

        if self._check_for_dupe(val):
            d = gtk.MessageDialog(parent=self, buttons=gtk.BUTTONS_OK)
            d.set_property("text",
                           "Location %i is already being imported" % val)
            d.run()
            d.destroy()
            return

        self.record_use_of(val)

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

    def ensure_calls(self, dst_rthread, import_list):
        rlist_changed = False
        ulist_changed = False

        if not isinstance(self.dst_radio, chirp_common.IcomDstarRadio):
            return

        ulist = self.dst_radio.get_urcall_list()
        rlist = self.dst_radio.get_repeater_call_list()

        for old, new in import_list:
            mem = self.src_radio.get_memory(old)
            if isinstance(mem, chirp_common.DVMemory):
                if mem.dv_urcall not in ulist:
                    print "Adding %s to ucall list" % mem.dv_urcall
                    ulist.append(mem.dv_urcall)
                    ulist_changed = True
                if mem.dv_rpt1call not in rlist:
                    print "Adding %s to rcall list" % mem.dv_rpt1call
                    rlist.append(mem.dv_rpt1call)
                    rlist_changed = True
                if mem.dv_rpt2call not in rlist:
                    print "Adding %s to rcall list" % mem.dv_rpt2call
                    rlist.append(mem.dv_rpt2call)
                    rlist_changed = True
                
        if ulist_changed:
            job = common.RadioJob(None, "set_urcall_list", ulist)
            job.set_desc("Updating URCALL list")
            dst_rthread._qsubmit(job)

        if rlist_changed:
            job = common.RadioJob(None, "set_repeater_call_list", ulist)
            job.set_desc("Updating RPTCALL list")
            dst_rthread._qsubmit(job)
            
        return

    def do_import(self, dst_rthread):
        i = 0

        import_list = self.get_import_list()

        self.ensure_calls(dst_rthread, import_list)

        for old, new in import_list:
            print "%sing %i -> %i" % (self.ACTION, old, new)
            mem = self.src_radio.get_memory(old)
            mem.number = new

            job = common.RadioJob(None, "set_memory", mem)
            job.set_desc("Setting memory %i" % mem.number)
            dst_rthread._qsubmit(job)

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

            if k == self.col_nloc:
                column.set_cell_data_func(rend, self._render, k)

            column.set_sort_column_id(k)
            self.__view.append_column(column)
        
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.__view)
        sw.show()

        return sw

    def __select_all(self, button, state):
        iter = self.__store.get_iter_first()
        while iter:
            if state is None:
                _state, = self.__store.get(iter, self.col_import)
                _state = not _state
            else:
                _state = state
            self.__store.set(iter, self.col_import, _state)
            iter = self.__store.iter_next(iter)

    def make_select(self):
        hbox = gtk.HBox(True, 2)

        all = gtk.Button("All");
        all.connect("clicked", self.__select_all, True)
        all.set_size_request(50, 25)
        all.show()
        hbox.pack_start(all, 0, 0, 0)

        none = gtk.Button("None");
        none.connect("clicked", self.__select_all, False)
        none.set_size_request(50, 25)
        none.show()
        hbox.pack_start(none, 0, 0, 0)

        inv = gtk.Button("Inverse")
        inv.connect("clicked", self.__select_all, None)
        inv.set_size_request(50, 25)
        inv.show()
        hbox.pack_start(inv, 0, 0, 0)

        frame = gtk.Frame("Select")
        frame.show()
        frame.add(hbox)
        hbox.show()

        return frame

    def make_options(self):
        hbox = gtk.HBox(True, 2)

        confirm = gtk.CheckButton("Confirm overwrites")
        confirm.connect("toggled", __set_confirm)
        confirm.show()

        hbox.pack_start(confirm, 0, 0, 0)

        frame = gtk.Frame("Options")
        frame.add(hbox)
        frame.show()
        hbox.show()

        return frame

    def make_controls(self):
        hbox = gtk.HBox(True, 2)
        
        hbox.pack_start(self.make_select(), 0, 0, 0)
        #hbox.pack_start(self.make_options(), 0, 0, 0)
        hbox.show()

        return hbox

    def build_ui(self):
        self.vbox.pack_start(self.make_view(), 1, 1, 1)
        self.vbox.pack_start(self.make_controls(), 0, 0, 0)

    def record_use_of(self, number):
        try:
            self.dst_radio.get_memory(number)
            if number not in self.used_list:
                self.used_list.append(number)
        except errors.InvalidMemoryLocation:
            print "Location %i empty or at limit of destination radio" % number
            if number not in self.not_used_list:
                self.not_used_list.append(number)
        except errors.InvalidDataError, e:
            print "Got error from radio, assuming %i beyond limits: %s" % \
                (number, e)

    def populate_list(self, radio):
        for mem in radio.get_memories():
            self.__store.append(row=(True,
                                     mem.number,
                                     mem.number,
                                     mem.name,
                                     mem.freq))
            self.record_use_of(mem.number)


    TITLE = "Import From File"
    ACTION = "Import"

    def __init__(self, src_radio, dst_radio):
        gtk.Dialog.__init__(self,
                            buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK,
                                     gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL),
                            title=self.TITLE)

        self.col_import = 0
        self.col_nloc = 1
        self.col_oloc = 2
        self.col_name = 3
        self.col_freq = 4

        self.caps = {
            self.col_import : self.ACTION,
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

        self.src_radio = src_radio
        self.dst_radio = dst_radio

        self.used_list = []
        self.not_used_list = []

        self.build_ui()
        self.set_default_size(400, 300)
        self.populate_list(src_radio)

class ExportDialog(ImportDialog):
    TITLE = "Export To File"
    ACTION = "Export"

if __name__ == "__main__":
    from chirpui import editorset
    import sys

    f = sys.argv[1]
    rc = editorset.radio_class_from_file(f)
    radio = rc(f)

    d = ImportDialog(radio)
    d.run()

    print d.get_import_list()
