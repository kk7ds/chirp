#!/usr/bin/env python3

import argparse
import collections
import functools
import gettext
import logging
import os
import sys

import wx
import wx.aui
import wx.grid
import wx.lib.newevent

from chirp import chirp_common
from chirp.drivers import ic2820, generic_csv
from chirp import directory
from chirp import logger

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
    logger.add_arguments(parser)
    args = parser.parse_args()

    logger.handle_options(args)

    directory.safe_import_drivers(limit=args.onlydriver)

    #logging.basicConfig(level=logging.DEBUG)
    app = wx.App()
    mainwindow = main.ChirpMain(None, title='CHIRP')
    mainwindow.Show()
    for fn in args.files:
        mainwindow.open_file(fn, select=False)

    if args.inspect:
        import wx.lib.inspection
        wx.lib.inspection.InspectionTool().Show()

    app.MainLoop()
