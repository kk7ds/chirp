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

from chirp import platform, id800, ic2820, ic2200, ic9x, xml, CHIRP_VERSION
from chirpui import editorset, clone, inputdialog, miscwidgets, common

RADIOS = {
    "ic2820" : ic2820.IC2820Radio,
    "ic2200" : ic2200.IC2200Radio,
    "ic9x:A" : ic9x.IC9xRadioA,
    "ic9x:B" : ic9x.IC9xRadioB,
    "id800"  : id800.ID800v2Radio,
    "Virtual": xml.XMLRadio,
}

RTYPES = {}
for __key, __val in RADIOS.items():
    RTYPES[__val] = __key

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

        if not eset or isinstance(eset.radio, ic9x.IC9xRadio):
            sensitive = False
        else:
            sensitive = True

        for i in ["save", "saveas", "cloneout"]:
            set_action_sensitive(i, sensitive)
        
        set_action_sensitive("close", bool(eset))

    def ev_status(self, editorset, msg):
        self.sb_radio.pop(0)
        self.sb_radio.push(0, msg)

    def do_new(self):
        eset = editorset.EditorSet("Untitled.chirp")
        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.prime()
        eset.show()

        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def do_open(self, fname=None):
        if not fname:
            fname = platform.get_platform().gui_open_file()
            if not fname:
                return

        try:
            eset = editorset.EditorSet(fname)
        except Exception, e:
            print e
            return # FIXME

        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.show()
        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def do_open9x(self, rclass):
        dlg = clone.CloneSettingsDialog(clone_in=False,
                                        filename="(live)",
                                        rtype="ic9x")
        res = dlg.run()
        port, _, _ = dlg.get_values()
        dlg.destroy()

        if res != gtk.RESPONSE_OK:
            return
        
        ser = serial.Serial(port=port,
                            baudrate=38400,
                            timeout=0.1)
        radio = rclass(ser)
        
        eset = editorset.EditorSet(radio)
        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.show()

        action = self.menu_ag.get_action("open9x")
        action.set_sensitive(False)

        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def do_save(self, eset=None):
        if not eset:
            eset = self.get_current_editorset()
        eset.save()

    def do_saveas(self):

        while True:
            fname = platform.get_platform().gui_save_file()
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

        eset = self.get_current_editorset()
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

    def do_clonein(self):
        dlg = clone.CloneSettingsDialog()
        res = dlg.run()
        port, rtype, fn = dlg.get_values()
        dlg.destroy()

        if res != gtk.RESPONSE_OK:
            return

        rc = RADIOS[rtype]
        try:
            ser = serial.Serial(port=port, baudrate=rc.BAUD_RATE, timeout=0.25)
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio = rc(ser)

        ct = clone.CloneThread(radio, fn, cb=self.cb_clonein, parent=self)
        ct.start()

    def do_cloneout(self):
        eset = self.get_current_editorset()
        radio = eset.radio

        dlg = clone.CloneSettingsDialog(False,
                                        eset.filename,
                                        RTYPES[radio.__class__])
        res = dlg.run()
        port, rtype, _ = dlg.get_values()
        dlg.destroy()

        if res != gtk.RESPONSE_OK:
            return

        rc = RADIOS[rtype]
        try:
            ser = serial.Serial(port=port, baudrate=rc.BAUD_RATE, timeout=0.25)
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio.set_pipe(ser)

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
            action = self.menu_ag.get_action("open9x")
            if action:
                action.set_sensitive(True)

        page = self.tabs.page_num(eset)
        if page is not None:
            self.tabs.remove_page(page)

        return True

    def do_import(self):
        filen = platform.get_platform().gui_open_file()
        if not filen:
            return

        eset = self.get_current_editorset()
        eset.do_import(filen)

    def do_export(self):
        filen = platform.get_platform().gui_save_file(default_name="radio.chirp")
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
        d.set_copyright("Copyright 2008 Dan Smith (KK7DS)")
        d.set_website("http://chirp.danplanet.com")
        d.set_authors(("Dan Smith <dsmith@danplanet.com>",))
        d.set_comments(verinfo)
        
        d.run()
        d.destroy()

    def mh(self, _action):
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
        elif action == "clonein":
            self.do_clonein()
        elif action == "cloneout":
            self.do_cloneout()
        elif action == "close":
            self.do_close()
        elif action == "open9xA":
            self.do_open9x(ic9x.IC9xRadioA)
        elif action == "open9xB":
            self.do_open9x(ic9x.IC9xRadioB)
        elif action == "import":
            self.do_import()
        elif action == "export":
            self.do_export()
        elif action == "about":
            self.do_about()
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
      <menuitem action="quit"/>
    </menu>
    <menu action="radio">
      <menuitem action="clonein"/>
      <menuitem action="cloneout"/>
      <menu action="open9x">
        <menuitem action="open9xA"/>
        <menuitem action="open9xB"/>
      </menu>
    <separator/>
    <menuitem action="import"/>
    <menuitem action="export"/>
    </menu>
    <menu action="help">
      <menuitem action="about"/>
    </menu>
  </menubar>
</ui>
"""
        actions = [\
            ('file', None, "_File", None, None, self.mh),
            ('new', None, "_New", None, None, self.mh),
            ('open', None, "_Open", None, None, self.mh),
            ('open9x', None, "_Connect to an IC9x", None, None, self.mh),
            ('open9xA', None, "Band A", None, None, self.mh),
            ('open9xB', None, "Band B", None, None, self.mh),
            ('save', None, "_Save", None, None, self.mh),
            ('saveas', None, "Save _As", None, None, self.mh),
            ('close', None, "_Close", None, None, self.mh),
            ('quit', None, "_Quit", None, None, self.mh),
            ('radio', None, "_Radio", None, None, self.mh),
            ('clonein', None, "Download From Radio", None, None, self.mh),
            ('cloneout', None, "Upload To Radio", None, None, self.mh),
            ('import', None, 'Import from file', None, None, self.mh),
            ('export', None, 'Export to file', None, None, self.mh),
            ('help', None, 'Help', None, None, self.mh),
            ('about', None, 'About', None, None, self.mh),
            ]

        uim = gtk.UIManager()
        self.menu_ag = gtk.ActionGroup("MenuBar")
        self.menu_ag.add_actions(actions)

        uim.insert_action_group(self.menu_ag, 0)
        uim.add_ui_from_string(menu_xml)

        return uim.get_widget("/MenuBar")

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
