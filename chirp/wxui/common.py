import functools
import logging

import wx

from chirp import chirp_common
from chirp.drivers import generic_csv
from chirp import errors
from chirp import settings

LOG = logging.getLogger(__name__)

CHIRP_DATA_MEMORY = wx.DataFormat('x-chirp/memory-channel')
EditorChanged, EVT_EDITOR_CHANGED = wx.lib.newevent.NewCommandEvent()


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
            status.msg = 'Cloning'
            self.status_fn(status)

    def get_settings(self):
        return self._liveradio.get_settings()

    def set_settings(self, settings):
        return self._liveradio.set_settings(settings)


class ChirpEditor(wx.Panel):
    def cb_copy(self, cut=False):
        pass

    def cb_paste(self, data):
        pass

    def select_all(self):
        pass

    def saved(self):
        pass

    def selected(self):
        pass


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
                    self.pg.Append(editor)

    def _pg_changed(self, event):
        wx.PostEvent(self, EditorChanged(self.GetId()))

    def _get_editor_int(self, setting, value):
        class ChirpIntProperty(wx.propgrid.IntProperty):
            def ValidateValue(self, val, info):
                if not (val > value.get_min() and val < value.get_max()):
                    info.SetFailureMessage(
                        _('Value must be between %i and %i') % (
                            value.get_min(), value.get_max()))
                    return False
                return True
        return ChirpIntProperty(setting.get_shortname(),
                                setting.get_name(),
                                value=int(value))

    def _get_editor_float(self, setting, value):
        class ChirpFloatProperty(wx.propgrid.IntProperty):
            def ValidateValue(self, val, info):
                if not (val > value.get_min() and val < value.get_max()):
                    info.SetFailureMessage(
                        _('Value must be between %.4f and %.4f') % (
                            value.get_min(), value.get_max()))
        return ChirpFloatProperty(setting.get_shortname(),
                                setting.get_name(),
                                value=int(value))

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

    def get_values(self):
        values = {}
        for prop in self.pg._Items():
            if isinstance(prop, wx.propgrid.EnumProperty):
                value = self._choices[prop.GetName()][prop.GetValue()]
            else:
                value = prop.GetValue()
            values[prop.GetName()] = value
        return values

    def saved(self):
        for prop in self.pg._Items():
            prop.SetModifiedStatus(False)


def _error_proof(*expected_errors):
    """Decorate a method and display an error if it raises.

    If the method raises something in expected_errors, then
    log an error, otherwise log exception.
    """

    def show_error(msg):
        d = wx.MessageDialog(None, str(msg), 'An error has occurred',
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
        d = wx.MessageDialog(None, str(msg), 'An error has occurred',
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
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self.run_safe(fn, args, kwargs)
        return wrapper

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, traceback):
        if exc_type:
            if exc_type in self._expected:
                LOG.error('%s: %s: %s' % (fn, exc_type, exc_val))
                self.show_error(exc_val)
                return True
            else:
                LOG.exception('Context raised unexpected_exception',
                              exc_info=(exc_type, exc_val, traceback))
                self.show_error(exc_val)
