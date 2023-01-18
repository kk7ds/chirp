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
from chirp.wxui import config
from chirp.wxui import report

CONF = config.get()


class MemoryPrinter(wx.html.HtmlEasyPrinting):
    def __init__(self, parent, radio, memedit):
        super().__init__(name=_('Printing'), parentWindow=parent)
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

        # These are arbitrary defaults that seem to work okay. Let people
        # override via the config for now
        try:
            self._font_size = CONF.get_int('font_size', 'printing')
        except TypeError:
            self._font_size = 8
        try:
            self._rows_per_page = CONF.get_int('rows_per_page', 'printing')
        except TypeError:
            self._rows_per_page = 35
        self._normal_font = CONF.get('normal_font', 'printing') or 'Sans'
        self._fixed_font = CONF.get('fixed_font', 'printing') or 'Courier'
        self.SetStandardFonts(self._font_size, self._normal_font,
                              self._fixed_font)

    def _memory(self, doc, mem):
        tag = doc.tag
        with tag('td'):
            with tag('tt'):
                doc.text(mem.number)
        for col_def in self._col_defs:
            if not col_def.valid:
                continue
            with tag('td', 'nowrap'):
                with tag('tt'):
                    doc.text(col_def.render_value(mem))

    def _memory_table(self, doc, memories):
        tag = doc.tag
        row = 0

        for i in range(0, len(memories), self._rows_per_page):
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
                            pieces = col_def.label.split()
                            for piece in pieces:
                                doc.text(piece)
                                if piece != pieces[-1]:
                                    doc.stag('br')
                for row in range(i, i + self._rows_per_page):
                    try:
                        mem = memories[row]
                    except IndexError:
                        continue
                    with tag('tr'):
                        try:
                            self._memory(doc, mem)
                        except IndexError:
                            pass

    def _print(self, memories):
        report.report_model(self._radio, 'print')
        memories = [m for m in memories if not m.empty]
        doc, tag, text = yattag.Doc().tagtext()
        with tag('html'):
            with tag('body'):
                self._memory_table(doc, memories)
        return doc

    @common.error_proof()
    def print(self, memories):
        doc = self._print(memories)
        self.PrintText(doc.getvalue())

    @common.error_proof()
    def print_preview(self, memories):
        doc = self._print(memories)
        return self.PreviewText(doc.getvalue())
