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

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

import threading

import gtk
from gobject import TYPE_INT, \
    TYPE_DOUBLE as TYPE_FLOAT, \
    TYPE_STRING, \
    TYPE_BOOLEAN
import gobject

import common
from chirp import chirp_common, errors

def handle_toggle(rend, path, store, col):
    store[path][col] = not store[path][col]    

def handle_ed(rend, path, new, store, col):
    iter = store.get_iter(path)
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

class MemoryEditor(common.Editor):
    cols = [
        ("Loc"       , TYPE_INT,    gtk.CellRendererText,  ),
        ("Name"      , TYPE_STRING, gtk.CellRendererText,  ), 
        ("Frequency" , TYPE_FLOAT,  gtk.CellRendererText,  ),
        ("Tone Mode" , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Tone"      , TYPE_FLOAT,  gtk.CellRendererCombo, ),
        ("ToneSql"   , TYPE_FLOAT,  gtk.CellRendererCombo, ),
        ("DTCS Code" , TYPE_INT,    gtk.CellRendererCombo, ),
        ("DTCS Pol"  , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Duplex"    , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Offset"    , TYPE_FLOAT,  gtk.CellRendererText,  ),
        ("Mode"      , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Tune Step" , TYPE_FLOAT,  gtk.CellRendererCombo, ),
        ]

    defaults = {
        "Name"      : "",
        "Frequency" : 146.010,
        "Tone"      : 88.5,
        "ToneSql"   : 88.5,
        "DTCS Code" : 23,
        "DTCS Pol"  : "NN",
        "Duplex"    : "",
        "Offset"    : 0.0,
        "Mode"      : "FM",
        "Tune Step" : 10.0,
        "Tone Mode" : "",
        }

    choices = {
        "Tone" : chirp_common.TONES,
        "ToneSql" : chirp_common.TONES,
        "DTCS Code" : chirp_common.DTCS_CODES,
        "DTCS Pol" : ["NN", "NR", "RN", "RR"],
        "Mode" : chirp_common.MODES,
        "Duplex" : ["", "-", "+"],
        "Tune Step" : [5, 10],
        "Tone Mode" : ["", "Tone", "TSQL", "DTCS"],
        }
    
    def ed_name(self, rend, path, new, col):
        return new[:self.name_length]

    def ed_freq(self, rend, path, new, col):
        def set_offset(path, offset):
            if offset > 0:
                dup = "+"
            elif offset == 0:
                dup = ""
            else:
                dup = "-"
                offset *= -1

            iter = self.store.get_iter(path)
            
            if offset:
                self.store.set(iter, self.col("Offset"), offset)

            self.store.set(iter, self.col("Duplex"), dup)

        try:
            new = float(new)
        except Exception, e:
            print e
            new = None

        if new:
            set_offset(path, 0)
            band = int(new / 100)
            if chirp_common.STD_OFFSETS.has_key(band):
                offsets = chirp_common.STD_OFFSETS[band]
                for lo, hi, offset in offsets:
                    if new < hi and new > lo:
                        set_offset(path, offset)
                        break

        return new

    def edited(self, rend, path, new, cap):
        colnum = self.col(cap)
        funcs = {
            "Name" : self.ed_name,
            "Frequency" : self.ed_freq,
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

        if not handle_ed(rend, path, new, self.store, self.col(cap)):
            # No change was made
            return

        iter = self.store.get_iter(path)
        mem = self._get_memory(iter)

        try:
            self.radio.set_memory(mem)
        except Exception, e:
            d = ValueErrorDialog(e)
            d.run()
            d.destroy()

        self.emit('changed')

    def _render(self, colnum, val):
        if colnum == self.col("Frequency"):
            val = "%.5f" % val
        elif colnum == self.col("DTCS Code"):
            val = "%03i" % int(val)
        elif colnum == self.col("Offset"):
            val = "%.3f" % val
        elif colnum in [self.col("Tone"), self.col("ToneSql")]:
            val = "%.1f" % val
        elif colnum in [self.col("Tone Mode"), self.col("Duplex")]:
            if not val:
                val = "(None)"

        return val

    def render(self, col, rend, model, iter, colnum):
        vals = model.get(iter, *tuple(range(0, len(self.cols))))
        val = vals[colnum]

        def _enabled(s):
            rend.set_property("sensitive", s)

        def d_unless_tmode(tmode):
            _enabled(vals[self.col("Tone Mode")] == tmode)

        def d_unless_dup():
            _enabled(vals[self.col("Duplex")])

        def d_if_mode(mode):
            _enabled(vals[self.col("Mode")] != mode)

        val = self._render(colnum, val)
        rend.set_property("text", "%s" % val)

        if colnum == self.col("DTCS Code"):
            d_unless_tmode("DTCS")
        elif colnum == self.col("DTCS Pol"):
            d_unless_tmode("DTCS")
        elif colnum == self.col("Tone"):
            d_unless_tmode("Tone")
            d_if_mode("DV")
        elif colnum == self.col("ToneSql"):
            d_unless_tmode("TSQL")
            d_if_mode("DV")
        elif colnum == self.col("Offset"):
            d_unless_dup()

    def mh(self, _action):
        action = _action.get_name()
        store, iter = self.view.get_selection().get_selected()
        curpos, = store.get(iter, self.col("Loc"))

        if action in ["insert_next", "insert_prev"]:
            line = []
            for k,v in self.defaults.items():
                line.append(self.col(k))
                line.append(v)

            
            if action == "insert_next":
                newiter = store.insert_after(iter)
                newpos = curpos + 1
            else:
                newiter = store.insert_before(iter)
                newpos = curpos - 1

            store.set(newiter,
                      0, newpos,
                      *tuple(line))

            mem = self._get_memory(newiter)
            self.radio.set_memory(mem)

        elif action == "delete":
            store.remove(iter)
            self.radio.erase_memory(curpos)

    def make_context_menu(self, loc, can_prev, can_next):
        menu_xml = """
<ui>
  <popup name="Menu">
    <menuitem action="insert_prev"/>
    <menuitem action="insert_next"/>
    <menuitem action="delete"/>
  </popup>
</ui>
"""

        actions = [
            ("insert_prev",None,"Insert row above",None,None, self.mh),
            ("insert_next",None,"Insert row below",None,None, self.mh),
            ("delete", None, "Delete", None, None, self.mh),
            ]

        ag = gtk.ActionGroup("Menu")
        ag.add_actions(actions)

        if not can_prev:
            action = ag.get_action("insert_prev")
            action.set_sensitive(False)

        if not can_next:
            action = ag.get_action("insert_next")
            action.set_sensitive(False)

        uim = gtk.UIManager()
        uim.insert_action_group(ag, 0)
        uim.add_ui_from_string(menu_xml)

        return uim.get_widget("/Menu")

    def click_cb(self, view, event):
        if event.button != 3:
            return

        store, iter = self.view.get_selection().get_selected()

        curpos, = store.get(iter, self.col("Loc"))
        next_loc = curpos + 1
        can_prev = True
        can_next = True

        next = store.iter_next(iter)
        if next:
            nextpos, = store.get(next, self.col("Loc"))
            if nextpos == (curpos + 1):
                can_next = False

        prev = iter_prev(store, iter)
        if prev:
            prevpos, = store.get(prev, self.col("Loc"))
            if prevpos == (curpos - 1) or curpos == 0:
                can_prev = False
        else:
            can_prev = False

        menu = self.make_context_menu(curpos, can_prev, can_next)
        menu.popup(None, None, None, event.button, event.time)
            
    def make_editor(self):
        types = tuple([x[1] for x in self.cols])
        self.store = gtk.ListStore(*types)

        self.view = gtk.TreeView(self.store)
        self.view.set_rules_hint(True)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.view)

        i = 0
        for c, t, r in self.cols:
            rend = r()
            if t == TYPE_BOOLEAN:
                rend.set_property("activatable", True)
                rend.connect("toggled", handle_toggle, self.store, i)
                col = gtk.TreeViewColumn(c, rend, active=i)
            elif r == gtk.CellRendererCombo:
                if isinstance(self.choices[c], gtk.ListStore):
                    choices = self.choices[c]
                else:
                    choices = gtk.ListStore(TYPE_STRING, TYPE_STRING)
                    for choice in self.choices[c]:
                        choices.append([choice, self._render(i, choice)])
                rend.set_property("model", choices)
                rend.set_property("text-column", 1)
                rend.set_property("editable", True)
                rend.set_property("has-entry", False)
                rend.connect("edited", self.edited, c)
                col = gtk.TreeViewColumn(c, rend, text=i)
                col.set_cell_data_func(rend, self.render, i)
            else:
                rend.set_property("editable", True)
                rend.connect("edited", self.edited, c)
                col = gtk.TreeViewColumn(c, rend, text=i)
                col.set_cell_data_func(rend, self.render, i)
                
            col.set_sort_column_id(i)
            col.set_resizable(True)
            col.set_min_width(1)
            self.view.append_column(col)

            i += 1

        self.view.show()
        sw.show()

        self.view.connect("button_press_event", self.click_cb)

        return sw

    def col(self, caption):
        i = 0
        for column in self.cols:
            if column[0] == caption:
                return i

            i += 1

        print "Not found: %s" % caption

        return None

    def _prefill(self):
        self.store.clear()

        lo = int(self.lo_limit_adj.get_value())
        hi = int(self.hi_limit_adj.get_value())

        import time
        t = time.time()

        for i in range(lo, hi+1):
            try:
                mem = self.radio.get_memory(i)
            except errors.InvalidMemoryLocation:
                mem = None

            if mem:
                gobject.idle_add(self.set_memory, mem)

        #mems = self.radio.get_memories(lo, hi)
        print "Loaded %i memories in %s sec" % (hi - lo,
                                                time.time() - t)

        self.fill_thread = None

        print "Fill thread ending"

    def prefill(self):
        if self.fill_thread:
            return

        self.fill_thread = threading.Thread(target=self._prefill)
        self.fill_thread.start()

    def _set_memory(self, iter, memory):
        if memory.dtcsEnabled:
            tmode = "DTCS"
        elif memory.tsqlEnabled:
            tmode = "TSQL"
        elif memory.tencEnabled:
            tmode = "Tone"
        else:
            tmode = ""

        self.store.set(iter,
                       self.col("Loc"), memory.number,
                       self.col("Name"), memory.name,
                       self.col("Frequency"), memory.freq,
                       self.col("Tone Mode"), tmode,
                       self.col("Tone"), memory.rtone,
                       self.col("ToneSql"), memory.ctone,
                       self.col("DTCS Code"), memory.dtcs,
                       self.col("DTCS Pol"), memory.dtcsPolarity,
                       self.col("Duplex"), memory.duplex,
                       self.col("Offset"), memory.offset,
                       self.col("Mode"), memory.mode,
                       self.col("Tune Step"), memory.tuningStep)

    def set_memory(self, memory):
        iter = self.store.get_iter_first()

        while iter is not None:
            loc, = self.store.get(iter, self.col("Loc"))
            if loc == memory.number:
                return self._set_memory(iter, memory)

            iter = self.store.iter_next(iter)

        iter = self.store.append()
        self._set_memory(iter, memory)

    def _set_mem_vals(self, mem, vals):
        mem.freq = vals[self.col("Frequency")]
        mem.number = vals[self.col("Loc")]
        mem.name = vals[self.col("Name")]
        mem.vfo = 0
        mem.rtone = vals[self.col("Tone")]
        mem.ctone = vals[self.col("ToneSql")]
        mem.dtcs = vals[self.col("DTCS Code")]
        mem.tencEnabled = mem.tsqlEnabled = mem.dtcsEnabled = False
        tmode = vals[self.col("Tone Mode")]
        if tmode == "Tone":
            mem.tencEnabled = True
        elif tmode == "TSQL":
            mem.tsqlEnabled = True
        elif tmode == "DTCS":
            mem.dtcsEnabled = True
        mem.dtcsPolarity = vals[self.col("DTCS Pol")]
        mem.duplex = vals[self.col("Duplex")]
        mem.offset = vals[self.col("Offset")]
        mem.mode = vals[self.col("Mode")]
        mem.tuningStep = vals[self.col("Tune Step")]

    def _get_memory(self, iter):
        vals = self.store.get(iter, *range(0, len(self.cols)))
        mem = chirp_common.Memory()
        self._set_mem_vals(mem, vals)

        return mem

    def make_controls(self):
        hbox = gtk.HBox(False, 2)

        lab = gtk.Label("Memory range:")
        lab.show()
        hbox.pack_start(lab, 0,0,0)

        self.lo_limit_adj = gtk.Adjustment(0, 0, 999, 1, 10)
        lo = gtk.SpinButton(self.lo_limit_adj)
        lo.show()
        hbox.pack_start(lo, 0,0,0)

        lab = gtk.Label(" - ")
        lab.show()
        hbox.pack_start(lab, 0,0,0)

        self.hi_limit_adj = gtk.Adjustment(25, 1, 999, 1, 10)
        hi = gtk.SpinButton(self.hi_limit_adj)
        hi.show()
        hbox.pack_start(hi, 0,0,0)

        refresh = gtk.Button("Go")
        refresh.show()
        refresh.connect("clicked", lambda x: self.prefill())
        hbox.pack_start(refresh, 0,0,0)

        hbox.show()

        return hbox

    def __init__(self, radio):
        common.Editor.__init__(self)
        self.radio = radio
        self.allowed_bands = [144, 440]
        self.count = 100
        self.name_length = 8

        self.fill_thread = None

        vbox = gtk.VBox(False, 2)
        vbox.pack_start(self.make_controls(), 0,0,0)
        vbox.pack_start(self.make_editor(), 1,1,1)
        vbox.show()
        
        self.root = vbox

        self.prefill()

class DstarMemoryEditor(MemoryEditor):
    def _get_memory(self, iter):
        if vals[self.col("Mode")] != "DV":
            return MemoryEditor._get_memory(self, iter)

        mem = chirp_common.DVMemory()

        MemoryEditor._set_mem_vals(mem, val)

        mem.UrCall = vals[self.col("URCALL")]
        mem.Rpt1Call = vals[self.col("RPT1CALL")]
        mem.Rpt2Call = vals[self.col("RPT2CALL")]

        return mem

    def __init__(self, radio):
        self.cols += [("URCALL", TYPE_STRING, gtk.CellRendererCombo),
                      ("RPT1CALL", TYPE_STRING, gtk.CellRendererCombo),
                      ("RPT2CALL", TYPE_STRING, gtk.CellRendererCombo)]

        self.choices["URCALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT1CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT2CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)

        iter = self.choices["URCALL"].append(("CQCQCQ", "CQCQCQ"))
        self.choices["RPT1CALL"].append(("", ""))
        self.choices["RPT2CALL"].append(("", ""))

        for call in radio.get_urcall_list():
            self.choices["URCALL"].append((call, call))
        
        for call in radio.get_repeater_call_list():
            self.choices["RPT1CALL"].append((call, call))
            self.choices["RPT2CALL"].append((call, call))

        self.defaults["URCALL"] = "CQCQCQ"
        self.defaults["RPT1CALL"] = ""
        self.defaults["RPT2CALL"] = ""

        MemoryEditor.__init__(self, radio)
    
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
                           self.col("URCALL"), memory.UrCall,
                           self.col("RPT1CALL"), memory.Rpt1Call,
                           self.col("RPT2CALL"), memory.Rpt2Call)
        else:
            self.store.set(iter,
                           self.col("URCALL"), "",
                           self.col("RPT1CALL"), "",
                           self.col("RPT2CALL"), "")

class ID800MemoryEditor(DstarMemoryEditor):
    pass

if __name__ == "__main__":
    from chirp import id800, ic9x, ic2820, ic2200, generic
    import serial
    r = id800.ID800v2Radio("../id800.img")
    #s = serial.Serial(port="/dev/ttyUSB1", baudrate=38400, timeout=0.2)
    #r = ic9x.IC9xRadioB(s)

    e = ID800MemoryEditor(r)
    w = gtk.Window()
    w.add(e.root)
    e.root.show()
    w.show()

    try:
        gtk.main()
    except KeyboardInterrupt:
        pass

    r.save_mmap("../id800.img")
