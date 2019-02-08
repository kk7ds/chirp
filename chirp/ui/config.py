# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

from chirp import platform
try:
    from ConfigParser import ConfigParser
except ImportError:
    from configparser import ConfigParser
import os


class ChirpConfig:
    def __init__(self, basepath, name="chirp.config"):
        self.__basepath = basepath
        self.__name = name

        self._default_section = "global"

        self.__config = ConfigParser()

        cfg = os.path.join(basepath, name)
        if os.path.exists(cfg):
            self.__config.read(cfg)

    def save(self):
        cfg = os.path.join(self.__basepath, self.__name)
        with open(cfg, "w") as cfg_file:
            self.__config.write(cfg_file)

    def get(self, key, section, raw=False):
        if not self.__config.has_section(section):
            return None

        if not self.__config.has_option(section, key):
            return None

        return self.__config.get(section, key, raw=raw)

    def set(self, key, value, section):
        if not self.__config.has_section(section):
            self.__config.add_section(section)

        self.__config.set(section, key, value)

    def is_defined(self, key, section):
        return self.__config.has_option(section, key)

    def remove_option(self, section, key):
        self.__config.remove_option(section, key)

        if not self.__config.items(section):
            self.__config.remove_section(section)


class ChirpConfigProxy:
    def __init__(self, config, section="global"):
        self._config = config
        self._section = section

    def get(self, key, section=None, raw=False):
        return self._config.get(key, section or self._section,
                                raw=raw)

    def set(self, key, value, section=None):
        return self._config.set(key, value, section or self._section)

    def get_int(self, key, section=None):
        try:
            return int(self.get(key, section))
        except ValueError:
            return 0

    def set_int(self, key, value, section=None):
        if not isinstance(value, int):
            raise ValueError("Value is not an integer")

        self.set(key, "%i" % value, section)

    def get_float(self, key, section=None):
        try:
            return float(self.get(key, section))
        except ValueError:
            return 0

    def set_float(self, key, value, section=None):
        if not isinstance(value, float):
            raise ValueError("Value is not an integer")

        self.set(key, "%i" % value, section)

    def get_bool(self, key, section=None, default=False):
        val = self.get(key, section)
        if val is None:
            return default
        else:
            return val == "True"

    def set_bool(self, key, value, section=None):
        self.set(key, str(bool(value)), section)

    def is_defined(self, key, section=None):
        return self._config.is_defined(key, section or self._section)

    def remove_option(self, key, section):
        self._config.remove_option(section, key)


_CONFIG = None


def get(section="global"):
    global _CONFIG

    p = platform.get_platform()

    if not _CONFIG:
        _CONFIG = ChirpConfig(p.config_dir())

    return ChirpConfigProxy(_CONFIG, section)
