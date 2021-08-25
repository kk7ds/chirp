import functools
import logging
import os

import wx
import wx.richtext
import wx.lib.scrolledpanel

from chirp import bitwise
from chirp.wxui import common

LOG = logging.getLogger(__name__)


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
            self, style=wx.VSCROLL|wx.HSCROLL|wx.NO_BORDER)
        sizer.Add(self.text, 1, wx.EXPAND)

        sizer.Add(wx.StaticLine(self), 0)

        btn = wx.Button(self, wx.OK, 'OK')
        btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.OK))
        sizer.Add(btn, 0)

        font = wx.Font(12, wx.FONTFAMILY_MODERN, wx.FONTSTYLE_NORMAL,
                       wx.FONTWEIGHT_NORMAL)

        self.text.BeginFont(font)

        if isinstance(mem, tuple):
            mem_a, mem_b = mem
            self._diff_memories(mem_a, mem_b)
        else:
            self._raw_memory(mem)

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

    def set_up(self):
        pass

    def _mark_changed(self, thing):
        thing.SetBackgroundColour(self._changed_color)
        tt = thing.GetToolTip()
        if not tt:
            tt = wx.ToolTip('')
            thing.SetToolTip(tt)
        tt.SetTip('Press enter to set this in memory')

    def _mark_unchanged(self, thing):
        thing.SetBackgroundColour(wx.NullColour)
        thing.UnsetToolTip()

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
            return '%s[%i] (%i bytes each) @ %s' % (typestr(innertype),
                                                    len(self._obj),
                                                    innertype.size() / 8,
                                                    addr)
        elif self._obj.size() % 8 == 0:
            return '%s (%i bytes) @ %s' % (typestr(self._obj),
                                           self._obj.size() / 8,
                                           addr)
        else:
            return '%s bits @ %s' % (self._obj.size(),
                                     addr)


class ChirpStringEditor(ChirpEditor):
    def set_up(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        entry = wx.TextCtrl(self, value=str(self._obj),
                            style=wx.TE_PROCESS_ENTER)
        entry.SetMaxLength(len(self._obj))
        self.SetSizer(sizer)
        sizer.Add(entry, 1, wx.EXPAND)

        entry.Bind(wx.EVT_TEXT, self._edited)
        entry.Bind(wx.EVT_TEXT_ENTER, self._changed)

    def _edited(self, event):
        entry = event.GetEventObject()
        value = entry.GetValue()
        if len(value) == len(self._obj):
            self._mark_changed(entry)
        else:
            self._mark_error(entry, 'Length must be %i' % len(self._obj))

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

        self._editors = {'Hex': (16, '{:0%iX}' % hexdigits),
                         'Dec': (10, '{:d}'),
                         'Bin': (2, '{:0%ib}' % bindigits)}
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

    def _edited(self, event, base=10):
        entry = event.GetEventObject()
        others = {n: e for n, e in self._entries.items()
                  if e != entry}

        try:
            val = int(entry.GetValue(), base)
            assert val >= 0, 'Value must be zero or greater'
            assert val < pow(2, self._obj.size()), \
                'Value does not fit in %i bits' % self._obj.size()
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
        entry = wx.TextCtrl(self, value=str(int(self._obj)),
                            style=wx.TE_PROCESS_ENTER)
        entry.SetFont(self._fixed_font)
        sizer.Add(entry, 1, wx.EXPAND)
        entry.Bind(wx.EVT_TEXT, self._edited)
        entry.Bind(wx.EVT_TEXT_ENTER, self._changed)

    def _edited(self, event):
        entry = event.GetEventObject()
        try:
            val = int(entry.GetValue())
            digits = self._obj.size() // 4
            assert val >= 0, 'Value must be zero or greater'
            assert len(entry.GetValue()) == digits, \
                   'Value must be exactly %i decimal digits' % digits
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
    def __init__(self, parent):
        super(ChirpBrowserPanel, self).__init__(parent)
        self._sizer = wx.FlexGridSizer(2)
        self._sizer.AddGrowableCol(1)
        self.SetSizer(self._sizer)
        self.SetupScrolling()
        self._editors = {}

    def add_editor(self, name, editor):
        self._editors[name] = editor

    def selected(self):
        for name, editor in self._editors.items():
            editor.set_up()
            label = wx.StaticText(self, label='%s: ' % name)
            tt = wx.ToolTip(repr(editor))
            label.SetToolTip(tt)

            self._sizer.Add(label, 0, wx.ALIGN_CENTER)
            self._sizer.Add(editor, 1, flag=wx.EXPAND)

        self._editors = {}
        self._sizer.Layout()


class ChirpRadioBrowser(common.ChirpEditor):
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

        view.SetMinSize((250,0))

        self._treebook.Bind(wx.EVT_TREEBOOK_PAGE_CHANGED,
                            self.page_selected)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._treebook, 1, wx.EXPAND)
        self.SetSizer(sizer)

    def selected(self):
        if self._loaded:
            return

        pd = wx.ProgressDialog('Loading', 'Building Radio Browser')
        self._loaded = True
        self._load_from_radio('%s %s' % (self._radio.VENDOR,
                                         self._radio.MODEL),
                              self._radio._memobj, pd)
        pd.Destroy()
        self._treebook.ExpandNode(0)

    def page_selected(self, event):
        page = self._treebook.GetPage(event.GetSelection())
        page.selected()

    def _load_from_radio(self, name, memobj, pd, parent=None):
        editor = None

        def sub_panel(name, memobj, pd, parent):
            page = ChirpBrowserPanel(self)
            if parent:
                pos = self._treebook.FindPage(parent)
                self._treebook.InsertSubPage(pos, page, name)
                # Stop updating the progress dialog once we get past the
                # first generation in the tree because it slows us down
                # a lot.
                pd = None
            else:
                self._treebook.AddPage(page, name)

            for subname, item in memobj.items():
                self._load_from_radio(subname, item, pd, parent=page)


        if isinstance(memobj, bitwise.structDataElement):
            if pd:
                pd.Pulse('Loading %s' % name)
            sub_panel(name, memobj, pd, parent)
        elif isinstance(memobj, bitwise.arrayDataElement):
            if isinstance(memobj[0], bitwise.charDataElement):
                editor = ChirpStringEditor(parent, memobj)
            elif isinstance(memobj[0], bitwise.bcdDataElement):
                editor = ChirpBCDEditor(parent, memobj)
            else:
                if pd:
                    pd.Pulse('Loading %s' % name)
                sub_panel('%s[%i]' % (name, len(memobj)), memobj, pd, parent)
        elif isinstance(memobj, bitwise.intDataElement):
            editor = ChirpIntegerEditor(parent, memobj)
        else:
            print('Unsupported editor type for %s (%s)' % (
                name, memobj.__class__))

        if editor:
            parent.add_editor(name, editor)
