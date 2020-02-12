import functools
import logging
import pickle

import wx
import wx.lib.newevent
import wx.grid
import wx.propgrid

from chirp import chirp_common
from chirp.ui import config
from chirp.wxui import common
from chirp.wxui import developer

LOG = logging.getLogger(__name__)
CONF = config.get()


class ChirpMemoryColumn(object):
    NAME = None
    DEFAULT = ''

    def __init__(self, name, radio):
        """
        :param name: The name on the Memory object that this represents
        """
        self._name = name
        self._radio = radio
        self._features = radio.get_features()

    @property
    def label(self):
        return self.NAME or self._name.title()

    def hidden_for(self, memory):
        return False

    @property
    def valid(self):
        if self._name in ['freq', 'rtone']:
            return True
        to_try = ['has_%s', 'valid_%ss', 'valid_%ses', 'valid_%s_levels']
        for thing in to_try:
            try:
                return bool(self._features[thing % self._name])
            except KeyError:
                pass

        LOG.error('Unsure if %r is valid' % self._name)
        return True

    def _render_value(self, memory, value):
        if value is []:
            raise Exception('Found empty list value for %s: %r' % (
                self._name, value))
        return str(value)

    def value(self, memory):
        return getattr(memory, self._name)

    def render_value(self, memory):
        if memory.empty:
            return ''
        if self.hidden_for(memory):
            return ''
        return self._render_value(memory, self.value(memory))

    def _digest_value(self, memory, input_value):
        return str(input_value)

    def digest_value(self, memory, input_value):
        setattr(memory, self._name, self._digest_value(memory, input_value))

    def get_editor(self):
        return wx.grid.GridCellTextEditor()

    def get_propeditor(self, memory):
        class ChirpStringProperty(wx.propgrid.StringProperty):
            def ValidateValue(myself, value, validationInfo):
                try:
                    self._digest_value(memory, value)
                    return True
                except ValueError:
                    validationInfo.SetFailureMessage(
                        'Invalid value: %r' % value)
                    return False
                except Exception as e:
                    LOG.exception('Failed to validate %r for property %s' % (
                        value, self._name))
                    validationInfo.SetFailureMessage(
                        'Invalid value: %r' % value)
                    return False

        editor = ChirpStringProperty(self.label, self._name)
        editor.SetValue(self.render_value(memory))
        return editor


class ChirpFrequencyColumn(ChirpMemoryColumn):
    DEFAULT = 0
    @property
    def label(self):
        if self._name == 'offset':
            return 'Offset'
        else:
            return 'Frequency'

    def hidden_for(self, memory):
        return self._name == 'offset' and not memory.duplex

    def _render_value(self, memory, value):
        if not value:
            value = 0
        return '%.5f' % (value / 1000000.0)

    def _digest_value(self, memory, input_value):
        if not input_value.strip():
            input_value = 0
        return int(chirp_common.to_MHz(float(input_value)))


class ChirpToneColumn(ChirpMemoryColumn):
    def __init__(self, name, radio):
        super(ChirpToneColumn, self).__init__(name, radio)
        self._choices = chirp_common.TONES
        self._str_choices = [str(x) for x in self._choices]

    @property
    def label(self):
        if self._name == 'rtone':
            return 'Tone'
        else:
            return 'ToneSql'

    def hidden_for(self, memory):
        return (
            (self._name == 'rtone' and memory.tmode not in ('Tone', 'Cross'))
            or
            (self._name == 'ctone' and memory.tmode not in ('TSQL', 'Cross')))

    def _digest_value(self, memory, input_value):
        return float(input_value)

    def get_editor(self):
        return wx.grid.GridCellChoiceEditor(['%.1f' % t
                                             for t in chirp_common.TONES])

    def get_propeditor(self, memory):
        current = self.value(memory)
        return wx.propgrid.EnumProperty(self.label, self._name,
                                        self._str_choices,
                                        range(len(self._choices)),
                                        self._choices.index(current))


class ChirpChoiceColumn(ChirpMemoryColumn):
    def __init__(self, name, radio, choices):
        super(ChirpChoiceColumn, self).__init__(name, radio)
        self._choices = choices
        self._str_choices = [str(x) for x in choices]

    def _digest_value(self, memory, input_value):
        idx = self._str_choices.index(input_value)
        return self._choices[idx]

    def get_editor(self):
        return wx.grid.GridCellChoiceEditor(self._str_choices)

    def get_propeditor(self, memory):
        current = self._render_value(memory, self.value(memory))
        try:
            cur_index = self._choices.index(current)
        except ValueError:
            # This means the memory has some value set that the radio
            # does not support, like the default cross_mode not being
            # in rf.valid_cross_modes. This is likely because the memory
            # just doesn't have that value set, so take the first choice
            # in this case.
            cur_index = 0
        return wx.propgrid.EnumProperty(self.label, self._name,
                                        self._str_choices,
                                        range(len(self._str_choices)),
                                        cur_index)


class ChirpDTCSColumn(ChirpChoiceColumn):
    def __init__(self, name, radio):
        dtcs_codes = ['%03i' % code for code in chirp_common.DTCS_CODES]
        super(ChirpDTCSColumn, self).__init__(name, radio,
                                              dtcs_codes)

    @property
    def label(self):
        if self._name == 'dtcs':
            return 'DTCS'
        elif self._name == 'rx_dtcs':
            return 'RX DTCS'
        else:
            return 'ErrDTCS'

    def _digest_value(self, memory, input_value):
        return int(input_value)

    def _render_value(self, memory, value):
        return '%03i' % value

    def hidden_for(self, memory):
        return (
            (self._name == 'dtcs' and not (
                memory.tmode == 'DTCS' or (memory.tmode == 'Cross' and
                                           'DTCS->' in memory.cross_mode)))
            or
            (self._name == 'rx_dtcs' and not (
                memory.tmode == 'Cross' and '>DTCS' in memory.cross_mode)))


class ChirpCrossModeColumn(ChirpChoiceColumn):
    def __init__(self, name, radio):
        rf = radio.get_features()
        super(ChirpCrossModeColumn, self).__init__(name, radio,
                                                   rf.valid_cross_modes)

    @property
    def label(self):
        return 'Cross mode'

    def hidden_for(self, memory):
        return memory.tmode != 'Cross'


class ChirpMemEdit(common.ChirpEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpMemEdit, self).__init__(*a, **k)

        self._radio = radio
        self._features = self._radio.get_features()

        #self._radio.subscribe(self._job_done)
        self._jobs = {}
        self._memory_cache = {}

        self._col_defs = self._setup_columns()

        self._grid = wx.grid.Grid(self)
        self._grid.CreateGrid(self._features.memory_bounds[1] +
                              len(self._features.valid_special_chans) + 1,
                              len(self._col_defs))
        self._grid.SetSelectionMode(wx.grid.Grid.SelectRows)

        self._fixed_font = wx.Font(pointSize=10,
                                   family=wx.FONTFAMILY_TELETYPE,
                                   style=wx.FONTSTYLE_NORMAL,
                                   weight=wx.FONTWEIGHT_NORMAL)

        for col, col_def in enumerate(self._col_defs):
            if not col_def.valid:
                self._grid.HideCol(col)
            else:
                self._grid.SetColLabelValue(col, col_def.label)
                attr = wx.grid.GridCellAttr()
                attr.SetEditor(col_def.get_editor())
                attr.SetFont(self._fixed_font)
                self._grid.SetColAttr(col, attr)
                self._grid.SetColMinimalWidth(col, 75)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._grid, 1, wx.EXPAND)
        self.SetSizer(sizer)

        wx.CallAfter(self._grid.AutoSizeColumns, setAsMin=False)

        self._grid.Bind(wx.grid.EVT_GRID_CELL_CHANGING,
                        self._memory_edited)
        self._grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED,
                        self._memory_changed)
        self._grid.Bind(wx.grid.EVT_GRID_CELL_RIGHT_CLICK,
                        self._memory_rclick)

        # For resize calculations
        self._dc = wx.ScreenDC()
        self._dc.SetFont(self._fixed_font)

    def _setup_columns(self):
        defs = [
            ChirpFrequencyColumn('freq', self._radio),
            ChirpMemoryColumn('name', self._radio),
            ChirpChoiceColumn('tmode', self._radio,
                              self._features.valid_tmodes),
            ChirpToneColumn('rtone', self._radio),
            ChirpToneColumn('ctone', self._radio),
            ChirpDTCSColumn('dtcs', self._radio),
            ChirpDTCSColumn('rx_dtcs', self._radio),
            ChirpChoiceColumn('duplex', self._radio,
                              self._features.valid_duplexes),
            ChirpFrequencyColumn('offset', self._radio),
            ChirpChoiceColumn('mode', self._radio,
                              self._features.valid_modes),
            ChirpChoiceColumn('tuning_step', self._radio,
                              self._features.valid_tuning_steps),
            ChirpChoiceColumn('skip', self._radio,
                              self._features.valid_skips),
            ChirpCrossModeColumn('cross_mode', self._radio),
            ChirpChoiceColumn('power', self._radio,
                              self._features.valid_power_levels),
            ChirpMemoryColumn('comment', self._radio),
        ]
        return defs

    def refresh_memory(self, memory):
        self._memory_cache[memory.number] = memory

        row = memory.number - self._features.memory_bounds[0]

        if memory.extd_number:
            self._grid.SetRowLabelValue(row, memory.extd_number)
        else:
            self._grid.SetRowLabelValue(row, str(memory.number))

        for col, col_def in enumerate(self._col_defs):
            self._grid.SetCellValue(row, col, col_def.render_value(memory))

    def refresh(self):
        for i in range(*self._features.memory_bounds):
            try:
                m = self._radio.get_memory(i)
            except Exception as e:
                LOG.exception('Failure retreiving memory %i from %s' % (
                    i, '%s %s %s' % (self._radio.VENDOR,
                                     self._radio.MODEL,
                                     self._radio.VARIANT)))
                continue
            self.refresh_memory(m)

        return

        for i in self._features.valid_special_chans:
            m = self._radio.get_memory(i)
            self.refresh_memory(m)

    def _memory_edited(self, event):
        """
        Called when the memory row in the UI is edited.
        Writes the memory to the radio and displays an error if needed.
        """
        row = event.GetRow()
        col = event.GetCol()
        val = event.GetString()

        col_def = self._col_defs[col]

        try:
            mem = self._memory_cache[row + self._features.memory_bounds[0]]
        except KeyError:
            wx.MessageBox('Unable to edit memory before radio is loaded')
            event.Veto()
            return

        try:
            if col_def.label == 'Name':
                val = self._radio.filter_name(val)
            col_def.digest_value(mem, val)
            mem.empty = False
            job = self._radio.set_memory(mem)
        except Exception as e:
            LOG.exception('Failed to edit memory')
            wx.MessageBox('Invalid edit: %s' % e, 'Error')
            event.Veto()
        else:
            LOG.debug('Memory %i changed, column: %i:%s' % (row, col, mem))

        wx.CallAfter(self._resize_col_after_edit, row, col)

    def _resize_col_after_edit(self, row, col):
        """Resize the column if the text in row,col does not fit."""
        size = self._dc.GetTextExtent(self._grid.GetCellValue(row, col))
        padsize = size[0] + 20
        if padsize > self._grid.GetColSize(col):
            self._grid.SetColSize(col, padsize)

    def _memory_changed(self, event):
        """
        Called when the memory in the UI has been changed.
        Responsible for re-requesting the memory from the radio and updating
        the UI accordingly.
        Also provides the trigger to the editorset that we have changed.
        """
        row = event.GetRow()
        mem = self._radio.get_memory(row + self._features.memory_bounds[0])
        self.refresh_memory(mem)
        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def delete_memory_at(self, row, event):
        number = row + self._features.memory_bounds[0]
        mem = self._radio.get_memory(number)
        mem.empty = True
        self._radio.set_memory(mem)
        self.refresh_memory(mem)
        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def _delete_memories_at(self, rows, event):
        for row in rows:
            self.delete_memory_at(row, event)

    def _memory_rclick(self, event):
        menu = wx.Menu()
        selected_rows = self._grid.GetSelectedRows()

        props_item = wx.MenuItem(menu, wx.NewId(), 'Properties')
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._mem_properties, selected_rows),
                  props_item)
        menu.Append(props_item)

        if len(selected_rows) > 1:
            del_item = wx.MenuItem(menu, wx.NewId(),
                                   'Delete %i Memories' % len(selected_rows))
            to_delete = selected_rows
        else:
            del_item = wx.MenuItem(menu, wx.NewId(), 'Delete')
            to_delete = [event.GetRow()]
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._delete_memories_at, to_delete),
                  del_item)
        menu.Append(del_item)

        if CONF.get_bool('developer', 'state'):
            menu.Append(wx.MenuItem(menu, wx.ID_SEPARATOR))

            raw_item = wx.MenuItem(menu, wx.NewId(), 'Show Raw Memory')
            self.Bind(wx.EVT_MENU,
                      functools.partial(self._mem_showraw, event.GetRow()),
                      raw_item)
            menu.Append(raw_item)

            if len(selected_rows) == 2:
                diff_item = wx.MenuItem(menu, wx.NewId(), 'Diff Raw Memories')
                self.Bind(wx.EVT_MENU,
                          functools.partial(self._mem_diff, selected_rows),
                          diff_item)
                menu.Append(diff_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def row2mem(self, row):
        return row + self._features.memory_bounds[0]

    def _mem_properties(self, rows, event):
        memories = [
            self._radio.get_memory(self.row2mem(row))
            for row in rows]
        with ChirpMemPropDialog(memories, self) as d:
            if d.ShowModal() == wx.ID_OK:
                for memory in d._memories:
                    self._radio.set_memory(memory)
                    self.refresh_memory(memory)

    def _mem_showraw(self, row, event):
        mem = self._radio.get_raw_memory(self.row2mem(row))
        with developer.MemoryDialog(mem, self) as d:
            d.ShowModal()

    def _mem_diff(self, rows, event):
        mem_a = self._radio.get_raw_memory(self.row2mem(rows[0]))
        mem_b = self._radio.get_raw_memory(self.row2mem(rows[1]))
        with developer.MemoryDialog((mem_a, mem_b), self) as d:
            d.ShowModal()

    def cb_copy(self, cut=False):
        rows = self._grid.GetSelectedRows()
        offset = self._features.memory_bounds[0]
        mems = []
        for row in rows:
            mem = self._radio.get_memory(row + offset)
            # We can't pickle settings, nor would they apply if we
            # paste across models
            mem.extra = []
            mems.append(mem)
        data = wx.CustomDataObject(common.CHIRP_DATA_MEMORY)
        data.SetData(pickle.dumps(mems))
        for mem in mems:
            if cut:
                self._radio.erase_memory(mem.number)
                mem = self._radio.get_memory(mem.number)
                self.refresh_memory(mem)
        return data

    def _cb_paste_memories(self, mems):
        try:
            row = self._grid.GetSelectedRows()[0]
        except IndexError:
            LOG.info('No row selected for paste')
            return

        for mem in mems:
            mem.empty = False
            mem.number = row + self._features.memory_bounds[0]
            row += 1
            self._radio.set_memory(mem)
            self.refresh_memory(mem)

    def cb_paste(self, data):
        if data.GetFormat() == common.CHIRP_DATA_MEMORY:
            mems = pickle.loads(data.GetData().tobytes())
            self._cb_paste_memories(mems)
        elif data.GetFormat() == wx.DF_UNICODETEXT:
            LOG.debug('FIXME: handle pasted text: %r' % data.GetText())
        else:
            LOG.warning('Unknown data format %s' % data.GetFormat().Type)

    def select_all(self):
        self._grid.SelectAll()


class ChirpMemPropDialog(wx.Dialog):
    def __init__(self, memories, memedit, *a, **k):
        if len(memories) == 1:
            title = 'Edit details for memory %i' % memories[0].number
        else:
            title = 'Edit details for %i memories' % len(memories)

        super(ChirpMemPropDialog, self).__init__(
            memedit, *a, title=title, **k)

        self.Centre()

        self._memories = memories
        self._col_defs = memedit._col_defs

        # The first memory sets the defaults
        memory = self._memories[0]

        self._tabs = wx.Notebook(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        vbox.Add(self._tabs, 1, wx.EXPAND)

        self._pg = wx.propgrid.PropertyGrid(self._tabs)
        self._tabs.InsertPage(0, self._pg, 'Values')

        if memory.extra:
            self._tabs.InsertPage(1, common.ChirpSettingGrid(memory.extra,
                                                             self._tabs),
                                  'Extra')

        for coldef in memedit._col_defs:
            if coldef.valid:
                self._pg.Append(coldef.get_propeditor(memory))

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(wx.Button(self, wx.ID_OK))
        hbox.Add(wx.Button(self, wx.ID_CANCEL))

        vbox.Add(hbox, 0, wx.ALIGN_RIGHT|wx.ALL, border=10)

        self.Bind(wx.EVT_BUTTON, self._button)

    def _col_def_by_name(self, name):
        for coldef in self._col_defs:
            if coldef._name == name:
                return coldef
        LOG.error('No column definition for %s' % name)

    def _make_memories(self):
        memories = [memory.dupe() for memory in self._memories]

        for mem in memories:
            for prop in self._pg._Items():
                name = prop.GetName()

                coldef = self._col_def_by_name(name)
                value = prop.GetValueAsString()
                value = coldef._digest_value(mem, value)

                if (getattr(self._memories[0], name) == value):
                    LOG.debug('Skipping unchanged field %s' % name)
                    continue

                LOG.debug('Value for %s is %r' % (name, value))
                setattr(mem, prop.GetName(), value)

            if self._tabs.GetPageCount() == 2:
                extra = self._tabs.GetPage(1).get_values()
                for setting in mem.extra:
                    name = setting.get_name()
                    try:
                        setting.value = extra[name]
                    except KeyError:
                        raise
                        LOG.warning('Missing setting %r' % name)
                        continue

        return memories

    def _button(self, event):
        button_id = event.GetEventObject().GetId()
        if button_id == wx.ID_OK:
            self._memories = self._make_memories()

        self.EndModal(button_id)
