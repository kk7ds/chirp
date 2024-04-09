# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import os
from pathlib import Path
import sys
import re
import logging
from subprocess import Popen

LOG = logging.getLogger(__name__)


def _find_me():
    return sys.modules["chirp.platform"].__file__


def natural_sorted(lst):
    def convert(text):
        return int(text) if text.isdigit() else text.lower()

    def natural_key(key):
        return [convert(c) for c in re.split('([0-9]+)', key)]

    return sorted(lst, key=natural_key)


class Platform:
    """Base class for platform-specific functions"""

    def __init__(self, basepath):
        self._base = basepath
        self._last_dir = self.default_dir()

    def get_last_dir(self):
        """Return the last directory used"""
        return self._last_dir

    def set_last_dir(self, last_dir):
        """Set the last directory used"""
        self._last_dir = last_dir

    def config_dir(self):
        """Return the preferred configuration file directory"""
        return self._base

    def log_dir(self):
        """Return the preferred log file directory"""
        logdir = os.path.join(self.config_dir(), "logs")
        try:
            os.mkdir(logdir)
        except FileExistsError:
            pass

        return logdir

    def filter_filename(self, filename):
        """Filter @filename for platform-forbidden characters"""
        return filename

    def log_file(self, filename):
        """Return the full path to a log file with @filename"""
        filename = self.filter_filename(filename + ".txt").replace(" ", "_")
        return os.path.join(self.log_dir(), filename)

    def config_file(self, filename):
        """Return the full path to a config file with @filename"""
        return os.path.join(self.config_dir(),
                            self.filter_filename(filename))

    def open_text_file(self, path):
        """Spawn the necessary program to open a text file at @path"""
        raise NotImplementedError("The base class can't do that")

    def open_html_file(self, path):
        """Spawn the necessary program to open an HTML file at @path"""
        raise NotImplementedError("The base class can't do that")

    def default_dir(self):
        """Return the default directory for this platform"""
        return "."

    def os_version_string(self):
        """Return a string that describes the OS/platform version"""
        return "Unknown Operating System"

    def executable_path(self):
        """Return a full path to the program executable"""
        def we_are_frozen():
            return hasattr(sys, "frozen")

        if we_are_frozen():
            # Win32, find the directory of the executable
            return os.path.dirname(str(sys.executable,
                                       sys.getfilesystemencoding()))
        else:
            # UNIX: Find the parent directory of this module
            return os.path.dirname(os.path.abspath(os.path.join(_find_me(),
                                                                "..")))

    def find_resource(self, filename):
        """Searches for files installed to a share/ prefix."""
        execpath = self.executable_path()
        share_candidates = [
            os.path.join(execpath, "share"),
            os.path.join(sys.prefix, "share"),
            "/usr/local/share",
            "/usr/share",
        ]
        pkgshare_candidates = [os.path.join(i, "chirp")
                               for i in share_candidates]
        search_paths = [execpath] + pkgshare_candidates + share_candidates
        for path in search_paths:
            candidate = os.path.join(path, filename)
            if os.path.exists(candidate):
                return candidate
        return ""


def _unix_editor():
    macos_textedit = "/Applications/TextEdit.app/Contents/MacOS/TextEdit"

    if os.path.exists(macos_textedit):
        return macos_textedit
    else:
        return "gedit"


class UnixPlatform(Platform):
    """A platform module suitable for UNIX systems"""
    def __init__(self, basepath):
        if not basepath:
            basepath = os.path.join(self.default_dir(),
                                    ".chirp")

        Path(basepath).mkdir(exist_ok=True)
        super().__init__(str(basepath))

    def default_dir(self):
        return str(Path.home())

    def filter_filename(self, filename):
        return filename.replace("/", "")

    def open_text_file(self, path):
        pid1 = os.fork()
        if pid1 == 0:
            pid2 = os.fork()
            if pid2 == 0:
                editor = _unix_editor()
                LOG.debug("calling `%s %s'" % (editor, path))
                os.execlp(editor, editor, path)
            else:
                sys.exit(0)
        else:
            os.waitpid(pid1, 0)
            LOG.debug("Exec child exited")

    def open_html_file(self, path):
        os.system("firefox '%s'" % path)

    def os_version_string(self):
        try:
            issue = open("/etc/issue.net", "r")
            ver = issue.read().strip().replace("\r", "").replace("\n", "")[:64]
            issue.close()
            ver = "%s - %s" % (os.uname()[0], ver)
        except Exception:
            ver = " ".join(os.uname())

        return ver


class Win32Platform(Platform):
    """A platform module suitable for Windows systems"""
    def __init__(self, basepath=None):
        if not basepath:
            appdata = os.getenv("APPDATA")
            if not appdata:
                appdata = "C:\\"
            basepath = os.path.abspath(os.path.join(appdata, "CHIRP"))

        if not os.path.isdir(basepath):
            try:
                os.mkdir(basepath)
            except FileExistsError:
                pass

        Platform.__init__(self, basepath)

    def default_dir(self):
        return os.path.abspath(os.path.join(os.getenv("USERPROFILE"),
                                            "Desktop"))

    def filter_filename(self, filename):
        for char in "/\\:*?\"<>|":
            filename = filename.replace(char, "")

        return filename

    def open_text_file(self, path):
        Popen(["notepad", path])
        return

    def open_html_file(self, path):
        os.system("explorer %s" % path)

    def os_version_string(self):
        import win32api

        vers = {4: "Win2k",
                5: "WinXP",
                6: "WinVista/7",
                }

        (pform, sub, build, _, _) = win32api.GetVersionEx()

        return vers.get(pform,
                        "Win32 (Unknown %i.%i:%i)" % (pform, sub, build))


def _get_platform(basepath):
    if os.name == "nt":
        return Win32Platform(basepath)
    else:
        return UnixPlatform(basepath)


PLATFORM = None


def get_platform(basepath=None):
    """Return the platform singleton"""
    global PLATFORM

    if not PLATFORM:
        PLATFORM = _get_platform(basepath)

    return PLATFORM


def _do_test():
    __pform = get_platform()

    print("Config dir: %s" % __pform.config_dir())
    print("Default dir: %s" % __pform.default_dir())
    print("Log file (foo): %s" % __pform.log_file("foo"))
    print("OS Version: %s" % __pform.os_version_string())
    # __pform.open_text_file("d-rats.py")


if __name__ == "__main__":
    _do_test()
