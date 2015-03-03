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

import os
import logging

from chirp import platform

LOG = logging.getLogger(__name__)


class KeyedListWidget(gtk.HBox):
    __gsignals__ = {
        "item-selected": (gobject.SIGNAL_RUN_LAST,
                          gobject.TYPE_NONE,
                          (gobject.TYPE_STRING,)),
        "item-toggled": (gobject.SIGNAL_ACTION,
                         gobject.TYPE_BOOLEAN,
                         (gobject.TYPE_STRING, gobject.TYPE_BOOLEAN)),
        "item-set": (gobject.SIGNAL_ACTION,
                     gobject.TYPE_BOOLEAN,
                     (gobject.TYPE_STRING,)),
        }

    def _toggle(self, rend, path, colnum):
        if self.__toggle_connected:
            self.__store[path][colnum] = not self.__store[path][colnum]
            iter = self.__store.get_iter(path)
            id, = self.__store.get(iter, 0)
            self.emit("item-toggled", id, self.__store[path][colnum])

    def _edited(self, rend, path, new, colnum):
        iter = self.__store.get_iter(path)
        key, oldval = self.__store.get(iter, 0, colnum)
        self.__store.set(iter, colnum, new)
        if not self.emit("item-set", key):
            self.__store.set(iter, colnum, oldval)

    def _mouse(self, view, event):
        x, y = event.get_coords()
        path = self.__view.get_path_at_pos(int(x), int(y))
        if path:
            self.__view.set_cursor_on_cell(path[0])

        sel = self.get_selected()
        if sel:
            self.emit("item-selected", sel)

    def _make_view(self):
        colnum = -1

        for typ, cap in self.columns:
            colnum += 1
            if colnum == 0:
                continue  # Key column

            if typ in [gobject.TYPE_STRING, gobject.TYPE_INT,
                       gobject.TYPE_FLOAT]:
                rend = gtk.CellRendererText()
                rend.set_property("ellipsize", pango.ELLIPSIZE_END)
                column = gtk.TreeViewColumn(cap, rend, text=colnum)
            elif typ in [gobject.TYPE_BOOLEAN]:
                rend = gtk.CellRendererToggle()
                rend.connect("toggled", self._toggle, colnum)
                column = gtk.TreeViewColumn(cap, rend, active=colnum)
            else:
                raise Exception("Unsupported type %s" % typ)

            column.set_sort_column_id(colnum)
            self.__view.append_column(column)

        self.__view.connect("button_press_event", self._mouse)

    def set_item(self, key, *values):
        iter = self.__store.get_iter_first()
        while iter:
            id, = self.__store.get(iter, 0)
            if id == key:
                self.__store.insert_after(iter, row=(id,)+values)
                self.__store.remove(iter)
                return
            iter = self.__store.iter_next(iter)

        self.__store.append(row=(key,) + values)

        self.emit("item-set", key)

    def get_item(self, key):
        iter = self.__store.get_iter_first()
        while iter:
            vals = self.__store.get(iter, *tuple(range(len(self.columns))))
            if vals[0] == key:
                return vals
            iter = self.__store.iter_next(iter)

        return None

    def del_item(self, key):
        iter = self.__store.get_iter_first()
        while iter:
            id, = self.__store.get(iter, 0)
            if id == key:
                self.__store.remove(iter)
                return True

            iter = self.__store.iter_next(iter)

        return False

    def has_item(self, key):
        return self.get_item(key) is not None

    def get_selected(self):
        try:
            (store, iter) = self.__view.get_selection().get_selected()
            return store.get(iter, 0)[0]
        except Exception, e:
            LOG.error("Unable to find selected: %s" % e)
            return None

    def select_item(self, key):
        if key is None:
            sel = self.__view.get_selection()
            sel.unselect_all()
            return True

        iter = self.__store.get_iter_first()
        while iter:
            if self.__store.get(iter, 0)[0] == key:
                selection = self.__view.get_selection()
                path = self.__store.get_path(iter)
                selection.select_path(path)
                return True
            iter = self.__store.iter_next(iter)

        return False

    def get_keys(self):
        keys = []
        iter = self.__store.get_iter_first()
        while iter:
            key, = self.__store.get(iter, 0)
            keys.append(key)
            iter = self.__store.iter_next(iter)

        return keys

    def __init__(self, columns):
        gtk.HBox.__init__(self, True, 0)

        self.columns = columns

        types = tuple([x for x, y in columns])

        self.__store = gtk.ListStore(*types)
        self.__view = gtk.TreeView(self.__store)

        self.pack_start(self.__view, 1, 1, 1)

        self.__toggle_connected = False

        self._make_view()
        self.__view.show()

    def connect(self, signame, *args):
        if signame == "item-toggled":
            self.__toggle_connected = True

        gtk.HBox.connect(self, signame, *args)

    def set_editable(self, column, is_editable):
        col = self.__view.get_column(column)
        rend = col.get_cell_renderers()[0]
        rend.set_property("editable", True)
        rend.connect("edited", self._edited, column + 1)

    def set_sort_column(self, column, value=None):
        if not value:
            value = column
        col = self.__view.get_column(column)
        col.set_sort_column_id(value)

    def get_renderer(self, colnum):
        return self.__view.get_column(colnum).get_cell_renderers()[0]


class ListWidget(gtk.HBox):
    __gsignals__ = {
        "click-on-list": (gobject.SIGNAL_RUN_LAST,
                          gobject.TYPE_NONE,
                          (gtk.TreeView, gtk.gdk.Event)),
        "item-toggled": (gobject.SIGNAL_RUN_LAST,
                         gobject.TYPE_NONE,
                         (gobject.TYPE_PYOBJECT,)),
        }

    store_type = gtk.ListStore

    def mouse_cb(self, view, event):
        self.emit("click-on-list", view, event)

    # pylint: disable-msg=W0613
    def _toggle(self, render, path, column):
        self._store[path][column] = not self._store[path][column]
        iter = self._store.get_iter(path)
        vals = tuple(self._store.get(iter, *tuple(range(self._ncols))))
        for cb in self.toggle_cb:
            cb(*vals)
        self.emit("item-toggled", vals)

    def make_view(self, columns):
        self._view = gtk.TreeView(self._store)

        for _type, _col in columns:
            if _col.startswith("__"):
                continue

            index = columns.index((_type, _col))
            if _type == gobject.TYPE_STRING or \
                    _type == gobject.TYPE_INT or \
                    _type == gobject.TYPE_FLOAT:
                rend = gtk.CellRendererText()
                column = gtk.TreeViewColumn(_col, rend, text=index)
                column.set_resizable(True)
                rend.set_property("ellipsize", pango.ELLIPSIZE_END)
            elif _type == gobject.TYPE_BOOLEAN:
                rend = gtk.CellRendererToggle()
                rend.connect("toggled", self._toggle, index)
                column = gtk.TreeViewColumn(_col, rend, active=index)
            else:
                raise Exception("Unknown column type (%i)" % index)

            column.set_sort_column_id(index)
            self._view.append_column(column)

        self._view.connect("button_press_event", self.mouse_cb)

    def __init__(self, columns, parent=True):
        gtk.HBox.__init__(self)

        # pylint: disable-msg=W0612
        col_types = tuple([x for x, y in columns])
        self._ncols = len(col_types)

        self._store = self.store_type(*col_types)
        self._view = None
        self.make_view(columns)

        self._view.show()
        if parent:
            self.pack_start(self._view, 1, 1, 1)

        self.toggle_cb = []

    def packable(self):
        return self._view

    def add_item(self, *vals):
        if len(vals) != self._ncols:
            raise Exception("Need %i columns" % self._ncols)

        args = []
        i = 0
        for val in vals:
            args.append(i)
            args.append(val)
            i += 1

        args = tuple(args)

        iter = self._store.append()
        self._store.set(iter, *args)

    def _remove_item(self, model, path, iter, match):
        vals = model.get(iter, *tuple(range(0, self._ncols)))
        if vals == match:
            model.remove(iter)

    def remove_item(self, *vals):
        if len(vals) != self._ncols:
            raise Exception("Need %i columns" % self._ncols)

    def remove_selected(self):
        try:
            (lst, iter) = self._view.get_selection().get_selected()
            lst.remove(iter)
        except Exception, e:
            LOG.error("Unable to remove selected: %s" % e)

    def get_selected(self, take_default=False):
        (lst, iter) = self._view.get_selection().get_selected()
        if not iter and take_default:
            iter = lst.get_iter_first()

        return lst.get(iter, *tuple(range(self._ncols)))

    def move_selected(self, delta):
        (lst, iter) = self._view.get_selection().get_selected()

        pos = int(lst.get_path(iter)[0])

        try:
            target = None

            if delta > 0 and pos > 0:
                target = lst.get_iter(pos-1)
            elif delta < 0:
                target = lst.get_iter(pos+1)
        except Exception, e:
            return False

        if target:
            return lst.swap(iter, target)

    def _get_value(self, model, path, iter, lst):
        lst.append(model.get(iter, *tuple(range(0, self._ncols))))

    def get_values(self):
        lst = []

        self._store.foreach(self._get_value, lst)

        return lst

    def set_values(self, lst):
        self._store.clear()

        for i in lst:
            self.add_item(*i)


class TreeWidget(ListWidget):
    store_type = gtk.TreeStore

    # pylint: disable-msg=W0613
    def _toggle(self, render, path, column):
        self._store[path][column] = not self._store[path][column]
        iter = self._store.get_iter(path)
        vals = tuple(self._store.get(iter, *tuple(range(self._ncols))))

        piter = self._store.iter_parent(iter)
        if piter:
            parent = self._store.get(piter, self._key)[0]
        else:
            parent = None

        for cb in self.toggle_cb:
            cb(parent, *vals)

    def __init__(self, columns, key, parent=True):
        ListWidget.__init__(self, columns, parent)

        self._key = key

    def _add_item(self, piter, *vals):
        args = []
        i = 0
        for val in vals:
            args.append(i)
            args.append(val)
            i += 1

        args = tuple(args)

        iter = self._store.append(piter)
        self._store.set(iter, *args)

    def _iter_of(self, key, iter=None):
        if not iter:
            iter = self._store.get_iter_first()

        while iter is not None:
            _id = self._store.get(iter, self._key)[0]
            if _id == key:
                return iter

            iter = self._store.iter_next(iter)

        return None

    def add_item(self, parent, *vals):
        if len(vals) != self._ncols:
            raise Exception("Need %i columns" % self._ncols)

        if not parent:
            self._add_item(None, *vals)
        else:
            iter = self._iter_of(parent)
            if iter:
                self._add_item(iter, *vals)
            else:
                raise Exception("Parent not found: %s", parent)

    def _set_values(self, parent, vals):
        if isinstance(vals, dict):
            for key, val in vals.items():
                iter = self._store.append(parent)
                self._store.set(iter, self._key, key)
                self._set_values(iter, val)
        elif isinstance(vals, list):
            for i in vals:
                self._set_values(parent, i)
        elif isinstance(vals, tuple):
            self._add_item(parent, *vals)
        else:
            LOG.error("Unknown type: %s" % vals)

    def set_values(self, vals):
        self._store.clear()
        self._set_values(self._store.get_iter_first(), vals)

    def del_item(self, parent, key):
        iter = self._iter_of(key,
                             self._store.iter_children(self._iter_of(parent)))
        if iter:
            self._store.remove(iter)
        else:
            raise Exception("Item not found")

    def get_item(self, parent, key):
        iter = self._iter_of(key,
                             self._store.iter_children(self._iter_of(parent)))

        if iter:
            return self._store.get(iter, *(tuple(range(0, self._ncols))))
        else:
            raise Exception("Item not found")

    def set_item(self, parent, *vals):
        iter = self._iter_of(vals[self._key],
                             self._store.iter_children(self._iter_of(parent)))

        if iter:
            args = []
            i = 0

            for val in vals:
                args.append(i)
                args.append(val)
                i += 1

            self._store.set(iter, *(tuple(args)))
        else:
            raise Exception("Item not found")


class ProgressDialog(gtk.Window):
    def __init__(self, title, parent=None):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_modal(True)
        self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
        self.set_title(title)
        if parent:
            self.set_transient_for(parent)

        self.set_resizable(False)

        vbox = gtk.VBox(False, 2)

        self.label = gtk.Label("")
        self.label.set_size_request(100, 50)
        self.label.show()

        self.pbar = gtk.ProgressBar()
        self.pbar.show()

        vbox.pack_start(self.label, 0, 0, 0)
        vbox.pack_start(self.pbar, 0, 0, 0)

        vbox.show()

        self.add(vbox)

    def set_text(self, text):
        self.label.set_text(text)
        self.queue_draw()

        while gtk.events_pending():
            gtk.main_iteration_do(False)

    def set_fraction(self, frac):
        self.pbar.set_fraction(frac)
        self.queue_draw()

        while gtk.events_pending():
            gtk.main_iteration_do(False)


class LatLonEntry(gtk.Entry):
    def __init__(self, *args):
        gtk.Entry.__init__(self, *args)

        self.connect("changed", self.format)

    def format(self, entry):
        string = entry.get_text()
        if string is None:
            return

        deg = u"\u00b0"

        while " " in string:
            if "." in string:
                break
            elif deg not in string:
                string = string.replace(" ", deg)
            elif "'" not in string:
                string = string.replace(" ", "'")
            elif '"' not in string:
                string = string.replace(" ", '"')
            else:
                string = string.replace(" ", "")

        entry.set_text(string)

    def parse_dd(self, string):
        return float(string)

    def parse_dm(self, string):
        string = string.strip()
        string = string.replace('  ', ' ')

        (_degrees, _minutes) = string.split(' ', 2)

        degrees = int(_degrees)
        minutes = float(_minutes)

        return degrees + (minutes / 60.0)

    def parse_dms(self, string):
        string = string.replace(u"\u00b0", " ")
        string = string.replace('"', ' ')
        string = string.replace("'", ' ')
        string = string.replace('  ', ' ')
        string = string.strip()

        items = string.split(' ')

        if len(items) > 3:
            raise Exception("Invalid format")
        elif len(items) == 3:
            deg = items[0]
            mns = items[1]
            sec = items[2]
        elif len(items) == 2:
            deg = items[0]
            mns = items[1]
            sec = 0
        elif len(items) == 1:
            deg = items[0]
            mns = 0
            sec = 0
        else:
            deg = 0
            mns = 0
            sec = 0

        degrees = int(deg)
        minutes = int(mns)
        seconds = float(sec)

        return degrees + (minutes / 60.0) + (seconds / 3600.0)

    def value(self):
        string = self.get_text()

        try:
            return self.parse_dd(string)
        except:
            try:
                return self.parse_dm(string)
            except:
                try:
                    return self.parse_dms(string)
                except Exception, e:
                    LOG.error("DMS: %s" % e)

        raise Exception("Invalid format")

    def validate(self):
        try:
            self.value()
            return True
        except:
            return False


class YesNoDialog(gtk.Dialog):
    def __init__(self, title="", parent=None, buttons=None):
        gtk.Dialog.__init__(self, title=title, parent=parent, buttons=buttons)

        self._label = gtk.Label("")
        self._label.show()

        # pylint: disable-msg=E1101
        self.vbox.pack_start(self._label, 1, 1, 1)

    def set_text(self, text):
        self._label.set_text(text)


def make_choice(options, editable=True, default=None):
    if editable:
        sel = gtk.combo_box_entry_new_text()
    else:
        sel = gtk.combo_box_new_text()

    for opt in options:
        sel.append_text(opt)

    if default:
        try:
            idx = options.index(default)
            sel.set_active(idx)
        except:
            pass

    return sel


class FilenameBox(gtk.HBox):
    __gsignals__ = {
        "filename-changed": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
        }

    def do_browse(self, _, dir):
        if self.filename.get_text():
            start = os.path.dirname(self.filename.get_text())
        else:
            start = None

        if dir:
            fn = platform.get_platform().gui_select_dir(start)
        else:
            fn = platform.get_platform().gui_save_file(start, types=self.types)
        if fn:
            self.filename.set_text(fn)

    def do_changed(self, _):
        self.emit("filename_changed")

    def __init__(self, find_dir=False, types=[]):
        gtk.HBox.__init__(self, False, 0)

        self.types = types

        self.filename = gtk.Entry()
        self.filename.show()
        self.pack_start(self.filename, 1, 1, 1)

        browse = gtk.Button("...")
        browse.show()
        self.pack_start(browse, 0, 0, 0)

        self.filename.connect("changed", self.do_changed)
        browse.connect("clicked", self.do_browse, find_dir)

    def set_filename(self, fn):
        self.filename.set_text(fn)

    def get_filename(self):
        return self.filename.get_text()


def make_pixbuf_choice(options, default=None):
    store = gtk.ListStore(gtk.gdk.Pixbuf, gobject.TYPE_STRING)
    box = gtk.ComboBox(store)

    cell = gtk.CellRendererPixbuf()
    box.pack_start(cell, True)
    box.add_attribute(cell, "pixbuf", 0)

    cell = gtk.CellRendererText()
    box.pack_start(cell, True)
    box.add_attribute(cell, "text", 1)

    _default = None
    for pic, value in options:
        iter = store.append()
        store.set(iter, 0, pic, 1, value)
        if default == value:
            _default = options.index((pic, value))

    if _default:
        box.set_active(_default)

    return box


def test():
    win = gtk.Window(gtk.WINDOW_TOPLEVEL)
    lst = ListWidget([(gobject.TYPE_STRING, "Foo"),
                      (gobject.TYPE_BOOLEAN, "Bar")])

    lst.add_item("Test1", True)
    lst.set_values([("Test2", True), ("Test3", False)])

    lst.show()
    win.add(lst)
    win.show()

    win1 = ProgressDialog("foo")
    win1.show()

    win2 = gtk.Window(gtk.WINDOW_TOPLEVEL)
    lle = LatLonEntry()
    lle.show()
    win2.add(lle)
    win2.show()

    win3 = gtk.Window(gtk.WINDOW_TOPLEVEL)
    lst = TreeWidget([(gobject.TYPE_STRING, "Id"),
                      (gobject.TYPE_STRING, "Value")],
                     1)
    lst.set_values({"Fruit": [("Apple", "Red"), ("Orange", "Orange")],
                    "Pizza": [("Cheese", "Simple"), ("Pepperoni", "Yummy")]})
    lst.add_item("Fruit", "Bananna", "Yellow")
    lst.show()
    win3.add(lst)
    win3.show()

    def print_val(entry):
        if entry.validate():
            print "Valid: %s" % entry.value()
        else:
            print "Invalid"
    lle.connect("activate", print_val)

    lle.set_text("45 13 12")

    try:
        gtk.main()
    except KeyboardInterrupt:
        pass

    print lst.get_values()


if __name__ == "__main__":
    test()
