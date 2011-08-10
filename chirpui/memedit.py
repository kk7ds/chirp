#/usr/bin/python
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

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

import threading

import gtk
import pango
from gobject import TYPE_INT, \
    TYPE_DOUBLE as TYPE_FLOAT, \
    TYPE_STRING, \
    TYPE_BOOLEAN, \
    TYPE_PYOBJECT, \
    TYPE_INT64
import gobject
import pickle
import os

from chirpui import common, shiftdialog, miscwidgets, config
from chirp import chirp_common, errors, directory

def handle_toggle(_, path, store, col):
    store[path][col] = not store[path][col]    

def handle_ed(_, iter, new, store, col):
    old, = store.get(iter, col)
    if old != new:
        store.set(iter, col, new)
        return True
    else:
        return False

class ValueErrorDialog(gtk.MessageDialog):
    def __init__(self, exception, **args):
        gtk.MessageDialog.__init__(self, buttons=gtk.BUTTONS_OK, **args)
        self.set_property("text", "Invalid value for this field")
        self.format_secondary_text(str(exception))

def iter_prev(store, iter):
    row = store.get_path(iter)[0]
    if row == 0:
        return None
    return store.get_iter((row - 1,))

# A quick hacked up tool to show a blob of text in a dialog window
# using fixed-width fonts. It also highlights lines that start with
# a '-' in red bold font and '+' with blue bold font.
def show_blob(title, result):
    d = gtk.Dialog(title=title,
                   buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK))
    b = gtk.TextBuffer()

    tags = b.get_tag_table()
    for color in ["red", "blue", "green", "grey"]:
        tag = gtk.TextTag(color)
        tag.set_property("foreground", color)
        tags.add(tag)
    tag = gtk.TextTag("bold")
    tag.set_property("weight", pango.WEIGHT_BOLD)
    tags.add(tag)

    lines = result.split(os.linesep)
    for line in lines:
        if line.startswith("-"):
            tags = ("red", "bold")
        elif line.startswith("+"):
            tags = ("blue", "bold")
        else:
            tags = ()
        b.insert_with_tags_by_name(b.get_end_iter(), line + os.linesep, *tags)
    v = gtk.TextView(b)
    fontdesc = pango.FontDescription("Courier 11")
    v.modify_font(fontdesc)
    v.set_editable(False)
    v.show()
    s = gtk.ScrolledWindow()
    s.add(v)
    s.show()
    d.vbox.pack_start(s, 1, 1, 1)
    d.set_size_request(600, 400)
    d.run()
    d.destroy()

class MemoryEditor(common.Editor):
    cols = [
        ("Loc"       , TYPE_INT,     gtk.CellRendererText,  ),
        ("Name"      , TYPE_STRING,  gtk.CellRendererText,  ), 
        ("Frequency" , TYPE_INT64,   gtk.CellRendererText,  ),
        ("Tone Mode" , TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Tone"      , TYPE_FLOAT,   gtk.CellRendererCombo, ),
        ("ToneSql"   , TYPE_FLOAT,   gtk.CellRendererCombo, ),
        ("DTCS Code" , TYPE_INT,     gtk.CellRendererCombo, ),
        ("DTCS Pol"  , TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Cross Mode", TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Duplex"    , TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Offset"    , TYPE_INT64,   gtk.CellRendererText,  ),
        ("Mode"      , TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Power"     , TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Tune Step" , TYPE_FLOAT,   gtk.CellRendererCombo, ),
        ("Skip"      , TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Bank"      , TYPE_STRING,  gtk.CellRendererCombo, ),
        ("Bank Index", TYPE_INT,     gtk.CellRendererText,  ),
        ("_filled"   , TYPE_BOOLEAN, None,                  ),
        ("_hide_cols", TYPE_PYOBJECT,None,                  ),
        ("_extd"     , TYPE_STRING,  None,                  ),
        ]

    defaults = {
        "Name"      : "",
        "Frequency" : 146010000,
        "Tone"      : 88.5,
        "ToneSql"   : 88.5,
        "DTCS Code" : 23,
        "DTCS Pol"  : "NN",
        "Cross Mode": "DCS->Off",
        "Duplex"    : "",
        "Offset"    : 0,
        "Mode"      : "FM",
        "Power"     : "",
        "Tune Step" : 5.0,
        "Tone Mode" : "",
        "Skip"      : "",
        "Bank"      : "",
        "Bank Index": 0,
        }

    choices = {
        "Tone" : chirp_common.TONES,
        "ToneSql" : chirp_common.TONES,
        "DTCS Code" : chirp_common.DTCS_CODES,
        "DTCS Pol" : ["NN", "NR", "RN", "RR"],
        "Mode" : chirp_common.MODES,
        "Power" : [],
        "Duplex" : ["", "-", "+", "split"],
        "Tune Step" : chirp_common.TUNING_STEPS,
        "Tone Mode" : ["", "Tone", "TSQL", "DTCS"],
        "Cross Mode" : chirp_common.CROSS_MODES,
        }
    
    def ed_name(self, _, __, new, ___):
        return self.rthread.radio.filter_name(new)

    def ed_offset(self, _, path, new, __):
        return chirp_common.parse_freq(new)

    def ed_freq(self, _, path, new, colnum):
        iter = self.store.get_iter(path)
        prev, = self.store.get(iter, colnum)

        def set_offset(path, offset):
            if offset > 0:
                dup = "+"
            elif offset == 0:
                dup = ""
            else:
                dup = "-"
                offset *= -1

            if offset:
                self.store.set(iter, self.col("Offset"), offset)

            self.store.set(iter, self.col("Duplex"), dup)

        def set_ts(ts):
            self.store.set(iter, self.col("Tune Step"), ts)

        def get_ts(path):
            return self.store.get(iter, self.col("Tune Step"))[0]

        try:
            new = chirp_common.parse_freq(new)
        except ValueError, e:
            print e
            new = None

        set_ts(chirp_common.required_step(new))

        if new and self._config.get_bool("autorpt") and new != prev:
            band = int(new / 100000000)
            if chirp_common.STD_OFFSETS.has_key(band):
                offsets = chirp_common.STD_OFFSETS[band]
                set_offset(path, 0)
                for lo, hi, offset in offsets:
                    if new < hi and new > lo:
                        set_offset(path, offset)
                        break

        return new

    def ed_loc(self, _, path, new, __):
        iter = self.store.get_iter(path)
        curloc, = self.store.get(iter, self.col("Loc"))

        job = common.RadioJob(None, "erase_memory", curloc)
        job.set_desc("Erasing memory %i" % curloc)
        self.rthread.submit(job)

        self.need_refresh = True

        return new

    def ed_duplex(self, _, path, new, __):
        if new == "":
            return # Fast path outta here

        iter = self.store.get_iter(path)
        freq, = self.store.get(iter, self.col("Frequency"))
        if new == "split":
            # If we're going to split mode, use the current
            # RX frequency as the default TX frequency
            self.store.set(iter, self.col("Offset"), freq)
        else:
            band = int(freq / 100000000)
            if chirp_common.STD_OFFSETS.has_key(band):
                offset = chirp_common.STD_OFFSETS[band][0][2]
            else:
                offset = 0
            self.store.set(iter, self.col("Offset"), abs(offset))

        return new

    def _get_cols_to_hide(self, iter):
        tmode, duplex, bank = self.store.get(iter,
                                             self.col("Tone Mode"),
                                             self.col("Duplex"),
                                             self.col("Bank"))

        hide = []

        if tmode == "Tone":
            hide += [self.col("ToneSql"),
                     self.col("DTCS Code"),
                     self.col("DTCS Pol")]
        elif tmode == "TSQL":
            hide += [self.col("Tone"),
                     self.col("DTCS Code"),
                     self.col("DTCS Pol")]
        elif tmode == "DTCS":
            hide += [self.col("Tone"), self.col("ToneSql")]
        elif tmode == "" or tmode == "(None)":
            hide += [self.col("Tone"),
                     self.col("ToneSql"),
                     self.col("DTCS Code"),
                     self.col("DTCS Pol")]

        if duplex == "" or duplex == "(None)":
            hide += [self.col("Offset")]

        if bank == "":
            hide += [self.col("Bank Index")]

        return hide

    def maybe_hide_cols(self, iter):
        hide_cols = self._get_cols_to_hide(iter)
        self.store.set(iter, self.col("_hide_cols"), hide_cols)

    def edited(self, rend, path, new, cap):
        if self.read_only:
            common.show_error("Unable to make changes to this model")
            return

        iter = self.store.get_iter(path)
        if not self.store.get(iter, self.col("_filled"))[0]:
            print "Editing new item, taking defaults"
            self.insert_new(iter)

        colnum = self.col(cap)
        funcs = {
            "Loc" : self.ed_loc,
            "Name" : self.ed_name,
            "Frequency" : self.ed_freq,
            "Duplex" : self.ed_duplex,
            "Offset" : self.ed_offset,
            }

        if funcs.has_key(cap):
            new = funcs[cap](rend, path, new, colnum)

        if new is None:
            print "Bad value for %s: %s" % (cap, new)
            return

        if self.store.get_column_type(colnum) == TYPE_INT:
            new = int(new)
        elif self.store.get_column_type(colnum) == TYPE_FLOAT:
            new = float(new)
        elif self.store.get_column_type(colnum) == TYPE_BOOLEAN:
            new = bool(new)
        elif self.store.get_column_type(colnum) == TYPE_STRING:
            if new == "(None)":
                new = ""

        if not handle_ed(rend, iter, new, self.store, self.col(cap)) and \
                cap != "Frequency":
            # No change was made
            # For frequency, we make an exception, since the handler might
            # have altered the duplex.  That needs to be fixed.
            return

        mem = self._get_memory(iter)

        msgs = self.rthread.radio.validate_memory(mem)
        if msgs:
            common.show_error("Error setting memory:\r\n" + \
                                  "\r\n".join(msgs))
            self.prefill()
            return

        mem.empty = False

        job = common.RadioJob(self._set_memory_cb, "set_memory", mem)
        job.set_desc("Writing memory %i" % mem.number)
        self.rthread.submit(job)

        self.store.set(iter, self.col("_filled"), True)

        self.maybe_hide_cols(iter)

        persist_defaults = ["Power", "Frequency"]
        if cap in persist_defaults:
            self.defaults[cap] = new

    def _render(self, colnum, val, iter=None, hide=[]):
        if colnum in hide and self.hide_unused:
            return ""

        if colnum == self.col("Frequency"):
            val = chirp_common.format_freq(val)
        elif colnum == self.col("DTCS Code"):
            val = "%03i" % int(val)
        elif colnum == self.col("Offset"):
            val = chirp_common.format_freq(val)
        elif colnum in [self.col("Tone"), self.col("ToneSql")]:
            val = "%.1f" % val
        elif colnum in [self.col("Tone Mode"), self.col("Duplex")]:
            if not val:
                val = "(None)"
        elif colnum == self.col("Loc") and iter is not None:
            extd, = self.store.get(iter, self.col("_extd"))
            if extd:
                val = extd


        return val

    def render(self, _, rend, model, iter, colnum):
        val, hide = model.get(iter, colnum, self.col("_hide_cols"))
        val = self._render(colnum, val, iter, hide or [])
        rend.set_property("text", "%s" % val)

    def insert_new(self, iter, loc=None):
        line = []
        for key, val in self.defaults.items():
            line.append(self.col(key))
            line.append(val)
        
        if not loc:
            loc, = self.store.get(iter, self.col("Loc"))

        self.store.set(iter,
                       0, loc,
                       *tuple(line))
        
        return self._get_memory(iter)

    def insert_easy(self, store, _iter, delta):
        if delta < 0:
            iter = store.insert_before(_iter)
        else:
            iter = store.insert_after(_iter)

        newpos, = store.get(_iter, self.col("Loc"))
        newpos += delta

        print "Insert easy: %i" % delta

        mem = self.insert_new(iter, newpos)
        job = common.RadioJob(None, "set_memory", mem)
        job.set_desc("Writing memory %i" % mem.number)
        self.rthread.submit(job)

    def insert_hard(self, store, _iter, delta, warn=True):
	if isinstance(self.rthread.radio, chirp_common.LiveRadio) and warn:
            txt = """This operation requires moving all subsequent channels
by one spot until an empty location is reached.  This can take a LONG
time.  Are you sure you want to do this?"""
            if not common.ask_yesno_question(txt):
                return

        if delta <= 0:
            iter = _iter
        else:
            iter = store.iter_next(_iter)

        pos, = store.get(iter, self.col("Loc"))

        sd = shiftdialog.ShiftDialog(self.rthread)

        if delta == 0:
            sd.delete(pos)
            sd.destroy()
            self.prefill()
        else:
            sd.insert(pos)
            sd.destroy()
            mem = chirp_common.Memory()
            mem.number = pos
            mem.empty = True
            job = common.RadioJob(lambda x: self.prefill(), "set_memory", mem)
            job.set_desc("Adding memory %i" % mem.number)
            self.rthread.submit(job)


    def mh(self, _action, store, paths):
        action = _action.get_name()
        iter = store.get_iter(paths[0])
        cur_pos, = store.get(iter, self.col("Loc"))

        if action == "insert_next":
            self.insert_hard(store, iter, 1)
            self.emit("changed")
        elif action == "insert_prev":
            self.insert_hard(store, iter, -1)
            self.emit("changed")
        elif action == "delete":
            for path in paths:
                iter = store.get_iter(path)
                cur_pos, = store.get(iter, self.col("Loc"))
                store.set(iter, self.col("_filled"), False)
                job = common.RadioJob(None, "erase_memory", cur_pos)
                job.set_desc("Erasing memory %i" % cur_pos)
                self.rthread.submit(job)
                
                def handler(mem):
                    if not isinstance(mem, Exception):
                        if not mem.empty or self.show_empty:
                            gobject.idle_add(self.set_memory, mem)
                
                job = common.RadioJob(handler, "get_memory", cur_pos)
                job.set_desc("Getting memory %s" % cur_pos)
                self.rthread.submit(job)
                
                if not self.show_empty:
                    store.remove(iter)

            self.emit("changed")

        elif action == "delete_s":
            starting_loc, = store.get(iter, self.col("Loc"))

            # Check that they are all contiguous
            for path in paths[1:]:
                if store.get_path(store.iter_next(iter)) != path:
                    common.show_error("This operation only works on " + \
                                          "contiguous memories")
                    return
                iter = store.iter_next(iter)

            for i in range(0, len(paths)):
                sd = shiftdialog.ShiftDialog(self.rthread)
                sd.delete(starting_loc, quiet=True)
                sd.destroy()

            self.prefill()
            self.emit("changed")
        elif action in ["cut", "copy"]:
            self.copy_selection(action=="cut")
        elif action == "paste":
            self.paste_selection()
        elif action == "devshowraw":

            def idle_show_raw(result):
                gobject.idle_add(show_blob, "Raw memory %i" % cur_pos, result)

            job = common.RadioJob(idle_show_raw, "get_raw_memory", cur_pos)
            job.set_desc("Getting raw memory %i" % cur_pos)
            self.rthread.submit(job)
        elif action == "devdiffraw":
            if len(paths) != 2:
                common.show_error("You can only diff two memories!")
                return

            loc_a = store.get(store.get_iter(paths[0]), self.col("Loc"))[0]
            loc_b = store.get(store.get_iter(paths[1]), self.col("Loc"))[0]

            raw = {}

            def simple_diff(a, b):
                lines_a = a.split(os.linesep)
                lines_b = b.split(os.linesep)

                diff = ""
                for i in range(0, len(lines_a)):
                    if lines_a[i] != lines_b[i]:
                        diff += "-%s%s" % (lines_a[i], os.linesep)
                        diff += "+%s%s" % (lines_b[i], os.linesep)
                    else:
                        diff += " %s%s" % (lines_a[i], os.linesep)
                return diff

            def diff_raw(which, result):
                raw[which] = "Memory %i:%s%s" % (which, os.linesep, result)

                if len(raw.keys()) == 2:
                    diff = simple_diff(raw[loc_a], raw[loc_b])
                    gobject.idle_add(show_blob,
                                     "Diff of %i and %i" % (loc_a, loc_b),
                                     diff)

            job = common.RadioJob(lambda r: diff_raw(loc_a, r),
                                  "get_raw_memory", loc_a)
            job.set_desc("Getting raw memory %i" % loc_a)
            self.rthread.submit(job)

            job = common.RadioJob(lambda r: diff_raw(loc_b, r),
                                  "get_raw_memory", loc_b)
            job.set_desc("Getting raw memory %i" % loc_b)
            self.rthread.submit(job)

    def make_context_menu(self):
        if self._config.get_bool("developer", "state"):
            devmenu = """
<separator/>
<menuitem action="devshowraw"/>
<menuitem action="devdiffraw"/>
"""
        else:
            devmenu = ""

        menu_xml = """
<ui>
  <popup name="Menu">
    <menuitem action="insert_prev"/>
    <menuitem action="insert_next"/>
    <menuitem action="delete"/>
    <menuitem action="delete_s"/>
    <separator/>
    <menuitem action="cut"/>
    <menuitem action="copy"/>
    <menuitem action="paste"/>
    %s
  </popup>
</ui>
""" % devmenu


        (store, paths) = self.view.get_selection().get_selected_rows()
        issingle = len(paths) == 1
        istwo = len(paths) == 2

        actions = [
            ("insert_prev", "Insert row above"),
            ("insert_next", "Insert row below"),
            ("delete", issingle and "Delete" or "Delete all"),
            ("delete_s", "Delete (and shift up)"),
            ("cut", "Cut"),
            ("copy", "Copy"),
            ("paste", "Paste"),
            ("devshowraw", "Show Raw Memory"),
            ("devdiffraw", "Diff Raw Memories"),
            ]

        no_multiple = ["insert_prev", "insert_next", "paste", "devshowraw"]
        only_two = ["devdiffraw"]

        ag = gtk.ActionGroup("Menu")

        for name, label in actions:
            a = gtk.Action(name, label, "", 0)
            a.connect("activate", self.mh, store, paths)
            if name in no_multiple:
                a.set_sensitive(issingle)
            if name in only_two:
                a.set_sensitive(istwo)
            ag.add_action(a)

        uim = gtk.UIManager()
        uim.insert_action_group(ag, 0)
        uim.add_ui_from_string(menu_xml)

        return uim.get_widget("/Menu")

    def click_cb(self, view, event):
        if event.button != 3:
            return False

        menu = self.make_context_menu()
        menu.popup(None, None, None, event.button, event.time)

        return True
        
    def get_column_visible(self, col):
        column = self.view.get_column(col)
        return column.get_visible()

    def set_column_visible(self, col, visible):
        column = self.view.get_column(col)
        column.set_visible(visible)
    
    def make_editor(self):
        types = tuple([x[1] for x in self.cols])
        self.store = gtk.ListStore(*types)

        self.view = gtk.TreeView(self.store)
        self.view.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.view.set_rules_hint(True)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.view)

        filled = self.col("_filled")

        i = 0
        for _cap, _type, _rend in self.cols:
            if not _rend:
                continue
            rend = _rend()
            if _type == TYPE_BOOLEAN:
                #rend.set_property("activatable", True)
                #rend.connect("toggled", handle_toggle, self.store, i)
                col = gtk.TreeViewColumn(_cap, rend, active=i, sensitive=filled)
            elif _rend == gtk.CellRendererCombo:
                if isinstance(self.choices[_cap], gtk.ListStore):
                    choices = self.choices[_cap]
                else:
                    choices = gtk.ListStore(TYPE_STRING, TYPE_STRING)
                    for choice in self.choices[_cap]:
                        choices.append([choice, self._render(i, choice)])
                rend.set_property("model", choices)
                rend.set_property("text-column", 1)
                rend.set_property("editable", True)
                rend.set_property("has-entry", False)
                rend.connect("edited", self.edited, _cap)
                col = gtk.TreeViewColumn(_cap, rend, text=i, sensitive=filled)
                col.set_cell_data_func(rend, self.render, i)
            else:
                rend.set_property("editable", True)
                rend.connect("edited", self.edited, _cap)
                col = gtk.TreeViewColumn(_cap, rend, text=i, sensitive=filled)
                col.set_cell_data_func(rend, self.render, i)
                
            col.set_sort_column_id(i)
            col.set_resizable(True)
            col.set_min_width(1)
            col.set_visible(not _cap.startswith("_"))
            self.view.append_column(col)

            i += 1

        self.store.set_sort_column_id(self.col("Loc"), gtk.SORT_ASCENDING)

        self.view.show()
        sw.show()

        self.view.connect("button_press_event", self.click_cb)

        return sw

    def col(self, caption):
        try:
            return self._cached_cols[caption]
        except KeyError:
            raise Exception("Internal Error: Column %s not found" % caption)

    def prefill(self):
        self.store.clear()

        lo = int(self.lo_limit_adj.get_value())
        hi = int(self.hi_limit_adj.get_value())

        def handler(mem):
            if not isinstance(mem, Exception):
                if not mem.empty or self.show_empty:
                    gobject.idle_add(self.set_memory, mem)

        for i in range(lo, hi+1):
            job = common.RadioJob(handler, "get_memory", i)
            job.set_desc("Getting memory %s" % i)
            self.rthread.submit(job, 2)

        if self.show_special:
            for i in self.rthread.radio.get_special_locations():
                job = common.RadioJob(handler, "get_memory", i)
                job.set_desc("Getting channel %s" % i)
                self.rthread.submit(job, 2)

    def _set_memory(self, iter, memory):
        try:
            if memory.bank is None:
                bank = ""
            else:
                pathstr = "%i" % (memory.bank + 1)
                bi = self.choices["Bank"].get_iter_from_string(pathstr)
                bank, = self.choices["Bank"].get(bi, 1)
        except Exception, e:
            common.log_exception()
            print "Unable to get bank: %s" % e
            bank = ""

        features = self.rthread.radio.get_features()

        self.store.set(iter,
                       self.col("_filled"), not memory.empty,
                       self.col("Loc"), memory.number,
                       self.col("_extd"), memory.extd_number,
                       self.col("Name"), memory.name,
                       self.col("Frequency"), memory.freq,
                       self.col("Tone Mode"), memory.tmode,
                       self.col("Tone"), memory.rtone,
                       self.col("ToneSql"), memory.ctone,
                       self.col("DTCS Code"), memory.dtcs,
                       self.col("DTCS Pol"), memory.dtcs_polarity,
                       self.col("Cross Mode"), memory.cross_mode,
                       self.col("Duplex"), memory.duplex,
                       self.col("Offset"), memory.offset,
                       self.col("Mode"), memory.mode,
                       self.col("Power"), memory.power or "",
                       self.col("Tune Step"), memory.tuning_step,
                       self.col("Skip"), memory.skip,
                       self.col("Bank"), bank,
                       self.col("Bank Index"), memory.bank_index)

        hide = self._get_cols_to_hide(iter)
        self.store.set(iter, self.col("_hide_cols"), hide)

    def set_memory(self, memory):
        iter = self.store.get_iter_first()

        while iter is not None:
            loc, = self.store.get(iter, self.col("Loc"))
            if loc == memory.number:
                return self._set_memory(iter, memory)

            iter = self.store.iter_next(iter)

        iter = self.store.append()
        self._set_memory(iter, memory)

    def clear_memory(self, number):
        iter = self.store.get_iter_first()
        while iter:
            loc, = self.store.get(iter, self.col("Loc"))
            if loc == number:
                print "Deleting %i" % number
                # FIXME: Make the actual remove happen on callback
                self.store.remove(iter)
                job = common.RadioJob(None, "erase_memory", number)
                job.set_desc("Erasing memory %i" % number)
                self.rthread.submit()
                break
            iter = self.store.iter_next(iter)

    def _set_mem_vals(self, mem, vals, iter):
        def get_bank_index(name):
            bidx = 0
            banks = self.choices["Bank"]
            iter = banks.get_iter_first()
            iter = banks.iter_next(iter)
            while iter:
                _bank, = banks.get(iter, 1)
                if name == _bank:
                    break
                iter = banks.iter_next(iter)
                bidx += 1

            return bidx

        features = self.rthread.radio.get_features()

        bank = vals[self.col("Bank")]
        if bank is "":
            bidx = None
            bank_index = vals[self.col("Bank Index")]
        else:
            bidx = get_bank_index(bank)
            if vals[self.col("Bank Index")] == -1 and features.has_bank_index:
                bank_index = self.rthread.radio.get_available_bank_index(bidx)
                print "Chose %i index for bank %s" % (bank_index, bank)
                self.store.set(iter, self.col("Bank Index"), bank_index)
            else:
                bank_index = vals[self.col("Bank Index")]

        power_levels = {"" : None}
        for i in features.valid_power_levels:
            power_levels[str(i)] = i

        mem.freq = vals[self.col("Frequency")]
        mem.number = vals[self.col("Loc")]
        mem.extd_number = vals[self.col("_extd")]
        mem.name = vals[self.col("Name")]
        mem.vfo = 0
        mem.rtone = vals[self.col("Tone")]
        mem.ctone = vals[self.col("ToneSql")]
        mem.dtcs = vals[self.col("DTCS Code")]
        mem.tmode = vals[self.col("Tone Mode")]
        mem.cross_mode = vals[self.col("Cross Mode")]
        mem.dtcs_polarity = vals[self.col("DTCS Pol")]
        mem.duplex = vals[self.col("Duplex")]
        mem.offset = vals[self.col("Offset")]
        mem.mode = vals[self.col("Mode")]
        mem.power = power_levels[vals[self.col("Power")]]
        mem.tuning_step = vals[self.col("Tune Step")]
        mem.skip = vals[self.col("Skip")]
        mem.bank = bidx
        mem.bank_index = bank_index
        mem.empty = not vals[self.col("_filled")]

    def _get_memory(self, iter):
        vals = self.store.get(iter, *range(0, len(self.cols)))
        mem = chirp_common.Memory()
        self._set_mem_vals(mem, vals, iter)

        return mem

    def _limit_key(self, which):
        if which not in ["lo", "hi"]:
            raise Exception("Internal Error: Invalid limit %s" % which)
        return "%s_%s" % (directory.get_driver(self.rthread.radio.__class__),
                          which)

    def _store_limit(self, sb, which):
        self._config.set_int(self._limit_key(which), int(sb.get_value()))

    def make_controls(self, min, max):
        hbox = gtk.HBox(False, 2)

        lab = gtk.Label("Memory range:")
        lab.show()
        hbox.pack_start(lab, 0, 0, 0)

        lokey = self._limit_key("lo")
        hikey = self._limit_key("hi")
        lostart = self._config.is_defined(lokey) and \
            self._config.get_int(lokey) or min
        histart = self._config.is_defined(hikey) and \
            self._config.get_int(hikey) or 25

        self.lo_limit_adj = gtk.Adjustment(lostart, min, max-1, 1, 10)
        lo = gtk.SpinButton(self.lo_limit_adj)
        lo.connect("value-changed", self._store_limit, "lo")
        lo.show()
        hbox.pack_start(lo, 0, 0, 0)

        lab = gtk.Label(" - ")
        lab.show()
        hbox.pack_start(lab, 0, 0, 0)

        self.hi_limit_adj = gtk.Adjustment(histart, min+1, max, 1, 10)
        hi = gtk.SpinButton(self.hi_limit_adj)
        hi.connect("value-changed", self._store_limit, "hi")
        hi.show()
        hbox.pack_start(hi, 0, 0, 0)

        refresh = gtk.Button("Go")
        refresh.show()
        refresh.connect("clicked", lambda x: self.prefill())
        hbox.pack_start(refresh, 0, 0, 0)

        def activate_go(widget):
            refresh.clicked()

        def set_hi(widget, event):
            loval = self.lo_limit_adj.get_value()
            hival = self.hi_limit_adj.get_value()
            if loval >= hival:
                self.hi_limit_adj.set_value(loval + 25)
        
        lo.connect_after("focus-out-event", set_hi)
        lo.connect_after("activate", activate_go)
        hi.connect_after("activate", activate_go)

        sep = gtk.VSeparator()
        sep.show()
        sep.set_size_request(20, -1)
        hbox.pack_start(sep, 0, 0, 0)

        showspecial = gtk.CheckButton("Special Channels")
        showspecial.set_active(self.show_special)
        showspecial.connect("toggled",
                            lambda x: self.set_show_special(x.get_active()))
        showspecial.show()
        hbox.pack_start(showspecial, 0, 0, 0)

        showempty = gtk.CheckButton("Show Empty")
        showempty.set_active(self.show_empty);
        showempty.connect("toggled",
                          lambda x: self.set_show_empty(x.get_active()))
        showempty.show()
        hbox.pack_start(showempty, 0, 0, 0)

        hbox.show()

        return hbox

    def set_bank_list(self, banks):
        self.choices["Bank"].clear()
        self.choices["Bank"].append(("", "(None)"))

        i = ord("A")
        for bank in banks:
            self.choices["Bank"].append((str(bank),
                                         ("%s-%s" % (chr(i), str(bank)))))
            i += 1
        
    def set_show_special(self, show):
        self.show_special = show
        self.prefill()
        self._config.set_bool("show_special", show)

    def set_show_empty(self, show):
        self.show_empty = show
        self.prefill()
        self._config.set_bool("hide_empty", not show)

    def set_read_only(self, read_only):
        self.read_only = read_only

    def set_hide_unused(self, hide_unused):
        self.hide_unused = hide_unused
        self.prefill()
        self._config.set_bool("hide_unused", hide_unused)

    def __cache_columns(self):
        # We call self.col() a lot.  Caching the name->column# lookup
        # makes a significant performance improvement
        self._cached_cols = {}
        i = 0
        for x in self.cols:
            self._cached_cols[x[0]] = i
            i += 1

    def get_unsupported_columns(self):
        maybe_hide = [
            ("has_bank_index", "Bank Index"),
            ("has_bank", "Bank"),
            ("has_dtcs", "DTCS Code"),
            ("has_dtcs_polarity", "DTCS Pol"),
            ("has_mode", "Mode"),
            ("has_offset", "Offset"),
            ("has_name", "Name"),
            ("has_tuning_step", "Tune Step"),
            ("has_name", "Name"),
            ("has_ctone", "ToneSql"),
            ("has_cross", "Cross Mode"),
            ("valid_tmodes", "Tone Mode"),
            ("valid_tmodes", "Tone"),
            ("valid_duplexes", "Duplex"),
            ("valid_skips", "Skip"),
            ("valid_power_levels", "Power"),
            ]

        unsupported = []
        features = self.rthread.radio.get_features()
        for feature, colname in maybe_hide:
            if feature.startswith("has_"):
                supported = features[feature]
                print "%s supported: %s" % (colname, supported)
            elif feature.startswith("valid_"):
                supported = len(features[feature]) != 0

            if not supported:
                unsupported.append(colname)

        return unsupported

    def set_columns_visible(self):
        unsupported = self.get_unsupported_columns()
        driver = directory.get_driver(self.rthread.radio.__class__)
        user_visible = self._config.get(driver, "memedit_columns")
        if user_visible:
            user_visible = user_visible.split(",")
        else:
            # No setting for this radio, so assume all
            user_visible = [x[0] for x in self.cols if x not in unsupported]

        for colname in [colspec[0] for colspec in self.cols]:
            if colname.startswith("_"):
                continue
            bi = self.view.get_column(self.col(colname))
            bi.set_visible(colname not in unsupported and \
                               colname in user_visible)

    def __init__(self, rthread):
        common.Editor.__init__(self)
        self.rthread = rthread

        self.defaults = dict(self.defaults)

        self._config = config.get("memedit")

        self.allowed_bands = [144, 440]
        self.count = 100
        self.show_special = self._config.get_bool("show_special")
        self.show_empty = not self._config.get_bool("hide_empty")
        self.hide_unused = self._config.get_bool("hide_unused")
        self.read_only = False

        self.need_refresh = False

        self.lo_limit_adj = self.hi_limit_adj = None
        self.store = self.view = None

        self.__cache_columns()

        features = self.rthread.radio.get_features()

        (min, max) = features.memory_bounds

        self.choices["Bank"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["Mode"] = features["valid_modes"]
        self.choices["Tone Mode"] = features["valid_tmodes"]
        self.choices["Skip"] = features["valid_skips"]
        self.choices["Power"] = [str(x) for x in features["valid_power_levels"]]

        if features["valid_power_levels"]:
            self.defaults["Power"] = features["valid_power_levels"][0]

        job = common.RadioJob(self.set_bank_list, "get_banks")
        job.set_desc("Getting bank list")
        rthread.submit(job)

        if not features["can_odd_split"]:
            # We need a new list, so .remove() won't work for us
            self.choices["Duplex"] = [x for x in self.choices["Duplex"]
                                      if x != "split"]

        vbox = gtk.VBox(False, 2)
        vbox.pack_start(self.make_controls(min, max), 0, 0, 0)
        vbox.pack_start(self.make_editor(), 1, 1, 1)
        vbox.show()

        self.prefill()
        
        self.choices["Mode"] = features.valid_modes

        self.root = vbox

        self.set_columns_visible()

        self.prefill()

        # Run low priority jobs to get the rest of the memories
        hi = int(self.hi_limit_adj.get_value())
        for i in range(hi, max+1):
            job = common.RadioJob(None, "get_memory", i)
            job.set_desc("Getting memory %i" % i)
            self.rthread.submit(job, 10)

    def _set_memory_cb(self, result):
        if isinstance(result, Exception):
            # FIXME: This can't be in the thread
            dlg = ValueErrorDialog(result)
            dlg.run()
            dlg.destroy()
            self.prefill()
        elif self.need_refresh:
            self.prefill()
            self.need_refresh = False

        self.emit('changed')

    def copy_selection(self, cut=False):
        (store, paths) = self.view.get_selection().get_selected_rows()

        maybe_cut = []
        selection = []

        for path in paths:
            iter = store.get_iter(path)
            mem = self._get_memory(iter)
            selection.append(mem.dupe())
            maybe_cut.append((iter, mem))
        
        if cut:
            for iter, mem in maybe_cut:
                mem.empty = True
                job = common.RadioJob(self._set_memory_cb, "set_memory", mem)
                job.set_desc("Cutting memory %i" % mem.number)
                self.rthread.submit(job)

                self._set_memory(iter, mem)

        result = pickle.dumps(selection)
        clipboard = gtk.Clipboard(selection="PRIMARY")
        clipboard.set_text(result)

        return result        

    def _paste_selection(self, clipboard, text, data):
        if not text:
            return

        (store, paths) = self.view.get_selection().get_selected_rows()
        if len(paths) > 1:
            common.show_error("To paste, select only the starting location")
            return

        iter = store.get_iter(paths[0])

        always = False

        try:
            mem_list = pickle.loads(text)
        except Exception:
            print "Paste failed to unpickle"
            return

        for mem in pickle.loads(text):
            loc, filled = store.get(iter, self.col("Loc"), self.col("_filled"))
            if filled and not always:
                d = miscwidgets.YesNoDialog(title="Overwrite?",
                                            buttons=(gtk.STOCK_YES, 1,
                                                     gtk.STOCK_NO, 2,
                                                     gtk.STOCK_CANCEL, 3,
                                                     "All", 4))
                d.set_text("Overwrite location %i?" % loc)
                r = d.run()
                d.destroy()
                if r == 4:
                    always = True
                elif r == 3:
                    break
                elif r == 2:
                    iter = store.iter_next(iter)
                    continue

            mem.name = self.rthread.radio.filter_name(mem.name)
            if not self.rthread.radio.get_features().has_bank:
                mem.bank = None
                mem.bank_index = -1

            src_number = mem.number
            mem.number = loc
            msgs = self.rthread.radio.validate_memory(mem)
            if msgs:
                d = miscwidgets.YesNoDialog(title="Incompatible Memory",
                                            buttons=(gtk.STOCK_OK, 1,
                                                     gtk.STOCK_CANCEL, 2))
                d.set_text("Pasted memory %i is not compatible with this radio because:%s%s" %\
                               (src_number, os.linesep, os.linesep.join(msgs)))
                r = d.run()
                d.destroy()
                if r == 2:
                    break
                else:
                    iter = store.iter_next(iter)
                    continue

            self._set_memory(iter, mem)
            iter = store.iter_next(iter)

            job = common.RadioJob(self._set_memory_cb, "set_memory", mem)
            job.set_desc("Writing memory %i" % mem.number)
            self.rthread.submit(job)

    def paste_selection(self):
        clipboard = gtk.Clipboard(selection="PRIMARY")
        clipboard.request_text(self._paste_selection)

class DstarMemoryEditor(MemoryEditor):
    def _get_cols_to_hide(self, iter):
        hide = MemoryEditor._get_cols_to_hide(self, iter)

        mode, = self.store.get(iter, self.col("Mode"))
        if mode != "DV":
            hide += [self.col("URCALL"),
                     self.col("RPT1CALL"),
                     self.col("RPT2CALL")]

        return hide

    def render(self, _, rend, model, iter, colnum):
        MemoryEditor.render(self, _, rend, model, iter, colnum)

        vals = model.get(iter, *tuple(range(0, len(self.cols))))
        val = vals[colnum]

        def _enabled(sensitive):
            rend.set_property("sensitive", sensitive)

        def d_unless_mode(mode):
            _enabled(vals[self.col("Mode")] == mode)

        _dv_columns = ["URCALL", "RPT1CALL", "RPT2CALL", "Digital Code"]
        dv_columns = [self.col(x) for x in _dv_columns]
        if colnum in dv_columns:
            d_unless_mode("DV")

    def _get_memory(self, iter):
        vals = self.store.get(iter, *range(0, len(self.cols)))
        if vals[self.col("Mode")] != "DV":
            return MemoryEditor._get_memory(self, iter)

        mem = chirp_common.DVMemory()

        MemoryEditor._set_mem_vals(self, mem, vals, iter)

        mem.dv_urcall = vals[self.col("URCALL")]
        mem.dv_rpt1call = vals[self.col("RPT1CALL")]
        mem.dv_rpt2call = vals[self.col("RPT2CALL")]
        mem.dv_code = vals[self.col("Digital Code")]

        return mem

    def __init__(self, rthread):
        # I think self.cols is "static" or "unbound" or something else
        # like that and += modifies the type, not self (how bizarre)
        self.cols = list(self.cols)
        new_cols = [("URCALL", TYPE_STRING, gtk.CellRendererCombo),
                    ("RPT1CALL", TYPE_STRING, gtk.CellRendererCombo),
                    ("RPT2CALL", TYPE_STRING, gtk.CellRendererCombo),
                    ("Digital Code", TYPE_INT, gtk.CellRendererText),
                    ]
        for col in new_cols:
            index = self.cols.index(("_filled", TYPE_BOOLEAN, None))
            self.cols.insert(index, col)

        self.choices = dict(self.choices)
        self.defaults = dict(self.defaults)

        self.choices["URCALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT1CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT2CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)

        self.defaults["URCALL"] = ""
        self.defaults["RPT1CALL"] = ""
        self.defaults["RPT2CALL"] = ""
        self.defaults["Digital Code"] = 0

        MemoryEditor.__init__(self, rthread)
    
        def ucall_cb(calls):
            self.defaults["URCALL"] = calls[0]
            for call in calls:
                self.choices["URCALL"].append((call, call))
        
        if self.rthread.radio.get_features().requires_call_lists:
            ujob = common.RadioJob(ucall_cb, "get_urcall_list")
            ujob.set_desc("Downloading URCALL list")
            rthread.submit(ujob)

        def rcall_cb(calls):
            self.defaults["RPT1CALL"] = calls[0]
            self.defaults["RPT2CALL"] = calls[0]
            for call in calls:
                self.choices["RPT1CALL"].append((call, call))
                self.choices["RPT2CALL"].append((call, call))

        if self.rthread.radio.get_features().requires_call_lists:
            rjob = common.RadioJob(rcall_cb, "get_repeater_call_list")
            rjob.set_desc("Downloading RPTCALL list")
            rthread.submit(rjob)

        _dv_columns = ["URCALL", "RPT1CALL", "RPT2CALL", "Digital Code"]

        if not rthread.radio.get_features().requires_call_lists:
            for i in _dv_columns:
                if not self.choices.has_key(i):
                    continue
                column = self.view.get_column(self.col(i))
                rend = column.get_cell_renderers()[0]
                rend.set_property("has-entry", True)

        for i in _dv_columns:
            col = self.view.get_column(self.col(i))
            rend = col.get_cell_renderers()[0]
            rend.set_property("family", "Monospace")

    def set_urcall_list(self, urcalls):
        store = self.choices["URCALL"]

        store.clear()
        for call in urcalls:
            store.append((call, call))

    def set_repeater_list(self, repeaters):
        for listname in ["RPT1CALL", "RPT2CALL"]:
            store = self.choices[listname]

            store.clear()
            for call in repeaters:
                store.append((call, call))

    def _set_memory(self, iter, memory):
        MemoryEditor._set_memory(self, iter, memory)

        if isinstance(memory, chirp_common.DVMemory):
            self.store.set(iter,
                           self.col("URCALL"), memory.dv_urcall,
                           self.col("RPT1CALL"), memory.dv_rpt1call,
                           self.col("RPT2CALL"), memory.dv_rpt2call,
                           self.col("Digital Code"), memory.dv_code,
                           )
        else:
            self.store.set(iter,
                           self.col("URCALL"), "",
                           self.col("RPT1CALL"), "",
                           self.col("RPT2CALL"), "",
                           self.col("Digital Code"), 0,
                           )

class ID800MemoryEditor(DstarMemoryEditor):
    pass
