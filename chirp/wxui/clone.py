import collections
import logging
import threading

import serial
import wx

from chirp import chirp_common
from chirp import directory
from chirp import platform
from chirp.ui import config
from chirp.wxui import common

LOG = logging.getLogger(__name__)
CONF = config.get()


class CloneThread(threading.Thread):
    def __init__(self, radio, dialog, fn):
        super(CloneThread, self).__init__()
        self._radio = radio
        self._dialog = dialog
        self._fn = getattr(self._radio, fn)
        self._radio.status_fn = self._status

    def _status(self, status):
        self._dialog._status(status)

    def run(self):
        try:
            self._fn()
        except Exception as e:
            LOG.error('Failed to clone: %s' % e)
            self._dialog.fail(str(e))
        else:
            self._dialog.complete()


class SettingsThread(threading.Thread):
    def __init__(self, radio, progdialog, settings=None):
        super(SettingsThread, self).__init__()
        self._radio = radio
        self._dialog = progdialog
        self.settings = settings
        self._dialog.SetRange(100)
        self.error = None

    def run(self):
        self._radio.pipe.open()
        try:
            self._run()
        except Exception as e:
            LOG.exception('Failed during setting operation')
            wx.CallAfter(self._dialog.Update, 100)
            self.error = str(e)
        finally:
            self._radio.pipe.close()

    def _run(self):
        if self.settings:
            msg = _('Applying settings')
        else:
            msg = _('Loading settings')
        wx.CallAfter(self._dialog.Update, 10, newmsg=msg)
        if self.settings:
            self._radio.set_settings(self.settings)
        else:
            self.settings = self._radio.get_settings()
        wx.CallAfter(self._dialog.Update, 100, newmsg=_('Complete'))


class ChirpCloneDialog(wx.Dialog):
    def __init__(self, *a, **k):
        super(ChirpCloneDialog, self).__init__(
            *a, title='Communicate with radio', **k)

        panel = wx.Panel(self)

        try:
            grid = wx.FlexGridSizer(3, 2)
        except TypeError:
            grid = wx.FlexGridSizer(2, 5, 0)

        def _add_grid(label, control):
            grid.Add(wx.StaticText(panel, label=label),
                     border=20, flag=wx.ALIGN_CENTER|wx.RIGHT|wx.LEFT)
            grid.Add(control, 1, flag=wx.EXPAND)

        ports = platform.get_platform().list_serial_ports()
        last_port = CONF.get('last_port', 'state')
        if last_port and last_port not in ports:
            ports.insert(0, last_port)
        elif not last_port:
            last_port = ports[0]
        self._port = wx.ComboBox(panel, choices=ports)
        self._port.SetValue(last_port)
        self.Bind(wx.EVT_COMBOBOX, self._selected_port, self._port)
        _add_grid('Port', self._port)

        self._vendor = wx.Choice(panel, choices=['Icom', 'Yaesu'])
        _add_grid('Vendor', self._vendor)
        self.Bind(wx.EVT_CHOICE, self._selected_vendor, self._vendor)

        self._model = wx.Choice(panel, choices=[])
        _add_grid('Model', self._model)
        self.Bind(wx.EVT_CHOICE, self._selected_model, self._model)

        self.gauge = wx.Gauge(panel)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)

        action = self._make_action(panel)

        hbox2.Add(action)
        self._action_button = action

        cancel = wx.Button(panel, wx.ID_CANCEL)
        hbox2.Add(cancel, flag=wx.RIGHT)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, proportion=0, flag=wx.ALIGN_CENTER|wx.TOP|wx.BOTTOM,
                 border=20)
        vbox.Add(self.gauge, flag=wx.EXPAND, border=10, proportion=1)
        vbox.Add(wx.StaticLine(panel), flag=wx.EXPAND|wx.TOP, border=10)
        vbox.Add(hbox2, proportion=0, flag=wx.ALIGN_RIGHT|wx.ALL, border=10)
        panel.SetSizer(vbox)

        self._vendors = collections.defaultdict(list)
        for rclass in directory.DRV_TO_RADIO.values():
            if (not issubclass(rclass, chirp_common.CloneModeRadio) and
                    not issubclass(rclass, chirp_common.LiveRadio)):
                continue
            self._vendors[rclass.VENDOR].append(rclass)
            for alias in rclass.ALIASES:
                self._vendors[alias.VENDOR].append(alias)

        self._vendor.Set(sorted(self._vendors.keys()))
        try:
            self.select_vendor_model(CONF.get('last_vendor', 'state'),
                                     CONF.get('last_model', 'state'))
        except ValueError as e:
            LOG.warning('Last vendor/model not found')

    def disable_model_select(self):
        self._vendor.Disable()
        self._model.Disable()

    def disable_running(self):
        self._port.Disable()
        self._action_button.Disable()

    def _persist_choices(self):
        CONF.set('last_vendor', self._vendor.GetStringSelection(), 'state')
        CONF.set('last_model', self._model.GetStringSelection(), 'state')
        CONF.set('last_port', self._port.GetValue(), 'state')

    def _selected_port(self, event):
        self._persist_choices()

    def _select_vendor(self, vendor):
        models = [x.MODEL for x in self._vendors[vendor]]
        self._model.Set(models)
        self._model.SetSelection(0)

    def _selected_vendor(self, event):
        self._select_vendor(event.GetString())
        self._persist_choices()

    def _selected_model(self, event):
        self._persist_choices()

    def select_vendor_model(self, vendor, model):
        self._vendor.SetSelection(self._vendor.GetItems().index(vendor))
        self._select_vendor(vendor)
        self._model.SetSelection(self._model.GetItems().index(model))

    def _status(self, status):
        def _safe_status():
            self.gauge.SetRange(status.max)
            self.gauge.SetValue(status.cur)

        wx.CallAfter(_safe_status)

    def complete(self):
        self._radio.pipe.close()
        wx.CallAfter(self.EndModal, wx.ID_OK)

    def fail(self, message):
        def safe_fail():
            wx.MessageBox(message,
                          'Error communicating with radio',
                          wx.ICON_ERROR)
            self.EndModal(wx.ID_CANCEL)

        wx.CallAfter(safe_fail)

    def get_selected_rclass(self):
        vendor = self._vendor.GetStringSelection()
        model = self._model.GetSelection()
        return self._vendors[vendor][model]


class ChirpDownloadDialog(ChirpCloneDialog):
    def _make_action(self, panel):
        start = wx.Button(panel, label='Download')
        start.Bind(wx.EVT_BUTTON, self._download)
        return start

    def _selected_model(self, event):
        super(ChirpDownloadDialog, self)._selected_model(event)
        rclass = self.get_selected_rclass()
        prompts = rclass.get_prompts()
        if prompts.pre_download:
            prompt = prompts.pre_download
        else:
            prompt = ''

        # FIXME: Handle download prompt here

    def _download(self, event):
        self.disable_model_select()
        self.disable_running()

        port = self._port.GetValue()
        rclass = self.get_selected_rclass()

        pipe = serial.Serial(port=port, baudrate=rclass.BAUD_RATE,
                             rtscts=rclass.HARDWARE_FLOW, timeout=0.25)
        try:
            self._radio = rclass(pipe)
        except Exception as e:
            self.fail(str(e))
            return

        if isinstance(self._radio, chirp_common.LiveRadio):
            self._radio = common.LiveAdapter(self._radio)

        self._radio.status_fn = self._status

        self._clone_thread = CloneThread(self._radio, self, 'sync_in')
        self._clone_thread.start()


class ChirpUploadDialog(ChirpCloneDialog):
    def __init__(self, radio, *a, **k):
        super(ChirpUploadDialog, self).__init__(*a, **k)
        self._radio = radio

        self.select_vendor_model(self._radio.VENDOR,
                                 self._radio.MODEL)

        if isinstance(self._radio, chirp_common.LiveRadio):
            self._radio = common.LiveAdapter(self._radio)

    def _make_action(self, panel):
        start = wx.Button(panel, label='Upload')
        start.Bind(wx.EVT_BUTTON, self._upload)
        self.disable_model_select()
        return start

    def _upload(self, event):
        self.disable_running()

        port = self._port.GetValue()

        baud = self._radio.BAUD_RATE
        if self._radio.pipe:
            baud = self._radio.pipe.baudrate

        pipe = serial.Serial(port=port, baudrate=baud,
                             rtscts=self._radio.HARDWARE_FLOW, timeout=0.25)
        self._radio.set_pipe(pipe)
        self._radio._status_fn = self._status

        self._clone_thread = CloneThread(self._radio, self, 'sync_out')
        self._clone_thread.start()
