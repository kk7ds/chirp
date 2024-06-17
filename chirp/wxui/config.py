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

import base64
import binascii
import logging

from chirp import platform
from configparser import ConfigParser
import os

LOG = logging.getLogger(__name__)


class ChirpConfig:
    def __init__(self, basepath, name="chirp.config"):
        self.__basepath = basepath
        self.__name = name

        self._default_section = "global"

        self.__config = ConfigParser(interpolation=None)

        cfg = os.path.join(basepath, name)
        if os.path.exists(cfg):
            try:
                self.__config.read(cfg, encoding='utf-8-sig')
            except UnicodeDecodeError:
                LOG.warning('Failed to read config as UTF-8; '
                            'falling back to default encoding')
                self.__config.read(cfg)

    def save(self):
        cfg = os.path.join(self.__basepath, self.__name)
        with open(cfg, "w", encoding='utf-8') as cfg_file:
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

    def get_password(self, key, section):
        # So, we used to store the password in plaintext in $key. Then some
        # dumb guy stored the base64-encoded password in $key also. However,
        # if the plaintext password happens to be valid base64, we'll decode it
        # to some random binary, and then fail to decode UTF-8 from it. So,
        # for people already in this situation, first try the "new" location
        # of $key_encoded, if it exists. If it doesn't honor the old place
        # and return the exact string if base64 or UTF-8 decoding fails,
        # otherwise return the fully decoded thing. Conversion will happen
        # when people update passwords and set_passwoord() is called, which
        # always stores the new format.
        encoded = self.get('%s_encoded' % key, section)
        if encoded is None:
            encoded = self.get(key, section)
        if encoded:
            try:
                return base64.b64decode(encoded.encode()).decode()
            except binascii.Error:
                # Likely not stored encoded, return as-is
                return encoded
            except UnicodeDecodeError:
                # This means it must be stored in plaintext but we did
                # actually decode it with base64, but not to a valid string
                return encoded
        else:
            return encoded

    def set(self, key, value, section=None):
        return self._config.set(key, value, section or self._section)

    def set_password(self, key, value, section):
        """Store a password slightly obfuscated.

        THIS IS NOT SECURE. It just avoids storing the password
        in complete cleartext. It is trivial to read them in this
        format.
        """
        value = base64.b64encode(value.encode()).decode()
        # Clean up old cleartext passwords
        if self.is_defined(key, section):
            self.remove_option(key, section)
        self.set('%s_encoded' % key, value, section)

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
