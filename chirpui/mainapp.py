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
from glob import glob
import shutil
import time

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
from chirp import platform, xml, generic_csv, directory, util
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
        
        for i in ["export", "import", "close", "columns", "rbook", "rfinder",
                  "stock", "move_up", "move_dn", "exchange",
                  "cut", "copy", "paste", "delete", "viewdeveloper"]:
            set_action_sensitive(i, eset is not None)

    def ev_status(self, editorset, msg):
        self.sb_radio.pop(0)
        self.sb_radio.push(0, msg)

    def ev_usermsg(self, editorset, msg):
        self.sb_general.pop(0)
        self.sb_general.push(0, msg)

    def ev_editor_selected(self, editorset, editortype):
        mappings = {
            "memedit" : ["view", "edit"],
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

    def do_diff_radio(self):
        if self.tabs.get_n_pages() < 2:
            common.show_error("Diff tabs requires at least two open tabs!")
            return

        esets = []
        for i in range(0, self.tabs.get_n_pages()):
            esets.append(self.tabs.get_nth_page(i))

        d = gtk.Dialog(title="Diff Radios",
                       buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK,
                                gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL),
                       parent=self)

        choices = []
        for eset in esets:
            choices.append("%s %s (%s)" % (eset.rthread.radio.VENDOR,
                                           eset.rthread.radio.MODEL,
                                           eset.filename))
        choice_a = miscwidgets.make_choice(choices, False, choices[0])
        choice_a.show()
        chan_a = gtk.SpinButton()
        chan_a.get_adjustment().set_all(1, -1, 999, 1, 10, 0)
        chan_a.show()
        hbox = gtk.HBox(False, 3)
        hbox.pack_start(choice_a, 1, 1, 1)
        hbox.pack_start(chan_a, 0, 0, 0)
        hbox.show()
        d.vbox.pack_start(hbox, 0, 0, 0)

        choice_b = miscwidgets.make_choice(choices, False, choices[1])
        choice_b.show()
        chan_b = gtk.SpinButton()
        chan_b.get_adjustment().set_all(1, -1, 999, 1, 10, 0)
        chan_b.show()
        hbox = gtk.HBox(False, 3)
        hbox.pack_start(choice_b, 1, 1, 1)
        hbox.pack_start(chan_b, 0, 0, 0)
        hbox.show()
        d.vbox.pack_start(hbox, 0, 0, 0)

        r = d.run()
        sel_a = choice_a.get_active_text()
        sel_chan_a = chan_a.get_value()
        sel_b = choice_b.get_active_text()
        sel_chan_b = chan_b.get_value()
        d.destroy()
        if r == gtk.RESPONSE_CANCEL:
            return

        if sel_a == sel_b:
            common.show_error("Can't diff the same tab!")
            return

        print "Selected %s@%i and %s@%i" % (sel_a, sel_chan_a,
                                            sel_b, sel_chan_b)

        eset_a = esets[choices.index(sel_a)]
        eset_b = esets[choices.index(sel_b)]

        def _show_diff(mem_b, mem_a):
            # Step 3: Show the diff
            diff = common.simple_diff(mem_a, mem_b)
            common.show_diff_blob("Differences", diff)

        def _get_mem_b(mem_a):
            # Step 2: Get memory b
            job = common.RadioJob(_show_diff, "get_raw_memory", int(sel_chan_b))
            job.set_cb_args(mem_a)
            eset_b.rthread.submit(job)
            
        if sel_chan_a >= 0 and sel_chan_b >= 0:
            # Diff numbered memory
            # Step 1: Get memory a
            job = common.RadioJob(_get_mem_b, "get_raw_memory", int(sel_chan_a))
            eset_a.rthread.submit(job)
        elif isinstance(eset_a.rthread.radio, chirp_common.CloneModeRadio) and\
                isinstance(eset_b.rthread.radio, chirp_common.CloneModeRadio):
            # Diff whole (can do this without a job, since both are clone-mode)
            a = util.hexprint(eset_a.rthread.radio._mmap.get_packed())
            b = util.hexprint(eset_b.rthread.radio._mmap.get_packed())
            common.show_diff_blob("Differences", common.simple_diff(a, b))
        else:
            common.show_error("Cannot diff whole live-mode radios!")

    def do_new(self):
        eset = editorset.EditorSet(_("Untitled") + ".csv", self)
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
            types = [(_("CHIRP Radio Images") + " (*.img)", "*.img"),
                     (_("CHIRP Files") + " (*.chirp)", "*.chirp"),
                     (_("CSV Files") + " (*.csv)", "*.csv"),
                     (_("ICF Files") + " (*.icf)", "*.icf"),
                     (_("VX7 Commander Files") + " (*.vx7)", "*.vx7"),
                     ]
            fname = platform.get_platform().gui_open_file(types=types)
            if not fname:
                return

        self.record_recent_file(fname)

        if icf.is_icf_file(fname):
            a = common.ask_yesno_question(\
                _("ICF files cannot be edited, only displayed or imported "
                  "into another file. Open in read-only mode?"),
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

            if radio.get_features().has_sub_devices:
                devices = radio.get_sub_devices()
            else:
                devices = [radio]

        prio = len(devices)
        first_tab = False
        for device in devices:
            try:
                eset = editorset.EditorSet(device, self,
                                           filename=fname,
                                           tempname=tempname)
            except Exception, e:
                common.log_exception()
                common.show_error(
                    _("There was an error opening {fname}: {error}").format(
                        fname=fname,
                        error=error))
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
                msg = _("{num} errors during open:").format(num=len(eset.rthread.radio.errors))
                common.show_error_text(msg,
                                       "\r\n".join(eset.rthread.radio.errors))

    def do_live_warning(self, radio):
        d = gtk.MessageDialog(parent=self, buttons=gtk.BUTTONS_OK)
        d.set_markup("<big><b>" + _("Note:") + "</b></big>")
        msg = _("The {vendor} {model} operates in <b>live mode</b>. "
                "This means that any changes you make are immediately sent "
                "to the radio. Because of this, you cannot perform the "
                "<u>Save</u> or <u>Upload</u> operations. If you wish to "
                "edit the contents offline, please <u>Export</u> to a CSV "
                "file, using the <b>File menu</b>.").format(vendor=radio.VENDOR,
                                                            model=radio.MODEL)
        d.format_secondary_markup(msg)

        again = gtk.CheckButton(_("Don't show this again"))
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
            eset = editorset.EditorSet(device, self, tempname=tempname)
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

        label = _("{vendor} {model} image file").format(\
            vendor=eset.radio.VENDOR,
            model=eset.radio.MODEL)
                                                     
        types = [(label + " (*.%s)" % eset.radio.FILE_EXTENSION,
                 eset.radio.FILE_EXTENSION)]

        if isinstance(eset.radio, vx7.VX7Radio):
            types += [(_("VX7 Commander") + " (*.vx7)", "vx7")]

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
            self.do_open_live(radio, tempname="(" + _("Untitled") + ")")
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
                                _("Open recent file {name}").format(name=fname),
                                "")
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

    def import_stock_config(self, action, config):
        eset = self.get_current_editorset()
        count = eset.do_import(config)

    def copy_shipped_stock_configs(self, stock_dir):
        execpath = platform.get_platform().executable_path()
        basepath = os.path.abspath(os.path.join(execpath, "stock_configs"))
        if not os.path.exists(basepath):
            basepath = "/usr/share/chirp/stock_configs"

        files = glob(os.path.join(basepath, "*.csv"))
        for fn in files:
            if os.path.exists(os.path.join(stock_dir, os.path.basename(fn))):
                print "Skipping existing stock config"
                continue
            try:
                shutil.copy(fn, stock_dir)
                print "Copying %s -> %s" % (fn, stock_dir)
            except Exception, e:
                print "ERROR: Unable to copy %s to %s: %s" % (fn, stock_dir, e)
                return False
        return True

    def update_stock_configs(self):
        stock_dir = platform.get_platform().config_file("stock_configs")
        if not os.path.isdir(stock_dir):
            try:
                os.mkdir(stock_dir)
            except Exception, e:
                print "ERROR: Unable to create directory: %s" % stock_dir
                return
        if not self.copy_shipped_stock_configs(stock_dir):
            return

        def _do_import_action(config):
            name = os.path.splitext(os.path.basename(config))[0]
            action_name = "stock-%i" % configs.index(config)
            path = "/MenuBar/radio/stock"
            action = gtk.Action(action_name,
                                name,
                                _("Import stock "
                                  "configuration {name}").format(name=name),
                                "")
            action.connect("activate", self.import_stock_config, config)
            mid = self.menu_uim.new_merge_id()
            mid = self.menu_uim.add_ui(mid, path,
                                       action_name, action_name,
                                       gtk.UI_MANAGER_MENUITEM, False)
            self.menu_ag.add_action(action)

        def _do_open_action(config):
            name = os.path.splitext(os.path.basename(config))[0]
            action_name = "openstock-%i" % configs.index(config)
            path = "/MenuBar/file/openstock"
            action = gtk.Action(action_name,
                                name,
                                _("Open stock "
                                  "configuration {name}").format(name=name),
                                "")
            action.connect("activate", lambda a,c: self.do_open(c), config)
            mid = self.menu_uim.new_merge_id()
            mid = self.menu_uim.add_ui(mid, path,
                                       action_name, action_name,
                                       gtk.UI_MANAGER_MENUITEM, False)
            self.menu_ag.add_action(action)
            

        configs = glob(os.path.join(stock_dir, "*.csv"))
        for config in configs:
            _do_import_action(config)
            _do_open_action(config)

    def do_download(self, port=None, rtype=None):
        d = clone.CloneSettingsDialog(parent=self)
        settings = d.run()
        d.destroy()
        if not settings:
            return

        print "User selected %s %s on port %s" % (settings.radio_class.VENDOR,
                                                  settings.radio_class.MODEL,
                                                  settings.port)

        try:
            ser = serial.Serial(port=settings.port,
                                baudrate=settings.radio_class.BAUD_RATE,
                                rtscts=settings.radio_class.HARDWARE_FLOW,
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
                                rtscts=radio.HARDWARE_FLOW,
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
            dlg = miscwidgets.YesNoDialog(title=_("Discard Changes?"),
                                          parent=self,
                                          buttons=(gtk.STOCK_YES, gtk.RESPONSE_YES,
                                                   gtk.STOCK_NO, gtk.RESPONSE_NO,
                                                   gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
            dlg.set_text(_("File is modified, save changes before closing?"))
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
        types = [(_("CHIRP Files") + " (*.chirp)", "*.chirp"),
                 (_("CHIRP Radio Images") + " (*.img)", "*.img"),
                 (_("CSV Files") + " (*.csv)", "*.csv"),
                 (_("ICF Files") + " (*.icf)", "*.icf"),
                 (_("VX7 Commander Files") + " (*.vx7)", "*.vx7")]
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

        try:
            # Validate CSV
            from chirp import generic_csv
            r = generic_csv.CSVRadio(filename)
            if r.errors:
                reporting.report_misc_error("repeaterbook",
                                            ("query=%s\n" % query) +
                                            ("\n") +
                                            ("\n".join(r.errors)))
        except Exception, e:
            common.log_exception()

        class RBRadio(chirp_common.Radio):
            VENDOR = "RepeaterBook"
            MODEL = ""
            def __init__(self, *args):
                pass

        reporting.report_model_usage(RBRadio(), "import", True)

        self.window.set_cursor(None)
        eset = self.get_current_editorset()
        count = eset.do_import(filename)

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

        self.window.set_cursor(None)

    def do_export(self):
        types = [(_("CSV Files") + " (*.csv)", "csv"),
                 (_("CHIRP Files") + " (*.chirp)", "chirp"),
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

        if os.path.exists(filen):
            dlg = inputdialog.OverwriteDialog(filen)
            owrite = dlg.run()
            dlg.destroy()
            if owrite != gtk.RESPONSE_OK:
                return
            os.remove(filen)

        count = eset.do_export(filen)
        reporting.report_model_usage(eset.rthread.radio, "export", count > 0)

    def do_about(self):
        d = gtk.AboutDialog()
        d.set_transient_for(self)
        import sys
        verinfo = "GTK %s\nPyGTK %s\nPython %s\n" % ( \
            ".".join([str(x) for x in gtk.gtk_version]),
            ".".join([str(x) for x in gtk.pygtk_version]),
            sys.version.split()[0])

        d.set_name("CHIRP")
        d.set_version(CHIRP_VERSION)
        d.set_copyright("Copyright 2012 Dan Smith (KK7DS)")
        d.set_website("http://chirp.danplanet.com")
        d.set_authors(("Dan Smith <dsmith@danplanet.com>",
                       _("With significant contributions by:"),
                       "Marco IZ3GME",
                       "Rick WZ3RO",
                       "Vernon N7OH"
                       ))
        d.set_translator_credits("Polish: Grzegorz SQ2RBY" +
                                 os.linesep +
                                 "Italian: Fabio IZ2QDH")
        d.set_comments(verinfo)
        
        d.run()
        d.destroy()

    def do_columns(self):
        eset = self.get_current_editorset()
        driver = directory.get_driver(eset.rthread.radio.__class__)
        radio_name = "%s %s %s" % (eset.rthread.radio.VENDOR,
                                   eset.rthread.radio.MODEL,
                                   eset.rthread.radio.VARIANT)
        d = gtk.Dialog(title=_("Select Columns"),
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

        label = gtk.Label(_("Visible columns for {radio}").format(radio=radio_name))
        label.show()
        vbox.pack_start(label)

        fields = []
        memedit = eset.editors["memedit"]
        unsupported = memedit.get_unsupported_columns()
        for colspec in memedit.cols:
            if colspec[0].startswith("_"):
                continue
            elif colspec[0] in unsupported:
                continue
            label = colspec[0]
            visible = memedit.get_column_visible(memedit.col(label))
            widget = gtk.CheckButton(label)
            widget.set_active(visible)
            fields.append(widget)
            vbox.pack_start(widget, 1, 1, 1)
            widget.show()

        res = d.run()
        selected_columns = []
        if res == gtk.RESPONSE_OK:
            for widget in fields:
                colnum = memedit.col(widget.get_label())
                memedit.set_column_visible(colnum, widget.get_active())
                if widget.get_active():
                    selected_columns.append(widget.get_label())
                                                
        d.destroy()

        CONF.set(driver, ",".join(selected_columns), "memedit_columns")

    def do_hide_unused(self, action):
        eset = self.get_current_editorset()
        eset.editors["memedit"].set_hide_unused(action.get_active())

    def do_clearq(self):
        eset = self.get_current_editorset()
        eset.rthread.flush()

    def do_copy(self, cut):
        eset = self.get_current_editorset()
        eset.get_current_editor().copy_selection(cut)

    def do_paste(self):
        eset = self.get_current_editorset()
        eset.get_current_editor().paste_selection()

    def do_delete(self):
        eset = self.get_current_editorset()
        eset.get_current_editor().copy_selection(True)

    def do_toggle_report(self, action):
        if not action.get_active():
            d = gtk.MessageDialog(buttons=gtk.BUTTONS_YES_NO,
                                  parent=self)
            d.set_markup("<b><big>" + _("Reporting is disabled") + "</big></b>")
            msg = _("The reporting feature of CHIRP is designed to help "
                    "<u>improve quality</u> by allowing the authors to focus "
                    "on the radio drivers used most often and errors "
                    "experienced by the users. The reports contain no "
                    "identifying information and are used only for statistical "
                    "purposes by the authors. Your privacy is extremely "
                    "important, but <u>please consider leaving this feature "
                    "enabled to help make CHIRP better!</u>\n\n<b>Are you "
                    "sure you want to disable this feature?</b>")
            d.format_secondary_markup(msg.replace("\n", "\r\n"))
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

    def do_change_language(self):
        langs = ["Auto", "English", "Polish", "Italian"]
        d = inputdialog.ChoiceDialog(langs, parent=self,
                                     title="Choose Language")
        d.label.set_text(_("Choose a language or Auto to use the "
                           "operating system default. You will need to "
                           "restart the application before the change "
                           "will take effect"))
        d.label.set_line_wrap(True)
        r = d.run()
        if r == gtk.RESPONSE_OK:
            print "Chose language %s" % d.choice.get_active_text()
            conf = config.get()
            conf.set("language", d.choice.get_active_text(), "state")
        d.destroy()

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
            self.get_current_editorset().get_current_editor().hotkey(_action)
        elif action == "devdifftab":
            self.do_diff_radio()
        elif action == "language":
            self.do_change_language()
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
      <menu action="openstock" name="openstock"/>
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
        <menuitem action="devdifftab"/>
      </menu>
      <menuitem action="language"/>
    </menu>
    <menu action="radio" name="radio">
      <menuitem action="download"/>
      <menuitem action="upload"/>
      <menuitem action="rbook"/>
      <menuitem action="rfinder"/>
      <menu action="stock" name="stock"/>
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
            ('file', None, _("_File"), None, None, self.mh),
            ('new', gtk.STOCK_NEW, None, None, None, self.mh),
            ('open', gtk.STOCK_OPEN, None, None, None, self.mh),
            ('openstock', None, _("Open stock config"), None, None, self.mh),
            ('recent', None, _("_Recent"), None, None, self.mh),
            ('save', gtk.STOCK_SAVE, None, None, None, self.mh),
            ('saveas', gtk.STOCK_SAVE_AS, None, None, None, self.mh),
            ('close', gtk.STOCK_CLOSE, None, None, None, self.mh),
            ('quit', gtk.STOCK_QUIT, None, None, None, self.mh),
            ('edit', None, _("_Edit"), None, None, self.mh),
            ('cut', None, _("_Cut"), "<Ctrl>x", None, self.mh),
            ('copy', None, _("_Copy"), "<Ctrl>c", None, self.mh),
            ('paste', None, _("_Paste"), "<Ctrl>v", None, self.mh),
            ('delete', None, _("_Delete"), "Delete", None, self.mh),
            ('move_up', None, _("Move _Up"), "<Control>Up", None, self.mh),
            ('move_dn', None, _("Move Dow_n"), "<Control>Down", None, self.mh),
            ('exchange', None, _("E_xchange"), "<Control><Shift>x", None, self.mh),
            ('view', None, _("_View"), None, None, self.mh),
            ('columns', None, _("Columns"), None, None, self.mh),
            ('viewdeveloper', None, _("Developer"), None, None, self.mh),
            ('devshowraw', None, _('Show raw memory'), "<Control><Shift>r", None, self.mh),
            ('devdiffraw', None, _("Diff raw memories"), "<Control><Shift>d", None, self.mh),
            ('devdifftab', None, _("Diff tabs"), None, None, self.mh),
            ('language', None, _("Change language"), None, None, self.mh),
            ('radio', None, _("_Radio"), None, None, self.mh),
            ('download', None, _("Download From Radio"), "<Alt>d", None, self.mh),
            ('upload', None, _("Upload To Radio"), "<Alt>u", None, self.mh),
            ('import', None, _("Import"), "<Alt>i", None, self.mh),
            ('export', None, _("Export"), "<Alt>x", None, self.mh),
            ('rfinder', None, _("Import from RFinder"), None, None, self.mh),
            ('export_chirp', None, _("CHIRP Native File"), None, None, self.mh),
            ('export_csv', None, _("CSV File"), None, None, self.mh),
            ('rbook', None, _("Import from RepeaterBook"), None, None, self.mh),
            ('stock', None, _("Import from stock config"), None, None, self.mh),
            ('cancelq', gtk.STOCK_STOP, None, "Escape", None, self.mh),
            ('help', None, _('Help'), None, None, self.mh),
            ('about', gtk.STOCK_ABOUT, None, None, None, self.mh),
            ]

        conf = config.get()
        re = not conf.get_bool("no_report");
        hu = conf.get_bool("hide_unused", "memedit")
        ro = conf.get_bool("autorpt", "memedit")
        dv = conf.get_bool("developer", "state")

        toggles = [\
            ('report', None, _("Report statistics"), None, None, self.mh, re),
            ('hide_unused', None, _("Hide Unused Fields"), None, None, self.mh, hu),
            ('autorpt', None, _("Automatic Repeater Offset"), None, None, self.mh, ro),
            ('developer', None, _("Enable Developer Functions"), None, None, self.mh, dv),
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

        memedit = lambda a: self.get_current_editorset().editors["memedit"].hotkey(a)

        actions = [
            # ("action_name", "key", function)
            ]

        for name, key, fn in actions:
            a = gtk.Action(name, name, name, "")
            a.connect("activate", fn)
            self.menu_ag.add_action_with_accel(a, key)
            a.set_accel_group(accelg)
            a.connect_accelerator()
        
    def _set_icon(self):
        execpath = platform.get_platform().executable_path()
        path = os.path.abspath(os.path.join(execpath, "share", "chirp.png"))
        if not os.path.exists(path):
            path = "/usr/share/pixmaps/chirp.png"

        if os.path.exists(path):
            self.set_icon_from_file(path)
        else:
            print "Icon %s not found" % path

    def _updates(self, version):
        if not version:
            return

        if version == CHIRP_VERSION:
            return

        print "Server reports version %s is available" % version

        # Report new updates every seven days
        intv = 3600 * 24 * 7

        if CONF.is_defined("last_update_check", "state") and \
             (time.time() - CONF.get_int("last_update_check", "state")) < intv:
            return

        CONF.set_int("last_update_check", int(time.time()), "state")
        d = gtk.MessageDialog(buttons=gtk.BUTTONS_OK, parent=self,
                              type=gtk.MESSAGE_INFO)
        d.set_property("text",
                       _("A new version of CHIRP is available: " +
                         "{ver}. ".format(ver=version) +
                         "It is recommended that you upgrade, so " +
                         "go to http://chirp.danplanet.com soon!"))
        d.run()
        d.destroy()

    def _init_macos(self, menu_bar):
        try:
            import gtk_osxapplication
            macapp = gtk_osxapplication.OSXApplication()
        except ImportError, e:
            print "No MacOS support: %s" % e
            return
        
        menu_bar.hide()
        macapp.set_menu_bar(menu_bar)

        quititem = self.menu_uim.get_widget("/MenuBar/file/quit")
        quititem.hide()

        aboutitem = self.menu_uim.get_widget("/MenuBar/help/about")
        macapp.insert_app_menu_item(aboutitem, 0)

        macapp.set_use_quartz_accelerators(False)
        macapp.ready()

        print "Initialized MacOS support"

    def __init__(self, *args, **kwargs):
        gtk.Window.__init__(self, *args, **kwargs)

        d = CONF.get("last_dir", "state")
        if d and os.path.isdir(d):
            platform.get_platform().set_last_dir(d)

        vbox = gtk.VBox(False, 2)

        self._recent = []

        self.menu_ag = None
        mbar = self.make_menubar()

        if os.name != "nt":
            self._set_icon() # Windows gets the icon from the exe
            if os.uname()[0] == "Darwin":
                self._init_macos(mbar)

        vbox.pack_start(mbar, 0, 0, 0)

        self.tabs = None
        tabs = self.make_tabs()
        tabs.connect("switch-page", lambda n, _, p: self.ev_tab_switched(p))
        tabs.connect("page-removed", lambda *a: self.ev_tab_switched())
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
            d.set_markup("<b><big>" +
                         _("Error reporting is enabled") +
                         "</big></b>")
            d.format_secondary_markup(\
                _("If you wish to disable this feature you may do so in "
                  "the <u>Help</u> menu"))
            d.run()
            d.destroy()
        CONF.set_bool("warned_about_reporting", True)

        if not CONF.is_defined("autorpt", "memedit"):
            print "autorpt not set et"
            CONF.set_bool("autorpt", True, "memedit")

        self.update_recent_files()
        self.update_stock_configs()
        self.setup_extra_hotkeys()

        def updates_callback(ver):
            gobject.idle_add(self._updates, ver)

        if not CONF.get_bool("skip_update_check", "state"):
            reporting.check_for_updates(updates_callback)
