#!/usr/bin/env python3

import argparse
import gettext
import os
import sys

import wx
import wx.aui
import wx.grid
import wx.lib.newevent

# Import the drivers module before directory for frozen builds
from chirp import drivers

from chirp import directory
from chirp import logger

from chirp.ui import config
from chirp.wxui import main


if __name__ == '__main__':
    gettext.install('CHIRP')
    parser = argparse.ArgumentParser()
    parser.add_argument("files", metavar="file", nargs='*',
                        help="File to open")
    parser.add_argument("--module", metavar="module",
                        help="Load module on startup")
    logger.add_version_argument(parser)
    parser.add_argument("--profile", action="store_true",
                        help="Enable profiling")
    parser.add_argument("--onlydriver", nargs="+",
                        help="Include this driver while loading")
    parser.add_argument("--inspect", action="store_true",
                        help="Show wxPython inspector")
    if sys.platform == 'linux':
        parser.add_argument('--no-linux-gdk-backend', action='store_true',
                            help='Do not force GDK_BACKEND=x11')
    logger.add_arguments(parser)
    args = parser.parse_args()

    logger.handle_options(args)

    directory.safe_import_drivers(limit=args.onlydriver)

    CONF = config.get()
    if CONF.get('developer', 'state'):
        from chirp.drivers import fake
        fake.register_fakes()

    # wxGTK on Wayland seems to have problems. Override GDK_BACKEND to
    # use X11, unless we were asked not to
    if sys.platform == 'linux' and not args.no_linux_gdk_backend:
        os.putenv('GDK_BACKEND', 'x11')

    app = wx.App()
    mainwindow = main.ChirpMain(None, title='CHIRP')
    mainwindow.Show()
    for fn in args.files:
        mainwindow.open_file(fn, select=False)

    if args.inspect:
        import wx.lib.inspection
        wx.lib.inspection.InspectionTool().Show()

    app.MainLoop()
