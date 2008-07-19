import gtk

import platform

RADIOS = [ "ic2820", "id800", "ic9x" ]

def make_choice(options, editable=True, default=None):
    if editable:
        sel = gtk.combo_box_entry_new_text()
    else:
        sel = gtk.combo_box_new_text()

    for o in options:
        sel.append_text(o)

    if default:
        try:
            idx = options.index(default)
            sel.set_active(idx)
        except:
            pass

    return sel

class StdButton(gtk.Button):
    def __init__(self, *args):
        gtk.Button.__init__(self, *args)

        self.set_size_request(75, 25)

class CsvDumpWindow(gtk.Window):
    def set_image_info(self, canUpload, canCsv, info):
        self.w_imginfo.set_text(info)
        self.w_uli.set_sensitive(canUpload)
        self.w_fileframe.set_sensitive(canCsv)

    def set_status(self, status):
        self.sb.pop(0)
        self.sb.push(0, status)

    def select_radio(self, box):
        radio = self.w_radio.get_active_text()
        port = self.w_port.get_active_text()
        self.w_imgframe.set_sensitive(radio != "ic9x")
        self.fn_radiosel(radio, port)

    def make_radio_sel(self):
        f = gtk.Frame("Radio")

        hbox = gtk.HBox(False, 2)
        hbox.set_border_width(2)
        
        self.w_radio = make_choice(RADIOS, False, RADIOS[0])
        self.w_radio.connect("changed", self.select_radio)
        self.w_radio.show()
        hbox.pack_start(self.w_radio, 1,1,1)

        l = gtk.Label(" on port ")
        l.show()
        hbox.pack_start(l, 0,0,0)

        ports = platform.get_platform().list_serial_ports()
        self.w_port = make_choice(ports, True, ports[0])
        self.w_port.connect("changed", self.select_radio)
        self.w_port.show()
        hbox.pack_start(self.w_port, 1,1,1)

        f.add(hbox)
        hbox.show()
        f.show()

        return f

    def make_image_ctl(self):
        self.w_imgframe = gtk.Frame("Image")

        vbox = gtk.VBox(False, 2)
        vbox.set_border_width(2)

        self.w_imginfo = gtk.Label("No image")
        self.w_imginfo.show()
        vbox.pack_start(self.w_imginfo, 0,0,0)

        hbox = gtk.HBox(True, 2)
        hbox.set_border_width(2)

        self.w_dli = StdButton("Download")
        self.w_dli.connect("clicked", lambda x: self.fn_download())
        self.w_dli.show()
        hbox.pack_start(self.w_dli, 0,0,0)

        self.w_uli = StdButton("Upload")
        self.w_uli.set_sensitive(False)
        self.w_uli.connect("clicked", lambda x: self.fn_upload())
        self.w_uli.show()
        hbox.pack_start(self.w_uli, 0,0,0)

        hbox.show()
        vbox.pack_start(hbox, 0,0,0)

        vbox.show()
        self.w_imgframe.add(vbox)
        self.w_imgframe.show()
        self.w_imgframe.set_sensitive(False)

        return self.w_imgframe

    def pick_file(self, button):
        fn = platform.get_platform().gui_save_file()
        if fn:
            self.w_filename.set_text(fn)

    def make_file_ctl(self):
        self.w_fileframe = gtk.Frame("File")

        vbox = gtk.VBox(False, 2)
        vbox.set_border_width(2)

        hbox = gtk.HBox(False, 2)
        hbox.set_border_width(2)

        l = gtk.Label("File")
        l.show()
        hbox.pack_start(l, 0,0,0)

        self.w_filename = gtk.Entry()
        self.w_filename.show()
        hbox.pack_start(self.w_filename, 1,1,1)
        
        bb = StdButton("Browse")
        bb.connect("clicked", self.pick_file)
        bb.show()
        hbox.pack_start(bb, 0,0,0)

        hbox.show()
        vbox.pack_start(hbox, 0,0,0)

        hbox = gtk.HBox(True, 2)
        hbox.set_border_width(2)

        eb = StdButton("Export")
        eb.connect("clicked",
                   lambda x: self.fn_eport(self.w_filename.get_text()))
        eb.show()
        hbox.pack_start(eb, 0,0,0)

        ib = StdButton("Import")
        ib.connect("clicked",
                   lambda x: self.fn_iport(self.w_filename.get_text()))
        ib.show()
        hbox.pack_start(ib, 0,0,0)

        hbox.show()
        vbox.pack_start(hbox, 0,0,0)

        vbox.show()
        self.w_fileframe.add(vbox)
        self.w_fileframe.show()

        return self.w_fileframe

    def make_status_bar(self):
        self.sb = gtk.Statusbar()
        self.sb.set_has_resize_grip(False)
        self.sb.show()

        return self.sb

    def __init__(self, radiosel, download, upload, iport, eport):
        gtk.Window.__init__(self)

        self.fn_radiosel = radiosel
        self.fn_download = download
        self.fn_upload = upload
        self.fn_iport = iport
        self.fn_eport = eport

        self.set_title("CHIRP: CSV Dump")
        self.set_resizable(False)

        vbox = gtk.VBox(False, 2)

        vbox.pack_start(self.make_radio_sel(), 0,0,0)
        vbox.pack_start(self.make_image_ctl(), 0,0,0)
        vbox.pack_start(self.make_file_ctl(), 0,0,0)
        vbox.pack_start(self.make_status_bar(), 0,0,0)

        vbox.show()
        self.add(vbox)

    def show(self):
        gtk.Window.show(self)

        self.select_radio(self.w_radio)

if __name__ == "__main__":
    def cb(arg=None):
        print "Callback: %s" % arg

    w = CsvDumpWindow(cb, cb, cb, cb)

    w.show()

    gtk.main()
