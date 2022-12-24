# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
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

import functools
import logging
import os

import wx
import wx.richtext
import wx.lib.scrolledpanel

from chirp import bitwise
from chirp.wxui import common

LOG = logging.getLogger(__name__)
BrowserChanged, EVT_BROWSER_CHANGED = wx.lib.newevent.NewCommandEvent()


def simple_diff(a, b, diffsonly=False):
    lines_a = a.split(os.linesep)
    lines_b = b.split(os.linesep)
    blankprinted = True

    diff = ""
    for i in range(0, len(lines_a)):
        if lines_a[i] != lines_b[i]:
            diff += "-%s%s" % (lines_a[i], os.linesep)
            diff += "+%s%s" % (lines_b[i], os.linesep)
            blankprinted = False
        elif diffsonly is True:
            if blankprinted:
                continue
            diff += os.linesep
            blankprinted = True
        else:
            diff += " %s%s" % (lines_a[i], os.linesep)
    return diff


class MemoryDialog(wx.Dialog):
    def __init__(self, mem, *a, **k):

        super(MemoryDialog, self).__init__(*a, **k)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self.text = wx.richtext.RichTextCtrl(
            self, style=wx.VSCROLL | wx.HSCROLL | wx.NO_BORDER)
        sizer.Add(self.text, 1, wx.EXPAND)

        sizer.Add(wx.StaticLine(self), 0)

        bs = self.CreateButtonSizer(wx.OK | wx.OK_DEFAULT)
        sizer.Add(bs)

        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.CLOSE))

        font = wx.Font(12, wx.FONTFAMILY_MODERN, wx.FONTSTYLE_NORMAL,
                       wx.FONTWEIGHT_NORMAL)

        self.text.BeginFont(font)

        if isinstance(mem, tuple):
            mem_a, mem_b = mem
            self._diff_memories(mem_a, mem_b)
        else:
            self._raw_memory(mem)

        self.SetSize(640, 480)
        self.Centre()

    def _raw_memory(self, mem):
        self.text.WriteText(mem)

    def _diff_memories(self, mem_a, mem_b):
        diff = simple_diff(mem_a, mem_b)

        for line in diff.split(os.linesep):
            color = None
            if line.startswith('+'):
                self.text.BeginTextColour((255, 0, 0))
                color = True
            elif line.startswith('-'):
                self.text.BeginTextColour((0, 0, 255))
                color = True
            self.text.WriteText(line)
            self.text.Newline()
            if color:
                self.text.EndTextColour()


class ChirpEditor(wx.Panel):
    def __init__(self, parent, obj):
        super(ChirpEditor, self).__init__(parent)
        self._obj = obj
        self._fixed_font = wx.Font(pointSize=10,
                                   family=wx.FONTFAMILY_TELETYPE,
                                   style=wx.FONTSTYLE_NORMAL,
                                   weight=wx.FONTWEIGHT_NORMAL)
        self._changed_color = wx.Colour(0, 255, 0)
        self._error_color = wx.Colour(255, 0, 0)

    def refresh(self):
        """Called to refresh the widget from memory"""
        pass

    def set_up(self):
        pass

    def _mark_changed(self, thing):
        thing.SetBackgroundColour(self._changed_color)
        tt = thing.GetToolTip()
        if not tt:
            tt = wx.ToolTip('')
            thing.SetToolTip(tt)
        tt.SetTip(_('Press enter to set this in memory'))

    def _mark_unchanged(self, thing, mem_changed=True):
        thing.SetBackgroundColour(wx.NullColour)
        thing.UnsetToolTip()
        if mem_changed:
            wx.PostEvent(self, BrowserChanged(self.GetId()))

    def _mark_error(self, thing, reason):
        tt = thing.GetToolTip()
        if not tt:
            tt = wx.ToolTip('')
            thing.SetToolTip(tt)
        tt.SetTip(reason)
        thing.SetBackgroundColour(self._error_color)

    def __repr__(self):
        addr = '0x%02x' % int(self._obj._offset)

        def typestr(c):
            return c.__class__.__name__.lower().replace('dataelement', '')

        if isinstance(self._obj, bitwise.arrayDataElement):
            innertype = list(self._obj.items())[0][1]
            return '%s[%i] (%i %s) @ %s' % (typestr(innertype),
                                            len(self._obj),
                                            innertype.size() / 8,
                                            _('bytes each'),
                                            addr)
        elif self._obj.size() % 8 == 0:
            return '%s (%i %s) @ %s' % (typestr(self._obj),
                                        self._obj.size() / 8,
                                        _('bytes'),
                                        addr)
        else:
            return '%s %s @ %s' % (self._obj.size(),
                                   _('bits'),
                                   addr)


class ChirpStringEditor(ChirpEditor):
    def set_up(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._entry = wx.TextCtrl(self, value=str(self._obj),
                                  style=wx.TE_PROCESS_ENTER)
        self._entry.SetMaxLength(len(self._obj))
        self.SetSizer(sizer)
        sizer.Add(self._entry, 1, wx.EXPAND)

        self._entry.Bind(wx.EVT_TEXT, self._edited)
        self._entry.Bind(wx.EVT_TEXT_ENTER, self._changed)

    def refresh(self):
        self._entry.SetValue(str(self._obj))
        self._mark_unchanged(self._entry, mem_changed=False)

    def _edited(self, event):
        entry = event.GetEventObject()
        value = entry.GetValue()
        if len(value) == len(self._obj):
            self._mark_changed(entry)
        else:
            self._mark_error(entry, _('Length must be %i') % len(self._obj))

    @common.error_proof()
    def _changed(self, event):
        entry = event.GetEventObject()
        value = entry.GetValue()
        self._obj.set_value(value)
        self._mark_unchanged(entry)
        LOG.debug('Set value: %r' % value)


class ChirpIntegerEditor(ChirpEditor):
    def set_up(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer)

        hexdigits = (self._obj.size() / 4) + (self._obj.size() % 4 and 1 or 0)
        bindigits = self._obj.size()

        self._editors = {_('Hex'): (16, '{:0%iX}' % hexdigits),
                         _('Dec'): (10, '{:d}'),
                         _('Bin'): (2, '{:0%ib}' % bindigits)}
        self._entries = {}
        for name, (base, fmt) in self._editors.items():
            label = wx.StaticText(self, label=name)
            entry = wx.TextCtrl(self, value=fmt.format(int(self._obj)),
                                style=wx.TE_PROCESS_ENTER)
            entry.SetFont(self._fixed_font)
            sizer.Add(label, 0, wx.ALIGN_CENTER)
            sizer.Add(entry, 1, flag=wx.EXPAND)
            self._entries[name] = entry

            entry.Bind(wx.EVT_TEXT, functools.partial(self._edited,
                                                      base=base))
            entry.Bind(wx.EVT_TEXT_ENTER, functools.partial(self._changed,
                                                            base=base))

    def refresh(self):
        for name, (base, fmt) in self._editors.items():
            self._entries[name].SetValue(fmt.format(int(self._obj)))
            self._mark_unchanged(self._entries[name],
                                 mem_changed=False)

    def _edited(self, event, base=10):
        entry = event.GetEventObject()
        others = {n: e for n, e in self._entries.items()
                  if e != entry}

        try:
            val = int(entry.GetValue(), base)
            assert val >= 0, _('Value must be zero or greater')
            assert val < pow(2, self._obj.size()), \
                _('Value does not fit in %i bits') % self._obj.size()
        except (ValueError, AssertionError) as e:
            self._mark_error(entry, str(e))
            return
        else:
            self._mark_changed(entry)

        for name, entry in others.items():
            base, fmt = self._editors[name]
            entry.ChangeValue(fmt.format(val))

    @common.error_proof()
    def _changed(self, event, base=10):
        entry = event.GetEventObject()
        val = int(entry.GetValue(), base)
        self._obj.set_value(val)
        self._mark_unchanged(entry)
        LOG.debug('Set value: %r' % val)


class ChirpBCDEditor(ChirpEditor):
    def set_up(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer)
        self._entry = wx.TextCtrl(self, value=str(int(self._obj)),
                                  style=wx.TE_PROCESS_ENTER)
        self._entry.SetFont(self._fixed_font)
        sizer.Add(self._entry, 1, wx.EXPAND)
        self._entry.Bind(wx.EVT_TEXT, self._edited)
        self._entry.Bind(wx.EVT_TEXT_ENTER, self._changed)

    def refresh(self):
        self._entry.SetValue(str(int(self._obj)))
        self._mark_unchanged(self._entry,
                             mem_changed=False)

    def _edited(self, event):
        entry = event.GetEventObject()
        try:
            val = int(entry.GetValue())
            digits = self._obj.size() // 4
            assert val >= 0, _('Value must be zero or greater')
            assert len(entry.GetValue()) == digits, \
                   _('Value must be exactly %i decimal digits') % digits
        except (ValueError, AssertionError) as e:
            self._mark_error(entry, str(e))
        else:
            self._mark_changed(entry)

    @common.error_proof()
    def _changed(self, event):
        entry = event.GetEventObject()
        val = int(entry.GetValue())
        self._obj.set_value(val)
        self._mark_unchanged(entry)
        LOG.debug('Set Value: %r' % val)


class ChirpBrowserPanel(wx.lib.scrolledpanel.ScrolledPanel):
    def __init__(self, parent, memobj):
        super(ChirpBrowserPanel, self).__init__(parent)
        self._sizer = wx.FlexGridSizer(2)
        self._sizer.AddGrowableCol(1)
        self.SetSizer(self._sizer)
        self.SetupScrolling()
        self._parent = parent
        self._memobj = memobj
        self._editors = {}
        self._initialized = False

    def add_editor(self, name, editor):
        self._editors[name] = editor
        editor.Bind(EVT_BROWSER_CHANGED, self._panel_changed)

    def _panel_changed(self, event):
        wx.PostEvent(self, BrowserChanged(self.GetId()))

    def _initialize(self):
        for name, obj in self._memobj.items():
            editor = None
            if isinstance(obj, bitwise.arrayDataElement):
                if isinstance(obj[0], bitwise.charDataElement):
                    editor = ChirpStringEditor(self, obj)
                elif isinstance(obj[0], bitwise.bcdDataElement):
                    editor = ChirpBCDEditor(self, obj)
                else:
                    self._parent.add_sub_panel(name, obj, self)
            elif isinstance(obj, bitwise.intDataElement):
                editor = ChirpIntegerEditor(self, obj)
            elif isinstance(obj, bitwise.structDataElement):
                self._parent.add_sub_panel(name, obj, self)
            if editor:
                self.add_editor(name, editor)
        self._initialized = True

    def add_sub_panel(self, name, obj, parent):
        # This just forwards until we get to the browser
        self._parent.add_sub_panel(name, obj, parent)

    def selected(self):
        if not self._initialized:
            self._initialize()

            for name, editor in self._editors.items():
                editor.set_up()
                label = wx.StaticText(self, label='%s: ' % name)
                tt = wx.ToolTip(repr(editor))
                label.SetToolTip(tt)

                self._sizer.Add(label, 0, wx.ALIGN_CENTER)
                self._sizer.Add(editor, 1, flag=wx.EXPAND)
        else:
            for editor in self._editors.values():
                editor.refresh()

        self._sizer.Layout()


class ChirpRadioBrowser(common.ChirpEditor, common.ChirpSyncEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpRadioBrowser, self).__init__(*a, **k)
        self._loaded = False
        self._radio = radio
        self._features = radio.get_features()

        self._treebook = wx.Treebook(self)

        try:
            view = self._treebook.GetTreeCtrl()
        except AttributeError:
            # https://github.com/wxWidgets/Phoenix/issues/918
            view = self._treebook.GetChildren()[0]

        view.SetMinSize((250, 0))

        self._treebook.Bind(wx.EVT_TREEBOOK_PAGE_CHANGED,
                            self.page_selected)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._treebook, 1, wx.EXPAND)
        self.SetSizer(sizer)

    def _page_changed(self, event):
        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def selected(self):
        if self._loaded:
            self._treebook.CurrentPage.selected()
            return

        self.start_wait_dialog(_('Building Radio Browser'))

        self._loaded = True
        self.add_sub_panel('%s %s' % (self._radio.VENDOR,
                                      self._radio.MODEL),
                           self._radio._memobj, self)
        self.stop_wait_dialog()
        if self._treebook.GetPageCount():
            self._treebook.ExpandNode(0)

    def page_selected(self, event):
        page = self._treebook.GetPage(event.GetSelection())
        page.selected()

    def add_sub_panel(self, name, memobj, parent):
        LOG.debug('Adding sub panel for %s' % name)
        page = ChirpBrowserPanel(self, memobj)
        page.Bind(EVT_BROWSER_CHANGED, self._page_changed)
        if parent != self:
            pos = self._treebook.FindPage(parent)
            self._treebook.InsertSubPage(pos, page, name)
            self._treebook.ExpandNode(pos)
        else:
            self._treebook.AddPage(page, name)
