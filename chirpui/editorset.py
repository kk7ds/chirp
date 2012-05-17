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

from chirp import chirp_common, directory, generic_csv, xml
from chirpui import memedit, dstaredit, bankedit, common, importdialog
from chirpui import inputdialog, reporting

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

        self.rthread = common.RadioThread(self.radio)
        self.rthread.setDaemon(True)
        self.rthread.start()

        self.rthread.connect("status", lambda e, m: self.emit("status", m))

        self.tabs = gtk.Notebook()
        self.tabs.connect("switch-page", self.tab_selected)
        self.tabs.set_tab_pos(gtk.POS_LEFT)

        self.editors = {
            "memedit"      : None,
            "dstar"        : None,
            "bank_names"   : None,
            "bank_members" : None,
            }

        if isinstance(self.radio, chirp_common.IcomDstarSupport):
            self.editors["memedit"] = memedit.DstarMemoryEditor(self.rthread)
            self.editors["dstar"] = dstaredit.DStarEditor(self.rthread)
        else:
            self.editors["memedit"] = memedit.MemoryEditor(self.rthread)

        self.editors["memedit"].connect("usermsg",
                                        lambda e, m: self.emit("usermsg", m))

        rf = self.radio.get_features()

        if rf.has_bank:
            self.editors["bank_members"] = \
                bankedit.BankMembershipEditor(self.rthread, self)
        
        if rf.has_bank_names:
            self.editors["bank_names"] = bankedit.BankNameEditor(self.rthread)

        lab = gtk.Label(_("Memories"))
        self.tabs.append_page(self.editors["memedit"].root, lab)
        self.editors["memedit"].root.show()

        if self.editors["dstar"]:
            lab = gtk.Label(_("D-STAR"))
            self.tabs.append_page(self.editors["dstar"].root, lab)
            self.editors["dstar"].root.show()
            self.editors["dstar"].connect("changed", self.dstar_changed)

        if self.editors["bank_names"]:
            lab = gtk.Label(_("Bank Names"))
            self.tabs.append_page(self.editors["bank_names"].root, lab)
            self.editors["bank_names"].root.show()
            self.editors["bank_names"].connect("changed", self.banks_changed)

        if self.editors["bank_members"]:
            lab = gtk.Label(_("Banks"))
            self.tabs.append_page(self.editors["bank_members"].root, lab)
            self.editors["bank_members"].root.show()
            self.editors["bank_members"].connect("changed", self.banks_changed)

        self.pack_start(self.tabs)
        self.tabs.show()

        # pylint: disable-msg=E1101
        self.editors["memedit"].connect("changed", self.editor_changed)

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
        self.radio.save(fname)
        self.rthread.unlock()

        self.modified = False
        self.update_tab()

    def dstar_changed(self, *args):
        print "D-STAR editor changed"
        memedit = self.editors["memedit"]
        dstared = self.editors["dstar"]
        memedit.set_urcall_list(dstared.editor_ucall.get_callsigns())
        memedit.set_repeater_list(dstared.editor_rcall.get_callsigns())
        memedit.prefill()
        self.modified = True
        self.update_tab()

    def banks_changed(self, *args):
        print "Banks changed"
        if self.editors["bank_members"]:
            self.editors["bank_members"].banks_changed()
        self.modified = True
        self.update_tab()

    def editor_changed(self, *args):
        if not isinstance(self.radio, chirp_common.LiveRadio):
            self.modified = True
            self.update_tab()
        if self.editors["bank_members"]:
            self.editors["bank_members"].memories_changed()

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
            gobject.idle_add(self.editors["memedit"].prefill)

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
        try:
            src_radio = directory.get_radio_by_image(filen)
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
                dst_radio = xml.XMLRadio(filen)
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
                              self)
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
        mem = chirp_common.Memory()
        mem.freq = 146010000

        def cb(*args):
            gobject.idle_add(self.editors["memedit"].prefill)

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
        self.editors["memedit"].set_read_only(read_only)

    def prepare_close(self):
        self.editors["memedit"].prepare_close()

    def get_current_editor(self):
        for e in self.editors.values():
            if e and self.tabs.page_num(e.root) == self.tabs.get_current_page():
                return e
        raise Exception("No editor selected?")
