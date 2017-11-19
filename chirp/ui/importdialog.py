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
import logging

from chirp import errors, chirp_common, import_logic
from chirp.drivers import generic_xml
from chirp.ui import common

LOG = logging.getLogger(__name__)


class WaitWindow(gtk.Window):
    def __init__(self, msg, parent=None):
        gtk.Window.__init__(self)
        self.set_title("Please Wait")
        self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
        if parent:
            self.set_transient_for(parent)
            self.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        else:
            self.set_position(gtk.WIN_POS_CENTER)

        vbox = gtk.VBox(False, 2)

        l = gtk.Label(msg)
        l.show()
        vbox.pack_start(l)

        self.prog = gtk.ProgressBar()
        self.prog.show()
        vbox.pack_start(self.prog)

        vbox.show()
        self.add(vbox)

    def grind(self):
        while gtk.events_pending():
            gtk.main_iteration(False)

        self.prog.pulse()

    def set(self, fraction):
        while gtk.events_pending():
            gtk.main_iteration(False)

        self.prog.set_fraction(fraction)


class ImportMemoryBankJob(common.RadioJob):
    def __init__(self, cb, dst_mem, src_radio, src_mem):
        common.RadioJob.__init__(self, cb, None)
        self.__dst_mem = dst_mem
        self.__src_radio = src_radio
        self.__src_mem = src_mem

    def execute(self, radio):
        import_logic.import_bank(radio, self.__src_radio,
                                 self.__dst_mem, self.__src_mem)
        if self.cb:
            gobject.idle_add(self.cb, *self.cb_args)


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
                           _("Location {number} is already being imported. "
                             "Choose another value for 'New Location' "
                             "before selection 'Import'").format(number=nloc))
            d.run()
            d.destroy()
        else:
            self.__store[path][col] = not imp

    def _render(self, _, rend, model, iter, colnum):
        newloc, imp = model.get(iter, self.col_nloc, self.col_import)
        lo, hi = self.dst_radio.get_features().memory_bounds

        rend.set_property("text", "%i" % newloc)
        if newloc in self.used_list and imp:
            rend.set_property("foreground", "goldenrod")
            rend.set_property("weight", pango.WEIGHT_BOLD)
        elif newloc < lo or newloc > hi:
            rend.set_property("foreground", "red")
            rend.set_property("weight", pango.WEIGHT_BOLD)
        else:
            rend.set_property("foreground", "black")
            rend.set_property("weight", pango.WEIGHT_NORMAL)

    def _edited(self, rend, path, new, col):
        iter = self.__store.get_iter(path)

        if col == self.col_nloc:
            nloc, = self.__store.get(iter, self.col_nloc)

            try:
                val = int(new)
            except ValueError:
                common.show_error(_("Invalid value. Must be an integer."))
                return

            if val == nloc:
                return

            if self._check_for_dupe(val):
                d = gtk.MessageDialog(parent=self, buttons=gtk.BUTTONS_OK)
                d.set_property("text",
                               _("Location {number} is already being "
                                 "imported").format(number=val))
                d.run()
                d.destroy()
                return

            self.record_use_of(val)

        elif col == self.col_name or col == self.col_comm:
            val = str(new)

        else:
            return

        self.__store.set(iter, col, val)

    def get_import_list(self):
        import_list = []
        iter = self.__store.get_iter_first()
        while iter:
            old, new, name, comm, enb = \
                self.__store.get(iter, self.col_oloc, self.col_nloc,
                                 self.col_name, self.col_comm, self.col_import)
            if enb:
                import_list.append((old, new, name, comm))
            iter = self.__store.iter_next(iter)

        return import_list

    def ensure_calls(self, dst_rthread, import_list):
        rlist_changed = False
        ulist_changed = False

        if not isinstance(self.dst_radio, chirp_common.IcomDstarSupport):
            return

        ulist = self.dst_radio.get_urcall_list()
        rlist = self.dst_radio.get_repeater_call_list()

        for old, new in import_list:
            mem = self.src_radio.get_memory(old)
            if isinstance(mem, chirp_common.DVMemory):
                if mem.dv_urcall not in ulist:
                    LOG.debug("Adding %s to ucall list" % mem.dv_urcall)
                    ulist.append(mem.dv_urcall)
                    ulist_changed = True
                if mem.dv_rpt1call not in rlist:
                    LOG.debug("Adding %s to rcall list" % mem.dv_rpt1call)
                    rlist.append(mem.dv_rpt1call)
                    rlist_changed = True
                if mem.dv_rpt2call not in rlist:
                    LOG.debug("Adding %s to rcall list" % mem.dv_rpt2call)
                    rlist.append(mem.dv_rpt2call)
                    rlist_changed = True

        if ulist_changed:
            job = common.RadioJob(None, "set_urcall_list", ulist)
            job.set_desc(_("Updating URCALL list"))
            dst_rthread._qsubmit(job, 0)

        if rlist_changed:
            job = common.RadioJob(None, "set_repeater_call_list", ulist)
            job.set_desc(_("Updating RPTCALL list"))
            dst_rthread._qsubmit(job, 0)

        return

    def _convert_power(self, dst_levels, src_levels, mem):
        if not dst_levels:
            mem.power = None
            return
        elif not mem.power:
            # Source radio does not support power levels, so choose the
            # first (highest) level from the destination radio.
            mem.power = dst_levels[0]
            return ""

        # If both radios support power levels, we need to decide how to
        # convert the source power level to a valid one for the destination
        # radio.  To do that, find the absolute level of the source value
        # and calculate the different between it and all the levels of the
        # destination, choosing the one that matches most closely.

        deltas = [abs(mem.power - power) for power in dst_levels]
        mem.power = dst_levels[deltas.index(min(deltas))]

    def do_soft_conversions(self, dst_features, src_features, mem):
        self._convert_power(dst_features.valid_power_levels,
                            src_features.valid_power_levels,
                            mem)

        return mem

    def do_import_banks(self):
        try:
            dst_banks = self.dst_radio.get_banks()
            src_banks = self.src_radio.get_banks()
            if not dst_banks or not src_banks:
                raise Exception()
        except Exception:
            LOG.error("One or more of the radios doesn't support banks")
            return

        if not isinstance(self.dst_radio, generic_xml.XMLRadio) and \
                len(dst_banks) != len(src_banks):
            LOG.warn("Source and destination radios have "
                     "a different number of banks")
        else:
            self.dst_radio.set_banks(src_banks)

    def do_import(self, dst_rthread):
        i = 0
        error_messages = {}
        import_list = self.get_import_list()

        src_features = self.src_radio.get_features()

        for old, new, name, comm in import_list:
            i += 1
            LOG.debug("%sing %i -> %i" % (self.ACTION, old, new))

            src = self.src_radio.get_memory(old)

            try:
                mem = import_logic.import_mem(self.dst_radio,
                                              src_features,
                                              src,
                                              {"number":  new,
                                               "name":    name,
                                               "comment": comm})
            except import_logic.ImportError, e:
                LOG.error("Import error: %s", e)
                error_messages[new] = str(e)
                continue

            job = common.RadioJob(None, "set_memory", mem)
            desc = _("Setting memory {number}").format(number=mem.number)
            job.set_desc(desc)
            dst_rthread._qsubmit(job, 0)

            job = ImportMemoryBankJob(None, mem, self.src_radio, src)
            job.set_desc(_("Importing bank information"))
            dst_rthread._qsubmit(job, 0)

        if error_messages.keys():
            msg = _("Error importing memories:") + "\r\n"
            for num, msgs in error_messages.items():
                msg += "%s: %s" % (num, ",".join(msgs))
            common.show_error(msg)

        return i

    def make_view(self):
        editable = [self.col_nloc, self.col_name, self.col_comm]

        self.__store = gtk.ListStore(gobject.TYPE_BOOLEAN,  # Import
                                     gobject.TYPE_INT,      # Source loc
                                     gobject.TYPE_INT,      # Destination loc
                                     gobject.TYPE_STRING,   # Name
                                     gobject.TYPE_STRING,   # Frequency
                                     gobject.TYPE_STRING,   # Comment
                                     gobject.TYPE_BOOLEAN,
                                     gobject.TYPE_STRING)
        self.__view = gtk.TreeView(self.__store)
        self.__view.show()

        tips = gtk.Tooltips()

        for k in self.caps.keys():
            t = self.types[k]

            if t == gobject.TYPE_BOOLEAN:
                rend = gtk.CellRendererToggle()
                rend.connect("toggled", self._toggle, k)
                column = gtk.TreeViewColumn(self.caps[k], rend,
                                            active=k,
                                            sensitive=self.col_okay,
                                            activatable=self.col_okay)
            else:
                rend = gtk.CellRendererText()
                if k in editable:
                    rend.set_property("editable", True)
                    rend.connect("edited", self._edited, k)
                column = gtk.TreeViewColumn(self.caps[k], rend,
                                            text=k,
                                            sensitive=self.col_okay)

            if k == self.col_nloc:
                column.set_cell_data_func(rend, self._render, k)

            if k in self.tips.keys():
                LOG.debug("Doing %s" % k)
                lab = gtk.Label(self.caps[k])
                column.set_widget(lab)
                tips.set_tip(lab, self.tips[k])
                lab.show()
            column.set_sort_column_id(k)
            self.__view.append_column(column)

        self.__view.set_tooltip_column(self.col_tmsg)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.__view)
        sw.show()

        return sw

    def __select_all(self, button, state):
        iter = self.__store.get_iter_first()
        while iter:
            _state, okay, = self.__store.get(iter,
                                             self.col_import,
                                             self.col_okay)
            if state is None:
                _state = not _state and okay
            else:
                _state = state and okay
            self.__store.set(iter, self.col_import, _state)
            iter = self.__store.iter_next(iter)

    def __incrnew(self, button, delta):
        iter = self.__store.get_iter_first()
        while iter:
            pos = self.__store.get(iter, self.col_nloc)[0]
            pos += delta
            if pos < 0:
                pos = 0
            self.__store.set(iter, self.col_nloc, pos)
            iter = self.__store.iter_next(iter)

    def __autonew(self, button):
        pos = self.dst_radio.get_features().memory_bounds[0]
        iter = self.__store.get_iter_first()
        while iter:
            selected, okay = self.__store.get(iter,
                                              self.col_import, self.col_okay)
            if selected and okay:
                self.__store.set(iter, self.col_nloc, pos)
                pos += 1
            iter = self.__store.iter_next(iter)

    def __revrnew(self, button):
        positions = []
        iter = self.__store.get_iter_first()
        while iter:
            positions.append(self.__store.get(iter, self.col_nloc)[0])
            iter = self.__store.iter_next(iter)

        iter = self.__store.get_iter_first()
        while iter:
            self.__store.set(iter, self.col_nloc, positions.pop())
            iter = self.__store.iter_next(iter)

    def make_select(self):
        hbox = gtk.HBox(True, 2)

        all = gtk.Button(_("All"))
        all.connect("clicked", self.__select_all, True)
        all.set_size_request(50, 25)
        all.show()
        hbox.pack_start(all, 0, 0, 0)

        none = gtk.Button(_("None"))
        none.connect("clicked", self.__select_all, False)
        none.set_size_request(50, 25)
        none.show()
        hbox.pack_start(none, 0, 0, 0)

        inv = gtk.Button(_("Inverse"))
        inv.connect("clicked", self.__select_all, None)
        inv.set_size_request(50, 25)
        inv.show()
        hbox.pack_start(inv, 0, 0, 0)

        frame = gtk.Frame(_("Select"))
        frame.show()
        frame.add(hbox)
        hbox.show()

        return frame

    def make_adjust(self):
        hbox = gtk.HBox(True, 2)

        incr = gtk.Button("+100")
        incr.connect("clicked", self.__incrnew, 100)
        incr.set_size_request(50, 25)
        incr.show()
        hbox.pack_start(incr, 0, 0, 0)

        incr = gtk.Button("+10")
        incr.connect("clicked", self.__incrnew, 10)
        incr.set_size_request(50, 25)
        incr.show()
        hbox.pack_start(incr, 0, 0, 0)

        incr = gtk.Button("+1")
        incr.connect("clicked", self.__incrnew, 1)
        incr.set_size_request(50, 25)
        incr.show()
        hbox.pack_start(incr, 0, 0, 0)

        decr = gtk.Button("-1")
        decr.connect("clicked", self.__incrnew, -1)
        decr.set_size_request(50, 25)
        decr.show()
        hbox.pack_start(decr, 0, 0, 0)

        decr = gtk.Button("-10")
        decr.connect("clicked", self.__incrnew, -10)
        decr.set_size_request(50, 25)
        decr.show()
        hbox.pack_start(decr, 0, 0, 0)

        decr = gtk.Button("-100")
        decr.connect("clicked", self.__incrnew, -100)
        decr.set_size_request(50, 25)
        decr.show()
        hbox.pack_start(decr, 0, 0, 0)

        auto = gtk.Button(_("Auto"))
        auto.connect("clicked", self.__autonew)
        auto.set_size_request(50, 25)
        auto.show()
        hbox.pack_start(auto, 0, 0, 0)

        revr = gtk.Button(_("Reverse"))
        revr.connect("clicked", self.__revrnew)
        revr.set_size_request(50, 25)
        revr.show()
        hbox.pack_start(revr, 0, 0, 0)

        frame = gtk.Frame(_("Adjust New Location"))
        frame.show()
        frame.add(hbox)
        hbox.show()

        return frame

    def make_options(self):
        hbox = gtk.HBox(True, 2)

        confirm = gtk.CheckButton(_("Confirm overwrites"))
        confirm.connect("toggled", __set_confirm)
        confirm.show()

        hbox.pack_start(confirm, 0, 0, 0)

        frame = gtk.Frame(_("Options"))
        frame.add(hbox)
        frame.show()
        hbox.show()

        return frame

    def make_controls(self):
        hbox = gtk.HBox(False, 2)

        hbox.pack_start(self.make_select(), 0, 0, 0)
        hbox.pack_start(self.make_adjust(), 0, 0, 0)
        # hbox.pack_start(self.make_options(), 0, 0, 0)
        hbox.show()

        return hbox

    def build_ui(self):
        self.vbox.pack_start(self.make_view(), 1, 1, 1)
        self.vbox.pack_start(self.make_controls(), 0, 0, 0)

    def record_use_of(self, number):
        lo, hi = self.dst_radio.get_features().memory_bounds

        if number < lo or number > hi:
            return

        try:
            mem = self.dst_radio.get_memory(number)
            if mem and not mem.empty and number not in self.used_list:
                self.used_list.append(number)
        except errors.InvalidMemoryLocation:
            LOG.error("Location %i empty or at limit of destination radio" %
                      number)
        except errors.InvalidDataError, e:
            LOG.error("Got error from radio, assuming %i beyond limits: %s" %
                      (number, e))

    def populate_list(self):
        start, end = self.src_radio.get_features().memory_bounds
        for i in range(start, end+1):
            if end > 50 and i % (end/50) == 0:
                self.ww.set(float(i) / end)
            try:
                mem = self.src_radio.get_memory(i)
            except errors.InvalidMemoryLocation, e:
                continue
            except Exception, e:
                self.__store.append(row=(False,
                                         i,
                                         i,
                                         "ERROR",
                                         chirp_common.format_freq(0),
                                         "",
                                         False,
                                         str(e),
                                         ))
                self.record_use_of(i)
                continue
            if mem.empty:
                continue

            self.ww.set(float(i) / end)
            try:
                msgs = self.dst_radio.validate_memory(
                        import_logic.import_mem(self.dst_radio,
                                                self.src_radio.get_features(),
                                                mem))
            except import_logic.DestNotCompatible:
                msgs = self.dst_radio.validate_memory(mem)
            errs = [x for x in msgs
                    if isinstance(x, chirp_common.ValidationError)]
            if errs:
                msg = _("Cannot be imported because") + ":\r\n"
                msg += ",".join(errs)
            else:
                errs = []
                msg = "Memory can be imported into target"

            self.__store.append(row=(not bool(msgs),
                                     mem.number,
                                     mem.number,
                                     mem.name,
                                     chirp_common.format_freq(mem.freq),
                                     mem.comment,
                                     not bool(errs),
                                     msg
                                     ))
            self.record_use_of(mem.number)

    TITLE = _("Import From File")
    ACTION = _("Import")

    def __init__(self, src_radio, dst_radio, parent=None):
        gtk.Dialog.__init__(self,
                            buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK,
                                     gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL),
                            title=self.TITLE,
                            parent=parent)

        self.col_import = 0
        self.col_nloc = 1
        self.col_oloc = 2
        self.col_name = 3
        self.col_freq = 4
        self.col_comm = 5
        self.col_okay = 6
        self.col_tmsg = 7

        self.caps = {
            self.col_import:  self.ACTION,
            self.col_nloc:    _("To"),
            self.col_oloc:    _("From"),
            self.col_name:    _("Name"),
            self.col_freq:    _("Frequency"),
            self.col_comm:    _("Comment"),
            }

        self.tips = {
            self.col_nloc:  _("Location memory will be imported into"),
            self.col_oloc:  _("Location of memory in the file being imported"),
            }

        self.types = {
            self.col_import:  gobject.TYPE_BOOLEAN,
            self.col_oloc:    gobject.TYPE_INT,
            self.col_nloc:    gobject.TYPE_INT,
            self.col_name:    gobject.TYPE_STRING,
            self.col_freq:    gobject.TYPE_STRING,
            self.col_comm:    gobject.TYPE_STRING,
            self.col_okay:    gobject.TYPE_BOOLEAN,
            self.col_tmsg:    gobject.TYPE_STRING,
            }

        self.src_radio = src_radio
        self.dst_radio = dst_radio

        self.used_list = []
        self.not_used_list = []

        self.build_ui()
        self.set_default_size(600, 400)

        self.ww = WaitWindow(_("Preparing memory list..."), parent=parent)
        self.ww.show()
        self.ww.grind()

        self.populate_list()

        self.ww.hide()


class ExportDialog(ImportDialog):
    TITLE = _("Export To File")
    ACTION = _("Export")

if __name__ == "__main__":
    from chirp.ui import editorset
    import sys

    f = sys.argv[1]
    rc = editorset.radio_class_from_file(f)
    radio = rc(f)

    d = ImportDialog(radio)
    d.run()

    print d.get_import_list()
