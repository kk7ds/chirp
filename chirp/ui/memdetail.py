# Copyright 2012 Dan Smith <dsmith@danplanet.com>
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

import gtk
import os
import logging

from chirp import chirp_common, settings
from chirp.ui import miscwidgets, common
from chirp.ui import compat

LOG = logging.getLogger(__name__)

POL = ["NN", "NR", "RN", "RR"]


class ValueEditor:
    """Base class"""
    def __init__(self, features, memory, errfn, name, data=None):
        self._features = features
        self._memory = memory
        self._errfn = errfn
        self._name = name
        self._widget = None
        self._init(data)

    def _init(self, data):
        """Type-specific initialization"""

    def set_sensitive(self, sensitive):
        self._widget.set_sensitive(sensitive)

    def get_widget(self):
        """Returns the widget associated with this editor"""
        return self._widget

    def _mem_value(self):
        """Returns the raw value from the memory associated with this name"""
        if self._name.startswith("extra_"):
            return self._memory.extra[self._name.split("_", 1)[1]].value
        else:
            return getattr(self._memory, self._name)

    def _get_value(self):
        """Returns the value from the widget that
        should be set in the memory"""

    def update(self):
        """Updates the memory object with self._getvalue()"""

        try:
            newval = self._get_value()
        except ValueError as e:
            self._errfn(self._name, str(e))
            return str(e)

        if self._name.startswith("extra_"):
            try:
                self._memory.extra[self._name.split("_", 1)[1]].value = newval
            except settings.InternalError as e:
                self._errfn(self._name, str(e))
                return str(e)
        else:
            try:
                setattr(self._memory, self._name, newval)
            except chirp_common.ImmutableValueError as e:
                if getattr(self._memory, self._name) != self._get_value():
                    self._errfn(self._name, str(e))
                    return str(e)
            except ValueError as e:
                self._errfn(self._name, str(e))
                return str(e)

        all_msgs = self._features.validate_memory(self._memory)
        errs = []
        for msg in all_msgs:
            if isinstance(msg, chirp_common.ValidationError):
                errs.append(str(msg))
        if errs:
            self._errfn(self._name, errs)
        else:
            self._errfn(self._name, None)


class StringEditor(ValueEditor):
    def _init(self, data):
        try:
            self._widget = gtk.Entry(int(data))
        except TypeError:
            self._widget = gtk.Entry()
            self._widget.set_max_length(int(data))
        self._widget.set_text(str(self._mem_value()))
        self._widget.connect("changed", self.changed)

    def _get_value(self):
        return self._widget.get_text()

    def changed(self, _widget):
        self.update()


class ChoiceEditor(ValueEditor):
    def _init(self, data):
        self._choice = miscwidgets.make_choice([str(x) for x in data],
                                               False,
                                               str(self._mem_value()))
        self._widget = self._choice.widget

        self._widget.connect("changed", self.changed)

    def _get_value(self):
        return self._choice.value

    def changed(self, _widget):
        self.update()


class PowerChoiceEditor(ChoiceEditor):
    def _init(self, data):
        self._choices = data
        ChoiceEditor._init(self, data)

    def _get_value(self):
        choice = self._widget.get_active_text()
        for level in self._choices:
            if str(level) == choice:
                return level
        raise Exception("Internal error: power level went missing")


class IntChoiceEditor(ChoiceEditor):
    def _get_value(self):
        return int(self._widget.get_active_text())


class FloatChoiceEditor(ChoiceEditor):
    def _get_value(self):
        return float(self._widget.get_active_text())


class FreqEditor(StringEditor):
    def _init(self, data):
        StringEditor._init(self, 0)

    def _mem_value(self):
        return chirp_common.format_freq(StringEditor._mem_value(self))

    def _get_value(self):
        return chirp_common.parse_freq(self._widget.get_text())


class BooleanEditor(ValueEditor):
    def _init(self, data):
        self._widget = gtk.CheckButton("Enabled")
        self._widget.set_active(self._mem_value())
        self._widget.connect("toggled", self.toggled)

    def _get_value(self):
        return self._widget.get_active()

    def toggled(self, _widget):
        self.update()


class OffsetEditor(FreqEditor):
    pass


class MemoryDetailEditor(gtk.Dialog):
    """Detail editor for a memory"""

    def _add(self, tab, row, name, editor, text, colindex=0):
        label = gtk.Label(text + ":")
        label.set_alignment(0.0, 0.5)
        label.show()
        tab.attach(label, colindex, colindex + 1, row, row + 1,
                   xoptions=gtk.FILL, yoptions=0, xpadding=6, ypadding=3)

        widget = editor.get_widget()
        widget.show()
        tab.attach(widget, colindex + 1, colindex + 2, row, row + 1,
                   xoptions=gtk.FILL, yoptions=0, xpadding=3, ypadding=3)

        img = gtk.Image()
        img.set_size_request(16, -1)
        img.show()
        tab.attach(img, colindex + 2, colindex + 3, row, row + 1,
                   xoptions=gtk.FILL, yoptions=0, xpadding=3, ypadding=3)

        self._editors[name] = label, editor, img
        return label, editor, img

    def _set_doc(self, name, doc):
        label, editor, _img = self._editors[name]
        self._tips.set_tip(label, doc)

    def _make_ui(self):

        box = gtk.VBox()
        box.show()

        notebook = gtk.Notebook()
        notebook.set_show_border(False)
        notebook.show()

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        sw.show()

        hbox = gtk.HBox()
        hbox.pack_start(sw, 1, 1, 1)
        hbox.show()

        tab = notebook.append_page(hbox, gtk.Label(_("General")))

        table = gtk.Table(len(self._order), 4, False)
        table.set_resize_mode(gtk.RESIZE_IMMEDIATE)
        table.show()
        sw.add_with_viewport(table)

        def _err(name, msg):
            try:
                _img = self._editors[name][2]
            except KeyError:
                LOG.error(self._editors.keys())
            if msg is None:
                _img.clear()
                self._tips.set_tip(_img, "")
            else:
                _img.set_from_stock(gtk.STOCK_DIALOG_WARNING,
                                    gtk.ICON_SIZE_MENU)
                self._tips.set_tip(_img, str(msg))
            self._errors[self._order.index(name)] = msg is not None
            self.set_response_sensitive(gtk.RESPONSE_OK,
                                        True not in self._errors)

        row = 0
        for name in self._order:
            text, editorcls, data = self._elements[name]
            editor = editorcls(self._features, self._memory,
                               _err, name, data)

            self._add(table, row, name, editor, text)
            self._set_doc(name, text)
            row += 1

        if len(self._memory.extra):
            sw = gtk.ScrolledWindow()
            sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
            sw.show()

            hbox = gtk.HBox()
            hbox.pack_start(sw, 1, 1, 1)
            hbox.show()

            tab = notebook.append_page(hbox, gtk.Label(_("Other")))

            table = gtk.Table(len(self._memory.extra), 4, False)
            table.set_resize_mode(gtk.RESIZE_IMMEDIATE)
            table.show()
            sw.add_with_viewport(table)

            for setting in self._memory.extra:
                name = "extra_%s" % setting.get_name()
                if isinstance(setting.value,
                              settings.RadioSettingValueBoolean):
                    editor = BooleanEditor(self._features, self._memory,
                                           _err, name)
                    self._add(table, row, name, editor,
                              setting.get_shortname())
                    self._set_doc(name, setting.__doc__)
                elif isinstance(setting.value,
                                settings.RadioSettingValueList):
                    editor = ChoiceEditor(self._features, self._memory, _err,
                                          name, setting.value.get_options())
                    self._add(table, row, name, editor,
                              setting.get_shortname())
                    self._set_doc(name, setting.__doc__)
                row += 1
                self._order.append(name)

        self.vbox.pack_start(notebook, 1, 1, 1)

    def __init__(self, features, memory, parent=None):
        self._memory = memory
        gtk.Dialog.__init__(self,
                            title="Memory Properties",
                            flags=gtk.DIALOG_MODAL,
                            parent=parent,
                            buttons=(gtk.STOCK_OK, gtk.RESPONSE_OK,
                                     gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
        self.set_size_request(-1, 500)
        self._tips = compat.CompatTooltips()

        self._features = features

        self._editors = {}
        self._elements = {
            "freq":          (_("Frequency"),
                              FreqEditor, None),
            "name":          (_("Name"),
                              StringEditor, features.valid_name_length),
            "tmode":         (_("Tone Mode"),
                              ChoiceEditor, features.valid_tmodes),
            "rtone":         (_("Tone"),
                              FloatChoiceEditor, chirp_common.TONES),
            "ctone":         (_("ToneSql"),
                              FloatChoiceEditor, chirp_common.TONES),
            "dtcs":          (_("DTCS Code"),
                              IntChoiceEditor, chirp_common.DTCS_CODES),
            "rx_dtcs":       (_("RX DTCS Code"),
                              IntChoiceEditor, chirp_common.DTCS_CODES),
            "dtcs_polarity": (_("DTCS Pol"),
                              ChoiceEditor, POL),
            "cross_mode":    (_("Cross mode"),
                              ChoiceEditor, features.valid_cross_modes),
            "duplex":        (_("Duplex"),
                              ChoiceEditor, features.valid_duplexes),
            "offset":        (_("Offset"),
                              OffsetEditor, None),
            "mode":          (_("Mode"),
                              ChoiceEditor, features.valid_modes),
            "tuning_step":   (_("Tune Step"),
                              FloatChoiceEditor, features.valid_tuning_steps),
            "skip":          (_("Skip"),
                              ChoiceEditor, features.valid_skips),
            "power":         (_("Power"),
                              PowerChoiceEditor, features.valid_power_levels),
            "comment":       (_("Comment"),
                              StringEditor, 256),
        }

        self._order = [
            "freq", "name", "tmode", "rtone", "ctone",  "cross_mode",
            "dtcs", "rx_dtcs", "dtcs_polarity", "duplex", "offset",
            "mode", "tuning_step", "skip", "power", "comment"
        ]

        hide_rules = [
            ("name", features.has_name),
            ("tmode", len(features.valid_tmodes) > 0),
            ("ctone", features.has_ctone),
            ("dtcs", features.has_dtcs),
            ("rx_dtcs", features.has_rx_dtcs),
            ("dtcs_polarity", features.has_dtcs_polarity),
            ("cross_mode", "Cross" in features.valid_tmodes),
            ("duplex", len(features.valid_duplexes) > 0),
            ("offset", features.has_offset),
            ("mode", len(features.valid_modes) > 0),
            ("tuning_step", features.has_tuning_step),
            ("skip", len(features.valid_skips) > 0),
            ("power", features.valid_power_levels),
            ("comment", features.has_comment),
        ]

        for name, visible in hide_rules:
            if not visible:
                del self._elements[name]
                self._order.remove(name)

        self._make_ui()

        self._errors = [False] * len(self._order)

        self.connect("response", self._validate)

    def _validate(self, _dialog, response):
        if response == gtk.RESPONSE_OK:
            all_msgs = self._features.validate_memory(self._memory)
            errors = []
            for msg in all_msgs:
                if isinstance(msg, chirp_common.ValidationError):
                    errors.append(msg)
            if errors:
                common.show_error_text(_("Memory validation failed:"),
                                       os.linesep +
                                       os.linesep.join(errors))
                self.emit_stop_by_name('response')

    def get_memory(self):
        self._memory.empty = False
        return self._memory


class MultiMemoryDetailEditor(MemoryDetailEditor):

    def __init__(self, features, memory, parent=None):
        self._selections = dict()
        super(MultiMemoryDetailEditor, self).__init__(features, memory, parent)

    def _toggle_selector(self, selector, *widgets):
        for widget in widgets:
            widget.set_sensitive(selector.get_active())

    def _add(self, tab, row, name, editor, text):

        label, editor, img = super(MultiMemoryDetailEditor, self)._add(
            tab, row, name, editor, text, 1)

        selector = gtk.CheckButton()
        tab.attach(selector, 0, 1, row, row + 1,
                   xoptions=gtk.FILL, yoptions=0, xpadding=0, ypadding=3)
        selector.show()
        self._toggle_selector(selector, label, editor, img)
        selector.connect("toggled", self._toggle_selector, label, editor, img)
        self._selections[name] = selector

    def get_fields(self):
        return [k for k, v in self._selections.items() if v.get_active()]
