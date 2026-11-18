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

    def select_columns(self, parent):
        col_defs = [col_def for col_def in self._col_defs if col_def.valid]
        choices = [col_def.label.replace('\n', ' ')
                   for col_def in col_defs]
        hidden_names = list(dict.fromkeys(
            name.strip() for name in
            (CONF.get('hide_in_printout', 'printing') or '').split(',')
            if name.strip()))
        hidden = set(hidden_names)
        dialog = wx.MultiChoiceDialog(
            parent, _('Select columns to include in print output'),
            _('Print Columns'), choices)
        dialog.SetSelections([i for i, col_def in enumerate(col_defs)
                              if col_def.name not in hidden])
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return False
            selected = set(dialog.GetSelections())
            self._col_defs = [col_def for i, col_def in enumerate(col_defs)
                              if i in selected]

            # Keep exclusions for columns not available on this radio so
            # switching models does not discard the user's preferences.
            available_names = {col_def.name for col_def in col_defs}
            hidden_names = [name for name in hidden_names
                            if name not in available_names]
            hidden_names.extend(col_def.name
                                for i, col_def in enumerate(col_defs)
                                if i not in selected)
            CONF.set('hide_in_printout', ','.join(hidden_names), 'printing')
            config._CONFIG.save()
            return True
        finally:
            dialog.Destroy()

    def _column_widths(self, memories, col_defs):
        dc = wx.ScreenDC()
        fixed_font = wx.Font(
            pointSize=self._font_size,
            family=wx.FONTFAMILY_TELETYPE,
            style=wx.FONTSTYLE_NORMAL,
            weight=wx.FONTWEIGHT_NORMAL,
            faceName=self._fixed_font)
        normal_font = wx.Font(
            pointSize=self._font_size,
            family=wx.FONTFAMILY_DEFAULT,
            style=wx.FONTSTYLE_NORMAL,
            weight=wx.FONTWEIGHT_BOLD,
            faceName=self._normal_font)

        def measure(text):
            text = ' '.join(str(text).split())
            return dc.GetTextExtent(text)[0]

        widths = {None: 0}
        for col_def in col_defs:
            widths[col_def.name] = 0

        dc.SetFont(fixed_font)
        widths[None] = max([measure('#')] +
                           [measure(mem.number) for mem in memories])
        for col_def in col_defs:
            for mem in memories:
                try:
                    value = col_def.render_value(mem)
                except IndexError:
                    continue
                widths[col_def.name] = max(widths[col_def.name],
                                           measure(value))

        dc.SetFont(normal_font)
        widths[None] = max(widths[None], measure('#'))
        for col_def in col_defs:
            label = ' '.join(col_def.label.split())
            widths[col_def.name] = max(widths[col_def.name],
                                       measure(label))

        screen_ppi = dc.GetPPI()[0] or 96
        pixel_scale = 96.0 / screen_ppi
        # Match wxHTML's default 3px cell padding and 1px cell border on
        # either side of the measured text, with a small allowance for
        # differences between screen and printer font metrics.
        return {name: int(width * pixel_scale + 0.5) + 12
                for name, width in widths.items()}

    def _cell_attrs(self, name, expander, widths):
        width = ('100%' if expander and name == expander else
                 widths[name])
        return ['nowrap', ('width', str(width))]

    def _memory(self, doc, mem, expander, widths):
        tag = doc.tag
        with tag('td', *self._cell_attrs(None, expander, widths)):
            with tag('tt'):
                doc.text(mem.number)
        for col_def in self._col_defs:
            if not col_def.valid:
                continue
            with tag('td', *self._cell_attrs(col_def.name, expander,
                                             widths)):
                with tag('tt'):
                    doc.text(col_def.render_value(mem))

    def _memory_table(self, doc, memories):
        tag = doc.tag
        col_defs = [col_def for col_def in self._col_defs
                    if col_def.valid]
        col_names = {col_def.name for col_def in col_defs}
        expander = ('comment' if 'comment' in col_names else
                    'name' if 'name' in col_names else None)
        widths = self._column_widths(memories, col_defs)

        for i in range(0, len(memories), self._rows_per_page):
            with tag('div', ('style', 'page-break-before:always')):
                pass
            table_attrs = [('border', '1'), ('cellspacing', '0')]
            if expander:
                table_attrs.append(('width', '100%'))
            with tag('table', *table_attrs):
                with tag('tr'):
                    with tag('th', *self._cell_attrs(None, expander,
                                                     widths)):
                        doc.text('#')
                    for col_def in col_defs:
                        with tag('th', *self._cell_attrs(col_def.name,
                                                         expander, widths)):
                            doc.text(' '.join(col_def.label.split()))
                for row in range(i, i + self._rows_per_page):
                    try:
                        mem = memories[row]
                    except IndexError:
                        continue
                    with tag('tr'):
                        try:
                            self._memory(doc, mem, expander, widths)
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
