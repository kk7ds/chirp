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
import logging

from chirp import chirp_common, directory
from chirp.drivers import generic_csv, generic_xml
from chirp.ui import memedit, dstaredit, bankedit, common, importdialog
from chirp.ui import inputdialog, reporting, settingsedit, radiobrowser, config

LOG = logging.getLogger(__name__)


class EditorSet(gtk.VBox):
    __gsignals__ = {
        "want-close": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
        "status": (gobject.SIGNAL_RUN_LAST,
                   gobject.TYPE_NONE,
                   (gobject.TYPE_STRING,)),
        "usermsg": (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE,
                    (gobject.TYPE_STRING,)),
        "editor-selected": (gobject.SIGNAL_RUN_LAST,
                            gobject.TYPE_NONE,
                            (gobject.TYPE_STRING,)),
        }

    def _make_device_mapping_editors(self, device, devrthread, index):
        sub_index = 0
        memory_editor = self.editors["memedit%i" % index]
        mappings = device.get_mapping_models()
        for mapping_model in mappings:
            members = bankedit.MappingMembershipEditor(devrthread, self,
                                                       mapping_model)
            label = mapping_model.get_name()
            if self.rf.has_sub_devices:
                label += "(%s)" % device.VARIANT
            lab = gtk.Label(label)
            self.tabs.append_page(members.root, lab)
            self.editors["mapping_members%i%i" % (index, sub_index)] = members

            basename = common.unpluralize(mapping_model.get_name())
            names = bankedit.MappingNameEditor(devrthread, mapping_model)
            label = "%s Names" % basename
            if self.rf.has_sub_devices:
                label += " (%s)" % device.VARIANT
            lab = gtk.Label(label)
            self.tabs.append_page(names.root, lab)
            self.editors["mapping_names%i%i" % (index, sub_index)] = names

            members.root.show()
            members.connect("changed", self.editor_changed)
            if hasattr(mapping_model.get_mappings()[0], "set_name"):
                names.root.show()
                members.connect("changed", lambda x: names.mappings_changed())
                names.connect("changed", lambda x: members.mappings_changed())
                names.connect("changed", self.editor_changed)
            sub_index += 1

    def _make_device_editors(self, device, devrthread, index):
        if isinstance(device, chirp_common.IcomDstarSupport):
            memories = memedit.DstarMemoryEditor(devrthread)
        else:
            memories = memedit.MemoryEditor(devrthread)

        memories.connect("usermsg", lambda e, m: self.emit("usermsg", m))
        memories.connect("changed", self.editor_changed)

        if self.rf.has_sub_devices:
            label = (_("Memories (%(variant)s)") %
                     dict(variant=device.VARIANT))
            rf = device.get_features()
        else:
            label = _("Memories")
            rf = self.rf
        lab = gtk.Label(label)
        self.tabs.append_page(memories.root, lab)
        memories.root.show()
        self.editors["memedit%i" % index] = memories

        self._make_device_mapping_editors(device, devrthread, index)

        if isinstance(device, chirp_common.IcomDstarSupport):
            editor = dstaredit.DStarEditor(devrthread)
            self.tabs.append_page(editor.root, gtk.Label(_("D-STAR")))
            editor.root.show()
            editor.connect("changed", self.dstar_changed, memories)
            editor.connect("changed", self.editor_changed)
            self.editors["dstar"] = editor

    def __init__(self, source, parent_window=None,
                 filename=None, tempname=None):
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

        self.editors = {}

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

        if self.rf.has_settings:
            editor = settingsedit.SettingsEditor(rthread)
            self.tabs.append_page(editor.root, gtk.Label(_("Settings")))
            editor.root.show()
            editor.connect("changed", self.editor_changed)
            self.editors["settings"] = editor

        conf = config.get()
        if (hasattr(self.rthread.radio, '_memobj') and
                conf.get_bool("developer", "state")):
            editor = radiobrowser.RadioBrowser(self.rthread)
            lab = gtk.Label(_("Browser"))
            self.tabs.append_page(editor.root, lab)
            editor.connect("changed", self.editor_changed)
            self.editors["browser"] = editor

        self.pack_start(self.tabs)
        self.tabs.show()

        self.label = self.text_label = None
        self.make_label()
        self.modified = (tempname is not None)
        if tempname:
            self.filename = tempname
        self.tooltip_filename = None
        self.update_tab()

    def make_label(self):
        self.label = gtk.HBox(False, 0)

        self.text_label = gtk.Label("")
        self.text_label.show()
        self.label.pack_start(self.text_label, 1, 1, 1)

        button = gtk.Button()
        button.set_relief(gtk.RELIEF_NONE)
        button.set_focus_on_click(False)

        icon = gtk.image_new_from_stock(gtk.STOCK_CLOSE, gtk.ICON_SIZE_MENU)
        icon.show()
        button.add(icon)

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
        if self.filename != self.tooltip_filename:
            self.text_label.set_tooltip_text(self.filename)
            self.tooltip_filename = self.filename

    def save(self, fname=None):
        if not fname:
            fname = self.filename
            if not os.path.exists(self.filename):
                return  # Probably before the first "Save as"
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

    def dstar_changed(self, dstared, memedit):
        memedit.set_urcall_list(dstared.editor_ucall.get_callsigns())
        memedit.set_repeater_list(dstared.editor_rcall.get_callsigns())
        memedit.prefill()

    def editor_changed(self, target_editor=None):
        LOG.debug("%s changed" % target_editor)
        if not isinstance(self.radio, chirp_common.LiveRadio):
            self.modified = True
            self.update_tab()
        for editor in self.editors.values():
            if editor != target_editor:
                editor.other_editor_changed(target_editor)

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

        dst_rthread._qlock_when_idle(5)  # Suspend job submission when idle

        dialog = dlgclass(src_radio, dst_rthread.radio, self.parent_window)
        r = dialog.run()
        dialog.hide()
        if r != gtk.RESPONSE_OK:
            dst_rthread._qunlock()
            return

        count = dialog.do_import(dst_rthread)
        LOG.debug("Imported %i" % count)
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
        text = _("The {vendor} {model} has multiple independent sub-devices")
        d.label.set_text(text.format(vendor=radio.VENDOR, model=radio.MODEL) +
                         os.linesep + _("Choose one to import from:"))
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
        for k, v in self.editors.items():
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
        tabs = self.tabs
        for lab, e in self.editors.items():
            if e and tabs.page_num(e.root) == tabs.get_current_page():
                return e
        raise Exception("No editor selected?")

    @property
    def rthread(self):
        """Magic rthread property to return the rthread of the currently-
        selected editor"""
        e = self.get_current_editor()
        return e.rthread
