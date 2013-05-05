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

from chirp import chirp_common, settings
from chirpui import common, miscwidgets

class RadioSettingProxy(settings.RadioSetting):
    def __init__(self, setting, editor):
        self._setting = setting
        self._editor = editor

class SettingsEditor(common.Editor):
    def __init__(self, rthread):
        super(SettingsEditor, self).__init__(rthread)
        self._changed = False
        self.root = gtk.HBox(False, 10)
        self._store = gtk.TreeStore(gobject.TYPE_STRING,
                                    gobject.TYPE_PYOBJECT)
        self._view = gtk.TreeView(self._store)
        self._view.set_size_request(150, -1)
        self._view.connect("button-press-event", self._group_selected)
        self._view.show()
        self.root.pack_start(self._view, 0, 0, 0)

        col = gtk.TreeViewColumn("", gtk.CellRendererText(), text=0)
        self._view.append_column(col)

        self._table = gtk.Table(20, 3)
        self._table.set_col_spacings(10)
        self._table.show()

        sw = gtk.ScrolledWindow()
        sw.add_with_viewport(self._table)
        sw.show()

        self.root.pack_start(sw, 1, 1, 1)

        self._index = 0

        self._top_setting_group = None

        job = common.RadioJob(self._build_ui, "get_settings")
        job.set_desc("Getting radio settings")
        self.rthread.submit(job)

    def _save_settings(self):
        if self._top_setting_group is None:
            return

        def setting_cb(result):
            if isinstance(result, Exception):
                common.show_error(_("Error in setting value: %s") % result)
            elif self._changed:
                self.emit("changed")
                self._changed = False

        job = common.RadioJob(setting_cb, "set_settings",
                              self._top_setting_group)
        job.set_desc("Setting radio settings")
        self.rthread.submit(job)

    def _load_setting(self, value, widget):
        if isinstance(value, settings.RadioSettingValueInteger):
            adj = widget.get_adjustment()
            adj.configure(value.get_value(),
                          value.get_min(), value.get_max(),
                          value.get_step(), 1, 0)
        elif isinstance(value, settings.RadioSettingValueFloat):
            widget.set_text(value.format())
        elif isinstance(value, settings.RadioSettingValueBoolean):
            widget.set_active(value.get_value())
        elif isinstance(value, settings.RadioSettingValueList):
            model = widget.get_model()
            model.clear()
            for option in value.get_options():
                widget.append_text(option)
            current = value.get_value()
            index = value.get_options().index(current)
            widget.set_active(index)
        elif isinstance(value, settings.RadioSettingValueString):
            widget.set_text(str(value).rstrip())
        else:
            print "Unsupported widget type %s for %s" % (value.__class__,
                                                         element.get_name())
            
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
            print "Unsupported widget type %s for %s" % (\
                element.value.__class__,
                element.get_name())

        self._changed = True
        self._save_settings()

    def _save_setting(self, widget, value):
        try:
            self._do_save_setting(widget, value)
        except settings.InvalidValueError, e:
            common.show_error(_("Invalid setting value: %s") % e)

    def _build_ui_group(self, group):
        def pack(widget, pos):
            self._table.attach(widget, pos, pos+1, self._index, self._index+1,
                               xoptions=gtk.FILL, yoptions=0)

        def abandon(child):
            self._table.remove(child)
        self._table.foreach(abandon)

        self._index = 0
        for element in group:
            if not isinstance(element, settings.RadioSetting):
                continue
            label = gtk.Label(element.get_shortname())
            label.set_alignment(1.0, 0.5)
            label.show()
            pack(label, 0)

            if isinstance(element.value, list) and \
                    isinstance(element.value[0],
                               settings.RadioSettingValueInteger):
                arraybox = gtk.HBox(3, True)
            else:
                arraybox = gtk.VBox(3, True)
            pack(arraybox, 1)
            arraybox.show()

            widgets = []
            for index in element.keys():
                value = element[index]
                if isinstance(value, settings.RadioSettingValueInteger):
                    widget = gtk.SpinButton()
                    print "Digits: %i" % widget.get_digits()
                    signal = "value-changed"
                elif isinstance(value, settings.RadioSettingValueFloat):
                    widget = gtk.Entry()
                    signal = "focus-out-event"
                elif isinstance(value, settings.RadioSettingValueBoolean):
                    widget = gtk.CheckButton(_("Enabled"))
                    signal = "toggled"
                elif isinstance(value, settings.RadioSettingValueList):
                    widget = miscwidgets.make_choice([], editable=False)
                    signal = "changed"
                elif isinstance(value, settings.RadioSettingValueString):
                    widget = gtk.Entry()
                    signal = "changed"
                else:
                    print "Unsupported widget type: %s" % value.__class__

                # Make sure the widget gets left-aligned to match up
                # with its label
                lalign = gtk.Alignment(0, 0, 0, 0)
                lalign.add(widget)
                lalign.show()

                widget.set_sensitive(value.get_mutable())

                arraybox.pack_start(lalign, 1, 1, 1)
                widget.show()
                self._load_setting(value, widget)
                if signal == "focus-out-event":
                    widget.connect(signal, lambda w, e, v:
                                       self._save_setting(w, v), value)
                else:
                    widget.connect(signal, self._save_setting, value)

            self._index += 1

    def _build_tree(self, group, parent):
        iter = self._store.append(parent)
        self._store.set(iter, 0, group.get_shortname(), 1, group)
        
        if self._set_default is None:
            # If we haven't found the first page with actual settings on it
            # yet, then look for one here
            for element in group:
                if isinstance(element, settings.RadioSetting):
                    self._set_default = self._store.get_path(iter), group
                    break

        for element in group:
            if not isinstance(element, settings.RadioSetting):
                self._build_tree(element, iter)
        self._view.expand_all()

    def _build_ui_real(self, group):
        if not isinstance(group, settings.RadioSettingGroup):
            print "Toplevel is not a group"
            return

        self._set_default = None
        self._top_setting_group = group
        self._build_tree(group, None)
        self._view.set_cursor(self._set_default[0])
        self._build_ui_group(self._set_default[1])

    def _build_ui(self, group):
        gobject.idle_add(self._build_ui_real, group)

    def _group_selected(self, view, event):
        if event.button != 1:
            return

        try:
            path, col, x, y = view.get_path_at_pos(int(event.x), int(event.y))
        except TypeError:
            return # Didn't click on an actual item

        group, = self._store.get(self._store.get_iter(path), 1)
        if group:
            self._build_ui_group(group)
