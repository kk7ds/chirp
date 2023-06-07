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

import platform

import wx
import wx.grid

from chirp import chirp_common
from chirp.wxui import common
from chirp.wxui import config
from chirp.wxui import memedit

CONF = config.get()


if platform.system() == 'Linux':
    BANK_SET_VALUE = 'X'
else:
    BANK_SET_VALUE = '1'


class ChirpBankToggleColumn(memedit.ChirpMemoryColumn):
    def __init__(self, bank, radio):
        self.bank = bank
        super().__init__('bank-%s' % bank.get_index(), radio)

    @property
    def label(self):
        return '%s(%s)' % (self.bank.get_name(),
                           self.bank.get_index())

    def hidden_for(self, memory):
        return False

    def get_editor(self):
        return wx.grid.GridCellBoolEditor()

    def get_renderer(self):
        return wx.grid.GridCellBoolRenderer()


class ChirpBankIndexColumn(memedit.ChirpMemoryColumn):
    def __init__(self, model, radio):
        self.model = model
        super().__init__('bank_index', radio)

    @property
    def label(self):
        return _('Index')

    def get_editor(self):
        lower, upper = self.model.get_index_bounds()
        return wx.grid.GridCellNumberEditor(lower, upper)


class ChirpBankEdit(common.ChirpEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpBankEdit, self).__init__(*a, **k)

        self._radio = radio
        self._features = radio.get_features()
        self._bankmodel = radio.get_bank_model()

        self._col_defs = self._setup_columns()

        self._grid = memedit.ChirpMemoryGrid(self)
        self._grid.CreateGrid(
            self._features.memory_bounds[1] - self._features.memory_bounds[0] +
            1, len(self._col_defs))
        # GridSelectNone only available in >=4.2.0
        if hasattr(wx.grid.Grid, 'GridSelectNone'):
            self._grid.SetSelectionMode(wx.grid.Grid.GridSelectNone)
        self._grid.DisableDragRowSize()
        self._grid.SetFocus()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._grid, proportion=1, flag=wx.EXPAND)
        self.SetSizer(sizer)

        self._fixed_font = wx.Font(pointSize=10,
                                   family=wx.FONTFAMILY_TELETYPE,
                                   style=wx.FONTSTYLE_NORMAL,
                                   weight=wx.FONTWEIGHT_NORMAL)
        self._variable_font = self._grid.GetDefaultCellFont()
        self.update_font(False)

        for col, col_def in enumerate(self._col_defs):
            self._grid.SetColLabelValue(col, col_def.label)
            attr = wx.grid.GridCellAttr()
            if platform.system() != 'Linux':
                attr.SetEditor(col_def.get_editor())
                attr.SetRenderer(col_def.get_renderer())
            attr.SetReadOnly(not (isinstance(col_def, ChirpBankToggleColumn) or
                                  isinstance(col_def, ChirpBankIndexColumn)))
            attr.SetAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
            self._grid.SetColAttr(col, attr)

        self._memory_cache = {}

        self._grid.Bind(wx.grid.EVT_GRID_CELL_CHANGING, self._index_changed)
        self._grid.Bind(wx.grid.EVT_GRID_CELL_LEFT_CLICK, self._memory_changed)
        self._grid.Bind(wx.grid.EVT_GRID_LABEL_LEFT_DCLICK, self._label_click)
        self._grid.GetGridColLabelWindow().Bind(wx.EVT_MOTION,
                                                self._colheader_mouseover)

    def update_font(self, refresh=True):
        fixed = CONF.get_bool('font_fixed', 'state', False)
        large = CONF.get_bool('font_large', 'state', False)
        if fixed:
            font = self._fixed_font
        else:
            font = self._variable_font
        if large:
            font = wx.Font(font)
            font.SetPointSize(font.PointSize + 2)
        self._grid.SetDefaultCellFont(font)
        if refresh:
            self.refresh()
            wx.CallAfter(self._grid.AutoSizeColumns, setAsMin=False)
            wx.CallAfter(self._grid.AutoSizeRows, setAsMin=False)

    def selected(self):
        self.refresh_memories()

    def refresh_memories(self):
        self._memory_cache = {}
        lower, upper = self._features.memory_bounds

        for i in range(lower, upper + 1):
            mem = self._radio.get_memory(i)
            self._refresh_memory(mem)

        wx.CallAfter(self._grid.AutoSizeColumns, setAsMin=True)

    def _setup_columns(self):
        defs = [
            memedit.ChirpFrequencyColumn('freq', self._radio),
            memedit.ChirpMemoryColumn('name', self._radio),
        ]
        if isinstance(self._bankmodel,
                      chirp_common.MappingModelIndexInterface):
            defs.append(ChirpBankIndexColumn(self._bankmodel, self._radio))

        self._meta_cols = len(defs)

        self._bank_indexes = {}
        self._bank_index_order = []
        for bank in self._bankmodel.get_mappings():
            self._bank_index_order.append(bank.get_index())
            self._bank_indexes[bank.get_index()] = bank
            defs.append(ChirpBankToggleColumn(bank, self._radio))

        return defs

    def col2bank(self, col):
        if col < self._meta_cols:
            raise RuntimeError('Error: column %i is not a bank' % col)
        return col - self._meta_cols

    def bank2col(self, bank):
        return bank + self._meta_cols

    def row2mem(self, row):
        return row + self._features.memory_bounds[0]

    def mem2row(self, mem):
        return mem - self._features.memory_bounds[0]

    def _colheader_mouseover(self, event):
        x = event.GetX()
        y = event.GetY()
        col = self._grid.XToCol(x, y)
        tip = ''
        if col >= self._meta_cols:
            bank = self._bankmodel.get_mappings()[self.col2bank(col)]
            if hasattr(bank, 'set_name'):
                tip = _('Double-click to change bank name')
        self._grid.GetGridColLabelWindow().SetToolTip(tip)

    def _label_click(self, event):
        row = event.GetRow()
        col = event.GetCol()
        if row != -1:
            # Row labels do not change
            return
        bank = self._bankmodel.get_mappings()[self.col2bank(col)]
        if not hasattr(bank, 'set_name'):
            return
        d = wx.TextEntryDialog(self,
                               _('Enter a new name for bank %s:') % (
                                   bank.get_index()),
                               _('Rename bank'))
        d.SetValue(bank.get_name())
        if d.ShowModal() == wx.ID_OK:
            self.change_bank_name(col, bank, d.GetValue())
            wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def change_bank_name(self, col, bank, name):
        bank.set_name(name)
        # Refresh the column from the col def to make sure it stuck
        col_def = self._col_defs[col]
        self._grid.SetColLabelValue(col, col_def.label)
        wx.CallAfter(self._grid.AutoSizeColumns, setAsMin=True)

    @common.error_proof()
    def _index_changed(self, event):
        row = event.GetRow()
        col = event.GetCol()
        value = event.GetString()
        if isinstance(self._col_defs[col], ChirpBankIndexColumn):
            self._change_memory_index(self.row2mem(row), int(value))

    def _change_memory_index(self, number, index):
        for i, bank_index in enumerate(self._bank_index_order):
            if self._grid.GetCellValue(self.mem2row(number),
                                       self.bank2col(i)) == BANK_SET_VALUE:
                member_bank = self._bank_indexes[bank_index]
                break
        else:
            raise Exception(_('Memory must be in a bank to be edited'))

        self._bankmodel.set_memory_index(self._memory_cache[number],
                                         member_bank,
                                         index)

        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    @common.error_proof()
    def _memory_changed(self, event):
        row = event.GetRow()
        col = event.GetCol()
        value = self._grid.GetCellValue(row, col)

        if isinstance(self._col_defs[col], ChirpBankIndexColumn):
            event.Skip()
        elif col < self._meta_cols:
            event.Skip()
        else:
            self._change_memory_mapping(self.row2mem(row),
                                        self.col2bank(col),
                                        value != BANK_SET_VALUE)

    def _change_memory_mapping(self, number, bank, present):
        mem = self._memory_cache[number]
        bank = self._bank_indexes[self._bank_index_order[bank]]
        if present:
            self._bankmodel.add_memory_to_mapping(mem, bank)
        else:
            self._bankmodel.remove_memory_from_mapping(mem, bank)

        self._refresh_memory(mem)

        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    @common.error_proof()
    def _refresh_memory(self, mem):
        self._memory_cache[mem.number] = mem
        self._grid.SetRowLabelValue(self.mem2row(mem.number),
                                    '%i' % mem.number)

        bank_index = None
        member = [bank.get_index()
                  for bank in self._bankmodel.get_memory_mappings(mem)]
        for i, bank in enumerate(self._bank_indexes.values()):
            present = bank.get_index() in member and not mem.empty
            self._grid.SetCellValue(self.mem2row(mem.number),
                                    self.bank2col(i),
                                    present and BANK_SET_VALUE or '')
            if present and isinstance(self._bankmodel,
                                      chirp_common.MappingModelIndexInterface):
                # NOTE: if this is somehow an indexed many-to-one model,
                # we will only get the last index!
                bank_index = self._bankmodel.get_memory_index(mem, bank)

        for i in range(0, self._meta_cols):
            meta_col = self._col_defs[i]
            if meta_col.name == 'freq':
                freq = '' if mem.empty else chirp_common.format_freq(mem.freq)
                self._grid.SetCellValue(
                    self.mem2row(mem.number), i, freq)
            elif meta_col.name == 'name':
                self._grid.SetCellValue(
                    self.mem2row(mem.number),
                    i, '' if mem.empty else mem.name)
            elif meta_col.name == 'bank_index' and bank_index is not None:
                self._grid.SetCellValue(
                    self.mem2row(mem.number),
                    i, '' if mem.empty else '%i' % bank_index)


class ChirpBankEditSync(ChirpBankEdit, common.ChirpSyncEditor):
    pass
