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

from chirp import chirp_common, directory, generic_csv, generic_xml
from chirpui import memedit, dstaredit, bankedit, common, importdialog
from chirpui import inputdialog, reporting, settingsedit

class EditorSet(gtk.VBox):
    __gsignals__ = {
        "want-close" : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
        "status" : (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE,
                    (gobject.TYPE_STRING,)),
        "usermsg": (gobject.SIGNAL_RUN_LAST,
                   gobject.TYPE_NONE,
                   (gobject.TYPE_STRING,)),
        "editor-selected" : (gobject.SIGNAL_RUN_LAST,
                             gobject.TYPE_NONE,
                             (gobject.TYPE_STRING,)),
        }

    def _make_device_editors(self, device, devrthread, index):
        key = "memedit%i" % index
        if isinstance(device, chirp_common.IcomDstarSupport):
            self.editors[key] = memedit.DstarMemoryEditor(devrthread)
        else:
            self.editors[key] = memedit.MemoryEditor(devrthread)

        self.editors[key].connect("usermsg",
                                  lambda e, m: self.emit("usermsg", m))
        self.editors[key].connect("changed", self.editor_changed)

        if self.rf.has_sub_devices:
            label = (_("Memories (%(variant)s)") % 
                     dict(variant=device.VARIANT))
            rf = device.get_features()
        else:
            label = _("Memories")
            rf = self.rf
        lab = gtk.Label(label)
        memedit_tab = self.tabs.append_page(self.editors[key].root, lab)
        self.editors[key].root.show()

        if rf.has_bank:
            key = "bank_members%i" % index
            self.editors[key] = bankedit.BankMembershipEditor(devrthread, self)
            if self.rf.has_sub_devices:
                label = _("Banks (%(variant)s)") % dict(variant=device.VARIANT)
            else:
                label = _("Banks")
            lab = gtk.Label(label)
            self.tabs.append_page(self.editors[key].root, lab)
            self.editors[key].root.show()
            self.editors[key].connect("changed", self.banks_changed)

        if rf.has_bank_names:
            key = "bank_names%i" % index
            self.editors[key] = bankedit.BankNameEditor(devrthread)
            if self.rf.has_sub_devices:
                label = (_("Bank Names (%(variant)s)") %
                         dict(variant=device.VARIANT))
            else:
                label = _("Bank Names")
            lab = gtk.Label(label)
            self.tabs.append_page(self.editors[key].root, lab)
            self.editors[key].root.show()
            self.editors[key].connect("changed", self.banks_changed)

    def __init__(self, source, parent_window=None, filename=None, tempname=None):
        gtk.VBox.__init__(self, True, 0)

        self.parent_window = parent_window

        if isinstance(source, str):
            self.filename = source
            self.radio = directory.get_radio_by_image(self.filename)
        elif isinstance(source, chirp_common.Radio):
            self.radio = source
            self.filename = filename or tempname or source.VARIANT
        else:
            raise Exception("Unknown source type")

        rthread = common.RadioThread(self.radio)
        rthread.setDaemon(True)
        rthread.start()

        rthread.connect("status", lambda e, m: self.emit("status", m))

        self.tabs = gtk.Notebook()
        self.tabs.connect("switch-page", self.tab_selected)
        self.tabs.set_tab_pos(gtk.POS_LEFT)

        self.editors = {
            "dstar"        : None,
            "settings"     : None,
            }

        self.rf = self.radio.get_features()
        if self.rf.has_sub_devices:
            devices = self.radio.get_sub_devices()
        else:
            devices = [self.radio]

        index = 0
        for device in devices:
            devrthread = common.RadioThread(device, rthread)
            devrthread.setDaemon(True)
            devrthread.start()
            self._make_device_editors(device, devrthread, index)
            index += 1

        if isinstance(self.radio, chirp_common.IcomDstarSupport):
            self.editors["dstar"] = dstaredit.DStarEditor(rthread)

        if self.rf.has_settings:
            self.editors["settings"] = settingsedit.SettingsEditor(rthread)

        if self.editors["dstar"]:
            self.tabs.append_page(self.editors["dstar"].root,
                                  gtk.Label(_("D-STAR")))
            self.editors["dstar"].root.show()
            self.editors["dstar"].connect("changed", self.dstar_changed)

        if self.editors["settings"]:
            self.tabs.append_page(self.editors["settings"].root,
                                  gtk.Label(_("Settings")))
            self.editors["settings"].root.show()

        self.pack_start(self.tabs)
        self.tabs.show()

        self.label = self.text_label = None
        self.make_label()
        self.modified = (tempname is not None)
        if tempname:
            self.filename = tempname
        self.update_tab()

    def make_label(self):
        self.label = gtk.HBox(False, 0)

        self.text_label = gtk.Label("")
        self.text_label.show()
        self.label.pack_start(self.text_label, 1, 1, 1)

        button = gtk.Button("X")
        button.set_relief(gtk.RELIEF_NONE)
        button.connect("clicked", lambda x: self.emit("want-close"))
        button.show()
        self.label.pack_start(button, 0, 0, 0)

        self.label.show()

    def update_tab(self):
        fn = os.path.basename(self.filename)
        if self.modified:
            text = "%s*" % fn
        else:
            text = fn

        self.text_label.set_text(self.radio.get_name() + ": " + text)

    def save(self, fname=None):
        if not fname:
            fname = self.filename
            if not os.path.exists(self.filename):
                return # Probably before the first "Save as"
        else:
            self.filename = fname

        self.rthread.lock()
        try:
            self.radio.save(fname)
        except:
            self.rthread.unlock()
            raise
        self.rthread.unlock()

        self.modified = False
        self.update_tab()

    def dstar_changed(self, *args):
        print "D-STAR editor changed"
        dstared = self.editors["dstar"]
        for editor in self.editors.values():
            if isinstance(editor, memedit.MemoryEditor):
                editor.set_urcall_list(dstared.editor_ucall.get_callsigns())
                editor.set_repeater_list(dstared.editor_rcall.get_callsigns())
                editor.prefill()
        if not isinstance(self.radio, chirp_common.LiveRadio):
            self.modified = True
            self.update_tab()

    def banks_changed(self, *args):
        print "Banks changed"
        for editor in self.editors.values():
            if isinstance(editor, bankedit.BankMembershipEditor):
                editor.banks_changed()
        if not isinstance(self.radio, chirp_common.LiveRadio):
            self.modified = True
            self.update_tab()

    def editor_changed(self, *args):
        if not isinstance(self.radio, chirp_common.LiveRadio):
            self.modified = True
            self.update_tab()
        for editor in self.editors.values():
            if isinstance(editor, bankedit.BankMembershipEditor):
                editor.memories_changed()

    def get_tab_label(self):
        return self.label

    def is_modified(self):
        return self.modified

    def _do_import_locked(self, dlgclass, src_radio, dst_rthread):

        # An import/export action needs to be done in the absence of any
        # other queued changes.  So, we make sure that nothing else is
        # staged for the thread and lock it up.  Then we use the hidden
        # interface to queue our own changes before opening it up to the
        # rest of the world.

        dst_rthread._qlock_when_idle(5) # Suspend job submission when idle

        dialog = dlgclass(src_radio, dst_rthread.radio, self.parent_window)
        r = dialog.run()
        dialog.hide()
        if r != gtk.RESPONSE_OK:
            dst_rthread._qunlock()
            return

        count = dialog.do_import(dst_rthread)
        print "Imported %i" % count
        dst_rthread._qunlock()

        if count > 0:
            self.editor_changed()
            current_editor = self.get_current_editor()
            gobject.idle_add(current_editor.prefill)

        return count

    def choose_sub_device(self, radio):
        devices = radio.get_sub_devices()
        choices = [x.VARIANT for x in devices]

        d = inputdialog.ChoiceDialog(choices)
        d.label.set_text(_("The {vendor} {model} has multiple "
                           "independent sub-devices").format( \
                vendor=radio.VENDOR, model=radio.MODEL) + os.linesep + \
                             _("Choose one to import from:"))
        r = d.run()
        chosen = d.choice.get_active_text()
        d.destroy()
        if r == gtk.RESPONSE_CANCEL:
            raise Exception(_("Cancelled"))
        for d in devices:
            if d.VARIANT == chosen:
                return d

        raise Exception(_("Internal Error"))

    def do_import(self, filen):
        current_editor = self.get_current_editor()
        if not isinstance(current_editor, memedit.MemoryEditor):
            # FIXME: We need a nice message to let the user know that they
            # need to select the appropriate memory editor tab before doing
            # and import so that we know which thread and editor to import
            # into and refresh. This will do for the moment.
            common.show_error("Memory editor must be selected before import")
        try:
            src_radio = directory.get_radio_by_image(filen)
        except Exception, e:
            common.show_error(e)
            return

        if isinstance(src_radio, chirp_common.NetworkSourceRadio):
            ww = importdialog.WaitWindow("Querying...", self.parent_window)
            ww.show()
            def status(status):
                ww.set(float(status.cur) / float(status.max))
            try:
                src_radio.status_fn = status
                src_radio.do_fetch()
            except Exception, e:
                common.show_error(e)
                ww.hide()
                return
            ww.hide()

        try:
            if src_radio.get_features().has_sub_devices:
                src_radio = self.choose_sub_device(src_radio)
        except Exception, e:
            common.show_error(e)
            return

        if len(src_radio.errors) > 0:
            _filen = os.path.basename(filen)
            common.show_error_text(_("There were errors while opening {file}. "
                                     "The affected memories will not "
                                     "be importable!").format(file=_filen),
                                   "\r\n".join(src_radio.errors))

        try:
            count = self._do_import_locked(importdialog.ImportDialog,
                                           src_radio,
                                           self.rthread)
            reporting.report_model_usage(src_radio, "importsrc", True)
        except Exception, e:
            common.log_exception()
            common.show_error(_("There was an error during "
                                "import: {error}").format(error=e))
        
    def do_export(self, filen):
        try:
            if filen.lower().endswith(".csv"):
                dst_radio = generic_csv.CSVRadio(filen)
            elif filen.lower().endswith(".chirp"):
                dst_radio = generic_xml.XMLRadio(filen)
            else:
                raise Exception(_("Unsupported file type"))
        except Exception, e:
            common.log_exception()
            common.show_error(e)
            return

        dst_rthread = common.RadioThread(dst_radio)
        dst_rthread.setDaemon(True)
        dst_rthread.start()

        try:
            count = self._do_import_locked(importdialog.ExportDialog,
                                           self.rthread.radio,
                                           dst_rthread)
        except Exception, e:
            common.log_exception()
            common.show_error(_("There was an error during "
                                "export: {error}").format(error=e),
                              self.parent_window)
            return

        if count <= 0:
            return

        # Wait for thread queue to complete
        dst_rthread._qlock_when_idle()

        try:
            dst_radio.save(filename=filen)
        except Exception, e:
            common.log_exception()
            common.show_error(_("There was an error during "
                                "export: {error}").format(error=e),
                              self)
            
    def prime(self):
        # NOTE: this is only called to prime new CSV files, so assume
        # only one memory editor for now
        mem = chirp_common.Memory()
        mem.freq = 146010000

        def cb(*args):
            gobject.idle_add(self.editors["memedit0"].prefill)

        job = common.RadioJob(cb, "set_memory", mem)
        job.set_desc(_("Priming memory"))
        self.rthread.submit(job)

    def tab_selected(self, notebook, foo, pagenum):
        widget = notebook.get_nth_page(pagenum)
        for k,v in self.editors.items():
            if v and v.root == widget:
                v.focus()
                self.emit("editor-selected", k)
            elif v:
                v.unfocus()

    def set_read_only(self, read_only=True):
        for editor in self.editors.values():
            editor and editor.set_read_only(read_only)

    def get_read_only(self):
        return self.editors["memedit0"].get_read_only()

    def prepare_close(self):
        for editor in self.editors.values():
            editor and editor.prepare_close()

    def get_current_editor(self):
        for lab, e in self.editors.items():
            if e and self.tabs.page_num(e.root) == self.tabs.get_current_page():
                return e
        raise Exception("No editor selected?")

    @property
    def rthread(self):
        """Magic rthread property to return the rthread of the currently-
        selected editor"""
        e = self.get_current_editor()
        return e.rthread
