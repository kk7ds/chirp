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

from gobject import TYPE_INT, TYPE_STRING, TYPE_BOOLEAN

from chirp import chirp_common
from chirpui import common, miscwidgets

class BankNamesJob(common.RadioJob):
    def __init__(self, editor, cb):
        common.RadioJob.__init__(self, cb, None)
        self.__editor = editor

    def execute(self, radio):
        self.__editor.banks = []

        bm = radio.get_bank_model()
        banks = bm.get_banks()
        for bank in banks:
            self.__editor.banks.append((bank, bank.get_name()))

        gobject.idle_add(self.cb, *self.cb_args)

class BankNameEditor(common.Editor):
    def refresh(self):
        def got_banks():
            self._keys = []
            for bank, name in self.banks:
                self._keys.append(bank.get_index())
                self.listw.set_item(bank.get_index(),
                                    bank.get_index(),
                                    name)

            self.listw.connect("item-set", self.bank_changed)

        job = BankNamesJob(self, got_banks)
        job.set_desc(_("Retrieving bank information"))
        self.rthread.submit(job)

    def get_bank_list(self):
        banks = []
        keys = self.listw.get_keys()
        for key in keys:
            banks.append(self.listw.get_item(key)[2])

        return banks
    
    def bank_changed(self, listw, key):
        def cb(*args):
            self.emit("changed")

        name = self.listw.get_item(key)[2]
        bank, oldname = self.banks[self._keys.index(key)]

        def trigger_changed(*args):
            self.emit("changed")

        job = common.RadioJob(trigger_changed, "set_name", name)
        job.set_target(bank)
        job.set_desc(_("Setting name on bank"))
        self.rthread.submit(job)

        return True

    def __init__(self, rthread):
        common.Editor.__init__(self)
        self.rthread = rthread

        types = [(gobject.TYPE_STRING, "key"),
                 (gobject.TYPE_STRING, _("Bank")),
                 (gobject.TYPE_STRING, _("Name"))]

        self.listw = miscwidgets.KeyedListWidget(types)
        self.listw.set_editable(1, True)
        self.listw.set_sort_column(0, 1)
        self.listw.set_sort_column(1, -1)
        self.listw.show()

        self.banks = []

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(self.listw)

        self.root = sw
        self._loaded = False

    def focus(self):
        if self._loaded:
            return

        self.refresh()
        self._loaded = True

class MemoryBanksJob(common.RadioJob):
    def __init__(self, cb, number):
        common.RadioJob.__init__(self, cb, None)
        self.__number = number

    def execute(self, radio):
        mem = radio.get_memory(self.__number)
        if mem.empty:
            banks = []
            indexes = []
        else:
            bm = radio.get_bank_model()
            banks = bm.get_memory_banks(mem)
            indexes = []
            if isinstance(bm, chirp_common.BankIndexInterface):
                for bank in banks:
                    indexes.append(bm.get_memory_index(mem, bank))
        self.cb(mem, banks, indexes, *self.cb_args)
            
class BankMembershipEditor(common.Editor):
    def _number_to_path(self, number):
        return (number - self._rf.memory_bounds[0],)

    def _get_next_bank_index(self, bank):
        # NB: Only works for one-to-one bank models right now!
        iter = self._store.get_iter_first()
        indexes = []
        ncols = len(self._cols) + len(self.banks)
        while iter:
            vals = self._store.get(iter, *tuple([n for n in range(0, ncols)]))
            loc = vals[self.C_LOC]
            index = vals[self.C_INDEX]
            banks = vals[self.C_BANKS:]
            if True in banks and banks.index(True) == bank:
                indexes.append(index)
            iter = self._store.iter_next(iter)

        index_bounds = self.rthread.radio.get_bank_model().get_index_bounds()
        num_indexes = index_bounds[1] - index_bounds[0]
        indexes.sort()
        for i in range(0, num_indexes):
            if i not in indexes:
                return i + index_bounds[0] # In case not zero-origin index

        return 0 # If the bank is full, just wrap around!

    def _toggled_cb(self, rend, path, colnum):
        try:
            if not rend.get_sensitive():
                return
        except AttributeError:
            # support PyGTK < 2.22
            iter = self._store.get_iter(path)
            if not self._store.get(iter, self.C_FILLED)[0]:
                return

        # The bank index is the column number, minus the 3 label columns
        bank, name = self.banks[colnum - len(self._cols)]
        loc, = self._store.get(self._store.get_iter(path), self.C_LOC)

        if rend.get_active():
            # Changing from True to False
            fn = "remove_memory_from_bank"
            index = None
        else:
            # Changing from False to True
            fn = "add_memory_to_bank"
            if self._rf.has_bank_index:
                index = self._get_next_bank_index(colnum - len(self._cols))
            else:
                index = None

        def do_refresh_memory(*args):
            # Step 2: Update our notion of the memory's bank information
            self.refresh_memory(loc)

        def do_bank_index(result, memory):
            if isinstance(result, Exception):
                common.show_error("Failed to add {mem} to bank: {err}"
                                  .format(mem=memory.number,
                                          err=str(result)),
                                  parent=self.editorset.parent_window)
                return
            self.emit("changed")
            # Step 3: Set the memory's bank index (maybe)
            if not self._rf.has_bank_index or index is None:
                return do_refresh_memory()

            job = common.RadioJob(do_refresh_memory,
                                  "set_memory_index", memory, bank, index)
            job.set_target(self.rthread.radio.get_bank_model())
            job.set_desc(_("Updating bank index "
                           "for memory {num}").format(num=memory.number))
            self.rthread.submit(job)

        def do_bank_adjustment(memory):
            # Step 1: Do the bank add/remove
            job = common.RadioJob(do_bank_index, fn, memory, bank)
            job.set_target(self.rthread.radio.get_bank_model())
            job.set_cb_args(memory)
            job.set_desc(_("Updating bank information "
                           "for memory {num}").format(num=memory.number))
            self.rthread.submit(job)

        # Step 0: Fetch the memory
        job = common.RadioJob(do_bank_adjustment, "get_memory", loc)
        job.set_desc(_("Getting memory {num}").format(num=loc))
        self.rthread.submit(job)

    def _index_edited_cb(self, rend, path, new):
        loc, = self._store.get(self._store.get_iter(path), self.C_LOC)
        
        def refresh_memory(*args):
            self.refresh_memory(loc)

        def set_index(banks, memory):
            self.emit("changed")
            # Step 2: Set the index
            job = common.RadioJob(refresh_memory, "set_memory_index",
                                  memory, banks[0], int(new))
            job.set_target(self.rthread.radio.get_bank_model())
            job.set_desc(_("Setting index "
                           "for memory {num}").format(num=memory.number))
            self.rthread.submit(job)

        def get_bank(memory):
            # Step 1: Get the first/only bank
            job = common.RadioJob(set_index, "get_memory_banks", memory)
            job.set_cb_args(memory)
            job.set_target(self.rthread.radio.get_bank_model())
            job.set_desc(_("Getting bank for "
                           "memory {num}").format(num=memory.number))
            self.rthread.submit(job)

        # Step 0: Get the memory
        job = common.RadioJob(get_bank, "get_memory", loc)
        job.set_desc(_("Getting memory {num}").format(num=loc))
        self.rthread.submit(job)
            
    def __init__(self, rthread, editorset):
        common.Editor.__init__(self)
        self.rthread = rthread
        self.editorset = editorset
        self._rf = rthread.radio.get_features()

        self._view_cols = [
            (_("Loc"),       TYPE_INT,     gtk.CellRendererText, ),
            (_("Frequency"), TYPE_STRING,  gtk.CellRendererText, ),
            (_("Name"),      TYPE_STRING,  gtk.CellRendererText, ),
            (_("Index"),     TYPE_INT,     gtk.CellRendererText, ),
            ]

        self._cols = [
            ("_filled",      TYPE_BOOLEAN, None,                 ),
            ] + self._view_cols

        self.C_FILLED = 0
        self.C_LOC    = 1
        self.C_FREQ   = 2
        self.C_NAME   = 3
        self.C_INDEX  = 4
        self.C_BANKS  = 5 # and beyond
        
        cols = list(self._cols)

        self._index_cache = []

        for i in range(0, self.rthread.radio.get_bank_model().get_num_banks()):
            label = "Bank %i" % (i+1)
            cols.append((label, TYPE_BOOLEAN, gtk.CellRendererToggle))

        self._store = gtk.ListStore(*tuple([y for x,y,z in cols]))
        self._view = gtk.TreeView(self._store)

        colnum = 0
        for label, dtype, rtype in cols:
            if not rtype:
                colnum += 1
                continue
            rend = rtype()
            if dtype == TYPE_BOOLEAN:
                rend.set_property("activatable", True)
                rend.connect("toggled", self._toggled_cb, colnum)
                col = gtk.TreeViewColumn(label, rend, active=colnum,
                                         sensitive=self.C_FILLED)
            else:
                col = gtk.TreeViewColumn(label, rend, text=colnum,
                                         sensitive=self.C_FILLED)

            self._view.append_column(col)
            if colnum == self.C_NAME:
                col.set_visible(self._rf.has_name)
            elif colnum == self.C_INDEX:
                rend.set_property("editable", True)
                rend.connect("edited", self._index_edited_cb)
                col.set_visible(self._rf.has_bank_index)
            colnum += 1

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self._view)
        self._view.show()

        for i in range(*self._rf.memory_bounds):
            iter = self._store.append()
            self._store.set(iter,
                            self.C_FILLED, False,
                            self.C_LOC, i,
                            self.C_FREQ, 0,
                            self.C_NAME, "",
                            self.C_INDEX, 0)

        self.root = sw
        self._loaded = False

    def refresh_memory(self, number):
        def got_mem(memory, banks, indexes):
            iter = self._store.get_iter(self._number_to_path(memory.number))
            row = [self.C_FILLED, not memory.empty,
                   self.C_LOC, memory.number,
                   self.C_FREQ, chirp_common.format_freq(memory.freq),
                   self.C_NAME, memory.name,
                   # Hack for only one index right now
                   self.C_INDEX, indexes and indexes[0] or 0,
                   ]
            for i in range(0, len(self.banks)):
                row.append(i + len(self._cols))
                row.append(self.banks[i][0] in banks)
                
            self._store.set(iter, *tuple(row))

        job = MemoryBanksJob(got_mem, number)
        job.set_desc(_("Getting bank information "
                       "for memory {num}").format(num=number))
        self.rthread.submit(job)

    def refresh_all_memories(self):
        for i in range(*self._rf.memory_bounds):
            self.refresh_memory(i)

    def refresh_banks(self, and_memories=False):
        def got_banks():
            for i in range(len(self._cols) - len(self._view_cols) - 1,
                           len(self.banks)):
                col = self._view.get_column(i + len(self._view_cols))
                bank, name = self.banks[i]
                if name:
                    col.set_title(name)
                else:
                    col.set_title("(%s)" % i)
            if and_memories:
                self.refresh_all_memories()

        job = BankNamesJob(self, got_banks)
        job.set_desc(_("Getting bank information"))
        self.rthread.submit(job)

    def focus(self):
        common.Editor.focus(self)
        if self._loaded:
            return

        self.refresh_banks(True)

        self._loaded = True

    def memories_changed(self):
        self._loaded = False
        if self.is_focused():
            self.refresh_all_memories()

    def banks_changed(self):
        self.refresh_banks()
