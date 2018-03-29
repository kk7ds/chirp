# Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import gtk
import gobject
import logging

from chirp import chirp_common
from chirp import settings
from chirp.ui import common, miscwidgets

LOG = logging.getLogger(__name__)


class RadioSettingProxy(settings.RadioSetting):

    def __init__(self, setting, editor):
        self._setting = setting
        self._editor = editor


class SettingsEditor(common.Editor):

    def __init__(self, rthread):
        super(SettingsEditor, self).__init__(rthread)

        # The main box
        self.root = gtk.HBox(False, 0)

        # The pane
        paned = gtk.HPaned()
        paned.show()
        self.root.pack_start(paned, 1, 1, 0)

        # The selection tree
        self._store = gtk.TreeStore(gobject.TYPE_STRING, gobject.TYPE_INT)
        self._view = gtk.TreeView(self._store)
        self._view.get_selection().connect("changed", self._view_changed_cb)
        self._view.append_column(
            gtk.TreeViewColumn("", gtk.CellRendererText(), text=0))
        self._view.show()
        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        scrolled_window.add_with_viewport(self._view)
        scrolled_window.set_size_request(200, -1)
        scrolled_window.show()
        paned.pack1(scrolled_window)

        # The settings notebook
        self._notebook = gtk.Notebook()
        self._notebook.set_show_tabs(False)
        self._notebook.set_show_border(False)
        self._notebook.show()
        paned.pack2(self._notebook)

        self._changed = False
        self._settings = None

        job = common.RadioJob(self._get_settings_cb, "get_settings")
        job.set_desc("Getting radio settings")
        self.rthread.submit(job)

    def _save_settings(self):
        if self._settings is None:
            return

        def setting_cb(result):
            if isinstance(result, Exception):
                common.show_error(_("Error in setting value: %s") % result)
            elif self._changed:
                self.emit("changed")
                self._changed = False

        job = common.RadioJob(setting_cb, "set_settings",
                              self._settings)
        job.set_desc("Setting radio settings")
        self.rthread.submit(job)

    def _do_save_setting(self, widget, value):
        if isinstance(value, settings.RadioSettingValueInteger):
            value.set_value(widget.get_adjustment().get_value())
        elif isinstance(value, settings.RadioSettingValueFloat):
            value.set_value(widget.get_text())
        elif isinstance(value, settings.RadioSettingValueBoolean):
            value.set_value(widget.get_active())
        elif isinstance(value, settings.RadioSettingValueList):
            value.set_value(widget.get_active_text())
        elif isinstance(value, settings.RadioSettingValueString):
            value.set_value(widget.get_text())
        else:
            LOG.error("Unsupported widget type %s for %s" %
                      (element.value.__class__, element.get_name()))

        self._changed = True
        self._save_settings()

    def _save_setting(self, widget, value):
        try:
            self._do_save_setting(widget, value)
        except settings.InvalidValueError, e:
            common.show_error(_("Invalid setting value: %s") % e)

    def _build_ui_tab(self, group):

        # The scrolled window
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.show()

        # Notebook tab
        tab = self._notebook.append_page(sw, gtk.Label(_(group.get_name())))

        # Settings table
        table = gtk.Table(len(group), 2, False)
        table.set_resize_mode(gtk.RESIZE_IMMEDIATE)
        table.show()
        sw.add_with_viewport(table)

        row = 0
        for element in group:
            if not isinstance(element, settings.RadioSetting):
                continue

            # Label
            label = gtk.Label(element.get_shortname() + ":")
            label.set_alignment(0.0, 0.5)
            label.show()

            table.attach(label, 0, 1, row, row + 1,
                         xoptions=gtk.FILL, yoptions=0,
                         xpadding=6, ypadding=3)

            if isinstance(element.value, list) and \
                    isinstance(element.value[0],
                               settings.RadioSettingValueInteger):
                box = gtk.HBox(True)
            else:
                box = gtk.VBox(True)

            # Widget container
            box.show()
            table.attach(box, 1, 2, row, row + 1,
                         xoptions=gtk.FILL, yoptions=0,
                         xpadding=12, ypadding=3)

            for i in element.keys():
                value = element[i]
                if isinstance(value, settings.RadioSettingValueInteger):
                    widget = gtk.SpinButton()
                    adj = widget.get_adjustment()
                    adj.configure(value.get_value(),
                                  value.get_min(), value.get_max(),
                                  value.get_step(), 1, 0)
                    widget.connect("value-changed", self._save_setting, value)
                elif isinstance(value, settings.RadioSettingValueFloat):
                    widget = gtk.Entry()
                    widget.set_width_chars(16)
                    widget.set_text(value.format())
                    widget.connect("focus-out-event", lambda w, e, v:
                                   self._save_setting(w, v), value)
                elif isinstance(value, settings.RadioSettingValueBoolean):
                    widget = gtk.CheckButton(_("Enabled"))
                    widget.set_active(value.get_value())
                    widget.connect("toggled", self._save_setting, value)
                elif isinstance(value, settings.RadioSettingValueList):
                    widget = miscwidgets.make_choice([], editable=False)
                    model = widget.get_model()
                    model.clear()
                    for option in value.get_options():
                        widget.append_text(option)
                    current = value.get_value()
                    index = value.get_options().index(current)
                    widget.set_active(index)
                    widget.connect("changed", self._save_setting, value)
                elif isinstance(value, settings.RadioSettingValueString):
                    widget = gtk.Entry()
                    widget.set_width_chars(32)
                    widget.set_text(str(value).rstrip())
                    widget.connect("focus-out-event", lambda w, e, v:
                                   self._save_setting(w, v), value)
                else:
                    LOG.error("Unsupported widget type: %s" % value.__class__)

                widget.set_sensitive(value.get_mutable())
                label.set_mnemonic_widget(widget)
                widget.get_accessible().set_name(element.get_shortname())
                widget.show()

                box.pack_start(widget, 1, 1, 1)

            row += 1

        return tab

    def _build_ui_group(self, group, parent):
        tab = self._build_ui_tab(group)

        iter = self._store.append(parent)
        self._store.set(iter, 0, group.get_shortname(), 1, tab)

        for element in group:
            if not isinstance(element, settings.RadioSetting):
                self._build_ui_group(element, iter)

    def _build_ui(self, settings):
        if not isinstance(settings, list):
            raise Exception("Invalid Radio Settings")
            return

        self._settings = settings
        for group in settings:
            self._build_ui_group(group, None)
        self._view.expand_all()

    def _get_settings_cb(self, settings):
        gobject.idle_add(self._build_ui, settings)

    def _view_changed_cb(self, selection):
        (lst, iter) = selection.get_selected()
        tab, = self._store.get(iter, 1)
        self._notebook.set_current_page(tab)
