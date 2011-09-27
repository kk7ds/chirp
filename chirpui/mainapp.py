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
import urllib

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
from chirp import platform, xml, generic_csv, directory
from chirp import ic9x, kenwood_live, idrp, vx7
from chirp import CHIRP_VERSION, chirp_common, detect, errors
from chirp import icf, ic9x_icf
from chirpui import editorset, clone, miscwidgets, config, reporting

CONF = config.get()

KEEP_RECENT = 8

FIPS_CODES = {
    "Alaska"               : 2,
    "Alabama"              : 1,
    "Arkansas"             : 5,
    "Arizona"              : 4,
    "California"           : 6,
    "Colorado"             : 8,
    "Connecticut"          : 9,
    "District of Columbia" : 11,
    "Delaware"             : 10,
    "Florida"              : 12,
    "Georgia"              : 13,
    "Guam"                 : 66,
    "Hawaii"               : 15,
    "Iowa"                 : 19,
    "Idaho"                : 16,
    "Illinois"             : 17,
    "Indiana"              : 18,
    "Kansas"               : 20,
    "Kentucky"             : 21,
    "Louisiana"            : 22,
    "Massachusetts"        : 25,
    "Maryland"             : 24,
    "Maine"                : 23,
    "Michigan"             : 26,
    "Minnesota"            : 27,
    "Missouri"             : 29,
    "Mississippi"          : 28,
    "Montana"              : 30,
    "North Carolina"       : 37,
    "North Dakota"         : 38,
    "Nebraska"             : 31,
    "New Hampshire"        : 33,
    "New Jersey"           : 34,
    "New Mexico"           : 35,
    "Nevada"               : 32,
    "New York"             : 36,
    "Ohio"                 : 39,
    "Oklahoma"             : 40,
    "Oregon"               : 41,
    "Pennsylvania"         : 32,
    "Puerto Rico"          : 72,
    "Rhode Island"         : 44,
    "South Carolina"       : 45,
    "South Dakota"         : 46,
    "Tennessee"            : 47,
    "Texas"                : 48,
    "Utah"                 : 49,
    "Virginia"             : 51,
    "Virgin Islands"       : 78,
    "Vermont"              : 50,
    "Washington"           : 53,
    "Wisconsin"            : 55,
    "West Virginia"        : 54,
    "Wyoming"              : 56,
}

RB_BANDS = {
    "--All--"                 : 0,
    "10 meters (29MHz)"       : 29,
    "6 meters (54MHz)"        : 5,
    "2 meters (144MHz)"       : 14,
    "1.25 meters (220MHz)"    : 22,
    "70 centimeters (440MHz)" : 4,
    "33 centimeters (900MHz)" : 9,
    "23 centimeters (1.2GHz)" : 12,
}

def key_bands(band):
    if band.startswith("-"):
        return -1

    amount, units, mhz = band.split(" ")
    scale = units == "meters" and 100 or 1

    return 100000 - (float(amount) * scale)

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

        for i in ["save", "saveas", "upload"]:
            set_action_sensitive(i, mmap_sens)

        for i in ["cancelq"]:
            set_action_sensitive(i, eset is not None and not mmap_sens)
        
        for i in ["export", "import", "close", "columns", "rbook", "rfinder"]:
            set_action_sensitive(i, eset is not None)

    def ev_status(self, editorset, msg):
        self.sb_radio.pop(0)
        self.sb_radio.push(0, msg)

    def ev_usermsg(self, editorset, msg):
        self.sb_general.pop(0)
        self.sb_general.push(0, msg)

    def ev_editor_selected(self, editorset, editortype):
        mappings = {
            "memory" : ["view", "edit"],
            }

        for _editortype, actions in mappings.items():
            for _action in actions:
                action = self.menu_ag.get_action(_action)
                action.set_sensitive(_editortype == editortype)

    def _connect_editorset(self, eset):
        eset.connect("want-close", self.do_close)
        eset.connect("status", self.ev_status)
        eset.connect("usermsg", self.ev_usermsg)
        eset.connect("editor-selected", self.ev_editor_selected)

    def do_new(self):
        eset = editorset.EditorSet("Untitled.csv", self)
        self._connect_editorset(eset)
        eset.prime()
        eset.show()

        tab = self.tabs.append_page(eset, eset.get_tab_label())
        self.tabs.set_current_page(tab)

    def _do_manual_select(self, filename):
        radiolist = {}
        for drv, radio in directory.DRV_TO_RADIO.items():
            if not issubclass(radio, chirp_common.CloneModeRadio):
                continue
            radiolist["%s %s" % (radio.VENDOR, radio.MODEL)] = drv

        lab = gtk.Label("""<b><big>Unable to detect model!</big></b>

If you think that it is valid, you can select a radio model below to force an open attempt. If selecting the model manually works, please file a bug on the website and attach your image. If selecting the model does not work, it is likely that you are trying to open some other type of file.
""")

        lab.set_justify(gtk.JUSTIFY_FILL)
        lab.set_line_wrap(True)
        lab.set_use_markup(True)
        lab.show()
        choice = miscwidgets.make_choice(sorted(radiolist.keys()), False,
                                         sorted(radiolist.keys())[0])
        d = gtk.Dialog(title="Detection Failed",
                       buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK,
                                gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
        d.vbox.pack_start(lab, 0, 0, 0)
        d.vbox.pack_start(choice, 0, 0, 0)
        d.vbox.set_spacing(5)
        choice.show()
        d.set_default_size(400, 200)
        #d.set_resizable(False)
        r = d.run()
        d.destroy()
        if r != gtk.RESPONSE_OK:
            return
        try:
            rc = directory.DRV_TO_RADIO[radiolist[choice.get_active_text()]]
            return rc(filename)
        except:
            return

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

        self.record_recent_file(fname)

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
            except errors.ImageDetectFailed:
                radio = self._do_manual_select(fname)
                if not radio:
                    return
                print "Manually selected %s" % radio
            except Exception, e:
                common.log_exception()
                common.show_error(os.path.basename(fname) + ": " + str(e))
                return

            tempname = fname
            if radio.get_features().has_sub_devices:
                devices = radio.get_sub_devices()
            else:
                devices = [radio]

        prio = len(devices)
        first_tab = False
        for device in devices:
            try:
                eset = editorset.EditorSet(device, self, tempname=tempname)
            except Exception, e:
                common.log_exception()
                common.show_error("There was an error opening %s: %s" % (fname,
                                                                         e))
                return
    
            eset.set_read_only(read_only)
            self._connect_editorset(eset)
            eset.show()
            tab = self.tabs.append_page(eset, eset.get_tab_label())
            if first_tab:
                self.tabs.set_current_page(tab)
                first_tab = False

            if hasattr(eset.rthread.radio, "errors") and \
                    eset.rthread.radio.errors:
                msg = "%i errors during open, check the " + \
                                      "debug log for details"
                msg = msg % len(eset.rthread.radio.errors)
                common.show_error(msg)

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
                                  "the <b>File menu</b>.")
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
        
        first_tab = True
        for device in devices:
            eset = editorset.EditorSet(device, self, tempname)
            eset.connect("want-close", self.do_close)
            eset.connect("status", self.ev_status)
            eset.show()

            tab = self.tabs.append_page(eset, eset.get_tab_label())
            if first_tab:
                self.tabs.set_current_page(tab)
                first_tab = False

        if isinstance(radio, chirp_common.LiveRadio):
            reporting.report_model_usage(radio, "live", True)
            if not CONF.get_bool("live_mode", "noconfirm"):
                self.do_live_warning(radio)

    def do_save(self, eset=None):
        if not eset:
            eset = self.get_current_editorset()

        # For usability, allow Ctrl-S to short-circuit to Save-As if
        # we are working on a yet-to-be-saved image
        if not os.path.exists(eset.filename):
            return self.do_saveas()

        eset.save()

    def do_saveas(self):
        eset = self.get_current_editorset()

        if isinstance(eset.radio, chirp_common.CloneModeRadio):
            types = [("Radio-specific Image (*.img)", "img")]
        elif isinstance(eset.radio, generic_csv.CSVRadio):
            types = [("CSV File (*.csv)", "csv")]
        elif isinstance(eset.radio, xml.XMLRadio):
            types = [("CHIRP File (*.chirp)", "chirp")]
        else:
            types = [("ERROR", "*")]

        if isinstance(eset.radio, vx7.VX7Radio):
            types += [("VX7 Commander (*.vx7)", "vx7")]

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

    def _get_recent_list(self):
        recent = []
        for i in range(0, KEEP_RECENT):
            fn = CONF.get("recent%i" % i, "state")
            if fn:
                recent.append(fn)
        return recent
                    
    def _set_recent_list(self, recent):
        for fn in recent:
            CONF.set("recent%i" % recent.index(fn), fn, "state")

    def update_recent_files(self):
        i = 0
        for fname in self._get_recent_list():
            action_name = "recent%i" % i
            path = "/MenuBar/file/recent"

            old_action = self.menu_ag.get_action(action_name)
            if old_action:
                self.menu_ag.remove_action(old_action)

            file_basename = os.path.basename(fname).replace("_", "__")
            action = gtk.Action(action_name,
                                "_%i. %s" % (i+1, file_basename),
                                "Open recent file %s" % fname, "")
            action.connect("activate", lambda a,f: self.do_open(f), fname)
            mid = self.menu_uim.new_merge_id()
            self.menu_uim.add_ui(mid, path, 
                                 action_name, action_name,
                                 gtk.UI_MANAGER_MENUITEM, False)
            self.menu_ag.add_action(action)
            i += 1

    def record_recent_file(self, filename):

        recent_files = self._get_recent_list()
        if filename not in recent_files:
            if len(recent_files) == KEEP_RECENT:
                del recent_files[-1]
            recent_files.insert(0, filename)
            self._set_recent_list(recent_files)

        self.update_recent_files()

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
            ser.flushInput()
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio = settings.radio_class(ser)

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
            ser.flushInput()
        except serial.SerialException, e:
            d = inputdialog.ExceptionDialog(e)
            d.run()
            d.destroy()
            return

        radio.set_pipe(ser)

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
    
        eset.prepare_close()

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

    def do_repeaterbook_prompt(self):
        if not CONF.get_bool("has_seen_credit", "repeaterbook"):
            d = gtk.MessageDialog(parent=self, buttons=gtk.BUTTONS_OK)
            d.set_markup("<big><big><b>RepeaterBook</b></big>\r\n" + \
                             "<i>North American Repeater Directory</i></big>")
            d.format_secondary_markup("For more information about this " +\
                                          "free service, please go to\r\n" +\
                                          "http://www.repeaterbook.com")
            d.run()
            d.destroy()
            CONF.set_bool("has_seen_credit", True, "repeaterbook")

        default_state = "Oregon"
        default_band = "--All--"
        try:
            code = int(CONF.get("state", "repeaterbook"))
            for k,v in FIPS_CODES.items():
                if code == v:
                    default_state = k
                    break

            code = int(CONF.get("band", "repeaterbook"))
            for k,v in RB_BANDS.items():
                if code == v:
                    default_band = k
                    break
        except:
            pass

        state = miscwidgets.make_choice(sorted(FIPS_CODES.keys()),
                                        False, default_state)
        band = miscwidgets.make_choice(sorted(RB_BANDS.keys(), key=key_bands),
                                       False, default_band)
        d = inputdialog.FieldDialog(title="RepeaterBook Query", parent=self)
        d.add_field("State", state)
        d.add_field("Band", band)

        r = d.run()
        d.destroy()
        if r != gtk.RESPONSE_OK:
            return False

        code = FIPS_CODES[state.get_active_text()]
        freq = RB_BANDS[band.get_active_text()]
        CONF.set("state", str(code), "repeaterbook")
        CONF.set("band", str(freq), "repeaterbook")

        return True

    def do_repeaterbook(self):
        self.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        if not self.do_repeaterbook_prompt():
            self.window.set_cursor(None)
            return

        try:
            code = int(CONF.get("state", "repeaterbook"))
        except:
            code = 41 # Oregon default

        try:
            band = int(CONF.get("band", "repeaterbook"))
        except:
            band = 14 # 2m default

        query = "http://www.repeaterbook.com/repeaters/downloads/chirp.php?" + \
            "func=default&state_id=%02i&band=%s&freq=%%&band6=%%&loc=%%" + \
            "&county_id=%%&status_id=%%&features=%%&coverage=%%&use=%%"
        query = query % (code, band and band or "%%")

        # Do this in case the import process is going to take a while
        # to make sure we process events leading up to this
        gtk.gdk.window_process_all_updates()
        while gtk.events_pending():
            gtk.main_iteration(False)

        fn = tempfile.mktemp(".csv")
        filename, headers = urllib.urlretrieve(query, fn)
        if not os.path.exists(filename):
            print "Failed, headers were:"
            print str(headers)
            common.show_error("RepeaterBook query failed")
            self.window.set_cursor(None)
            return

        self.window.set_cursor(None)
        eset = self.get_current_editorset()
        count = eset.do_import(filename)
        reporting.report_model_usage(eset.rthread.radio, "import", count > 0)

    def do_rfinder_prompt(self):
        fields = {"1Email"    : (gtk.Entry(),
                                lambda x: "@" in x),
                  "2Password" : (gtk.Entry(),
                                lambda x: x),
                  "3Latitude" : (gtk.Entry(),
                                lambda x: float(x) < 90 and float(x) > -90),
                  "4Longitude": (gtk.Entry(),
                                lambda x: float(x) < 180 and float(x) > -180),
                  }

        d = inputdialog.FieldDialog(title="RFinder Login", parent=self)
        for k in sorted(fields.keys()):
            d.add_field(k[1:], fields[k][0])
            fields[k][0].set_text(CONF.get(k[1:], "rfinder") or "")
            fields[k][0].set_visibility(k != "2Password")

        while d.run() == gtk.RESPONSE_OK:
            valid = True
            for k in sorted(fields.keys()):
                widget, validator = fields[k]
                try:
                    if validator(widget.get_text()):
                        CONF.set(k[1:], widget.get_text(), "rfinder")
                        continue
                except Exception:
                    pass
                common.show_error("Invalid value for %s" % k[1:])
                valid = False
                break

            if valid:
                d.destroy()
                return True

        d.destroy()
        return False

    def do_rfinder(self):
        self.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        if not self.do_rfinder_prompt():
            self.window.set_cursor(None)
            return

        lat = CONF.get_float("Latitude", "rfinder")
        lon = CONF.get_float("Longitude", "rfinder")
        passwd = CONF.get("Password", "rfinder")
        email = CONF.get("Email", "rfinder")

        # Do this in case the import process is going to take a while
        # to make sure we process events leading up to this
        gtk.gdk.window_process_all_updates()
        while gtk.events_pending():
            gtk.main_iteration(False)

        eset = self.get_current_editorset()
        count = eset.do_import("rfinder://%s/%s/%f/%f" % (email, passwd, lat, lon))
        reporting.report_model_usage(eset.rthread.radio, "import", count > 0)

        self.window.set_cursor(None)

    def do_export(self):
        types = [("CSV Files (*.csv)", "csv"),
                 ("CHIRP Files (*.chirp)", "chirp"),
                 ]

        eset = self.get_current_editorset()

        if os.path.exists(eset.filename):
            base = os.path.basename(eset.filename)
            if "." in base:
                base = base[:base.rindex(".")]
            defname = base
        else:
            defname = "radio"

        filen = platform.get_platform().gui_save_file(default_name=defname,
                                                      types=types)
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
        d.set_copyright("Copyright 2011 Dan Smith (KK7DS)")
        d.set_website("http://chirp.danplanet.com")
        d.set_authors(("Dan Smith <dsmith@danplanet.com>",))
        d.set_comments(verinfo)
        
        d.run()
        d.destroy()

    def do_columns(self):
        eset = self.get_current_editorset()
        driver = directory.get_driver(eset.rthread.radio.__class__)
        radio_name = "%s %s %s" % (eset.rthread.radio.VENDOR,
                                   eset.rthread.radio.MODEL,
                                   eset.rthread.radio.VARIANT)
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

        label = gtk.Label("Visible columns for %s" % radio_name)
        label.show()
        vbox.pack_start(label)

        fields = []
        unsupported = eset.memedit.get_unsupported_columns()
        for colspec in eset.memedit.cols:
            if colspec[0].startswith("_"):
                continue
            elif colspec[0] in unsupported:
                continue
            label = colspec[0]
            visible = eset.memedit.get_column_visible(eset.memedit.col(label))
            widget = gtk.CheckButton(label)
            widget.set_active(visible)
            fields.append(widget)
            vbox.pack_start(widget, 1, 1, 1)
            widget.show()

        res = d.run()
        selected_columns = []
        if res == gtk.RESPONSE_OK:
            for widget in fields:
                colnum = eset.memedit.col(widget.get_label())
                eset.memedit.set_column_visible(colnum, widget.get_active())
                if widget.get_active():
                    selected_columns.append(widget.get_label())
                                                
        d.destroy()

        CONF.set(driver, ",".join(selected_columns), "memedit_columns")

    def do_hide_unused(self, action):
        eset = self.get_current_editorset()
        eset.memedit.set_hide_unused(action.get_active())

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

    def do_toggle_autorpt(self, action):
        CONF.set_bool("autorpt", action.get_active(), "memedit")

    def do_toggle_developer(self, action):
        conf = config.get()
        conf.set_bool("developer", action.get_active(), "state")

        devaction = self.menu_ag.get_action("viewdeveloper")
        devaction.set_visible(action.get_active())

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
        elif action == "rfinder":
            self.do_rfinder()
        elif action == "export":
            self.do_export()
        elif action == "rbook":
            self.do_repeaterbook()
        elif action == "about":
            self.do_about()
        elif action == "columns":
            self.do_columns()
        elif action == "hide_unused":
            self.do_hide_unused(_action)
        elif action == "cancelq":
            self.do_clearq()
        elif action == "report":
            self.do_toggle_report(_action)
        elif action == "autorpt":
            self.do_toggle_autorpt(_action)
        elif action == "developer":
            self.do_toggle_developer(_action)
        elif action in ["cut", "copy", "paste", "delete",
                        "move_up", "move_dn", "exchange",
                        "devshowraw", "devdiffraw"]:
            self.get_current_editorset().memedit.hotkey(_action)
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
      <menu action="recent" name="recent"/>
      <menuitem action="save"/>
      <menuitem action="saveas"/>
      <separator/>
      <menuitem action="import"/>
      <menuitem action="export"/>
      <separator/>
      <menuitem action="close"/>
      <menuitem action="quit"/>
    </menu>
    <menu action="edit">
      <menuitem action="cut"/>
      <menuitem action="copy"/>
      <menuitem action="paste"/>
      <menuitem action="delete"/>
      <separator/>
      <menuitem action="move_up"/>
      <menuitem action="move_dn"/>
      <menuitem action="exchange"/>
    </menu>
    <menu action="view">
      <menuitem action="columns"/>
      <menuitem action="hide_unused"/>
      <menu action="viewdeveloper">
        <menuitem action="devshowraw"/>
        <menuitem action="devdiffraw"/>
      </menu>
    </menu>
    <menu action="radio" name="radio">
      <menuitem action="download"/>
      <menuitem action="upload"/>
      <menuitem action="rbook"/>
      <menuitem action="rfinder"/>
      <separator/>
      <menuitem action="autorpt"/>
      <separator/>
      <menuitem action="cancelq"/>
    </menu>
    <menu action="help">
      <menuitem action="about"/>
      <menuitem action="report"/>
      <menuitem action="developer"/>
    </menu>
  </menubar>
</ui>
"""
        actions = [\
            ('file', None, "_File", None, None, self.mh),
            ('new', gtk.STOCK_NEW, None, None, None, self.mh),
            ('open', gtk.STOCK_OPEN, None, None, None, self.mh),
            ('recent', None, "_Recent", None, None, self.mh),
            ('save', gtk.STOCK_SAVE, None, None, None, self.mh),
            ('saveas', gtk.STOCK_SAVE_AS, None, None, None, self.mh),
            ('close', gtk.STOCK_CLOSE, None, None, None, self.mh),
            ('quit', gtk.STOCK_QUIT, None, None, None, self.mh),
            ('edit', None, "_Edit", None, None, self.mh),
            ('cut', None, "_Cut", "<Ctrl>x", None, self.mh),
            ('copy', None, "_Copy", "<Ctrl>c", None, self.mh),
            ('paste', None, "_Paste", "<Ctrl>v", None, self.mh),
            ('delete', None, "_Delete", "Delete", None, self.mh),
            ('move_up', None, "Move _Up", "<Control>Up", None, self.mh),
            ('move_dn', None, "Move D_n", "<Control>Down", None, self.mh),
            ('exchange', None, "E_xchange", "<Control><Shift>x", None, self.mh),
            ('view', None, "_View", None, None, self.mh),
            ('columns', None, 'Columns', None, None, self.mh),
            ('viewdeveloper', None, "Developer", None, None, self.mh),
            ('devshowraw', None, 'Show raw memory', "<Control><Shift>r", None, self.mh),
            ('devdiffraw', None, 'Diff raw memories', "<Control><Shift>d", None, self.mh),
            ('radio', None, "_Radio", None, None, self.mh),
            ('download', None, "Download From Radio", "<Alt>d", None, self.mh),
            ('upload', None, "Upload To Radio", "<Alt>u", None, self.mh),
            ('import', None, 'Import', "<Alt>i", None, self.mh),
            ('export', None, 'Export', "<Alt>x", None, self.mh),
            ('rfinder', None, "Import from RFinder", None, None, self.mh),
            ('export_chirp', None, 'CHIRP Native File', None, None, self.mh),
            ('export_csv', None, 'CSV File', None, None, self.mh),
            ('rbook', None, "Import from RepeaterBook", None, None, self.mh),
            ('cancelq', gtk.STOCK_STOP, None, "Escape", None, self.mh),
            ('help', None, 'Help', None, None, self.mh),
            ('about', gtk.STOCK_ABOUT, None, None, None, self.mh),
            ]

        conf = config.get()
        re = not conf.get_bool("no_report");
        hu = conf.get_bool("hide_unused", "memedit")
        ro = conf.get_bool("autorpt", "memedit")
        dv = conf.get_bool("developer", "state")

        toggles = [\
            ('report', None, "Report statistics", None, None, self.mh, re),
            ('hide_unused', None, 'Hide Unused Fields', None, None, self.mh, hu),
            ('autorpt', None, 'Automatic Repeater Offset', None, None, self.mh, ro),
            ('developer', None, "Enable Developer Functions", None, None, self.mh, dv),
            ]

        self.menu_uim = gtk.UIManager()
        self.menu_ag = gtk.ActionGroup("MenuBar")
        self.menu_ag.add_actions(actions)
        self.menu_ag.add_toggle_actions(toggles)

        self.menu_uim.insert_action_group(self.menu_ag, 0)
        self.menu_uim.add_ui_from_string(menu_xml)

        self.add_accel_group(self.menu_uim.get_accel_group())

        self.recentmenu = self.menu_uim.get_widget("/MenuBar/file/recent")

        # Initialize
        self.do_toggle_developer(self.menu_ag.get_action("developer"))

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

    def setup_extra_hotkeys(self):
        accelg = self.menu_uim.get_accel_group()

        memedit = lambda a: self.get_current_editorset().memedit.hotkey(a)

        actions = [
            # ("action_name", "key", function)
            ]

        for name, key, fn in actions:
            a = gtk.Action(name, name, name, "")
            a.connect("activate", fn)
            self.menu_ag.add_action_with_accel(a, key)
            a.set_accel_group(accelg)
            a.connect_accelerator()
        
    def __init__(self, *args, **kwargs):
        gtk.Window.__init__(self, *args, **kwargs)

        d = CONF.get("last_dir", "state")
        if d and os.path.isdir(d):
            platform.get_platform().set_last_dir(d)

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

        if not CONF.is_defined("autorpt", "memedit"):
            print "autorpt not set et"
            CONF.set_bool("autorpt", True, "memedit")

        self.update_recent_files()
        self.setup_extra_hotkeys()
