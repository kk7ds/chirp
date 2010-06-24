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

import os

import gtk
import gobject
gobject.threads_init()

import serial

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

from chirp import platform, xml, csv, directory, ic9x, thd7, idrp
from chirp import CHIRP_VERSION, convert_icf, chirp_common, detect
from chirpui import editorset, clone, inputdialog, miscwidgets, common

class ModifiedError(Exception):
    pass

class ChirpMain(gtk.Window):
    def get_current_editorset(self):
        page = self.tabs.get_current_page()
        if page is not None:
            return self.tabs.get_nth_page(page)
        else:
            return None

    def ev_tab_switched(self, pagenum=None):
        def set_action_sensitive(action, sensitive):
            self.menu_ag.get_action(action).set_sensitive(sensitive)

        if pagenum is not None:
            eset = self.tabs.get_nth_page(pagenum)
        else:
            eset = self.get_current_editorset()

        if not eset or \
                isinstance(eset.radio, ic9x.IC9xRadio) or \
                isinstance(eset.radio, thd7.THD7xRadio) or \
                isinstance(eset.radio, idrp.IDRPx000V):
            mmap_sens = False
        else:
            mmap_sens = True

        for i in ["save", "saveas", "cloneout"]:
            set_action_sensitive(i, mmap_sens)

        for i in ["cancelq"]:
            set_action_sensitive(i, eset is not None and not mmap_sens)
        
        for i in ["export", "import", "close", "columns"]:
            set_action_sensitive(i, eset is not None)

    def ev_status(self, editorset, msg):
        self.sb_radio.pop(0)
        self.sb_radio.push(0, msg)

    def do_new(self):
        eset = editorset.EditorSet("Untitled.chirp", self)
        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.prime()
        eset.show()

        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def do_open(self, fname=None):
        if not fname:
            types = [("CHIRP Radio Images (*.img)", "*.img"),
                     ("CHIRP Files (*.chirp)", "*.chirp"),
                     ("CSV Files (*.csv)", "*.csv"),
                     ]
            fname = platform.get_platform().gui_open_file(types=types)
            if not fname:
                return

        try:
            eset = editorset.EditorSet(fname, self)
        except Exception, e:
            common.log_exception()
            common.show_error("There was an error opening %s: %s" % (fname, e))
            return

        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.show()
        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def do_open_live(self, rclass, rtype):
        dlg = clone.CloneSettingsDialog(clone_in=False,
                                        filename="(live)",
                                        rtype=rtype)
        res = dlg.run()
        port, _, _ = dlg.get_values()
        dlg.destroy()

        if res != gtk.RESPONSE_OK:
            return
        
        ser = serial.Serial(port=port,
                            baudrate=rclass.BAUD_RATE,
                            timeout=0.1)
        radio = rclass(ser)
        
        eset = editorset.EditorSet(radio, self)
        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.show()

        action = self.menu_ag.get_action("openlive")
        action.set_sensitive(False)

        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def do_save(self, eset=None):
        if not eset:
            eset = self.get_current_editorset()
        eset.save()

    def do_saveas(self):
        eset = self.get_current_editorset()

        if isinstance(eset.radio, chirp_common.IcomMmapRadio):
            types = [("Radio-specific Image (*.img)", "*.img")]
        elif isinstance(eset.radio, csv.CSVRadio):
            types = [("CSV File (*.csv)", "*.csv")]
        elif isinstance(eset.radio, xml.XMLRadio):
            types = [("CHIRP File (*.chirp)", "*.chirp")]
        else:
            types = [("ERROR", "*.*")]

        while True:
            fname = platform.get_platform().gui_save_file(types=types)
            if not fname:
                return

            if os.path.exists(fname):
                dlg = inputdialog.OverwriteDialog(fname)
                owrite = dlg.run()
                dlg.destroy()
                if owrite == gtk.RESPONSE_OK:
                    break
            else:
                break

        eset.save(fname)

    def cb_clonein(self, radio, fn, emsg=None):
        radio.pipe.close()
        if not emsg:
            self.do_open(fn)
        else:
            d = inputdialog.ExceptionDialog(emsg)
            d.run()
            d.destroy()

    def cb_cloneout(self, radio, fn, emsg= None):
        radio.pipe.close()

    def record_recent_radio(self, port, rtype):
        if (port, rtype) in self._recent:
            return

        spid = "sep-%s%s" % (port.replace("/", ""), rtype)
        upid = "cloneout-%s%s" % (port.replace("/", ""), rtype)
        dnid = "clonein-%s%s" % (port.replace("/", ""), rtype)

        spaction = gtk.Action(spid, "", "", "")
        upaction = gtk.Action(upid,
                              "Upload to %s @ %s" % (rtype, port),
                              "Upload to recent radio", "")
        dnaction = gtk.Action(dnid,
                              "Download from %s @ %s" % (rtype, port),
                              "Download from recent radio", "")

        upaction.connect("activate", self.mh, port, rtype)
        dnaction.connect("activate", self.mh, port, rtype)

        id = self.menu_uim.new_merge_id()
        self.menu_uim.add_ui(id, "/MenuBar/radio/recent", upid, upid,
                             gtk.UI_MANAGER_MENUITEM, True)
        self.menu_uim.add_ui(id, "/MenuBar/radio/recent", dnid, dnid,
                             gtk.UI_MANAGER_MENUITEM, True)
        self.menu_uim.add_ui(id, "/MenuBar/radio/recent", spid, spid,
                             gtk.UI_MANAGER_SEPARATOR, True)

        self.menu_ag.add_action(spaction)
        self.menu_ag.add_action(upaction)
        self.menu_ag.add_action(dnaction)

        self._recent.append((port, rtype))

    def do_clonein(self, port=None, rtype=None):
        dlg = clone.CloneSettingsDialog(rtype=rtype, port=port)
        res = dlg.run()
        port, rtype, fn = dlg.get_values()
        dlg.destroy()

        if res != gtk.RESPONSE_OK:
            return

        if rtype == clone.AUTO_DETECT_STRING:
            rtype = detect.detect_radio(port)

        try:
            rc = directory.get_radio(rtype)
            ser = serial.Serial(port=port, baudrate=rc.BAUD_RATE, timeout=0.25)
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio = rc(ser)

        self.record_recent_radio(port, rtype)

        ct = clone.CloneThread(radio, fn, cb=self.cb_clonein, parent=self)
        ct.start()

    def do_cloneout(self, port=None, rtype=None):
        eset = self.get_current_editorset()
        radio = eset.radio

        if rtype and rtype != directory.get_driver(radio.__class__):
            common.show_error("Unable to upload to %s from current %s image" % (
                    rtype, directory.get_driver(radio.__class__)))
            return

        dlg = clone.CloneSettingsDialog(False,
                                        eset.filename,
                                        directory.get_driver(radio.__class__),
                                        port=port)
        res = dlg.run()
        port, rtype, _ = dlg.get_values()
        dlg.destroy()

        if res != gtk.RESPONSE_OK:
            return

        try:
            rc = directory.get_radio(rtype)
            ser = serial.Serial(port=port, baudrate=rc.BAUD_RATE, timeout=0.25)
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio.set_pipe(ser)

        self.record_recent_radio(port, rtype)

        ct = clone.CloneThread(radio, cb=self.cb_cloneout, parent=self)
        ct.start()

    def do_close(self, tab_child=None):
        if tab_child:
            eset = tab_child
        else:
            eset = self.get_current_editorset()

        if not eset:
            return False

        if eset.is_modified():
            dlg = miscwidgets.YesNoDialog(title="Discard Changes?",
                                          parent=self,
                                          buttons=(gtk.STOCK_YES, gtk.RESPONSE_YES,
                                                   gtk.STOCK_NO, gtk.RESPONSE_NO,
                                                   gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
            dlg.set_text("File is modified, save changes before closing?")
            res = dlg.run()
            dlg.destroy()
            if res == gtk.RESPONSE_YES:
                self.do_save(eset)
            elif res == gtk.RESPONSE_CANCEL:
                raise ModifiedError()

        eset.rthread.stop()
        eset.rthread.join()
    
        if eset.radio.pipe:
            eset.radio.pipe.close()

        if isinstance(eset.radio, ic9x.IC9xRadio):
            action = self.menu_ag.get_action("openlive")
            if action:
                action.set_sensitive(True)

        page = self.tabs.page_num(eset)
        if page is not None:
            self.tabs.remove_page(page)

        return True

    def do_import(self):
        types = [("CHIRP Files (*.chirp)", "*.chirp"),
                 ("CHIRP Radio Images (*.img)", "*.img"),
                 ("CSV Files (*.csv)", "*.csv")]
        filen = platform.get_platform().gui_open_file(types=types)
        if not filen:
            return

        eset = self.get_current_editorset()
        eset.do_import(filen)

    def do_export(self, type="chirp"):
        
        types = { "chirp": ("CHIRP Files (*.chirp)", "*.chirp"),
                  "csv" : ("CSV Files (*.csv)", "*.csv"),
                  }

        defname = "radio.%s" % type
        filen = platform.get_platform().gui_save_file(default_name=defname,
                                                      types=[types[type]])
        if not filen:
            return

        eset = self.get_current_editorset()
        eset.do_export(filen)

    def do_about(self):
        d = gtk.AboutDialog()
        d.set_transient_for(self)
        verinfo = "GTK %s\nPyGTK %s\n" % ( \
            ".".join([str(x) for x in gtk.gtk_version]),
            ".".join([str(x) for x in gtk.pygtk_version]))

        d.set_name("CHIRP")
        d.set_version(CHIRP_VERSION)
        d.set_copyright("Copyright 2010 Dan Smith (KK7DS)")
        d.set_website("http://chirp.danplanet.com")
        d.set_authors(("Dan Smith <dsmith@danplanet.com>",))
        d.set_comments(verinfo)
        
        d.run()
        d.destroy()

    def do_converticf(self):
        icftypes = [("ICF Files (*.icf)", "*.icf")]
        icffile = platform.get_platform().gui_open_file(types=icftypes)
        if not icffile:
            return

        imgtypes = [("CHIRP Radio Images (*.img)", "*.img")]
        imgfile = platform.get_platform().gui_save_file(types=imgtypes)
        if not imgfile:
            return

        try:
            convert_icf.icf_to_image(icffile, imgfile)
        except Exception, e:
            common.log_exception()
            common.show_error("Unable to convert ICF file: %s" % e)

        self.do_open(imgfile)

    def do_columns(self):
        eset = self.get_current_editorset()
        d = gtk.Dialog(title="Select Columns",
                       parent=self,
                       buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK,
                                gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))

        vbox = gtk.VBox()
        vbox.show()
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(vbox)
        sw.show()
        d.vbox.pack_start(sw, 1, 1, 1)
        d.set_size_request(-1, 300)
        d.set_resizable(False)

        fields = []
        for colspec in eset.memedit.cols:
            label = colspec[0]
            visible = eset.memedit.get_column_visible(eset.memedit.col(label))
            widget = gtk.CheckButton(label)
            widget.set_active(visible)
            fields.append(widget)
            vbox.pack_start(widget, 1, 1, 1)
            widget.show()

        res = d.run()
        if res == gtk.RESPONSE_OK:
            for widget in fields:
                colnum = eset.memedit.col(widget.get_label())
                eset.memedit.set_column_visible(colnum, widget.get_active())
                                                
        d.destroy()

    def do_clearq(self):
        eset = self.get_current_editorset()
        eset.rthread.flush()

    def mh(self, _action, *args):
        action = _action.get_name()

        if action == "quit":
            gtk.main_quit()
        elif action == "new":
            self.do_new()
        elif action == "open":
            self.do_open()
        elif action == "save":
            self.do_save()
        elif action == "saveas":
            self.do_saveas()
        elif action.startswith("clonein"):
            self.do_clonein(*args)
        elif action.startswith("cloneout"):
            self.do_cloneout(*args)
        elif action == "close":
            self.do_close()
        elif action == "converticf":
            self.do_converticf()
        elif action == "open9xA":
            self.do_open_live(ic9x.IC9xRadioA, "ic9x")
        elif action == "open9xB":
            self.do_open_live(ic9x.IC9xRadioB, "ic9x")
        elif action == "openTHD7x":
            self.do_open_live(thd7.THD7Radio, "thd7")
        elif action == "openrpxkv":
            self.do_open_live(idrp.IDRPx000V, "idrpx000v")
        elif action == "import":
            self.do_import()
        elif action == "export_csv":
            self.do_export("csv")
        elif action == "export_chirp":
            self.do_export("chirp")
        elif action == "about":
            self.do_about()
        elif action == "columns":
            self.do_columns()
        elif action == "cancelq":
            self.do_clearq()
        else:
            return

        self.ev_tab_switched()

    def make_menubar(self):
        menu_xml = """
<ui>
  <menubar name="MenuBar">
    <menu action="file">
      <menuitem action="new"/>
      <menuitem action="open"/>
      <menuitem action="save"/>
      <menuitem action="saveas"/>
      <menuitem action="close"/>
      <menuitem action="converticf"/>
      <menuitem action="quit"/>
    </menu>
    <menu action="view">
      <menuitem action="columns"/>
    </menu>
    <menu action="radio" name="radio">
      <menuitem action="clonein"/>
      <menuitem action="cloneout"/>
      <menu action="openlive">
        <menuitem action="open9xA"/>
        <menuitem action="open9xB"/>
        <menuitem action="openrpxkv"/>
        <menuitem action="openTHD7x"/>
      </menu>
      <menu action="recent" name="recent"/>
      <separator/>
      <menuitem action="import"/>
      <menu action="export">
        <menuitem action="export_chirp"/>
        <menuitem action="export_csv"/>
      </menu>
      <separator/>
      <menuitem action="cancelq"/>
    </menu>
    <menu action="help">
      <menuitem action="about"/>
    </menu>
  </menubar>
</ui>
"""
        actions = [\
            ('file', None, "_File", None, None, self.mh),
            ('new', gtk.STOCK_NEW, None, None, None, self.mh),
            ('open', gtk.STOCK_OPEN, None, None, None, self.mh),
            ('openlive', gtk.STOCK_CONNECT, "_Connect to a radio", None, None, self.mh),
            ('open9xA', None, "Icom IC9x Band A", None, None, self.mh),
            ('open9xB', None, "Icom IC9x Band B", None, None, self.mh),
            ('openTHD7x', None, "Kenwood TH-D7/TM-D700", None, None, self.mh),
            ('openrpxkv', gtk.STOCK_CONNECT, "Icom ID-RP*", None, None, self.mh),
            ('save', gtk.STOCK_SAVE, None, None, None, self.mh),
            ('saveas', gtk.STOCK_SAVE_AS, None, None, None, self.mh),
            ('converticf', gtk.STOCK_CONVERT, "Convert .icf file", None, None, self.mh),
            ('close', gtk.STOCK_CLOSE, None, None, None, self.mh),
            ('quit', gtk.STOCK_QUIT, None, None, None, self.mh),
            ('view', None, "_View", None, None, self.mh),
            ('columns', None, 'Columns', None, None, self.mh),
            ('radio', None, "_Radio", None, None, self.mh),
            ('clonein', None, "Download From Radio", "<Alt>d", None, self.mh),
            ('cloneout', None, "Upload To Radio", "<Alt>u", None, self.mh),
            ('import', None, 'Import from file', "<Alt>i", None, self.mh),
            ('export', None, 'Export to...', None, None, self.mh),
            ('export_chirp', None, 'CHIRP Native File', None, None, self.mh),
            ('export_csv', None, 'CSV File', None, None, self.mh),
            ('cancelq', gtk.STOCK_STOP, None, "Escape", None, self.mh),
            ('help', None, 'Help', None, None, self.mh),
            ('about', gtk.STOCK_ABOUT, None, None, None, self.mh),
            ('recent', None, "Recent", None, None, self.mh),
            ]

        self.menu_uim = gtk.UIManager()
        self.menu_ag = gtk.ActionGroup("MenuBar")
        self.menu_ag.add_actions(actions)

        self.menu_uim.insert_action_group(self.menu_ag, 0)
        self.menu_uim.add_ui_from_string(menu_xml)

        self.add_accel_group(self.menu_uim.get_accel_group())

        self.recentmenu = self.menu_uim.get_widget("/MenuBar/radio/recent")

        return self.menu_uim.get_widget("/MenuBar")

    def make_tabs(self):
        self.tabs = gtk.Notebook()

        return self.tabs        

    def close_out(self):
        num = self.tabs.get_n_pages()
        while num > 0:
            num -= 1
            print "Closing %i" % num
            try:
                self.do_close(self.tabs.get_nth_page(num))
            except ModifiedError:
                return False

        gtk.main_quit()

        return True

    def make_status_bar(self):
        box = gtk.HBox(False, 2)

        self.sb_general = gtk.Statusbar()
        self.sb_general.set_has_resize_grip(False)
        self.sb_general.show()
        box.pack_start(self.sb_general, 1,1,1)
        
        self.sb_radio = gtk.Statusbar()
        self.sb_radio.set_has_resize_grip(True)
        self.sb_radio.show()
        box.pack_start(self.sb_radio, 1,1,1)

        box.show()
        return box

    def ev_delete(self, window, event):
        if not self.close_out():
            return True # Don't exit

    def ev_destroy(self, window):
        if not self.close_out():
            return True # Don't exit

    def __init__(self, *args, **kwargs):
        gtk.Window.__init__(self, *args, **kwargs)

        vbox = gtk.VBox(False, 2)

        self._recent = []

        self.menu_ag = None
        mbar = self.make_menubar()
        mbar.show()
        vbox.pack_start(mbar, 0, 0, 0)

        self.tabs = None
        tabs = self.make_tabs()
        tabs.connect("switch-page", lambda n, _, p: self.ev_tab_switched(p))
        tabs.show()
        self.ev_tab_switched()
        vbox.pack_start(tabs, 1, 1, 1)

        vbox.pack_start(self.make_status_bar(), 0, 0, 0)

        vbox.show()


        self.add(vbox)

        self.set_default_size(640, 480)
        self.set_title("CHIRP")

        self.connect("delete_event", self.ev_delete)
        self.connect("destroy", self.ev_destroy)
