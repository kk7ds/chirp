import functools
import logging
import pickle

import wx
import wx.lib.newevent
import wx.grid
import wx.propgrid

from chirp import chirp_common
from chirp.wxui import common

LOG = logging.getLogger(__name__)


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
        to_try = ['has_%s', 'valid_%ss', 'valid_%ses']
        for thing in to_try:
            try:
                return bool(self._features[thing % self._name])
            except KeyError:
                pass

        LOG.error('Unsure if %r is valid' % self._name)
        return True

    def _render_value(self, memory, value):
        if value == []:
            raise Exception('Found empty list value for %s' % self._name)
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
        class ChirpPropertyEditor(wx.propgrid.PGProperty):
            def DoGetEditorClass(myself):
                return wx.propgrid.PropertyGridInterface.GetEditorByName(
                    'TextCtrl')

            def ValueToString(myself, value, flags):
                r = self._render_value(memory, value)
                return r

            def StringToValue(myself, string, *a, flags=0, **k):
                if string == '':
                    string = str(self.DEFAULT)
                r = self._digest_value(memory, string)
                return (True, r)

        pe = ChirpPropertyEditor(self.label, self._name)
        v = self.render_value(memory)
        pe.SetValueFromString(v)
        return pe


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
        return '%.5f' % (value / 1000000.0)

    def _digest_value(self, memory, input_value):
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
        return self._choices[self._str_choices.index(input_value)]

    def get_editor(self):
        return wx.grid.GridCellChoiceEditor(self._str_choices)

    def get_propeditor(self, memory):
        current = self.value(memory)
        return wx.propgrid.EnumProperty(self.label, self._name,
                                        self._str_choices,
                                        range(len(self._str_choices)),
                                        self._choices.index(current))


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

        for col, col_def in enumerate(self._col_defs):
            if not col_def.valid:
                self._grid.HideCol(col)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._grid, 1, wx.EXPAND)
        self.SetSizer(sizer)

        for i, col_def in enumerate(self._col_defs):
            self._grid.SetColLabelValue(i, col_def.label)

        self._grid.Bind(wx.grid.EVT_GRID_CELL_CHANGING,
                        self._memory_edited)
        self._grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED,
                        self._memory_changed)
        self._grid.Bind(wx.grid.EVT_GRID_CELL_RIGHT_CLICK,
                        self._memory_rclick)

    def _setup_columns(self):
        defs = [
            ChirpFrequencyColumn('freq', self._radio),
            ChirpMemoryColumn('name', self._radio),
            ChirpChoiceColumn('tmode', self._radio,
                              self._features.valid_tmodes),
            ChirpToneColumn('rtone', self._radio),
            ChirpToneColumn('ctone', self._radio),
            ChirpChoiceColumn('duplex', self._radio,
                              self._features.valid_duplexes),
            ChirpFrequencyColumn('offset', self._radio),
            ChirpChoiceColumn('mode', self._radio,
                              self._features.valid_modes),
            ChirpChoiceColumn('tuning_step', self._radio,
                              self._features.valid_tuning_steps),
            ChirpChoiceColumn('skip', self._radio,
                              self._features.valid_skips),
            ChirpMemoryColumn('comment', self._radio),
        ]
        return defs
    def refresh_memory(self, memory):
        self._memory_cache[memory.number] = memory

        row = memory.number - self._features.memory_bounds[0]

        if memory.extd_number:
            self._grid.SetRowLabelValue(row, memory.extd_number)

        for col, col_def in enumerate(self._col_defs):
            self._grid.SetCellValue(row, col, col_def.render_value(memory))

            # Only do this the first time
            editor = col_def.get_editor()
            self._grid.SetCellEditor(row, col, editor)

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
            col_def.digest_value(mem, val)
            mem.empty = False
            job = self._radio.set_memory(mem)
        except Exception as e:
            wx.MessageBox('Invalid edit: %s' % e, 'Error')
            event.Veto()
        else:
            LOG.debug('Memory %i changed, column: %i:%s' % (row, col, mem))

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

    def _memory_rclick(self, event):
        menu = wx.Menu()

        del_item = wx.MenuItem(menu, wx.NewId(), 'Delete')
        self.Bind(wx.EVT_MENU,
                  functools.partial(self.delete_memory_at, event.GetRow()),
                  del_item)
        menu.AppendItem(del_item)

        props_item = wx.MenuItem(menu, wx.NewId(), 'Properties')
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._mem_properties, event.GetRow()),
                  props_item)
        menu.AppendItem(props_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def _mem_properties(self, row, event):
        number = row + self._features.memory_bounds[0]
        mem = self._radio.get_memory(number)
        with ChirpMemPropDialog(mem, self) as d:
            if d.ShowModal() == wx.ID_OK:
                self._radio.set_memory(d._memory)
                self.refresh_memory(d._memory)

    def cb_copy(self, cut=False):
        rows = self._grid.GetSelectedRows()
        offset = self._features.memory_bounds[0]
        mems = [self._radio.get_memory(row + offset) for row in rows]
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


class ChirpMemPropDialog(wx.Dialog):
    def __init__(self, memory, memedit, *a, **k):
        super(ChirpMemPropDialog, self).__init__(
            memedit, *a,
            title='Edit details for memory %i' % memory.number,
            **k)
        self._memory = memory
        self._col_defs = memedit._col_defs

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

    def _make_memory(self):
        mem = self._memory.dupe()
        for prop in self._pg._Items():
            if isinstance(prop, wx.propgrid.EnumProperty):
                coldef = self._col_def_by_name(prop.GetName())
                value = coldef._choices[prop.GetValue()]
            else:
                value = prop.GetValue()
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

        return mem

    def _button(self, event):
        button_id = event.GetEventObject().GetId()
        if button_id == wx.ID_OK:
            self._memory = self._make_memory()

        self.EndModal(button_id)
