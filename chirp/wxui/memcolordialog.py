# Copyright 2026
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

"""The memory color-coding customization dialog.

Edits happen against an in-memory working copy of the ColorProfile;
nothing is persisted (chirp.wxui.memcolors.ColorCodingController.save())
until Apply or OK is pressed, so Cancel always leaves prior settings
untouched. Apply pushes the working copy to the controller (which
notifies every open memory-edit grid) without closing the dialog.
"""

import copy
import logging

import wx

from chirp.memcolors import categories
from chirp.memcolors import contrast
from chirp.memcolors import profile as profile_mod
from chirp.memcolors import rules as rules_mod
from chirp.wxui import common

_ = wx.GetTranslation
LOG = logging.getLogger(__name__)

_SWATCH_SIZE = (16, 16)

_REGULATORY_NOTE = _(
    'These categories are a visual convenience aid, not a legal or '
    'regulatory determination. Frequency allocations vary by country, '
    'license class, and local band plan, and change over time. You '
    'remain responsible for verifying your own frequencies and '
    'operating privileges.')


def _make_swatch_bitmap(bg_hex, size=_SWATCH_SIZE):
    bmp = wx.Bitmap(*size)
    dc = wx.MemoryDC(bmp)
    try:
        dc.SetBackground(wx.Brush(wx.Colour(bg_hex)))
        dc.Clear()
    except Exception:
        dc.SetBackground(wx.Brush(wx.Colour('#FF00FF')))
        dc.Clear()
    finally:
        dc.SelectObject(wx.NullBitmap)
    return bmp


class _CategoryPanel(wx.Panel):
    """Editor for the currently-selected built-in category."""

    def __init__(self, parent, on_change):
        super().__init__(parent)
        self._on_change = on_change
        self._category_id = None
        self._suspend = False

        grid = wx.FlexGridSizer(cols=2, gap=(8, 6))
        grid.AddGrowableCol(1)

        self._desc = wx.StaticText(self, label='')
        self._desc.Wrap(360)

        self._enabled_chk = wx.CheckBox(self, label=_('Enabled'))
        self._enabled_chk.Bind(wx.EVT_CHECKBOX, self._changed)

        self._bold_chk = wx.CheckBox(self, label=_('Bold text'))
        self._bold_chk.Bind(wx.EVT_CHECKBOX, self._changed)

        self._bg_picker = wx.ColourPickerCtrl(self)
        self._bg_picker.Bind(wx.EVT_COLOURPICKER_CHANGED, self._changed)

        self._fg_picker = wx.ColourPickerCtrl(self)
        self._fg_picker.Bind(wx.EVT_COLOURPICKER_CHANGED, self._changed)

        self._priority_spin = wx.SpinCtrl(self, min=0, max=100)
        self._priority_spin.Bind(wx.EVT_SPINCTRL, self._changed)

        self._contrast_label = wx.StaticText(self, label='')

        self._sample = wx.Panel(self, size=(220, 30))
        self._sample.SetMinSize((220, 30))
        self._sample_text = wx.StaticText(self._sample,
                                          label=_('Sample Memory Text'))
        sbox = wx.BoxSizer(wx.VERTICAL)
        sbox.AddStretchSpacer()
        sbox.Add(self._sample_text, 0, wx.ALIGN_CENTER | wx.ALL, 4)
        sbox.AddStretchSpacer()
        self._sample.SetSizer(sbox)

        reset_btn = wx.Button(self, label=_('Reset This Category'))
        reset_btn.Bind(wx.EVT_BUTTON, self._on_reset)

        grid.Add(self._desc, 0, wx.EXPAND)
        grid.Add(wx.StaticText(self), 0)
        grid.Add(wx.StaticText(self, label=_('Enabled:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._enabled_chk, 0)
        grid.Add(wx.StaticText(self, label=_('Background:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._bg_picker, 0)
        grid.Add(wx.StaticText(self, label=_('Text color:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._fg_picker, 0)
        grid.Add(wx.StaticText(self, label=_('Bold:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._bold_chk, 0)
        grid.Add(wx.StaticText(self, label=_('Legend priority:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._priority_spin, 0)
        grid.Add(wx.StaticText(self, label=_('Contrast:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._contrast_label, 0)
        grid.Add(wx.StaticText(self, label=_('Sample:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._sample, 0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        vbox.Add(reset_btn, 0, wx.LEFT | wx.BOTTOM, 10)
        self.SetSizer(vbox)
        self.Disable()

    def load(self, category_id, state, description):
        self._suspend = True
        self._category_id = category_id
        self._desc.SetLabel(description)
        self._enabled_chk.SetValue(state.enabled)
        self._bold_chk.SetValue(state.bold)
        self._bg_picker.SetColour(wx.Colour(state.bg))
        self._fg_picker.SetColour(wx.Colour(state.fg))
        self._priority_spin.SetValue(state.priority)
        self._suspend = False
        self.Enable()
        self._refresh_sample()

    def _refresh_sample(self):
        bg = self._bg_picker.GetColour()
        fg = self._fg_picker.GetColour()
        self._sample.SetBackgroundColour(bg)
        self._sample_text.SetForegroundColour(fg)
        font = self._sample_text.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD if self._bold_chk.GetValue()
                       else wx.FONTWEIGHT_NORMAL)
        self._sample_text.SetFont(font)
        self._sample.Refresh()
        ratio = contrast.contrast_ratio(fg.GetAsString(wx.C2S_HTML_SYNTAX),
                                        bg.GetAsString(wx.C2S_HTML_SYNTAX))
        ok = ratio >= 4.5
        self._contrast_label.SetLabel(
            ('%.1f:1 ' % ratio) +
            (_('(meets WCAG AA)') if ok else _('(LOW CONTRAST)')))
        self._contrast_label.SetForegroundColour(
            wx.NullColour if ok else wx.Colour('#B71C1C'))

    def current_state(self):
        return profile_mod.CategoryState(
            bg=self._bg_picker.GetColour().GetAsString(wx.C2S_HTML_SYNTAX),
            fg=self._fg_picker.GetColour().GetAsString(wx.C2S_HTML_SYNTAX),
            enabled=self._enabled_chk.GetValue(),
            bold=self._bold_chk.GetValue(),
            priority=self._priority_spin.GetValue())

    def _changed(self, event):
        self._refresh_sample()
        if not self._suspend and self._category_id:
            self._on_change(self._category_id, self.current_state())

    def _on_reset(self, event):
        if not self._category_id:
            return
        builtin = categories.default_category(self._category_id)
        self.load(self._category_id,
                  profile_mod.CategoryState.from_category(builtin),
                  self._desc.GetLabel())
        self._on_change(self._category_id, self.current_state(),
                        reset=True)


class _CategoriesPage(wx.Panel):
    def __init__(self, parent, dialog):
        super().__init__(parent)
        self._dialog = dialog

        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, '')
        self._list.InsertColumn(1, _('Category'))
        self._list.InsertColumn(2, _('Enabled'))
        self._image_list = wx.ImageList(*_SWATCH_SIZE)
        self._list.AssignImageList(self._image_list, wx.IMAGE_LIST_SMALL)
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)

        self._editor = _CategoryPanel(self, self._on_category_changed)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self._list, 1, wx.EXPAND | wx.ALL, 5)
        hbox.Add(self._editor, 0, wx.EXPAND | wx.ALL, 5)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(hbox, 1, wx.EXPAND)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        reset_all = wx.Button(self, label=_('Reset All Colors to Defaults'))
        reset_all.Bind(wx.EVT_BUTTON, self._on_reset_all)
        btn_row.Add(reset_all, 0, wx.ALL, 5)
        vbox.Add(btn_row, 0)

        note = wx.StaticText(self, label=_REGULATORY_NOTE)
        note.Wrap(600)
        vbox.Add(note, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(vbox)
        self.reload()

    def reload(self):
        self._list.DeleteAllItems()
        self._image_list.RemoveAll()
        working = self._dialog.working_profile
        for i, cat in enumerate(categories.DEFAULT_CATEGORIES):
            state = working.category_state(cat.id)
            img_idx = self._image_list.Add(_make_swatch_bitmap(state.bg))
            idx = self._list.InsertItem(i, '')
            self._list.SetItemImage(idx, img_idx)
            self._list.SetItem(idx, 1, _(cat.label))
            self._list.SetItem(idx, 2,
                               _('Yes') if state.enabled else _('No'))
            self._list.SetItemData(idx, i)
        self._list.SetColumnWidth(0, 28)
        self._list.SetColumnWidth(1, 220)
        self._list.SetColumnWidth(2, 70)

    def _on_select(self, event):
        i = self._list.GetItemData(event.GetIndex())
        cat = categories.DEFAULT_CATEGORIES[i]
        state = self._dialog.working_profile.category_state(cat.id)
        self._editor.load(cat.id, state, _(cat.description))

    def _on_category_changed(self, category_id, state, reset=False):
        self._dialog.working_profile.set_category_state(category_id, state)
        self._dialog.mark_dirty()
        self.reload()
        # Re-select the same row after the list rebuild.
        for i in range(self._list.GetItemCount()):
            if categories.DEFAULT_CATEGORIES[
                    self._list.GetItemData(i)].id == category_id:
                self._list.Select(i)
                break

    def _on_reset_all(self, event):
        if wx.MessageBox(
                _('Reset all built-in category colors to their defaults? '
                  'Custom rules are not affected.'),
                _('Reset All Colors'), wx.YES_NO | wx.ICON_QUESTION,
                self) != wx.YES:
            return
        self._dialog.working_profile.reset_all_categories()
        self._dialog.mark_dirty()
        self.reload()


class _RuleEditDialog(wx.Dialog):
    """Add/edit a single custom rule. One condition per row, ANDed."""

    _FIELD_CHOICES = (
        (rules_mod.FIELD_FREQ, _('Frequency (Hz)')),
        (rules_mod.FIELD_SERVICE, _('Service')),
        (rules_mod.FIELD_DUPLEX, _('Duplex')),
        (rules_mod.FIELD_OFFSET_DIRECTION, _('Offset direction')),
        (rules_mod.FIELD_MODE, _('Mode')),
        (rules_mod.FIELD_TONE_MODE, _('Tone mode')),
        (rules_mod.FIELD_NAME, _('Name')),
        (rules_mod.FIELD_COMMENT, _('Comment')),
        (rules_mod.FIELD_SKIP, _('Skip state')),
        (rules_mod.FIELD_RECEIVE_ONLY, _('Receive-only')),
        (rules_mod.FIELD_CLASSIFICATION, _('Built-in classification')),
    )
    _OP_CHOICES = (
        (rules_mod.OP_EQ, '='),
        (rules_mod.OP_NE, '!='),
        (rules_mod.OP_CONTAINS, _('contains')),
        (rules_mod.OP_STARTSWITH, _('starts with')),
        (rules_mod.OP_ENDSWITH, _('ends with')),
    )

    def __init__(self, parent, rule=None):
        super().__init__(parent, title=_('Custom Color Rule'),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((480, 420))

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        form = wx.FlexGridSizer(cols=2, gap=(8, 6))
        form.AddGrowableCol(1)

        self._name = wx.TextCtrl(self, value=rule.name if rule else '')
        form.Add(wx.StaticText(self, label=_('Name:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        form.Add(self._name, 1, wx.EXPAND)

        self._enabled = wx.CheckBox(self, label=_('Enabled'))
        self._enabled.SetValue(rule.enabled if rule else True)
        form.Add(wx.StaticText(self), 0)
        form.Add(self._enabled, 0)

        self._bg = wx.ColourPickerCtrl(self)
        self._bg.SetColour(wx.Colour(rule.bg if rule else '#FFF59D'))
        form.Add(wx.StaticText(self, label=_('Background:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        form.Add(self._bg, 0)

        self._fg = wx.ColourPickerCtrl(self)
        self._fg.SetColour(wx.Colour(rule.fg if rule else '#212121'))
        form.Add(wx.StaticText(self, label=_('Text color:')), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        form.Add(self._fg, 0)

        self._bold = wx.CheckBox(self, label=_('Bold'))
        self._bold.SetValue(rule.bold if rule else False)
        form.Add(wx.StaticText(self), 0)
        form.Add(self._bold, 0)

        vbox.Add(form, 0, wx.EXPAND | wx.ALL, 10)

        vbox.Add(wx.StaticText(self, label=_(
            'Match ALL of these conditions:')), 0, wx.LEFT, 10)

        self._cond_list = wx.ListCtrl(self, style=wx.LC_REPORT)
        self._cond_list.InsertColumn(0, _('Field'))
        self._cond_list.InsertColumn(1, _('Operator'))
        self._cond_list.InsertColumn(2, _('Value'))
        self._cond_list.SetColumnWidth(0, 150)
        self._cond_list.SetColumnWidth(1, 100)
        self._cond_list.SetColumnWidth(2, 150)
        vbox.Add(self._cond_list, 1, wx.EXPAND | wx.ALL, 10)

        self._conditions = list(rule.conditions) if rule else []
        self._refresh_conditions()

        cond_btns = wx.BoxSizer(wx.HORIZONTAL)
        add_cond = wx.Button(self, label=_('Add Condition...'))
        add_cond.Bind(wx.EVT_BUTTON, self._on_add_condition)
        del_cond = wx.Button(self, label=_('Remove Condition'))
        del_cond.Bind(wx.EVT_BUTTON, self._on_remove_condition)
        cond_btns.Add(add_cond, 0, wx.RIGHT, 5)
        cond_btns.Add(del_cond, 0)
        vbox.Add(cond_btns, 0, wx.LEFT | wx.BOTTOM, 10)

        vbox.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0,
                 wx.EXPAND | wx.ALL, 10)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.CenterOnParent()

    def _refresh_conditions(self):
        self._cond_list.DeleteAllItems()
        for i, cond in enumerate(self._conditions):
            idx = self._cond_list.InsertItem(i, cond.field)
            self._cond_list.SetItem(idx, 1, cond.op)
            self._cond_list.SetItem(idx, 2, str(cond.value))

    def _on_add_condition(self, event):
        field_labels = [label for _f, label in self._FIELD_CHOICES]
        d = wx.SingleChoiceDialog(self, _('Field to match:'),
                                  _('Add Condition'), field_labels)
        if d.ShowModal() != wx.ID_OK:
            d.Destroy()
            return
        field = self._FIELD_CHOICES[d.GetSelection()][0]
        d.Destroy()

        op_labels = [label for _o, label in self._OP_CHOICES]
        d2 = wx.SingleChoiceDialog(self, _('Operator:'), _('Add Condition'),
                                   op_labels)
        if d2.ShowModal() != wx.ID_OK:
            d2.Destroy()
            return
        op = self._OP_CHOICES[d2.GetSelection()][0]
        d2.Destroy()

        prompt = _('Value (integer Hz for Frequency):') \
            if field == rules_mod.FIELD_FREQ else _('Value:')
        d3 = wx.TextEntryDialog(self, prompt, _('Add Condition'))
        if d3.ShowModal() != wx.ID_OK:
            d3.Destroy()
            return
        raw = d3.GetValue()
        d3.Destroy()

        try:
            if field == rules_mod.FIELD_FREQ:
                value = int(raw)
            elif field == rules_mod.FIELD_RECEIVE_ONLY:
                value = raw.strip().lower() in ('1', 'true', 'yes')
            else:
                value = raw
            cond = rules_mod.Condition(field=field, op=op, value=value)
            cond.validate()
        except (ValueError, rules_mod.RuleValidationError) as e:
            common.error_proof.show_error(str(e))
            return

        self._conditions.append(cond)
        self._refresh_conditions()

    def _on_remove_condition(self, event):
        idx = self._cond_list.GetFirstSelected()
        if idx == -1:
            return
        del self._conditions[idx]
        self._refresh_conditions()

    def _on_ok(self, event):
        if not self._name.GetValue().strip():
            common.error_proof.show_error(_('Rule name is required'))
            return
        if not self._conditions:
            common.error_proof.show_error(
                _('Add at least one match condition'))
            return
        event.Skip()

    def get_rule(self, priority):
        return rules_mod.Rule(
            name=self._name.GetValue().strip(),
            enabled=self._enabled.GetValue(),
            priority=priority,
            conditions=tuple(self._conditions),
            bg=self._bg.GetColour().GetAsString(wx.C2S_HTML_SYNTAX),
            fg=self._fg.GetColour().GetAsString(wx.C2S_HTML_SYNTAX),
            bold=self._bold.GetValue())


class _RulesPage(wx.Panel):
    def __init__(self, parent, dialog):
        super().__init__(parent)
        self._dialog = dialog

        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, _('Name'))
        self._list.InsertColumn(1, _('Enabled'))
        self._list.InsertColumn(2, _('Conditions'))
        self._list.SetColumnWidth(0, 160)
        self._list.SetColumnWidth(1, 70)
        self._list.SetColumnWidth(2, 220)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._list, 1, wx.EXPAND | wx.ALL, 5)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
                (_('Add...'), self._on_add),
                (_('Edit...'), self._on_edit),
                (_('Duplicate'), self._on_duplicate),
                (_('Delete'), self._on_delete),
                (_('Move Up'), self._on_move_up),
                (_('Move Down'), self._on_move_down),
                (_('Test...'), self._on_test)):
            btn = wx.Button(self, label=label)
            btn.Bind(wx.EVT_BUTTON, handler)
            btns.Add(btn, 0, wx.RIGHT, 5)
        vbox.Add(btns, 0, wx.ALL, 5)
        self.SetSizer(vbox)
        self.reload()

    def reload(self):
        self._list.DeleteAllItems()
        ordered = sorted(self._dialog.working_profile.custom_rules,
                         key=lambda r: r.priority)
        for i, rule in enumerate(ordered):
            idx = self._list.InsertItem(i, rule.name)
            self._list.SetItem(idx, 1, _('Yes') if rule.enabled else _('No'))
            self._list.SetItem(idx, 2, '; '.join(
                '%s %s %r' % (c.field, c.op, c.value)
                for c in rule.conditions))

    def _selected_rule(self):
        idx = self._list.GetFirstSelected()
        if idx == -1:
            return None
        ordered = sorted(self._dialog.working_profile.custom_rules,
                         key=lambda r: r.priority)
        return ordered[idx]

    def _next_priority(self):
        existing = [r.priority for r in
                    self._dialog.working_profile.custom_rules]
        return (max(existing) + 1) if existing else 0

    def _on_add(self, event):
        d = _RuleEditDialog(self)
        if d.ShowModal() == wx.ID_OK:
            try:
                rule = d.get_rule(self._next_priority())
                self._dialog.working_profile.add_rule(rule)
                self._dialog.mark_dirty()
                self.reload()
            except rules_mod.RuleValidationError as e:
                common.error_proof.show_error(str(e))
        d.Destroy()

    def _on_edit(self, event):
        rule = self._selected_rule()
        if not rule:
            return
        d = _RuleEditDialog(self, rule)
        if d.ShowModal() == wx.ID_OK:
            try:
                new_rule = d.get_rule(rule.priority)
                self._dialog.working_profile.remove_rule(rule.name)
                self._dialog.working_profile.add_rule(new_rule)
                self._dialog.mark_dirty()
                self.reload()
            except rules_mod.RuleValidationError as e:
                common.error_proof.show_error(str(e))
        d.Destroy()

    def _on_duplicate(self, event):
        rule = self._selected_rule()
        if not rule:
            return
        base_name = '%s (copy)' % rule.name
        name = base_name
        n = 1
        existing_names = {r.name for r in
                          self._dialog.working_profile.custom_rules}
        while name in existing_names:
            n += 1
            name = '%s %i' % (base_name, n)
        dup = rules_mod.Rule(name=name, enabled=rule.enabled,
                             priority=self._next_priority(),
                             conditions=rule.conditions, bg=rule.bg,
                             fg=rule.fg, bold=rule.bold,
                             description=rule.description)
        self._dialog.working_profile.add_rule(dup)
        self._dialog.mark_dirty()
        self.reload()

    def _on_delete(self, event):
        rule = self._selected_rule()
        if not rule:
            return
        if wx.MessageBox(_('Delete rule "%s"?') % rule.name,
                         _('Delete Rule'), wx.YES_NO | wx.ICON_QUESTION,
                         self) != wx.YES:
            return
        self._dialog.working_profile.remove_rule(rule.name)
        self._dialog.mark_dirty()
        self.reload()

    def _on_move_up(self, event):
        rule = self._selected_rule()
        if rule:
            self._dialog.working_profile.move_rule(rule.name, -1)
            self._dialog.mark_dirty()
            self.reload()

    def _on_move_down(self, event):
        rule = self._selected_rule()
        if rule:
            self._dialog.working_profile.move_rule(rule.name, 1)
            self._dialog.mark_dirty()
            self.reload()

    def _on_test(self, event):
        rule = self._selected_rule()
        if not rule:
            return
        d = wx.TextEntryDialog(
            self, _('Enter a test frequency in Hz (used for any '
                    'frequency condition; other conditions are ignored '
                    'in this simple preview):'), _('Test Rule'), '146520000')
        if d.ShowModal() != wx.ID_OK:
            d.Destroy()
            return
        try:
            freq = int(d.GetValue())
        except ValueError:
            common.error_proof.show_error(_('Enter an integer frequency'))
            d.Destroy()
            return
        d.Destroy()

        context = {
            rules_mod.FIELD_FREQ: freq,
            rules_mod.FIELD_SERVICE: '',
            rules_mod.FIELD_DUPLEX: '',
            rules_mod.FIELD_OFFSET_DIRECTION: 'none',
            rules_mod.FIELD_MODE: 'FM',
            rules_mod.FIELD_TONE_MODE: '',
            rules_mod.FIELD_NAME: '',
            rules_mod.FIELD_COMMENT: '',
            rules_mod.FIELD_SKIP: '',
            rules_mod.FIELD_RECEIVE_ONLY: False,
            rules_mod.FIELD_CLASSIFICATION: '',
        }
        matched = rule.matches(context)
        wx.MessageBox(
            _('Rule matches: %s') % (_('YES') if matched else _('NO')),
            _('Test Rule'), wx.OK | wx.ICON_INFORMATION, self)


class _ColumnsPage(wx.Panel):
    def __init__(self, parent, dialog, available_columns):
        """@available_columns: [(name, label), ...] for the currently
        open editor. Columns configured previously but not present here
        (a different radio/tab) are preserved untouched on save."""
        super().__init__(parent)
        self._dialog = dialog
        self._available = available_columns

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(wx.StaticText(self, label=_(
            'When "Apply color only to selected columns" is enabled, '
            'color coding is limited to these columns:')), 0,
            wx.EXPAND | wx.ALL, 8)

        labels = [label for _n, label in available_columns]
        self._clb = wx.CheckListBox(self, choices=labels)
        selected = set(dialog.working_profile.selected_columns)
        for i, (name, label) in enumerate(available_columns):
            self._clb.Check(i, name in selected)
        self._clb.Bind(wx.EVT_CHECKLISTBOX, self._on_change)
        vbox.Add(self._clb, 1, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(vbox)

    def _on_change(self, event):
        visible_names = {name for name, _l in self._available}
        checked = {self._available[i][0]
                   for i in range(len(self._available))
                   if self._clb.IsChecked(i)}
        preserved = (set(self._dialog.working_profile.selected_columns) -
                     visible_names)
        self._dialog.working_profile.selected_columns = tuple(
            sorted(checked | preserved))
        self._dialog.mark_dirty()


class ChirpColorSettingsDialog(wx.Dialog):
    def __init__(self, parent, controller, available_columns=None):
        super().__init__(
            parent, title=_('Memory Color Coding'),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetSize((760, 620))
        self.SetMinSize((600, 480))

        self._controller = controller
        self.working_profile = copy.deepcopy(controller.profile)
        self._available_columns = available_columns or [
            (n, n) for n in profile_mod.DEFAULT_SELECTED_COLUMNS]

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        master = wx.StaticBoxSizer(wx.VERTICAL, self, _('Master Controls'))

        self._enable_chk = wx.CheckBox(
            self, label=_('Enable memory color coding'))
        self._enable_chk.SetValue(self.working_profile.enabled)
        self._enable_chk.Bind(wx.EVT_CHECKBOX, self._on_enable_changed)
        master.Add(self._enable_chk, 0, wx.ALL, 5)

        apply_row = wx.BoxSizer(wx.HORIZONTAL)
        self._apply_row_radio = wx.RadioButton(
            self, label=_('Apply color to entire row'), style=wx.RB_GROUP)
        self._apply_cols_radio = wx.RadioButton(
            self, label=_('Apply color only to selected columns'))
        if self.working_profile.apply_mode == profile_mod.APPLY_COLUMNS:
            self._apply_cols_radio.SetValue(True)
        else:
            self._apply_row_radio.SetValue(True)
        self._apply_row_radio.Bind(wx.EVT_RADIOBUTTON, self._on_apply_mode)
        self._apply_cols_radio.Bind(wx.EVT_RADIOBUTTON, self._on_apply_mode)
        apply_row.Add(self._apply_row_radio, 0, wx.RIGHT, 15)
        apply_row.Add(self._apply_cols_radio, 0)
        master.Add(apply_row, 0, wx.ALL, 5)

        self._legend_chk = wx.CheckBox(self, label=_('Show color legend'))
        self._legend_chk.SetValue(self.working_profile.show_legend)
        self._legend_chk.Bind(wx.EVT_CHECKBOX, self._on_legend_changed)
        master.Add(self._legend_chk, 0, wx.ALL, 5)

        self._invalid_chk = wx.CheckBox(
            self, label=_('Flag memories that fail radio validation'))
        self._invalid_chk.SetValue(self.working_profile.flag_invalid)
        self._invalid_chk.Bind(wx.EVT_CHECKBOX, self._on_invalid_changed)
        master.Add(self._invalid_chk, 0, wx.ALL, 5)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        default_btn = wx.Button(self, label=_('Use Default Color Profile'))
        default_btn.Bind(wx.EVT_BUTTON, self._on_use_default)
        export_btn = wx.Button(self, label=_('Export Color Profile...'))
        export_btn.Bind(wx.EVT_BUTTON, self._on_export)
        import_btn = wx.Button(self, label=_('Import Color Profile...'))
        import_btn.Bind(wx.EVT_BUTTON, self._on_import)
        for b in (default_btn, export_btn, import_btn):
            btn_row.Add(b, 0, wx.RIGHT, 8)
        master.Add(btn_row, 0, wx.ALL, 5)

        vbox.Add(master, 0, wx.EXPAND | wx.ALL, 10)

        self._notebook = wx.Notebook(self)
        self._categories_page = _CategoriesPage(self._notebook, self)
        self._rules_page = _RulesPage(self._notebook, self)
        self._columns_page = _ColumnsPage(self._notebook, self,
                                          self._available_columns)
        self._notebook.AddPage(self._categories_page, _('Categories'))
        self._notebook.AddPage(self._rules_page, _('Custom Rules'))
        self._notebook.AddPage(self._columns_page, _('Selected Columns'))
        vbox.Add(self._notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        apply_btn = wx.Button(self, label=_('Apply'))
        apply_btn.Bind(wx.EVT_BUTTON, self._on_apply)
        btns.Add(apply_btn, 0, wx.RIGHT, 10)
        btns.AddStretchSpacer()
        btns.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL))
        vbox.Add(btns, 0, wx.EXPAND | wx.ALL, 10)

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        self.CenterOnParent()

    def mark_dirty(self):
        pass  # hook point; nothing persists until Apply/OK

    # --- master control handlers -------------------------------------

    def _on_enable_changed(self, event):
        self.working_profile.enabled = self._enable_chk.GetValue()

    def _on_apply_mode(self, event):
        self.working_profile.apply_mode = (
            profile_mod.APPLY_COLUMNS if self._apply_cols_radio.GetValue()
            else profile_mod.APPLY_ROW)

    def _on_legend_changed(self, event):
        self.working_profile.show_legend = self._legend_chk.GetValue()

    def _on_invalid_changed(self, event):
        self.working_profile.flag_invalid = self._invalid_chk.GetValue()

    def _on_use_default(self, event):
        if wx.MessageBox(
                _('Replace ALL current color settings (including custom '
                  'rules) with the built-in default profile?'),
                _('Use Default Color Profile'),
                wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self.working_profile = profile_mod.default_profile()
        self._reload_all()

    def _reload_all(self):
        self._enable_chk.SetValue(self.working_profile.enabled)
        self._apply_cols_radio.SetValue(
            self.working_profile.apply_mode == profile_mod.APPLY_COLUMNS)
        self._apply_row_radio.SetValue(
            self.working_profile.apply_mode == profile_mod.APPLY_ROW)
        self._legend_chk.SetValue(self.working_profile.show_legend)
        self._invalid_chk.SetValue(self.working_profile.flag_invalid)
        self._categories_page.reload()
        self._rules_page.reload()

    # --- import/export -------------------------------------------------

    def _on_export(self, event):
        with wx.FileDialog(
                self, _('Export Color Profile'),
                wildcard=_('JSON files') + ' (*.json)|*.json',
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal() != wx.ID_OK:
                return
            path = d.GetPath()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.working_profile.to_json())
        except OSError as e:
            common.error_proof.show_error(
                _('Failed to write %(path)s: %(error)s') % {
                    'path': path, 'error': e})

    def _on_import(self, event):
        with wx.FileDialog(
                self, _('Import Color Profile'),
                wildcard=_('JSON files') + ' (*.json)|*.json',
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal() != wx.ID_OK:
                return
            path = d.GetPath()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            imported = profile_mod.ColorProfile.from_json(text)
        except (OSError, profile_mod.ProfileValidationError) as e:
            common.error_proof.show_error(
                _('Could not import %(path)s: %(error)s') % {
                    'path': path, 'error': e})
            return

        msg = _('Import color profile "%s"?') % imported.profile_name
        if imported.load_warnings:
            msg += '\n\n' + _('Note: some entries were invalid and will '
                              'use defaults:') + '\n' + '\n'.join(
                imported.load_warnings)
        if wx.MessageBox(msg, _('Import Color Profile'),
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self.working_profile = imported
        self._reload_all()

    # --- dialog buttons -------------------------------------------------

    def _on_apply(self, event):
        self._controller.replace_profile(copy.deepcopy(self.working_profile))

    def _on_ok(self, event):
        self._controller.replace_profile(copy.deepcopy(self.working_profile))
        event.Skip()

    def _on_cancel(self, event):
        # Persisted settings were never touched unless Apply was pressed
        # explicitly, matching the required Cancel semantics.
        event.Skip()
