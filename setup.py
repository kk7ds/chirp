from __future__ import print_function

import sys
import glob
import os

from chirp import CHIRP_VERSION
import chirp
from chirp import directory

directory.safe_import_drivers()


def staticify_chirp_module():
    import chirp

    with open("chirp/__init__.py", "w") as init:
        print("CHIRP_VERSION = \"%s\"" % CHIRP_VERSION, file=init)
        print("__all__ = %s\n" % str(chirp.__all__), file=init)

    print("Set chirp/__init__.py::__all__ = %s" % str(chirp.__all__))


def staticify_drivers_module():
    import chirp.drivers

    with file("chirp/drivers/__init__.py", "w") as init:
        print("__all__ = %s\n" % str(chirp.drivers.__all__), file=init)

    print("Set chirp/drivers/__init__.py::__all__ = %s" % str(
        chirp.drivers.__all__))


def win32_build():
    from distutils.core import setup
    import py2exe

    try:
        # if this doesn't work, try import modulefinder
        import py2exe.mf as modulefinder
        import win32com
        for p in win32com.__path__[1:]:
            modulefinder.AddPackagePath("win32com", p)
        for extra in ["win32com.shell"]:  # ,"win32com.mapi"
            __import__(extra)
            m = sys.modules[extra]
            for p in m.__path__[1:]:
                modulefinder.AddPackagePath(extra, p)
    except ImportError:
        # no build path setup, no worries.
        pass

    staticify_chirp_module()
    staticify_drivers_module()

    opts = {
        "py2exe": {
            "includes": "pango,atk,gobject,cairo,pangocairo," +
                        "win32gui,win32com,win32com.shell," +
                        "email.iterators,email.generator,gio",

            "compressed": 1,
            "optimize": 2,
            "bundle_files": 3,
            # "packages": ""
            }
        }

    mods = []
    for mod in chirp.__all__:
        mods.append("chirp.%s" % mod)
    for mod in chirp.drivers.__all__:
        mods.append("chirp.drivers.%s" % mod)
    opts["py2exe"]["includes"] += ("," + ",".join(mods))

    setup(
        zipfile=None,
        windows=[{'script':         "chirpw",
                  'icon_resources': [(0x0004, 'share/chirp.ico')],
                  }],
        options=opts)


def macos_build():
    from setuptools import setup
    import shutil

    APP = ['chirp-%s.py' % CHIRP_VERSION]
    shutil.copy("chirpw", APP[0])
    DATA_FILES = [('../Frameworks', ['/opt/local/lib/libpangox-1.0.dylib']),
                  ('../Resources/', ['/opt/local/lib/pango']),
                  ]
    OPTIONS = {'argv_emulation': True, "includes": "gtk,atk,pangocairo,cairo"}

    setup(
        app=APP,
        data_files=DATA_FILES,
        options={'py2app': OPTIONS},
        setup_requires=['py2app'],
        )

    EXEC = 'bash ./build/macos/make_pango.sh ' + \
           '/opt/local dist/chirp-%s.app' % CHIRP_VERSION
    # print "exec string: %s" % EXEC
    os.system(EXEC)


def default_build():
    from distutils.core import setup
    from glob import glob

    os.system("make -C locale clean all")

    desktop_files = glob("share/*.desktop")
    # form_files = glob("forms/*.x?l")
    image_files = glob("images/*")
    _locale_files = glob("locale/*/LC_MESSAGES/CHIRP.mo")
    stock_configs = glob("stock_configs/*")

    locale_files = []
    for f in _locale_files:
        locale_files.append(("share/chirp/%s" % os.path.dirname(f), [f]))

    print("LOC: %s" % str(locale_files))

    xsd_files = glob("chirp*.xsd")

    setup(
        name="chirp",
        packages=["chirp", "chirp.drivers", "chirp.ui", "tests", "tests.unit",
                  "chirp.wxui"],
        version=CHIRP_VERSION,
        scripts=["chirpw", "rpttool", "chirpwx.py"],
        data_files=[('share/applications', desktop_files),
                    ('share/chirp/images', image_files),
                    ('share/chirp', xsd_files),
                    ('share/doc/chirp', ['COPYING']),
                    ('share/pixmaps', ['share/chirp.png']),
                    ('share/man/man1', ["share/chirpw.1"]),
                    ('share/chirp/stock_configs', stock_configs),
                    ] + locale_files)


def nuke_manifest(*files):
    for i in ["MANIFEST", "MANIFEST.in"]:
        if os.path.exists(i):
            os.remove(i)

    if not files:
        return

    f = file("MANIFEST.in", "w")
    for fn in files:
        print(fn, file=f)
    f.close()


if sys.platform == "darwin":
    macos_build()
elif sys.platform == "win32":
    win32_build()
else:
    default_build()
