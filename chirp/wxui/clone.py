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

import collections
import logging
import textwrap
import threading

import serial
from serial.tools import list_ports
import wx
import wx.lib.sized_controls

from chirp import chirp_common
from chirp import directory
from chirp.drivers import fake
from chirp.wxui import config
from chirp.wxui import common
from chirp.wxui import developer

LOG = logging.getLogger(__name__)
CONF = config.get()
HELPME = _('Help Me...')
CUSTOM = _('Custom...')

FAKES = {
    'Fake NOP': developer.FakeSerial(),
    'Fake Echo NOP': developer.FakeEchoSerial(),
    'Fake F7E': fake.FakeKenwoodSerial(),
}


class CloneThread(threading.Thread):
    def __init__(self, radio, dialog, fn):
        super(CloneThread, self).__init__()
        self._radio = radio
        self._dialog = dialog
        self._fn = getattr(self._radio, fn)
        self._radio.status_fn = self._status

    def stop(self):
        LOG.warning('Stopping clone thread')

        # Clear out our dialog reference, which should stop us from
        # eventing to a missing window, and reporting error, when we have
        # already been asked to cancel
        self._dialog = None

        # Close the serial, which should stop the clone soon
        self._radio.pipe.close()

    def _status(self, status):
        self._dialog._status(status)

    def run(self):
        try:
            self._fn()
        except Exception as e:
            if self._dialog:
                LOG.exception('Failed to clone: %s' % e)
                self._dialog.fail(str(e))
            else:
                LOG.warning('Clone failed after cancel: %s', e)
        else:
            if self._dialog:
                self._dialog.complete()
        finally:
            try:
                self._radio.pipe.close()
            except OSError:
                # If we were canceled and we have already closed an active
                # serial, this will fail with EBADF
                pass


# NOTE: This is the legacy settings thread that facilitates
# LiveAdapter to get/fetch settings.
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


def open_serial(port, rclass):
    if port.startswith('Fake'):
        return FAKES[port]
    if '://' in port:
        pipe = serial.serial_for_url(port, do_not_open=True)
        pipe.timeout = 0.25
        pipe.rtscts = rclass.HARDWARE_FLOW
        pipe.rts = rclass.WANTS_RTS
        pipe.dtr = rclass.WANTS_DTR
        pipe.open()
        pipe.baudrate = rclass.BAUD_RATE
    else:
        pipe = serial.Serial(baudrate=rclass.BAUD_RATE,
                             rtscts=rclass.HARDWARE_FLOW, timeout=0.25)
        pipe.rts = rclass.WANTS_RTS
        pipe.dtr = rclass.WANTS_DTR
        pipe.port = port
        pipe.open()

    LOG.debug('Serial opened: %s (rts=%s dtr=%s)',
              pipe, pipe.rts, pipe.dtr)
    return pipe


class ChirpRadioPromptDialog(wx.Dialog):
    def __init__(self, *a, **k):
        self.radio = k.pop('radio')
        self.prompt = k.pop('prompt')
        buttons = k.pop('buttons', wx.OK | wx.CANCEL)
        super().__init__(*a, **k)

        prompts = self.radio.get_prompts()
        self.message = getattr(prompts, self.prompt)

        if '\n' not in self.message:
            self.message = '\n'.join(textwrap.wrap(self.message))

        bs = self.CreateButtonSizer(buttons)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        instructions = wx.StaticText(self)
        instructions.SetLabelMarkup(self.message)
        vbox.Add(instructions,
                 border=20, flag=wx.ALL)
        self.cb = wx.CheckBox(
            self, label=_("Do not prompt again for %s") % (
                '%s %s' % (self.radio.VENDOR, self.radio.MODEL)))
        vbox.Add(self.cb, border=20, flag=wx.ALL)
        vbox.Add(bs, flag=wx.ALL, border=10)
        self.Fit()
        self.Centre()

    def persist_flag(self, radio, flag):
        key = '%s_%s' % (flag, directory.radio_class_id(radio))
        CONF.set_bool(key.lower(), not self.cb.IsChecked(), 'clone_prompts')

    def check_flag(self, radio, flag):
        key = '%s_%s' % (flag, directory.radio_class_id(radio))
        return CONF.get_bool(key.lower(), 'clone_prompts', True)

    def ShowModal(self):
        if not self.message:
            LOG.debug('No %s prompt for radio' % self.prompt)
            return wx.ID_OK
        if not self.check_flag(self.radio, self.prompt):
            LOG.debug('Prompt %s disabled for radio' % self.prompt)
            return wx.ID_OK
        LOG.debug('Showing %s prompt' % self.prompt)
        status = super().ShowModal()
        if status == wx.ID_OK:
            LOG.debug('Setting flag for prompt %s' % self.prompt)
            self.persist_flag(self.radio, self.prompt)
        else:
            LOG.debug('No flag change for %s' % self.prompt)
        return status


def port_label(port):
    if not port.description:
        return port.device
    elif port.description == 'n/a':
        return port.device
    elif port.device not in port.description:
        return '%s (%s)' % (port.description, port.device)
    else:
        return port.description


# Make this global so it sticks for a session
CUSTOM_PORTS = []


class ChirpCloneDialog(wx.Dialog):
    def __init__(self, *a, **k):
        super(ChirpCloneDialog, self).__init__(
            *a, title=_('Communicate with radio'), **k)
        self._clone_thread = None
        grid = wx.FlexGridSizer(2, 5, 5)
        grid.AddGrowableCol(1)
        bs = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        if CONF.get_bool('developer', 'state'):
            for fakeserial in FAKES.keys():
                if fakeserial not in CUSTOM_PORTS:
                    CUSTOM_PORTS.append(fakeserial)

        def _add_grid(label, control):
            grid.Add(wx.StaticText(self, label=label),
                     proportion=1, border=10,
                     flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
            grid.Add(control,
                     proportion=1, border=10,
                     flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

        self._port = wx.Choice(self, choices=[])
        self._port.SetMaxSize((50, -1))
        self.set_ports()
        self.Bind(wx.EVT_CHOICE, self._selected_port, self._port)
        _add_grid(_('Port'), self._port)

        self._vendor = wx.Choice(self, choices=['Icom', 'Yaesu'])
        _add_grid(_('Vendor'), self._vendor)
        self.Bind(wx.EVT_CHOICE, self._selected_vendor, self._vendor)

        self._model = wx.Choice(self, choices=[])
        _add_grid(_('Model'), self._model)
        self.Bind(wx.EVT_CHOICE, self._selected_model, self._model)

        self.gauge = wx.Gauge(self)

        self.Bind(wx.EVT_BUTTON, self._action)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, proportion=1,
                 flag=wx.TOP | wx.BOTTOM | wx.EXPAND,
                 border=20)
        self.status_msg = wx.StaticText(
            self, label='',
            style=(wx.ALIGN_CENTER_HORIZONTAL | wx.ST_NO_AUTORESIZE |
                   wx.ELLIPSIZE_END))
        vbox.Add(self.status_msg,
                 border=5, proportion=0,
                 flag=wx.EXPAND | wx.BOTTOM)
        vbox.Add(self.gauge, flag=wx.EXPAND | wx.RIGHT | wx.LEFT, border=10,
                 proportion=0)
        vbox.Add(wx.StaticLine(self), flag=wx.EXPAND | wx.ALL, border=5)
        vbox.Add(bs, flag=wx.ALL, border=10)
        self.SetSizer(vbox)
        self.Center()

        self._vendors = collections.defaultdict(list)
        for rclass in directory.DRV_TO_RADIO.values():
            if (not issubclass(rclass, chirp_common.CloneModeRadio) and
                    not issubclass(rclass, chirp_common.LiveRadio)):
                continue
            self._vendors[rclass.VENDOR].append(rclass)
            self._add_aliases(rclass)

        for models in self._vendors.values():
            models.sort(key=lambda x: '%s %s' % (x.MODEL, x.VARIANT))

        self._vendor.Set(sorted(self._vendors.keys()))
        try:
            self.select_vendor_model(CONF.get('last_vendor', 'state'),
                                     CONF.get('last_model', 'state'))
        except ValueError:
            LOG.warning('Last vendor/model not found')

        self.SetMinSize((400, 200))
        self.Fit()

    def set_ports(self, system_ports=None, select=None):
        if not system_ports:
            system_ports = list_ports.comports()

        # These are ports that we should never offer to the user because
        # they get picked up by the list but are not usable or relevant.
        filter_ports = [
            # MacOS unpaired bluetooth serial
            '/dev/cu.Bluetooth-Incoming-Port',
        ]

        self.ports = [(port.device, port_label(port))
                      for port in system_ports
                      if port.device not in filter_ports]
        self.ports.sort()

        favorite_ports = CONF.get('favorite_ports', 'state') or ''
        for port in favorite_ports.split(','):
            if port and port not in [x[0] for x in self.ports]:
                self.ports.insert(0, (port, port))

        for port in CUSTOM_PORTS:
            if port not in [x[0] for x in self.ports]:
                self.ports.insert(0, (port, port))

        if not select:
            select = CONF.get('last_port', 'state')

        if not self.ports:
            LOG.warning('No ports available; action will be disabled')
        okay_btn = self.FindWindowById(self.GetAffirmativeId())
        okay_btn.Enable(bool(self.ports))

        self._port.SetItems([x[1] for x in self.ports] +
                            [CUSTOM, HELPME])
        for device, name in self.ports:
            if device == select:
                self._port.SetStringSelection(name)
                break
        else:
            LOG.warning('Unable to select %r' % select)

    def get_selected_port(self):
        selected = self._port.GetStringSelection()
        for device, name in self.ports:
            if name == selected:
                return device
        LOG.warning('Did not find device for selected port %s' % selected)
        return selected

    def _port_assist(self, event):
        r = wx.MessageBox(
            _('Unplug your cable (if needed) and then click OK'),
            _('USB Port Finder'),
            style=wx.OK | wx.CANCEL | wx.OK_DEFAULT)
        if r == wx.CANCEL:
            return
        before = list_ports.comports()
        r = wx.MessageBox(
            _('Plug in your cable and then click OK'),
            _('USB Port Finder'),
            style=wx.OK | wx.CANCEL | wx.OK_DEFAULT)
        if r == wx.CANCEL:
            return
        after = list_ports.comports()
        changed = set(after) - set(before)
        found = None
        if not changed:
            wx.MessageBox(
                _('Unable to determine port for your cable. '
                  'Check your drivers and connections.'),
                _('USB Port Finder'))
            self.set_ports(after)
            return
        elif len(changed) == 1:
            found = list(changed)[0]
            wx.MessageBox(
                '%s\n%s' % (_('Your cable appears to be on port:'),
                            port_label(found)),
                _('USB Port Finder'))
        else:
            wx.MessageBox(
                _('More than one port found: %s') % ', '.join(changed),
                _('USB Port Finder'))
            self.set_ports(after)
            return
        self.set_ports(after, select=found.device)

    def _add_aliases(self, rclass):
        for alias in rclass.ALIASES:
            class DynamicRadioAlias(rclass):
                _orig_rclass = rclass
                VENDOR = alias.VENDOR
                MODEL = alias.MODEL
                VARIANT = alias.VARIANT

            self._vendors[alias.VENDOR].append(DynamicRadioAlias)

    def disable_model_select(self):
        self._vendor.Disable()
        self._model.Disable()

    def disable_running(self):
        self._port.Disable()
        self.FindWindowById(wx.ID_OK).Disable()

    def _persist_choices(self):
        CONF.set('last_vendor', self._vendor.GetStringSelection(), 'state')
        CONF.set('last_model', self._model.GetStringSelection(), 'state')
        CONF.set('last_port', self.get_selected_port(), 'state')

    def _selected_port(self, event):
        if self._port.GetStringSelection() == CUSTOM:
            port = wx.GetTextFromUser(_('Enter custom port:'),
                                      _('Custom Port'),
                                      parent=self)
            if port:
                CUSTOM_PORTS.append(port)
            self.set_ports(select=port or None)
            return
        elif self._port.GetStringSelection() == HELPME:
            self._port_assist(event)
            return
        self._persist_choices()

    def _select_vendor(self, vendor):
        models = [('%s %s' % (x.MODEL, x.VARIANT)).strip()
                  for x in self._vendors[vendor]]
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
            self.gauge.SetValue(min(status.cur, status.max))
            self.status_msg.SetLabel(status.msg)

        wx.CallAfter(_safe_status)

    def complete(self):
        self._radio.pipe.close()
        wx.CallAfter(self.EndModal, wx.ID_OK)

    def fail(self, message):
        def safe_fail():
            wx.MessageBox(message,
                          _('Error communicating with radio'),
                          wx.ICON_ERROR)
            self.cancel_action()
        wx.CallAfter(safe_fail)

    def cancel_action(self):
        if isinstance(self, ChirpDownloadDialog):
            self._vendor.Enable()
            self._model.Enable()
        self._port.Enable()
        s = chirp_common.Status()
        s.cur = 0
        s.max = 1
        s.msg = ''
        self._status(s)
        self.FindWindowById(wx.ID_OK).Enable()

    def get_selected_rclass(self):
        vendor = self._vendor.GetStringSelection()
        model = self._model.GetSelection()
        LOG.debug('Selected %r' % self._vendors[vendor][model])
        return self._vendors[vendor][model]


class ChirpDownloadDialog(ChirpCloneDialog):
    def _selected_model(self, event):
        super(ChirpDownloadDialog, self)._selected_model(event)
        rclass = self.get_selected_rclass()
        prompts = rclass.get_prompts()
        if prompts.experimental:
            d = ChirpRadioPromptDialog(self,
                                       title=_('Experimental driver'),
                                       buttons=wx.OK,
                                       radio=rclass,
                                       prompt='experimental')
            d.ShowModal()

    def _action(self, event):
        if event.GetEventObject().GetId() == wx.ID_CANCEL:
            if self._clone_thread:
                self._clone_thread.stop()
            self.EndModal(event.GetEventObject().GetId())
            return

        self._persist_choices()
        self.disable_model_select()
        self.disable_running()

        port = self.get_selected_port()
        LOG.debug('Using port %r' % port)
        rclass = self.get_selected_rclass()

        prompts = rclass.get_prompts()
        if prompts.info:
            d = ChirpRadioPromptDialog(self,
                                       title=_('Radio information'),
                                       radio=rclass,
                                       prompt='info')
            if d.ShowModal() != wx.ID_OK:
                self.cancel_action()
                return
        if prompts.pre_download:
            d = ChirpRadioPromptDialog(self,
                                       title=_('Download instructions'),
                                       radio=rclass,
                                       prompt='pre_download')
            if d.ShowModal() != wx.ID_OK:
                self.cancel_action()
                return

        try:
            self._radio = rclass(open_serial(port, rclass))
        except Exception as e:
            LOG.exception('Failed to open serial: %s' % e)
            self.fail(str(e))
            return

        if isinstance(self._radio, chirp_common.LiveRadio):
            if CONF.get_bool('live_adapter', 'state', False):
                # Use LiveAdapter to make LiveRadio behave like CloneMode
                self._radio = common.LiveAdapter(self._radio)
            else:
                # Live radios are live
                # FIXME: This needs to make sure we can talk to the radio first
                self.EndModal(wx.ID_OK)
                return

        self._radio.status_fn = self._status

        self._clone_thread = CloneThread(self._radio, self, 'sync_in')
        self._clone_thread.start()


class ChirpUploadDialog(ChirpCloneDialog):
    def __init__(self, radio, *a, **k):
        super(ChirpUploadDialog, self).__init__(*a, **k)
        self._radio = radio

        self.select_vendor_model(
            self._radio.VENDOR,
            ('%s %s' % (self._radio.MODEL, self._radio.VARIANT)).strip())
        self.disable_model_select()

        if isinstance(self._radio, chirp_common.LiveRadio):
            self._radio = common.LiveAdapter(self._radio)

    def _action(self, event):
        if event.GetEventObject().GetId() == wx.ID_CANCEL:
            if self._clone_thread:
                self._clone_thread.stop()
            self.EndModal(event.GetEventObject().GetId())
            return

        self._persist_choices()
        self.disable_running()
        port = self.get_selected_port()

        prompts = self._radio.get_prompts()
        if prompts.info:
            d = ChirpRadioPromptDialog(self,
                                       title=_('Radio information'),
                                       radio=self._radio,
                                       prompt='info')
            if d.ShowModal() != wx.ID_OK:
                self.cancel_action()
                return

        if prompts.display_pre_upload_prompt_before_opening_port:
            s = None
        else:
            LOG.debug('Opening serial %r before upload prompt' % port)
            s = open_serial(port, self._radio)

        if prompts.pre_upload:
            d = ChirpRadioPromptDialog(self,
                                       title=_('Upload instructions'),
                                       radio=self._radio,
                                       prompt='pre_upload')
            if d.ShowModal() != wx.ID_OK:
                self.cancel_action()
                if s:
                    s.close()
                return

        baud = self._radio.BAUD_RATE
        if self._radio.pipe:
            baud = self._radio.pipe.baudrate

        if s is None:
            LOG.debug('Opening serial %r after upload prompt' % port)
            s = open_serial(port, self._radio)

        try:
            self._radio.set_pipe(s)
            # Short-circuit straight to the previous baudrate for variable-
            # rate radios to sync back up faster
            self._radio.pipe.baudrate = baud
        except Exception as e:
            self.fail(str(e))
            return

        self._radio._status_fn = self._status

        self._clone_thread = CloneThread(self._radio, self, 'sync_out')
        self._clone_thread.start()
