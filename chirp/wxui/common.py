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
import threading

import wx

from chirp import chirp_common
from chirp.drivers import generic_csv
from chirp import errors
from chirp import settings
from chirp.wxui import radiothread

LOG = logging.getLogger(__name__)

CHIRP_DATA_MEMORY = wx.DataFormat('x-chirp/memory-channel')
EditorChanged, EVT_EDITOR_CHANGED = wx.lib.newevent.NewCommandEvent()
StatusMessage, EVT_STATUS_MESSAGE = wx.lib.newevent.NewCommandEvent()
INDEX_CHAR = settings.BANNED_NAME_CHARACTERS[0]

# This is a lock that can be used to exclude edit-specific operations
# from happening at the same time, like radiothread async
# operations. This needs to be local to the thing with the wx.Grid as
# its child, which is the chirp main window in our case. Making this
# global is technically too broad, but in reality, it's equivalent for
# us at the moment, and this is easier.
EDIT_LOCK = threading.Lock()


class LiveAdapter(generic_csv.CSVRadio):
    FILE_EXTENSION = 'img'

    def __init__(self, liveradio):
        # Python2 old-style class compatibility
        generic_csv.CSVRadio.__init__(self, None)
        self._liveradio = liveradio
        self.VENDOR = liveradio.VENDOR
        self.MODEL = liveradio.MODEL
        self.VARIANT = liveradio.VARIANT
        self.BAUD_RATE = liveradio.BAUD_RATE
        self.HARDWARE_FLOW = liveradio.HARDWARE_FLOW
        self.pipe = liveradio.pipe
        self._features = self._liveradio.get_features()

    def get_features(self):
        return self._features

    def set_pipe(self, pipe):
        self.pipe = pipe
        self._liveradio.pipe = pipe

    def sync_in(self):
        for i in range(*self._features.memory_bounds):
            mem = self._liveradio.get_memory(i)
            self.set_memory(mem)
            status = chirp_common.Status()
            status.max = self._features.memory_bounds[1]
            status.cur = i
            status.msg = 'Cloning'
            self.status_fn(status)

    def sync_out(self):
        # FIXME: Handle errors
        for i in range(*self._features.memory_bounds):
            mem = self.get_memory(i)
            if mem.freq == 0:
                # Convert the CSV notion of emptiness
                try:
                    self._liveradio.erase_memory(i)
                except errors.RadioError as e:
                    LOG.error(e)
            else:
                try:
                    self._liveradio.set_memory(mem)
                except errors.RadioError as e:
                    LOG.error(e)
            status = chirp_common.Status()
            status.max = self._features.memory_bounds[1]
            status.cur = i
            status.msg = _('Cloning')
            self.status_fn(status)

    def get_settings(self):
        return self._liveradio.get_settings()

    def set_settings(self, settings):
        return self._liveradio.set_settings(settings)


class ChirpEditor(wx.Panel):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setup_radio_interface()
        self.wait_dialog = None

    def start_wait_dialog(self, message):
        if self.wait_dialog:
            LOG.error('Wait dialog already in progress!')
            return

        self.wait_dialog = wx.ProgressDialog(_('Please wait'), message, 100,
                                             parent=self)
        wx.CallAfter(self.wait_dialog.Show)

    def bump_wait_dialog(self, value=None, message=None):
        if value:
            wx.CallAfter(self.wait_dialog.Update, value, newmsg=message)
        else:
            wx.CallAfter(self.wait_dialog.Pulse, message)

    def stop_wait_dialog(self):
        def cb():
            if self.wait_dialog:
                self.wait_dialog.Destroy()
                self.wait_dialog = None

        wx.CallAfter(cb)

    def status_message(self, message):
        wx.PostEvent(self, StatusMessage(self.GetId(), message=message))

    def refresh(self):
        pass

    def cb_copy(self, cut=False):
        pass

    def cb_paste(self, data):
        pass

    def cb_goto(self, number):
        pass

    def cb_find(self, text):
        pass

    def select_all(self):
        pass

    def saved(self):
        pass

    def selected(self):
        pass

    def get_scroll_pos(self):
        return None

    def set_scroll_pos(self, pos):
        LOG.warning('Editor %s does not support set_scroll_pos()' % (
            self.__class__.__name__))


class ChirpSyncEditor:
    """Radio interface that makes synchronous calls.

    This executes RadioJob requests synchronously in the calling
    thread and directly spawns the callback. To be used only with
    radio drivers that manipulate in-memory state.
    """
    def do_radio(self, cb, fn, *a, **k):
        """Synchronous passthrough for non-Live radios"""
        job = radiothread.RadioJob(self, fn, a, k)
        try:
            job.result = getattr(self._radio, fn)(*a, **k)
        except Exception as e:
            LOG.exception('Failed to run %s(%s, %s)' % (
                fn, ','.join(str(x) for x in a),
                ','.join('%s=%r' % (k, v) for k, v in k.items())))
            job.result = e
        if cb:
            cb(job)

    def setup_radio_interface(self):
        pass


class ChirpAsyncEditor(ChirpSyncEditor):
    """Radio interface that makes async calls in a helper thread.

    This executes RadioJob requests asynchronously in a thread and
    schedules the callback via a wx event.

    """
    def do_radio(self, cb, fn, *a, **k):
        self._jobs[self._radio_thread.submit(self, fn, *a, **k)] = cb

    def radio_thread_event(self, job, block=True):
        if job.fn == 'get_memory':
            msg = _('Refreshed memory %s') % job.args[0]
        elif job.fn == 'set_memory':
            msg = _('Uploaded memory %s') % job.args[0].number
        elif job.fn == 'get_settings':
            msg = _('Retrieved settings')
        elif job.fn == 'set_settings':
            msg = _('Saved settings')
        else:
            msg = _('Finished radio job %s') % job.fn

        if not EDIT_LOCK.acquire(block):
            return False
        try:
            self.status_message(msg)
            cb = self._jobs.pop(job.id)
            if cb:
                wx.CallAfter(cb, job)

            # Update our status, which may be reset to unmodified
            wx.PostEvent(self, EditorChanged(self.GetId()))
        finally:
            EDIT_LOCK.release()

        return True

    def set_radio_thread(self, radio_thread):
        self._radio_thread = radio_thread

    def setup_radio_interface(self):
        self._jobs = {}


class ChirpSettingGrid(wx.Panel):
    def __init__(self, settinggroup, *a, **k):
        super(ChirpSettingGrid, self).__init__(*a, **k)
        self._group = settinggroup

        self.pg = wx.propgrid.PropertyGrid(
            self,
            style=wx.propgrid.PG_SPLITTER_AUTO_CENTER |
            wx.propgrid.PG_BOLD_MODIFIED)

        self.pg.Bind(wx.propgrid.EVT_PG_CHANGED, self._pg_changed)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)
        sizer.Add(self.pg, 1, wx.EXPAND)

        self._choices = {}

        for name, element in self._group.items():
            if not isinstance(element, settings.RadioSetting):
                LOG.debug('Skipping nested group %s' % element)
                continue
            if len(element.keys()) > 1:
                self.pg.Append(wx.propgrid.PropertyCategory(
                    element.get_shortname()))

            for i in element.keys():
                value = element[i]
                if isinstance(value, settings.RadioSettingValueInteger):
                    editor = self._get_editor_int(element, value)
                elif isinstance(value, settings.RadioSettingValueFloat):
                    editor = self._get_editor_float(element, value)
                elif isinstance(value, settings.RadioSettingValueList):
                    editor = self._get_editor_choice(element, value)
                elif isinstance(value, settings.RadioSettingValueBoolean):
                    editor = self._get_editor_bool(element, value)
                elif isinstance(value, settings.RadioSettingValueString):
                    editor = self._get_editor_str(element, value)
                else:
                    LOG.warning('Unsupported setting type %r' % value)
                    editor = None
                if editor:
                    editor.SetName('%s%s%i' % (name, INDEX_CHAR, i))
                    if len(element.keys()) > 1:
                        editor.SetLabel('')
                    editor.Enable(value.get_mutable())
                    self.pg.Append(editor)

    @property
    def name(self):
        return self._group.get_name()

    @property
    def propgrid(self):
        return self.pg

    def _pg_changed(self, event):
        wx.PostEvent(self, EditorChanged(self.GetId()))

    def _get_editor_int(self, setting, value):
        e = wx.propgrid.IntProperty(setting.get_shortname(),
                                    setting.get_name(),
                                    value=int(value))
        e.SetEditor('SpinCtrl')
        e.SetAttribute(wx.propgrid.PG_ATTR_MIN, value.get_min())
        e.SetAttribute(wx.propgrid.PG_ATTR_MAX, value.get_max())
        e.SetAttribute(wx.propgrid.PG_ATTR_SPINCTRL_STEP, value.get_step())
        return e

    def _get_editor_float(self, setting, value):
        class ChirpFloatProperty(wx.propgrid.FloatProperty):
            def ValidateValue(self, val, info):
                if value.get_min() and not val >= value.get_min():
                    info.SetFailureMessage(
                        _('Value must be at least %.4f' % value.get_min()))
                    return False
                if value.get_max() and not val <= value.get_max():
                    info.SetFailureMessage(
                        _('Value must be at most %.4f' % value.get_max()))
                    return False
                return True
        return ChirpFloatProperty(setting.get_shortname(),
                                  setting.get_name(),
                                  value=float(value))

    def _get_editor_choice(self, setting, value):
        choices = value.get_options()
        self._choices[setting.get_name()] = choices
        current = choices.index(str(value))
        return wx.propgrid.EnumProperty(setting.get_shortname(),
                                        setting.get_name(),
                                        choices, range(len(choices)),
                                        current)

    def _get_editor_bool(self, setting, value):
        prop = wx.propgrid.BoolProperty(setting.get_shortname(),
                                        setting.get_name(),
                                        bool(value))
        prop.SetAttribute(wx.propgrid.PG_BOOL_USE_CHECKBOX, True)
        return prop

    def _get_editor_str(self, setting, value):
        class ChirpStrProperty(wx.propgrid.StringProperty):
            def ValidateValue(self, text, info):
                try:
                    value.set_value(text)
                except Exception as e:
                    info.SetFailureMessage(str(e))
                    return False
                return True

        return ChirpStrProperty(setting.get_shortname(),
                                setting.get_name(),
                                value=str(value))

    def get_setting_values(self):
        """Return a dict of {name: (RadioSetting, newvalue)}"""
        values = {}
        for prop in self.pg._Items():
            if prop.IsCategory():
                continue
            basename = prop.GetName().split(INDEX_CHAR)[0]
            if isinstance(prop, wx.propgrid.EnumProperty):
                value = self._choices[basename][prop.GetValue()]
            else:
                value = prop.GetValue()
            setting = self._group[basename]
            values[prop.GetName()] = setting, value
        return values

    def get_values(self):
        """Return a dict of {name: newvalue}"""
        return {k: v[1] for k, v in self.get_setting_values().items()}

    def saved(self):
        for prop in self.pg._Items():
            prop.SetModifiedStatus(False)


def _error_proof(*expected_errors):
    """Decorate a method and display an error if it raises.

    If the method raises something in expected_errors, then
    log an error, otherwise log exception.
    """

    def show_error(msg):
        d = wx.MessageDialog(None, str(msg), _('An error has occurred'),
                             style=wx.OK | wx.ICON_ERROR)
        d.ShowModal()

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except expected_errors as e:
                LOG.error('%s: %s' % (fn, e))
                show_error(e)
            except Exception as e:
                LOG.exception('%s raised unexpected exception' % fn)
                show_error(e)

        return inner
    return wrap


class error_proof(object):
    def __init__(self, *expected_exceptions):
        self._expected = expected_exceptions

    @staticmethod
    def show_error(msg):
        d = wx.MessageDialog(None, str(msg), _('An error has occurred'),
                             style=wx.OK | wx.ICON_ERROR)
        d.ShowModal()

    def run_safe(self, fn, args, kwargs):
        try:
            return fn(*args, **kwargs)
        except self._expected as e:
            LOG.error('%s: %s' % (fn, e))
            self.show_error(e)
        except Exception as e:
            LOG.exception('%s raised unexpected exception' % fn)
            self.show_error(e)

    def __call__(self, fn):
        self.fn = fn

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self.run_safe(fn, args, kwargs)
        return wrapper

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, traceback):
        if exc_type:
            if exc_type in self._expected:
                LOG.error('%s: %s: %s' % (self.fn, exc_type, exc_val))
                self.show_error(exc_val)
                return True
            else:
                LOG.exception('Context raised unexpected_exception',
                              exc_info=(exc_type, exc_val, traceback))
                self.show_error(exc_val)
