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

import copy
import logging

import wx
import wx.dataview

from chirp import settings
from chirp.wxui import common

LOG = logging.getLogger(__name__)


class ChirpSettingsEdit(common.ChirpEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpSettingsEdit, self).__init__(*a, **k)

        self._radio = radio
        self._settings = None
        self._propgrid = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self._group_control = wx.Treebook(self, style=wx.LB_LEFT)
        self._group_control.GetTreeCtrl().SetMinSize((250, -1))
        sizer.Add(self._group_control, 1, wx.EXPAND)

        self._initialized = False
        self._restore_selection = None

    def _initialize(self, job):
        self.stop_wait_dialog()
        with common.error_proof(Exception):
            if isinstance(job.result, Exception):
                raise job.result
            self._settings = job.result
            self._load_settings()
            if self._restore_selection is not None:
                self._group_control.SetSelection(self._restore_selection)
                self._restore_selection = None

    def selected(self):
        if not self._initialized:
            self._initialized = True
            self.start_wait_dialog(_('Getting settings'))
            self.do_radio(lambda job: wx.CallAfter(self._initialize, job),
                          'get_settings')

    def get_scroll_pos(self):
        return self._group_control.GetSelection()

    def set_scroll_pos(self, pos):
        try:
            self._group_control.SetSelection(pos)
        except AssertionError:
            # If we're in the middle of a load, stash the position so we will
            # restore it once we have everything.
            self._restore_selection = pos

    def refresh(self):
        self._restore_selection = self._group_control.GetSelection()
        self._group_control.DeleteAllPages()
        # Next select will re-load everything
        self._initialized = False

    def _load_settings(self):
        for group in self._settings:
            self._add_group(group)
        self.Layout()

    def _add_group(self, group, parent=None):
        propgrid = common.ChirpSettingGrid(group, self._group_control)
        self._propgrid = propgrid
        self.Bind(common.EVT_EDITOR_CHANGED, self._changed, propgrid)
        LOG.debug('Adding page for %s (parent=%s)' % (group.get_shortname(),
                                                      parent))
        if parent is not None:
            self._group_control.InsertSubPage(parent, propgrid,
                                              group.get_shortname())
        else:
            self._group_control.AddPage(propgrid, group.get_shortname())

        for element in group.values():
            if not isinstance(element, (settings.RadioSetting,
                                        settings.RadioSettingSubGroup)):
                self._add_group(element,
                                parent=self._group_control.FindPage(propgrid))

    def cb_copy(self, cut=False):
        pass

    def cb_paste(self, data):
        pass

    def _apply_settings(self):
        try:
            for i in range(self._group_control.GetPageCount()):
                page = self._group_control.GetPage(i)
                for name, (setting, val) in page.get_setting_values().items():
                    if isinstance(setting.value, list):
                        values = setting.value
                    else:
                        values = [setting.value]
                    for j, value in enumerate(values):
                        if not value.get_mutable():
                            # Do not update immutable settings
                            continue
                        realname, index = name.split(common.INDEX_CHAR)
                        prop = page.propgrid.GetProperty(name)
                        if not prop:
                            LOG.warning('Unable to find property %s in page',
                                        name)
                            continue
                        if int(index) == j:
                            try:
                                setting[j] = val
                            finally:
                                if setting[j].get_value() != val:
                                    # setting value modified or not accepted in
                                    # validate callback, propagate back to GUI
                                    prop.SetValue(setting[j].get_value())
            return True
        except Exception as e:
            LOG.exception('Failed to apply settings')
            wx.MessageBox(str(e), _('Error applying settings'),
                          wx.OK | wx.ICON_ERROR)
            return False

    def _apply_setting_group(self, all_values, group):
        for element in group.values():
            if isinstance(element, settings.RadioSetting):
                if element.value.get_mutable():
                    element.value = \
                        all_values[group.get_name()][element.get_name()]
            else:
                self._apply_setting_group(all_values, element)

    def _set_settings_cb(self, job):
        if isinstance(job.result, Exception):
            common.error_proof.show_error(str(job.result))

    def _reload(self):
        self.refresh()
        self.selected()

    def _remove_dead_settings(self, root):
        """Remove any settings that are immutable or uninitialized"""
        for e in root.values():
            if isinstance(e, settings.RadioSetting):
                # Immutable and uninitialized settings don't get sent to the
                # radio
                for value in e:
                    if not value.get_mutable():
                        LOG.debug('Skipping immutable %s', e.get_name())
                        del root[e]
                    elif not value.initialized:
                        LOG.debug('Skipping uninitialized %s', e.get_name())
                        del root[e]
            elif isinstance(e, settings.RadioSettingGroup):
                self._remove_dead_settings(e)

    def _changed(self, event):
        if not self._apply_settings():
            return
        settings = copy.deepcopy(self._settings)
        for g in settings:
            self._remove_dead_settings(g)
        self.do_radio(self._set_settings_cb, 'set_settings', settings)
        wx.PostEvent(self, common.EditorChanged(self.GetId()))
        if self._propgrid.needs_reload:
            LOG.warning('Settings grid needs a reload')
            wx.CallAfter(self._reload)

    def saved(self):
        for i in range(self._group_control.GetPageCount()):
            page = self._group_control.GetPage(i)
            page.saved()


class ChirpCloneSettingsEdit(ChirpSettingsEdit,
                             common.ChirpSyncEditor):
    pass


class ChirpLiveSettingsEdit(ChirpSettingsEdit,
                            common.ChirpAsyncEditor):
    pass
