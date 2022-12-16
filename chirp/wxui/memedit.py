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
from chirp import settings
from chirp.ui import config
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
    def name(self):
        return self._name

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

        editor = ChirpStringProperty(self.label, self._name)
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

        return '%.5f' % (value / 1000000.0)

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
        return int(chirp_common.to_MHz(float(input_value)))

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
    def __init__(self, name, radio, choices):
        super(ChirpChoiceColumn, self).__init__(name, radio)
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
        return wx.propgrid.EnumProperty(self.label, self._name,
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
        tones = [str(x) for x in chirp_common.TONES]
        super(ChirpToneColumn, self).__init__(name, radio,
                                              tones)

    @property
    def label(self):
        if self._name == 'rtone':
            return _('Tone')
        else:
            return _('ToneSql')

    def hidden_for(self, memory):
        cross_rx_tone = (memory.tmode == 'Cross' and
                         '->Tone' in memory.cross_mode)
        cross_tx_tone = (memory.tmode == 'Cross' and
                         'Tone->' in memory.cross_mode)
        return not (
            (self._name == 'rtone' and (
                memory.tmode == 'Tone' or cross_tx_tone))
            or
            (self._name == 'ctone' and (
                memory.tmode == 'TSQL' or cross_rx_tone)))

    def _digest_value(self, memory, input_value):
        return float(input_value)


class ChirpDuplexColumn(ChirpChoiceColumn):
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
        dtcs_codes = ['%03i' % code for code in chirp_common.DTCS_CODES]
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

    def hidden_for(self, memory):
        return (
            (self._name == 'dtcs' and not (
                memory.tmode == 'DTCS' or (memory.tmode == 'Cross' and
                                           'DTCS->' in memory.cross_mode)))
            or
            (self._name == 'rx_dtcs' and not (
                memory.tmode == 'Cross' and '>DTCS' in memory.cross_mode)))


class ChirpDTCSPolColumn(ChirpChoiceColumn):
    def __init__(self, name, radio):
        super().__init__(name, radio,
                         ['NN', 'NR', 'RN', 'RR'])

    @property
    def label(self):
        return _('DTCS Polarity')

    def hidden_for(self, memory):
        return not (memory.tmode == 'DTCS' or
                    'DTCS' in memory.cross_mode)


class ChirpCrossModeColumn(ChirpChoiceColumn):
    def __init__(self, name, radio):
        rf = radio.get_features()
        super(ChirpCrossModeColumn, self).__init__(name, radio,
                                                   rf.valid_cross_modes)

    @property
    def label(self):
        return _('Cross mode')

    def hidden_for(self, memory):
        return memory.tmode != 'Cross'


class ChirpMemEdit(common.ChirpEditor, common.ChirpSyncEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpMemEdit, self).__init__(*a, **k)

        self._radio = radio
        self._features = self._radio.get_features()
        # This is set based on the radio behavior during refresh()
        self._negative_specials = False

        self._memory_cache = {}
        self._special_rows = {}

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

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._grid, 1, wx.EXPAND)
        self.SetSizer(sizer)

        if platform.system() == 'Linux':
            minwidth = 100
        else:
            minwidth = 75

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
                self._grid.SetColMinimalWidth(col, minwidth)

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
            ChirpDTCSPolColumn('dtcs_polarity', self._radio),
            ChirpCrossModeColumn('cross_mode', self._radio),
            ChirpDuplexColumn('duplex', self._radio,
                              self._features.valid_duplexes),
            ChirpFrequencyColumn('offset', self._radio),
            ChirpChoiceColumn('mode', self._radio,
                              self._features.valid_modes),
            ChirpChoiceColumn('tuning_step', self._radio,
                              self._features.valid_tuning_steps),
            ChirpChoiceColumn('skip', self._radio,
                              self._features.valid_skips),
            ChirpChoiceColumn('power', self._radio,
                              self._features.valid_power_levels),
            ChirpMemoryColumn('comment', self._radio),
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
        return number - self._features.memory_bounds[0]

    def row2mem(self, row):
        if row in self._special_rows.values():
            row2number = {v: k for k, v in self._special_rows.items()}
            return row2number[row]
        else:
            return row + self._features.memory_bounds[0]

    def refresh_memory(self, number, memory):
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
            if memory.extd_number:
                self._grid.SetRowLabelValue(row, memory.extd_number)
            else:
                self._grid.SetRowLabelValue(row, str(memory.number))

            for col, col_def in enumerate(self._col_defs):
                self._grid.SetCellValue(row, col, col_def.render_value(memory))

    def refresh_memory_from_job(self, job):
        self.refresh_memory(job.args[0], job.result)

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
            self.do_radio(self.refresh_memory_from_job, 'get_memory', i)

        for i in self._features.valid_special_chans:
            self._special_rows[i] = row
            row += 1
            self.do_radio(self.refresh_memory_from_job, 'get_memory', i)

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
            only = ('offset', 'duplex', 'tuning_step', 'mode', 'rtone')

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
        txmode, rxmode = mem.cross_mode.split('->')
        todo = [('TX', txmode, 'rtone', 'dtcs'),
                ('RX', rxmode, 'ctone', 'rx_dtcs')]
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
        return True

    def _resolve_duplex(self, mem):
        self._set_memory_defaults(mem, 'offset')
        if mem.duplex == 'split':
            msg = _('Enter TX Frequency (MHz)')
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

        def set_cb(job):
            if isinstance(job.result, Exception):
                self._row_label_renderers[row].set_error()
            else:
                self._row_label_renderers[row].clear_error()

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

        # Try to validate these changes with the radio before we go to store
        # them, as now is the best time to present an error to the user.
        msgs = self._radio.validate_memory(mem)
        if msgs:
            LOG.warning('Memory failed validation: %s' % mem)
            wx.MessageBox(_('Invalid edit: %s') % '; '.join(msgs),
                          'Invalid Entry')
            event.Skip()
            return

        self._grid.SetRowLabelValue(row, '*%i' % mem.number)
        self._row_label_renderers[row].set_progress()
        self.do_radio(set_cb, 'set_memory', mem)
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
        self.do_radio(self.refresh_memory_from_job, 'get_memory',
                      self.row2mem(row))

        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def delete_memory_at(self, row, event):
        number = self.row2mem(row)

        def del_cb(job):
            self.do_radio(self.refresh_memory_from_job, 'get_memory', number)

        self.do_radio(del_cb, 'erase_memory', number)
        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def _delete_memories_at(self, rows, event):
        for row in rows:
            self.delete_memory_at(row, event)

    def _memory_rclick(self, event):
        menu = wx.Menu()
        selected_rows = self._grid.GetSelectedRows()
        if not selected_rows:
            selected_rows = [event.GetRow()]

        props_item = wx.MenuItem(menu, wx.NewId(), _('Properties'))
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._mem_properties, selected_rows),
                  props_item)
        menu.Append(props_item)

        if len(selected_rows) > 1:
            del_item = wx.MenuItem(
                menu, wx.NewId(),
                _('Delete %i Memories') % len(selected_rows))
            to_delete = selected_rows
        else:
            del_item = wx.MenuItem(menu, wx.NewId(), _('Delete'))
            to_delete = [event.GetRow()]
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._delete_memories_at, to_delete),
                  del_item)
        menu.Append(del_item)

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
            self._radio.get_memory(self.row2mem(row))
            for row in rows]
        with ChirpMemPropDialog(self, memories) as d:
            if d.ShowModal() == wx.ID_OK:
                for memory in d._memories:
                    self._radio.set_memory(memory)
                    self.refresh_memory(memory.number, memory)
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
                self.refresh_memory(mem.number, mem)

        if cut:
            wx.PostEvent(self, common.EditorChanged(self.GetId()))

        return data

    def _cb_paste_memories(self, mems):
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

        errors = []
        modified = False
        for mem in mems:
            mem.number = self.row2mem(row)
            row += 1
            try:
                if mem.empty:
                    self._radio.erase_memory(mem.number)
                else:
                    self._radio.set_memory(mem)
                self.refresh_memory(mem.number, mem)
                modified = True
            except Exception as e:
                errors.append((mem, e))

        if modified:
            wx.PostEvent(self, common.EditorChanged(self.GetId()))

        if errors:
            d = wx.MessageDialog(
                    self,
                    _('Some memories are incompatible with this radio'))
            msg = '\n'.join('#%i: %s' % (mem.number, e) for mem, e in errors)
            d.SetExtendedMessage(msg)
            d.ShowModal()

    def cb_paste(self, data):
        if data.GetFormat() == common.CHIRP_DATA_MEMORY:
            mems = pickle.loads(data.GetData().tobytes())
            self._cb_paste_memories(mems)
        elif data.GetFormat() == wx.DF_UNICODETEXT:
            LOG.debug('FIXME: handle pasted text: %r' % data.GetText())
        else:
            LOG.warning('Unknown data format %s' % data.GetFormat().Type)

    def cb_goto(self, number, column=0):
        self._grid.GoToCell(self.mem2row(number), column)
        self._grid.SelectRow(self.mem2row(number))

    def cb_find(self, text):
        # FIXME: This should be more dynamic
        cols = [
            0,   # Freq
            1,   # Name
            14,  # Comment
        ]
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
            r.set_memory(self._memory_cache[row])
        r.save(filename)


class ChirpLiveMemEdit(ChirpMemEdit, common.ChirpAsyncEditor):
    pass


class DVMemoryAsSettings(settings.RadioSettingGroup):
    def __init__(self, dvmemory):
        self._dvmemory = dvmemory
        super(DVMemoryAsSettings, self).__init__('dvmemory', 'DV Memory')

        fields = {'dv_urcall': 'URCALL',
                  'dv_rpt1call': 'RPT1Call',
                  'dv_rpt2call': 'RPT2Call',
                  'dv_code': _('Digital Code')}

        for field, title in fields.items():
            value = getattr(dvmemory, field)

            if isinstance(value, int):
                rsv = settings.RadioSettingValueInteger(0, 99, value)
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
            self._dv = common.ChirpSettingGrid(DVMemoryAsSettings(memory),
                                               self._tabs)
            self._tabs.InsertPage(page_index, self._dv, _('DV Memory'))
            self._dv.propgrid.Bind(wx.propgrid.EVT_PG_CHANGED,
                                   self._mem_prop_changed)

        for coldef in self._col_defs:
            if coldef.valid:
                self._pg.Append(coldef.get_propeditor(memory))

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

    def _mem_prop_changed(self, event):
        self.FindWindowById(wx.ID_OK).Enable(True)

        prop = event.GetProperty()
        coldef = self._col_def_by_name(prop.GetName())
        name = prop.GetName().split(common.INDEX_CHAR)[0]
        value = prop.GetValueAsString()
        for mem in self._memories:
            if coldef:
                setattr(mem, name, coldef._digest_value(mem, value))
            else:
                setattr(mem, name, prop.GetValue())
            LOG.debug('Changed mem %i %s=%r' % (mem.number, name,
                                                value))
            if prop.GetName() == 'freq':
                mem.empty = False

    def _mem_extra_changed(self, event):
        self.FindWindowById(wx.ID_OK).Enable(True)

        prop = event.GetProperty()
        name = prop.GetName().split(common.INDEX_CHAR)[0]
        value = prop.GetValueAsString()
        for mem in self._memories:
            for setting in mem.extra:
                if setting.get_name() == name:
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
