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
    windows=[{'script' : "csvdump.py"}],
    console=[{'script' : "chirp.py"}],
    options=opts)
