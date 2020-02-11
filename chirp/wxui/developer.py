import os

import wx
import wx.richtext
import wx.lib.scrolledpanel

from chirp import bitwise
from chirp.wxui import common


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

    def set_up(self):
        pass


class ChirpStringEditor(ChirpEditor):
    def set_up(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        entry = wx.TextCtrl(self, value=str(self._obj))
        entry.SetMaxLength(len(self._obj))
        self.SetSizer(sizer)
        sizer.Add(entry, 1, wx.EXPAND)


class ChirpIntegerEditor(ChirpEditor):
    def set_up(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer)

        hexdigits = (self._obj.size() / 4) + (self._obj.size() % 4 and 1 or 0)
        bindigits = self._obj.size()

        editors = {'Hex': (16, '{:0%iX}' % hexdigits),
                   'Dec': (10, '{:d}'),
                   'Bin': (2, '{:0%ib}' % bindigits)}
        for name, (base, fmt) in editors.items():
            label = wx.StaticText(self, label=name)
            entry = wx.TextCtrl(self, value=fmt.format(int(self._obj)))
            sizer.Add(label, 0, wx.ALIGN_CENTER)
            sizer.Add(entry, 1, flag=wx.EXPAND)


class ChirpBCDEditor(ChirpEditor):
    def set_up(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer)
        entry = wx.TextCtrl(self, value=str(int(self._obj)))
        sizer.Add(entry, 1, wx.EXPAND)


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
            self._sizer.Add(label, 0, wx.ALIGN_CENTER)
            self._sizer.Add(editor, 1, flag=wx.EXPAND)

        self._editors = {}
        self._sizer.Layout()


class ChirpRadioBrowser(common.ChirpEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpRadioBrowser, self).__init__(*a, **k)

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
        pd = wx.ProgressDialog('Loading', 'Building Radio Browser')
        self._load_from_radio('root', self._radio._memobj, pd)
        pd.Destroy()

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
