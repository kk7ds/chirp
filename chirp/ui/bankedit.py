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
import time
import logging

from gobject import TYPE_INT, TYPE_STRING, TYPE_BOOLEAN

from chirp import chirp_common
from chirp.ui import common, miscwidgets

LOG = logging.getLogger(__name__)


class MappingNamesJob(common.RadioJob):
    def __init__(self, model, editor, cb):
        common.RadioJob.__init__(self, cb, None)
        self.__model = model
        self.__editor = editor

    def execute(self, radio):
        self.__editor.mappings = []

        mappings = self.__model.get_mappings()
        for mapping in mappings:
            self.__editor.mappings.append((mapping, mapping.get_name()))

        gobject.idle_add(self.cb, *self.cb_args)


class MappingNameEditor(common.Editor):
    def refresh(self):
        def got_mappings():
            self._keys = []
            for mapping, name in self.mappings:
                self._keys.append(mapping.get_index())
                self.listw.set_item(mapping.get_index(),
                                    mapping.get_index(),
                                    name)

            self.listw.connect("item-set", self.mapping_changed)

        job = MappingNamesJob(self._model, self, got_mappings)
        job.set_desc(_("Retrieving %s information") % self._type)
        self.rthread.submit(job)

    def get_mapping_list(self):
        mappings = []
        keys = self.listw.get_keys()
        for key in keys:
            mappings.append(self.listw.get_item(key)[2])

        return mappings

    def mapping_changed(self, listw, key):
        def cb(*args):
            self.emit("changed")

        name = self.listw.get_item(key)[2]
        mapping, oldname = self.mappings[self._keys.index(key)]

        def trigger_changed(*args):
            self.emit("changed")

        job = common.RadioJob(trigger_changed, "set_name", name)
        job.set_target(mapping)
        job.set_desc(_("Setting name on %s") % self._type.lower())
        self.rthread.submit(job)

        return True

    def __init__(self, rthread, model):
        super(MappingNameEditor, self).__init__(rthread)
        self._model = model
        self._type = common.unpluralize(model.get_name())

        types = [(gobject.TYPE_STRING, "key"),
                 (gobject.TYPE_STRING, self._type),
                 (gobject.TYPE_STRING, _("Name"))]

        self.listw = miscwidgets.KeyedListWidget(types)
        self.listw.set_editable(1, True)
        self.listw.set_sort_column(0, 1)
        self.listw.set_sort_column(1, -1)
        self.listw.show()

        self.mappings = []

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

    def other_editor_changed(self, target_editor):
        self._loaded = False
        if self.is_focused():
            self.refresh_all_memories()

    def mappings_changed(self):
        pass


class MemoryMappingsJob(common.RadioJob):
    def __init__(self, model, cb, number):
        common.RadioJob.__init__(self, cb, None)
        self.__model = model
        self.__number = number

    def execute(self, radio):
        mem = radio.get_memory(self.__number)
        if mem.empty:
            mappings = []
            indexes = []
        else:
            mappings = self.__model.get_memory_mappings(mem)
            indexes = []
            if isinstance(self.__model,
                          chirp_common.MappingModelIndexInterface):
                for mapping in mappings:
                    indexes.append(self.__model.get_memory_index(mem, mapping))
        self.cb(mem, mappings, indexes, *self.cb_args)


class MappingMembershipEditor(common.Editor):
    def _number_to_path(self, number):
        return (number - self._rf.memory_bounds[0],)

    def _get_next_mapping_index(self, mapping):
        # NB: Only works for one-to-one models right now!
        iter = self._store.get_iter_first()
        indexes = []
        ncols = len(self._cols) + len(self.mappings)
        while iter:
            vals = self._store.get(iter, *tuple([n for n in range(0, ncols)]))
            loc = vals[self.C_LOC]
            index = vals[self.C_INDEX]
            mappings = vals[self.C_MAPPINGS:]
            if True in mappings and mappings.index(True) == mapping:
                indexes.append(index)
            iter = self._store.iter_next(iter)

        index_bounds = self._model.get_index_bounds()
        num_indexes = index_bounds[1] - index_bounds[0]
        indexes.sort()
        for i in range(0, num_indexes):
            if i not in indexes:
                return i + index_bounds[0]  # In case not zero-origin index

        return 0  # If the mapping is full, just wrap around!

    def _toggled_cb(self, rend, path, colnum):
        try:
            if not rend.get_sensitive():
                return
        except AttributeError:
            # support PyGTK < 2.22
            iter = self._store.get_iter(path)
            if not self._store.get(iter, self.C_FILLED)[0]:
                return

        # The mapping index is the column number, minus the 3 label columns
        mapping, name = self.mappings[colnum - len(self._cols)]
        loc, = self._store.get(self._store.get_iter(path), self.C_LOC)

        is_indexed = isinstance(self._model,
                                chirp_common.MappingModelIndexInterface)

        if rend.get_active():
            # Changing from True to False
            fn = "remove_memory_from_mapping"
            index = None
        else:
            # Changing from False to True
            fn = "add_memory_to_mapping"
            if is_indexed:
                index = self._get_next_mapping_index(colnum - len(self._cols))
            else:
                index = None

        def do_refresh_memory(*args):
            # Step 2: Update our notion of the memory's mapping information
            self.refresh_memory(loc)

        def do_mapping_index(result, memory):
            if isinstance(result, Exception):
                common.show_error("Failed to add {mem} to mapping: {err}"
                                  .format(mem=memory.number,
                                          err=str(result)),
                                  parent=self.editorset.parent_window)
                return
            self.emit("changed")
            # Step 3: Set the memory's mapping index (maybe)
            if not is_indexed or index is None:
                return do_refresh_memory()

            job = common.RadioJob(do_refresh_memory,
                                  "set_memory_index", memory, mapping, index)
            job.set_target(self._model)
            job.set_desc(_("Updating {type} index "
                           "for memory {num}").format(type=self._type,
                                                      num=memory.number))
            self.rthread.submit(job)

        def do_mapping_adjustment(memory):
            # Step 1: Do the mapping add/remove
            job = common.RadioJob(do_mapping_index, fn, memory, mapping)
            job.set_target(self._model)
            job.set_cb_args(memory)
            job.set_desc(_("Updating mapping information "
                           "for memory {num}").format(num=memory.number))
            self.rthread.submit(job)

        # Step 0: Fetch the memory
        job = common.RadioJob(do_mapping_adjustment, "get_memory", loc)
        job.set_desc(_("Getting memory {num}").format(num=loc))
        self.rthread.submit(job)

    def _index_edited_cb(self, rend, path, new):
        loc, = self._store.get(self._store.get_iter(path), self.C_LOC)

        def refresh_memory(*args):
            self.refresh_memory(loc)

        def set_index(mappings, memory):
            self.emit("changed")
            # Step 2: Set the index
            job = common.RadioJob(refresh_memory, "set_memory_index",
                                  memory, mappings[0], int(new))
            job.set_target(self._model)
            job.set_desc(_("Setting index "
                           "for memory {num}").format(num=memory.number))
            self.rthread.submit(job)

        def get_mapping(memory):
            # Step 1: Get the first/only mapping
            job = common.RadioJob(set_index, "get_memory_mappings", memory)
            job.set_cb_args(memory)
            job.set_target(self._model)
            job.set_desc(_("Getting {type} for "
                           "memory {num}").format(type=self._type,
                                                  num=memory.number))
            self.rthread.submit(job)

        # Step 0: Get the memory
        job = common.RadioJob(get_mapping, "get_memory", loc)
        job.set_desc(_("Getting memory {num}").format(num=loc))
        self.rthread.submit(job)

    def __init__(self, rthread, editorset, model):
        super(MappingMembershipEditor, self).__init__(rthread)

        self.editorset = editorset
        self._rf = rthread.radio.get_features()
        self._model = model
        self._type = common.unpluralize(model.get_name())

        self._view_cols = [
            (_("Loc"),       TYPE_INT,     gtk.CellRendererText, ),
            (_("Frequency"), TYPE_STRING,  gtk.CellRendererText, ),
            (_("Name"),      TYPE_STRING,  gtk.CellRendererText, ),
            (_("Index"),     TYPE_INT,     gtk.CellRendererText, ),
            ]

        self._cols = [
            ("_filled",      TYPE_BOOLEAN, None, ),
            ] + self._view_cols

        self.C_FILLED = 0
        self.C_LOC = 1
        self.C_FREQ = 2
        self.C_NAME = 3
        self.C_INDEX = 4
        self.C_MAPPINGS = 5  # and beyond

        cols = list(self._cols)

        self._index_cache = []

        for i in range(0, self._model.get_num_mappings()):
            label = "%s %i" % (self._type, (i+1))
            cols.append((label, TYPE_BOOLEAN, gtk.CellRendererToggle))

        self._store = gtk.ListStore(*tuple([y for x, y, z in cols]))
        self._view = gtk.TreeView(self._store)

        is_indexed = isinstance(self._model,
                                chirp_common.MappingModelIndexInterface)

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
            col.set_resizable(True)
            if colnum == self.C_NAME:
                col.set_visible(self._rf.has_name)
            elif colnum == self.C_INDEX:
                rend.set_property("editable", True)
                rend.connect("edited", self._index_edited_cb)
                col.set_visible(is_indexed)
            colnum += 1

        # A non-rendered column to absorb extra space in the row
        self._view.append_column(gtk.TreeViewColumn())

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self._view)
        self._view.show()

        (min, max) = self._rf.memory_bounds
        for i in range(min, max+1):
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
        def got_mem(memory, mappings, indexes):
            iter = self._store.get_iter(self._number_to_path(memory.number))
            row = [self.C_FILLED, not memory.empty,
                   self.C_LOC, memory.number,
                   self.C_FREQ, chirp_common.format_freq(memory.freq),
                   self.C_NAME, memory.name,
                   # Hack for only one index right now
                   self.C_INDEX, indexes and indexes[0] or 0,
                   ]
            for i in range(0, len(self.mappings)):
                row.append(i + len(self._cols))
                row.append(self.mappings[i][0] in mappings)

            self._store.set(iter, *tuple(row))

        job = MemoryMappingsJob(self._model, got_mem, number)
        job.set_desc(_("Getting {type} information "
                       "for memory {num}").format(type=self._type, num=number))
        self.rthread.submit(job)

    def refresh_all_memories(self):
        start = time.time()
        (min, max) = self._rf.memory_bounds
        for i in range(min, max+1):
            self.refresh_memory(i)
        LOG.debug("Got all %s info in %s" %
                  (self._type, (time.time() - start)))

    def refresh_mappings(self, and_memories=False):
        def got_mappings():
            for i in range(len(self._cols) - len(self._view_cols) - 1,
                           len(self.mappings)):
                col = self._view.get_column(i + len(self._view_cols))
                mapping, name = self.mappings[i]
                if name:
                    col.set_title(name)
                else:
                    col.set_title("(%s)" % i)
            if and_memories:
                self.refresh_all_memories()

        job = MappingNamesJob(self._model, self, got_mappings)
        job.set_desc(_("Getting %s information") % self._type)
        self.rthread.submit(job)

    def focus(self):
        common.Editor.focus(self)
        if self._loaded:
            return

        self.refresh_mappings(True)

        self._loaded = True

    def other_editor_changed(self, target_editor):
        self._loaded = False
        if self.is_focused():
            self.refresh_all_memories()

    def mappings_changed(self):
        self.refresh_mappings()
