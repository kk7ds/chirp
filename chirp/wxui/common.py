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

import atexit
import contextlib
import functools
import itertools
import logging
import os
import platform
import shutil
import tempfile
import threading
import webbrowser

import wx

from chirp import chirp_common
from chirp.drivers import generic_csv
from chirp import errors
from chirp import logger
from chirp import platform as chirp_platform
from chirp import settings
from chirp.wxui import config
from chirp.wxui import radiothread

LOG = logging.getLogger(__name__)
CONF = config.get()

CHIRP_DATA_MEMORY = wx.DataFormat('x-chirp/memory-channel')
EditorChanged, EVT_EDITOR_CHANGED = wx.lib.newevent.NewCommandEvent()
StatusMessage, EVT_STATUS_MESSAGE = wx.lib.newevent.NewCommandEvent()
EditorRefresh, EVT_EDITOR_REFRESH = wx.lib.newevent.NewCommandEvent()
CrossEditorAction, EVT_CROSS_EDITOR_ACTION = wx.lib.newevent.NewCommandEvent()
INDEX_CHAR = settings.BANNED_NAME_CHARACTERS[0]

# This is a lock that can be used to exclude edit-specific operations
# from happening at the same time, like radiothread async
# operations. This needs to be local to the thing with the wx.Grid as
# its child, which is the chirp main window in our case. Making this
# global is technically too broad, but in reality, it's equivalent for
# us at the moment, and this is easier.
EDIT_LOCK = threading.Lock()


class ExportFailed(Exception):
    pass


def closes_clipboard(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        finally:
            if wx.TheClipboard.IsOpened():
                LOG.warning('Closing clipboard left open by %s' % fn)
                wx.TheClipboard.Close()
    return wrapper


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


class EditorMenuItem(wx.MenuItem):
    MENU_VIEW = 'View'
    MENU_EDIT = 'Edit'
    ITEMS = {}

    def __init__(self, cls, callback_name, *a, **k):
        self._wx_id = k.pop('id', None)
        if not self._wx_id:
            self._wx_id = wx.NewId()
        super().__init__(None, self._wx_id, *a, **k)
        self._cls = cls
        self._callback_name = callback_name
        self.ITEMS[self.key] = self._wx_id

    @property
    def key(self):
        return '%s:%s' % (self._cls.__name__, self._callback_name)

    @property
    def editor_class(self):
        return self._cls

    def editor_callback(self, editor, event):
        getattr(editor, self._callback_name)(event)

    def add_menu_callback(self):
        # Some platforms won't actually set the accelerator (macOS) or allow
        # enable/check (linux) before we are in a menu.
        accel = self.GetAccel()
        self.SetAccel(None)
        self.SetAccel(accel)


class EditorMenuItemToggleStateless(EditorMenuItem):
    def __init__(self, cls, callback_name, *a, **k):
        k['kind'] = wx.ITEM_CHECK
        super().__init__(cls, callback_name, *a, **k)


class EditorMenuItemToggle(EditorMenuItemToggleStateless):
    """An EditorMenuItem that manages boolean/check state in CONF"""
    def __init__(self, cls, callback_name, conf_tuple, *a, **k):
        super().__init__(cls, callback_name, *a, **k)
        self._conf_key, self._conf_section = conf_tuple

    def editor_callback(self, editor, event):
        menuitem = event.GetEventObject().FindItemById(event.GetId())
        CONF.set_bool(self._conf_key, menuitem.IsChecked(), self._conf_section)
        super().editor_callback(editor, event)

    def add_menu_callback(self):
        super().add_menu_callback()
        self.Check(CONF.get_bool(self._conf_key, self._conf_section, False))


class ChirpEditor(wx.Panel):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setup_radio_interface()
        self.wait_dialog = None

    @property
    def radio(self):
        return self._radio

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
        raise NotImplementedError()

    @closes_clipboard
    def cb_copy_data(self, data):
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(data)
            wx.TheClipboard.Close()
        else:
            raise RuntimeError(_('Unable to open the clipboard'))

    @closes_clipboard
    def cb_paste(self):
        memdata = wx.CustomDataObject(CHIRP_DATA_MEMORY)
        textdata = wx.TextDataObject()
        if wx.TheClipboard.Open():
            gotchirpmem = wx.TheClipboard.GetData(memdata)
            got = wx.TheClipboard.GetData(textdata)
            wx.TheClipboard.Close()
        if gotchirpmem:
            return memdata
        elif got:
            return textdata

    def cb_delete(self):
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

    def update_font(self):
        pass

    @classmethod
    def get_menu_items(self):
        """Return a dict of menu items specific to this editor class

        Example: {'Edit': [wx.MenuItem], 'View': [wx.MenuItem]}
        """
        return {}


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

    do_lazy_radio = do_radio

    def setup_radio_interface(self):
        pass

    @property
    def busy(self):
        return False


class ChirpAsyncEditor(ChirpSyncEditor):
    """Radio interface that makes async calls in a helper thread.

    This executes RadioJob requests asynchronously in a thread and
    schedules the callback via a wx event.

    """
    def do_radio(self, cb, fn, *a, **k):
        self._jobs[self._radio_thread.submit(self, fn, *a, **k)] = cb

    def do_lazy_radio(self, cb, fn, *a, **k):
        self._jobs[self._radio_thread.background(self, fn, *a, **k)] = cb

    def radio_thread_event(self, job, block=True):
        if job.fn == 'get_memory':
            msg = _('Refreshed memory %s') % job.args[0]
        elif job.fn == 'set_memory':
            msg = _('Uploaded memory %s') % job.args[0].number
        elif job.fn == 'get_settings':
            msg = _('Retrieved settings')
        elif job.fn == 'set_settings':
            msg = _('Saved settings')
        elif job.fn == 'erase_memory':
            msg = _('Erased memory %s') % job.args[0]
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

    @property
    def busy(self):
        return self._radio_thread.pending != 0


class ChirpSettingGrid(wx.Panel):
    def __init__(self, settinggroup, *a, **k):
        super(ChirpSettingGrid, self).__init__(*a, **k)
        self._group = settinggroup
        self._settings = {}
        self._needs_reload = False

        self.pg = wx.propgrid.PropertyGrid(
            self,
            style=wx.propgrid.PG_SPLITTER_AUTO_CENTER |
            wx.propgrid.PG_BOLD_MODIFIED)

        self.pg.Bind(wx.propgrid.EVT_PG_CHANGED, self._pg_changed)
        self.pg.Bind(wx.EVT_MOTION, self._mouseover)

        self.pg.DedicateKey(wx.WXK_TAB)
        self.pg.DedicateKey(wx.WXK_RETURN)
        self.pg.DedicateKey(wx.WXK_UP)
        self.pg.DedicateKey(wx.WXK_DOWN)
        self.pg.AddActionTrigger(wx.propgrid.PG_ACTION_EDIT, wx.WXK_RETURN)
        self.pg.AddActionTrigger(wx.propgrid.PG_ACTION_NEXT_PROPERTY,
                                 wx.WXK_RETURN)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)
        sizer.Add(self.pg, 1, wx.EXPAND)

        self._choices = {}

        self._add_items(self._group)
        self.pg.Bind(wx.propgrid.EVT_PG_CHANGING, self._check_change)

    def _mouseover(self, event):
        prop = self.pg.HitTest(event.GetPosition()).GetProperty()
        tip = None
        if prop:
            setting = self.get_setting_by_name(prop.GetName())
            # FIXME: Indexed properties will have their INDEX_CHAR replaced
            # here and thus won't match the actual setting name, so we'll
            # get None here. Avoid a trace for now, but this needs fixing.
            if setting and isinstance(setting.value,
                                      settings.RadioSettingValueString):
                tip = setting.__doc__ or ''
                if setting.value.maxlength == setting.value._minlength:
                    extra = '%i characters' % setting.value.maxlength
                else:
                    extra = '%i-%i characters' % (setting.value.minlength,
                                                  setting.value.maxlength)
                tip = (tip + ' (%s)' % extra).strip()
            else:
                tip = setting.__doc__ or None

        event.GetEventObject().SetToolTip(tip)

    def _add_items(self, group, parent=None):
        def append(item):
            if parent:
                self.pg.AppendIn(parent, item)
            else:
                self.pg.Append(item)

        for name, element in group.items():
            if isinstance(element, settings.RadioSettingSubGroup):
                category = wx.propgrid.PropertyCategory(
                               element.get_shortname(), element.get_name())
                append(category)
                self._add_items(element, parent=category)
                continue
            elif not isinstance(element, settings.RadioSetting):
                LOG.debug('Skipping nested group %s' % element)
                continue
            if len(element.keys()) > 1:
                append(wx.propgrid.PropertyCategory(
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
                if not editor:
                    continue

                editor.SetName('%s%s%i' % (name, INDEX_CHAR, i))
                if len(element.keys()) > 1:
                    editor.SetLabel('')
                editor.Enable(value.get_mutable())
                append(editor)
                self._settings[element.get_name()] = element
                if editor.IsValueUnspecified():
                    # Mark invalid/unspecified values so the user can fix them
                    self.pg.SetPropertyBackgroundColour(editor.GetName(),
                                                        wx.YELLOW)

        self.pg.Bind(wx.propgrid.EVT_PG_CHANGING, self._check_change)

    def get_setting_by_name(self, name, index=0):
        if INDEX_CHAR in name:
            # FIXME: This will only work for single-index settings of course
            name, _ = name.split(INDEX_CHAR, 1)
        for setting_name, setting in self._settings.items():
            if name == setting_name:
                return setting

    def _check_change(self, event):
        setting = self.get_setting_by_name(event.GetPropertyName())
        if not setting:
            LOG.error('Got change event for unknown setting %s' % (
                event.GetPropertyName()))
            return
        warning = setting.get_warning(event.GetValue())
        if warning:
            r = wx.MessageBox(warning, _('WARNING!'),
                              wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT)
            if r == wx.CANCEL:
                LOG.info('User aborted setting %s=%s with warning message',
                         event.GetPropertyName(), event.GetValue())
                event.SetValidationFailureBehavior(0)
                event.Veto()
                return
            else:
                LOG.info('User made change to %s=%s despite warning',
                         event.GetPropertyName(), event.GetValue())
        if setting.volatile:
            wx.MessageBox(_(
                'Changing this setting requires refreshing the settings from '
                'the image, which will happen now.'),
                          _('Refresh required'), wx.OK)
            self._needs_reload = True

        # If we were unspecified or otherwise marked, clear those markings
        self.pg.SetPropertyColoursToDefault(event.GetProperty().GetName())

    @property
    def name(self):
        return self._group.get_name()

    @property
    def propgrid(self):
        return self.pg

    def _pg_changed(self, event):
        wx.PostEvent(self, EditorChanged(self.GetId(),
                                         reload=self._needs_reload))
        self._needs_reload = False

    def _get_editor_int(self, setting, value):
        e = wx.propgrid.IntProperty(setting.get_shortname(),
                                    setting.get_name())
        if value.initialized:
            e.SetValue(int(value))
        else:
            e.SetValueToUnspecified()
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

            def ValueToString(self, _value, flags=0):
                return value.format(_value)

        e = ChirpFloatProperty(setting.get_shortname(),
                               setting.get_name())
        if value.initialized:
            e.SetValue(float(value))
        else:
            e.SetValueToUnspecified()
        return e

    def _get_editor_choice(self, setting, value):
        choices = value.get_options()
        self._choices[setting.get_name()] = choices
        e = wx.propgrid.EnumProperty(setting.get_shortname(),
                                     setting.get_name(),
                                     choices, range(len(choices)))
        if value.initialized:
            e.SetValue(choices.index(str(value)))
        else:
            e.SetValueToUnspecified()
        return e

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

        e = ChirpStrProperty(setting.get_shortname(),
                             setting.get_name())
        if value.initialized:
            e.SetValue(str(value))
        else:
            e.SetValueToUnspecified()
        return e

    def get_setting_values(self):
        """Return a dict of {name: (RadioSetting, newvalue)}"""
        values = {}
        for prop in self.pg._Items():
            if prop.IsCategory():
                continue
            if prop.IsValueUnspecified():
                continue
            basename = prop.GetName().split(INDEX_CHAR)[0]
            if isinstance(prop, wx.propgrid.EnumProperty):
                value = self._choices[basename][prop.GetValue()]
            else:
                value = prop.GetValue()
            setting = self._settings[basename]
            values[prop.GetName()] = setting, value
        return values

    def get_values(self):
        """Return a dict of {name: newvalue}"""
        return {k: v[1] for k, v in self.get_setting_values().items()}

    def saved(self):
        for prop in self.pg._Items():
            prop.SetModifiedStatus(False)


class error_proof(object):
    def __init__(self, *expected_exceptions, title=None):
        self._expected = expected_exceptions
        self.fn = None
        self.title = title

    @staticmethod
    def show_error(error, parent=None, title=None):
        title = title or _('An error has occurred')

        if isinstance(error, errors.SpecificRadioError):
            link = error.get_link()
            message = str(error)
        else:
            link = None
            message = str(error)

        if link:
            buttons = wx.YES_NO | wx.NO_DEFAULT
        else:
            buttons = wx.OK
        d = wx.MessageDialog(parent, message, title,
                             wx.ICON_ERROR | buttons)
        if link:
            d.SetYesNoLabels(_('More Info'), wx.ID_OK)
        r = d.ShowModal()
        if r == wx.ID_YES:
            webbrowser.open(link)

    def run_safe(self, fn, args, kwargs):
        try:
            return fn(*args, **kwargs)
        except self._expected as e:
            LOG.error('%s: %s' % (fn, e))
            self.show_error(e, title=self.title)
        except Exception as e:
            LOG.exception('%s raised unexpected exception' % fn)
            self.show_error(e, title=self.title)

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
                LOG.error('%s: %s: %s',
                          self.fn or 'context', exc_type, exc_val)
                self.show_error(exc_val)
                return True
            else:
                LOG.exception('Context raised unexpected_exception',
                              exc_info=(exc_type, exc_val, traceback))
                self.show_error(exc_val)


def reveal_location(path):
    LOG.debug('Revealing path %s', path)
    system = platform.system()
    if system == 'Windows':
        if not os.path.isdir(path):
            # Windows can only reveal the containing directory of a file
            path = os.path.dirname(path)
        wx.Execute('explorer %s' % path)
    elif system == 'Darwin':
        wx.Execute('open -R %s' % path)
    elif system == 'Linux':
        wx.Execute('open %s' % path)
    else:
        raise Exception(_('Unable to reveal %s on this system') % path)


def delete_atexit(path_):
    def do(path):
        try:
            os.remove(path)
            LOG.debug('Removed temporary file %s', path)
        except Exception as e:
            LOG.warning('Failed to remove %s: %s', path, e)

    atexit.register(do, path_)


def temporary_debug_log():
    """Return a temporary copy of our debug log"""
    pf = chirp_platform.get_platform()
    src = pf.config_file('debug.log')
    fd, dst = tempfile.mkstemp(
        prefix='chirp_debug-',
        suffix='.txt')
    delete_atexit(dst)
    shutil.copy(src, dst)
    return dst


class MultiErrorDialog(wx.Dialog):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        self.choices = []
        self.choice_box = wx.ListBox(self)
        vbox.Add(self.choice_box, border=10, proportion=0,
                 flag=wx.EXPAND | wx.ALL)

        self.message = wx.TextCtrl(self)
        self.message.SetEditable(False)
        vbox.Add(self.message, border=10, proportion=1,
                 flag=wx.EXPAND | wx.ALL)

        buttons = self.CreateButtonSizer(wx.OK)
        vbox.Add(buttons, border=10, flag=wx.ALL)

        self.Bind(wx.EVT_BUTTON, self._button)
        self.choice_box.Bind(wx.EVT_LISTBOX, self._selected)

        self.SetMinSize((600, 400))
        self.Fit()
        self.Center()

    def _button(self, event):
        self.EndModal(wx.ID_OK)

    def select(self, index):
        error = self.choices[index]
        self.message.SetValue('%s in %s:\n%s' % (
            error.levelname, error.module, error.getMessage()))

    def _selected(self, event):
        self.select(event.GetInt())

    def set_errors(self, errors):
        self.choices = errors
        self.choice_box.Set([x.getMessage() for x in self.choices])
        self.select(0)


@contextlib.contextmanager
def expose_logs(level, root, label, maxlen=128, parent=None,
                show_on_raise=True):
    if not isinstance(root, tuple):
        root = (root,)

    error = None

    mgrs = (logger.log_history(level, x) for x in root)
    with contextlib.ExitStack() as stack:
        histories = [stack.enter_context(m) for m in mgrs]
        try:
            yield
        except Exception as e:
            LOG.warning('Failure while capturing logs (showing=%s): %s',
                        show_on_raise, e)
            error = e
        finally:
            lines = list(itertools.chain.from_iterable(x.get_history()
                                                       for x in histories))
            if lines and (show_on_raise or not error):
                LOG.warning('Showing %i lines of logs', len(lines))
                d = MultiErrorDialog(parent)
                d.SetTitle(label)
                d.set_errors(lines)
                d.ShowModal()
            else:
                LOG.warning('Not showing %i lines of logs (error=%s,show=%s)',
                            len(lines), bool(error), show_on_raise)
            if error:
                raise error


def mems_from_clipboard(string, maxlen=128, parent=None):
    label = _('Paste external memories')
    radio = generic_csv.TSVRadio(None)
    radio.clear()
    # Try to load the whole thing as a full TSV with header row
    try:
        with expose_logs(logging.WARNING, 'chirp.drivers', label,
                         parent=parent, show_on_raise=False):
            radio.load_from(string)
            return [x for x in radio.get_memories() if not x.empty]
    except errors.InvalidDataError:
        LOG.debug('No header information found in TSV paste')
    except RuntimeError:
        pass

    # If we got no memories, try prefixing the default header row and repeat
    header = generic_csv.TSVRadio.SEPCHAR.join(chirp_common.Memory.CSV_FORMAT)
    string = os.linesep.join([header, string])
    with expose_logs(logging.WARNING, 'chirp.drivers', label, parent=parent):
        radio.load_from(string)

    return [x for x in radio.get_memories() if not x.empty]
