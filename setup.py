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

from distutils.core import setup
import py2exe
import sys

try:
    # if this doesn't work, try import modulefinder
    import py2exe.mf as modulefinder
    import win32com
    for p in win32com.__path__[1:]:
        modulefinder.AddPackagePath("win32com", p)
    for extra in ["win32com.shell"]: #,"win32com.mapi"
        __import__(extra)
        m = sys.modules[extra]
        for p in m.__path__[1:]:
            modulefinder.AddPackagePath(extra, p)
except ImportError:
    # no build path setup, no worries.
    pass


opts = {
    "py2exe" : {
        "includes" : "pango,atk,gobject,cairo,pangocairo,win32gui,win32com,win32com.shell",
        "compressed" : 1,
        "optimize" : 2,
        "bundle_files" : 3,
#        "packages" : ""
        }
    }

setup(
    windows=[{'script' : "csvdump.py",
              'icon_resources' : [(0x0004, 'csvdump.ico')]},
             {'script' : "chirpw.py"}],
    console=[{'script' : "chirp.py"}],
    options=opts)
