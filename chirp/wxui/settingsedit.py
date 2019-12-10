import logging

import wx
import wx.dataview

from chirp import settings
from chirp.wxui import clone
from chirp.wxui import common

LOG = logging.getLogger(__name__)


class ChirpSettingsEdit(common.ChirpEditor):
    def __init__(self, radio, *a, **k):
        super(ChirpSettingsEdit, self).__init__(*a, **k)

        self._radio = radio
        self._settings = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self._pre_propgrid_hook(sizer)

        self._group_control = wx.Listbook(self, style=wx.LB_LEFT)
        sizer.Add(self._group_control, 1, wx.EXPAND)

        self._initialized = False
        self._group_control.Bind(wx.EVT_PAINT, self._activate)

    def _activate(self, event):
        if not self._initialized:
            self._initialized = True
            wx.CallAfter(self._initialize)

    def _load_settings(self):
        for group in self._settings:
            self._add_group(group)
        self._group_control.Layout()

    def _add_group(self, group):
        propgrid = common.ChirpSettingGrid(group, self._group_control)
        self.Bind(common.EVT_EDITOR_CHANGED, self._changed, propgrid)
        LOG.debug('Adding page for %s' % group.get_shortname())
        self._group_control.AddPage(propgrid, group.get_shortname())

        for element in group.values():
            if not isinstance(element, settings.RadioSetting):
                self._add_group(element)

    def cb_copy(self, cut=False):
        pass

    def cb_paste(self, data):
        pass

    def _apply_settings(self):
        try:
            all_values = {}
            for i in range(self._group_control.GetPageCount()):
                page = self._group_control.GetPage(i)
                all_values.update(page.get_values())
            for group in self._settings:
                self._apply_setting_group(all_values, group)
            return True
        except Exception as e:
            LOG.exception('Failed to apply settings')
            wx.MessageBox(str(e), 'Error applying settings',
                          wx.OK | wx.ICON_ERROR)
            return False

    def _apply_setting_group(self, all_values, group):
        for element in group.values():
            if isinstance(element, settings.RadioSetting):
                if element.value.get_mutable():
                    element.value = all_values[element.get_name()]
            else:
                self._apply_setting_group(all_values, element)

    def _changed(self, event):
        wx.PostEvent(self, common.EditorChanged(self.GetId()))

    def saved(self):
        for i in range(self._group_control.GetPageCount()):
            page = self._group_control.GetPage(i)
            page.saved()


class ChirpCloneSettingsEdit(ChirpSettingsEdit):

    def __init__(self, *a, **k):
        super(ChirpCloneSettingsEdit, self).__init__(*a, **k)

        self._settings = self._radio.get_settings()

    def _initialize(self):
        self._load_settings()

    def _pre_propgrid_hook(self, sizer):
        pass

    def _changed(self, event):
        if not self._apply_settings():
            return
        self._radio.set_settings(self._settings)
        super(ChirpCloneSettingsEdit, self)._changed(event)


class ChirpLiveSettingsEdit(ChirpSettingsEdit):
    def _pre_propgrid_hook(self, sizer):
        buttons = wx.Panel(self)
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        buttons.SetSizer(hbox)
        sizer.Add(buttons, 0, flag=wx.ALIGN_RIGHT)

        self._apply_btn = wx.Button(buttons, wx.ID_APPLY)
        hbox.Add(self._apply_btn, 0,
                  flag=wx.ALIGN_RIGHT|wx.ALL, border=10)
        self._apply_btn.Disable()
        self._apply_btn.Bind(wx.EVT_BUTTON, self._apply_settings_button)

    def _apply_setting_edit(self):
        # Do not apply settings during edit for live radios
        pass

    def _changed(self, event):
        self._apply_btn.Enable()
        # Do not send the changed event for live radios

    def saved(self):
        # Do not allow saved event to change modified statuses
        pass

    def _initialize(self):
        LOG.debug('Loading settings for live radio')
        prog = wx.ProgressDialog('Loading Settings', 'Please wait...', 100,
                                 parent=self)
        thread = clone.SettingsThread(self._radio, prog)
        thread.start()
        prog.ShowModal()
        LOG.debug('Settings load complete')
        self._settings = thread.settings
        self._load_settings()

    def _apply_settings_button(self, event):
        if not self._apply_settings():
            return

        prog = wx.ProgressDialog('Applying Settings', 'Please wait...', 100,
                                 parent=self)
        thread = clone.SettingsThread(self._radio, prog, self._settings)
        thread.start()
        prog.ShowModal()

        if thread.error:
            wx.MessageBox('Error applying settings: %s' % thread.error,
                          'Error',
                          wx.OK | wx.ICON_ERROR)
        else:
            self._apply_btn.Disable()
            super(ChirpLiveSettingsEdit, self).saved()
