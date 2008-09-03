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

class Platform:
    def __init__(self, basepath):
        self._base = basepath

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

    def gui_open_file(self, start_dir=None):
        import gtk

        dlg = gtk.FileChooserDialog("Select a file to open",
                                    None,
                                    gtk.FILE_CHOOSER_ACTION_OPEN,
                                    (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                     gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        if start_dir and os.path.isdir(start_dir):
            dlg.set_current_folder(start_dir)

        res = dlg.run()
        fname = dlg.get_filename()
        dlg.destroy()

        if res == gtk.RESPONSE_OK:
            return fname
        else:
            return None

    def gui_save_file(self, start_dir=None, default_name=None):
        import gtk

        dlg = gtk.FileChooserDialog("Save file as",
                                    None,
                                    gtk.FILE_CHOOSER_ACTION_SAVE,
                                    (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                     gtk.STOCK_SAVE, gtk.RESPONSE_OK))
        if start_dir and os.path.isdir(start_dir):
            dlg.set_current_folder(start_dir)

        if default_name:
            dlg.set_current_name(default_name)

        res = dlg.run()
        fname = dlg.get_filename()
        dlg.destroy()

        if res == gtk.RESPONSE_OK:
            return fname
        else:
            return None

    def gui_select_dir(self, start_dir=None):
        import gtk

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
            return fname
        else:
            return None

    def os_version_string(self):
        return "Unknown Operating System"

class UnixPlatform(Platform):
    def __init__(self, basepath):
        if not basepath:
            basepath = os.path.abspath(os.path.join(self.default_dir(),
                                                    ".d-rats"))
        
        if not os.path.isdir(basepath):
            os.mkdir(basepath)

        Platform.__init__(self, basepath)

    def default_dir(self):
        return os.path.abspath(os.getenv("HOME"))

    def filter_filename(self, filename):
        return filename.replace("/", "")

    def _editor(self):
        macos_textedit = "/Applications/TextEdit.app/Contents/MacOS/TextEdit"

        if os.path.exists(macos_textedit):
            return macos_textedit
        else:
            return "gedit"

    def open_text_file(self, path):
        pid1 = os.fork()
        if pid1 == 0:
            pid2 = os.fork()
            if pid2 == 0:
                editor = self._editor()
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
        return sorted(glob.glob("/dev/ttyS*") + glob.glob("/dev/ttyUSB*"))

    def os_version_string(self):
        try:
            issue = file("/etc/issue.net", "r")
            ver = issue.read().strip()
            issue.close()
            ver = "%s - %s" % (os.uname()[0], ver)
        except Exception, e:
            ver = " ".join(os.uname())

        return ver

class Win32Platform(Platform):
    def __init__(self, basepath=None):
        if not basepath:
            basepath = os.path.abspath(os.path.join(os.getenv("APPDATA"),
                                                    "D-RATS"))

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

    def gui_open_file(self, start_dir=None):
        import win32gui

        try:
            fname, _, _ = win32gui.GetOpenFileNameW()
        except Exception, e:
            print "Failed to get filename: %s" % e
            return None

        return str(fname)

    def gui_save_file(self, start_dir=None, default_name=None):
        import win32gui

        try:
            fname, _, _ = win32gui.GetSaveFileNameW(File=default_name)
        except Exception, e:
            print "Failed to get filename: %s" % e
            return None

        return str(fname)

    def gui_select_dir(self, start_dir=None):
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
