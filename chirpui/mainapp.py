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
import tempfile

import gtk
import gobject
gobject.threads_init()

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

from chirpui import inputdialog, common
try:
    import serial
except ImportError,e:
    common.log_exception()
    common.show_error("\nThe Pyserial module is not installed!")
from chirp import platform, xml, csv, directory, ic9x, kenwood_live, idrp, vx7
from chirp import CHIRP_VERSION, chirp_common, detect
from chirp import icf, ic9x_icf
from chirpui import editorset, clone, miscwidgets, config, reporting

CONF = config.get()

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

        if not eset or isinstance(eset.radio, chirp_common.LiveRadio):
            mmap_sens = False
        else:
            mmap_sens = True

        # If it's a MMAP radio and the file exists, then we can save
        cansave = bool(eset and os.path.exists(eset.filename) and mmap_sens)

        for i in ["saveas", "upload"]:
            set_action_sensitive(i, mmap_sens)

        set_action_sensitive("save", cansave)

        for i in ["cancelq"]:
            set_action_sensitive(i, eset is not None and not mmap_sens)
        
        for i in ["export", "import", "close", "columns"]:
            set_action_sensitive(i, eset is not None)

    def ev_status(self, editorset, msg):
        self.sb_radio.pop(0)
        self.sb_radio.push(0, msg)

    def do_new(self):
        eset = editorset.EditorSet("Untitled.csv", self)
        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.prime()
        eset.show()

        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def do_open(self, fname=None, tempname=None):
        if not fname:
            types = [("CHIRP Radio Images (*.img)", "*.img"),
                     ("CHIRP Files (*.chirp)", "*.chirp"),
                     ("CSV Files (*.csv)", "*.csv"),
                     ("ICF Files (*.icf)", "*.icf"),
                     ("VX7 Commander Files (*.vx7)", "*.vx7"),
                     ]
            fname = platform.get_platform().gui_open_file(types=types)
            if not fname:
                return

        if icf.is_icf_file(fname):
            a = common.ask_yesno_question("ICF files cannot be edited, only " +
                                          "displayed or imported into " +
                                          "another file.  " +
                                          "Open in read-only mode?",
                                          self)
            if not a:
                return
            read_only = True
        else:
            read_only = False

        if icf.is_9x_icf(fname):
            # We have to actually instantiate the IC9xICFRadio to get its
            # sub-devices
            radio = ic9x_icf.IC9xICFRadio(fname)
            devices = radio.get_sub_devices()
            del radio
        else:
            try:
                radio = directory.get_radio_by_image(fname)
            except Exception, e:
                common.show_error(os.path.basename(fname) + ": " + str(e))
                return

            if radio.get_features().has_sub_devices:
                devices = radio.get_sub_devices()
                tempname = fname
            else:
                del radio
                devices = [fname]

        for device in devices:
            try:
                eset = editorset.EditorSet(device, self, tempname=tempname)
            except Exception, e:
                common.log_exception()
                common.show_error("There was an error opening %s: %s" % (fname,
                                                                         e))
                return
    
            eset.set_read_only(read_only)
            eset.connect("want-close", self.do_close)
            eset.connect("status", self.ev_status)
            eset.show()
            tab = self.tabs.append_page(eset, eset.get_tab_label())
            self.tabs.set_current_page(tab)

    def do_live_warning(self, radio):
        d = gtk.MessageDialog(parent=self, buttons=gtk.BUTTONS_OK)
        d.set_markup("<big><b>Note:</b></big>")
        d.format_secondary_markup("The %s %s " % (radio.VENDOR, radio.MODEL)  +
                                  "operates in <b>live mode</b>.  "           +
                                  "This means that any changes you make "     +
                                  "are immediately sent to the radio.  "      +
                                  "Because of this, you cannot perform the "  +
                                  "<u>Save</u> or <u>Upload</u> operations."  +
                                  "If you wish to edit the contents offline, "+
                                  "please <u>Export</u> to a CSV file, using "+
                                  "the <b>Radio menu</b>.")
        again = gtk.CheckButton("Don't show this again")
        again.show()
        d.vbox.pack_start(again, 0, 0, 0)
        d.run()
        CONF.set_bool("live_mode", again.get_active(), "noconfirm")
        d.destroy()

    def do_open_live(self, radio, tempname=None):
        if radio.get_features().has_sub_devices:
            devices = radio.get_sub_devices()
        else:
            devices = [radio]
        
        for device in devices:
            eset = editorset.EditorSet(device, self, tempname)
            eset.connect("want-close", self.do_close)
            eset.connect("status", self.ev_status)
            eset.show()

            tab = self.tabs.append_page(eset, eset.get_tab_label())
            self.tabs.set_current_page(tab)

        if isinstance(radio, chirp_common.LiveRadio):
            reporting.report_model_usage(radio, "live", True)
            if not CONF.get_bool("live_mode", "noconfirm"):
                self.do_live_warning(radio)

    def do_save(self, eset=None):
        if not eset:
            eset = self.get_current_editorset()
        eset.save()

    def do_saveas(self):
        eset = self.get_current_editorset()

        if isinstance(eset.radio, chirp_common.CloneModeRadio):
            types = [("Radio-specific Image (*.img)", "*.img")]
        elif isinstance(eset.radio, csv.CSVRadio):
            types = [("CSV File (*.csv)", "*.csv")]
        elif isinstance(eset.radio, xml.XMLRadio):
            types = [("CHIRP File (*.chirp)", "*.chirp")]
        else:
            types = [("ERROR", "*.*")]

        if isinstance(eset.radio, vx7.VX7Radio):
            types += [("VX7 Commander (*.vx7)", "*.vx7")]

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

        try:
            eset.save(fname)
        except Exception,e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()

    def cb_clonein(self, radio, emsg=None):
        radio.pipe.close()
        reporting.report_model_usage(radio, "download", bool(emsg))
        if not emsg:
            self.do_open_live(radio, tempname="(Untitled)")
        else:
            d = inputdialog.ExceptionDialog(emsg)
            d.run()
            d.destroy()

    def cb_cloneout(self, radio, fn, emsg= None):
        radio.pipe.close()
        reporting.report_model_usage(radio, "upload", True)

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

    def do_download(self, port=None, rtype=None):
        d = clone.CloneSettingsDialog(parent=self)
        settings = d.run()
        d.destroy()
        if not settings:
            return

        try:
            ser = serial.Serial(port=settings.port,
                                baudrate=settings.radio_class.BAUD_RATE,
                                timeout=0.25)
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio = settings.radio_class(ser)

        #FIXME: Fix or remove
        #self.record_recent_radio(port, rtype)

        fn = tempfile.mktemp()
        if isinstance(radio, chirp_common.CloneModeRadio):
            ct = clone.CloneThread(radio, "in", cb=self.cb_clonein, parent=self)
            ct.start()
        else:
            self.do_open_live(radio)

    def do_upload(self, port=None, rtype=None):
        eset = self.get_current_editorset()
        radio = eset.radio

        settings = clone.CloneSettings()
        settings.radio_class = radio.__class__

        d = clone.CloneSettingsDialog(settings, parent=self)
        settings = d.run()
        d.destroy()
        if not settings:
            return

        try:
            ser = serial.Serial(port=settings.port,
                                baudrate=radio.BAUD_RATE,
                                timeout=0.25)
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio.set_pipe(ser)

        #FIXME: Fix or remove
        #self.record_recent_radio(port, rtype)

        ct = clone.CloneThread(radio, "out", cb=self.cb_cloneout, parent=self)
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

        if isinstance(eset.radio, chirp_common.LiveRadio):
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
                 ("CSV Files (*.csv)", "*.csv"),
                 ("ICF Files (*.icf)", "*.icf"),
                 ("VX7 Commander Files (*.vx7)", "*.vx7")]
        filen = platform.get_platform().gui_open_file(types=types)
        if not filen:
            return

        eset = self.get_current_editorset()
        count = eset.do_import(filen)
        reporting.report_model_usage(eset.rthread.radio, "import", count > 0)

    def do_export(self, type="chirp"):
        
        types = { "chirp": ("CHIRP Files (*.chirp)", "*.chirp"),
                  "csv" : ("CSV Files (*.csv)", "*.csv"),
                  }

        eset = self.get_current_editorset()

        if os.path.exists(eset.filename):
            base = os.path.basename(eset.filename)
            if "." in base:
                base = base[:base.rindex(".")]
            defname = "%s.%s" % (base, type)
        else:
            defname = "radio.%s" % type

        filen = platform.get_platform().gui_save_file(default_name=defname,
                                                      types=[types[type]])
        if not filen:
            return

        count = eset.do_export(filen)
        reporting.report_model_usage(eset.rthread.radio, "export", count > 0)

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
            if colspec[0].startswith("_"):
                continue
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

    def do_copy(self, cut):
        eset = self.get_current_editorset()
        eset.memedit.copy_selection(cut)

    def do_paste(self):
        eset = self.get_current_editorset()
        eset.memedit.paste_selection()

    def do_delete(self):
        eset = self.get_current_editorset()
        eset.memedit.copy_selection(True)

    def do_toggle_report(self, action):
        if not action.get_active():
            d = gtk.MessageDialog(buttons=gtk.BUTTONS_YES_NO,
                                  parent=self)
            d.set_markup("<b><big>Reporting is disabled</big></b>")
            msg = "The reporting feature of CHIRP is designed to help "       +\
                "<u>improve quality</u> by allowing the authors to focus on " +\
                "the radio drivers used most often and errors experienced by "+\
                "the users.  The reports contain no identifying information " +\
                "and are used only for statistical purposes by the authors.  "+\
                "Your privacy is extremely important, but <u>please consider "+\
                "leaving this feature enabled to help make CHIRP better!</u>" +\
                "\r\n\r\n"                                                    +\
                "<b>Are you sure you want to disable this feature?</b>"
            d.format_secondary_markup(msg)
            r = d.run()
            d.destroy()
            if r == gtk.RESPONSE_NO:
                action.set_active(not action.get_active())

        conf = config.get()
        conf.set_bool("no_report", not action.get_active())

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
        elif action.startswith("download"):
            self.do_download(*args)
        elif action.startswith("upload"):
            self.do_upload(*args)
        elif action == "close":
            self.do_close()
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
        elif action == "cut":
            self.do_copy(cut=True)
        elif action == "copy":
            self.do_copy(cut=False)
        elif action == "paste":
            self.do_paste()
        elif action == "delete":
            self.do_delete()
        elif action == "report":
            self.do_toggle_report(_action)
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
    <menu action="edit">
      <menuitem action="cut"/>
      <menuitem action="copy"/>
      <menuitem action="paste"/>
      <menuitem action="delete"/>
    </menu>
    <menu action="view">
      <menuitem action="columns"/>
    </menu>
    <menu action="radio" name="radio">
      <menuitem action="download"/>
      <menuitem action="upload"/>
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
      <menuitem action="report"/>
    </menu>
  </menubar>
</ui>
"""
        actions = [\
            ('file', None, "_File", None, None, self.mh),
            ('new', gtk.STOCK_NEW, None, None, None, self.mh),
            ('open', gtk.STOCK_OPEN, None, None, None, self.mh),
            ('save', gtk.STOCK_SAVE, None, None, None, self.mh),
            ('saveas', gtk.STOCK_SAVE_AS, None, None, None, self.mh),
            ('close', gtk.STOCK_CLOSE, None, None, None, self.mh),
            ('quit', gtk.STOCK_QUIT, None, None, None, self.mh),
            ('edit', None, "_Edit", None, None, self.mh),
            ('cut', None, "_Cut", "<Ctrl>x", None, self.mh),
            ('copy', None, "_Copy", "<Ctrl>c", None, self.mh),
            ('paste', None, "_Paste", "<Ctrl>v", None, self.mh),
            ('delete', None, "_Delete", "Delete", None, self.mh),
            ('view', None, "_View", None, None, self.mh),
            ('columns', None, 'Columns', None, None, self.mh),
            ('radio', None, "_Radio", None, None, self.mh),
            ('download', None, "Download From Radio", "<Alt>d", None, self.mh),
            ('upload', None, "Upload To Radio", "<Alt>u", None, self.mh),
            ('import', None, 'Import from file', "<Alt>i", None, self.mh),
            ('export', None, 'Export to...', None, None, self.mh),
            ('export_chirp', None, 'CHIRP Native File', None, None, self.mh),
            ('export_csv', None, 'CSV File', None, None, self.mh),
            ('cancelq', gtk.STOCK_STOP, None, "Escape", None, self.mh),
            ('help', None, 'Help', None, None, self.mh),
            ('about', gtk.STOCK_ABOUT, None, None, None, self.mh),
            ('recent', None, "Recent", None, None, self.mh),
            ]

        conf = config.get()
        re = not conf.get_bool("no_report");

        toggles = [\
            ('report', None, "Report statistics", None, None, self.mh, re),
            ]

        self.menu_uim = gtk.UIManager()
        self.menu_ag = gtk.ActionGroup("MenuBar")
        self.menu_ag.add_actions(actions)
        self.menu_ag.add_toggle_actions(toggles)

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

        self.set_default_size(800, 600)
        self.set_title("CHIRP")

        self.connect("delete_event", self.ev_delete)
        self.connect("destroy", self.ev_destroy)

        if not CONF.get_bool("warned_about_reporting") and \
                not CONF.get_bool("no_report"):
            d = gtk.MessageDialog(buttons=gtk.BUTTONS_OK, parent=self)
            d.set_markup("<b><big>Error reporting is enabled</big></b>")
            d.format_secondary_markup("If you wish to disable this feature " +
                                      "you may do so in the <u>Help</u> menu")
            d.run()
            d.destroy()
        CONF.set_bool("warned_about_reporting", True)
