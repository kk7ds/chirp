import gtk
from gobject import TYPE_INT, \
    TYPE_DOUBLE as TYPE_FLOAT, \
    TYPE_STRING, \
    TYPE_BOOLEAN

import common
try:
    from chirp import chirp_common, id800
except ImportError:
    import sys
    sys.path.insert(0, "..")
    from chirp import chirp_common, id800, ic9x

def handle_toggle(rend, path, store, col):
    store[path][col] = not store[path][col]    

def handle_ed(rend, path, new, store, col):
    iter = store.get_iter(path)
    store.set(iter, col, new)

class ValueErrorDialog(gtk.MessageDialog):
    def __init__(self, exception, **args):
        gtk.MessageDialog.__init__(self, buttons=gtk.BUTTONS_OK, **args)
        self.set_property("text", "Invalid value for this field")
        self.format_secondary_text(str(exception))

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
        "Tone On"   : False,
        "ToneSql"   : 88.5,
        "ToneSql On": False,
        "DTCS Code" : 23,
        "DTCS On"   : False,
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

        handle_ed(rend, path, new, self.store, self.col(cap))

        iter = self.store.get_iter(path)
        mem = self._get_memory(iter)

        try:
            self.radio.set_memory(mem)
        except Exception, e:
            d = InvalidValueError(e)
            d.run()
            d.destroy()

    def _render(self, colnum, val):
        if colnum == self.col("Frequency"):
            val = "%.5f" % val
        elif colnum == self.col("DTCS Code"):
            val = "%03i" % int(val)
        elif colnum == self.col("Offset"):
            val = "%.3f" % val
        elif colnum in [self.col("Tone"), self.col("ToneSql")]:
            val = "%.1f" % val

        return val

    def render(self, col, rend, model, iter, colnum):
        val = self._render(colnum, model.get_value(iter, colnum))
        rend.set_property("text", "%s" % val)

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

        return sw

    def col(self, caption):
        i = 0
        for column in self.cols:
            if column[0] == caption:
                return i

            i += 1

        print "Not found: %s" % caption

        return None

    def prefill(self):
        mems = self.radio.get_memories()

        for mem in mems:
            self.set_memory(mem)

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

    def _get_memory(self, iter):
        vals = self.store.get(iter, *range(0, len(self.cols)))
        if vals[self.col("Mode")] == "DV":
            mem = chirp_common.DVMemory()
            mem.UrCall = vals[self.col("URCALL")]
            mem.Rpt1Call = vals[self.col("RPT1CALL")]
            mem.Rpt2Call = vals[self.col("RPT2CALL")]
        else:
            mem = chirp_common.Memory()

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

        return mem

    def __init__(self, radio):
        self.radio = radio
        self.allowed_bands = [144, 440]
        self.count = 100
        self.name_length = 8
        self.root = self.make_editor()
        self.prefill()

class LimitedDstarMemoryEditor(MemoryEditor):
    def __init__(self, *args):
        self.cols += [("URCALL", TYPE_STRING, gtk.CellRendererCombo),
                      ("RPT1CALL", TYPE_STRING, gtk.CellRendererCombo),
                      ("RPT2CALL", TYPE_STRING, gtk.CellRendererCombo)]

        self.choices["URCALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT1CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT2CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)

        iter = self.choices["URCALL"].append(("CQCQCQ", "CQCQCQ"))
        self.choices["RPT1CALL"].append(("", ""))
        self.choices["RPT2CALL"].append(("", ""))

        self.defaults["URCALL"] = "CQCQCQ"
        self.defaults["RPT1CALL"] = ""
        self.defaults["RPT2CALL"] = ""

        MemoryEditor.__init__(self, *args)
    
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
        self.store.set(iter,
                       self.col("URCALL"), memory.UrCall,
                       self.col("RPT1CALL"), memory.Rpt1Call,
                       self.col("RPT2CALL"), memory.Rpt2Call)

class ID800MemoryEditor(LimitedDstarMemoryEditor):
    pass

if __name__ == "__main__":
    import serial
    #r = id800.ID800v2Radio("../id800.img")
    s = serial.Serial(port="/dev/ttyUSB1", baudrate=38400, timeout=0.2)
    r = ic9x.IC9xRadioB(s)

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
