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

import wx.html

import yattag

from chirp.wxui import common
from chirp.wxui import report


class MemoryPrinter(wx.html.HtmlEasyPrinting):
    def __init__(self, parent, radio, memedit):
        super().__init__()
        self._radio = radio
        self._features = radio.get_features()
        self._col_defs = memedit._col_defs
        # Set some default printer and page options.
        self.GetPrintData().SetPaperId(wx.PAPER_LETTER)  # wx.PAPER_A4
        self.GetPrintData().SetOrientation(wx.LANDSCAPE)  # wx.PORTRAIT
        # Black and white printing if False.
        self.GetPrintData().SetColour(False)
        self.GetPageSetupData().SetMarginTopLeft((0, 5))
        self.GetPageSetupData().SetMarginBottomRight((10, 10))
        self.SetFonts('Sans', 'Courier', (8,) * 7)

    def _memory(self, doc, mem):
        tag = doc.tag
        with tag('td'):
            with tag('tt'):
                doc.text(mem.number)
        for col_def in self._col_defs:
            if not col_def.valid:
                continue
            with tag('td'):
                with tag('tt'):
                    doc.text(col_def.render_value(mem))

    def _memory_table(self, doc, memories):
        tag = doc.tag
        row = 0

        # This is arbitrary, unsure if it will work on all platforms
        # or not
        ROWS_PER_PAGE = 35

        for i in range(0, len(memories), ROWS_PER_PAGE):
            with tag('div', ('style', 'page-break-before:always')):
                pass
            with tag('table', ('border', '1'), ('width', '100%'),
                     ('cellspacing', '0')):
                with tag('tr'):
                    with tag('th'):
                        doc.text('#')
                    for col_def in self._col_defs:
                        if not col_def.valid:
                            continue
                        with tag('th'):
                            doc.text(col_def.label)
                for row in range(i, i + ROWS_PER_PAGE):
                    try:
                        mem = memories[row]
                    except IndexError:
                        continue
                    with tag('tr'):
                        try:
                            self._memory(doc, mem)
                        except IndexError:
                            pass

    @common.error_proof()
    def print(self, memories):
        report.report_model(self._radio, 'print')
        memories = [m for m in memories if not m.empty]
        doc, tag, text = yattag.Doc().tagtext()
        with tag('html'):
            with tag('body'):
                self._memory_table(doc, memories)
        return self.PreviewText(doc.getvalue())
