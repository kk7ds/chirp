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
        self.GetPageSetupData().SetPaperId(wx.PAPER_LETTER)
        self.GetPageSetupData().GetPrintData().SetOrientation(wx.LANDSCAPE)
        self.GetPageSetupData().SetMarginTopLeft((5, 5))
        self.GetPageSetupData().SetMarginBottomRight((10, 10))

        # These are arbitrary defaults that seem to work okay. Let people
        # override via the config for now
        try:
            self._font_size = CONF.get_int('font_size', 'printing')
        except TypeError:
            self._font_size = 8
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
            pieces = col_def.label.split()
            label_width = max(measure(piece) for piece in pieces)
            widths[col_def.name] = max(widths[col_def.name],
                                       label_width)

        screen_ppi = dc.GetPPI()[1] or 96
        pixel_scale = 96.0 / screen_ppi
        # Match wxHTML's default 3px cell padding and 1px cell border on
        # either side of the measured text, with a small allowance for
        # differences between screen and printer font metrics.
        return {name: int(width * pixel_scale + 0.5) + 12
                for name, width in widths.items()}

    def _cell_attrs(self, name, expander, widths, nowrap=True):
        width = ('100%' if expander and name == expander else
                 widths[name])
        attrs = [('width', str(width))]
        if nowrap:
            attrs.append('nowrap')
        return attrs

    def _table_markup(self, memories, col_defs, expander, widths):
        doc, tag, text = yattag.Doc().tagtext()
        table_attrs = [('border', '1'), ('cellspacing', '0')]
        if expander:
            table_attrs.append(('width', '100%'))
        with tag('table', *table_attrs):
            with tag('tr'):
                with tag('th', *self._cell_attrs(None, expander, widths)):
                    doc.text('#')
                for col_def in col_defs:
                    with tag('th', *self._cell_attrs(col_def.name, expander,
                                                     widths, nowrap=False)):
                        for i, piece in enumerate(col_def.label.split()):
                            if i:
                                doc.stag('br')
                            doc.text(piece)
            for mem in memories:
                with tag('tr'):
                    try:
                        self._memory(doc, mem, expander, widths)
                    except IndexError:
                        pass
        return doc.getvalue()

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

    def _printout_args(self, memories):
        memories = [mem for mem in memories if not mem.empty]
        col_defs = [col_def for col_def in self._col_defs
                    if col_def.valid]
        col_names = {col_def.name for col_def in col_defs}
        expander = ('comment' if 'comment' in col_names else
                    'name' if 'name' in col_names else None)
        widths = self._column_widths(memories, col_defs)
        return memories, col_defs, expander, widths

    def _copy_print_data(self, data):
        target = self.GetPrintData()
        target.SetPrinterName(data.GetPrinterName())
        target.SetPaperId(data.GetPaperId())
        target.SetOrientation(data.GetOrientation())
        target.SetColour(data.GetColour())
        target.SetNoCopies(data.GetNoCopies())
        target.SetCollate(data.GetCollate())
        target.SetDuplex(data.GetDuplex())
        target.SetQuality(data.GetQuality())
        target.SetBin(data.GetBin())

    def _print_dialog_data(self):
        data = wx.PrintDialogData(self.GetPrintData())
        print_data = data.GetPrintData()
        print_data.SetPaperId(wx.PAPER_LETTER)
        print_data.SetOrientation(wx.LANDSCAPE)
        return data

    @common.error_proof()
    def print(self, memories):
        report.report_model(self._radio, 'print')
        printout = MemoryPrintout(self, *self._printout_args(memories))
        data = self._print_dialog_data()
        printer = wx.Printer(data)
        if not printer.Print(self.GetParentWindow(), printout, True):
            if wx.Printer.GetLastError() == wx.PRINTER_ERROR:
                wx.MessageBox(_('There was a problem printing.'),
                              _('Printing'), wx.OK | wx.ICON_ERROR,
                              self.GetParentWindow())
            return False
        self._copy_print_data(
            printer.GetPrintDialogData().GetPrintData())
        return True

    @common.error_proof()
    def print_preview(self, memories):
        report.report_model(self._radio, 'print')
        args = self._printout_args(memories)
        printout = MemoryPrintout(self, *args)
        printout_for_printing = MemoryPrintout(self, *args)
        data = self._print_dialog_data()
        preview = wx.PrintPreview(printout, printout_for_printing, data)
        if not preview.IsOk():
            wx.MessageBox(_('There was a problem preparing the preview.'),
                          _('Print Preview'), wx.OK | wx.ICON_ERROR,
                          self.GetParentWindow())
            return False

        parent = self.GetParentWindow()
        frame = wx.PreviewFrame(
            preview, parent, _('%s Preview') % self.GetName(),
            wx.DefaultPosition, wx.Window.FromDIP(wx.Size(650, 500), parent))
        frame.Centre(wx.BOTH)
        frame.Initialize()
        frame.Show(True)
        return True


class MemoryPrintout(wx.Printout):
    def __init__(self, printer, memories, col_defs, expander, widths):
        super().__init__(_('Printing'))
        self._printer = printer
        self._memories = memories
        self._col_defs = col_defs
        self._expander = expander
        self._widths = widths
        self._pages = []

    def _renderer(self, dc, pixel_scale, font_scale, width, height):
        renderer = wx.html.HtmlDCRenderer()
        try:
            renderer.SetDC(dc, pixel_scale, font_scale)
        except TypeError:
            renderer.SetDC(dc, pixel_scale)
        renderer.SetStandardFonts(self._printer._font_size,
                                  self._printer._normal_font,
                                  self._printer._fixed_font)
        renderer.SetSize(width, height)
        return renderer

    def _page_metrics(self):
        page_width, page_height = self.GetPageSizePixels()
        page_width_mm, page_height_mm = self.GetPageSizeMM()
        _, ppi_printer_y = self.GetPPIPrinter()
        _, ppi_screen_y = self.GetPPIScreen()
        ppi_printer_y = ppi_printer_y or ppi_screen_y or 96
        ppi_screen_y = ppi_screen_y or 96
        page_width = max(1, page_width)
        page_height = max(1, page_height)
        page_width_mm = page_width_mm or 1
        page_height_mm = page_height_mm or 1

        dc = self.GetDC()
        dc_width, dc_height = dc.GetSize()
        dc.SetUserScale(float(dc_width) / page_width,
                        float(dc_height) / page_height)

        margin_left, margin_top = self._printer.GetPageSetupData().\
            GetMarginTopLeft()
        margin_right, margin_bottom = self._printer.GetPageSetupData().\
            GetMarginBottomRight()
        ppmm_x = float(page_width) / page_width_mm
        ppmm_y = float(page_height) / page_height_mm
        area_width_mm = page_width_mm - margin_left - margin_right
        area_height_mm = page_height_mm - margin_top - margin_bottom
        area_width = max(1, int(ppmm_x * area_width_mm))
        area_height = max(1, int(ppmm_y * area_height_mm))
        offset_x = int(ppmm_x * margin_left)
        offset_y = int(ppmm_y * margin_top)

        font_scale = float(ppi_printer_y) / ppi_screen_y
        pixel_scale = float(ppi_printer_y) / 96.0
        return (dc, pixel_scale, font_scale, area_width, area_height,
                offset_x, offset_y)

    def OnPreparePrinting(self):
        self._pages = []
        (dc, pixel_scale, font_scale, area_width, area_height, offset_x,
         offset_y) = self._page_metrics()
        self._metrics = (pixel_scale, font_scale, area_width, area_height,
                         offset_x, offset_y)
        renderer = self._renderer(dc, pixel_scale, font_scale,
                                  area_width, area_height)

        def table_height(memories):
            markup = self._printer._table_markup(
                memories, self._col_defs, self._expander, self._widths)
            renderer.SetHtmlText('<html><body>%s</body></html>' % markup)
            return renderer.GetTotalHeight()

        header_height = table_height([])
        page = []
        used_height = header_height
        for mem in self._memories:
            row_height = max(1, table_height([mem]) - header_height)
            if page and used_height + row_height > area_height:
                self._pages.append(page)
                page = []
                used_height = header_height
            page.append(mem)
            used_height += row_height

        if page:
            self._pages.append(page)
        elif not self._pages:
            self._pages.append([])

    def GetPageInfo(self):
        pages = max(1, len(self._pages))
        return 1, pages, 1, pages

    def HasPage(self, page):
        return 1 <= page <= len(self._pages)

    def OnPrintPage(self, page):
        if not self.HasPage(page):
            return False

        (pixel_scale, font_scale, area_width, area_height, offset_x,
         offset_y) = self._metrics
        dc = self.GetDC()
        if not dc or not dc.IsOk():
            return False
        page_width, page_height = self.GetPageSizePixels()
        page_width = max(1, page_width)
        page_height = max(1, page_height)
        dc_width, dc_height = dc.GetSize()
        dc.SetBackgroundMode(wx.BRUSHSTYLE_TRANSPARENT)
        dc.SetUserScale(float(dc_width) / page_width,
                        float(dc_height) / page_height)
        renderer = self._renderer(dc, pixel_scale, font_scale,
                                  area_width, area_height)
        markup = self._printer._table_markup(
            self._pages[page - 1], self._col_defs, self._expander,
            self._widths)
        renderer.SetHtmlText('<html><body>%s</body></html>' % markup)
        renderer.Render(offset_x, offset_y)
        return True
