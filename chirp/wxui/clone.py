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
import platform
import re
import textwrap
import threading
import webbrowser

import serial
from serial.tools import list_ports
import wx
import wx.lib.sized_controls

from chirp import chirp_common
from chirp import directory
from chirp.drivers import fake
from chirp import errors
from chirp.wxui import config
from chirp.wxui import common
from chirp.wxui import developer
from chirp.wxui import serialtrace

_ = wx.GetTranslation
LOG = logging.getLogger(__name__)
CONF = config.get()
HELPME = _('Help Me...')
CUSTOM = _('Custom...')
ID_RECENT = wx.NewId()


def is_prolific_warning(string):
    return 'PL2303' in string and 'CONTACT YOUR SUPPLIER' in string


def get_model_label(rclass):
    detected = ','.join(set([
        detected_value(rclass, m)
        for m in rclass.detected_models(include_self=False)]))
    if len(detected) > (32 - 5):
        detected = 'others'
    return detected


def get_fakes():
    return {
        'Fake NOP': developer.FakeSerial,
        'Fake Echo NOP': developer.FakeEchoSerial,
        'Fake F7E': fake.FakeKenwoodSerial,
        'Fake UV17': fake.FakeUV17Serial,
        'Fake UV17Pro': fake.FakeUV17ProSerial,
        'Fake AT778': developer.FakeAT778,
        'Fake Open Error': developer.FakeErrorOpenSerial,
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
        except errors.SpecificRadioError as e:
            if self._dialog:
                LOG.exception('Failed to clone: %s', e)
                self._dialog.fail(e)
            else:
                LOG.warning('Clone failed after cancel: %s', e)
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
        return get_fakes()[port]()
    if '://' in port:
        pipe = serial.serial_for_url(port, do_not_open=True)
        pipe.timeout = 0.25
        pipe.rtscts = rclass.HARDWARE_FLOW
        pipe.rts = rclass.WANTS_RTS
        pipe.dtr = rclass.WANTS_DTR
        pipe.open()
        pipe.baudrate = rclass.BAUD_RATE
    else:
        pipe = serialtrace.SerialTrace(
            baudrate=rclass.BAUD_RATE,
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
        self.rconfig = config.get_for_radio(self.radio)
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
        if self.prompt == 'experimental':
            risk_warning = wx.StaticText(self)
            risk_warning.SetLabelMarkup(_('Do you accept the risk?'))
            vbox.Add(risk_warning, border=20, flag=wx.ALL)
        self.cb = wx.CheckBox(
            self, label=_("Do not prompt again for %s") % (
                '%s %s' % (self.radio.VENDOR, self.radio.MODEL)))
        vbox.Add(self.cb, border=20, flag=wx.ALL)
        vbox.Add(bs, flag=wx.ALL, border=10)
        self.Fit()
        self.Centre()

    def persist_flag(self, radio, flag):
        key = 'prompt_%s' % flag.lower()
        self.rconfig.set_bool(key, not self.cb.IsChecked())
        oldkey = '%s_%s' % (flag, directory.radio_class_id(radio))
        if CONF.is_defined(oldkey, 'clone_prompts'):
            CONF.remove_option(oldkey, 'clone_prompts')

    def check_flag(self, radio, flag):
        key = 'prompt_%s' % flag.lower()
        if not self.rconfig.is_defined(key):
            # FIXME: Remove this compatibility at some point
            oldkey = '%s_%s' % (flag, directory.radio_class_id(radio))
            return CONF.get_bool(oldkey.lower(), 'clone_prompts', True)
        return self.rconfig.get_bool(key, default=True)

    def ShowModal(self):
        if not self.message:
            LOG.debug('No %s prompt for radio' % self.prompt)
            return wx.ID_OK
        if not self.check_flag(self.radio, self.prompt):
            LOG.debug('Prompt %s disabled for radio' % self.prompt)
            return wx.ID_OK
        LOG.debug('Showing %s prompt' % self.prompt)
        status = super().ShowModal()
        if status in (wx.ID_OK, wx.ID_YES):
            LOG.debug('Setting flag for prompt %s' % self.prompt)
            self.persist_flag(self.radio, self.prompt)
        else:
            LOG.debug('No flag change for %s' % self.prompt)
        return status


def port_label(port):
    if platform.system() == 'Windows':
        # The OS format for description is "Long Name (COMn)", so use
        # port: desc to make the port visible early in the string without
        # changing the description format.
        label_fmt = '%(dev)s: %(desc)s'
    else:
        label_fmt = '%(desc)s (%(dev)s)'
    dev = port.device
    if dev.startswith('/dev/'):
        dev = dev.split('/dev/')[1]
    if not port.description:
        return dev
    elif port.description == 'n/a':
        return dev
    else:
        return label_fmt % ({'desc': port.description,
                             'dev': dev})


def port_sort_key(port):
    key = port.device
    if platform.system() == 'Windows':
        try:
            m = re.match('^COM([0-9]+)$', port.device)
            if m:
                key = 'COM%08i' % int(m.group(1))
        except Exception as e:
            LOG.warning('Failed to stable format %s: %s', port.device, e)

    return key


def model_value(rclass):
    return ('%s %s' % (rclass.MODEL, rclass.VARIANT)).strip()


def detected_value(parent_rclass, rclass):
    """Try to calculate a label for detected classes.

    This should be short and only represent the difference between them (like
    a VARIANT or different MODEL).
    """
    if parent_rclass.MODEL != rclass.MODEL:
        # If the model is different, use that
        label = rclass.MODEL
        # If the detected class is a modified MODEL (i.e. 'RT95' and 'RT95 VOX'
        # then strip off the prefix and the delimiter, if any.
        if label.startswith(parent_rclass.MODEL):
            label = label.replace(parent_rclass.MODEL, '').strip(' -_')
    else:
        # Assume the VARIANT is the distinguisher
        label = rclass.VARIANT

    # In case the detected class is a different vendor, prefix that
    if parent_rclass.VENDOR != rclass.VENDOR:
        label = '%s %s' % (rclass.VENDOR, label)

    label = label.strip()
    if not label:
        LOG.error('Calculated blank detected value of %s from %s',
                  rclass, parent_rclass)
    return label


# Make this global so it sticks for a session
CUSTOM_PORTS = []


class ChirpCloneDialog(wx.Dialog):
    def __init__(self, *a, **k):
        allow_detected_models = k.pop('allow_detected_models', False)
        super(ChirpCloneDialog, self).__init__(
            *a, title=_('Communicate with radio'), **k)
        self._clone_thread = None
        grid = wx.FlexGridSizer(2, 5, 5)
        grid.AddGrowableCol(1)
        bs = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        if developer.developer_mode():
            for fakeserial in get_fakes().keys():
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

        panel = wx.Panel(self)
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        panel.SetSizer(hbox)
        self._vendor = wx.Choice(panel, choices=['Icom', 'Yaesu'])
        self.Bind(wx.EVT_CHOICE, self._selected_vendor, self._vendor)
        self._recent = wx.Button(panel, ID_RECENT, label=_('Recent...'))
        self._recent.Enable(bool(CONF.get('recent_models', 'state')))
        hbox.Add(self._vendor, proportion=1, border=10, flag=wx.RIGHT)
        hbox.Add(self._recent)
        _add_grid(_('Vendor'), panel)

        self._model_choices = []
        self._model = wx.Choice(self, choices=self._model_choices)
        _add_grid(_('Model'), self._model)
        self.Bind(wx.EVT_CHOICE, self._selected_model, self._model)

        self.gauge = wx.Gauge(self)

        self.Bind(wx.EVT_BUTTON, self._action)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, proportion=1,
                 flag=wx.TOP | wx.BOTTOM | wx.EXPAND,
                 border=20)
        self.model_msg = wx.StaticText(
            self,
            label='',
            style=(wx.ALIGN_CENTER_HORIZONTAL | wx.ST_NO_AUTORESIZE |
                   wx.ELLIPSIZE_END))
        self.status_msg = wx.StaticText(
            self, label='',
            style=(wx.ALIGN_CENTER_HORIZONTAL | wx.ST_NO_AUTORESIZE |
                   wx.ELLIPSIZE_END))
        vbox.Add(self.status_msg,
                 border=5, proportion=0,
                 flag=wx.EXPAND | wx.BOTTOM)
        vbox.Add(self.gauge, flag=wx.EXPAND | wx.RIGHT | wx.LEFT, border=10,
                 proportion=0)
        vbox.Add(self.model_msg,
                 border=5, proportion=0,
                 flag=wx.EXPAND | wx.BOTTOM)
        vbox.Add(wx.StaticLine(self), flag=wx.EXPAND | wx.ALL, border=5)
        vbox.Add(bs, flag=wx.ALL, border=10)
        self.SetSizer(vbox)
        self.Center()

        self._vendors = collections.defaultdict(list)
        for rclass in directory.DRV_TO_RADIO.values():
            if (not issubclass(rclass, chirp_common.CloneModeRadio) and
                    not issubclass(rclass, chirp_common.LiveRadio)):
                continue
            if (getattr(rclass, '_DETECTED_BY', None) and
                    not allow_detected_models):
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
            LOG.warning('Last vendor/model (%s/%s) not found',
                        CONF.get('last_vendor', 'state'),
                        CONF.get('last_model', 'state'))

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
            '/dev/cu.debug-console',
            '/dev/cu.wlan-debug',
        ]

        LOG.debug('All system ports: %s', [x.__dict__ for x in system_ports])
        self.ports = [(port.device, port_label(port))
                      for port in sorted(system_ports,
                                         key=port_sort_key)
                      if port.device not in filter_ports]

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
            if self.ports:
                port = self.ports[0]
                self._port.SetStringSelection(port[0])
            else:
                port = '(no ports available)'
            LOG.warning('Last port %r is unavailable, defaulting to %s',
                        select, port)

    def get_selected_port(self):
        selected = self._port.GetStringSelection()
        for device, name in self.ports:
            if name == selected:
                return device
        LOG.warning('Did not find device for selected port %s' % selected)
        return selected

    def set_selected_port(self, devname):
        for device, name in self.ports:
            if device == devname:
                self._port.SetStringSelection(name)
                return True
        else:
            LOG.debug('Port %s not in current list', devname)

    def _port_assist(self, event):
        r = wx.MessageBox(
            _('Unplug your cable (if needed) and then click OK'),
            _('USB Port Finder'),
            style=wx.OK | wx.CANCEL | wx.OK_DEFAULT, parent=self)
        if r == wx.CANCEL:
            return
        before = list_ports.comports()
        r = wx.MessageBox(
            _('Plug in your cable and then click OK'),
            _('USB Port Finder'),
            style=wx.OK | wx.CANCEL | wx.OK_DEFAULT, parent=self)
        if r == wx.CANCEL:
            return
        after = list_ports.comports()
        changed = set(after) - set(before)
        found = None
        if not changed:
            wx.MessageBox(
                _('Unable to determine port for your cable. '
                  'Check your drivers and connections.'),
                _('USB Port Finder'), parent=self)
            self.set_ports(after)
            return
        elif len(changed) == 1:
            found = list(changed)[0]
            wx.MessageBox(
                '%s\n%s' % (_('Your cable appears to be on port:'),
                            port_label(found)),
                _('USB Port Finder'), parent=self)
        else:
            wx.MessageBox(
                _('More than one port found: %s') % ', '.join(changed),
                _('USB Port Finder'), parent=self)
            self.set_ports(after)
            return
        self.set_ports(after, select=found.device)

    def _prolific_assist(self, event):
        r = wx.MessageBox(
            _('Your Prolific-based USB device will not work without '
              'reverting to an older version of the driver. Visit the '
              'CHIRP website to read more about how to resolve this?'),
            _('Prolific USB device'),
            style=wx.YES | wx.NO | wx.YES_DEFAULT, parent=self)
        if r == wx.YES:
            webbrowser.open(
                'https://chirpmyradio.com/projects/chirp/wiki/'
                'ProlificDriverDeprecation')

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
        self._recent.Disable()

    def enable_model_select(self):
        self._vendor.Enable()
        self._model.Enable()
        self._recent.Enable()

    def disable_running(self):
        self._port.Disable()
        self.FindWindowById(wx.ID_OK).Disable()

    def enable_running(self):
        self._port.Enable()
        self.FindWindowById(wx.ID_OK).Enable()

    def _persist_choices(self):
        raise NotImplementedError()

    def _selected_port(self, event):
        okay_btn = self.FindWindowById(self.GetAffirmativeId())
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
        elif is_prolific_warning(self._port.GetStringSelection()):
            self._prolific_assist(event)
            okay_btn.Enable(False)
            return
        self._persist_choices()
        okay_btn.Enable(True)

    def _select_vendor(self, vendor):
        display_models = []
        actual_models = []
        for rclass in self._vendors[vendor]:
            display = model_value(rclass)
            actual_models.append(display)
            detected = get_model_label(rclass)
            if detected:
                display += ' (+ %s)' % detected
            display_models.append(display)

        self._model_choices = actual_models
        self._model.Set(display_models)
        self._model.SetSelection(0)

    def _do_recent(self):
        recent = CONF.get('recent_models', 'state')
        if recent:
            recent = recent.split(';')
        else:
            recent = []
        recent_strs = ['%s %s' % tuple(vm.split(':', 1)) for vm in recent]
        d = wx.SingleChoiceDialog(self,
                                  _('Choose a recent model'),
                                  _('Recent'),
                                  recent_strs)
        box = d.GetSizer()
        panel = wx.Panel(d)
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        panel.SetSizer(hbox)
        box.Insert(box.GetItemCount() - 1, panel)

        def remove_selected(event):
            listbox = [x for x in d.GetChildren()
                       if isinstance(x, wx.ListBox)][0]
            idx = listbox.GetSelection()
            listbox.Delete(idx)
            del recent_strs[idx]
            del recent[idx]
            CONF.set('recent_models', ';'.join(recent), 'state')
            listbox.SetSelection(max(0, idx - 1))

        always = wx.CheckBox(panel, label=_('Always start with recent list'))
        always.SetValue(CONF.get_bool('always_start_recent', 'state'))
        remove = wx.Button(panel, label=_('Remove'))
        remove.SetToolTip(_('Remove selected model from list'))
        remove.Bind(wx.EVT_BUTTON, remove_selected)
        hbox.Add(always, border=10, flag=wx.ALL | wx.EXPAND)
        hbox.Add(remove, border=10, flag=wx.ALL)

        d.SetSize((400, 400))
        d.SetMinSize((400, 400))
        d.SetMaxSize((400, 400))
        d.Center()
        c = d.ShowModal()
        if c == wx.ID_OK and recent:
            vendor, model = recent[d.GetSelection()].split(':')
            self.select_vendor_model(vendor, model)
            CONF.set_bool('always_start_recent', always.GetValue(), 'state')

    def _selected_vendor(self, event):
        self._select_vendor(event.GetString())
        self._persist_choices()
        self._select_port_for_model()

    def _selected_model(self, event):
        self._persist_choices()
        self._select_port_for_model()

    def select_vendor_model(self, vendor, model):
        self._vendor.SetSelection(self._vendor.GetItems().index(vendor))
        self._select_vendor(vendor)
        self._model.SetSelection(self._model_choices.index(model))
        self._select_port_for_model()

    def _select_port_for_model(self):
        vendor = self._vendor.GetStringSelection()
        model = self._model.GetStringSelection()

        rclass = self.get_selected_rclass()
        rconfig = config.get_for_radio(rclass)
        last_port = rconfig.get('last_port')
        if last_port and self.set_selected_port(last_port):
            LOG.debug('Automatically chose last-used port %s for %s %s',
                      last_port, vendor, model)
        else:
            LOG.debug('No recent/available port for %s %s', vendor, model)

    def _remember_port_for_selected(self):
        rclass = self.get_selected_rclass()
        rconfig = config.get_for_radio(rclass)
        port = self.get_selected_port()
        rconfig.set('last_port', port)
        LOG.debug('Recorded last-used port %s for %s %s',
                  port, rclass.VENDOR, rclass.MODEL)

    def _status(self, status):
        def _safe_status():
            self.gauge.SetRange(status.max)
            self.gauge.SetValue(min(status.cur, status.max))
            self.status_msg.SetLabel(status.msg)

        wx.CallAfter(_safe_status)

    def complete(self):
        self._radio.pipe.close()
        wx.CallAfter(self.EndModal, wx.ID_OK)

    def fail(self, error):
        def safe_fail():
            common.error_proof.show_error(
                error, parent=self,
                title=_('Error communicating with radio'))
            if isinstance(self, ChirpDownloadDialog):
                self.enable_model_select()
            self.enable_running()
        wx.CallAfter(safe_fail)

    def cancel_action(self):
        if isinstance(self, ChirpDownloadDialog):
            self.enable_model_select()
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

    def _action(self, event):
        id = event.GetEventObject().GetId()
        if id == wx.ID_CANCEL:
            if self._clone_thread:
                self._clone_thread.stop()
            self.EndModal(id)
            return
        try:
            self._actual_action(event)
        except Exception as e:
            self.fail(str(e))
            return


class ChirpDownloadDialog(ChirpCloneDialog):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        if (CONF.get_bool('always_start_recent', 'state') and
                CONF.get('recent_models', 'state')):
            self._do_recent()
        # Clean up old-style port recall
        CONF.remove_section('port_recall')

    def _selected_model(self, event):
        super(ChirpDownloadDialog, self)._selected_model(event)
        rclass = self.get_selected_rclass()
        prompts = rclass.get_prompts()
        self.model_msg.SetLabel('')
        if prompts.experimental:
            d = ChirpRadioPromptDialog(
                self,
                title=_('Experimental driver'),
                buttons=wx.YES_NO | wx.NO_DEFAULT,
                radio=rclass,
                prompt='experimental')
            d.SetAffirmativeId(wx.ID_YES)
            d.SetEscapeId(wx.ID_NO)
            r = d.ShowModal()
            if r == wx.ID_CANCEL:
                LOG.info('User did not accept experimental risk for %s',
                         rclass)
                self.FindWindowById(wx.ID_OK).Disable()
            else:
                LOG.info('User accepted experimental risk for %s',
                         rclass)
                self.FindWindowById(wx.ID_OK).Enable()

    def _actual_action(self, event):
        id = event.GetEventObject().GetId()
        if id == ID_RECENT:
            self._do_recent()
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

        serial = open_serial(port, rclass)

        # See if the driver detects we should be using a different radio class
        # to communicate with this model
        try:
            rclass = rclass.detect_from_serial(serial)
            LOG.info('Detected %s from serial', rclass)
        except NotImplementedError:
            pass
        except errors.RadioError as e:
            LOG.error('Radio serial detection failed: %s', e)
            self.fail(str(e))
            return
        except Exception as e:
            LOG.exception('Exception during detection: %s', e)
            self.fail(_('Internal driver error'))
            return

        self.model_msg.SetLabel('%s %s %s' % (
            rclass.VENDOR, rclass.MODEL, rclass.VARIANT))

        self._remember_port_for_selected()

        try:
            self._radio = rclass(serial)
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

    def _persist_choices(self):
        # On download, persist the selections from the actual UI boxes
        CONF.set('last_vendor', self._vendor.GetStringSelection(), 'state')
        CONF.set('last_model', self._model_choices[self._model.GetSelection()],
                 'state')
        CONF.set('last_port', self.get_selected_port(), 'state')
        recent = CONF.get('recent_models', 'state')
        if recent:
            recent = recent.split(';')
        else:
            recent = []
        modelstr = '%s:%s' % (self._vendor.GetStringSelection(),
                              self._model_choices[self._model.GetSelection()])
        if modelstr in recent:
            recent.remove(modelstr)
        recent.insert(0, modelstr)
        recent = recent[:10]
        CONF.set('recent_models', ';'.join(recent), 'state')


class ChirpUploadDialog(ChirpCloneDialog):
    def __init__(self, radio, *a, **k):
        super(ChirpUploadDialog, self).__init__(*a, allow_detected_models=True,
                                                **k)
        self._radio = radio

        self.select_vendor_model(self._radio.VENDOR, model_value(self._radio))
        self.disable_model_select()

        if isinstance(self._radio, chirp_common.LiveRadio):
            self._radio = common.LiveAdapter(self._radio)

    def _actual_action(self, event):
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

        self._remember_port_for_selected()

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

    def _persist_choices(self):
        # On upload, we may have a detected-only subclass, which won't be
        # selectable normally. If so, use the detected_by instead of the
        # actual driver
        parent = getattr(self._radio, '_DETECTED_BY', None)
        model = model_value(parent or self._radio)
        CONF.set('last_vendor', self._vendor.GetStringSelection(), 'state')
        CONF.set('last_model', model, 'state')
        CONF.set('last_port', self.get_selected_port(), 'state')
