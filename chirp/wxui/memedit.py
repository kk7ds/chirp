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

import functools
import logging
import pickle
import platform

import wx
import wx.lib.newevent
import wx.grid
import wx.propgrid
import wx.lib.mixins.gridlabelrenderer as glr

from chirp import chirp_common
from chirp import bandplan
from chirp.drivers import generic_csv
from chirp import errors
from chirp import import_logic
from chirp import settings
from chirp.wxui import config
from chirp.wxui import common
from chirp.wxui import developer

LOG = logging.getLogger(__name__)
CONF = config.get()


class ChirpMemoryGrid(wx.grid.Grid, glr.GridWithLabelRenderersMixin):
    def __init__(self, *a, **k):
        wx.grid.Grid.__init__(self, *a, **k)
        glr.GridWithLabelRenderersMixin.__init__(self)


class ChirpRowLabelRenderer(glr.GridDefaultRowLabelRenderer):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.bgcolor = None

    def set_error(self):
        self.bgcolor = '#FF0000'

    def set_progress(self):
        self.bgcolor = '#98FB98'

    def clear_error(self):
        self.bgcolor = None

    def Draw(self, grid, dc, rect, row):
        if self.bgcolor:
            dc.SetBrush(wx.Brush(self.bgcolor))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)
        hAlign, vAlign = grid.GetRowLabelAlignment()
        text = grid.GetRowLabelValue(row)
        self.DrawBorder(grid, dc, rect)
        self.DrawText(grid, dc, rect, text, hAlign, vAlign)


class ChirpMemoryColumn(object):
    DEFAULT = ''

    def __init__(self, name, radio, label=None):
        """
        :param name: The name on the Memory object that this represents
        :param label: Static label override
        """
        self._name = name
        self._label = label or _(name.title())
        self._radio = radio
        self._features = radio.get_features()

    @property
    def name(self):
        return self._name

    @property
    def label(self):
        return self._label.replace('_', ' ').replace(' ', '\n', 1)

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
            raise Exception(
                _('Found empty list value for %(name)s: %(value)r' % {
                    'name': self._name,
                    'value': value}))
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

    def get_renderer(self):
        return None

    def get_propeditor(self, memory):
        class ChirpStringProperty(wx.propgrid.StringProperty):
            def ValidateValue(myself, value, validationInfo):
                try:
                    self._digest_value(memory, value)
                    return True
                except ValueError:
                    validationInfo.SetFailureMessage(
                        _('Invalid value: %r') % value)
                    return False
                except Exception:
                    LOG.exception('Failed to validate %r for property %s' % (
                        value, self._name))
                    validationInfo.SetFailureMessage(
                        _('Invalid value: %r') % value)
                    return False

        editor = ChirpStringProperty(self.label.replace('\n', ' '),
                                     self._name)
        editor.SetValue(self.render_value(memory))
        return editor

    def get_by_prompt(self, parent, memory, message):
        common.error_proof.show_error(
            'Internal error: unable to prompt for %s' % self._name)


class ChirpFrequencyColumn(ChirpMemoryColumn):
    DEFAULT = 0

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._wants_split = set()

    @property
    def label(self):
        if self._name == 'offset':
            return _('Offset')
        else:
            return _('Frequency')

    def hidden_for(self, memory):
        return (self._name == 'offset' and
                memory.duplex in ('', 'off') and
                memory.number not in self._wants_split)

    def _render_value(self, memory, value):
        if not value:
            value = 0
        if (self._name == 'offset' and
                memory.number in self._wants_split and
                memory.duplex in ('', '-', '+')):
            # Radio is returning offset but user wants split, so calculate
            # the TX frequency to render what they expect.
            value = memory.freq + int('%s%i' % (memory.duplex, value))

        return chirp_common.format_freq(value)

    def _digest_value(self, memory, input_value):
        if not input_value.strip():
            input_value = 0
        if self._name == 'offset' and memory.number in self._wants_split:
            # If we are being edited and the user has requested split for
            # this memory, we need to keep requesting split, even if the
            # radio is returning an offset-based memory. Otherwise, radios
            # that emulate offset-based memories from tx/rx frequencies will
            # fight with the user.
            memory.duplex = 'split'
        return chirp_common.parse_freq(input_value)

    def get_by_prompt(self, parent, memory, message):
        if self._name == 'offset':
            if memory.duplex == 'split':
                default = self._render_value(memory, memory.freq)
            else:
                default = self._render_value(memory, memory.offset)
        else:
            default = self._render_value(memory, memory.freq)
        d = wx.TextEntryDialog(parent, message, _('Enter Frequency'),
                               value=default)
        while True:
            r = d.ShowModal()
            if r == wx.ID_CANCEL:
                return
            try:
                return chirp_common.to_MHz(float(d.GetValue()))
            except ValueError:
                common.error_proof.show_error('Invalid frequency')

    def wants_split(self, memory, split):
        if split:
            self._wants_split.add(memory.number)
        else:
            self._wants_split.discard(memory.number)


class ChirpVariablePowerColumn(ChirpMemoryColumn):
    def __init__(self, name, radio, power_levels):
        super().__init__(name, radio)

    @property
    def level(self):
        return _('Power')

    def _digest_value(self, memory, value):
        return chirp_common.parse_power(value)


class ChirpChoiceEditor(wx.grid.GridCellChoiceEditor):
    """A locking GridCellChoiceEditor.

    Events to our parent window will cause editing to stop and will
    close our drop-down box, which is very annoying. This looks the
    begin/end event to use the EDIT_LOCK to prevent other things from
    submitting changes while we're in the middle of an edit.
    """
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._locked = False

    def BeginEdit(self, *a, **k):
        common.EDIT_LOCK.acquire()
        self._locked = True
        return super().BeginEdit(*a, **k)

    def EndEdit(self, row, col, grid, val, **k):
        common.EDIT_LOCK.release()
        return self.Control.GetStringSelection()


class ChirpChoiceColumn(ChirpMemoryColumn):
    # This is just here so it is marked for translation
    __TITLE1 = _('Tuning Step')

    def __init__(self, name, radio, choices, **k):
        super(ChirpChoiceColumn, self).__init__(name, radio, **k)
        self._choices = choices
        self._str_choices = [str(x) for x in choices]

    def _digest_value(self, memory, input_value):
        idx = self._str_choices.index(input_value)
        return self._choices[idx]

    def get_editor(self):
        return ChirpChoiceEditor(self._str_choices)

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
        return wx.propgrid.EnumProperty(self.label.replace('\n', ' '),
                                        self._name,
                                        self._str_choices,
                                        range(len(self._str_choices)),
                                        cur_index)

    def get_by_prompt(self, parent, memory, message):
        d = wx.SingleChoiceDialog(parent, message, _('Choice Required'),
                                  self._str_choices,
                                  style=wx.OK | wx.CANCEL | wx.CENTER)
        if d.ShowModal() == wx.ID_OK:
            return self._digest_value(memory, self._choices[d.GetSelection()])


class ChirpToneColumn(ChirpChoiceColumn):
    def __init__(self, name, radio):
        self.rf = radio.get_features()
        tones = self.rf.valid_tones or chirp_common.TONES
        tones = [str(x) for x in tones]
        super(ChirpToneColumn, self).__init__(name, radio,
                                              tones)

    @property
    def label(self):
        if self._name == 'rtone':
            return _('Tone')
        else:
            return _('Tone Squelch').replace(' ', '\n', 1)

    def rtone_visible(self, memory):
        if not self._features.has_ctone:
            tmodes = ['Tone', 'TSQL', 'TSQL-R']
            cross_modes = [x for x in chirp_common.CROSS_MODES
                           if 'Tone' in x]
        else:
            tmodes = ['Tone']
            cross_modes = [x for x in chirp_common.CROSS_MODES
                           if 'Tone->' in x]
        if memory.tmode == 'Cross':
            return memory.cross_mode in cross_modes
        else:
            return memory.tmode in tmodes

    def ctone_visible(self, memory):
        return memory.tmode == 'TSQL' or (memory.tmode == 'Cross' and
                                          '->Tone' in memory.cross_mode)

    def hidden_for(self, memory):
        if self._name == 'rtone':
            return not self.rtone_visible(memory)
        else:
            return not self.ctone_visible(memory)

    def _digest_value(self, memory, input_value):
        return float(input_value)


class ChirpDuplexColumn(ChirpChoiceColumn):
    # This is just here so it is marked for translation
    __TITLE = _('Duplex')

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._wants_split = set()

    def _render_value(self, memory, value):
        if memory.number in self._wants_split:
            return 'split'
        else:
            return value

    def _digest_value(self, memory, input_value):
        if memory.number in self._wants_split:
            # If we are being edited and the user has requested split for
            # this memory, we need to avoid requesting a tiny tx frequency
            # (i.e. an offset), even if the radio is returning an offset-based
            # memory. Otherwise, radios that emulate offset-based memories
            # from tx/rx frequencies will fight with the user.
            memory.offset = memory.freq
        return super()._digest_value(memory, input_value)

    def wants_split(self, memory, split):
        if split:
            self._wants_split.add(memory.number)
        else:
            self._wants_split.discard(memory.number)


class ChirpDTCSColumn(ChirpChoiceColumn):
    def __init__(self, name, radio):
        rf = radio.get_features()
        codes = rf.valid_dtcs_codes or chirp_common.DTCS_CODES
        dtcs_codes = ['%03i' % code for code in codes]
        super(ChirpDTCSColumn, self).__init__(name, radio,
                                              dtcs_codes)

    @property
    def label(self):
        if self._name == 'dtcs':
            return _('DTCS')
        elif self._name == 'rx_dtcs':
            return _('RX DTCS')
        else:
            return 'ErrDTCS'

    def _digest_value(self, memory, input_value):
        return int(input_value)

    def _render_value(self, memory, value):
        return '%03i' % value

    def _dtcs_visible(self, memory):
        if memory.tmode in ['DTCS', 'DTCS-R']:
            return True
        if memory.tmode == 'Cross':
            if self._features.has_rx_dtcs:
                # If we have rx_dtcs then this is only visible for cross modes
                # where we are transmitting DTCS
                return 'DTCS->' in memory.cross_mode
            else:
                # If we do not have rx_dtcs then this is used for either tx
                # or rx DTCS in cross.
                return 'DTCS' in memory.cross_mode

    def _rx_dtcs_visible(self, memory):
        return (self._features.has_rx_dtcs and
                memory.tmode == 'Cross' and
                '>DTCS' in memory.cross_mode)

    def hidden_for(self, memory):
        if self._name == 'dtcs':
            return not self._dtcs_visible(memory)
        elif self._name == 'rx_dtcs':
            return not self._rx_dtcs_visible(memory)
        else:
            raise Exception('Internal error')


class ChirpDTCSPolColumn(ChirpChoiceColumn):
    def __init__(self, name, radio):
        super().__init__(name, radio,
                         ['NN', 'NR', 'RN', 'RR'])

    @property
    def label(self):
        return _('DTCS\nPolarity')

    def hidden_for(self, memory):
        return not (memory.tmode == 'DTCS' or
                    'DTCS' in memory.cross_mode)


class ChirpCrossModeColumn(ChirpChoiceColumn):
    # This is just here so it is marked for translation
    __TITLE = _('Mode')

    def __init__(self, name, radio):
        rf = radio.get_features()
        super(ChirpCrossModeColumn, self).__init__(name, radio,
                                                   rf.valid_cross_modes)

    @property
    def valid(self):
        return ('Cross' in self._features.valid_tmodes and
                self._features.valid_cross_modes)

    @property
    def label(self):
        return _('Cross mode')

    def hidden_for(self, memory):
        return memory.tmode != 'Cross'


class ChirpCommentColumn(ChirpMemoryColumn):
    # This is just here so it is marked for translation
    __TITLE = _('Comment')

    @property
    def valid(self):
        return (self._features.has_comment or
                isinstance(self._radio, chirp_common.CloneModeRadio))

    def _digest_value(self, memory, input_value):
        # Limit to 128 characters for sanity
        return str(input_value)[:256]


class ChirpMemEdit(common.ChirpEditor, common.ChirpSyncEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpMemEdit, self).__init__(*a, **k)

        self._radio = radio
        self._features = self._radio.get_features()

        # Cache of memories by *row*
        self._memory_cache = {}
        # Maps special memory *names* to rows
        self._special_rows = {}
        # Maps special memory *numbers* to rows
        self._special_numbers = {}

        self._col_defs = self._setup_columns()

        self.bandplan = bandplan.BandPlans(CONF)

        self._grid = ChirpMemoryGrid(self)
        self._grid.CreateGrid(
            self._features.memory_bounds[1] - self._features.memory_bounds[0] +
            len(self._features.valid_special_chans) + 1,
            len(self._col_defs))
        self._grid.SetSelectionMode(wx.grid.Grid.SelectRows)
        self._grid.DisableDragRowSize()
        self._grid.SetFocus()
        self._default_cell_bg_color = self._grid.GetCellBackgroundColour(0, 0)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._grid, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self._fixed_font = wx.Font(pointSize=10,
                                   family=wx.FONTFAMILY_TELETYPE,
                                   style=wx.FONTSTYLE_NORMAL,
                                   weight=wx.FONTWEIGHT_NORMAL)
        self._variable_font = self._grid.GetDefaultCellFont()
        self.update_font(False)

        self._grid.Bind(wx.grid.EVT_GRID_CELL_CHANGING,
                        self._memory_edited)
        self._grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED,
                        self._memory_changed)
        self._grid.Bind(wx.grid.EVT_GRID_CELL_RIGHT_CLICK,
                        self._memory_rclick)
        self._grid.Bind(wx.grid.EVT_GRID_LABEL_RIGHT_CLICK,
                        self._memory_rclick)

        self._dc = wx.ScreenDC()
        self.set_cell_attrs()

    def set_cell_attrs(self):
        if platform.system() == 'Linux':
            minwidth = 100
        else:
            minwidth = 75

        for col, col_def in enumerate(self._col_defs):
            if not col_def.valid:
                self._grid.HideCol(col)
            else:
                self._grid.SetColLabelValue(col, col_def.label)
                attr = wx.grid.GridCellAttr()
                attr.SetEditor(col_def.get_editor())
                self._grid.SetColAttr(col, attr)
                self._grid.SetColMinimalWidth(col, minwidth)
                try:
                    attr.SetFitMode(wx.grid.GridFitMode.Ellipsize())
                except AttributeError:
                    # No SetFitMode() support on wxPython 4.0.7
                    pass
        wx.CallAfter(self._grid.AutoSizeColumns, setAsMin=False)

    def _setup_columns(self):
        def filter_unknowns(items):
            return [x for x in items if '?' not in x]

        # Some drivers report invalid enumerations in their lists
        # by using strings with question mark characters. Don't let the
        # users select these.
        valid_tmodes = filter_unknowns(self._features.valid_tmodes)
        valid_modes = filter_unknowns(self._features.valid_modes)
        valid_skips = filter_unknowns(self._features.valid_skips)
        valid_duplexes = filter_unknowns(self._features.valid_duplexes)
        valid_power_levels = self._features.valid_power_levels
        valid_tuning_steps = self._features.valid_tuning_steps
        if self._features.has_variable_power:
            power_col_cls = ChirpVariablePowerColumn
        else:
            power_col_cls = ChirpChoiceColumn
        defs = [
            ChirpFrequencyColumn('freq', self._radio),
            ChirpMemoryColumn('name', self._radio),
            ChirpChoiceColumn('tmode', self._radio,
                              valid_tmodes,
                              label=_('Tone Mode')),
            ChirpToneColumn('rtone', self._radio),
            ChirpToneColumn('ctone', self._radio),
            ChirpDTCSColumn('dtcs', self._radio),
            ChirpDTCSColumn('rx_dtcs', self._radio),
            ChirpDTCSPolColumn('dtcs_polarity', self._radio),
            ChirpCrossModeColumn('cross_mode', self._radio),
            ChirpDuplexColumn('duplex', self._radio,
                              valid_duplexes),
            ChirpFrequencyColumn('offset', self._radio),
            ChirpChoiceColumn('mode', self._radio,
                              valid_modes),
            ChirpChoiceColumn('tuning_step', self._radio,
                              valid_tuning_steps),
            ChirpChoiceColumn('skip', self._radio,
                              valid_skips),
            power_col_cls('power', self._radio,
                          valid_power_levels),
            ChirpCommentColumn('comment', self._radio),
        ]
        return defs

    def _col_def_by_name(self, name):
        for coldef in self._col_defs:
            if coldef._name == name:
                return coldef
        LOG.error('No column definition for %s' % name)

    def mem2row(self, number):
        if isinstance(number, str):
            return self._special_rows[number]
        if number in self._special_numbers:
            return self._special_rows[self._special_numbers[number]]
        return number - self._features.memory_bounds[0]

    def row2mem(self, row):
        if row in self._special_rows.values():
            row2number = {v: k for k, v in self._special_rows.items()}
            return row2number[row]
        else:
            return row + self._features.memory_bounds[0]

    def _refresh_memory(self, number, memory):
        row = self.mem2row(number)

        if isinstance(memory, Exception):
            LOG.error('Failed to load memory %s as error because: %s' % (
                number, memory))
            self._row_label_renderers[row].set_error()
            self._grid.SetRowLabelValue(row, '!%s' % (
                self._grid.GetRowLabelValue(row)))
            return

        if memory.empty:
            # Reset our "wants split" flags if the memory is empty
            offset_col = self._col_def_by_name('offset')
            duplex_col = self._col_def_by_name('duplex')
            offset_col.wants_split(memory, False)
            duplex_col.wants_split(memory, False)

        self._memory_cache[row] = memory

        with wx.grid.GridUpdateLocker(self._grid):
            self.set_row_finished(row)

            for col, col_def in enumerate(self._col_defs):
                self._grid.SetCellValue(row, col, col_def.render_value(memory))
                self._grid.SetReadOnly(row, col,
                                       col_def.name in memory.immutable)
                if col_def.name in memory.immutable:
                    color = (0xF5, 0xF5, 0xF5, 0xFF)
                else:
                    color = self._default_cell_bg_color
                self._grid.SetCellBackgroundColour(row, col, color)

    def synchronous_get_memory(self, number):
        """SYNCHRONOUSLY Get memory with extra properties

        This shoud ideally not be used except in situations (like copy)
        where we really have to do the operation synchronously.
        """
        mem = self._radio.get_memory(number)
        if isinstance(self._radio, chirp_common.ExternalMemoryProperties):
            mem = self._radio.get_memory_extra(mem)
        return mem

    def set_row_finished(self, row):
        self._row_label_renderers[row].clear_error()
        memory = self._memory_cache[row]
        if memory.extd_number:
            self._grid.SetRowLabelValue(row, memory.extd_number)
        else:
            self._grid.SetRowLabelValue(row, str(memory.number))

    def set_row_pending(self, row):
        self._row_label_renderers[row].set_progress()
        memory = self._memory_cache[row]
        if memory.extd_number:
            self._grid.SetRowLabelValue(row, '*%s' % memory.extd_number)
        else:
            self._grid.SetRowLabelValue(row, '*%i' % memory.number)

    def refresh_memory(self, number, lazy=False):
        if lazy:
            executor = self.do_lazy_radio
        else:
            executor = self.do_radio

        def extra_cb(job):
            self._refresh_memory(number, job.result)

        def get_cb(job):
            # If get_memory() failed, just refresh with the exception
            if isinstance(job.result, Exception):
                self._refresh_memory(job.args[0], job.result)
                return

            # If this memory is a special, record the mapping of its driver-
            # determined virtual number to is special name for use later
            if job.result.extd_number:
                self._special_numbers[job.result.number] = (
                    job.result.extd_number)
            # Otherwise augment with extra fields and call refresh with that,
            # if appropriate
            if isinstance(self._radio,
                          chirp_common.ExternalMemoryProperties):
                executor(extra_cb, 'get_memory_extra', job.result)
            else:
                extra_cb(job)

        executor(get_cb, 'get_memory', number)

    def set_memory(self, mem, refresh=True):
        """Update a memory in the radio and refresh our view on success"""
        row = self.mem2row(mem.number)
        if refresh:
            self.set_row_pending(row)

        def extra_cb(job):
            if refresh:
                self.refresh_memory(mem.number)

        def set_cb(job):
            if isinstance(job.result, Exception):
                self._row_label_renderers[row].set_error()
            else:
                self._row_label_renderers[row].clear_error()
                if isinstance(self._radio,
                              chirp_common.ExternalMemoryProperties):
                    self.do_radio(extra_cb, 'set_memory_extra', mem)
                else:
                    extra_cb(job)

        self.do_radio(set_cb, 'set_memory', mem)

    def erase_memory(self, number, refresh=True):
        """Erase a memory in the radio and refresh our view on success"""
        row = self.mem2row(number)
        if refresh:
            self.set_row_pending(row)

        def extra_cb(job):
            if refresh:
                self.refresh_memory(number)

        def erase_cb(job):
            if isinstance(job.result, Exception):
                self._row_label_renderers[row].set_error()
            else:
                self._row_label_renderers[row].clear_error()
                if isinstance(self._radio,
                              chirp_common.ExternalMemoryProperties):
                    self.do_radio(extra_cb, 'erase_memory_extra', number)
                else:
                    extra_cb(job)

        self.do_radio(erase_cb, 'erase_memory', number)

    def refresh(self):

        lower, upper = self._features.memory_bounds

        # Build our row label renderers so we can set colors to
        # indicate success or failure
        self._row_label_renderers = []
        for row, _ in enumerate(
                range(lower,
                      upper + len(self._features.valid_special_chans) + 1)):
            self._row_label_renderers.append(ChirpRowLabelRenderer())
            self._grid.SetRowLabelRenderer(row, self._row_label_renderers[-1])

        row = 0
        for i in range(lower, upper + 1):
            row += 1
            self.refresh_memory(i, lazy=True)

        for i in self._features.valid_special_chans:
            self._special_rows[i] = row
            row += 1
            self.refresh_memory(i, lazy=True)

    def _set_memory_defaults(self, mem, *only):
        """This is responsible for setting sane default values on memories.

        For the most part, this just honors the bandplan rules, but it also
        tries to do things like calculate the required step for the memory's
        frequency, etc.

        If fields are provided as arguments, only set those defaults, else,
        set them all.
        """
        if not CONF.get_bool('auto_edits', 'state', True):
            return
        if not only:
            only = ['offset', 'duplex', 'tuning_step', 'mode', 'rtone']
        for prop in mem.immutable:
            if prop in only:
                only.remove(prop)

        defaults = self.bandplan.get_defaults_for_frequency(mem.freq)
        features = self._features

        if not defaults.offset:
            want_duplex = ''
            want_offset = None
        elif defaults.offset > 0:
            want_duplex = '+'
            want_offset = defaults.offset
        elif defaults.offset < 0:
            want_duplex = '-'
            want_offset = abs(defaults.offset)
        else:
            want_duplex = want_offset = None

        if want_duplex is not None and want_duplex in features.valid_duplexes:
            if 'duplex' in only:
                mem.duplex = want_duplex
        if want_offset is not None and features.has_offset:
            if 'offset' in only:
                mem.offset = want_offset

        if defaults.step_khz:
            want_tuning_step = defaults.step_khz
        else:
            try:
                want_tuning_step = chirp_common.required_step(mem.freq)
            except errors.InvalidDataError as e:
                LOG.warning(e)
                want_tuning_step = None

        if want_tuning_step in features.valid_tuning_steps:
            if 'tuning_step' in only:
                mem.tuning_step = want_tuning_step

        if defaults.mode and defaults.mode in features.valid_modes:
            if 'mode' in only:
                mem.mode = defaults.mode

        if defaults.tones and defaults.tones[0] in features.valid_tones:
            if 'rtone' in only:
                mem.rtone = defaults.tones[0]

    def _resolve_cross_mode(self, mem):
        # Resolve TX/RX tones/codes when "Cross Mode" is changed
        txmode, rxmode = mem.cross_mode.split('->')
        todo = [('TX', txmode, 'rtone', 'dtcs'),
                ('RX', rxmode, 'ctone', 'rx_dtcs')]
        setvals = []
        for which, mode, tone_prop, dtcs_prop in todo:
            if mode == 'Tone':
                msg = _('Choose %s Tone') % which
                prop = tone_prop
            elif mode == 'DTCS':
                msg = _('Choose %s DTCS Code') % which
                prop = dtcs_prop
            else:
                # No value for this element, so do not prompt
                continue

            val = self._col_def_by_name(prop).get_by_prompt(
                self, mem, msg)
            if val is None:
                # User hit cancel, so abort
                return False
            setattr(mem, prop, val)
            setvals.append(val)

        if rxmode == txmode and len(setvals) == 2 and setvals[0] == setvals[1]:
            if rxmode == 'Tone':
                mode = 'TSQL'
                name = 'tones'
            else:
                mode = 'DTCS'
                name = 'codes'
            wx.MessageBox(_('Channels with equivalent TX and RX %s are '
                            'represented by tone mode of "%s"') % (name, mode),
                          _('Information'))

        return True

    def _resolve_tmode_cross(self, mem):
        # Resolve cross_mode when tmode is changed to Cross
        # Triggers resolve_cross_mode() after a selection is made
        val = self._col_def_by_name('cross_mode').get_by_prompt(
            self, mem, _('Choose Cross Mode'))
        if val is None:
            return False
        mem.cross_mode = val
        return self._resolve_cross_mode(mem)

    def _resolve_duplex(self, mem):
        self._set_memory_defaults(mem, 'offset')
        if mem.duplex == 'split':
            msg = _('Enter TX Frequency (MHz)')
        elif mem.duplex == 'off':
            # Clearly no need to prompt for this duplex
            return True
        elif 0 < mem.offset < 70000000:
            # We don't need to ask, offset looks like an offset
            return True
        else:
            msg = _('Enter Offset (MHz)')

        offset = self._col_def_by_name('offset').get_by_prompt(
            self, mem, msg)
        if offset is None:
            return False
        mem.offset = offset
        return True

    def _resolve_offset(self, mem):
        self._set_memory_defaults(mem, 'duplex')
        if mem.duplex == '':
            duplex = self._col_def_by_name('duplex').get_by_prompt(
                self, mem, _('Choose duplex'))
            if duplex is None:
                return False
            mem.duplex = duplex
        return True

    @common.error_proof()
    def _memory_edited(self, event):
        """
        Called when the memory row in the UI is edited.

        Responsible for updating our copy of the memory with changes from the
        grid, defaults where appropriate, and extra values when required.
        Validates the memory with the radio, then writes the memory to the
        radio and displays an error if needed.
        """
        row = event.GetRow()
        col = event.GetCol()
        val = event.GetString()

        col_def = self._col_defs[col]

        try:
            mem = self._memory_cache[row]
        except KeyError:
            # This means we never loaded this memory from the radio in the
            # first place, likely due to some error.
            wx.MessageBox(_('Unable to edit memory before radio is loaded'))
            event.Veto()
            return

        # Filter the name according to the radio's rules before we try to
        # validate it
        if col_def.name == 'name':
            val = self._radio.filter_name(val)

        # Record the user's desire for this being a split duplex so that
        # we can represent it consistently to them. The offset and duplex
        # columns need to know so they can behave appropriately.
        if col_def.name == 'duplex':
            offset_col = self._col_def_by_name('offset')
            duplex_col = self._col_def_by_name('duplex')
            offset_col.wants_split(mem, val == 'split')
            duplex_col.wants_split(mem, val == 'split')

        # Any edited memory is going to be non-empty
        if mem.empty:
            mem.empty = False

        # This is where the column definition actually applies the edit they
        # made to the memory.
        col_def.digest_value(mem, val)

        # If they edited the frequency, we assume that they are likely going
        # to want band defaults applied (duplex, offset, etc).
        if col_def.name == 'freq':
            self._set_memory_defaults(mem)

        # If they edited cross mode, they definitely want a tone mode of
        # 'Cross'. For radios that do not store all the tone/code values
        # all the time, we need to set certain tones or codes at the same
        # time as this selection was made.
        if col_def.name == 'cross_mode':
            mem.tmode = 'Cross'
            if not self._resolve_cross_mode(mem):
                event.Veto()
                return
        elif col_def.name == 'tmode' and val == 'Cross':
            if not self._resolve_tmode_cross(mem):
                event.Veto()
                return

        # If they edited one of the tone values and tmode is not Cross,
        # select the right thing for them. Note that we could get fancy
        # here and change the TX or RX part of cross_mode, if Cross is
        # selected.
        if col_def.name == 'rtone' and mem.tmode != 'Cross':
            mem.tmode = 'Tone'
        elif col_def.name == 'ctone' and mem.tmode != 'Cross':
            mem.tmode = 'TSQL'
        elif col_def.name == 'dtcs' and mem.tmode != 'Cross':
            mem.tmode = 'DTCS'

        # If they edited duplex, we need to prompt them for the value of
        # offset in some cases. For radios that do not store offset itself,
        # we need to prompt for the offset so it is set in the same operation.
        # For split mode, we should always prompt, because trying to set a
        # TX frequency of 600kHz is likely to fail on most radios.
        if col_def.name == 'duplex' and val != '':
            if not self._resolve_duplex(mem):
                event.Veto()
                return

        if col_def.name == 'offset' and mem.duplex in ('', 'off'):
            if not self._resolve_offset(mem):
                event.Veto()
                return

        # Try to validate these changes with the radio before we go to store
        # them, as now is the best time to present an error to the user.
        warnings, errors = chirp_common.split_validation_msgs(
            self._radio.validate_memory(mem))
        if errors:
            LOG.warning('Memory failed validation: %s' % mem)
            wx.MessageBox(_('Invalid edit: %s') % '; '.join(errors),
                          'Invalid Entry')
            event.Skip()
            return
        if warnings:
            LOG.warning('Memory validation had warnings: %s' % mem)
            wx.MessageBox(_('Warning: %s') % '; '.join(warnings),
                          _('Warning'))

        self.set_row_pending(row)
        self.set_memory(mem)
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
        self.refresh_memory(self.row2mem(row))

        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def delete_memory_at(self, row, event):
        number = self.row2mem(row)

        if 'empty' in self._memory_cache[row].immutable:
            raise errors.InvalidMemoryLocation(
                _('Memory %i is not deletable') % number)

        self.erase_memory(number)

    @common.error_proof(errors.InvalidMemoryLocation)
    def _delete_memories_at(self, rows, event, shift_up=None):
        if rows:
            wx.PostEvent(self, common.EditorChanged(self.GetId()))

        for row in rows:
            if not self._memory_cache[row].empty:
                self.delete_memory_at(row, event)

        if not shift_up:
            return

        LOG.debug('Shifting up...%s' % shift_up)
        next_row = rows[-1] + 1
        delta = len(rows)
        mems_to_move = []

        # Find all the memories we are going to shift up, either to the end
        # of the current block, or to the end of the list
        for row in range(next_row, self._grid.GetNumberRows()):
            if (shift_up == 'block' and
                    self._memory_cache[row].empty):
                # We found the end of the next block
                break
            elif isinstance(self.row2mem(row), str):
                # We hit the specials, stop here
                break
            mems_to_move.append(self.row2mem(row))

        if not mems_to_move:
            LOG.debug('Delete %s has no memories to move' % shift_up)
            return

        # Shift them all up by however many we deleted
        for number in mems_to_move:
            LOG.debug('Moving memory %i -> %i', number, number - delta)
            mem = self._memory_cache[self.mem2row(number)]
            mem.number -= delta
            if mem.empty:
                self.erase_memory(mem.number, refresh=False)
            else:
                self.set_memory(mem, refresh=False)

        # Delete the memories that are now the hole we made
        for number in range(mem.number + 1, mems_to_move[-1] + 1):
            LOG.debug('Erasing memory %i', number)
            self.erase_memory(number, refresh=False)

        # Refresh the entire range from the top of what we deleted to the
        # hole we created
        for number in range(self.row2mem(rows[0]), mems_to_move[-1] + 1):
            self.refresh_memory(number)

    def _memory_rclick(self, event):
        if event.GetRow() == -1:
            # This is a right-click on a column header
            return
        menu = wx.Menu()
        selected_rows = self._grid.GetSelectedRows()
        if not selected_rows:
            selected_rows = [event.GetRow()]

        props_item = wx.MenuItem(menu, wx.NewId(), _('Properties'))
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._mem_properties, selected_rows),
                  props_item)
        menu.Append(props_item)

        insert_item = wx.MenuItem(menu, wx.NewId(), _('Insert Row Above'))
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._mem_insert, selected_rows[0]),
                  insert_item)
        menu.Append(insert_item)

        if len(selected_rows) > 1:
            del_item = wx.MenuItem(
                menu, wx.NewId(),
                _('Delete %i Memories') % len(selected_rows))
            del_block_item = wx.MenuItem(
                menu, wx.NewId(),
                _('Delete %i Memories and shift block up') % (
                    len(selected_rows)))
            del_shift_item = wx.MenuItem(
                menu, wx.NewId(),
                _('Delete %i Memories and shift all up') % len(selected_rows))
            to_delete = selected_rows
        else:
            del_item = wx.MenuItem(menu, wx.NewId(), _('Delete'))
            del_block_item = wx.MenuItem(menu, wx.NewId(),
                                         _('Delete and shift block up'))
            del_shift_item = wx.MenuItem(menu, wx.NewId(),
                                         _('Delete and shift all up'))
            to_delete = [event.GetRow()]
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._delete_memories_at, to_delete),
                  del_item)
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._delete_memories_at, to_delete,
                                    shift_up='block'),
                  del_block_item)
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._delete_memories_at, to_delete,
                                    shift_up='all'),
                  del_shift_item)

        menu.Append(del_item)
        menu.Append(del_block_item)
        menu.Append(del_shift_item)

        # Don't allow bulk operations on live radios with pending jobs
        del_block_item.Enable(not self.busy)
        del_shift_item.Enable(not self.busy)
        insert_item.Enable(not self.busy)

        if CONF.get_bool('developer', 'state'):
            menu.Append(wx.MenuItem(menu, wx.ID_SEPARATOR))

            raw_item = wx.MenuItem(menu, wx.NewId(), _('Show Raw Memory'))
            self.Bind(wx.EVT_MENU,
                      functools.partial(self._mem_showraw, event.GetRow()),
                      raw_item)
            menu.Append(raw_item)

            if len(selected_rows) == 2:
                diff_item = wx.MenuItem(menu, wx.NewId(),
                                        _('Diff Raw Memories'))
                self.Bind(wx.EVT_MENU,
                          functools.partial(self._mem_diff, selected_rows),
                          diff_item)
                menu.Append(diff_item)

        self.PopupMenu(menu)
        menu.Destroy()

    @common.error_proof()
    def _mem_properties(self, rows, event):
        memories = [
            self.synchronous_get_memory(self.row2mem(row))
            for row in rows]
        with ChirpMemPropDialog(self, memories) as d:
            if d.ShowModal() == wx.ID_OK:
                memories = d._memories
            else:
                return

        # Schedule all the set jobs
        for memory in memories:
            self.set_memory(memory)

        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    @common.error_proof()
    def _mem_insert(self, row, event):
        # Traverse memories downward until we find a hole
        for i in range(row, self.mem2row(self._features.memory_bounds[1] + 1)):
            mem = self._memory_cache[i]
            if mem.empty:
                LOG.debug("Found empty memory %i at row %i" % (mem.number, i))
                empty_row = i
                break
        else:
            raise Exception(_('No empty rows below!'))

        mems_to_refresh = []
        # Move memories down in reverse order
        for target_row in range(empty_row, row, -1):
            mem = self._memory_cache[target_row - 1]
            LOG.debug('Moving memory %i -> %i', mem.number,
                      self.row2mem(target_row))
            mem.number = self.row2mem(target_row)
            self.set_memory(mem, refresh=False)
            mems_to_refresh.append(mem.number)

        # Erase the memory that is to become the empty row
        LOG.debug('Erasing memory %i', self.row2mem(row))
        self.erase_memory(self.row2mem(row), refresh=False)
        mems_to_refresh.append(self.row2mem(row))

        # Refresh all the memories we touched
        for number in mems_to_refresh:
            self.refresh_memory(number)

        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def _mem_showraw(self, row, event):
        mem = self._radio.get_raw_memory(self.row2mem(row))
        with developer.MemoryDialog(mem, self) as d:
            d.ShowModal()

    def _mem_diff(self, rows, event):
        mem_a = self._radio.get_raw_memory(self.row2mem(rows[0]))
        mem_b = self._radio.get_raw_memory(self.row2mem(rows[1]))
        with developer.MemoryDialog((mem_a, mem_b), self) as d:
            d.ShowModal()

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

    def cb_copy(self, cut=False):
        rows = self._grid.GetSelectedRows()
        offset = self._features.memory_bounds[0]
        mems = []
        for row in rows:
            mem = self.synchronous_get_memory(row + offset)
            # We can't pickle settings, nor would they apply if we
            # paste across models
            mem.extra = []
            mems.append(mem)
        payload = {'mems': mems,
                   'features': self._radio.get_features()}
        data = wx.DataObjectComposite()
        memdata = wx.CustomDataObject(common.CHIRP_DATA_MEMORY)
        data.Add(memdata)
        memdata.SetData(pickle.dumps(payload))
        strfmt = chirp_common.mem_to_text(mems[0])
        textdata = wx.TextDataObject(strfmt)
        data.Add(textdata)
        if cut:
            if any('empty' in mem.immutable for mem in mems):
                raise errors.InvalidMemoryLocation(
                    _('Some memories are not deletable'))
            for mem in mems:
                self.erase_memory(mem.number)

        if cut:
            wx.PostEvent(self, common.EditorChanged(self.GetId()))

        return data

    def _cb_paste_memories(self, payload):
        mems = payload['mems']
        srcrf = payload['features']
        try:
            row = self._grid.GetSelectedRows()[0]
        except IndexError:
            LOG.info('No row selected for paste')
            return

        overwrite = []
        for i in range(len(mems)):
            mem = self._memory_cache[row + i]
            if not mem.empty:
                overwrite.append(mem.number)

        if overwrite:
            if len(overwrite) == 1 and len(mems) == 1:
                msg = _('Pasted memory will overwrite memory %i') % (
                    overwrite[0])
            elif len(overwrite) == 1 and len(mems) > 0:
                msg = _('Pasted memories will overwrite memory %i') % (
                    overwrite[0])
            elif len(overwrite) > 10:
                msg = _('Pasted memories will overwrite %i '
                        'existing memories') % (len(overwrite))
            else:
                msg = _('Pasted memories will overwrite memories %s') % (
                    ','.join(str(x) for x in overwrite))
            d = wx.MessageDialog(self, msg,
                                 _('Overwrite memories?'),
                                 wx.YES | wx.NO | wx.YES_DEFAULT)
            resp = d.ShowModal()
            if resp == wx.ID_NO:
                return

        errormsgs = []
        modified = False
        for mem in mems:
            existing = self._memory_cache[row]
            mem.number = self.row2mem(row)
            row += 1
            try:
                if mem.empty:
                    self.erase_memory(mem.number)
                    self._radio.check_set_memory_immutable_policy(existing,
                                                                  mem)
                else:
                    mem = import_logic.import_mem(self._radio, srcrf, mem)
                    warns, errs = chirp_common.split_validation_msgs(
                        self._radio.validate_memory(mem))
                    errormsgs.extend([(mem, e) for e in errs])
                    errormsgs.extend([(mem, w) for w in warns])
                    if not errs:
                        # If we got error messages from validate, don't even
                        # try to set the memory, just like if import_logic
                        # was unable to make it compatible.
                        self.set_memory(mem)
                modified = True
            except (import_logic.DestNotCompatible,
                    chirp_common.ImmutableValueError,
                    errors.RadioError) as e:
                LOG.warning('Pasted memory %s incompatible: %s' % (
                    mem, str(e)))
                errormsgs.append((mem, e))
            except Exception as e:
                LOG.exception('Failed to paste: %s' % e)
                errormsgs.append((mem, e))

        if modified:
            wx.PostEvent(self, common.EditorChanged(self.GetId()))

        if errormsgs:
            d = wx.MessageDialog(
                    self,
                    _('Some memories are incompatible with this radio'))
            msg = '\n'.join('#%i: %s' % (mem.number, e)
                            for mem, e in errormsgs)
            d.SetExtendedMessage(msg)
            d.ShowModal()

    def cb_paste(self, data):
        if common.CHIRP_DATA_MEMORY in data.GetAllFormats():
            payload = pickle.loads(data.GetData().tobytes())
            LOG.debug('CHIRP-native paste: %r' % payload)
            self._cb_paste_memories(payload)
        elif wx.DF_UNICODETEXT in data.GetAllFormats():
            try:
                mem = chirp_common.mem_from_text(
                    data.GetText())
            except Exception as e:
                LOG.warning('Failed to parse pasted data %r: %s' % (
                    data.GetText(), e))
                return
            # Since matching the offset is kinda iffy, set our band plan
            # set the offset, if a rule exists.
            if mem.duplex in ('-', '+'):
                self._set_memory_defaults(mem, 'offset')
            LOG.debug('Generic text paste %r: %s' % (
                data.GetText(), mem))
            self._cb_paste_memories({'mems': [mem],
                                     'features': self._features})
        else:
            LOG.warning('Unknown data format %s paste' % (
                data.GetFormat().Type))

    def cb_delete(self):
        selected_rows = self._grid.GetSelectedRows()
        for row in selected_rows:
            self.delete_memory_at(row, None)

    def cb_goto(self, number, column=0):
        self._grid.GoToCell(self.mem2row(number), column)
        self._grid.SelectRow(self.mem2row(number))

    def cb_find(self, text):
        search_cols = ('freq', 'name', 'comment')
        cols = [self._col_defs.index(self._col_def_by_name(x))
                for x in search_cols]
        num_rows = self._grid.GetNumberRows()
        try:
            current_row = self._grid.GetSelectedRows()[0] + 1
        except IndexError:
            current_row = 0
        for row in range(current_row, current_row + num_rows):
            # Start at current row, and wrap around
            row_num = row % num_rows
            for col in cols:
                if text.lower() in self._grid.GetCellValue(
                        row_num, col).lower():
                    self.cb_goto(self.row2mem(row_num), col)
                    return True
        return False

    def select_all(self):
        self._grid.SelectAll()

    def rows_visible(self):
        first = self._grid.GetFirstFullyVisibleRow()
        last = first + self._grid.GetScrollPageSize(wx.VERTICAL)
        return first, last

    def get_scroll_pos(self):
        return self._grid.GetViewStart()

    def set_scroll_pos(self, pos):
        self._grid.Scroll(*pos)

    def export_to_file(self, filename):
        if not filename.lower().endswith('.csv'):
            raise Exception(_('Export can only write CSV files'))
        selected = self._grid.GetSelectedRows()
        if len(selected) <= 1:
            selected = range(0, self._grid.GetNumberRows())
        r = generic_csv.CSVRadio(None)
        # The CSV driver defaults to a single non-empty memory at location
        # zero, so delete it before we go to export.
        r.erase_memory(0)
        for row in selected:
            m = self._memory_cache[row]
            if not m.empty:
                m = import_logic.import_mem(r, self._features, m)
            r.set_memory(m)
        r.save(filename)
        LOG.info('Wrote exported CSV to %s' % filename)

    def get_selected_memories(self, or_all=True):
        rows = self._grid.GetSelectedRows()
        if len(rows) <= 1 and or_all:
            rows = list(range(self._grid.GetNumberRows()))
        return [self._memory_cache[r] for r in rows]


class ChirpLiveMemEdit(ChirpMemEdit, common.ChirpAsyncEditor):
    pass


class DVMemoryAsSettings(settings.RadioSettingGroup):
    def __init__(self, radio, dvmemory):
        self._dvmemory = dvmemory
        super(DVMemoryAsSettings, self).__init__('dvmemory', 'DV Memory')

        features = radio.get_features()

        fields = {'dv_urcall': 'URCALL',
                  'dv_rpt1call': 'RPT1Call',
                  'dv_rpt2call': 'RPT2Call',
                  'dv_code': _('Digital Code')}

        for field, title in fields.items():
            value = getattr(dvmemory, field)

            if isinstance(value, int):
                rsv = settings.RadioSettingValueInteger(0, 99, value)
            elif features.requires_call_lists and 'call' in field:
                if 'urcall' in field:
                    calls = radio.get_urcall_list()
                elif 'rpt' in field:
                    calls = radio.get_repeater_call_list()
                else:
                    LOG.error('Unhandled call type %s' % field)
                    calls = []
                rsv = settings.RadioSettingValueList(
                    calls,
                    getattr(dvmemory, field))
            else:
                rsv = settings.RadioSettingValueString(0, 8, str(value))

            rs = settings.RadioSetting(field, title, rsv)
            self.append(rs)


class ChirpMemPropDialog(wx.Dialog):
    def __init__(self, memedit, memories, *a, **k):
        if len(memories) == 1:
            title = _('Edit details for memory %i') % memories[0].number
        else:
            title = _('Edit details for %i memories') % len(memories)

        super().__init__(memedit, *a, title=title, **k)

        self._memories = [mem.dupe() for mem in memories]
        self._col_defs = list(memedit._col_defs)
        self._radio = memedit._radio

        # The first non-empty memory sets the defaults
        memory = self._memories[0]
        for mem in self._memories:
            if not mem.empty:
                memory = mem
                break
        self.default_memory = memory

        self._tabs = wx.Notebook(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        vbox.Add(self._tabs, 1, wx.EXPAND)

        self._pg = wx.propgrid.PropertyGrid(self._tabs,
                                            style=wx.propgrid.PG_BOLD_MODIFIED)
        self._pg.Bind(wx.propgrid.EVT_PG_CHANGED, self._mem_prop_changed)
        self._tabs.InsertPage(0, self._pg, 'Values')
        page_index = 0
        self._extra_page = None
        self._dv_page = None

        if memory.extra:
            page_index += 1
            self._extra_page = page_index
            self._extra = common.ChirpSettingGrid(memory.extra, self._tabs)
            self._tabs.InsertPage(page_index, self._extra, _('Extra'))
            self._extra.propgrid.Bind(wx.propgrid.EVT_PG_CHANGED,
                                      self._mem_extra_changed)

        if isinstance(memory, chirp_common.DVMemory):
            page_index += 1
            self._dv_page = page_index
            self._dv = common.ChirpSettingGrid(
                DVMemoryAsSettings(memedit._radio,
                                   memory),
                self._tabs)
            self._tabs.InsertPage(page_index, self._dv, _('DV Memory'))
            self._dv.propgrid.Bind(wx.propgrid.EVT_PG_CHANGED,
                                   self._mem_prop_changed)

        for coldef in self._col_defs:
            if coldef.valid:
                editor = coldef.get_propeditor(memory)
                self._pg.Append(editor)
                if coldef.name in memory.immutable:
                    editor.Enable(False)

        bs = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        vbox.Add(bs, 0, wx.ALIGN_RIGHT | wx.ALL, border=10)
        self.Bind(wx.EVT_BUTTON, self._button)

        # OK button is disabled until something is changed
        self.FindWindowById(wx.ID_OK).Enable(False)

        self.SetMinSize((400, 400))
        self.Fit()
        self.Center()
        wx.CallAfter(self._pg.FitColumns)

    def _col_def_by_name(self, name):
        for coldef in self._col_defs:
            if coldef._name == name:
                return coldef
        LOG.error('No column definition for %s' % name)

    def _update_mem(self, mem, prop, coldef):
        name = prop.GetName().split(common.INDEX_CHAR)[0]
        value = prop.GetValueAsString()
        if coldef:
            setattr(mem, name, coldef._digest_value(mem, value))
        elif value.isdigit():
            # Assume this is an integer (dv_code) and set it as
            # such
            setattr(mem, name, prop.GetValue())
        else:
            setattr(mem, name, value)
        LOG.debug('Changed mem %i %s=%r' % (mem.number, name,
                                            value))
        if prop.GetName() == 'freq':
            mem.empty = False

    def _mem_prop_changed(self, event):
        self.FindWindowById(wx.ID_OK).Enable(True)

        prop = event.GetProperty()
        coldef = self._col_def_by_name(prop.GetName())
        for mem in self._memories:
            try:
                self._update_mem(mem, prop, coldef)
            except chirp_common.ImmutableValueError as e:
                LOG.warning('Memory %s: %s' % (mem.number, e))

    def _mem_extra_changed(self, event):
        self.FindWindowById(wx.ID_OK).Enable(True)

        prop = event.GetProperty()
        name = prop.GetName().split(common.INDEX_CHAR)[0]
        value = prop.GetValueAsString()
        for mem in self._memories:
            for setting in mem.extra:
                if setting.get_name() == name:
                    if isinstance(setting.value,
                                  settings.RadioSettingValueBoolean):
                        setting.value = value == 'True'
                    else:
                        setting.value = value
                    LOG.debug('Changed mem %i extra %s=%r' % (
                        mem.number, setting.get_name(), value))

    def _validate_memories(self):
        for mem in self._memories:
            msgs = self._radio.validate_memory(mem)
            if msgs:
                wx.MessageBox(_('Invalid edit: %s') % '; '.join(msgs),
                              'Invalid Entry')
                raise errors.InvalidValueError()

    def _button(self, event):
        button_id = event.GetEventObject().GetId()
        if button_id == wx.ID_OK:
            try:
                self._validate_memories()
            except errors.InvalidValueError:
                # Leave the box open
                return

        self.EndModal(button_id)
