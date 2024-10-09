import logging

from chirp import chirp_common
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueBoolean, \
    RadioSettingValueString, RadioSettingValueList, RadioSettingValueMap, \
    RadioSettings

LOG = logging.getLogger(__name__)


class SettingsMixin(chirp_common.LiveRadio):
    _COMMON_SETTINGS = {}
    _SETTINGS = {}

    _cur_setting = 0
    _setcache = {}
    _setting_count = 0

    def __init__(self, *args, **kwargs):
        # Clear the cache
        self._setcache = {}

    def _count_settings(self, entries):
        for entry in entries:
            if (type(entry[1]) is tuple):
                self._count_settings(entry[1])
            else:
                self._setting_count += 1

    def _create_group(self, entries, grp=None):
        if grp is None:
            grp = RadioSettings()
        for entry in entries:
            if (type(entry[1]) is tuple):
                subgrp = RadioSettingGroup(entry[0].lower(), entry[0])
                grp.append(self._create_group(entry[1], subgrp))
            else:
                setting = self._get_setting_data(entry[0])
                if setting['type'] == 'undefined':
                    continue
                if setting['type'] == 'list':
                    rsvl = RadioSettingValueList(setting['values'])
                    rs = RadioSetting(entry[0], entry[1], rsvl)
                elif setting['type'] == 'bool':
                    rs = RadioSetting(entry[0], entry[1],
                                      RadioSettingValueBoolean(False))
                elif setting['type'] == 'string':
                    params = {}
                    if 'charset' in setting:
                        params['charset'] = setting['charset']
                    else:
                        params['charset'] = chirp_common.CHARSET_ASCII
                    minlen = 'min_len' in setting and setting['min_len'] or 0
                    dummy = params['charset'][0] * minlen
                    rsvs = RadioSettingValueString(minlen,
                                                   setting['max_len'],
                                                   dummy,
                                                   False, **params)
                    rs = RadioSetting(entry[0], entry[1], rsvs)
                elif setting['type'] == 'integer':
                    rs = RadioSetting(entry[0], entry[1],
                                      RadioSettingValueInteger(setting['min'],
                                                               setting['max'],
                                                               setting['min']))
                elif setting['type'] == 'map':
                    rsvs = RadioSettingValueMap(setting['map'],
                                                setting['map'][0][1])
                    rs = RadioSetting(entry[0], entry[1], rsvs)
                else:
                    rs = setting['type'](entry[0], entry[1], self)
                rs._setting_loaded = False
                grp.append(rs)
                self._setcache[entry[0]] = rs
        return grp

    def _do_prerequisite(self, cmd, get, do):
        if get:
            arg = 'get_requires'
        else:
            arg = 'set_requires'
        setting = self._get_setting_data(cmd)
        if arg not in setting:
            return
        # Undo prerequisites in the reverse order they were applied
        if not do:
            it = reversed(setting[arg])
        else:
            it = iter(setting[arg])
        for prereq, value in it:
            entry = self._setcache[prereq]
            sdata = self._get_setting_data(prereq)
            if not entry._setting_loaded:
                self._refresh_setting(entry)
            if do:
                entry._settings_old_value = entry.value.get_value()
                self._set_value_from_radio(entry, value, sdata)
            else:
                self._set_value_from_radio(entry, entry._settings_old_value,
                                           sdata)
            self._set_setting(prereq, sdata, entry)

    def _get_setting_data(self, setting):
        if setting in self._SETTINGS:
            return self._SETTINGS[setting]
        if setting in self._COMMON_SETTINGS:
            return self._COMMON_SETTINGS[setting]
        if (setting.upper() == setting):
            LOG.debug("Undefined setting: %s" % setting)
        return {'type': 'undefined'}

    def _refresh_setting(self, entry):
        name = entry.get_name()
        setting = self._get_setting_data(name)
        # TODO: It would be nice to bump_wait_dialog here...
        #       Also, this is really only useful for the cli. :(
        if self.status_fn:
            status = chirp_common.Status()
            status.cur = self._cur_setting
            status.max = self._setting_count
            status.msg = "Fetching %-30s" % entry.get_shortname()
            # self.bump_wait_dialog(int(status.cur * 100 / status.max),
            #                       "Fetching %s" % entry[1])
            self.status_fn(status)
        self._cur_setting += 1
        # We can't do this because hasattr() doesn't work...
        # if hasattr(entry, 'read_setting_from_radio'):
        #     entry.read_setting_from_radio(setting)
        # else:
        #     self._read_setting_from_radio(entry, setting)
        try:
            entry.read_setting_from_radio()
        except KeyError:
            value = self._read_setting_from_radio(entry, setting)
            self._set_value_from_radio(entry, value, setting)
        # Since we're using try/except above, don't use hasattr() here
        # either.
        if hasattr(entry, "value") and hasattr(entry.value, "_has_changed"):
            entry.value._has_changed = False
        entry._setting_loaded = True

    def _refresh_settings(self):
        for entry in self._setcache.values():
            if not entry._setting_loaded:
                self._refresh_setting(entry)

    def _set_setting(self, name, sdata, element):
        try:
            element.set_setting_to_radio()
        except KeyError:
            self._set_setting_to_radio(element, sdata)
        if hasattr(element, "value") and hasattr(element.value, "_has_changed"):
            element.value._has_changed = False

    def _set_value_from_radio(self, entry, value, sdata):
        if sdata['type'] == 'map':
            entry.value.set_mem_val(value)
        elif sdata['type'] == 'list':
            entry.value.set_index(value)
        else:
            entry.value.set_value(value)

    def get_settings(self):
        if self._setting_count == 0:
            self._count_settings(self._SETTINGS_MENUS)
        ret = self._create_group(self._SETTINGS_MENUS)
        self._cur_setting = 0
        self._refresh_settings()
        status = chirp_common.Status()
        status.cur = self._setting_count
        status.max = self._setting_count
        status.msg = "%-40s" % "Done"
        self.status_fn(status)
        return ret

    def set_settings(self, settings):
        for element in settings:
            name = element.get_name()
            sdata = self._get_setting_data(name)
            if sdata['type'] == 'undefined':
                if isinstance(element, RadioSettingGroup):
                    self.set_settings(element)
                continue
            if not element.changed():
                continue
            self._set_setting(name, sdata, element)
