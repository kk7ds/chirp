#!/usr/bin/python
#
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

#
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
import sys
import glob
from subprocess import Popen

def find_me():
    return sys.modules["chirp.platform"].__file__

class Platform:
    # pylint: disable-msg=R0201

    def __init__(self, basepath):
        self._base = basepath
        self._last_dir = self.default_dir()

    def config_dir(self):
        return self._base

    def log_dir(self):
        logdir = os.path.join(self.config_dir(), "logs")
        if not os.path.isdir(logdir):
            os.mkdir(logdir)

        return logdir

    def filter_filename(self, filename):
        return filename

    def log_file(self, filename):
        filename = self.filter_filename(filename + ".txt").replace(" ", "_")
        return os.path.join(self.log_dir(), filename)

    def config_file(self, filename):
        return os.path.join(self.config_dir(),
                            self.filter_filename(filename))

    def open_text_file(self, path):
        raise NotImplementedError("The base class can't do that")

    def open_html_file(self, path):
        raise NotImplementedError("The base class can't do that")

    def list_serial_ports(self):
        return []

    def default_dir(self):
        return "."

    def gui_open_file(self, start_dir=None, types=[]):
        import gtk

        if not start_dir:
            start_dir = self._last_dir

        dlg = gtk.FileChooserDialog("Select a file to open",
                                    None,
                                    gtk.FILE_CHOOSER_ACTION_OPEN,
                                    (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                     gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        if start_dir and os.path.isdir(start_dir):
            dlg.set_current_folder(start_dir)

        for desc, spec in types:
            ff = gtk.FileFilter()
            ff.set_name(desc)
            ff.add_pattern(spec)
            dlg.add_filter(ff)

        res = dlg.run()
        fname = dlg.get_filename()
        dlg.destroy()

        if res == gtk.RESPONSE_OK:
            self._last_dir = os.path.dirname(fname)
            return fname
        else:
            return None

    def gui_save_file(self, start_dir=None, default_name=None, types=[]):
        import gtk

        if not start_dir:
            start_dir = self._last_dir

        dlg = gtk.FileChooserDialog("Save file as",
                                    None,
                                    gtk.FILE_CHOOSER_ACTION_SAVE,
                                    (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                     gtk.STOCK_SAVE, gtk.RESPONSE_OK))
        if start_dir and os.path.isdir(start_dir):
            dlg.set_current_folder(start_dir)

        if default_name:
            dlg.set_current_name(default_name)

        extensions = {}
        for desc, ext in types:
            ff = gtk.FileFilter()
            ff.set_name(desc)
            ff.add_pattern("*.%s" % ext)
            extensions[desc] = ext
            dlg.add_filter(ff)

        res = dlg.run()

        fname = dlg.get_filename()
        ext = extensions[dlg.get_filter().get_name()]
        if fname and not fname.endswith(".%s" % ext):
            fname = "%s.%s" % (fname, ext)

        dlg.destroy()

        if res == gtk.RESPONSE_OK:
            self._last_dir = os.path.dirname(fname)
            return fname
        else:
            return None

    def gui_select_dir(self, start_dir=None):
        import gtk

        if not start_dir:
            start_dir = self._last_dir

        dlg = gtk.FileChooserDialog("Choose folder",
                                    None,
                                    gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                    (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                     gtk.STOCK_SAVE, gtk.RESPONSE_OK))
        if start_dir and os.path.isdir(start_dir):
            dlg.set_current_folder(start_dir)

        res = dlg.run()
        fname = dlg.get_filename()
        dlg.destroy()

        if res == gtk.RESPONSE_OK and os.path.isdir(fname):
            self._last_dir = fname
            return fname
        else:
            return None

    def os_version_string(self):
        return "Unknown Operating System"

    def executable_path(self):
        def we_are_frozen():
            return hasattr(sys, "frozen")

        if we_are_frozen():
            # Win32, find the directory of the executable
            return os.path.dirname(unicode(sys.executable,
                                           sys.getfilesystemencoding()))
        else:
            # UNIX: Find the parent directory of this module
            return os.path.dirname(os.path.abspath(os.path.join(find_me(), "..")))

def _unix_editor():
    macos_textedit = "/Applications/TextEdit.app/Contents/MacOS/TextEdit"

    if os.path.exists(macos_textedit):
        return macos_textedit
    else:
        return "gedit"

class UnixPlatform(Platform):
    def __init__(self, basepath):
        if not basepath:
            basepath = os.path.abspath(os.path.join(self.default_dir(),
                                                    ".chirp"))
        
        if not os.path.isdir(basepath):
            os.mkdir(basepath)

        Platform.__init__(self, basepath)

	# This is a hack that needs to be properly fixed by importing the
	# latest changes to this module from d-rats.  In the interest of
	# time, however, I'll throw it here
	if sys.platform == "darwin":
            if not os.environ.has_key("DISPLAY"):
                print "Forcing DISPLAY for MacOS"
                os.environ["DISPLAY"] = ":0"

            os.environ["PANGO_RC_FILE"] = "../Resources/etc/pango/pangorc"

    def default_dir(self):
        return os.path.abspath(os.getenv("HOME"))

    def filter_filename(self, filename):
        return filename.replace("/", "")

    def open_text_file(self, path):
        pid1 = os.fork()
        if pid1 == 0:
            pid2 = os.fork()
            if pid2 == 0:
                editor = _unix_editor()
                print "calling `%s %s'" % (editor, path)
                os.execlp(editor, editor, path)
            else:
                sys.exit(0)
        else:
            os.waitpid(pid1, 0)
            print "Exec child exited"

    def open_html_file(self, path):
        os.system("firefox '%s'" % path)

    def list_serial_ports(self):
        return sorted(glob.glob("/dev/ttyS*") +
                      glob.glob("/dev/ttyUSB*") +
                      glob.glob("/dev/cu.*") +
                      glob.glob("/dev/term/*") +
                      glob.glob("/dev/tty.KeySerial*"))

    def os_version_string(self):
        # pylint: disable-msg=W0703
        try:
            issue = file("/etc/issue.net", "r")
            ver = issue.read().strip()
            issue.close()
            ver = "%s - %s" % (os.uname()[0], ver)
        except Exception:
            ver = " ".join(os.uname())

        return ver

class Win32Platform(Platform):
    def __init__(self, basepath=None):
        if not basepath:
            appdata = os.getenv("APPDATA")
            if not appdata:
                appdata = "C:\\"
            basepath = os.path.abspath(os.path.join(appdata, "CHIRP"))

        if not os.path.isdir(basepath):
            os.mkdir(basepath)

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
    
    def list_serial_ports(self):
        return ["COM%i" % x for x in range(1, 8)]

    def gui_open_file(self, start_dir=None, types=[]):
        # pylint: disable-msg=W0703,W0613
        import win32gui

        typestrs = ""
        for desc, spec in types:
            typestrs += "%s\0%s\0" % (desc, spec)
        if not typestrs:
            typestrs = None

        try:
            fname, _, _ = win32gui.GetOpenFileNameW(Filter=typestrs)
        except Exception, e:
            print "Failed to get filename: %s" % e
            return None

        return str(fname)

    def gui_save_file(self, start_dir=None, default_name=None, types=[]):
        # pylint: disable-msg=W0703,W0613
        import win32gui

        typestrs = ""
        custom = "%s\0*.%s\0" % (types[0][0], types[0][1])
        for desc, ext in types[1:]:
            typestrs += "%s\0%s\0" % (desc, "*.%s" % ext)
        if not typestrs:
            typestrs = custom
            custom = None

        def_ext = "*.%s" % types[0][1]
        try:
            fname, filter, _ = win32gui.GetSaveFileNameW(File=default_name,
                                                         CustomFilter=custom,
                                                         DefExt=def_ext,
                                                         Filter=typestrs)
        except Exception, e:
            print "Failed to get filename: %s" % e
            return None

        return str(fname)

    def gui_select_dir(self, start_dir=None):
        # pylint: disable-msg=W0703,W0613
        from win32com.shell import shell

        try:
            pidl, _, _ = shell.SHBrowseForFolder()
            fname = shell.SHGetPathFromIDList(pidl)
        except Exception, e:
            print "Failed to get directory: %s" % e
            return None

        return str(fname)

    def os_version_string(self):
        import win32api

        vers = { 4: "Win2k",
                 5: "WinXP",
                 }

        (pform, _, build, _, _) = win32api.GetVersionEx()

        return vers.get(pform, "Win32 (Unknown %i:%i)" % (pform, build))

def _get_platform(basepath):
    if os.name == "nt":
        return Win32Platform(basepath)
    else:
        return UnixPlatform(basepath)

PLATFORM = None
def get_platform(basepath=None):
    #pylint: disable-msg=W0602

    global PLATFORM

    if not PLATFORM:
        PLATFORM = _get_platform(basepath)

    return PLATFORM

if __name__ == "__main__":
    def do_test():
        __pform = get_platform()

        print "Config dir: %s" % __pform.config_dir()
        print "Default dir: %s" % __pform.default_dir()
        print "Log file (foo): %s" % __pform.log_file("foo")
        print "Serial ports: %s" % __pform.list_serial_ports()
        print "OS Version: %s" % __pform.os_version_string()
        #__pform.open_text_file("d-rats.py")

        #print "Open file: %s" % __pform.gui_open_file()
        #print "Save file: %s" % __pform.gui_save_file(default_name="Foo.txt")
        print "Open folder: %s" % __pform.gui_select_dir("/tmp")

    do_test()
