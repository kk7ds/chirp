import os

import wx
import wx.richtext


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

